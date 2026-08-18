---
name: greengage-ci
description: Triage a red Greengage CI run on GitHub Actions - greengage-ci.yml job matrix, pinned greengagedb/greengage-ci reusable workflows, shared expected/*.out answer files, pulling regression.diffs from job logs and artifacts with gh, classifying failures as cosmetic drift, real bug, flaky or lost coverage, reproducing a job in the ci/ docker images. Use when a PR check is red, a log shows "DIFF FILE:", "FailedAssertion(" or "server closed the connection unexpectedly", or a fix that greened one job turned another red.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Triaging a red Greengage CI run

## CI is GitHub Actions; `concourse/` is where the scripts live, not where the run happens

Everything that gates a pull request is declared in `.github/workflows/`:
`greengage-ci.yml`, `greengage-abi-tests.yml`, `greengage-release.yml`, and (7.x only)
`greengage-sql-dump.yml`, documented in `.github/workflows/README.md`.

`greengage-ci.yml` contains **no test commands at all**. Every job delegates to a
reusable workflow in the separate `greengagedb/greengage-ci` repository, pinned to a tag:

```yaml
uses: greengagedb/greengage-ci/.github/workflows/greengage-reusable-tests-regression.yml@v28
with:
  version: 7
  target_os: ${{ matrix.target_os }}
```

Consequences you must internalise before triaging:

- **The commands are not in this repo.** The suite a job ran is
  `make -s $MAKE_TEST_COMMAND` (`concourse/scripts/ic_gpdb.bash` `gen_env()`), and
  `MAKE_TEST_COMMAND` is set by the reusable workflow. Read it off the job log's
  container-launch step; never guess it.
- **6.x and 7.x pin different tags of the same reusable workflow** (7.x
  `-tests-regression.yml@v28`, 6.x `@v46`). Same job name, different behaviour per line.
- `concourse/` is legacy Greenplum pipeline *code*, but `concourse/scripts/ic_gpdb.bash`,
  `common.bash` and `unit_tests_gporca.bash` are the entrypoints `ci/readme.md` and
  `ci/scripts/*` still execute inside the container. Reading them is how you learn what a
  job does. `concourse/pipelines/pr_pipeline.yml` still exists — it is a Concourse
  pipeline file, triggered by nothing in this repo, and it is **not** the PR gate.

## Tests run only on pull requests

`greengage-ci.yml` triggers on push to `7.x` (6.x: `6.x`) plus version tags, and on
`pull_request` to `**`. Every test job carries `if: github.event_name == 'pull_request'`.
A green push build on `7.x` therefore proves **only that the image builds** — it ran no
tests. Never cite a branch push run as evidence that a merge is safe.

`concurrency.cancel-in-progress: true` is grouped by PR number, so a new push cancels the
in-flight run. **A conclusion of `cancelled` is not a failure.** Check the conclusion
before triaging anything.

## The 7.x job matrix

| Job | Trigger | Reusable workflow (7.x pin) | Matrix |
|---|---|---|---|
| `build` | PR + push + tags | `greengage-reusable-build.yml@v33` | ubuntu |
| `behave-tests` | PR only | `-tests-behave.yml@v35` | ubuntu |
| `regression-tests` | PR only | `-tests-regression.yml@v28` | ubuntu |
| `orca-tests` | PR only | `-tests-orca.yml@v28` | ubuntu |
| `resgroup-tests` | PR only | `-tests-resgroup.yml@v31` | ubuntu |
| `jit-tests` | PR only | `-tests-jit.yml@v28` | ubuntu |
| `upload` | push only | `-upload.yml@v28` | ubuntu |
| `package` | PR + push | `-package.yml@v44` | ubuntu, `test_docker: ubuntu:22.04` |

6.x deltas that change where a failure can come from:

| | 6.x | 7.x |
|---|---|---|
| `build` matrix | ubuntu 22.04, ubuntu 24.04, Rocky 8, Rocky 9 | ubuntu only |
| `regression-tests` | ubuntu **24.04 only** | ubuntu |
| `behave-tests` | ubuntu 22.04 **and** 24.04 (runs twice) | ubuntu |
| `jit-tests` | absent | present |
| `coverage` | present, `coverage_threshold: 75` | absent |

Two 6.x traps follow from that table. A Rocky-only compile break shows up in `build` and
in **no test job**, because tests never run on Rocky. And `coverage` is gated on
`needs.behave-tests.result == 'success' && needs.regression-tests.result == 'success'`, so
while tests are red it is *skipped*, not failed — fixing the tests can expose a brand-new
red coverage job that was never evaluated before.

The `.github/workflows/README.md` line "Package: … Currently supported for version 6.x
only" is stale: 7.x `greengage-ci.yml` defines a `package` job. **Trust the YAML over the
README prose.** Full per-job detail, plus the ABI, release and SQL-dump workflows, is in
[reference/job-matrix.md](reference/job-matrix.md).

## Every optimizer job reads the same `expected/*.out` tree

`pg_regress` picks an answer file by falling back, not by job
(`src/test/regress/pg_regress.c:1121-1141`, 7.x; 6.x `1107-1127`):

| Run | First choice | Fallback |
|---|---|---|
| `optimizer=on` + resgroup | `<t>_optimizer_resgroup.out` | ↓ |
| `optimizer=on` | `<t>_optimizer.out` | ↓ |
| resgroup | `<t>_resgroup.out` | ↓ |
| anything else | `<t>.out` | — |

On 7.x that is 706 top-level `expected/*.out` files: 153 `_optimizer.out`, 5
`_resgroup.out`, and 548 base files. Every one of those 153 has a base file too, so
**395 of the 548 have no ORCA-specific answer file at all — the ORCA job, the planner job
and both JIT variants compare them against the identical `<t>.out`** (the JIT job is two
runs: `ci/readme.md` — "jit tests need to be executed with optimizer both on and off").
Regenerating that one file to green one job silently changes the answer for three others.
You never have to guess which file a run used: every chunk in `regression.diffs` opens
with a `diff <opts> <expected-file> <results-file>` header naming the expected file
`pg_regress` actually chose (`pg_regress.c:2006-2013`).
Before editing any expected file, work out which of the four reads it — the rules are in
[greengage-answer-files](../greengage-answer-files/SKILL.md).

6.x: 574 `.out`, 106 `_optimizer.out`, 3 `_resgroup.out`. Same structure, same trap.

Coverage is *not* the same across jobs, though. Top-level `make installcheck` recurses only
into `src/test/regress` (`GNUmakefile.in:159-161`), where `installcheck` = `installcheck-good`
= `parallel_schedule` + `greengage_schedule`. `installcheck-world` additionally recurses
through `ICW_TARGETS` (isolation2, gpcontrib, `src/bin`, `gpMgmt/bin`, a dozen `contrib`
modules) plus `installcheck-gpcheckcat` and `installcheck-analyze`. A job that runs
`installcheck` cannot fail an isolation2 test; do not look for one there.

## The job log already contains `regression.diffs` — read it before downloading anything

`concourse/scripts/ic_gpdb.bash` `gen_env()` writes a `trap look4diffs ERR` into the test
script it generates, so on any test failure `find .. -name regression.diffs` runs and
**every** hit is cat'd into the log (same code on 6.x and 7.x):

```
======================================================================
DIFF FILE: ../gpdb_src/src/test/regress/regression.diffs
----------------------------------------------------------------------
```

So the first move is always:

```bash
gh run view <run-id> --log-failed > /tmp/ci.log
grep -n 'DIFF FILE:' /tmp/ci.log
```

Those diffs are already gpdiff-filtered — they are what actually failed, not raw `diff`
output. Never triage from a guess, a test name, or a summary line; work from the diff text.
If there is no `DIFF FILE:` banner, that job did not go through `ic_gpdb.bash` —
`ci/scripts/run_resgroup_test.bash`, for one, calls `make` directly and has no trap. Fall
back to the artifacts.

isolation2 sub-suites write into their own `--outputdir`, so their diffs land at different
paths (`src/test/isolation2/Makefile`): `resgroup/`, `resqueue/`, `parallelretrcursor/`,
`mirrorless/`, `hot_standby/`, `ic_tcp/`, `ic_proxy/`. The `DIFF FILE:` banner tells you
which suite failed.

## Fetch the rest with `gh`, not curl

`gh` carries the auth; raw `curl` against the API needs a token you probably do not have.

```bash
gh run list --repo GreengageDB/greengage --branch <branch> --limit 10
gh run view <run-id> --repo GreengageDB/greengage            # job list + conclusions
gh run view --job <job-id> --log                              # one job's full log
gh api repos/GreengageDB/greengage/actions/runs/<run-id>/artifacts \
  --jq '.artifacts[] | "\(.name)\t\(.size_in_bytes)"'         # enumerate, do not guess
gh run download <run-id> -n <artifact-name> -D /tmp/ci-art
gh run rerun <run-id> --failed                                # flaky check, same SHA
```

Artifact names come from the reusable workflows and change with their pinned tag, so
**enumerate them; never hard-code a name.** The only artifact names declared in this repo
are the SQL dump (`sqldump_ggdb7_ubuntu`, from
`/mnt/logs/ubuntu_postgres_sqldump.tar`) and the ABI workflow's
`exception_lists`, `build-baseline`, `build-latest`, `compat-report-<sha>`. Behave runs
collect `/logs/behave_<feature>_{gpAdminLogs,log,pg_log}.tar`
(`ci/scripts/behave_collect_logs.bash`, only when `$CI` is set).

Segment and coordinator logs are inside those tarballs under
`gpdb_src/gpAux/gpdemo/datadirs/*/`. **On 7.x the log directory is `log`; on 6.x it is `pg_log`**
(`src/backend/utils/misc/guc.c` `log_directory` default) — that is why the collector
script tars both names. Reading them is [greengage-debug](../greengage-debug/SKILL.md).

## Classify every failing test before you touch anything

Split the diff into per-test chunks and give each exactly one verdict.

**REAL — never regenerate, never mask:**

| Signature | What it means |
|---|---|
| a result *value* differs (sum, count, string) | wrong answer |
| rows missing or extra, `(N rows)` count changed | wrong answer |
| `+ERROR:` where the expected file has rows | success turned into failure |
| `DETAIL:  FailedAssertion("<cond>", File: "<f>", Line: <n>)` | assertion crash (see below) |
| `server closed the connection unexpectedly`, `Error on receive from seg0 slice1 …: server closed the connection unexpectedly` | a segment died |
| `PANIC`, `cache lookup failed`, `could not devise a plan` newly appearing | backend bug |

The Greengage assertion spelling is not upstream's. `ExceptionalCondition()` in
`src/backend/utils/error/assert.c` raises `ereport(FATAL, … errmsg("Unexpected internal
error"), errdetail("%s(\"%s\", File: \"%s\", Line: %d)"))` and then re-raises to dump core.
The `%s` is the `errorType` argument, which `Assert()` fixes to `"FailedAssertion"`
(`src/include/c.h:832`). So you look for `FATAL:  Unexpected internal error` with a
`DETAIL:  FailedAssertion(...)` line (the spelling is quoted verbatim in a test comment at
`src/test/regress/expected/portals.out:1242`), plus the
client-side `server closed the connection unexpectedly` on the coordinator. **Do not grep
for `TRAP: failed Assert` — that is PostgreSQL 13+ wording and Greengage 7.x is
PostgreSQL 12.22.**

**COSMETIC — safe to regenerate or mask:**

| Class | Signature |
|---|---|
| Error-location suffix drift | only `(foo.c:123)` → `(foo.c:456)` changed |
| Catalog/OID drift | printed OIDs shifted by new catalog entries |
| Statistics drift | ANALYZE MCV/histogram sampling differences |
| New upstream test content | added queries and their output, nothing existing changed |
| Documented limitation + its cascade | e.g. an unsupported-feature ERROR that the test expects |

For the first class the fix is usually **not** a regen: `src/test/regress/init_file`
already carries `matchsubs` entries that collapse `(analyze.c:NNN)`, `(cdbpartition.c:NNN)`,
`(openssl.c:NNN)`, `(cdbpath.c:NNN)`, `(dbsize.c:NNN)`, `(cdbmutate.c:NNN)`,
`(cdbdisp_async.c:…)` and `(parse_utilcmd.c:NNN)`. If a *different* file's line number is
drifting, add a `matchsubs` pair to `init_file` — one edit fixes every test at once and
survives the next line-number shift. Baking the new number into an expected file does not.

**FLAKY — confirm, then leave alone:** re-run the identical SHA (`gh run rerun --failed`).
A failure that does not reproduce is flaky. Regenerating from a flaky run bakes one run's
output into the tree, which is worse than the flake. Track it, do not "fix" it.

**HELD — output is correct, coverage was lost:** the query returns the right rows but the
plan no longer exercises what the test was written for (partition elimination disappeared,
a motion type changed, an index scan became a seq scan). Regenerating deletes the test's
purpose while leaving it green. Hold these for a real investigation.

## gpdiff already masked the easy stuff, so most "cosmetic" classes are not cosmetic here

`pg_regress` does not call `diff`; it calls `gpdiff.pl`
(`src/test/regress/pg_regress.c:1914`), which runs `atmsort` over both sides. That changes
what a surviving diff means:

- **Row order.** atmsort "sorts the query output for all SELECT statements that do *not*
  have an ORDER BY" (`atmsort.pl` DESCRIPTION). A row-order-only diff therefore is **not**
  MPP nondeterminism you can regenerate away. It means either the query *has* an `ORDER BY`
  that does not fully specify the order (a real test bug — add a tiebreaker), or atmsort
  could not parse the statement — the POD's own list: embedded `INSERT`/`UPDATE`/`DELETE`
  keywords, no terminating semicolon, or output with embedded newlines or `|` characters —
  and the test needs an `-- order N` or `-- mvd` directive.
- **Plan costs.** Plain `EXPLAIN` and `EXPLAIN ANALYZE` output is reduced by `explain.pm`
  to node identity plus tree shape; atmsort.pl's own worked example turns
  `Gather Motion 2:1  (slice1)  (cost=0.00..698.88 rows=25088 width=550)` into
  `'short' => 'Gather Motion'`. Costs, row estimates, widths, timings, slice statistics and
  worker counts are already gone. A diff inside a plain EXPLAIN block is a genuine change of
  plan node or tree shape — classify it HELD or REAL, not cosmetic.
- **`EXPLAIN (COSTS OFF)` is compared verbatim** (`atmsort.pm:541-548`), and so is any block
  under `-- explain_processing_off`. Those are the EXPLAIN blocks where node-name drift can
  legitimately be cosmetic.
- `Optimizer:` / `Optimizer status:` / `Settings:` lines are in `init_file`'s
  `matchignore` block, and its `matchsubs` rewrite the `QUERY PLAN` header and the dashed
  rule to a fixed width. If they appear in a diff, the run did not pass
  `--init-file=src/test/regress/init_file` (`REGRESS_OPTS`,
  `src/test/regress/GNUmakefile:215`) — suspect the invocation, not the test.

atmsort's per-test directives (`-- order N`, `-- order none`, `-- ignore`, `-- mvd`,
`-- start_ignore`/`-- end_ignore`, `-- start_matchsubs`/`-- end_matchsubs`,
`-- force_explain`, `-- explain_processing_on|off`) are documented in the POD block of
`src/test/regress/atmsort.pl`. Read it before inventing a mask.

## Then try to refute every REAL and UNSURE verdict

A verdict is not a finding until you have argued against it. For each REAL/UNSURE chunk,
attempt in order:

1. Match it against the cosmetic table above. Can any single hunk be explained by drift?
2. Check the base commit. Does the diff signature match a commit already reverted, or a
   stale build cache? A diff describing behaviour nobody changed is usually a stale binary.
3. Check for cascade. A crashed segment makes every later test in the run fail with
   connection errors. The **first** failing test is the root cause; the rest is noise. Fix
   one crash and expect a new, longer, more honest failure list on the next run.
4. Check whether the same test also fails in the sibling job. A failure present in the ORCA
   job only, on a test with no `_optimizer.out`, is an optimizer bug, not drift.

Spot-check a sample of the COSMETIC verdicts the same way. A cosmetic misclassification is
how a real bug gets committed into an expected file.

## Local repro is not CI

The CI cluster is built by `make_cluster` in `concourse/scripts/common.bash`, which is not
what you get from a bare `make create-demo-cluster`:

| CI sets | Effect if your local cluster differs |
|---|---|
| `WITH_MIRRORS=${WITH_MIRRORS:-true}` | mirrorless local cluster changes recovery/FTS tests |
| `STATEMENT_MEM=250MB` | different spill behaviour and plans |
| `LANG=en_US.utf8` | collation-ordered output differs |
| `PG_TEST_EXTRA="kerberos ssl"` (`ic_gpdb.bash`, 7.x) | adds `src/test/{kerberos,ssl}` to `src/test`'s SUBDIRS under `installcheck-world` (`src/test/Makefile:24-37`); unset locally they are skipped. 6.x lists both unconditionally and sets no `PG_TEST_EXTRA` |
| default 3 primary/mirror pairs, `PORT_BASE=7000` | segment counts and ports appear in error text |

On top of that, container hostname and socket paths are baked into connection-error
messages, the database name is folded into `current_database()` literals, and `.source`
tests embed `@abs_builddir@`. **Some CI failures cannot be reproduced locally at all.** For
those, regenerate only from CI output, never from a local run, and prefer an `init_file`
`matchsubs` mask over baking any environment-specific value into an expected file.

## Reproducing a job in the `ci/` containers

Commands are verbatim from `ci/readme.md`; the full set, including the 6.x forms, is in
[reference/evidence.md](reference/evidence.md).

```bash
docker build -t gpdb7_u22:latest -f ci/Dockerfile.ubuntu .

docker run --name gpdb7_opt_on --rm -it -e TEST_OS=ubuntu \
  -e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on' installcheck-world" \
  --sysctl "kernel.sem=500 1024000 200 4096" gpdb7_u22:latest \
  /home/gpadmin/gpdb_src/concourse/scripts/ic_gpdb.bash
```

Swap `MAKE_TEST_COMMAND` to change suite: `optimizer=off` for the planner job, and for the
JIT job `-k PGOPTIONS='-c optimizer=on -c jit=on -c jit_above_cost=0 -c
optimizer_jit_above_cost=0 -c gp_explain_jit=off' installcheck` (the `optimizer=off` twin
drops `optimizer_jit_above_cost`). `ci/readme.md` prefixes that twin with a stray `make` —
drop it, because `ic_gpdb.bash` already runs `make -s $MAKE_TEST_COMMAND`. The resgroup job
has a dedicated runner that is *not* documented in `ci/readme.md`:

```bash
IMAGE=gpdb7_u22:latest LOGS=$PWD/logs TEST_OS=ubuntu OPTIMIZER=off \
  bash ci/scripts/run_resgroup_test.bash
```

It runs `--privileged` and needs **cgroup v1**. Behave:
`IMAGE=greengage7_u22:<branch> bash ci/scripts/run_behave_tests.bash gpstart gpstop`, which
brings up the 4-host `cdw`/`sdw1..3` compose cluster from `ci/docker-compose.yaml`, runs 3
features in parallel with `--tags=~concourse_cluster`, and writes `allure-results/`.

Better still, pull the exact image CI used rather than rebuilding: the build job pushes
`ghcr.io/greengagedb/greengage/ggdb7_ubuntu:<commit-sha>` (name construction in
`greengage-sql-dump.yml`; `docker login ghcr.io` first — the workflows read it with a
`packages: read` token, not anonymously). Suite-level detail lives in
[greengage-testing](../greengage-testing/SKILL.md); build flags in
[greengage-build](../greengage-build/SKILL.md).

## What not to do

- **Do not regenerate an expected file whose diff shows a result replaced by an `ERROR`.**
  That is the one absolute gate.
- Do not regenerate from a run you have not re-run at least once, unless the diff is
  deterministic by construction.
- Do not treat a `cancelled` run, a skipped `coverage` job, or a skipped `upload` job as a
  failure.
- Do not conclude "JIT bug" from a red `jit-tests`. It reads the same answer files as every
  other regression job; check the non-JIT jobs first.
- Do not triage a behave failure from the behave summary. For every failed scenario the CI
  formatter (`gpMgmt/test/behave_utils/ci/formatter.py`) attaches the scenario's captured
  stdout/stderr and every file in `~/gpAdminLogs` to the allure report — that attachment is
  the evidence. Behave scenarios tagged `concourse_cluster` are excluded
  (`clusters="~concourse_cluster"` in `ci/scripts/run_behave_tests.bash`) and cannot run on
  a demo cluster.
- Do not fix a wedged-cluster cascade test by test. Recover the cluster first
  ([greengage-cluster-ops](../greengage-cluster-ops/SKILL.md)), then rerun.

## Changing the job list needs an administrator

`.github/workflows/README.md` states it in a warning block: whenever the list of **names of
required jobs** — including names inside reusable workflows — is added to, removed from, or
renamed, a repository administrator must update the branch protection rules, or the new or
renamed job will not be recognised as required on pull requests. A renamed job that quietly
stops being required looks exactly like a green PR.

`.github/CODEOWNERS` routes `/.github/` to `@GreengageDB/ci`, so any workflow edit
auto-requests that team for review. PR conventions are in
[greengage-contribute](../greengage-contribute/SKILL.md).

See also: [greengage-answer-files](../greengage-answer-files/SKILL.md),
[greengage-testing](../greengage-testing/SKILL.md),
[greengage-build](../greengage-build/SKILL.md),
[greengage-debug](../greengage-debug/SKILL.md),
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md),
[greengage-contribute](../greengage-contribute/SKILL.md)
