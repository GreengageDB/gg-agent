#!/usr/bin/env python3
"""Prepare a batch of upstream PostgreSQL commits on greengage_sync for review.

The batch flow (skill greengage-pg-batch) merges a slice of upstream history into a
Greengage branch, brings it up on a "raw" branch, then rebuilds the branch for review:
the batch merge first (conflict markers committed), then one commit per unit of
change (UoC) holding that unit's conflict resolutions and fixes.

    BASE (e.g. next) --merge--> DIRTY (markers committed) --> ... --> RAW (CI green)
    review branch:  BASE --> MERGE (tree of DIRTY) --> UoC 1 --> ... --> UoC N (tree of RAW)

Subcommands, in the order the flow uses them:

    select     pick the upstream commits of the batch and check the cut for split revert pairs
    inventory  replay the merge and sort every conflict hunk into AUTO / REGEN / RESOLVE
    facts      collect per-file facts once RAW is green
    assign     group the changed files into units of change from a topics file
    classify   give each unit a review status: MUST REVIEW / NO REVIEW / MERGE AUTOMATICALLY
    series     build the review branch from DIRTY and RAW
    verify     prove the review branch reproduces RAW, unit by unit
    render     write the pull request description

Usage:
    pg_batch.py [-C REPO] select --source next --upstream REF (--count N | --until REV | --before DATE)
                         [--lookahead 300] [--out batch.json]
    pg_batch.py [-C REPO] inventory OURS THEIRS [--json inv.json] [--apply WORKTREE] [--blame]
    pg_batch.py [-C REPO] facts BASE CUT DIRTY RAW --inventory inv.json --out facts.json
    pg_batch.py [-C REPO] assign facts.json topics.json --out uocs.json [--notes DIR]
    pg_batch.py [-C REPO] classify facts.json uocs.json --out tiers.json
    pg_batch.py [-C REPO] series facts.json uocs.json tiers.json --worktree WT --branch B
                         --out series.json [--pr-branch NAME] [--merge-message-file F]
    pg_batch.py [-C REPO] verify facts.json series.json
    pg_batch.py [-C REPO] render facts.json uocs.json tiers.json series.json --sections sections.md
                         --repo OWNER/REPO --out body.md [--inventory inv.json] [--raw-branch B]

REPO defaults to the current directory and must be the greengage_sync checkout.
The git subcommands need git >= 2.38 (merge-tree --write-tree).

topics.json (input of assign):
    {"topics": [{"slug": "memoize-rename", "title": "Result Cache renamed to Memoize",
                 "summary": "one paragraph for the PR table",
                 "commits": ["83f4fcc6550"],                 # upstream commits that define the unit
                 "paths": ["src/backend/executor/nodeMemoize.c", "re:^src/test/regress/.*memoize"],
                 "aliases": ["memoize"],                     # other UoC: trailer values meaning this unit
                 "notes": ["adaptation bullet for the commit message"]}],
     "module_buckets": [["re:^src/backend/regex/", "regex", "Regular expressions"], ["re:.", "misc", "Other"]]}

Exit status: 0 clean; 1 findings (select: the cut splits a revert pair; verify: the review
branch does not reproduce RAW; render: the body is over GitHub's limit); 2 usage or
environment error.
"""
import argparse
import difflib
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, OrderedDict, defaultdict

REPO = None
BODY_LIMIT = 65536
TIER_ORDER = {'MUST REVIEW': 0, 'NO REVIEW': 1, 'MERGE AUTOMATICALLY': 2}
TIER_LABEL = {'MUST REVIEW': '🔴 must review', 'NO REVIEW': '🟢 no review',
              'MERGE AUTOMATICALLY': '⚪ merge automatically'}


class Refuse(Exception):
    """A usage or environment problem: exit 2 with a remediation."""


# ------------------------------------------------------------------ git plumbing
def git(*args, ok=(0,), inp=None, env=None):
    cmd = ['git'] + (['-C', REPO] if REPO else []) + list(args)
    e = dict(os.environ, **env) if env else None
    r = subprocess.run(cmd, capture_output=True, input=inp.encode() if inp is not None else None, env=e)
    if r.returncode not in ok:
        raise Refuse('git %s failed (%d): %s' % (' '.join(args[:3]), r.returncode,
                                                  r.stderr.decode(errors='replace').strip()[:600]))
    return r.stdout.decode('utf-8', errors='replace')


def git_wt(wt, *args, inp=None, env=None):
    global REPO
    saved, REPO = REPO, wt
    try:
        return git(*args, inp=inp, env=env)
    finally:
        REPO = saved


def rev(x):
    return git('rev-parse', '--verify', '--quiet', x + '^{commit}').strip() or None


_cat = None


def blob(spec):
    """file content at 'rev:path' as text, None if missing or binary"""
    global _cat
    if _cat is None:
        _cat = subprocess.Popen(['git'] + (['-C', REPO] if REPO else []) + ['cat-file', '--batch'],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    _cat.stdin.write((spec + '\n').encode())
    _cat.stdin.flush()
    hdr = _cat.stdout.readline().decode()
    if hdr.endswith('missing\n'):
        return None
    data = _cat.stdout.read(int(hdr.split()[2]))
    _cat.stdout.read(1)
    if b'\0' in data[:8000]:
        return None
    return data.decode('utf-8', errors='replace')


def numstat(a, b, paths=()):
    d = {}
    for ln in git('diff', '--numstat', '--no-renames', a, b, '--', *paths).splitlines():
        x, y, p = ln.split('\t', 2)
        d[p] = (0 if x == '-' else int(x)) + (0 if y == '-' else int(y))
    return d


def name_status(a, b):
    out = []
    for ln in git('diff-tree', '-r', '--no-renames', '--name-status', a, b).splitlines():
        st, p = ln.split('\t', 1)
        out.append((st[0], p))
    return out


def marked_files(r):
    """files at revision r that hold a conflict-marker line"""
    out = git('grep', '-l', '-I', '-e', '^<<<<<<< ', r, ok=(0, 1))
    return set(ln.split(':', 1)[1] for ln in out.splitlines() if ln)


def short(h):
    return h[:11]


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except OSError as e:
        raise Refuse('cannot read %s: %s' % (path, e.strerror))


def dump(obj, path):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=1)


def file_kind(p):
    if re.search(r'(^|/)configure$', p):
        return 'generated'
    if re.search(r'/expected/|/output/.*\.source$|\.out$', p):
        return 'test_expected'
    if re.search(r'/sql/|/input/.*\.source$|\.sql$|\.spec$|/t/.*\.pl$', p):
        return 'test_input'
    if p.endswith('.po'):
        return 'translation'
    if p.startswith('doc/') or p.endswith('.sgml'):
        return 'doc'
    return 'code'


# ------------------------------------------------------------------ 3-way helpers
def merge_file(base, ours, theirs):
    with tempfile.TemporaryDirectory() as d:
        fs = []
        for n, t in (('o', ours), ('b', base), ('t', theirs)):
            p = os.path.join(d, n)
            with open(p, 'w') as f:
                f.write(t)
            fs.append(p)
        r = subprocess.run(['git', 'merge-file', '-p', '--diff3', '-L', 'ours', '-L', 'base', '-L', 'theirs'] + fs,
                           capture_output=True)
        return r.returncode, r.stdout.decode('utf-8', errors='replace')


def token_merge(base, ours, theirs):
    """word-level 3-way merge; None if it still conflicts"""
    esc = lambda t: t.replace('\\', '\\\\').replace('\n', '\\n')
    tok = lambda s: ''.join(esc(t) + '\n' for t in re.findall(r'\s+|\w+|[^\w\s]', s))
    rc, out = merge_file(tok(base), tok(ours), tok(theirs))
    if rc != 0:
        return None
    return ''.join(re.sub(r'\\(.)', lambda m: '\n' if m.group(1) == 'n' else m.group(1), t)
                   for t in out.split('\n')[:-1])


def parse_marked(s):
    """diff3 output -> [('c', lines) | ('h', ours, base, theirs)]"""
    segs, cur, state, o, b, t = [], [], 'c', None, None, None
    for ln in s.splitlines(keepends=True):
        if state == 'c' and ln.startswith('<<<<<<< ours'):
            segs.append(('c', cur))
            cur, o, b, t, state = [], [], [], [], 'o'
            continue
        if state == 'o' and ln.startswith('||||||| base'):
            state = 'b'
            continue
        if state in ('o', 'b') and ln.rstrip('\n') == '=======':
            state = 't'
            continue
        if state == 't' and ln.startswith('>>>>>>> theirs'):
            segs.append(('h', o, b, t))
            state = 'c'
            continue
        {'c': cur, 'o': o, 'b': b, 't': t}[state].append(ln)
    segs.append(('c', cur))
    return segs


def align(segs, lines):
    """hunk index -> (lines that replaced it or None, j1, j2) in `lines`"""
    skel, hidx = [], []
    for s in segs:
        if s[0] == 'c':
            skel.extend(s[1])
        else:
            hidx.append(len(skel))
            skel.append('\0HUNK%d\0\n' % len(hidx))
    out = {}
    for _, i1, i2, j1, j2 in difflib.SequenceMatcher(None, skel, lines, autojunk=False).get_opcodes():
        hs = [k for k, pos in enumerate(hidx) if i1 <= pos < i2]
        for k in hs:
            out[k] = (lines[j1:j2] if len(hs) == 1 else None, j1, j2)
    return out


WS = re.compile(r'\s+')


def norm(s):
    return WS.sub('', s if isinstance(s, str) else ''.join(s))


# ------------------------------------------------------------------ select
REVERT_HASH = re.compile(r'This reverts commit ([0-9a-f]{7,40})')
REVERT_SUBJ = re.compile(r'^Revert "(.+)"\s*$')
HASHLIKE = re.compile(r'\b[0-9a-f]{7,40}\b')


def cmd_select(a):
    src, up = rev(a.source), rev(a.upstream)
    if not src or not up:
        raise Refuse('cannot resolve %s; fetch the source branch and the upstream PostgreSQL '
                     'remote first (git fetch origin; git fetch pg)' % (a.source if not src else a.upstream))
    mbase = git('merge-base', src, up).strip()
    if not mbase:
        raise Refuse('%s and %s share no history; --upstream must be PostgreSQL history' % (a.source, a.upstream))
    commits = git('rev-list', '--reverse', '--first-parent', mbase + '..' + up).split()
    if not commits:
        raise Refuse('%s already contains %s: nothing left to merge' % (a.source, a.upstream))
    if a.count:
        idx = min(a.count, len(commits)) - 1
    elif a.until:
        u = rev(a.until)
        if u not in commits:
            raise Refuse('%s is not on the first-parent line %s..%s' % (a.until, short(mbase), a.upstream))
        idx = commits.index(u)
    else:
        dates = git('log', '--reverse', '--first-parent', '--format=%cI', mbase + '..' + up).split()
        idx = max((i for i, d in enumerate(dates) if d[:10] < a.before), default=-1)
        if idx < 0:
            raise Refuse('no upstream commit before %s after the merge base %s' % (a.before, short(mbase)))
    end = min(len(commits), idx + 1 + a.lookahead)
    info = OrderedDict()
    log = git('log', '--reverse', '--first-parent', '--format=%x00%H%x01%cs%x01%s%x01%b',
              mbase + '..' + commits[end - 1])
    for blk in log.split('\0')[1:]:
        h, d, s, b = blk.split('\x01', 3)
        info[h] = dict(date=d, subject=s, body=b)
    pos = {h: i for i, h in enumerate(commits[:end])}
    by_subject = {}
    for h in commits[:end]:
        by_subject.setdefault(info[h]['subject'], h)

    def reverted(h):
        out = []
        for m in REVERT_HASH.finditer(info[h]['body']):
            out += [c for c in commits[:end] if c.startswith(m.group(1))]
        m = REVERT_SUBJ.match(info[h]['subject'])
        if m and m.group(1) in by_subject:
            out.append(by_subject[m.group(1)])
        return sorted(set(x for x in out if pos[x] < pos[h]), key=pos.get)

    def split_pairs(cut_idx):
        return [(x, r) for r in commits[cut_idx + 1:end] for x in reverted(r) if pos[x] <= cut_idx]

    pairs = split_pairs(idx)
    closing = idx
    for _ in range(10):                      # extend until no pair inside the window is split
        sp = split_pairs(closing)
        if not sp:
            break
        closing = max(pos[r] for _, r in sp)
    earlier = min((pos[x] for x, _ in pairs), default=idx + 1) - 1
    prefixes = defaultdict(list)
    for h in commits[:idx + 1]:
        prefixes[h[:7]].append(h)
    follow = []
    for h in commits[idx + 1:end]:
        refs = sorted(set(c for m in HASHLIKE.finditer(info[h]['body'])
                          for c in prefixes.get(m.group(0)[:7], []) if c.startswith(m.group(0))))
        if refs and not reverted(h):
            follow.append(dict(commit=short(h), subject=info[h]['subject'], follows=[short(c) for c in refs]))

    row = lambda h: dict(commit=short(h), date=info[h]['date'], subject=info[h]['subject'])
    out = dict(source=a.source, source_sha=src, upstream=a.upstream, upstream_sha=up, mbase=mbase,
               cut=commits[idx], count=idx + 1, remaining=len(commits) - idx - 1,
               commits=[row(h) for h in commits[:idx + 1]],
               split_revert_pairs=[dict(commit=row(x), reverted_by=row(r)) for x, r in pairs],
               closing_cut=None if closing == idx else dict(row(commits[closing]), count=closing + 1),
               earlier_cut=None if not pairs or earlier < 0 else dict(row(commits[earlier]), count=earlier + 1),
               followups_after_cut=follow[:40])
    if a.out:
        dump(out, a.out)
    print('merge base %s (%s), upstream %s: %d commits left' % (short(mbase), a.source, a.upstream, len(commits)))
    print('batch: %d commits, %s %s .. %s %s' % (idx + 1, out['commits'][0]['date'], out['commits'][0]['commit'],
                                                  info[commits[idx]]['date'], short(commits[idx])))
    print('cut:   %s %s' % (short(commits[idx]), info[commits[idx]]['subject']))
    print('\naround the cut:')
    for i in range(max(0, idx - 4), min(end, idx + 6)):
        print('  %s %4d %s %s %s' % ('>' if i == idx else ' ', i + 1, short(commits[i]), info[commits[i]]['date'],
                                    info[commits[i]]['subject'][:90]))
    if pairs:
        print('\nSPLIT REVERT PAIRS (the batch has the commit, the revert lies after the cut):')
        for x, r in pairs:
            print('  %s %s\n     reverted by %s (+%d) %s' % (short(x), info[x]['subject'][:80], short(r),
                                                          pos[r] - idx, info[r]['subject'][:80]))
        if out['closing_cut']:
            c = out['closing_cut']
            print('  closing cut: %s (%d commits) %s' % (c['commit'], c['count'], c['subject'][:80]))
        if out['earlier_cut']:
            c = out['earlier_cut']
            print('  earlier cut: %s (%d commits) %s' % (c['commit'], c['count'], c['subject'][:80]))
    if follow:
        print('\nfollow-ups after the cut that cite batch commits (first %d of %d):' % (min(10, len(follow)), len(follow)))
        for f in follow[:10]:
            print('  %s %s  <- %s' % (f['commit'], f['subject'][:80], ' '.join(f['follows'])))
    return 1 if pairs else 0


# ------------------------------------------------------------------ inventory
def conflicts(ours, theirs):
    raw = git('merge-tree', '--write-tree', ours, theirs, ok=(0, 1))
    head = raw.partition('\n\n')[0]
    stages = defaultdict(dict)
    for ln in head.splitlines()[1:]:
        meta, path = ln.split('\t', 1)
        _, oid, st = meta.split()
        stages[path][int(st)] = oid
    return stages


COPYRIGHT = re.compile(r'Copyright|IDENTIFICATION|\$PostgreSQL|\$Header', re.I)


def classify_hunk(path, ho, hb, ht):
    """pre-resolution tier of one hunk -> (tier, rule, auto text or suggestion)"""
    kind = file_kind(path)
    o, b, t = ''.join(ho), ''.join(hb), ''.join(ht)
    tokm = token_merge(b, o, t)
    if kind in ('doc', 'translation'):
        return 'AUTO', 'doc/translation: take upstream', t
    if kind == 'generated':
        return 'REGEN', 'generated file: resolve its source (configure.ac) and regenerate', None
    if tokm is not None and COPYRIGHT.search(o + t):
        return 'AUTO', 'copyright/header: word-level merge', tokm
    if norm(o) == norm(b):
        return 'AUTO', 'greengage side is whitespace-only: take upstream', t
    if norm(t) == norm(b):
        return 'AUTO', 'upstream side is whitespace-only (pgindent): keep ours', o
    if kind == 'test_expected':
        return 'REGEN', 'expected output: regenerate after the build, through the answer-file gate', None
    return 'RESOLVE', 'word-level merge is clean' if tokm else 'needs a resolution', tokm


def day1_rank(base, theirs, delta, top=15):
    """upstream commits that change Greengage-heavy files the most"""
    rows = []
    for blk in git('log', '--no-merges', '--numstat', '--format=@@%h %s', base + '..' + theirs).split('@@')[1:]:
        lines = blk.strip().splitlines()
        score, files = 0, []
        for ln in lines[1:]:
            m = ln.split('\t')
            if len(m) != 3 or m[0] == '-' or file_kind(m[2]) in ('translation', 'doc', 'test_expected'):
                continue
            ch, g = int(m[0]) + int(m[1]), delta.get(m[2], 0)
            if g >= 100 and ch >= 20:
                score += min(ch, g)
                files.append(m[2])
        if score:
            rows.append(dict(score=score, commit=lines[0], files=files))
    rows.sort(key=lambda r: -r['score'])
    return rows[:top]


def blame_commits(theirs, base, path, text):
    full = blob('%s:%s' % (theirs, path))
    if not full or not text.strip() or full.find(text) < 0:
        return []
    start = full.count('\n', 0, full.find(text)) + 1
    end = start + max(text.count('\n'), 1) - 1
    shas = []
    for ln in git('blame', '-s', '-l', '-L', '%d,%d' % (start, end), base + '..' + theirs, '--', path).splitlines():
        s = ln.split()[0].lstrip('^')
        if not ln.startswith('^') and s not in shas:
            shas.append(s)
    return [git('log', '-1', '--format=%h %s', s).strip() for s in shas[:5]]


def cmd_inventory(a):
    base = git('merge-base', a.ours, a.theirs).strip()
    delta = numstat(base, a.ours)
    rep = dict(ours=a.ours, theirs=a.theirs, base=base, files=[], must_review=[], day1_commits=[])
    tiers = Counter()
    for path, s in sorted(conflicts(a.ours, a.theirs).items()):
        f = dict(path=path, stages=sorted(s), gg_delta_lines=delta.get(path, 0))
        if sorted(s) == [1, 3]:
            f.update(tier='AUTO', rule='Greengage deleted the file: keep it deleted')
        elif sorted(s) == [1, 2] and file_kind(path) != 'code':
            f.update(tier='REGEN', rule='upstream deleted a test file Greengage modifies: carry the coverage over if still wanted')
        elif sorted(s) == [1, 2]:
            f.update(tier='REVIEW', rule='upstream deleted/moved a file Greengage modifies: re-graft the Greengage delta')
            rep['must_review'].append(dict(path=path, why=f['rule']))
        elif sorted(s) != [1, 2, 3]:
            f.update(tier='RESOLVE', rule='add/add: read both sides')
        else:
            b, o, t = (blob(s[i]) for i in (1, 2, 3))
            if None in (b, o, t):
                f.update(tier='RESOLVE', rule='binary')
            else:
                segs = parse_marked(merge_file(b, o, t)[1])
                hs, texts = [], []
                for k, (_, ho, hb, ht) in enumerate(x for x in segs if x[0] == 'h'):
                    tier, rule, text = classify_hunk(path, ho, hb, ht)
                    h = dict(idx=k, tier=tier, rule=rule, ours_lines=len(ho), upstream_lines=len(ht))
                    if tier == 'RESOLVE':
                        h['suggestion'] = text
                        if a.blame:
                            h['upstream_commits'] = blame_commits(a.theirs, base, path, ''.join(ht))
                    hs.append(h)
                    texts.append(text)
                    tiers['hunk_' + tier] += 1
                f['hunks'] = hs
                order = ['AUTO', 'REGEN', 'RESOLVE']
                f['tier'] = max((h['tier'] for h in hs), key=order.index) if hs else 'RESOLVE'
                if not hs:
                    f['rule'] = 'git reports a conflict a plain 3-way merge does not reproduce (rename/mode): check by hand'
                if f['tier'] == 'AUTO':
                    out, n = [], 0
                    for sg in segs:
                        if sg[0] == 'c':
                            out.extend(sg[1])
                        else:
                            out.append(texts[n])
                            n += 1
                    f['auto_content'] = ''.join(out)
        tiers['file_' + f['tier']] += 1
        rep['files'].append(f)
    rep['day1_commits'] = day1_rank(base, a.theirs, delta)
    rep['summary'] = dict(tiers)
    if a.apply:
        applied = 0
        for f in rep['files']:
            if f['tier'] != 'AUTO':
                continue
            p = os.path.join(a.apply, f['path'])
            if f['stages'] == [1, 3]:
                if os.path.exists(p):
                    git_wt(a.apply, 'rm', '-q', '--', f['path'])
                    applied += 1
            elif 'auto_content' in f:
                with open(p, 'w') as fh:
                    fh.write(f['auto_content'])
                git_wt(a.apply, 'add', '--', f['path'])
                applied += 1
        rep['applied'] = applied
    for f in rep['files']:
        f.pop('auto_content', None)
    if a.json:
        dump(rep, a.json)
    s = rep['summary']
    print('# Conflict inventory %s <- %s (merge base %s)\n' % (a.ours, a.theirs, short(base)))
    print('files: ' + ', '.join('%s %d' % (k[5:], v) for k, v in sorted(s.items()) if k.startswith('file_')))
    print('hunks: ' + ', '.join('%s %d' % (k[5:], v) for k, v in sorted(s.items()) if k.startswith('hunk_')))
    if 'applied' in rep:
        print('applied AUTO resolutions to %d files' % rep['applied'])
    print('\n## Must review whatever the resolution looks like (R2)\n')
    for m in rep['must_review']:
        print('- %s: %s' % (m['path'], m['why']))
    print('\n## Day-1 list: upstream commits that overlap Greengage-heavy files most (R1)\n')
    for r in rep['day1_commits']:
        print('- %6d  %s  (%s)' % (r['score'], r['commit'][:80], ', '.join(os.path.basename(x) for x in r['files'][:6])))
    print('\n## Files that still need a resolution (hunks, Greengage delta lines)\n')
    for f in sorted((f for f in rep['files'] if f['tier'] == 'RESOLVE'), key=lambda f: -f['gg_delta_lines']):
        n = sum(1 for h in f.get('hunks', []) if h['tier'] == 'RESOLVE')
        sug = sum(1 for h in f.get('hunks', []) if h.get('suggestion'))
        print('- %-60s %2d hunks (%d with a clean word-level merge), Greengage delta %d'
              % (f['path'], n, sug, f['gg_delta_lines']))
    return 0


# ------------------------------------------------------------------ facts
TRAILER = re.compile(r'^(UoC|Upstream|Kind|Backport):\s*(.+)$', re.M | re.I)


def cmd_facts(a):
    base, cut, dirty, raw = (rev(x) for x in (a.base, a.cut, a.dirty, a.raw))
    for name, v in zip(('BASE', 'CUT', 'DIRTY', 'RAW'), (base, cut, dirty, raw)):
        if not v:
            raise Refuse('cannot resolve %s; run from the greengage_sync checkout (or pass -C)' % name)
    if git('log', '-1', '--format=%P', dirty).split() != [base, cut]:
        raise Refuse('DIRTY must be the merge commit with parents BASE and CUT, in that order')
    if subprocess.run(['git'] + (['-C', REPO] if REPO else []) + ['merge-base', '--is-ancestor', dirty, raw]).returncode:
        raise Refuse('RAW must descend from DIRTY')
    mbase = git('merge-base', base, cut).strip()
    inv = load(a.inventory)
    auto = {f['path'] for f in inv['files'] if f['tier'] == 'AUTO'}
    r2 = {m['path'] for m in inv.get('must_review', [])}
    day1 = [r['commit'].split()[0] for r in inv.get('day1_commits', [])]
    status = dict((p, st) for st, p in name_status(base, raw))
    gg = numstat(mbase, base)
    after_dirty = numstat(dirty, raw)
    conflicted = marked_files(dirty) - marked_files(base)
    up_files, subjects = defaultdict(list), OrderedDict()
    cur = None
    for ln in git('log', '--reverse', '--no-merges', '--no-renames', '--numstat', '--format=@@%H %s',
                  mbase + '..' + cut).splitlines():
        if ln.startswith('@@'):
            h, _, s = ln[2:].partition(' ')
            cur = short(h)
            subjects[cur] = s
            continue
        m = ln.split('\t')
        if len(m) == 3 and cur:
            up_files[m[2]].append([cur, (0 if m[0] == '-' else int(m[0])) + (0 if m[1] == '-' else int(m[1]))])
    bring = []
    for blk in git('log', '--reverse', '--format=%x00%H%x01%s%x01%B', dirty + '..' + raw).split('\0')[1:]:
        h, s, body = blk.split('\x01', 2)
        tr = dict((k.lower(), v.strip()) for k, v in TRAILER.findall(body))
        bring.append(dict(commit=short(h), subject=s, trailers=tr, files=numstat(h + '^', h)))
    files = {}
    for p, st in sorted(status.items()):
        files[p] = dict(status=st, kind=file_kind(p), gg_delta=gg.get(p, 0), conflicted=p in conflicted,
                        auto=p in auto, r2=p in r2, after_dirty=after_dirty.get(p, 0),
                        upstream=up_files.get(p, []), bringup=[b['commit'] for b in bring if p in b['files']])
    dropped = sorted(p for p in up_files if p not in files)
    dump(dict(base=base, cut=cut, dirty=dirty, raw=raw, mbase=mbase, day1=day1, subjects=subjects,
              files=files, dropped_upstream_files=dropped, bringup=bring, marked_in_merge=len(conflicted)), a.out)
    print('files %d (conflicted %d, changed after the merge %d), upstream commits %d, bring-up commits %d, '
          'upstream-only files dropped by Greengage %d' % (
              len(files), sum(f['conflicted'] for f in files.values()),
              sum(1 for f in files.values() if f['after_dirty']), len(subjects), len(bring), len(dropped)))
    return 0


# ------------------------------------------------------------------ assign
def pmatch(pat, path):
    if pat.startswith('re:'):
        return re.search(pat[3:], path) is not None
    return fnmatch.fnmatch(path, pat) or path == pat


def load_notes(d):
    """resolver notes: a '### path' heading followed by a 'UoC: slug' line"""
    slugs = {}
    if not d or not os.path.isdir(d):
        return slugs
    for fn in sorted(os.listdir(d)):
        cur = None
        with open(os.path.join(d, fn)) as f:
            for ln in f:
                m = re.match(r'^#+\s+`?([\w./+-]+)`?\s*$', ln)
                if m and ('/' in m.group(1) or '.' in m.group(1)):
                    cur = m.group(1)
                m2 = re.search(r'(?:UoC|unit[- ]of[- ]change)[^:]*:\s*\**`?([a-z0-9][a-z0-9-]+)`?', ln, re.I)
                if cur and m2 and cur not in slugs:
                    slugs[cur] = m2.group(1).lower()
    return slugs


def cmd_assign(a):
    F, T = load(a.facts), load(a.topics)
    notes = load_notes(a.notes)
    topics = OrderedDict((t['slug'], t) for t in T['topics'])
    alias = {t['slug']: t['slug'] for t in T['topics']}
    for t in T['topics']:
        for x in t.get('aliases', []):
            alias[x] = t['slug']
    commit_topic = {short(c): t['slug'] for t in T['topics'] for c in t.get('commits', [])}
    bring_topic = {}
    for b in F['bringup']:
        s = b['trailers'].get('uoc')
        if s:
            for p in b['files']:
                bring_topic.setdefault(p, Counter())[alias.get(s, s)] += b['files'][p] or 1
    assign, why = {}, {}
    for p, f in F['files'].items():
        slug = w = None
        for t in T['topics']:
            if any(pmatch(x, p) for x in t.get('paths', [])):
                slug, w = t['slug'], 'path'
                break
        if not slug and p in bring_topic and not f['upstream']:
            slug, w = bring_topic[p].most_common(1)[0][0], 'trailer'
        if not slug and p in notes:
            slug, w = alias.get(notes[p], notes[p]), 'note'
        if not slug and f['upstream']:
            byt = Counter()
            for c, n in f['upstream']:
                if c in commit_topic:
                    byt[commit_topic[c]] += n
            if byt:
                slug, w = byt.most_common(1)[0][0], 'commit'
        if not slug and p in bring_topic:
            slug, w = bring_topic[p].most_common(1)[0][0], 'trailer'
        if not slug:
            for pat, s, title in T.get('module_buckets', []):
                if pmatch(pat, p):
                    slug, w = s, 'module'
                    topics.setdefault(s, dict(slug=s, title=title, summary=''))
                    break
        if not slug:
            slug, w = 'misc', 'fallback'
            topics.setdefault('misc', dict(slug='misc', title='Other upstream changes', summary=''))
        if slug not in topics:
            topics[slug] = dict(slug=slug, title=slug, summary='')
        assign[p], why[p] = slug, w
    order = list(F['subjects'])
    uocs = []
    for s, t in topics.items():
        fl = sorted(p for p, x in assign.items() if x == s)
        if not fl:
            continue
        cs = Counter()
        for p in fl:
            for c, n in F['files'][p]['upstream']:
                cs[c] += n
        uocs.append(dict(slug=s, title=t.get('title', s), summary=t.get('summary', ''), notes=t.get('notes', []),
                         aliases=t.get('aliases', []), files=fl, why={p: why[p] for p in fl},
                         commits=sorted(cs, key=order.index),
                         primary=[short(c) for c in t.get('commits', []) if short(c) in cs]))
    listed = set(c for u in uocs for c in u['commits'])
    unlisted = [c for c in F['subjects'] if c not in listed]
    dump(dict(uocs=uocs, unlisted_commits=unlisted), a.out)
    for u in uocs:
        print('%-36s %4d files %4d commits  (%s)' % (u['slug'], len(u['files']), len(u['commits']),
                                                    ', '.join('%s=%d' % kv for kv in Counter(u['why'].values()).items())))
    print('units %d; upstream commits that touch only files Greengage dropped: %d' % (len(uocs), len(unlisted)))
    fb = [p for p, w in why.items() if w == 'fallback']
    if fb:
        print('%d files fell through to "misc" - add topic paths or a module bucket for them' % len(fb))
    return 0


# ------------------------------------------------------------------ classify
LIMITS = dict(novel=3, gg_lost=3, up_lost=3, extra=6)
RULE_NAMES = {'R1': 'day-1 upstream commit on a Greengage-heavy file',
              'R2': 'upstream deleted/moved a Greengage-modified file',
              'R3': 'new lines in a resolution', 'R4': 'Greengage lines dropped', 'R5': 'upstream lines dropped',
              'R6': 'changed lines outside the conflicts', 'R7': 'new code after the merge (bring-up fix)',
              'R8': 'test changes add errors or drop tests'}


def hunk_metrics(F, p):
    """lines a resolution invented, and lines it dropped from each side (DIRTY -> RAW)"""
    m, ranges = Counter(), []
    b, o, t = (blob('%s:%s' % (F[x], p)) for x in ('mbase', 'base', 'cut'))
    before, after = blob('%s:%s' % (F['dirty'], p)), blob('%s:%s' % (F['raw'], p))
    if None in (b, o, t, before):
        return m, ranges
    segs = parse_marked(merge_file(b, o, t)[1])
    bl = before.splitlines(keepends=True)
    al = align(segs, bl)
    al_after = align(segs, (after or '').splitlines(keepends=True))
    for k, (_, ho, hb, ht) in enumerate(x for x in segs if x[0] == 'h'):
        if k not in al:
            continue
        ranges.append((al[k][1], al[k][2]))
        res = al_after.get(k, (None,))[0]
        if res is None or norm(bl[al[k][1]:al[k][2]]) == norm(res):
            continue
        side = set(x.strip() for x in ho + hb + ht if x.strip())
        rs, bs = set(x.strip() for x in res), set(x.strip() for x in hb)
        m['novel'] += sum(1 for x in res if x.strip() and x.strip() not in side)
        m['gg_lost'] += sum(1 for x in ho if x.strip() and x.strip() not in bs and x.strip() not in rs)
        m['up_lost'] += sum(1 for x in ht if x.strip() and x.strip() not in bs and x.strip() not in rs)
    return m, ranges


def extra_lines(F, p, ranges):
    """changed lines DIRTY -> RAW outside the conflict regions"""
    n = 0
    for part in re.split(r'^(?=@@ )', git('diff', '-U0', '--no-renames', F['dirty'], F['raw'], '--', p), flags=re.M)[1:]:
        x = re.match(r'@@ -(\d+)(?:,(\d+))? ', part)
        start, cnt = int(x.group(1)), int(x.group(2) if x.group(2) is not None else 1)
        a1 = start - 1 if cnt else start
        a2 = a1 + max(cnt, 1)
        if any(not (a2 + 3 <= j1 or j2 + 3 <= a1) for j1, j2 in ranges):
            continue
        n += sum(1 for ln in part.splitlines()[1:] if ln[:1] in '+-' and ln[1:].strip())
    return n


IGN_START, IGN_END = re.compile(r'^\s*--\s*start_ignore'), re.compile(r'^\s*--\s*end_ignore')


def strip_ignored(text):
    """drop -- start_ignore ... -- end_ignore regions, as gpdiff does"""
    out, skip = [], False
    for ln in (text or '').splitlines():
        if IGN_START.match(ln):
            skip = True
        elif IGN_END.match(ln):
            skip = False
        elif not skip:
            out.append(ln)
    return out


def schedule_tests(text):
    return set(w for ln in (text or '').splitlines() if ln.startswith('test:') for w in ln[5:].split())


def test_flags(F, p, kind):
    flags = set()
    old, new = strip_ignored(blob('%s:%s' % (F['base'], p))), strip_ignored(blob('%s:%s' % (F['raw'], p)))
    added, removed = [], []
    for ln in difflib.unified_diff(old, new, lineterm='', n=0):
        if ln.startswith('+') and not ln.startswith('+++'):
            added.append(ln[1:])
        elif ln.startswith('-') and not ln.startswith('---'):
            removed.append(ln[1:])
    loc = lambda ln: re.sub(r'\s*\((\w+\.c:\d+|seg\d+[^)]*)\)', '', ln)
    if kind == 'test_expected':
        up = set(loc(ln) for ln in strip_ignored(blob('%s:%s' % (F['cut'], p))))
        rem = Counter(loc(ln) for ln in removed if 'ERROR:' in ln)
        new_err = []
        for ln in added:
            if 'ERROR:' in ln:
                k = loc(ln)
                if rem[k]:
                    rem[k] -= 1                  # the same error, only the location suffix moved
                elif k not in up:
                    new_err.append(ln)
        if len(new_err) > sum(rem.values()):
            flags.add('expected output gains ERROR lines not in upstream (%d)' % len(new_err))
        if any(re.search(r'server closed the connection|terminated by signal|PANIC|FailedAssertion', ln) for ln in added):
            flags.add('crash text in expected output')
    if kind == 'test_input' and len(removed) > len(added) + 5:
        flags.add('test statements removed')
    if p.endswith('schedule'):
        gone = schedule_tests(blob('%s:%s' % (F['base'], p))) - schedule_tests(blob('%s:%s' % (F['raw'], p)))
        up_before = schedule_tests(blob('%s:%s' % (F['mbase'], p)))
        up_after = schedule_tests(blob('%s:%s' % (F['cut'], p)))
        dropped = [t for t in gone if not (t in up_before and t not in up_after)]    # upstream's own removals pass
        if dropped:
            flags.add('schedule drops %s' % ', '.join(sorted(dropped)[:5]))
        if any(re.search(r'^\s*#\s*test:|ignore:', ln) for ln in added):
            flags.add('schedule comments out or ignores a test')
    return flags


def cmd_classify(a):
    """Rules R1-R8 come from the b14-b17 review triage; their thresholds were fitted per PR
    (median: one file), so they are applied per FILE: a unit is MUST REVIEW when any of its
    files trips a rule, and the reasons name those files."""
    F, U = load(a.facts), load(a.uocs)
    day1 = set(F['day1'])
    buildfix = {b['commit'] for b in F['bringup'] if b['trailers'].get('kind', '').lower().startswith('build')}
    out = {}
    for u in U['uocs']:
        hits, auto_ok, build_lines = defaultdict(list), True, 0
        for p in u['files']:
            f, kind, base = F['files'][p], F['files'][p]['kind'], os.path.basename(p)
            if kind == 'code' and f['gg_delta'] >= 100:
                d1 = sorted({c for c, n in f['upstream'] if c in day1 and n >= 20})
                if d1:
                    hits['R1'].append('%s (%s)' % (base, ' '.join(d1)))
            if f['r2']:
                hits['R2'].append(base)
            ranges, m = [], Counter()
            if f['conflicted'] and kind not in ('test_expected', 'generated'):
                hm, ranges = hunk_metrics(F, p)
                m.update(hm)
            if f['after_dirty'] and kind == 'code':
                ex = extra_lines(F, p, ranges)
                if f['bringup'] and all(c in buildfix for c in f['bringup']):
                    build_lines += ex
                else:
                    m['extra'] += ex
            for k, rid in (('novel', 'R3'), ('gg_lost', 'R4'), ('up_lost', 'R5')):
                if m[k] >= LIMITS[k]:
                    hits[rid].append('%s (%d)' % (base, m[k]))
            if m['extra'] >= LIMITS['extra']:
                hits['R6' if f['conflicted'] else 'R7'].append('%s (%d)' % (base, m['extra']))
            if (kind in ('test_expected', 'test_input') or p.endswith('schedule')) and f['status'] != 'D':
                tf = test_flags(F, p, kind)
                if tf:
                    hits['R8'].append('%s: %s' % (base, '; '.join(sorted(tf))))
            clean_upstream = not f['conflicted'] and not f['after_dirty'] and f['gg_delta'] == 0
            if not (clean_upstream or f['auto'] or kind in ('test_expected', 'generated')):
                auto_ok = False
        if build_lines > 40:
            hits['R7'].append('build fixes %d lines' % build_lines)
        reasons = ['%s %s: %s' % (r, RULE_NAMES[r], ', '.join(v)) for r, v in sorted(hits.items())]
        tier = 'MUST REVIEW' if reasons else ('MERGE AUTOMATICALLY' if auto_ok else 'NO REVIEW')
        out[u['slug']] = dict(tier=tier, reasons=reasons, rules=sorted(hits))
        print('%-20s %-30s %s' % (tier, u['slug'], ' | '.join(reasons)[:150]))
    dump(out, a.out)
    print(dict(Counter(v['tier'] for v in out.values())))
    return 0


# ------------------------------------------------------------------ series
def ordered(U, Tr):
    missing = [u['slug'] for u in U['uocs'] if u['slug'] not in Tr]
    if missing:
        raise Refuse('tiers.json has no entry for %s; re-run classify after assign' % ', '.join(missing))
    return sorted(U['uocs'], key=lambda u: (TIER_ORDER[Tr[u['slug']]['tier']], U['uocs'].index(u)))


def trailer_split(msg):
    paras = msg.rstrip('\n').split('\n\n')
    last = paras[-1].split('\n')
    if len(paras) > 1 and all(re.match(r'^[A-Za-z][A-Za-z-]*:\s', ln) for ln in last):
        return '\n\n'.join(paras[:-1]), last
    return msg.rstrip('\n'), []


def unit_message(F, u, tr, n, total, batch, primary):
    lines = ['UoC %d/%d: %s' % (n, total, u['title']), '']
    if u.get('summary'):
        lines += [u['summary'], '']
    lines += ['- ' + x for x in u.get('notes', [])] + ([''] if u.get('notes') else [])
    lines.append('Review status: %s' % tr['tier'])
    lines += ['  ' + r for r in tr['reasons']]
    lines += ['', 'Upstream PostgreSQL commits (%d):' % len(u['commits'])]
    for c in u['commits']:
        other = primary.get(c)
        lines.append('  %s %s%s' % (c, F['subjects'][c],
                                    ' (main change: UoC %s)' % other if other and other != u['slug'] else ''))
    nconf = sum(1 for p in u['files'] if F['files'][p]['conflicted'])
    nfix = sum(1 for p in u['files'] if F['files'][p]['after_dirty'] and not F['files'][p]['conflicted'])
    lines += ['', 'Files: %d (%d resolved conflicts, %d adapted after the merge)' % (len(u['files']), nconf, nfix),
              '', 'UoC: %s' % u['slug'], 'Batch: %s' % batch]
    return '\n'.join(lines) + '\n'


def default_merge_message(F, branch, total, marked):
    n = len(F['subjects'])
    first = git('log', '-1', '--format=%cs', F['mbase']).strip()
    last = git('log', '-1', '--format=%cs', F['cut']).strip()
    return ('Merge upstream PostgreSQL %s into %s\n\n'
            'Merges upstream PostgreSQL %s..%s (%d commits, %s .. %s).\n\n'
            'Conflicts that a rule could settle (Greengage-deleted files, copyright\n'
            'headers, whitespace-only sides) are resolved here.  The other %d\n'
            'conflicted files are committed WITH conflict markers (zdiff3 style, base\n'
            'section included), so the tree does not build at this commit.\n\n'
            'The %d commits that follow hold the conflict resolutions and the Greengage\n'
            'fixes found by local testing and CI, one commit per unit of change\n'
            '("UoC N/%d"), each listing the unit\'s upstream commits and review status.\n'
            'Units whose upstream changes merged cleanly or were resolved by rule in\n'
            'this commit have an empty UoC commit.\n' % (
                short(F['cut']), branch, short(F['mbase']), short(F['cut']), n, first, last,
                marked, total, total))


def cmd_series(a):
    F, U, Tr = load(a.facts), load(a.uocs), load(a.tiers)
    wt = a.worktree
    if git_wt(wt, 'status', '--porcelain', '--untracked-files=no').strip():
        raise Refuse('worktree %s has uncommitted changes; use a clean worktree (git worktree add)' % wt)
    us = ordered(U, Tr)
    total = len(us)
    n_of = {u['slug']: i for i, u in enumerate(us, 1)}
    primary = {}
    for u in us:
        for c in u.get('primary', []):
            primary.setdefault(short(c), u['slug'])
    f2u = {f: u['slug'] for u in us for f in u['files']}
    alias = {u['slug']: u['slug'] for u in us}
    for u in us:
        for x in u.get('aliases', []):
            alias[x] = u['slug']
    dirty, raw = F['dirty'], F['raw']

    plan = []                                   # [(raw commit, {slug: [(status, path)]})]
    for h in git('rev-list', '--reverse', '%s..%s' % (dirty, raw)).split():
        m = re.search(r'^UoC:\s*(\S+)', git('log', '-1', '--format=%B', h), re.M)
        tslug = alias.get(m.group(1), m.group(1)) if m else None
        parts = OrderedDict()
        for st, p in name_status(h + '^', h):
            s = f2u.get(p) or tslug
            if s not in n_of:
                raise Refuse('cannot place %s (bring-up commit %s, UoC trailer %s): give the commit a UoC '
                             'trailer naming a unit, or add the path to a topic' % (p, short(h), tslug))
            parts.setdefault(s, []).append((st, p))
        plan.append((h, parts))
    touch = defaultdict(list)
    for h, parts in plan:
        for s, fl in parts.items():
            for _, p in fl:
                touch[p].append(s)

    marked = len(marked_files(dirty) - marked_files(F['base']))
    name = a.pr_branch or a.branch             # the branch the PR will use; messages name it
    msg = open(a.merge_message_file).read() if a.merge_message_file else default_merge_message(F, name, total, marked)
    parents = git('log', '-1', '--format=%P', dirty).split()
    an = git('log', '-1', '--format=%an%x00%ae%x00%aI', dirty).strip().split('\0')
    env = dict(GIT_AUTHOR_NAME=an[0], GIT_AUTHOR_EMAIL=an[1], GIT_AUTHOR_DATE=an[2])
    args = ['commit-tree', dirty + '^{tree}']
    for p in parents:
        args += ['-p', p]
    merge = git(*args, '-F', '-', inp=msg, env=env).strip()
    git_wt(wt, 'checkout', '-q', '-B', a.branch, merge)

    net = defaultdict(list)                     # slug -> [(status, path)] of the net change merge -> raw
    for st, p in name_status(merge, raw):
        s = f2u.get(p) or (min(touch[p], key=n_of.get) if p in touch else None)
        if s is None:
            raise Refuse('cannot place %s (changed between the merge and RAW, in no unit)' % p)
        net[s].append((st, p))

    batch = 'upstream %s..%s' % (short(F['mbase']), short(F['cut']))
    series = OrderedDict()
    for u in us:
        s = u['slug']
        mine = [(h, parts) for h, parts in plan if s in parts]
        body, trailers = trailer_split(unit_message(F, u, Tr[s], n_of[s], total, batch, primary))
        fl = net.get(s, [])
        if mine:
            subj = ['  %s %s%s' % (short(h), git('log', '-1', '--format=%s', h).strip(),
                                   ' [%s part]' % s if len(parts) > 1 else '') for h, parts in mine]
            body += ('\n\nThe upstream commits are in the batch merge.  This commit holds the Greengage changes of '
                     'this unit: the conflict resolutions and fixes of its files (%d), squashed from %d bring-up '
                     'commit%s:\n%s' % (len(fl), len(mine), '' if len(mine) == 1 else 's', '\n'.join(subj)))
        else:
            body += ('\n\nNo Greengage changes: the upstream commits of this unit merged cleanly or were resolved '
                     'by rule in the batch merge, so this commit only records the unit.')
        trailers = trailers + ['Raw-commit: %s' % short(h) for h, _ in mine]
        keep = [p for st, p in fl if st != 'D']
        dele = [p for st, p in fl if st == 'D']
        for i in range(0, len(keep), 200):
            git_wt(wt, 'checkout', raw, '--', *keep[i:i + 200])
        for i in range(0, len(dele), 200):
            git_wt(wt, 'rm', '-q', '--', *dele[i:i + 200])
        git_wt(wt, '-c', 'core.hooksPath=/dev/null', 'commit', '-q', '--allow-empty', '-F', '-',
               inp=body + '\n\n' + '\n'.join(trailers) + '\n')
        series[s] = dict(n=n_of[s], commit=git_wt(wt, 'rev-parse', 'HEAD').strip(),
                         raw=[short(h) for h, _ in mine], files=[p for _, p in fl])
    tip = git_wt(wt, 'rev-parse', 'HEAD').strip()
    if git('diff', '--stat', raw, tip).strip():
        raise Refuse('the rebuilt branch does not reproduce RAW (git diff %s %s); nothing was pushed' % (short(raw), short(tip)))
    dump(dict(branch=name, build_branch=a.branch, merge=merge, tip=tip, marked_in_merge=marked, units=series), a.out)
    print('%s: merge %s + %d unit commits (%d empty), %d files from %d bring-up commits (%d split across units); '
          'tip %s, tree == RAW' % (a.branch, short(merge), total, sum(1 for v in series.values() if not v['files']),
                                  sum(len(v['files']) for v in series.values()), len(plan),
                                  sum(1 for _, p in plan if len(p) > 1), short(tip)))
    return 0


# ------------------------------------------------------------------ verify
def cmd_verify(a):
    F, S = load(a.facts), load(a.series)
    dirty, raw, merge = F['dirty'], F['raw'], S['merge']
    errs = []
    if git('rev-parse', merge + '^{tree}') != git('rev-parse', dirty + '^{tree}'):
        errs.append('the merge commit tree differs from DIRTY')
    if git('log', '-1', '--format=%P', merge) != git('log', '-1', '--format=%P', dirty):
        errs.append('the merge commit parents differ from DIRTY')

    def bl(c, p):
        return git('rev-parse', '--verify', '--quiet', '%s:%s' % (c, p), ok=(0, 1)).strip() or None

    want = set(p for _, p in name_status(merge, raw))
    seen, prev, raw_listed = {}, merge, set()
    raw_all = set(short(h) for h in git('rev-list', '%s..%s' % (dirty, raw)).split())
    for s, v in sorted(S['units'].items(), key=lambda kv: kv[1]['n']):
        c = v['commit']
        if git('log', '-1', '--format=%P', c).split() != [prev]:
            errs.append('UoC %d (%s) is not a child of the previous commit' % (v['n'], s))
        ch = set(p for _, p in name_status(prev, c))
        if ch != set(v['files']):
            errs.append('UoC %d (%s) changes %d files, series.json lists %d' % (v['n'], s, len(ch), len(v['files'])))
        for p in ch:
            if bl(c, p) != bl(raw, p):
                errs.append('UoC %d (%s): %s differs from RAW' % (v['n'], s, p))
            if p in seen:
                errs.append('%s is changed by UoC %s and UoC %s' % (p, seen[p], s))
            seen[p] = s
        tr = re.findall(r'^Raw-commit:\s*(\S+)', git('log', '-1', '--format=%B', c), re.M)
        if tr != v['raw']:
            errs.append('UoC %d (%s): Raw-commit trailers %s, expected %s' % (v['n'], s, tr, v['raw']))
        if not ch and v['raw']:
            errs.append('UoC %d (%s) squashes bring-up commits but changes nothing' % (v['n'], s))
        raw_listed.update(tr)
        prev = c
    if set(seen) != want:
        errs.append('%d files change between the merge and RAW, the units cover %d' % (len(want), len(seen)))
    if raw_listed != raw_all:
        errs.append('bring-up commits not listed in any unit: %s' % ' '.join(sorted(raw_all - raw_listed)))
    if git('rev-parse', prev + '^{tree}') != git('rev-parse', raw + '^{tree}'):
        errs.append('the tip tree differs from RAW')
    for e in errs:
        print('MISMATCH ' + e)
    print('merge %s, %d units, %d files, %d bring-up commits: %s' % (
        short(merge), len(S['units']), len(seen), len(raw_listed), 'review branch == RAW' if not errs else '%d mismatches' % len(errs)))
    return 1 if errs else 0


# ------------------------------------------------------------------ render
def sections(path):
    out, cur = OrderedDict(), None
    with open(path) as f:
        for ln in f:
            m = re.match(r'<!-- section: (\w+) -->', ln)
            if m:
                cur = m.group(1)
                out[cur] = ''
            elif cur:
                out[cur] += ln
    return {k: v.strip() + '\n' for k, v in out.items() if v.strip()}


def cmd_render(a):
    F, U, Tr, S = load(a.facts), load(a.uocs), load(a.tiers), load(a.series)
    sec = sections(a.sections)
    missing = [k for k in ('intro', 'adaptations', 'validation') if k not in sec]
    if missing:
        raise Refuse('%s has no %s section; start from the skeleton in the skill reference pr-template.md'
                     % (a.sections, ', '.join(missing)))
    inv = load(a.inventory) if a.inventory else None
    us = ordered(U, Tr)
    cnt = Counter(Tr[u['slug']]['tier'] for u in us)
    br, raw_br, total = S['branch'], a.raw_branch or S['branch'] + '-raw', len(us)
    empty = [u['title'] for u in us if not S['units'][u['slug']]['files']]
    m = re.match(r'sync-(\d+)x-b(\d+)$', br)
    title = a.title or ('Sync %s: merge upstream PostgreSQL %s..%s (%s%d units of change)' % (
        br.replace('sync-', '').replace('-', ' '), short(F['mbase']), short(F['cut']),
        'PG%s batch %s, ' % m.groups() if m else '', total))
    rows = []
    for n, u in enumerate(us, 1):
        t, cs = Tr[u['slug']], u['commits']
        pc = ' '.join(cs) if len(cs) <= a.max_inline else '%s … <br>(%d total, full list in the UoC commit)' % (
            ' '.join(cs[:a.max_inline]), len(cs))
        why = '<br><sub>%s</sub>' % '; '.join(t['rules']) if t['rules'] else ''
        tag = '' if S['units'][u['slug']]['files'] else '<br><sub>(upstream only, empty commit)</sub>'
        rows.append('| %d | **%s**<br>%s%s | %s | %s | %s%s | — |' % (
            n, u['title'].replace('|', '\\|'), short(S['units'][u['slug']]['commit']), tag,
            (u.get('summary') or '').replace('|', '\\|').replace('\n', ' '), pc or '—', TIER_LABEL[t['tier']], why))

    stats = ''
    if inv:
        c = Counter(f['tier'] for f in inv['files'])
        hunks = sum(1 for f in inv['files'] for h in f.get('hunks', []) if h['tier'] == 'RESOLVE')
        regen = sum(1 for f in inv['files'] if f['tier'] == 'REGEN')
        stats = ('\nMerge statistics: %d conflicted files.\n- %d resolved by rule in the merge commit.\n'
                 '- %d resolved by hand (%d content hunks), %d of them committed with markers.\n'
                 '- %d generated or expected-output files regenerated rather than merged.\n' % (
                     len(inv['files']), c['AUTO'], len(inv['files']) - c['AUTO'], hunks, S['marked_in_merge'], regen))
    org = ('**How this PR is organised.** The history starts with the real merge of the upstream batch, followed by '
           'one commit per **unit of change (UoC)**:\n'
           '- `Merge upstream PostgreSQL %s into %s` brings in the %d upstream commits. Conflicts that a rule could '
           'settle are resolved in it. The other %d conflicted files are committed with their conflict markers (zdiff3, '
           'base section included), so the merge commit itself does not build.\n'
           '- Each UoC is then one commit, `UoC N/%d: <title>`. Its diff holds the unit\'s conflict resolutions (each '
           'removes the committed markers, so it shows both sides and the chosen result) and the adaptations and fixes '
           'found by local testing and CI. Its message holds the summary, the review recommendation with the rules and '
           'files that triggered it, the full list of the unit\'s upstream commits, and the bring-up commits it squashes.\n'
           % (short(F['cut']), br, len(F['subjects']), S['marked_in_merge'], total))
    if empty:
        org += ('- Units whose upstream changes merged cleanly or were settled by rule inside the merge (%s) have no '
                'Greengage changes. Their UoC commit is empty and only records the unit.\n' % ', '.join(empty))
    org += ('\nThe individual bring-up commits are kept on `%s` in their original order. Each UoC commit names the ones '
            'it squashes in `Raw-commit:` trailers; a bring-up commit that touched several units is listed in each. The '
            'commits before the tip do not build on their own; CI validates the tip. Merge this PR with a merge commit '
            '(not squash or rebase) so the upstream ancestry is kept.\n' % raw_br)

    body = [sec['intro'], org + stats, '## Units of change\n',
            '%d units: %d must review, %d no review, %d merge automatically. The first commit on this branch, %s, is '
            'the merge of the upstream batch. Each unit is then one commit (the short hash after the title).%s The '
            '**Review PR** column is kept up to date from the review PRs themselves.\n' % (
                total, cnt['MUST REVIEW'], cnt['NO REVIEW'], cnt['MERGE AUTOMATICALLY'], short(S['merge']),
                ' The %d units marked "upstream only" have no Greengage changes; their commits are empty.' % len(empty)
                if empty else ''),
            '| # | Unit of change | Summary | PostgreSQL commits | Review | Review PR |',
            '|---|---|---|---|---|---|'] + rows + ['']
    if U.get('unlisted_commits'):
        body += ['<details><summary>%d upstream commits that change only files Greengage removed (docs, translations, '
                 '...)</summary>\n' % len(U['unlisted_commits']), ' '.join(U['unlisted_commits']), '\n</details>\n']
    body.append(
        '### Review status\n\n'
        'The recommendation applies the rules from the b14–b17 review triage (review threads and defect outcomes of '
        '607 PRs). The thresholds were fitted per PR, so they are evaluated **per file** inside each UoC; the '
        'triggering files are listed in each UoC commit.\n\n'
        '| Status | Meaning | Rules |\n|---|---|---|\n'
        '| 🔴 **must review** | A reviewer should read it, and run the affected tests where possible. All high and '
        'medium review findings of b14–b17 were in this class. | **R1** an upstream "day-1" commit (largest overlap '
        'with Greengage-heavy code) touches a Greengage-heavy file · **R2** upstream deleted or moved a file Greengage '
        'modifies · **R3/R4/R5** ≥3 new / Greengage-dropped / upstream-dropped lines in a conflict resolution · '
        '**R6/R7** ≥6 changed code lines outside the conflicts, or new code added during bring-up · **R8** expected '
        'output gains errors, or tests are dropped |\n'
        '| 🟢 **no review** | Small resolutions, build fixes and clean upstream changes in Greengage-modified files. '
        'Gated by CI. | none of the above |\n'
        '| ⚪ **merge automatically** | Clean upstream changes in files Greengage never modified, rule-based '
        'resolutions, generated/regenerated files. | none of the above |\n')
    body.append(
        '### Review PRs\n\n'
        'Review PRs are opened per unit as reviewers are assigned, and the fixes they produce are merged into this PR. '
        'A review PR for UoC *N* has base `%s-uoc<N>-base` (the commit before the unit) and head `%s-uoc<N>` (the unit '
        'commit), so its diff is exactly that unit. With the gg-agent plugin, `uoc_review.py open --pr <this PR> --uoc '
        '<N>` creates both branches and the PR; by hand, with `<commit>` the hash after the unit\'s title:\n\n'
        '```sh\n'
        'git push origin <commit>^:refs/heads/%s-uoc<N>-base <commit>:refs/heads/%s-uoc<N>\n'
        'gh pr create -R %s --base %s-uoc<N>-base --head %s-uoc<N> --title "Review %s UoC <N>: <title>"\n'
        '```\n\n'
        'The upstream commits are only listed in the unit commit; they are already reviewed upstream. Push review fixes '
        'to the head branch. When the review is done, retarget the review PR\'s base to `%s`: its diff becomes only the '
        'fixes, which are merged into this branch with a merge commit. Upstream-only units (empty commits) need no '
        'review PR.\n' % (br, br, br, br, a.repo, br, br, br, br))
    for k in ('adaptations', 'validation', 'followups'):
        if k in sec:
            body.append(sec[k])
    text = '\n'.join(body)
    with open(a.out, 'w') as f:
        f.write(text)
    print('title: %s' % title)
    print('%s: %d chars, %d unit rows' % (a.out, len(text), len(rows)))
    if len(text) >= BODY_LIMIT:
        print('the body is over GitHub\'s %d-character limit: lower --max-inline (now %d) or shorten the sections'
              % (BODY_LIMIT, a.max_inline))
        return 1
    return 0


# ------------------------------------------------------------------ main
def main(argv=None):
    global REPO
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                 epilog='See the module docstring (head -60 %s) for the flow.' % os.path.basename(__file__),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-C', dest='gitdir', help='greengage_sync checkout (default: current directory)')
    sp = ap.add_subparsers(dest='cmd', metavar='SUBCOMMAND')
    p = sp.add_parser('select', help='pick the upstream commits of the batch')
    p.add_argument('--source', default='next', help='Greengage branch the batch starts from (default: next)')
    p.add_argument('--upstream', required=True, help='upstream PostgreSQL ref that bounds the batch (the pinned major target)')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--count', type=int, help='number of upstream commits')
    g.add_argument('--until', help='last upstream commit of the batch')
    g.add_argument('--before', help='take commits dated before YYYY-MM-DD')
    p.add_argument('--lookahead', type=int, default=300, help='commits after the cut checked for reverts (default 300)')
    p.add_argument('--out')
    p = sp.add_parser('inventory', help='sort the conflict hunks of the merge')
    p.add_argument('ours')
    p.add_argument('theirs')
    p.add_argument('--json')
    p.add_argument('--apply', metavar='WORKTREE', help='write the AUTO resolutions into this worktree (merge in progress)')
    p.add_argument('--blame', action='store_true', help='name the upstream commits behind each hunk (slow)')
    p = sp.add_parser('facts', help='collect per-file facts of BASE..RAW')
    for x in ('base', 'cut', 'dirty', 'raw'):
        p.add_argument(x)
    p.add_argument('--inventory', required=True)
    p.add_argument('--out', required=True)
    p = sp.add_parser('assign', help='group files into units of change')
    p.add_argument('facts')
    p.add_argument('topics')
    p.add_argument('--notes', help='directory of resolver notes ("### path" + "UoC: slug")')
    p.add_argument('--out', required=True)
    p = sp.add_parser('classify', help='give each unit a review status')
    p.add_argument('facts')
    p.add_argument('uocs')
    p.add_argument('--out', required=True)
    p = sp.add_parser('series', help='build the review branch')
    for x in ('facts', 'uocs', 'tiers'):
        p.add_argument(x)
    p.add_argument('--worktree', required=True, help='a clean worktree of the repository to build in')
    p.add_argument('--branch', required=True, help='local branch to build on (created or reset in WT)')
    p.add_argument('--pr-branch', help='branch name the PR uses, for the messages (default: --branch); '
                   'build on a temporary --branch when the PR branch is checked out elsewhere')
    p.add_argument('--out', required=True)
    p.add_argument('--merge-message-file')
    p = sp.add_parser('verify', help='prove the review branch reproduces RAW')
    p.add_argument('facts')
    p.add_argument('series')
    p = sp.add_parser('render', help='write the pull request description')
    for x in ('facts', 'uocs', 'tiers', 'series'):
        p.add_argument(x)
    p.add_argument('--sections', required=True, help='hand-written sections (skeleton: reference/pr-template.md)')
    p.add_argument('--repo', required=True, help='OWNER/REPO of the pull request, e.g. GreengageDB/greengage_sync')
    p.add_argument('--inventory', help='inventory JSON, for the merge statistics')
    p.add_argument('--raw-branch', help='branch that keeps the bring-up history (default: <branch>-raw)')
    p.add_argument('--title')
    p.add_argument('--max-inline', type=int, default=12, help='upstream commits listed per row before truncating')
    p.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    REPO = a.gitdir
    try:
        if subprocess.run(['git'] + (['-C', REPO] if REPO else []) + ['rev-parse', '--git-dir'],
                          capture_output=True).returncode:
            raise Refuse('%s is not a git repository; run from the greengage_sync checkout or pass -C' % (REPO or '.'))
        return {'select': cmd_select, 'inventory': cmd_inventory, 'facts': cmd_facts, 'assign': cmd_assign,
                'classify': cmd_classify, 'series': cmd_series, 'verify': cmd_verify, 'render': cmd_render}[a.cmd](a)
    except Refuse as e:
        print('pg_batch.py %s: %s' % (a.cmd, e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
