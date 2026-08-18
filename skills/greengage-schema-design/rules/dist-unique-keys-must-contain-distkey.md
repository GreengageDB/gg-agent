---
title: Make every UNIQUE and PRIMARY KEY a superset of the distribution key
impact: CRITICAL
impactDescription: "A constraint that does not contain the whole distribution key is rejected outright; discovering this after the table is loaded means a full rewrite"
tags: [schema, distribution, constraints, primary-key, unique]
---

## Make every UNIQUE and PRIMARY KEY a superset of the distribution key

**Impact: CRITICAL**

Uniqueness is enforced locally, inside each segment, by an ordinary index. That is only
correct if every row that could collide is guaranteed to live on the same segment — which
is true exactly when the constraint's columns include all of the distribution key columns.
`src/backend/cdb/cdbcat.c` `index_check_policy_compatible()` enforces the rule on 7.x and
states it in the comment: "The set of columns being indexed needs to be a superset of the
distribution policy." (6.x: `checkPolicyForUniqueIndex()` in the same file.)

The exact errors, all from `errdetails_index_policy()` in the same file (7.x wording):

| Situation | Message |
|---|---|
| `PRIMARY KEY` missing a distribution column | `PRIMARY KEY definition must contain all columns in the table's distribution key` |
| `UNIQUE` constraint missing one | `UNIQUE constraint must contain all columns in the table's distribution key` |
| `CREATE UNIQUE INDEX` missing one | `UNIQUE index must contain all columns in the table's distribution key` |
| Column present but wrong opclass | `DETAIL: Operator class <a> of distribution key column "x" is not compatible with operator class <b> used in the constraint.` |
| Changing the policy away from an existing constraint (7.x) | `distribution policy is not compatible with the table's PRIMARY KEY` / `... with UNIQUE constraint "c"` / `... with UNIQUE index "i"` |

**6.x differs in the function and the wording.** The check lives in
`checkPolicyForUniqueIndex()`, is reached only from `DefineIndex()` (so 6.x does not
re-check it on `ALTER TABLE ... SET DISTRIBUTED BY`), and it raises one NOTICE per missing
column — `PRIMARY KEY index must contain all columns in the table's distribution key.` —
followed by the ERROR
`PRIMARY KEY must contain all columns in the distribution key of relation "orders"`
(`UNIQUE index` in place of `PRIMARY KEY` for a unique constraint). The rule is identical;
only the strings you grep for change.

The corollary bites in the other direction too: when you write `PRIMARY KEY` but no
`DISTRIBUTED BY`, the parser derives the distribution key *from the constraint*
(`src/backend/parser/parse_utilcmd.c`). With two constraints that share no column you get
`UNIQUE or PRIMARY KEY definitions are incompatible with each other`,
`HINT: When there are multiple PRIMARY KEY / UNIQUE constraints, they must have at least
one column in common.`

**Incorrect (natural key does not include the distribution column):**

```sql
-- Bad: distributed by order_id, unique on (customer_id, external_ref)
CREATE TABLE orders (
    order_id     bigint NOT NULL,
    customer_id  bigint NOT NULL,
    external_ref text   NOT NULL,
    total        numeric(12,2),
    UNIQUE (customer_id, external_ref)
)
DISTRIBUTED BY (order_id);
-- ERROR:  UNIQUE constraint must contain all columns in the table's distribution key
-- DETAIL:  Distribution key column "order_id" is not included in the constraint.
```

**Correct (distribute on a column the constraint already contains):**

```sql
-- Good: customer_id is in the unique key, so uniqueness is enforceable per segment
--       and orders co-locates with customers at the same time
CREATE TABLE orders (
    order_id     bigint NOT NULL,
    customer_id  bigint NOT NULL,
    external_ref text   NOT NULL,
    total        numeric(12,2),
    UNIQUE (customer_id, external_ref)
)
DISTRIBUTED BY (customer_id);
```

If neither works, the escape hatch is `DISTRIBUTED REPLICATED`, where every constraint is
allowed — but only for a table small enough to live on every segment. There is no way to
enforce a cluster-wide unique constraint on a large hash-distributed table whose key you
cannot include.

Reference: [Overview of the CREATE TABLE SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_table.html)
