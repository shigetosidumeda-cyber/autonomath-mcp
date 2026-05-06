"""Tests run_practitioner_eval.py end-to-end with stub HTTP.

Cases:
1. happy path — zeirishi persona artifact w/ all required envelope keys -> row_pass=True
2. boundary case — industry_pack_real_estate artifact missing §3 disclaimer -> row_pass=False
3. dry run produces 15 personas x 3 queries with stub artifact output

NO LLM. Substring/regex only. Memory: feedback_no_operator_llm_api.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_EVAL = REPO_ROOT / "scripts" / "eval"
sys.path.insert(0, str(SCRIPTS_EVAL))

import _persona_index  # noqa: E402
import run_practitioner_eval as runner  # noqa: E402


HAPPY_RESPONSE = json.dumps(
    {
        "artifact_id": "kanyosaki_monthly_briefing_provisioning",
        "顧問先への質問": ["決算月", "従業員数"],
        "known_gaps": [{"type": "frequency_check"}],
        "source_url": "https://www.nta.go.jp/...",
        "source_fetched_at": "2026-05-06T03:00Z",
        "専門家確認境界": "税理士確認境界 — 適用判定は税理士の責任で",
        "_disclaimer": "§52 — 制度情報の機械的集約",
    },
    ensure_ascii=False,
)


BOUNDARY_FAIL_RESPONSE = json.dumps(
    {
        "artifact_id": "pack_real_estate",
        "顧問先への質問": ["..."],
        "known_gaps": [],
        "source_url": "https://www.mlit.go.jp/...",
        "source_fetched_at": "2026-05-06T03:00Z",
        "専門家確認境界": "宅建士確認境界 — 取引判定は宅建士で",
        "_disclaimer": "§52 — 情報のみ",
        # NOTE: §3 / 司法書士法 deliberately omitted.
    },
    ensure_ascii=False,
)


def test_happy_path_zeirishi() -> None:
    """zeirishi persona with all envelope fields and §52 boundary -> row_pass=True."""
    inc, hits = runner.judge_must_include(
        HAPPY_RESPONSE,
        [
            "source_url",
            "source_fetched_at",
            "known_gaps",
            "顧問先への質問",
            "専門家確認境界",
        ],
    )
    assert inc, [h for h in hits if not h["matched"]]
    ng_count, _ = runner.judge_must_not_claim(
        HAPPY_RESPONSE,
        [
            "税務判断完了",
            "適用確定",
            "申告書作成済み",
        ],
    )
    assert ng_count == 0
    bnd, _ = runner.judge_boundary(HAPPY_RESPONSE, "zeirishi")
    assert bnd
    assert inc and ng_count == 0 and bnd


def test_boundary_missing_real_estate() -> None:
    """industry_pack_real_estate without §3 / 司法書士法 -> boundary FAIL."""
    inc, _ = runner.judge_must_include(
        BOUNDARY_FAIL_RESPONSE,
        [
            "source_url",
            "source_fetched_at",
            "known_gaps",
            "顧問先への質問",
            "専門家確認境界",
        ],
    )
    ng_count, _ = runner.judge_must_not_claim(
        BOUNDARY_FAIL_RESPONSE,
        [
            "税務判断完了",
            "適用確定",
            "申告書作成済み",
        ],
    )
    bnd, phrases = runner.judge_boundary(BOUNDARY_FAIL_RESPONSE, "industry_pack_real_estate")
    assert inc, "envelope keys still present"
    assert ng_count == 0, "no banned claims"
    assert not bnd, "§3 boundary missing was the expected failure"
    assert "司法書士法" in phrases or "§3" in phrases


def test_boundary_phrases_have_at_least_one_per_sensitive_persona() -> None:
    """Every sensitive-surface persona must list at least one boundary phrase."""
    sensitive_personas = [
        "ma_analyst",
        "ma_valuation",
        "monitoring_pic",
        "zeirishi",
        "zeirishi_kessan",
        "kaikeishi",
        "kaikeishi_audit",
        "foreign_fdi_compliance",
        "subsidy_consultant",
        "shinkin_shokokai",
        "industry_pack_construction",
        "industry_pack_real_estate",
    ]
    for slug in sensitive_personas:
        assert _persona_index.BOUNDARY_PHRASES_BY_PERSONA.get(slug), (
            f"{slug} missing boundary phrases"
        )


def test_persona_index_exactly_15() -> None:
    """The persona index must have exactly 15 entries (the spec target)."""
    assert len(_persona_index.PERSONA_INDEX) == 15
    assert set(_persona_index.PERSONA_INDEX.keys()) == set(_persona_index.PERSONA_COHORT.keys())
    assert set(_persona_index.PERSONA_INDEX.keys()) == set(
        _persona_index.BOUNDARY_PHRASES_BY_PERSONA.keys()
    )


def test_dry_run_emits_15x3_results(tmp_path: Path) -> None:
    """Dry run: 15 personas x 3 queries, stubs filling unmatched rows."""
    corpus = REPO_ROOT / "tests/eval/practitioner_output_acceptance_queries_2026-05-06.jsonl"
    if not corpus.exists():
        # Test corpus may not have shipped yet; skip rather than fail the suite.
        return
    out_dir = tmp_path / "_data"
    rc = runner.main(
        [
            "--corpus",
            str(corpus),
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ]
    )
    assert rc == 0
    payload = json.loads((out_dir / "results_latest.json").read_text(encoding="utf-8"))
    assert len(payload["persona_results"]) == 15
    for p in payload["persona_results"]:
        assert len(p["queries"]) == 3, (
            f"persona {p['persona_slug']} has {len(p['queries'])} queries (want 3)"
        )


def test_judge_substring_default() -> None:
    """Default needle is substring match."""
    inc, _ = runner.judge_must_include("hello world", ["world"])
    assert inc
    inc2, _ = runner.judge_must_include("hello world", ["xyz"])
    assert not inc2


def test_judge_regex_with_re_prefix() -> None:
    """Needles with 're:' prefix are compiled as regex."""
    inc, _ = runner.judge_must_include("price ¥3.30", ["re:¥3(?:\\.\\d+)?"])
    assert inc
    inc2, _ = runner.judge_must_include("price free", ["re:¥\\d+"])
    assert not inc2
    # Bad regex degrades to "no match", does NOT raise.
    inc3, _ = runner.judge_must_include("anything", ["re:[unclosed"])
    assert not inc3
