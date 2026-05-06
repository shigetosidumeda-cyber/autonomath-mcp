from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "gbiz-ingest-monthly.yml"


def _load_workflow() -> dict[str, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "gbiz-ingest-monthly.yml must parse to a mapping"
    return data


def _on_block(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML still follows YAML 1.1 bool resolution, so GitHub's `on:` key may
    # parse as True. Keep the test focused on the workflow contract.
    block = workflow.get("on", workflow.get(True))
    assert isinstance(block, dict), "workflow must define triggers under `on:`"
    return block


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1, f"expected one step named {name!r}"
    return matches[0]


def test_workflow_dispatch_mode_contract() -> None:
    mode = _on_block(_load_workflow())["workflow_dispatch"]["inputs"]["mode"]

    assert mode == {
        "description": "ingest mode: both / bulk-only / delta-only",
        "required": False,
        "default": "both",
        "type": "choice",
        "options": ["both", "bulk-only", "delta-only"],
    }


def test_fly_ssh_target_and_ingest_commands() -> None:
    workflow = _load_workflow()
    assert workflow["env"]["FLY_APP"] == "autonomath-api"

    jobs = workflow["jobs"]
    bulk_run = _step(
        jobs["bulk-cold-start"],
        "Run gBizINFO bulk JSONL monthly on Fly machine",
    )["run"]
    delta_run = _step(
        jobs["delta-pulls"],
        "Run gBizINFO ${{ matrix.family }} delta on Fly machine",
    )["run"]

    expected_fragments = {
        "bulk": (
            bulk_run,
            "/app/scripts/cron/ingest_gbiz_bulk_jsonl_monthly.py",
            "--log-file /data/gbiz_bulk_load_log.jsonl",
            "tee gbiz_bulk_load.out",
        ),
        "delta": (
            delta_run,
            "/app/scripts/cron/ingest_gbiz_${{ matrix.family }}_v2.py",
            "--log-file /data/gbiz_delta_load_log.jsonl",
            "tee gbiz_${{ matrix.family }}_delta.out",
        ),
    }
    for label, (run, script, log_file, tee_path) in expected_fragments.items():
        assert 'flyctl ssh console -a "${FLY_APP}" -C' in run, f"{label} must run via Fly SSH"
        assert script in run
        assert "--db /data/autonomath.db" in run
        assert log_file in run
        assert tee_path in run


def test_delta_matrix_covers_expected_gbiz_families() -> None:
    matrix = _load_workflow()["jobs"]["delta-pulls"]["strategy"]["matrix"]

    assert matrix["family"] == [
        "corporate",
        "subsidy",
        "certification",
        "commendation",
        "procurement",
    ]


def test_failure_notifications_are_failure_only() -> None:
    jobs = _load_workflow()["jobs"]

    for job_name, suffix in (
        ("bulk-cold-start", "bulk failure"),
        ("delta-pulls", "delta failure"),
    ):
        issue = _step(jobs[job_name], f"Open issue on {suffix}")
        slack = _step(jobs[job_name], f"Slack notify on {suffix}")

        assert issue["if"] == "failure()"
        assert issue["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert slack["if"] == "failure() && env.SLACK_WEBHOOK_INGEST != ''"
        assert slack["env"]["SLACK_WEBHOOK_INGEST"] == "${{ secrets.SLACK_WEBHOOK_INGEST }}"


def test_github_secret_references_are_expected() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    secret_refs = set(re.findall(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}", text))

    assert secret_refs == {"FLY_API_TOKEN", "SLACK_WEBHOOK_INGEST"}
