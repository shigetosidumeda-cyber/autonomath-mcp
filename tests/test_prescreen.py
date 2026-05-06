"""Tests for POST /v1/programs/prescreen and its pure helpers.

Covers the product's core judgment surface — LLM agents submit a caller
profile and expect ranked matches with reasons + caveats. The tests lock in:

  - boundary normalization ("Tokyo" → "東京都" round-trips through profile_echo)
  - target_type match EN/JP alias bridge (memory: project_registry_vocab_drift)
  - amount sufficiency caveat
  - prerequisite caveat + its suppression via declared_certifications
  - MCP parity — the in-process MCP tool calls run_prescreen and returns the
    same model_dump shape
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.prescreen import (
    PrescreenRequest,
    run_prescreen,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# REST endpoint
# ---------------------------------------------------------------------------


def test_prescreen_happy_path_anonymous(client: TestClient) -> None:
    """Empty-ish profile still returns ranked rows + profile_echo."""
    r = client.post("/v1/programs/prescreen", json={"limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "results" in body
    assert "total_considered" in body
    assert "profile_echo" in body
    # tier-X / excluded rows never appear
    ids = [m["unified_id"] for m in body["results"]]
    assert "UNI-test-x-1" not in ids
    # all four seeded tiers S/A/B visible (X excluded), minus excluded
    assert "UNI-test-s-1" in ids
    assert "UNI-test-a-1" in ids
    assert "UNI-test-b-1" in ids


def test_prescreen_prefecture_romaji_normalizes(client: TestClient) -> None:
    """Romaji 'Tokyo' round-trips to canonical '東京都' through profile_echo,
    and UNI-test-s-1 (東京都) scores higher than青森 row on prefecture alone."""
    r = client.post(
        "/v1/programs/prescreen",
        json={"prefecture": "Tokyo", "limit": 10},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_echo"]["prefecture"] == "東京都"
    # the 東京都 row should appear with prefecture 一致 reason
    tokyo = next(m for m in body["results"] if m["unified_id"] == "UNI-test-s-1")
    assert any("東京都" in reason for reason in tokyo["match_reasons"])
    assert tokyo["fit_score"] >= 2


def test_prescreen_prefecture_short_jp_normalizes(client: TestClient) -> None:
    """短い '東京' も canonical に正規化される"""
    r = client.post(
        "/v1/programs/prescreen",
        json={"prefecture": "東京", "limit": 10},
    )
    assert r.status_code == 200, r.text
    assert r.json()["profile_echo"]["prefecture"] == "東京都"


def test_prescreen_sole_proprietor_matches_en_token(client: TestClient) -> None:
    """is_sole_proprietor=True matches target_types=['sole_proprietor', ...]
    — the EN/JP alias bridge (project_registry_vocab_drift)."""
    r = client.post(
        "/v1/programs/prescreen",
        json={"is_sole_proprietor": True, "limit": 10},
    )
    assert r.status_code == 200, r.text
    s_row = next(m for m in r.json()["results"] if m["unified_id"] == "UNI-test-s-1")
    assert any("個人事業主" in reason for reason in s_row["match_reasons"])


def test_prescreen_sole_proprietor_caveat_on_mismatch(client: TestClient) -> None:
    """UNI-test-a-1 has target_types=['認定新規就農者']. A sole_proprietor caller
    does NOT match that token, so we flag the caveat but still show the row."""
    r = client.post(
        "/v1/programs/prescreen",
        json={"is_sole_proprietor": True, "limit": 20},
    )
    assert r.status_code == 200, r.text
    a_row = next(m for m in r.json()["results"] if m["unified_id"] == "UNI-test-a-1")
    assert any("個人事業主" in c and "target_types" in c for c in a_row["caveats"])


def test_prescreen_amount_sufficiency_caveat(client: TestClient) -> None:
    """planned 2000万円 > amount_max 500万円 on UNI-test-a-1 → caveat."""
    r = client.post(
        "/v1/programs/prescreen",
        json={"planned_investment_man_yen": 2000, "limit": 20},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    a_row = next(m for m in body["results"] if m["unified_id"] == "UNI-test-a-1")
    assert any("足りない可能性" in c for c in a_row["caveats"])
    # UNI-test-s-1 amount_max 1000 is still below 2000 → also caveat
    s_row = next(m for m in body["results"] if m["unified_id"] == "UNI-test-s-1")
    assert any("足りない可能性" in c for c in s_row["caveats"])


def test_prescreen_amount_sufficiency_positive(client: TestClient) -> None:
    """Small planned investment → amount OK reason, no caveat."""
    r = client.post(
        "/v1/programs/prescreen",
        json={"planned_investment_man_yen": 100, "limit": 20},
    )
    assert r.status_code == 200, r.text
    s_row = next(m for m in r.json()["results"] if m["unified_id"] == "UNI-test-s-1")
    assert any("amount_max" in reason for reason in s_row["match_reasons"])
    assert not any("足りない可能性" in c for c in s_row["caveats"])


def test_prescreen_rejects_unknown_field(client: TestClient) -> None:
    """extra='forbid' on PrescreenRequest — unknown fields must 422."""
    r = client.post(
        "/v1/programs/prescreen",
        json={"unknown_field": "x", "limit": 10},
    )
    assert r.status_code == 422


def test_prescreen_empty_prefecture_is_ok(client: TestClient) -> None:
    """Missing prefecture returns national + prefecture-unset rows."""
    r = client.post("/v1/programs/prescreen", json={"limit": 5})
    assert r.status_code == 200, r.text


def test_prescreen_paid_final_cap_failure_returns_503_without_usage_event(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "programs.prescreen"),
            ).fetchone()
            return int(n)
        finally:
            conn.close()

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    before_usage = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = client.post(
        "/v1/programs/prescreen",
        headers={"X-API-Key": paid_key},
        json={"limit": 1},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before_usage


# ---------------------------------------------------------------------------
# Prerequisite caveat — seed an extra program whose unified_id matches
# the prereq rule `program_a`. conftest's excl-test-prereq has
# program_a="seinen-shuno-shikin" program_b="認定新規就農者".
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_db_with_prereq_program(seeded_db: Path):
    """Insert one extra program whose unified_id = "seinen-shuno-shikin" so
    the already-seeded excl-test-prereq rule actually fires on a match.
    Teardown deletes it so the session-scoped seeded_db stays clean."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """INSERT OR REPLACE INTO programs(
                unified_id, primary_name, authority_level, prefecture,
                program_kind, amount_max_man_yen, tier, excluded,
                target_types_json, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "seinen-shuno-shikin",
                "青年等就農資金 (テスト注入)",
                "national",
                None,
                "融資",
                3700,
                "A",
                0,
                '["sole_proprietor", "認定新規就農者"]',
                "2026-04-23T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
            "VALUES (?,?,?,?)",
            ("seinen-shuno-shikin", "青年等就農資金 (テスト注入)", "", ""),
        )
        conn.commit()
    finally:
        conn.close()
    yield seeded_db

    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute("DELETE FROM programs WHERE unified_id = ?", ("seinen-shuno-shikin",))
        conn.execute("DELETE FROM programs_fts WHERE unified_id = ?", ("seinen-shuno-shikin",))
        conn.commit()
    finally:
        conn.close()


def test_prescreen_prerequisite_caveat_visible(
    seeded_db_with_prereq_program: Path,
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.post(
        "/v1/programs/prescreen",
        json={"is_sole_proprietor": True, "limit": 50},
    )
    assert r.status_code == 200, r.text
    matches = r.json()["results"]
    prereq_row = next(m for m in matches if m["unified_id"] == "seinen-shuno-shikin")
    assert any("認定新規就農者" in c and "未申告" in c for c in prereq_row["caveats"])


def test_prescreen_prerequisite_suppressed_when_declared(
    seeded_db_with_prereq_program: Path,
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.post(
        "/v1/programs/prescreen",
        json={
            "is_sole_proprietor": True,
            "declared_certifications": ["認定新規就農者"],
            "limit": 50,
        },
    )
    assert r.status_code == 200, r.text
    matches = r.json()["results"]
    prereq_row = next(m for m in matches if m["unified_id"] == "seinen-shuno-shikin")
    assert not any("認定新規就農者" in c and "未申告" in c for c in prereq_row["caveats"])


# ---------------------------------------------------------------------------
# run_prescreen pure function — used by both REST and MCP
# ---------------------------------------------------------------------------


def test_run_prescreen_pure_function(seeded_db: Path) -> None:
    """Calling run_prescreen directly (MCP path) returns the same response
    model as the REST layer."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        profile = PrescreenRequest(
            prefecture="東京都",
            is_sole_proprietor=True,
            planned_investment_man_yen=800,
            limit=5,
        )
        resp = run_prescreen(conn, profile)
    finally:
        conn.close()

    assert resp.limit == 5
    assert resp.total_considered >= 1
    tokyo = next(m for m in resp.results if m.unified_id == "UNI-test-s-1")
    # prefecture一致 + sole_proprietor + amount OK = score 4
    assert tokyo.fit_score >= 4
    assert resp.profile_echo["prefecture"] == "東京都"


# ---------------------------------------------------------------------------
# MCP parity
# ---------------------------------------------------------------------------


def test_mcp_prescreen_tool_same_shape_as_rest(seeded_db: Path) -> None:
    """The MCP `prescreen_programs` tool should return the same dict shape
    `PrescreenResponse.model_dump()` produces — so an agent calling MCP sees
    the identical envelope as the REST caller."""
    from jpintel_mcp.mcp import server as mcp_server

    # The MCP tool is defined at module level via @mcp.tool. FastMCP exposes
    # the underlying callable so we can invoke it in-process without spinning
    # up a stdio transport.
    tool_fn = None
    for name in dir(mcp_server):
        if name == "prescreen_programs":
            tool_fn = getattr(mcp_server, name)
            break
    assert tool_fn is not None, "prescreen_programs tool not registered"

    # If FastMCP wrapped it, it has `.fn` (the real callable). Fall back to
    # the object itself otherwise.
    callable_fn = getattr(tool_fn, "fn", tool_fn)

    resp = callable_fn(
        prefecture="Tokyo",
        is_sole_proprietor=True,
        planned_investment_man_yen=500,
        limit=5,
    )
    # Tool returns a dict (model_dump()) — same envelope as REST.
    assert isinstance(resp, dict)
    assert "results" in resp
    assert "total_considered" in resp
    assert "profile_echo" in resp
    assert resp["profile_echo"]["prefecture"] == "東京都"
