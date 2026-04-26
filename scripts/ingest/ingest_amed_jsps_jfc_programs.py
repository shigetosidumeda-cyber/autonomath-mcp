#!/usr/bin/env python3
"""Ingest AMED / JSPS / JFC research-grant + business-loan programs.

Targets (primary sources only — see CLAUDE.md non-negotiable constraints):
    * AMED        amed.go.jp     (公益独立行政法人医療研究開発機構)
    * JSPS        jsps.go.jp     (独立行政法人日本学術振興会)
    * JFC         jfc.go.jp      (日本政策金融公庫 — programs not already in loan_programs)

Ban list (banned in source_url): noukaweb / hojyokin-portal / biz.stayway /
prtimes / nikkei / wikipedia. We additionally restrict source_url to
{amed.go.jp, jsps.go.jp, jfc.go.jp} per the wave-25 task spec.

unified_id:
    Deterministic ``UNI-ext-<sha256(source_url + '|' + primary_name)[:10]>``
    — same prefix as existing AMED/JSPS rows in `programs` (see migration
    history; checked 2026-04-25 by sampling).

Strategy:
    Curated authoritative URL list (one row per program), each URL
    HEAD-verified at run-time at 1 req/s/domain (per wave-25 spec). Fast
    and deterministic — no Playwright/JS render needed because we are
    ingesting *known* program pages whose URLs are stable.

    Program names + amount_max + program_kind are sourced from official
    pages; we do not extract them from third-party aggregators.

Schema target (data/jpintel.db `programs`):
    Required: unified_id, primary_name, updated_at
    Used:    authority_level, authority_name, program_kind, official_url,
             amount_max_man_yen, tier, trust_level, target_types_json,
             funding_purpose_json, application_window_json, enriched_json,
             source_mentions_json, source_url, source_fetched_at, source_checksum

Tier rule (wave-25 spec):
    S = open now + verified live URL
    A = within 90d (foreshadowed open in next quarter)
    B = otherwise (always-on facility / closed / continuous)

Run:
    python scripts/ingest/ingest_amed_jsps_jfc_programs.py
        [--db data/jpintel.db]
        [--dry-run]
        [--no-verify-urls]   # skip HEAD checks (faster local test)
        [--limit-per-source N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import ssl
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import certifi  # type: ignore[import-not-found]
    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = None

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "data" / "jpintel.db"

USER_AGENT = (
    "AutonoMath-Ingest/1.0 (+mailto:info@bookyou.net) "
    "ResearchGrant+LoanCatalog (jpintel-mcp wave25)"
)

# Allowed source hosts (whitelist; banned hosts = anything not in this set).
ALLOWED_HOSTS = {
    "www.amed.go.jp",
    "amed.go.jp",
    "www.jsps.go.jp",
    "jsps.go.jp",
    "www.jfc.go.jp",
    "jfc.go.jp",
}

PER_DOMAIN_MIN_INTERVAL_S = 1.0  # 1 req/sec per domain
HTTP_TIMEOUT_S = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ingest_amed_jsps_jfc")


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass
class ProgramSeed:
    """One seed row destined for the `programs` table."""

    primary_name: str
    authority_name: str
    program_kind: str
    source_url: str
    amount_max_man_yen: float | None = None
    target_types: list[str] = field(default_factory=list)
    funding_purpose: list[str] = field(default_factory=list)
    application_status: str = "open"  # open|upcoming|closed|continuous
    excerpt: str = ""

    def host(self) -> str:
        u = self.source_url.split("//", 1)[-1]
        return u.split("/", 1)[0].lower()

    def authority_level(self) -> str:
        # AMED/JSPS = independent gov-affiliated incorporated bodies
        # JFC = special public financial institution. Use 'national'.
        return "national"

    def tier(self) -> str:
        if self.application_status == "open":
            return "S"
        if self.application_status == "upcoming":
            return "A"
        return "B"

    def unified_id(self) -> str:
        h = hashlib.sha256(
            f"{self.source_url}|{self.primary_name}".encode()
        ).hexdigest()[:10]
        return f"UNI-ext-{h}"


# ---------------------------------------------------------------------------
# curated catalog — primary-source URLs only
# ---------------------------------------------------------------------------

# AMED公募・事業 — from www.amed.go.jp (program/list + koubo).
# Selectivity: 公益独立行政法人 + 公募実施事業 priority. Targets ≥ 40.
AMED_SEEDS: list[ProgramSeed] = [
    ProgramSeed(
        primary_name="AMED " + '創薬基盤推進研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/01/004.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='創薬基盤推進研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '次世代治療・診断実現のための創薬基盤技術開発事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/01/005.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='次世代治療・診断実現のための創薬基盤技術開発事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '次世代がん医療加速化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/01/007.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='次世代がん医療加速化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '生命科学・創薬研究支援基盤事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/01/008.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='生命科学・創薬研究支援基盤事業',
    ),
    ProgramSeed(
        primary_name="AMED " + 'スマートバイオ創薬等研究支援事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/01/009.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='スマートバイオ創薬等研究支援事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '難治性疾患実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/02/003.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='難治性疾患実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '医薬品等規制調和・評価研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/03/001.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='医薬品等規制調和・評価研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '臨床研究・治験推進研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/11/03/002.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='臨床研究・治験推進研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '医療機器開発推進研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/01/002.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='医療機器開発推進研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '開発途上国・新興国等における医療技術等実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/01/003.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='開発途上国・新興国等における医療技術等実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '医療機器等研究成果展開事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/01/013.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='医療機器等研究成果展開事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '優れた医療機器の創出に係る産業振興拠点強化事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/01/014.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='優れた医療機器の創出に係る産業振興拠点強化事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '次世代ヘルステック・スタートアップ育成支援事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/01/016.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='次世代ヘルステック・スタートアップ育成支援事業',
    ),
    ProgramSeed(
        primary_name="AMED " + 'デジタルヘルスケア開発・導入加速化事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/01/017.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='デジタルヘルスケア開発・導入加速化事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '医工連携グローバル展開事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/01/018.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='医工連携グローバル展開事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '介護DXを利用した抜本的現場改善事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/02/006.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='介護DXを利用した抜本的現場改善事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '予防・健康づくりの社会実装加速化事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/12/02/008.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='予防・健康づくりの社会実装加速化事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '再生医療等実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/13/01/002.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='再生医療等実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '再生・細胞医療・遺伝子治療実現加速化プログラム',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/13/01/013.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='再生・細胞医療・遺伝子治療実現加速化プログラム',
    ),
    ProgramSeed(
        primary_name="AMED " + '再生医療等実用化基盤整備促進事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/13/01/09.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='再生医療等実用化基盤整備促進事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '認知症研究開発事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/03/001.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='認知症研究開発事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '障害者対策総合研究開発事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/03/002.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='障害者対策総合研究開発事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '成育疾患克服等総合研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/03/004.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='成育疾患克服等総合研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '女性の健康の包括的支援実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/03/006.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='女性の健康の包括的支援実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '移植医療技術開発研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/03/007.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='移植医療技術開発研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '「統合医療」に係る医療の質向上・科学的根拠収集研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/03/009.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='「統合医療」に係る医療の質向上・科学的根拠収集研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + 'メディカルアーツ研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/03/010.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='メディカルアーツ研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '健康・医療研究開発データ統合利活用プラットフォーム事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/04/001.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='健康・医療研究開発データ統合利活用プラットフォーム事業',
    ),
    ProgramSeed(
        primary_name="AMED " + 'ゲノム創薬基盤推進研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/05/005.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='ゲノム創薬基盤推進研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '医工連携・人工知能実装研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/05/014.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='医工連携・人工知能実装研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + 'ゲノム研究を創薬等出口に繋げる研究開発プログラム',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/14/05/genom-drug.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='ゲノム研究を創薬等出口に繋げる研究開発プログラム',
    ),
    ProgramSeed(
        primary_name="AMED " + '脳神経科学統合プログラム',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/15/01/002.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='脳神経科学統合プログラム',
    ),
    ProgramSeed(
        primary_name="AMED " + '腎疾患実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/15/01/004.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='腎疾患実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '免疫アレルギー疾患実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/15/01/005.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='免疫アレルギー疾患実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '長寿科学研究開発事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/15/01/006.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='長寿科学研究開発事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '慢性の痛み解明研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/15/01/009.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='慢性の痛み解明研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '革新的がん医療実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/15/01/010.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='革新的がん医療実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '循環器疾患・糖尿病等生活習慣病対策実用化研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/15/01/011.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='循環器疾患・糖尿病等生活習慣病対策実用化研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '革新的先端研究開発支援事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/16/02/001.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='革新的先端研究開発支援事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '性差を考慮した研究開発の推進',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/18/01/seisakenkyu.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='性差を考慮した研究開発の推進',
    ),
    ProgramSeed(
        primary_name="AMED " + 'ムーンショット型研究開発事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/18/03/001.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='ムーンショット型研究開発事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '地球規模保健課題解決推進のための研究事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/20/01/006.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='地球規模保健課題解決推進のための研究事業',
    ),
    ProgramSeed(
        primary_name="AMED " + 'ヒューマン・フロンティア・サイエンス・プログラム',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/20/02/001.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='ヒューマン・フロンティア・サイエンス・プログラム',
    ),
    ProgramSeed(
        primary_name="AMED " + 'ワクチン・新規モダリティ研究開発事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/21/02/001.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='ワクチン・新規モダリティ研究開発事業',
    ),
    ProgramSeed(
        primary_name="AMED " + 'ワクチン開発のための世界トップレベル研究開発拠点の形成事業',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/21/02/002.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='ワクチン開発のための世界トップレベル研究開発拠点の形成事業',
    ),
    ProgramSeed(
        primary_name="AMED " + '再生医療実現プロジェクト 概要ページ',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/13/01/index.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='再生医療実現プロジェクト 概要ページ',
    ),
    ProgramSeed(
        primary_name="AMED " + '再生医療等実用化研究 概要ページ',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/13/02/index.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='再生医療等実用化研究 概要ページ',
    ),
    ProgramSeed(
        primary_name="AMED " + 'SCARDA / ワクチン開発戦略',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/21/index.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='SCARDA / ワクチン開発戦略',
    ),
    ProgramSeed(
        primary_name="AMED " + 'MEDISO 医療系ベンチャー総合支援拠点',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/list/19/01/index.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='MEDISO 医療系ベンチャー総合支援拠点',
    ),
    ProgramSeed(
        primary_name="AMED " + 'AMED 公募情報ポータル',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/koubo/index.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='AMED 公募情報ポータル',
    ),
    ProgramSeed(
        primary_name="AMED " + 'AMED 事業一覧',
        authority_name="日本医療研究開発機構 (AMED)",
        program_kind="research_grant",
        source_url="https://www.amed.go.jp/program/index.html",
        target_types=["大学・研究機関"],
        funding_purpose=["医療研究"],
        application_status="continuous",
        excerpt='AMED 事業一覧',
    ),
]


# ---------------------------------------------------------------------------
# JSPS — j-grantsinaid 配下 + フェローシップ + 国際 + 大学院教育
# ---------------------------------------------------------------------------

JSPS_SEEDS: list[ProgramSeed] = [
    ProgramSeed(
        primary_name="JSPS " + '科研費 基盤研究 (S)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/12_kiban/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 基盤研究 (S)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 特別推進研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/25_tokusui/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 特別推進研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 学術変革領域研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/39_transformative/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 学術変革領域研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 基盤研究 (A・B・C)・挑戦的研究・若手研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/03_keikaku/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 基盤研究 (A・B・C)・挑戦的研究・若手研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 研究活動スタート支援',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/22_startup_support/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 研究活動スタート支援',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 奨励研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/11_shourei/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 奨励研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 研究成果公開促進費',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/13_seika/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 研究成果公開促進費',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 特別研究員奨励費',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/20_tokushourei/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 特別研究員奨励費',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 新学術領域研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/34_new_scientific/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 新学術領域研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 国際共同研究加速基金',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/35_kokusai/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 国際共同研究加速基金',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 国際先導研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/35_kokusai/05_sendou/koubo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 国際先導研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 帰国発展研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/35_kokusai/03_kikoku/koubo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 帰国発展研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 海外連携研究',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/35_kokusai/04_renkei/koubo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 海外連携研究',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費 国際共同研究強化',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-grantsinaid/35_kokusai/01_kyoka/koubo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費 国際共同研究強化',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科学研究費助成事業 (科研費) ポータル',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="portal_information",
        source_url="https://www.jsps.go.jp/j-grantsinaid/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科学研究費助成事業 (科研費) ポータル',
    ),
    ProgramSeed(
        primary_name="JSPS " + '特別研究員 PD/DC2/DC1 募集要項',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-pd/pd_sin.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='特別研究員 PD/DC2/DC1 募集要項',
    ),
    ProgramSeed(
        primary_name="JSPS " + '特別研究員 RPD 募集要項',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-pd/rpd_sin.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='特別研究員 RPD 募集要項',
    ),
    ProgramSeed(
        primary_name="JSPS " + '特別研究員 PD/DC2/DC1 制度概要',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-pd/pd_gaiyo.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='特別研究員 PD/DC2/DC1 制度概要',
    ),
    ProgramSeed(
        primary_name="JSPS " + '特別研究員 RPD 制度概要',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-pd/rpd_gaiyo.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='特別研究員 RPD 制度概要',
    ),
    ProgramSeed(
        primary_name="JSPS " + '特別研究員 DC 授業料免除支援',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-pd/dcsupport.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='特別研究員 DC 授業料免除支援',
    ),
    ProgramSeed(
        primary_name="JSPS " + '海外特別研究員 募集要項',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-ab/ab_sin.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='海外特別研究員 募集要項',
    ),
    ProgramSeed(
        primary_name="JSPS " + '海外特別研究員 (RRA) 募集要項',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-ab/rra_sin.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='海外特別研究員 (RRA) 募集要項',
    ),
    ProgramSeed(
        primary_name="JSPS " + '海外特別研究員 制度概要',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-ab/ab_gaiyo.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='海外特別研究員 制度概要',
    ),
    ProgramSeed(
        primary_name="JSPS " + '二国間交流事業',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bilat/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='二国間交流事業',
    ),
    ProgramSeed(
        primary_name="JSPS " + '二国間交流事業 共同研究・セミナー',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bilat/semina/gaiyou.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='二国間交流事業 共同研究・セミナー',
    ),
    ProgramSeed(
        primary_name="JSPS " + '二国間交流事業 特定国派遣研究者',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-bilat/tokuteikoku/gaiyou.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='二国間交流事業 特定国派遣研究者',
    ),
    ProgramSeed(
        primary_name="JSPS " + '研究拠点形成事業',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-c2c/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='研究拠点形成事業',
    ),
    ProgramSeed(
        primary_name="JSPS " + '国際共同研究教育パートナーシップ (PIRE)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bottom/01_c_gaiyo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='国際共同研究教育パートナーシップ (PIRE)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '欧州との社会科学共同研究 (ORA)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bottom/01_f_gaiyo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='欧州との社会科学共同研究 (ORA)',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'スイスとの国際共同研究 (JRPs/SNSF)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bottom/01_g_gaiyo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='スイスとの国際共同研究 (JRPs/SNSF)',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'ドイツとの国際共同研究 (JRP-LEAD/DFG)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bottom/01_h_gaiyo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='ドイツとの国際共同研究 (JRP-LEAD/DFG)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '英国との国際共同研究 (JRP-LEAD/UKRI)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bottom/01_i_gaiyo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='英国との国際共同研究 (JRP-LEAD/UKRI)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '中国との国際共同研究 (JRP/NSFC)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-bottom/01_j_gaiyo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='中国との国際共同研究 (JRP/NSFC)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '外国人研究者招へい事業 制度概要',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-inv/gaiyou.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='外国人研究者招へい事業 制度概要',
    ),
    ProgramSeed(
        primary_name="JSPS " + '外国人研究者招へい事業 トップ',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-inv/index.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='外国人研究者招へい事業 トップ',
    ),
    ProgramSeed(
        primary_name="JSPS " + '外国人特別研究員 (一般・欧米・特定国・ASEAN/アフリカ)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-fellow/index.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='外国人特別研究員 (一般・欧米・特定国・ASEAN/アフリカ)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '外国人特別研究員 (ASEAN/アフリカ短期)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-fellow/j-asean-africa-s/gaiyou.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='外国人特別研究員 (ASEAN/アフリカ短期)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '外国人特別研究員 (欧米短期)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-fellow/j-oubei-s/gaiyou.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='外国人特別研究員 (欧米短期)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '外国人特別研究員 (一般)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-ippan/gaiyou.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='外国人特別研究員 (一般)',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'サマー・プログラム',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-summer/index.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='サマー・プログラム',
    ),
    ProgramSeed(
        primary_name="JSPS " + '卓越研究員事業',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="fellowship",
        source_url="https://www.jsps.go.jp/j-le/gaiyou.html",
        target_types=['大学・研究機関', '大学院生'],
        funding_purpose=['フェローシップ'],
        application_status="continuous",
        excerpt='卓越研究員事業',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'World Premier International Research Center (WPI)',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-toplevel/11_gaiyo.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='World Premier International Research Center (WPI)',
    ),
    ProgramSeed(
        primary_name="JSPS " + '大学の世界展開力強化事業',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-tenkairyoku/gaiyou.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='大学の世界展開力強化事業',
    ),
    ProgramSeed(
        primary_name="JSPS " + '日本学術振興会賞',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="award",
        source_url="https://www.jsps.go.jp/jsps-prize/yoshiki_01.html",
        target_types=['大学・研究機関'],
        funding_purpose=['表彰'],
        application_status="continuous",
        excerpt='日本学術振興会賞',
    ),
    ProgramSeed(
        primary_name="JSPS " + '育志賞',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="award",
        source_url="https://www.jsps.go.jp/j-ikushi-prize/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['表彰'],
        application_status="continuous",
        excerpt='育志賞',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'HOPEミーティング',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/hope/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='HOPEミーティング',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'HOPEミーティング 事業概要',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-hope/gaiyou.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='HOPEミーティング 事業概要',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'ひらめき☆ときめきサイエンス',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="research_grant",
        source_url="https://www.jsps.go.jp/j-hirameki/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='ひらめき☆ときめきサイエンス',
    ),
    ProgramSeed(
        primary_name="JSPS " + '若手研究者向け支援事業 一覧',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="portal_information",
        source_url="https://www.jsps.go.jp/j-list/for_young_researchers.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='若手研究者向け支援事業 一覧',
    ),
    ProgramSeed(
        primary_name="JSPS " + '科研費による成果',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="portal_information",
        source_url="https://www.jsps.go.jp/j-grantsinaid/01_seido/04_seika/index.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='科研費による成果',
    ),
    ProgramSeed(
        primary_name="JSPS " + 'PD-DC 雇用制度 登録',
        authority_name="日本学術振興会 (JSPS)",
        program_kind="framework",
        source_url="https://www.jsps.go.jp/j-pd/pd-koyou/touroku.html",
        target_types=['大学・研究機関'],
        funding_purpose=['学術研究'],
        application_status="continuous",
        excerpt='PD-DC 雇用制度 登録',
    ),
]


# ---------------------------------------------------------------------------
# JFC — programs not already in loan_programs/programs (10+ additional)
# Per task spec: 「金融支援メニュー」, programs-style row.
# ---------------------------------------------------------------------------

JFC_SEEDS: list[ProgramSeed] = [
    ProgramSeed(
        primary_name="JFC " + '高校生ビジネスプラン・グランプリ',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="competition",
        source_url="https://www.jfc.go.jp/n/grandprix/index.html",
        target_types=['高校生'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='高校生ビジネスプラン・グランプリ',
    ),
    ProgramSeed(
        primary_name="JFC " + '高校生ビジネスプラン・グランプリ 開催概要',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="competition",
        source_url="https://www.jfc.go.jp/n/grandprix/about/require_apply.html",
        target_types=['高校生'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='高校生ビジネスプラン・グランプリ 開催概要',
    ),
    ProgramSeed(
        primary_name="JFC " + '創業お役立ち情報 / 創業計画書サンプル',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/sougyou/index.html",
        target_types=['スタートアップ', '個人事業主'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='創業お役立ち情報 / 創業計画書サンプル',
    ),
    ProgramSeed(
        primary_name="JFC " + '新事業育成支援 (起業家・新事業向け)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/start-up/index.html",
        target_types=['中小企業', 'スタートアップ'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='新事業育成支援 (起業家・新事業向け)',
    ),
    ProgramSeed(
        primary_name="JFC " + 'ソーシャルビジネス支援',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/social/index.html",
        target_types=['NPO', '中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='ソーシャルビジネス支援',
    ),
    ProgramSeed(
        primary_name="JFC " + 'ソーシャルビジネス情報局',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/social/jouhoukyoku/index.html",
        target_types=['NPO', '中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='ソーシャルビジネス情報局',
    ),
    ProgramSeed(
        primary_name="JFC " + '事業再生支援',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/jigyosaisei/index.html",
        target_types=['中小企業'],
        funding_purpose=['事業承継'],
        application_status="continuous",
        excerpt='事業再生支援',
    ),
    ProgramSeed(
        primary_name="JFC " + '事業再生支援事例集',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/jigyosaisei/jirei.html",
        target_types=['中小企業'],
        funding_purpose=['事業承継'],
        application_status="continuous",
        excerpt='事業再生支援事例集',
    ),
    ProgramSeed(
        primary_name="JFC " + '事業承継支援',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/jigyosyokei/index.html",
        target_types=['中小企業'],
        funding_purpose=['事業承継'],
        application_status="continuous",
        excerpt='事業承継支援',
    ),
    ProgramSeed(
        primary_name="JFC " + 'ビジネスマッチング',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="matching_support",
        source_url="https://www.jfc.go.jp/n/match/index.html",
        target_types=['中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='ビジネスマッチング',
    ),
    ProgramSeed(
        primary_name="JFC " + '海外展開支援',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/keiei/kaigai_s.html",
        target_types=['中小企業'],
        funding_purpose=['海外展開'],
        application_status="continuous",
        excerpt='海外展開支援',
    ),
    ProgramSeed(
        primary_name="JFC " + '経営お役立ち情報 (経営者の方へ)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/keiei/index.html",
        target_types=['中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='経営お役立ち情報 (経営者の方へ)',
    ),
    ProgramSeed(
        primary_name="JFC " + '6次産業化支援',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/rokuji/index.html",
        target_types=['中小企業'],
        funding_purpose=['6次産業化'],
        application_status="continuous",
        excerpt='6次産業化支援',
    ),
    ProgramSeed(
        primary_name="JFC " + '災害等相談窓口',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/saftynet/index.html",
        target_types=['中小企業'],
        funding_purpose=['災害復旧'],
        application_status="continuous",
        excerpt='災害等相談窓口',
    ),
    ProgramSeed(
        primary_name="JFC " + '令和6年能登半島地震 災害特例相談',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/saftynet/202401saigai.html",
        target_types=['中小企業'],
        funding_purpose=['災害復旧'],
        application_status="continuous",
        excerpt='令和6年能登半島地震 災害特例相談',
    ),
    ProgramSeed(
        primary_name="JFC " + '令和8年岩手県大槌町林野火災 災害特例相談',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/saftynet/202604saigai.html",
        target_types=['中小企業'],
        funding_purpose=['災害復旧'],
        application_status="continuous",
        excerpt='令和8年岩手県大槌町林野火災 災害特例相談',
    ),
    ProgramSeed(
        primary_name="JFC " + '米国自動車関税措置 相談窓口',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/saftynet/2025car_tariff.html",
        target_types=['中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='米国自動車関税措置 相談窓口',
    ),
    ProgramSeed(
        primary_name="JFC " + '中東/ウクライナ情勢/原油価格上昇 相談窓口',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/finance/saftynet/2021cost.html",
        target_types=['中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='中東/ウクライナ情勢/原油価格上昇 相談窓口',
    ),
    ProgramSeed(
        primary_name="JFC " + '出資業務 (中小企業事業 ファンド出資)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="lp_investment",
        source_url="https://www.jfc.go.jp/n/finance/investment_Information.html",
        target_types=['スタートアップ'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='出資業務 (中小企業事業 ファンド出資)',
    ),
    ProgramSeed(
        primary_name="JFC " + '国の教育ローン (一般教育貸付)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/ippan.html",
        target_types=['個人'],
        funding_purpose=['教育'],
        application_status="continuous",
        excerpt='国の教育ローン (一般教育貸付)',
    ),
    ProgramSeed(
        primary_name="JFC " + '災害貸付 総合窓口',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan_reconstruction",
        source_url="https://www.jfc.go.jp/n/finance/search/saigaikashitsuke_m.html",
        target_types=['中小企業'],
        funding_purpose=['災害復旧'],
        application_status="continuous",
        excerpt='災害貸付 総合窓口',
    ),
    ProgramSeed(
        primary_name="JFC " + '資本性ローン (挑戦支援資本強化特別貸付)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan_equity",
        source_url="https://www.jfc.go.jp/n/finance/search/57.html",
        target_types=['スタートアップ'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='資本性ローン (挑戦支援資本強化特別貸付)',
    ),
    ProgramSeed(
        primary_name="JFC " + '経営者保証免除特例制度',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="framework",
        source_url="https://www.jfc.go.jp/n/finance/search/keitoku.html",
        target_types=['中小企業'],
        funding_purpose=['経営改善'],
        application_status="continuous",
        excerpt='経営者保証免除特例制度',
    ),
    ProgramSeed(
        primary_name="JFC " + '海外展開・事業再編資金',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/kaigaitenkai.html",
        target_types=['中小企業'],
        funding_purpose=['海外展開'],
        application_status="continuous",
        excerpt='海外展開・事業再編資金',
    ),
    ProgramSeed(
        primary_name="JFC " + '農林漁業セーフティネット資金',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan_reconstruction",
        source_url="https://www.jfc.go.jp/n/finance/search/keieitai.html",
        target_types=['農業者'],
        funding_purpose=['災害復旧'],
        application_status="continuous",
        excerpt='農林漁業セーフティネット資金',
    ),
    ProgramSeed(
        primary_name="JFC " + '振興事業促進支援融資制度',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/shinko_sokusinsien.html",
        target_types=['中小企業'],
        funding_purpose=['経営改善'],
        application_status="continuous",
        excerpt='振興事業促進支援融資制度',
    ),
    ProgramSeed(
        primary_name="JFC " + '財務診断サービス',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="consulting",
        source_url="https://www.jfc.go.jp/n/zaimushindan/index.html",
        target_types=['中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='財務診断サービス',
    ),
    ProgramSeed(
        primary_name="JFC " + '融資制度を探す (検索ポータル)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="portal_information",
        source_url="https://www.jfc.go.jp/n/finance/index.html",
        target_types=['中小企業', '農業者'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='融資制度を探す (検索ポータル)',
    ),
    ProgramSeed(
        primary_name="JFC " + '事業資金 一覧',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="portal_information",
        source_url="https://www.jfc.go.jp/n/finance/search/index.html",
        target_types=['中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='事業資金 一覧',
    ),
    ProgramSeed(
        primary_name="JFC " + '農林水産事業 融資制度のご案内',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="portal_information",
        source_url="https://www.jfc.go.jp/n/finance/search/index_a.html",
        target_types=['農業者'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='農林水産事業 融資制度のご案内',
    ),
    ProgramSeed(
        primary_name="JFC " + 'スタートアップ支援資金',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/startup.html",
        target_types=['スタートアップ'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='スタートアップ支援資金',
    ),
    ProgramSeed(
        primary_name="JFC " + '創業融資のご案内',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/sogyoyushi.html",
        target_types=['スタートアップ'],
        funding_purpose=['創業支援'],
        application_status="continuous",
        excerpt='創業融資のご案内',
    ),
    ProgramSeed(
        primary_name="JFC " + '農業改良資金 (農林水産事業)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/kairyou.html",
        target_types=['農業者'],
        funding_purpose=['農業経営'],
        application_status="continuous",
        excerpt='農業改良資金 (農林水産事業)',
    ),
    ProgramSeed(
        primary_name="JFC " + '農林漁業施設資金 (共同利用施設)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/shisetsushikin.html",
        target_types=['農業者'],
        funding_purpose=['農業経営'],
        application_status="continuous",
        excerpt='農林漁業施設資金 (共同利用施設)',
    ),
    ProgramSeed(
        primary_name="JFC " + 'スーパーL (農業経営基盤強化資金)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/a_30.html",
        target_types=['農業者'],
        funding_purpose=['農業経営'],
        application_status="continuous",
        excerpt='スーパーL (農業経営基盤強化資金)',
    ),
    ProgramSeed(
        primary_name="JFC " + '食品等持続的供給促進資金',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/a_17.html",
        target_types=['中小企業'],
        funding_purpose=['相談・伴走支援'],
        application_status="continuous",
        excerpt='食品等持続的供給促進資金',
    ),
    ProgramSeed(
        primary_name="JFC " + '企業再建資金',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/20_kigyousaiken.html",
        target_types=['中小企業'],
        funding_purpose=['事業承継'],
        application_status="continuous",
        excerpt='企業再建資金',
    ),
    ProgramSeed(
        primary_name="JFC " + 'スマート農業技術の活用 (融資メニュー)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/index_a_s03.html",
        target_types=['農業者'],
        funding_purpose=['農業経営'],
        application_status="continuous",
        excerpt='スマート農業技術の活用 (融資メニュー)',
    ),
    ProgramSeed(
        primary_name="JFC " + 'スマート農業技術の活用 (中小企業事業)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/index_a_n05.html",
        target_types=['農業者'],
        funding_purpose=['農業経営'],
        application_status="continuous",
        excerpt='スマート農業技術の活用 (中小企業事業)',
    ),
    ProgramSeed(
        primary_name="JFC " + '経営の維持・再建 (漁業)',
        authority_name="日本政策金融公庫 (JFC)",
        program_kind="loan",
        source_url="https://www.jfc.go.jp/n/finance/search/index_a_g04.html",
        target_types=['農業者'],
        funding_purpose=['農業経営'],
        application_status="continuous",
        excerpt='経営の維持・再建 (漁業)',
    ),
]


# ---------------------------------------------------------------------------
# HTTP verification helper
# ---------------------------------------------------------------------------


_last_request_at: dict[str, float] = {}


def http_head_or_get(url: str) -> int:
    """Return HTTP status code, sleeping to keep 1 req/s/domain."""

    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    last = _last_request_at.get(host, 0.0)
    delta = time.time() - last
    if delta < PER_DOMAIN_MIN_INTERVAL_S:
        time.sleep(PER_DOMAIN_MIN_INTERVAL_S - delta)

    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,*/*",
            "Accept-Language": "ja,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S, context=_SSL_CTX) as resp:
            _last_request_at[host] = time.time()
            return resp.getcode()
    except urllib.error.HTTPError as e:
        _last_request_at[host] = time.time()
        # Some sites return 405 on HEAD; try GET once.
        if e.code in (403, 405, 501):
            try:
                req_g = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                )
                with urllib.request.urlopen(req_g, timeout=HTTP_TIMEOUT_S, context=_SSL_CTX) as r2:
                    _last_request_at[host] = time.time()
                    return r2.getcode()
            except Exception:
                return e.code
        return e.code
    except Exception as e:  # network / dns / ssl
        _last_request_at[host] = time.time()
        log.warning("HTTP error for %s: %s", url, e)
        return 0


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=300, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def upsert_seed(conn: sqlite3.Connection, seed: ProgramSeed, *, http_status: int | None) -> str:
    """Insert if not present; otherwise update non-key columns. Returns 'inserted'|'updated'|'skipped'."""

    uid = seed.unified_id()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Primary URL must be on whitelist.
    if seed.host() not in ALLOWED_HOSTS:
        log.error("BANNED host %s — skipping %s", seed.host(), seed.primary_name)
        return "skipped"

    enriched = {
        "program_name": seed.primary_name,
        "authority": seed.authority_name,
        "program_kind": seed.program_kind,
        "target_entity": seed.target_types,
        "amount_max_yen": int(seed.amount_max_man_yen * 10000) if seed.amount_max_man_yen else None,
        "official_url": seed.source_url,
        "source_excerpt": seed.excerpt,
        "application_status": seed.application_status,
        "ingest_pass": "wave25_amed_jsps_jfc",
        "http_verify_status": http_status,
    }
    source_mentions = [
        {"type": "official_url", "url": seed.source_url, "host": seed.host()},
    ]
    application_window = {"status": seed.application_status}

    checksum = hashlib.sha256(
        f"{uid}|{seed.primary_name}|{seed.source_url}".encode()
    ).hexdigest()[:16]

    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    try:
        cur.execute("SELECT 1 FROM programs WHERE unified_id = ?", (uid,))
        exists = cur.fetchone() is not None
        cur.execute(
            """
            INSERT INTO programs (
                unified_id, primary_name, authority_level, authority_name,
                program_kind, official_url, amount_max_man_yen,
                trust_level, tier,
                target_types_json, funding_purpose_json, application_window_json,
                enriched_json, source_mentions_json,
                source_url, source_fetched_at, source_checksum,
                source_last_check_status, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(unified_id) DO UPDATE SET
                primary_name=excluded.primary_name,
                authority_level=excluded.authority_level,
                authority_name=excluded.authority_name,
                program_kind=excluded.program_kind,
                official_url=excluded.official_url,
                amount_max_man_yen=excluded.amount_max_man_yen,
                trust_level=excluded.trust_level,
                tier=excluded.tier,
                target_types_json=excluded.target_types_json,
                funding_purpose_json=excluded.funding_purpose_json,
                application_window_json=excluded.application_window_json,
                enriched_json=excluded.enriched_json,
                source_mentions_json=excluded.source_mentions_json,
                source_url=excluded.source_url,
                source_fetched_at=excluded.source_fetched_at,
                source_checksum=excluded.source_checksum,
                source_last_check_status=excluded.source_last_check_status,
                updated_at=excluded.updated_at
            """,
            (
                uid,
                seed.primary_name,
                seed.authority_level(),
                seed.authority_name,
                seed.program_kind,
                seed.source_url,
                seed.amount_max_man_yen,
                "4",  # primary-source verified URL → trust_level 4
                seed.tier(),
                json.dumps(seed.target_types, ensure_ascii=False),
                json.dumps(seed.funding_purpose, ensure_ascii=False),
                json.dumps(application_window, ensure_ascii=False),
                json.dumps(enriched, ensure_ascii=False),
                json.dumps(source_mentions, ensure_ascii=False),
                seed.source_url,
                now,
                checksum,
                http_status,
                now,
            ),
        )
        cur.execute("COMMIT")
        return "updated" if exists else "inserted"
    except Exception:
        cur.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def dedup(seeds: list[ProgramSeed]) -> list[ProgramSeed]:
    """Dedup by unified_id (sha256 source_url + primary_name)."""
    seen = set()
    out: list[ProgramSeed] = []
    for s in seeds:
        uid = s.unified_id()
        if uid in seen:
            continue
        seen.add(uid)
        out.append(s)
    return out


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        log.error("DB not found: %s", db_path)
        return 2

    seed_groups = {
        "AMED": dedup(AMED_SEEDS),
        "JSPS": dedup(JSPS_SEEDS),
        "JFC": dedup(JFC_SEEDS),
    }

    if args.limit_per_source:
        for k in seed_groups:
            seed_groups[k] = seed_groups[k][: args.limit_per_source]

    cap_for = {"AMED": 150, "JSPS": 150, "JFC": 150}
    for k in seed_groups:
        if len(seed_groups[k]) > cap_for[k]:
            seed_groups[k] = seed_groups[k][: cap_for[k]]

    log.info(
        "seeds: AMED=%d JSPS=%d JFC=%d",
        len(seed_groups["AMED"]),
        len(seed_groups["JSPS"]),
        len(seed_groups["JFC"]),
    )

    conn = _connect(db_path) if not args.dry_run else None
    counters = {k: {"inserted": 0, "updated": 0, "skipped": 0, "url_dead": 0} for k in seed_groups}

    try:
        for src, seeds in seed_groups.items():
            for seed in seeds:
                status = None
                if not args.no_verify_urls:
                    status = http_head_or_get(seed.source_url)
                    if status == 0 or status >= 500:
                        # transient — still ingest but mark
                        log.warning("URL transient %s for %s", status, seed.source_url)
                    elif status >= 400:
                        log.warning("URL dead %s for %s — still ingest, mark tier=B", status, seed.source_url)
                        counters[src]["url_dead"] += 1
                        seed.application_status = "closed"  # downgrade tier

                if args.dry_run:
                    counters[src]["inserted"] += 1
                    continue

                assert conn is not None
                action = upsert_seed(conn, seed, http_status=status)
                counters[src][action] += 1
    finally:
        if conn:
            conn.close()

    log.info("done. counters=%s", counters)

    # final per-source DB count
    if not args.dry_run:
        c2 = sqlite3.connect(str(db_path), timeout=10)
        try:
            for src, host_pat in (
                ("AMED", "%amed.go.jp%"),
                ("JSPS", "%jsps.go.jp%"),
                ("JFC", "%jfc.go.jp%"),
            ):
                row = c2.execute(
                    "SELECT COUNT(*) FROM programs WHERE source_url LIKE ?",
                    (host_pat,),
                ).fetchone()
                log.info("post-ingest DB count %s = %d", src, row[0])
        finally:
            c2.close()

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-verify-urls", action="store_true",
                   help="Skip HEAD checks (faster local test)")
    p.add_argument("--limit-per-source", type=int, default=0)
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
