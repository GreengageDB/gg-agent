# Authoring contract

How skills in this repository are written. Read this before adding or editing one.
`tools/validate_skills.py` enforces the mechanical half; the rest is style you are
expected to match by hand.

## Repository layout

```
.claude-plugin/
  plugin.json          # every skill directory must be listed in skills[]
  marketplace.json     # one plugin entry, source "./"
skills/<skill-name>/
  SKILL.md             # required
  reference/*.md       # optional: lookup material (tables, inventories, maps)
  rules/*.md           # optional: atomic, individually-loadable rules
commands/*.md          # slash commands
agents/*.md            # subagents
tools/validate_skills.py
```

Skill directories are `kebab-case` and **always prefixed `greengage-`**.
`SKILL.md` is always uppercase.

## Frontmatter

```yaml
---
name: greengage-<topic>          # must equal the directory name
description: <what it does> - <inventory of the concepts it covers>. Use when <trigger>, <trigger>, or <symptom>.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---
```

`description` is the only thing loaded at startup — it is the routing signal, and it is
worth 400 characters of care. Three parts, in this order:

1. **What the skill does**, as a verb phrase.
2. **An inventory** of 6–12 concepts it covers, comma-separated. This is what makes the
   router fire on a specific sub-topic rather than the general area.
3. **`Use when …`** — two to four concrete triggers, and where possible **literal error
   strings the user might paste**: `Cluster validation failed`,
   `Segments are in reset/recovery mode`, `COORDINATOR_DATA_DIRECTORY not set!`. A pasted
   symptom is the highest-value trigger there is, and generic descriptions miss it.

Target 350–520 characters. Shorter than 200 will not route reliably.

## Structure and size

`SKILL.md` holds **decision rules**, the happy-path commands, and the traps that
invalidate them. Bulk inventories go **exactly one level down** into `reference/` or
`rules/` — file references only work one level deep, so never nest further.

- `SKILL.md`: aim for under 400 lines. The validator warns past that.
- Section order that works: orientation → happy path → the trap that invalidates the
  happy path → failure-mode tables → what NOT to do → `See also:`.
- End every `SKILL.md` with a `See also:` line linking 3–6 sibling skills as
  `[greengage-build](../greengage-build/SKILL.md)`. Link inline at the point of need too,
  not only at the bottom.
- Reference files are strictly *lookup* material — tables of paths, commands, signatures.
  Methodology stays in `SKILL.md`.

## Voice

These skills double as developer documentation: a human should be able to read one
straight through and learn something. What that means concretely:

- **Write headings as the wrong belief being corrected**, not as topics.
  "Environment first (silent-failure trap)" beats "Environment".
  "`--use-existing` runs are not authoritative" beats "Running single tests".
- **Rules are imperative and absolute.** "Never regenerate an answer file whose diff shows
  a result replaced by an ERROR." Not "it is generally advisable to check whether…".
- **Every claim carries evidence** — an exact error string, a `file:line`, a catalog name,
  a measured number. A claim you cannot ground is a claim to delete.
- **Tables for anything enumerable.** `| Symptom | Cause | Fix |` is the workhorse.
- **Say what not to do and what noise to ignore.** Half the value is stopping the agent
  from chasing a red herring.
- Bold inline for emphasis; skip decorative callouts and emoji.

## Version handling

Greengage has two live lines and they differ in ways that break commands:
**7.x** (PostgreSQL 12.22, *coordinator*) and **6.x** (PostgreSQL 9.4.26, *master*).

Write for 7.x, and call out 6.x deltas inline, at the point where they bite — a table row
or a parenthetical, not a separate section nobody reads. When a form works on both lines,
prefer it and say so — but establish which form that actually is rather than assuming the
newer name is the portable one. The worked example: **`PGOPTIONS='-c gp_session_role=utility'`
is the portable utility-mode spelling**, because 7.x keeps `gp_session_role` as a rename
alias for `gp_role` (`guc.c:4761`), while on 6.x setting only `gp_role` leaves
`Gp_session_role` at `dispatch` and the connection is rejected with
`connections to primary segments are not allowed` (`postinit.c:1196`). `gp_role=utility`
is the 7.x-only spelling.

## Grounding rules

1. Verify against `refs/remotes/origin/7.x` / `refs/remotes/origin/6.x` of
   `GreengageDB/greengage`. Never cite a working tree or a feature branch.
2. Do not carry over facts from other Greenplum forks. The environment script is
   `greengage_path.sh`, the regression schedule is `greengage_schedule`, CI is GitHub
   Actions delegating to `greengagedb/greengage-ci`. `greenplum_path.sh`,
   `greenplum_schedule`, Concourse-as-PR-CI and any `arenadata/` path are wrong here, and
   the validator fails on them.
3. Greengage 7.x is PostgreSQL **12.22**. Anything gated on PG 13+ behaviour does not
   apply unless you confirmed it in this tree.
4. Documentation links use `https://greengagedb.org/en/docs-gg/{current|7}/…`.
   **`current` is the Greengage 6 tree**; the `/7/` tree is partial. Link `/current/` and
   note the 7 delta in prose when no `/7/` page exists. Verify a URL resolves before
   citing it.

**One exception, and only one.** `greengage-pg-merge` and the `greengage-pg-merger`
subagent document the PostgreSQL major-version bump, which happens on the campaign branches
in `GreengageDB/greengage_sync` and cannot be grounded in `GreengageDB/greengage` — the
whole subject is a tree that does not exist there. They are grounded on named
`greengage_sync` branches instead (`8.x`, `next`, `claude-merge-*`), and every version
claim in them is verifiable with `git show <branch>:configure.ac`. Rules 2 and 3 still
apply in full: no facts from other Greenplum forks, and no claim about `7.x` that was
actually observed on a campaign branch. If you add a third file that needs this exception,
that is a signal to reconsider the boundary, not to widen it quietly.

## Rule files (`rules/*.md`)

Used by the rule-library skills (`greengage-schema-design`,
`greengage-query-performance`). One rule per file, individually loadable.

Filename is `<section-prefix>-<descriptive-name>.md`; the prefix groups the rule and gives
it a citable id (`schema-distribution-key-choice`). Sections are declared in
`rules/_sections.md`; `rules/_template.md` is the skeleton for new rules.

```markdown
---
title: Choose a distribution key that spreads rows evenly
impact: CRITICAL
impactDescription: "A skewed key makes one segment do all the work; the cluster runs at 1/N speed"
tags: [schema, distribution, skew]
---

## Choose a distribution key that spreads rows evenly

**Impact: CRITICAL**

Why it matters, in terms of the mechanism.

**Incorrect (low-cardinality key concentrates rows on few segments):**

```sql
-- Bad: three distinct values across 24 segments -> 21 segments hold nothing
CREATE TABLE events (...) DISTRIBUTED BY (event_type);
```

**Correct (high-cardinality key spreads evenly):**

```sql
-- Good: event_id is unique, so rows hash uniformly
CREATE TABLE events (...) DISTRIBUTED BY (event_id);
```

Reference: [Table distribution](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
```

Impact ladder:

| Level | Meaning |
|---|---|
| `CRITICAL` | Order-of-magnitude effect, or prevents data loss / cluster damage |
| `HIGH` | 2–10x effect, or significantly limits scalability |
| `MEDIUM-HIGH` | 25–100% effect, or important for a specific workload |
| `MEDIUM` | 10–25% effect, or maintainability |
| `LOW-MEDIUM` | 5–10% effect |
| `LOW` | Minor or edge case |

Every rule needs a real, runnable SQL pair — not pseudo-code — and a `Reference:` link.

## Commands and subagents

Commands live in `commands/<name>.md` with `description` and optional `argument-hint`
frontmatter. They are thin: state the goal, then defer to a skill for the method rather
than duplicating it.

Subagents live in `agents/<name>.md` with `name`, `description`, and `tools` frontmatter.
The `description` decides when the main agent delegates, so it follows the same
trigger-oriented rules as a skill description.

## Before you commit

```bash
python3 tools/validate_skills.py
```

It checks: frontmatter parses and `name` matches the directory; description length and the
presence of a "Use when" clause; `SKILL.md` line cap; relative links resolve; reference
files are at most one level deep; every skill directory appears in `plugin.json`; rule
frontmatter carries a valid `impact`; and no forbidden foreign-fork strings crept in.
