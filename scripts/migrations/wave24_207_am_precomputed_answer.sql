-- target_db: autonomath
-- migration: wave24_207_am_precomputed_answer
-- generated_at: 2026-05-17
-- author: Moat Lane P3 — 500 FAQ deterministic answer pre-population
-- idempotent: every CREATE uses IF NOT EXISTS; no DML in DDL.
--
-- Purpose
-- -------
-- Stores 500 pre-composed answers (5 cohort × 100 FAQ) produced by the
-- P2 rule-based composer (scripts/aws_credit_ops/precompute_answer_composer
-- _2026_05_17.py). The composer reads FAQ yaml seeds from
-- ``data/faq_bank/{税理士,会計士,行政書士,司法書士,中小経営者}_top100.yaml``,
-- pulls deterministic facts from autonomath.db (am_entities / am_law_reference
-- / am_source / am_authority), assembles a citation-bearing answer payload,
-- and INSERTs one row per FAQ here.
--
-- Subsequent agent reads hit ``search_precomputed_answers`` (MCP) and replay
-- the cached payload verbatim. Lifetime savings model:
--   * Naive Opus 4.7 baseline: 500 × ¥25 (one round per question) = ¥12,500
--   * jpcite serve cost: 500 × ¥3 = ¥1,500
--   * Per 1000 subsequent reads of the same 500 FAQs:
--       Opus rerun: 500 × 1000 × ¥25 = ¥12,500,000
--       jpcite replay: 500 × 1000 × ¥3 = ¥1,500,000
--       Net savings: ¥11,000,000 per 1000-read cycle.
--   * Per 1 lifetime LLM call avoided per agent read, ¥22 savings.
--
-- Honest framing
-- --------------
-- The composer is purely deterministic / rule-based. No LLM inference is
-- performed at compose time or serve time. The cached answer is a
-- citation-anchored summary, NOT a legally binding opinion. Every response
-- carries the §52/§47条の2/§72/§1/§3 disclaimer enforced at the MCP wrapper.
--
-- Schema field semantics
-- ----------------------
--   answer_id           INTEGER PK AUTOINCREMENT
--   cohort              TEXT  — 士業 cohort slug:
--                                'tax' / 'audit' / 'gyousei' / 'shihoshoshi' /
--                                'chusho_keieisha' (中小経営者)
--   faq_slug            TEXT  — deterministic question slug
--                               (e.g. 'tax_001_invoice_2wari_tokurei').
--                               Globally unique with cohort.
--   question_text       TEXT  — canonical Japanese question.
--   question_variants   TEXT  — JSON array of paraphrases (FTS material).
--   answer_text         TEXT  — composed answer body (deterministic).
--   citation_ids        TEXT  — JSON array of am_entities.canonical_id used as
--                               citation sources.
--   citation_count      INT   — len(citation_ids), denormalized for ranking.
--   citation_urls       TEXT  — JSON array of primary source URLs.
--   depth_level         INT   — 1..5; how deep the composer traversed the
--                               relation graph during composition.
--   composer_version    TEXT  — composer rule-set version (e.g. 'p2.v1').
--   composed_at         TEXT  — ISO-8601 UTC when this row was composed.
--   corpus_snapshot_id  TEXT  — for cache invalidation across snapshot bumps.
--   freshness_state     TEXT  — fresh / stale / unknown — based on
--                               max(citation source fetched_at).
--   is_scaffold_only    INT   — always 1 (mirrors lane N1 / N8 contract).
--   requires_professional_review INT — always 1.
--   uses_llm            INT   — always 0.
--   license             TEXT  — composite jpcite-scaffold-cc0 / citation
--                               provenance carried in citation_urls.
--   created_at          TEXT  — ISO-8601 UTC.
--   updated_at          TEXT  — ISO-8601 UTC.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_precomputed_answer (
    answer_id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort                        TEXT NOT NULL CHECK (cohort IN (
                                       'tax', 'audit', 'gyousei',
                                       'shihoshoshi', 'chusho_keieisha'
                                  )),
    faq_slug                      TEXT NOT NULL,
    question_text                 TEXT NOT NULL,
    question_variants             TEXT NOT NULL DEFAULT '[]',
    answer_text                   TEXT NOT NULL,
    citation_ids                  TEXT NOT NULL DEFAULT '[]',
    citation_count                INTEGER NOT NULL DEFAULT 0,
    citation_urls                 TEXT NOT NULL DEFAULT '[]',
    depth_level                   INTEGER NOT NULL DEFAULT 1
                                   CHECK (depth_level BETWEEN 1 AND 5),
    composer_version              TEXT NOT NULL DEFAULT 'p2.v1',
    composed_at                   TEXT NOT NULL DEFAULT (datetime('now')),
    corpus_snapshot_id            TEXT,
    freshness_state               TEXT NOT NULL DEFAULT 'unknown'
                                   CHECK (freshness_state IN (
                                       'fresh', 'stale', 'unknown'
                                   )),
    is_scaffold_only              INTEGER NOT NULL DEFAULT 1
                                   CHECK (is_scaffold_only IN (0, 1)),
    requires_professional_review  INTEGER NOT NULL DEFAULT 1
                                   CHECK (requires_professional_review IN (0, 1)),
    uses_llm                      INTEGER NOT NULL DEFAULT 0
                                   CHECK (uses_llm IN (0, 1)),
    license                       TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
    created_at                    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                    TEXT NOT NULL DEFAULT (datetime('now')),
    -- P2 deterministic composition extension columns (Wave 95 P2, directive
    -- 2026-05-17). Captured as direct columns when CREATE TABLE runs for
    -- the first time; otherwise added via ALTER below for existing installs.
    --
    -- question_id     : canonical FAQ id from P1 yaml (e.g. ``zeirishi_q001``).
    -- q_hash          : sha256 of (cohort + '' + question_text) hex-32.
    --                   Anchors the row across question wording edits and
    --                   provides O(1) lookup key for ``get_precomputed_answer``.
    -- answer_md       : structured markdown body (結論 / 根拠 / 通達補足 /
    --                   判例の傾向 / 実務留意点 / 関連書類 / 申請窓口 /
    --                   直近改正情報 / 免責事項).
    -- answer_xml      : same content as ``answer_md`` rendered as an XML
    --                   envelope <precomputed_answer><section name="..."/></...>
    --                   for agents that need a structured tree.
    -- sections_jsonb  : JSON array of {name, body} sections (one per
    --                   markdown section); enables partial-section access
    --                   without re-parsing markdown.
    -- composed_from   : JSON dict of {source_kind, [id_list]} the composer
    --                   walked to assemble the answer (e.g. {"law_article":
    --                   [123, 456], "reasoning_chain": ["LRC-..."], ...}).
    -- source_citations: JSON array of {kind, id, source_url, excerpt}
    --                   verbatim citation triples for the disclaimer / audit
    --                   trail. citation_count denormalizes len() for ranking.
    -- last_composed_at: ISO 8601 UTC of the most recent compose run for the
    --                   row (touched on every UPSERT). Distinct from
    --                   ``composed_at`` which captures the *first* compose.
    -- version_seq     : monotonically increasing int per (cohort, faq_slug);
    --                   bumped on every UPSERT so agents can detect drift.
    -- opus_baseline_jpy / jpcite_actual_jpy: cost-saving telemetry per row
    --                   (sourced from the P1 yaml's
    --                   ``opus_baseline_cost_estimate_jpy`` /
    --                   ``jpcite_target_cost_jpy``).
    question_id                   TEXT,
    q_hash                        TEXT,
    answer_md                     TEXT,
    answer_xml                    TEXT,
    sections_jsonb                TEXT NOT NULL DEFAULT '[]',
    composed_from                 TEXT NOT NULL DEFAULT '{}',
    source_citations              TEXT NOT NULL DEFAULT '[]',
    last_composed_at              TEXT,
    version_seq                   INTEGER NOT NULL DEFAULT 1,
    opus_baseline_jpy             INTEGER NOT NULL DEFAULT 0,
    jpcite_actual_jpy             INTEGER NOT NULL DEFAULT 3,
    UNIQUE (cohort, faq_slug)
);

-- ---------------------------------------------------------------------------
-- Idempotent ALTER guard for pre-existing am_precomputed_answer installs.
-- SQLite lacks ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``. Wrap each ALTER
-- in a CREATE-TRIGGER-style probe is too noisy here; instead we rely on the
-- entrypoint.sh §4 self-heal loop swallowing duplicate-column errors and on
-- the loader script (``scripts/aws_credit_ops/precompute_answer_composer_
-- 2026_05_17.py``) running ``PRAGMA table_info`` before insert. Re-running
-- this migration on a fresh DB hits the CREATE TABLE branch above and the
-- ALTERs become no-ops; re-running on an old DB applies the ALTERs once and
-- subsequent reruns raise a duplicate-column error that the boot loop ignores.
-- ---------------------------------------------------------------------------
ALTER TABLE am_precomputed_answer ADD COLUMN question_id     TEXT;
ALTER TABLE am_precomputed_answer ADD COLUMN q_hash          TEXT;
ALTER TABLE am_precomputed_answer ADD COLUMN answer_md       TEXT;
ALTER TABLE am_precomputed_answer ADD COLUMN answer_xml      TEXT;
ALTER TABLE am_precomputed_answer ADD COLUMN sections_jsonb  TEXT NOT NULL DEFAULT '[]';
ALTER TABLE am_precomputed_answer ADD COLUMN composed_from   TEXT NOT NULL DEFAULT '{}';
ALTER TABLE am_precomputed_answer ADD COLUMN source_citations TEXT NOT NULL DEFAULT '[]';
ALTER TABLE am_precomputed_answer ADD COLUMN last_composed_at TEXT;
ALTER TABLE am_precomputed_answer ADD COLUMN version_seq     INTEGER NOT NULL DEFAULT 1;
ALTER TABLE am_precomputed_answer ADD COLUMN opus_baseline_jpy INTEGER NOT NULL DEFAULT 0;
ALTER TABLE am_precomputed_answer ADD COLUMN jpcite_actual_jpy INTEGER NOT NULL DEFAULT 3;

CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_cohort
    ON am_precomputed_answer(cohort);

CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_freshness
    ON am_precomputed_answer(freshness_state);

CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_cite_count
    ON am_precomputed_answer(citation_count DESC);

CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_composed_at
    ON am_precomputed_answer(composed_at DESC);

-- O(1) hash lookup for ``get_precomputed_answer`` MCP tool.
CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_q_hash
    ON am_precomputed_answer(q_hash);

-- Lookup by canonical question_id (e.g. ``zeirishi_q001``) — agents that
-- already know the FAQ id skip the q_hash compute.
CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_question_id
    ON am_precomputed_answer(question_id);

-- Cohort + question_id covering index for the most common access pattern.
CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_cohort_qid
    ON am_precomputed_answer(cohort, question_id);

-- FTS5 trigram index over question_text + question_variants. The MCP tool
-- ``search_precomputed_answers`` performs MATCH against this index to find
-- the best pre-composed answer for an incoming agent query.
CREATE VIRTUAL TABLE IF NOT EXISTS am_precomputed_answer_fts USING fts5(
    answer_id UNINDEXED,
    cohort UNINDEXED,
    faq_slug UNINDEXED,
    question_text,
    question_variants,
    answer_text,
    tokenize='trigram'
);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
