#!/usr/bin/env python3
"""Review pull requests for the units of change (UoC) of a greengage_sync batch PR.

A batch PR (built by pg_batch.py, skill greengage-pg-batch) carries the upstream batch
merge followed by one commit per unit, "UoC N/M: <title>". A review PR for unit N has
    base  <batch-branch>-uoc<N>-base   at the commit before the unit
    head  <batch-branch>-uoc<N>        at the unit commit (review fixes are pushed here)
so its diff is exactly that unit. Once approved it is retargeted to the batch branch,
where its diff shrinks to the review fixes, and merged into the batch PR.

    open      create both branches and the review PR for unit N
    retarget  move an approved review PR's base to the batch branch, so it can be merged
    status    refresh the "Review PR" column of the batch PR's unit table

Usage:
    uoc_review.py open     --pr PR --uoc N [--repo OWNER/REPO] [--draft] [--reviewer LOGIN]... [--force] [--dry-run]
    uoc_review.py retarget --pr PR --uoc N [--repo OWNER/REPO] [--force] [--dry-run]
    uoc_review.py status   --pr PR [--repo OWNER/REPO] [--dry-run]

PR is the batch PR, as a number or a URL (https://github.com/OWNER/REPO/pull/626).
Without --repo the repository comes from the URL, or from `gh repo view` in the current
directory. Everything goes through the GitHub API with `gh api` (authenticated gh CLI
required); no local checkout is needed. --dry-run prints what would change and writes nothing.

Review PRs are found by the marker the open subcommand writes into their body
(<!-- uoc-review: pr=626 uoc=7 ... -->) or by their head branch name, so PRs opened by hand
with the documented branch names are found too.

Exit status: 0 done (or nothing to do); 1 refused on a finding (a review PR for the unit
already exists, the unit is upstream-only, the PR to retarget is not approved); 2 usage or
environment error (gh missing or unauthenticated, PR or unit not found).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

UOC_SUBJECT = re.compile(r'^UoC (\d+)/(\d+): (.*)$')
MARKER = re.compile(r'<!-- uoc-review: pr=(\d+) uoc=(\d+)\b[^>]*-->')
STATUS_BEGIN, STATUS_END = '<!-- uoc-review-status -->', '<!-- /uoc-review-status -->'


class Refuse(Exception):
    """usage or environment error: exit 2"""


class Finding(Exception):
    """refused on a finding: exit 1"""


# ------------------------------------------------------------------ gh plumbing
def gh(*args, inp=None, ok404=False):
    try:
        r = subprocess.run(['gh'] + list(args), capture_output=True, text=True, input=inp)
    except FileNotFoundError:
        raise Refuse('the gh CLI is not installed; install it and run `gh auth login`')
    if r.returncode:
        if ok404 and ('HTTP 404' in r.stderr or 'Not Found' in r.stderr):
            return None
        raise Refuse('gh %s failed: %s' % (' '.join(args[:3]), r.stderr.strip()[:500]))
    return r.stdout


def api(path, *fields, method=None, ok404=False):
    args = ['api'] + (['-X', method] if method else []) + [path] + list(fields)
    out = gh(*args, ok404=ok404)
    return None if out is None else (json.loads(out) if out.strip() else {})


def graphql(query):
    return json.loads(gh('api', 'graphql', '-f', 'query=' + query))['data']


def resolve_pr(pr, repo):
    m = re.match(r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)', pr)
    if m:
        repo, num = repo or m.group(1), int(m.group(2))
    elif pr.isdigit():
        num = int(pr)
    else:
        raise Refuse('--pr must be a number or a pull request URL, not %r' % pr)
    if not repo:
        repo = gh('repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner').strip()
    p = api('repos/%s/pulls/%d' % (repo, num), ok404=True)
    if p is None:
        raise Refuse('%s#%d does not exist (or gh cannot see it)' % (repo, num))
    return repo, p


def find_unit(repo, batch, n, pages=10):
    """the 'UoC N/M:' commit on the batch PR head -> commit JSON from the commits list"""
    for page in range(1, pages + 1):
        cs = api('repos/%s/commits?sha=%s&per_page=100&page=%d' % (repo, batch['head']['sha'], page))
        for c in cs:
            m = UOC_SUBJECT.match(c['commit']['message'].split('\n', 1)[0])
            if m and int(m.group(1)) == n:
                return c
        if len(cs) < 100:
            break
    raise Refuse('no commit "UoC %d/..." on %s (branch %s); is #%d a batch PR built by pg_batch.py?'
                 % (n, repo, batch['head']['ref'], batch['number']))


def review_prs(repo, batch):
    """{uoc number: [pull request JSON]} for every review PR of the batch PR"""
    head = batch['head']['ref']
    by_head = re.compile(r'^%s-uoc(\d+)$' % re.escape(head))
    since = batch['created_at']
    found = {}
    for page in range(1, 50):
        ps = api('repos/%s/pulls?state=all&sort=created&direction=desc&per_page=100&page=%d' % (repo, page))
        for p in ps:
            if p['number'] == batch['number']:
                continue
            m = MARKER.search(p.get('body') or '')
            if m and int(m.group(1)) == batch['number']:
                found.setdefault(int(m.group(2)), []).append(p)
                continue
            m = by_head.match(p['head']['ref'])
            if m and p['head']['repo'] and p['head']['repo']['full_name'] == repo:
                found.setdefault(int(m.group(1)), []).append(p)
        if len(ps) < 100 or ps[-1]['created_at'] < since:
            break
    for v in found.values():
        v.sort(key=lambda p: p['number'])
    return found


def ref_sha(repo, name):
    r = api('repos/%s/git/ref/heads/%s' % (repo, name), ok404=True)
    return r['object']['sha'] if r else None


def contains(repo, ref_sha_, commit):
    """does the branch at ref_sha_ contain commit?"""
    c = api('repos/%s/compare/%s...%s' % (repo, commit, ref_sha_))
    return c['status'] in ('identical', 'ahead')


def approved(repo, number):
    latest = {}
    for r in api('repos/%s/pulls/%d/reviews?per_page=100' % (repo, number)):
        if r['state'] in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            latest[r['user']['login']] = r['state']
    return 'APPROVED' in latest.values() and 'CHANGES_REQUESTED' not in latest.values()


def write_tmp(text):
    fd, path = tempfile.mkstemp(prefix='uoc_review_', suffix='.md')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    return path


# ------------------------------------------------------------------ open
def review_body(batch, n, total, title, commit, msg, base_ref, head_ref):
    status = re.search(r'^Review status: (.+)$((?:\n  .+)*)', msg, re.M)
    st = ''
    if status:
        st = '**Review status: %s**%s\n\n' % (status.group(1).strip(), ''.join(
            '\n- ' + ln.strip() for ln in status.group(2).splitlines() if ln.strip()))
    fence = '````' if '```' in msg else '```'
    return (
        'Review of **UoC %d/%d: %s** from #%d (batch branch `%s`).\n\n'
        'This PR holds one commit, the unit commit %s of the batch PR. Its diff is the Greengage side of the unit: '
        'the conflict resolutions (they remove the conflict markers committed in the batch merge, so each hunk shows '
        'both sides and the chosen result) and the fixes found by local testing and CI. The unit\'s upstream commits '
        'are listed in the commit message below; they are already reviewed upstream and are not part of this diff.\n\n'
        '%s'
        '<details><summary>Unit commit message</summary>\n\n%s\n%s\n%s\n\n</details>\n\n'
        '**Finishing the review.** Push review fixes to `%s`. When the review is approved, retarget this PR\'s base '
        'from `%s` to `%s` (the diff then shows only the fixes) and merge it with a merge commit. The batch PR\'s '
        '**Review PR** column follows this PR\'s state.\n\n'
        '<!-- uoc-review: pr=%d uoc=%d commit=%s -->\n' % (
            n, total, title, batch['number'], batch['head']['ref'], commit[:11], st, fence, msg.strip(), fence,
            head_ref, base_ref, batch['head']['ref'], batch['number'], n, commit))


def cmd_open(a):
    repo, batch = resolve_pr(a.pr, a.repo)
    c = find_unit(repo, batch, a.uoc)
    sha, msg = c['sha'], c['commit']['message']
    _, total, title = UOC_SUBJECT.match(msg.split('\n', 1)[0]).groups()
    parent = c['parents'][0]['sha']
    full = api('repos/%s/commits/%s' % (repo, sha))
    if not full.get('files') and not a.force:
        raise Finding('UoC %d (%s) is upstream-only: its commit %s is empty, so there is nothing to review. '
                      'Pass --force to open a PR anyway.' % (a.uoc, title, sha[:11]))
    existing = [p for p in review_prs(repo, batch).get(a.uoc, []) if p['state'] == 'open']
    if existing:
        raise Finding('UoC %d already has an open review PR: %s' % (a.uoc, ', '.join(p['html_url'] for p in existing)))
    head = batch['head']['ref']
    base_ref, head_ref = '%s-uoc%d-base' % (head, a.uoc), '%s-uoc%d' % (head, a.uoc)
    plan = []
    for name, want in ((base_ref, parent), (head_ref, sha)):
        have = ref_sha(repo, name)
        if have is None:
            plan.append(('create', name, want))
        elif have == want or (name == head_ref and contains(repo, have, sha)):
            plan.append(('reuse', name, have))
        else:
            raise Finding('branch %s exists at %s, which is not the unit commit %s or a descendant of it; '
                          'delete it or open the review PR by hand' % (name, have[:11], want[:11]))
    pr_title = 'Review %s UoC %d: %s' % (head, a.uoc, title)
    body = review_body(batch, a.uoc, int(total), title, sha, msg, base_ref, head_ref)
    print('batch PR  %s#%d (%s), unit commit %s, %d files' % (repo, batch['number'], head, sha[:11], len(full['files'])))
    for act, name, s in plan:
        print('%-6s branch %s at %s' % (act, name, s[:11]))
    print('open PR   %s  (%s <- %s)%s' % (pr_title, base_ref, head_ref, ' as draft' if a.draft else ''))
    if a.reviewer:
        print('request   %s' % ', '.join(a.reviewer))
    if a.dry_run:
        print('\n--- body ---\n' + body)
        return 0
    for act, name, s in plan:
        if act == 'create':
            api('repos/%s/git/refs' % repo, '-f', 'ref=refs/heads/' + name, '-f', 'sha=' + s, method='POST')
    path = write_tmp(body)
    try:
        p = api('repos/%s/pulls' % repo, '-f', 'title=' + pr_title, '-f', 'head=' + head_ref, '-f', 'base=' + base_ref,
                '-F', 'body=@' + path, '-F', 'draft=%s' % ('true' if a.draft else 'false'), method='POST')
    finally:
        os.unlink(path)
    if a.reviewer:
        api('repos/%s/pulls/%d/requested_reviewers' % (repo, p['number']),
            *[x for r in a.reviewer for x in ('-f', 'reviewers[]=' + r)], method='POST')
    print('opened %s' % p['html_url'])
    return 0


# ------------------------------------------------------------------ retarget
def cmd_retarget(a):
    repo, batch = resolve_pr(a.pr, a.repo)
    prs = [p for p in review_prs(repo, batch).get(a.uoc, []) if p['state'] == 'open']
    if not prs:
        raise Refuse('UoC %d of #%d has no open review PR' % (a.uoc, batch['number']))
    if len(prs) > 1:
        raise Refuse('UoC %d has several open review PRs (%s); retarget the one you mean in the GitHub UI'
                     % (a.uoc, ', '.join('#%d' % p['number'] for p in prs)))
    p, target = prs[0], batch['head']['ref']
    if p['base']['ref'] == target:
        print('#%d already targets %s' % (p['number'], target))
        return 0
    if not approved(repo, p['number']) and not a.force:
        raise Finding('#%d is not approved (or a reviewer still requests changes); pass --force to retarget anyway'
                      % p['number'])
    print('retarget #%d: base %s -> %s' % (p['number'], p['base']['ref'], target))
    if not a.dry_run:
        api('repos/%s/pulls/%d' % (repo, p['number']), '-f', 'base=' + target, method='PATCH')
        print('done; merge it with a merge commit (not squash or rebase)')
    return 0


# ------------------------------------------------------------------ status
def pr_states(repo, numbers):
    owner, name = repo.split('/', 1)
    out = {}
    for i in range(0, len(numbers), 50):
        q = ' '.join('p%d: pullRequest(number: %d) { number state isDraft reviewDecision baseRefName '
                     'latestOpinionatedReviews(first: 30) { nodes { state } } reviewRequests(first: 1) { totalCount } '
                     'commits(last: 1) { nodes { commit { statusCheckRollup { state } } } } }' % (n, n)
                     for n in numbers[i:i + 50])
        d = graphql('query { repository(owner: "%s", name: "%s") { %s } }' % (owner, name, q))['repository']
        out.update({v['number']: v for v in d.values() if v})
    return out


def state_text(s, batch_head):
    if s['state'] == 'MERGED':
        return 'merged'
    if s['state'] == 'CLOSED':
        return 'closed'
    if s['isDraft']:
        t = 'draft'
    else:
        # reviewDecision is null when the base branch requires no review (the uoc<N>-base
        # branches are unprotected), so fall back to each reviewer's latest verdict
        verdicts = [r['state'] for r in s['latestOpinionatedReviews']['nodes']]
        decision = s['reviewDecision'] or ('CHANGES_REQUESTED' if 'CHANGES_REQUESTED' in verdicts else
                                           'APPROVED' if 'APPROVED' in verdicts else
                                           'REVIEW_REQUIRED' if s['reviewRequests']['totalCount'] else None)
        t = {'APPROVED': 'approved', 'CHANGES_REQUESTED': 'changes requested',
             'REVIEW_REQUIRED': 'in review'}.get(decision, 'open')
        if t == 'approved':
            t += ', ready to merge' if s['baseRefName'] == batch_head else ', to retarget'
    nodes = s['commits']['nodes']
    ci = nodes and nodes[0]['commit']['statusCheckRollup'] and nodes[0]['commit']['statusCheckRollup']['state']
    if ci in ('FAILURE', 'ERROR'):
        t += ', CI failing'
    elif ci in ('PENDING', 'EXPECTED'):
        t += ', CI running'
    return t


def split_row(ln):
    cells, cur, esc = [], '', False
    for ch in ln.strip()[1:-1] if ln.strip().endswith('|') else ln.strip()[1:]:
        if ch == '|' and not esc:
            cells.append(cur)
            cur = ''
        else:
            cur += ch
        esc = ch == '\\' and not esc
    cells.append(cur)
    return cells


def unit_table(lines):
    """-> (header line index, Review PR column, {unit number: (line index, cells)})"""
    hdr = next((i for i, ln in enumerate(lines) if ln.startswith('|') and re.search(r'\|\s*Unit of change\s*\|', ln)
                and 'Review PR' in ln), None)
    if hdr is None:
        raise Refuse('the batch PR body has no unit table (a header row with "Unit of change" and "Review PR")')
    col = [c.strip() for c in split_row(lines[hdr])].index('Review PR')
    rows, i = {}, hdr + 2
    while i < len(lines) and lines[i].startswith('|'):
        cells = split_row(lines[i])
        if cells[0].strip().isdigit() and col < len(cells):
            rows[int(cells[0].strip())] = (i, cells)
        i += 1
    return hdr, col, rows


def update_body(body, cell, summary):
    """rewrite the Review PR column with cell[n] and the status line above the table -> (text, rows changed)"""
    lines = body.split('\n')
    hdr, col, rows = unit_table(lines)
    changed = 0
    for n, (i, cells) in rows.items():
        if cell[n] != cells[col].strip():
            cells[col] = ' %s ' % cell[n]
            lines[i] = '|' + '|'.join(cells) + '|'
            changed += 1
    text = '\n'.join(lines)
    block = '%s\n%s\n%s' % (STATUS_BEGIN, summary, STATUS_END)
    if STATUS_BEGIN in text and STATUS_END in text:
        text = re.sub(re.escape(STATUS_BEGIN) + r'.*?' + re.escape(STATUS_END), lambda m: block, text, flags=re.S)
    else:
        lines = text.split('\n')
        lines[hdr:hdr] = [block, '']
        text = '\n'.join(lines)
    return text, changed


STAMP = re.compile(r' \(Updated [^)]*\)\.')


def cmd_status(a):
    repo, batch = resolve_pr(a.pr, a.repo)
    found = review_prs(repo, batch)
    states = pr_states(repo, sorted(p['number'] for v in found.values() for p in v))
    head = batch['head']['ref']
    texts = {}
    for n, prs in found.items():
        texts[n] = [(p['number'], state_text(states[p['number']], head) if p['number'] in states else p['state'])
                    for p in prs]
    for attempt in range(3):
        old = batch['body'] or ''
        _, _, rows = unit_table(old.split('\n'))
        cell, tally, without = {}, {}, []
        for n, (_, cells) in rows.items():
            row = ' '.join(cells).lower()
            if n in texts:
                cell[n] = '<br>'.join('#%d %s' % t for t in texts[n])
                key = texts[n][-1][1].split(',')[0]
                tally[key] = tally.get(key, 0) + 1
            else:
                cell[n] = '—'
                if 'must review' in row and 'upstream only' not in row:
                    without.append(n)
        orphans = sorted(set(texts) - set(rows))
        summary = 'Review PRs: %s. Must-review units without a review PR: %s. (Updated %s).' % (
            ', '.join('%d %s' % (v, k) for k, v in sorted(tally.items(), key=lambda kv: -kv[1])) or 'none yet',
            ', '.join('UoC %d' % n for n in without) or 'none',
            datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
        new, changed = update_body(old, cell, summary)
        print('%s#%d: %d review PRs for %d units; %d table rows change' % (
            repo, batch['number'], sum(len(v) for v in texts.values()), len(texts), changed))
        for n in sorted(texts):
            print('  UoC %-3d %s' % (n, '; '.join('#%d %s' % t for t in texts[n])))
        if orphans:
            print('  review PRs for units not in the table: %s' % ', '.join('UoC %d' % n for n in orphans))
        print('  ' + summary)
        if STAMP.sub('', new) == STAMP.sub('', old):
            print('no change')
            return 0
        if a.dry_run:
            return 0
        fresh = api('repos/%s/pulls/%d' % (repo, batch['number']))
        if (fresh['body'] or '') != old:          # edited meanwhile: recompute from the fresh body
            batch = fresh
            continue
        path = write_tmp(new)
        try:
            api('repos/%s/pulls/%d' % (repo, batch['number']), '-F', 'body=@' + path, method='PATCH')
        finally:
            os.unlink(path)
        print('updated %s' % batch['html_url'])
        return 0
    raise Refuse('the batch PR body kept changing while updating it; run again')


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                 epilog='See the module docstring for the branch layout and the marker.',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', metavar='SUBCOMMAND')
    for name, hlp in (('open', 'create the branches and the review PR for one unit'),
                      ('retarget', 'move an approved review PR onto the batch branch'),
                      ('status', 'refresh the Review PR column of the batch PR')):
        p = sp.add_parser(name, help=hlp)
        p.add_argument('--pr', required=True, help='batch PR number or URL')
        p.add_argument('--repo', help='OWNER/REPO (default: from the URL or the current checkout)')
        p.add_argument('--dry-run', action='store_true', help='print what would change, write nothing')
        if name in ('open', 'retarget'):
            p.add_argument('--uoc', type=int, required=True, help='unit number, the N of "UoC N/M"')
            p.add_argument('--force', action='store_true',
                           help='open: also for an upstream-only unit; retarget: also when not approved')
        if name == 'open':
            p.add_argument('--draft', action='store_true')
            p.add_argument('--reviewer', action='append', help='GitHub login to request a review from (repeatable)')
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {'open': cmd_open, 'retarget': cmd_retarget, 'status': cmd_status}[a.cmd](a)
    except Finding as e:
        print('uoc_review.py %s: %s' % (a.cmd, e), file=sys.stderr)
        return 1
    except Refuse as e:
        print('uoc_review.py %s: %s' % (a.cmd, e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
