# Batch PR description template

Lookup material for [greengage-pg-batch](../SKILL.md), step 8. The template is the
description of [GreengageDB/greengage_sync#626](https://github.com/GreengageDB/greengage_sync/pull/626).
`pg_batch.py render` assembles it from a **sections file** you write and parts it generates.

| Part, in order | Source | Content |
|---|---|---|
| Title | generated, printed by `render` (`--title` overrides) | `Sync 15x b1: merge upstream PostgreSQL e1c1c30f635..3b231596ccf (PG15 batch 1, 31 units of change)` |
| `intro` | **sections file** | What the batch is and why the cut is where it is |
| How this PR is organised, merge statistics | generated | The layout, the counts of conflicted files by how they were resolved |
| Units of change table, unlisted upstream commits | generated | One row per unit; the **Review PR** column starts as `—` |
| Review status legend, Review PRs | generated | Rules R1–R8, the review-PR branch recipe |
| `adaptations` | **sections file** | Bugs found, re-grafts reviewers must know, policy decisions |
| `validation` | **sections file** | What was run, what passed, the CI runs |
| `followups` | **sections file**, optional | What is left, and what the next batch should expect |

## Sections file skeleton

Sections start at a `<!-- section: NAME -->` line and run to the next one.

```markdown
<!-- section: intro -->
# Sync <major>x b<N>: merge upstream PostgreSQL `<mbase>..<cut>` (<ordinal> PostgreSQL <major> batch)

This PR merges <which part of upstream> into `next`: **<count> upstream commits**, from
<where it starts> (`<first>`, <date>) up to `<cut>` "<cut subject>" (<date>). <Why the cut is
here: the revert pairs and series it closes, from `pg_batch.py select`.> Batch <N+1> starts
at <the next topic> (`<hash>`).

<!-- section: adaptations -->
## Notable Greengage adaptations and bugs found during bring-up

These are the places where re-grafting Greengage onto the new upstream shape needed real
work. Each is in the UoC named in brackets.

**Real bugs found and fixed (a test reproduced each one before the fix):**
1. **<What a user would see>** [<unit slug>]. <The upstream commit that changed the shape,
   by hash>. <Which Greengage code broke, and why>. <What the fix does>.

**Re-grafts reviewers should know about:**
- **<Topic>** (`<upstream hash>`): <where the Greengage logic lives in the new shape>.

**Policy decisions to confirm:**
- **<Decision>**: <what was chosen, the alternative, and the default it ships>.

<!-- section: validation -->
## Validation

- Build (cassert, ORCA, LLVM, TAP), `unittest-check`, initdb and the demo cluster.
- `installcheck-good` under `optimizer=off` and `optimizer=on`; how every regenerated answer
  file passed the answer-file gate.
- The merge audits from greengage-pg-merge, and what they found.
- CI: run [<id>](https://github.com/GreengageDB/greengage_sync/actions/runs/<id>) — green, or which flake was re-run. Update this line after every run.

<!-- section: followups -->
## Follow-ups (not in this PR)

- <A gap found but not fixed here, with its evidence and whether it already exists on `next`>.
- A later batch should expect <upstream fixes listed by `select` as follow-ups after the cut>.
- <Flaky tests seen in CI, each with why it is not caused by this batch>.
```

## Writing rules, from the #626 review

- Name the unit in brackets after every bug and re-graft, so a reviewer can go from the
  description to the unit commit.
- Lead each bug with the symptom, not the fix: "`ALTER TABLE … SET TABLESPACE` segfaulted
  the coordinator and all segments [relation-get-smgr]", then the upstream commit, the
  mechanism and the fix.
- Say **Pre-existing, not caused by this merge** when the bug exists on `next` (b1: three of
  twelve), and cite the upstream fix and its release when the fix is a backport.
- A policy decision gets its own bullet with the default it ships, even when it keeps the
  current behaviour (b1: `wal_compression` zstd not carried over; `shared_buffers` default
  kept at 4096).
- Keep campaign-internal names out (round numbers, local paths, container names); every
  hash must exist on `greengage_sync` or upstream.
- Keep the whole body under GitHub's 65,536 characters; `render` exits 1 above it.
