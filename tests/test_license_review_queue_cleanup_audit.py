from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "audit_license_review_queue_cleanup.py"


def _load_module():
    etl_dir = SCRIPT_PATH.parent
    if str(etl_dir) not in sys.path:
        sys.path.insert(0, str(etl_dir))
    spec = importlib.util.spec_from_file_location("license_review_cleanup_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(
    source_id: str,
    license_value: str,
    domain: str,
    source_url: str,
    linked_entity_count: str = "1",
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "license": license_value,
        "domain": domain,
        "source_type": "primary",
        "source_url": source_url,
        "first_seen": "2026-05-01",
        "last_verified": "",
        "linked_entity_count": linked_entity_count,
        "sample_entity_ids": "program:one",
    }


def test_cleanup_audit_separates_drop_bulk_safe_blocked_and_pending() -> None:
    mod = _load_module()
    rows = [
        _row("1", "unknown", "", "quarantined://banned/1", "0"),
        _row("2", "unknown", "www.meti.go.jp", "https://www.meti.go.jp/policy/a"),
        _row("3", "proprietary", "example.co.jp", "https://example.co.jp/a"),
        _row("4", "unknown", "manual.example", "https://manual.example/a"),
        _row("5", "unknown", "manual-zero.example", "https://manual-zero.example/a", "0"),
    ]

    report, classified = mod.build_cleanup_report(rows)

    assert report["by_action"] == {
        "bulk_safe_government_domain": 1,
        "drop_internal_or_quarantined": 1,
        "drop_unlinked": 1,
        "keep_blocked_by_domain_rule": 1,
        "pending_manual_review": 1,
    }
    by_id = {item.row["source_id"]: item for item in classified}
    assert by_id["2"].recommended_license == "gov_standard_v2.0"
    assert by_id["3"].recommended_license == "proprietary"
    assert report["public_export_guard"]["pending_rows_are_not_publishable"] is True


def test_cleanup_audit_cli_writes_nonblocking_report_and_optional_strict_exit(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    input_csv = tmp_path / "queue.csv"
    json_output = tmp_path / "report.json"
    classified_output = tmp_path / "classified.csv"
    rows = [
        _row("10", "unknown", "manual.example", "https://manual.example/a"),
        _row("11", "unknown", "www.meti.go.jp", "https://www.meti.go.jp/policy/a"),
    ]
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=mod.REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    rc = mod.main(
        [
            "--input",
            str(input_csv),
            "--json-output",
            str(json_output),
            "--classified-output",
            str(classified_output),
        ]
    )

    assert rc == 0
    report = json.loads(json_output.read_text(encoding="utf-8"))
    assert report["by_action"]["bulk_safe_government_domain"] == 1
    assert report["by_action"]["pending_manual_review"] == 1
    with classified_output.open(encoding="utf-8", newline="") as f:
        classified_rows = list(csv.DictReader(f))
    assert {row["cleanup_action"] for row in classified_rows} == {
        "bulk_safe_government_domain",
        "pending_manual_review",
    }

    strict_rc = mod.main(
        [
            "--input",
            str(input_csv),
            "--json-output",
            str(json_output),
            "--fail-on-pending",
        ]
    )
    assert strict_rc == 1
