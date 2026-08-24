# Conflict mechanics: plumbing, sweeps, and the garbage to recognise on sight

Lookup material for [greengage-pg-merge](../SKILL.md). Methodology is in the skill; this is
the command surface and the failure catalogue.

## Plumbing

During a conflicted merge every file has up to three staged versions, and they are the
authority — not your memory of what the file used to look like.

| Command | What it gives you |
|---|---|
| `git show :1:<path>` | The merge base |
| `git show :2:<path>` | **Ours** — Greengage before the merge (also `<merge>^1:<path>` after committing) |
| `git show :3:<path>` | **Theirs** — the pinned upstream target (also `<merge>^2:<path>`) |
| `git diff --name-only --diff-filter=U` | The conflicted set |
| `git status --porcelain` | The conflicted set *typed* — `UU`, `AU`, `DU`, `UD`, `AA` |
| `git checkout -m -- <path>` | Restore the conflict markers in one file you mis-resolved and have not staged |
| `git add <path>` | Mark resolved; staged resolutions survive everything except `--abort` |
| `git merge --abort` | Discard the entire merge state. Rarely what you want |

Useful counts while planning:

```bash
# conflicts by extension - tells you how much is code and how much is bulk
git diff --name-only --diff-filter=U | sed 's/.*\.//' | sort | uniq -c | sort -rn

# hunk count per file - the batching key
for f in $(git diff --name-only --diff-filter=U); do
  printf '%3d %s\n' "$(grep -c '^<<<<<<<' "$f")" "$f"
done | sort -rn
```

## Bulk classes: resolve these first and get them out of the inventory

| Class | Recipe |
|---|---|
| `*.po` translations (`DU`) | `git rm` them; Greengage does not maintain translations |
| Removed upstream docs (`DU`) | `git rm` |
| Greengage-only tests (`AU`) | Keep, after confirming upstream has no file at that path |
| Generated files (`configure`, `gram.c`, `*_d.h`) | Never hand-merge. Resolve the source, regenerate. `configure` needs **autoconf 2.69** — any other version aborts with `Autoconf version 2.69 is required`, an `m4_fatal` that `configure.ac` carries deliberately |
| Copyright-year and pgindent-only hunks | Scriptable; take upstream |
| `expected/*.out`, `sql/*` | Defer to the regress phase entirely |

## The long-tail sweep

For the one-to-five-hunk files — the bulk of any inventory — a fixed rule set applied one
file at a time, ordered by hunk count (all the one-hunk files, then two, then the rest):

1. Both sides **added different things** → keep both, if and only if they are additive
   lines (case labels, enum members, includes).
2. Both sides **changed the same code** → upstream's shape, Greengage's intent.
3. The Greengage side is **deliberate behaviour** — MPP, AO, distribution, GPORCA, or
   anything carrying an explanatory Greengage comment → keep it and re-graft it onto the
   new shape.
4. The Greengage side is **incidental** — formatting, a comment, a rename that upstream has
   now done itself → take upstream.

Record per file: what was resolved, what Greengage behaviour was preserved, what upstream
shape was adopted, and — the important one — an **uncertainty note**. Then verify
mechanically before staging:

```bash
# markers must be zero
grep -c '^<<<<<<<\|^=======\|^>>>>>>>' <file>

# brace balance must match the upstream side; a delta means a spliced function
for side in :3: HEAD; do
  git show $side:<file> 2>/dev/null | tr -cd '{}' | wc -c
done
```

A non-zero brace delta is *usually* a `'{'` character literal rather than a real
structural divergence — check before panicking, but never skip the check.

Excluded from any sweep, always resolved individually: files with six or more hunks. In
practice that has meant `tablecmds.c`, `gram.y`, `planner.c`, `xlog.c`, `xact.c`, `guc.c`,
`vacuum.c`, `bufmgr.c`, `heapam.c`, `pg_dump.c`, `nodeModifyTable.c`, `copy.c`,
`twophase.c`, `storage.c`, `pg_regress.c`, the catalog `.dat` files and the build files.

### Cross-file dependencies must be decided once, up front

A sweep resolves files independently, which is exactly wrong for a decision that spans
them. Before starting, write down the ones you know — each is a rule every file in the
sweep must honour. Real examples from past campaigns:

- Keep Greengage's three-argument `smgropen(..., SMgrImpl which)` in `smgr.h`/`smgr.c`; all
  AO storage depends on it, so no file may adopt upstream's two-argument form.
- `lwlock.h`'s Greengage tranches resolve together with `lwlock.c`.
- Greengage keeps `OBJECT_RESQUEUE` / `OBJECT_RESGROUP` switch cases wherever upstream
  enumerates object types.

## Merge-artifact garbage: recognise it on sight

These are not bugs in the code, they are damage from the resolution. Each has a signature
that is faster to recognise than to debug.

| Symptom at build time | What actually happened | Fix |
|---|---|---|
| `storage class specified for parameter` cascading through one file | Both the old prototype and a truncated new one survived the conflict | Delete the stale signature; re-extract the function head from `:3:` |
| `missing terminating` / a stray `* foo` line | A comment's opening `/*` was inside a discarded hunk | Restore the opener |
| `#endif without #if`, or the same header included twice | A `#ifdef` opener or its `#endif` was lost across the conflict | Re-extract the guard region |
| A symbol defined twice | The clean-merged region already contained what you took from `:3:` | Read the whole file before taking a side; this is the two-way-conflict-style trap |
| `undefined reference` to a Greengage function whose declaration is fine | A file split left the declaration and callers but dropped the definition | Recover it from a reference branch |
| Two copies of the same function, one dead | An upstream file split (for example `xlog.c` into `xlogrecovery.c`) left the originals behind | Delete the orphans; confirm which copy the build actually links |

## Clean-merge traps: no markers, still wrong

The class that costs the most, because nothing draws attention to it.

- **Old-arity callers survive in Greengage-only code paths.** Upstream changed a signature
  and updated its own callers; Greengage's callers live in code upstream never touched, so
  they merge cleanly at the old arity. The compiler finds these — which is why the compile
  phase is not optional even when the resolution "looks done".
- **A file split drops a function's definition and its call while the header `extern`
  survives.** No conflict, no link error if nothing else references it, and the behaviour
  is simply gone. Cross-check: any header `extern` with no definition anywhere in the
  split-file family is a dropped function.
- **The pinned target predates an upstream fix Greengage had already backported.** Git
  takes upstream wholesale and the backport disappears.
- **A relocated table or registry loses its Greengage entries** — the authority-relocation
  class, with worked examples in [version-traps.md](version-traps.md).

The systematic defence is a post-resolution audit driven by the sweep's uncertainty notes,
plus a diff of the merged tree against the nearest reference branch restricted to
Greengage-specific paths (`src/backend/cdb`, `src/backend/gpopt`, `gpcontrib`,
`src/include/catalog` Greengage entries).

## Per-area verifiers

Run the ones your resolution touched, before building.

```bash
bison -Wcounterexamples src/backend/parser/gram.y   # runs standalone, needs no configure
perl src/backend/nodes/gen_node_support.pl          # PG16+; must exit 0
perl src/include/catalog/duplicate_oids             # must print nothing
perl src/include/catalog/unused_oids                # where to move a colliding Greengage OID
```

`gram.y` deserves the emphasis. A marker-clean grammar can still carry duplicate `%token`
declarations, duplicate productions that show up only as reduce/reduce conflicts, and
Greengage nonterminals that a new upstream feature made unreachable. Only bison sees any of
it.

For the QD-to-QE wire, remember that Greengage's binary serializers are
`src/backend/nodes/outfast.c` and `src/backend/nodes/readfast.c`, and that they are
**hand-maintained** even on the versions where upstream's `out`/`read` functions are
generated. A field added to a plan node and written in `outfast.c` but not read in
`readfast.c` desynchronises the stream and fails far from the cause. Both sides, every time
— see [greengage-internals](../../greengage-internals/SKILL.md).
