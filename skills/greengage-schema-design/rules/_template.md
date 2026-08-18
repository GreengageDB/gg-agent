---
title: <imperative statement of the rule, e.g. "Distribute joined tables on the join key">
impact: CRITICAL | HIGH | MEDIUM-HIGH | MEDIUM | LOW-MEDIUM | LOW
impactDescription: "<quantified or mechanistic consequence, one sentence>"
tags: [schema, <section>, <topic>]
---

## <same text as title>

**Impact: <same level as frontmatter>**

<Two to five sentences on the mechanism: what Greengage actually does, why the
PostgreSQL-shaped instinct is wrong here, and what it costs. Name the source of truth —
a catalog, a GUC, an exact error string, or a file in the source tree. Note the 6.x delta
inline if the command or clause differs.>

**Incorrect (<what is wrong, in four or five words>):**

```sql
-- Bad: <why this specific statement is wrong>
CREATE TABLE ...;
```

**Correct (<what is right, in four or five words>):**

```sql
-- Good: <why this specific statement is right>
CREATE TABLE ...;
```

<Optional: a verification query the reader can run, or a table of exact error strings.>

Reference: [<exact page title>](<verified https://greengagedb.org/... URL>)
