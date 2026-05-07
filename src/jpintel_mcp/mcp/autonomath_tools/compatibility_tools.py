"""compatibility_tools — Program × program compatibility (R8, am_compat_matrix full surface).

Two MCP tools that mirror ``api/compatibility.py``:

  * ``portfolio_optimize_am`` — multi-program portfolio assembly with
    duplicate/exclusion risk + axis-weighted recommended_mix.
  * ``program_compatibility_pair_am`` — 2-program verdict
    (compatible / mutually_exclusive / unknown / sequential).

Both tools are pure SQLite + Python. NO LLM. The same 4-source resolution
stack as the REST surface:

  1. legal predicate (am_program_eligibility_predicate, NOT_IN / != / CONTAINS)
  2. empirical conflict (am_funding_stack_empirical, conflict_flag=1)
  3. matrix (am_compat_matrix, compat_status)
  4. temporal precedence (am_relation, requires_before / precedes / follows /
     superseded_by) — surfaces the 4th bucket ``sequential`` for 段階申請

Sensitive: §52 / §1 / §72 fence — verdict is a machine signal, not a 申請可否
判断. Disclaimer is inserted by ``envelope_wrapper`` once both tool names are
added to ``SENSITIVE_TOOLS``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from itertools import combinations
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

if TYPE_CHECKING:
    from collections.abc import Callable

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot_with_conn

logger = logging.getLogger("jpintel.mcp.autonomath.compatibility")

_ENABLED = os.environ.get("AUTONOMATH_COMPATIBILITY_TOOLS_ENABLED", "1") == "1"

_MAX_CANDIDATES = 30
_RECOMMENDED_MIX_LIMIT = 3
_AXIS_VOCAB = ("coverage", "amount", "risk")
_TIER_RISK = {"S": 10, "A": 20, "B": 35, "C": 50, "D": 65, "X": 90}

_DISCLAIMER = (
    "本 compatibility / portfolio response は am_compat_matrix (43,966 rows, "
    "4,300 sourced + 39,666 heuristic inferences) + am_funding_stack_empirical "
    "(実証 stack co-occurrence) + am_program_eligibility_predicate "
    "(法的 mutual exclusion) + am_relation (temporal precedence) を機械的照合した "
    "結果であり、補助金併用可否・順序・税務処理の確定判断ではない。"
    "inferred_only=true の edge は heuristic、経費重複 + 適正化法 17 条 + "
    "個別 公募要領 例外条項は本 tool の対象外。本 response は税理士法 §52 ・"
    "行政書士法 §1 ・弁護士法 §72 のいずれにも該当せず、確定判断は士業へ。"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            retry_with=["find_complementary_programs_am"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["find_complementary_programs_am"],
        )


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


def _missing(missing: list[str], name: str) -> None:
    if name not in missing:
        missing.append(name)


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _matrix_row(
    conn: sqlite3.Connection, a: str, b: str, missing: list[str]
) -> dict[str, Any] | None:
    if not _table_exists(conn, "am_compat_matrix"):
        _missing(missing, "am_compat_matrix")
        return None
    try:
        row = conn.execute(
            "SELECT program_a_id, program_b_id, compat_status, combined_max_yen, "
            "       conditions_text, rationale_short, source_url, confidence, inferred_only "
            "  FROM am_compat_matrix "
            " WHERE (program_a_id=? AND program_b_id=?) "
            "    OR (program_a_id=? AND program_b_id=?) "
            " LIMIT 1",
            (a, b, b, a),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return {
        "program_a": row["program_a_id"],
        "program_b": row["program_b_id"],
        "compat_status": row["compat_status"],
        "combined_max_yen": row["combined_max_yen"],
        "conditions_text": row["conditions_text"],
        "rationale_short": row["rationale_short"],
        "source_url": row["source_url"],
        "confidence": row["confidence"],
        "inferred_only": bool(row["inferred_only"]),
    }


def _empirical_row(
    conn: sqlite3.Connection, a: str, b: str, missing: list[str]
) -> dict[str, Any] | None:
    if not _table_exists(conn, "am_funding_stack_empirical"):
        _missing(missing, "am_funding_stack_empirical")
        return None
    lo, hi = _normalize_pair(a, b)
    try:
        row = conn.execute(
            "SELECT co_adoption_count, compat_matrix_says, conflict_flag "
            "  FROM am_funding_stack_empirical "
            " WHERE program_a_id=? AND program_b_id=? LIMIT 1",
            (lo, hi),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return {
        "co_adoption_count": int(row["co_adoption_count"] or 0),
        "compat_matrix_says": row["compat_matrix_says"],
        "conflict_flag": int(row["conflict_flag"] or 0),
    }


def _predicate_row(
    conn: sqlite3.Connection, a: str, b: str, missing: list[str]
) -> dict[str, Any] | None:
    if not _table_exists(conn, "am_program_eligibility_predicate"):
        _missing(missing, "am_program_eligibility_predicate")
        return None
    try:
        rows = conn.execute(
            "SELECT program_unified_id, predicate_kind, operator, value_text, "
            "       source_url, source_clause_quote "
            "  FROM am_program_eligibility_predicate "
            " WHERE program_unified_id IN (?, ?) "
            "   AND operator IN ('NOT_IN','!=','CONTAINS') "
            "   AND value_text IS NOT NULL",
            (a, b),
        ).fetchall()
    except sqlite3.Error:
        return None
    for r in rows:
        owner = r["program_unified_id"]
        other = b if owner == a else a
        vt = (r["value_text"] or "").strip()
        if vt == other or other in vt.split(",") or other in vt:
            return {
                "owning_program": owner,
                "kind": r["predicate_kind"],
                "operator": r["operator"],
                "value_text": vt,
                "source_url": r["source_url"],
                "source_clause_quote": r["source_clause_quote"],
            }
    return None


def _sequential_row(
    conn: sqlite3.Connection, a: str, b: str, missing: list[str]
) -> dict[str, Any] | None:
    if not _table_exists(conn, "am_relation"):
        _missing(missing, "am_relation")
        return None
    cols = _columns(conn, "am_relation")
    src_col = "src_id" if "src_id" in cols else ("source_id" if "source_id" in cols else None)
    dst_col = "dst_id" if "dst_id" in cols else ("target_id" if "target_id" in cols else None)
    type_col = "relation_type" if "relation_type" in cols else ("type" if "type" in cols else None)
    if not src_col or not dst_col or not type_col:
        return None
    try:
        row = conn.execute(
            f"SELECT {src_col} AS src, {dst_col} AS dst, {type_col} AS rtype "
            "  FROM am_relation "
            f" WHERE (({src_col}=? AND {dst_col}=?) OR ({src_col}=? AND {dst_col}=?)) "
            f"   AND {type_col} IN "
            "       ('requires_before','precedes','follows','sequential','superseded_by') "
            " LIMIT 1",
            (a, b, b, a),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return {"from": row["src"], "to": row["dst"], "relation_type": row["rtype"]}


def _pair_compatibility(
    conn: sqlite3.Connection, a: str, b: str, missing: list[str]
) -> dict[str, Any]:
    matrix = _matrix_row(conn, a, b, missing)
    empirical = _empirical_row(conn, a, b, missing)
    predicate = _predicate_row(conn, a, b, missing)
    sequential = _sequential_row(conn, a, b, missing)

    verdict = "unknown"
    parts: list[str] = []
    evidence: dict[str, Any] = {}

    if predicate is not None:
        verdict = "mutually_exclusive"
        parts.append(
            f"legal predicate: {predicate['owning_program']} declares "
            f"{predicate['kind']} {predicate['operator']} against the counterparty"
        )
        evidence["legal_predicate"] = predicate
    elif empirical and empirical.get("conflict_flag"):
        verdict = "mutually_exclusive"
        parts.append(
            "empirical stack conflict: matrix says "
            f"{empirical.get('compat_matrix_says')!r}, "
            f"co_adoption_count={empirical.get('co_adoption_count')}"
        )
        evidence["empirical"] = empirical
    elif matrix is not None and matrix.get("compat_status") == "incompatible":
        verdict = "mutually_exclusive"
        parts.append("am_compat_matrix marks pair 'incompatible'")
        evidence["matrix"] = matrix
    elif matrix is not None and matrix.get("compat_status") == "compatible":
        verdict = "compatible"
        parts.append("am_compat_matrix marks pair 'compatible'")
        evidence["matrix"] = matrix
    elif matrix is not None and matrix.get("compat_status") == "case_by_case":
        verdict = "compatible"
        parts.append("am_compat_matrix marks pair 'case_by_case' — verify 公募要領")
        evidence["matrix"] = matrix
    elif sequential is not None:
        verdict = "sequential"
        parts.append(
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
        parts.append(
            f"am_compat_matrix compat_status={matrix.get('compat_status')!r}; treated as unknown"
        )

    return {
        "compatibility": verdict,
        "rationale": "; ".join(parts)
        if parts
        else ("no matrix / empirical / predicate / relation row found for pair"),
        "evidence": evidence,
        "inferred_only": inferred_only,
    }


def _programs_meta(conn: sqlite3.Connection, program_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Pull tier + amount + program_kind from jpi_programs / programs (mirrored)."""
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
    table = (
        "jpi_programs"
        if _table_exists(conn, "jpi_programs")
        else ("programs" if _table_exists(conn, "programs") else None)
    )
    if table is None:
        return out
    cols = _columns(conn, table)
    id_col = (
        "unified_id" if "unified_id" in cols else ("program_id" if "program_id" in cols else None)
    )
    name_col = "primary_name" if "primary_name" in cols else ("name" if "name" in cols else None)
    tier_col = "tier" if "tier" in cols else None
    kind_col = "program_kind" if "program_kind" in cols else None
    amount_col = (
        "amount_max_man_yen"
        if "amount_max_man_yen" in cols
        else ("max_amount_yen" if "max_amount_yen" in cols else None)
    )
    if not id_col:
        return out
    placeholders = ",".join(["?"] * len(program_ids))
    select_cols = [f"{id_col} AS pid"]
    select_cols.append(f"{name_col} AS name" if name_col else "NULL AS name")
    select_cols.append(f"{tier_col} AS tier" if tier_col else "NULL AS tier")
    select_cols.append(f"{kind_col} AS kind" if kind_col else "NULL AS kind")
    select_cols.append(f"{amount_col} AS amount_raw" if amount_col else "NULL AS amount_raw")
    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM {table} WHERE {id_col} IN ({placeholders})",
            program_ids,
        ).fetchall()
    except sqlite3.Error:
        return out
    for r in rows:
        pid = r["pid"]
        amax = r["amount_raw"]
        amount_yen = 0
        if amax is not None:
            try:
                v = float(amax)
                # man_yen if column was amount_max_man_yen.
                amount_yen = int(v * 10_000) if amount_col == "amount_max_man_yen" else int(v)
            except (TypeError, ValueError):
                amount_yen = 0
        out[pid] = {
            "program_id": pid,
            "name": r["name"],
            "tier": r["tier"],
            "program_kind": r["kind"],
            "amount_yen": amount_yen,
        }
    return out


def _greedy_mis(
    program_ids: list[str],
    exclude: set[tuple[str, str]],
    sort_key: Callable[[str], Any],
) -> list[str]:
    accepted: list[str] = []
    accepted_set: set[str] = set()
    for pid in sorted(program_ids, key=sort_key):
        clash = False
        for taken in accepted_set:
            if _normalize_pair(pid, taken) in exclude:
                clash = True
                break
        if not clash:
            accepted.append(pid)
            accepted_set.add(pid)
    return accepted


def _axis_score(bundle: list[str], meta: dict[str, dict[str, Any]], axis: str) -> float:
    if not bundle:
        return 0.0
    if axis == "amount":
        total: float = float(sum(meta[p]["amount_yen"] for p in bundle if p in meta))
        return min(1.0, round(total / 1_000_000_000, 4))
    if axis == "coverage":
        kinds = {meta[p].get("program_kind") for p in bundle if p in meta}
        kinds.discard(None)
        return min(1.0, round(len(kinds) / 5.0, 4))
    if axis == "risk":
        risks = [
            _TIER_RISK.get(str(meta[p].get("tier") or "").upper(), 50) for p in bundle if p in meta
        ]
        if not risks:
            return 0.0
        return round(max(0.0, 1.0 - (sum(risks) / len(risks)) / 100.0), 4)
    return 0.0


def _bundle_score(bundle: list[str], meta: dict[str, dict[str, Any]], axes: list[str]) -> float:
    if not bundle or not axes:
        return 0.0
    return round(sum(_axis_score(bundle, meta, a) for a in axes) / len(axes), 4)


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


def portfolio_optimize_impl(
    candidate_program_ids: list[str],
    target_axes: list[str] | None = None,
) -> dict[str, Any]:
    if not candidate_program_ids or not isinstance(candidate_program_ids, list):
        return make_error(
            code="missing_required_arg",
            message="candidate_program_ids is required (list of >=2 ids).",
            field="candidate_program_ids",
        )
    seen: set[str] = set()
    program_ids: list[str] = []
    for raw in candidate_program_ids:
        pid = (raw or "").strip()
        if pid and pid not in seen:
            program_ids.append(pid)
            seen.add(pid)
    if len(program_ids) < 2:
        return make_error(
            code="invalid_input",
            message=(
                "After de-dup, candidate_program_ids must contain >= 2 ids "
                f"(got {len(program_ids)})."
            ),
            field="candidate_program_ids",
        )
    if len(program_ids) > _MAX_CANDIDATES:
        program_ids = program_ids[:_MAX_CANDIDATES]

    axes = [a for a in (target_axes or list(_AXIS_VOCAB)) if a in _AXIS_VOCAB]
    if not axes:
        axes = ["amount"]

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    missing: list[str] = []
    pair_verdicts: dict[tuple[str, str], dict[str, Any]] = {}
    for a, b in combinations(program_ids, 2):
        pair_verdicts[_normalize_pair(a, b)] = _pair_compatibility(conn, a, b, missing)

    duplicate_risk = [
        {
            "program_a": pa,
            "program_b": pb,
            "compatibility": info["compatibility"],
            "rationale": info["rationale"],
            "inferred_only": info["inferred_only"],
            "evidence": info["evidence"],
        }
        for (pa, pb), info in sorted(pair_verdicts.items())
        if info["compatibility"] in ("mutually_exclusive", "sequential")
    ]

    meta = _programs_meta(conn, program_ids)
    excluded_pairs = {
        pair
        for pair, info in pair_verdicts.items()
        if info["compatibility"] in ("mutually_exclusive", "sequential")
    }

    bundles: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()

    def _add(bundle: list[str], rationale: str) -> None:
        key = tuple(sorted(bundle))
        if not bundle or key in seen_keys:
            return
        seen_keys.add(key)
        bundles.append(
            {
                "bundle": list(bundle),
                "score": _bundle_score(bundle, meta, axes),
                "axis_scores": {a: _axis_score(bundle, meta, a) for a in axes},
                "expected_total_amount": sum(meta[p]["amount_yen"] for p in bundle if p in meta),
                "rationale": rationale,
            }
        )

    primary = _greedy_mis(
        program_ids,
        excluded_pairs,
        sort_key=lambda pid: (-meta.get(pid, {}).get("amount_yen", 0), pid),
    )
    _add(primary, "max_amount_compatible_subset")
    for drop in list(primary):
        remaining = [p for p in program_ids if p != drop]
        alt = _greedy_mis(
            remaining,
            excluded_pairs,
            sort_key=lambda pid: (-meta.get(pid, {}).get("amount_yen", 0), pid),
        )
        _add(alt, f"alt_without_{drop}")
        if len(bundles) >= _RECOMMENDED_MIX_LIMIT + 2:
            break
    _add(
        _greedy_mis(
            program_ids,
            excluded_pairs,
            sort_key=lambda pid: (
                _TIER_RISK.get(str(meta.get(pid, {}).get("tier") or "").upper(), 50),
                pid,
            ),
        ),
        "tier_safest_subset",
    )
    _add(
        _greedy_mis(
            program_ids,
            excluded_pairs,
            sort_key=lambda pid: (
                0 if meta.get(pid, {}).get("program_kind") else 1,
                -meta.get(pid, {}).get("amount_yen", 0),
                pid,
            ),
        ),
        "max_coverage_subset",
    )
    bundles.sort(key=lambda b: (-float(b["score"]), tuple(sorted(b["bundle"]))))
    bundles = bundles[:_RECOMMENDED_MIX_LIMIT]

    portfolio = bundles[0]["bundle"] if bundles else []
    portfolio_score = bundles[0]["score"] if bundles else 0.0

    body: dict[str, Any] = {
        "input_program_ids": program_ids,
        "target_axes": axes,
        "portfolio": portfolio,
        "portfolio_score": portfolio_score,
        "axis_scores": {a: _axis_score(portfolio, meta, a) for a in axes},
        "duplicate_risk": duplicate_risk,
        "recommended_mix": bundles,
        "summary": {
            "candidate_count": len(program_ids),
            "duplicate_risk_count": len(duplicate_risk),
            "pair_count": len(pair_verdicts),
            "mix_count": len(bundles),
        },
        "data_quality": {
            "missing_tables": sorted(set(missing)),
            "compat_matrix_total": 43966,
            "authoritative_share_pct": 9.8,
            "caveat": (
                "inferred_only=true edges are heuristic. axis_scores are "
                "normalized [0,1] (amount saturates at ¥1B; coverage at 5 "
                "distinct kinds; risk = 1 - mean(tier_risk)/100)."
            ),
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    attach_corpus_snapshot_with_conn(conn, body)
    return body


def program_compatibility_pair_impl(a: str, b: str) -> dict[str, Any]:
    if not a or not isinstance(a, str) or not a.strip():
        return make_error(
            code="missing_required_arg",
            message="a (program_id) is required.",
            field="a",
        )
    if not b or not isinstance(b, str) or not b.strip():
        return make_error(
            code="missing_required_arg",
            message="b (program_id) is required.",
            field="b",
        )
    a_norm = a.strip()
    b_norm = b.strip()
    if a_norm == b_norm:
        return make_error(
            code="invalid_input",
            message="a and b must be distinct program ids.",
            field="a|b",
            hint="Pass two different canonical program ids.",
        )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    missing: list[str] = []
    info = _pair_compatibility(conn, a_norm, b_norm, missing)

    body: dict[str, Any] = {
        "program_a": a_norm,
        "program_b": b_norm,
        "compatibility": info["compatibility"],
        "rationale": info["rationale"],
        "inferred_only": info["inferred_only"],
        "evidence": info["evidence"],
        "data_quality": {"missing_tables": sorted(set(missing))},
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    attach_corpus_snapshot_with_conn(conn, body)
    return body


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def portfolio_optimize_am(
        candidate_program_ids: Annotated[
            list[str],
            Field(
                description=(
                    "List of 2-30 candidate program ids (UNI-... or canonical "
                    "program:* / certification:* / loan:*). Order is irrelevant, "
                    "duplicates de-duped server-side."
                ),
                min_length=2,
                max_length=_MAX_CANDIDATES,
            ),
        ],
        target_axes: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optimization axes: 'coverage' (max distinct program "
                    "kinds), 'amount' (max combined ¥), 'risk' (min "
                    "weighted tier risk). Unknown axes ignored; empty/None "
                    "defaults to ['amount']."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[R8-COMPAT] am_compat_matrix 43,966 row full surface — portfolio optimizer (greedy max-IS) + duplicate / mutually-exclusive risk pairs + top-3 recommended_mix ranked by axis-weighted score (coverage / amount / risk). Cross-joins am_compat_matrix + am_funding_stack_empirical + am_program_eligibility_predicate + am_relation. Pure SQLite + Python. NO LLM. §52 / §1 / §72 sensitive — verify 経費重複 + 適正化法 17 条 before stacking."""
        return portfolio_optimize_impl(
            candidate_program_ids=candidate_program_ids,
            target_axes=target_axes,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def program_compatibility_pair_am(
        a: Annotated[
            str,
            Field(description="First program canonical_id."),
        ],
        b: Annotated[
            str,
            Field(description="Second program canonical_id (must differ from a)."),
        ],
    ) -> dict[str, Any]:
        """[R8-COMPAT] 2 制度間の互換性 — 4-bucket verdict {compatible, mutually_exclusive, unknown, sequential} resolved over am_compat_matrix + am_funding_stack_empirical + am_program_eligibility_predicate + am_relation. 'sequential' fires on temporal-precedence edges (requires_before / precedes / follows / superseded_by). NO LLM. §52 / §1 / §72 sensitive."""
        return program_compatibility_pair_impl(a=a, b=b)


__all__ = [
    "portfolio_optimize_impl",
    "program_compatibility_pair_impl",
]


if __name__ == "__main__":  # pragma: no cover
    import pprint

    pprint.pprint(
        portfolio_optimize_impl(
            candidate_program_ids=[
                "program:04_program_documents:000000:23_25d25bdfe8",
                "program:08_loan_programs:000017:23ec41c30b",
                "program:08_loan_programs:000043:IT_c2763c9944",
            ],
            target_axes=["coverage", "amount", "risk"],
        )
    )
