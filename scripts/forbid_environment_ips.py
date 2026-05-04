"""Pre-commit hook: block RFC 1918 private IP literals in staged files.

Blocks `10.x.x.x`, `172.16-31.x.x`, `192.168.x.x` from creeping into
the repo. Files under `legacy/` and `docs/` are exempt because those
hold historical / documentation content where examples may legitimately
reference local network addresses.

Exit 0 if clean, 1 with a list of `path:line:literal` violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable


# RFC 1918 ranges with word-boundary anchors so we don't flag substrings
# like `10.0.0` in semver, but we DO flag actual dotted-quads.
_RFC1918_RE = re.compile(
    r"\b("
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r")\b"
)

_EXEMPT_PREFIXES = ("legacy/", "docs/")


def _is_exempt(path: str) -> bool:
    norm = path.replace("\\", "/")
    return any(norm.startswith(p) for p in _EXEMPT_PREFIXES)


def _scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return []
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _RFC1918_RE.finditer(line):
            hits.append((lineno, match.group(1)))
    return hits


def main(argv: Iterable[str]) -> int:
    failures: list[str] = []
    for raw in argv:
        if _is_exempt(raw):
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        for lineno, literal in _scan_file(path):
            failures.append(f"{raw}:{lineno}: RFC 1918 IP literal {literal!r}")

    if failures:
        sys.stderr.write(
            "Forbidden private IP literals found (RFC 1918):\n"
        )
        for f in failures:
            sys.stderr.write(f"  {f}\n")
        sys.stderr.write(
            "If this is genuinely a docs/example, move it under docs/ or legacy/.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
