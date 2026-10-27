---
name: greengage-uoc-review-pr
description: Open and carry through the review PRs of a greengage_sync batch split into units of change (UoC) - one <prefix>-uocN -> <prefix>-base PR per unit, opening them with uoc_review.py, reading a unit by its Review focus, review fixes on the unit branch without force-push, the -test branch CI runs, squash-merging into the base, splitting a unit under review, holding a unit out, closing the batch. Use when a reviewer is assigned to a unit, when asked to open the unit PRs of sync-15x-b2, or when a unit PR is approved.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.2.0"
  greengageVersion: "8.x campaign line in greengage_sync (batches split by greengage-pg-batch)"
---

# Reviewing a batch unit by unit

A batch split by [greengage-pg-batch](../greengage-pg-batch/SKILL.md) is reviewed as one pull
request per unit of change. Each PR holds one commit on top of the upstream merge: only that
unit's conflict resolutions, adaptations and answer files. The batch PR (`<prefix>-base` →
`next`) is the integration point; its unit table tracks the unit PRs
([greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md)). b1 reviewed 42 units
this way: PRs #632–#690 into `sync-15x-b1-base`, batch PR #660, test PR #631.

The tool is `${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py`. It works through the GitHub API with
`gh api`, needs no checkout, and takes the batch PR as a number or a URL, or the branch prefix.

## Every unit PR starts from the same merge commit

```
<prefix>-base   DIRTY ── (unit PRs squash-merged here, in any order) ──▶ PR into next
                  ├── <prefix>-uoc1  UoC 1: <title>  ── review fixes
                  ├── <prefix>-uoc2  UoC 2: <title>
                  └── <prefix>-test  base + every uocN, merged   (CI)
```

| Branch | Points at | Why |
|---|---|---|
| `<prefix>-base` | DIRTY, then the merged units | Every unit PR targets it; its diff from DIRTY is exactly one unit |
| `<prefix>-uoc<N>` | The unit commit, review fixes on top | Built by `uoc_split.py branches`; never rebuilt once its PR is open |
| `<prefix>-test` | Octopus merge of the base and every unit branch | The only tree that builds before all units are merged; its PR runs CI |

The diff of a unit PR is the Greengage side of the unit. Each conflict hunk removes the
committed markers, so it shows both sides and the chosen result. The unit's upstream commits
are named in its description; they are reviewed upstream and are not in the diff. The units
change disjoint lines, so the PRs merge cleanly in any order.

## Open them: dry run, confirm, then create

```bash
U=${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py
python3 $U open --prefix sync-15x-b2 --repo GreengageDB/greengage_sync --all --dry-run
python3 $U open --pr 700 --repo GreengageDB/greengage_sync --uoc 7 --reviewer <login>
```

The branches must already be on GitHub (`uoc_split.py branches --create --base`, then a push
the user agreed to). `open` takes the PR title and body from the `UoC N:` commit — the title
line and the unit description — and adds a `<!-- uoc-review: prefix=… uoc=N -->` marker. PRs
are visible to the whole team: run the real command only when the user asked or confirmed
the dry run. b1 opened all units at once; reviewers then took them one by one.

| Result | Meaning | What to do |
|---|---|---|
| `UoC N already has an open PR` (exit 1; with `--all` only reported) | Opened before, by the tool or by hand | Use that PR |
| `no branch <prefix>-uocN` (exit 2) | Not pushed, or the unit has no operations (upstream-only topics get no branch) | Push it, or there is nothing to review |
| `no commit "UoC N: ..."` (exit 2) | The branch was not made by `uoc_split.py branches` | Open the PR by hand |

Titles carry no unit total (`UoC 7:`, not `UoC 7/28:`): the number of units changes during
review. b1's first PRs had the total and had to be closed and reopened when units were split.

## Review: read the unit by its description

The description is the reviewer's map: what upstream changed, what Greengage did and why,
**Review focus**, the upstream commits, and the bring-up commits (`Raw-commit:`) that hold the
reasoning. Read the Review focus files first.

| Look for | Why |
|---|---|
| A Greengage line that is in neither the resolution nor the merge base | A re-graft that vanished — the most common real bug of a bump |
| An upstream line the resolution dropped | An upstream fix Greengage silently refused |
| Lines on neither side of a conflict | An invention: is it needed, and is it MPP-correct? |
| Code moved against both parents | Minimality is judged against Greengage before the merge and upstream, not against the markers; a needless move costs a conflict in every later batch |
| An answer-file hunk where a result became an `ERROR` | Never accept a regenerated failure ([greengage-answer-files](../greengage-answer-files/SKILL.md)) |
| A change that belongs to another upstream commit | It belongs in that unit; say so on the PR rather than accepting it here |

For the MPP checklist — dispatch and serialization, motion and locus, distributed
transactions, AO auxiliary relations — delegate to the `greengage-mpp-reviewer` subagent with
the unit PR's diff.

## Fixes go on the unit branch, forward only

- Push review fixes to `<prefix>-uoc<N>` as new commits. **Never force-push a unit branch**:
  the test branch already contains its commits, and a rewritten commit no longer merges into it.
- Keep a fix inside the unit's own lines. A fix that must touch lines another unit changed goes
  to that unit's PR, or the two PRs stop merging cleanly.
- The test branch picks the fix up by itself: `sync-uoc-test.yml` on the base merges every unit
  branch the test branch lacks whenever a unit PR changes. Check the test PR's CI after a fix;
  `uoc_sync_test.sh <prefix>` does the same merge by hand if the workflow is stuck.
- A unit branch that conflicts with the test branch is left out, and the unit PR gets one
  comment per branch head: "Could not merge … into `<prefix>-test` automatically", with the
  files. Until someone merges it into the test branch by hand, CI runs without that fix. The
  workflow fails on the unit's own PR only, so the other units are not held up.

## Merge: squash into the base, then refresh the table

b1 squash-merged every approved unit PR into the base: the base gains one commit per unit,
`UoC N: <title> (#PR)`, whose body is the unit description — update the description first if
the review changed what the unit does. Other unit PRs stay mergeable because the units are
disjoint. Then run [greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md).

## Splitting a unit under review

When a unit turns out to hold unrelated upstream changes, split it in the batch directory
([units-of-change.md](../greengage-pg-batch/reference/units-of-change.md), "Splitting a unit
whose PR is already open"): the first part keeps the number, branch and PR; the other parts get
new numbers and new PRs; the review fixes already on the branch go to the parts whose files they
touch. b1 split seven units into three parts each (UoC 29–42).

## Holding a unit out of the batch

A unit that fixes something older than the batch can stay out of it: its PR stays open (b1: as
a draft), it is never merged into the base, and the test branch keeps it. Hold a unit only when
the base builds and passes without it, and name it in the batch PR with the reason. b1 held
UoC 26, a relcache-race fix with no reproducer and no test, and UoC 27, a backport upstream
brings in a later batch. Record it in the unit table:

```bash
python3 $U status --pr 660 --repo GreengageDB/greengage_sync --held 26,27
```

Later runs read the list back from the batch PR (`--held ''` clears it). A held unit is not
"not merged yet", and its PR is not closed: it is the record of the fix until a later batch
or a separate PR takes it.

## Closing the batch

When every unit PR except the held ones is merged, the base builds. Its tree equals the test
branch's tree without the workflow file and without the held units. Check that difference
(`git diff <prefix>-base <prefix>-test` shows only those). Remove
`.github/workflows/sync-uoc-test.yml` from the base, close the test PR, let CI run on the batch
PR, and hand it to the team: it merges into `next` with a merge commit, after two approvals.

## What not to do

- Do not force-push or rebuild a unit branch whose PR is open.
- Do not put a unit total in titles or branch names.
- Do not fix another unit's lines in this unit's PR.
- Do not merge the batch PR, or squash or rebase it; only the unit PRs are squash-merged.
- Do not leave the workflow file on the base when the batch PR merges.
- Do not hold a unit the base needs to build or pass, and do not hold one silently.

See also: [greengage-pg-batch](../greengage-pg-batch/SKILL.md) ·
[greengage-uoc-review-status](../greengage-uoc-review-status/SKILL.md) ·
[greengage-internals](../greengage-internals/SKILL.md) ·
[greengage-pg-merge](../greengage-pg-merge/SKILL.md) ·
[greengage-ci](../greengage-ci/SKILL.md)
