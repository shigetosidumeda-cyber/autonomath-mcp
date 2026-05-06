-- target_db: autonomath
-- migration wave24_163_am_citation_network
--
-- Why this exists:
--   Cross-corpus citation graph derived from regex extraction over
--   am_law_article body text + nta_tsutatsu_index references +
--   court_decisions (jpi_court_decisions) related-laws JSON.
--
--   Drives "what law cites what law", inbound-degree ranking
--   (most-cited authority detection) and outbound-degree ranking
--   (most-citing law surfaces).
--
-- Schema:
--   * citing_entity_id   TEXT  — am_law.canonical_id, nta_tsutatsu_index.code, or court unified_id
--   * citing_kind        TEXT  — 'law' | 'tsutatsu' | 'court_decision'
--   * cited_entity_id    TEXT  — am_law.canonical_id (cited targets are laws here)
--   * cited_kind         TEXT  — 'law' (extensible)
--   * citation_count     INTEGER — number of times the (citing -> cited) edge appears
--   * computed_at        TEXT NOT NULL DEFAULT (datetime('now'))
--   * PRIMARY KEY (citing_entity_id, cited_entity_id)
--
-- Indexes:
--   * (cited_entity_id) — inbound-degree (most-cited) lookup
--   * (citing_entity_id) — outbound-degree (most-citing) lookup
--   * (citing_kind, cited_kind) — kind-pair filter scans
--
-- Idempotency:
--   CREATE * IF NOT EXISTS. Populator uses INSERT OR REPLACE keyed on
--   (citing_entity_id, cited_entity_id) — re-run safe.
--
-- DOWN: see wave24_163_am_citation_network_rollback.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_citation_network (
    citing_entity_id TEXT NOT NULL,
    citing_kind      TEXT NOT NULL CHECK (citing_kind IN ('law','tsutatsu','court_decision')),
    cited_entity_id  TEXT NOT NULL,
    cited_kind       TEXT NOT NULL DEFAULT 'law',
    citation_count   INTEGER NOT NULL DEFAULT 1,
    computed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (citing_entity_id, cited_entity_id)
);

CREATE INDEX IF NOT EXISTS ix_citation_cited
    ON am_citation_network(cited_entity_id);

CREATE INDEX IF NOT EXISTS ix_citation_citing
    ON am_citation_network(citing_entity_id);

CREATE INDEX IF NOT EXISTS ix_citation_kinds
    ON am_citation_network(citing_kind, cited_kind);
