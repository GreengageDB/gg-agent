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

- **A pull request** — `gh pr diff <number>`. Prefer this over local git: it needs no
  history, which matters because a full-history checkout of this repository is hundreds of
  megabytes and CI checks it out shallow.
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

See also: [greengage-internals](../skills/greengage-internals/SKILL.md) ·
[greengage-testing](../skills/greengage-testing/SKILL.md) ·
[greengage-ci](../skills/greengage-ci/SKILL.md)
