# Governance and tooling files, 7.x vs 6.x

Paths verified with `git ls-tree` against `refs/remotes/origin/7.x` and
`refs/remotes/origin/6.x` of `GreengageDB/greengage`.

## Process documents

| File | 7.x | 6.x | Status |
|---|---|---|---|
| `CONTRIBUTING.md` | yes | yes | **Authoritative.** Same document on both lines; only three hyperlink targets differ — the two `NOTICE` links on line 15 and the `README.gpdb` link on line 30 (`blob/7.x/…` vs `blob/main/…`) |
| `README.md` `## Contributing` | lines 208-375, full inherited Greenplum text | lines 246-248, a pointer to `CONTRIBUTING.md` | 7.x copy is **stale**: names Pivotal, `gpdb-dev`, a 404 mailing-list link, and `main` as the target branch |
| `CODE-OF-CONDUCT.md` | repo root | `.github/CODE_OF_CONDUCT.md` | byte-identical on both lines; report to `code@greengagedb.org` |
| `SECURITY.md` | repo root | — | current; report to `security@greengagedb.org`, never as a public issue |
| `LICENSE` | Apache-2.0 | Apache-2.0 | current |
| `COPYRIGHT` | yes | yes | "Copyright (c) 2025 Greengage Community"; PostgreSQL and Greenplum notices follow |
| `NOTICE` | 604 lines | 2309 lines | third-party attribution; add an entry when a Category A license requires one |

## GitHub templates

| Purpose | 7.x path | 6.x path |
|---|---|---|
| Pull request template | `.github/pull_request_template.md` | `PULL_REQUEST_TEMPLATE.md` (repo root) |
| Bug report | `.github/ISSUE_TEMPLATE/bug_report.yml` | same |
| Feature request | `.github/ISSUE_TEMPLATE/feature_request.md` | same |
| Generic issue form | — | `.github/issue_template.md` |
| Code owners | `.github/CODEOWNERS` | same |

Both lines' PR template is five checkboxes, one of which — `Pass \`make installcheck\`` —
names a target the README documents as broken. Use `make installcheck-world`.

`bug_report.yml` requires: problem description, reproduction steps, expected behaviour,
GreengageDB version, and server OS. Optional but valuable: SQL + schema, and segment
log directories (the form warns that logs can contain confidential information).

## Style and editor configuration

| File | 7.x | 6.x | Contents |
|---|---|---|---|
| `.editorconfig` | yes | yes | tabs width 4 for `*.{c,cpp,h,y}`, makefiles and `*.mk`; 4 spaces for `*.py`; 2 spaces for `*.{dxl,mdp}` |
| `.dir-locals.el` | yes | yes | Emacs: `c-file-style "bsd"`, `c-basic-offset 4`, `fill-column 78`, tabs on |
| `.gitattributes` | yes | yes | whitespace policy per extension; `git diff --check` enforces it |
| `.git-blame-ignore-revs` | yes | yes | ORCA/GPOPT mass-reformat commits; enable with `git config blame.ignoreRevsFile .git-blame-ignore-revs` |
| `.clang-tidy` | yes | — | ORCA check set, `WarningsAsErrors: '*'`, `HeaderFilterRegex: 'gpdbcost\|gpopt\|gpos\|naucrates'` |
| `src/tools/editors/` | yes | yes | `emacs.samples`, `vim.samples`, `clion.xml` |

## Formatting and linting entry points

| Path | 7.x | 6.x | Notes |
|---|---|---|---|
| `src/tools/pgindent/pgindent` | yes | yes | PostgreSQL Perl driver; needs an external `pg_bsd_indent` of a **specific** version - `$INDENT_VERSION = "2.1"` on 7.x, `"1.3"` on 6.x, and the script aborts with `You do not appear to have pg_bsd_indent version <n> installed` |
| `src/tools/pgindent/README.gpdb` | yes | yes | **the policy**: do not reformat inherited upstream code |
| `src/tools/pgindent/typedefs.list` | yes | yes | shipped deliberately out of date; regenerate from your own build |
| `src/tools/pgindent/exclude_file_patterns` | yes | yes | files pgindent skips |
| `src/tools/pgindent/pgperltidy` | yes | **no** | Perl formatting driver; on 6.x only `perltidyrc` ships, so run `perltidy --profile=src/tools/pgindent/perltidyrc` yourself |
| `src/tools/pgindent/perltidyrc` | yes | yes | max line 78, tabs 4 |
| `src/tools/pgindent/indent.bsd.patch` | — | yes | 6.x-only patch for the BSD indent source |
| `src/tools/fmt` | yes | yes | ORCA/GPOPT clang-format driver: `gen`, `fmt`, `chk` |
| `src/tools/tidy` | yes | — | ORCA clang-tidy driver: `chk-orca <builddir>`, `chk-gpopt <vpath>` |
| `src/backend/gporca/README.format.md` | yes | yes | clang-format version policy and editor integrations |
| `src/backend/gporca/README.tidy.md` | yes | — | how to generate `compile_commands.json` for tidy |
| `src/backend/gporca/StyleGuide.md` | yes | yes | ORCA C++ style |
| `ci/Dockerfile.linter` | yes | yes | containerised ORCA format check; requires a clean work tree |
| `gpMgmt/bin/go-tools/Makefile` | yes | — | `format` (goimports + gofmt), `lint` (golangci-lint) |

No `pylintrc` and no `pyproject.toml` exists on either line, and neither line has a
repo-level `setup.cfg` (6.x carries two, but both are inside vendored packages under
`gpMgmt/bin/pythonSrc/`), so `CONTRIBUTING.md:31`'s Pylint requirement runs with tool
defaults.

## Repository features that are NOT part of the contribution path

| Path | Why to ignore it |
|---|---|
| `hooks/install`, `hooks/pre-push` | installs a hook that only warns about `concourse/pipelines/*.yml` — legacy Greenplum CI, unrelated to the GitHub Actions checks that gate your PR |
| `concourse/` | legacy Greenplum pipeline. Its `concourse/scripts/*.bash` are still invoked by `ci/`, but no Concourse pipeline gates a Greengage pull request |
| `.travis.yml` | inherited; not a check on your PR |
| `README.git`, `README.PostgreSQL` | inherited PostgreSQL files |
| `https://greengagedb.org/community/` | linked from `README.md:222`; returns 404 |
| `https://greengagedb.org/en/blog/contributing.html` | returns 200, but the "Pull Request Submission Guidelines" it names are a link to `https://github.com/GreengageDB/greengage?tab=contributing-ov-file#readme` — i.e. back to the repo's `CONTRIBUTING.md`. There are no commit-message or PR-body format rules anywhere else |

## Branch naming actually used upstream

64 remote branches on `GreengageDB/greengage`, counted with
`git for-each-ref refs/remotes/origin/` and excluding the `HEAD` symref:

| Pattern | Count |
|---|---|
| `GG-<n>` (incl. `GG-<n>-v2`, `GG-<n>_python311`) | 39 |
| `ADBDEV-<n>` (incl. `-full-rollback`, `_2` suffixes) | 8 |
| `CI-<n>` | 7 |
| `feature/<name>` | 3 |
| line branches: `6.x`, `7.x`, `next`, `main` | 4 |
| everything else (`merge_queue`, one-off names) | 3 |
