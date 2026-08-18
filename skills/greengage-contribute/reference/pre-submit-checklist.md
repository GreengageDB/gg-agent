# Pre-submit checklist

Ordered gates. Every command was read out of `refs/remotes/origin/7.x`; 6.x deltas are
called out per row. Run them from the repository root.

## 0. Identity and base

| Gate | Command | Pass condition |
|---|---|---|
| CLA email matches every commit | `git log --format='%ae%n%ce' <base>..HEAD \| sort -u` | one address, the one on file at `https://cla.greengagedb.org/sign/greengage` (linked from `README.md:231`) |
| Base is a live line | `git merge-base --is-ancestor refs/remotes/origin/7.x HEAD` | true for a 7-line change; use `6.x` for a 6-line change. **Never `main`.** |
| Branch name | — | `GG-<issue>`, or `feature/<short-name>`; `CI-<n>` for pipeline work |

## 1. Build

| Line | Commands |
|---|---|
| 7.x | `git submodule update --init` → `./configure --with-perl --with-python --with-libxml --with-gssapi --prefix=/usr/local/gpdb` → `make -j8` → `make -j8 install` |
| 6.x | `git submodule update --init --recursive --force` → `make GPROOT=~/build PARALLEL_MAKE_OPTS=-j8 devel -C gpAux` (the `devel` target is a debug build and is required for regression tests) |

Then `source <prefix>/greengage_path.sh`. `.gitmodules` on 7.x declares one submodule,
`gpcontrib/gpcloud/test/googletest`; 6.x declares three — that one plus
`gpAux/extensions/pgbouncer/source` and `gpMgmt/bin/pythonSrc/PyGreSQL-5.2.5`, which is
why the 6.x command needs `--recursive`.

## 2. Cluster and tests

```bash
export LANG=en_US.UTF-8            # README.md:116-117 - tests need a UTF-8 locale
make create-demo-cluster
source gpAux/gpdemo/gpdemo-env.sh  # without this, gp* utilities abort
make installcheck-world            # README.md:282 - the documented minimum bar
```

| Do not run | Why |
|---|---|
| `make check` | never builds a cluster (`README.md:99-104`) |
| `make installcheck` | includes tests known to fail on Greengage (`README.md:106-109`), even though the PR template's checkbox names it |

Iterating on one test:
`make -C src/test/regress installcheck-tests TESTS="<name>"`.

## 3. Tests you added

| Gate | Requirement |
|---|---|
| Location | `src/test/regress/sql/<name>.sql` + `src/test/regress/expected/<name>.out` |
| Registration | one `test: <name>` line in `src/test/regress/greengage_schedule` |
| Never | the upstream-inherited PostgreSQL schedules `parallel_schedule` and `serial_schedule`; nor the special-purpose ones (`minimal_schedule`, `mirrorless_schedule`, `standby_schedule`, `icudp_schedule`), which each drive one specific cluster configuration |
| Grouping | put the test in a parallel group of similar runtime, max ~20 per group (rules in the schedule file's own header) |
| Teardown | leave objects behind — `src/test/regress/README`: "Please leave objects behind in the regression database", it is reused by gpbackup/gpupgrade integration tests |
| Isolation/concurrency tests | `src/test/isolation2/`, session syntax documented in `sql_isolation_testcase.py` |
| Management-utility behaviour | `gpMgmt/test/behave/mgmt_utils/*.feature` |

## 4. Formatting

| Change touches | Command |
|---|---|
| Greengage-only C file | pgindent it: `src/tools/pgindent/pgindent --typedefs=src/tools/pgindent/typedefs.list <file>` (needs a `pg_bsd_indent` binary you supply) |
| Inherited upstream C file | reformat nothing; hand-match surrounding style |
| Mixed file | pgindent only your added hunks, with the pgindent version matching the newest PostgreSQL code in that file |
| Perl | `src/tools/pgindent/pgperltidy` (7.x); on 6.x run `perltidy --profile=src/tools/pgindent/perltidyrc <files>` |
| ORCA / GPOPT C++ | `src/tools/fmt chk`, fix with `src/tools/fmt fmt` |
| ORCA static checks (7.x only) | `src/tools/tidy chk-orca build.debug` |
| Python | Pylint (no `pylintrc` in the tree; defaults apply) |
| Go (7.x only) | `make -C gpMgmt/bin/go-tools format` then `make -C gpMgmt/bin/go-tools lint` |
| Anything | `git diff --check` and `git diff --color` (`CONTRIBUTING.md:34`, `README.md:273`) |

`src/tools/fmt` and `src/tools/tidy` operate on `git ls-files` output, so an untracked
new file is skipped by both until you `git add` it.

## 5. Pull request body

| Gate | Source |
|---|---|
| Tests added | `.github/pull_request_template.md` checkbox 1 (6.x: `PULL_REQUEST_TEMPLATE.md` at repo root) |
| Documentation changes described | checkbox 2 |
| Local test run passed | checkbox 4 — read it as `make installcheck-world`, not `make installcheck` |
| Reviewed someone else's PR in return | checkbox 5 |
| Title reads as a commit subject | merges are squashed and the PR number is appended, e.g. `Fix scan for AO table without columns (#512)` |
| Draft + `WIP:` prefix if incomplete | `README.md:308-311` |
| Bug affecting both lines | open one PR per line, mirroring the `(7.x)` / `(6.x)` subject convention |

## 6. Legal

| Gate | Rule |
|---|---|
| Original work | released under Apache-2.0 (`CONTRIBUTING.md:13`) |
| Third-party code | must be Apache [Category A](https://www.apache.org/legal/resolved.html#category-a) compatible (`CONTRIBUTING.md:15`) |
| Attribution | add a `NOTICE` entry where the third-party license requires it |
| Headers | never strip a licensing header you did not write (`CONTRIBUTING.md:17`) |
| Security bug | do **not** open a PR or issue — mail `security@greengagedb.org` (`SECURITY.md`) |
