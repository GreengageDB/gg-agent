# Greengage agent skills

Agent skills and a Claude Code plugin for [Greengage DB](https://greengagedb.org/) — the
open-source MPP analytical database built on PostgreSQL, continuing the Greenplum lineage.

An agent reasoning about Greengage from vanilla PostgreSQL intuition gets things
confidently wrong: it forgets that every table has a distribution policy, reads an
`EXPLAIN` without noticing the Motion node that dominates it, runs DDL in utility mode and
desynchronises the cluster, or regenerates a regression answer file that was hiding a real
bug. These skills encode what actually matters — the MPP semantics, the operational traps,
and the exact commands — for both people running Greengage and people hacking on it.

## Install

```
/plugin marketplace add GreengageDB/gg-agent
/plugin install greengage@greengage-agent-skills
```

From a local checkout:

```
/plugin marketplace add /path/to/gg-agent
/plugin install greengage@greengage-agent-skills
```

Skills load on demand — only their names and descriptions sit in context until one is
relevant. Every skill also reads as plain documentation, so `skills/<name>/SKILL.md` is
worth opening directly.

## Skills

Written for **Greengage 7.x** (PostgreSQL 12.22, *coordinator* terminology), with **6.x**
(PostgreSQL 9.4.26, *master* terminology) deltas called out where they change a command.

### Start here

| Skill | Use it when |
|---|---|
| [greengage-overview](skills/greengage-overview/SKILL.md) | You need the lay of the land — cluster model, which version and mode you are in, which of the skills below applies, and where the documentation lives |

### Running and querying Greengage

| Skill | Use it when |
|---|---|
| [greengage-cluster-ops](skills/greengage-cluster-ops/SKILL.md) | Bringing up a demo cluster or attaching to an existing one; a segment is down, degraded, or wedged; `gpstart`/`gpstop`/`gpstate`/`gprecoverseg`/`gpexpand`/`ggrebalance` |
| [greengage-schema-design](skills/greengage-schema-design/SKILL.md) | Choosing a distribution key, heap vs append-optimized vs column storage, compression, partitioning, or types — the decisions that are expensive to reverse |
| [greengage-query-performance](skills/greengage-query-performance/SKILL.md) | A query is slow — reading MPP `EXPLAIN` output, motions and slices, skew, statistics, spill, ORCA vs the Postgres planner |
| [greengage-data-loading](skills/greengage-data-loading/SKILL.md) | Loading or unloading data — `gpfdist`, external tables, `gpload`, `COPY`, error handling, foreign tables, S3 |
| [greengage-workload-management](skills/greengage-workload-management/SKILL.md) | Resource groups vs resource queues, concurrency and memory limits, cgroup prerequisites, moving a running query |
| [greengage-backup-restore](skills/greengage-backup-restore/SKILL.md) | `gpbackup`/`gprestore` (full, partial, incremental, S3), `pg_dump`/`pg_restore`, point-in-time recovery |

### Developing Greengage

| Skill | Use it when |
|---|---|
| [greengage-build](skills/greengage-build/SKILL.md) | Turning a source change into a running binary — configure flags, the 6.x/7.x build split, docker images, and the stale-binary trap |
| [greengage-testing](skills/greengage-testing/SKILL.md) | Running one test or the whole matrix — regress, isolation2, behave, resgroup, JIT, ORCA unit tests; picking the right target and avoiding false passes |
| [greengage-answer-files](skills/greengage-answer-files/SKILL.md) | A failing test's diff looks cosmetic — regenerate (or better, mask) it without burying a real bug |
| [greengage-internals](skills/greengage-internals/SKILL.md) | Writing or reviewing a backend change that has to be MPP-correct — dispatch, motion, distributed transactions, FTS, append-optimized tables |
| [greengage-debug](skills/greengage-debug/SKILL.md) | A crash, assertion failure, hang, or wrong result — logs, reproduction, fault injection, gdb |
| [greengage-ci](skills/greengage-ci/SKILL.md) | A CI run is red — fetching artifacts and classifying each failure as cosmetic, real, or flaky |
| [greengage-contribute](skills/greengage-contribute/SKILL.md) | Preparing a pull request — which branch to target, the CLA, formatting rules, and the review process |
| [greengage-pg-merge](skills/greengage-pg-merge/SKILL.md) | Merging an upstream PostgreSQL major version into the fork — conflict clustering, semantic re-grafting, the phased bring-up, and the traps that recur every bump |

## Commands

| Command | Does |
|---|---|
| `/gg-review` | Review a change for MPP correctness and report findings on the diff |
| `/gg-cluster-up` | Bring up a demo cluster, or attach to and verify an existing one |
| `/gg-health` | Segment configuration, mirror sync, FTS state, disk and skew in one report |
| `/gg-explain` | Run a query under both optimizers and interpret the plans, motions and skew |
| `/gg-test` | Run a regression test or suite correctly for the detected version |
| `/gg-triage-ci` | Fetch a failed CI run's artifacts and classify every failure |
| `/gg-skew` | Data and computational skew report for a table or a whole database |
| `/gg-pg-bump` | Start or continue a PostgreSQL major-version bump on the campaign line |

## Subagents

| Agent | Does |
|---|---|
| `greengage-mpp-reviewer` | Reviews a diff for MPP correctness — dispatch desync, motion and locus, append-optimized aux relations, catalog changes, utility-mode assumptions |
| `greengage-perf-analyst` | End-to-end slow-query analysis: plan, skew, statistics, storage layout, distribution key |
| `greengage-pg-merger` | Runs a PostgreSQL major-version bump: conflict inventory, semantic resolution, and the compile → unit-test → initdb → regress → isolation2 → CI ladder |

## Use it on GitHub pull requests

The plugin can review pull requests in place. Add a workflow that installs it from this
marketplace, and Claude answers when someone writes `@claude` on a PR:

```yaml
# .github/workflows/claude.yml
name: Claude
on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

jobs:
  claude:
    if: contains(github.event.comment.body, '@claude')
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 1
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          plugin_marketplaces: "https://github.com/GreengageDB/gg-agent.git"
          plugins: "greengage@greengage-agent-skills"
          claude_args: |
            --allowedTools "mcp__github_inline_comment__create_inline_comment,Bash(gh pr diff:*),Bash(gh pr view:*),Bash(gh pr comment:*),Read,Grep,Glob,Agent,Skill"
```

The only secret required is `ANTHROPIC_API_KEY`. Then comment
`@claude review this for MPP correctness` — or name the reviewer explicitly with
`@claude @agent-greengage:greengage-mpp-reviewer review this`.

Passing `github_token` is what avoids needing the Claude GitHub App installed on the
repository: the action returns that token immediately instead of exchanging an OIDC token
for an app token. The cost is that comments are authored by `github-actions[bot]` rather
than `claude[bot]`, and `use_sticky_comment` stops working. Inline comments are unaffected,
but they do require `pull-requests: write`.

Two things worth knowing. The `plugin_marketplaces` URL **must end in `.git`**; the action
rejects `owner/repo` shorthand and SSH URLs. And the inline-comment MCP server only starts
when `claude_args` names `mcp__github_inline_comment__create_inline_comment`, so keep that
entry even though the review flow implies it. Claude posts inline comments and a summary —
it cannot submit a formal GitHub review or approve a PR.

A repo-level `CLAUDE.md` telling Claude to delegate to
`@agent-greengage:greengage-mpp-reviewer` makes a bare `@claude review this` route
correctly without anyone remembering the agent's name.

## Scope

Everything above covers Greengage as it ships, on the `7.x` and `6.x` lines. One thing here
does not: merging a new upstream PostgreSQL major version into the fork is a separate
discipline — conflict clustering, semantic re-grafting, a phased bring-up — carried out on
the campaign branches in
[`GreengageDB/greengage_sync`](https://github.com/GreengageDB/greengage_sync), whose `8.x`
line is already past both shipping lines.

That work is covered by [greengage-pg-merge](skills/greengage-pg-merge/SKILL.md) and the
`greengage-pg-merger` subagent, and only by those two. They say so at the top, they cite
`greengage_sync` branches by name, and they are the one deliberate exception to the
grounding rule in [AGENTS.md](AGENTS.md) that facts must come from `GreengageDB/greengage`.
Anything else you read here is about the shipping lines; do not carry a command from a
campaign branch into a `7.x` answer without checking that the file still has that name.

## Contributing

Read [AGENTS.md](AGENTS.md) — it is the authoring contract: structure, frontmatter, voice,
version handling, and the grounding rules that keep facts tied to
`GreengageDB/greengage`. Then:

```bash
python3 tools/validate_skills.py     # structure, frontmatter, links, manifests
python3 tools/check_doc_links.py     # external documentation URLs (needs network)
```

## License

Apache-2.0. See [LICENSE](LICENSE).
