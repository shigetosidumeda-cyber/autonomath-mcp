"""Tests for tools/offline/extract_prefecture_municipality.py.

The CSV-emitting CLI is operator-only and not part of `src/`, so this test
imports it through `tools/offline/` directly. The detector is exercised
without touching any database — we build a tiny synthetic `RegionIndex`
covering the names referenced in the cases and assert the merger output
shape.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools" / "offline"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import extract_prefecture_municipality as ext  # noqa: E402


def _make_index() -> ext.RegionIndex:
    """Synthetic RegionIndex covering only the places this test references.

    We intentionally do NOT load from autonomath.db; the test is hermetic.
    """
    pref_by_name = {
        "北海道": "01000",
        "福島県": "07000",
        "東京都": "13000",
        "山形県": "06000",
        "富山県": "16000",
        "福岡県": "40000",
        "長崎県": "42000",
    }
    name_to_pref: dict[str, set[str]] = defaultdict(set)
    name_to_pref["南相馬市"].add("07")
    name_to_pref["朝倉市"].add("40")
    name_to_pref["天童市"].add("06")
    name_to_pref["南砺市"].add("16")
    name_to_pref["あきる野市"].add("13")
    # Bare 23-ku name (also a designated-ward elsewhere) — handled via
    # the TOKYO_23_WARDS gate inside extract_from_name.
    name_to_pref["中央区"].update({"01", "13", "27"})
    name_to_pref["札幌市"].add("01")
    return ext.RegionIndex(
        pref_codes={pref_by_name[n][:2] for n in pref_by_name},
        pref_by_name=pref_by_name,
        name_to_pref=name_to_pref,
        designated_cities={"札幌市": "01"},
        designated_wards={},
    )


def _run(name: str, url: str, idx: ext.RegionIndex) -> tuple[ext.Extracted, str]:
    url_ext = ext.extract_from_url(url, idx)
    name_ext = ext.extract_from_name(name, idx, url_prefecture=url_ext.prefecture)
    return ext.merge(name_ext, url_ext)


def test_happy_municipal_url_resolves_pref_and_muni() -> None:
    idx = _make_index()
    merged, conf = _run(
        "南相馬市中小企業賃上げ緊急一時支援金",
        "https://www.city.minamisoma.lg.jp/portal/sangyo/jigyosho/hojokin/",
        idx,
    )
    # Name pins 南相馬市 -> 福島県; URL gives no romaji prefecture.
    assert merged.prefecture == "福島県"
    assert merged.municipality == "南相馬市"
    assert conf in {"medium", "high"}  # name only here; URL has no pref signal


def test_happy_pref_lg_jp_url_extracts_prefecture() -> None:
    idx = _make_index()
    merged, conf = _run(
        "北海道地域経済活性化補助金",
        "https://www.pref.hokkaido.lg.jp/ns/kei/kinyu/sikin.html",
        idx,
    )
    assert merged.prefecture == "北海道"
    assert merged.municipality is None
    assert conf == "high"  # both name and URL agree


def test_happy_pref_in_name_pins_unique_muni() -> None:
    idx = _make_index()
    merged, conf = _run(
        "山形県天童市まちづくり促進補助金",
        "https://www.city.tendo.yamagata.jp/",
        idx,
    )
    assert merged.prefecture == "山形県"
    assert merged.municipality == "天童市"
    assert conf == "high"


def test_happy_tokyo_23_ku_under_anchor() -> None:
    idx = _make_index()
    merged, conf = _run(
        "東京都中央区創業支援補助金",
        "https://www.example-kuyakusho.tokyo.jp/",
        idx,
    )
    # 中央区 is ambiguous in isolation, but anchored by 東京都 in the name.
    assert merged.prefecture == "東京都"
    assert merged.municipality == "中央区"
    assert conf in {"medium", "high"}


def test_happy_hiragana_muni_in_name() -> None:
    idx = _make_index()
    merged, conf = _run(
        "あきる野市子育て世帯支援補助金",
        "https://www.city.akiruno.tokyo.jp/0000002609.html",
        idx,
    )
    # あきる野市 is hiragana-leading; regex must include hiragana.
    # URL gives 東京都 via the .tokyo.jp sublabel.
    assert merged.prefecture == "東京都"
    assert merged.municipality == "あきる野市"
    assert conf == "high"


def test_zenkoku_returns_no_extraction() -> None:
    idx = _make_index()
    merged, conf = _run(
        "全国一律 就農給付金（全国対象）",
        "https://www.maff.go.jp/j/new_farmer/n_syunou/hatten.html",
        idx,
    )
    # 全国 is not a prefecture; URL is national. We must NOT invent a place.
    assert merged.prefecture is None
    assert merged.municipality is None
    assert conf == "low"
