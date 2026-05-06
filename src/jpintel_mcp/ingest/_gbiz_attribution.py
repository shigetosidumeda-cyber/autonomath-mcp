"""gBizINFO 出典明記 helper — verbatim source-of-truth strings.

This module is the single source of truth for the 出典固定文 strings
that 6 条件 condition 4 mandates. All gBizINFO-derived API responses,
MCP tool payloads, cron job stdout summaries, and static docs MUST
import their attribution copy from here — never duplicate the strings
inline (drift = compliance risk).

6 条件 mapping (verbatim §jpcite ¥3/req metered passthrough greenlight,
verbatim ToS doc tools/offline/_inbox/public_source_foundation/
gbizinfo_tos_verbatim_2026-05-06.md):

  条件 1: Bookyou 株式会社 (T8010001213708) 名義の利用申請 — paper artifact
  条件 2: 1-token 原則 — enforced in `_gbiz_rate_limiter.py` via single
          ``GBIZINFO_API_TOKEN`` env var
  条件 3: 1 rps 防衛既定値 + 24h cache TTL + per-houjin debounce —
          enforced in `_gbiz_rate_limiter.py`
  条件 4: 出典固定文 (短形 / 長形 / 機械可読 ``_attribution``) — THIS MODULE
  条件 5: 第三者権利クレーム転嫁条項 — enforced in `docs/legal/jpcite_tos.md`
          (operator-maintained legal text, surfaced via runtime disclaimers)
  条件 6: 個別法令マーク (JIS / PSE / PSC / 高圧ガス / 計量法 / 特定原産地)
          画像除外 — enforced in `scripts/cron/ingest_gbiz_*` drop logic
          (REST API v2 responses do not contain image fields anyway,
          this is defensive against future schema additions)

Reference: §出典表記 verbatim of the ToS doc + §確定 出典文 templates.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Verbatim 固定文言 — DO NOT EDIT without re-reading 利用規約 4795140981406.
# Both strings are reproduced exactly as the verbatim ToS doc records them
# in §確定 出典文 (jpcite-api response / docs に固定文言で同梱すべきもの).
# ---------------------------------------------------------------------------
ATTRIBUTION_SHORT = (
    "出典：「Gビズインフォ」（経済産業省）（https://info.gbiz.go.jp/）を加工して作成"
)

ATTRIBUTION_LONG = (
    "本データは経済産業省「Gビズインフォ」（https://info.gbiz.go.jp/ ）が"
    "提供する公開法人情報を、Bookyou株式会社（jpcite-api）が編集・加工して"
    "作成したものです。ライセンスは政府標準利用規約 第2.0版"
    "（CC BY 4.0 互換）に準拠します。\n"
    "原典：https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406"
)

# Machine-readable license metadata — surfaced inside the JSON
# ``_attribution`` envelope. License URL points at the canonical
# 利用規約 article so machine consumers can hash + diff for drift.
LICENSE_NAME = "政府標準利用規約 2.0 (CC-BY 4.0 互換)"
LICENSE_URL = "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406"
SOURCE_NAME = "Gビズインフォ"
PUBLISHER_NAME = "経済産業省"
PRIMARY_PUBLISHER = "Gビズインフォ（経済産業省）"
PRIMARY_URL = "https://info.gbiz.go.jp/"
EDIT_NOTICE = "編集・加工して作成"
OPERATOR = "Bookyou株式会社 (T8010001213708)"
FETCHED_VIA = "gBizINFO REST API v2"


def attribution_disclaimer_short() -> str:
    """Return the 短形固定文 (one-line response footer / `_disclaimer`)."""
    return ATTRIBUTION_SHORT


def attribution_disclaimer_long() -> str:
    """Return the 長形固定文 (docs / landing pages / MCP tool description)."""
    return ATTRIBUTION_LONG


def build_attribution(
    source_url: str,
    fetched_at: str,
    upstream_source: str,
) -> dict[str, Any]:
    """Build the machine-readable ``_attribution`` envelope.

    Args:
        source_url: The exact gBizINFO URL the data was retrieved from
            (e.g. ``https://info.gbiz.go.jp/hojin/ichiran?...``).
        fetched_at: ISO-8601 timestamp at which the upstream call landed.
            Pass-through string — caller controls timezone (UTC recommended).
        upstream_source: REQUIRED for subsidy / certification / commendation
            / procurement responses (per §利用規約「外部DB由来コンテンツ」 —
            per-record attribution to the original ministry/aggregator,
            e.g. ``"jGrants"``, ``"MAFF"``, ``"中企庁"``, ``"p-portal"``).
            For corporate_activity the upstream is always
            ``"NTA Houjin Bangou Web-API"``; pass that string explicitly.

    Returns:
        ``{"_attribution": {...}}`` dict ready to merge into a response.
    """
    if not upstream_source or not str(upstream_source).strip():
        raise ValueError("gBizINFO attribution requires upstream_source")
    return {
        "_attribution": {
            "source": SOURCE_NAME,
            "publisher": PUBLISHER_NAME,
            "primary": PRIMARY_PUBLISHER,
            "primary_url": PRIMARY_URL,
            "source_url": source_url,
            "fetched_at": fetched_at,
            "snapshot_date": fetched_at,
            "fetched_via": FETCHED_VIA,
            "license": LICENSE_NAME,
            "license_url": LICENSE_URL,
            "modification_notice": EDIT_NOTICE,
            "edit_notice": EDIT_NOTICE,
            "operator": OPERATOR,
            "upstream_source": upstream_source,
        }
    }


def inject_attribution_into_response(
    envelope: dict[str, Any],
    source_url: str,
    fetched_at: str,
    upstream_source: str,
) -> dict[str, Any]:
    """Idempotently merge ``_attribution`` + ``_disclaimer`` into envelope.

    - ``_attribution`` is overwritten on every call (latest fetch wins,
      since callers always pass the most recent ``fetched_at``).
    - ``_disclaimer`` is set only when absent (so a route-specific
      disclaimer such as §52 / §47条の2 is preserved if it was already
      injected upstream — gBizINFO 出典 is appended as a sibling field
      ``_disclaimer_gbiz`` at the same time).

    Returns the same dict object that was passed in (mutated in place).
    """
    attribution_block = build_attribution(
        source_url=source_url,
        fetched_at=fetched_at,
        upstream_source=upstream_source,
    )
    envelope["_attribution"] = attribution_block["_attribution"]
    if "_disclaimer" not in envelope:
        envelope["_disclaimer"] = ATTRIBUTION_SHORT
    else:
        # Preserve existing _disclaimer, but expose the gBiz 出典 as a
        # sibling field so consumers that look up gBizINFO 出典 specifically
        # can find it without parsing the combined disclaimer string.
        envelope.setdefault("_disclaimer_gbiz", ATTRIBUTION_SHORT)
    return envelope
