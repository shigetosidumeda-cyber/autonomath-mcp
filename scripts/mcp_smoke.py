#!/usr/bin/env python3
"""MCP stdio smoke test for jpintel-mcp.

Launches the MCP server as subprocess and drives it via newline-delimited
JSON-RPC 2.0 on stdio. Exits 0 if all 4 core tools respond with the right shape.

Usage:
    .venv/bin/python scripts/mcp_smoke.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue

REPO = Path(__file__).resolve().parent.parent
SERVER_CMD = [str(REPO / ".venv" / "bin" / "jpintel-mcp")]
PROTOCOL_VERSION = "2025-06-18"
TIMEOUT = 15.0


class McpClient:
    def __init__(self) -> None:
        env = os.environ.copy()
        env.setdefault("JPINTEL_DB_PATH", str(REPO / "data" / "jpintel.db"))
        self.proc = subprocess.Popen(
            SERVER_CMD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        self.q: Queue[str] = Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._id = 0

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            decoded = line.decode("utf-8", errors="replace").rstrip("\n")
            if decoded:
                self.q.put(decoded)

    def _send(self, obj: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            try:
                raw = self.q.get(timeout=0.5)
            except Empty:
                if self.proc.poll() is not None:
                    err = (
                        self.proc.stderr.read().decode("utf-8", errors="replace")
                        if self.proc.stderr
                        else ""
                    )
                    raise RuntimeError(
                        f"server exited early rc={self.proc.returncode} stderr={err[:2000]}"
                    ) from None
                continue
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if frame.get("id") == self._id:
                return frame
        raise TimeoutError(f"no response to {method} within {TIMEOUT}s")

    def notify(self, method: str, params: dict | None = None) -> None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def unwrap_call(frame: dict) -> dict:
    if "error" in frame:
        raise RuntimeError(f"tool error: {frame['error']}")
    result = frame["result"]
    # FastMCP returns content[] (text blocks) plus optional structuredContent.
    if "structuredContent" in result and result["structuredContent"] is not None:
        return result["structuredContent"]
    blocks = result.get("content") or []
    for b in blocks:
        if b.get("type") == "text":
            try:
                return json.loads(b["text"])
            except json.JSONDecodeError:
                return {"_text": b["text"]}
    raise RuntimeError(f"no usable content in tool result: {result}")


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        raise SystemExit(1)


def main() -> int:
    cli = McpClient()
    try:
        init = cli.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "jpintel-smoke", "version": "0.1"},
            },
        )
        check(
            "result" in init,
            f"initialize returned result (proto={init.get('result', {}).get('protocolVersion')})",
        )
        cli.notify("notifications/initialized", {})

        listed = cli.request("tools/list", {})
        tools = {t["name"]: t for t in listed["result"]["tools"]}
        for name in ("search_programs", "get_program", "list_exclusion_rules", "check_exclusions"):
            check(name in tools, f"tools/list includes {name}")

        # search_programs(q=農業)
        sr = unwrap_call(
            cli.request(
                "tools/call",
                {"name": "search_programs", "arguments": {"q": "農業", "limit": 5}},
            )
        )
        check(
            isinstance(sr.get("results"), list) and len(sr["results"]) >= 1,
            f"search_programs returned {len(sr.get('results', []))} results (total={sr.get('total')})",
        )
        first = sr["results"][0]
        for field in (
            "unified_id",
            "primary_name",
            "tier",
            "trust_level",
            "coverage_score",
            "equipment_category",
        ):
            check(field in first, f"search_programs result has '{field}' field")
        unified_id = first["unified_id"]

        # get_program(unified_id)
        gp = unwrap_call(
            cli.request(
                "tools/call",
                {"name": "get_program", "arguments": {"unified_id": unified_id}},
            )
        )
        check(gp.get("unified_id") == unified_id, f"get_program returned requested id {unified_id}")
        check("enriched" in gp, "get_program response includes 'enriched' field")
        for lineage_field in ("source_url", "source_fetched_at", "source_checksum"):
            check(lineage_field in gp, f"get_program response includes '{lineage_field}' field")

        # list_exclusion_rules()
        # FastMCP wraps list returns under structuredContent={"result": [...]}
        rules_frame = cli.request(
            "tools/call",
            {"name": "list_exclusion_rules", "arguments": {}},
        )
        result = rules_frame.get("result", {})
        if "structuredContent" in result and isinstance(result["structuredContent"], dict):
            rules = result["structuredContent"].get("result", result["structuredContent"])
        else:
            blocks = result.get("content") or []
            rules = json.loads(blocks[0]["text"]) if blocks else []
        check(
            isinstance(rules, list) and len(rules) >= 22,
            f"list_exclusion_rules returned {len(rules) if isinstance(rules, list) else 'non-list'} rules (expect >=22)",
        )
        for f in ("rule_id", "kind", "severity", "description"):
            check(f in rules[0], f"exclusion rule row has '{f}'")

        # check_exclusions(program_ids=[unified_id])
        ce = unwrap_call(
            cli.request(
                "tools/call",
                {"name": "check_exclusions", "arguments": {"program_ids": [unified_id]}},
            )
        )
        check(
            "hits" in ce and isinstance(ce["hits"], list),
            f"check_exclusions returned hits list (len={len(ce.get('hits', []))})",
        )
        check(
            ce.get("checked_rules", 0) >= 22,
            f"check_exclusions checked_rules={ce.get('checked_rules')} (expect >=22)",
        )

        print("\nAll 4 MCP tools PASS.")
        return 0
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
