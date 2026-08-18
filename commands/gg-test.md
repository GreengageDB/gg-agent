---
description: Run a Greengage regression test or suite with the right target, optimizer and environment
argument-hint: "<test name, suite, or 'all'>"
---

Run: $ARGUMENTS

Load the **greengage-testing** skill — it owns the target selection, the environment
requirements, and the traps that make a run lie to you. Do not assemble a `pg_regress`
command line from memory.

## Procedure

1. **Establish which branch line you are on** (7.x or 6.x). The available targets differ,
   and so does the build that the tests need. Check `configure.in` / `VERSION` rather than
   assuming.

2. **Confirm a cluster is running and the environment is sourced.** Tests run against an
   existing cluster; a missing environment produces failures that look like code bugs. If
   there is no cluster, use `/gg-cluster-up` first.

3. **Pick the target from the skill's inventory**, not by pattern-matching a make target
   name. In particular: `make check` and plain `make installcheck` do not do what their
   PostgreSQL names suggest here.

4. **Decide the optimizer axis.** Greengage runs its regression suites under both GPORCA
   and the PostgreSQL planner, and they compare against different expected files. If the
   user did not say which, run the planner path first — its failures are easier to read —
   and say that is what you did.

5. **Run it**, capturing output to a file. A full schedule takes tens of minutes: run it
   detached and poll rather than blocking a single call on the whole run.

## Judge the result correctly

- **A pass is an empty `regression.diffs`.** A green summary line is not sufficient
  evidence, and neither is a zero exit status.
- A single-test run against an existing database is **not authoritative** — test pollution
  and missing setup dependencies both fake failures. Confirm anything surprising with the
  schedule run that builds its own database.
- Before calling a failure a bug, rerun it. Greengage has known-flaky classes and the skill
  lists them; a rotating failure must never be "fixed" by regenerating its answer file.

## Report

Which target and optimizer you ran, the pass/fail tally, and for each failure the test
name plus the relevant hunk of `regression.diffs` — not a paraphrase of it. Classify each
failure as likely-real, likely-cosmetic, or flaky, and hand off: **greengage-answer-files**
for a cosmetic diff, **greengage-debug** for a crash or wrong result.
