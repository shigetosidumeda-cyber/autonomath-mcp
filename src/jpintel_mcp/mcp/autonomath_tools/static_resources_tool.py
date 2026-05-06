"""MCP tool wrappers for static_resources.py.

Registers four read-only tools that serve curated taxonomies + canonical
example payloads:
  - list_static_resources_am
  - get_static_resource_am(resource_id)
  - list_example_profiles_am
  - get_example_profile_am(profile_id)

Pure file reads, zero compute, zero LLM. Backed by JSON files under
``data/autonomath_static/`` (8 taxonomies + 5 example profiles).
"""

from __future__ import annotations

import logging
from typing import Annotated

from pydantic import Field

from jpintel_mcp.mcp._error_helpers import safe_internal_message
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error
from .static_resources import (
    ResourceNotFoundError,
    get_example_profile,
    get_static_resource,
    list_example_profiles,
    list_static_resources,
)

logger = logging.getLogger("jpintel.mcp.am.static")


@mcp.tool(annotations=_READ_ONLY)
def list_static_resources_am() -> dict[str, object]:
    """Manifest of curated jpcite taxonomies (制度 / 用語 / 助成区分 / 義務 etc.).

    Returns 8 entries (seido / glossary / money_types / obligations /
    dealbreakers / sector_combos / crop_library / exclusion_rules). Each
    entry carries id + filename + size_bytes; use ``get_static_resource_am``
    with the id to fetch the full payload.

    Example:
        list_static_resources_am()
        → {"total": 8, "results": [{"id": "seido", "filename": "seido.json", ...}, ...]}

    When NOT to call:
        - To LOAD a specific taxonomy → use get_static_resource_am(resource_id=...).
        - For the runtime program list (実データ) → use search_programs / list_open_programs.
        - For example client profiles → use list_example_profiles_am instead.
        - For database-level enum values (industry_jsic etc.) → use enum_values_am.

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    try:
        results = list_static_resources()
        if not results:
            return {
                "total": 0,
                "items": [],
                "results": [],
                "hint": (
                    "data/autonomath_static/ の taxonomy ファイルが見つかりません。"
                    "デプロイ漏れの可能性があります。enum_values_am で代替値を確認してください。"
                ),
                "retry_with": ["enum_values_am", "list_example_profiles_am"],
            }
        return {"total": len(results), "results": results}
    except Exception as exc:
        msg, _ = safe_internal_message(exc, logger=logger, tool_name="list_static_resources_am")
        return make_error("internal", msg)


@mcp.tool(annotations=_READ_ONLY)
def get_static_resource_am(
    resource_id: Annotated[
        str,
        Field(
            description=(
                "One of: seido, glossary, money_types, obligations, "
                "dealbreakers, sector_combos, crop_library, exclusion_rules. "
                "Call list_static_resources_am to enumerate."
            )
        ),
    ],
) -> dict[str, object]:
    """Load one curated taxonomy / lookup file. Returns full JSON + license.

    Resolves controlled-vocabulary keys (e.g. seido kind codes, money_types,
    obligations) to their human labels and parent groupings. Pure file read,
    zero compute, zero LLM.

    Example:
        get_static_resource_am(resource_id="seido")
        → {"resource_id": "seido", "content": [...], "license": "CC0-1.0"}

    When NOT to call:
        - To DISCOVER which resource_ids exist → use list_static_resources_am first.
        - For a CLIENT-INTAKE profile shape → use get_example_profile_am instead.
        - For runtime program search (q="設備投資") → use search_programs / list_open_programs.
        - For statutory text → use search_laws / get_law (taxonomy is metadata, not law).
    """
    try:
        return get_static_resource(resource_id)
    except ResourceNotFoundError as exc:
        # ResourceNotFoundError carries the resource_id the caller passed
        # (no internal leak). Forward it so the LLM can self-correct.
        return make_error(
            "seed_not_found",
            str(exc),
            hint=(
                "Call list_static_resources_am to enumerate the 8 valid "
                "resource_ids (seido / glossary / money_types / "
                "obligations / dealbreakers / sector_combos / "
                "crop_library / exclusion_rules)."
            ),
            retry_with=["list_static_resources_am"],
        )
    except Exception as exc:
        msg, _ = safe_internal_message(
            exc,
            logger=logger,
            tool_name="get_static_resource_am",
            extra={"resource_id": resource_id},
        )
        return make_error("internal", msg)


@mcp.tool(annotations=_READ_ONLY)
def list_example_profiles_am() -> dict[str, object]:
    """Manifest of canonical client-intake example payloads (PII-clean).

    Use these as reference shapes when constructing ``business_profile`` /
    ``profile`` arguments for downstream tools (validation, eligibility,
    tax-applicability, bid-screening). Returns id + label + summary; pass
    each id to ``get_example_profile_am`` for the full JSON payload.

    Example:
        list_example_profiles_am()
        → {"total": 5, "results": [{"profile_id": "ichigo_20a", ...}, ...]}

    When NOT to call:
        - To fetch the actual profile JSON → use get_example_profile_am(profile_id).
        - For the controlled-vocabulary list (industry codes / 助成区分) →
          use list_static_resources_am instead.
        - For real client records — these are CC0 fixtures, not anonymised data.

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    try:
        results = list_example_profiles()
        if not results:
            return {
                "total": 0,
                "items": [],
                "results": [],
                "hint": (
                    "data/autonomath_static/example_profiles/ が空です。"
                    "デプロイ漏れの可能性があります。"
                    "list_static_resources_am で taxonomy 一覧を確認してください。"
                ),
                "retry_with": ["list_static_resources_am", "enum_values_am"],
            }
        return {"total": len(results), "results": results}
    except Exception as exc:
        msg, _ = safe_internal_message(exc, logger=logger, tool_name="list_example_profiles_am")
        return make_error("internal", msg)


@mcp.tool(annotations=_READ_ONLY)
def get_example_profile_am(
    profile_id: Annotated[
        str,
        Field(
            description=(
                "One of: ichigo_20a, rice_200a, new_corp, "
                "dairy_100head, minimal. Call list_example_profiles_am "
                "to enumerate."
            )
        ),
    ],
) -> dict[str, object]:
    """Return one canonical client profile JSON as a complete-payload example.

    Use this as a copy-paste seed for the ``business_profile`` argument to
    ``evaluate_tax_applicability`` / ``bid_eligible_for_profile`` / DD tools —
    every required key is present with a plausible value.

    Example:
        get_example_profile_am(profile_id="ichigo_20a")
        → {"profile_id": "ichigo_20a", "profile": {...}, "license": "CC0-1.0"}

    When NOT to call:
        - To enumerate available profile_ids → use list_example_profiles_am.
        - To fetch a TAXONOMY (seido / glossary / 助成区分) → use get_static_resource_am.
        - For a real client's data — these are PII-clean fixtures, not real records.
    """
    try:
        return get_example_profile(profile_id)
    except ResourceNotFoundError as exc:
        return make_error(
            "seed_not_found",
            str(exc),
            hint=(
                "Call list_example_profiles_am to enumerate the 5 valid "
                "profile_ids (ichigo_20a / rice_200a / new_corp / "
                "dairy_100head / minimal)."
            ),
            retry_with=["list_example_profiles_am"],
        )
    except Exception as exc:
        msg, _ = safe_internal_message(
            exc,
            logger=logger,
            tool_name="get_example_profile_am",
            extra={"profile_id": profile_id},
        )
        return make_error("internal", msg)
