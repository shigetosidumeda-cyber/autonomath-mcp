"""Contract tests for tools/offline/bench_prefetch_probe.py.

The probe is an operator-only script, so these tests invoke it via
subprocess instead of importing from tools.offline. The script is expected
to read the canonical 30-query bench CSV, call the local
EvidencePacketComposer with no network or LLM calls, and emit a JSON
summary plus optional per-query CSV metrics.
"""
from __future__ import annotations

import ast
import csv
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "tools" / "offline" / "bench_prefetch_probe.py"
BENCH_QUERIES_CSV = (
    REPO_ROOT / "tools" / "offline" / "bench_queries_2026_04_30.csv"
)


def _run_probe(
    *args: str,
    pythonpath: Path | None = None,
    call_log: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if pythonpath is not None:
        env["PYTHONPATH"] = (
            str(pythonpath)
            if not env.get("PYTHONPATH")
            else f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
        )
    if call_log is not None:
        env["PREFETCH_PROBE_CALL_LOG"] = str(call_log)

    return subprocess.run(
        [sys.executable, str(PROBE_PATH), *args],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _install_offline_composer_stub(tmp_path: Path) -> Path:
    """Install a PYTHONPATH-first jpintel_mcp stub used only by the subprocess."""
    package_root = tmp_path / "stubpkg"
    services = package_root / "jpintel_mcp" / "services"
    services.mkdir(parents=True)
    (package_root / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import socket

            def _blocked(*args, **kwargs):
                raise AssertionError("bench_prefetch_probe.py must not use network")

            socket.create_connection = _blocked
            socket.socket.connect = _blocked
            """
        ),
        encoding="utf-8",
    )
    (package_root / "jpintel_mcp" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "jpintel_mcp" / "config.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path

            class _Settings:
                db_path = Path("stub-jpintel.sqlite")
                autonomath_db_path = Path("stub-autonomath.sqlite")

            settings = _Settings()
            """
        ),
        encoding="utf-8",
    )
    (services / "__init__.py").write_text("", encoding="utf-8")
    (services / "evidence_packet.py").write_text(
        textwrap.dedent(
            """
            import json
            import os

            class EvidencePacketComposer:
                def __init__(self, jpintel_db, autonomath_db):
                    self.jpintel_db = str(jpintel_db)
                    self.autonomath_db = str(autonomath_db)

                def compose_for_query(self, query_text, **kwargs):
                    call_log = os.environ["PREFETCH_PROBE_CALL_LOG"]
                    with open(call_log, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "jpintel_db": self.jpintel_db,
                            "autonomath_db": self.autonomath_db,
                            "query_text": query_text,
                            "kwargs": kwargs,
                        }, ensure_ascii=False) + "\\n")

                    marker = len(query_text)
                    record_count = marker % 3 + 1
                    precomputed_count = marker % 2 + 1
                    records = []
                    for idx in range(record_count):
                        rec = {"record_id": f"rec_{idx}"}
                        if idx < precomputed_count:
                            rec["precomputed"] = {"basis": "fixture"}
                        records.append(rec)
                    return {
                        "packet_id": f"evp_{marker}",
                        "records": records,
                        "compression": {
                            "packet_tokens_estimate": 1000 + marker,
                        },
                    }
            """
        ),
        encoding="utf-8",
    )
    return package_root


def _canonical_query_rows() -> list[dict[str, str]]:
    with BENCH_QUERIES_CSV.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_probe_script_exists_at_operator_path() -> None:
    assert PROBE_PATH.exists(), (
        "expected offline prefetch probe script at "
        "tools/offline/bench_prefetch_probe.py"
    )


def test_probe_reads_canonical_queries_and_writes_summary_and_rows(
    tmp_path: Path,
) -> None:
    rows_csv = tmp_path / "prefetch_rows.csv"
    call_log = tmp_path / "composer_calls.jsonl"
    stub_path = _install_offline_composer_stub(tmp_path)
    result = _run_probe(
        "--queries-csv",
        str(BENCH_QUERIES_CSV),
        "--rows-csv",
        str(rows_csv),
        pythonpath=stub_path,
        call_log=call_log,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    query_rows = _canonical_query_rows()
    assert summary["total_queries"] == 30
    assert summary["zero_result_queries"] == 0
    assert summary["queries_with_precomputed"] == 30
    assert len(summary["rows"]) == 30

    with call_log.open("r", encoding="utf-8") as f:
        calls = [json.loads(line) for line in f if line.strip()]
    assert [call["query_text"] for call in calls] == [
        row["query_text"] for row in query_rows
    ]
    assert {call["jpintel_db"] for call in calls} == {"stub-jpintel.sqlite"}
    assert {call["autonomath_db"] for call in calls} == {"stub-autonomath.sqlite"}
    assert all(call["kwargs"].get("include_compression") is True for call in calls)
    assert all(call["kwargs"].get("include_rules") is False for call in calls)

    with rows_csv.open("r", encoding="utf-8", newline="") as f:
        output_rows = list(csv.DictReader(f))
    assert len(output_rows) == 30
    assert set(output_rows[0]) >= {
        "query_id",
        "domain",
        "query_text",
        "records_returned",
        "precomputed_record_count",
        "packet_tokens_estimate",
    }
    assert [row["query_id"] for row in output_rows] == [
        row["query_id"] for row in query_rows
    ]
    assert all(int(row["records_returned"]) >= 1 for row in output_rows)
    assert all(int(row["precomputed_record_count"]) >= 1 for row in output_rows)
    assert all(int(row["packet_tokens_estimate"]) >= 1000 for row in output_rows)

    assert summary["records_total"] == sum(
        int(row["records_returned"]) for row in output_rows
    )
    assert summary["precomputed_records_total"] == sum(
        int(row["precomputed_record_count"]) for row in output_rows
    )
    assert sum(
        int(row["packet_tokens_estimate"]) for row in output_rows
    ) == sum(int(row["packet_tokens_estimate"]) for row in summary["rows"])


def test_probe_can_emit_json_summary_without_rows_csv(tmp_path: Path) -> None:
    call_log = tmp_path / "composer_calls.jsonl"
    stub_path = _install_offline_composer_stub(tmp_path)

    result = _run_probe(
        "--queries-csv",
        str(BENCH_QUERIES_CSV),
        pythonpath=stub_path,
        call_log=call_log,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["total_queries"] == 30
    assert len(summary["rows"]) == 30
    assert summary["records_total"] == sum(
        int(row["records_returned"]) for row in summary["rows"]
    )
    assert summary["precomputed_records_total"] == sum(
        int(row["precomputed_record_count"]) for row in summary["rows"]
    )
    assert all(row["packet_tokens_estimate"] for row in summary["rows"])


def test_probe_file_has_no_llm_or_network_imports() -> None:
    assert PROBE_PATH.exists(), (
        "expected offline prefetch probe script at "
        "tools/offline/bench_prefetch_probe.py"
    )
    tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
    forbidden_modules = {
        "anthropic",
        "claude_agent_sdk",
        "google.generativeai",
        "httpx",
        "openai",
        "requests",
        "urllib.request",
    }
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_modules or alias.name.split(".")[0] in {
                    "anthropic",
                    "httpx",
                    "openai",
                    "requests",
                }:
                    hits.append(f"import {alias.name}")
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (
                node.module in forbidden_modules
                or node.module.split(".")[0]
                in {"anthropic", "httpx", "openai", "requests"}
            )
        ):
            hits.append(f"from {node.module} import ...")
    assert not hits, (
        "bench_prefetch_probe.py must stay offline and LLM-free; "
        f"forbidden imports found: {hits}"
    )
