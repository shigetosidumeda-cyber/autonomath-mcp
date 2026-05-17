-- target_db: autonomath
-- migration: wave24_195_am_case_extracted_facts
-- generated_at: 2026-05-17
-- author: Lane M2 case extraction (jpcite RC1 moat)
-- spec: docs/_internal/AWS_MOAT_LANE_M2_CASE_EXTRACT_2026_05_17.md
--
-- Purpose
-- -------
-- AWS moat Lane M2 lands a structured-facts side-table over the existing
-- 201,845-row jpi_adoption_records corpus + 2,286-stub case_studies surface.
-- The base tables hold raw text (program_name_raw / project_title /
-- company_name_raw / industry_raw); this migration adds the canonical
-- destination for the extraction pipeline's structured output.
--
-- Why a new table (not an ALTER on jpi_adoption_records)
-- ------------------------------------------------------
--   1. jpi_adoption_records is the canonical immutable mirror of upstream
--      公開済 PDF lists (smrj.go.jp / METI). Adding extracted columns
--      directly would conflate (a) what the upstream said vs (b) what we
--      derived. The Dim O verified-fact principle demands separation.
--   2. Each extracted fact carries its own confidence + extraction_method
--      + source_signal trace. ALTERing the base table cannot host those
--      provenance columns without bloating every row.
--   3. The extraction pipeline is rerun-able: when the regex/dict/NER
--      rules improve we want to drop and re-emit facts atomically per
--      source row without touching the base record.
--
-- Schema
-- ------
-- * case_id            — source row identifier. For jpi_adoption_records
--                        rows this is "adoption:" || id. For case_studies
--                        rows (when populated, currently 0) this is
--                        "case:" || case_id. The prefix lets one table
--                        host both source kinds with no FK ambiguity.
-- * source_kind        — 'adoption' | 'case_study'. CHECK enforced.
-- * amount_yen         — extracted 補助金額 in yen. NULL when no amount
--                        signal was found (most adoption rows). Integer
--                        because every upstream amount lands in 円
--                        granularity.
-- * fiscal_year        — extracted 採択年度 (Western year, e.g. 2023).
--                        Wareki and 令和N年 are converted at extraction
--                        time to keep this column homogeneous.
-- * industry_jsic      — JSIC major (1-letter A-T) when derivable from
--                        industry_raw / company_name_raw / project_title.
--                        NULL when ambiguous — never guess for the sake
--                        of filling.
-- * prefecture         — copied from source row (already 99.3% populated
--                        upstream). Stored here so the facts table is
--                        self-contained for cohort joins.
-- * success_signals    — JSON array of detected positive-outcome tokens
--                        ("新商品" / "販路拡大" / "DX" / "省人化" etc.).
--                        Empty array (not NULL) when no signal matched.
-- * failure_signals    — JSON array of detected risk/withdrawal tokens
--                        ("辞退" / "取消" / "返還" / "減額"). Used by
--                        the cohort matcher to flag historically thin
--                        outcomes. Empty array (not NULL) when none.
-- * related_program_ids— JSON array of program_id matches inferred from
--                        program_name_raw via the existing program-name
--                        → program_id alias index. Empty array (not NULL)
--                        when no alias hit.
-- * extraction_method  — 'regex' | 'dict' | 'ner' | 'composite'. Records
--                        which extraction pass produced each fact row;
--                        re-runs can incrementally upgrade rows.
-- * confidence         — 0.0..1.0 per-row confidence. Composite of
--                        per-field confidences from the extraction
--                        script. The cohort matcher filters rows with
--                        confidence < 0.5 by default.
-- * extracted_at       — ISO-8601 UTC. NOT NULL.
--
-- Indexes
-- -------
-- * idx_amcef_case        — (case_id) for source-row joins.
-- * idx_amcef_amount_pref — (prefecture, amount_yen) for cohort matcher
--                           "industry × prefecture × amount band" queries.
-- * idx_amcef_jsic_year   — (industry_jsic, fiscal_year) for vertical
--                           cohort cuts.
--
-- Idempotency
-- -----------
-- CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS. The companion
-- ingest script (extract_case_facts_2026_05_17.py) uses INSERT OR REPLACE
-- on (case_id) so re-runs overwrite prior extraction passes without
-- duplicating rows.
--
-- Cost posture
-- ------------
-- Pure SQLite DDL. Zero LLM, zero AWS side-effect. Population happens via
-- the M2 pipeline driver; this migration only creates the destination.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_case_extracted_facts (
    case_id              TEXT PRIMARY KEY,
    source_kind          TEXT NOT NULL CHECK (source_kind IN ('adoption','case_study')),
    amount_yen           INTEGER,
    fiscal_year          INTEGER,
    industry_jsic        TEXT,
    prefecture           TEXT,
    success_signals      TEXT NOT NULL DEFAULT '[]',
    failure_signals      TEXT NOT NULL DEFAULT '[]',
    related_program_ids  TEXT NOT NULL DEFAULT '[]',
    extraction_method    TEXT NOT NULL CHECK (extraction_method IN ('regex','dict','ner','composite')),
    confidence           REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extracted_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_amcef_case
    ON am_case_extracted_facts(case_id);

CREATE INDEX IF NOT EXISTS idx_amcef_amount_pref
    ON am_case_extracted_facts(prefecture, amount_yen);

CREATE INDEX IF NOT EXISTS idx_amcef_jsic_year
    ON am_case_extracted_facts(industry_jsic, fiscal_year);
