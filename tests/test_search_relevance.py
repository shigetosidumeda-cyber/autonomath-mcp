"""Regression tests for search relevance fixes.

Covers the six fixes landed in src/jpintel_mcp/api/programs.py:

1. tier='X' quarantine — rows gated out of user-facing search/get even
   when excluded=0 (ingest lag leaves 432 such rows).
2. FTS ordering respects tier — tier primacy, FTS rank as secondary.
3. Kana normalization — hiragana/katakana queries find kanji documents
   via a query-time KANA_EXPANSIONS map (no reindex needed).
4. Phrase-match for pure-kanji queries — `税額控除` uses FTS5 phrase
   quoting so trigram overlaps on single kanji don't float
   `企業版ふるさと納税` above `研究開発税制(試験研究費の税額控除)`.
5. q<3 LIKE fallback column coverage — short queries scan primary_name,
   aliases_json, AND enriched_json (previously only primary_name +
   aliases_json).
6. Dedup by primary_name — `IT導入補助金` had 4 near-identical rows;
   ROW_NUMBER() per-name keeps the highest-tier row.

The test seed DB (tests/conftest.py::seeded_db) holds 4 fixture rows.
We extend it with targeted inserts per test to exercise each fix in
isolation. conftest.py is session-scoped, so we use a dedicated fixture
that augments the existing DB on demand.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers — augment the session-seeded DB with rows targeted at each fix.
# We insert once per test, with unique unified_ids, so concurrent tests in
# this module don't collide.
# ---------------------------------------------------------------------------


def _insert(
    conn: sqlite3.Connection,
    *,
    unified_id: str,
    primary_name: str,
    tier: str | None,
    excluded: int = 0,
    aliases: list[str] | None = None,
    enriched_text: str = "",
) -> None:
    """Insert one program row + its FTS row. Minimal column set — matches
    conftest.py::seeded_db usage."""
    now = datetime.now(UTC).isoformat()
    aliases_json = json.dumps(aliases or [], ensure_ascii=False)
    conn.execute(
        """INSERT OR REPLACE INTO programs(
            unified_id, primary_name, aliases_json,
            authority_level, authority_name, prefecture, municipality,
            program_kind, official_url,
            amount_max_man_yen, amount_min_man_yen, subsidy_rate,
            trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
            excluded, exclusion_reason,
            crop_categories_json, equipment_category,
            target_types_json, funding_purpose_json,
            amount_band, application_window_json,
            enriched_json, source_mentions_json, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            unified_id,
            primary_name,
            aliases_json,
            "国",
            None,
            None,
            None,
            "補助金",
            None,
            None,
            None,
            None,
            None,
            tier,
            None,
            None,
            None,
            excluded,
            None,
            None,
            None,
            json.dumps([], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            None,
            None,
            enriched_text,
            None,
            now,
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
        "VALUES (?,?,?,?)",
        (unified_id, primary_name, " ".join(aliases or []), enriched_text),
    )
    conn.commit()


@pytest.fixture()
def db_conn(seeded_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Fix 1: tier='X' leak — never surface quarantined rows.
# ---------------------------------------------------------------------------


def test_tier_x_excluded(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """A tier='X' row with excluded=0 must not appear in /search results."""
    unique_name = "テスト除外X浄化槽"
    _insert(
        db_conn,
        unified_id="UNI-test-tierx-leak",
        primary_name=unique_name,
        tier="X",
        excluded=0,
    )

    r = client.get("/v1/programs/search", params={"q": unique_name})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0, f"tier='X' row leaked into search despite excluded=0; got {body}"

    # Public search rejects hidden/internal filters instead of exposing
    # quarantine rows.
    r2 = client.get(
        "/v1/programs/search",
        params={"q": unique_name, "include_excluded": "true"},
    )
    assert r2.status_code == 422
    assert "include_excluded" in r2.text


def test_get_program_tier_x_404(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """GET /v1/programs/{id} must 404 on tier='X' rows so stale slug
    links from the static site / search-engine cache can't serve
    quarantined content."""
    unified_id = "UNI-test-tierx-get404"
    _insert(
        db_conn,
        unified_id=unified_id,
        primary_name="テスト除外取得",
        tier="X",
        excluded=0,
    )
    r = client.get(f"/v1/programs/{unified_id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Fix 2: FTS ordering respects tier — S/A outrank B/C/X on FTS path.
# ---------------------------------------------------------------------------


def test_fts_tier_priority(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """A common search term should return a top result with tier S or A."""
    # Seed DB already has UNI-test-s-1 (tier=S) and UNI-test-a-1 (tier=A)
    # that both contain "補助金" / "支援事業" — common enough to trigger
    # multiple hits. Use "補助金" which exists in the S fixture.
    r = client.get("/v1/programs/search", params={"q": "補助金", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    first = body["results"][0]
    assert first["tier"] in ("S", "A"), f"FTS ordering did not prioritize tier; first row = {first}"


# ---------------------------------------------------------------------------
# Fix 3: kana -> kanji expansion at query time.
# ---------------------------------------------------------------------------


def test_kana_expansion(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """A hiragana query ('のうぎょう') must find kanji-only primary_names
    ('農業...')."""
    # Fresh tier-A kanji doc with 農業 in primary_name so the expansion
    # has an unambiguous target. Seed DB's青森 fixture doesn't have 農業
    # directly in primary_name.
    _insert(
        db_conn,
        unified_id="UNI-test-kana-target",
        primary_name="テスト農業経営支援補助金",
        tier="A",
    )

    r = client.get("/v1/programs/search", params={"q": "のうぎょう", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1, (
        "hiragana query 'のうぎょう' returned zero hits; KANA_EXPANSIONS "
        "not wired into search_programs"
    )
    # Top result must contain the kanji form (the whole point of expansion).
    top = body["results"][0]
    assert (
        "農業" in top["primary_name"]
    ), f"first result does not contain 農業: {top['primary_name']!r}"


# ---------------------------------------------------------------------------
# Fix 4: phrase-match defeats trigram single-kanji false-positives.
# ---------------------------------------------------------------------------


def test_phrase_match_no_false_positive(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """`税額控除` must NOT pick up `ふるさと納税` / `企業版ふるさと納税`
    as the top result — those share only the single kanji 税.

    We seed both candidates ourselves so the test is deterministic
    independent of what's in the production DB snapshot.
    """
    # Decoy: shares only the single kanji 税 with the query. Trigrams
    # from the query (税額控, 額控除) don't appear here, but FTS rank
    # can still surface this doc because its enriched_text contains
    # 税額控除 as a mention.
    _insert(
        db_conn,
        unified_id="UNI-test-phrase-decoy",
        primary_name="テスト企業版ふるさと納税",
        tier="S",
        enriched_text="この制度は法人税の税額控除を提供します。",
    )
    # True hit: primary_name contains 税額控除 literally.
    _insert(
        db_conn,
        unified_id="UNI-test-phrase-hit",
        primary_name="テスト研究開発税制（試験研究費の税額控除）",
        tier="C",
    )

    r = client.get("/v1/programs/search", params={"q": "税額控除", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    top = body["results"][0]
    assert (
        "税額控除" in top["primary_name"]
    ), f"top result does not contain the literal phrase 税額控除: {top['primary_name']!r}"
    assert (
        "ふるさと納税" not in top["primary_name"]
    ), f"top result is the 税-overlap false-positive: {top['primary_name']!r}"


# ---------------------------------------------------------------------------
# Fix 6: dedup by primary_name — duplicate inserts collapse to one row.
# ---------------------------------------------------------------------------


def test_dedup(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """Multiple rows with the same primary_name must collapse to a single
    result, keeping the highest-tier row."""
    name = "テスト重複IT導入補助金"
    _insert(
        db_conn,
        unified_id="UNI-test-dedup-a",
        primary_name=name,
        tier="C",
    )
    _insert(
        db_conn,
        unified_id="UNI-test-dedup-b",
        primary_name=name,
        tier="S",
    )
    _insert(
        db_conn,
        unified_id="UNI-test-dedup-c",
        primary_name=name,
        tier="B",
    )

    r = client.get("/v1/programs/search", params={"q": name, "limit": 10})
    assert r.status_code == 200
    body = r.json()
    names = [row["primary_name"] for row in body["results"]]
    assert len(names) == len(set(names)), f"duplicate primary_names leaked: {names}"
    # Matching row present, and the kept copy is tier S (the highest).
    matching = [row for row in body["results"] if row["primary_name"] == name]
    assert len(matching) == 1
    assert matching[0]["tier"] == "S", f"dedup kept the wrong tier: {matching[0]['tier']!r}"


# ---------------------------------------------------------------------------
# Fix 5: q<3 LIKE fallback must scan aliases_json and enriched_json.
# ---------------------------------------------------------------------------


def test_short_query_aliases(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """A 2-char query whose term lives only in aliases_json (not in
    primary_name) must still return that row. Proves the LIKE fallback
    covers the aliases column, not only primary_name."""
    # Alias-only token: 'XY' doesn't appear in any primary_name in the
    # seed DB or test inserts. Hidden in aliases_json alone.
    _insert(
        db_conn,
        unified_id="UNI-test-short-alias",
        primary_name="テスト略称検索対象事業",
        tier="A",
        aliases=["XY"],
    )

    r = client.get("/v1/programs/search", params={"q": "XY", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1, (
        "2-char query 'XY' missed the aliases_json match; LIKE fallback "
        "does not cover aliases column"
    )
    names = [row["primary_name"] for row in body["results"]]
    assert "テスト略称検索対象事業" in names


def test_short_query_enriched(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """Companion to test_short_query_aliases: a 2-char NON-ASCII query
    whose term lives only in enriched_json must surface the row.

    Enriched-column coverage is retained for short Japanese / mixed-script
    queries. Pure-ASCII short queries (<3 chars) deliberately skip
    enriched_json — the q=IT perf fix, see programs.py::search_programs
    LIKE-fallback branch. `test_short_query_ascii_skips_enriched` below
    pins the new ASCII behavior.
    """
    _insert(
        db_conn,
        unified_id="UNI-test-short-enriched",
        primary_name="テスト詳細本文検索対象",
        tier="A",
        enriched_text="この事業は税額控除の対象です。",
    )
    r = client.get("/v1/programs/search", params={"q": "税額", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    names = [row["primary_name"] for row in body["results"]]
    assert (
        "テスト詳細本文検索対象" in names
    ), f"2-char query '税額' missed the enriched_json match; names={names}"


def test_short_query_ascii_skips_enriched(client: TestClient, db_conn: sqlite3.Connection) -> None:
    """Short pure-ASCII queries (len<3) deliberately skip enriched_json.

    Rationale: including enriched_json for 2-char ASCII is a double
    failure — latency (~400ms P95 scan over 184 MB of JSON) and relevance
    (substring hits inside English words like 'credit', 'exhibit' are not
    what the user means by 'IT'). The fix restricts short-ASCII LIKE to
    primary_name + aliases_json so the token has to appear as a real
    acronym in a label, which is the common agent-query intent.

    This test pins the new behavior so we don't accidentally re-introduce
    the enriched_json scan in a future refactor.
    """
    # Decoy: the short-ASCII token 'QZ' exists only inside enriched_text.
    # Under the old behavior this row would match ?q=QZ; under the new
    # behavior it must NOT match.
    _insert(
        db_conn,
        unified_id="UNI-test-ascii-enriched-decoy",
        primary_name="テストASCII短文デコイ対象",
        tier="A",
        enriched_text="参考資料 QZ リファレンス。",
    )
    # Control row: 'QZ' in primary_name — must match.
    _insert(
        db_conn,
        unified_id="UNI-test-ascii-name-hit",
        primary_name="QZ導入支援事業",
        tier="A",
    )

    r = client.get("/v1/programs/search", params={"q": "QZ", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    names = [row["primary_name"] for row in body["results"]]
    assert "QZ導入支援事業" in names, f"short ASCII query missed primary_name hit; names={names}"
    assert (
        "テストASCII短文デコイ対象" not in names
    ), "short ASCII query leaked enriched_json-only match; the perf-fix narrowing is not active"
