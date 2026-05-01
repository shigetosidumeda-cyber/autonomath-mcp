"""Tests for ``scripts/etl/generate_monthly_amendment_digest.py``.

Builds a self-contained in-memory ``autonomath.db`` substitute populated with
5 fixture diffs across mixed tiers / fields, runs the digest pipeline, and
asserts the rendered markdown + HTML carry the expected lead, ranking, and
operator footer (Bookyou T8010001213708 / info@bookyou.net).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import generate_monthly_amendment_digest as digest  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture DB
# ---------------------------------------------------------------------------


def _build_db() -> sqlite3.Connection:
    """Return an in-memory connection populated with schema + 5 diffs."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            record_kind TEXT NOT NULL,
            confidence REAL,
            source_url TEXT,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE am_amendment_diff (
            diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            prev_value TEXT,
            new_value TEXT,
            prev_hash TEXT,
            new_hash TEXT,
            detected_at TEXT NOT NULL,
            source_url TEXT
        );
        """
    )
    entities = [
        (
            "program:test:000001:s_amount",
            "令和8年度 創業助成金",
            "program",
            0.95,
            "https://example.go.jp/sogyo",
            json.dumps(
                {
                    "authority_name": "東京都中小企業振興公社",
                    "prefecture": "東京都",
                    "program_kind": "subsidy",
                    "tier": "S",
                },
                ensure_ascii=False,
            ),
        ),
        (
            "program:test:000002:a_rate",
            "ものづくり補助金 18次",
            "program",
            0.90,
            "https://example.go.jp/monodzukuri",
            json.dumps(
                {
                    "authority_name": "中小企業庁",
                    "prefecture": None,
                    "program_kind": "subsidy",
                },
                ensure_ascii=False,
            ),
        ),
        (
            "program:test:000003:b_url",
            "県内事業者向け省エネ機器導入支援",
            "program",
            0.82,
            "https://example.pref.example/eco",
            json.dumps(
                {
                    "authority_name": "○○県産業振興課",
                    "prefecture": "○○県",
                    "program_kind": "subsidy",
                },
                ensure_ascii=False,
            ),
        ),
        (
            "program:test:000004:c_target",
            "市町村レベル小規模事業者持続化補助金 (例示)",
            "program",
            0.70,
            "https://example.city.example/jizoku",
            json.dumps(
                {
                    "authority_name": "△△市商工課",
                    "prefecture": "△△県",
                    "program_kind": "subsidy",
                },
                ensure_ascii=False,
            ),
        ),
        (
            "program:test:000005:s_target",
            "省エネ設備投資促進事業",
            "program",
            0.94,
            "https://example.meti.go.jp/shouene",
            json.dumps(
                {
                    "authority_name": "経済産業省",
                    "program_kind": "subsidy",
                    "tier": "S",
                },
                ensure_ascii=False,
            ),
        ),
    ]
    conn.executemany(
        "INSERT INTO am_entities (canonical_id, primary_name, record_kind, "
        "confidence, source_url, raw_json) VALUES (?, ?, ?, ?, ?, ?)",
        entities,
    )

    diffs = [
        # 1. tier S program with amount uplift inside target month
        (
            "program:test:000001:s_amount",
            "amount_max_yen",
            "3000000",
            "5000000",
            "2026-04-15T03:00:00+00:00",
            "https://example.go.jp/sogyo",
        ),
        # 2. tier A program with subsidy_rate change inside month
        (
            "program:test:000002:a_rate",
            "subsidy_rate_max",
            "0.5",
            "0.667",
            "2026-04-20T03:00:00+00:00",
            "https://example.go.jp/monodzukuri",
        ),
        # 3. tier B program with source_url change (low importance)
        (
            "program:test:000003:b_url",
            "source_url",
            "https://example.pref.example/old",
            "https://example.pref.example/eco",
            "2026-04-22T03:00:00+00:00",
            "https://example.pref.example/eco",
        ),
        # 4. tier C program with target_set_json shift (対象拡大)
        (
            "program:test:000004:c_target",
            "target_set_json",
            "[]",
            '["小規模事業者","個人事業主"]',
            "2026-04-25T03:00:00+00:00",
            "https://example.city.example/jizoku",
        ),
        # 5. tier S program with projection_regression (multi-field) — should
        #    rank near top alongside #1 because of S tier weight.
        (
            "program:test:000005:s_target",
            "projection_regression_candidate",
            None,
            json.dumps(
                {
                    "amount_max_yen": {"prev": 1000000, "new": 2000000},
                    "subsidy_rate_max": {"prev": 0.333, "new": 0.5},
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            "2026-04-28T03:00:00+00:00",
            "https://example.meti.go.jp/shouene",
        ),
        # Out-of-window diff (March): should NOT appear in April digest.
        (
            "program:test:000001:s_amount",
            "amount_max_yen",
            "2500000",
            "3000000",
            "2026-03-15T03:00:00+00:00",
            "https://example.go.jp/sogyo",
        ),
    ]
    conn.executemany(
        "INSERT INTO am_amendment_diff (entity_id, field_name, prev_value, "
        "new_value, detected_at, source_url) VALUES (?, ?, ?, ?, ?, ?)",
        diffs,
    )
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_month_explicit() -> None:
    label, start, end = digest._parse_month("2026-04")
    assert label == "2026-04"
    assert start == date(2026, 4, 1)
    assert end == date(2026, 5, 1)


def test_parse_month_invalid_raises() -> None:
    with pytest.raises(SystemExit):
        digest._parse_month("not-a-month")


def test_score_diff_amount_field_gets_boost() -> None:
    row = digest.DiffRow(
        diff_id=1,
        entity_id="x",
        field_name="amount_max_yen",
        prev_value="100",
        new_value="200",
        detected_at="2026-04-15T00:00:00+00:00",
        source_url=None,
    )
    score = digest._score_diff(row)
    # amount_max_yen → +25 boost; "amount" keyword in field_name → +30
    assert score >= 25


def test_tier_from_confidence_buckets() -> None:
    assert digest._tier_from_confidence(None) == "C"
    assert digest._tier_from_confidence(0.99) == "S"
    assert digest._tier_from_confidence(0.93) == "S"
    assert digest._tier_from_confidence(0.92) == "A"
    assert digest._tier_from_confidence(0.85) == "B"
    assert digest._tier_from_confidence(0.50) == "C"


def test_build_digest_renders_top_5_with_full_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end fixture: 5 in-window diffs render with operator footer."""
    fake_db = _build_db()

    def _fake_open(_path: Path) -> sqlite3.Connection:
        return fake_db

    monkeypatch.setattr(digest, "_open_db_readonly", _fake_open)

    result = digest.build_digest(
        db_path=tmp_path / "ignored.db",
        month_arg="2026-04",
        limit=5,
    )

    # 5 in-window diffs across 5 distinct entities; March diff excluded.
    assert result.total_diff_count == 5
    assert result.total_entity_count == 5
    assert result.selected_count == 5
    assert result.month == "2026-04"

    md = result.markdown_text
    htm = result.html_text

    # Lead line + total counts
    assert "日本の制度 改正 digest (2026 年 4 月)" in md
    assert "5 制度" in md
    assert "5 件の差分" in md

    # All 5 program names surface
    for name in (
        "令和8年度 創業助成金",
        "ものづくり補助金 18次",
        "県内事業者向け省エネ機器導入支援",
        "市町村レベル小規模事業者持続化補助金 (例示)",
        "省エネ設備投資促進事業",
    ):
        assert name in md, f"markdown missing {name}"
        assert name in htm, f"html missing {name}"

    # Ranking: tier S items must lead. Index of S programs < index of B/C ones.
    idx_s1 = md.index("令和8年度 創業助成金")
    idx_s2 = md.index("省エネ設備投資促進事業")
    idx_b = md.index("県内事業者向け省エネ機器導入支援")
    idx_c = md.index("市町村レベル小規模事業者持続化補助金")
    assert idx_s1 < idx_b
    assert idx_s2 < idx_b
    assert idx_s1 < idx_c
    assert idx_s2 < idx_c

    # Tier badge surfaced
    assert "[tier S]" in md
    assert "[tier S]" in htm

    # Amount formatting: prev 3,000,000 → new 5,000,000 (sogyo subsidy)
    assert "3,000,000 円" in md
    assert "5,000,000 円" in md

    # Subsidy rate formatting (50.0% → 66.7%)
    assert "50.0%" in md
    assert "66.7%" in md

    # CTA: api.jpcite.com search URLs
    assert "api.jpcite.com/v1/programs/search?q=" in md
    assert "api.jpcite.com/v1/programs/search?q=" in htm

    # Operator + unsubscribe + frequency footer
    assert "Bookyou株式会社" in md
    assert "T8010001213708" in md
    assert "info@bookyou.net" in md
    assert "unsubscribe" in md
    assert "毎月 5 日 09:00 JST" in md
    assert "Bookyou株式会社" in htm
    assert "T8010001213708" in htm
    assert "info@bookyou.net" in htm
    assert "unsubscribe" in htm

    # No interpretation / advisory phrasing — fact summary only.
    assert "おすすめ" not in md
    assert "推奨" not in md
    assert "解釈・助言は含みません" in md


def test_write_outputs_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_db = _build_db()
    monkeypatch.setattr(digest, "_open_db_readonly", lambda _p: fake_db)
    result = digest.build_digest(
        db_path=tmp_path / "ignored.db",
        month_arg="2026-04",
        limit=3,
    )
    digest.write_outputs(result, tmp_path / "out")
    md_path = tmp_path / "out" / "2026-04" / "digest.md"
    html_path = tmp_path / "out" / "2026-04" / "digest.html"
    assert md_path.exists()
    assert html_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("# 日本の制度 改正 digest")
    assert html_path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_empty_month_renders_clean_lead(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A month with zero diffs still renders a complete envelope."""
    fake_db = _build_db()
    monkeypatch.setattr(digest, "_open_db_readonly", lambda _p: fake_db)
    result = digest.build_digest(
        db_path=tmp_path / "ignored.db",
        month_arg="2026-05",
        limit=10,
    )
    assert result.total_diff_count == 0
    assert result.selected_count == 0
    assert "対象期間内の検出差分はありませんでした" in result.markdown_text
    assert "T8010001213708" in result.markdown_text
