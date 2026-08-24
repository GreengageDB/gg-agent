---
name: greengage-pg-merge
description: Merge an upstream PostgreSQL major version into Greengage and bring the fork back up - pinned one-major-per-step targets on greengage_sync, semantic conflict resolution against reference branches, typing the AU/DU/UU inventory, cluster and batch-sweep resolution, the compile - unittest - initdb - regress - isolation2 - CI phase ladder, per-area verifiers beyond conflict markers, merge-artifact garbage and clean-merge traps. Use when starting or continuing a PG major-version bump, when `git diff --diff-filter=U` lists hundreds of files, or when a post-merge failure looks like a dropped re-graft.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "8.x campaign line in greengage_sync (7.x/6.x are merge targets, not merge sources)"
---

# Merging a PostgreSQL major version into Greengage

## This work does not happen in `GreengageDB/greengage`

Every other skill here is written for the shipping lines — **7.x** (PostgreSQL 12.22) and
**6.x** (PostgreSQL 9.4.26). A major-version bump is a different tree. It lives in
[`GreengageDB/greengage_sync`](https://github.com/GreengageDB/greengage_sync), whose `8.x`
line is already past both, and the campaign branches are the merge history:

| Branch (`greengage_sync`) | `PG_PACKAGE_VERSION` | What it is |
|---|---|---|
| `8.x`, `next`, `sync-14x-b*` | `14alpha0` | The settled PG14-based line; the closest thing to "current Greengage" for a re-graft |
| `claude-merge-4` | `16beta2` | PG16 bump, finished |
| `claude-merge-5` | `17beta2` | PG17 bump |
| `claude-merge-6` | `18beta1` | PG18 bump |
| `claude-merge-7` | `18.4` | PG18.4 minor bump on top |

Read the base version off `configure.ac` rather than a branch name — it sits in the
`AC_INIT` block at the top of the file, and every value in the table above came from there:

```
dnl The PACKAGE_VERSION from upstream PostgreSQL is maintained in the
dnl PG_PACKAGE_VERSION variable, when merging make sure to update this
dnl variable with the merge conflict from the AC_INIT() statement.
AC_INIT([Greengage Database], [8.0.0-alpha.0], ...)
[PG_PACKAGE_VERSION=18.4]
```

That comment is a merge instruction: `AC_INIT` conflicts on every bump, and resolving it
means keeping Greengage's product version in `AC_INIT` while moving upstream's into
`PG_PACKAGE_VERSION`. Note the filename too — the campaign line has **`configure.ac`**,
7.x and 6.x still have **`configure.in`** (upstream renamed it in PG14; `REL_13_STABLE` is
the last branch with the old name). A command copied from another skill that names
`configure.in` will not find the file here.

## One major version per step

Never jump two majors in one merge. A direct jump stacks several upstream rewrites on top
of each Greengage re-graft with **no buildable checkpoint in between**, so the first thing
you can compile is also the first thing that could have told you which of a hundred
resolutions was wrong. The campaign so far went 14 → 15 → 16 → 17 → 18, each step on its
own branch, worktree and build container
([greengage-build](../greengage-build/SKILL.md)); continue that way.

Pin the upstream target to a commit, not a moving tag — the merge-base of upstream `master`
and the `REL_x_0` tag is the conventional choice, because it excludes post-branch
development that belongs to the *next* major:

```bash
git remote add pg https://github.com/postgres/postgres.git
git fetch pg master --tags
git merge --no-commit --no-ff <target-sha>
git diff --name-only --diff-filter=U > /tmp/conflicts.txt   # the inventory
```

Calibrate before promising anything. A single-major step has measured at roughly
**2400 commits / 3900 upstream files / 600–800 conflicted files**, and the merge itself is
the smaller half: the bring-up that follows produced several hundred further fix commits.

**Do not commit the merge until every conflict is resolved and the build plus core regress
are green.** The merge state survives on disk, staged resolutions survive in the index, and
a single mis-resolved file is recoverable with `git checkout -m -- <file>`. `git merge
--abort` throws all of it away — reach for it only deliberately.

## Never resolve by taking ours or theirs

The rule the whole campaign rests on: **adopt the upstream API shape first, then re-graft
the Greengage logic into that new shape.** Ours-wholesale orphans the upstream rewrite the
rest of the file now depends on; theirs-wholesale silently deletes MPP behaviour, and
nothing fails until a regression test days later. What the Greengage side *means* —
dispatch, motion, locus, AO tables, distributed transactions — is
[greengage-internals](../greengage-internals/SKILL.md); this is when to apply it.

The two sides of a conflicted file are addressable, so read them rather than guessing:

```bash
git show :2:<path>   # ours   - Greengage before the merge
git show :3:<path>   # theirs - the upstream target
```

When the merge dropped a re-graft you need back, diff against a **reference branch**:

| Reference | What it gives you |
|---|---|
| `greengage_sync` `8.x` | The settled PG14-based Greengage state — the default reference |
| `greengage` `7.x` | Last shipped Greengage major (PostgreSQL 12.22), when 8.x itself is suspect |
| The previous `claude-merge-N` | How the *last* bump resolved this same file |
| `postgres/postgres` at the previous target | Pure upstream — what was Greengage's in the first place |

`greengage` `6.x` is PostgreSQL 9.4.26, far too old to re-graft from; use it only to date a
Greengage feature. And a previous branch's resolution can itself be wrong: verify before
transplanting one.

**Merges are resolved in two-way conflict style, not diff3.** A hunk where ours equals the
merge base auto-resolves to theirs, so upstream's new scaffolding is often sitting in the
*clean* region around the conflict you are looking at. Take-HEAD then orphans it. Read the
surrounding merged code first — if it already uses the new type or idiom, resolve the
conflict to match. That agreement is the tell that "adopt theirs" is right here.

**"Keep both sides" is unsafe at a function boundary.** Where two different functions share
a `/*` opener or a trailing `}` across the conflict, concatenating both sides loses a
delimiter and produces a syntactically valid but semantically spliced function. Same for
the interleaved case, a Greengage function and an upstream function tangled across two
hunks: extract each complete function from `:2:` and `:3:` and write them out one after the
other. Keeping both is only safe for genuinely additive lines — `case` labels, enum
members, `#include`s.

The one place wholesale-ours is correct: a heavily forked, self-contained Greengage
subsystem where every upstream change is unwanted. Take `:2:` entirely and record why,
rather than building a hybrid nobody can reason about.

## Type the inventory before resolving any of it

`git status --porcelain` classifies the conflicts, and the classes need completely
different work:

| Code | Meaning | Treatment |
|---|---|---|
| `AU` | Added by us | Greengage-only files, usually tests — bulk keep, after confirming upstream really has no file of that name |
| `DU` / `UD` | Deleted one side | Translations (`*.po`) and removed docs — bulk `git rm` |
| `AA` | Added by both | Same path, unrelated content; read both |
| `UU` | Modified by both | The real semantic work |

Then order the `UU` set by structure, **not alphabetically**:

1. **Resolve in clusters.** A header and its `.c` family must be resolved together or the
   signatures and enums disagree: the node layer, catalog headers, xlog and recovery,
   pgstat, partition pruning, memory contexts.
2. **Never hand-merge a generated file.** Resolve `configure.ac` and regenerate `configure`
   with autoconf 2.69; resolve `gram.y`, never `gram.c`.
3. **Big files get their own session.** Anything with roughly six or more hunks —
   `tablecmds.c`, `gram.y`, `planner.c`, `xlog.c`, `guc.c`, `pg_dump.c`,
   `nodeModifyTable.c`, `copy.c` — is individual work. Batching them is how tangled
   functions get created.
4. **The one-to-five-hunk tail can be swept** with a repeatable recipe, provided every file
   gets a per-file verification (markers zero, brace-balance delta against `:3:` zero) and
   an explicit **uncertainty note**. Those notes are the highest-value artefact of the
   entire resolution stage: nearly every real bug found later during regress is a re-graft
   a sweep quietly reduced to pure upstream, and the notes are how you find it in an hour
   instead of a week.
5. **Defer `expected/*.out` and `sql/*` to the regress phase.** They do not block the
   build, and resolving them before you know what the code does is guesswork.

Mechanics — the plumbing, the sweep recipe and the per-file verification — are in
[reference/conflict-recipes.md](reference/conflict-recipes.md).

## Conflict markers gone is not the same as resolved

```bash
rg "^(<<<<<<<|=======|>>>>>>>)" .    # necessary, nowhere near sufficient
```

Each area has a validator that catches what a marker scan cannot. Run the ones your
resolution touched **before** you try to build:

| Area | Verifier | What it catches that markers do not |
|---|---|---|
| `gram.y` | `bison -Wcounterexamples gram.y` (runs standalone) | Duplicate `%token` or precedence declarations, duplicate productions as reduce/reduce conflicts, Greengage nonterminals a new upstream feature orphaned |
| Node layer (PG16+) | `src/backend/nodes/gen_node_support.pl` must exit 0 | Node annotations that no longer match the struct |
| Catalogs | `perl src/include/catalog/duplicate_oids`, then a real initdb | OID collisions with upstream's new ranges; take replacements from `src/include/catalog/unused_oids` |
| Changed signatures | Multi-line-aware caller sweep across the whole tree | Clean-merged callers still passing the old arity — no marker was ever shown |
| WAL record layout | Read `ParseCommitRecord` / `ParseAbortRecord` first, then the write path | A serialization order that no longer matches its parser |
| Any resolved file | Brace balance against `:3:` | A hunk whose structure diverged — a spliced function |

## Each bring-up phase catches a class the previous one cannot

Run them in this order. Skipping ahead does not save time; it moves the failure somewhere
it is much harder to read.

1. **Compile and link.** The compiler enumerates every caller of every changed signature —
   that is why wide caller sweeps are deliberately deferred to here rather than done by
   hand during resolution. Link errors are the valuable ones: an undefined symbol whose
   declaration and callers survived means the merge dropped a *definition*.
2. **Mock unit tests** — `make -s unittest-check`, run **serially**; `-j` races on shared
   mock objects and produces failures that are not real. Every new upstream GUC must appear
   in exactly one of `src/include/utils/sync_guc_name.h` or
   `src/include/utils/unsync_guc_name.h` (new upstream GUCs go in `unsync`) or the GUC
   coverage test fails. New parameters on a mocked function need matching `expect_*` calls.
   CI stops at the first failure, so always run the whole suite locally.
3. **initdb and a demo cluster.** Catalog and BKI regressions fire only when initdb
   actually builds `template1` — neither the compiler nor the mocks can see them. Then
   bring up a cluster ([greengage-cluster-ops](../greengage-cluster-ops/SKILL.md)); a
   coordinator that starts and a cluster that dispatches are two different milestones.
4. **The regress matrix, both optimizers.** Run `optimizer=off` first — planner failures
   are readable — then `optimizer=on`. **GPORCA's translator must be re-grafted for every
   new plan-node field, or it silently produces wrong results rather than an error**, and
   because GPORCA falls back to the planner silently a green run may never have exercised
   it. Then `greengage_schedule`, isolation2, contrib and `src/bin`. Every new suite
   surfaces another layer of dropped re-grafts; budget for that rather than treating it as
   a surprise. See [greengage-testing](../greengage-testing/SKILL.md) and
   [greengage-answer-files](../greengage-answer-files/SKILL.md).
5. **CI.** The job matrix runs configurations you do not have locally — assert builds,
   resource groups, JIT, multiple operating systems — and all regress jobs share one
   `expected/` tree. [greengage-ci](../greengage-ci/SKILL.md).

## The re-graft that vanishes without a conflict

The most expensive class in every campaign so far, and the one worth a proactive audit:
**upstream relocates an authority — a table, a list, a generated file — and Greengage's
entries in the old location simply cease to exist.** Git reports no conflict, because from
its point of view the old file was replaced wholesale.

| Bump | Relocation | What silently vanished |
|---|---|---|
| PG16 | GUC table moved `guc.c` → `guc_tables.c` | Greengage's overridden `boot_val`s reverted to upstream defaults. Cost: a recursive-CTE query that hung for 13 minutes, diagnosed as an interconnect deadlock before the real cause surfaced |
| PG17 | Wait events → generated `src/backend/utils/activity/wait_event_names.txt` | Greengage's custom `WAIT_EVENT_*` members — 160 in the old header, 3 upstream. Re-added entries must be in strict alphabetical order or the generator hard-errors |
| PG17 | LWLocks → `src/include/storage/lwlocklist.h` (`lwlocknames.txt` deleted) | 14 custom locks. They must be registered in `wait_event_names.txt` in the same order — the generator now dies on a mismatch, so this build-breaks until finished |
| PG17 | Syscache → `MAKE_SYSCACHE()` in catalog headers (`cacheinfo[]` deleted) | Greengage's hand-written syscaches. The macro takes the *index name*, not the `*IndexId` macro |
| PG17 | `gram.y` precedence block relocated | Greengage's kept `%nonassoc` entries. Only `bison -Wcounterexamples` proves the parse tables still work |

So: **whenever a merge moves or regenerates a table, list or registry, diff the old file's
Greengage-specific entries against the new one, entry by entry, before moving on.** The
generalisation is worth more than any of the individual rows — the next major will relocate
something else.

Two smaller relatives of the same class, both real:

- **A dead `#ifdef` sweep.** Upstream removes a `pg_config.h.in` macro; every Greengage
  `#ifdef` on it becomes silently dead code that still compiles. After the merge, grep the
  whole tree — `gpcontrib/` included — for each removed macro.
- **A backport the target predates.** If the pinned target is older than an upstream fix
  Greengage had already backported, git takes upstream wholesale and drops the backport
  without a conflict.

Per-version evidence, and the rest of the recurring classes, are in
[reference/version-traps.md](reference/version-traps.md).

## What not to do

- **Do not commit a merge with a red build**, and do not commit one whose conflicts were
  resolved but never verified. The merge commit is what makes bisecting possible later; a
  broken one destroys that for the whole campaign.
- **Do not regenerate an answer file to make the merge look finished.** A diff where a
  committed result became an `ERROR` is a dropped re-graft, not drift — that is the one
  absolute gate, and [greengage-answer-files](../greengage-answer-files/SKILL.md) owns it.
  A merge that "passes" because its expected files were rewritten to match the breakage is
  worse than a merge that fails.
- **Do not hand-edit `configure`, `gram.c`, or any other generated file.** Resolve the
  source and regenerate.
- **Do not treat a clean auto-merge as evidence.** Files with no markers at all are a
  recognised failure class: old-arity callers in Greengage-only code paths upstream never
  touched, and functions whose definition disappeared in a file split while the header
  `extern` survived.
- **Do not resolve `.out` files early**, and do not resolve them from the upstream side by
  reflex — Greengage's expected output legitimately differs wherever MPP changes the plan.

See also: [greengage-internals](../greengage-internals/SKILL.md),
[greengage-build](../greengage-build/SKILL.md),
[greengage-testing](../greengage-testing/SKILL.md),
[greengage-answer-files](../greengage-answer-files/SKILL.md),
[greengage-ci](../greengage-ci/SKILL.md),
[greengage-debug](../greengage-debug/SKILL.md),
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md)
