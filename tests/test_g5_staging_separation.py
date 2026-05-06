from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "report_repo_staging_separation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("report_repo_staging_separation", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_report_counts_staging_roots_and_keeps_commands_inert(tmp_path: Path) -> None:
    mod = _load_module()
    staging = tmp_path / "autonomath_staging"
    api_meta = staging / "api_meta"
    api_meta.mkdir(parents=True)
    (staging / "README.md").write_text("# Stage\n\nnotes\n", encoding="utf-8")
    (api_meta / "tool.py").write_text("print('one')\nprint('two')\n", encoding="utf-8")
    (api_meta / "cache.db").write_bytes(b"SQLite format 3\x00binary")

    salvage = tmp_path / "analysis_wave18" / "_salvage_from_tmp"
    salvage.mkdir(parents=True)
    (salvage / "plan.md").write_text("line 1\nline 2", encoding="utf-8")

    protected_archive = tmp_path / "src" / "jpintel_mcp" / "_archive" / "old_staging"
    protected_archive.mkdir(parents=True)
    (protected_archive / "ignored.py").write_text("should_not_count()\n", encoding="utf-8")

    report = mod.build_report(repo_root=tmp_path)

    assert report["read_mode"] == {
        "filesystem_read_only": True,
        "git_status_only": True,
        "network_access_performed": False,
        "llm_api_calls_performed": False,
        "moves_performed": False,
        "deletes_performed": False,
        "commands_are_strings_only": True,
    }
    assert report["completion_status"] == {
        "G5": "readiness_only",
        "complete": False,
        "reason": "No staging extraction moves/deletes were performed.",
    }
    assert report["requires_owner_confirmation"] is True
    assert report["ready_for_extraction"] is False
    assert report["git"]["available"] is False

    root_by_path = {root["path"]: root for root in report["staging_roots"]}
    assert set(root_by_path) == {"analysis_wave18/_salvage_from_tmp", "autonomath_staging"}
    assert report["totals"]["file_count"] == 4
    assert report["totals"]["text_file_count"] == 3
    assert report["totals"]["binary_file_count"] == 1
    assert report["totals"]["loc"] == 7
    assert report["totals"]["db_like_file_count"] == 1

    assert root_by_path["autonomath_staging"]["file_count"] == 3
    assert root_by_path["autonomath_staging"]["loc"] == 5
    assert root_by_path["autonomath_staging"]["db_like_file_count"] == 1
    owner_by_top = {
        owner["top_level"]: owner
        for owner in root_by_path["autonomath_staging"]["ownership_estimate"]
    }
    assert owner_by_top["api_meta"]["owner_area"] == "api_mcp"
    assert owner_by_top["."]["owner_area"] == "mixed_or_unknown"

    assert all(isinstance(command, str) for command in report["dry_run_commands"])
    assert len(report["dry_run_commands"]) == 2
    assert all("--dry-run" in command for command in report["dry_run_commands"])
    assert all("rsync" in command for command in report["dry_run_commands"])
    assert "owner_confirmation_required" in {blocker["code"] for blocker in report["blockers"]}
    assert "runtime_artifacts:autonomath_staging" in {
        blocker["code"] for blocker in report["blockers"]
    }
    assert "old_staging" not in json.dumps(report)


def test_cli_writes_json_and_markdown_outputs(tmp_path: Path) -> None:
    mod = _load_module()
    staging = tmp_path / "autonomath_staging"
    staging.mkdir()
    (staging / "README.md").write_text("ready\n", encoding="utf-8")
    output = tmp_path / "analysis" / "staging.json"
    markdown_output = tmp_path / "analysis" / "staging.md"

    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["totals"]["file_count"] == 1
    assert payload["completion_status"]["complete"] is False
    assert payload["requires_owner_confirmation"] is True
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "# G5 Staging Separation Readiness" in markdown
    assert "G5 complete: False" in markdown
