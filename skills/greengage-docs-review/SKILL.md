---
name: greengage-docs-review
description: Review the Greengage documentation repositories layer by layer - the Antora en/ru tree layout, docs_tool.py's 23 rules across chars, markup, refs, links, l10n, terms and style, the gating order that keeps later layers from reporting noise, severity triage, and posting findings on a GitLab merge request. Use when reviewing a docs merge request or a page set, when a check prints BROKEN, ORPHANED, MISMATCH or "no ru counterpart", or when asked whether the documentation matches a Greengage release.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Reviewing the Greengage documentation

The documentation is not in the source tree. It lives in its own Antora repositories, in
two languages that must stay line-for-line parallel, and it describes a database whose
behaviour changes every release. That produces four independent ways to be wrong — broken
markup, a broken reference, a Russian page that drifted from its English original, and a
sentence that was true two versions ago — and only the first two announce themselves.

This skill owns the pipeline: what runs, in what order, and how to read the result. The
judgement layers have their own skills, linked at the point of need below.

## The seven layers, and why the order is not a preference

| # | Layer | Settled by | Skill |
|---|---|---|---|
| 1 | AsciiDoc and markup | `docs_tool check chars markup`, `adoc_style_check` structure rules | this one |
| 2 | Links and references | `docs_tool check refs`, then `check links` | this one |
| 3 | Misprints | reading the prose | [greengage-docs-style](../greengage-docs-style/SKILL.md) |
| 4 | Grammar | reading the prose against the style guide | [greengage-docs-style](../greengage-docs-style/SKILL.md) |
| 5 | EN/RU consistency | `docs_tool check l10n terms`, then reading both | [greengage-docs-i18n](../greengage-docs-i18n/SKILL.md) |
| 6 | Technical correctness | the Greengage source at a pinned ref, or a live cluster | [greengage-docs-verify](../greengage-docs-verify/SKILL.md) |
| 7 | Guideline compliance | `docs_tool check style terms`, `adoc_style_check` house rules | [greengage-docs-style](../greengage-docs-style/SKILL.md) |

**A red early layer makes a later layer lie, and this is mechanical, not stylistic.**
Two gates carry that weight:

- **Unbalanced delimiters invalidate reference resolution.** `MK02` flattens the include
  chain to check delimiters; `RF01` walks that same chain to resolve `xref:` and
  `include::`. An unclosed `----` changes which lines are part of which block, so the
  "broken" references it reports may be an artefact of the markup.
- **A line-count drift invalidates every EN/RU comparison below it.** `docs_tool` pairs
  EN and RU by *line index* — `LN03` and `TM01` compare EN line *i* against RU line *i*.
  Once `LN01` reports a count mismatch, everything downstream points at unrelated lines.

`doc_checks.py` encodes both gates: it marks the affected steps `UNRELIABLE` rather than
reporting their findings as fact. Fix the gate, re-run, then read what is left.

## Establish three things before running anything

Say all three back before you start, and stop if you cannot establish one:

1. **Which repository and which branch.** The docs family is three separate repositories,
   one per Antora component — `docs-gg` (Greengage DB), `docs-backup` (gpbackup &
   gprestore) and `docs-pxf` (PXF). Cross-component `xref:`s only resolve when the sibling
   checkouts are passed with `--external-root`.
2. **Which page set.** Mechanical layers run tree-wide and cost nothing. The judgement
   layers must be bounded — the merge-request diff, an explicit list, or `--page`. An
   unbounded prose review of the whole tree does not finish and does not pay.
3. **Which Greengage ref the prose is checked against** — a tag like `7.4.1`, or a branch.
   Without it layer 6 is not runnable. Say that plainly instead of guessing a version;
   "documented behaviour matches some release" is not a review.

Repository layout, access recipes and the version map are in
[reference/docs-repos.md](reference/docs-repos.md).

## The happy path

`docs_tool.py` is the engine for layers 1, 2, 5 and 7. It is not vendored here — it
carries no licence — so fetch it once and pin it:

```bash
curl --create-dirs -o ~/.cache/gg-agent/docs_tool.py \
  https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py
```

Then drive the whole mechanical pipeline from the docs repository root:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/doc_checks.py \
  --repo <docs checkout> \
  --external-root docs-pxf=../docs-pxf --external-root docs-backup=../docs-backup \
  --report /tmp/doc-review.md
```

Useful narrowings: `--page resource_groups.adoc` (repeatable), `--layers 1,2` to gate
before spending anything on prose, `--offline` to skip the network link check, `--beta`
to add the heuristic style rules. `--no-gate` reports gated steps as findings anyway —
use it only when you have already established the gate is a false alarm.

To run one family directly, from the repository root:

```bash
python3 ~/.cache/gg-agent/docs_tool.py check refs --external-root docs-pxf=../docs-pxf
python3 ~/.cache/gg-agent/docs_tool.py check l10n --structure --verbose --page intro.adoc
python3 ~/.cache/gg-agent/docs_tool.py check chars markup --page UNCOMMITTED
```

The full rule inventory — 23 rules, their ids, flags and what each actually catches — is
in [reference/docs-tool.md](reference/docs-tool.md).

## `docs_tool` refuses to run outside the repository root, and that refusal is a feature

It resolves content through the hardcoded relative roots `en/modules` and `ru/modules`
(`docs_tool.py:70-71`), so from anywhere else it would scan nothing and exit `0`. It
detects that and exits `2` instead. **Never read a clean result you did not run from the
root**, and never "fix" this by passing absolute paths.

Two more results that are not what they look like:

- **Exit `0` from `check links` does not mean every link is healthy.** Only a dead link
  fails the run; permanent redirects and unreachable hosts are reported and not failed,
  and `401`/`403`/`429`/`5xx` collapse into a count unless you pass `--show-unverified`.
- **A `--page` that matches nothing exits `2`**, deliberately — a typo in a page name
  would otherwise look like a clean page.

## A clean mechanical run is not a reviewed document

Everything above is layers 1, 2, 5 and 7, and even there the coverage is partial: `style`
holds three rules, `terms` one. Nothing in it reads a sentence. A document can pass every
check and still say that a GUC defaults to a value it has not defaulted to since 6.x.

So a report that stops at the tool output is not a review. State explicitly which
judgement layers you ran, over which pages, and which you did not.

## Severity, and what earns a finding

| Severity | What qualifies | Examples |
|---|---|---|
| **BLOCKER** | breaks the build or the published page, or states something false | `RF01` broken `xref:`, a missing RU counterpart, a wrong GUC default or CLI flag |
| **MAJOR** | the reader is misled or cannot navigate | orphaned page, dead external link, untranslated RU line, missing page attributes, a claim that is right for one line and wrong for the other |
| **MINOR** | house style, typography, consistency | `ё`, typographic quotes, missing `opts=nofollow`, heading punctuation |

Every finding carries the file, the line, the rule id where one exists, and what to change.
A finding a writer cannot act on without asking you a question is not finished.

## Report

Lead with what was reviewed: repository, branch, page set, the Greengage ref, and which
layers ran. Then findings in severity order, grouped by file. Then, explicitly, **what you
did not check** — the layers you skipped, the pages outside the bounded set, and anything
that needs a running cluster to settle.

For a merge request, post inline where the finding has a line, and one summary note.
Resolve the SHAs first; a discussion without a valid `position` is rejected:

```bash
# GitLab wants the project path URL-encoded; %2F is the / separator.
PROJECT=arenadata%2Fdevelopment%2Fdocs-greengagedb
curl -sf --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.adsw.io/api/v4/projects/$PROJECT/merge_requests/<iid>/versions"
```

Then one `POST` per finding to `.../merge_requests/<iid>/discussions` with
`position[position_type]=text`, `position[base_sha]`, `position[start_sha]`,
`position[head_sha]`, `position[new_path]` and `position[new_line]`, and one `POST` to
`.../notes` for the summary. End the summary with exactly:

```
---
_Generated with [greengage plugin](https://github.com/GreengageDB/gg-agent)_
```

**Print by default; post only when asked.** Check the existing discussions before posting
so a re-run does not stack duplicates on the same head SHA.

## What not to do

- **Do not re-derive by reading what a rule already proved.** If `RF01` says a reference is
  broken, that is the finding; spend the reading budget on the layers no rule covers.
- **Do not report a gated step's findings as fact.** Fix the gate and re-run.
- **Do not edit the RU page to make `LN01` pass.** Padding lines to equalise counts hides
  the drift instead of fixing it — see [greengage-docs-i18n](../greengage-docs-i18n/SKILL.md).
- **Do not copy `docs_tool.py` or its glossary into this repository.** No licence, no
  vendoring. Fetch it at the pinned URL.
- **Do not report a version-dependent claim without naming the ref you checked it against.**
- **Do not treat `[beta]` rules as authoritative.** `ST02`, `ST03`, `LN02`, `LN03`, `TM01`,
  `CH05` and `LK01` are heuristics; confirm each hit before it becomes a finding.

See also: [greengage-docs-style](../greengage-docs-style/SKILL.md) ·
[greengage-docs-i18n](../greengage-docs-i18n/SKILL.md) ·
[greengage-docs-verify](../greengage-docs-verify/SKILL.md) ·
[greengage-overview](../greengage-overview/SKILL.md) ·
[greengage-contribute](../greengage-contribute/SKILL.md) ·
[reference/docs-tool.md](reference/docs-tool.md) ·
[reference/docs-repos.md](reference/docs-repos.md)
