---
title: Pick classic or declarative partitioning deliberately, and know which catalog goes with it
impact: MEDIUM
impactDescription: "6.x has only the classic grammar and the pg_partitions view; 7.x has both grammars and no pg_partitions, so introspection scripts written for one line break silently on the other"
tags: [schema, partitioning, syntax, catalog, migration]
---

## Pick classic or declarative partitioning deliberately, and know which catalog goes with it

**Impact: MEDIUM**

Greengage 6.x supports exactly one partitioning grammar: the Greenplum-inherited "classic"
`PARTITION BY RANGE/LIST (...) [SUBPARTITION BY ... SUBPARTITION TEMPLATE (...)] ( ... )`
attached to `CREATE TABLE`. Greengage 7.x keeps that grammar **and** adds PostgreSQL 12
declarative partitioning (`PARTITION BY RANGE (col)` on the parent, `CREATE TABLE ...
PARTITION OF ... FOR VALUES ...` per child). The documentation for 7 says it "retain[s]
most of the partitioning syntax from earlier versions — known as the classic syntax. It
also introduces support for a declarative partitioning syntax derived from PostgreSQL."

Choose by what you need:

| | Classic | Declarative (7.x only) |
|---|---|---|
| Available on | 6.x and 7.x | 7.x |
| Bulk creation | `EVERY (INTERVAL '1 month')` generates partitions for you | one `CREATE TABLE ... PARTITION OF` per partition |
| Maintenance verbs | `ADD/DROP/SPLIT/EXCHANGE PARTITION`, `SET SUBPARTITION TEMPLATE` | `ATTACH`/`DETACH PARTITION` |
| Expressions in the key | rejected — on 7.x with `ERROR: expressions in partition key not supported in legacy GPDB partition syntax` | supported |
| Heterogeneous hierarchy | uniform levels expected | supported |
| Hash partitioning | no | `PARTITION BY HASH (col)` with `FOR VALUES WITH (MODULUS n, REMAINDER r)` |

The introspection trap is separate from the grammar: **`pg_partitions` exists on 6.x and
does not exist on 7.x**. Any script that reads it breaks on upgrade. On 7.x use the
PostgreSQL functions `pg_partition_tree()`, `pg_partition_root()` and
`pg_partition_ancestors()`, or `pg_inherits` directly. Leaf partitions are named
`<parent>_1_prt_<partition_name>` under the classic grammar on both lines.

**Incorrect (6.x introspection carried onto 7.x):**

```sql
-- Bad on 7.x: relation "pg_partitions" does not exist
SELECT partitiontablename, partitionrangestart, partitionrangeend
FROM   pg_partitions WHERE tablename = 'sales_fact';
```

**Correct (7.x introspection, works for classic and declarative alike):**

```sql
-- Good on 7.x
SELECT relid::regclass AS partition, parentrelid::regclass AS parent, level, isleaf
FROM   pg_partition_tree('sales_fact'::regclass)
ORDER  BY level, 1;
```

```sql
-- Good on both lines: walk pg_inherits, which classic partitioning also populates
SELECT c.relname AS partition, p.relname AS parent
FROM   pg_inherits i
JOIN   pg_class c ON c.oid = i.inhrelid
JOIN   pg_class p ON p.oid = i.inhparent
WHERE  p.relname = 'sales_fact'
ORDER  BY 1;
```

Prefer the classic grammar for anything that must run on both lines, and for time-series
tables where `EVERY (INTERVAL ...)` saves you writing a hundred statements. Reach for
declarative only on 7.x, and only when you need an expression key, a non-uniform
hierarchy, or hash partitioning.

Reference: [Partitioning in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/7/table_partitioning_declarative.html)
