"""Tests for loop_j_gold_expansion.

Covers the launch-v1 happy path: synthesised query_log_v2 rows + a
fixture `derive_expected_ids` callable feed the loop, which mines
high-confidence stable queries, redacts PII (INV-21), filters out
queries already present in evals/gold.yaml, and writes a proposals
YAML for operator review.
"""

from __future__ import annotations

from pathlib import Path

from jpintel_mcp.self_improve import loop_j_gold_expansion as loop_j


def _fake_query_log_rows() -> list[dict[str, object]]:
    """Synthetic query_log_v2 rows.

    High-confidence + stable groups (should propose):
        ("認定新規就農者向けの補助制度を教えてください。", search_programs,
         UNI-5cb4538235) -> 6 distinct sessions, conf 0.97, sentiment positive
        ("インボイス登録番号 T1234567890123 の事業者は誰?", search_corp,
         CORP-1) -> 5 distinct sessions, conf 0.96 — query carries 法人番号
                  in the text; redaction MUST scrub it.
    Below-bar groups (should drop):
        Low confidence (0.80) — fails MIN_CONFIDENCE.
        Low stability (only 2 sessions) — fails MIN_STABILITY.
        Already in gold (existing_gold fixture) — silently skipped.
        Negative sentiment — fails sentiment gate.
        No top_result_id — fails (tool didn't return a row).
    """
    rows: list[dict[str, object]] = []
    # === Group 1: 6 distinct sessions, conf 0.97, positive sentiment ===
    for i in range(6):
        rows.append(
            {
                "session_id": f"sess_agri_{i}",
                "query_text": "認定新規就農者向けの補助制度を教えてください。",
                "tool": "search_programs",
                "tool_args": {"q": "認定新規就農者", "tier": ["S", "A", "B"], "limit": 10},
                "top_result_id": "UNI-5cb4538235",
                "confidence": 0.97,
                "sentiment": "positive",
            }
        )
    # === Group 2: 5 distinct sessions, conf 0.96, query has PII ===
    for i in range(5):
        rows.append(
            {
                "session_id": f"sess_corp_{i}",
                "query_text": "インボイス登録番号 T1234567890123 の事業者は誰?連絡 03-1234-5678 まで。",
                "tool": "search_corp",
                "tool_args": '{"houjin_bangou": "1234567890123"}',  # JSON string form
                "top_result_id": "CORP-1",
                "confidence": 0.96,
                "sentiment": "neutral",
            }
        )
    # === Drop: low confidence (0.80) ===
    for i in range(6):
        rows.append(
            {
                "session_id": f"sess_lowconf_{i}",
                "query_text": "曖昧なクエリ",
                "tool": "search_programs",
                "tool_args": {"q": "曖昧"},
                "top_result_id": "UNI-x",
                "confidence": 0.80,
                "sentiment": "positive",
            }
        )
    # === Drop: low stability (only 2 sessions, even at 0.99 conf) ===
    for i in range(2):
        rows.append(
            {
                "session_id": f"sess_unstable_{i}",
                "query_text": "未成熟なクエリ",
                "tool": "search_programs",
                "tool_args": {"q": "未成熟"},
                "top_result_id": "UNI-y",
                "confidence": 0.99,
                "sentiment": "positive",
            }
        )
    # === Drop: already in evals/gold.yaml ===
    for i in range(6):
        rows.append(
            {
                "session_id": f"sess_existing_{i}",
                "query_text": "既存ゴールドクエリ",
                "tool": "search_programs",
                "tool_args": {"q": "既存"},
                "top_result_id": "UNI-existing",
                "confidence": 0.98,
                "sentiment": "positive",
            }
        )
    # === Drop: negative sentiment ===
    for i in range(6):
        rows.append(
            {
                "session_id": f"sess_neg_{i}",
                "query_text": "不満のあったクエリ",
                "tool": "search_programs",
                "tool_args": {"q": "不満"},
                "top_result_id": "UNI-z",
                "confidence": 0.99,
                "sentiment": "negative",
            }
        )
    # === Drop: no top_result_id ===
    for i in range(6):
        rows.append(
            {
                "session_id": f"sess_zero_{i}",
                "query_text": "ゼロ結果のクエリ",
                "tool": "search_programs",
                "tool_args": {"q": "ゼロ"},
                "top_result_id": "",
                "confidence": 0.99,
                "sentiment": "positive",
            }
        )
    return rows


def _fake_derive_expected_ids(
    tool_name: str, tool_args: dict[str, object], top_result_id: str
) -> list[str]:
    """SQL-derived top-K stand-in for tests."""
    if tool_name == "search_programs" and top_result_id == "UNI-5cb4538235":
        return [
            "UNI-5cb4538235",
            "UNI-2accde9202",
            "UNI-2293683c44",
        ]
    if tool_name == "search_corp" and top_result_id == "CORP-1":
        return ["CORP-1"]
    return []


def _fake_derive_source_url(
    tool_name: str, tool_args: dict[str, object], top_result_id: str
) -> str | None:
    """Primary-source URL stand-in for tests."""
    if top_result_id == "UNI-5cb4538235":
        return "https://www.maff.go.jp/example/agri.html"
    return None  # CORP-1 -> falls into 'review' bucket


def test_loop_j_mines_high_confidence_candidates_redacts_pii_and_writes_yaml(
    tmp_path: Path,
):
    out_path = tmp_path / "tier_a_proposed.yaml"
    rows = _fake_query_log_rows()

    result = loop_j.run(
        dry_run=False,
        query_log_rows=rows,
        derive_expected_ids=_fake_derive_expected_ids,
        derive_source_url=_fake_derive_source_url,
        existing_gold={"既存ゴールドクエリ"},
        out_path=out_path,
    )

    # Standard scaffold shape.
    assert result["loop"] == "loop_j_gold_expansion"
    assert result["scanned"] == len(rows)
    # Two surviving groups: agri search_programs + corp search_corp.
    assert result["actions_proposed"] == 2
    assert result["actions_executed"] == 1

    # Inspect the parsed candidates via the helper directly.
    candidates = loop_j.extract_candidates(
        rows,
        derive_expected_ids=_fake_derive_expected_ids,
        derive_source_url=_fake_derive_source_url,
        existing_gold_queries={"既存ゴールドクエリ"},
    )
    # Sorted by stability desc -> agri (6) first, then corp (5).
    assert [c["tool_name"] for c in candidates] == ["search_programs", "search_corp"]

    agri = candidates[0]
    assert agri["stability"] == 6
    assert agri["confidence"] == 0.97
    assert agri["expected_ids"] == [
        "UNI-5cb4538235",
        "UNI-2accde9202",
        "UNI-2293683c44",
    ]
    assert agri["gold_source_url"] == "https://www.maff.go.jp/example/agri.html"
    assert agri["recommended"] == "accept"
    # Query had no PII so it should pass through unchanged.
    assert agri["query_text"] == "認定新規就農者向けの補助制度を教えてください。"

    corp = candidates[1]
    assert corp["stability"] == 5
    # PII redaction is the load-bearing assertion (INV-21).
    assert "T1234567890123" not in corp["query_text"]
    assert "03-1234-5678" not in corp["query_text"]
    assert "[REDACTED:HOUJIN]" in corp["query_text"]
    assert "[REDACTED:PHONE]" in corp["query_text"]
    # No source URL -> review bucket.
    assert corp["gold_source_url"] is None
    assert corp["recommended"] == "review"

    # YAML file should exist; redaction guarantees apply on disk too.
    body = out_path.read_text(encoding="utf-8")
    assert "search_programs" in body
    assert "search_corp" in body
    assert "認定新規就農者" in body
    assert "T1234567890123" not in body
    assert "03-1234-5678" not in body
    # Dropped groups must NOT leak into the YAML.
    assert "曖昧なクエリ" not in body
    assert "未成熟なクエリ" not in body
    assert "既存ゴールドクエリ" not in body
    assert "不満のあったクエリ" not in body
    assert "ゼロ結果のクエリ" not in body


def test_loop_j_no_rows_returns_zeroed_scaffold():
    """Pre-launch: orchestrator hasn't wired the learning DB yet."""
    out = loop_j.run(dry_run=True)
    assert out == {
        "loop": "loop_j_gold_expansion",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }
