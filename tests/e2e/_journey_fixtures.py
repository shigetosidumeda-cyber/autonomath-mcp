"""Shared fixtures + simulation harness for D4 E2E user-journey tests.

These tests live in ``tests/e2e/`` per design audit D4 — but they are NOT
Playwright tests. The sibling ``conftest.py`` only auto-skips items that
carry ``@pytest.mark.e2e``; plain function tests run during the default
``pytest`` invocation. We deliberately avoid the ``e2e`` marker so the
journey simulations exercise the real moat-lane tool functions on every
local run + CI shard.

Simulation contract
-------------------
- No live LLM call (NO_LLM_REQUIRED).
- No network I/O.
- All MCP tool functions are invoked as ordinary Python callables; the
  agent loop is modelled by ``JourneyAgent.invoke`` which records every
  call into a deterministic ledger (tool name + args + ¥3 cost).
- The fixture DB is seeded with:
    * am_artifact_templates (templates for 5 segments × N artifact_types)
    * am_placeholder_mapping (canonical placeholder → MCP call schema)
    * am_entities + am_entity_facts (one synthetic 法人)
    * am_houjin_program_portfolio (one program row)
    * am_window_directory (one 法務局 + one tax_office row)
    * am_legal_reasoning_chain (one synthetic chain for 監査調書 walk)

The shape mirrors the production schemas verified during audit D4 at
2026-05-17.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# --------------------------------------------------------------------------- #
# Schema fragments (idempotent CREATE TABLE statements)
# --------------------------------------------------------------------------- #

_SCHEMA_ARTIFACT_TEMPLATES = """
CREATE TABLE IF NOT EXISTS am_artifact_templates (
    template_id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    artifact_name_ja TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT 'v1',
    authority TEXT NOT NULL,
    sensitive_act TEXT NOT NULL,
    is_scaffold_only INTEGER NOT NULL DEFAULT 1,
    requires_professional_review INTEGER NOT NULL DEFAULT 1,
    uses_llm INTEGER NOT NULL DEFAULT 0,
    quality_grade TEXT NOT NULL DEFAULT 'draft',
    structure_jsonb TEXT NOT NULL,
    placeholders_jsonb TEXT NOT NULL,
    mcp_query_bindings_jsonb TEXT NOT NULL,
    license TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (segment, artifact_type, version)
);
"""

_SCHEMA_PLACEHOLDER_MAPPING = """
CREATE TABLE IF NOT EXISTS am_placeholder_mapping (
    placeholder_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    placeholder_name     TEXT NOT NULL UNIQUE,
    source_template_ids  TEXT,
    mcp_tool_name        TEXT NOT NULL,
    args_template        TEXT NOT NULL DEFAULT '{}',
    output_path          TEXT NOT NULL DEFAULT '$',
    fallback_value       TEXT,
    value_kind           TEXT NOT NULL DEFAULT 'text',
    description          TEXT NOT NULL,
    is_sensitive         INTEGER NOT NULL DEFAULT 0,
    license              TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_SCHEMA_ENTITIES = """
CREATE TABLE IF NOT EXISTS am_entities (
    canonical_id TEXT PRIMARY KEY,
    record_kind TEXT NOT NULL,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS am_entity_facts (
    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    value_text TEXT,
    confidence REAL DEFAULT 1.0,
    source_id INTEGER
);
"""

_SCHEMA_PORTFOLIO = """
CREATE TABLE IF NOT EXISTS am_houjin_program_portfolio (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou        TEXT NOT NULL,
    program_id           TEXT NOT NULL,
    applicability_score  REAL NOT NULL,
    score_industry       REAL NOT NULL DEFAULT 0.0,
    score_size           REAL NOT NULL DEFAULT 0.0,
    score_region         REAL NOT NULL DEFAULT 0.0,
    score_sector         REAL NOT NULL DEFAULT 0.0,
    score_target_form    REAL NOT NULL DEFAULT 0.0,
    applied_status       TEXT NOT NULL DEFAULT 'unknown',
    applied_at           TEXT,
    deadline             TEXT,
    deadline_kind        TEXT,
    priority_rank        INTEGER,
    computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    method               TEXT NOT NULL DEFAULT 'lane_n2_deterministic_v1',
    notes                TEXT
);
"""

_SCHEMA_WINDOW_DIRECTORY = """
CREATE TABLE IF NOT EXISTS am_window_directory (
    window_id                        TEXT PRIMARY KEY,
    jurisdiction_kind                TEXT NOT NULL,
    name                             TEXT NOT NULL,
    postal_address                   TEXT,
    jp_postcode                      TEXT,
    latitude_longitude               TEXT,
    tel                              TEXT,
    fax                              TEXT,
    email                            TEXT,
    url                              TEXT,
    opening_hours                    TEXT,
    jurisdiction_houjin_filter_regex TEXT,
    jurisdiction_region_code         TEXT,
    parent_window_id                 TEXT,
    source_url                       TEXT NOT NULL,
    license                          TEXT NOT NULL DEFAULT 'public_domain_jp_gov'
);
"""

_SCHEMA_REASONING_CHAIN = """
CREATE TABLE IF NOT EXISTS am_legal_reasoning_chain (
    chain_id                     TEXT PRIMARY KEY,
    topic_id                     TEXT NOT NULL,
    topic_label                  TEXT NOT NULL,
    tax_category                 TEXT NOT NULL,
    premise_law_article_ids      TEXT NOT NULL DEFAULT '[]',
    premise_tsutatsu_ids         TEXT NOT NULL DEFAULT '[]',
    minor_premise_judgment_ids   TEXT NOT NULL DEFAULT '[]',
    conclusion_text              TEXT NOT NULL,
    confidence                   REAL NOT NULL DEFAULT 0.5,
    opposing_view_text           TEXT,
    citations                    TEXT NOT NULL DEFAULT '{}',
    computed_by_model            TEXT NOT NULL DEFAULT 'rule_engine_v1',
    computed_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# A synthetic 法人 (matches the operator's actual T-number for parity with
# fixtures elsewhere in the repo: T8010001213708 → houjin_bangou
# 8010001213708, Bookyou株式会社). Used as the consistent test subject.
TEST_HOUJIN_BANGOU = "8010001213708"
TEST_HOUJIN_NAME = "Bookyou株式会社"
TEST_HOUJIN_ADDRESS = "東京都文京区小日向2-22-1"
TEST_HOUJIN_REPRESENTATIVE = "梅田 茂利"


def seed_journey_db(db_path: Path, *, templates: list[dict[str, Any]]) -> None:
    """Build the per-journey autonomath.db fixture.

    ``templates`` is a list of artifact-template seed dicts (segment +
    artifact_type + sections + placeholders). The placeholder mapping
    table is seeded with all the canonical placeholders referenced by
    the templates so the agent can resolve every one of them.
    """

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            _SCHEMA_ARTIFACT_TEMPLATES
            + _SCHEMA_PLACEHOLDER_MAPPING
            + _SCHEMA_ENTITIES
            + _SCHEMA_PORTFOLIO
            + _SCHEMA_WINDOW_DIRECTORY
            + _SCHEMA_REASONING_CHAIN
        )
        for tpl in templates:
            conn.execute(
                """
                INSERT INTO am_artifact_templates (
                    segment, artifact_type, artifact_name_ja,
                    authority, sensitive_act,
                    structure_jsonb, placeholders_jsonb,
                    mcp_query_bindings_jsonb
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tpl["segment"],
                    tpl["artifact_type"],
                    tpl["artifact_name_ja"],
                    tpl["authority"],
                    tpl["sensitive_act"],
                    json.dumps(tpl["structure"], ensure_ascii=False),
                    json.dumps(tpl["placeholders"], ensure_ascii=False),
                    json.dumps(tpl.get("mcp_query_bindings", {}), ensure_ascii=False),
                ),
            )

        # Seed canonical placeholder mapping rows for every placeholder
        # referenced by any template (deduped by name).
        seen: set[str] = set()
        for tpl in templates:
            for ph in tpl["placeholders"]:
                name = f"{{{{{ph['key']}}}}}"
                if name in seen:
                    continue
                seen.add(name)
                mapping = _placeholder_mapping_row(ph)
                conn.execute(
                    """
                    INSERT INTO am_placeholder_mapping (
                        placeholder_name, mcp_tool_name, args_template,
                        output_path, fallback_value, value_kind,
                        description, is_sensitive, license
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    mapping,
                )

        # Seed one synthetic 法人.
        canonical_id = f"houjin:{TEST_HOUJIN_BANGOU}"
        conn.execute(
            "INSERT INTO am_entities (canonical_id, record_kind, display_name)"
            " VALUES (?, 'corporate_entity', ?)",
            (canonical_id, TEST_HOUJIN_NAME),
        )
        for field_name, value in (
            ("corp.name", TEST_HOUJIN_NAME),
            ("corp.registered_address", TEST_HOUJIN_ADDRESS),
            ("corp.representative", TEST_HOUJIN_REPRESENTATIVE),
        ):
            conn.execute(
                "INSERT INTO am_entity_facts (entity_id, field_name, value_text) VALUES (?, ?, ?)",
                (canonical_id, field_name, value),
            )

        # One portfolio row.
        conn.execute(
            """
            INSERT INTO am_houjin_program_portfolio (
                houjin_bangou, program_id, applicability_score,
                score_industry, score_size, score_region,
                score_sector, score_target_form,
                applied_status, deadline, deadline_kind, priority_rank
            )
            VALUES (?, 'shoukibo-jigyousha-shien', 0.92,
                    0.95, 0.90, 0.88, 0.93, 0.91,
                    'unknown', '2026-08-31', 'application', 1)
            """,
            (TEST_HOUJIN_BANGOU,),
        )

        # Two window directory rows (法務局 = legal_affairs_bureau + tax_office).
        conn.execute(
            """
            INSERT INTO am_window_directory (
                window_id, jurisdiction_kind, name,
                postal_address, tel, url,
                jurisdiction_houjin_filter_regex,
                jurisdiction_region_code, source_url
            )
            VALUES ('LAB-13-FUMINKAWA', 'legal_affairs_bureau', '東京法務局 文京出張所',
                    '東京都文京区小日向', '03-0000-0000',
                    'https://houmukyoku.moj.go.jp/tokyo/',
                    '東京都文京区', '13105',
                    'https://houmukyoku.moj.go.jp/tokyo/')
            """
        )
        conn.execute(
            """
            INSERT INTO am_window_directory (
                window_id, jurisdiction_kind, name,
                postal_address, tel, url,
                jurisdiction_houjin_filter_regex,
                jurisdiction_region_code, source_url
            )
            VALUES ('TAX-13-FUMINKAWA', 'tax_office', '本郷税務署',
                    '東京都文京区本郷4-22-13', '03-3814-6111',
                    'https://www.nta.go.jp/about/organization/tokyo/location/',
                    '東京都文京区', '13105',
                    'https://www.nta.go.jp/about/organization/tokyo/location/')
            """
        )

        # One reasoning chain (for scenario 2 walk_reasoning_chain).
        conn.execute(
            """
            INSERT INTO am_legal_reasoning_chain (
                chain_id, topic_id, topic_label, tax_category,
                premise_law_article_ids, premise_tsutatsu_ids,
                minor_premise_judgment_ids, conclusion_text,
                confidence, opposing_view_text, citations
            )
            VALUES (
                'LRC-1a2b3c4d5e', 'corporate_tax:kansa_chosho',
                '監査調書の作成義務', 'corporate_tax',
                '["law:商法193の2"]', '["tsutatsu:cpa_001"]',
                '["judgment:NONE"]',
                '監査調書は監査基準委員会報告書230に従い、監査の各段階で十分かつ適切な記録を残すこと。',
                0.92, '監査調書作成義務に異論なし', '{}'
            )
            """
        )

        conn.commit()
    finally:
        conn.close()


def _placeholder_mapping_row(ph: dict[str, Any]) -> tuple[Any, ...]:
    """Build the am_placeholder_mapping row for a template placeholder.

    - source=mcp  → uses the placeholder's mcp_query_spec.
    - source=session → uses ``context`` synthetic tool (value already in context).
    - source=computed → uses ``computed`` synthetic tool.
    """

    key = ph["key"]
    name = f"{{{{{key}}}}}"
    description = ph.get("description") or key
    value_kind = ph.get("type", "text")
    source = ph.get("source", "session")
    if source == "mcp" and ph.get("mcp_query_spec"):
        spec = ph["mcp_query_spec"]
        tool_name = spec["tool"]
        # Convert spec args ({{HOUJIN_BANGOU}} style) to {token} substitution
        # form (the n9 resolver expects {foo} not {{foo}}).
        args_template = json.dumps(spec.get("args", {}), ensure_ascii=False)
        # The args_template syntax in n9 is {token} — rewrite any
        # ``{{TOKEN}}`` braces (which is how templates reference upstream
        # context) into ``{token_lowercase}``.
        args_template = re.sub(
            r"\{\{([A-Z][A-Z0-9_]*)\}\}",
            lambda m: "{" + m.group(1).lower() + "}",
            args_template,
        )
        output_path = f"primary_result.{spec.get('args', {}).get('field', 'value')}"
        is_sensitive = 0
    elif source == "computed":
        tool_name = "computed"
        args_template = '{"compute": "today_iso"}'
        output_path = "$"
        is_sensitive = 0
    else:
        tool_name = "context"
        # Pass the key lowercased so the agent's context dict carries
        # the same name.
        args_template = json.dumps({key: "{" + key.lower() + "}"}, ensure_ascii=False)
        output_path = f"${key}"
        is_sensitive = 0

    return (
        name,
        tool_name,
        args_template,
        output_path,
        ph.get("fallback_value"),
        value_kind,
        description,
        is_sensitive,
        "jpcite-scaffold-cc0",
    )


# --------------------------------------------------------------------------- #
# Journey Agent — records every MCP call into a ledger
# --------------------------------------------------------------------------- #


@dataclass
class JourneyCall:
    """One MCP call entry on the journey ledger."""

    tool_name: str
    args: dict[str, Any]
    cost_jpy: int = 3
    result_summary: str = ""


@dataclass
class JourneyLedger:
    """Append-only ledger of MCP calls in a journey run."""

    calls: list[JourneyCall] = field(default_factory=list)

    def record(self, tool_name: str, args: dict[str, Any], result_summary: str = "") -> None:
        self.calls.append(
            JourneyCall(tool_name=tool_name, args=dict(args), result_summary=result_summary)
        )

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def total_cost_jpy(self) -> int:
        return sum(c.cost_jpy for c in self.calls)

    def tools_called(self) -> list[str]:
        return [c.tool_name for c in self.calls]


# --------------------------------------------------------------------------- #
# Synthetic mcp_tool registry — maps mcp_tool_name → callable invoking the
# real moat_lane_tools function (or a tiny shim for synthetic tools).
# --------------------------------------------------------------------------- #


def build_mcp_registry() -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    """Lazy import of the moat-lane tools so the seed step does not pull the
    full jpintel_mcp tree if the schemas are still being built.

    All real tools below are pure-Python read-only readers — invoking them
    here does not depend on a running uvicorn server.
    """

    from jpintel_mcp.mcp.moat_lane_tools.moat_n1_artifact import (
        get_artifact_template,
        list_artifact_templates,
    )
    from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import get_houjin_portfolio
    from jpintel_mcp.mcp.moat_lane_tools.moat_n3_reasoning import walk_reasoning_chain
    from jpintel_mcp.mcp.moat_lane_tools.moat_n4_window import find_filing_window
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    def _wrap_houjin_360(args: dict[str, Any]) -> dict[str, Any]:
        # The production get_houjin_360_am surface is broader than our test
        # needs; for the e2e simulation we satisfy the contract by reading
        # the synthetic am_entity_facts rows the journey fixture seeded.
        import os
        import sqlite3 as _sql

        db_path = os.environ.get("JPCITE_AUTONOMATH_DB_PATH") or os.environ.get(
            "AUTONOMATH_DB_PATH"
        )
        if not db_path:
            return {"primary_result": {"status": "empty", "rationale": "DB path missing"}}
        houjin_bangou = args.get("houjin_bangou")
        field_req = args.get("field", "name")
        canonical_id = f"houjin:{houjin_bangou}"
        # Field aliases — templates reference "name", "address", "representative".
        field_aliases = {
            "name": "corp.name",
            "address": "corp.registered_address",
            "representative": "corp.representative",
        }
        target_field = field_aliases.get(field_req, f"corp.{field_req}")
        conn = _sql.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value_text FROM am_entity_facts WHERE entity_id=? AND field_name=?",
                (canonical_id, target_field),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return {"primary_result": {"status": "empty"}, field_req: None}
        return {"primary_result": {field_req: row[0]}, field_req: row[0]}

    return {
        "get_artifact_template": lambda args: get_artifact_template(**args),
        "list_artifact_templates": lambda args: list_artifact_templates(**args),
        "get_houjin_portfolio": lambda args: get_houjin_portfolio(**args),
        "walk_reasoning_chain": lambda args: walk_reasoning_chain(**args),
        "find_filing_window": lambda args: find_filing_window(**args),
        "resolve_placeholder": lambda args: resolve_placeholder(**args),
        "get_houjin_360_am": _wrap_houjin_360,
    }


# --------------------------------------------------------------------------- #
# Draft assembly — render a template with a resolved context dict and check
# that all placeholders {{...}} have been substituted.
# --------------------------------------------------------------------------- #

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def render_artifact(structure: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    """Render a template structure into a flat draft string + return any
    unresolved placeholders. The structure JSON has shape::

        {
            "sections": [
                {"id": "...", "title": "...", "paragraphs": ["...{{FOO}}..."]}
            ]
        }
    """

    lines: list[str] = []
    for section in structure.get("sections", []):
        lines.append(f"# {section.get('title', section.get('id'))}")
        for paragraph in section.get("paragraphs", []):
            rendered = _PLACEHOLDER_RE.sub(
                lambda m: str(context.get(m.group(1), m.group(0))), paragraph
            )
            lines.append(rendered)
        lines.append("")
    draft = "\n".join(lines).strip() + "\n"
    unresolved = sorted(set(_PLACEHOLDER_RE.findall(draft)))
    return draft, unresolved


def collect_template_placeholders(structure: dict[str, Any]) -> list[str]:
    """Return the sorted unique list of placeholder names ({{X}}) found in
    every paragraph of the template structure.
    """

    seen: set[str] = set()
    for section in structure.get("sections", []):
        for paragraph in section.get("paragraphs", []):
            seen.update(_PLACEHOLDER_RE.findall(paragraph))
    return sorted(seen)


__all__ = [
    "JourneyAgent",
    "JourneyCall",
    "JourneyLedger",
    "TEST_HOUJIN_ADDRESS",
    "TEST_HOUJIN_BANGOU",
    "TEST_HOUJIN_NAME",
    "TEST_HOUJIN_REPRESENTATIVE",
    "build_mcp_registry",
    "collect_template_placeholders",
    "render_artifact",
    "seed_journey_db",
]


# --------------------------------------------------------------------------- #
# JourneyAgent — wraps the registry + ledger into a single agent loop.
# --------------------------------------------------------------------------- #


@dataclass
class JourneyAgent:
    """Stateful simulation of an MCP-driven agent.

    The agent exposes ``invoke(tool, args)`` which:

    * looks the tool up in the registry,
    * calls the underlying Python function,
    * records the call in the ledger (¥3 each),
    * returns the canonical envelope dict.
    """

    registry: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]
    ledger: JourneyLedger = field(default_factory=JourneyLedger)

    def invoke(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self.registry:
            raise KeyError(
                f"JourneyAgent.invoke: unknown tool {tool_name!r}; "
                f"registry has {sorted(self.registry)}"
            )
        result = self.registry[tool_name](args)
        # Light summary string for the ledger — first 80 chars of repr.
        summary = repr(result)[:80]
        self.ledger.record(tool_name, args, result_summary=summary)
        return result
