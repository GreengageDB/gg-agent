# Units of change: topics.json and the b1 result

Lookup material for [greengage-pg-batch](../SKILL.md), steps 5 and 6.

## topics.json

```json
{"topics": [
   {"slug": "memoize-rename",
    "title": "Result Cache renamed to Memoize",
    "commits": ["83f4fcc6550"],
    "paths": ["src/backend/executor/nodeMemoize.c", "re:^src/test/regress/(sql|expected)/(memoize|resultcache)",
              "src/backend/cdb/cdbplan.c", "src/include/utils/unsync_guc_name.h"],
    "aliases": []},
   {"slug": "hot-chain-backport",
    "title": "Backport: fix HOT chain corruption during pruning (bug #17255)",
    "commits": [], "paths": []}],
 "module_buckets": [["re:^src/backend/regex/", "regex", "Regular expressions"],
                    ["re:.", "misc", "Other changes"]]}
```

| Field | Meaning |
|---|---|
| `slug` | Unit id: commit trailers (`UoC: <slug>`), split.json entries, `msg/<slug>.txt` |
| `title` | One line; the unit commit becomes `UoC N: <title>` from `msg/<slug>.txt`, which may refine it |
| `commits` | Upstream commits that define the unit. The unit **claims** them for the split; a commit listed by several topics is claimed by all of them unless split.json `primary` pins it |
| `paths` | Files the unit owns in the per-file cut: exact paths, globs, or `re:<regex>`. The first matching topic wins |
| `aliases` | Other `UoC:` trailer values that mean this unit |
| `module_buckets` | `[pattern, slug, title]` fallbacks, tried in order after the topics |

The topic order is the unit order: `assign` sends an operation with several candidate units to
the earliest, and new unit numbers follow it. Put the independent-fix units (no commits; their
operations arrive through split.json `redirect`) last.

## What a unit claims

`uoc_split.py` turns the topics and `uocs.json` into claims: a unit claims the commits its topic
lists, plus every upstream commit that touches its per-file files and that no topic lists (the
commits `pg_batch.py` would list without "main change"). An operation caused by a commit goes
to a unit claiming it. A commit nobody claims leaves its operations with the per-file owner.

## How pg_batch.py assign places a file (the per-file owner)

First match wins:

1. A topic's `paths`.
2. The `UoC:` trailer of the bring-up commits that touched it, if no upstream commit did.
3. A resolver note: a `### <path>` heading followed by a `UoC: <slug>` line (`--notes DIR`).
4. The topic whose `commits` changed the most lines of the file.
5. The `UoC:` trailer, for a file upstream also touched.
6. The first matching `module_buckets` entry; otherwise `misc`.

## Grouping heuristics that worked in b1

- Each day-1 commit and each upstream deletion of a Greengage-modified file anchors a unit of
  its own: an upstream API change plus every Greengage re-graft it forced.
- Give a rename's re-grafts to the rename's unit, even in Greengage-only files (`cdbplan.c`,
  `memquota.c`, the unsynced GUC list for Memoize). The per-operation split does this by
  itself through `tokens2` once the rename's commit is in the topic's `commits`.
- Cut the rest by upstream change, not by subsystem: b1's subsystem units (`planner`,
  `executor`, `wal-xact`, `pg-dump`, `sql-functions-types`, `commands-parser`, `alter-table`)
  were each split into three after review started, because one reviewer could not own
  unrelated changes in one sitting.
- Upstream-only areas (regex, ECPG, contrib, docs, encoding tables) stay topics so their commits
  have a home; they have no Greengage operation and get no branch.
- Answer files: the operations a `testL` cause ties to an upstream test go with that test's
  unit; Greengage regenerations stay in one tests unit (b1: `regress-tests`).

## Splitting a unit whose PR is already open

The first part keeps the unit's number (and so its branch and PR); the other parts take the next
free numbers in `numbers.json`. Write the parts as topics in place of the parent, place the
operations no commit ties to a part with `overrides`, rebuild only the parts' branches
(`branches --only`), and bring the review fixes from the parent's branch into the parts whose
files they touch. Check: merging the parts' branches gives exactly the parent's old branch tree.

## b1: 42 units for 468 commits

`sync-15x-b1`, by number. Units 1–25 are the 31 per-file units of #626 after the re-split
(`access-methods` and five upstream-only units had no operation left); seven of them now hold
the first part of a unit split during review, whose other parts are 29–42. Units 26–28 are the
independent fixes.

| # | Slug | Title | Origin |
|---|---|---|---|
| 1 | `memoize-rename` | Result Cache renamed to Memoize | |
| 2 | `catalog-pin-oid-range` | Pinned objects: OID range test instead of pg_depend PIN entries | |
| 3 | `catalog-declare-index` | Index OID macro argument to DECLARE_INDEX | |
| 4 | `alter-table-set-am` | ALTER TABLE SET ACCESS METHOD | split from `alter-table` |
| 5 | `conflicting-options-errors` | Report "conflicting or redundant options" via errorConflictingDefElem | |
| 6 | `parallel-distinct` | Parallel DISTINCT | split from `planner` |
| 7 | `hash-memory-limit` | Hash memory limit: get_hash_memory_limit() | split from `executor` |
| 8 | `node-support` | Node support: PublicationTable node, COPY_POINTER_FIELD size check | |
| 9 | `buffile-fileset` | BufFile: FileSet split out of SharedFileSet | |
| 10 | `relation-get-smgr` | RelationOpenSmgr() replaced by RelationGetSmgr() | |
| 11 | `process-startup` | Process startup/shutdown rework and shared_memory_size | |
| 12 | `pgstat` | pgstat: bgwriter and checkpointer statistics split | |
| 13 | `analyze-partitioned-revert` | Revert autoanalyze of partitioned tables | |
| 14 | `fpw-compression` | WAL full-page image compression: LZ4, wal_compression enum | split from `wal-xact` |
| 15 | `logical-replication-2pc` | Logical replication: two-phase commit for subscriptions | |
| 16 | `pg-dump-public-schema` | pg_dump: public schema ownership, comment and ACL | split from `pg-dump` |
| 17 | `client-tools` | Client tools: integer option parsing, pg_resetwal -u, pg_ctl commands | |
| 18 | `tap-postgresnode` | TAP: unify PostgresNode new() and get_new_node() | |
| 19 | `record-hashing` | Anonymous record types no longer hashable | split from `sql-functions-types` |
| 20 | `storage-locking` | Locking, visibility horizon and invalidation refactors | |
| 21 | `partition-triggers` | Triggers on partitions: cloned firing state, ALTER TRIGGER RENAME | split from `commands-parser` |
| 22 | `regress-tests` | Regression answer files regenerated for the batch | |
| 23 | `build-system` | Version 15devel and world-bin make targets | |
| 24 | `libpq-auth` | libpq: generic SASL interface and OOM-safe error messages | |
| 25 | `plpgsql` | PL/pgSQL: shorter "returned more than one row" errors | |
| 26 | `policy-heal` | Greengage fix: heal a transiently stale ENTRY distribution policy | independent fix |
| 27 | `hot-chain-backport` | Backport: fix HOT chain corruption during pruning (bug #17255) | independent fix |
| 28 | `windowdef-binary` | Greengage fix: binary node serialization for WindowDef | independent fix |
| 29 | `relkind-errmsg` | Error messages about mismatching relkind | split from `alter-table` |
| 30 | `toast-rewrite` | Toast rewrites in logical decoding | split from `alter-table` |
| 31 | `path-plan-structs` | NestPath contains JoinPath, SeqScan contains Scan | split from `planner` |
| 32 | `planner-misc` | Planner: partition scans, hashed NOT IN, smaller fixes | split from `planner` |
| 33 | `agg-cleanup` | Aggregate code cleanup in the executor | split from `executor` |
| 34 | `datum-sort` | Datum sorts for single-column sorts | split from `executor` |
| 35 | `slot-invalidation` | Old-segment horizon after replication slot invalidation | split from `wal-xact` |
| 36 | `recovery-refactor` | WAL recovery refactoring and fixes | split from `wal-xact` |
| 37 | `pg-dump-typename-cache` | pg_dump: cached type names | split from `pg-dump` |
| 38 | `pg-dump-queries` | pg_dump: disabled triggers on partitions, fewer per-table queries | split from `pg-dump` |
| 39 | `size-pretty` | pg_size_pretty: unit table, petabytes, rounding | split from `sql-functions-types` |
| 40 | `numeric-hex` | numeric_power fixes, hex code back from src/common | split from `sql-functions-types` |
| 41 | `matview-refresh` | REFRESH MATERIALIZED VIEW CONCURRENTLY alias ambiguity | split from `commands-parser` |
| 42 | `extension-rewriter` | Extension membership checks and rewriter fixes | split from `commands-parser` |
