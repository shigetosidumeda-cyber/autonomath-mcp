#!/usr/bin/env python3
"""Emit analytics/backups.jsonl: machine-readable inventory of all backups.

One JSONL line per (db_id, R2 key) pair, with: key / mtime / size / age_hours
/ sha256 (read from the .sha256 sidecar). Designed for monitoring dashboards
or anomaly alerts (e.g. age_hours > expected_rpo).

Run daily after both backup crons:
    30 4 * * *  /app/.venv/bin/python /app/scripts/backup_manifest.py

Schema (one JSON object per line):
    {
        "db_id": "jpintel" | "autonomath",
        "key": "jpintel/jpintel-20260429-031500.db.gz",
        "mtime_utc": "2026-04-29T03:15:00+00:00",
        "size_bytes": 115527638,
        "age_hours": 1.42,
        "sha256": "<hex>" | null,
        "tier": "hourly" | "daily" | "weekly" | "monthly" | null,
        "expected_rpo_hours": 1 | 24,
        "rpo_violated": false
    }

Exit codes: 0 ok / 1 config / 2 fetch failed.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cron._r2_client import R2ConfigError, download, list_keys  # type: ignore

_LOG = logging.getLogger("jpintel.backup_manifest")

_REGISTRY = {
    "jpintel": {"prefix": "jpintel/", "expected_rpo_hours": 1},
    "autonomath": {"prefix": "autonomath/", "expected_rpo_hours": 24},
}


def _classify_tier(items: list[tuple[str, datetime, int]], now: datetime) -> dict[str, str]:
    """Tag each key with its retention tier. Newest in the last hour = hourly,
    newest of each day for 30d = daily, newest of each ISO week = weekly,
    newest of each month = monthly."""
    tier: dict[str, str] = {}
    sorted_items = sorted(items, key=lambda x: x[1], reverse=True)

    for k, m, _ in sorted_items:
        if (now - m) < timedelta(hours=2):
            tier[k] = "hourly"

    by_day: dict[str, tuple[str, datetime]] = {}
    for k, m, _ in sorted_items:
        d = m.strftime("%Y-%m-%d")
        if d not in by_day or m > by_day[d][1]:
            by_day[d] = (k, m)
    for k, _ in by_day.values():
        tier.setdefault(k, "daily")

    by_week: dict[str, tuple[str, datetime]] = {}
    for k, m, _ in sorted_items:
        iso = m.isocalendar()
        wk = f"{iso[0]}-W{iso[1]:02d}"
        if wk not in by_week or m > by_week[wk][1]:
            by_week[wk] = (k, m)
    for k, _ in by_week.values():
        tier.setdefault(k, "weekly")

    by_month: dict[str, tuple[str, datetime]] = {}
    for k, m, _ in sorted_items:
        mn = m.strftime("%Y-%m")
        if mn not in by_month or m > by_month[mn][1]:
            by_month[mn] = (k, m)
    for k, _ in by_month.values():
        tier.setdefault(k, "monthly")

    return tier


def _fetch_sha(key: str, bucket: str | None, work: Path) -> str | None:
    sha_key = key + ".sha256"
    dst = work / Path(sha_key).name
    try:
        download(sha_key, dst, bucket=bucket)
    except Exception:
        return None
    try:
        return dst.read_text(encoding="utf-8").split()[0]
    except Exception:
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    out_path = Path(os.environ.get("BACKUP_MANIFEST_PATH", "analytics/backups.jsonl"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bucket = os.environ.get("R2_BUCKET") or os.environ.get("JPINTEL_BACKUP_BUCKET")
    now = datetime.now(timezone.utc)

    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="backup-manifest-") as td:
        work = Path(td)
        for db_id, cfg in _REGISTRY.items():
            try:
                items = list_keys(cfg["prefix"], bucket=bucket)
            except R2ConfigError as exc:
                _LOG.error("r2_config_error err=%s", exc)
                return 1
            except Exception as exc:
                _LOG.exception("list_failed db=%s err=%s", db_id, exc)
                return 2

            db_items = [(k, m, s) for (k, m, s) in items if k.endswith(".db.gz")]
            tier_map = _classify_tier(db_items, now)
            db_items_sorted = sorted(db_items, key=lambda x: x[1], reverse=True)
            newest_age_hours = (
                (now - db_items_sorted[0][1]).total_seconds() / 3600
                if db_items_sorted
                else float("inf")
            )
            rpo_violated = newest_age_hours > cfg["expected_rpo_hours"] * 2

            for k, m, s in db_items_sorted:
                age_h = (now - m).total_seconds() / 3600
                sha = _fetch_sha(k, bucket, work)
                rows.append(
                    {
                        "db_id": db_id,
                        "key": k,
                        "mtime_utc": m.isoformat(),
                        "size_bytes": s,
                        "age_hours": round(age_h, 2),
                        "sha256": sha,
                        "tier": tier_map.get(k),
                        "expected_rpo_hours": cfg["expected_rpo_hours"],
                        "rpo_violated": (k == db_items_sorted[0][0]) and rpo_violated,
                    }
                )

    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _LOG.info("manifest_written path=%s rows=%d", out_path, len(rows))
    violated = [r for r in rows if r["rpo_violated"]]
    if violated:
        _LOG.warning("rpo_violations n=%d", len(violated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
