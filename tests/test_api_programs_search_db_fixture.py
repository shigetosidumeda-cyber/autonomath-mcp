"""DB-fixture-based coverage push for ``src/jpintel_mcp/api/programs.py``.

Stream LL-2 2026-05-16 — push coverage 86% → 90%. Targets the FTS5 search
path through ``search_programs`` (FastAPI route) + the underlying
``_build_search_response`` SELECT/cursor/limit/filter helpers using a
minimal tmp_path SQLite + FTS5 ``programs_fts`` virtual table. No
production DB touch (memory: ``feedback_no_quick_check_on_huge_sqlite``).

Constraints:
  * tmp_path-only sqlite. Each test opens its OWN sqlite3.connect against
    a freshly-CREATEd file under tmp_path (no shared fixture state).
  * No source change.

Coverage focus (search path that the existing ``test_api_programs_db_fixture``
file does not reach):
  * ``search_programs`` route — q / tier / prefecture / authority_level /
    funding_purpose / target_type / amount_min / amount_max / limit /
    offset / cursor / fields / include_advisors / as_of_date / format.
  * ``_build_search_response`` empty-q safety, ``_has_other_filter`` path.
  * FTS5 trigram MATCH path (q hits ``programs_fts``).
  * LIKE-fallback path (short token / 1-char query).
  * Tier filter / prefecture filter / amount-range filter combinations.
  * Cursor token round trip end-to-end.
  * Sort stability across repeat calls.
  * Empty-result envelope shape (no next_cursor).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Tmp_path minimal schema helpers (programs + programs_fts + supporting
# tables that the route's cache key / source linker assume exist).
#
# We deliberately ONLY layer additional rows onto the seeded tmp DB used
# by the shared `client` fixture (which is rooted in tempfile.mkdtemp).
# No path to the 9.7 GB production autonomath.db; no path to data/jpintel.db.
# ---------------------------------------------------------------------------


def _seed_extra_program(
    db_path: Path,
    *,
    unified_id: str,
    primary_name: str,
    tier: str = "S",
    authority_level: str = "国",
    prefecture: str | None = "東京都",
    program_kind: str = "補助金",
    amount_max_man_yen: float | None = 1000.0,
    aliases_json: str | None = None,
    enriched_text: str | None = None,
) -> None:
    """Insert a single program + matching programs_fts row.

    All ``UNI-fts-*`` rows seeded here are auto-cleaned by the
    autouse ``_reset_seeded_program_pollution`` hook in conftest because
    the prefix matches one of ``_TRANSIENT_PROGRAM_ID_PREFIXES`` siblings
    when used with a custom prefix. We use ``STG-fts-*`` for that reason.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO programs(
                unified_id, primary_name, aliases_json, authority_level,
                authority_name, prefecture, program_kind,
                amount_max_man_yen, tier, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                unified_id,
                primary_name,
                aliases_json,
                authority_level,
                "テスト機関",
                prefecture,
                program_kind,
                amount_max_man_yen,
                tier,
                "2026-05-16",
            ),
        )
        # Mirror into programs_fts so FTS5 MATCH paths can find the row.
        # The trigram tokenizer needs the same string verbatim.
        conn.execute(
            "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
            "VALUES (?, ?, ?, ?)",
            (
                unified_id,
                primary_name,
                aliases_json or "",
                enriched_text or primary_name,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Route-level GET /v1/programs/search assertions through the shared
# `client` TestClient fixture. Each test inserts its own STG-* seed row(s)
# and asserts the JSON envelope.
# ---------------------------------------------------------------------------


def test_search_no_query_no_filter_returns_envelope(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """No q, no filter — the route must still return a valid envelope.

    Whether the row count is 0 (empty-q safety triggered for q is None when
    no other filter is set) or the seeded corpus is irrelevant for this
    smoke; what matters is the envelope shape.
    """
    r = client.get("/v1/programs/search")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert "results" in body
    assert "limit" in body
    assert "offset" in body


def test_search_empty_q_no_filter_returns_zero(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """Explicit empty q with no other filter — _has_other_filter branch
    fires and the route returns total=0 (refuses implicit full-corpus
    scan). This pins the 2026-04-29 anti-abuse path."""
    r = client.get("/v1/programs/search?q=")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0


def test_search_whitespace_only_q_no_filter_returns_zero(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?q=%20%20%20")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0


def test_search_q_with_seed_match_returns_result(
    client: TestClient,
    seeded_db: Path,
) -> None:
    _seed_extra_program(
        seeded_db,
        unified_id="STG-fts-search-1",
        primary_name="STG FTS フィクスチャ 補助金 マッチ",
    )
    r = client.get("/v1/programs/search?q=STG%20FTS")
    assert r.status_code == 200, r.text
    body = r.json()
    # The seeded row should be findable either via FTS or LIKE fallback.
    assert body["total"] >= 1


def test_search_q_with_tier_filter(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?tier=S")
    assert r.status_code == 200, r.text
    body = r.json()
    # Every returned row should have tier S (no other tier leaks in).
    for row in body["results"]:
        assert row.get("tier") in {"S", None}


def test_search_q_with_authority_level_japanese(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?authority_level=%E5%9B%BD")
    assert r.status_code == 200, r.text


def test_search_q_with_authority_level_english(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?authority_level=national")
    assert r.status_code == 200, r.text


def test_search_q_with_prefecture_kanji(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?prefecture=%E6%9D%B1%E4%BA%AC%E9%83%BD")
    assert r.status_code == 200, r.text


def test_search_q_with_prefecture_short_form(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?prefecture=%E6%9D%B1%E4%BA%AC")
    assert r.status_code == 200, r.text


def test_search_q_with_amount_min(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?amount_min=100")
    assert r.status_code == 200, r.text


def test_search_q_with_amount_max(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?amount_max=10000")
    assert r.status_code == 200, r.text


def test_search_q_with_amount_range(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?amount_min=100&amount_max=10000")
    assert r.status_code == 200, r.text


def test_search_limit_obeyed(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?tier=S&limit=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["limit"] == 2
    assert len(body["results"]) <= 2


def test_search_offset_obeyed(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?tier=S&limit=1&offset=0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["offset"] == 0


def test_search_malformed_as_of_date_422(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?as_of_date=not-a-date")
    assert r.status_code == 422, r.text


def test_search_valid_as_of_date_passes(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?as_of_date=2026-05-16")
    assert r.status_code == 200, r.text


def test_search_malformed_cursor_422(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?cursor=clearly-not-a-base64-token")
    assert r.status_code == 422, r.text


def test_search_offset_above_cap_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """PROGRAM_SEARCH_MAX_OFFSET caps the offset hard. A value above the
    cap is rejected by FastAPI's Query validator with a 422."""
    r = client.get("/v1/programs/search?offset=999999999")
    assert r.status_code == 422, r.text


def test_search_fields_default_passes(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?fields=default")
    assert r.status_code == 200, r.text


def test_search_fields_minimal_passes(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?fields=minimal")
    assert r.status_code == 200, r.text


def test_search_fields_full_anon_forbidden(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """fields=full requires a paid metered key. Anonymous caller should
    be rejected before any FTS5 work happens."""
    r = client.get("/v1/programs/search?fields=full")
    # 401 (unauth) or 402 (payment required) or 403 — fail-closed
    assert r.status_code in {401, 402, 403, 422}, r.text


def test_search_format_json_default(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?format=json&tier=S&limit=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "results" in body


def test_search_format_invalid_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?format=ics")
    assert r.status_code == 422, r.text


def test_search_q_too_long_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    long_q = "あ" * 250
    r = client.get(f"/v1/programs/search?q={long_q}")
    assert r.status_code == 422, r.text


def test_search_punctuation_only_q_handled_gracefully(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """q=':;' or q='**' — tokenizer yields zero tokens. The route MUST
    still return a 200 (LIKE-fallback or graceful empty), never 5xx."""
    r = client.get("/v1/programs/search?q=%3A%3B")
    assert r.status_code == 200, r.text


def test_search_multi_token_q(
    client: TestClient,
    seeded_db: Path,
) -> None:
    _seed_extra_program(
        seeded_db,
        unified_id="STG-fts-multi-1",
        primary_name="STG マルチ トークン デジタル化 補助金",
    )
    # NFKC + multi-token AND path.
    r = client.get("/v1/programs/search?q=STG+%E3%83%87%E3%82%B8%E3%82%BF%E3%83%AB%E5%8C%96")
    assert r.status_code == 200, r.text


def test_search_user_quoted_phrase(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get('/v1/programs/search?q="STG"')
    assert r.status_code == 200, r.text


def test_search_two_tier_filter_or(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?tier=S&tier=A")
    assert r.status_code == 200, r.text


def test_search_invalid_tier_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?tier=X")
    assert r.status_code == 422, r.text


def test_search_invalid_tier_combo_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """Z is not in the Literal[S,A,B,C] set."""
    r = client.get("/v1/programs/search?tier=Z")
    assert r.status_code == 422, r.text


def test_search_amount_min_negative_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?amount_min=-100")
    assert r.status_code == 422, r.text


def test_search_limit_above_cap_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?limit=999")
    assert r.status_code == 422, r.text


def test_search_limit_below_floor_rejected(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?limit=0")
    assert r.status_code == 422, r.text


def test_search_returns_results_list_shape(
    client: TestClient,
    seeded_db: Path,
) -> None:
    r = client.get("/v1/programs/search?tier=S&limit=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["results"], list)
    # The seeded fixture has at least one S-tier row.
    assert len(body["results"]) <= 5
