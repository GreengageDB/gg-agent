---
description: Review a Greengage change for MPP correctness and report findings on the diff
argument-hint: "[PR number, branch, or nothing for the working diff]"
---

Review: $ARGUMENTS

Delegate the analysis to the **greengage-mpp-reviewer** subagent — it owns the checklist
of failure modes that look correct on a single node and break across segments. This command
establishes the diff, drives that agent, and decides where the findings go.

## 1. Establish the real diff

Never review a description of a change. Get the actual patch:

- **A pull request** — `gh pr diff <number> --repo <owner>/<repo>`. Prefer this over local
  git: it needs no history, which matters because a full-history checkout of this
  repository is hundreds of megabytes and CI checks it out shallow.

  **Resolve which repository first, and never assume the current one.** Accept any of
  `https://github.com/<owner>/<repo>/pull/<n>`, `<owner>/<repo>#<n>`, `<owner>/<repo> <n>`,
  or a bare `<n>`. For anything but the bare form, pass `--repo <owner>/<repo>` to *every*
  `gh` call, including the one that posts.

  **A bare number is dangerous in a checkout that has more than one remote.** `gh` silently
  resolves it against its default repository, which is the upstream `origin`, not the fork
  you were thinking of — and the same number is a completely different pull request in each.
  Before trusting a bare number:

  ```bash
  git remote -v                 # more than one? the number is ambiguous
  gh repo set-default --view    # empty means gh is guessing
  ```

  If there is any ambiguity, resolve it to an explicit `<owner>/<repo>` and use `--repo`.
  Always echo the resolved `<owner>/<repo>#<n>` **and the PR title** before doing any work —
  the title is what makes a wrong target obvious at a glance.

  You do not need a local checkout at all if you only need the diff. You do need one to
  read surrounding code, which is usually what separates a real finding from a guess — so
  when reviewing a repository you have no checkout of, say that the review is diff-only and
  what that limits.
- **A branch** — `git diff $(git merge-base HEAD <base>)...HEAD`, where `<base>` is `7.x`
  or `6.x`. Not `main`, which is a stale mirror of the 6.x line.
- **Nothing given** — the uncommitted working diff, `git diff` plus `git diff --cached`.

Note which branch line the change targets before reading it. **7.x is PostgreSQL 12.22 and
6.x is PostgreSQL 9.4.26**, and the same patch can be right on one and wrong on the other.

## 2. Delegate

`@agent-greengage:greengage-mpp-reviewer` — give it the diff, the target branch line, and
any context the author supplied about intent. Let it work; do not pre-filter the diff down
to what looks interesting, because the defects this catches are usually in the parts that
look routine.

If the change touches none of the MPP surface — documentation only, a comment fix, a change
confined to `gpMgmt` Python with no backend interaction — say so and stop. A review that
manufactures findings to look thorough is worse than no review.

## 3. Report

**In CI**, post each finding as an inline comment on the exact line it applies to, using
`mcp__github_inline_comment__create_inline_comment`. The subagent cannot post — its declared
tools are read-only by design, so that it works locally too — so you post on its behalf.
Then add one summary comment: what you reviewed, the count by severity, and anything you
could not verify without a running cluster.

Claude cannot submit a formal GitHub review or approve a pull request. Do not imply
otherwise in the summary; say "review comments posted", not "approved".

**Locally**, print the findings in severity order. If the user asked you to post them to
the pull request, submit **one review** rather than a scatter of loose comments — it
groups the inline comments under a single summary and sends one notification:

```bash
cat > /tmp/gg-review.json <<'JSON'
{
  "commit_id": "<head sha from `gh pr view <n> --json headRefOid`>",
  "event": "COMMENT",
  "body": "<summary: what was reviewed, counts by severity, what needs a cluster to settle>",
  "comments": [
    { "path": "src/backend/...", "line": 123, "side": "RIGHT", "body": "<the finding>" }
  ]
}
JSON
gh api repos/<owner>/<repo>/pulls/<n>/reviews --input /tmp/gg-review.json
```

`<owner>/<repo>` here is the repository resolved in step 1 — the one the pull request
lives in, which is not necessarily the one you are standing in.

Rules that will otherwise cost you a failed call or a misleading review:

- `line` must be a line the diff actually touches, numbered in the **head** commit. A line
  outside the diff is rejected. Use `side: "LEFT"` only to comment on a removed line.
- Use `event: "COMMENT"`. `APPROVE` and `REQUEST_CHANGES` are refused on your own pull
  request, and approving is not the agent's call to make regardless.
- The review is authored by whoever owns the `gh` token — a human account, not a bot, so
  the findings must be marked as generated. End the summary with exactly:

  ```
  ---
  _Generated with [greengage plugin](https://github.com/GreengageDB/gg-agent)_
  ```
- Post once. Re-running the command should not stack duplicate reviews on the same head
  commit; check `gh pr view <n> --json reviews` first.

Either way, for each finding give: the file and line, the mechanism by which it breaks on a
cluster, and a concrete scenario that triggers it — which segment, which role, which
sequence. Separate confirmed defects from things that need a cluster to settle, and label
which is which.

**Keep each comment short.** A reviewer reads it next to the line it is attached to, so it
needs the defect, the mechanism in a sentence or two, and the fix — not a derivation. Aim
for under ~600 characters per inline comment: lead with the problem in bold, then why it
breaks, then what to change. Move anything longer into the summary, or leave it out. A
comment that has to be scrolled past is a comment that gets skimmed.

If nothing is wrong, say so plainly and list what you checked.

## Running this from a terminal

The command works headless, with no interactive session. Install the plugin once:

```bash
claude plugin marketplace add https://github.com/GreengageDB/gg-agent.git
claude plugin install greengage@greengage-agent-skills
```

Then review any pull request you can read, in any repository:

```bash
claude -p "/greengage:gg-review GreengageDB/greengage#123 and post the review" \
  --permission-mode dontAsk \
  --max-turns 30
```

- **`--permission-mode dontAsk`** matters: `-p` starts in `manual`, where every `gh` call
  waits for an approval nobody is there to give. The alternative is an explicit
  `--allowedTools "Bash(gh pr diff:*) Bash(gh api:*) Read Grep Glob"`.
- **Never pass `--bare`** — it skips plugin sync and `CLAUDE.md` discovery, which removes
  the knowledge this command exists to apply.
- The review is authored by whoever `gh auth status` reports. Check that before posting to
  a repository other people watch.
- Cost controls: `--max-turns`, `--max-budget-usd`, `--model`.
- Say explicitly in the prompt whether to post. Left ambiguous, a headless run should print
  and not post — posting to someone else's repository is not a default worth guessing at.

### Running inside a Greengage checkout

Worth doing — a checkout is what lets the reviewer grep the whole tree, which is where the
findings the diff cannot show come from ("this field is written but nothing ever sets it").
Two things to get right:

**The checkout should match the pull request.** Standing on an unrelated branch means the
surrounding code you read is not the code the PR modifies. Do not `gh pr checkout` over
work in progress; add a worktree at the PR's head instead, and remove it afterwards:

```bash
gh pr view <n> --repo <owner>/<repo> --json headRefOid -q .headRefOid   # -> <sha>
git fetch <remote> <sha> && git worktree add /tmp/review-<n> <sha>
cd /tmp/review-<n>       # review from here
# when done:  git worktree remove /tmp/review-<n>
```

If you review from a branch that does not match, say so in the summary and treat anything
that depends on surrounding code as unconfirmed.

**Name the repository explicitly**, per the ambiguity warning above — a Greengage checkout
usually has both `origin` (upstream) and a fork remote.

See also: [greengage-internals](../skills/greengage-internals/SKILL.md) ·
[greengage-testing](../skills/greengage-testing/SKILL.md) ·
[greengage-ci](../skills/greengage-ci/SKILL.md)
