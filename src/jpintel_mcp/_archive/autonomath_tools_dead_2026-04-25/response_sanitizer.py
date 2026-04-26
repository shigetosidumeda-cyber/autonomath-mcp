"""Response-time sanitizer for MCP tool output.

Second line of defense in AutonoMath's prompt-injection model. Even if
ingest-time sanitize missed something (new pattern, upstream edit, cache),
every text field delivered to a customer LLM passes through here.

Usage (inside mcp_new tool handlers):

    from mcp_new.response_sanitizer import sanitize_envelope

    payload = build_payload(...)
    envelope = sanitize_envelope({"data": payload, "meta": {}})
    return envelope

The returned envelope always carries:
    envelope["meta"]["sanitized"]  : True / False
    envelope["meta"]["reasons"]    : ["field_path:pattern_id", ...]

Flagged strings are replaced with "[flagged]".
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Tuple

# Re-use ingest patterns. We keep the two modules decoupled at import level.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_INGEST_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "ingest"))
if _INGEST_DIR not in sys.path:
    sys.path.insert(0, _INGEST_DIR)

from .prompt_injection_sanitizer import sanitize_text  # noqa: E402

FLAG_PLACEHOLDER = "[flagged]"

# field names that carry free-text destined for a customer LLM
TEXT_FIELDS = {
    "description",
    "eligibility_text",
    "summary",
    "notes",
    "text",
    "content",
    "answer",
    "body",
}


def _walk(node: Any, path: str, reasons: List[Tuple[str, str]]) -> Any:
    if isinstance(node, dict):
        out: dict = {}
        for k, v in node.items():
            child_path = f"{path}.{k}" if path else str(k)
            if isinstance(v, str) and k in TEXT_FIELDS:
                res = sanitize_text(v)
                if res.flagged:
                    for h in res.hits:
                        reasons.append((child_path, h))
                    out[k] = FLAG_PLACEHOLDER
                else:
                    out[k] = v
            else:
                out[k] = _walk(v, child_path, reasons)
        return out
    if isinstance(node, list):
        return [_walk(item, f"{path}[{i}]", reasons) for i, item in enumerate(node)]
    return node


def sanitize_payload(payload: Any) -> tuple[Any, List[str]]:
    """Walk payload, sanitize any known customer-facing text field.

    Returns (clean_payload, reasons_flat) where reasons_flat is a list of
    "field.path:pattern_id" strings.
    """
    reasons: list[tuple[str, str]] = []
    clean = _walk(payload, "", reasons)
    flat = [f"{p}:{pid}" for p, pid in reasons]
    return clean, flat


def sanitize_envelope(envelope: dict) -> dict:
    """Canonical MCP response post-process.

    Expects `envelope = {"data": ..., "meta": {...}}`. Adds:
        meta.sanitized : bool
        meta.reasons   : list[str]
    Idempotent.
    """
    data = envelope.get("data")
    meta = dict(envelope.get("meta") or {})
    clean, reasons = sanitize_payload(data)
    meta["sanitized"] = bool(reasons)
    meta["reasons"] = reasons
    meta.setdefault("defense_layer", "response_sanitizer.v1")
    return {"data": clean, "meta": meta}


__all__ = ["sanitize_envelope", "sanitize_payload", "FLAG_PLACEHOLDER"]
