-- target_db: autonomath
-- migration wave24_173_invoice_status_history
--
-- Purpose
-- -------
-- Historical event-log of 適格事業者 (qualified-invoice issuer) status changes
-- keyed on the invoice registration number (T+13). Captures the full
-- active → 廃止 → re-active arc that the static `invoice_registrants`
-- table flattens into a current-state snapshot. Without this table, the
-- `tax_client_monthly_public_digest` artifact (SYNTHESIS §8.13) cannot
-- answer "did this 取引先 lose qualification between fiscal year boundaries"
-- and the company baseline cannot show the cause-of-change provenance.
--
-- Backlog row: SYNTHESIS_2026_05_06.md §8.14 row 5 (`invoice_status_history`).
--
-- Source families covered (W1_A02 / 02_A_SOURCE_PROFILE.jsonl):
--   * `nta_invoice_zenken_monthly_bulk`  — monthly full snapshot diff
--   * `nta_invoice_sabun_daily_diff`     — daily delta CSV
--   * `nta_invoice_webapi_lookup`        — single-T-number authoritative probe
--   * `nta_invoice_search_ui_human_fallback` — operator triage path
--
-- Relationship to existing tables
-- -------------------------------
--   * `invoice_registrants` (jpintel.db, 13,801 rows delta + monthly 4M-row
--     bulk wired 2026-04-29) keeps current-state-only. This table is its
--     APPEND-ONLY history pair on autonomath.db, joined by t_number.
--   * `houjin_change_history` (NTA 法人番号 lineage) is the parallel for
--     houjin_bangou; these two tables are siblings, NOT a single table —
--     T-number issuer state and 法人 lineage state are disjoint event types.
--   * `entity_resolution_bridge_v2` (mig 168) provides the (t_number ↔
--     houjin_bangou) join axis; this table does NOT duplicate that mapping.
--   * `source_receipt_ledger` (DF-02 / mig 171) — every history row carries
--     `receipt_id` FK so the row's evidence chain is one JOIN away.
--
-- target_db = autonomath
-- ----------------------
-- First-line marker `-- target_db: autonomath` is mandatory; entrypoint.sh
-- §4 globs every migration with this prefix and applies idempotently to
-- $AUTONOMATH_DB_PATH on Fly boot. NEVER re-enable Fly release_command
-- (CLAUDE.md "Common gotchas" + feedback_no_quick_check_on_huge_sqlite
-- memory — 9.4 GB DB blows past the 60s release grace).
--
-- Idempotency contract
-- --------------------
--   * `CREATE TABLE IF NOT EXISTS` — re-run on a populated DB is a no-op.
--   * 4 indexes all use `CREATE INDEX IF NOT EXISTS`.
--   * 1 view uses `CREATE VIEW IF NOT EXISTS`.
--   * No DML — backfill is the ETL's job.
--
-- ¥3/req billing posture
-- ----------------------
-- Status-history reads are billed at ¥3/req (税込 ¥3.30) under
-- /v1/invoices/{t_number}/history and the MCP equivalent. NO LLM call inside
-- the read path — pure SQLite + index lookup. The `attribution_json` column
-- carries verbatim license +출처 fragments so every surfaced row can be
-- reproduced from source without re-resolving.
--
-- Schema notes
-- ------------
--   * `history_id` INTEGER PRIMARY KEY AUTOINCREMENT — surrogate; never
--     exposed externally.
--   * `t_number` TEXT NOT NULL — `T` + 13-digit. Required (this entire table
--     is keyed on the invoice number; rows with NULL T are illegal).
--   * `houjin_bangou` TEXT — 13-digit. NULL for 個人事業主 (W1_A02 kind=1).
--     The (t_number, houjin_bangou) pair is NOT 1:1 — for 法人 the lower 13
--     digits of T equal houjin_bangou, but for 個人 they DO NOT — never
--     strip-and-cast.
--   * `status_before` / `status_after` TEXT — enum-as-text, allowed values
--     in the CHECK below. The transition (NULL → 'active') is the initial
--     registration event; ('active' → 'haishi') is voluntary deregistration;
--     ('haishi' → 'active') is rare but possible re-registration; ('active'
--     → 'shobun_torikeshi') is NTA-side cancellation under 消費税法 §57の2
--     第10項. NEVER let status_before == status_after — a row with no
--     transition is meaningless and is rejected by CHECK.
--   * `changed_at` TEXT NOT NULL — ISO-8601 date (effective date of the
--     transition, NOT the discovery date). For zenken bulk we use NTA's
--     公表日; for sabun daily we use the diff date.
--   * `discovered_at` TEXT NOT NULL DEFAULT (datetime('now')) — when our
--     ingest first observed the transition. Distinct from `changed_at`
--     because NTA can backdate corrections.
--   * `source_url` TEXT NOT NULL — verbatim primary URL.
--   * `source_id` TEXT NOT NULL — one of the 4 source IDs above; CHECK
--     constraint ensures only known source ingest paths can write.
--   * `fetched_at` TEXT NOT NULL — ISO-8601; when ingest fetched the bytes
--     that surfaced this row.
--   * `content_hash` TEXT NOT NULL — sha256 of the source bytes as observed
--     (for diffing future re-fetches without re-storing).
--   * `attribution_json` TEXT NOT NULL — JSON object with verbatim license
--     fragment + 出典 string + retrieval method (so we can publish without
--     re-deriving 出典 string at query time). PDL v1.0 mandate per CLAUDE.md
--     "monthly 4M-row zenken bulk wired 2026-04-29".
--   * `receipt_id` INTEGER REFERENCES source_receipt_ledger(receipt_id) —
--     DF-02 cross-link. NULL is allowed for back-fill rows pre-DF-02 launch
--     but every NEW row inserted post-launch MUST carry it (enforced by
--     ETL, not by SQLite — sqlite FK can't conditionally enforce).
--   * `cause_code` TEXT — short code for the proximate cause (e.g.
--     'voluntary_deregistration', 'business_closed', 'shobun_torikeshi',
--     'name_change_only', 'address_change_only'). NULL when the source
--     does not report cause (most zenken bulk rows).
--   * `notes` TEXT — operator-only free-text triage memo; NEVER surfaced
--     to the public artifact path.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS invoice_status_history (
    history_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    t_number            TEXT NOT NULL,
    houjin_bangou       TEXT,
    status_before       TEXT,
    status_after        TEXT NOT NULL,
    changed_at          TEXT NOT NULL,
    discovered_at       TEXT NOT NULL DEFAULT (datetime('now')),
    source_url          TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    fetched_at          TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    attribution_json    TEXT NOT NULL,
    receipt_id          INTEGER,
    cause_code          TEXT,
    notes               TEXT,

    -- T format: literal 'T' + 13 ASCII digits.
    CHECK (
        length(t_number) = 14
        AND substr(t_number, 1, 1) = 'T'
        AND substr(t_number, 2) GLOB '[0-9]*'
        AND substr(t_number, 2) NOT GLOB '*[^0-9]*'
    ),
    -- houjin_bangou format: 13 ASCII digits when present.
    CHECK (
        houjin_bangou IS NULL
        OR (length(houjin_bangou) = 13
            AND houjin_bangou GLOB '[0-9]*'
            AND houjin_bangou NOT GLOB '*[^0-9]*')
    ),
    -- Status enum.
    CHECK (status_before IS NULL OR status_before IN (
        'active', 'haishi', 'shobun_torikeshi', 'unknown'
    )),
    CHECK (status_after IN (
        'active', 'haishi', 'shobun_torikeshi', 'unknown'
    )),
    -- A history row MUST represent a real transition.
    CHECK (status_before IS NULL OR status_before <> status_after),
    -- source_id allowlist: only the 4 NTA invoice paths can write.
    CHECK (source_id IN (
        'nta_invoice_zenken_monthly_bulk',
        'nta_invoice_sabun_daily_diff',
        'nta_invoice_webapi_lookup',
        'nta_invoice_search_ui_human_fallback'
    ))
);

-- Index 1: primary lookup — "give me the full timeline for this T-number,
-- newest first." This is the dominant query shape from the company folder
-- and tax-client digest artifacts.
CREATE INDEX IF NOT EXISTS idx_invoice_status_history_t_changed
    ON invoice_status_history (t_number, changed_at DESC);

-- Index 2: secondary lookup by houjin_bangou for the company-folder path
-- where the user supplies 法人番号 not T-number. Partial because individuals
-- are NULL on this column.
CREATE INDEX IF NOT EXISTS idx_invoice_status_history_houjin_changed
    ON invoice_status_history (houjin_bangou, changed_at DESC)
    WHERE houjin_bangou IS NOT NULL;

-- Index 3: receipt_id FK lookup — for the audit-pack path that walks
-- receipts and joins back to the events that triggered them.
CREATE INDEX IF NOT EXISTS idx_invoice_status_history_receipt
    ON invoice_status_history (receipt_id)
    WHERE receipt_id IS NOT NULL;

-- Index 4: cause_code triage — small, partial. Used by the operator dashboard
-- to surface ihansei-flagged transitions for review.
CREATE INDEX IF NOT EXISTS idx_invoice_status_history_cause
    ON invoice_status_history (cause_code, changed_at DESC)
    WHERE cause_code IS NOT NULL;

-- Public-surface view: hides operator notes and the discovered_at delta.
CREATE VIEW IF NOT EXISTS v_invoice_status_history_public AS
SELECT
    history_id,
    t_number,
    houjin_bangou,
    status_before,
    status_after,
    changed_at,
    source_url,
    source_id,
    fetched_at,
    content_hash,
    attribution_json,
    cause_code
FROM invoice_status_history;
