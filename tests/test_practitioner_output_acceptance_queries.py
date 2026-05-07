from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
JSONL_PATH = (
    REPO_ROOT / "tests" / "eval" / "practitioner_output_acceptance_queries_2026-05-06.jsonl"
)

REQUIRED_KEYS = {
    "persona",
    "query",
    "expected_artifact",
    "must_include",
    "must_not_claim",
    "data_join_needed",
}

PROFESSIONAL_JUDGMENT_OR_ASSERTION_NG = (
    "専門家レビュー不要",
    "専門判断不要",
    "専門家相談不要",
    "窓口確認不要",
    "専門家確認不要",
    "専門判断",
    "判断の代替",
    "手続の代替",
    "回答として確定",
    "断定",
    "確定",
    "保証",
    "証明",
    "完了",
    "結論",
    "推奨",
    "見込み",
    "リスクなし",
    "問題なし",
    "安全",
    "不要",
)

PRICE_OR_FREE_TIER_CHANGE_REQUEST = re.compile(
    r"価格変更|料金変更|価格改定|料金改定|値上げ|値下げ|" r"free\s*tier|フリー\s*ティア|無料枠",
    re.IGNORECASE,
)


def _load_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(JSONL_PATH.read_text(encoding="utf-8").splitlines(), 1):
        assert line.strip(), f"blank JSONL line at {line_no}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid JSON at line {line_no}: {exc}") from exc
        assert isinstance(row, dict), f"line {line_no} must be a JSON object"
        rows.append(row)
    return rows


def test_practitioner_output_acceptance_jsonl_shape() -> None:
    rows = _load_rows()

    assert len(rows) >= 30
    assert len({row["persona"] for row in rows}) == 10

    for line_no, row in enumerate(rows, 1):
        assert row.keys() >= REQUIRED_KEYS, f"line {line_no} missing required keys"
        assert set(row.keys()) == REQUIRED_KEYS, f"line {line_no} has unexpected keys"
        assert isinstance(row["persona"], str) and row["persona"].strip()
        assert isinstance(row["query"], str) and row["query"].strip()
        assert isinstance(row["expected_artifact"], str) and row["expected_artifact"].strip()

        for key in ("must_include", "must_not_claim", "data_join_needed"):
            assert isinstance(row[key], list), f"line {line_no} {key} must be a list"
            assert row[key], f"line {line_no} {key} must not be empty"
            assert all(
                isinstance(item, str) and item.strip() for item in row[key]
            ), f"line {line_no} {key} must contain non-empty strings"


def test_must_not_claim_blocks_professional_substitution_and_assertions() -> None:
    for line_no, row in enumerate(_load_rows(), 1):
        joined = " ".join(row["must_not_claim"])
        assert any(
            term in joined for term in PROFESSIONAL_JUDGMENT_OR_ASSERTION_NG
        ), f"line {line_no} must_not_claim lacks judgment/definitive-claim guard"


def test_queries_do_not_request_price_or_free_tier_changes() -> None:
    for line_no, row in enumerate(_load_rows(), 1):
        assert (
            PRICE_OR_FREE_TIER_CHANGE_REQUEST.search(row["query"]) is None
        ), f"line {line_no} query must not request price/free tier changes"
