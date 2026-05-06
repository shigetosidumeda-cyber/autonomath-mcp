"""Tests for scripts/etl/ingest_jfc_loan_scaffold.py.

Pure-parser tests against an inline HTML fixture mirroring the structure of
JFC product pages on www.jfc.go.jp. NO network access (the script's
`--no-net` mode emits empty CSVs; the real coverage is the parser, since
that is where the three-axis normalisation is enforced).

Why these tests matter:
    * Migration 013 (`scripts/migrations/013_loan_risk_structure.sql`)
      forbids collapsing 担保 / 個人保証人 / 第三者保証人 into a single
      text column. The normaliser must emit three independent axis values.
    * `feedback_no_priority_question` and `project_autonomath_loan_risk_axes`
      memory entries reinforce that the three axes are independent enums.
    * The CSV scaffold is the *upstream* of any future DB write; if the
      parser emits a single collapsed string here, every downstream insert
      will be wrong.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

# scripts/etl is not a package; load the module directly so we can import
# its helpers under test.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from scripts.etl import ingest_jfc_loan_scaffold as ing  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

# A faithful (trimmed) reproduction of a JFC product page. The structure is
# what `_ProductTableParser` walks: <h1> + a <table> with `<th scope="col">`
# label cells and adjacent `<td>` value cells.
_JFC_FIXTURE_NEGOTIABLE = """\
<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><title>新規開業・スタートアップ支援資金</title></head>
<body>
<h1>新規開業・スタートアップ支援資金</h1>
<table>
  <tr>
    <th scope="col">ご利用いただける方</th>
    <td colspan="2">新たに事業を始める方または事業開始後おおむね7年以内の方</td>
  </tr>
  <tr>
    <th scope="col">資金のお使いみち</th>
    <td colspan="2">設備資金および運転資金</td>
  </tr>
  <tr>
    <th scope="col">融資限度額</th>
    <td colspan="2">7,200万円</td>
  </tr>
  <tr>
    <th rowspan="2" scope="col">ご返済期間</th>
    <td>設備資金</td>
    <td>20年以内＜うち据置期間5年以内＞</td>
  </tr>
  <tr>
    <td>運転資金</td>
    <td>10年以内</td>
  </tr>
  <tr>
    <th scope="col">利率（年）</th>
    <td colspan="2">基準利率。ただし要件に該当する方は特別利率。</td>
  </tr>
  <tr>
    <th scope="col">担保・保証人</th>
    <td colspan="2">お客さまのご希望を伺いながらご相談させていただきます。</td>
  </tr>
</table>
</body></html>
"""

_JFC_FIXTURE_MARUKE_UNSECURED = """\
<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><title>マル経融資</title></head>
<body>
<h1>マル経融資（小規模事業者経営改善資金）</h1>
<table>
  <tr>
    <th scope="col">ご利用いただける方</th>
    <td>商工会議所の経営指導を6か月以上受けた小規模事業者</td>
  </tr>
  <tr>
    <th scope="col">融資限度額</th>
    <td>2,000万円</td>
  </tr>
  <tr>
    <th scope="col">ご返済期間</th>
    <td>運転資金 7年以内</td>
  </tr>
  <tr>
    <th scope="col">利率（年）</th>
    <td>特別利率F</td>
  </tr>
  <tr>
    <th scope="col">担保・保証人</th>
    <td>無担保・無保証人</td>
  </tr>
</table>
</body></html>
"""

_JFC_FIXTURE_FULL_SECURED = """\
<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><title>仮想 担保あり保証人あり</title></head>
<body>
<h1>仮想 担保あり保証人あり融資（テスト用）</h1>
<table>
  <tr>
    <th scope="col">ご利用いただける方</th>
    <td>大型設備投資を行う中小企業</td>
  </tr>
  <tr>
    <th scope="col">融資限度額</th>
    <td>7億2,000万円</td>
  </tr>
  <tr>
    <th scope="col">ご返済期間</th>
    <td>15年以内</td>
  </tr>
  <tr>
    <th scope="col">利率（年）</th>
    <td>基準利率</td>
  </tr>
  <tr>
    <th scope="col">担保・保証人</th>
    <td>担保が必要。連帯保証人が必要。第三者保証人を不要とする取扱いがあります。</td>
  </tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# parser tests
# ---------------------------------------------------------------------------


def test_parse_negotiable_jfc_product() -> None:
    rec = ing.parse_jfc_product_page(
        _JFC_FIXTURE_NEGOTIABLE,
        "https://www.jfc.go.jp/n/finance/search/01_sinkikaigyou_m.html",
    )
    assert rec is not None
    assert rec.program_name == "新規開業・スタートアップ支援資金"
    assert rec.provider == "日本政策金融公庫"
    assert rec.amount_max_text == "7,200万円"
    assert rec.amount_max_yen == 72_000_000
    # 20年以内 + 10年以内 → max
    assert rec.loan_period_years_max == 20
    # Three axis values: ご相談 -> negotiable on collateral & personal,
    # third-party defaults to negotiable when only ご相談 is mentioned.
    assert rec.collateral_required == "negotiable"
    assert rec.personal_guarantor_required == "negotiable"
    assert rec.third_party_guarantor_required == "negotiable"
    assert rec.source_url.endswith("01_sinkikaigyou_m.html")


def test_parse_maruke_unsecured() -> None:
    """マル経 is the canonical 無担保・無保証人 product. All three axes
    must be `not_required` — the migration 013 docstring uses this exact
    case as motivation."""
    rec = ing.parse_jfc_product_page(
        _JFC_FIXTURE_MARUKE_UNSECURED,
        "https://www.jfc.go.jp/n/finance/search/seiei_shihonseiloan.html",
    )
    assert rec is not None
    assert rec.collateral_required == "not_required"
    assert rec.personal_guarantor_required == "not_required"
    assert rec.third_party_guarantor_required == "not_required"
    assert rec.amount_max_yen == 20_000_000
    assert rec.loan_period_years_max == 7


def test_parse_full_secured_with_third_party_exemption() -> None:
    """担保あり + 個人保証あり + 第三者保証 不要 — the three-axis
    distinction's whole reason for existing.
    """
    rec = ing.parse_jfc_product_page(
        _JFC_FIXTURE_FULL_SECURED,
        "https://www.jfc.go.jp/n/finance/search/test_full_secured.html",
    )
    assert rec is not None
    assert rec.collateral_required == "required"
    assert rec.personal_guarantor_required == "required"
    # The "第三者保証人を不要とする" phrasing must override the default.
    assert rec.third_party_guarantor_required == "not_required"
    # 7億2,000万円 → 720,000,000
    assert rec.amount_max_yen == 720_000_000


def test_three_axis_never_collapsed_to_single_field() -> None:
    """Migration 013 anchor: the three axes are independent columns.
    Verify the dataclass / CSV schema does NOT regress to a single
    `security_required` text column.
    """
    csv_fields = ing.JFC_CSV_FIELDS
    assert "collateral_required" in csv_fields
    assert "personal_guarantor_required" in csv_fields
    assert "third_party_guarantor_required" in csv_fields
    # security_notes is allowed (audit trail), `security_required` is NOT.
    assert "security_required" not in csv_fields
    assert "security_notes" in csv_fields


# ---------------------------------------------------------------------------
# CSV write tests
# ---------------------------------------------------------------------------


def test_write_jfc_csv_round_trip(tmp_path: Path) -> None:
    rec = ing.parse_jfc_product_page(
        _JFC_FIXTURE_MARUKE_UNSECURED,
        "https://www.jfc.go.jp/n/finance/search/maruke.html",
    )
    assert rec is not None
    out = tmp_path / "jfc.csv"
    n = ing.write_jfc_csv([rec], out)
    assert n == 1
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 1
    row = rows[0]
    assert row["collateral_required"] == "not_required"
    assert row["personal_guarantor_required"] == "not_required"
    assert row["third_party_guarantor_required"] == "not_required"
    assert row["source_url"].endswith("maruke.html")


# ---------------------------------------------------------------------------
# guarantee-association discovery
# ---------------------------------------------------------------------------

_ZENSHINHOREN_FIXTURE = """\
<html><body>
  <ul>
    <li><a href="https://www.cgc-tokyo.or.jp/">東京</a></li>
    <li><a href="https://www.cgc-osaka.jp/">大阪</a></li>
    <li><a href="https://www.kagawa-cgc.com/">香川</a></li>
    <li><a href="https://kyosinpo.or.jp/">京都</a></li>
    <li><a href="https://www.zenshinhoren.or.jp/guarantee-system/hoshoseido">本部</a></li>
  </ul>
</body></html>
"""


def test_discover_guarantee_associations_excludes_zenshinhoren() -> None:
    """The 連合会 itself must be excluded from the member list."""
    rows = ing.discover_guarantee_associations(_ZENSHINHOREN_FIXTURE)
    hosts = [r.homepage_url for r in rows]
    # Members are present
    assert any("cgc-tokyo" in h for h in hosts)
    assert any("cgc-osaka" in h for h in hosts)
    assert any("kagawa-cgc" in h for h in hosts)
    assert any("kyosinpo" in h for h in hosts)
    # The 連合会 home is excluded
    assert not any("zenshinhoren.or.jp" in h for h in hosts)


def test_discover_guarantee_associations_assigns_prefecture() -> None:
    rows = ing.discover_guarantee_associations(_ZENSHINHOREN_FIXTURE)
    by_pref = {r.prefecture: r for r in rows}
    assert by_pref["東京都"].homepage_url == "https://www.cgc-tokyo.or.jp"
    assert by_pref["大阪府"].homepage_url == "https://www.cgc-osaka.jp"
    assert by_pref["京都府"].homepage_url == "https://kyosinpo.or.jp"


# ---------------------------------------------------------------------------
# index discovery
# ---------------------------------------------------------------------------

_JFC_INDEX_FIXTURE = """\
<html><body>
  <ul>
    <li><a href="/n/finance/search/01_sinkikaigyou_m.html">新規開業</a></li>
    <li><a href="/n/finance/search/06_tousanntaisaku_m.html">取引企業倒産</a></li>
    <li><a href="/n/finance/search/keieiantei.html">経営安定</a></li>
    <li><a href="/n/finance/search/index.html#chusho">中小企業（nav anchor）</a></li>
    <li><a href="/n/finance/search/index_k.html">国民事業（nav）</a></li>
    <li><a href="/n/finance/search/ippan.html">国の教育ローン（除外）</a></li>
    <li><a href="/n/finance/search/pdf/yuushi_guide.pdf">PDF</a></li>
  </ul>
</body></html>
"""


def test_discover_jfc_product_urls_filters_navigation() -> None:
    urls = ing.discover_jfc_product_urls(_JFC_INDEX_FIXTURE)
    assert any(u.endswith("01_sinkikaigyou_m.html") for u in urls)
    assert any(u.endswith("06_tousanntaisaku_m.html") for u in urls)
    assert any(u.endswith("keieiantei.html") for u in urls)
    # Navigation / index / consumer pages must not appear.
    assert not any(u.endswith("index_k.html") for u in urls)
    assert not any(u.endswith("ippan.html") for u in urls)
    # PDFs are not html product pages.
    assert not any(u.endswith(".pdf") for u in urls)


# ---------------------------------------------------------------------------
# amount / period helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("7,200万円", 72_000_000),
        ("2,000万円", 20_000_000),
        ("7億2,000万円", 720_000_000),
        ("3億円", 300_000_000),
        ("別枠 3,000万円", 30_000_000),
        ("該当なし", None),
        ("", None),
    ],
)
def test_parse_amount_max_yen(text: str, expected: int | None) -> None:
    assert ing.parse_amount_max_yen(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20年以内＜うち据置期間5年以内＞", 20),  # 5 should not win, 20 is max
        ("運転資金 7年以内", 7),
        ("設備資金 20年以内 / 運転資金 10年以内", 20),
        ("該当なし", None),
        ("", None),
    ],
)
def test_parse_loan_period_years_max(text: str, expected: int | None) -> None:
    assert ing.parse_loan_period_years_max(text) == expected
