"""MCP tools for Wave 34 Axis 4 precomputed tables.

5 read-only tools backed by precomputed stores (mig 235-239):

  portfolio_optimize_precomputed_am
  houjin_risk_score_am
  program_forecast_30yr_am
  alliance_opportunities_am
  graph_vec_search_am

NO LLM SDK import. Pure SQL + Python.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import struct
from typing import Any

from jpintel_mcp.mcp.server import mcp

from .db import connect_autonomath

LOG = logging.getLogger(__name__)

_TAX_DISCLAIMER = (
    "本 response は public corpus + 法人 master + 採択 history + 行政処分 "
    "+ am_compat_matrix からの統計 signal です。"
    "税理士法 §52 / 行政書士法 §1 / 弁護士法 §72 上の助言ではありません。"
    "最終判断は専門家に相談してください。"
)

_KIND_TO_TABLE = {
    "program": "am_entities_vec_S",
    "case_study": "am_entities_vec_C",
    "court_decision": "am_entities_vec_J",
    "adoption": "am_entities_vec_A",
    "corporate_entity": "am_entities_vec_E",
    "statistic": "am_entities_vec_T",
    "tax_measure": "am_entities_vec_T",
    "enforcement": "am_entities_vec_F",
    "invoice_registrant": "am_entities_vec_I",
    "law": "am_entities_vec_L",
    "certification": "am_entities_vec_R",
    "authority": "am_entities_vec_R",
    "document": "am_entities_vec_R",
}


def _select_first(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
) -> Any:
    try:
        return conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return None


def _select_all(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
) -> list[Any]:
    try:
        return list(conn.execute(sql, params).fetchall())
    except sqlite3.OperationalError:
        return []


@mcp.tool(
    name="portfolio_optimize_precomputed_am",
    description=(
        "Top 8 program ranked recommendations for a 法人 (precomputed daily). "
        "Reads am_portfolio_optimize (mig 235, daily cron) — distinct from "
        "compatibility_tools.portfolio_optimize_am which composes "
        "am_compat_matrix at request time. Fast-path for 税理士 顧問先 fan-out. "
        "NO LLM, 1 ¥3 billable unit. §52/§1/§72 envelope."
    ),
)
def portfolio_optimize_precomputed_am(
    houjin_bangou: str,
    limit: int = 8,
) -> dict[str, Any]:
    """Return precomputed top-N portfolio for houjin_bangou."""
    limit = max(1, min(8, int(limit or 8)))
    conn = connect_autonomath()
    rows = _select_all(
        conn,
        "SELECT rank, program_unified_id, program_primary_name, score_0_100, "
        " tier, program_amount_max_yen, reason_json, refreshed_at "
        "FROM am_portfolio_optimize WHERE houjin_bangou = ? ORDER BY rank LIMIT ?",
        (houjin_bangou, limit),
    )
    items = []
    refreshed_at = None
    for r in rows:
        refreshed_at = refreshed_at or r["refreshed_at"]
        signals = {}
        if r["reason_json"]:
            try:
                signals = json.loads(r["reason_json"]).get("signals", {})
            except (json.JSONDecodeError, TypeError):
                signals = {}
        items.append(
            {
                "rank": r["rank"],
                "program_unified_id": r["program_unified_id"],
                "program_primary_name": r["program_primary_name"],
                "score_0_100": r["score_0_100"],
                "tier": r["tier"],
                "program_amount_max_yen": r["program_amount_max_yen"],
                "signals": signals,
            }
        )
    return {
        "houjin_bangou": houjin_bangou,
        "refreshed_at": refreshed_at,
        "items": items,
        "_disclaimer": _TAX_DISCLAIMER,
        "_source": "am_portfolio_optimize (mig 235, daily cron)",
    }


@mcp.tool(
    name="houjin_risk_score_am",
    description=(
        "0-100 composite risk score for a 法人 (daily refresh). 40 enforcement "
        "+ 30 invoice + 15 adoption + 15 credit_age. Pure SELECT against "
        "am_houjin_risk_score. NO LLM, 1 ¥3 billable unit. §52 envelope."
    ),
)
def houjin_risk_score_am(houjin_bangou: str) -> dict[str, Any]:
    """Return precomputed risk score for houjin_bangou."""
    conn = connect_autonomath()
    row = _select_first(
        conn,
        "SELECT risk_score_0_100, risk_bucket, enforcement_subscore, invoice_subscore, "
        " adoption_subscore, credit_age_subscore, signals_json, refreshed_at "
        "FROM am_houjin_risk_score WHERE houjin_bangou = ?",
        (houjin_bangou,),
    )
    if row is None:
        return {
            "houjin_bangou": houjin_bangou,
            "found": False,
            "_disclaimer": _TAX_DISCLAIMER,
            "_hint": "Risk row not yet precomputed for this houjin_bangou.",
        }
    signals = {}
    if row["signals_json"]:
        try:
            signals = json.loads(row["signals_json"])
        except (json.JSONDecodeError, TypeError):
            signals = {}
    return {
        "houjin_bangou": houjin_bangou,
        "found": True,
        "risk_score_0_100": row["risk_score_0_100"],
        "risk_bucket": row["risk_bucket"],
        "subscores": {
            "enforcement": row["enforcement_subscore"],
            "invoice": row["invoice_subscore"],
            "adoption": row["adoption_subscore"],
            "credit_age": row["credit_age_subscore"],
        },
        "signals": signals,
        "refreshed_at": row["refreshed_at"],
        "_disclaimer": _TAX_DISCLAIMER,
        "_source": "am_houjin_risk_score (mig 236, daily cron)",
    }


@mcp.tool(
    name="program_forecast_30yr_am",
    description=(
        "30-year x 12-month Markov chain forecast for a program (monthly refresh). "
        "Returns per-(year, month) state distribution over "
        "{active, paused, sunset, renewed} + expected_call_count cumulative. "
        "Pure SELECT against am_subsidy_30yr_forecast. NO LLM, 1 ¥3 unit. "
        "Not §52 sensitive — statistical projection."
    ),
)
def program_forecast_30yr_am(program_unified_id: str, year_offset_max: int = 30) -> dict[str, Any]:
    """Return precomputed 30-year forecast trajectory."""
    year_offset_max = max(1, min(30, int(year_offset_max or 30)))
    conn = connect_autonomath()
    rows = _select_all(
        conn,
        "SELECT forecast_year_offset, horizon_month, state, p_active, p_paused, "
        " p_sunset, p_renewed, expected_call_count, refreshed_at "
        "FROM am_subsidy_30yr_forecast "
        "WHERE program_unified_id = ? AND forecast_year_offset < ? "
        "ORDER BY forecast_year_offset, horizon_month",
        (program_unified_id, year_offset_max),
    )
    return {
        "program_unified_id": program_unified_id,
        "refreshed_at": rows[0]["refreshed_at"] if rows else None,
        "found": bool(rows),
        "horizon": [
            {
                "forecast_year_offset": r["forecast_year_offset"],
                "horizon_month": r["horizon_month"],
                "state": r["state"],
                "p_active": r["p_active"],
                "p_paused": r["p_paused"],
                "p_sunset": r["p_sunset"],
                "p_renewed": r["p_renewed"],
                "expected_call_count": r["expected_call_count"],
            }
            for r in rows
        ],
        "_source": "am_subsidy_30yr_forecast (mig 237, monthly cron)",
    }


@mcp.tool(
    name="alliance_opportunities_am",
    description=(
        "Top 10 partner 法人 候補 for a source 法人 (weekly refresh). "
        "Composes co-adoption + JSIC chain + size balance + region proximity "
        "into a 0-100 score. Pure SELECT against am_alliance_opportunity. "
        "NO LLM, 1 ¥3 billable unit. §52/§1/§72 envelope."
    ),
)
def alliance_opportunities_am(houjin_bangou: str, limit: int = 10) -> dict[str, Any]:
    """Return precomputed top-N partner candidates."""
    limit = max(1, min(10, int(limit or 10)))
    conn = connect_autonomath()
    rows = _select_all(
        conn,
        "SELECT rank, partner_houjin_bangou, partner_primary_name, alliance_score_0_100, "
        " co_adoption_count, industry_chain_pair, region_a, region_b, reason_json, refreshed_at "
        "FROM am_alliance_opportunity WHERE houjin_bangou = ? ORDER BY rank LIMIT ?",
        (houjin_bangou, limit),
    )
    items = []
    refreshed_at = None
    for r in rows:
        refreshed_at = refreshed_at or r["refreshed_at"]
        signals = {}
        if r["reason_json"]:
            try:
                signals = json.loads(r["reason_json"]).get("signals", {})
            except (json.JSONDecodeError, TypeError):
                signals = {}
        items.append(
            {
                "rank": r["rank"],
                "partner_houjin_bangou": r["partner_houjin_bangou"],
                "partner_primary_name": r["partner_primary_name"],
                "alliance_score_0_100": r["alliance_score_0_100"],
                "co_adoption_count": r["co_adoption_count"],
                "industry_chain_pair": r["industry_chain_pair"],
                "region_a": r["region_a"],
                "region_b": r["region_b"],
                "signals": signals,
            }
        )
    return {
        "houjin_bangou": houjin_bangou,
        "refreshed_at": refreshed_at,
        "items": items,
        "_disclaimer": _TAX_DISCLAIMER,
        "_source": "am_alliance_opportunity (mig 238, weekly cron)",
    }


@mcp.tool(
    name="graph_vec_search_am",
    description=(
        "Top-k semantic similar entity via sqlite-vec k-NN over am_entities "
        "(503,930 rows x 12 record_kinds). Pure SQL k-NN on precomputed "
        "embeddings. NO LLM at request time. 1 ¥3 unit."
    ),
)
def graph_vec_search_am(
    query_text: str,
    top_k: int = 10,
    record_kinds: list[str] | None = None,
) -> dict[str, Any]:
    """Top-k semantic similar entity over am_entities_vec_* tables."""
    top_k = max(1, min(50, int(top_k or 10)))
    conn = connect_autonomath()
    ledger = _select_first(
        conn,
        "SELECT model_name, embed_dim FROM am_entities_vec_refresh_log "
        "WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1",
        (),
    )
    model_id = (ledger["model_name"] if ledger else None) or "hash-fallback-v1"
    dim = int(ledger["embed_dim"]) if ledger and ledger["embed_dim"] else 384

    text = (query_text or "").strip() or " "
    seed = text.encode("utf-8")
    h = hashlib.sha256(seed).digest()
    qvec: list[float] = []
    while len(qvec) < dim:
        qvec.extend((b - 127.5) / 127.5 for b in h)
        h = hashlib.sha256(h).digest()
    qvec = qvec[:dim]
    qbytes = struct.pack(f"{len(qvec)}f", *qvec)

    if record_kinds:
        target_tables = sorted({_KIND_TO_TABLE[k] for k in record_kinds if k in _KIND_TO_TABLE})
    else:
        target_tables = sorted(set(_KIND_TO_TABLE.values()))

    hits = []
    for table in target_tables:
        try:
            cur = conn.execute(
                f"SELECT entity_id, distance FROM {table} "
                f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (qbytes, top_k),
            )
            for row in cur:
                meta = _select_first(
                    conn,
                    "SELECT primary_name, record_kind FROM am_entities WHERE canonical_id = ?",
                    (row[0],),
                )
                hits.append(
                    {
                        "canonical_id": row[0],
                        "record_kind": (meta["record_kind"] if meta else "unknown"),
                        "primary_name": (meta["primary_name"] if meta else None),
                        "distance": float(row[1]),
                    }
                )
        except sqlite3.OperationalError:
            continue
    hits.sort(key=lambda h: h["distance"])
    hits = hits[:top_k]
    return {
        "query_text": query_text,
        "embed_model": model_id,
        "embed_dim": dim,
        "hits": hits,
        "_disclaimer": _TAX_DISCLAIMER,
        "_source": "am_entities_vec_* (mig 239, monthly+daily cron)",
    }
