"""Moat N9 — placeholder → MCP query resolver (1 tool, DB-backed).

Surfaces the placeholder mapping bank stored in ``am_placeholder_mapping``
(migration ``wave24_206_am_placeholder_mapping.sql``, target_db =
autonomath). ~207 canonical placeholders (HOUJIN_NAME / PROGRAM_ID /
LEGAL_BASIS_ARTICLE / TAX_RULE_RATE / etc.) bound to deterministic MCP
call schemas.

Tool
----

* ``resolve_placeholder(placeholder_name, context_dict_json)`` — given a
  canonical placeholder (e.g. ``"{{HOUJIN_NAME}}"``) and a JSON-encoded
  context dictionary, returns the resolved MCP call schema:
  (mcp_tool_name, args_substituted, output_path, fallback_value,
  value_kind, is_sensitive). The agent then invokes the indicated MCP
  tool with the substituted args and applies ``output_path`` to the
  response.

Hard constraints
----------------

* NO LLM inference. Pure SQLite read + JSON parse + token substitution.
* Sensitive placeholders (is_sensitive=1) carry a §-aware disclaimer
  envelope so the agent cannot silently strip the scaffold-only marker.
* Read-only SQLite connection (URI mode ``ro``).
* Gated by the lane N10 master flag ``JPCITE_MOAT_LANES_ENABLED`` (default ON).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.moat_n9_placeholder")

_LANE_ID = "N9"
_SCHEMA_VERSION = "moat.n9.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.n9_placeholder"

# Substitution token regex: {foo} or {foo.bar}. Dotted lookups let the
# args_template reference nested context keys compactly.
_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _open_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.warning("autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='am_placeholder_mapping' LIMIT 1"
    ).fetchone()
    return row is not None


def _empty_envelope(
    tool_name: str,
    primary_input: dict[str, Any],
    rationale: str,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "empty",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n9_placeholder_db",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


def _substitute_tokens(template: str, context: dict[str, Any]) -> str:
    """Substitute ``{token}`` references in ``template`` against ``context``.

    Supports dotted lookups ("foo.bar.baz") via repeated dict indexing.
    Missing tokens are left in place verbatim so the caller can detect
    leftover braces and fall back to the placeholder's ``fallback_value``.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        cur: Any = context
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return match.group(0)
            cur = cur[part]
        if cur is None:
            return match.group(0)
        return str(cur)

    return _TOKEN_RE.sub(_replace, template)


def _row_to_mapping(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "placeholder_id": int(row["placeholder_id"]),
        "placeholder_name": row["placeholder_name"],
        "source_template_ids": row["source_template_ids"],
        "mcp_tool_name": row["mcp_tool_name"],
        "args_template": row["args_template"],
        "output_path": row["output_path"],
        "fallback_value": row["fallback_value"],
        "value_kind": row["value_kind"],
        "description": row["description"],
        "is_sensitive": bool(row["is_sensitive"]),
        "license": row["license"],
    }


@mcp.tool(annotations=_READ_ONLY)
def resolve_placeholder(
    placeholder_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Canonical placeholder with braces, e.g. '{{HOUJIN_NAME}}'. "
                "Must match a row in am_placeholder_mapping (lane N9). "
                "Case-sensitive."
            ),
        ),
    ],
    context_dict_json: Annotated[
        str,
        Field(
            description=(
                "JSON-encoded context dictionary providing token values for "
                "args_template substitution. Pass '{}' for context-free "
                "placeholders (CURRENT_DATE, OPERATOR_NAME, etc.)."
            ),
        ),
    ] = "{}",
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - SS52/SS47-2/SS72/SS1/SS3] Moat N9 resolve one
    placeholder to its canonical MCP call schema. Returns
    (mcp_tool_name, args_substituted, output_path, fallback_value, value_kind,
    is_sensitive) so the agent can deterministically execute the resolved
    call and apply output_path to the response. Special mcp_tool_name
    values: ``context`` (value already in context_dict) / ``computed``
    (deterministic CURRENT_DATE / OPERATOR_NAME / etc.). NO LLM inference.
    """
    primary_input = {
        "placeholder_name": placeholder_name,
        "context_dict_json": context_dict_json,
    }
    if not placeholder_name.strip():
        return _empty_envelope(
            tool_name="resolve_placeholder",
            primary_input=primary_input,
            rationale="placeholder_name is required.",
        )
    if not (placeholder_name.startswith("{{") and placeholder_name.endswith("}}")):
        return _empty_envelope(
            tool_name="resolve_placeholder",
            primary_input=primary_input,
            rationale=("placeholder_name must use canonical braces; wrap as '{{NAME}}'."),
        )
    try:
        context = json.loads(context_dict_json or "{}")
        if not isinstance(context, dict):
            raise ValueError("context_dict_json must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        return _empty_envelope(
            tool_name="resolve_placeholder",
            primary_input=primary_input,
            rationale=f"context_dict_json must be a JSON object: {exc}",
        )

    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            tool_name="resolve_placeholder",
            primary_input=primary_input,
            rationale="autonomath.db unreachable",
        )
    try:
        if not _table_present(conn):
            return _empty_envelope(
                tool_name="resolve_placeholder",
                primary_input=primary_input,
                rationale=(
                    "am_placeholder_mapping table missing (migration wave24_206 not applied)."
                ),
            )
        row = conn.execute(
            """
            SELECT placeholder_id, placeholder_name, source_template_ids,
                   mcp_tool_name, args_template, output_path, fallback_value,
                   value_kind, description, is_sensitive, license,
                   created_at, updated_at
              FROM am_placeholder_mapping
             WHERE placeholder_name = ?
            """,
            (placeholder_name,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return _empty_envelope(
            tool_name="resolve_placeholder",
            primary_input=primary_input,
            rationale=f"placeholder not found: {placeholder_name}",
        )
    mapping = _row_to_mapping(row)
    # Substitute tokens in args_template.
    substituted_str = _substitute_tokens(mapping["args_template"], context)
    try:
        args_substituted = json.loads(substituted_str)
        substitution_complete = True
    except json.JSONDecodeError:
        args_substituted = {}
        substitution_complete = False
    leftover_tokens = _TOKEN_RE.findall(substituted_str)
    mapping["args_substituted"] = args_substituted
    mapping["substitution_complete"] = bool(substitution_complete and not leftover_tokens)
    mapping["missing_context_keys"] = leftover_tokens
    return {
        "tool_name": "resolve_placeholder",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": mapping,
        "results": [mapping],
        "total": 1,
        "limit": 1,
        "offset": 0,
        "citations": [
            {"kind": "license", "text": mapping["license"]},
            {"kind": "value_kind", "text": mapping["value_kind"]},
        ],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n9_placeholder_db",
            "observed_at": today_iso_utc(),
            "row_count": 1,
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }
