"""Moat N8 — 15 jpcite recipe bank MCP tools (2 tools, file-backed).

Surfaces the 15 ``recipe_*.yaml`` machine-readable call sequences stored
in ``data/recipes/`` (Lane N8 deliverable). Covers 5 士業 segments ×
3 scenarios each:

* 税理士 (tax): monthly_closing / year_end_adjustment / corporate_filing
* 会計士 (audit): workpaper_compile / internal_control / consolidation
* 行政書士 (gyousei): subsidy_application_draft / license_renewal /
  contract_compliance_check
* 司法書士 (shihoshoshi): corporate_setup_registration /
  director_change_registration / real_estate_transfer
* AX エンジニア / FDE (ax_fde): client_onboarding /
  domain_expertise_transfer / compliance_dashboard

Tools
-----

* ``get_recipe(recipe_name)`` — fetch one recipe (preconditions / steps /
  output_artifact / disclaimer / cost / duration). Pure file read.
* ``list_recipes(segment="all")`` — enumerate recipe summaries
  (recipe_name / title / disclaimer / step_count / billable_units /
  cost_estimate_jpy / expected_duration_seconds). Filter by segment or
  ``"all"`` for the full 15-recipe catalog.

Hard constraints
----------------

* NO LLM inference. Pure filesystem read + tiny YAML-subset parse + JSON
  envelope.
* Every response carries a ``_disclaimer`` envelope referencing the five
  regulated 士業 (§52 / §47条の2 / §72 / §1 / §3 / 社労士法) because each
  recipe ends in a scaffold or reference deliverable, not a legally
  certified filing.
* Recipes carry ``no_llm_required = 1`` by construction; the tool
  surfaces that flag so agents cannot mistake the response for a finished
  outcome.
* Read-only file access — recipes are versioned in git.
* Gated by the lane N10 master flag ``JPCITE_MOAT_LANES_ENABLED`` (default ON).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.moat_n8_recipe")

# Canonical segment labels (must match the YAML ``segment`` field).
_SEGMENTS = ("tax", "audit", "gyousei", "shihoshoshi", "ax_fde")
_SEGMENT_PATTERN = r"^(tax|audit|gyousei|shihoshoshi|ax_fde|all)$"
_LANE_ID = "N8"
_SCHEMA_VERSION = "moat.n8.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.n8_recipe"

# Per-segment friendly Japanese label.
_SEGMENT_LABEL_JA: dict[str, str] = {
    "tax": "税理士",
    "audit": "会計士",
    "gyousei": "行政書士",
    "shihoshoshi": "司法書士",
    "ax_fde": "AX エンジニア / FDE",
}


def _recipe_dir() -> Path:
    """Resolve the data/recipes/ directory relative to the repo root.

    moat_lane_tools/ -> mcp/ -> jpintel_mcp/ -> src/ -> repo root
    """
    return Path(__file__).resolve().parents[4] / "data" / "recipes"


# ---------------------------------------------------------------------------
# Tiny YAML-subset parser
# ---------------------------------------------------------------------------
#
# The recipe YAML format is deliberately limited (top-level scalar +
# nested 2-space-indent dict + list-of-dicts). We avoid a runtime
# dependency on PyYAML by parsing inline. The parser is sufficient for
# every recipe shipped in lane N8; it is NOT a general YAML parser.


def _coerce_scalar(value: str) -> Any:
    """Convert a YAML scalar token to a Python type."""
    v = value.strip()
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    lower = v.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none", "~"):
        return None
    if v == "{}":
        return {}
    if v == "[]":
        return []
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _indent_of(line: str) -> int:
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        else:
            break
    return n


def _parse_yaml_recipe(text: str) -> dict[str, Any]:
    """Parse a recipe YAML file into a Python dict.

    Supports the strict subset used by ``data/recipes/recipe_*.yaml``:
      * Top-level scalar / list / nested dict keys (no leading whitespace).
      * 2-space indent for nested blocks.
      * ``- key: value`` list-of-dict entries (e.g. the ``steps`` list).
      * Scalars: bare / single-quoted / double-quoted / int / float /
        true|false|null|{}|[].
    """
    text = text.strip()
    if text.startswith("{"):
        # JSON fallback for forward compatibility.
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
        raise ValueError("top-level JSON must be an object")
    lines = text.split("\n")
    return _parse_block(lines, base_indent=0)


def _parse_block(lines: list[str], *, base_indent: int) -> dict[str, Any]:
    """Parse a block of lines at the given base indent into a dict."""
    out: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        cur_indent = _indent_of(line)
        if cur_indent != base_indent:
            # Line belongs to an inner block; should have been consumed
            # by a recursive call. Skip defensively.
            i += 1
            continue
        if ":" not in stripped:
            i += 1
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            out[key] = _coerce_scalar(value)
            i += 1
            continue
        # Nested block — collect indented lines at base_indent + 2.
        inner: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip() or nxt.strip().startswith("#"):
                inner.append(nxt)
                j += 1
                continue
            if _indent_of(nxt) >= base_indent + 2:
                inner.append(nxt)
                j += 1
            else:
                break
        if _block_is_list(inner, base_indent + 2):
            out[key] = _parse_list_block(inner, base_indent + 2)
        else:
            out[key] = _parse_block(inner, base_indent=base_indent + 2)
        i = j
    return out


def _block_is_list(lines: list[str], base_indent: int) -> bool:
    """Return True if this block is a list-of-dicts (``- key: value`` head)."""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # First content line at our indent doesn't start with "- " → dict.
        return _indent_of(line) == base_indent and stripped.startswith("- ")
    return False


def _parse_list_block(lines: list[str], base_indent: int) -> list[Any]:
    """Parse a list-of-dicts block at base_indent."""
    items: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        cur_indent = _indent_of(line)
        if cur_indent == base_indent and stripped.startswith("- "):
            if current:
                items.append(current)
                current = {}
            inner = stripped[2:]
            if ":" in inner:
                k, _, v = inner.partition(":")
                k = k.strip()
                v = v.strip()
                if v:
                    current[k] = _coerce_scalar(v)
                else:
                    # Sub-block follows (rare in recipes).
                    sub_lines: list[str] = []
                    j = i + 1
                    while j < len(lines):
                        nxt = lines[j]
                        if not nxt.strip():
                            sub_lines.append(nxt)
                            j += 1
                            continue
                        if _indent_of(nxt) >= base_indent + 4:
                            sub_lines.append(nxt)
                            j += 1
                        else:
                            break
                    current[k] = _parse_block(sub_lines, base_indent=base_indent + 4)
                    i = j
                    continue
            i += 1
        elif cur_indent >= base_indent + 2:
            # Continuation of the current list item (regular k: v line).
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip()
                if v:
                    current[k] = _coerce_scalar(v)
                    i += 1
                else:
                    # Nested mapping inside the list item.
                    sub_lines = []
                    j = i + 1
                    while j < len(lines):
                        nxt = lines[j]
                        if not nxt.strip():
                            sub_lines.append(nxt)
                            j += 1
                            continue
                        if _indent_of(nxt) >= cur_indent + 2:
                            sub_lines.append(nxt)
                            j += 1
                        else:
                            break
                    current[k] = _parse_block(sub_lines, base_indent=cur_indent + 2)
                    i = j
            else:
                i += 1
        else:
            break
    if current:
        items.append(current)
    return items


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


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
            "wrap_kind": "moat_lane_n8_recipe_files",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


def _recipe_summary(recipe: dict[str, Any]) -> dict[str, Any]:
    steps = recipe.get("steps", [])
    step_count = len(steps) if isinstance(steps, list) else 0
    return {
        "recipe_name": recipe.get("recipe_name"),
        "segment": recipe.get("segment"),
        "segment_label_ja": _SEGMENT_LABEL_JA.get(str(recipe.get("segment", ""))),
        "title": recipe.get("title"),
        "disclaimer": recipe.get("disclaimer"),
        "step_count": step_count,
        "billable_units": recipe.get("billable_units"),
        "cost_estimate_jpy": recipe.get("cost_estimate_jpy"),
        "expected_duration_seconds": recipe.get("expected_duration_seconds"),
        "parallel_calls_supported": bool(recipe.get("parallel_calls_supported", False)),
        "no_llm_required": bool(recipe.get("no_llm_required", True)),
    }


def _load_recipes() -> list[dict[str, Any]]:
    """Load every recipe YAML in ``data/recipes/``. Empty list if missing."""
    rdir = _recipe_dir()
    if not rdir.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(rdir.glob("recipe_*.yaml")):
        try:
            text = path.read_text(encoding="utf-8")
            recipe = _parse_yaml_recipe(text)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("recipe parse failed for %s: %s", path, exc)
            continue
        # Backfill recipe_name from filename if missing.
        recipe.setdefault("recipe_name", path.stem)
        out.append(recipe)
    return out


# ---------------------------------------------------------------------------
# MCP tool surface
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def get_recipe(
    recipe_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Recipe slug (e.g. 'recipe_tax_monthly_closing'). Call "
                "list_recipes for the per-segment manifest of valid values."
            ),
        ),
    ],
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - SS52/SS47-2/SS72/SS1/SS3] Moat N8 fetch a single
    recipe's full deterministic call sequence (preconditions + steps + args +
    output_artifact + disclaimer). Returns the structured payload an agent
    can iterate over to execute the recipe step-by-step. NO LLM inference.
    """
    primary_input = {"recipe_name": recipe_name}
    # Defensive: refuse traversal attempts.
    if "/" in recipe_name or ".." in recipe_name:
        return _empty_envelope(
            tool_name="get_recipe",
            primary_input=primary_input,
            rationale="recipe_name must be a bare slug (no slashes or relative paths).",
        )
    if not recipe_name.startswith("recipe_"):
        return _empty_envelope(
            tool_name="get_recipe",
            primary_input=primary_input,
            rationale="recipe_name must start with 'recipe_'; call list_recipes for the canonical manifest.",
        )
    path = _recipe_dir() / f"{recipe_name}.yaml"
    if not path.exists():
        return _empty_envelope(
            tool_name="get_recipe",
            primary_input=primary_input,
            rationale=f"recipe not found: {recipe_name}",
        )
    try:
        text = path.read_text(encoding="utf-8")
        recipe = _parse_yaml_recipe(text)
    except Exception as exc:
        return _empty_envelope(
            tool_name="get_recipe",
            primary_input=primary_input,
            rationale=f"recipe parse failed: {exc}",
        )
    recipe.setdefault("recipe_name", path.stem)
    segment = recipe.get("segment")
    return {
        "tool_name": "get_recipe",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": recipe,
        "results": [recipe],
        "total": 1,
        "limit": 1,
        "offset": 0,
        "citations": [
            {
                "kind": "disclaimer",
                "text": recipe.get("disclaimer", ""),
            },
            {
                "kind": "segment",
                "text": _SEGMENT_LABEL_JA.get(str(segment), str(segment)),
            },
        ],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n8_recipe_files",
            "observed_at": today_iso_utc(),
            "recipe_path": str(path.name),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=_READ_ONLY)
def list_recipes(
    segment: Annotated[
        str,
        Field(
            pattern=_SEGMENT_PATTERN,
            description=("Segment filter (tax / audit / gyousei / shihoshoshi / ax_fde / all)."),
        ),
    ] = "all",
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max recipe summaries to return."),
    ] = 50,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - SS52/SS47-2/SS72/SS1/SS3] Moat N8 enumerate recipe
    summaries by segment. Returns lightweight per-recipe metadata
    (recipe_name / segment / title / disclaimer / step_count / cost_estimate /
    duration / parallel_calls_supported). Pass ``"all"`` for the 15-recipe
    catalog, or a concrete segment for the 3 scenarios under that 士業.
    Detailed step sequence + output_artifact schema available via
    ``get_recipe``.
    """
    primary_input = {"segment": segment, "limit": limit}
    recipes = _load_recipes()
    if not recipes:
        return _empty_envelope(
            tool_name="list_recipes",
            primary_input=primary_input,
            rationale="no recipe files found under data/recipes/ (lane N8 missing).",
        )
    if segment != "all":
        recipes = [r for r in recipes if r.get("segment") == segment]
    if not recipes:
        return _empty_envelope(
            tool_name="list_recipes",
            primary_input=primary_input,
            rationale=f"no recipes registered for segment={segment}",
        )
    summaries = [_recipe_summary(r) for r in recipes[:limit]]
    return {
        "tool_name": "list_recipes",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "segment": segment,
            "total": len(summaries),
        },
        "results": summaries,
        "total": len(summaries),
        "limit": limit,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_n8_recipe_files",
            "observed_at": today_iso_utc(),
            "row_count": len(summaries),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
    }
