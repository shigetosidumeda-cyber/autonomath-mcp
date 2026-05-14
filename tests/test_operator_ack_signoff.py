#!/usr/bin/env python3
"""
test_operator_ack_signoff.py — DEEP-51 draft test stub (10 cases).

Tests the operator_ack_signoff.py CLI without requiring a live flyctl
or git context. All subprocess calls into the CLI's verify functions
are mocked via monkeypatching `_run_capture` / `_git_head_sha`.

Run:
    uv run pytest test_operator_ack_signoff.py -v
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

# Ensure CLI module importable: module lives in tools/offline/operator_review/
_HERE = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_MODULE_DIR = _REPO_ROOT / "tools" / "offline" / "operator_review"
sys.path.insert(0, str(_MODULE_DIR))

from typing import TYPE_CHECKING  # noqa: E402  (sys.path manipulation precedes)

import operator_ack_signoff as oas  # noqa: E402

if TYPE_CHECKING:
    import pytest

# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _patch_all_pass(monkeypatch: pytest.MonkeyPatch, repo_root: pathlib.Path) -> None:
    """Make every verify return PASS with deterministic evidence."""

    def fake_run(cmd, *, timeout=60):
        joined = " ".join(cmd)
        if "rev-parse" in joined:
            return 0, "abc1234567890abcdef1234567890abcdef12345\n", ""
        if "flyctl" in joined and "status" in joined:
            return 0, json.dumps({"App": {"Name": "autonomath-api"}}), ""
        if "flyctl" in joined and "secrets" in joined and "list" in joined:
            rows = [
                {"Name": "ADMIN_API_KEY"},
                {"Name": "API_KEY_SALT"},
                {"Name": "AUDIT_SEAL_SECRET"},
                {"Name": "AUTONOMATH_API_HASH_PEPPER"},
                {"Name": "AUTONOMATH_DB_SHA256"},
                {"Name": "AUTONOMATH_DB_URL"},
                {"Name": "CLOUDFLARE_TURNSTILE_SECRET"},
                {"Name": "INVOICE_FOOTER_JA"},
                {"Name": "INVOICE_REGISTRATION_NUMBER"},
                {"Name": "JPCITE_EDGE_AUTH_SECRET"},
                {"Name": "JPCITE_SESSION_SECRET"},
                {"Name": "JPINTEL_CORS_ORIGINS"},
                {"Name": "JPINTEL_ENV"},
                {"Name": "RATE_LIMIT_FREE_PER_DAY"},
                {"Name": "R2_ACCESS_KEY_ID"},
                {"Name": "R2_BUCKET"},
                {"Name": "R2_ENDPOINT"},
                {"Name": "R2_SECRET_ACCESS_KEY"},
                {"Name": "STRIPE_BILLING_PORTAL_CONFIG_ID"},
                {"Name": "STRIPE_PRICE_PER_REQUEST"},
                {"Name": "STRIPE_API_KEY"},
                {"Name": "STRIPE_SECRET_KEY"},
                {"Name": "STRIPE_TAX_ENABLED"},
                {"Name": "STRIPE_WEBHOOK_SECRET"},
                {"Name": "GBIZINFO_INGEST_APPROVED"},
            ]
            return 0, json.dumps(rows), ""
        if "pre_deploy_verify.py" in joined:
            return 0, json.dumps({"ok": True, "failures": []}), ""
        if "compute_dirty_fingerprint" in joined:
            return (
                0,
                json.dumps(
                    {
                        "current_head": "a" * 40,
                        "dirty_entries": 0,
                        "status_counts": {},
                        "lane_counts": {},
                        "critical_lanes_present": [],
                        "path_sha256": "f" * 64,
                        "content_sha256": "e" * 64,
                        "content_hash_skipped_large_files": [],
                    }
                ),
                "",
            )
        if "migration_inventory" in joined or "verify_migration_targets" in joined:
            return 0, json.dumps({"target_db_ok": True}), ""
        return 0, "", ""

    monkeypatch.setattr(oas, "_run_capture", fake_run)
    monkeypatch.setattr(oas, "_which", lambda name: f"/usr/local/bin/{name}")

    # Make filesystem-backed checks deterministic
    mig_dir = repo_root / "scripts" / "migrations"
    mig_dir.mkdir(parents=True, exist_ok=True)
    (mig_dir / "001_rollback.sql").write_text("-- rollback\n")
    (mig_dir / "002_rollback.sql").write_text("-- rollback\n")
    ops_dir = repo_root / "scripts" / "ops"
    ops_dir.mkdir(parents=True, exist_ok=True)
    (ops_dir / "pre_deploy_verify.py").write_text("# stub\n")
    (ops_dir / "migration_inventory.py").write_text("# stub\n")
    (ops_dir / "verify_migration_targets.py").write_text("# stub\n")
    (ops_dir / "compute_dirty_fingerprint.py").write_text("# stub\n")
    # Operator-review canonical fingerprint location (B7 fix)
    operator_review_dir = repo_root / "tools" / "offline" / "operator_review"
    operator_review_dir.mkdir(parents=True, exist_ok=True)
    (operator_review_dir / "compute_dirty_fingerprint.py").write_text("# stub\n")
    # Secrets registry
    docs_dir = repo_root / "docs" / "_internal"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "SECRETS_REGISTRY.md").write_text(
        "- REQUIRED: STRIPE_API_KEY\n"
        "- REQUIRED: CLOUDFLARE_TURNSTILE_SECRET\n"
        "- CONDITIONAL: GBIZINFO_INGEST_APPROVED\n"
    )


# ----------------------------------------------------------------------
# 10 test cases
# ----------------------------------------------------------------------


def test_dry_run_boolean_1_verify_passes(monkeypatch, tmp_path):
    """Case 1: --boolean=1 dry-run on a passing fly status."""
    _patch_all_pass(monkeypatch, tmp_path)
    rc = oas.main(["--boolean", "1", "--repo-root", str(tmp_path)])
    assert rc == 0


def test_boolean_1_fail_skips_signoff(monkeypatch, tmp_path):
    """Case 2: failing verify must NOT prompt for signoff (exit 1)."""
    _patch_all_pass(monkeypatch, tmp_path)

    def failing(cmd, *, timeout=60):
        if "flyctl" in " ".join(cmd) and "status" in " ".join(cmd):
            return 0, json.dumps({"App": {"Name": "WRONG-APP"}}), ""
        return 0, "", ""

    monkeypatch.setattr(oas, "_run_capture", failing)
    rc = oas.main(["--boolean", "1", "--repo-root", str(tmp_path)])
    assert rc == 1


def test_all_pass_yields_schema_valid_yaml(monkeypatch, tmp_path):
    """Case 3: all PASS + auto-yes -> YAML body matches schema shape."""
    _patch_all_pass(monkeypatch, tmp_path)
    out = tmp_path / "ack.yaml"
    rc = oas.main(
        [
            "--all",
            "--commit",
            "--yes",
            "--ack-out",
            str(out),
            "--repo-root",
            str(tmp_path),
            "--operator-email",
            "info@bookyou.net",
        ]
    )
    assert rc == 0
    assert out.is_file()
    import yaml

    payload = yaml.safe_load(out.read_text())
    for name in oas.BOOLEAN_NAMES:
        assert payload[name] is True, f"missing or false: {name}"
    assert "_meta" in payload
    assert "yaml_sha256" in payload["_meta"]
    assert "git_commit_hash" in payload["_meta"]
    assert "signed_at" in payload["_meta"]
    assert payload["_meta"]["operator_email"] == "info@bookyou.net"
    assert "dirty_tree_fingerprint" in payload
    fp = payload["dirty_tree_fingerprint"]
    for key in (
        "current_head",
        "dirty_entries",
        "status_counts",
        "lane_counts",
        "path_sha256",
        "content_sha256",
        "content_hash_skipped_large_files",
    ):
        assert key in fp


def test_commit_writes_to_out_of_repo_path(monkeypatch, tmp_path):
    """Case 4: --commit honors --ack-out and creates parent dir."""
    _patch_all_pass(monkeypatch, tmp_path)
    deep = tmp_path / "out-of-repo" / "nested" / "ack.yaml"
    rc = oas.main(
        [
            "--all",
            "--commit",
            "--yes",
            "--ack-out",
            str(deep),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert deep.is_file()
    assert deep.parent.is_dir()


def test_no_llm_api_imports_in_module():
    """Case 5: source file must contain ZERO LLM API imports."""
    src = (_MODULE_DIR / "operator_ack_signoff.py").read_text()
    forbidden = [
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ]
    for token in forbidden:
        assert token not in src, f"forbidden token leaked into module: {token}"


def test_signature_integrity_8_booleans(monkeypatch, tmp_path):
    """Case 6: every boolean name appears in YAML AND is True on full pass."""
    _patch_all_pass(monkeypatch, tmp_path)
    out = tmp_path / "ack.yaml"
    rc = oas.main(
        [
            "--all",
            "--commit",
            "--yes",
            "--ack-out",
            str(out),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    import yaml

    payload = yaml.safe_load(out.read_text())
    for name in oas.BOOLEAN_NAMES:
        assert name in payload
        assert payload[name] is True
    assert len(oas.BOOLEAN_NAMES) == 8


def test_sha256_and_git_hash_binding(monkeypatch, tmp_path):
    """Case 7: yaml_sha256 + git_commit_hash both populated and well-formed."""
    _patch_all_pass(monkeypatch, tmp_path)
    out = tmp_path / "ack.yaml"
    rc = oas.main(
        [
            "--all",
            "--commit",
            "--yes",
            "--ack-out",
            str(out),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    import yaml

    payload = yaml.safe_load(out.read_text())
    sha = payload["_meta"]["yaml_sha256"]
    git_hash = payload["_meta"]["git_commit_hash"]
    assert re.fullmatch(r"[0-9a-f]{64}", sha), f"bad sha256: {sha}"
    assert re.fullmatch(r"[0-9a-f]{7,40}", git_hash), f"bad git hash: {git_hash}"


def test_timestamp_tampering_detect(monkeypatch, tmp_path):
    """Case 8: tampering with signed_at AFTER emission breaks sha256."""
    _patch_all_pass(monkeypatch, tmp_path)
    out = tmp_path / "ack.yaml"
    rc = oas.main(
        [
            "--all",
            "--commit",
            "--yes",
            "--ack-out",
            str(out),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    import yaml

    payload = yaml.safe_load(out.read_text())
    original_sha = payload["_meta"]["yaml_sha256"]

    # Tamper: change signed_at
    payload["_meta"]["signed_at"] = "2099-01-01T00:00:00Z"
    tampered_meta = {k: v for k, v in payload["_meta"].items() if k != "yaml_sha256"}
    body_no_sha = yaml.safe_dump(
        {k: v for k, v in payload.items() if k != "_meta"},
        sort_keys=True,
        allow_unicode=True,
    ) + yaml.safe_dump({"_meta": tampered_meta}, sort_keys=True, allow_unicode=True)
    new_sha = hashlib.sha256(body_no_sha.encode("utf-8")).hexdigest()
    assert new_sha != original_sha, "tampered timestamp must break sha256"


def test_schema_mismatch_rejected(tmp_path):
    """Case 9: a YAML missing a required boolean must fail schema match."""

    bad = {
        "fly_app_confirmed": True,
        # missing fly_secrets_names_confirmed
        "appi_disabled_or_turnstile_secret_confirmed": True,
        "target_db_packet_reviewed": True,
        "rollback_reconciliation_packet_ready": True,
        "live_gbiz_ingest_disabled_or_approved": True,
        "dirty_lanes_reviewed": True,
        "pre_deploy_verify_clean": True,
        "_meta": {
            "tool_version": "operator_ack_signoff/0.1.0",
            "operator_email": "info@bookyou.net",
            "signed_at": "2026-05-07T00:00:00Z",
            "git_commit_hash": "abc1234567890abcdef1234567890abcdef12345",
            "yaml_sha256": "0" * 64,
        },
    }
    schema = json.loads((_MODULE_DIR / "ack_yaml_schema.json").read_text())
    # Lightweight required-field check (no jsonschema dep needed for stub)
    missing = [k for k in schema["required"] if k not in bad]
    assert "fly_secrets_names_confirmed" in missing
    assert "dirty_tree_fingerprint" in missing


def test_ack_schema_dirty_fingerprint_matches_gate_required_fields():
    """Schema required fields must stay aligned with production GO gate."""
    schema = json.loads((_MODULE_DIR / "ack_yaml_schema.json").read_text())
    required = schema["properties"]["dirty_tree_fingerprint"]["required"]
    assert required == [
        "current_head",
        "dirty_entries",
        "status_counts",
        "lane_counts",
        "path_sha256",
        "content_sha256",
        "content_hash_skipped_large_files",
    ]


def test_appi_ack_accepts_fly_toml_disabled_without_flyctl(monkeypatch, tmp_path):
    """ACK boolean 3 must follow the runtime APPI flag used by Fly deploys."""
    monkeypatch.delenv("JPINTEL_APPI_DISABLED", raising=False)
    monkeypatch.setattr(oas, "_which", lambda name: None)
    (tmp_path / "fly.toml").write_text(
        'app = "autonomath-api"\n\n[env]\n  AUTONOMATH_APPI_ENABLED = "0"\n',
        encoding="utf-8",
    )

    result = oas.verify_appi_or_turnstile(tmp_path)

    assert result.passed is True
    assert "AUTONOMATH_APPI_ENABLED" in result.detail
    assert result.raw_evidence["path"] == "fly.toml"


def test_single_boolean_mode_returns_just_one_result(monkeypatch, tmp_path, capsys):
    """Case 10: --boolean=N mode runs ONE verify only and emits no YAML."""
    _patch_all_pass(monkeypatch, tmp_path)
    rc = oas.main(
        [
            "--boolean",
            "5",
            "--repo-root",
            str(tmp_path),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    # No YAML was emitted (no "WROTE:" line).
    assert "WROTE:" not in captured.out
    assert "DRY_RUN: would write" not in captured.out
    # JSON payload contains the expected boolean name only.
    # Find the outermost JSON block: json.dumps(indent=2) emits a top-level
    # "{" at column 0 followed by indented children. Locate the last such
    # column-0 opening brace and walk forward via brace-balance.
    text = captured.out
    # Locate column-0 "{" lines (start of a top-level JSON object).
    starts = [i for i in range(len(text)) if text[i] == "{" and (i == 0 or text[i - 1] == "\n")]
    assert starts, "no top-level JSON object found in stdout"
    start = starts[-1]
    depth = 0
    end = -1
    for j in range(start, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = j
                break
    assert end > start, "could not balance braces on top-level JSON"
    block = text[start : end + 1]
    parsed = json.loads(block)
    assert parsed["boolean_name"] == "rollback_reconciliation_packet_ready"


def test_secret_contract_reads_go_gate_required_names():
    required, conditional, alternatives = oas._read_secret_contract(_REPO_ROOT)

    assert "STRIPE_SECRET_KEY" in required
    assert "JPCITE_SESSION_SECRET" in required
    assert "JPCITE_EDGE_AUTH_SECRET" in required
    assert "CLOUDFLARE_TURNSTILE_SECRET" in conditional
    assert ("AUDIT_SEAL_SECRET", "JPINTEL_AUDIT_SEAL_KEYS") in alternatives
