"""End-to-end MCP protocol integration tests.

Spawns the real `autonomath-mcp` binary as a subprocess over stdio and
exercises the full JSON-RPC handshake (initialize -> initialized
notification -> tools/list -> tools/call) for every tool the server
exposes. Previous test coverage (`tests/test_mcp_tools.py`) calls the
decorated Python functions directly, which leaves the MCP wire format
unverified -- if FastMCP ever shipped malformed JSON-RPC envelopes,
Claude Desktop would silently hang and we would not catch it.

These tests run against `data/jpintel.db` as-is (no mocks), which is
explicitly required by CLAUDE.md ("Never mock the database in
integration tests"). They need the real DB to be populated; the suite
skips individual assertions that depend on content we cannot guarantee
(e.g. there are no known-conflicting program ids in the seeded set).
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BINARY = REPO_ROOT / ".venv" / "bin" / "autonomath-mcp"
DB_PATH = REPO_ROOT / "data" / "jpintel.db"


pytestmark = pytest.mark.skipif(
    not BINARY.exists() or not DB_PATH.exists(),
    reason="Requires built venv + seeded data/jpintel.db (integration-only)",
)


class MCPClient:
    """Minimal JSON-RPC client over stdio for the FastMCP server.

    The server writes one JSON object per line on stdout. Logs go to
    stderr -- we drain stderr in the background so a full pipe cannot
    deadlock the server when it tries to log during a handler.
    """

    def __init__(self, binary: Path = BINARY, cwd: Path = REPO_ROOT) -> None:
        # conftest.py sets JPINTEL_DB_PATH to an empty test DB for unit
        # tests. We want the real seeded data/jpintel.db here, so scrub
        # that override (plus any other Pytest-local settings) and force
        # the production default.
        env = os.environ.copy()
        env["JPINTEL_DB_PATH"] = str(DB_PATH)
        # Suppress server banner INFO logs on stderr so pytest output
        # stays readable if a test ever hits a RuntimeError.
        env.setdefault("JPINTEL_LOG_LEVEL", "WARNING")
        self.proc = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            bufsize=0,
            env=env,
        )
        self._next_id = 0
        self.server_info: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Raw JSON-RPC plumbing
    # ------------------------------------------------------------------
    def _send(
        self, method: str, params: dict[str, Any] | None = None, is_notification: bool = False
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

    def _recv(self, expected_id: int, timeout: float = 15.0) -> dict[str, Any]:
        """Read stdout line-by-line until we see the matching id.

        Skips notifications or stray responses with a different id (the
        server can in principle interleave log-style notifications).
        """
        assert self.proc.stdout is not None
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            r, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not r:
                continue
            chunk = self.proc.stdout.readline()
            if not chunk:
                # EOF -- drain stderr to make the failure debuggable.
                err = self._drain_stderr()
                raise RuntimeError(
                    f"MCP server closed stdout before responding to id={expected_id}. "
                    f"stderr tail:\n{err[-2000:] if err else '(empty)'}"
                )
            buf = chunk.strip()
            if not buf:
                continue
            try:
                msg = json.loads(buf)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"MCP server emitted non-JSON on stdout: {buf!r} ({e})") from e
            # Skip notifications (no id) and mismatched-id responses.
            if "id" not in msg:
                continue
            if msg.get("id") != expected_id:
                continue
            return msg
        err = self._drain_stderr()
        raise TimeoutError(
            f"No response to id={expected_id} within {timeout}s. "
            f"stderr tail:\n{err[-2000:] if err else '(empty)'}"
        )

    def _drain_stderr(self) -> str:
        """Non-blocking drain of whatever is buffered on stderr."""
        assert self.proc.stderr is not None
        out = b""
        while True:
            r, _, _ = select.select([self.proc.stderr], [], [], 0.05)
            if not r:
                break
            chunk = self.proc.stderr.read1(65536)
            if not chunk:
                break
            out += chunk
        try:
            return out.decode("utf-8", errors="replace")
        except Exception:
            return repr(out)

    # ------------------------------------------------------------------
    # High-level protocol helpers
    # ------------------------------------------------------------------
    def initialize(self) -> dict[str, Any]:
        mid = self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "autonomath-integration-test", "version": "0.0.0"},
            },
        )
        assert mid is not None
        resp = self._recv(mid)
        self.server_info = resp.get("result", {}).get("serverInfo")
        # Notification -- no response expected.
        self._send("notifications/initialized", {}, is_notification=True)
        return resp

    def list_tools(self) -> dict[str, Any]:
        mid = self._send("tools/list")
        assert mid is not None
        return self._recv(mid)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        mid = self._send("tools/call", {"name": name, "arguments": arguments})
        assert mid is not None
        return self._recv(mid, timeout=20.0)

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


# ----------------------------------------------------------------------
# Helpers to unpack FastMCP tool responses
# ----------------------------------------------------------------------
def extract_tool_payload(resp: dict[str, Any]) -> Any:
    """Pull the JSON-decoded payload out of a tools/call response.

    FastMCP 1.27 (this repo's pinned version) returns BOTH
    ``structuredContent`` (the typed return value) and ``content``
    (a list with a single TextContent whose `text` is the JSON-encoded
    version). Prefer structuredContent when present; fall back to
    parsing the text block so the tests still work if the server is
    downgraded to a version that only emits unstructured content.
    """
    assert "result" in resp, f"expected tools/call result, got {resp}"
    result = resp["result"]
    if "structuredContent" in result and result["structuredContent"] is not None:
        sc = result["structuredContent"]
        # FastMCP wraps non-dict returns in {"result": ...}; unwrap if so.
        if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
            return sc["result"]
        return sc
    content = result.get("content") or []
    assert content, f"no content in tool response: {result}"
    first = content[0]
    assert first.get("type") == "text", f"unexpected content type: {first}"
    text = first.get("text", "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some tools return prose on error -- let callers see it raw.
        return text


def is_error_response(resp: dict[str, Any]) -> bool:
    """MCP tool errors can show up either as a JSON-RPC `error` object
    (e.g. for unknown tool names) or inside `result.isError=True`."""
    if "error" in resp:
        return True
    result = resp.get("result") or {}
    return bool(result.get("isError"))


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def mcp():
    client = MCPClient()
    try:
        client.initialize()
    except Exception:
        client.close()
        raise
    try:
        yield client
    finally:
        client.close()


# ======================================================================
# Tests
# ======================================================================


# ----- handshake ------------------------------------------------------
def test_initialize_reports_server_info(mcp: MCPClient) -> None:
    assert mcp.server_info is not None, "initialize() did not capture serverInfo"
    assert (
        mcp.server_info.get("name") == "autonomath"
    ), f"serverInfo.name must be 'autonomath', got {mcp.server_info}"
    version = mcp.server_info.get("version")
    assert (
        isinstance(version, str) and version
    ), f"serverInfo.version must be non-empty string, got {version!r}"


def test_list_tools_covers_all_handlers(mcp: MCPClient) -> None:
    resp = mcp.list_tools()
    assert "result" in resp, f"tools/list failed: {resp}"
    tools = resp["result"].get("tools") or []
    names = {t["name"] for t in tools}
    expected = {
        "search_programs",
        "get_program",
        "batch_get_programs",
        "list_exclusion_rules",
        "check_exclusions",
        "get_meta",
        "enum_values",
        "search_enforcement_cases",
        "get_enforcement_case",
        "search_case_studies",
        "get_case_study",
        "search_loan_programs",
        "get_loan_program",
    }
    assert expected.issubset(names), f"missing tools: {expected - names}. Got: {sorted(names)}"
    # Every tool must carry an inputSchema (Claude Desktop requires it).
    for t in tools:
        if t["name"] in expected:
            assert "inputSchema" in t, f"{t['name']} missing inputSchema"


# ----- search_programs ------------------------------------------------
def test_search_programs_basic(mcp: MCPClient) -> None:
    # Use 3+ char queries so FTS5 trigram matches; 2-char 農業 returns 0
    # in trigram mode (the REST handler pads shorter queries via LIKE).
    resp = mcp.call_tool("search_programs", {"q": "補助金", "limit": 5})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    assert isinstance(payload, dict)
    assert set(payload.keys()) >= {"total", "limit", "offset", "results"}
    assert payload["limit"] == 5
    assert isinstance(payload["results"], list)
    assert 0 < len(payload["results"]) <= 5
    # Each row must carry a unified_id + primary_name at minimum.
    for row in payload["results"]:
        assert "unified_id" in row and row["unified_id"], row
        assert "primary_name" in row and row["primary_name"], row


def test_search_programs_short_query_uses_like_fallback(mcp: MCPClient) -> None:
    """2-char queries bypass FTS (trigram needs 3 chars) and fall back
    to LIKE. The server must still return something for a common term
    like 農業.
    """
    resp = mcp.call_tool("search_programs", {"q": "農業", "limit": 5})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    # LIKE fallback path should yield plenty of matches.
    assert payload["total"] > 0, f"short-query LIKE fallback returned zero hits for 農業: {payload}"


def test_search_programs_phrase_relevance(mcp: MCPClient) -> None:
    """FTS trigram can bleed single-kanji overlap into unrelated rows
    (CLAUDE.md notes this explicitly: 税額控除 vs ふるさと納税). We
    can't require the *first* result to be perfectly ranked, but at
    least one of the top 5 must be a genuinely tax-related program.
    """
    resp = mcp.call_tool("search_programs", {"q": "税額控除", "limit": 5})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    assert payload["results"], "expected at least one hit for 税額控除"
    tax_like_keywords = ("税", "控除", "税制")
    tax_hits = [
        r
        for r in payload["results"]
        if any(kw in (r.get("primary_name") or "") for kw in tax_like_keywords)
    ]
    assert tax_hits, (
        "no tax-related hits in top 5 for '税額控除'; results="
        f"{[r.get('primary_name') for r in payload['results']]}"
    )


def test_search_programs_with_prefecture_filter(mcp: MCPClient) -> None:
    resp = mcp.call_tool("search_programs", {"prefecture": "東京都", "limit": 3})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    for row in payload["results"]:
        assert row.get("prefecture") == "東京都", row


# ----- get_program ----------------------------------------------------
def _grab_any_id(mcp: MCPClient) -> str:
    resp = mcp.call_tool("search_programs", {"limit": 1})
    payload = extract_tool_payload(resp)
    assert payload["results"], "seeded DB has no programs -- cannot test get_program"
    return payload["results"][0]["unified_id"]


def test_get_program_known_id(mcp: MCPClient) -> None:
    uid = _grab_any_id(mcp)
    resp = mcp.call_tool("get_program", {"unified_id": uid})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    assert payload["unified_id"] == uid
    # get_program uses the "default" shape which still carries tier.
    assert "tier" in payload
    assert "primary_name" in payload and payload["primary_name"]


def test_get_program_unknown_id_returns_error_envelope(mcp: MCPClient) -> None:
    resp = mcp.call_tool("get_program", {"unified_id": "UNI-nonexistent-xyz"})
    # New contract: tools no longer raise on bad input. They return a
    # structured envelope with `error`, `code`, and `hint`. FastMCP
    # surfaces that as a normal (non-isError) success response whose
    # payload carries the envelope. Clients still get an actionable
    # signal — just via the payload, not JSON-RPC -32603.
    assert not is_error_response(
        resp
    ), f"tool unexpectedly raised; envelope contract regressed: {resp}"
    payload = extract_tool_payload(resp)
    assert isinstance(payload, dict), f"expected dict envelope, got {payload!r}"
    assert payload.get("code") == "no_matching_records", payload
    err_text = str(payload.get("error", "")).lower()
    assert (
        "not found" in err_text or "nonexistent" in err_text.lower()
    ), f"error message did not mention the missing id: {payload}"
    assert "hint" in payload, f"missing hint in error envelope: {payload}"


# ----- batch_get_programs --------------------------------------------
def test_batch_get_programs_round_trip(mcp: MCPClient) -> None:
    search = mcp.call_tool("search_programs", {"limit": 10})
    uids = [r["unified_id"] for r in extract_tool_payload(search)["results"]]
    assert uids, "cannot test batch without ids"
    resp = mcp.call_tool("batch_get_programs", {"unified_ids": uids})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    assert set(payload.keys()) >= {"results", "not_found"}
    returned = {r["unified_id"] for r in payload["results"]}
    assert returned == set(
        uids
    ), f"batch dropped/added ids. asked={uids} got={returned} not_found={payload['not_found']}"
    # Batch contract: full shape always carries these keys.
    for row in payload["results"]:
        for k in ("enriched", "source_mentions", "source_url"):
            assert k in row, f"batch row missing {k}: {row.keys()}"


def test_batch_get_programs_over_limit_errors(mcp: MCPClient) -> None:
    fake_ids = [f"UNI-fake-{i}" for i in range(51)]
    resp = mcp.call_tool("batch_get_programs", {"unified_ids": fake_ids})
    assert is_error_response(resp), f"expected validation error for 51 ids, got success: {resp}"
    # Drill into the error text to confirm it's the right failure.
    result = resp.get("result") or {}
    text_blob = " ".join(
        (c.get("text") or "") for c in (result.get("content") or []) if isinstance(c, dict)
    )
    err_msg = (resp.get("error") or {}).get("message", "")
    combined = (text_blob + " " + err_msg).lower()
    assert (
        "50" in combined or "cap" in combined or "limit" in combined
    ), f"validation error did not cite the 50-id cap: {resp}"


# ----- list_exclusion_rules ------------------------------------------
# Rule floor is the 35 curated rules (22 agri + 13 non-agri) seeded at
# launch; migration 011 adds the 2026-04-23 external exclusion_rules so
# this count grows monotonically. Assert on the floor only — a strict
# equality would churn every data refresh.
_EXCLUSION_RULES_FLOOR = 35


def test_list_exclusion_rules_returns_35(mcp: MCPClient) -> None:
    resp = mcp.call_tool("list_exclusion_rules", {})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    # α11: tool now always returns the unified envelope
    # `{"rules": [...], "total": int, "filters": {...}}` (was union of
    # bare list on hit + dict on miss). Both populated and empty paths
    # share the same shape.
    assert isinstance(payload, dict), f"expected dict envelope, got {type(payload).__name__}"
    assert {"rules", "total", "filters"} <= set(payload.keys())
    rules = payload["rules"]
    assert isinstance(rules, list)
    assert payload["total"] == len(rules)
    assert len(rules) >= _EXCLUSION_RULES_FLOOR, (
        f"expected >= {_EXCLUSION_RULES_FLOOR} rules (22 agri + 13 non-agri + external), "
        f"got {len(rules)}"
    )
    # Shape sanity on the first rule.
    rule = rules[0]
    for k in ("rule_id", "kind", "severity", "description"):
        assert k in rule, f"rule missing {k}: {rule.keys()}"


# ----- check_exclusions ----------------------------------------------
def test_check_exclusions_known_conflict(mcp: MCPClient) -> None:
    """Two programs with a rule-documented mutex must surface a hit.

    `keiei-kaishi-shikin` vs `koyo-shuno-shikin` is excl-keiei-kaishi-vs-
    koyo-shuno-absolute in the seeded rule set.
    """
    resp = mcp.call_tool(
        "check_exclusions",
        {
            "program_ids": ["keiei-kaishi-shikin", "koyo-shuno-shikin"],
        },
    )
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    assert payload["checked_rules"] >= _EXCLUSION_RULES_FLOOR
    assert payload[
        "hits"
    ], f"expected at least one hit for the known agri mutex pair, got {payload}"
    hit_rules = {h["rule_id"] for h in payload["hits"]}
    assert any(
        "keiei-kaishi" in r and "koyo-shuno" in r for r in hit_rules
    ), f"known mutex rule not among hits: {hit_rules}"


def test_check_exclusions_no_conflict(mcp: MCPClient) -> None:
    """Two unrelated unified_ids should produce zero mutex hits."""
    search = mcp.call_tool("search_programs", {"q": "補助金", "limit": 2})
    uids = [r["unified_id"] for r in extract_tool_payload(search)["results"]]
    assert len(uids) >= 2, "cannot test no-conflict without 2 programs"
    resp = mcp.call_tool("check_exclusions", {"program_ids": uids})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    # Unified ids don't match canonical agri names, so *mutex* hits
    # must be zero. Prerequisite hits could theoretically fire, so we
    # only assert on kind=absolute mutexes.
    mutex_hits = [h for h in payload["hits"] if h.get("kind") == "absolute"]
    assert not mutex_hits, f"unrelated ids {uids} unexpectedly triggered mutex rules: {mutex_hits}"


# ----- get_meta -------------------------------------------------------
def test_get_meta_shape(mcp: MCPClient) -> None:
    resp = mcp.call_tool("get_meta", {})
    assert not is_error_response(resp), f"tool errored: {resp}"
    payload = extract_tool_payload(resp)
    assert (
        payload["total_programs"] > 5000
    ), f"total_programs suspiciously low: {payload['total_programs']}"
    assert "tier_counts" in payload
    tier_keys = set(payload["tier_counts"].keys())
    # S/A/B/C must all be represented in the real dataset.
    for t in ("S", "A", "B", "C"):
        assert t in tier_keys, f"tier {t} missing from tier_counts: {tier_keys}"
    assert payload["exclusion_rules_count"] >= _EXCLUSION_RULES_FLOOR
    # last_ingested_at must be an ISO-8601 timestamp.
    last = payload.get("last_ingested_at")
    assert isinstance(last, str) and last, f"last_ingested_at missing/empty: {last}"
    assert "T" in last and (
        "Z" in last or "+" in last or "-" in last[10:]
    ), f"last_ingested_at does not look ISO-8601: {last!r}"


# ----- protocol error handling ---------------------------------------
def test_unknown_tool_returns_error(mcp: MCPClient) -> None:
    resp = mcp.call_tool("does_not_exist_tool", {})
    assert is_error_response(resp), f"expected error for unknown tool, got success: {resp}"
    err = resp.get("error") or {}
    result = resp.get("result") or {}
    text_blob = " ".join(
        (c.get("text") or "") for c in (result.get("content") or []) if isinstance(c, dict)
    )
    combined = (err.get("message", "") + " " + text_blob).lower()
    assert (
        "unknown" in combined
        or "not found" in combined
        or "no such" in combined
        or "does_not_exist" in combined
    ), f"unexpected error shape for unknown tool: {resp}"


if __name__ == "__main__":
    # Allow ad-hoc debugging: `python tests/test_mcp_integration.py`
    sys.exit(pytest.main([__file__, "-xvs"]))
