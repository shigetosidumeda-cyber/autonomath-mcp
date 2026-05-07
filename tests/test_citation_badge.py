"""DEEP-27 citation badge widget tests (CL-08).

8 cases covering `widget/badge.svg`, `citation/{request_id}`, and the
in-process scrubber + aggregator + LLM-0 invariants:

  1. Migration applies idempotently — wave24_183 produces
     `citation_log` with the 4-state CHECK constraint, re-running on
     the same handle is a no-op.
  2. SVG generation in all 4 states — `verified` / `expired` /
     `invalid` / `boundary_warn`.
  3. Static MD page renders an existing row with the receipt /
     identity_confidence / lineage / audit_seal blocks.
  4. TTL expiry — a row 91 days old renders as `expired` even when
     `verified_status='verified'` is stored.
  5. Scrubber rejects PII — マイナンバー / 電話 / email / 番地 / カード番号
     are all redacted from `answer_text` before render.
  6. LLM API import 0 — `citation_badge.py` carries zero LLM SDK
     references on real code lines (docstrings excluded from scan).
  7. Aggregator URL reject — noukaweb.com etc. are stripped /
     struck-through both at insert filter and at render time.
  8. Snippet helper — `cite_html_snippet()` produces the exact 1-line
     HTML the customer pastes; the link target resolves to the same
     UUID that minted it.

Network is NEVER touched in this suite — the SVG + MD endpoints are
pure SQLite + string format.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
MIG_FORWARD = REPO_ROOT / "scripts" / "migrations" / "wave24_183_citation_log.sql"
MIG_ROLLBACK = REPO_ROOT / "scripts" / "migrations" / "wave24_183_citation_log_rollback.sql"
SRC_MODULE = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "citation_badge.py"


# ---------------------------------------------------------------------------
# Fixture — fresh in-memory autonomath handle with citation_log applied
# ---------------------------------------------------------------------------


@pytest.fixture()
def cit_db(tmp_path, monkeypatch):
    """Apply the wave24_183 migration into a tmp autonomath.db and
    re-point the citation_badge module at it.

    The fixture also re-imports the module so cached settings pick up
    the env var. Returns the path the module is now reading from.
    """
    db_path = tmp_path / "autonomath.db"
    sql = MIG_FORWARD.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    conn.executescript(sql)
    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    # Hot-swap the cached path on the citation_badge module if it's
    # already imported.
    mod = sys.modules.get("jpintel_mcp.api.citation_badge")
    if mod is not None:
        # Module reads env per-call; nothing to patch on the module
        # surface itself.
        pass

    return db_path


def _insert_row(
    db_path: Path,
    *,
    request_id: str,
    answer_text: str = "持続化補助金は最大50万円。",
    source_urls: str = '["https://www.meti.go.jp/example"]',
    verified_status: str = "verified",
    ttl_days: int = 90,
    created_at: str | None = None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    if created_at is None:
        conn.execute(
            "INSERT INTO citation_log (request_id, answer_text, source_urls, "
            "verified_status, ttl_days) VALUES (?, ?, ?, ?, ?)",
            (request_id, answer_text, source_urls, verified_status, ttl_days),
        )
    else:
        conn.execute(
            "INSERT INTO citation_log (request_id, answer_text, source_urls, "
            "verified_status, ttl_days, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                request_id,
                answer_text,
                source_urls,
                verified_status,
                ttl_days,
                created_at,
            ),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Case 1 — migration applies idempotently
# ---------------------------------------------------------------------------


def test_migration_applies_idempotently(tmp_path):
    sql = MIG_FORWARD.read_text(encoding="utf-8")
    assert sql.splitlines()[0].strip() == "-- target_db: autonomath", (
        "first line must be the target_db marker"
    )

    db_path = tmp_path / "am.db"
    conn = sqlite3.connect(str(db_path))
    # apply twice — idempotent
    conn.executescript(sql)
    conn.executescript(sql)
    conn.commit()

    # citation_log exists
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='citation_log'"
    ).fetchall()
    assert len(rows) == 1

    # CHECK constraint enforces the 4-state enum
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO citation_log (request_id, source_urls, "
            "verified_status) VALUES (?, '[]', 'pending')",
            (uuid.uuid4().hex,),
        )

    # rollback companion drops the table cleanly
    rb_sql = MIG_ROLLBACK.read_text(encoding="utf-8")
    conn.executescript(rb_sql)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='citation_log'"
    ).fetchall()
    assert rows == []
    conn.close()


# ---------------------------------------------------------------------------
# Case 2 — SVG generation in all 4 states
# ---------------------------------------------------------------------------


def test_svg_renders_four_states():
    from jpintel_mcp.api.citation_badge import (
        _STATE_COLORS,
        DISCLAIMER_JA,
        render_badge_svg,
    )

    for state in ("verified", "expired", "invalid", "boundary_warn"):
        svg = render_badge_svg(state)
        assert "<svg" in svg
        assert 'width="120"' in svg and 'height="20"' in svg
        assert _STATE_COLORS[state]["bg"] in svg
        assert _STATE_COLORS[state]["value"] in svg
        # disclaimer envelope rides in <title> for tooltip + a11y
        assert DISCLAIMER_JA in svg

    # an unknown state coerces to invalid (fence)
    coerced = render_badge_svg("totally_made_up")
    assert _STATE_COLORS["invalid"]["bg"] in coerced


# ---------------------------------------------------------------------------
# Case 3 — static MD page renders a row with all blocks
# ---------------------------------------------------------------------------


def test_citation_md_renders_row(cit_db):
    from jpintel_mcp.api import citation_badge as cb

    rid = uuid.uuid4().hex
    _insert_row(cit_db, request_id=rid)
    row = cb._fetch_row(rid)
    assert row is not None

    md = cb.render_citation_md(
        request_id=rid,
        row=row,
        identity_confidence=0.873,
        amendment_lineage=[
            {"effective_from": "2025-04-01", "summary": "持続化 v3 開始"},
        ],
        source_receipt={
            "sources": [
                {
                    "url": "https://www.meti.go.jp/example",
                    "retrieved_at": "2026-05-07T00:00:00Z",
                    "content_hash": "deadbeef" * 8,
                }
            ]
        },
        audit_seal={
            "call_id": "01HW2J3ABCDEFGHJKMNPQRSTVW",
            "ts": "2026-05-07T00:00:00+00:00",
            "query_hash": "a" * 64,
            "response_hash": "b" * 64,
            "hmac": "c" * 64,
        },
    )
    assert "# jpcite citation" in md
    assert rid in md
    assert "verified_status" in md
    assert "持続化補助金" in md
    assert "https://www.meti.go.jp/example" in md
    assert "0.873" in md
    assert "持続化 v3 開始" in md
    assert "deadbeef" in md
    assert "01HW2J3ABCDEFGHJKMNPQRSTVW" in md
    assert "DEEP-25" in md  # Verify-this-citation block

    # invalid path renders link-safe
    invalid_md = cb.render_citation_md(request_id=uuid.uuid4().hex, row=None)
    assert "invalid" in invalid_md.lower()
    assert "request_id" in invalid_md


# ---------------------------------------------------------------------------
# Case 4 — TTL expiry forces `expired` even when row says `verified`
# ---------------------------------------------------------------------------


def test_ttl_flips_to_expired(cit_db):
    from jpintel_mcp.api import citation_badge as cb

    rid = uuid.uuid4().hex
    old = (datetime.now(UTC) - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_row(
        cit_db,
        request_id=rid,
        verified_status="verified",
        ttl_days=90,
        created_at=old,
    )

    row = cb._fetch_row(rid)
    assert row is not None
    assert row["verified_status"] == "verified"
    state = cb._ttl_status(row)
    assert state == "expired", "row >ttl_days must render as expired"

    # fresh row stays verified
    rid2 = uuid.uuid4().hex
    _insert_row(cit_db, request_id=rid2)
    row2 = cb._fetch_row(rid2)
    assert cb._ttl_status(row2) == "verified"


# ---------------------------------------------------------------------------
# Case 5 — scrubber redacts PII patterns
# ---------------------------------------------------------------------------


def test_scrubber_redacts_pii():
    from jpintel_mcp.api.citation_badge import (
        has_forbidden_phrase,
        scrub,
    )

    raw = (
        "問い合わせは tax@example.co.jp / 03-1234-5678 まで。"
        "マイナンバー 123456789012 は 4111-1111-1111-1111 のカードに紐付く。"
        "東京都文京区小日向2-22-1 で受付。"
    )
    out = scrub(raw)
    assert "tax@example.co.jp" not in out
    assert "[email]" in out
    assert "[電話番号]" in out
    assert "[マイナンバー]" in out
    assert "[カード番号]" in out
    assert "[番地]" in out
    # 13 桁 houjin (public NTA) and 都道府県 names stay untouched
    bare_houjin = "T8010001213708"
    out2 = scrub(f"請求書発行事業者 {bare_houjin}")
    assert bare_houjin in out2
    out3 = scrub("東京都文京区で開催")
    assert "東京都" in out3 and "文京区" in out3

    # forbidden_phrase detection
    assert has_forbidden_phrase("確実に採択されます。")
    assert has_forbidden_phrase("100%採択を保証します")
    assert not has_forbidden_phrase("一般的な情報です。")


# ---------------------------------------------------------------------------
# Case 6 — LLM API import = 0
# ---------------------------------------------------------------------------


def test_llm_api_imports_zero():
    text = SRC_MODULE.read_text(encoding="utf-8")
    no_comments = re.sub(r"#[^\n]*", "", text)
    no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", no_comments)
    no_docstrings = re.sub(r"'''(?:.|\n)*?'''", "", no_docstrings)
    forbidden = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    )
    hits = [t for t in forbidden if t in no_docstrings]
    assert hits == [], f"LLM SDK references must be 0; found: {hits}"


# ---------------------------------------------------------------------------
# Case 7 — aggregator URL reject
# ---------------------------------------------------------------------------


def test_aggregator_url_reject(cit_db):
    from jpintel_mcp.api import citation_badge as cb

    # Filter helper rejects
    cleaned = cb.reject_aggregator_urls(
        [
            "https://noukaweb.com/article/123",
            "https://www.meti.go.jp/policy/x",
            "https://hojyokin-portal.jp/article/5",
            "https://www.nta.go.jp/taxes/x.htm",
        ]
    )
    assert "https://www.meti.go.jp/policy/x" in cleaned
    assert "https://www.nta.go.jp/taxes/x.htm" in cleaned
    for banned in (
        "https://noukaweb.com/article/123",
        "https://hojyokin-portal.jp/article/5",
    ):
        assert banned not in cleaned

    # Defense-in-depth: even if an aggregator slips into the row's
    # source_urls, the MD render strikes it through and never surfaces
    # it as a clean link.
    rid = uuid.uuid4().hex
    _insert_row(
        cit_db,
        request_id=rid,
        source_urls='["https://noukaweb.com/sneaky", "https://www.meti.go.jp/ok"]',
    )
    row = cb._fetch_row(rid)
    md = cb.render_citation_md(request_id=rid, row=row)
    assert "noukaweb.com" in md  # surfaced as struck-through
    assert "aggregator" in md.lower()
    assert "https://www.meti.go.jp/ok" in md


# ---------------------------------------------------------------------------
# Case 8 — snippet helper produces a valid 1-line link
# ---------------------------------------------------------------------------


def test_cite_html_snippet():
    from jpintel_mcp.api.citation_badge import cite_html_snippet, mint_request_id

    rid = mint_request_id()
    snippet = cite_html_snippet(rid)
    # 1 line, anchor + img, badge URL points at widget.jpcite.com,
    # citation URL points at jpcite.com/citation/{rid}
    assert snippet.count("\n") == 0
    assert f"https://jpcite.com/citation/{rid}" in snippet
    assert f"https://widget.jpcite.com/badge.svg?request_id={rid}" in snippet
    assert 'data-jpcite-verified="true"' in snippet
    assert 'alt="jpcite verified"' in snippet
    assert 'width="120"' in snippet and 'height="20"' in snippet
