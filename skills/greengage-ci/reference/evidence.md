# Evidence commands and where the output lives

## `gh` cookbook

`gh` handles authentication; the artifacts and logs endpoints reject unauthenticated
requests, so prefer it over `curl`.

```bash
R=GreengageDB/greengage

gh run list --repo $R --branch 7.x --limit 10
gh run list --repo $R --workflow greengage-ci.yml --limit 20
gh run list --repo $R --json databaseId,headBranch,conclusion,event,displayTitle --limit 20

gh run view <run-id> --repo $R                     # jobs + conclusions
gh run view <run-id> --repo $R --log-failed        # only the failed steps
gh run view --job <job-id> --repo $R --log         # one job, entire log

gh api repos/$R/actions/runs/<run-id>/jobs \
  --jq '.jobs[] | "\(.conclusion)\t\(.name)"'
gh api repos/$R/actions/runs/<run-id>/artifacts \
  --jq '.artifacts[] | "\(.name)\t\(.size_in_bytes)\t\(.expired)"'

gh run download <run-id> --repo $R -n <artifact-name> -D /tmp/ci-art
gh run rerun <run-id> --repo $R --failed           # same SHA: the flaky test
```

For a pull request: `gh pr checks <pr>` lists the check names as branch protection sees
them, which is what an admin needs when a required job is renamed.

## Reading a failed regression job log

`concourse/scripts/ic_gpdb.bash` installs `trap look4diffs ERR`, and `look4diffs` runs
``find .. -name regression.diffs`` and cats each one into the log inside a banner:

```
======================================================================
DIFF FILE: <path>
----------------------------------------------------------------------
```

```bash
gh run view <run-id> --log-failed > /tmp/ci.log
grep -n 'DIFF FILE:' /tmp/ci.log
# gh prefixes every line with "<job>\t<step>\t<timestamp> " — strip it, or nothing
# anchored with ^ will ever match
sed -E 's/^.*[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z //' /tmp/ci.log > /tmp/ci.plain
csplit -z -f /tmp/chunk_ /tmp/ci.plain '/^diff /' '{*}'   # one file per failing test
```

Each chunk opens with the header `pg_regress` writes before running the pretty diff —
`diff <opts> <expected-file> <results-file>` (`pg_regress.c:2006-2013`) — so the header
names the expected file that run actually selected.

The diffs are already produced by `gpdiff.pl` (`pg_regress.c:1914`), so they are the
normalised comparison, not raw `diff`.

## Where `regression.diffs` and `results/` live in the tree

| Suite | Output dir | Diff path |
|---|---|---|
| `src/test/regress` (`installcheck`, `installcheck-good`) | `.` | `src/test/regress/regression.diffs`, results in `src/test/regress/results/` |
| isolation2 default schedule | `.` | `src/test/isolation2/regression.diffs` |
| `installcheck-resgroup` / `-resgroup-v2` | `resgroup` | `src/test/isolation2/resgroup/regression.diffs` |
| `installcheck-resource-queue` (7.x) | `resqueue` | `src/test/isolation2/resqueue/regression.diffs` |
| `installcheck-parallel-retrieve-cursor` | `parallelretrcursor` | `src/test/isolation2/parallelretrcursor/regression.diffs` |
| `installcheck-mirrorless` | `mirrorless` | `src/test/isolation2/mirrorless/regression.diffs` |
| `installcheck-hot-standby` (7.x) | `hot_standby` | `src/test/isolation2/hot_standby/regression.diffs` |
| `installcheck-ic-tcp` | `ic_tcp` | `src/test/isolation2/ic_tcp/regression.diffs` |
| `installcheck-ic-proxy` | `ic_proxy` | `src/test/isolation2/ic_proxy/regression.diffs` |

Source: `src/test/isolation2/Makefile` `--outputdir` arguments. `pg_regress` also writes
`<outputdir>/regression.out` and creates `<outputdir>/results/` (`pg_regress.c:2550-2575`);
`results/<test>.out` is the raw run output and the only correct source for a regeneration.

## Server logs

Demo-cluster data directories: `gpAux/gpdemo/datadirs/qddir/demoDataDir-1` (coordinator),
`dbfast{1,2,3}/demoDataDir{0,1,2}` (primaries), `dbfast_mirror{1,2,3}/…`, `standby/`.

| Line | Log directory under each data dir |
|---|---|
| 7.x | `log/` |
| 6.x | `pg_log/` |

`log_directory` is marked **Defunct** in `src/backend/utils/misc/guc.c` in both lines; the
default value is the only thing that differs (`"log"` on 7.x, `"pg_log"` on 6.x).

Behave runs tar three trees per feature (`ci/scripts/behave_collect_logs.bash`, only when
`$CI` is set):

```
/logs/behave_<feature>_gpAdminLogs.tar
/logs/behave_<feature>_log.tar
/logs/behave_<feature>_pg_log.tar
```

## Answer-file selection

`pg_regress.c:1121-1141` (7.x; 6.x `1107-1127`), in order, first existing file wins — the
`return NULL` at the end is what makes `expected/<test>.out` the last resort:

```
optimizer=on + resgroup  ->  expected/<test>_optimizer_resgroup.out
optimizer=on             ->  expected/<test>_optimizer.out
resgroup                 ->  expected/<test>_resgroup.out
(fallback)               ->  expected/<test>.out
```

`src/test/regress/resultmap` is consulted **before** the optimizer/resgroup fallbacks and
can redirect a test to a platform-specific file. On 7.x it carries only `float4` entries
for cygwin/mingw/hpux; 6.x additionally carries `float4`/`float8`/`int8` entries for
mingw/win32/freebsd/openbsd/netbsd. On Linux neither matches.

Counts of the top-level files at the tip of each line (the `expected/` subdirectories —
`icudp/`, `uao_ddl/`, `uao_dml/` — are not included):

| | 7.x | 6.x |
|---|---|---|
| `src/test/regress/expected/*.out` | 706 | 574 |
| of which `_optimizer.out` | 153 | 106 |
| of which `_resgroup.out` | 5 | 3 |
| `src/test/isolation2/expected/*.out` | 145 | 136 |
| of which `_optimizer.out` | 7 | 8 |

## Reproducing a job locally

7.x, from `ci/readme.md` (verbatim):

```bash
docker build -t gpdb7_u22:latest -f ci/Dockerfile.ubuntu .       # Ubuntu 22.04
docker build -t gpdb7_regress:latest -f ci/Dockerfile .          # Rocky Linux

# full suite, ORCA
docker run --name gpdb7_opt_on --rm -it -e TEST_OS=ubuntu \
  -e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on' installcheck-world" \
  --sysctl "kernel.sem=500 1024000 200 4096" gpdb7_u22:latest \
  /home/gpadmin/gpdb_src/concourse/scripts/ic_gpdb.bash

# JIT, ORCA
-e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on -c jit=on -c jit_above_cost=0 \
   -c optimizer_jit_above_cost=0 -c gp_explain_jit=off' installcheck"

# JIT, planner (note: no optimizer_jit_above_cost)
-e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=off -c jit=on -c jit_above_cost=0 \
   -c gp_explain_jit=off' installcheck"
```

`ci/readme.md` writes the last one as `MAKE_TEST_COMMAND="make -k …"`. That leading `make`
is a readme bug — `ic_gpdb.bash` already runs `make -s ${MAKE_TEST_COMMAND}` — so drop it.

Rocky Linux uses `-e TEST_OS=centos` and the `gpdb7_regress` image (`ci/Dockerfile`,
`FROM rockylinux:8.8`; `ci/Dockerfile.ubuntu` is `FROM ubuntu:22.04`). Add `--privileged`
to run gdb inside the container.

Resource groups (`ci/scripts/run_resgroup_test.bash`, not mentioned in `ci/readme.md`):

```bash
IMAGE=gpdb7_u22:latest LOGS=$PWD/logs TEST_OS=ubuntu OPTIMIZER=off STATEMENT_MEM=125MB \
  bash ci/scripts/run_resgroup_test.bash
```

It starts the container `--privileged`, chmods `/sys/fs/cgroup/{memory,cpu,cpuset}` and
runs `make PGOPTIONS='-c optimizer=$OPTIMIZER -c statement_mem=$STATEMENT_MEM'
installcheck-resgroup`, writing the exit code to `$LOGS/.exitcode`. Requires **cgroup v1**
(`stat -fc %T /sys/fs/cgroup/` must print `tmpfs`).

Behave (`ci/scripts/run_behave_tests.bash`):

```bash
docker build -t "greengage7_u22:${BRANCH_NAME}" -f ci/Dockerfile.ubuntu .
IMAGE=greengage7_u22:${BRANCH_NAME} bash ci/scripts/run_behave_tests.bash            # all
IMAGE=greengage7_u22:${BRANCH_NAME} bash ci/scripts/run_behave_tests.bash gpstart gpstop
```

3 features in parallel, `clusters="~concourse_cluster"`, `cross_subnet`/`gpssh`/`gpexpand`
excluded from the default set, output in `allure-results/`, 4-host compose cluster
`cdw`/`sdw1`/`sdw2`/`sdw3` from `ci/docker-compose.yaml`.

ORCA unit tests and linter:

```bash
docker run --rm -it gpdb7_u22:latest bash -c "gpdb_src/concourse/scripts/unit_tests_gporca.bash"
docker build -t orca-linter:test -f ci/Dockerfile.linter . && docker run --rm -it orca-linter:test
```

The linter requires a clean work tree — stage or commit first.

### 6.x deltas

`ci/readme.md` on 6.x uses `-e TEST_OS=centos`, image `gpdb6_regress`, and must start sshd
by hand because the container does not. Note the readme builds `gpdb6_regress` from
`ci/Dockerfile.ubuntu` (Ubuntu 22.04) and still passes `TEST_OS=centos` — that is what the
readme says, so do not "correct" it to `TEST_OS=ubuntu`:

```bash
docker run --name gpdb6_opt_on --rm -it -e TEST_OS=centos \
  -e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on' installcheck-world" \
  --sysctl 'kernel.sem=500 1024000 200 4096' gpdb6_regress:latest \
  bash -c "ssh-keygen -A && /usr/sbin/sshd && bash /home/gpadmin/gpdb_src/concourse/scripts/ic_gpdb.bash"
```

6.x also ships `ci/Dockerfile.rockylinux` (`--build-arg OS_VERSION=9` for Rocky 9), takes
`--build-arg OS_VERSION=24.04` on `ci/Dockerfile.ubuntu`, and has `ci/Dockerfile.centos`
(a symlink to `ci/Dockerfile`, which is `FROM centos:centos7`). 7.x ships
`ci/Dockerfile.pg_upgrade` and `ci/Dockerfile.ubuntu.clang-check` instead, and its
`ci/Dockerfile.ubuntu` takes no `OS_VERSION` arg. 6.x has no
`ci/scripts/behave_collect_logs.bash`.

## What the CI cluster sets that a bare demo cluster does not

From `concourse/scripts/common.bash` `make_cluster()` and `ic_gpdb.bash` `gen_env()`:

| Variable | CI value |
|---|---|
| `WITH_MIRRORS` | `${WITH_MIRRORS:-true}` |
| `STATEMENT_MEM` | `250MB` |
| `LANG` | `en_US.utf8` |
| `PG_TEST_EXTRA` | `"kerberos ssl"` — **7.x only**; 6.x `ic_gpdb.bash` sets it nowhere and its `src/test/Makefile` lists `ssl kerberos` in `SUBDIRS` unconditionally |
| `BLDWRAP_POSTGRES_CONF_ADDONS` | passed through |
| install prefix | `/usr/local/greengage-db-devel` (unpacked from `bin_gpdb/bin_gpdb.tar.gz`, or `bin_gpdb_with_llvm_asserts.tar.gz` when `CONFIGURE_FLAGS` has `enable-cassert`) |
| env script sourced | `/usr/local/greengage-db-devel/greengage_path.sh` then `gpAux/gpdemo/gpdemo-env.sh` |

When `MAKE_TEST_COMMAND` mentions `gp_interconnect_type=proxy`, `make_cluster` additionally
derives `gp_interconnect_proxy_addresses` from `gp_segment_configuration` (port minus 3000)
and sets `gp_interconnect_tcp_listener_backlog=1024`.
