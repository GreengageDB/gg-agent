---
title: Never rely on a FOREIGN KEY — Greengage accepts it and does not enforce it
impact: HIGH
impactDescription: "A FOREIGN KEY produces a WARNING and is then ignored entirely; orphan rows accumulate silently in a model whose DDL says they cannot exist"
tags: [schema, constraints, foreign-key, data-quality]
---

## Never rely on a FOREIGN KEY — Greengage accepts it and does not enforce it

**Impact: HIGH**

`FOREIGN KEY` is parsed, stored in `pg_constraint`, shown by `\d`, and **never checked**.
`validateForeignKeyConstraint()` in `src/backend/commands/tablecmds.c` warns and returns
before it validates a single row; `createForeignKeyActionTriggers()` warns as well. Both
call sites are guarded by `Gp_role == GP_ROLE_DISPATCH || GP_ROLE_UTILITY`, so the message
lands once, on the coordinator, on 6.x and on 7.x:

```
WARNING:  referential integrity (FOREIGN KEY) constraints are not supported in Greengage
Database, will not be enforced
```

`src/test/regress/expected/foreign_key_gp.out` is the proof: it inserts an `id` into a
heap, an `ao_row` and an `ao_column` table that references `fk_ref`, with no matching row
in `fk_ref`, and every insert succeeds with no error. The mechanism is structural:
enforcing a reference would mean checking a row on one segment against a table distributed
over all of them, on every write.

The practical consequences:

- Migrating a PostgreSQL schema with `pg_dump` gives you a wall of these warnings and a
  model whose integrity guarantees silently evaporated.
- Tools that read `pg_constraint` to infer joins still see the constraints, so the ERD
  looks right while the data is not.
- Do not design around `ON DELETE CASCADE` / `ON UPDATE CASCADE` either: they are part of
  a constraint the server tells you it will not enforce, so the referential state they are
  supposed to maintain is not guaranteed. Delete children explicitly.

Use what **is** enforced: `NOT NULL`, `CHECK`, and `UNIQUE`/`PRIMARY KEY` subject to
`dist-unique-keys-must-contain-distkey`. Enforce referential integrity in the load process
and audit for violations on a schedule.

**Incorrect (relying on the database to reject orphans):**

```sql
-- Bad: the constraint is created, warned about, and ignored
CREATE TABLE customers (customer_id bigint NOT NULL PRIMARY KEY, name text)
  DISTRIBUTED BY (customer_id);

CREATE TABLE orders (
    order_id    bigint NOT NULL,
    customer_id bigint NOT NULL REFERENCES customers(customer_id),
    total       numeric(12,2)
) DISTRIBUTED BY (customer_id);
-- WARNING:  referential integrity (FOREIGN KEY) constraints are not supported in
--           Greengage Database, will not be enforced

INSERT INTO orders VALUES (1, 999999, 10.00);   -- succeeds; customer 999999 does not exist
```

**Correct (enforceable constraints in the schema, referential checks in the pipeline):**

```sql
-- Good: NOT NULL and CHECK are enforced; the reference is validated at load time
CREATE TABLE orders (
    order_id    bigint NOT NULL,
    customer_id bigint NOT NULL,
    total       numeric(12,2) NOT NULL,
    CONSTRAINT orders_total_nonneg CHECK (total >= 0)
) DISTRIBUTED BY (customer_id);

-- Load step: reject orphans instead of inserting them
INSERT INTO orders (order_id, customer_id, total)
SELECT s.order_id, s.customer_id, s.total
FROM   stg_orders s
WHERE  EXISTS (SELECT 1 FROM customers c WHERE c.customer_id = s.customer_id);

-- Audit step: this must return zero rows
SELECT count(*) AS orphan_orders
FROM   orders o
WHERE  NOT EXISTS (SELECT 1 FROM customers c WHERE c.customer_id = o.customer_id);
```

If you keep the `REFERENCES` clause for documentation value, say so in a comment so nobody
downstream mistakes it for a guarantee.

Reference: [Overview of the CREATE TABLE SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_table.html)
