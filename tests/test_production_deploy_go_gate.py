from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "production_deploy_go_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("production_deploy_go_gate", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _minimal_repo(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "docs" / "_internal").mkdir(parents=True)
    (root / "docs" / "runbook").mkdir(parents=True)
    (root / "docs" / "legal").mkdir(parents=True)
    (root / "scripts" / "migrations").mkdir(parents=True)
    (root / ".env.example").write_text(
        "# fly secrets set GBIZINFO_API_TOKEN=... -a autonomath-api\n",
        encoding="utf-8",
    )
    (root / "fly.toml").write_text('app = "autonomath-api"\n', encoding="utf-8")
    secret_names = "\n".join(
        [
            "ADMIN_API_KEY",
            "API_KEY_SALT",
            "AUDIT_SEAL_SECRET",
            "AUTONOMATH_API_HASH_PEPPER",
            "AUTONOMATH_DB_SHA256",
            "AUTONOMATH_DB_URL",
            "INVOICE_FOOTER_JA",
            "INVOICE_REGISTRATION_NUMBER",
            "JPCITE_SESSION_SECRET",
            "JPINTEL_AUDIT_SEAL_KEYS",
            "JPINTEL_CORS_ORIGINS",
            "JPINTEL_ENV",
            "RATE_LIMIT_FREE_PER_DAY",
            "R2_ACCESS_KEY_ID",
            "R2_BUCKET",
            "R2_ENDPOINT",
            "R2_SECRET_ACCESS_KEY",
            "STRIPE_BILLING_PORTAL_CONFIG_ID",
            "STRIPE_PRICE_PER_REQUEST",
            "STRIPE_SECRET_KEY",
            "STRIPE_TAX_ENABLED",
            "STRIPE_WEBHOOK_SECRET",
            "CLOUDFLARE_TURNSTILE_SECRET",
            "GBIZINFO_API_TOKEN",
        ]
    )
    (root / "docs" / "_internal" / "SECRETS_REGISTRY.md").write_text(
        f"autonomath-api\n{secret_names}\n",
        encoding="utf-8",
    )
    (root / "scripts" / "migrations" / "wave24_164_gbiz_v2_mirror_tables.sql").write_text(
        "-- target_db: autonomath\nselect 1;\n",
        encoding="utf-8",
    )
    (root / "scripts" / "migrations" / "wave24_166_credit_pack_reservation.sql").write_text(
        "-- target_db: jpintel\nselect 1;\n",
        encoding="utf-8",
    )
    (
        root / "scripts" / "migrations" / "wave24_166_credit_pack_reservation_rollback.sql"
    ).write_text(
        "-- boot_time: manual\nselect 1;\n",
        encoding="utf-8",
    )
    return root


def test_fly_app_command_context_detects_legacy_alias(tmp_path: Path) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    (root / "docs" / "_internal" / "bad.md").write_text(
        "flyctl logs -a jpintel-mcp\n",
        encoding="utf-8",
    )

    check = mod.check_fly_app_command_contexts(root)

    assert check.ok is False
    assert any("legacy_fly_app_context" in issue for issue in check.issues)


def test_fly_app_command_context_detects_quoted_equals_legacy_alias(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "deploy.yml").write_text(
        "steps:\n  - run: fly deploy --app='jpcite-api'\n  - run: flyctl logs -a=jpintel-mcp\n",
        encoding="utf-8",
    )

    check = mod.check_fly_app_command_contexts(root)

    assert check.ok is False
    assert sum("legacy_fly_app_context" in issue for issue in check.issues) == 2


def test_fly_app_command_context_allows_shadow_jpcite_api_workflow(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    workflow = root / ".github" / "workflows" / "deploy-jpcite-api.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        "steps:\n  - run: flyctl secrets list -a jpcite-api\n",
        encoding="utf-8",
    )

    check = mod.check_fly_app_command_contexts(root)

    assert check.ok is True
    assert (
        ".github/workflows/deploy-jpcite-api.yml" in check.evidence["allowed_legacy_context_files"]
    )


def test_fly_app_command_context_detects_fly_toml_mismatch(tmp_path: Path) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    (root / "fly.toml").write_text('app = "jpcite-api"\n', encoding="utf-8")

    check = mod.check_fly_app_command_contexts(root)

    assert check.ok is False
    assert any("fly_toml_app_mismatch" in issue for issue in check.issues)


def test_migration_target_boundaries_flag_wrong_target(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    (root / "scripts" / "migrations" / "wave24_166_credit_pack_reservation.sql").write_text(
        "-- target_db: autonomath\nselect 1;\n",
        encoding="utf-8",
    )
    (
        root / "scripts" / "migrations" / "wave24_166_credit_pack_reservation_rollback.sql"
    ).write_text(
        "-- target_db: jpintel\ndelete from credit_pack_reservation;\n",
        encoding="utf-8",
    )

    check = mod.check_migration_target_boundaries(root)

    assert check.ok is False
    assert any("migration_target_mismatch" in issue for issue in check.issues)
    assert not any("rollback_has_auto_target" in issue for issue in check.issues)


def test_migration_target_boundaries_scan_dirty_forward_migrations(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    bad = root / "scripts" / "migrations" / "wave24_bad.sql"
    bad.write_text(
        "-- target_db: jpintel\nDELETE FROM api_keys;\n",
        encoding="utf-8",
    )
    missing = root / "scripts" / "migrations" / "wave24_missing.sql"
    missing.write_text("CREATE TABLE missing_target(id integer);\n", encoding="utf-8")
    ok_view = root / "scripts" / "migrations" / "wave24_view_refresh.sql"
    ok_view.write_text(
        "-- target_db: autonomath\n"
        "DROP VIEW IF EXISTS v_refresh;\n"
        "CREATE VIEW v_refresh AS SELECT 1 AS ok;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mod,
        "_git_status",
        lambda _repo_root: [
            "?? scripts/migrations/wave24_bad.sql",
            "?? scripts/migrations/wave24_missing.sql",
            "?? scripts/migrations/wave24_view_refresh.sql",
        ],
    )

    check = mod.check_migration_target_boundaries(root)

    assert check.ok is False
    assert "dirty_forward_migration_missing_target_db:scripts/migrations/wave24_missing.sql" in (
        check.issues
    )
    assert (
        "dirty_forward_migration_dangerous_sql:scripts/migrations/wave24_bad.sql:delete_from"
        in check.issues
    )
    assert not any("wave24_view_refresh" in issue for issue in check.issues)


def test_migration_target_boundaries_allow_fts_delete_trigger(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    migration = root / "scripts" / "migrations" / "wave24_fts_trigger.sql"
    migration.write_text(
        "-- target_db: autonomath\n"
        "CREATE TRIGGER am_program_narrative_ad\n"
        "AFTER DELETE ON am_program_narrative\n"
        "BEGIN\n"
        "    DELETE FROM am_program_narrative_fts WHERE rowid = OLD.narrative_id;\n"
        "END;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mod,
        "_git_status",
        lambda _repo_root: ["?? scripts/migrations/wave24_fts_trigger.sql"],
    )

    check = mod.check_migration_target_boundaries(root)

    assert check.ok is True


def test_operator_ack_requires_all_confirmations(tmp_path: Path) -> None:
    mod = _load_module()
    ack = tmp_path / "ack.json"
    ack.write_text(json.dumps({"fly_app_confirmed": True}), encoding="utf-8")

    check = mod.check_operator_ack(ack)

    assert check.ok is False
    assert "operator_ack:false_or_missing:pre_deploy_verify_clean" in check.issues


def test_secret_registry_flags_missing_conditional_secret_doc(tmp_path: Path) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    registry = root / "docs" / "_internal" / "SECRETS_REGISTRY.md"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace("CLOUDFLARE_TURNSTILE_SECRET\n", ""),
        encoding="utf-8",
    )

    check = mod.check_secret_registry(root)

    assert check.ok is False
    assert (
        "conditional_secret_name_missing_from_registry:CLOUDFLARE_TURNSTILE_SECRET" in check.issues
    )


def test_secret_registry_flags_missing_jpcite_session_secret(tmp_path: Path) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    registry = root / "docs" / "_internal" / "SECRETS_REGISTRY.md"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace("JPCITE_SESSION_SECRET\n", ""),
        encoding="utf-8",
    )

    check = mod.check_secret_registry(root)

    assert check.ok is False
    assert "secret_name_missing_from_registry:JPCITE_SESSION_SECRET" in check.issues


def test_secret_registry_flags_missing_audit_seal_alternative_doc(tmp_path: Path) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    registry = root / "docs" / "_internal" / "SECRETS_REGISTRY.md"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace("JPINTEL_AUDIT_SEAL_KEYS\n", ""),
        encoding="utf-8",
    )

    check = mod.check_secret_registry(root)

    assert check.ok is False
    assert (
        "alternative_secret_name_missing_from_registry:"
        "AUDIT_SEAL_SECRET/JPINTEL_AUDIT_SEAL_KEYS:JPINTEL_AUDIT_SEAL_KEYS"
    ) in check.issues


def test_secret_registry_does_not_block_on_optional_secret_docs(tmp_path: Path) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)

    check = mod.check_secret_registry(root)

    assert check.ok is True
    assert "JPCITE_SESSION_SECRET" in check.evidence["required_secret_names"]
    assert ["AUDIT_SEAL_SECRET", "JPINTEL_AUDIT_SEAL_KEYS"] in check.evidence[
        "alternative_secret_groups"
    ]
    assert "TG_BOT_TOKEN" in check.evidence["optional_secret_names"]


def test_build_report_can_pass_with_clean_tree_and_full_ack(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    ack = tmp_path / "ack.json"
    ack.write_text(
        json.dumps(
            {
                "fly_app_confirmed": True,
                "fly_secrets_names_confirmed": True,
                "appi_disabled_or_turnstile_secret_confirmed": True,
                "target_db_packet_reviewed": True,
                "rollback_reconciliation_packet_ready": True,
                "live_gbiz_ingest_disabled_or_approved": True,
                "dirty_lanes_reviewed": True,
                "pre_deploy_verify_clean": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_git_status", lambda _repo_root: [])
    monkeypatch.setattr(mod, "_git_head", lambda _repo_root: "head123")

    report = mod.build_report(root, operator_ack=ack)

    assert report["ok"] is True
    assert report["summary"] == {"pass": 5, "fail": 0, "total": 5}


def test_dirty_tree_blocks_without_allow_dirty(monkeypatch: Any, tmp_path: Path) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    monkeypatch.setattr(
        mod.subprocess,
        "check_output",
        lambda *args, **kwargs: " M src/jpintel_mcp/api/main.py\n?? docs/_internal/x.md\n",
    )

    blocked = mod.check_dirty_tree(root, allow_dirty=False)
    fingerprint = dict(blocked.evidence)
    fingerprint["critical_dirty_lanes_reviewed"] = ["runtime_code"]
    allowed = mod.check_dirty_tree(
        root,
        allow_dirty=True,
        ack_data={"dirty_tree_fingerprint": fingerprint},
    )

    assert blocked.ok is False
    assert blocked.evidence["dirty_entries"] == 2
    assert allowed.ok is True


def test_dirty_tree_fails_closed_when_git_status_unavailable(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)

    def raise_status(*args: Any, **kwargs: Any) -> str:
        raise mod.subprocess.CalledProcessError(128, ["git", "status"])

    monkeypatch.setattr(mod.subprocess, "check_output", raise_status)

    check = mod.check_dirty_tree(root, allow_dirty=False)

    assert check.ok is False
    assert check.issues == ["git_status_unavailable"]


def test_allow_dirty_requires_matching_fingerprint(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    monkeypatch.setattr(
        mod,
        "_git_status",
        lambda _repo_root: [" M src/jpintel_mcp/api/main.py"],
    )
    monkeypatch.setattr(mod, "_git_head", lambda _repo_root: "head123")

    check = mod.check_dirty_tree(
        root,
        allow_dirty=True,
        ack_data={
            "dirty_tree_fingerprint": {
                "current_head": "other-head",
                "dirty_entries": 999,
                "status_counts": {"M": 1},
                "lane_counts": {"internal_docs": 1},
                "path_sha256": "wrong",
                "content_sha256": "wrong",
                "content_hash_skipped_large_files": ["data/large.bin"],
                "critical_dirty_lanes_reviewed": ["runtime_code"],
            }
        },
    )

    assert check.ok is False
    assert "dirty_fingerprint_mismatch:dirty_entries" in check.issues
    assert "dirty_fingerprint_mismatch:lane_counts" in check.issues
    assert "dirty_fingerprint_mismatch:path_sha256" in check.issues
    assert "dirty_fingerprint_mismatch:current_head" in check.issues
    assert "dirty_fingerprint_mismatch:content_sha256" in check.issues
    assert "dirty_fingerprint_mismatch:content_hash_skipped_large_files" in check.issues


def test_allow_dirty_requires_complete_fingerprint_fields(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    source = root / "src" / "jpintel_mcp" / "api"
    source.mkdir(parents=True)
    (source / "main.py").write_text("dirty\n", encoding="utf-8")
    status_lines = [" M src/jpintel_mcp/api/main.py"]
    monkeypatch.setattr(mod, "_git_status", lambda _repo_root: status_lines)
    monkeypatch.setattr(mod, "_git_head", lambda _repo_root: "head123")
    fingerprint = {
        **mod._dirty_tree_fingerprint(root, status_lines),
        "critical_dirty_lanes_reviewed": ["runtime_code"],
    }

    for missing_field in mod.REQUIRED_DIRTY_TREE_FINGERPRINT_FIELDS:
        ack_fingerprint = dict(fingerprint)
        del ack_fingerprint[missing_field]
        check = mod.check_dirty_tree(
            root,
            allow_dirty=True,
            ack_data={"dirty_tree_fingerprint": ack_fingerprint},
        )

        assert check.ok is False
        assert f"dirty_fingerprint_missing:{missing_field}" in check.issues


def test_dirty_content_fingerprint_changes_when_file_content_changes(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    path = root / "src" / "jpintel_mcp" / "api"
    path.mkdir(parents=True)
    target = path / "main.py"
    target.write_text("first\n", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "_git_status",
        lambda _repo_root: [" M src/jpintel_mcp/api/main.py"],
    )
    first = mod.check_dirty_tree(root, allow_dirty=False).evidence["content_sha256"]
    target.write_text("second\n", encoding="utf-8")
    second = mod.check_dirty_tree(root, allow_dirty=False).evidence["content_sha256"]

    assert first != second


def test_dirty_fingerprint_is_stable_for_status_line_order(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    (root / "src").mkdir()
    (root / "scripts").mkdir(exist_ok=True)
    (root / "src" / "a.py").write_text("a\n", encoding="utf-8")
    (root / "scripts" / "b.py").write_text("b\n", encoding="utf-8")
    lines_a = [" M scripts/b.py", " M src/a.py"]
    lines_b = list(reversed(lines_a))

    assert (
        mod._dirty_tree_fingerprint(root, lines_a)["content_sha256"]
        == mod._dirty_tree_fingerprint(root, lines_b)["content_sha256"]
    )


def test_dirty_rename_requires_source_and_destination_lane_review(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    (root / "docs" / "_internal" / "main.py").write_text("moved\n", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "_git_status",
        lambda _repo_root: ["R  src/jpintel_mcp/api/main.py -> docs/_internal/main.py"],
    )

    check = mod.check_dirty_tree(
        root,
        allow_dirty=True,
        ack_data={
            "dirty_tree_fingerprint": {
                **mod._dirty_tree_fingerprint(
                    root,
                    ["R  src/jpintel_mcp/api/main.py -> docs/_internal/main.py"],
                ),
                "critical_dirty_lanes_reviewed": ["internal_docs"],
            }
        },
    )

    assert check.ok is False
    assert "dirty_critical_lanes_not_reviewed:runtime_code" in check.issues


def test_dirty_large_file_blocks_allow_dirty(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    root = _minimal_repo(tmp_path)
    big = root / "data" / "large.bin"
    big.parent.mkdir(parents=True)
    with big.open("wb") as handle:
        handle.truncate((64 * 1024 * 1024) + 1)
    monkeypatch.setattr(mod, "_git_status", lambda _repo_root: ["?? data/large.bin"])
    fingerprint = mod._dirty_tree_fingerprint(root, ["?? data/large.bin"])

    check = mod.check_dirty_tree(
        root,
        allow_dirty=True,
        ack_data={
            "dirty_tree_fingerprint": {
                **fingerprint,
                "critical_dirty_lanes_reviewed": [],
            }
        },
    )

    assert check.ok is False
    assert any(issue.startswith("dirty_large_file_content_hash_skipped:") for issue in check.issues)


def test_main_warn_only_exits_zero_on_no_go(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        mod,
        "build_report",
        lambda repo_root, *, allow_dirty, operator_ack: {
            "ok": False,
            "issues": [{"name": "dirty_tree", "issues": ["dirty_tree_present:1"]}],
        },
    )

    exit_code = mod.main(["--repo-root", str(tmp_path), "--warn-only"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is False


def test_main_exits_nonzero_on_no_go(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        mod,
        "build_report",
        lambda repo_root, *, allow_dirty, operator_ack: {"ok": False, "issues": []},
    )

    exit_code = mod.main(["--repo-root", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
