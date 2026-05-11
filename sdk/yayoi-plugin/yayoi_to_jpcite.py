"""弥生会計 → jpcite glue layer.

Wave 35 Axis 6c (2026-05-12). Stateless adapter mapping Yayoi
accounting CSV / cloud transactions into jpcite ``programs.search``.

Security: tokens are never persisted, logged, or echoed.
No LLM provider API is contacted.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("jpcite.yayoi")

YAYOI_CLOUD_BASE = "https://api.biz.yayoi-kk.co.jp"
JPCITE_API_BASE = "https://api.jpcite.com"

YAYOI_ACCOUNT_TO_FUNDING_PURPOSE: dict[str, list[str]] = {
    "減価償却費": ["設備投資"],
    "機械装置": ["設備投資"],
    "工具器具備品": ["設備投資"],
    "車両運搬具": ["設備投資"],
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
    "外注工賃": ["業務委託"],
    "外注費": ["業務委託"],
    "消耗品費": ["設備投資"],
    "修繕費": ["設備投資"],
    "電力料": ["省エネ", "GX"],
    "水道光熱費": ["省エネ", "GX"],
    "燃料費": ["省エネ", "GX"],
    "法定福利費": ["雇用"],
    "厚生費": ["雇用"],
    "退職給付費用": ["人材確保"],
    "雇用保険料": ["雇用"],
    "労働保険料": ["雇用"],
}


class YayoiContext(BaseModel):
    accounts: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    prefecture: str | None = None
    corporate_class: str | None = None


class ProgramRecommendation(BaseModel):
    unified_id: str
    title: str
    authority: str | None = None
    tier: str | None = None
    source_url: str


def parse_yayoi_csv(csv_bytes: bytes) -> list[str]:
    """Extract distinct account names from a 弥生 仕訳帳 CSV export."""
    text: str | None = None
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            text = csv_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return []

    out: list[str] = []
    seen: set[str] = set()
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    name_idxs = [
        i for i, h in enumerate(header)
        if isinstance(h, str) and ("勘定科目" in h or "科目" in h)
    ]
    if not name_idxs:
        return []
    for row in reader:
        for idx in name_idxs:
            if idx >= len(row):
                continue
            name = (row[idx] or "").strip()
            if name and name not in seen:
                out.append(name)
                seen.add(name)
        if len(out) >= 32:
            break
    return out


def map_accounts_to_purposes(accounts: list[str]) -> list[str]:
    purposes: list[str] = []
    seen: set[str] = set()
    for acc in accounts:
        for p in YAYOI_ACCOUNT_TO_FUNDING_PURPOSE.get(acc, []):
            if p not in seen:
                purposes.append(p)
                seen.add(p)
    return purposes


def call_yayoi_cloud_summary(
    *,
    yayoi_token: str,
    company_id: str,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch the 弥生クラウド 試算表 summary (read-only)."""
    if not yayoi_token or not isinstance(yayoi_token, str):
        raise ValueError("yayoi_token is required (caller-supplied)")
    owns_client = http_client is None
    client = http_client or httpx.Client(base_url=YAYOI_CLOUD_BASE, timeout=15.0)
    try:
        resp = client.get(
            f"/v1/companies/{company_id}/trial_balance",
            headers={"Authorization": f"Bearer {yayoi_token}"},
        )
        resp.raise_for_status()
        body = resp.json()
        return body if isinstance(body, dict) else {}
    finally:
        if owns_client:
            client.close()


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
            headers={"X-API-Key": api_key, "User-Agent": "jpcite-yayoi-plugin/0.1"},
        )
        resp.raise_for_status()
        body = resp.json() if isinstance(resp.json(), dict) else {}
        items = body.get("items") or body.get("results") or []
        return [x for x in items if isinstance(x, dict)]
    finally:
        if owns_client:
            client.close()


def recommend(
    *,
    yayoi_csv_bytes: bytes | None = None,
    yayoi_token: str | None = None,
    company_id: str | None = None,
    jpcite_api_key: str,
    prefecture: str | None = None,
    corporate_class: str | None = None,
    limit: int = 5,
    yayoi_client: httpx.Client | None = None,
    jpcite_client: httpx.Client | None = None,
) -> list[ProgramRecommendation]:
    """Top-level glue. Accepts either a desktop CSV OR a cloud token."""
    if not jpcite_api_key:
        raise ValueError("jpcite_api_key is required (caller-supplied)")
    if limit <= 0 or limit > 5:
        raise ValueError("limit must be in 1..5")

    accounts: list[str] = []
    if yayoi_csv_bytes:
        accounts = parse_yayoi_csv(yayoi_csv_bytes)
    elif yayoi_token and company_id:
        body = call_yayoi_cloud_summary(
            yayoi_token=yayoi_token,
            company_id=company_id,
            http_client=yayoi_client,
        )
        for row in body.get("items", []):
            if isinstance(row, dict) and "account_name" in row:
                acc = str(row["account_name"]).strip()
                if acc and acc not in accounts:
                    accounts.append(acc)
    else:
        raise ValueError("must provide either yayoi_csv_bytes OR (yayoi_token + company_id)")

    purposes = map_accounts_to_purposes(accounts)
    if not purposes:
        return []

    params: dict[str, Any] = {
        "limit": int(limit),
        "tier": ["S", "A", "B"],
        "funding_purpose": purposes[:5],
    }
    if prefecture:
        params["prefecture"] = prefecture
    if corporate_class:
        params["target_type"] = [corporate_class]

    raw_items = _call_jpcite_search(
        api_key=jpcite_api_key,
        params=params,
        http_client=jpcite_client,
    )
    out: list[ProgramRecommendation] = []
    for raw in raw_items:
        url = raw.get("source_url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        out.append(
            ProgramRecommendation(
                unified_id=str(raw.get("unified_id") or raw.get("id") or ""),
                title=str(raw.get("title") or raw.get("name") or ""),
                authority=raw.get("authority"),
                tier=raw.get("tier"),
                source_url=url,
            )
        )
        if len(out) >= limit:
            break
    return out


__all__ = [
    "YayoiContext",
    "ProgramRecommendation",
    "YAYOI_ACCOUNT_TO_FUNDING_PURPOSE",
    "parse_yayoi_csv",
    "map_accounts_to_purposes",
    "call_yayoi_cloud_summary",
    "recommend",
]
