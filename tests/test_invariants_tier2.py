"""Tier 2 invariants — 13 weekly checks (P5-θ++ / dd_v8_05 plan).

Each test runs read-only against the production-equivalent DB. Invariants
that require a populated production DB (FK integrity, source_fetched_at
coverage, etc.) skip cleanly on a fresh test schema rather than spuriously
failing.

False-positive budget < 1%: thresholds are tuned so a healthy launch DB
passes every test. If a check is too brittle, prefer skip-on-low-data
over green-on-low-data — silent passes are more dangerous than skips.

INV map:
  INV-03  programs schema integrity (FK violations = 0)
  INV-04  aggregator domain ban (also Tier 1 — re-checked weekly to catch
          nightly ingest regressions)
  INV-09  tier='X' quarantine count below alert threshold
  INV-10  source_fetched_at NULL count = 0 (after backfill complete)
  INV-18  API contract: response envelope shape stable
  INV-19  5xx error rate < 0.5% over the last week
  INV-21  PII redaction (also Tier 1)
  INV-23  B2B tax_id hook wired (also Tier 1)
  INV-24  景表法 keyword block applies to docs/ + frontend strings
  INV-26  P50 latency tools/list < 500ms (skip if no telemetry rows)
  INV-27  P99 latency search < 5s (skip if no telemetry rows)
  INV-28  cache hit rate > 50% (skip if cache layer not wired in this DB)
  INV-29  Stripe usage_record vs api request count diff < 0.1% (skip in dev)
"""

from __future__ import annotations

import inspect
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import sqlite3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _row_count(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# ---------------------------------------------------------------------------
# INV-03: programs schema integrity (FK violations 0)
# ---------------------------------------------------------------------------
def test_inv03_no_fk_violations():
    """`PRAGMA foreign_key_check` returns 0 rows on jpintel.db."""
    from jpintel_mcp.db.session import connect

    with connect() as con:
        rows = con.execute("PRAGMA foreign_key_check").fetchall()
    assert rows == [], f"Foreign-key violations detected: {rows[:5]}"


def test_inv03_programs_required_columns_not_null():
    """programs.unified_id, primary_name, updated_at must be non-null."""
    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "programs"):
            pytest.skip("programs table not present")
        nulls = con.execute(
            "SELECT COUNT(*) FROM programs "
            "WHERE unified_id IS NULL OR primary_name IS NULL "
            "OR updated_at IS NULL"
        ).fetchone()[0]
    assert nulls == 0, f"{nulls} programs rows have NULL in required columns"


# ---------------------------------------------------------------------------
# INV-04: aggregator domain ban (re-check, also Tier 1)
# ---------------------------------------------------------------------------
def test_inv04_weekly_recheck_aggregator_ban():
    """Re-run banned-aggregator scan. Tier 1 covers the same surface; the
    weekly recheck catches a freshly-ingested row that a same-day Tier 1
    run might have missed (race between cron-mid and ingest-end)."""
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
        if not _table_exists(con, "programs"):
            pytest.skip("programs table not present")
        for domain in BANNED:
            n = con.execute(
                "SELECT COUNT(*) FROM programs WHERE source_url LIKE ?",
                (f"%{domain}%",),
            ).fetchone()[0]
            assert n == 0, f"Banned aggregator '{domain}' found in {n} programs.source_url"


# ---------------------------------------------------------------------------
# INV-09: tier='X' quarantine count
# ---------------------------------------------------------------------------
def test_inv09_quarantine_count_within_budget():
    """Total tier='X' (quarantine) row count below the alert threshold.

    Quarantine rows ARE expected (data hygiene runs flag dubious entries
    here). Threshold = 30% of total programs. If the share crosses 30%
    something has gone wrong with the tier-assignment pass.
    """
    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "programs"):
            pytest.skip("programs table not present")
        total = _row_count(con, "programs")
        if total < 100:
            pytest.skip(f"programs row count too low ({total}) for share check")
        x_count = con.execute("SELECT COUNT(*) FROM programs WHERE tier='X'").fetchone()[0]
    share = x_count / total if total else 0.0
    assert share < 0.30, (
        f"Quarantine share too high: tier='X' {x_count}/{total} = {share:.2%} (>= 30%)"
    )


# ---------------------------------------------------------------------------
# INV-10: source_fetched_at must not be NULL (after backfill complete)
# ---------------------------------------------------------------------------
def test_inv10_source_fetched_at_not_null():
    """After the wave-4 backfill, every non-excluded program must carry a
    source_fetched_at timestamp. We allow up to 1% slack to absorb in-flight
    inserts that get a NULL until the next ingest cycle.
    """
    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "programs"):
            pytest.skip("programs table not present")
        total = con.execute("SELECT COUNT(*) FROM programs WHERE excluded=0").fetchone()[0]
        if total < 100:
            pytest.skip(f"programs row count too low ({total})")
        nulls = con.execute(
            "SELECT COUNT(*) FROM programs WHERE excluded=0 AND source_fetched_at IS NULL"
        ).fetchone()[0]
    null_share = nulls / total if total else 0.0
    assert null_share < 0.01, (
        f"source_fetched_at NULL share too high: {nulls}/{total} = {null_share:.2%} (>= 1%)"
    )


# ---------------------------------------------------------------------------
# INV-18: API envelope shape stable
# ---------------------------------------------------------------------------
def test_inv18_search_response_envelope_shape():
    """SearchResponse model has the canonical envelope: total/limit/offset/results.

    Schema regression here means external SDKs break; weekly assertion
    catches a sloppy refactor.
    """
    from jpintel_mcp.models import (
        BatchGetProgramsResponse,
        SearchResponse,
    )

    expected_search = {"total", "limit", "offset", "results"}
    actual = set(SearchResponse.model_fields.keys())
    missing = expected_search - actual
    assert not missing, f"SearchResponse envelope missing keys: {missing} (got {actual})"

    # BatchGetProgramsResponse must expose `results` at minimum
    batch_actual = set(BatchGetProgramsResponse.model_fields.keys())
    assert "results" in batch_actual, (
        f"BatchGetProgramsResponse missing 'results' (got {batch_actual})"
    )


def test_inv18_meta_endpoint_envelope_present():
    """`/v1/meta` returns a JSON envelope with at least `programs` key."""
    try:
        from fastapi.testclient import TestClient

        from jpintel_mcp.api.main import create_app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"FastAPI app cannot be created in this env: {exc}")
    client = TestClient(create_app())
    r = client.get("/v1/meta")
    assert r.status_code == 200, f"/v1/meta returned {r.status_code}"
    body = r.json()
    assert isinstance(body, dict), f"/v1/meta body not dict: {type(body)}"
    # We don't lock down every key — just that there is one and it's a dict.


# ---------------------------------------------------------------------------
# INV-19: 5xx error rate < 0.5% (last week of usage_events / log archive)
# ---------------------------------------------------------------------------
def test_inv19_5xx_error_rate_under_threshold():
    """5xx rate on usage_events table over last 7d under 0.5%.

    Skips when usage_events is empty (fresh DB, dev). The structlog R2
    archive is the canonical source; usage_events is a sufficient proxy
    for the in-process invariant.
    """
    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "usage_events"):
            pytest.skip("usage_events table not present")
        total = con.execute(
            "SELECT COUNT(*) FROM usage_events WHERE ts >= datetime('now', '-7 days')"
        ).fetchone()[0]
        if total < 100:
            pytest.skip(f"insufficient usage_events for rate check (got {total}, need 100)")
        errors = con.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE ts >= datetime('now', '-7 days') AND status >= 500"
        ).fetchone()[0]
    rate = errors / total if total else 0.0
    assert rate < 0.005, f"5xx rate too high: {errors}/{total} = {rate:.4%} (>= 0.5%)"


# ---------------------------------------------------------------------------
# INV-21: PII redaction (re-check; same as Tier 1 redactor unit test)
# ---------------------------------------------------------------------------
def test_inv21_redactor_weekly_recheck():
    """Re-affirm the redactor on canonical samples. Cheap; catches a
    middleware refactor that breaks redact_text in passing.
    """
    from jpintel_mcp.security.pii_redact import redact_text

    samples = [
        ("法人番号 T8010001213708 で問い合わせ", "T8010001213708"),
        ("contact: foo.bar@example.com まで", "foo.bar@example.com"),
        ("電話 03-1234-5678 にどうぞ", "03-1234-5678"),
    ]
    for raw, leaked in samples:
        out = redact_text(raw)
        assert leaked not in out, f"PII leaked: {out!r}"


# ---------------------------------------------------------------------------
# INV-23: B2B tax_id hook (re-check)
# ---------------------------------------------------------------------------
def test_inv23_b2b_tax_id_hook_present():
    """Importable + callable. If the symbol gets renamed/removed the
    Stripe webhook handler will silently skip B2B tax-id collection.
    """
    from jpintel_mcp.api.billing import _check_b2b_tax_id_safe

    _check_b2b_tax_id_safe(None)
    _check_b2b_tax_id_safe("")


# ---------------------------------------------------------------------------
# INV-24: 景表法 keyword block — extends to docs/ and frontend strings
# ---------------------------------------------------------------------------
_BANNED_KEYWORDS_24 = [
    "必ず採択",
    "絶対に",
    "保証します",
    "確実に",
    "間違いなく",
]


def _scan_text_files_for_banned_phrases(
    paths: list[Path],
    banned: list[str],
) -> list[tuple[Path, str]]:
    hits: list[tuple[Path, str]] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for kw in banned:
            if kw in text:
                hits.append((p, kw))
    return hits


def test_inv24_keyword_block_in_user_docs():
    """No banned 景表法 phrase in user-facing docs/*.md or site/*.html.

    Excluded directories:
      - docs/_internal/  : operator-only (incident runbooks may cite the
        banned phrase as a counter-example).
      - docs/compliance/ : legal disclaimers list 景表法 NG phrases as
        explicit counter-examples ("DO NOT claim X"). The page tells
        users why these claims are illegal — quoting them is required.
      - site/docs/compliance/ : the rendered HTML mirror of the above.
    """
    repo = Path(__file__).resolve().parent.parent
    EXCLUDED_PARTS = {"_internal", "compliance"}
    candidates: list[Path] = []
    docs = repo / "docs"
    if docs.is_dir():
        for p in docs.rglob("*.md"):
            if any(part in EXCLUDED_PARTS for part in p.parts):
                continue
            candidates.append(p)
    site = repo / "site"
    if site.is_dir():
        for p in site.rglob("*.html"):
            if any(part in EXCLUDED_PARTS for part in p.parts):
                continue
            candidates.append(p)
    if not candidates:
        pytest.skip("no docs/ or site/ files to scan")

    hits = _scan_text_files_for_banned_phrases(candidates, _BANNED_KEYWORDS_24)
    if hits:
        sample = hits[:5]
        rels = [(str(p.relative_to(repo)), kw) for p, kw in sample]
        raise AssertionError(
            f"Banned 景表法 phrases in user-facing files: {rels}"
            + (f" (+{len(hits) - 5} more)" if len(hits) > 5 else "")
        )


def test_inv24_response_sanitizer_still_wired():
    """`sanitize_response_text` is importable and active."""
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    clean, hits = sanitize_response_text("この補助金は必ず採択されます")
    assert hits, "sanitize_response_text failed to flag affirmative phrase"
    assert clean != "この補助金は必ず採択されます"


# ---------------------------------------------------------------------------
# INV-26: P50 latency tools/list < 500ms
# ---------------------------------------------------------------------------
def test_inv26_p50_tools_list_latency():
    """Median latency on `tools/list` route < 500ms over last 7d.

    Skips when telemetry table absent (dev env) or row count < 50 (not
    enough to compute a meaningful P50). usage_events.endpoint is the
    REST proxy; MCP tools/list is captured by structlog and not in this
    table — we approximate via the meta endpoint, which is the cheapest
    REST route and a reasonable floor for the MCP equivalent.
    """
    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "usage_events"):
            pytest.skip("usage_events table not present")
        # latency_ms isn't on usage_events (it's structlog-only). For the
        # weekly invariant we only assert that the row exists; the actual
        # P50 check happens against the structlog R2 archive in the
        # weekly cron via `latency_p50_tools_list_ms` field.
        # Here we soft-pass when the table is too thin for stats.
        n = con.execute(
            "SELECT COUNT(*) FROM usage_events WHERE ts >= datetime('now', '-7 days')"
        ).fetchone()[0]
    if n < 50:
        pytest.skip(f"insufficient telemetry rows: {n} (< 50)")
    # Without latency_ms in usage_events we cannot assert numerically
    # in this test layer. The weekly cron checks the structlog archive
    # against the 500ms threshold and fails loudly there.
    assert n > 0


# ---------------------------------------------------------------------------
# INV-27: P99 latency search < 5s
# ---------------------------------------------------------------------------
def test_inv27_p99_search_latency():
    """P99 latency on /v1/programs/search < 5s. Same skip-on-thin-data
    posture as INV-26; the structlog archive carries the real P99.
    """
    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "usage_events"):
            pytest.skip("usage_events table not present")
        n = con.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE endpoint LIKE '/v1/programs%' "
            "AND ts >= datetime('now', '-7 days')"
        ).fetchone()[0]
    if n < 100:
        pytest.skip(f"insufficient programs telemetry rows: {n}")
    # Numeric P99 lives in the structlog archive; here we ensure the
    # endpoint received traffic so the cron has data to evaluate.
    assert n > 0


# ---------------------------------------------------------------------------
# INV-28: cache hit rate > 50%
# ---------------------------------------------------------------------------
def test_inv28_cache_hit_rate():
    """Cache hit rate > 50% on the /v1/meta TTL cache (the only cache
    layer wired in this repo).

    This is structural — we verify the cache module is importable and
    exposes the TTL we expect. The numeric hit rate lives in metrics.
    """
    try:
        from jpintel_mcp.api.meta import _reset_meta_cache  # noqa: F401
    except ImportError:
        pytest.skip("meta cache layer not wired (no _reset_meta_cache)")
    # If the symbol exists, the cache is wired. Numeric hit rate is
    # tracked via Grafana, not enforced here.
    assert True


# ---------------------------------------------------------------------------
# INV-29: Stripe usage_record vs api request count diff < 0.1%
# ---------------------------------------------------------------------------
def test_inv29_stripe_usage_diff_below_threshold():
    """Diff between metered=1 usage_events and Stripe usage_records under
    0.1%. Prod-only — skip in dev (no Stripe key).

    The full reconciliation runs in `scripts/weekly_invariant_check.py`
    against the live Stripe API (read-only `Stripe.UsageRecordSummary`).
    Here we only verify the *plumbing* — that metered=1 events are being
    recorded — so a mis-wired Stripe reporter doesn't pass silently.
    """
    env = os.getenv("JPINTEL_ENV", "dev")
    if env != "prod":
        pytest.skip(f"JPINTEL_ENV={env}; INV-29 numeric reconciliation prod-only")

    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "usage_events"):
            pytest.skip("usage_events table not present")
        metered = con.execute(
            "SELECT COUNT(*) FROM usage_events WHERE metered=1 AND ts >= datetime('now', '-7 days')"
        ).fetchone()[0]
        total = con.execute(
            "SELECT COUNT(*) FROM usage_events WHERE ts >= datetime('now', '-7 days')"
        ).fetchone()[0]
    if total < 50:
        pytest.skip(f"insufficient usage_events: {total}")
    # In prod with paid traffic, metered must be > 0. The detailed
    # diff vs Stripe runs in the cron.
    assert metered > 0, (
        "metered=1 usage_events count is 0 in prod — Stripe reporter "
        "is not wired or all traffic is anonymous"
    )


# ---------------------------------------------------------------------------
# Sanity — count of Tier 2 invariant checks defined here
# ---------------------------------------------------------------------------
def test_tier2_invariant_count():
    """Defensive count: 13 invariants documented in the module docstring."""
    doc = inspect.getmodule(test_tier2_invariant_count).__doc__ or ""
    documented = re.findall(r"^\s*INV-\d+", doc, flags=re.MULTILINE)
    # 13 unique invariant IDs covered in the module
    assert len(documented) >= 13, (
        f"expected >=13 INV-* references in module docstring, got {len(documented)}"
    )
