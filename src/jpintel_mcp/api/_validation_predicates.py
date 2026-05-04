"""Generic intake validation predicates re-implemented locally.

Background
----------
``am_validation_rule`` (migration 047) carries 6 generic ``python_dispatch``
rules whose ``predicate_ref`` is shaped ``autonomath.intake.<func_name>``.
Per project policy (``feedback_autonomath_no_api_use`` + the
"do not import the Autonomath package" rule), jpintel-mcp must not actually
import ``autonomath.intake_consistency_rules``. Instead we re-implement the
6 generic predicates here as small pure functions over the ``applicant_data``
dict that the LLM agent passes into the ``validate`` tool.

Each predicate returns ``True`` when the applicant data PASSES the rule
(i.e. no violation), ``False`` when it FAILS (violation detected). For
predicates that simply cannot evaluate (missing field, wrong type) we
also return ``True`` — silence on missing data is the canonical V1 stance
matching ``intake_consistency_rules.py`` semantics where each ``check_*``
returns ``None`` (= no violation) on missing input.

Predicate suffixes correspond to the suffix of the dotted predicate_ref
after stripping the ``autonomath.intake.`` prefix.
"""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def _get(data: dict[str, Any], path: str) -> Any:
    """Walk ``data`` along a dotted path, returning ``None`` on miss.

    Mirrors ``backend.services.intake_consistency._get`` so dotted paths
    like ``identity.age`` or ``behavioral.training_hours_per_year`` can
    address nested intake dicts without per-rule plumbing.
    """
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


# ---------------------------------------------------------------------------
# Predicate implementations.
#
# Signature: ``(data: dict) -> bool`` where True == passed (no violation).
# Each one MUST be a pure function, no side effects, no I/O.
# ---------------------------------------------------------------------------


def _check_training_hours_per_year_over(data: dict[str, Any]) -> bool:
    """``training_hours_per_year > 8760`` (24*365) is physically impossible."""
    th = _get(data, "behavioral.training_hours_per_year")
    return not (isinstance(th, (int, float)) and th > 8760)


def _check_annual_work_days_over(data: dict[str, Any]) -> bool:
    """``annual_work_days > 365`` is calendar-impossible."""
    wd = _get(data, "behavioral.annual_work_days")
    return not (isinstance(wd, (int, float)) and wd > 365)


def _check_weekly_work_hours_over(data: dict[str, Any]) -> bool:
    """``weekly_work_hours > 168`` (24*7) is physically impossible."""
    wh = _get(data, "behavioral.weekly_work_hours")
    return not (isinstance(wh, (int, float)) and wh > 168)


def _check_start_year_plausible(data: dict[str, Any]) -> bool:
    """``plan.start_year`` must fall within ``today.year - 20 .. today.year + 10``."""
    sy = _get(data, "plan.start_year")
    if not isinstance(sy, int):
        return True
    this_year = datetime.date.today().year
    return not (sy < this_year - 20 or sy > this_year + 10)


def _check_birth_vs_age(data: dict[str, Any]) -> bool:
    """Computed age from ``identity.birth_date`` must match ``identity.age`` ±1y."""
    birth = _get(data, "identity.birth_date")
    age = _get(data, "identity.age")
    if not birth or not isinstance(age, (int, float)):
        return True
    try:
        if isinstance(birth, str):
            y, m, d = birth.split("-")
            birth_date = datetime.date(int(y), int(m), int(d))
        elif isinstance(birth, datetime.date):
            birth_date = birth
        else:
            return True
    except (ValueError, AttributeError):
        return True
    today = datetime.date.today()
    calc_age = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    return abs(calc_age - age) < 1


def _check_desired_amount_sanity_upper(data: dict[str, Any]) -> bool:
    """``plan.desired_amount_man_yen > 500000`` (50 億円) is a magnitude sanity ceiling."""
    desired = _get(data, "plan.desired_amount_man_yen")
    return not (isinstance(desired, (int, float)) and desired > 500000)


# ---------------------------------------------------------------------------
# Registry.
#
# Keyed by the trailing function-name segment of ``predicate_ref`` (i.e.
# everything after ``autonomath.intake.``). When a rule's predicate_ref does
# NOT live in this registry the dispatcher returns passed=null with
# ``message_ja`` = "external dispatch deferred — use jpcite operator workflow".
# ---------------------------------------------------------------------------

PREDICATE_PREFIX = "autonomath.intake."

PREDICATES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "check_training_hours_per_year_over": _check_training_hours_per_year_over,
    "check_annual_work_days_over": _check_annual_work_days_over,
    "check_weekly_work_hours_over": _check_weekly_work_hours_over,
    "check_start_year_plausible": _check_start_year_plausible,
    "check_birth_vs_age": _check_birth_vs_age,
    "check_desired_amount_sanity_upper": _check_desired_amount_sanity_upper,
}


def resolve_predicate(predicate_ref: str) -> Callable[[dict[str, Any]], bool] | None:
    """Look up a predicate by full ``predicate_ref`` string.

    Returns ``None`` when the predicate_ref does not match any locally
    re-implemented function. Caller should treat ``None`` as the
    "external dispatch deferred" branch.
    """
    if not predicate_ref.startswith(PREDICATE_PREFIX):
        return None
    suffix = predicate_ref[len(PREDICATE_PREFIX):]
    return PREDICATES.get(suffix)


__all__ = [
    "PREDICATES",
    "PREDICATE_PREFIX",
    "resolve_predicate",
]
