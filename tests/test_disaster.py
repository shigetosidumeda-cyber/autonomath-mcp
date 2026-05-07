"""Tests for the 災害復興 × 特例制度 surface (api/disaster.py + MCP mirrors).

Covers ``/v1/disaster/active_programs`` (GET), ``/v1/disaster/match`` (POST),
``/v1/disaster/catalog`` (GET), plus the three MCP tool wrappers.

Seed strategy: insert four programs that span the keyword fence (能登半島地震
loan / 山形豪雨 subsidy / 静岡台風 subsidy / 鹿児島噴火 subsidy) plus one
unrelated row to verify the fence doesn't over-match.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_disaster_programs(seeded_db: Path) -> Path:
    """Insert representative disaster rows + one decoy."""
    now = datetime.now(UTC).isoformat()
    last_year = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    rows = [
        {
            "unified_id": "UNI-test-disaster-noto-loan",
            "primary_name": "令和6年能登半島地震 なりわい再建支援補助金（テスト）",
            "tier": "S",
            "prefecture": "石川県",
            "authority_level": "都道府県",
            "program_kind": "subsidy",
            "amount_max_man_yen": 15000,
            "official_url": "https://example.go.jp/noto",
            "source_url": "https://example.go.jp/noto",
            "valid_from": last_year,
        },
        {
            "unified_id": "UNI-test-disaster-yamagata-flood",
            "primary_name": "令和6年7月豪雨 山形災害復旧支援事業（テスト）",
            "tier": "A",
            "prefecture": "山形県",
            "authority_level": "都道府県",
            "program_kind": "subsidy",
            "amount_max_man_yen": 500,
            "official_url": "https://example.pref.yamagata.jp/flood",
            "source_url": "https://example.pref.yamagata.jp/flood",
            "valid_from": last_year,
        },
        {
            "unified_id": "UNI-test-disaster-shizuoka-typhoon",
            "primary_name": "令和5年台風7号 静岡県被災事業者支援補助金（テスト）",
            "tier": "B",
            "prefecture": "静岡県",
            "authority_level": "都道府県",
            "program_kind": "support",
            "amount_max_man_yen": 200,
            "official_url": "https://example.pref.shizuoka.jp/typhoon",
            "source_url": "https://example.pref.shizuoka.jp/typhoon",
            "valid_from": last_year,
        },
        {
            "unified_id": "UNI-test-disaster-kagoshima-volcanic",
            "primary_name": "令和7年桜島噴火 被災者支援（テスト）",
            "tier": "B",
            "prefecture": "鹿児島県",
            "authority_level": "都道府県",
            "program_kind": "subsidy",
            "amount_max_man_yen": 100,
            "official_url": "https://example.pref.kagoshima.jp/volcanic",
            "source_url": "https://example.pref.kagoshima.jp/volcanic",
            "valid_from": last_year,
        },
        {
            "unified_id": "UNI-test-disaster-decoy",
            "primary_name": "ふるさと納税ポータル",
            "tier": "B",
            "prefecture": "東京都",
            "authority_level": "国",
            "program_kind": "support",
            "amount_max_man_yen": 0,
            "official_url": "https://example.com/decoy",
            "source_url": "https://example.com/decoy",
            "valid_from": now,
        },
    ]

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    for r in rows:
        conn.execute(
            """INSERT OR IGNORE INTO programs(
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json, updated_at,
                source_url, valid_from
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["unified_id"],
                r["primary_name"],
                None,
                r.get("authority_level"),
                None,
                r.get("prefecture"),
                None,
                r.get("program_kind"),
                r.get("official_url"),
                r.get("amount_max_man_yen"),
                None,
                None,
                None,
                r.get("tier"),
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                json.dumps([], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                None,
                None,
                None,
                None,
                now,
                r.get("source_url"),
                r.get("valid_from"),
            ),
        )
    conn.commit()
    conn.close()
    return seeded_db


# ---------------------------------------------------------------------------
# REST: GET /v1/disaster/active_programs
# ---------------------------------------------------------------------------


def test_active_programs_returns_disaster_rows(client, seeded_disaster_programs):
    r = client.get("/v1/disaster/active_programs", params={"limit": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    names = {row["primary_name"] for row in body["results"]}
    assert any("能登半島地震" in n for n in names)
    assert any("豪雨" in n for n in names)
    assert "ふるさと納税ポータル" not in names


def test_active_programs_filter_disaster_type_earthquake(client, seeded_disaster_programs):
    r = client.get(
        "/v1/disaster/active_programs",
        params={"disaster_type": "earthquake", "limit": 100},
    )
    assert r.status_code == 200
    names = {row["primary_name"] for row in r.json()["results"]}
    assert any("能登半島地震" in n for n in names)
    assert not any("豪雨" in n for n in names)


def test_active_programs_filter_prefecture(client, seeded_disaster_programs):
    r = client.get(
        "/v1/disaster/active_programs",
        params={"prefecture": "山形県", "limit": 100},
    )
    assert r.status_code == 200
    body = r.json()
    names = {row["primary_name"] for row in body["results"]}
    assert any("山形" in n for n in names)
    assert not any("能登" in n for n in names)


def test_active_programs_window_clamp_upper_bound(client):
    r = client.get("/v1/disaster/active_programs", params={"window_months": 999})
    assert r.status_code == 422


def test_active_programs_results_carry_matched_types(client, seeded_disaster_programs):
    r = client.get("/v1/disaster/active_programs", params={"limit": 100})
    body = r.json()
    for row in body["results"]:
        if "能登半島地震" in row["primary_name"]:
            assert "earthquake" in row["matched_disaster_types"]
        if "豪雨" in row["primary_name"]:
            assert "flood" in row["matched_disaster_types"]


# ---------------------------------------------------------------------------
# REST: POST /v1/disaster/match
# ---------------------------------------------------------------------------


def test_match_returns_buckets(client, seeded_disaster_programs):
    r = client.post(
        "/v1/disaster/match",
        json={
            "prefecture": "17",  # 石川県
            "disaster_type": "earthquake",
            "incident_date": "2026-01-01",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prefecture"] == "石川県"
    assert body["prefecture_code"] == "17"
    assert body["disaster_type"] == "earthquake"
    assert body["total"] >= 1
    assert any(b["program_kind"] == "subsidy" for b in body["buckets"])


def test_match_rejects_unknown_prefecture_code(client):
    r = client.post(
        "/v1/disaster/match",
        json={
            "prefecture": "99",
            "disaster_type": "flood",
            "incident_date": "2026-04-01",
        },
    )
    assert r.status_code == 422


def test_match_rejects_unknown_disaster_type(client):
    r = client.post(
        "/v1/disaster/match",
        json={
            "prefecture": "13",
            "disaster_type": "alien-invasion",
            "incident_date": "2026-04-01",
        },
    )
    assert r.status_code == 422


def test_match_rejects_bad_incident_date(client):
    r = client.post(
        "/v1/disaster/match",
        json={
            "prefecture": "13",
            "disaster_type": "flood",
            "incident_date": "not-a-date",
        },
    )
    assert r.status_code == 422


def test_match_yamagata_flood(client, seeded_disaster_programs):
    r = client.post(
        "/v1/disaster/match",
        json={
            "prefecture": "06",
            "disaster_type": "flood",
            "incident_date": "2026-07-15",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prefecture"] == "山形県"
    primary_names = [item["primary_name"] for b in body["buckets"] for item in b["items"]]
    assert any("山形" in n for n in primary_names)


# ---------------------------------------------------------------------------
# REST: GET /v1/disaster/catalog
# ---------------------------------------------------------------------------


def test_catalog_returns_recent_events(client, seeded_disaster_programs):
    r = client.get("/v1/disaster/catalog", params={"years": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    labels = {ev["label"] for ev in body["events"]}
    # Expect at least one Reiwa-tagged event from the seed set.
    assert any("令和" in label for label in labels)
    assert body["total_events"] >= 1


def test_catalog_year_clamp(client):
    r = client.get("/v1/disaster/catalog", params={"years": 999})
    assert r.status_code == 422


def test_catalog_events_carry_inferred_type(client, seeded_disaster_programs):
    r = client.get("/v1/disaster/catalog", params={"years": 5})
    body = r.json()
    for ev in body["events"]:
        assert ev["inferred_type"] in {
            "flood",
            "earthquake",
            "typhoon",
            "snow",
            "fire",
            "tsunami",
            "volcanic",
            "any",
        }


# ---------------------------------------------------------------------------
# MCP tool parity (smoke).
# ---------------------------------------------------------------------------


def test_mcp_list_active_disaster_programs(client, seeded_disaster_programs):
    from jpintel_mcp.mcp.server import list_active_disaster_programs

    res = list_active_disaster_programs(limit=100)
    assert isinstance(res, dict)
    assert res["total"] >= 1
    names = [r["primary_name"] for r in res["results"]]
    assert any("能登半島地震" in n for n in names)


def test_mcp_match_disaster_programs_invalid_prefecture(client):
    from jpintel_mcp.mcp.server import match_disaster_programs

    res = match_disaster_programs(
        prefecture_code="99",
        disaster_type="flood",
        incident_date="2026-04-01",
    )
    assert res.get("error", {}).get("code") == "invalid_enum"
    assert res["total"] == 0


def test_mcp_disaster_catalog_smoke(client, seeded_disaster_programs):
    from jpintel_mcp.mcp.server import disaster_catalog

    res = disaster_catalog(years=5, sample_per_event=3)
    assert "events" in res
    assert res["years"] == 5
    # Catalog parses on Reiwa tokens; seeded names use 令和N年.
    assert res["total_events"] >= 1
