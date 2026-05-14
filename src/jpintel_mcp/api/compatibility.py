"""Program × program compatibility surface — am_compat_matrix full surface (R8).

Two endpoints land here, both pure SQLite + Python (NO LLM). They turn the
43,966-row `am_compat_matrix` (4,300 sourced + heuristic inferences flagged
``status='unknown'`` via ``inferred_only=1``) into a public surface so a
customer LLM can portfolio-optimize across multiple programs in 1 call.

Endpoints
---------

POST /v1/programs/portfolio_optimize
    Body: ``{candidate_program_ids: ["UNI-..."], target_axes: ["coverage",
    "amount", "risk"]}``
    Returns: ``portfolio`` (recommended mix on greedy max-IS), ``duplicate_risk``
    (pairs flagged via empirical-stack / legal-predicate / matrix), ``axis_scores``
    (one breakdown per requested target_axis), ``recommended_mix`` (top 3
    bundles ranked by axis-weighted score), ``data_quality``.

GET /v1/programs/{a}/compatibility/{b}
    Returns the compatibility verdict between two programs:
    ``compatibility``∈{compatible,mutually_exclusive,unknown,sequential},
    plus ``rationale``, ``evidence`` (compat-matrix row), ``co_adoption_count``
    (empirical), ``predicate`` (legal predicate row if any), ``inferred_only``.

Compatibility model
-------------------

The four-bucket vocabulary lifts the raw matrix's `compat_status` (which is
{compatible, incompatible, case_by_case, unknown}) into a customer-facing
schema that surfaces a useful 4th bucket — ``sequential``. ``sequential``
fires when the pair has a documented temporal-precedence edge in
``am_relation`` (relation_type='requires_before' / 'precedes' / 'follows')
without an explicit incompatibility verdict. This unblocks 段階申請 use cases
where program A is a prerequisite of program B but they cannot be claimed
in the same fiscal year.

Hard constraints
----------------

* NO LLM call (memory `feedback_no_operator_llm_api`). 1 unit ¥3 / call.
* Read-only — no writes against jpintel.db or autonomath.db.
* Graceful when am_compat_matrix / am_funding_stack_empirical / am_relation
  are missing on a fresh dev DB: the corresponding axis is flagged in
  ``data_quality.missing_tables`` and the response keeps a partial-but-honest
  envelope, never a 500.

Sensitive surface
-----------------

§52 / §1 / §72 fence applied via the standard ``_disclaimer`` envelope.
Compatibility verdicts are machine signals; combo eligibility decisions
remain with the qualified 士業.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import time
from itertools import combinations
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Callable

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.compatibility")

router = APIRouter(prefix="/v1/programs", tags=["programs"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Hard cap on candidate_program_ids cardinality. Mirrors intel_conflict's
#: greedy-MIS cap; pairs explode quadratically.
_MAX_CANDIDATES: int = 30

#: Recommended mix size — customer LLM presents these as top-3 plans.
_RECOMMENDED_MIX_LIMIT: int = 3

#: Axis vocabulary for portfolio_optimize.target_axes. Unknown axes pass
#: validation but are silently ignored at scoring time.
_AXIS_VOCAB: tuple[str, ...] = ("coverage", "amount", "risk")

#: Tier risk points (lower = safer). Mirrors intel_portfolio_heatmap so the
#: two surfaces stay numerically consistent. Unknown tier defaults to 50.
_TIER_RISK: dict[str, int] = {"S": 10, "A": 20, "B": 35, "C": 50, "D": 65, "X": 90}

_DISCLAIMER = (
    "本 compatibility / portfolio surface は am_compat_matrix (43,966 rows, "
    "4,300 sourced + 39,666 heuristic inferences flagged status='unknown') + "
    "am_funding_stack_empirical (実証 stack co-occurrence) + "
    "am_program_eligibility_predicate (法的 mutual exclusion) + am_relation "
    "(temporal precedence) を機械的照合した response であり、補助金併用可否・"
    "順序・税務処理の確定判断ではない。inferred_only=true の edge は heuristic、"
    "経費重複 + 適正化法 17 条 + 個別 公募要領 例外条項は本 endpoint の対象外。"
    "本 response は税理士法 §52 (税務代理) ・行政書士法 §1の2 (申請代理) ・"
    "弁護士法 §72 (法律事務) のいずれにも該当せず、確定判断は資格を有する "
    "士業 (行政書士・中小企業診断士・税理士) へ。"
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PortfolioOptimizeRequest(BaseModel):
    """POST body for /v1/programs/portfolio_optimize."""

    candidate_program_ids: list[str] = Field(
        ...,
        min_length=2,
        max_length=_MAX_CANDIDATES,
        description=(
            "List of 2-30 candidate program ids (UNI-... or canonical "
            "program:* / certification:* / loan:*). Order is irrelevant; "
            "duplicates are de-duplicated server-side."
        ),
    )
    target_axes: list[str] = Field(
        default_factory=lambda: list(_AXIS_VOCAB),
        description=(
            "Optimization axes: 'coverage' (max distinct program kinds), "
            "'amount' (max combined ¥), 'risk' (min weighted tier risk). "
            "Unknown axes are ignored; empty list collapses to amount."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers — DB introspection + ID normalization
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _missing(missing_tables: list[str], name: str) -> None:
    if name not in missing_tables:
        missing_tables.append(name)


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    """Return (lo, hi) so the pair matches the empirical-table CHECK ordering."""
    return (a, b) if a < b else (b, a)


def _validate_program_id(raw: str) -> str | None:
    """Defang program ids before they reach the SQLite layer.

    Allowed character class is ``[A-Za-z0-9_:.-]`` — the canonical id format
    is ``program:base:hash`` / ``UNI-...`` / ``certification:...`` / ``loan:...``.
    Anything else is rejected as invalid input (caller gets 422).
    """
    s = (raw or "").strip()
    if not s or len(s) > 200:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_:.\-]+", s):
        return None
    return s


def _open_autonomath() -> sqlite3.Connection | None:
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

    try:
        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.warning("autonomath unavailable for compatibility surface: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Pair-level lookup (a, b) compatibility verdict
# ---------------------------------------------------------------------------


def _matrix_row_for_pair(
    am_conn: sqlite3.Connection | None,
    pair: tuple[str, str],
    missing: list[str],
) -> dict[str, Any] | None:
    """Pull `am_compat_matrix` row for a pair, regardless of stored direction."""
    if am_conn is None or not _table_exists(am_conn, "am_compat_matrix"):
        _missing(missing, "am_compat_matrix")
        return None
    a, b = pair
    try:
        row = am_conn.execute(
            "SELECT program_a_id, program_b_id, compat_status, combined_max_yen, "
            "       conditions_text, rationale_short, evidence_relation, source_url, "
            "       confidence, inferred_only "
            "  FROM am_compat_matrix "
            " WHERE (program_a_id=? AND program_b_id=?) "
            "    OR (program_a_id=? AND program_b_id=?) "
            " LIMIT 1",
            (a, b, b, a),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("am_compat_matrix lookup failed: %s", exc)
        return None
    if row is None:
        return None
    return {
        "program_a": row["program_a_id"] if isinstance(row, sqlite3.Row) else row[0],
        "program_b": row["program_b_id"] if isinstance(row, sqlite3.Row) else row[1],
        "compat_status": row["compat_status"] if isinstance(row, sqlite3.Row) else row[2],
        "combined_max_yen": (row["combined_max_yen"] if isinstance(row, sqlite3.Row) else row[3]),
        "conditions_text": (row["conditions_text"] if isinstance(row, sqlite3.Row) else row[4]),
        "rationale_short": (row["rationale_short"] if isinstance(row, sqlite3.Row) else row[5]),
        "evidence_relation": (row["evidence_relation"] if isinstance(row, sqlite3.Row) else row[6]),
        "source_url": row["source_url"] if isinstance(row, sqlite3.Row) else row[7],
        "confidence": row["confidence"] if isinstance(row, sqlite3.Row) else row[8],
        "inferred_only": bool(row["inferred_only"] if isinstance(row, sqlite3.Row) else row[9]),
    }


def _empirical_count_for_pair(
    am_conn: sqlite3.Connection | None,
    pair: tuple[str, str],
    missing: list[str],
) -> dict[str, Any] | None:
    """Empirical co-adoption count for a pair (empirical table is order-strict)."""
    if am_conn is None or not _table_exists(am_conn, "am_funding_stack_empirical"):
        _missing(missing, "am_funding_stack_empirical")
        return None
    lo, hi = _normalize_pair(*pair)
    try:
        row = am_conn.execute(
            "SELECT co_adoption_count, compat_matrix_says, conflict_flag "
            "  FROM am_funding_stack_empirical "
            " WHERE program_a_id=? AND program_b_id=? LIMIT 1",
            (lo, hi),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("am_funding_stack_empirical lookup failed: %s", exc)
        return None
    if row is None:
        return None
    return {
        "co_adoption_count": int(row["co_adoption_count"] or 0)
        if isinstance(row, sqlite3.Row)
        else int(row[0] or 0),
        "compat_matrix_says": (
            row["compat_matrix_says"] if isinstance(row, sqlite3.Row) else row[1]
        ),
        "conflict_flag": int(row["conflict_flag"] or 0)
        if isinstance(row, sqlite3.Row)
        else int(row[2] or 0),
    }


def _predicate_for_pair(
    am_conn: sqlite3.Connection | None,
    pair: tuple[str, str],
    missing: list[str],
) -> dict[str, Any] | None:
    """Legal mutual-exclusion predicate (jpi/wave24_137)."""
    if am_conn is None or not _table_exists(am_conn, "am_program_eligibility_predicate"):
        _missing(missing, "am_program_eligibility_predicate")
        return None
    a, b = pair
    try:
        rows = am_conn.execute(
            "SELECT program_unified_id, predicate_kind, operator, value_text, "
            "       source_url, source_clause_quote "
            "  FROM am_program_eligibility_predicate "
            " WHERE program_unified_id IN (?, ?) "
            "   AND operator IN ('NOT_IN', '!=', 'CONTAINS') "
            "   AND value_text IS NOT NULL",
            (a, b),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_program_eligibility_predicate lookup failed: %s", exc)
        return None
    for r in rows:
        owner = r["program_unified_id"] if isinstance(r, sqlite3.Row) else r[0]
        kind = r["predicate_kind"] if isinstance(r, sqlite3.Row) else r[1]
        op = r["operator"] if isinstance(r, sqlite3.Row) else r[2]
        val = (r["value_text"] if isinstance(r, sqlite3.Row) else r[3]) or ""
        url = r["source_url"] if isinstance(r, sqlite3.Row) else r[4]
        quote = r["source_clause_quote"] if isinstance(r, sqlite3.Row) else r[5]
        other = b if owner == a else a
        vt = val.strip()
        hit = vt == other or other in vt.split(",") or other in vt
        if hit:
            return {
                "owning_program": owner,
                "kind": kind,
                "operator": op,
                "value_text": vt,
                "source_url": url,
                "source_clause_quote": quote,
            }
    return None


def _sequential_for_pair(
    am_conn: sqlite3.Connection | None,
    pair: tuple[str, str],
    missing: list[str],
) -> dict[str, Any] | None:
    """Detect temporal precedence via am_relation."""
    if am_conn is None or not _table_exists(am_conn, "am_relation"):
        _missing(missing, "am_relation")
        return None
    a, b = pair
    cols = _columns(am_conn, "am_relation")
    src_col = "src_id" if "src_id" in cols else ("source_id" if "source_id" in cols else None)
    dst_col = "dst_id" if "dst_id" in cols else ("target_id" if "target_id" in cols else None)
    type_col = "relation_type" if "relation_type" in cols else ("type" if "type" in cols else None)
    if not src_col or not dst_col or not type_col:
        return None
    try:
        row = am_conn.execute(
            f"SELECT {src_col} AS src, {dst_col} AS dst, {type_col} AS rtype "
            "  FROM am_relation "
            f" WHERE (({src_col}=? AND {dst_col}=?) OR ({src_col}=? AND {dst_col}=?)) "
            f"   AND {type_col} IN "
            "       ('requires_before','precedes','follows','sequential','superseded_by') "
            " LIMIT 1",
            (a, b, b, a),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("am_relation lookup failed: %s", exc)
        return None
    if row is None:
        return None
    src = row["src"] if isinstance(row, sqlite3.Row) else row[0]
    dst = row["dst"] if isinstance(row, sqlite3.Row) else row[1]
    rtype = row["rtype"] if isinstance(row, sqlite3.Row) else row[2]
    return {
        "from": src,
        "to": dst,
        "relation_type": rtype,
    }


def _pair_compatibility(
    am_conn: sqlite3.Connection | None,
    a: str,
    b: str,
    missing: list[str],
) -> dict[str, Any]:
    """Resolve a single (a, b) pair into a 4-bucket compatibility verdict.

    Resolution order (highest authority wins):
      1. legal predicate (NOT_IN / !=) → mutually_exclusive
      2. empirical conflict_flag=1 → mutually_exclusive
      3. matrix compat_status='incompatible' → mutually_exclusive
      4. matrix compat_status='compatible' → compatible
      5. matrix compat_status='case_by_case' → compatible (with conditions)
      6. am_relation sequential edge → sequential
      7. otherwise → unknown
    """
    pair = (a, b)
    matrix = _matrix_row_for_pair(am_conn, pair, missing)
    empirical = _empirical_count_for_pair(am_conn, pair, missing)
    predicate = _predicate_for_pair(am_conn, pair, missing)
    sequential = _sequential_for_pair(am_conn, pair, missing)

    verdict = "unknown"
    rationale_parts: list[str] = []
    evidence: dict[str, Any] = {}

    if predicate is not None:
        verdict = "mutually_exclusive"
        rationale_parts.append(
            f"legal predicate: {predicate['owning_program']} "
            f"declares {predicate['kind']} {predicate['operator']} "
            f"against the counterparty"
        )
        evidence["legal_predicate"] = predicate
    elif empirical and empirical.get("conflict_flag"):
        verdict = "mutually_exclusive"
        rationale_parts.append(
            "empirical stack conflict: matrix says "
            f"{empirical.get('compat_matrix_says')!r}, "
            f"co_adoption_count={empirical.get('co_adoption_count')}"
        )
        evidence["empirical"] = empirical
    elif matrix is not None and matrix.get("compat_status") == "incompatible":
        verdict = "mutually_exclusive"
        rationale_parts.append("am_compat_matrix marks pair 'incompatible' (rule-based)")
        evidence["matrix"] = matrix
    elif matrix is not None and matrix.get("compat_status") == "compatible":
        verdict = "compatible"
        rationale_parts.append("am_compat_matrix marks pair 'compatible'")
        evidence["matrix"] = matrix
    elif matrix is not None and matrix.get("compat_status") == "case_by_case":
        verdict = "compatible"
        rationale_parts.append("am_compat_matrix marks pair 'case_by_case' — verify 公募要領")
        evidence["matrix"] = matrix
    elif sequential is not None:
        verdict = "sequential"
        rationale_parts.append(
            f"am_relation: {sequential['relation_type']} edge "
            f"({sequential['from']} → {sequential['to']})"
        )
        evidence["sequential"] = sequential

    # Attach matrix even when not the deciding source so the customer LLM
    # always sees the underlying matrix row when present.
    if matrix is not None and "matrix" not in evidence:
        evidence["matrix"] = matrix
    if empirical is not None and "empirical" not in evidence:
        evidence["empirical"] = empirical
    if sequential is not None and "sequential" not in evidence:
        evidence["sequential"] = sequential

    inferred_only = bool(matrix.get("inferred_only")) if matrix else False
    if verdict == "unknown" and matrix is not None:
        # Matrix has the pair but compat_status is something we did not
        # bucket (e.g. literal 'unknown'); flag as unknown with the matrix
        # row carried as evidence.
        rationale_parts.append(
            f"am_compat_matrix compat_status={matrix.get('compat_status')!r}; treated as unknown"
        )

    return {
        "compatibility": verdict,
        "rationale": "; ".join(rationale_parts)
        if rationale_parts
        else ("no matrix / empirical / predicate / relation row found for pair"),
        "evidence": evidence,
        "inferred_only": inferred_only,
    }


# ---------------------------------------------------------------------------
# Portfolio assembly — duplicate risk + axis scoring + greedy MIS
# ---------------------------------------------------------------------------


def _programs_meta(
    conn: sqlite3.Connection,
    program_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Pull tier + amount + program_kind for portfolio scoring."""
    out: dict[str, dict[str, Any]] = {
        pid: {
            "program_id": pid,
            "name": None,
            "tier": None,
            "program_kind": None,
            "amount_yen": 0,
        }
        for pid in program_ids
    }
    if not program_ids:
        return out
    placeholders = ",".join(["?"] * len(program_ids))
    try:
        rows = conn.execute(
            "SELECT unified_id, primary_name, tier, program_kind, amount_max_man_yen "
            "  FROM programs "
            f" WHERE unified_id IN ({placeholders})",
            program_ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("programs metadata lookup failed: %s", exc)
        return out
    for r in rows:
        uid = r["unified_id"] if isinstance(r, sqlite3.Row) else r[0]
        name = r["primary_name"] if isinstance(r, sqlite3.Row) else r[1]
        tier = r["tier"] if isinstance(r, sqlite3.Row) else r[2]
        kind = r["program_kind"] if isinstance(r, sqlite3.Row) else r[3]
        amax = r["amount_max_man_yen"] if isinstance(r, sqlite3.Row) else r[4]
        amount_yen = int(float(amax) * 10_000) if amax is not None else 0
        out[uid] = {
            "program_id": uid,
            "name": name,
            "tier": tier,
            "program_kind": kind,
            "amount_yen": amount_yen,
        }
    return out


def _bulk_matrix_rows(
    am_conn: sqlite3.Connection | None,
    program_ids: list[str],
    missing: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """One-shot prefetch of am_compat_matrix rows touching any program in the set.

    Replaces the per-pair `_matrix_row_for_pair` lookup so portfolio_optimize
    issues 1 query instead of C(N,2). Result keyed by `_normalize_pair`.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if am_conn is None or not program_ids:
        if am_conn is None:
            _missing(missing, "am_compat_matrix")
        return out
    if not _table_exists(am_conn, "am_compat_matrix"):
        _missing(missing, "am_compat_matrix")
        return out
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            "SELECT program_a_id, program_b_id, compat_status, combined_max_yen, "
            "       conditions_text, rationale_short, evidence_relation, source_url, "
            "       confidence, inferred_only "
            f"  FROM am_compat_matrix "
            f" WHERE program_a_id IN ({placeholders}) "
            f"   AND program_b_id IN ({placeholders})",
            (*program_ids, *program_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_compat_matrix bulk lookup failed: %s", exc)
        return out
    id_set = set(program_ids)
    for row in rows:
        a = row["program_a_id"] if isinstance(row, sqlite3.Row) else row[0]
        b = row["program_b_id"] if isinstance(row, sqlite3.Row) else row[1]
        if a not in id_set or b not in id_set or a == b:
            continue
        key = _normalize_pair(a, b)
        # Keep the first row seen per pair — matrix should not duplicate.
        if key in out:
            continue
        out[key] = {
            "program_a": a,
            "program_b": b,
            "compat_status": row["compat_status"] if isinstance(row, sqlite3.Row) else row[2],
            "combined_max_yen": (
                row["combined_max_yen"] if isinstance(row, sqlite3.Row) else row[3]
            ),
            "conditions_text": (row["conditions_text"] if isinstance(row, sqlite3.Row) else row[4]),
            "rationale_short": (row["rationale_short"] if isinstance(row, sqlite3.Row) else row[5]),
            "evidence_relation": (
                row["evidence_relation"] if isinstance(row, sqlite3.Row) else row[6]
            ),
            "source_url": row["source_url"] if isinstance(row, sqlite3.Row) else row[7],
            "confidence": row["confidence"] if isinstance(row, sqlite3.Row) else row[8],
            "inferred_only": bool(row["inferred_only"] if isinstance(row, sqlite3.Row) else row[9]),
        }
    return out


def _bulk_empirical_rows(
    am_conn: sqlite3.Connection | None,
    program_ids: list[str],
    missing: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """One-shot prefetch of am_funding_stack_empirical co-adoption rows."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if am_conn is None or not program_ids:
        if am_conn is None:
            _missing(missing, "am_funding_stack_empirical")
        return out
    if not _table_exists(am_conn, "am_funding_stack_empirical"):
        _missing(missing, "am_funding_stack_empirical")
        return out
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            "SELECT program_a_id, program_b_id, co_adoption_count, "
            "       compat_matrix_says, conflict_flag "
            f"  FROM am_funding_stack_empirical "
            f" WHERE program_a_id IN ({placeholders}) "
            f"   AND program_b_id IN ({placeholders})",
            (*program_ids, *program_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_funding_stack_empirical bulk lookup failed: %s", exc)
        return out
    id_set = set(program_ids)
    for row in rows:
        a = row["program_a_id"] if isinstance(row, sqlite3.Row) else row[0]
        b = row["program_b_id"] if isinstance(row, sqlite3.Row) else row[1]
        if a not in id_set or b not in id_set or a == b:
            continue
        key = _normalize_pair(a, b)
        if key in out:
            continue
        co = row["co_adoption_count"] if isinstance(row, sqlite3.Row) else row[2]
        says = row["compat_matrix_says"] if isinstance(row, sqlite3.Row) else row[3]
        cf = row["conflict_flag"] if isinstance(row, sqlite3.Row) else row[4]
        out[key] = {
            "co_adoption_count": int(co or 0),
            "compat_matrix_says": says,
            "conflict_flag": int(cf or 0),
        }
    return out


def _bulk_predicate_rows(
    am_conn: sqlite3.Connection | None,
    program_ids: list[str],
    missing: list[str],
) -> list[dict[str, Any]]:
    """One-shot prefetch of NOT_IN/!=/CONTAINS predicates owned by any program in the set."""
    if am_conn is None or not program_ids:
        if am_conn is None:
            _missing(missing, "am_program_eligibility_predicate")
        return []
    if not _table_exists(am_conn, "am_program_eligibility_predicate"):
        _missing(missing, "am_program_eligibility_predicate")
        return []
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            "SELECT program_unified_id, predicate_kind, operator, value_text, "
            "       source_url, source_clause_quote "
            f"  FROM am_program_eligibility_predicate "
            f" WHERE program_unified_id IN ({placeholders}) "
            f"   AND operator IN ('NOT_IN', '!=', 'CONTAINS') "
            f"   AND value_text IS NOT NULL",
            tuple(program_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_program_eligibility_predicate bulk lookup failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "program_unified_id": (
                    r["program_unified_id"] if isinstance(r, sqlite3.Row) else r[0]
                ),
                "predicate_kind": (r["predicate_kind"] if isinstance(r, sqlite3.Row) else r[1]),
                "operator": r["operator"] if isinstance(r, sqlite3.Row) else r[2],
                "value_text": (r["value_text"] if isinstance(r, sqlite3.Row) else r[3]) or "",
                "source_url": r["source_url"] if isinstance(r, sqlite3.Row) else r[4],
                "source_clause_quote": (
                    r["source_clause_quote"] if isinstance(r, sqlite3.Row) else r[5]
                ),
            }
        )
    return out


def _bulk_sequential_rows(
    am_conn: sqlite3.Connection | None,
    program_ids: list[str],
    missing: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """One-shot prefetch of am_relation sequential edges between programs in the set.

    Result keyed by ordered `(a, b)` (NOT normalized) so callers can detect
    direction. The pair-level resolver normalizes when looking up.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if am_conn is None or not program_ids:
        if am_conn is None:
            _missing(missing, "am_relation")
        return out
    if not _table_exists(am_conn, "am_relation"):
        _missing(missing, "am_relation")
        return out
    cols = _columns(am_conn, "am_relation")
    src_col = "src_id" if "src_id" in cols else ("source_id" if "source_id" in cols else None)
    dst_col = "dst_id" if "dst_id" in cols else ("target_id" if "target_id" in cols else None)
    type_col = "relation_type" if "relation_type" in cols else ("type" if "type" in cols else None)
    if not src_col or not dst_col or not type_col:
        return out
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            f"SELECT {src_col} AS src, {dst_col} AS dst, {type_col} AS rtype "
            f"  FROM am_relation "
            f" WHERE {src_col} IN ({placeholders}) "
            f"   AND {dst_col} IN ({placeholders}) "
            f"   AND {type_col} IN "
            f"       ('requires_before','precedes','follows','sequential','superseded_by')",
            (*program_ids, *program_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_relation bulk lookup failed: %s", exc)
        return out
    id_set = set(program_ids)
    for r in rows:
        src = r["src"] if isinstance(r, sqlite3.Row) else r[0]
        dst = r["dst"] if isinstance(r, sqlite3.Row) else r[1]
        rtype = r["rtype"] if isinstance(r, sqlite3.Row) else r[2]
        if src not in id_set or dst not in id_set or src == dst:
            continue
        key = (src, dst)
        if key in out:
            continue
        out[key] = {"from": src, "to": dst, "relation_type": rtype}
    return out


def _resolve_pair_from_bulk(
    a: str,
    b: str,
    *,
    matrix_by_pair: dict[tuple[str, str], dict[str, Any]],
    empirical_by_pair: dict[tuple[str, str], dict[str, Any]],
    predicate_rows: list[dict[str, Any]],
    sequential_by_pair: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Mirror of `_pair_compatibility` that reads from prefetched bulk maps.

    Returns the same shape as `_pair_compatibility`; never queries the DB.
    """
    pair_norm = _normalize_pair(a, b)

    matrix = matrix_by_pair.get(pair_norm)
    empirical = empirical_by_pair.get(pair_norm)

    # Predicate filtering happens in Python over the prefetched list — same
    # logic as `_predicate_for_pair`, just without re-issuing SQL.
    predicate: dict[str, Any] | None = None
    for row in predicate_rows:
        owner = row.get("program_unified_id")
        if owner not in (a, b):
            continue
        other = b if owner == a else a
        vt = (row.get("value_text") or "").strip()
        if not vt:
            continue
        hit = vt == other or other in vt.split(",") or other in vt
        if hit:
            predicate = {
                "owning_program": owner,
                "kind": row.get("predicate_kind"),
                "operator": row.get("operator"),
                "value_text": vt,
                "source_url": row.get("source_url"),
                "source_clause_quote": row.get("source_clause_quote"),
            }
            break

    sequential = sequential_by_pair.get((a, b)) or sequential_by_pair.get((b, a))

    verdict = "unknown"
    rationale_parts: list[str] = []
    evidence: dict[str, Any] = {}

    if predicate is not None:
        verdict = "mutually_exclusive"
        rationale_parts.append(
            f"legal predicate: {predicate['owning_program']} "
            f"declares {predicate['kind']} {predicate['operator']} "
            f"against the counterparty"
        )
        evidence["legal_predicate"] = predicate
    elif empirical and empirical.get("conflict_flag"):
        verdict = "mutually_exclusive"
        rationale_parts.append(
            "empirical stack conflict: matrix says "
            f"{empirical.get('compat_matrix_says')!r}, "
            f"co_adoption_count={empirical.get('co_adoption_count')}"
        )
        evidence["empirical"] = empirical
    elif matrix is not None and matrix.get("compat_status") == "incompatible":
        verdict = "mutually_exclusive"
        rationale_parts.append("am_compat_matrix marks pair 'incompatible' (rule-based)")
        evidence["matrix"] = matrix
    elif matrix is not None and matrix.get("compat_status") == "compatible":
        verdict = "compatible"
        rationale_parts.append("am_compat_matrix marks pair 'compatible'")
        evidence["matrix"] = matrix
    elif matrix is not None and matrix.get("compat_status") == "case_by_case":
        verdict = "compatible"
        rationale_parts.append("am_compat_matrix marks pair 'case_by_case' — verify 公募要領")
        evidence["matrix"] = matrix
    elif sequential is not None:
        verdict = "sequential"
        rationale_parts.append(
            f"am_relation: {sequential['relation_type']} edge "
            f"({sequential['from']} → {sequential['to']})"
        )
        evidence["sequential"] = sequential

    if matrix is not None and "matrix" not in evidence:
        evidence["matrix"] = matrix
    if empirical is not None and "empirical" not in evidence:
        evidence["empirical"] = empirical
    if sequential is not None and "sequential" not in evidence:
        evidence["sequential"] = sequential

    inferred_only = bool(matrix.get("inferred_only")) if matrix else False
    if verdict == "unknown" and matrix is not None:
        rationale_parts.append(
            f"am_compat_matrix compat_status={matrix.get('compat_status')!r}; treated as unknown"
        )

    return {
        "compatibility": verdict,
        "rationale": "; ".join(rationale_parts)
        if rationale_parts
        else ("no matrix / empirical / predicate / relation row found for pair"),
        "evidence": evidence,
        "inferred_only": inferred_only,
    }


def _all_pair_verdicts(
    am_conn: sqlite3.Connection | None,
    program_ids: list[str],
    missing: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Resolve every n-choose-2 pair into a verdict dict.

    Issues 4 bulk prefetch queries (matrix / empirical / predicate /
    sequential) over the entire `program_ids` set, then resolves each pair
    in pure Python. This replaces the previous N+1 path that fired 4
    queries per pair (4 × C(N,2) = up to 1,740 queries at N=30).
    """
    matrix_by_pair = _bulk_matrix_rows(am_conn, program_ids, missing)
    empirical_by_pair = _bulk_empirical_rows(am_conn, program_ids, missing)
    predicate_rows = _bulk_predicate_rows(am_conn, program_ids, missing)
    sequential_by_pair = _bulk_sequential_rows(am_conn, program_ids, missing)

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for a, b in combinations(program_ids, 2):
        out[_normalize_pair(a, b)] = _resolve_pair_from_bulk(
            a,
            b,
            matrix_by_pair=matrix_by_pair,
            empirical_by_pair=empirical_by_pair,
            predicate_rows=predicate_rows,
            sequential_by_pair=sequential_by_pair,
        )
    return out


def _duplicate_risk(
    pair_verdicts: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Surface mutually_exclusive + sequential pairs as duplicate-risk edges."""
    out: list[dict[str, Any]] = []
    for (a, b), info in sorted(pair_verdicts.items()):
        if info["compatibility"] in ("mutually_exclusive", "sequential"):
            out.append(
                {
                    "program_a": a,
                    "program_b": b,
                    "compatibility": info["compatibility"],
                    "rationale": info["rationale"],
                    "inferred_only": info["inferred_only"],
                    "evidence": info["evidence"],
                }
            )
    return out


def _greedy_max_independent_set(
    program_ids: list[str],
    exclude_pairs: set[tuple[str, str]],
    sort_key: Callable[[str], Any],
) -> list[str]:
    """Greedy MIS keyed by `sort_key` — drops any candidate that conflicts
    with the already-accepted set."""
    accepted: list[str] = []
    accepted_set: set[str] = set()
    for pid in sorted(program_ids, key=sort_key):
        clash = False
        for taken in accepted_set:
            if _normalize_pair(pid, taken) in exclude_pairs:
                clash = True
                break
        if not clash:
            accepted.append(pid)
            accepted_set.add(pid)
    return accepted


def _axis_score(
    bundle: list[str],
    meta: dict[str, dict[str, Any]],
    axis: str,
) -> float:
    """Compute the axis score for a bundle. All axes return [0.0, 1.0]."""
    if not bundle:
        return 0.0
    if axis == "amount":
        # Normalise against an arbitrary 1B yen ceiling to keep [0, 1] friendly.
        total = sum(float(meta[p]["amount_yen"]) for p in bundle if p in meta)
        return min(1.0, round(total / 1_000_000_000, 4))
    if axis == "coverage":
        kinds = {meta[p].get("program_kind") for p in bundle if p in meta}
        kinds.discard(None)
        # Saturate at 5 distinct kinds (補助金 / 融資 / 税制 / 認定 / 助成).
        return min(1.0, round(len(kinds) / 5.0, 4))
    if axis == "risk":
        # Inverted tier risk → safer = higher score.
        risks = [
            _TIER_RISK.get(str(meta[p].get("tier") or "").upper(), 50) for p in bundle if p in meta
        ]
        if not risks:
            return 0.0
        avg = sum(risks) / len(risks)
        return round(max(0.0, 1.0 - (avg / 100.0)), 4)
    return 0.0


def _bundle_score(
    bundle: list[str],
    meta: dict[str, dict[str, Any]],
    axes: list[str],
) -> float:
    """Equal-weighted average of per-axis scores."""
    if not bundle or not axes:
        return 0.0
    parts = [_axis_score(bundle, meta, a) for a in axes]
    return round(sum(parts) / len(parts), 4)


def _recommended_mix(
    program_ids: list[str],
    pair_verdicts: dict[tuple[str, str], dict[str, Any]],
    meta: dict[str, dict[str, Any]],
    axes: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Greedy seed + drop-each-top rotation, ranked by axis-weighted score."""
    excluded_pairs = {
        pair
        for pair, info in pair_verdicts.items()
        if info["compatibility"] in ("mutually_exclusive", "sequential")
    }

    bundles: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()

    def _add(bundle: list[str], rationale: str) -> None:
        key = tuple(sorted(bundle))
        if not bundle or key in seen:
            return
        seen.add(key)
        bundles.append(
            {
                "bundle": list(bundle),
                "score": _bundle_score(bundle, meta, axes),
                "axis_scores": {a: _axis_score(bundle, meta, a) for a in axes},
                "expected_total_amount": sum(meta[p]["amount_yen"] for p in bundle if p in meta),
                "rationale": rationale,
            }
        )

    # Primary seed: amount-desc.
    primary = _greedy_max_independent_set(
        program_ids,
        excluded_pairs,
        sort_key=lambda pid: (-meta.get(pid, {}).get("amount_yen", 0), pid),
    )
    _add(primary, "max_amount_compatible_subset")

    # Drop top-1, top-2 etc. for diversity.
    for drop in list(primary):
        remaining = [p for p in program_ids if p != drop]
        alt = _greedy_max_independent_set(
            remaining,
            excluded_pairs,
            sort_key=lambda pid: (-meta.get(pid, {}).get("amount_yen", 0), pid),
        )
        _add(alt, f"alt_without_{drop}")
        if len(bundles) >= limit + 2:
            break

    # Tier-safest seed (lower _TIER_RISK is safer).
    tier_safest = _greedy_max_independent_set(
        program_ids,
        excluded_pairs,
        sort_key=lambda pid: (
            _TIER_RISK.get(str(meta.get(pid, {}).get("tier") or "").upper(), 50),
            pid,
        ),
    )
    _add(tier_safest, "tier_safest_subset")

    # Coverage seed (max distinct program_kind).
    coverage_first = _greedy_max_independent_set(
        program_ids,
        excluded_pairs,
        sort_key=lambda pid: (
            0 if meta.get(pid, {}).get("program_kind") else 1,
            -meta.get(pid, {}).get("amount_yen", 0),
            pid,
        ),
    )
    _add(coverage_first, "max_coverage_subset")

    bundles.sort(key=lambda b: (-float(b["score"]), tuple(sorted(b["bundle"]))))
    return bundles[:limit]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/portfolio_optimize",
    summary="制度ポートフォリオ最適化 + 重複/排他 risk + 推奨 mix (NO LLM, ¥3 / call)",
    description=(
        "Single-call portfolio optimizer over am_compat_matrix (43,966 rows; "
        "4,300 sourced + heuristic inferences flagged status='unknown'). "
        "Returns the recommended portfolio (greedy max-IS), duplicate / "
        "mutually-exclusive risk pairs, axis-weighted scores per requested "
        "target_axis, and the top-3 recommended mixes ranked by score.\n\n"
        "**Pricing:** ¥3 / call (1 unit total) regardless of "
        "candidate_program_ids cardinality.\n\n"
        "**Cross-join:** am_compat_matrix + am_funding_stack_empirical + "
        "am_program_eligibility_predicate + am_relation. Pure SQLite + "
        "Python greedy walk. NO LLM, deterministic.\n\n"
        "**Sensitive:** §52 / §1 / §72 fence — portfolio decisions are a "
        "machine signal, not a 申請可否 / 併用可否 判断."
    ),
)
def post_portfolio_optimize(
    payload: Annotated[PortfolioOptimizeRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    _t0 = time.perf_counter()

    # De-dupe + validate program_ids; preserve first-seen order.
    program_ids: list[str] = []
    seen: set[str] = set()
    for raw in payload.candidate_program_ids:
        pid = _validate_program_id(raw)
        if pid is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_program_id",
                    "field": "candidate_program_ids",
                    "message": (
                        f"program_id {raw!r} is not a valid canonical id "
                        "([A-Za-z0-9_:.-], <=200 chars)."
                    ),
                },
            )
        if pid not in seen:
            program_ids.append(pid)
            seen.add(pid)
    if len(program_ids) < 2:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "insufficient_candidate_program_ids",
                "field": "candidate_program_ids",
                "message": (
                    "After de-duplication, candidate_program_ids must contain "
                    f"at least 2 distinct ids (got {len(program_ids)})."
                ),
            },
        )

    axes = [a for a in payload.target_axes if a in _AXIS_VOCAB]
    if not axes:
        axes = ["amount"]

    am_conn = _open_autonomath()
    missing: list[str] = []
    if am_conn is None:
        _missing(missing, "autonomath.db")

    pair_verdicts = _all_pair_verdicts(am_conn, program_ids, missing)
    duplicate_risk = _duplicate_risk(pair_verdicts)
    meta = _programs_meta(conn, program_ids)
    mixes = _recommended_mix(
        program_ids,
        pair_verdicts,
        meta,
        axes,
        _RECOMMENDED_MIX_LIMIT,
    )
    portfolio = mixes[0]["bundle"] if mixes else []
    portfolio_score = mixes[0]["score"] if mixes else 0.0

    # Aggregate axis_scores dict for the *primary* portfolio.
    axis_scores = {a: _axis_score(portfolio, meta, a) for a in axes}

    body: dict[str, Any] = {
        "input_program_ids": program_ids,
        "target_axes": axes,
        "portfolio": portfolio,
        "portfolio_score": portfolio_score,
        "axis_scores": axis_scores,
        "duplicate_risk": duplicate_risk,
        "recommended_mix": mixes,
        "summary": {
            "candidate_count": len(program_ids),
            "duplicate_risk_count": len(duplicate_risk),
            "pair_count": len(pair_verdicts),
            "mix_count": len(mixes),
        },
        "data_quality": {
            "missing_tables": sorted(set(missing)),
            "compat_matrix_total": 43966,
            "authoritative_share_pct": 9.8,  # 4,300 / 43,966
            "caveat": (
                "inferred_only=true edges are heuristic. "
                "axis_scores are normalized to [0,1] (amount saturates at "
                "¥1B; coverage saturates at 5 distinct program_kind values; "
                "risk = 1 - mean(tier_risk)/100). 経費重複 + 適正化法 17 条 + "
                "個別 公募要領 例外条項は本 endpoint の対象外。"
            ),
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }

    with contextlib.suppress(sqlite3.Error):
        body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "programs.portfolio_optimize",
        latency_ms=latency_ms,
        result_count=len(portfolio),
        params={
            "candidate_count": len(program_ids),
            "axis_count": len(axes),
            "duplicate_risk_count": len(duplicate_risk),
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="programs.portfolio_optimize",
        request_params={
            "candidate_program_ids": program_ids,
            "target_axes": axes,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


@router.get(
    "/{a}/compatibility/{b}",
    summary="2 制度間の互換性 (compatible / mutually_exclusive / unknown / sequential)",
    description=(
        "GET pair compatibility verdict between two programs. Resolves "
        "am_compat_matrix + am_funding_stack_empirical + "
        "am_program_eligibility_predicate + am_relation into one of four "
        "buckets:\n\n"
        "* **compatible** — matrix says compatible OR case_by_case\n"
        "* **mutually_exclusive** — legal predicate / empirical conflict / "
        "matrix incompatible\n"
        "* **sequential** — am_relation declares temporal precedence "
        "(requires_before / precedes / follows / superseded_by) without an "
        "explicit incompatibility\n"
        "* **unknown** — no row in any of the four sources\n\n"
        "**Pricing:** ¥3 / call.\n\n"
        "**Sensitive:** §52 / §1 / §72 fence — verdict is a machine signal."
    ),
)
def get_pair_compatibility(
    conn: DbDep,
    ctx: ApiContextDep,
    a: Annotated[str, Path(min_length=1, max_length=200)],
    b: Annotated[str, Path(min_length=1, max_length=200)],
) -> dict[str, Any]:
    _t0 = time.perf_counter()
    a_norm = _validate_program_id(a)
    b_norm = _validate_program_id(b)
    if a_norm is None or b_norm is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_program_id",
                "field": "a|b",
                "message": (
                    f"program ids must match [A-Za-z0-9_:.-] (<=200 chars). got a={a!r} b={b!r}"
                ),
            },
        )
    if a_norm == b_norm:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "same_program",
                "field": "a|b",
                "message": "a and b must be distinct program ids.",
            },
        )

    am_conn = _open_autonomath()
    missing: list[str] = []
    if am_conn is None:
        _missing(missing, "autonomath.db")
    info = _pair_compatibility(am_conn, a_norm, b_norm, missing)

    body: dict[str, Any] = {
        "program_a": a_norm,
        "program_b": b_norm,
        "compatibility": info["compatibility"],
        "rationale": info["rationale"],
        "inferred_only": info["inferred_only"],
        "evidence": info["evidence"],
        # R8 BUGHUNT (2026-05-07): mirror portfolio_optimize disclosure shape
        # so a downstream LLM consumer cannot mistake heuristic edges for
        # authoritative rulings.
        "data_quality": {
            "missing_tables": sorted(set(missing)),
            "compat_matrix_total": 43_966,
            "authoritative_pair_count": 4_300,
            "authoritative_share_pct": 9.8,
            "heuristic_inferred_only_count": 39_666,
            "caveat": (
                "am_compat_matrix の 43,966 行のうち authoritative pair は 4,300 "
                "(~9.8%)。inferred_only=true のエッジは heuristic 推論で、"
                "compat_status='unknown' の case_by_case を含む。経費重複 + "
                "適正化法 17 条 + 個別 公募要領 例外条項は本 endpoint の対象外。"
            ),
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }

    with contextlib.suppress(sqlite3.Error):
        body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "programs.compatibility_pair",
        latency_ms=latency_ms,
        result_count=1,
        params={
            "compatibility": info["compatibility"],
            "inferred_only": info["inferred_only"],
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="programs.compatibility_pair",
        request_params={"a": a_norm, "b": b_norm},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = ["router"]
