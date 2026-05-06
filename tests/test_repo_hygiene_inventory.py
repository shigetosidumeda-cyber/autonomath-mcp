from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "repo_hygiene_inventory.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("repo_hygiene_inventory", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_render_markdown_classifies_common_repo_roots(tmp_path: Path) -> None:
    mod = _load_module()
    for rel in ("src", "tests", "site", "data", "tools", "dist.bak"):
        (tmp_path / rel).mkdir()
    (tmp_path / "autonomath.db").write_bytes(b"db")
    (tmp_path / "pyproject.toml.bak").write_text("backup", encoding="utf-8")

    text = mod.render_markdown(tmp_path)

    assert "Repo Hygiene Inventory" in text
    assert "| source_or_test |" in text
    assert "| generated_or_output |" in text
    assert "| data_mixed |" in text
    assert "| operator_or_research |" in text
    assert "| local_runtime_data |" in text
    assert "| local_noise |" in text
    assert "`autonomath.db`" in text


def test_main_writes_inventory_report(tmp_path: Path, capsys) -> None:
    mod = _load_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    out = tmp_path / "inventory.md"

    rc = mod.main(["--repo", str(repo), "--out", str(out)])

    assert rc == 0
    assert out.exists()
    assert "Repo Hygiene Inventory" in out.read_text(encoding="utf-8")
    assert "inventory.md" in capsys.readouterr().out
