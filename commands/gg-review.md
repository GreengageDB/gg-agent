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

**Locally**, print the findings in severity order.

Either way, for each finding give: the file and line, the mechanism by which it breaks on a
cluster, and a concrete scenario that triggers it — which segment, which role, which
sequence. Separate confirmed defects from things that need a cluster to settle, and label
which is which.

If nothing is wrong, say so plainly and list what you checked.

See also: [greengage-internals](../skills/greengage-internals/SKILL.md) ·
[greengage-testing](../skills/greengage-testing/SKILL.md) ·
[greengage-ci](../skills/greengage-ci/SKILL.md)
