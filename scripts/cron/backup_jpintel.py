#!/usr/bin/env python3
"""Hourly online backup of jpintel.db -> R2 with tiered retention.

What this does
--------------
1. sqlite3 .backup API (atomic, online, no exclusive lock) -> staged copy.
2. PRAGMA integrity_check on the staged copy. Abort on failure.
3. gzip -> .db.gz (smaller for upload).
4. SHA256 sidecar.
5. Upload to R2: <prefix>/jpintel-YYYYMMDD-HHMMSS.db.gz (+ .sha256).
6. Tiered retention prune: 24 hourly + 30 daily + 12 monthly.

Why this is safe
----------------
Uses sqlite3.Connection.backup() (online API). Never copies the file with
cp/rsync (which races against WAL checkpoint and produces malformed copies
that the entrypoint will reject via SHA mismatch).

Run via Fly cron (see fly.toml [[processes]] cron) or systemd timer:
    0 * * * *  /app/.venv/bin/python /app/scripts/cron/backup_jpintel.py

Required env: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
              (or JPINTEL_BACKUP_BUCKET).
Optional env: JPINTEL_DB_PATH (default /data/jpintel.db),
              JPINTEL_BACKUP_PREFIX (default jpintel/),
              JPINTEL_BACKUP_LOCAL_DIR (default /data/backups),
              SENTRY_DSN.

Exit codes: 0 ok / 1 config / 2 snapshot / 3 upload / 4 retention.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Reuse the proven online backup helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backup import _gzip_file, _integrity_check, _online_backup, _write_sha256  # type: ignore
from cron._r2_client import R2ConfigError, delete, list_keys, upload  # type: ignore

_LOG = logging.getLogger("jpintel.backup_hourly")
_KEY_RE = re.compile(r"^jpintel-(\d{8})-(\d{6})\.db\.gz$")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def _select_keep(
    items: list[tuple[str, datetime, int]],
    now: datetime,
    *,
    keep_hourly: int = 24,
    keep_daily: int = 30,
    keep_monthly: int = 12,
) -> set[str]:
    """Tiered: most recent N hourly + newest of each day for next M days +
    newest of each month for next Y months."""
    items_sorted = sorted(items, key=lambda x: x[1], reverse=True)
    keep: set[str] = set()

    hourly = [it for it in items_sorted if (now - it[1]) <= timedelta(hours=keep_hourly + 1)]
    keep.update(it[0] for it in hourly[:keep_hourly])

    by_day: dict[str, tuple[str, datetime, int]] = {}
    cutoff_day = now - timedelta(days=keep_daily)
    for it in items_sorted:
        if it[1] < cutoff_day:
            continue
        d = it[1].strftime("%Y-%m-%d")
        if d not in by_day or it[1] > by_day[d][1]:
            by_day[d] = it
    keep.update(it[0] for it in by_day.values())

    by_month: dict[str, tuple[str, datetime, int]] = {}
    cutoff_month = now - timedelta(days=keep_monthly * 31)
    for it in items_sorted:
        if it[1] < cutoff_month:
            continue
        m = it[1].strftime("%Y-%m")
        if m not in by_month or it[1] > by_month[m][1]:
            by_month[m] = it
    keep.update(it[0] for it in by_month.values())

    return keep


def _prune_r2(prefix: str, bucket: str | None, now: datetime) -> int:
    items = list_keys(prefix, bucket=bucket)
    db_items = [it for it in items if _KEY_RE.match(Path(it[0]).name)]
    keep = _select_keep(db_items, now)
    removed = 0
    for key, _mtime, _size in db_items:
        if key in keep:
            continue
        try:
            delete(key, bucket=bucket)
            try:
                delete(key + ".sha256", bucket=bucket)
            except Exception:
                pass
            removed += 1
        except Exception as exc:
            _LOG.warning("prune_skip key=%s err=%s", key, exc)
    return removed


def _init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0.0,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        )
    except Exception:  # pragma: no cover
        pass


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _init_sentry()
    db_path = Path(os.environ.get("JPINTEL_DB_PATH", "/data/jpintel.db"))
    local_dir = Path(os.environ.get("JPINTEL_BACKUP_LOCAL_DIR", "/data/backups"))
    prefix = os.environ.get("JPINTEL_BACKUP_PREFIX", "jpintel/")
    bucket = os.environ.get("R2_BUCKET") or os.environ.get("JPINTEL_BACKUP_BUCKET")

    if not db_path.is_file():
        _LOG.error("db_missing path=%s", db_path)
        return 1
    local_dir.mkdir(parents=True, exist_ok=True)

    now = _now_utc()
    name = f"jpintel-{_stamp(now)}.db"
    staged = local_dir / name

    try:
        _online_backup(db_path, staged)
        _integrity_check(staged)
    except Exception as exc:
        _LOG.exception("snapshot_failed err=%s", exc)
        return 2

    gz = _gzip_file(staged)
    sha = _write_sha256(gz)
    _LOG.info("artifact_ready gz=%s size=%d", gz, gz.stat().st_size)

    try:
        upload(gz, f"{prefix.rstrip('/')}/{gz.name}", bucket=bucket)
        upload(sha, f"{prefix.rstrip('/')}/{sha.name}", bucket=bucket)
    except R2ConfigError as exc:
        _LOG.error("r2_config_error err=%s", exc)
        return 1
    except Exception as exc:
        _LOG.exception("upload_failed err=%s", exc)
        return 3

    try:
        removed = _prune_r2(prefix, bucket, now)
        _LOG.info("prune_done removed=%d", removed)
    except Exception as exc:
        _LOG.warning("prune_failed err=%s (backup itself succeeded)", exc)
        return 4

    # Local cleanup -- keep last 24 local copies for fast recovery.
    locals_ = sorted(local_dir.glob("jpintel-*.db.gz"))
    for old in locals_[:-24]:
        try:
            old.unlink()
            sha_sib = old.with_suffix(old.suffix + ".sha256")
            if sha_sib.exists():
                sha_sib.unlink()
        except OSError:
            pass

    _LOG.info("backup_ok key=%s", gz.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
