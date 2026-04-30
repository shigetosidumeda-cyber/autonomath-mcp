"""Tier 1 envelope CS features (P3-M++, dd_v8_08).

Six purely-additive helpers that enrich the response envelope's `meta`
block with customer-facing context. Designed to be backward-compatible
with the existing `build_envelope` shape: the `meta` block is opt-in (a
caller passing `fields="minimal"` to `build_meta()` gets `None` back),
and every field inside `meta` is optional.

Six features
------------

A. Contextual help
   - `meta.suggestions` (0-result): concrete next queries to try.
   - `meta.alternative_intents` (low-confidence query): alt intent candidates.
   - `meta.input_warnings` (validation): year/range/format hints.

B. Per-tool latency / token estimate
   - `meta.token_estimate` (output token count, byte/3 safe-side rounding).
   - `meta.wall_time_ms` (mirror of envelope-level latency_ms; explicit name
     so consumers do not have to know the legacy alias).

D. Predictive billing alert (cron-only — see scripts/cron/predictive_billing_alert.py)
   - This module exposes a *helper* `compute_billing_alert()` that the
     cron script can import. The envelope itself never carries the alert
     (alerts are out-of-band emails).

E. Intelligent retry suggestion (error responses)
   - `error.retry_after` (seconds; rate-limit aware).
   - `error.alternate_endpoint` (e.g. 503 → `/v1/programs` REST mirror).

F. Onboarding nudge (D+0/1/3/7 contextual tips)
   - `meta.tips` keyed on api_keys.created_at age in days.

J. Plain-Japanese error message
   - `error.user_message` mapped from error code (and HTTP status).

No API key usage
----------------
This module is pure deterministic logic. No Anthropic / OpenAI call.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "build_meta",
    "compute_token_estimate",
    "derive_suggestions",
    "derive_alternative_intents",
    "derive_input_warnings",
    "onboarding_tips_for_age_days",
    "USER_MESSAGES",
    "user_message_for_error",
    "enhance_error_with_retry",
    "compute_billing_alert",
]


# ---------------------------------------------------------------------------
# Token estimation (byte/3 safe-side per task spec)
# ---------------------------------------------------------------------------


def compute_token_estimate(payload: Any) -> int:
    """Return an over-estimate of the LLM token count for `payload`.

    Strategy:
        1. JSON-encode (compact, no whitespace) to count effective bytes.
        2. Divide by 3 (safe side) — under-estimating tokens leaks money,
           so we over-state. Real Claude tokenizers run ~3.5-4 bytes/tok
           for Japanese; byte/3 is a comfortable upper bound.

    Falls back to `len(str(payload))/3` if JSON encoding fails (object
    contained non-serializable things), which is still safe-side.
    """
    try:
        import json

        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        nbytes = len(encoded.encode("utf-8"))
    except Exception:
        nbytes = len(str(payload).encode("utf-8"))
    return max(1, math.ceil(nbytes / 3))


# ---------------------------------------------------------------------------
# Feature A — Contextual help
# ---------------------------------------------------------------------------

# Per-tool 0-result suggestion templates. Each suggestion is a short,
# user-facing Japanese sentence the customer can show their end-user.
_TOOL_SUGGESTIONS: dict[str, list[str]] = {
    "search_tax_incentives": [
        "業種を絞らずに再検索してみる",
        "target_year を 1 年広げる (例: 2024 → 2023-2025)",
        "search_certifications で関連認定制度も併せて探す",
    ],
    "search_certifications": [
        "認定名の正式名称で再検索 (例: 経営革新計画)",
        "業種フィルタを外す",
    ],
    "list_open_programs": [
        "都道府県を「全国」に広げる",
        "募集中の絞り込みを外して直近終了分も含める",
    ],
    "search_by_law": [
        "法令の正式名称を確認 (例: 中小企業等経営強化法)",
        "search_programs_fts で自由語検索を試す",
    ],
    "active_programs_at": [
        "日付の前後 30 日を試す",
        "list_open_programs で現在募集中のものに切替",
    ],
    "related_programs": [
        "seed_id の表記揺れを enum_values で確認",
        "search_programs_fts で別の seed を見つける",
    ],
    "search_acceptance_stats": [
        "制度名の表記揺れを確認 (例: ものづくり vs ものつくり)",
        "search_programs_fts で正式名を取得してから再検索",
    ],
    "enum_values": [
        "enum 名のスペルを確認",
    ],
    "intent_of": [
        "業種・地域・時期を含めて再質問",
    ],
    "reason_answer": [
        "質問を分割して 1 つずつ問い合わせる",
    ],
}

_FALLBACK_SUGGESTIONS: list[str] = [
    "検索条件を 1 つ外して再試行",
    "search_programs_fts で自由語検索を試す",
]


def derive_suggestions(tool_name: str, status: str) -> list[str]:
    """Return up to 3 short suggestions when status == 'empty'.

    For non-empty status we return [] so consumers can render the field
    only when it is actionable.
    """
    if status != "empty":
        return []
    return list(_TOOL_SUGGESTIONS.get(tool_name, _FALLBACK_SUGGESTIONS))[:3]


def derive_alternative_intents(
    tool_name: str,
    query_echo: str,
    *,
    status: str,
) -> list[str]:
    """Heuristic alt-intent suggestions for low-confidence cases.

    We treat status='empty' OR (status='sparse' AND query_echo has >=8 chars)
    as low-confidence. The returned list is short, deterministic, and
    keyed on simple keyword presence in the user's free-text query.
    """
    if status not in ("empty", "sparse"):
        return []
    q = (query_echo or "").lower()
    if not q:
        return []
    out: list[str] = []
    if any(k in q for k in ("税", "税制", "控除", "減税")):
        out.append("税制特例検索 (search_tax_incentives) を試す")
    if any(k in q for k in ("補助", "助成", "給付")):
        out.append("公募中制度一覧 (list_open_programs) を試す")
    if any(k in q for k in ("認定", "計画認定", "経営革新")):
        out.append("認定制度検索 (search_certifications) を試す")
    if any(k in q for k in ("法律", "法令", "条文")):
        out.append("法令から逆引き (search_by_law) を試す")
    if any(k in q for k in ("採択", "採択率", "実績")):
        out.append("採択統計 (search_acceptance_stats) を試す")
    # Dedupe while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped[:3]


def derive_input_warnings(
    tool_name: str,
    kwargs: dict[str, Any],
    *,
    coverage_min_year: int = 2018,
    coverage_max_year: int = 2026,
) -> list[str]:
    """Inspect kwargs for known out-of-coverage / ambiguous values.

    Pure validation — does not raise. The wrapped tool will already have
    its own validation; this just surfaces a *hint* to the caller before
    they look at empty results.
    """
    warnings: list[str] = []
    for key in ("target_year", "fy", "fiscal_year", "year"):
        v = kwargs.get(key)
        if isinstance(v, int):
            if v < coverage_min_year:
                warnings.append(
                    f"{key}={v} は提供データ範囲外 (収録は {coverage_min_year} 年以降)"
                )
            elif v > coverage_max_year:
                warnings.append(
                    f"{key}={v} は提供データ範囲外 (収録は {coverage_max_year} 年まで)"
                )
    # Date string sanity (cheap)
    for key in ("at", "as_of", "date"):
        v = kwargs.get(key)
        if isinstance(v, str) and v and len(v) >= 4:
            try:
                year = int(v[:4])
                if year < coverage_min_year or year > coverage_max_year:
                    warnings.append(
                        f"{key}={v} は提供データ範囲外 ({coverage_min_year}-{coverage_max_year})"
                    )
            except ValueError:
                # Not a YYYY-* string, skip.
                pass
    # Limit too aggressive
    lim = kwargs.get("limit")
    if isinstance(lim, int) and lim > 100:
        warnings.append(f"limit={lim} は実質 100 で打ち切られます")
    return warnings


# ---------------------------------------------------------------------------
# Feature F — Onboarding nudge
# ---------------------------------------------------------------------------

# Day-keyed onboarding tips. Customer LLMs see ONE message per response
# only on the matching day-anchor (D+0 / D+1 / D+3 / D+7). Other days
# return [] to keep the envelope quiet.
_ONBOARDING_TIPS: dict[int, list[str]] = {
    0: [
        "first request 受信、ようこそ AutonoMath へ。docs/quickstart.md を参照。",
    ],
    1: [
        "list_open_programs で公募中 program 一覧を取得できます。",
    ],
    3: [
        "deadline_calendar で締切カレンダー作成可。",
    ],
    7: [
        "subsidy_combo_finder で複合提案を取得。",
    ],
}


def onboarding_tips_for_age_days(age_days: int | None) -> list[str]:
    """Return the onboarding nudge for `age_days` (D+0 / 1 / 3 / 7).

    `age_days = None` (anonymous tier or unknown key) → no tips.
    Other days (D+2, D+4-6, D+8+) → no tips.
    """
    if age_days is None:
        return []
    return list(_ONBOARDING_TIPS.get(age_days, []))


def _age_days_from_created_at(created_at: str | None) -> int | None:
    """Parse api_keys.created_at ISO string and return whole-day age.

    Returns None if `created_at` is missing or unparseable.
    """
    if not created_at or not isinstance(created_at, str):
        return None
    try:
        # Tolerate trailing Z or +00:00; api_keys uses datetime.now(UTC).isoformat()
        s = created_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Feature J — Plain-Japanese error messages
# ---------------------------------------------------------------------------

# Maps a canonical error code to a user-facing Japanese sentence. Every
# string is deliberately short (<= 80 chars) and ends with a clear
# next-action verb so non-LLM clients (Claude Desktop popups, curl users)
# can render it raw.
USER_MESSAGES: dict[str, str] = {
    # error_envelope.ErrorCode set
    "missing_required_arg": "必須パラメータが空です。引数を指定して再試行してください。",
    "invalid_enum": "指定値が候補にありません。enum_values で正しい値を取得してください。",
    "invalid_date_format": "日付形式が不正です。YYYY-MM-DD で指定してください。",
    "out_of_range": "数値が範囲外です。docs/api_reference.md の上下限を確認してください。",
    "no_matching_records": "該当データが見つかりません。条件を緩めるか別のツールをお試しください。",
    "ambiguous_query": "クエリが曖昧です。業種・地域・時期で絞り込んでください。",
    "seed_not_found": "指定 ID が DB にありません。search_* で正しい ID を取得してください。",
    "db_locked": "DB が一時的にロック中です。数秒待って再試行してください。",
    "db_unavailable": "DB に接続できません。サービス側障害の可能性があります。",
    "subsystem_unavailable": "補助サブシステム停止中。基本機能のみで継続します。",
    "internal": "内部エラーです。時間をおいて再試行してください。",
    # Rate / billing surface (used when wrapping HTTP layer errors)
    "rate_limit_exceeded": "リクエスト多すぎ。1 分待ってからリトライください。",
    "monthly_cap_reached": "月次上限到達。ダッシュボードで上限変更可。",
    "auth_required": "認証エラー。X-API-Key を確認してください。",
    "invalid_api_key": "API キーが無効です。dashboard で再発行してください。",
}

# HTTP status code → base Japanese message (used as fallback when no code map hit)
HTTP_STATUS_MESSAGES: dict[int, str] = {
    400: "リクエストに不備があります。引数を確認してください。",
    401: "認証エラー。X-API-Key を確認してください。",
    403: "アクセス権がありません。プラン / 課金状態を確認してください。",
    404: "該当データが見つかりません。",
    408: "タイムアウト。再試行してください。",
    409: "競合が発生しました。少し待ってから再試行してください。",
    422: "入力検証に失敗しました。docs/api_reference.md を参照ください。",
    429: "リクエスト多すぎ。1 分待ってからリトライください。",
    500: "サーバ内部エラーです。時間をおいて再試行してください。",
    502: "上流サービスがダウンしています。再試行してください。",
    503: "一時的にサービス停止中です。数分後に再試行してください。",
    504: "上流タイムアウト。再試行してください。",
}


def user_message_for_error(
    code: str | None = None,
    *,
    http_status: int | None = None,
) -> str:
    """Return a Japanese end-user message for the given error code/status.

    Resolution order:
      1. USER_MESSAGES[code] if code is known.
      2. HTTP_STATUS_MESSAGES[http_status] if status is known.
      3. Generic fallback.
    """
    if code and code in USER_MESSAGES:
        return USER_MESSAGES[code]
    if http_status is not None:
        if http_status in HTTP_STATUS_MESSAGES:
            return HTTP_STATUS_MESSAGES[http_status]
        # Generic class fallback
        if 400 <= http_status < 500:
            return "リクエストエラーです。引数を確認してください。"
        if 500 <= http_status < 600:
            return "サーバ側エラーです。時間をおいて再試行してください。"
    return "エラーが発生しました。時間をおいて再試行してください。"


# ---------------------------------------------------------------------------
# Feature E — Intelligent retry suggestion
# ---------------------------------------------------------------------------

# Mapping of error code to (retry_after_seconds, alternate_endpoint or None).
# Values are conservative; clients honor retry_after as a minimum sleep.
_RETRY_HINTS: dict[str, tuple[int, str | None]] = {
    "db_locked": (3, None),
    "db_unavailable": (60, "https://jpcite.com/v1/programs"),
    "subsystem_unavailable": (10, None),
    "internal": (15, None),
    "rate_limit_exceeded": (60, None),
    "monthly_cap_reached": (0, "https://jpcite.com/dashboard/billing"),
}


def enhance_error_with_retry(
    err: dict[str, Any],
    *,
    http_status: int | None = None,
) -> dict[str, Any]:
    """Enrich an existing `error` dict with retry_after + alternate_endpoint
    + user_message. Pure: returns a new dict, does not mutate input.

    Resolution order:
      1. Apply code-keyed hints from _RETRY_HINTS (if known).
      2. ALSO apply http_status hints (additive — these may fill in
         `alternate_endpoint` when the code-level hint omitted it).
      3. Attach `user_message` (code wins over http_status).

    No-op on a falsy / non-dict input.
    """
    if not isinstance(err, dict) or not err:
        return err
    out = dict(err)
    code = out.get("code")
    if isinstance(code, str) and code in _RETRY_HINTS:
        retry_after, alternate = _RETRY_HINTS[code]
        out.setdefault("retry_after", retry_after)
        if alternate:
            out.setdefault("alternate_endpoint", alternate)
    if http_status == 503:
        out.setdefault("retry_after", 30)
        out.setdefault(
            "alternate_endpoint",
            "https://jpcite.com/v1/programs",
        )
    elif http_status == 429:
        out.setdefault("retry_after", 60)
    if "user_message" not in out:
        out["user_message"] = user_message_for_error(
            code if isinstance(code, str) else None,
            http_status=http_status,
        )
    return out


# ---------------------------------------------------------------------------
# Feature D — Predictive billing alert (helper used by the cron script)
# ---------------------------------------------------------------------------


def compute_billing_alert(
    *,
    current_month_count: int,
    rolling_avg_count: float,
    threshold_multiplier: float = 3.0,
    min_floor: int = 100,
) -> dict[str, Any] | None:
    """Return an alert payload if `current_month_count` is unusually high.

    Heuristic:
        - Skip if current_month_count < min_floor (noise floor).
        - Skip if rolling_avg_count <= 0 (cold start, no history).
        - Trigger when current >= avg * threshold_multiplier.

    Returns
    -------
    None if no alert needed. Otherwise a dict with `multiplier`, `current`,
    `avg`, `recommended_action` for the email template.
    """
    if current_month_count < min_floor:
        return None
    if rolling_avg_count <= 0:
        return None
    multiplier = current_month_count / rolling_avg_count
    if multiplier < threshold_multiplier:
        return None
    return {
        "current": int(current_month_count),
        "avg": round(float(rolling_avg_count), 1),
        "multiplier": round(multiplier, 2),
        "threshold_multiplier": float(threshold_multiplier),
        "recommended_action": (
            f"今月の利用量が平均の {round(multiplier, 1)} 倍に達しています。"
            "ダッシュボードで上限見直し / 用途の確認を推奨します。"
        ),
    }


# ---------------------------------------------------------------------------
# Aggregate: build the meta block for build_envelope()
# ---------------------------------------------------------------------------


def build_meta(
    *,
    tool_name: str,
    status: str,
    query_echo: str,
    latency_ms: float,
    results: list,
    legacy_extras: dict[str, Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    api_key_created_at: str | None = None,
    fields: str = "standard",
) -> dict[str, Any] | None:
    """Return the `meta` block, or `None` for fields='minimal'.

    Order of keys is alphabetical for predictability across consumer
    parsers. All fields are optional — empty lists / None are dropped
    so the response stays compact.
    """
    if fields == "minimal":
        return None

    legacy_extras = legacy_extras or {}
    kwargs = kwargs or {}

    suggestions = derive_suggestions(tool_name, status)
    alternative_intents = derive_alternative_intents(
        tool_name, query_echo, status=status,
    )
    input_warnings = derive_input_warnings(tool_name, kwargs)
    age_days = _age_days_from_created_at(api_key_created_at)
    tips = onboarding_tips_for_age_days(age_days)

    # token_estimate is computed on the (results + legacy_extras) payload
    # since that's what the caller gets back. We deliberately exclude meta
    # itself (avoid recursion) — caller can add ~5% for the meta overhead
    # if they want a tighter number.
    estimate_payload = {
        "results": results,
        "legacy": {k: v for k, v in legacy_extras.items() if k in ("hint", "total")},
    }
    token_estimate = compute_token_estimate(estimate_payload)

    meta: dict[str, Any] = {
        "alternative_intents": alternative_intents,
        "input_warnings": input_warnings,
        "suggestions": suggestions,
        "tips": tips,
        "token_estimate": token_estimate,
        "wall_time_ms": round(float(latency_ms), 3),
    }
    # Drop empty arrays so the envelope is compact. Numeric fields stay.
    cleaned = {
        k: v for k, v in meta.items()
        if not (isinstance(v, list) and len(v) == 0)
    }
    # Preserve alphabetical order (dict retains insertion order in 3.7+).
    return dict(sorted(cleaned.items(), key=lambda kv: kv[0]))
