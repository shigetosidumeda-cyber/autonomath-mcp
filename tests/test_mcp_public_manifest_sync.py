from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FULL_MANIFESTS = [
    REPO_ROOT / "mcp-server.json",
    REPO_ROOT / "mcp-server.full.json",
    REPO_ROOT / "site" / "mcp-server.json",
    REPO_ROOT / "site" / "mcp-server.full.json",
]
SUBSET_MANIFESTS = [
    REPO_ROOT / "mcp-server.core.json",
    REPO_ROOT / "mcp-server.composition.json",
]
SERVER_MANIFESTS = [
    REPO_ROOT / "server.json",
    REPO_ROOT / "site" / "server.json",
]
BANNED_PUBLIC_DESCRIPTION_PATTERNS = (
    re.compile(r"CLAUDE\.md"),
    re.compile(r"\bmigration\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bWave\s+\d+(?:\.\d+)*\b"),
    re.compile(r"\bDEEP-\d+\b"),
    re.compile(r"\beligibility_hash\b"),
    re.compile(r"\b(?:jpintel|autonomath)\.db\b"),
    re.compile(r"\busage_events\b"),
    re.compile(r"\bapi_keys\b"),
    re.compile(r"\bcost_ledger(?:\.[a-z0-9_]+)?\b"),
    re.compile(r"\baeo_citation_bench\b"),
    re.compile(r"`?(?<![A-Za-z0-9_])(?:am|v|jpi|jc)_[a-z0-9_]+`?"),
)


def _published_tool_count() -> int:
    for raw in (
        (REPO_ROOT / "scripts" / "distribution_manifest.yml")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        line = raw.split("#", 1)[0].strip()
        if line.startswith("tool_count_default_gates:"):
            return int(line.split(":", 1)[1].strip())
    raise AssertionError("tool_count_default_gates not found")


# Hard-stop patterns enforced over the *whole rendered manifest* (root
# description + tool descriptions + meta + everything else).  Mirrors the
# A3 packet's final grep, with `\bam_x+\b` understood as the secret-shape
# `am_xxxxx…` (one or more `x` characters after `am_x`).
TASK_GREP_PATTERNS = (
    re.compile(r"jpintel\.db", re.IGNORECASE),
    re.compile(r"autonomath\.db", re.IGNORECASE),
    re.compile(r"\busage_events\b"),
    re.compile(r"\bapi_keys\b"),
    re.compile(r"\bcost_ledger\b"),
    re.compile(r"\bam_x{2,}[A-Za-z0-9_]*\b"),
    re.compile(r"Authorization:\s*Bearer\s+am_", re.IGNORECASE),
    re.compile(r"\bARR\b"),
    re.compile(r"\bROI\b"),
    re.compile(r"\bWave\s+\d", re.IGNORECASE),
    re.compile(r"\bmigration\s+\d", re.IGNORECASE),
    re.compile(r"CLAUDE\.md"),
)


@pytest.fixture(scope="module")
def runtime_tool_names() -> list[str]:
    env = os.environ.copy()
    env["AUTONOMATH_36_KYOTEI_ENABLED"] = "0"
    env["JPCITE_36_KYOTEI_ENABLED"] = "0"
    code = textwrap.dedent(
        """
        import asyncio
        import json
        from jpintel_mcp.mcp.server import mcp

        async def main():
            tools = await mcp.list_tools()
            print(json.dumps([tool.name for tool in tools]))

        asyncio.run(main())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _publisher_meta(data: dict) -> dict:
    return data["_meta"]["io.modelcontextprotocol.registry/publisher-provided"]


def test_full_public_manifests_match_runtime_tool_manager(
    runtime_tool_names: list[str],
) -> None:
    published_count = _published_tool_count()
    assert len(runtime_tool_names) >= published_count
    assert len(runtime_tool_names) == len(set(runtime_tool_names))
    assert not [name for name in runtime_tool_names if name.startswith("intel_")]

    for path in FULL_MANIFESTS:
        data = _load(path)
        names = [tool["name"] for tool in data["tools"]]
        assert len(names) == published_count
        assert set(names).issubset(set(runtime_tool_names)), path
        assert data["_meta"]["tool_count"] == published_count
        assert _publisher_meta(data)["tool_count"] == published_count
        assert not [name for name in names if name.startswith("intel_")]


EXPECTED_MCP_TRANSPORTS = ["stdio", "sse", "streamable_http"]


def test_public_manifests_advertise_http_transports_with_stdio_package_default() -> None:
    for path in FULL_MANIFESTS:
        data = _load(path)
        assert data.get("transport") == "stdio"
        meta = data.get("_meta", {})
        publisher = _publisher_meta(data)
        assert meta.get("transports") == EXPECTED_MCP_TRANSPORTS
        assert publisher.get("transports") == EXPECTED_MCP_TRANSPORTS
        assert meta["transport_endpoints"]["streamable_http"]["url"].endswith(
            "/v1/mcp/streamable_http"
        )
        assert publisher["transport_endpoints"]["streamable_http"]["type"] == "streamable_http"
        for package in data.get("packages", []):
            assert package["transport"]["type"] == "stdio"


def test_public_manifest_requirement_url_fields_are_plain_urls() -> None:
    for path in FULL_MANIFESTS + SUBSET_MANIFESTS:
        requirements = _load(path).get("requirements") or {}
        for key in ("api_key", "api_key_doc"):
            value = requirements.get(key)
            if value is None:
                continue
            assert value == "https://jpcite.com/pricing.html", f"{path}:{key}"


def test_public_tool_descriptions_do_not_leak_internal_process_terms() -> None:
    for path in FULL_MANIFESTS:
        data = _load(path)
        for tool in data["tools"]:
            description = tool.get("description", "")
            for pattern in BANNED_PUBLIC_DESCRIPTION_PATTERNS:
                assert not pattern.search(description), (
                    f"{path}:{tool.get('name')} leaks {pattern.pattern!r}"
                )

    for path in SERVER_MANIFESTS:
        data = _load(path)
        publisher = _publisher_meta(data)
        assert publisher["tool_count"] == _published_tool_count()
        assert publisher["transports"] == EXPECTED_MCP_TRANSPORTS
        for package in data.get("packages", []):
            assert package["transport"]["type"] == "stdio"


def test_rendered_manifests_pass_task_a3_leak_grep() -> None:
    """Whole-file leak gate that mirrors the A3 packet final grep.

    The narrower per-tool description test above gates tool descriptions only.
    This test additionally gates root description / meta / publisher copy so a
    leak landing in non-tools fields is also caught before commit.
    """
    targets = FULL_MANIFESTS + SUBSET_MANIFESTS + SERVER_MANIFESTS
    for path in targets:
        payload = path.read_text(encoding="utf-8")
        for pattern in TASK_GREP_PATTERNS:
            match = pattern.search(payload)
            if match is None:
                continue
            idx = match.start()
            window = payload[max(0, idx - 60) : idx + 80].replace("\n", " ")
            raise AssertionError(f"{path}: leaks {pattern.pattern!r} near …{window}…")


def test_sanitizer_strips_synthetic_leakage_shapes() -> None:
    """Unit-test the sanitizer against synthetic leak shapes.

    Guards against a runtime tool author introducing a brand-new leak shape
    that the description-level regex passes don't yet catch.  All synthetic
    shapes must come out empty of the A3 grep patterns after one pass.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        sync = __import__("sync_mcp_public_manifests")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))

    synthetic_inputs = [
        "joins jpintel.db with autonomath.db rows for the matcher",
        "writes to usage_events and api_keys after each call",
        "see cost_ledger.daily_total for billing",
        'example: api_key="am_xxxxxxxxxxxx" Authorization: Bearer am_xxxxsecret',
        "Wave 47 migration 091 introduced this surface (CLAUDE.md gotcha)",
        "phase-zero ROI math vs ARR table",
        "DEEP-22 verifier deepening using eligibility_hash",
    ]
    for raw in synthetic_inputs:
        cleaned = sync._sanitize_public_description(raw)
        for pattern in TASK_GREP_PATTERNS:
            assert not pattern.search(cleaned), (
                f"sanitizer leaked {pattern.pattern!r} for input {raw!r} -> {cleaned!r}"
            )


def test_sanitizer_normalizes_legacy_price_marker() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        sync = __import__("sync_mcp_public_manifests")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))

    cleaned = sync._sanitize_public_description("NO LLM, single ¥3/req billing.")
    assert "¥3/req" not in cleaned
    assert "¥3/billable unit" in cleaned


def test_tool_count_rewriter_handles_public_variants() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        sync = __import__("sync_mcp_public_manifests")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))

    raw = "139 tools; 139-tool MCP; MCP tools (139); tools (139); **139 個の MCP ツール**"
    rewritten = sync._replace_tool_count_text(raw, _published_tool_count())
    assert "139" not in rewritten
    assert "184 tools" in rewritten
    assert "184-tool MCP" in rewritten
    assert "MCP tools (184)" in rewritten
    assert "**184 個の MCP ツール**" in rewritten


def test_llms_marker_upsert_rewrites_count_and_required_markers() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        sync = __import__("sync_mcp_public_manifests")
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))

    raw = "# jpcite\nBrand: jpcite.\n- [MCP tools (139)](https://jpcite.com/docs/mcp-tools/)\n"
    updated = sync._upsert_llms_marker(raw, _published_tool_count())
    assert "MCP package: autonomath-mcp" in updated
    assert "Public MCP tools: 184" in updated
    assert "JPY 3 ex-tax per billable unit" in updated
    assert "3 requests/day/IP" in updated
    assert "139" not in updated
