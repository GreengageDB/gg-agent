# Review rules R1–R8

Lookup material for [greengage-pg-batch](../SKILL.md). `pg_batch.py classify` implements
these rules; the PR legend that `render` writes summarises them.

## Where the rules come from

The b14–b17 batches of the PG14 sync on `greengage_sync` were reviewed as 607 single-topic
PRs. Every review thread and every defect found later was traced back to the PR that
introduced it, and the rules below are the features that separated PRs with high or
medium findings from the rest. Two consequences:

- The thresholds were fitted **per PR**, and the median PR touched one file with 13 changed
  lines. `classify` therefore applies them **per file** and marks a unit *must review* when
  any of its files trips a rule. Applied to a whole unit, the line counts add up and every
  unit trips them.
- They were fitted on PG14 batches. Treat them as a recommendation to the team and run
  them in shadow mode against the review outcome of each new batch.

## The rules

DIRTY is the merge commit with markers, RAW the green tip, BASE the source branch (`next`),
CUT the last upstream commit, MBASE the merge base of BASE and CUT. A **conflicted file** has
a conflict-marker line at DIRTY and none at BASE. Line comparisons ignore whitespace.

| Rule | Fires on a file when | Measured how |
|---|---|---|
| **R1** day-1 commit | It is code, Greengage changed ≥100 lines of it (MBASE→BASE), and an upstream commit from the inventory's day-1 list changes ≥20 lines of it | `inventory` ranks upstream commits by overlap with Greengage-heavy files; `facts` keeps the top 15 |
| **R2** upstream deleted or moved it | Upstream deleted or renamed a code file Greengage modifies (merge stages 1 and 2 only) | `inventory` must-review list |
| **R3** new lines | A resolution contains ≥3 lines that are on neither side of its conflict | Per hunk: the conflict is re-created with `git merge-file --diff3` from MBASE, BASE and CUT and aligned to the resolved text at RAW |
| **R4** Greengage lines dropped | ≥3 lines of the Greengage side are in neither the resolution nor the merge base | Same alignment |
| **R5** upstream lines dropped | ≥3 lines of the upstream side are in neither the resolution nor the merge base | Same alignment |
| **R6** changes outside the conflicts | ≥6 changed non-blank lines DIRTY→RAW in a conflicted code file, more than 3 lines away from any conflict region | `git diff -U0 DIRTY RAW` |
| **R7** new code after the merge | The same count in a code file that had no conflict; or more than 40 such lines in a unit from commits that all carry `Kind: build-fix` | Build-fix commits are exempt below 40 lines: in b14–b17 the compiler was their reviewer (2 low findings in 48 such PRs) |
| **R8** tests weakened | Expected output gains `ERROR:` lines that upstream does not have (a moved error does not count); crash text appears (`server closed the connection`, `terminated by signal`, `PANIC`, `FailedAssertion`); a test input loses more than 5 statements net; a schedule drops a test upstream keeps, or comments one out | `-- start_ignore` … `-- end_ignore` regions are skipped, as gpdiff skips them; error location suffixes `(file.c:NNN)` and `(segN …)` are normalised away |

Expected-output and generated files are regenerated, not resolved, so R3–R6 never apply to
them; only R8 does.

## The tiers

| Tier | A unit gets it when |
|---|---|
| **must review** | Any file trips any rule. The reasons name the rule and the files |
| **merge automatically** | No rule fires and every file is one of: a clean upstream change to a file Greengage never modified (no conflict, no change after the merge), an AUTO resolution from the inventory, an expected-output or generated file |
| **no review** | Everything else: small resolutions, build fixes, clean upstream changes in Greengage-modified files. CI is the gate |

b1 (`sync-15x-b1`, 31 units): 24 must review, 6 no review, 1 merge automatically. The
rules that fired most were R4 (14 units), R1 (13), R7 (12), R3 and R6 (10 each).
