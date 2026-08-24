---
description: Start or continue a PostgreSQL major-version bump of Greengage on the campaign line
argument-hint: "[target PG major or upstream commit, or nothing to continue the merge in progress]"
---

Bump: $ARGUMENTS

Delegate to the **greengage-pg-merger** subagent — it owns the resolution rules and the
bring-up ladder. This command establishes where the campaign actually is and hands over.

## 1. Confirm the tree

A bump happens in [`GreengageDB/greengage_sync`](https://github.com/GreengageDB/greengage_sync),
never in `GreengageDB/greengage`. Check the remotes before anything else; if you are in the
shipping repository, stop and say so rather than merging PostgreSQL into `7.x`.

## 2. Establish the state, do not assume it

```bash
git status --porcelain | cut -c1-2 | sort | uniq -c   # merge in progress? conflicts by type
grep -n 'PG_PACKAGE_VERSION=' configure.ac            # the real base version
```

Three cases, and they need different handling:

- **A merge is already in progress** (conflicts present, or `.git/MERGE_HEAD` exists) —
  continue it. Do not start a new one, and do not `git merge --abort`: staged resolutions
  are real work and aborting discards all of it.
- **No merge, a target given** — resolve the target to a commit and confirm it is exactly
  one major version ahead of `PG_PACKAGE_VERSION`. Two majors in one merge has no buildable
  checkpoint in between; propose the intermediate step instead of doing what was asked.
- **No merge, no target** — the campaign is between steps. Report the base version and the
  obvious next target, and ask before starting a merge. Starting one is not a default.

## 3. Delegate

`@agent-greengage:greengage-pg-merger` — give it the tree, the base version, the target
commit, the typed conflict inventory, and any notes from the previous session, especially
the uncertainty notes from an earlier sweep.

Let it work through the phases. A bump is not a single session: expect to hand the campaign
state back and forth, which is why the agent reports state first.

## 4. Report

Campaign state at the top — base, target, conflicts remaining by type, phase reached, what
is red. Then the uncertainty notes, then failures with their classification and the evidence
behind it, then what was not done.

Do not call a phase green on a summary line. A green regress phase is an empty
`regression.diffs`, produced by a binary you can prove you just built.

See also: [greengage-pg-merge](../skills/greengage-pg-merge/SKILL.md) ·
[greengage-build](../skills/greengage-build/SKILL.md) ·
[greengage-testing](../skills/greengage-testing/SKILL.md) ·
[greengage-ci](../skills/greengage-ci/SKILL.md)
