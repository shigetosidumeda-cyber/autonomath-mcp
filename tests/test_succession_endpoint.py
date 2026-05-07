"""Contract tests for /v1/succession/* — M&A / 事業承継 制度 matcher.

Pins the response shape so a future refactor cannot silently drop the
disclaimer envelope, the curated tax_levers list, or the law join.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[1]
_JPINTEL_DB = Path(os.environ.get("JPINTEL_DB_PATH", str(_REPO_ROOT / "data" / "jpintel.db")))


# ---------------------------------------------------------------------------
# Pure-Python pin (no live DB required) — covered by the in-process impl
# accessor on the MCP side. Skipped when jpintel.db is missing because
# the matcher reads from `programs` and `laws`.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pin_jpintel_db_for_anon_quota(seeded_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep anon quota writes on the seeded jpintel DB during full-suite runs."""
    from jpintel_mcp.api import anon_limit as _anon_limit
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "db_path", seeded_db)
    monkeypatch.setattr(_anon_limit.settings, "db_path", seeded_db)


def test_match_returns_expected_envelope_for_child_inherit(client: TestClient) -> None:
    """親族内承継 scenario must return the full envelope contract."""
    payload = {
        "scenario": "child_inherit",
        "current_revenue": 300_000_000,
        "employee_count": 20,
        "owner_age": 72,
    }
    r = client.post("/v1/succession/match", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level envelope keys.
    for key in (
        "scenario",
        "scenario_label_ja",
        "cohort_summary",
        "is_chusho_kigyo",
        "early_succession_advised",
        "primary_levers",
        "programs",
        "tax_levers",
        "legal_support",
        "next_steps",
        "provenance",
        "_disclaimer",
    ):
        assert key in body, f"missing envelope key: {key}"

    assert body["scenario"] == "child_inherit"
    assert body["scenario_label_ja"].startswith("親族内承継")
    assert body["cohort_summary"]["owner_age"] == 72
    # 72 歳 → 早期承継 advisory
    assert body["early_succession_advised"] is True
    # 中小企業 — small revenue + 20 employees
    assert body["is_chusho_kigyo"] is True

    # primary_levers must include 事業承継税制 (法人版特例措置)
    levers = body["primary_levers"]
    assert any("事業承継税制" in lv for lv in levers)
    assert any("経営承継円滑化法" in lv for lv in levers)

    # tax_levers (curated, ≥1 row).
    assert isinstance(body["tax_levers"], list)
    assert len(body["tax_levers"]) >= 1
    for lev in body["tax_levers"]:
        assert "name" in lev and lev["name"]
        assert "primary_source_url" in lev and lev["primary_source_url"].startswith("https://")

    # next_steps must surface the early-succession 70+ advisory.
    assert any("70" in s or "事業承継" in s for s in body["next_steps"])

    # disclaimer copy must mention §52 fence + 一般情報提供 only.
    assert "§52" in body["_disclaimer"]
    assert "一般" in body["_disclaimer"]


def test_match_m_and_a_returns_m_and_a_levers(client: TestClient) -> None:
    """第三者承継 scenario must surface M&A-specific levers."""
    payload = {
        "scenario": "m_and_a",
        "current_revenue": 800_000_000,
        "employee_count": 80,
        "owner_age": 65,
    }
    r = client.post("/v1/succession/match", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenario"] == "m_and_a"
    assert body["scenario_label_ja"].startswith("第三者承継")
    assert body["early_succession_advised"] is False  # 65 < 70

    # Primary levers should mention 引継ぎ補助金 and M&A.
    levers_str = " ".join(body["primary_levers"])
    assert "M&A" in levers_str or "引継ぎ" in levers_str

    # tax_levers must include 経営資源集約化 or 登録免許税 軽減
    tax_lever_names = " ".join(lev["name"] for lev in body["tax_levers"])
    assert "経営資源集約化" in tax_lever_names or "登録免許税" in tax_lever_names


def test_match_employee_buy_out_returns_ebo_levers(client: TestClient) -> None:
    """役員・従業員承継 must surface EBO/MBO levers."""
    payload = {
        "scenario": "employee_buy_out",
        "current_revenue": 200_000_000,
        "employee_count": 15,
        "owner_age": 68,
    }
    r = client.post("/v1/succession/match", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenario"] == "employee_buy_out"
    levers_str = " ".join(body["primary_levers"])
    assert "EBO" in levers_str or "従業員" in levers_str or "事業承継・集約" in levers_str


def test_match_invalid_scenario_returns_422(client: TestClient) -> None:
    """Closed-vocab scenario regex rejects unknown values."""
    r = client.post(
        "/v1/succession/match",
        json={
            "scenario": "magical_takeover",
            "current_revenue": 1_000_000,
            "employee_count": 5,
            "owner_age": 50,
        },
    )
    assert r.status_code == 422


def test_match_negative_revenue_returns_422(client: TestClient) -> None:
    """Field bound rejects negative numeric inputs."""
    r = client.post(
        "/v1/succession/match",
        json={
            "scenario": "child_inherit",
            "current_revenue": -1,
            "employee_count": 5,
            "owner_age": 50,
        },
    )
    assert r.status_code == 422


def test_match_owner_age_too_low_returns_422(client: TestClient) -> None:
    """Owner age <18 is rejected (Pydantic ge=18)."""
    r = client.post(
        "/v1/succession/match",
        json={
            "scenario": "child_inherit",
            "current_revenue": 100_000,
            "employee_count": 1,
            "owner_age": 5,
        },
    )
    assert r.status_code == 422


def test_match_large_enterprise_flag_flips_chusho_false(client: TestClient) -> None:
    """売上 ¥50億 以上 + 従業員 300名 以上 → not 中小企業 in our coarse classifier."""
    payload = {
        "scenario": "child_inherit",
        "current_revenue": 100_000_000_000,  # ¥1000億
        "employee_count": 5_000,
        "owner_age": 60,
    }
    r = client.post("/v1/succession/match", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["is_chusho_kigyo"] is False
    # And next_steps must call out the cap-exceedance.
    assert any("中小企業" in s for s in body["next_steps"])


def test_playbook_returns_seven_steps(client: TestClient) -> None:
    """Playbook returns 7 standard 事業承継 steps + cliff dates + sources."""
    r = client.get("/v1/succession/playbook")
    assert r.status_code == 200, r.text
    body = r.json()

    for key in (
        "overview_ja",
        "typical_horizon_years",
        "advisor_chain",
        "steps",
        "cliff_dates",
        "primary_sources",
        "_disclaimer",
    ):
        assert key in body, f"missing playbook key: {key}"

    assert len(body["steps"]) == 7
    # Each step has a step_no in 1..7 and at least 1 deliverable + 1 primary_source.
    seen = set()
    for step in body["steps"]:
        assert 1 <= step["step_no"] <= 7
        seen.add(step["step_no"])
        assert step["label_ja"]
        assert step["advisor_kind"]
        assert step["horizon"]
        assert isinstance(step["deliverables"], list) and step["deliverables"]
        assert isinstance(step["primary_sources"], list) and step["primary_sources"]
    assert seen == {1, 2, 3, 4, 5, 6, 7}

    # Cliff dates must include the 2026-03-31 特例承継計画 提出期限 and the
    # 2027-12-31 特例措置 適用期限.
    cliff_dates = [c["date"] for c in body["cliff_dates"]]
    assert "2026-03-31" in cliff_dates
    assert "2027-12-31" in cliff_dates

    # Advisor chain must mention 税理士 + M&A仲介 + 認定支援機関.
    chain_str = " ".join(body["advisor_chain"])
    assert "税理士" in chain_str or "公認会計士" in chain_str
    assert "M&A" in chain_str
    assert "認定経営革新等支援機関" in chain_str

    # Disclaimer envelope mandatory.
    assert "§52" in body["_disclaimer"]


def test_playbook_paid_key_logs_usage(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
) -> None:
    """Authenticated GET /v1/succession/playbook must record a usage_events row."""
    import sqlite3

    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    conn = sqlite3.connect(seeded_db)
    try:
        before = int(
            conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "succession.playbook"),
            ).fetchone()[0]
        )
    finally:
        conn.close()

    r = client.get(
        "/v1/succession/playbook",
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text

    conn = sqlite3.connect(seeded_db)
    try:
        after = int(
            conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "succession.playbook"),
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert after == before + 1, (
        f"expected exactly 1 new usage_events row for succession.playbook; got {after - before}"
    )


def test_match_paid_key_logs_usage(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
) -> None:
    """Authenticated POST /v1/succession/match must record exactly 1 usage_events row."""
    import sqlite3

    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    conn = sqlite3.connect(seeded_db)
    try:
        before = int(
            conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "succession.match"),
            ).fetchone()[0]
        )
    finally:
        conn.close()

    r = client.post(
        "/v1/succession/match",
        headers={"X-API-Key": paid_key},
        json={
            "scenario": "child_inherit",
            "current_revenue": 50_000_000,
            "employee_count": 10,
            "owner_age": 75,
        },
    )
    assert r.status_code == 200, r.text

    conn = sqlite3.connect(seeded_db)
    try:
        after = int(
            conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "succession.match"),
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert after == before + 1


def test_match_v2_envelope(client: TestClient) -> None:
    """v2 envelope wraps the body and emits a citation pointer."""
    r = client.post(
        "/v1/succession/match",
        headers={"Accept": "application/vnd.jpcite.v2+json"},
        json={
            "scenario": "m_and_a",
            "current_revenue": 1_000_000_000,
            "employee_count": 50,
            "owner_age": 60,
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Envelope-Version") == "v2"
    body = r.json()
    assert body["status"] == "sparse"
    assert body["meta"]["billable_units"] == 1
    assert body["citations"], "v2 succession.match must surface a citation"
    citation = body["citations"][0]
    assert "chusho.meti.go.jp" in citation["source_url"]
    inner = body["results"][0]
    assert inner["scenario"] == "m_and_a"
    assert "_disclaimer" in inner
