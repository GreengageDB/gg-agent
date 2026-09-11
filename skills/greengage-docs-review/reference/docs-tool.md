# docs_tool.py rule inventory

Lookup material. Read from `andreyaksenov/docs-tool` at commit `0baf5ea` on 2026-08-31, by
running `docs_tool.py list`, `list rules` and `list targets` against that checkout. The tool
is a single stdlib-only Python file (Python 3.7+, no dependencies, `git` used only by
`sync`); re-run `list rules` before quoting a rule id, because the registry is the source of
truth and this table is a copy.

It carries **no licence file**. Fetch and run it; never vendor it into this repository.

```bash
curl --create-dirs -o ~/.cache/gg-agent/docs_tool.py \
  https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py
```

## Families

| Family | Covers | Suggested gate |
|---|---|---|
| `chars` | Unicode and encoding | block |
| `markup` | AsciiDoc syntax | block |
| `refs` | Antora reference resolution | block |
| `style` | Arenadata house style | warn |
| `terms` | controlled vocabulary | warn |
| `l10n` | EN↔RU parity | warn |
| `links` | external URL health (network; run explicitly) | warn |

`suggest:` is advice for a pre-commit hook, not something the tool enforces — every family
uses the same exit codes.

## Rules

| Id | Invocation | Catches | Layer |
|---|---|---|---|
| CH01 | `check chars --no-cyrillic` | Cyrillic characters in `en/` files (RU text left in EN) | 1 |
| CH02 | `check chars --no-cyrillic --target examples` | the same, over `examples/` | 1 |
| CH03 | `check chars --no-invisible` | zero-width, bidi-control and BOM characters | 1 |
| CH04 | `check chars --dashes` | literal en/em dashes; house style is `--` | 1 |
| CH05 | `check chars --homoglyphs` *(beta)* | Latin letters inside Russian words | 1 |
| MK01 | `check markup --backticks` | a line with an odd number of backticks | 1 |
| MK02 | `check markup --delimiters` | a block delimiter left unclosed once includes are flattened | 1 |
| RF01 | `check refs --broken` | `xref:`, `include::`, `image:` targets that do not resolve | 2 |
| RF02 | `check refs --orphaned` | a page no `nav.adoc` reaches | 2 |
| RF03 | `check refs --orphaned --target partials` | a partial nothing includes | 2 |
| RF04 | `check refs --orphaned --target examples` | an example nothing includes | 2 |
| RF05 | `check refs --orphaned --target images` | an image no macro references | 2 |
| RF06 | `check refs --orphaned --target tags` | a `tag::` region nothing pulls | 2 |
| ST01 | `check style --no-yo` | `ё`/`Ё` in `ru/` (`:page-author:` exempt) | 7 |
| ST02 | `check style --file-path-italics` *(beta)* | file and directory names not in `_italics_` | 7 |
| ST03 | `check style --table-cell-periods` *(beta)* | a table cell whose last sentence ends in a period | 7 |
| TM01 | `check terms` *(beta)* | an EN glossary term rendered with a non-house RU word | 5, 7 |
| LN01 | `check l10n --lines` | EN file and its RU counterpart differ in line count | 5 |
| LN02 | `check l10n --structure` *(beta)* | EN and RU structural skeletons differ | 5 |
| LN03 | `check l10n --untranslated` *(beta)* | RU line identical to EN, or carrying English stopwords | 5 |
| LN04 | `check l10n --examples` | `examples/` differ (byte-wise; `.sql` comment-stripped) | 5 |
| LN05 | `check l10n --nav` | EN and RU `nav.adoc` structures differ | 5 |
| LK01 | `check links` *(beta, network)* | external links: 404 fails; redirects and unreachable hosts are reported | 2 |

Seven rules are marked `[beta]` by the tool itself — `CH05`, `ST02`, `ST03`, `TM01`, `LN02`,
`LN03`, `LK01`. Confirm each hit before it becomes a finding.

## `--target` values

| Value | Scans |
|---|---|
| `pages` | `pages/` + `partials/` (the default) |
| `partials` | `partials/` only |
| `examples` | `examples/` |
| `images` | `images/` |
| `tags` | `tag::` / `end::` regions in pages, partials and examples |
| `nav` | `nav.adoc` |
| `all` | every target above |

## Flags that change the answer

| Flag | Effect |
|---|---|
| `--page NAME` | narrows *reporting*; corpus-building rules still scan the whole tree. A name matching nothing exits `2`. `--page UNCOMMITTED` takes the stems from `git status --porcelain` |
| `--external-root NAME=PATH` | resolves cross-component references against a sibling checkout. Without it those components are listed on stderr as "left unchecked", not reported broken |
| `--glossary PATH` | glossary for `TM01`; repeatable |
| `--offline` | skip network work in `check links` |
| `--show-unverified` | list the `401`/`403`/`429`/`5xx` links that otherwise collapse into a count |
| `--allow-domain HOST` | treat a host as healthy without probing it |
| `--link-cache PATH` | JSON cache with a 7-day TTL; off unless passed |
| `--verbose` | full diffs for `LN02`, visible markers for `CH03` |

## Output and exit codes

Findings print as a `FILE <path>` header followed by indented `path:line:col: text`, with
`BROKEN`, `ORPHANED`, `MISSING`, `DIFF`, `REDIRECT`, `UNREACHABLE`, `MISMATCH`,
`UNTRANSLATED` and `SUSPECT` labels. A clean rule prints `OK: …`. Multi-rule runs print
`=== CH01  check chars --no-cyrillic ===` section headers.

| Exit | Meaning |
|---|---|
| `0` | everything passed — but for `check links`, only a *dead* link can fail |
| `1` | a rule found something |
| `2` | usage error: run outside a docs tree, a `--page` matching nothing, or `--<rule>` flags spanning more than one family |

There is no JSON or SARIF output, no `--fix`, no inline suppression comment, and no
baseline file. Do not write a report that implies otherwise.

## `sync` — the EN→RU repair path

`docs_tool.py sync <en-file> [--dry-run]` aligns a RU page to its EN original: it inserts
new EN lines untranslated, marks reworded paragraphs `// STALE VERSION:` and stranded RU
blocks `// POSSIBLY ORPHANED:`, and writes **only** the RU file. Run
`check l10n --untranslated` afterwards. It is beta, and it is a starting point for a
translator, not a translation.
