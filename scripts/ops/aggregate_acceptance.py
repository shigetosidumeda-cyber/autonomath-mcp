"""
aggregate_acceptance.py
=======================

Per-spec rollup for DEEP-59 acceptance criteria runs.

Reads:
- a JUnit XML produced by `pytest tests/test_acceptance_criteria.py
  --junitxml=acceptance_junit.xml`, OR
- the canonical YAML (acceptance_criteria.yaml) when junit is absent
  (in which case we report planned coverage only).

Emits a JSON document of shape:

    {
      "schema_version": 1,
      "generated_at": "2026-05-07T...Z",
      "summary": {
        "total": 258,
        "passed": 205,
        "failed": 0,
        "skipped": 53,
        "automated": 205,
        "semi_automated": 30,
        "manual": 23,
        "automation_ratio": 0.795,
        "automation_target": 0.795,
        "automation_target_met": true
      },
      "per_spec": {
        "DEEP-22": {"total": 4, "passed": 3, "failed": 0, "skipped": 1},
        ...
      },
      "per_check_kind": { "file_existence": {...}, ... },
      "rows": [...]
    }

Constraints:
- LLM API call count = 0
- stdlib + PyYAML only

Usage:

    python aggregate_acceptance.py \
        --junit acceptance_junit.xml \
        --yaml acceptance_criteria.yaml \
        --out aggregate_acceptance.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

AUTOMATION_TARGET = 0.795


def parse_yaml(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"{path}: root must be a list")
    return [r for r in raw if isinstance(r, dict)]


def parse_junit(path: Path) -> dict[str, str]:
    """Return mapping of pytest test id -> outcome ('passed'|'failed'|'skipped')."""
    if not path.exists():
        return {}
    tree = ET.parse(path)
    root = tree.getroot()
    out: dict[str, str] = {}
    for tc in root.iter("testcase"):
        name = tc.attrib.get("name", "")
        # pytest emits ids like 'test_acceptance_criterion[DEEP-22-1-sql_syntax]'
        if "[" in name and name.endswith("]"):
            tid = name.split("[", 1)[1][:-1]
        else:
            tid = name
        if tc.find("failure") is not None or tc.find("error") is not None:
            out[tid] = "failed"
        elif tc.find("skipped") is not None:
            out[tid] = "skipped"
        else:
            out[tid] = "passed"
    return out


def build_report(
    rows: list[dict[str, Any]],
    junit: dict[str, str],
    target_count: int = 258,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": len(rows),
        "expected_total": target_count,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "automated": 0,
        "semi_automated": 0,
        "manual": 0,
    }
    per_spec: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    )
    per_check_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    )

    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        rid = f"{row['id']}-{row['check_kind']}"
        outcome = junit.get(rid, "unrun")
        automation = row.get("automation", "auto")
        spec = row["spec"]
        kind = row["check_kind"]

        per_spec[spec]["total"] += 1
        per_check_kind[kind]["total"] += 1

        if outcome == "passed":
            summary["passed"] += 1
            per_spec[spec]["passed"] += 1
            per_check_kind[kind]["passed"] += 1
        elif outcome == "failed":
            summary["failed"] += 1
            per_spec[spec]["failed"] += 1
            per_check_kind[kind]["failed"] += 1
        elif outcome == "skipped":
            summary["skipped"] += 1
            per_spec[spec]["skipped"] += 1
            per_check_kind[kind]["skipped"] += 1

        if automation == "auto":
            summary["automated"] += 1
        elif automation == "semi":
            summary["semi_automated"] += 1
        elif automation == "manual":
            summary["manual"] += 1

        enriched_rows.append(
            {
                "id": row["id"],
                "spec": spec,
                "check_kind": kind,
                "automation": automation,
                "outcome": outcome,
            }
        )

    total = summary["expected_total"] or 1
    summary["automation_ratio"] = round(summary["automated"] / total, 4)
    summary["automation_target"] = AUTOMATION_TARGET
    summary["automation_target_met"] = summary["automation_ratio"] + 1e-9 >= AUTOMATION_TARGET

    return {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "summary": summary,
        "per_spec": dict(sorted(per_spec.items())),
        "per_check_kind": dict(sorted(per_check_kind.items())),
        "rows": enriched_rows,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--yaml",
        default=str(Path(__file__).parent / "acceptance_criteria.yaml"),
        help="path to acceptance_criteria.yaml",
    )
    p.add_argument(
        "--junit",
        default=str(Path(__file__).parent / "acceptance_junit.xml"),
        help="path to pytest junit XML",
    )
    p.add_argument(
        "--out",
        default=str(Path(__file__).parent / "aggregate_acceptance.json"),
        help="output JSON path",
    )
    p.add_argument(
        "--target-count",
        type=int,
        default=258,
        help="planned acceptance criteria total (default 258)",
    )
    args = p.parse_args(argv)

    rows = parse_yaml(Path(args.yaml))
    junit = parse_junit(Path(args.junit))
    report = build_report(rows, junit, target_count=args.target_count)

    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[aggregate_acceptance] wrote {args.out} "
        f"(rows={report['summary']['total']}, "
        f"passed={report['summary']['passed']}, "
        f"failed={report['summary']['failed']}, "
        f"automation_ratio={report['summary']['automation_ratio']})"
    )
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
