from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / "scripts" / "cron" / "extract_program_facts.py"


def _load_driver():
    spec = importlib.util.spec_from_file_location("extract_program_facts", DRIVER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_normalizes_japanese_era_and_western_dates() -> None:
    drv = _load_driver()

    assert drv.normalize_japanese_date("令和6年5月31日(金)") == "2024-05-31"
    assert drv.normalize_japanese_date("令和元年10月1日") == "2019-10-01"
    assert drv.normalize_japanese_date("2025/2/7") == "2025-02-07"


def test_normalizes_yen_amounts_and_subsidy_rates() -> None:
    drv = _load_driver()

    assert drv.normalize_yen_amount("補助上限額 1,000千円")["yen"] == 1_000_000
    assert drv.normalize_yen_amount("最大 50万円")["yen"] == 500_000
    assert drv.normalize_subsidy_rate("補助率 2分の1以内")["normalized"] == "1/2"
    assert drv.normalize_subsidy_rate("助成率 50%")["percent"] == 50.0


def test_grant_env_content_profile_extracts_dry_run_facts() -> None:
    drv = _load_driver()
    fixture = """
    省エネ設備導入補助金 募集要領
    募集期間 令和6年4月1日(月)から令和6年5月31日(金)まで
    補助率 2分の1以内
    補助上限額 100万円

    提出書類
    1. 交付申請書
    2. 事業計画書
    3. 見積書

    お問い合わせ 環境政策課 03-1234-5678 env@example.jp
    """

    facts = drv.parse_program_facts(
        fixture,
        source_url="https://example.lg.jp/grant/env.pdf",
        source_domain="example.lg.jp",
    )

    assert facts.profile == "grant_env_content"
    assert facts.source_url == "https://example.lg.jp/grant/env.pdf"
    assert facts.deadline["value"] == "2024-05-31"
    assert facts.subsidy_rate["normalized"] == "1/2"
    assert facts.max_amount["yen"] == 1_000_000
    assert facts.required_docs == ["交付申請書", "事業計画書", "見積書"]
    assert facts.contact["phone"] == "03-1234-5678"
    assert facts.contact["email"] == "env@example.jp"
    assert len(facts.content_hash) == 64
    assert len(facts.text_hash) == 64
    assert facts.confidence == 1.0


def test_deadline_handles_rolling_budget_limited_language() -> None:
    drv = _load_driver()

    facts = drv.parse_program_facts(
        "申請期限 予算額に達し次第、受付を終了します。",
        source_url="https://example.lg.jp/rolling.pdf",
        source_domain="example.lg.jp",
    )

    assert facts.deadline == {
        "value": None,
        "raw": "申請期限 予算額に達し次第、受付を終了します。",
        "status": "rolling_or_budget_limited",
    }
