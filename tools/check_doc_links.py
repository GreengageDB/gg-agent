#!/usr/bin/env python3
"""Check that every external documentation URL cited by the skills resolves.

Network-dependent, so it is advisory: CI runs it with continue-on-error. Run it
locally before adding a batch of new documentation links.

Usage:
    python3 tools/check_doc_links.py [--host greengagedb.org]
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"https?://[^\s()\[\]<>\"'`]+")
TIMEOUT = 20

# Placeholder URLs in templates and the authoring contract are patterns, not links.
# "$" covers a shell variable standing in for a project path or a host in a snippet.
PLACEHOLDER_MARKERS = ("{", "<", "…", "...", "$")

# Hosts that only ever appear inside worked examples (gpfdist locations, S3
# endpoints). They are not meant to resolve.
EXAMPLE_HOST_RE = re.compile(
    r"^https?://("
    r"(\d{1,3}\.){3}\d{1,3}"          # bare IPv4 literals in examples
    r"|[^/.:]+"                        # single-label hosts: webhost, sdw1, cdw
    r")(:\d+)?(/|$)"
)

# Links this repository cites *because they are broken upstream*. The skills
# report them as dead on purpose - that is the finding, not a defect here.
# Keep the reason with each entry so nobody silently promotes one to "fixed".
KNOWN_BROKEN = {
    "https://greengagedb.org/community/":
        "linked from greengage README.md:222 as the developer mailing list; 404s. "
        "greengage-contribute documents that it is dead.",
    "https://cla.pivotal.io/about#obvious-fixes":
        "linked from greengage README.md:233 for the 'obvious fixes' CLA exemption; "
        "the Pivotal domain is gone. greengage-contribute documents that it is dead.",
}


def collect_urls(host_filter: str | None) -> dict[str, list[str]]:
    urls: dict[str, list[str]] = {}
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for raw in URL_RE.findall(text):
            if any(m in raw for m in PLACEHOLDER_MARKERS):
                continue
            url = raw.rstrip(".,;:")
            if host_filter and host_filter not in url:
                continue
            if url in KNOWN_BROKEN or EXAMPLE_HOST_RE.match(url):
                continue
            urls.setdefault(url, []).append(str(path.relative_to(ROOT)))
    return urls


def check(url: str) -> tuple[str, int | str]:
    try:
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "gg-agent-link-check"}
        )
    except ValueError as exc:  # malformed URL extracted from prose
        return url, f"malformed: {exc}"
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return url, resp.status
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 405):  # some hosts reject HEAD; retry with GET
            try:
                get = urllib.request.Request(url, headers={"User-Agent": "gg-agent-link-check"})
                with urllib.request.urlopen(get, timeout=TIMEOUT) as resp:
                    return url, resp.status
            except Exception as inner:  # noqa: BLE001 - report whatever went wrong
                return url, f"{type(inner).__name__}: {inner}"
        return url, exc.code
    except Exception as exc:  # noqa: BLE001 - network errors are the point here
        return url, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=None, help="only check URLs containing this host")
    args = parser.parse_args()

    urls = collect_urls(args.host)
    if not urls:
        print("no URLs found")
        return 0

    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, status in pool.map(check, urls):
            if status != 200:
                failures.append((url, status, urls[url]))

    for url, status, sources in sorted(failures):
        print(f"FAIL {status}  {url}")
        for src in sorted(set(sources)):
            print(f"           cited by {src}")

    print(f"\n{len(urls)} URL(s) checked - {len(failures)} unreachable")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
