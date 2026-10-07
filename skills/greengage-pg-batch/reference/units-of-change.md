# Units of change: topics.json and the b1 example

Lookup material for [greengage-pg-batch](../SKILL.md), step 5.

## topics.json

```json
{"topics": [
   {"slug": "memoize-rename",
    "title": "Result Cache renamed to Memoize",
    "summary": "Upstream renamed the Result Cache plan node to Memoize (node, GUC enable_memoize, EXPLAIN output, tests). Greengage-only references follow: plan walkers, cdbplan/cdbllize, targeted dispatch, memquota, unsynced GUC list, ORCA answer files.",
    "commits": ["83f4fcc6550"],
    "paths": ["src/backend/executor/nodeMemoize.c", "re:^src/test/regress/(sql|expected)/(memoize|resultcache)",
              "src/backend/cdb/cdbplan.c", "src/include/utils/unsync_guc_name.h"],
    "aliases": [],
    "notes": []}],
 "module_buckets": [["re:^src/backend/regex/", "regex", "Regular expressions"],
                    ["re:.", "misc", "Other changes"]]}
```

| Field | Meaning |
|---|---|
| `slug` | Unit id: commit trailers (`UoC: <slug>`), review branch names, the PR table |
| `title` | One line; becomes `UoC N/M: <title>` |
| `summary` | The PR table cell: what upstream changed, then what Greengage had to do about it |
| `commits` | Upstream commits that define the unit. A commit listed by several units is tagged `(main change: UoC <slug>)` in the others |
| `paths` | Files of the unit: exact paths, globs, or `re:<regex>`. The first topic that matches wins |
| `aliases` | Other `UoC:` trailer values that mean this unit (b1 renamed `alter-table-set-am` and `relkind-errmsg` into `alter-table`) |
| `notes` | Bullets for the unit commit message |
| `module_buckets` | `[pattern, slug, title]` fallbacks, tried in order after the topics |

## How assign places a file

First match wins:

1. A topic's `paths`.
2. The `UoC:` trailer of the bring-up commits that touched it, if no upstream commit did.
3. A resolver note: a `### <path>` heading followed by a `UoC: <slug>` line (`--notes DIR`).
4. The topic whose `commits` changed the most lines of the file.
5. The `UoC:` trailer, for a file upstream also touched.
6. The first matching `module_buckets` entry; otherwise `misc`.

`assign` lists every upstream commit under each unit whose files it touches. Commits that touch
only files Greengage removed (docs, translations) are reported as *unlisted* and go into a
collapsed list under the PR table.

## Grouping heuristics that worked in b1

- Start from the inventory: each day-1 commit (R1) and each R2 file usually anchors a unit
  of its own — an upstream API change plus every Greengage re-graft it forced.
- Give the re-grafts of a rename to the rename's unit, even where they live in Greengage-only
  files (`cdbplan.c`, `memquota.c`, the unsynced GUC list for Memoize).
- Then cut the rest by subsystem, at a size one reviewer can own in a sitting.
- Keep upstream-only areas (regex, ECPG, contrib, docs, encoding tables) as their own units;
  they become empty commits and need no review PR.
- Put regenerated answer files with the unit whose behaviour change they record when that is
  one unit; otherwise collect them in a tests unit (b1: `regress-tests`, 105 files).
- Write every b1 topic with explicit `paths`: all 953 files were placed by a path match, so no
  file's unit depended on the fallback order.

## b1: 31 units for 468 commits

`sync-15x-b1`, in tier order. *Files* is the unit's share of `next..sync-15x-b1-raw`; *GG files*
is how many of them the unit commit changes after the merge (0 means an empty commit).

| # | Slug | Title | Files | Upstream commits | GG files | Tier (rules) |
|---|---|---|---|---|---|---|
| 1 | `memoize-rename` | Result Cache renamed to Memoize | 15 | 2 | 11 | must review (R6, R7) |
| 2 | `catalog-pin-oid-range` | Pinned objects: OID range test instead of pg_depend PIN entries | 11 | 11 | 9 | must review (R1, R3, R4, R5, R6, R7, R8) |
| 3 | `catalog-declare-index` | Catalog headers: index OID macro in DECLARE_INDEX | 91 | 19 | 24 | must review (R3, R4, R7) |
| 4 | `alter-table` | ALTER TABLE: relkind error messages, SET ACCESS METHOD, toast rewrite | 5 | 14 | 8 | must review (R1, R3, R5, R6, R7) |
| 5 | `conflicting-options-errors` | Option parsing: errorConflictingDefElem() | 11 | 7 | 1 | must review (R1, R7) |
| 6 | `planner` | Planner: parallel DISTINCT, NestPath/SeqScan structs, pruning, costing | 24 | 22 | 12 | must review (R1, R3, R6, R7) |
| 7 | `executor` | Executor: aggregate cleanup, hash memory limit, Datum sort | 24 | 18 | 7 | must review (R1, R3, R4, R6, R7) |
| 8 | `node-support` | Node support functions, Greengage serializers, ORCA translator | 13 | 15 | 7 | must review (R1, R6, R7) |
| 9 | `buffile-fileset` | BufFile: sharedfileset split into fileset | 10 | 5 | 5 | must review (R7) |
| 10 | `relation-get-smgr` | RelationOpenSmgr() replaced by RelationGetSmgr() | 9 | 13 | 4 | must review (R3, R4) |
| 11 | `process-startup` | Process startup/shutdown rework, shared memory size | 24 | 37 | 9 | must review (R4, R6, R7) |
| 12 | `pgstat` | Statistics collector changes | 5 | 10 | 1 | must review (R1, R4, R6) |
| 13 | `analyze-partitioned-revert` | Revert of autoanalyze for partitioned tables | 2 | 8 | 2 | must review (R1, R4) |
| 14 | `wal-xact` | WAL and transactions: FPW compression, recovery refactoring | 17 | 35 | 4 | must review (R1, R4, R5, R6) |
| 15 | `logical-replication-2pc` | Logical replication: two-phase commit, streaming | 60 | 42 | 2 | must review (R3, R4) |
| 16 | `pg-dump` | pg_dump: public schema ownership, partition triggers | 10 | 15 | 5 | must review (R1, R3, R4, R5, R6) |
| 17 | `client-tools` | Client utilities | 78 | 71 | 8 | must review (R3, R4) |
| 18 | `tap-postgresnode` | TAP framework: PostgresNode->new() | 45 | 16 | 7 | must review (R4) |
| 19 | `sql-functions-types` | SQL functions, data types, backend utilities | 38 | 38 | 3 | must review (R1) |
| 20 | `storage-locking` | Storage, locking and invalidation | 24 | 27 | 5 | must review (R4, R7) |
| 21 | `commands-parser` | Commands, parser and rewriter | 45 | 40 | 3 | must review (R1, R5) |
| 22 | `access-methods` | Index and table access methods | 22 | 14 | 2 | must review (R3, R4, R5, R7) |
| 23 | `regress-tests` | Regression and isolation test changes | 105 | 62 | 45 | must review (R8) |
| 24 | `build-system` | Build system and portability | 30 | 47 | 3 | must review (R1) |
| 25 | `libpq-auth` | libpq and authentication | 36 | 20 | 2 | no review |
| 26 | `regex` | Regular expressions | 15 | 13 | 0 | no review |
| 27 | `plpgsql` | PL/pgSQL | 11 | 4 | 1 | no review |
| 28 | `ecpg` | ECPG | 17 | 6 | 0 | no review |
| 29 | `contrib` | contrib modules | 44 | 26 | 0 | no review |
| 30 | `docs` | Documentation | 26 | 29 | 0 | no review |
| 31 | `encoding-unicode` | Encoding conversions and Unicode tables | 86 | 10 | 0 | merge automatically |
