#!/usr/bin/env python3
"""check_sitemap_freshness: compare max <lastmod> across site/sitemap-*.xml against
data/facts_registry.json snapshot_at. WARN (exit 0 with stderr) if delta >24h.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"

LASTMOD_RE = re.compile(r"<lastmod>([^<]+)</lastmod>", re.IGNORECASE)


def _parse(ts: str) -> dt.datetime | None:
    ts = ts.strip()
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            d = dt.datetime.strptime(ts, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d
        except ValueError:
            continue
    return None


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    snap = _parse(reg["snapshot_at"])
    if snap is None:
        print("WARN: snapshot_at unparseable", file=sys.stderr)
        return 0

    files = list((ROOT / "site").glob("sitemap-*.xml"))
    if not files:
        print("WARN: no sitemap-*.xml found", file=sys.stderr)
        return 0

    max_lastmod: dt.datetime | None = None
    for f in files:
        try:
            text = f.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        for m in LASTMOD_RE.finditer(text):
            d = _parse(m.group(1))
            if d is not None and (max_lastmod is None or d > max_lastmod):
                max_lastmod = d

    if max_lastmod is None:
        print("WARN: no <lastmod> tags parsed", file=sys.stderr)
        return 0

    delta = abs((snap - max_lastmod).total_seconds()) / 3600.0
    print(f"snapshot_at={snap.isoformat()} max_lastmod={max_lastmod.isoformat()} delta_hours={delta:.2f}")
    if delta > 24.0:
        print(f"WARN: sitemap lastmod drift {delta:.2f}h > 24h", file=sys.stderr)
    else:
        print("OK: sitemap fresh within 24h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
