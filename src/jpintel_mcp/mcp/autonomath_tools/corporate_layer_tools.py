"""corporate_layer_tools — P12 §4.8 corporate-layer differentiation (3 tools, 2026-05-04).

Three new MCP tools that widen the corporate layer (closest competitor
ground vs. yamariki-hub/japan-corporate-mcp). Each tool emits the same
contract as Wave 22:

  * ``results`` (list) + ``total`` / ``limit`` / ``offset`` envelope
  * ``_disclaimer`` for §52 / §72 sensitive surfaces (法人 / 適格事業者
    information is in 税理士 / 弁護士 advisory territory)
  * ``_next_calls`` (compound multiplier mechanism)
  * ``corpus_snapshot_id`` + ``corpus_checksum`` (auditor reproducibility)

Tools shipped here
------------------

  get_houjin_360_am
      Given 法人番号, returns 360 view (法人 master + 適格事業者 status +
      行政処分 count + 採択履歴 count + 関連 program count). Composes
      jpi_houjin_master + jpi_invoice_registrants + am_enforcement_detail
      + jpi_adoption_records into a single envelope. NO LLM. Sensitive
      (§52 — 与信判断 / 税務助言 territory).

  list_edinet_disclosures
      Given 法人番号 or sec_code, returns latest disclosure list from
      EDINET (金融庁 有価証券報告書) public API. Stub-only catalogue
      pointer (no live HTTP calls — surfaces the canonical EDINET URL +
      catalogue search hint so the customer LLM can drill in itself).
      EDINET is a public 一次資料 (license: public_domain). NOT sensitive
      — pure pointer, no advice.

  search_invoice_by_houjin_partial
      Given partial 法人名 query, returns top N matching 適格請求書発行
      事業者 (NTA bulk, PDL v1.0). Partial substring LIKE on normalized_name
      with PDL v1.0 attribution baked into the response. Sensitive (§52
      — invoice 仕入税額控除 確定判断 territory).

NO Anthropic API self-call — pure SQL / Python over autonomath.db.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import close_all, connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.corporate_layer")

# Env-gated registration (default on). Flip to "0" for one-flag rollback
# if a regression surfaces post-launch.
_ENABLED = (
    get_flag("JPCITE_CORPORATE_LAYER_ENABLED", "AUTONOMATH_CORPORATE_LAYER_ENABLED", "1") == "1"
)
_JST = datetime.timezone(datetime.timedelta(hours=9))


# ---------------------------------------------------------------------------
# Disclaimers (§52 / §72 fence — see envelope_wrapper.SENSITIVE_TOOLS).
# ---------------------------------------------------------------------------

_DISCLAIMER_HOUJIN_360 = (
    "本 response は jpi_houjin_master + jpi_invoice_registrants + "
    "am_enforcement_detail + jpi_adoption_records の機械的 join による "
    "法人 360° view で、信用調査・反社チェック・税務代理 (税理士法 §52) "
    "・与信判断 (弁護士法 §72) の代替ではありません。商号変更・合併・"
    "事業譲渡 等のイベント前後では同一番号下に異なる時点情報が混在 "
    "する場合があります。最新登記情報は法務局・gBizINFO 一次サイトでご確認ください。"
)

_DISCLAIMER_INVOICE_PARTIAL = (
    "本 response は国税庁適格請求書発行事業者公表サイト (PDL v1.0) の "
    "partial substring 検索結果で、仕入税額控除の確定判断 (税理士法 §52) "
    "は提供しません。NTA への登録状況は本 API ではなく、発行元サイト "
    "(https://www.invoice-kohyo.nta.go.jp/) で最新を必ず確認してください。"
)


# ---------------------------------------------------------------------------
# PDL v1.0 attribution block (mirror of api/invoice_registrants.py).
# ---------------------------------------------------------------------------

_PDL_ATTRIBUTION: dict[str, Any] = {
    "source": "国税庁適格請求書発行事業者公表サイト（国税庁）",
    "source_url": "https://www.invoice-kohyo.nta.go.jp/",
    "license": "公共データ利用規約 第1.0版 (PDL v1.0)",
    "edited": True,
    "notice": (
        "本データは国税庁公表データを編集加工したものであり、原データと完全には一致しません。"
        "公表データは本API経由ではなく、発行元サイトで最新のものを確認してください。"
    ),
}


# ---------------------------------------------------------------------------
# EDINET (金融庁 有価証券報告書) static reference points.
#
# We do NOT make live HTTP calls inside MCP tools (CI guard
# tests/test_no_llm_in_production.py forbids any external API call from
# this surface). Instead we return a stable pointer envelope so the
# customer LLM can guide the user to the canonical EDINET search.
# ---------------------------------------------------------------------------

_EDINET_BASE = "https://disclosure2.edinet-fsa.go.jp"
_EDINET_DOC_LIST = f"{_EDINET_BASE}/api/v2/documents.json"
_EDINET_HUMAN_SEARCH = f"{_EDINET_BASE}/WEEK0010.aspx"
_EDINET_LICENSE = "public_domain"
_EDINET_SOURCE_LABEL = "EDINET（金融庁・電子開示システム）"


# ---------------------------------------------------------------------------
# Reproducibility — corpus_snapshot_id + corpus_checksum (mirrors wave22).
# ---------------------------------------------------------------------------

_SNAPSHOT_TTL_SECONDS = 300.0
_SNAPSHOT_CACHE: dict[str, tuple[float, str, str]] = {}

_SNAPSHOT_TABLES: tuple[str, ...] = (
    "jpi_houjin_master",
    "jpi_invoice_registrants",
    "am_enforcement_detail",
    "jpi_adoption_records",
)


def _compute_corpus_snapshot(conn: sqlite3.Connection) -> tuple[str, str]:
    """Return (corpus_snapshot_id, corpus_checksum) for the corporate corpus.

    Caches per-process for 5 minutes. Same shape as wave22 so MCP and
    REST surface the same identity for a given moment.
    """
    cache_key = "corporate_layer"
    now_mono = datetime.datetime.now().timestamp()
    cached = _SNAPSHOT_CACHE.get(cache_key)
    if cached is not None and cached[0] > now_mono:
        return cached[1], cached[2]

    snapshot_id: str | None = None
    candidates: list[str] = []
    for table, expr in (
        ("jpi_invoice_registrants", "MAX(fetched_at)"),
        ("jpi_houjin_master", "MAX(fetched_at)"),
        ("am_enforcement_detail", "MAX(source_fetched_at)"),
        ("jpi_adoption_records", "MAX(announced_at)"),
        ("am_entities", "MAX(fetched_at)"),
    ):
        try:
            # B608 false positive: `table` and `expr` are from controlled internal whitelists
            # (the for-loop literal tuples above), never from user input.
            row = conn.execute(f"SELECT {expr} FROM {table}").fetchone()  # nosec B608
            if row and row[0]:
                candidates.append(str(row[0]))
        except sqlite3.Error:
            continue
    snapshot_id = max(candidates) if candidates else "1970-01-01T00:00:00Z"

    counts: list[int] = []
    for table in _SNAPSHOT_TABLES:
        try:
            # B608 false positive: `table` is from the _SNAPSHOT_TABLES module-level whitelist.
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # nosec B608
            counts.append(int(row[0]) if row and row[0] is not None else 0)
        except sqlite3.Error:
            counts.append(0)

    api_version = "v0.3.3"
    digest_input = (f"{snapshot_id}|{api_version}|{','.join(str(c) for c in counts)}").encode()
    checksum = "sha256:" + hashlib.sha256(digest_input).hexdigest()[:16]

    _SNAPSHOT_CACHE[cache_key] = (
        now_mono + _SNAPSHOT_TTL_SECONDS,
        snapshot_id,
        checksum,
    )
    return snapshot_id, checksum


def _attach_snapshot(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:
    """Inject corpus_snapshot_id + corpus_checksum keys onto `body`."""
    snapshot_id, checksum = _compute_corpus_snapshot(conn)
    body["corpus_snapshot_id"] = snapshot_id
    body["corpus_checksum"] = checksum
    return body


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db, returning either a conn or an error envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["search_programs"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_programs"],
        )


def _normalize_houjin(value: str) -> str:
    """Strip whitespace + leading 'T' (invoice registration prefix).

    Returns the 13-digit candidate; caller validates via isdigit + len ==
    13 before issuing a SQL probe.
    """
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    # Strip common formatting separators that callers may include.
    for ch in ("-", " ", "　", ","):
        s = s.replace(ch, "")
    return s


def _parse_iso_date(value: Any) -> datetime.date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _invoice_is_active(
    registered_date: Any,
    revoked_date: Any,
    expired_date: Any,
    *,
    today: datetime.date | None = None,
) -> bool:
    """Return NTA invoice active status as of JST today.

    Future registrations are not active yet. Revocation / expiry dates on or
    before today mean inactive. Missing registered_date is treated as
    inactive because the effective start date is not provable.
    """
    today = today or datetime.datetime.now(_JST).date()
    registered = _parse_iso_date(registered_date)
    revoked = _parse_iso_date(revoked_date)
    expired = _parse_iso_date(expired_date)
    if registered is None or registered > today:
        return False
    if revoked is not None and revoked <= today:
        return False
    return not (expired is not None and expired <= today)


# ---------------------------------------------------------------------------
# 1) get_houjin_360_am
# ---------------------------------------------------------------------------


def _get_houjin_360_impl(houjin_bangou: str) -> dict[str, Any]:
    """Pure SQL: jpi_houjin_master + jpi_invoice_registrants +
    am_enforcement_detail + jpi_adoption_records → 360 view envelope.

    NO LLM. Pure rollup join.
    """
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号 with or without 'T' prefix).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
            hint="国税庁 法人番号公表サイトの 13 桁 (チェックディジット含む) を渡してください.",
        )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Master row -------------------------------------------------------
    master_row: sqlite3.Row | None = None
    try:
        master_row = conn.execute(
            """
            SELECT houjin_bangou, normalized_name, prefecture, municipality,
                   address_normalized, corporation_type, established_date,
                   close_date, last_updated_nta, total_adoptions,
                   total_received_yen, fetched_at
              FROM jpi_houjin_master
             WHERE houjin_bangou = ?
            """,
            (hb,),
        ).fetchone()
    except sqlite3.Error:
        master_row = None

    master_info: dict[str, Any] | None = None
    if master_row is not None:
        master_info = {
            "houjin_bangou": master_row["houjin_bangou"],
            "normalized_name": master_row["normalized_name"],
            "prefecture": master_row["prefecture"],
            "municipality": master_row["municipality"],
            "address_normalized": master_row["address_normalized"],
            "corporation_type": master_row["corporation_type"],
            "established_date": master_row["established_date"],
            "close_date": master_row["close_date"],
            "last_updated_nta": master_row["last_updated_nta"],
            "total_adoptions": master_row["total_adoptions"],
            "total_received_yen": master_row["total_received_yen"],
            "fetched_at": master_row["fetched_at"],
        }

    # --- Invoice status ---------------------------------------------------
    invoice_status: dict[str, Any] | None = None
    try:
        inv_row = conn.execute(
            """
            SELECT invoice_registration_number, registered_date,
                   revoked_date, expired_date, prefecture, registrant_kind,
                   normalized_name, source_url, fetched_at
              FROM jpi_invoice_registrants
             WHERE houjin_bangou = ?
             ORDER BY registered_date DESC
             LIMIT 1
            """,
            (hb,),
        ).fetchone()
        if inv_row is not None:
            is_active = _invoice_is_active(
                inv_row["registered_date"],
                inv_row["revoked_date"],
                inv_row["expired_date"],
            )
            invoice_status = {
                "invoice_registration_number": inv_row["invoice_registration_number"],
                "registered_date": inv_row["registered_date"],
                "revoked_date": inv_row["revoked_date"],
                "expired_date": inv_row["expired_date"],
                "prefecture": inv_row["prefecture"],
                "registrant_kind": inv_row["registrant_kind"],
                "normalized_name": inv_row["normalized_name"],
                "is_active": is_active,
                "source_url": inv_row["source_url"],
                "fetched_at": inv_row["fetched_at"],
            }
    except sqlite3.Error:
        invoice_status = None

    # --- Enforcement count + recent kinds ---------------------------------
    enforcement_count = 0
    recent_enforcement: list[dict[str, Any]] = []
    try:
        enf_count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_enforcement_detail WHERE houjin_bangou = ?",
            (hb,),
        ).fetchone()
        enforcement_count = enf_count_row["n"] if enf_count_row else 0

        if enforcement_count > 0:
            for r in conn.execute(
                """
                SELECT enforcement_kind, issuing_authority, issuance_date,
                       amount_yen, reason_summary, source_url
                  FROM am_enforcement_detail
                 WHERE houjin_bangou = ?
                 ORDER BY COALESCE(issuance_date, '') DESC
                 LIMIT 5
                """,
                (hb,),
            ).fetchall():
                recent_enforcement.append(
                    {
                        "enforcement_kind": r["enforcement_kind"],
                        "issuing_authority": r["issuing_authority"],
                        "issuance_date": r["issuance_date"],
                        "amount_yen": r["amount_yen"],
                        "reason_summary": r["reason_summary"],
                        "source_url": r["source_url"],
                    }
                )
    except sqlite3.Error:
        enforcement_count = 0

    # --- Adoption count + recent rounds -----------------------------------
    adoption_count = 0
    recent_adoptions: list[dict[str, Any]] = []
    related_program_ids: set[str] = set()
    try:
        ad_count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM jpi_adoption_records WHERE houjin_bangou = ?",
            (hb,),
        ).fetchone()
        adoption_count = ad_count_row["n"] if ad_count_row else 0

        if adoption_count > 0:
            for r in conn.execute(
                """
                SELECT program_name_raw, program_id_hint, round_label,
                       announced_at, amount_granted_yen, source_url
                  FROM jpi_adoption_records
                 WHERE houjin_bangou = ?
                 ORDER BY COALESCE(announced_at, '') DESC
                 LIMIT 5
                """,
                (hb,),
            ).fetchall():
                recent_adoptions.append(
                    {
                        "program_name": r["program_name_raw"],
                        "program_id_hint": r["program_id_hint"],
                        "round_label": r["round_label"],
                        "announced_at": r["announced_at"],
                        "amount_granted_yen": r["amount_granted_yen"],
                        "source_url": r["source_url"],
                    }
                )
                if r["program_id_hint"]:
                    related_program_ids.add(r["program_id_hint"])

            # Fan out the full distinct program_id_hint set so the
            # related_programs_count rollup is honest (LIMIT 5 above is for
            # surfacing rows; the count uses the full distinct set).
            for r in conn.execute(
                """
                SELECT DISTINCT program_id_hint
                  FROM jpi_adoption_records
                 WHERE houjin_bangou = ? AND program_id_hint IS NOT NULL
                """,
                (hb,),
            ).fetchall():
                if r["program_id_hint"]:
                    related_program_ids.add(r["program_id_hint"])
    except sqlite3.Error:
        adoption_count = 0

    related_programs_count = len(related_program_ids)

    # --- 404 hint when nothing matched ------------------------------------
    if (
        master_info is None
        and invoice_status is None
        and enforcement_count == 0
        and adoption_count == 0
    ):
        out_miss: dict[str, Any] = {
            "houjin_bangou": hb,
            "results": [],
            "total": 0,
            "limit": 1,
            "offset": 0,
            "master_info": None,
            "invoice_status": None,
            "enforcement_count": 0,
            "adoption_count": 0,
            "related_programs_count": 0,
            "data_quality": {
                "houjin_corpus_total": 166765,
                "invoice_corpus_total": 13801,
                "enforcement_corpus_total": 22258,
                "adoption_corpus_total": 201845,
                "caveat": (
                    "no rows matched in any of the 4 corporate corpora. "
                    "law of the matter: 法人番号 公表サイトに存在するが当社 "
                    "snapshot 未取込の可能性 — 一次サイトでご確認ください."
                ),
                "official_lookup_url": "https://www.houjin-bangou.nta.go.jp/",
            },
            "_disclaimer": _DISCLAIMER_HOUJIN_360,
            "_next_calls": [
                {
                    "tool": "search_invoice_by_houjin_partial",
                    "args": {"name_query": "<known 法人名>"},
                    "rationale": (
                        "If 13-digit 法人番号 has no hit, try a partial 法人名 "
                        "search to recover the canonical entity id."
                    ),
                    "compound_mult": 1.3,
                },
            ],
        }
        return _attach_snapshot(conn, out_miss)

    # --- Compose results --------------------------------------------------
    results: list[dict[str, Any]] = []
    if master_info is not None:
        results.append(
            {
                "kind": "master_info",
                "value": master_info,
            }
        )
    if invoice_status is not None:
        results.append(
            {
                "kind": "invoice_status",
                "value": invoice_status,
            }
        )
    if enforcement_count > 0:
        results.append(
            {
                "kind": "enforcement_summary",
                "value": {
                    "count": enforcement_count,
                    "recent": recent_enforcement,
                },
            }
        )
    if adoption_count > 0:
        results.append(
            {
                "kind": "adoption_summary",
                "value": {
                    "count": adoption_count,
                    "recent": recent_adoptions,
                    "related_programs_count": related_programs_count,
                },
            }
        )

    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "results": results,
        "total": len(results),
        "limit": len(results) or 1,
        "offset": 0,
        "master_info": master_info,
        "invoice_status": invoice_status,
        "enforcement_count": enforcement_count,
        "adoption_count": adoption_count,
        "related_programs_count": related_programs_count,
        "recent_enforcement": recent_enforcement,
        "recent_adoptions": recent_adoptions,
        "data_quality": {
            "houjin_corpus_total": 166765,
            "invoice_corpus_total": 13801,
            "enforcement_corpus_total": 22258,
            "adoption_corpus_total": 201845,
            "caveat": (
                "360 view is a join over 4 corpora. Counts are exact for "
                "this snapshot; recent_* lists are capped at 5 rows. "
                "Use related_programs to drill into eligibility chains."
            ),
        },
        "_disclaimer": _DISCLAIMER_HOUJIN_360,
        "_next_calls": [
            {
                "tool": "match_due_diligence_questions",
                "args": {"houjin_bangou": hb, "deck_size": 40},
                "rationale": (
                    "360 view surfaces what we know; DD deck surfaces what to confirm next."
                ),
                "compound_mult": 2.0,
            },
            {
                "tool": "cross_check_jurisdiction",
                "args": {"houjin_bangou": hb},
                "rationale": (
                    "Compare 法務局 vs NTA 適格事業者 vs 採択 jurisdiction "
                    "for tax-residency / 事業所税 due diligence."
                ),
                "compound_mult": 1.6,
            },
            {
                "tool": "list_edinet_disclosures",
                "args": {"houjin_bangou": hb},
                "rationale": (
                    "Surface latest 有価証券報告書 / 大量保有報告書 disclosures "
                    "for 上場企業 — orthogonal to 補助金 corpus."
                ),
                "compound_mult": 1.4,
            },
        ],
    }
    return _attach_snapshot(conn, out)


# ---------------------------------------------------------------------------
# 2) list_edinet_disclosures
# ---------------------------------------------------------------------------


def _list_edinet_disclosures_impl(
    houjin_bangou: str | None = None,
    sec_code: str | None = None,
) -> dict[str, Any]:
    """Pointer-only EDINET disclosure surface.

    EDINET (金融庁 電子開示システム) is a public 一次資料 (license:
    public_domain). MCP tools must NOT make external HTTP calls (CI
    guard tests/test_no_llm_in_production.py forbids it). Instead this
    tool returns a stable pointer envelope so the customer LLM can guide
    the user to the canonical EDINET search with concrete query
    parameters.

    NOT sensitive — pure pointer, no advice. The customer LLM is
    responsible for fetching live EDINET data via their own client when
    they need it (or jpcite ingest will surface them via the upcoming
    edinet_disclosures table once the ingest pipeline lands).
    """
    if not (houjin_bangou or sec_code):
        return make_error(
            code="missing_required_arg",
            message="One of houjin_bangou (13-digit) or sec_code (4-digit) is required.",
            field="houjin_bangou",
            hint="EDINET indexes 上場企業 by sec_code; 非上場 公益法人 by 法人番号.",
        )

    hb: str | None = None
    if houjin_bangou:
        hb_candidate = _normalize_houjin(houjin_bangou)
        if not (hb_candidate.isdigit() and len(hb_candidate) == 13):
            return make_error(
                code="invalid_enum",
                message=f"houjin_bangou must be 13 digits (got {hb_candidate!r}).",
                field="houjin_bangou",
            )
        hb = hb_candidate

    sc: str | None = None
    if sec_code:
        sc_clean = (sec_code or "").strip()
        # Accept 4-digit (legacy) or 5-digit (post-2024 standardized) codes.
        if not (sc_clean.isdigit() and len(sc_clean) in (4, 5)):
            return make_error(
                code="invalid_enum",
                message=f"sec_code must be 4-5 digits (got {sc_clean!r}).",
                field="sec_code",
                hint="証券コードは 4 桁 (旧) または 5 桁 (2024年以降) の数字です.",
            )
        sc = sc_clean

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Resolve human-friendly search URL --------------------------------
    # EDINET's WEEK0010.aspx accepts ekey (証券コード) + edinetCode etc. We
    # surface the canonical search root with both 法人番号 and sec_code as
    # query hints so the LLM can render a click-through link.
    search_url = _EDINET_HUMAN_SEARCH
    api_query: dict[str, Any] = {
        "type": 2,  # 有価証券報告書 / 半期 / 四半期 等
    }
    if sc:
        api_query["secCode"] = sc
        search_url = f"{_EDINET_HUMAN_SEARCH}?ekey={sc}"
    elif hb:
        api_query["houjinBangou"] = hb

    # --- Resolve corporate name from autonomath corpus (best-effort) ------
    resolved_name: str | None = None
    if hb:
        try:
            row = conn.execute(
                "SELECT normalized_name FROM jpi_houjin_master WHERE houjin_bangou = ?",
                (hb,),
            ).fetchone()
            if row:
                resolved_name = row["normalized_name"]
        except sqlite3.Error:
            resolved_name = None

    # --- Compose pointer envelope -----------------------------------------
    # Each "result" is a pointer to a canonical EDINET endpoint the
    # customer can hit themselves. We do NOT proxy the EDINET API.
    results: list[dict[str, Any]] = [
        {
            "kind": "edinet_search_human",
            "label": "EDINET 検索ページ (人間向け)",
            "url": search_url,
            "license": _EDINET_LICENSE,
            "source_label": _EDINET_SOURCE_LABEL,
            "instruction_ja": (
                "ブラウザで開き、提出書類一覧から最新の有価証券報告書 / "
                "半期報告書 / 四半期報告書 / 大量保有報告書を選択してください."
            ),
        },
        {
            "kind": "edinet_documents_api",
            "label": "EDINET API v2 (documents.json) — 機械可読",
            "url": _EDINET_DOC_LIST,
            "license": _EDINET_LICENSE,
            "source_label": _EDINET_SOURCE_LABEL,
            "query_hint": api_query,
            "instruction_ja": (
                "EDINET API v2 documents.json を `date=YYYY-MM-DD&type=2` "
                "で日次取得し、得られた docID から書類本文 (PDF/XBRL) を "
                "取得します. API トークン不要 (公開 API)."
            ),
            "documentation_url": "https://disclosure2.edinet-fsa.go.jp/weee0020.aspx",
        },
    ]

    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "sec_code": sc,
        "resolved_name": resolved_name,
        "results": results,
        "total": len(results),
        "limit": len(results),
        "offset": 0,
        "data_quality": {
            "method": "pointer_only",
            "live_fetch_inside_tool": False,
            "license": _EDINET_LICENSE,
            "caveat": (
                "本 tool は EDINET の canonical URL + API クエリ hint を "
                "返す pointer-only サーフェスで、書類本文の取得は customer "
                "LLM 側で行ってください. EDINET は API 利用料無料・トークン "
                "不要・public_domain license です."
            ),
        },
        "_next_calls": [
            *(
                [
                    {
                        "tool": "get_houjin_360_am",
                        "args": {"houjin_bangou": hb},
                        "rationale": (
                            "Pair EDINET disclosure pointer with the 法人 360 view "
                            "(invoice / enforcement / adoption rollup)."
                        ),
                        "compound_mult": 1.6,
                    }
                ]
                if hb
                else []
            ),
            {
                "tool": "search_invoice_by_houjin_partial",
                "args": {"name_query": resolved_name or "<法人名>"},
                "rationale": (
                    "If sec_code only, use the resolved name to look up "
                    "the corresponding 適格事業者 number."
                ),
                "compound_mult": 1.3,
            },
        ],
    }
    return _attach_snapshot(conn, out)


# ---------------------------------------------------------------------------
# 3) search_invoice_by_houjin_partial
# ---------------------------------------------------------------------------


def _search_invoice_by_houjin_partial_impl(
    name_query: str,
    limit: int = 20,
    active_only: bool = True,
) -> dict[str, Any]:
    """Pure SQL: substring LIKE on jpi_invoice_registrants.normalized_name.

    Returns top-N matches with PDL v1.0 attribution baked in. Sensitive
    (§52 — 仕入税額控除 確定判断 territory).
    """
    if not name_query or not isinstance(name_query, str):
        return make_error(
            code="missing_required_arg",
            message="name_query is required (partial 法人名).",
            field="name_query",
        )
    q = (name_query or "").strip()
    if len(q) < 2:
        return make_error(
            code="invalid_enum",
            message="name_query must be at least 2 characters.",
            field="name_query",
            hint="2 文字以上の partial 法人名 (株式会社 等の suffix も含む) を渡してください.",
        )
    limit = max(1, min(int(limit) if isinstance(limit, int) else 20, 50))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Build WHERE ------------------------------------------------------
    where_clauses: list[str] = ["normalized_name LIKE ?"]
    params: list[Any] = [f"%{q}%"]
    if active_only:
        today = datetime.datetime.now(_JST).date().isoformat()
        where_clauses.append("registered_date IS NOT NULL")
        where_clauses.append("registered_date <= ?")
        where_clauses.append("(revoked_date IS NULL OR revoked_date > ?)")
        where_clauses.append("(expired_date IS NULL OR expired_date > ?)")
        params.extend([today, today, today])
    where_sql = " AND ".join(where_clauses)

    # --- Fetch matches (partial inside-string LIKE; capped at LIMIT) -----
    # Note: prefix LIKE 'q%' is index-eligible on idx_invoice_registrants_name,
    # but %q% is NOT — caller often wants substring match (e.g. "ブッキ").
    # We accept the full table scan cost up to LIMIT — corpus is 13,801
    # rows in the delta snapshot, ~4M rows post-monthly-bulk. For the
    # post-bulk scale we will need an FTS5 index; tracked in the runbook.
    try:
        # B608 false positive: `where_sql` is built from the local-only
        # `where_clauses` list (literal SQL fragments above with bound `?`
        # placeholders), never from user input. Every user value goes
        # through `params` and is bound, not interpolated.
        rows = conn.execute(
            f"""
            SELECT invoice_registration_number, houjin_bangou,
                   normalized_name, prefecture, registered_date,
                   revoked_date, expired_date, registrant_kind,
                   trade_name, last_updated_nta, source_url, fetched_at
              FROM jpi_invoice_registrants
             WHERE {where_sql}
             ORDER BY registered_date DESC
             LIMIT ?
            """,  # nosec B608
            (*params, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("search_invoice_by_houjin_partial query failed")
        with contextlib.suppress(sqlite3.Error):
            close_all()
        return make_error(
            code="db_unavailable",
            message=f"jpi_invoice_registrants query failed: {exc}",
        )

    matches: list[dict[str, Any]] = [
        {
            "invoice_registration_number": r["invoice_registration_number"],
            "houjin_bangou": r["houjin_bangou"],
            "normalized_name": r["normalized_name"],
            "prefecture": r["prefecture"],
            "registered_date": r["registered_date"],
            "revoked_date": r["revoked_date"],
            "expired_date": r["expired_date"],
            "registrant_kind": r["registrant_kind"],
            "trade_name": r["trade_name"],
            "is_active": _invoice_is_active(
                r["registered_date"],
                r["revoked_date"],
                r["expired_date"],
            ),
            "last_updated_nta": r["last_updated_nta"],
            "source_url": r["source_url"],
            "fetched_at": r["fetched_at"],
        }
        for r in rows
    ]

    out: dict[str, Any] = {
        "name_query": q,
        "results": matches,
        "total": len(matches),
        "limit": limit,
        "offset": 0,
        "active_only": active_only,
        "attribution": _PDL_ATTRIBUTION,
        "data_quality": {
            "invoice_corpus_total": 13801,
            "match_strategy": "substring LIKE %q% on normalized_name",
            "caveat": (
                "Substring LIKE — non-index-eligible scan. "
                "When invoice_registrants reaches 4M rows (post-monthly-bulk), "
                "this scan will be slower; future migration may add FTS5. "
                "Hard cap at limit=50 keeps response bounded."
            ),
            "official_lookup_url": "https://www.invoice-kohyo.nta.go.jp/regno-search/",
        },
        "_disclaimer": _DISCLAIMER_INVOICE_PARTIAL,
        "_next_calls": [
            {
                "tool": "get_houjin_360_am",
                "args": {
                    "houjin_bangou": (
                        matches[0]["houjin_bangou"]
                        if matches and matches[0]["houjin_bangou"]
                        else "<13-digit 法人番号>"
                    ),
                },
                "rationale": (
                    "Top match → 360 view (master + invoice + enforcement "
                    "+ adoption rollup) for the candidate counterparty."
                ),
                "compound_mult": 1.8,
            },
            {
                "tool": "match_due_diligence_questions",
                "args": {
                    "houjin_bangou": (
                        matches[0]["houjin_bangou"]
                        if matches and matches[0]["houjin_bangou"]
                        else "<13-digit 法人番号>"
                    ),
                    "deck_size": 30,
                },
                "rationale": (
                    "Counterparty resolved → DD deck for 仕入税額控除 確定 "
                    "前の confirm step (registration + invoicability)."
                ),
                "compound_mult": 1.5,
            },
        ],
    }
    return _attach_snapshot(conn, out)


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_CORPORATE_LAYER_ENABLED + the
# global AUTONOMATH_ENABLED. Each @mcp.tool docstring is ≤ 400 chars per
# the Wave 21 / Wave 22 / Wave 23 convention.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def get_houjin_360_am(
        houjin_bangou: Annotated[
            str,
            Field(
                description=("13-digit 法人番号 (with or without 'T' prefix)."),
            ),
        ],
    ) -> dict[str, Any]:
        """[CORPORATE-LAYER] 法人 360° view by 法人番号 — joins jpi_houjin_master + jpi_invoice_registrants + am_enforcement_detail + jpi_adoption_records into a single envelope. Surfaces master_info + invoice_status + enforcement_count + adoption_count + related_programs_count. NO LLM. §52 sensitive — 与信判断 / 税務助言 territory."""
        return _get_houjin_360_impl(houjin_bangou=houjin_bangou)

    @mcp.tool(annotations=_READ_ONLY)
    def list_edinet_disclosures(
        houjin_bangou: Annotated[
            str | None,
            Field(
                description=("13-digit 法人番号. One of houjin_bangou or sec_code required."),
            ),
        ] = None,
        sec_code: Annotated[
            str | None,
            Field(
                description=("4-5 digit 証券コード (post-2024 standardized = 5 digit)."),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[CORPORATE-LAYER] EDINET (金融庁 電子開示) disclosure pointer — returns canonical search URL + API v2 query hint for 有価証券報告書 / 大量保有報告書 etc. Pointer-only (NO live HTTP inside tool). License public_domain. NOT sensitive — pure pointer, no advice; customer LLM fetches body itself."""
        return _list_edinet_disclosures_impl(
            houjin_bangou=houjin_bangou,
            sec_code=sec_code,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def search_invoice_by_houjin_partial(
        name_query: Annotated[
            str,
            Field(
                description=(
                    "Partial 法人名 (≥ 2 chars). Substring match against "
                    "normalized_name (株式会社 / suffix 含む可)."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=50,
                description="Max matches (1-50). Default 20.",
            ),
        ] = 20,
        active_only: Annotated[
            bool,
            Field(
                description=("When true (default), excludes revoked / expired registrants."),
            ),
        ] = True,
    ) -> dict[str, Any]:
        """[CORPORATE-LAYER] Partial 法人名 search across NTA 適格請求書発行事業者 (PDL v1.0 bulk). Substring LIKE on normalized_name with 出典明記 + 編集・加工注記 attribution baked into every response. Returns top-N matches with houjin_bangou + status + last_update. §52 sensitive — 仕入税額控除 確定判断 territory."""
        return _search_invoice_by_houjin_partial_impl(
            name_query=name_query,
            limit=limit,
            active_only=active_only,
        )


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.corporate_layer_tools
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    print("\n=== get_houjin_360_am ===")
    res = _get_houjin_360_impl(houjin_bangou="3450001000777")
    pprint.pprint(
        {
            "total": res.get("total"),
            "master_info_present": res.get("master_info") is not None,
            "invoice_status_present": res.get("invoice_status") is not None,
            "enforcement_count": res.get("enforcement_count"),
            "adoption_count": res.get("adoption_count"),
            "related_programs_count": res.get("related_programs_count"),
            "next_calls_count": len(res.get("_next_calls", [])),
            "snapshot_id": res.get("corpus_snapshot_id"),
        }
    )

    print("\n=== list_edinet_disclosures ===")
    res = _list_edinet_disclosures_impl(houjin_bangou="3450001000777")
    pprint.pprint(
        {
            "total": res.get("total"),
            "resolved_name": res.get("resolved_name"),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== search_invoice_by_houjin_partial ===")
    res = _search_invoice_by_houjin_partial_impl(name_query="株式会社")
    pprint.pprint(
        {
            "total": res.get("total"),
            "first_match_name": (
                res.get("results", [{}])[0].get("normalized_name") if res.get("results") else None
            ),
            "attribution_present": "attribution" in res,
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )
