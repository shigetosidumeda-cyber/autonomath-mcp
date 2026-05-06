"""Tests for the V4 Phase 4 ``validate`` MCP tool + 6 generic intake predicates.

Coverage matrix
---------------
- ``api/_validation_predicates.py`` exports 6 ``check_*`` functions wrapped
  by the ``PREDICATES`` dict + ``resolve_predicate``. Each predicate gets a
  positive case (no violation → True) and a negative case (violation → False).
- ``mcp/autonomath_tools/validation_tools.py`` exposes ``validate`` /
  ``_validate_impl``. Tests verify the rule scan + cache key shape + REST
  POST /v1/am/validate end-to-end.

Skips module-wide if autonomath.db is missing — same convention as
test_autonomath_tools.py / test_annotation_tools.py.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))
_GRAPH_PATH = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH)))

if not _DB_PATH.exists() or not _GRAPH_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) or graph.sqlite ({_GRAPH_PATH}) "
        "not present; skipping validation suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

# server import first to break circular dependency.
from jpintel_mcp.api._validation_predicates import (  # noqa: E402
    PREDICATE_PREFIX,
    PREDICATES,
    resolve_predicate,
)
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.validation_tools import (  # noqa: E402
    _canonical_applicant_hash,
    _validate_impl,
    validate,
)

THIS_YEAR = datetime.date.today().year


# ---------------------------------------------------------------------------
# 1. _validation_predicates.py — 6 predicates × (positive, negative)
# ---------------------------------------------------------------------------


def test_predicate_prefix_is_documented_value():
    assert PREDICATE_PREFIX == "autonomath.intake."


def test_predicates_registry_has_six_entries():
    """Registry size = 6 generic predicates ported from autonomath.intake_consistency_rules."""
    assert len(PREDICATES) == 6
    assert set(PREDICATES.keys()) == {
        "check_training_hours_per_year_over",
        "check_annual_work_days_over",
        "check_weekly_work_hours_over",
        "check_start_year_plausible",
        "check_birth_vs_age",
        "check_desired_amount_sanity_upper",
    }


# --- 1a. training_hours_per_year > 8760 ----------------------------------


def test_check_training_hours_passes_for_normal_value():
    fn = PREDICATES["check_training_hours_per_year_over"]
    assert fn({"behavioral": {"training_hours_per_year": 100}}) is True


def test_check_training_hours_fails_when_over_8760():
    fn = PREDICATES["check_training_hours_per_year_over"]
    assert fn({"behavioral": {"training_hours_per_year": 9001}}) is False


def test_check_training_hours_passes_on_missing_field():
    """Silence on missing field is the documented V1 stance (mirrors intake_consistency_rules)."""
    fn = PREDICATES["check_training_hours_per_year_over"]
    assert fn({}) is True


# --- 1b. annual_work_days > 365 ------------------------------------------


def test_check_annual_work_days_passes_for_normal_value():
    fn = PREDICATES["check_annual_work_days_over"]
    assert fn({"behavioral": {"annual_work_days": 250}}) is True


def test_check_annual_work_days_fails_when_over_365():
    fn = PREDICATES["check_annual_work_days_over"]
    assert fn({"behavioral": {"annual_work_days": 400}}) is False


# --- 1c. weekly_work_hours > 168 ------------------------------------------


def test_check_weekly_work_hours_passes_for_normal_value():
    fn = PREDICATES["check_weekly_work_hours_over"]
    assert fn({"behavioral": {"weekly_work_hours": 40}}) is True


def test_check_weekly_work_hours_fails_when_over_168():
    fn = PREDICATES["check_weekly_work_hours_over"]
    assert fn({"behavioral": {"weekly_work_hours": 200}}) is False


# --- 1d. start_year plausible (today.year ± 20 / +10) --------------------


def test_check_start_year_passes_for_current_year():
    fn = PREDICATES["check_start_year_plausible"]
    assert fn({"plan": {"start_year": THIS_YEAR}}) is True


def test_check_start_year_fails_for_year_too_old():
    fn = PREDICATES["check_start_year_plausible"]
    assert fn({"plan": {"start_year": THIS_YEAR - 50}}) is False


def test_check_start_year_fails_for_year_too_far_future():
    fn = PREDICATES["check_start_year_plausible"]
    assert fn({"plan": {"start_year": THIS_YEAR + 30}}) is False


# --- 1e. birth_date vs age (±1y) -----------------------------------------


def test_check_birth_vs_age_passes_when_consistent():
    fn = PREDICATES["check_birth_vs_age"]
    # Pick a birth_date that yields exactly age=40 today. We must use
    # yesterday's month/day so the "born today" boundary doesn't bite.
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    bd = datetime.date(today.year - 40, yesterday.month, yesterday.day).isoformat()
    assert fn({"identity": {"birth_date": bd, "age": 40}}) is True


def test_check_birth_vs_age_fails_when_off_by_5_years():
    fn = PREDICATES["check_birth_vs_age"]
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    bd = datetime.date(today.year - 40, yesterday.month, yesterday.day).isoformat()
    # Reported age 45 — but actual is 40. Off by 5 years > tolerance (1y).
    assert fn({"identity": {"birth_date": bd, "age": 45}}) is False


def test_check_birth_vs_age_passes_on_malformed_date():
    """Malformed birth_date is silent — never violation."""
    fn = PREDICATES["check_birth_vs_age"]
    assert fn({"identity": {"birth_date": "not-a-date", "age": 40}}) is True


# --- 1f. desired_amount > 50 億 (500,000 万円) sanity ceiling ------------


def test_check_desired_amount_passes_for_normal_value():
    fn = PREDICATES["check_desired_amount_sanity_upper"]
    assert fn({"plan": {"desired_amount_man_yen": 5000}}) is True  # 5000万 = 5千万円


def test_check_desired_amount_fails_when_over_500000_man_yen():
    fn = PREDICATES["check_desired_amount_sanity_upper"]
    # 600,000 万円 = 60 億円 — over the 50 億 ceiling.
    assert fn({"plan": {"desired_amount_man_yen": 600000}}) is False


# ---------------------------------------------------------------------------
# 2. resolve_predicate — registry lookup + miss handling
# ---------------------------------------------------------------------------


def test_resolve_predicate_returns_callable_for_known_ref():
    fn = resolve_predicate("autonomath.intake.check_annual_work_days_over")
    assert callable(fn)


def test_resolve_predicate_returns_none_for_unknown_ref():
    assert resolve_predicate("autonomath.intake.totally_made_up") is None


def test_resolve_predicate_returns_none_for_wrong_prefix():
    assert resolve_predicate("some.other.module.check_annual_work_days_over") is None


# ---------------------------------------------------------------------------
# 3. _canonical_applicant_hash — stable + deterministic
# ---------------------------------------------------------------------------


def test_applicant_hash_is_stable_across_key_order():
    h1 = _canonical_applicant_hash({"a": 1, "b": 2})
    h2 = _canonical_applicant_hash({"b": 2, "a": 1})
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_applicant_hash_differs_for_different_payloads():
    h1 = _canonical_applicant_hash({"a": 1})
    h2 = _canonical_applicant_hash({"a": 2})
    assert h1 != h2


# ---------------------------------------------------------------------------
# 4. _validate_impl — full eval against the 6 'intake' rules
# ---------------------------------------------------------------------------


def _safe_birth_date_for_age(age: int) -> str:
    """A birth_date that yields exactly ``age`` today (uses yesterday's
    month/day to avoid the leap-day boundary)."""
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    return datetime.date(today.year - age, yesterday.month, yesterday.day).isoformat()


def test_validate_impl_clean_payload_all_pass():
    """A consistent applicant payload passes all 6 generic intake checks."""
    payload = {
        "behavioral": {
            "training_hours_per_year": 200,
            "annual_work_days": 240,
            "weekly_work_hours": 40,
        },
        "plan": {"start_year": THIS_YEAR, "desired_amount_man_yen": 1500},
        "identity": {"birth_date": _safe_birth_date_for_age(40), "age": 40},
    }
    res = _validate_impl(payload, entity_id=None, scope="intake")
    assert res["scope"] == "intake"
    assert res["entity_id"] is None
    assert res["total"] >= 6
    # No rule should report failed; passed + deferred together cover the set.
    # (Persistence into am_validation_result can transiently fail if a writer
    # holds the DB lock; the predicate itself still evaluates True, but if
    # the row was previously cached as deferred we tolerate that bucket too.)
    assert res["summary"]["failed"] == 0
    assert res["summary"]["passed"] + res["summary"]["deferred"] >= 6


def test_validate_impl_dirty_payload_flags_violations():
    """Inject sentinel-violation values; failed count must be > 0."""
    payload = {
        "behavioral": {
            "training_hours_per_year": 99999,  # > 8760
            "annual_work_days": 999,  # > 365
            "weekly_work_hours": 9999,  # > 168
        },
        "plan": {
            "start_year": 1900,  # outside ±20y
            "desired_amount_man_yen": 999999,  # > 50 億
        },
    }
    res = _validate_impl(payload, entity_id=None, scope="intake")
    assert res["summary"]["failed"] >= 4
    # Each failed result carries severity + message
    for r in res["results"]:
        if r["passed"] is False:
            assert r["severity"] in ("info", "warning", "critical")
            assert r["predicate_kind"] == "python_dispatch"


def test_validate_impl_rejects_non_dict_applicant_data():
    res = _validate_impl("not_a_dict", entity_id=None, scope="intake")  # type: ignore[arg-type]
    err = res.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "missing_required_arg"


def test_validate_impl_returns_canonical_summary_keys():
    res = _validate_impl({}, entity_id=None, scope="intake")
    summary = res["summary"]
    assert set(summary.keys()) == {"passed", "failed", "deferred"}
    assert "applicant_hash" in res
    assert isinstance(res["applicant_hash"], str)


def test_validate_tool_alias_matches_impl():
    """The @mcp.tool wrapper delegates to _validate_impl with same signature."""
    res = validate(applicant_data={}, entity_id=None, scope="intake")
    assert isinstance(res, dict)
    assert "summary" in res


# ---------------------------------------------------------------------------
# 5. REST endpoint — POST /v1/am/validate
# ---------------------------------------------------------------------------


def test_rest_validate_clean_payload_returns_200(client):
    bd = _safe_birth_date_for_age(40)
    body = {
        "applicant_data": {
            "behavioral": {
                "training_hours_per_year": 200,
                "annual_work_days": 240,
                "weekly_work_hours": 40,
            },
            "plan": {"start_year": THIS_YEAR, "desired_amount_man_yen": 1500},
            "identity": {"birth_date": bd, "age": 40},
        },
        "scope": "intake",
    }
    r = client.post("/v1/am/validate", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["scope"] == "intake"
    # Per `_validate_impl`: persistence into am_validation_result can race
    # with WAL writers and silently land rows in the deferred bucket. The
    # predicate evaluation itself never reports failed for this clean input.
    assert j["summary"]["failed"] == 0


def test_rest_validate_dirty_payload_flags_failures(client):
    body = {
        "applicant_data": {
            "behavioral": {"weekly_work_hours": 9999},
            "plan": {"start_year": 1900, "desired_amount_man_yen": 999999},
        },
        "scope": "intake",
    }
    r = client.post("/v1/am/validate", json=body)
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["failed"] >= 1
