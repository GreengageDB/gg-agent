---
name: greengage-uoc-review-status
description: Update the Review PR column of a greengage_sync batch PR's units-of-change table - finding each unit's review PRs by body marker or uoc<N> head branch, reading state, draft, review verdicts and CI through the GitHub API, writing #<n> <status> per unit plus a summary of unreviewed units, idempotently and without clobbering concurrent edits. Use when the Review PR column is stale, after review PRs were opened, approved or merged, or when asked which units are still unreviewed.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "8.x campaign line in greengage_sync (batch PRs built by greengage-pg-batch)"
---

# Keeping the batch PR's review column current

The units-of-change table of a batch PR ([greengage-pg-batch](../greengage-pg-batch/SKILL.md))
ends with a **Review PR** column. It starts as `—` for every unit. Review PRs are opened unit
by unit ([greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md)) and move through
review at different speeds; this skill rewrites that column, and a one-line summary above
the table, from the review PRs' real state.

```bash
U=${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py
python3 $U status --pr https://github.com/GreengageDB/greengage_sync/pull/626 --dry-run
python3 $U status --pr 626 --repo GreengageDB/greengage_sync
```

Everything goes through `gh api`; no checkout is needed. The dry run prints each unit's new
cell and the summary and writes nothing. The real run is safe to repeat: when nothing but the
timestamp would change, it prints `no change` and does not touch the PR.

## How a review PR is recognised

| Signal | Written by | Covers |
|---|---|---|
| `<!-- uoc-review: pr=<batch> uoc=<N> … -->` in the PR body | `uoc_review.py open` | PRs opened with the tool, whatever their branch names |
| Head branch `<batch-branch>-uoc<N>` in the same repository | The documented recipe | PRs opened by hand |

The search walks the repository's PRs newest first and stops at the batch PR's creation
date, since no review PR can be older than its batch. A unit may have several review PRs
(a closed first attempt, then a new one); the cell lists all of them, oldest first, and the
summary counts the newest.

## What each cell says

A cell is `#<number> <status>`, joined with `<br>` when there are several. GitHub links `#<n>`
by itself.

| Status | Meaning | Next step |
|---|---|---|
| `draft` | Opened as a draft | The author marks it ready |
| `open` | Ready, no reviewer requested, no verdict yet | Request a reviewer |
| `in review` | A reviewer is requested and has not given a verdict | Wait for the reviewer |
| `changes requested` | A reviewer's latest verdict asks for changes | Push fixes to the head branch |
| `approved, to retarget` | Approved, base still `<batch>-uoc<N>-base` | `uoc_review.py retarget` |
| `approved, ready to merge` | Approved and based on the batch branch | Merge with a merge commit |
| `merged` | Merged; its fixes are in the batch PR | — |
| `closed` | Closed without merging | Open a new one if the unit still needs review |

The review state is GitHub's `reviewDecision` where the base branch requires reviews. The
`uoc<N>-base` branches require none, and GitHub then reports no decision at all, so the tool
falls back to each reviewer's latest approving or change-requesting review. `, CI failing` or
`, CI running` is appended from the head commit's check rollup. The
summary line counts units by the status of their newest review PR and lists the
*must review* units that have none yet. Units marked "upstream only" are never listed
there: they have nothing to review.

## Editing the description without losing someone else's edit

The column and the summary are the only things rewritten. The summary lives between
`<!-- uoc-review-status -->` and `<!-- /uoc-review-status -->` and is inserted above the
table the first time. Just before writing, the tool fetches the description again; if
someone edited it meanwhile, it recomputes from the new text, up to three times, then gives
up with exit status 2 and asks for a re-run.

The write is `PATCH /repos/<repo>/pulls/<n>` through `gh api`. `gh pr edit` cannot be used on
`greengage_sync`: it fails with a Projects (classic) deprecation error from GraphQL.

| Problem | Cause | Fix |
|---|---|---|
| `the batch PR body has no unit table` | The header row lost "Unit of change" or "Review PR" | Restore the header from `pg_batch.py render`; the tool finds the table by those two names |
| A unit shows `—` although it has a review PR | The PR was opened by hand with another branch name, from a fork, or before the batch PR existed | Add the marker line to its body, or rename the head branch |
| `review PRs for units not in the table` | A unit number that the table does not have | Check the PR's `uoc=` marker; the batch may have been rebuilt with different numbers |
| A hand-written note in the Review PR column disappeared | The column belongs to the tool | Put notes in the PR description's prose, not in that column |

## When to run it

After opening, approving, retargeting or merging any review PR, and before reporting
review progress. It is cheap: a few paged REST calls and one GraphQL query for every
fifty review PRs. A scheduled run keeps the column current during a long review.

## What not to do

- Do not hand-edit the Review PR column or the status block; the next run overwrites both.
- Do not use the column as the review record; the review PRs themselves are.
- Do not run it against a PR that is not a batch PR; without the unit table it refuses
  rather than guessing.

See also: [greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md) ·
[greengage-pg-batch](../greengage-pg-batch/SKILL.md) ·
[greengage-ci](../greengage-ci/SKILL.md) ·
[greengage-contribute](../greengage-contribute/SKILL.md)
