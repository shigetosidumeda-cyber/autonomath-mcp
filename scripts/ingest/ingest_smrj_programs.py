"""Ingest 独立行政法人 中小企業基盤整備機構 (SMRJ) 補助金・制度 into jpintel.db.

Source: smrj.go.jp / j-net21.smrj.go.jp / sub-domains (it-shien / shoryokuka /
shinjigyou-shinshutsu / shoukei / yorozu / shoukei-mahojokin / kyosai-web / etc).
SMRJ は独立行政法人 (METI 所管). 一次資料に該当、PDL v1.0-compatible attribution.

Recon: analysis_wave18/data_collection_log/p5_recon_smrj.md (~56 programs).

Pattern:
  * Curated seed list of canonical SMRJ programs from recon (1-A〜1-L 56 cells).
  * For each entry:
      1. Fetch source_url at 1 req/s (User-Agent: AutonoMath/0.1.0)
      2. Parse title + meta description (BeautifulSoup) — use as fallback
         summary when entry lacks an explicit description.
      3. Build canonical program row (programs schema in jpintel.db).
      4. UPSERT (ON CONFLICT(unified_id) DO UPDATE) — idempotent.
  * Tier defaults to B (verified primary source, generic application window).
    A若干 (open NOW + verified) and S (fully populated) は seed で個別指定。
  * Excluded = 0. authority_level = 'national'. authority_name = 'SMRJ' or
    sub-organ (中小企業基盤整備機構). source_fetched_at stamped from probe.

Constraints:
  * NO Anthropic API. NO claude CLI invocation. Pure stdlib + bs4.
  * Rate-limit: 1 req/s to smrj.go.jp.
  * BEGIN IMMEDIATE + busy_timeout=300_000 (parallel-write safe).

Run:
  .venv/bin/python scripts/ingest/ingest_smrj_programs.py
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

try:
    import certifi  # type: ignore[import-untyped]

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "jpintel.db"

UA = "AutonoMath/0.1.0 (+https://bookyou.net)"
RATE_DELAY = 1.0  # seconds between requests
HTTP_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Seed: curated SMRJ programs (recon 1-A 〜 1-L, 56 cells minus ones already
# present in jpintel.db). Each tuple: (slug, name, source_url, kind, tier_hint,
# description_fallback, application_window, amount_max_man_yen, target_types,
# funding_purpose).
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class SmrjSeed:
    slug: str
    name: str
    source_url: str
    program_kind: str
    tier_hint: str
    description: str
    application_start: str | None = None
    application_end: str | None = None
    max_man_yen: float | None = None
    target_types: tuple[str, ...] = ("corporation", "sole_proprietor")
    funding_purpose: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


SEEDS: tuple[SmrjSeed, ...] = (
    # ------------------ 1-A 大型 国費補助金 (SMRJ 事務局運営) ------------------
    SmrjSeed(
        slug="smrj-jizokuka-shokokai-shokoukaigisho",
        name="小規模事業者持続化補助金 (商工会・商工会議所地区 共通制度)",
        source_url="https://s18.jizokukahojokin.info/index.php",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "小規模事業者の販路開拓・業務効率化等の取組に対する補助制度。"
            "商工会・商工会議所地区で共同事務局として SMRJ・全国商工会連合会・"
            "日本商工会議所が運営。一般型・創業型・災害支援枠等の枠あり。"
        ),
        application_start="2026-04-01",
        application_end=None,
        max_man_yen=200.0,
        funding_purpose=("販路開拓", "業務効率化", "創業"),
        aliases=("持続化補助金", "Jizokuka subsidy"),
    ),
    SmrjSeed(
        slug="smrj-monodukuri-seisansei",
        name="ものづくり・商業・サービス生産性向上促進補助金 (ものづくり補助金)",
        source_url="https://seisansei.smrj.go.jp/",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "中小企業生産性革命推進事業の柱。革新的サービス開発・試作品開発・"
            "生産プロセス改善のための設備投資等を支援。SMRJ が事業実施機関。"
        ),
        application_start="2026-04-01",
        max_man_yen=8000.0,
        funding_purpose=("設備投資", "生産性向上", "新事業"),
        aliases=("ものづくり補助金", "monodukuri"),
    ),
    SmrjSeed(
        slug="smrj-shoryokuka-ippan",
        name="中小企業省力化投資補助金 (一般型)",
        source_url="https://portal.shoryokuka.smrj.go.jp/ippan/",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "人手不足に直面する中小企業等の生産性向上・賃上げを実現するため、"
            "オーダーメイド型の省力化投資を支援する一般型枠。"
        ),
        max_man_yen=10000.0,
        funding_purpose=("省力化投資", "賃上げ", "DX"),
    ),
    SmrjSeed(
        slug="smrj-shoryokuka-catalog",
        name="中小企業省力化投資補助金 (カタログ注文型)",
        source_url="https://shoryokuka.smrj.go.jp/catalog/",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "中小企業庁・SMRJ がカタログ登録した省力化機器を低スペックで導入できる"
            "カタログ注文型枠。短時間採択・標準化された機器類。"
        ),
        max_man_yen=1500.0,
        funding_purpose=("省力化投資",),
    ),
    SmrjSeed(
        slug="smrj-shinjigyo-shinshutsu",
        name="中小企業新事業進出補助金",
        source_url="https://shinjigyou-shinshutsu.smrj.go.jp/",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "ポスト事業再構築の後継制度。既存事業から新分野への進出を支援する"
            "新事業進出枠。SMRJ が事業実施機関。"
        ),
        max_man_yen=9000.0,
        funding_purpose=("新事業", "事業転換", "設備投資"),
    ),
    SmrjSeed(
        slug="smrj-seicho-100oku",
        name="中小企業成長加速化補助金 (100億企業育成枠)",
        source_url="https://www.smrj.go.jp/sme/consulting/growth-100-oku/",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "売上 100 億円の壁突破を目指す中小企業の大規模成長投資を支援。"
            "SMRJ ハンズオン伴走と連動。"
        ),
        max_man_yen=50000.0,
        funding_purpose=("成長投資", "規模拡大", "設備投資"),
    ),
    SmrjSeed(
        slug="smrj-saikouchiku-handson",
        name="事業再構築ハンズオン支援事業",
        source_url="https://www.smrj.go.jp/sme/consulting/jigyo_saikoutiku_hands-on/",
        program_kind="consulting",
        tier_hint="B",
        description=(
            "事業再構築補助金採択者等を対象とする SMRJ 専門家派遣ハンズオン支援。"
            "再構築計画の実行段階を伴走。"
        ),
        funding_purpose=("経営支援", "事業再構築"),
    ),
    SmrjSeed(
        slug="smrj-shoukei-ma-hojokin",
        name="事業承継・M&A補助金",
        source_url="https://shoukei-mahojokin.go.jp/",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "事業承継・M&A を契機とする新たな取組や M&A 専門家活用を支援。"
            "事業承継促進枠・専門家活用枠・PMI 推進枠・廃業再チャレンジ枠あり。"
        ),
        max_man_yen=2000.0,
        funding_purpose=("事業承継", "M&A", "PMI"),
        aliases=("事業承継・引継ぎ補助金",),
    ),
    # ------------------ 1-B SMRJ 自主制度 ------------------
    SmrjSeed(
        slug="smrj-kodoka-prefecture-loan",
        name="高度化事業 (都道府県経由の長期低利融資)",
        source_url="https://www.smrj.go.jp/sme/funding/equipment_loan/index.html",
        program_kind="loan",
        tier_hint="A",
        description=(
            "中小企業の組合等が経営基盤強化のために行う共同施設・集団化・"
            "団地化・連鎖化等の事業に対し、SMRJ と都道府県が共同で長期低利"
            "(R8: 1.35%)・貸付割合 80% の融資を行う制度。"
        ),
        funding_purpose=("組合・連携事業", "集団化", "共同施設"),
    ),
    SmrjSeed(
        slug="smrj-kodoka-municipality-loan",
        name="高度化事業 (市町村経由の長期低利融資)",
        source_url="https://www.smrj.go.jp/sme/funding/municipalities_loan/index.html",
        program_kind="loan",
        tier_hint="B",
        description=(
            "中心市街地活性化・商業活性化等を目的とした事業に対し、SMRJ と市町村が"
            "共同で長期低利の融資を行う制度。市町村事業計画に基づく。"
        ),
        funding_purpose=("中心市街地活性化", "商業活性化"),
    ),
    SmrjSeed(
        slug="smrj-regional-fund-startup",
        name="地域中小企業応援ファンド (スタート・アップ応援型) ハブ",
        source_url="https://www.smrj.go.jp/sme/funding/regional_fund/index.html",
        program_kind="incentive",
        tier_hint="B",
        description=(
            "都道府県の中核的な支援機関と連携し、SMRJ の長期借入により基金を造成。"
            "運用益で地域中小企業の創業期・販路開拓を助成。23 都道府県設置。"
        ),
        funding_purpose=("創業", "販路開拓"),
    ),
    SmrjSeed(
        slug="smrj-fund-equity-investment",
        name="ファンド出資事業 (起業支援/中小企業成長支援/再生/事業承継/地域系)",
        source_url="https://www.smrj.go.jp/supporter/fund_investment/index.html",
        program_kind="fund_equity_investment",
        tier_hint="B",
        description=(
            "SMRJ が GP に LP 出資する形で投資ファンドの組成を促進。"
            "起業支援・中小企業成長支援・中小企業再生・事業承継・地域経済活性化等"
            "の各タイプを設置。"
        ),
        funding_purpose=("出資", "ファンド組成", "成長支援"),
    ),
    SmrjSeed(
        slug="smrj-saimu-hosho",
        name="債務保証事業 (認定革新的技術研究成果活用事業者)",
        source_url="https://www.smrj.go.jp/supporter/fund_investment/index.html",
        program_kind="credit_guarantee",
        tier_hint="C",
        description=(
            "認定された革新的技術の事業化に取り組む事業者が金融機関から借入を行う際、"
            "SMRJ が債務保証契約を締結することで信用補完。DAIZ 等実績。"
        ),
        funding_purpose=("研究開発", "事業化", "信用補完"),
    ),
    SmrjSeed(
        slug="smrj-risaisha-rishi-hokyu",
        name="利子補給事業 (事業継続力強化計画認定事業者向け)",
        source_url="https://www.smrj.go.jp/sme/risk_disaster/interest_supply/",
        program_kind="financial_support_interest_subsidy",
        tier_hint="B",
        description=(
            "事業継続力強化計画 (連携型を含む) の認定を受けた事業者が日本政策金融公庫から"
            "防災・減災投資のために借入を行う場合に、SMRJ が利子の一部を補給する制度。"
        ),
        funding_purpose=("BCP", "防災投資", "事業継続力強化"),
    ),
    # ------------------ 1-C Go-Tech / 研究開発系 ------------------
    SmrjSeed(
        slug="smrj-go-tech",
        name="Go-Tech 事業 (成長型中小企業等研究開発支援事業, 旧サポイン)",
        source_url="https://www.smrj.go.jp/sme/consulting/supporting_industry/index.html",
        program_kind="rd_grant",
        tier_hint="A",
        description=(
            "中小企業のものづくり基盤技術の高度化に資する研究開発を支援。"
            "中小機構は計画策定〜事業化までの伴走支援を提供。SBIR 特定新技術補助金。"
        ),
        max_man_yen=9750.0,
        funding_purpose=("研究開発", "事業化", "ものづくり基盤技術"),
        aliases=("サポイン",),
    ),
    SmrjSeed(
        slug="smrj-automobile-supplier",
        name="自動車部品サプライヤー事業転換支援事業",
        source_url="https://www.smrj.go.jp/sme/consulting/automobile_parts_supplier/",
        program_kind="consulting_support",
        tier_hint="B",
        description=(
            "EV シフトに伴う自動車部品サプライヤーの事業転換を、SMRJ 専門家伴走と"
            "セミナー・診断で支援する事業。"
        ),
        funding_purpose=("事業転換", "EV対応", "ものづくり"),
    ),
    SmrjSeed(
        slug="smrj-handson-general",
        name="ハンズオン支援 (専門家派遣)",
        source_url="https://www.smrj.go.jp/sme/consulting/hands-on/",
        program_kind="consulting_expert_dispatch",
        tier_hint="B",
        description=(
            "経営課題に応じて SMRJ 登録の中小企業診断士・税理士・技術士等の専門家を"
            "派遣する伴走支援。最大 30 回程度。"
        ),
        funding_purpose=("経営支援", "専門家派遣"),
    ),
    SmrjSeed(
        slug="smrj-advisor-kodoka",
        name="中小企業アドバイザー (高度化事業支援) 派遣事業",
        source_url="https://www.smrj.go.jp/sme/funding/equipment_loan/advisor/",
        program_kind="advisory_dispatch",
        tier_hint="C",
        description=(
            "高度化事業を活用する組合・組合員等に対し、SMRJ 登録アドバイザーを派遣して"
            "計画策定から実行までを伴走支援する制度。"
        ),
        funding_purpose=("組合支援", "計画策定"),
    ),
    SmrjSeed(
        slug="smrj-advisor-urban",
        name="中小企業アドバイザー (中心市街地活性化) 派遣事業",
        source_url="https://www.smrj.go.jp/supporter/urban_vitalization/",
        program_kind="advisory_dispatch",
        tier_hint="C",
        description=(
            "中心市街地活性化協議会等に対し SMRJ 登録の専門家を派遣し、"
            "まちづくり計画策定・タウンマネジメント等を支援。"
        ),
        funding_purpose=("中心市街地活性化", "まちづくり"),
    ),
    # ------------------ 1-D 海外展開 ------------------
    SmrjSeed(
        slug="smrj-overseas-handson",
        name="海外展開ハンズオン支援",
        source_url="https://www.smrj.go.jp/sme/overseas/consulting/advice/",
        program_kind="consulting_support",
        tier_hint="B",
        description=(
            "海外展開を計画する中小企業に対し、海外ビジネスの専門家を派遣し、"
            "輸出・進出・販路開拓に伴走する成長枠/飛躍的成長枠の支援事業。"
        ),
        funding_purpose=("海外展開", "輸出", "販路開拓"),
    ),
    SmrjSeed(
        slug="smrj-overseas-ceo",
        name="海外 CEO 商談会",
        source_url="https://www.smrj.go.jp/sme/overseas/ceo/",
        program_kind="matching_support",
        tier_hint="C",
        description=(
            "海外大手企業の CEO・購買責任者を招聘または訪問し、中小企業との"
            "ビジネスマッチングを行う SMRJ 主催の国際商談会。"
        ),
        funding_purpose=("海外展開", "商談", "マッチング"),
    ),
    SmrjSeed(
        slug="smrj-jgoodtech",
        name="J-GoodTech (ジェグテック)",
        source_url="https://www.smrj.go.jp/sme/overseas/jgoodtech/index.html",
        program_kind="matching_support",
        tier_hint="B",
        description=(
            "中小企業と国内外バイヤー・大手企業をつなぐ SMRJ 運営の B2B"
            "マッチングプラットフォーム。約 24,000 社登録。"
        ),
        funding_purpose=("販路開拓", "マッチング", "海外展開"),
    ),
    SmrjSeed(
        slug="smrj-overseas-test-marketing",
        name="海外展開テストマーケティング支援 (市場開拓トライアル/虎ノ門オンライン)",
        source_url="https://www.smrj.go.jp/sme/overseas/new_business/index.html",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "海外バイヤーへの試行販売・現役バイヤーとのオンライン相談・チカパー"
            "(東南アジア中小企業マッチング) 等を SMRJ がパッケージ提供。"
        ),
        funding_purpose=("海外展開", "テストマーケティング"),
    ),
    SmrjSeed(
        slug="smrj-fukko-ouen-fair-noto",
        name="復興応援フェア (能登半島地震被災事業者向け)",
        source_url="https://www.smrj.go.jp/sme/overseas/new_business/favgos000001r9pa.html",
        program_kind="matching_support",
        tier_hint="C",
        description=(
            "能登半島地震で被災した北陸地域の事業者の販路回復のため、"
            "SMRJ が主催する物産展・商談会の総称。"
        ),
        funding_purpose=("販路回復", "災害復興"),
    ),
    # ------------------ 1-E 人材育成 ------------------
    SmrjSeed(
        slug="smrj-institute",
        name="中小企業大学校 研修 (全国 9 校 + WEBeeCampus)",
        source_url="https://www.smrj.go.jp/institute/index.html",
        program_kind="training",
        tier_hint="A",
        description=(
            "中小企業の経営者・幹部・従業員向けに SMRJ が運営する全寮制研修機関。"
            "全国 9 校 + オンライン (WEBeeCampus)。年間約 1,000 コース・2 万人受講。"
        ),
        funding_purpose=("人材育成", "経営研修"),
    ),
    SmrjSeed(
        slug="smrj-institute-shindanshi",
        name="中小企業診断士養成課程 (中小企業大学校東京校・関西校)",
        source_url="https://www.smrj.go.jp/institute/index.html",
        program_kind="training",
        tier_hint="B",
        description=(
            "中小企業診断士登録の要件を満たす SMRJ 中小企業大学校の養成課程。"
            "東京校・関西校等で開講。約 6 ヶ月の集中課程。"
        ),
        funding_purpose=("人材育成", "資格取得"),
        aliases=("中小企業診断士養成課程",),
    ),
    SmrjSeed(
        slug="smrj-jinzai-online",
        name="人材育成オンライン相談窓口",
        source_url="https://www.smrj.go.jp/sme/human_resources/guide/index.html",
        program_kind="consulting_hotline",
        tier_hint="C",
        description=(
            "中小企業大学校・SMRJ 全国の研修担当者がオンラインで対応する"
            "人材育成・教育研修に関する無料相談窓口。"
        ),
        funding_purpose=("人材育成", "経営相談"),
    ),
    # ------------------ 1-F BCP / 災害 ------------------
    SmrjSeed(
        slug="smrj-jigyokei",
        name="事業継続力強化計画 (ジギョケイ) 単独型/連携型 認定支援",
        source_url="https://www.smrj.go.jp/sme/risk_disaster/enhancement/",
        program_kind="authorization_support",
        tier_hint="A",
        description=(
            "中小企業の防災・減災への取組を促進するため、SMRJ がセミナー・"
            "計画策定支援・フォローアップを提供する認定取得伴走支援事業。"
        ),
        funding_purpose=("BCP", "事業継続力強化", "認定取得"),
    ),
    # ------------------ 1-G 事業承継 / 再生 ------------------
    SmrjSeed(
        slug="smrj-revitalization-council",
        name="中小企業活性化協議会 (再生支援)",
        source_url="https://www.smrj.go.jp/sme/succession/revitalization/index.html",
        program_kind="consulting_support",
        tier_hint="A",
        description=(
            "経営困難に陥った中小企業を対象に、各都道府県に設置された活性化協議会で"
            "再生計画策定支援・金融機関調整等を無料で行う制度。"
        ),
        funding_purpose=("事業再生", "経営改善"),
    ),
    SmrjSeed(
        slug="smrj-improvement-plans",
        name="認定経営革新等支援機関による経営改善計画策定支援",
        source_url="https://www.smrj.go.jp/sme/succession/improvement-plans.html",
        program_kind="consulting_support",
        tier_hint="B",
        description=(
            "金融支援を伴う経営改善計画の策定を、認定経営革新等支援機関と連携して"
            "実施する場合に費用の一部を補助する制度。早期経営改善計画策定支援も。"
        ),
        funding_purpose=("経営改善", "事業再生"),
    ),
    SmrjSeed(
        slug="smrj-shoukei-center",
        name="事業承継・引継ぎ支援センター (国設置・全国 48 か所)",
        source_url="https://shoukei.smrj.go.jp/",
        program_kind="consulting_support",
        tier_hint="A",
        description=(
            "都道府県単位で SMRJ が設置・運営する公的機関。後継者不在の中小企業の"
            "M&A・親族内承継・個人事業主承継・後継者人材バンク等を無料支援。"
        ),
        funding_purpose=("事業承継", "M&A"),
    ),
    # ------------------ 1-H 中心市街地 / 商店街 ------------------
    SmrjSeed(
        slug="smrj-machizukuri-online",
        name="中心市街地・商店街等診断・サポート事業 (まちづくりオンライン相談他)",
        source_url="https://www.smrj.go.jp/supporter/urban_vitalization/",
        program_kind="consulting_support",
        tier_hint="B",
        description=(
            "中心市街地活性化協議会・商店街振興組合等を対象に、SMRJ が"
            "オンライン相談・巡回型・パッケージ型診断を原則無料で提供。"
        ),
        funding_purpose=("中心市街地活性化", "商店街支援"),
    ),
    SmrjSeed(
        slug="smrj-machizukuri-center",
        name="中心市街地活性化協議会支援センター運営",
        source_url="https://www.smrj.go.jp/supporter/urban_vitalization/",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "中心市街地活性化協議会の自走を促すため、SMRJ が情報提供・"
            "ノウハウ蓄積・人材ネットワーク提供を行う支援センター事業。"
        ),
        funding_purpose=("中心市街地活性化",),
    ),
    SmrjSeed(
        slug="smrj-yorozu-honbu",
        name="よろず支援拠点 全国本部 (運営)",
        source_url="https://www.smrj.go.jp/supporter/yorozu/",
        program_kind="consulting_support",
        tier_hint="A",
        description=(
            "全国 47 都道府県に設置された無料経営相談所「よろず支援拠点」の"
            "全国本部。SMRJ が中央事務局として運営支援。"
        ),
        funding_purpose=("経営相談", "販路開拓"),
    ),
    SmrjSeed(
        slug="smrj-shoukei-honbu",
        name="事業承継・引継ぎ支援全国本部 (運営)",
        source_url="https://shoukei.smrj.go.jp/",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "全国 48 か所の事業承継・引継ぎ支援センターの中央本部機能を担う"
            "SMRJ の組織。情報集約・専門家派遣・統計取りまとめ。"
        ),
        funding_purpose=("事業承継", "中央事務局"),
    ),
    # ------------------ 1-I 起業 / 創業 ------------------
    SmrjSeed(
        slug="smrj-incubation",
        name="インキュベーション施設 (TIP*S/BusiNest/京大桂/クリエイション・コア東大阪等)",
        source_url="https://www.smrj.go.jp/venture/bace/index.html",
        program_kind="startup_support_non_cash",
        tier_hint="B",
        description=(
            "SMRJ が直営または連携運営する起業支援拠点・インキュベーション施設。"
            "オフィス低料金提供・専門家マッチング・コミュニティイベント。"
        ),
        funding_purpose=("創業支援", "オフィス提供"),
    ),
    SmrjSeed(
        slug="smrj-creation-link-act",
        name="創業支援等事業計画連携支援 (産業競争力強化法)",
        source_url="https://www.smrj.go.jp/venture/supporter/index.html",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "産業競争力強化法に基づき市町村が策定する創業支援等事業計画について、"
            "SMRJ が認定支援機関として伴走・関係者ネットワーク構築を支援。"
        ),
        funding_purpose=("創業支援",),
    ),
    SmrjSeed(
        slug="smrj-third-party-inherited",
        name="第三者承継起業支援",
        source_url="https://www.smrj.go.jp/venture/third_party_inherited_support/",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "親族外の第三者に既存事業を引き継がせて起業するスキームを支援。"
            "後継者人材バンク・SMRJ 専門家マッチング等を組み合わせる。"
        ),
        funding_purpose=("事業承継", "第三者承継"),
    ),
    # ------------------ 1-J デジタル / DX ------------------
    SmrjSeed(
        slug="smrj-digwith",
        name="デジwith (中小機構 DX 支援窓口)",
        source_url="https://www.smrj.go.jp/sme/digital/index.html",
        program_kind="consulting_hotline",
        tier_hint="C",
        description=(
            "中小機構 DX 支援統合窓口。中小企業 DX 推進ガイドライン啓発・"
            "事例紹介・専門家派遣を一元提供。"
        ),
        funding_purpose=("DX", "デジタル化"),
    ),
    SmrjSeed(
        slug="smrj-it-keiei-support",
        name="IT 経営サポートセンター",
        source_url="https://www.smrj.go.jp/sme/digital/index.html",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "中小企業の IT 経営確立・DX 推進をサポートする SMRJ の支援部門。"
            "IT 専門家派遣・スマート化診断等を行う。"
        ),
        funding_purpose=("IT", "DX", "経営支援"),
    ),
    SmrjSeed(
        slug="smrj-smart-shindan",
        name="生産工程スマート化診断",
        source_url="https://www.smrj.go.jp/sme/digital/index.html",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "製造業中小企業を対象に、SMRJ 専門家が生産工程のデジタル化・"
            "スマート化の段階を診断し、改善提案を行う事業。"
        ),
        funding_purpose=("DX", "ものづくり", "生産性向上"),
    ),
    SmrjSeed(
        slug="smrj-it-shien-2026",
        name="デジタル化・AI導入補助金 (2026 年度新設, 旧 IT 導入補助金系統)",
        source_url="https://it-shien.smrj.go.jp/",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "中小企業のデジタル化・AI 活用を支援する 2026 年度新設補助金。"
            "通常枠・セキュリティ枠・電子取引枠等。SMRJ が事業実施機関。"
        ),
        max_man_yen=450.0,
        funding_purpose=("DX", "IT 導入", "AI 活用"),
    ),
    # ------------------ 1-K SDGs / CN ------------------
    SmrjSeed(
        slug="smrj-sdgs-soudan",
        name="SDGs に関する相談 (中小機構)",
        source_url="https://www.smrj.go.jp/sme/sdgs/index.html",
        program_kind="consulting_hotline",
        tier_hint="C",
        description=(
            "中小企業の SDGs 経営導入に関する SMRJ の無料相談窓口。"
            "セミナー・事例紹介・専門家マッチング。"
        ),
        funding_purpose=("SDGs", "経営相談"),
    ),
    SmrjSeed(
        slug="smrj-cn-soudan",
        name="カーボンニュートラルに関する支援 (中小機構)",
        source_url="https://www.smrj.go.jp/sme/sdgs/index.html",
        program_kind="consulting_support",
        tier_hint="C",
        description=(
            "中小企業の脱炭素経営移行を支援する SMRJ のセミナー・"
            "省エネ診断・専門家派遣等の総合プログラム。"
        ),
        funding_purpose=("カーボンニュートラル", "省エネ", "脱炭素"),
    ),
    # ------------------ 1-L 相談系 ------------------
    SmrjSeed(
        slug="smrj-keiei-tel-soudan",
        name="経営に関する相談 (中小機構 電話窓口)",
        source_url="https://www.smrj.go.jp/sme/consulting/index.html",
        program_kind="consulting_hotline",
        tier_hint="C",
        description=(
            "中小機構が運営する経営全般に関する無料電話相談窓口。"
            "創業・販路・資金繰り・承継・再生等を一次受付。"
        ),
        funding_purpose=("経営相談",),
    ),
    SmrjSeed(
        slug="smrj-e-sodan",
        name="経営相談チャットサービス E-SODAN",
        source_url="https://www.smrj.go.jp/sme/consulting/index.html",
        program_kind="consulting_hotline",
        tier_hint="C",
        description=(
            "AI チャットボット + 平日 9-17 時専門家対応のオンライン経営相談。"
            "中小機構運営、無料・匿名利用可。"
        ),
        funding_purpose=("経営相談", "AI", "チャット"),
        aliases=("E-SODAN",),
    ),
    SmrjSeed(
        slug="smrj-noushokoku-renkei",
        name="農商工等連携の支援 (認定申請支援)",
        source_url="https://www.smrj.go.jp/sme/consulting/agri_commerce/index.html",
        program_kind="authorization_support",
        tier_hint="B",
        description=(
            "中小企業者と農林漁業者の連携による新商品・新サービス開発の認定申請を"
            "支援。認定取得で日本政策金融公庫等の低利融資・補助金加点が適用。"
        ),
        funding_purpose=("農商工連携", "認定取得", "新商品開発"),
    ),
    # ------------------ 共済 ------------------
    SmrjSeed(
        slug="smrj-skyosai-detail",
        name="小規模企業共済制度 (経営者退職金積立)",
        source_url="https://www.smrj.go.jp/kyosai/skyosai/index.html",
        program_kind="mutual_aid",
        tier_hint="A",
        description=(
            "小規模企業の個人事業主・会社等役員のための退職金積立制度。"
            "掛金は全額所得控除、契約者貸付制度あり。SMRJ が運営。"
        ),
        funding_purpose=("退職金積立", "所得控除", "事業主備え"),
    ),
    SmrjSeed(
        slug="smrj-tkyosai-detail",
        name="経営セーフティ共済 (中小企業倒産防止共済)",
        source_url="https://www.smrj.go.jp/kyosai/tkyosai/index.html",
        program_kind="insurance",
        tier_hint="A",
        description=(
            "取引先倒産による連鎖倒産・経営難を防ぐ共済制度。掛金月額 5,000 円〜"
            "20 万円、無担保・無保証で掛金総額の 10 倍まで貸付。"
        ),
        funding_purpose=("倒産防止", "貸付", "リスク管理"),
    ),
    # ------------------ J-Net21 / 起業ガイド ------------------
    SmrjSeed(
        slug="smrj-jnet21",
        name="J-Net21 (中小企業ビジネス支援サイト)",
        source_url="https://j-net21.smrj.go.jp/",
        program_kind="information_service",
        tier_hint="A",
        description=(
            "中小機構が運営する中小企業向け総合ポータル。補助金・支援制度・"
            "起業ガイド・経営課題別ナビを集約。"
        ),
        funding_purpose=("情報提供", "支援制度ナビ"),
    ),
    SmrjSeed(
        slug="smrj-venture-info",
        name="起業ガイド (Venture/info)",
        source_url="https://www.smrj.go.jp/venture/info/index.html",
        program_kind="information_service",
        tier_hint="C",
        description=(
            "起業を志す者向けに、ステージ別の必要手続き・資金調達・拠点・支援機関を"
            "解説する SMRJ の起業ガイドコンテンツ。"
        ),
        funding_purpose=("創業支援", "情報提供"),
    ),
    SmrjSeed(
        slug="smrj-venture-supporter",
        name="ベンチャー支援機関ネットワーク (Venture/supporter)",
        source_url="https://www.smrj.go.jp/venture/supporter/index.html",
        program_kind="network_support",
        tier_hint="C",
        description=(
            "創業・スタートアップ支援を行う各種支援機関 (VC・自治体・大学等) を"
            "横断検索できる SMRJ のディレクトリ。"
        ),
        funding_purpose=("ネットワーキング", "創業支援"),
    ),
    SmrjSeed(
        slug="smrj-supporter-startup",
        name="スタートアップ支援機関連携 (supporter/startup)",
        source_url="https://www.smrj.go.jp/supporter/startup/index.html",
        program_kind="network_support",
        tier_hint="C",
        description=(
            "スタートアップ・エコシステム拠点都市等と連携する SMRJ の"
            "支援機関向けポータル。J-Startup・大学発ベンチャー支援等。"
        ),
        funding_purpose=("スタートアップ", "拠点連携"),
    ),
    SmrjSeed(
        slug="smrj-supporter-succession",
        name="事業承継支援機関連携 (supporter/succession)",
        source_url="https://www.smrj.go.jp/supporter/succession/index.html",
        program_kind="network_support",
        tier_hint="C",
        description=(
            "事業承継支援を行う商工団体・金融機関・専門家等の支援機関向けに"
            "SMRJ が提供するポータル。"
        ),
        funding_purpose=("事業承継", "ネットワーク"),
    ),
)


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch(url: str, *, retries: int = 2) -> tuple[int, str]:
    """Fetch URL with retry. Returns (status, decoded_text). 0 status => failure."""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_SSL_CTX) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(charset, errors="replace")
                except LookupError:
                    text = raw.decode("utf-8", errors="replace")
                return resp.status, text
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in (404, 410):
                return exc.code, ""
            time.sleep(2.0 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2.0 * (attempt + 1))
    print(f"  [WARN] fetch failed: {url}: {last_err}", file=sys.stderr)
    return 0, ""


def parse_meta(html: str) -> tuple[str | None, str | None]:
    """Return (title, description) extracted from <title> / og:title / meta description."""
    soup = BeautifulSoup(html, "html.parser")
    title = None
    if soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string.strip())
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = re.sub(r"\s+", " ", str(og["content"]).strip())
    desc = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        desc = re.sub(r"\s+", " ", str(md["content"]).strip())
    if not desc:
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            desc = re.sub(r"\s+", " ", str(og["content"]).strip())
    return title, desc


# ---------------------------------------------------------------------------
# Build row
# ---------------------------------------------------------------------------

def make_unified_id(slug: str) -> str:
    """Stable hash-based UNI- id (10 hex chars), namespaced under smrj."""
    h = hashlib.sha1(f"smrj:{slug}".encode("utf-8")).hexdigest()[:10]
    return f"UNI-{h}"


def authority_for_url(url: str) -> tuple[str, str]:
    """Return (authority_level, authority_name) for a SMRJ-family URL."""
    return ("national", "中小企業基盤整備機構 (SMRJ)")


def build_row(seed: SmrjSeed, fetched_at: str, http_status: int, fetched_meta: tuple[str | None, str | None]) -> dict[str, object]:
    auth_level, auth_name = authority_for_url(seed.source_url)
    enriched = {
        "_meta": {
            "program_id": make_unified_id(seed.slug),
            "program_name": seed.name,
            "source_format": "html",
            "source_urls": [seed.source_url],
            "fetched_at": fetched_at,
            "model": "smrj-seed-curated-v1",
            "worker_id": "ingest_smrj_programs",
            "fetch_method": "urllib",
            "primary_source_confirmed": http_status == 200,
            "http_status": http_status,
            "fetched_title": fetched_meta[0],
            "fetched_meta_description": fetched_meta[1],
        },
        "extraction": {
            "basic": {
                "正式名称": seed.name,
                "_source_ref": {"url": seed.source_url, "excerpt": fetched_meta[0] or ""},
            },
            "money": {
                "amount_max_man_yen": seed.max_man_yen,
                "subsidy_rate": None,
                "_source_ref": {"url": seed.source_url, "excerpt": ""},
            },
            "schedule": {
                "start_date": seed.application_start,
                "end_date": seed.application_end,
                "fiscal_year": None,
                "_source_ref": {"url": seed.source_url, "excerpt": ""},
            },
        },
        "license_attribution": "© 独立行政法人中小企業基盤整備機構 (SMRJ). PDL v1.0 互換 (政府関係機関一次資料).",
    }

    application_window = None
    if seed.application_start or seed.application_end:
        application_window = json.dumps(
            {"start_date": seed.application_start, "end_date": seed.application_end},
            ensure_ascii=False,
        )

    aliases = list(seed.aliases) if seed.aliases else []

    return {
        "unified_id": make_unified_id(seed.slug),
        "primary_name": seed.name,
        "aliases_json": json.dumps(aliases, ensure_ascii=False) if aliases else None,
        "authority_level": auth_level,
        "authority_name": auth_name,
        "prefecture": None,
        "municipality": None,
        "program_kind": seed.program_kind,
        "official_url": seed.source_url,
        "amount_max_man_yen": seed.max_man_yen,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": "1",
        "tier": seed.tier_hint,
        "coverage_score": None,
        "gap_to_tier_s_json": None,
        "a_to_j_coverage_json": None,
        "excluded": 0,
        "exclusion_reason": None,
        "crop_categories_json": None,
        "equipment_category": None,
        "target_types_json": json.dumps(list(seed.target_types), ensure_ascii=False)
        if seed.target_types
        else None,
        "funding_purpose_json": json.dumps(list(seed.funding_purpose), ensure_ascii=False)
        if seed.funding_purpose
        else None,
        "amount_band": None,
        "application_window_json": application_window,
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps({"smrj_seed": seed.slug}, ensure_ascii=False),
        "source_url": seed.source_url,
        "source_fetched_at": fetched_at,
        "source_checksum": hashlib.sha1(
            f"{seed.slug}|{seed.source_url}|{seed.name}|{seed.tier_hint}|{seed.max_man_yen}".encode("utf-8")
        ).hexdigest()[:16],
        "updated_at": fetched_at,
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO programs (
    unified_id, primary_name, aliases_json, authority_level, authority_name,
    prefecture, municipality, program_kind, official_url,
    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
    trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
    excluded, exclusion_reason,
    crop_categories_json, equipment_category,
    target_types_json, funding_purpose_json, amount_band, application_window_json,
    enriched_json, source_mentions_json,
    source_url, source_fetched_at, source_checksum, updated_at
) VALUES (
    :unified_id, :primary_name, :aliases_json, :authority_level, :authority_name,
    :prefecture, :municipality, :program_kind, :official_url,
    :amount_max_man_yen, :amount_min_man_yen, :subsidy_rate,
    :trust_level, :tier, :coverage_score, :gap_to_tier_s_json, :a_to_j_coverage_json,
    :excluded, :exclusion_reason,
    :crop_categories_json, :equipment_category,
    :target_types_json, :funding_purpose_json, :amount_band, :application_window_json,
    :enriched_json, :source_mentions_json,
    :source_url, :source_fetched_at, :source_checksum, :updated_at
)
ON CONFLICT(unified_id) DO UPDATE SET
    primary_name = excluded.primary_name,
    aliases_json = COALESCE(excluded.aliases_json, programs.aliases_json),
    authority_level = COALESCE(excluded.authority_level, programs.authority_level),
    authority_name = COALESCE(excluded.authority_name, programs.authority_name),
    program_kind = COALESCE(excluded.program_kind, programs.program_kind),
    official_url = COALESCE(excluded.official_url, programs.official_url),
    amount_max_man_yen = COALESCE(excluded.amount_max_man_yen, programs.amount_max_man_yen),
    target_types_json = COALESCE(excluded.target_types_json, programs.target_types_json),
    funding_purpose_json = COALESCE(excluded.funding_purpose_json, programs.funding_purpose_json),
    application_window_json = COALESCE(
        excluded.application_window_json, programs.application_window_json
    ),
    enriched_json = excluded.enriched_json,
    source_mentions_json = COALESCE(
        excluded.source_mentions_json, programs.source_mentions_json
    ),
    source_url = excluded.source_url,
    source_fetched_at = excluded.source_fetched_at,
    source_checksum = excluded.source_checksum,
    tier = CASE
        WHEN programs.tier IS NULL OR programs.tier IN ('X','C') THEN excluded.tier
        ELSE programs.tier
    END,
    trust_level = COALESCE(excluded.trust_level, programs.trust_level),
    excluded = COALESCE(programs.excluded, 0),
    updated_at = excluded.updated_at
WHERE programs.excluded = 0
"""


FTS_INSERT_SQL = (
    "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
    "VALUES (?,?,?,?)"
)


def upsert(conn: sqlite3.Connection, row: dict[str, object]) -> str:
    prev = conn.execute(
        "SELECT excluded FROM programs WHERE unified_id = ?", (row["unified_id"],)
    ).fetchone()
    if prev is None:
        action = "insert"
    else:
        if prev[0]:
            return "skip"
        action = "update"
    conn.execute(UPSERT_SQL, row)
    if action == "insert":
        conn.execute(
            FTS_INSERT_SQL,
            (
                row["unified_id"],
                row["primary_name"],
                row["aliases_json"] or "",
                f"{row['primary_name']}",
            ),
        )
    return action


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print(f"jpintel.db: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"[ERROR] DB not found: {DB_PATH}", file=sys.stderr)
        return 2

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    fetched: dict[str, tuple[int, tuple[str | None, str | None]]] = {}

    # Cache fetches per URL (multiple seeds may share a URL).
    unique_urls = sorted({s.source_url for s in SEEDS})
    print(f"Probing {len(unique_urls)} unique SMRJ URLs at 1 req/s ...")
    for i, url in enumerate(unique_urls, 1):
        status, html = fetch(url)
        if status == 200 and html:
            meta = parse_meta(html)
        else:
            meta = (None, None)
        fetched[url] = (status, meta)
        ok = "OK" if status == 200 else f"HTTP {status}"
        print(f"  [{i:02d}/{len(unique_urls)}] {ok}  {url}")
        time.sleep(RATE_DELAY)

    for seed in SEEDS:
        status, meta = fetched.get(seed.source_url, (0, (None, None)))
        rows.append(build_row(seed, fetched_at, status, meta))

    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=300.0)
    try:
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute("BEGIN IMMEDIATE")
        ins = upd = skip = 0
        for r in rows:
            try:
                action = upsert(conn, r)
            except sqlite3.IntegrityError as exc:
                print(f"  [WARN] integrity: {r['unified_id']} {exc}", file=sys.stderr)
                skip += 1
                continue
            if action == "insert":
                ins += 1
            elif action == "update":
                upd += 1
            else:
                skip += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    print(f"\nDone: insert={ins} update={upd} skip={skip} (seeds={len(SEEDS)})")

    # Verification.
    conn = sqlite3.connect(str(DB_PATH))
    try:
        c = conn.execute(
            "SELECT COUNT(*) FROM programs WHERE source_url LIKE '%smrj.go.jp%'"
        ).fetchone()[0]
        print(f"Total programs with smrj.go.jp source_url: {c}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
