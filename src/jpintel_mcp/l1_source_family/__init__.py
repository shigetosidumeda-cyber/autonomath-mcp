"""Wave 51 L1 source family — static catalog of public-program data sources.

This package is the *static* registry layer for Wave 51 L1 (lateral source
expansion). It declares the 32 public-program source families specified in
``docs/_internal/WAVE51_L1_SOURCE_FAMILY_CATALOG.md`` along with their
ministry / category / license / access_mode / refresh / priority axes.

Hard constraints (enforced structurally, not by convention):

- **No live HTTP**: this module imports neither ``httpx``, ``requests``,
  nor any scraping library. The registry is pure metadata; downstream
  fetch/parse/validate machinery is wired separately.
- **No LLM SDK import**: ``anthropic`` / ``openai`` / ``google.generativeai``
  / ``claude_agent_sdk`` are forbidden under ``src/`` (CI guard
  ``tests/test_no_llm_in_production.py``). This package complies.
- **No DB access**: the registry does not open SQLite / PostgreSQL /
  Cloudflare KV; it is in-process Python only.

See ``catalog.py`` for the registry definition.
"""

from __future__ import annotations

from jpintel_mcp.l1_source_family.catalog import (
    SOURCE_FAMILY_REGISTRY,
    AccessMode,
    Category,
    LicenseTag,
    Ministry,
    Priority,
    RefreshFrequency,
    SourceFamily,
    get_source_family,
    list_source_families,
    list_source_families_by_priority,
)

__all__ = [
    "SOURCE_FAMILY_REGISTRY",
    "AccessMode",
    "Category",
    "LicenseTag",
    "Ministry",
    "Priority",
    "RefreshFrequency",
    "SourceFamily",
    "get_source_family",
    "list_source_families",
    "list_source_families_by_priority",
]
