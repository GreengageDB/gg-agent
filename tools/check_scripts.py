#!/usr/bin/env python3
"""Validate the runtime scripts under scripts/.

Every shipped script must compile, describe itself, and answer --help without a
repository or a network. A script that only fails when an agent runs it against a
real docs tree is a script nobody trusts twice.

Usage:
    python3 tools/check_scripts.py

Exit status is non-zero on any error.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
HELP_TIMEOUT = 60

errors: list[str] = []


def err(where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def check(path: Path) -> None:
    where = str(path.relative_to(ROOT))
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        err(where, f"does not parse: line {exc.lineno}: {exc.msg}")
        return

    doc = ast.get_docstring(tree)
    if not doc:
        err(where, "has no module docstring")
    elif "Usage:" not in doc:
        err(where, "module docstring has no 'Usage:' block")

    if not source.startswith("#!/usr/bin/env python3\n"):
        err(where, "missing the '#!/usr/bin/env python3' shebang")

    # The agent invokes these as `python3 <path>`, so executability is a convention
    # rather than a requirement - but an inconsistent tree invites `./script` calls.
    if not path.stat().st_mode & 0o111:
        err(where, "is not executable (chmod +x)")

    try:
        proc = subprocess.run([sys.executable, str(path), "--help"],
                              capture_output=True, text=True, timeout=HELP_TIMEOUT)
    except subprocess.TimeoutExpired:
        err(where, f"--help did not return within {HELP_TIMEOUT}s")
        return
    if proc.returncode != 0:
        err(where, f"--help exited {proc.returncode}: {proc.stderr.strip()[:200]}")


def main() -> int:
    if not SCRIPTS.is_dir():
        print("no scripts/ directory - nothing to check")
        return 0

    paths = sorted(SCRIPTS.glob("*.py"))
    if not paths:
        err("scripts/", "directory exists but holds no Python scripts")

    for path in paths:
        check(path)

    for e in errors:
        print(f"ERROR {e}")
    print(f"\n{len(paths)} script(s) checked - {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
