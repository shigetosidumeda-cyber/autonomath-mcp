#!/usr/bin/env python3
"""Weekly backup integrity drill.

For each registered DB (jpintel + autonomath):
  1. Resolve the latest R2 backup key.
  2. Download into /tmp/.
  3. Verify SHA256.
  4. Decompress.
  5. PRAGMA integrity_check; abort on non-ok.
  6. Compare row counts of canary tables vs the live DB.
  7. Compare DB size delta -- ratio outside [0.5, 2.0] is suspicious.
  8. Emit Sentry breadcrumb on mismatch (if SENTRY_DSN set).

Run weekly via cron:
    0 6 * * 0  /app/.venv/bin/python /app/scripts/test_backup_integrity.py

Exit codes: 0 ok / 1 config / 2 download / 3 integrity / 4 row_count / 5 size_delta.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cron._r2_client import R2ConfigError, download, list_keys  # type: ignore

_LOG = logging.getLogger("jpintel.backup_integrity")

_REGISTRY = {
    "jpintel": {
        "live": "/data/jpintel.db",
        "prefix": "jpintel/",
        "name_prefix": "jpintel-",
        "canary_tables": ["api_keys", "subscribers", "anon_rate_limit", "usage_events", "stripe_webhook_events"],
    },
    "autonomath": {
        "live": "/data/autonomath.db",
        "prefix": "autonomath/",
        "name_prefix": "autonomath-",
        "canary_tables": ["entities", "facts", "sources"],
    },
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(db: Path, table: str) -> int | None:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        try:
            (n,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(n)
        except sqlite3.OperationalError:
            return None
    finally:
        conn.close()


def _capture_sentry(level: str, message: str, **extra: object) -> None:
    try:
        import sentry_sdk

        sentry_sdk.capture_message(message, level=level, scope=lambda s: [s.set_extra(k, v) for k, v in extra.items()])
    except Exception:
        pass


def _check_one(db_id: str, cfg: dict, work: Path) -> int:
    bucket = os.environ.get("R2_BUCKET") or os.environ.get("JPINTEL_BACKUP_BUCKET")
    items = list_keys(cfg["prefix"], bucket=bucket)
    items = [it for it in items if Path(it[0]).name.startswith(cfg["name_prefix"]) and it[0].endswith(".db.gz")]
    if not items:
        _LOG.error("no_backups db=%s prefix=%s", db_id, cfg["prefix"])
        _capture_sentry("error", f"backup integrity: no backups for {db_id}", prefix=cfg["prefix"])
        return 2
    items.sort(key=lambda x: x[1], reverse=True)
    key, mtime, _ = items[0]
    _LOG.info("latest db=%s key=%s mtime=%s", db_id, key, mtime.isoformat())

    gz = work / Path(key).name
    sha = work / (Path(key).name + ".sha256")
    try:
        download(key, gz, bucket=bucket)
        download(key + ".sha256", sha, bucket=bucket)
    except Exception as exc:
        _LOG.exception("download_failed db=%s err=%s", db_id, exc)
        _capture_sentry("error", f"backup integrity: download failed {db_id}", err=str(exc))
        return 2

    expected = sha.read_text(encoding="utf-8").split()[0]
    actual = _sha256(gz)
    if expected != actual:
        _LOG.error("sha_mismatch db=%s expected=%s actual=%s", db_id, expected, actual)
        _capture_sentry("error", f"backup integrity: sha mismatch {db_id}", expected=expected, actual=actual)
        return 3

    decomp = work / Path(gz.stem)
    with gzip.open(gz, "rb") as f_in, decomp.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    conn = sqlite3.connect(str(decomp))
    try:
        row = conn.execute("PRAGMA integrity_check;").fetchone()
    finally:
        conn.close()
    if row is None or row[0] != "ok":
        _LOG.error("integrity_failed db=%s row=%r", db_id, row)
        _capture_sentry("error", f"backup integrity: PRAGMA failed {db_id}", row=str(row))
        return 3

    live = Path(cfg["live"])
    if not live.is_file():
        _LOG.warning("live_missing db=%s path=%s -- skip row/size compare", db_id, live)
        return 0

    backup_size = decomp.stat().st_size
    live_size = live.stat().st_size
    if live_size > 0:
        ratio = backup_size / live_size
        if ratio < 0.5 or ratio > 2.0:
            _LOG.error("size_drift db=%s backup=%d live=%d ratio=%.2f", db_id, backup_size, live_size, ratio)
            _capture_sentry("warning", f"backup integrity: size drift {db_id}", backup=backup_size, live=live_size, ratio=ratio)
            return 5

    mismatches: list[tuple[str, int, int]] = []
    for table in cfg["canary_tables"]:
        b_n = _row_count(decomp, table)
        l_n = _row_count(live, table)
        if b_n is None or l_n is None:
            continue
        # Allow 10% drift for hot tables. Backup is older than live by up to RPO,
        # so live can have more rows; live should NOT have fewer.
        if b_n > l_n * 1.1 or (l_n > 0 and b_n < l_n * 0.5):
            mismatches.append((table, b_n, l_n))

    if mismatches:
        _LOG.error("row_count_mismatch db=%s mismatches=%s", db_id, mismatches)
        _capture_sentry("warning", f"backup integrity: row count mismatch {db_id}", mismatches=mismatches)
        return 4

    _LOG.info("ok db=%s backup_size=%d live_size=%d tables=%d", db_id, backup_size, live_size, len(cfg["canary_tables"]))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    dsn = os.environ.get("SENTRY_DSN")
    if dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0, environment=os.environ.get("SENTRY_ENVIRONMENT", "production"))
        except Exception:
            pass

    rc = 0
    with tempfile.TemporaryDirectory(prefix="backup-integrity-") as td:
        for db_id, cfg in _REGISTRY.items():
            try:
                code = _check_one(db_id, cfg, Path(td))
            except R2ConfigError as exc:
                _LOG.error("r2_config_error db=%s err=%s", db_id, exc)
                return 1
            if code != 0:
                rc = max(rc, code)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
