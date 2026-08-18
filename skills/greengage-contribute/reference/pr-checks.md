# What runs on a Greengage pull request

Read from `.github/workflows/` on `refs/remotes/origin/7.x` and
`refs/remotes/origin/6.x`. Pipeline internals live in a separate repository,
`greengagedb/greengage-ci`, referenced by pinned tag.

## Workflows present

| File | 7.x | 6.x | Triggers |
|---|---|---|---|
| `greengage-ci.yml` | yes | yes | `push` on `7.x` / `6.x` and tags `7.*` / `6.*`; `pull_request` on `**` |
| `greengage-abi-tests.yml` | yes | yes | `workflow_dispatch`; `pull_request` on `**` |
| `greengage-release.yml` | yes | yes | `release: types: [released]` (`.github/workflows/README.md` still calls it `release: [published]` — the yaml wins) |
| `greengage-sql-dump.yml` | yes | — | `workflow_run` after `Greengage CI` completes, for `6.x`, `7.x`, `next` |

There is **no CLA workflow file**. The CLA status check comes from an external app.

## `Greengage CI` jobs

Every job delegates to `greengagedb/greengage-ci/.github/workflows/<name>@<tag>`.
All test jobs carry `if: github.event_name == 'pull_request'`, so pushes to a release
branch build, package and upload, but run no tests.

| Job | 7.x reusable workflow | 6.x reusable workflow | Runs on |
|---|---|---|---|
| `build` | `greengage-reusable-build.yml@v33` | `@v42` | PR + push |
| `behave-tests` | `greengage-reusable-tests-behave.yml@v35` | `@v46` | PR only |
| `regression-tests` | `greengage-reusable-tests-regression.yml@v28` | `@v46` | PR only |
| `orca-tests` | `greengage-reusable-tests-orca.yml@v28` | `@v28` | PR only |
| `resgroup-tests` | `greengage-reusable-tests-resgroup.yml@v31` | `@v31` | PR only |
| `jit-tests` | `greengage-reusable-tests-jit.yml@v28` | — | PR only |
| `coverage` | — | `greengage-reusable-coverage.yml@v46` | PR only, and only if `behave-tests` and `regression-tests` both succeeded |
| `upload` | `greengage-reusable-upload.yml@v28` | `@v28` | push/tag only |
| `package` | `greengage-reusable-package.yml@v44` | `@v47` | PR + push (no `if:` gate) |

OS matrix, per job (`target_os` with no `target_os_version` means Ubuntu 22.04 — the
`.github/workflows/README.md` backward-compatibility rule):

| Job | 7.x matrix | 6.x matrix |
|---|---|---|
| `build` | `ubuntu` | `ubuntu`, `ubuntu` 24.04, `rockylinux` 8, `rockylinux` 9 |
| `behave-tests` | `ubuntu` | `ubuntu`, `ubuntu` 24.04 |
| `regression-tests` | `ubuntu` | `ubuntu` 24.04 only |
| `orca-tests` | `ubuntu` | `ubuntu` |
| `resgroup-tests` | `ubuntu` | `ubuntu` 24.04 only |
| `coverage` | — | `ubuntu` 24.04, `coverage_threshold: 75` |
| `upload` | `ubuntu` | `ubuntu`, `ubuntu` 24.04 |
| `package` | `ubuntu` | `ubuntu`, `ubuntu` 24.04 (both `test_install: true`), `rockylinux` 8, `rockylinux` 9 |

Concurrency: `${{ github.workflow }}-<PR number or ref>` with
`cancel-in-progress: true` — pushing again to the PR cancels the running checks.
A "cancelled" job is your own newer push, not an infrastructure fault.

## Two gates that are not in the workflow files

| Gate | Evidence | Symptom |
|---|---|---|
| Maintainer must approve the first run | `CONTRIBUTING.md:67` — "After basic review ... and approve to run CI pipelines, the processes of patch review begins" | a brand-new contributor's PR shows **zero** checks |
| Required-check names live in branch protection | `.github/workflows/README.md`: adding, removing or renaming a required job name "must contact a repository administrator to update the Branch Protection Rules" | a renamed job stops being enforced, or the PR blocks on a check that no longer exists |

`.github/CODEOWNERS` (both lines) is a single rule: `/.github/ @GreengageDB/ci`.
Any change under `.github/` auto-requests review from the CI team.

## The ABI check

`greengage-abi-tests.yml` jobs: `abi-dump-setup` → `abi-dump` (matrix
`build-baseline` / `build-latest`) → `abi-compare`.

The baseline is picked at runtime. On 7.x:

```bash
git ls-remote --tags --refs --sort='v:refname' \
  https://github.com/GreengageDB/greengage.git '7.*' | grep -v '-' | tail -n 1
```

i.e. the newest non-prerelease tag on the line. **6.x runs the same command with `'6.*'`
and no `grep -v '-'`**, so on 6.x a prerelease tag can become the baseline. `abi-compare` runs
`abi-compliance-checker -lib postgres -old build-baseline/postgres*.abi -new
build-latest/postgres*.abi`, optionally with `-skip-symbols` / `-skip-types` from
`.abi-check/<baseline version>/`.

When `abi-compare` fails:

1. Read the report. The job prints it with `lynx -dump` and uploads it as artifact
   `compat-report-<sha>`.
2. If the break is real, change the patch — do not suppress it.
3. If it is a genuinely safe break (a removed symbol nothing links against), add the
   symbol to `.abi-check/<baseline version>/postgres.symbols.ignore`, one per line, or
   the type to `postgres.types.ignore` (prefix a struct with the `struct` keyword).
   The directory must be named for the **baseline tag**, e.g. `.abi-check/7.4.1/`.

Reproducing locally (`.abi-check/README.md`) requires `-Og -g3`:

```bash
CFLAGS='-Og -g3 -Wno-maybe-uninitialized' ./configure ...
abi-dumper $GPHOME/bin/postgres -lver 7.4.1 -o greengage-7.4.1.dump
abi-compliance-checker -lib postgres -old greengage-7.4.1.dump -new greengage-new.dump
```

## Reproducing the test jobs locally

From `ci/readme.md`, verbatim. Build the image from a **clean** source tree (no
objects from a previous build):

```bash
docker build -t gpdb7_u22:latest -f ci/Dockerfile.ubuntu .   # Ubuntu 22.04
docker build -t gpdb7_regress:latest -f ci/Dockerfile .      # Rocky Linux
```

Full regression suite:

```bash
docker run --name gpdb7_opt_on --rm -it -e TEST_OS=ubuntu \
  -e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on' installcheck-world" \
  --sysctl "kernel.sem=500 1024000 200 4096" gpdb7_u22:latest \
  /home/gpadmin/gpdb_src/concourse/scripts/ic_gpdb.bash
```

JIT variant (7.x): same command with

```
MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on -c jit=on -c jit_above_cost=0 -c optimizer_jit_above_cost=0 -c gp_explain_jit=off' installcheck"
```

ORCA unit tests, ORCA linter, behave:

```bash
docker run --rm -it gpdb7_u22:latest bash -c "gpdb_src/concourse/scripts/unit_tests_gporca.bash"

docker build -t orca-linter:test -f ci/Dockerfile.linter .
docker run --rm -it orca-linter:test          # requires a CLEAN work tree

IMAGE=greengage7_u22:${BRANCH_NAME} bash ci/scripts/run_behave_tests.bash gpstart gpstop
```

The linter image's entrypoint is
`src/tools/fmt gen && git diff --exit-code && src/tools/fmt chk` with
`CLANG_FORMAT=clang-format-11`; the `git diff --exit-code` in the middle is why a dirty
tree fails the job before any formatting is checked.

6.x delta: `ci/` additionally carries `Dockerfile.centos` and `Dockerfile.rockylinux`,
and lacks `Dockerfile.pg_upgrade` and `Dockerfile.ubuntu.clang-check`.
