#!/usr/bin/env python3
"""PyPI downloads → analytics/pypi_daily.jsonl (append-only).

Source: https://pypistats.org/api/packages/<pkg>/recent (no auth, public).
Tracked package: autonomath-mcp.

Idempotent: skips if today's row already exists.
429 / network errors: log + exit 0 (no crash).

Output row shape:
  {"date":"2026-04-28","package":"autonomath-mcp","last_day":N,
   "last_week":N,"last_month":N,"fetched_at":"..."}
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

ANALYTICS_DIR = _REPO_ROOT / "analytics"
OUT_PATH = ANALYTICS_DIR / "pypi_daily.jsonl"
PACKAGES = ["autonomath-mcp"]
URL = "https://pypistats.org/api/packages/{pkg}/recent"


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
    with heartbeat("pypi_downloads") as hb:
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
                        f"[pypi] {pkg} {today} already recorded — skip",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue
                try:
                    resp = cli.get(URL.format(pkg=pkg))
                    if resp.status_code == 429:
                        print(
                            f"[pypi] {pkg}: 429 rate limited — skip",
                            file=sys.stderr,
                        )
                        skipped += 1
                        continue
                    resp.raise_for_status()
                    payload = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    print(
                        f"[pypi] {pkg}: network error: {exc} — skip",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue

                data = payload.get("data") or {}
                row = {
                    "date": today,
                    "package": pkg,
                    "last_day": int(data.get("last_day") or 0),
                    "last_week": int(data.get("last_week") or 0),
                    "last_month": int(data.get("last_month") or 0),
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
                with OUT_PATH.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
                print(
                    f"[pypi] wrote {pkg} {today}: day={row['last_day']} "
                    f"wk={row['last_week']} mo={row['last_month']}"
                )
        print(f"[pypi] done — {written} row(s) written")
        hb["rows_processed"] = int(written)
        hb["rows_skipped"] = int(skipped)
        hb["metadata"] = {"packages": PACKAGES, "date": today}
    return 0


if __name__ == "__main__":
    sys.exit(main())
