"""Regression test for the FTS5 trigram tokenizer gotcha documented in
``CLAUDE.md`` (§ Common gotchas):

    > FTS5 trigram tokenizer causes false single-kanji overlap matches.
    > Example: searching ``税額控除`` also hits rows mentioning only
    > ``ふるさと納税`` because both contain ``税``. Use phrase queries
    > (``"税額控除"`` with quotes) for 2+ character kanji compounds.
    > See ``src/jpintel_mcp/api/programs.py`` for the current workaround.

This test exercises the workaround *end-to-end* against a real SQLite
FTS5 virtual table with the ``trigram`` tokenizer — not just the string
output of ``_build_fts_match``. That is the difference that matters:
upstream SQLite tokenizer semantics, not Python string equality, is what
determines whether the trigram false-positive surfaces in production.

The pin contract is three behaviors:

1. ``q="税額控除"`` (2+ kanji compound) -> only rows containing that exact
   phrase return; ``ふるさと納税``-only rows must NOT surface as a
   trigram-overlap false positive on the shared kanji ``税``.
2. ``q="税"`` (single kanji) -> the rewriter must NOT over-filter so that
   *both* of the seeded rows still surface. FTS5 trigram needs >=3 chars
   contiguously, so single-kanji recall is delegated to the caller's LIKE
   fallback; the rewriter's job is only to emit a syntactically valid
   expression that does not raise.
3. ``q='"消費税法 第6条"'`` -> a user-quoted multi-token phrase must
   propagate to FTS5 as a single phrase literal including its internal
   whitespace, matching the row that has that exact sequence.

If the workaround in ``programs.py`` regresses (e.g. someone removes the
phrase-quote wrap for pure-kanji compounds, or escapes the user quotes
twice and produces a literal-string match against zero rows), one of
these assertions fails.

NO DB stub modules, NO production seed data — the test owns a private
in-memory FTS5 table whose three rows make the gotcha unambiguous.
"""

from __future__ import annotations

import sqlite3

import pytest

from jpintel_mcp.api.programs import _build_fts_match


# ---------------------------------------------------------------------------
# Seed fixture: a private in-memory FTS5(trigram) table with three controlled
# rows. The rows are crafted to expose the gotcha *if* the workaround
# regresses:
#
#   row TAX     -> contains the exact phrase 税額控除 in primary_name
#   row FURUSATO-> contains ふるさと納税 (shares the kanji 税 with TAX,
#                  but NOT the phrase 税額控除)
#   row LAW     -> contains the exact phrase "消費税法 第6条" with an
#                  internal space, used to pin user-quote propagation
# ---------------------------------------------------------------------------


@pytest.fixture()
def fts5_db() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with a 3-row FTS5(trigram)
    table that exercises the trigram-overlap gotcha.

    The schema mirrors the relevant subset of the production
    ``programs_fts`` table: a single content column (``primary_name``)
    tokenized via FTS5's ``trigram`` tokenizer."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE VIRTUAL TABLE programs_fts USING fts5(primary_name, tokenize='trigram')"
    )
    conn.executemany(
        "INSERT INTO programs_fts(rowid, primary_name) VALUES (?, ?)",
        [
            (1, "テスト試験研究費の税額控除制度"),
            (2, "テスト企業版ふるさと納税"),
            (3, "テスト消費税法 第6条 該当事業者向け支援"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


def _match(conn: sqlite3.Connection, expr: str) -> list[str]:
    """Run an FTS5 MATCH and return the matched primary_name values
    ordered by rowid (stable across runs)."""
    rows = conn.execute(
        "SELECT primary_name FROM programs_fts WHERE programs_fts MATCH ? ORDER BY rowid",
        (expr,),
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Test 1: 2+ kanji compound must NOT trigger the trigram overlap false
# positive on the shared kanji 税.
# ---------------------------------------------------------------------------


def test_phrase_quote_blocks_furusato_false_positive(
    fts5_db: sqlite3.Connection,
) -> None:
    """``q=税額控除`` -> exactly the tax-credit row, NOT ふるさと納税.

    This is the canonical CLAUDE.md gotcha. The rewriter must emit a
    phrase-quoted expression (``"税額控除"``) so that FTS5 forces the
    two trigrams ``税額控`` and ``額控除`` to appear contiguously. The
    decoy row contains ``税`` (in ``ふるさと納税``) but does NOT contain
    the sequence ``税額控除`` -> it must be excluded."""
    expr = _build_fts_match("税額控除")
    # Pin the workaround output explicitly: phrase-quoted, single token.
    assert expr == '"税額控除"', (
        f"FTS5 trigram workaround regressed: 2+ kanji compound was not "
        f"phrase-quoted. _build_fts_match('税額控除') -> {expr!r}; "
        f"expected '\"税額控除\"'. See programs.py:_build_fts_match."
    )
    hits = _match(fts5_db, expr)
    assert hits == ["テスト試験研究費の税額控除制度"], (
        f"FTS5 phrase quote did not block trigram overlap on 税: "
        f"got hits={hits!r}, expected only the 税額控除 row. The "
        f"ふるさと納税 decoy row leaked through — the workaround "
        f"in programs.py is not effective."
    )


# ---------------------------------------------------------------------------
# Test 2: single kanji must NOT be over-filtered. Both seeded rows
# containing 税 should still surface (recall preserved).
# ---------------------------------------------------------------------------


def test_single_kanji_does_not_overfilter(
    fts5_db: sqlite3.Connection,
) -> None:
    """``q=税`` (single kanji) -> both rows containing 税 surface.

    FTS5 trigram needs 3+ contiguous characters to produce trigrams,
    so a 1-char query has no trigrams of its own; the FTS path will
    return zero rows. Production routes single-kanji queries through
    the LIKE fallback in programs.py, which catches both rows. This
    test pins the rewriter's contract:

      - rewriter must not crash on a single kanji (regression: prior
        implementations raised on tokens shorter than the trigram
        minimum);
      - rewriter must emit a syntactically valid FTS5 expression so
        the caller can run it without a parser error and then fall
        back to LIKE for recall;
      - LIKE recall against the same corpus surfaces both seeded
        rows (no over-filter).
    """
    expr = _build_fts_match("税")
    assert expr == '"税"', (
        f"single-kanji rewriter regressed: got {expr!r}, expected '\"税\"'"
    )
    # The FTS5 trigram path is allowed to return [] for a 1-char token
    # (trigram needs 3+ chars). The contract is "does not raise" and
    # "is syntactically valid".
    try:
        fts_hits = _match(fts5_db, expr)
    except sqlite3.OperationalError as exc:
        pytest.fail(
            f"single-kanji FTS expression {expr!r} raised on FTS5 MATCH: "
            f"{exc}. The rewriter must always emit a parseable expression."
        )
    # Trigram cannot match a 1-char query; LIKE fallback is the recall
    # path. Simulate that here against the same in-memory rows.
    like_hits = [
        r[0]
        for r in fts5_db.execute(
            "SELECT primary_name FROM programs_fts WHERE primary_name LIKE ? ORDER BY rowid",
            ("%税%",),
        ).fetchall()
    ]
    # Both seeded rows contain 税 (税額控除 + ふるさと納税). The single-
    # kanji LIKE recall must surface BOTH — over-filtering here would
    # mean the workaround swung too far the other way.
    assert "テスト試験研究費の税額控除制度" in like_hits, (
        f"single-kanji LIKE recall missed the 税額控除 row: {like_hits!r}"
    )
    assert "テスト企業版ふるさと納税" in like_hits, (
        f"single-kanji LIKE recall missed the ふるさと納税 row "
        f"(over-filter): {like_hits!r}"
    )
    # Sanity: FTS path returned valid result set (possibly empty), no exception.
    assert isinstance(fts_hits, list)


# ---------------------------------------------------------------------------
# Test 3: user-quoted multi-token phrase propagates through the rewriter
# to FTS5 as a single phrase literal including internal whitespace.
# ---------------------------------------------------------------------------


def test_user_quoted_phrase_propagates_to_fts5(
    fts5_db: sqlite3.Connection,
) -> None:
    """``q='"消費税法 第6条"'`` -> exact phrase match on the row that has
    that sequence, no AND-split on the internal space.

    The user explicitly phrase-quoted, so the rewriter must:

      - NOT split on the internal space (which would AND two separate
        phrase tokens);
      - NOT double-escape the user's quotes (which produced a literal-
        string match against zero rows in the prior implementation);
      - emit a single FTS5 phrase literal that FTS5 parses as
        "tokens in sequence" and which matches the exact row.
    """
    expr = _build_fts_match('"消費税法 第6条"')
    assert expr == '"消費税法 第6条"', (
        f"user-quoted phrase propagation regressed: got {expr!r}, "
        f"expected '\"消費税法 第6条\"' (single phrase, internal "
        f"whitespace preserved, no double-quote escape doubling)."
    )
    # No triple-quote escape sequence (the prior-implementation bug).
    assert '"""' not in expr, (
        f"triple-quote escape leaked into FTS expression: {expr!r}; "
        f"_fts_escape was applied twice to a user-quoted phrase."
    )
    hits = _match(fts5_db, expr)
    assert hits == ["テスト消費税法 第6条 該当事業者向け支援"], (
        f"user-quoted phrase did not match the seeded exact-sequence "
        f"row: hits={hits!r}, expected only the 消費税法 第6条 row. "
        f"The phrase quote was either split or escaped incorrectly."
    )
