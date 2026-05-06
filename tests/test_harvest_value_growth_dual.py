from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "harvest_value_growth_dual.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("harvest_value_growth_dual", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_render_markdown_handles_empty_dual_cli_root(tmp_path: Path) -> None:
    mod = _load_module()
    root = tmp_path / "value_growth_dual"

    text = mod.render_markdown(root)

    assert "Value Growth Dual CLI Main Workstream Status" in text
    assert "| SLOT_A | pending |" in text
    assert "| SLOT_B | pending |" in text
    assert "| SourceProfile >= 150 | 0 | pending |" in text
    assert "| Artifact spec >= 30 | 0 | pending |" in text


def test_render_markdown_counts_outputs_and_agent_ledger(tmp_path: Path) -> None:
    mod = _load_module()
    root = tmp_path / "value_growth_dual"
    coord = root / "_coordination"
    a_dir = root / "A_source_foundation"
    b_dir = root / "B_output_market"
    integrated = root / "_integrated"
    for path in (coord, a_dir, b_dir, a_dir / "parts", b_dir / "parts", integrated):
        path.mkdir(parents=True)

    (coord / "SLOT_A_CLAIM.md").write_text("slot: SLOT_A\n", encoding="utf-8")
    (coord / "SLOT_B_CLAIM.md").write_text("slot: SLOT_B\n", encoding="utf-8")
    (coord / "AGENT_LEDGER.csv").write_text(
        "timestamp_jst,slot,wave,agent_count,topic,output_file,status,notes\n"
        "2026-05-06T12:00:00+09:00,SLOT_A,Wave 0,10,bootstrap,a,done,\n"
        "2026-05-06T12:00:00+09:00,SLOT_B,Wave 0,12,bootstrap,b,done,\n",
        encoding="utf-8",
    )
    (a_dir / "02_A_SOURCE_PROFILE.jsonl").write_text(
        '{"source_id":"a"}\n{"source_id":"b"}\n',
        encoding="utf-8",
    )
    (b_dir / "02_B_ARTIFACT_SPEC_CATALOG.md").write_text(
        "artifact_id: one\nartifact_id: two\n",
        encoding="utf-8",
    )
    (b_dir / "04_B_EVAL_QUERIES.jsonl").write_text(
        '{"query":"one"}\n',
        encoding="utf-8",
    )
    (b_dir / "06_B_FEATURE_TICKET_BACKLOG.md").write_text(
        "ticket_id: VG-1\nticket_id: VG-2\n",
        encoding="utf-8",
    )
    (integrated / "01_TOP_30_IMPLEMENTATION_TICKETS.md").write_text(
        "ticket_id: TOP-1\n",
        encoding="utf-8",
    )
    (a_dir / "parts" / "one.md").write_text("# one\n", encoding="utf-8")
    (b_dir / "parts" / "one.md").write_text("# one\n", encoding="utf-8")
    (b_dir / "parts" / "two.md").write_text("# two\n", encoding="utf-8")

    text = mod.render_markdown(root)

    assert "- ledger_rows: `2`" in text
    assert "- total_agents_recorded: `22`" in text
    assert "- slot_a_part_files: `1`" in text
    assert "- slot_b_part_files: `2`" in text
    assert "| SLOT_A | ready |" in text
    assert "| SLOT_B | ready |" in text
    assert "| SLOT_A source profiles | ready | 2 | 2 |" in text
    assert "| SLOT_B artifact specs | ready | 2 | 2 |" in text
    assert "| SLOT_B eval queries | ready | 1 | 1 |" in text
    assert "| SLOT_B feature tickets | ready | 2 | 2 |" in text
    assert "| Integrated top tickets >= 30 | 1 | pending |" in text


def test_main_writes_report(tmp_path: Path, capsys) -> None:
    mod = _load_module()
    root = tmp_path / "value_growth_dual"
    out = tmp_path / "status.md"

    rc = mod.main(["--root", str(root), "--out", str(out)])

    assert rc == 0
    assert out.exists()
    assert "Value Growth Dual CLI Main Workstream Status" in out.read_text(encoding="utf-8")
    assert "status.md" in capsys.readouterr().out
