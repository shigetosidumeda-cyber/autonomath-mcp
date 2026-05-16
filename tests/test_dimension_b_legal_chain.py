"""Tests for Dim B legal_chain MCP 5-layer (Wave 43.2.2).

Covers:
  * migration 261 schema integrity (5-layer table + CHECK constraints)
  * each layer evidence_url is REQUIRED + URL prefix CHECK
  * 5 layer fetch returns all layers in canonical order
  * each surfaced row carries an evidence_url (REQUIRED)
  * chain integrity — next_layer_link forms a valid chain when pre-warmed
  * billing unit = 3 on REST + MCP wrapper
  * §72 / §1 / §52 disclaimer envelope present on every 2xx body
  * No LLM-API imports anywhere in the new surface

Migration 261 introduces ``am_legal_chain`` (anchor_program_id → 5 layer
rows, each carrying evidence_url + layer_data_json + next_layer_link).
"""

from __future__ import annotations

import pathlib
import re
import sqlite3

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATION_PATH = REPO_ROOT / "scripts" / "migrations" / "261_legal_chain_5layer.sql"
ROLLBACK_PATH = REPO_ROOT / "scripts" / "migrations" / "261_legal_chain_5layer_rollback.sql"
REST_API_PATH = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "legal_chain_v2.py"
MCP_TOOL_PATH = REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "legal_chain_v2.py"
BOOT_MANIFEST = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


def _apply_migration(conn: sqlite3.Connection, path: pathlib.Path) -> None:
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


@pytest.fixture
def am_conn(tmp_path) -> sqlite3.Connection:
    """Fresh autonomath.db with migration 261 applied."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _apply_migration(conn, MIGRATION_PATH)
    return conn


def test_migration_files_exist():
    """Both forward + rollback files must exist."""
    assert MIGRATION_PATH.exists(), f"missing {MIGRATION_PATH}"
    assert ROLLBACK_PATH.exists(), f"missing {ROLLBACK_PATH}"


def test_migration_target_db_header():
    """First line must be -- target_db: autonomath (entrypoint.sh filter)."""
    first_line = MIGRATION_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.strip() == "-- target_db: autonomath", (
        f"first line must be exactly '-- target_db: autonomath', got {first_line!r}"
    )


def test_migration_idempotent(tmp_path):
    """Migration must be safely re-applied (CREATE IF NOT EXISTS only)."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
    conn.executescript(sql)
    conn.commit()
    conn.close()


def test_boot_manifest_lists_migration():
    """261 file must be in the boot manifest allowlist."""
    text = BOOT_MANIFEST.read_text(encoding="utf-8")
    assert "261_legal_chain_5layer.sql" in text, (
        "261_legal_chain_5layer.sql must be in autonomath_boot_manifest.txt"
    )


def test_table_and_indexes_exist(am_conn):
    """Schema sanity: table + 4 indexes + view + run_log table all present."""
    objects = {
        row["name"]: row["type"]
        for row in am_conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE name LIKE 'am_legal_chain%' "
            "   OR name LIKE 'v_legal_chain%' "
            "   OR name LIKE 'idx_legal_chain%' "
            "   OR name LIKE 'uq_legal_chain%'"
        ).fetchall()
    }
    assert objects.get("am_legal_chain") == "table"
    assert objects.get("v_legal_chain_public") == "view"
    assert objects.get("am_legal_chain_run_log") == "table"
    assert objects.get("idx_legal_chain_anchor") == "index"
    assert objects.get("idx_legal_chain_layer_date") == "index"
    assert objects.get("uq_legal_chain_anchor_layer_url") == "index"


def test_evidence_url_required_check_constraint(am_conn):
    """evidence_url must reject non-http(s) values via CHECK constraint."""
    with pytest.raises(sqlite3.IntegrityError):
        am_conn.execute(
            "INSERT INTO am_legal_chain "
            "(anchor_program_id, layer, layer_name, evidence_url, evidence_host) "
            "VALUES ('UNI-test-a-1', 1, 'budget', 'ftp://bad.example', 'bad.example')"
        )


def test_evidence_url_required_not_null(am_conn):
    """evidence_url must be NOT NULL."""
    with pytest.raises(sqlite3.IntegrityError):
        am_conn.execute(
            "INSERT INTO am_legal_chain "
            "(anchor_program_id, layer, layer_name, evidence_url, evidence_host) "
            "VALUES ('UNI-test-a-2', 1, 'budget', NULL, 'host')"
        )


def test_layer_layer_name_pair_check(am_conn):
    """layer + layer_name must agree (e.g. layer=1 ↔ layer_name='budget')."""
    with pytest.raises(sqlite3.IntegrityError):
        am_conn.execute(
            "INSERT INTO am_legal_chain "
            "(anchor_program_id, layer, layer_name, evidence_url, evidence_host) "
            "VALUES ('UNI-test-a-3', 1, 'law', 'https://example.gov.jp/x', 'example.gov.jp')"
        )


def test_layer_range_1_to_5(am_conn):
    """layer must be in [1, 5]."""
    with pytest.raises(sqlite3.IntegrityError):
        am_conn.execute(
            "INSERT INTO am_legal_chain "
            "(anchor_program_id, layer, layer_name, evidence_url, evidence_host) "
            "VALUES ('UNI-test-a-4', 6, 'case', 'https://example.gov.jp/x', 'example.gov.jp')"
        )


_LAYERS = [
    (1, "budget", "https://www.bb.mof.go.jp/server/2025/budget/15001.html"),
    (2, "law", "https://elaws.e-gov.go.jp/document?lawid=425AC0000000063"),
    (3, "cabinet", "https://www.cas.go.jp/jp/seisaku/kakugi/2025/0411.html"),
    (4, "enforcement", "https://www.meti.go.jp/policy/local/enforce/2025/03.html"),
    (5, "case", "https://www.maff.go.jp/j/keiei/koukai/2025/saiyou_kekka.html"),
]


def _seed_5_layer_chain(
    am_conn: sqlite3.Connection,
    anchor_id: str = "UNI-test-a-5",
) -> None:
    """Seed a complete 5-layer chain for one anchor program."""
    for layer, name, url in _LAYERS:
        host = re.sub(r"^https?://", "", url).split("/", 1)[0]
        next_link = f"layer{layer + 1}" if layer < 5 else None
        am_conn.execute(
            "INSERT INTO am_legal_chain "
            "(anchor_program_id, layer, layer_name, evidence_url, evidence_host, "
            " layer_data_json, layer_summary, effective_date, next_layer_link) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                anchor_id,
                layer,
                name,
                url,
                host,
                '{"layer_no": ' + str(layer) + ', "kind": "' + name + '"}',
                f"{name} layer summary verbatim",
                f"2025-0{layer}-15",
                next_link,
            ),
        )
    am_conn.commit()


def test_5_layer_chain_fanout(am_conn):
    """Each anchor surfaces exactly 5 layers with evidence_url present."""
    _seed_5_layer_chain(am_conn)
    rows = am_conn.execute(
        "SELECT layer, layer_name, evidence_url, next_layer_link "
        "FROM am_legal_chain "
        "WHERE anchor_program_id = ? "
        "ORDER BY layer ASC",
        ("UNI-test-a-5",),
    ).fetchall()
    assert len(rows) == 5
    layer_names = [r["layer_name"] for r in rows]
    assert layer_names == ["budget", "law", "cabinet", "enforcement", "case"]
    for row in rows:
        assert row["evidence_url"], f"layer {row['layer_name']} missing evidence_url"
        assert row["evidence_url"].startswith(("http://", "https://"))
    for row in rows:
        if row["layer"] < 5:
            assert row["next_layer_link"], (
                f"layer {row['layer']} must point forward (chain integrity)"
            )
        else:
            assert row["next_layer_link"] is None, (
                "layer 5 (case) is the sink; next_layer_link must be NULL"
            )


def test_public_view_filters_redistribute_ok(am_conn):
    """v_legal_chain_public must hide rows where redistribute_ok=0."""
    am_conn.execute(
        "INSERT INTO am_legal_chain "
        "(anchor_program_id, layer, layer_name, evidence_url, evidence_host, redistribute_ok) "
        "VALUES ('UNI-test-a-6', 1, 'budget', 'https://example.gov.jp/y', 'example.gov.jp', 0)"
    )
    am_conn.commit()
    public_rows = am_conn.execute(
        "SELECT COUNT(*) AS n FROM v_legal_chain_public WHERE anchor_program_id = ?",
        ("UNI-test-a-6",),
    ).fetchone()
    raw_rows = am_conn.execute(
        "SELECT COUNT(*) AS n FROM am_legal_chain WHERE anchor_program_id = ?",
        ("UNI-test-a-6",),
    ).fetchone()
    assert raw_rows["n"] == 1
    assert public_rows["n"] == 0


def test_rest_module_has_router_and_disclaimer():
    """REST module exposes router with /v1/legal prefix + §72 disclaimer."""
    src = REST_API_PATH.read_text(encoding="utf-8")
    assert 'prefix="/v1/legal"' in src
    assert "_LEGAL_CHAIN_DISCLAIMER" in src
    assert "弁護士法 §72" in src
    assert "行政書士法 §1" in src
    for layer in ("budget", "law", "cabinet", "enforcement", "case"):
        assert f'"{layer}"' in src, f"layer literal {layer!r} missing"


def test_rest_billing_unit_3():
    """REST handler must emit _billing_unit: 3 (heavy chain query)."""
    src = REST_API_PATH.read_text(encoding="utf-8")
    assert '"_billing_unit": 3' in src
    assert "quantity=3" in src


def test_mcp_module_exposes_impl_and_billing_3():
    """MCP module exposes _legal_chain_am_impl and 3-unit billing."""
    src = MCP_TOOL_PATH.read_text(encoding="utf-8")
    assert "_legal_chain_am_impl" in src
    assert '"_billing_unit": 3' in src
    assert "AUTONOMATH_LEGAL_CHAIN_V2_ENABLED" in src


def test_no_llm_api_imports():
    """No anthropic/openai/google.generativeai/claude_agent_sdk anywhere."""
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import claude_agent_sdk",
        "from claude_agent_sdk",
    )
    for path in (REST_API_PATH, MCP_TOOL_PATH):
        src = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            assert pattern not in src, f"LLM API import detected in {path.name}: {pattern!r}"
