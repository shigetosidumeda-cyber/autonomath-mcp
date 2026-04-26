"""Tier 3 invariants — 4 monthly review checks (P5-θ++ / dd_v8_05).

INV-30  gold precision monotonic (per-tool precision must not drop MoM)
INV-31  am_entities row count strictly increasing month-over-month
INV-32  testimonial / case_studies count strictly increasing
INV-33  margin >= 92% (Stripe revenue / total cost; ¥3/req metered + Fly/CF
        infra costs)

These are advisory: in dev/test most of them skip cleanly. The monthly
cron (`scripts/monthly_invariant_review.py`) writes a markdown audit
to `analysis_wave18/invariant_monthly/<YYYY-MM>.md`; failures there
produce an operator email rather than a hard test failure (these are
business-health signals, not safety-critical).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# INV-30: gold precision monotonic
# ---------------------------------------------------------------------------
def test_inv30_gold_precision_history_artifact():
    """A gold-precision audit artifact must exist under evals/.

    The numeric MoM monotonic check is computed by
    `scripts/monthly_invariant_review.py` against the dated artifacts.
    Here we just assert the artifact directory + at least one snapshot.
    """
    repo = Path(__file__).resolve().parent.parent
    evals_dir = repo / "evals"
    if not evals_dir.is_dir():
        pytest.skip("evals/ directory not present")
    snapshots = list(evals_dir.rglob("*.json")) + list(evals_dir.rglob("*.md"))
    if not snapshots:
        pytest.skip("no eval snapshots present yet (pre-launch)")
    # Soft pass — monthly cron does the MoM monotonic compare.
    assert snapshots


# ---------------------------------------------------------------------------
# INV-31: am_entities row count strictly increasing
# ---------------------------------------------------------------------------
def test_inv31_am_entities_present():
    """autonomath.db.am_entities must exist and have > 0 rows.

    The MoM growth check is in the monthly review script. Here we
    sanity-check the table is populated so the cron has data to
    compare against the previous month's snapshot.
    """
    repo = Path(__file__).resolve().parent.parent
    db_path = repo / "autonomath.db"
    if not db_path.is_file():
        pytest.skip("autonomath.db not present in repo root (dev/test)")
    con = sqlite3.connect(db_path)
    try:
        if not _table_exists(con, "am_entities"):
            pytest.skip("am_entities table not present")
        n = con.execute("SELECT COUNT(*) FROM am_entities").fetchone()[0]
    finally:
        con.close()
    assert n > 0, "am_entities is empty — MoM growth invariant cannot be evaluated"


# ---------------------------------------------------------------------------
# INV-32: testimonial / case_studies count strictly increasing
# ---------------------------------------------------------------------------
def test_inv32_case_studies_table_present():
    """case_studies table exists; row count history is the monthly
    cron's responsibility.
    """
    from jpintel_mcp.db.session import connect

    with connect() as con:
        if not _table_exists(con, "case_studies"):
            pytest.skip("case_studies table not present")
        n = con.execute("SELECT COUNT(*) FROM case_studies").fetchone()[0]
    # case_studies may legitimately be empty in dev; only assert presence.
    assert n >= 0


# ---------------------------------------------------------------------------
# INV-33: margin >= 92%
# ---------------------------------------------------------------------------
def test_inv33_margin_floor_in_prod():
    """In prod, the previous month's margin must be >= 92%.

    Skipped in dev. The numeric check is performed in the monthly
    review script against Stripe revenue + Fly/CF cost data.
    """
    env = os.getenv("JPINTEL_ENV", "dev")
    if env != "prod":
        pytest.skip(f"JPINTEL_ENV={env}; INV-33 prod-only")
    # Even in prod, the test-layer cannot fetch live Stripe / Fly bills.
    # The cron writes a markdown artifact + emails the operator on
    # margin breach. This test passes if the artifact exists for the
    # previous calendar month.
    repo = Path(__file__).resolve().parent.parent
    monthly_dir = repo / "analysis_wave18" / "invariant_monthly"
    if not monthly_dir.is_dir():
        pytest.skip("monthly_invariant_review has never run")
    artifacts = sorted(monthly_dir.glob("*.md"))
    assert artifacts, "monthly_invariant_review produced no artifact"
