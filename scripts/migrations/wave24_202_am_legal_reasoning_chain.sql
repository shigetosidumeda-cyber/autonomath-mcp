-- target_db: autonomath
-- migration: wave24_202_am_legal_reasoning_chain
-- generated_at: 2026-05-17
-- author: Lane N3 — Legal reasoning chain DB (判例 → 通達 → 法令 → 学説 triples)
-- spec: docs/_internal/MOAT_N3_LEGAL_REASONING_CHAIN_2026_05_17.md
--
-- Purpose
-- -------
-- jpcite Niche Moat Lane N3 lands the canonical destination for the 三段論法
-- (syllogistic) reasoning chains that 税理士 / 会計士 cohort agents pull when
-- asked "この処理は安全か?". Each chain assembles:
--
--   * premise (大前提) — 法令条文 (am_law_article ids) + 通達 references
--                       (am_law_article ids on law:*-tsutatsu rows)
--   * minor premise (小前提) — 判例 / 採決事例 (court_decisions HAN-* ids on
--                              jpintel.db side + nta_saiketsu ids on the
--                              autonomath.db side)
--   * conclusion (結論) — 学説 + 一般実務 (deterministic text + confidence)
--   * 反対説 / 異論 (opposing view) — captured separately so the chain
--                                       remains "honest about ambiguity"
--   * citation triple — 法令 + 判例 + 通達 packaged as JSON for the MCP
--                       walk surface
--
-- Why a new table (not an ALTER on am_relation / am_citation_judge_law)
-- --------------------------------------------------------------------
--   1. am_relation is the canonical KG edge set; absorbing the syllogistic
--      composition would conflate (a) what the corpus said vs (b) what the
--      chain composer derived. Dim O verified-fact principle demands the
--      separation.
--   2. Each chain carries its own confidence + opposing_view_text +
--      computed_by_model + computed_at provenance. ALTERing the relation
--      table cannot host those fields without bloating every edge row.
--   3. The chain composer is rerun-able: when topic taxonomy or chain
--      rules improve we want to drop and re-emit chains atomically per
--      topic without touching the base corpus.
--   4. Chain composition is pure-Python rule code (no LLM, no model
--      inference) — the ``computed_by_model`` column lets us distinguish
--      ``"rule_engine_v1"`` from any future ML-assisted variant without
--      collapsing them into the same surface.
--
-- Schema
-- ------
-- * chain_id                 — canonical ``LRC-<10 lowercase hex>`` (matches
--                              the rest of the autonomath SOT naming so the
--                              MCP surface can pattern-match like
--                              ``TAX-<10 hex>`` / ``HAN-<10 hex>``).
-- * topic_id                 — canonical topic slug (``corporate_tax:yakuin_hosyu``
--                              / ``shouhi_zei:shiire_kojo`` /
--                              ``subsidy:keizai_gouriseii`` / ``labor:rodo_jikan``
--                              / ``commerce:yakuin_sennin`` etc.). The
--                              taxonomy lives in
--                              ``scripts/build_legal_reasoning_chain.py``
--                              constant block — not in another table —
--                              so the chain composer can drift the labels
--                              without an extra migration.
-- * topic_label              — human-readable JP label (e.g.
--                              "役員報酬の損金算入"). Stored so the MCP
--                              surface can render without re-joining a
--                              lookup table.
-- * tax_category             — high-level fence
--                              ('corporate_tax' / 'consumption_tax' /
--                              'income_tax' / 'subsidy' / 'labor' /
--                              'commerce' / 'other'). Indexed for the
--                              get_reasoning_chain hot-path.
-- * premise_law_article_ids  — JSON array of am_law_article.article_id ints.
--                              The "law side" of the 大前提. Empty array
--                              (not NULL) when none.
-- * premise_tsutatsu_ids     — JSON array of am_law_article.article_id ints
--                              that sit on a law:*-tsutatsu canonical id.
--                              The "通達 side" of the 大前提. Empty array
--                              (not NULL) when none.
-- * minor_premise_judgment_ids — JSON array of court_decisions.unified_id
--                              strings (HAN-* on the jpintel.db side) +
--                              nta_saiketsu.saiketsu_id strings. The
--                              小前提. Empty array (not NULL) when none.
-- * conclusion_text          — Pure-Python composed conclusion (closed
--                              vocab, no LLM). NOT NULL — every chain
--                              MUST have a conclusion or it would not be
--                              a chain.
-- * confidence               — 0.0..1.0 per-row confidence. Composite of
--                              (a) source-coverage (how many of premise /
--                              minor / opposing fields are non-empty)
--                              and (b) opposing-view density (a chain
--                              with an opposing view caps at 0.85 to
--                              reflect honest ambiguity).
-- * opposing_view_text       — 反対説 / 異論 text. NULL when no opposing
--                              view is encoded (chain remains shippable
--                              but the confidence cap removes the bonus).
-- * citations                — JSON object packaging the 法令 + 判例 + 通達
--                              triple in render-ready form:
--                              ``{"law": [{"article_id":..., "article_number":..., "law_canonical_id":...}, ...],
--                                "hanrei": [{"unified_id":..., "court":..., "decision_date":..., "key_ruling_excerpt":...}, ...],
--                                "tsutatsu": [{"article_id":..., "article_number":..., "law_canonical_id":..., "title":...}, ...]}``
--                              The MCP surface renders this verbatim;
--                              re-joining is intentionally avoided so the
--                              path stays pure SQLite SELECT.
-- * computed_by_model        — 'rule_engine_v1' for the current pure-Python
--                              composer. Future ML-assisted variants get
--                              their own model id so re-runs can co-exist.
-- * computed_at              — ISO-8601 UTC timestamp of composition.
--
-- Indexes
-- -------
-- * idx_amlrc_topic           — (topic_id) for the get_reasoning_chain hot path.
-- * idx_amlrc_category        — (tax_category, confidence DESC) for the
--                               walk_reasoning_chain query-driven cohort cut.
-- * idx_amlrc_computed        — (computed_at DESC) for the re-run gate.
--
-- Idempotency
-- -----------
-- CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS. The companion
-- composer (scripts/build_legal_reasoning_chain.py) uses INSERT OR REPLACE
-- on (chain_id) so re-runs overwrite prior composition passes without
-- duplicating rows.
--
-- Cost posture
-- ------------
-- Pure SQLite DDL. Zero LLM, zero AWS side-effect. Population happens via
-- the N3 composer; this migration only creates the destination.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_legal_reasoning_chain (
    chain_id                     TEXT PRIMARY KEY,
    topic_id                     TEXT NOT NULL,
    topic_label                  TEXT NOT NULL,
    tax_category                 TEXT NOT NULL,
    premise_law_article_ids      TEXT NOT NULL DEFAULT '[]',
    premise_tsutatsu_ids         TEXT NOT NULL DEFAULT '[]',
    minor_premise_judgment_ids   TEXT NOT NULL DEFAULT '[]',
    conclusion_text              TEXT NOT NULL,
    confidence                   REAL NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    opposing_view_text           TEXT,
    citations                    TEXT NOT NULL DEFAULT '{}',
    computed_by_model            TEXT NOT NULL DEFAULT 'rule_engine_v1',
    computed_at                  TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CONSTRAINT ck_amlrc_chain_id_shape
        CHECK (chain_id LIKE 'LRC-%' AND length(chain_id) = 14),
    CONSTRAINT ck_amlrc_category
        CHECK (tax_category IN (
            'corporate_tax', 'consumption_tax', 'income_tax',
            'subsidy', 'labor', 'commerce', 'other'
        ))
);

CREATE INDEX IF NOT EXISTS idx_amlrc_topic
    ON am_legal_reasoning_chain(topic_id);

CREATE INDEX IF NOT EXISTS idx_amlrc_category
    ON am_legal_reasoning_chain(tax_category, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_amlrc_computed
    ON am_legal_reasoning_chain(computed_at DESC);

-- Convenience view: high-confidence chains, ready for the get_reasoning_chain
-- MCP tool to dispatch by topic without a confidence filter on the caller
-- side.
CREATE VIEW IF NOT EXISTS v_am_legal_reasoning_chain_confident AS
    SELECT
        chain_id,
        topic_id,
        topic_label,
        tax_category,
        premise_law_article_ids,
        premise_tsutatsu_ids,
        minor_premise_judgment_ids,
        conclusion_text,
        confidence,
        opposing_view_text,
        citations,
        computed_by_model,
        computed_at
      FROM am_legal_reasoning_chain
     WHERE confidence >= 0.6
     ORDER BY topic_id, confidence DESC;
