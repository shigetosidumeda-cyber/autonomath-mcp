"""program_abstract_structured — R7 multilingual abstract MCP tool.

Returns a closed-vocabulary, audience-targeted abstract of a single
``programs`` row in **the original Japanese only**. Translation is handled by
the caller's LLM or translation pipeline; this tool does not perform
request-time translation.

Why structured + Japanese-only
------------------------------
- ¥1/req metered pricing forbids server-side LLM inference. The
  customer pays for their own translation pass.
- Closed-vocab JSON (``ISO-style`` enums) lets the customer LLM
  *render* into any language without re-deriving semantics. The
  enums are stable across renders, so ``business_type_enum:
  ["corporation"]`` reliably maps to "法人", "corporation",
  "企業", "công ty" etc. on the customer side.
- ``official_name_ja`` + ``legal_id`` are **never translated** —
  the i18n_hints flag ``official_name_must_keep_ja=true`` instructs
  the customer LLM to keep them verbatim so 音訳 mismatch (e.g.
  romanizing 助成金 wrong) cannot break peg-back to JP官公庁
  documents.

Design doc: ``analysis_wave18/_r7_multilingual_abstracts_2026-04-25.md``.

Audience enum (5 values)
------------------------
- ``foreign_employer``  — 在日外国人雇用主向け制度 (191-program
  audience, the launch use case)
- ``smb``              — 中小企業全般
- ``tax_advisor``      — 税理士向け (税制優遇 / 損金算入要件)
- ``admin_scrivener``  — 行政書士向け (許認可 / 申請代行)
- ``vc``               — VC / 投資家向け (R&D + GX + IPO 関連)

Response shape
--------------
::

    {
      "program_id":         "UNI-...",
      "official_name_ja":   "<verbatim 日本語>",
      "legal_id":           "雇用保険法施行規則" | null,
      "summary_ja":         "<≤120 chars 日本語要約>",
      "audience":           "foreign_employer" | ...,
      "eligibility": {
        "business_type_enum":            ["sme"|"large"|"sole_proprietor"|"corporation"|...],
        "must_employ_foreign_workers":   bool,
        "must_join_employment_insurance":bool,
      },
      "amount":   { "max_man_yen": int|null, "min_man_yen": int|null, "currency": "JPY" },
      "deadline": { "cycle": "rolling"|"annual"|"multi_round"|"unknown",
                    "fiscal_year": int|null,
                    "start_date": "YYYY-MM-DD"|null,
                    "end_date":   "YYYY-MM-DD"|null },
      "documents": [ { "name_ja": str, "format": str|null, "template_url": str|null } ],
      "contact_route": "prefectural_labor_bureau" | "hello_work" | "national" | "prefecture" | "municipality" | "financial" | "unknown",
      "i18n_hints": {
        "render_languages_supported": ["en","vi","id","th","zh-CN","fil"],
        "official_name_must_keep_ja": true,
        "legal_id_must_keep_ja":      true,
        "translate_summary":          true
      },
      "source_urls": [ "<gov 一次資料 URL>" ... ],
      "_disclaimer": "<翻訳/法的責任は customer 側>"
    }
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.config import Settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.multilingual_abstract")


_AUDIENCE_VALUES = (
    "foreign_employer",
    "smb",
    "tax_advisor",
    "admin_scrivener",
    "vc",
)

# ISO-stable render targets. customer LLM picks one; we don't translate.
_SUPPORTED_LANGS = ["en", "vi", "id", "th", "zh-CN", "fil"]

_DISCLAIMER = (
    "本 response は元日本語の構造化抽象です。"
    "翻訳およびその正確性は customer LLM 側の責任で実施してください。"
    "official_name_ja / legal_id は翻訳禁止 (一次資料との peg-back 維持のため)。"
    "最終的な制度該当性判断は source_urls の一次資料 + 専門家 (社労士/税理士/弁護士) 確認を優先。"
)


def _safe_json_loads(blob: Any) -> dict[str, Any]:
    if not blob:
        return {}
    if isinstance(blob, dict):
        return blob
    try:
        parsed = json.loads(blob)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _foreign_employer_signals(extraction: dict[str, Any]) -> dict[str, bool]:
    """Detect the 2 hard-rule signals for the foreign_employer audience.

    Looks at eligibility_clauses + ineligibility_v3 + obligations strings.
    Returns the 2 booleans the customer LLM needs without us hallucinating.
    """
    blob = json.dumps(extraction, ensure_ascii=False)
    must_employ_foreign = bool(
        "外国人労働者を雇用" in blob or "外国人を雇用" in blob or "外国人従業員" in blob
    )
    must_employment_insurance = bool(
        "雇用保険" in blob and "未加入" not in blob[: blob.find("雇用保険") + 200]
        if "雇用保険" in blob
        else False
    )
    return {
        "must_employ_foreign_workers": must_employ_foreign,
        "must_join_employment_insurance": must_employment_insurance,
    }


def _resolve_contact_route(extraction: dict[str, Any], authority_level: str | None) -> str:
    """Map extraction.contacts_v3 + authority_level to closed-enum route."""
    contacts_v3 = extraction.get("contacts_v3") or extraction.get("contacts") or []
    if isinstance(contacts_v3, list) and contacts_v3:
        office = (contacts_v3[0] or {}).get("office_name") or ""
        if "労働局" in office or "ハローワーク" in office:
            return "prefectural_labor_bureau"
        if "ハローワーク" in office:
            return "hello_work"
    if authority_level == "national" or authority_level == "国":
        return "national"
    if authority_level == "prefecture" or authority_level == "都道府県":
        return "prefecture"
    if authority_level == "municipality":
        return "municipality"
    if authority_level == "financial":
        return "financial"
    return "unknown"


def _extract_documents(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull a flat ≤5-entry list of {name_ja, format, template_url} docs."""
    out: list[dict[str, Any]] = []
    docs_v3 = extraction.get("documents_v3")
    legacy = (extraction.get("documents") or {}).get("__legacy__") or []
    src = docs_v3 if isinstance(docs_v3, list) and docs_v3 else legacy
    if not isinstance(src, list):
        return out
    for d in src[:5]:
        if not isinstance(d, dict):
            continue
        name = d.get("name") or d.get("name_ja")
        if not name:
            continue
        out.append(
            {
                "name_ja": name,
                "format": d.get("format"),
                "template_url": d.get("template_url"),
            }
        )
    return out


def _extract_summary(extraction: dict[str, Any], primary_name: str) -> str:
    """≤120-char Japanese summary derived from extraction (no LLM call)."""
    cls = extraction.get("classification") or {}
    excerpt = ((cls.get("_source_ref") or {}).get("excerpt") or "").strip()
    if excerpt:
        return excerpt[:120]
    money_detail = ((extraction.get("money") or {}).get("amount_detail") or "").strip()
    if money_detail:
        return money_detail[:120]
    return primary_name[:120]


def _program_abstract_structured_impl(program_id: str, audience: str) -> dict[str, Any]:
    """Pure, testable core. server.py wires the @mcp.tool decorator below."""
    if audience not in _AUDIENCE_VALUES:
        return make_error(
            code="invalid_enum",
            message=f"audience must be one of {list(_AUDIENCE_VALUES)}",
            hint="Pass audience='foreign_employer' for 在日外国人雇用主向け制度.",
            field="audience",
            extra={"allowed_values": list(_AUDIENCE_VALUES)},
        )
    if not program_id or not str(program_id).strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            hint="Pass a unified_id like 'UNI-16b8d86302'.",
            field="program_id",
        )

    db_path = Settings().db_path
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT unified_id, primary_name, authority_level, prefecture, "
            "amount_max_man_yen, amount_min_man_yen, target_types_json, "
            "enriched_json, source_url FROM programs WHERE unified_id = ? "
            "AND excluded = 0 LIMIT 1",
            (program_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.exception("program_abstract_structured db error")
        return make_error(
            code="db_unavailable",
            message=str(exc)[:120],
            hint="jpintel.db unreachable; retry later.",
            retry_with=["search_programs"],
        )
    finally:
        with contextlib.suppress(Exception):  # pragma: no cover
            conn.close()

    if row is None:
        return make_error(
            code="no_matching_records",
            message=f"program_id={program_id!r} not found in programs (or excluded).",
            hint="Use search_programs to find the unified_id first.",
            retry_with=["search_programs"],
            field="program_id",
        )

    enriched = _safe_json_loads(row["enriched_json"])
    extraction = enriched.get("extraction") or {}
    meta = enriched.get("_meta") or {}
    basic = extraction.get("basic") or {}

    # `target_types_json` is a JSON LIST like `["corporation"]`, but
    # `_safe_json_loads` strictly returns `{}` for non-dict payloads —
    # which silently maps every list to `[]`. Parse directly with
    # `json.loads` + isinstance gate so the list shape is preserved.
    raw_tt = row["target_types_json"]
    if raw_tt:
        try:
            parsed_tt = json.loads(raw_tt) if isinstance(raw_tt, (str, bytes)) else raw_tt
        except (TypeError, ValueError):
            parsed_tt = []
        target_types = parsed_tt if isinstance(parsed_tt, list) else []
    else:
        target_types = []

    eligibility: dict[str, Any] = {"business_type_enum": list(target_types)}
    if audience == "foreign_employer":
        eligibility.update(_foreign_employer_signals(extraction))

    schedule = extraction.get("schedule_v3") or extraction.get("schedule") or {}
    deadline = {
        "cycle": schedule.get("cycle") or "unknown",
        "fiscal_year": schedule.get("fiscal_year"),
        "start_date": schedule.get("start_date"),
        "end_date": schedule.get("end_date"),
    }

    source_urls = list(meta.get("source_urls") or [])
    if row["source_url"] and row["source_url"] not in source_urls:
        source_urls.insert(0, row["source_url"])

    return {
        "program_id": row["unified_id"],
        "official_name_ja": basic.get("正式名称") or row["primary_name"],
        "legal_id": basic.get("根拠法"),
        "summary_ja": _extract_summary(extraction, row["primary_name"]),
        "audience": audience,
        "eligibility": eligibility,
        "amount": {
            "max_man_yen": row["amount_max_man_yen"],
            "min_man_yen": row["amount_min_man_yen"],
            "currency": "JPY",
        },
        "deadline": deadline,
        "documents": _extract_documents(extraction),
        "contact_route": _resolve_contact_route(extraction, row["authority_level"]),
        "i18n_hints": {
            "render_languages_supported": list(_SUPPORTED_LANGS),
            "official_name_must_keep_ja": True,
            "legal_id_must_keep_ja": True,
            "translate_summary": True,
        },
        "source_urls": source_urls,
        "_disclaimer": _DISCLAIMER,
    }


@mcp.tool(annotations=_READ_ONLY)
def program_abstract_structured(
    program_id: Annotated[
        str,
        Field(
            description=(
                "unified_id of a row in programs (e.g. 'UNI-16b8d86302'). "
                "Must be excluded=0 / non-X tier."
            ),
            min_length=1,
        ),
    ],
    audience: Annotated[
        Literal[
            "foreign_employer",
            "smb",
            "tax_advisor",
            "admin_scrivener",
            "vc",
        ],
        Field(
            description=(
                "Closed-enum audience. 'foreign_employer' is the launch "
                "audience (在日外国人雇用主向け制度, ~191 programs). "
                "Other audiences reuse the same shape; audience-specific "
                "eligibility booleans are only injected when relevant."
            ),
        ),
    ] = "foreign_employer",
) -> dict[str, Any]:
    """I18N — Returns audience-targeted, closed-vocab Japanese abstract for a single program. Translation is the customer LLM's job; we never call Anthropic API. official_name_ja + legal_id must stay verbatim (i18n_hints.official_name_must_keep_ja=true). Output is search-derived; verify primary source (source_urls) for application use.

    WHAT: Reshapes ``programs.enriched_json`` into a 5-audience-aware,
    ISO-style closed-vocab JSON. Returns only original Japanese
    strings + finite enums — the customer LLM owns rendering into
    en/vi/id/th/zh-CN/fil.

    WHEN:
      - 在日外国人雇用主が雇用助成金一覧を多言語で提示したい
      - 税理士が顧問先 (外国人) に税制優遇制度を説明したい
      - VC が投資先の R&D 補助金 portfolio を英文で投資委員会に出したい

    WHEN NOT:
      - 単純な検索 → search_programs (this tool returns 1 record only)
      - 翻訳済テキストが欲しい → 呼び出し元側の LLM / 翻訳処理で実施
      - 制度の as-of 履歴 → query_at_snapshot

    Args:
      program_id: unified_id ('UNI-...').
      audience:   Closed enum, default 'foreign_employer'.

    Returns:
      JSON dict with the shape documented in the module docstring,
      or the canonical error envelope on failure.
    """
    return _program_abstract_structured_impl(program_id, audience)
