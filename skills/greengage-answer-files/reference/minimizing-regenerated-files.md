# Minimizing regenerated answer files

Lookup material for [greengage-answer-files](../SKILL.md), procedure step 5. A regenerated
`expected/*.out` usually carries far more change than gpdiff needs: reordered rows of
unordered results, `Optimizer:`/`Settings:` lines, `DISTRIBUTED BY` notices, `(segN … pid=N)`
tails. Two scripts under `${CLAUDE_PLUGIN_ROOT}/scripts/` remove that churn without changing
what the test asserts.

## gpdiff_min.py: keep only the hunks gpdiff needs

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gpdiff_min.py -o /tmp/gm <merge-base> <pr-head>      # every */expected/*.out changed
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gpdiff_min.py -o /tmp/gm -r results/ -r results-orca/ \
    <merge-base> <pr-head> src/test/regress/expected/inherit.out
cp /tmp/gm/fin/src/test/regress/expected/inherit.out src/test/regress/expected/inherit.out
```

| Step | What it does |
|---|---|
| 1. Put hunks back | Every hunk of BASE..HEAD returns to its BASE side unless gpdiff (with HEAD's init files) then sees a difference from the HEAD file. The rows of one `(N rows)` result go back together, then single hunks, then windows of 2–8 hunks (a moved row is a delete and an insert) |
| 2. Strip added lines | `strip_gpdiff_ignored.pl` removes what gpdiff ignores, but only from lines the change **adds**; lines kept from BASE stay byte-for-byte, so the file stays consistent with the rest of the tree |
| 3. Verify | `DIFFERS FROM HEAD` on a file means gpdiff no longer accepts the result as equal to HEAD: do not copy that file. With `-r`, the result is also compared with real pg_regress output (`X_optimizer.out` against a results dir whose path contains `orca`): `MISMATCH` means the minimized file fails where HEAD passed |

Conflict markers must stay exactly as in HEAD, so the script also works on the unit branches
of a batch whose base still has markers ([greengage-pg-batch](../../greengage-pg-batch/SKILL.md)).
Init files are read at HEAD: `src/test/regress/init_file` always,
`src/test/isolation2/init_file_isolation2` for isolation2 files, plus any `-i <path>`.
`-C <checkout>` runs it outside the source tree; gpdiff.pl comes from that checkout.

Output, per file: `hunks H, kept K, stripped S; lines changed A -> B`. `OUTDIR` holds `base/`,
`head/`, `min/` (after step 1) and `fin/` (the result) at repository paths.

## strip_gpdiff_ignored.pl: strip a whole file

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/strip_gpdiff_ignored.pl -n src/test/regress/expected/foo.out   # dry run
${CLAUDE_PLUGIN_ROOT}/scripts/strip_gpdiff_ignored.pl src/test/regress/expected/foo.out
```

In place, it removes `-- start_ignore` … `-- end_ignore` blocks with their markers, lines
starting with `HINT:`, `CONTEXT:` or `GP_IGNORE:`, lines matched by a `matchignore` rule of
atmsort.pm or the init files, and the text a `matchsubs` rule deletes. It keeps continuation
lines of multi-line CONTEXT messages and DETAIL lines, which gpdiff compares. Use it on a file
you write from scratch; on an existing file prefer `gpdiff_min.py`, which strips only the
lines you added. Rerun the test afterwards either way.

| Trap | Consequence |
|---|---|
| The product name in atmsort.pm's referential-integrity rule differs by branch (`Greenplum Database` on greengage_sync, `Greengage Database` on 6.x/7.x) | The script matches both; a hand-written copy of the rule matching one silently keeps the other |
| A `matchsubs` that rewrites rather than deletes | Not applied: only `s/X//` rules are, so a masked value stays in the file as written |
| Running it over a file another change regenerated wholesale | Every gpdiff-ignored line in the file goes, existing ones included: churn for the reviewer |
