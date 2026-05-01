from __future__ import annotations

import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import reconcile_law_prefixes as reconcile  # noqa: E402


def test_normalize_law_prefix_strips_articles_and_width_noise() -> None:
    assert reconcile.normalize_law_prefix(
        " 補助金等に係る予算の執行の適正化に関する法律　第２条 "
    ) == "補助金等に係る予算の執行の適正化に関する法律"


def test_build_law_prefix_index_keeps_ambiguous_prefixes_out() -> None:
    rows = [
        {"unified_id": "LAW-aaaaaaaaaa", "law_title": "中小企業等経営強化法"},
        {"unified_id": "LAW-bbbbbbbbbb", "law_title": "中小企業信用保険法"},
        {
            "unified_id": "LAW-cccccccccc",
            "law_title": "補助金等に係る予算の執行の適正化に関する法律",
        },
    ]

    index = reconcile.build_law_prefix_index(rows)

    assert index["補助金等に係る予算の執行の適正化に関する法律"] == "LAW-cccccccccc"
    assert "中小企業" not in index


def test_reconcile_law_prefixes_resolves_only_unambiguous_titles() -> None:
    laws = [
        {"unified_id": "LAW-aaaaaaaaaa", "law_title": "中小企業等経営強化法"},
        {"unified_id": "LAW-bbbbbbbbbb", "law_title": "中小企業信用保険法"},
        {
            "unified_id": "LAW-cccccccccc",
            "law_title": "補助金等に係る予算の執行の適正化に関する法律",
        },
    ]
    refs = [
        {
            "program_unified_id": "UNI-1111111111",
            "law_prefix": "補助金等に係る予算の執行の適正化に関する法律 第2条",
        },
        {"program_unified_id": "UNI-2222222222", "law_prefix": "中小企業"},
        {"program_unified_id": "UNI-3333333333", "law_prefix": "存在しない法令"},
    ]

    resolved, unresolved = reconcile.reconcile_law_prefixes(refs, laws)

    assert resolved == [
        {
            "program_unified_id": "UNI-1111111111",
            "law_prefix": "補助金等に係る予算の執行の適正化に関する法律 第2条",
            "law_unified_id": "LAW-cccccccccc",
        }
    ]
    assert {row["program_unified_id"] for row in unresolved} == {
        "UNI-2222222222",
        "UNI-3333333333",
    }
