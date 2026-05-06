#!/usr/bin/env python3
"""Online SQLite backup for jpintel-mcp.

Uses sqlite3.Connection.backup() which is safe during concurrent reads/writes.
Writes a timestamped .db file plus a sibling .sha256 file, optionally gzipped.
Prunes backups older than --keep days.

Exit codes: 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

_LOG = logging.getLogger("jpintel.backup")


def _default_db_path() -> Path:
    # Avoid importing jpintel_mcp.config so this script works without the package installed.
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return Path(env)
    # Resolve to <repo>/data/jpintel.db relative to this file.
    return Path(__file__).resolve().parent.parent / "data" / "jpintel.db"


def _sha256_of_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _online_backup(src: Path, dst: Path) -> None:
    """Perform online backup from src -> dst using sqlite3 backup API."""
    if not src.is_file():
        raise FileNotFoundError(f"source DB not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # If dst exists, sqlite3.connect will open it; remove to be safe.
    if dst.exists():
        dst.unlink()
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            # pages=-1 copies the whole database in one step (still chunked internally).
            src_conn.backup(dst_conn, pages=-1)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _integrity_check(path: Path) -> None:
    """Run PRAGMA integrity_check on a backup copy. Raises RuntimeError if not 'ok'."""
    conn = sqlite3.connect(str(path))
    try:
        result = conn.execute("PRAGMA integrity_check;").fetchone()
    finally:
        conn.close()
    if result is None or result[0] != "ok":
        raise RuntimeError(
            f"PRAGMA integrity_check failed on {path}: {result!r}. "
            "Backup aborted — do NOT upload a corrupt backup."
        )
    _LOG.info("integrity_check_passed path=%s", path)


def _gzip_file(path: Path) -> Path:
    gz_path = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    path.unlink()
    return gz_path


def _write_sha256(target: Path) -> Path:
    digest = _sha256_of_file(target)
    sidecar = target.with_name(target.name + ".sha256")
    sidecar.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return sidecar


def _prune_old(out_dir: Path, keep_days: int) -> int:
    if keep_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    removed = 0
    for entry in out_dir.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        if not name.startswith("jpintel-"):
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                entry.unlink()
                removed += 1
                _LOG.info("pruned %s", entry)
            except OSError as e:
                _LOG.warning("prune_failed path=%s err=%s", entry, e)
    return removed


def _configure_logging(log_file: Path | None) -> None:
    root = logging.getLogger("jpintel.backup")
    root.setLevel(logging.INFO)
    # Clear any prior handlers on re-entry (tests).
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    stderr_h = logging.StreamHandler(stream=sys.stderr)
    stderr_h.setFormatter(fmt)
    root.addHandler(stderr_h)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_h = logging.FileHandler(log_file, encoding="utf-8")
        file_h.setFormatter(fmt)
        root.addHandler(file_h)


def run_backup(
    db_path: Path,
    out_dir: Path,
    keep_days: int,
    gzip_enabled: bool,
) -> Path:
    """Run a single backup. Returns path to the final artifact (db or db.gz)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    final_name = f"jpintel-{ts}.db"
    # Stage inside out_dir to keep everything on one filesystem (atomic rename).
    with tempfile.TemporaryDirectory(prefix="jpintel-backup-", dir=str(out_dir)) as tmpd:
        staged = Path(tmpd) / final_name
        _LOG.info("backup_start src=%s staged=%s", db_path, staged)
        _online_backup(db_path, staged)

        # Move staged -> final path atomically within out_dir.
        final_path = out_dir / final_name
        staged.replace(final_path)

    _LOG.info("backup_written path=%s size=%d", final_path, final_path.stat().st_size)

    # Integrity check before compressing or uploading — abort on any corruption.
    _integrity_check(final_path)

    artifact = final_path
    if gzip_enabled:
        artifact = _gzip_file(final_path)
        _LOG.info("backup_gzipped path=%s size=%d", artifact, artifact.stat().st_size)

    sidecar = _write_sha256(artifact)
    _LOG.info("checksum_written path=%s", sidecar)

    removed = _prune_old(out_dir, keep_days)
    if removed:
        _LOG.info("pruned_count n=%d keep_days=%d", removed, keep_days)

    return artifact


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Online SQLite backup for jpintel-mcp")
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to source SQLite DB (default: JPINTEL_DB_PATH or ./data/jpintel.db)",
    )
    p.add_argument(
        "--out", type=Path, default=Path("/tmp/jpintel-backups"), help="Output directory"
    )
    p.add_argument("--keep", type=int, default=14, help="Retention in days (prune older files)")
    p.add_argument("--gzip", action="store_true", help="Gzip the .db after backup")
    p.add_argument("--log", type=Path, default=None, help="Optional log file path")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.log)

    db_path = args.db if args.db else _default_db_path()
    try:
        artifact = run_backup(
            db_path=db_path,
            out_dir=args.out,
            keep_days=args.keep,
            gzip_enabled=args.gzip,
        )
    except Exception as e:
        _LOG.error("backup_failed err=%s", e, exc_info=True)
        return 1

    print(str(artifact))
    return 0


if __name__ == "__main__":
    sys.exit(main())
