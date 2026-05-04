"""Extract candidate API URL paths from the My CUPRA xapk.

XAPK is a ZIP wrapping a base APK + config splits. The base APK contains the
classes*.dex files where Retrofit/OkHttp endpoint strings live as plain
MUTF-8 string-table entries — readable as raw bytes.

Strategy:
1. Unzip the xapk into a scratch dir.
2. Identify the base APK (largest .apk, or the one containing classes.dex).
3. Unzip base.apk; collect every classes*.dex.
4. Walk the bytes of each dex, recovering printable ASCII runs >= 6 chars.
5. Filter to URL-path-shaped or Cupra-host-shaped strings, with a sharper
   focus on charging/history/session keywords.
6. Write structured output to docs/probe_output/09_apk_endpoint_strings.json
   plus a flat text file with the most relevant matches highlighted first.

This script is read-only with respect to the xapk; everything goes into a
gitignored scratch directory under docs/_apk_extract/.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
XAPK_PATH = REPO_ROOT / "docs" / "My CUPRA App_2.15.0.xapk"
EXTRACT_ROOT = REPO_ROOT / "docs" / "_apk_extract"
OUTPUT_DIR = REPO_ROOT / "docs" / "probe_output"
OUTPUT_JSON = OUTPUT_DIR / "09_apk_endpoint_strings.json"
OUTPUT_TXT = OUTPUT_DIR / "09_apk_endpoint_strings.txt"


# Printable-ASCII run; URLs/paths fit cleanly here. We deliberately exclude
# whitespace so we cleave on string-table boundaries.
PRINTABLE_RUN = re.compile(rb"[\x21-\x7e]{6,}")

# Things worth surfacing.
URL_PATH_RE = re.compile(r"^/v\d+/")
HOST_TOKENS = ("ola.prod.code.seat.cloud.vwgroup.com", "vwgroup.io", "vwgroup.com")
CHARGING_TOKENS = ("charging", "charge")
HISTORY_TOKENS = (
    "history",
    "session",
    "sessions",
    "log",
    "logs",
    "record",
    "records",
    "transaction",
    "transactions",
    "summary",
    "summaries",
    "statistics",
    "details",
    "events",
)


def main() -> int:
    if not XAPK_PATH.exists():
        sys.exit(f"XAPK not found at {XAPK_PATH}")
    EXTRACT_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[apk] extracting {XAPK_PATH.name}")
    xapk_dir = EXTRACT_ROOT / "xapk"
    if xapk_dir.exists():
        # Wipe stale extraction so re-runs are deterministic.
        _rmtree(xapk_dir)
    xapk_dir.mkdir()
    with zipfile.ZipFile(XAPK_PATH) as zf:
        zf.extractall(xapk_dir)

    apks = sorted(xapk_dir.rglob("*.apk"), key=lambda p: p.stat().st_size, reverse=True)
    if not apks:
        sys.exit("No .apk files found inside the xapk.")
    print(f"[apk] {len(apks)} APK(s) found inside xapk; largest: {apks[0].name}")

    # The base APK is the one carrying classes.dex. Iterate from largest
    # down so we hit it on the first try.
    base_apk = None
    for candidate in apks:
        with zipfile.ZipFile(candidate) as zf:
            names = zf.namelist()
            if any(n == "classes.dex" or n.startswith("classes") and n.endswith(".dex") for n in names):
                base_apk = candidate
                break
    if base_apk is None:
        sys.exit("None of the inner APKs contained a classes.dex. Cannot proceed.")
    print(f"[apk] base APK: {base_apk.name}")

    apk_dir = EXTRACT_ROOT / "base"
    if apk_dir.exists():
        _rmtree(apk_dir)
    apk_dir.mkdir()
    with zipfile.ZipFile(base_apk) as zf:
        for name in zf.namelist():
            if name.startswith("classes") and name.endswith(".dex"):
                zf.extract(name, apk_dir)

    dex_files = sorted(apk_dir.rglob("classes*.dex"))
    print(f"[apk] {len(dex_files)} dex file(s) extracted")

    # ---- harvest printable strings ------------------------------------
    raw_strings: set[str] = set()
    for dex in dex_files:
        data = dex.read_bytes()
        for m in PRINTABLE_RUN.finditer(data):
            try:
                raw_strings.add(m.group().decode("ascii"))
            except UnicodeDecodeError:
                pass
        print(f"[apk] {dex.name}: {len(data):,} bytes scanned")

    print(f"[apk] {len(raw_strings):,} unique printable runs (>=6 chars)")

    # ---- bucketise -----------------------------------------------------
    buckets: dict[str, list[str]] = {
        "charging_history_paths": [],   # /vN/.../charging.../<history-token>
        "charging_paths": [],           # /vN/.../charging...
        "all_v_paths": [],              # any /vN/... path
        "cupra_host_urls": [],          # full URLs to vwgroup hosts
        "history_keyword_strings": [],  # any string containing a history-ish token (no path filter)
        "interesting_misc": [],         # paths mentioning history-ish tokens but no /vN/
    }

    for s in raw_strings:
        low = s.lower()
        is_path = URL_PATH_RE.match(s) is not None
        is_host_url = any(host in s for host in HOST_TOKENS)
        has_charging = any(t in low for t in CHARGING_TOKENS)
        has_history = any(t in low for t in HISTORY_TOKENS)

        if is_path and has_charging and has_history:
            buckets["charging_history_paths"].append(s)
        if is_path and has_charging:
            buckets["charging_paths"].append(s)
        if is_path:
            buckets["all_v_paths"].append(s)
        if is_host_url:
            buckets["cupra_host_urls"].append(s)
        if has_history and len(s) < 200:
            buckets["history_keyword_strings"].append(s)
        if not is_path and has_charging and has_history:
            buckets["interesting_misc"].append(s)

    # Dedup + sort each bucket. Cap large buckets so the JSON file is
    # navigable (full set still in the .txt dump).
    for k, v in buckets.items():
        buckets[k] = sorted(set(v))

    # ---- write outputs -------------------------------------------------
    summary = {
        "xapk": str(XAPK_PATH.relative_to(REPO_ROOT)),
        "base_apk": base_apk.name,
        "dex_files": [d.name for d in dex_files],
        "total_unique_strings": len(raw_strings),
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "top_path_prefixes": _top_prefixes(buckets["all_v_paths"], 30),
        "buckets": {
            # JSON keeps the high-signal buckets in full; large generic
            # buckets are sampled (full content in the .txt file).
            "charging_history_paths": buckets["charging_history_paths"],
            "charging_paths": buckets["charging_paths"][:200],
            "cupra_host_urls": buckets["cupra_host_urls"][:200],
            "interesting_misc": buckets["interesting_misc"][:200],
            "history_keyword_strings_sample": buckets["history_keyword_strings"][:80],
        },
    }
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# My CUPRA APK — extracted endpoint strings\n")
    lines.append(f"Source: {XAPK_PATH.name} ({base_apk.name})\n")
    lines.append(f"Unique printable runs: {len(raw_strings):,}\n")

    def section(title: str, items: list[str], cap: int | None = None) -> None:
        lines.append(f"\n## {title} ({len(items)})\n")
        if not items:
            lines.append("_(none)_\n")
            return
        sl = items if cap is None else items[:cap]
        for s in sl:
            lines.append(f"- `{s}`")
        if cap is not None and len(items) > cap:
            lines.append(f"\n_…and {len(items) - cap} more_")

    section("Charging-history path candidates (high signal)", buckets["charging_history_paths"])
    section("All charging-related /vN/ paths", buckets["charging_paths"])
    section("Cupra/VW group full URLs", buckets["cupra_host_urls"])
    section("Non-path strings containing both 'charging' and a history-ish token", buckets["interesting_misc"])
    section("Other history-flavoured strings (sampled)", buckets["history_keyword_strings"], cap=200)
    section("All discovered /vN/ paths (sampled)", buckets["all_v_paths"], cap=400)
    OUTPUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[apk] wrote {OUTPUT_JSON.relative_to(REPO_ROOT)}")
    print(f"[apk] wrote {OUTPUT_TXT.relative_to(REPO_ROOT)}")
    print(f"[apk] charging_history_paths: {len(buckets['charging_history_paths'])}")
    print(f"[apk] charging_paths total: {len(buckets['charging_paths'])}")
    return 0


def _top_prefixes(paths: list[str], limit: int) -> list[tuple[str, int]]:
    """Return the most common 3-segment prefixes among /vN/ paths."""
    c: Counter[str] = Counter()
    for p in paths:
        # strip query
        clean = p.split("?", 1)[0]
        segments = clean.split("/")
        prefix = "/".join(segments[:4])  # ['', 'v1', 'vehicles', '{vin}']
        c[prefix] += 1
    return c.most_common(limit)


def _rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path)


if __name__ == "__main__":
    raise SystemExit(main())
