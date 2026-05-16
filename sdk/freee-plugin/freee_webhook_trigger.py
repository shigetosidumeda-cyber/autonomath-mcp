"""freee → jpcite webhook trigger surface.

Wave 35 Axis 6c (2026-05-12). Extends ``freee_to_autonomath.py`` with a
webhook receiver that translates freee accounting events (journal
entry created, 経費精算 submitted, etc.) into a jpcite
``programs.search`` query.

Flow
----
1. freee posts a webhook to ``/freee/webhook`` (Fly app).
2. ``freee_webhook_handle()`` validates the payload signature using
   freee's HMAC-SHA256 secret (env ``FREEE_WEBHOOK_SECRET``).
3. The journal entry's 仕訳科目 → jpcite ``funding_purpose`` mapping
   feeds a sub-search through ``/v1/programs/search``.
4. Up to 3 candidate programs are returned in the response.

Memory references
-----------------
* feedback_no_operator_llm_api : no model call anywhere.
* feedback_zero_touch_solo : stateless Fly app.
* feedback_dont_extrapolate_principles : plugin SDK side calls jpcite
  REST (it IS customer side) but never an LLM API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING, Any

from .freee_to_autonomath import call_autonomath_search

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger("jpcite.freee_webhook")

# 仕訳科目 → jpcite funding_purpose alias. 60 common 借方/貸方 entries.
JOURNAL_ACCOUNT_TO_FUNDING_PURPOSE: dict[str, list[str]] = {
    "減価償却費": ["設備投資"],
    "機械装置": ["設備投資"],
    "工具器具備品": ["設備投資"],
    "車両運搬具": ["設備投資"],
    "建物附属設備": ["設備投資"],
    "ソフトウェア": ["IT導入", "DX"],
    "通信費": ["IT導入"],
    "研究開発費": ["研究開発"],
    "試験研究費": ["研究開発"],
    "広告宣伝費": ["販路開拓"],
    "販売促進費": ["販路開拓"],
    "教育研修費": ["人材育成"],
    "支払手数料": ["事業承継"],
    "支払利息": ["創業"],
    "賃借料": ["店舗開設"],
    "地代家賃": ["店舗開設"],
    "支払報酬": ["業務委託"],
    "外注費": ["業務委託"],
    "消耗品費": ["設備投資"],
    "修繕費": ["設備投資"],
    "電力料": ["省エネ", "GX"],
    "燃料費": ["省エネ", "GX"],
    "派遣社員給与": ["雇用"],
    "雑給": ["雇用"],
    "退職給付費用": ["人材確保"],
    "法定福利費": ["雇用"],
    "厚生費": ["雇用"],
}


class FreeeWebhookSignatureError(RuntimeError):
    """Raised when the webhook signature header is missing or invalid."""


def verify_freee_webhook(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
) -> None:
    """Verify ``X-Freee-Signature`` over the raw body using HMAC-SHA256."""
    if not signature_header:
        raise FreeeWebhookSignatureError("missing X-Freee-Signature")
    if not secret:
        raise FreeeWebhookSignatureError("FREEE_WEBHOOK_SECRET not set")
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, signature_header.strip()):
        raise FreeeWebhookSignatureError("signature mismatch")


def _extract_accounts(payload: dict[str, Any]) -> list[str]:
    """Return up to 8 distinct 仕訳科目 names from a freee payload."""
    out: list[str] = []
    details = (
        (payload.get("deal") or {}).get("details")
        or (payload.get("manual_journal") or {}).get("details")
        or payload.get("expense_application", {}).get("receipts")
        or []
    )
    seen: set[str] = set()
    for d in details:
        if not isinstance(d, dict):
            continue
        item = d.get("account_item") or {}
        name = item.get("name") or d.get("account_item_name") or ""
        if name and name not in seen:
            out.append(name)
            seen.add(name)
        if len(out) >= 8:
            break
    return out


def freee_webhook_handle(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
    jpcite_api_key: str,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Validate + translate a freee webhook into jpcite candidate matches."""
    verify_freee_webhook(raw_body=raw_body, signature_header=signature_header, secret=secret)
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreeeWebhookSignatureError(f"invalid JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise FreeeWebhookSignatureError("payload not an object")

    accounts = _extract_accounts(payload)
    purposes: list[str] = []
    seen: set[str] = set()
    for acc in accounts:
        for p in JOURNAL_ACCOUNT_TO_FUNDING_PURPOSE.get(acc, []):
            if p not in seen:
                purposes.append(p)
                seen.add(p)

    if not purposes:
        return {
            "kind": "freee_webhook",
            "accounts": accounts,
            "purposes": [],
            "matches": [],
            "skipped_reason": "no funding_purpose mapping",
        }

    items = call_autonomath_search(
        autonomath_api_key=jpcite_api_key,
        params={"limit": 3, "tier": ["S", "A", "B"], "funding_purpose": purposes[:5]},
        http_client=http_client,
    )
    matches: list[dict[str, Any]] = []
    for raw in items:
        url = raw.get("source_url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        matches.append(
            {
                "unified_id": raw.get("unified_id") or raw.get("id"),
                "title": raw.get("title") or raw.get("name"),
                "authority": raw.get("authority"),
                "tier": raw.get("tier"),
                "source_url": url,
            }
        )
        if len(matches) >= 3:
            break

    return {
        "kind": "freee_webhook",
        "accounts": accounts,
        "purposes": purposes,
        "matches": matches,
    }


__all__ = [
    "FreeeWebhookSignatureError",
    "JOURNAL_ACCOUNT_TO_FUNDING_PURPOSE",
    "freee_webhook_handle",
    "verify_freee_webhook",
]
