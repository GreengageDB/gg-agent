#!/usr/bin/env python3
"""Validate the Greengage skills plugin.

Checks structure, frontmatter, cross-links and manifest consistency, plus a
porting-regression guard for strings that belong to other Greenplum forks.

Usage:
    python3 tools/validate_skills.py [--strict]

--strict turns warnings into errors. Exit status is non-zero on any error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
IMPACTS = {"CRITICAL", "HIGH", "MEDIUM-HIGH", "MEDIUM", "LOW-MEDIUM", "LOW"}

DESCRIPTION_MIN = 200
DESCRIPTION_MAX = 700
SKILL_MAX_LINES = 400

# Strings that mean content was copied from another Greenplum fork without being
# re-grounded against GreengageDB/greengage. See AGENTS.md "Grounding rules".
FORBIDDEN = {
    "greenplum_path.sh": "the Greengage environment script is greengage_path.sh",
    "greenplum_schedule": "the Greengage regression schedule is greengage_schedule",
    "greenplum-db-devel": "the Greengage install dir is greengage-db-devel",
    "arenadata/": "no arenadata/ directory exists in GreengageDB/greengage",
}

errors: list[str] = []
warnings: list[str] = []


def err(where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def warn(where: str, msg: str) -> None:
    warnings.append(f"{where}: {msg}")


def parse_frontmatter(text: str, where: str) -> dict | None:
    """Parse the leading YAML frontmatter block.

    Deliberately hand-rolled: this script must run with no third-party
    dependencies. Handles the flat scalar and one-level-nested mapping shapes
    the authoring contract allows, which is all our frontmatter uses.
    """
    if not text.startswith("---\n"):
        err(where, "missing YAML frontmatter (file must start with '---')")
        return None
    end = text.find("\n---", 3)
    if end == -1:
        err(where, "frontmatter is not terminated by a '---' line")
        return None
    block = text[4:end]

    data: dict = {}
    current_parent: str | None = None
    for raw in block.split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[0] in " \t"
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if indented and current_parent:
            data.setdefault(current_parent, {})
            if isinstance(data[current_parent], dict):
                data[current_parent][key] = value.strip("\"'")
            continue
        if value == "":
            current_parent = key
            data.setdefault(key, {})
        else:
            current_parent = None
            data[key] = value.strip("\"'")
    return data


def check_forbidden(path: Path, text: str) -> None:
    rel = path.relative_to(ROOT)
    for needle, why in FORBIDDEN.items():
        if needle in text:
            for i, line in enumerate(text.split("\n"), 1):
                if needle in line:
                    err(f"{rel}:{i}", f"forbidden string {needle!r} - {why}")
                    break


def check_links(path: Path, text: str) -> None:
    rel = path.relative_to(ROOT)
    for target in LINK_RE.findall(text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            err(str(rel), f"broken relative link -> {target}")


def validate_skill(skill_dir: Path) -> None:
    name = skill_dir.name
    rel = skill_dir.relative_to(ROOT)

    if not SKILL_NAME_RE.match(name):
        err(str(rel), "directory name must be kebab-case")
    if not name.startswith("greengage-"):
        err(str(rel), "skill directories must be prefixed 'greengage-'")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        err(str(rel), "missing SKILL.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    where = str(skill_md.relative_to(ROOT))
    check_forbidden(skill_md, text)
    check_links(skill_md, text)

    fm = parse_frontmatter(text, where)
    if fm is None:
        return

    if fm.get("name") != name:
        err(where, f"frontmatter name {fm.get('name')!r} != directory name {name!r}")

    desc = fm.get("description", "")
    if not desc:
        err(where, "frontmatter is missing 'description'")
    else:
        if len(desc) < DESCRIPTION_MIN:
            err(where, f"description is {len(desc)} chars, minimum {DESCRIPTION_MIN}")
        elif len(desc) > DESCRIPTION_MAX:
            warn(where, f"description is {len(desc)} chars, over {DESCRIPTION_MAX}")
        if "use when" not in desc.lower() and "use whenever" not in desc.lower():
            err(where, "description must contain a 'Use when ...' trigger clause")

    if fm.get("license") != "Apache-2.0":
        err(where, "frontmatter 'license' must be Apache-2.0")

    meta = fm.get("metadata")
    if not isinstance(meta, dict):
        err(where, "frontmatter is missing a 'metadata' block")
    else:
        for key in ("author", "version", "greengageVersion"):
            if key not in meta:
                err(where, f"metadata is missing '{key}'")

    body_lines = len(text.split("\n"))
    if body_lines > SKILL_MAX_LINES:
        warn(where, f"{body_lines} lines, over the {SKILL_MAX_LINES}-line guideline")

    if "See also" not in text:
        warn(where, "no 'See also:' cross-link block")

    # Supporting files: at most one level deep, and validated in their own right.
    for sub in sorted(skill_dir.rglob("*.md")):
        if sub == skill_md:
            continue
        depth = len(sub.relative_to(skill_dir).parts)
        subrel = str(sub.relative_to(ROOT))
        if depth > 2:
            err(subrel, "supporting files must be at most one directory deep")
        sub_text = sub.read_text(encoding="utf-8")
        check_forbidden(sub, sub_text)
        check_links(sub, sub_text)
        if sub.parent.name == "rules" and not sub.name.startswith("_"):
            validate_rule(sub, sub_text)


def validate_rule(path: Path, text: str) -> None:
    where = str(path.relative_to(ROOT))
    fm = parse_frontmatter(text, where)
    if fm is None:
        return
    if not fm.get("title"):
        err(where, "rule frontmatter is missing 'title'")
    impact = fm.get("impact", "")
    if impact not in IMPACTS:
        err(where, f"rule impact {impact!r} not one of {sorted(IMPACTS)}")
    if "Reference:" not in text:
        warn(where, "rule has no 'Reference:' documentation link")
    if "```sql" not in text:
        warn(where, "rule has no SQL example")


def validate_markdown_dir(dirname: str, required_keys: tuple[str, ...]) -> None:
    d = ROOT / dirname
    if not d.is_dir():
        return
    for path in sorted(d.glob("*.md")):
        where = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        check_forbidden(path, text)
        check_links(path, text)
        fm = parse_frontmatter(text, where)
        if fm is None:
            continue
        for key in required_keys:
            if not fm.get(key):
                err(where, f"frontmatter is missing '{key}'")


def validate_manifests(skill_dirs: list[Path]) -> None:
    plugin_path = ROOT / ".claude-plugin" / "plugin.json"
    market_path = ROOT / ".claude-plugin" / "marketplace.json"

    for p in (plugin_path, market_path):
        if not p.is_file():
            err(str(p.relative_to(ROOT)), "missing")
            return

    try:
        plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
        json.loads(market_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        err(".claude-plugin", f"invalid JSON: {exc}")
        return

    # `commands` and `agents` must be arrays when present. A bare string parses as
    # JSON but is rejected by `claude plugin install` with "agents: Invalid input",
    # and the failure only shows up at install time. Both default to ./commands and
    # ./agents, so the usual fix is to omit them entirely.
    for key in ("commands", "agents", "skills"):
        if key in plugin and not isinstance(plugin[key], list):
            err("plugin.json", f"{key!r} must be an array, not {type(plugin[key]).__name__}")

    listed = {s.rstrip("/").removeprefix("./") for s in plugin.get("skills", [])}
    actual = {f"skills/{d.name}" for d in skill_dirs}

    for missing in sorted(actual - listed):
        err("plugin.json", f"skill directory {missing} is not listed in skills[]")
    for extra in sorted(listed - actual):
        err("plugin.json", f"skills[] lists {extra}, which does not exist")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args()

    skills_root = ROOT / "skills"
    skill_dirs = sorted(d for d in skills_root.iterdir() if d.is_dir()) if skills_root.is_dir() else []

    if not skill_dirs:
        err("skills/", "no skill directories found")

    for d in skill_dirs:
        validate_skill(d)

    validate_markdown_dir("commands", ("description",))
    validate_markdown_dir("agents", ("name", "description"))
    validate_manifests(skill_dirs)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    print(
        f"\n{len(skill_dirs)} skills checked - "
        f"{len(errors)} error(s), {len(warnings)} warning(s)"
    )

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
