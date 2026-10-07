---
name: greengage-uoc-review-pr
description: Open the review PR for one unit of change (UoC) of a greengage_sync batch PR, given the batch PR by number or URL and the unit number - the UoC N/M commit, the uoc<N>-base and uoc<N> branches, a diff of exactly that unit, refusing upstream-only units and duplicates, reviewers, and retargeting the approved PR into the batch. Use when a reviewer is assigned to a unit, when asked to open the review PR for UoC 7 of #626, or when an approved unit review must be merged back into the batch.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "8.x campaign line in greengage_sync (batch PRs built by greengage-pg-batch)"
---

# Opening the review PR for one unit of change

A batch PR built by [greengage-pg-batch](../greengage-pg-batch/SKILL.md) is reviewed
unit by unit. Each unit is one commit on the batch branch, `UoC N/M: <title>`, and gets its
own review PR once a reviewer is assigned. The batch PR stays the integration point: review
fixes land in it by merging the review PR, and its **Review PR** column tracks them
([greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md)).

The tool is `${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py`. It works entirely through the
GitHub API with `gh api` — no checkout needed — and takes the batch PR as a number or a URL.

## The branch layout makes the diff exactly one unit

```
batch branch   … ── UoC N-1 ── UoC N ── UoC N+1 ── …          (sync-15x-b1, the batch PR head)
                       │          │
review PR      base: sync-15x-b1-uoc<N>-base     head: sync-15x-b1-uoc<N>  ── review fixes
```

| Branch | Points at | Why |
|---|---|---|
| `<batch>-uoc<N>-base` | The commit before the unit | The PR diff starts after every earlier unit |
| `<batch>-uoc<N>` | The unit commit; review fixes go on top | The PR diff ends at the unit, plus its fixes |

The diff is the Greengage side of the unit: conflict resolutions — each removes the markers
that the batch merge committed, so a hunk shows both sides and the chosen result — and the
fixes found during bring-up. The unit's upstream commits are listed in the commit message;
they are already reviewed upstream and are not in the diff.

When the review is approved, the PR is **retargeted** to the batch branch. The merge base
becomes the unit commit, so the diff shrinks to the review fixes, and merging it (with a
merge commit) brings exactly those fixes into the batch PR.

## Open it: dry run, confirm, then create

```bash
U=${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py
python3 $U open --pr https://github.com/GreengageDB/greengage_sync/pull/626 --uoc 7 --dry-run
python3 $U open --pr 626 --repo GreengageDB/greengage_sync --uoc 7 --reviewer <login>
```

The dry run prints the unit commit, the two branches (create or reuse) and the full PR body.
Creating branches and a PR is visible to the whole team — run the real command only when the
user asked for it or confirmed the dry run. In b1 the team opened review PRs as reviewers
were assigned, not all at once.

`open` creates the branches through `POST /git/refs` and the PR through `POST /pulls` (the
unit commit is already on GitHub, so nothing is pushed), then requests the reviewers. The
PR is titled `Review <batch> UoC <N>: <title>` and its body carries the unit's review status
and rules, the full unit commit message, the finishing steps, and a marker —
`<!-- uoc-review: pr=626 uoc=7 commit=<sha> -->` — that the status skill finds it by.

It refuses, with exit status 1, rather than doing something surprising:

| Refusal | Meaning | What to do |
|---|---|---|
| `UoC N (…) is upstream-only: its commit … is empty` | The unit's upstream changes merged cleanly or by rule; there is no Greengage diff (b1: `regex`, `ecpg`, `contrib`, `docs`, `encoding-unicode`) | Nothing to review; `--force` opens an empty PR only if the team insists |
| `UoC N already has an open review PR` | Opened before, by the tool or by hand with the same branch names | Use that PR |
| `branch … exists at …, which is not the unit commit or a descendant of it` | A stale branch from a rebuilt batch, or an unrelated branch | Delete it after checking nobody uses it, or open the PR by hand |

Exit status 2 means the PR, the unit or `gh` itself is not usable: `no commit "UoC 99/..."`
names a unit that does not exist on the batch head.

## Review: read the unit in the order its commit message gives

The unit commit message is the reviewer's map. Its **Review status** lines name the rule
and the files ([review rules](../greengage-pg-batch/reference/review-rules.md)) — read those
files first:

| Rule in the message | Look for |
|---|---|
| R1 day-1 commit | The upstream API change itself, and every Greengage caller of the old shape |
| R3 new lines | Lines on neither side: is the invention needed, and is it MPP-correct? |
| R4 Greengage lines dropped | A re-graft that vanished — the most common real bug of a bump |
| R5 upstream lines dropped | An upstream fix Greengage silently refused |
| R6/R7 changes outside the conflicts, new code | Bring-up fixes: each needs the test that proved it |
| R8 tests weakened | A result replaced by an `ERROR`, a dropped test — never accept a regenerated failure |

For the MPP checklist — dispatch and serialization, motion and locus, distributed
transactions, AO auxiliary relations — delegate to the `greengage-mpp-reviewer` subagent
with the review PR's diff.

## Fixes, then retarget and merge

Push review fixes to `<batch>-uoc<N>`. Keep them inside the unit's files where possible: a
fix to another unit's file is fine (units do not overlap, so it merges cleanly), but name the
other unit in the commit message.

```bash
python3 $U retarget --pr 626 --repo GreengageDB/greengage_sync --uoc 7 --dry-run
python3 $U retarget --pr 626 --repo GreengageDB/greengage_sync --uoc 7
```

`retarget` changes the review PR's base to the batch branch. It refuses (exit 1) unless the
PR is approved and no reviewer's latest review requests changes; `--force` overrides. Then
the team merges the review PR **with a merge commit**, and the status skill refreshes the
batch PR's table. The `-base` branch is no longer used after the retarget; delete it when
the PR is merged.

## Without the plugin

The batch PR description carries the same recipe, so anyone can do it by hand:

```bash
git push origin <commit>^:refs/heads/sync-15x-b1-uoc7-base <commit>:refs/heads/sync-15x-b1-uoc7
gh pr create -R GreengageDB/greengage_sync --base sync-15x-b1-uoc7-base --head sync-15x-b1-uoc7 \
   --title "Review sync-15x-b1 UoC 7: <title>"
```

A PR opened this way has no marker, but the status skill still finds it by its head branch.

## What not to do

- Do not open review PRs in bulk or for upstream-only units unless asked; reviewers are
  assigned unit by unit.
- Do not rebuild or force-push the batch branch once a review PR exists: both review
  branches point at the old unit commit, and after a retarget the diff would show the whole
  unit again.
- Do not squash-merge or rebase-merge a review PR into the batch branch; the batch keeps
  every commit's provenance.
- Do not resolve review comments by editing the batch branch directly; the fix belongs on
  the review PR, where the reviewer sees it.

See also: [greengage-pg-batch](../greengage-pg-batch/SKILL.md) ·
[greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md) ·
[greengage-internals](../greengage-internals/SKILL.md) ·
[greengage-pg-merge](../greengage-pg-merge/SKILL.md) ·
[greengage-ci](../greengage-ci/SKILL.md)
