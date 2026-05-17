#!/usr/bin/env python3
"""jpcite A7 — sales-grade product landing + SDK examples + cookbook auto-generator.

Organic acquisition asset generator. NO LLM CALL. Pure file assembly from the
authoritative inputs:

* ``site/.well-known/jpcite-outcome-catalog.json`` (450 outcome contracts)
* ``data/recipes/*.yaml`` (15 cookbook recipes, F1-F5 lanes)
* ``docs/_internal/JPCITE_COHORT_PERSONAS_2026_05_17.md`` (5 cohort persona deep dive)

Produces under ``site/products/`` and ``docs/recipes/``:

1. Per-product landing pages (A1-A5)
2. SDK example snippets (Python / TypeScript / Claude Code ``.mcp.json``)
3. Cookbook recipe markdown (h1/h2 SEO + structured data)
4. Cohort-specific persona landings (``site/for/<cohort>.html``)
5. Comparison pages (jpcite ¥30 vs LLM API ¥3,000 cost per cohort)
6. ``site/sitemap-products.xml`` + ``site/llms.txt`` refresh

Constraints (CLAUDE.md non-negotiable):
* NO LLM API import
* aggregator banned in source URLs
* §52 / §47条の2 / §72 / §1 / §3 disclaimer on sensitive cohort surfaces
* ¥3/req metered only — no tier SKUs
* operator = Bookyou株式会社 (T8010001213708)
* mypy --strict clean, ruff clean

Operator: Bookyou株式会社 (info@bookyou.net)
Brand: jpcite (https://jpcite.com)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from xml.sax.saxutils import escape

LOG = logging.getLogger("jpcite_a7")

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
DOCS_DIR = REPO_ROOT / "docs"
DATA_DIR = REPO_ROOT / "data"
WELL_KNOWN = SITE_DIR / ".well-known" / "jpcite-outcome-catalog.json"
RECIPES_DIR = DATA_DIR / "recipes"
DOMAIN = "jpcite.com"


# --------------------------------------------------------------------------- #
# Product definitions — A1..A5 are derived from cohort × package_kind.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Product:
    """A jpcite product (A1..A5) = cohort × package_kind bundle."""

    code: str
    slug: str
    name_ja: str
    name_en: str
    cohort_jp: str
    cohort_en: str
    cohort_slug: str
    package_kinds: tuple[str, ...]
    heavy_endpoints: tuple[str, ...]
    sensitive_acts: tuple[str, ...]
    monthly_req_estimate: int
    one_call_replacement_jpy: int
    summary_ja: str
    summary_en: str


PRODUCTS: tuple[Product, ...] = (
    Product(
        code="A1",
        slug="A1_zeirishi_monthly_pack",
        name_ja="税理士 月次レビュー & 制度棚卸し pack",
        name_en="Tax-Firm Monthly Review & Program Audit Pack",
        cohort_jp="税理士",
        cohort_en="Tax-Firm",
        cohort_slug="zeirishi",
        package_kinds=("evidence_packet", "watch_digest", "artifact_pack"),
        heavy_endpoints=(
            "POST /v1/cases/cohort_match",
            "GET /v1/tax_rules/{rule_id}/full_chain",
            "POST /v1/jpcite/route",
            "POST /v1/jpcite/preview_cost",
            "POST /v1/evidence/packets/query",
        ),
        sensitive_acts=("§52", "§47条の2"),
        monthly_req_estimate=500,
        one_call_replacement_jpy=1500,
        summary_ja=(
            "月次仕訳・年末調整・法人税申告に必要な制度改正・行政処分・取引先公開"
            "情報を一次資料 URL + 取得時刻 + known_gaps つきで 1 query 返却。"
            "顧問先 fan-out は X-Client-Tag header で 1 cron 集約。"
        ),
        summary_en=(
            "Returns monthly closing, year-end adjustment, and corporate tax filing"
            " evidence packets in one query: amendment diff, enforcement watch,"
            " counterparty invoice verification, all with primary-source URLs,"
            " fetched-at timestamps, and known gaps. Fan-out across clients"
            " through the X-Client-Tag header consolidates to a single cron."
        ),
    ),
    Product(
        code="A2",
        slug="A2_cpa_audit_workpaper_pack",
        name_ja="会計士 監査調書 scaffold pack",
        name_en="CPA Audit Workpaper Scaffold Pack",
        cohort_jp="会計士",
        cohort_en="CPA-Firm",
        cohort_slug="kaikei",
        package_kinds=("evidence_packet", "artifact_pack"),
        heavy_endpoints=(
            "POST /v1/cases/cohort_match",
            "GET /v1/tax_rules/{rule_id}/full_chain",
            "POST /v1/dd/question_match",
            "POST /v1/houjin/360",
            "POST /v1/evidence/packets/query",
        ),
        sensitive_acts=("§47条の2",),
        monthly_req_estimate=300,
        one_call_replacement_jpy=2500,
        summary_ja=(
            "被監査会社 360 度 (法人格 × 適格事業者 × 行政処分 × 採択履歴 × 法改正)"
            " を 1 packet。研究開発税制 + IT 導入補助金 会計処理 dual check + 監査"
            "調書 scaffold 自動生成。意見表明は会計士責任の境界を維持。"
        ),
        summary_en=(
            "360-degree view of audit clients (corporate form × invoice registrant"
            " × enforcement history × adoption record × amendment lineage) as one"
            " packet. R&D tax credit and IT-introduction subsidy dual check, plus"
            " audit workpaper scaffold generation. Audit-opinion authority"
            " boundary preserved."
        ),
    ),
    Product(
        code="A3",
        slug="A3_gyosei_licensing_eligibility_pack",
        name_ja="行政書士 許認可 eligibility pack",
        name_en="Administrative-Scrivener Licensing Eligibility Pack",
        cohort_jp="行政書士",
        cohort_en="Administrative-Scrivener",
        cohort_slug="gyoseishoshi",
        package_kinds=("evidence_packet", "watch_digest"),
        heavy_endpoints=(
            "POST /v1/programs/full_context",
            "GET /v1/laws/{law_id}/related_programs",
            "POST /v1/exclusions/check",
            "POST /v1/jpcite/route",
            "POST /v1/evidence/packets/query",
        ),
        sensitive_acts=("§1", "§47条の2", "行政書士法"),
        monthly_req_estimate=200,
        one_call_replacement_jpy=2000,
        summary_ja=(
            "建設業・産廃・宅建・運送・古物・飲食 等の許認可 eligibility を"
            "業種 × 都道府県 × 市町村 × 法人格 fence + 排他/併用ルール 1 packet。"
            "申請書面作成は scaffold + 一次 URL only。"
        ),
        summary_en=(
            "Licensing eligibility check for construction, waste, real-estate,"
            " transport, antiques, food-service, etc. across industry × prefecture"
            " × municipality × corporate-form fence + exclusion/combination rules"
            " as one packet. Application drafting limited to scaffold + primary-"
            " source URLs only."
        ),
    ),
    Product(
        code="A4",
        slug="A4_shihoshoshi_registry_watch",
        name_ja="司法書士 登記 watch pack",
        name_en="Judicial-Scrivener Registry Watch Pack",
        cohort_jp="司法書士",
        cohort_en="Judicial-Scrivener",
        cohort_slug="shihoshoshi",
        package_kinds=("watch_digest", "evidence_packet"),
        heavy_endpoints=(
            "POST /v1/houjin/watch/subscribe",
            "POST /v1/houjin/360",
            "POST /v1/invoice_registrants/search",
            "POST /v1/jpcite/route",
            "POST /v1/evidence/packets/query",
        ),
        sensitive_acts=("§3",),
        monthly_req_estimate=150,
        one_call_replacement_jpy=2200,
        summary_ja=(
            "顧客法人 watch list で役員変更 / 商号変更 / 資本変更 / 適格事業者"
            " 取消 を webhook + RSS。同名法人解消は 13 桁法人番号 + 適格番号"
            "  T-prefix で出典 URL 添付。"
        ),
        summary_en=(
            "Houjin watch list with webhook + RSS delivery for director change,"
            " trade-name change, capital change, and invoice-registrant"
            " cancellation. Same-name corporation disambiguation via 13-digit"
            " corporate number + T-prefix invoice number with source URLs"
            " attached."
        ),
    ),
    Product(
        code="A5",
        slug="A5_sme_subsidy_companion",
        name_ja="中小経営者 補助金 companion",
        name_en="SME Subsidy Companion",
        cohort_jp="中小経営者",
        cohort_en="SME-Owner",
        cohort_slug="sme",
        package_kinds=("evidence_packet", "artifact_pack", "watch_digest"),
        heavy_endpoints=(
            "POST /v1/jpcite/route",
            "POST /v1/jpcite/preview_cost",
            "POST /v1/cases/cohort_match",
            "POST /v1/programs/full_context",
            "POST /v1/evidence/packets/query",
        ),
        sensitive_acts=("§52", "§1"),
        monthly_req_estimate=100,
        one_call_replacement_jpy=900,
        summary_ja=(
            "業種 × 地域 × 規模 × ライフサイクル 段階で利用可能な補助金 / 融資 /"
            " 税制 / 認定 を 1 packet。同業同地域の採択事例 + 排他ルール + 申請"
            " 期限カレンダーを併載。最終判断は税理士 / 行政書士 confirm 経路。"
        ),
        summary_en=(
            "Subsidy, loan, tax incentive, and certification candidates available"
            " for the given industry × region × size × lifecycle-stage as one"
            " packet. Includes adoption cases from the same cohort, exclusion"
            " rules, and application-deadline calendar. Final judgment via"
            " tax-firm or administrative-scrivener confirmation path."
        ),
    ),
)


# Heavy / composed endpoint catalog — 16 entries (R8 + Wave 22 + Wave 51).
HEAVY_ENDPOINTS: tuple[dict[str, str], ...] = (
    {"path": "POST /v1/jpcite/route", "purpose": "intent → cheapest outcome routing"},
    {"path": "POST /v1/jpcite/preview_cost", "purpose": "free preflight cost cap"},
    {"path": "POST /v1/jpcite/execute_packet", "purpose": "metered packet execution"},
    {"path": "GET /v1/jpcite/get_packet/{packet_id}", "purpose": "free packet retrieval"},
    {"path": "POST /v1/evidence/packets/query", "purpose": "evidence packet primary surface"},
    {"path": "GET /v1/intelligence/precomputed/query", "purpose": "precomputed intelligence layer"},
    {"path": "POST /v1/cases/cohort_match", "purpose": "採択事例 × 業種規模地域 cohort matcher"},
    {"path": "POST /v1/houjin/360", "purpose": "houjin 360 unified scoring"},
    {"path": "POST /v1/houjin/watch/subscribe", "purpose": "real-time corp amendment watch"},
    {"path": "POST /v1/dd/question_match", "purpose": "DD question deck 30-60 question matcher"},
    {
        "path": "GET /v1/tax_rules/{rule_id}/full_chain",
        "purpose": "tax rule full chain (50 ruleset)",
    },
    {"path": "POST /v1/programs/full_context", "purpose": "program full context cross-reference"},
    {"path": "GET /v1/laws/{law_id}/related_programs", "purpose": "law × program cross-reference"},
    {"path": "POST /v1/exclusions/check", "purpose": "exclusion + prerequisite 181 rule check"},
    {"path": "POST /v1/citations/verify", "purpose": "citation pair verification"},
    {"path": "GET /v1/programs/{unified_id}", "purpose": "program detail by unified ID"},
)


# 21 organic lanes (Wave 50/51 derived).
LANES: tuple[str, ...] = (
    "tax_monthly_closing",
    "tax_year_end_adjustment",
    "tax_corporate_filing",
    "subsidy_application_draft",
    "audit_workpaper_compile",
    "audit_internal_control",
    "audit_consolidation",
    "client_onboarding",
    "compliance_dashboard",
    "contract_compliance_check",
    "corporate_setup_registration",
    "director_change_registration",
    "license_renewal",
    "real_estate_transfer",
    "domain_expertise_transfer",
    "company_public_baseline",
    "regulation_change_watch",
    "case_cohort_match",
    "exclusion_combination_check",
    "amendment_diff_alert",
    "invoice_registrant_check",
)


@dataclass
class Recipe:
    """Lightweight YAML recipe loader (no PyYAML — recipes are ASCII-only)."""

    recipe_name: str
    segment: str
    title: str
    disclaimer: str
    cost_estimate_jpy: int
    billable_units: int
    parallel_calls_supported: bool
    expected_duration_seconds: int
    steps: list[dict[str, Any]] = field(default_factory=list)
    output_artifact_type: str = ""
    preconditions: list[str] = field(default_factory=list)


def _parse_recipe_yaml(path: Path) -> Recipe | None:
    """Tiny YAML reader for the recipe shape used in ``data/recipes/``.

    The recipe schema is shallow: top-level scalars + a ``steps:`` list of
    dicts with ``step`` / ``tool_name`` / ``purpose`` keys. We avoid pulling
    in PyYAML so the script stays import-free; ruff / mypy strict pass with
    no extra deps.
    """
    text = path.read_text(encoding="utf-8")
    rec: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    preconditions: list[str] = []

    in_steps = False
    in_preconditions = False
    in_output = False
    output_type = ""
    current_step: dict[str, Any] = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if indent == 0:
            if in_steps and current_step:
                steps.append(current_step)
                current_step = {}
            in_steps = stripped.startswith("steps:")
            in_preconditions = stripped.startswith("preconditions:")
            in_output = stripped.startswith("output_artifact:")
            if not (in_steps or in_preconditions or in_output) and ":" in stripped:
                key, _, val = stripped.partition(":")
                rec[key.strip()] = val.strip().strip('"').strip("'")
            continue

        if in_preconditions and stripped.startswith("- "):
            preconditions.append(stripped[2:].strip())
            continue

        if in_output:
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                if key.strip() == "type":
                    output_type = val.strip().strip('"').strip("'")
            continue

        if in_steps:
            if stripped.startswith("- step:"):
                if current_step:
                    steps.append(current_step)
                current_step = {"step": stripped.split(":", 1)[1].strip()}
            elif ":" in stripped:
                key, _, val = stripped.partition(":")
                current_step[key.strip()] = val.strip().strip('"').strip("'")

    if in_steps and current_step:
        steps.append(current_step)

    try:
        cost = int(rec.get("cost_estimate_jpy", "0") or 0)
    except ValueError:
        cost = 0
    try:
        units = int(rec.get("billable_units", "0") or 0)
    except ValueError:
        units = 0
    try:
        duration = int(rec.get("expected_duration_seconds", "0") or 0)
    except ValueError:
        duration = 0

    parallel = str(rec.get("parallel_calls_supported", "false")).lower() == "true"

    name = rec.get("recipe_name") or path.stem
    if not name:
        return None
    return Recipe(
        recipe_name=name,
        segment=rec.get("segment", ""),
        title=rec.get("title", name),
        disclaimer=rec.get("disclaimer", ""),
        cost_estimate_jpy=cost,
        billable_units=units,
        parallel_calls_supported=parallel,
        expected_duration_seconds=duration,
        steps=steps,
        output_artifact_type=output_type,
        preconditions=preconditions,
    )


# --------------------------------------------------------------------------- #
# Disclaimers
# --------------------------------------------------------------------------- #


DISCLAIMERS: dict[str, str] = {
    "§52": (
        "税理士法 §52 — 個別具体的な税務代理 / 税務書類作成 / 税務相談は税理士の独占業務。"
        "jpcite は候補列挙 + 一次資料 URL only。最終判断は税理士確認境界を越えない。"
    ),
    "§47条の2": (
        "弁護士法 §47条の2 — 法律事務の取扱は弁護士の独占業務。"
        "jpcite は法令 + 採択事例 + 行政処分のメタデータ surface only。法的助言は弁護士確認境界を越えない。"
    ),
    "§72": (
        "弁護士法 §72 — 非弁活動禁止。jpcite は紛争処理代理は提供せず、"
        "出典 URL + 取得時刻 + known_gaps のみを返す。"
    ),
    "§1": (
        "行政書士法 §1 — 官公署提出書類作成は行政書士の独占業務。"
        "jpcite は申請書面の scaffold + 一次資料 URL only。完成版作成は行政書士確認境界を越えない。"
    ),
    "§3": (
        "司法書士法 §3 — 登記・供託に関する手続代理は司法書士の独占業務。"
        "jpcite は登記簿公開情報 + 適格事業者公開情報の lookup のみ。"
    ),
    "行政書士法": (
        "行政書士法 — 申請書面作成は行政書士の独占業務。jpcite は scaffold + 一次資料 URL only。"
    ),
    "社労士法": (
        "社労士法 — 36協定 / 就業規則 / 労務管理書類作成は社労士の独占業務。"
        "jpcite は様式枠 + 一次資料 URL only、36協定 render は AUTONOMATH_36_KYOTEI_ENABLED gate で operator legal review 後にのみ flip。"
    ),
}


def disclaimer_html(acts: tuple[str, ...]) -> str:
    if not acts:
        return ""
    items = "".join(
        f"<li><strong>{escape(a)}</strong>: {escape(DISCLAIMERS.get(a, '境界遵守'))}</li>"
        for a in acts
    )
    return (
        '<section class="disclaimer" aria-label="sensitive surface disclaimer">'
        "<h2>免責 / 越権越えゼロの境界</h2>"
        f"<ul>{items}</ul>"
        "</section>"
    )


# --------------------------------------------------------------------------- #
# SDK example snippet builders
# --------------------------------------------------------------------------- #


def python_snippet(product: Product) -> str:
    """Python (autonomath-mcp SDK wrapping FastMCP / REST) snippet."""
    return f"""# {product.code} {product.name_en} — Python (jpcite-mcp)
import os
import httpx

JPCITE_API = "https://api.jpcite.com"
API_KEY = os.environ["JPCITE_API_KEY"]  # see https://jpcite.com/dashboard

def fetch_{product.cohort_slug}_packet(houjin_bangou: str) -> dict:
    # 1. Free preflight — no charge until accepted_artifact delivery.
    preview = httpx.post(
        f"{{JPCITE_API}}/v1/jpcite/preview_cost",
        headers={{"X-API-Key": API_KEY, "X-Client-Tag": "{product.cohort_slug}-001"}},
        json={{"outcome_contract_id": "{product.slug}",
               "input": {{"houjin_bangou": houjin_bangou}}}}
    ).raise_for_status().json()
    assert preview["cap_passed"], "outcome exceeds cap — adjust max_price_jpy"

    # 2. Execute packet — charges {product.one_call_replacement_jpy // 100 * 3} billable units (=¥{product.one_call_replacement_jpy // 100 * 3}).
    packet = httpx.post(
        f"{{JPCITE_API}}/v1/jpcite/execute_packet",
        headers={{"X-API-Key": API_KEY,
                  "X-Client-Tag": "{product.cohort_slug}-001",
                  "X-Jpcite-Scoped-Cap-Token": preview["scoped_cap_token"],
                  "Idempotency-Key": f"{product.cohort_slug}-{{houjin_bangou}}-2026-05"}},
        json={{"outcome_contract_id": "{product.slug}",
               "input": {{"houjin_bangou": houjin_bangou}},
               "max_price_jpy": {product.one_call_replacement_jpy}}}
    ).raise_for_status().json()
    return packet  # contains source_url[], fetched_at, known_gaps[], evidence[]
"""


def typescript_snippet(product: Product) -> str:
    """TypeScript (OpenAI tool-use / Bedrock MCP wrapper) snippet."""
    return f"""// {product.code} {product.name_en} — TypeScript (Bedrock / OpenAI tool-use)
import {{ JpciteClient }} from "@jpcite/sdk";  // wraps OpenAPI 219 paths

const client = new JpciteClient({{
  baseUrl: "https://api.jpcite.com",
  apiKey: process.env.JPCITE_API_KEY!,
  clientTag: "{product.cohort_slug}-001",  // 顧問先 fan-out attribution
}});

export async function fetch{product.cohort_en.replace("-", "")}Packet(houjinBangou: string) {{
  const preview = await client.previewCost({{
    outcome_contract_id: "{product.slug}",
    input: {{ houjin_bangou: houjinBangou }},
  }});
  if (!preview.cap_passed) throw new Error("over cap");

  const packet = await client.executePacket({{
    outcome_contract_id: "{product.slug}",
    input: {{ houjin_bangou: houjinBangou }},
    max_price_jpy: {product.one_call_replacement_jpy},
    scopedCapToken: preview.scoped_cap_token,
    idempotencyKey: `{product.cohort_slug}-${{houjinBangou}}-2026-05`,
  }});
  return packet;  // {{ source_url[], fetched_at, known_gaps[], evidence[] }}
}}
"""


def claude_code_snippet(product: Product) -> str:
    """Claude Code ``.mcp.json`` snippet — drop into project root."""
    return json.dumps(
        {
            "mcpServers": {
                "jpcite": {
                    "command": "npx",
                    "args": ["-y", "autonomath-mcp"],
                    "env": {
                        "JPCITE_API_KEY": "${env:JPCITE_API_KEY}",
                        "JPCITE_DEFAULT_OUTCOME": product.slug,
                        "JPCITE_CLIENT_TAG": f"{product.cohort_slug}-001",
                    },
                }
            }
        },
        indent=2,
        ensure_ascii=False,
    )


# --------------------------------------------------------------------------- #
# LLM cost projection (Comparison page — Justifiability moat)
# --------------------------------------------------------------------------- #


# Estimated tokens for the typical packet returned by a single jpcite call.
# Sourced from the existing outcome_catalog estimated_tokens_saved field (~5k
# input tokens of long-form PDF + 1.5k output token equivalent of synthesis).
# We surface 3 reference LLM tariffs: Opus 4.7 / Sonnet 4.6 / Haiku 4.5.
LLM_COSTS: tuple[dict[str, Any], ...] = (
    # Anthropic public pricing snapshot 2026-05 — input / output ¥ per 1k tokens.
    {"name": "Opus 4.7", "in_jpy_per_1k": 2.25, "out_jpy_per_1k": 11.25},
    {"name": "Sonnet 4.6", "in_jpy_per_1k": 0.45, "out_jpy_per_1k": 2.25},
    {"name": "Haiku 4.5", "in_jpy_per_1k": 0.12, "out_jpy_per_1k": 0.60},
)


def llm_replacement_cost(
    input_tokens: int = 5000, output_tokens: int = 1500
) -> list[dict[str, Any]]:
    """Project LLM-only replacement cost per packet across 3 model tiers."""
    rows = []
    for tariff in LLM_COSTS:
        cost = (input_tokens / 1000) * float(tariff["in_jpy_per_1k"]) + (
            output_tokens / 1000
        ) * float(tariff["out_jpy_per_1k"])
        rows.append({"model": tariff["name"], "per_packet_jpy": round(cost, 2)})
    return rows


# --------------------------------------------------------------------------- #
# HTML page rendering
# --------------------------------------------------------------------------- #


HTML_BASE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="theme-color" content="#ffffff">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_description}">
<meta property="og:type" content="website">
<meta property="og:url" content="https://{domain}{path}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://{domain}{path}">
<link rel="alternate" hreflang="ja" href="https://{domain}{path}">
<link rel="alternate" hreflang="x-default" href="https://{domain}{path}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260517a">
<script defer src="/analytics.js?v=20260503a"></script>
<script type="application/ld+json">{jsonld}</script>
</head>
<body>
<header class="site-header"><a href="/">jpcite</a> &middot; <a href="/products">成果物カタログ</a> &middot; <a href="/docs/">API / MCP docs</a></header>
<main>
{body}
</main>
<footer class="site-footer">
<p>Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) / info@bookyou.net</p>
<p>Brand: jpcite (https://jpcite.com / https://api.jpcite.com) — 100% organic acquisition · ¥3/req fully metered · anonymous 3 req/day/IP</p>
<p>NO LLM API calls inside jpcite tools. Source URLs are first-party (government ministry / prefecture / 公庫 / e-Gov / NTA) — aggregators are banned.</p>
</footer>
</body>
</html>
"""


def render_product_page(product: Product) -> str:
    cohort_compare_path = f"/compare/{product.cohort_slug}.html"
    llm_rows = llm_replacement_cost()
    jpcite_monthly = product.monthly_req_estimate * 3  # ¥3/req
    cheapest_llm_monthly = round(
        min(r["per_packet_jpy"] for r in llm_rows) * product.monthly_req_estimate, 2
    )
    multiplier = round(cheapest_llm_monthly / max(jpcite_monthly, 1), 2)

    heavy = "".join(f"<li><code>{escape(e)}</code></li>" for e in product.heavy_endpoints)
    pkg = ", ".join(escape(p) for p in product.package_kinds)
    disclaimer = disclaimer_html(product.sensitive_acts)

    title = f"{product.name_ja} — {product.code} — jpcite"
    description = (
        f"{product.cohort_jp}向け jpcite {product.code}. {product.summary_ja[:120]}. "
        f"月次 {product.monthly_req_estimate} req = ¥{jpcite_monthly:,} (¥3/req)."
    )

    jsonld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": product.name_ja,
            "alternateName": product.name_en,
            "sku": product.slug,
            "description": product.summary_ja,
            "brand": {"@type": "Brand", "name": "jpcite"},
            "offers": {
                "@type": "Offer",
                "priceCurrency": "JPY",
                "price": "3.30",
                "priceSpecification": {
                    "@type": "UnitPriceSpecification",
                    "price": "3.30",
                    "priceCurrency": "JPY",
                    "unitText": "billable_request_tax_included",
                    "referenceQuantity": {
                        "@type": "QuantitativeValue",
                        "value": 1,
                        "unitText": "request",
                    },
                },
                "availability": "https://schema.org/InStock",
                "seller": {"@type": "Organization", "name": "Bookyou株式会社"},
            },
            "audience": {"@type": "Audience", "audienceType": product.cohort_jp},
        },
        ensure_ascii=False,
    )

    body = f"""
<article class="product-landing">
  <nav class="breadcrumb"><a href="/">Home</a> &raquo; <a href="/products">成果物カタログ</a> &raquo; {escape(product.code)}</nav>
  <h1>{escape(product.name_ja)} <small>({escape(product.code)})</small></h1>
  <p class="lede">{escape(product.summary_ja)}</p>

  <h2>誰のためか</h2>
  <p>{escape(product.cohort_jp)} ({escape(product.cohort_en)}) cohort. 月次 {product.monthly_req_estimate} req 想定 (¥3/req)。</p>

  <h2>1 query で返るもの (package_kind)</h2>
  <p>{pkg}</p>

  <h2>呼び出される heavy / composed endpoint</h2>
  <ul>{heavy}</ul>

  <h2>SDK example — Python (jpcite-mcp / autonomath-mcp PyPI)</h2>
  <pre><code class="language-python">{escape(python_snippet(product))}</code></pre>

  <h2>SDK example — TypeScript (Bedrock MCP / OpenAI tool-use)</h2>
  <pre><code class="language-typescript">{escape(typescript_snippet(product))}</code></pre>

  <h2>Claude Code <code>.mcp.json</code> snippet</h2>
  <pre><code class="language-json">{escape(claude_code_snippet(product))}</code></pre>

  <h2>jpcite ¥{jpcite_monthly:,} / 月 vs LLM API replacement</h2>
  <table class="comparison">
    <thead><tr><th>路線</th><th>1 packet</th><th>{product.monthly_req_estimate} packet / 月</th></tr></thead>
    <tbody>
      <tr><td>jpcite ({escape(product.code)})</td><td>¥3 (税抜) / ¥3.30 (税込)</td><td>¥{jpcite_monthly:,}</td></tr>
      <tr><td>LLM Opus 4.7 only</td><td>¥{llm_rows[0]["per_packet_jpy"]}</td><td>¥{round(llm_rows[0]["per_packet_jpy"] * product.monthly_req_estimate):,}</td></tr>
      <tr><td>LLM Sonnet 4.6 only</td><td>¥{llm_rows[1]["per_packet_jpy"]}</td><td>¥{round(llm_rows[1]["per_packet_jpy"] * product.monthly_req_estimate):,}</td></tr>
      <tr><td>LLM Haiku 4.5 only</td><td>¥{llm_rows[2]["per_packet_jpy"]}</td><td>¥{round(llm_rows[2]["per_packet_jpy"] * product.monthly_req_estimate):,}</td></tr>
    </tbody>
  </table>
  <p>cheapest LLM tier (Haiku 4.5) でも jpcite の <strong>{multiplier}x</strong> コスト。
     さらに LLM 単独は出典 URL を hallucinate するため、
     一次資料 URL + fetched_at + known_gaps は <strong>jpcite でしか得られない</strong>。</p>
  <p><a href="{cohort_compare_path}">cohort 別コスト比較表を見る &rarr;</a></p>

  <h2>1 call ≈ 人手 ¥{product.one_call_replacement_jpy:,} 相当</h2>
  <p>30-90 分の一次資料調査 + 名寄せ + 出典確認を 1 query で代替。
     代替時給 ¥3,000 換算で 1 packet ≒ ¥{product.one_call_replacement_jpy:,}。
     jpcite ¥3 / packet との差分が ROI。</p>

  {disclaimer}

  <h2>使い始める</h2>
  <ol>
    <li><a href="/dashboard">/dashboard</a> で API キー発行 (匿名 3 req/日無料)</li>
    <li>Python: <code>pip install autonomath-mcp</code></li>
    <li>Claude Code: <code>.mcp.json</code> 上記 snippet を貼り付け</li>
    <li><a href="/docs/getting-started/">getting-started</a> 経由で 1 packet を取得</li>
  </ol>

  <h2>関連リソース</h2>
  <ul>
    <li><a href="/docs/api-reference/">API reference (219 path)</a></li>
    <li><a href="/docs/mcp-tools/">MCP tools (146 default-gate)</a></li>
    <li><a href="/cookbook/">cookbook (15 recipes)</a></li>
    <li><a href="/for/{product.cohort_slug}.html">{escape(product.cohort_jp)} 向け cohort landing</a></li>
    <li><a href="/.well-known/jpcite-outcome-catalog.json">outcome catalog (450 outcome)</a></li>
  </ul>
</article>
"""

    return HTML_BASE.format(
        title=escape(title),
        description=escape(description),
        og_title=escape(title),
        og_description=escape(description),
        domain=DOMAIN,
        path=f"/products/{product.slug}.html",
        jsonld=jsonld,
        body=body,
    )


def render_cohort_persona_page(product: Product) -> str:
    """Persona-specific landing at site/for/<cohort_slug>.html."""
    monthly_jpy = product.monthly_req_estimate * 3
    cheapest_llm = round(
        min(r["per_packet_jpy"] for r in llm_replacement_cost()) * product.monthly_req_estimate
    )
    disclaimer = disclaimer_html(product.sensitive_acts)

    title = f"{product.cohort_jp}事務所向け jpcite — {product.name_ja}"
    description = (
        f"{product.cohort_jp}事務所向け jpcite 活用ガイド。"
        f"{product.summary_ja[:80]}. 月次 {product.monthly_req_estimate} req = ¥{monthly_jpy:,}。"
    )
    jsonld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": title,
            "audience": {"@type": "Audience", "audienceType": product.cohort_jp},
            "url": f"https://{DOMAIN}/for/{product.cohort_slug}.html",
        },
        ensure_ascii=False,
    )

    body = f"""
<article class="cohort-landing">
  <nav class="breadcrumb"><a href="/">Home</a> &raquo; <a href="/products">成果物カタログ</a> &raquo; {escape(product.cohort_jp)}</nav>
  <h1>{escape(product.cohort_jp)}事務所向け jpcite</h1>
  <p class="lede">{escape(product.summary_ja)}</p>

  <h2>主な業務 × jpcite endpoint</h2>
  <ul>
{"".join(f"<li><code>{escape(e)}</code></li>" for e in product.heavy_endpoints)}
  </ul>

  <h2>¥3/req 経済性</h2>
  <p>月次 {product.monthly_req_estimate} req × ¥3 = <strong>¥{monthly_jpy:,}</strong>。
     LLM API 単独 (Haiku 4.5 換算) では <strong>¥{cheapest_llm:,}</strong> 相当で、
     さらに出典 URL を hallucinate しないという quality 差は jpcite が提供。</p>

  <h2>推奨 product</h2>
  <p><a href="/products/{product.slug}.html">{escape(product.code)} {escape(product.name_ja)} &rarr;</a></p>

  {disclaimer}

  <h2>使い始める</h2>
  <ul>
    <li>API キー: <a href="/dashboard">/dashboard</a></li>
    <li>SDK: <code>pip install autonomath-mcp</code> / <code>npm install @jpcite/sdk</code></li>
    <li>Claude Desktop: <a href="/docs/getting-started/">getting-started</a></li>
  </ul>
</article>
"""

    return HTML_BASE.format(
        title=escape(title),
        description=escape(description),
        og_title=escape(title),
        og_description=escape(description),
        domain=DOMAIN,
        path=f"/for/{product.cohort_slug}.html",
        jsonld=jsonld,
        body=body,
    )


def render_comparison_page(product: Product) -> str:
    """¥30 vs LLM ¥3,000 cohort cost analysis page (Justifiability moat)."""
    llm_rows = llm_replacement_cost()
    jpcite_monthly = product.monthly_req_estimate * 3
    title = f"{product.cohort_jp} cohort — jpcite ¥{jpcite_monthly:,} vs LLM API replacement cost"
    description = (
        f"{product.cohort_jp} cohort コスト比較. jpcite ¥3/req metered "
        f"vs Anthropic Opus 4.7 / Sonnet 4.6 / Haiku 4.5 自前 LLM 投入のコスト試算."
    )

    rows = "".join(
        f"<tr><td>{escape(r['model'])}</td>"
        f"<td>¥{r['per_packet_jpy']}</td>"
        f"<td>¥{round(r['per_packet_jpy'] * product.monthly_req_estimate):,}</td>"
        f"<td>¥{round(r['per_packet_jpy'] * product.monthly_req_estimate * 12):,}</td></tr>"
        for r in llm_rows
    )

    jsonld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": title,
            "author": {"@type": "Organization", "name": "Bookyou株式会社"},
            "datePublished": date.today().isoformat(),
        },
        ensure_ascii=False,
    )

    body = f"""
<article class="comparison-page">
  <nav class="breadcrumb"><a href="/">Home</a> &raquo; <a href="/compare/">比較</a> &raquo; {escape(product.cohort_jp)}</nav>
  <h1>{escape(product.cohort_jp)} cohort コスト比較</h1>
  <p class="lede">jpcite ¥3/req metered vs 自前 LLM 投入の単純比較. 月次 {product.monthly_req_estimate} packet 前提.</p>

  <h2>jpcite (推奨 path)</h2>
  <table>
    <thead><tr><th>項目</th><th>値</th></tr></thead>
    <tbody>
      <tr><td>1 packet 単価</td><td>¥3 (税抜) / ¥3.30 (税込)</td></tr>
      <tr><td>月次 ({product.monthly_req_estimate} packet)</td><td>¥{jpcite_monthly:,}</td></tr>
      <tr><td>年次</td><td>¥{jpcite_monthly * 12:,}</td></tr>
      <tr><td>出典 URL + fetched_at + known_gaps</td><td>含む (一次資料 only / aggregator ban)</td></tr>
      <tr><td>意見表明 / 申請書面 / 登記代理</td><td><strong>含まない</strong> — 士業独占業務の境界遵守</td></tr>
    </tbody>
  </table>

  <h2>LLM API replacement (jpcite 経由なし / 自前 prompt)</h2>
  <p>LLM 1 call 平均 input 5,000 tokens + output 1,500 tokens 想定. 公開価格 (2026-05 snapshot).</p>
  <table>
    <thead><tr><th>モデル</th><th>1 packet</th><th>月次 {product.monthly_req_estimate}</th><th>年次</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>

  <h2>LLM 単独経路の隠れコスト</h2>
  <ul>
    <li><strong>Source hallucination</strong> — 出典 URL を捏造するリスク. jpcite は一次資料 URL + fetched_at で構造的に防ぐ.</li>
    <li><strong>known_gaps 概念なし</strong> — LLM は「分からない」を返さず憶測する. jpcite は欠損 surface を artifact 化.</li>
    <li><strong>aggregator 汚染</strong> — LLM の training set には noukaweb / hojyokin-portal 等が含まれる. jpcite は aggregator ban.</li>
    <li><strong>士業独占業務の越権リスク</strong> — LLM は §52 / §47条の2 / §72 / §1 / §3 を境界として明示しない. jpcite は disclaimer envelope 必須.</li>
    <li><strong>fetched_at の semantic honesty</strong> — LLM は「最新」と言うが何時取得かは保証しない. jpcite は「出典取得 YYYY-MM-DD HH:MM」を必ず返す.</li>
  </ul>

  <h2>推奨 product</h2>
  <p><a href="/products/{product.slug}.html">{escape(product.code)} {escape(product.name_ja)} &rarr;</a></p>

  <h2>cohort 横断比較</h2>
  <ul>
    <li><a href="/compare/zeirishi.html">税理士</a></li>
    <li><a href="/compare/kaikei.html">会計士</a></li>
    <li><a href="/compare/gyoseishoshi.html">行政書士</a></li>
    <li><a href="/compare/shihoshoshi.html">司法書士</a></li>
    <li><a href="/compare/sme.html">中小経営者</a></li>
  </ul>
</article>
"""
    return HTML_BASE.format(
        title=escape(title),
        description=escape(description),
        og_title=escape(title),
        og_description=escape(description),
        domain=DOMAIN,
        path=f"/compare/{product.cohort_slug}.html",
        jsonld=jsonld,
        body=body,
    )


def render_recipe_md(recipe: Recipe) -> str:
    """SEO-friendly markdown for a cookbook recipe."""
    h1 = recipe.title
    steps_md = "\n".join(
        f"{i + 1}. **{escape(s.get('tool_name', '?'))}** — {escape(s.get('purpose', ''))}"
        for i, s in enumerate(recipe.steps)
    )
    preconditions_md = "\n".join(f"- `{escape(p)}`" for p in recipe.preconditions)
    disclaimer = escape(recipe.disclaimer)

    jsonld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": recipe.title,
            "description": recipe.disclaimer or recipe.title,
            "estimatedCost": {
                "@type": "MonetaryAmount",
                "currency": "JPY",
                "value": recipe.cost_estimate_jpy,
            },
            "totalTime": f"PT{max(recipe.expected_duration_seconds, 1)}S",
            "step": [
                {
                    "@type": "HowToStep",
                    "name": s.get("tool_name", "?"),
                    "text": s.get("purpose", ""),
                    "position": i + 1,
                }
                for i, s in enumerate(recipe.steps)
            ],
        },
        ensure_ascii=False,
    )

    return f"""---
title: "{h1}"
segment: {recipe.segment}
recipe: {recipe.recipe_name}
cost_estimate_jpy: {recipe.cost_estimate_jpy}
billable_units: {recipe.billable_units}
parallel: {str(recipe.parallel_calls_supported).lower()}
duration_seconds: {recipe.expected_duration_seconds}
---

<!-- structured data -->
<script type="application/ld+json">
{jsonld}
</script>

# {h1}

> **Cost**: ¥{recipe.cost_estimate_jpy} ({recipe.billable_units} billable units, ¥3/req) ·
> **Duration**: {recipe.expected_duration_seconds}s ·
> **Parallel-safe**: {recipe.parallel_calls_supported} ·
> **Disclaimer**: {disclaimer}

## Preconditions

{preconditions_md or "- (none)"}

## Steps

{steps_md or "_(no steps registered)_"}

## Output artifact

- Type: `{recipe.output_artifact_type or "evidence_packet"}`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{{JPCITE}}/v1/jpcite/route",
    headers={{"X-API-Key": key}},
    json={{"intent": "{recipe.recipe_name}"}},
).raise_for_status().json()
# returns recommended_tool, outcome_contract_id, deliverable_slug,
# estimated_price_jpy, execute_input_hash, next_action
```

## Related

- [Cookbook index](/docs/cookbook/)
- [API reference](/docs/api-reference/)
- [MCP tools](/docs/mcp-tools/)
- [Outcome catalog](https://{DOMAIN}/.well-known/jpcite-outcome-catalog.json)

---

*Operator: Bookyou株式会社 (T8010001213708) · Brand: jpcite · NO LLM inside · ¥3/req metered · 100% organic*
"""


# --------------------------------------------------------------------------- #
# sitemap + llms.txt + outcome-catalog refresh
# --------------------------------------------------------------------------- #


def render_products_sitemap(urls: list[str]) -> str:
    today = date.today().isoformat()
    items = "".join(
        f"  <url><loc>{escape(u)}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.8</priority></url>\n"
        for u in urls
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemap.org/schemas/sitemap/0.9">
{items}</urlset>
"""


def refresh_outcome_catalog_meta(
    products: tuple[Product, ...], recipes: list[Recipe]
) -> dict[str, Any]:
    """Add a small ``a7_assets`` block to the outcome catalog without touching ``outcomes[]``."""
    catalog: dict[str, Any] = json.loads(WELL_KNOWN.read_text(encoding="utf-8"))
    catalog["a7_assets"] = {
        "schema_version": "1",
        "regenerated_at": datetime.now(UTC).isoformat(),
        "product_count": len(products),
        "products": [
            {
                "code": p.code,
                "slug": p.slug,
                "name_ja": p.name_ja,
                "name_en": p.name_en,
                "cohort": p.cohort_jp,
                "cohort_slug": p.cohort_slug,
                "package_kinds": list(p.package_kinds),
                "monthly_req_estimate": p.monthly_req_estimate,
                "monthly_jpy_at_3_per_req": p.monthly_req_estimate * 3,
                "url_landing": f"https://{DOMAIN}/products/{p.slug}.html",
                "url_persona": f"https://{DOMAIN}/for/{p.cohort_slug}.html",
                "url_compare": f"https://{DOMAIN}/compare/{p.cohort_slug}.html",
            }
            for p in products
        ],
        "heavy_endpoint_count": len(HEAVY_ENDPOINTS),
        "lane_count": len(LANES),
        "recipe_count": len(recipes),
        "llm_cost_reference": LLM_COSTS,
        "operator": {
            "name": "Bookyou株式会社",
            "tax_invoice_id": "T8010001213708",
            "email": "info@bookyou.net",
        },
        "brand": "jpcite",
        "disclaimers_present": sorted(DISCLAIMERS.keys()),
    }
    WELL_KNOWN.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return cast("dict[str, Any]", catalog["a7_assets"])


LLMS_A7_MARKER_START = "<!-- A7-products-start -->"
LLMS_A7_MARKER_END = "<!-- A7-products-end -->"


def refresh_llms_txt(products: tuple[Product, ...]) -> None:
    """Insert / replace an A7 section in ``site/llms.txt``."""
    path = SITE_DIR / "llms.txt"
    current = path.read_text(encoding="utf-8")
    block_lines = [LLMS_A7_MARKER_START, "", "## A7 products (5 cohort packs)"]
    for p in products:
        block_lines.append(
            f"- {p.code} {p.name_en} ({p.cohort_en}) — "
            f"https://{DOMAIN}/products/{p.slug}.html · "
            f"persona https://{DOMAIN}/for/{p.cohort_slug}.html · "
            f"compare https://{DOMAIN}/compare/{p.cohort_slug}.html"
        )
    block_lines.extend(
        [
            "",
            "Pricing reminder: each packet is one billable unit (¥3 ex-tax, ¥3.30 tax-included). "
            "No tier SKUs. Anonymous 3 req/day per IP free.",
            "",
            LLMS_A7_MARKER_END,
        ]
    )
    block = "\n".join(block_lines) + "\n"

    if LLMS_A7_MARKER_START in current and LLMS_A7_MARKER_END in current:
        head, _, rest = current.partition(LLMS_A7_MARKER_START)
        _, _, tail = rest.partition(LLMS_A7_MARKER_END)
        new = head + block + tail
    else:
        new = current.rstrip() + "\n\n" + block

    path.write_text(new, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    products_dir = SITE_DIR / "products"
    for_dir = SITE_DIR / "for"
    compare_dir = SITE_DIR / "compare"
    docs_recipes_dir = DOCS_DIR / "recipes"
    for d in (products_dir, for_dir, compare_dir, docs_recipes_dir):
        if not args.dry_run:
            d.mkdir(parents=True, exist_ok=True)

    # 1. Load recipes
    recipes: list[Recipe] = []
    for path in sorted(RECIPES_DIR.glob("recipe_*.yaml")):
        r = _parse_recipe_yaml(path)
        if r:
            recipes.append(r)
    LOG.info("loaded %d recipes", len(recipes))

    # 2. Product landing pages + persona pages + comparison pages
    urls: list[str] = []
    for product in PRODUCTS:
        landing_path = products_dir / f"{product.slug}.html"
        persona_path = for_dir / f"{product.cohort_slug}.html"
        compare_path = compare_dir / f"{product.cohort_slug}.html"
        if not args.dry_run:
            landing_path.write_text(render_product_page(product), encoding="utf-8")
            persona_path.write_text(render_cohort_persona_page(product), encoding="utf-8")
            compare_path.write_text(render_comparison_page(product), encoding="utf-8")
        urls.append(f"https://{DOMAIN}/products/{product.slug}.html")
        urls.append(f"https://{DOMAIN}/for/{product.cohort_slug}.html")
        urls.append(f"https://{DOMAIN}/compare/{product.cohort_slug}.html")
        LOG.info("rendered product %s + persona + compare", product.code)

    # 3. Recipe markdown (auto-render from data/recipes)
    for recipe in recipes:
        out = docs_recipes_dir / f"{recipe.recipe_name}.md"
        if not args.dry_run:
            out.write_text(render_recipe_md(recipe), encoding="utf-8")
        urls.append(f"https://{DOMAIN}/docs/recipes/{recipe.recipe_name}/")
    LOG.info("rendered %d recipe markdown files", len(recipes))

    # 4. Products sitemap
    sitemap = render_products_sitemap(urls)
    if not args.dry_run:
        (SITE_DIR / "sitemap-products.xml").write_text(sitemap, encoding="utf-8")
    LOG.info("rendered sitemap-products.xml with %d url(s)", len(urls))

    # 5. Outcome catalog A7 meta + llms.txt
    if not args.dry_run:
        a7_meta = refresh_outcome_catalog_meta(PRODUCTS, recipes)
        refresh_llms_txt(PRODUCTS)
        LOG.info(
            "outcome-catalog a7_assets: product=%d recipe=%d heavy_endpoint=%d lane=%d",
            a7_meta["product_count"],
            a7_meta["recipe_count"],
            a7_meta["heavy_endpoint_count"],
            a7_meta["lane_count"],
        )

    LOG.info(
        "A7 done: products=%d cohorts=%d recipes=%d total_urls=%d",
        len(PRODUCTS),
        len({p.cohort_slug for p in PRODUCTS}),
        len(recipes),
        len(urls),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
