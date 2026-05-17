"""Tests for moat_lane_tools.moat_n1_artifact (Lane N1 — artifact template bank).

Validates the two MCP tools (``get_artifact_template`` + ``list_artifact_templates``)
against an isolated on-disk ``am_artifact_templates`` fixture so the suite does
not depend on the live 12 GB autonomath.db.

Covers:
* DB missing / table missing → empty envelope (not a 500).
* segment + artifact_type round trip pulls structure / placeholders / bindings.
* list filtered by segment vs. ``segment="all"``.
* every response carries the canonical §52/§47条の2/§72/§1/§3 disclaimer.
* citations + provenance shape.
* ``segment="all"`` is rejected on ``get_artifact_template`` with empty
  envelope + rationale.
* ``is_scaffold_only`` + ``requires_professional_review`` flags surface as True.
* unknown artifact_type returns empty envelope (graceful, not raise).
* limit param is honored.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

# Import path that exercises the wrapper module under test.
_MODULE = "jpintel_mcp.mcp.moat_lane_tools.moat_n1_artifact"


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    """Build an isolated autonomath.db with the am_artifact_templates schema +
    a small but representative seed (5 士業 segments × 2 sample rows each).
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE am_artifact_templates (
            template_id INTEGER PRIMARY KEY AUTOINCREMENT,
            segment TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            artifact_name_ja TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT 'v1',
            authority TEXT NOT NULL,
            sensitive_act TEXT NOT NULL,
            is_scaffold_only INTEGER NOT NULL DEFAULT 1,
            requires_professional_review INTEGER NOT NULL DEFAULT 1,
            uses_llm INTEGER NOT NULL DEFAULT 0,
            quality_grade TEXT NOT NULL DEFAULT 'draft',
            structure_jsonb TEXT NOT NULL,
            placeholders_jsonb TEXT NOT NULL,
            mcp_query_bindings_jsonb TEXT NOT NULL,
            license TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (segment, artifact_type, version)
        )
        """
    )
    seeds: list[tuple[str, str, str, str, str]] = [
        ("税理士", "gessji_shiwake", "月次仕訳", "法人税法 §22", "税理士法 §52"),
        ("税理士", "nenmatsu_chosei", "年末調整書", "所得税法 §190", "税理士法 §52"),
        ("会計士", "kansa_chosho", "監査調書", "金商法 §193の2", "公認会計士法 §47条の2"),
        ("会計士", "kansa_iken", "監査意見書", "金商法 §193の2", "公認会計士法 §47条の2"),
        ("行政書士", "hojokin_shinsei", "補助金申請書", "補助金適正化法", "行政書士法 §1"),
        ("行政書士", "kyoninka_shinsei", "許認可申請書", "行政書士法 §1の2", "行政書士法 §1"),
        (
            "司法書士",
            "kaisha_setsuritsu_touki",
            "会社設立登記申請書",
            "商業登記法 §47",
            "司法書士法 §3",
        ),
        ("司法書士", "yakuin_henko_touki", "役員変更登記申請書", "商業登記法 §46", "司法書士法 §3"),
        ("社労士", "shuugyou_kisoku", "就業規則", "労基法 §89", "社労士法 §27"),
        ("社労士", "sanroku_kyoutei", "36協定書", "労基法 §36", "社労士法 §27"),
    ]
    structure_payload = json.dumps(
        {"sections": [{"id": "h", "title": "ヘッダ", "paragraphs": ["{{NAME}}"]}]},
        ensure_ascii=False,
    )
    placeholder_payload = json.dumps(
        [
            {
                "key": "NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "テスト用",
            }
        ],
        ensure_ascii=False,
    )
    binding_payload = json.dumps({}, ensure_ascii=False)
    for segment, artifact_type, name_ja, authority, sensitive_act in seeds:
        conn.execute(
            """
            INSERT INTO am_artifact_templates (
                segment, artifact_type, artifact_name_ja, authority,
                sensitive_act, structure_jsonb, placeholders_jsonb,
                mcp_query_bindings_jsonb
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment,
                artifact_type,
                name_ja,
                authority,
                sensitive_act,
                structure_payload,
                placeholder_payload,
                binding_payload,
            ),
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch, fixture_db: Path) -> Any:
    """Import the moat_n1_artifact module with the fixture DB pinned via env."""
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(fixture_db))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    import jpintel_mcp.mcp.moat_lane_tools.moat_n1_artifact as m

    return importlib.reload(m)


def _impl(tool: Any) -> Any:
    """Return underlying callable for an mcp.tool-wrapped function.

    FastMCP wraps functions; ``.fn`` / ``.func`` exposes the original.
    Fall back to the object itself if neither attribute exists (so the test
    is robust to future FastMCP shape changes).
    """
    for attr in ("fn", "func", "_fn"):
        inner = getattr(tool, attr, None)
        if callable(inner):
            return inner
    return tool


def test_get_artifact_template_returns_known_row(mod: Any) -> None:
    fn = _impl(mod.get_artifact_template)
    out = fn(segment="社労士", artifact_type="shuugyou_kisoku")
    assert out["tool_name"] == "get_artifact_template"
    assert out["total"] == 1
    primary = out["primary_result"]
    assert primary["segment"] == "社労士"
    assert primary["artifact_type"] == "shuugyou_kisoku"
    assert primary["artifact_name_ja"] == "就業規則"
    assert primary["is_scaffold_only"] is True
    assert primary["requires_professional_review"] is True
    assert primary["uses_llm"] is False
    assert primary["structure"]["sections"][0]["id"] == "h"
    assert primary["placeholders"][0]["key"] == "NAME"


def test_get_artifact_template_unknown_returns_empty(mod: Any) -> None:
    fn = _impl(mod.get_artifact_template)
    out = fn(segment="税理士", artifact_type="does_not_exist_xyz")
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"
    assert "no template found" in out["primary_result"]["rationale"]


def test_get_artifact_template_segment_all_is_invalid(mod: Any) -> None:
    fn = _impl(mod.get_artifact_template)
    out = fn(segment="all", artifact_type="gessji_shiwake")
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"
    rationale = out["primary_result"]["rationale"]
    assert "list_artifact_templates" in rationale


def test_list_artifact_templates_segment_all_returns_every_seed(mod: Any) -> None:
    fn = _impl(mod.list_artifact_templates)
    out = fn(segment="all", limit=50)
    # 5 segments × 2 fixture rows = 10
    assert out["total"] == 10
    seen_segments = {r["segment"] for r in out["results"]}
    assert seen_segments == {"税理士", "会計士", "行政書士", "司法書士", "社労士"}


def test_list_artifact_templates_segment_filter(mod: Any) -> None:
    fn = _impl(mod.list_artifact_templates)
    out = fn(segment="税理士", limit=50)
    assert out["total"] == 2
    for row in out["results"]:
        assert row["segment"] == "税理士"
        assert row["is_scaffold_only"] is True
        assert row["requires_professional_review"] is True


def test_list_artifact_templates_limit_param(mod: Any) -> None:
    fn = _impl(mod.list_artifact_templates)
    out = fn(segment="all", limit=3)
    assert out["total"] == 3
    assert out["limit"] == 3


def test_disclaimer_present_on_both_tools(mod: Any) -> None:
    fn_get = _impl(mod.get_artifact_template)
    fn_list = _impl(mod.list_artifact_templates)
    out_get = fn_get(segment="社労士", artifact_type="shuugyou_kisoku")
    out_list = fn_list(segment="all", limit=10)
    for envelope in (out_get, out_list):
        assert "_disclaimer" in envelope
        d = envelope["_disclaimer"]
        # The canonical §-aware disclaimer references all 5 sensitive acts.
        assert "税理士法 §52" in d
        assert "公認会計士法 §47条の2" in d
        assert "弁護士法 §72" in d
        assert "行政書士法 §1" in d
        assert "司法書士法 §3" in d


def test_provenance_and_billing_shape(mod: Any) -> None:
    fn_get = _impl(mod.get_artifact_template)
    out = fn_get(segment="行政書士", artifact_type="hojokin_shinsei")
    assert out["_billing_unit"] == 1
    prov = out["provenance"]
    assert prov["lane_id"] == "N1"
    assert prov["wrap_kind"] == "moat_lane_n1_artifact_db"
    assert "observed_at" in prov


def test_citations_include_authority_and_sensitive_act(mod: Any) -> None:
    fn = _impl(mod.get_artifact_template)
    out = fn(segment="司法書士", artifact_type="kaisha_setsuritsu_touki")
    kinds = {c["kind"] for c in out["citations"]}
    assert "authority" in kinds
    assert "sensitive_act" in kinds


def test_db_missing_returns_empty_envelope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If autonomath.db does not exist the wrapper must NOT raise — it should
    return a structured empty envelope with the disclaimer intact.
    """
    missing = tmp_path / "definitely_not_here.db"
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(missing))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(missing))
    import jpintel_mcp.mcp.moat_lane_tools.moat_n1_artifact as m

    m = importlib.reload(m)
    fn = _impl(m.get_artifact_template)
    out = fn(segment="税理士", artifact_type="gessji_shiwake")
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"
    assert "autonomath.db unreachable" in out["primary_result"]["rationale"]
    # disclaimer must still be present even on error.
    assert "_disclaimer" in out


def test_segment_whitelist_consistency() -> None:
    """The 5-segment whitelist constant must match the regex pattern + the
    set of segments actually present in the 50-row YAML catalog under
    ``data/artifact_templates/``.
    """
    import jpintel_mcp.mcp.moat_lane_tools.moat_n1_artifact as m

    expected = {"税理士", "会計士", "行政書士", "司法書士", "社労士"}
    assert set(m._SEGMENTS_JA) == expected
    # Pattern must accept every segment + "all".
    import re

    rx = re.compile(m._SEGMENT_PATTERN)
    for s in expected | {"all"}:
        assert rx.match(s), f"pattern rejected legal segment: {s}"
    # And must reject bogus segments.
    for bad in ("弁護士", "all_segments", ""):
        assert not rx.match(bad), f"pattern accepted illegal segment: {bad}"


def test_yaml_catalog_has_50_files_across_5_segments() -> None:
    """Catalog SOT: data/artifact_templates/{segment}/{type}.yaml has 50 files
    spread evenly across 5 segments.
    """
    root = Path(__file__).resolve().parents[1] / "data" / "artifact_templates"
    if not root.exists():
        pytest.skip("artifact_templates dir not present in this checkout")
    files = sorted(root.glob("*/*.yaml"))
    assert len(files) == 50, f"expected 50 catalog files, found {len(files)}"
    segments = {f.parent.name for f in files}
    assert segments == {"zeirishi", "kaikeishi", "gyousei", "shihou", "sharoushi"}
    # 10 per segment.
    per_segment = {seg: sum(1 for f in files if f.parent.name == seg) for seg in segments}
    for seg, count in per_segment.items():
        assert count == 10, f"{seg} has {count} files, expected 10"
