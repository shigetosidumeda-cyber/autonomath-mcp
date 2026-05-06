"""Shared R2 (Cloudflare) helper for backup cron scripts.

Wraps the existing `rclone` binary that is already installed in the Fly image
(see scripts/cron/r2_backup.sh). Pure-Python S3v4 signing was rejected to
avoid adding boto3 as a runtime dep — rclone is already vetted, supports
Cloudflare R2 natively, and keeps secrets in env vars rather than on disk.

Required env (set via `flyctl secrets set ...`):
    R2_ENDPOINT            https://<acct>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID       Cloudflare R2 API token access key.
    R2_SECRET_ACCESS_KEY   Cloudflare R2 API token secret.
    R2_BUCKET              Bucket name (default: autonomath-backup).

Functions
---------
upload(local, remote_key, *, bucket=None) -> None
list_keys(prefix, *, bucket=None) -> list[tuple[str, datetime, int]]
delete(remote_key, *, bucket=None) -> None
download(remote_key, local, *, bucket=None) -> None
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_LOG = logging.getLogger("jpintel.r2")


class R2ConfigError(RuntimeError):
    """Raised when R2 env vars or rclone binary are missing."""


def _require_env() -> dict[str, str]:
    missing = [
        k
        for k in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
        if not os.environ.get(k)
    ]
    if missing:
        raise R2ConfigError(f"missing R2 env: {missing}")
    if not shutil.which("rclone"):
        raise R2ConfigError("rclone not on PATH (apt install rclone OR add to image)")
    return {
        "endpoint": os.environ["R2_ENDPOINT"],
        "access_key": os.environ["R2_ACCESS_KEY_ID"],
        "secret_key": os.environ["R2_SECRET_ACCESS_KEY"],
    }


def _bucket(name: str | None) -> str:
    return (
        name
        or os.environ.get("R2_BUCKET")
        or os.environ.get("JPINTEL_BACKUP_BUCKET", "autonomath-backup")
    )


def _rclone_args(env: dict[str, str]) -> list[str]:
    return [
        "rclone",
        "--config",
        "/dev/null",
        "--s3-endpoint",
        env["endpoint"],
        "--s3-access-key-id",
        env["access_key"],
        "--s3-secret-access-key",
        env["secret_key"],
        "--s3-region",
        "auto",
        "--s3-provider",
        "Cloudflare",
    ]


def upload(local: Path, remote_key: str, *, bucket: str | None = None) -> None:
    env = _require_env()
    b = _bucket(bucket)
    cmd = _rclone_args(env) + ["copyto", str(local), f":s3:{b}/{remote_key}"]
    _LOG.info("r2_upload start key=%s bytes=%d", remote_key, local.stat().st_size)
    subprocess.run(cmd, check=True)
    _LOG.info("r2_upload done key=%s", remote_key)


def download(remote_key: str, local: Path, *, bucket: str | None = None) -> None:
    env = _require_env()
    b = _bucket(bucket)
    local.parent.mkdir(parents=True, exist_ok=True)
    cmd = _rclone_args(env) + ["copyto", f":s3:{b}/{remote_key}", str(local)]
    _LOG.info("r2_download start key=%s -> %s", remote_key, local)
    subprocess.run(cmd, check=True)
    _LOG.info("r2_download done key=%s bytes=%d", remote_key, local.stat().st_size)


def list_keys(
    prefix: str,
    *,
    bucket: str | None = None,
) -> list[tuple[str, datetime, int]]:
    """Return [(key, mtime_utc, size_bytes), ...] for a prefix."""
    env = _require_env()
    b = _bucket(bucket)
    cmd = _rclone_args(env) + ["lsf", "--format", "tps", f":s3:{b}/{prefix}"]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    out: list[tuple[str, datetime, int]] = []
    for line in proc.stdout.splitlines():
        parts = line.split(";")
        if len(parts) < 3:
            continue
        ts_str, path, size = parts[0], parts[1], parts[2]
        try:
            mtime = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        try:
            sz = int(size)
        except ValueError:
            sz = 0
        out.append((f"{prefix.rstrip('/')}/{path}".lstrip("/"), mtime, sz))
    return out


def delete(remote_key: str, *, bucket: str | None = None) -> None:
    env = _require_env()
    b = _bucket(bucket)
    cmd = _rclone_args(env) + ["deletefile", f":s3:{b}/{remote_key}"]
    _LOG.info("r2_delete start key=%s", remote_key)
    subprocess.run(cmd, check=True)
    _LOG.info("r2_delete done key=%s", remote_key)
