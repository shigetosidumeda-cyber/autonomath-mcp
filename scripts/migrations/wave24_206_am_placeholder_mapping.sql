-- target_db: autonomath
-- migration: wave24_206_am_placeholder_mapping
-- generated_at: 2026-05-17
-- author: Niche Moat Lane N9 — placeholder → MCP query resolver
-- idempotent: every CREATE uses IF NOT EXISTS; no DML beyond optional bulk
--             load from data/placeholder_mappings.json (handled by
--             scripts/etl/load_placeholder_mappings_2026_05_17.py, kept
--             out of this DDL file so re-runs are pure CREATE IF NOT EXISTS).
--
-- Purpose
-- -------
-- Lane N1 (am_artifact_templates) ships scaffolds whose body contains
-- canonical placeholders (e.g. ``{{HOUJIN_NAME}}``, ``{{TAX_RULE_RATE}}``,
-- ``{{INVOICE_REGISTRANT_T}}``). Resolving each placeholder deterministically
-- requires a binding to the canonical MCP tool that can fetch the value,
-- the args_template to call it with, and the JSONPath-ish output_path to
-- extract from the response. ``am_placeholder_mapping`` is that binding.
--
-- 1st-pass scope
-- --------------
-- ~207 canonical placeholders covering:
--   * 法人 / 会社情報 (HOUJIN_NAME, HOUJIN_BANGOU, ADDRESS, REPRESENTATIVE …)
--   * 制度 / 助成 (PROGRAM_ID, PROGRAM_TITLE, DEADLINE, AMOUNT_MAX, …)
--   * 税制 (TAX_RULE_RATE, TAX_BASE_AMOUNT, KOJO_RIGHT, …)
--   * 法令 (LEGAL_BASIS_ARTICLE, LEGAL_BASIS_TITLE, LAW_BODY_EN, …)
--   * 行政処分 (ENFORCEMENT_REASON, ENFORCEMENT_AMOUNT, …)
--   * 適格 (INVOICE_REGISTRANT_T, INVOICE_VALID_FROM, …)
--   * 採択 (ADOPTION_YEAR, ADOPTION_COUNT, …)
--   * 操作系 (CURRENT_DATE, OPERATOR_NAME, JST_NOW, …)
--
-- target_db = autonomath
-- ----------------------
-- Co-located with am_artifact_templates (lane N1) and 78 jpi_* / am_* tables.
-- entrypoint.sh §4 auto-applies any ``-- target_db: autonomath`` migration
-- on boot — this DDL re-creates the table idempotently if production
-- volume ever loses the schema.
--
-- Idempotency contract
-- --------------------
--   * ``CREATE TABLE IF NOT EXISTS`` — existing rows preserved on re-apply.
--   * All indexes are ``CREATE INDEX IF NOT EXISTS``.
--   * Auxiliary view is ``CREATE VIEW IF NOT EXISTS``.
--   * No DML — bulk seed is handled by a separate loader (see header).
--
-- LLM call: 0. Pure SQLite DDL.
--
-- License posture
-- ---------------
-- Mapping table schema is jpcite-scaffold-cc0. Individual rows carry their
-- own ``license`` column reflecting the upstream data source of the
-- placeholder's resolved value (pdl_v1.0 for 法人番号公表サイト, cc_by_4.0
-- for e-Gov, gov_standard for 国税庁通達, jpcite-scaffold-cc0 for purely
-- structural / context / computed placeholders).
--
-- Field semantics
-- ---------------
-- placeholder_id        INTEGER PK AUTOINCREMENT
-- placeholder_name      TEXT  — canonical, with braces, e.g. '{{HOUJIN_NAME}}'
-- source_template_ids   TEXT  — comma-separated artifact_template ids that
--                               surface this placeholder (nullable, hint only).
-- mcp_tool_name         TEXT  — canonical MCP tool slug (e.g.
--                               'get_houjin_360_am'). Special values:
--                                 'context'  — value already supplied by
--                                              caller in context_dict_json.
--                                 'computed' — deterministic compute
--                                              (CURRENT_DATE / JST_NOW / ...).
-- args_template         TEXT  — JSON-encoded args template with {tokens}
--                               that are substituted from context_dict_json.
-- output_path           TEXT  — JSONPath-lite for extracting the resolved
--                               value from the MCP tool response. '$' means
--                               the entire response IS the value.
-- fallback_value        TEXT  — human-readable fallback string when the
--                               resolved value is unavailable.
-- value_kind            TEXT  — text / yen / date / boolean / list / json /
--                               enum / wareki / integer / percentage / url
-- description           TEXT  — operator-facing description (JP)
-- is_sensitive          INT   — 0 / 1; sensitive placeholders carry the
--                               §-aware disclaimer envelope upstream.
-- license               TEXT  — upstream-data license tag for the resolved
--                               value (pdl_v1.0 / cc_by_4.0 / gov_standard
--                               / jpcite-scaffold-cc0 / public_domain_jp_gov)
-- created_at            TEXT  — ISO 8601 UTC
-- updated_at            TEXT  — ISO 8601 UTC

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_placeholder_mapping — canonical placeholder → MCP call schema
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_placeholder_mapping (
    placeholder_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    placeholder_name     TEXT NOT NULL UNIQUE,
    source_template_ids  TEXT,
    mcp_tool_name        TEXT NOT NULL,
    args_template        TEXT NOT NULL DEFAULT '{}',
    output_path          TEXT NOT NULL DEFAULT '$',
    fallback_value       TEXT,
    value_kind           TEXT NOT NULL DEFAULT 'text'
                          CHECK (value_kind IN (
                            'text',
                            'yen',
                            'date',
                            'boolean',
                            'list',
                            'json',
                            'enum',
                            'wareki',
                            'integer',
                            'percentage',
                            'url'
                          )),
    description          TEXT NOT NULL,
    is_sensitive         INTEGER NOT NULL DEFAULT 0
                          CHECK (is_sensitive IN (0, 1)),
    license              TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0'
                          CHECK (license IN (
                            'jpcite-scaffold-cc0',
                            'pdl_v1.0',
                            'cc_by_4.0',
                            'gov_standard',
                            'public_domain',
                            'public_domain_jp_gov',
                            'proprietary',
                            'unknown'
                          )),
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS ix_am_placeholder_tool
    ON am_placeholder_mapping(mcp_tool_name);

CREATE INDEX IF NOT EXISTS ix_am_placeholder_sensitive
    ON am_placeholder_mapping(is_sensitive, placeholder_name);

CREATE INDEX IF NOT EXISTS ix_am_placeholder_value_kind
    ON am_placeholder_mapping(value_kind);

-- Convenience view: per-tool aggregate (operator dashboards / audit).
CREATE VIEW IF NOT EXISTS v_am_placeholder_by_tool AS
    SELECT
        mcp_tool_name,
        COUNT(*) AS placeholder_count,
        SUM(is_sensitive) AS sensitive_count,
        MIN(created_at) AS earliest_created,
        MAX(updated_at) AS latest_updated
      FROM am_placeholder_mapping
     GROUP BY mcp_tool_name;
