---
name: greengage-uoc-review-status
description: Keep the unit table of a greengage_sync batch PR current - finding every unit PR by its <prefix>-uoc<N> head branch, reading state, draft, review verdicts and CI through the GitHub API, writing one row per unit with all its PRs and a summary of units not merged yet, idempotently and without clobbering concurrent edits. Use when the batch PR's unit table is stale, after unit PRs were opened, approved, merged or split, or when asked which units are still not merged.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.2.0"
  greengageVersion: "8.x campaign line in greengage_sync (batches split by greengage-pg-batch)"
---

# Keeping the batch PR's unit table current

A batch split by [greengage-pg-batch](../greengage-pg-batch/SKILL.md) is reviewed as one PR per
unit ([greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md)), and the units move at
different speeds. This skill writes a table into the batch PR's description — one row per unit:
number, title, its PRs, their state — and a summary line above it, from the PRs' real state.

```bash
U=${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py
python3 $U status --pr https://github.com/GreengageDB/greengage_sync/pull/660 --dry-run
python3 $U status --pr 660 --repo GreengageDB/greengage_sync
```

Everything goes through `gh api`; no checkout is needed. The dry run prints the summary and the
table and writes nothing. The real run is safe to repeat: when nothing but the timestamp would
change, it prints `no change` and does not touch the PR. Against #660 it reported
`40 merged, 2 draft. Not merged yet: UoC 26, UoC 27.`

## How a unit and its PRs are found

The batch PR's head branch is `<prefix>-base`, which gives the prefix (`--prefix` overrides it).
A unit is any `<prefix>-uoc<N>` branch on GitHub or any PR whose head is such a branch in the
same repository, so PRs opened by hand count too. The search walks all the repository's PRs,
not only those newer than the batch PR: b1's unit PRs (#632–#659) predate its batch PR (#660).
A unit may have several PRs (b1: a closed first attempt with a `UoC N/28` title, then a new
one); the row lists all of them, oldest first, and the summary counts the newest.

## What each row says

| Status | Meaning | Next step |
|---|---|---|
| `no PR yet` | A unit branch without a PR | `uoc_review.py open --uoc N` |
| `draft` | Opened as a draft | The author marks it ready |
| `open` | Ready, no reviewer requested, no verdict yet | Request a reviewer |
| `in review` | A reviewer is requested and has not given a verdict | Wait for the reviewer |
| `changes requested` | A reviewer's latest verdict asks for changes | Push fixes to the unit branch |
| `approved` | Approved | Squash-merge it into the base |
| `merged` | Merged into the base | — |
| `… held: test branch only` | Held out of the batch with `--held`; not counted as pending | Nothing for this batch |
| `closed` | Closed without merging | Open a new one if the unit still needs review |

The review state is GitHub's `reviewDecision` where the base branch requires reviews. The
`<prefix>-base` branches require none, and GitHub then reports no decision at all, so the tool
falls back to each reviewer's latest approving or change-requesting review. `, CI failing` or
`, CI running` comes from the head commit's check rollup. The title comes from the newest PR,
without the `UoC N:` prefix and the `(#PR)` suffix of a squash merge.

## Held units

`--held 26,27` marks units that stay on the test branch only
([greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md), "Holding a unit out of the
batch"). The list is written into the block as `<!-- uoc-held: 26,27 -->`, so later runs keep it
without the flag; `--held ''` clears it. The summary then reads
`40 merged, 2 held. Not merged yet: none. Held out of the batch: UoC 26, UoC 27.` (#660).

## Editing the description without losing someone else's edit

Only the block between `<!-- uoc-review-status -->` and `<!-- /uoc-review-status -->` is
rewritten. The first run puts it right under the `## Units of change` heading, or appends that
heading when there is none. Just before writing, the tool fetches the description again; if
someone edited it meanwhile, it recomputes from the new text, up to three times, then gives up
with exit status 2 and asks for a re-run.

The write is `PATCH /repos/<repo>/pulls/<n>` through `gh api`. `gh pr edit` cannot be used on
`greengage_sync`: it fails with a Projects (classic) deprecation error from GraphQL.

| Problem | Cause | Fix |
|---|---|---|
| `the head branch of #N is X, not <prefix>-base` | The PR is not a batch PR, or `gh` picked another repository | Pass `--repo`, or `--prefix` for an unusual head name |
| A unit is missing | Its PR comes from a fork, or its branch has another name | Push the branch as `<prefix>-uoc<N>` to the repository |
| A row lists a PR of an old layout | A branch name was reused (b1: #627 and #629 of the per-file layout used `uoc31`/`uoc30`) | Harmless; the newest PR decides the status |
| A hand-written note inside the block disappeared | The block belongs to the tool | Put notes in the description's prose |

## When to run it

After opening, approving, merging or splitting any unit PR, and before reporting review
progress. It is cheap: a few paged REST calls and one GraphQL query for every fifty PRs. A
scheduled run keeps the table current during a long review.

## What not to do

- Do not hand-edit the table or the summary; the next run overwrites both.
- Do not use the table as the review record; the unit PRs themselves are.
- Do not run it with a guessed `--prefix` on a PR that is not a batch PR.

See also: [greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md) ·
[greengage-pg-batch](../greengage-pg-batch/SKILL.md) ·
[greengage-ci](../greengage-ci/SKILL.md) ·
[greengage-contribute](../greengage-contribute/SKILL.md)
