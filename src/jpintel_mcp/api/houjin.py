"""REST handler for /v1/houjin/{bangou} — corporate 360 lookup by 法人番号.

Surfaces the 1.12M gBizINFO facts already absorbed into autonomath.db
(`am_entities` record_kind='corporate_entity' + `am_entity_facts` 21
corp.* field_names per V4 absorption — 79,876 corporate_entity rows
populated as of 2026-04-29). Joins jpintel-mirrored auxiliaries:

    autonomath.db  am_entities         (record_kind='corporate_entity', name)
    autonomath.db  am_entity_facts     (corp.*, EAV)
    autonomath.db  jpi_invoice_registrants (T-prefix, registered_date)
    autonomath.db  jpi_adoption_records    (n_adoptions, recent rounds)
    autonomath.db  am_enforcement_detail   (n_enforcements, recent kinds)

Pricing: ¥3/req metered (1 unit), single GET. Anonymous tier shares the
3/日 IP cap via AnonIpLimitDep on the router mount in api/main.py.

§52 envelope: every 2xx body carries a `_disclaimer` envelope key plus a
`_namayoke_caveat` (名寄せ) explicitly noting that 法人番号 → entity_id
resolution may aggregate distinct legal entities sharing a 法人番号 (rare
but possible after 法人合併 / 商号変更 events).

Read-only. The autonomath connection is opened in `mode=ro` so a
misconfigured deploy can never write to the 9.4 GB primary DB through
this surface.
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._envelope import StandardError, StandardResponse, wants_envelope_v2
from jpintel_mcp.api._error_envelope import safe_request_id
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.ingest._gbiz_attribution import (
    LICENSE_NAME as GBIZ_LICENSE_NAME,
)
from jpintel_mcp.ingest._gbiz_attribution import (
    LICENSE_URL as GBIZ_LICENSE_URL,
)
from jpintel_mcp.ingest._gbiz_attribution import (
    PUBLISHER_NAME as GBIZ_PUBLISHER_NAME,
)
from jpintel_mcp.ingest._gbiz_attribution import (
    SOURCE_NAME as GBIZ_SOURCE_NAME,
)
from jpintel_mcp.ingest._gbiz_attribution import (
    attribution_disclaimer_short,
    inject_attribution_into_response,
)

router = APIRouter(prefix="/v1/houjin", tags=["houjin"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 13-digit 法人番号. Path-level regex below additionally enforces the format
# at FastAPI's parameter layer; this guard is defence-in-depth in case a
# future router refactor relaxes the path pattern.
_BANGOU_RE = re.compile(r"^\d{13}$")

# Cap on the number of corp.* facts returned in a single response. The
# 21 V4 corp.* field_names are stable and small; a 50-fact cap keeps a
# typical body well under the 50 KB target while leaving headroom for
# future field additions without forcing a paginate cut-over.
_MAX_FACTS = 50

# Cap on the number of recent adoption / enforcement rows surfaced inline.
# Kept tight — callers wanting the full timeline use the dedicated
# /v1/am/* endpoints (acceptance_stats / check_enforcement).
_MAX_RECENT_ADOPTIONS = 5
_MAX_RECENT_ENFORCEMENTS = 5

# 税理士法 §52 fence — DOC-level information, never 税務助言.
_DISCLAIMER = (
    "本情報は税務助言ではありません。jpcite は公的機関 (gBizINFO・国税庁・"
    "会計検査院 等) が公表する企業情報を検索・整理して提供するサービスで、"
    "税理士法 §52 に基づき個別具体的な税務判断・与信判断は行いません。"
    "個別案件は資格を有する税理士・公認会計士に必ずご相談ください。"
)

# 名寄せ caveat — 法人番号 is unique per the 商業登記法 issuing rule, but
# legacy gBizINFO facts may straddle 商号変更 / 合併 boundaries (a single
# 法人番号 inherits facts from a predecessor entity). Surfaced verbatim so
# downstream LLMs do not relay a stale 商号 as the current one.
_NAMAYOKE_CAVEAT = (
    "本データは公開情報の名寄せ結果です。法人番号は一意ですが、商号変更・合併・"
    "事業譲渡 等のイベント前後では同一番号の下に異なる時点の情報が混在する場合"
    "があります。最新の登記情報は法務局・gBizINFO 一次サイトでご確認ください。"
)

_GBIZ_UPSTREAM_SOURCE = "NTA Houjin Bangou Web-API"


def _mark_envelope_v2_served(request: Request) -> None:
    """Tell EnvelopeAdapterMiddleware that this route emitted the v2 shape."""
    with contextlib.suppress(Exception):
        request.state.envelope_v2_served = True


# ---------------------------------------------------------------------------
# Autonomath read-only connection helper (pattern from api/ma_dd.py)
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path. Mirrors api/ma_dd.py::_autonomath_db_path."""
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open a read-only connection to autonomath.db. Returns None when the
    file is missing — endpoint then returns the structured 503 below.
    """
    p = _autonomath_db_path()
    if not p.exists():
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


def _normalize_bangou(raw: str) -> str | None:
    """Strip 'T' prefix, NFKC fullwidth-digits, hyphens, spaces. Return 13
    digits or None on malformed input.
    """
    s = unicodedata.normalize("NFKC", str(raw))
    s = s.strip().lstrip("Tt")
    for ch in "- ,　":
        s = s.replace(ch, "")
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _gbiz_lookup_url(bangou: str) -> str:
    return f"https://info.gbiz.go.jp/hojin/ichiran?hojinBango={bangou}"


def _attach_gbiz_attribution(body: dict[str, Any], bangou: str) -> dict[str, Any]:
    """Attach mandatory gBizINFO attribution when corporate facts are present."""
    provenance = body.get("provenance") or {}
    if not body.get("fact_count") and not provenance.get("has_corporate_entity"):
        return body
    fetched_at = str(provenance.get("source_snapshot_at") or provenance.get("fetched_at") or "")
    return inject_attribution_into_response(
        body,
        source_url=_gbiz_lookup_url(bangou),
        fetched_at=fetched_at,
        upstream_source=_GBIZ_UPSTREAM_SOURCE,
    )


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def _build_houjin_360(am_conn: sqlite3.Connection, bangou: str) -> dict[str, Any] | None:
    """Compose the 360 envelope from autonomath.db reads.

    Returns ``None`` when no row exists in `am_entities` for the
    `houjin:<bangou>` canonical_id AND no corresponding `jpi_houjin_master`
    / `jpi_invoice_registrants` row exists. The 'no facts but invoice
    exists' case still returns a usable shell so callers can see the
    invoice registration before our gBizINFO ingest catches up.
    """
    canonical_id = f"houjin:{bangou}"

    # 1. core entity row (am_entities)
    entity_row = am_conn.execute(
        """SELECT canonical_id, primary_name, source_url, fetched_at, created_at,
                  updated_at, confidence
             FROM am_entities
            WHERE canonical_id = ?
              AND record_kind = 'corporate_entity'""",
        (canonical_id,),
    ).fetchone()

    # 2. facts (am_entity_facts) — index hit on idx_am_entity_facts_csc
    fact_rows = am_conn.execute(
        """SELECT field_name, field_value_text, field_value_numeric, unit, field_kind
             FROM am_entity_facts
            WHERE entity_id = ?
            ORDER BY field_name
            LIMIT ?""",
        (canonical_id, _MAX_FACTS),
    ).fetchall()

    # 3. invoice registration (jpi_invoice_registrants — soft FK by houjin_bangou)
    invoice_row = am_conn.execute(
        """SELECT invoice_registration_number, registered_date, revoked_date,
                  expired_date, prefecture, registrant_kind
             FROM jpi_invoice_registrants
            WHERE houjin_bangou = ?
            LIMIT 1""",
        (bangou,),
    ).fetchone()

    # 4. adoption rollup (jpi_adoption_records)
    (n_adoptions,) = am_conn.execute(
        "SELECT COUNT(*) FROM jpi_adoption_records WHERE houjin_bangou = ?",
        (bangou,),
    ).fetchone()
    recent_adoptions: list[dict[str, Any]] = []
    if n_adoptions:
        recent_adoptions = [
            {
                "program_name": r["program_name_raw"],
                "round_label": r["round_label"],
                "announced_at": r["announced_at"],
                "amount_granted_yen": r["amount_granted_yen"],
                "source_url": r["source_url"],
            }
            for r in am_conn.execute(
                """SELECT program_name_raw, round_label, announced_at,
                          amount_granted_yen, source_url
                     FROM jpi_adoption_records
                    WHERE houjin_bangou = ?
                    ORDER BY COALESCE(announced_at, '') DESC
                    LIMIT ?""",
                (bangou, _MAX_RECENT_ADOPTIONS),
            ).fetchall()
        ]

    # 5. enforcement rollup (am_enforcement_detail)
    (n_enforcements,) = am_conn.execute(
        "SELECT COUNT(*) FROM am_enforcement_detail WHERE houjin_bangou = ?",
        (bangou,),
    ).fetchone()
    recent_enforcements: list[dict[str, Any]] = []
    if n_enforcements:
        recent_enforcements = [
            {
                "enforcement_kind": r["enforcement_kind"],
                "issuing_authority": r["issuing_authority"],
                "issuance_date": r["issuance_date"],
                "amount_yen": r["amount_yen"],
                "reason_summary": r["reason_summary"],
                "source_url": r["source_url"],
            }
            for r in am_conn.execute(
                """SELECT enforcement_kind, issuing_authority, issuance_date,
                          amount_yen, reason_summary, source_url
                     FROM am_enforcement_detail
                    WHERE houjin_bangou = ?
                    ORDER BY issuance_date DESC
                    LIMIT ?""",
                (bangou, _MAX_RECENT_ENFORCEMENTS),
            ).fetchall()
        ]

    # If we have no entity row AND no auxiliary hits, treat as 404.
    if (
        entity_row is None
        and not fact_rows
        and invoice_row is None
        and not n_adoptions
        and not n_enforcements
    ):
        return None

    # Distill the 21 corp.* facts into a single map (text|numeric, whichever
    # is populated) so consumers don't have to re-parse the EAV.
    corp_facts: dict[str, Any] = {}
    fact_count = 0
    for r in fact_rows:
        fname = r["field_name"]
        # Skip the redundant houjin_bangou fact — already in the path.
        if fname == "houjin_bangou":
            continue
        # Numeric fact wins when present (employee_count, capital_amount).
        if r["field_value_numeric"] is not None:
            corp_facts[fname] = {
                "value": r["field_value_numeric"],
                "unit": r["unit"],
                "kind": r["field_kind"],
            }
        else:
            corp_facts[fname] = {
                "value": r["field_value_text"],
                "unit": r["unit"],
                "kind": r["field_kind"],
            }
        fact_count += 1

    # Pull the most useful basics into a top-level `basic` block so callers
    # don't have to dig through `corp_facts` for the obvious fields.
    def _pluck(name: str) -> Any:
        f = corp_facts.get(name)
        return f["value"] if f else None

    basic = {
        "houjin_bangou": bangou,
        "name": (entity_row["primary_name"] if entity_row else _pluck("corp.legal_name")),
        "name_kana": _pluck("corp.legal_name_kana"),
        "name_en": _pluck("corp.legal_name_en"),
        "address": _pluck("corp.location"),
        "prefecture": _pluck("corp.prefecture"),
        "municipality": _pluck("corp.municipality"),
        "postal_code": _pluck("corp.postal_code"),
        "founded_date": _pluck("corp.date_of_establishment"),
        "representative": _pluck("corp.representative"),
        "company_url": _pluck("corp.company_url"),
        "industry_jsic_major": _pluck("corp.jsic_major"),
        "industry_raw": _pluck("corp.industry_raw"),
        "employee_count": _pluck("corp.employee_count"),
        "capital_yen": _pluck("corp.capital_amount"),
        "business_summary": _pluck("corp.business_summary"),
        "status": _pluck("corp.status"),
    }

    invoice_block: dict[str, Any] | None = None
    if invoice_row is not None:
        invoice_block = {
            "invoice_registration_number": invoice_row["invoice_registration_number"],
            "registered_date": invoice_row["registered_date"],
            "revoked_date": invoice_row["revoked_date"],
            "expired_date": invoice_row["expired_date"],
            "prefecture": invoice_row["prefecture"],
            "registrant_kind": invoice_row["registrant_kind"],
        }

    source_snapshot_at = None
    if entity_row is not None:
        source_snapshot_at = (
            entity_row["fetched_at"] or entity_row["updated_at"] or entity_row["created_at"]
        )

    body: dict[str, Any] = {
        "basic": basic,
        "corp_facts": corp_facts,
        "fact_count": fact_count,
        "invoice_registration": invoice_block,
        "adoptions": {
            "total": int(n_adoptions),
            "recent": recent_adoptions,
        },
        "enforcement": {
            "total": int(n_enforcements),
            "recent": recent_enforcements,
        },
        "provenance": {
            "canonical_id": canonical_id,
            "has_corporate_entity": entity_row is not None,
            "primary_source": (entity_row["source_url"] if entity_row else None),
            "fetched_at": (entity_row["fetched_at"] if entity_row else None),
            "source_snapshot_at": source_snapshot_at,
            "confidence": (entity_row["confidence"] if entity_row else None),
            "gbizinfo_source_url": _gbiz_lookup_url(bangou),
            "gbizinfo_license": GBIZ_LICENSE_NAME,
            "gbizinfo_license_url": GBIZ_LICENSE_URL,
            "upstream_source": _GBIZ_UPSTREAM_SOURCE,
            "data_origin": "gBizINFO + 国税庁適格事業者公表サイト + 会計検査院",
        },
        "_disclaimer": _DISCLAIMER,
        "_namayoke_caveat": _NAMAYOKE_CAVEAT,
    }
    return body


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/{bangou}",
    summary="Corporate 360 lookup by 法人番号",
    description=(
        "Returns corporate facts, adoption history, enforcement details, "
        "and registration status from public datasets for a given 13-digit "
        "法人番号.\n\n"
        "**Pricing:** ¥3/call (1 unit). Anonymous callers share the "
        "3/日 per-IP cap (JST 翌日 00:00 リセット).\n\n"
        "**§52 envelope:** every 2xx body carries `_disclaimer` "
        "(税理士法 §52 fence) + `_namayoke_caveat` (商号変更・合併 周辺の "
        "名寄せ caveat). LLM relays must surface both verbatim.\n\n"
        "**Coverage:** unavailable records return official lookup guidance."
    ),
    responses={
        200: {
            "description": (
                "Corporate 360 envelope. `corp_facts` is a name → "
                "{value, unit, kind} map covering the 21 corp.* "
                "field_names; `basic` distills the top-level identity "
                "fields; auxiliaries (`invoice_registration`, "
                "`adoptions`, `enforcement`) carry the joined rollups."
            )
        },
        404: {
            "description": (
                "No `am_entities` corporate_entity row AND no auxiliary "
                "rows for this 法人番号. The body carries a structured "
                "miss explanation with the official gBizINFO lookup URL."
            ),
        },
        422: {"description": "bangou must match '^\\d{13}$' (13 digits, half-width)"},
        503: {
            "description": ("autonomath.db unreachable (partial deploy / file missing)."),
        },
    },
)
def get_houjin_360(
    request: Request,
    bangou: Annotated[
        str,
        PathParam(
            min_length=13,
            max_length=13,
            pattern=r"^\d{13}$",
            description="13-digit 法人番号 (half-width digits, no T-prefix).",
            examples=["4120101047866"],
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return one corporate 360 envelope for the given 法人番号.

    Reads from autonomath.db (read-only) for both `am_*` source-of-truth
    and `jpi_*` mirrors. The handler never opens a write connection.
    """
    _t0 = time.perf_counter()

    # Path regex already enforces 13-digit half-width, but we run the
    # NFKC normaliser here too so an upstream proxy that fullwidth-encoded
    # the path still resolves to the canonical bangou.
    norm = _normalize_bangou(bangou)
    if norm is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "bangou must be 13 half-width digits (no T-prefix)",
        )

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "autonomath.db unavailable",
        )

    try:
        body = _build_houjin_360(am_conn, norm)
    finally:
        am_conn.close()

    if body is None:
        log_usage(
            conn,
            ctx,
            "houjin.get",
            status_code=status.HTTP_404_NOT_FOUND,
            params={"miss": True},
        )
        if wants_envelope_v2(request):
            _mark_envelope_v2_served(request)
            err = StandardError.not_found(
                "houjin",
                norm,
                developer_message=(
                    "houjin not found in current corporate snapshot; "
                    f"official lookup may still contain bangou={norm}"
                ),
            )
            env = StandardResponse.from_error(
                err,
                request_id=safe_request_id(request),
                query_echo={
                    "normalized_input": {"bangou": norm},
                    "applied_filters": {"bangou": norm},
                    "unparsed_terms": [],
                },
                billable_units=0,
            )
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=env.to_wire(),
                headers={"X-Envelope-Version": "v2"},
            )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": (
                    "Not found in current corporate snapshot. "
                    "jpcite mirrors a 79,876-row gBizINFO subset; "
                    "this 法人番号 may be real but not yet absorbed."
                ),
                "houjin_bangou": norm,
                "alternative": (
                    "公式 gBizINFO lookup: https://info.gbiz.go.jp/hojin/ichiran?hojinBango=" + norm
                ),
                "_disclaimer": _DISCLAIMER,
                "_namayoke_caveat": _NAMAYOKE_CAVEAT,
            },
        )

    _attach_gbiz_attribution(body, norm)
    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "houjin.get",
        latency_ms=_latency_ms,
        # houjin_bangou is PII-adjacent (it identifies a specific business);
        # keep it OUT of params_digest. The endpoint name + status are what
        # the SLA / freshness dashboard needs.
        params={"hit": True},
        strict_metering=True,
    )
    # §17.D audit seal on paid responses (no-op for anon).
    attach_seal_to_body(
        body,
        endpoint="houjin.get",
        request_params={"bangou": norm},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    if wants_envelope_v2(request):
        _mark_envelope_v2_served(request)
        provenance = body.get("provenance") or {}
        attribution = body.get("_attribution") or {}
        citations = []
        if attribution.get("source_url"):
            citations.append(
                {
                    "source_url": attribution.get("source_url"),
                    "publisher": attribution.get("publisher") or GBIZ_PUBLISHER_NAME,
                    "title": f"{GBIZ_SOURCE_NAME} 法人情報",
                    "fetched_at": attribution.get("fetched_at"),
                    "license": attribution.get("license") or GBIZ_LICENSE_NAME,
                    "license_url": attribution.get("license_url") or GBIZ_LICENSE_URL,
                    "upstream_source": attribution.get("upstream_source"),
                    "citation_text_ja": attribution_disclaimer_short(),
                    "field_paths": ["/results/0/basic", "/results/0/corp_facts"],
                    "verification_status": "unknown",
                    "verification_basis": "local_catalog",
                    "live_verified_at_request": False,
                }
            )
        elif provenance.get("primary_source"):
            citations.append(
                {
                    "source_url": provenance.get("primary_source"),
                    "publisher": "gBizINFO / jpcite mirror",
                    "title": "Corporate 360 public-source snapshot",
                    "fetched_at": provenance.get("fetched_at"),
                    "verification_status": "unknown",
                    "verification_basis": "local_catalog",
                    "live_verified_at_request": False,
                }
            )
        env = StandardResponse.sparse(
            [body],
            request_id=safe_request_id(request),
            citations=citations,
            query_echo={
                "normalized_input": {"bangou": norm},
                "applied_filters": {"bangou": norm},
                "unparsed_terms": [],
            },
            latency_ms=_latency_ms,
            billable_units=1,
            client_tag=getattr(request.state, "client_tag", None),
        )
        return JSONResponse(
            content=env.to_wire(),
            headers={"X-Envelope-Version": "v2"},
        )
    return JSONResponse(content=body)
