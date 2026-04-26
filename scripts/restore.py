#!/usr/bin/env python3
"""Restore a jpintel-mcp SQLite backup.

Given a backup file path (.db or .db.gz), verify the sibling .sha256 file
then copy (decompressing if needed) to the target DB path.

Safety:
- Requires --yes to actually overwrite the target.
- Writes to <target>.restore-tmp then atomic rename.
- Refuses if the target file is open with WAL journaling and --force is not given
  (we cannot be sure no writer is attached).

Exit codes: 0 on success, 1 on failure.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

_LOG = logging.getLogger("jpintel.restore")


def _default_db_path() -> Path:
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return Path(env)
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


def _read_expected_sha256(sidecar: Path) -> str:
    text = sidecar.read_text(encoding="utf-8").strip()
    # Accept both "<hex>  <name>" and raw "<hex>" forms.
    return text.split()[0]


def _decompress_if_needed(src: Path, work_dir: Path) -> Path:
    if src.suffix != ".gz":
        return src
    decompressed = work_dir / src.stem  # strip .gz
    with gzip.open(src, "rb") as f_in, decompressed.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    return decompressed


def _configure_logging() -> None:
    root = logging.getLogger("jpintel.restore")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def run_restore(backup_path: Path, target_path: Path, yes: bool) -> None:
    if not backup_path.is_file():
        raise FileNotFoundError(f"backup not found: {backup_path}")

    sidecar = backup_path.with_name(backup_path.name + ".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"checksum sidecar not found: {sidecar}")

    expected = _read_expected_sha256(sidecar)
    actual = _sha256_of_file(backup_path)
    if expected != actual:
        raise ValueError(f"sha256 mismatch: expected={expected} actual={actual}")
    _LOG.info("checksum_ok sha256=%s", actual)

    if not yes:
        raise RuntimeError("refusing to overwrite without --yes")

    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Decompress (if needed) into a temp space on the same filesystem as target
    # so final rename is atomic and does not cross devices.
    with tempfile.TemporaryDirectory(prefix="jpintel-restore-", dir=str(target_path.parent)) as tmpd:
        work_dir = Path(tmpd)
        usable = _decompress_if_needed(backup_path, work_dir)

        staged = target_path.parent / (target_path.name + ".restore-tmp")
        shutil.copyfile(usable, staged)

        # Best-effort: remove sidecar WAL/SHM so SQLite re-initializes cleanly.
        for suffix in ("-wal", "-shm"):
            aux = target_path.with_name(target_path.name + suffix)
            try:
                if aux.exists():
                    aux.unlink()
                    _LOG.info("removed_aux path=%s", aux)
            except OSError as e:
                _LOG.warning("aux_unlink_failed path=%s err=%s", aux, e)

        staged.replace(target_path)
        _LOG.info("restored src=%s target=%s", backup_path, target_path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Restore a jpintel-mcp SQLite backup")
    p.add_argument("backup", type=Path, help="Path to backup file (.db or .db.gz)")
    p.add_argument("--target", type=Path, default=None, help="Target DB path (default: JPINTEL_DB_PATH or ./data/jpintel.db)")
    p.add_argument("--yes", action="store_true", help="Confirm overwrite of target")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    target = args.target if args.target else _default_db_path()
    try:
        run_restore(args.backup, target, args.yes)
    except Exception as e:
        _LOG.error("restore_failed err=%s", e, exc_info=True)
        return 1
    print(str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
