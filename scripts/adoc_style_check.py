#!/usr/bin/env python3
"""Check Antora AsciiDoc pages against the Arenadata Syntax & Grammar guide.

Covers the mechanically checkable house rules that docs_tool.py does not implement -
page metadata, heading shape, admonitions, external-link attributes, image attributes,
typography and forbidden constructs. Findings print as `path:line:col: [ID] message`,
the same shape docs_tool.py emits, so both tools' output merges into one report.

Stable rules are the ones that do not fire on correct prose. Beta rules need `--beta`;
they catch real defects but depend on heuristics that a legitimate page can trip.

Usage:
    python3 scripts/adoc_style_check.py [--repo PATH] [FILE ...]
                                        [--beta] [--rule ID ...] [--list]

Exit status is 1 when any finding is reported, 2 on a usage error, 0 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EN_MODULES = Path("en/modules")
RU_MODULES = Path("ru/modules")

# Every page must declare these (syntax-grammar.md:5655, :5937).
REQUIRED_PAGE_ATTRS = (":page-productlogo:", ":page-author:", ":page-htmltitle:", ":description:")

# Only two block-image widths are permitted (syntax-grammar.md:2385-2402).
ALLOWED_IMAGE_WIDTHS = ("724", "362")

ADMONITIONS = ("NOTE", "TIP", "IMPORTANT", "CAUTION", "WARNING")

# Rule id -> (severity, one-line description, beta?)
RULES: dict[str, tuple[str, str, bool]] = {
    "SG-H1-COUNT":        ("MAJOR", "exactly one H1 per page", False),
    "SG-HEADING-SKIP":    ("MAJOR", "heading levels must not skip", False),
    "SG-HEADING-DEPTH":   ("MINOR", "at most three heading levels", False),
    "SG-HEADING-DOT":     ("MINOR", "no dot at the end of a heading", False),
    "SG-HEADING-LINK":    ("MINOR", "no links in headings", False),
    "SG-PAGE-ATTRS":      ("MAJOR", "page is missing a required attribute", False),
    "SG-ADMON-WARNING":   ("MAJOR", "[WARNING] is not used; use [CAUTION]", False),
    "SG-ADMON-CAPTION":   ("MINOR", "admonition block needs a caption", False),
    "SG-LINK-NEWTAB":     ("MINOR", "external link must open in a new tab (^)", False),
    "SG-LINK-NOFOLLOW":   ("MINOR", "external link needs opts=nofollow", False),
    "SG-IMG-ALT":         ("MAJOR", "image needs an alt attribute", False),
    "SG-IMG-WIDTH":       ("MINOR", "PNG image needs width=724 or width=362", False),
    "SG-TYPOGRAPHY":      ("MINOR", "use straight quotes and -- for dashes", False),
    "SG-TRADEMARK":       ("MINOR", "do not use the symbols (c), (r) or (tm)", False),
    "SG-COLON-BEFORE":    ("MINOR", "no colon before an image or a table", True),
    "SG-TABLE-EMPTY":     ("MINOR", "empty table cell; enter -- instead", True),
    "SG-LIST-SINGLE":     ("MINOR", "a list should have at least two items", True),
    "SG-BUTTON":          ("MINOR", "do not write the word 'button' after a UI element", True),
    "SG-ABBREV":          ("MINOR", "spell the word out (info, docs, app)", True),
}

HEADING_RE = re.compile(r"^(=+)\s+(\S.*)$")
ATTR_ENTRY_RE = re.compile(r"^:[\w!-]+:")
BLOCK_ATTR_RE = re.compile(r"^\[(.+)\]\s*$")
BLOCK_TITLE_RE = re.compile(r"^\.\S")
# Link macros: `https://host/path[...]` and `link:https://host/path[...]`.
LINK_MACRO_RE = re.compile(r"(?<![\w\\])(?:link:)?(https?://[^\s\[\]]+)\[([^\]]*)\]")
IMAGE_RE = re.compile(r"^image::([^\[]+)\[([^\]]*)\]")
TYPOGRAPHY = {"“": "\"", "”": "\"", "‘": "'", "’": "'"}
TRADEMARKS = {"©": "(c)", "®": "(r)", "™": "(tm)"}
ABBREVS = re.compile(r"(?<![\w-])(info|docs|app)(?![\w-])", re.IGNORECASE)
BUTTON_RE = re.compile(r"\*_[^_]+_\*\s+button\b", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^([*.]+|-)\s+\S")

# Delimiters that open a verbatim or non-prose block. `|===` is deliberately absent:
# table content is prose and several rules need to see it.
VERBATIM_DELIMS = ("----", "....", "////", "++++")


class Finding:
    __slots__ = ("path", "line", "col", "rule", "message")

    def __init__(self, path: str, line: int, col: int, rule: str, message: str) -> None:
        self.path, self.line, self.col, self.rule, self.message = path, line, col, rule, message

    def render(self) -> str:
        sev = RULES[self.rule][0]
        return f"{self.path}:{self.line}:{self.col}: [{self.rule}/{sev}] {self.message}"


def mask_line(line: str) -> str:
    """Blank out inline code spans and comments, preserving column offsets."""
    if line.lstrip().startswith("//"):
        return " " * len(line)
    out = list(line)
    in_code = False
    i = 0
    while i < len(out):
        if out[i] == "`":
            in_code = not in_code
            out[i] = " "
        elif in_code:
            out[i] = " "
        i += 1
    return "".join(out)


def scan(path: Path, rel: str, enabled: set[str], is_page: bool) -> list[Finding]:
    """Run every enabled rule over one file."""
    try:
        raw_lines = path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(rel, 1, 1, "SG-H1-COUNT", f"cannot read: {exc}")]

    found: list[Finding] = []
    def add(lineno: int, col: int, rule: str, msg: str) -> None:
        if rule in enabled:
            found.append(Finding(rel, lineno, col, rule, msg))

    verbatim: str | None = None
    in_table = False
    heading_levels: list[tuple[int, int, str]] = []   # (lineno, level, text)
    prev_line = ""
    list_run: list[int] = []
    list_marker = ""

    for n, raw in enumerate(raw_lines, 1):
        stripped = raw.strip()

        # Verbatim blocks: skip everything inside, but keep tracking the delimiter.
        if verbatim is not None:
            if stripped == verbatim:
                verbatim = None
            prev_line = raw
            continue
        if stripped in VERBATIM_DELIMS:
            verbatim = stripped
            prev_line = raw
            continue
        if stripped == "|===":
            in_table = not in_table

        line = mask_line(raw)

        # --- headings -------------------------------------------------------
        m = HEADING_RE.match(line)
        if m and not in_table:
            level, text = len(m.group(1)), m.group(2).strip()
            heading_levels.append((n, level, text))
            if level > 3:
                add(n, 1, "SG-HEADING-DEPTH",
                    f"heading level {level}; use bold text instead of a fourth level")
            if text.endswith(".") and not text.endswith(".."):
                add(n, len(raw), "SG-HEADING-DOT", "heading ends with a dot")
            if "xref:" in text or "link:" in text or "http" in text:
                add(n, 1, "SG-HEADING-LINK", "heading contains a link")

        # --- admonitions ----------------------------------------------------
        battr = BLOCK_ATTR_RE.match(stripped)
        admon = battr.group(1).split(",")[0].strip() if battr else ""
        if admon == "WARNING" or stripped.startswith("WARNING:"):
            add(n, 1, "SG-ADMON-WARNING", "[WARNING] is not used in our documentation; use [CAUTION]")
        if admon in ADMONITIONS and not BLOCK_TITLE_RE.match(prev_line.strip()):
            add(n, 1, "SG-ADMON-CAPTION", f"[{admon}] block has no caption line above it")

        # --- external links -------------------------------------------------
        for lm in LINK_MACRO_RE.finditer(line):
            attrs = lm.group(2)
            col = lm.start() + 1
            if "^" not in attrs:
                add(n, col, "SG-LINK-NEWTAB", f"external link {lm.group(1)} has no ^ (open in a new tab)")
            if "nofollow" not in attrs:
                add(n, col, "SG-LINK-NOFOLLOW", f"external link {lm.group(1)} has no opts=nofollow")

        # --- images ---------------------------------------------------------
        im = IMAGE_RE.match(stripped)
        if im:
            target, attrs = im.group(1), im.group(2)
            if "alt=" not in attrs:
                add(n, 1, "SG-IMG-ALT", f"image {target} has no alt attribute")
            if target.lower().endswith(".png"):
                wm = re.search(r"width=(\d+)", attrs)
                if not wm:
                    add(n, 1, "SG-IMG-WIDTH", f"PNG image {target} has no width attribute")
                elif wm.group(1) not in ALLOWED_IMAGE_WIDTHS:
                    add(n, 1, "SG-IMG-WIDTH",
                        f"image width {wm.group(1)}; only {' and '.join(ALLOWED_IMAGE_WIDTHS)} are used")
            if prev_line.strip().endswith(":"):
                add(n - 1, len(prev_line), "SG-COLON-BEFORE", "colon before an image")
        if stripped == "|===" and prev_line.strip().endswith(":"):
            add(n - 1, len(prev_line), "SG-COLON-BEFORE", "colon before a table")

        # --- typography and forbidden symbols -------------------------------
        for ch, want in TYPOGRAPHY.items():
            idx = line.find(ch)
            if idx != -1:
                add(n, idx + 1, "SG-TYPOGRAPHY", f"typographic {ch!r}; write {want!r}")
        for ch, name in TRADEMARKS.items():
            idx = line.find(ch)
            if idx != -1:
                add(n, idx + 1, "SG-TRADEMARK", f"remove the {name} symbol")

        # --- beta prose rules ------------------------------------------------
        bm = BUTTON_RE.search(line)
        if bm:
            add(n, bm.start() + 1, "SG-BUTTON", "drop the word 'button' after the UI element name")
        if not ATTR_ENTRY_RE.match(stripped) and not stripped.startswith("image:"):
            am = ABBREVS.search(line)
            if am:
                full = {"info": "information", "docs": "documentation", "app": "application"}
                add(n, am.start() + 1, "SG-ABBREV",
                    f"write {full[am.group(1).lower()]!r}, not {am.group(1)!r}")

        # --- tables ----------------------------------------------------------
        if in_table and stripped.startswith("|") and stripped != "|===":
            body = stripped[1:]
            if "||" in body or body.endswith("|"):
                add(n, 1, "SG-TABLE-EMPTY", "empty table cell; enter -- if there is no value")

        # --- lists -----------------------------------------------------------
        lm2 = LIST_ITEM_RE.match(stripped)
        if lm2:
            marker = lm2.group(1)
            if marker != list_marker:
                flush_single_item_list(list_run, list_marker, add)
                list_run, list_marker = [], marker
            list_run.append(n)
        elif not stripped or stripped == "+":
            pass
        else:
            flush_single_item_list(list_run, list_marker, add)
            list_run, list_marker = [], ""

        prev_line = raw

    flush_single_item_list(list_run, list_marker, add)

    # --- whole-file rules ----------------------------------------------------
    h1s = [h for h in heading_levels if h[1] == 1]
    if is_page:
        if not h1s:
            add(1, 1, "SG-H1-COUNT", "page has no H1 title")
        elif len(h1s) > 1:
            for lineno, _, text in h1s[1:]:
                add(lineno, 1, "SG-H1-COUNT", f"second H1 on the page: {text!r}")
        head = "\n".join(raw_lines[:40])
        for attr in REQUIRED_PAGE_ATTRS:
            if attr not in head:
                add(1, 1, "SG-PAGE-ATTRS", f"page does not declare {attr}")

    prev_level = 0
    for lineno, level, text in heading_levels:
        if prev_level and level > prev_level + 1:
            add(lineno, 1, "SG-HEADING-SKIP",
                f"heading jumps from level {prev_level} to {level}: {text!r}")
        prev_level = level

    return found


def flush_single_item_list(run: list[int], marker: str, add) -> None:
    if len(run) == 1 and marker:
        add(run[0], 1, "SG-LIST-SINGLE", "list has a single item")


def discover(repo: Path) -> list[tuple[Path, bool]]:
    """Every .adoc under en/modules and ru/modules, flagged page or not."""
    out: list[tuple[Path, bool]] = []
    for base in (EN_MODULES, RU_MODULES):
        root = repo / base
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.adoc")):
            if any(part.startswith(".") for part in path.parts):
                continue
            parts = path.relative_to(root).parts
            is_page = len(parts) > 1 and parts[1] == "pages"
            out.append((path, is_page))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, metavar="FILE",
                        help="specific .adoc files; default is the whole docs tree")
    parser.add_argument("--repo", type=Path, default=Path("."), help="docs repository root")
    parser.add_argument("--beta", action="store_true", help="also run the heuristic rules")
    parser.add_argument("--rule", action="append", default=[], metavar="ID",
                        help="run only this rule (repeatable)")
    parser.add_argument("--list", action="store_true", help="list the rules and exit")
    args = parser.parse_args()

    if args.list:
        for rid, (sev, desc, beta) in RULES.items():
            print(f"{rid:20} {sev:6} {desc}{'  [beta]' if beta else ''}")
        return 0

    enabled = {r for r, (_, _, beta) in RULES.items() if args.beta or not beta}
    if args.rule:
        unknown = [r for r in args.rule if r not in RULES]
        if unknown:
            print(f"unknown rule(s): {', '.join(unknown)}", file=sys.stderr)
            print("run with --list to see the rule ids", file=sys.stderr)
            return 2
        enabled = set(args.rule)

    if args.files:
        targets = [(f, "/pages/" in str(f).replace("\\", "/")) for f in args.files]
        missing = [f for f, _ in targets if not f.is_file()]
        if missing:
            print(f"no such file: {missing[0]}", file=sys.stderr)
            return 2
    else:
        targets = discover(args.repo)
        if not targets:
            print(f"no en/modules or ru/modules under {args.repo} - run from the docs repo root, "
                  f"or pass --repo PATH", file=sys.stderr)
            return 2

    findings: list[Finding] = []
    for path, is_page in targets:
        try:
            rel = str(path.relative_to(args.repo))
        except ValueError:
            rel = str(path)
        findings.extend(scan(path, rel, enabled, is_page))

    current = None
    for f in sorted(findings, key=lambda f: (f.path, f.line, f.rule)):
        if f.path != current:
            print(f"FILE {f.path}")
            current = f.path
        print(f"  {f.render()}")

    by_rule: dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
    if findings:
        print("\n" + ", ".join(f"{r}={c}" for r, c in sorted(by_rule.items())))
    print(f"{len(targets)} file(s) checked - {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
