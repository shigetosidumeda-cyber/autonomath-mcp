"""POST /v1/intel/probability_radar — program × houjin radar bundle.

Returns in 1 call: probability_estimate (statistical, NOT a forecast),
same_industry_adoption_rate, mean_award_amount_yen,
estimated_application_effort_hours, roi_per_program (expected award - effort
cost), evidence_packets, and a §52 / §1 行政書士法 disclaimer envelope so the
customer LLM can immediately turn it into an actionable answer.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside this endpoint. Pure SQLite SELECT + Python arithmetic
  over `am_recommended_programs` (wave24_126), `am_adopted_company_features`
  (wave24_157), and `jpi_adoption_records`.
* The output is a **statistical estimate**. The disclaimer text forbids
  「採択確実」「採択保証」「採択率予測」 phrasing per 景表法 fence in the
  sibling `score_application_probability` MCP tool. Final go/no-go is the
  customer LLM's responsibility, with 確定判断 deferred to qualified
  行政書士 / 中小企業診断士 (行政書士法 §1の2).

Graceful degradation
--------------------
When a target table is missing in a fresh dev DB, the field for that axis
returns `null` and the table name is added to `data_quality.missing_tables`
— the customer LLM gets a partial-but-honest envelope rather than a 500.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body, get_corpus_snapshot_id
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api._response_models import IntelMatchResponse
from jpintel_mcp.api.audit_proof import (
    _build_proof_path,
    _fetch_all_leaves,
    _fetch_anchor,
    _fetch_leaf,
    _github_commit_url,
    _open_autonomath_rw,
    _ots_url_for,
)
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# Heuristic: median application effort hours. Fixed default reflects the
# operator's published 申請工数 estimates; per-program overrides land later
# via `am_program_effort_hours` if/when that table ships. The hourly rate
# is the published 中小企業診断士 standard ¥8,000 / hour.
_DEFAULT_EFFORT_HOURS: int = 25
_EFFORT_HOURLY_RATE_YEN: int = 8_000


_DISCLAIMER = (
    "本 probability_estimate は am_recommended_programs (採択者プロファイル類似度) "
    "+ jpi_adoption_records 由来の **統計的推定** であり、「採択確実」「採択保証」"
    "「採択率予測」 ではない。output field 名は `probability_estimate` (estimate) "
    "であり `probability_forecast` ではない。本 estimate を「採択保証」「採択確実」"
    "として広告・営業に使用することは景表法 (不当景品類及び不当表示防止法) 違反の"
    "リスクがあるため禁止。申請可否判断 (行政書士法 §1の2) の代替ではなく、確定判断は"
    "資格を有する行政書士・中小企業診断士へ。"
)


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


class ProbabilityRadarRequest(BaseModel):
    """POST body for /v1/intel/probability_radar."""

    program_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Program unified id (UNI-...) or canonical id (program:...).",
    )
    houjin_bangou: str = Field(
        ...,
        min_length=13,
        max_length=14,
        description="13-digit 法人番号 (NTA canonical), with or without 'T' prefix.",
    )
    effort_hours_override: int | None = Field(
        None,
        ge=1,
        le=2000,
        description=(
            "Optional caller-supplied per-program 申請工数 estimate (hours). "
            "Defaults to the operator-published median (25h) when null."
        ),
    )
    hourly_rate_yen_override: int | None = Field(
        None,
        ge=1_000,
        le=100_000,
        description=(
            "Optional caller-supplied 中小企業診断士 hourly rate in JPY. "
            f"Defaults to ¥{_EFFORT_HOURLY_RATE_YEN:,} when null."
        ),
    )


def _compute_probability_estimate(
    conn: sqlite3.Connection,
    *,
    houjin_bangou: str,
    program_id: str,
    missing_tables: list[str],
) -> float | None:
    """SELECT score from am_recommended_programs (wave24_126)."""
    if not _table_exists(conn, "am_recommended_programs"):
        missing_tables.append("am_recommended_programs")
        return None
    try:
        row = conn.execute(
            "SELECT score FROM am_recommended_programs "
            "WHERE houjin_bangou = ? AND program_unified_id = ? LIMIT 1",
            (houjin_bangou, program_id),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("am_recommended_programs query failed: %s", exc)
        return None
    if not row or row["score"] is None:
        return None
    return round(float(row["score"]), 4)


def _compute_industry_rate_and_award(
    conn: sqlite3.Connection,
    *,
    houjin_bangou: str,
    program_id: str,
    missing_tables: list[str],
) -> tuple[float | None, int | None, int]:
    """Same-industry adoption rate + mean award amount (jpi_adoption_records).

    Returns (same_industry_adoption_rate, mean_award_amount_yen, total_program_adoption_count).
    `same_industry_adoption_rate` = (program adoptions whose
    industry_jsic_medium starts with the houjin's dominant_jsic_major) /
    (total program adoptions). Returns null if either side is missing.
    """
    if not _table_exists(conn, "jpi_adoption_records"):
        missing_tables.append("jpi_adoption_records")
        return None, None, 0

    # Mean award amount + total count per program.
    try:
        agg = conn.execute(
            "SELECT COUNT(*) AS total_n, "
            "       AVG(amount_granted_yen) AS mean_yen "
            "  FROM jpi_adoption_records "
            " WHERE program_id = ?",
            (program_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("jpi_adoption_records aggregate failed: %s", exc)
        return None, None, 0
    total_n = int(agg["total_n"]) if agg and agg["total_n"] is not None else 0
    mean_yen: int | None = (
        int(round(float(agg["mean_yen"]))) if agg and agg["mean_yen"] is not None else None
    )

    # Resolve houjin's dominant industry from am_adopted_company_features
    # (wave24_157). Fallback null if missing.
    dominant_jsic: str | None = None
    if _table_exists(conn, "am_adopted_company_features"):
        try:
            f_row = conn.execute(
                "SELECT dominant_jsic_major FROM am_adopted_company_features "
                "WHERE houjin_bangou = ? LIMIT 1",
                (houjin_bangou,),
            ).fetchone()
            if f_row and f_row["dominant_jsic_major"]:
                dominant_jsic = str(f_row["dominant_jsic_major"]).strip()
        except sqlite3.Error as exc:
            logger.warning("am_adopted_company_features query failed: %s", exc)
    else:
        missing_tables.append("am_adopted_company_features")

    same_industry_rate: float | None = None
    if dominant_jsic and total_n > 0:
        try:
            ind_row = conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM jpi_adoption_records "
                " WHERE program_id = ? "
                "   AND industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ?",
                (program_id, dominant_jsic[:1]),
            ).fetchone()
            ind_n = int(ind_row["n"]) if ind_row and ind_row["n"] is not None else 0
            same_industry_rate = round(ind_n / total_n, 4) if total_n else None
        except sqlite3.Error as exc:
            logger.warning("industry-rate query failed: %s", exc)

    return same_industry_rate, mean_yen, total_n


def _build_evidence_packets(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Up to `limit` source_url citations from jpi_adoption_records.

    Each packet is the minimal {source_url, program_id, kind} envelope so
    the customer LLM can re-fetch / cite without a follow-up call.
    """
    packets: list[dict[str, Any]] = []
    if not _table_exists(conn, "jpi_adoption_records"):
        return packets
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_url FROM jpi_adoption_records "
            " WHERE program_id = ? AND source_url IS NOT NULL "
            " LIMIT ?",
            (program_id, int(limit)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("evidence-packet query failed: %s", exc)
        return packets
    for r in rows:
        url = r["source_url"]
        if url:
            packets.append(
                {
                    "kind": "adoption_record",
                    "program_id": program_id,
                    "source_url": url,
                }
            )
    return packets


@router.post(
    "/probability_radar",
    summary="Probability radar — 統計的推定 + fee context / program in one call",
    description=(
        "Returns probability_estimate (NOT a forecast), same-industry adoption "
        "rate, mean award amount, application effort estimate, and fee context for a "
        "given (program_id, houjin_bangou) pair. NO LLM call, pure SQLite. "
        "Sensitive: §52 / §1 行政書士法 fence."
    ),
)
def post_probability_radar(
    payload: Annotated[ProbabilityRadarRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    _t0 = time.perf_counter()

    hb = _normalize_houjin(payload.houjin_bangou)
    if not _is_valid_houjin(hb):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_bangou",
                "field": "houjin_bangou",
                "message": f"houjin_bangou must be 13 digits (got {hb!r}).",
            },
        )
    pid = payload.program_id.strip()

    # Open autonomath.db (the wave24 substrate lives there). Lazy import so
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

    missing_tables: list[str] = []
    try:
        probability_estimate = _compute_probability_estimate(
            am_conn,
            houjin_bangou=hb,
            program_id=pid,
            missing_tables=missing_tables,
        )
        (
            same_industry_rate,
            mean_award_yen,
            program_adoption_count,
        ) = _compute_industry_rate_and_award(
            am_conn,
            houjin_bangou=hb,
            program_id=pid,
            missing_tables=missing_tables,
        )
        evidence_packets = _build_evidence_packets(am_conn, program_id=pid)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    effort_hours = int(payload.effort_hours_override or _DEFAULT_EFFORT_HOURS)
    hourly_rate = int(payload.hourly_rate_yen_override or _EFFORT_HOURLY_RATE_YEN)
    effort_cost_yen = effort_hours * hourly_rate

    # ROI: expected award = probability * mean_award. If either side is null,
    # net is null (we do NOT silently substitute a zero).
    expected_award_yen: int | None = None
    if probability_estimate is not None and mean_award_yen is not None:
        expected_award_yen = int(round(probability_estimate * mean_award_yen))
    net_expected_yen: int | None = None
    if expected_award_yen is not None:
        net_expected_yen = expected_award_yen - effort_cost_yen

    body: dict[str, Any] = {
        "program_id": pid,
        "houjin_bangou": hb,
        "probability_estimate": probability_estimate,
        "same_industry_adoption_rate": same_industry_rate,
        "mean_award_amount_yen": mean_award_yen,
        "estimated_application_effort_hours": effort_hours,
        "roi_per_program": {
            "expected_award_yen": expected_award_yen,
            "effort_cost_yen": effort_cost_yen,
            "net_expected_yen": net_expected_yen,
            "hourly_rate_yen": hourly_rate,
        },
        "evidence_packets": evidence_packets,
        "data_quality": {
            "missing_tables": missing_tables,
            "program_adoption_record_count": program_adoption_count,
            "probability_basis": (
                "am_recommended_programs.score (similarity, NOT forecast)"
                if probability_estimate is not None
                else None
            ),
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    # Auditor reproducibility (corpus_snapshot_id + corpus_checksum) — same
    # pattern the Wave 22/24 composition tools use so a customer LLM can
    # cite the exact corpus snapshot the radar was computed against.
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.probability_radar",
        latency_ms=latency_ms,
        result_count=1 if probability_estimate is not None else 0,
        params={
            "program_id": pid,
            "houjin_bangou_present": bool(hb),
            "effort_hours_override": payload.effort_hours_override,
            "hourly_rate_yen_override": payload.hourly_rate_yen_override,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.probability_radar",
        request_params={"program_id": pid, "houjin_bangou": hb},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


# ---------------------------------------------------------------------------
# /v1/intel/audit_chain — composite Merkle proof + sources + verify chain
# ---------------------------------------------------------------------------
#
# 監査担当者 (auditor / 税務調査官) currently has to fan out across:
#   * GET /v1/audit/proof/{epid}     (Merkle inclusion proof)
#   * GET /v1/audit/seals/{seal_id}  (HMAC seal envelope)
#   * GET /v1/am/provenance/{eid}    (per-source content_hash + license)
# and re-implement the verifier fold themselves before they trust the row.
#
# This composite endpoint merges all three reads + emits a 5-step verify
# chain whose booleans the auditor can paste directly into a 監査調書.
# Same ¥3 metering as a single read (`_billing_unit: 1`); the saving is
# on round-trip count + LLM context token consumption.
#
# NOT a tax-advice surface — pure cryptographic provenance compaction.

_AUDIT_CHAIN_DISCLAIMER = (
    "本エンドポイントは Merkle 包含証明 + 出典 URL + 改竄検証チェーンを 1 call で"
    "返却する暗号学的監査基盤であり、税理士法 §52 / 公認会計士法 §47条の2 に基づく"
    "税務判断・監査意見の代替ではありません。 verify_chain の各 step は本サーバ側"
    "の再計算結果であり、監査担当者は OpenTimestamps + GitHub commit の独立検証も"
    "合わせて実施してください。"
)

_EPID_RE = re.compile(r"^evp_[A-Za-z0-9_]{1,64}$")


class AuditChainRequest(BaseModel):
    """Request body for POST /v1/intel/audit_chain."""

    evidence_packet_id: str = Field(
        ...,
        min_length=5,
        max_length=80,
        description="Evidence packet identifier, e.g. 'evp_a1b2c3d4'.",
        examples=["evp_a1b2c3d4e5f6g7h8"],
    )


def _verify_proof_path(
    leaf_hash: str,
    proof_path: list[dict[str, str]],
    expected_root: str,
) -> bool:
    """Walk the proof path and return True iff the recomputed root matches.

    Mirrors the verifier fold documented on /v1/audit/proof/{epid}:

        h = leaf_hash
        for entry in proof_path:
            if entry.position == 'left':
                h = sha256(entry.hash || h)
            else:
                h = sha256(h || entry.hash)
        assert h == merkle_root

    Returns False on any non-hex byte, missing field, or mismatch — never
    raises so the verify_chain step always produces a boolean.
    """
    if not leaf_hash or not expected_root:
        return False
    h = leaf_hash
    try:
        for entry in proof_path:
            sibling = entry.get("hash") or ""
            position = entry.get("position") or ""
            digest = hashlib.sha256()
            if position == "left":
                digest.update(bytes.fromhex(sibling))
                digest.update(bytes.fromhex(h))
            elif position == "right":
                digest.update(bytes.fromhex(h))
                digest.update(bytes.fromhex(sibling))
            else:
                return False
            h = digest.hexdigest()
    except ValueError:
        return False
    return h.lower() == expected_root.lower()


def _seal_source_urls_for_epid(conn: sqlite3.Connection, epid: str) -> list[dict[str, Any]]:
    """Pull source_urls_json from any audit_seals row that referenced this epid.

    The seal envelope persists ``source_urls_json`` per metered call; we
    LIKE-search for the epid token in the column and union the URL lists.
    Result is an ordered list of unique URLs with the seal's ``ts`` as a
    best-available ``fetched_at`` (the seal ts == response flush moment).

    Pre-migration-089 DBs / fresh test DBs degrade silently to [].
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        rows = conn.execute(
            "SELECT source_urls_json, ts FROM audit_seals "
            "WHERE source_urls_json LIKE ? "
            "ORDER BY ts DESC LIMIT 50",
            (f"%{epid}%",),
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for row in rows:
        ts = row["ts"] if isinstance(row, sqlite3.Row) else row[1]
        raw = row["source_urls_json"] if isinstance(row, sqlite3.Row) else row[0]
        try:
            urls = json.loads(raw or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(urls, list):
            continue
        for u in urls:
            if not isinstance(u, str) or not u.startswith(("http://", "https://")):
                continue
            if u in seen:
                continue
            seen.add(u)
            out.append({"url": u, "fetched_at": ts})
    return out


def _enrich_with_am_source(
    am_conn: sqlite3.Connection, urls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join URL list against am_source for content_hash + last_verified.

    Missing rows in am_source surface as null content_hash but the URL
    is preserved (auditor can re-fetch and recompute the hash themselves).
    """
    enriched: list[dict[str, Any]] = []
    for entry in urls:
        url = entry.get("url")
        content_hash: str | None = None
        last_verified: str | None = None
        try:
            row = am_conn.execute(
                "SELECT content_hash, last_verified FROM am_source WHERE source_url = ? LIMIT 1",
                (url,),
            ).fetchone()
            if row is not None:
                content_hash = row["content_hash"] if isinstance(row, sqlite3.Row) else row[0]
                last_verified = row["last_verified"] if isinstance(row, sqlite3.Row) else row[1]
        except sqlite3.OperationalError:
            pass
        enriched.append(
            {
                "url": url,
                "content_hash": content_hash,
                "fetched_at": last_verified or entry.get("fetched_at"),
            }
        )
    return enriched


@router.post(
    "/audit_chain",
    summary="Composite audit chain — Merkle proof + sources + verify in 1 call",
    description=(
        "Returns the full audit chain for one `evidence_packet_id` in a "
        "single POST: Merkle inclusion proof + OpenTimestamps / GitHub "
        "anchor metadata, source URLs with content hashes and "
        "fetched_at timestamps, and a 5-step verify chain whose booleans "
        "the auditor can paste directly into a 監査調書. Replaces the "
        "legacy 3-call fan-out (/v1/audit/proof + /v1/audit/seals + "
        "/v1/am/provenance).\n\n"
        "**Billing:** ¥3 per call (`_billing_unit: 1`).\n\n"
        "**Verify chain steps:**\n\n"
        "1. `step1_recompute_leaf` — leaf_hash present in audit_merkle_leaves.\n"
        "2. `step2_walk_proof` — proof_path walks back to the daily Merkle root.\n"
        "3. `step3_verify_root` — recomputed root matches the stored root.\n"
        "4. `step4_ots_verified` — OpenTimestamps proof BLOB present (URL "
        "    surfaced for offline `ots verify`).\n"
        "5. `step5_github_anchor_found` — GitHub commit SHA present (URL "
        "    surfaced for `git log` cross-check)."
    ),
    responses={
        200: {"description": "Composite audit chain envelope."},
        400: {"description": "Malformed evidence_packet_id."},
        404: {"description": "Unknown evidence_packet_id (not yet anchored)."},
    },
)
def post_audit_chain(
    payload: Annotated[AuditChainRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return the composite audit chain for `payload.evidence_packet_id`."""
    _t0 = time.perf_counter()
    epid = payload.evidence_packet_id
    if not _EPID_RE.match(epid):
        raise HTTPException(
            status_code=400,
            detail=(
                "evidence_packet_id must match ^evp_[A-Za-z0-9_]{1,64}$ "
                "(e.g. 'evp_a1b2c3d4e5f6g7h8')."
            ),
        )

    am_conn = _open_autonomath_rw()
    try:
        try:
            leaf = _fetch_leaf(am_conn, epid)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                logger.warning("audit_merkle_leaves missing: %s", exc)
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"audit_merkle_anchor not yet provisioned on this "
                        f"volume; evidence_packet_id={epid} has no "
                        f"inclusion proof available."
                    ),
                ) from exc
            raise

        if leaf is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"evidence_packet_id={epid} not found in "
                    f"audit_merkle_leaves. Either the id is unknown, or "
                    f"its anchor cron has not run yet (anchors close at "
                    f"00:30 JST for the prior JST day)."
                ),
            )
        daily_date, leaf_index, leaf_hash = leaf

        anchor = _fetch_anchor(am_conn, daily_date)
        if anchor is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"audit_merkle_anchor missing for daily_date={daily_date} "
                    f"despite leaf row existing — anchor cron run incomplete."
                ),
            )

        all_leaves = _fetch_all_leaves(am_conn, daily_date)
        proof_path = _build_proof_path(all_leaves, leaf_index)

        # source_urls + content_hash join (am_source lives in autonomath.db).
        seal_urls = _seal_source_urls_for_epid(conn, epid)
        source_urls = _enrich_with_am_source(am_conn, seal_urls)
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()

    merkle_root = anchor["merkle_root"]
    ots_proof = anchor["ots_proof"]
    github_sha = anchor["github_commit_sha"]
    twitter_post_id = anchor["twitter_post_id"]

    # 5-step verify chain (computed server-side; auditor reads booleans).
    step1 = bool(leaf_hash)
    # Single-leaf trees have an empty proof_path (no siblings to fold) —
    # treat that as "trivially walked". Multi-leaf trees must produce at
    # least one sibling for the walk to be meaningful.
    step2 = bool(proof_path) or len(all_leaves) <= 1
    step3 = _verify_proof_path(leaf_hash, proof_path, merkle_root)
    step4 = bool(ots_proof)
    step5 = bool(github_sha)

    body: dict[str, Any] = {
        "evidence_packet_id": epid,
        "merkle": {
            "root": f"sha256:{merkle_root}",
            "leaf_index": leaf_index,
            "leaf_hash": leaf_hash,
            "proof_path": proof_path,
            "daily_date": daily_date,
            "row_count": anchor["row_count"],
            "ots_url": _ots_url_for(ots_proof),
            "ots_proof_b64": (base64.b64encode(ots_proof).decode("ascii") if ots_proof else None),
            "github_commit_url": _github_commit_url(github_sha),
            "github_commit_sha": github_sha,
            "twitter_post_id": twitter_post_id,
        },
        "source_urls": source_urls,
        "verify_chain": {
            "step1_recompute_leaf": step1,
            "step2_walk_proof": step2,
            "step3_verify_root": step3,
            "step4_ots_verified": _ots_url_for(ots_proof) if step4 else None,
            "step5_github_anchor_found": step5,
            "all_steps_pass": all([step1, step2, step3, step4, step5]),
        },
        "corpus_snapshot_id": get_corpus_snapshot_id(),
        "_disclaimer": _AUDIT_CHAIN_DISCLAIMER,
        "_billing_unit": 1,
        "_meta": {
            "verifier_algorithm": "merkle_sha256_bitcoin_style",
            "leaf_hash_recipe": "sha256(epid || params_digest || ts)",
            "creator": "Bookyou株式会社 (T8010001213708)",
            "endpoint": "intel.audit_chain",
        },
    }

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.audit_chain",
        latency_ms=latency_ms,
        result_count=1,
        params={"evidence_packet_id": epid},
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.audit_chain",
        request_params={"evidence_packet_id": epid},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body)


# ===========================================================================
# POST /v1/intel/match — smart matchmaking (single-call composite envelope).
# ===========================================================================

# JIS X 0401 prefecture code → Japanese long-form name (programs.prefecture
# stores the long-form value, e.g. "東京都" for code "13").
_PREFECTURE_CODE_TO_NAME: dict[str, str] = {
    "01": "北海道",
    "02": "青森県",
    "03": "岩手県",
    "04": "宮城県",
    "05": "秋田県",
    "06": "山形県",
    "07": "福島県",
    "08": "茨城県",
    "09": "栃木県",
    "10": "群馬県",
    "11": "埼玉県",
    "12": "千葉県",
    "13": "東京都",
    "14": "神奈川県",
    "15": "新潟県",
    "16": "富山県",
    "17": "石川県",
    "18": "福井県",
    "19": "山梨県",
    "20": "長野県",
    "21": "岐阜県",
    "22": "静岡県",
    "23": "愛知県",
    "24": "三重県",
    "25": "滋賀県",
    "26": "京都府",
    "27": "大阪府",
    "28": "兵庫県",
    "29": "奈良県",
    "30": "和歌山県",
    "31": "鳥取県",
    "32": "島根県",
    "33": "岡山県",
    "34": "広島県",
    "35": "山口県",
    "36": "徳島県",
    "37": "香川県",
    "38": "愛媛県",
    "39": "高知県",
    "40": "福岡県",
    "41": "佐賀県",
    "42": "長崎県",
    "43": "熊本県",
    "44": "大分県",
    "45": "宮崎県",
    "46": "鹿児島県",
    "47": "沖縄県",
}

# Tier ranking weight. Used as the dominant ranking term so S/A always
# outrank B/C even when verification counts diverge.
_TIER_WEIGHT: dict[str, float] = {"S": 4.0, "A": 3.0, "B": 2.0, "C": 1.0}

# Valid JSIC 大分類 codes (A–T).
_JSIC_MAJOR_CODES: frozenset[str] = frozenset("ABCDEFGHIJKLMNOPQRST")

_MATCH_DISCLAIMER = (
    "本 matched_programs は jpcite corpus (programs / adoption_records / "
    "program_law_refs / tax_rulesets) を SQL + 決定論的ランキングで突き合わせた "
    "**ヒューリスティック・マッチング** であり、「採択確実」「採択保証」"
    "「補助金受給確約」 ではない。match_score は tier 重み + verification_count "
    "+ density + キーワード一致 + (利用可能な場合) sqlite-vec 類似度 の合成スコア。"
    "申請可否判断 (行政書士法 §1の2) / 税務助言 (税理士法 §52) の代替ではなく、確定判断は"
    "資格を有する行政書士・税理士・中小企業診断士へ。"
)


class IntelMatchRequest(BaseModel):
    """POST body for /v1/intel/match.

    Customer LLM hands us four canonical filters + a free-text keyword and
    the limit. Everything else is computed server-side.
    """

    industry_jsic_major: str = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "JSIC 大分類 single letter (A–T). Filters programs whose "
            "`jsic_majors` JSON array (or single `jsic_major`) contains this code."
        ),
        examples=["E"],
    )
    prefecture_code: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description=(
            "JIS X 0401 prefecture code (01–47). 13=東京都. Programs whose "
            "`prefecture` is the matching long-form name OR is national/NULL "
            "are returned."
        ),
        examples=["13"],
    )
    capital_jpy: int | None = Field(
        None,
        ge=0,
        description="Applicant capital in JPY. Used only for soft amount-fit ranking, not exclusion.",
        examples=[50_000_000],
    )
    employee_count: int | None = Field(
        None,
        ge=0,
        description=(
            "Applicant employee headcount. Reserved for future SME-tier "
            "filtering; currently informational."
        ),
        examples=[50],
    )
    keyword: str | None = Field(
        None,
        max_length=200,
        description="Free-text keyword matched against `primary_name` (LIKE).",
        examples=["DX"],
    )
    limit: int = Field(
        5,
        ge=1,
        le=20,
        description="Cap on matched_programs[] length. Hard cap = 20.",
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    for r in rows:
        try:
            if r["name"] == column:
                return True
        except (IndexError, KeyError):
            try:
                if r[1] == column:
                    return True
            except (IndexError, KeyError):
                continue
    return False


def _build_match_where(
    conn: sqlite3.Connection,
    *,
    jsic_major: str,
    pref_name: str,
    keyword: str | None,
) -> tuple[str, list[Any], list[str]]:
    """Build WHERE-clause + params for the matchmaking SELECT.

    Returns ``(where_sql, params, applied_filters)``. Each filter is added
    only if the underlying column exists in the schema (test fixtures may
    not carry migration 148 / 167 columns).
    """
    parts: list[str] = ["1=1"]
    params: list[Any] = []
    applied: list[str] = []

    parts.append("tier IN ('S','A','B','C')")
    applied.append("tier_in_SABC")

    if _column_exists(conn, "programs", "audit_quarantined"):
        parts.append("COALESCE(audit_quarantined, 0) = 0")
        applied.append("audit_quarantined=0")

    parts.append("COALESCE(excluded, 0) = 0")
    applied.append("excluded=0")

    has_majors = _column_exists(conn, "programs", "jsic_majors")
    has_major = _column_exists(conn, "programs", "jsic_major")
    if has_majors and has_major:
        parts.append("(jsic_majors LIKE ? OR jsic_major = ?)")
        params.extend([f'%"{jsic_major}"%', jsic_major])
        applied.append("jsic_major")
    elif has_majors:
        parts.append("jsic_majors LIKE ?")
        params.append(f'%"{jsic_major}"%')
        applied.append("jsic_majors")
    elif has_major:
        parts.append("jsic_major = ?")
        params.append(jsic_major)
        applied.append("jsic_major")

    parts.append("(prefecture = ? OR prefecture = '全国' OR prefecture IS NULL)")
    params.append(pref_name)
    applied.append("prefecture_or_national")

    if keyword:
        parts.append("primary_name LIKE ?")
        params.append(f"%{keyword}%")
        applied.append("keyword_like")

    return " AND ".join(parts), params, applied


def _select_match_columns(conn: sqlite3.Connection) -> str:
    """Return the SELECT column list, COALESCE-ing optional new columns
    so a fixture DB without migration 148/167 still answers cleanly.
    """
    cols = [
        "unified_id",
        "primary_name",
        "tier",
        "prefecture",
        "authority_name",
        "program_kind",
        "amount_max_man_yen",
        "amount_min_man_yen",
        "subsidy_rate",
    ]
    if _column_exists(conn, "programs", "source_url"):
        cols.append("source_url")
    else:
        cols.append("NULL AS source_url")
    if _column_exists(conn, "programs", "official_url"):
        cols.append("official_url")
    else:
        cols.append("NULL AS official_url")
    if _column_exists(conn, "programs", "verification_count"):
        cols.append("COALESCE(verification_count, 0) AS verification_count")
    else:
        cols.append("0 AS verification_count")
    if _column_exists(conn, "programs", "jsic_majors"):
        cols.append("jsic_majors")
    else:
        cols.append("NULL AS jsic_majors")
    if _column_exists(conn, "programs", "jsic_major"):
        cols.append("jsic_major")
    else:
        cols.append("NULL AS jsic_major")
    if _column_exists(conn, "programs", "application_window_json"):
        cols.append("application_window_json")
    else:
        cols.append("NULL AS application_window_json")
    if _column_exists(conn, "programs", "target_types_json"):
        cols.append("target_types_json")
    else:
        cols.append("NULL AS target_types_json")
    if _column_exists(conn, "programs", "funding_purpose_json"):
        cols.append("funding_purpose_json")
    else:
        cols.append("NULL AS funding_purpose_json")
    return ", ".join(cols)


def _density_lookup(conn: sqlite3.Connection, pref_code: str) -> dict[str, int]:
    """Return ``{tier: program_count}`` for the prefecture from
    ``pc_program_geographic_density``. Empty dict on missing table.
    """
    if not _table_exists(conn, "pc_program_geographic_density"):
        return {}
    code = f"JP-{pref_code}"
    try:
        rows = conn.execute(
            "SELECT tier, program_count FROM pc_program_geographic_density "
            "WHERE prefecture_code = ?",
            (code,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, int] = {}
    for r in rows:
        try:
            out[str(r["tier"])] = int(r["program_count"])
        except (IndexError, KeyError, TypeError, ValueError):
            continue
    return out


def _capital_fit_bonus(capital_jpy: int | None, amount_max_man_yen: Any) -> float:
    """Soft bonus when the program's amount cap is roughly matched to the
    applicant's capital. Returns 0.0 when either side is missing.

    Heuristic: reward programs whose amount cap is between 1% and 100% of
    the applicant's capital — the "right-sized" zone where the program
    materially affects cash flow without being so large that the applicant
    cannot absorb the obligation.
    """
    if capital_jpy is None or amount_max_man_yen is None:
        return 0.0
    try:
        cap_yen = float(amount_max_man_yen) * 10_000.0
    except (TypeError, ValueError):
        return 0.0
    if cap_yen <= 0 or capital_jpy <= 0:
        return 0.0
    ratio = cap_yen / float(capital_jpy)
    if 0.01 <= ratio <= 1.0:
        return 0.3
    if ratio < 0.01:
        return 0.05
    return 0.1  # cap > capital — still relevant, just oversized.


def _vec_similarity_signal(
    am_conn: sqlite3.Connection | None,
    *,
    unified_id: str,
    keyword: str | None,
) -> float | None:
    """Best-effort sqlite-vec presence signal.

    We have no live embedding model in the request path
    (memory `feedback_no_operator_llm_api`), so we cannot compute a true
    similarity. The honest signal we CAN give is "this UNI exists in the
    autonomath dense index" — a small uniform bonus keeps the dense term
    in the formula while making it clear no model was invoked.
    """
    if am_conn is None or not unified_id or not keyword:
        return None
    if not _table_exists(am_conn, "am_entities_vec_S"):
        return None
    try:
        row = am_conn.execute(
            "SELECT 1 FROM entity_id_map WHERE jpi_unified_id = ? LIMIT 1",
            (unified_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return 0.05 if row else None


def _compute_match_score(
    *,
    tier: str | None,
    verification_count: int,
    density: int,
    keyword: str | None,
    primary_name: str,
    capital_bonus: float,
    vec_similarity: float | None,
) -> float:
    """Composite ranking score. Deterministic, higher is better."""
    from math import log10

    score = _TIER_WEIGHT.get((tier or "").upper(), 0.5)
    score += min(int(verification_count or 0), 5) * 0.1
    if density > 0:
        score += min(0.4, max(0.0, log10(max(1, density)) * 0.2))
    if keyword and keyword.lower() in (primary_name or "").lower():
        score += 0.6
    score += capital_bonus
    if vec_similarity is not None:
        score += vec_similarity
    return round(score, 4)


def _normalize_match_score(score: float, max_score: float) -> float:
    """Project the raw composite score onto ``[0, 1]`` using ``max_score``."""
    if max_score <= 0:
        return 0.0
    return round(min(1.0, max(0.0, score / max_score)), 4)


def _eligibility_predicate(row: dict[str, Any]) -> dict[str, Any]:
    """Pull a structured eligibility predicate from the program row."""

    def _try_json(value: Any) -> Any:
        if not value:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    jsic_majors = _try_json(row.get("jsic_majors")) or []
    if not jsic_majors and row.get("jsic_major"):
        jsic_majors = [row.get("jsic_major")]

    return {
        "target_types": _try_json(row.get("target_types_json")) or [],
        "funding_purpose": _try_json(row.get("funding_purpose_json")) or [],
        "application_window": _try_json(row.get("application_window_json")) or {},
        "prefecture": row.get("prefecture"),
        "industry_jsic_majors": jsic_majors,
        "amount_max_man_yen": row.get("amount_max_man_yen"),
        "amount_min_man_yen": row.get("amount_min_man_yen"),
        "subsidy_rate": row.get("subsidy_rate"),
    }


def _required_documents_for(
    conn: sqlite3.Connection, *, primary_name: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Top-N required documents from ``program_documents`` keyed by name."""
    if not _table_exists(conn, "program_documents"):
        return []
    signature_col = (
        "signature_required"
        if _column_exists(conn, "program_documents", "signature_required")
        else "NULL AS signature_required"
    )
    try:
        rows = conn.execute(
            "SELECT form_name, form_type, form_format, form_url_direct, "
            f"       {signature_col} "
            "FROM program_documents "
            "WHERE program_name = ? "
            "ORDER BY CASE COALESCE(form_type,'') "
            "  WHEN 'required' THEN 0 WHEN 'optional' THEN 1 ELSE 2 END, "
            "  id ASC LIMIT ?",
            (primary_name, int(limit)),
        ).fetchall()
    except sqlite3.Error:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "form_name": r["form_name"],
                "form_type": r["form_type"],
                "form_format": r["form_format"],
                "form_url": r["form_url_direct"],
                "signature_required": (
                    bool(r["signature_required"]) if r["signature_required"] is not None else None
                ),
            }
        )
    return out


def _meaningful_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [v for v in value if v not in (None, "", [], {})]


def _question(
    *,
    qid: str,
    field: str,
    question: str,
    reason: str,
    kind: str,
    impact: str = "semi_blocking",
) -> dict[str, Any]:
    return {
        "id": qid,
        "field": field,
        "question": question,
        "reason": reason,
        "kind": kind,
        "impact": impact,
        "blocking": impact == "blocking",
    }


def _gap(
    *,
    field: str,
    reason: str,
    required_by: str,
    gap_type: str = "missing_payload",
    impact: str = "semi_blocking",
    expected: Any = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "field": field,
        "gap_type": gap_type,
        "reason": reason,
        "required_by": required_by,
        "impact": impact,
        "blocking": impact == "blocking",
    }
    if expected is not None:
        out["expected"] = expected
    return out


def _is_required_document(doc: dict[str, Any]) -> bool:
    form_type = str(doc.get("form_type") or "").strip().lower()
    return form_type not in {"optional", "任意"}


def _document_readiness(
    required_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    required_docs = [d for d in required_documents if _is_required_document(d)]
    signature_values = [d.get("signature_required") for d in required_docs]
    return {
        "required_document_count": len(required_docs),
        "forms_with_url_count": sum(
            1 for d in required_docs if str(d.get("form_url") or "").strip()
        ),
        "signature_required_count": sum(1 for v in signature_values if v is True),
        "signature_unknown_count": sum(1 for v in signature_values if v is None),
        "needs_user_confirmation": bool(required_docs),
    }


def _document_questions(
    required_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for idx, doc in enumerate(required_documents):
        if not _is_required_document(doc):
            continue
        form_name = str(doc.get("form_name") or "必要書類").strip()
        questions.append(
            _question(
                qid=f"document_{idx + 1}_confirmation",
                field=f"required_documents[{idx}].user_confirmation",
                question=(f"「{form_name}」の取得状況、発行日、署名・押印要否を確認してください。"),
                reason="required_documents に含まれるため申請準備状況の確認が必要です。",
                kind="document_readiness",
            )
        )
    return questions


def _eligibility_gaps_for(
    *,
    payload: IntelMatchRequest,
    predicate: dict[str, Any],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if payload.employee_count is None:
        gaps.append(
            _gap(
                field="employee_count",
                reason="従業員数により中小企業者要件や規模要件の確認が必要です。",
                required_by="sme_size",
            )
        )
    if payload.capital_jpy is None:
        gaps.append(
            _gap(
                field="capital_jpy",
                reason="資本金により中小企業者要件と補助上限との規模適合を確認します。",
                required_by="capital_or_amount_fit",
            )
        )

    target_types = _meaningful_list(predicate.get("target_types"))
    if target_types:
        gaps.append(
            _gap(
                field="entity_type",
                reason="対象者種別が制度条件に含まれるため、申請主体の種別確認が必要です。",
                required_by="eligibility_predicate.target_types",
                expected=target_types,
            )
        )

    funding_purpose = _meaningful_list(predicate.get("funding_purpose"))
    if funding_purpose:
        gaps.append(
            _gap(
                field="funding_purpose",
                reason="対象経費・投資目的が制度条件に含まれるため、今回の用途確認が必要です。",
                required_by="eligibility_predicate.funding_purpose",
                expected=funding_purpose,
            )
        )

    if predicate.get("prefecture") and not payload.prefecture_code:
        gaps.append(
            _gap(
                field="prefecture_code",
                reason="地域要件が制度条件に含まれるため所在地確認が必要です。",
                required_by="eligibility_predicate.prefecture",
                expected=predicate.get("prefecture"),
            )
        )

    jsic_majors = _meaningful_list(predicate.get("industry_jsic_majors"))
    if jsic_majors and not payload.industry_jsic_major:
        gaps.append(
            _gap(
                field="industry_jsic_major",
                reason="業種要件が制度条件に含まれるため JSIC 大分類の確認が必要です。",
                required_by="eligibility_predicate.industry_jsic_majors",
                expected=jsic_majors,
            )
        )
    return gaps


def _next_questions_for(
    *,
    payload: IntelMatchRequest,
    predicate: dict[str, Any],
    eligibility_gaps: list[dict[str, Any]],
    required_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    gap_fields = {str(g.get("field") or "") for g in eligibility_gaps}

    if "employee_count" in gap_fields:
        questions.append(
            _question(
                qid="employee_count",
                field="employee_count",
                question="常時使用する従業員数は何名ですか。",
                reason="従業員数により中小企業者要件や規模要件の確認が必要です。",
                kind="eligibility_input",
            )
        )
    if "capital_jpy" in gap_fields:
        questions.append(
            _question(
                qid="capital_jpy",
                field="capital_jpy",
                question="資本金はいくらですか（円）。",
                reason="資本金により中小企業者要件と補助上限との規模適合を確認します。",
                kind="eligibility_input",
            )
        )
    if "entity_type" in gap_fields:
        questions.append(
            _question(
                qid="entity_type",
                field="entity_type",
                question="申請主体の種別は何ですか（法人、個人事業主、NPO 等）。",
                reason="対象者種別が制度条件に含まれるため確認が必要です。",
                kind="eligibility_input",
            )
        )
    if "funding_purpose" in gap_fields:
        expected = _meaningful_list(predicate.get("funding_purpose"))
        suffix = f"候補: {', '.join(map(str, expected))}。" if expected else ""
        questions.append(
            _question(
                qid="funding_purpose",
                field="funding_purpose",
                question=f"今回の投資目的・対象経費は何ですか。{suffix}",
                reason="制度の対象経費・目的との適合確認が必要です。",
                kind="eligibility_input",
            )
        )
    if "prefecture_code" in gap_fields:
        questions.append(
            _question(
                qid="prefecture_code",
                field="prefecture_code",
                question="申請主体の所在地都道府県はどこですか。",
                reason="地域要件が制度条件に含まれるため確認が必要です。",
                kind="eligibility_input",
            )
        )
    if "industry_jsic_major" in gap_fields:
        questions.append(
            _question(
                qid="industry_jsic_major",
                field="industry_jsic_major",
                question="主たる業種の JSIC 大分類は何ですか。",
                reason="業種要件が制度条件に含まれるため確認が必要です。",
                kind="eligibility_input",
            )
        )

    questions.extend(_document_questions(required_documents))
    return questions


def _similar_adopted_companies(
    conn: sqlite3.Connection,
    *,
    pref_name: str,
    jsic_major: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Top-N adopted companies in the same prefecture × industry slice."""
    if not _table_exists(conn, "adoption_records"):
        return []
    has_houjin_master = _table_exists(conn, "houjin_master")
    sql = (
        "SELECT ar.houjin_bangou, "
        "       "
        + (
            "COALESCE(hm.normalized_name, ar.company_name_raw)"
            if has_houjin_master
            else "ar.company_name_raw"
        )
        + " AS trade_name, "
        "       substr(COALESCE(ar.announced_at,''),1,4) AS year, "
        "       ar.amount_granted_yen AS amount "
        "FROM adoption_records ar "
        + (
            "LEFT JOIN houjin_master hm ON hm.houjin_bangou = ar.houjin_bangou "
            if has_houjin_master
            else ""
        )
        + "WHERE ar.prefecture = ? "
        "  AND ar.industry_jsic_medium IS NOT NULL "
        "  AND substr(ar.industry_jsic_medium,1,1) = ? "
        "ORDER BY ar.announced_at DESC "
        "LIMIT ?"
    )
    try:
        rows = conn.execute(sql, (pref_name, jsic_major, int(limit))).fetchall()
    except sqlite3.Error:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "houjin_bangou": r["houjin_bangou"],
                "trade_name": r["trade_name"],
                "year": r["year"] or None,
                "amount": int(r["amount"]) if r["amount"] is not None else None,
            }
        )
    return out


def _applicable_laws(
    conn: sqlite3.Connection, *, unified_id: str, limit: int = 2
) -> list[dict[str, Any]]:
    """Top-N laws referenced by this program via ``program_law_refs``."""
    if not _table_exists(conn, "program_law_refs"):
        return []
    if not _table_exists(conn, "laws"):
        return []
    try:
        rows = conn.execute(
            "SELECT plr.law_unified_id AS law_id, "
            "       plr.article_citation AS article_no, "
            "       l.law_title AS title "
            "FROM program_law_refs plr "
            "JOIN laws l ON l.unified_id = plr.law_unified_id "
            "WHERE plr.program_unified_id = ? "
            "ORDER BY (plr.ref_kind = 'authority') DESC, plr.confidence DESC "
            "LIMIT ?",
            (unified_id, int(limit)),
        ).fetchall()
    except sqlite3.Error:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "law_id": r["law_id"],
                "article_no": r["article_no"] or None,
                "title": r["title"],
            }
        )
    return out


def _applicable_tsutatsu(
    conn: sqlite3.Connection, *, primary_name: str, limit: int = 2
) -> list[dict[str, Any]]:
    """Top-N tax_rulesets (通達) whose ruleset_name overlaps the program name."""
    if not _table_exists(conn, "tax_rulesets"):
        return []
    tokens = [t for t in re.findall(r"[一-龯]{2,}", primary_name) if len(t) >= 2]
    if not tokens:
        return []
    likes: list[str] = []
    params: list[Any] = []
    for t in tokens[:6]:
        likes.append("ruleset_name LIKE ?")
        params.append(f"%{t}%")
    sql = (
        "SELECT unified_id, ruleset_name, tax_category, ruleset_kind, "
        "       authority, source_url "
        "FROM tax_rulesets "
        "WHERE (" + " OR ".join(likes) + ") "
        "ORDER BY confidence DESC LIMIT ?"
    )
    params.append(int(limit))
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "ruleset_id": r["unified_id"],
                "ruleset_name": r["ruleset_name"],
                "tax_category": r["tax_category"],
                "ruleset_kind": r["ruleset_kind"],
                "authority": r["authority"],
                "source_url": r["source_url"],
            }
        )
    return out


def _audit_proof_for(unified_id: str) -> dict[str, Any]:
    """Return an audit_proof envelope for the program (best-effort)."""
    out: dict[str, Any] = {"merkle_root": None, "ots_url": None}
    if not unified_id:
        return out
    try:
        am_conn: sqlite3.Connection | None = _open_autonomath_rw()
    except Exception:
        return out
    if am_conn is None:
        return out
    try:
        leaf = _fetch_leaf(am_conn, unified_id)
        if not leaf:
            return out
        anchor = _fetch_anchor(am_conn, str(leaf[0]))
        if not anchor:
            return out
        out["merkle_root"] = anchor.get("merkle_root")
        out["ots_url"] = _ots_url_for(anchor.get("ots_proof"))
    except sqlite3.Error:
        return out
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()
    return out


def _open_intel_match_autonomath_ro() -> sqlite3.Connection | None:
    """Open autonomath.db read-only for vec lookups (best-effort)."""
    try:
        from jpintel_mcp.config import settings

        p = settings.autonomath_db_path
        if not p.exists() or p.stat().st_size == 0:
            return None
        uri = f"file:{p}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
        return conn
    except (sqlite3.Error, AttributeError, OSError):
        return None


def _build_match_envelope(
    conn: sqlite3.Connection,
    *,
    payload: IntelMatchRequest,
    pref_name: str,
) -> dict[str, Any]:
    """Build the matched_programs envelope. Pure SQLite, NO LLM."""
    where_sql, where_params, applied_filters = _build_match_where(
        conn,
        jsic_major=payload.industry_jsic_major,
        pref_name=pref_name,
        keyword=payload.keyword,
    )
    cols_sql = _select_match_columns(conn)

    # Pull a generous candidate pool (5x limit) so the python-side ranker
    # has room to re-order; SQLite's row order on `tier IN ()` is not stable.
    fetch_n = max(payload.limit * 5, 25)
    sql = (
        f"SELECT {cols_sql} FROM programs "
        f"WHERE {where_sql} "
        "ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 "
        "                    WHEN 'B' THEN 2 ELSE 3 END, "
        "  COALESCE(verification_count,0) DESC, "
        "  unified_id ASC "
        "LIMIT ?"
    )
    final_params = list(where_params) + [fetch_n]
    try:
        rows = conn.execute(sql, final_params).fetchall()
    except sqlite3.OperationalError as exc:
        # Defensive: if the fixture DB is missing a column referenced in
        # the secondary ORDER BY (e.g. `verification_count` on a very old
        # schema), drop that ORDER BY clause and retry.
        logger.warning("intel.match retry without verification_count: %s", exc)
        sql_retry = (
            f"SELECT {cols_sql} FROM programs WHERE {where_sql} "
            "ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 "
            "                    WHEN 'B' THEN 2 ELSE 3 END, "
            "  unified_id ASC LIMIT ?"
        )
        rows = conn.execute(sql_retry, final_params).fetchall()

    if not rows:
        return {
            "matched_programs": [],
            "total_candidates": 0,
            "applied_filters": applied_filters,
            "_disclaimer": _MATCH_DISCLAIMER,
            "_billing_unit": 1,
        }

    density_by_tier = _density_lookup(conn, payload.prefecture_code)
    am_conn = _open_intel_match_autonomath_ro()
    try:
        scored: list[tuple[float, dict[str, Any]]] = []
        for r in rows:
            row_dict = dict(r)
            tier = row_dict.get("tier")
            density = density_by_tier.get(str(tier or ""), 0)
            capital_bonus = _capital_fit_bonus(
                payload.capital_jpy, row_dict.get("amount_max_man_yen")
            )
            vec_sim = _vec_similarity_signal(
                am_conn,
                unified_id=row_dict.get("unified_id") or "",
                keyword=payload.keyword,
            )
            score = _compute_match_score(
                tier=tier,
                verification_count=int(row_dict.get("verification_count") or 0),
                density=density,
                keyword=payload.keyword,
                primary_name=row_dict.get("primary_name") or "",
                capital_bonus=capital_bonus,
                vec_similarity=vec_sim,
            )
            scored.append((score, row_dict))
        scored.sort(key=lambda x: (-x[0], x[1].get("unified_id") or ""))
        top = scored[: payload.limit]
        max_raw = max((s for s, _ in top), default=1.0) or 1.0

        matched: list[dict[str, Any]] = []
        for raw_score, row_dict in top:
            uid = row_dict.get("unified_id") or ""
            primary = row_dict.get("primary_name") or ""
            predicate = _eligibility_predicate(row_dict)
            required_documents = _required_documents_for(conn, primary_name=primary, limit=5)
            eligibility_gaps = _eligibility_gaps_for(
                payload=payload,
                predicate=predicate,
            )
            matched.append(
                {
                    "program_id": uid,
                    "primary_name": primary,
                    "tier": row_dict.get("tier"),
                    "match_score": _normalize_match_score(raw_score, max_raw),
                    "score_components": {
                        "tier_weight": _TIER_WEIGHT.get((row_dict.get("tier") or "").upper(), 0.5),
                        "verification_count": int(row_dict.get("verification_count") or 0),
                        "density_score": density_by_tier.get(str(row_dict.get("tier") or ""), 0),
                        "raw_score": raw_score,
                    },
                    "authority_name": row_dict.get("authority_name"),
                    "prefecture": row_dict.get("prefecture"),
                    "program_kind": row_dict.get("program_kind"),
                    "source_url": row_dict.get("source_url") or row_dict.get("official_url"),
                    "eligibility_predicate": predicate,
                    "required_documents": required_documents,
                    "next_questions": _next_questions_for(
                        payload=payload,
                        predicate=predicate,
                        eligibility_gaps=eligibility_gaps,
                        required_documents=required_documents,
                    ),
                    "eligibility_gaps": eligibility_gaps,
                    "document_readiness": _document_readiness(required_documents),
                    "similar_adopted_companies": _similar_adopted_companies(
                        conn,
                        pref_name=pref_name,
                        jsic_major=payload.industry_jsic_major,
                        limit=3,
                    ),
                    "applicable_laws": _applicable_laws(conn, unified_id=uid, limit=2),
                    "applicable_tsutatsu": _applicable_tsutatsu(
                        conn, primary_name=primary, limit=2
                    ),
                    "audit_proof": _audit_proof_for(uid),
                }
            )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    return {
        "matched_programs": matched,
        "total_candidates": len(rows),
        "applied_filters": applied_filters,
        "_disclaimer": _MATCH_DISCLAIMER,
        "_billing_unit": 1,
    }


@router.post(
    "/match",
    response_model=IntelMatchResponse,
    summary="Smart matchmaking — top-N programs in 1 call (NO LLM)",
    description=(
        "Single-call matchmaking: customer LLM passes "
        "`{industry_jsic_major, prefecture_code, capital_jpy, "
        "employee_count, keyword, limit}` and receives the top-N programs "
        "pre-joined to required_documents, similar_adopted_companies, "
        "applicable_laws, applicable_tsutatsu, and an audit_proof block.\n\n"
        "**Pricing:** ¥3 / call (1 unit total) regardless of `limit`.\n\n"
        "**Ranking:** tier weight + verification_count + density + keyword + "
        "capital fit + (optional) sqlite-vec similarity. Deterministic, no LLM."
    ),
)
def post_intel_match(
    payload: Annotated[IntelMatchRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    _t0 = time.perf_counter()

    major = payload.industry_jsic_major.strip().upper()
    if major not in _JSIC_MAJOR_CODES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_jsic_major",
                "field": "industry_jsic_major",
                "message": (f"industry_jsic_major must be one of A–T (got {major!r})."),
            },
        )
    pref_code = payload.prefecture_code.strip()
    pref_name = _PREFECTURE_CODE_TO_NAME.get(pref_code)
    if not pref_name:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_prefecture_code",
                "field": "prefecture_code",
                "message": (
                    f"prefecture_code must be a JIS X 0401 two-digit code "
                    f"01–47 (got {pref_code!r})."
                ),
            },
        )

    # Re-bind validated values back onto the payload so downstream helpers
    # see the canonical form.
    payload = payload.model_copy(
        update={"industry_jsic_major": major, "prefecture_code": pref_code}
    )

    body = _build_match_envelope(conn, payload=payload, pref_name=pref_name)
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.match",
        latency_ms=latency_ms,
        result_count=len(body.get("matched_programs") or []),
        params={
            "industry_jsic_major": major,
            "prefecture_code": pref_code,
            "has_keyword": bool(payload.keyword),
            "limit": payload.limit,
            "capital_jpy_present": payload.capital_jpy is not None,
            "employee_count_present": payload.employee_count is not None,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.match",
        request_params={
            "industry_jsic_major": major,
            "prefecture_code": pref_code,
            "capital_jpy": payload.capital_jpy,
            "employee_count": payload.employee_count,
            "keyword": payload.keyword,
            "limit": payload.limit,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body)


__all__ = ["router"]
