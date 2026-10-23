#!/usr/bin/env python3
"""Pull requests for the units of change (UoC) of a greengage_sync batch.

A batch split by uoc_split.py (skill greengage-pg-batch) has one branch per unit:
    <prefix>-base   the upstream merge with its conflict markers committed (the batch PR head)
    <prefix>-uocN   one commit on top of it, "UoC N: <title>": only unit N's operations
Each unit is reviewed in its own PR, <prefix>-uocN -> <prefix>-base. The units are
independent, so their PRs merge in any order; the batch PR (<prefix>-base -> next)
builds once all of them are merged.

    open      create the PR of one, several or all units
    status    refresh the unit table in the batch PR's description

Usage:
    uoc_review.py open   (--prefix P | --pr BATCH) (--uoc N[,N...] | --all) [--repo OWNER/REPO]
                         [--reviewer LOGIN]... [--draft] [--dry-run]
    uoc_review.py status --pr BATCH [--prefix P] [--held N[,N...]] [--repo OWNER/REPO] [--dry-run]

BATCH is the batch PR, as a number or a URL (https://github.com/OWNER/REPO/pull/660); its
head branch is <prefix>-base, which gives the prefix. Without --repo the repository comes
from the URL, or from `gh repo view` in the current directory. Everything goes through
the GitHub API with `gh api` (authenticated gh CLI required); no checkout is needed.
--dry-run prints what would change and writes nothing.

Unit PRs are found by their head branch, <prefix>-uoc<N> in the same repository, so PRs
opened by hand are found too. A unit can be held out of the batch (it stays on the test
branch only): status --held lists such units, and the list is kept in the batch PR body
(<!-- uoc-held: 26,27 -->) for later runs; --held '' clears it.

Exit status: 0 done (or nothing to do); 1 refused on a finding (the unit already has an
open PR); 2 usage or environment error (gh missing or unauthenticated, PR or branch not found).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

UOC_SUBJECT = re.compile(r'^UoC (\d+)(?:/\d+)?: (.*?)(?: \(#\d+\))?$')
STATUS_BEGIN, STATUS_END = '<!-- uoc-review-status -->', '<!-- /uoc-review-status -->'
HELD = re.compile(r'<!-- uoc-held: ([\d, ]*) -->')


class Refuse(Exception):
    """usage or environment error: exit 2"""


class Finding(Exception):
    """refused on a finding: exit 1"""


# ------------------------------------------------------------------ gh plumbing
def gh(*args, ok404=False):
    try:
        r = subprocess.run(['gh'] + list(args), capture_output=True, text=True)
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


def resolve_repo(repo, url=None):
    m = re.match(r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)', url or '')
    if m and not repo:
        return m.group(1)
    return repo or gh('repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner').strip()


def resolve_pr(pr, repo):
    m = re.match(r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)', pr)
    if m:
        num = int(m.group(2))
    elif pr.isdigit():
        num = int(pr)
    else:
        raise Refuse('--pr must be a number or a pull request URL, not %r' % pr)
    repo = resolve_repo(repo, pr)
    p = api('repos/%s/pulls/%d' % (repo, num), ok404=True)
    if p is None:
        raise Refuse('%s#%d does not exist (or gh cannot see it)' % (repo, num))
    return repo, p


def prefix_of(batch, prefix):
    if prefix:
        return prefix
    head = batch['head']['ref']
    if not head.endswith('-base'):
        raise Refuse('the head branch of #%d is %s, not <prefix>-base; pass --prefix'
                     % (batch['number'], head))
    return head[:-len('-base')]


def ref_sha(repo, name):
    r = api('repos/%s/git/ref/heads/%s' % (repo, name), ok404=True)
    return r['object']['sha'] if r else None


def unit_branches(repo, prefix):
    """{unit number: head sha} of the <prefix>-uoc<N> branches on GitHub"""
    pat = re.compile(r'^refs/heads/%s-uoc(\d+)$' % re.escape(prefix))
    out = {}
    for r in api('repos/%s/git/matching-refs/heads/%s-uoc' % (repo, prefix)) or []:
        m = pat.match(r['ref'])
        if m:
            out[int(m.group(1))] = r['object']['sha']
    return out


def unit_prs(repo, prefix, pages=50):
    """{unit number: [pull request JSON, oldest first]} for every PR from <prefix>-uoc<N>"""
    pat = re.compile(r'^%s-uoc(\d+)$' % re.escape(prefix))
    found = {}
    for page in range(1, pages + 1):
        ps = api('repos/%s/pulls?state=all&sort=created&direction=desc&per_page=100&page=%d' % (repo, page))
        for p in ps:
            m = pat.match(p['head']['ref'])
            if m and p['head']['repo'] and p['head']['repo']['full_name'] == repo:
                found.setdefault(int(m.group(1)), []).append(p)
        if len(ps) < 100:
            break
    for v in found.values():
        v.sort(key=lambda p: p['number'])
    return found


def write_tmp(text):
    fd, path = tempfile.mkstemp(prefix='uoc_review_', suffix='.md')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    return path


# ------------------------------------------------------------------ open
def unit_commit(repo, n, head):
    """the 'UoC N:' commit on the unit branch (review fixes may sit on top of it)"""
    for c in api('repos/%s/commits?sha=%s&per_page=30' % (repo, head)):
        m = UOC_SUBJECT.match(c['commit']['message'].split('\n', 1)[0])
        if m and int(m.group(1)) == n:
            return c
    raise Refuse('no commit "UoC %d: ..." among the last 30 commits of the unit branch; was it made by '
                 'uoc_split.py branches?' % n)


def cmd_open(a):
    if a.pr:
        repo, batch = resolve_pr(a.pr, a.repo)
        prefix = prefix_of(batch, a.prefix)
    elif a.prefix:
        repo, prefix = resolve_repo(a.repo), a.prefix
    else:
        raise Refuse('pass --prefix or --pr')
    base = '%s-base' % prefix
    if not ref_sha(repo, base):
        raise Refuse('%s has no branch %s; push it first (uoc_split.py branches --base)' % (repo, base))
    branches = unit_branches(repo, prefix)
    if a.all:
        todo = sorted(branches)
    elif a.uoc:
        todo = [int(x) for x in a.uoc.split(',')]
    else:
        raise Refuse('pass --uoc N[,N...] or --all')
    missing = [n for n in todo if n not in branches]
    if missing:
        raise Refuse('no branch %s on %s; push it first' % (', '.join('%s-uoc%d' % (prefix, n) for n in missing), repo))
    existing = unit_prs(repo, prefix)
    refused = []
    for n in todo:
        head = '%s-uoc%d' % (prefix, n)
        open_prs = [p for p in existing.get(n, []) if p['state'] == 'open']
        if open_prs:
            refused.append('UoC %d already has an open PR: %s' % (n, ', '.join(p['html_url'] for p in open_prs)))
            continue
        c = unit_commit(repo, n, branches[n])
        title, _, body = c['commit']['message'].partition('\n')
        body = body.strip('\n') + '\n\n<!-- uoc-review: prefix=%s uoc=%d -->\n' % (prefix, n)
        print('open PR   %s  (%s <- %s)%s' % (title, base, head, ' as draft' if a.draft else ''))
        if a.reviewer:
            print('request   %s' % ', '.join(a.reviewer))
        if a.dry_run:
            print('--- body ---\n' + body)
            continue
        path = write_tmp(body)
        try:
            p = api('repos/%s/pulls' % repo, '-f', 'title=' + title, '-f', 'head=' + head, '-f', 'base=' + base,
                    '-F', 'body=@' + path, '-F', 'draft=%s' % ('true' if a.draft else 'false'), method='POST')
        finally:
            os.unlink(path)
        if a.reviewer:
            api('repos/%s/pulls/%d/requested_reviewers' % (repo, p['number']),
                *[x for r in a.reviewer for x in ('-f', 'reviewers[]=' + r)], method='POST')
        print('opened %s' % p['html_url'])
    for r in refused:
        print(r, file=sys.stderr)
    if refused and not a.all:
        raise Finding('%d unit(s) refused' % len(refused))
    return 0


# ------------------------------------------------------------------ status
def pr_states(repo, numbers):
    owner, name = repo.split('/', 1)
    out = {}
    for i in range(0, len(numbers), 50):
        q = ' '.join('p%d: pullRequest(number: %d) { number state isDraft reviewDecision '
                     'latestOpinionatedReviews(first: 30) { nodes { state } } reviewRequests(first: 1) { totalCount } '
                     'commits(last: 1) { nodes { commit { statusCheckRollup { state } } } } }' % (n, n)
                     for n in numbers[i:i + 50])
        d = graphql('query { repository(owner: "%s", name: "%s") { %s } }' % (owner, name, q))['repository']
        out.update({v['number']: v for v in d.values() if v})
    return out


def state_text(s):
    if s['state'] == 'MERGED':
        return 'merged'
    if s['state'] == 'CLOSED':
        return 'closed'
    if s['isDraft']:
        t = 'draft'
    else:
        # reviewDecision is null when the base branch requires no review (the <prefix>-base
        # branches are unprotected), so fall back to each reviewer's latest verdict
        verdicts = [r['state'] for r in s['latestOpinionatedReviews']['nodes']]
        decision = s['reviewDecision'] or ('CHANGES_REQUESTED' if 'CHANGES_REQUESTED' in verdicts else
                                           'APPROVED' if 'APPROVED' in verdicts else
                                           'REVIEW_REQUIRED' if s['reviewRequests']['totalCount'] else None)
        t = {'APPROVED': 'approved', 'CHANGES_REQUESTED': 'changes requested',
             'REVIEW_REQUIRED': 'in review'}.get(decision, 'open')
    nodes = s['commits']['nodes']
    ci = nodes and nodes[0]['commit']['statusCheckRollup'] and nodes[0]['commit']['statusCheckRollup']['state']
    if ci in ('FAILURE', 'ERROR'):
        t += ', CI failing'
    elif ci in ('PENDING', 'EXPECTED'):
        t += ', CI running'
    return t


def unit_title(p):
    m = UOC_SUBJECT.match(p['title'])
    return (m.group(2) if m else p['title']).replace('|', '\\|')


def status_block(found, states, branches, held):
    """the unit table: one row per unit branch or unit PR, its PRs oldest first; held units
    stay on the test branch only and are not counted as pending"""
    rows, tally, pending = [], {}, []
    for n in sorted(set(found) | set(branches)):
        prs = found.get(n, [])
        texts = [(p['number'], state_text(states[p['number']]) if p['number'] in states else p['state'])
                 for p in prs]
        key = texts[-1][1].split(',')[0] if texts else 'no PR'
        if n in held:
            key = 'held'
        tally[key] = tally.get(key, 0) + 1
        if key not in ('merged', 'held'):
            pending.append(n)
        status = '<br>'.join(t[1] for t in texts) or 'no PR yet'
        rows.append('| %d | %s | %s | %s |' % (
            n, unit_title(prs[-1]) if prs else '—', '<br>'.join('#%d' % t[0] for t in texts) or '—',
            status + ('<br>**held: test branch only**' if n in held else '')))
    summary = '**Unit PRs:** %s. Not merged yet: %s.%s (Updated %s).' % (
        ', '.join('%d %s' % (v, k) for k, v in sorted(tally.items(), key=lambda kv: -kv[1])) or 'none',
        ', '.join('UoC %d' % n for n in pending) or 'none',
        ' Held out of the batch: %s.' % ', '.join('UoC %d' % n for n in sorted(held)) if held else '',
        datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
    marker = ['<!-- uoc-held: %s -->' % ','.join(str(n) for n in sorted(held))] if held else []
    return '\n'.join([STATUS_BEGIN] + marker + [summary, '', '| UoC | Unit | PR | Status |', '|---|---|---|---|'] +
                     rows + [STATUS_END]), summary


def update_body(body, block):
    """replace the status block; the first time, put it under the "Units of change" heading"""
    if STATUS_BEGIN in body and STATUS_END in body:
        return re.sub(re.escape(STATUS_BEGIN) + r'.*?' + re.escape(STATUS_END), lambda m: block, body, flags=re.S)
    lines = body.split('\n')
    at = next((i for i, ln in enumerate(lines) if re.match(r'^#+\s*Units of change', ln)), None)
    if at is None:
        return body.rstrip('\n') + '\n\n## Units of change\n\n' + block + '\n'
    lines[at + 1:at + 1] = ['', block]
    return '\n'.join(lines)


STAMP = re.compile(r' \(Updated [^)]*\)\.')


def cmd_status(a):
    repo, batch = resolve_pr(a.pr, a.repo)
    prefix = prefix_of(batch, a.prefix)
    found = unit_prs(repo, prefix)
    branches = unit_branches(repo, prefix)
    states = pr_states(repo, sorted(p['number'] for v in found.values() for p in v))
    for attempt in range(3):
        old = batch['body'] or ''
        if a.held is not None:
            held = {int(x) for x in a.held.split(',') if x.strip()}
        else:
            m = HELD.search(old)
            held = {int(x) for x in m.group(1).split(',') if x.strip()} if m else set()
        block, summary = status_block(found, states, branches, held)
        new = update_body(old, block)
        print('%s#%d: %d unit PRs for %d units, %d unit branches' % (
            repo, batch['number'], sum(len(v) for v in found.values()), len(found), len(branches)))
        print('  ' + summary)
        if STAMP.sub('', new) == STAMP.sub('', old):
            print('no change')
            return 0
        if a.dry_run:
            print('\n' + block)
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
                                 epilog='See the module docstring for the branch layout.',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', metavar='SUBCOMMAND')
    p = sp.add_parser('open', help='open the PR of one, several or all units')
    p.add_argument('--prefix', help='branch prefix, e.g. sync-15x-b2 (default: from the batch PR head)')
    p.add_argument('--pr', help='batch PR number or URL')
    p.add_argument('--uoc', help='unit numbers, comma-separated')
    p.add_argument('--all', action='store_true', help='every <prefix>-uoc<N> branch without an open PR')
    p.add_argument('--draft', action='store_true')
    p.add_argument('--reviewer', action='append', help='GitHub login to request a review from (repeatable)')
    p = sp.add_parser('status', help='refresh the unit table of the batch PR')
    p.add_argument('--pr', required=True, help='batch PR number or URL')
    p.add_argument('--prefix', help='branch prefix (default: the batch PR head without -base)')
    p.add_argument('--held', help="units held out of the batch, comma-separated ('' clears; "
                   "default: the list kept in the batch PR body)")
    for p in sp.choices.values():
        p.add_argument('--repo', help='OWNER/REPO (default: from the URL or the current checkout)')
        p.add_argument('--dry-run', action='store_true', help='print what would change, write nothing')
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {'open': cmd_open, 'status': cmd_status}[a.cmd](a)
    except Finding as e:
        print('uoc_review.py %s: %s' % (a.cmd, e), file=sys.stderr)
        return 1
    except Refuse as e:
        print('uoc_review.py %s: %s' % (a.cmd, e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
