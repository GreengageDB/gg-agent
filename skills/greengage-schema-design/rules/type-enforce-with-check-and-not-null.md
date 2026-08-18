---
title: Put the integrity you actually get into NOT NULL and CHECK constraints
impact: MEDIUM
impactDescription: "NOT NULL and CHECK are the only constraints enforced on every distributed write; they also feed partition elimination and keep NULLs out of distribution keys"
tags: [schema, constraints, check, not-null, data-quality]
---

## Put the integrity you actually get into NOT NULL and CHECK constraints

**Impact: MEDIUM**

With `FOREIGN KEY` unenforced (`type-foreign-keys-are-not-enforced`) and
`UNIQUE`/`PRIMARY KEY` restricted to supersets of the distribution key
(`dist-unique-keys-must-contain-distkey`), `NOT NULL` and `CHECK` are what is left — and
they are fully enforced, per row, on every segment, because they need no knowledge of any
other row. Use them deliberately rather than treating them as decoration.

They earn their place three ways:

1. **NULLs in a distribution key all hash to one segment.** `NOT NULL` on the distribution
   key is the cheapest skew insurance there is.
2. **On 6.x, CHECK constraints are what partition elimination is built on.** Classic
   partitioning creates a `CHECK` per partition there
   (`"sales_fact_1_prt_5_check" CHECK (sale_date >= ... AND sale_date < ...)` in `\d`).
   7.x stores the bound in `pg_class.relpartbound` instead, so a partition no longer
   carries a user-visible `CHECK` — but an explicit `CHECK` on the same column still costs
   nothing and documents the intent on both lines.
3. **Errors surface at load time**, on the segment, instead of as wrong numbers in a
   report three weeks later.

`CHECK` sees only the row it is validating, so it may not reference other tables or system
columns — `ERROR: system column "gp_segment_id" reference in check constraint is invalid`.
Subqueries are not allowed, exactly as in PostgreSQL.

**Incorrect (nullable key, no domain checks, integrity delegated to an ignored FK):**

```sql
-- Bad: NULL customer_ids pile onto one segment, negative totals go unnoticed,
--      and the REFERENCES clause enforces nothing
CREATE TABLE orders (
    order_id     bigint,
    customer_id  bigint REFERENCES customers(customer_id),
    order_status text,
    total        numeric(12,2)
)
DISTRIBUTED BY (customer_id);
```

**Correct (every enforceable guarantee actually declared):**

```sql
-- Good
CREATE TABLE orders (
    order_id     bigint        NOT NULL,
    customer_id  bigint        NOT NULL,
    order_status text          NOT NULL,
    ordered_at   timestamptz   NOT NULL,
    total        numeric(12,2) NOT NULL,
    CONSTRAINT orders_total_nonneg CHECK (total >= 0),
    CONSTRAINT orders_status_known
        CHECK (order_status IN ('new','paid','shipped','cancelled'))
)
DISTRIBUTED BY (customer_id);
```

Adding a constraint to a loaded table validates it by scanning every segment, so on a
large table use the two-step form and validate in a quieter window:

```sql
ALTER TABLE orders ADD CONSTRAINT orders_total_nonneg CHECK (total >= 0) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT orders_total_nonneg;
```

Reference: [Overview of the ALTER TABLE SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/alter_table.html)
