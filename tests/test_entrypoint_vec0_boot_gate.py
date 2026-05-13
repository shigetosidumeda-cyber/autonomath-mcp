from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "entrypoint.sh"
AUTONOMATH_BOOT_MANIFEST = REPO_ROOT / "scripts/migrations/autonomath_boot_manifest.txt"
JPCITE_BOOT_MANIFEST = REPO_ROOT / "scripts/migrations/jpcite_boot_manifest.txt"
_URL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+")
_PRODUCTION_RUNTIME_PATH_RE = re.compile(
    r"(?:^|[\s\"'=(:;,[<>|&]|:-)(?:/data|/seed|/app/scripts)(?=/|$|[\s\"'`;,)])"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_safe_entrypoint(tmp_path: Path, *, schema_guard: Path | None = None) -> Path:
    data_dir = tmp_path / "data"
    seed_dir = tmp_path / "seed"
    app_scripts_dir = tmp_path / "app" / "scripts"
    script = tmp_path / "entrypoint.sh"
    text = ENTRYPOINT.read_text(encoding="utf-8")
    # Wave 48 §4.x W48.x402: rewrite the seed_x402_endpoints.py path FIRST so
    # the subsequent `/seed` replacement doesn't corrupt it (the substring
    # `/seed` lives inside `/seed_x402_endpoints.py` and would be eaten by the
    # generic seed-dir substitution if reordered).
    text = text.replace(
        "/app/scripts/etl/seed_x402_endpoints.py",
        str(app_scripts_dir / "etl/seed_x402_endpoints.py"),
    )
    text = text.replace(
        "/app/scripts/ops/warmup_semantic_reranker.py",
        str(app_scripts_dir / "ops/warmup_semantic_reranker.py"),
    )
    text = text.replace("/data", str(data_dir))
    text = text.replace("/seed", str(seed_dir))
    text = text.replace("/app/scripts/migrate.py", str(app_scripts_dir / "migrate.py"))
    text = text.replace("/app/scripts/migrations", str(app_scripts_dir / "migrations"))
    text = text.replace(
        "/app/scripts/schema_guard.py",
        str(schema_guard or app_scripts_dir / "schema_guard.py"),
    )
    text = text.replace("python ", f'"{sys.executable}" ')
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def _entrypoint_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "AUTONOMATH_DB_URL",
        "AUTONOMATH_DB_SHA256",
        "AUTONOMATH_BOOTSTRAP_MODE",
        "AUTONOMATH_ENABLED",
        "DATA_SEED_VERSION",
        "JPCITE_DB_PATH",
        "JPINTEL_FORCE_SEED_OVERWRITE",
    ):
        env.pop(name, None)
    env.update(
        {
            "AUTONOMATH_DB_PATH": str(tmp_path / "autonomath.db"),
            "JPINTEL_DB_PATH": str(tmp_path / "jpintel.db"),
            "AUTONOMATH_BOOT_MIGRATION_MODE": "off",
        }
    )
    return env


def _run_entrypoint(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), "true"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def _strip_shell_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if char == "#" and quote is None and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def _runtime_script_lines(script: Path) -> list[str]:
    runtime_lines = []
    for line in script.read_text(encoding="utf-8").splitlines():
        runtime_line = _URL_RE.sub("<url>", _strip_shell_comment(line)).rstrip()
        if runtime_line.strip():
            runtime_lines.append(runtime_line)
    return runtime_lines


def test_entrypoint_vec0_migrations_degrade_without_boot_fail() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    assert "USING[[:space:]]+vec0" in text
    assert "AUTONOMATH_VEC0_PATH" in text
    assert "no such module: vec0" in text
    assert "am_mig_degraded" in text
    assert "autonomath vec0 migration degraded" in text
    assert "degraded=$am_mig_degraded failed=$am_mig_failed" in text


def test_entrypoint_optional_autonomath_tables_degrade_without_boot_fail() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    assert "no such table:" in text
    assert "optional source table missing" in text
    assert "schema_guard below still protects" in text
    assert "am_mig_degraded=$((am_mig_degraded + 1))" in text


def test_entrypoint_drops_empty_cross_polluted_programs_before_guard() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    autonomath_guard = (
        'python /app/scripts/schema_guard.py "$DB_PATH" autonomath --drop-empty-cross-pollution'
    )
    assert autonomath_guard in text
    assert text.index(autonomath_guard) < text.index("schema_guard failed for autonomath")


def test_entrypoint_seed_gate_uses_programs_table_contract() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    assert "SELECT COUNT(*) FROM programs;" in text
    assert "seed DB programs row-count below 10000 floor" in text


def test_entrypoint_autonomath_boot_migrations_are_manifest_gated_by_default() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    assert "AUTONOMATH_BOOT_MIGRATION_MODE:-manifest" in text
    assert "AUTONOMATH_BOOT_MIGRATION_MANIFEST" in text
    assert "autonomath_boot_manifest.txt" in text
    assert "am_mig_in_manifest" in text
    assert 'grep -Fxq "$name"' in text
    assert text.index('am_mig_in_manifest "$am_mig_id"') < text.index(
        'head -1 "$am_mig" | grep -q "target_db: autonomath"'
    )
    assert "AUTONOMATH_BOOT_MIGRATION_MODE=discover" in text


def test_autonomath_boot_manifest_is_synced_with_jpcite_manifest() -> None:
    assert AUTONOMATH_BOOT_MANIFEST.exists()
    assert JPCITE_BOOT_MANIFEST.exists()
    assert _sha256(AUTONOMATH_BOOT_MANIFEST) == _sha256(JPCITE_BOOT_MANIFEST)
    entries = [
        line.strip()
        for line in AUTONOMATH_BOOT_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert entries
    assert all("_rollback" not in entry for entry in entries)


def test_entrypoint_backgrounds_only_missing_db_r2_bootstrap() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    assert "missing_db=1" in text
    assert "sha_mismatch_db=0" in text
    assert "sha_mismatch_db=1" in text
    assert "AUTONOMATH_BOOTSTRAP_MODE:-background" in text
    assert "bootstrap_autonomath_db_snapshot background" in text
    assert ") &" in text
    assert "bootstrap_autonomath_db_snapshot foreground || exit 1" in text
    assert '"$missing_db" -eq 1' in text
    assert '"$sha_mismatch_db" -eq 1' in text
    assert "SHA256 mismatch (have=$existing_sha want=$DB_SHA256) — re-downloading" in text
    assert text.index("SHA256 mismatch (have=$existing_sha want=$DB_SHA256)") < text.index(
        "bootstrap_autonomath_db_snapshot foreground || exit 1"
    )
    url_unset_check = 'if [ -z "$DB_URL" ]; then'
    missing_skip = "AUTONOMATH_DB_URL unset and DB missing — skipping bootstrap"
    mismatch_fail = "AUTONOMATH_DB_URL unset and existing DB SHA256 mismatch — failing boot"
    assert text.index(url_unset_check) < text.index('if [ "$missing_db" -eq 1 ]; then')
    assert text.index('if [ "$missing_db" -eq 1 ]; then') < text.index(missing_skip)
    assert text.index(missing_skip) < text.index(mismatch_fail)
    assert text.index(mismatch_fail) < text.index("exit 1", text.index(mismatch_fail))
    assert 'if [ "$mode" = "foreground" ]; then' in text
    assert 'rm -f "$TMP_DB"' in text


def test_entrypoint_validates_staged_background_bootstrap_before_atomic_mv() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    staged_guard = (
        'python /app/scripts/schema_guard.py "$TMP_DB" autonomath --drop-empty-cross-pollution'
    )
    atomic_mv = 'mv "$TMP_DB" "$DB_PATH"'
    background_gate = (
        'if [ "$needs_download" -eq 1 ] && [ "$missing_db" -eq 1 ] '
        '&& [ "$AUTONOMATH_BOOTSTRAP_MODE" = "background" ]; then'
    )

    assert 'if [ "$mode" = "background" ] && [ -f /app/scripts/schema_guard.py ]; then' in text
    assert "if ! curl -fL --retry 5 --retry-delay 10 --retry-all-errors \\" in text
    assert "DB snapshot download failed" in text
    assert (
        'if ! python /app/scripts/schema_guard.py "$TMP_DB" autonomath --drop-empty-cross-pollution; then'
        in text
    )
    assert "schema_guard failed for staged autonomath snapshot" in text
    assert 'if ! mv "$TMP_DB" "$DB_PATH"; then' in text
    assert staged_guard in text
    assert text.index(staged_guard) < text.index(atomic_mv)
    assert background_gate in text
    assert text.index(background_gate) < text.index("bootstrap_autonomath_db_snapshot background")


def test_write_safe_entrypoint_rewrites_executable_production_paths(tmp_path: Path) -> None:
    script = _write_safe_entrypoint(tmp_path)
    runtime_lines = _runtime_script_lines(script)
    runtime_text = "\n".join(runtime_lines)

    assert str(tmp_path / "data") in runtime_text
    assert str(tmp_path / "seed") in runtime_text
    assert str(tmp_path / "app" / "scripts") in runtime_text
    assert [line for line in runtime_lines if _PRODUCTION_RUNTIME_PATH_RE.search(line)] == []


def test_entrypoint_env_removes_parent_bootstrap_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMATH_BOOTSTRAP_MODE", "foreground")

    env = _entrypoint_env(tmp_path)

    assert os.environ["AUTONOMATH_BOOTSTRAP_MODE"] == "foreground"
    assert "AUTONOMATH_BOOTSTRAP_MODE" not in env


def test_entrypoint_runtime_degrades_missing_db_when_url_unset(tmp_path: Path) -> None:
    script = _write_safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)

    result = _run_entrypoint(script, env)

    assert result.returncode == 0, result.stderr
    assert "AUTONOMATH_DB_URL unset and DB missing — skipping bootstrap" in result.stdout
    assert not Path(env["AUTONOMATH_DB_PATH"]).exists()


def test_entrypoint_runtime_fails_existing_sha_mismatch_when_url_unset(
    tmp_path: Path,
) -> None:
    script = _write_safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    db_path = Path(env["AUTONOMATH_DB_PATH"])
    db_path.write_bytes(b"old-db")
    env["AUTONOMATH_DB_SHA256"] = hashlib.sha256(b"new-db").hexdigest()

    result = _run_entrypoint(script, env)

    assert result.returncode == 1
    assert "AUTONOMATH_DB_URL unset and existing DB SHA256 mismatch — failing boot" in result.stderr
    assert db_path.read_bytes() == b"old-db"


def test_entrypoint_runtime_backgrounds_only_missing_db(tmp_path: Path) -> None:
    script = _write_safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    snapshot = tmp_path / "snapshot.db"
    snapshot.write_bytes(b"fresh-db")
    env["AUTONOMATH_DB_URL"] = snapshot.as_uri()
    env["AUTONOMATH_DB_SHA256"] = _sha256(snapshot)

    result = _run_entrypoint(script, env)

    assert result.returncode == 0, result.stderr
    assert "starting background autonomath DB bootstrap" in result.stdout
    assert "downloading DB snapshot from R2 (background)" in result.stdout
    assert "downloading DB snapshot from R2 (foreground)" not in result.stdout
    assert Path(env["AUTONOMATH_DB_PATH"]).read_bytes() == b"fresh-db"


def test_entrypoint_runtime_sha_mismatch_uses_foreground_even_if_background_mode(
    tmp_path: Path,
) -> None:
    script = _write_safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    db_path = Path(env["AUTONOMATH_DB_PATH"])
    db_path.write_bytes(b"old-db")
    snapshot = tmp_path / "snapshot.db"
    snapshot.write_bytes(b"fresh-db")
    env["AUTONOMATH_DB_URL"] = snapshot.as_uri()
    env["AUTONOMATH_DB_SHA256"] = _sha256(snapshot)
    env["AUTONOMATH_BOOTSTRAP_MODE"] = "background"

    result = _run_entrypoint(script, env)

    assert result.returncode == 0, result.stderr
    assert "starting background autonomath DB bootstrap" not in result.stdout
    assert "downloading DB snapshot from R2 (foreground)" in result.stdout
    assert db_path.read_bytes() == b"fresh-db"


def test_entrypoint_runtime_background_schema_guard_failure_does_not_land_db(
    tmp_path: Path,
) -> None:
    schema_guard = tmp_path / "schema_guard.py"
    marker = tmp_path / "schema_guard_called"
    schema_guard.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('called', encoding='utf-8')\n"
        "raise SystemExit(42)\n",
        encoding="utf-8",
    )
    script = _write_safe_entrypoint(tmp_path, schema_guard=schema_guard)
    env = _entrypoint_env(tmp_path)
    snapshot = tmp_path / "snapshot.db"
    snapshot.write_bytes(b"fresh-db")
    db_path = Path(env["AUTONOMATH_DB_PATH"])
    env["AUTONOMATH_DB_URL"] = snapshot.as_uri()
    env["AUTONOMATH_DB_SHA256"] = _sha256(snapshot)

    result = _run_entrypoint(script, env)

    assert result.returncode == 0, result.stderr
    assert "schema_guard failed for staged autonomath snapshot" in result.stderr
    assert marker.read_text(encoding="utf-8") == "called"
    assert not db_path.exists()
    assert not Path(f"{db_path}.partial").exists()
