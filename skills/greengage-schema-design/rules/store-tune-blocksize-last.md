---
title: Leave blocksize at the default unless you have measured a reason to change it
impact: LOW-MEDIUM
impactDescription: "blocksize trades sequential-scan throughput against random-fetch latency and memory per open segment file; changing it blindly costs memory for no gain"
tags: [schema, storage, blocksize, tuning]
---

## Leave blocksize at the default unless you have measured a reason to change it

**Impact: LOW-MEDIUM**

`blocksize` is the size in bytes of one append-optimized storage block. The default is
32768 (`DEFAULT_APPENDONLY_BLOCK_SIZE`, `src/include/cdb/cdbappendonlyam.h`) and the legal
range is 8192 to 2097152 (`MIN_APPENDONLY_BLOCK_SIZE` .. `MAX_APPENDONLY_BLOCK_SIZE`, same
header), in multiples of 8192. The documented trade-off: "Smaller block sizes favor faster
random access, while larger block sizes favor faster sequential access."

It is genuinely the last knob to reach for, because:

- A column-oriented table keeps a separate segment file, and therefore a separate block
  buffer, **per column**. Multiplying the block size by 64 on a wide AOCO table multiplies
  the writer's buffer footprint by 64 as well, on every segment.
- Distribution, orientation and compresstype each move the number by an order of
  magnitude more than blocksize does. Fix those first.
- The value is validated at parse time:
  `ERROR: block size must be between 8KB and 2MB and be a multiple of 8KB`,
  `DETAIL: Got block size <n>.`

Change it when scans are demonstrably sequential and wide (large `ao_row` tables read end
to end) or demonstrably point-lookup-shaped (an indexed AO table fetched by key), and only
after you have fixed everything else.

**Incorrect (maximum blocksize on a wide column table, cargo-culted):**

```sql
-- Bad: 2 MB x one file per column x every concurrent writer, for no measured benefit
CREATE TABLE sales_fact (
    sale_id bigint, sale_date date, store_id int, product_id int, amount numeric(12,2)
    -- ... 60 more columns
)
WITH (appendoptimized=true, orientation=column, compresstype=zstd,
      compresslevel=5, blocksize=2097152)
DISTRIBUTED BY (sale_id);
```

**Correct (default blocksize; raise it only on a narrow, sequentially scanned AO row table):**

```sql
-- Good: leave it alone on the wide column table
CREATE TABLE sales_fact (
    sale_id bigint, sale_date date, store_id int, product_id int, amount numeric(12,2)
)
WITH (appendoptimized=true, orientation=column, compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (sale_id);

-- Good: a narrow, append-only, always-full-scanned log can justify larger blocks
CREATE TABLE event_log (
    event_id bigint NOT NULL,
    payload  text
)
WITH (appendoptimized=true, orientation=row, compresstype=zstd,
      compresslevel=3, blocksize=1048576)
DISTRIBUTED BY (event_id);
```

Reference: [Data compression in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_compression.html)
