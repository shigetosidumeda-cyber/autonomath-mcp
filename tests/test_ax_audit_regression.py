"""Regression test for ``audit_runner_ax_4pillars.py`` — Wave 41 expansion.

Pins the audit script at 48 / 48 (4 pillars × 12 each = 48). Each pillar
must surface 6 cells (was 5 prior to Wave 41). New cells:

  - Access: ``device_flow_polling_live``
  - Context: ``dataset_metadata_jsonld_live``
  - Tools: ``mcp_resource_polling_live``
  - Orchestration: ``a2a_skill_negotiation_live``

The test runs the audit as a subprocess so the production CLI path is
exercised end-to-end, then asserts on the structured JSON output.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "ops" / "audit_runner_ax_4pillars.py"


def _run_audit(tmp_path: pathlib.Path) -> dict:
    md_out = tmp_path / "audit.md"
    json_out = tmp_path / "audit.json"
    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--out",
            str(md_out),
            "--out-json",
            str(json_out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "AX 4 Pillars total=" in result.stdout, result.stdout
    return json.loads(json_out.read_text(encoding="utf-8"))


def test_ax_audit_total_score_48(tmp_path: pathlib.Path) -> None:
    """Wave 41 — total possible is 48 (was 40)."""
    audit = _run_audit(tmp_path)
    assert audit["max_score"] == 48.0
    assert audit["pillar_max"] == 12.0


def test_ax_audit_pillar_count_4(tmp_path: pathlib.Path) -> None:
    """Still 4 pillars — Access / Context / Tools / Orchestration."""
    audit = _run_audit(tmp_path)
    assert set(audit["pillars"].keys()) == {"Access", "Context", "Tools", "Orchestration"}


def test_ax_audit_cells_six_per_pillar(tmp_path: pathlib.Path) -> None:
    """Wave 41 — each pillar carries 6 cells (was 5)."""
    audit = _run_audit(tmp_path)
    for name, body in audit["pillars"].items():
        assert body["cells"] == 6, f"{name} has {body['cells']} cells; expected 6"


def test_ax_audit_perfect_green(tmp_path: pathlib.Path) -> None:
    """48 / 48 perfect green is the launch gate for Wave 41."""
    audit = _run_audit(tmp_path)
    assert audit["total_score"] == 48.0, (
        f"got {audit['total_score']}; missing items: "
        + ", ".join(
            f"{name}: {body['missing_items']}"
            for name, body in audit["pillars"].items()
            if body["missing_items"]
        )
    )
    assert audit["verdict"] == "green"


def test_ax_audit_wave41_new_cells_present(tmp_path: pathlib.Path) -> None:
    """The 4 Wave 41 cells must surface as Evidence rows (passing)."""
    audit = _run_audit(tmp_path)
    expected_cells = {
        "Access": "device_flow_polling_live",
        "Context": "dataset_metadata_jsonld_live",
        "Tools": "mcp_resource_polling_live",
        "Orchestration": "a2a_skill_negotiation_live",
    }
    for pillar, cell_name in expected_cells.items():
        evidence = audit["pillars"][pillar]["evidence"]
        assert any(
            cell_name in row for row in evidence
        ), f"{pillar} missing Wave 41 cell {cell_name!r}; evidence={evidence}"
