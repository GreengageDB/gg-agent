---
name: greengage-answer-files
description: Regenerate Greengage regression answer files without burying a real bug - the success-to-ERROR safety gate, the upstream-assertion-still-holds gate and MPP test-input adaptation, reading gpdiff regression.diffs rather than git diff, init_file matchignore and matchsubs masks, atmsort blind spots, base .out vs _optimizer.out selection and their sibling files, and .source-generated tests. Use when pg_regress reports FAILED or failed (ignored), when a test appears in regression.diffs, when a lone rerun dies with relation "tenk1" does not exist, or before cp results/foo.out expected/foo.out.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Regenerating answer files without burying a bug

A Greengage regression test passes when `gpdiff.pl` finds no difference between
`expected/<t>.out` and `results/<t>.out`. Copying the result over the expectation
makes any test pass, including a test that just caught a real defect. This skill is
the set of checks that separate the two, and the masks that let you avoid the copy
entirely.

Most answer-file churn is genuinely cosmetic — MPP plan shapes, per-segment message
suffixes, psql column widths, environment paths. A minority is a bug. The gate below
is what tells them apart; run it before you touch a single `expected/` file.

## The safety gate: a committed result that became an ERROR is never a regen

**Never regenerate an answer file whose gpdiff output shows a result row or a
`(N rows)` count replaced by an added `ERROR:` line.** That is the exact signature
of a query that used to work and no longer does.

Run the gate on the gpdiff-produced `regression.diffs`, never on `git diff` or a
raw `diff` of the two files:

```sh
# every failing suite writes its own file
find . -name regression.diffs

cd src/test/regress
# which tests are in there at all: pg_regress writes one
# "diff <opts> <expected> <results>" header per failing test (pg_regress.c:2010)
grep -n '^diff ' regression.diffs

# the gate
grep -nE '^\+ERROR' regression.diffs
grep -nE '^-\s*\([0-9]+ rows?\)' regression.diffs
```

Then work the checklist. Every rule here is absolute.

| Check | Rule |
|---|---|
| `+ERROR` with a matching `-ERROR` elsewhere in the same hunk | A **move**, not a new failure. Count `-ERROR` and `+ERROR` occurrences per test before concluding anything. |
| `+ERROR` inside a `-- start_ignore` … `-- end_ignore` region | Not a failure. atmsort rewrites the line to `GP_IGNORE:ERROR:  …` (`atmsort.pm:1076`), so `^\+ERROR` cannot match it — if it does, your diff is not a gpdiff. |
| No `+ERROR` anywhere | **Not sufficient.** A changed set of *data rows* with no error at all is equally a bug. Inspect the row set per test; never bulk `cp`. |
| Row set changed but sorted row set identical | Reorder noise. atmsort sorts unordered results, so gpdiff already ignored it; only `git diff` shows it. |
| Test failed under `Out of memory`, `could not fork`, or a segment down | Discard the whole run. Do not regenerate from it. |
| A clean re-run reports `ok    ` and `regression.diffs` is gone | **This is the definitive proof.** pg_regress unlinks `regression.diffs` and `regression.out` when the diff file came out empty (`pg_regress.c:3446`, `:3458`). |

## The gate has a second half: the upstream assertion must still hold

A block that ends in a success can still be a failure. Upstream tests assert through their
output — `(0 rows)` from a query that returns only violations, a `pg_relation_size`
equality, an `EXPLAIN` that must show an index scan or a particular node. When MPP changes
the physical facts the query still "succeeds", the ERROR gate stays quiet, and a
regeneration records the failed assertion as the expectation; the test asserts nothing
from then on. Before regenerating, ask what the block proves, and adapt the **input** so it
still proves it on a cluster. `sql/brin.sql:500-504` is the shipped model — *"GPDB: use
more rows, and a larger statistics sample, to get the same plan"*, then `set statistics
1000` and 200000 rows so the planner keeps choosing the BRIN index the test exists to show.

| The upstream block assumes | Adapt the input with |
|---|---|
| One heap on one page (`pg_relation_size` arithmetic, "tuple larger than fillfactor") | The same distribution-key value for every row, or `DISTRIBUTED REPLICATED`; sizes for the 32 kB block |
| A plan the optimizer must pick on a small table | More rows and a larger statistics target (`brin.sql`), or the `enable_*` / `optimizer_enable_*` GUC that forces the shape under both optimizers |
| A GUC name, option or syntax an upstream rule now rejects, in a Greengage-specific test | Rename or rephrase the input so the Greengage feature stays under test — never record the new `ERROR` |
| A single-backend invariant (an index that must not grow) | Seed every segment first so the baseline is comparable |
| Statement and comment text | Keep it; inherited `.sql` files stay as close to upstream as the adaptation allows |

Never assert on the segment count or cluster layout, and never let a regression test destroy
or recreate a data directory. If the property genuinely cannot hold on MPP, say why in a
comment, and only then record the output.

## `git diff` over-reports by two orders of magnitude — read `regression.diffs`

`gpdiff.pl` runs `atmsort::run()` over **both** files and only then shells out to
`diff` (`gpdiff.pl:136-151`). `atmsort` sorts unordered result rows, strips
per-segment message suffixes, re-emits a costed EXPLAIN as a pruned plan tree, and
applies every mask in `init_file`. A raw `git diff` sees none of that: an
unordered MPP result comes
back in segment order, so a regenerated file shows every row as moved.

Observed magnitude on a bulk post-merge drift: **5326 raw diff lines, 16 real ones**
after gpdiff normalised both sides. Reviewing the raw diff is not conservative, it
is noise that hides the sixteen lines that matter.

Reproduce the comparison that lands in `regression.diffs` by hand
(`pg_regress.c:76-77`, `:2019`; the pass/fail decision runs the same command
without `-U3` at `:1914`):

```sh
cd src/test/regress
./gpdiff.pl -I HINT: -I CONTEXT: -I GP_IGNORE: -U3 \
    --gpd_init init_file \
    expected/<t>.out results/<t>.out
```

There is **no `-w`** outside Windows. Whitespace is significant: an editor that
strips trailing spaces will break answer files whose psql column padding matters.

## Decision order: mask, fix the test, regenerate — in that order

Work down this list and stop at the first rung that applies. Regeneration is the
last resort, not the first move.

| Rung | Applies when | Do |
|---|---|---|
| 1. Mask | The differing text varies with the environment: a path, an address, a hostname, a temp-schema number, an OID, a source-file line number, a timing figure | Add a paired `m//` + `s///` to `src/test/regress/init_file`, or an embedded `-- start_matchsubs` block in `sql/<t>.sql` |
| 2. Fix the test | The output is nondeterministic *by construction*: a `SELECT` with no `ORDER BY` whose rows atmsort cannot sort, a leaked GUC from a previous statement, a `CREATE TABLE AS` with no `DISTRIBUTED BY`, a fault-injection test in a parallel schedule group | Edit `sql/<t>.sql` — add the `ORDER BY`, reset the GUC, pin the distribution, move the test into its own schedule group. Then regenerate both variants. |
| 3. Regenerate | The output changed deterministically and correctly: a new plan shape, new upstream queries, a reworded message you deliberately changed | `cp results/<t>.out expected/<t>.out`, then re-run to `ok` |

Rung 1 is strictly better than rung 3 because a mask fixes the test in **every**
environment at once; a regeneration fixes it in exactly the one it was taken from.

## init_file: matchignore drops a line, matchsubs rewrites it

`src/test/regress/init_file` reaches gpdiff as `--gpd_init` and applies to **every**
regress test and **every** isolation2 suite. The wiring:

- `src/test/regress/GNUmakefile:215` — `REGRESS_OPTS = … --init-file=$(srcdir)/init_file`
- `pg_regress.c:1888-1892` — each `--init-file` becomes ` --gpd_init <file>` on the
  gpdiff command line
- `src/test/isolation2/Makefile` — every target passes `--init-file=…/regress/init_file`
  **plus** its own `init_file_isolation2` / `init_file_resgroup` /
  `init_file_parallel_retrieve_cursor`

Two block types, and they are not interchangeable:

```
-- start_matchignore
# bare patterns. A matching line is DELETED from both result and expected.
m/^ Settings:.*/
-- end_matchignore

-- start_matchsubs
# PAIRED: an m// on one line, the s/// that rewrites it on the next.
# Both sides get the substitution wherever the match hits.
m/\(dbsize\.c\:\d+\)/
s/\(dbsize\.c:\d+\)/\(dbsize\.c:XXX\)/
-- end_matchsubs
```

The pairing is positional, not syntactic: `_build_match_subs` (`atmsort.pm:116`)
walks the block two lines at a time and dies with `bad definition` on an odd count.
Blank lines and `#` comments are stripped first, so never leave a lone `m//`.

**Prefer a substitution to an ignore.** `matchignore` deletes the whole line, which
silently destroys coverage — the reason no answer file on 7.x can assert which
optimizer ran is that `init_file` matchignores `m/^ Optimizer: GPORCA/` and its four
siblings. A `matchsubs` that blanks only the varying token keeps the rest asserted.

Per-test blocks live in the `.sql` as SQL comments with the inner lines also
comment-prefixed. psql echoes them, so **the block appears in the answer file too
and must be present in every variant of it** — base, `_optimizer`, `_resgroup`.
`sql/direct_dispatch.sql:1-7` is the canonical example:

```sql
-- start_matchsubs
-- m/\(cost=.*\)/
-- s/\(cost=.*\)//
--
-- m/\(slice\d+; segments: \d+\)/
-- s/\(slice\d+; segments: \d+\)//
-- end_matchsubs
```

Before adding a mask, check it is not already there: see
[reference/masking-inventory.md](reference/masking-inventory.md) for the full
shipped inventory. On 7.x, 104 `sql/` files carry a `-- start_matchsubs` block and
162 carry a `-- start_ignore`.

**6.x delta:** `init_file` on 6.x carries only the older `Optimizer: Pivotal
Optimizer (GPORCA)` / `Optimizer: Postgres query optimizer` spellings, and has no
`QUERY PLAN` header-width matchsub. That matchsub is a 7.x-only backstop for
output atmsort did **not** classify as an EXPLAIN; inside a recognised EXPLAIN
block atmsort rewrites the header itself on both lines (`atmsort.pm:1373`).

## What atmsort normalises for free

Do not add a mask for any of these, and do not chase them in a diff.

| Normalised | Mechanism |
|---|---|
| Row order of a `SELECT` with no top-level `ORDER BY` | `atmsort.pm:1398-1428` decides, `:969` sorts |
| `(segN sliceN ip:port pid=N)` suffixes on messages | built-in matchsub `s/\s+\(seg.*pid.*\)//` (`atmsort.pm:216`) |
| `(entry db … pid=N)` on coordinator messages | `init_file` matchsub |
| The same NOTICE/ERROR/WARNING repeated by N segments | adjacent duplicates collapse to one (`atmsort.pm:1282`) |
| Per-node detail lines (`Sort Key:`, `Merge Key:`, `Filter:`, `Hash Cond:`) of a **costed** EXPLAIN | `explain.pm` keeps only each node's first line, and re-emits the plan as a tree dump (`atmsort.pm:491-496`) |
| `Slice statistics:` / `Executor memory:` / `Settings:` / `Total runtime:` trailer, and per-node `total_time` | `PRUNE => 'heavily'` deletes them (`explain.pm:920-938`, `:1182`), plus `init_file` `m/^ Settings:.*/` |
| The ` QUERY PLAN ` header and its `-----` rule line, inside a recognised EXPLAIN block | rewritten to `QUERY PLAN` / `___________` (`atmsort.pm:1369-1376`, 6.x and 7.x alike) |
| The `(N rows)` line after an EXPLAIN | `atmsort.pm:1151` prefixes it `GP_IGNORE:` |
| `NOTICE: Table doesn't have 'DISTRIBUTED BY' clause …` and its HINT | `init_file` matchignore |
| `Distributed by: (…)` / `Distributed randomly` from `\d` | `init_file` matchignore — you **cannot** regression-test `\d` distribution output |
| `DEBUG: … JIT …` lines | `init_file` matchignore, so JIT-on and JIT-off runs agree |

## atmsort's blind spots — the four things it will not save you from

1. **`EXPLAIN (COSTS OFF)` is compared verbatim.** `format_query_output` skips
   `explain.pm` whenever the directive is `costs_off`; the code comment at
   `atmsort.pm:543-547` says so. Matchsubs still apply, plan shape does not get
   pruned. It is the standard plan-test idiom on 7.x — 2443 lines in 131 of the 589
   `sql/` files match atmsort's detector (6.x: 1126 lines in 77 files) — so most
   plan-shape drift you meet is drift in a verbatim comparison, and fixing it means
   editing the node-type words in the expected file.
2. **A *costed* EXPLAIN does not get its costs pruned either.** `PRUNE => 'heavily'`
   deletes timings and the statistics trailer and lifts slice/gang/segment numbers
   into separate keys, but `(cost=… rows=… width=…)`, `(actual time=…)` and
   `(slice1; segments: 3)` all survive inside each node's text (`prune_heavily`,
   `explain.pm:1262`). That is exactly why `sql/direct_dispatch.sql:1-7` ships its
   own `m/\(cost=.*\)/` and `m/\(slice\d+; segments: \d+\)/` matchsubs. Column widths
   and trailing whitespace are significant too — gpdiff passes no `-w`, and no rule
   normalises data column widths.
3. **An `ORDER BY` in a subquery defeats the sort.** The detection is the regex
   `select.*order.*by` over the whole statement, with `OVER (ORDER BY …)`,
   `WINDOW … ORDER BY` and `WITHIN GROUP (ORDER BY …)` stripped first
   (`atmsort.pm:1404-1419`). A subquery `ORDER BY` still matches, atmsort concludes
   the result is ordered, and stops sorting. The test then flutters. Diagnose with
   `atmsort.pl --order_warn`.
4. **Strings containing a newline or a `|` break the tokeniser.** `gpdiff.pl`'s own
   BUGS section says so: such queries must carry an explicit `ORDER BY` or the
   comparison is unreliable.

## Base `.out` vs `_optimizer.out`: which file is actually being compared

`get_expectfile()` (`pg_regress.c:1069`) picks the expected file per test, using
GUC values read **once per run** by `SHOW optimizer;` and `SHOW gp_resource_manager;`
(`check_feature_status`, `pg_regress.c:2715`):

```
resultmap entry  ->  <t>_optimizer_resgroup.out  ->  <t>_optimizer.out
                 ->  <t>_resgroup.out            ->  <t>.out
```

then `<t>_1.out` … `<t>_9.out` as alternates if the chosen file still differs.
`expected/` holds 765 `.out` files on 7.x: 584 base, 153 `_optimizer.out`,
5 `_resgroup.out`, 23 alternates, zero `_optimizer_resgroup.out`.

The rules that follow from that fallback:

- **A base `<t>.out` with no `<t>_optimizer.out` beside it is compared by the ORCA
  run too.** Regenerating it from an `optimizer=off` result breaks the ORCA job.
  Regenerating a base file is only safe when the `_optimizer` variant exists.
- If both optimizers genuinely need different output, **split**: copy the current
  ORCA-passing base to `<t>_optimizer.out` first, then regenerate the base from the
  planner result. Never edit one and hope.
- **Do not backfill `_optimizer.out` files.** Coverage is self-balancing: a test that
  passes against a shared base needs no variant, and a test that genuinely diverges
  is already red. 153 of the 584 base files have one.
- ORCA falls back to the Postgres planner silently. A plan you believe came from
  ORCA may not have — and `init_file` masks the `Optimizer:` line that would have
  told you.
- **A base regeneration has siblings upstream never touches.** Visit them in the same
  change: `<t>_optimizer.out`, `output/<t>.source`, the `enable_*` GUC lists in
  `sysviews` and `rangefuncs_cdb`, and the suites outside `src/test/regress` whose expected
  files carry the same message text (`src/interfaces/gppc/test/expected`,
  `src/bin/gpfdist/regress/output`, `gpcontrib/*/expected`). The CI regression artifact
  does not include that contrib tail — read the job log.

The 7.x GitHub Actions workflow runs `regression-tests`, `orca-tests`,
`resgroup-tests` and `jit-tests` as separate jobs against the same `expected/` tree
(`.github/workflows/greengage-ci.yml`, all delegating to pinned reusable workflows
in `greengagedb/greengage-ci`; tests run **only** on `pull_request`). Any job that
flips `optimizer` or `gp_resource_manager` compares a different file, so a
regeneration that greens one job can redden another. Check all of them before
pushing — see [greengage-ci](../greengage-ci/SKILL.md) for fetching job logs and
artifacts.

## `.source` tests are generated — never commit the generated `.out`

`convert_sourcefiles()` (`pg_regress.c:963`) generates `sql/<t>.sql` from
`input/<t>.source` and `expected/<t>.out` from `output/<t>.source`, substituting
`@abs_builddir@`, `@testtablespace@`, `@hostname@`, `@curusername@`, `@libdir@` and
friends. With the default `--outputdir=.` the generated files land inside the
tracked `sql/` and `expected/` directories, which is why 58 entries in
`sql/.gitignore` and 63 in `expected/.gitignore` exist. 7.x has 80 `.source` files
under `input/` and 90 under `output/` (50 and 58 of them at the top level, the rest
in the `uao_ddl/` and `uao_dml/` subdirectories).

- To change one of these, edit `output/<t>.source`, **never** `expected/<t>.out`.
  Your edit to the generated file is silently overwritten on the next run and cannot
  be committed.
- `gpsourcify.pl` does the reverse substitution — it rewrites a `results/*.out` back
  into token form, so it is the correct starting point for a regeneration here.
- These tests bake absolute paths, hostnames and usernames, which makes them the
  **least locally reproducible class**. Prefer a mask; if you must regenerate,
  regenerate from the failing job's results, not yours.
- `input/uao_ddl/`, `input/uao_dml/` and their `output/` twins each carry a marker
  file `GENERATE_ROW_AND_COLUMN_FILES` that makes every `.source` produce a `_row`
  and a `_column` test. `expected/uao_ddl/` and `expected/uao_dml/` contain nothing
  but a `.gitignore` and a README. Edit `output/uao_*/<t>.source`.

Paths, tokens and the full generation table: [reference/answer-file-map.md](reference/answer-file-map.md).

## Regenerate from the failing job's results, not from a fresh local run

A local demo cluster bakes its own facts into the output: the database name inside
`current_database()` literals, the segment count, local IP addresses, local row
order, local absolute paths. Copying those into `expected/` greens your machine and
reddens CI.

Take `results/<t>.out` from the artifacts of the job that failed, and regenerate
from that. [greengage-ci](../greengage-ci/SKILL.md) covers fetching them. The one
exception is output with nothing environment-dependent left in it — a test that
filters its own result through a matchsub, or one whose only output is a row count.
A costed EXPLAIN is **not** such a case: `explain.pm` leaves `cost=`, `rows=` and
`width=` in place, and those move with the local statistics.

If you must run locally, do not run the test alone. pg_regress **drops and recreates**
the `regression` database unless `--use-existing` is passed (`pg_regress.c:3327-3350`),
and both schedules open with `test: test_setup` under a "required setup steps"
comment. Running one test in isolation therefore starts from an empty database and
dies with errors like `ERROR:  relation "tenk1" does not exist` — `tenk1` is created
by `sql/create_table.sql`. Pass the prerequisites explicitly:

```sh
make -C src/test/regress installcheck-tests TESTS="test_setup create_table <t>"
```

**6.x delta:** there is no `test_setup` test on 6.x — `sql/test_setup.sql` does not
exist and `parallel_schedule` opens with `tablespace`. Drop it from `TESTS` there.

## Procedure

1. `find . -name regression.diffs` — `installcheck-world` produces several, and the
   isolation2 sub-suites write theirs into `resgroup/`, `ic_tcp/`, `hot_standby/`
   and friends.
2. Run the safety gate above on each. Investigate every hit before proceeding.
3. Decide the rung: mask, fix the test, or regenerate. Prefer the lower number.
4. If regenerating: first run `gpdiff.pl … --gpd_init init_file expected/<t>.out
   results/<t>.out` — a file gpdiff passes is not regenerated, whatever `git diff` shows,
   and `results/*.out` is never bulk-copied. Then `cp results/<t>.out expected/<t>.out`,
   taking `results/` from the failing CI job where the test is environment-sensitive.
5. **Do not hand-clean the copy.** It is tempting to strip the gpdiff-ignored
   lines the raw result carries, but this tree keeps them: 353 of the 765 `.out`
   files under `src/test/regress/expected/` contain the `Table doesn't have 'DISTRIBUTED BY'
   clause` NOTICE and 39 contain `Distributed by: (…)`, both of which `init_file`
   matchignores. Stripping them makes your file inconsistent with the other 352 and
   adds churn a reviewer has to read. Copy the file byte-for-byte, trailing
   whitespace included.
6. Re-run the test and confirm `ok    ` and no `regression.diffs`. If the file is a
   shared base, confirm under `optimizer=on` **and** `optimizer=off`.
7. Commit answer-file regenerations as isolated, clearly labelled commits. The
   visual diff is worthless as a review artefact; the gate is the correctness check,
   and a reviewer needs to see that nothing else rode along.

## Never regenerate these

| Class | Symptom | Do instead |
|---|---|---|
| Flaky output | Two runs of the same test produce different `results/<t>.out` | Diff the two results. The intersection of failures is a regen candidate; the rotating remainder is flaky and needs a fix or a mask. |
| Fault injection in a parallel group | A `gp_inject_fault` test that fails only under load | `cd src/test/regress && ./scan_flaky_fault_injectors.sh` — it globs `*schedule` and `sql input specs` in the current directory, so it must be run from there (or from `src/test/isolation2`). It flags exactly this. Move the test to its own schedule group. (6.x runs it for you: it is a phony prerequisite of `all`.) |
| Unordered index or seq scan output | Row order changes run to run | Add `ORDER BY` to the `.sql`, or `-- order 1` |
| `CREATE TABLE AS` with no `DISTRIBUTED BY` | Row placement moves whenever the plan does: the key is deduced from the chosen path (`get_partitioned_policy_from_path`, `cdbllize.c:431`), so ORCA and the planner can pick different keys | Pin `DISTRIBUTED BY` in the `.sql` |
| Memory-pressure victims | `Out of memory`, `failed to acquire resources`, `could not fork` | Discard the run. gpdemo is small; the results are corrupt, not new. |
| Environment-specific text | Paths, hostnames, addresses, conninfo, OIDs, `file.c:NNN` line numbers | Mask it in `init_file` |
| A failed upstream assertion with a "successful" output | `(0 rows)` became `(1 row)`; a size check prints a different number; an EXPLAIN lost the node the test names | Adapt the test input for MPP (the second half of the gate above) |
| Source locations in messages | `(user.c:2093)` appended to an `ereport` that has no `errcode` | Add the missing `errcode()`, or mask it as `init_file`'s `(analyze.c:XXX)` rules do; never bake the line number |
| An `_optimizer.out` full of `did not get … plan` warnings | ORCA ignores `enable_seqscan`/`enable_bitmapscan` | Force the shape with `optimizer_enable_tablescan`/`optimizer_enable_bitmapscan` in the `.sql`; a warning per query is a failure to adapt, not ORCA's answer |
| Coverage-defeating regens | The new plan no longer uses the feature the test exists to prove — a partition-elimination test that now scans every partition, an index test that now seq-scans | **Hold and investigate.** Regenerating deletes the coverage silently. This is the most expensive mistake in this skill. |
| Anything validated only under `--ignore-plans` | The test goes green only when that switch is on | The switch ignores *all* plan content, `COSTS OFF` included. Re-verify without it; never commit on its strength. |

A test listed as `ignore: <test>` in a schedule prints `failed (ignored)`, still
writes its diff to `regression.diffs`, and does not set the non-zero exit status.
The two schedules `installcheck-good` runs carry exactly three on 7.x:
`gp_portal_error` and `tpch500GB_orca` in `greengage_schedule`, `random` in
`parallel_schedule`. Other schedules have their own — five in `serial_schedule`,
one in `icudp_schedule`, four lines in `isolation2_schedule` — so count them in the
schedule your target actually runs. Do not add a fourth to avoid a regen decision.

## Noise to ignore

- A huge `git diff` on a data-returning test. Unordered MPP results arrive in
  segment order; gpdiff sorts them, git does not.
- `Optimizer:` and `Settings:` lines. Both are matchignored globally — chasing a
  JIT-on vs JIT-off `Settings:` difference is chasing something gpdiff never saw.
- A `NOTICE` about `'DISTRIBUTED BY'`, a partition name, or a resource queue.
  Globally matchignored.
- A per-segment `(seg3 slice1 10.0.0.4:25433 pid=12345)` suffix. Stripped by
  atmsort before the diff.
- `regression.diffs` from a previous run. pg_regress deletes it on success, so a
  file that exists after a green run is stale — check the timestamp.

See also: [greengage-testing](../greengage-testing/SKILL.md),
[greengage-ci](../greengage-ci/SKILL.md),
[greengage-build](../greengage-build/SKILL.md),
[greengage-debug](../greengage-debug/SKILL.md),
[greengage-internals](../greengage-internals/SKILL.md),
[greengage-contribute](../greengage-contribute/SKILL.md).
