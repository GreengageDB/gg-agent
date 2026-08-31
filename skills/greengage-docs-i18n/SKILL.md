---
name: greengage-docs-i18n
description: Keep the English and Russian Greengage documentation in step - the line-for-line mirror model the tooling depends on, docs_tool's l10n family (line count, structure skeleton, nav, examples, untranslated and suspect lines), the sync repair path, and the Russian rules a parity check cannot see. Use when EN and RU pages have drifted, when a check prints MISSING, DIFF, UNTRANSLATED, SUSPECT or "no ru counterpart", when a page was edited in one language only, or before publishing a translated page.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# EN and RU as one document in two files

The Russian documentation is not a translation that lives its own life. It is a **line-for-
line mirror** of the English tree: same module, same filename, same structure, same line
count. Every automated EN/RU check depends on that, and every one of them degrades into
noise the moment it stops being true.

That is not a style preference — it is the data model. `docs_tool` pairs the two files by
identical content-relative path and then compares them **by line index**: EN line *i*
against RU line *i*. Nothing reconciles them semantically.

## Line-count parity is the foundation, not a formality

`LN01` looks trivial and is the most important rule in the family. Once the counts differ,
`LN03` compares an English sentence against an unrelated Russian one, `TM01` reports a
missing term that is present two lines down, and `LN02`'s diff points at the wrong place.
Every downstream finding becomes a coin flip.

So the order is fixed:

```bash
python3 ~/.cache/gg-agent/docs_tool.py check l10n --lines            # gate
python3 ~/.cache/gg-agent/docs_tool.py check l10n --structure --nav --examples
python3 ~/.cache/gg-agent/docs_tool.py check l10n --untranslated
python3 ~/.cache/gg-agent/docs_tool.py check terms
```

`doc_checks.py` enforces this gate and marks the later steps `UNRELIABLE` when `LN01` is
red. **Do not read past a red gate**, and do not pass `--no-gate` to make the report look
complete.

## What each rule actually proves

| Rule | Proves | Does not prove |
|---|---|---|
| `LN01 --lines` | the two files have the same number of lines | that any line corresponds to its counterpart |
| `LN02 --structure` *(beta)* | headings, block titles, delimiters, block attributes and `include::`s match | that the prose between them says the same thing |
| `LN03 --untranslated` *(beta)* | a RU line is byte-identical to EN, or carries English stopwords | that a translated line is *correctly* translated |
| `LN04 --examples` | `examples/` hold the same files; non-`.sql` byte-identical, `.sql` compared with comments blanked | that the translated SQL comments are right |
| `LN05 --nav` | EN and RU navigation have the same depth and the same link targets | that the translated labels are right — labels are ignored by design |
| `TM01 terms` *(beta)* | a glossary term has a house-style rendering somewhere on the line | that the rendering matches the sense of the sentence |

Read that right-hand column before writing "EN/RU parity: clean". **Every one of these
rules is structural.** A Russian page can pass the whole family and say something the
English page does not.

## The failure modes, and what each one means

| Report | Means | Do |
|---|---|---|
| `MISSING … (no ru counterpart)` | the page exists only in EN | a page must exist in both trees (guide 5651) — this is a BLOCKER, not a backlog item |
| `MISSING … (no en counterpart)` | RU-only page | usually a rename that landed on one side; find the EN name before deleting anything |
| `DIFF` from `LN01`/`LN02` | the pages drifted structurally | almost always an EN edit not carried across |
| `UNTRANSLATED` | the RU line is still the English one | real, and the most common defect after an EN edit |
| `SUSPECT` | the RU line carries English stopwords | often a false positive on a line quoting a product name or a config snippet — confirm before reporting |
| `MISMATCH` from `TM01` | glossary term rendered with a non-house word | confirm against the glossary's `ru` and `note` columns |

## Repair with `sync`, then read what it produced

When an English page has been edited and the Russian one has not, `docs_tool sync` realigns
them instead of leaving a translator to diff by hand:

```bash
python3 ~/.cache/gg-agent/docs_tool.py sync en/modules/ROOT/pages/<page>.adoc --dry-run
python3 ~/.cache/gg-agent/docs_tool.py sync en/modules/ROOT/pages/<page>.adoc
python3 ~/.cache/gg-agent/docs_tool.py check l10n --untranslated --page <page>.adoc
```

It writes **only** the RU file, inserts new English lines untranslated, marks reworded
paragraphs `// STALE VERSION:` and stranded Russian blocks `// POSSIBLY ORPHANED:`.

Three things follow. It is **beta**, so read its diff before keeping it. Its output is a
scaffold with English text in it, so a synced page is *less* finished than before even
though `LN01` now passes. And those markers are the deliverable — a sync whose
`// STALE VERSION:` comments were deleted without a translator reading them has hidden the
drift rather than fixed it.

## Never make a parity rule pass by padding

The tempting fix for `LN01` is to add or delete a blank line until the counts match. It
works, it is invisible in review, and it destroys the only thing that made the comparison
meaningful — after it, `LN03` and `TM01` compare misaligned lines and report *nothing*,
which reads exactly like success.

The same applies to translating a line yourself to clear an `UNTRANSLATED` report. Report
it and let a translator write it, unless you were asked to translate.

## The Russian rules no parity check can see

Structural parity says nothing about whether the Russian is right. These are the recurring
ones (source lines in
[greengage-docs-style/reference/styleguide-rules.md](../greengage-docs-style/reference/styleguide-rules.md)):

- **Hyphenate an English word before a Russian one** — `SQL-команды` or `Команды SQL`, never
  `SQL команды` (guide 5898).
- **Do not decline English terms left in Russian** — `Количество процессов reducer`, not
  `Количество reducer-ов` (5904).
- **Translate selectively.** Only terms with a well-known Russian analogue; give the English
  in parentheses on first mention (5899). `backpressure`, `bare metal`, `firewall`,
  `split-brain`, `on-premises` and `Java heap` stay in English.
- **Abbreviation expansions are comma-separated** — `(Access Control List, ACL)` (5900).
- **Admonition captions are the Russian ones** — `.ПРИМЕЧАНИЕ`, `.ВАЖНО`, `.ВНИМАНИЕ`,
  `.РЕКОМЕНДАЦИЯ` (3583–3586).
- **Units are the Russian abbreviations** — `КБ МБ ГБ ТБ ПБ`, `Кбит Мбит Гбит` (5226–5228).
- **RU pages link to RU targets** (5662), and `alt`, `title` and `description` are translated
  too (6536).
- **No `ё`** — that one `ST01` does catch.

## What not to do

- **Do not report `SUSPECT` lines as findings without reading them.** It is a stopword
  heuristic and it fires on legitimate Russian prose quoting English identifiers.
- **Do not equalise line counts to clear `LN01`.**
- **Do not assume the EN page is the correct one.** It usually is, because EN is edited
  first — but a fix applied only to RU is a real pattern, and reverting it is a regression.
- **Do not treat a translated `nav.adoc` label as a parity failure.** `LN05` ignores labels
  deliberately; only depth and targets must match.
- **Do not run the l10n family from anywhere but the repository root.** It exits `2` rather
  than reporting a false clean, and that exit is the check working.

See also: [greengage-docs-review](../greengage-docs-review/SKILL.md) ·
[greengage-docs-style](../greengage-docs-style/SKILL.md) ·
[greengage-docs-verify](../greengage-docs-verify/SKILL.md) ·
[greengage-overview](../greengage-overview/SKILL.md) ·
[greengage-docs-style/reference/glossary.md](../greengage-docs-style/reference/glossary.md)
