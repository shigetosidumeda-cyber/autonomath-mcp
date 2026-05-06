"""POST /v1/intel/bundle/optimal — houjin → 最適 program bundle.

Single-call optimizer: customer LLM passes a houjin id (or houjin dict)
and receives the best mutually-compatible bundle of programs joined to
expected_amount totals + conflict-avoidance metadata + an optimization
log + runner-up alternatives. Avoids the 3-call fan-out across
``/v1/intel/probability_radar`` × N + ``/v1/funding_stack/check`` ×
pair-grid that customers used to assemble manually.

Hard constraints (memory ``feedback_no_operator_llm_api``)
-----------------------------------------------------------
* NO LLM call inside this endpoint. Pure SQLite SELECT + Python
  greedy independent-set + sort. Algorithm is deterministic on
  (corpus_snapshot_id, request payload).
* Pure read — never writes to autonomath.db.
* Graceful degradation — when a substrate table is missing on a fresh
  dev DB, the affected axis returns empty rather than 500.

Algorithm
---------
1. Build the eligible candidate pool by joining
   ``am_recommended_programs`` (precomputed top-N per houjin) with
   ``am_program_eligibility_predicate`` (predicate filter — drop any
   program with a *required* predicate the houjin demonstrably fails,
   leave unknown predicates alone per ``missing_axis = unknown`` rule).
2. Build a conflict graph from ``am_funding_stack_empirical`` (any
   row with ``conflict_flag = 1`` is a hard incompatibility) plus
   mutual-exclusion predicates surfaced via ``predicate_kind`` in
   ``{'jsic_not_in', 'region_not_in', 'no_enforcement_within_years'}``.
3. Solve weighted maximum independent set greedily by dropping the
   objective function (``max_amount`` / ``max_count`` / ``min_overlap``)
   onto the candidate ordering and skipping conflict-edged neighbors.
4. Capture the top ``bundle_size`` selected nodes; the remaining
   feasible bundles (3 alternatives) are emitted in
   ``runner_up_bundles`` so the customer LLM can present "or instead".
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api._response_models import IntelBundleOptimalResponse
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.intel_bundle_optimal")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# Hard ceilings — caller cannot overshoot.
_MIN_BUNDLE: int = 1
_MAX_BUNDLE: int = 10
# Candidate pool ceiling. We pull up to this many recommended programs
# per houjin from am_recommended_programs (precomputed top-50). Keeping
# this above bundle_size ensures the greedy walk has options when the
# top-K nodes form a conflict clique.
_MAX_CANDIDATES: int = 50

_BUNDLE_DISCLAIMER = (
    "本 bundle は am_recommended_programs (採択者プロファイル類似度) + "
    "am_program_eligibility_predicate (機械的 predicate 評価) + "
    "am_funding_stack_empirical (実績 co-adoption) を SQL + 決定論的"
    "貪欲アルゴリズムで合成した **統計的最適化提案** であり、「採択保証」"
    "「重複受給可」の確約ではない。expected_amount は programs.amount_max_man_yen / "
    "amount_min_man_yen の rollup であり、申請時の実支給額ではない。"
    "predicate 不足 (missing axis = unknown) は eligible 扱いだが最終確認は "
    "primary source + 行政書士・中小企業診断士へ。税理士法 §52 / 行政書士法 §1 "
    "の代替ではない。"
)


# ---------------------------------------------------------------------------
# Predicate kinds that imply a *mutual exclusion* edge between two programs
# (in addition to am_funding_stack_empirical conflict_flag rows). When two
# programs both carry one of these kinds with disjoint value sets, they
# cannot both be granted to the same houjin.
# ---------------------------------------------------------------------------
_MUTEX_PREDICATE_KINDS: frozenset[str] = frozenset(
    {"jsic_not_in", "region_not_in", "no_enforcement_within_years"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> str:
    """Resolve autonomath.db path. Mirrors api/houjin.py::_autonomath_db_path."""
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return raw
    return str(settings.autonomath_db_path)


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Read-only connection to autonomath.db. Returns ``None`` when missing."""
    p = _autonomath_db_path()
    if not p or not os.path.exists(p):
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.OperationalError:
            pass
        return conn
    except sqlite3.OperationalError:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _normalize_houjin(value: str | None) -> str:
    """Strip whitespace + leading 'T' (invoice registration prefix)."""
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s


def _is_valid_houjin(value: str) -> bool:
    return bool(value) and value.isdigit() and len(value) == 13


def _safe_json_loads(blob: str | None) -> Any:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Request / response shape
# ---------------------------------------------------------------------------


class BundleOptimalRequest(BaseModel):
    """POST body for /v1/intel/bundle/optimal.

    ``houjin_id`` may be either a 13-digit 法人番号 string (with or without
    'T' prefix) OR a free-form dict allowing the customer LLM to pass an
    in-memory profile when the houjin is not in the gBizINFO mirror.
    """

    houjin_id: Annotated[
        str | dict[str, Any],
        Field(
            description=(
                "13-digit 法人番号 (with or without 'T' prefix), OR a dict "
                "{houjin_bangou?, prefecture?, jsic_major?, capital_yen?, "
                "employee_count?} for in-memory profiles."
            ),
        ),
    ]
    bundle_size: Annotated[
        int,
        Field(
            default=5,
            ge=_MIN_BUNDLE,
            le=_MAX_BUNDLE,
            description=(
                f"Target bundle size (1..{_MAX_BUNDLE}). The optimizer "
                "may return fewer programs if the candidate pool is "
                "exhausted by conflicts."
            ),
        ),
    ] = 5
    objective: Annotated[
        Literal["max_amount", "max_count", "min_overlap"],
        Field(
            default="max_amount",
            description=(
                "max_amount = pure expected_amount_max DESC. "
                "max_count = ignore amount, just fill bundle_size. "
                "min_overlap = prefer programs with fewest conflict edges."
            ),
        ),
    ] = "max_amount"
    exclude_program_ids: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "Hard exclusions — these program_unified_id values will "
                "NEVER appear in the bundle (caller has already chosen them, "
                "rejected them, or knows they are infeasible)."
            ),
            max_length=_MAX_CANDIDATES,
        ),
    ]
    prefer_categories: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "JSIC major letters or program_kind tokens used as a soft "
                "ordering bias — eligible programs whose authority_level / "
                "program_kind matches one of these sort earlier within the "
                "objective tie-break."
            ),
            max_length=20,
        ),
    ]


# ---------------------------------------------------------------------------
# Candidate pool — pulls eligibility-predicate-filtered TOP-N from
# am_recommended_programs and joins programs (jpi_programs) for amount data.
# ---------------------------------------------------------------------------


def _resolve_houjin(payload: BundleOptimalRequest) -> tuple[str, dict[str, Any]]:
    """Normalize ``payload.houjin_id`` into ``(bangou, profile_dict)``.

    Returns ``("", profile)`` when the caller passed a dict without a
    ``houjin_bangou`` field — predicate evaluation can still proceed
    against the in-memory profile, but precomputed-recommendations lookups
    will return an empty pool (caller falls back to manual selection).
    """
    raw = payload.houjin_id
    if isinstance(raw, dict):
        bangou = _normalize_houjin(str(raw.get("houjin_bangou") or ""))
        profile = {
            "houjin_bangou": bangou or None,
            "prefecture": raw.get("prefecture"),
            "jsic_major": raw.get("jsic_major"),
            "capital_yen": raw.get("capital_yen"),
            "employee_count": raw.get("employee_count"),
        }
        return bangou, profile
    bangou = _normalize_houjin(str(raw))
    return bangou, {"houjin_bangou": bangou or None}


def _fetch_houjin_profile(
    am_conn: sqlite3.Connection,
    bangou: str,
) -> dict[str, Any]:
    """Fetch (capital_yen, employee_count, prefecture, jsic_major) from the
    autonomath corpus. Best-effort — missing facts return ``None``.

    Reads ``am_adopted_company_features`` first (wave24_157 dominant_jsic_major
    + capital_yen + employee_count crystalized). Falls back to
    ``am_entity_facts`` for capital / employee fields that have no rollup.
    """
    profile: dict[str, Any] = {
        "capital_yen": None,
        "employee_count": None,
        "prefecture": None,
        "jsic_major": None,
    }
    if not bangou:
        return profile
    if _table_exists(am_conn, "am_adopted_company_features"):
        try:
            row = am_conn.execute(
                "SELECT dominant_jsic_major, capital_yen, employee_count, prefecture "
                "FROM am_adopted_company_features WHERE houjin_bangou = ? LIMIT 1",
                (bangou,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            keys = row.keys() if hasattr(row, "keys") else ()
            if "dominant_jsic_major" in keys:
                profile["jsic_major"] = row["dominant_jsic_major"]
            if "capital_yen" in keys:
                profile["capital_yen"] = row["capital_yen"]
            if "employee_count" in keys:
                profile["employee_count"] = row["employee_count"]
            if "prefecture" in keys:
                profile["prefecture"] = row["prefecture"]
    return profile


def _fetch_candidate_pool(
    am_conn: sqlite3.Connection,
    *,
    bangou: str,
    exclude_ids: set[str],
    program_table: str,
) -> list[dict[str, Any]]:
    """Return the recommended program candidate pool joined to programs.

    Strategy:
      1. If ``am_recommended_programs`` exists for this houjin, pull the
         precomputed top-N (rank ASC).
      2. Otherwise fall back to a tier-ordered tail of the jpi_programs /
         programs table — this gives the in-memory-profile path *some*
         signal even when the gBizINFO recommender hasn't computed for
         this houjin.

    Each row returns
    ``{program_id, name, score, amount_min_man_yen, amount_max_man_yen,
       authority_level, program_kind, tier}``.
    """
    pool: list[dict[str, Any]] = []
    if (
        bangou
        and _table_exists(am_conn, "am_recommended_programs")
        and _table_exists(am_conn, program_table)
    ):
        try:
            rows = am_conn.execute(
                f"""SELECT arp.program_unified_id AS program_id,
                          arp.score              AS score,
                          arp.rank               AS rank,
                          prg.primary_name       AS name,
                          prg.amount_min_man_yen AS amin,
                          prg.amount_max_man_yen AS amax,
                          prg.authority_level    AS auth_level,
                          prg.program_kind       AS kind,
                          prg.tier               AS tier
                     FROM am_recommended_programs arp
                LEFT JOIN {program_table} prg
                       ON prg.unified_id = arp.program_unified_id
                    WHERE arp.houjin_bangou = ?
                 ORDER BY arp.rank ASC
                    LIMIT ?""",
                (bangou, _MAX_CANDIDATES),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("am_recommended_programs join failed: %s", exc)
            rows = []
        for r in rows:
            pid = r["program_id"]
            if not pid or pid in exclude_ids:
                continue
            pool.append(
                {
                    "program_id": pid,
                    "name": r["name"] or pid,
                    "score": float(r["score"] or 0.0),
                    "rank": int(r["rank"] or 0),
                    "amount_min_man_yen": r["amin"],
                    "amount_max_man_yen": r["amax"],
                    "authority_level": r["auth_level"],
                    "program_kind": r["kind"],
                    "tier": r["tier"],
                }
            )

    # Fall-through: if no recommendations exist, take a tier-ordered
    # representative slice so the optimizer has *something* to chew on.
    # Keeps the in-memory-profile flow functional on fresh dev DBs.
    if not pool and _table_exists(am_conn, program_table):
        try:
            rows = am_conn.execute(
                f"""SELECT unified_id AS program_id,
                          primary_name AS name,
                          amount_min_man_yen AS amin,
                          amount_max_man_yen AS amax,
                          authority_level    AS auth_level,
                          program_kind       AS kind,
                          tier               AS tier
                     FROM {program_table}
                    WHERE COALESCE(excluded, 0) = 0
                      AND tier IN ('S','A','B','C')
                 ORDER BY CASE tier
                              WHEN 'S' THEN 0
                              WHEN 'A' THEN 1
                              WHEN 'B' THEN 2
                              ELSE 3 END,
                          amount_max_man_yen DESC
                    LIMIT ?""",
                (_MAX_CANDIDATES,),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("fallback program tier scan failed: %s", exc)
            rows = []
        for r in rows:
            pid = r["program_id"]
            if not pid or pid in exclude_ids:
                continue
            pool.append(
                {
                    "program_id": pid,
                    "name": r["name"] or pid,
                    "score": 0.5,  # heuristic baseline for unranked rows
                    "rank": 0,
                    "amount_min_man_yen": r["amin"],
                    "amount_max_man_yen": r["amax"],
                    "authority_level": r["auth_level"],
                    "program_kind": r["kind"],
                    "tier": r["tier"],
                }
            )
    return pool


def _resolve_program_table(am_conn: sqlite3.Connection) -> str:
    """Pick whichever programs-mirror exists on this volume.

    Production runs against ``jpi_programs`` (autonomath.db mirror of
    jpintel.db). Dev fixtures often only ship ``programs`` (the jpintel
    table itself) — we soft-degrade so the test suite can use either.
    """
    if _table_exists(am_conn, "jpi_programs"):
        return "jpi_programs"
    return "programs"


# ---------------------------------------------------------------------------
# Predicate filter — drop programs whose required predicate the houjin fails.
# ---------------------------------------------------------------------------


def _evaluate_predicate(
    predicate_kind: str,
    operator: str,
    value_text: str | None,
    value_num: float | None,
    value_json: str | None,
    profile: dict[str, Any],
) -> bool:
    """Return ``True`` when houjin *passes* the predicate (or it's unknown).

    Per docs, ``missing axis = unknown`` (NOT 'no constraint'), so we
    return ``True`` (eligible) on missing-fact paths — that keeps the
    candidate pool wide and lets the customer LLM flag manually-verified
    failures via ``exclude_program_ids`` on a follow-up call.
    """
    # Profile axes we know how to evaluate.
    capital = profile.get("capital_yen")
    employees = profile.get("employee_count")
    prefecture = profile.get("prefecture")
    jsic_major = profile.get("jsic_major")

    def _num_cmp(houjin_val: Any, target: float, op: str) -> bool:
        if houjin_val is None:
            return True  # unknown axis → pass
        try:
            hv = float(houjin_val)
        except (TypeError, ValueError):
            return True
        if op == "<=":
            return hv <= target
        if op == "<":
            return hv < target
        if op == ">=":
            return hv >= target
        if op == ">":
            return hv > target
        if op == "=":
            return hv == target
        if op == "!=":
            return hv != target
        return True

    if predicate_kind == "capital_max" and value_num is not None:
        return _num_cmp(capital, value_num, operator or "<=")
    if predicate_kind == "capital_min" and value_num is not None:
        return _num_cmp(capital, value_num, operator or ">=")
    if predicate_kind == "employee_max" and value_num is not None:
        return _num_cmp(employees, value_num, operator or "<=")
    if predicate_kind == "employee_min" and value_num is not None:
        return _num_cmp(employees, value_num, operator or ">=")
    if predicate_kind in {"jsic_in", "jsic_not_in"}:
        if not jsic_major:
            return True
        targets = _safe_json_loads(value_json) or []
        if value_text:
            targets.append(value_text)
        if not targets:
            return True
        contains = jsic_major in targets
        return contains if predicate_kind == "jsic_in" else not contains
    if predicate_kind in {"region_in", "region_not_in"}:
        if not prefecture:
            return True
        targets = _safe_json_loads(value_json) or []
        if value_text:
            targets.append(value_text)
        if not targets:
            return True
        contains = prefecture in targets
        return contains if predicate_kind == "region_in" else not contains
    # Other predicate kinds are harmless to skip — we can't evaluate
    # invoice/tax_compliance/business_age axes from the rollup table
    # alone, so honor the missing_axis=unknown rule.
    return True


def _filter_by_predicates(
    am_conn: sqlite3.Connection,
    *,
    pool: list[dict[str, Any]],
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Drop pool entries whose REQUIRED predicates the houjin demonstrably fails.

    Returns ``(eligible_pool, dropped_count)``. ``dropped_count`` feeds
    the ``optimization_log.alternative_considered`` field.
    """
    if not _table_exists(am_conn, "am_program_eligibility_predicate"):
        # Predicate cache empty — pass-through with a 0 drop count.
        return pool, 0
    eligible: list[dict[str, Any]] = []
    dropped = 0
    for entry in pool:
        pid = entry["program_id"]
        try:
            preds = am_conn.execute(
                "SELECT predicate_kind, operator, value_text, value_num, value_json "
                "FROM am_program_eligibility_predicate "
                "WHERE program_unified_id = ? AND is_required = 1",
                (pid,),
            ).fetchall()
        except sqlite3.Error:
            preds = []
        passed = True
        for p in preds:
            if not _evaluate_predicate(
                p["predicate_kind"],
                p["operator"],
                p["value_text"],
                p["value_num"],
                p["value_json"],
                profile,
            ):
                passed = False
                break
        if passed:
            eligible.append(entry)
        else:
            dropped += 1
    return eligible, dropped


# ---------------------------------------------------------------------------
# Conflict graph — am_funding_stack_empirical conflict_flag rows + mutex preds.
# ---------------------------------------------------------------------------


def _build_conflict_graph(
    am_conn: sqlite3.Connection,
    *,
    candidate_ids: list[str],
) -> tuple[dict[str, set[str]], int]:
    """Build an undirected conflict graph keyed by program_id.

    Returns ``(adj, edge_count)``. Edge sources:
      * ``am_funding_stack_empirical`` rows with ``conflict_flag = 1``.
      * Mutual-exclusion predicate pairs (jsic_not_in / region_not_in /
        no_enforcement_within_years) — implementation-light: any two
        programs both carrying a ``no_enforcement_within_years`` predicate
        with the SAME value_num are NOT mutually exclusive (they share a
        condition the houjin must satisfy once); only disjoint sets edge.
        We start with the funding_stack table and leave the mutex layer
        as a no-op stub when the table is missing.
    """
    adj: dict[str, set[str]] = {pid: set() for pid in candidate_ids}
    edge_count = 0
    if not candidate_ids:
        return adj, 0
    if _table_exists(am_conn, "am_funding_stack_empirical"):
        # Use a placeholder list to keep the SQL compact and indexable.
        placeholders = ",".join(["?"] * len(candidate_ids))
        try:
            rows = am_conn.execute(
                f"""SELECT program_a_id, program_b_id
                      FROM am_funding_stack_empirical
                     WHERE conflict_flag = 1
                       AND program_a_id IN ({placeholders})
                       AND program_b_id IN ({placeholders})""",
                (*candidate_ids, *candidate_ids),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("am_funding_stack_empirical scan failed: %s", exc)
            rows = []
        for r in rows:
            a, b = r["program_a_id"], r["program_b_id"]
            if a in adj and b in adj and b not in adj[a]:
                adj[a].add(b)
                adj[b].add(a)
                edge_count += 1
    return adj, edge_count


# ---------------------------------------------------------------------------
# Greedy weighted maximum independent set with objective-aware ranking.
# ---------------------------------------------------------------------------


def _objective_key(
    entry: dict[str, Any],
    *,
    objective: str,
    prefer_set: set[str],
    adj: dict[str, set[str]],
) -> tuple[float, ...]:
    """Sort key — higher is better. Returned as a tuple of negatives so
    the standard ``sort()`` (ascending) yields highest-priority first.
    """
    amax = entry.get("amount_max_man_yen") or 0
    amin = entry.get("amount_min_man_yen") or 0
    score = entry.get("score") or 0.0
    pref_bonus = (
        1
        if (
            (entry.get("authority_level") in prefer_set)
            or (entry.get("program_kind") in prefer_set)
        )
        else 0
    )
    deg = len(adj.get(entry["program_id"], ()))

    if objective == "max_count":
        # Prefer low-degree first so we can fit more, then preference,
        # then score, then amount as final tie-break.
        return (deg, -pref_bonus, -score, -amax)
    if objective == "min_overlap":
        # Fewest conflict edges, then score / amount.
        return (deg, -score, -pref_bonus, -amax)
    # max_amount (default): pure expected_amount_max DESC, with score +
    # preference acting as tie-break at equal amount.
    return (-float(amax), -float(amin), -score, -pref_bonus, deg)


def _greedy_independent_set(
    *,
    candidates: list[dict[str, Any]],
    adj: dict[str, set[str]],
    objective: str,
    bundle_size: int,
    prefer_set: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Greedy max-weight IS. Returns ``(selected, iterations)``.

    Because we walk the sorted list once and skip conflicting nodes, the
    iteration count equals ``len(candidates)`` in the worst case. We
    expose the count for the optimization_log envelope.
    """
    sorted_pool = sorted(
        candidates,
        key=lambda e: _objective_key(e, objective=objective, prefer_set=prefer_set, adj=adj),
    )
    selected: list[dict[str, Any]] = []
    blocked: set[str] = set()
    iterations = 0
    for entry in sorted_pool:
        iterations += 1
        if len(selected) >= bundle_size:
            break
        pid = entry["program_id"]
        if pid in blocked:
            continue
        selected.append(entry)
        # Mark every neighbor as blocked.
        for nb in adj.get(pid, ()):
            blocked.add(nb)
        blocked.add(pid)
    return selected, iterations


def _runner_up_bundles(
    *,
    candidates: list[dict[str, Any]],
    adj: dict[str, set[str]],
    bundle_size: int,
    prefer_set: set[str],
    chosen_ids: set[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Generate ``limit`` alternative bundles by swapping one chosen node
    for the next-best non-chosen feasible node, then re-running the greedy
    walk on the modified candidate set. Each alternative carries a
    ``why_not_chosen`` string explaining the swap.
    """
    alternatives: list[dict[str, Any]] = []
    chosen_list = sorted(chosen_ids)
    if not chosen_list:
        return alternatives
    # Iterate "swap candidates" — programs not in the chosen bundle.
    swap_pool = [c for c in candidates if c["program_id"] not in chosen_ids]
    for swap in swap_pool[:limit]:
        # Build a candidate set that *forces* the swap by excluding one of
        # the chosen ids (rotates through chosen_list to vary alternatives).
        forced_out = chosen_list[len(alternatives) % len(chosen_list)]
        modified = [c for c in candidates if c["program_id"] != forced_out]
        rerun, _ = _greedy_independent_set(
            candidates=modified,
            adj=adj,
            objective="max_amount",
            bundle_size=bundle_size,
            prefer_set=prefer_set,
        )
        alt_ids = [c["program_id"] for c in rerun]
        if not alt_ids or set(alt_ids) == chosen_ids:
            continue
        total_max = sum(int(c.get("amount_max_man_yen") or 0) for c in rerun)
        total_yen = total_max * 10000
        alternatives.append(
            {
                "bundle": alt_ids,
                "total_amount": total_yen,
                "why_not_chosen": (
                    f"swap excluded {forced_out!r} → forces "
                    f"{swap['program_id']!r} into pool; total "
                    f"{total_yen:,} yen vs primary objective."
                ),
            }
        )
        if len(alternatives) >= limit:
            break
    return alternatives


def _decision_support_item(
    signal: str,
    message_ja: str,
    basis: list[str],
    **metrics: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "signal": signal,
        "message_ja": message_ja,
        "basis": basis,
    }
    if metrics:
        item["metrics"] = metrics
    return item


def _build_decision_support(
    *,
    payload: BundleOptimalRequest,
    pool: list[dict[str, Any]],
    eligible: list[dict[str, Any]],
    dropped_pred: int,
    conflict_pairs: int,
    selected: list[dict[str, Any]],
    bundle_rows: list[dict[str, Any]],
    runner_ups: list[dict[str, Any]],
    data_quality: dict[str, Any],
    total_max: int,
) -> dict[str, Any]:
    """Build LLM-facing decision support from already-computed optimizer state."""
    selected_count = len(selected)
    target_count = int(payload.bundle_size)
    unknown_axes = [
        axis
        for axis, value in (data_quality.get("houjin_profile_used") or {}).items()
        if value is None
    ]

    why_this_matters: list[dict[str, Any]] = [
        _decision_support_item(
            "candidate_pool_shortlist",
            (
                f"{len(pool)}件の候補からpredicate評価と併用排他を同時に見て"
                f"{selected_count}件の主案に絞っています。"
            ),
            ["data_quality.candidate_pool_size", "bundle[]", "conflict_avoidance"],
            candidate_pool_size=len(pool),
            eligible_after_predicate_filter=len(eligible),
            selected_count=selected_count,
        )
    ]
    if total_max > 0:
        why_this_matters.append(
            _decision_support_item(
                "expected_amount_rollup",
                (
                    f"主案のexpected_amount_max合計は{total_max:,}円です。"
                    "上限額ベースの比較軸であり、採択額や受給保証ではありません。"
                ),
                ["bundle_total.expected_amount_max", "bundle[].expected_amount_max"],
                expected_amount_max=total_max,
            )
        )
    if conflict_pairs > 0:
        why_this_matters.append(
            _decision_support_item(
                "conflict_avoidance",
                (
                    f"実績併用データ上のconflict_flagペア{conflict_pairs}件を"
                    "主案の同時選定から外しています。"
                ),
                ["conflict_avoidance.conflict_pairs_avoided"],
                conflict_pairs_avoided=int(conflict_pairs),
            )
        )
    else:
        why_this_matters.append(
            _decision_support_item(
                "no_conflict_edges_detected",
                "候補プール内では実績併用データ上のconflict_flagペアは検出されませんでした。",
                ["conflict_avoidance.conflict_pairs_avoided"],
                conflict_pairs_avoided=0,
            )
        )

    decision_insights: list[dict[str, Any]] = [
        _decision_support_item(
            "objective_applied",
            f"選定はobjective={payload.objective!r}の順序で実行しています。",
            ["optimization_log.algorithm", "request.objective"],
            objective=payload.objective,
        )
    ]
    if selected_count < target_count:
        decision_insights.append(
            _decision_support_item(
                "bundle_size_not_filled",
                (
                    f"希望{target_count}件に対して{selected_count}件の主案です。"
                    "predicate除外または併用排他で候補が不足した可能性があります。"
                ),
                ["bundle[]", "data_quality", "conflict_avoidance"],
                requested_bundle_size=target_count,
                selected_count=selected_count,
            )
        )
    else:
        decision_insights.append(
            _decision_support_item(
                "bundle_size_filled",
                f"希望件数{target_count}件に対して主案{selected_count}件を充足しています。",
                ["bundle[]"],
                requested_bundle_size=target_count,
                selected_count=selected_count,
            )
        )
    decision_insights.append(
        _decision_support_item(
            "predicate_filter",
            (
                f"必須predicateで{int(dropped_pred)}件を除外し、"
                f"{len(eligible)}件をeligibleとして残しています。"
            ),
            ["data_quality.predicate_dropped", "data_quality.eligible_after_predicate_filter"],
            predicate_dropped=int(dropped_pred),
            eligible_after_predicate_filter=len(eligible),
        )
    )
    if runner_ups:
        decision_insights.append(
            _decision_support_item(
                "runner_up_alternatives",
                f"{len(runner_ups)}件のrunner-up bundleを返しています。主案との差し替え比較に使えます。",
                ["runner_up_bundles[]"],
                runner_up_count=len(runner_ups),
            )
        )
    if unknown_axes:
        decision_insights.append(
            _decision_support_item(
                "profile_axes_unknown",
                (
                    "法人profileの一部軸がunknownのため、該当predicateはeligible扱いです。"
                    "確認前提で読んでください。"
                ),
                ["data_quality.houjin_profile_used"],
                unknown_axes=unknown_axes,
            )
        )

    next_actions: list[dict[str, Any]] = [
        _decision_support_item(
            "verify_primary_sources",
            "bundle[]の各制度について、公募要領・公式情報で対象要件、締切、併用制限を確認してください。",
            ["bundle[].program_id", "_disclaimer"],
        ),
        _decision_support_item(
            "confirm_professional_review",
            "申請可否、重複受給、税務処理は行政書士・中小企業診断士・税理士などの専門家確認に回してください。",
            ["_disclaimer"],
        ),
    ]
    if unknown_axes:
        next_actions.insert(
            0,
            _decision_support_item(
                "fill_missing_profile_axes",
                "capital_yen、employee_count、prefecture、jsic_majorの不足値を補うとpredicate判定の精度が上がります。",
                ["data_quality.houjin_profile_used"],
                unknown_axes=unknown_axes,
            ),
        )
    if runner_ups:
        next_actions.append(
            _decision_support_item(
                "compare_runner_ups",
                "runner_up_bundles[]を主案と比較し、既採択・申請済み・社内優先度に合わない制度をexclude_program_idsで外して再実行してください。",
                ["runner_up_bundles[]", "request.exclude_program_ids"],
            )
        )

    return {
        "schema_version": "v1",
        "generated_from": [
            "pool",
            "eligible",
            "dropped_pred",
            "conflict_pairs",
            "selected",
            "bundle_rows",
            "runner_ups",
            "data_quality",
        ],
        "why_this_matters": why_this_matters,
        "decision_insights": decision_insights,
        "next_actions": next_actions,
    }


# ---------------------------------------------------------------------------
# Envelope assembly
# ---------------------------------------------------------------------------


def _build_envelope(
    *,
    am_conn: sqlite3.Connection,
    payload: BundleOptimalRequest,
    bangou: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    _t0 = time.perf_counter()

    program_table = _resolve_program_table(am_conn)
    exclude_ids = set(payload.exclude_program_ids or [])

    # 1. Candidate pool (recommendations + program join).
    pool = _fetch_candidate_pool(
        am_conn,
        bangou=bangou,
        exclude_ids=exclude_ids,
        program_table=program_table,
    )

    # 2. Predicate filter.
    eligible, dropped_pred = _filter_by_predicates(am_conn, pool=pool, profile=profile)

    # 3. Conflict graph (am_funding_stack_empirical).
    candidate_ids = [e["program_id"] for e in eligible]
    adj, conflict_pairs = _build_conflict_graph(am_conn, candidate_ids=candidate_ids)

    # 4. Greedy max-IS.
    prefer_set = {p for p in payload.prefer_categories if p}
    selected, iterations = _greedy_independent_set(
        candidates=eligible,
        adj=adj,
        objective=payload.objective,
        bundle_size=payload.bundle_size,
        prefer_set=prefer_set,
    )

    # 5. Bundle envelope rows.
    bundle_rows: list[dict[str, Any]] = []
    total_min = 0
    total_max = 0
    score_sum = 0.0
    selected_ids = {e["program_id"] for e in selected}
    for entry in selected:
        amax = int((entry.get("amount_max_man_yen") or 0) * 10000)
        amin = int((entry.get("amount_min_man_yen") or 0) * 10000)
        total_min += amin
        total_max += amax
        score_sum += float(entry.get("score") or 0.0)
        bundle_rows.append(
            {
                "program_id": entry["program_id"],
                "name": entry.get("name"),
                "eligibility_score": round(float(entry.get("score") or 0.0), 4),
                "expected_amount_min": amin,
                "expected_amount_max": amax,
                # Always [] in optimal output — selected nodes form an
                # independent set by construction.
                "conflict_with_others_in_bundle": [],
            }
        )
    eligibility_avg = round(score_sum / len(selected), 4) if selected else 0.0

    # 6. Runner-up alternatives.
    runner_ups = _runner_up_bundles(
        candidates=eligible,
        adj=adj,
        bundle_size=payload.bundle_size,
        prefer_set=prefer_set,
        chosen_ids=selected_ids,
    )

    elapsed_ms = int((time.perf_counter() - _t0) * 1000)
    data_quality = {
        "candidate_pool_size": len(pool),
        "eligible_after_predicate_filter": len(eligible),
        "predicate_dropped": int(dropped_pred),
        "program_table": program_table,
        "houjin_profile_used": {
            k: profile.get(k) for k in ("capital_yen", "employee_count", "prefecture", "jsic_major")
        },
    }
    decision_support = _build_decision_support(
        payload=payload,
        pool=pool,
        eligible=eligible,
        dropped_pred=dropped_pred,
        conflict_pairs=conflict_pairs,
        selected=selected,
        bundle_rows=bundle_rows,
        runner_ups=runner_ups,
        data_quality=data_quality,
        total_max=total_max,
    )
    body: dict[str, Any] = {
        "houjin_id": bangou or payload.houjin_id,
        "bundle": bundle_rows,
        "bundle_total": {
            "expected_amount_min": total_min,
            "expected_amount_max": total_max,
            "eligibility_avg": eligibility_avg,
        },
        "conflict_avoidance": {
            "conflict_pairs_avoided": int(conflict_pairs),
            "alternative_considered": int(dropped_pred + len(eligible)),
        },
        "optimization_log": {
            "algorithm": "greedy_amount",
            "iterations": int(iterations),
            "time_ms": int(elapsed_ms),
        },
        "runner_up_bundles": runner_ups,
        "data_quality": data_quality,
        "decision_support": decision_support,
        "_disclaimer": _BUNDLE_DISCLAIMER,
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "/bundle/optimal",
    response_model=IntelBundleOptimalResponse,
    summary="Optimal program bundle — conflict-avoiding TOP-N + alternatives",
    description=(
        "Single-call optimizer: customer LLM passes a houjin id (or houjin "
        "dict) and receives the best mutually-compatible bundle of programs "
        "joined to expected_amount totals + conflict-avoidance metadata + "
        "optimization log + runner-up alternatives. Pure SQLite + greedy "
        "max-independent-set. NO LLM call. ¥3 / call.\n\n"
        "**Algorithm**: predicate-filtered eligible pool → conflict graph "
        "(am_funding_stack_empirical conflict_flag rows) → greedy weighted "
        "max-IS sorted by the requested objective.\n\n"
        "**Sensitive**: 行政書士法 §1 / 税理士法 §52 — bundle is a "
        "statistical proposal, NOT a 申請保証 / 受給保証."
    ),
    responses={
        200: {"description": "Optimal bundle envelope with runner-up alternatives."},
        422: {"description": "Malformed houjin_id / out-of-range bundle_size."},
        503: {"description": "autonomath.db unavailable on this volume."},
    },
)
def post_bundle_optimal(
    payload: Annotated[BundleOptimalRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
    request: Request,
    compact: Annotated[
        bool | None,
        Query(
            description=(
                "Opt in to the compact envelope projection. Equivalent to X-JPCite-Compact: 1."
            ),
        ),
    ] = None,
) -> JSONResponse:
    _t0 = time.perf_counter()

    bangou, profile = _resolve_houjin(payload)
    if isinstance(payload.houjin_id, str) and not _is_valid_houjin(bangou):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_bangou",
                "field": "houjin_id",
                "message": (
                    f"houjin_id must be a 13-digit 法人番号 string (with or "
                    f"without 'T' prefix) or a dict; got {payload.houjin_id!r}."
                ),
            },
        )

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unavailable",
                "message": (
                    "autonomath.db not present on this volume; bundle/optimal "
                    "requires the recommended_programs + funding_stack tables."
                ),
            },
        )

    try:
        # Enrich the in-memory profile with am_adopted_company_features facts
        # when the gBizINFO mirror has the 法人 cached. Caller-supplied dict
        # values WIN (we never overwrite a non-null caller-provided field).
        if bangou:
            corpus = _fetch_houjin_profile(am_conn, bangou)
            for k, v in corpus.items():
                if profile.get(k) is None:
                    profile[k] = v

        body = _build_envelope(
            am_conn=am_conn,
            payload=payload,
            bangou=bangou,
            profile=profile,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    # Auditor reproducibility (corpus_snapshot_id + corpus_checksum).
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.bundle_optimal",
        latency_ms=latency_ms,
        result_count=len(body.get("bundle") or []),
        params={
            "houjin_bangou_present": bool(bangou),
            "bundle_size": payload.bundle_size,
            "objective": payload.objective,
            "exclude_count": len(payload.exclude_program_ids or []),
            "prefer_count": len(payload.prefer_categories or []),
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.bundle_optimal",
        request_params={
            "houjin_bangou": bangou,
            "bundle_size": payload.bundle_size,
            "objective": payload.objective,
            "exclude_program_ids": payload.exclude_program_ids,
            "prefer_categories": payload.prefer_categories,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    # Compact-envelope projection (opt-in via ?compact=true / X-JPCite-Compact: 1).
    try:
        if request is not None and wants_compact(request):
            decision_support = body.get("decision_support")
            body = to_compact(body)
            if decision_support is not None:
                body["decision_support"] = decision_support
    except AttributeError:
        pass

    return JSONResponse(content=body)


__all__ = ["router"]
