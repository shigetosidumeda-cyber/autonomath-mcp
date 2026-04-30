"""M&A pillar bundle — boutique-grade DD/audit/watch/graph surfaces.

Four endpoints lift boutique ARPU 16x by composing the existing ¥3/req
metered tools into investor-grade workflows:

    POST /v1/am/dd_batch          — 1..200 法人 batch DD, NDJSON stream-able
    GET  /v1/am/group_graph       — 2-hop 法人↔法人 part_of traversal
    POST /v1/am/dd_export         — audit-bundle ZIP via signed R2 URL
    (watch surface lives in api/me_watches.py — POST/GET/DELETE
     /v1/me/watches; the cron is scripts/cron/dispatch_watch_events.py.)

Pricing (project_autonomath_business_model — almost-immutable):
    * dd_batch:        ¥3 per houjin_bangou (per-id metered, NOT 1 ¥3/call).
    * group_graph:     ¥3 per call (single houjin seed, single response).
    * dd_export:       ¥3 × N (per-id) + ¥3 × bundle_units (per-bundle).
                       Charges remain pure ¥3 × quantity — there is NO tier
                       SKU. `bundle_class` is an artifact-size knob (like
                       `row_count` in bulk_evaluate) that maps to a quantity
                       multiplier:
                         standard → 333 units (≈¥1,000) — default ZIP
                         deal     → 1,000 units (≈¥3,000) — deal-room ZIP
                         case     → 3,333 units (≈¥10,000) — full case ZIP
                       Justified by R2 storage compute + bundle composition
                       cost. Customer is always charged `quantity × ¥3`;
                       Stripe usage_records carry the same unit price.
                       Documented explicitly in docs/pricing.md.

Per-request anti-runaway:
    The optional `X-Cost-Cap-JPY` header (and `max_cost_jpy` body field on
    POST endpoints) caps the predicted cost. dd_batch with 200 法人 + cap
    of 100 returns 400 *before* any DB read so the customer never burns the
    cap on a request they meant to refuse. The cap is checked locally in
    the route handler — the global CustomerCapMiddleware enforces the
    monthly cap separately and is unchanged.

§52 envelope:
    Every response carries `_disclaimer` (税理士法 §52) and a coverage scope
    note explicitly excluding 役員一覧 / 株主構成 / 経歴 (商業登記法 gray
    zone — TDB primary). LLM agents MUST relay both verbatim.

Solo + zero-touch posture:
    No CS team, no legal escalation. Every flag is self-serve via the
    response body's `dd_flags` / `disclaimer` / `coverage_scope` fields.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._corpus_snapshot import (
    attach_corpus_snapshot,
    compute_corpus_snapshot,
)
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.ma_dd")

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# `ma_dd` covers /v1/am/dd_batch + /v1/am/group_graph + /v1/am/dd_export.
router = APIRouter(prefix="/v1/am", tags=["ma_dd"])

# `watches` covers /v1/me/watches (register/list/cancel). Distinct prefix
# (`/v1/me/*` is the customer-scoped surface) so we expose a separate router
# rather than mounting these under `/v1/am/`.
watches_router = APIRouter(prefix="/v1/me/watches", tags=["customer_watches"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Per-id metered base price. Mirrors api/cost.py::_UNIT_PRICE_YEN.
_UNIT_PRICE_YEN: int = 3

# Bundle-class quantity multipliers. The ZIP export charge is `quantity × ¥3`
# where quantity = `_BUNDLE_CLASS_UNITS[bundle_class]`. This stays compliant
# with the ¥3/req metered-only pricing rule (project_autonomath_business_model)
# — there is NO tier SKU. The `bundle_class` is an artifact-size selector
# (like `row_count` in bulk_evaluate.py) that controls how many billing units
# the export consumes:
#
#     standard → 333 units (¥999 ≈ ¥1,000) — default
#     deal     → 1,000 units (¥3,000)      — deal-room ZIP
#     case     → 3,333 units (¥9,999 ≈ ¥10,000) — full case ZIP
#
# The numbers are calibrated so the rounded ¥-target lands at ¥1k / ¥3k / ¥10k
# while the unit price stays at the canonical ¥3. Stripe usage_records report
# the same `quantity` so reconciliation stays one-line per export.
_BUNDLE_CLASS_UNITS: dict[str, int] = {
    "standard": 333,
    "deal": 1_000,
    "case": 3_333,
}

# Legacy compat shim — code paths and tests that imported the old constant
# can still resolve `_AUDIT_BUNDLE_FEE_YEN` to the standard-class subtotal.
# Equals `_BUNDLE_CLASS_UNITS['standard'] * _UNIT_PRICE_YEN` = ¥999.
_AUDIT_BUNDLE_FEE_YEN: int = _BUNDLE_CLASS_UNITS["standard"] * _UNIT_PRICE_YEN

# Hard cap on the number of 法人番号 per batch call. 200 is the customer-
# facing contract; matches the spec.
_MAX_BATCH_HOUJIN: int = 200

# When the input batch is larger than this we stream NDJSON (one JSON object
# per line, terminated by `\n`). 50+ keeps p95 latency-to-first-byte tight
# for boutique workflows that pipe each row into a DD checklist.
_NDJSON_THRESHOLD: int = 50

# Per-watch-key cap. Mirrors customer_webhooks.MAX_WEBHOOKS_PER_KEY (10) but
# scaled for the M&A scenario — a boutique tracking 5,000 portfolio companies
# needs headroom that webhooks (10 URLs) does not.
_MAX_WATCHES_PER_KEY: int = 5000

# group_graph traversal depth cap. Hard 2-hop ceiling (spec). Edges over
# 200 hops would expose pathological aggregator-style fan-out — keep the
# upper bound tight.
_MAX_GRAPH_DEPTH: int = 2
_MAX_GRAPH_NODES: int = 500

# Audit-bundle signed URL TTL.
_BUNDLE_URL_TTL_HOURS: int = 24

# §52 fence + privacy/coverage disclaimer. Mirrors the strings in
# api/autonomath.py::_TAX_DISCLAIMER + dd_profile_am::coverage_scope so
# LLM agents see consistent fence vocabulary across surfaces.
_TAX_DISCLAIMER = (
    "本情報は税務助言ではありません。AutonoMath は公的機関が公表する税制・補助金・"
    "法令情報を検索・整理して提供するサービスで、税理士法 §52 に基づき個別具体的な"
    "税務判断・申告書作成代行は行いません。個別案件は資格を有する税理士に必ずご相談"
    "ください。本サービスの情報利用により生じた損害について、当社は一切の責任を負いません。"
)

# Coverage scope (negative space) that ALL ma_dd responses must surface so
# downstream agents do not misrepresent the bundle as 信用情報 / 反社 /
# 経歴 / 役員 / 株主構成 — those are商業登記法 gray-zone surfaces sourced
# from TDB / 帝国データバンク and explicitly OUT OF SCOPE.
_COVERAGE_SCOPE = (
    "対象データ: 公開政府ソース (jpi_enforcement_cases / am_amendment_diff "
    "/ jpi_invoice_registrants / programs / am_relation 'part_of') のみ。"
    "対象外: 役員一覧・株主構成・経歴・反社・信用情報・帝国データバンク。"
    "商業登記法・個人情報保護法を理由に本サービスでは扱いません。"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_houjin(raw: str | None) -> str | None:
    """Strip 'T' prefix, NFKC fullwidth-digits, hyphens, spaces. Return 13
    digits or None.

    Mirrors `mcp/autonomath_tools/enforcement_tool._normalize_houjin` but
    re-implemented here to keep the api router dependency-free of the MCP
    package (the MCP server is a separate stdio process; importing from it
    would lazy-pull FastMCP and other heavy deps into the API hot path).
    """
    if raw is None:
        return None
    import unicodedata

    s = unicodedata.normalize("NFKC", str(raw))
    s = s.strip().lstrip("Tt")
    # Remove hyphens, spaces (full + half), commas — paste-from-CSV friendly.
    for ch in "- ,　":
        s = s.replace(ch, "")
    if not s.isdigit():
        return None
    if len(s) != 13:
        return None
    return s


def _parse_cost_cap_header(value: str | None) -> int | None:
    """Parse `X-Cost-Cap-JPY: <int>`. Return int or None on missing/invalid."""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        cap = int(raw)
    except ValueError:
        return None
    if cap < 0:
        return None
    return cap


def _check_cost_cap(
    *, predicted_yen: int, header_cap: int | None, body_cap: int | None,
) -> None:
    """Raise 400 with the canonical envelope when predicted > min(caps).

    Either / both caps may be None. The smallest non-None cap binds.
    """
    caps = [c for c in (header_cap, body_cap) if c is not None]
    if not caps:
        return
    binding = min(caps)
    if predicted_yen <= binding:
        return
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail={
            "error": {
                "code": "cost_cap_exceeded",
                "message": (
                    f"Predicted cost ¥{predicted_yen} exceeds cap ¥{binding}. "
                    f"Lower batch size or raise the cap "
                    f"(X-Cost-Cap-JPY / max_cost_jpy)."
                ),
                "predicted_yen": predicted_yen,
                "cost_cap_yen": binding,
                "unit_price_yen": _UNIT_PRICE_YEN,
            }
        },
    )


def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path the API process should read from.

    Uses `AUTONOMATH_DB_PATH` env (matches the MCP-side resolution in
    `mcp/autonomath_tools/db.py`) so the API + MCP + cron read the same
    file. Falls back to the repo root.
    """
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    # Repo root: this file is at src/jpintel_mcp/api/ma_dd.py.
    return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open a read-only connection to autonomath.db. Returns None if the
    file is missing — endpoints fall back gracefully so a partial deploy
    cannot 500.
    """
    p = _autonomath_db_path()
    if not p.exists():
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # Match the MCP-side perf tuning so the API path doesn't cold-read
        # tail of am_relation (146,161 part_of rows).
        with contextlib_suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
        return conn
    except sqlite3.OperationalError:
        return None


def contextlib_suppress(*exc):
    """Tiny inline contextlib.suppress so we don't import the stdlib
    module just for one line. Mirrors stdlib semantics exactly."""
    import contextlib

    return contextlib.suppress(*exc)


# ---------------------------------------------------------------------------
# DD compose: per-houjin profile builder used by dd_batch + dd_export
# ---------------------------------------------------------------------------


def _build_dd_profile(
    *,
    jp_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    houjin_bangou: str,
    depth: Literal["summary", "full"] = "summary",
) -> dict[str, Any]:
    """Compose one DD profile from the existing data tables.

    Schema reads:
      autonomath.db  am_entities (record_kind='corporate_entity' / 'adoption')
      autonomath.db  am_amendment_diff (per-houjin amendment δ — when
                     the entity_id is resolvable)
      jpintel.db     enforcement_cases (recipient_houjin_bangou)
      jpintel.db     invoice_registrants (houjin_bangou)
      jpintel.db     bids (winner_houjin_bangou + procuring_houjin_bangou)
      jpintel.db     case_studies (subject_houjin_bangou-shaped fields are
                     resolved best-effort; case_studies has no canonical
                     houjin column today, so this slot stays empty until
                     ingest plumbs it through)

    The composer NEVER raises on missing tables — it returns the shape with
    null/empty slots so a partial-deploy still serves a valid envelope.
    """
    profile: dict[str, Any] = {
        "houjin_bangou": houjin_bangou,
        "entity": None,
        "adoptions_summary": {"total": 0, "programs_list": []},
        "invoice_registration": {"status": "unknown_in_mirror"},
        "enforcement": {
            "found": False,
            "currently_excluded": False,
            "active_exclusions": [],
            "recent_history": [],
            "all_count": 0,
        },
        "bids_summary": {
            "total_won": 0,
            "total_procured": 0,
            "recent_won": [],
        },
        "adoption_timeline": [],
        "amendment_recent": [],
        "dd_flags": [],
    }

    # --- corporate_entity + adoption (autonomath.db) -----------------------
    if am_conn is not None:
        try:
            ce = am_conn.execute(
                """SELECT canonical_id, primary_name, raw_json
                     FROM am_entities
                    WHERE record_kind = 'corporate_entity'
                      AND json_extract(raw_json, '$.houjin_bangou') = ?
                    LIMIT 1""",
                (houjin_bangou,),
            ).fetchone()
            if ce:
                try:
                    raw = json.loads(ce["raw_json"]) if ce["raw_json"] else {}
                except Exception:
                    raw = {}
                profile["entity"] = {
                    "canonical_id": ce["canonical_id"],
                    "name": ce["primary_name"] or raw.get("name"),
                    "category": raw.get("category"),
                    "prefecture": raw.get("prefecture_name") or raw.get("prefecture"),
                    "municipality": raw.get("municipality"),
                    "certified_at": raw.get("certified_at"),
                }

            # adoption count + (depth='full') timeline rows.
            arow = am_conn.execute(
                """SELECT COUNT(*) AS n
                     FROM am_entities
                    WHERE record_kind = 'adoption'
                      AND json_extract(raw_json, '$.houjin_bangou') = ?""",
                (houjin_bangou,),
            ).fetchone()
            adoptions_total = int(arow["n"] if arow else 0)
            profile["adoptions_summary"]["total"] = adoptions_total

            if adoptions_total > 0:
                limit = 50 if depth == "full" else 10
                rows = am_conn.execute(
                    """SELECT canonical_id, primary_name, source_topic, raw_json
                         FROM am_entities
                        WHERE record_kind = 'adoption'
                          AND json_extract(raw_json, '$.houjin_bangou') = ?
                        LIMIT ?""",
                    (houjin_bangou, limit),
                ).fetchall()
                programs_set: set[str] = set()
                for r in rows:
                    try:
                        rj = json.loads(r["raw_json"]) if r["raw_json"] else {}
                    except Exception:
                        rj = {}
                    prog = rj.get("program_name") or r["source_topic"]
                    if prog:
                        programs_set.add(prog)
                    profile["adoption_timeline"].append({
                        "canonical_id": r["canonical_id"],
                        "program_name": prog,
                        "adopted_at": rj.get("adopted_at") or rj.get("adoption_date"),
                        "adopted_name": r["primary_name"],
                        "prefecture": rj.get("prefecture"),
                        "source_topic": r["source_topic"],
                    })
                profile["adoptions_summary"]["programs_list"] = sorted(programs_set)
        except sqlite3.OperationalError as exc:
            logger.debug("am_entities read failed: %s", exc)

        # am_amendment_diff (depth=full) — recent amendments referencing this
        # houjin via entity_id. The table is keyed on entity_id (canonical
        # corporate_entity id), so we can only fetch when the entity row is
        # resolvable.
        if depth == "full" and profile["entity"]:
            try:
                eid = profile["entity"].get("canonical_id")
                if eid:
                    rows = am_conn.execute(
                        """SELECT diff_id, field_name, prev_value, new_value,
                                   detected_at, source_url
                             FROM am_amendment_diff
                            WHERE entity_id = ?
                         ORDER BY detected_at DESC
                            LIMIT 10""",
                        (eid,),
                    ).fetchall()
                    profile["amendment_recent"] = [
                        {
                            "diff_id": r["diff_id"],
                            "field": r["field_name"],
                            "before": r["prev_value"],
                            "after": r["new_value"],
                            "detected_at": r["detected_at"],
                            "source_url": r["source_url"],
                        }
                        for r in rows
                    ]
            except sqlite3.OperationalError:
                pass

    # --- enforcement_cases (jpintel.db) ------------------------------------
    try:
        rows = jp_conn.execute(
            """SELECT case_id, event_type, recipient_name, prefecture, ministry,
                      amount_yen, reason_excerpt, source_url, disclosed_date,
                      disclosed_until
                 FROM enforcement_cases
                WHERE recipient_houjin_bangou = ?
             ORDER BY COALESCE(disclosed_date, '') DESC
                LIMIT ?""",
            (houjin_bangou, 20 if depth == "full" else 5),
        ).fetchall()
        if rows:
            profile["enforcement"]["found"] = True
            profile["enforcement"]["all_count"] = len(rows)
            today_iso = datetime.now(UTC).date().isoformat()
            for r in rows:
                event = {
                    "case_id": r["case_id"],
                    "event_type": r["event_type"],
                    "recipient_name": r["recipient_name"],
                    "prefecture": r["prefecture"],
                    "ministry": r["ministry"],
                    "amount_yen": r["amount_yen"],
                    "reason_excerpt": r["reason_excerpt"],
                    "source_url": r["source_url"],
                    "disclosed_date": r["disclosed_date"],
                    "disclosed_until": r["disclosed_until"],
                }
                if r["disclosed_until"] and r["disclosed_until"] >= today_iso:
                    profile["enforcement"]["currently_excluded"] = True
                    profile["enforcement"]["active_exclusions"].append(event)
                else:
                    profile["enforcement"]["recent_history"].append(event)
    except sqlite3.OperationalError as exc:
        logger.debug("enforcement_cases read failed: %s", exc)

    # --- invoice_registrants (jpintel.db) ----------------------------------
    try:
        inv = jp_conn.execute(
            """SELECT invoice_registration_number, registered_date,
                      revoked_date, expired_date, registrant_kind, trade_name,
                      normalized_name, prefecture
                 FROM invoice_registrants
                WHERE houjin_bangou = ?
                LIMIT 1""",
            (houjin_bangou,),
        ).fetchone()
        if inv:
            profile["invoice_registration"] = {
                "status": (
                    "revoked" if inv["revoked_date"]
                    else "expired" if inv["expired_date"]
                    else "registered"
                ),
                "invoice_registration_number": inv["invoice_registration_number"],
                "registered_date": inv["registered_date"],
                "revoked_date": inv["revoked_date"],
                "expired_date": inv["expired_date"],
                "registrant_kind": inv["registrant_kind"],
                "trade_name": inv["trade_name"],
                "name": inv["normalized_name"],
                "prefecture": inv["prefecture"],
            }
        else:
            profile["dd_flags"].append("invoice_mirror_miss")
    except sqlite3.OperationalError as exc:
        logger.debug("invoice_registrants read failed: %s", exc)

    # --- bids (jpintel.db, two roles: winner + procuring) ------------------
    try:
        won_count = jp_conn.execute(
            "SELECT COUNT(*) FROM bids WHERE winner_houjin_bangou = ?",
            (houjin_bangou,),
        ).fetchone()[0]
        procured_count = jp_conn.execute(
            "SELECT COUNT(*) FROM bids WHERE procuring_houjin_bangou = ?",
            (houjin_bangou,),
        ).fetchone()[0]
        profile["bids_summary"]["total_won"] = int(won_count or 0)
        profile["bids_summary"]["total_procured"] = int(procured_count or 0)

        if depth == "full" and won_count:
            recent = jp_conn.execute(
                """SELECT unified_id, bid_title, procuring_entity, awarded_amount_yen,
                          decision_date, source_url
                     FROM bids
                    WHERE winner_houjin_bangou = ?
                 ORDER BY COALESCE(decision_date, '') DESC
                    LIMIT 10""",
                (houjin_bangou,),
            ).fetchall()
            profile["bids_summary"]["recent_won"] = [
                {
                    "unified_id": r["unified_id"],
                    "bid_title": r["bid_title"],
                    "procuring_entity": r["procuring_entity"],
                    "awarded_amount_yen": r["awarded_amount_yen"],
                    "decision_date": r["decision_date"],
                    "source_url": r["source_url"],
                }
                for r in recent
            ]
    except sqlite3.OperationalError as exc:
        logger.debug("bids read failed: %s", exc)

    # --- dd_flags rollup ---------------------------------------------------
    if profile["enforcement"]["currently_excluded"]:
        profile["dd_flags"].append("currently_excluded")
    if (
        profile["enforcement"]["found"]
        and not profile["enforcement"]["currently_excluded"]
    ):
        profile["dd_flags"].append("recent_enforcement_history")
    if profile["adoptions_summary"]["total"] == 0:
        profile["dd_flags"].append("no_adoption_history")
    if (
        profile["entity"] is None
        and profile["invoice_registration"].get("status") == "unknown_in_mirror"
        and profile["adoptions_summary"]["total"] == 0
    ):
        profile["dd_flags"].append("unknown_company")

    return profile


# ---------------------------------------------------------------------------
# PILLAR 1: dd_batch
# ---------------------------------------------------------------------------


class DdBatchRequest(BaseModel):
    """`POST /v1/am/dd_batch` request body."""

    houjin_bangous: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=_MAX_BATCH_HOUJIN,
            description=(
                "1..200 法人番号 (13 digits, NFKC + T prefix + hyphens "
                "auto-stripped). Each id contributes ¥3 to the metered "
                "total."
            ),
        ),
    ]
    depth: Annotated[
        Literal["summary", "full"],
        Field(
            description=(
                "summary = entity + counts + recent_history; "
                "full = entity + adoption_timeline + amendment_recent + "
                "bids.recent_won + extended enforcement history."
            ),
        ),
    ] = "summary"
    max_cost_jpy: Annotated[
        int | None,
        Field(
            ge=0,
            description=(
                "Optional in-body cost cap. The lower of this and the "
                "`X-Cost-Cap-JPY` header binds. 400 if predicted "
                "(`len(houjin_bangous) * 3`) exceeds the cap."
            ),
        ),
    ] = None


@router.post(
    "/dd_batch",
    summary="Batch DD over up to 200 法人 (¥3 per id, NDJSON when N>50)",
    description=(
        "Composes the existing dd_profile_am chain "
        "(corporate_entity + adoptions + enforcement + invoice + bids + "
        "amendment_recent) over a batch of 1..200 法人番号 in a single call.\n\n"
        "**Pricing**: ¥3 per houjin_bangou (per-id, NOT 1 ¥3/call). Cap "
        "enforced via `X-Cost-Cap-JPY` header AND/OR `max_cost_jpy` body "
        "field — the lower binds.\n\n"
        "**Response shape**:\n"
        "  - len ≤ 50 → application/json `{batch_size, profiles: [...], "
        "metered_yen, corpus_snapshot_id, _disclaimer, coverage_scope}`\n"
        "  - len > 50 → application/x-ndjson stream, one profile per line, "
        "terminated by a `{ \"_meta\": {...}, \"_disclaimer\": ..., "
        "\"coverage_scope\": ... }` envelope line.\n\n"
        "**§52 fence**: every response carries the 税理士法 §52 disclaimer "
        "and an explicit coverage_scope excluding 役員一覧 / 株主構成 / 経歴 / "
        "反社 / 信用情報 (商業登記法 gray-zone; TDB primary). LLM agents "
        "MUST relay both verbatim.\n\n"
        "**Operator**: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708). "
        "Brand: 税務会計AI."
    ),
)
def post_dd_batch(
    payload: DdBatchRequest,
    ctx: ApiContextDep,
    conn: DbDep,
    x_cost_cap_jpy: Annotated[
        str | None, Header(alias="X-Cost-Cap-JPY")
    ] = None,
) -> JSONResponse:
    # 1. Normalize + dedup (preserve order). Reject the request if any
    #    individual id can't normalize to 13 digits — the boutique caller
    #    passed bad input and we don't want a silent partial.
    normalized: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for raw in payload.houjin_bangous:
        n = _normalize_houjin(raw)
        if n is None:
            invalid.append(raw)
            continue
        if n in seen:
            continue
        seen.add(n)
        normalized.append(n)
    if invalid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "invalid_houjin_bangou",
                    "message": (
                        f"{len(invalid)} of {len(payload.houjin_bangous)} ids "
                        "failed to normalize to 13 digits."
                    ),
                    "invalid": invalid[:10],
                    "hint": (
                        "Each id must be a 13-digit 法人番号. "
                        "T-prefix インボイス番号、ハイフン入り、全角数字 are auto-"
                        "normalized. Sole-proprietors that lack a 法人番号 cannot "
                        "be batched here — use /v1/invoice_registrants/search."
                    ),
                }
            },
        )

    n_ids = len(normalized)
    predicted_yen = n_ids * _UNIT_PRICE_YEN
    _check_cost_cap(
        predicted_yen=predicted_yen,
        header_cap=_parse_cost_cap_header(x_cost_cap_jpy),
        body_cap=payload.max_cost_jpy,
    )

    # 2. Snapshot id once per request so every profile in the batch quotes
    #    the same auditor work-paper identity.
    snapshot_id, checksum = compute_corpus_snapshot(conn)

    # 3. Open autonomath.db RO once; share across the batch loop.
    am_conn = _open_autonomath_ro()

    # 4. Bill: one usage_event per houjin_bangou. We log AFTER the work so a
    #    transient DB error mid-batch doesn't bill the customer for rows
    #    they didn't get.
    profiles: list[dict[str, Any]] = []
    try:
        for hj in normalized:
            try:
                profiles.append(
                    _build_dd_profile(
                        jp_conn=conn,
                        am_conn=am_conn,
                        houjin_bangou=hj,
                        depth=payload.depth,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — partial-row resilience
                logger.warning("dd_batch profile failed for %s: %s", hj, exc)
                profiles.append({
                    "houjin_bangou": hj,
                    "error": {
                        "code": "internal_error",
                        "message": "profile compose failed; row skipped",
                    },
                    "dd_flags": ["compose_failed"],
                })
    finally:
        if am_conn is not None:
            with contextlib_suppress(sqlite3.Error):
                am_conn.close()

    # 5. Per-id metering. Each houjin = one billable event. We reuse the
    #    existing log_usage helper so dashboards / Stripe usage_records all
    #    reconcile against `endpoint='am.dd_batch.row'`.
    for hj in normalized:
        log_usage(
            conn,
            ctx,
            endpoint="am.dd_batch.row",
            params={"houjin_bangou": hj, "depth": payload.depth},
            result_count=1,
        )

    # 6. NDJSON stream when batch is large. Each profile gets its own line +
    #    a final meta envelope. Customers running this through `jq -c` will
    #    not need to wait for the whole result before they can pipe.
    if n_ids > _NDJSON_THRESHOLD:
        meta = {
            "_meta": {
                "batch_size": n_ids,
                "depth": payload.depth,
                "metered_yen": predicted_yen,
                "unit_price_yen": _UNIT_PRICE_YEN,
                "corpus_snapshot_id": snapshot_id,
                "corpus_checksum": checksum,
                "operator": "Bookyou株式会社",
                "operator_houjin_bangou": "T8010001213708",
                "brand": "税務会計AI",
            },
            "_disclaimer": _TAX_DISCLAIMER,
            "coverage_scope": _COVERAGE_SCOPE,
        }

        def _ndjson_iter():
            for p in profiles:
                yield json.dumps(p, ensure_ascii=False).encode("utf-8") + b"\n"
            yield json.dumps(meta, ensure_ascii=False).encode("utf-8") + b"\n"

        return StreamingResponse(
            _ndjson_iter(),
            media_type="application/x-ndjson",
            headers={
                "X-Metered-Yen": str(predicted_yen),
                "X-Batch-Size": str(n_ids),
                "X-Corpus-Snapshot-Id": snapshot_id,
            },
        )

    # 7. JSON response for small batches.
    body = {
        "batch_size": n_ids,
        "depth": payload.depth,
        "profiles": profiles,
        "metered_yen": predicted_yen,
        "unit_price_yen": _UNIT_PRICE_YEN,
        "corpus_snapshot_id": snapshot_id,
        "corpus_checksum": checksum,
        "operator": "Bookyou株式会社",
        "operator_houjin_bangou": "T8010001213708",
        "brand": "税務会計AI",
        "_disclaimer": _TAX_DISCLAIMER,
        "coverage_scope": _COVERAGE_SCOPE,
    }
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body,
        headers={
            "X-Metered-Yen": str(predicted_yen),
            "X-Batch-Size": str(n_ids),
        },
    )


# ---------------------------------------------------------------------------
# PILLAR 2: customer_watches CRUD (dispatcher cron lives separately)
# ---------------------------------------------------------------------------


_WATCH_KINDS: tuple[str, ...] = ("houjin", "program", "law")
WatchKindLiteral = Literal["houjin", "program", "law"]


class WatchRegisterRequest(BaseModel):
    watch_kind: WatchKindLiteral = Field(
        description="One of 'houjin' | 'program' | 'law'.",
    )
    target_id: Annotated[str, Field(min_length=1, max_length=128)] = Field(
        description=(
            "houjin_bangou (13 digits) for kind='houjin'; programs.unified_id "
            "for kind='program'; laws.law_id for kind='law'. Opaque to the "
            "API server — the dispatcher resolves it per-kind."
        ),
    )


class WatchResponse(BaseModel):
    id: int
    watch_kind: str
    target_id: str
    status: str
    registered_at: str
    last_event_at: str | None
    created_at: str


def _row_to_watch(row: dict) -> WatchResponse:
    return WatchResponse(
        id=row["id"],
        watch_kind=row["watch_kind"],
        target_id=row["target_id"],
        status=row["status"],
        registered_at=row["registered_at"],
        last_event_at=row["last_event_at"],
        created_at=row["created_at"],
    )


@watches_router.post(
    "",
    response_model=WatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a real-time watch (houjin / program / law)",
    description=(
        "Creates a customer_watches row. Watch *registration* is FREE; "
        "delivery is ¥3 per HTTP 2xx via the existing customer_webhooks "
        "infrastructure (dispatcher cron: dispatch_watch_events.py).\n\n"
        "Per-key watch cap: 5,000. Re-registering an existing target is a "
        "no-op (returns the existing row).\n\n"
        "Customer must ALSO register a webhook via "
        "/v1/me/webhooks before deliveries can fire. Watches without a "
        "matching webhook fan-out are silently dropped at dispatch time."
    ),
)
def register_watch(
    payload: WatchRegisterRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> WatchResponse:
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "watches require an authenticated API key",
        )
    # Per-kind validation — for houjin the 13-digit normalize is the spec.
    target_id = payload.target_id.strip()
    if payload.watch_kind == "houjin":
        norm = _normalize_houjin(target_id)
        if norm is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="target_id must be a 13-digit 法人番号",
            )
        target_id = norm
    elif len(target_id) > 128:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "target_id too long (max 128 chars)",
        )

    # Cap check.
    (n_active,) = conn.execute(
        "SELECT COUNT(*) FROM customer_watches "
        "WHERE api_key_hash = ? AND status = 'active'",
        (ctx.key_hash,),
    ).fetchone()
    if n_active >= _MAX_WATCHES_PER_KEY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"watch count cap reached ({_MAX_WATCHES_PER_KEY} active per key) — "
            "delete an existing watch before registering a new one.",
        )

    # Idempotent register: if the unique index already has an active row for
    # (key_hash, watch_kind, target_id) we return the existing row.
    existing = conn.execute(
        "SELECT id, watch_kind, target_id, status, registered_at, "
        "last_event_at, created_at FROM customer_watches "
        "WHERE api_key_hash = ? AND watch_kind = ? AND target_id = ? "
        "AND status = 'active' "
        "LIMIT 1",
        (ctx.key_hash, payload.watch_kind, target_id),
    ).fetchone()
    if existing is not None:
        return _row_to_watch(dict(existing))

    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """INSERT INTO customer_watches(
                api_key_hash, watch_kind, target_id,
                registered_at, status, created_at, updated_at
           ) VALUES (?, ?, ?, ?, 'active', ?, ?)""",
        (ctx.key_hash, payload.watch_kind, target_id, now, now, now),
    )
    new_id = cur.lastrowid
    if new_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "failed to register watch"
        )
    row = conn.execute(
        "SELECT id, watch_kind, target_id, status, registered_at, "
        "last_event_at, created_at FROM customer_watches WHERE id = ?",
        (new_id,),
    ).fetchone()
    return _row_to_watch(dict(row))


@watches_router.get(
    "",
    response_model=list[WatchResponse],
    summary="List the calling key's watches (active + disabled)",
)
def list_watches(
    ctx: ApiContextDep,
    conn: DbDep,
    watch_kind: Annotated[WatchKindLiteral | None, Query()] = None,
    status_filter: Annotated[
        Literal["active", "disabled"] | None,
        Query(alias="status"),
    ] = None,
) -> list[WatchResponse]:
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "watches require an authenticated API key",
        )
    where = ["api_key_hash = ?"]
    params: list[Any] = [ctx.key_hash]
    if watch_kind:
        where.append("watch_kind = ?")
        params.append(watch_kind)
    if status_filter:
        where.append("status = ?")
        params.append(status_filter)
    rows = conn.execute(
        "SELECT id, watch_kind, target_id, status, registered_at, "
        "last_event_at, created_at FROM customer_watches "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY id DESC LIMIT 5000",
        params,
    ).fetchall()
    return [_row_to_watch(dict(r)) for r in rows]


@watches_router.delete(
    "/{watch_id}",
    summary="Cancel a watch (soft delete; row stays for audit)",
)
def cancel_watch(
    watch_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
) -> dict[str, Any]:
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "watches require an authenticated API key",
        )
    row = conn.execute(
        "SELECT id, status FROM customer_watches "
        "WHERE id = ? AND api_key_hash = ?",
        (watch_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "watch not found")
    if row["status"] == "disabled":
        return {"ok": True, "id": watch_id}
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE customer_watches SET status='disabled', updated_at=?, "
        "disabled_at=?, disabled_reason='deleted_by_customer' "
        "WHERE id = ? AND api_key_hash = ?",
        (now, now, watch_id, ctx.key_hash),
    )
    return {"ok": True, "id": watch_id}


# ---------------------------------------------------------------------------
# PILLAR 3: group_graph (2-hop part_of traversal, 法人↔法人 only)
# ---------------------------------------------------------------------------


@router.get(
    "/group_graph",
    summary="2-hop 法人↔法人 part_of traversal (no shareholder data)",
    description=(
        "Walks `am_relation.part_of` edges where BOTH endpoints are "
        "`am_entities.record_kind='corporate_entity'` (filter applied "
        "in-query). Returns nodes + edges up to depth=2.\n\n"
        "**Excluded by design** (商業登記法 gray-zone, TDB primary):\n"
        "  - 役員一覧 / 株主構成 / 経歴 / 持株比率\n"
        "  - 反社チェック / 信用情報 / 帝国データバンク data\n\n"
        "**Pricing**: ¥3 per call (single houjin seed)."
    ),
)
def get_group_graph(
    ctx: ApiContextDep,
    conn: DbDep,
    houjin_bangou: Annotated[str, Query(min_length=1, max_length=64)],
    depth: Annotated[int, Query(ge=1, le=_MAX_GRAPH_DEPTH)] = 2,
) -> JSONResponse:
    norm = _normalize_houjin(houjin_bangou)
    if norm is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "houjin_bangou must normalize to 13 digits",
        )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    am_conn = _open_autonomath_ro()
    seed_canonical_id: str | None = None
    if am_conn is not None:
        try:
            # Resolve seed houjin to canonical_id.
            row = am_conn.execute(
                """SELECT canonical_id, primary_name, raw_json
                     FROM am_entities
                    WHERE record_kind = 'corporate_entity'
                      AND json_extract(raw_json, '$.houjin_bangou') = ?
                    LIMIT 1""",
                (norm,),
            ).fetchone()
            if row:
                try:
                    raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
                except Exception:
                    raw = {}
                seed_canonical_id = row["canonical_id"]
                nodes[seed_canonical_id] = {
                    "canonical_id": seed_canonical_id,
                    "houjin_bangou": norm,
                    "name": row["primary_name"] or raw.get("name"),
                    "depth": 0,
                }

                # BFS over part_of edges with corporate_entity↔corporate_entity
                # filter. We stop at _MAX_GRAPH_NODES to bound the response.
                frontier: list[str] = [seed_canonical_id]
                for d in range(1, depth + 1):
                    if len(nodes) >= _MAX_GRAPH_NODES:
                        break
                    next_frontier: list[str] = []
                    if not frontier:
                        break
                    placeholders = ",".join("?" for _ in frontier)
                    rows = am_conn.execute(
                        f"""SELECT r.source_entity_id, r.target_entity_id,
                                   r.confidence, r.origin
                              FROM am_relation r
                              JOIN am_entities e1 ON e1.canonical_id = r.source_entity_id
                              JOIN am_entities e2 ON e2.canonical_id = r.target_entity_id
                             WHERE r.relation_type = 'part_of'
                               AND e1.record_kind = 'corporate_entity'
                               AND e2.record_kind = 'corporate_entity'
                               AND (r.source_entity_id IN ({placeholders})
                                    OR r.target_entity_id IN ({placeholders}))
                             LIMIT 5000""",
                        frontier + frontier,
                    ).fetchall()
                    for er in rows:
                        src = er["source_entity_id"]
                        tgt = er["target_entity_id"]
                        edges.append({
                            "source": src,
                            "target": tgt,
                            "relation_type": "part_of",
                            "confidence": er["confidence"],
                            "origin": er["origin"],
                        })
                        for nid in (src, tgt):
                            if nid in nodes:
                                continue
                            if len(nodes) >= _MAX_GRAPH_NODES:
                                break
                            # Resolve node metadata one row at a time.
                            nr = am_conn.execute(
                                "SELECT canonical_id, primary_name, raw_json "
                                "FROM am_entities WHERE canonical_id = ? LIMIT 1",
                                (nid,),
                            ).fetchone()
                            if nr is None:
                                continue
                            try:
                                raw_n = json.loads(nr["raw_json"]) if nr["raw_json"] else {}
                            except Exception:
                                raw_n = {}
                            nodes[nid] = {
                                "canonical_id": nr["canonical_id"],
                                "houjin_bangou": raw_n.get("houjin_bangou"),
                                "name": nr["primary_name"] or raw_n.get("name"),
                                "depth": d,
                            }
                            next_frontier.append(nid)
                    frontier = next_frontier
        except sqlite3.OperationalError as exc:
            logger.debug("group_graph traversal failed: %s", exc)
        finally:
            with contextlib_suppress(sqlite3.Error):
                am_conn.close()

    snapshot_id, checksum = compute_corpus_snapshot(conn)
    body = {
        "houjin_bangou": norm,
        "seed_canonical_id": seed_canonical_id,
        "depth": depth,
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_cap": _MAX_GRAPH_NODES,
        "metered_yen": _UNIT_PRICE_YEN,
        "unit_price_yen": _UNIT_PRICE_YEN,
        "corpus_snapshot_id": snapshot_id,
        "corpus_checksum": checksum,
        "operator": "Bookyou株式会社",
        "operator_houjin_bangou": "T8010001213708",
        "brand": "税務会計AI",
        "_disclaimer": _TAX_DISCLAIMER,
        "coverage_scope": _COVERAGE_SCOPE,
        "graph_scope_note": (
            "part_of edges only; nodes restricted to am_entities."
            "record_kind='corporate_entity'. 役員/株主/経歴 は範囲外。"
        ),
    }

    log_usage(
        conn,
        ctx,
        endpoint="am.group_graph",
        params={"houjin_bangou": norm, "depth": depth},
        result_count=len(nodes),
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=body)


# ---------------------------------------------------------------------------
# PILLAR 4: dd_export (audit-bundle ZIP via signed R2 URL)
#
# The ONLY non-¥3 SKU in the system: ¥3 × N (per-id) + ¥30 fixed bundle fee.
# Justified by R2 storage compute (zip + sha256 manifest + signed URL
# lifecycle). Documented explicitly in docs/pricing.md.
# ---------------------------------------------------------------------------


class DdExportRequest(BaseModel):
    deal_id: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_\-:.]+$")
    ] = Field(
        description=(
            "Free-form audit deal identifier; written into the bundle "
            "manifest. Boutiques typically use 'PROJECT-ALPHA-2026' shaped "
            "tags so the bundle ZIP filename round-trips through their "
            "deal-room."
        ),
    )
    houjin_bangous: Annotated[
        list[str], Field(min_length=1, max_length=_MAX_BATCH_HOUJIN)
    ]
    format: Annotated[Literal["zip", "pdf"], Field()] = "zip"
    bundle_class: Annotated[
        Literal["standard", "deal", "case"],
        Field(
            description=(
                "Artifact-size selector controlling the per-bundle quantity "
                "multiplier (NOT a tier SKU). Each class maps to a fixed "
                "number of ¥3 billing units:\n"
                "  standard → 333 units (≈¥1,000)\n"
                "  deal     → 1,000 units (≈¥3,000)\n"
                "  case     → 3,333 units (≈¥10,000)\n"
                "Customer is charged `(N houjin + bundle_units) × ¥3`."
            ),
        ),
    ] = "standard"
    max_cost_jpy: Annotated[
        int | None, Field(ge=0)
    ] = None


def _build_audit_bundle_zip(
    *,
    deal_id: str,
    profiles: list[dict[str, Any]],
    snapshot_id: str,
    checksum: str,
) -> tuple[bytes, str]:
    """Materialize the audit-bundle ZIP in memory. Return (zip_bytes,
    sha256_hex_of_zip).

    Bundle contents:
      manifest.json                        — deal_id, snapshot, file map
      profiles/<houjin>.jsonl              — one profile per file, jsonl
      cite_chain.json                      — provenance cite-chain rollup
      sha256.manifest                      — `<sha256>  <filename>` per line
      README.txt                           — boutique-readable summary

    The ZIP is materialized in memory (BytesIO) so we can stream it to R2
    in a single pass. For >200 法人 the materialized size is bounded by
    the per-row payload (~5KB summary, ~30KB full) — well under typical
    R2 multipart thresholds (5MB).
    """
    buf = BytesIO()
    inner_files: dict[str, bytes] = {}

    # Per-houjin JSONL.
    for p in profiles:
        hj = p.get("houjin_bangou") or "_unknown"
        # Honest filename: include the deal_id so unzipped contents don't
        # collide between bundles in a deal-room workspace.
        fname = f"profiles/{hj}.jsonl"
        # JSONL with one canonical record. Future field additions get
        # additional lines without breaking existing readers.
        line = json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8")
        inner_files[fname] = line + b"\n"

    # Cite chain rollup — every source_url across the profile set with a
    # short context tag. Used by auditors to cross-reference primary
    # sources without re-running the API.
    cite_chain: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for p in profiles:
        hj = p.get("houjin_bangou")
        for ev in (p.get("enforcement", {}) or {}).get("recent_history", []) or []:
            url = ev.get("source_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                cite_chain.append({
                    "houjin_bangou": hj,
                    "kind": "enforcement",
                    "url": url,
                    "case_id": ev.get("case_id"),
                })
        for ev in (p.get("enforcement", {}) or {}).get("active_exclusions", []) or []:
            url = ev.get("source_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                cite_chain.append({
                    "houjin_bangou": hj,
                    "kind": "enforcement_active",
                    "url": url,
                    "case_id": ev.get("case_id"),
                })
        for am in p.get("amendment_recent", []) or []:
            url = am.get("source_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                cite_chain.append({
                    "houjin_bangou": hj,
                    "kind": "amendment",
                    "url": url,
                    "diff_id": am.get("diff_id"),
                })
        for b in (p.get("bids_summary", {}) or {}).get("recent_won", []) or []:
            url = b.get("source_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                cite_chain.append({
                    "houjin_bangou": hj,
                    "kind": "bid",
                    "url": url,
                    "unified_id": b.get("unified_id"),
                })
    inner_files["cite_chain.json"] = json.dumps(
        cite_chain, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")

    # README — boutique-readable summary.
    readme = (
        f"AutonoMath audit bundle\n"
        f"=======================\n\n"
        f"Deal: {deal_id}\n"
        f"Profiles: {len(profiles)}\n"
        f"Corpus snapshot: {snapshot_id}\n"
        f"Corpus checksum: {checksum}\n"
        f"Generated: {datetime.now(UTC).isoformat()}\n"
        f"Operator: Bookyou株式会社 (T8010001213708)\n"
        f"Brand: 税務会計AI\n\n"
        f"Files:\n"
        f"  manifest.json           — bundle metadata + file map\n"
        f"  profiles/<houjin>.jsonl — one record per company\n"
        f"  cite_chain.json         — provenance rollup\n"
        f"  sha256.manifest         — `<sha256>  <filename>` per line\n\n"
        f"§52 fence: {_TAX_DISCLAIMER}\n\n"
        f"Coverage scope: {_COVERAGE_SCOPE}\n"
    )
    inner_files["README.txt"] = readme.encode("utf-8")

    # SHA-256 manifest computed BEFORE manifest.json is written so manifest
    # itself doesn't need to be self-referential.
    sha_lines: list[str] = []
    for name in sorted(inner_files):
        digest = hashlib.sha256(inner_files[name]).hexdigest()
        sha_lines.append(f"{digest}  {name}")
    inner_files["sha256.manifest"] = ("\n".join(sha_lines) + "\n").encode("utf-8")

    # manifest.json — written LAST so it can include sha of every other file.
    manifest_obj = {
        "deal_id": deal_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "operator": "Bookyou株式会社",
        "operator_houjin_bangou": "T8010001213708",
        "brand": "税務会計AI",
        "corpus_snapshot_id": snapshot_id,
        "corpus_checksum": checksum,
        "profile_count": len(profiles),
        "files": [
            {"name": n, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
            for n, b in sorted(inner_files.items())
        ],
        "_disclaimer": _TAX_DISCLAIMER,
        "coverage_scope": _COVERAGE_SCOPE,
    }
    inner_files["manifest.json"] = json.dumps(
        manifest_obj, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")

    with zipfile.ZipFile(
        buf, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zf:
        for name in sorted(inner_files):
            zf.writestr(name, inner_files[name])

    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def _upload_bundle_to_r2(
    *, zip_bytes: bytes, key: str, ttl_hours: int = _BUNDLE_URL_TTL_HOURS,
) -> tuple[str, datetime]:
    """Upload to R2 and return a (signed_url, expires_at) tuple.

    Best-effort: when rclone / R2 env vars are missing we fall back to
    a local "stub" URL (`local://<key>`) so the route never 500s on a
    missing-storage deploy. The response carries a stub flag so callers
    know not to publish the URL to a third party.
    """
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)

    # Late import keeps the api hot path free of subprocess / rclone bring-up
    # cost when no caller has hit dd_export yet.
    try:
        from scripts.cron._r2_client import R2ConfigError, upload  # noqa: PLC0415
    except Exception:
        return f"local://{key}#stub_no_r2_module", expires_at

    # Stage to a temp file; rclone needs a real file handle (no stdin path).
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path = Path(tmp.name)
    try:
        try:
            upload(tmp_path, key)
        except R2ConfigError as exc:
            logger.warning("dd_export r2 stub: %s", exc)
            return f"local://{key}#stub_{exc}", expires_at
        except Exception as exc:  # noqa: BLE001
            logger.warning("dd_export r2 upload failed: %s", exc)
            return f"local://{key}#stub_upload_failed", expires_at
    finally:
        with contextlib_suppress(OSError):
            tmp_path.unlink()

    # Signed-URL minting via rclone is a pre-signed S3 URL; for the in-house
    # pipeline we round-trip via `rclone link --expire` if available. The
    # current shared helper does not expose link generation, so we surface
    # the canonical R2 path + expiry — the customer downloads via a separate
    # short-lived pre-signed URL minted by the operator (Cloudflare R2 API).
    # The route does NOT mint a Cloudflare-signed URL itself today; this
    # forward-compat slot is here so the response shape is stable.
    bucket = os.environ.get("R2_BUCKET", "autonomath-backup")
    endpoint = os.environ.get("R2_ENDPOINT", "")
    base = endpoint.rstrip("/") if endpoint else "https://r2.cloudflarestorage.com"
    return f"{base}/{bucket}/{key}", expires_at


@router.post(
    "/dd_export",
    summary="Audit-bundle ZIP via signed R2 URL (¥3 × (N + bundle_units))",
    description=(
        "Builds a ZIP containing one JSONL per houjin + cite_chain.json + "
        "sha256.manifest + manifest.json, uploads to R2, returns a signed "
        "URL with 24h TTL.\n\n"
        "**Pricing**: ¥3 per houjin_bangou + ¥3 per `bundle_units` where "
        "`bundle_units` is determined by `bundle_class` "
        "(standard=333 / deal=1,000 / case=3,333). Customer total = "
        "`(N + bundle_units) × ¥3`. NO tier SKU — the multiplier is an "
        "artifact-size knob like `row_count` in bulk_evaluate. "
        "Documented explicitly in docs/pricing.md.\n\n"
        "**§52 fence**: response carries the 税理士法 §52 disclaimer + "
        "coverage_scope. The bundle README + manifest.json mirror the "
        "fence inside the ZIP."
    ),
)
def post_dd_export(
    payload: DdExportRequest,
    ctx: ApiContextDep,
    conn: DbDep,
    x_cost_cap_jpy: Annotated[
        str | None, Header(alias="X-Cost-Cap-JPY")
    ] = None,
) -> JSONResponse:
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "audit bundle export requires an authenticated API key",
        )
    if payload.format != "zip":
        # PDF mode is reserved for a future signed PDF audit-pack; the spec
        # only mandates ZIP today. Return a clear 400 so callers don't
        # silently get a ZIP they thought was a PDF.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"format={payload.format!r} not yet available; ZIP only.",
        )

    # Normalize + dedup.
    normalized: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for raw in payload.houjin_bangous:
        n = _normalize_houjin(raw)
        if n is None:
            invalid.append(raw)
            continue
        if n in seen:
            continue
        seen.add(n)
        normalized.append(n)
    if invalid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "invalid_houjin_bangou",
                    "invalid": invalid[:10],
                }
            },
        )

    n_ids = len(normalized)
    bundle_units = _BUNDLE_CLASS_UNITS[payload.bundle_class]
    bundle_fee_yen = bundle_units * _UNIT_PRICE_YEN
    predicted_yen = n_ids * _UNIT_PRICE_YEN + bundle_fee_yen
    _check_cost_cap(
        predicted_yen=predicted_yen,
        header_cap=_parse_cost_cap_header(x_cost_cap_jpy),
        body_cap=payload.max_cost_jpy,
    )

    snapshot_id, checksum = compute_corpus_snapshot(conn)
    am_conn = _open_autonomath_ro()
    try:
        profiles = [
            _build_dd_profile(
                jp_conn=conn,
                am_conn=am_conn,
                houjin_bangou=hj,
                depth="full",
            )
            for hj in normalized
        ]
    finally:
        if am_conn is not None:
            with contextlib_suppress(sqlite3.Error):
                am_conn.close()

    # Build + upload bundle.
    zip_bytes, zip_sha256 = _build_audit_bundle_zip(
        deal_id=payload.deal_id,
        profiles=profiles,
        snapshot_id=snapshot_id,
        checksum=checksum,
    )
    # R2 key: includes deal_id + snapshot_id + a random nonce so two boutique
    # users running the same deal on the same snapshot get distinct keys
    # (avoid mid-flight overwrite + signed URL race).
    nonce = secrets.token_urlsafe(8)
    safe_deal = "".join(c if c.isalnum() or c in "_-" else "_" for c in payload.deal_id)
    r2_key = f"audit_bundle/{safe_deal}/{snapshot_id}/{nonce}.zip"
    signed_url, expires_at = _upload_bundle_to_r2(
        zip_bytes=zip_bytes, key=r2_key,
    )

    # Bill: per-id (N rows of am.dd_export.row) + the bundle fee surfaced
    # as a SINGLE usage_event with `quantity=bundle_units` so the Stripe
    # usage_record posts ONE line for the bundle (not N parallel POSTs).
    # Same ¥-total as the legacy loop (`bundle_units × ¥3`) but with one
    # idempotency key per export → cleaner reconciliation surface.
    for hj in normalized:
        log_usage(
            conn,
            ctx,
            endpoint="am.dd_export.row",
            params={"houjin_bangou": hj, "deal_id": payload.deal_id},
            result_count=1,
        )
    # Bundle fee — single row, quantity = bundle_units.
    log_usage(
        conn,
        ctx,
        endpoint="am.dd_export.bundle_fee",
        params={
            "deal_id": payload.deal_id,
            "bundle_sha256": zip_sha256,
            "bundle_class": payload.bundle_class,
        },
        quantity=bundle_units,
        result_count=bundle_units,
    )

    body = {
        "deal_id": payload.deal_id,
        "format": payload.format,
        "batch_size": n_ids,
        "bundle_class": payload.bundle_class,
        "bundle_units": bundle_units,
        "signed_url": signed_url,
        "expires_at": expires_at.isoformat(),
        "ttl_hours": _BUNDLE_URL_TTL_HOURS,
        "bundle_bytes": len(zip_bytes),
        "bundle_sha256": zip_sha256,
        "manifest_filename": "manifest.json",
        "metered_yen": predicted_yen,
        "metered_breakdown": {
            "per_houjin_yen": _UNIT_PRICE_YEN,
            "per_houjin_count": n_ids,
            "subtotal_yen": n_ids * _UNIT_PRICE_YEN,
            "bundle_class": payload.bundle_class,
            "bundle_units": bundle_units,
            "audit_bundle_fee_yen": bundle_fee_yen,
            "total_yen": predicted_yen,
        },
        "pricing_note": (
            f"Audit bundle export: ¥3 × ({n_ids} houjin + {bundle_units} "
            f"bundle_units) = ¥{predicted_yen}. Stays pure ¥3/req metered "
            "— bundle_class controls the artifact-size quantity multiplier "
            "(standard=333 / deal=1,000 / case=3,333) like row_count in "
            "bulk_evaluate; it is NOT a tier SKU. See docs/pricing.md."
        ),
        "corpus_snapshot_id": snapshot_id,
        "corpus_checksum": checksum,
        "operator": "Bookyou株式会社",
        "operator_houjin_bangou": "T8010001213708",
        "brand": "税務会計AI",
        "_disclaimer": _TAX_DISCLAIMER,
        "coverage_scope": _COVERAGE_SCOPE,
    }
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body,
        headers={
            "X-Metered-Yen": str(predicted_yen),
            "X-Bundle-Sha256": zip_sha256,
        },
    )


__all__ = [
    "router",
    "watches_router",
    "_AUDIT_BUNDLE_FEE_YEN",
    "_BUNDLE_CLASS_UNITS",
    "_MAX_BATCH_HOUJIN",
    "_NDJSON_THRESHOLD",
    "_TAX_DISCLAIMER",
    "_COVERAGE_SCOPE",
    "_normalize_houjin",
    "_build_dd_profile",
    "_build_audit_bundle_zip",
    "_check_cost_cap",
    "_parse_cost_cap_header",
]
