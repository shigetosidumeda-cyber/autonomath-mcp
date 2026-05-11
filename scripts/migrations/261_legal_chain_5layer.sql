-- target_db: autonomath
-- migration: 261_legal_chain_5layer
-- generated_at: 2026-05-12
-- author: Wave 43.2.2 — Dim B legal_chain 5-layer 因果関係追跡
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- One-call causal chain that links a 制度 (program_id) backwards through
-- the five layers of how an Japanese subsidy / tax / loan / certification
-- comes into legal existence. Surfaces are pulled in parallel today across
-- 5 different tables / sources; this layer materializes the chain so a
-- customer LLM can render "this 制度 traces to FY budget → law article →
-- cabinet order → enforcement event → similar case" in one ¥3 call.
--
-- 5 Layers (anchor = program)
-- ---------------------------
--   1. budget       — 予算成立 (該当年度の歳出予算 / 補正予算 / 概算要求)
--   2. law          — 該当法令 article (法律 / 政令 / 省令 / 通達 / 告示)
--   3. cabinet      — 関連 閣議決定 / 内閣府令 / 政令 (cabinet order)
--   4. enforcement  — 行政処分 history (関連事業者 / 関連処分歴)
--   5. case         — 該当採択事例 (similar 採択 within same 制度 family)
--
-- Each layer carries:
--   * evidence_url       — primary first-party government URL (REQUIRED).
--                           Aggregators (noukaweb / hojyokin-portal / news
--                           consolidators) are BANNED by ETL discipline.
--   * layer_data_json    — verbatim per-layer payload (≤ 4KB, JSON object).
--                           NEVER LLM rewording; values are source quotes
--                           + minimal structural metadata (date / amount /
--                           ref id) only.
--   * next_layer_link    — optional pointer to the next layer's chain_id
--                           or composite key so a downstream traverser can
--                           step layer1 → layer5 without re-querying.
--
-- License posture
-- ---------------
-- All 5 layers source from `gov_standard` / `cc_by_4.0` / `public_domain`
-- (NTA / e-Gov / 内閣府 / 各省庁 一次資料 only). Row-level `license`
-- column captures the source policy; redistribute_ok flag gates the
-- v_legal_chain_public view so downstream artifacts can filter on it.
--
-- ¥3/req billing posture (3 unit for heavy chain query)
-- -----------------------------------------------------
-- Read path is ¥3/req × 3 unit (税込 ¥9.90) under
-- `/v1/legal/chain/{program_id}`. The 3-unit multiplier is justified by:
--   * Cross-table fan-out (5 separate SELECTs × per-layer caps).
--   * No FTS5 narrowing — must full-scan 5 surfaces per call.
--   * Materialized chain row writes (when ETL pre-warms) cost write I/O.
-- NO LLM call inside the read or write path — pure SQLite + Python.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_legal_chain (
    chain_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    anchor_program_id    TEXT NOT NULL,                  -- canonical jpintel programs.unified_id
    layer                INTEGER NOT NULL,               -- 1..5
    layer_name           TEXT NOT NULL,                  -- 'budget' | 'law' | 'cabinet' | 'enforcement' | 'case'
    evidence_url         TEXT NOT NULL,                  -- primary 一次資料 URL (NEVER aggregator)
    evidence_host        TEXT NOT NULL,                  -- denormalized host for freshness audit
    layer_data_json      TEXT NOT NULL DEFAULT '{}',     -- verbatim per-layer payload (≤ 4KB)
    layer_summary        TEXT,                           -- ≤ 200-char headline; verbatim source quote
    effective_date       TEXT,                           -- ISO 8601 layer-specific reference date
    next_layer_link      TEXT,                           -- optional pointer to next layer chain_id or composite key
    license              TEXT NOT NULL DEFAULT 'gov_standard',
    redistribute_ok      INTEGER NOT NULL DEFAULT 1 CHECK (redistribute_ok IN (0, 1)),
    ingested_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_verified        TEXT,
    content_hash         TEXT,                           -- sha256(evidence_url|layer_data_json) for dedup
    notes                TEXT,
    CONSTRAINT ck_legal_chain_layer CHECK (layer BETWEEN 1 AND 5),
    CONSTRAINT ck_legal_chain_layer_name CHECK (layer_name IN (
        'budget','law','cabinet','enforcement','case'
    )),
    CONSTRAINT ck_legal_chain_evidence_url CHECK (
        evidence_url LIKE 'http://%' OR evidence_url LIKE 'https://%'
    ),
    -- Layer ↔ layer_name 同期 (1=budget, 2=law, 3=cabinet, 4=enforcement, 5=case).
    CONSTRAINT ck_legal_chain_layer_pair CHECK (
        (layer = 1 AND layer_name = 'budget')
        OR (layer = 2 AND layer_name = 'law')
        OR (layer = 3 AND layer_name = 'cabinet')
        OR (layer = 4 AND layer_name = 'enforcement')
        OR (layer = 5 AND layer_name = 'case')
    )
);

CREATE INDEX IF NOT EXISTS idx_legal_chain_anchor
    ON am_legal_chain(anchor_program_id, layer);

CREATE INDEX IF NOT EXISTS idx_legal_chain_layer_date
    ON am_legal_chain(layer, effective_date DESC);

CREATE INDEX IF NOT EXISTS idx_legal_chain_host
    ON am_legal_chain(evidence_host, ingested_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_legal_chain_anchor_layer_url
    ON am_legal_chain(anchor_program_id, layer, evidence_url);

-- Public-surface view: redistribute_ok=1 only.
DROP VIEW IF EXISTS v_legal_chain_public;
CREATE VIEW v_legal_chain_public AS
SELECT
    chain_id, anchor_program_id, layer, layer_name,
    evidence_url, evidence_host, layer_data_json,
    layer_summary, effective_date, next_layer_link,
    license, ingested_at, last_verified
FROM am_legal_chain
WHERE redistribute_ok = 1;

-- Run log: tracks each fill_legal_chain_2x.py run.
CREATE TABLE IF NOT EXISTS am_legal_chain_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    anchor_count    INTEGER NOT NULL DEFAULT 0,
    rows_added      INTEGER NOT NULL DEFAULT 0,
    rows_updated    INTEGER NOT NULL DEFAULT 0,
    layers_filled   TEXT,                                -- comma-separated layer subset
    errors_count    INTEGER NOT NULL DEFAULT 0,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_legal_chain_run_log_started
    ON am_legal_chain_run_log(started_at DESC);

COMMIT;
