# The Greengage documentation repositories

Lookup material. The published-site facts were read from
`https://greengagedb.org/en/docs-gg/current/intro.html` and its Russian counterpart on
2026-08-31; the repository-layout facts from `docs_tool.py` at commit `0baf5ea`, which
hardcodes the content roots it scans. Items marked **confirm** were inferred from those two
sources and have not been read from the GitLab instance — check them against the checkout
before relying on them.

## Components and where they publish

| Component | Site label | URL segment | Source repository |
|---|---|---|---|
| Greengage DB | Greengage DB | `/docs-gg/` | `gitlab.adsw.io/arenadata/development/docs-greengagedb` |
| gpbackup & gprestore | gpbackup & gprestore | `/docs-backup/` | **confirm** — `docs-backup` is the Antora component name |
| PXF | PXF | `/docs-pxf/` | **confirm** — `docs-pxf` is the Antora component name |

Published URLs are `https://greengagedb.org/{en|ru}/{component}/{version}/{page}.html`.
The version selector currently offers **7.5.0**, **6.31.0 (current)** and **6.30.1** — so
`current` is the Greengage 6 tree, exactly as it is for the product documentation links in
[AGENTS.md](../../../AGENTS.md). A page that exists under `/7/` may not exist under
`/current/` and the reverse is also true; check the one you cite.

`docs_tool` reports cross-component references it cannot resolve on stderr rather than
calling them broken:

```
note: 2 referenced component(s) left unchecked -- docs-backup, docs-pxf
      pass --external-root NAME=PATH for each one you have checked out locally
```

**An unchecked component looks exactly like a healthy one.** Check out the siblings and
pass `--external-root` whenever the review covers cross-component links.

## Repository layout

Each language is its own Antora component version, with its own descriptor:

```
<docs repo>/
  en/antora.yml                       # component name, version, start_page
  en/modules/<module>/
    nav.adoc                          # the left navigation
    pages/*.adoc                      # one file per published page
    partials/*.adoc                   # included fragments, never published alone
    examples/                         # include::example$…[] content, .sql and others
    images/                           # image:: targets
  ru/antora.yml
  ru/modules/<module>/…               # the same tree, mirrored file for file
```

`docs_tool` resolves everything through the relative roots `en/modules` and `ru/modules`
(`docs_tool.py:70-71`) and reads `en/antora.yml` as `EN_MODULES_ROOT.parent / "antora.yml"`
(`docs_tool.py:867`). Modules are discovered as the union of the directory names under both
roots, so a multi-module site works and a single `ROOT` module is just the one-element case.

Three consequences worth stating outright:

- **Run every check from the repository root.** Anywhere else the tool exits `2` rather than
  scanning nothing and reporting success.
- **EN and RU are paired by identical content-relative path**, then compared *by line index*.
  The mirror is structural, not approximate.
- **A page absent from `nav.adoc` is unreachable on the site** even though it builds. That is
  what `RF02` reports, and `start_page` from `antora.yml` is the one exemption.

## Getting a checkout

The instance needs credentials; nothing here assumes they are present.

```bash
# Preferred: a checkout the user already has, passed as a path.
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/doc_checks.py --repo ~/ws/docs-greengagedb

# With a token in the environment (never on the command line - argv is world readable):
git clone https://oauth2:${GITLAB_TOKEN}@gitlab.adsw.io/arenadata/development/docs-greengagedb.git
```

For a merge request the API serves the diff without a clone, which is enough for the
judgement layers but not for `refs` or `l10n` — those need the whole tree:

```bash
# GitLab wants the project path URL-encoded; %2F is the / separator.
PROJECT=arenadata%2Fdevelopment%2Fdocs-greengagedb
BASE="https://gitlab.adsw.io/api/v4/projects/$PROJECT"
curl -sf --header "PRIVATE-TOKEN: $GITLAB_TOKEN" "$BASE/merge_requests/<iid>/changes"
curl -sf --header "PRIVATE-TOKEN: $GITLAB_TOKEN" "$BASE/merge_requests/<iid>/versions"
```

**Say which of these you used in the report.** A diff-only review cannot see a broken
reference into a file the diff does not touch, and should not imply that it did.

## The glossary

`greengagedb-glossary.psv` ships in the `docs-tool` repository, not in the docs repository.
`TM01` loads it by default and `--glossary PATH` is repeatable, so a project-specific
glossary can be layered on top. Format and matching semantics are in
[greengage-docs-style/reference/glossary.md](../../greengage-docs-style/reference/glossary.md).
