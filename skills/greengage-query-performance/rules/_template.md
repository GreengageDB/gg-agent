---
title: <imperative statement of the rule, e.g. "Read the Optimizer line on every plan">
impact: CRITICAL | HIGH | MEDIUM-HIGH | MEDIUM | LOW-MEDIUM | LOW
impactDescription: "<quantified or mechanistic consequence, one sentence>"
tags: [query-performance, <section>, <topic>]
---

## <same text as title>

**Impact: <same level as frontmatter>**

<Two to five sentences on the mechanism: what Greengage actually does at execution time,
why the PostgreSQL-shaped instinct is wrong here, and what it costs in motions, segments
or wall-clock. Name the source of truth — an exact plan line, a catalog or gp_toolkit
view, a GUC with its real default, an error string, or a file under src/. Note the 6.x
delta inline if the command, GUC or printed label differs.>

**Incorrect (<what is wrong, in four or five words>):**

```sql
-- Bad: <why this specific statement is wrong on a cluster>
SELECT ...;
```

**Correct (<what is right, in four or five words>):**

```sql
-- Good: <why this specific statement is right>
SELECT ...;
```

<Optional but preferred: the verification query or plan line the reader should look for
afterwards, or a table of exact error strings and their causes.>

Reference: [<exact page title>](<verified https://greengagedb.org/en/docs-gg/... URL>)
