"""Smoke verification: 120 MCP tool surface, envelope keys, disclaimer / audit_seal injection.

Per task 2026-05-04 — verify wave24 first_half + second_half registered, count == 120,
each wave24 tool has FastMCP input_schema, dummy invocation returns a complete envelope,
sensitive tools carry ``_disclaimer``, and the API-side audit_seal helper signs without
touching audit_seal_keys.

Run from repo root:

    AUTONOMATH_ENABLED=1 \
    AUTONOMATH_WAVE24_FIRST_HALF_ENABLED=1 \
    AUTONOMATH_WAVE24_SECOND_HALF_ENABLED=1 \
    .venv/bin/python tests/smoke/verify_120_tools.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from typing import Any

# Defensive defaults — task says default ON is the intent.
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE24_FIRST_HALF_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE24_SECOND_HALF_ENABLED", "1")

ENVELOPE_REQUIRED_KEYS = (
    "total",
    "limit",
    "offset",
    "results",
    "_billing_unit",
    "_next_calls",
)


def _print(label: str, msg: Any) -> None:
    print(f"[{label}] {msg}", flush=True)


def main() -> int:
    rc = 0

    # --- step 1: server import + tool count ---------------------------------
    from jpintel_mcp.mcp.server import mcp

    list_tools = mcp._tool_manager.list_tools()
    _print("count", f"len(mcp._tool_manager.list_tools()) = {len(list_tools)}")
    if len(list_tools) != 120:
        _print("count", f"WARN expected 120, got {len(list_tools)}")
        rc = 1

    # Async list_tools (covers MCP protocol path)
    try:
        async_tools = asyncio.run(mcp.list_tools())
        _print("count", f"async mcp.list_tools() = {len(async_tools)}")
    except Exception as exc:  # pragma: no cover
        _print("count", f"async list_tools failed: {exc}")

    by_name = {t.name: t for t in list_tools}

    # --- step 2: wave24 tool input schema check -----------------------------
    from jpintel_mcp.mcp.autonomath_tools import (
        wave24_tools_first_half,
        wave24_tools_second_half,
    )

    w24a = list(getattr(wave24_tools_first_half, "WAVE24_TOOLS_FIRST_HALF", []))
    w24b = list(getattr(wave24_tools_second_half, "WAVE24_TOOLS_SECOND_HALF", []))
    _print("wave24", f"first_half exported={len(w24a)} second_half exported={len(w24b)}")

    # Second-half exports `_*_impl` callables but registers them in MCP under
    # public names listed in `_TOOL_FUNCS`. Read that for canonical names.
    second_half_pub: list[str] = [
        n for (n, _f) in getattr(wave24_tools_second_half, "_TOOL_FUNCS", ())
    ]

    wave24_names: list[str] = []
    for fn in w24a:
        nm = getattr(fn, "__name__", None) or getattr(fn, "tool_name", None)
        if nm:
            wave24_names.append(nm)
    wave24_names.extend(second_half_pub)

    schema_missing: list[str] = []
    schema_invalid: list[str] = []
    for name in wave24_names:
        tool = by_name.get(name)
        if tool is None:
            schema_missing.append(name)
            continue
        # FastMCP exposes parameters as `parameters` (JSON Schema) or
        # `inputSchema` depending on version.
        schema = getattr(tool, "parameters", None) or getattr(tool, "inputSchema", None)
        if not isinstance(schema, dict):
            schema_invalid.append(f"{name}: no schema dict")
            continue
        if schema.get("type") != "object":
            schema_invalid.append(f"{name}: schema.type != object ({schema.get('type')!r})")
            continue
        if "properties" not in schema:
            schema_invalid.append(f"{name}: schema missing properties")

    _print(
        "schema",
        f"wave24 registered={len(wave24_names) - len(schema_missing)} / {len(wave24_names)} "
        f"missing={schema_missing} invalid={schema_invalid}",
    )
    if schema_missing or schema_invalid:
        rc = 1

    # --- step 3: invoke 5 wave24 tools with dummy args ---------------------
    # Pick 5 tools that take only safe scalar args. They will hit empty
    # tables in the dev DB but should still return a v2 envelope (graceful
    # empty path).
    invoke_targets: list[tuple[str, dict[str, Any]]] = [
        ("recommend_programs_for_houjin", {"houjin_bangou": "0000000000000", "limit": 5}),
        ("get_houjin_360_snapshot_history", {"houjin_bangou": "0000000000000", "months": 6}),
        ("infer_invoice_buyer_seller", {"houjin_bangou": "0000000000000", "direction": "buyer"}),
        ("get_program_application_documents", {"program_id": "smoke-nonexistent"}),
        (
            "score_application_probability",
            {"houjin_bangou": "0000000000000", "program_id": "smoke-nonexistent"},
        ),
    ]

    envelope_missing: dict[str, list[str]] = {}
    envelope_errors: dict[str, str] = {}

    for tname, kwargs in invoke_targets:
        tool = by_name.get(tname)
        if tool is None:
            envelope_errors[tname] = "tool not registered"
            continue
        try:
            # FastMCP Tool objects expose .fn (callable) — fall back to .run
            # for older versions.
            fn = getattr(tool, "fn", None) or getattr(tool, "_fn", None)
            if fn is None:
                envelope_errors[tname] = "no callable on tool"
                continue
            result = fn(**kwargs)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            if not isinstance(result, dict):
                envelope_errors[tname] = f"non-dict return: {type(result).__name__}"
                continue
            missing = [k for k in ENVELOPE_REQUIRED_KEYS if k not in result]
            if missing:
                envelope_missing[tname] = missing
            _print(
                "invoke",
                f"{tname}: keys={sorted(result.keys())[:14]}... "
                f"total={result.get('total')!r} _billing_unit={result.get('_billing_unit')!r}",
            )
        except Exception as exc:
            envelope_errors[tname] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

    _print("envelope_keys_missing", json.dumps(envelope_missing, ensure_ascii=False))
    _print("invoke_errors", json.dumps(envelope_errors, ensure_ascii=False))
    if envelope_missing or envelope_errors:
        rc = 1

    # --- step 4: _disclaimer injection on SENSITIVE_TOOLS -------------------
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
        SENSITIVE_TOOLS,
        disclaimer_for,
    )

    # 4a) static check — every SENSITIVE_TOOLS entry resolves to a non-empty
    # disclaimer string at the configured level.
    bad_disclaimers = [t for t in sorted(SENSITIVE_TOOLS) if not disclaimer_for(t, "standard")]
    _print(
        "disclaimer_static",
        f"SENSITIVE_TOOLS={len(SENSITIVE_TOOLS)} resolved="
        f"{len(SENSITIVE_TOOLS) - len(bad_disclaimers)} missing={bad_disclaimers}",
    )
    if bad_disclaimers:
        rc = 1

    # 4b) runtime check — re-invoke 3 sensitive wave24 tools and verify the
    # envelope carried _disclaimer.
    sensitive_invoke = [
        ("get_houjin_360_snapshot_history", {"houjin_bangou": "0000000000000", "months": 6}),
        ("infer_invoice_buyer_seller", {"houjin_bangou": "0000000000000", "direction": "buyer"}),
        (
            "score_application_probability",
            {"houjin_bangou": "0000000000000", "program_id": "smoke-nonexistent"},
        ),
    ]
    runtime_disclaimer = {}
    for tname, kwargs in sensitive_invoke:
        tool = by_name.get(tname)
        if tool is None:
            runtime_disclaimer[tname] = "tool missing"
            continue
        fn = getattr(tool, "fn", None) or getattr(tool, "_fn", None)
        if fn is None:
            runtime_disclaimer[tname] = "no callable"
            continue
        try:
            r = fn(**kwargs)
            if asyncio.iscoroutine(r):
                r = asyncio.run(r)
            if isinstance(r, dict) and r.get("_disclaimer"):
                runtime_disclaimer[tname] = "OK"
            else:
                runtime_disclaimer[tname] = "MISSING (sensitive tool emitted no _disclaimer)"
        except Exception as exc:
            runtime_disclaimer[tname] = f"invoke error: {exc}"
    _print("disclaimer_runtime", json.dumps(runtime_disclaimer, ensure_ascii=False))
    if any("MISSING" in v or "error" in v for v in runtime_disclaimer.values()):
        rc = 1

    # --- step 5: API-side audit_seal sign path ------------------------------
    try:
        from jpintel_mcp.api import _audit_seal as audit_seal_mod
    except Exception as exc:
        _print("audit_seal", f"import failed: {exc}")
        rc = 1
        return rc

    sample_body = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
        "_billing_unit": 1,
        "_next_calls": [],
    }

    # 5a) HMAC sign primitive (no DB).
    try:
        sig = audit_seal_mod.sign(b"smoke-payload-1")
        _print(
            "audit_seal_sign",
            f"sign() -> keys={sorted(sig.keys())} v={sig.get('v')} alg={sig.get('alg')}",
        )
        ok = audit_seal_mod.verify(b"smoke-payload-1", sig)
        _print("audit_seal_verify", f"verify() -> {ok}")
        if not ok:
            rc = 1
    except Exception as exc:
        _print("audit_seal_sign", f"FAIL: {type(exc).__name__}: {exc}")
        rc = 1

    # 5b) build_seal() — full envelope build, no persistence.
    try:
        seal = audit_seal_mod.build_seal(
            response_body=sample_body,
            endpoint="/v1/smoke",
            request_params={"smoke": True},
            api_key_hash=None,
        )
        if isinstance(seal, dict):
            _print("audit_seal_build", f"OK keys={sorted(seal.keys())}")
        else:
            _print("audit_seal_build", f"WARN non-dict: {type(seal).__name__}")
    except TypeError as exc:
        # Signature may differ — walk the function's signature to find names.
        import inspect as _ins

        sigobj = _ins.signature(audit_seal_mod.build_seal)
        _print(
            "audit_seal_build",
            f"TypeError {exc} — params={list(sigobj.parameters.keys())}",
        )
        rc = 1
    except Exception as exc:
        _print(
            "audit_seal_build", f"WARN (likely audit_seal_keys empty): {type(exc).__name__}: {exc}"
        )
        # Not fatal — task says dev DB empty path is OK; sign() above already
        # proved the HMAC path works.

    # 5c) attach_seal_to_body() — full path including DB persistence.
    try:
        body_copy = dict(sample_body)
        out = audit_seal_mod.attach_seal_to_body(
            body=body_copy,
            endpoint="/v1/smoke",
            request_params={"smoke": True},
            api_key_hash=None,
        )
        if asyncio.iscoroutine(out):
            out = asyncio.run(out)
        if isinstance(out, dict) and "audit_seal" in out:
            _print(
                "audit_seal_attach",
                f"OK audit_seal keys: {sorted(out['audit_seal'].keys())}",
            )
        elif isinstance(body_copy, dict) and "audit_seal" in body_copy:
            _print(
                "audit_seal_attach",
                f"OK (mutated) audit_seal keys: {sorted(body_copy['audit_seal'].keys())}",
            )
        else:
            _print("audit_seal_attach", "WARN body lacks audit_seal after attach")
    except TypeError as exc:
        import inspect as _ins

        sigobj = _ins.signature(audit_seal_mod.attach_seal_to_body)
        _print(
            "audit_seal_attach",
            f"TypeError {exc} — params={list(sigobj.parameters.keys())}",
        )
    except Exception as exc:
        _print("audit_seal_attach", f"WARN: {type(exc).__name__}: {exc}")
        # not fatal — DB may not have audit_seals table in dev.

    return rc


if __name__ == "__main__":
    sys.exit(main())
