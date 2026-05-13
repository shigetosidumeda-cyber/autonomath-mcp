"""Regression tests for the FTS5 query rewriter in
``src/jpintel_mcp/api/programs.py``.

The FTS5 trigram tokenizer has two sharp edges that the rewriter mitigates:

  1. **Single-kanji overlap false-positives.** ``税額控除`` shares the kanji
     ``税`` with ``ふるさと納税``; without phrase-quoting, FTS5 trigrams of the
     query (``税額控``, ``額控除``) can co-rank documents that mention only
     ``税`` somewhere in their long body text. The rewriter wraps 2+ char
     compound terms in FTS5 phrase syntax (``"..."``) so the trigrams must
     appear contiguously.
  2. **User-quoted phrases must be preserved.** A query like
     ``'"中小企業" 補助金'`` should treat ``中小企業`` as a single phrase
     token (NOT escape the quotes into the phrase literal as the prior
     implementation did, producing a triple-quote escaped phrase that
     FTS5 parses as a literal-string match).

The tests below pin both behaviors plus the edge cases called out in the
2026-04-29 fix audit:

  - ``q=""`` / whitespace / punctuation-only → empty result, never a corpus dump.
  - User-quoted phrases inside a multi-token query.
  - Mixed JA + EN, numbers, comma separators, FTS5-special chars.
  - Single-character katakana / kanji do not raise.
  - Idempotence: same input → same output.

If you change ``_build_fts_match`` or ``_tokenize_query`` you MUST keep these
green — they encode the trigram false-positive contract that is documented
in the public OpenAPI description.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.programs import (
    _build_fts_match,
    _is_pure_kanji,
    _tokenize_query,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Pure-function tests on _build_fts_match / _tokenize_query
# (No DB, no client — these run in <10ms each.)
# ---------------------------------------------------------------------------


class TestBuildFtsMatchPure:
    """Unit tests for the FTS5 MATCH expression builder. Pure functional."""

    def test_pure_kanji_compound_phrase_quoted(self) -> None:
        """``税額控除`` (4-char kanji compound) must be wrapped in
        FTS5 phrase-quote syntax. This is the core CLAUDE.md gotcha
        workaround: forces trigrams to appear contiguously."""
        out = _build_fts_match("税額控除")
        assert out == '"税額控除"', f"pure kanji compound was NOT phrase-quoted; got {out!r}"

    def test_two_char_kanji_phrase_quoted(self) -> None:
        """Two-char kanji (``農業``) is the threshold case from CLAUDE.md."""
        out = _build_fts_match("農業")
        assert out == '"農業"'

    def test_single_kanji_phrase_quoted(self) -> None:
        """Single kanji is still wrapped — phrase-quote on a 1-char string is
        a no-op for trigram (FTS5 returns 0 anyway), and the wrapper protects
        against accidental operator parsing."""
        out = _build_fts_match("税")
        assert out == '"税"'

    def test_two_char_ascii_phrase_quoted(self) -> None:
        """Pure-ASCII 2-char acronyms (``GX``, ``DX``) get phrase-quoted.
        The FTS path won't return rows for them anyway (trigram needs 3+
        chars), so the caller should route to LIKE — but the rewriter still
        emits a syntactically valid expression."""
        out = _build_fts_match("GX")
        assert out == '"GX"'

    def test_three_char_ascii_phrase_quoted(self) -> None:
        """3-char ASCII (``DX5``) is the FTS5 trigram minimum."""
        out = _build_fts_match("DX5")
        assert out == '"DX5"'

    def test_mixed_ja_en_split_and_anded(self) -> None:
        """``"GX 補助金"`` (mixed) splits on whitespace, each token is
        phrase-quoted, ANDed."""
        out = _build_fts_match("GX 補助金")
        # AND of two single tokens: both phrase-quoted.
        assert "GX" in out and "補助金" in out
        assert "AND" in out

    def test_three_token_mixed(self) -> None:
        """``"GX 中小企業 補助金"`` — three tokens AND'd."""
        out = _build_fts_match("GX 中小企業 補助金")
        assert out.count("AND") == 2
        assert "GX" in out
        assert "中小企業" in out
        assert "補助金" in out

    def test_user_quoted_phrase_preserved(self) -> None:
        # The user explicitly phrase-quoted DX in '"DX" 製造業'. We must
        # emit two separate phrase-quoted tokens AND'd, not a triple-quote
        # escape sequence. Prior implementation passed each whitespace-
        # split token through _fts_escape which doubled the user's quotes,
        # producing a literal-triple-quote phrase that FTS5 parses but
        # never matches.
        out = _build_fts_match('"DX" 製造業')
        assert '"""' not in out, f"triple-quote escape leaked into FTS expression: {out!r}"
        assert '"DX"' in out
        assert '"製造業"' in out
        assert "AND" in out

    def test_user_quoted_phrase_with_internal_space(self) -> None:
        """``'"中小企業 デジタル化"'`` — the user wants the whole thing as a
        phrase, internal space included. Tokenizer must NOT split on the
        space inside the user quote."""
        toks = _tokenize_query('"中小企業 デジタル化"')
        assert len(toks) == 1
        assert toks[0] == ("中小企業 デジタル化", True)
        out = _build_fts_match('"中小企業 デジタル化"')
        assert out == '"中小企業 デジタル化"'

    def test_user_quoted_disables_kana_expansion(self) -> None:
        """User-quoted ``"のうぎょう"`` is an explicit "exact phrase" signal —
        do NOT inject KANA_EXPANSIONS. Bare ``のうぎょう`` still expands."""
        bare = _build_fts_match("のうぎょう")
        # bare expands: original OR'd with KANA target
        assert "農業" in bare
        assert "OR" in bare
        # quoted: no expansion
        quoted = _build_fts_match('"のうぎょう"')
        assert quoted == '"のうぎょう"'
        assert "農業" not in quoted

    def test_punctuation_separator_japanese(self) -> None:
        """Comma (both ASCII ``,`` and 全角 ``、``) and similar punctuation
        is a token separator, NOT part of the token."""
        out = _build_fts_match("中小企業, 製造業")
        assert "," not in out, f"comma leaked into phrase literal: {out!r}"
        assert '"中小企業"' in out
        assert '"製造業"' in out

    def test_punctuation_separator_zenkaku(self) -> None:
        out = _build_fts_match("中小企業、製造業")
        assert "、" not in out, f"全角 comma leaked: {out!r}"
        assert "中小企業" in out and "製造業" in out

    def test_fts5_special_char_colon_stripped(self) -> None:
        """``:`` is FTS5 column-filter syntax; treat as separator."""
        out = _build_fts_match("税:制度")
        assert ":" not in out, f"colon leaked: {out!r}"
        assert '"税"' in out
        assert '"制度"' in out

    def test_fts5_special_char_paren_stripped(self) -> None:
        out = _build_fts_match("(税)")
        assert out == '"税"', f"unexpected: {out!r}"

    def test_fts5_special_char_asterisk_stripped(self) -> None:
        """``*`` is FTS5 prefix-wildcard; stripping it is safer than
        passing it through (a deliberate prefix query is out of scope —
        agents can use the dedicated tier filter for that)."""
        out = _build_fts_match("税*")
        assert "*" not in out
        assert '"税"' in out

    def test_punctuation_only_input_returns_empty(self) -> None:
        """``'**'`` / ``':;'`` / ``'(())'`` — no real content. Builder
        returns empty string so the caller can detect and skip the FTS
        path entirely (otherwise FTS5 raises ``syntax error near ""``)."""
        for q in ["**", ":;", "(())", ",,", "。。", "  ", ""]:
            out = _build_fts_match(q)
            assert out == "", f"q={q!r} should yield empty MATCH, got {out!r}"

    def test_nfkc_normalization_zenkaku_ascii(self) -> None:
        """Mac-IME / Word-paste produces 全角 ASCII (``ＩＴ``); NFKC folds
        these to half-width before tokenization. Ensures the resulting
        FTS expression matches half-width DB content."""
        out = _build_fts_match("ＩＴ導入補助金")
        assert "IT" in out  # NFKC'd
        assert "ＩＴ" not in out

    def test_nfkc_normalization_zenkaku_space(self) -> None:
        """全角 space (　) is folded to half-width by NFKC, so a
        zenkaku-spaced query splits on tokens correctly."""
        out = _build_fts_match("中小企業　補助金")
        assert "AND" in out
        assert "中小企業" in out
        assert "補助金" in out

    def test_double_quote_escape(self) -> None:
        """A double-quote that is NOT a phrase delimiter must be escaped
        as ``""`` per FTS5 phrase syntax. Triggered by an unbalanced or
        odd number of quotes."""
        # Unbalanced: a single trailing quote. The tokenizer treats it as
        # not opening a quoted phrase; the builder must still emit a
        # syntactically valid expression.
        raw_input = 'test"'
        out = _build_fts_match(raw_input)
        # We're permissive about the exact rendering — only require it
        # is a valid FTS expression that doesn't trip the parser.
        assert isinstance(out, str)
        # Exercise on a real FTS5 to confirm:
        conn = sqlite3.connect(":memory:")
        conn.execute('CREATE VIRTUAL TABLE t USING fts5(c, tokenize="trigram")')
        conn.execute("INSERT INTO t VALUES (?)", ("placeholder",))
        if out:  # only test if non-empty
            try:
                conn.execute("SELECT c FROM t WHERE t MATCH ?", (out,)).fetchall()
            except sqlite3.OperationalError as exc:
                pytest.fail(
                    f"_build_fts_match emitted unparseable FTS expression "
                    f"{out!r} for input {raw_input!r}: {exc}"
                )

    def test_idempotent(self) -> None:
        """Same input → same output. No global state, no clock, no random."""
        for q in [
            "税額控除",
            "GX 補助金",
            '"DX" 製造業',
            "中小企業, 製造業",
            "100億 補助金",
            "",
            "**",
            "のうぎょう",
        ]:
            assert _build_fts_match(q) == _build_fts_match(q)

    def test_long_input_does_not_crash(self) -> None:
        """Up to the API-layer 200-char cap, builder must not crash."""
        q = "中小企業 " * 30  # 30 tokens × 5 chars = 150 chars
        out = _build_fts_match(q)
        assert "AND" in out
        # All tokens should appear as phrase-quoted entries.
        assert out.count("中小企業") == 30


class TestTokenizeQuery:
    """Tokenizer is the seam between the user's free text and the FTS5
    builder. Pin the contract."""

    def test_empty_returns_empty_list(self) -> None:
        assert _tokenize_query("") == []
        assert _tokenize_query("   ") == []
        assert _tokenize_query("\t\n") == []

    def test_single_unquoted(self) -> None:
        assert _tokenize_query("税額控除") == [("税額控除", False)]

    def test_single_user_quoted(self) -> None:
        assert _tokenize_query('"税額控除"') == [("税額控除", True)]

    def test_mixed_unquoted_and_quoted(self) -> None:
        toks = _tokenize_query('"DX" 製造業')
        assert toks == [("DX", True), ("製造業", False)]

    def test_quoted_with_internal_space(self) -> None:
        toks = _tokenize_query('"中小企業 デジタル化"')
        assert toks == [("中小企業 デジタル化", True)]

    def test_punctuation_only(self) -> None:
        assert _tokenize_query("**") == []
        assert _tokenize_query(":;") == []
        assert _tokenize_query("(((") == []

    def test_drops_punctuation_inside_quote(self) -> None:
        """User-quoted ``"foo:bar"`` — the colon (FTS5 column-filter
        syntax) is stripped even inside the user quote, because passing
        it through would always raise on FTS5 evaluation."""
        toks = _tokenize_query('"foo:bar"')
        assert len(toks) == 1
        assert toks[0][0] == "foo bar" or toks[0][0] == "foobar" or ":" not in toks[0][0]


# ---------------------------------------------------------------------------
# End-to-end tests via TestClient
# These rely on the seeded DB from conftest.py; they augment it with rows
# targeted at the new rewriter behavior.
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
    """Mirror tests/test_search_relevance.py::_insert."""
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


@pytest.fixture(autouse=True)
def _reset_per_ip_endpoint_buckets() -> None:
    """Clear the 30 req/min per-IP cap on /v1/programs/search between
    tests. Without this, late tests in this module 429 because earlier
    tests in the suite (test_search_relevance, test_programs) already
    burned the testclient IP's quota. The conftest autouse only resets
    ``anon_rate_limit`` and the burst limiter — not the per-endpoint
    cap."""
    try:
        from jpintel_mcp.api.middleware.per_ip_endpoint_limit import (
            _reset_per_ip_endpoint_buckets as _r,
        )

        _r()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _cleanup_fts5_seeds(seeded_db: Path):
    """Remove any ``UNI-fts5-*`` rows after each test.

    ``seeded_db`` is session-scoped, so without cleanup the rows this
    module inserts pollute later tests in the run (test_meta in
    test_api.py asserts ``total_programs == 4`` against the original
    fixture). Clean up after every test so each FTS5 test starts from
    the same 4-row baseline as the rest of the suite."""
    yield
    try:
        c = sqlite3.connect(seeded_db)
        c.execute("DELETE FROM programs WHERE unified_id LIKE 'UNI-fts5-%'")
        c.execute("DELETE FROM programs_fts WHERE unified_id LIKE 'UNI-fts5-%'")
        c.commit()
        c.close()
    except sqlite3.Error:
        pass


@pytest.fixture()
def db_conn(seeded_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Spec-mandated 5 representative queries
# ---------------------------------------------------------------------------


def test_q_zeigaku_kojo_returns_tax_credit_rows_not_furusato(
    client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    """``q=税額控除`` must return programs whose primary_name carries the
    phrase ``税額控除``, NOT ふるさと納税-only rows that share only the
    single kanji ``税``. Dual seed: a true tax-credit hit AND a
    ふるさと納税 decoy."""
    _insert(
        db_conn,
        unified_id="UNI-fts5-tax-credit-hit",
        primary_name="テスト試験研究費の税額控除制度",
        tier="A",
    )
    _insert(
        db_conn,
        unified_id="UNI-fts5-furusato-decoy",
        primary_name="テスト企業版ふるさと納税",
        tier="S",
        enriched_text="この制度は法人税の税額控除を提供します。",
    )

    r = client.get("/v1/programs/search", params={"q": "税額控除", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    top = body["results"][0]
    # Top must be the genuine tax-credit row (in primary_name), not the
    # furusato decoy whose only mention is in enriched_text.
    assert "税額控除" in top["primary_name"], (
        f"top result missing 税額控除 in primary_name: {top['primary_name']!r}"
    )
    assert "ふるさと納税" not in top["primary_name"], (
        f"top result is the trigram false-positive: {top['primary_name']!r}"
    )


def test_q_gx_compound_returns_gx_subsidies(
    client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    """``q=GX 補助金`` (mixed ASCII + kanji) — ASCII 2-char route
    must surface rows containing GX in name+aliases."""
    _insert(
        db_conn,
        unified_id="UNI-fts5-gx-hit",
        primary_name="テストGX促進事業費補助金",
        tier="A",
    )
    r = client.get("/v1/programs/search", params={"q": "GX 補助金", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    names = [row["primary_name"] for row in body["results"]]
    assert any("GX" in n and "補助金" in n for n in names), (
        f"GX 補助金 query missed compound match; names={names}"
    )


def test_q_chusho_kigyo_returns_smb_rows(
    client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    """``q=中小企業`` (4-char kanji compound) — phrase-quoted, must
    return SMB-related rows."""
    _insert(
        db_conn,
        unified_id="UNI-fts5-smb-hit",
        primary_name="テスト中小企業デジタル化補助金",
        tier="S",
    )
    r = client.get("/v1/programs/search", params={"q": "中小企業", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    top = body["results"][0]
    assert "中小企業" in top["primary_name"]


def test_q_user_quoted_dx_preserved(
    client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    # q='"DX" 製造業' — the user explicitly phrase-quoted DX. The rewriter
    # must NOT produce a triple-quote escape sequence (which the prior
    # implementation did via _fts_escape) — that emits a phrase literal
    # FTS5 parses as a literal-string match against zero rows.
    """User-quoted DX is preserved as a phrase, no escape doubling."""
    # Seed both halves so the AND has a chance to match.
    _insert(
        db_conn,
        unified_id="UNI-fts5-dx-mfg-hit",
        primary_name="テストDX製造業向け補助金",
        tier="A",
    )
    r = client.get(
        "/v1/programs/search",
        params={"q": '"DX" 製造業', "limit": 5},
    )
    assert r.status_code == 200
    body = r.json()
    # We don't assert >= 1 because production corpus may not have the
    # specific compound. We DO assert the request didn't 500 / didn't
    # surface a parser error — and that the seeded fixture row hits.
    names = [row["primary_name"] for row in body["results"]]
    assert "テストDX製造業向け補助金" in names, (
        f"user-quoted '\"DX\"' broke the AND match; names={names}"
    )


def test_q_empty_returns_empty_not_corpus_dump(client: TestClient) -> None:
    """``q=""`` (explicit empty string) must NOT dump the entire corpus.
    Without this guard a buggy client that forgot to populate the q
    field would burn anonymous quota at ¥3/req for zero signal."""
    # GET /v1/programs/search?q= (no value)
    r = client.get("/v1/programs/search?q=&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0, f"empty q dumped {body['total']} rows; expected 0"
    assert body["results"] == []


def test_q_whitespace_only_returns_empty(client: TestClient) -> None:
    """Whitespace-only ``q='   '`` must behave like the empty case."""
    r = client.get("/v1/programs/search", params={"q": "   ", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0


def test_q_empty_with_filter_still_filters(client: TestClient) -> None:
    """Regression guard: when ``q=""`` is paired with a structural filter
    (tier, prefecture, etc.) the filter still applies. We do NOT collapse
    every empty-q request to zero — only the unprotected case."""
    r = client.get(
        "/v1/programs/search",
        params={"q": "", "tier": "S", "limit": 10},
    )
    assert r.status_code == 200
    body = r.json()
    # Seeded DB has 1 tier=S row; we don't pin to == 1 because other tests
    # may have inserted more — only that the filter took effect.
    assert body["total"] >= 1


def test_q_cursor_preserves_literal_name_boost(
    client: TestClient,
    db_conn: sqlite3.Connection,
    paid_key: str,
) -> None:
    """Text-search cursors must carry the literal-name boost key.

    ``テストカーソル設備支援`` matches only through enriched_text. It must stay
    behind rows whose primary_name literally contains the query across both
    offset and cursor pagination.
    """
    query = "カーソル補助金"
    _insert(
        db_conn,
        unified_id="UNI-fts5-cursor-literal-a",
        primary_name="テストカーソル補助金A",
        tier="C",
    )
    _insert(
        db_conn,
        unified_id="UNI-fts5-cursor-literal-b",
        primary_name="テストカーソル補助金B",
        tier="C",
    )
    _insert(
        db_conn,
        unified_id="UNI-fts5-cursor-body-only",
        primary_name="テストカーソル設備支援",
        tier="S",
        enriched_text=query,
    )
    headers = {"X-API-Key": paid_key}

    offset_names: list[str] = []
    for offset in range(3):
        resp = client.get(
            "/v1/programs/search",
            params={"q": query, "limit": 1, "offset": offset},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        offset_names.extend(row["primary_name"] for row in resp.json()["results"])

    cursor_names: list[str] = []
    resp = client.get(
        "/v1/programs/search",
        params={"q": query, "limit": 1},
        headers=headers,
    )
    for _ in range(5):
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cursor_names.extend(row["primary_name"] for row in body["results"])
        token = body.get("next_cursor")
        if not token:
            break
        resp = client.get(
            "/v1/programs/search",
            params={"q": query, "limit": 1, "cursor": token},
            headers=headers,
        )

    assert cursor_names[:3] == offset_names
    assert all(query in name for name in cursor_names[:2])
    assert cursor_names[2] == "テストカーソル設備支援"


def test_q_cursor_rejects_changed_query(
    client: TestClient,
    db_conn: sqlite3.Connection,
    paid_key: str,
) -> None:
    query = "カーソル変更補助金"
    _insert(
        db_conn,
        unified_id="UNI-fts5-cursor-query-a",
        primary_name="テストカーソル変更補助金A",
        tier="A",
    )
    _insert(
        db_conn,
        unified_id="UNI-fts5-cursor-query-b",
        primary_name="テストカーソル変更補助金B",
        tier="A",
    )
    headers = {"X-API-Key": paid_key}
    resp = client.get(
        "/v1/programs/search",
        params={"q": query, "limit": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    token = resp.json().get("next_cursor")
    assert token

    mismatch = client.get(
        "/v1/programs/search",
        params={"q": "別のカーソル変更補助金", "limit": 1, "cursor": token},
        headers=headers,
    )
    assert mismatch.status_code == 422, mismatch.text
    assert "cursor" in mismatch.text


# ---------------------------------------------------------------------------
# Edge cases — the spec calls these out explicitly.
# ---------------------------------------------------------------------------


def test_q_short_katakana_does_not_crash(client: TestClient) -> None:
    """``q=あ`` (single hiragana, 1 char) — must not raise FTS5 syntax
    error. Routes through LIKE because the single char is below the
    trigram floor."""
    r = client.get("/v1/programs/search", params={"q": "あ", "limit": 3})
    assert r.status_code == 200


def test_q_single_kanji_does_not_crash(client: TestClient) -> None:
    """``q=税`` — single kanji, LIKE path."""
    r = client.get("/v1/programs/search", params={"q": "税", "limit": 3})
    assert r.status_code == 200


def test_q_punctuation_only_does_not_crash(client: TestClient, paid_key: str) -> None:
    """``q="**"`` / ``q=":;"`` — punctuation-only. Tokenizer returns
    empty; LIKE path takes over with the literal substring (which
    matches 0 in practice)."""
    for q in ["**", ":;", "()", ",,"]:
        r = client.get(
            "/v1/programs/search",
            params={"q": q, "limit": 3},
            headers={"X-API-Key": paid_key},
        )
        assert r.status_code == 200, f"q={q!r} crashed: status={r.status_code} body={r.text[:200]}"


def test_q_mixed_punctuation_separates_tokens(
    client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    """``q="中小企業, 製造業"`` (comma separator) — must split into two
    tokens even without whitespace. Prior behavior glued the comma onto
    the first token, producing ``"中小企業,"`` which never matched."""
    _insert(
        db_conn,
        unified_id="UNI-fts5-comma-target",
        primary_name="テスト中小企業向け製造業支援金",
        tier="A",
    )
    r = client.get(
        "/v1/programs/search",
        params={"q": "中小企業, 製造業", "limit": 5},
    )
    assert r.status_code == 200
    body = r.json()
    names = [row["primary_name"] for row in body["results"]]
    assert "テスト中小企業向け製造業支援金" in names, (
        f"comma-separated query missed AND match; names={names}"
    )


def test_q_number_kanji_compound_works(
    client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    """``q="100億 補助金"`` — number+kanji token (``100億``) plus kanji
    token (``補助金``). Must AND, must phrase-quote each."""
    _insert(
        db_conn,
        unified_id="UNI-fts5-100oku-hit",
        primary_name="テスト100億規模補助金",
        tier="S",
    )
    r = client.get(
        "/v1/programs/search",
        params={"q": "100億 補助金", "limit": 5},
    )
    assert r.status_code == 200
    body = r.json()
    names = [row["primary_name"] for row in body["results"]]
    assert "テスト100億規模補助金" in names


def test_q_user_quoted_disables_kana_expansion(
    client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    """``q='"のうぎょう"'`` — user explicitly phrase-quoted a hiragana
    reading. Rewriter must NOT inject KANA_EXPANSIONS (which would
    expand to 農業). The intent was an exact-phrase search."""
    # Seed only the kanji form. If KANA_EXPANSIONS were applied, this
    # row would surface; with the quote-disable it must NOT.
    _insert(
        db_conn,
        unified_id="UNI-fts5-hiragana-only",
        primary_name="テスト農業特例補助金",
        tier="A",
    )
    # Bare 'のうぎょう' → expansion → finds the row.
    r1 = client.get("/v1/programs/search", params={"q": "のうぎょう", "limit": 10})
    assert r1.status_code == 200
    names1 = [row["primary_name"] for row in r1.json()["results"]]
    assert "テスト農業特例補助金" in names1, f"bare hiragana query did not expand; names={names1}"
    # Quoted '"のうぎょう"' → no expansion → seed row (which only has 農業)
    # must NOT be in the result set unless the corpus already had a doc
    # whose enriched text literally contains のうぎょう (unlikely for the
    # seed).
    r2 = client.get(
        "/v1/programs/search",
        params={"q": '"のうぎょう"', "limit": 10},
    )
    assert r2.status_code == 200
    names2 = [row["primary_name"] for row in r2.json()["results"]]
    assert "テスト農業特例補助金" not in names2, (
        f"quoted hiragana leaked the kanji-form row; KANA_EXPANSIONS was "
        f"erroneously applied to a user-quoted phrase. names={names2}"
    )


def test_q_long_input_capped_at_200(client: TestClient) -> None:
    """The Query(max_length=200) cap is enforced by FastAPI. We just
    confirm a long-but-under-cap query doesn't crash."""
    q = "中小企業 " * 30  # 30 × 5 = 150 chars
    r = client.get("/v1/programs/search", params={"q": q, "limit": 3})
    assert r.status_code == 200


def test_q_over_200_returns_422(client: TestClient) -> None:
    q = "a" * 201
    r = client.get("/v1/programs/search", params={"q": q, "limit": 3})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Helper assertion: the pure-kanji predicate. Pinned because if its
# logic drifts (e.g. allows mixed-script), the rewriter's phrase-quote
# decision could regress.
# ---------------------------------------------------------------------------


class TestIsPureKanji:
    def test_pure_kanji(self) -> None:
        assert _is_pure_kanji("税額控除")
        assert _is_pure_kanji("中小企業")
        assert _is_pure_kanji("税")  # single is pure-kanji

    def test_mixed_kanji_kana(self) -> None:
        assert not _is_pure_kanji("ふるさと納税")  # has hiragana
        assert _is_pure_kanji("税額")  # both kanji — IS pure
        assert not _is_pure_kanji("税の制度")  # の is hiragana

    def test_mixed_kanji_ascii(self) -> None:
        assert not _is_pure_kanji("DX税制")
        assert not _is_pure_kanji("税100")

    def test_no_kanji(self) -> None:
        assert not _is_pure_kanji("DX")
        assert not _is_pure_kanji("ふるさと")
        assert not _is_pure_kanji("123")

    def test_empty(self) -> None:
        assert not _is_pure_kanji("")
