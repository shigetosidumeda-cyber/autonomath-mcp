#!/usr/bin/env python3
"""Generate 30 synthesized JPCIR sample packets + render HTML + build showcase.

The samples are *synthesized* — drawn from well-known public corporate names,
canonical 補助金 names and standard cohort axes (prefecture × industry × scale).
No customer-private data ever touches this generator: every field is either
a literal public name or a deterministic synthetic placeholder.

Pipeline
--------
1. Build 30 packet envelopes covering the 14 canonical outcome contracts plus
   the 4 v1 packet families (法人 360 / 制度 lineage / 採択確率 / enforcement
   heatmap). 5 per family × 4 = 20, plus 1 sample for each of 10 remaining
   outcome contracts = 30 total.
2. Render each envelope via :mod:`render_packet_preview` into a static HTML
   page at ``site/packets/sample/<outcome_type>_<sample_id>.html``.
3. Write ``site/packets/index.html`` — a JS-free grid with outcome-type
   filter buttons (CSS ``:has`` + checkbox toggles, no JS dependency) and a
   "Try in agent" CTA pointing at the MCP setup guide.
4. Write ``site/.well-known/jpcite-packet-samples.json`` — a machine-readable
   index that AI agents can crawl to discover the sample inventory.
5. Update ``site/_data/public_counts.json`` adding ``packet_samples_total``.

Constraints
-----------
* No JS dependency in the static HTML.
* No live data sources (Athena / S3 / DB) — every value is a constant in
  this file.
* Each rendered HTML must stay under 15 KB.
* mypy strict + ruff 0.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_packet_preview import build_html  # noqa: E402

from jpintel_mcp.safety_scanners import scan_forbidden_claims  # noqa: E402

logger = logging.getLogger("generate_sample_packet_showcase")

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
SITE_DIR: Final[Path] = REPO_ROOT / "site"
SAMPLE_DIR: Final[Path] = SITE_DIR / "packets" / "sample"
INDEX_PATH: Final[Path] = SITE_DIR / "packets" / "index.html"
WELL_KNOWN_PATH: Final[Path] = SITE_DIR / ".well-known" / "jpcite-packet-samples.json"
PUBLIC_COUNTS_PATH: Final[Path] = SITE_DIR / "_data" / "public_counts.json"
PREVIEW_BASE_URL: Final[str] = "https://jpcite.com/packets/sample"

DEFAULT_DISCLAIMER: Final[str] = (
    "jpcite は情報検索・根拠確認の補助に徹し、個別具体的な税務・法律・"
    "申請・監査・登記・労務・知財・労基の判断は行いません。"
)

# Synthesized seeds — every value is a public corporate name, public 補助金
# name, or canonical cohort axis. None of these are pulled from a customer
# private corpus.
LARGE_CORPORATES: Final[tuple[tuple[str, str], ...]] = (
    ("8010401084110", "トヨタ自動車株式会社"),
    ("9010401052465", "ソフトバンクグループ株式会社"),
    ("7010001008844", "日本電信電話株式会社"),
    ("3010401088193", "三菱商事株式会社"),
    ("7010001008456", "株式会社日立製作所"),
)

WELL_KNOWN_PROGRAMS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "monodukuri_subsidy_2024",
        "ものづくり・商業・サービス生産性向上促進補助金",
        "https://www.chusho.meti.go.jp/keiei/sapoin/",
    ),
    (
        "it_introduction_2024",
        "IT導入補助金 2024",
        "https://www.it-hojo.jp/",
    ),
    (
        "business_succession_2024",
        "事業承継・引継ぎ補助金",
        "https://www.shokei-portal.go.jp/",
    ),
    (
        "small_business_2024",
        "小規模事業者持続化補助金",
        "https://r3.jizokukahojokin.info/",
    ),
    (
        "jigyou_saikouchiku_2024",
        "事業再構築補助金",
        "https://jigyou-saikouchiku.go.jp/",
    ),
)

COHORTS: Final[tuple[tuple[str, str, str, str, str], ...]] = (
    ("東京都", "E", "中小企業", "subsidy", "2023"),
    ("大阪府", "I", "中小企業", "subsidy", "2023"),
    ("愛知県", "E", "中小企業", "subsidy", "2024"),
    ("福岡県", "G", "中小企業", "subsidy", "2024"),
    ("北海道", "A", "中小企業", "subsidy", "2023"),
)

ENFORCEMENT_INDUSTRIES: Final[tuple[tuple[str, str], ...]] = (
    ("D", "建設業"),
    ("E", "製造業 (化学工業含む)"),
    ("F", "電気・ガス・熱供給・水道業"),
    ("I", "卸売業・小売業"),
    ("M", "宿泊業・飲食サービス業"),
)

REMAINING_OUTCOME_TYPES: Final[
    tuple[tuple[str, str, str, dict[str, Any]], ...]
] = (
    (
        "company_public_baseline",
        "Company public baseline",
        "公開ソースで法人プロフィールを 1 リクエストにまとめます。",
        {"subject_kind": "houjin", "subject_id": "8010401084110"},
    ),
    (
        "invoice_registrant_public_check",
        "Invoice registrant public check",
        "請求書発行事業者の公開情報を取得します。",
        {"subject_kind": "houjin", "subject_id": "T8010001213708"},
    ),
    (
        "application_strategy",
        "Subsidy and grant candidate pack",
        "事業者プロフィールから候補となる補助金を提示します。",
        {"subject_kind": "houjin", "subject_id": "7010001008456"},
    ),
    (
        "regulation_change_watch",
        "Law and regulation change watch",
        "法令改正・政令改正の差分を 24 時間以内にお知らせします。",
        {"subject_kind": "law", "subject_id": "326AC0000000027"},
    ),
    (
        "local_government_permit_obligation_map",
        "Local government permit and obligation map",
        "自治体条例・許認可・届出を地域横断で集約します。",
        {"subject_kind": "region", "subject_id": "13"},
    ),
    (
        "court_enforcement_citation_pack",
        "Court and enforcement citation pack",
        "裁判例・行政処分の引用パックを構築します。",
        {"subject_kind": "houjin", "subject_id": "3010401088193"},
    ),
    (
        "public_statistics_market_context",
        "Public statistics market context",
        "e-Stat 等の公的統計から市場文脈を抽出します。",
        {"subject_kind": "region", "subject_id": "27"},
    ),
    (
        "evidence_answer",
        "Evidence answer citation pack",
        "回答に対する一次出典の引用パックを返します。",
        {"subject_kind": "question", "subject_id": "rd_credit_smb"},
    ),
    (
        "foreign_investor_japan_public_entry_brief",
        "Foreign investor Japan public entry brief",
        "外資系投資家向けに日本進出公開情報をまとめます。",
        {"subject_kind": "houjin", "subject_id": "9010401052465"},
    ),
    (
        "healthcare_regulatory_public_check",
        "Healthcare regulatory public check",
        "医療系規制の公開情報を 1 リクエストでチェックします。",
        {"subject_kind": "houjin", "subject_id": "7010001008844"},
    ),
)


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _build_houjin_360_packet(
    houjin_bangou: str,
    houjin_name: str,
) -> dict[str, Any]:
    """Synthesize a houjin_360_full_packet sample."""

    package_id = f"sample.houjin_360.{houjin_bangou}"
    return {
        "package_id": package_id,
        "package_kind": "houjin_360_full_packet",
        "schema_version": "jpcir.p0.v1",
        "generated_at": _iso_now(),
        "subject": {
            "kind": "houjin",
            "id": houjin_bangou,
            "display_name": houjin_name,
        },
        "coverage": {
            "coverage_grade": "A",
            "coverage_score": 0.82,
        },
        "sources": [
            {
                "source_url": "https://info.gbiz.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "経済産業省 gBizINFO",
                "license": "gov_standard",
            },
            {
                "source_url": "https://www.invoice-kohyo.nta.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "国税庁 請求書発行事業者公表サイト",
                "license": "pdl_v1.0",
            },
            {
                "source_url": "https://disclosure2.edinet-fsa.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "金融庁 EDINET",
                "license": "gov_standard",
            },
        ],
        "records": [
            {
                "axis": "corporate_identity",
                "houjin_bangou": houjin_bangou,
                "display_name": houjin_name,
                "source_url": "https://info.gbiz.go.jp/",
            },
            {
                "axis": "invoice_registration",
                "houjin_bangou": houjin_bangou,
                "qualified_invoice": "registered",
                "source_url": "https://www.invoice-kohyo.nta.go.jp/",
            },
            {
                "axis": "securities_disclosure",
                "houjin_bangou": houjin_bangou,
                "edinet_status": "filer",
                "source_url": "https://disclosure2.edinet-fsa.go.jp/",
            },
        ],
        "sections": [
            {
                "section_id": "summary",
                "title": "サマリー",
                "body": (
                    f"# {houjin_name}\n\n"
                    "公開ソース 3 系統 (gBizINFO / 国税庁請求書事業者 / EDINET) を"
                    "サンプル合成しています。実データではありません。\n\n"
                    "- 法人番号で識別\n"
                    "- 請求書発行事業者として登録あり\n"
                    "- 有価証券報告書提出義務あり\n"
                ),
            },
        ],
        "known_gaps": [
            {
                "code": "freshness_stale_or_unknown",
                "description": (
                    "サンプル envelope のため source_fetched_at は固定の参考値です。"
                ),
            },
        ],
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 8000,
        "source_count": 3,
        "disclaimer": DEFAULT_DISCLAIMER,
    }


def _build_program_lineage_packet(
    program_id: str,
    program_name: str,
    program_url: str,
) -> dict[str, Any]:
    """Synthesize a program_lineage_packet sample."""

    package_id = f"sample.program_lineage.{program_id}"
    return {
        "package_id": package_id,
        "package_kind": "program_lineage_packet",
        "schema_version": "jpcir.p0.v1",
        "generated_at": _iso_now(),
        "subject": {
            "kind": "program",
            "id": program_id,
            "display_name": program_name,
        },
        "coverage": {"coverage_grade": "S", "coverage_score": 0.93},
        "sources": [
            {
                "source_url": program_url,
                "source_fetched_at": "2026-05-16",
                "publisher": "経済産業省 中小企業庁",
                "license": "gov_standard",
            },
            {
                "source_url": "https://www.jgrants-portal.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "経済産業省 jGrants",
                "license": "gov_standard",
            },
            {
                "source_url": "https://elaws.e-gov.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "e-Gov 法令検索",
                "license": "cc_by_4.0",
            },
        ],
        "records": [
            {
                "axis": "program_meta",
                "program_id": program_id,
                "display_name": program_name,
                "source_url": program_url,
            },
            {
                "axis": "application_round",
                "round": "公募期間 (サンプル)",
                "status": "open",
                "source_url": "https://www.jgrants-portal.go.jp/",
            },
            {
                "axis": "law_reference",
                "law_name": "中小企業の事業活動の促進に関する法律 (サンプル)",
                "source_url": "https://elaws.e-gov.go.jp/",
            },
        ],
        "sections": [
            {
                "section_id": "lineage",
                "title": "制度の系譜",
                "body": (
                    f"# {program_name}\n\n"
                    "本サンプル envelope は制度系譜の **3 軸** を合成しています。\n\n"
                    "- 公募ラウンド\n"
                    "- 根拠法令\n"
                    "- 関連政令・告示\n\n"
                    "実データの紐付けは MCP ツール `apply_eligibility_chain_am` 等を利用してください。"
                ),
            },
        ],
        "known_gaps": [
            {
                "code": "professional_review_required",
                "description": "申請可否判定は税理士・行政書士の確認が必須です。",
            },
        ],
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 12000,
        "source_count": 3,
        "disclaimer": DEFAULT_DISCLAIMER,
    }


def _build_acceptance_probability_packet(
    prefecture: str,
    jsic_major: str,
    scale_band: str,
    program_kind: str,
    fiscal_year: str,
) -> dict[str, Any]:
    """Synthesize an acceptance_probability_cohort_packet sample."""

    cohort_id = f"{prefecture}.{jsic_major}.{scale_band}.{program_kind}.{fiscal_year}"
    package_id = f"sample.acceptance_probability.{cohort_id}"
    return {
        "package_id": package_id,
        "package_kind": "acceptance_probability_cohort_packet",
        "schema_version": "jpcir.p0.v1",
        "generated_at": _iso_now(),
        "subject": {
            "kind": "cohort",
            "id": cohort_id,
            "display_name": (
                f"{prefecture} × JSIC {jsic_major} × {scale_band} × {program_kind} × FY{fiscal_year}"
            ),
        },
        "coverage": {"coverage_grade": "B", "coverage_score": 0.68},
        "sources": [
            {
                "source_url": "https://www.jgrants-portal.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "経済産業省 jGrants",
                "license": "gov_standard",
            },
        ],
        "records": [
            {
                "axis": "cohort_definition",
                "prefecture": prefecture,
                "jsic_major": jsic_major,
                "scale_band": scale_band,
                "program_kind": program_kind,
                "fiscal_year": fiscal_year,
            },
            {
                "axis": "probability_estimate",
                "n_sample": 20,
                "n_eligible_programs": 8,
                "probability_estimate": 0.62,
                "confidence_interval_low": 0.41,
                "confidence_interval_high": 0.83,
                "confidence_method": "wilson_score_95",
            },
        ],
        "sections": [
            {
                "section_id": "estimate",
                "title": "採択確率の推定",
                "body": (
                    "# 採択確率の統計推定\n\n"
                    "本サンプルは Wilson Score 95% CI で算出された推定値です。"
                    "個別案件の採択を保証するものではありません。\n\n"
                    "- 採択確率: **0.62 (95% CI: 0.41 - 0.83)**\n"
                    "- 標本数: 20\n"
                ),
            },
        ],
        "known_gaps": [
            {
                "code": "professional_review_required",
                "description": "採択確率は統計推定です。専門家確認が必要です。",
            },
            {
                "code": "freshness_stale_or_unknown",
                "description": "コホート最新採択告示日が 12 ヶ月以上前または不明です。",
            },
        ],
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 6500,
        "source_count": 1,
        "disclaimer": DEFAULT_DISCLAIMER,
    }


def _build_enforcement_heatmap_packet(
    jsic_major: str,
    industry_name: str,
) -> dict[str, Any]:
    """Synthesize an enforcement_industry_heatmap_packet sample."""

    package_id = f"sample.enforcement_heatmap.jsic_{jsic_major}"
    return {
        "package_id": package_id,
        "package_kind": "enforcement_industry_heatmap_packet",
        "schema_version": "jpcir.p0.v1",
        "generated_at": _iso_now(),
        "subject": {
            "kind": "industry",
            "id": f"jsic_major_{jsic_major}",
            "display_name": industry_name,
        },
        "coverage": {"coverage_grade": "A", "coverage_score": 0.79},
        "sources": [
            {
                "source_url": "https://www.meti.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "経済産業省",
                "license": "gov_standard",
            },
            {
                "source_url": "https://www.maff.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "農林水産省",
                "license": "gov_standard",
            },
        ],
        "records": [
            {
                "axis": "industry_meta",
                "jsic_major": jsic_major,
                "industry_name": industry_name,
            },
            {
                "axis": "enforcement_window",
                "window": "過去 36 ヶ月",
                "case_count": 42,
                "fine_total_yen": 12_400_000,
            },
        ],
        "sections": [
            {
                "section_id": "heatmap",
                "title": "業種別行政処分ヒートマップ",
                "body": (
                    f"# JSIC {jsic_major} — {industry_name}\n\n"
                    "過去 36 ヶ月の行政処分件数を業種軸で集約したサンプルです。\n\n"
                    "- 案件件数: 42\n"
                    "- 過料合計: ¥12,400,000\n"
                    "- 出典: 経産省 + 農水省 (各省公開告示)\n"
                ),
            },
        ],
        "known_gaps": [
            {
                "code": "no_hit_not_absence",
                "description": "件数 0 件の業種は無処分の証明ではなく公開告示の検索結果です。",
            },
        ],
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 7000,
        "source_count": 2,
        "disclaimer": DEFAULT_DISCLAIMER,
    }


def _build_generic_outcome_packet(
    outcome_contract_id: str,
    display_name: str,
    description_ja: str,
    subject_kind: str,
    subject_id: str,
) -> dict[str, Any]:
    """Build a small generic envelope for a remaining outcome contract."""

    package_id = f"sample.{outcome_contract_id}.{subject_id}"
    return {
        "package_id": package_id,
        "package_kind": outcome_contract_id,
        "schema_version": "jpcir.p0.v1",
        "generated_at": _iso_now(),
        "subject": {
            "kind": subject_kind,
            "id": subject_id,
            "display_name": f"{display_name} sample subject",
        },
        "coverage": {"coverage_grade": "B", "coverage_score": 0.71},
        "sources": [
            {
                "source_url": "https://www.e-stat.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "総務省統計局 e-Stat",
                "license": "cc_by_4.0",
            },
            {
                "source_url": "https://elaws.e-gov.go.jp/",
                "source_fetched_at": "2026-05-16",
                "publisher": "e-Gov 法令検索",
                "license": "cc_by_4.0",
            },
        ],
        "records": [
            {
                "axis": "outcome_contract",
                "outcome_contract_id": outcome_contract_id,
                "display_name": display_name,
            },
            {
                "axis": "subject",
                "kind": subject_kind,
                "id": subject_id,
            },
        ],
        "sections": [
            {
                "section_id": "what_you_get",
                "title": "このパケットで取得できる情報",
                "body": (
                    f"# {display_name}\n\n"
                    f"{description_ja}\n\n"
                    "- 公開ソース 2 系統以上\n"
                    "- 出典 URL + license 明記\n"
                    "- known_gaps で限界を明示\n"
                ),
            },
        ],
        "known_gaps": [
            {
                "code": "source_receipt_incomplete",
                "description": "サンプル envelope のため一部出典 receipt は省略しています。",
            },
        ],
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 5500,
        "source_count": 2,
        "disclaimer": DEFAULT_DISCLAIMER,
    }


def _safe_sample_id(envelope: dict[str, Any]) -> str:
    package_id = str(envelope.get("package_id") or "sample")
    return package_id.replace("/", "_").replace(":", "_")


def _build_all_packets() -> list[tuple[str, str, dict[str, Any]]]:
    """Build the 30 sample packets.

    Returns a list of (outcome_type, sample_id, envelope) triples in stable
    order so the index renders deterministically.
    """

    bundle: list[tuple[str, str, dict[str, Any]]] = []

    for houjin_bangou, houjin_name in LARGE_CORPORATES:
        envelope = _build_houjin_360_packet(houjin_bangou, houjin_name)
        bundle.append(("houjin_360_full_packet", _safe_sample_id(envelope), envelope))

    for program_id, program_name, program_url in WELL_KNOWN_PROGRAMS:
        envelope = _build_program_lineage_packet(program_id, program_name, program_url)
        bundle.append(("program_lineage_packet", _safe_sample_id(envelope), envelope))

    for prefecture, jsic_major, scale_band, program_kind, fiscal_year in COHORTS:
        envelope = _build_acceptance_probability_packet(
            prefecture, jsic_major, scale_band, program_kind, fiscal_year
        )
        bundle.append(
            ("acceptance_probability_cohort_packet", _safe_sample_id(envelope), envelope)
        )

    for jsic_major, industry_name in ENFORCEMENT_INDUSTRIES:
        envelope = _build_enforcement_heatmap_packet(jsic_major, industry_name)
        bundle.append(
            ("enforcement_industry_heatmap_packet", _safe_sample_id(envelope), envelope)
        )

    for outcome_id, display_name, description_ja, params in REMAINING_OUTCOME_TYPES:
        envelope = _build_generic_outcome_packet(
            outcome_id,
            display_name,
            description_ja,
            str(params["subject_kind"]),
            str(params["subject_id"]),
        )
        bundle.append((outcome_id, _safe_sample_id(envelope), envelope))

    return bundle


OUTCOME_LABELS_JA: Final[dict[str, str]] = {
    "houjin_360_full_packet": "法人 360 (5 件)",
    "program_lineage_packet": "制度系譜 (5 件)",
    "acceptance_probability_cohort_packet": "採択確率コホート (5 件)",
    "enforcement_industry_heatmap_packet": "業種別行政処分 (5 件)",
    "company_public_baseline": "法人 baseline",
    "invoice_registrant_public_check": "請求書事業者 check",
    "application_strategy": "補助金候補",
    "regulation_change_watch": "法令改正 watch",
    "local_government_permit_obligation_map": "自治体許認可",
    "court_enforcement_citation_pack": "判例・処分 citation",
    "public_statistics_market_context": "公的統計コンテキスト",
    "evidence_answer": "Evidence answer",
    "foreign_investor_japan_public_entry_brief": "外資進出 brief",
    "healthcare_regulatory_public_check": "医療規制 check",
}


def _render_index_html(bundle: list[tuple[str, str, dict[str, Any]]]) -> str:
    """Render the showcase grid index HTML.

    No JS. Filter buttons are <a> anchors pointing at `#filter-<type>`. CSS
    `:target` selectors implement the filter without JavaScript.
    """

    outcome_types: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for outcome_type, _sample_id, envelope in bundle:
        outcome_types.setdefault(outcome_type, []).append((_sample_id, envelope))

    # Card list, in stable order.
    cards: list[str] = []
    for outcome_type, _sample_id, envelope in bundle:
        package_id = envelope.get("package_id", "—")
        subject = envelope.get("subject") or {}
        subject_display = subject.get("display_name") or subject.get("id") or "—"
        coverage = envelope.get("coverage") or {}
        coverage_grade = coverage.get("coverage_grade") or "—"
        cost = envelope.get("jpcite_cost_jpy")
        cost_str = f"¥{int(cost)}" if isinstance(cost, (int, float)) else "—"
        href = f"sample/{outcome_type}_{_sample_id}.html"
        cards.append(
            f'<article class="card" data-outcome="{outcome_type}">'
            f'<p class="outcome-tag">{outcome_type}</p>'
            f'<h3><a href="{href}">{package_id}</a></h3>'
            f'<dl class="card-meta">'
            f"<dt>subject</dt><dd>{subject_display}</dd>"
            f"<dt>coverage</dt><dd>{coverage_grade}</dd>"
            f"<dt>cost</dt><dd>{cost_str}/req</dd>"
            f"</dl>"
            f"</article>"
        )

    # Filter rows (CSS :target driven). Each filter button is a same-page
    # anchor link; CSS hides cards whose data-outcome does not match.
    filter_buttons: list[str] = ['<a href="#all" class="filter active">すべて (30)</a>']
    for outcome_type, samples in outcome_types.items():
        label = OUTCOME_LABELS_JA.get(outcome_type, outcome_type)
        filter_buttons.append(
            f'<a href="#filter-{outcome_type}" class="filter">{label} ({len(samples)})</a>'
        )

    # Style block. Use :target to power the filter without JS.
    filter_css = "\n".join(
        (
            f'#filter-{outcome_type}:target ~ .grid .card:not([data-outcome="{outcome_type}"])'
            "{display:none}"
        )
        for outcome_type in outcome_types
    )

    style = (
        "body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;"
        "max-width:1100px;margin:2rem auto;padding:0 1rem;color:#222;"
        "line-height:1.55}"
        "header h1{margin:.25rem 0 1rem;font-size:2rem}"
        "header p.lede{color:#555;font-size:1.05rem;margin:0 0 1rem;max-width:720px}"
        ".cta{display:inline-block;background:#0061ff;color:#fff;padding:.5rem .9rem;"
        "border-radius:6px;text-decoration:none;font-weight:600;margin:.25rem 0 1rem}"
        ".filters{display:flex;flex-wrap:wrap;gap:.4rem;margin:1rem 0 1.25rem}"
        ".filter{display:inline-block;padding:.3rem .7rem;background:#eee;color:#222;"
        "border-radius:999px;font-size:.85rem;text-decoration:none}"
        ".filter:hover{background:#ddd}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));"
        "gap:.85rem}"
        ".card{border:1px solid #ddd;border-radius:8px;padding:.85rem 1rem;"
        "background:#fff;display:flex;flex-direction:column}"
        ".card h3{margin:.25rem 0 .5rem;font-size:1rem;word-break:break-all}"
        ".card h3 a{color:#0050d0;text-decoration:none}"
        ".card h3 a:hover{text-decoration:underline}"
        ".card .outcome-tag{display:inline-block;background:#f0f5ff;color:#0050d0;"
        "padding:.1rem .45rem;border-radius:4px;font-size:.72rem;font-family:monospace;"
        "margin:0 0 .35rem;align-self:flex-start}"
        ".card-meta{display:grid;grid-template-columns:max-content 1fr;column-gap:.5rem;"
        "row-gap:.15rem;font-size:.85rem;margin:.1rem 0 0}"
        ".card-meta dt{font-weight:600;color:#555}"
        ".card-meta dd{margin:0}"
        "footer{margin-top:2.5rem;padding-top:1rem;border-top:1px solid #ddd;"
        "color:#444;font-size:.9rem}"
        "footer a{color:#0050d0}"
        + filter_css
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<meta name="robots" content="index,follow">\n'
        '<meta name="description" content="jpcite サンプル packet 30 件のショーケース。'
        "公開ソースのみ・¥3/req・JPCIR エンベロープ。\">\n"
        "<title>jpcite — packet サンプル 30 件のショーケース</title>\n"
        f"<style>{style}</style>\n"
        "</head>\n"
        "<body>\n"
        "<header>\n"
        '<p class="eyebrow">jpcite packet showcase</p>\n'
        "<h1>30 サンプルパケット (全 14 outcome contracts カバー)</h1>\n"
        '<p class="lede">公開ソースのみで合成した JPCIR エンベロープのサンプルです。'
        "実データではなく、AI agent / 税理士 / 行政書士 / 監査法人が "
        "<code>¥3/req</code> で受け取れる出力形式を確認できます。</p>\n"
        '<a class="cta" href="/docs/mcp/install.html" rel="nofollow noopener">'
        "Try in agent — MCP セットアップ手順を見る</a>\n"
        "</header>\n"
        '<nav class="filters" aria-label="outcome filter">\n'
        + "\n".join(filter_buttons)
        + "\n</nav>\n"
        '<main class="grid">\n'
        + "\n".join(cards)
        + "\n</main>\n"
        "<footer>\n"
        '<p>全 30 件は <a href="/.well-known/jpcite-packet-samples.json">'
        "/.well-known/jpcite-packet-samples.json</a> で機械可読 index も提供。</p>\n"
        f'<p>サンプル合成のため <code>source_fetched_at</code> は {datetime.now(tz=UTC).date()} の固定値です。</p>\n'
        f'<p class="schema">capsule_id: rc1-p0-bootstrap-2026-05-15 / generated_at: {_iso_now()}</p>\n'
        "</footer>\n"
        "</body>\n"
        "</html>\n"
    )


def _render_well_known(
    bundle: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, Any]:
    """Build the machine-readable index for AI agent discovery."""

    entries: list[dict[str, Any]] = []
    for outcome_type, sample_id, envelope in bundle:
        href = f"{PREVIEW_BASE_URL}/{outcome_type}_{sample_id}.html"
        entries.append(
            {
                "outcome_type": outcome_type,
                "package_id": envelope.get("package_id"),
                "package_kind": envelope.get("package_kind"),
                "subject_kind": (envelope.get("subject") or {}).get("kind"),
                "subject_id": (envelope.get("subject") or {}).get("id"),
                "preview_url": href,
                "coverage_grade": (envelope.get("coverage") or {}).get("coverage_grade"),
                "cost_jpy_per_req": envelope.get("jpcite_cost_jpy"),
                "schema_version": envelope.get("schema_version"),
            }
        )
    return {
        "schema_version": "jpcite.packet_samples_index.v1",
        "generated_at": _iso_now(),
        "capsule_id": "rc1-p0-bootstrap-2026-05-15",
        "total_samples": len(entries),
        "note": (
            "Synthesized samples for AI agent discovery. No customer-private data. "
            "Live packets use the same JPCIR envelope at /v1/packets/<package_id>."
        ),
        "samples": entries,
    }


def _update_public_counts(total_samples: int) -> None:
    """Add packet_samples_total to public_counts.json idempotently."""

    data: dict[str, Any] = json.loads(PUBLIC_COUNTS_PATH.read_text(encoding="utf-8"))
    data["packet_samples_total"] = total_samples
    PUBLIC_COUNTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_sample(outcome_type: str, sample_id: str, envelope: dict[str, Any]) -> Path:
    violations = scan_forbidden_claims(envelope, source=f"sample:{outcome_type}")
    if violations:
        msg = f"forbidden-claim violation in synthesized sample {sample_id}: {violations!r}"
        raise RuntimeError(msg)
    html_text = build_html(envelope)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SAMPLE_DIR / f"{outcome_type}_{sample_id}.html"
    out_path.write_text(html_text, encoding="utf-8")
    size = len(html_text.encode("utf-8"))
    if size >= 15 * 1024:
        msg = f"sample {sample_id} exceeds 15 KB ceiling: {size} bytes"
        raise RuntimeError(msg)
    return out_path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    bundle = _build_all_packets()
    if len(bundle) != 30:
        msg = f"expected 30 samples, got {len(bundle)}"
        raise RuntimeError(msg)
    written_paths: list[Path] = []
    for outcome_type, sample_id, envelope in bundle:
        out_path = _write_sample(outcome_type, sample_id, envelope)
        written_paths.append(out_path)
        logger.info("wrote %s", out_path.relative_to(REPO_ROOT))

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(_render_index_html(bundle), encoding="utf-8")
    logger.info("wrote %s", INDEX_PATH.relative_to(REPO_ROOT))

    WELL_KNOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    WELL_KNOWN_PATH.write_text(
        json.dumps(_render_well_known(bundle), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("wrote %s", WELL_KNOWN_PATH.relative_to(REPO_ROOT))

    _update_public_counts(len(bundle))
    logger.info("updated %s (packet_samples_total=%d)", PUBLIC_COUNTS_PATH.relative_to(REPO_ROOT), len(bundle))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
