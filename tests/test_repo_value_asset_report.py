from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "repo_value_asset_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("repo_value_asset_report", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_classify_path_finds_value_categories() -> None:
    mod = _load_module()

    assert mod.classify_path("server.json") == "ai_first_hop_distribution"
    assert mod.classify_path("src/jpintel_mcp/api/intel_path.py") == "customer_output_surfaces"
    assert (
        mod.classify_path("scripts/migrations/170_program_decision_layer.sql") == "data_foundation"
    )
    assert mod.classify_path("benchmarks/jcrb_v1/token_savings_report.md") == "trust_quality_proof"
    assert (
        mod.classify_path("tools/offline/INFO_COLLECTOR_LOOP.md") == "operator_research_to_product"
    )
    assert mod.classify_path("docs/index.md") == "public_conversion_copy"
    assert mod.classify_path("docs/_internal/SECRETS_REGISTRY.md") == "internal_sensitive_only"
    assert mod.classify_path("random/file.txt") is None


def test_render_markdown_with_fake_assets(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()

    monkeypatch.setattr(
        mod,
        "collect_assets",
        lambda _repo: [
            mod.ValueAsset("server.json", "modified", "ai_first_hop_distribution"),
            mod.ValueAsset(
                "src/jpintel_mcp/api/intel_path.py", "tracked", "customer_output_surfaces"
            ),
            mod.ValueAsset("benchmarks/jcrb_v1/README.md", "untracked", "trust_quality_proof"),
        ],
    )

    text = mod.render_markdown(tmp_path)

    assert "Repo Value Asset Report" in text
    assert "| ai_first_hop_distribution | 1 | 1 |" in text
    assert "| customer_output_surfaces | 1 | 0 |" in text
    assert "Productization Ideas" in text


def test_main_writes_value_report(monkeypatch, tmp_path: Path, capsys) -> None:
    mod = _load_module()

    monkeypatch.setattr(mod, "collect_assets", lambda _repo: [])
    out = tmp_path / "value.md"

    rc = mod.main(["--repo", str(tmp_path), "--out", str(out)])

    assert rc == 0
    assert out.exists()
    assert "Repo Value Asset Report" in out.read_text(encoding="utf-8")
    assert "value.md" in capsys.readouterr().out
