---
name: greengage-docs-style
description: Apply the Arenadata Syntax & Grammar guide to Greengage documentation - misprints, grammar and house style in AsciiDoc pages. Covers sentence-case headings, the Oxford comma, active voice and present tense, banned abbreviations and trademark symbols, external-link opts=nofollow, image alt and width, tables, lists, UI element naming and glossary terminology. Use when reviewing prose for layers 3, 4 or 7, when a page reads oddly but passes every check, or when a finding cites SG-, ST01 or TM01.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Style, grammar and misprints

Three of the seven review layers are prose: misprints (3), grammar (4) and guideline
compliance (7). Only the last has meaningful tooling, and even that covers a fraction of the
rules. This skill is how to spend a reader's attention where it pays.

Run [greengage-docs-review](../greengage-docs-review/SKILL.md)'s mechanical layers first.
Everything they catch is a finding you do not have to find.

## Read the changed pages, not the tree

The mechanical layers are free and run everywhere. A prose pass is not, and its value falls
off a cliff outside the pages someone actually changed. Bound it: the merge-request diff,
an explicit page list, or `--page`. If asked to "review the documentation", come back with
the page set you propose rather than starting an unbounded pass.

Read **both** language versions of each page in the set. A misprint in the Russian page is
invisible from the English one, and the two drift in different ways —
[greengage-docs-i18n](../greengage-docs-i18n/SKILL.md) owns that comparison.

## What the tools already settle, so you do not have to look

| Already checked | By |
|---|---|
| Cyrillic in EN files, invisible characters, en/em dashes, homoglyphs | `docs_tool check chars` |
| `ё` in RU, un-italicised file paths, table-cell periods | `docs_tool check style` |
| Glossary terminology | `docs_tool check terms` (`TM01`) |
| Headings, page attributes, admonitions, link attributes, image attributes, typography, trademark symbols | `adoc_style_check.py` |

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adoc_style_check.py --repo <docs checkout> --beta
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adoc_style_check.py --list       # rule ids and severity
```

Without `--beta` it runs only rules that do not fire on correct prose. The beta rules —
`SG-COLON-BEFORE`, `SG-TABLE-EMPTY`, `SG-LIST-SINGLE`, `SG-BUTTON`, `SG-ABBREV` — are
heuristics worth running and worth confirming one by one.

The full rule set with its source lines is in
[reference/styleguide-rules.md](reference/styleguide-rules.md).

## What only a reader catches

Work through these on each page in the set. Name the specific problem or say the page is
clean on that axis — do not skip silently.

**Voice and tense.** Active voice, simple present, no "will" (guide 5057, 5178, 5180). The
guide explicitly permits passive in release notes and to front-load a keyword, so a passive
sentence is a question, not a finding.

**Person.** "You" for instructions, "the user" for explanation; never *he/she* (5096, 5097).

**Headings as sentences.** Sentence case, no terminal dot, no links, no article at the
start, infinitive not gerund — `Create a cluster`, not `Creating a cluster` (5638–5646).
Only the last three are mechanical; sentence-case detection is a reader's job because a
proper noun and a capitalised common noun look identical to a regex.

**Terminology by sense.** The glossary merges rows, so a term with two acceptable Russian
renderings passes on either — and `TM01` cannot tell which sense the sentence is in. The
`note` column carries those distinctions; treat it as a review instruction. See
[reference/glossary.md](reference/glossary.md).

**Misprints in technical tokens.** A misspelled English word is usually obvious; a
misspelled GUC, catalog, function or flag name is not, and it is worse — it turns a correct
sentence into a wrong one. Every identifier is a layer 6 claim; hand it to
[greengage-docs-verify](../greengage-docs-verify/SKILL.md) rather than eyeballing it.

**Structure that reads badly but parses.** A table where a list would do, a list that should
be a table (guide 4190), an admonition stack, an introduction that promises something the
section does not deliver. None of it is checkable and all of it is worth saying.

## `aspell` is worth running and not worth trusting

There is no spellchecker in the pipeline, because AsciiDoc source is mostly identifiers and
a naive run drowns in false positives. If `aspell` is installed, run it as a *hint
generator* over the prose of the changed pages, one language at a time:

```bash
aspell --lang=en --mode=none list < page.adoc | sort -u
aspell --lang=ru --mode=none list < page.adoc | sort -u
```

Then read the list and keep the handful of real misprints. **Never report its output as
findings.** Most entries are product names, GUCs and SQL keywords. If `aspell` is missing,
say the layer was done by reading, and do not claim a spellcheck ran.

## What not to do

- **Do not report a style rule without its source.** Cite the guide line, or the rule id.
  A house rule asserted from memory is how a reviewer loses an argument they were right in.
- **Do not report tone as a defect.** "Warm and friendly" (5087–5095) is guidance for a
  writer, not a finding against one.
- **Do not flag a passive sentence in a release note**, or a capitalised proper noun as a
  title-case violation. Both are the guide's own exemptions.
- **Do not treat glossary silence as approval.** Coverage is curated from observed drift and
  says so; an unlisted term is unreviewed, not correct.
- **Do not fix Russian text by translating from the English yourself** unless asked. Report
  the drift and let a translator decide; a plausible-looking machine rendering is harder to
  spot later than an obviously untranslated line.
- **Do not pile up MINOR findings.** Twenty typography notes bury the one wrong GUC default.
  Group them by rule, give one example each, and say how many there are.

See also: [greengage-docs-review](../greengage-docs-review/SKILL.md) ·
[greengage-docs-i18n](../greengage-docs-i18n/SKILL.md) ·
[greengage-docs-verify](../greengage-docs-verify/SKILL.md) ·
[greengage-contribute](../greengage-contribute/SKILL.md) ·
[reference/styleguide-rules.md](reference/styleguide-rules.md) ·
[reference/glossary.md](reference/glossary.md)
