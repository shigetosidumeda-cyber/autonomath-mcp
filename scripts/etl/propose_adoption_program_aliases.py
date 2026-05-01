#!/usr/bin/env python3
"""Generate review-only adoption program alias proposals.

B7 follow-up helper. It consumes the read-only adoption/program join gap report
when present, or recomputes that report locally, and emits a reviewable alias
proposal file. It never updates ``programs.aliases_json`` or adoption tables.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import report_adoption_program_join_gaps as join_gaps

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAP_JSON = (
    REPO_ROOT / "analysis_wave18" / "adoption_program_join_gaps_2026-05-01.json"
)
DEFAULT_GAP_CSV = REPO_ROOT / "analysis_wave18" / "adoption_program_join_gaps_2026-05-01.csv"
DEFAULT_JSON_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "adoption_alias_proposals_2026-05-01.json"
)
DEFAULT_CSV_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "adoption_alias_proposals_2026-05-01.csv"
)

DEFAULT_MIN_CONFIDENCE = 0.90
PROPOSAL_COLUMNS = [
    "unmatched_name",
    "prefecture",
    "candidate_program_id",
    "candidate_program_name",
    "strategy",
    "unmatched_rows",
    "confidence",
    "reason",
    "review_required",
]

STRATEGY_BASE_CONFIDENCE = {
    "exact_normalized": 0.98,
    "strip_fiscal_year_round": 0.94,
    "strip_parentheses": 0.94,
    "grant_suffix_variants": 0.92,
    "strip_punctuation": 0.90,
    "combined_aggressive": 0.87,
    "combined_aggressive_punctuationless": 0.85,
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _parse_int(value: Any) -> int:
    try:
        return int(str(value or "0").strip())
    except ValueError:
        return 0


def _parse_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_confidence(value: float) -> str:
    return f"{value:.2f}"


def _candidate_count(row: dict[str, Any]) -> int | None:
    raw = row.get("candidate_count")
    if raw in (None, ""):
        return None
    count = _parse_int(raw)
    return count if count > 0 else None


def score_recommendation(row: dict[str, Any]) -> float:
    """Return a conservative deterministic confidence score for a gap row."""
    strategy = str(row.get("strategy") or "")
    base = STRATEGY_BASE_CONFIDENCE.get(strategy, 0.0)
    if base <= 0:
        return 0.0

    count = _candidate_count(row)
    if count == 1:
        base += 0.02
    elif count is not None and count >= 4:
        base -= 0.02

    if _parse_bool(row.get("review_required")):
        base -= 0.04

    return round(max(0.0, min(0.99, base)), 2)


def _proposal_from_recommendation(
    row: dict[str, Any],
    *,
    min_confidence: float,
) -> dict[str, Any] | None:
    confidence = score_recommendation(row)
    if confidence < min_confidence:
        return None

    unmatched_name = _parse_optional_str(row.get("alias") or row.get("unmatched_name"))
    candidate_program_id = _parse_optional_str(
        row.get("recommended_program_id") or row.get("candidate_program_id")
    )
    candidate_program_name = _parse_optional_str(
        row.get("recommended_primary_name") or row.get("candidate_program_name")
    )
    unmatched_rows = _parse_int(row.get("unmatched_rows"))
    if not unmatched_name or not candidate_program_id or not candidate_program_name:
        return None
    if unmatched_rows <= 0:
        return None

    strategy = str(row.get("strategy") or "")
    reason = _parse_optional_str(row.get("reason"))
    if reason is None:
        reason = f"deterministic {strategy} match from B7 join-gap analysis"

    return {
        "unmatched_name": unmatched_name,
        "prefecture": _parse_optional_str(row.get("prefecture")),
        "candidate_program_id": candidate_program_id,
        "candidate_program_name": candidate_program_name,
        "strategy": strategy,
        "unmatched_rows": unmatched_rows,
        "confidence": confidence,
        "reason": reason,
        "review_required": _parse_bool(row.get("review_required")),
    }


def build_alias_proposals(
    recommendations: list[dict[str, Any]],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[dict[str, Any]]:
    """Filter deterministic join-gap recommendations into alias proposals."""
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str]] = set()
    for row in recommendations:
        proposal = _proposal_from_recommendation(row, min_confidence=min_confidence)
        if proposal is None:
            continue
        marker = (
            str(proposal["unmatched_name"]),
            proposal["prefecture"],
            str(proposal["candidate_program_id"]),
        )
        if marker in seen:
            continue
        seen.add(marker)
        proposals.append(proposal)

    return sorted(
        proposals,
        key=lambda row: (
            -int(row["unmatched_rows"]),
            bool(row["review_required"]),
            -float(row["confidence"]),
            str(row["unmatched_name"]),
            str(row["prefecture"] or ""),
            str(row["candidate_program_id"]),
        ),
    )


def load_gap_recommendations_from_json(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report.get("recommended_alias_additions", [])
    if not isinstance(rows, list):
        rows = []
    metadata = {
        "source_kind": "json_report",
        "source_path": str(path),
        "source_generated_at": report.get("generated_at"),
        "source_totals": report.get("totals", {}),
    }
    return [dict(row) for row in rows if isinstance(row, dict)], metadata


def load_gap_recommendations_from_csv(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    metadata = {
        "source_kind": "csv_report",
        "source_path": str(path),
        "source_totals": {"recommended_alias_additions": len(rows)},
    }
    return rows, metadata


def recompute_gap_recommendations(
    *,
    adoption_db: Path,
    program_db: Path,
    tiers: tuple[str, ...],
    max_groups: int,
    recommendation_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with join_gaps._connect_readonly(adoption_db) as adoption_conn:
        if adoption_db.resolve() == program_db.resolve():
            report = join_gaps.collect_adoption_program_join_gaps(
                adoption_conn,
                adoption_conn,
                tiers=tiers,
                max_groups=max_groups,
                sample_limit=0,
                recommendation_limit=recommendation_limit,
            )
        else:
            with join_gaps._connect_readonly(program_db) as program_conn:
                report = join_gaps.collect_adoption_program_join_gaps(
                    adoption_conn,
                    program_conn,
                    tiers=tiers,
                    max_groups=max_groups,
                    sample_limit=0,
                    recommendation_limit=recommendation_limit,
                )
    rows = report.get("recommended_alias_additions", [])
    metadata = {
        "source_kind": "recomputed",
        "source_path": None,
        "source_generated_at": report.get("generated_at"),
        "source_totals": report.get("totals", {}),
        "adoption_db": str(adoption_db),
        "program_db": str(program_db),
    }
    return [dict(row) for row in rows if isinstance(row, dict)], metadata


def load_or_recompute_gap_recommendations(
    *,
    gap_json: Path,
    gap_csv: Path,
    adoption_db: Path,
    program_db: Path,
    tiers: tuple[str, ...],
    max_groups: int,
    recommendation_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if gap_json.exists():
        return load_gap_recommendations_from_json(gap_json)
    if gap_csv.exists():
        return load_gap_recommendations_from_csv(gap_csv)
    return recompute_gap_recommendations(
        adoption_db=adoption_db,
        program_db=program_db,
        tiers=tiers,
        max_groups=max_groups,
        recommendation_limit=recommendation_limit,
    )


def build_proposal_report(
    recommendations: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> dict[str, Any]:
    proposals = build_alias_proposals(recommendations, min_confidence=min_confidence)
    return {
        "generated_at": _utc_now(),
        "report_only": True,
        "mutates_db": False,
        "proposal_columns": PROPOSAL_COLUMNS,
        "min_confidence": min_confidence,
        "source": metadata,
        "totals": {
            "source_recommendations": len(recommendations),
            "proposals": len(proposals),
            "review_required": sum(1 for row in proposals if row["review_required"]),
        },
        "proposals": proposals,
        "notes": [
            "Review-only alias proposal; no SQLite tables are updated.",
            "review_required is preserved from the B7 join-gap analysis.",
            "confidence is a deterministic heuristic over the normalization strategy and ambiguity.",
        ],
    }


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROPOSAL_COLUMNS)
        writer.writeheader()
        for row in report.get("proposals", []):
            writer.writerow(
                {
                    **{field: row.get(field) for field in PROPOSAL_COLUMNS},
                    "confidence": _format_confidence(float(row["confidence"])),
                }
            )


def _split_tiers(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gap-json", type=Path, default=DEFAULT_GAP_JSON)
    parser.add_argument("--gap-csv", type=Path, default=DEFAULT_GAP_CSV)
    parser.add_argument("--adoption-db", type=Path, default=join_gaps.DEFAULT_ADOPTION_DB)
    parser.add_argument("--program-db", type=Path, default=join_gaps.DEFAULT_PROGRAM_DB)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--tiers", default=",".join(join_gaps.DEFAULT_TIERS))
    parser.add_argument("--max-groups", type=int, default=join_gaps.DEFAULT_MAX_GROUPS)
    parser.add_argument(
        "--recommendation-limit",
        type=int,
        default=join_gaps.DEFAULT_RECOMMENDATION_LIMIT,
    )
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--write-json", action="store_true")
    parser.add_argument("--write-csv", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    recommendations, metadata = load_or_recompute_gap_recommendations(
        gap_json=args.gap_json,
        gap_csv=args.gap_csv,
        adoption_db=args.adoption_db,
        program_db=args.program_db,
        tiers=_split_tiers(args.tiers),
        max_groups=args.max_groups,
        recommendation_limit=args.recommendation_limit,
    )
    report = build_proposal_report(
        recommendations,
        metadata,
        min_confidence=args.min_confidence,
    )

    if args.write_json:
        write_json_report(report, args.json_output)
    if args.write_csv:
        write_csv_report(report, args.csv_output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        totals = report["totals"]
        print(f"source_kind={metadata['source_kind']}")
        print(f"source_recommendations={totals['source_recommendations']}")
        print(f"proposals={totals['proposals']}")
        print(f"review_required={totals['review_required']}")
        print(f"min_confidence={report['min_confidence']:.2f}")
        if args.write_json:
            print(f"json_output={args.json_output}")
        if args.write_csv:
            print(f"csv_output={args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
