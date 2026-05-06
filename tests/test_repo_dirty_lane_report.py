from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "repo_dirty_lane_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("repo_dirty_lane_report", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_classify_path_routes_common_review_lanes() -> None:
    mod = _load_module()

    assert mod.classify_path("src/jpintel_mcp/api/main.py") == "runtime_code"
    assert mod.classify_path("src/jpintel_mcp/api/billing.py") == "billing_auth_security"
    assert mod.classify_path("scripts/migrations/170_program_decision_layer.sql") == "migrations"
    assert mod.classify_path("scripts/cron/precompute_actionable_answers.py") == "cron_etl_ops"
    assert mod.classify_path("tests/test_intel_path.py") == "tests"
    assert mod.classify_path(".github/workflows/deploy.yml") == "workflows"
    assert mod.classify_path("site/index.html") == "generated_public_site"
    assert mod.classify_path("docs/openapi/agent.json") == "openapi_distribution"
    assert mod.classify_path("sdk/python/README.md") == "sdk_distribution"
    assert mod.classify_path("docs/_internal/release_readiness.md") == "internal_docs"
    assert mod.classify_path("tools/offline/INFO_COLLECTOR_LOOP.md") == "operator_offline"
    assert mod.classify_path("data/source_freshness_report.json") == "data_or_local_seed"
    assert mod.classify_path("DIRECTORY.md") == "root_release_files"


def test_parse_status_lines_handles_renames_and_statuses() -> None:
    mod = _load_module()

    entries = mod.parse_status_lines(
        [
            " M src/jpintel_mcp/api/main.py",
            "?? scripts/migrations/170_program_decision_layer.sql",
            "D  sdk/typescript/autonomath-sdk-0.2.0.tgz",
            "R  old.md -> docs/getting-started.md",
        ]
    )

    assert [entry.status for entry in entries] == [" M", "??", "D ", "R "]
    assert [entry.path for entry in entries][-1] == "docs/getting-started.md"
    assert entries[0].lane == "runtime_code"
    assert entries[1].lane == "migrations"
    assert entries[2].lane == "sdk_distribution"
    assert entries[3].lane == "public_docs"


def test_render_markdown_with_fake_collector(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()

    monkeypatch.setattr(
        mod,
        "collect_entries",
        lambda _repo: mod.parse_status_lines(
            [
                " M src/jpintel_mcp/api/main.py",
                "?? docs/_internal/repo_notes.md",
                "?? site/index.html",
            ]
        ),
    )

    text = mod.render_markdown(tmp_path)

    assert "Repo Dirty Lane Report" in text
    assert "| runtime_code | 1 | 1 | 0 | 0 | 0 |" in text
    assert "| internal_docs | 1 | 0 | 1 | 0 | 0 |" in text
    assert "| generated_public_site | 1 | 0 | 1 | 0 | 0 |" in text
    assert "Review Order" in text
