#!/usr/bin/env python3
"""Drop from regenerated answer files what gpdiff does not need.

usage: gpdiff_min.py [-C REPO] -o OUTDIR [-i INIT_FILE]... [-r RESULTS]... BASE HEAD [FILE...]

  BASE, HEAD  revisions: the PR's merge base and head
  FILE        answer files to process (paths in the repository), default every
              */expected/*.out changed in BASE..HEAD
  -C REPO     the checkout (default: the one around the current directory); gpdiff.pl
              and atmsort.pm are taken from its src/test/regress
  -o OUTDIR   where to write the results
  -i INIT     an extra init file (path in the repository, read at HEAD), for every file;
              src/test/regress/init_file is always used, and
              src/test/isolation2/init_file_isolation2 for files under src/test/isolation2
  -r RESULTS  a pg_regress results/ directory (e.g. from a CI artifact) to check the
              outputs against: X_optimizer.out is compared with the X.out of a results
              dir whose path contains "orca", the other files with the remaining dirs

Every hunk of BASE..HEAD is put back to its BASE side unless gpdiff (with HEAD's init
files) then sees a difference from the HEAD file. Rows of one "(N rows)" result go back
together, so reordered rows of an unordered result are restored as a whole. Conflict
markers must stay as in HEAD. After that, from the lines the PR still adds (not from
lines kept from BASE), strip_gpdiff_ignored.pl removes what gpdiff ignores: HINT,
Optimizer/Settings lines, DISTRIBUTED BY notices, seg/pid tails, ...

OUTDIR gets base/, head/ (the inputs), min/ (step 1) and fin/ (the result), each with the
files at their repository paths. Copy fin/<path> over <path> on the PR branch and rerun
the test.
"""
import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STRIP = os.path.join(HERE, 'strip_gpdiff_ignored.pl')
MARK = re.compile(r'^(<<<<<<< |\|\|\|\|\|\|\| |=======$|>>>>>>> )')
REPO = None


def git(*a):
    return subprocess.check_output(['git', '-C', REPO, *a], text=True)


def show(rev, path):
    r = subprocess.run(['git', '-C', REPO, 'show', f'{rev}:{path}'], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ''


def gpdiff(inits, exp, res):
    args = [x for i in inits for x in ('--gpd_init', i)]
    return subprocess.run(['perl', f'{REPO}/src/test/regress/gpdiff.pl', '-I', 'HINT:', '-I', 'CONTEXT:',
                           '-I', 'GP_IGNORE:', *args, exp, res],
                          capture_output=True, text=True).stdout.strip()


def minimize(base, head, inits, tmp):
    ops = difflib.SequenceMatcher(None, base, head, autojunk=False).get_opcodes()
    hunks = [i for i, o in enumerate(ops) if o[0] != 'equal']
    head_marks = [l for l in head if MARK.match(l)]
    head_path = f'{tmp}/head'
    with open(head_path, 'w') as f:
        f.writelines(head)
    rev = set()

    def build(r):
        out = []
        for i, (t, a1, a2, b1, b2) in enumerate(ops):
            out += base[a1:a2] if (t == 'equal' or i in r) else head[b1:b2]
        return out

    def equiv(r):
        cand = build(r)
        if [l for l in cand if MARK.match(l)] != head_marks:
            return False
        with open(f'{tmp}/cand', 'w') as f:
            f.writelines(cand)
        return gpdiff(inits, f'{tmp}/cand', head_path) == ''

    def ddmin(units):
        # put back a set of units wholesale if possible, else split it
        if not units:
            return
        flat = [h for u in units for h in u]
        if equiv(rev | set(flat)):
            rev.update(flat)
        elif len(units) > 1:
            m = len(units) // 2
            ddmin(units[:m])
            ddmin(units[m:])

    # result block of each HEAD line: the rows between the header
    # separator and "(N rows)" make one block
    blk, n = [], 0
    for l in head:
        if re.match(r'^-+(\+-+)*$', l.strip()):
            n += 1
        blk.append(n)
        if re.match(r'^\(\d+ rows?\)$', l.strip()):
            n += 1
    groups = {}
    for h in hunks:
        groups.setdefault(blk[min(ops[h][3], len(head) - 1)] if head else 0, []).append(h)
    ddmin(list(groups.values()))
    ddmin([[h] for h in hunks if h not in rev])
    # a row moved elsewhere: its delete and insert must go back together
    for w in (2, 3, 4, 6, 8):
        rest = [h for h in hunks if h not in rev]
        i = 0
        while i + w <= len(rest):
            if equiv(rev | set(rest[i:i + w])):
                rev.update(rest[i:i + w])
                i += w
            else:
                i += 1
    return build(rev), len(hunks), len(hunks) - len(rev)


def strip_added(base, out, inits, tmp):
    p = f'{tmp}/strip.out'
    with open(p, 'w') as f:
        f.writelines(out)
    subprocess.run(['perl', STRIP, *[x for i in inits for x in ('-i', i)], p], check=True, capture_output=True)
    st = open(p).read().splitlines(keepends=True)

    # lines of the HEAD side of a conflict in BASE are Greengage's own, not
    # added ones
    ours, side = [], None
    for l in base:
        if l.startswith('<<<<<<< '):
            side = 'ours'
        elif l.startswith('||||||| ') or l.rstrip('\n') == '=======':
            side = 'theirs'
        elif l.startswith('>>>>>>> '):
            side = None
        elif side != 'theirs':
            ours.append(l)
    added = set()
    for t, a1, a2, b1, b2 in difflib.SequenceMatcher(None, ours, out, autojunk=False).get_opcodes():
        if t != 'equal':
            added.update(range(b1, b2))
    # what the strip did to each line: None = removed, str = text left
    fate = {}
    for t, a1, a2, b1, b2 in difflib.SequenceMatcher(None, out, st, autojunk=False).get_opcodes():
        if t == 'delete':
            fate.update((i, None) for i in range(a1, a2))
        elif t == 'replace' and a2 - a1 == b2 - b1:
            fate.update((i, st[b1 + k]) for k, i in enumerate(range(a1, a2)))
        elif t == 'replace':
            j = b1
            for i in range(a1, a2):
                if j < b2 and out[i].startswith(st[j].rstrip('\n')[:20]):
                    fate[i] = st[j]
                    j += 1
                else:
                    fate[i] = None
    fin, n = [], 0
    for i, l in enumerate(out):
        if i in added and i in fate:
            n += 1
            if fate[i] is not None:
                fin.append(fate[i])
        else:
            fin.append(l)
    return fin, n


def nchanged(a, b):
    return sum(max(a2 - a1, b2 - b1) for t, a1, a2, b1, b2 in
               difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if t != 'equal')


def write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.writelines(lines)


def main():
    global REPO
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-C', dest='repo')
    ap.add_argument('-o', required=True)
    ap.add_argument('-i', action='append', default=[])
    ap.add_argument('-r', action='append', default=[])
    ap.add_argument('base')
    ap.add_argument('head')
    ap.add_argument('files', nargs='*')
    a = ap.parse_args()
    REPO = subprocess.check_output(['git', '-C', a.repo or '.', 'rev-parse', '--show-toplevel'], text=True).strip()
    if not os.path.exists(f'{REPO}/src/test/regress/gpdiff.pl'):
        sys.exit(f'gpdiff_min.py: {REPO} has no src/test/regress/gpdiff.pl; pass the Greengage checkout with -C')

    files = a.files or git('diff', '--name-only', '--diff-filter=AM', f'{a.base}..{a.head}', '--',
                           ':(glob)**/expected/*.out').split()
    os.makedirs(a.o, exist_ok=True)
    tmproot = tempfile.mkdtemp(dir=a.o)
    initfiles = {}

    def inits(path):
        """HEAD's init files for an answer file, copied into OUTDIR/init/"""
        want = ['src/test/regress/init_file'] + a.i
        if path.startswith('src/test/isolation2/'):
            want.append('src/test/isolation2/init_file_isolation2')
        for w in want:
            if w not in initfiles:
                text = show(a.head, w)
                if not text:
                    sys.exit(f'gpdiff_min.py: no {w} at {a.head}')
                initfiles[w] = os.path.join(a.o, 'init', w)
                write(initfiles[w], [text])
        return [initfiles[w] for w in want]

    tot_head = tot_fin = 0
    for path in files:
        base = show(a.base, path).splitlines(keepends=True)
        head = show(a.head, path).splitlines(keepends=True)
        for d, ls in (('base', base), ('head', head)):
            write(f'{a.o}/{d}/{path}', ls)
        ini = inits(path)
        tmp = tempfile.mkdtemp(dir=tmproot)
        out, nh, kept = minimize(base, head, ini, tmp)
        write(f'{a.o}/min/{path}', out)
        fin, ns = strip_added(base, out, ini, tmp)
        write(f'{a.o}/fin/{path}', fin)
        shutil.rmtree(tmp)

        bad = gpdiff(ini, f'{a.o}/fin/{path}', f'{a.o}/head/{path}') != ''
        ch, cf = nchanged(base, head), nchanged(base, fin)
        tot_head += ch
        tot_fin += cf
        line = f'{path}: hunks {nh}, kept {kept}, stripped {ns}; lines changed {ch} -> {cf}'
        if bad:
            line += '; DIFFERS FROM HEAD'
        test = os.path.basename(path)[:-4]
        orca = test.endswith('_optimizer')
        test = test[:-len('_optimizer')] if orca else test
        for r in a.r:
            if ('orca' in r) != orca or not os.path.exists(f'{r}/{test}.out'):
                continue
            h = len(gpdiff(ini, f'{a.o}/head/{path}', f'{r}/{test}.out').splitlines())
            n = len(gpdiff(ini, f'{a.o}/fin/{path}', f'{r}/{test}.out').splitlines())
            line += f'; vs results head/fin {h}/{n}' + ('' if h == n else ' MISMATCH')
        print(line, flush=True)
    os.rmdir(tmproot)
    print(f'total lines changed {tot_head} -> {tot_fin}')


if __name__ == '__main__':
    sys.exit(main())
