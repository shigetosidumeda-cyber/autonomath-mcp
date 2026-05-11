"""MoneyForward (MF) → jpcite webhook trigger surface.

Wave 35 Axis 6c (2026-05-12). Parallel to freee_webhook_trigger but for
the MF API event model (ledger_entry.created, transaction.created,
account_classification.updated).

Memory references
-----------------
* feedback_no_operator_llm_api : SDK side calls jpcite REST (paid key),
  but never an LLM provider.
* feedback_keep_it_simple : single endpoint, single match list.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("jpcite.mf_webhook")

JPCITE_API_BASE = "https://api.jpcite.com"

MF_ACCOUNT_TO_FUNDING_PURPOSE: dict[str, list[str]] = {
    "ソフトウェア": ["IT導入", "DX"],
    "通信費": ["IT導入"],
    "減価償却費": ["設備投資"],
    "機械装置": ["設備投資"],
    "工具器具備品": ["設備投資"],
    "車両運搬具": ["設備投資"],
    "建物": ["店舗開設"],
    "賃借料": ["店舗開設"],
    "地代家賃": ["店舗開設"],
    "広告宣伝費": ["販路開拓"],
    "販売促進費": ["販路開拓"],
    "研究開発費": ["研究開発"],
    "試験研究費": ["研究開発"],
    "教育研修費": ["人材育成"],
    "外注工賃": ["業務委託"],
    "外注費": ["業務委託"],
    "支払手数料": ["事業承継"],
    "雑費": ["創業"],
    "支払利息": ["創業"],
    "派遣社員給与": ["雇用"],
    "法定福利費": ["雇用"],
    "厚生費": ["雇用"],
    "電力料": ["省エネ", "GX"],
    "燃料費": ["省エネ", "GX"],
    "水道光熱費": ["省エネ", "GX"],
}


class MfWebhookSignatureError(RuntimeError):
    """Raised when MF webhook signature is invalid."""


def verify_mf_webhook(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
) -> None:
    if not signature_header:
        raise MfWebhookSignatureError("missing X-MF-Signature")
    if not secret:
        raise MfWebhookSignatureError("MF_WEBHOOK_SECRET not set")
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, signature_header.strip()):
        raise MfWebhookSignatureError("signature mismatch")


def _extract_accounts(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    txn = payload.get("transaction")
    if isinstance(txn, dict):
        cls = txn.get("account_classification") or {}
        for k in ("middle_category", "small_category", "large_category"):
            name = cls.get(k)
            if name and name not in seen:
                out.append(name)
                seen.add(name)
    le = payload.get("ledger_entry") or {}
    details = le.get("details") or []
    for d in details:
        if not isinstance(d, dict):
            continue
        item = d.get("account_item") or {}
        name = item.get("name")
        if name and name not in seen:
            out.append(name)
            seen.add(name)
        if len(out) >= 8:
            break
    return out


def _call_jpcite_search(
    *,
    api_key: str,
    params: dict[str, Any],
    http_client: httpx.Client | None,
) -> list[dict[str, Any]]:
    owns_client = http_client is None
    client = http_client or httpx.Client(base_url=JPCITE_API_BASE, timeout=15.0)
    try:
        resp = client.get(
            "/v1/programs/search",
            params=params,
            headers={"X-API-Key": api_key, "User-Agent": "jpcite-mf-plugin/0.2"},
        )
        resp.raise_for_status()
        body = resp.json() if isinstance(resp.json(), dict) else {}
        items = body.get("items") or body.get("results") or []
        return [x for x in items if isinstance(x, dict)]
    finally:
        if owns_client:
            client.close()


def mf_webhook_handle(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
    jpcite_api_key: str,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Validate + translate an MF webhook into jpcite candidate matches."""
    verify_mf_webhook(
        raw_body=raw_body, signature_header=signature_header, secret=secret
    )
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MfWebhookSignatureError(f"invalid JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise MfWebhookSignatureError("payload not an object")

    accounts = _extract_accounts(payload)
    purposes: list[str] = []
    seen: set[str] = set()
    for acc in accounts:
        for p in MF_ACCOUNT_TO_FUNDING_PURPOSE.get(acc, []):
            if p not in seen:
                purposes.append(p)
                seen.add(p)

    if not purposes:
        return {
            "kind": "mf_webhook",
            "accounts": accounts,
            "purposes": [],
            "matches": [],
            "skipped_reason": "no funding_purpose mapping",
        }

    items = _call_jpcite_search(
        api_key=jpcite_api_key,
        params={"limit": 3, "tier": ["S", "A", "B"], "funding_purpose": purposes[:5]},
        http_client=http_client,
    )
    matches: list[dict[str, Any]] = []
    for raw in items:
        url = raw.get("source_url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        matches.append({
            "unified_id": raw.get("unified_id") or raw.get("id"),
            "title": raw.get("title") or raw.get("name"),
            "authority": raw.get("authority"),
            "tier": raw.get("tier"),
            "source_url": url,
        })
        if len(matches) >= 3:
            break

    return {
        "kind": "mf_webhook",
        "accounts": accounts,
        "purposes": purposes,
        "matches": matches,
    }


__all__ = [
    "MfWebhookSignatureError",
    "MF_ACCOUNT_TO_FUNDING_PURPOSE",
    "mf_webhook_handle",
    "verify_mf_webhook",
]
