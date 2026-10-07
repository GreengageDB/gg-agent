---
name: greengage-pg-batch
description: Prepare a batch of upstream PostgreSQL commits on greengage_sync for team review - picking the cut and checking it for split revert pairs, branching from next, merging with conflict markers committed, bring-up to green CI on a raw branch, units of change (UoC), review tiers from the b14-b17 rules, the batch-merge-plus-one-commit-per-unit branch, and the templated PR description. Use when asked to take the next N upstream commits into greengage_sync, or to prepare a sync-<major>x-b<N> batch PR.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "8.x campaign line in greengage_sync (next and the sync-<major>x-b<N> batch branches)"
---

# Preparing an upstream PostgreSQL batch for review

A **batch PR** brings a slice of upstream PostgreSQL history into `greengage_sync` `next`
and is shaped so the team can review it unit by unit. The reference is
[GreengageDB/greengage_sync#626](https://github.com/GreengageDB/greengage_sync/pull/626)
(`sync-15x-b1`): 468 upstream commits `e1c1c30f635..3b231596ccf`, 151 conflicted files, 12
real bugs found during bring-up, 31 units of change. Everything here was done on that batch
and every command was run against it.

This skill is the pipeline around the merge. The merge itself — resolving a conflict
semantically, re-grafting Greengage logic, the compile → regress → CI ladder — belongs to
[greengage-pg-merge](../greengage-pg-merge/SKILL.md); load it before step 4. Review PRs
for single units are [greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md), and
their status in the batch PR is [greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md).

The scripts are `${CLAUDE_PLUGIN_ROOT}/scripts/pg_batch.py` (git only, run from the
`greengage_sync` checkout or with `-C`) and `${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py`
(GitHub API through `gh`). Below, `pg_batch.py` means the first one.

## The deliverable is a review layout, not a merge

Two branches end with the **same tree**. Only the first is the PR:

```
sync-15x-b1      next ── Merge upstream PostgreSQL 3b231596ccf ── UoC 1/31 ── UoC 2/31 ── … ── UoC 31/31
                          (468 commits in, 101 files with markers)   (resolutions + fixes of one unit each)
sync-15x-b1-raw  next ── the same merge ── 36 resolution and fix commits in bring-up order
```

| Name | What it is |
|---|---|
| `sync-<major>x-b<N>` | The PR head, in the review layout: the batch merge, then one commit per unit |
| `sync-<major>x-b<N>-raw` | The bring-up history, kept for provenance; never merged |
| `sync-<major>x-b<N>-dirty` (tag) | The merge commit with markers, parent of every raw commit |
| `…-uoc<N>-base`, `…-uoc<N>` | Review PR branches for unit N ([greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md)) |

The merge commit carries the conflict markers on purpose. That is the team's
committed-markers workflow ([greengage-pg-merge](../greengage-pg-merge/SKILL.md), "Two
workflows"): every resolution diff then shows both sides and the chosen result. The price is
that the merge and the unit commits before the tip do not build — bisect `next` with
`--first-parent`, and merge the batch PR **with a merge commit**, never squash or rebase,
or the upstream ancestry is lost. `next` requires two approvals; you never merge it.

## 1. Pick the batch from the request, then confirm it

Translate the request into a bound: "the next 200 commits" (`--count 200`), "up to
`<hash>`" (`--until`), "everything before 2021-10-01" (`--before`). The upstream bound is the
pinned target of the major (PG15: `adadae45816`, see greengage-pg-merge); a batch never
crosses it.

```bash
git fetch origin next && git fetch pg                     # pg = github.com/postgres/postgres
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pg_batch.py select \
    --source origin/next --upstream adadae45816 --count 200 --out batch.json
```

`select` prints the cut with its neighbours and exits **1** when the cut splits a revert
pair — the batch has a commit whose revert lies after the cut. Move the cut to the printed
*closing cut* (includes the revert) or *earlier cut* (excludes the reverted commit); do not
merge a change you know upstream takes back. On `next` before b1, `--count 200` exits 1:
`6a2c532c223` (disable the pg_receivewal ZLIB TAP tests on Windows) is reverted by
`0b8ea707580` 31 commits later. b1 took 468 commits instead,
which closes every revert pair and the `shared_memory_size` series; batch 2 starts at the
Value-node removal (`639a86e36aa`).

`select` also lists **follow-ups after the cut** — later upstream commits that cite a batch
commit. Record them in the PR's follow-ups: the next batch applies them on top (b1:
`ff9f111bce2` fixes `515e3d84a0b`, and Greengage already had it as a backport, so the next
batch applies it twice). For features reverted before the release tag, run the lookahead
gate in [greengage-pg-merge](../greengage-pg-merge/SKILL.md) as well.

**Confirm the batch with the user before merging** — count, first and last commit, and
why the cut sits there. b1's size was picked without asking; the user expected about 200.

## 2. Branch from the source

```bash
git worktree add -b sync-15x-b2 ../gpdb-15b2 origin/next
```

The source is `next` unless the request names another branch; the PR's base is the
source. Do not start from `8.x`: when b1 was cut, `8.x` was still at the b14 level.

## 3. Merge with the markers committed

```bash
cd ../gpdb-15b2
git -c merge.conflictStyle=zdiff3 merge --no-commit --no-ff <cut>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pg_batch.py inventory HEAD <cut> --json ../b2/inv.json --apply .
git add -A && git commit -m "Merge upstream PostgreSQL <cut> into sync-15x-b2"
git tag sync-15x-b2-dirty
```

`inventory` replays the merge (`git merge-tree --write-tree`, git ≥ 2.38) and sorts every
hunk: **AUTO** (Greengage deleted the file, copyright header, a whitespace-only side — `--apply`
writes these), **REGEN** (expected output and generated files: do not hand-merge, regenerate
after the build) and **RESOLVE**. It also prints the two lists that make a unit *must review*
whatever its resolution looks like: upstream deleting or moving a file Greengage modifies
(R2), and the **day-1 commits** that overlap Greengage-heavy files most (R1). Resolve those
first. b1: 151 files — 50 AUTO, 14 REGEN, 87 RESOLVE with 197 hunks.

## 4. Resolve and bring up on the raw history

Work on `sync-15x-b2` itself and open a **draft PR** against the source as soon as the tree
builds: CI only runs on pull requests ([greengage-ci](../greengage-ci/SKILL.md)). Resolve
by [greengage-pg-merge](../greengage-pg-merge/SKILL.md) — its rules, its commit message
template, its phase ladder — and add three trailers to every commit:

```
Resolve conflicts in the executor

<numbered decisions, as in the greengage-pg-merge template>

UoC: executor                      # the unit this commit belongs to
Upstream: 83f4fcc6550 28d936031a8  # the upstream commits that collided
Kind: resolve                      # resolve | bring-up | build-fix | answer-files
```

The trailers are what step 5 reads. `UoC:` places files that no topic claims (Greengage-only
files a fix touched) and is required for them — `series` refuses with `cannot place <path>
(bring-up commit …)` otherwise. `Kind: build-fix` keeps a pure compile fix out of rule R7. A
commit may span several units; `series` splits it by file.

CI loop facts from b1:

| Fact | Consequence |
|---|---|
| A push cancels the in-flight run of the same PR; marking ready or editing the body starts none | Push to re-run; read the conclusion before triaging — `cancelled` is not red |
| `gh run view --job <id> --log` returned an empty file | `gh api repos/GreengageDB/greengage_sync/actions/jobs/<id>/logs`, then `grep -a 'DIFF FILE:'` |
| Known flakes, unchanged by the batch: contrib `ltree` `siglen=8168` "index row requires 8312 bytes", `bfv_partition_plans` (JIT) `Max (segment N)`, isolation2 `fsync_ao` | `gh run rerun <run> --failed`; anything else is real until a rerun says otherwise |
| JIT results carry `Settings: jit=…` lines | Regenerate answer files from non-JIT runs only, through [greengage-answer-files](../greengage-answer-files/SKILL.md) |
| Three of the 12 bugs were pre-existing on `next` (HOT-chain pruning corruption, PG bug #17255; a relcache policy race; `pg_upgrade` dropping `PUBLIC`'s rights on schema `public`) | Fix them in the batch, with a backport where upstream has one, and say "pre-existing" in the PR |

When CI is green, push the same commits as `sync-15x-b2-raw`. That branch is never rebuilt.

## 5. Group the changes into units of change

A unit is what one reviewer can own: an upstream API change together with its Greengage
re-grafts (`memoize-rename`, `catalog-declare-index`), a subsystem (`planner`, `pg-dump`,
`tap-postgresnode`), or an upstream-only area (`regex`, `docs`). b1 had 31 units for 953
changed files. Write `topics.json` — format, assignment order and the b1 units are in
[reference/units-of-change.md](reference/units-of-change.md) — then:

```bash
B=../b2; P=${CLAUDE_PLUGIN_ROOT}/scripts/pg_batch.py
python3 $P facts sync-15x-b2-dirty^1 <cut> sync-15x-b2-dirty sync-15x-b2-raw --inventory $B/inv.json --out $B/facts.json
python3 $P assign $B/facts.json $B/topics.json --out $B/uocs.json
python3 $P classify $B/facts.json $B/uocs.json --out $B/tiers.json
```

Run them from the checkout (or pass `-C`), and **do not pipe them through `tail`**: the pipe
hides the exit status, and in b1 a failed `classify` left a stale `tiers.json` behind that way.
`assign` must report no files falling through to `misc`. Re-run all three whenever RAW moves.

## 6. Review tiers come from per-file rules

`classify` gives each unit **must review**, **no review** or **merge automatically** from
rules R1–R8 of the b14–b17 review triage (607 PRs). Definitions and thresholds are in
[reference/review-rules.md](reference/review-rules.md). Two facts govern how to read them:

- **The rules are evaluated per file.** Their thresholds were fitted per PR, and the median
  PR touched one file. Aggregated per unit, every unit of b1 came out *must review*; per
  file, b1 is 24 must review, 6 no review, 1 merge automatically, and each reason names the
  files that tripped it.
- **A tier is a recommendation to the team, not a gate.** Every unit still passes CI, and
  "no review" means only that b14–b17 found no defect in that class.

## 7. Rebuild the review branch and prove it

```bash
git worktree add --detach ../gpdb-15b2-series sync-15x-b2-raw
python3 $P series $B/facts.json $B/uocs.json $B/tiers.json --worktree ../gpdb-15b2-series \
    --branch sync-15x-b2-review --pr-branch sync-15x-b2 --out $B/series.json
python3 $P verify $B/facts.json $B/series.json
```

The PR branch is checked out in the bring-up worktree, so build on a temporary branch and
name the PR branch with `--pr-branch`: the merge message and the PR text use that name. (b1
built on a scratch name without it, and the scratch name ended up in the merge message.)

`series` re-creates the merge with DIRTY's tree and parents, then commits each unit in
tier order: the net change of the unit's files from the merge to RAW, a message with the
summary, review status, upstream commits and the bring-up commits it squashes
(`Raw-commit:` trailers). A unit with no Greengage change is an **empty commit** that only
records it — b1 had five (`regex`, `ecpg`, `contrib`, `docs`, `encoding-unicode`). It
refuses unless the tip tree equals RAW. `verify` re-checks independently: merge tree and
parents, one owner per file, every file at RAW's content, every bring-up commit listed.

Then push, after the user agrees to the force-push, and move the bring-up worktree onto the
new head (same tree, so nothing in it changes):

```bash
git push origin sync-15x-b2-raw
git push --force-with-lease=sync-15x-b2:<old head> origin sync-15x-b2-review:refs/heads/sync-15x-b2
git -C ../gpdb-15b2 reset --soft sync-15x-b2-review
```

CI runs again on the same tree; it must be green again (rerun known flakes). **Once a review
PR exists, never rebuild or force-push the batch branch**: review branches point at the old
unit commits. Fixes reach the batch through review PR merges from then on.

## 8. Write the PR description from the template

The description is part generated, part written. Write the sections file from the skeleton
in [reference/pr-template.md](reference/pr-template.md) — intro, adaptations and bugs,
validation, follow-ups — then:

```bash
python3 $P render $B/facts.json $B/uocs.json $B/tiers.json $B/series.json \
    --sections $B/sections.md --repo GreengageDB/greengage_sync --inventory $B/inv.json --out $B/body.md
gh api -X PATCH repos/GreengageDB/greengage_sync/pulls/<n> -F body=@$B/body.md
```

`render` prints the title and generates the organisation paragraph, merge statistics, the
unit table (Review PR column `—`), the review legend and the review-PR instructions. It exits
1 when the body reaches GitHub's 65,536-character limit (b1: 31.6k with `--max-inline 12`).
Edit the body with `gh api -X PATCH`, not `gh pr edit`: on `greengage_sync`, `gh pr edit`
fails with a Projects (classic) deprecation error from GraphQL. Mark the PR ready when CI is
green, then hand over to [greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `select` exits 1 | The cut splits a revert pair | Take the printed closing or earlier cut |
| `inventory`: `git merge-tree … failed` | git older than 2.38 | Upgrade git; the inventory needs `--write-tree` |
| `facts`: `DIRTY must be the merge commit with parents BASE and CUT` | BASE given as a branch that has moved since the merge | Pass the merge's own first parent, `<dirty>^1` |
| `series`: `cannot place <path>` | A Greengage-only file changed by a commit without a `UoC:` trailer | Add the path to a topic, re-run assign and classify |
| `series`: `does not reproduce RAW` | RAW moved after `facts`, or the build worktree was dirty | Re-run facts, assign, classify; use a fresh worktree |
| `verify` reports mismatches | The branch was edited after `series` | Rebuild; never hand-edit the review layout |
| Every unit is *must review* | Rules aggregated per unit, or build fixes without `Kind: build-fix` | Use `classify` as is; fix the trailers |

## What not to do

- Do not choose the batch size silently, and do not cross the major's pinned target.
- Do not merge, squash or rebase the batch PR; the team merges it with a merge commit.
- Do not rebuild or force-push the batch branch after the first review PR is open.
- Do not regenerate answer files from JIT runs or from a run with a crashed segment.
- Do not read *no review* as *no CI*: every unit is validated by the tip's CI run.

See also: [greengage-pg-merge](../greengage-pg-merge/SKILL.md) ·
[greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md) ·
[greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md) ·
[greengage-ci](../greengage-ci/SKILL.md) ·
[greengage-answer-files](../greengage-answer-files/SKILL.md) ·
[greengage-testing](../greengage-testing/SKILL.md)
