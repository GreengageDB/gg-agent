---
title: Use text or varchar for strings, never char(n)
impact: LOW-MEDIUM
impactDescription: "char(n) blank-pads every value to n bytes and hashes in a different opfamily from text/varchar, so it wastes storage and silently prevents co-location"
tags: [schema, types, strings, opclass, co-location]
---

## Use text or varchar for strings, never char(n)

**Impact: LOW-MEDIUM**

`text` and `varchar(n)` are the same storage internally and, critically, share a hash
operator family: `src/include/catalog/pg_opclass.dat` maps both `text_ops` and
`varchar_ops` to `hash/text_ops`. A `text` distribution key therefore co-locates with a
`varchar` one, and you can widen or drop a length limit without disturbing distribution.

`char(n)` (`bpchar`) is different in two ways that both cost you:

- It **blank-pads** every value to `n` characters. A `char(50)` column holding
  three-character country codes stores 50 bytes per row on every segment, and the padding
  is real bytes fed to the compressor.
- It hashes under `hash/bpchar_ops`, a **different opfamily** from `hash/text_ops`. A
  `char(3)` distribution key does not co-locate with a `text` or `varchar` one, so a join
  between them pays a `Redistribute Motion` even though both columns hold the same
  three-character codes. `cdbpathlocus_equal()` compares `dk_opfamily` and rejects the
  pair outright.

`varchar(n)` is fine when the length limit is a real business rule you want enforced;
`text` is fine everywhere else. Changing between them later is an `ALTER TABLE ... ALTER
COLUMN ... TYPE`, which rewrites the table.

**Incorrect (char(n) key joined to a text key):**

```sql
-- Bad: dim uses char(3), fact uses text -> different hash opfamilies -> motion
CREATE TABLE dim_country (
    country_code char(3) NOT NULL,
    country_name text
) DISTRIBUTED BY (country_code);

CREATE TABLE sales_fact (
    sale_id      bigint NOT NULL,
    country_code text   NOT NULL,
    amount       numeric(12,2)
) DISTRIBUTED BY (country_code);
```

**Correct (text on both sides — same opfamily, no padding):**

```sql
-- Good: joins locally, and stores three bytes instead of a padded fixed width
CREATE TABLE dim_country (
    country_code text NOT NULL,
    country_name text,
    CONSTRAINT dim_country_code_len CHECK (char_length(country_code) = 3)
) DISTRIBUTED REPLICATED;

CREATE TABLE sales_fact (
    sale_id      bigint NOT NULL,
    country_code text   NOT NULL,
    amount       numeric(12,2)
) DISTRIBUTED BY (sale_id);
```

Note that the `CHECK` constraint above **is** enforced, unlike a `FOREIGN KEY` — see
`type-foreign-keys-are-not-enforced`.

Find `char(n)` columns already in the schema:

```sql
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) AS coltype
FROM   pg_attribute a
JOIN   pg_class     c ON c.oid = a.attrelid
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  a.atttypid = 'bpchar'::regtype
  AND  a.attnum > 0 AND NOT a.attisdropped
  AND  c.relkind = 'r'
  AND  n.nspname NOT IN ('pg_catalog','information_schema','gp_toolkit')
ORDER  BY 1, 2;
```

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
