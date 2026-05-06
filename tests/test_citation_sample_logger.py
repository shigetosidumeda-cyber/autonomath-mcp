"""tests/test_citation_sample_logger.py — DEEP-43 manual citation sample.

5 cases per spec §8 acceptance:
1. CSV parse round-trip
2. Monthly aggregate produces correct totals + cascade_state
3. Per-LLM rate computation isolates each provider
4. LLM API 0 — no anthropic / openai / google.generativeai imports
   anywhere in the script's source text
5. citation_query_set_100.json shape valid (24 + 24 + 52 = 100)
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys
import tempfile

import pytest

# import path (tools/offline/operator_review/)
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
TOOL_DIR = REPO / "tools" / "offline" / "operator_review"
sys.path.insert(0, str(TOOL_DIR))

import log_citation_sample as lcs  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_csv(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a small CSV with 4 LLM × 5 rows + mixed citation flags."""
    p = tmp_path / "citation_samples_2026-05.csv"
    rows = []
    # claude: 5 samples, 1 jpcite cited
    for i in range(5):
        rows.append({
            "sample_month": "2026-05",
            "llm_provider": "claude",
            "query_id": f"Q{i+1:03d}",
            "query_text": "test",
            "jpcite_cited": "1" if i == 0 else "0",
            "competitor_cited": "0",
            "citation_url": "https://jpcite.com/x" if i == 0 else "",
            "sampled_at": "2026-05-01T09:00:00Z",
            "sampled_by": "operator",
        })
    # perplexity: 5 samples, 2 jpcite cited
    for i in range(5):
        rows.append({
            "sample_month": "2026-05",
            "llm_provider": "perplexity",
            "query_id": f"Q{i+1:03d}",
            "query_text": "test",
            "jpcite_cited": "1" if i < 2 else "0",
            "competitor_cited": "1" if i == 4 else "0",
            "citation_url": "",
            "sampled_at": "2026-05-01T09:01:00Z",
            "sampled_by": "operator",
        })
    # chatgpt: 5 samples, 0 jpcite, 3 competitor
    for i in range(5):
        rows.append({
            "sample_month": "2026-05",
            "llm_provider": "chatgpt",
            "query_id": f"Q{i+1:03d}",
            "query_text": "test",
            "jpcite_cited": "0",
            "competitor_cited": "1" if i < 3 else "0",
            "citation_url": "",
            "sampled_at": "2026-05-01T09:02:00Z",
            "sampled_by": "operator",
        })
    # gemini: 5 samples, 1 jpcite, 1 competitor
    for i in range(5):
        rows.append({
            "sample_month": "2026-05",
            "llm_provider": "gemini",
            "query_id": f"Q{i+1:03d}",
            "query_text": "test",
            "jpcite_cited": "1" if i == 0 else "0",
            "competitor_cited": "1" if i == 1 else "0",
            "citation_url": "",
            "sampled_at": "2026-05-01T09:03:00Z",
            "sampled_by": "operator",
        })

    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p


# ---------------------------------------------------------------------------
# 1. CSV parse round-trip
# ---------------------------------------------------------------------------


def test_csv_parse_roundtrip(sample_csv: pathlib.Path) -> None:
    rows = lcs.parse_csv(sample_csv)
    assert len(rows) == 20  # 4 LLM × 5
    providers = {r["llm_provider"] for r in rows}
    assert providers == {"claude", "perplexity", "chatgpt", "gemini"}
    cited = sum(r["jpcite_cited"] for r in rows)
    assert cited == 4  # 1 + 2 + 0 + 1
    competitor = sum(r["competitor_cited"] for r in rows)
    assert competitor == 5  # 0 + 1 + 3 + 1


# ---------------------------------------------------------------------------
# 2. monthly aggregate produces correct totals + cascade_state
# ---------------------------------------------------------------------------


def test_aggregate_totals_and_cascade(sample_csv: pathlib.Path) -> None:
    rows = lcs.parse_csv(sample_csv)
    summary = lcs.aggregate(rows, month="2026-05")
    assert summary["total_samples"] == 20
    assert summary["q_jpcite"] == round(4 / 20, 4)  # 0.2
    assert summary["q_competitor"] == round(5 / 20, 4)  # 0.25
    # 0.2 >= 0.10 → tipping_confirmed
    assert summary["cascade_state"] == "tipping_confirmed"
    assert summary["llm_api_calls"] == 0
    assert summary["critical_q_star"] == 0.10


def test_aggregate_pre_tipping_state() -> None:
    """When q < 0.05 → pre_tipping; when 0.05 ≤ q < 0.10 → approach."""
    rows = []
    # 100 samples, 2 jpcite cited → q = 0.02 → pre_tipping
    for i in range(100):
        rows.append({
            "sample_month": "2026-05",
            "llm_provider": "claude",
            "query_id": f"Q{i+1:03d}",
            "query_text": "x",
            "jpcite_cited": 1 if i < 2 else 0,
            "competitor_cited": 0,
            "citation_url": None,
            "sampled_at": "x",
            "sampled_by": "operator",
        })
    s_pre = lcs.aggregate(rows, month="2026-05")
    assert s_pre["q_jpcite"] == 0.02
    assert s_pre["cascade_state"] == "pre_tipping"

    # 100 samples, 7 cited → q = 0.07 → approach
    rows2 = []
    for i in range(100):
        rows2.append({
            "sample_month": "2026-05",
            "llm_provider": "claude",
            "query_id": f"Q{i+1:03d}",
            "query_text": "x",
            "jpcite_cited": 1 if i < 7 else 0,
            "competitor_cited": 0,
            "citation_url": None,
            "sampled_at": "x",
            "sampled_by": "operator",
        })
    s_app = lcs.aggregate(rows2, month="2026-05")
    assert s_app["q_jpcite"] == 0.07
    assert s_app["cascade_state"] == "approach"


# ---------------------------------------------------------------------------
# 3. per-LLM rate computation isolates each provider
# ---------------------------------------------------------------------------


def test_per_llm_rate_isolation(sample_csv: pathlib.Path) -> None:
    rows = lcs.parse_csv(sample_csv)
    summary = lcs.aggregate(rows, month="2026-05")
    per = summary["per_llm"]
    assert per["claude"]["sample_count"] == 5
    assert per["claude"]["jpcite_rate"] == 0.2
    assert per["perplexity"]["jpcite_rate"] == 0.4  # 2/5
    assert per["chatgpt"]["jpcite_rate"] == 0.0
    assert per["chatgpt"]["competitor_rate"] == 0.6  # 3/5
    assert per["gemini"]["jpcite_rate"] == 0.2
    # missing_rate per LLM = (100 - 5) / 100 = 0.95
    assert per["claude"]["missing_rate"] == 0.95


# ---------------------------------------------------------------------------
# 4. LLM API 0 — script source must not import LLM SDKs
# ---------------------------------------------------------------------------


def test_llm_api_zero_in_logger_source() -> None:
    """The logger script + query set + dashboard MUST NOT import
    anthropic / openai / google.generativeai / claude_agent_sdk
    or reference api keys. DEEP-43 §8.4 CI guard equivalent."""
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import claude_agent_sdk",
        "from claude_agent_sdk",
        "anthropic.Anthropic(",
        "OpenAI(",
        "perplexity_api",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "PERPLEXITY_API_KEY",
    )
    paths = [
        TOOL_DIR / "log_citation_sample.py",
        TOOL_DIR / "citation_query_set_100.json",
        TOOL_DIR / "citation_samples_template.csv",
        REPO / "site" / "transparency" / "llm-citation-rate.html",
    ]
    for p in paths:
        text = p.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, (
                f"{p.name}: forbidden LLM SDK reference '{needle}' "
                f"violates DEEP-43 §8.4 / feedback_no_operator_llm_api"
            )


# ---------------------------------------------------------------------------
# 5. citation_query_set_100.json valid shape
# ---------------------------------------------------------------------------


def test_query_set_shape_valid() -> None:
    qs = lcs.load_query_set()
    result = lcs.validate_query_set(qs)
    assert result == {
        "ok": True,
        "total": 100,
        "sensitive": 24,
        "non_sensitive": 24,
        "general": 52,
    }
    queries = qs["queries"]
    # Every query has the required fields
    for q in queries:
        assert q["query_id"].startswith("Q")
        assert q["category"] in ("sensitive", "non_sensitive", "general")
        assert q["intent"]
        assert q["text"]
    # Spec §3.4: ll_api_calls is 0
    assert qs["ll_api_calls"] == 0
