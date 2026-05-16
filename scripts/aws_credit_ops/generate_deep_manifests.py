#!/usr/bin/env python3
"""Generate J0X_deep_*.json manifests with expanded target URL coverage.

Each manifest descends from the smoke baseline at ``data/aws_credit_jobs/J0X_*.json``
but expands ``target_urls`` to 100-1000x scale so the AWS Batch credit run can
consume the remaining $19,500 envelope in 3-5 days.

Only official Japanese public-source URLs are emitted (NTA / e-Gov / J-Grants /
gBizINFO / 各省庁 / 47都道府県 / 主要市区町村). Aggregator sources like
noukaweb, hojyokin-portal, biz.stayway are excluded per CLAUDE.md.

Output: ``data/aws_credit_jobs/deep/J0X_deep_*.json``.

The smoke baseline (J01-J07 at the repo root of ``data/aws_credit_jobs/``) is
kept intact — these are *new* sibling manifests, not replacements.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEEP_DIR = ROOT / "data" / "aws_credit_jobs" / "deep"
DEEP_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT_PREFIX = (
    "jpcite-{role}-bot/0.1 (+info@bookyou.net; Bookyou株式会社; T8010001213708)"
)

# ---------------------------------------------------------------------------
# Static reference tables (47 都道府県, 主要市区町村, 各省庁)
# ---------------------------------------------------------------------------

PREFECTURES_47 = [
    ("hokkaido", "01"),
    ("aomori", "02"),
    ("iwate", "03"),
    ("miyagi", "04"),
    ("akita", "05"),
    ("yamagata", "06"),
    ("fukushima", "07"),
    ("ibaraki", "08"),
    ("tochigi", "09"),
    ("gunma", "10"),
    ("saitama", "11"),
    ("chiba", "12"),
    ("tokyo", "13"),
    ("kanagawa", "14"),
    ("niigata", "15"),
    ("toyama", "16"),
    ("ishikawa", "17"),
    ("fukui", "18"),
    ("yamanashi", "19"),
    ("nagano", "20"),
    ("gifu", "21"),
    ("shizuoka", "22"),
    ("aichi", "23"),
    ("mie", "24"),
    ("shiga", "25"),
    ("kyoto", "26"),
    ("osaka", "27"),
    ("hyogo", "28"),
    ("nara", "29"),
    ("wakayama", "30"),
    ("tottori", "31"),
    ("shimane", "32"),
    ("okayama", "33"),
    ("hiroshima", "34"),
    ("yamaguchi", "35"),
    ("tokushima", "36"),
    ("kagawa", "37"),
    ("ehime", "38"),
    ("kochi", "39"),
    ("fukuoka", "40"),
    ("saga", "41"),
    ("nagasaki", "42"),
    ("kumamoto", "43"),
    ("oita", "44"),
    ("miyazaki", "45"),
    ("kagoshima", "46"),
    ("okinawa", "47"),
]

# Pref-level subsidy / business support gateway path patterns.
# Each entry will be expanded against each prefecture's apex.
PREF_APEX = {
    "01": "pref.hokkaido.lg.jp",
    "02": "pref.aomori.lg.jp",
    "03": "pref.iwate.jp",
    "04": "pref.miyagi.jp",
    "05": "pref.akita.lg.jp",
    "06": "pref.yamagata.jp",
    "07": "pref.fukushima.lg.jp",
    "08": "pref.ibaraki.jp",
    "09": "pref.tochigi.lg.jp",
    "10": "pref.gunma.jp",
    "11": "pref.saitama.lg.jp",
    "12": "pref.chiba.lg.jp",
    "13": "metro.tokyo.lg.jp",
    "14": "pref.kanagawa.jp",
    "15": "pref.niigata.lg.jp",
    "16": "pref.toyama.jp",
    "17": "pref.ishikawa.lg.jp",
    "18": "pref.fukui.lg.jp",
    "19": "pref.yamanashi.jp",
    "20": "pref.nagano.lg.jp",
    "21": "pref.gifu.lg.jp",
    "22": "pref.shizuoka.jp",
    "23": "pref.aichi.jp",
    "24": "pref.mie.lg.jp",
    "25": "pref.shiga.lg.jp",
    "26": "pref.kyoto.jp",
    "27": "pref.osaka.lg.jp",
    "28": "pref.hyogo.lg.jp",
    "29": "pref.nara.jp",
    "30": "pref.wakayama.lg.jp",
    "31": "pref.tottori.lg.jp",
    "32": "pref.shimane.lg.jp",
    "33": "pref.okayama.jp",
    "34": "pref.hiroshima.lg.jp",
    "35": "pref.yamaguchi.lg.jp",
    "36": "pref.tokushima.lg.jp",
    "37": "pref.kagawa.lg.jp",
    "38": "pref.ehime.jp",
    "39": "pref.kochi.lg.jp",
    "40": "pref.fukuoka.lg.jp",
    "41": "pref.saga.lg.jp",
    "42": "pref.nagasaki.jp",
    "43": "pref.kumamoto.jp",
    "44": "pref.oita.jp",
    "45": "pref.miyazaki.lg.jp",
    "46": "pref.kagoshima.jp",
    "47": "pref.okinawa.jp",
}

# 主要 20 市区町村 (政令指定都市 + 中核市の代表).
MAJOR_CITIES = [
    ("sapporo", "city.sapporo.jp"),
    ("sendai", "city.sendai.jp"),
    ("saitama", "city.saitama.jp"),
    ("chiba", "city.chiba.jp"),
    ("yokohama", "city.yokohama.lg.jp"),
    ("kawasaki", "city.kawasaki.jp"),
    ("sagamihara", "city.sagamihara.kanagawa.jp"),
    ("niigata", "city.niigata.lg.jp"),
    ("shizuoka", "city.shizuoka.lg.jp"),
    ("hamamatsu", "city.hamamatsu.shizuoka.jp"),
    ("nagoya", "city.nagoya.jp"),
    ("kyoto", "city.kyoto.lg.jp"),
    ("osaka", "city.osaka.lg.jp"),
    ("sakai", "city.sakai.lg.jp"),
    ("kobe", "city.kobe.lg.jp"),
    ("okayama", "city.okayama.jp"),
    ("hiroshima", "city.hiroshima.lg.jp"),
    ("kitakyushu", "city.kitakyushu.lg.jp"),
    ("fukuoka", "city.fukuoka.lg.jp"),
    ("kumamoto", "city.kumamoto.jp"),
]

# 23 中央省庁 + agency apex.
MINISTRY_APEX = {
    "meti": "www.meti.go.jp",
    "chusho": "www.chusho.meti.go.jp",
    "mhlw": "www.mhlw.go.jp",
    "maff": "www.maff.go.jp",
    "mlit": "www.mlit.go.jp",
    "env": "www.env.go.jp",
    "mext": "www.mext.go.jp",
    "mof": "www.mof.go.jp",
    "moj": "www.moj.go.jp",
    "mofa": "www.mofa.go.jp",
    "mod": "www.mod.go.jp",
    "soumu": "www.soumu.go.jp",
    "cao": "www.cao.go.jp",
    "cas": "www.cas.go.jp",
    "kantei": "www.kantei.go.jp",
    "digital": "www.digital.go.jp",
    "nta": "www.nta.go.jp",
    "fsa": "www.fsa.go.jp",
    "jpo": "www.jpo.go.jp",
    "fttc": "www.jftc.go.jp",
    "pmda": "www.pmda.go.jp",
    "smrj": "www.smrj.go.jp",
    "jetro": "www.jetro.go.jp",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _base_manifest(
    *,
    job_id: str,
    job_title: str,
    plan_ref: str,
    source_family: str,
    purpose: str,
    target_urls: list[str],
    budget_usd: int,
    budget_band: str,
    user_agent_role: str,
    rate_limit_rps: float,
    max_pages: int,
    max_records: int,
    max_runtime_seconds: int,
    output_prefix: str,
    output_artifacts: list[str],
    parser: str,
    license_boundary: str,
    license_family: str,
    required_notice: str,
    known_gaps_default: list[str],
    join_keys: list[str],
    success_criteria: str,
    stop_conditions: list[str],
    no_hit_safe_copy: str,
    no_hit_forbidden_copy: list[str],
    compute: str = "AWS Batch on Fargate Spot (heavy: 16 vCPU / 32 GB)",
    compute_job_definition: str = "jpcite-crawl-heavy",
    compute_queue: str = "jpcite-credit-fargate-spot-short-queue",
    personal_data_flag: str = "none",
    redistribution_scope: str = "derived_fields",
    terms_status: str = "confirmed_or_unknown_safe",
    terms_url: str | None = None,
    parent_job_id: str | None = None,
    iteration_intent: str = "deep_target_url_expansion_for_credit_burn_2026_05",
    **extra: Any,
) -> dict[str, Any]:
    urls = _dedupe_preserve_order(target_urls)
    manifest: dict[str, Any] = {
        "job_id": job_id,
        "job_title": job_title,
        "plan_ref": plan_ref,
        "source_family": source_family,
        "purpose": purpose,
        "target_urls": urls,
        "target_url_count": len(urls),
        "rate_limit_rps": rate_limit_rps,
        "max_pages": max_pages,
        "max_records": max_records,
        "max_runtime_seconds": max_runtime_seconds,
        "output_prefix": output_prefix,
        "output_artifacts": output_artifacts,
        "parser": parser,
        "robots_respect": True,
        "user_agent": USER_AGENT_PREFIX.format(role=user_agent_role),
        "budget_usd": budget_usd,
        "budget_band": budget_band,
        "compute": compute,
        "compute_job_definition": compute_job_definition,
        "compute_queue": compute_queue,
        "storage": "S3 + Glue + Athena",
        "terms_status": terms_status,
        "license_boundary": license_boundary,
        "license_family": license_family,
        "attribution_required": True,
        "required_notice": required_notice,
        "redistribution_scope": redistribution_scope,
        "personal_data_flag": personal_data_flag,
        "known_gaps_default": known_gaps_default,
        "no_hit_policy": "no_hit_not_absence",
        "no_hit_safe_copy": no_hit_safe_copy,
        "no_hit_forbidden_copy": no_hit_forbidden_copy,
        "private_data_policy": (
            "no_private_data_no_aggregator_sources_only_official_jp_public_anchors"
        ),
        "join_keys": join_keys,
        "success_criteria": success_criteria,
        "stop_conditions": stop_conditions,
        "iteration_intent": iteration_intent,
        "iteration_budget_usd": budget_usd,
        "lane": "solo",
        "tags": {
            "Project": "jpcite",
            "CreditRun": "2026-05",
            "Workload": job_id,
            "AutoStop": "2026-05-29",
        },
    }
    if terms_url is not None:
        manifest["terms_url"] = terms_url
    if parent_job_id is not None:
        manifest["parent_job_id"] = parent_job_id
    manifest.update(extra)
    return manifest


# ---------------------------------------------------------------------------
# J01 deep — Official source profile sweep (300+ URLs)
# ---------------------------------------------------------------------------


def build_j01_deep() -> dict[str, Any]:
    base = [
        # Smoke baseline 39 URLs.
        "https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html",
        "https://www.houjin-bangou.nta.go.jp/webapi/",
        "https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html",
        "https://www.houjin-bangou.nta.go.jp/download/",
        "https://www.houjin-bangou.nta.go.jp/robots.txt",
        "https://www.invoice-kohyo.nta.go.jp/aboutweb/index.html",
        "https://www.invoice-kohyo.nta.go.jp/web-api/index.html",
        "https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html",
        "https://www.invoice-kohyo.nta.go.jp/download/index.html",
        "https://www.invoice-kohyo.nta.go.jp/robots.txt",
        "https://laws.e-gov.go.jp/",
        "https://laws.e-gov.go.jp/robots.txt",
        "https://developer.e-gov.go.jp/contents/terms",
        "https://api-catalog.e-gov.go.jp/info/terms",
        "https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44",
        "https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/33",
        "https://developers.digital.go.jp/documents/jgrants/api/",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E6%A6%82%E8%A6%81.pdf",
        "https://www.jgrants-portal.go.jp/robots.txt",
        "https://content.info.gbiz.go.jp/api/index.html",
        "https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102",
        "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406",
        "https://info.gbiz.go.jp/robots.txt",
        "https://www.e-stat.go.jp/api/api-info/api-guide",
        "https://www.e-stat.go.jp/api/terms-of-use",
        "https://www.e-stat.go.jp/robots.txt",
        "https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0030.html",
        "https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140191.pdf",
        "https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html",
        "https://www.jpo.go.jp/toppage/about/index.html",
        "https://www.jpo.go.jp/system/laws/sesaku/data/download.html",
        "https://www.inpit.go.jp/j-platpat_info/guide/j-platpat_notice.html",
        "https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html",
        "https://www.jetro.go.jp/legal.html",
        "https://www.jetro.go.jp/robots.txt",
        "https://www.courts.go.jp/hanrei/search1/index.html?lang=ja",
        "https://www.courts.go.jp/robots.txt",
        "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
    ]

    # 32 L1 source family canonical surfaces (apex + key sub-paths).
    families = [
        # Laws / regulations / amendment diff.
        "https://laws.e-gov.go.jp/api/2/law_lists/1",
        "https://laws.e-gov.go.jp/api/2/law_lists/2",
        "https://laws.e-gov.go.jp/api/2/law_lists/3",
        "https://laws.e-gov.go.jp/api/2/law_lists/4",
        "https://laws.e-gov.go.jp/api/2/law_data",
        "https://laws.e-gov.go.jp/api/2/articles",
        "https://laws.e-gov.go.jp/bulkdownload/",
        "https://laws.e-gov.go.jp/help/",
        "https://elaws.e-gov.go.jp/api/info/",
        "https://elaws.e-gov.go.jp/document",
        # NTA invoice + houjin.
        "https://www.invoice-kohyo.nta.go.jp/",
        "https://www.invoice-kohyo.nta.go.jp/download/zenken/",
        "https://web-api.invoice.nta.go.jp/",
        "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/index.html",
        "https://www.houjin-bangou.nta.go.jp/download/zenken/",
        "https://www.houjin-bangou.nta.go.jp/download/sashibun/",
        "https://www.houjin-bangou.nta.go.jp/download/csvSample/",
        "https://www.houjin-bangou.nta.go.jp/download/format.html",
        "https://www.houjin-bangou.nta.go.jp/download/iclass.html",
        "https://api.houjin-bangou.nta.go.jp/4/diff",
        "https://api.houjin-bangou.nta.go.jp/4/num",
        "https://api.houjin-bangou.nta.go.jp/4/name",
        # gBizINFO.
        "https://info.gbiz.go.jp/",
        "https://info.gbiz.go.jp/hojin/",
        "https://info.gbiz.go.jp/api/v1/hojin",
        "https://info.gbiz.go.jp/opendata/",
        "https://content.info.gbiz.go.jp/api/",
        "https://content.info.gbiz.go.jp/api/index.html",
        # J-Grants.
        "https://www.jgrants-portal.go.jp/",
        "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies",
        "https://api.jgrants-portal.go.jp/exp/v1/public/notices",
        "https://developers.digital.go.jp/documents/jgrants/",
        # EDINET / FSA.
        "https://disclosure2.edinet-fsa.go.jp/",
        "https://disclosure2dl.edinet-fsa.go.jp/",
        "https://disclosure2dl.edinet-fsa.go.jp/guide/",
        "https://disclosure2dl.edinet-fsa.go.jp/api/v2/documents.json",
        "https://www.fsa.go.jp/",
        "https://www.fsa.go.jp/policy/",
        # 法人登記 (MOJ / 商業法人登記).
        "https://www.moj.go.jp/MINJI/minji06_00075.html",
        "https://houjin.touki-kyoutaku-online.moj.go.jp/",
        "https://www1.touki.or.jp/",
        # METI subsidies.
        "https://www.meti.go.jp/main/yosan.html",
        "https://www.meti.go.jp/policy/jigyou_saikouchiku/",
        "https://www.meti.go.jp/policy/mono_info_service/mono/creative/manufacturing.html",
        "https://www.chusho.meti.go.jp/koukai/yosan/",
        "https://www.chusho.meti.go.jp/keiei/sapoin/",
        # MLIT permits.
        "https://www.mlit.go.jp/page/index_00000098.html",
        "https://www.mlit.go.jp/totikensangyo/const/totikensangyo_const_tk1_000059.html",
        "https://etsuran.mlit.go.jp/TAKKEN/",
        # MHLW labor.
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/index.html",
        "https://www.mhlw.go.jp/stf/newpage_42432.html",
        "https://www.mhlw.go.jp/general/sesaku/anteikyoku/",
        # MAFF.
        "https://www.maff.go.jp/j/supply/hozyo/",
        "https://www.maff.go.jp/j/budget/",
        # ENV.
        "https://www.env.go.jp/policy/info_index.html",
        "https://www.env.go.jp/hourei/",
        "https://www.env.go.jp/budget/",
        # SOUMU (e-Stat + local gov).
        "https://www.soumu.go.jp/menu_seisaku/",
        "https://www.e-stat.go.jp/",
        "https://www.e-stat.go.jp/api/",
        # MOF.
        "https://www.mof.go.jp/",
        "https://www.mof.go.jp/tax_policy/",
        "https://www.mof.go.jp/budget/",
        # MEXT research.
        "https://www.mext.go.jp/a_menu/yosan/",
        "https://www.jsps.go.jp/j-grantsinaid/",
        # JFC.
        "https://www.jfc.go.jp/",
        "https://www.jfc.go.jp/n/finance/",
        "https://www.jfc.go.jp/n/findings/",
        # SMRJ.
        "https://www.smrj.go.jp/",
        "https://www.smrj.go.jp/sme/",
        # PMDA medical.
        "https://www.pmda.go.jp/",
        "https://www.pmda.go.jp/regulatory-info/",
        # Courts.
        "https://www.courts.go.jp/app/hanrei_jp/search1",
        "https://www.courts.go.jp/saiban/",
        # Kanpou / 官報.
        "https://kanpou.npb.go.jp/",
        "https://kanpou.npb.go.jp/aboutHTML/",
        # JETRO.
        "https://www.jetro.go.jp/",
        "https://www.jetro.go.jp/about/policy/",
        # JISC.
        "https://www.jisc.go.jp/",
        "https://www.jisc.go.jp/eng/index.html",
        # JPO patent.
        "https://www.jpo.go.jp/",
        "https://www.jpo.go.jp/system/",
        "https://www.j-platpat.inpit.go.jp/",
        # Enforcement actions (multi-ministry sweep).
        "https://www.fsa.go.jp/news/news_menu.html",
        "https://www.meti.go.jp/press/index.html",
        "https://www.mhlw.go.jp/stf/houdou/index.html",
        "https://www.mlit.go.jp/report/press/index.html",
        "https://www.env.go.jp/press/",
        "https://www.nta.go.jp/information/release/index.htm",
        # e-Stat statistics.
        "https://www.e-stat.go.jp/api/api-info/api-data",
        "https://www.e-stat.go.jp/dbview",
        # Procurement portal.
        "https://www.p-portal.go.jp/",
        "https://www.p-portal.go.jp/pps-web-biz/",
        # Climate / GHG.
        "https://www.env.go.jp/earth/ondanka/ghg-mrv/",
    ]

    # 47 都道府県 apex (each contributes 4 URLs: top / 補助金 / 入札 / robots).
    pref_urls: list[str] = []
    for code, apex in PREF_APEX.items():
        pref_urls.extend(
            [
                f"https://www.{apex}/",
                f"https://www.{apex}/robots.txt",
                f"https://www.{apex}/site/keieishien.html",
                f"https://www.{apex}/soshiki/sangyo.html",
            ]
        )

    # 主要 20 政令指定都市 apex (top + robots).
    city_urls: list[str] = []
    for _name, apex in MAJOR_CITIES:
        city_urls.extend(
            [
                f"https://www.{apex}/",
                f"https://www.{apex}/robots.txt",
            ]
        )

    # 各省庁 apex + robots.
    ministry_urls: list[str] = []
    for _key, apex in MINISTRY_APEX.items():
        ministry_urls.extend(
            [
                f"https://{apex}/",
                f"https://{apex}/robots.txt",
            ]
        )

    target_urls = _dedupe_preserve_order(
        base + families + pref_urls + city_urls + ministry_urls
    )

    return _base_manifest(
        job_id="J01_deep_source_profile_sweep",
        job_title=(
            "J01 deep — official source profile sweep "
            "(32 L1 families + 47 prefectures + 20 cities + 23 ministries)"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J01",
        source_family="all_p0_plus_p1_plus_p2",
        purpose=(
            "L1 32 source family catalog 全域 + 47都道府県 + 主要市区町村 + 各省庁 apex に対し "
            "robots/terms/形式判定/pagination 入口を receipt 化、source_profile_delta + "
            "license_boundary_report を確定して以降の deep ジョブの起点にする"
        ),
        target_urls=target_urls,
        budget_usd=800,
        budget_band="600-1000",
        user_agent_role="source-profile",
        rate_limit_rps=0.5,
        max_pages=500,
        max_records=0,
        max_runtime_seconds=7200,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J01_deep_source_profile/"
        ),
        output_artifacts=[
            "source_profile_delta.jsonl",
            "source_review_backlog.jsonl",
            "license_boundary_report.md",
            "robots_receipts.jsonl",
            "terms_receipts.jsonl",
            "format_detection.jsonl",
            "pagination_map.jsonl",
            "run_manifest.json",
            "job_report.md",
        ],
        parser="html_meta_extract",
        license_boundary="metadata_only",
        license_family="per_source_terms",
        required_notice="出典: 各公的機関 / e-Gov / NTA / 各省庁 / 47都道府県 / 各市区町村。jpcite が profile を構造化したもの。",
        known_gaps_default=[
            "source_receipt_incomplete",
            "freshness_stale_or_unknown",
        ],
        join_keys=[
            "source_id",
            "official_owner",
            "source_url",
        ],
        success_criteria=(
            "L1 32 source family 全件 + 47 都道府県 + 23 中央省庁 apex で robots/terms receipt を取得"
            "し source_profile_delta に 100% 反映 (pagination / format / license boundary フィールド埋め)"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1000",
            "robots_disallow_detected_on_target_path",
        ],
        no_hit_safe_copy=(
            "取得時点の各 source apex / robots / terms スナップショットでは、"
            "指定 URL の応答を確認できませんでした。"
        ),
        no_hit_forbidden_copy=[
            "このサイトは存在しません",
            "アクセス禁止です",
        ],
        parent_job_id="J01_source_profile_sweep",
    )


# ---------------------------------------------------------------------------
# J02 deep — NTA houjin full bulk + diff + per-prefecture (50+ URLs)
# ---------------------------------------------------------------------------


def build_j02_deep() -> dict[str, Any]:
    base = [
        "https://www.houjin-bangou.nta.go.jp/download/",
        "https://www.houjin-bangou.nta.go.jp/download/zenken/",
        "https://www.houjin-bangou.nta.go.jp/download/zenken/00_zenkoku_all.zip",
        "https://www.houjin-bangou.nta.go.jp/download/sashibun/",
        "https://www.houjin-bangou.nta.go.jp/download/sashibun/jp/00_zenkoku_diff.zip",
        "https://www.houjin-bangou.nta.go.jp/download/csvSample/",
        "https://api.houjin-bangou.nta.go.jp/4/diff",
        "https://api.houjin-bangou.nta.go.jp/4/num",
        "https://api.houjin-bangou.nta.go.jp/4/name",
        "https://www.houjin-bangou.nta.go.jp/webapi/",
        "https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html",
        "https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html",
        "https://www.houjin-bangou.nta.go.jp/download/iclass.html",
        "https://www.houjin-bangou.nta.go.jp/download/format.html",
    ]

    # 47 都道府県 zenken ZIP + sashibun diff per prefecture.
    pref_zip: list[str] = []
    for _name, code in PREFECTURES_47:
        # NTA zenken / sashibun per-prefecture bulk download conventions.
        pref_zip.extend(
            [
                f"https://www.houjin-bangou.nta.go.jp/download/zenken/{code}_zenken.zip",
                f"https://www.houjin-bangou.nta.go.jp/download/sashibun/jp/{code}_diff.zip",
            ]
        )

    # WebAPI walk seeds (param surface; the worker hydrates token + paging).
    api_walk = [
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2025-01-01&to=2025-12-31",
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2024-01-01&to=2024-12-31",
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2023-01-01&to=2023-12-31",
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2022-01-01&to=2022-12-31",
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2021-01-01&to=2021-12-31",
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2020-01-01&to=2020-12-31",
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2019-01-01&to=2019-12-31",
        "https://api.houjin-bangou.nta.go.jp/4/diff?from=2018-01-01&to=2018-12-31",
    ]

    target_urls = _dedupe_preserve_order(base + pref_zip + api_walk)

    return _base_manifest(
        job_id="J02_deep_nta_houjin_full",
        job_title=(
            "J02 deep — NTA 法人番号 zenken bulk 700 MB + sashibun diff + "
            "47 prefecture per-pref bulk + WebAPI 全件 walk"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J02",
        source_family="corporation",
        purpose=(
            "法人番号公表 zenken 700+ MB ZIP + sashibun diff ZIP + 47 都道府県 per-prefecture bulk + "
            "WebAPI 8 年分 diff walk を heavy queue (16 vCPU / 32 GB) で完走、houjin_master 全量 5M+ "
            "rows + 8 年 change-event 履歴を receipt 化"
        ),
        target_urls=target_urls,
        budget_usd=1100,
        budget_band="900-1300",
        user_agent_role="houjin-sync",
        rate_limit_rps=1.0,
        max_pages=0,
        max_records=6500000,
        max_runtime_seconds=10800,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J02_deep_nta_houjin/"
        ),
        output_artifacts=[
            "houjin_master_full.parquet",
            "houjin_change_events_full.parquet",
            "houjin_per_prefecture.parquet",
            "houjin_zenken_zip.raw",
            "houjin_sashibun_zip.raw",
            "identity_claim_refs.jsonl",
            "source_receipts.jsonl",
            "no_hit_checks.jsonl",
            "quarantine.jsonl",
            "run_manifest.json",
            "job_report.md",
        ],
        parser="nta_houjin_bulk_csv_normalizer",
        license_boundary="attribution_open",
        license_family="PDL1.0_compatible",
        required_notice="出典: 国税庁 法人番号公表サイト。国税庁はこのサービスを保証しません。",
        known_gaps_default=[
            "identity_ambiguity_unresolved",
            "freshness_stale_or_unknown",
            "source_receipt_incomplete",
        ],
        join_keys=["houjin_bangou", "prefecture_code"],
        success_criteria=(
            "全国 zenken ZIP + 47 prefecture per-pref ZIP + sashibun diff + 8 年分 WebAPI walk が完走し "
            "houjin_master_full.parquet 5M+ rows + change_events 履歴が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1300",
            "schema_drift_on_bulk_csv",
        ],
        no_hit_safe_copy=(
            "この検索条件では、取得時点の法人番号公表サイト/APIスナップショット内に"
            "一致レコードを確認できませんでした。"
        ),
        no_hit_forbidden_copy=[
            "この法人は存在しません",
            "実在しない会社です",
            "反社・不正ではありません",
        ],
        parent_job_id="J02_nta_houjin_master_mirror",
        terms_url="https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html",
    )


# ---------------------------------------------------------------------------
# J03 deep — NTA invoice full T番号 + bulk + prefecture rollup (100+ URLs)
# ---------------------------------------------------------------------------


def build_j03_deep() -> dict[str, Any]:
    base = [
        "https://www.invoice-kohyo.nta.go.jp/download/index.html",
        "https://www.invoice-kohyo.nta.go.jp/download/zenken/",
        "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/index.html",
        "https://www.invoice-kohyo.nta.go.jp/web-api/index.html",
        "https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html",
        "https://www.invoice-kohyo.nta.go.jp/aboutweb/index.html",
        "https://www.invoice-kohyo.nta.go.jp/regulation/notes-on-using-publication-system.html",
        "https://www.invoice-kohyo.nta.go.jp/",
    ]

    # zenken bulk ZIPs per prefecture (NTA 適格事業者公表 zenken download).
    pref_zip: list[str] = []
    for _name, code in PREFECTURES_47:
        pref_zip.append(
            f"https://www.invoice-kohyo.nta.go.jp/download/zenken/{code}_zenken.zip"
        )
        pref_zip.append(
            f"https://www.invoice-kohyo.nta.go.jp/download/sashibun/{code}_diff.zip"
        )

    # WebAPI walk — T 番号 search variations + announcement walk.
    api_walk = [
        "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_history",
        "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_diff",
    ]

    # T 番号 prefix search variations (T1 .. T9 / per prefecture rollup).
    t_prefix_search: list[str] = []
    for tn in range(1, 10):
        t_prefix_search.append(
            "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/num"
            f"?id=jpcite-credit-2026-05&number=T{tn}000000000000"
        )

    # Per-prefecture rollup queries (snapshot diffs by month/year, last 24 months).
    monthly_diff = []
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            monthly_diff.append(
                "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_diff"
                f"?from={year:04d}-{month:02d}-01"
            )

    target_urls = _dedupe_preserve_order(
        base + pref_zip + api_walk + t_prefix_search + monthly_diff
    )

    return _base_manifest(
        job_id="J03_deep_nta_invoice_full",
        job_title=(
            "J03 deep — NTA invoice zenken bulk × 47 prefecture + "
            "T 番号 search variations + monthly announce_diff walk"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J03",
        source_family="invoice",
        purpose=(
            "適格請求書発行事業者公表 zenken bulk × 47 都道府県 + announce_diff 24 ヶ月分 + "
            "T 番号 prefix search を全件 receipt 化、4M+ 行 invoice_registrants を full load 化、"
            "no-hit を not-absence で記録"
        ),
        target_urls=target_urls,
        budget_usd=900,
        budget_band="700-1100",
        user_agent_role="invoice-sync",
        rate_limit_rps=0.5,
        max_pages=0,
        max_records=4500000,
        max_runtime_seconds=10800,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J03_deep_nta_invoice/"
        ),
        output_artifacts=[
            "invoice_registrants_full.parquet",
            "invoice_registrants_per_prefecture.parquet",
            "invoice_monthly_diff.parquet",
            "invoice_no_hit_checks.jsonl",
            "source_receipts.jsonl",
            "known_gaps.jsonl",
            "quarantine.jsonl",
            "privacy_gate_report.md",
            "run_manifest.json",
            "job_report.md",
        ],
        parser="nta_invoice_zenken_csv_normalizer",
        license_boundary="derived_fact",
        license_family="PDL1.0_compatible_attribution_required",
        required_notice=(
            "出典: 国税庁 適格請求書発行事業者公表サイト。国税庁は本サービスの内容を保証しません。"
        ),
        known_gaps_default=[
            "no_hit_not_absence",
            "identity_ambiguity_unresolved",
            "freshness_stale_or_unknown",
        ],
        join_keys=["t_bangou", "houjin_bangou", "prefecture_code"],
        success_criteria=(
            "47 都道府県 zenken ZIP + 24 ヶ月分 announce_diff が完走し "
            "invoice_registrants_full 4M+ 行 + monthly diff が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1100",
            "private_individual_data_leak_detected",
        ],
        no_hit_safe_copy=(
            "取得時点のインボイス公表情報/APIスナップショットでは、"
            "この登録番号または検索条件に一致する公表レコードを確認できませんでした。"
        ),
        no_hit_forbidden_copy=[
            "免税事業者です",
            "請求書を発行できません",
            "税務上問題があります",
            "取引してはいけません",
            "未登録確定",
        ],
        parent_job_id="J03_nta_invoice_registrants_mirror",
        terms_url="https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html",
        personal_data_flag="contains_public_personal_data_for_sole_proprietors",
        privacy_gate=(
            "individual_sole_proprietor_name_and_address_redacted_in_public_packet"
        ),
    )


# ---------------------------------------------------------------------------
# J04 deep — e-Gov 9,484 laws full pagination (500+ URLs)
# ---------------------------------------------------------------------------


def build_j04_deep() -> dict[str, Any]:
    base = [
        "https://laws.e-gov.go.jp/api/2/law_data",
        "https://laws.e-gov.go.jp/api/2/law_lists/1",
        "https://laws.e-gov.go.jp/api/2/law_lists/2",
        "https://laws.e-gov.go.jp/api/2/law_lists/3",
        "https://laws.e-gov.go.jp/api/2/law_lists/4",
        "https://laws.e-gov.go.jp/api/2/articles",
        "https://laws.e-gov.go.jp/bulkdownload/",
        "https://laws.e-gov.go.jp/",
        "https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44",
        "https://developer.e-gov.go.jp/contents/terms",
        "https://api-catalog.e-gov.go.jp/info/terms",
        "https://elaws.e-gov.go.jp/api/info/",
        "https://elaws.e-gov.go.jp/document",
    ]

    # 9,484 laws / 10 per page → ~949 list-page sweeps. Cap at ~480 pages
    # so the manifest stays below 500 URL ceiling per the plan.
    # law_lists category 1 (憲法・法律) — ~3,500 → 350 pages.
    # law_lists category 2 (政令・勅令) — ~3,000 → 300 pages.
    # law_lists category 3 (府省令・規則) — ~2,500 → 250 pages.
    # law_lists category 4 (その他) — ~500 → 50 pages.
    # We sweep up to 120/120/120/40 = 400 pages here; the worker can recurse
    # deeper inside the run, this seeds 400 pagination entrypoints.
    list_sweeps: list[str] = []
    sweep_plan = [
        (1, 120),
        (2, 120),
        (3, 120),
        (4, 40),
    ]
    for category, pages in sweep_plan:
        for page in range(1, pages + 1):
            list_sweeps.append(
                f"https://laws.e-gov.go.jp/api/2/law_lists/{category}?page={page}&per_page=10"
            )

    # Bulk XML download axis (legacy + v2 bulks).
    bulk_axes = [
        "https://laws.e-gov.go.jp/bulkdownload/all_law.zip",
        "https://laws.e-gov.go.jp/bulkdownload/recent.zip",
        "https://laws.e-gov.go.jp/bulkdownload/amendments_index.zip",
        "https://laws.e-gov.go.jp/bulkdownload/article_index.zip",
        "https://laws.e-gov.go.jp/bulkdownload/cabinet_order.zip",
        "https://laws.e-gov.go.jp/bulkdownload/ministerial_ordinance.zip",
    ]

    # Amendment diff API walk (last 6 years).
    amendment_walk = []
    for year in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        amendment_walk.append(
            f"https://laws.e-gov.go.jp/api/2/articles?from={year:04d}-01-01&to={year:04d}-12-31"
        )

    target_urls = _dedupe_preserve_order(base + list_sweeps + bulk_axes + amendment_walk)

    return _base_manifest(
        job_id="J04_deep_egov_law_full",
        job_title=(
            "J04 deep — e-Gov 法令 全 9,484 law 4 カテゴリ pagination 400 ページ "
            "+ bulk XML + 7 年改正 diff walk"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J04",
        source_family="law",
        purpose=(
            "e-Gov 法令 9,484 件を category × pagination 400+ ページで sweep、bulk XML 6 axis + "
            "7 年分の改正 diff を receipt 化、law_snapshot 全量 + law_amendment_diff を確定"
        ),
        target_urls=target_urls,
        budget_usd=1000,
        budget_band="800-1200",
        user_agent_role="egov-law",
        rate_limit_rps=1.0,
        max_pages=500,
        max_records=12000,
        max_runtime_seconds=14400,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J04_deep_egov_law/"
        ),
        output_artifacts=[
            "law_snapshot.parquet",
            "law_article_claim_refs.jsonl",
            "law_amendment_diff.parquet",
            "law_bulk_xml.raw",
            "source_receipts.jsonl",
            "stale_law_report.md",
            "quarantine.jsonl",
            "run_manifest.json",
            "job_report.md",
        ],
        parser="egov_law_xml_v2_to_article_normalizer",
        license_boundary="attribution_open",
        license_family="PDL1.0_or_site_terms",
        required_notice=(
            "出典: e-Gov法令検索 (デジタル庁・総務省 行政管理局)。"
            "jpciteが加工した結果であり、政府は本分析を保証しません。"
        ),
        known_gaps_default=[
            "freshness_stale_or_unknown",
            "professional_review_required",
            "source_receipt_incomplete",
        ],
        join_keys=["law_id", "law_number", "article_number"],
        success_criteria=(
            "9,484 law の 90%+ で 1 法令 1 receipt + 改正 diff history が落ち、"
            "professional_review_required gap が rules 通り付与される"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1200",
            "egov_api_v2_schema_drift",
        ],
        no_hit_safe_copy=(
            "このAPI/スナップショットでは、指定条件に一致する法令メタデータ"
            "または条文を確認できませんでした。"
        ),
        no_hit_forbidden_copy=[
            "法的義務はありません",
            "この手続きは不要です",
            "違法ではありません",
        ],
        parent_job_id="J04_egov_law_snapshot",
        terms_url="https://developer.e-gov.go.jp/contents/terms",
    )


# ---------------------------------------------------------------------------
# J05 deep — J-Grants program list + per-program + amendments (1000+ URLs)
# ---------------------------------------------------------------------------


def build_j05_deep() -> dict[str, Any]:
    base = [
        "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies",
        "https://api.jgrants-portal.go.jp/exp/v1/public/notices",
        "https://www.jgrants-portal.go.jp/",
        "https://developers.digital.go.jp/documents/jgrants/api/",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E6%A6%82%E8%A6%81.pdf",
        # Adjacency portals.
        "https://www.meti.go.jp/policy/mono_info_service/mono/creative/manufacturing.html",
        "https://www.chusho.meti.go.jp/koukai/yosan/index.html",
        "https://www.smrj.go.jp/",
    ]

    # Program list pagination — public/subsidies endpoint accepts ``page`` +
    # ``per_page`` (1-100). 30k expected total → 500 pages × 100/page.
    list_sweep: list[str] = []
    for page in range(1, 501):
        list_sweep.append(
            f"https://api.jgrants-portal.go.jp/exp/v1/public/subsidies?page={page}&per_page=100"
        )

    # Per-program detail seeds (subsidy_id placeholder; worker hydrates from list).
    detail_seed: list[str] = []
    for i in range(1, 401):
        # Synthesized seed IDs spanning expected J-Grants ID range; worker
        # replaces with real subsidy_id parsed from list_sweep responses.
        detail_seed.append(
            "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies/id/"
            f"jgrants-{i:05d}"
        )

    # Notice / 公募 sweep (announcements + amendments).
    notice_sweep: list[str] = []
    for page in range(1, 101):
        notice_sweep.append(
            f"https://api.jgrants-portal.go.jp/exp/v1/public/notices?page={page}&per_page=50"
        )

    # 47 都道府県 + METI/MAFF/MHLW 補助金 portal entrypoints.
    pref_entry: list[str] = []
    for _name, _code in PREFECTURES_47:
        apex = PREF_APEX[_code]
        pref_entry.extend(
            [
                f"https://www.{apex}/site/keieishien.html",
                f"https://www.{apex}/soshiki/sangyo.html",
            ]
        )

    target_urls = _dedupe_preserve_order(
        base + list_sweep + detail_seed + notice_sweep + pref_entry
    )

    return _base_manifest(
        job_id="J05_deep_jgrants_full",
        job_title=(
            "J05 deep — J-Grants public/subsidies × 500 pagination + 400 detail seeds + "
            "100 notice pages + 47 都道府県補助金 portal"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J05",
        source_family="program",
        purpose=(
            "J-Grants public/subsidies × 500 pages + per-program detail 400 seeds + "
            "notices 100 pages + 47 都道府県補助金 portal を sweep して "
            "30k+ 制度 + 改正履歴 + 自治体 portal の 100% で receipt + deadline_calendar を生成"
        ),
        target_urls=target_urls,
        budget_usd=2000,
        budget_band="1600-2300",
        user_agent_role="jgrants",
        rate_limit_rps=1.0,
        max_pages=2000,
        max_records=30000,
        max_runtime_seconds=18000,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J05_deep_jgrants_program/"
        ),
        output_artifacts=[
            "programs.parquet",
            "program_rounds.parquet",
            "program_requirements.parquet",
            "program_amendment_history.parquet",
            "program_source_receipts.jsonl",
            "program_known_gaps.jsonl",
            "deadline_calendar.jsonl",
            "attachment_hash_only_ledger.jsonl",
            "quarantine.jsonl",
            "run_manifest.json",
            "job_report.md",
        ],
        parser="jgrants_api_v1_json_to_program_normalizer",
        license_boundary="derived_fact",
        license_family="jgrants_api_terms",
        required_notice=(
            "出典: Jグランツ (デジタル庁)。jpciteが加工して作成。"
            "政府及び自治体は本分析を保証しません。"
        ),
        known_gaps_default=[
            "professional_review_required",
            "freshness_stale_or_unknown",
            "source_receipt_incomplete",
        ],
        join_keys=["subsidy_id", "round_id", "prefecture_code"],
        success_criteria=(
            "P0 制度候補の 80%+ で deadline/target/amount/contact/source URL が receipt 付きで取得され、"
            "改正 history と 47 都道府県 portal が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_2300",
            "jgrants_api_schema_drift",
            "attachment_pdf_redistribution_risk_detected",
        ],
        no_hit_safe_copy=(
            "取得時点のJ-Grants公開API/スナップショットでは、"
            "指定条件に一致する公募情報を確認できませんでした。"
        ),
        no_hit_forbidden_copy=[
            "使える補助金はありません",
            "不採択になります",
            "申請資格がありません",
            "利用可能な補助金はありません",
        ],
        parent_job_id="J05_jgrants_public_program_acquisition",
        terms_url=(
            "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf"
        ),
    )


# ---------------------------------------------------------------------------
# J06 deep — Ministry + 47 prefecture + 20 city PDF index sweep (200+ URLs)
# ---------------------------------------------------------------------------


def build_j06_deep() -> dict[str, Any]:
    base = [
        "https://www.meti.go.jp/policy/jigyou_saikouchiku/",
        "https://www.meti.go.jp/policy/mono_info_service/mono/creative/manufacturing.html",
        "https://www.chusho.meti.go.jp/koukai/yosan/index.html",
        "https://www.meti.go.jp/main/yosan.html",
        "https://www.meti.go.jp/policy/sme_chiiki/index.html",
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/index.html",
        "https://www.mhlw.go.jp/stf/newpage_42432.html",
        "https://www.maff.go.jp/j/supply/hozyo/",
        "https://www.mlit.go.jp/page/index_00000098.html",
        "https://www.env.go.jp/policy/info_index.html",
        "https://www.cao.go.jp/houan/index.html",
    ]

    # 23 中央省庁 — 各 2 entry (補助金 / 公募).
    ministry_sub = [
        "/policy/",
        "/budget/",
        "/news/",
        "/press/",
    ]
    ministry_entries: list[str] = []
    for _key, apex in MINISTRY_APEX.items():
        for sub in ministry_sub:
            ministry_entries.append(f"https://{apex}{sub}")

    # 47 都道府県 — 補助金 + 入札 + press 系 path 4 つずつ.
    pref_entries: list[str] = []
    pref_paths = [
        "/site/keieishien.html",
        "/soshiki/sangyo.html",
        "/keiei/hojokin/",
        "/nyusatsu/",
    ]
    for code, apex in PREF_APEX.items():
        for path in pref_paths:
            pref_entries.append(f"https://www.{apex}{path}")

    # 主要 20 市区町村 — business / 補助金 path 2 つずつ.
    city_entries: list[str] = []
    city_paths = ["/business/", "/keizai/", "/sangyo/", "/keieishien/"]
    for _name, apex in MAJOR_CITIES:
        for path in city_paths:
            city_entries.append(f"https://www.{apex}{path}")

    target_urls = _dedupe_preserve_order(
        base + ministry_entries + pref_entries + city_entries
    )

    return _base_manifest(
        job_id="J06_deep_ministry_pdf_full",
        job_title=(
            "J06 deep — 23 中央省庁 × 4 path + 47 都道府県 × 4 path + "
            "20 政令指定都市 × 4 path PDF index sweep"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J06",
        source_family="ministry_municipality_pdf",
        purpose=(
            "23 中央省庁 × policy/budget/news/press + 47 都道府県 × 補助金/産業/経営支援/入札 + "
            "20 政令指定都市 × business/keizai/sangyo/keieishien path を sweep、PDF index → "
            "PDF fetch → Textract (selective) で構造化 fact を 800+ PDF まで抽出"
        ),
        target_urls=target_urls,
        budget_usd=2600,
        budget_band="2000-3200",
        user_agent_role="pdf-extract",
        rate_limit_rps=0.3,
        max_pages=2000,
        max_records=0,
        max_runtime_seconds=21600,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J06_deep_ministry_pdf/"
        ),
        output_artifacts=[
            "pdf_extracted_facts.parquet",
            "pdf_parse_failures.jsonl",
            "source_receipts.jsonl",
            "review_backlog.jsonl",
            "object_manifest.parquet",
            "quarantine.jsonl",
            "run_manifest.json",
            "job_report.md",
        ],
        parser="textract_or_cpu_pdf_to_structured_program_fields",
        compute_queue="jpcite-credit-ec2-spot-cpu-queue",
        license_boundary="metadata_only",
        license_family="site_specific_per_domain",
        required_notice=(
            "出典: 各省庁・自治体公式ページ。jpciteは抽出結果を構造化したものであり、"
            "各機関は本分析を保証しません。原本は出典URLでご確認ください。"
        ),
        known_gaps_default=[
            "source_receipt_incomplete",
            "freshness_stale_or_unknown",
            "professional_review_required",
        ],
        join_keys=["source_url", "content_hash", "publishing_authority"],
        success_criteria=(
            "OCR/parse 対象の 70%+ で 最低 1 つ reviewable fact を抽出し、"
            "低信頼 fact は quarantine に落ちる。23 省庁 + 47 都道府県 + 20 市の coverage 100%"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_3200",
            "robots_disallow_on_target_path",
            "pdf_third_party_rights_unconfirmed",
        ],
        no_hit_safe_copy=(
            "取得対象にした自治体/省庁ページとPDFスナップショットの範囲では、"
            "指定条件に一致する制度情報を確認できませんでした。"
        ),
        no_hit_forbidden_copy=[
            "この自治体に制度はありません",
            "申請できません",
            "この条件なら必ず対象です",
        ],
        compute=(
            "AWS Batch on EC2 Spot CPU + Textract (selective)"
        ),
        personal_data_flag="possible",
        redistribution_scope="metadata_only_short_quote",
        max_pdfs=2400,
        parent_job_id="J06_ministry_municipality_pdf_extraction",
    )


# ---------------------------------------------------------------------------
# J07 deep — gBizINFO corporate detail + bulk export (100+ URLs)
# ---------------------------------------------------------------------------


def build_j07_deep() -> dict[str, Any]:
    base = [
        "https://info.gbiz.go.jp/hojin/",
        "https://info.gbiz.go.jp/api/v1/hojin",
        "https://info.gbiz.go.jp/api/v1/hojin/{corporate_number}",
        "https://info.gbiz.go.jp/api/v1/hojin/{corporate_number}/certification",
        "https://info.gbiz.go.jp/api/v1/hojin/{corporate_number}/commendation",
        "https://info.gbiz.go.jp/api/v1/hojin/{corporate_number}/subsidy",
        "https://info.gbiz.go.jp/api/v1/hojin/{corporate_number}/procurement",
        "https://info.gbiz.go.jp/api/v1/hojin/{corporate_number}/workplace",
        "https://info.gbiz.go.jp/api/v1/hojin/{corporate_number}/finance",
        "https://content.info.gbiz.go.jp/api/index.html",
        "https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102",
        "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406",
        "https://info.gbiz.go.jp/opendata/",
    ]

    # gBizINFO bulk download / opendata axis.
    bulk_axes = [
        "https://info.gbiz.go.jp/opendata/houjin_info_full.zip",
        "https://info.gbiz.go.jp/opendata/houjin_info_diff.zip",
        "https://info.gbiz.go.jp/opendata/certification_full.zip",
        "https://info.gbiz.go.jp/opendata/commendation_full.zip",
        "https://info.gbiz.go.jp/opendata/subsidy_full.zip",
        "https://info.gbiz.go.jp/opendata/procurement_full.zip",
        "https://info.gbiz.go.jp/opendata/workplace_full.zip",
        "https://info.gbiz.go.jp/opendata/finance_full.zip",
    ]

    # Search / pagination sweeps by prefecture (gBizINFO supports name + corporate
    # number + prefecture filter). 47 都道府県 × top-3 list page sweep.
    search_sweep: list[str] = []
    for _name, code in PREFECTURES_47:
        for page in range(1, 4):
            search_sweep.append(
                f"https://info.gbiz.go.jp/api/v1/hojin?prefecture={code}&page={page}&per_page=100"
            )

    target_urls = _dedupe_preserve_order(base + bulk_axes + search_sweep)

    return _base_manifest(
        job_id="J07_deep_gbizinfo_full",
        job_title=(
            "J07 deep — gBizINFO opendata bulk 8 axes + 47 prefecture × 3 page search + "
            "9 per-houjin sub-resources"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J07",
        source_family="corporate_signal",
        purpose=(
            "gBizINFO opendata bulk 8 axis (houjin/certification/commendation/subsidy/procurement/"
            "workplace/finance + diff) + 47 prefecture × 3 page search + 9 per-houjin sub-resource "
            "を receipt 化、houjin_bangou を hub にした public business signal を full join"
        ),
        target_urls=target_urls,
        budget_usd=800,
        budget_band="600-1000",
        user_agent_role="gbizinfo",
        rate_limit_rps=0.5,
        max_pages=0,
        max_records=500000,
        max_runtime_seconds=14400,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J07_deep_gbizinfo/"
        ),
        output_artifacts=[
            "business_public_signals.parquet",
            "join_candidates.parquet",
            "identity_mismatch_ledger.jsonl",
            "source_receipts.jsonl",
            "quarantine.jsonl",
            "no_hit_checks.jsonl",
            "bulk_export.raw",
            "run_manifest.json",
            "job_report.md",
        ],
        parser="gbizinfo_api_v1_json_to_signal_normalizer",
        compute="AWS Batch on EC2 Spot memory + Fargate Spot (heavy bulk)",
        license_boundary="derived_fact",
        license_family="gbizinfo_api_terms",
        required_notice=(
            "出典: gBizINFO (経済産業省)。jpciteが加工して作成。"
            "元データの提供元条件に従う。経済産業省は本分析を保証しません。"
        ),
        known_gaps_default=[
            "identity_ambiguity_unresolved",
            "source_receipt_incomplete",
            "freshness_stale_or_unknown",
        ],
        join_keys=["houjin_bangou", "corporate_number", "prefecture_code"],
        success_criteria=(
            "houjin_bangou hub に対し certification/commendation/subsidy/procurement/workplace/finance "
            "6 sub-resource の receipt が 80%+ で付き、bulk 8 axis が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1000",
            "api_token_quota_exhausted",
            "gbizinfo_api_schema_drift",
        ],
        no_hit_safe_copy=(
            "取得時点のgBizINFO API/スナップショットでは、"
            "指定法人番号または条件に一致する公開レコードを確認できませんでした。"
        ),
        no_hit_forbidden_copy=[
            "補助金・調達・認定の履歴が一切ありません",
            "信用上の問題はありません",
            "公的評価が低い",
            "公的評価が高い",
            "活動実績はありません",
        ],
        api_token_required=True,
        api_token_storage=(
            "AWS Secrets Manager, never exposed in CloudWatch Logs or artifact"
        ),
        parent_job_id="J07_gbizinfo_public_business_signals",
        terms_url=(
            "https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102"
        ),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


BUILDERS = [
    ("J01_deep_source_profile_sweep.json", build_j01_deep),
    ("J02_deep_nta_houjin_full.json", build_j02_deep),
    ("J03_deep_nta_invoice_full.json", build_j03_deep),
    ("J04_deep_egov_law_full.json", build_j04_deep),
    ("J05_deep_jgrants_full.json", build_j05_deep),
    ("J06_deep_ministry_pdf_full.json", build_j06_deep),
    ("J07_deep_gbizinfo_full.json", build_j07_deep),
]


def main() -> None:
    summary = []
    total_urls = 0
    total_budget = 0
    for name, builder in BUILDERS:
        manifest = builder()
        path = DEEP_DIR / name
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        n = manifest["target_url_count"]
        b = manifest["budget_usd"]
        total_urls += n
        total_budget += b
        summary.append((manifest["job_id"], n, b, str(path)))
    print("job_id,target_url_count,budget_usd,path")
    for row in summary:
        print(f"{row[0]},{row[1]},{row[2]},{row[3]}")
    print(f"TOTAL,{total_urls},{total_budget},-")


if __name__ == "__main__":
    main()
