# Per-version traps: what each PostgreSQL major broke in Greengage

Lookup material for [greengage-pg-merge](../SKILL.md). Distilled from the PG14–PG18 bump
campaigns on `greengage_sync`. Read the recurring-class table before starting **any** bump;
read the per-version section for the step you are on and the one before it.

The point of this file is not the individual rows — it is that the same six classes recur
every single time, wearing different clothes. Budget for them by class, not by version.

## The six recurring classes

| Class | How it presents | Defence |
|---|---|---|
| **Authority relocation** | A table, list or registry moves to a new file or becomes generated; Greengage's entries in the old location are gone with no conflict | After any relocation, diff the old file's Greengage entries against the new one, entry by entry |
| **Missing or retyped struct field** | Upstream adds a field to a struct Greengage-only code initialises with `{0}` — a NULL deref rather than a compile error | Grep Greengage-only files (`cdb`, `gpopt`, AO handlers) for every struct upstream changed |
| **Dropped re-graft in a clean merge** | No conflict marker at all; behaviour simply gone | Uncertainty notes from the sweep; a diff against a reference branch over Greengage-only paths |
| **GPORCA translator gap** | Works with `optimizer=off`, **silently wrong results** with `optimizer=on` | Every new plan-node field or `Query` flag needs the DXL translator checked, or an explicit unsupported-feature fallback |
| **QD-to-QE serializer desync** | `unrecognized node type`, or a garbage node tag far from the cause | Every added node field needs both `outfast.c` and `readfast.c` |
| **Assert-build crasher** | Fine in a release build, `FailedAssertion` under `--enable-cassert` | Run an assert build; either Greengage legitimately exceeds an upstream precondition (drop the assert) or upstream re-tightened one Greengage had exempted (re-graft the exemption) |

The assert class has a matrix hole worth knowing: the assert CI job builds without GPORCA
and the GPORCA jobs build without asserts, so **assert ∩ GPORCA is never covered by CI**.
Run that combination by hand at least once per campaign.

## PG14

The heaviest catalog and planner cycle of the campaign so far.

**Catalog and genbki tightening.** `genbki.pl` rejects `oid_symbol` for `pg_proc`/`pg_type`
and generates `F_<NAME>` / `<TYPE>OID` itself. `DECLARE_TOAST` and `DECLARE_*INDEX` moved
into the per-catalog headers, and the merge tends to take upstream's gutted central
`indexing.h` — which drops **every** Greengage catalog index. Symptom is a build error
`<X>IndexId undeclared`; the fix is re-declaring roughly thirty indexes in their own
catalog headers (`pg_extprotocol.h`, `gp_distribution_policy.h`, `pg_appendonly.h`,
`pg_resqueue.h` and friends). BKI also became single-quoted, and `genbki.pl`,
`bootscanner.l`, initdb's `escape_quotes_bki()` and `guc-file.l` must all agree or initdb
dies with `syntax error ... unexpected character "`.

`pg_proc.dat` duplicate keys are Perl **last-wins**: if both the Greengage and the upstream
`proargnames` survive in one entry, one silently vanishes. And PG14 moved about 46 function
bodies out of `pg_proc.dat` into `system_functions.sql` — a function that ends up defined
in two of `pg_proc.dat` / `system_functions.sql` / `system_views.sql` fails initdb with
"already exists". Give each function exactly one home.

**Structural re-grafts.** PGXACT was eliminated in favour of dense arrays in `PROC_HDR`
(`ProcGlobal->xids[proc->pgxactoff]`), which the distributed-snapshot code in `procarray.c`
must be re-grafted onto. `copy.c` was split into `copyfrom.c`/`copyto.c` — Greengage keeps
the monolith, because `CopyStateData` is heavily extended for external tables, and one
leftover `CopyFromState cstate;` declaration reading past the end of the smaller struct
produced nondeterministic segment crashes at initdb. PG14's `bare_label_keyword` supersedes
Greengage's `ColLabelNoAs`: keeping both yields hundreds of reduce/reduce conflicts, and
clause-introducing keywords (`PARTITION`, `DISTRIBUTED`, `SCATTER`) must stay label-only or
the count reaches thousands.

**The lazy-row-identity rework** (upstream `86dc90056df`) dropped Greengage logic at five
separate layers — `add_row_identity_columns` must also emit the `gp_segment_id` junk Var,
`is_split_updates` must be built in lockstep with `resultRelations` in every branch, split
update needs `expand_targetlist` to run *first*, AO relations cannot fetch by TID, and
`create_splitupdate_plan` must use the nominal target relation rather than a partition
leaf. Symptoms range from `could not find gp_segment_id in subplan's targetlist` to a
silently NULL partition key.

**Aggregation.** PG14 assigns `Aggref.aggno`/`aggtransno` in `preprocess_aggrefs`, which
**GPORCA plans never pass through** — so the DXL-to-plan translator has to renumber each
Agg node's Aggrefs densely, or every multi-aggregate query returns the first aggregate's
value for all of them. Separately, Greengage puts aggregates with *different* `aggsplit`
modes in one Agg node, so every `DO_AGGSPLIT_*` test in `nodeAgg.c` must read
`aggref->aggsplit`, never the node-level `aggstate->aggsplit`.

**Dispatch.** PG14 added per-message-type length limits in `SocketBackend`; Greengage's
dispatch message types `'M'` (serialized plan) and `'T'` (DTX protocol) need
`PQ_LARGE_MESSAGE_LIMIT` or every dispatch fails with `invalid message length` and the
cluster never leaves utility mode.

## PG15

The cycle of file splits.

| Split | What it cost |
|---|---|
| `xlog.c` → `xlogrecovery.c` | Dropped `XLogProcessCheckpointRecord()` **and its call** — the DTX checkpoint payload was silently never replayed. The forward declaration survived, so nothing failed to build |
| `PostgresMain` → `PostgresSingleUserMain` | Greengage's startup hooks must be placed in the right half |
| `system_views.sql` → `system_functions.sql` | Same double-definition trap as PG14 |
| basebackup → `bbsink`/`bbstreamer` | A recurring HA hazard; segment base backups go through it |
| pgstat → shared memory | The Greengage pgstat extensions need porting onto the new storage |

PG15 also revoked `CREATE` on the `public` schema from `PUBLIC`, which breaks
non-superuser test setup; added a second per-parameter-ACL lookup on a path the **FTS
handler** reaches, and FTS runs outside a transaction so no catalog or syscache lookup is
legal there; and introduced `MERGE`, which arrives with no MPP support at all and needs an
explicit gate rather than a half-implementation.

The `Value` node split (into `Integer`/`Float`/`String`/`Boolean`) is an assert-build crash
class — code that still constructs a bare `Value` compiles and crashes later.

`pg_regress`'s `convert_sourcefiles()` call was dropped by the merge once: every `.source`
test then compared against an untemplated file, which looks like mass test failure and is
one missing call.

## PG16

**The node layer became generated.** `copy`/`equal`/`out`/`read` functions are produced by
`src/backend/nodes/gen_node_support.pl` from annotations in the struct definitions. Three
lists must match in count *and* order or the script asserts. Greengage's binary
serializers, `outfast.c`/`readfast.c`, stay **hand-maintained** and must be decoupled from
the generated ones; binary-only Greengage nodes need `no_read`. Derive any manual function
from the final merged struct, never by copying the previous version's body.

**The most expensive single lesson of the campaign** was the GUC table moving from `guc.c`
to `guc_tables.c`. Greengage's overridden `boot_val`s did not survive, silently reverting
to upstream defaults. The symptom was a recursive-CTE query hanging for thirteen minutes,
investigated as an interconnect deadlock. The generalisation is the authority-relocation
class at the top of this file — and the concrete follow-up is to extract every `boot_val`
Greengage overrides and diff it after the merge.

Also in PG16:

- `IndexVacuumInfo.heaprel` — a new struct field that Greengage-only AO code
  zero-initialises, giving a NULL deref rather than a compile error. The whole
  missing-struct-field class starts here.
- `RelFileNode` → `RelFileLocator` (`rnode` → `rlocator`) tree-wide, and `varatt.h` split
  out of `postgres.h`.
- `HAVE_UNIX_SOCKETS` removed from `pg_config.h.in`, turning every Greengage `#ifdef` on it
  into silently dead code — the first instance of the dead-macro sweep.
- GPORCA needed the `RTEPermissionInfo` translator port, and `gporca.mk` must filter
  `-Wshadow=compatible-local` out of both `CXXFLAGS` and `CFLAGS`.
- `_optimizer.out` regeneration is legitimately local work: those files are GPORCA-only and
  not shared across the job matrix, unlike base `.out` files.

## PG17

Four separate authority relocations in one cycle, all of the PG16 GUC-table shape:

| Relocated to | Greengage entries that vanish | Note |
|---|---|---|
| `src/backend/utils/activity/wait_event_names.txt` (generated) | Custom `WAIT_EVENT_*` members — 160 in the old header against 3 upstream | Strict alphabetical order; the generator hard-errors otherwise. Classes carrying an Oid stay hand-written, because a 16-bit event id cannot hold one |
| `src/include/storage/lwlocklist.h` (`lwlocknames.txt` deleted) | 14 custom LWLocks | Must also be registered in `wait_event_names.txt` in the same order — the generator dies on a mismatch, so the build stays broken until both are done |
| `MAKE_SYSCACHE()` in the catalog headers (`cacheinfo[]` deleted) | The hand-written Greengage syscaches | The macro takes the **index name**, not the `*IndexId` macro |
| The `gram.y` precedence block | Greengage's kept `%nonassoc` entries | Only `bison -Wcounterexamples` proves the parse tables still work |

Good news worth knowing so you do not budget for it: the GUC table did **not** move again
in PG17, and the `xl_xact` WAL record layout stayed stable.

Other PG17 items with teeth: `ParseLoc` retyping across the node layer; `BackendId`
becoming a 0-based `ProcNumber`; SLRU page numbers widening to 64-bit with per-bank locks;
`ShmemVariableCache` renamed to `TransamVariables`; two-phase-commit filenames gaining a
full transaction id; a new `transaction_timeout` GUC whose per-backend timer is armed in
`StartTransaction`; `VacDeadItems` replaced by `TidStore`; and the `DECLARE_*INDEX` arity
change, which collides with Greengage's catalog declarations again. `ROLE_PG_MAINTAIN`
takes an OID `pg_authid.dat` already uses on the Greengage side.

The dead-macro sweep recurs: `ENABLE_THREAD_SAFETY`, `HAVE_LOCALE_T`,
`HAVE_BIO_GET_DATA`, `HAVE_X509_GET_SIGNATURE_NID`, `HAVE_DECL_LLVMGETHOSTCPU*` all
disappear, and AIX support is removed outright.

## PG18

Reached on `claude-merge-6` (18beta1) and `claude-merge-7` (18.4). The classes that
actually bit, all of them instances of the six above:

- **A dropped caller, not a dropped function.** The single-row-insert direct-dispatch path
  lost its call site in `create_modifytable_plan`, so a constant `INSERT ... VALUES` ran a
  writer gang on every segment plus two-phase commit — which hung the whole CI regression
  job for three hours against a down mirror. The merge had *masked* it by regenerating the
  direct-dispatch answer file to the broken all-segments output. Both halves of that
  sentence are the lesson.
- **`LIKE INCLUDING STORAGE` lost per-column AO encoding.** Only the table-level reloptions
  carryover was re-grafted in `transformTableLikeClause`; the per-column
  `pg_attribute_encoding` union was dropped, and again an answer-file regeneration hid it.
- **GPORCA had no `CMD_MERGE` case**, so any `MERGE` statement produced a NULL DXL and
  segfaulted the coordinator. The correct fix for an unimplemented feature is to raise the
  unsupported-feature exception and fall back to the planner, not to leave the gap.
- **A missing `break` in an `allpaths.c` switch over RTE kinds**, reachable through
  parallelism — the kind of one-line damage a resolution introduces and no conflict marker
  survives to point at.
- **`ALTER COLUMN TYPE` index reuse dispatched a coordinator-local relfilenumber to the
  segments**, leaving the rebuilt index file unbuilt there — `could not open file` until a
  `REINDEX`.

## Two habits that would have caught most of the above

1. **Compare the two optimizers on any post-merge suspicion.** `SET debug_print_plan=on;
   SET client_min_messages=log;` under `optimizer=off` and then `optimizer=on`, and grep
   for the field in question. A plan field populated by the planner and NIL under GPORCA is
   a translator gap, and translator gaps produce wrong answers rather than errors.
2. **Treat an answer-file change during a merge as a claim that needs evidence.** In PG18,
   two real backend bugs were masked by regenerating expected output while resolving the
   merge. The gate is in [greengage-answer-files](../../greengage-answer-files/SKILL.md):
   never regenerate a file whose diff turns a committed result into an `ERROR`, and during
   a bump extend that suspicion to any diff that changes a *plan shape* — dispatch, motion,
   or segment count.
