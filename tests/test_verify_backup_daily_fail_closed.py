"""Fail-closed gates for scripts/cron/verify_backup_daily.py."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "cron" / "verify_backup_daily.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_backup_daily_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wire_sidecar(mod: Any, tmp_path: Path) -> Path:
    sidecar = tmp_path / "backup_verify_daily.json"
    mod.SIDECAR = sidecar
    mod.ANALYTICS = tmp_path
    return sidecar


def _snapshot(*, age_hours: float = 0.1, checksum_listed: bool = True, size: int = 128) -> dict[str, Any]:
    key = "jpintel/jpintel-20260513-000000.db.gz"
    return {
        "key": key,
        "mtime": datetime.now(UTC) - timedelta(hours=age_hours),
        "size_bytes": size,
        "checksum_key": key + ".sha256",
        "checksum_listed": checksum_listed,
    }


def test_prod_dry_run_fails_closed(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    sidecar = _wire_sidecar(mod, tmp_path)
    monkeypatch.setenv("JPINTEL_ENV", "production")
    monkeypatch.setattr(mod, "_latest_r2_snapshot", lambda prefix, bucket: _snapshot())

    rc = mod.run(["--dry-run"])

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["integrity_pass"] == 0
    assert payload["r2_hash_match"] == 0
    assert payload["details"]["error"] == "dry_run_forbidden_in_prod"


def test_missing_checksum_listing_fails_before_dry_run_green(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    sidecar = _wire_sidecar(mod, tmp_path)
    monkeypatch.delenv("JPINTEL_ENV", raising=False)
    monkeypatch.setattr(
        mod,
        "_latest_r2_snapshot",
        lambda prefix, bucket: _snapshot(checksum_listed=False),
    )

    rc = mod.run(["--dry-run"])

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert rc == 2
    assert payload["integrity_pass"] == 0
    assert payload["r2_hash_match"] == 0
    assert payload["details"]["error"] == "no_r2_checksum"
    assert payload["details"]["checksum_listed"] is False


def test_stale_r2_snapshot_fails_rpo_gate(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    sidecar = _wire_sidecar(mod, tmp_path)
    monkeypatch.setattr(
        mod,
        "_latest_r2_snapshot",
        lambda prefix, bucket: _snapshot(age_hours=3.0, checksum_listed=True),
    )

    rc = mod.run(["--dry-run", "--max-age-hours", "2"])

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert rc == 2
    assert payload["rpo_pass"] == 0
    assert payload["details"]["error"] == "stale_r2_snapshot"
    assert payload["details"]["latest_age_hours"] >= 3.0


def test_download_path_requires_matching_checksum_and_size(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    sidecar = _wire_sidecar(mod, tmp_path)
    stage = tmp_path / "stage"
    monkeypatch.setenv("VERIFY_STAGE_DIR", str(stage))

    raw = b"SQLite format 3\000" + (b"jpcite-backup" * 100)
    gz_bytes = gzip.compress(raw)
    sha = hashlib.sha256(gz_bytes).hexdigest()
    snap = _snapshot(size=len(gz_bytes), checksum_listed=True)
    monkeypatch.setattr(mod, "_latest_r2_snapshot", lambda prefix, bucket: snap)

    def fake_download(key: str, dest: Path, bucket: str | None) -> bool:
        if key.endswith(".sha256"):
            dest.write_text(f"{sha}  {Path(snap['key']).name}\n", encoding="utf-8")
        else:
            dest.write_bytes(gz_bytes)
        return True

    monkeypatch.setattr(mod, "_r2_download", fake_download)

    rc = mod.run(["--max-age-hours", "2"])

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["integrity_pass"] == 1
    assert payload["r2_hash_match"] == 1
    assert payload["gzip_ok"] == 1
    assert payload["rpo_pass"] == 1
