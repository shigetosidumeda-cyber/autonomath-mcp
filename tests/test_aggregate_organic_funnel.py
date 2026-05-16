"""Tests for ``scripts/cron/aggregate_organic_funnel_daily.py`` (Wave 49 G1).

Coverage targets:
  1. ``parse_beacon_blob`` rejects malformed JSON / missing fields.
  2. ``aggregate_records`` computes 5-stage uniq + conversion correctly.
  3. ``aggregate_records`` filters bot session_ids (defense-in-depth).
  4. ``evaluate_g1_gate`` flips achieved=True after 3 consecutive uniq>=10.
  5. ``evaluate_g1_gate`` resets the streak when a day drops below threshold.
  6. ``run`` (dry-run) reads from a fake R2 client + writes nothing.
  7. ``run`` (live mode in tmp_path) writes JSONL + sidecar atomically.
  8. ``run`` emits ``::organic-funnel-g1-achieved::`` marker on transition.
  9. LLM API import = 0 (text grep on the script body).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "cron" / "aggregate_organic_funnel_daily.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("aggregate_organic_funnel_daily", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


agg = _load_module()


# ---------------------------------------------------------------------------
# Fake R2 client — drop-in for ``_r2_client`` module interface.
# ---------------------------------------------------------------------------


class FakeR2:
    """In-memory R2 stand-in matching the ``_r2_client`` surface."""

    def __init__(self, objects: dict[str, str]) -> None:
        # objects: {full_key: json_text}
        self._objects = objects

    def list_keys(self, prefix: str, *, bucket: str | None = None) -> list[tuple[str, Any, int]]:
        import datetime as _dt

        out: list[tuple[str, Any, int]] = []
        for k, v in self._objects.items():
            if k.startswith(prefix):
                out.append((k, _dt.datetime.now(_dt.UTC), len(v.encode("utf-8"))))
        return out

    def download(self, key: str, local: Path, *, bucket: str | None = None) -> None:
        if key not in self._objects:
            raise FileNotFoundError(key)
        local.write_text(self._objects[key], encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_beacon_blob_rejects_malformed() -> None:
    assert agg.parse_beacon_blob("not-json") is None
    assert agg.parse_beacon_blob("null") is None
    assert agg.parse_beacon_blob('{"session_id": "abc"}') is None  # missing fields
    valid = json.dumps(
        {
            "session_id": "abc",
            "step": "landing",
            "event": "view",
            "ts": 1715900000000,
        }
    )
    parsed = agg.parse_beacon_blob(valid)
    assert parsed is not None
    assert parsed["session_id"] == "abc"


def test_aggregate_records_five_stage_funnel() -> None:
    # 10 landing sessions, 5 progress to free, 3 to signup, 2 to topup,
    # 1 to calc_engaged. All distinct session_ids. ts is irrelevant.
    records: list[dict[str, Any]] = []
    for i in range(10):
        records.append(
            {
                "session_id": f"s{i:02d}",
                "step": "landing",
                "event": "view",
                "ts": 1,
            }
        )
    for i in range(5):
        records.append(
            {
                "session_id": f"s{i:02d}",
                "step": "free",
                "event": "step_complete",
                "ts": 2,
            }
        )
    for i in range(3):
        records.append(
            {
                "session_id": f"s{i:02d}",
                "step": "signup",
                "event": "step_complete",
                "ts": 3,
            }
        )
    for i in range(2):
        records.append(
            {
                "session_id": f"s{i:02d}",
                "step": "topup",
                "event": "step_complete",
                "ts": 4,
            }
        )
    records.append(
        {
            "session_id": "s00",
            "step": "calc_engaged",
            "event": "step_complete",
            "ts": 5,
        }
    )

    out = agg.aggregate_records(records)
    assert out["uniq_visitor"] == 10
    assert out["stage_uniq_sessions"] == {
        "landing": 10,
        "free": 5,
        "signup": 3,
        "topup": 2,
        "calc_engaged": 1,
    }
    assert out["conversion_rate"] == {
        "landing": 1.0,
        "free": 0.5,
        "signup": 0.3,
        "topup": 0.2,
        "calc_engaged": 0.1,
    }
    assert out["total_events"] == 21


def test_aggregate_records_filters_bot_session_ids() -> None:
    records = [
        {
            "session_id": "real-uuid-1",
            "step": "landing",
            "event": "view",
            "ts": 1,
        },
        {
            "session_id": "gptbot-crawler",  # filtered out
            "step": "landing",
            "event": "view",
            "ts": 1,
        },
    ]
    out = agg.aggregate_records(records)
    assert out["uniq_visitor"] == 1
    assert out["stage_uniq_sessions"]["landing"] == 1


def test_g1_gate_flips_after_three_consecutive_days() -> None:
    rolling = [
        {"date": "2026-05-13", "uniq_visitor": 12},
        {"date": "2026-05-14", "uniq_visitor": 15},
        {"date": "2026-05-15", "uniq_visitor": 11},
    ]
    g1 = agg.evaluate_g1_gate(rolling, today_iso="2026-05-15T19:30Z")
    assert g1["achieved"] is True
    assert g1["achieved_on"] == "2026-05-15"
    assert g1["current_consecutive_days"] == 3
    assert g1["longest_consecutive_days"] == 3


def test_g1_gate_resets_streak_on_low_day() -> None:
    rolling = [
        {"date": "2026-05-13", "uniq_visitor": 12},
        {"date": "2026-05-14", "uniq_visitor": 4},  # break
        {"date": "2026-05-15", "uniq_visitor": 11},
    ]
    g1 = agg.evaluate_g1_gate(rolling, today_iso="2026-05-15T19:30Z")
    assert g1["achieved"] is False
    assert g1["current_consecutive_days"] == 1
    assert g1["longest_consecutive_days"] == 1


def _make_beacon(session_id: str, step: str, event: str = "view") -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "step": step,
            "event": event,
            "ts": 1715900000000,
            "ua_hash": "deadbe",
            "page": "/",
        }
    )


def test_run_dry_run_does_not_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Redirect output paths into tmp_path so we can assert no writes.
    monkeypatch.setattr(agg, "JSONL_OUT", tmp_path / "organic_funnel_daily.jsonl")
    monkeypatch.setattr(agg, "SIDECAR_OUT", tmp_path / "organic_funnel_state.json")
    objs = {
        f"funnel/2026-05-15/s{i:02d}-1.json": _make_beacon(f"s{i:02d}", "landing") for i in range(3)
    }
    fake = FakeR2(objs)
    result = agg.run(
        date_str="2026-05-15",
        dry_run=True,
        bucket="test-bucket",
        prefix="funnel",
        emit_issue=False,
        r2_client=fake,
    )
    assert result["today_row"]["uniq_visitor"] == 3
    assert result["today_row"]["n_objects"] == 3
    # Dry-run must NOT create either output file.
    assert not (tmp_path / "organic_funnel_daily.jsonl").exists()
    assert not (tmp_path / "organic_funnel_state.json").exists()


def test_run_live_writes_jsonl_and_sidecar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jsonl = tmp_path / "organic_funnel_daily.jsonl"
    sidecar = tmp_path / "organic_funnel_state.json"
    monkeypatch.setattr(agg, "JSONL_OUT", jsonl)
    monkeypatch.setattr(agg, "SIDECAR_OUT", sidecar)
    # 12 distinct landing sessions to trip the uniq >= 10 threshold.
    objs = {
        f"funnel/2026-05-15/s{i:02d}-1.json": _make_beacon(f"s{i:02d}", "landing")
        for i in range(12)
    }
    fake = FakeR2(objs)
    result = agg.run(
        date_str="2026-05-15",
        dry_run=False,
        bucket="test-bucket",
        prefix="funnel",
        emit_issue=False,
        r2_client=fake,
    )
    assert jsonl.exists()
    assert sidecar.exists()
    row = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[-1])
    assert row["uniq_visitor"] == 12
    side = json.loads(sidecar.read_text(encoding="utf-8"))
    assert side["wave"] == "49-G1"
    assert side["g1_state"]["current_consecutive_days"] == 1
    assert side["g1_state"]["achieved"] is False  # only 1 day so far


def test_run_emits_g1_marker_on_transition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jsonl = tmp_path / "organic_funnel_daily.jsonl"
    sidecar = tmp_path / "organic_funnel_state.json"
    monkeypatch.setattr(agg, "JSONL_OUT", jsonl)
    monkeypatch.setattr(agg, "SIDECAR_OUT", sidecar)
    # Pre-seed 2 prior days at uniq=11 each — today (#3) trips the gate.
    jsonl.write_text(
        json.dumps({"date": "2026-05-13", "uniq_visitor": 11})
        + "\n"
        + json.dumps({"date": "2026-05-14", "uniq_visitor": 11})
        + "\n",
        encoding="utf-8",
    )
    objs = {
        f"funnel/2026-05-15/s{i:02d}-1.json": _make_beacon(f"s{i:02d}", "landing")
        for i in range(15)
    }
    fake = FakeR2(objs)
    result = agg.run(
        date_str="2026-05-15",
        dry_run=False,
        bucket="test-bucket",
        prefix="funnel",
        emit_issue=True,
        r2_client=fake,
    )
    captured = capsys.readouterr().out
    assert "::organic-funnel-g1-achieved::" in captured
    side = json.loads(sidecar.read_text(encoding="utf-8"))
    assert side["g1_state"]["achieved"] is True
    assert side["achievement_transition_this_run"] is True


def test_no_llm_api_imports_in_script_body() -> None:
    body = SCRIPT_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "claude_agent_sdk",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert forbidden not in body, f"forbidden LLM marker in script: {forbidden}"
