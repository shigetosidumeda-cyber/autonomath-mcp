-- target_db: autonomath
-- migration 223_am_authority_contact
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #8 (官公庁 contact 情報、TOS 確認後配信)
--
-- Purpose
-- -------
-- am_authority は 20 行ある (省庁 / 庁 / 都道府県 / 政令市)。各
-- authority に対して、operator + 上流側 (consultant / 税理士) が
-- 問合せ可能な contact info を持ちたい:
--
--   - 部署名 (担当課)
--   - tel + 受付時間
--   - email (公開されているもの)
--   - inquiry form URL
--   - press contact (報道発表問合せ先 — 異なる窓口がよくある)
--
-- ただし **TOS 確認後配信** が原則: 各省庁の web TOS が "scrape して
-- 第三者配信は禁止" の場合がある。`tos_status` カラムで未確認 / 確認済
-- / 禁止 を明示し、`tos_status != 'allowed'` の行は REST に出さない。
--
-- 既存 am_authority と分けた理由
-- -------------------------------
-- am_authority は基幹 master (20 行 fixed)、contact 情報は volatile
-- (担当課が年度ごとに変わる)。1:N 関係 (一つの authority に複数の
-- 担当課) なので別 table が正解。
--
-- Surface contract
-- ----------------
-- - REST: `GET /v1/am/authorities/{id}/contacts` returns rows where
--   tos_status='allowed' AND review_status='approved'.
-- - MCP: NOT surfaced as a tool (operator-side reference, not agent
--   workflow). Agents should cite `canonical_url` from the authority
--   record directly, never email.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_authority_contact (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    authority_id    INTEGER NOT NULL,                        -- FK am_authority.id
    department_name TEXT,                                    -- "中小企業庁 経営支援課"
    role_kind       TEXT    NOT NULL DEFAULT 'general',      -- 'general' | 'press' | 'subsidy_admin' | 'audit' | 'foia'
    tel             TEXT,                                    -- "03-3501-1900"
    tel_hours       TEXT,                                    -- "9:30-17:30 (土日祝休)"
    email           TEXT,
    inquiry_url     TEXT,                                    -- form URL on the authority's site
    notes           TEXT,                                    -- "電話受付 unavailable 12:00-13:00" etc.
    -- TOS / redistribution status
    tos_status      TEXT    NOT NULL DEFAULT 'unverified',   -- 'unverified' | 'allowed' | 'forbidden'
    tos_verified_at TEXT,
    tos_source_url  TEXT,                                    -- evidence URL for the TOS check
    -- Lifecycle metadata
    last_verified_at TEXT,                                   -- last time operator confirmed phone/email still live
    detected_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    review_status   TEXT    NOT NULL DEFAULT 'pending',
    reviewed_at     TEXT,
    reviewed_by     TEXT,
    CONSTRAINT ck_authority_contact_role CHECK (role_kind IN (
        'general', 'press', 'subsidy_admin', 'audit', 'foia'
    )),
    CONSTRAINT ck_authority_contact_tos CHECK (tos_status IN (
        'unverified', 'allowed', 'forbidden'
    )),
    CONSTRAINT ck_authority_contact_review CHECK (review_status IN (
        'pending', 'approved', 'rejected'
    ))
);

-- Per-authority lookup (group by role_kind).
CREATE INDEX IF NOT EXISTS idx_authority_contact_auth
    ON am_authority_contact(authority_id, role_kind);

-- Surface filter: only rows that are TOS-cleared AND approved.
CREATE INDEX IF NOT EXISTS idx_authority_contact_surface
    ON am_authority_contact(authority_id)
    WHERE tos_status = 'allowed' AND review_status = 'approved';

-- TOS-pending queue (operator's verify backlog).
CREATE INDEX IF NOT EXISTS idx_authority_contact_tos_pending
    ON am_authority_contact(authority_id)
    WHERE tos_status = 'unverified';

-- View: TOS-cleared, approved contacts (the only surface that REST
-- emits). Re-create-able.
DROP VIEW IF EXISTS v_am_authority_contact_surface;
CREATE VIEW v_am_authority_contact_surface AS
SELECT
    id,
    authority_id,
    department_name,
    role_kind,
    tel,
    tel_hours,
    email,
    inquiry_url,
    notes,
    last_verified_at
FROM am_authority_contact
WHERE tos_status = 'allowed' AND review_status = 'approved';
