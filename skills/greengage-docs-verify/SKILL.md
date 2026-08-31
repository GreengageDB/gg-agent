---
name: greengage-docs-verify
description: Check what the Greengage documentation asserts against the source at a pinned tag or branch - GUC names, defaults and ranges from guc_gp.c, catalog and gp_toolkit columns, SQL synopses from the in-tree sgml reference, gpMgmt utility flags, gpbackup and PXF CLI options, version-gated statements, and when a live cluster is needed instead. Use when reviewing documentation against a release, when prose quotes a default or a flag, or when asked whether a page is still true for 7.x or 6.x.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Checking the documentation against the source

This is the layer no tool covers, and the only one where a finding is unambiguously a bug
rather than a preference. Everything else in a documentation review makes a page better to
read; this makes it true.

The method is narrow and mechanical: **extract every checkable claim, then check each one
against a named ref.** Not "read the page and see if anything looks wrong" — that finds the
claims you already doubted, and the dangerous ones are the ones that read as obvious.

## Pin the ref first, or do not run this layer

A documentation claim is only true relative to a release. Establish the ref before reading
anything, and put it in the report:

```bash
cd <greengage checkout>
git fetch origin --tags
git ls-tree -r --name-only <tag-or-branch> | head -1   # confirm the ref exists
git show <tag>:VERSION
```

If nobody named a ref, ask for one. Do not default to the working tree, to `master` — which
is a stale mirror of the 6.x line — or to "the latest". **7.x is PostgreSQL 12.22 and 6.x is
PostgreSQL 9.4.26**, and a page that is right on one line is routinely wrong on the other.

Read facts with `git show <ref>:<path>`, never from a working tree that may be mid-edit.

## Extract the claims before checking any of them

Go through the page and list every statement that could be false. The recurring classes:

| Claim class | Looks like |
|---|---|
| GUC | a parameter name, its default, its range, its unit, whether a restart is needed |
| Catalog or view | a table, view or column name; the columns of a `gp_toolkit` view |
| SQL syntax | a synopsis, a clause, an option name, what is and is not supported |
| Utility | a `gpMgmt` command, its flags, its output, its exit behaviour |
| Component CLI | a `gpbackup`/`gprestore` or `pxf` flag and its default |
| Version gate | "since 7.x", "not supported in 6.x", "deprecated" |
| Path and port | an install directory, a data directory, a default port |
| Behaviour | "the coordinator dispatches…", "mirrors are…" — the hardest class, and the one where a live cluster earns its cost |

Listing them first is what makes the layer finishable and what makes the report honest: the
claims you checked, the claims you could not, and why.

Where each class is settled — with the 6.x deltas — is in
[reference/source-anchors.md](reference/source-anchors.md).

## Check, and read the definition rather than searching for the string

```bash
git show <ref>:src/backend/utils/misc/guc_gp.c | grep -n -A15 '"gp_resource_manager"'
git show <ref>:src/include/catalog/pg_resgroup.h
git show <ref>:doc/src/sgml/ref/create_resource_group.sgml
git show <ref>:gpMgmt/bin/gpconfig | grep -n 'add_option\|add_argument'
```

**Finding the name in the tree is not confirmation.** A GUC that exists says nothing about
its default; a flag that is parsed says nothing about what it does. Read the definition
record, the bounds, and the assign hook where there is one.

Two traps worth naming:

- **The compiled-in default and the shipped default differ.** `guc_gp.c` holds the former,
  `postgresql.conf.sample` what `initdb` writes. A page describing a fresh cluster means the
  second one.
- **A `gp_toolkit` view moved between the lines** — `gpcontrib/gp_toolkit/gp_toolkit--<v>.sql`
  on 7.x, `src/backend/catalog/gp_toolkit.sql` on 6.x. Reading the wrong file produces a
  confident wrong answer rather than a miss.

## The published page and the source can both be right

The site publishes several versions at once — currently **7.5.0**, **6.31.0 (current)** and
**6.30.1** — and `current` is the Greengage 6 tree. So before reporting a mismatch, establish
which version the page belongs to. A page in the 6 tree describing 6.x behaviour is correct
even when it contradicts 7.x, and reporting it is worse than saying nothing.

The question is never "is this true", it is **"is this true for the version this page
documents"**.

## When a live cluster is worth it

Most claims are settled by the source, faster and more reliably. Use a cluster for effective
values after configuration, a view's real column list, and behaviour that only shows up when
something runs. Bring one up with
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md) and read state with
[greengage-query-performance](../greengage-query-performance/SKILL.md) where a plan is
involved.

`SELECT version()` before anything else — a cluster that is not at the pinned ref answers a
question you did not ask. And a value read from a configured cluster is evidence about that
cluster, not about the release; when they disagree, the source at the ref wins.

## Report

Per claim: the sentence as written, the ref, the file and line that settles it, and what it
should say. A finding here is a **BLOCKER** — the documentation states something false —
even when the fix is one word.

Then say what you could not settle, and why: claims needing a cluster you do not have,
components you have no checkout of, behaviour not visible in the source. **An unchecked
claim reported as checked is the one failure this layer cannot survive.**

## What not to do

- **Do not check against the working tree.** Use `git show <ref>:<path>`.
- **Do not report a 6.x page as wrong for describing 6.x.**
- **Do not infer a default from prose elsewhere in the documentation.** Documentation
  agreeing with itself is not evidence; that is how one wrong value spreads.
- **Do not fix a technical claim by rewording it into vagueness.** "A reasonable default" is
  not a fix for a wrong number.
- **Do not extend a `greengage` fact to gpbackup or PXF.** They are separate repositories on
  their own release cycles — `GreengageDB/gpbackup` (default branch `master`) and
  `GreengageDB/pxf` (default branch `main`).
- **Do not report every identifier you could not find as wrong.** Say you could not confirm
  it, and where you looked.

See also: [greengage-docs-review](../greengage-docs-review/SKILL.md) ·
[greengage-docs-style](../greengage-docs-style/SKILL.md) ·
[greengage-internals](../greengage-internals/SKILL.md) ·
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md) ·
[greengage-backup-restore](../greengage-backup-restore/SKILL.md) ·
[reference/source-anchors.md](reference/source-anchors.md)
