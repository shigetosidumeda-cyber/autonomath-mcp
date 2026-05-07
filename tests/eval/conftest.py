"""Pytest fixtures for tests/eval/.

Fixtures:
  mcp_stdio_client      - spawn ``autonomath-mcp`` subprocess, JSON-RPC over stdio
  autonomath_db_ro      - sqlite3.Connection in URI read-only mode against live DB
  jpintel_db_ro         - same, against data/jpintel.db
  hallucination_guard   - parsed YAML (60 entries) for Tier C
  thresholds            - eval thresholds dict (Tier A / B / C floors)

Per ``feedback_autonomath_no_api_use``: harness MUST NOT call the Anthropic API.
The MCP server resolves tools deterministically against local SQLite.
"""

from __future__ import annotations

import json
import os
import select
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
HALLUCINATION_GUARD = REPO_ROOT / "data" / "hallucination_guard.yaml"
SEED_DB = REPO_ROOT / "tests" / "eval" / "fixtures" / "seed.db"
MCP_BINARY = REPO_ROOT / ".venv" / "bin" / "autonomath-mcp"


def _resolve_db(prod: Path) -> Path:
    """Prefer CI fixture slice; fall back to live prod DB."""
    if SEED_DB.exists() and os.environ.get("EVAL_USE_SEED", "0") == "1":
        return SEED_DB
    return prod


@pytest.fixture(scope="session")
def autonomath_db_ro() -> Iterator[sqlite3.Connection]:
    db = _resolve_db(AUTONOMATH_DB)
    assert db.exists(), f"missing {db}"
    uri = f"file:{db}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def jpintel_db_ro() -> Iterator[sqlite3.Connection]:
    db = _resolve_db(JPINTEL_DB)
    assert db.exists(), f"missing {db}"
    uri = f"file:{db}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def hallucination_guard() -> list[dict[str, Any]]:
    with HALLUCINATION_GUARD.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["entries"]


@pytest.fixture(scope="session")
def thresholds() -> dict[str, float]:
    return {
        "tier_a_precision_at_1": 0.85,
        "tier_b_precision_at_1": 0.80,
        "tier_c_refusal_acc": 0.90,
        "hallucination_rate_max": 0.02,
        "citation_rate_min": 1.00,
        "recall_at_5_min": 0.95,
    }


class MCPStdioClient:
    """Minimal JSON-RPC 2.0 stdio client. Drives autonomath-mcp subprocess.

    Mirrors the wire format used by ``tests/test_mcp_integration.py::MCPClient``
    so future fixes propagate via shared review. Does not call the Anthropic API.
    """

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self._next_id = 0
        self.server_info: dict[str, Any] | None = None

    def _send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        is_notification: bool = False,
    ) -> int | None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not is_notification:
            self._next_id += 1
            msg["id"] = self._next_id
        if params is not None:
            msg["params"] = params
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        return msg.get("id")

    def _recv(self, expected_id: int, timeout: float = 20.0) -> dict[str, Any]:
        assert self.proc.stdout is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            r, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not r:
                continue
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP server closed stdout (id={expected_id})")
            buf = line.strip()
            if not buf:
                continue
            try:
                msg = json.loads(buf)
            except json.JSONDecodeError:
                continue  # skip non-JSON banner lines
            if "id" not in msg or msg.get("id") != expected_id:
                continue
            return msg
        raise TimeoutError(f"No response to id={expected_id} within {timeout}s")

    def initialize(self) -> None:
        mid = self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "autonomath-eval-harness", "version": "0.1.0"},
            },
        )
        assert mid is not None
        resp = self._recv(mid)
        self.server_info = resp.get("result", {}).get("serverInfo")
        self._send("notifications/initialized", {}, is_notification=True)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        mid = self._send("tools/call", {"name": tool, "arguments": arguments})
        assert mid is not None
        resp = self._recv(mid, timeout=30.0)
        # Unwrap structuredContent if present (FastMCP convention); else
        # parse the first text content as JSON.
        result = resp.get("result", {})
        if "structuredContent" in result:
            return result["structuredContent"]
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, KeyError):
                    return {"_raw": item.get("text")}
        return result

    def shutdown(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture(scope="session")
def mcp_stdio_client() -> Iterator[MCPStdioClient]:
    """Spawn autonomath-mcp subprocess. NEVER calls Anthropic API."""
    if not MCP_BINARY.exists():
        pytest.skip(f"missing {MCP_BINARY}; install with `pip install -e .[dev]`")
    env = os.environ.copy()
    env["AUTONOMATH_ENABLED"] = "1"
    env["AUTONOMATH_36_KYOTEI_ENABLED"] = "0"
    env["JPINTEL_LOG_LEVEL"] = "WARNING"
    proc = subprocess.Popen(
        [str(MCP_BINARY)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(REPO_ROOT),
        bufsize=0,
    )
    client = MCPStdioClient(proc)
    try:
        client.initialize()
        yield client
    finally:
        client.shutdown()
