"""POST /v1/intel/peer_group — 同業他社 peer-group comparison + adoption stats.

Returns in 1 call (¥3): the query houjin profile + N nearest peer 法人
(by JSIC + prefecture + log-bucketed capital/employees), per-peer adoption
facts, statistical context (mean / percentile against the peer cohort),
and the top programs that peers actually adopted (peer-validated rec list).

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside this endpoint. Pure SQLite SELECT + Python arithmetic
  over `houjin_master`, `am_adopted_company_features` (Wave22-7 / wave24
  substrate), `am_geo_industry_density` (Wave22-5), `jpi_adoption_records`,
  `am_entity_facts` (corp.capital_amount / corp.employee_count facts), and
  `jpi_programs` (peer-adopted program metadata).
* Output is statistical: similarity_score is a Jaccard-style proximity
  signal, NOT a 同業認定 / 業界 belonging guarantee. The disclaimer fences
  the typical 景表法 / 行政書士法 §1の2 / 税理士法 §52 angles.

Cross-join graph
----------------
1. Resolve the query houjin profile (capital / employees / jsic / prefecture).
   Two paths: (a) houjin_id given → lookup `houjin_master` + `am_entity_facts`;
   (b) attribute dict given → use the dict verbatim (synthetic / 未登録 entity).

2. Candidate peers = `am_adopted_company_features` joined to `houjin_master`,
   restricted by SAME jsic_major OR SAME prefecture (broad pool of ~5k-50k).

3. Score each candidate via Jaccard-on-features (jsic + prefecture +
   log-bucketed capital + log-bucketed employees), pick top-K.

4. For each peer: pull adoption_count + estimated total amount + top
   3 categories from `jpi_adoption_records` (program_id_hint → category).

5. Statistical context: peer_avg_adoption_count, peer_avg_amount,
   query percentile against the peer cohort.

6. recommended_programs_peers_used: top programs by peer adoption rate
   joined to `jpi_programs` for primary_name + program_kind metadata.

Graceful degradation
--------------------
Missing tables (am_geo_industry_density / am_entity_facts / etc.) surface
as `null` fields + a `data_quality.missing_tables` list — the customer LLM
gets a partial-but-honest envelope rather than a 500.
"""

from __future__ import annotations

import contextlib
import logging
import math
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_peer_group")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


_DISCLAIMER = (
    "本 peer_group は houjin_master + am_adopted_company_features + "
    "am_entity_facts (corp.*) を Jaccard 類似度で機械的に近傍探索した "
    "**統計的サンプル** であり、「同業認定」「業界比較保証」「採択率予測」 "
    "ではない。similarity_score は jsic + prefecture + 資本金/従業員数 (対数バケット) "
    "の集合一致度のみで、業界実態 (商流・顧客層・規模感) を厳密に反映するものではない。"
    "本 envelope を「同業他社事例」として広告・営業に使用する場合は景表法 (不当表示防止法) "
    "の優良誤認 / 有利誤認 リスクに留意。確定的な業界比較・税務 / 採択判断は資格を有する "
    "行政書士・税理士・中小企業診断士へ。"
)


# Capital / employee log-bucket boundaries (yen / persons). Two houjin land
# in the same bucket when their value floor(log10(v)) matches. A 10x scale
# step is the empirically-stable rung — 1M yen vs 9M yen are "same bucket"
# (both 6), 100M yen and 1B yen drift apart (8 vs 9).
def _log_bucket(value: float | None) -> int | None:
    """Return floor(log10(value)) bucket id, or None when value is non-positive."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return int(math.floor(math.log10(v)))


def _normalize_houjin(value: str | None) -> str:
    """Strip whitespace + leading 'T' (invoice registration prefix)."""
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s


def _is_valid_houjin(value: str) -> bool:
    """13-digit numeric check after `_normalize_houjin`."""
    return bool(value) and value.isdigit() and len(value) == 13


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


_VALID_AXES: frozenset[str] = frozenset({"adoption_count", "total_amount", "category_diversity"})


class HoujinAttributes(BaseModel):
    """Inline houjin profile for未登録 (unregistered) entity matching.

    Use this when the caller doesn't have a 13-digit 法人番号 (e.g. a
    sole proprietor doing matchmaking, or a hypothetical profile for
    cohort discovery). All fields are optional; absent fields drop their
    contribution from the Jaccard similarity (smaller intersection set).
    """

    name: str | None = Field(None, max_length=200)
    capital: float | None = Field(
        None, ge=0, description="Capital in yen (will be log-bucketed for similarity)."
    )
    employees: int | None = Field(
        None, ge=0, description="Employee count (will be log-bucketed for similarity)."
    )
    jsic: str | None = Field(
        None,
        min_length=1,
        max_length=1,
        description="JSIC 大分類 letter (A–T).",
    )
    prefecture: str | None = Field(
        None,
        max_length=10,
        description="Prefecture long-form name (e.g. '東京都').",
    )


class PeerGroupRequest(BaseModel):
    """POST body for /v1/intel/peer_group.

    Either ``houjin_id`` (registered法人) OR ``houjin_attributes`` (未登録
    / synthetic profile) is required — the validator raises 422 when both
    are missing.
    """

    houjin_id: str | None = Field(
        None,
        min_length=13,
        max_length=14,
        description="13-digit 法人番号 (NTA canonical), with or without 'T' prefix.",
    )
    houjin_attributes: HoujinAttributes | None = Field(
        None,
        description="Inline houjin profile for未登録 entity matching.",
    )
    peer_count: int = Field(
        5,
        ge=3,
        le=10,
        description="Number of peers to return (3..10).",
    )
    comparison_axes: list[str] = Field(
        default_factory=lambda: [
            "adoption_count",
            "total_amount",
            "category_diversity",
        ],
        description=(
            "Axes to compare in the peer envelope. Subset of "
            "{adoption_count, total_amount, category_diversity}."
        ),
    )


# ---------------------------------------------------------------------------
# Profile resolution helpers
# ---------------------------------------------------------------------------


def _fetch_houjin_capital_employees(
    am_conn: sqlite3.Connection,
    *,
    houjin_bangou: str,
    missing_tables: list[str],
) -> tuple[float | None, int | None]:
    """Return (capital_yen, employee_count) from `am_entity_facts`.

    The entity_id convention for corporate facts is `houjin:<bangou>`. We
    prefer `corp.capital_amount` / `corp.employee_count` (gBizINFO source),
    falling back to the legacy `capital_yen` / `employees` keys.
    """
    if not _table_exists(am_conn, "am_entity_facts"):
        missing_tables.append("am_entity_facts")
        return None, None

    eid = f"houjin:{houjin_bangou}"
    capital: float | None = None
    employees: int | None = None
    try:
        for field, alt in (
            ("corp.capital_amount", "capital_yen"),
            ("corp.employee_count", "employees"),
        ):
            row = am_conn.execute(
                "SELECT field_value_numeric FROM am_entity_facts "
                " WHERE entity_id = ? AND field_name IN (?, ?) "
                "   AND field_value_numeric IS NOT NULL "
                " ORDER BY CASE WHEN field_name = ? THEN 0 ELSE 1 END "
                " LIMIT 1",
                (eid, field, alt, field),
            ).fetchone()
            if not row:
                continue
            v = row["field_value_numeric"]
            if v is None:
                continue
            if "capital" in field:
                capital = float(v)
            else:
                employees = int(round(float(v)))
    except sqlite3.Error as exc:
        logger.warning("am_entity_facts capital/employees query failed: %s", exc)
    return capital, employees


def _fetch_query_profile(
    am_conn: sqlite3.Connection,
    *,
    houjin_id: str | None,
    attrs: HoujinAttributes | None,
    missing_tables: list[str],
) -> dict[str, Any]:
    """Resolve the query houjin's profile.

    Order of precedence per field: explicit attribute dict > houjin_master /
    am_adopted_company_features > am_entity_facts. We always emit a profile
    dict (possibly with null fields) so the caller can introspect what we
    knew vs guessed.
    """
    profile: dict[str, Any] = {
        "id": None,
        "name": None,
        "capital": None,
        "employees": None,
        "jsic": None,
        "prefecture": None,
    }
    if attrs is not None:
        profile["name"] = attrs.name
        profile["capital"] = attrs.capital
        profile["employees"] = attrs.employees
        profile["jsic"] = (attrs.jsic or "").strip().upper() or None
        profile["prefecture"] = (attrs.prefecture or "").strip() or None

    if not houjin_id:
        return profile

    profile["id"] = houjin_id

    # houjin_master / jpi_houjin_master for name + prefecture + jsic_major
    for table in ("houjin_master", "jpi_houjin_master"):
        if not _table_exists(am_conn, table):
            continue
        try:
            row = am_conn.execute(
                f"SELECT * FROM {table} WHERE houjin_bangou = ? LIMIT 1",
                (houjin_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("%s query failed: %s", table, exc)
            continue
        if row is None:
            continue
        rd = dict(row)
        if not profile["name"] and rd.get("normalized_name"):
            profile["name"] = rd["normalized_name"]
        if not profile["prefecture"] and rd.get("prefecture"):
            profile["prefecture"] = rd["prefecture"]
        if not profile["jsic"] and rd.get("jsic_major"):
            profile["jsic"] = rd["jsic_major"]
        break

    # am_adopted_company_features for dominant_jsic / dominant_prefecture
    # fallback (some houjin only appear here, not in houjin_master).
    if _table_exists(am_conn, "am_adopted_company_features"):
        try:
            row = am_conn.execute(
                "SELECT dominant_jsic_major, dominant_prefecture "
                "  FROM am_adopted_company_features "
                " WHERE houjin_bangou = ? LIMIT 1",
                (houjin_id,),
            ).fetchone()
            if row:
                if not profile["jsic"] and row["dominant_jsic_major"]:
                    profile["jsic"] = str(row["dominant_jsic_major"]).strip()
                if not profile["prefecture"] and row["dominant_prefecture"]:
                    profile["prefecture"] = str(row["dominant_prefecture"]).strip()
        except sqlite3.Error as exc:
            logger.warning("am_adopted_company_features lookup failed: %s", exc)
    else:
        missing_tables.append("am_adopted_company_features")

    # capital + employees from am_entity_facts (corp.* facts)
    if profile["capital"] is None or profile["employees"] is None:
        cap, emp = _fetch_houjin_capital_employees(
            am_conn, houjin_bangou=houjin_id, missing_tables=missing_tables
        )
        if profile["capital"] is None:
            profile["capital"] = cap
        if profile["employees"] is None:
            profile["employees"] = emp

    return profile


# ---------------------------------------------------------------------------
# Peer search + Jaccard similarity
# ---------------------------------------------------------------------------


def _jaccard_similarity(query_features: set[str], peer_features: set[str]) -> float:
    """|A ∩ B| / |A ∪ B|. Returns 0.0 when both sets are empty."""
    if not query_features and not peer_features:
        return 0.0
    inter = query_features & peer_features
    union = query_features | peer_features
    return round(len(inter) / len(union), 4) if union else 0.0


def _features_for(
    *,
    jsic: str | None,
    prefecture: str | None,
    capital: float | None,
    employees: int | None,
) -> set[str]:
    """Build the canonical feature set for similarity scoring.

    Each present axis contributes one token:
      jsic:E
      pref:東京都
      cap:7   (log-bucket)
      emp:2   (log-bucket)
    """
    out: set[str] = set()
    if jsic:
        out.add(f"jsic:{jsic}")
    if prefecture:
        out.add(f"pref:{prefecture}")
    cap_b = _log_bucket(capital)
    if cap_b is not None:
        out.add(f"cap:{cap_b}")
    emp_b = _log_bucket(employees)
    if emp_b is not None:
        out.add(f"emp:{emp_b}")
    return out


def _candidate_pool(
    am_conn: sqlite3.Connection,
    *,
    profile: dict[str, Any],
    exclude_houjin: str | None,
    missing_tables: list[str],
    pool_cap: int = 2000,
) -> list[dict[str, Any]]:
    """Pull candidate peers via SAME jsic OR SAME prefecture restriction.

    The candidate pool is bounded at `pool_cap` rows so the per-row Jaccard
    + capital/employee fact lookup stays under the 5ms budget on a hot DB.
    With ~167k corporate_entity rows + jsic+pref filter, the pool typically
    settles in the 1k-5k band before truncation.

    Returns a list of dicts with houjin_bangou + name + jsic + prefecture +
    adoption_count (best-effort fields). Capital / employees are lazy-fetched
    per-peer in the scoring loop only when actually needed.
    """
    if not _table_exists(am_conn, "am_adopted_company_features"):
        missing_tables.append("am_adopted_company_features")
        return []

    where_clauses: list[str] = []
    params: list[Any] = []
    if profile.get("jsic"):
        where_clauses.append("a.dominant_jsic_major = ?")
        params.append(profile["jsic"])
    if profile.get("prefecture"):
        where_clauses.append("a.dominant_prefecture = ?")
        params.append(profile["prefecture"])

    if not where_clauses:
        # Without jsic OR prefecture we have no axis to filter on; return [].
        return []

    where_sql = " OR ".join(where_clauses)
    exclude_sql = ""
    if exclude_houjin:
        exclude_sql = " AND a.houjin_bangou <> ?"
        params.append(exclude_houjin)

    sql = (
        "SELECT a.houjin_bangou, a.adoption_count, "
        "       a.dominant_jsic_major, a.dominant_prefecture, "
        "       h.normalized_name, h.prefecture, h.jsic_major "
        "  FROM am_adopted_company_features a "
        "  LEFT JOIN houjin_master h "
        "         ON h.houjin_bangou = a.houjin_bangou "
        f" WHERE ({where_sql}){exclude_sql} "
        " ORDER BY a.adoption_count DESC "
        " LIMIT ?"
    )
    params.append(pool_cap)

    try:
        rows = am_conn.execute(sql, tuple(params)).fetchall()
    except sqlite3.Error as exc:
        logger.warning("candidate pool query failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        rd = dict(r)
        out.append(
            {
                "houjin_bangou": rd["houjin_bangou"],
                "name": rd.get("normalized_name") or "",
                "jsic": rd.get("jsic_major") or rd.get("dominant_jsic_major"),
                "prefecture": rd.get("prefecture") or rd.get("dominant_prefecture"),
                "adoption_count": int(rd.get("adoption_count") or 0),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-peer fact enrichment (adoption / categories / amount)
# ---------------------------------------------------------------------------


def _peer_program_facts(
    am_conn: sqlite3.Connection,
    *,
    houjin_bangou: str,
    missing_tables: list[str],
) -> tuple[int | None, list[str]]:
    """Estimate (total_amount_yen, top_categories) for one peer.

    total_amount = SUM(amount_granted_yen) across jpi_adoption_records.
    top_categories = top 3 program_kind values by adoption count, joined
    via program_id → jpi_programs.program_kind.
    """
    if not _table_exists(am_conn, "jpi_adoption_records"):
        if "jpi_adoption_records" not in missing_tables:
            missing_tables.append("jpi_adoption_records")
        return None, []

    total_amount: int | None = None
    try:
        row = am_conn.execute(
            "SELECT SUM(amount_granted_yen) AS total_amount "
            "  FROM jpi_adoption_records "
            " WHERE houjin_bangou = ?",
            (houjin_bangou,),
        ).fetchone()
        if row and row["total_amount"] is not None:
            total_amount = int(row["total_amount"])
    except sqlite3.Error as exc:
        logger.warning("peer total_amount query failed: %s", exc)

    categories: list[str] = []
    if _table_exists(am_conn, "jpi_programs"):
        try:
            cat_rows = am_conn.execute(
                "SELECT p.program_kind AS kind, COUNT(*) AS n "
                "  FROM jpi_adoption_records a "
                "  JOIN jpi_programs p ON p.unified_id = a.program_id "
                " WHERE a.houjin_bangou = ? "
                "   AND p.program_kind IS NOT NULL "
                " GROUP BY p.program_kind "
                " ORDER BY n DESC, kind ASC "
                " LIMIT 3",
                (houjin_bangou,),
            ).fetchall()
            categories = [str(r["kind"]) for r in cat_rows if r["kind"] is not None]
        except sqlite3.Error as exc:
            logger.warning("peer category query failed: %s", exc)
    return total_amount, categories


# ---------------------------------------------------------------------------
# Statistical context + peer-validated program list
# ---------------------------------------------------------------------------


def _query_adoption_count(am_conn: sqlite3.Connection, *, houjin_bangou: str | None) -> int:
    """Adoption count for the query houjin (0 when未登録 / no row)."""
    if not houjin_bangou:
        return 0
    if not _table_exists(am_conn, "am_adopted_company_features"):
        return 0
    try:
        row = am_conn.execute(
            "SELECT adoption_count FROM am_adopted_company_features "
            " WHERE houjin_bangou = ? LIMIT 1",
            (houjin_bangou,),
        ).fetchone()
    except sqlite3.Error:
        return 0
    if row is None or row["adoption_count"] is None:
        return 0
    return int(row["adoption_count"])


def _percentile_of(value: float, distribution: list[float]) -> float:
    """Return the percentile rank of value within distribution (0..100).

    Uses the "fraction strictly less than value" convention, scaled by
    100 and rounded to one decimal. Empty distribution returns 0.0.
    """
    if not distribution:
        return 0.0
    lt = sum(1 for v in distribution if v < value)
    eq = sum(1 for v in distribution if v == value)
    # "midrank" convention: half-credit for ties so identical values land
    # at the same percentile regardless of tied bucket size.
    rank = (lt + 0.5 * eq) / len(distribution)
    return round(rank * 100.0, 1)


def _peer_recommended_programs(
    am_conn: sqlite3.Connection,
    *,
    peer_houjin_bangous: list[str],
    missing_tables: list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Top programs by peer adoption rate.

    Adoption rate = (peers who adopted program X) / (total peers).
    Joined to jpi_programs for primary_name + program_kind + amount.
    """
    if not peer_houjin_bangous:
        return []
    if not _table_exists(am_conn, "jpi_adoption_records"):
        if "jpi_adoption_records" not in missing_tables:
            missing_tables.append("jpi_adoption_records")
        return []

    placeholders = ",".join(["?"] * len(peer_houjin_bangous))
    try:
        rows = am_conn.execute(
            "SELECT program_id, "
            "       COUNT(DISTINCT houjin_bangou) AS adopters, "
            "       AVG(amount_granted_yen) AS est_amount "
            "  FROM jpi_adoption_records "
            f" WHERE houjin_bangou IN ({placeholders}) "
            "   AND program_id IS NOT NULL "
            " GROUP BY program_id "
            " ORDER BY adopters DESC, program_id ASC "
            " LIMIT ?",
            (*peer_houjin_bangous, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("peer recommended programs query failed: %s", exc)
        return []

    has_jpi_programs = _table_exists(am_conn, "jpi_programs")
    total = len(peer_houjin_bangous)
    out: list[dict[str, Any]] = []
    for r in rows:
        pid = r["program_id"]
        name: str | None = None
        if has_jpi_programs:
            try:
                name_row = am_conn.execute(
                    "SELECT primary_name FROM jpi_programs  WHERE unified_id = ? LIMIT 1",
                    (pid,),
                ).fetchone()
                if name_row:
                    name = name_row["primary_name"]
            except sqlite3.Error:
                name = None
        adopters = int(r["adopters"]) if r["adopters"] is not None else 0
        est = int(round(float(r["est_amount"]))) if r["est_amount"] is not None else None
        out.append(
            {
                "program_id": pid,
                "name": name,
                "peer_adoption_rate": (round(adopters / total, 4) if total else 0.0),
                "peer_adopter_count": adopters,
                "est_amount": est,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def _build_envelope(
    am_conn: sqlite3.Connection,
    *,
    payload: PeerGroupRequest,
) -> dict[str, Any]:
    missing: list[str] = []

    houjin_id = _normalize_houjin(payload.houjin_id) if payload.houjin_id else None
    if payload.houjin_id and not _is_valid_houjin(houjin_id or ""):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_id",
                "field": "houjin_id",
                "message": (f"houjin_id must be 13 digits when supplied (got {houjin_id!r})."),
            },
        )

    profile = _fetch_query_profile(
        am_conn,
        houjin_id=houjin_id,
        attrs=payload.houjin_attributes,
        missing_tables=missing,
    )

    # Build feature set for the query houjin. The Jaccard scorer needs at
    # least one populated axis; absent everything, we cannot find peers.
    query_features = _features_for(
        jsic=profile.get("jsic"),
        prefecture=profile.get("prefecture"),
        capital=profile.get("capital"),
        employees=profile.get("employees"),
    )
    if not query_features:
        # Soft-fail: return an empty peer list with an honest envelope.
        return {
            "query_houjin": profile,
            "peers": [],
            "statistical_context": {
                "peer_avg_adoption_count": None,
                "peer_avg_amount": None,
                "query_percentile": None,
                "peer_count": 0,
            },
            "recommended_programs_peers_used": [],
            "data_quality": {
                "missing_tables": missing,
                "candidate_pool_size": 0,
                "reason": "query houjin has no populated features",
            },
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }

    candidates = _candidate_pool(
        am_conn,
        profile=profile,
        exclude_houjin=houjin_id,
        missing_tables=missing,
    )

    # Score every candidate by Jaccard similarity. We lazy-fetch
    # capital/employees for the top-N pool only after the cheap jsic+pref
    # similarity prune narrows the pool — perf optimization on the 2k cap.
    scored: list[tuple[float, dict[str, Any]]] = []
    for c in candidates:
        # Use the cheap features first (jsic + pref); fetch capital / employees
        # only for candidates whose cheap-features score is non-zero.
        cheap_features = _features_for(
            jsic=c.get("jsic"),
            prefecture=c.get("prefecture"),
            capital=None,
            employees=None,
        )
        cheap_score = _jaccard_similarity(query_features, cheap_features)
        if cheap_score == 0.0:
            continue
        # Now fetch capital/employees only for non-zero candidates.
        cap, emp = _fetch_houjin_capital_employees(
            am_conn,
            houjin_bangou=c["houjin_bangou"],
            missing_tables=missing,
        )
        peer_features = _features_for(
            jsic=c.get("jsic"),
            prefecture=c.get("prefecture"),
            capital=cap,
            employees=emp,
        )
        full_score = _jaccard_similarity(query_features, peer_features)
        c["capital"] = cap
        c["employees"] = emp
        scored.append((full_score, c))

    # Sort by similarity desc, tiebreak by adoption_count desc, then bangou.
    scored.sort(
        key=lambda t: (
            -t[0],
            -int(t[1].get("adoption_count") or 0),
            t[1]["houjin_bangou"],
        )
    )
    top = scored[: payload.peer_count]

    # Per-peer enrichment: adoption_count + total_amount + categories.
    peers_out: list[dict[str, Any]] = []
    peer_amounts: list[float] = []
    peer_adoption_counts: list[float] = []
    for sim, c in top:
        total_amount, categories = _peer_program_facts(
            am_conn,
            houjin_bangou=c["houjin_bangou"],
            missing_tables=missing,
        )
        axes_compared: dict[str, Any] = {
            "jsic": {"query": profile.get("jsic"), "peer": c.get("jsic")},
            "prefecture": {
                "query": profile.get("prefecture"),
                "peer": c.get("prefecture"),
            },
        }
        if "adoption_count" in payload.comparison_axes:
            axes_compared["adoption_count"] = c.get("adoption_count")
        if "total_amount" in payload.comparison_axes:
            axes_compared["total_amount"] = total_amount
        if "category_diversity" in payload.comparison_axes:
            axes_compared["category_diversity"] = len(categories)
        # Capital / employees axes are always echoed when present (they
        # are similarity inputs, so the auditor needs to see them).
        axes_compared["capital_log_bucket"] = {
            "query": _log_bucket(profile.get("capital")),
            "peer": _log_bucket(c.get("capital")),
        }
        axes_compared["employee_log_bucket"] = {
            "query": _log_bucket(profile.get("employees")),
            "peer": _log_bucket(c.get("employees")),
        }

        peers_out.append(
            {
                "houjin_id": c["houjin_bangou"],
                "name": c.get("name"),
                "similarity_score": sim,
                "axes_compared": axes_compared,
                "adoption_count": c.get("adoption_count"),
                "total_amount_estimated": total_amount,
                "top_categories": categories,
            }
        )
        peer_adoption_counts.append(float(c.get("adoption_count") or 0))
        if total_amount is not None:
            peer_amounts.append(float(total_amount))

    # Statistical context.
    peer_avg_adoption = (
        round(sum(peer_adoption_counts) / len(peer_adoption_counts), 2)
        if peer_adoption_counts
        else None
    )
    peer_avg_amount = int(round(sum(peer_amounts) / len(peer_amounts))) if peer_amounts else None
    query_adopt = _query_adoption_count(am_conn, houjin_bangou=houjin_id)
    query_pct = (
        _percentile_of(float(query_adopt), peer_adoption_counts) if peer_adoption_counts else None
    )

    statistical_context: dict[str, Any] = {
        "peer_avg_adoption_count": peer_avg_adoption,
        "peer_avg_amount": peer_avg_amount,
        "query_percentile": query_pct,
        "query_adoption_count": query_adopt,
        "peer_count": len(peers_out),
    }

    # Peer-validated program recommendations.
    recommended = _peer_recommended_programs(
        am_conn,
        peer_houjin_bangous=[p["houjin_id"] for p in peers_out],
        missing_tables=missing,
    )

    body: dict[str, Any] = {
        "query_houjin": profile,
        "peers": peers_out,
        "statistical_context": statistical_context,
        "recommended_programs_peers_used": recommended,
        "data_quality": {
            "missing_tables": sorted(set(missing)),
            "candidate_pool_size": len(candidates),
            "scored_pool_size": len(scored),
            "comparison_axes": list(payload.comparison_axes),
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post(
    "/peer_group",
    summary="同業他社 peer-group + adoption stats — 5 peers in 1 call (NO LLM)",
    description=(
        "Returns the N nearest peer 法人 (Jaccard on jsic + prefecture + "
        "log-bucketed capital / employees) along with each peer's adoption "
        "count / total amount / top categories, statistical context "
        "(peer avg + percentile), and a peer-validated top-N program list. "
        "Cross-joins houjin_master + am_adopted_company_features + "
        "am_geo_industry_density + am_entity_facts (corp.*) + "
        "jpi_adoption_records + jpi_programs.\n\n"
        "**Pricing:** ¥3 / call (1 unit total).\n\n"
        "Sensitive: 景表法 / 行政書士法 §1の2 / 税理士法 §52 fence."
    ),
)
def post_intel_peer_group(
    payload: Annotated[PeerGroupRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    _t0 = time.perf_counter()

    # Cross-field validation. Done in the route handler (not a pydantic
    # model_validator) because the global RequestValidationError handler
    # in main.py JSON-encodes the error context dict, and pydantic's
    # `value_error` ctx ships the original ValueError instance which
    # blows up the encoder. HTTPException(422) sidesteps that path.
    if not payload.houjin_id and not payload.houjin_attributes:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_required_field",
                "field": "houjin_id|houjin_attributes",
                "message": ("either 'houjin_id' or 'houjin_attributes' must be supplied"),
            },
        )
    bad_axes = [a for a in payload.comparison_axes if a not in _VALID_AXES]
    if bad_axes:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_comparison_axes",
                "field": "comparison_axes",
                "message": (f"unknown comparison_axes: {bad_axes!r}; valid={sorted(_VALID_AXES)}"),
            },
        )

    # Open autonomath.db (peer-group substrate lives there). Lazy import so
    # tests can monkeypatch AUTONOMATH_DB_PATH between cases.
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

    try:
        am_conn = connect_autonomath()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unavailable",
                "message": str(exc),
            },
        ) from exc
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unavailable",
                "message": str(exc),
            },
        ) from exc

    try:
        body = _build_envelope(am_conn, payload=payload)
    finally:
        # Per-thread connection is reused — do NOT close. The test harness
        # monkeypatches AUTONOMATH_DB_PATH between cases via the close_all
        # fixture. We do swallow any rare close error defensively.
        with contextlib.suppress(sqlite3.Error):
            pass

    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.peer_group",
        latency_ms=latency_ms,
        result_count=len(body.get("peers") or []),
        params={
            "houjin_id_present": bool(payload.houjin_id),
            "houjin_attributes_present": bool(payload.houjin_attributes),
            "peer_count": payload.peer_count,
            "axes_count": len(payload.comparison_axes),
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.peer_group",
        request_params={
            "houjin_id": _normalize_houjin(payload.houjin_id) if payload.houjin_id else None,
            "peer_count": payload.peer_count,
            "comparison_axes": list(payload.comparison_axes),
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = ["router"]
