---
title: Never run the gp_toolkit skew views casually on a production cluster
impact: MEDIUM-HIGH
impactDescription: "gp_skew_coefficients and gp_skew_idle_fractions loop over every user table and sequentially scan each one; on a large warehouse that is a full-cluster table scan of the entire database"
tags: [query-performance, skew, gp-toolkit, safety]
---

## Never run the `gp_toolkit` skew views casually on a production cluster

**Impact: MEDIUM-HIGH**

`gp_toolkit.gp_skew_coefficients` and `gp_toolkit.gp_skew_idle_fractions` look like
catalog views. They are not. Both are wrappers over PL/pgSQL functions
(`__gp_skew_coefficients()` and `__gp_skew_idle_fractions()`) that loop over
`__gp_user_data_tables_readable` and call `gp_skew_coefficient(oid)` /
`gp_skew_idle_fraction(oid)` once per table, each of which reads
`gp_skew_details(oid)`. For a heap table `gp_skew_details` builds and executes

```sql
SELECT gp_segment_id, COUNT(*) AS cnt FROM <schema>.<table> GROUP BY 1
```

— a full sequential scan. `SELECT * FROM gp_toolkit.gp_skew_coefficients;` therefore
scans every user table in the database, one after another, in a single transaction. On a
warehouse that is hours of I/O and a long-held snapshot.

There is one fast path and it is narrow: if the table is append-optimized **and** the
current user is a superuser, `gp_skew_details` uses `pg_catalog.get_ao_distribution()`,
which reads `pg_aoseg` metadata instead of scanning. A non-superuser gets the scanning
branch even on AO tables.

Column names are non-obvious and prefixed per view:

| View | Columns | Meaning of the metric |
|---|---|---|
| `gp_skew_coefficients` | `skcoid, skcnamespace, skcrelname, skccoeff` | `stddev(rows)/avg(rows) * 100` — coefficient of variation as a percentage; lower is better |
| `gp_skew_idle_fractions` | `sifoid, sifnamespace, sifrelname, siffraction` | fraction of the cluster idle during a scan; `0.02` means 2% skew |

**Incorrect (a whole-database scan disguised as a monitoring query):**

```sql
-- Bad: scans every user table in the database, in one transaction.
SELECT * FROM gp_toolkit.gp_skew_coefficients ORDER BY skccoeff DESC;
```

**Correct (call the per-table function on the tables you are actually investigating):**

```sql
-- Good: same metric, one table, bounded cost. Both functions take an oid.
SELECT skcoid::regclass AS table_name, round(skccoeff, 1) AS skew_pct
FROM   gp_toolkit.gp_skew_coefficient('events'::regclass::oid);

SELECT sifoid::regclass AS table_name, round(siffraction, 4) AS idle_fraction
FROM   gp_toolkit.gp_skew_idle_fraction('events'::regclass::oid);
```

Note the singular function names (`gp_skew_coefficient`, `gp_skew_idle_fraction`) versus
the plural view names. If you must sweep many tables, restrict the loop yourself and run
it in a maintenance window:

```sql
SELECT c.oid::regclass AS table_name, round((gp_toolkit.gp_skew_coefficient(c.oid)).skccoeff, 1) AS skew_pct
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname = 'analytics' AND c.relkind = 'r'
ORDER  BY 2 DESC;
```

On 7.x `gp_toolkit` is an extension — if the schema is missing, `CREATE EXTENSION
gp_toolkit;` installs it. On 6.x it is loaded into every database by `initdb` and is
always present.

Reference: [Greengage DB system view: gp_skew_coefficients](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_skew_coefficients.html)
