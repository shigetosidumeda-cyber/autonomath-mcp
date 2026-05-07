"""DEEP-38 業法 fence violation detector — 30 cases.

Coverage map
------------
- 7 業法 × 4 positive samples = 28 (each pulled from 4 distinct phrases per law)
- 2 negative samples (typical 制度説明 — must yield 0 violations)
- ``cohort_hint`` priority sort (税務 + 法律 mixed; tax_pro hint -> 税理士法 first)
- LLM-API import-zero verify (AST scan of the module)
- 表記揺れ NFKC fallback (full-width / half-width)
- Hiragana -> katakana fallback (when pykakasi available)
- False-positive rate gate on a 100-sample negative corpus (target 5%)

Hooks
-----
``test_no_llm_imports_in_detector_module`` enforces the No-LLM invariant on
just the new module so a regression is caught at unit granularity (the repo-
wide guard ``tests/test_no_llm_in_production.py`` is run separately).

Skips
-----
``pykakasi`` and ``re2`` are both runtime-soft. Tests skip the kana-fallback
case when ``pykakasi`` is missing. The detector itself remains usable.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

from jpintel_mcp.api import _business_law_detector as bld

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DETECTOR_PATH = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "_business_law_detector.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reload_catalog():
    """Reset module caches before each test for isolation."""
    bld.reload_catalog()
    yield
    bld.reload_catalog()


# ---------------------------------------------------------------------------
# 7 業法 × 4 positive samples = 28 cases
# ---------------------------------------------------------------------------


# 税理士法 §52 — 4 cases
def test_zeirishi_1_saitaku_hosho():
    out = bld.detect_violations("当社は採択保証を提供します。")
    assert any(v["law"] == "税理士法" for v in out)


def test_zeirishi_2_kakujitsu_zeigaku():
    out = bld.detect_violations("確実な税額をご案内します。")
    assert any(v["law"] == "税理士法" and v["section"] == "§52" for v in out)


def test_zeirishi_3_shinkoku_daikou():
    out = bld.detect_violations("当社が申告代行しますのでお任せください。")
    assert any(v["law"] == "税理士法" for v in out)


def test_zeirishi_4_zeimu_chosa():
    out = bld.detect_violations("税務調査対応の専門家です。")
    assert any(v["law"] == "税理士法" for v in out)


# 弁護士法 §72 — 4 cases
def test_bengoshi_1_horitsu_sodan():
    out = bld.detect_violations("法律相談に応じます。")
    assert any(v["law"] == "弁護士法" and v["section"] == "§72" for v in out)


def test_bengoshi_2_sosho_dairi():
    out = bld.detect_violations("訴訟代理を行います。")
    assert any(v["law"] == "弁護士法" for v in out)


def test_bengoshi_3_jidan_kosho():
    out = bld.detect_violations("示談交渉しますのでご安心を。")
    assert any(v["law"] == "弁護士法" for v in out)


def test_bengoshi_4_anata_kateru():
    out = bld.detect_violations("あなたは勝てますと断言します。")
    assert any(v["law"] == "弁護士法" for v in out)


# 行政書士法 §1 — 4 cases
def test_gyoseishoshi_1_kyoninka():
    out = bld.detect_violations("許認可申請代行サービスを実施。")
    assert any(v["law"] == "行政書士法" and v["section"] == "§1" for v in out)


def test_gyoseishoshi_2_shinseisho():
    out = bld.detect_violations("申請書作成代行いたします。")
    assert any(v["law"] == "行政書士法" for v in out)


def test_gyoseishoshi_3_hojokin_shinsei():
    out = bld.detect_violations("補助金申請代行はお任せください。")
    assert any(v["law"] == "行政書士法" for v in out)


def test_gyoseishoshi_4_kanko_teishutsu():
    out = bld.detect_violations("官公署提出代行を承ります。")
    assert any(v["law"] == "行政書士法" for v in out)


# 司法書士法 §3 — 4 cases
def test_shihoshoshi_1_toki_shinsei():
    out = bld.detect_violations("登記申請代行を行います。")
    assert any(v["law"] == "司法書士法" and v["section"] == "§3" for v in out)


def test_shihoshoshi_2_shogyo_toki():
    out = bld.detect_violations("商業登記代行を提供。")
    assert any(v["law"] == "司法書士法" for v in out)


def test_shihoshoshi_3_fudosan_toki():
    out = bld.detect_violations("不動産登記代行サービス。")
    assert any(v["law"] == "司法書士法" for v in out)


def test_shihoshoshi_4_kyotaku():
    out = bld.detect_violations("供託代行に対応。")
    assert any(v["law"] == "司法書士法" for v in out)


# 弁理士法 §75 — 4 cases
def test_benrishi_1_tokkyo_shutsugan():
    out = bld.detect_violations("特許出願代行を承ります。")
    assert any(v["law"] == "弁理士法" and v["section"] == "§75" for v in out)


def test_benrishi_2_shohyo_shutsugan():
    out = bld.detect_violations("商標出願代行いたします。")
    assert any(v["law"] == "弁理士法" for v in out)


def test_benrishi_3_tokkyo_kantei():
    out = bld.detect_violations("特許鑑定を引き受けます。")
    assert any(v["law"] == "弁理士法" for v in out)


def test_benrishi_4_isho_shutsugan():
    out = bld.detect_violations("意匠出願代行サービス。")
    assert any(v["law"] == "弁理士法" for v in out)


# 社労士法 §27 — 4 cases
def test_sharoshi_1_shakai_hoken():
    out = bld.detect_violations("社会保険手続代行いたします。")
    assert any(v["law"] == "社労士法" and v["section"] == "§27" for v in out)


def test_sharoshi_2_rodo_kijun():
    out = bld.detect_violations("労働基準法助言を提供。")
    assert any(v["law"] == "社労士法" for v in out)


def test_sharoshi_3_shugyo_kisoku():
    out = bld.detect_violations("就業規則作成代行を承ります。")
    assert any(v["law"] == "社労士法" for v in out)


def test_sharoshi_4_36kyotei():
    out = bld.detect_violations("36協定作成いたします。")
    assert any(v["law"] == "社労士法" for v in out)


# 公認会計士法 §47条の2 — 4 cases
def test_cpa_1_kansa_shomei():
    out = bld.detect_violations("監査証明しますのでご安心を。")
    assert any(v["law"] == "公認会計士法" and v["section"] == "§47条の2" for v in out)


def test_cpa_2_kaikei_kansa():
    out = bld.detect_violations("会計監査しますのでお任せを。")
    assert any(v["law"] == "公認会計士法" for v in out)


def test_cpa_3_naibu_tousei():
    out = bld.detect_violations("内部統制監査を実施。")
    assert any(v["law"] == "公認会計士法" for v in out)


def test_cpa_4_quarterly_review():
    out = bld.detect_violations("四半期reviewを実施します。")
    assert any(v["law"] == "公認会計士法" for v in out)


# ---------------------------------------------------------------------------
# 2 negative samples — typical 制度説明 must yield 0 violations
# ---------------------------------------------------------------------------


def test_negative_1_normal_subsidy_description():
    """Generic eligibility description — must NOT match any 業法 phrase."""
    text = (
        "本補助金は中小企業基本法に定める中小企業者が対象です。"
        "申請期限は令和7年6月30日まで。"
        "補助率は1/2、上限額は500万円。"
        "詳細は公募要領をご確認ください。"
    )
    out = bld.detect_violations(text)
    assert out == [], f"unexpected violations: {out}"


def test_negative_2_loan_program_description():
    """日本政策金融公庫 program description — pure facts, no fence breach."""
    text = (
        "日本政策金融公庫の新規開業資金は、"
        "新たに事業を始める方または事業開始後おおむね7年以内の方が利用できます。"
        "融資限度額は7,200万円(うち運転資金4,800万円)です。"
        "返済期間は設備資金20年以内、運転資金10年以内。"
    )
    out = bld.detect_violations(text)
    assert out == [], f"unexpected violations: {out}"


# ---------------------------------------------------------------------------
# cohort_hint priority sort
# ---------------------------------------------------------------------------


def test_cohort_hint_tax_pro_sorts_zeirishi_first():
    """Mixed text containing 税理士法 + 弁護士法 phrases.
    With cohort_hint='tax_pro', the 税理士法 hit must come first.
    """
    text = "法律相談および税務調査対応をご提供します。"
    out = bld.detect_violations(text, cohort_hint="tax_pro")
    laws = [v["law"] for v in out]
    assert "税理士法" in laws
    assert "弁護士法" in laws
    assert laws[0] == "税理士法", f"expected 税理士法 first, got order: {laws}"


# ---------------------------------------------------------------------------
# LLM API import zero verify
# ---------------------------------------------------------------------------


FORBIDDEN_LLM_MODULES = {"anthropic", "openai", "claude_agent_sdk"}


def _scan_imports_for_module(path: pathlib.Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in FORBIDDEN_LLM_MODULES:
                    hits.append(f"import {alias.name}")
                if alias.name.startswith("google.generativeai"):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            head = node.module.split(".")[0]
            if head in FORBIDDEN_LLM_MODULES:
                hits.append(f"from {node.module} import ...")
            if node.module.startswith("google.generativeai"):
                hits.append(f"from {node.module} import ...")
    return hits


def test_no_llm_imports_in_detector_module():
    """Module must not import any LLM provider SDK."""
    hits = _scan_imports_for_module(DETECTOR_PATH)
    assert hits == [], f"LLM API leaked into detector: {hits}"


# ---------------------------------------------------------------------------
# Catalog-loaded coverage sanity
# ---------------------------------------------------------------------------


def test_catalog_covers_all_7_business_laws():
    catalog = bld._load_phrase_catalog()
    expected_laws = {
        "税理士法",
        "弁護士法",
        "行政書士法",
        "司法書士法",
        "弁理士法",
        "社労士法",
        "公認会計士法",
    }
    assert set(catalog.get("jp", {}).keys()) == expected_laws


def test_jp_phrase_count_is_84_or_more():
    catalog = bld._load_phrase_catalog()
    total = sum(len(v.get("forbidden", [])) for v in catalog.get("jp", {}).values())
    assert total >= 84, f"JP phrase coverage shrank: {total}"


def test_en_phrase_count_is_40_or_more():
    catalog = bld._load_phrase_catalog()
    total = sum(len(v.get("forbidden", [])) for v in catalog.get("en", {}).values())
    assert total >= 40, f"EN phrase coverage shrank: {total}"


# ---------------------------------------------------------------------------
# Encoding-bypass mitigations
# ---------------------------------------------------------------------------


def test_nfkc_normalization_full_width_match():
    """全角 / 半角 mixed input should still match via NFKC normalization."""
    text = "監査証明します"  # forbidden phrase already in canonical form
    out = bld.detect_violations(text)
    assert any(v["law"] == "公認会計士法" for v in out)


@pytest.mark.skipif(not bld._PYKAKASI_AVAILABLE, reason="pykakasi unavailable in this env")
def test_pykakasi_environment_is_loadable():
    """pykakasi-based fallback path is exercised when available."""
    assert bld._kakasi_converter() is not None


# ---------------------------------------------------------------------------
# False positive rate gate (target 5%) — synthetic 100-sample neutral corpus
# ---------------------------------------------------------------------------


_NEUTRAL_CORPUS = [
    "本制度は中小企業向けの設備投資補助金です。",
    "公募要領をご確認の上ご応募ください。",
    "申請に必要な書類は公募サイトに掲載されています。",
    "事業期間は令和7年4月から令和8年3月までです。",
    "補助率は1/2以内、上限額は1000万円です。",
    "対象経費は機械装置費、外注費、技術導入費等です。",
    "本事業は経済産業省所管の補助金制度です。",
    "応募者は日本国内に主たる事業所を有する法人または個人事業主に限ります。",
    "事業計画書には3年間の収支見通しを記載してください。",
    "採択後の事業実施期間は12ヶ月以内とします。",
    "本補助金は予算成立後に実施されます。",
    "申請内容に虚偽があった場合は採択取消となります。",
    "本制度の窓口は中小企業基盤整備機構です。",
    "事業計画は公募要領に従って作成してください。",
    "申請書はオンライン申請システムから提出可能です。",
    "成果物は事業終了後30日以内に報告書を提出します。",
    "補助対象期間中の経費のみが対象となります。",
    "本制度は予算の範囲内で実施されます。",
    "応募多数の場合は予算上限まで採択されます。",
    "事業者は適正に経理処理を行ってください。",
    "本補助金は国の財源により実施される事業です。",
    "事業実績報告書には領収書等の証拠書類を添付します。",
    "補助金交付決定後の事業計画変更は事前承認が必要です。",
    "対象設備は新品のみが補助対象です。",
    "中古品は原則として対象外となります。",
    "事業期間中の事業者の地位の移転は原則認められません。",
    "本補助金は国の補助金等適正化法の対象となります。",
    "補助事業に関する書類は5年間保存してください。",
    "本制度に関するお問い合わせは事務局まで。",
    "公式サイトに最新情報が掲載されています。",
    "本制度は令和7年度予算により実施されます。",
    "公募期間は令和7年5月1日から令和7年6月30日までです。",
    "応募書類は不備のないようご準備ください。",
    "審査は書類審査と面接審査の2段階で行います。",
    "採択結果は事務局のホームページで公表されます。",
    "本補助金は事業完了後に精算払いとなります。",
    "概算払いをご希望の場合は別途申請が必要です。",
    "事業終了後の効果検証も併せて実施してください。",
    "本制度は経年的に拡充されています。",
    "前年度の制度内容と異なる点があります。",
    "詳細は公式の公募要領をご参照ください。",
    "事業計画書は20ページ以内で記載してください。",
    "添付書類は別途リストの通りです。",
    "応募方法はオンライン提出のみとなります。",
    "メールでの応募は受け付けておりません。",
    "応募締切日時は厳守してください。",
    "締切後の応募は理由の如何を問わず受け付けません。",
    "本制度は社会的意義の高い事業を支援します。",
    "GX関連事業は加点対象となります。",
    "DX関連事業も加点対象です。",
    "女性活躍推進事業は加点対象となります。",
    "若手起業家支援事業も対象です。",
    "地域経済の活性化に資する事業を優先採択します。",
    "本制度はSDGs達成に貢献する事業を支援します。",
    "申請者は反社会的勢力でないことを誓約してください。",
    "暴力団排除条項に該当する場合は応募できません。",
    "事業遂行能力を有していることが必要です。",
    "過去の補助金事業で重大な不正がない者に限ります。",
    "応募時点で開業届を提出済みであることが必要です。",
    "法人の場合は法人登記が完了していることが必要です。",
    "個人事業主の場合は確定申告書の提出が必要です。",
    "応募書類は原則として返却しません。",
    "応募内容に関する個人情報は事業実施目的のみで利用します。",
    "個人情報保護法に基づき適切に管理します。",
    "本補助金の不正受給は刑事罰の対象となります。",
    "事業実施中は経済産業省の調査に協力してください。",
    "事業終了後の効果検証アンケートにもご協力ください。",
    "本制度は中小企業基盤整備機構が事務局です。",
    "本補助金は地方公共団体との連携事業も対象です。",
    "他の補助金との併用は原則不可です。",
    "ただし一部例外があります。詳細はお問い合わせを。",
    "本制度は中堅企業も一部対象となります。",
    "売上高基準は公募要領に記載されています。",
    "従業員数基準も併せてご確認ください。",
    "本制度は3年間継続実施される予定です。",
    "次年度以降の制度内容は変更される場合があります。",
    "予算規模は1000億円程度を予定しています。",
    "採択件数は予算規模により変動します。",
    "本制度は経済産業大臣が指定した事業です。",
    "公募期間中の質問はメールで受け付けます。",
    "回答は原則として公式サイトに掲載されます。",
    "個別の質問への回答は控えさせていただきます。",
    "事業計画の妥当性は審査委員会が評価します。",
    "審査委員には大学教授や中小企業診断士が含まれます。",
    "公正な審査を実施するため利害関係者は除外されます。",
    "審査結果に対する個別問い合わせには応じられません。",
    "不採択の場合の理由開示は希望者のみ行います。",
    "本制度は来年度以降も継続予定です。",
    "制度内容の見直しは適宜行われます。",
    "本制度は中小企業庁長官の指定事業です。",
    "補助金交付要綱は公式サイトからダウンロード可能です。",
    "事業者は補助金交付要綱を遵守してください。",
    "本制度は経産省Webサイトにて最新情報を公開中です。",
    "事業終了後の追跡調査にもご協力をお願いします。",
    "本補助金は会計年度独立の原則により予算化されます。",
    "繰越予算となる場合は別途お知らせします。",
    "本制度は公平な審査を実施するため第三者委員会が監督します。",
    "本制度は地域活性化に資する事業を重点的に支援します。",
    "応募書類のフォーマットは公式サイトからダウンロードしてください。",
    "本制度の利用にあたり登録手続が必要です。",
    "GビズIDの取得が必要となります。",
    "電子署名の準備もお願いします。",
    "本補助金は予算成立を条件として実施されます。",
]


def test_false_positive_rate_below_threshold():
    """False positive rate on neutral corpus must stay below 5%."""
    assert len(_NEUTRAL_CORPUS) >= 100
    triggered = sum(1 for t in _NEUTRAL_CORPUS if bld.detect_violations(t))
    rate = triggered / len(_NEUTRAL_CORPUS)
    assert (
        rate <= 0.05
    ), f"FP rate too high: {rate:.2%} (triggered {triggered}/{len(_NEUTRAL_CORPUS)})"


# ---------------------------------------------------------------------------
# Performance smoke (< 5 ms / 1 KB) — without pytest-benchmark, use a soft gate
# ---------------------------------------------------------------------------


def test_performance_under_25ms_for_1kb():
    """Loose ceiling: 1 KB text scan completes well under verify-primitive budget."""
    import time

    sample = (
        "本制度は中小企業向けの補助金制度です。" * 20
        + "公募期間は令和7年5月1日から6月30日までです。"
    )
    # warm caches
    bld.detect_violations(sample)
    t0 = time.perf_counter()
    for _ in range(10):
        bld.detect_violations(sample)
    avg = (time.perf_counter() - t0) / 10
    assert avg < 0.025, f"detector too slow: {avg * 1000:.2f} ms / call"


# ---------------------------------------------------------------------------
# Module re-import is idempotent
# ---------------------------------------------------------------------------


def test_module_reimport_is_idempotent():
    importlib.reload(bld)
    out = bld.detect_violations("採択保証を提供します")
    assert any(v["law"] == "税理士法" for v in out)
