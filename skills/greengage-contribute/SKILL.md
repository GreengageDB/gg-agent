---
name: greengage-contribute
description: Get a change accepted into GreengageDB/greengage: branch targeting, the CLA, committee review, formatting, linting, regression tests, pull-request CI gates. Covers 6.x/7.x vs the stale main branch, two-approval merges, +1/-1 votes, pgindent policy for inherited code, greengage_schedule, installcheck-world, ABI checks. Use when opening a Greengage pull request, when told "All new features should be submitted against the main branch", when a CLA check fails, or when the ORCA linter fails on `git diff --exit-code`.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Getting a change into Greengage

Two documents in the repo claim to govern contributions, and they disagree.
`CONTRIBUTING.md` is the Greengage-authored one and is authoritative.
The `## Contributing` section of `README.md` (7.x `README.md:208-375`) is inherited
Greenplum text that still mentions Pivotal, `gpdb-dev`, and a mailing list whose link
404s. Read this skill for where they differ; when in doubt, `CONTRIBUTING.md` wins.

## `main` is a dead mirror — target `6.x` or `7.x`

7.x `README.md:313` says:

> All new features should be submitted against the main branch. Bugfixes
> should too be submitted against main unless they only exist in a supported
> back-branch.

**This is wrong.** `main` has not moved since 2026-03-13 and carries nothing of its
own. Evidence, all reproducible:

| Check | Command | Result |
|---|---|---|
| `main` tip | `git log -1 refs/remotes/origin/main` | `9e566a560c1b`, 2026-03-13, subject `Build in Ubuntu 22.04 and 24.04 for 6.x (#312)` |
| `main` is behind `6.x` | `git rev-list --count refs/remotes/origin/main..refs/remotes/origin/6.x` | `227` |
| `main` has no unique commits | `git rev-list --count refs/remotes/origin/6.x..refs/remotes/origin/main` | `0` |
| `main` is an ancestor of `6.x` | `git merge-base --is-ancestor refs/remotes/origin/main refs/remotes/origin/6.x` | true |
| `main` is *not* on the 7 line | `git merge-base --is-ancestor refs/remotes/origin/main refs/remotes/origin/7.x` | false |
| `main` is a 6-line tree | `git show refs/remotes/origin/main:configure.in \| grep PG_PACKAGE_VERSION=` | `9.4.26` (6.x base; 7.x is `12.22`) |

The workflows agree: `.github/workflows/greengage-ci.yml` triggers `push` on
`branches: ['7.x']` / tags `['7.*']` on the 7 line and `branches: ['6.x']` / tags
`['6.*']` on the 6 line. Neither workflow names `main`.

**Rules:**

- A 7-line change targets `7.x`. A 6-line change targets `6.x`.
- A fix that applies to both is submitted **twice**, once per line. That is the
  project's habit — see the paired subjects
  `Report tables and columns removed from Greengage 7 (7.x) (#515)` and
  `... (6.x) (#514)`.
- `next` exists and is the 8.x development line: `.github/workflows/README.md` maps
  `next` to version 8, and `refs/remotes/origin/next` carries `configure.ac` (not
  `configure.in`) declaring `8.0.0-alpha.0` over `PG_PACKAGE_VERSION=14alpha0`. Do
  not target it unless a maintainer asked you to.
- Never trust the branch your clone checked out. `git symbolic-ref
  refs/remotes/origin/HEAD` can still resolve to `refs/remotes/origin/main`.
  Check out the target line explicitly and branch from it.
- `CONTRIBUTING.md:46` is about *your fork*: "create a branch **other than main**".
  That is not permission to target `main` upstream.

## Where the README and CONTRIBUTING.md contradict each other

| Question | README (inherited, 7.x only) | CONTRIBUTING.md (authoritative) |
|---|---|---|
| Target branch | `main` (`README.md:313`) | silent — use `6.x`/`7.x`, see above |
| Who reviews | "core team", peer review, ≥1 `+1` and no `-1` (`README.md:351`) | architectural committee, **two approvals** (`CONTRIBUTING.md:61`) |
| Where to discuss a design | developer's mailing list (`README.md:261`), whose only link — `https://greengagedb.org/community/` at `README.md:222` — returns **404** | open a GitHub issue first (`CONTRIBUTING.md:21`) |
| Minimum local test bar | `make installcheck-world` (`README.md:282`) | "all local test runs are successful" (`CONTRIBUTING.md:38`) |
| Licensing owner | "Pivotal will release it" (`README.md:239`) | Apache-2.0 by the Greengage project (`CONTRIBUTING.md:13`) |

6.x delta: 6.x has no stale section to trip over. Its `README.md:246-248` is a
two-line pointer: `See CONTRIBUTING.md`. The two lines' copies of
`CONTRIBUTING.md` are otherwise the same document, differing only in three hyperlink
targets — the two `NOTICE` links on line 15 and the `README.gpdb` link on line 30,
`blob/7.x/…` on 7.x versus `blob/main/…` on 6.x.

## The CLA check fails on your commit email, not on your account

`README.md:231` links the agreement at `https://cla.greengagedb.org/sign/greengage`
and `README.md:327` names the failure mode outright:

> the most common reason for a failed CLA check is a mismatch between an email
> on file and an email recorded in the commits submitted as part of the pull request.

**Fix the commits, not the form.** Before the first push:

```bash
git config user.email "<the address you signed the CLA with>"
git log --format='%ae%n%ce' <base>..HEAD | sort -u   # every line must be that address
```

If a commit already carries the wrong address, rewrite it — a new commit on top does
not clear the check, because the bot inspects every commit in the PR.

There is **no CLA workflow in the repository**: the only workflow files under
`.github/workflows/` are `greengage-ci.yml`, `greengage-abi-tests.yml`,
`greengage-release.yml`, and (7.x only) `greengage-sql-dump.yml`, alongside a
`README.md`. The CLA check comes from an external app, so you cannot
debug it by reading the repo. `README.md:232-235` mentions an "obvious fixes"
exemption — whose only link is `https://cla.pivotal.io/about#obvious-fixes`, a Pivotal
domain — and immediately advises against relying on it, because the check runs by
default.

## Big patches are not reviewed faster — they are reviewed later

`CONTRIBUTING.md:23`: "Submitting changes in small portions is the best strategy,
even if you are working on a massive feature." Granularity is not a style
preference here; it is the input to the review SLA (`CONTRIBUTING.md:55-57`):

| Patch size | Committee SLA |
|---|---|
| small / easy | up to 1 week |
| medium complexity | up to 4 weeks |
| extra size or complexity | up to 8 weeks |

So a feature split into four small PRs can clear in a month; the same feature as one
changeset can sit for two. Two committee members must approve before merge
(`CONTRIBUTING.md:61`) and they review sequentially — "Once the patch is accepted by
the first reviewer, the second reviewer steps up" (`CONTRIBUTING.md:63`) — so every
extra review round costs a full cycle.

Before a *major* change, open a GitHub issue describing the approach and the reasons
for it and get it validated (`CONTRIBUTING.md:21`). The committee reserves the right
to decline a patch without review (`CONTRIBUTING.md:59`).

Open the pull request as a **Draft** while it is incomplete, and prefix the title
`WIP:` (`README.md:308-311`). Early feedback is explicitly welcomed.

## A feature without a regression test is not reviewable

`CONTRIBUTING.md:36`: "Regression tests are mandatory for every new feature."
Review is explicitly slowed "if tests are missing or copied to incorrect folders"
(`CONTRIBUTING.md:48-50`).

**New regression tests go in `src/test/regress/greengage_schedule`.** Never add a
test to `parallel_schedule`, `serial_schedule`, or any other upstream-inherited
schedule — 7.x `README.md:111-114` states the reason: the inherited schedules are kept
byte-identical to upstream PostgreSQL so that merges from newer PostgreSQL releases
stay clean. Both lines ship the same schedule file names.

Mechanics:

1. `src/test/regress/sql/<name>.sql` and `src/test/regress/expected/<name>.out`.
2. One `test: <name>` line in `src/test/regress/greengage_schedule`, placed in a
   parallel group with tests of similar runtime (the file's own header explains the
   grouping rules, max ~20 per group).
3. `make -C src/test/regress installcheck-tests TESTS="<name>"` to iterate.

**Do not drop your objects at the end of the test.** `src/test/regress/README`:
"Please leave objects behind in the regression database" — the database left by
`installcheck-world` is reused for integration testing of auxiliary tools such as
gpbackup and gpupgrade, and a tidy teardown silently removes their coverage.

## `make installcheck` is not the bar — `make installcheck-world` is

`.github/pull_request_template.md` (6.x: `PULL_REQUEST_TEMPLATE.md` at the repo root)
contains this checkbox:

> - [ ] Pass `make installcheck`

**That checkbox is inherited and wrong.** 7.x `README.md:106-109` says the PostgreSQL
`installcheck` target "does not work either, because some tests are known to fail with
Greengage", and `README.md:99` says plain `make check` never builds a cluster at all.
The real bar is `README.md:282`:

```bash
make installcheck-world
```

against a running cluster, with `export LANG=en_US.UTF-8` set before the cluster was
created (`README.md:117`). Details of building the cluster and running individual
suites are in [greengage-testing](../greengage-testing/SKILL.md) and
[greengage-build](../greengage-build/SKILL.md).

## Formatting: never reformat inherited upstream code

`src/tools/pgindent/README.gpdb` is the policy, and it is a merge-cost argument, not
an aesthetic one: reformatting a file that came from upstream PostgreSQL "would be
merge conflicts when commits from Postgres 8.4 were cherry-picked on top of it".

| File origin | What to run |
|---|---|
| Purely Greengage-added file (e.g. under `src/backend/cdb`, `src/backend/access/appendonly`) | latest pgindent, whole file |
| Inherited upstream file | **nothing** — leave existing lines alone |
| Mixed file | pgindent **only the hunks you added**, with the pgindent version matching the newest PostgreSQL code in that file |

`README.gpdb` says the pgindent binaries "were removed from GPDB". That is stale on
both lines: `src/tools/pgindent/pgindent` (the PostgreSQL Perl driver) ships, and it
demands an external `pg_bsd_indent` of one exact version — `$INDENT_VERSION = "2.1"`
on 7.x, `"1.3"` on 6.x — refusing to run otherwise with
`You do not appear to have pg_bsd_indent version <n> installed on your system.`
`src/tools/pgindent/typedefs.list` ships and is documented as out of date; regenerate
it from your own build before a full run (recipe in `README.gpdb`).

Language entry points, all verified in the tree:

| Language | Tool | Exact invocation |
|---|---|---|
| C, C++ (non-ORCA) | pgindent | `src/tools/pgindent/pgindent --typedefs=src/tools/pgindent/typedefs.list <files>` |
| Perl | perltidy | `src/tools/pgindent/pgperltidy` (7.x). 6.x has no such driver — run `perltidy --profile=src/tools/pgindent/perltidyrc <files>` |
| ORCA / GPOPT C++ | clang-format 10/11 | `src/tools/fmt chk` to check, `src/tools/fmt fmt` to apply, `CLANG_FORMAT=clang-format-11 src/tools/fmt gen` to regenerate configs |
| ORCA C++ static checks | clang-tidy (7.x only) | `src/tools/tidy chk-orca build.debug` — needs a `compile_commands.json` (see `src/backend/gporca/README.tidy.md`) |
| Python | Pylint | `CONTRIBUTING.md:31`; the repo ships **no** `pylintrc`, so defaults apply |
| Go (7.x only) | goimports + gofmt | `make -C gpMgmt/bin/go-tools format`; `make -C gpMgmt/bin/go-tools lint` runs `golangci-lint` |

6.x deltas: no root `.clang-tidy` and no `src/tools/tidy` — `src/tools/fmt` exists on
both lines. There is no `gpMgmt/bin/go-tools` on 6.x, so 6.x has no Go to format.

Whitespace is enforced by `.gitattributes` (`*  whitespace=space-before-tab,trailing-space`,
tab width 4 for `*.[chly]`), so run both of these before pushing:

```bash
git diff --check          # trailing whitespace, space-before-tab, indent-with-non-tab
git diff --color          # recommended by CONTRIBUTING.md:34 and README.md:273
```

Editor settings live in `.editorconfig` (tabs, width 4 for `*.{c,cpp,h,y}`; spaces for
`*.py`; 2 spaces for `*.{dxl,mdp}`), `.dir-locals.el` for Emacs, and
`src/tools/editors/` (`emacs.samples`, `vim.samples`, `clion.xml`). Configure
`git config blame.ignoreRevsFile .git-blame-ignore-revs` so `git blame` skips the ORCA
mass-reformat commits listed there.

## The ORCA linter judges your work tree before it judges your code

`ci/Dockerfile.linter` copies the whole checkout in and runs, verbatim:

```
ENTRYPOINT src/tools/fmt gen && git diff --exit-code && src/tools/fmt chk
```

The middle step means **an unstaged or untracked-in-diff change fails the job before
`fmt chk` ever runs**, and `ci/readme.md` says so: "The work directory must be clean
to pass this test. Please, stage or even commit your changes." A `git diff --exit-code`
failure in that job is therefore usually a dirty tree or a stale generated
`.clang-format`, not a formatting violation in your patch. Reproduce locally:

```bash
docker build -t orca-linter:test -f ci/Dockerfile.linter .
docker run --rm -it orca-linter:test
```

## What actually runs on your pull request

`.github/workflows/greengage-ci.yml` delegates every job to a pinned reusable
workflow in `greengagedb/greengage-ci`. Test jobs are gated on
`if: github.event_name == 'pull_request'`, so **the test suites only ever run on a
PR** — a push to `7.x` builds, packages and uploads, but runs no tests.

| Job | 7.x | 6.x |
|---|---|---|
| `build` | ubuntu | ubuntu 22.04, ubuntu 24.04, Rocky 8, Rocky 9 |
| `behave-tests` | yes | yes |
| `regression-tests` | yes | yes |
| `orca-tests` | yes | yes |
| `resgroup-tests` | yes | yes |
| `jit-tests` | yes | — |
| `coverage` | — | yes (runs only if behave and regression both succeeded) |
| `package` | yes (no event gate) | yes (no event gate) |
| `upload` | push/tag only (`if: github.event_name == 'push'`) | push/tag only |

`greengage-abi-tests.yml` runs on every pull request on both lines (jobs
`abi-dump-setup`, `abi-dump`, `abi-compare`) and diffs your build's `postgres` ABI
against the newest tag on the line — newest *non-prerelease* tag on 7.x, which filters
with `grep -v '-'`; 6.x omits that filter and takes the newest `6.*` tag as-is. See
[reference/pr-checks.md](reference/pr-checks.md) for the ABI failure procedure and how
to reproduce each suite locally, and [greengage-ci](../greengage-ci/SKILL.md) for the
pipeline itself.

Two gates are invisible in the workflow files:

- **First-run approval.** `CONTRIBUTING.md:67`: "After basic review (including feature
  relevancy, absence of malicious changes, etc.) and approve to run CI pipelines, the
  processes of patch review begins." A new contributor's PR shows *no* checks until a
  maintainer approves the run. Zero checks is not a broken pipeline.
- **Which checks are required** is branch-protection configuration, not repo content.
  `.github/workflows/README.md` warns that adding, removing, or renaming a required
  job name needs a repository administrator to update the Branch Protection Rules.
  Do not rename a job in a drive-by commit.

`.github/CODEOWNERS` maps `/.github/ @GreengageDB/ci` on both lines: touching anything
under `.github/` auto-requests review from the CI team and adds a reviewer you did not
plan for.

## Branch names, PR titles, and what the merge produces

Branch naming actually used on the upstream remote — counts from
`git for-each-ref refs/remotes/origin/`, 64 branches excluding `HEAD`:

| Pattern | Count | Example |
|---|---|---|
| `GG-<n>` | 39 | `GG-410`, `GG-410-v2`, `GG-212_python311` |
| `ADBDEV-<n>` | 8 | `ADBDEV-9772`, `ADBDEV-9083-full-rollback` |
| `CI-<n>` | 7 | `CI-5955` |
| `feature/<name>` | 3 | `feature/aocs_optimization` |

Pick `GG-<issue>` when you have a Greengage issue number, otherwise
`feature/<short-name>`. The name is cosmetic — nothing in CI parses it.

PRs land squashed with the PR number appended to the subject, e.g.
`Fix scan for AO table without columns (#512)` — 32 of the last 50 subjects on `7.x`
end in `(#NNN)`; the remainder are upstream PostgreSQL cherry-picks and true merge
commits, not PR merges. **Your PR title becomes the permanent commit subject**, so
write it as an imperative one-line summary of the change, not as a ticket reference.

## Licensing: keep every header you did not write

- Original work is released under **Apache-2.0**; a patch valuable upstream may
  additionally be offered under the PostgreSQL license (`CONTRIBUTING.md:13`).
- Third-party code must be under an Apache
  [Category A](https://www.apache.org/legal/resolved.html#category-a) compatible
  license, and some of those require attribution in the repo's `NOTICE` file
  (`CONTRIBUTING.md:15`; `NOTICE` is 604 lines of exactly such entries on 7.x,
  2309 on 6.x).
- **Never strip a licensing header** from work that is not yours, even when you
  reuse only part of a file (`CONTRIBUTING.md:17`).
- Changes to functionality shared with PostgreSQL may be sent upstream first
  (`CONTRIBUTING.md:42`); keep a PostgreSQL checkout handy to check whether your
  fix belongs there.

Security problems never go through a pull request or a GitHub issue. `SECURITY.md`:
"**IMPORTANT: Do not file public issues on GitHub for security vulnerabilities!**" —
mail `security@greengagedb.org`. Conduct complaints go to `code@greengagedb.org`
(`CODE-OF-CONDUCT.md`; 6.x keeps the same document at `.github/CODE_OF_CONDUCT.md`).

## What not to do

| Do not | Why |
|---|---|
| Target `main` | 227 commits behind `6.x`, zero commits of its own, no CI trigger |
| Follow the README's mailing-list advice | `https://greengagedb.org/community/` returns 404; the "gpdb-dev" list is Greenplum's |
| Tick "Pass `make installcheck`" literally | that target is documented as broken here; run `make installcheck-world` |
| Add a test to `parallel_schedule` | breaks future PostgreSQL merges; use `greengage_schedule` |
| pgindent a whole inherited file | generates merge conflicts with upstream cherry-picks |
| Run `hooks/install` | it installs `hooks/pre-push`, which only warns about `concourse/pipelines/*.yml` — legacy Greenplum CI, not the GitHub Actions pipeline that gates your PR |
| Rename or delete a CI job casually | required-check names live in branch protection; an admin must re-point them |
| Expect the blog "Pull Request Submission Guidelines" to hold the rules | `https://greengagedb.org/en/blog/contributing.html` resolves but points back at the repo's `CONTRIBUTING.md` |
| Push a fix-up commit to clear a CLA failure | the check reads every commit; rewrite the author email instead |

## Reference

- [reference/pre-submit-checklist.md](reference/pre-submit-checklist.md) — the ordered
  gate list with exact commands.
- [reference/pr-checks.md](reference/pr-checks.md) — CI job inventory per line, the ABI
  check procedure, local reproduction commands.
- [reference/governance-files.md](reference/governance-files.md) — where every
  governance and tooling file lives on 7.x and 6.x, and which are stale.

See also: [greengage-build](../greengage-build/SKILL.md),
[greengage-testing](../greengage-testing/SKILL.md),
[greengage-ci](../greengage-ci/SKILL.md),
[greengage-answer-files](../greengage-answer-files/SKILL.md),
[greengage-overview](../greengage-overview/SKILL.md)
