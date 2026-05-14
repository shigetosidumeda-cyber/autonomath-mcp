#!/usr/bin/env python3
"""Generate /compare/{slug}/index.html pages from docs/compare_matrix.csv.

The matrix is hand-curated — this generator just renders the HTML.
Each page documents jpcite vs one alternative JP institutional-data source.

HONESTY RULES:
- Do NOT denigrate competitors.
- Use "公開情報なし" when we don't know — never fabricate.
- Cite competitor public sites for their claims.
- Always include a "When to choose them" section.

Usage:
    .venv/bin/python scripts/generate_compare_pages.py

Outputs:
    site/compare/{slug}/index.html  (10 pages)

The "When to choose us / them / dual-use" copy lives in this script
because each pair has a different honest framing — automating it from
CSV would be fragile.
"""

from __future__ import annotations

import csv
import html
import json
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_CSV = REPO_ROOT / "docs" / "compare_matrix.csv"
OUTPUT_ROOT = REPO_ROOT / "site" / "compare"
PUBLISHED = "2026-04-29"
SITE_BASE = "https://jpcite.com"


# Per-page narrative copy. CSV holds the matrix; this dict holds positioning.
# Every entry must include:
#   title_competitor: short label for H1
#   meta_description: 130-160 char SEO meta
#   intro: one paragraph framing
#   us_strengths: list of 2-3 bullets (HTML allowed)
#   them_strengths: list of 2-3 bullets (HTML allowed)
#   migration: HTML string with 2 <p> for dual-use guidance
PAGES: OrderedDict[str, dict] = OrderedDict()

PAGES["tdb"] = {
    "title_competitor": "帝国データバンク (TDB)",
    "meta_description": (
        "jpcite と帝国データバンクの中立比較 (2026)。API/MCP・価格・データ範囲・"
        "信用調査評点の有無を 15 軸で並べた honest comparison。両者の住み分けと併用ガイド付き。"
    ),
    "intro": (
        "信用調査・与信判断の文脈で帝国データバンク (TDB) を検討中の方向け。"
        "両社はそもそも提供スコープが大きく違います — TDB は<strong>信用調査・評点・経営者経歴</strong>、"
        "jpcite は<strong>制度 (補助金/融資/税制/認定) + 法令 + 判例 + 行政処分 + 適格請求書発行事業者の機械可読 API/MCP</strong>。"
        "「どちらか」ではなく「目的別に併用」が一般的な落としどころです。"
    ),
    "us_strengths": [
        "<strong>機械可読 API + MCP</strong>を必須とする LLM Agent / 自社プロダクトでの自動化用途。151 tools (protocol 2025-06-18) と OpenAPI 3.1 で Claude Desktop / Cursor は MCP、ChatGPT は OpenAPI Actions から呼べます。",
        "<strong>補助金・融資・税制・認定の横断検索</strong>と<strong>行政処分 1,185 件</strong>の取引相手調査が必要なとき。TDB は信用調査専業のため、制度 DB 用途では当社が補完。",
        "<strong>完全従量 ¥3/billable unit</strong>(税込目安 ¥3.30) で最低料金/契約期間なし。匿名 3 requests/日/IP が無料、評価開始の摩擦が低い。",
    ],
    "them_strengths": [
        "<strong>信用調査評点・代表者経歴・親族関係</strong>などの取材ベースの人物・与信情報が必要なとき。TDB は同領域の代表的な専門業者。",
        "上場・大企業を含む<strong>約 147 万社</strong>(同社公開情報) の網羅性、長年の取材・蓄積。当社の corporate_entity 166,969 件より広範。",
        "<strong>Account manager 制</strong>で個別の調査依頼・追跡調査が必要な場面。当社は self-service + メール (info@bookyou.net 48h) のみ。",
    ],
    "migration": (
        "<p><strong>典型的な併用パターン</strong>: 取引先の与信判断は TDB のレポートを取り寄せ、"
        "その上で「この業者は当社の補助金原資 (例: 業務改善助成金) と排他関係にある制度を受給していないか」"
        "「同業者の行政処分履歴は」をjpcite の API/MCP で機械的にクロスチェックする運用です。"
        "TDB のレポート → 法人番号 (T...) → 当社 <code>/v1/programs/by_houjin?houjin_bangou=T...</code> や "
        "<code>/v1/enforcement/search</code> へ流し込めば 1 分で双方が連結します。</p>"
        "<p><strong>移行ではなく補完</strong>: jpcite は信用調査評点を提供しないため、"
        "TDB を完全に置き換えることはできません。"
        "逆に TDB は制度 DB を提供しないため、補助金・融資・税制の自動探索用途は当社が独立で必要になります。"
        "両者は競合ではなく、与信フェーズと制度フェーズで別役割を担うのが現実的な落としどころです。</p>"
    ),
}

PAGES["tsr"] = {
    "title_competitor": "東京商工リサーチ (TSR)",
    "meta_description": (
        "jpcite と東京商工リサーチの中立比較 (2026)。信用調査評点と制度 DB は別役割。"
        "API/MCP・価格・データ範囲を 15 軸で honest に並べ、併用ガイドも掲載。"
    ),
    "intro": (
        "東京商工リサーチ (TSR) を信用調査用途で検討中の方向け。"
        "TSR は<strong>取材ベースの信用調査・評点</strong>、jpcite は<strong>制度 DB の機械可読 API/MCP</strong>"
        "という、提供スコープがほぼ重ならない 2 サービスです。"
        "目的が「与信判断」なら TSR、「補助金・税制・法令の自動探索」なら当社、両方なら併用、が素直な選び方になります。"
    ),
    "us_strengths": [
        "<strong>API/MCP 必須の自動化用途</strong>。151 tools + OpenAPI 3.1 で LLM Agent から直接呼べます。"
        "TSR の API/MCP の公開仕様は 2026-04 時点で公開情報なし。",
        "<strong>11,601 検索可制度 + 2,065 判例 + 9,484 法令 + 1,185 行政処分</strong>の横断検索。TSR の対象外領域。",
        "<strong>¥3/billable unit 完全従量</strong>。年間契約・代理店経由不要、匿名 3 requests/日/IP 無料で評価可能。",
    ],
    "them_strengths": [
        "<strong>信用調査評点 (TSR 評点) と代表者経歴</strong>。同社のコア商品で、当社では提供できない領域。",
        "<strong>約 100 万社以上</strong>(同社公開情報) の網羅性。当社 corporate_entity 166,969 件より広範。",
        "<strong>専属担当者制</strong>で個別調査依頼が可能。当社は self-service + メールのみ。",
    ],
    "migration": (
        "<p><strong>併用が前提</strong>: TSR で与信レポートを取り、得られた法人番号で当社 API を叩いて"
        "「補助金の併給可否」「行政処分の有無」「適格請求書発行事業者の登録番号確認」"
        "「適用可能な税制 (例: 賃上げ促進税制) の検出」を 1 分で機械化できます。"
        "判例や法令を併せて参照する顧問業務 (税理士・行政書士・中小企業診断士) では、両者を並行で使うのが標準的です。</p>"
        "<p><strong>置換ではなく補完</strong>: TSR の取材ベース評点は当社で再現不可能、"
        "当社の制度 DB / 法令 / 判例の機械可読 API は TSR 側にない、という非対称な役割分担です。"
        "「どちらか一方」ではなく、「与信→制度」のフェーズ別ワークフローで自然に併用されます。</p>"
    ),
}

PAGES["gbizinfo"] = {
    "title_competitor": "gBizINFO (METI 公式)",
    "meta_description": (
        "jpcite と gBizINFO (METI 公式) の中立比較 (2026)。gBizINFO は無料で良質な"
        "法人 API、当社は制度 DB の MCP/REST。両者の役割分担と併用方法を解説。"
    ),
    "intro": (
        "gBizINFO は METI が運営する<strong>無料・公式</strong>の法人情報 API で、"
        "jpcite も内部で取込・利用しています (corporate_entity の主要源)。"
        "「法人台帳」用途なら gBizINFO で十分なケースが多く、"
        "当社が必要になるのは<strong>制度 (補助金/融資/税制) との連結</strong>"
        "<strong>判例 / 行政処分 / 適格請求書発行事業者を含めた横断検索</strong>、"
        "そして<strong>MCP プロトコル経由での AI Agent 統合</strong>です。"
    ),
    "us_strengths": [
        "<strong>制度 DB との連結</strong>: 法人番号 → 適用可能な補助金 / 融資 / 税制 / 認定 を 1 リクエストで取得。"
        "gBizINFO は補助金採択企業のリンクはあるが、未受給の制度を逆引きする検索は提供せず。",
        "<strong>MCP プロトコル対応</strong>。Claude Desktop / Cursor は MCP、ChatGPT は OpenAPI Actions から呼べる 151 tools。"
        "gBizINFO は REST のみ (MCP は公開情報なし)。",
        "<strong>判例 2,065 件 + 行政処分 1,185 件 + 法令 9,484 件 + 適格請求書 13,801 件</strong>を横断"
        "(法人 × 制度 × 法令 × 処分 を 1 query)。",
    ],
    "them_strengths": [
        "<strong>完全無料</strong>(政府公式)。当社は ¥3/billable unit 完全従量。"
        "「法人マスタの定期取込だけ必要」なケースなら gBizINFO で完結します。",
        "<strong>500 万社超の網羅性</strong>(法人番号公表サイト連携、ほぼ全法人)。"
        "当社 corporate_entity は 166,969 件で、網羅性では gBizINFO が圧倒。",
        "<strong>政府標準利用規約 2.0</strong>(原則 CC-BY 相当) で再配布が極めて自由。"
        "当社の license フィールドも gBizINFO 由来の行は <code>gov_standard</code> としてこの規約に従う。",
    ],
    "migration": (
        "<p><strong>当社は gBizINFO の上位互換ではなく補完</strong>: 法人マスタの基礎データは gBizINFO が決定版で、"
        "当社内部でも同 API を取込元としています。当社の独自性は<strong>制度・法令・判例・処分との連結</strong>"
        "と<strong>MCP プロトコル経由の AI Agent 直結</strong>です。"
        "「法人マスタだけ欲しい」なら gBizINFO、「制度・法令と連結した上で AI Agent から呼びたい」なら当社、"
        "という単純な切り分けが可能です。</p>"
        "<p><strong>典型的な併用</strong>: バッチで gBizINFO から法人マスタを取込み、"
        "個別の与信・適合判定の場面で当社 MCP の "
        "<code>get_programs_for_entity</code> / <code>check_enforcement_am</code> を呼び出すパターン。"
        "両者ともデータが政府標準利用規約系のため、出典明記すれば下流再配布も可能です (license フィールド参照)。</p>"
    ),
}

PAGES["jgrants"] = {
    "title_competitor": "jGrants (中小企業庁公式申請ポータル)",
    "meta_description": (
        "jpcite と jGrants 公式の中立比較 (2026)。jGrants は申請ポータル、当社は検索 + 適合判定 API/MCP。"
        "役割が違うため住み分けと併用が前提。jGrants 側に API は無い (2026-04 時点)。"
    ),
    "intro": (
        "jGrants は中小企業庁が運営する<strong>補助金の電子申請ポータル</strong>です。"
        "jpcite とはそもそも目的が違い、jGrants は「申請」、当社は「検索・適合判定・MCP 経由 AI Agent 連携」。"
        "「申請を電子化する」なら jGrants、「申請前の探索を自動化する」なら当社、両方使うのが標準的です。"
    ),
    "us_strengths": [
        "<strong>API + MCP で横断検索</strong>。11,601 検索可制度 (補助金 + 融資 + 税制 + 認定) を一括で扱える。"
        "jGrants は 2026-04 時点で公開 API なし、検索 UI のみ。",
        "<strong>適合判定ロジック</strong> (target_types / 業種 / 売上規模 / 都道府県) を query で指定可能。"
        "jGrants の検索はキーワード + カテゴリ中心。",
        "<strong>採択事例 2,286 件 / 行政処分 1,185 件 / 判例 2,065 件 / 法令 9,484 件</strong>を制度と連結。"
        "jGrants は申請特化で、判例・法令・行政処分は対象外。",
    ],
    "them_strengths": [
        "<strong>電子申請</strong>。gBizID 連携で実際に補助金を申請できる唯一の公的経路。"
        "当社は検索・適合判定までで、申請は jGrants 経由を推奨します。",
        "<strong>完全無料</strong>(中小企業庁公式)。",
        "<strong>政府公式の信頼性</strong>。掲載は採択された制度のみで、ノイズが少ない。",
    ],
    "migration": (
        "<p><strong>役割が完全に違う</strong>: jGrants は申請、当社は探索 + 適合判定。"
        "競合関係ではなく、申請フローの<strong>前段</strong>として当社を使い、"
        "適合した制度の jGrants 公募ページ (URL は当社 <code>source_url</code> に格納) "
        "に遷移して電子申請する、というのが自然な動線です。</p>"
        "<p><strong>典型的なワークフロー</strong>: 当社 MCP の "
        "<code>list_open_programs</code> + <code>search_acceptance_stats_am</code> で"
        "事業者プロフィールに合う open 公募を抽出 → 採択事例の傾向を把握 → 当該制度の jGrants 公募ページに遷移して申請。"
        "申請後の追跡 (採択結果) も jGrants 側で確認、その採択事例が翌年以降の探索に役立つループが回ります。</p>"
    ),
}

PAGES["mirasapo"] = {
    "title_competitor": "ミラサポplus (中小企業庁公式)",
    "meta_description": (
        "jpcite とミラサポ plus の中立比較 (2026)。ミラサポは「読み物 + 専門家紹介」、"
        "当社は機械可読 API/MCP。役割の住み分けと併用ガイド付き。"
    ),
    "intro": (
        "ミラサポ plus は中小企業庁の<strong>事業者向け制度ポータル + 専門家紹介プラットフォーム</strong>。"
        "jpcite は同じ制度情報を<strong>機械可読 API/MCP</strong>で配信する基盤層に近い役割で、"
        "両者の競合関係は実は薄く、用途が違います。"
    ),
    "us_strengths": [
        "<strong>API + MCP</strong> による自動化。151 tools で AI Agent から直接呼べる。"
        "ミラサポは 2026-04 時点で公開 API なし。",
        "<strong>適用可能な制度の機械的フィルタ</strong>(業種 / 都道府県 / 売上規模 等の structured query)。",
        "<strong>判例 / 行政処分 / 法令 / 適格請求書発行事業者</strong>の横断検索。"
        "ミラサポは制度紹介中心。",
    ],
    "them_strengths": [
        "<strong>完全無料</strong>(中小企業庁公式)。",
        "<strong>専門家紹介機能</strong>(中小企業診断士・士業マッチング)。"
        "人的支援が必要なケースでは当社では代替不能。",
        "<strong>読み物としての解説の充実</strong>。制度を初めて知る経営者向けの導入線として機能。",
    ],
    "migration": (
        "<p><strong>用途別に住み分け</strong>: 制度を初めて理解する SMB 経営者なら、まずミラサポ plus の解説で勘所を掴み、"
        "「この制度を顧問先 10 社に毎月チェックしたい」「LLM Agent から自動で呼びたい」段階で当社に来る、"
        "が自然な流れです。</p>"
        "<p><strong>士業の方の典型運用</strong>: ミラサポで人的相談 (中小企業診断士の紹介) を案内する一方で、"
        "顧問先への日々の制度通知は当社 MCP の "
        "<code>list_open_programs</code> + <code>deadline_calendar</code> を Claude/ChatGPT 経由で自動化、"
        "という二段構え。互いを置き換えるものではなく、人的層と機械層で重ねる前提です。</p>"
    ),
}

PAGES["moneyforward"] = {
    "title_competitor": "マネーフォワード ビジネスID",
    "meta_description": (
        "jpcite とマネーフォワード ビジネス ID の中立比較 (2026)。会計 SaaS と制度 DB API は"
        "そもそも別領域。スコープの違いと併用ガイドを honest に整理。"
    ),
    "intro": (
        "マネーフォワード (MF) は<strong>会計・経費・人事の SaaS 集約プラットフォーム</strong>、"
        "jpcite は<strong>制度 DB / 法令 / 判例 / 行政処分 / 適格請求書の機械可読 API/MCP</strong>。"
        "提供スコープがほぼ重ならず、競合ではなく併用が前提です。"
        "「自社の会計を回したい」なら MF、「制度・法令を AI Agent から自動探索したい」なら当社。"
    ),
    "us_strengths": [
        "<strong>制度 DB API/MCP</strong>。11,601 検索可制度 + 50 税制 ruleset + 2,065 判例 + 9,484 法令メタデータの横断検索。"
        "MF は会計 SaaS のため、制度 DB の API は提供せず。",
        "<strong>API/MCP 提供</strong>。当社の API は LLM Agent 連携が主用途。"
        "MF API は会計 SaaS の顧客向けで、制度 DB アクセスとは別レイヤー。",
        "<strong>従量 ¥3/billable unit</strong>。会計データ自体は持たないため、「制度横断検索だけ欲しい」なら従量だけで済みます。",
    ],
    "them_strengths": [
        "<strong>会計・経費・給与・人事</strong>の SaaS。当社は会計データを持たず、MF の代替にはなりません。",
        "<strong>銀行 / カード / 決済の連携 (fintech 集約プラットフォーム)</strong>。会計の自動仕訳が主機能。",
        "<strong>多数の中小企業に既に普及</strong>。制度情報も同社の bizキャッシュ等で一部紹介。",
    ],
    "migration": (
        "<p><strong>会計と制度は分離レイヤー</strong>: MF で会計を回しつつ、"
        "「自社の業種・売上・地域に合う未受給の補助金」を当社 API で横断検索する併用が一般的です。"
        "両者のデータが交差するのは、<strong>適格請求書発行事業者の登録番号</strong>と<strong>賃上げ促進税制等の税制</strong>あたり。"
        "当社の <code>invoice_registrants</code> 13,801 件と"
        "<code>tax_rulesets</code> 50 件は MF 内部のマスタとは別系統で、出典 (国税庁 / e-Gov) を直接参照できます。</p>"
        "<p><strong>住み分け</strong>: MF を会計の<strong>口座</strong>として、"
        "当社を制度・法令の<strong>辞書</strong>として併用するイメージ。"
        "両者を接続するのは法人番号 (T...) と業種 (JSIC) のキーで、"
        "「MF で見えた取引履歴 → 当社で適用可能な税制の自動検出」という流れが取れます。</p>"
    ),
}

PAGES["freee"] = {
    "title_competitor": "freee 助成金AI",
    "meta_description": (
        "jpcite と freee 助成金AI の中立比較 (2026)。freee 助成金 AI は freee 顧客向け、"
        "当社は誰でも使える従量 API/MCP。スコープと制約の honest 整理。"
    ),
    "intro": (
        "freee 助成金 AI は<strong>freee 会計・人事の顧客</strong>向けに提供される助成金検索 + 適合判定機能。"
        "jpcite は<strong>誰でも使える従量 API/MCP</strong>で、freee アカウント不要。"
        "「freee を使っていて他は使う気がない」なら freee の方が連携が深く、"
        "「freee 以外の会計を使っている / そもそも会計 SaaS と切り離したい」「LLM Agent から呼びたい」なら当社。"
    ),
    "us_strengths": [
        "<strong>顧客制約なし</strong>。freee アカウント不要、誰でも匿名 3 req/日/IP で評価可能。",
        "<strong>API + MCP</strong>。LLM Agent / 自社プロダクトに直接組み込める 151 tools。"
        "freee 助成金 AI の外部 API は 2026-04 時点で公開情報なし。",
        "<strong>判例 + 行政処分 + 法令 + 適格請求書</strong>の横断検索。"
        "freee 助成金 AI は助成金中心で、これらは対象外。",
    ],
    "them_strengths": [
        "<strong>freee 内部データとの深い連携</strong>。会計・人事データから自動で適合判定できる。"
        "当社は会計データを持たないため、ユーザーが手動で profile を入力する必要がある (or LLM Agent が抽出)。",
        "<strong>会計 SaaS の中で完結</strong>するワークフロー。"
        "「会計→助成金検索→申請」の動線が同一 SaaS 内で繋がる。",
        "<strong>freee サポート</strong>(チャット + 電話)。当社は self-service + メールのみ。",
    ],
    "migration": (
        "<p><strong>顧客の前提が違う</strong>: freee 助成金 AI は freee 顧客向け、"
        "当社は誰向けでも (freee 顧客含む)。「会計 SaaS と切り離して助成金 DB だけ取りたい」"
        "「自前のシステムに組み込みたい」「LLM Agent (Claude / ChatGPT) から呼びたい」"
        "といった用途では当社の従量 API が合います。</p>"
        "<p><strong>併用も可能</strong>: freee 内で日常の助成金チェックは freee 助成金 AI、"
        "より広範な制度 (融資・税制・認定 含む) や判例・行政処分を扱う場面では当社 API、"
        "という二段構え。法人番号と業種コードでキー連結できます。"
        "freee の API でデータ取得→当社の MCP で制度マッチング、というデータ取込も組めます。</p>"
    ),
}

PAGES["navit"] = {
    "title_competitor": "ナビット 補助金検索pro",
    "meta_description": (
        "jpcite とナビット (補助金検索 pro) の中立比較 (2026)。両者とも有償 SaaS だが、"
        "当社は API/MCP + 従量、ナビットは Web UI + Seat 課金。役割の違いを honest に整理。"
    ),
    "intro": (
        "ナビット (株式会社ナビット) は<strong>補助金検索 pro</strong>を提供する SaaS 事業者。"
        "提供領域は当社と近い (補助金 DB) ですが、配信方法が異なります — "
        "ナビットは<strong>Web UI + Seat 課金</strong>、当社は<strong>API/MCP + 従量</strong>。"
        "「人が UI で検索する」ならナビット、「AI Agent / 自社システムから API 呼出」なら当社、が素直な切り分けです。"
    ),
    "us_strengths": [
        "<strong>API + MCP</strong>提供。151 tools で LLM Agent から直接呼べる。"
        "ナビットは Web UI 中心で、API/MCP の公開仕様は 2026-04 時点で公開情報なし。",
        "<strong>従量 ¥3/billable unit</strong>。Seat 不要、必要な分だけ。"
        "ナビットは Seat 課金モデル (公開価格情報なし、要問合せ)。",
        "<strong>制度 + 判例 + 行政処分 + 法令 + 適格請求書</strong>の横断検索。"
        "補助金単体の網羅件数では同社が多い場合あり (「6,000 件以上」と公開) — 件数だけが指標ならナビットを検討する価値あり。",
    ],
    "them_strengths": [
        "<strong>補助金件数の網羅性</strong>。「6,000 件以上」と公開 (同社サイト) — 当社の補助金単体カウントよりは広い領域あり。"
        "ただし当社は補助金以外 (融資/税制/認定/判例/法令/処分/適格請求書) も含む横断構造のため、単純比較は難しい。",
        "<strong>Web UI</strong>。プログラミング不要で経営者・士業がそのまま使える。当社は API/MCP が主のため、UI 利用者は別途ダッシュボードが必要。",
        "<strong>無料お試し</strong>あり (公開情報、期間/制限は要確認)。",
    ],
    "migration": (
        "<p><strong>UI ユーザー vs API ユーザー</strong>で住み分け: 経営者個人や士業がブラウザで使うならナビット、"
        "AI Agent / 自社プロダクト / バッチ処理から呼ぶなら当社。"
        "「人が UI で 1 件ずつ眺める」用途と「機械が大量に列挙する」用途で配信形態が違います。</p>"
        "<p><strong>併用も成立</strong>: ナビットの Web UI で発見した制度の<strong>一次資料 URL</strong>を当社 API で再取得して "
        "<code>source_url</code> + <code>fetched_at</code> 付きで保存、判例・法令との連結を当社 MCP で行う、"
        "といった補完使用も可能です。"
        "両者の補助金 DB は重複が多いため、片方で十分なケースも多く、"
        "「件数の網羅性 vs API/MCP 経由の自動化」のどちらを優先するかで決まります。</p>"
    ),
}

PAGES["nta-invoice"] = {
    "title_competitor": "国税庁 適格請求書発行事業者公表サイト",
    "meta_description": (
        "jpcite と国税庁 適格請求書発行事業者公表サイトの中立比較 (2026)。"
        "国税庁公表サイトは登録番号のみ、当社は制度 + 法人 + 適格請求書を横断する API/MCP。役割の違いを整理。"
    ),
    "intro": (
        "国税庁 適格請求書発行事業者公表サイト (invoice-kohyo.nta.go.jp) は<strong>登録番号公表のみ</strong>を扱う"
        "<strong>無料・公式</strong>サービスで、Web API + 月次 bulk CSV を提供。"
        "当社も同 bulk を取込元としており、「適格請求書発行事業者の登録番号確認だけ」なら国税庁公表サイトで完結します。"
        "当社が必要になるのは、<strong>同登録番号と制度 / 判例 / 行政処分 / 法人マスタを横断連結</strong>"
        "<strong>MCP プロトコル経由で AI Agent から呼ぶ</strong>場合です。"
    ),
    "us_strengths": [
        "<strong>登録番号 × 制度の横断検索</strong>。同事業者が受給できる補助金 / 適用税制 / 該当判例 を 1 リクエストで取得。"
        "国税庁公表サイトは登録番号と公示情報のみで、他データとの結合は提供せず。",
        "<strong>MCP プロトコル対応</strong>。Claude Desktop / Cursor は MCP、ChatGPT は OpenAPI Actions から呼べる 151 tools。"
        "国税庁公表サイトは Web API のみで、MCP は対象外。",
        "<strong>判例 / 行政処分 / 法令</strong>を含む横断検索。「取引相手の登録番号 → 行政処分の有無」を 1 query で確認可能。",
    ],
    "them_strengths": [
        "<strong>完全無料</strong>(国税庁公式)。当社は ¥3/billable unit 完全従量。",
        "<strong>登録番号約 4 百万件の網羅性</strong>(全件)。"
        "当社は delta 13,801 件で、フル取込は月次予定。網羅性では国税庁公表サイトが圧倒。",
        "<strong>PDL v1.0</strong>(Public Data License) で出典明記付きの再配布が可能。"
        "当社の bulk 取込もこの規約のおかげで成立。",
    ],
    "migration": (
        "<p><strong>当社は国税庁公表サイトの上位互換ではない</strong>: 登録番号の網羅性とコストで国税庁が上、"
        "当社は<strong>制度 / 判例 / 行政処分との連結</strong>と<strong>MCP 経由の AI Agent 直結</strong>のために存在します。"
        "「登録番号確認だけ」なら国税庁公表サイトで完結、"
        "「登録番号と制度 / 行政処分をクロスチェックしたい」「AI Agent から呼びたい」なら当社、で切り分け可能です。</p>"
        "<p><strong>典型的な併用</strong>: バッチで国税庁の bulk CSV を取込んで自社 DB に保存、"
        "個別の取引判定で当社 MCP の <code>check_enforcement_am</code> + 制度連結を呼び出すパターン。"
        "当社内部もこの構造で、<code>invoice_registrants</code> テーブルは国税庁 bulk が真値、"
        "我々は連結とインターフェース層を提供する補完関係です。</p>"
    ),
}

PAGES["diy-scraping"] = {
    "title_competitor": "自前スクレイピング (DIY)",
    "meta_description": (
        "jpcite vs 自前スクレイピング — 制度 DB を自分で crawl + 正規化 + MCP 化する場合の "
        "工数 / 失効監視 / dedup / license 管理の比較。買うか作るかの honest 整理。"
    ),
    "intro": (
        "「制度 DB は自分で crawl すれば作れるのでは」と検討中の開発者向け。"
        "技術的には作れます — 当社もそうしました。"
        "ただし、本気で本番品質に持っていく場合の工数 (ソース 1,500+ / 失効監視 / dedup / license 管理 / 政府サイト改修追従)"
        "を踏まえると、買う方が早いケースが多いという honest な比較です。"
    ),
    "us_strengths": [
        "<strong>5 分で動く</strong>。匿名 3 req/日/IP で即評価、API key 不要。"
        "自前 crawler は 1,500+ ソースを書ききるまで数週間〜数ヶ月。",
        "<strong>失効監視 + dedup + license 管理</strong>を当社が運用。"
        "URL 死活と出典鮮度を定期的に監視し、問題のある行は確認対象に回します。"
        "重複除去ロジック (公募回 / 都道府県差し替え) も内製済。",
        "<strong>151 MCP tools</strong>を Claude Desktop / Cursor は MCP、ChatGPT は OpenAPI Actions から呼び出し。"
        "自前で MCP サーバーを書く工数も不要。",
    ],
    "them_strengths": [
        "<strong>完全コントロール</strong>。データ構造・正規化方針・更新頻度を自社要件に合わせて設計可能。"
        "当社のスキーマで合わない場合、自前が選択肢。",
        "<strong>原価が下がる</strong>(規模次第)。月数十万 req 規模で長期運用するなら、Cloud + 開発工数の方が"
        "従量 ¥3/billable unit より安くなる可能性あり (人件費を除けば)。",
        "<strong>機密性</strong>。第三者 API に query を流したくない (例: クライアント名を含む) ケースでは自前が必要。",
    ],
    "migration": (
        "<p><strong>買って始め、作るかは後で判断</strong>: まず当社 API で小さく検証し、必要なデータ範囲を確認してから、"
        "本当にデータの一部だけが必要 (例: 自社業種の補助金 50 件分だけ) と分かった段階で、"
        "そのスライスだけ自前で crawl する、というハイブリッド戦略が現実的です。"
        '当社の OpenAPI 3.1 spec は <a href="/docs/api-reference/">API リファレンス</a> 経由で公開、'
        'MCP tool 仕様も <a href="/docs/mcp-tools/">MCP tools</a> で読めるため、'
        "後から自前に切り替える際の移植も比較的容易です。</p>"
        "<p><strong>license の落とし穴</strong>: 自前 crawler の最大の罠は<strong>出典管理</strong>です。"
        "集約サイト (noukaweb / hojyokin-portal / biz.stayway 等) を <code>source_url</code> にすると"
        "古い金額・終了済み制度を孫引きしてしまい、景表法 / 善管注意義務リスクが顕在化します。"
        "当社は「集約サイトを出典にしない」方針を公開し、主要な公開行に"
        "<code>source_url</code> + <code>fetched_at</code> + <code>license</code> を持たせています。"
        "この運用を自前で再現するのは技術より<strong>規律の問題</strong>で、"
        "「とりあえず動くもの」と「本番に出せるもの」の差が大きい領域です。</p>"
    ),
}


def load_matrix() -> dict[str, list[dict]]:
    """Load CSV and group rows by slug."""
    by_slug: dict[str, list[dict]] = {}
    with MATRIX_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = row["slug"].strip()
            by_slug.setdefault(slug, []).append(row)
    return by_slug


def render_matrix_html(rows: list[dict], competitor_label: str) -> str:
    """Render the comparison <table>."""
    parts: list[str] = []
    parts.append('<div class="compare-wrap">')
    parts.append('<table class="compare-table">')
    parts.append("<thead>")
    parts.append("<tr>")
    parts.append('<th scope="col">比較軸</th>')
    parts.append('<th scope="col" class="col-us">jpcite</th>')
    parts.append(f'<th scope="col">{html.escape(competitor_label)}</th>')
    parts.append('<th scope="col">補足</th>')
    parts.append("</tr>")
    parts.append("</thead>")
    parts.append("<tbody>")
    for i, row in enumerate(rows, 1):
        axis = html.escape(row["axis"])
        us = row["us"]
        them = row["competitor"]
        note = row.get("note", "") or ""
        parts.append("<tr>")
        parts.append(f'<th scope="row">{i}. {axis}</th>')
        parts.append(f'<td class="col-us">{us}</td>')
        parts.append(f"<td>{them}</td>")
        parts.append(f'<td class="compare-note-cell">{note}</td>' if note else "<td></td>")
        parts.append("</tr>")
    parts.append("</tbody>")
    parts.append("</table>")
    parts.append("</div>")
    return "\n".join(parts)


def render_jsonld(slug: str, page: dict) -> str:
    """Render JSON-LD: Article + Organization."""
    title_competitor = page["title_competitor"]
    headline = f"jpcite vs {title_competitor}: 機能・価格・データ範囲の比較 (2026)"
    url = f"{SITE_BASE}/compare/{slug}/"
    article_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": page["meta_description"],
        "url": url,
        "datePublished": PUBLISHED,
        "dateModified": PUBLISHED,
        "inLanguage": "ja",
        "author": {
            "@type": "Organization",
            "name": "Bookyou株式会社",
            "url": f"{SITE_BASE}/",
        },
        "publisher": {
            "@type": "Organization",
            "name": "Bookyou株式会社",
            "url": f"{SITE_BASE}/",
        },
        "mainEntityOfPage": url,
    }
    org_ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Bookyou株式会社",
        "alternateName": ["jpcite"],
        "url": f"{SITE_BASE}/",
        "address": {
            "@type": "PostalAddress",
            "addressCountry": "JP",
            "addressLocality": "文京区",
            "addressRegion": "東京都",
        },
        "contactPoint": {
            "@type": "ContactPoint",
            "email": "info@bookyou.net",
            "contactType": "customer support",
        },
    }
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(article_ld, ensure_ascii=False, indent=2)
        + "\n</script>\n"
        + '<script type="application/ld+json">\n'
        + json.dumps(org_ld, ensure_ascii=False, indent=2)
        + "\n</script>"
    )


def render_page(slug: str, page: dict, rows: list[dict]) -> str:
    title_competitor = page["title_competitor"]
    headline = f"jpcite vs {title_competitor}: 機能・価格・データ範囲の比較 (2026)"
    url = f"{SITE_BASE}/compare/{slug}/"
    matrix_html = render_matrix_html(rows, title_competitor)
    jsonld = render_jsonld(slug, page)
    us_bullets = "\n".join(f"<li>{b}</li>" for b in page["us_strengths"])
    them_bullets = "\n".join(f"<li>{b}</li>" for b in page["them_strengths"])
    competitor_url = rows[0].get("competitor_url", "") if rows else ""
    if competitor_url:
        competitor_link_phrase = f'最新情報は <a href="{html.escape(competitor_url)}" rel="noopener nofollow" target="_blank">{html.escape(title_competitor)} 公式</a> および当社 <a href="/pricing.html">料金ページ</a> をご確認ください。'
    else:
        competitor_link_phrase = f'最新情報は当社 <a href="/pricing.html">料金ページ</a> でご確認ください ({html.escape(title_competitor)} は外部サービスではないため公式参照先はありません)。'
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>{html.escape(headline)} — jpcite</title>
<meta name="description" content="{html.escape(page["meta_description"])}">
<meta name="robots" content="index,follow">

<meta property="og:title" content="{html.escape(headline)}">
<meta property="og:description" content="{html.escape(page["meta_description"])}">
<meta property="og:type" content="article">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE_BASE}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(headline)}">
<meta name="twitter:description" content="{html.escape(page["meta_description"])}">
<meta name="twitter:image" content="{SITE_BASE}/assets/og-twitter.png">

<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="ja" href="{url}">
<link rel="alternate" hreflang="x-default" href="{url}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/assets/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="stylesheet" href="/styles.css?v=20260515c">

{jsonld}

<style>
  .compare-page {{ padding: 48px 0 64px; }}
  .compare-page h1 {{ font-size: 30px; margin: 0 0 8px; font-weight: 800; letter-spacing: -0.01em; line-height: 1.3; }}
  .compare-page .lead {{ font-size: 16px; color: var(--text-muted); margin: 0 0 22px; max-width: 760px; line-height: 1.75; }}
  .compare-page h2 {{ font-size: 22px; margin: 40px 0 12px; font-weight: 700; }}
  .compare-page h3 {{ font-size: 17px; margin: 22px 0 8px; font-weight: 700; }}
  .compare-page p, .compare-page ul {{ max-width: 820px; line-height: 1.75; }}
  .compare-page strong {{ font-weight: 700; }}
  .compare-page code {{ background: var(--bg-alt); padding: 1px 6px; border-radius: 4px; font-size: 0.92em; }}
  .compare-disclaimer {{
    background: var(--bg-alt); border-left: 3px solid var(--accent);
    padding: 14px 18px; border-radius: 8px; font-size: 14px;
    color: var(--text-muted); margin: 0 0 28px; max-width: 820px; line-height: 1.7;
  }}
  .compare-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; margin: 16px 0 8px; }}
  .compare-table {{ width: 100%; border-collapse: collapse; font-size: 14px; min-width: 760px; background: var(--bg); }}
  .compare-table th, .compare-table td {{ border-bottom: 1px solid var(--border); padding: 10px 12px; text-align: left; vertical-align: top; }}
  .compare-table thead th {{ background: var(--bg-alt); font-size: 12px; letter-spacing: 0.03em; text-transform: uppercase; color: var(--text-muted); white-space: nowrap; position: sticky; top: 0; }}
  .compare-table tbody th {{ font-weight: 600; color: var(--text); width: 18%; background: var(--bg-alt); }}
  .compare-table .col-us {{ background: rgba(30,58,138,0.03); }}
  .compare-table .compare-note-cell {{ font-size: 12.5px; color: var(--text-muted); width: 22%; }}
  .compare-table tbody tr:hover td, .compare-table tbody tr:hover th {{ background: rgba(30,58,138,0.04); }}
  .compare-table tbody tr:last-child th, .compare-table tbody tr:last-child td {{ border-bottom: 0; }}
  .pick-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 16px 0 0; }}
  .pick-card {{ border: 1px solid var(--border); border-radius: 10px; padding: 20px; background: var(--bg); }}
  .pick-card h3 {{ margin: 0 0 8px; font-size: 16px; font-weight: 700; }}
  .pick-card .pick-tag {{ font-size: 12px; color: var(--accent); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; margin: 0 0 10px; }}
  .pick-card ul {{ font-size: 14px; color: var(--text); margin: 0; padding-left: 20px; line-height: 1.7; }}
  .pick-card.us {{ border-color: var(--accent); }}
  .compare-migration {{ border: 1px solid var(--border); border-radius: 10px; padding: 22px 24px; background: var(--bg-alt); margin: 16px 0 0; }}
  .compare-migration p {{ margin: 0 0 12px; font-size: 14.5px; }}
  .compare-migration p:last-child {{ margin-bottom: 0; }}
  .related-list {{ list-style: none; padding: 0; margin: 12px 0 0; display: flex; flex-wrap: wrap; gap: 12px; }}
  .related-list li {{ background: var(--bg-alt); border-radius: 6px; padding: 6px 12px; font-size: 13.5px; }}
  .related-list a {{ text-decoration: none; }}
  .footnote {{ font-size: 13px; color: var(--text-muted); margin: 32px 0 0; max-width: 820px; line-height: 1.7; }}
  @media (max-width: 768px) {{
    .pick-grid {{ grid-template-columns: 1fr; }}
    .compare-table .compare-note-cell {{ display: none; }}
  }}
</style>

<script defer src="/analytics.js?v=20260503a"></script>
</head>
<body>

<a class="skip-link" href="#main">メインコンテンツへスキップ / Skip to main content</a>

<header class="site-header" role="banner">
  <div class="container header-inner">
    <a class="brand" href="/" aria-label="jpcite ホーム">
 <picture><source media="(prefers-color-scheme: dark)" srcset="/assets/brand/lockup-transparent-600-lightlogo.png 1x, /assets/brand/lockup-transparent-1200-lightlogo.png 2x"><img src="/assets/brand/lockup-transparent-600-darklogo.png" srcset="/assets/brand/lockup-transparent-600-darklogo.png 1x, /assets/brand/lockup-transparent-1200-darklogo.png 2x" width="190" decoding="async" fetchpriority="high" alt="jpcite" height="32" style="height:32px;width:auto;display:block;"></picture>
 </a>
    <nav class="site-nav" aria-label="主要ナビゲーション">
      <a href="/about.html">About</a>
      <a href="/products.html">Products</a>
      <a href="/docs/">Docs</a>
      <a href="/pricing.html">Pricing</a>
      <a href="/audiences/">Audiences</a>
      <a href="/compare.html">Compare</a>
    </nav>
  </div>
</header>

<main id="main" class="compare-page">
  <div class="container">

    <nav aria-label="ぱんくず" style="font-size:13px;color:var(--text-muted);margin:0 0 16px;">
      <a href="/">ホーム</a>
      <span aria-hidden="true">/</span>
      <a href="/compare.html">比較</a>
      <span aria-hidden="true">/</span>
      <span aria-current="page">{html.escape(title_competitor)}</span>
    </nav>

    <h1>{html.escape(headline)}</h1>
    <p class="lead">{page["intro"]}</p>

    <div class="compare-disclaimer">
      <strong>本ページは公開情報をもとに当社が作成しています。</strong>
      各社価格・機能は <time datetime="{PUBLISHED}">{PUBLISHED}</time> 時点のもので、{competitor_link_phrase}
      誤りに気づいた場合は <a href="mailto:info@bookyou.net?subject=compare/{slug}%20correction">info@bookyou.net</a> までご連絡いただければ 48 時間以内に修正します。
    </div>

    <h2>機能・データ範囲・価格の比較表</h2>
    <p>「公開情報なし」と書いた行は<strong>「機能が無い」と断定するものではありません</strong> — 各社公式サイトに記載が無い、または当社が確認できなかった項目です。</p>

    {matrix_html}

    <h2>当社を選ぶケース</h2>
    <div class="pick-grid">
      <div class="pick-card us">
        <p class="pick-tag">jpcite が向いている</p>
        <ul>
          {us_bullets}
        </ul>
      </div>
      <div class="pick-card">
        <p class="pick-tag">{html.escape(title_competitor)} が向いている</p>
        <ul>
          {them_bullets}
        </ul>
      </div>
    </div>

    <h2>移行 / 併用ガイド</h2>
    <div class="compare-migration">
      {page["migration"]}
    </div>

    <h2>関連ページ</h2>
    <ul class="related-list">
      <li><a href="/compare.html">全比較表 (6 サービス × 13 軸)</a></li>
      <li><a href="/pricing.html">料金 (¥3/billable unit 完全従量)</a></li>
      <li><a href="/docs/api-reference/">API リファレンス</a></li>
      <li><a href="/docs/mcp-tools/">MCP tools (139)</a></li>
      <li><a href="/sources.html">出典・ライセンス</a></li>
      <li><a href="/facts.html">数字の検証 SQL</a></li>
    </ul>

    <p class="footnote">
      凡例: 「公開情報なし」「公開情報非公表」は、各社公式サイトに記載が確認できなかった、または当社が把握していない項目を指します。
      機能の不在を断定するものではありません。各社 ToS や新規機能追加によって変わります。
      本ページは公開情報に基づき、誇張を避け、訂正依頼を受け付けます。
      訂正が必要な場合は <a href="mailto:info@bookyou.net?subject=compare/{slug}%20correction">info@bookyou.net</a> 宛にご連絡ください。
    </p>

  </div>
</main>

<div class="container">
  <p class="trust-strip" style="margin:24px 0 8px;font-size:13px;color:var(--text-muted);line-height:1.7;">
    比較は <time datetime="{PUBLISHED}">{PUBLISHED}</time> 時点の各社公開情報に基づきます。
    {html.escape(title_competitor)} の各サービス名は、運営者の登録商標または商標です。
    · 運営 <a href="/about.html">Bookyou株式会社</a>
    · <a href="/tokushoho.html">特商法表記</a> / <a href="/tos.html">利用規約</a> / <a href="/privacy.html">プライバシー</a>
    · 修正提案 <a href="mailto:info@bookyou.net?subject=compare/{slug}%20correction">info@bookyou.net</a>
  </p>
</div>

<footer class="site-footer" role="contentinfo">
  <div class="container footer-inner">
    <div class="footer-col">
      <p class="footer-brand"><picture class="footer-brand-mark"><source media="(prefers-color-scheme: light)" srcset="/assets/brand/jpcite-mark-light-fill.svg"><img src="/assets/brand/jpcite-mark-dark-fill.svg" alt="" width="20" height="20" loading="lazy" decoding="async"></picture>jpcite</p>
      <p class="footer-tag">日本の制度 API</p>
    </div>
    <nav class="footer-nav" aria-label="フッター">
      <a href="/tos.html">利用規約</a>
      <a href="/privacy.html">プライバシー</a>
      <a href="/tokushoho.html">特定商取引法</a>
      <a href="https://github.com/shigetosidumeda-cyber/autonomath-mcp" aria-label="GitHub" rel="noopener">GitHub</a>
      <a href="mailto:info@bookyou.net">info@bookyou.net</a>
    </nav>
    <p class="footer-entity">運営: Bookyou株式会社 · <a href="mailto:info@bookyou.net">info@bookyou.net</a></p>
    <p class="footer-copy">&copy; 2026 Bookyou株式会社</p>
  </div>
</footer>

<script src="/assets/trust-strip.js" defer></script>

</body>
</html>
"""


def main() -> None:
    by_slug = load_matrix()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    written = 0
    for slug, page in PAGES.items():
        rows = by_slug.get(slug)
        if not rows:
            print(f"[skip] no matrix rows for slug={slug}")
            continue
        out_dir = OUTPUT_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "index.html"
        out_path.write_text(render_page(slug, page, rows), encoding="utf-8")
        print(f"[ok] {out_path.relative_to(REPO_ROOT)} ({len(rows)} axes)")
        written += 1
    print(f"\nDone: {written} pages written to {OUTPUT_ROOT.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
