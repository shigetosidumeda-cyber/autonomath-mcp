-- target_db: autonomath
-- migration wave24_168_entity_resolution_bridge_v2
--
-- Purpose
-- -------
-- Canonical cross-source identity bridge for the M00-F data spine. Bundles
-- houjin_bangou (NTA), invoice_registration_number (T+13-digit), edinet_code
-- (E+6-digit), sec_code (4-digit listed), gbiz_id (gBizINFO internal), and
-- jpo_applicant_id (J-PlatPat 9-digit) into a single row per identity event,
-- with explicit match_confidence + match_method + dispute_flag so every
-- public surface can enforce an artifact-level confidence floor without
-- re-deriving identity at query time.
--
-- This is the highest-priority backlog object in SYNTHESIS_2026_05_06 §8.14
-- (the other three are source_catalog / source_freshness_ledger /
-- cross_source_signal_layer). Without this layer, source families keep being
-- ingested without a join axis and the company-folder / DD-pack / sales-dossier
-- artifacts cannot honestly assert "this row is the same legal entity as
-- that row".
--
-- Relationship to existing tables
-- -------------------------------
-- This table SUPERSEDES the loose join via `am_alias` + `entity_id_map` for
-- corporate-identity questions:
--   * `am_alias` (335,605 rows) stays as the surface-form dictionary
--     (canonical_id ↔ alias_text). It does NOT carry houjin_bangou, T-number,
--     edinet_code together — only one identifier per row.
--   * `entity_id_map` (mig 032) maps am_entities.canonical_id ↔ jpi
--     unified_id, but is also single-axis.
--   * `entity_match` (sketched in 04_A_ENTITY_BRIDGE_GRAPH §3) was a draft
--     that this migration finalizes with the v2 column set (adds gbiz_id /
--     jpo_applicant_id / sec_code / address_normalized / representative_name
--     and a deterministic supersede chain).
--
-- The companion ETL `scripts/etl/backfill_entity_resolution_bridge.py` walks
-- am_alias + am_entities (record_kind='corporate_entity') + gbiz_corp_activity
-- (post-M01) and INSERT OR IGNOREs into this table on the (canonical_houjin_bangou)
-- composite uniqueness so re-runs are idempotent.
--
-- target_db = autonomath (entrypoint.sh §4 picks up; release_command stays off)
-- ----------------------------------------------------------------------------
-- The first line `-- target_db: autonomath` marks this as autonomath-DB only.
-- entrypoint.sh §4 globs every `scripts/migrations/*.sql` whose first line
-- matches and applies idempotently to $AUTONOMATH_DB_PATH on each Fly boot.
-- Re-runs are safe: every CREATE uses IF NOT EXISTS, no ALTER TABLE.
--
-- DO NOT re-enable Fly release_command to apply this — 87+ migrations × 9.4 GB
-- autonomath.db hangs the release machine (CLAUDE.md "Common gotchas" +
-- feedback_no_quick_check_on_huge_sqlite memory).
--
-- Idempotency contract
-- --------------------
-- * `CREATE TABLE IF NOT EXISTS entity_resolution_bridge_v2` — re-run on a
--   DB that already has the table is a no-op.
-- * `CREATE INDEX IF NOT EXISTS` for all 6 indexes.
-- * `CREATE VIEW IF NOT EXISTS v_entity_resolution_public`.
-- * No DML — backfill is the ETL's job, not the migration's.
--
-- ¥3/req billing posture
-- ----------------------
-- Resolution requests through `/v1/entities/resolve` and the MCP equivalent
-- are billed at ¥3 per resolution (税込 ¥3.30) per CLAUDE.md non-negotiable
-- constraint. NO LLM call inside the resolver — pure SQLite + rapidfuzz.
-- The `evidence_source_ids` column is a JSON array of source_id strings
-- (verbatim from W1_A* shards) so every surfaced bridge can be traced back
-- to a primary source without re-resolving.
--
-- Schema notes
-- ------------
-- * `bridge_id` INTEGER PRIMARY KEY AUTOINCREMENT — surrogate; NEVER expose
--   externally as a stable identifier (use canonical_houjin_bangou for that
--   when available; otherwise use the (invoice_registration_number) for
--   個人事業主).
-- * `canonical_houjin_bangou` TEXT — 13-digit NTA 法人番号. NULL allowed
--   for 個人事業主 / 任意団体 (W0_A10 #5, W1_A02 kind=1). When NULL, at
--   least one of (invoice_registration_number, edinet_code, gbiz_id,
--   jpo_applicant_id) MUST be NOT NULL — enforced via CHECK below.
-- * `invoice_registration_number` TEXT — `T` + 13-digit. For 法人 (kind=2/3)
--   the lower 13 digits equal canonical_houjin_bangou; for 個人 (kind=1)
--   they DO NOT — never strip-and-cast (W1_A02 hard rule).
-- * `edinet_code` TEXT — `E` + 6-digit. NULL for 非上場 + 非提出.
-- * `sec_code` TEXT — 4-digit (4001..9999). NULL for non-listed.
-- * `gbiz_id` TEXT — gBizINFO internal identifier. NULL if not in gBiz.
-- * `jpo_applicant_id` TEXT — J-PlatPat 9-digit applicant code. NULL if no
--   IP filing (W1_A13 ip_applicant_bridge).
-- * `company_name_normalized` TEXT — NFKC fold + 株式会社/有限会社/合同会社
--   等 法人格語尾 stripped + half/full-width fold + lowercase Latin
--   (per §1.1 fuzzy_match_threshold_recommended).
-- * `address_normalized` TEXT — 都道府県 + 市区町村 ONLY. 番地 / 部屋番号 /
--   building name are STRIPPED to avoid PII redistribution and to keep the
--   row stable across minor 住所 drift (per §6 anonymization gate
--   conservatism). For 個人事業主 this is the registered prefecture+city
--   only; never the residence address.
-- * `representative_name` TEXT — NULL for 個人事業主 unless authorization-
--   to-surface is recorded explicitly (W1_A02 kind=1 個人氏名公表同意 trap).
-- * `match_confidence` REAL — strict CHECK BETWEEN 0.0 AND 1.0. The PUBLIC
--   surface gate is 0.95 for sensitive artifacts (enforcement / labor /
--   permit / KFS / court), 0.85 for procurement / 採択 / fuzzy bridges,
--   0.70 for general informational surfaces, NEVER raw 1.0 (a perfect
--   match still has the human-error floor).
-- * `match_method` TEXT — enum-as-text. Allowed values are listed in the
--   CHECK below; any new method must update both the CHECK and the resolver.
-- * `evidence_source_ids` TEXT — JSON array of source_id strings, e.g.
--   `["nta_houjin_bangou_bulk_monthly", "gbizinfo_bulk_jsonl_monthly"]`.
--   At least 1 source_id required. Stored as TEXT (JSON) not as a relation
--   to keep the resolver hot path single-table.
-- * `created_at` / `updated_at` — ISO-8601 (datetime('now')), matches the
--   rest of the schema convention.
-- * `dispute_flag` BOOL DEFAULT 0 — flipped to 1 by the
--   identity-drift sentinel cron (商号変更 / 合併 / 廃業 / 大手共通名義
--   false-positive — §7.1..7.6).
-- * `dispute_reason` TEXT — short string; NULL when dispute_flag=0.
-- * `superseded_by_bridge_id` INTEGER — self-FK; set when a corrected
--   bridge replaces this one (e.g. on 合併 / 名義変更 lineage).
--
-- Indexes
-- -------
-- 1. (canonical_houjin_bangou) WHERE NOT NULL — primary lookup; the most
--    common entry point for /v1/entities/resolve?houjin_bangou=...
-- 2. (invoice_registration_number) WHERE NOT NULL — for invoice-pack
--    queries; partial because the column is NULL on non-registered.
-- 3. (edinet_code) WHERE NOT NULL — EDINET lookup.
-- 4. (company_name_normalized) — fuzzy lookup hot path; NOT WHERE since
--    almost every row has a name.
-- 5. (match_confidence DESC) — for high-confidence-first scans (the
--    artifact-level confidence floor enforcement).
-- 6. PARTIAL (dispute_flag) WHERE dispute_flag=1 — review queue (small,
--    most rows are 0 so partial keeps the index tight).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entity_resolution_bridge_v2 (
    bridge_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_houjin_bangou     TEXT,
    invoice_registration_number TEXT,
    edinet_code                 TEXT,
    sec_code                    TEXT,
    gbiz_id                     TEXT,
    jpo_applicant_id            TEXT,
    company_name_normalized     TEXT,
    address_normalized          TEXT,
    representative_name         TEXT,
    match_confidence            REAL NOT NULL CHECK (match_confidence BETWEEN 0.0 AND 1.0),
    match_method                TEXT NOT NULL CHECK (match_method IN (
        'direct_houjin_bangou',
        'invoice_t_number_to_houjin',
        'edinet_code_to_houjin',
        'gbizinfo_reverse',
        'name_address',
        'name_address_representative',
        'fuzzy_address_representative',
        'fts_proximity',
        'jpo_id_to_houjin_via_bridge',
        'invoice_individual_name_address',
        'manual_human_review'
    )),
    evidence_source_ids         TEXT NOT NULL,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    dispute_flag                INTEGER NOT NULL DEFAULT 0 CHECK (dispute_flag IN (0, 1)),
    dispute_reason              TEXT,
    superseded_by_bridge_id     INTEGER REFERENCES entity_resolution_bridge_v2(bridge_id),

    -- At least one identifier MUST be present. A bridge with all NULL
    -- identifiers is a logic error and would silently corrupt downstream
    -- artifacts.
    CHECK (
        canonical_houjin_bangou IS NOT NULL
        OR invoice_registration_number IS NOT NULL
        OR edinet_code IS NOT NULL
        OR gbiz_id IS NOT NULL
        OR jpo_applicant_id IS NOT NULL
    ),

    -- houjin_bangou format: 13 ASCII digits (no leading T).
    CHECK (
        canonical_houjin_bangou IS NULL
        OR (length(canonical_houjin_bangou) = 13
            AND canonical_houjin_bangou GLOB '[0-9]*'
            AND canonical_houjin_bangou NOT GLOB '*[^0-9]*')
    ),

    -- T number format: literal 'T' + 13 ASCII digits.
    CHECK (
        invoice_registration_number IS NULL
        OR (length(invoice_registration_number) = 14
            AND substr(invoice_registration_number, 1, 1) = 'T'
            AND substr(invoice_registration_number, 2) GLOB '[0-9]*'
            AND substr(invoice_registration_number, 2) NOT GLOB '*[^0-9]*')
    ),

    -- EDINET format: literal 'E' + 6 ASCII digits.
    CHECK (
        edinet_code IS NULL
        OR (length(edinet_code) = 7
            AND substr(edinet_code, 1, 1) = 'E'
            AND substr(edinet_code, 2) GLOB '[0-9]*'
            AND substr(edinet_code, 2) NOT GLOB '*[^0-9]*')
    ),

    -- sec_code format: 4 ASCII digits.
    CHECK (
        sec_code IS NULL
        OR (length(sec_code) = 4
            AND sec_code GLOB '[0-9]*'
            AND sec_code NOT GLOB '*[^0-9]*')
    )
);

-- Index 1: primary lookup by houjin_bangou. Partial because individuals are
-- NULL on this column and we never want to scan them when the user supplied
-- a bangou.
CREATE INDEX IF NOT EXISTS idx_entity_resolution_bridge_v2_houjin
    ON entity_resolution_bridge_v2 (canonical_houjin_bangou)
    WHERE canonical_houjin_bangou IS NOT NULL;

-- Index 2: invoice-pack lookup (kind=1 個人 + kind=2/3 法人 both go here).
CREATE INDEX IF NOT EXISTS idx_entity_resolution_bridge_v2_invoice
    ON entity_resolution_bridge_v2 (invoice_registration_number)
    WHERE invoice_registration_number IS NOT NULL;

-- Index 3: EDINET-side lookup.
CREATE INDEX IF NOT EXISTS idx_entity_resolution_bridge_v2_edinet
    ON entity_resolution_bridge_v2 (edinet_code)
    WHERE edinet_code IS NOT NULL;

-- Index 4: fuzzy name lookup hot path. Non-partial because almost every row
-- carries a name.
CREATE INDEX IF NOT EXISTS idx_entity_resolution_bridge_v2_name
    ON entity_resolution_bridge_v2 (company_name_normalized);

-- Index 5: confidence-DESC scan for the public-surface confidence-floor gate.
CREATE INDEX IF NOT EXISTS idx_entity_resolution_bridge_v2_confidence
    ON entity_resolution_bridge_v2 (match_confidence DESC);

-- Index 6: review queue. Partial keeps the index tight (most rows are 0).
CREATE INDEX IF NOT EXISTS idx_entity_resolution_bridge_v2_dispute
    ON entity_resolution_bridge_v2 (dispute_flag, updated_at DESC)
    WHERE dispute_flag = 1;

-- Public-surface view. The artifact-level confidence floor (0.95) is encoded
-- here so REST / MCP / site / llms.txt can SELECT from this view directly
-- and never see low-confidence rows. Disputed rows are also withheld.
-- Surfaces ONLY (canonical_houjin_bangou, name_normalized) — representative
-- name + address + dispute reason stay in the underlying table for operator
-- triage and never reach the public surface.
CREATE VIEW IF NOT EXISTS v_entity_resolution_public AS
SELECT
    bridge_id,
    canonical_houjin_bangou,
    invoice_registration_number,
    edinet_code,
    sec_code,
    company_name_normalized,
    match_confidence,
    match_method,
    updated_at
FROM entity_resolution_bridge_v2
WHERE dispute_flag = 0
  AND match_confidence >= 0.95
  AND superseded_by_bridge_id IS NULL;
