"""MCP protocol-level canonical error code statement (Wave 19 #A6).

The MCP protocol (spec rev 2025-06-18) does **not** itself standardise
domain-level error codes — it ships JSON-RPC error codes
(``-32700..-32603``) and otherwise leaves the tool author to surface
human-readable strings. This is a footgun for agent orchestrators that
want to do retry / route-around / escalate decisions without doing NLP
on prose.

We extend the REST envelope's closed enum (``api/_error_envelope.py``
``ERROR_CODES``) to the MCP layer so a single 30+ code surface covers
both transports. Each code maps to:

  - ``code`` — short closed-enum identifier
  - ``http_status`` — for REST callers
  - ``jsonrpc_code`` — for MCP / stdio callers
  - ``user_message_ja`` / ``user_message_en`` — copy
  - ``retryable`` — agent should retry vs surface to user
  - ``escalation`` — operator action required vs caller can self-heal
  - ``documentation`` — anchor URL into docs/error_handling.md

This module exposes:

  - ``CANONICAL_ERROR_CODES`` — the 30+ code dictionary
  - ``build_mcp_error_advertisement()`` — the ``_meta.error_codes``
    object that goes into the MCP capabilities advertisement
  - ``map_rest_to_jsonrpc()`` — helper that converts a REST envelope
    error to the equivalent JSON-RPC error body (for the streamable
    HTTP MCP transport)

NO LLM API import. Pure declaration + helpers.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

logger = logging.getLogger("jpintel.api.mcp_errors")

MCP_ERROR_SCHEMA = "mcp-error-codes/v1"
DOCS_BASE = "https://jpcite.com/docs/error_handling#"


class CanonicalError(TypedDict):
    """Shape of one canonical error entry."""

    code: str
    http_status: int
    jsonrpc_code: int
    user_message_ja: str
    user_message_en: str
    retryable: bool
    escalation: str
    documentation: str
    category: str


def _e(
    code: str,
    *,
    http_status: int,
    jsonrpc_code: int,
    ja: str,
    en: str,
    retryable: bool,
    escalation: str,
    category: str,
) -> CanonicalError:
    """Build one CanonicalError record."""
    return {
        "code": code,
        "http_status": http_status,
        "jsonrpc_code": jsonrpc_code,
        "user_message_ja": ja,
        "user_message_en": en,
        "retryable": retryable,
        "escalation": escalation,
        "documentation": f"{DOCS_BASE}{code}",
        "category": category,
    }


# 32 canonical codes covering the 5 axes: auth, billing, validation,
# upstream, internal. Codes are intentionally short closed enums so
# agent orchestrators can pattern-match on them across transport.
CANONICAL_ERROR_CODES: dict[str, CanonicalError] = {
    # ---- Authentication (5) -----------------------------------------
    "auth_missing": _e(
        "auth_missing",
        http_status=401,
        jsonrpc_code=-32001,
        ja="APIキーが必要です。",
        en="API key required for this endpoint.",
        retryable=False,
        escalation="caller_self_heal",
        category="auth",
    ),
    "auth_invalid": _e(
        "auth_invalid",
        http_status=401,
        jsonrpc_code=-32002,
        ja="APIキーが無効です。",
        en="API key is invalid or has been revoked.",
        retryable=False,
        escalation="caller_self_heal",
        category="auth",
    ),
    "auth_expired": _e(
        "auth_expired",
        http_status=401,
        jsonrpc_code=-32003,
        ja="APIキーの有効期限が切れています。",
        en="API key has expired.",
        retryable=False,
        escalation="caller_self_heal",
        category="auth",
    ),
    "auth_revoked": _e(
        "auth_revoked",
        http_status=401,
        jsonrpc_code=-32004,
        ja="APIキーは取り消されました。",
        en="API key has been revoked by the operator.",
        retryable=False,
        escalation="operator_action",
        category="auth",
    ),
    "auth_scope_insufficient": _e(
        "auth_scope_insufficient",
        http_status=403,
        jsonrpc_code=-32005,
        ja="このAPIキーには必要な権限がありません。",
        en="API key lacks the scope required for this operation.",
        retryable=False,
        escalation="caller_self_heal",
        category="auth",
    ),
    # ---- Billing / Quota (6) ----------------------------------------
    "quota_anon_exceeded": _e(
        "quota_anon_exceeded",
        http_status=429,
        jsonrpc_code=-32010,
        ja="本日の無料枠を使い切りました。",
        en="Anonymous daily quota exhausted. Issue an API key to continue.",
        retryable=True,
        escalation="caller_self_heal",
        category="billing",
    ),
    "quota_cap_reached": _e(
        "quota_cap_reached",
        http_status=429,
        jsonrpc_code=-32011,
        ja="月次利用上限に達しました。",
        en="Monthly cost cap reached. Raise cap to continue.",
        retryable=False,
        escalation="caller_self_heal",
        category="billing",
    ),
    "billing_card_declined": _e(
        "billing_card_declined",
        http_status=402,
        jsonrpc_code=-32012,
        ja="お支払いカードが拒否されました。",
        en="Payment method declined; update billing details.",
        retryable=False,
        escalation="caller_self_heal",
        category="billing",
    ),
    "billing_no_method": _e(
        "billing_no_method",
        http_status=402,
        jsonrpc_code=-32013,
        ja="お支払い方法が登録されていません。",
        en="No payment method on file.",
        retryable=False,
        escalation="caller_self_heal",
        category="billing",
    ),
    "billing_trial_expired": _e(
        "billing_trial_expired",
        http_status=402,
        jsonrpc_code=-32014,
        ja="トライアル期間が終了しました。",
        en="Trial period ended; add a payment method.",
        retryable=False,
        escalation="caller_self_heal",
        category="billing",
    ),
    "rate_limit_global": _e(
        "rate_limit_global",
        http_status=429,
        jsonrpc_code=-32015,
        ja="リクエストが集中しています。少し待って再試行してください。",
        en="Global rate limit hit; retry with backoff.",
        retryable=True,
        escalation="caller_self_heal",
        category="billing",
    ),
    # ---- Validation (8) ---------------------------------------------
    "validation_required_field": _e(
        "validation_required_field",
        http_status=400,
        jsonrpc_code=-32020,
        ja="必須項目が不足しています。",
        en="A required field is missing.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    "validation_type_mismatch": _e(
        "validation_type_mismatch",
        http_status=400,
        jsonrpc_code=-32021,
        ja="フィールドの型が想定と異なります。",
        en="Field type does not match the schema.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    "validation_out_of_range": _e(
        "validation_out_of_range",
        http_status=400,
        jsonrpc_code=-32022,
        ja="値が許容範囲外です。",
        en="Value out of allowed range.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    "validation_enum_invalid": _e(
        "validation_enum_invalid",
        http_status=400,
        jsonrpc_code=-32023,
        ja="許可されていない選択肢が指定されました。",
        en="Value not in allowed enum set.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    "validation_id_unknown": _e(
        "validation_id_unknown",
        http_status=404,
        jsonrpc_code=-32024,
        ja="指定のIDが見つかりません。",
        en="Resource id not found.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    "validation_id_fabricated": _e(
        "validation_id_fabricated",
        http_status=400,
        jsonrpc_code=-32025,
        ja="架空のIDの可能性があります。検索エンドポイントで実在性を確認してください。",
        en="ID appears fabricated; resolve via search first.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    "validation_houjin_bangou_invalid": _e(
        "validation_houjin_bangou_invalid",
        http_status=400,
        jsonrpc_code=-32026,
        ja="法人番号のチェックディジットが一致しません。",
        en="Houjin bangou check digit mismatch.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    "validation_date_out_of_window": _e(
        "validation_date_out_of_window",
        http_status=400,
        jsonrpc_code=-32027,
        ja="指定日付がデータ範囲外です。",
        en="Date falls outside corpus snapshot window.",
        retryable=False,
        escalation="caller_self_heal",
        category="validation",
    ),
    # ---- Upstream / data (7) ----------------------------------------
    "upstream_source_dead": _e(
        "upstream_source_dead",
        http_status=503,
        jsonrpc_code=-32030,
        ja="一次資料サイトが応答していません。",
        en="Upstream primary-source site is unreachable.",
        retryable=True,
        escalation="operator_action",
        category="upstream",
    ),
    "upstream_source_changed": _e(
        "upstream_source_changed",
        http_status=200,
        jsonrpc_code=-32031,
        ja="一次資料が更新されています。再取得を推奨します。",
        en="Primary source has been amended; consider re-fetch.",
        retryable=True,
        escalation="caller_self_heal",
        category="upstream",
    ),
    "snapshot_stale": _e(
        "snapshot_stale",
        http_status=200,
        jsonrpc_code=-32032,
        ja="現在のスナップショットは古い可能性があります。",
        en="Corpus snapshot is older than the freshness window.",
        retryable=True,
        escalation="operator_action",
        category="upstream",
    ),
    "corpus_unavailable": _e(
        "corpus_unavailable",
        http_status=503,
        jsonrpc_code=-32033,
        ja="コーパスデータベースが一時的に利用できません。",
        en="Corpus database temporarily unavailable.",
        retryable=True,
        escalation="operator_action",
        category="upstream",
    ),
    "fts_query_timeout": _e(
        "fts_query_timeout",
        http_status=504,
        jsonrpc_code=-32034,
        ja="検索クエリがタイムアウトしました。",
        en="FTS query timed out.",
        retryable=True,
        escalation="caller_self_heal",
        category="upstream",
    ),
    "known_gap_no_data": _e(
        "known_gap_no_data",
        http_status=200,
        jsonrpc_code=-32035,
        ja="この項目はデータ未収載です。",
        en="Field intentionally not covered in current corpus.",
        retryable=False,
        escalation="none",
        category="upstream",
    ),
    "compatibility_unknown": _e(
        "compatibility_unknown",
        http_status=200,
        jsonrpc_code=-32036,
        ja="互換性が確認できていません。一次資料を確認してください。",
        en="Compatibility pair not yet validated; consult primary source.",
        retryable=False,
        escalation="caller_self_heal",
        category="upstream",
    ),
    # ---- Internal / unrecoverable (6) -------------------------------
    "internal_server": _e(
        "internal_server",
        http_status=500,
        jsonrpc_code=-32603,
        ja="内部エラーが発生しました。",
        en="Internal server error.",
        retryable=True,
        escalation="operator_action",
        category="internal",
    ),
    "internal_db_locked": _e(
        "internal_db_locked",
        http_status=503,
        jsonrpc_code=-32041,
        ja="データベースが一時的にロックされています。",
        en="Database temporarily locked; retry with backoff.",
        retryable=True,
        escalation="operator_action",
        category="internal",
    ),
    "internal_timeout": _e(
        "internal_timeout",
        http_status=504,
        jsonrpc_code=-32042,
        ja="処理がタイムアウトしました。",
        en="Internal processing timeout.",
        retryable=True,
        escalation="operator_action",
        category="internal",
    ),
    "internal_migration_pending": _e(
        "internal_migration_pending",
        http_status=503,
        jsonrpc_code=-32043,
        ja="メンテナンス中です。しばらくお待ちください。",
        en="Maintenance in progress; service will resume shortly.",
        retryable=True,
        escalation="operator_action",
        category="internal",
    ),
    "internal_deprecated_endpoint": _e(
        "internal_deprecated_endpoint",
        http_status=410,
        jsonrpc_code=-32044,
        ja="このエンドポイントは廃止されました。",
        en="This endpoint has been deprecated and removed.",
        retryable=False,
        escalation="caller_self_heal",
        category="internal",
    ),
    "internal_not_implemented": _e(
        "internal_not_implemented",
        http_status=501,
        jsonrpc_code=-32601,
        ja="この機能は未実装です。",
        en="Feature not implemented.",
        retryable=False,
        escalation="operator_action",
        category="internal",
    ),
}


def build_mcp_error_advertisement() -> dict[str, Any]:
    """Build the ``_meta.error_codes`` block for the MCP capabilities ad.

    Embedded into the streamable HTTP transport's
    ``initialize`` response so agent orchestrators can statically map
    error codes to retry / escalation policy before issuing tool calls.
    """
    return {
        "schema_version": MCP_ERROR_SCHEMA,
        "documentation_url": "https://jpcite.com/docs/error_handling.html",
        "categories": ["auth", "billing", "validation", "upstream", "internal"],
        "count": len(CANONICAL_ERROR_CODES),
        "codes": [
            {
                "code": e["code"],
                "category": e["category"],
                "jsonrpc_code": e["jsonrpc_code"],
                "http_status": e["http_status"],
                "retryable": e["retryable"],
                "escalation": e["escalation"],
            }
            for e in CANONICAL_ERROR_CODES.values()
        ],
    }


def map_rest_to_jsonrpc(rest_envelope: dict[str, Any]) -> dict[str, Any]:
    """Convert a REST error envelope to the JSON-RPC equivalent.

    Used by the streamable HTTP MCP transport when surfacing a REST
    error to a JSON-RPC client. Falls back to ``-32603`` (internal)
    if the code is not in :data:`CANONICAL_ERROR_CODES`.
    """
    err = rest_envelope.get("error") or {}
    code = err.get("code") or "internal_server"
    entry = CANONICAL_ERROR_CODES.get(code)
    if entry is None:
        return {
            "code": -32603,
            "message": err.get("user_message") or "Internal error",
            "data": {"original_code": code, "request_id": err.get("request_id")},
        }
    return {
        "code": entry["jsonrpc_code"],
        "message": entry["user_message_en"],
        "data": {
            "code": code,
            "category": entry["category"],
            "user_message_ja": entry["user_message_ja"],
            "retryable": entry["retryable"],
            "escalation": entry["escalation"],
            "documentation": entry["documentation"],
            "request_id": err.get("request_id"),
        },
    }


__all__ = [
    "CANONICAL_ERROR_CODES",
    "MCP_ERROR_SCHEMA",
    "build_mcp_error_advertisement",
    "map_rest_to_jsonrpc",
]
