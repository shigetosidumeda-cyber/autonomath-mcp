"""Test stubs for DEEP-58 aggregator (session A draft, jpcite v0.3.4).

8 cases:
  1. synthetic verify result aggregate produces the 4 blocker pane
  2. HTML render syntax validation (parses as well-formed HTML5)
  3. 4 blocker status all combinations (BLOCKED / PARTIAL / RESOLVED)
  4. 8 ACK boolean accuracy from operator_ack_signoff stdout
  5. 33 spec status table renders all DEEP-22..54 rows
  6. LLM API import = 0 (text grep on the script body)
  7. GHA workflow YAML syntax validates
  8. graceful degradation on verify-script timeout / FileNotFoundError

Tests use only stdlib + jinja2 + pytest. They mock subprocess, so no
real verify scripts need to exist on the filesystem.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

import pytest

# Resolve the draft module path. After codex-lane promotion the script
# lives in scripts/cron/, template in scripts/templates/, workflow in
# .github/workflows/. This block tolerates both layouts.
DRAFT_DIR = Path(__file__).resolve().parent
REPO_ROOT = DRAFT_DIR.parent if DRAFT_DIR.name == "tests" else DRAFT_DIR
SCRIPT_PATH = REPO_ROOT / "scripts" / "cron" / "aggregate_production_gate_status.py"
TEMPLATE_PATH = REPO_ROOT / "scripts" / "templates" / "production_gate.html.j2"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "production-gate-dashboard-daily.yml"
# Fallback to draft inbox layout if codex-lane files not yet placed.
if not SCRIPT_PATH.exists():
    SCRIPT_PATH = DRAFT_DIR / "aggregate_production_gate_status.py"
    TEMPLATE_PATH = DRAFT_DIR / "production_gate.html.j2"
    WORKFLOW_PATH = DRAFT_DIR / "production-gate-dashboard-daily.yml"

sys.path.insert(0, str(SCRIPT_PATH.parent))
import aggregate_production_gate_status as agg  # noqa: E402

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_completed(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["dummy"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class _HTMLValidator(HTMLParser):
    """Tiny HTML validator: balanced tag stack + no parse errors."""

    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unbalanced </{tag}> at depth {len(self.stack)}")
            return
        self.stack.pop()

    def error(self, message: str) -> None:  # pragma: no cover
        self.errors.append(message)


# ---------------------------------------------------------------------------
# 1. synthetic verify result aggregate
# ---------------------------------------------------------------------------


def test_synthetic_verify_result_aggregate(tmp_path: Path) -> None:
    """run_verify produces a normalized VerifyResult with sha256 + status."""

    with mock.patch.object(subprocess, "run", return_value=_make_completed(0, "ok\n")):
        result = agg.run_verify("scripts/dummy.py", repo_root=tmp_path)
    assert result.returncode == 0
    assert result.status == "RESOLVED"
    assert len(result.sha256) == 64
    assert result.sha256 == agg._sha256_text("ok\n")


# ---------------------------------------------------------------------------
# 2. HTML render syntax validation
# ---------------------------------------------------------------------------


def test_html_render_syntax(tmp_path: Path) -> None:
    snap = agg.GateSnapshot(
        snapshot_date="2026-05-07",
        git_head_sha="abc1234",
        last_update_utc="2026-05-07T21:00:00+00:00",
        last_update_jst="2026-05-08T06:00:00+09:00",
    )
    snap.blockers = [
        {
            "id": b["id"],
            "title": b["title"],
            "deep": b["deep"],
            "status": "PARTIAL",
            "evidence_url": b["verify_cmd"],
            "sha256": "deadbeef" * 8,
            "duration_ms": 100,
            "stderr_tail": "",
        }
        for b in agg.BLOCKERS
    ]
    snap.acks = [
        {
            "id": a["id"],
            "title": a["title"],
            "deep": a["deep"],
            "status": "RESOLVED",
            "evidence_url": "scripts/operator_ack_signoff.py",
        }
        for a in agg.ACK_BOOLEANS
    ]
    snap.specs = [
        {
            "id": s,
            "title": f"{s} implementation",
            "status": "PARTIAL",
            "last_check": "",
            "evidence_url": f"docs/_internal/{s}_*.md",
            "sha256": "",
        }
        for s in agg.SPEC_IDS
    ]
    out = tmp_path / "out.html"
    agg.render_html(snap, TEMPLATE_PATH.parent, out)
    text = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in text.lower()
    parser = _HTMLValidator()
    parser.feed(text)
    parser.close()
    assert parser.errors == [], parser.errors
    assert parser.stack == [], f"unclosed tags: {parser.stack}"
    # Section headings present.
    assert "4 blocker" in text
    assert "8 ACK boolean" in text
    assert "33 spec implementation" in text


# ---------------------------------------------------------------------------
# 3. 4 blocker status all combinations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "returncode,timed_out,error,expected",
    [
        (0, False, None, "RESOLVED"),
        (1, False, None, "BLOCKED"),
        (-1, True, "timeout", "PARTIAL"),
        (-2, False, "FileNotFoundError", "PARTIAL"),
    ],
)
def test_blocker_status_combinations(
    returncode: int, timed_out: bool, error: str | None, expected: str
) -> None:
    vr = agg.VerifyResult(
        cmd="x",
        returncode=returncode,
        stdout="",
        stderr="",
        sha256="",
        duration_ms=0,
        timed_out=timed_out,
        error=error,
    )
    assert vr.status == expected


# ---------------------------------------------------------------------------
# 4. 8 ACK boolean accuracy
# ---------------------------------------------------------------------------


def test_ack_boolean_accuracy() -> None:
    payload = {
        "acks": {
            "ACK_MIGRATION_TARGETS": True,
            "ACK_FINGERPRINT_CLEAN": False,
            "ACK_WORKFLOWS_TRACKED": True,
            "ACK_DELIVERY_STRICT": "RESOLVED",
            "ACK_SMOKE_RUNBOOK": "PARTIAL",
            "ACK_LANE_ENFORCED": False,
            "ACK_RELEASE_READINESS": True,
            "ACK_PROD_RUNBOOK": "BLOCKED",
        }
    }
    parsed = agg._ack_status_from_signoff(json.dumps(payload))
    assert parsed["ACK_MIGRATION_TARGETS"] == "RESOLVED"
    assert parsed["ACK_FINGERPRINT_CLEAN"] == "BLOCKED"
    assert parsed["ACK_DELIVERY_STRICT"] == "RESOLVED"
    assert parsed["ACK_SMOKE_RUNBOOK"] == "PARTIAL"
    assert parsed["ACK_PROD_RUNBOOK"] == "BLOCKED"
    # The collect_acks fan-out fills missing IDs with PARTIAL.
    rows = agg.collect_acks(Path("/tmp"), json.dumps({"acks": {}}))
    assert len(rows) == 8
    assert all(r["status"] == "PARTIAL" for r in rows)


# ---------------------------------------------------------------------------
# 5. 33 spec status table render
# ---------------------------------------------------------------------------


def test_33_spec_table_render(tmp_path: Path) -> None:
    assert len(agg.SPEC_IDS) == 33
    snap = agg.GateSnapshot(
        snapshot_date="2026-05-07",
        git_head_sha="abc1234",
        last_update_utc="2026-05-07T21:00:00+00:00",
        last_update_jst="2026-05-08T06:00:00+09:00",
    )
    snap.specs = [
        {
            "id": s,
            "title": f"{s} implementation",
            "status": "PARTIAL",
            "last_check": "",
            "evidence_url": f"docs/_internal/{s}_*.md",
            "sha256": "",
        }
        for s in agg.SPEC_IDS
    ]
    out = tmp_path / "out.html"
    agg.render_html(snap, TEMPLATE_PATH.parent, out)
    text = out.read_text(encoding="utf-8")
    for spec_id in agg.SPEC_IDS:
        assert spec_id in text, f"missing spec row {spec_id}"


# ---------------------------------------------------------------------------
# 6. LLM API import = 0
# ---------------------------------------------------------------------------


def test_no_llm_api_imports() -> None:
    body = SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden_modules = [
        r"^\s*import\s+anthropic\b",
        r"^\s*from\s+anthropic\b",
        r"^\s*import\s+openai\b",
        r"^\s*from\s+openai\b",
        r"^\s*import\s+google\.generativeai\b",
        r"^\s*from\s+google\.generativeai\b",
        r"^\s*import\s+claude_agent_sdk\b",
        r"^\s*from\s+claude_agent_sdk\b",
    ]
    for pattern in forbidden_modules:
        assert not re.search(pattern, body, flags=re.MULTILINE), pattern
    forbidden_envs = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]
    code_lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
    code_text = "\n".join(code_lines)
    for env_var in forbidden_envs:
        assert env_var not in code_text, env_var


# ---------------------------------------------------------------------------
# 7. GHA workflow yaml syntax
# ---------------------------------------------------------------------------


def test_workflow_yaml_syntax() -> None:
    yaml = pytest.importorskip("yaml")
    with WORKFLOW_PATH.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict)
    assert doc["name"] == "production-gate-dashboard-daily"
    # PyYAML coerces the bare `on:` key to Python True.
    on_key = True if True in doc else "on"
    assert on_key in doc
    schedule = doc[on_key]["schedule"]
    assert any(item.get("cron") == "0 21 * * *" for item in schedule)
    assert "aggregate" in doc["jobs"]
    assert "on-failure" in doc["jobs"]


# ---------------------------------------------------------------------------
# 8. graceful degradation
# ---------------------------------------------------------------------------


def test_graceful_degradation_on_timeout(tmp_path: Path) -> None:
    timeout_exc = subprocess.TimeoutExpired(cmd=["dummy"], timeout=5)
    timeout_exc.stdout = ""
    timeout_exc.stderr = ""
    with mock.patch.object(subprocess, "run", side_effect=timeout_exc):
        result = agg.run_verify("scripts/dummy.py", repo_root=tmp_path, timeout_sec=5)
    assert result.timed_out is True
    assert result.status == "PARTIAL"
    assert "TIMEOUT" in result.stderr


def test_graceful_degradation_on_missing_script(tmp_path: Path) -> None:
    with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("no such file")):
        result = agg.run_verify("scripts/missing.py", repo_root=tmp_path)
    assert result.error is not None
    assert result.status == "PARTIAL"


def test_collect_specs_missing_evidence_is_partial(tmp_path: Path) -> None:
    rows = agg.collect_specs(tmp_path)
    assert len(rows) == 33
    for row in rows:
        assert row["status"] == "PARTIAL"
        assert row["last_check"] == ""
