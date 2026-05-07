#!/usr/bin/env python3
"""Daily online backup of autonomath.db -> R2 with weekly retention.

autonomath.db (~8.3 GB on disk, ~3 GB gzipped) is mostly read-only entity-fact
data. Daily snapshots are kept for 7 days, plus a weekly snapshot for 4 weeks.
Total cold storage: ~7 daily + 4 weekly = 11 copies max -> ~33 GB on R2 at
$0.045 / GB-mo = $1.50 / mo. Well inside the budget.

Why daily not hourly: autonomath.db write traffic is bulk-ingest only (not
request-path), so RPO=24h is acceptable. If the volume corrupts mid-day we
re-bootstrap from R2, then re-run any ingest jobs that ran since the last
snapshot (logged under data/ingest_logs/).

Run via cron at off-peak (e.g. 04:00 UTC daily):
    0 4 * * *  /app/.venv/bin/python /app/scripts/cron/backup_autonomath.py

Required env: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
              R2_BUCKET (or JPINTEL_BACKUP_BUCKET).
Optional env: AUTONOMATH_DB_PATH (default /data/autonomath.db),
              AUTONOMATH_BACKUP_PREFIX (default autonomath/),
              AUTONOMATH_BACKUP_LOCAL_DIR (default /data/backups-autonomath),
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import contextlib

from backup import _gzip_file, _integrity_check, _online_backup, _write_sha256  # type: ignore
from cron._r2_client import R2ConfigError, delete, list_keys, upload  # type: ignore

# Sentry route — backup_integrity_failure rule (monitoring/sentry_alert_rules.yml)
# fires on logger=jpintel.backup_hourly + level=error. The autonomath backup
# also forwards to Sentry so daily-window failures show up in the same rule.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from jpintel_mcp.observability import safe_capture_exception  # type: ignore
except Exception:  # pragma: no cover — defensive: never block the backup on import errors
    def safe_capture_exception(exc: BaseException, **scope: object) -> None:  # type: ignore[no-redef]
        return

_LOG = logging.getLogger("jpintel.backup_autonomath")
_KEY_RE = re.compile(r"^autonomath-(\d{8})-(\d{6})\.db\.gz$")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _select_keep_daily_weekly(
    items: list[tuple[str, datetime, int]],
    now: datetime,
    *,
    keep_daily: int = 7,
    keep_weekly: int = 4,
) -> set[str]:
    items_sorted = sorted(items, key=lambda x: x[1], reverse=True)
    keep: set[str] = set()

    by_day: dict[str, tuple[str, datetime, int]] = {}
    cutoff_d = now - timedelta(days=keep_daily)
    for it in items_sorted:
        if it[1] < cutoff_d:
            continue
        d = it[1].strftime("%Y-%m-%d")
        if d not in by_day or it[1] > by_day[d][1]:
            by_day[d] = it
    keep.update(it[0] for it in by_day.values())

    by_week: dict[str, tuple[str, datetime, int]] = {}
    cutoff_w = now - timedelta(weeks=keep_weekly)
    for it in items_sorted:
        if it[1] < cutoff_w:
            continue
        iso = it[1].isocalendar()
        wk = f"{iso[0]}-W{iso[1]:02d}"
        if wk not in by_week or it[1] > by_week[wk][1]:
            by_week[wk] = it
    keep.update(it[0] for it in by_week.values())

    return keep


def _prune_r2(prefix: str, bucket: str | None, now: datetime) -> int:
    items = list_keys(prefix, bucket=bucket)
    db_items = [it for it in items if _KEY_RE.match(Path(it[0]).name)]
    keep = _select_keep_daily_weekly(db_items, now)
    removed = 0
    for key, _mtime, _size in db_items:
        if key in keep:
            continue
        try:
            delete(key, bucket=bucket)
            with contextlib.suppress(Exception):
                delete(key + ".sha256", bucket=bucket)
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
    db_path = Path(os.environ.get("AUTONOMATH_DB_PATH", "/data/autonomath.db"))
    local_dir = Path(os.environ.get("AUTONOMATH_BACKUP_LOCAL_DIR", "/data/backups-autonomath"))
    prefix = os.environ.get("AUTONOMATH_BACKUP_PREFIX", "autonomath/")
    bucket = os.environ.get("R2_BUCKET") or os.environ.get("JPINTEL_BACKUP_BUCKET")

    if not db_path.is_file():
        _LOG.error("db_missing path=%s", db_path)
        return 1
    local_dir.mkdir(parents=True, exist_ok=True)

    now = _now_utc()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    name = f"autonomath-{stamp}.db"
    staged = local_dir / name

    try:
        _online_backup(db_path, staged)
        _integrity_check(staged)
    except Exception as exc:
        _LOG.exception("snapshot_failed err=%s", exc)
        safe_capture_exception(exc, stage="snapshot", db_path=str(db_path))
        return 2

    gz = _gzip_file(staged)
    sha = _write_sha256(gz)
    _LOG.info("artifact_ready gz=%s size=%d", gz, gz.stat().st_size)

    try:
        upload(gz, f"{prefix.rstrip('/')}/{gz.name}", bucket=bucket)
        upload(sha, f"{prefix.rstrip('/')}/{sha.name}", bucket=bucket)
    except R2ConfigError as exc:
        _LOG.error("r2_config_error err=%s", exc)
        safe_capture_exception(exc, stage="r2_config")
        return 1
    except Exception as exc:
        _LOG.exception("upload_failed err=%s", exc)
        safe_capture_exception(exc, stage="upload", artifact=str(gz))
        return 3

    try:
        removed = _prune_r2(prefix, bucket, now)
        _LOG.info("prune_done removed=%d", removed)
    except Exception as exc:
        _LOG.warning("prune_failed err=%s (backup itself succeeded)", exc)
        return 4

    locals_ = sorted(local_dir.glob("autonomath-*.db.gz"))
    for old in locals_[:-2]:  # autonomath.db is huge, keep only 2 local copies
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
