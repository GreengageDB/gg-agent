# Rule sections

Each section id is the filename prefix of its rules. Load `<prefix>-<name>.md` to get one
rule; the priority table in `../SKILL.md` maps sections to counts.

| Prefix | Title | Impact | Rules |
|---|---|---|---|
| `dist-` | Distribution | CRITICAL | 11 |
| `store-` | Storage | CRITICAL/HIGH | 9 |
| `part-` | Partitioning | HIGH | 7 |
| `type-` | Types, constraints and indexes | MEDIUM/HIGH | 5 |

---

## `dist-` — Distribution

**Impact: CRITICAL**

The distribution key decides which segment every row lands on, and therefore how much of
the cluster does the work and how much data has to move across the interconnect to answer
a join. A key with three distinct values leaves all but three segments idle no matter how
many hosts you bought. Two tables joined on a column that is the distribution key of
neither pay a `Redistribute Motion` or `Broadcast Motion` on every single query. Both
mistakes are invisible in `\d`, cost nothing at `CREATE TABLE` time, and are only fixable
by rewriting and redistributing the whole table (`ALTER TABLE ... SET DISTRIBUTED BY`
moves every row across the network). The distribution key also constrains what unique
constraints the table can carry at all: `src/backend/cdb/cdbcat.c`
`index_check_policy_compatible()` on 7.x (`checkPolicyForUniqueIndex()` on 6.x) rejects
any `UNIQUE`/`PRIMARY KEY`/`EXCLUDE` whose column set is not a superset of the
distribution key. Get this right before anything else.

## `store-` — Storage

**Impact: CRITICAL/HIGH**

Heap, append-optimized row and append-optimized column are three different storage engines
with different write paths, different visibility machinery and an order-of-magnitude
difference in bytes read for a wide-table aggregate. A column-oriented table reads only
the columns the query names; a heap table reads whole rows and keeps the MVCC bookkeeping
that an analytical table never uses. Compression only exists on append-optimized tables,
and `rle_type` only on column-oriented ones. On 6.x the choice is permanent — there is no
`ALTER` that changes it, so you recreate and migrate. On 7.x storage became a PostgreSQL
table access method (`heap`, `ao_row`, `ao_column` in `src/include/catalog/pg_am.dat`) and
`ALTER TABLE ... SET ACCESS METHOD` rewrites the table, which is still a full rewrite of
every segment. Either way this is a decision you make once, at design time.

## `part-` — Partitioning

**Impact: HIGH**

Partitioning is orthogonal to distribution and beginners conflate them: distribution
spreads rows *across segments*, partitioning splits the table *within each segment*. Every
partition of a partitioned table carries the same distribution policy, so partitioning
never fixes skew and never removes a motion. What it buys is partition elimination (the
planner skips partitions whose constraint contradicts the predicate) and O(1) data
lifecycle — `DROP PARTITION` and `EXCHANGE PARTITION` instead of `DELETE` and `INSERT`.
What it costs is catalog rows, locks, planning time and per-partition statistics: the
documentation warns that "excessive partitioning can negatively impact system operations
such as vacuuming, segment recovery, cluster expansion, disk usage checks". 7.x carries
both the classic `PARTITION BY RANGE ... SUBPARTITION TEMPLATE` grammar and PostgreSQL
declarative partitioning; 6.x has only the classic one, and its `pg_partitions` view does
not exist on 7.x.

## `type-` — Types, constraints and indexes

**Impact: MEDIUM/HIGH**

Column types decide the width of every row on every segment and the hash opfamily that
decides co-location, so they are a distribution decision in disguise. Constraints behave
differently from PostgreSQL in one way that silently corrupts data models: `FOREIGN KEY`
is accepted, stored, and **never enforced** — `src/backend/commands/tablecmds.c` raises
`WARNING: referential integrity (FOREIGN KEY) constraints are not supported in Greengage
Database, will not be enforced` and returns. `CHECK` and `NOT NULL` are enforced and are
what you actually have. Indexes are the last decision, not the first: a scan-heavy
analytical query over an append-optimized table is usually faster with a sequential scan
across all segments than with an index, and on append-optimized tables the first index
forces creation of a block directory that costs space and write throughput.
