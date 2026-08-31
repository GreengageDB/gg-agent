---
description: Review Greengage documentation layer by layer and report findings on the pages or the merge request
argument-hint: "[docs repo path or MR] [--against <greengage tag/branch>] [--page NAME]"
---

Review the documentation: $ARGUMENTS

Delegate the analysis to the **greengage-docs-reviewer** subagent — it owns the layered
pipeline and the failure modes that survive a careful read. This command establishes what is
being reviewed, drives that agent, and decides where the findings go.

## 1. Establish the target

Never review a description of a change. Get the actual pages.

- **A local checkout** — the normal case, and the only form that supports every layer.
  Reference resolution and EN/RU parity need the whole tree, not a diff.
- **A merge request** — resolve the project and the iid, then fetch the changes over the
  API. `gitlab.adsw.io` needs `GITLAB_TOKEN`; if it is unset, say so and ask for a checkout
  path rather than failing halfway through.

  ```bash
  # GitLab wants the project path URL-encoded; %2F is the / separator.
  PROJECT=arenadata%2Fdevelopment%2Fdocs-greengagedb
  BASE="https://gitlab.adsw.io/api/v4/projects/$PROJECT"
  curl -sf --header "PRIVATE-TOKEN: $GITLAB_TOKEN" "$BASE/merge_requests/<iid>/changes"
  ```

  **Echo the resolved project, branch and merge-request title before doing any work** — the
  title is what makes a wrong target obvious at a glance.
- **Nothing given** — the checkout in the working directory, if it has `en/modules` or
  `ru/modules`. If it does not, this is not a docs repository; say so and stop.

Note which components the pages link across to. `docs-gg`, `docs-backup` and `docs-pxf` are
separate repositories, and a cross-component reference with no `--external-root` is reported
as "left unchecked", which reads exactly like healthy.

## 2. Establish the Greengage ref

Layer 6 checks what the prose asserts against the source at a named tag or branch. Ask for
one if the arguments do not carry it, and **say in the report which ref you used**. Without a
ref, layer 6 does not run — report that rather than implying the prose was verified.

## 3. Run the mechanical layers

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/doc_checks.py \
  --repo <docs checkout> --report /tmp/doc-review.md
```

`--page NAME` narrows it, `--layers 1,2` gates cheaply before spending anything on prose,
`--offline` skips the network link check, `--beta` adds the heuristic rules. It needs
`docs_tool.py`, which is not vendored — it carries no licence — and prints the fetch command
when it is missing.

Read the gates before reading the findings. A step marked `UNRELIABLE` has a red gate above
it and its evidence points at the wrong lines.

## 4. Delegate

`@agent-greengage:greengage-docs-reviewer` — give it the page set, the Greengage ref, the
mechanical report, and any context the author supplied about intent. Do not pre-filter the
pages down to what looks interesting; the defects this catches are in the parts that read as
routine.

If the change touches no prose — a rebuild of generated navigation, an image swap, a
whitespace fix — say so and stop. A review that manufactures findings to look thorough is
worse than no review.

## 5. Report

**Locally**, print the findings in severity order and write the report file. For each: the
file and line, what is wrong, and what to change. Separate confirmed defects from what needs
a cluster or a checkout you do not have.

**On a merge request**, post inline where the finding has a line, plus one summary note.
Resolve the SHAs first — a discussion without a valid `position` is rejected:

```bash
curl -sf --header "PRIVATE-TOKEN: $GITLAB_TOKEN" "$BASE/merge_requests/<iid>/versions"
curl -sf --request POST --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --data "body=<the finding>" \
  --data "position[position_type]=text" \
  --data "position[base_sha]=<base_sha>" \
  --data "position[start_sha]=<start_sha>" \
  --data "position[head_sha]=<head_sha>" \
  --data "position[new_path]=<path>" \
  --data "position[new_line]=<line>" \
  "$BASE/merge_requests/<iid>/discussions"
```

Then one `POST` to `$BASE/merge_requests/<iid>/notes` for the summary: what was reviewed,
which layers ran, counts by severity, and what could not be settled. End it with exactly:

```
---
_Generated with [greengage plugin](https://github.com/GreengageDB/gg-agent)_
```

Rules that will otherwise cost you a failed call or a misleading review:

- `new_line` must be a line the diff actually touches, numbered in the head commit. Use
  `position[old_line]` and `old_path` to comment on a removed line.
- The notes are authored by whoever owns the token — a human account, so the findings must be
  marked as generated. Keep the attribution line.
- Post once. Check the existing discussions before posting so a re-run does not stack
  duplicates on the same head SHA.
- **Print by default.** Posting to a repository other people watch is not a default worth
  guessing at; say explicitly in the prompt when you want it posted.

Keep each inline comment short — under ~600 characters. The rule or the source line, the
defect, the fix. Anything longer belongs in the summary.

If the pages are clean, say so plainly and list what you checked.

## Running this from a terminal

```bash
claude -p "/greengage:gg-doc-review ~/ws/docs-greengagedb --against 7.4.1 --page intro.adoc" \
  --permission-mode dontAsk --max-turns 40
```

`-p` starts in `manual`, where every command waits for an approval nobody is there to give —
hence `--permission-mode dontAsk`, or an explicit `--allowedTools` listing
`Bash(python3:*)`, `Bash(git show:*)`, `Read`, `Grep` and `Glob`.
Never pass `--bare`: it skips plugin sync, which removes the knowledge this command applies.

See also: [greengage-docs-review](../skills/greengage-docs-review/SKILL.md) ·
[greengage-docs-style](../skills/greengage-docs-style/SKILL.md) ·
[greengage-docs-i18n](../skills/greengage-docs-i18n/SKILL.md) ·
[greengage-docs-verify](../skills/greengage-docs-verify/SKILL.md)
