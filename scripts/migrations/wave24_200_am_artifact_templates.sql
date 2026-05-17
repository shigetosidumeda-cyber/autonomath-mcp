-- target_db: autonomath
-- Lane N1 — 実務成果物テンプレート bank (50 templates, 5 士業 × 10 種類).
--
-- Stores machine-readable artifact-template skeletons that let an agent
-- (Opus 4.7 等) retrieve a template via MCP and fill placeholders by
-- calling other jpcite MCP tools. The goal is to compress an agent's
-- "draft a 36協定 / 補助金申請書 / 就業規則" turn-loop from N calls of
-- generic LLM text generation into a single deterministic skeleton
-- pull + a small number of MCP bindings to fact-anchored sources.
--
-- Honest framing
-- --------------
-- These templates are **scaffolds**, not legally certified deliverables.
-- Every record carries:
--   - `is_scaffold_only = 1` (machine-readable disclaimer)
--   - `requires_professional_review = 1` (must be reviewed by the
--     corresponding 士業 before submission to 役所 / 労基署 / 法務局 /
--     税務署 等)
--   - `authority` reference (e.g. 労基法 §89 for 就業規則 / 商業登記法
--     §47 for 会社設立登記)
--   - structure_jsonb listing sections / paragraphs / clauses
--   - placeholders_jsonb (typed placeholders with MCP binding spec)
--   - mcp_query_bindings_jsonb (placeholder → MCP tool name + args)
--
-- The 50 segment × artifact_type rows seeded here are catalog records;
-- the actual structure / placeholder / binding payload is hydrated from
-- ``data/artifact_templates/{segment}/{artifact_type}.yaml`` at boot via
-- ``scripts/cron/load_artifact_templates_2026_05_17.py`` (idempotent
-- INSERT OR REPLACE).
--
-- Sensitive surfaces
-- ------------------
-- Each segment maps to a regulated profession:
--   - 税理士: 税理士法 §52 (税理士業務独占)
--   - 会計士: 公認会計士法 §47条の2 + §1 (監査独占)
--   - 行政書士: 行政書士法 §1 + §19 (官公署提出書類)
--   - 司法書士: 司法書士法 §3 + §73 (登記独占)
--   - 社労士: 社会保険労務士法 §27 (労務管理書類)
--
-- The agent-facing MCP tools (`get_artifact_template` /
-- `list_artifact_templates`) MUST attach a §-aware disclaimer envelope to
-- every response. The MCP tool layer enforces this — the table here just
-- carries the structure.
--
-- Idempotent (CREATE IF NOT EXISTS only); safe to re-run on every boot.

CREATE TABLE IF NOT EXISTS am_artifact_templates (
    template_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    segment                      TEXT NOT NULL,        -- 税理士 / 会計士 / 行政書士 / 司法書士 / 社労士
    artifact_type                TEXT NOT NULL,        -- e.g. 'gessji_shiwake' / '36_kyotei' / 'shuugyou_kisoku'
    artifact_name_ja             TEXT NOT NULL,        -- 表示用 日本語名 (e.g. '就業規則')
    version                      TEXT NOT NULL DEFAULT 'v1',
    authority                    TEXT NOT NULL,        -- 根拠法令 (e.g. '労基法 §89')
    sensitive_act                TEXT NOT NULL,        -- 規制業法 (e.g. '社労士法 §27')
    is_scaffold_only             INTEGER NOT NULL DEFAULT 1 CHECK (is_scaffold_only IN (0, 1)),
    requires_professional_review INTEGER NOT NULL DEFAULT 1 CHECK (requires_professional_review IN (0, 1)),
    uses_llm                     INTEGER NOT NULL DEFAULT 0 CHECK (uses_llm IN (0, 1)),
    quality_grade                TEXT NOT NULL DEFAULT 'draft',  -- draft / reviewed / certified
    structure_jsonb              TEXT NOT NULL,        -- JSON: { "sections": [ {id, title, paragraphs: [...]} ] }
    placeholders_jsonb           TEXT NOT NULL,        -- JSON: [ {key, type, required, source, mcp_query_spec} ]
    mcp_query_bindings_jsonb     TEXT NOT NULL,        -- JSON: { placeholder_key: { tool, args_spec } }
    license                      TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
    notes                        TEXT,
    created_at                   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (segment, artifact_type, version)
);

CREATE INDEX IF NOT EXISTS ix_am_artifact_templates_segment
    ON am_artifact_templates(segment);

CREATE INDEX IF NOT EXISTS ix_am_artifact_templates_type
    ON am_artifact_templates(artifact_type);

CREATE INDEX IF NOT EXISTS ix_am_artifact_templates_segment_type
    ON am_artifact_templates(segment, artifact_type);

-- Convenience view: latest version per (segment, artifact_type).
CREATE VIEW IF NOT EXISTS v_am_artifact_templates_latest AS
    SELECT t.*
      FROM am_artifact_templates t
      JOIN (
            SELECT segment, artifact_type, MAX(version) AS max_version
              FROM am_artifact_templates
             GROUP BY segment, artifact_type
           ) m
        ON m.segment = t.segment
       AND m.artifact_type = t.artifact_type
       AND m.max_version = t.version;
