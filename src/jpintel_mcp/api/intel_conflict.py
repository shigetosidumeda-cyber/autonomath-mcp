"""POST /v1/intel/conflict — 補助金併用 conflict 検出 + 代替提案 (Wave 31-4).

Customer LLM use-case
---------------------
A 税理士 / 行政書士 / 中小企業診断士 user has hand-picked N programs for a
顧問先 (法人 X) and needs to know **before** drafting an application:

  1. Which pairs are *known* to conflict — either because beneficiaries who
     stacked them got flagged in the empirical co-adoption matrix
     (`am_funding_stack_empirical.conflict_flag=1`, exclusion-rule false-
     positive against the published 公募要領 fence) or because the
     eligibility predicate (`am_program_eligibility_predicate`) declares a
     mutual-exclusion clause (NOT_IN / jsic_not_in / etc.).
  2. The *largest compatible subset* (maximum independent set in the
     conflict graph).
  3. The top-3 *alternative bundles* (different combinations of programs
     scored by total ¥) so the customer LLM can present plan A / B / C
     without a follow-up call.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside this endpoint. Pure SQLite SELECT + Python graph
  walk. Cost is ¥3 / call regardless of program_ids cardinality.
* The output is a *machine-readable signal*, not a 行政書士 §1 申請可否
  判断. The disclaimer text fences this explicitly.

Graceful degradation
--------------------
When `am_funding_stack_empirical` or `am_program_eligibility_predicate`
is missing on a fresh dev DB, the corresponding evidence-pair source
returns 0 hits and the table name is appended to
`data_quality.missing_tables`. The customer LLM gets a partial-but-honest
envelope, never a 500.

Sensitive surface
-----------------
§52 / §1 / §72 fence (税理士・行政書士・弁護士) applied via the standard
`_disclaimer` envelope — combo eligibility decisions are deferred to
qualified 士業.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_conflict")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Severity weights for the aggregate `conflict_score` (0.0..1.0). Empirical
#: stack co-adoption data carries the highest weight because it is observed
#: ground truth (法人 actually stacked the pair); legal predicate exclusion
#: is one rung lower (the 公募要領 says no, but adoption records may show a
#: case-by-case exception); guideline mentions are weakest.
_SEVERITY_WEIGHT: dict[str, float] = {"high": 1.0, "med": 0.6, "low": 0.3}

#: Hard cap on program_ids cardinality. The maximum-independent-set greedy
#: walk is O(2^n) worst-case if we tried exhaustive enumeration; greedy is
#: O(n^2) but we still cap at a sensible UX limit.
_MAX_PROGRAM_IDS: int = 20

#: Number of alternative bundles to surface. The customer LLM presents this
#: as plan A / B / C — three is the documented contract.
_ALTERNATIVE_BUNDLE_LIMIT: int = 3

_DISCLAIMER = (
    "本 conflict 検出は am_funding_stack_empirical (実証 co-adoption) + "
    "am_program_eligibility_predicate (法的 mutual exclusion) の **機械的照合** "
    "結果であり、補助金併用可否の最終判断ではない。個別 公募要領 の最新版・"
    "適用除外 例外条項は本 endpoint の対象外。本 response は税理士法 §52 "
    "(税務代理) ・行政書士法 §1 (申請代理) ・弁護士法 §72 (法律事務) のいずれにも"
    "該当せず、確定判断は資格を有する 士業 (行政書士・中小企業診断士・税理士) へ。"
)


# ---------------------------------------------------------------------------
# Helpers — DB introspection + ID normalization
# ---------------------------------------------------------------------------


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


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    """Return (lo, hi) so the pair matches the empirical-table CHECK ordering."""
    return (a, b) if a < b else (b, a)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ConflictRequest(BaseModel):
    """POST body for /v1/intel/conflict."""

    program_ids: list[str] = Field(
        ...,
        min_length=2,
        max_length=_MAX_PROGRAM_IDS,
        description=(
            "List of 2-20 program identifiers (UNI-... or canonical "
            "program:* / certification:* / loan:*). Order is irrelevant; "
            "duplicates are de-duplicated server-side."
        ),
    )
    houjin_id: str = Field(
        ...,
        min_length=13,
        max_length=14,
        description=(
            "13-digit 法人番号 (NTA canonical), with or without 'T' prefix. "
            "Used as evaluation context only — does NOT scope the conflict "
            "matrix lookup."
        ),
    )


# ---------------------------------------------------------------------------
# Conflict-pair detection — empirical stack + legal predicate
# ---------------------------------------------------------------------------


def _empirical_stack_conflicts(
    am_conn: sqlite3.Connection | None,
    pairs: list[tuple[str, str]],
    missing_tables: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Look up `am_funding_stack_empirical.conflict_flag=1` for each pair.

    Returns a {(lo, hi): {reason, severity, evidence}} dict. Pairs not
    flagged in the empirical table are absent from the result.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if am_conn is None or not _table_exists(am_conn, "am_funding_stack_empirical"):
        missing_tables.append("am_funding_stack_empirical")
        return out
    if not pairs:
        return out

    placeholders = ",".join("(?, ?)" for _ in pairs)
    flat: list[str] = []
    for lo, hi in pairs:
        flat.extend([lo, hi])
    sql = (
        "SELECT program_a_id, program_b_id, co_adoption_count, "
        "       compat_matrix_says, conflict_flag "
        "  FROM am_funding_stack_empirical "
        " WHERE (program_a_id, program_b_id) IN (" + placeholders + ")"
    )
    try:
        rows = am_conn.execute(sql, flat).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_funding_stack_empirical lookup failed: %s", exc)
        return out

    for r in rows:
        lo = r["program_a_id"] if isinstance(r, sqlite3.Row) else r[0]
        hi = r["program_b_id"] if isinstance(r, sqlite3.Row) else r[1]
        co = r["co_adoption_count"] if isinstance(r, sqlite3.Row) else r[2]
        says = r["compat_matrix_says"] if isinstance(r, sqlite3.Row) else r[3]
        flag = r["conflict_flag"] if isinstance(r, sqlite3.Row) else r[4]
        if not flag:
            continue
        # Empirical conflict: matrix says 'incompatible' AND >=1 法人 stacked
        # them anyway. Severity = high because the 公募要領 explicitly forbids
        # the combo, even though some 法人 got both. Treat as `high` for the
        # default fence; downgrade later if compat_matrix_says is unknown.
        severity = "high" if says == "incompatible" else "med"
        out[(lo, hi)] = {
            "reason": (
                f"empirical conflict: matrix says {says!r}, co_adoption_count={int(co or 0)}"
            ),
            "severity": severity,
            "evidence": {
                "source": "stack_empirical",
                "table": "am_funding_stack_empirical",
                "co_adoption_count": int(co or 0),
                "compat_matrix_says": says,
            },
        }
    return out


def _legal_predicate_conflicts(
    am_conn: sqlite3.Connection | None,
    pairs: list[tuple[str, str]],
    missing_tables: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Look up legal mutual-exclusion predicates for each pair.

    Pulls from `am_program_eligibility_predicate` (wave24_137) where the
    predicate kind 'jsic_not_in' / 'region_not_in' / 'other' carries a
    `value_text` containing the *other* program's id. Pairs without a
    matching predicate are absent.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if am_conn is None or not _table_exists(am_conn, "am_program_eligibility_predicate"):
        missing_tables.append("am_program_eligibility_predicate")
        return out
    if not pairs:
        return out

    # Pull all predicates touching any program in the candidate set so we
    # can match on either direction (A excludes B, or B excludes A).
    program_set: set[str] = set()
    for lo, hi in pairs:
        program_set.add(lo)
        program_set.add(hi)
    placeholders = ",".join("?" for _ in program_set)
    sql = (
        "SELECT program_unified_id, predicate_kind, operator, "
        "       value_text, source_url, source_clause_quote "
        "  FROM am_program_eligibility_predicate "
        " WHERE program_unified_id IN (" + placeholders + ") "
        "   AND operator IN ('NOT_IN', '!=', 'CONTAINS') "
        "   AND value_text IS NOT NULL"
    )
    try:
        rows = am_conn.execute(sql, list(program_set)).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_program_eligibility_predicate lookup failed: %s", exc)
        return out

    # Index predicates by (owning_program -> [{value_text, kind, ...}])
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        owner = r["program_unified_id"] if isinstance(r, sqlite3.Row) else r[0]
        kind = r["predicate_kind"] if isinstance(r, sqlite3.Row) else r[1]
        op = r["operator"] if isinstance(r, sqlite3.Row) else r[2]
        val = r["value_text"] if isinstance(r, sqlite3.Row) else r[3]
        url = r["source_url"] if isinstance(r, sqlite3.Row) else r[4]
        quote = r["source_clause_quote"] if isinstance(r, sqlite3.Row) else r[5]
        by_owner.setdefault(owner, []).append(
            {
                "kind": kind,
                "operator": op,
                "value_text": val,
                "source_url": url,
                "source_clause_quote": quote,
            }
        )

    for lo, hi in pairs:
        # Direction 1: lo's predicate excludes hi
        for owner, other in ((lo, hi), (hi, lo)):
            for pred in by_owner.get(owner, []):
                vt = (pred.get("value_text") or "").strip()
                if not vt:
                    continue
                # Match if value_text either equals other's id OR contains it
                # (e.g. comma-separated list).
                hit = (vt == other) or (other in vt.split(",")) or (other in vt)
                if not hit:
                    continue
                out[(lo, hi)] = {
                    "reason": (
                        f"legal mutual exclusion: program {owner} "
                        f"declares {pred['kind']!r} {pred['operator']!r} "
                        f"against {other}"
                    ),
                    "severity": "high",
                    "evidence": {
                        "source": "law",
                        "table": "am_program_eligibility_predicate",
                        "owning_program": owner,
                        "predicate_kind": pred["kind"],
                        "operator": pred["operator"],
                        "url": pred.get("source_url"),
                        "clause": pred.get("source_clause_quote"),
                    },
                }
                break
            if (lo, hi) in out:
                break
    return out


# ---------------------------------------------------------------------------
# Compat matrix bridge — `am_compat_matrix` direct lookup as guideline tier
# ---------------------------------------------------------------------------


def _matrix_guideline_conflicts(
    am_conn: sqlite3.Connection | None,
    pairs: list[tuple[str, str]],
    already_flagged: set[tuple[str, str]],
    missing_tables: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Surface `am_compat_matrix.compat_status='incompatible'` as guideline tier.

    Skips pairs already flagged via empirical or legal sources to avoid
    double-counting. Severity = 'med' because matrix-only signals are
    rule-based without observed adoption to confirm.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if am_conn is None or not _table_exists(am_conn, "am_compat_matrix"):
        missing_tables.append("am_compat_matrix")
        return out
    if not pairs:
        return out

    candidates = [p for p in pairs if p not in already_flagged]
    if not candidates:
        return out
    placeholders = ",".join("(?, ?)" for _ in candidates)
    flat: list[str] = []
    for lo, hi in candidates:
        flat.extend([lo, hi])
    sql = (
        "SELECT program_a_id, program_b_id, compat_status "
        "  FROM am_compat_matrix "
        " WHERE (program_a_id, program_b_id) IN (" + placeholders + ") "
        "   AND compat_status = 'incompatible'"
    )
    try:
        rows = am_conn.execute(sql, flat).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_compat_matrix lookup failed: %s", exc)
        return out
    for r in rows:
        lo = r["program_a_id"] if isinstance(r, sqlite3.Row) else r[0]
        hi = r["program_b_id"] if isinstance(r, sqlite3.Row) else r[1]
        out[(lo, hi)] = {
            "reason": (
                "guideline conflict: am_compat_matrix marks pair "
                "'incompatible' (rule-based, no observed co-adoption)"
            ),
            "severity": "med",
            "evidence": {
                "source": "guideline",
                "table": "am_compat_matrix",
                "compat_status": "incompatible",
            },
        }
    return out


# ---------------------------------------------------------------------------
# Maximum independent set (greedy by amount)
# ---------------------------------------------------------------------------


def _amounts_for_programs(conn: sqlite3.Connection, program_ids: list[str]) -> dict[str, int]:
    """Pull `programs.amount_max_man_yen` (in ¥10k units) → ¥ for the set.

    Programs missing in the table return 0 so the greedy set still has a
    deterministic ordering (alphabetical fallback).
    """
    amounts: dict[str, int] = dict.fromkeys(program_ids, 0)
    if not program_ids:
        return amounts
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = conn.execute(
            "SELECT unified_id, amount_max_man_yen FROM programs "
            "WHERE unified_id IN (" + placeholders + ")",
            list(program_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("programs.amount_max_man_yen lookup failed: %s", exc)
        return amounts
    for r in rows:
        uid = r["unified_id"] if isinstance(r, sqlite3.Row) else r[0]
        amax = r["amount_max_man_yen"] if isinstance(r, sqlite3.Row) else r[1]
        if amax is None:
            continue
        # amount_max_man_yen is in 10k yen (万円); promote to yen.
        amounts[uid] = int(float(amax) * 10_000)
    return amounts


def _greedy_max_independent_set(
    program_ids: list[str],
    conflict_set: set[tuple[str, str]],
    amounts_yen: dict[str, int],
) -> list[str]:
    """Greedy MIS: sort programs by amount desc, then add each only if it
    has no conflict with the already-accepted set.

    This is a 2-approximation in the worst case; for the launch use-case
    (n <= 20, sparse conflict graph) it returns the optimal subset on
    typical inputs. Deterministic ordering (alphabetical tiebreak).
    """
    ordered = sorted(
        program_ids,
        key=lambda pid: (-amounts_yen.get(pid, 0), pid),
    )
    accepted: list[str] = []
    accepted_set: set[str] = set()
    for pid in ordered:
        clash = False
        for taken in accepted_set:
            pair = _normalize_pair(pid, taken)
            if pair in conflict_set:
                clash = True
                break
        if not clash:
            accepted.append(pid)
            accepted_set.add(pid)
    return accepted


def _alternative_bundles(
    program_ids: list[str],
    conflict_set: set[tuple[str, str]],
    amounts_yen: dict[str, int],
    primary_subset: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Generate the top-`limit` alternative bundles by total amount.

    Strategy: rotate the seed (skip the i-th highest-amount program from
    the greedy seed list) and re-run MIS. The first bundle is the primary
    subset itself; subsequent bundles drop each top-scoring program in
    turn so the customer LLM sees plan A (max ¥), plan B (drop top-1),
    plan C (drop top-2).
    """
    bundles: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()

    def _amount(pids: list[str]) -> int:
        return sum(amounts_yen.get(p, 0) for p in pids)

    def _add(bundle_pids: list[str], rationale: str) -> None:
        key = tuple(sorted(bundle_pids))
        if key in seen_keys or not bundle_pids:
            return
        seen_keys.add(key)
        bundles.append(
            {
                "bundle": list(bundle_pids),
                "expected_total_amount": _amount(bundle_pids),
                "rationale": rationale,
            }
        )

    _add(primary_subset, "max_amount_compatible_subset")

    # Rotate seeds: drop each program in primary_subset and re-run MIS.
    for drop in list(primary_subset):
        remaining = [p for p in program_ids if p != drop]
        alt = _greedy_max_independent_set(remaining, conflict_set, amounts_yen)
        _add(alt, f"alt_without_{drop}")
        if len(bundles) >= limit:
            break

    # Rank by descending total amount, deterministic tiebreak by bundle key.
    bundles.sort(key=lambda b: (-int(b["expected_total_amount"]), tuple(sorted(b["bundle"]))))
    return bundles[:limit]


# ---------------------------------------------------------------------------
# Aggregate conflict score
# ---------------------------------------------------------------------------


def _aggregate_conflict_score(
    conflict_pairs: list[dict[str, Any]],
    program_ids: list[str],
) -> float:
    """Weighted ratio of conflicting pairs over total possible pairs.

    score = sum(severity_weight) / total_possible_pairs

    Bounded to [0.0, 1.0]. A fully-conflicting set with all severity=high
    returns 1.0; an empty conflict set returns 0.0.
    """
    n = len(program_ids)
    if n < 2:
        return 0.0
    total_pairs = n * (n - 1) / 2
    if total_pairs == 0:
        return 0.0
    weight_sum = sum(
        _SEVERITY_WEIGHT.get(str(p.get("severity") or "low"), 0.3) for p in conflict_pairs
    )
    return round(min(1.0, weight_sum / total_pairs), 4)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/conflict",
    summary="補助金併用 conflict 検出 + 代替提案 (NO LLM, ¥3 / call)",
    description=(
        "Single-call combo evaluator: customer LLM passes "
        "`{program_ids: [...], houjin_id}` and receives the conflict "
        "matrix, the largest compatible subset, and the top-3 alternative "
        "bundles ranked by total amount.\n\n"
        "**Pricing:** ¥3 / call (1 unit total) regardless of "
        "program_ids cardinality.\n\n"
        "**Cross-join:** am_funding_stack_empirical (実証 stack co-occurrence) "
        "+ am_program_eligibility_predicate (法的 mutual exclusion) + "
        "am_compat_matrix (rule-based fallback). Pure SQLite + Python "
        "graph walk. NO LLM, deterministic.\n\n"
        "**Sensitive:** §52 / §1 / §72 fence — combo eligibility is a "
        "machine signal, not a 申請可否 判断."
    ),
)
def post_intel_conflict(
    payload: Annotated[ConflictRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    _t0 = time.perf_counter()

    # Validate houjin_id first so we 422 cleanly before touching the DB.
    hb = _normalize_houjin(payload.houjin_id)
    if not (hb.isdigit() and len(hb) == 13):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_id",
                "field": "houjin_id",
                "message": f"houjin_id must be 13 digits (got {hb!r}).",
            },
        )

    # De-dupe + preserve first-seen order.
    program_ids: list[str] = []
    seen: set[str] = set()
    for raw in payload.program_ids:
        pid = (raw or "").strip()
        if pid and pid not in seen:
            program_ids.append(pid)
            seen.add(pid)
    if len(program_ids) < 2:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "insufficient_program_ids",
                "field": "program_ids",
                "message": (
                    "After de-duplication, program_ids must contain at "
                    f"least 2 distinct ids (got {len(program_ids)})."
                ),
            },
        )

    # Build all unordered pairs (n choose 2).
    pairs: list[tuple[str, str]] = []
    for i in range(len(program_ids)):
        for j in range(i + 1, len(program_ids)):
            pairs.append(_normalize_pair(program_ids[i], program_ids[j]))

    # Open autonomath.db (where am_funding_stack_empirical +
    # am_program_eligibility_predicate live). Lazy import so tests can
    # monkeypatch AUTONOMATH_DB_PATH between cases.
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

    am_conn: sqlite3.Connection | None = None
    try:
        am_conn = connect_autonomath()
    except FileNotFoundError:
        am_conn = None
    except sqlite3.Error as exc:
        logger.warning("autonomath.db unavailable: %s", exc)
        am_conn = None

    missing_tables: list[str] = []
    try:
        empirical = _empirical_stack_conflicts(am_conn, pairs, missing_tables)
        legal = _legal_predicate_conflicts(am_conn, pairs, missing_tables)
        already = set(empirical) | set(legal)
        guideline = _matrix_guideline_conflicts(am_conn, pairs, already, missing_tables)
    finally:
        # Don't close the thread-local connection from connect_autonomath —
        # subsequent requests on the same thread reuse it. The conn is
        # opened RO so leaving it open is safe.
        pass

    # Merge conflict pair sources. Empirical wins over legal wins over
    # guideline (precedence by source authority).
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for src in (guideline, legal, empirical):
        merged.update(src)

    conflict_pairs: list[dict[str, Any]] = []
    for (lo, hi), info in sorted(merged.items()):
        conflict_pairs.append(
            {
                "a": lo,
                "b": hi,
                "reason": info["reason"],
                "severity": info["severity"],
                "evidence": info["evidence"],
            }
        )

    has_conflict = bool(conflict_pairs)
    conflict_score = _aggregate_conflict_score(conflict_pairs, program_ids)

    # Compatible subset + alternative bundles.
    amounts_yen = _amounts_for_programs(conn, program_ids)
    conflict_set: set[tuple[str, str]] = set(merged.keys())
    compatible_subset = _greedy_max_independent_set(program_ids, conflict_set, amounts_yen)
    alternatives = _alternative_bundles(
        program_ids,
        conflict_set,
        amounts_yen,
        compatible_subset,
        _ALTERNATIVE_BUNDLE_LIMIT,
    )

    body: dict[str, Any] = {
        "houjin_id": hb,
        "input_program_ids": program_ids,
        "has_conflict": has_conflict,
        "conflict_score": conflict_score,
        "conflict_pairs": conflict_pairs,
        "compatible_subset": compatible_subset,
        "alternative_bundles": alternatives,
        "data_quality": {
            "missing_tables": missing_tables,
            "total_pairs_evaluated": len(pairs),
            "conflict_pairs_found": len(conflict_pairs),
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }

    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.conflict",
        latency_ms=latency_ms,
        result_count=len(conflict_pairs),
        params={
            "program_id_count": len(program_ids),
            "houjin_id_present": bool(hb),
            "has_conflict": has_conflict,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.conflict",
        request_params={
            "program_ids": program_ids,
            "houjin_id": hb,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = ["router"]
