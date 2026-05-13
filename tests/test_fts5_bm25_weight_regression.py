"""Regression test for the FTS5 bm25 column-weight + tier_weight composite
ranking fix documented in ``src/jpintel_mcp/api/programs.py:50-58`` (block
dated 2026-04-30).

The CLAUDE.md ``Key files`` entry pins ``api/programs.py`` as the home of
the search ranking logic; the inline comment block declares two coupled
calibrations:

1. **bm25 column weighting** (``BM25_EXPR = bm25(programs_fts, 5.0, 1.0,
   1.0)``). ``programs_fts`` is declared as
   ``fts5(unified_id UNINDEXED, primary_name, aliases, enriched_text,
   tokenize='trigram')``. ``bm25()`` takes one weight per INDEXED column
   in declaration order (UNINDEXED columns are skipped). ``primary_name``
   is weighted 5x so a query that hits the program name directly outranks
   a doc whose only hit is buried in long-form description / aliases. The
   three positional weights MUST stay aligned with the FTS column order —
   if anyone adds an INDEXED column to ``programs_fts`` without also
   bumping the weight tuple, the ``bm25(...)`` call will silently
   misalign weights to columns.
2. **Tier prior multiplier** (``TIER_PRIOR_WEIGHTS``). Replaces a prior
   strict ``S > A > B > C > X`` bucket-ordering with a soft multiplier
   applied to bm25. bm25 is negative (lower = better), so a >1 weight
   amplifies (boosts) and a <1 weight attenuates (demotes). The composite
   sort key is ``bm25 * tier_weight ASC``.

The combined contract therefore has three legs:

* same FTS relevance + different tier  -> higher tier ranks first;
* same tier + different FTS relevance   -> stronger bm25 hit ranks first;
* mixed relevance + tier                -> ``bm25 * tier_weight`` produces
  a single deterministic ordering across all input rows.

This test exercises the composite end-to-end against a real SQLite FTS5
``trigram`` table — not Python arithmetic on mock numbers. The actual
SQLite ``bm25()`` auxiliary function is invoked, and the SQL ``CASE``
expression produced by ``_build_tier_weight_case`` is plugged in
verbatim. If a future edit drops one of the column weights, swaps the
sort direction, or replaces the multiplier with an additive offset, one
of these assertions fails.

NO production DB, NO mocks — the fixture owns a private in-memory
``programs`` + ``programs_fts`` pair with hand-controlled rows.
"""

from __future__ import annotations

import sqlite3

import pytest

from jpintel_mcp.api.programs import (
    BM25_EXPR,
    TIER_PRIOR_WEIGHTS,
    _build_tier_weight_case,
)


# ---------------------------------------------------------------------------
# Substrate guards: lock the constants the SQL below relies on. If anyone
# changes the bm25 weight tuple or the tier multiplier dict shape, these
# fire before the SQL assertions so the failure surface is unambiguous.
# ---------------------------------------------------------------------------


def test_bm25_expr_pins_primary_name_5x_weight() -> None:
    """``BM25_EXPR`` must keep primary_name at 5x relative to aliases /
    enriched_text. This is the column-weight fix from programs.py:50-58."""
    # Direct string pin — if the constant is re-formatted, update the test
    # alongside the production change deliberately.
    assert BM25_EXPR == "bm25(programs_fts, 5.0, 1.0, 1.0)", (
        f"bm25 column-weight fix regressed: BM25_EXPR={BM25_EXPR!r}. "
        f"Expected 'bm25(programs_fts, 5.0, 1.0, 1.0)' — primary_name "
        f"must weigh 5x against aliases (1.0) + enriched_text (1.0) per "
        f"the 2026-04-30 calibration comment in api/programs.py."
    )


def test_tier_weights_monotone_decreasing_through_x() -> None:
    """Tier prior multipliers must remain ordered S >= A >= B > C > X so
    that ``bm25 * tier_weight ASC`` mirrors the tier hierarchy. The exact
    numbers are calibration-driven (Brier-fit) and may change; the
    ordering invariant is what the composite formula relies on."""
    s, a, b, c, x = (
        TIER_PRIOR_WEIGHTS["S"],
        TIER_PRIOR_WEIGHTS["A"],
        TIER_PRIOR_WEIGHTS["B"],
        TIER_PRIOR_WEIGHTS["C"],
        TIER_PRIOR_WEIGHTS["X"],
    )
    # Note: production values currently have S(1.07) >= A(1.06) >= B(1.06)
    # > C(0.99) > X(0.83); the C3 calibration intentionally tied A and B.
    # Treat the spec as non-strict between S/A and A/B but strict at the
    # C and X step.
    assert s >= a >= b > c > x, (
        f"tier prior weight monotonicity regressed: S={s}, A={a}, B={b}, "
        f"C={c}, X={x}. Required: S>=A>=B>C>X."
    )
    # X must stay below 1.0 (= demote unknown/quarantine), S above 1.0
    # (= boost top tier). The composite formula's sign relies on this.
    assert x < 1.0 < s, (
        f"tier multiplier sign regressed: X={x} should be <1.0 (demote) "
        f"and S={s} should be >1.0 (boost). Lose this and the calibration "
        f"comment in api/programs.py becomes a lie."
    )


# ---------------------------------------------------------------------------
# Seed fixture: a private in-memory schema that mirrors the relevant
# subset of production — a ``programs`` table with (unified_id, tier,
# primary_name, aliases, enriched_text) and an ``programs_fts`` external-
# content FTS5 virtual table with the *exact* column declaration used in
# `src/jpintel_mcp/db/schema.sql:67` (unified_id UNINDEXED + 3 indexed
# text columns + trigram tokenizer).
# ---------------------------------------------------------------------------


@pytest.fixture()
def ranking_db() -> sqlite3.Connection:
    """Build a 4-row programs corpus exercising the bm25 + tier weight
    composite. Rows are crafted to make the three ranking legs falsifiable:

      UNI-S-strong: tier='S', primary_name='テスト税額控除制度' (direct
                    bm25 hit on primary_name → strongest FTS hit).
      UNI-C-strong: tier='C', primary_name='テスト税額控除制度' (SAME
                    bm25 relevance as UNI-S-strong, but lower tier — used
                    to pin "same bm25, different tier" leg).
      UNI-S-weak:   tier='S', primary_name='テスト一般支援制度',
                    enriched_text mentions 税額控除 once in body (weak
                    bm25 hit — primary_name miss, body hit).
      UNI-C-weak:   tier='C', primary_name='テスト一般支援制度',
                    enriched_text mentions 税額控除 once in body (SAME
                    weak bm25 as UNI-S-weak; combined with mixed-tier
                    sibling above to pin the composite leg).
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            primary_name TEXT NOT NULL,
            aliases TEXT,
            enriched_text TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE programs_fts USING fts5(
            unified_id UNINDEXED,
            primary_name,
            aliases,
            enriched_text,
            tokenize='trigram'
        )
        """
    )
    seed = [
        # (unified_id, tier, primary_name, aliases, enriched_text)
        (
            "UNI-S-strong",
            "S",
            "テスト税額控除制度",
            "",
            "本制度の概要を記載します。",
        ),
        (
            "UNI-C-strong",
            "C",
            "テスト税額控除制度",
            "",
            "本制度の概要を記載します。",
        ),
        (
            "UNI-S-weak",
            "S",
            "テスト一般支援制度",
            "",
            "本制度では税額控除を一度だけ説明する長文の本文です。",
        ),
        (
            "UNI-C-weak",
            "C",
            "テスト一般支援制度",
            "",
            "本制度では税額控除を一度だけ説明する長文の本文です。",
        ),
    ]
    conn.executemany(
        "INSERT INTO programs(unified_id, tier, primary_name, aliases, "
        "enriched_text) VALUES (?, ?, ?, ?, ?)",
        seed,
    )
    conn.executemany(
        "INSERT INTO programs_fts(unified_id, primary_name, aliases, "
        "enriched_text) VALUES (?, ?, ?, ?)",
        [(r[0], r[2], r[3], r[4]) for r in seed],
    )
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helper: run the production composite ORDER BY against the in-memory
# corpus. ``q`` is plugged into the FTS5 MATCH; the SELECT list uses the
# exact ``BM25_EXPR`` and ``_build_tier_weight_case`` strings as
# programs.py:2024-2025 would build them.
# ---------------------------------------------------------------------------


def _rank(conn: sqlite3.Connection, q: str) -> list[tuple[str, str, float, float]]:
    """Return list of (unified_id, tier, raw_bm25, composite_score) ordered
    by the composite ``bm25 * tier_weight ASC`` rule, matching the
    production FTS path SQL."""
    tier_case = _build_tier_weight_case("programs.tier")
    sql = (
        "SELECT programs.unified_id, programs.tier, "
        f"  {BM25_EXPR} AS _rank, "
        f"  ({BM25_EXPR}) * ({tier_case}) AS _score "
        "FROM programs JOIN programs_fts ON programs.unified_id = "
        "  programs_fts.unified_id "
        "WHERE programs_fts MATCH ? "
        "ORDER BY _score ASC, programs.primary_name ASC, "
        "  programs.unified_id ASC"
    )
    return [
        (row[0], row[1], float(row[2]), float(row[3]))
        for row in conn.execute(sql, (q,)).fetchall()
    ]


# ---------------------------------------------------------------------------
# Test 1: same FTS relevance, different tier — S must rank before C.
# Both UNI-S-strong and UNI-C-strong have identical primary_name (so
# identical raw bm25); only the tier_weight multiplier differs.
# ---------------------------------------------------------------------------


def test_same_bm25_different_tier_s_outranks_c(
    ranking_db: sqlite3.Connection,
) -> None:
    """Composite ranking puts S-tier ahead of C-tier when bm25 is tied.

    Both ``UNI-S-strong`` and ``UNI-C-strong`` hit ``税額控除`` on
    primary_name identically, so ``bm25(...)`` produces the same raw
    score for both. The tier multiplier (S=1.07, C=0.99) breaks the tie:
    ``negative * 1.07`` is more negative than ``negative * 0.99``, so
    S-tier sorts first under ASC.
    """
    ranked = _rank(ranking_db, '"税額控除"')
    # Filter to the strong-hit pair only — the weak-hit rows also match
    # 税額控除 (in enriched_text) but at lower bm25, so they'll fall to
    # the back of the list and aren't the subject of this assertion.
    ids = [r[0] for r in ranked]
    assert "UNI-S-strong" in ids and "UNI-C-strong" in ids, (
        f"seed corpus regression: both strong-hit rows must MATCH. "
        f"Got ranked={ranked!r}"
    )
    s_pos = ids.index("UNI-S-strong")
    c_pos = ids.index("UNI-C-strong")
    # Raw bm25 must be (numerically) equal up to FP noise — identical
    # primary_name content into FTS5 yields identical bm25.
    s_raw = ranked[s_pos][2]
    c_raw = ranked[c_pos][2]
    assert abs(s_raw - c_raw) < 1e-9, (
        f"raw bm25 should tie when primary_name matches identically; got "
        f"S={s_raw}, C={c_raw}. If this fires, the seed corpus drifted "
        f"and the same-bm25 leg is no longer being tested."
    )
    # Composite score: more-negative = stronger. S must be more negative.
    assert ranked[s_pos][3] < ranked[c_pos][3], (
        f"composite (bm25 * tier_weight) failed to demote C below S: "
        f"S _score={ranked[s_pos][3]}, C _score={ranked[c_pos][3]}. "
        f"Expected S < C (more negative)."
    )
    # Final ordering: S strictly before C in the result list.
    assert s_pos < c_pos, (
        f"tier ordering regressed at the composite layer: UNI-S-strong "
        f"appeared at position {s_pos} vs UNI-C-strong at {c_pos}; "
        f"S must rank first. Full ranked={ranked!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: same tier, different FTS relevance — primary_name hit must
# outrank enriched_text-only hit.
# This is the 5x column-weight leg of the fix. Without it, both rows
# would be near-equal under default bm25 (1.0/1.0/1.0).
# ---------------------------------------------------------------------------


def test_same_tier_different_relevance_strong_bm25_wins(
    ranking_db: sqlite3.Connection,
) -> None:
    """Among S-tier rows, the primary_name hit beats the body-only hit.

    ``UNI-S-strong`` has 税額控除 in primary_name (5x column weight) and
    ``UNI-S-weak`` only in enriched_text (1x). The composite formula is
    ``bm25 * tier_weight``, but tier is identical (both S) so the only
    differentiator is bm25 — the column-weight tuple must be doing its
    job for this leg to pass.
    """
    ranked = _rank(ranking_db, '"税額控除"')
    ids = [r[0] for r in ranked]
    assert "UNI-S-strong" in ids and "UNI-S-weak" in ids, (
        f"seed corpus regression: both S-tier rows must MATCH on a "
        f"phrase query for 税額控除. Got ranked={ranked!r}"
    )
    strong_pos = ids.index("UNI-S-strong")
    weak_pos = ids.index("UNI-S-weak")
    strong_raw = ranked[strong_pos][2]
    weak_raw = ranked[weak_pos][2]
    # bm25 is negative; stronger hit = MORE negative = strictly smaller.
    assert strong_raw < weak_raw, (
        f"5x primary_name column weight regressed: primary_name-hit row "
        f"raw bm25={strong_raw} did NOT beat body-hit row {weak_raw}. "
        f"Check that BM25_EXPR still carries the (5.0, 1.0, 1.0) tuple "
        f"and that the FTS schema column order still puts primary_name "
        f"as the first INDEXED column."
    )
    assert strong_pos < weak_pos, (
        f"bm25 column-weight ordering regressed: UNI-S-strong fell to "
        f"position {strong_pos} vs UNI-S-weak at {weak_pos}; the "
        f"primary_name hit must rank first. Full ranked={ranked!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: deterministic ordering of the full mixed corpus under the
# composite formula. With all four seeded rows on the same query, the
# composite ``bm25 * tier_weight`` must produce a single stable order:
#   1) UNI-S-strong   (strong bm25, S boost)
#   2) UNI-C-strong   (strong bm25, C neutral)
#   3) UNI-S-weak     (weak bm25,   S boost)
#   4) UNI-C-weak     (weak bm25,   C neutral)
# The strong-bm25 leg dominates the tier leg because the primary_name
# 5x weight produces a much larger magnitude gap than the tier
# multiplier delta (S=1.07 vs C=0.99 ≈ 8% spread).
# ---------------------------------------------------------------------------


def test_composite_bm25_tier_weight_full_ordering(
    ranking_db: sqlite3.Connection,
) -> None:
    """All four rows under the same query rank in a deterministic order
    that matches the documented contract ``bm25 * tier_weight ASC``.

    Beyond the position assertions, this test verifies the composite is
    *monotone*: walking the result list, ``_score`` must be non-
    decreasing. A monotonicity break would indicate the ORDER BY
    composite expression diverged from what the SELECT projection
    computes (a real bug we saw earlier when bm25 was applied without
    the multiplier).
    """
    ranked = _rank(ranking_db, '"税額控除"')
    ids = [r[0] for r in ranked]
    # All four rows must appear.
    assert set(ids) == {
        "UNI-S-strong",
        "UNI-C-strong",
        "UNI-S-weak",
        "UNI-C-weak",
    }, f"missing rows in MATCH result: ranked={ranked!r}"
    # Exact deterministic order — strong-bm25 leg dominates tier leg.
    assert ids == [
        "UNI-S-strong",
        "UNI-C-strong",
        "UNI-S-weak",
        "UNI-C-weak",
    ], (
        f"composite ranking deterministic order regressed. Expected "
        f"[S-strong, C-strong, S-weak, C-weak]; got {ids!r}. Full "
        f"ranked={ranked!r}"
    )
    # Monotone _score (ASC): each row's composite score >= previous.
    scores = [r[3] for r in ranked]
    for i in range(1, len(scores)):
        assert scores[i] >= scores[i - 1], (
            f"composite _score is not monotonically non-decreasing at "
            f"position {i}: scores={scores!r}. SELECT projection of "
            f"(bm25 * tier_weight) diverged from the ORDER BY composite."
        )
    # Cross-leg: the C-strong row (lower tier, stronger hit) must rank
    # ABOVE the S-weak row (higher tier, weaker hit) because the bm25
    # magnitude gap dominates the tier multiplier gap. This is what
    # "soft multiplier replacing strict bucket order" means.
    c_strong_pos = ids.index("UNI-C-strong")
    s_weak_pos = ids.index("UNI-S-weak")
    assert c_strong_pos < s_weak_pos, (
        f"soft-multiplier contract regressed: UNI-C-strong (C tier, "
        f"strong bm25) at position {c_strong_pos} did NOT outrank "
        f"UNI-S-weak (S tier, weak bm25) at {s_weak_pos}. The tier "
        f"multiplier has reverted to a strict bucket dominator — the "
        f"C3 calibration comment in api/programs.py is no longer "
        f"reflected in the SQL."
    )
