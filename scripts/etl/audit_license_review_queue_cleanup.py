#!/usr/bin/env python3
"""Classify license_review_queue.csv into deterministic cleanup buckets.

This is a read-only audit helper. It does not mutate the queue CSV or SQLite.
The report lets operators separate rows that can be kept out of public exports
without manual license research from rows that still need review.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from propose_official_license_labels import PUBLIC_LICENSES, classify_source_url

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "analysis_wave18" / "license_review_queue.csv"
DEFAULT_JSON_OUTPUT = REPO_ROOT / "analysis_wave18" / "license_review_cleanup_report.json"

REQUIRED_COLUMNS = (
    "source_id",
    "license",
    "domain",
    "source_type",
    "source_url",
    "first_seen",
    "last_verified",
    "linked_entity_count",
    "sample_entity_ids",
)

ACTION_DROP_INTERNAL = "drop_internal_or_quarantined"
ACTION_DROP_UNLINKED = "drop_unlinked"
ACTION_KEEP_BLOCKED = "keep_blocked_by_domain_rule"
ACTION_BULK_SAFE = "bulk_safe_government_domain"
ACTION_PENDING = "pending_manual_review"
ALL_ACTIONS = (
    ACTION_BULK_SAFE,
    ACTION_DROP_INTERNAL,
    ACTION_DROP_UNLINKED,
    ACTION_KEEP_BLOCKED,
    ACTION_PENDING,
)


@dataclass(frozen=True)
class ClassifiedQueueRow:
    row: dict[str, str]
    action: str
    recommended_license: str
    confidence: float | None
    reason: str


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _linked_count(row: dict[str, str]) -> int:
    value = _clean(row.get("linked_entity_count"))
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _domain(row: dict[str, str]) -> str:
    stored = _clean(row.get("domain")).lower()
    if stored:
        return stored
    source_url = _clean(row.get("source_url"))
    try:
        parsed = urlparse(source_url)
    except ValueError:
        return ""
    return (parsed.hostname or parsed.netloc or "").lower()


def _is_public_url(source_url: str) -> bool:
    return source_url.startswith(("http://", "https://"))


def _is_internal_or_quarantined(row: dict[str, str]) -> bool:
    source_url = _clean(row.get("source_url"))
    domain = _domain(row)
    return source_url.startswith(("internal://", "autonomath:", "quarantined://")) or domain in {
        "autonomath",
        "autonomath.internal",
        "banned",
    }


def read_queue_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} missing required columns: {', '.join(missing)}")
        return [{key: _clean(value) for key, value in row.items()} for row in reader]


def classify_queue_row(row: dict[str, str]) -> ClassifiedQueueRow:
    source_url = _clean(row.get("source_url"))
    domain = _domain(row)
    linked_count = _linked_count(row)

    if _is_internal_or_quarantined(row):
        return ClassifiedQueueRow(
            row=row,
            action=ACTION_DROP_INTERNAL,
            recommended_license="",
            confidence=None,
            reason="non-public internal/autonomath/quarantined source; keep out of public export",
        )

    if linked_count == 0:
        return ClassifiedQueueRow(
            row=row,
            action=ACTION_DROP_UNLINKED,
            recommended_license="",
            confidence=None,
            reason="no linked entities; cleanup/drop candidate before manual license research",
        )

    classified = classify_source_url(source_url, domain)
    if classified is not None:
        proposed_license, confidence, rule_reason = classified
        if proposed_license in PUBLIC_LICENSES and _is_public_url(source_url):
            return ClassifiedQueueRow(
                row=row,
                action=ACTION_BULK_SAFE,
                recommended_license=proposed_license,
                confidence=confidence,
                reason=f"{domain} matched repo public license rule: {rule_reason}",
            )
        if proposed_license == "proprietary":
            return ClassifiedQueueRow(
                row=row,
                action=ACTION_KEEP_BLOCKED,
                recommended_license=proposed_license,
                confidence=confidence,
                reason=f"{domain} matched repo proprietary domain rule: {rule_reason}",
            )

    return ClassifiedQueueRow(
        row=row,
        action=ACTION_PENDING,
        recommended_license="",
        confidence=None,
        reason="no deterministic public/drop/domain-blocked rule matched",
    )


def _top(counter: Counter[str], limit: int) -> list[dict[str, Any]]:
    rows = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"value": key or "<blank>", "count": count} for key, count in rows[:limit]]


def _sample_ids(classified: list[ClassifiedQueueRow], limit: int) -> dict[str, list[str]]:
    samples: dict[str, list[str]] = defaultdict(list)
    for item in classified:
        if len(samples[item.action]) >= limit:
            continue
        source_id = _clean(item.row.get("source_id"))
        if source_id:
            samples[item.action].append(source_id)
    return dict(sorted(samples.items()))


def build_cleanup_report(
    rows: list[dict[str, str]],
    *,
    input_path: Path | None = None,
    top_limit: int = 20,
) -> tuple[dict[str, Any], list[ClassifiedQueueRow]]:
    classified = [classify_queue_row(row) for row in rows]
    by_action = Counter(item.action for item in classified)
    by_license = Counter(_clean(row.get("license")) or "<blank>" for row in rows)
    linked_by_action: Counter[str] = Counter()
    domains_by_action: dict[str, Counter[str]] = defaultdict(Counter)
    proposed_by_license: Counter[str] = Counter()

    for item in classified:
        linked_by_action[item.action] += _linked_count(item.row)
        domains_by_action[item.action][_domain(item.row) or "<blank>"] += 1
        if item.recommended_license:
            proposed_by_license[item.recommended_license] += 1

    by_action_complete = {action: by_action.get(action, 0) for action in ALL_ACTIONS}
    linked_by_action_complete = {action: linked_by_action.get(action, 0) for action in ALL_ACTIONS}

    report: dict[str, Any] = {
        "schema_version": "license_review_cleanup_report.v1",
        "input_csv": str(input_path) if input_path is not None else "",
        "total_rows": len(rows),
        "by_action": by_action_complete,
        "by_current_license": dict(sorted(by_license.items())),
        "linked_entity_count_by_action": linked_by_action_complete,
        "recommended_license_counts": dict(sorted(proposed_by_license.items())),
        "top_domains_by_action": {
            action: _top(domains_by_action.get(action, Counter()), top_limit)
            for action in ALL_ACTIONS
        },
        "sample_source_ids_by_action": _sample_ids(classified, limit=25),
        "public_export_guard": {
            "non_allowlisted_license_rows_must_block": True,
            "pending_rows_are_not_publishable": True,
        },
        "next_actions": [
            "Bulk-safe rows are implementation candidates only; review the matched domain rule before updating am_source.license.",
            "Internal/quarantined/unlinked rows can stay permanently excluded from public exports.",
            "pending_manual_review rows still need source-by-source license decisions.",
        ],
    }
    return report, classified


def write_classified_csv(path: Path, classified: list[ClassifiedQueueRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(REQUIRED_COLUMNS) + [
        "cleanup_action",
        "recommended_license",
        "classification_confidence",
        "classification_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in classified:
            row = {field: item.row.get(field, "") for field in REQUIRED_COLUMNS}
            row.update(
                {
                    "cleanup_action": item.action,
                    "recommended_license": item.recommended_license,
                    "classification_confidence": (
                        "" if item.confidence is None else f"{item.confidence:.3f}"
                    ),
                    "classification_reason": item.reason,
                }
            )
            writer.writerow(row)


def _print_summary(report: dict[str, Any]) -> None:
    print(f"total_rows={report['total_rows']}")
    print(f"by_action={report['by_action']}")
    print(f"by_current_license={report['by_current_license']}")
    print(f"recommended_license_counts={report['recommended_license_counts']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--classified-output", type=Path)
    parser.add_argument("--top-limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--fail-on-pending",
        action="store_true",
        help="exit 1 when pending_manual_review rows remain; default is report-only",
    )
    args = parser.parse_args(argv)

    rows = read_queue_rows(args.input)
    report, classified = build_cleanup_report(rows, input_path=args.input, top_limit=args.top_limit)

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if args.classified_output:
        write_classified_csv(args.classified_output, classified)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_summary(report)
        print(f"json_output={args.json_output}")
        if args.classified_output:
            print(f"classified_output={args.classified_output}")

    if args.fail_on_pending and report["by_action"].get(ACTION_PENDING, 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
