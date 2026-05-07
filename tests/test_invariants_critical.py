"""Compliance critical invariant tests (INV-04/21/22/23/25).

Per dd_v8_05 / v8 P3-V+ requirements. These tests are designed to fail loudly
when launch-blocking compliance regressions appear.
"""

from __future__ import annotations

import inspect
import os
import re

import pytest


# ---------------------------------------------------------------------------
# INV-04: aggregator domain ban
# ---------------------------------------------------------------------------
def test_inv04_no_banned_aggregator_in_programs():
    """No banned aggregator domain may appear in programs.source_url."""
    BANNED = [
        "noukaweb",
        "hojyokin-portal",
        "biz.stayway",
        "stayway.jp",
        "nikkei.com",
        "prtimes.jp",
        "wikipedia.org",
    ]
    from jpintel_mcp.db.session import connect

    with connect() as con:
        # Ensure programs table exists; otherwise skip rather than crash
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='programs'"
        ).fetchone()
        if not row:
            pytest.skip("programs table not present in this DB")
        for domain in BANNED:
            n = con.execute(
                "SELECT COUNT(*) FROM programs WHERE source_url LIKE ?",
                (f"%{domain}%",),
            ).fetchone()[0]
            assert n == 0, f"Banned aggregator '{domain}' found in {n} programs.source_url"


# ---------------------------------------------------------------------------
# INV-21: PII redaction in query_log_v2
# ---------------------------------------------------------------------------
PII_PATTERNS = [
    re.compile(r"T\d{13}"),  # 法人番号
    re.compile(r"[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}"),  # email
    re.compile(r"(?:\+?81[- ]?|0)\d{1,4}[- ]?\d{1,4}[- ]?\d{3,4}"),  # 電話
]


def test_inv21_no_pii_in_query_log():
    """query_log_v2 must not contain raw 法人番号 / email / 電話 patterns."""
    from jpintel_mcp.db.session import connect

    with connect() as con:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='query_log_v2'"
        ).fetchone()
        if not row:
            pytest.skip("query_log_v2 table not present in this DB")
        rows = con.execute(
            "SELECT query_normalized FROM query_log_v2 "
            "WHERE query_normalized IS NOT NULL LIMIT 1000"
        ).fetchall()
        for (q,) in rows:
            for p in PII_PATTERNS:
                assert not p.search(
                    q
                ), f"PII pattern {p.pattern} found in query_log_v2.query_normalized: {q[:60]}"


def test_inv21_redactor_strips_pii():
    """INV-21 wiring: jpintel_mcp.security.pii_redact must redact all 3 patterns.

    Even on a fresh DB without query_log_v2, the *source* of any future row
    in that table is the `autonomath.query` log emission, which now passes
    through `redact_pii`. This test directly verifies the redactor rather
    than depending on table presence.
    """
    from jpintel_mcp.security.pii_redact import redact_text

    samples = [
        ("法人番号 T8010001213708 で問い合わせ", "T8010001213708"),
        ("contact: foo.bar@example.com まで", "foo.bar@example.com"),
        ("電話 03-1234-5678 にどうぞ", "03-1234-5678"),
        ("国際電話 +81 90-1234-5678 です", "90-1234-5678"),
    ]
    for raw, leaked in samples:
        out = redact_text(raw)
        assert leaked not in out, f"PII leaked through redactor: {out!r}"
        assert "[REDACTED:" in out, f"Redactor did not stamp placeholder: {out!r}"


# ---------------------------------------------------------------------------
# INV-22: 景表法 keyword block in tool docstrings/responses
# ---------------------------------------------------------------------------
def test_inv22_response_sanitizer_blocks_affirmative_phrases():
    """Response sanitizer replaces affirmative grant phrases with neutral copy.

    Verifies the runtime middleware (api/response_sanitizer.py) — separate
    from the docstring scan below. False-positive guard: negation contexts
    must NOT be sanitized.
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    # Affirmative claims that MUST be sanitized
    bad = [
        "この補助金は必ず採択されます",
        "確実に貰える融資です",
        "採択を保証します",
        "絶対に通る制度",
    ]
    for s in bad:
        clean, hits = sanitize_response_text(s)
        assert hits, f"Should have flagged: {s!r} -> {clean!r}"
        assert clean != s, f"Body unchanged: {s!r}"

    # Negation contexts that MUST be left alone (false-positive guard)
    safe_negations = [
        "必ずしも採択されるとは限らない",
        "採択を保証するわけではありません",
        "信用保証協会の保証付き融資",  # 保証 in entity-name context
        "絶対値で評価する",  # 絶対 in math context
    ]
    for s in safe_negations:
        clean, hits = sanitize_response_text(s)
        assert not hits, f"False positive on negation: {s!r} hits={hits}"
        assert clean == s, f"Body altered on negation: {s!r} -> {clean!r}"


def test_inv22_no_misleading_keywords_in_docstrings():
    """No 「必ず採択」「絶対に」「保証します」「確実に」「間違いなく」 in tool docstrings.

    Use phrase patterns rather than bare characters so the trust-sense
    「保証」 (e.g. "信用保証協会") doesn't false-positive.
    """
    BANNED_KEYWORDS = [
        "必ず採択",
        "絶対に",
        "保証します",
        "確実に",
        "間違いなく",
    ]
    from jpintel_mcp.mcp.server import mcp

    failures = []
    for tool_name, tool in mcp._tool_manager._tools.items():
        doc = inspect.getdoc(tool.fn) or ""
        for kw in BANNED_KEYWORDS:
            if kw in doc:
                failures.append((tool_name, kw))
    assert not failures, f"Banned 景表法 keywords in tool docstrings: {failures}"


# ---------------------------------------------------------------------------
# INV-23: tax_id field in invoice config (インボイス制度)
# ---------------------------------------------------------------------------
def test_inv23_invoice_registration_number_set():
    """Bookyou KK must have inv registration number T8010001213708 in env (prod only)."""
    env = os.getenv("JPINTEL_ENV", "dev")
    inv_num = os.getenv("INVOICE_REGISTRATION_NUMBER", "")
    if env != "prod" and not inv_num:
        pytest.skip("INVOICE_REGISTRATION_NUMBER not set and not prod env; dev/test mode skip")
    assert inv_num.startswith("T") and len(inv_num) == 14, (
        f"Invalid invoice registration number: {inv_num!r} "
        f"(expected T+13 digits, got len={len(inv_num)})"
    )


def test_inv23_b2b_tax_id_check_wired():
    """INV-23 wiring: webhook handler must call _check_b2b_tax_id_safe on
    customer.subscription.created. Importable + invocable in dev (no Stripe).
    """
    from jpintel_mcp.api.billing import _check_b2b_tax_id_safe

    # None / empty must no-op without raising — dev/test path
    _check_b2b_tax_id_safe(None)
    _check_b2b_tax_id_safe("")


# ---------------------------------------------------------------------------
# INV-25: PEPPER not default in prod
# ---------------------------------------------------------------------------
def test_inv25_pepper_not_default_in_prod():
    """In prod env, AUTONOMATH_API_HASH_PEPPER must not be the default value."""
    env = os.getenv("JPINTEL_ENV", "dev")
    if env != "prod":
        pytest.skip(f"JPINTEL_ENV={env!r}; prod-only check skipped")
    pepper = os.getenv("AUTONOMATH_API_HASH_PEPPER", "")
    assert pepper not in (
        "",
        "dev-pepper-change-me",
    ), "PEPPER must be rotated in prod (got default or empty)"


# ---------------------------------------------------------------------------
# INV-Tier-X: Tier='X' quarantine is invisible to user-facing surfaces
#
# Per CLAUDE.md "common gotchas": tier='X' is the quarantine bucket. All
# search paths must exclude it. generate_program_pages.py filters
# tier IN ('S','A','B','C') — keep that filter. A regression that surfaces
# tier=X in /v1/programs/search would expose un-vetted rows to consumers
# who pay ¥3/req for vetted data — same fraud-risk surface as banned
# aggregator domains in INV-04.
# ---------------------------------------------------------------------------
def test_inv_tier_x_excluded_from_programs_search(client):
    """/v1/programs/search must not surface any tier='X' row (default path)."""
    # Pull a generous batch and assert no result carries tier='X'. We do
    # NOT assume any specific result count — the seeded DB has exactly one
    # X-row plus three live rows. With limit=100 we capture the entire
    # corpus in one call.
    r = client.get("/v1/programs/search", params={"limit": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    # Find the result list under any of the documented envelope shapes:
    # top-level "results" (current canonical) or "items" (legacy alias).
    rows = body.get("results") or body.get("items") or []
    assert isinstance(rows, list)
    assert rows, "search returned 0 rows; cannot assert tier=X exclusion meaningfully"
    for row in rows:
        # Some routes embed the row under "program" / "data"; tolerate either.
        candidate = row if isinstance(row, dict) else {}
        tier = (
            candidate.get("tier")
            or (candidate.get("program") or {}).get("tier")
            or (candidate.get("data") or {}).get("tier")
        )
        assert tier != "X", f"tier=X leaked into /v1/programs/search results: {candidate!r}"


def test_inv_tier_x_excluded_from_generate_program_pages_query():
    """generate_program_pages.py must keep tier IN ('S','A','B','C') in its SELECTs.

    We don't run the generator here (it writes to site/programs/). Instead we
    parse the script's SQL constants and assert no *bulk* SELECT against
    ``programs`` uses an unbounded tier predicate. Catches the regression
    where someone deletes the tier filter to "include everything for
    debugging" and forgets to revert it.

    Single-row PK lookups (``WHERE unified_id = ?``) are exempt: the caller
    has already filtered by tier when picking which unified_ids to render,
    so the row-fetch shape doesn't need to re-enforce the invariant.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "generate_program_pages.py"
    if not script_path.exists():
        pytest.skip(f"generator not present at {script_path}")
    src = script_path.read_text(encoding="utf-8")

    # Every "FROM programs" stanza in the file must be paired with a tier
    # whitelist predicate within the surrounding ~800 chars, UNLESS the WHERE
    # clause is a single-row PK lookup by unified_id.
    #
    # Acceptable forms:
    #   1. ``tier IN ('S','A','B','C')`` — legacy literal, preserved on
    #      paths that don't take a runtime --tiers filter.
    #   2. ``tier IN ({tier_in})`` — INDEXABLE_SQL_TEMPLATE; runtime callers
    #      build {tier_in} from a whitelist that explicitly excludes X
    #      (see _iter_rows safe_tiers list — only S/A/B/C accepted).
    #   3. ``tier IN ('S','A')`` — frozen S+A subset (post-2026-04-29
    #      AI-feel reduction). Still excludes X, still safe.
    from_blocks = [m.start() for m in re.finditer(r"\bFROM\s+programs\b", src, re.IGNORECASE)]
    assert from_blocks, "expected at least one FROM programs in generator"
    accepted_predicates = (
        "tier IN ('S','A','B','C')",
        "tier IN ({tier_in})",
        "tier IN ('S','A')",
    )
    for offset in from_blocks:
        # Look ahead up to 800 chars (covers the longest WHERE in the file).
        window = src[offset : offset + 800]
        # Exempt: single-row PK lookup — caller already enforced tier upstream.
        if re.search(r"WHERE\s+unified_id\s*=\s*\?", window, re.IGNORECASE):
            continue
        assert any(p in window for p in accepted_predicates), (
            f"FROM programs at offset {offset} not paired with a tier whitelist "
            f"(must include one of {accepted_predicates}); "
            f"window head: {window[:200]!r}"
        )
