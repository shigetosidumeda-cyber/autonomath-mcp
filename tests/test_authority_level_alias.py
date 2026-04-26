"""Tests for authority_level JP/EN alias normalization at the API boundary.

The DB stores English lowercase (`national` / `prefecture` / `municipality`
/ `financial`). Historic docs taught users to pass Japanese (`国` / `都道府県`
/ `市区町村`). The normalization layer accepts both vocabularies and maps to
the canonical English form before the SQL equality filter runs.

See: src/jpintel_mcp/api/vocab.py
"""

from __future__ import annotations

import pytest

from jpintel_mcp.api.vocab import _normalize_authority_level


@pytest.mark.parametrize(
    "raw,expected",
    [
        # English canonical — idempotent pass-through.
        ("national", "national"),
        ("prefecture", "prefecture"),
        ("municipality", "municipality"),
        ("financial", "financial"),
    ],
)
def test_english_canonical_passthrough(raw: str, expected: str) -> None:
    assert _normalize_authority_level(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Japanese aliases (what the pre-fix docs + SDK examples told users).
        ("国", "national"),
        ("都道府県", "prefecture"),
        ("市区町村", "municipality"),
        ("市町村", "municipality"),
        ("公庫", "financial"),
        ("政府系金融機関", "financial"),
    ],
)
def test_japanese_aliases_map_to_english(raw: str, expected: str) -> None:
    assert _normalize_authority_level(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Mixed case English — case-insensitive normalization.
        ("NATIONAL", "national"),
        ("National", "national"),
        ("Prefecture", "prefecture"),
        ("MUNICIPALITY", "municipality"),
        # Leading/trailing whitespace is stripped before lookup.
        ("  prefecture  ", "prefecture"),
        ("\t国\n", "national"),
    ],
)
def test_case_and_whitespace_tolerance(raw: str, expected: str) -> None:
    assert _normalize_authority_level(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Unknown values pass through verbatim — callers get 0 rows, not a
        # silent rewrite. Treat empty/None as "no filter".
        (None, None),
        ("", None),
        ("   ", None),
        # Genuinely unknown — pass through (future-proof).
        ("regional_bureau", "regional_bureau"),
        ("独立行政法人", "独立行政法人"),
    ],
)
def test_unknown_and_empty_passthrough(raw, expected) -> None:
    assert _normalize_authority_level(raw) == expected


def test_end_to_end_rest_filter_accepts_japanese(client) -> None:
    """Regression test: historic docs promised `国` works in /v1/programs/search.

    The seeded DB in conftest.py happens to store JP values, but the server
    now normalizes before querying either way — so both `国` and `national`
    must be accepted and return results without erroring. The exact row
    count depends on the fixture; we only assert the call succeeds and the
    echoed param is what the user sent (we intentionally don't rewrite the
    echoed filter in the response).
    """
    resp_jp = client.get("/v1/programs/search", params={"authority_level": "国"})
    assert resp_jp.status_code == 200, resp_jp.text

    resp_en = client.get("/v1/programs/search", params={"authority_level": "national"})
    assert resp_en.status_code == 200, resp_en.text

    # Both queries must return the same total — they filter on the same
    # canonical bucket post-normalization.
    assert resp_jp.json()["total"] == resp_en.json()["total"]
