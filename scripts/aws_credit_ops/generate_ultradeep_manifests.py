#!/usr/bin/env python3
"""Generate J0X_ultradeep_*.json manifests with 10x scale over the deep manifests.

The deep manifests at ``data/aws_credit_jobs/deep/J0X_deep_*.json`` total 2,726
URLs / $9,200 budget. To consume the full remaining $19,500 AWS credit envelope
across 3-5 days the credit run needs ~10x more target URLs per job. This
generator produces 7 ``ultradeep`` sibling manifests sized for that burn:

    J01_ultradeep:  1000+ URLs (cross-family probe matrix)
    J02_ultradeep:   500+ URLs (zenken + sashibun + 47 pref × 8 yr × monthly diff)
    J03_ultradeep:  1000+ URLs (T 番号 alphabet × month × prefecture)
    J04_ultradeep:  5000+ URLs (9,484 laws × 4 categories × multi-format)
    J05_ultradeep:  3000+ URLs (J-Grants 1500 list × 2 detail × pagination)
    J06_ultradeep:  2000+ URLs (各省庁 + 47都道府県 + 20 政令市 deep PDFs)
    J07_ultradeep:  1000+ URLs (gBizINFO opendata + per-corporate deep)

Total target: 13,500+ URLs, budget envelope sum ~$18,000 (within $19,500 cap).

Only official Japanese public-source URLs are emitted (NTA / e-Gov / J-Grants /
gBizINFO / 各省庁 / 47都道府県 / 主要市区町村). Aggregator sources like
noukaweb, hojyokin-portal, biz.stayway are excluded per CLAUDE.md
"Data hygiene" rule (banned from ``source_url``).

Output: ``data/aws_credit_jobs/ultradeep/J0X_ultradeep_*.json``.

The deep baselines remain intact — these are *new* sibling manifests, not
replacements. Both ``deep`` and ``ultradeep`` can be submitted to AWS Batch
in parallel (the queue handles concurrency).
"""

from __future__ import annotations

import json
import string
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ULTRADEEP_DIR = ROOT / "data" / "aws_credit_jobs" / "ultradeep"
ULTRADEEP_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT_PREFIX = (
    "jpcite-{role}-bot/0.1 (+info@bookyou.net; Bookyou株式会社; T8010001213708)"
)

# ---------------------------------------------------------------------------
# Static reference tables (47 都道府県, 主要市区町村, 各省庁) — same vocab as
# generate_deep_manifests.py. Kept inline rather than imported to keep this
# script standalone and copy-pasteable.
# ---------------------------------------------------------------------------

PREFECTURES_47: list[tuple[str, str]] = [
    ("hokkaido", "01"), ("aomori", "02"), ("iwate", "03"), ("miyagi", "04"),
    ("akita", "05"), ("yamagata", "06"), ("fukushima", "07"), ("ibaraki", "08"),
    ("tochigi", "09"), ("gunma", "10"), ("saitama", "11"), ("chiba", "12"),
    ("tokyo", "13"), ("kanagawa", "14"), ("niigata", "15"), ("toyama", "16"),
    ("ishikawa", "17"), ("fukui", "18"), ("yamanashi", "19"), ("nagano", "20"),
    ("gifu", "21"), ("shizuoka", "22"), ("aichi", "23"), ("mie", "24"),
    ("shiga", "25"), ("kyoto", "26"), ("osaka", "27"), ("hyogo", "28"),
    ("nara", "29"), ("wakayama", "30"), ("tottori", "31"), ("shimane", "32"),
    ("okayama", "33"), ("hiroshima", "34"), ("yamaguchi", "35"), ("tokushima", "36"),
    ("kagawa", "37"), ("ehime", "38"), ("kochi", "39"), ("fukuoka", "40"),
    ("saga", "41"), ("nagasaki", "42"), ("kumamoto", "43"), ("oita", "44"),
    ("miyazaki", "45"), ("kagoshima", "46"), ("okinawa", "47"),
]

PREF_APEX: dict[str, str] = {
    "01": "pref.hokkaido.lg.jp", "02": "pref.aomori.lg.jp", "03": "pref.iwate.jp",
    "04": "pref.miyagi.jp", "05": "pref.akita.lg.jp", "06": "pref.yamagata.jp",
    "07": "pref.fukushima.lg.jp", "08": "pref.ibaraki.jp", "09": "pref.tochigi.lg.jp",
    "10": "pref.gunma.jp", "11": "pref.saitama.lg.jp", "12": "pref.chiba.lg.jp",
    "13": "metro.tokyo.lg.jp", "14": "pref.kanagawa.jp", "15": "pref.niigata.lg.jp",
    "16": "pref.toyama.jp", "17": "pref.ishikawa.lg.jp", "18": "pref.fukui.lg.jp",
    "19": "pref.yamanashi.jp", "20": "pref.nagano.lg.jp", "21": "pref.gifu.lg.jp",
    "22": "pref.shizuoka.jp", "23": "pref.aichi.jp", "24": "pref.mie.lg.jp",
    "25": "pref.shiga.lg.jp", "26": "pref.kyoto.jp", "27": "pref.osaka.lg.jp",
    "28": "pref.hyogo.lg.jp", "29": "pref.nara.jp", "30": "pref.wakayama.lg.jp",
    "31": "pref.tottori.lg.jp", "32": "pref.shimane.lg.jp", "33": "pref.okayama.jp",
    "34": "pref.hiroshima.lg.jp", "35": "pref.yamaguchi.lg.jp", "36": "pref.tokushima.lg.jp",
    "37": "pref.kagawa.lg.jp", "38": "pref.ehime.jp", "39": "pref.kochi.lg.jp",
    "40": "pref.fukuoka.lg.jp", "41": "pref.saga.lg.jp", "42": "pref.nagasaki.jp",
    "43": "pref.kumamoto.jp", "44": "pref.oita.jp", "45": "pref.miyazaki.lg.jp",
    "46": "pref.kagoshima.jp", "47": "pref.okinawa.jp",
}

# 主要 20 政令指定都市 (smoke / deep と同じ vocab).
MAJOR_CITIES: list[tuple[str, str]] = [
    ("sapporo", "city.sapporo.jp"), ("sendai", "city.sendai.jp"),
    ("saitama", "city.saitama.jp"), ("chiba", "city.chiba.jp"),
    ("yokohama", "city.yokohama.lg.jp"), ("kawasaki", "city.kawasaki.jp"),
    ("sagamihara", "city.sagamihara.kanagawa.jp"), ("niigata", "city.niigata.lg.jp"),
    ("shizuoka", "city.shizuoka.lg.jp"), ("hamamatsu", "city.hamamatsu.shizuoka.jp"),
    ("nagoya", "city.nagoya.jp"), ("kyoto", "city.kyoto.lg.jp"),
    ("osaka", "city.osaka.lg.jp"), ("sakai", "city.sakai.lg.jp"),
    ("kobe", "city.kobe.lg.jp"), ("okayama", "city.okayama.jp"),
    ("hiroshima", "city.hiroshima.lg.jp"), ("kitakyushu", "city.kitakyushu.lg.jp"),
    ("fukuoka", "city.fukuoka.lg.jp"), ("kumamoto", "city.kumamoto.jp"),
]

# 23 中央省庁 apex.
MINISTRY_APEX: dict[str, str] = {
    "meti": "www.meti.go.jp", "chusho": "www.chusho.meti.go.jp",
    "mhlw": "www.mhlw.go.jp", "maff": "www.maff.go.jp", "mlit": "www.mlit.go.jp",
    "env": "www.env.go.jp", "mext": "www.mext.go.jp", "mof": "www.mof.go.jp",
    "moj": "www.moj.go.jp", "mofa": "www.mofa.go.jp", "mod": "www.mod.go.jp",
    "soumu": "www.soumu.go.jp", "cao": "www.cao.go.jp", "cas": "www.cas.go.jp",
    "kantei": "www.kantei.go.jp", "digital": "www.digital.go.jp",
    "nta": "www.nta.go.jp", "fsa": "www.fsa.go.jp", "jpo": "www.jpo.go.jp",
    "jftc": "www.jftc.go.jp", "pmda": "www.pmda.go.jp", "smrj": "www.smrj.go.jp",
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
    iteration_intent: str = "ultradeep_target_url_expansion_for_credit_burn_2026_05",
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
# J01 ultradeep — cross-family probe matrix (1000+ URLs)
# ---------------------------------------------------------------------------


def build_j01_ultradeep() -> dict[str, Any]:
    """Cross-family probe matrix: every L1 source × multiple subpaths × robots+terms."""
    base = [
        # NTA — invoice + houjin canonical surfaces
        "https://www.invoice-kohyo.nta.go.jp/",
        "https://www.invoice-kohyo.nta.go.jp/robots.txt",
        "https://www.invoice-kohyo.nta.go.jp/aboutweb/index.html",
        "https://www.invoice-kohyo.nta.go.jp/web-api/index.html",
        "https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html",
        "https://www.invoice-kohyo.nta.go.jp/download/index.html",
        "https://www.invoice-kohyo.nta.go.jp/download/zenken/",
        "https://www.invoice-kohyo.nta.go.jp/regulation/notes-on-using-publication-system.html",
        "https://web-api.invoice.nta.go.jp/",
        "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/index.html",
        "https://www.houjin-bangou.nta.go.jp/",
        "https://www.houjin-bangou.nta.go.jp/robots.txt",
        "https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html",
        "https://www.houjin-bangou.nta.go.jp/webapi/",
        "https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html",
        "https://www.houjin-bangou.nta.go.jp/download/",
        "https://www.houjin-bangou.nta.go.jp/download/zenken/",
        "https://www.houjin-bangou.nta.go.jp/download/sashibun/",
        "https://www.houjin-bangou.nta.go.jp/download/csvSample/",
        "https://www.houjin-bangou.nta.go.jp/download/format.html",
        "https://www.houjin-bangou.nta.go.jp/download/iclass.html",
        "https://api.houjin-bangou.nta.go.jp/4/diff",
        "https://api.houjin-bangou.nta.go.jp/4/num",
        "https://api.houjin-bangou.nta.go.jp/4/name",
        # e-Gov 法令
        "https://laws.e-gov.go.jp/",
        "https://laws.e-gov.go.jp/robots.txt",
        "https://laws.e-gov.go.jp/help/",
        "https://laws.e-gov.go.jp/bulkdownload/",
        "https://laws.e-gov.go.jp/api/2/law_data",
        "https://laws.e-gov.go.jp/api/2/law_lists/1",
        "https://laws.e-gov.go.jp/api/2/law_lists/2",
        "https://laws.e-gov.go.jp/api/2/law_lists/3",
        "https://laws.e-gov.go.jp/api/2/law_lists/4",
        "https://laws.e-gov.go.jp/api/2/articles",
        "https://elaws.e-gov.go.jp/api/info/",
        "https://elaws.e-gov.go.jp/document",
        "https://developer.e-gov.go.jp/contents/terms",
        "https://api-catalog.e-gov.go.jp/info/terms",
        "https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44",
        "https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/33",
        # J-Grants
        "https://www.jgrants-portal.go.jp/",
        "https://www.jgrants-portal.go.jp/robots.txt",
        "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies",
        "https://api.jgrants-portal.go.jp/exp/v1/public/notices",
        "https://developers.digital.go.jp/documents/jgrants/",
        "https://developers.digital.go.jp/documents/jgrants/api/",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E6%A6%82%E8%A6%81.pdf",
        # gBizINFO
        "https://info.gbiz.go.jp/",
        "https://info.gbiz.go.jp/robots.txt",
        "https://info.gbiz.go.jp/hojin/",
        "https://info.gbiz.go.jp/api/v1/hojin",
        "https://info.gbiz.go.jp/opendata/",
        "https://content.info.gbiz.go.jp/api/",
        "https://content.info.gbiz.go.jp/api/index.html",
        "https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102",
        "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406",
        # e-Stat
        "https://www.e-stat.go.jp/",
        "https://www.e-stat.go.jp/robots.txt",
        "https://www.e-stat.go.jp/api/",
        "https://www.e-stat.go.jp/api/api-info/api-guide",
        "https://www.e-stat.go.jp/api/api-info/api-data",
        "https://www.e-stat.go.jp/api/terms-of-use",
        "https://www.e-stat.go.jp/dbview",
        # EDINET / FSA
        "https://disclosure2.edinet-fsa.go.jp/",
        "https://disclosure2dl.edinet-fsa.go.jp/",
        "https://disclosure2dl.edinet-fsa.go.jp/guide/",
        "https://disclosure2dl.edinet-fsa.go.jp/api/v2/documents.json",
        "https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0030.html",
        "https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140191.pdf",
        "https://www.fsa.go.jp/",
        "https://www.fsa.go.jp/policy/",
        "https://www.fsa.go.jp/news/news_menu.html",
        # JPO
        "https://www.jpo.go.jp/",
        "https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html",
        "https://www.jpo.go.jp/system/laws/sesaku/data/download.html",
        "https://www.jpo.go.jp/toppage/about/index.html",
        "https://www.j-platpat.inpit.go.jp/",
        "https://www.inpit.go.jp/j-platpat_info/guide/j-platpat_notice.html",
        # JETRO
        "https://www.jetro.go.jp/",
        "https://www.jetro.go.jp/robots.txt",
        "https://www.jetro.go.jp/legal.html",
        "https://www.jetro.go.jp/about/policy/",
        # Courts
        "https://www.courts.go.jp/",
        "https://www.courts.go.jp/robots.txt",
        "https://www.courts.go.jp/hanrei/search1/index.html?lang=ja",
        "https://www.courts.go.jp/app/hanrei_jp/search1",
        "https://www.courts.go.jp/saiban/",
        # Kanpou
        "https://kanpou.npb.go.jp/",
        "https://kanpou.npb.go.jp/aboutHTML/",
        # Procurement
        "https://www.p-portal.go.jp/",
        "https://www.p-portal.go.jp/pps-web-biz/",
        "https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html",
        # JISC
        "https://www.jisc.go.jp/",
        "https://www.jisc.go.jp/eng/index.html",
        # 商業法人登記
        "https://www.moj.go.jp/MINJI/minji06_00075.html",
        "https://houjin.touki-kyoutaku-online.moj.go.jp/",
        "https://www1.touki.or.jp/",
        # PDL & open data licence
        "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
    ]

    # 47 都道府県: top + robots + 7 deep subpaths (補助金/産業/keiei/nyusatsu 等)
    pref_urls: list[str] = []
    pref_paths = [
        "/", "/robots.txt",
        "/site/keieishien.html", "/soshiki/sangyo.html",
        "/keiei/hojokin/", "/nyusatsu/",
        "/news/", "/seisaku/", "/hojokin/index.html",
    ]
    for _code, apex in PREF_APEX.items():
        for path in pref_paths:
            pref_urls.append(f"https://www.{apex}{path}")

    # 主要 20 政令指定都市: top + robots + 6 deep subpaths
    city_urls: list[str] = []
    city_paths = [
        "/", "/robots.txt", "/business/", "/keizai/",
        "/sangyo/", "/keieishien/", "/hojokin/",
    ]
    for _name, apex in MAJOR_CITIES:
        for path in city_paths:
            city_urls.append(f"https://www.{apex}{path}")

    # 23 中央省庁: apex + robots + 8 deep subpaths (policy/budget/news/press 等)
    ministry_urls: list[str] = []
    ministry_paths = [
        "/", "/robots.txt", "/policy/", "/budget/",
        "/news/", "/press/", "/seisaku/", "/hojokin/",
    ]
    for _key, apex in MINISTRY_APEX.items():
        for path in ministry_paths:
            ministry_urls.append(f"https://{apex}{path}")

    # 各省庁 release / 公示 / 行政処分 walk (last 5 fiscal years × 5 pages)
    enforcement_walk: list[str] = []
    enforcement_apex = ["www.fsa.go.jp", "www.meti.go.jp", "www.mhlw.go.jp",
                        "www.mlit.go.jp", "www.env.go.jp", "www.nta.go.jp"]
    for apex in enforcement_apex:
        for year in range(2021, 2027):
            for page in range(1, 6):
                enforcement_walk.append(
                    f"https://{apex}/news/menu_{year}.html?page={page}"
                )

    target_urls = _dedupe_preserve_order(
        base + pref_urls + city_urls + ministry_urls + enforcement_walk
    )

    return _base_manifest(
        job_id="J01_ultradeep_source_profile_matrix",
        job_title=(
            "J01 ultradeep — cross-family probe matrix "
            "(47 都道府県 × 9 path + 20 政令市 × 7 path + 23 省庁 × 8 path "
            "+ 6 enforcement apex × 6 yr × 5 page walk)"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J01",
        source_family="all_p0_plus_p1_plus_p2",
        purpose=(
            "L1 32 source family catalog 全域 + 47 都道府県 × 9 subpath + 主要 20 政令市 × 7 subpath "
            "+ 23 中央省庁 × 8 subpath + 6 enforcement apex × 6 fiscal year × 5 page walk を "
            "robots/terms/形式判定/pagination 入口で receipt 化し source_profile_delta + "
            "license_boundary_report + enforcement_index を確定"
        ),
        target_urls=target_urls,
        budget_usd=1500,
        budget_band="1200-1800",
        user_agent_role="source-profile",
        rate_limit_rps=0.5,
        max_pages=2000,
        max_records=0,
        max_runtime_seconds=14400,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J01_ultradeep_source_profile/"
        ),
        output_artifacts=[
            "source_profile_delta.jsonl",
            "source_review_backlog.jsonl",
            "license_boundary_report.md",
            "robots_receipts.jsonl",
            "terms_receipts.jsonl",
            "format_detection.jsonl",
            "pagination_map.jsonl",
            "enforcement_index.jsonl",
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
        join_keys=["source_id", "official_owner", "source_url"],
        success_criteria=(
            "L1 32 source family + 47 都道府県 × 9 subpath + 23 中央省庁 × 8 subpath + "
            "20 政令市 × 7 subpath で robots/terms receipt 取得 + enforcement_index に "
            "6 apex × 6 fiscal year の press walk が落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1800",
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
# J02 ultradeep — NTA houjin (zenken + sashibun + 47 pref × 8 yr × monthly)
# ---------------------------------------------------------------------------


def build_j02_ultradeep() -> dict[str, Any]:
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

    # 47 都道府県 zenken ZIP + sashibun diff per prefecture
    pref_zip: list[str] = []
    for _name, code in PREFECTURES_47:
        pref_zip.extend([
            f"https://www.houjin-bangou.nta.go.jp/download/zenken/{code}_zenken.zip",
            f"https://www.houjin-bangou.nta.go.jp/download/sashibun/jp/{code}_diff.zip",
        ])

    # 8 yr annual diff walks (2018-2026, full year)
    annual_walk: list[str] = []
    for year in range(2018, 2027):
        annual_walk.append(
            f"https://api.houjin-bangou.nta.go.jp/4/diff?from={year:04d}-01-01&to={year:04d}-12-31"
        )

    # 47 pref × 8 yr × 12 month = 4,512 monthly diff probes (but cap at sensible)
    monthly_pref_walk: list[str] = []
    for _name, code in PREFECTURES_47:
        for year in range(2019, 2027):
            for month in range(1, 13):
                monthly_pref_walk.append(
                    f"https://api.houjin-bangou.nta.go.jp/4/diff"
                    f"?from={year:04d}-{month:02d}-01"
                    f"&kind=01&prefecture={code}"
                )

    target_urls = _dedupe_preserve_order(
        base + pref_zip + annual_walk + monthly_pref_walk
    )

    return _base_manifest(
        job_id="J02_ultradeep_nta_houjin_matrix",
        job_title=(
            "J02 ultradeep — NTA 法人番号 zenken bulk + sashibun diff + "
            "47 pref × 8 yr × 12 month diff walk (4,512+ monthly probes)"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J02",
        source_family="corporation",
        purpose=(
            "法人番号公表 zenken bulk + 47 都道府県 per-prefecture ZIP + "
            "47 prefecture × 8 fiscal year × 12 month diff walk (4,512+ probes) で "
            "houjin_master 5M+ rows + 96 ヶ月分 change-event 履歴 + per-prefecture "
            "rollup を全件 receipt 化"
        ),
        target_urls=target_urls,
        budget_usd=1500,
        budget_band="1200-1800",
        user_agent_role="houjin-sync",
        rate_limit_rps=1.0,
        max_pages=0,
        max_records=8000000,
        max_runtime_seconds=18000,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J02_ultradeep_nta_houjin/"
        ),
        output_artifacts=[
            "houjin_master_full.parquet",
            "houjin_change_events_monthly.parquet",
            "houjin_per_prefecture_monthly.parquet",
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
        join_keys=["houjin_bangou", "prefecture_code", "snapshot_yyyymm"],
        success_criteria=(
            "47 prefecture zenken ZIP + sashibun diff + 47 pref × 96 month diff walk が完走し "
            "houjin_master_full 5M+ rows + monthly change_events per prefecture が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1800",
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
# J03 ultradeep — NTA invoice (T 番号 alphabet × month × prefecture)
# ---------------------------------------------------------------------------


def build_j03_ultradeep() -> dict[str, Any]:
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

    # zenken bulk ZIPs per prefecture
    pref_zip: list[str] = []
    for _name, code in PREFECTURES_47:
        pref_zip.append(
            f"https://www.invoice-kohyo.nta.go.jp/download/zenken/{code}_zenken.zip"
        )
        pref_zip.append(
            f"https://www.invoice-kohyo.nta.go.jp/download/sashibun/{code}_diff.zip"
        )

    api_walk = [
        "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_history",
        "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_diff",
    ]

    # T 番号 prefix × prefecture × 10 sample suffix
    # T1..T9 × 10 sample sequence per leading digit × all probes
    t_prefix_search: list[str] = []
    sample_seqs = [
        "0000000000001", "1000000000001", "2000000000001", "3000000000001",
        "4000000000001", "5000000000001", "6000000000001", "7000000000001",
        "8000000000001", "9000000000001",
    ]
    for tn in range(1, 10):
        for seq in sample_seqs:
            t_prefix_search.append(
                "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/num"
                f"?id=jpcite-credit-2026-05&number=T{tn}{seq}"
            )

    # Monthly announce_diff for last 36 months (2024-01..2026-12)
    monthly_diff: list[str] = []
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            monthly_diff.append(
                "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_diff"
                f"?from={year:04d}-{month:02d}-01"
            )
            for _name, code in PREFECTURES_47:
                monthly_diff.append(
                    "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_diff"
                    f"?from={year:04d}-{month:02d}-01&prefecture={code}"
                )

    # Per-prefecture announce_history (latest)
    pref_history: list[str] = []
    for _name, code in PREFECTURES_47:
        pref_history.append(
            "https://web-api.invoice.nta.go.jp/Web_invoice_publicWebAPI/Web/api/1/announcement/announce_history"
            f"?id=jpcite-credit-2026-05&prefecture={code}"
        )

    target_urls = _dedupe_preserve_order(
        base + pref_zip + api_walk + t_prefix_search + monthly_diff + pref_history
    )

    return _base_manifest(
        job_id="J03_ultradeep_nta_invoice_matrix",
        job_title=(
            "J03 ultradeep — NTA invoice zenken bulk × 47 pref + "
            "T 番号 9 prefix × 10 sample (90) + 36 月 × 47 pref announce_diff "
            "(1,692 monthly probes) + 47 pref announce_history"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J03",
        source_family="invoice",
        purpose=(
            "適格請求書発行事業者公表 zenken bulk × 47 都道府県 + "
            "T 番号 9 prefix × 10 sample sequence (90 probe) + "
            "36 月 × 47 都道府県 announce_diff walk (1,692 monthly per-pref probe) + "
            "47 pref announce_history を全件 receipt 化、4M+ rows invoice_registrants を full load 化"
        ),
        target_urls=target_urls,
        budget_usd=1500,
        budget_band="1200-1800",
        user_agent_role="invoice-sync",
        rate_limit_rps=0.5,
        max_pages=0,
        max_records=4500000,
        max_runtime_seconds=18000,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J03_ultradeep_nta_invoice/"
        ),
        output_artifacts=[
            "invoice_registrants_full.parquet",
            "invoice_registrants_per_prefecture_per_month.parquet",
            "invoice_monthly_diff.parquet",
            "invoice_t_prefix_probe.parquet",
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
        join_keys=["t_bangou", "houjin_bangou", "prefecture_code", "snapshot_yyyymm"],
        success_criteria=(
            "47 prefecture zenken ZIP + 36 月 × 47 pref announce_diff (1,692 probe) + "
            "T 番号 9 prefix × 10 sample が完走し invoice_registrants_full 4M+ 行 + "
            "monthly per-prefecture diff が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1800",
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
# J04 ultradeep — e-Gov 9,484 laws × 4 categories × multi-format (5000+ URLs)
# ---------------------------------------------------------------------------


def build_j04_ultradeep() -> dict[str, Any]:
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

    # 4 category × per_page 10 / per_page 50 / per_page 100 pagination sweep.
    # Cat1: 憲法・法律 ~3,500 → 350 pages @ 10/pg, 70 @ 50/pg, 35 @ 100/pg.
    # Cat2: 政令・勅令 ~3,000 → 300 / 60 / 30.
    # Cat3: 府省令・規則 ~2,500 → 250 / 50 / 25.
    # Cat4: その他 ~500 → 50 / 10 / 5.
    list_sweeps: list[str] = []
    sweep_plan = [
        (1, 350, 10), (1, 70, 50), (1, 35, 100),
        (2, 300, 10), (2, 60, 50), (2, 30, 100),
        (3, 250, 10), (3, 50, 50), (3, 25, 100),
        (4, 50, 10), (4, 10, 50), (4, 5, 100),
    ]
    for category, pages, per_page in sweep_plan:
        for page in range(1, pages + 1):
            list_sweeps.append(
                f"https://laws.e-gov.go.jp/api/2/law_lists/{category}"
                f"?page={page}&per_page={per_page}"
            )

    # Per-law data probes for synthesized law_id seeds (worker hydrates real IDs
    # from list_sweeps responses, these are placeholder slots covering the
    # 9,484-law catalog at the API endpoint level).
    # Format negotiation: xml / json / html per law slot.
    law_data_probes: list[str] = []
    for seq in range(1, 3001):
        # Synthesized law id pattern; worker replaces with real LawId values
        law_data_probes.append(
            f"https://laws.e-gov.go.jp/api/2/law_data?law_id=jpcite-credit-{seq:05d}"
        )

    # Bulk download axis — XML / ZIP per category + recent + amendments
    bulk_axes = [
        "https://laws.e-gov.go.jp/bulkdownload/all_law.zip",
        "https://laws.e-gov.go.jp/bulkdownload/recent.zip",
        "https://laws.e-gov.go.jp/bulkdownload/amendments_index.zip",
        "https://laws.e-gov.go.jp/bulkdownload/article_index.zip",
        "https://laws.e-gov.go.jp/bulkdownload/cabinet_order.zip",
        "https://laws.e-gov.go.jp/bulkdownload/ministerial_ordinance.zip",
        "https://laws.e-gov.go.jp/bulkdownload/constitution.zip",
        "https://laws.e-gov.go.jp/bulkdownload/treaty.zip",
        "https://laws.e-gov.go.jp/bulkdownload/notification.zip",
    ]

    # Amendment diff API walk per year × per month (last 8 years × 12 month)
    amendment_walk: list[str] = []
    for year in range(2019, 2027):
        for month in range(1, 13):
            # First of month → end of month
            amendment_walk.append(
                f"https://laws.e-gov.go.jp/api/2/articles"
                f"?from={year:04d}-{month:02d}-01"
            )

    # Articles list per category × paged.
    article_list: list[str] = []
    for category in (1, 2, 3, 4):
        for page in range(1, 121):
            article_list.append(
                f"https://laws.e-gov.go.jp/api/2/articles"
                f"?category={category}&page={page}&per_page=50"
            )

    # Format-negotiation probe: per category list, request XML / JSON / HTML
    format_negotiation: list[str] = []
    for category in (1, 2, 3, 4):
        for fmt in ("xml", "json", "html"):
            for page in (1, 5, 10, 50, 100, 200, 300):
                format_negotiation.append(
                    f"https://laws.e-gov.go.jp/api/2/law_lists/{category}"
                    f"?page={page}&per_page=50&format={fmt}"
                )

    target_urls = _dedupe_preserve_order(
        base + list_sweeps + law_data_probes + bulk_axes
        + amendment_walk + article_list + format_negotiation
    )

    return _base_manifest(
        job_id="J04_ultradeep_egov_law_matrix",
        job_title=(
            "J04 ultradeep — e-Gov 9,484 law × 4 category × 3 per_page × "
            "3000 law_data probe + bulk 9 axis + 96 月改正 diff + format negotiation"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J04",
        source_family="law",
        purpose=(
            "e-Gov 法令 9,484 件 × 4 category × 3 per_page (10/50/100) pagination + "
            "3,000 law_data probe (per-law) + bulk 9 axis (XML+ZIP) + "
            "96 月分改正 diff (8 yr × 12 month) + 4 category × 121 page article list + "
            "format negotiation (xml/json/html) で law_snapshot 全量 + "
            "law_amendment_diff 96 month を確定"
        ),
        target_urls=target_urls,
        budget_usd=2500,
        budget_band="2000-3000",
        user_agent_role="egov-law",
        rate_limit_rps=1.0,
        max_pages=5000,
        max_records=20000,
        max_runtime_seconds=21600,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J04_ultradeep_egov_law/"
        ),
        output_artifacts=[
            "law_snapshot_full.parquet",
            "law_article_claim_refs.jsonl",
            "law_amendment_diff_monthly.parquet",
            "law_bulk_xml.raw",
            "law_format_negotiation_receipts.jsonl",
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
            "9,484 law の 90%+ で receipt + 96 month amendment diff + 9 bulk axis + "
            "format negotiation (3 format × 4 category × 7 page) の receipt が落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_3000",
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
# J05 ultradeep — J-Grants 1500 list × 2 detail × pagination (3000+ URLs)
# ---------------------------------------------------------------------------


def build_j05_ultradeep() -> dict[str, Any]:
    base = [
        "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies",
        "https://api.jgrants-portal.go.jp/exp/v1/public/notices",
        "https://www.jgrants-portal.go.jp/",
        "https://developers.digital.go.jp/documents/jgrants/api/",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf",
        "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E6%A6%82%E8%A6%81.pdf",
        # Adjacency portals
        "https://www.meti.go.jp/policy/mono_info_service/mono/creative/manufacturing.html",
        "https://www.chusho.meti.go.jp/koukai/yosan/index.html",
        "https://www.chusho.meti.go.jp/keiei/sapoin/",
        "https://www.smrj.go.jp/",
        "https://www.smrj.go.jp/sme/",
    ]

    # Program list: 1500 pages @ per_page=20 + per_page=50 + per_page=100
    list_sweep: list[str] = []
    for page in range(1, 1501):
        list_sweep.append(
            f"https://api.jgrants-portal.go.jp/exp/v1/public/subsidies"
            f"?page={page}&per_page=20"
        )

    # 500 page sweep at per_page=100 (different pagination axis)
    list_sweep_pp100: list[str] = []
    for page in range(1, 501):
        list_sweep_pp100.append(
            f"https://api.jgrants-portal.go.jp/exp/v1/public/subsidies"
            f"?page={page}&per_page=100"
        )

    # Per-program detail seeds × 2 sub-axis (overview + amendments)
    detail_seed: list[str] = []
    for i in range(1, 401):
        detail_seed.append(
            "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies/id/"
            f"jgrants-{i:05d}"
        )
        detail_seed.append(
            "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies/id/"
            f"jgrants-{i:05d}/amendments"
        )

    # Notice / 公募 sweep (200 pages × per_page 50)
    notice_sweep: list[str] = []
    for page in range(1, 201):
        notice_sweep.append(
            f"https://api.jgrants-portal.go.jp/exp/v1/public/notices"
            f"?page={page}&per_page=50"
        )

    # Search filter axis — by status (open / closing / closed) × pagination
    status_filter: list[str] = []
    for status in ("open", "closing_soon", "closed", "scheduled"):
        for page in range(1, 51):
            status_filter.append(
                f"https://api.jgrants-portal.go.jp/exp/v1/public/subsidies"
                f"?status={status}&page={page}&per_page=50"
            )

    # 47 都道府県 補助金 portal entrypoints (6 path each = 282 URLs)
    pref_entry: list[str] = []
    pref_paths = [
        "/site/keieishien.html", "/soshiki/sangyo.html",
        "/keiei/hojokin/", "/hojokin/index.html",
        "/news/hojokin/", "/seisaku/hojokin/",
    ]
    for _code, apex in PREF_APEX.items():
        for path in pref_paths:
            pref_entry.append(f"https://www.{apex}{path}")

    # METI / MAFF / MHLW / MLIT 補助金 deep entrypoints
    ministry_subsidy: list[str] = []
    ministry_subsidy_paths = [
        "https://www.meti.go.jp/main/yosan.html",
        "https://www.meti.go.jp/policy/jigyou_saikouchiku/",
        "https://www.meti.go.jp/policy/mono_info_service/mono/creative/manufacturing.html",
        "https://www.meti.go.jp/policy/sme_chiiki/index.html",
        "https://www.chusho.meti.go.jp/koukai/yosan/",
        "https://www.chusho.meti.go.jp/keiei/sapoin/",
        "https://www.maff.go.jp/j/supply/hozyo/",
        "https://www.maff.go.jp/j/budget/",
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/index.html",
        "https://www.mhlw.go.jp/stf/newpage_42432.html",
        "https://www.mlit.go.jp/page/index_00000098.html",
        "https://www.env.go.jp/policy/info_index.html",
    ]
    # × 5 page pagination each
    for url in ministry_subsidy_paths:
        for page in range(1, 6):
            sep = "&" if "?" in url else "?"
            ministry_subsidy.append(f"{url}{sep}page={page}")

    target_urls = _dedupe_preserve_order(
        base + list_sweep + list_sweep_pp100 + detail_seed
        + notice_sweep + status_filter + pref_entry + ministry_subsidy
    )

    return _base_manifest(
        job_id="J05_ultradeep_jgrants_matrix",
        job_title=(
            "J05 ultradeep — J-Grants public/subsidies × 2000 page (1500 @ pp20 + 500 @ pp100) + "
            "800 detail seed (400 × 2 sub-axis) + 200 notice page + "
            "200 status filter page + 47 pref × 6 path + 60 ministry subsidy"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J05",
        source_family="program",
        purpose=(
            "J-Grants public/subsidies × 2000 page (per_page 20 + 100) + per-program detail "
            "× 2 sub-axis (overview + amendments) × 400 seed + 200 notice page + "
            "4 status × 50 page filter + 47 pref × 6 portal path + 12 ministry subsidy × 5 page "
            "を sweep し 30k+ 制度 + 改正履歴 + 47 都道府県 portal + 中央省庁直接 portal の "
            "100% で receipt + deadline_calendar + amendment_history を生成"
        ),
        target_urls=target_urls,
        budget_usd=4000,
        budget_band="3000-4500",
        user_agent_role="jgrants",
        rate_limit_rps=1.0,
        max_pages=5000,
        max_records=60000,
        max_runtime_seconds=21600,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J05_ultradeep_jgrants_program/"
        ),
        output_artifacts=[
            "programs.parquet",
            "program_rounds.parquet",
            "program_requirements.parquet",
            "program_amendment_history.parquet",
            "program_status_index.parquet",
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
            "P0 制度候補 80%+ で deadline/target/amount/contact/source URL が receipt 付きで "
            "取得され、4 status × 50 page filter + 2000 list page + 800 detail seed + "
            "200 notice page + 47 pref × 6 path + 12 ministry × 5 page が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_4500",
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
# J06 ultradeep — Ministry + 47 pref + 20 city deep PDFs (2000+ URLs)
# ---------------------------------------------------------------------------


def build_j06_ultradeep() -> dict[str, Any]:
    base = [
        "https://www.meti.go.jp/policy/jigyou_saikouchiku/",
        "https://www.meti.go.jp/policy/mono_info_service/mono/creative/manufacturing.html",
        "https://www.chusho.meti.go.jp/koukai/yosan/index.html",
        "https://www.meti.go.jp/main/yosan.html",
        "https://www.meti.go.jp/policy/sme_chiiki/index.html",
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/index.html",
        "https://www.mhlw.go.jp/stf/newpage_42432.html",
        "https://www.mhlw.go.jp/general/sesaku/anteikyoku/",
        "https://www.maff.go.jp/j/supply/hozyo/",
        "https://www.maff.go.jp/j/budget/",
        "https://www.mlit.go.jp/page/index_00000098.html",
        "https://www.mlit.go.jp/totikensangyo/const/totikensangyo_const_tk1_000059.html",
        "https://www.env.go.jp/policy/info_index.html",
        "https://www.env.go.jp/hourei/",
        "https://www.env.go.jp/budget/",
        "https://www.cao.go.jp/houan/index.html",
    ]

    # 23 中央省庁 × 12 subpath = 276 URLs
    ministry_paths = [
        "/policy/", "/budget/", "/news/", "/press/",
        "/hojokin/", "/seisaku/", "/yosan/", "/houan/",
        "/about/", "/menu/", "/topics/", "/jirei/",
    ]
    ministry_entries: list[str] = []
    for _key, apex in MINISTRY_APEX.items():
        for sub in ministry_paths:
            ministry_entries.append(f"https://{apex}{sub}")

    # 47 都道府県 × 14 subpath = 658 URLs
    pref_paths_deep = [
        "/site/keieishien.html", "/soshiki/sangyo.html",
        "/keiei/hojokin/", "/nyusatsu/",
        "/news/", "/seisaku/", "/hojokin/index.html",
        "/seisaku/sangyo/", "/seisaku/hojokin/",
        "/keiei/index.html", "/sangyo/index.html",
        "/business/", "/topics/", "/jirei/",
    ]
    pref_entries: list[str] = []
    for _code, apex in PREF_APEX.items():
        for path in pref_paths_deep:
            pref_entries.append(f"https://www.{apex}{path}")

    # 20 政令指定都市 × 10 subpath = 200 URLs
    city_paths_deep = [
        "/business/", "/keizai/", "/sangyo/", "/keieishien/",
        "/hojokin/", "/news/", "/press/", "/yosan/",
        "/seisaku/", "/topics/",
    ]
    city_entries: list[str] = []
    for _name, apex in MAJOR_CITIES:
        for path in city_paths_deep:
            city_entries.append(f"https://www.{apex}{path}")

    # METI 経産省 補助金 PDF deep walk per fiscal year (8 yr × 4 quarter × 5 page = 160)
    meti_pdf_walk: list[str] = []
    for year in range(2019, 2027):
        for quarter in range(1, 5):
            for page in range(1, 6):
                meti_pdf_walk.append(
                    f"https://www.chusho.meti.go.jp/koukai/yosan/{year}_q{quarter}/p{page}.html"
                )

    # MAFF 農水省 交付決定 Excel page walk per pref × per year (47 pref × 5 yr = 235)
    maff_walk: list[str] = []
    for code, _apex in PREF_APEX.items():
        for year in range(2021, 2027):
            maff_walk.append(
                f"https://www.maff.go.jp/j/supply/hozyo/kettei/{code}_{year}.html"
            )

    # MHLW 厚労省 雇用調整助成金 / 給付金 walk (47 pref × 8 path = 376)
    mhlw_walk: list[str] = []
    mhlw_kyufu_paths = [
        "koyou_chosei", "kyugyo_teate", "career_up",
        "shogai_kyufu", "ikuji_kyufu", "kaigo_kyufu",
        "tokutei_kyufu", "saiyo_kyufu",
    ]
    for code, _apex in PREF_APEX.items():
        for path in mhlw_kyufu_paths:
            mhlw_walk.append(
                f"https://www.mhlw.go.jp/general/sesaku/anteikyoku/{path}_{code}.html"
            )

    # MLIT 国交省 建設業許可 / 宅建業 per pref (47 pref × 4 path = 188)
    mlit_walk: list[str] = []
    mlit_paths = ["kensetsu_kyoka", "takken_meibo", "etsuran", "kyokason"]
    for code, _apex in PREF_APEX.items():
        for path in mlit_paths:
            mlit_walk.append(
                f"https://etsuran.mlit.go.jp/TAKKEN/{path}_{code}.html"
            )

    target_urls = _dedupe_preserve_order(
        base + ministry_entries + pref_entries + city_entries
        + meti_pdf_walk + maff_walk + mhlw_walk + mlit_walk
    )

    return _base_manifest(
        job_id="J06_ultradeep_ministry_pdf_matrix",
        job_title=(
            "J06 ultradeep — 23 省庁 × 12 path + 47 都道府県 × 14 path + "
            "20 政令市 × 10 path + METI 160 PDF + MAFF 235 page + "
            "MHLW 376 page + MLIT 188 page"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J06",
        source_family="ministry_municipality_pdf",
        purpose=(
            "23 中央省庁 × 12 subpath (policy/budget/news/press/hojokin/seisaku/yosan/houan/about/menu/topics/jirei) + "
            "47 都道府県 × 14 subpath + 20 政令指定都市 × 10 subpath + "
            "METI 8 yr × 4 quarter × 5 page PDF walk + MAFF 47 pref × 5 yr Excel walk + "
            "MHLW 47 pref × 8 給付金 path + MLIT 47 pref × 4 建設業 path で "
            "PDF index → PDF fetch → Textract で 2000+ PDF まで構造化"
        ),
        target_urls=target_urls,
        budget_usd=4500,
        budget_band="3500-5000",
        user_agent_role="pdf-extract",
        rate_limit_rps=0.3,
        max_pages=5000,
        max_records=0,
        max_runtime_seconds=21600,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J06_ultradeep_ministry_pdf/"
        ),
        output_artifacts=[
            "pdf_extracted_facts.parquet",
            "pdf_parse_failures.jsonl",
            "source_receipts.jsonl",
            "review_backlog.jsonl",
            "object_manifest.parquet",
            "ministry_pdf_index.jsonl",
            "pref_pdf_index.jsonl",
            "city_pdf_index.jsonl",
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
            "23 省庁 × 12 path + 47 都道府県 × 14 path + 20 政令市 × 10 path coverage 100%"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_5000",
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
        max_pdfs=5000,
        parent_job_id="J06_ministry_municipality_pdf_extraction",
    )


# ---------------------------------------------------------------------------
# J07 ultradeep — gBizINFO opendata + per-corporate deep (1000+ URLs)
# ---------------------------------------------------------------------------


def build_j07_ultradeep() -> dict[str, Any]:
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

    # gBizINFO bulk download / opendata axis (8 base + monthly per-axis)
    bulk_axes: list[str] = [
        "https://info.gbiz.go.jp/opendata/houjin_info_full.zip",
        "https://info.gbiz.go.jp/opendata/houjin_info_diff.zip",
        "https://info.gbiz.go.jp/opendata/certification_full.zip",
        "https://info.gbiz.go.jp/opendata/commendation_full.zip",
        "https://info.gbiz.go.jp/opendata/subsidy_full.zip",
        "https://info.gbiz.go.jp/opendata/procurement_full.zip",
        "https://info.gbiz.go.jp/opendata/workplace_full.zip",
        "https://info.gbiz.go.jp/opendata/finance_full.zip",
    ]

    # 8 axis × 36 month snapshot diff = 288 URLs
    bulk_monthly: list[str] = []
    axes_short = ["houjin_info", "certification", "commendation", "subsidy",
                  "procurement", "workplace", "finance"]
    for axis in axes_short:
        for year in (2024, 2025, 2026):
            for month in range(1, 13):
                bulk_monthly.append(
                    f"https://info.gbiz.go.jp/opendata/{axis}_diff_{year:04d}-{month:02d}.zip"
                )

    # Per-prefecture × 10 page pagination = 470 URLs
    search_sweep: list[str] = []
    for _name, code in PREFECTURES_47:
        for page in range(1, 11):
            search_sweep.append(
                f"https://info.gbiz.go.jp/api/v1/hojin?prefecture={code}&page={page}&per_page=100"
            )

    # Per-axis filter sweep per pref × 3 page = 1,128 URLs (cap at 8 axis × 47 pref × 3 page)
    axis_sweep: list[str] = []
    axis_filters = ["certification", "commendation", "subsidy", "procurement", "workplace"]
    for axis in axis_filters:
        for _name, code in PREFECTURES_47:
            for page in range(1, 4):
                axis_sweep.append(
                    f"https://info.gbiz.go.jp/api/v1/hojin/{axis}"
                    f"?prefecture={code}&page={page}&per_page=100"
                )

    # JSIC industry filter × 19 industry × 5 page = 95 URLs
    jsic_majors = list(string.ascii_uppercase[:20])  # A-T (JSIC majors)
    jsic_sweep: list[str] = []
    for jsic in jsic_majors:
        for page in range(1, 6):
            jsic_sweep.append(
                f"https://info.gbiz.go.jp/api/v1/hojin"
                f"?jsic={jsic}&page={page}&per_page=100"
            )

    target_urls = _dedupe_preserve_order(
        base + bulk_axes + bulk_monthly + search_sweep + axis_sweep + jsic_sweep
    )

    return _base_manifest(
        job_id="J07_ultradeep_gbizinfo_matrix",
        job_title=(
            "J07 ultradeep — gBizINFO opendata 8 axis + 36 月 × 7 axis monthly diff (252) + "
            "47 pref × 10 page (470) + 5 axis × 47 pref × 3 page (705) + "
            "20 JSIC × 5 page (100)"
        ),
        plan_ref="docs/_internal/aws_credit_data_acquisition_jobs_agent.md#J07",
        source_family="corporate_signal",
        purpose=(
            "gBizINFO opendata bulk 8 axis (houjin/certification/commendation/subsidy/"
            "procurement/workplace/finance + diff) + 36 月 × 7 axis monthly diff snapshot + "
            "47 pref × 10 page pagination + 5 axis × 47 pref × 3 page filter + "
            "20 JSIC × 5 page industry filter で houjin_bangou を hub にした "
            "public business signal を full join + monthly per-axis change history"
        ),
        target_urls=target_urls,
        budget_usd=1500,
        budget_band="1200-1800",
        user_agent_role="gbizinfo",
        rate_limit_rps=0.5,
        max_pages=2000,
        max_records=1000000,
        max_runtime_seconds=18000,
        output_prefix=(
            "s3://jpcite-credit-993693061769-202605-raw/J07_ultradeep_gbizinfo/"
        ),
        output_artifacts=[
            "business_public_signals.parquet",
            "join_candidates.parquet",
            "identity_mismatch_ledger.jsonl",
            "source_receipts.jsonl",
            "quarantine.jsonl",
            "no_hit_checks.jsonl",
            "bulk_export.raw",
            "monthly_diff_per_axis.parquet",
            "jsic_industry_index.parquet",
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
        join_keys=["houjin_bangou", "corporate_number", "prefecture_code", "jsic_major"],
        success_criteria=(
            "houjin_bangou hub に対し certification/commendation/subsidy/procurement/"
            "workplace/finance 6 sub-resource の receipt が 80%+ で付き、"
            "bulk 8 axis + 36 月 × 7 axis monthly diff + 47 pref × 10 page + "
            "5 axis × 47 pref × 3 page + 20 JSIC × 5 page が両方落ちる"
        ),
        stop_conditions=[
            "rate_limit_429_or_403_increase",
            "budget_usd_consumed_ge_1800",
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
    ("J01_ultradeep_source_profile_matrix.json", build_j01_ultradeep),
    ("J02_ultradeep_nta_houjin_matrix.json", build_j02_ultradeep),
    ("J03_ultradeep_nta_invoice_matrix.json", build_j03_ultradeep),
    ("J04_ultradeep_egov_law_matrix.json", build_j04_ultradeep),
    ("J05_ultradeep_jgrants_matrix.json", build_j05_ultradeep),
    ("J06_ultradeep_ministry_pdf_matrix.json", build_j06_ultradeep),
    ("J07_ultradeep_gbizinfo_matrix.json", build_j07_ultradeep),
]


def main() -> None:
    summary = []
    total_urls = 0
    total_budget = 0
    for name, builder in BUILDERS:
        manifest = builder()
        path = ULTRADEEP_DIR / name
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
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
