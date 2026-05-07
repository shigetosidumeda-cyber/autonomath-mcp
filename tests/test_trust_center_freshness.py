"""Trust Center freshness gate.

If the cron has been broken for over 8 days, this test fails so the operator
notices and either fixes the cron or rolls the page off public surface.

NO LLM. Pure file IO + clock check.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX = REPO_ROOT / "site/trust/_data/matrix_latest.json"


def _load_matrix() -> dict | None:
    if not MATRIX.exists():
        return None
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_trust_matrix_freshness_within_8_days() -> None:
    """Trust Center matrix generated_at must be within 8 days of now."""
    j = _load_matrix()
    if j is None:
        return  # first run not yet completed; test_trust_matrix_exists_eventually flags this separately
    ts = j["generated_at"].rstrip("Z")
    gen_at = dt.datetime.fromisoformat(ts)
    age = dt.datetime.utcnow() - gen_at
    assert age < dt.timedelta(days=8), (
        f"Trust Center matrix stale: generated_at={j['generated_at']}, "
        f"age={age.total_seconds() / 86400:.1f} days. Cron freshness threshold is 8 days."
    )


def test_trust_matrix_has_seven_rows() -> None:
    """Matrix must have exactly 7 proof rows."""
    j = _load_matrix()
    if j is None:
        return
    assert len(j["rows"]) == 7, (
        f"expected 7 trust rows (JCRB / practitioner / composite / source_receipts / "
        f"known_gaps / anchor_verify / acceptance), got {len(j['rows'])}"
    )


def test_trust_matrix_anchor_files_referenced() -> None:
    """Every row must declare anchor_file so reproducers can re-derive numbers."""
    j = _load_matrix()
    if j is None:
        return
    for row in j["rows"]:
        assert row.get("anchor_file"), f"row {row.get('id')} missing anchor_file"


def test_trust_matrix_has_corpus_snapshot_id() -> None:
    """Top-level corpus_snapshot_id ties the matrix to a specific data slice."""
    j = _load_matrix()
    if j is None:
        return
    assert "corpus_snapshot_id" in j
    # Non-empty string ("unknown" is acceptable on first runs).
    assert isinstance(j["corpus_snapshot_id"], str) and j["corpus_snapshot_id"]


def test_trust_matrix_required_row_ids_present() -> None:
    """All seven canonical row ids must appear (allowing alternate stems)."""
    j = _load_matrix()
    if j is None:
        return
    ids = {r["id"] for r in j["rows"]}
    # Match either canonical stems or jsonl filename stems.
    required_seeds = {
        ("jcrb",),
        ("practitioner_eval",),
        ("composite", "composite_benchmark_latest"),
        ("source_receipts", "source_receipts_coverage"),
        ("known_gaps", "known_gaps_display"),
        ("anchor_verify", "audit_seal_roundtrip"),
        ("acceptance", "acceptance_contract_pass"),
    }
    for alts in required_seeds:
        assert any(
            a in ids for a in alts
        ), f"none of {alts} found in trust matrix row ids {sorted(ids)}"
