"""Tests for /v1/eligibility/* and the matching MCP wrappers.

Walks the dynamic eligibility check end-to-end: seeded jpintel.db
(programs + exclusion_rules) + a tiny autonomath.db slice with
am_enforcement_detail rows. Confirms the join surfaces the right
verdict for each (houjin, program) combination without hitting an LLM.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_enforcement_for_eligibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a tiny autonomath.db with am_enforcement_detail rows.

    Three houjin shapes:
      * 1111111111111 → blocking history (subsidy_exclude within 5 years)
      * 2222222222222 → warning-only (business_improvement)
      * 3333333333333 → clean (no enforcement rows)
    """

    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE am_enforcement_detail (
            enforcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            houjin_bangou TEXT,
            target_name TEXT,
            enforcement_kind TEXT,
            issuing_authority TEXT,
            issuance_date TEXT NOT NULL,
            exclusion_start TEXT,
            exclusion_end TEXT,
            reason_summary TEXT,
            related_law_ref TEXT,
            amount_yen INTEGER,
            source_url TEXT,
            source_fetched_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    rows = [
        (
            "houjin:1111111111111",
            "1111111111111",
            "ブロック対象株式会社",
            "subsidy_exclude",
            "農林水産省",
            "2024-04-01",
            "2024-04-15",
            "2027-04-15",
            "対象外設備に補助金を充当した。",
            "補助金等適正化法",
            8_000_000,
            "https://example.maff.go.jp/case/1111.pdf",
            "2026-04-30T00:00:00Z",
        ),
        (
            "houjin:2222222222222",
            "2222222222222",
            "警告対象合同会社",
            "business_improvement",
            "国土交通省",
            "2025-02-15",
            None,
            None,
            "業務改善命令の発出。",
            "建設業法",
            None,
            "https://example.mlit.go.jp/case/2222.pdf",
            "2026-04-29T00:00:00Z",
        ),
        # Out-of-window blocking row (2010 — should be filtered out by 5-year window)
        (
            "houjin:3333333333333",
            "3333333333333",
            "古いケース株式会社",
            "subsidy_exclude",
            "経済産業省",
            "2010-06-30",
            "2010-07-01",
            "2015-07-01",
            "古い処分事例。",
            "補助金等適正化法",
            500_000,
            "https://example.meti.go.jp/old.pdf",
            "2026-04-28T00:00:00Z",
        ),
    ]
    conn.executemany(
        """INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen, source_url,
            source_fetched_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    return db_path


# ---------------------------------------------------------------------------
# REST: /v1/eligibility/dynamic_check
# ---------------------------------------------------------------------------


def test_dynamic_check_blocked_path(client, seeded_enforcement_for_eligibility):
    """A houjin with a blocking enforcement record gets verdict=blocked or
    borderline for every program in the seed (since seeded rules cover the
    test programs)."""

    r = client.post(
        "/v1/eligibility/dynamic_check",
        json={
            "houjin_bangou": "1111111111111",
            "exclude_history_years": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["houjin_bangou"] == "1111111111111"
    assert body["exclude_history_years"] == 5
    # The blocking hit lands in enforcement_hits with severity=blocking.
    hits = body["enforcement_hits"]
    assert len(hits) == 1
    assert hits[0]["enforcement_kind"] == "subsidy_exclude"
    assert hits[0]["severity_bucket"] == "blocking"
    # No program is "eligible" for a houjin with blocking history within
    # the look-back window — every candidate is at least borderline.
    assert body["eligible_programs"] == []
    assert body["checked_program_count"] >= 1
    assert body["checked_rule_count"] >= 1
    assert "_disclaimer" in body


def test_dynamic_check_warning_path(client, seeded_enforcement_for_eligibility):
    """Warning-only enforcement (e.g. business_improvement) does not block
    programs unconditionally — the test seed has no critical-severity rule
    on the warning houjin, so all candidates land in `eligible_programs`."""

    r = client.post(
        "/v1/eligibility/dynamic_check",
        json={
            "houjin_bangou": "2222222222222",
            "exclude_history_years": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    hits = body["enforcement_hits"]
    assert len(hits) == 1
    assert hits[0]["severity_bucket"] == "warning"
    # Warning-only path leaves blocked empty.
    assert body["blocked_programs"] == []
    # Eligible programs > 0 because no rule matches the warning kind.
    assert len(body["eligible_programs"]) >= 1


def test_dynamic_check_history_window_filters_old_rows(
    client, seeded_enforcement_for_eligibility
):
    """A 2010 enforcement row falls outside the default 5-year window."""

    r = client.post(
        "/v1/eligibility/dynamic_check",
        json={
            "houjin_bangou": "3333333333333",
            "exclude_history_years": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Window cuts the 2010 row out → 0 hits → all candidates eligible.
    assert body["enforcement_hits"] == []
    assert body["blocked_programs"] == []
    assert body["borderline_programs"] == []
    assert len(body["eligible_programs"]) >= 1


def test_dynamic_check_history_window_can_be_widened(
    client, seeded_enforcement_for_eligibility
):
    """Widening the look-back window pulls the 2010 row back in."""

    r = client.post(
        "/v1/eligibility/dynamic_check",
        json={
            "houjin_bangou": "3333333333333",
            "exclude_history_years": 20,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["enforcement_hits"]) == 1
    assert body["enforcement_hits"][0]["enforcement_kind"] == "subsidy_exclude"


def test_dynamic_check_invalid_houjin(client, seeded_enforcement_for_eligibility):
    r = client.post(
        "/v1/eligibility/dynamic_check",
        json={"houjin_bangou": "not-a-bangou"},
    )
    # Invalid string is rejected at FastAPI validation time (min length 13).
    assert r.status_code == 422


def test_dynamic_check_unknown_houjin_returns_eligible(
    client, seeded_enforcement_for_eligibility
):
    """A houjin with no enforcement history at all → every candidate is
    eligible (deterministic clean-room verdict)."""

    r = client.post(
        "/v1/eligibility/dynamic_check",
        json={"houjin_bangou": "9999999999999"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enforcement_hits"] == []
    assert len(body["eligible_programs"]) >= 1
    assert body["blocked_programs"] == []


def test_dynamic_check_program_id_hint_narrows_candidates(
    client, seeded_enforcement_for_eligibility
):
    r = client.post(
        "/v1/eligibility/dynamic_check",
        json={
            "houjin_bangou": "9999999999999",
            "program_id_hint": ["UNI-test-s-1"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["checked_program_count"] == 1


# ---------------------------------------------------------------------------
# REST: GET /v1/eligibility/programs/{program_id}/eligibility_for/{houjin_bangou}
# ---------------------------------------------------------------------------


def test_single_program_eligibility_blocked(
    client, seeded_enforcement_for_eligibility
):
    r = client.get(
        "/v1/eligibility/programs/UNI-test-s-1/eligibility_for/1111111111111"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["program_id"] == "UNI-test-s-1"
    assert body["houjin_bangou"] == "1111111111111"
    # blocked or borderline — both are valid given the rule corpus, but it
    # MUST NOT come back eligible (we have a blocking enforcement hit).
    assert body["verdict"] in {"blocked", "borderline"}
    assert len(body["enforcement_hits"]) == 1


def test_single_program_eligibility_clean_houjin(
    client, seeded_enforcement_for_eligibility
):
    r = client.get(
        "/v1/eligibility/programs/UNI-test-s-1/eligibility_for/9999999999999"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "eligible"
    assert body["enforcement_hits"] == []


def test_single_program_eligibility_unknown_program(
    client, seeded_enforcement_for_eligibility
):
    r = client.get(
        "/v1/eligibility/programs/UNI-does-not-exist/eligibility_for/1111111111111"
    )
    assert r.status_code == 404


def test_single_program_eligibility_invalid_bangou(
    client, seeded_enforcement_for_eligibility
):
    r = client.get(
        "/v1/eligibility/programs/UNI-test-s-1/eligibility_for/12345"
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# MCP wrapper smoke (impl helpers, not the @mcp.tool entry, so we don't need
# the full MCP transport spun up).
# ---------------------------------------------------------------------------


def test_mcp_dynamic_eligibility_check_impl(
    client, seeded_enforcement_for_eligibility
):
    from jpintel_mcp.mcp.autonomath_tools.eligibility_tools import (
        _dynamic_check_impl,
    )

    out = _dynamic_check_impl(
        houjin_bangou="1111111111111",
        industry_jsic=None,
        exclude_history_years=5,
        program_id_hint=None,
    )
    assert "error" not in out
    assert out["houjin_bangou"] == "1111111111111"
    assert len(out["enforcement_hits"]) == 1
    assert out["enforcement_hits"][0]["severity_bucket"] == "blocking"
    assert out["_disclaimer"]


def test_mcp_program_eligibility_for_houjin_impl(
    client, seeded_enforcement_for_eligibility
):
    from jpintel_mcp.mcp.autonomath_tools.eligibility_tools import (
        _single_program_impl,
    )

    out = _single_program_impl(
        program_id="UNI-test-s-1",
        houjin_bangou="9999999999999",
        exclude_history_years=5,
    )
    assert "error" not in out
    assert out["verdict"] == "eligible"
    assert out["enforcement_hits"] == []


def test_mcp_invalid_houjin_returns_error_envelope():
    from jpintel_mcp.mcp.autonomath_tools.eligibility_tools import (
        _dynamic_check_impl,
    )

    out = _dynamic_check_impl(
        houjin_bangou="abc",
        industry_jsic=None,
        exclude_history_years=5,
        program_id_hint=None,
    )
    assert "error" in out
    assert out["error"]["code"] == "out_of_range"
