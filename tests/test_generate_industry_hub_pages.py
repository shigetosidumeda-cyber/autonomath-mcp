from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import generate_industry_hub_pages as hub  # noqa: E402


def test_preparing_source_title_renders_as_unpublished_guideline_status() -> None:
    display_title = "令和8年度徳島県地域脱炭素移行・再エネ推進事業補助金について"
    raw_title = f"【準備中】{display_title}"
    html_doc = hub._render_hub(
        "F",
        "JSIC F 電気・ガス・熱供給・水道業",
        "電気・ガス・熱供給・水道業",
        "desc",
        [
            {
                "unified_id": "UNI-test-preparing",
                "primary_name": raw_title,
                "prefecture": "徳島県",
                "program_kind": "subsidy",
                "target_types_json": "[]",
                "amount_max_man_yen": None,
                "amount_min_man_yen": None,
                "tier": "A",
                "source_url": "https://www.pref.tokushima.lg.jp/example/",
                "authority_name": "徳島県",
                "authority_level": "prefecture",
            }
        ],
        "jpcite.test",
        "/industries/F/",
    )

    assert "準備中" not in html_doc
    assert "要綱未公表" in html_doc
    assert display_title in html_doc
    assert f"{display_title}（要綱未公表）" in html_doc
