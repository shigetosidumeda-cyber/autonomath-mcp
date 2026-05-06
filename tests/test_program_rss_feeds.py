"""Tests for ``scripts/etl/generate_program_rss_feeds.py``.

Covered cases (5):

1. Tier S RSS item count = min(num_tier_s_in_db, 100).
2. Amendment RSS items are reverse-chronological (newest first).
3. Prefecture URL pattern is ``/rss/prefecture/{ascii_slug}.xml`` AND the
   feed only references that prefecture's programs.
4. Idempotency: running twice with the same DB + ``--lastmod`` produces
   byte-identical output.
5. Brand + copyright stay public-facing ``jpcite`` (and never the deprecated
   ``AutonoMath`` / ``jpintel`` user-facing branding — internal package paths
   still say ``jpintel_mcp`` and that's fine).

Tests use a tmp sqlite fixture so they do not depend on a live data/jpintel.db
or autonomath.db at repo root. The module under test connects via a URI with
``mode=ro`` — pytest's tmp_path produces normal files which we open RO too.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts" / "etl"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# --- minimal schema ---------------------------------------------------------

_PROGRAMS_SCHEMA = """
CREATE TABLE programs (
    unified_id TEXT PRIMARY KEY,
    primary_name TEXT NOT NULL,
    aliases_json TEXT,
    authority_level TEXT,
    authority_name TEXT,
    prefecture TEXT,
    municipality TEXT,
    program_kind TEXT,
    official_url TEXT,
    amount_max_man_yen REAL,
    amount_min_man_yen REAL,
    subsidy_rate REAL,
    trust_level TEXT,
    tier TEXT,
    coverage_score REAL,
    gap_to_tier_s_json TEXT,
    a_to_j_coverage_json TEXT,
    excluded INTEGER DEFAULT 0,
    exclusion_reason TEXT,
    crop_categories_json TEXT,
    equipment_category TEXT,
    target_types_json TEXT,
    funding_purpose_json TEXT,
    amount_band TEXT,
    application_window_json TEXT,
    enriched_json TEXT,
    source_mentions_json TEXT,
    updated_at TEXT NOT NULL,
    source_url TEXT,
    source_fetched_at TEXT,
    source_checksum TEXT,
    source_url_corrected_at TEXT,
    source_last_check_status INTEGER,
    source_fail_count INTEGER DEFAULT 0,
    merged_from TEXT,
    valid_from TEXT,
    valid_until TEXT,
    source_url_status TEXT DEFAULT 'unknown',
    source_url_last_checked TEXT,
    subsidy_rate_text TEXT
);
"""

_AMENDMENT_SCHEMA = """
CREATE TABLE am_amendment_diff (
    diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    prev_value TEXT,
    new_value TEXT,
    prev_hash TEXT,
    new_hash TEXT,
    detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_url TEXT
);
"""


@pytest.fixture()
def jpintel_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "jpintel.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_PROGRAMS_SCHEMA)
        # Insert: 5 Tier S (one aggregator-domain row), 2 Tier A, 1 Tier B, 1 excluded.
        rows = [
            (
                "UNI-S-001",
                "東京都ものづくり補助金",
                "S",
                "東京都",
                "東京都",
                "subsidy",
                "https://www.metro.tokyo.lg.jp/x",
                "2026-04-26 10:00:00",
                1500.0,
                0,
            ),
            (
                "UNI-S-002",
                "北海道農業経営支援",
                "S",
                "北海道",
                "北海道",
                "subsidy",
                "https://www.pref.hokkaido.lg.jp/y",
                "2026-04-25 10:00:00",
                800.0,
                0,
            ),
            (
                "UNI-S-003",
                "全国DX投資促進",
                "S",
                "東京都",
                "経産省",
                "subsidy",
                "https://www.meti.go.jp/z",
                "2026-04-24 10:00:00",
                5000.0,
                0,
            ),
            (
                "UNI-A-001",
                "愛知県スタートアップ",
                "A",
                "愛知県",
                "愛知県",
                "loan",
                "https://www.pref.aichi.lg.jp/q",
                "2026-04-23 10:00:00",
                300.0,
                0,
            ),
            (
                "UNI-A-002",
                "京都市創業支援",
                "A",
                "京都府",
                "京都市",
                "subsidy",
                "https://www.city.kyoto.lg.jp/r",
                "2026-04-22 10:00:00",
                200.0,
                0,
            ),
            (
                "UNI-B-001",
                "大阪市起業塾",
                "B",
                "大阪府",
                "大阪市",
                "subsidy",
                "https://www.city.osaka.lg.jp/s",
                "2026-04-21 10:00:00",
                50.0,
                0,
            ),
            (
                "UNI-S-004",
                "青森県集約サイト由来",
                "S",
                "青森県",
                "青森県",
                "subsidy",
                "https://www.smart-hojokin.jp/subsidies/67658",
                "2026-04-30 10:00:00",
                1000.0,
                0,
            ),
            (
                "UNI-S-005",
                "焼津市スマート農業普及",
                "S",
                "静岡県",
                "焼津市",
                "subsidy",
                "https://www.city.yaizu.lg.jp/business/suisan-nougyo/agriculture/manage-support/smart/smart-hojokin.html",
                "2026-04-29 10:00:00",
                500.0,
                0,
            ),
            ("UNI-EXC-001", "除外", "S", "東京都", None, "subsidy", None, None, None, 1),
        ]
        for r in rows:
            conn.execute(
                """
                INSERT INTO programs
                  (unified_id, primary_name, tier, prefecture, authority_name,
                   program_kind, source_url, source_fetched_at,
                   amount_max_man_yen, excluded, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?, '2026-04-30')
                """,
                r,
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def autonomath_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_AMENDMENT_SCHEMA)
        # Insert 4 diffs across 3 days; ensure detected_at order is enforced
        rows = [
            ("entityA", "amount_max_yen", "1000000", "1500000", "2026-04-28 10:00:00"),
            ("entityB", "subsidy_rate_max", "0.5", "0.66", "2026-04-29 12:00:00"),
            (
                "entityC",
                "source_url",
                "https://old.example.jp",
                "https://new.example.jp",
                "2026-04-30 09:00:00",
            ),
            ("entityD", "target_set_json", "[]", '["sme"]', "2026-04-27 08:00:00"),
        ]
        for r in rows:
            conn.execute(
                """
                INSERT INTO am_amendment_diff
                  (entity_id, field_name, prev_value, new_value, detected_at)
                VALUES (?,?,?,?,?)
                """,
                r,
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _generate(jpintel_db: Path, autonomath_db: Path, out_dir: Path) -> int:
    import generate_program_rss_feeds as mod  # type: ignore[import-not-found]

    return mod.main(
        [
            "--jpintel-db",
            str(jpintel_db),
            "--autonomath-db",
            str(autonomath_db),
            "--out-dir",
            str(out_dir),
            "--lastmod",
            "2026-05-01T00:00:00+00:00",
        ]
    )


# --- 1. Tier S item count ---------------------------------------------------
def test_tier_s_feed_item_count(jpintel_db: Path, autonomath_db: Path, tmp_path: Path):
    out = tmp_path / "rss"
    rc = _generate(jpintel_db, autonomath_db, out)
    assert rc == 0
    body = (out / "programs-tier-s.xml").read_text(encoding="utf-8")
    # Fixture seeds 5 Tier S non-excluded rows, but one is an aggregator
    # domain and must be filtered. The official Yaizu URL contains the
    # substring "smart-hojokin" in its path and must remain.
    assert body.count("<item>") == 4
    assert "UNI-S-001" in body
    assert "UNI-S-002" in body
    assert "UNI-S-003" in body
    assert "UNI-S-004" not in body
    assert "UNI-S-005" in body
    assert "www.smart-hojokin.jp" not in body
    # Excluded row must not leak in.
    assert "UNI-EXC-001" not in body


# --- 2. Amendment RSS reverse-chrono ordering -------------------------------
def test_amendment_feed_is_reverse_chrono(jpintel_db: Path, autonomath_db: Path, tmp_path: Path):
    out = tmp_path / "rss"
    rc = _generate(jpintel_db, autonomath_db, out)
    assert rc == 0
    body = (out / "amendments.xml").read_text(encoding="utf-8")
    # 4 diffs total, all field_names are tracked → expect 4 items.
    assert body.count("<item>") == 4
    # Verify entity order: 2026-04-30 (entityC) first, then 04-29 (B), 04-28 (A), 04-27 (D).
    entity_order = []
    for needle in ("entityC", "entityB", "entityA", "entityD"):
        # Position of the entity_id substring in the rendered feed body —
        # strictly increasing positions = reverse-chrono preserved.
        entity_order.append((needle, body.find(needle)))
    # Strictly increasing positions = reverse-chrono preserved.
    positions = [p for _, p in entity_order]
    assert all(p != -1 for p in positions), entity_order
    assert positions == sorted(positions), positions


# --- 3. Prefecture URL pattern ----------------------------------------------
def test_prefecture_url_pattern_and_isolation(
    jpintel_db: Path, autonomath_db: Path, tmp_path: Path
):
    out = tmp_path / "rss"
    rc = _generate(jpintel_db, autonomath_db, out)
    assert rc == 0
    pref_dir = out / "prefecture"
    files = sorted(p.name for p in pref_dir.glob("*.xml"))
    # Fixture has S/A/B rows in: 東京都, 北海道, 静岡県, 愛知県, 京都府, 大阪府.
    # The 青森県 row is aggregator-domain only and must not emit a feed.
    # That maps to slugs: tokyo, hokkaido, shizuoka, aichi, kyoto, osaka.
    assert "tokyo.xml" in files
    assert "hokkaido.xml" in files
    assert "shizuoka.xml" in files
    assert "aichi.xml" in files
    assert "kyoto.xml" in files
    assert "osaka.xml" in files
    assert "aomori.xml" not in files
    # Prefectures with zero matching rows must NOT emit empty files.
    assert "okinawa.xml" not in files

    # Tokyo feed must only contain Tokyo programs (no cross-pollination).
    tokyo = (pref_dir / "tokyo.xml").read_text(encoding="utf-8")
    assert "UNI-S-001" in tokyo  # Tokyo S
    assert "UNI-S-003" in tokyo  # Tokyo S (different program)
    assert "UNI-S-002" not in tokyo  # Hokkaido S — must NOT appear
    assert "UNI-A-001" not in tokyo  # Aichi A — must NOT appear
    # URL pattern: feed self-link contains /rss/prefecture/tokyo.xml
    assert "https://jpcite.com/rss/prefecture/tokyo.xml" in tokyo


# --- 4. Idempotency ---------------------------------------------------------
def test_idempotent_byte_identical(jpintel_db: Path, autonomath_db: Path, tmp_path: Path):
    out = tmp_path / "rss"
    assert _generate(jpintel_db, autonomath_db, out) == 0
    snap1 = {p.relative_to(out): p.read_bytes() for p in out.rglob("*.xml")}
    assert _generate(jpintel_db, autonomath_db, out) == 0
    snap2 = {p.relative_to(out): p.read_bytes() for p in out.rglob("*.xml")}
    assert snap1.keys() == snap2.keys()
    for k in snap1:
        assert snap1[k] == snap2[k], f"{k} drifted on second run"


# --- 5. Brand + copyright sanity --------------------------------------------
def test_brand_and_copyright(jpintel_db: Path, autonomath_db: Path, tmp_path: Path):
    out = tmp_path / "rss"
    assert _generate(jpintel_db, autonomath_db, out) == 0
    for path in [
        out / "programs-tier-s.xml",
        out / "amendments.xml",
        out / "prefecture" / "tokyo.xml",
    ]:
        body = path.read_text(encoding="utf-8")
        assert "(C) 2026 jpcite" in body, path
        assert "Bookyou株式会社" not in body, path
        assert "T8010001213708" not in body, path
        assert "info@bookyou.net" not in body, path
        # User-facing brand must be jpcite (not AutonoMath / jpintel).
        assert "jpcite" in body, path
        # Defensive: no leak of deprecated user-facing brand strings into <title>.
        # The internal package name `jpintel_mcp` may legitimately appear in
        # API URLs, but channel/title/description should never expose it.
        title_block = body.split("</title>", 1)[0]
        assert "AutonoMath" not in title_block, path
        assert "jpintel" not in title_block, path
