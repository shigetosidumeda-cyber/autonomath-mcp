"""Tests for `scripts/etl/reconcile_adoption_to_program.py`.

Covers the strip_year_round_suffix regex set + the matcher's signal
selection. Read-only on the database — the reconciler itself never
writes, and these tests use only Python data.

The 5 strip cases below are the canonical regression set: they cover
the actual suffix shapes observed in production raw_json across the
11 distinct program_id_hint cohorts (it_dounyu / it_hojo_2023 /
it_hojo_2025 / monodukuri / saikouchiku / jigyou_saikouchiku /
jizokuka_ippan / jizokuka_shokokai / jizokuka_sogyo / shoryokuka_ippan
/ shinjigyou).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "etl" / "reconcile_adoption_to_program.py"
_spec = importlib.util.spec_from_file_location(
    "reconcile_adoption_to_program",
    _SCRIPT,
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["reconcile_adoption_to_program"] = _mod
_spec.loader.exec_module(_mod)


# ---------------------------------------------------------------------------
# strip_year_round_suffix — 5 canonical cases plus edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # 1. Trailing fiscal year + reporting period (IT導入補助金 cohort).
        ("IT導入補助金 2023 後期", "IT導入補助金"),
        # 2. 第N回公募 round number suffix (事業再構築 cohort).
        ("事業再構築補助金 第13回公募", "事業再構築補助金"),
        # 3. 第N次公募 — same rule, different counter (ものづくり cohort).
        ("ものづくり補助金 第22次公募", "ものづくり補助金"),
        # 4. 令和N年度第M次補正 — fiscal-year + supplementary round.
        (
            "省エネ・非化石転換補助金 設備単位型 令和7年度補正",
            "省エネ・非化石転換補助金 設備単位型",
        ),
        # 5. R6補正第3次 — Reiwa abbrev form.
        ("中小企業省力化投資補助金 R6補正第3次", "中小企業省力化投資補助金"),
        # ---- additional edge cases ----
        # 6. Parenthesized 枠 name MUST survive — it's a real variant.
        (
            "小規模事業者持続化補助金 (商工会地区)",
            "小規模事業者持続化補助金 (商工会地区)",
        ),
        # 7. NFKC half/full-width fold — fullwidth digits should normalise.
        ("ものづくり補助金 第２２次公募", "ものづくり補助金"),
        # 8. Bare-year mid-string strip (IT導入補助金 2025 (枠名) cohort).
        (
            "IT導入補助金 2025 (デジタル化・AI導入補助金)",
            "IT導入補助金 (デジタル化・AI導入補助金)",
        ),
        # 9. Empty input is the empty string.
        ("", ""),
        # 10. Pure suffix collapses to empty string (defensive).
        ("R6補正第3次", ""),
    ],
)
def test_strip_year_round_suffix(raw: str, expected: str) -> None:
    assert _mod.strip_year_round_suffix(raw) == expected


# ---------------------------------------------------------------------------
# _confidence_band
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, expected",
    [
        (1.0, "high"),
        (0.95, "high"),
        (0.92, "high"),
        (0.91, "medium"),
        (0.85, "medium"),
        (0.84, "low"),
        (0.50, "low"),
        (0.0, "none"),
    ],
)
def test_confidence_band(score: float, expected: str) -> None:
    assert _mod._confidence_band(score) == expected


# ---------------------------------------------------------------------------
# Matcher — exact / alias / fuzzy_high / fuzzy_med / hint cohort
# ---------------------------------------------------------------------------


def _scorer():
    from rapidfuzz import distance

    return distance.JaroWinkler.normalized_similarity


def _make_program(canonical_id: str, primary_name: str) -> _mod.ProgramRow:
    return _mod.ProgramRow(
        canonical_id=canonical_id,
        primary_name=primary_name,
        aliases=[],
        jsic_major=None,
        funding_purpose=None,
    )


def _make_adoption(
    *,
    canonical_id: str = "adoption:test:00001",
    program_name_raw: str | None = None,
    program_id_hint: str | None = None,
    source_url_domain: str | None = None,
) -> _mod.AdoptionRow:
    return _mod.AdoptionRow(
        canonical_id=canonical_id,
        program_name_raw=program_name_raw,
        program_id_hint=program_id_hint,
        source_url_domain=source_url_domain,
        raw_json="{}",
    )


def test_matcher_signal_exact() -> None:
    """Exact normalised name match returns signal='exact', score=1.0."""
    pr = _make_program("p1", "IT導入補助金")
    programs = [pr]
    norm_index = {_mod._normalize(pr.primary_name): [pr]}
    alias_index: dict[str, list[_mod.ProgramRow]] = {}

    ad = _make_adoption(program_name_raw="IT導入補助金 2023 後期", program_id_hint="it_hojo_2023")
    pid, score, signal, stripped = _mod._try_match(
        ad,
        programs,
        norm_index,
        alias_index,
        _scorer(),
    )
    assert pid == "p1"
    assert score == 1.0
    assert signal == "exact"
    assert stripped == "IT導入補助金"


def test_matcher_signal_fuzzy_high() -> None:
    """Drift like '事業再構築補助金A' (single trailing char) lands fuzzy_high."""
    pr = _make_program("p2", "事業再構築補助金")
    programs = [pr]
    norm_index = {_mod._normalize(pr.primary_name): [pr]}
    alias_index: dict[str, list[_mod.ProgramRow]] = {}

    # Single-trailing-char drift — JaroWinkler ≈ 0.97 against the program.
    ad = _make_adoption(program_name_raw="事業再構築補助金A")
    pid, score, signal, _stripped = _mod._try_match(
        ad,
        programs,
        norm_index,
        alias_index,
        _scorer(),
    )
    assert pid == "p2"
    assert score >= 0.92
    assert signal == "fuzzy_high"


def test_matcher_signal_hint_when_program_name_missing() -> None:
    """05_adoption_additional cohort (program_name=NULL) resolves via hint."""
    pr = _make_program("program:base:a841db60bb", "事業再構築補助金")
    programs = [pr]
    norm_index = {_mod._normalize(pr.primary_name): [pr]}
    alias_index: dict[str, list[_mod.ProgramRow]] = {}

    ad = _make_adoption(
        program_name_raw=None,
        program_id_hint="jigyou_saikouchiku",  # mapped in HINT_TO_CANONICAL_PROGRAM
    )
    pid, score, signal, _stripped = _mod._try_match(
        ad,
        programs,
        norm_index,
        alias_index,
        _scorer(),
    )
    assert pid == "program:base:a841db60bb"
    assert score == 1.0
    assert signal == "hint"


def test_matcher_signal_unmatched_when_no_signal() -> None:
    """Garbage program name + unknown hint -> unmatched, no program_id."""
    pr = _make_program("p3", "全く別の制度")
    programs = [pr]
    norm_index = {_mod._normalize(pr.primary_name): [pr]}
    alias_index: dict[str, list[_mod.ProgramRow]] = {}

    ad = _make_adoption(
        program_name_raw="まったく違う名前の補助金",
        program_id_hint="unknown_hint_not_in_table",
    )
    pid, score, signal, _stripped = _mod._try_match(
        ad,
        programs,
        norm_index,
        alias_index,
        _scorer(),
    )
    # No fuzzy match clears even 0.85.
    assert pid is None
    assert signal == "unmatched"
    assert score < 0.85
