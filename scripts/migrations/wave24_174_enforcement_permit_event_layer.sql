-- target_db: autonomath
-- migration wave24_174_enforcement_permit_event_layer
--
-- Purpose
-- -------
-- Unified event table that flattens行政処分・公正取引委員会命令・労働局
-- 違反公表・許認可取消・建設業/宅建業/運輸/介護等のネガティブ情報を
-- 一行=1イベント として保持する横断レイヤー. Every event row carries
-- a stable `event_kind`, severity, dated_at, prefecture, JSIC industry,
-- the (anonymized-or-resolved) respondent, and a verbatim source_url +
-- content_hash so the `public_dd_evidence_book` artifact (SYNTHESIS §8.13
-- "DD pack") can answer "what regulators have touched this 法人 in the
-- last 5 years" with one indexed scan.
--
-- Backlog row: SYNTHESIS_2026_05_06.md §8.14 row 6
-- (`enforcement_permit_event_layer`).
--
-- Source families covered (W1_A* / 02_A_SOURCE_PROFILE.jsonl):
--   * `fsa_per_respondent_disclosure`               (P0, FSA per-respondent)
--   * `jftc_haijo_sochi_meirei` / `jftc_kacho_kin_meirei` /
--     `jftc_keikoku` / `jftc_chui`                  (P0/P1/P2)
--   * `mhlw_roudoukyoku_ihan_kouhyou`               (P0)
--   * `mhlw_kouseikyoku_hokeniryou_shobun`          (P0)
--   * `mhlw_kaigo_shobun_torikeshi`                 (P0)
--   * `mlit_negative_kensetsu` / `mlit_negative_takken` /
--     `mlit_negative_unsou_jidosha_anzen03` /
--     `mlit_negative_jidosha_seibi`                 (P0/P0/P0/P1)
--   * `mlit_permit_kensetsu_etsuran2`               (P1)
--   * `churoi_meirei_db_master`                     (P1)
--   * `chiroi_47pref_orders_aggregate`              (P2)
--   * `labor_enforcement_cross_respondent_master`   (P2)
--   * `caa_recall_general` / `caa_food_recall`      (recall — gated)
--   * `nite_product_accident`                       (recall — gated)
--   * `meti_recall_notification`                    (recall — gated)
--
-- DEEP-08 anonymization gate
-- --------------------------
-- Per DEEP-08 anonymization gate (referenced in the calling spec), when
-- `respondent_match_confidence < 0.95` the row's `respondent_houjin_bangou`
-- is left NULL and the event is surfaced via `respondent_name_anonymized`
-- only. The public view (`v_enforcement_event_public`) gates on
-- `respondent_match_confidence >= 0.95` so low-confidence rows never
-- appear on the artifact-level DD pack. The 0.95 floor is the same as
-- entity_resolution_bridge_v2 (mig 168) for sensitive surfaces.
--
-- Relationship to existing tables
-- -------------------------------
--   * `am_enforcement_detail` (22,258 rows; 6,455 with houjin_bangou) is the
--     pre-existing single-source-style enforcement table. This new layer
--     UNIFIES across FSA/JFTC/MHLW/MLIT/中労委/47-pref so the artifact
--     surface stops needing source-specific JOINs. We do NOT delete
--     am_enforcement_detail — it stays as the source mirror; this table
--     is the read-side projection.
--   * `enforcement_decision_refs` (jpintel.db) is the bridging table for
--     program×enforcement; that stays.
--   * `entity_resolution_bridge_v2` (mig 168) provides the houjin_bangou
--     resolution; rows here look up via canonical_houjin_bangou.
--   * `source_receipt_ledger` (DF-02 / mig 171) — every event row carries
--     `receipt_id` FK so the audit chain is one JOIN away.
--
-- target_db = autonomath
-- ----------------------
-- First-line marker required. entrypoint.sh §4 picks up. NEVER re-enable
-- Fly release_command. See feedback_no_quick_check_on_huge_sqlite memory.
--
-- Idempotency contract
-- --------------------
-- All CREATE statements use IF NOT EXISTS. No DML.
--
-- ¥3/req billing posture
-- ----------------------
-- Event reads are ¥3/req (税込 ¥3.30) under /v1/enforcement/events and the
-- MCP equivalent. NO LLM call inside the read path — pure SQLite + index.
-- The `decision_summary` field is verbatim source-quote ≤ 200 chars
-- (license_verbatim_ng safe fragment), NEVER an LLM rewording.
--
-- Schema notes
-- ------------
--   * `event_id` INTEGER PRIMARY KEY AUTOINCREMENT — surrogate.
--   * `event_kind` TEXT NOT NULL — enum-as-text. The full enum:
--       jftc_haijo_meirei         | 排除措置命令
--       jftc_kacho_kin            | 課徴金納付命令
--       jftc_keikoku              | 警告
--       jftc_chui                 | 注意
--       fsa_kanshi_kantoku_shobun | 金融処分（業務改善命令・業務停止命令等）
--       mhlw_roudou_ihan          | 労働関係法令違反公表
--       mhlw_iryou_shobun         | 保険医療機関 取消・登録取消
--       mhlw_kaigo_torikeshi      | 介護事業者 指定取消
--       mlit_kensetsu_negative    | 建設業 ネガティブ情報
--       mlit_takken_negative      | 宅建業 ネガティブ情報
--       mlit_unsou_negative       | 運輸 ネガティブ情報
--       mlit_seibi_negative       | 自動車整備 ネガティブ情報
--       mlit_kensetsu_permit      | 建設業 許可（許可情報自体）
--       churoi_meirei             | 中央労働委員会 命令
--       chiroi_meirei             | 都道府県 労働委員会 命令
--       caa_recall                | 消費者庁 リコール（gated）
--       nite_jiko                 | NITE 製品事故（gated）
--       meti_recall               | METI リコール（gated）
--       prefecture_kyoka_torikeshi| 自治体 許認可取消
--       other                     | 上記以外（暫定。事後再分類）
--   * `severity` INTEGER NOT NULL — 1..5; mapping is per source family
--     (jftc_haijo_meirei = 5, kacho_kin = 5, keikoku = 3, chui = 2;
--     mhlw_iryou_torikeshi = 5; mlit_negative_kensetsu varies by 処分種別).
--     The mapping table is in `scripts/etl/backfill_enforcement_event_layer.py`
--     (single source-of-truth dict).
--   * `dated_at` TEXT NOT NULL — ISO-8601 date of the order/announcement.
--   * `prefecture` TEXT — JIS X 0401 2-digit prefecture code; NULL for
--     national-level orders (JFTC haijo etc.).
--   * `prefecture_name` TEXT — 都道府県名 (denormalized for read speed).
--   * `industry_jsic` TEXT — JSIC major (1-letter A..T) when classifiable;
--     NULL when the event has no industry signal.
--   * `respondent_houjin_bangou` TEXT — 13-digit; NULL when match confidence
--     < 0.95 (DEEP-08 gate). When non-NULL, `respondent_match_confidence`
--     MUST be >= 0.95 (CHECK constraint).
--   * `respondent_name_anonymized` TEXT NOT NULL — display string; for
--     low-confidence rows this is "X社 (匿名化)" or similar; for resolved
--     rows it is the canonical company name.
--   * `respondent_match_confidence` REAL — 0.0..1.0; mirrors
--     entity_resolution_bridge_v2.match_confidence.
--   * `decision_summary` TEXT — verbatim source quote ≤ 200 chars;
--     license_verbatim_ng safe length.
--   * `decision_full_url` TEXT — link to the full decision PDF / page.
--   * `source_url` TEXT NOT NULL — listing-page URL where this event was
--     observed.
--   * `source_id` TEXT NOT NULL — one of the 18+ source IDs above.
--   * `fetched_at` TEXT NOT NULL.
--   * `content_hash` TEXT NOT NULL.
--   * `license` TEXT NOT NULL — verbatim license tag (e.g. 'gov_standard',
--     'pdl_v1.0', 'cc_by_4.0', 'proprietary'). Drives the `redistribute_ok`
--     flag for downstream artifacts.
--   * `redistribute_ok` INTEGER NOT NULL — 0/1; 1 only when license allows
--     verbatim redistribution. The public view filters on this.
--   * `receipt_id` INTEGER — FK to source_receipt_ledger (DF-02).
--   * `superseded_by_event_id` INTEGER REFERENCES enforcement_permit_event_layer(event_id)
--     — set when a corrected/updated decision replaces this one.
--   * `notes` TEXT — operator-only triage memo.
--
-- Indexes
-- -------
--  1. (event_kind, dated_at DESC)            — kind-filtered timeline.
--  2. (respondent_houjin_bangou, dated_at DESC) WHERE houjin NOT NULL
--                                              AND respondent_match_confidence >= 0.95
--                                              — DD pack hot path.
--  3. (prefecture, industry_jsic, dated_at DESC) — region/industry rollup.
--  4. (severity DESC, dated_at DESC)         — high-severity-first scan.
--  5. (receipt_id) WHERE NOT NULL             — audit chain.
--  6. (source_id, fetched_at DESC)            — freshness audit by source.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS enforcement_permit_event_layer (
    event_id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    event_kind                  TEXT NOT NULL,
    severity                    INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 5),
    dated_at                    TEXT NOT NULL,
    prefecture                  TEXT,
    prefecture_name             TEXT,
    industry_jsic               TEXT,
    respondent_houjin_bangou    TEXT,
    respondent_name_anonymized  TEXT NOT NULL,
    respondent_match_confidence REAL,
    decision_summary            TEXT,
    decision_full_url           TEXT,
    source_url                  TEXT NOT NULL,
    source_id                   TEXT NOT NULL,
    fetched_at                  TEXT NOT NULL,
    content_hash                TEXT NOT NULL,
    license                     TEXT NOT NULL,
    redistribute_ok             INTEGER NOT NULL DEFAULT 0 CHECK (redistribute_ok IN (0, 1)),
    receipt_id                  INTEGER,
    superseded_by_event_id      INTEGER REFERENCES enforcement_permit_event_layer(event_id),
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    notes                       TEXT,

    -- event_kind enum.
    CHECK (event_kind IN (
        'jftc_haijo_meirei',
        'jftc_kacho_kin',
        'jftc_keikoku',
        'jftc_chui',
        'fsa_kanshi_kantoku_shobun',
        'mhlw_roudou_ihan',
        'mhlw_iryou_shobun',
        'mhlw_kaigo_torikeshi',
        'mlit_kensetsu_negative',
        'mlit_takken_negative',
        'mlit_unsou_negative',
        'mlit_seibi_negative',
        'mlit_kensetsu_permit',
        'churoi_meirei',
        'chiroi_meirei',
        'caa_recall',
        'nite_jiko',
        'meti_recall',
        'prefecture_kyoka_torikeshi',
        'other'
    )),
    -- prefecture format: 2 ASCII digits (01..47) when present.
    CHECK (
        prefecture IS NULL
        OR (length(prefecture) = 2
            AND prefecture GLOB '[0-9]*'
            AND prefecture NOT GLOB '*[^0-9]*')
    ),
    -- industry_jsic: single uppercase letter A..T when present.
    CHECK (
        industry_jsic IS NULL
        OR industry_jsic GLOB '[A-T]'
    ),
    -- houjin format.
    CHECK (
        respondent_houjin_bangou IS NULL
        OR (length(respondent_houjin_bangou) = 13
            AND respondent_houjin_bangou GLOB '[0-9]*'
            AND respondent_houjin_bangou NOT GLOB '*[^0-9]*')
    ),
    -- match_confidence range.
    CHECK (
        respondent_match_confidence IS NULL
        OR (respondent_match_confidence >= 0.0
            AND respondent_match_confidence <= 1.0)
    ),
    -- DEEP-08 gate: when houjin is non-NULL, confidence MUST be >= 0.95.
    -- When confidence < 0.95, houjin MUST be NULL.
    CHECK (
        respondent_houjin_bangou IS NULL
        OR respondent_match_confidence >= 0.95
    ),
    -- source_id allowlist (extends as new sources land — keep in sync
    -- with scripts/etl/backfill_enforcement_event_layer.py).
    CHECK (source_id IN (
        'fsa_per_respondent_disclosure',
        'jftc_haijo_sochi_meirei',
        'jftc_kacho_kin_meirei',
        'jftc_keikoku',
        'jftc_chui',
        'mhlw_roudoukyoku_ihan_kouhyou',
        'mhlw_kouseikyoku_hokeniryou_shobun',
        'mhlw_kaigo_shobun_torikeshi',
        'mlit_negative_kensetsu',
        'mlit_negative_takken',
        'mlit_negative_unsou_jidosha_anzen03',
        'mlit_negative_jidosha_seibi',
        'mlit_permit_kensetsu_etsuran2',
        'churoi_meirei_db_master',
        'chiroi_47pref_orders_aggregate',
        'labor_enforcement_cross_respondent_master',
        'caa_recall_general',
        'caa_food_recall',
        'nite_product_accident',
        'meti_recall_notification',
        'manual_human_review'
    ))
);

-- Index 1: kind-filtered timeline.
CREATE INDEX IF NOT EXISTS idx_enforcement_event_kind_dated
    ON enforcement_permit_event_layer (event_kind, dated_at DESC);

-- Index 2: DD pack hot path. Partial — only high-confidence resolved rows.
CREATE INDEX IF NOT EXISTS idx_enforcement_event_houjin_dated
    ON enforcement_permit_event_layer (respondent_houjin_bangou, dated_at DESC)
    WHERE respondent_houjin_bangou IS NOT NULL
      AND respondent_match_confidence >= 0.95;

-- Index 3: region/industry rollup (47 pref × 20 industry × time).
CREATE INDEX IF NOT EXISTS idx_enforcement_event_region_industry
    ON enforcement_permit_event_layer (prefecture, industry_jsic, dated_at DESC);

-- Index 4: severity-DESC scan.
CREATE INDEX IF NOT EXISTS idx_enforcement_event_severity
    ON enforcement_permit_event_layer (severity DESC, dated_at DESC);

-- Index 5: receipt audit chain.
CREATE INDEX IF NOT EXISTS idx_enforcement_event_receipt
    ON enforcement_permit_event_layer (receipt_id)
    WHERE receipt_id IS NOT NULL;

-- Index 6: freshness audit by source.
CREATE INDEX IF NOT EXISTS idx_enforcement_event_source_fetched
    ON enforcement_permit_event_layer (source_id, fetched_at DESC);

-- Public-surface view: enforces the DEEP-08 anonymization gate
-- (confidence >= 0.95) AND the redistribute_ok license gate AND
-- non-superseded. The artifact-level DD pack reads from this view, NEVER
-- from the underlying table.
CREATE VIEW IF NOT EXISTS v_enforcement_event_public AS
SELECT
    event_id,
    event_kind,
    severity,
    dated_at,
    prefecture,
    prefecture_name,
    industry_jsic,
    respondent_houjin_bangou,
    respondent_name_anonymized,
    decision_summary,
    decision_full_url,
    source_url,
    source_id,
    fetched_at,
    content_hash,
    license
FROM enforcement_permit_event_layer
WHERE redistribute_ok = 1
  AND superseded_by_event_id IS NULL
  AND (
      respondent_houjin_bangou IS NULL
      OR respondent_match_confidence >= 0.95
  );
