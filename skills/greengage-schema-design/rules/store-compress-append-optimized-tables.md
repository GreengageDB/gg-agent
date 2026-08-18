---
title: Compress append-optimized tables, and pick the compresstype the orientation allows
impact: HIGH
impactDescription: "Compression trades CPU for I/O on a workload that is almost always I/O bound; the wrong compresstype for the orientation is a hard error, and quicklz no longer exists on 7.x"
tags: [schema, storage, compression, zstd, rle]
---

## Compress append-optimized tables, and pick the compresstype the orientation allows

**Impact: HIGH**

An analytical scan reads far more bytes than it computes on, so trading CPU for fewer
bytes off disk and off the interconnect is usually a straight win. Compression is
available **only** on append-optimized tables: `compresstype` on a heap table gives
`ERROR: unrecognized parameter "compresstype"` on 7.x (it is not a heap reloption at all)
and `ERROR: invalid option "compresstype" for base relation` on 6.x.

Valid values, hard-coded in `compresstype_is_valid()`
(`src/backend/catalog/pg_compression.c`):

| `compresstype` | 6.x | 7.x | `compresslevel` range | Orientation |
|---|---|---|---|---|
| `zstd` | yes (`--with-zstd`) | yes (`--with-zstd`) | 1–19 | row or column |
| `zlib` | yes | yes | 1–9 | row or column |
| `rle_type` | yes | yes | 1–6 in a zstd build, else 1–4 (`RLE_MAX_LEVEL`, `src/include/storage/gp_compress.h`) | **column only** |
| `none` | yes | yes | 0 | either |
| `quicklz` | yes | **removed** | — | — |

Rules the parser enforces, with the exact messages:

- `rle_type` on an AO **row** table: `ERROR: rle_type cannot be used with Append Only relations row orientation`.
- A level outside the range, e.g. `compresslevel=12` with zlib:
  `ERROR: compresslevel=12 is out of range for zlib (should be in the range 1 to 9)`.
- `compresslevel=0` with a real compresstype: `ERROR: compresstype "zstd" can't be used with compresslevel 0`.
- `compresstype=quicklz` on 7.x: `ERROR: unknown compresstype "quicklz"`, unless a
  superuser has set `gp_quicklz_fallback=on` (default `off`), in which case it is silently
  rewritten to `zstd`.

Defaults when you say nothing: `compresstype` `none`, `compresslevel` `0`
(`AO_DEFAULT_COMPRESSTYPE` / `AO_DEFAULT_COMPRESSLEVEL`,
`src/include/access/reloptions.h`). Naming only `compresslevel` implicitly selects
**`zlib`** (`AO_DEFAULT_USABLE_COMPRESSTYPE`); naming only `compresstype` sets level 1
(`AO_DEFAULT_USABLE_COMPRESSLEVEL`).

**Incorrect (rle_type on a row-oriented table, and a level zlib cannot take):**

```sql
-- Bad: both clauses are rejected
CREATE TABLE sales_fact (sale_id bigint, amount numeric(12,2))
WITH (appendoptimized=true, orientation=row, compresstype=rle_type, compresslevel=1)
DISTRIBUTED BY (sale_id);
-- ERROR:  rle_type cannot be used with Append Only relations row orientation

CREATE TABLE sales_fact (sale_id bigint, amount numeric(12,2))
WITH (appendoptimized=true, orientation=column, compresstype=zlib, compresslevel=12)
DISTRIBUTED BY (sale_id);
-- ERROR:  compresslevel=12 is out of range for zlib (should be in the range 1 to 9)
```

**Correct (zstd as the general-purpose default; rle_type only where it applies):**

```sql
-- Good: zstd level 5 is a reasonable ratio/CPU balance for a mixed fact table
CREATE TABLE sales_fact (
    sale_id   bigint NOT NULL,
    sale_date date   NOT NULL,
    store_id  int,
    amount    numeric(12,2)
)
WITH (appendoptimized=true, orientation=column, compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (sale_id);

-- Good: rle_type on a column-oriented table with long runs of repeated values
CREATE TABLE sensor_state (
    reading_id bigint NOT NULL,
    device_id  int    NOT NULL,
    state      text   ENCODING (compresstype=rle_type, compresslevel=1),
    reading_ts timestamptz
)
WITH (appendoptimized=true, orientation=column, compresstype=zstd, compresslevel=3)
DISTRIBUTED BY (reading_id);
```

Measure rather than guess — 7.x ships per-column ratios:

```sql
-- 7.x only (gpcontrib/gp_toolkit); the view itself is restricted to ao_column tables
SELECT relname, attname, size, size_uncompressed, compression_ratio
FROM   gp_toolkit.gp_column_size_summary
WHERE  relname = 'sales_fact'
ORDER  BY size DESC;

-- both lines: whole-table ratio. Raises
-- ERROR: 'sales_fact' is not an append-only relation on heap; on 7.x it returns -1
-- for the root of a partitioned table, so call it on the leaf partitions.
SELECT pg_catalog.get_ao_compression_ratio('sales_fact'::regclass);
```

Reference: [Data compression in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_compression.html)
