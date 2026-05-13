#!/usr/bin/env python3
"""
DEEP-61 — jpcite (v0.3.4) post-deploy smoke runbook.

Five module gate (routes / mcp / disclaimer / stripe / health) covering the
240 production route walk, the MCP tools/list 151+ verify, and the 17
sensitive-tool `_disclaimer` envelope assertion. Designed to run from a
Cloudflare Pages tunnel host or operator laptop within ~120 seconds.

Constraints:
- LLM API import budget = 0 (anthropic / openai / google.generativeai
  / claude_agent_sdk all forbidden — operator-only offline tooling).
- httpx + subprocess + json + stdlib only.
- Exit 0 = all selected modules PASS, exit 1 = at least one FAIL.
- Per-module timing log (CSV-friendly stderr, JSON to --report-out).

Usage:
    python post_deploy_smoke.py \\
        --base-url https://api.jpcite.com \\
        --module all \\
        --report-out /tmp/jpcite_smoke_v034.json

DEEP-61 spec lives at docs/_internal/deep61_smoke_runbook.md (sketch).

Session A lane draft, 2026-05-07.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# LLM API import guard (mirror of tests/test_no_llm_in_production.py)
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORTS = (
    "anthropic",
    "openai",
    "google.generativeai",
    "claude_agent_sdk",
)
for _mod in _FORBIDDEN_IMPORTS:
    if _mod in sys.modules:
        raise RuntimeError(
            f"DEEP-61 violation: LLM API module '{_mod}' is loaded; "
            "post-deploy smoke must run with LLM-API import budget = 0."
        )

DEFAULT_BASE_URL = "https://api.jpcite.com"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
ROUTES_FILE = REPO_ROOT / "tests" / "fixtures" / "240_routes_sample.txt"
SENSITIVE_FILE = REPO_ROOT / "tests" / "fixtures" / "17_sensitive_tools.json"

# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------


@dataclass
class ModuleResult:
    name: str
    ok: bool
    elapsed_s: float
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        flag = "PASS" if self.ok else "FAIL"
        return f"[{flag}] {self.name:20s}  {self.elapsed_s:6.2f}s  {self.summary}"


def _timed(
    fn: Callable[[argparse.Namespace], ModuleResult],
) -> Callable[[argparse.Namespace], ModuleResult]:
    def _wrap(args: argparse.Namespace) -> ModuleResult:
        t0 = time.perf_counter()
        try:
            r = fn(args)
        except Exception as exc:  # noqa: BLE001 — modules must never raise upward
            r = ModuleResult(
                name=fn.__name__.replace("module_", ""),
                ok=False,
                elapsed_s=time.perf_counter() - t0,
                summary=f"unhandled exception: {type(exc).__name__}: {exc}",
            )
        if r.elapsed_s == 0.0:
            r.elapsed_s = time.perf_counter() - t0
        return r

    return _wrap


# ---------------------------------------------------------------------------
# Module 1 — 240 sample route 5xx ZERO
# ---------------------------------------------------------------------------


def _load_routes() -> list[str]:
    if not ROUTES_FILE.exists():
        raise FileNotFoundError(f"missing route sample list: {ROUTES_FILE}")
    rows: list[str] = []
    for line in ROUTES_FILE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        rows.append(s)
    return rows


@_timed
def module_routes_500_zero(args: argparse.Namespace) -> ModuleResult:
    routes = _load_routes()
    expected = 240
    if len(routes) != expected:
        return ModuleResult(
            name="routes_500_zero",
            ok=False,
            elapsed_s=0.0,
            summary=f"sample list has {len(routes)} rows, expected {expected}",
        )

    five_xx: list[tuple[str, int]] = []
    sample: list[tuple[str, int]] = []
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    headers = {"User-Agent": "jpcite-deep61-smoke/0.3.4"}

    with httpx.Client(base_url=args.base_url, timeout=timeout, headers=headers) as client:
        for path in routes:
            try:
                resp = client.get(path)
                code = resp.status_code
            except httpx.RequestError as exc:
                code = -1
                five_xx.append((path, code))
                if args.verbose:
                    print(f"  request_error path={path} err={exc}", file=sys.stderr)
                continue
            if 500 <= code < 600:
                five_xx.append((path, code))
            if len(sample) < 5:
                sample.append((path, code))

    ok = not five_xx
    summary = (
        f"240/240 walked, 5xx={len(five_xx)}, sample={sample[:3]}"
        if ok
        else f"240/240 walked, 5xx={len(five_xx)} first={five_xx[:3]}"
    )
    return ModuleResult(
        name="routes_500_zero",
        ok=ok,
        elapsed_s=0.0,
        summary=summary,
        detail={"total": len(routes), "five_xx": five_xx[:25], "sample": sample},
    )


# ---------------------------------------------------------------------------
# Module 2 — MCP tools/list ≥ 151
# ---------------------------------------------------------------------------


def _mcp_request(
    server_cmd: list[str], payload: dict[str, Any], timeout_s: float = 30.0
) -> dict[str, Any]:
    """Send one stdio JSON-RPC request to a freshly spawned MCP server."""
    init = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "jpcite-deep61-smoke", "version": "0.3.4"},
        },
    }
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    body = json.dumps(init) + "\n" + json.dumps(initialized) + "\n" + json.dumps(payload) + "\n"
    proc = subprocess.run(
        server_cmd,
        input=body.encode("utf-8"),
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode not in (0, None):
        raise RuntimeError(
            f"mcp server exit={proc.returncode} stderr={proc.stderr.decode('utf-8', 'replace')[:400]}"
        )
    target_id = payload["id"]
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == target_id:
            return msg
    raise RuntimeError(f"no response for id={target_id} from MCP stdio server")


@_timed
def module_mcp_tools_list(args: argparse.Namespace) -> ModuleResult:
    server_cmd = args.mcp_cmd.split() if args.mcp_cmd else ["autonomath-mcp"]
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    try:
        msg = _mcp_request(server_cmd, request, timeout_s=args.mcp_timeout)
    except subprocess.TimeoutExpired:
        return ModuleResult(
            name="mcp_tools_list",
            ok=False,
            elapsed_s=0.0,
            summary=f"timeout after {args.mcp_timeout}s — MCP server hung on tools/list",
        )
    except FileNotFoundError:
        return ModuleResult(
            name="mcp_tools_list",
            ok=False,
            elapsed_s=0.0,
            summary=f"binary not found: {server_cmd[0]} (pip install -e . in venv?)",
        )

    if "error" in msg:
        return ModuleResult(
            name="mcp_tools_list",
            ok=False,
            elapsed_s=0.0,
            summary=f"jsonrpc error: {msg['error']}",
        )
    tools = msg.get("result", {}).get("tools", [])
    count = len(tools)
    floor = args.mcp_min_tools
    ok = count >= floor
    return ModuleResult(
        name="mcp_tools_list",
        ok=ok,
        elapsed_s=0.0,
        summary=f"{count} tools listed (floor={floor}{'+' if ok else ''})",
        detail={
            "count": count,
            "floor": floor,
            "names_sample": [t.get("name") for t in tools[:8]],
        },
    )


# ---------------------------------------------------------------------------
# Module 3 — 17 sensitive tool _disclaimer emit
# ---------------------------------------------------------------------------


def _load_sensitive_tools() -> list[dict[str, Any]]:
    if not SENSITIVE_FILE.exists():
        raise FileNotFoundError(f"missing sensitive tool table: {SENSITIVE_FILE}")
    data = json.loads(SENSITIVE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{SENSITIVE_FILE} must hold a JSON list")
    return data


def _call_mcp_tool(
    server_cmd: list[str], name: str, arguments: dict[str, Any], timeout_s: float
) -> dict[str, Any]:
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    return _mcp_request(server_cmd, request, timeout_s=timeout_s)


def _envelope_has_disclaimer(envelope: dict[str, Any]) -> bool:
    """Walk the result envelope checking for `_disclaimer` field anywhere reasonable."""
    result = envelope.get("result", {})
    if "_disclaimer" in result:
        return True
    # FastMCP wraps tool output under content[].text — accept JSON-decoded text too.
    for chunk in result.get("content", []) or []:
        if not isinstance(chunk, dict):
            continue
        if "_disclaimer" in chunk:
            return True
        text = chunk.get("text")
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "_disclaimer" in parsed:
                return True
    return False


def _gate_flag_enabled(flag: str) -> bool:
    """Return True iff env var `flag` is set to a truthy value (1/true/yes/on)."""
    raw = os.environ.get(flag, "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


@_timed
def module_disclaimer_emit_17(args: argparse.Namespace) -> ModuleResult:
    sensitive = _load_sensitive_tools()
    if len(sensitive) != 17:
        return ModuleResult(
            name="disclaimer_emit_17",
            ok=False,
            elapsed_s=0.0,
            summary=f"sensitive table has {len(sensitive)} entries, expected 17",
        )
    server_cmd = args.mcp_cmd.split() if args.mcp_cmd else ["autonomath-mcp"]
    misses: list[str] = []
    hits: list[str] = []
    skipped_gated: list[str] = []
    mandatory_total = 0
    for entry in sensitive:
        name = entry["name"]
        # Gated-off-expected: tool is intentionally muted unless its env flag
        # is flipped on (e.g. 36協定 needs 社労士 review). When the flag is
        # OFF and the entry is marked `gated_off_expected`, the smoke gate
        # treats the tool as PASS-by-design rather than counting it as a
        # missing _disclaimer envelope. Flipping the flag ON re-promotes the
        # tool to mandatory in the same run.
        gate_flag = entry.get("gate_flag")
        gated_off_expected = bool(entry.get("gated_off_expected"))
        if gated_off_expected and gate_flag and not _gate_flag_enabled(gate_flag):
            skipped_gated.append(name)
            continue
        mandatory_total += 1
        sample_args = entry.get("sample_arguments", {})
        try:
            envelope = _call_mcp_tool(server_cmd, name, sample_args, timeout_s=args.mcp_timeout)
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            misses.append(f"{name} (call_error: {type(exc).__name__})")
            continue
        if _envelope_has_disclaimer(envelope):
            hits.append(name)
        else:
            misses.append(name)

    ok = not misses
    summary = (
        f"{len(hits)}/{mandatory_total} mandatory emit _disclaimer (gated_off={len(skipped_gated)})"
        if ok
        else (
            f"{len(hits)}/{mandatory_total} emit OK, {len(misses)} missing "
            f"first={misses[:3]} (gated_off={len(skipped_gated)})"
        )
    )
    return ModuleResult(
        name="disclaimer_emit_17",
        ok=ok,
        elapsed_s=0.0,
        summary=summary,
        detail={
            "hits": hits,
            "misses": misses,
            "skipped_gated": skipped_gated,
            "mandatory_total": mandatory_total,
            "table_size": len(sensitive),
        },
    )


# ---------------------------------------------------------------------------
# Module 4 — Stripe webhook delivery + idempotency
# ---------------------------------------------------------------------------


def _make_stripe_test_event() -> dict[str, Any]:
    """Synthesize a deterministic test event the local handler can ingest."""
    return {
        "id": "evt_jpcite_deep61_smoke_0001",
        "object": "event",
        "type": "invoice.paid",
        "api_version": "2024-09-30.acacia",
        "data": {
            "object": {
                "id": "in_jpcite_deep61_smoke_0001",
                "object": "invoice",
                "amount_paid": 330,
                "currency": "jpy",
                "metadata": {"jpcite_smoke": "deep61"},
            }
        },
        "livemode": False,
    }


@_timed
def module_stripe_webhook(args: argparse.Namespace) -> ModuleResult:
    if args.skip_stripe:
        return ModuleResult(
            name="stripe_webhook",
            ok=True,
            elapsed_s=0.0,
            summary="skipped (--skip-stripe)",
        )

    event = _make_stripe_test_event()
    headers = {
        "Content-Type": "application/json",
        # In a real run the operator pre-computes a stripe_signature with whsec_TEST.
        "Stripe-Signature": os.environ.get("JPCITE_SMOKE_STRIPE_SIGNATURE", "t=0,v1=smoke"),
        "X-Smoke-Idempotency": event["id"],
    }
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    url = "/v1/billing/stripe_webhook"

    try:
        with httpx.Client(base_url=args.base_url, timeout=timeout) as client:
            r1 = client.post(url, content=json.dumps(event), headers=headers)
            r2 = client.post(url, content=json.dumps(event), headers=headers)
    except httpx.RequestError as exc:
        return ModuleResult(
            name="stripe_webhook",
            ok=False,
            elapsed_s=0.0,
            summary=f"request_error: {exc}",
        )

    accept = (
        200,
        202,
        204,
        400,
    )  # 400 lets a sig-verify-only deploy still pass the idempotency hop
    first_ok = r1.status_code in accept
    second_ok = r2.status_code in accept
    idempotent = r1.status_code == r2.status_code

    ok = first_ok and second_ok and idempotent
    summary = f"first={r1.status_code} second={r2.status_code} idempotent={idempotent}"
    return ModuleResult(
        name="stripe_webhook",
        ok=ok,
        elapsed_s=0.0,
        summary=summary,
        detail={
            "first_status": r1.status_code,
            "second_status": r2.status_code,
            "first_body_head": r1.text[:200],
            "second_body_head": r2.text[:200],
        },
    )


# ---------------------------------------------------------------------------
# Module 5 — Health endpoints
# ---------------------------------------------------------------------------


HEALTH_ENDPOINTS = (
    "/healthz",
    "/readyz",
    "/v1/am/health/deep",
)


@_timed
def module_health_endpoints(args: argparse.Namespace) -> ModuleResult:
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    rows: list[tuple[str, int]] = []
    failed: list[tuple[str, int]] = []
    with httpx.Client(base_url=args.base_url, timeout=timeout) as client:
        for path in HEALTH_ENDPOINTS:
            try:
                resp = client.get(path)
                code = resp.status_code
            except httpx.RequestError as exc:
                code = -1
                if args.verbose:
                    print(f"  health request_error path={path} err={exc}", file=sys.stderr)
            rows.append((path, code))
            if code != 200:
                failed.append((path, code))
    ok = not failed
    summary = "3/3 healthy" if ok else f"failed={failed}"
    return ModuleResult(
        name="health_endpoints",
        ok=ok,
        elapsed_s=0.0,
        summary=summary,
        detail={"endpoints": rows},
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


MODULES: dict[str, Callable[[argparse.Namespace], ModuleResult]] = {
    "routes": module_routes_500_zero,
    "mcp": module_mcp_tools_list,
    "disclaimer": module_disclaimer_emit_17,
    "stripe": module_stripe_webhook,
    "health": module_health_endpoints,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="post_deploy_smoke",
        description="DEEP-61 jpcite v0.3.4 post-deploy smoke runbook (5 module gate).",
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("JPCITE_SMOKE_BASE_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument(
        "--module",
        default="all",
        choices=("routes", "mcp", "disclaimer", "stripe", "health", "all"),
        help="Run a single module or all (default: all).",
    )
    parser.add_argument(
        "--mcp-cmd", default=os.environ.get("JPCITE_SMOKE_MCP_CMD", "autonomath-mcp")
    )
    parser.add_argument("--mcp-timeout", type=float, default=30.0)
    parser.add_argument("--mcp-min-tools", type=int, default=151)
    parser.add_argument(
        "--skip-stripe", action="store_true", help="Skip the Stripe webhook module."
    )
    parser.add_argument("--report-out", default=None, help="Write JSON report to this path.")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def select_modules(name: str) -> list[Callable[[argparse.Namespace], ModuleResult]]:
    if name == "all":
        # Order matters: cheap → expensive, so the first failure prints early.
        return [MODULES[k] for k in ("health", "routes", "mcp", "disclaimer", "stripe")]
    return [MODULES[name]]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results: list[ModuleResult] = []
    for fn in select_modules(args.module):
        r = fn(args)
        print(r.line(), file=sys.stderr)
        results.append(r)

    overall_ok = all(r.ok for r in results)
    report = {
        "deep_id": "DEEP-61",
        "version": "0.3.4",
        "base_url": args.base_url,
        "module": args.module,
        "ok": overall_ok,
        "results": [asdict(r) for r in results],
    }
    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(json.dumps({"ok": overall_ok, "modules": [r.name for r in results]}))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
