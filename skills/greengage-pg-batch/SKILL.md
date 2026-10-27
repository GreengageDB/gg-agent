---
name: greengage-pg-batch
description: Prepare a batch of upstream PostgreSQL commits on greengage_sync for team review - picking the cut and checking split revert pairs, merging with conflict markers committed, bring-up on a raw branch, units of change (UoC) split per operation by conflict-region, bring-up-commit, identifier and answer-file causes, diff minimisation against both parents, independence and completeness checks, one PR per unit into <prefix>-base. Use when asked to take the next N upstream commits into greengage_sync, to split a batch into units, or to prepare a sync-<major>x-b<N> batch PR.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.2.0"
  greengageVersion: "8.x campaign line in greengage_sync (next and the sync-<major>x-b<N> batch branches)"
---

# Preparing an upstream PostgreSQL batch for review

A **batch** brings a slice of upstream PostgreSQL history into `greengage_sync` `next`, shaped
so the team can review it unit by unit. The reference is `sync-15x-b1`: 468 upstream commits
`e1c1c30f635..3b231596ccf`, 101 files committed with conflict markers, 12 real bugs found
during bring-up. It was first split per file into 31 units
([greengage_sync#626](https://github.com/GreengageDB/greengage_sync/pull/626)), then re-split
per operation into 42 units, each reviewed in its own PR, with
[greengage_sync#660](https://github.com/GreengageDB/greengage_sync/pull/660) as the batch PR.
This skill is the second way. Every command below was run against b1.

The merge itself — resolving a conflict semantically, re-grafting Greengage logic, the
compile → regress → CI ladder — belongs to [greengage-pg-merge](../greengage-pg-merge/SKILL.md);
load it before step 4. The unit PRs are [greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md),
their table in the batch PR is [greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md).

Scripts, all under `${CLAUDE_PLUGIN_ROOT}/scripts/`: `pg_batch.py` (cut, merge inventory,
per-file facts), `uoc_split.py` (the per-operation split and the unit branches), both git only
and run from the `greengage_sync` checkout or with `-C`; `uoc_review.py` (unit PRs, through
`gh`); `uoc_sync_test.sh` and `sync-uoc-test.yml` (the test branch).

## The deliverable is independent unit PRs, not one merge

```
sync-15x-b1-base   next ── Merge upstream PostgreSQL 3b231596ccf    (DIRTY: markers committed)
sync-15x-b1-uocN                      └── UoC N: <title>             (only unit N's operations)
sync-15x-b1-test                      └── base + every uocN merged   (CI runs here, PR #631)
sync-15x-b1-raw    next ── the same merge ── 36 bring-up commits     (RAW: green; never merged)
```

| Name | What it is |
|---|---|
| `<prefix>-base` | DIRTY, the merge commit with markers; head of the batch PR into `next` |
| `<prefix>-uoc<N>` | One commit, parent DIRTY: the conflict resolutions and fixes of unit N only; its PR targets `<prefix>-base` |
| `<prefix>-test` | Octopus merge of the base and every unit branch; its PR into the base runs CI on the combined tree |
| `<prefix>-raw` | The bring-up history, kept for provenance and as the source of every operation's cause |
| `<prefix>-dirty` (tag) | DIRTY on the raw branch |

Every unit changes only its own lines, so the unit PRs merge cleanly **in any order** and all
of them together give RAW's tree. The base does not build until all are merged; CI validates
the test branch instead. The batch PR is merged into `next` **with a merge commit**, after the
last unit PR that goes into it, never squashed or rebased, or the upstream ancestry is lost.
`next` requires two approvals; you never merge it.

## A unit is one upstream change with everything it caused, not a set of files

The per-file split gave each file to one "main" unit. The Greengage changes caused by one
upstream commit then landed in other units (`functioncmds.c` from the pinned-objects change
in option parsing, `outfast.c` from Memoize in node support), and units carried conflicts
that were not theirs (`pg_depend.c` in the pinned objects). Split by **operation** — one
difflib opcode of a file's DIRTY → RAW change — instead:

- A unit is one upstream change (one or a few tightly related commits) plus **every**
  Greengage change it caused: conflict resolutions, Greengage-only adaptations, answer files.
- A fix caused by an upstream commit belongs to that commit's unit ("Fix build"; `gpstart`
  waiting after `7ff23c6d277` lets the checkpointer run during crash recovery).
- A Greengage fix that the batch did not cause and CI merely exposed gets **its own unit at
  the end**: b1 had three (HOT-chain backport of PG bug #17255, healing a transiently stale
  ENTRY policy, binary serialization of `WindowDef`).
- Such a unit may be **held out of the batch**: it stays on the test branch only, and the batch
  PR names it and why. b1 held two of the three: UoC 26 (the policy heal: the crash it fixes
  could not be reproduced without it, and it has no test) and UoC 27 (the HOT-chain backport:
  upstream has it as `18b87b201f7`, which arrives with a later PG15 batch). Only a unit the
  batch does not depend on can be held — the base must build without it.
- The number of units is not fixed. A topic with no Greengage operation gets no branch (b1:
  `regex`, `ecpg`, `contrib`, `docs`, `encoding-unicode`, and `access-methods` once emptied).

## 1. Pick the batch from the request, then confirm it

Translate the request into a bound: "the next 200 commits" (`--count 200`), "up to `<hash>`"
(`--until`), "everything before 2021-10-01" (`--before`). The upstream bound is the pinned
target of the major (PG15: `adadae45816`, see greengage-pg-merge); a batch never crosses it.

```bash
git fetch origin next && git fetch pg                     # pg = github.com/postgres/postgres
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pg_batch.py select \
    --source origin/next --upstream adadae45816 --count 200 --out batch.json
```

`select` exits **1** when the cut splits a revert pair: move the cut to the printed *closing
cut* (includes the revert) or *earlier cut* (excludes the reverted commit). On `next` before
b1, `--count 200` exits 1: `6a2c532c223` is reverted by `0b8ea707580` 31 commits later. b1
took 468 commits, closing every revert pair and the `shared_memory_size` series. `select`
also lists **follow-ups after the cut** (b1: `ff9f111bce2` fixes `515e3d84a0b`); record them
for the next batch, and run the lookahead gate of greengage-pg-merge for reverted features.

**Confirm the batch with the user before merging** — count, first and last commit, and why
the cut sits there. b1's size was picked without asking; the user expected about 200.

## 2. Branch from the source, 3. merge with the markers committed

```bash
git worktree add -b sync-15x-b2 ../gpdb-15b2 origin/next     # source: next, never 8.x
cd ../gpdb-15b2
git -c merge.conflictStyle=zdiff3 merge --no-commit --no-ff <cut>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pg_batch.py inventory HEAD <cut> --json ../b2/inv.json --apply .
git add -A && git commit -m "Merge upstream PostgreSQL <cut> into sync-15x-b2"
git tag sync-15x-b2-dirty
```

`inventory` replays the merge (`git merge-tree --write-tree`, git ≥ 2.38) and sorts every hunk:
**AUTO** (Greengage deleted the file, copyright header, whitespace-only side — `--apply`
writes these), **REGEN** (expected output and generated files: regenerate after the build)
and **RESOLVE**. It also lists upstream deletions or moves of Greengage-modified files and the
**day-1 commits** overlapping Greengage-heavy files most; resolve those first. The markers stay
committed on purpose: every resolution diff then shows both sides and the chosen result.

## 4. Resolve and bring up on the raw history

Resolve by [greengage-pg-merge](../greengage-pg-merge/SKILL.md) on the branch and open a
**draft PR** against the source as soon as the tree builds: CI only runs on pull requests.
Give every commit three trailers; the split reads them:

```
UoC: executor                      # the unit this commit belongs to
Upstream: 83f4fcc6550 28d936031a8  # the upstream commits that caused it
Kind: resolve                      # resolve | bring-up | build-fix | answer-files
```

| CI fact from b1 | Consequence |
|---|---|
| A push cancels the in-flight run of the same PR; editing the body starts none | Read the conclusion first — `cancelled` is not red |
| `gh run view --job <id> --log` returned an empty file | `gh api repos/GreengageDB/greengage_sync/actions/jobs/<id>/logs`, then `grep -a 'DIFF FILE:'` |
| Known flakes: contrib `ltree` `siglen=8168`, `bfv_partition_plans` (JIT) `Max (segment N)`, isolation2 `fsync_ao` | `gh run rerun <run> --failed`; anything else is real until a rerun says otherwise |
| JIT results carry `Settings: jit=…` lines | Regenerate answer files from non-JIT runs only ([greengage-answer-files](../greengage-answer-files/SKILL.md)) |
| Three of the 12 bugs were pre-existing on `next` | Fix them in the batch, as units of their own, and say "pre-existing" in the PR |

When CI is green, push the same commits as `sync-15x-b2-raw`. That branch is never rebuilt:
it is the evidence the split reads.

## 5. First cut: topics and the per-file owner

Write `topics.json` — the units in review order, each with the upstream commits that define
it and its file paths; format and heuristics in [reference/units-of-change.md](reference/units-of-change.md):

```bash
B=../b2; P=${CLAUDE_PLUGIN_ROOT}/scripts/pg_batch.py; S=${CLAUDE_PLUGIN_ROOT}/scripts/uoc_split.py
python3 $P facts sync-15x-b2-dirty^1 <cut> sync-15x-b2-dirty sync-15x-b2-raw --inventory $B/inv.json --out $B/facts.json
python3 $P assign $B/facts.json $B/topics.json --out $B/uocs.json
```

`assign` gives each file one owner. That owner is only the **fallback** of the operations
nothing else places; `assign` must still report no file falling through to `misc`. Add the
independent-fix units as topics with no commits. `classify` (rules R1–R8,
[reference/review-rules.md](reference/review-rules.md)) is an optional per-file hint for where
reviewers should look first; do not copy its flags into unit descriptions — in b1 they misfired.
Do not pipe these commands through `tail`: the pipe hides a failed exit status.

## 6. Give every operation a unit

```bash
python3 $S --dir $B causes      # b1: 190 files, 4039 operations, 527 in conflict regions; ~1 min
python3 $S --dir $B assign      # fast: re-run after every split.json edit
python3 $S --dir $B review --how raw,tokens2,testL     # read the moves
```

`causes` finds four kinds of evidence; `assign` uses them in this order:

| Placement (`how`) | Evidence | Rule |
|---|---|---|
| `region` | The operation touches a conflict region. Its theirs section is verbatim upstream text: located in CUT's file, `git log -L` over it (plus a line each side, for pure deletions) in `<mbase>..<cut>` names the commits | A region is atomic: it goes to the units claiming those commits |
| `raw` | `git log -L` over the operation's final lines on the raw history names the bring-up commit; if nothing, the only bring-up commit that touched the file | Only through split.json `redirect`: independent fixes to their units, build fixes to the unit of the commit they follow |
| `tokens2` | The operation removes identifier X and adds Y, and one upstream commit removed X **and** added Y (rare tokens weigh more) | A rename. A one-sided match is noise and is never used |
| `testL` | Answer files: the upstream file (the planner `.out` for `_optimizer.out`) is blamed over the batch and aligned with DIRTY | A replacement goes to the commit that wrote **at least half** of the replaced lines, an insertion to the commit that wrote the line before it; otherwise it is a Greengage regeneration |
| `none` | Nothing | Stays with the per-file owner |

Candidates are the units claiming the cause commits. If the per-file owner is among them the
operation stays (fewer moves); otherwise it goes to the earliest candidate. Answer-file
operations left in place follow a `testL` neighbour in the same result set or within two lines
(`group`); an `_optimizer.out` operation follows the one at the same place of the `.out`
(`mirror`). Renames and regions pull no neighbours: they would drag in header widths and
foreign comments. b1: 215 of 4039 operations left their per-file unit; 59 needed an override.

Manual decisions go into `$B/split.json` ([reference/split-config.md](reference/split-config.md)):
`overrides` (`"path:DIRTY line": slug`), `redirect`, `primary` for a commit several units claim
when completeness depends on it (b1: `d68a0039121` → storage-locking). Overrides are needed
where the rules cannot see the cause: a comment mixing a rename with `get_hash_memory_limit`,
a row moved in sorted output (`rangefuncs_cdb.out`), an adaptation to a removed identifier
outside any conflict (`bgwriterLaunched`, `InitBufferPoolBackend`), a declaration a moved
region needs (`recursive` in `analyze.c`). `assign` exits 1 when an override matches no
operation — DIRTY line numbers are their keys.

## 7. Minimise the diff against both parents

- Judge minimality against **both parents**: Greengage before the merge (`<dirty>^1`) and
  upstream (`<cut>`). The diff from DIRTY says nothing: theirs always follows ours inside the
  markers, so "take upstream" looks like a reordering there.
- Upstream code stays where upstream put it. A Greengage block stays one contiguous insertion
  at its old anchor (`varsup.c`: `SetNextObjectId`/`StopGeneratingPinnedObjectIds` right after
  `GetNewObjectId`, the `AdvanceObjectId…` block after them).
- Do not reorder functions or lines without a cause; keep sorted lists sorted. Copy upstream
  comments into Greengage files verbatim (`pg_magic_oid.h`); change a GPDB note minimally.
- Do not change values that already passed the tests. Put Greengage-only decisions
  (`nextRelfilenode = FirstGenbkiObjectId`) into the unit description for review.
- **Minimising future conflicts wins** over every other preference.
- Measure, per conflicted file: the size of the Greengage delta against upstream before and
  after the merge, and lines both removed and added in that delta (moves). More moves means
  a needless reordering.

A minimisation changes RAW's content: write it as an `edits` entry in split.json (exact
`old`/`new` text, applied from one unit on), not as a new bring-up commit.

Answer files are minimised on the unit branch, after `branches`: `gpdiff_min.py -o <dir>
<prefix>-base <prefix>-uocN` puts back every hunk gpdiff does not need and strips ignored text
from added lines only ([minimizing regenerated files](../greengage-answer-files/reference/minimizing-regenerated-files.md)).
On the 12 first files of b1's `regress-tests` unit it cut the changed lines from 1219 to 143.

## 8. Prove the split, then read it

```bash
python3 $S --dir $B check       # exit 1 on a conflict, a RAW mismatch or a completeness hole
```

| Section | Proves or lists |
|---|---|
| `indep` | Each unit alone on DIRTY, merged one by one with `git merge-file` in unit order and in reverse: no conflict, and the result is RAW (plus edits). b1: 39 files shared by several units, 0 problems |
| `complete` | In each unit's own tree, an identifier its own commits removed from the code base (and RAW no longer has) occurs only inside unresolved markers. b1: 0 |
| `removed` | Operations dropping a use of a removed identifier outside that identifier's unit — override candidates |
| `crossdeps` | One new identifier introduced by several units of a file — a use may land without its definition (b1: `live` in `tablecmds.c`) |
| `audit` | NONE (no cause), MULTI (cause claimed by several units), RAWX (bring-up commit whose `Upstream:` names none of the unit's commits), OVR — the per-unit re-check list |

Then read by eye: every region move (one example per file and direction), every `raw`, every
`tokens2`, a sample of `testL`. The unit trees do not build alone (DIRTY has markers); do not try.
If an edit changed RAW beyond comments, build and test the final tree.

## 9. Describe each unit

`bundle` writes `$B/units/NN-slug/`: `diff.patch`, `ops.txt`, `upstream.txt` (causes with
counts), `raw.txt` (the bring-up commit messages, the best answer to "why"). Write
`$B/msg/<slug>.txt` from them:

1. Title line, without `UoC N:` (`branches` adds it).
2. What upstream changed, in 1–3 sentences with hashes.
3. What Greengage did and why: Greengage-only code, each resolved conflict and which side was
   taken, decisions upstream does not have and why they are safe.
4. `Review focus:` — where a reviewer must look (b1 Memoize: without `T_Memoize` in
   `outfast.c`/`readfast.c` a plan with Memoize cannot be dispatched).
5. `Upstream:` — only the commits that actually caused work in the unit.
6. Trailers `UoC: <slug>`, `Batch: upstream <mbase>..<cut>`, one `Raw-commit:` per bring-up commit.

## 10. Branches, unit PRs, the test branch

```bash
python3 $S --dir $B branches sync-15x-b2                 # dry run: numbers, trees, titles
python3 $S --dir $B branches sync-15x-b2 --create --base
git push origin sync-15x-b2-raw sync-15x-b2-base sync-15x-b2-uoc1 …     # only after the user agrees
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py open --prefix sync-15x-b2 --all --dry-run
```

Unit numbers live in `$B/numbers.json` and never change: a new or split-off unit gets the next
free number. Authors come from the bring-up commit behind most of the unit's operations
(`author_from` overrides). Creating branches and PRs is visible to the team: dry run first.

The test branch: `git checkout -b sync-15x-b2-test sync-15x-b2-base && git merge --no-ff
sync-15x-b2-uoc1 …`, push, open its PR into the base, and commit `sync-uoc-test.yml` to
`.github/workflows/` **on the base**: it runs on `pull_request`, whose workflow file comes
from the PR's merge ref (`pull_request_target` would read the default branch and never run).
On every unit PR change it merges the unit branches and the base that the test branch lacks,
the PR's own unit first. A branch that conflicts with the test branch is **left out** and the
rest are merged and pushed; every later run retries it. The conflict is reported once per
branch head, in a comment on that unit's PR (on the triggering PR for the base), and the job
fails only when the PR's own unit or the base was left out. Set the `SYNC_PUSH_TOKEN` secret,
or its pushes leave the CI runs awaiting approval. `uoc_sync_test.sh <prefix>` does the same by
hand without commenting: it prints the branches it left out and exits 1 when the base is one of
them. (The leave-out behaviour replaced all-or-nothing merging on 2026-10-23 and has been run
locally only, not yet on GitHub.) **Unit branches must never be force-pushed**: the test branch
already holds their commits. Remove the workflow before the batch PR merges.

Write the batch PR description from [reference/pr-template.md](reference/pr-template.md),
fill `{Un}` with `uoc_split.py links`, and keep its unit table current with
[greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md). Edit it with
`gh api -X PATCH`: `gh pr edit` fails on `greengage_sync` with a Projects (classic) error.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `select` exits 1 | The cut splits a revert pair | Take the printed closing or earlier cut |
| `inventory`: `git merge-tree … failed` | git older than 2.38 | Upgrade git |
| `assign`: `N changed files have no unit` | A file whose net change BASE → RAW is empty, touched by a commit without a `UoC:` trailer | `owners` in split.json |
| `assign`: `split.json names units that topics.json does not have` | A unit was renamed or split after the entry was written | Point the entry at the new slug or the part |
| `assign` exits 1: overrides match no operation | DIRTY changed, or the key is not the operation's first DIRTY line | `review --all --path <file>` shows the keys |
| `check`: `conflict in <file> merging <unit>` | Two units' operations touch adjacent lines | Override one of them into the other unit |
| `check complete` lists a use | The fix of a removed identifier sits in another unit | Override that operation, or pin the commit with `primary` |
| A unit PR shows changes it should not | The branch was rebuilt after review started | Never rebuild an open unit; fix on its branch |
| A unit PR gets "Could not merge `<prefix>-uocN` into `<prefix>-test`" | A review fix touches lines the test branch already changed differently (another unit, or a fix merged by hand) | Merge the unit branch into the test branch by hand and push; the next run picks the rest up |

## What not to do

- Do not choose the batch size silently, and do not cross the major's pinned target.
- Do not split per file, and do not leave an independent Greengage fix inside an upstream unit.
- Do not judge minimality against the merge commit with markers.
- Do not hand-edit unit branches before review starts; change split.json and rebuild instead.
- Do not force-push a unit branch, or rebuild one whose PR is open.
- Do not regenerate answer files from JIT runs or from a run with a crashed segment.

See also: [greengage-pg-merge](../greengage-pg-merge/SKILL.md) ·
[greengage-uoc-review-pr](../greengage-uoc-review-pr/SKILL.md) ·
[greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md) ·
[greengage-ci](../greengage-ci/SKILL.md) ·
[greengage-answer-files](../greengage-answer-files/SKILL.md) ·
[greengage-testing](../greengage-testing/SKILL.md)
