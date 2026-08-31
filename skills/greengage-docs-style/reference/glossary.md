# The Greengage terminology glossary

Lookup material. Read from `greengagedb-glossary.psv` in `andreyaksenov/docs-tool` at commit
`0baf5ea` on 2026-08-31: 149 lines — 16 comment lines, one header, **132 data rows** over 124
distinct English terms. It ships with the tool, not with the documentation repositories, and
carries no licence: read it, do not copy it here.

## Format

Pipe-delimited, four columns, declared by the header line:

```
en|ru|ru_pattern|note
based on Greenplum|на основе Greenplum|основ<> Greenplum|
Greengage DB|Greengage DB|Greengage DB|do-not-translate
master host|мастер-хост|мастер-хост<>|
Transparent Huge Pages|Transparent Huge Pages|Transparent Huge Pages|do-not-translate
```

The delimiter is `|` because prose contains commas but never pipes, so nothing needs quoting
or escaping. `#`-prefixed and blank lines are stripped. A row without exactly four fields is
skipped with a warning on stderr — **check stderr before trusting a clean `TM01` run.**

| Column | Meaning |
|---|---|
| `en` | the English term, matched case-insensitively on word boundaries |
| `ru` | the canonical Russian rendering, for humans — *not* used for matching |
| `ru_pattern` | what the checker matches: space-separated tokens, all of which must be present |
| `note` | why the row exists; informational, but it is where the sense distinctions live |

**Reading it as guidance rather than running it:** use `en`, `ru` and `note`, and ignore
`ru_pattern`. The file says so itself. Coverage is curated from observed drift, not
exhaustive — a term's absence is not permission.

## How matching works

Each `ru_pattern` token becomes a case-insensitive word-boundary regex. A `word<>` token is a
**stem**: the marker is dropped and the stem prefix-matches any Russian ending, so `таблиц<>`
covers таблица, таблицы, таблицу and the rest. A bare token must match exactly, which is how
do-not-translate terms, SQL keywords and abbreviations are pinned.

A pattern is satisfied when **all** of its tokens are found somewhere in the Russian line. An
entry is satisfied when **any one** of its patterns is — rows sharing an `en` value merge, so
a term with two acceptable translations passes on either.

`TM01` then counts occurrences of the English term in the EN line and the satisfied patterns
in the RU line at the same index, and reports when the Russian side has fewer:

```
MISMATCH  ru/…:LINE: term 'x' -- expected one of ['…'], not found
```

## Two things that make TM01 lie

- **It is line-indexed.** EN line *i* is compared against RU line *i*. If `LN01` reports a
  line-count drift, every `MISMATCH` is comparing unrelated lines. Fix parity first; the
  pipeline gates on this for exactly this reason.
- **It is marked beta by the tool.** A Russian sentence can render a term correctly with a
  word the glossary does not list, and it will be reported. Confirm each hit against the `ru`
  and `note` columns before it becomes a finding.

## Senses, and why one term has several rows

The rows that matter most are the ones distinguishing meanings that English collapses:

```
backup|бэкап|бэкап<>|
backup|резервное копирование|резервн<> копирован<>|sense: backup as a process/mode … rather than the artifact itself
connection|подключение|подключени<>|sense: the client's act of connecting / a connection slot
connection|соединение|соединени<>|sense: the link/channel itself (e.g. SSL connection, connection string)
partition|раздел|раздел<>|sense: window partition (PARTITION BY / OVER), as opposed to a table partition
```

**A sense note is a review instruction, not trivia.** "Connection" rendered as соединение in a
sentence about connection slots is wrong even though the glossary lists соединение, and
`TM01` will pass it. That check belongs to a reader.

Six rows are marked `do-not-translate` — including `Greengage DB` and `Transparent Huge
Pages`. Nineteen carry a `note`. `write-ahead logging` maps to the bare acronym `WAL`,
because the acronym is what running Russian prose uses.

Passing another glossary is supported and repeatable: `--glossary PATH`.
