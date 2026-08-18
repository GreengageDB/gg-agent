---
description: Fetch a failed Greengage CI run's artifacts and classify every failure as cosmetic, real, or flaky
argument-hint: "[run URL, run id, PR number, or branch]"
---

Triage the CI failure for: $ARGUMENTS

Load the **greengage-ci** skill — it owns the job matrix, the artifact layout, and the
classification taxonomy. This command drives that method.

## Procedure

1. **Find the run.** With no argument, use the most recent failed run on the current
   branch. Use `gh` for everything (`gh run list`, `gh run view`, `gh pr checks`) — it
   handles authentication, and hand-rolled API calls will fail on a private repo.

2. **Identify which jobs failed and what each one actually runs.** The job matrix is
   version-dependent, and a failure means different things in a behave job than in a
   regression job. Get this from the skill, not from the job name alone.

3. **Fetch the evidence, not the summary.** Download the run's artifacts and work from the
   real `regression.diffs` and result files. A job log tail is not enough to classify a
   failure, and guessing from a test name is how a real bug gets waved through as
   cosmetic.

4. **Split and classify each failing test** using the skill's taxonomy:
   **COSMETIC** (plan-shape drift, message drift, row order without `ORDER BY`, statistics
   drift), **REAL** (wrong values, missing or extra rows, unexpected `ERROR`/`PANIC`/
   assertion failure, a connection dropping, a previously-succeeding statement now
   erroring), **FLAKY** (rotating between runs), **HELD** (output is correct but coverage
   was silently lost — for example a plan that stopped using partition elimination).

5. **Adversarially re-verify every REAL and every uncertain verdict** before reporting it.
   Try to prove each one is actually cosmetic; the ones that survive are the findings.
   Spot-check the cosmetic pile too — that is where a real bug hides.

6. **Check for cross-job damage.** All the regression jobs compare against the same
   expected files, so a change that greens one job can redden another. If the run followed
   an answer-file change, check the sibling jobs specifically.

## Report

A table of failing test, job, verdict, and one line of evidence. Then, for each REAL
finding, the failing input and the observed-versus-expected behaviour. Recommend the next
action per finding — code fix, answer-file regeneration
(**greengage-answer-files**, and only after its safety gate passes), or rerun-to-confirm —
and say which failures you could not reproduce locally and why.

Do not push commits or re-run CI without being asked.
