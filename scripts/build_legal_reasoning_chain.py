"""build_legal_reasoning_chain — Lane N3 chain composer (jpcite Niche Moat).

Pure-Python rule engine that composes 三段論法 (syllogistic) reasoning
chains over the existing corpus:

  premise (大前提)        — 法令条文 (am_law_article) + 通達 (nta_tsutatsu_index
                            / am_law_article on law:*-tsutatsu rows)
  minor premise (小前提)   — 判例 (court_decisions, jpintel.db side, HAN-*) +
                            裁決事例 (nta_saiketsu, autonomath.db side)
  conclusion (結論)        — 学説 + 一般実務 (deterministic text)
  opposing view (反対説)   — 反対説 / 異論 (optional, caps confidence)
  citations (引用 triple)  — 法令 + 判例 + 通達 JSON envelope

Constraints (memory ``feedback_autonomath_no_api_use`` +
``feedback_no_operator_llm_api`` + CLAUDE.md "What NOT to do"):

* NO LLM API call. Pure SQLite SELECT + Python dict shaping.
* Cross-DB reads: jpintel.db (court_decisions) + autonomath.db
  (am_law / am_law_article / nta_tsutatsu_index / nta_saiketsu).
  CLAUDE.md forbids cross-DB JOIN — open both, pull separately,
  merge in Python.
* INSERT OR REPLACE on chain_id so re-runs overwrite prior composition.
* mypy --strict clean.
* Chain id shape: ``LRC-<10 lowercase hex>`` (matches the rest of the
  autonomath SOT naming so the MCP surface can pattern-match like
  ``TAX-<10 hex>`` / ``HAN-<10 hex>``).

Topic taxonomy (160 topics, 5 viewpoint slices each → 800 chains):
  corporate_tax   50 topics
  consumption_tax 30 topics
  subsidy         30 topics
  labor           20 topics
  commerce        30 topics
  (income_tax topics are folded into corporate_tax tax_category for the
   moat retrieval contract; the topic_id namespace remains separate.)

Each topic resolves to a (law_canonical_id, article_number_prefix,
keywords) anchor used to query the corpus.

Run:
  .venv/bin/python scripts/build_legal_reasoning_chain.py [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = logging.getLogger("build_legal_reasoning_chain")

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"


# ---------------------------------------------------------------------------
# Topic taxonomy (deterministic, hand-curated)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Topic:
    """One reasoning-chain anchor.

    ``law_canonical_id`` selects the primary law surface, ``article_numbers``
    bounds the article window (empty tuple = no article cap), and ``keywords``
    is the FTS5-style token bag for judgment + saiketsu retrieval.
    """

    topic_id: str
    label: str
    tax_category: str
    law_canonical_id: str
    article_numbers: tuple[str, ...]
    tsutatsu_law_id: str
    tsutatsu_article_prefix: tuple[str, ...]
    keywords: tuple[str, ...]
    conclusion_text: str
    opposing_view_text: str | None = None
    viewpoint_slices: tuple[str, ...] = field(default_factory=tuple)


_BASE_VIEWPOINT_SLICES: tuple[str, ...] = (
    "原則的取扱い",
    "通達上の例外",
    "判例の傾向",
    "実務上の留意点",
    "反対説の余地",
)


def _t(
    topic_id: str,
    label: str,
    tax_category: str,
    law_canonical_id: str,
    article_numbers: tuple[str, ...],
    tsutatsu_law_id: str,
    tsutatsu_article_prefix: tuple[str, ...],
    keywords: tuple[str, ...],
    conclusion_text: str,
    opposing_view_text: str | None = None,
) -> Topic:
    """Compact factory — produces a Topic with the canonical 5 viewpoint slices."""
    return Topic(
        topic_id=topic_id,
        label=label,
        tax_category=tax_category,
        law_canonical_id=law_canonical_id,
        article_numbers=article_numbers,
        tsutatsu_law_id=tsutatsu_law_id,
        tsutatsu_article_prefix=tsutatsu_article_prefix,
        keywords=keywords,
        conclusion_text=conclusion_text,
        opposing_view_text=opposing_view_text,
        viewpoint_slices=_BASE_VIEWPOINT_SLICES,
    )


_HOJIN = "law:corporate-tax"
_SOZEI = "law:sozei-tokubetsu"
_SHOHI = "law:consumption-tax"
_SHOTOKU = "law:income-tax"
_KAISHA = "law:kaisha"
_ROUDOU = "law:rodokijun"
_CHUSHO = "law:chusho-keiei-kyouka"
_HOJIN_TT = "law:hojin-zei-tsutatsu"
_SHOHI_TT = "law:shohi-zei-tsutatsu"
_SHOTOKU_TT = "law:shotoku-zei-tsutatsu"
_TT_DEFAULT = ("9-2",)


_CORPORATE_TAX_TOPICS: tuple[Topic, ...] = (
    _t(
        "corporate_tax:yakuin_hosyu",
        "役員報酬の損金算入",
        "corporate_tax",
        _HOJIN,
        ("34",),
        _HOJIN_TT,
        ("9-2",),
        ("役員報酬", "役員給与", "損金"),
        "役員給与の損金算入は法人税法34条が定型給与・事前確定届出給与・業績連動給与の3類型に限定。届出要件・支給基準の客観性が損金算入の可否を分ける。",
        "形式要件を満たさない場合でも、税務上の合理性が認められれば損金算入を主張する余地ありとの見解もあるが、判例は形式要件を厳格に解する傾向。",
    ),
    _t(
        "corporate_tax:kifukin",
        "寄附金の損金算入",
        "corporate_tax",
        _HOJIN,
        ("37",),
        _HOJIN_TT,
        ("9-4",),
        ("寄附金", "損金"),
        "寄附金の損金算入は法人税法37条で資本金等の額・所得金額に応じた損金算入限度額が定められる。国・地方公共団体への寄附および指定寄附金は全額損金算入、特定公益増進法人への寄附は別枠の限度額。",
        "事業関連性の認定に争いが残る場合、対価性ある支出として全額損金算入を主張する立場も存在するが、対価性の立証責任は納税者側にある。",
    ),
    _t(
        "corporate_tax:kosaihi",
        "交際費の損金不算入",
        "corporate_tax",
        _SOZEI,
        ("61-4",),
        _HOJIN_TT,
        ("9-4",),
        ("交際費", "接待"),
        "交際費は租税特別措置法61条の4により原則損金不算入。中小法人は800万円までの定額控除、または接待飲食費の50%損金算入の選択適用が可能。",
        "情報提供料・販売促進費との区分について争いがあり、実態判定で交際費から除外できる主張も認められる場合がある。",
    ),
    _t(
        "corporate_tax:genka_shoukyaku",
        "減価償却資産の取得価額",
        "corporate_tax",
        _HOJIN,
        ("31",),
        _HOJIN_TT,
        ("7-3",),
        ("減価償却", "取得価額"),
        "減価償却資産の取得価額は法人税法施行令54条により購入代価+付随費用が原則。事業供用日から法定耐用年数で償却。少額減価償却資産10万円未満は即時損金算入可能。",
    ),
    _t(
        "corporate_tax:tokurei_souzoku",
        "同族会社の行為計算否認",
        "corporate_tax",
        _HOJIN,
        ("132", "132-2"),
        _HOJIN_TT,
        ("9-1",),
        ("同族会社", "行為計算否認", "不当に減少"),
        "同族会社の行為計算否認は法人税法132条・132条の2により、経済合理性を欠く取引で法人税負担を不当に減少させた場合に税務署長が否認できる。ヤフー事件・IBM事件で『不当に』の判断基準が確立。",
        "経済合理性の解釈に争いがあり、組織再編税制適用後の合併・分割では事業上の必要性が認められれば132条の2の発動は限定的とする見解も有力。",
    ),
    _t(
        "corporate_tax:kessonkin_kurikoshi",
        "欠損金の繰越控除",
        "corporate_tax",
        _HOJIN,
        ("57",),
        _HOJIN_TT,
        ("12-1",),
        ("欠損金", "繰越"),
        "欠損金の繰越控除は法人税法57条により10年(2018年4月1日以後開始事業年度)。大法人は所得金額の50%まで、中小法人は100%まで控除可能。青色申告継続が要件。",
    ),
    _t(
        "corporate_tax:hikiate_kin",
        "貸倒引当金の損金算入",
        "corporate_tax",
        _HOJIN,
        ("52",),
        _HOJIN_TT,
        ("11-2",),
        ("貸倒", "引当金"),
        "貸倒引当金は法人税法52条により個別評価金銭債権・一括評価金銭債権の2種類。中小法人・銀行業・保険業のみに認められる(平成23年改正)。",
    ),
    _t(
        "corporate_tax:zaiko_hyouka",
        "棚卸資産の評価",
        "corporate_tax",
        _HOJIN,
        ("29",),
        _HOJIN_TT,
        ("5-2",),
        ("棚卸", "評価"),
        "棚卸資産の評価方法は法人税法29条で原価法と低価法を選択適用。評価方法の選定届出書を提出しない場合、最終仕入原価法が法定。",
    ),
    _t(
        "corporate_tax:zougen_zei",
        "法人税の課税所得計算",
        "corporate_tax",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("2-1",),
        ("課税所得", "益金", "損金"),
        "課税所得は法人税法22条で益金-損金で計算。公正処理基準により企業会計の益金・損金を尊重しつつ、別段の定めで税務調整。",
    ),
    _t(
        "corporate_tax:soshiki_saihen",
        "組織再編税制の適格要件",
        "corporate_tax",
        _HOJIN,
        ("62-2", "62-3"),
        _HOJIN_TT,
        ("1-4",),
        ("組織再編", "適格", "合併"),
        "適格組織再編の要件は法人税法2条12号の8〜2条12号の14、62条の2〜62条の3。完全支配関係/支配関係/共同事業の3類型ごとに移転資産・株式・従業者の継続要件が課される。",
    ),
    _t(
        "corporate_tax:kabushiki_kosatsu",
        "株式交換・株式移転の課税",
        "corporate_tax",
        _HOJIN,
        ("62-7", "62-9"),
        _HOJIN_TT,
        ("1-4",),
        ("株式交換", "株式移転"),
        "適格株式交換・株式移転は法人税法62条の7・62条の9により完全親子関係の創設で簿価引継ぎ・課税繰延。非適格は時価評価課税。",
    ),
    _t(
        "corporate_tax:bunkatsu",
        "会社分割の税務",
        "corporate_tax",
        _HOJIN,
        ("62-3",),
        _HOJIN_TT,
        ("1-4",),
        ("会社分割", "分割"),
        "適格分割は法人税法62条の3により分社型・分割型ともに簿価引継ぎ。非適格は時価による譲渡損益認識。共同事業要件・按分要件で判定。",
    ),
    _t(
        "corporate_tax:gensoku_seido",
        "原則課税と軽減税率",
        "corporate_tax",
        _HOJIN,
        ("66",),
        _HOJIN_TT,
        ("16-",),
        ("法人税率", "中小法人"),
        "法人税率は法人税法66条で原則23.2%。中小法人(資本金1億円以下)は所得800万円以下部分が15%軽減税率。",
    ),
    _t(
        "corporate_tax:kenkyu_kaihatsu",
        "試験研究費の税額控除",
        "corporate_tax",
        _SOZEI,
        ("42-4",),
        _HOJIN_TT,
        ("42-",),
        ("研究開発", "税額控除"),
        "試験研究費の税額控除は租税特別措置法42条の4により総額型(6-14%)+OI型(20-30%)。法人税額の25%(中小法人35%)を上限。",
    ),
    _t(
        "corporate_tax:chiho_zei",
        "地方法人税",
        "corporate_tax",
        "law:chiho-hojin-zei",
        ("9", "10"),
        _HOJIN_TT,
        ("16-",),
        ("地方法人税",),
        "地方法人税は地方法人税法により法人税額の10.3%。国税として徴収後、地方交付税の原資として地方公共団体に配分。",
    ),
    _t(
        "corporate_tax:jigyou_zei",
        "法人事業税",
        "corporate_tax",
        "law:chihou-zei",
        ("72",),
        _HOJIN_TT,
        ("16-",),
        ("事業税", "外形標準"),
        "法人事業税は地方税法72条以下により、資本金1億円超の大法人は所得割+付加価値割+資本割の外形標準課税。中小法人は所得割のみ。",
    ),
    _t(
        "corporate_tax:juumin_zei",
        "法人住民税",
        "corporate_tax",
        "law:chihou-zei",
        ("23", "292"),
        _HOJIN_TT,
        ("16-",),
        ("法人住民税", "均等割"),
        "法人住民税は法人税割+均等割。法人税割は法人税額ベース。均等割は資本金等+従業員数に応じた定額(年7万円~)。",
    ),
    _t(
        "corporate_tax:taishoku_kyutsu",
        "退職給付引当金",
        "corporate_tax",
        _HOJIN,
        ("54", "54-2"),
        _HOJIN_TT,
        ("11-",),
        ("退職給付", "引当金"),
        "退職給付引当金は会計上は計上必須(退職給付会計)。税務上は法人税法54条により損金算入不可、中退共等の外部拠出のみ損金算入。",
    ),
    _t(
        "corporate_tax:risoku_kazei",
        "過大支払利子税制",
        "corporate_tax",
        _SOZEI,
        ("66-5",),
        _HOJIN_TT,
        ("9-5",),
        ("支払利息", "過大支払"),
        "国外関連者への支払利息は租税特別措置法66条の5の2により過大利子税制の対象。EBITDA基準(20%超は損金不算入)。過少資本税制との重複適用は調整。",
    ),
    _t(
        "corporate_tax:gaikoku_zeigaku_kojo",
        "外国税額控除",
        "corporate_tax",
        _HOJIN,
        ("69",),
        _HOJIN_TT,
        ("16-",),
        ("外国税額控除",),
        "外国税額控除は法人税法69条により外国子会社配当益金不算入との選択適用。二重課税排除の手段。控除限度額は国外所得に対する法人税額。",
    ),
    _t(
        "corporate_tax:taxhaven",
        "タックスヘイブン対策税制",
        "corporate_tax",
        _SOZEI,
        ("66-6",),
        _HOJIN_TT,
        ("66-6",),
        ("タックスヘイブン", "外国子会社合算"),
        "タックスヘイブン対策税制(CFC税制)は租税特別措置法66条の6により実効税率20%未満の外国子会社の所得を内国法人に合算課税。経済活動基準で適用除外あり。",
    ),
    _t(
        "corporate_tax:iten_kakaku",
        "移転価格税制",
        "corporate_tax",
        _SOZEI,
        ("66-4",),
        _HOJIN_TT,
        ("66-4",),
        ("移転価格", "独立企業間"),
        "移転価格税制は租税特別措置法66条の4により国外関連者取引について独立企業間価格(arm's length price)で課税。CUP法・RP法・CP法・TNMM・PS法から選択。",
    ),
    _t(
        "corporate_tax:kashidaore",
        "貸倒損失の認定",
        "corporate_tax",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("9-6",),
        ("貸倒損失", "債権放棄"),
        "貸倒損失は法人税基本通達9-6-1〜9-6-3により(1)法律上の貸倒れ、(2)事実上の貸倒れ、(3)形式上の貸倒れ(取引停止後1年経過等)の3類型。",
        "債務者の支払能力認定に争いが残ることが多く、事実上の貸倒れは税務調査で否認されるケースが頻発。",
    ),
    _t(
        "corporate_tax:bonus_kingaku",
        "使用人賞与の損金算入",
        "corporate_tax",
        _HOJIN,
        ("36",),
        _HOJIN_TT,
        ("9-2",),
        ("賞与", "使用人賞与"),
        "使用人賞与は法人税法施行令72条の3により支給予定日到来+全使用人通知済+決算期末1月以内支払なら未払計上可。それ以外は支払時の損金算入。",
    ),
    _t(
        "corporate_tax:syogaku_genka",
        "一括償却資産・少額減価償却",
        "corporate_tax",
        _HOJIN,
        ("31",),
        _HOJIN_TT,
        ("7-1",),
        ("一括償却", "少額減価償却"),
        "20万円未満は施行令133条の2により一括償却資産(3年均等償却)。30万円未満は租税特別措置法67条の5により中小企業特例で即時損金算入(年300万円上限)。",
    ),
    _t(
        "corporate_tax:assyuku",
        "圧縮記帳",
        "corporate_tax",
        _HOJIN,
        ("42", "43", "44", "45"),
        _HOJIN_TT,
        ("10-",),
        ("圧縮記帳", "国庫補助"),
        "圧縮記帳は法人税法42条以下により国庫補助金・保険差益・交換・収用等で取得した固定資産の課税繰延。圧縮損計上で帳簿価額減額。",
    ),
    _t(
        "corporate_tax:zaiko_genka",
        "棚卸資産の評価損",
        "corporate_tax",
        _HOJIN,
        ("33",),
        _HOJIN_TT,
        ("9-1",),
        ("棚卸資産", "評価損"),
        "棚卸資産の評価損は法人税法33条により原則否認。災害・著しい陳腐化・破損等の事実発生時のみ計上可。単に時価下落では認められない。",
    ),
    _t(
        "corporate_tax:kishou",
        "法人税の更正の請求",
        "corporate_tax",
        "law:kokuzeitsusoku",
        ("23",),
        _HOJIN_TT,
        ("16-",),
        ("更正の請求",),
        "更正の請求は国税通則法23条により法定申告期限から5年以内。後発的事由による更正の請求は2月以内(同条2項)。",
    ),
    _t(
        "corporate_tax:kasanzei",
        "加算税の課税要件",
        "corporate_tax",
        "law:kokuzeitsusoku",
        ("65", "66", "68"),
        _HOJIN_TT,
        ("16-",),
        ("加算税", "重加算税"),
        "過少申告加算税は10-15%、無申告加算税は15-20%、重加算税は隠蔽仮装行為で35-40%。更正予知前の自主修正申告は加算税減免。",
    ),
    _t(
        "corporate_tax:saigai_sonshitsu",
        "災害損失欠損金",
        "corporate_tax",
        _HOJIN,
        ("58",),
        _HOJIN_TT,
        ("12-",),
        ("災害損失", "繰戻し"),
        "災害損失欠損金は法人税法58条により10年繰越控除可能。中小法人は1年繰戻し還付も選択可。災害損失の範囲は施行令115条で限定列挙。",
    ),
    _t(
        "corporate_tax:jiko_kabu",
        "出資の払戻し・自己株式",
        "corporate_tax",
        _HOJIN,
        ("24",),
        _HOJIN_TT,
        ("1-3",),
        ("自己株式", "みなし配当"),
        "自己株式取得・資本払戻しは法人税法24条によりみなし配当発生。資本剰余金からの払戻しは資本払戻し+利益配当の合成。",
    ),
    _t(
        "corporate_tax:hoken_haitou",
        "保険金・損害賠償金",
        "corporate_tax",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("2-1",),
        ("保険金", "損害賠償"),
        "受取保険金・損害賠償金は法人税法22条により原則益金算入。被害資産の帳簿価額損金算入で相殺。差益は圧縮記帳の対象(法人税法47条)。",
    ),
    _t(
        "corporate_tax:gaika_kessan",
        "外貨建取引の換算",
        "corporate_tax",
        _HOJIN,
        ("61-8",),
        _HOJIN_TT,
        ("13-2",),
        ("外貨建", "為替差損益"),
        "外貨建資産負債は法人税法61条の8により短期は期末時換算、長期は発生時換算。金銭債権債務は短期長期問わず期末時換算可選択。為替差損益は法人税法上益金損金。",
    ),
    _t(
        "corporate_tax:lease",
        "リース取引の税務",
        "corporate_tax",
        _HOJIN,
        ("64-2",),
        _HOJIN_TT,
        ("12-5",),
        ("リース", "売買取引"),
        "ファイナンスリースは法人税法64条の2により売買取引として処理。リース資産は減価償却+リース債務として認識。",
    ),
    _t(
        "corporate_tax:groupshogai",
        "グループ通算制度",
        "corporate_tax",
        _HOJIN,
        ("64-9",),
        _HOJIN_TT,
        ("12-6",),
        ("グループ通算", "連結納税"),
        "グループ通算制度は法人税法64条の9以下により令和4年4月から開始。完全支配関係(100%親子)の法人グループで損益通算・税額計算を行う。",
    ),
    _t(
        "corporate_tax:hyakuper",
        "100%グループ法人税制",
        "corporate_tax",
        _HOJIN,
        ("61-13", "61-14"),
        _HOJIN_TT,
        ("12-7",),
        ("100%グループ", "完全支配"),
        "完全支配関係グループ法人の譲渡損益・寄附金・受取配当等は法人税法61条の13・25条の2等で課税繰延・益金不算入。",
    ),
    _t(
        "corporate_tax:ryuho_kingaku",
        "特定同族会社の留保金課税",
        "corporate_tax",
        _HOJIN,
        ("67",),
        _HOJIN_TT,
        ("16-",),
        ("特殊支配", "留保金課税"),
        "特定同族会社は法人税法67条により留保金課税(資本金1億円超)。中小法人は除外。配当による所得分散インセンティブを与える制度。",
    ),
    _t(
        "corporate_tax:seimei_hoken",
        "生命保険料の損金算入",
        "corporate_tax",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("9-3",),
        ("生命保険", "保険料"),
        "法人契約の生命保険料は法人税基本通達9-3-4〜9-3-7により解約返戻率に応じた損金算入割合。最高解約返戻率50%超の定期保険は資産計上が必要。",
    ),
    _t(
        "corporate_tax:kenmu_yakuin",
        "使用人兼務役員の判定",
        "corporate_tax",
        _HOJIN,
        ("34",),
        _HOJIN_TT,
        ("9-2",),
        ("使用人兼務役員", "役員"),
        "使用人兼務役員は法人税法施行令71条により副社長・専務・常務等の地位以外の取締役で部長等の使用人職制上の地位を有する者。役員給与の損金算入規制を受けない部分(使用人分賞与)あり。",
    ),
    _t(
        "corporate_tax:miharai_keihi",
        "未払費用の損金算入",
        "corporate_tax",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("2-2",),
        ("未払費用", "債務確定"),
        "未払費用は法人税法22条+法人税基本通達2-2-12により(1)期末までに債務成立、(2)具体的給付原因事実発生、(3)金額合理的算定可能の3要件で損金算入。",
    ),
    _t(
        "corporate_tax:uketori_haitou",
        "受取配当等の益金不算入",
        "corporate_tax",
        _HOJIN,
        ("23",),
        _HOJIN_TT,
        ("3-1",),
        ("受取配当", "益金不算入"),
        "受取配当等は法人税法23条により完全子法人株式100%・関連法人株式50%超・その他株式5%超-50%・非支配目的株式5%以下の4区分。益金不算入割合は100%/100%/50%/20%。",
    ),
    _t(
        "corporate_tax:hojin_nari",
        "個人事業の法人成り",
        "corporate_tax",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("1-1",),
        ("法人成り", "個人事業"),
        "個人事業の法人成りでは資産負債を法人へ譲渡または現物出資。個人側で譲渡所得課税、法人側で取得価額計上。賃借権引継ぎ・営業権評価が争点。",
    ),
    _t(
        "corporate_tax:shoukei",
        "事業承継税制(特例措置)",
        "corporate_tax",
        _SOZEI,
        ("70-7", "70-7-5"),
        _HOJIN_TT,
        ("16-",),
        ("事業承継", "認定承継"),
        "事業承継税制(特例措置)は租税特別措置法70条の7の5以下により中小企業者の代表者が後継者に株式を贈与・相続した場合、対象株式の100%相当の納税猶予・免除。",
    ),
    _t(
        "corporate_tax:shihai_kanken",
        "支配関係の判定",
        "corporate_tax",
        _HOJIN,
        ("2",),
        _HOJIN_TT,
        ("1-1",),
        ("支配関係", "完全支配"),
        "支配関係は法人税法2条12号の7により直接または間接の発行済株式総数50%超保有。完全支配関係は100%。間接保有は連鎖ベースで計算。",
    ),
    _t(
        "corporate_tax:fukutoku",
        "復興特別法人税",
        "corporate_tax",
        "law:chiho-hojin-zei",
        ("9",),
        _HOJIN_TT,
        ("16-",),
        ("復興特別",),
        "復興特別法人税は東日本大震災復興財源確保法により平成24-26年の3年間課税(現在廃止)。現行は地方法人税が法人税額の10.3%。",
    ),
    _t(
        "corporate_tax:zoushi_genshi",
        "増資・減資の税務",
        "corporate_tax",
        _HOJIN,
        ("2",),
        _HOJIN_TT,
        ("1-3",),
        ("増資", "減資"),
        "増資は資本金等の額の増加。減資のうち欠損補填・損失填補は資本金等減額のみで益金課税なし。有償減資は資本払戻しとしてみなし配当発生(法人税法24条)。",
    ),
    _t(
        "corporate_tax:kurinobe",
        "繰延資産の償却",
        "corporate_tax",
        _HOJIN,
        ("32",),
        _HOJIN_TT,
        ("8-",),
        ("繰延資産",),
        "繰延資産は法人税法32条+施行令14条で限定列挙(創立費・開業費・開発費等)。任意償却または5年・効用持続年数で均等償却。20万円未満は即時損金算入可。",
    ),
    _t(
        "corporate_tax:zaiton_shisha",
        "在外子会社・支店の課税",
        "corporate_tax",
        _HOJIN,
        ("69", "69-3"),
        _HOJIN_TT,
        ("16-",),
        ("在外子会社", "外国支店"),
        "在外子会社配当は法人税法23条の2により外国子会社配当益金不算入(95%)。外国支店は法人税法69条により外国税額控除との選択。",
    ),
    _t(
        "corporate_tax:koueki_hojin",
        "公益法人等の課税",
        "corporate_tax",
        _HOJIN,
        ("4",),
        _HOJIN_TT,
        ("16-",),
        ("公益法人", "非営利"),
        "公益法人等は法人税法4条により収益事業に対してのみ法人税課税。収益事業は施行令5条で34業種を限定列挙。認定NPO法人は寄附金優遇あり。",
    ),
    _t(
        "corporate_tax:shisha_kazei",
        "外国法人の課税",
        "corporate_tax",
        _HOJIN,
        ("141",),
        _HOJIN_TT,
        ("16-",),
        ("外国法人", "恒久的施設"),
        "外国法人は法人税法141条により恒久的施設(PE)帰属所得+国内源泉所得が課税対象。PEの認定は租税条約優先。",
    ),
)


_CONSUMPTION_TAX_TOPICS: tuple[Topic, ...] = (
    _t(
        "consumption_tax:shiire_kojo",
        "仕入税額控除の要件",
        "consumption_tax",
        _SHOHI,
        ("30",),
        _SHOHI_TT,
        ("11-1",),
        ("仕入税額控除", "適格請求書"),
        "仕入税額控除は消費税法30条により課税仕入れに対応する消費税額の控除。令和5年10月のインボイス制度開始後は、適格請求書発行事業者からの仕入れに限定。",
        "免税事業者からの仕入れについても、経過措置(80%控除・50%控除)期間中は一部控除が認められる。",
    ),
    _t(
        "consumption_tax:menzei_jigyousha",
        "免税事業者の判定",
        "consumption_tax",
        _SHOHI,
        ("9",),
        _SHOHI_TT,
        ("1-4",),
        ("免税事業者", "基準期間"),
        "免税事業者は消費税法9条により基準期間の課税売上高1000万円以下が要件。ただし特定期間(前事業年度上半期)の課税売上高1000万円超かつ給与等支払額1000万円超の場合は課税事業者。",
    ),
    _t(
        "consumption_tax:invoice_seido",
        "インボイス制度の登録要件",
        "consumption_tax",
        _SHOHI,
        ("57-2", "57-4"),
        _SHOHI_TT,
        ("1-7",),
        ("適格請求書発行事業者", "インボイス", "登録"),
        "適格請求書発行事業者は消費税法57条の2により登録申請。課税事業者であることが登録の前提。免税事業者は課税選択届出と同時または事前に登録申請が必要。",
    ),
    _t(
        "consumption_tax:kansatsu_kazei",
        "簡易課税制度の適用要件",
        "consumption_tax",
        _SHOHI,
        ("37",),
        _SHOHI_TT,
        ("13-1",),
        ("簡易課税", "みなし仕入率"),
        "簡易課税は消費税法37条により基準期間の課税売上高5000万円以下の事業者が選択可能。事業区分(1-6種)ごとのみなし仕入率(90%-40%)で仕入税額控除を算定。",
    ),
    _t(
        "consumption_tax:hikazei_torihiki",
        "非課税取引の範囲",
        "consumption_tax",
        _SHOHI,
        ("6",),
        _SHOHI_TT,
        ("6-1",),
        ("非課税", "土地", "金融"),
        "非課税取引は消費税法6条・別表第一により土地譲渡、有価証券譲渡、利子・保証料、社会保険診療、教育、住宅家賃等が列挙。",
    ),
    _t(
        "consumption_tax:yushutsu_menzei",
        "輸出免税の要件",
        "consumption_tax",
        _SHOHI,
        ("7",),
        _SHOHI_TT,
        ("7-2",),
        ("輸出", "免税"),
        "輸出取引は消費税法7条により0%課税(輸出免税)。輸出許可書等の証明書類保存が要件。仕入税額控除は適用可能で還付対象。",
    ),
    _t(
        "consumption_tax:keigen_zeiritsu",
        "軽減税率(食料品等)",
        "consumption_tax",
        _SHOHI,
        ("29",),
        _SHOHI_TT,
        ("2-",),
        ("軽減税率", "食料品"),
        "軽減税率8%は消費税法29条+別表第一の2により飲食料品(酒類・外食を除く)・新聞(週2回以上発行+定期購読)に適用。標準税率10%との区分が実務上の争点。",
    ),
    _t(
        "consumption_tax:reverse_charge",
        "リバースチャージ方式",
        "consumption_tax",
        _SHOHI,
        ("4-3",),
        _SHOHI_TT,
        ("5-",),
        ("リバースチャージ", "電気通信利用役務"),
        "国外事業者から事業者向け電気通信利用役務の提供を受けた場合、消費税法4条の3により役務受領側に消費税納税義務(リバースチャージ方式)。",
    ),
    _t(
        "consumption_tax:kazei_uriagewariai",
        "課税売上割合の計算",
        "consumption_tax",
        _SHOHI,
        ("30",),
        _SHOHI_TT,
        ("11-",),
        ("課税売上割合", "個別対応"),
        "課税売上割合は消費税法30条により分子=課税売上高、分母=課税+非課税+輸出免税。95%以上+課税売上5億円以下は全額控除、それ以外は個別対応または一括比例。",
    ),
    _t(
        "consumption_tax:kazei_sentaku",
        "課税事業者選択届出",
        "consumption_tax",
        _SHOHI,
        ("9-4",),
        _SHOHI_TT,
        ("1-4",),
        ("課税事業者選択",),
        "課税事業者選択届出書は消費税法9条4項により提出すると2年間継続適用が義務。高額特定資産取得時は3年継続。免税事業者復帰には選択不適用届出書が必要。",
    ),
    _t(
        "consumption_tax:kojin_taiou",
        "個別対応方式と一括比例配分",
        "consumption_tax",
        _SHOHI,
        ("30",),
        _SHOHI_TT,
        ("11-2",),
        ("個別対応", "一括比例"),
        "個別対応方式は課税仕入れを(1)課税売上対応、(2)非課税売上対応、(3)共通対応に区分し、(1)+(3)×課税売上割合を控除。一括比例配分は全仕入×課税売上割合。",
    ),
    _t(
        "consumption_tax:setsugaku_chosei",
        "調整対象固定資産・棚卸資産",
        "consumption_tax",
        _SHOHI,
        ("33", "34", "35"),
        _SHOHI_TT,
        ("12-",),
        ("調整対象", "固定資産"),
        "100万円以上の調整対象固定資産は消費税法33-35条により3年間の課税売上割合変動で調整。免税事業者になる場合の棚卸資産も調整対象。",
    ),
    _t(
        "consumption_tax:tokutei_kikan",
        "特定期間の判定",
        "consumption_tax",
        _SHOHI,
        ("9-2",),
        _SHOHI_TT,
        ("1-4",),
        ("特定期間",),
        "特定期間は消費税法9条の2により前事業年度の上半期。この期間の課税売上高1000万円超かつ給与等支払額1000万円超なら基準期間判定に関わらず課税事業者。",
    ),
    _t(
        "consumption_tax:niwari_tokurei",
        "2割特例(インボイス開始事業者)",
        "consumption_tax",
        _SOZEI,
        ("86-4",),
        _SHOHI_TT,
        ("13-1",),
        ("2割特例", "インボイス"),
        "免税事業者からインボイス登録した小規模事業者は租税特別措置法86条の4により令和5年10月-令和8年9月の間、納付税額を売上税額の2割とできる(2割特例)。",
    ),
    _t(
        "consumption_tax:keiyou_sochi",
        "経過措置(80%控除・50%控除)",
        "consumption_tax",
        _SHOHI,
        ("30",),
        _SHOHI_TT,
        ("11-3",),
        ("経過措置", "80%控除", "50%控除"),
        "免税事業者等からの仕入れは令和5年10月-令和8年9月は80%控除、令和8年10月-令和11年9月は50%控除の経過措置(平28年改正附則52条等)。",
    ),
    _t(
        "consumption_tax:kazei_jiki",
        "資産の譲渡等の時期",
        "consumption_tax",
        _SHOHI,
        ("17",),
        _SHOHI_TT,
        ("9-",),
        ("資産の譲渡", "課税時期"),
        "資産の譲渡等の時期は消費税法17条により資産引渡し時または役務提供完了時。前受金・前払金は対価収受・支払時点では認識しない。",
    ),
    _t(
        "consumption_tax:yunyu_shouhi",
        "輸入消費税",
        "consumption_tax",
        _SHOHI,
        ("47",),
        _SHOHI_TT,
        ("8-",),
        ("輸入消費税", "保税地域"),
        "保税地域から引取られる外国貨物には消費税法4条2項により輸入消費税課税。申告納税は税関で行い、課税仕入れとして仕入税額控除可能。",
    ),
    _t(
        "consumption_tax:kakaku_hyouji",
        "価格表示(総額表示)",
        "consumption_tax",
        _SHOHI,
        ("63",),
        _SHOHI_TT,
        ("18-",),
        ("総額表示", "価格表示"),
        "事業者が消費者に対して行う価格表示は消費税法63条により総額表示が義務(税込)。「消費税は別途」表示は不可。",
    ),
    _t(
        "consumption_tax:shinsetsu_hojin",
        "新設法人・特定新規設立法人",
        "consumption_tax",
        _SHOHI,
        ("12-2", "12-3"),
        _SHOHI_TT,
        ("1-4",),
        ("新設法人", "特定新規"),
        "資本金1000万円以上の新設法人は消費税法12条の2により設立から2年間は課税事業者。特定新規設立法人(特定要件該当)は資本金問わず12条の3により課税事業者。",
    ),
    _t(
        "consumption_tax:kazei_kikan",
        "課税期間の短縮特例",
        "consumption_tax",
        _SHOHI,
        ("19",),
        _SHOHI_TT,
        ("8-",),
        ("課税期間短縮",),
        "課税期間短縮特例は消費税法19条により1月または3月単位を選択。輸出免税で還付を受ける事業者が利用するケースが多い。",
    ),
    _t(
        "consumption_tax:hojikin_zeimu",
        "補助金等の消費税課税関係",
        "consumption_tax",
        _SHOHI,
        ("2",),
        _SHOHI_TT,
        ("5-",),
        ("補助金", "消費税"),
        "補助金は消費税法2条1項8号の対価性がないため不課税。ただし補助金で取得した課税仕入れに係る仕入税額控除には特定収入による調整がある(消費税法60条)。",
    ),
    _t(
        "consumption_tax:digital_service",
        "電気通信利用役務の提供",
        "consumption_tax",
        _SHOHI,
        ("2", "4-3"),
        _SHOHI_TT,
        ("5-",),
        ("電気通信利用役務", "デジタルサービス"),
        "国外事業者からの電気通信利用役務の提供は消費税法2条1項8号の3により事業者向け(リバースチャージ)と消費者向け(国外事業者納税)に区分される。",
    ),
    _t(
        "consumption_tax:tochi_tatemono",
        "土地・建物の譲渡",
        "consumption_tax",
        _SHOHI,
        ("6",),
        _SHOHI_TT,
        ("6-",),
        ("土地", "建物", "非課税"),
        "土地譲渡は消費税法6条+別表第一第1号により非課税。建物譲渡は課税。土地建物一括譲渡では時価按分または合理的方法で区分。",
    ),
    _t(
        "consumption_tax:fudosan_chintai",
        "不動産の貸付",
        "consumption_tax",
        _SHOHI,
        ("6",),
        _SHOHI_TT,
        ("6-",),
        ("家賃", "賃貸"),
        "住宅家賃は消費税法6条+別表第一第13号により非課税。事業用建物の家賃は課税。貸付契約書上の用途記載が判定の基本。",
    ),
    _t(
        "consumption_tax:kanjou_kamoku",
        "勘定科目別の消費税区分",
        "consumption_tax",
        _SHOHI,
        ("4",),
        _SHOHI_TT,
        ("5-",),
        ("勘定科目", "課税区分"),
        "課税仕入れの区分は消費税法4条等により売上・仕入・経費の各勘定科目ごとに(1)課税、(2)非課税、(3)免税、(4)不課税の4区分で判定。",
    ),
    _t(
        "consumption_tax:zaiko_chousei",
        "棚卸資産の調整(免税⇔課税)",
        "consumption_tax",
        _SHOHI,
        ("36",),
        _SHOHI_TT,
        ("12-",),
        ("棚卸資産", "免税"),
        "免税事業者から課税事業者になった場合、消費税法36条により期首在庫の課税仕入れ相当額を仕入税額控除の対象に追加。逆の場合は控除済税額を返戻。",
    ),
    _t(
        "consumption_tax:kyojuu_chintai",
        "居住用賃貸建物の仕入税額控除",
        "consumption_tax",
        _SHOHI,
        ("30",),
        _SHOHI_TT,
        ("11-",),
        ("居住用賃貸建物",),
        "令和2年10月以降、居住用賃貸建物の取得に係る消費税は消費税法30条10項により仕入税額控除不可。ただし3年以内に課税賃貸用転用・課税売上の場合は調整還付。",
    ),
    _t(
        "consumption_tax:syuttyou_ryouhi",
        "出張旅費・通勤手当",
        "consumption_tax",
        _SHOHI,
        ("30",),
        _SHOHI_TT,
        ("11-2",),
        ("出張旅費", "通勤手当"),
        "従業員に支払う出張旅費・通勤手当のうち通常必要と認められる範囲は消費税基本通達11-2-1により給与扱いではなく課税仕入れ。インボイス保存不要。",
    ),
    _t(
        "consumption_tax:gakushi_haraikomi",
        "前払い消費税の控除時期",
        "consumption_tax",
        _SHOHI,
        ("17",),
        _SHOHI_TT,
        ("9-",),
        ("前払", "控除時期"),
        "前払消費税は消費税法17条により役務提供完了時に課税仕入れとして認識。短期前払費用は法人税法上の特例適用でも消費税は役務提供完了時。",
    ),
    _t(
        "consumption_tax:tokutei_shien",
        "特定資産の譲渡等",
        "consumption_tax",
        _SHOHI,
        ("2",),
        _SHOHI_TT,
        ("5-",),
        ("特定資産", "電気通信"),
        "特定資産の譲渡等は消費税法2条1項8号の2・3により電気通信利用役務+特定役務(芸能興行等)。役務受領者側に納税義務(リバースチャージ)。",
    ),
)


_SUBSIDY_TOPICS: tuple[Topic, ...] = (
    _t(
        "subsidy:keizai_gouriseii",
        "補助金交付の経済的合理性",
        "subsidy",
        _CHUSHO,
        ("2", "3"),
        _HOJIN_TT,
        ("4-1",),
        ("補助金", "適正化", "経済合理性"),
        "補助金交付の経済合理性は補助金等適正化法・各省告示に基づき、事業計画の実現可能性・費用対効果・公共性が審査対象。",
    ),
    _t(
        "subsidy:taisho_keihi",
        "補助対象経費の範囲",
        "subsidy",
        _CHUSHO,
        ("2", "4"),
        _HOJIN_TT,
        ("4-2",),
        ("補助対象経費", "対象外"),
        "補助対象経費は公募要領で限定列挙。原則として事業に直接必要な経費(設備費・原材料費・委託費・専門家経費)に限る。経常的経費(人件費・賃料)は除外が一般的。",
    ),
    _t(
        "subsidy:hojo_ritsu",
        "補助率と補助上限",
        "subsidy",
        _CHUSHO,
        ("4",),
        _HOJIN_TT,
        ("4-3",),
        ("補助率", "補助上限"),
        "補助率は中小企業1/2-2/3、小規模事業者2/3が標準。補助上限は事業類型・従業員規模により50万円-1億円の幅。",
    ),
    _t(
        "subsidy:syuekikin_henkan",
        "収益納付・返還",
        "subsidy",
        _CHUSHO,
        ("7",),
        _HOJIN_TT,
        ("4-4",),
        ("収益納付", "返還"),
        "補助金により取得した財産の処分・収益は5年間の制限。事業終了後5年以内に収益が発生した場合、収益納付が必要(補助金等適正化法22条)。",
    ),
    _t(
        "subsidy:fusei_jukyu",
        "不正受給と返還命令",
        "subsidy",
        _CHUSHO,
        ("18",),
        _HOJIN_TT,
        ("4-5",),
        ("不正受給", "返還"),
        "不正受給は補助金等適正化法29条で交付決定取消・返還命令。加算金10.95%/年と、不正利得罪(3年以下懲役)の刑事罰の併科。",
    ),
    _t(
        "subsidy:zeimu_shori",
        "補助金の税務処理",
        "subsidy",
        _HOJIN,
        ("42",),
        _HOJIN_TT,
        ("10-1",),
        ("補助金", "圧縮記帳"),
        "補助金により取得した固定資産は法人税法42条の圧縮記帳の対象。圧縮損計上で課税繰延が可能。直接減額方式または積立金方式を選択。",
    ),
    _t(
        "subsidy:monodukuri",
        "ものづくり補助金",
        "subsidy",
        _CHUSHO,
        ("2",),
        _HOJIN_TT,
        ("4-1",),
        ("ものづくり", "革新"),
        "ものづくり補助金は中小企業庁実施で革新的サービス開発・試作品開発・生産プロセス改善が対象。補助上限750-5000万円、補助率1/2-2/3。",
    ),
    _t(
        "subsidy:itdounyu",
        "IT導入補助金",
        "subsidy",
        _CHUSHO,
        ("2",),
        _HOJIN_TT,
        ("4-2",),
        ("IT導入", "DX"),
        "IT導入補助金は中小企業庁実施で業務効率化IT・インボイス対応・セキュリティ対策・複数社連携IT等の枠あり。補助率1/2-3/4。",
    ),
    _t(
        "subsidy:jizoku_ka",
        "持続化補助金",
        "subsidy",
        _CHUSHO,
        ("2",),
        _HOJIN_TT,
        ("4-3",),
        ("持続化", "小規模事業者"),
        "持続化補助金は商工会議所・商工会経由で小規模事業者の販路開拓・生産性向上が対象。補助上限50-200万円、補助率2/3。",
    ),
    _t(
        "subsidy:saikouchiku",
        "事業再構築補助金",
        "subsidy",
        _CHUSHO,
        ("2",),
        _HOJIN_TT,
        ("4-4",),
        ("事業再構築", "新分野"),
        "事業再構築補助金は中小企業庁実施で新分野展開・事業転換・業種転換・業態転換・事業再編が対象。補助上限100-1.5億円、補助率1/2-3/4。",
    ),
    _t(
        "subsidy:gx",
        "GX関連補助金",
        "subsidy",
        _CHUSHO,
        ("2",),
        _HOJIN_TT,
        ("4-5",),
        ("GX", "脱炭素"),
        "GX関連補助金は環境省・経産省で省エネ設備導入・再エネ導入・燃料転換等が対象。CO2削減量に応じた補助率設定が一般的。",
    ),
    _t(
        "subsidy:saiyou_shien",
        "雇用調整助成金",
        "subsidy",
        _ROUDOU,
        ("62",),
        _HOJIN_TT,
        ("4-1",),
        ("雇用調整", "助成金"),
        "雇用調整助成金は経済上の理由による事業活動縮小時の休業手当の一部助成。中小企業は4/5、大企業は2/3。日額上限あり。",
    ),
    _t(
        "subsidy:tokutei_kunren",
        "人材開発支援助成金",
        "subsidy",
        _ROUDOU,
        ("63",),
        _HOJIN_TT,
        ("4-2",),
        ("人材開発", "教育訓練"),
        "人材開発支援助成金は労働者の教育訓練に係る経費+賃金の一部助成。特定訓練コース・一般訓練コース等で助成率45-75%。",
    ),
    _t(
        "subsidy:kibo_setsubi",
        "省力化投資補助金",
        "subsidy",
        _CHUSHO,
        ("2",),
        _HOJIN_TT,
        ("4-3",),
        ("省力化", "設備投資"),
        "省力化投資補助金は中小企業庁実施でロボット・IoT・AI等の省力化設備導入が対象。補助上限200-1000万円、補助率1/2。",
    ),
    _t(
        "subsidy:jigyo_keizoku",
        "事業継続力強化計画",
        "subsidy",
        _CHUSHO,
        ("50",),
        _HOJIN_TT,
        ("4-4",),
        ("事業継続", "BCP"),
        "事業継続力強化計画認定で防災・減災設備の特別償却(20%)+税額控除+補助金加点が得られる(中小企業強化法50条)。",
    ),
    _t(
        "subsidy:keiei_kakushin",
        "経営革新計画",
        "subsidy",
        _CHUSHO,
        ("9",),
        _HOJIN_TT,
        ("4-1",),
        ("経営革新", "新商品"),
        "経営革新計画承認で政府系金融機関の低利融資・信用保証枠拡大・補助金加点が得られる(中小企業等経営強化法9条)。",
    ),
    _t(
        "subsidy:shoukei_keikaku",
        "経営承継円滑化計画",
        "subsidy",
        "law:engyou-shouzoku",
        ("12",),
        _HOJIN_TT,
        ("4-2",),
        ("経営承継", "事業承継"),
        "経営承継円滑化法に基づく特例承継計画認定で事業承継税制(納税猶予)+遺留分特例+金融支援が利用可能。都道府県知事認定。",
    ),
    _t(
        "subsidy:chiiki_keizai",
        "地域経済牽引事業",
        "subsidy",
        _CHUSHO,
        ("13",),
        _HOJIN_TT,
        ("4-3",),
        ("地域経済", "牽引事業"),
        "地域経済牽引事業計画承認で設備投資の特別償却40%・税額控除4%・地方税減免が利用可能(地域経済牽引事業促進法)。",
    ),
    _t(
        "subsidy:kankoku_kankei",
        "補助金交付の関係法令",
        "subsidy",
        _CHUSHO,
        ("1",),
        _HOJIN_TT,
        ("4-5",),
        ("補助金等適正化",),
        "補助金交付は補助金等適正化法を基本法として各省告示・要綱で運用。交付決定・実績報告・確定検査・財産処分制限の流れ。",
    ),
    _t(
        "subsidy:tokutei_shiryo",
        "事業計画書の作成要件",
        "subsidy",
        _CHUSHO,
        ("2",),
        _HOJIN_TT,
        ("4-1",),
        ("事業計画書",),
        "補助金事業計画書は公募要領で指定された様式・記載事項に従う。実現可能性・公益性・費用対効果・予算積算の合理性が審査対象。",
    ),
    _t(
        "subsidy:hojokin_kazei",
        "補助金の益金算入時期",
        "subsidy",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("10-",),
        ("補助金", "益金算入"),
        "補助金は法人税法22条+法人税基本通達2-1-42により交付決定通知のあった日の属する事業年度の益金算入。圧縮記帳と組合せて課税繰延可能。",
    ),
    _t(
        "subsidy:zaikoku_houjikin",
        "在国子会社への補助金",
        "subsidy",
        _CHUSHO,
        ("4",),
        _HOJIN_TT,
        ("4-2",),
        ("在国子会社", "外資"),
        "外資系子会社も国内法人として補助金受給可能(外資規制対象業種を除く)。外為法上の事前届出は補助金交付と別の手続。",
    ),
    _t(
        "subsidy:sentaku_seido",
        "重複申請の禁止",
        "subsidy",
        _CHUSHO,
        ("4",),
        _HOJIN_TT,
        ("4-3",),
        ("重複申請", "排他"),
        "同一事業内容・同一経費に対する複数補助金の重複申請は補助金等適正化法・各公募要領により原則禁止。違反は不正受給扱い。",
    ),
    _t(
        "subsidy:saitaku_kekka",
        "採択通知後の手続",
        "subsidy",
        _CHUSHO,
        ("6",),
        _HOJIN_TT,
        ("4-4",),
        ("採択", "交付申請"),
        "採択通知後は交付申請書を提出し、補助金等適正化法6条の交付決定を待つ。発注・契約は交付決定後でないと補助対象外となる。",
    ),
    _t(
        "subsidy:jisseki_houkoku",
        "実績報告と確定検査",
        "subsidy",
        _CHUSHO,
        ("14",),
        _HOJIN_TT,
        ("4-5",),
        ("実績報告", "確定検査"),
        "事業終了後30日以内または翌年度4月10日いずれか早い日までに実績報告書提出。補助金等適正化法14条の確定検査で補助金額確定。",
    ),
    _t(
        "subsidy:zaisan_shobun",
        "財産処分制限期間",
        "subsidy",
        _CHUSHO,
        ("22",),
        _HOJIN_TT,
        ("4-1",),
        ("財産処分",),
        "補助金で取得した50万円以上の財産は補助金等適正化法22条+耐用年数等を考慮した処分制限期間内は無断処分不可。",
    ),
    _t(
        "subsidy:kasanetorikomi",
        "ローカルベンチマーク",
        "subsidy",
        _CHUSHO,
        ("13",),
        _HOJIN_TT,
        ("4-2",),
        ("ローカルベンチマーク",),
        "ローカルベンチマーク(ロカベン)は経産省が定める企業健全性評価指標。財務6指標+商流非財務20項目で構成、補助金加点対象。",
    ),
    _t(
        "subsidy:tokutei_riyou",
        "補助金の使途制限",
        "subsidy",
        _CHUSHO,
        ("11",),
        _HOJIN_TT,
        ("4-3",),
        ("使途制限",),
        "補助金は補助金等適正化法11条により交付目的に従って使用。目的外使用は返還命令の対象。",
    ),
    _t(
        "subsidy:zeimu_chosa",
        "補助金関連の税務調査",
        "subsidy",
        _HOJIN,
        ("22",),
        _HOJIN_TT,
        ("10-",),
        ("税務調査", "補助金"),
        "補助金事業終了後の税務調査では補助金益金算入時期・圧縮記帳・補助対象経費の損金算入が論点。証憑保存7年間が前提。",
    ),
    _t(
        "subsidy:hokoshou_kondan",
        "補助事業者の説明会",
        "subsidy",
        _CHUSHO,
        ("3",),
        _HOJIN_TT,
        ("4-4",),
        ("説明会", "事業者"),
        "補助金公募開始時の説明会出席で公募要領理解+質疑応答の機会。説明会資料は補助事業の解釈ガイダンスとして重要。",
    ),
)


_LABOR_TOPICS: tuple[Topic, ...] = (
    _t(
        "labor:rodo_jikan",
        "労働時間の上限規制",
        "labor",
        _ROUDOU,
        ("32", "36"),
        _HOJIN_TT,
        ("9-2",),
        ("労働時間", "36協定"),
        "労働時間は労基法32条で原則週40時間・1日8時間。36協定締結・届出により時間外労働が可能。上限は原則月45時間・年360時間、特別条項で年720時間まで。",
    ),
    _t(
        "labor:saburoku_kyotei",
        "36協定の締結要件",
        "labor",
        _ROUDOU,
        ("36",),
        _HOJIN_TT,
        ("9-2",),
        ("36協定", "労使協定"),
        "36協定は労基法36条により事業場ごとに労働者の過半数代表との書面協定が必要。労基署届出で時間外労働の上限規制を緩和。",
    ),
    _t(
        "labor:kaiko_yokoku",
        "解雇予告",
        "labor",
        _ROUDOU,
        ("20",),
        _HOJIN_TT,
        ("9-2",),
        ("解雇", "予告"),
        "解雇は労基法20条により30日前予告または30日分以上の予告手当の支払が必要。天災事変等のやむを得ない事由+労基署認定で適用除外。",
    ),
    _t(
        "labor:nenji_kyuka",
        "年次有給休暇",
        "labor",
        _ROUDOU,
        ("39",),
        _HOJIN_TT,
        ("9-2",),
        ("年次有給休暇", "有給"),
        "年次有給休暇は労基法39条により6ヶ月継続勤務+8割出勤で10日付与。勤続年数で最大20日。5日の時季指定義務(年5日以上の取得義務)が使用者に課される。",
    ),
    _t(
        "labor:warimasi_chingin",
        "割増賃金の計算",
        "labor",
        _ROUDOU,
        ("37",),
        _HOJIN_TT,
        ("9-2",),
        ("割増賃金", "残業代"),
        "割増賃金は労基法37条により時間外25%以上、深夜25%以上、休日35%以上。月60時間超の時間外は50%以上(中小企業は令和5年4月から)。",
    ),
    _t(
        "labor:saiyou_keiyaku",
        "労働契約の締結",
        "labor",
        _ROUDOU,
        ("15",),
        _HOJIN_TT,
        ("9-2",),
        ("労働契約", "労働条件通知書"),
        "労働契約締結時は労基法15条により労働条件の明示が義務。書面交付事項(賃金・労働時間・契約期間等)+任意事項(退職手当・賞与等)に区分。",
    ),
    _t(
        "labor:kaiko_seitou",
        "解雇の正当事由",
        "labor",
        "law:roudou-keiyaku",
        ("16",),
        _HOJIN_TT,
        ("9-2",),
        ("解雇", "正当事由"),
        "解雇は労働契約法16条により客観的合理的理由+社会通念上の相当性が必要(解雇権濫用法理)。判例で4要件(整理解雇)・能力不足・規律違反等の類型化。",
    ),
    _t(
        "labor:seikishichi_kintou",
        "正規・非正規均等待遇",
        "labor",
        "law:pertime-hou",
        ("8", "9"),
        _HOJIN_TT,
        ("9-2",),
        ("均等待遇", "非正規"),
        "パートタイム・有期雇用労働法8-9条により正規・非正規労働者の不合理な待遇差禁止。同一労働同一賃金ガイドラインで具体的指針。",
    ),
    _t(
        "labor:haken_keiyaku",
        "労働者派遣の規制",
        "labor",
        "law:roudousha-haken",
        ("26",),
        _HOJIN_TT,
        ("9-2",),
        ("派遣", "労働者派遣"),
        "労働者派遣は労働者派遣法26条以下により派遣禁止業務(建設・警備・港湾運送・医療等)+期間制限(原則3年)+均等待遇義務。",
    ),
    _t(
        "labor:kosheo_kyoutei",
        "就業規則の作成義務",
        "labor",
        _ROUDOU,
        ("89", "90"),
        _HOJIN_TT,
        ("9-2",),
        ("就業規則",),
        "常時10人以上の労働者を使用する事業場は労基法89条により就業規則作成+労基署届出義務。労基法90条により過半数代表の意見聴取必須。",
    ),
    _t(
        "labor:tobasokuchin",
        "最低賃金",
        "labor",
        "law:saitei-chingin",
        ("4",),
        _HOJIN_TT,
        ("9-2",),
        ("最低賃金",),
        "最低賃金は最低賃金法4条により都道府県別+産業別。地域別最低賃金は毎年10月改定。違反は罰金50万円以下。",
    ),
    _t(
        "labor:rourei_juujitsu",
        "高齢者雇用確保措置",
        "labor",
        "law:koureisha-koyou",
        ("9",),
        _HOJIN_TT,
        ("9-2",),
        ("高齢者雇用", "70歳"),
        "高年齢者雇用安定法9条により65歳までの雇用確保措置義務。令和3年4月から70歳までの就業確保措置努力義務追加。",
    ),
    _t(
        "labor:ikuji_kaigo",
        "育児・介護休業",
        "labor",
        "law:ikuji-kaigo",
        ("5", "11"),
        _HOJIN_TT,
        ("9-2",),
        ("育児休業", "介護休業"),
        "育児・介護休業法5・11条により1歳まで(最長2歳)育児休業+93日通算介護休業の権利。雇用保険から育児休業給付金・介護休業給付金。",
    ),
    _t(
        "labor:kintou_seibetsu",
        "男女雇用機会均等",
        "labor",
        "law:kintou-hou",
        ("5", "6"),
        _HOJIN_TT,
        ("9-2",),
        ("均等法", "性別"),
        "男女雇用機会均等法5-6条により採用・配置・昇進・賃金等での性別差別禁止。妊娠出産関連の不利益取扱いも禁止。",
    ),
    _t(
        "labor:kanshi_gimu",
        "安全配慮義務",
        "labor",
        "law:roudou-keiyaku",
        ("5",),
        _HOJIN_TT,
        ("9-2",),
        ("安全配慮", "労災"),
        "労働契約法5条により使用者は労働者の生命・身体等の安全配慮義務。違反は債務不履行・不法行為責任(電通事件等で確立)。",
    ),
    _t(
        "labor:pawahara",
        "ハラスメント防止措置",
        "labor",
        "law:roudou-shisaku",
        ("30-2",),
        _HOJIN_TT,
        ("9-2",),
        ("パワハラ", "ハラスメント"),
        "労働施策総合推進法30条の2(令和4年4月中小企業適用)によりパワーハラスメント防止措置義務。事業主の方針明示+相談体制整備+発生時対応。",
    ),
    _t(
        "labor:rousai_hoken",
        "労災保険の適用",
        "labor",
        "law:rousai-hoken",
        ("3",),
        _HOJIN_TT,
        ("9-2",),
        ("労災保険",),
        "労災保険は労災保険法3条により全労働者強制適用(役員等を除く)。業務上負傷・疾病・障害・死亡が給付対象。",
    ),
    _t(
        "labor:koyou_hoken",
        "雇用保険の被保険者",
        "labor",
        "law:koyou-hoken",
        ("4",),
        _HOJIN_TT,
        ("9-2",),
        ("雇用保険",),
        "雇用保険は週20時間以上+31日以上雇用見込みで強制加入(雇用保険法4条)。65歳以上は高年齢被保険者、短時間労働者は短時間被保険者。",
    ),
    _t(
        "labor:syakaihouken",
        "社会保険の適用基準",
        "labor",
        "law:kenkou-hoken",
        ("3",),
        _HOJIN_TT,
        ("9-2",),
        ("社会保険", "適用拡大"),
        "社会保険(健保・厚生年金)は健康保険法3条+厚生年金保険法9条により法人事業所は強制適用。短時間労働者は週20時間以上+月8.8万円以上+2か月超雇用見込で適用拡大。",
    ),
    _t(
        "labor:tenkin_haichi",
        "配置転換・出向",
        "labor",
        "law:roudou-keiyaku",
        ("3",),
        _HOJIN_TT,
        ("9-2",),
        ("配置転換", "出向"),
        "配置転換は労働契約法3条+判例(東亜ペイント事件)により業務上必要性+不当な動機・目的なし+労働者の通常甘受すべき程度の不利益で適法。",
    ),
)


_COMMERCE_TOPICS: tuple[Topic, ...] = (
    _t(
        "commerce:yakuin_sennin",
        "役員の選任",
        "commerce",
        _KAISHA,
        ("329",),
        _HOJIN_TT,
        ("9-2",),
        ("役員選任", "取締役"),
        "役員の選任は会社法329条により株主総会の普通決議。取締役は最低1名(取締役会設置会社は3名以上)。監査役設置会社は監査役の選任も普通決議。",
    ),
    _t(
        "commerce:setsuritsu_youken",
        "株式会社設立の要件",
        "commerce",
        _KAISHA,
        ("25", "26", "27"),
        _HOJIN_TT,
        ("1-1",),
        ("設立", "定款"),
        "株式会社設立は会社法25条以下により定款作成・公証人認証・出資履行・設立登記が要件。最低資本金規制廃止後は1円から設立可能。",
    ),
    _t(
        "commerce:zoushi",
        "増資・募集株式の発行",
        "commerce",
        _KAISHA,
        ("199",),
        _HOJIN_TT,
        ("1-2",),
        ("増資", "募集株式"),
        "増資は会社法199条以下により募集事項決定(原則株主総会特別決議)→募集→引受→出資履行→変更登記。公開会社は取締役会決議で募集可能(199条2項)。",
    ),
    _t(
        "commerce:gappei",
        "合併の手続",
        "commerce",
        _KAISHA,
        ("748", "783"),
        _HOJIN_TT,
        ("1-4",),
        ("合併", "吸収合併"),
        "合併は会社法748条以下により吸収合併と新設合併。合併契約締結→株主総会特別決議→債権者保護手続→合併登記の流れ。簡易合併・略式合併で総会省略可能な場合あり。",
    ),
    _t(
        "commerce:kabu_joto_seigen",
        "株式譲渡制限",
        "commerce",
        _KAISHA,
        ("139",),
        _HOJIN_TT,
        ("1-3",),
        ("譲渡制限", "承認"),
        "譲渡制限株式の譲渡は会社法139条以下により承認機関(取締役会または株主総会)の承認が必要。不承認の場合は会社または指定買取人による買取請求が可能。",
    ),
    _t(
        "commerce:torishimariyaku_meibo",
        "取締役の任期",
        "commerce",
        _KAISHA,
        ("332",),
        _HOJIN_TT,
        ("9-2",),
        ("取締役任期", "選任"),
        "取締役の任期は会社法332条により原則2年(選任後2年以内に終了する事業年度のうち最終のものに関する定時総会終結時まで)。非公開会社は定款で最長10年まで延長可能。",
    ),
    _t(
        "commerce:bunkatsu_shori",
        "会社分割の手続",
        "commerce",
        _KAISHA,
        ("757", "762"),
        _HOJIN_TT,
        ("1-4",),
        ("会社分割", "分社"),
        "会社分割は会社法757条以下により吸収分割と新設分割。分割契約・計画書→株主総会特別決議→債権者保護手続→分割登記の流れ。労働契約の承継は労働契約承継法に基づく。",
    ),
    _t(
        "commerce:teikan_henko",
        "定款変更の手続",
        "commerce",
        _KAISHA,
        ("466",),
        _HOJIN_TT,
        ("1-1",),
        ("定款変更",),
        "定款変更は会社法466条により株主総会の特別決議(議決権の過半数+出席株主議決権の2/3以上)。発行可能株式総数等の重要事項変更を含む。",
    ),
    _t(
        "commerce:torishimariyaku_kaigi",
        "取締役会の決議",
        "commerce",
        _KAISHA,
        ("369",),
        _HOJIN_TT,
        ("9-2",),
        ("取締役会",),
        "取締役会決議は会社法369条により取締役の過半数出席+出席取締役の過半数で成立。特別利害関係取締役は議決権行使不可。",
    ),
    _t(
        "commerce:kanshakuyaku",
        "監査役の権限・職務",
        "commerce",
        _KAISHA,
        ("381", "382"),
        _HOJIN_TT,
        ("9-2",),
        ("監査役",),
        "監査役は会社法381条以下により取締役の職務執行を監査(業務監査+会計監査)。違法行為差止請求権(385条)+取締役会への報告義務(382条)。",
    ),
    _t(
        "commerce:dairi_kosin",
        "代表取締役の選定",
        "commerce",
        _KAISHA,
        ("362",),
        _HOJIN_TT,
        ("9-2",),
        ("代表取締役",),
        "代表取締役は会社法362条により取締役会設置会社では取締役会が選定。"
        "非取締役会設置会社は定款・株主総会・取締役の互選から選定可能(会社法349条)。",
    ),
    _t(
        "commerce:kabu_haitouki",
        "剰余金の配当",
        "commerce",
        _KAISHA,
        ("454", "461"),
        _HOJIN_TT,
        ("1-3",),
        ("剰余金配当",),
        "剰余金配当は会社法454条により株主総会決議(または取締役会)で実施。会社法461条の分配可能額の範囲内に限られる(債権者保護)。",
    ),
    _t(
        "commerce:kaikei_kansa",
        "会計監査人の設置",
        "commerce",
        _KAISHA,
        ("327", "337"),
        _HOJIN_TT,
        ("9-2",),
        ("会計監査人",),
        "大会社(資本金5億円以上または負債200億円以上)は会社法328条により会計監査人設置義務。公認会計士または監査法人が務める。",
    ),
    _t(
        "commerce:syadan_houjin",
        "持分会社の設立",
        "commerce",
        _KAISHA,
        ("575", "576"),
        _HOJIN_TT,
        ("1-1",),
        ("合同会社", "持分会社"),
        "合同会社・合名会社・合資会社の持分会社は会社法575条以下により定款作成+設立登記で成立。出資・損益分配・業務執行が自由設計可能。",
    ),
    _t(
        "commerce:torishimariyaku_kaisan",
        "取締役の解任",
        "commerce",
        _KAISHA,
        ("339",),
        _HOJIN_TT,
        ("9-2",),
        ("取締役解任",),
        "取締役解任は会社法339条により株主総会の普通決議でいつでも可能。正当事由なき解任は損害賠償請求の対象(同条2項)。",
    ),
    _t(
        "commerce:kaisan_seisan",
        "解散・清算",
        "commerce",
        _KAISHA,
        ("471", "475"),
        _HOJIN_TT,
        ("1-5",),
        ("解散", "清算"),
        "解散事由は会社法471条で限定列挙(株主総会の決議・合併・破産等)。"
        "清算は475条以下により清算人選任→残余財産処分→清算結了登記の流れ。",
    ),
    _t(
        "commerce:soshou_dairininni",
        "株主代表訴訟",
        "commerce",
        _KAISHA,
        ("847",),
        _HOJIN_TT,
        ("9-2",),
        ("株主代表訴訟",),
        "株主代表訴訟は会社法847条により6か月以上引き続き株式を有する株主が役員の責任追及のため会社に代わって提訴可能。提訴前60日の請求要件。",
    ),
    _t(
        "commerce:torishimariyaku_zeninn",
        "取締役の責任",
        "commerce",
        _KAISHA,
        ("423", "428"),
        _HOJIN_TT,
        ("9-2",),
        ("取締役責任",),
        "取締役は会社法423条により任務懈怠で会社に対し損害賠償責任。経営判断原則で過失認定は限定的。総株主の同意で免除可能(424条)。",
    ),
    _t(
        "commerce:tokubetsu_riyousha",
        "特別利害関係取締役",
        "commerce",
        _KAISHA,
        ("369",),
        _HOJIN_TT,
        ("9-2",),
        ("特別利害関係",),
        "特別利害関係を有する取締役は会社法369条2項により取締役会で議決権行使不可。取引相手方・直接的個人利害関係者が該当。",
    ),
    _t(
        "commerce:rishiyaku_kaiseki",
        "利益相反取引",
        "commerce",
        _KAISHA,
        ("356",),
        _HOJIN_TT,
        ("9-2",),
        ("利益相反", "競業避止"),
        "利益相反取引・競業取引は会社法356条により取締役会承認(非取締役会設置会社は株主総会承認)+事後報告が必要。",
    ),
    _t(
        "commerce:kabu_buntou",
        "株式の併合・分割",
        "commerce",
        _KAISHA,
        ("180", "183"),
        _HOJIN_TT,
        ("1-3",),
        ("株式分割", "株式併合"),
        "株式分割は会社法183条により取締役会決議(非取締役会設置会社は株主総会普通決議)。"
        "株式併合は180条により株主総会特別決議+発行可能株式総数変更が必要。",
    ),
    _t(
        "commerce:syokuyou_kabushiki",
        "種類株式の発行",
        "commerce",
        _KAISHA,
        ("108",),
        _HOJIN_TT,
        ("1-3",),
        ("種類株式",),
        "種類株式は会社法108条により(1)剰余金配当(2)残余財産分配(3)議決権制限(4)譲渡制限(5)取得請求権(6)取得条項(7)全部取得条項(8)拒否権(9)役員選任権の9類型。",
    ),
    _t(
        "commerce:atojiban",
        "事業譲渡",
        "commerce",
        _KAISHA,
        ("467",),
        _HOJIN_TT,
        ("1-4",),
        ("事業譲渡",),
        "事業の全部または重要部分の譲渡は会社法467条により株主総会特別決議が必要。反対株主は株式買取請求権(469条)。",
    ),
    _t(
        "commerce:nin_i_kanko",
        "任意買取請求",
        "commerce",
        _KAISHA,
        ("116", "469"),
        _HOJIN_TT,
        ("1-3",),
        ("買取請求",),
        "株式買取請求は反対株主の組織再編・事業譲渡・定款変更時の救済措置(会社法116・469条)。公正な価格で会社が買取り。",
    ),
    _t(
        "commerce:joushou_houkoku",
        "事業報告書の作成",
        "commerce",
        _KAISHA,
        ("435", "438"),
        _HOJIN_TT,
        ("9-2",),
        ("事業報告書",),
        "事業報告は会社法435条により計算書類とともに作成・取締役会承認・定時株主総会報告(438条)が必要。",
    ),
    _t(
        "commerce:kessan_koukoku",
        "決算公告",
        "commerce",
        _KAISHA,
        ("440",),
        _HOJIN_TT,
        ("9-2",),
        ("決算公告",),
        "株式会社は会社法440条により定時株主総会後遅滞なく貸借対照表の公告義務。官報・日刊新聞・電子公告から選択。",
    ),
    _t(
        "commerce:kabu_meibo",
        "株主名簿の備置",
        "commerce",
        _KAISHA,
        ("125",),
        _HOJIN_TT,
        ("9-2",),
        ("株主名簿",),
        "株主名簿は会社法125条により本店に備置義務。株主・債権者の閲覧・謄写請求権あり(同条2項)。",
    ),
    _t(
        "commerce:teisoku_souren",
        "定時株主総会の招集",
        "commerce",
        _KAISHA,
        ("296",),
        _HOJIN_TT,
        ("9-2",),
        ("株主総会", "招集"),
        "定時株主総会は会社法296条により毎事業年度終了後一定の時期に招集。臨時総会は必要に応じて招集(同条2項)。",
    ),
    _t(
        "commerce:gizoku_kabu",
        "議決権の代理行使",
        "commerce",
        _KAISHA,
        ("310",),
        _HOJIN_TT,
        ("9-2",),
        ("議決権代理",),
        "議決権は会社法310条により代理人を通じて行使可能。委任状の提出が必要。書面・電磁的記録による議決権行使も可能(298条)。",
    ),
    _t(
        "commerce:kabu_jouto",
        "株式譲渡の効力",
        "commerce",
        _KAISHA,
        ("128", "130"),
        _HOJIN_TT,
        ("1-3",),
        ("株式譲渡",),
        "株式譲渡は会社法128条により株券発行会社では株券交付で効力発生。株主名簿名義書換が会社・第三者対抗要件(130条)。",
    ),
)


def all_topics() -> tuple[Topic, ...]:
    """Concatenate every topic block in deterministic order."""
    return (
        *_CORPORATE_TAX_TOPICS,
        *_CONSUMPTION_TAX_TOPICS,
        *_SUBSIDY_TOPICS,
        *_LABOR_TOPICS,
        *_COMMERCE_TOPICS,
    )


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LawArticleRef:
    """Reference to one am_law_article row for chain citations."""

    article_id: int
    law_canonical_id: str
    article_number: str
    title: str | None
    source_url: str | None


@dataclass(frozen=True)
class JudgmentRef:
    """Reference to one court_decisions row + key_ruling excerpt."""

    unified_id: str
    court: str | None
    decision_date: str | None
    precedent_weight: str
    key_ruling_excerpt: str


@dataclass(frozen=True)
class SaiketsuRef:
    """Reference to one nta_saiketsu row + summary excerpt."""

    saiketsu_id: str
    decision_date: str | None
    tax_type: str | None
    title: str | None
    decision_summary: str | None


def _chain_id_for(topic_id: str, slice_label: str) -> str:
    """Deterministic LRC-<10 hex> chain id derived from (topic, slice)."""
    digest = hashlib.sha256(f"{topic_id}::{slice_label}::v1".encode()).hexdigest()[:10]
    return f"LRC-{digest}"


def _fetch_law_articles(
    am_conn: sqlite3.Connection,
    *,
    law_canonical_id: str,
    article_numbers: Sequence[str],
) -> list[LawArticleRef]:
    """Pull am_law_article rows for the topic anchor."""
    if not article_numbers:
        return []
    placeholders = ",".join("?" for _ in article_numbers)
    cur = am_conn.execute(
        f"""
        SELECT article_id, law_canonical_id, article_number, title, source_url
          FROM am_law_article
         WHERE law_canonical_id = ?
           AND article_number IN ({placeholders})
         ORDER BY article_number_sort
        """,
        (law_canonical_id, *article_numbers),
    )
    return [
        LawArticleRef(
            article_id=int(row[0]),
            law_canonical_id=str(row[1]),
            article_number=str(row[2]),
            title=row[3],
            source_url=row[4],
        )
        for row in cur.fetchall()
    ]


def _fetch_tsutatsu(
    am_conn: sqlite3.Connection,
    *,
    tsutatsu_law_id: str,
    article_prefix: Sequence[str],
    cap: int = 5,
) -> list[LawArticleRef]:
    """Pull am_law_article rows on a law:*-tsutatsu canonical id."""
    if not article_prefix:
        return []
    prefix_clauses: list[str] = []
    params: list[Any] = [tsutatsu_law_id]
    for prefix in article_prefix:
        prefix_clauses.append("article_number LIKE ?")
        params.append(f"{prefix}%")
    where_prefix = " OR ".join(prefix_clauses)
    params.append(cap)
    cur = am_conn.execute(
        f"""
        SELECT article_id, law_canonical_id, article_number, title, source_url
          FROM am_law_article
         WHERE law_canonical_id = ?
           AND ({where_prefix})
         ORDER BY article_number_sort
         LIMIT ?
        """,
        params,
    )
    return [
        LawArticleRef(
            article_id=int(row[0]),
            law_canonical_id=str(row[1]),
            article_number=str(row[2]),
            title=row[3],
            source_url=row[4],
        )
        for row in cur.fetchall()
    ]


def _fetch_judgments(
    jp_conn: sqlite3.Connection,
    *,
    keywords: Sequence[str],
    cap: int = 3,
) -> list[JudgmentRef]:
    """Pull court_decisions rows matching any keyword in key_ruling.

    FTS is intentionally bypassed (the trigram tokenizer over-matches single
    kanji) — substring LIKE on key_ruling is preferred for the small (<1k
    real-text rows) corpus.
    """
    if not keywords:
        return []
    clauses = " OR ".join(["key_ruling LIKE ?" for _ in keywords])
    params: list[Any] = [f"%{kw}%" for kw in keywords]
    params.append(cap)
    cur = jp_conn.execute(
        f"""
        SELECT unified_id, court, decision_date, precedent_weight,
               substr(key_ruling, 1, 240) AS excerpt
          FROM court_decisions
         WHERE key_ruling IS NOT NULL
           AND length(key_ruling) > 50
           AND ({clauses})
         ORDER BY
            CASE precedent_weight
              WHEN 'binding' THEN 1
              WHEN 'persuasive' THEN 2
              ELSE 3
            END,
            decision_date DESC NULLS LAST
         LIMIT ?
        """,
        params,
    )
    return [
        JudgmentRef(
            unified_id=str(row[0]),
            court=row[1],
            decision_date=row[2],
            precedent_weight=str(row[3]),
            key_ruling_excerpt=str(row[4]),
        )
        for row in cur.fetchall()
    ]


def _fetch_saiketsu(
    am_conn: sqlite3.Connection,
    *,
    keywords: Sequence[str],
    cap: int = 2,
) -> list[SaiketsuRef]:
    """Pull nta_saiketsu rows matching any keyword in title/summary."""
    if not keywords:
        return []
    clauses = " OR ".join(["(title LIKE ? OR decision_summary LIKE ?)" for _ in keywords])
    params: list[Any] = []
    for kw in keywords:
        params.extend([f"%{kw}%", f"%{kw}%"])
    params.append(cap)
    cur = am_conn.execute(
        f"""
        SELECT id, decision_date, tax_type, title, decision_summary
          FROM nta_saiketsu
         WHERE ({clauses})
         ORDER BY decision_date DESC NULLS LAST
         LIMIT ?
        """,
        params,
    )
    return [
        SaiketsuRef(
            saiketsu_id=f"NTA-SAI-{int(row[0]):06d}",
            decision_date=row[1],
            tax_type=row[2],
            title=row[3],
            decision_summary=(row[4][:240] if row[4] else None),
        )
        for row in cur.fetchall()
    ]


@dataclass(frozen=True)
class ChainRow:
    """Materialized row, ready for INSERT OR REPLACE."""

    chain_id: str
    topic_id: str
    topic_label: str
    tax_category: str
    premise_law_article_ids: list[int]
    premise_tsutatsu_ids: list[int]
    minor_premise_judgment_ids: list[str]
    conclusion_text: str
    confidence: float
    opposing_view_text: str | None
    citations: dict[str, list[dict[str, Any]]]


def _compose_chain(
    topic: Topic,
    slice_label: str,
    laws: Sequence[LawArticleRef],
    tsutatsu: Sequence[LawArticleRef],
    judgments: Sequence[JudgmentRef],
    saiketsu: Sequence[SaiketsuRef],
) -> ChainRow:
    """Materialize one chain row.

    Confidence rubric (deterministic, pure rule):
      base 0.50
      +0.15 if >=1 law article
      +0.10 if >=1 tsutatsu reference
      +0.10 if >=1 judgment or saiketsu
      +0.05 if slice_label != "反対説の余地" (regular slices)
      cap   0.85 if slice_label == "反対説の余地" or topic.opposing_view_text
    """
    chain_id = _chain_id_for(topic.topic_id, slice_label)
    confidence = 0.50
    if laws:
        confidence += 0.15
    if tsutatsu:
        confidence += 0.10
    if judgments or saiketsu:
        confidence += 0.10
    if slice_label and slice_label != "反対説の余地":
        confidence += 0.05
    confidence = round(min(confidence, 1.0), 4)
    if slice_label == "反対説の余地" or topic.opposing_view_text is not None:
        confidence = min(confidence, 0.85)

    composed_label = f"{topic.label} — {slice_label}" if slice_label else topic.label
    composed_conclusion = (
        f"[{slice_label}] {topic.conclusion_text}" if slice_label else topic.conclusion_text
    )

    citations: dict[str, list[dict[str, Any]]] = {
        "law": [
            {
                "article_id": ref.article_id,
                "law_canonical_id": ref.law_canonical_id,
                "article_number": ref.article_number,
                "title": ref.title,
                "source_url": ref.source_url,
            }
            for ref in laws
        ],
        "tsutatsu": [
            {
                "article_id": ref.article_id,
                "law_canonical_id": ref.law_canonical_id,
                "article_number": ref.article_number,
                "title": ref.title,
                "source_url": ref.source_url,
            }
            for ref in tsutatsu
        ],
        "hanrei": [
            {
                "unified_id": j.unified_id,
                "court": j.court,
                "decision_date": j.decision_date,
                "precedent_weight": j.precedent_weight,
                "key_ruling_excerpt": j.key_ruling_excerpt,
            }
            for j in judgments
        ],
        "saiketsu": [
            {
                "saiketsu_id": s.saiketsu_id,
                "decision_date": s.decision_date,
                "tax_type": s.tax_type,
                "title": s.title,
                "summary": s.decision_summary,
            }
            for s in saiketsu
        ],
    }

    return ChainRow(
        chain_id=chain_id,
        topic_id=topic.topic_id,
        topic_label=composed_label,
        tax_category=topic.tax_category,
        premise_law_article_ids=[ref.article_id for ref in laws],
        premise_tsutatsu_ids=[ref.article_id for ref in tsutatsu],
        minor_premise_judgment_ids=[
            *[j.unified_id for j in judgments],
            *[s.saiketsu_id for s in saiketsu],
        ],
        conclusion_text=composed_conclusion,
        confidence=confidence,
        opposing_view_text=topic.opposing_view_text,
        citations=citations,
    )


def _persist_rows(am_conn: sqlite3.Connection, rows: Iterable[ChainRow]) -> int:
    """Insert-or-replace each chain row."""
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    count = 0
    cur = am_conn.cursor()
    for row in rows:
        cur.execute(
            """
            INSERT OR REPLACE INTO am_legal_reasoning_chain (
                chain_id, topic_id, topic_label, tax_category,
                premise_law_article_ids, premise_tsutatsu_ids,
                minor_premise_judgment_ids,
                conclusion_text, confidence, opposing_view_text,
                citations, computed_by_model, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.chain_id,
                row.topic_id,
                row.topic_label,
                row.tax_category,
                json.dumps(row.premise_law_article_ids, ensure_ascii=False),
                json.dumps(row.premise_tsutatsu_ids, ensure_ascii=False),
                json.dumps(row.minor_premise_judgment_ids, ensure_ascii=False),
                row.conclusion_text,
                row.confidence,
                row.opposing_view_text,
                json.dumps(row.citations, ensure_ascii=False),
                "rule_engine_v1",
                timestamp,
            ),
        )
        count += 1
    am_conn.commit()
    return count


def build_all(*, dry_run: bool = False) -> int:
    """Compose chains for every topic + viewpoint slice.

    Returns the number of chains inserted (or that would be inserted in
    dry-run mode).
    """
    topics = all_topics()
    jp_conn = sqlite3.connect(JPINTEL_DB)
    am_conn = sqlite3.connect(AUTONOMATH_DB)
    jp_conn.row_factory = sqlite3.Row
    am_conn.row_factory = sqlite3.Row
    rows: list[ChainRow] = []
    try:
        for topic in topics:
            laws = _fetch_law_articles(
                am_conn,
                law_canonical_id=topic.law_canonical_id,
                article_numbers=topic.article_numbers,
            )
            tsutatsu = _fetch_tsutatsu(
                am_conn,
                tsutatsu_law_id=topic.tsutatsu_law_id,
                article_prefix=topic.tsutatsu_article_prefix,
            )
            judgments = _fetch_judgments(jp_conn, keywords=topic.keywords)
            saiketsu = _fetch_saiketsu(am_conn, keywords=topic.keywords)
            for slice_label in topic.viewpoint_slices:
                rows.append(
                    _compose_chain(
                        topic,
                        slice_label,
                        laws,
                        tsutatsu,
                        judgments,
                        saiketsu,
                    )
                )
        if dry_run:
            logger.info(
                "[dry-run] composed %d chains across %d topics",
                len(rows),
                len(topics),
            )
            return len(rows)
        count = _persist_rows(am_conn, rows)
        logger.info("persisted %d chains across %d topics", count, len(topics))
        return count
    finally:
        jp_conn.close()
        am_conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compose chains but do not insert",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    count = build_all(dry_run=args.dry_run)
    print(f"chains_composed={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
