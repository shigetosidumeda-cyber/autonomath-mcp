"""MOAT N5 — resolve_alias MCP tool (2026-05-17).

Surfaces the ~433K row ``am_alias`` dictionary as a deterministic
text -> canonical_id_list[] resolver. Two stages: exact + NFKC.
"""

from __future__ import annotations

import logging
import os
import time
import unicodedata
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.resolve_alias")

_ENABLED = os.environ.get("AUTONOMATH_RESOLVE_ALIAS_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

_DISCLAIMER = (
    "am_alias (~433K rows) one-shot resolver. NOT legal advice; "
    "see TaxAccountantsLaw 52 / CertifiedPublicAccountantsLaw 47-2 / "
    "AttorneysLaw 72 / AdministrativeScrivenersLaw 1 / "
    "JudicialScrivenersLaw 3 envelope."
)

_VALID_ENTITY_TABLES: tuple[str, ...] = (
    "am_entities",
    "am_authority",
    "am_law",
    "am_industry_jsic",
    "am_region",
    "am_target_profile",
)

_MAX_LIMIT = 50
_DEFAULT_LIMIT = 10


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _resolve_alias_impl(
    text: str,
    entity_table: str | None,
    limit: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    text = text.strip()
    if not text:
        return make_error(
            code="invalid_argument",
            message="text must be a non-empty string after strip().",
        )

    if entity_table is not None and entity_table not in _VALID_ENTITY_TABLES:
        return make_error(
            code="invalid_argument",
            message=(
                f"entity_table must be one of {_VALID_ENTITY_TABLES!r} "
                f"or null; got {entity_table!r}."
            ),
        )

    effective_limit = max(1, min(_MAX_LIMIT, int(limit)))
    normalized = _normalize(text)

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    conn = connect_autonomath()
    try:
        if entity_table is None:
            cursor = conn.execute(
                "SELECT entity_table, canonical_id, alias, alias_kind, language "
                "FROM am_alias WHERE alias = ? LIMIT ?",
                (text, effective_limit),
            )
        else:
            cursor = conn.execute(
                "SELECT entity_table, canonical_id, alias, alias_kind, language "
                "FROM am_alias WHERE alias = ? AND entity_table = ? LIMIT ?",
                (text, entity_table, effective_limit),
            )
        for et, cid, alias_hit, kind, language in cursor:
            key = (str(et), str(cid), str(alias_hit))
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "entity_table": str(et),
                    "canonical_id": str(cid),
                    "alias_hit": str(alias_hit),
                    "alias_kind": str(kind),
                    "language": str(language) if language else "ja",
                    "confidence": 1.0,
                    "match_stage": "exact",
                }
            )

        if len(results) < effective_limit and normalized != text:
            remaining = effective_limit - len(results)
            if entity_table is None:
                cursor = conn.execute(
                    "SELECT entity_table, canonical_id, alias, alias_kind, language "
                    "FROM am_alias WHERE alias = ? LIMIT ?",
                    (normalized, remaining),
                )
            else:
                cursor = conn.execute(
                    "SELECT entity_table, canonical_id, alias, alias_kind, language "
                    "FROM am_alias WHERE alias = ? AND entity_table = ? LIMIT ?",
                    (normalized, entity_table, remaining),
                )
            for et, cid, alias_hit, kind, language in cursor:
                key = (str(et), str(cid), str(alias_hit))
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    {
                        "entity_table": str(et),
                        "canonical_id": str(cid),
                        "alias_hit": str(alias_hit),
                        "alias_kind": str(kind),
                        "language": str(language) if language else "ja",
                        "confidence": 0.9,
                        "match_stage": "nfkc",
                    }
                )
    finally:
        conn.close()

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "query": text,
        "normalized": normalized,
        "results": results,
        "total": len(results),
        "elapsed_ms": round(elapsed_ms, 2),
        "no_llm": True,
        "_disclaimer": _DISCLAIMER,
    }


if _ENABLED:

    @mcp.tool(
        description=(
            "MOAT N5 - Resolve a colloquial JP term to canonical_id[]. "
            "Uses am_alias (~433K rows). Single 3 JPY/req. NO LLM."
        )
    )
    def resolve_alias(
        text: Annotated[
            str,
            Field(
                description=(
                    "Free-text Japanese term to resolve "
                    "(invoice / IT-grant / etc). NFKC fallback runs auto."
                ),
                min_length=1,
                max_length=256,
            ),
        ],
        entity_table: Annotated[
            str | None,
            Field(
                description=(f"Optional entity_table filter ({', '.join(_VALID_ENTITY_TABLES)})."),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                description=(f"Max rows to return (1..{_MAX_LIMIT}, default {_DEFAULT_LIMIT})."),
                ge=1,
                le=_MAX_LIMIT,
            ),
        ] = _DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        return _resolve_alias_impl(text, entity_table, limit)
