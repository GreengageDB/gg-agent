---
title: Tune compression per column with ENCODING on column-oriented tables
impact: MEDIUM-HIGH
impactDescription: "One table-wide compresstype forces the same trade-off on a high-entropy id column and a column of repeated status strings; per-column ENCODING lets each pick its best"
tags: [schema, storage, compression, encoding, aoco]
---

## Tune compression per column with ENCODING on column-oriented tables

**Impact: MEDIUM-HIGH**

A column-oriented table stores each column in its own segment file, so each column can
have its own compression settings. That matters because columns are not alike: a
high-entropy surrogate id gets almost nothing from a high `zstd` level except CPU, while a
`state` column that holds a handful of repeated values in long runs is exactly what
`rle_type` exists for — and `rle_type` is only legal on column-oriented storage in the
first place. Per-column settings are stored in `pg_attribute_encoding.attoptions`.

Three forms, all from `doc/src/sgml/ref/create_table.sgml`:

| Form | Meaning |
|---|---|
| `<col> <type> ENCODING (compresstype=..., compresslevel=..., blocksize=...)` | inline, this column only |
| `DEFAULT COLUMN ENCODING (...)` as a table element | applies to every column with no inline `ENCODING` |
| `COLUMN <col> ENCODING (...)` as a table element | same as inline, written separately |

The restrictions, with exact messages:

- `ERROR: ENCODING clause only supported with column oriented tables` — it is meaningless
  on heap and on AO row.
- `ERROR: DEFAULT COLUMN ENCODING clause cannot override values set in WITH clause` — pick
  one place to state the table-wide default.
- `ERROR: column "x" referenced in more than one COLUMN ENCODING clause`.
- Inside a `SUBPARTITION TEMPLATE`:
  `ERROR: partition specific ENCODING clause not supported in SUBPARTITION TEMPLATE`.

On 7.x you can also change it after the fact, and only there:
`ALTER TABLE t ALTER COLUMN c SET ENCODING (compresstype=zlib, compresslevel=5)`. On a
non-AOCO table it fails with
`ERROR: ALTER COLUMN SET ENCODING operation is only applicable to AOCO tables`. 6.x has no
such statement — you recreate the table.

**Incorrect (one compresstype for every column, and ENCODING on a row-oriented table):**

```sql
-- Bad: rle_type is wasted on the high-cardinality id and wrong for the amount
CREATE TABLE sensor_readings (
    reading_id bigint,
    device_id  int,
    state      text,
    amount     numeric(12,2)
)
WITH (appendoptimized=true, orientation=column, compresstype=rle_type, compresslevel=1)
DISTRIBUTED BY (reading_id);

-- Bad: ENCODING on a row-oriented table
CREATE TABLE sensor_readings_row (
    reading_id bigint,
    state      text ENCODING (compresstype=rle_type)
)
WITH (appendoptimized=true, orientation=row)
DISTRIBUTED BY (reading_id);
-- ERROR:  ENCODING clause only supported with column oriented tables
```

**Correct (a table default plus per-column overrides where they pay):**

```sql
-- Good: zstd everywhere by default, rle_type on the low-cardinality column
CREATE TABLE sensor_readings (
    reading_id bigint NOT NULL,
    device_id  int    NOT NULL,
    state      text   ENCODING (compresstype=rle_type, compresslevel=1),
    amount     numeric(12,2),
    DEFAULT COLUMN ENCODING (compresstype=zstd, compresslevel=5)
)
WITH (appendoptimized=true, orientation=column)
DISTRIBUTED BY (reading_id);
```

Inspect what was actually stored:

```sql
SELECT a.attname, e.attoptions
FROM   pg_attribute_encoding e
JOIN   pg_attribute a ON a.attrelid = e.attrelid AND a.attnum = e.attnum
WHERE  e.attrelid = 'sensor_readings'::regclass
ORDER  BY a.attnum;
```

Reference: [pg_attribute_encoding](https://greengagedb.org/en/docs-gg/current/reference/pg_catalog/pg_attribute_encoding.html)
