"""Regression tests for the CLAUDE.md "tier='X' quarantine" gotcha.

CLAUDE.md / Common gotchas:

    `tier='X'` is the quarantine tier. All search paths must exclude it.
    `generate_program_pages.py` filters `tier IN ('S','A','B','C')` —
    keep that filter.

These tests guard the invariant on three fronts:

  1. Source-grep `src/jpintel_mcp/api/programs.py` for every `tier IN (`
     stanza. Each one must either pin the whitelist to S/A/B/C literally
     OR be a parameterized placeholder paired with the
     `COALESCE(tier,'X') != 'X'` quarantine gate within the same
     surrounding WHERE chain. Tier='X' must never be reachable as a
     literal in any `tier IN (...)` allow-list.

  2. Source-grep `scripts/generate_program_pages.py` for every
     `tier IN (` stanza. Each one must be paired with a whitelist that
     excludes 'X'. The accepted forms are the literal
     `tier IN ('S','A','B','C')`, the literal `tier IN ('S','A')`
     (post-2026-04-29 SEO reduction), and the templated
     `tier IN ({tier_in})` paired with the `safe_tiers` filter (which
     only accepts S/A/B/C).

  3. Integration: seed a `programs` row with `tier='X'` (excluded=0,
     so the row would leak if only `excluded=0` was checked), call
     `/v1/programs/search`, assert the row is NOT in results. This is
     the live end-to-end version of the source-grep guard — if a
     regression deletes the `COALESCE(tier,'X') != 'X'` gate but the
     source-grep still passes (e.g. the dynamic `tier IN (?)` stays
     parameterized), this integration test still trips.

Scope discipline: this test file MUST NOT edit programs.py or
generate_program_pages.py. It only reads them as text.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAMS_PY = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "programs.py"
GENERATE_PAGES_PY = REPO_ROOT / "scripts" / "generate_program_pages.py"

# The only whitelist literals that are SAFE — every one of them omits 'X'.
# 'S','A','B','C' is the canonical legacy form; 'S','A' is the post
# 2026-04-29 SEO-reduction form used by generate_program_pages.py for
# the static-page subset. Both exclude X by construction.
_SAFE_LITERAL_WHITELISTS = (
    "tier IN ('S','A','B','C')",
    "tier IN ('S','A')",
)

# Dynamic / templated forms are SAFE only because the surrounding code
# both (a) restricts the runtime allow-list to S/A/B/C and (b) layers
# the explicit `COALESCE(tier,'X') != 'X'` quarantine gate on top.
# We assert (b) per stanza below.
_TEMPLATED_FORMS = (
    "tier IN ({tier_in})",  # generate_program_pages INDEXABLE_SQL_TEMPLATE
)


def _find_tier_in_stanzas(src: str) -> list[tuple[int, str]]:
    """Return (offset, full_line) for each `tier IN (` SQL occurrence.

    Case-sensitive on the SQL keyword (`tier IN`) so prose docstrings
    that mention the invariant in lowercase (`tier in (S,A,B,C)`)
    don't trip the guard. By convention every SQL stanza in the two
    target files uses uppercase IN; this matches the codebase's existing
    convention and is robust against accidental matches.
    """
    out: list[tuple[int, str]] = []
    for m in re.finditer(r"tier\s+IN\s*\(", src):
        start = m.start()
        # Capture the rest of the logical SQL line (up to first newline or
        # 200 chars) for diagnostic + literal-match purposes.
        end = src.find("\n", start)
        if end == -1:
            end = min(len(src), start + 200)
        out.append((start, src[start:end]))
    return out


# ---------------------------------------------------------------------------
# Source-grep guards
# ---------------------------------------------------------------------------


def test_programs_py_tier_in_stanzas_safe() -> None:
    """Every `tier IN (` in api/programs.py must be safe.

    "Safe" means either:
      - A literal whitelist that omits 'X' (S/A/B/C or S/A), OR
      - A parameterized placeholder (`tier IN (?)` / `tier IN (?,?)` etc.)
        paired with `COALESCE(tier,'X') != 'X'` within a 2000-char window
        downstream of the stanza. The downstream window is the WHERE
        chain that gets appended after the dynamic clause, so the
        quarantine gate must land somewhere within that range.
    """
    src = PROGRAMS_PY.read_text(encoding="utf-8")
    stanzas = _find_tier_in_stanzas(src)
    assert stanzas, f"expected at least one `tier IN (` in {PROGRAMS_PY}"

    for offset, line in stanzas:
        # Allow literal safe forms first.
        if any(safe in line for safe in _SAFE_LITERAL_WHITELISTS):
            continue
        # Allow templated safe forms.
        if any(tmpl in line for tmpl in _TEMPLATED_FORMS):
            continue
        # Otherwise the stanza must be a parameterized form (e.g.
        # `tier IN ({','.join('?' * len(tier))})` or `tier IN (?,?)`)
        # AND the explicit X-quarantine gate must appear within a
        # downstream WHERE-chain window.
        is_parameterized = (
            "?" in line  # `tier IN (?, ?, ?)` or f-string with '?'
            or "'?'" in line  # double-quoted parameterized form
            or "'X'" not in line  # at minimum, no literal X in this line
        )
        assert is_parameterized, (
            f"`tier IN (` at offset {offset} is neither a safe literal "
            f"whitelist nor a parameterized placeholder: {line!r}"
        )

        window = src[offset : offset + 2000]
        assert "COALESCE(tier,'X') != 'X'" in window, (
            f"parameterized `tier IN (` at offset {offset} is not paired "
            f"with the `COALESCE(tier,'X') != 'X'` quarantine gate within "
            f"2000 chars downstream. Stanza: {line!r}"
        )


def test_programs_py_no_x_in_tier_in_literal() -> None:
    """No `tier IN (` literal in api/programs.py may include 'X'.

    Belt-and-braces over the previous test: even if someone replaces the
    parameterized form with a literal, that literal must still exclude X.
    """
    src = PROGRAMS_PY.read_text(encoding="utf-8")
    # Find every `tier IN ( ... )` whose contents are pure quoted literals
    # (i.e. NOT a placeholder/f-string/format expression). For those, scan
    # the parenthesized body for 'X'.
    pattern = re.compile(r"tier\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
    for m in pattern.finditer(src):
        body = m.group(1)
        # Only inspect bodies that look like literal CSV of quoted tiers
        # ('S','A',...). Skip parameterized / template forms.
        if "?" in body or "{" in body or "}" in body:
            continue
        # Now body is a literal list — must NOT mention 'X' or "X".
        assert "'X'" not in body and '"X"' not in body, (
            f"`tier IN ({body})` literal in api/programs.py includes 'X' — "
            f"would surface quarantined rows to user-facing search."
        )


def test_generate_program_pages_tier_in_stanzas_safe() -> None:
    """Every `tier IN (` in scripts/generate_program_pages.py must be safe.

    The generator is bulk-render-only; we accept either an X-excluding
    literal whitelist or the `{tier_in}` template (filled by `_iter_rows`
    from a `safe_tiers` allow-list that hard-codes S/A/B/C).
    """
    src = GENERATE_PAGES_PY.read_text(encoding="utf-8")
    stanzas = _find_tier_in_stanzas(src)
    assert stanzas, f"expected at least one `tier IN (` in {GENERATE_PAGES_PY}"

    for offset, line in stanzas:
        is_safe = any(safe in line for safe in _SAFE_LITERAL_WHITELISTS) or any(
            tmpl in line for tmpl in _TEMPLATED_FORMS
        )
        assert is_safe, (
            f"`tier IN (` at offset {offset} in generate_program_pages.py "
            f"is not paired with an X-excluding whitelist or template; "
            f"got: {line!r}"
        )


def test_generate_program_pages_no_x_in_tier_in_literal() -> None:
    """Same belt-and-braces invariant for the generator: no literal
    `tier IN ( ... 'X' ... )` may exist."""
    src = GENERATE_PAGES_PY.read_text(encoding="utf-8")
    pattern = re.compile(r"tier\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
    for m in pattern.finditer(src):
        body = m.group(1)
        if "?" in body or "{" in body or "}" in body:
            continue
        assert "'X'" not in body and '"X"' not in body, (
            f"`tier IN ({body})` literal in generate_program_pages.py "
            f"includes 'X' — would publish a quarantined row to the static site."
        )


def test_generate_program_pages_safe_tiers_filter_excludes_x() -> None:
    """The `_iter_rows` safe_tiers list comprehension must reject 'X'.

    Catches a regression where someone replaces the `("S","A","B","C")`
    membership check with something looser. We just check the literal
    string is present and that 'X' is NOT in the membership tuple on the
    same line.
    """
    src = GENERATE_PAGES_PY.read_text(encoding="utf-8")
    # The exact filter form: `safe_tiers = [t for t in tiers if t in (...)] or [...]`
    m = re.search(r"safe_tiers\s*=\s*\[.*?\]\s*or\s*\[.*?\]", src)
    assert m, "expected a `safe_tiers = [...] or [...]` filter in _iter_rows"
    snippet = m.group(0)
    assert "'X'" not in snippet and '"X"' not in snippet, (
        f"`safe_tiers` filter in generate_program_pages.py mentions 'X': {snippet!r}"
    )
    # And it must explicitly allow only S/A/B/C. Accept either single- or
    # double-quoted literals — the source file uses double quotes today.
    has_letter = lambda c: f"'{c}'" in snippet or f'"{c}"' in snippet  # noqa: E731
    assert all(has_letter(c) for c in "SABC"), (
        f"`safe_tiers` filter must whitelist S/A/B/C; got: {snippet!r}"
    )


# ---------------------------------------------------------------------------
# Integration guard — live end-to-end test via /v1/programs/search.
# ---------------------------------------------------------------------------


def _insert_tier_x_row(
    conn: sqlite3.Connection,
    *,
    unified_id: str,
    primary_name: str,
    excluded: int = 0,
) -> None:
    """Seed one program row with tier='X' + matching FTS row.

    excluded=0 is the dangerous case: only the explicit tier-X gate keeps
    this row out of search results. If the gate disappears, this row
    leaks.
    """
    now = datetime.now(UTC).isoformat()
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
            json.dumps([], ensure_ascii=False),
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
            "X",  # the quarantine tier
            None,
            None,
            None,
            excluded,
            "test-quarantine",
            None,
            None,
            json.dumps([], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            None,
            None,
            primary_name,  # enriched_json mirrors primary_name for FTS hit
            None,
            now,
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
        "VALUES (?,?,?,?)",
        (unified_id, primary_name, "", primary_name),
    )
    conn.commit()


def test_tier_x_row_not_returned_by_programs_search(client: TestClient, seeded_db: Path) -> None:
    """Seed a tier='X' / excluded=0 row, call /v1/programs/search, assert
    the row is NOT in results.

    Two complementary assertions:
      - Targeted query: search for the unique primary_name we inserted.
        Result count for that name must be 0.
      - Broad query: pull limit=100 across the entire corpus and assert
        no result row carries tier='X'.

    excluded=0 is critical: it isolates the test to the tier-X gate
    specifically. An excluded=1 row would be filtered by `excluded = 0`
    alone and would not exercise the quarantine guard.
    """
    unique_name = "テスト隔離プログラムTIERX_REGRESSION"
    unified_id = "UNI-test-tierx-regression-1"
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        _insert_tier_x_row(
            conn,
            unified_id=unified_id,
            primary_name=unique_name,
            excluded=0,
        )
    finally:
        conn.close()

    # Targeted search by the unique name — must not surface the X row.
    r = client.get("/v1/programs/search", params={"q": unique_name, "limit": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("results") or body.get("items") or []
    leaked = [
        row
        for row in rows
        if isinstance(row, dict) and (row.get("unified_id") == unified_id or row.get("tier") == "X")
    ]
    assert not leaked, (
        f"tier='X' / excluded=0 row leaked into targeted /v1/programs/search; found {leaked!r}"
    )
    # Also assert the API-reported total is 0 for this unique name —
    # paginating past `limit` doesn't change the leakage verdict.
    assert body.get("total", 0) == 0, (
        f"tier='X' row counted in search `total` even when paginated out of "
        f"the first {body.get('limit', 50)} results: {body!r}"
    )

    # Broad sweep — pull a generous batch and assert no X tier anywhere.
    r2 = client.get("/v1/programs/search", params={"limit": 100})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    rows2 = body2.get("results") or body2.get("items") or []
    for row in rows2:
        if not isinstance(row, dict):
            continue
        tier = (
            row.get("tier")
            or (row.get("program") or {}).get("tier")
            or (row.get("data") or {}).get("tier")
        )
        assert tier != "X", f"tier='X' row leaked into broad /v1/programs/search: {row!r}"


def test_tier_x_row_filter_active_even_with_explicit_tier_param(
    client: TestClient, seeded_db: Path
) -> None:
    """Even if a caller passes `tier=X` explicitly via query param, the
    response must NOT surface tier='X' rows.

    The dynamic `tier IN (?)` placeholder + the `COALESCE(tier,'X')!='X'`
    quarantine gate together must enforce this — even if someone tries
    to opt-in to the quarantine bucket from outside.
    """
    unique_name = "テスト隔離プログラムTIERX_EXPLICIT_QUERY"
    unified_id = "UNI-test-tierx-explicit-query-1"
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        _insert_tier_x_row(
            conn,
            unified_id=unified_id,
            primary_name=unique_name,
            excluded=0,
        )
    finally:
        conn.close()

    # Try to explicitly opt-in to tier=X (must be rejected by validation
    # OR yield zero results — either is acceptable as long as no X row
    # is surfaced).
    r = client.get("/v1/programs/search", params={"q": unique_name, "tier": "X", "limit": 50})
    # The endpoint may either reject the request with 422 (validation)
    # or accept it but return zero matching rows. Either is a "safe" response.
    if r.status_code == 200:
        body = r.json()
        rows = body.get("results") or body.get("items") or []
        leaked = [
            row
            for row in rows
            if isinstance(row, dict)
            and (row.get("unified_id") == unified_id or row.get("tier") == "X")
        ]
        assert not leaked, f"explicit `tier=X` query surfaced quarantined row: {leaked!r}"
    else:
        # 422 (FastAPI validation) is the strictest outcome and also acceptable.
        assert r.status_code in (400, 422), (
            f"unexpected status code {r.status_code} for explicit tier=X query: {r.text}"
        )
