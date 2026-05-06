#!/usr/bin/env python3
"""npm downloads → analytics/npm_daily.jsonl (append-only).

Source: https://api.npmjs.org/downloads/point/last-day/<scope>/<pkg>
       — public, no auth, no rate limit (in practice).

Tracked package: @autonomath/sdk.

Idempotent: skips if (date, package) row already exists.
Network errors: log + exit 0.

Output row shape:
  {"date":"2026-04-28","package":"@autonomath/sdk","downloads":N,
   "start":"...","end":"...","fetched_at":"..."}
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

ANALYTICS_DIR = _REPO_ROOT / "analytics"
OUT_PATH = ANALYTICS_DIR / "npm_daily.jsonl"
PACKAGES = ["@autonomath/sdk"]
URL = "https://api.npmjs.org/downloads/point/last-day/{pkg}"


def _existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            keys.add((row.get("date", ""), row.get("package", "")))
        except json.JSONDecodeError:
            continue
    return keys


def main() -> int:
    with heartbeat("npm_downloads") as hb:
        today = datetime.now(UTC).date().isoformat()
        seen = _existing_keys(OUT_PATH)
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        written = 0
        skipped = 0

        with httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "autonomath-analytics-cron/1.0"},
        ) as cli:
            for pkg in PACKAGES:
                if (today, pkg) in seen:
                    print(
                        f"[npm] {pkg} {today} already recorded — skip",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue
                url = URL.format(pkg=urllib.parse.quote(pkg, safe="@/"))
                try:
                    resp = cli.get(url)
                    # 404 is not a network error — package may be unpublished;
                    # record a 0-downloads row so the dashboard line stays continuous.
                    if resp.status_code == 404:
                        payload = {
                            "downloads": 0,
                            "start": today,
                            "end": today,
                            "package": pkg,
                        }
                    else:
                        resp.raise_for_status()
                        payload = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    print(
                        f"[npm] {pkg}: network error: {exc} — skip",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue

                row = {
                    "date": today,
                    "package": pkg,
                    "downloads": int(payload.get("downloads") or 0),
                    "start": payload.get("start", ""),
                    "end": payload.get("end", ""),
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
                with OUT_PATH.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
                print(f"[npm] wrote {pkg} {today}: downloads={row['downloads']}")
        print(f"[npm] done — {written} row(s) written")
        hb["rows_processed"] = int(written)
        hb["rows_skipped"] = int(skipped)
        hb["metadata"] = {"packages": PACKAGES, "date": today}
    return 0


if __name__ == "__main__":
    sys.exit(main())
