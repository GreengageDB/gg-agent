#!/usr/bin/env python3
"""Split the Greengage side of a greengage_sync batch into units of change, per operation.

The batch flow (skill greengage-pg-batch) commits the upstream merge with its conflict
markers (DIRTY) and brings it up to a green tip (RAW). This tool cuts every file's
DIRTY -> RAW change into operations (difflib opcodes), finds what caused each one, gives
it to a unit of change, and builds one independent branch per unit on top of DIRTY:

    <prefix>-base   DIRTY, the merge with the markers committed
    <prefix>-uocN   one commit, parent DIRTY: only unit N's operations applied

The unit branches merge cleanly in any order and together give RAW.

Subcommands, in the order the flow uses them:

    causes    cut every changed file into operations and find their causes (slow)
    assign    give every operation a unit (fast; re-run after each split.json edit)
    review    print operations with their content and causes, for checking by eye
    check     prove the units independent and complete, list placements to re-check
    bundle    write per-unit material for the unit descriptions
    branches  create <prefix>-base and the <prefix>-uocN branches
    links     fill the {Un} placeholders of a PR description with the unit PR URLs

Usage:
    uoc_split.py [-C REPO] --dir DIR causes
    uoc_split.py [-C REPO] --dir DIR assign
    uoc_split.py [-C REPO] --dir DIR review [--how region,raw,...] [--path SUBSTR] [--unit SLUG] [--all]
    uoc_split.py [-C REPO] --dir DIR check [--only indep,complete,removed,crossdeps,audit]
    uoc_split.py [-C REPO] --dir DIR bundle
    uoc_split.py [-C REPO] --dir DIR branches PREFIX [--create] [--force] [--base] [--only N,...]
    uoc_split.py [-C REPO] --dir DIR links PREFIX TEMPLATE [--repo OWNER/REPO]

DIR is the batch directory. Inputs:
    facts.json    pg_batch.py facts: BASE, CUT, DIRTY, RAW and the merge base
    topics.json   the units; their order is the unit order (pg_batch.py assign input)
    uocs.json     pg_batch.py assign: the per-file owner, an operation's fallback unit
    split.json    manual decisions, optional (redirect, primary, overrides, edits, ...)
    msg/<slug>.txt  unit descriptions, needed by branches --create
Outputs: ops.json (causes), assignment.json (assign), numbers.json (branches), units/
(bundle), tokens.json and gone.json (caches).

Exit status: 0 clean; 1 findings (check: units conflict, do not reproduce RAW, or leave a
removed identifier behind); 2 usage or environment error.
"""
import argparse
import difflib
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, OrderedDict, defaultdict

REPO = None
DIR = None
TOK = re.compile(r'[A-Za-z_][A-Za-z0-9_]{3,}')
STOP = set('''NULL true false void static const char bool return else break case int Oid
List text from select where SELECT FROM WHERE rows QUERY PLAN Output Filter Index Scan
create table insert into values explain costs'''.split())
SRC = ['--', '*.c', '*.h', '*.y', '*.l', '*.pl', '*.pm', '*.py', '*.cpp']
CHECKS = ('indep', 'complete', 'removed', 'crossdeps', 'audit')


class Refuse(Exception):
    """A usage or environment problem: exit 2 with a remediation."""


# ------------------------------------------------------------------ git plumbing
def git(*args, ok=(0,), inp=None, env=None, raw=False):
    cmd = ['git'] + (['-C', REPO] if REPO else []) + list(args)
    e = dict(os.environ, **env) if env else None
    r = subprocess.run(cmd, capture_output=True, input=inp.encode() if isinstance(inp, str) else inp, env=e)
    if ok is not None and r.returncode not in ok:
        raise Refuse('git %s failed (%d): %s' % (' '.join(args[:3]), r.returncode,
                                                  r.stderr.decode(errors='replace').strip()[:600]))
    return r.stdout if raw else r.stdout.decode('utf-8', errors='replace')


_cat = None


def content(spec):
    """bytes at 'rev:path', None if it does not exist"""
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
    return data


@functools.lru_cache(maxsize=8192)
def lines(rev, path):
    """lines of rev:path (keepends; bytes kept through surrogateescape), () if missing"""
    d = content('%s:%s' % (rev, path))
    if d is None:
        return ()
    ls = d.decode('utf-8', 'surrogateescape').split('\n')      # not splitlines(): git counts only \n
    return tuple([x + '\n' for x in ls[:-1]] + ([ls[-1]] if ls[-1] else []))


def exists(rev, path):
    return content('%s:%s' % (rev, path)) is not None


def short(h):
    return h[:11]


def subject(c, _s={}):
    if c not in _s:
        _s[c] = git('log', '-1', '--format=%s', c).strip()
    return _s[c]


# ------------------------------------------------------------------ batch directory
def bpath(name):
    return os.path.join(DIR, name)


def load(name, required=True):
    try:
        with open(bpath(name)) as f:
            return json.load(f)
    except FileNotFoundError:
        if required:
            raise Refuse('%s has no %s; %s' % (DIR, name, {
                'facts.json': 'run pg_batch.py facts first',
                'topics.json': 'write it as for pg_batch.py assign',
                'uocs.json': 'run pg_batch.py assign first',
                'ops.json': 'run uoc_split.py causes first',
                'assignment.json': 'run uoc_split.py assign first'}.get(name, 'create it')))
        return None
    except ValueError as e:
        raise Refuse('%s is not valid JSON: %s' % (bpath(name), e))


def dump(obj, name):
    with open(bpath(name), 'w') as f:
        json.dump(obj, f, indent=1)


def facts():
    F = load('facts.json')
    return F, F['dirty'], F['raw'], F['mbase'], F['cut']


def full(h):
    r = git('rev-parse', '--verify', '--quiet', h + '^{commit}', ok=(0, 1)).strip()
    if not r:
        raise Refuse('%s is not a commit in this repository (named in split.json or topics.json)' % h)
    return short(r)


def config():
    """split.json, with every commit hash resolved to 11 characters"""
    c = load('split.json', required=False) or {}
    unknown = set(c) - {'redirect', 'redirect_by_file', 'primary', 'overrides', 'owners', 'edits',
                        'author_from', 'audit', 'comment'}
    if unknown:
        raise Refuse('split.json: unknown keys %s' % ', '.join(sorted(unknown)))
    return dict(
        redirect={full(k): v for k, v in c.get('redirect', {}).items()},
        redirect_by_file=[(full(r), p, s) for r, p, s in c.get('redirect_by_file', [])],
        primary={full(k): v for k, v in c.get('primary', {}).items()},
        overrides=dict(c.get('overrides', {})),
        owners=dict(c.get('owners', {})),
        edits=c.get('edits', []),
        author_from={k: full(v) for k, v in c.get('author_from', {}).items()},
        tests_unit=c.get('audit', {}).get('tests_unit'),
        regen_commits={full(x) for x in c.get('audit', {}).get('regen_commits', [])})


def units(F, cfg):
    """unit order, titles, per-file owners and the upstream commits each unit claims.

    A unit claims the commits its topic lists and every upstream commit that touches its
    files and that no topic lists. A commit listed by several topics is claimed by all of
    them, unless split.json "primary" pins it to one."""
    T, U = load('topics.json'), load('uocs.json')
    order, titles, alias = [], {}, {}
    for t in T['topics']:
        order.append(t['slug'])
        titles[t['slug']] = t.get('title', t['slug'])
        for x in t.get('aliases', []):
            alias[x] = t['slug']
    for u in U['uocs']:
        if u['slug'] not in titles:
            order.append(u['slug'])
            titles[u['slug']] = u.get('title', u['slug'])
    owner = {p: u['slug'] for u in U['uocs'] for p in u['files']}
    for b in F['bringup']:                      # files whose net change BASE -> RAW is empty
        s = b['trailers'].get('uoc')
        for p in b['files'] if s else ():
            owner.setdefault(p, alias.get(s, s))
    owner.update(cfg['owners'])
    listed = defaultdict(set)                   # commit -> topics that list it
    for t in T['topics']:
        for c in t.get('commits', []):
            listed[full(c)].add(t['slug'])
    for c, s in cfg['primary'].items():
        listed[c] = {s}
    claim = defaultdict(set)
    for c, ss in listed.items():
        for s in ss:
            claim[s].add(c)
    for u in U['uocs']:
        for c in u['commits']:
            if c not in listed:
                claim[u['slug']].add(c)
    claimers = defaultdict(set)
    for s, cs in claim.items():
        for c in cs:
            claimers[c].add(s)
    return dict(order=order, titles=titles, owner=owner, claim=claim, claimers=claimers)


# ------------------------------------------------------------------ operations
def regions(M):
    """conflict regions of a merge state: start and end line, and the theirs section"""
    out, i = [], 0
    while i < len(M):
        if M[i].startswith('<<<<<<< '):
            s, t = i, None
            while i < len(M) and not M[i].startswith('>>>>>>> '):
                if M[i].rstrip('\r\n') == '=======':
                    t = i
                i += 1
            if i < len(M) and t is not None:
                out.append(dict(s=s, e=i, theirs=list(M[t + 1:i])))
        i += 1
    return out


def opcodes(M, F):
    sm = difflib.SequenceMatcher(None, M, F, autojunk=False)
    return [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != 'equal']


def overlapping(R, i1, i2):
    return [r for r in R if not (i2 <= r['s'] or i1 > r['e'])]


def toks(ls):
    return {t for ln in ls for t in TOK.findall(ln)} - STOP


def locate(Up, T, before, after):
    """0-based start of T in Up, disambiguated by the lines around it; None if ambiguous"""
    n, best = len(T), []
    for p in range(len(Up) - n + 1):
        if list(Up[p:p + n]) != T:
            continue
        score = 0
        for d in range(1, 4):
            if p - d >= 0 and len(before) >= d and Up[p - d] == before[-d]:
                score += 1
            if p + n + d - 1 < len(Up) and len(after) >= d and Up[p + n + d - 1] == after[d - 1]:
                score += 1
        best.append((score, p))
    if not best:
        return None
    best.sort(reverse=True)
    if len(best) > 1 and best[0][0] == best[1][0]:
        return None
    return best[0][1]


def log_L(path, s, e, rng):
    out = git('log', '--format=@%H', '--no-patch', '-L%d,%d:%s' % (s, e, path), rng, ok=None)
    return sorted({short(ln[1:]) for ln in out.splitlines() if ln.startswith('@')})


def region_causes(path, M, r, mbase, cut):
    """upstream commits that changed the region: its theirs section is verbatim upstream
    text, found in CUT's file by the lines around it; `git log -L` over it, one extra line
    on each side to catch pure deletions"""
    Up = lines(cut, path)
    if not Up:
        return None, 'no upstream file'
    p = locate(Up, r['theirs'], M[max(0, r['s'] - 3):r['s']], M[r['e'] + 1:r['e'] + 4])
    if p is None:
        return None, 'cannot locate %stheirs' % ('empty ' if not r['theirs'] else '')
    s, e = max(1, p), min(len(Up), p + len(r['theirs']) + 1)
    return log_L(path, s, max(s, e), '%s..%s' % (mbase, cut)), None


def token_index(mbase, cut):
    """identifiers each upstream commit of the batch removed and added (cached)"""
    rng = '%s..%s' % (mbase, cut)
    idx = load('tokens.json', required=False)
    if not idx or idx.get('range') != rng:
        commits = {}
        for c in git('rev-list', rng).split():
            d = git('show', '--format=', '-U0', '--no-renames', c)
            minus = [ln[1:] for ln in d.splitlines() if ln.startswith('-') and not ln.startswith('---')]
            plus = [ln[1:] for ln in d.splitlines() if ln.startswith('+') and not ln.startswith('+++')]
            tm, tp = toks(minus), toks(plus)
            commits[short(c)] = dict(removed=sorted(tm - tp), added=sorted(tp - tm))
        idx = dict(range=rng, commits=commits)
        dump(idx, 'tokens.json')
    df, rem, add = Counter(), defaultdict(set), defaultdict(set)
    for c, v in idx['commits'].items():
        for t in set(v['removed']) | set(v['added']):
            df[t] += 1
        for t in v['removed']:
            rem[t].add(c)
        for t in v['added']:
            add[t].add(c)
    return df, rem, add


def attribute(Ml, Fl, df, rem, add, maxdf=4):
    """the commits whose removed/added identifiers best match the operation's: rare tokens
    weigh more (1/df); a commit that matches both sides wins -> (commits, score, both)"""
    tm, tf = toks(Ml), toks(Fl)
    score, side = Counter(), defaultdict(set)
    for t in tm - tf:
        if df[t] <= maxdf:
            for c in rem[t]:
                score[c] += 1 / df[t]
                side[c].add('R')
    for t in tf - tm:
        if df[t] <= maxdf:
            for c in add[t]:
                score[c] += 1 / df[t]
                side[c].add('A')
    if not score:
        return [], 0, False
    both = {c for c in score if side[c] == {'R', 'A'}}
    pool = both or set(score)
    best = max(score[c] for c in pool)
    return sorted(c for c in pool if score[c] == best), round(best, 3), bool(both)


def is_answer(f):
    return '/expected/' in f


def upstream_answer(f):
    return re.sub(r'_optimizer(\.out)$', r'\1', f)


def blame(path, mbase, cut):
    """batch commit behind each line of CUT's file, None for lines older than the batch"""
    out = git('blame', '--porcelain', '%s..%s' % (mbase, cut), '--', path, ok=None).splitlines()
    res, boundary, cur = [], set(), None
    for ln in out:
        m = re.match(r'^([0-9a-f]{40}) \d+ \d+', ln)
        if m:
            cur = short(m.group(1))
        elif ln == 'boundary':
            boundary.add(cur)
        elif ln.startswith('\t'):
            res.append(cur)
    return [None if c in boundary else c for c in res]


def test_causes(f, M, i1, i2, cache, mbase, cut):
    """an answer-file replacement belongs to the batch commit that wrote at least half of
    the replaced lines upstream; a pure insertion to the one that wrote the line before it"""
    if f not in cache:
        up = upstream_answer(f)
        Up, mp = lines(cut, up), {}
        B = blame(up, mbase, cut) if Up else []
        if Up and len(B) == len(Up):
            for a, b, n in difflib.SequenceMatcher(None, M, Up, autojunk=False).get_matching_blocks():
                for k in range(n):
                    mp[a + k] = b + k
        cache.clear()
        cache[f] = (B, mp)
    B, mp = cache[f]
    if not mp:
        return []
    rng = range(i1, i2) if i2 > i1 else [i1 - 1]
    cnt = Counter(B[mp[i]] for i in rng if i in mp and B[mp[i]])
    top = max(cnt.values()) if cnt else 0
    if top and (i2 == i1 or 2 * top >= len(rng)):
        return sorted(c for c, n in cnt.items() if n == top)
    return []


def cmd_causes(a):
    F, dirty, raw, mbase, cut = facts()
    df, rem, add = token_index(mbase, cut)
    files = [f for f in git('diff', '--name-only', '--no-renames', dirty, raw).splitlines() if f]
    ops, errs, tcache = [], [], {}
    for n, f in enumerate(files, 1):
        if n % 100 == 0:
            print('  %d/%d files' % (n, len(files)), file=sys.stderr)
        M, Fl = lines(dirty, f), lines(raw, f)
        R = regions(M)
        rc = {}
        for r in R:
            c, err = region_causes(f, M, r, mbase, cut)
            rc[r['s']] = c or []
            if err:
                errs.append('%s:%d %s' % (f, r['s'] + 1, err))
        per_file = None
        for i1, i2, j1, j2 in opcodes(M, Fl):
            regs = overlapping(R, i1, i2)
            op = dict(f=f, i1=i1, i2=i2, j1=j1, j2=j2, regions=[r['s'] + 1 for r in regs],
                      causes=sorted({c for r in regs for c in rc[r['s']]}), tok=None, test=[])
            # the bring-up commit behind the operation: `git log -L` on the raw history over
            # its final lines (or the lines around a deletion); if that finds nothing and one
            # bring-up commit touched the file, it is that one
            if not exists(raw, f):
                op['raws'] = ['<deleted file>']
            else:
                s, e = (j1 + 1, j2) if j2 > j1 else (max(1, j1), min(len(Fl), j1 + 1))
                op['raws'] = log_L(f, s, max(s, e), '%s..%s' % (dirty, raw)) if Fl else []
                if not op['raws']:
                    if per_file is None:
                        per_file = sorted({short(h) for h in git('log', '--format=%H', '%s..%s' % (dirty, raw),
                                                                  '--', f).split()})
                    if len(per_file) == 1:
                        op['raws'] = per_file
            if not regs:
                c, score, both = attribute(M[i1:i2], Fl[j1:j2], df, rem, add)
                op['tok'] = dict(c=c, score=score, both=both)
                if is_answer(f):
                    op['test'] = test_causes(f, M, i1, i2, tcache, mbase, cut)
            ops.append(op)
    dump(dict(dirty=dirty, raw=raw, ops=ops, region_errors=errs), 'ops.json')
    nreg = sum(1 for o in ops if o['regions'])
    print('files %d, operations %d (%d in conflict regions), conflict regions without a cause %d, '
          'operations without a bring-up commit %d' % (len(files), len(ops), nreg, len(errs),
                                                       sum(1 for o in ops if not o['raws'])))
    for e in errs[:30]:
        print('  region: ' + e)
    return 0


# ------------------------------------------------------------------ assign
def result_blocks(M):
    """block id per line of an answer file: a result set (header, dashes, rows, "(N rows)")
    is one block; every other line is its own block"""
    ids, b, i = [0] * len(M), 0, 0
    while i < len(M):
        b += 1
        if i + 1 < len(M) and M[i + 1].strip() and re.fullmatch(r'[-+]+\n?', M[i + 1]):
            j = i
            while j < len(M) and not re.match(r'\(\d+ rows?\)', M[j]):
                j += 1
            for k in range(i, min(j + 1, len(M))):
                ids[k] = b
            i = j + 1
        else:
            ids[i] = b
            i += 1
    return ids


def group_answer_files(result, dirty, gap=2):
    """answer-file operations left in place follow an operation tied to new upstream test
    content in the same result set or within `gap` unchanged lines, so that a plan or a
    test is not split between units; an _optimizer.out operation follows the operation at
    the same place of the planner .out. Renames and conflict regions pull nothing along."""
    byf = defaultdict(list)
    for r in result:
        if is_answer(r['f']):
            byf[r['f']].append(r)

    def moved(r):
        return r['new'] != r['old'] and r['how'] in ('testL', 'mirror', 'group', 'override')

    def cluster(ops, M):
        blk = result_blocks(M)
        ops.sort(key=lambda r: r['i1'])
        groups, cur = [], [ops[0]]
        for x, y in zip(ops, ops[1:]):
            same = M and blk[min(x['i2'], len(M) - 1)] == blk[min(y['i1'], len(M) - 1)]
            if y['i1'] - x['i2'] <= gap or same:
                cur.append(y)
            else:
                groups.append(cur)
                cur = [y]
        groups.append(cur)
        for g in groups:
            targets = {r['new'] for r in g if moved(r)}
            if len(targets) == 1:
                t = targets.pop()
                for r in g:
                    if r['how'] == 'none' and r['new'] == r['old']:
                        r['new'], r['how'] = t, 'group'

    for f, ops in byf.items():
        cluster(ops, lines(dirty, f))
    for f, ops in byf.items():
        base = upstream_answer(f)
        if base == f or base not in byf:
            continue
        mp = {}
        for x, y, n in difflib.SequenceMatcher(None, lines(dirty, f), lines(dirty, base),
                                               autojunk=False).get_matching_blocks():
            for k in range(n):
                mp[x + k] = y + k
        for r in ops:
            if r['how'] != 'none' or r['new'] != r['old']:
                continue
            near = [mp[i] for i in range(max(0, r['i1'] - 3), r['i2'] + 3) if i in mp]
            if not near:
                continue
            lo, hi = min(near), max(near)
            ts = {b['new'] for b in byf[base] if b['i1'] <= hi + 1 and b['i2'] >= lo - 1 and moved(b)}
            if len(ts) == 1:
                r['new'], r['how'] = ts.pop(), 'mirror'
        cluster(ops, lines(dirty, f))


def cmd_assign(a):
    F, dirty, raw, mbase, cut = facts()
    cfg = config()
    X = units(F, cfg)
    O = load('ops.json')
    if (O['dirty'], O['raw']) != (dirty, raw):
        raise Refuse('ops.json was computed for another DIRTY/RAW; re-run causes')
    order = X['order']
    pos = {s: i for i, s in enumerate(order)}
    named = [('redirect', s) for s in cfg['redirect'].values()] + \
            [('redirect_by_file', s) for _, _, s in cfg['redirect_by_file']] + \
            [('primary', s) for s in cfg['primary'].values()] + \
            [('overrides', s) for s in cfg['overrides'].values()] + \
            [('owners', s) for s in cfg['owners'].values()] + [('edits', e['unit']) for e in cfg['edits']]
    bad = sorted({'%s: %s' % x for x in named if x[1] not in pos})
    if bad:
        raise Refuse('split.json names units that topics.json does not have: %s' % '; '.join(bad))
    result, unplaced = [], set()
    for op in O['ops']:
        f = op['f']
        old = X['owner'].get(f)
        if old is None:
            unplaced.add(f)
            continue
        causes, forced = [], None
        if op['regions']:
            causes, how = op['causes'], 'region'
        else:
            red = {cfg['redirect'][r] for r in op['raws'] if r in cfg['redirect']}
            red |= {s for r, p, s in cfg['redirect_by_file'] if r in op['raws'] and f.startswith(p)}
            if red:
                forced, how = min(red, key=pos.get), 'raw'
            elif op['tok'] and op['tok']['both'] and op['tok']['score'] >= 0.5:
                causes, how = op['tok']['c'], 'tokens2'
            elif op['test']:
                causes, how = op['test'], 'testL'
            else:
                how = 'none'
        cand = sorted({s for c in causes for s in X['claimers'].get(c, ())}, key=pos.get)
        new = forced or (cand[0] if cand and old not in cand else old)
        result.append(dict(f=f, i1=op['i1'], i2=op['i2'], j1=op['j1'], j2=op['j2'], old=old, new=new,
                           how=how, causes=causes, raws=op['raws'], cand=cand))
    if unplaced:
        raise Refuse('%d changed files have no unit (no topic path, no UoC trailer): %s; add them to "owners" '
                     'in split.json' % (len(unplaced), ', '.join(sorted(unplaced)[:20])))
    group_answer_files(result, dirty)
    keys = set()
    for r in result:
        key = '%s:%d' % (r['f'], r['i1'] + 1)
        keys.add(key)
        if key in cfg['overrides']:
            r['new'], r['how'] = cfg['overrides'][key], 'override'
    dump(dict(dirty=dirty, raw=raw, order=order, ops=result), 'assignment.json')

    moved = [r for r in result if r['new'] != r['old']]
    print('operations %d, moved from their per-file unit %d' % (len(result), len(moved)))
    for (o, n, h), v in sorted(Counter((r['old'], r['new'], r['how']) for r in moved).items(),
                               key=lambda kv: (pos[kv[0][0]], pos[kv[0][1]])):
        print('  %-30s -> %-30s %-8s %d' % (o, n, h, v))
    used = Counter(r['new'] for r in result)
    print('units with operations %d; without (no branch): %s' % (
        len(used), ', '.join(s for s in order if not used[s]) or 'none'))
    stale = sorted(set(cfg['overrides']) - keys)
    if stale:
        print('overrides that match no operation (DIRTY line numbers moved?): %s' % ', '.join(stale))
        return 1
    return 0


# ------------------------------------------------------------------ unit contents
class Files:
    """per file: the assigned operations, the DIRTY and RAW states, and how to compose a
    state with only some units' operations applied"""

    def __init__(self, A, cfg):
        self.dirty, self.raw = A['dirty'], A['raw']
        self.byf = defaultdict(list)
        for r in A['ops']:
            self.byf[r['f']].append(r)
        for ops in self.byf.values():
            ops.sort(key=lambda r: r['i1'])
        self.edits = defaultdict(list)
        for e in cfg['edits']:
            if not any(r['new'] == e['unit'] for r in self.byf.get(e['path'], [])):
                raise Refuse('split.json edit of %s from unit %s: that unit has no operation in the file'
                             % (e['path'], e['unit']))
            self.edits[e['path']].append(e)
        self._mode = {}

    def units_of(self, f):
        return {r['new'] for r in self.byf[f]}

    def mode(self, f):
        if f not in self._mode:
            for rev in (self.raw, self.dirty):
                ls = git('ls-tree', rev, '--', f).split()
                if ls:
                    self._mode[f] = ls[0]
                    break
        return self._mode[f]

    def compose(self, f, chosen):
        """bytes of f with the operations of the units in `chosen` applied, None if absent"""
        ops, M, Fl = self.byf[f], lines(self.dirty, f), lines(self.raw, f)
        out, p = [], 0
        for r in ops:
            out += M[p:r['i1']]
            out += Fl[r['j1']:r['j2']] if r['new'] in chosen else M[r['i1']:r['i2']]
            p = r['i2']
        out += M[p:]
        s = ''.join(out)
        for e in self.edits.get(f, []):
            if e['unit'] in chosen:
                if s.count(e['old']) != 1:
                    raise Refuse('split.json edit of %s (unit %s): "old" occurs %d times, must occur once'
                                 % (f, e['unit'], s.count(e['old'])))
                s = s.replace(e['old'], e['new'])
        whole = all(r['new'] in chosen for r in ops)
        present = exists(self.raw, f) if whole else exists(self.dirty, f)
        return s.encode('utf-8', 'surrogateescape') if present else None

    def tree(self, chosen, files=None):
        """tree object of DIRTY with the operations of `chosen` applied"""
        idx = bpath('index.tmp')
        env = dict(GIT_INDEX_FILE=idx)
        git('read-tree', self.dirty, env=env)
        info = []
        for f in (files if files is not None else self.byf):
            if not (self.units_of(f) & chosen):
                continue
            data = self.compose(f, chosen)
            if data is None:
                info.append('0 %s\t%s' % ('0' * 40, f))
            else:
                info.append('%s %s\t%s' % (self.mode(f), git('hash-object', '-w', '--stdin', inp=data).strip(), f))
        if info:
            git('update-index', '--index-info', inp='\n'.join(info) + '\n', env=env)
        t = git('write-tree', env=env).strip()
        os.unlink(idx)
        return t


def ordered_units(A):
    used = Counter(r['new'] for r in A['ops'])
    return [s for s in A['order'] if used[s]]


# ------------------------------------------------------------------ review
def cmd_review(a):
    A = load('assignment.json')
    kinds = set(a.how.split(',')) if a.how else None
    for r in A['ops']:
        if not a.all and r['new'] == r['old']:
            continue
        if (kinds and r['how'] not in kinds) or (a.path and a.path not in r['f']) or (a.unit and a.unit != r['new']):
            continue
        M, Fl = lines(A['dirty'], r['f']), lines(A['raw'], r['f'])
        print('### %s:%d %s -> %s [%s] cand=%s raw=%s' % (r['f'], r['i1'] + 1, r['old'], r['new'], r['how'],
                                                       ','.join(r['cand']), ','.join(r['raws'])))
        for c in r['causes'][:5]:
            print('#   %s %s' % (c, subject(c)[:64]))
        for ln in M[r['i1']:r['i2']][:10]:
            print('-' + ln.rstrip('\n')[:110])
        for ln in Fl[r['j1']:r['j2']][:10]:
            print('+' + ln.rstrip('\n')[:110])
    return 0


# ------------------------------------------------------------------ check
def words(tree):
    out = git('grep', '-h', '-o', '-I', '-E', r'[A-Za-z_][A-Za-z0-9_]{3,}', tree, *SRC, ok=(0, 1))
    return set(out.split())


def in_regions(text):
    """per 1-based line: inside a conflict region?"""
    flags, r = [False], False
    for ln in text.split('\n'):
        if ln.startswith('<<<<<<< '):
            r = True
        flags.append(r)
        if ln.startswith('>>>>>>> '):
            r = False
    return flags


def check_indep(A, FS):
    """every unit alone on DIRTY, merged one by one with `git merge-file` in unit order and
    in reverse: no conflicts, and the result is the final state"""
    order = A['order']
    problems = 0
    tmp = tempfile.mkdtemp(prefix='uoc_split_')
    every = set(order)
    for f in FS.byf:
        final = FS.compose(f, every)
        if not FS.edits.get(f) and final != content('%s:%s' % (FS.raw, f)):
            problems += 1
            print('indep: the operations of %s do not reproduce RAW' % f)
        us = [u for u in order if u in FS.units_of(f)]
        if len(us) == 1 or not exists(FS.dirty, f):
            continue
        base = os.path.join(tmp, 'base')
        with open(base, 'wb') as fh:
            fh.write(''.join(lines(FS.dirty, f)).encode('utf-8', 'surrogateescape'))
        for name, seq in (('forward', us), ('reverse', us[::-1])):
            cur, other = os.path.join(tmp, 'cur'), os.path.join(tmp, 'other')
            with open(cur, 'wb') as fh:
                fh.write(FS.compose(f, {seq[0]}) or b'')
            ok = True
            for u in seq[1:]:
                with open(other, 'wb') as fh:
                    fh.write(FS.compose(f, {u}) or b'')
                if subprocess.run(['git', 'merge-file', '-q', cur, base, other]).returncode:
                    ok = False
                    problems += 1
                    print('indep: %s: conflict in %s merging %s' % (name, f, u))
                    break
            if ok and open(cur, 'rb').read() != (final or b''):
                problems += 1
                print('indep: %s: merging the units of %s does not give the final state' % (name, f))
    shared = sum(1 for f in FS.byf if len(FS.units_of(f)) > 1)
    print('indep: %d files touched by several units, %d problems' % (shared, problems))
    return problems


def gone_identifiers(FS, mbase, cut, final_tree):
    g = load('gone.json', required=False)
    rng = '%s..%s' % (mbase, cut)
    if not g or g.get('range') != rng:
        g = dict(range=rng, words=sorted(words(mbase) - words(cut)))
        dump(g, 'gone.json')
    return set(g['words']) - words(final_tree)


def check_complete(A, FS, X, rem, gone):
    """in each unit's own tree, an identifier that the unit's own upstream commits removed
    from the code base (and the final tree no longer has) occurs only inside unresolved
    conflict regions"""
    bad = 0
    for s in ordered_units(A):
        mine = {c for c in X['claim'][s] if X['claimers'][c] == {s}}
        ids = sorted(x for x in gone if rem.get(x, set()) & mine)
        if not ids:
            continue
        tree = FS.tree({s})
        for i in range(0, len(ids), 200):
            pat = r'\b(' + '|'.join(map(re.escape, ids[i:i + 200])) + r')\b'
            hits = defaultdict(list)
            for ln in git('grep', '-n', '-I', '-E', pat, tree, *SRC, ok=(0, 1)).splitlines():
                _, f, n, txt = ln.split(':', 3)
                hits[f].append((int(n), txt))
            for f, hs in hits.items():
                flags = in_regions(content('%s:%s' % (tree, f)).decode('utf-8', 'replace'))
                for n, txt in hs:
                    if not flags[n]:
                        bad += 1
                        print('complete: %s: %s:%d: %s' % (s, f, n, txt.strip()[:90]))
    print('complete: %d removed-identifier uses left outside the conflicts' % bad)
    return bad


def check_removed(A, X, rem, gone):
    """an operation that drops a use of a removed identifier belongs to the unit of the
    commit that removed it"""
    pos = {s: i for i, s in enumerate(A['order'])}
    n = 0
    for r in A['ops']:
        f = r['f']
        if is_answer(f) or '/sql/' in f or f.endswith('.out'):
            continue
        M, Fl = lines(A['dirty'], f), lines(A['raw'], f)
        R = (toks(M[r['i1']:r['i2']]) - toks(Fl[r['j1']:r['j2']])) & gone
        us = sorted({s for t in R for c in rem.get(t, ()) for s in X['claimers'].get(c, ())}, key=pos.get)
        if us and r['new'] not in us:
            n += 1
            print('removed: %s:%d [%s] %s -> %s  %s' % (f, r['i1'] + 1, r['how'], r['new'], ','.join(us),
                                                       ' '.join(sorted(R)[:4])))
    print('removed: %d operations to re-check' % n)


def check_crossdeps(A):
    """operations of one file that introduce the same new identifier in different units"""
    byf = defaultdict(list)
    for r in A['ops']:
        byf[r['f']].append(r)
    n = 0
    for f, ops in byf.items():
        if is_answer(f) or f.endswith('.out') or len({r['new'] for r in ops}) < 2:
            continue
        M, Fl = lines(A['dirty'], f), lines(A['raw'], f)
        mt, intro = toks(M), defaultdict(set)
        for r in ops:
            for t in toks(Fl[r['j1']:r['j2']]) - mt:
                intro[t].add(r['new'])
        for t, us in intro.items():
            if len(us) > 1:
                n += 1
                where = sorted((r['i1'] + 1, r['new']) for r in ops if t in toks(Fl[r['j1']:r['j2']]))
                print('crossdeps: %s: %s: %s' % (f, t, ' '.join('%d:%s' % w for w in where)))
    print('crossdeps: %d identifiers introduced by several units of one file' % n)


def check_audit(A, X, cfg):
    """placements not backed by evidence: NONE (no cause), MULTI (cause claimed by several
    units), RAWX (bring-up commit whose Upstream: trailer names none of the unit's commits),
    OVR (manual overrides)"""
    raw_up = {}

    def upstream_of(r):
        if r not in raw_up:
            msg = git('log', '-1', '--format=%B', r)
            raw_up[r] = {short(h) for ln in re.findall(r'^Upstream:.*$', msg, re.M)
                         for h in re.findall(r'\b[0-9a-f]{7,40}\b', ln)}
        return raw_up[r]
    tests = cfg['tests_unit']
    out = defaultdict(list)
    for r in A['ops']:
        k, u = '%s:%d' % (r['f'], r['i1'] + 1), r['new']
        if r['how'] == 'override':
            out[u].append(('OVR', k, 'from ' + r['old']))
        if r['how'] == 'none' and u != tests:
            out[u].append(('NONE', k, 'raw=' + (','.join(r['raws']) or '?')))
        multi = [c for c in r['causes'] if len(X['claimers'].get(c, ())) > 1]
        if multi:
            others = sorted(set().union(*(X['claimers'][c] for c in multi)) - {u})
            out[u].append(('MULTI', k, '%s also claimed by %s' % (','.join(multi), ','.join(others))))
        if u == tests or not X['claim'][u]:
            continue
        for rw in r['raws']:
            if rw in cfg['regen_commits'] or rw.startswith('<'):
                continue
            up = upstream_of(rw)
            if up and not up & X['claim'][u]:
                out[u].append(('RAWX', k, 'raw %s upstream %s' % (rw, ' '.join(sorted(up)[:4]))))
    for s in A['order']:
        if not out[s]:
            continue
        print('audit: ===== %s' % s)
        for kind in ('OVR', 'MULTI', 'RAWX', 'NONE'):
            rows = [x for x in out[s] if x[0] == kind]
            for x in rows[:40]:
                print('audit:   %-5s %s  %s' % x)
            if len(rows) > 40:
                print('audit:   %-5s ... %d more' % (kind, len(rows) - 40))
    print('audit: %d placements to re-check' % sum(len(v) for v in out.values()))


def cmd_check(a):
    F, dirty, raw, mbase, cut = facts()
    cfg = config()
    X = units(F, cfg)
    A = load('assignment.json')
    if (A['dirty'], A['raw']) != (dirty, raw):
        raise Refuse('assignment.json was made for another DIRTY/RAW; re-run causes and assign')
    only = set(a.only.split(',')) if a.only else set(CHECKS)
    if only - set(CHECKS):
        raise Refuse('--only takes %s' % ','.join(CHECKS))
    FS = Files(A, cfg)
    failed = 0
    if 'indep' in only:
        failed += check_indep(A, FS)
    if only & {'complete', 'removed'}:
        _, rem, _ = token_index(mbase, cut)
        gone = gone_identifiers(FS, mbase, cut, FS.tree(set(A['order'])))
        if 'complete' in only:
            failed += check_complete(A, FS, X, rem, gone)
        if 'removed' in only:
            check_removed(A, X, rem, gone)
    if 'crossdeps' in only:
        check_crossdeps(A)
    if 'audit' in only:
        check_audit(A, X, cfg)
    return 1 if failed else 0


# ------------------------------------------------------------------ bundle
def numbers_for(order, save=False):
    """stable unit numbers: numbers.json keeps them; new units get the next free ones"""
    nums = load('numbers.json', required=False) or {}
    nxt = max(nums.values(), default=0) + 1
    new = []
    for s in order:
        if s not in nums:
            nums[s] = nxt
            new.append(s)
            nxt += 1
    if save and new:
        dump(nums, 'numbers.json')
    return nums, new


def cmd_bundle(a):
    cfg = config()
    A = load('assignment.json')
    FS = Files(A, cfg)
    order = ordered_units(A)
    nums, _ = numbers_for(order)
    for s in order:
        d = bpath(os.path.join('units', '%02d-%s' % (nums[s], s)))
        os.makedirs(d, exist_ok=True)
        tree = FS.tree({s})
        with open(os.path.join(d, 'diff.patch'), 'w') as o:
            o.write(git('diff', '--stat=200', A['dirty'], tree) + '\n' + git('diff', '-M', A['dirty'], tree))
        ops = [r for r in A['ops'] if r['new'] == s]
        with open(os.path.join(d, 'ops.txt'), 'w') as o:
            for r in ops:
                o.write('%s:%d from=%s how=%s causes=%s raw=%s\n' % (r['f'], r['i1'] + 1, r['old'], r['how'],
                                                                   ','.join(r['causes']), ','.join(r['raws'])))
        cause = Counter(c for r in ops for c in r['causes'])
        raws = Counter(c for r in ops for c in r['raws'] if not c.startswith('<'))
        with open(os.path.join(d, 'upstream.txt'), 'w') as o:
            o.write('# upstream commits behind the operations of this unit (operation count)\n')
            for c, n in cause.most_common():
                o.write('%s %4d %s\n' % (c, n, subject(c)))
        with open(os.path.join(d, 'raw.txt'), 'w') as o:
            for c, n in raws.most_common():
                o.write('===== raw %s (%d operations in this unit)\n%s\n' % (c, n, git('log', '-1', '--format=%B', c)))
        print('%s: %d operations, %d upstream causes, %d bring-up commits' % (
            os.path.basename(d), len(ops), len(cause), len(raws)))
    return 0


# ------------------------------------------------------------------ branches
def cmd_branches(a):
    cfg = config()
    A = load('assignment.json')
    FS = Files(A, cfg)
    order = ordered_units(A)
    nums, new = numbers_for(order, save=a.create)
    only = {int(x) for x in a.only.split(',')} if a.only else None
    todo = sorted((nums[s], s) for s in order if only is None or nums[s] in only)
    missing = [s for _, s in todo if not os.path.exists(bpath(os.path.join('msg', s + '.txt')))]
    if missing and a.create:
        raise Refuse('no description in %s/msg/ for: %s' % (DIR, ' '.join(missing)))
    names = ['%s-uoc%d' % (a.prefix, n) for n, _ in todo] + (['%s-base' % a.prefix] if a.base else [])
    taken = [n for n in names if git('rev-parse', '--verify', '-q', 'refs/heads/' + n, ok=(0, 1)).strip()]
    if a.create and taken and not a.force:
        raise Refuse('branches exist (pass --force to move them): %s' % ' '.join(taken))
    plan = [('%s-base' % a.prefix, A['dirty'], 'the merge with conflict markers')] if a.base else []
    for n, s in todo:
        tree = FS.tree({s})
        mine = [r for r in A['ops'] if r['new'] == s]
        src = cfg['author_from'].get(s) or next(
            (c for c, _ in Counter(c for r in mine for c in r['raws'] if not c.startswith('<')).most_common()), None)
        env = None
        if src:
            an, ae, ad = git('log', '-1', '--format=%an%x00%ae%x00%ad', '--date=raw', src).split('\x00')
            env = dict(GIT_AUTHOR_NAME=an, GIT_AUTHOR_EMAIL=ae, GIT_AUTHOR_DATE=ad.strip())
        if s in missing:
            plan.append(('%s-uoc%d' % (a.prefix, n), tree, '(tree; no msg/%s.txt yet) %s' % (s, s)))
            continue
        with open(bpath(os.path.join('msg', s + '.txt'))) as fh:
            body = fh.read().strip('\n')
        sha = git('commit-tree', tree, '-p', A['dirty'], '-F', '-', inp='UoC %d: %s\n' % (n, body),
                  env=env).strip() if a.create else tree
        plan.append(('%s-uoc%d' % (a.prefix, n), sha, 'UoC %d: %s%s' % (
            n, body.splitlines()[0], ' (new number)' if s in new else '')))
    for name, sha, what in plan:
        if a.create:
            git('branch', *(['-f'] if a.force else []), name, sha)
        print('%-28s %s  %s' % (name, short(sha), what))
    if not a.create:
        print('dry run: hashes are trees; pass --create to commit and create the branches')
    else:
        print('push with: git push origin %s' % ' '.join(n for n, _, _ in plan))
    return 0


# ------------------------------------------------------------------ links
def cmd_links(a):
    try:
        out = subprocess.run(['gh', 'pr', 'list', '-R', a.repo, '--state', 'all', '--limit', '500',
                              '--search', 'head:%s-uoc' % a.prefix, '--json', 'number,headRefName,url,state'],
                             capture_output=True, check=True).stdout.decode()
    except FileNotFoundError:
        raise Refuse('the gh CLI is not installed; install it and run `gh auth login`')
    except subprocess.CalledProcessError as e:
        raise Refuse('gh pr list failed: %s' % e.stderr.decode(errors='replace').strip()[:400])
    urls = {}
    for p in sorted(json.loads(out), key=lambda p: (p['state'] != 'CLOSED', p['number'])):
        m = re.fullmatch(re.escape(a.prefix) + r'-uoc(\d+)', p['headRefName'])
        if m:
            urls[int(m.group(1))] = p['url']          # an open or merged PR wins over a closed one

    def link(m):
        n = int(m.group(1))
        if n not in urls:
            raise Refuse('{U%d}: no PR from %s-uoc%d' % (n, a.prefix, n))
        return urls[n]
    with open(a.template) as fh:
        sys.stdout.write(re.sub(r'\{U(\d+)\}', link, fh.read()))
    return 0


# ------------------------------------------------------------------ main
def main(argv=None):
    global REPO, DIR
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                 epilog='See the module docstring (head -50 %s) for the flow.' % os.path.basename(__file__),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-C', dest='gitdir', help='greengage_sync checkout (default: current directory)')
    ap.add_argument('--dir', required=True, help='batch directory: facts.json, topics.json, uocs.json, split.json')
    sp = ap.add_subparsers(dest='cmd', metavar='SUBCOMMAND')
    sp.add_parser('causes', help='cut the DIRTY -> RAW change into operations and find their causes')
    sp.add_parser('assign', help='give every operation a unit')
    p = sp.add_parser('review', help='print moved operations with content and causes')
    p.add_argument('--how', help='only these placements: region,raw,tokens2,testL,group,mirror,override,none')
    p.add_argument('--path', help='only files whose path contains this')
    p.add_argument('--unit', help='only operations given to this unit')
    p.add_argument('--all', action='store_true', help='also operations that stay in their per-file unit')
    p = sp.add_parser('check', help='prove the units independent and complete; list placements to re-check')
    p.add_argument('--only', help='comma-separated subset of %s' % ','.join(CHECKS))
    sp.add_parser('bundle', help='write units/NN-slug/ material for the descriptions')
    p = sp.add_parser('branches', help='create <prefix>-base and <prefix>-uocN')
    p.add_argument('prefix', help='branch prefix, e.g. sync-15x-b2')
    p.add_argument('--create', action='store_true', help='commit and create the branches (default: dry run)')
    p.add_argument('--force', action='store_true', help='move existing branches')
    p.add_argument('--base', action='store_true', help='also create <prefix>-base at DIRTY')
    p.add_argument('--only', help='only these unit numbers, comma-separated')
    p = sp.add_parser('links', help='replace {Un} in a PR description with the URL of the PR from <prefix>-uocN')
    p.add_argument('prefix')
    p.add_argument('template')
    p.add_argument('--repo', default='GreengageDB/greengage_sync')
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    REPO, DIR = a.gitdir, a.dir
    try:
        if subprocess.run(['git'] + (['-C', REPO] if REPO else []) + ['rev-parse', '--git-dir'],
                          capture_output=True).returncode:
            raise Refuse('%s is not a git repository; run from the greengage_sync checkout or pass -C' % (REPO or '.'))
        if not os.path.isdir(DIR):
            raise Refuse('batch directory %s does not exist' % DIR)
        return {'causes': cmd_causes, 'assign': cmd_assign, 'review': cmd_review, 'check': cmd_check,
                'bundle': cmd_bundle, 'branches': cmd_branches, 'links': cmd_links}[a.cmd](a)
    except Refuse as e:
        print('uoc_split.py %s: %s' % (a.cmd, e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
