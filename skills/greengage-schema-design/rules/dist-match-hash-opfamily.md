---
title: Co-locate only across columns that share a hash operator family
impact: HIGH
impactDescription: "Mismatched types or legacy hashops silently defeat co-location: the DDL looks identical but every join still pays a Redistribute Motion"
tags: [schema, distribution, types, opclass, motion]
---

## Co-locate only across columns that share a hash operator family

**Impact: HIGH**

Two tables "distributed on the same column" only co-locate if the hash **operator family**
recorded in `gp_distribution_policy.distclass` is the same on both sides.
`cdbpathlocus_equal()` in `src/backend/cdb/cdbpathlocus.c` (7.x line 85, 6.x line 83)
rejects the pair outright:

```c
if (adistkey->dk_opfamily != bdistkey->dk_opfamily)
    return false;
```

Two things break this without any warning.

**Type mismatch.** Hash opclasses map to families that do not all overlap the way btree
comparison does (`src/include/catalog/pg_opclass.dat` on 7.x, `pg_opclass.h` on 6.x):

| Types | Hash opfamily | Co-locate with each other? |
|---|---|---|
| `int2`, `int4`, `int8` | `hash/integer_ops` | yes |
| `text`, `varchar(n)` | `hash/text_ops` | yes |
| `char(n)` / `bpchar` | `hash/bpchar_ops` | **no** — not with `text`/`varchar` |
| `numeric` | `hash/numeric_ops` | **no** — not with the integer types |
| `date` | `hash/date_ops` | **no** — not with `timestamp` |
| `timestamp` vs `timestamptz` | `hash/timestamp_ops` vs `hash/timestamptz_ops` | **no** |

So `orders.customer_id bigint` joined to `customers.customer_id numeric` redistributes on
every query even though both tables name `customer_id` as the distribution key.

**Legacy hashops.** `gp_use_legacy_hashops` (default `false` on both 6.x and 7.x,
`src/backend/utils/misc/guc_gp.c`) makes new tables use the `cdbhash_*_ops` families
instead. A table created in a session that had it on never co-locates with one created
without it — same column, same type, different family.

**Incorrect (same column name, different type):**

```sql
-- Bad: numeric vs bigint -> hash/numeric_ops vs hash/integer_ops -> motion on every join
CREATE TABLE customers (customer_id numeric(18) NOT NULL, name text)
  DISTRIBUTED BY (customer_id);
CREATE TABLE orders    (order_id bigint, customer_id bigint NOT NULL, total numeric(12,2))
  DISTRIBUTED BY (customer_id);
```

**Correct (identical type on both sides of the join):**

```sql
-- Good: both hash under hash/integer_ops, so the join is local
CREATE TABLE customers (customer_id bigint NOT NULL, name text)
  DISTRIBUTED BY (customer_id);
CREATE TABLE orders    (order_id bigint, customer_id bigint NOT NULL, total numeric(12,2))
  DISTRIBUTED BY (customer_id);
```

Audit the actual opclasses in use — anything named `cdbhash_*` is a legacy hashop:

```sql
SELECT c.relname,
       pg_catalog.pg_get_table_distributedby(c.oid) AS distributed_by,
       (SELECT string_agg(opf.opfname, ', ')
        FROM   unnest(string_to_array(p.distclass::text, ' ')::oid[]) AS u(opc)
        JOIN   pg_opclass  op  ON op.oid  = u.opc
        JOIN   pg_opfamily opf ON opf.oid = op.opcfamily) AS hash_opfamilies
FROM   gp_distribution_policy p
JOIN   pg_class     c ON c.oid = p.localoid
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname NOT IN ('pg_catalog','information_schema','gp_toolkit')
  AND  p.distclass::text <> ''
ORDER  BY 1;
```

Reference: [Greengage DB system table: gp_distribution_policy](https://greengagedb.org/en/docs-gg/current/reference/pg_catalog/gp_distribution_policy.html)
