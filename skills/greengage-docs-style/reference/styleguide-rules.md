# Arenadata Syntax & Grammar rules, as a review checklist

Lookup material. Extracted on 2026-08-31 from the Arenadata *Syntax & Grammar* guide
(internal BookStack wiki, `wiki.adsw.io/books/syntax-grammar`; the copy read here was a
6,638-line HTML export). Line numbers are that export's, quoted so a disputed rule can be
read in full rather than argued from memory. Re-read the wiki before treating any of these
as current — this is a snapshot of a living document.

Rules with an **id** are implemented by `adoc_style_check.py`; the rest need a reader.

## Page structure and metadata

| Rule | Line | id |
|---|---|---|
| Every page has a title, defined with `= `. Add only one H1 per document | 5635 | `SG-H1-COUNT` |
| Maximum three header levels, and never skip a level (H1 ⇒ H3). For a fourth, use bold text | 5637 | `SG-HEADING-DEPTH`, `SG-HEADING-SKIP` |
| Sentence case for all headers — first word and proper nouns only. No title case, including in the left navigation | 5638 | — |
| Do not use a dot at the end of headers | 5644 | `SG-HEADING-DOT` |
| Do not use links in headers | 5642 | `SG-HEADING-LINK` |
| Every page exists in both `en/modules/<module>/pages` and `ru/modules/<module>/pages` | 5651 | — |
| Every page is registered in both the EN and the RU `nav.adoc` | 5652 | — |
| No page may be absent from the left navigation menu | 5653 | — |
| Every page declares a product logo, an author, and `title`/`description` meta tags — `:page-productlogo:`, `:page-author:`, `:page-htmltitle:`, `:description:` | 5654, 3917, 3943 | `SG-PAGE-ATTRS` |

## Admonitions

| Rule | Line | id |
|---|---|---|
| `[WARNING]`/`WARNING:` is not supported in our design — use `[CAUTION]`/`CAUTION:` | 3587 | `SG-ADMON-WARNING` |
| Every admonition has a caption, and only the allowed caption for its type | 5698 | `SG-ADMON-CAPTION` |
| Allowed captions: `.NOTE`/`.ПРИМЕЧАНИЕ`, `.IMPORTANT`/`.ВАЖНО`, `.CAUTION`/`.ВНИМАНИЕ`, `.TIP`/`.РЕКОМЕНДАЦИЯ` | 3583–3586 | — |
| Do not place several admonitions next to each other | 5699 | — |

## Links

| Rule | Line | id |
|---|---|---|
| Every `http`/`https` link opens in a new tab via `^` **and** carries `opts=nofollow`. Does not apply to `xref:` | 5664, 5940 | `SG-LINK-NEWTAB`, `SG-LINK-NOFOLLOW` |
| An internal `xref:` within the same product carries no product name | 5665 | — |
| RU pages link to RU targets, EN pages to EN targets | 5662 | — |
| Link text matches the referenced article's full title, not its short nav name | 5684 | — |
| Avoid vague link text — no "there", "here", "read", "more" | 5666, 6564 | — |
| To show a non-active URL, escape it with a leading backslash | 5686 | — |
| Partials that are only included elsewhere live in `partials/`, not `pages/` | 5691 | — |

## Images

| Rule | Line | id |
|---|---|---|
| Always add the `alt` attribute; translate its value in Russian articles | 5824, 5939, 6536 | `SG-IMG-ALT` |
| Every PNG showing UI declares a width; only `724` (horizontal) and `362` (vertical) are used | 5832, 2384–2386 | `SG-IMG-WIDTH` |
| A text introduction before every image, describing what it shows | 5827 | — |
| A caption under every image, with no font styles in it | 5829, 5830 | — |
| Do not use `:` before an image | 5828 | `SG-COLON-BEFORE` |
| Avoid images of text — a command output belongs in a literal block | 5831 | — |

## Tables and lists

| Rule | Line | id |
|---|---|---|
| No dots in the last sentences of table cells (lists in cells and abbreviations excepted) | 5713 | — (`ST03` in `docs_tool`) |
| No empty cells — enter `--` where there is no meaningful value | 5717 | `SG-TABLE-EMPTY` |
| All tables have column headers, except argument-description tables | 5716 | — |
| A list contains at least two items | 5727 | `SG-LIST-SINGLE` |
| Text introducing a list ends with a colon | 5728 | — |
| Ordered-list items are full sentences: capital letter, terminal dot | 4749 | — |
| A list item starting with a capital ends with `.`; starting lowercase, with `;` and `.` on the last | 4771 | — |
| Commands and their results go in one list item, not two | 5730 | — |

## Source blocks and UI

| Rule | Line | id |
|---|---|---|
| Every code snippet declares the most suitable language | 4052, 5703 | — |
| No captions for source code and literal blocks | 5701 | — |
| Placeholders use `<…>` and are always explained afterwards | 5703 | — |
| Separate a source block (`----`) from its command output (`....`) | 5704 | — |
| OS-level commands start with `$`; SQL and psql input does not | 5705 | — |
| UI element names in bold+italic; menu paths joined with `->` | 5913 | — |
| EN puts the UI element name before its type; RU puts it after | 5919 | — |
| Do not use the word "button" explicitly — `Click OK`, not `Click OK button` | 5925 | `SG-BUTTON` |
| `Press` only for keyboard events; otherwise `Click` | 5926 | — |

## Grammar and word choice

| Rule | Line | id |
|---|---|---|
| American English; prefer the `-ize` spelling | 5051 | — |
| Active voice wherever possible — but passive is legitimate in release notes and to front-load keywords | 5055, 5057 | — |
| Avoid future tense and the word "will"; use simple present | 5178, 5180 | — |
| Use "you" for instructions; "the user" for general explanation | 5096 | — |
| No gender-specific pronouns — *they*/*their*, never *he/she* | 5097 | — |
| The Oxford comma should always be used | 5126 | — |
| Do not join independent clauses with a comma and no conjunction; use `;` | 5154 | — |
| Do not use abbreviations where a full word fits: `information` not `info`, `documentation` not `docs`, `application` not `app` | 5903 | `SG-ABBREV` |
| Do not use `©`, `®`, `TM` | 5906 | `SG-TRADEMARK` |
| Only use acronyms readers know; spell them out; do not introduce one used once | 5216–5218 | — |
| Lowercase the spelled-out form of an acronym except proper nouns | 5220 | — |

## Typography and numbers

| Rule | Line | id |
|---|---|---|
| Every dash is written `--`; a literal en/em dash is a defect | 5896 | — (`CH04` in `docs_tool`) |
| Apostrophes and single quotes are `'`, not `’` | 5901 | `SG-TYPOGRAPHY` |
| Double quotes are `"`, not `“`, in both languages | 5902 | `SG-TYPOGRAPHY` |
| A dot separates the integer and fractional parts, in both languages; commas only inside code | 5897 | — |
| No commas as digit-group separators | 5173 | — |
| Byte units `KB MB GB TB PB` / `КБ МБ ГБ ТБ ПБ`; bit units `Kb Mb…` / `Кбит Мбит…` | 5226–5228 | — |

## Russian-language rules

| Rule | Line |
|---|---|
| Add a hyphen after an English word that precedes a Russian one: `SQL-команды`, not `SQL команды` | 5898 |
| Translate only terms with a well-known Russian analogue; give the English term in parentheses on first mention | 5899 |
| Give an English analogue and its abbreviation as a comma-separated list: `(Access Control List, ACL)` | 5900 |
| Do not decline English terms left in Russian: `Количество процессов reducer`, not `reducer-ов` | 5904 |
| No `ё`/`Ё` (`:page-author:` exempt) | — (`ST01` in `docs_tool`) |
| Fixed translations, including the ones that are *not* translated | 5612–5625 |

The translation table at 5612–5625 is mangled by the HTML export; read it on the wiki. The
entries that most often go wrong: `snapshot` → снепшот (not снапшот), `session` → сессия
(not сеанс), `cache` → кеш, `hash` → хеш, `backup` → бэкап *or* резервная копия by sense,
`Java heap` → left untranslated (never куча), `lifecycle` → жизненный цикл,
`on-premises` → left untranslated and always plural, and `backpressure`, `bare metal`,
`firewall`, `split-brain` left in English.

## Rules that need a reader, not a rule

Do not pretend these are checkable, and do not report them as violations without an
argument: tone and register (5087–5095), whether a table or a list is the right form
(4190), whether an acronym is one readers know (5216), which terms deserve translation
(5899), sentence length — "keep it short" with no threshold (5105), whether a heading fits
the navigation width (5640), and whether an include is worth making (5689).
