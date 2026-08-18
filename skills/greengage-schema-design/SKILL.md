---
name: greengage-schema-design
description: Designs Greengage tables for MPP - distribution key choice, join co-location, DISTRIBUTED REPLICATED and RANDOMLY, heap vs append-optimized row/column storage, compresstype and column ENCODING, classic and declarative partitioning, unique-key rules, unenforced foreign keys. Use when writing or reviewing CREATE TABLE DDL, porting a PostgreSQL schema, chasing skew, or hitting `UNIQUE constraint must contain all columns in the table's distribution key` or `PRIMARY KEY and DISTRIBUTED RANDOMLY are incompatible`.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Designing tables for Greengage

A rule library. `rules/` holds 32 individually loadable rules; this file is the router.
Cite a rule by its id (the filename without `.md`) and load only that file.

## `CREATE TABLE` is four decisions, not one

PostgreSQL asks you for columns and types. Greengage asks for four things, and three of
them are effectively irreversible on a loaded table:

| Decision | Clause | Reversible? |
|---|---|---|
| Distribution | `DISTRIBUTED BY (...)` / `RANDOMLY` / `REPLICATED` | Only by rewriting and reshipping every row |
| Storage | `USING ao_column` (7.x) or `WITH (appendoptimized=..., orientation=...)` | 7.x: full rewrite. **6.x: not at all** |
| Partitioning | `PARTITION BY RANGE/LIST (...)` | Add/drop partitions cheaply; changing the key means rebuilding |
| Indexes | `CREATE INDEX` | Freely, and usually you should not have them |

Only the fourth is cheap to change. Everything else in this skill follows from that.

## Design in this order

Getting the order wrong is how people end up rewriting terabytes. Each step constrains the
next; do not skip ahead.

1. **Distribution first.** Pick the key from the join graph, not from the column list. It
   is the only decision that changes how much of the cluster does the work, and it
   constrains which unique constraints the table can ever carry
   (`dist-unique-keys-must-contain-distkey`). Write the clause explicitly, always
   (`dist-always-write-explicit-clause`).
2. **Storage second.** Heap, AO row or AO column, plus compression. This depends on the
   read/write shape of the workload, not on the key. On 6.x it cannot be changed later at
   all (`store-changing-storage-is-a-rewrite`).
3. **Partitioning third.** Only after distribution is settled, because partitioning does
   not affect it and must not reuse its key (`part-never-reuse-the-distribution-key`).
   Partition on what the predicates filter and what retention drops.
4. **Indexes last, and sparingly.** Add one only after `EXPLAIN ANALYZE` shows a selective
   lookup losing to a scan (`type-index-only-for-selective-lookups`).
5. **Then load a representative sample and measure.** Per-segment row counts, not
   intentions (`dist-measure-skew-after-load`). Fixing the key now costs a reload; fixing
   it in six months costs a maintenance window.

## Priority

| Priority | Category | Impact | Prefix | Count |
|---|---|---|---|---|
| 1 | Distribution | CRITICAL | `dist-` | 11 |
| 2 | Storage | CRITICAL/HIGH | `store-` | 9 |
| 3 | Partitioning | HIGH | `part-` | 7 |
| 4 | Types, constraints and indexes | MEDIUM/HIGH | `type-` | 5 |

Section rationale is in [rules/_sections.md](rules/_sections.md); the skeleton for a new
rule is [rules/_template.md](rules/_template.md).

## Rules

### `dist-` — Distribution (CRITICAL)

| Rule id | Impact | Summary |
|---|---|---|
| `dist-always-write-explicit-clause` | CRITICAL | With no clause, the key is derived from inheritance, `LIKE`, constraints, a GUC, or the first hashable column — usually the worst one |
| `dist-high-cardinality-key` | CRITICAL | Distinct-value count caps parallelism; NULLs all hash to one segment |
| `dist-colocate-join-keys` | CRITICAL | Same key on both sides of a join means no motion; `cdbpathlocus_equal()` compares keys positionally |
| `dist-unique-keys-must-contain-distkey` | CRITICAL | Every `UNIQUE`/`PRIMARY KEY`/`EXCLUDE` must be a superset of the distribution key |
| `dist-never-date-or-timestamp-key` | HIGH | Time-shaped keys put each day's load on one segment; time belongs in the partition key |
| `dist-match-hash-opfamily` | HIGH | `text` vs `char(n)`, `int` vs `numeric`, or `gp_use_legacy_hashops` silently break co-location |
| `dist-replicated-for-small-dimensions` | HIGH | `DISTRIBUTED REPLICATED` removes the broadcast and lifts constraint limits, at N copies |
| `dist-changing-key-rewrites-table` | HIGH | `SET DISTRIBUTED BY` rewrites and reships everything; re-stating the same key is a no-op |
| `dist-measure-skew-after-load` | HIGH | Count by `gp_segment_id`; `gp_toolkit.gp_skew_coefficients`; >10% skew means reconsider |
| `dist-random-is-a-last-resort` | MEDIUM-HIGH | Forbids every unique constraint and forces a motion on every join |
| `dist-never-update-distribution-key` | MEDIUM-HIGH | Updating the key produces a `Split` node — delete plus cross-segment insert per row |

### `store-` — Storage (CRITICAL/HIGH)

| Rule id | Impact | Summary |
|---|---|---|
| `store-choose-orientation-by-workload` | CRITICAL | heap for mutable, `ao_row` for whole-row scans, `ao_column` for wide tables read a few columns at a time |
| `store-never-ao-for-row-level-dml` | HIGH | AO `DELETE` only flips a visimap bit; no update/delete triggers, no `CLUSTER`, no unique keys on 6.x |
| `store-compress-append-optimized-tables` | HIGH | `zstd` 1-19, `zlib` 1-9, `rle_type` column-only; `quicklz` is gone on 7.x |
| `store-changing-storage-is-a-rewrite` | HIGH | 7.x `SET ACCESS METHOD` rewrites the table; 6.x refuses outright |
| `store-column-level-encoding` | MEDIUM-HIGH | Per-column `ENCODING` and `DEFAULT COLUMN ENCODING` on AOCO only |
| `store-write-storage-clause-explicitly` | MEDIUM-HIGH | Storage silently inherits from session GUCs; the 6.x and 7.x spellings differ |
| `store-vacuum-after-ao-dml` | MEDIUM-HIGH | `gp_appendonly_compaction_threshold` defaults to 10%; below it, space is never reclaimed |
| `store-set-defaults-once-not-per-table` | MEDIUM | `gp_default_storage_options` plus (7.x) `default_table_access_method`, set at database scope |
| `store-tune-blocksize-last` | LOW-MEDIUM | Default 32 KB; 8 KB-2 MB in 8 KB multiples; fix everything else first |

### `part-` — Partitioning (HIGH)

| Rule id | Impact | Summary |
|---|---|---|
| `part-is-not-distribution` | HIGH | Every partition inherits the parent's distribution policy; partitioning never fixes skew or removes a motion |
| `part-key-must-match-query-predicates` | HIGH | Elimination needs a predicate on the partition key; a function wrapper kills it |
| `part-do-not-over-partition` | HIGH | leaves x segments x columns; excessive partitioning slows vacuum, recovery and expansion |
| `part-never-reuse-the-distribution-key` | MEDIUM-HIGH | Same column for both makes each partition live on one segment |
| `part-load-and-age-with-exchange-and-drop` | MEDIUM-HIGH | `EXCHANGE PARTITION` to load, `DROP PARTITION` to age; never `DELETE` |
| `part-choose-classic-or-declarative-deliberately` | MEDIUM | 6.x has classic only and `pg_partitions`; 7.x has both and no `pg_partitions` |
| `part-analyze-the-root` | MEDIUM | Plans are costed from root statistics; analyzing only the loaded leaf leaves them stale |

### `type-` — Types, constraints and indexes (MEDIUM/HIGH)

| Rule id | Impact | Summary |
|---|---|---|
| `type-foreign-keys-are-not-enforced` | HIGH | `FOREIGN KEY` warns and is ignored — on both 6.x and 7.x |
| `type-index-only-for-selective-lookups` | MEDIUM-HIGH | Indexes cost load throughput and force an AO block directory; scans are already parallel |
| `type-choose-narrow-types` | MEDIUM | Row width multiplies by segment count on every scan, motion and spill |
| `type-enforce-with-check-and-not-null` | MEDIUM | The only always-enforced constraints; `NOT NULL` on the key is cheap skew insurance |
| `type-prefer-text-over-char` | LOW-MEDIUM | `char(n)` blank-pads and hashes in a different opfamily than `text`/`varchar` |

## How to apply this skill

**Reviewing existing DDL.** Walk the four categories in priority order and stop at the
first failure — a wrong distribution key makes every downstream observation moot.

```sql
-- 1. What is the distribution, really?
SELECT c.relname, p.policytype, p.numsegments,
       pg_catalog.pg_get_table_distributedby(c.oid) AS distributed_by
FROM   gp_distribution_policy p
JOIN   pg_class     c ON c.oid = p.localoid
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname NOT IN ('pg_catalog','information_schema','gp_toolkit')
ORDER  BY 1;

-- 2. What is the storage, really?  (7.x)
SELECT c.relname, am.amname, c.reloptions
FROM   pg_class c LEFT JOIN pg_am am ON am.oid = c.relam
WHERE  c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace
ORDER  BY 1;
--    on 6.x:
--    SELECT relid::regclass, columnstore, compresstype, compresslevel, blocksize
--    FROM pg_appendonly;

-- 3. Is the data actually spread?
SELECT gp_segment_id, count(*) FROM <table> GROUP BY 1 ORDER BY 2 DESC;
```

**Writing new DDL.** Answer these before typing `CREATE TABLE`:

1. What does this table join to, on which column? → distribution key.
2. Is it small enough to replicate? → `DISTRIBUTED REPLICATED`.
3. Is it loaded in bulk and read analytically? → `ao_column` + `zstd`.
4. Is there a retention or reload grain? → partition on that column.
5. Which unique constraints must hold? → check they contain the distribution key.

**Diagnosing a slow query that turns out to be a schema problem.** `Redistribute Motion`
or `Broadcast Motion` under a join means the tables are not co-located
(`dist-colocate-join-keys`, `dist-match-hash-opfamily`). One segment far slower than the
rest in `EXPLAIN ANALYZE` means skew (`dist-measure-skew-after-load`). A scan reading far
more than the query needs means the wrong storage or a missing partition key
(`store-choose-orientation-by-workload`, `part-key-must-match-query-predicates`).

## Traps that do not fit one rule

**The 6.x / 7.x deltas that change what you can write.** Write for 7.x; these are the
places a 6.x cluster diverges.

| Topic | 6.x (PostgreSQL 9.4.26) | 7.x (PostgreSQL 12.22) |
|---|---|---|
| Storage type | `appendonly`/`orientation` reloptions | table access methods `heap`, `ao_row`, `ao_column`; `USING` wins over `WITH` |
| Change storage | impossible — `SET (appendonly=...)` gives `cannot SET reloption "appendonly"`, `SET WITH (appendonly=...)` gives `option "appendonly" not supported` (6.x `SET WITH` takes only `REORGANIZE`) | `ALTER TABLE ... SET ACCESS METHOD` (full rewrite) |
| `gp_default_storage_options` | accepts `appendonly`, `orientation`, `blocksize`, `compresstype`, `compresslevel`, `checksum` | accepts only `blocksize`, `compresstype`, `compresslevel`, `checksum` |
| `default_table_access_method` | does not exist | `heap` / `ao_row` / `ao_column` |
| Unique index on AO | `append-only tables do not support unique indexes` | supported, not `CONCURRENTLY`, needs AO relation version GP7 |
| `quicklz` | valid compresstype | removed; `unknown compresstype "quicklz"` unless `gp_quicklz_fallback=on` maps it to zstd |
| Partitioning | classic grammar only | classic **plus** PostgreSQL declarative |
| `pg_partitions` view | exists | **does not exist** — use `pg_partition_tree()` / `pg_inherits` |
| `pg_appendonly` columns | carries `blocksize`, `compresstype`, `compresslevel`, `checksum`, `columnstore` | only `relid`, `segrelid`, `blkdirrelid`, `visimaprelid`, `version`; options live in `pg_class.reloptions` and `pg_attribute_encoding` |
| Per-column encoding after creation | not possible | `ALTER TABLE ... ALTER COLUMN ... SET ENCODING (...)` |

**The messages worth recognising on sight.** All verified in
`GreengageDB/greengage`; the wording below is the `refs/remotes/origin/7.x` one, and
rows that differ on `refs/remotes/origin/6.x` say so.

| Message | What it means | Rule |
|---|---|---|
| `NOTICE: Table doesn't have 'DISTRIBUTED BY' clause -- Using column named 'x' ...` | The key was guessed from the first hashable column | `dist-always-write-explicit-clause` |
| `NOTICE: table has parent, setting distribution columns to match parent table` | `INHERITS` decided the key | `dist-always-write-explicit-clause` |
| `NOTICE: table doesn't have 'DISTRIBUTED BY' clause, defaulting to distribution columns from LIKE table` | `LIKE` decided the key | `dist-always-write-explicit-clause` |
| `ERROR: UNIQUE constraint must contain all columns in the table's distribution key` | Constraint is not a superset of the key (6.x wording: `UNIQUE index must contain all columns in the distribution key of relation "x"`) | `dist-unique-keys-must-contain-distkey` |
| `ERROR: PRIMARY KEY and DISTRIBUTED RANDOMLY are incompatible` | No uniqueness on random tables | `dist-random-is-a-last-resort` |
| `ERROR: UNIQUE or PRIMARY KEY definitions are incompatible with each other` | Two constraints share no column, so no key can be derived | `dist-unique-keys-must-contain-distkey` |
| `WARNING: distribution policy of relation "x" already set to (a)` | The `ALTER` did nothing; add `SET WITH (REORGANIZE=TRUE)` | `dist-changing-key-rewrites-table` |
| `WARNING: referential integrity (FOREIGN KEY) constraints are not supported in Greengage Database, will not be enforced` | The FK exists in the catalog and is never checked | `type-foreign-keys-are-not-enforced` |
| `ERROR: invalid option "orientation" for base relation` | `orientation` without `appendoptimized=true` | `store-write-storage-clause-explicitly` |
| `ERROR: rle_type cannot be used with Append Only relations row orientation` | `rle_type` is column-only | `store-compress-append-optimized-tables` |
| `ERROR: ENCODING clause only supported with column oriented tables` | Per-column encoding on heap or AO row | `store-column-level-encoding` |
| `ERROR: altering reloptions for append only tables is not permitted` | **6.x only**: any `ALTER TABLE ... SET (reloption)` on a table that is already append-optimized | `store-changing-storage-is-a-rewrite` |
| `ERROR: cannot SET reloption "appendonly"` | **6.x only**: `SET (appendonly\|orientation\|blocksize\|compresstype\|compresslevel\|checksum)` — storage cannot be altered on 6.x | `store-changing-storage-is-a-rewrite` |
| `LOG: Append-only compaction skipped on relation x, segment file num n` | Dirty ratio is below `gp_appendonly_compaction_threshold` | `store-vacuum-after-ao-dml` |

**Noise to ignore.** `WARNING: Columns with geometric or user-defined data types are not
eligible as Greengage distribution key columns (type 'x')` comes from
`createForeignTablePartitionedPolicy()` — it is about a **foreign/external** table falling
back to a random policy, not about your `CREATE TABLE`. Costs from GPORCA (`optimizer=on`)
and the PostgreSQL planner (`optimizer=off`) are **not comparable**, so never tune a schema
by comparing plan costs across optimizers; compare `EXPLAIN ANALYZE` wall time and
per-segment row counts instead.

**Things that are not schema problems.** `mode='n'` on content -1 in
`gp_segment_configuration` is normal for the coordinator. A `Gather Motion` at the top of
every plan is normal — that is how results reach the client. One `Broadcast Motion` of a
tiny replicated-candidate dimension may be cheaper than replicating it; measure before
changing the schema.

See also: [greengage-query-performance](../greengage-query-performance/SKILL.md) for
reading motions and slices in `EXPLAIN`,
[greengage-data-loading](../greengage-data-loading/SKILL.md) for loading into partitioned
and append-optimized tables, [greengage-overview](../greengage-overview/SKILL.md) for the
MPP model these rules follow from,
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md) for rebalancing after
`gpexpand`, and [greengage-internals](../greengage-internals/SKILL.md) for the catalogs
(`gp_distribution_policy`, `pg_appendonly`, `pg_attribute_encoding`) behind these clauses.
