#!/usr/bin/env python3
"""Wave 43.3.10 cell 12 — Daily backup integrity verify + R2 hash check.

Extends Wave 21 backup_jpintel.py pattern: instead of *writing* a fresh
hourly snapshot, this daily cron verifies that the *latest* R2 snapshot's
SHA256 matches its sidecar, sanity-checks gzip size + decompressed size,
and runs PRAGMA integrity_check on a local restore (when feasible). When
any check fails it writes ``analytics/backup_verify_daily.json`` with
``integrity_pass=0`` so that cell 10 (sla_breach_alert.py) trips the
``backup_integrity_pass`` / ``r2_hash_match`` SLA metrics.

Per `feedback_no_quick_check_on_huge_sqlite`: PRAGMA integrity_check on
multi-GB DBs is FORBIDDEN at boot. This script runs the check only on a
*staging copy* of the latest R2 snapshot — never on the live volume DB —
and only when ``VERIFY_INTEGRITY_CHECK=1`` is explicitly set (default off
to keep the cron fast / cheap).

Run via Fly cron (daily) or GHA workflow:
    .github/workflows/backup-verify-daily.yml

Required env: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
Optional env: JPINTEL_BACKUP_PREFIX (default jpintel/),
              VERIFY_INTEGRITY_CHECK (default 0; opt-in),
              VERIFY_STAGE_DIR (default /tmp/jpcite_verify).

Exit codes: 0 ok / 1 config / 2 r2-missing / 3 hash-mismatch.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS = REPO_ROOT / "analytics"
SIDECAR = ANALYTICS / "backup_verify_daily.json"

logger = logging.getLogger("jpcite.cron.verify_backup_daily")
_KEY_RE = re.compile(r"^jpintel-(\d{8})-(\d{6})\.db\.gz$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _latest_r2_snapshot(prefix: str, bucket: str | None) -> tuple[str, int] | None:
    """Return (key, size_bytes) of the most-recent ``jpintel-*.db.gz`` in R2."""
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "cron"))
    try:
        from _r2_client import list_keys  # type: ignore
    except ImportError:
        logger.error("r2_client_import_failed")
        return None
    items = list_keys(prefix, bucket=bucket)
    db_items = [it for it in items if _KEY_RE.match(Path(it[0]).name)]
    if not db_items:
        return None
    db_items.sort(key=lambda x: x[1], reverse=True)
    key, _mtime, size = db_items[0]
    return key, int(size)


def _r2_download(key: str, dest: Path, bucket: str | None) -> bool:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "cron"))
    try:
        from _r2_client import download  # type: ignore
    except ImportError:
        return False
    try:
        download(key, dest, bucket=bucket)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort, errors recorded in sidecar
        logger.warning("r2_download_failed key=%s err=%s", key, exc)
        return False


def _verify_gzip(path: Path) -> tuple[bool, int]:
    """Decompress to /dev/null and return (ok, decompressed_size_bytes)."""
    try:
        size = 0
        with gzip.open(path, "rb") as gz:
            while True:
                chunk = gz.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
        return True, size
    except (OSError, EOFError) as exc:
        logger.warning("gzip_verify_failed path=%s err=%s", path, exc)
        return False, 0


def _integrity_check(staged_db: Path) -> bool:
    """PRAGMA integrity_check on a restored DB copy. Opt-in only."""
    try:
        conn = sqlite3.connect(str(staged_db))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return row is not None and row[0] == "ok"
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        logger.warning("integrity_check_failed err=%s", exc)
        return False


def _write_sidecar(payload: dict[str, Any]) -> None:
    ANALYTICS.mkdir(parents=True, exist_ok=True)
    SIDECAR.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--dry-run", action="store_true", help="skip actual R2 download")
    ap.add_argument("--prefix", default=os.environ.get("JPINTEL_BACKUP_PREFIX", "jpintel/"))
    args = ap.parse_args(argv)

    bucket = os.environ.get("R2_BUCKET") or os.environ.get("JPINTEL_BACKUP_BUCKET")
    stage_dir = Path(os.environ.get("VERIFY_STAGE_DIR", "/tmp/jpcite_verify"))
    stage_dir.mkdir(parents=True, exist_ok=True)
    do_integrity = os.environ.get("VERIFY_INTEGRITY_CHECK", "0") == "1"

    ts = _now_iso()
    payload: dict[str, Any] = {
        "snapshot_ts": ts, "schema_version": 1,
        "integrity_pass": 0, "r2_hash_match": 0, "gzip_ok": 0,
        "integrity_check_ran": 0, "details": {},
    }

    latest = _latest_r2_snapshot(args.prefix, bucket)
    if latest is None:
        payload["details"]["error"] = "no_r2_snapshot"
        _write_sidecar(payload)
        return 2
    key, expected_size = latest
    payload["details"]["latest_key"] = key
    payload["details"]["r2_size_bytes"] = expected_size

    if args.dry_run:
        payload["details"]["mode"] = "dry_run"
        payload["integrity_pass"] = 1
        payload["r2_hash_match"] = 1
        payload["gzip_ok"] = 1
        _write_sidecar(payload)
        return 0

    gz_local = stage_dir / Path(key).name
    sha_local = stage_dir / (Path(key).name + ".sha256")
    if not _r2_download(key, gz_local, bucket) or not _r2_download(key + ".sha256", sha_local, bucket):
        payload["details"]["error"] = "r2_download_failed"
        _write_sidecar(payload)
        return 2
    payload["details"]["local_gz_size"] = gz_local.stat().st_size
    sidecar_text = sha_local.read_text(encoding="utf-8", errors="replace").strip()
    expected_sha = sidecar_text.split()[0] if sidecar_text else ""
    actual_sha = _sha256_file(gz_local)
    payload["details"]["expected_sha256"] = expected_sha[:16]
    payload["details"]["actual_sha256"] = actual_sha[:16]
    if expected_sha and expected_sha == actual_sha:
        payload["r2_hash_match"] = 1
    else:
        payload["details"]["error"] = "sha_mismatch"

    gz_ok, decompressed = _verify_gzip(gz_local)
    payload["gzip_ok"] = int(gz_ok)
    payload["details"]["decompressed_size"] = decompressed

    if do_integrity and gz_ok:
        staged_db = stage_dir / (Path(key).stem)  # strip .gz
        try:
            import shutil
            with gzip.open(gz_local, "rb") as src, staged_db.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            payload["integrity_check_ran"] = 1
            payload["integrity_pass"] = int(_integrity_check(staged_db))
        finally:
            if staged_db.exists():
                staged_db.unlink()
    else:
        # Without explicit integrity check, treat r2_hash_match + gzip_ok as
        # sufficient (cheap daily mode; the opt-in flag gates the slow path).
        payload["integrity_pass"] = payload["r2_hash_match"] * payload["gzip_ok"]

    # Clean up staged blobs.
    for p in (gz_local, sha_local):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    _write_sidecar(payload)
    if payload["integrity_pass"] != 1:
        logger.warning("verify_failed payload=%s", payload)
        return 3
    print(json.dumps({"ts": ts, "key": key, "integrity_pass": payload["integrity_pass"],
                      "r2_hash_match": payload["r2_hash_match"], "gzip_ok": payload["gzip_ok"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(run())
