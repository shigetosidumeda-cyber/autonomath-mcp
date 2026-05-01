from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import propose_adoption_program_aliases as proposals  # noqa: E402


def test_build_alias_proposals_filters_high_confidence_only() -> None:
    recommendations = [
        {
            "alias": "IT導入補助金 2023 後期",
            "prefecture": "東京都",
            "recommended_program_id": "prog-it",
            "recommended_primary_name": "IT導入補助金",
            "strategy": "strip_fiscal_year_round",
            "unmatched_rows": 12,
            "candidate_count": 1,
            "review_required": False,
            "reason": "year/round stripped",
        },
        {
            "alias": "低確度候補",
            "prefecture": "東京都",
            "recommended_program_id": "prog-low",
            "recommended_primary_name": "低確度補助金",
            "strategy": "combined_aggressive_punctuationless",
            "unmatched_rows": 7,
            "candidate_count": 1,
            "review_required": False,
            "reason": "too aggressive",
        },
        {
            "alias": "候補IDなし",
            "prefecture": "大阪府",
            "recommended_primary_name": "欠落補助金",
            "strategy": "exact_normalized",
            "unmatched_rows": 5,
            "candidate_count": 1,
            "review_required": False,
        },
    ]

    rows = proposals.build_alias_proposals(recommendations, min_confidence=0.90)

    assert rows == [
        {
            "unmatched_name": "IT導入補助金 2023 後期",
            "prefecture": "東京都",
            "candidate_program_id": "prog-it",
            "candidate_program_name": "IT導入補助金",
            "strategy": "strip_fiscal_year_round",
            "unmatched_rows": 12,
            "confidence": 0.96,
            "reason": "year/round stripped",
            "review_required": False,
        }
    ]


def test_review_required_flags_are_preserved_in_json_and_csv(tmp_path: Path) -> None:
    recommendations = [
        {
            "alias": "IT導入補助金 2023 後期",
            "prefecture": "北海道",
            "recommended_program_id": "prog-it",
            "recommended_primary_name": "IT導入補助金",
            "strategy": "strip_fiscal_year_round",
            "unmatched_rows": 4,
            "candidate_count": 3,
            "review_required": "True",
            "reason": "ambiguous fiscal-year match",
        }
    ]
    report = proposals.build_proposal_report(
        recommendations,
        {"source_kind": "unit", "source_path": None},
        min_confidence=0.90,
    )
    json_path = tmp_path / "adoption_alias_proposals.json"
    csv_path = tmp_path / "adoption_alias_proposals.csv"

    proposals.write_json_report(report, json_path)
    proposals.write_csv_report(report, csv_path)

    decoded = json.loads(json_path.read_text(encoding="utf-8"))
    assert decoded["totals"]["proposals"] == 1
    assert decoded["totals"]["review_required"] == 1
    assert decoded["proposals"][0]["review_required"] is True
    assert decoded["proposals"][0]["confidence"] == 0.90

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "unmatched_name": "IT導入補助金 2023 後期",
            "prefecture": "北海道",
            "candidate_program_id": "prog-it",
            "candidate_program_name": "IT導入補助金",
            "strategy": "strip_fiscal_year_round",
            "unmatched_rows": "4",
            "confidence": "0.90",
            "reason": "ambiguous fiscal-year match",
            "review_required": "True",
        }
    ]
