"""jpcite MCP resources (Wave 15 A1).

Exposes the `mcp://jpcite/` URI scheme — separate from the legacy
`autonomath://` namespace owned by ``autonomath_tools.resources`` — so an
AI agent connecting via MCP can read jpcite SOT artefacts (facts registry,
業法 fence, glossary, license inventory, sources catalog) in a single
`resources/read` round trip instead of fetching JSON over HTTPS.

Design intent
-------------
* Each resource is **read-only** and computed at read-time from on-disk
  SOT files (``data/facts_registry.json``, ``data/fence_registry.json``,
  ``data/autonomath_static/glossary.json``). The 8-row license matrix
  and 14-row sources catalog are hand-curated inline literals — they
  describe the upstream license posture of the public 補助金 / 法令 /
  税制 / 適格事業者 / 行政処分 datasets so an agent can decide redistribution
  scope before quoting jpcite output downstream.
* No LLM calls. Pure dict / file IO. CI guard
  ``tests/test_no_llm_in_production.py`` enforces this rule for every
  module under ``src/``.
* Resources are registered through FastMCP's ``mcp.resource()`` decorator.
  ``register_jpcite_resources(mcp)`` is idempotent and tolerant of
  FastMCP versions that lack the decorator (skips silently).

The 5 resources land at:

  * ``mcp://jpcite/facts_registry.json`` — 24 publishable facts + guards
  * ``mcp://jpcite/legal/fence.md``       — 7 業法 fence as markdown
  * ``mcp://jpcite/glossary.json``        — 用語集 (補助金 / 助成金 / 融資 ...)
  * ``mcp://jpcite/license_matrix.json``  — 8-row license inventory
  * ``mcp://jpcite/sources_catalog.json`` — 14-dataset primary-source catalog
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]

_DATA_DIR = Path(
    os.environ.get(
        "JPCITE_DATA_DIR",
        str(_REPO_ROOT / "data"),
    )
)
_STATIC_DIR = Path(
    os.environ.get(
        "AUTONOMATH_STATIC_DIR",
        "/data/autonomath_static"
        if Path("/data/autonomath_static").exists()
        else str(_DATA_DIR / "autonomath_static"),
    )
)


# ---------------------------------------------------------------------------
# 1. facts_registry.json
# ---------------------------------------------------------------------------


def _facts_registry_text() -> str:
    """Return facts_registry.json verbatim — SOT for 24 publishable facts."""
    path = _DATA_DIR / "facts_registry.json"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        # Empty stub so the resource never 500s if the file is absent
        # (e.g. uvx install ships without ``data/``).
        return json.dumps(
            {"schema_version": "1.0", "facts": [], "note": "facts_registry.json not bundled"},
            ensure_ascii=False,
            indent=2,
        )


# ---------------------------------------------------------------------------
# 2. legal/fence.md
# ---------------------------------------------------------------------------


def _fence_md_text() -> str:
    """Render fence_registry.json as a markdown table (7 業法)."""
    path = _DATA_DIR / "fence_registry.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "# jpcite 業法 fence\n\n_(fence_registry.json not bundled)_\n"

    lines: list[str] = []
    lines.append("# jpcite 業法 fence (7 canonical)")
    lines.append("")
    lines.append(
        "jpcite が踏み込まない領域 — 個別助言は登録 業法資格者へ。AI agent は "
        "本 fence を出力時に必ず差し込み, 越境疑義は disclaimer_ja / disclaimer_en を "
        "提示すること."
    )
    lines.append("")
    lines.append(f"- snapshot_at: `{raw.get('snapshot_at', 'n/a')}`")
    lines.append(f"- canonical_count: `{raw.get('canonical_count', 0)}`")
    lines.append("")
    lines.append("| id | law | article | scope | do_not | may_do |")
    lines.append("|----|----|---------|-------|--------|--------|")
    for fence in raw.get("fences", []):
        do_not = " / ".join(fence.get("do_not", []))
        may_do = " / ".join(fence.get("may_do", []))
        lines.append(
            f"| `{fence.get('id', '')}` "
            f"| {fence.get('law', '')} "
            f"| {fence.get('article', '')} "
            f"| {fence.get('scope', '')} "
            f"| {do_not} "
            f"| {may_do} |"
        )
    lines.append("")
    lines.append("## Disclaimer templates (per-fence)")
    lines.append("")
    for fence in raw.get("fences", []):
        lines.append(f"### `{fence.get('id', '')}`")
        lines.append("")
        lines.append(f"- JA: {fence.get('disclaimer_ja', '')}")
        lines.append(f"- EN: {fence.get('disclaimer_en', '')}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. glossary.json
# ---------------------------------------------------------------------------


def _glossary_text() -> str:
    """Return jpcite glossary — proxies the canonical autonomath_static
    glossary file so a single SOT remains and the user-facing brand
    namespace is honored."""
    path = _STATIC_DIR / "glossary.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.dumps(
            {"schema_version": "1.0", "nodes": {}, "note": "glossary.json not bundled"},
            ensure_ascii=False,
            indent=2,
        )
    # Re-emit with a jpcite brand banner; payload itself unchanged.
    out = {
        "schema_version": raw.get("schema_version", "1.0"),
        "namespace": "mcp://jpcite/glossary.json",
        "description": (
            "jpcite 用語集 — 補助金 / 助成金 / 融資 / 税制 / 認定制度 の plain-Japanese "
            "+ technical + legal explanation. agent は専門用語を顧客向けに展開する際に "
            "本 resource を読み, 完全自由文ではなく canonical label を使うこと."
        ),
        "node_count": len(raw.get("nodes", {})),
        "nodes": raw.get("nodes", {}),
    }
    return json.dumps(out, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 4. license_matrix.json (hand-curated, in-code SOT)
# ---------------------------------------------------------------------------


_LICENSE_MATRIX: dict[str, Any] = {
    "schema_version": "1.0",
    "namespace": "mcp://jpcite/license_matrix.json",
    "description": (
        "jpcite が取り込む各 upstream データセットの license posture. "
        "agent はこの matrix を読み, 再配布スコープを判断してから quoting せよ. "
        "PDL v1.0 + CC-BY 4.0 + 政府著作物 §13 は出典明記で API 下流提供 OK; "
        "proprietary は引用範囲のみ allowed."
    ),
    "row_count": 8,
    "licenses": [
        {
            "id": "nta_invoice_pdl_v1",
            "label": "国税庁 適格請求書発行事業者公表サイト",
            "license_code": "PDL_v1.0",
            "license_url": "https://www.digital.go.jp/resources/data_policy",
            "redistribution": "allowed_with_attribution",
            "commercial_use": "allowed",
            "modification": "allowed_with_change_notice",
            "attribution_template": "出典: 国税庁 適格請求書発行事業者公表サイト (PDL v1.0)",
            "datasets": ["invoice_registrants (13,801 delta + monthly 4M bulk)"],
        },
        {
            "id": "egov_law_cc_by_4_0",
            "label": "e-Gov 法令検索",
            "license_code": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/deed.ja",
            "redistribution": "allowed_with_attribution",
            "commercial_use": "allowed",
            "modification": "allowed",
            "attribution_template": "出典: e-Gov 法令検索 (CC BY 4.0)",
            "datasets": ["laws (9,484)", "law_articles (353,278)", "law_articles.body_en"],
        },
        {
            "id": "maff_kessei_gov_standard",
            "label": "農林水産省 交付決定 / 採択結果",
            "license_code": "GOV_STANDARD",
            "license_url": "https://www.maff.go.jp/j/use/",
            "redistribution": "allowed_with_attribution",
            "commercial_use": "allowed",
            "modification": "allowed",
            "attribution_template": "出典: 農林水産省 (政府標準利用規約 2.0)",
            "datasets": ["adoption_records (subset)", "programs (MAFF subset)"],
        },
        {
            "id": "meti_subsidy_gov_standard",
            "label": "経済産業省 補助金 / 認定制度",
            "license_code": "GOV_STANDARD",
            "license_url": "https://www.meti.go.jp/main/rules.html",
            "redistribution": "allowed_with_attribution",
            "commercial_use": "allowed",
            "modification": "allowed",
            "attribution_template": "出典: 経済産業省 (政府標準利用規約 2.0)",
            "datasets": [
                "programs (METI subset, S/A/B/C)",
                "am_amendment_snapshot (METI 補助金 法令改正履歴)",
            ],
        },
        {
            "id": "courts_judgments_public_domain",
            "label": "裁判所 判決速報 / 公開判例",
            "license_code": "PUBLIC_DOMAIN",
            "license_url": "https://www.courts.go.jp/",
            "redistribution": "allowed",
            "commercial_use": "allowed",
            "modification": "allowed",
            "attribution_template": "出典: 最高裁判所 (公開判例)",
            "datasets": ["court_decisions (2,065)"],
        },
        {
            "id": "kaikei_kensa_gov_13",
            "label": "会計検査院 不当・指摘事例",
            "license_code": "GOV_13",
            "license_url": "https://www.jbaudit.go.jp/",
            "redistribution": "allowed_with_attribution",
            "commercial_use": "allowed",
            "modification": "allowed",
            "attribution_template": "出典: 会計検査院 (著作権法 §13 政府著作物)",
            "datasets": ["enforcement_cases (1,185)", "am_enforcement_detail (22,258)"],
        },
        {
            "id": "jfc_proprietary_excerpt",
            "label": "日本政策金融公庫 制度融資",
            "license_code": "PROPRIETARY_QUOTE_OK",
            "license_url": "https://www.jfc.go.jp/",
            "redistribution": "quote_only",
            "commercial_use": "quote_only",
            "modification": "not_allowed",
            "attribution_template": "出典: 日本政策金融公庫 (引用範囲のみ)",
            "datasets": ["loan_programs (108)"],
        },
        {
            "id": "jpcite_compiled_cc_by_4_0",
            "label": "jpcite 編集データ (公表値の集計・補助インデックス)",
            "license_code": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/deed.ja",
            "redistribution": "allowed_with_attribution",
            "commercial_use": "allowed",
            "modification": "allowed_with_change_notice",
            "attribution_template": "出典: jpcite (Bookyou株式会社, CC BY 4.0)",
            "datasets": [
                "facts_registry.json",
                "fence_registry.json",
                "exclusion_rules (181)",
                "compatibility matrix (am_compat_matrix sourced subset)",
            ],
        },
    ],
}


def _license_matrix_text() -> str:
    return json.dumps(_LICENSE_MATRIX, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 5. sources_catalog.json (14-dataset primary-source catalog)
# ---------------------------------------------------------------------------


_SOURCES_CATALOG: dict[str, Any] = {
    "schema_version": "1.0",
    "namespace": "mcp://jpcite/sources_catalog.json",
    "description": (
        "jpcite が取り込む 14 一次資料データセットの権威 URL + 取得頻度 + 取得方式. "
        "agent はソース URL を回答へ差し込む際, 本 catalog の primary_url を SOT として "
        "用いること. aggregator (noukaweb / hojyokin-portal 等) からの引用は禁止."
    ),
    "row_count": 14,
    "datasets": [
        {
            "id": "egov_law",
            "label": "e-Gov 法令検索",
            "primary_url": "https://laws.e-gov.go.jp/",
            "license_ref": "egov_law_cc_by_4_0",
            "refresh_cadence": "weekly",
            "ingest_method": "API + incremental_law_load",
            "row_count_jpcite": "9,484 law catalog stubs + 6,493 full-text + 353,278 articles",
        },
        {
            "id": "nta_invoice",
            "label": "国税庁 適格請求書発行事業者公表サイト",
            "primary_url": "https://www.invoice-kohyo.nta.go.jp/",
            "license_ref": "nta_invoice_pdl_v1",
            "refresh_cadence": "monthly_bulk + weekly_delta",
            "ingest_method": "zenken bulk + delta diff",
            "row_count_jpcite": "13,801 delta + 4M monthly bulk wire",
        },
        {
            "id": "maff_kessei",
            "label": "農林水産省 交付決定 Excel",
            "primary_url": "https://www.maff.go.jp/j/budget/yosan_kansi/sikkou/",
            "license_ref": "maff_kessei_gov_standard",
            "refresh_cadence": "quarterly",
            "ingest_method": "browser_walk + Excel parse",
            "row_count_jpcite": "subset of 201,845 jpi_adoption_records",
        },
        {
            "id": "meti_subsidy",
            "label": "経済産業省 補助金 (jGrants 連携 + 各省サイト)",
            "primary_url": "https://www.meti.go.jp/",
            "license_ref": "meti_subsidy_gov_standard",
            "refresh_cadence": "weekly",
            "ingest_method": "jGrants_api + scrape",
            "row_count_jpcite": "programs subset (METI 主管)",
        },
        {
            "id": "jgrants",
            "label": "デジタル庁 jGrants",
            "primary_url": "https://www.jgrants-portal.go.jp/",
            "license_ref": "meti_subsidy_gov_standard",
            "refresh_cadence": "daily",
            "ingest_method": "jGrants_api",
            "row_count_jpcite": "programs subset (jGrants 公開)",
        },
        {
            "id": "courts_judgments",
            "label": "裁判所 判決速報",
            "primary_url": "https://www.courts.go.jp/",
            "license_ref": "courts_judgments_public_domain",
            "refresh_cadence": "weekly",
            "ingest_method": "rss + html_parse",
            "row_count_jpcite": "2,065 court_decisions",
        },
        {
            "id": "kaikei_kensa",
            "label": "会計検査院 検査報告",
            "primary_url": "https://www.jbaudit.go.jp/report/index.html",
            "license_ref": "kaikei_kensa_gov_13",
            "refresh_cadence": "annual + ad-hoc",
            "ingest_method": "pdf_parse + footnote_extract",
            "row_count_jpcite": "1,185 enforcement_cases + 22,258 am_enforcement_detail",
        },
        {
            "id": "jfc_loan",
            "label": "日本政策金融公庫 制度融資",
            "primary_url": "https://www.jfc.go.jp/",
            "license_ref": "jfc_proprietary_excerpt",
            "refresh_cadence": "monthly",
            "ingest_method": "playwright_site_search",
            "row_count_jpcite": "108 loan_programs (3-axis 担保/個保/第三者)",
        },
        {
            "id": "nta_saiketsu",
            "label": "国税不服審判所 裁決事例",
            "primary_url": "https://www.kfs.go.jp/",
            "license_ref": "kaikei_kensa_gov_13",
            "refresh_cadence": "quarterly",
            "ingest_method": "html_parse",
            "row_count_jpcite": "~140 nta_saiketsu",
        },
        {
            "id": "nta_tsutatsu",
            "label": "国税庁 通達",
            "primary_url": "https://www.nta.go.jp/law/tsutatsu/",
            "license_ref": "kaikei_kensa_gov_13",
            "refresh_cadence": "ad-hoc",
            "ingest_method": "html_parse",
            "row_count_jpcite": "3,221 nta_tsutatsu_index",
        },
        {
            "id": "houjin_master",
            "label": "国税庁 法人番号公表サイト",
            "primary_url": "https://www.houjin-bangou.nta.go.jp/",
            "license_ref": "nta_invoice_pdl_v1",
            "refresh_cadence": "monthly",
            "ingest_method": "csv_bulk",
            "row_count_jpcite": "166,969 corporate_entity am_entities",
        },
        {
            "id": "egov_pubcomment",
            "label": "e-Gov パブリックコメント",
            "primary_url": "https://public-comment.e-gov.go.jp/",
            "license_ref": "egov_law_cc_by_4_0",
            "refresh_cadence": "weekly",
            "ingest_method": "rss + html_parse",
            "row_count_jpcite": "pubcomment_announcement (incremental)",
        },
        {
            "id": "kokkai",
            "label": "国会会議録検索システム",
            "primary_url": "https://kokkai.ndl.go.jp/",
            "license_ref": "egov_law_cc_by_4_0",
            "refresh_cadence": "daily",
            "ingest_method": "ndl_api",
            "row_count_jpcite": "kokkai_utterance + shingikai_minutes (incremental)",
        },
        {
            "id": "municipality_subsidy",
            "label": "自治体補助金 page diff (1,741 自治体)",
            "primary_url": "https://*.lg.jp/ (per 自治体)",
            "license_ref": "kaikei_kensa_gov_13",
            "refresh_cadence": "weekly",
            "ingest_method": "browser_walk + diff",
            "row_count_jpcite": "67 自治体 1st pass (47 都道府県 + 20 政令市)",
        },
    ],
}


def _sources_catalog_text() -> str:
    return json.dumps(_SOURCES_CATALOG, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Resource registration
# ---------------------------------------------------------------------------


_JPCITE_RESOURCES: tuple[dict[str, Any], ...] = (
    {
        "uri": "mcp://jpcite/facts_registry.json",
        "name": "jpcite_facts_registry",
        "description": (
            "jpcite 公開数値 SOT — 24 facts + guards.banned_terms + numeric_ranges. "
            "agent は tool 呼び出し前に必ず本 resource を読み, 最新値で応答せよ."
        ),
        "mime_type": "application/json",
        "provider": _facts_registry_text,
    },
    {
        "uri": "mcp://jpcite/legal/fence.md",
        "name": "jpcite_legal_fence",
        "description": (
            "7 業法 fence (税理士法 §52 / 弁護士法 §72 / 司法書士法 §73 / 行政書士法 §19 "
            "/ 社労士法 §27 / 中小企業診断士 / 弁理士法 §75). do_not / may_do + JA/EN "
            "disclaimer 文。agent 出力に差し込み必須."
        ),
        "mime_type": "text/markdown",
        "provider": _fence_md_text,
    },
    {
        "uri": "mcp://jpcite/glossary.json",
        "name": "jpcite_glossary",
        "description": (
            "jpcite 用語集 — 補助金 / 助成金 / 融資 / 税制 / 認定制度. plain-Japanese "
            "+ technical + legal explanation + canonical aliases. customer-facing "
            "言い回しはここから引くこと."
        ),
        "mime_type": "application/json",
        "provider": _glossary_text,
    },
    {
        "uri": "mcp://jpcite/license_matrix.json",
        "name": "jpcite_license_matrix",
        "description": (
            "8-row license inventory — PDL v1.0 / CC-BY 4.0 / 政府著作物 §13 / "
            "PROPRIETARY_QUOTE_OK. agent は再配布 / 引用範囲を判断する際の SOT として "
            "使用すること."
        ),
        "mime_type": "application/json",
        "provider": _license_matrix_text,
    },
    {
        "uri": "mcp://jpcite/sources_catalog.json",
        "name": "jpcite_sources_catalog",
        "description": (
            "14 一次資料 catalog — primary_url + refresh_cadence + ingest_method. "
            "aggregator (noukaweb / hojyokin-portal) からの引用は禁止, 本 catalog の "
            "primary_url を SOT として使用すること."
        ),
        "mime_type": "application/json",
        "provider": _sources_catalog_text,
    },
)


def list_jpcite_resources() -> list[dict[str, str]]:
    """Return MCP-style resource list (no provider callable)."""
    return [
        {
            "uri": r["uri"],
            "name": r["name"],
            "description": r["description"],
            "mimeType": r["mime_type"],
        }
        for r in _JPCITE_RESOURCES
    ]


def read_jpcite_resource(uri: str) -> dict[str, Any]:
    """Return MCP-style resource read payload."""
    for r in _JPCITE_RESOURCES:
        if r["uri"] == uri:
            text = r["provider"]()
            return {
                "contents": [
                    {
                        "uri": r["uri"],
                        "mimeType": r["mime_type"],
                        "text": text,
                    }
                ]
            }
    raise KeyError(f"unknown jpcite resource URI: {uri}")


def register_jpcite_resources(mcp: Any) -> None:
    """Wire the 5 jpcite resources into a FastMCP server at boot.

    Idempotent + tolerant of FastMCP versions without ``.resource()``.
    """
    try:
        for r in _JPCITE_RESOURCES:
            provider = r["provider"]

            def _make_cb(fn: Callable[[], str]) -> Callable[[], str]:
                def _cb() -> str:
                    return fn()

                return _cb

            mcp.resource(
                r["uri"],
                name=r["name"],
                description=r["description"],
                mime_type=r["mime_type"],
            )(_make_cb(provider))
    except AttributeError:
        # FastMCP without .resource() — silently skip.
        pass


__all__ = [
    "list_jpcite_resources",
    "read_jpcite_resource",
    "register_jpcite_resources",
]
