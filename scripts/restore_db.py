#!/usr/bin/env python3
"""Restore jpintel.db OR autonomath.db from an R2 backup.

Workflow
--------
1. Resolve target backup key (latest if --backup-key omitted).
2. Pre-backup: take a snapshot of the *current* live DB to the DB-specific
   pre-restore directory under a `pre-restore-<ts>.db.gz` name. Restore is
   reversible unless the free-space gate fails.
3. Download the chosen backup from R2 into /tmp/.
4. Verify SHA256 against the sidecar.
5. PRAGMA integrity_check on the decompressed file.
6. Atomically swap into the live path:
       a. write to <live>.restore-tmp
       b. fsync
       c. remove live -wal / -shm sidecars (force fresh open)
       d. os.replace(<tmp>, <live>)
7. Optionally restart the API: `flyctl machine restart <id>` if --restart
   and FLY_API_TOKEN is set.

Examples
--------
    # Restore latest jpintel backup, no API restart (manual):
    python scripts/restore_db.py --db jpintel

    # Restore a specific autonomath snapshot:
    python scripts/restore_db.py --db autonomath \\
        --backup-key autonomath-api/autonomath-db/jpintel-20260428-040000.db.gz

    # Local dry-run (no R2, use a local file):
    python scripts/restore_db.py --db jpintel \\
        --local-file /tmp/jpintel-20260428-232703.db.gz \\
        --target /tmp/jpintel-restored.db

Required env when downloading from R2:
    R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
    R2_BUCKET (or JPINTEL_BACKUP_BUCKET).

Exit codes: 0 ok / 1 config / 2 download / 3 verify / 4 swap / 5 restart.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cron._r2_client import R2ConfigError, download, list_keys  # type: ignore

_LOG = logging.getLogger("jpintel.restore_db")
_FREE_SPACE_MARGIN_BYTES = 512 * 1024 * 1024

_DB_DEFAULTS = {
    "jpintel": {
        "live_path": "/data/jpintel.db",
        "prefix": "jpintel/",
        "name_glob": "jpintel-",
        "pre_backup_dir": "/data/backups/pre-restore",
    },
    "autonomath": {
        "live_path": "/data/autonomath.db",
        # weekly-backup-autonomath.yml stores autonomath snapshots under this
        # prefix but backup.py currently emits jpintel-*.db.gz filenames for any
        # source DB. The separate prefix disambiguates the database.
        "prefix": "autonomath-api/autonomath-db/",
        "name_glob": "jpintel-",
        "pre_backup_dir": "/data/backups-autonomath/pre-restore",
    },
}


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _resolve_latest(prefix: str, bucket: str | None, name_prefix: str) -> str:
    items = list_keys(prefix, bucket=bucket)
    items = [
        it for it in items if Path(it[0]).name.startswith(name_prefix) and it[0].endswith(".db.gz")
    ]
    if not items:
        raise RuntimeError(f"no backups found under prefix={prefix!r}")
    items.sort(key=lambda x: x[1], reverse=True)
    return items[0][0]


def _decompress(src: Path, dst: Path) -> None:
    with gzip.open(src, "rb") as f_in, dst.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def _verify_sha(gz: Path, sha_path: Path) -> None:
    expected = sha_path.read_text(encoding="utf-8").split()[0]
    actual = _sha256(gz)
    if expected != actual:
        raise RuntimeError(f"sha256 mismatch expected={expected} actual={actual}")
    _LOG.info("sha256_ok %s", gz.name)


def _integrity(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("PRAGMA integrity_check;").fetchone()
    finally:
        conn.close()
    if row is None or row[0] != "ok":
        raise RuntimeError(f"integrity_check failed result={row!r}")
    _LOG.info("integrity_ok %s", db)


def _require_free_space(path: Path, required_bytes: int, label: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free
    if free < required_bytes:
        raise RuntimeError(
            f"insufficient free space for {label}: free={free} required={required_bytes} path={path}"
        )
    _LOG.info(
        "free_space_ok label=%s path=%s free=%d required=%d",
        label,
        path,
        free,
        required_bytes,
    )


def _pre_backup(live: Path, out_dir: Path) -> Path | None:
    if not live.is_file():
        _LOG.warning("pre_backup_skip live=%s not present", live)
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    # sqlite backup writes a raw DB, then gzip writes a second file before the
    # raw file is removed. Require 2x live size plus margin so the safety copy
    # cannot fill the volume halfway through restore.
    _require_free_space(
        out_dir,
        live.stat().st_size * 2 + _FREE_SPACE_MARGIN_BYTES,
        "pre-restore backup",
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst = out_dir / f"pre-restore-{live.stem}-{ts}.db"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backup import _online_backup, _gzip_file, _write_sha256  # type: ignore

    _online_backup(live, dst)
    gz = _gzip_file(dst)
    _write_sha256(gz)
    _LOG.info("pre_backup_ok path=%s", gz)
    return gz


def _atomic_swap(src: Path, live: Path) -> None:
    live.parent.mkdir(parents=True, exist_ok=True)
    _require_free_space(
        live.parent,
        src.stat().st_size + _FREE_SPACE_MARGIN_BYTES,
        "restore swap tmp",
    )
    tmp = live.with_suffix(live.suffix + ".restore-tmp")
    shutil.copyfile(src, tmp)
    with tmp.open("rb") as f:
        os.fsync(f.fileno())
    for sib in (live.with_suffix(live.suffix + "-wal"), live.with_suffix(live.suffix + "-shm")):
        if sib.exists():
            sib.unlink()
    os.replace(tmp, live)
    _LOG.info("atomic_swap_ok target=%s", live)


def _restart_api() -> int:
    app = os.environ.get("FLY_APP", "autonomath-api")
    if not shutil.which("flyctl"):
        _LOG.warning("flyctl not on PATH — restart manually: flyctl machine restart --app %s", app)
        return 5
    try:
        subprocess.run(["flyctl", "machine", "restart", "--app", app], check=True)
        _LOG.info("api_restarted app=%s", app)
        return 0
    except subprocess.CalledProcessError as exc:
        _LOG.error("restart_failed err=%s", exc)
        return 5


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Restore SQLite DB from R2 backup.")
    p.add_argument("--db", choices=("jpintel", "autonomath"), required=True)
    p.add_argument("--backup-key", default=None, help="R2 object key (default: latest)")
    p.add_argument("--target", default=None, help="Override live DB path (default: /data/<db>.db)")
    p.add_argument("--local-file", default=None, help="Skip R2; restore from local .db.gz")
    p.add_argument("--no-pre-backup", action="store_true", help="Skip pre-restore safety snapshot")
    p.add_argument("--restart", action="store_true", help="flyctl machine restart after swap")
    p.add_argument("--yes", action="store_true", help="Confirm overwrite of live DB")
    args = p.parse_args()

    cfg = _DB_DEFAULTS[args.db]
    live = Path(args.target) if args.target else Path(cfg["live_path"])
    bucket = os.environ.get("R2_BUCKET") or os.environ.get("JPINTEL_BACKUP_BUCKET")

    with tempfile.TemporaryDirectory(prefix="restore-") as td:
        work = Path(td)
        if args.local_file:
            gz = Path(args.local_file)
            sha_path = gz.with_suffix(gz.suffix + ".sha256")
            if not gz.is_file() or not sha_path.is_file():
                _LOG.error("local_file_missing gz=%s sha=%s", gz, sha_path)
                return 1
        else:
            try:
                key = args.backup_key or _resolve_latest(cfg["prefix"], bucket, cfg["name_glob"])
            except Exception as exc:
                _LOG.error("resolve_failed err=%s", exc)
                return 2
            gz = work / Path(key).name
            sha_path = work / (Path(key).name + ".sha256")
            try:
                download(key, gz, bucket=bucket)
                download(key + ".sha256", sha_path, bucket=bucket)
            except R2ConfigError as exc:
                _LOG.error("r2_config_error err=%s", exc)
                return 1
            except Exception as exc:
                _LOG.exception("download_failed err=%s", exc)
                return 2

        try:
            _verify_sha(gz, sha_path)
        except Exception as exc:
            _LOG.error("verify_failed err=%s", exc)
            return 3

        decompressed = work / Path(gz.stem)
        _decompress(gz, decompressed)
        try:
            _integrity(decompressed)
        except Exception as exc:
            _LOG.error("integrity_failed err=%s", exc)
            return 3

        if not args.yes:
            _LOG.error("Refusing to overwrite %s -- pass --yes to confirm", live)
            return 1

        if not args.no_pre_backup:
            pb_dir = Path(os.environ.get("RESTORE_PRE_BACKUP_DIR", str(cfg["pre_backup_dir"])))
            try:
                _pre_backup(live, pb_dir)
            except Exception as exc:
                _LOG.error(
                    "pre_backup_failed err=%s "
                    "(restore aborted; use --no-pre-backup only after manual snapshot)",
                    exc,
                )
                return 4

        try:
            _atomic_swap(decompressed, live)
        except Exception as exc:
            _LOG.exception("swap_failed err=%s", exc)
            return 4

    if args.restart:
        rc = _restart_api()
        if rc != 0:
            return rc

    _LOG.info("restore_ok db=%s target=%s", args.db, live)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
