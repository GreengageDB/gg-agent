#!/usr/bin/env python3
"""Run the mechanical layers of a Greengage documentation review, in order.

Drives docs_tool.py (external, fetched - see the greengage-docs-review skill) and
adoc_style_check.py (shipped beside this file) over an Antora docs repository, and
prints one layered report. It runs layers 1, 2, 5 and 7 - the ones a program can
settle. Layers 3, 4 and 6 (misprints, grammar, technical correctness) are judgement
and belong to the greengage-docs-reviewer subagent; this script names them as not run
rather than letting silence imply they passed.

Gating matters more than coverage here. Unbalanced delimiters make reference
resolution walk the wrong include chain, and an EN/RU line-count drift makes every
line-indexed comparison after it compare unrelated lines - so a red gate marks the
steps it invalidates UNRELIABLE instead of reporting their findings as fact.

Usage:
    python3 scripts/doc_checks.py [--repo PATH] [--page NAME ...] [--layers LIST]
                                  [--offline] [--no-gate] [--beta]
                                  [--docs-tool PATH] [--external-root NAME=PATH ...]
                                  [--glossary PATH] [--report PATH]

Exit status is 1 when any layer reports findings, 2 on a usage error, 0 otherwise.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STYLE_CHECK = HERE / "adoc_style_check.py"

# docs_tool.py is not vendored: it carries no licence. See the skill for the fetch recipe.
DOCS_TOOL_URL = "https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py"
DOCS_TOOL_CACHE = Path.home() / ".cache" / "gg-agent" / "docs_tool.py"

# Our own rules, split so each lands in the layer it belongs to.
STRUCTURE_RULES = [
    "SG-H1-COUNT", "SG-HEADING-SKIP", "SG-HEADING-DEPTH", "SG-HEADING-DOT",
    "SG-HEADING-LINK", "SG-PAGE-ATTRS", "SG-ADMON-WARNING", "SG-ADMON-CAPTION",
]
GUIDELINE_RULES = [
    "SG-LINK-NEWTAB", "SG-LINK-NOFOLLOW", "SG-IMG-ALT", "SG-IMG-WIDTH",
    "SG-TYPOGRAPHY", "SG-TRADEMARK",
]
# adoc_style_check treats an explicit --rule as "the author asked for this one by name" and
# runs it whether or not it is beta. So the beta ids live here and are only requested when
# --beta is passed - otherwise naming them would silently defeat the default.
GUIDELINE_RULES_BETA = [
    "SG-COLON-BEFORE", "SG-TABLE-EMPTY", "SG-LIST-SINGLE", "SG-BUTTON", "SG-ABBREV",
]

JUDGEMENT_LAYERS = {
    3: ("Misprints", "spelling and typography in prose - proofread the changed pages"),
    4: ("Grammar", "voice, tense, articles, punctuation, sentence length"),
    6: ("Technical correctness", "every claim checked against the pinned Greengage ref"),
}

# gate id -> what a red gate invalidates about the steps that declare it
GATES = {
    "delimiters": "an unclosed delimiter makes the include chain resolve differently, "
                  "so unresolved references may be an artefact of the markup",
    "lines": "EN and RU are compared by line index, so once the line counts differ "
             "every finding below points at an unrelated line",
}


class Step:
    """One command in a layer, plus the gate it opens or depends on."""

    def __init__(self, name: str, argv: list[str], *, needs_docs_tool: bool = False,
                 network: bool = False, opens: str = "", gated_by: str = "") -> None:
        self.name, self.argv = name, argv
        self.needs_docs_tool, self.network = needs_docs_tool, network
        self.opens, self.gated_by = opens, gated_by
        self.rc: int | None = None
        self.output = ""
        self.skipped = ""
        self.unreliable = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIPPED"
        if self.rc is None:
            return "NOT RUN"
        if self.rc == 0:
            return "clean"
        if self.rc == 1:
            return "UNRELIABLE" if self.unreliable else "FINDINGS"
        return f"ERROR (exit {self.rc})"


def resolve_docs_tool(explicit: Path | None, repo: Path) -> Path | None:
    for candidate in (explicit, os.environ.get("DOCS_TOOL"), repo / "docs_tool.py", DOCS_TOOL_CACHE):
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def run(step: Step, cwd: Path) -> None:
    try:
        proc = subprocess.run(step.argv, cwd=cwd, capture_output=True, text=True, timeout=1800)
    except (FileNotFoundError, PermissionError) as exc:
        step.rc, step.output = 2, f"cannot run: {exc}"
        return
    except subprocess.TimeoutExpired:
        step.rc, step.output = 2, "timed out after 1800s"
        return
    step.rc = proc.returncode
    step.output = (proc.stdout + proc.stderr).strip()


def build_layers(args, docs_tool: Path | None, repo: Path) -> list[tuple[int, str, list[Step]]]:
    dt = [sys.executable, str(docs_tool)] if docs_tool else ["docs_tool.py"]
    pages: list[str] = []
    for page in args.page:
        pages += ["--page", page]
    roots: list[str] = []
    for root in args.external_root:
        roots += ["--external-root", root]
    glossary = ["--glossary", args.glossary] if args.glossary else []

    style = [sys.executable, str(STYLE_CHECK), "--repo", str(repo)]
    if args.beta:
        style.append("--beta")

    def rules(ids: list[str]) -> list[str]:
        out: list[str] = []
        for rid in ids:
            out += ["--rule", rid]
        return out

    layers = [
        (1, "AsciiDoc and markup", [
            # The delimiter rule is its own step because it is the only one that gates:
            # a stray dash or an odd backtick says nothing about the include chain, and
            # bundling them would let an unrelated finding suppress reference resolution.
            Step("docs_tool check chars", dt + ["check", "chars"] + pages, needs_docs_tool=True),
            Step("docs_tool check markup --backticks",
                 dt + ["check", "markup", "--backticks"] + pages, needs_docs_tool=True),
            Step("docs_tool check markup --delimiters",
                 dt + ["check", "markup", "--delimiters"] + pages,
                 needs_docs_tool=True, opens="delimiters"),
            Step("adoc_style_check (structure)", style + rules(STRUCTURE_RULES)),
        ]),
        (2, "Links and references", [
            Step("docs_tool check refs", dt + ["check", "refs"] + pages + roots,
                 needs_docs_tool=True, gated_by="delimiters"),
            Step("docs_tool check links", dt + ["check", "links"],
                 needs_docs_tool=True, network=True),
        ]),
        (5, "EN/RU consistency", [
            Step("docs_tool check l10n --lines", dt + ["check", "l10n", "--lines"] + pages,
                 needs_docs_tool=True, opens="lines"),
            Step("docs_tool check l10n (structure, nav, examples)",
                 dt + ["check", "l10n", "--structure", "--nav", "--examples"] + pages,
                 needs_docs_tool=True, gated_by="lines"),
            Step("docs_tool check l10n --untranslated",
                 dt + ["check", "l10n", "--untranslated"] + pages,
                 needs_docs_tool=True, gated_by="lines"),
            Step("docs_tool check terms", dt + ["check", "terms"] + pages + glossary,
                 needs_docs_tool=True, gated_by="lines"),
        ]),
        (7, "Guideline compliance", [
            Step("docs_tool check style", dt + ["check", "style"] + pages, needs_docs_tool=True),
            Step("adoc_style_check (house rules)",
                 style + rules(GUIDELINE_RULES + (GUIDELINE_RULES_BETA if args.beta else []))),
        ]),
    ]
    return [layer for layer in layers if layer[0] in args.layer_set]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path("."), help="docs repository root")
    parser.add_argument("--page", action="append", default=[], metavar="NAME",
                        help="narrow reporting to this page (repeatable)")
    parser.add_argument("--layers", default="1,2,5,7",
                        help="comma-separated layer numbers to run (default 1,2,5,7)")
    parser.add_argument("--offline", action="store_true", help="skip the network link check")
    parser.add_argument("--no-gate", action="store_true",
                        help="report gated steps as findings even when their gate is red")
    parser.add_argument("--beta", action="store_true", help="include heuristic style rules")
    parser.add_argument("--docs-tool", type=Path, default=None, help="path to docs_tool.py")
    parser.add_argument("--external-root", action="append", default=[], metavar="NAME=PATH",
                        help="sibling docs checkout for cross-component refs (repeatable)")
    parser.add_argument("--glossary", default=None, help="path to a glossary .psv")
    parser.add_argument("--report", type=Path, default=None, help="write the report here")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / "en" / "modules").is_dir() and not (repo / "ru" / "modules").is_dir():
        print(f"{repo} has no en/modules or ru/modules - this is not a docs repository root.\n"
              f"Pass --repo PATH pointing at the checkout.", file=sys.stderr)
        return 2

    try:
        args.layer_set = {int(x) for x in args.layers.split(",") if x.strip()}
    except ValueError:
        print(f"--layers takes comma-separated numbers, got {args.layers!r}", file=sys.stderr)
        return 2

    docs_tool = resolve_docs_tool(args.docs_tool, repo)
    layers = build_layers(args, docs_tool, repo)

    red_gates: dict[str, str] = {}
    for _, _, steps in layers:
        for step in steps:
            if step.needs_docs_tool and docs_tool is None:
                step.skipped = "docs_tool.py not found"
                continue
            if step.network and args.offline:
                step.skipped = "--offline"
                continue
            if step.gated_by in red_gates and not args.no_gate:
                step.unreliable = red_gates[step.gated_by]
            run(step, repo)
            if step.opens and step.rc == 1:
                red_gates[step.opens] = f"{step.name} is red - {GATES[step.opens]}"

    lines: list[str] = ["# Documentation checks", "", f"Repository: `{repo}`"]
    if args.page:
        lines.append(f"Pages: {', '.join(args.page)}")
    lines.append(f"docs_tool.py: `{docs_tool}`" if docs_tool else
                 "docs_tool.py: **not found** - layers 1, 2, 5 and 7 ran only the checks "
                 "shipped with this plugin. Fetch it (see below) and re-run before trusting "
                 "a clean result.")
    lines += ["", "| Layer | Step | Status |", "|---|---|---|"]

    any_findings = False
    for number, title, steps in layers:
        for step in steps:
            lines.append(f"| {number} {title} | {step.name} | {step.status} |")
            if step.status == "FINDINGS":
                any_findings = True
    for number in sorted(JUDGEMENT_LAYERS):
        name, what = JUDGEMENT_LAYERS[number]
        lines.append(f"| {number} {name} | - | NOT RUN - judgement: {what} |")

    for number, title, steps in layers:
        for step in steps:
            if step.status in ("clean", "SKIPPED"):
                continue
            lines += ["", f"## Layer {number} - {step.name} ({step.status})"]
            if step.unreliable:
                lines.append(f"**Treat these as unreliable.** {step.unreliable}")
            lines += ["", "```", step.output or "(no output)", "```"]

    report = "\n".join(lines)
    print(report)
    if args.report:
        args.report.write_text(report + "\n", encoding="utf-8")
        print(f"\nreport written to {args.report}", file=sys.stderr)
    if not docs_tool:
        print(f"\nnote: docs_tool.py was not found. Fetch it with\n"
              f"      curl --create-dirs -o {DOCS_TOOL_CACHE} {DOCS_TOOL_URL}", file=sys.stderr)
    return 1 if any_findings else 0


if __name__ == "__main__":
    sys.exit(main())
