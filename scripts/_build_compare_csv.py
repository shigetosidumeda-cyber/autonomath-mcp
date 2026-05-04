#!/usr/bin/env python3
"""Build docs/compare_matrix.csv from a structured Python source.

The CSV is the source of truth for /compare/{slug}/ pages. Cells contain
commas (e.g. "166,969 件") and embedded prose, so we generate via csv.writer
which handles quoting correctly. Do not edit the CSV by hand — edit this
script and re-run it.
"""

from __future__ import annotations

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "docs" / "compare_matrix.csv"

ROWS: list[dict[str, str]] = []


def add(slug: str, comp_ja: str, comp_en: str, comp_url: str, axis: str, us: str, them: str, note: str = "") -> None:
    ROWS.append(
        {
            "slug": slug,
            "competitor_ja": comp_ja,
            "competitor_en": comp_en,
            "competitor_url": comp_url,
            "axis": axis,
            "us": us,
            "competitor": them,
            "note": note,
        }
    )


# ----------------------------------------------------------------------------
# tdb (帝国データバンク)
# ----------------------------------------------------------------------------
SLUG = "tdb"
NAME_JA = "帝国データバンク"
NAME_EN = "Teikoku Databank"
URL = "https://www.tdb.co.jp/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP (OpenAPI 3.1, MCP protocol 2025-06-18) で全機能を提供。/v1/* 公開、認証なしでも 3 req/日/IP。",
    "API は法人向け契約で別途提供 (公開価格なし) — 2026-04 月時点で公開ページに API/MCP 仕様の記載なし。",
    "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "MCP サーバー (autonomath-mcp PyPI 互換) + 手動設定 / DXT bundle。96 tools。",
    "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "完全従量 ¥3/req 税別 (税込 ¥3.30)、最低料金/契約期間/Seat 課金なし。匿名 3 req/日/IP 無料。",
    "COSMOS / 企業ファイル等は個別見積。一般的に年間契約 + 1 件閲覧課金で、公開価格表は無し (代理店経由)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件 (gBizINFO ベースの corporate_entity)。+13,801 件の適格請求書発行事業者 (delta、PDL v1.0)。",
    "「約 147 万社」(同社サイト 2026-04 時点) — 当社より大幅に広範。",
    "大企業/上場企業の網羅性では同社が圧倒。")
add(SLUG, NAME_JA, NAME_EN, URL, "Credit ratings / 評点",
    "<strong>なし</strong> (取扱対象外)。",
    "コア商品。「帝国データバンク評点」は同社の代表的なスコアリングサービス。",
    "信用調査用途では同社が第一選択。")
add(SLUG, NAME_JA, NAME_EN, URL, "Executive bio / 経営者情報",
    "<strong>なし</strong>。",
    "コア商品 (代表者経歴・親族関係等)。",
    "人物 DD 用途では同社が第一選択。")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件 検索可。主要な公開行に primary source URL + fetched_at。",
    "<strong>対象外</strong>。同社は信用調査専業で公的制度 DB は提供せず。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件 (am_tax_rule)。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件 (court_decisions)。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。更新状況は data freshness を参照。",
    "対象外 (信用調査の付随情報として扱う場合あり、API 単独提供は公開情報なし)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。出典方針は transparency と sources に掲載。",
    "信用調査レポートは独自取材ベース (一次資料明記は商品仕様による)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "プログラム配布: AGPL 相当のソース公開条項なし。データ再配布は出典表示で OK (e-Gov=CC-BY-4.0 / NTA=PDL v1.0 / proprietary 行は不可)。",
    "個別契約 (商用利用は再配布禁止条項あり、要確認)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP (登録不要)。",
    "なし (デモ閲覧は営業経由)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ (ToS 同意で開始)。",
    "個別契約 (年単位が一般的、公開情報なし)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service (ドキュメント + メール info@bookyou.net、48h 以内応答)。",
    "Account manager 制 (直接担当者、訪問可)。", "")


# ----------------------------------------------------------------------------
# tsr (東京商工リサーチ)
# ----------------------------------------------------------------------------
SLUG = "tsr"
NAME_JA = "東京商工リサーチ"
NAME_EN = "Tokyo Shoko Research"
URL = "https://www.tsr-net.co.jp/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP (OpenAPI 3.1)。匿名 3 req/日/IP 無料。",
    "tsr-van2 等の法人向け情報サービスを提供 — Web/専用回線。API/MCP の公開仕様は公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "MCP サーバー、96 tools。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量 (税込 ¥3.30)。",
    "個別見積 (代理店経由が中心、公開価格表は無し)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件。",
    "「約 100 万社以上」(同社公式 2026-04 時点) — 当社より広範。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Credit ratings / 評点",
    "<strong>なし</strong> (取扱対象外)。",
    "コア商品 (TSR 評点)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Executive bio / 経営者情報",
    "<strong>なし</strong>。", "コア商品。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件。", "対象外 (信用調査専業)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。", "独自取材ベース。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始 (再配布は出典表示制約に従う)。",
    "個別契約 (再配布禁止条項あり、要確認)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。",
    "公開情報なし (デモは営業経由)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。",
    "個別契約 (年単位が一般的、公開情報なし)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール (info@bookyou.net 48h)。",
    "Account manager 制。", "")


# ----------------------------------------------------------------------------
# gbizinfo
# ----------------------------------------------------------------------------
SLUG = "gbizinfo"
NAME_JA = "gBizINFO"
NAME_EN = "gBizINFO"
URL = "https://info.gbiz.go.jp/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP。OpenAPI 3.1。",
    "<strong>REST API あり</strong> (申請ベース、無料、利用規約あり) — 当社も内部で取込。当社の独自性は MCP / 制度 DB / 一次資料連結で、法人台帳機能は概ね同等。",
    "gBizINFO は METI 公式の良質な公開 API。当社の corporate_entity の主要源。")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools (protocol 2025-06-18)。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量 (税込 ¥3.30)。",
    "<strong>完全無料</strong> (政府公式)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件 (うち gBizINFO ベース約 87,076 + 適格請求書 delta 13,801)。",
    "500 万社超 (法人番号公表サイト連携、ほぼ全法人)。",
    "法人台帳の網羅性では gBizINFO が圧倒。")
add(SLUG, NAME_JA, NAME_EN, URL, "Credit ratings / 評点",
    "なし。", "なし (政府機関のため評点は提供せず)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件 (tier S/A/B/C)。",
    "補助金情報の連携あり (採択企業情報) — ただし制度横断の検索 API は無し。",
    "当社は制度を主、法人を従とする逆構造。")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。",
    "対象外 (国税庁公表サイトと連携可能だが gBizINFO 内部 DB は別)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "出典は政府機関 (一次)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。データは出典表示で再配布可 (license フィールド参照)。",
    "「政府標準利用規約 2.0」(原則 CC-BY 相当、出典表示で再配布可)。",
    "gBizINFO データを当社が取込・再配布できるのはこの規約のため。")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。", "完全無料。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。", "なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール。", "公的サービス窓口 (METI)。", "")


# ----------------------------------------------------------------------------
# jgrants
# ----------------------------------------------------------------------------
SLUG = "jgrants"
NAME_JA = "jGrants公式"
NAME_EN = "jGrants"
URL = "https://www.jgrants-portal.go.jp/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP。11,684 制度を横断検索。",
    "検索 UI のみ。<strong>API 公開なし</strong> (2026-04 時点公開情報)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量。", "<strong>完全無料</strong> (政府公式)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件。", "対象外 (制度ポータル、法人台帳は持たない)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件 (補助金 + 融資 + 税制 + 認定 横断)。",
    "補助金中心。電子申請対応。掲載数の公開情報なし。",
    "jGrants は「申請」、当社は「検索 + 適合判定」で住み分け。")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "出典は政府機関 (一次)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Electronic application / 電子申請",
    "<strong>なし</strong> (検索・適合判定が主機能、申請は jGrants 経由を推奨)。",
    "<strong>あり</strong> (gBizID 連携で電子申請) — コア機能。",
    "jGrants の主機能。当社は補完。")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。出典表示で再配布可 (e-Gov 等)。",
    "政府標準利用規約 2.0 系。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。", "完全無料。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。", "なし (gBizID 登録要)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール。", "公的サービス窓口 (中小企業庁)。", "")


# ----------------------------------------------------------------------------
# mirasapo
# ----------------------------------------------------------------------------
SLUG = "mirasapo"
NAME_JA = "ミラサポplus"
NAME_EN = "Mirasapo plus"
URL = "https://mirasapo-plus.go.jp/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP。",
    "検索 UI のみ。<strong>API 公開なし</strong> (2026-04 時点公開情報)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量。", "<strong>完全無料</strong> (政府公式)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件。",
    "主要補助金 + 関連制度の解説中心。",
    "ミラサポ plus は「読み物 + 専門家紹介」、当社は「機械可読 API」で住み分け。")
add(SLUG, NAME_JA, NAME_EN, URL, "Case studies / 採択事例",
    "2,286 件 (industry / amount / 公募回 で絞込)。",
    "<strong>事例ナビあり</strong> (Web UI のみ、API なし)。",
    "UI 閲覧では同等以上、API 用途では当社のみ。")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "出典は政府機関 (一次)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Expert matching / 専門家紹介",
    "<strong>なし</strong> (検索 + 適合判定が主機能)。",
    "<strong>あり</strong> (中小企業診断士・士業マッチング)。",
    "人的支援は同社、機械可読は当社。")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。", "政府標準利用規約 2.0 系。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。", "完全無料。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。", "なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール。", "公的サービス窓口 (中小企業庁)。", "")


# ----------------------------------------------------------------------------
# moneyforward
# ----------------------------------------------------------------------------
SLUG = "moneyforward"
NAME_JA = "マネーフォワード ビジネスID"
NAME_EN = "Money Forward Business ID"
URL = "https://biz.moneyforward.com/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "制度・税務・判例 等の REST + MCP。",
    "会計・経費・人事 SaaS の API (顧客向け、公開仕様は限定的)。fintech aggregator として銀行 / カード / 決済の連携 API はあるが、制度 DB API は提供せず。",
    "スコープが異なる (fintech 連携 vs 制度 DB)。")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量。",
    "SaaS Seat 課金 (会計プラン月額数千円〜)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件 (corporate_entity)。",
    "対象外 (顧客自身の法人 1 件分)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件 (横断検索 API)。",
    "bizキャッシュ等で一部紹介。横断検索 API は提供せず。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Accounting / 会計データ",
    "<strong>なし</strong> (会計ソフトではない)。",
    "コア商品 (青色申告対応の会計 SaaS)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。",
    "会計ソフト内部の税率マスタは持つが、当社のような検索可能な税制 DB は提供せず。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。",
    "会計データの中で扱うが、登録番号 DB の API は無い。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "SaaS 内部のため対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。",
    "SaaS 利用規約 (Seat 単位)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。",
    "会計プランは有料 (一部無料機能あり)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。",
    "Seat 月次課金 (年契約割引あり)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール。",
    "SaaS サポート + 電話/チャット。", "")


# ----------------------------------------------------------------------------
# freee
# ----------------------------------------------------------------------------
SLUG = "freee"
NAME_JA = "freee 助成金AI"
NAME_EN = "freee Joseikin AI"
URL = "https://www.freee.co.jp/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP。",
    "公開情報なし (freee アカウント連携前提、外部 API は提供せず)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量。",
    "freee 顧客向けの追加機能 (公開価格情報非公表)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件。", "対象外 (顧客自身)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件。",
    "助成金中心 (公開情報による掲載数非公表)。",
    "「freee 顧客のみ」が制約。")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。",
    "会計ソフト内部の税率マスタ。検索 API は提供せず。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。",
    "会計データ内で扱うが API 単独提供は公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Customer scope / 顧客制約",
    "誰でも (匿名 3 req/日/IP)。",
    "freee 利用顧客のみ (アカウント連携が前提)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。", "freee 利用規約に従属。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。",
    "freee 顧客向けの付加機能 (公開価格情報非公表)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。",
    "freee SaaS 契約に従属。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール。",
    "freee サポート (チャット + 電話)。", "")


# ----------------------------------------------------------------------------
# navit
# ----------------------------------------------------------------------------
SLUG = "navit"
NAME_JA = "ナビット 補助金検索pro"
NAME_EN = "Navit hojokin search pro"
URL = "https://www.navit-j.com/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP。",
    "有料 SaaS の Web UI。<strong>API/MCP の公開仕様は公開情報なし</strong> (2026-04 時点)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量 (税込 ¥3.30)。",
    "Seat 課金 (公開価格情報なし、要問合せ)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件。",
    "「補助金 6,000 件以上」(同社サイト) — 当社より多い。",
    "網羅性で同社が上回る項目あり。当社の優位は API/MCP と一次資料連結。")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "公開情報なし (要確認)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。",
    "<strong>無料お試しあり</strong> (公開情報、期間/制限は要確認)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。", "SaaS 利用規約 (Seat 単位)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。",
    "Seat 月次/年次 (公開情報なし)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール。", "SaaS サポート + 電話。", "")


# ----------------------------------------------------------------------------
# nta-invoice
# ----------------------------------------------------------------------------
SLUG = "nta-invoice"
NAME_JA = "国税庁 適格請求書発行事業者公表サイト"
NAME_EN = "NTA Invoice Issuer Public Site"
URL = "https://www.invoice-kohyo.nta.go.jp/"

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "REST + MCP (制度 + 法人 + 適格請求書 + 法令 + 判例 横断)。",
    "<strong>Web API + bulk download</strong> (公式 Web-API、月次 bulk CSV)。当社も内部で取込。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools。", "公開情報なし。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量。",
    "<strong>完全無料</strong> (国税庁公式)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件 (corporate_entity)。+13,801 件の適格請求書発行事業者 (delta)。",
    "<strong>約 4 百万件</strong> (適格請求書発行事業者の登録番号公表 — 全件)。",
    "適格請求書発行事業者の網羅性では同サイトが圧倒。当社の収録範囲と更新状況は data freshness で確認できます。")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件。", "対象外 (国税庁は税務専業)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件。",
    "対象外 (登録番号公表のみ、税制ルールは別サイト)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件。", "対象外。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Cross-domain join",
    "<strong>あり</strong> (制度 × 法人 × 判例 × 行政処分 × 適格請求書 を 1 リクエストで横断)。",
    "対象外 (適格請求書のみ)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "出典は国税庁 (一次)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。NTA 由来データは PDL v1.0 で再配布可。",
    "<strong>PDL v1.0</strong> (Public Data License、出典明記で再配布 OK)。",
    "この自由度の高い再配布規約のおかげで当社の bulk 取込が成立。")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。",
    "完全無料 (登録番号 1 件ずつの Web 検索は無料、bulk DL も無料)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Sample contract length",
    "なし — 利用規約のみ。", "なし (公的サービス)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Support model",
    "Self-service + メール。", "公的サービス窓口 (国税庁)。", "")


# ----------------------------------------------------------------------------
# diy-scraping
# ----------------------------------------------------------------------------
SLUG = "diy-scraping"
NAME_JA = "自前スクレイピング"
NAME_EN = "DIY scraping"
URL = ""

add(SLUG, NAME_JA, NAME_EN, URL, "API access",
    "<strong>REST + MCP を統一インターフェースで提供</strong>。OpenAPI 3.1。",
    "自分で Web スクレイピング + 正規化 + 重複排除 + 失効監視を実装。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "MCP support",
    "96 tools。",
    "自分で実装する場合は MCP サーバーも自作。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Pricing model",
    "¥3/req 完全従量 (税込 ¥3.30)。",
    "Cloud + 開発工数 (人件費が支配的)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "JP corporate count",
    "166,969 件 (gBizINFO + 適格請求書 delta 取込済)。",
    "自分で gBizINFO API + 国税庁 bulk を結合。出典・license 管理を自前で行う必要あり。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Subsidy / 制度 DB",
    "11,684 件 (47 都道府県 + 省庁 + 自治体 1,500+ ソース)。",
    "1,500+ ソースを個別 crawl + 失効監視。アグリゲータ (noukaweb 等) は当社で禁止 — 誤情報リスク。",
    "自前で 1,500+ ソース管理は実務上極めて重い。")
add(SLUG, NAME_JA, NAME_EN, URL, "Tax ruleset DB",
    "50 件 (e-Gov + 国税庁通達 + 措置法)。",
    "e-Gov + 国税庁通達 + 国会会議録 を結合。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Court decisions / 判例",
    "2,065 件 (裁判所公式 + 判例集)。",
    "裁判所サイト + 法律雑誌の判例索引を結合。OCR が必要な判決も多い。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Invoice registrants / 適格請求書",
    "13,801 件。国税庁 bulk PDL v1.0 に基づく登録情報を収録。",
    "国税庁 bulk 月次 DL を自前で取込 — PDL v1.0 で再配布も OK。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Primary source citations",
    "主要な公開行に source_url + fetched_at。",
    "自前で出典管理ポリシーを設計・運用。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Liveness monitoring / 失効監視",
    "<strong>毎晩 tier S/A 全件 + 段階的に B/C も巡回</strong>。404 即 quarantine (tier X)。",
    "自前で URL 死活監視 + cron + alert + DB 巡回。サイト改修ごとに parser 修正。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Deduplication",
    "公募回 / 都道府県差し替え 等の重複パターンを規則化。",
    "自前で名寄せルール設計。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Terms of use",
    "ToS 同意で開始。",
    "各サイトの ToS を個別確認 (アグリゲータ ban 等のポリシー判断が必要)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Free tier",
    "匿名 3 req/日/IP。",
    "自分の Cloud 費 (実質的な「無料枠」はない)。", "")
add(SLUG, NAME_JA, NAME_EN, URL, "Time to first useful response",
    "5 分 (匿名でいきなり叩ける)。",
    "数週間〜数ヶ月 (1,500+ ソースの crawler を書ききるまで)。", "")


def main() -> None:
    fields = ["slug", "competitor_ja", "competitor_en", "competitor_url",
              "axis", "us", "competitor", "note"]
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in ROWS:
            writer.writerow(row)
    print(f"Wrote {len(ROWS)} rows to {CSV_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
