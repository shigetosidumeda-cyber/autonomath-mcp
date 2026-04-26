"""Tests for loop_b_testimonial_seo.

Covers the launch-v1 happy path: synthesised query_log_v2 rows + customer
ratings feed the loop, which extracts testimonials, redacts PII, and writes
a proposals YAML.
"""

from __future__ import annotations

from pathlib import Path

from jpintel_mcp.self_improve import loop_b_testimonial_seo as loop_b


def _fake_query_log_rows() -> list[dict[str, object]]:
    """Synthetic query_log_v2 rows.

    Tool frequencies (success path only):
        search_programs   -> 6 hits  (high — should propose)
        search_loans      -> 4 hits  (medium — should propose, has rating)
        get_law_article   -> 2 hits  (below noise floor — drop)
    Plus contamination rows that must be filtered out:
        zero-result row, error row, low_confidence row.
    """
    return [
        {"tool": "search_programs", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_programs", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_programs", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_programs", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_programs", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_programs", "result_bucket": "success", "status_code": 200},
        {"tool": "search_loans", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_loans", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_loans", "result_bucket": "hit", "status_code": 200},
        {"tool": "search_loans", "result_bucket": "hit", "status_code": 200},
        # Below noise floor — drops out.
        {"tool": "get_law_article", "result_bucket": "hit", "status_code": 200},
        {"tool": "get_law_article", "result_bucket": "hit", "status_code": 200},
        # Contamination — must be filtered.
        {"tool": "search_programs", "result_bucket": "zero", "status_code": 200},
        {"tool": "search_programs", "result_bucket": "error", "status_code": 500},
        {"tool": "search_programs", "result_bucket": "low_confidence", "status_code": 200},
        {"tool": "", "result_bucket": "hit", "status_code": 200},
    ]


def _fake_ratings() -> list[dict[str, object]]:
    """Customer ratings + comments. The comments contain PII that MUST be
    redacted before any persistence (INV-21 / APPI § 31)."""
    return [
        {
            "tool": "search_loans",
            "rating": 5,
            "comment": "助成金の探索が驚くほど早い。連絡は info@example.co.jp まで。",
            "api_key_hash": "ak_abc",
        },
        {
            "tool": "search_loans",
            "rating": 4,
            "comment": "法人番号 T1234567890123 で照合できて感動。電話 03-1234-5678 でも対応可。",
            "api_key_hash": "ak_def",
        },
        # Lukewarm rating must be dropped entirely — we will not surface 3-star
        # reviews on the landing page.
        {
            "tool": "search_loans",
            "rating": 2,
            "comment": "微妙だった",
            "api_key_hash": "ak_ghi",
        },
        # Rating for an unproposed tool — should not influence anything.
        {
            "tool": "get_law_article",
            "rating": 5,
            "comment": "Best tool ever",
            "api_key_hash": "ak_jkl",
        },
    ]


def test_loop_b_extracts_testimonials_and_redacts_pii(tmp_path: Path):
    out_path = tmp_path / "testimonials_proposed.yaml"

    result = loop_b.run(
        dry_run=False,
        query_log_rows=_fake_query_log_rows(),
        ratings=_fake_ratings(),
        out_path=out_path,
    )

    # Standard scaffold shape.
    assert result["loop"] == "loop_b_testimonial_seo"
    assert result["scanned"] == 16  # all rows counted, even contamination
    # search_programs (6, no ratings -> high) and search_loans (4, has 4+ rating -> medium).
    # get_law_article (2) drops below noise floor regardless of its 5-star rating.
    assert result["actions_proposed"] == 2
    assert result["actions_executed"] == 1

    # Inspect proposals via the helpers directly to verify ranking + PII redaction.
    hits = loop_b.extract_hits(_fake_query_log_rows())
    # 6 search_programs + 4 search_loans + 2 get_law_article. Contamination
    # (zero/error/low_confidence/empty-tool) is filtered. get_law_article
    # survives extract_hits but gets dropped later at the noise-floor gate.
    assert len(hits) == 12
    proposals = loop_b.extract_testimonials(hits, _fake_ratings())
    assert [p["tool"] for p in proposals] == ["search_programs", "search_loans"]

    high = proposals[0]
    assert high["tool"] == "search_programs"
    assert high["hits"] == 6
    assert high["confidence"] == "high"
    assert high["median_rating"] is None
    assert high["sample_comments"] == []  # no ratings tagged for this tool

    medium = proposals[1]
    assert medium["tool"] == "search_loans"
    assert medium["hits"] == 4
    assert medium["confidence"] == "medium"
    # Two 4+ star ratings -> median 4.5; lukewarm 2-star excluded.
    assert medium["median_rating"] == 4.5
    assert len(medium["sample_comments"]) == 2

    # PII redaction is the load-bearing assertion (INV-21).
    blob = "\n".join(medium["sample_comments"])
    assert "info@example.co.jp" not in blob
    assert "T1234567890123" not in blob
    assert "03-1234-5678" not in blob
    assert "[REDACTED:EMAIL]" in blob
    assert "[REDACTED:HOUJIN]" in blob
    assert "[REDACTED:PHONE]" in blob

    # YAML file should exist and the same redaction guarantees apply on disk.
    body = out_path.read_text(encoding="utf-8")
    assert "search_programs" in body
    assert "search_loans" in body
    assert "get_law_article" not in body  # below noise floor
    assert "info@example.co.jp" not in body
    assert "T1234567890123" not in body
    assert "03-1234-5678" not in body


def test_loop_b_no_rows_returns_zeroed_scaffold():
    """Pre-launch: orchestrator hasn't wired the learning DB yet."""
    out = loop_b.run(dry_run=True)
    assert out == {
        "loop": "loop_b_testimonial_seo",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }
