# Batch PR description template

Lookup material for [greengage-pg-batch](../SKILL.md), step 10. The filled example is
[GreengageDB/greengage_sync#660](https://github.com/GreengageDB/greengage_sync/pull/660), the
batch PR `sync-15x-b1-base` → `next`. Write the template by hand, then make every `{Un}` the
URL of unit N's PR:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/uoc_split.py --dir $B links sync-15x-b2 template.md \
    --repo GreengageDB/greengage_sync > body.md          # fails on a {Un} with no PR yet
gh api -X PATCH repos/GreengageDB/greengage_sync/pulls/<n> -F body=@body.md
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/uoc_review.py status --pr <n> --repo GreengageDB/greengage_sync
```

`status` fills the unit table under "Units of change" ([greengage-uoc-review-status](../../greengage-uoc-review-status/SKILL.md)).

## Placeholders

| Placeholder | Source |
|---|---|
| `{MBASE}`, `{CUT}` | Upstream range of the batch: the merge base and the cut |
| `{NCOMMITS}` | `git rev-list --count {MBASE}..{CUT}` |
| `{FILES}`, `{INS}`, `{DEL}` | `git diff --shortstat next <prefix>-raw` |
| `{MERGE}` | The merge commit, DIRTY |
| `{NCONFLICT}` | `git grep -l '^<<<<<<< ' {MERGE} \| wc -l` |
| `{TEST_PR}` | The PR of `<prefix>-test` into the base |
| `{Un}` | Unit N's PR, filled by `links` |

Text sources: upstream subjects (`git log --no-merges {MBASE}..{CUT}`), subjects containing
"Revert", the unit descriptions (what Greengage did, `Review focus:`), and the bring-up commit
messages for the bugs.

## Skeleton

```markdown
# Sync {MAJOR}x b{N}: merge upstream PostgreSQL {MBASE}..{CUT}

{Ordinal} batch of PostgreSQL {MAJOR} development: **{NCOMMITS} upstream commits**, from
`{MBASE}` ({date}, {what it is}) to `{CUT}` "{cut subject}" ({date}). {FILES} files changed
against `next` (+{INS} / −{DEL}).

**How this PR is organised.** `<prefix>-base` starts with the upstream merge, `{MERGE}`. Its
{NCONFLICT} conflicted files are committed with diff3 conflict markers, so the base does not
build on its own. Each **unit of change** (UoC), an upstream change together with every
Greengage change it caused, is reviewed in its own PR into `<prefix>-base`, with what was done
and why in its description. (UoC N, #PR) below names the unit and its PR.

- The unit PRs are independent: each changes only its own hunks, and they merge cleanly in any
  order. The base builds once all of them are merged.
- #{TEST_PR} (`<prefix>-test`, the base with every unit branch merged in) runs CI on the
  combined result. `.github/workflows/sync-uoc-test.yml` merges the review fixes of the unit PRs
  into it, whoever makes them. The workflow is a temporary commit on the base and is removed
  before this PR is merged.
- Held units, if any: "UoC N (#PR) and UoC M (#PR) are not merged into this PR (see Units of
  change). Both fix problems that predate the batch, and both stay only on the test branch."
- Merge this PR with a merge commit, after all unit PRs are merged (except the held ones).

Below: what came from upstream, what was reverted within the batch, and the Greengage
adaptations. Commit hashes are upstream unless noted.

---

## Upstream changes in this batch

### {Area}
- {hash} **{main feature}**: {one-line effect}.
- {hash} {smaller change}; {hash} {smaller change}.

## Reverted within the batch

- {hash} {what was reverted} (reverts {hash}).

---

## Greengage adaptations and bugs found during bring-up

**Real bugs found and fixed:**
1. **{symptom as a user would see it}**: {cause, with the upstream hash}. (UoC N, {Un})
2. **Independent of the batch, found by CI on this branch:** {fix} (UoC N, {Un}).

**Re-grafts reviewers should know about:**
- **{area}**: {how the Greengage code was re-applied onto the new upstream shape}. (UoC N, {Un})

**Decisions to confirm:**
- {behaviour that differs from upstream or from the previous Greengage behaviour}. (UoC N, {Un})
- Lost test coverage: {test} ({reason}). (UoC N, {Un})
- Not merged: UoC N, {what it fixes}. {Why it is held: no reproducer or test; upstream brings
  it in a later batch as {hash}}.

## Units of change

<!-- uoc_review.py status writes the unit table here -->

## Validation

- Build (cassert, ORCA, LLVM, TAP), `unittest-check`, initdb and the demo cluster: {result}.
- `installcheck-good` under `optimizer=off` and `optimizer=on`: {result}.
- CI on #{TEST_PR}: run [{id}](https://github.com/GreengageDB/greengage_sync/actions/runs/{id}) {result}.
  Say that this tree includes the held units and the merged base does not.

## Follow-ups (not in this PR)

- {upstream fixes after the cut, from `pg_batch.py select`, that the next batch must apply}.
- {flaky tests seen in CI, each with why the batch does not cause it}.
```

Usual areas: Planner & executor; Catalog & SQL; Process startup, statistics, shared memory;
WAL & recovery; Replication; Commands & DDL; Client tools, libpq, contrib; Build & tests.
Drop empty sections.

## Writing rules, from the #626 and #660 reviews

- Lead each bug with the symptom, not the fix: "`ALTER TABLE … SET TABLESPACE` segfaulted the
  coordinator and all segments", then the upstream commit, the mechanism, the fix and the unit.
- End every Greengage item with `(UoC N, {Un})`: `links` puts the bare PR URL there, which
  GitHub renders as `#PR`, so a reviewer goes from the description to the unit PR in one click.
- Say **pre-existing, not caused by this merge** when the bug exists on `next` (b1: three of
  twelve), and cite the upstream fix and its release when the fix is a backport.
- A behaviour decision gets its own bullet with the default it ships, even when it keeps the
  current behaviour (b1: `shared_buffers` keeps the Greengage default 4096; `nextRelfilenode`
  starts at `FirstGenbkiObjectId`).
- Upstream hashes without a prefix, main features in bold, one line per item where possible.
- Keep campaign-internal names out (round numbers, local paths, container names); every hash
  must exist on `greengage_sync` or upstream.
- Keep the body under GitHub's 65,536 characters.
