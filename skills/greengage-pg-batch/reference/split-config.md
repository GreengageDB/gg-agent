# split.json and the files of the batch directory

Lookup material for [greengage-pg-batch](../SKILL.md), steps 6–10. `uoc_split.py --dir DIR`
reads and writes everything in DIR.

## split.json: the manual decisions

Every key is optional. Commit hashes may be abbreviated; they are resolved in the checkout.
Unit slugs must exist in `topics.json` (or `uocs.json`), or `assign` refuses.

```json
{
 "redirect": {"a0bbaf1bc42": "hot-chain-backport",
              "9970b63fe33": "process-startup"},
 "redirect_by_file": [["1a62f022089", "src/bin/gpfdist/regress/", "relkind-errmsg"],
                      ["1a62f022089", "src/bin/pg_basebackup/t/", "logical-replication-2pc"]],
 "primary": {"d68a0039121": "storage-locking"},
 "overrides": {"src/include/utils/unsync_guc_name.h:516": "process-startup",
               "src/test/regress/expected/rangefuncs_cdb.out:14": "memoize-rename"},
 "owners": {"<path>": "<slug>"},
 "edits": [{"path": "src/include/catalog/pg_magic_oid.h", "unit": "catalog-pin-oid-range",
            "old": "<the four-line GPDB note, verbatim>",
            "new": " * from 12000 to 12500.\n"}],
 "author_from": {"policy-heal": "6c7f942e333"},
 "audit": {"tests_unit": "regress-tests", "regen_commits": ["808dec21623", "ed10c3fd0b0"]}
}
```

| Key | Effect | b1 |
|---|---|---|
| `redirect` | Bring-up commit → unit, for operations **outside** conflict regions that this commit made. Independent fixes to their own units; build fixes and CI-found consequences to the unit of the upstream commit behind them (say which in a comment of the commit message) | 15 commits |
| `redirect_by_file` | The same for a bring-up commit that served several units: `[commit, path prefix, unit]` | 2 entries |
| `primary` | Upstream commit → the one unit that claims it, when several topics list it and the unit's completeness depends on it | 2 commits |
| `overrides` | `"path:line"` → unit, where `line` is the operation's first line in DIRTY (1-based; for a pure insertion the line it is inserted before). Wins over every rule | 59, plus 49 placing the operations of split units |
| `owners` | Per-file owner for a changed file that `uocs.json` lacks (its net change BASE → RAW is empty) | — |
| `edits` | A minimisation: in `path`, replace the exact text `old` (must occur once) with `new` in every state that includes `unit`'s operations. The final tree then differs from RAW by exactly these edits | 2 (a comment, an entry order) |
| `author_from` | Unit → commit whose author and date the unit commit takes. Default: the bring-up commit behind most of the unit's operations | 3 |
| `audit.tests_unit` | The answer-file unit, exempt from NONE and RAWX in `check audit` | `regress-tests` |
| `audit.regen_commits` | Bring-up commits that regenerated answer files wholesale, exempt from RAWX | 2 |

Find an override key with `review --all --path <file>`: each operation prints as
`### path:line old -> new [how]`.

## Placement kinds in assignment.json (`how`)

| `how` | Set by | Meaning |
|---|---|---|
| `region` | causes of the overlapped conflict regions | The units claiming the commits that changed the region upstream |
| `raw` | `redirect`, `redirect_by_file` | The bring-up commit that made the operation is redirected |
| `tokens2` | identifier index | A rename-like match on both sides, score ≥ 0.5 |
| `testL` | upstream blame of the answer file | At least half of the replaced lines come from one batch commit |
| `group` | answer-file grouping | Follows a moved neighbour in the same result set or ≤ 2 lines away |
| `mirror` | answer-file grouping | An `_optimizer.out` operation following the `.out` operation at the same place |
| `override` | `overrides` | Manual |
| `none` | — | No evidence: stays with the per-file owner |

Each operation also records `old` (per-file owner), `new` (unit), `causes` (upstream commits),
`raws` (bring-up commits; `<deleted file>` when RAW deletes the file), `cand` (claiming
units), and `i1,i2` / `j1,j2` (0-based line ranges in DIRTY and RAW).

## Files in the batch directory

| File | Written by | Content |
|---|---|---|
| `inv.json` | `pg_batch.py inventory` | Conflict hunks: AUTO / REGEN / RESOLVE, day-1 commits |
| `facts.json` | `pg_batch.py facts` | BASE, CUT, DIRTY, RAW, merge base, per-file facts, bring-up commits and trailers |
| `topics.json` | you | The units ([units-of-change.md](units-of-change.md)) |
| `uocs.json` | `pg_batch.py assign` | Per-file owners and the upstream commits touching each unit's files |
| `split.json` | you | Manual decisions (above) |
| `tokens.json`, `gone.json` | `causes`, `check` | Caches keyed by the upstream range: identifiers each commit removed and added; identifiers the batch removed |
| `ops.json` | `causes` | Every operation with its conflict-region, bring-up, identifier and answer-file evidence |
| `assignment.json` | `assign` | Every operation with its unit |
| `units/NN-slug/` | `bundle` | `diff.patch`, `ops.txt`, `upstream.txt`, `raw.txt` for writing the description |
| `msg/<slug>.txt` | you | The unit description; `branches` prefixes `UoC N: ` |
| `numbers.json` | `branches --create` | Stable unit numbers; edit only to give a split's first part the parent's number |
