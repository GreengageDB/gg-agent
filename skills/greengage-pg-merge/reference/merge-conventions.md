# Conventions for a reviewable bump: scope, lookahead, decisions, commits, tests

Lookup material for [greengage-pg-merge](../SKILL.md). The rules here were distilled from
the PG14 b16 sync on `greengage_sync` (2026-08/09), where the same upstream target
(`8ff1c94649f`, the PG14 feature freeze) was merged twice onto the same base
(`66db164a289`): once by a single AI session as one merge commit plus five fix commits
(`sync-14x-b16-ai`, PR #332), and once by the team as a committed conflicted merge followed
by 167 single-topic reviewed PRs (`sync-14x-b16`, PRs #313–#481). Both lines were
Claude-written; the differences below are what the review process caught and what the
solo process caught, so they are the conventions a solo merge must apply to itself.

## Scope: the resolution is the smallest edit that lets both sides coexist

| Inside a resolution, do not | Because | b16 evidence |
|---|---|---|
| Re-indent, re-tab or reword text either side already had | The reviewer must see only the merge in the hunk | `guc.c` `geqo` re-tab and errdetail rewording, `postgres.h` comment, `tablecmds.c` `default:` reordering |
| Remove pre-existing duplicates or dead code you notice | It is a separate change with its own review; note it in the report | `pgstat.c` duplicated include, `pg_dump.c` duplicated `append_depends_on_extension` |
| Re-derive a branch ladder upstream only split | Greengage's precedence was deliberate | `canAcceptConnections`: insert `CAC_NOTCONSISTENT` where `PM_RECOVERY` was; keep the mirror-ready check first |
| Take upstream's declaration over a Greengage type or arity | A type difference is a port until `git log -S` proves it incidental | `forbidden_in_wal_sender(int)` (`b6f43a0ccff`, unsigned-`char` platforms) |
| Keep a Greengage name upstream has renamed, when an earlier merge simply missed the rename | Each kept name is one more conflict next time | `lazy_vacuum_rel_heap` → `heap_vacuum_rel`; `SUBDIRS` one per line; GG `pgstat_report_*` moved with their family to `backend_status.c` |
| Re-graft Greengage text into `doc/` | Greengage documentation lives in its own repository | `create_table.sgml`, `declare.sgml` — take upstream |
| Add a new comment with the `GPDB:` prefix | New code uses `GGDB:`; the tree carries both, new code should not add to the old one | PR #400 review normalised every new comment |
| Guard a new MPP invariant with `Assert` when its failure would corrupt data | A release build must refuse, not proceed | `elog(ERROR, "gp_segment_id is NULL")` in `nodeModifyTable.c` kept over `Assert` after review |

## Lookahead: what upstream did after the target changes the resolution

```bash
TARGET=8ff1c94649f; NEXT=REL_14_0
# features in the batch that upstream reverted before the release
git log --oneline $TARGET..$NEXT --grep=Revert -- $(git diff --name-only $TARGET^ $TARGET -- src)
# fixes upstream applied before the release to code the merge brought in
for f in $(git diff --name-only <base> $TARGET -- src); do git log --oneline $TARGET..$NEXT -- "$f"; done | sort -u
# corruption fixes in later minors
git log --oneline $NEXT..REL_14_STABLE --grep='corrupt' --grep='crash' --grep='wrong results' -- src/backend/access
```

| Finding | Decision | b16 case |
|---|---|---|
| Feature in the batch reverted before the tag | Back the feature out of the merge: `git diff <first>^ <last> -- src \| git apply -R --3way`, restore files nothing else touched from the base, hand-resolve the rest. Mark kept Greengage code inside the region with `TODO_REVERT_<revert-hash>` so the next bump keeps ours where git would merge duplicates silently | XLogReader state machine + decode buffer + recovery prefetch (`323cbe7`, `f003d9f`, `1d25757`; reverted by `c2dc19342e0`). PR #347 did exactly this; the residual diff against the base is 35 comment lines |
| A smaller feature reverted before the tag | Same rule — apply the gate to every reverted commit in the batch, not only the biggest | psql "show all query results" (`3a5130672`, reverted by `fae65629cec` a week after the target). The freeze-era psql discards every NOTICE that arrives after an ErrorResponse (`common.c` error branch → `PQgetResult` → `termPQExpBuffer`), which hid the DTX abort/retry messages; two answer files were then changed for the wrong reason |
| Fix landed before the tag in merged code | Backport as its own commit, upstream hash in the subject, minimal shape; keep the list for the next bump | `0e69f705cc1` autovacuum unguarded `SearchSysCache1` (worker SIGSEGV, segment reset); `37e1cce4ddf` + `ffff00a3556` libpq SNI NULL `pghost` (every QD→QE connection with `ssl=on`) |
| Corruption fix in a later minor | Same | `dad1539aec2` (14.2, HOT-chain corruption during pruning, PG bug #17255); `61a86ed55ba` + `f6162c020c8` (parallel VACUUM overlooking indexes) |

A fix that lives only inside a to-be-reverted feature is not worth a commit — note it and
back the feature out (b16: `AllocSizeIsValid` on `xl_tot_len` in the freeze-era reader;
upstream fixed the class in `bae868caf22`, 2023, and the PG14-final reader already guards
it).

## Behaviour decisions are separate, reviewable commits

| Kind | Title | Default |
|---|---|---|
| A later upstream commit carried early | `pre-apply <hash>: <subject>` | Only after the lookahead gate says the batch is reverted/fixed |
| A Greengage gate on an upstream feature (`DETACH PARTITION CONCURRENTLY`, `REINDEX CONCURRENTLY`) | `policy: reject <feature> in dispatch mode` | Gate every sub-command of the protocol (`CONCURRENTLY` **and** `FINALIZE`), next to upstream's own transaction-block check in `utility.c`, with an `errhint` naming the supported form |
| A default that ships to every cluster (`checkpoint_completion_target`, `enable_resultcache`) | `policy: adopt upstream default <guc>=<value>` | Upstream's value |
| Dispatch-model change (COPY transcoding on the QD, query id QD-only, a GUC left unsynced) | `policy: …` with the retest matrix in the body | Upstream behaviour; say what a QE now sees differently |
| Catalog constant renumbering (`AO_COLUMN_TABLE_AM_OID` 8435 → ?) | `catalog: renumber <name> …` | Pick by `unused_oids` **and** check the sibling campaign lines so all lines agree (b16: AI 9446 vs team 8913 — divergent for no reason) |

List them, with hashes, at the top of the merge report. PR #332 listed twelve inside
section B of a 14 KB description; the team could act on none of them.

## Two workflows

| | One merge commit | Committed markers, then per-file commits |
|---|---|---|
| Used by | Solo campaign steps (`claude-merge-*`) | The team's `sync-14x-b*` line |
| Bisectability | The merge commit is one point | Every resolution is its own point, the merge commit does not build |
| Reviewability | None — 1032 files in b16 | One file or topic per PR, two reviewers each |
| Integration | Immediate | Needs an integration branch (b16: PR #404) to run CI at all |
| Rule | Do not commit until resolved and build + core regress are green | Commit the merge with markers as-is; resolve in `squash! Resolve conflicts in <file>` commits |

Commit message template the team uses (PR #320, #317, #400):

```
squash! Resolve conflicts in src/backend/commands/tablecmds.c

Commit 8ff1c94 added a new FDW API for TRUNCATE ... This caused conflicts with
GPDB-specific changes:

1. GPDB's ExecuteTruncateGuts() takes an extra trailing TruncateStmt argument
   (commit <gg-hash>) ... Keep that argument last and insert upstream's
   'relids_extra' after 'relids', in the declaration and both call sites.
2. ...
5. Skip the foreign table collection entirely on the QEs: the QD dispatches the
   statement, so every segment re-enters ExecuteTruncateGuts() for the same
   relations and would truncate the same remote table once per segment.
```

Name the upstream commit(s) and the Greengage commit(s) that collided, one numbered item
per decision, and say what behaviour each item preserves or changes. A resolution that
needs no explanation still names the two commits.

## Tests during a bump: adapt the input, keep the assertion

The team's convention, stated in reviews (#440, #454) and applied in #453/#454/#459/#462/#463:
keep upstream's statements and comments, record Greengage behaviour in `expected/`, and when
an upstream assertion cannot hold on MPP as written, change the **input** so the property
under test still holds. Recording the failed assertion is not an option.

| Test (upstream commit) | The solo merge recorded | The reviewed adaptation |
|---|---|---|
| `mvcc` clean_aborted_self (`90c885cdab8`) | `(1 row)` where upstream asserts `(0 rows)` — index growth | Seed every segment with negative keys so each btree already has its metapage; expected stays `(0 rows)` (#453) |
| `insert` "tuple larger than fillfactor" (`0ff8bbdee19`) | `64 kB`, the second size check gone | One distribution-key value for every row, payloads sized for the 32 kB block, sizes checked after both inserts (#454) |
| `guc` Greengage dispatch-quoting test vs `3db826bd55c` | `ERROR: invalid configuration parameter name` — the Greengage feature untested | Rename the custom GUC to `"table.foo"`: still needs quoting on dispatch, passes the new rule (#462) |
| `resultcache` (`9eacee2e62d`) | Merge Join / Hash Join plans with no Result Cache node | `enable_sort`/`enable_hashjoin` off around the blocks so the node the test exists to show stays in the plan (#463) |
| `brin_bloom`, `brin_multi` (`77b88cd1bb9`, `ab596105b55`) | Seq Scan where the test asserts "index is used"; `_optimizer.out` with 29 and 150 `did not get bitmap indexscan plan` warnings | 200k rows and `SET STATISTICS 1000` as `brin.sql` does; `optimizer_enable_tablescan`/`optimizer_enable_bitmapscan` for ORCA; two warnings total (#459) |
| `privileges` (`a14a0118a1f`) | `(user.c:2093)` baked into the expected error | Add the `errcode()` upstream forgot, as upstream later did (#449) |

Rules that follow:

- Run `gpdiff.pl … --gpd_init init_file expected results` first; a file gpdiff passes is
  not touched, whatever `git diff` shows. b16's `gporca.out` regeneration changed 5.3k
  lines for 4 that mattered, and copied raw errors into `start_ignore` blocks that upstream
  text used to fill.
- Never assert on the segment count or cluster layout; never let a regression test destroy
  or recreate a data directory (`rm -rf`, `gpinitstandby -r`) — skip or guard instead.
- Enable each new upstream isolation spec individually and give each disabled one a
  one-line concrete reason (FK enforcement, isolationtester attribution), not a blanket
  comment.
- Message wording follows upstream's spelling of the command (`ALTER TABLE ... DETACH
  PARTITION ... CONCURRENTLY is not supported`) with an `errhint` naming the supported form;
  no product name in the message.
- A regenerated base file has siblings upstream never touches: `<t>_optimizer.out`,
  `output/<t>.source`, the `enable_*` GUC lists in `sysviews` and `rangefuncs_cdb`,
  `src/interfaces/gppc/test/expected`, `src/bin/gpfdist/regress/output`,
  `gpcontrib/*/expected`. The CI regression artifact hides the contrib tail; read the job
  log for `not ok`.
- New upstream TAP tests that call `pg_ctl` or `postgres` directly need the Greengage
  identity options (`-c gp_role=utility --gp_dbid=… --gp_contentid=0`); CI runs
  `PG_TEST_EXTRA="kerberos ssl"`, so `perl -c` every changed `.pl`/`.pm` before pushing.

## Audits the sweep cannot do

Run after the last conflict is resolved and again after bring-up fixes.

| Audit | Command or grep | Catches |
|---|---|---|
| Bitmask / enum distinctness | `grep -h '#define CURSOR_OPT_' src/include/nodes/parsenodes.h \| awk '{print $3}' \| sort \| uniq -d` — repeat for every flag family Greengage appends to (`HEAP_*`, `PROC_*`, `RELOPT_KIND_*`, GUC flags, DTX and lock flags) | Upstream renumbered; the appended Greengage members alias upstream's (b16: every plpgsql cursor forced onto a generic plan, ORCA bypassed) |
| Collapsed N-subplan node | `grep -n 'forboth.*resultRelations\|list_make1(subpath)' src/backend/optimizer src/backend/cdb` | A per-subplan check now applied to the first relation only (`numsegments`, motion elision, trigger prohibition) |
| Lazy accessors upstream introduced | grep raw reads of the backing field (`ri_ChildToRootMap`, `ri_projectNewInfoValid`) in Greengage code | A field that is NULL until the accessor runs |
| Changed refusal / auth messages | grep the **old** string in `src/backend/cdb/dispatcher/cdbgang.c`, `src/test/isolation2/sql_isolation_testcase.py`, `gpMgmt/` | Retry surfaces that no longer match |
| New `bool` parameters on lookups | callers in `src/backend/cdb`, `src/backend/executor/nodeDynamic*`, `gpopt/` | A default that changes behaviour for detach-pending or invisible children |
| New FDW / AM callbacks | `git diff <base> <target> -- src/include/foreign/fdwapi.h src/include/access/tableam.h` | A callback the dispatched statement now runs once per QE |
| Trimmed header includes | build; then grep Greengage-only dirs for symbols of the trimmed header | Lost transitive includes (`storage/latch.h`) |
| Pipeline restructure entry points | list every Greengage path that bypasses the new pipeline: custom formatters, external-table callbacks, `COPY PROGRAM`, QD→QE frames, SREH retry, rescan | A flag upstream recomputed flowing into a consumer with different semantics; an error that retries without consuming input |
| `PG_CATCH` cleanup helpers | grep `PG_CATCH` in `src/backend/cdb` and `executor/execUtils.c` for state that may not exist yet (`queryDesc->estate`) | A new node type making an error path reachable that dereferences uninitialised state |
| Node-type coverage | for every new Plan/PlanState node: `plan_tree_walker`, `plan_tree_mutator`, `ExecSquelchNode`, `IsMemoryIntensiveOperator`, `motion_sanity_walker`, `DirectDispatchUpdateContentIdsFromPlan`, `outfast.c`/`readfast.c`, `explain.c` | `unrecognized node type` on the first plan that uses it |
| Raw-parse node readers | when a merge makes a new class of tree dispatched (`CreateFunctionStmt.sql_body`), enumerate the raw nodes it can carry (`ParamRef`, `ColumnRef`, `A_Const`, `TypeCast`) and test positional `$n` parameters | `could not deserialize unrecognized node type` on the QE |

## Where to look before re-deriving anything

1. The `greengage_sync` team PRs for the same file or symptom (`gh pr list --search
   "<file>"`); their descriptions name the colliding commits and the decision.
2. The previous campaign branches: `git log --grep=<symptom>` and `git log -S<identifier>`
   on `claude-merge-2` … `claude-merge-7` (b16: the SQL-body pristine-copy dispatch fix
   already existed as `a5a0d90e4b5` on `claude-merge-2` and was re-imported by PR #456).
3. Upstream after the target (the lookahead above).
