# Greengage CI workflow inventory

Read from `refs/remotes/origin/7.x` and `refs/remotes/origin/6.x` of
`GreengageDB/greengage`, `.github/workflows/`. Pinned reusable-workflow tags are the ones
in the branch at the time of reading — re-read the YAML before quoting a version.

## Files present

| File | 7.x | 6.x |
|---|---|---|
| `.github/workflows/greengage-ci.yml` | yes | yes |
| `.github/workflows/greengage-abi-tests.yml` | yes | yes |
| `.github/workflows/greengage-release.yml` | yes | yes |
| `.github/workflows/greengage-sql-dump.yml` | yes | **no** |
| `.github/workflows/README.md` | yes | yes (shorter, no SQL-dump section) |
| `.github/CODEOWNERS` | `/.github/ @GreengageDB/ci` | same |

`concourse/` in the repo root is legacy Greenplum CI. It still contains
`concourse/pipelines/pr_pipeline.yml`, which is a Concourse pipeline definition and is
**not** what gates a GitHub pull request — nothing in the repo triggers it. Its
`concourse/scripts/*.bash` are live, though: `ci/readme.md` and `ci/scripts/*` execute
`ic_gpdb.bash`, `common.bash`, `setup_gpadmin_user.bash` and `unit_tests_gporca.bash`
inside the container.

## `greengage-ci.yml` — triggers

```yaml
on:
  push:
    branches: ['7.x']    # 6.x branch: ['6.x']
    tags:     ['7.*']    # 6.x branch: ['6.*']
  pull_request:
    branches: ['**']
concurrency:
  group: ${{ github.workflow }}-${{ github.event_name == 'pull_request'
             && github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
```

Every test job additionally carries `if: github.event_name == 'pull_request'`.
`upload` carries `if: github.event_name == 'push'`. `build` and `package` have no `if`.
All matrices use `fail-fast: false`, so sibling legs keep running when one fails.

## 7.x jobs

| Job | `needs` | Gate | Reusable workflow | Matrix |
|---|---|---|---|---|
| `build` | — | none | `greengage-reusable-build.yml@v33` | `target_os: [ubuntu]` |
| `behave-tests` | build | PR | `greengage-reusable-tests-behave.yml@v35` | `[ubuntu]` |
| `regression-tests` | build | PR | `greengage-reusable-tests-regression.yml@v28` | `[ubuntu]` |
| `orca-tests` | build | PR | `greengage-reusable-tests-orca.yml@v28` | `[ubuntu]` |
| `resgroup-tests` | build | PR | `greengage-reusable-tests-resgroup.yml@v31` | `[ubuntu]` |
| `jit-tests` | build | PR | `greengage-reusable-tests-jit.yml@v28` | `[ubuntu]` |
| `upload` | build | push | `greengage-reusable-upload.yml@v28` | `[ubuntu]` |
| `package` | build | none | `greengage-reusable-package.yml@v44` | ubuntu, `test_docker: ubuntu:22.04` |

All pass `version: 7`. Secrets: `ghcr_token: ${{ secrets.GITHUB_TOKEN }}`; `upload` also
takes `DOCKERHUB_TOKEN` / `DOCKERHUB_USERNAME`.

## 6.x jobs

| Job | `needs` | Gate | Reusable workflow | Matrix |
|---|---|---|---|---|
| `build` | — | none | `greengage-reusable-build.yml@v42` | ubuntu (22.04), ubuntu 24.04, rockylinux 8, rockylinux 9 |
| `behave-tests` | build | PR | `-tests-behave.yml@v46` | ubuntu (22.04), ubuntu 24.04 |
| `regression-tests` | build | PR | `-tests-regression.yml@v46` | ubuntu 24.04 only |
| `coverage` | behave-tests, regression-tests | PR **and both `== 'success'`** | `greengage-reusable-coverage.yml@v46` | ubuntu 24.04, `coverage_threshold: 75` |
| `orca-tests` | build | PR | `-tests-orca.yml@v28` | `[ubuntu]` |
| `resgroup-tests` | build | PR | `-tests-resgroup.yml@v31` | ubuntu 24.04 |
| `upload` | build | push | `-upload.yml@v28` | ubuntu, ubuntu 24.04 |
| `package` | build | none | `greengage-reusable-package.yml@v47` | ubuntu + ubuntu 24.04 (`test_install: true`), rockylinux 8 + 9 (`test_install: false`) |

All pass `version: 6`.

`target_os_version` convention (from `.github/workflows/README.md`): for `ubuntu`, **omit**
the version to mean 22.04 — passing `"22.04"` explicitly breaks artifact-name backward
compatibility. Only `greengage-release.yml` is exempt, because it needs unambiguous cache
keys.

## What the branch README says each stage does

- **Build** — builds and pushes Docker images to GHCR tagged with the commit SHA and the
  branch name. Runs for PRs and all push events.
- **Tests** — behave, regression, orca, resource group, and (7.x only) JIT. Pull requests
  only.
- **Upload** — retags and pushes final images to GHCR and optionally DockerHub. Push to the
  default branch retags to `latest`.
- **Package** — Debian packages, optional deployment test. (The 7.x README claims this is
  6.x-only; the 7.x YAML disagrees and defines the job. Trust the YAML.)

DockerHub credentials are mandatory for `greengagedb/greengage` — a login failure stops the
workflow. For forks they are optional and a failure only skips the DockerHub upload.

## Image naming

`greengage-sql-dump.yml` constructs the image name CI produced:

```
ghcr.io/${{ github.repository }}/ggdb${VERSION}_${TARGET_OS}${TARGET_OS_VERSION}:${SHA}
```

lowercased — e.g. `ghcr.io/greengagedb/greengage/ggdb7_ubuntu:<sha>` and
`ghcr.io/greengagedb/greengage/ggdb6_ubuntu24.04:<sha>`. Pulling that tag reproduces the
exact binaries a job ran.

## `greengage-abi-tests.yml`

Triggers: `workflow_dispatch` and `pull_request: ['**']`. Three jobs on `ubuntu-22.04`.

1. `abi-dump-setup` — picks the baseline as the highest matching tag from
   `git ls-remote --tags --refs --sort='v:refname' https://github.com/GreengageDB/greengage.git '7.*' | grep -v '-' | tail -n 1`;
   the `grep -v '-'` is 7.x-only, so on 6.x a `-rc`/`-alpha` tag can become the baseline.
   Uploads `.abi-check/<BASELINE_VERSION>/` as the `exception_lists` artifact when that
   directory is non-empty.
2. `abi-dump` — matrix `build-baseline` / `build-latest`. Configures with
   `CFLAGS='-gdwarf-4 -Og -g3 -Wno-maybe-uninitialized'`, `--prefix=/usr/local/greengage-db-devel`,
   then `abi-dumper -lver <ref> -skip-cxx -public-headers …/include/. -o postgres-<ref>.abi
   …/bin/postgres`.
3. `abi-compare` — `abi-compliance-checker -lib postgres -old … -new …`, honouring
   `-skip-symbols exception_lists/postgres.symbols.ignore` and
   `-skip-types exception_lists/postgres.types.ignore` when present. Dumps the HTML report
   through `lynx -dump` into the log and uploads `compat-report-<sha>`.

Suppressing a deliberate, safe ABI break means adding the symbol or type to
`.abi-check/<baseline version>/postgres.symbols.ignore` or `postgres.types.ignore`, one per
line, `struct` prefix required for struct types. Procedure and screenshots:
`.abi-check/README.md`. 7.x baselines present: `7.0.0`, `7.1.0`, `7.2.0-rc.1`, `7.3.0`,
`7.4.0`, `7.4.1`.

## `greengage-release.yml`

Trigger `release: types: [released]`. Runs on `ubuntu-24.04`, uses
`greengagedb/greengage-ci/.github/actions/upload-pkgs-to-release@v38` with
`extensions: deb ddeb`, `package_dir: deb-packages`. 7.x has one matrix entry (ubuntu
22.04); 6.x has two (22.04 and 24.04). Packages are restored from the build cache keyed on
OS + commit SHA — on a cache miss the workflow reports how to re-trigger the build by hand
rather than triggering it (deliberate, to avoid loops).

## `greengage-sql-dump.yml` (7.x only)

Trigger `workflow_run: workflows: ["Greengage CI"], types: [completed]`, branches `6.x`,
`7.x`, `next`; runs only when the triggering run was a `push` with conclusion `success`.
Maps branch to version (`6.x`→6, `7.x`→7, `next`→8) and to `TARGET_OS_VERSION`
(`6.x`→`24.04`, otherwise empty). Pulls the GHCR image with `continue-on-error: true` —
**a missing image silently skips the dump instead of failing the job**. Then runs
`greengagedb/greengage-ci/.github/actions/tests/regression@v26` with `optimizer: postgres`
and `dump_db: "true"`, producing `/mnt/logs/<os><ver>_postgres_sqldump.tar`, uploaded as
`sqldump_ggdb<version>_<os><ver>`. A final `verify-dumps-created` job queries the jobs API
and fails if no `Upload SQL Dump` step succeeded. The artifact is consumed by the behave
gpexpand tests, and each download resets its 90-day retention.

## Where the test commands actually live

Not in this repo. The reusable workflows are in `greengagedb/greengage-ci`, documented in
that repo under `README/`: `REUSABLE-BUILD.md`, `REUSABLE-PACKAGE.md`,
`REUSABLE-TESTS-BEHAVE.md`, `REUSABLE-TESTS-ORCA.md`, `REUSABLE-TESTS-REGRESSION.md`,
`REUSABLE-TESTS-RESGROUP.md`, `REUSABLE-UPLOAD.md`. What they invoke inside the container
is this repo's `concourse/scripts/ic_gpdb.bash` (+ `common.bash`) and
`ci/scripts/*.bash` — read those, or read the echoed command in the job log.
