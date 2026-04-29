-- target_db: jpintel
-- 098_program_post_award_calendar.sql
-- Post-award milestone calendar + customer "intentions" register
-- (navit cancel trigger #2: 採択後 monitoring is the structural blank
-- in navit's surface — they index pre-award discovery, not post-award
-- 報告期日 / 経費精算 / 中間検査 / 事業化状況報告).
--
-- Business context:
--   * `program_post_award_calendar` curates per-program post-award
--     milestones from the 公募要領 PDFs. Initial seed: ~80 high-volume
--     programs × 4 milestone kinds = ~320 rows. Examples:
--       - ものづくり補助金 採択後 → 中間報告 T+6m / 事業実績 T+12m / 経費精算
--         (確定検査) ~T+13m / 事業化状況報告 (年次).
--       - IT導入補助金 採択後 → 事業実施報告 T+6m / 効果報告 T+12m–T+36m.
--       - 事業再構築補助金 採択後 → 中間 T+6m / 確定 T+13m / 事業化 T+5y/年次.
--   * `customer_intentions` lets a 補助金コンサル register "顧問先 X is
--     APPLYING for program Y" (FREE — registration is on the customer's
--     own row tree). The cron then JOINs intentions × post_award_calendar
--     and emits webhook events ¥3 each on T-30 / T-7 / day-of milestones.
--
-- Idempotency:
--   * `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`. Safe
--     to re-apply via migrate.py and entrypoint.sh self-heal loop.
--
-- DOWN:
--   `DROP TABLE program_post_award_calendar; DROP TABLE customer_intentions;`
--   No companion rollback file because the table sizes are bounded
--   (calendar ~few thousand rows, intentions per-customer).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS program_post_award_calendar (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id          TEXT NOT NULL,                          -- programs.unified_id
    -- Milestone kind enum. Keep narrow so the dispatcher matrix stays
    -- legible. New kinds require a code change in dispatch_post_award_events.py.
    milestone_kind      TEXT NOT NULL CHECK (
                            milestone_kind IN (
                                'report_due_T+6m',
                                'report_due_T+12m',
                                'keihi_seisan_due',
                                'status_check'
                            )
                        ),
    -- Days after the award notification (採択通知日) that the milestone
    -- falls due. Negative values reserved for pre-award (not used here).
    days_after_award    INTEGER NOT NULL,
    -- Free-text label rendered in the webhook payload's `data.kind_label`
    -- field, e.g. "中間報告書 (事業実施期間 6 ヶ月時点)".
    kind_label          TEXT,
    -- Source URL (公募要領 PDF or 採択者向け案内 page) that documented this
    -- milestone. Required so the webhook can cite a primary source — same
    -- aggregator-banned posture as `programs.source_url`.
    source_url          TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- A program × milestone_kind pair should be unique (no duplicate
    -- "T+6m" milestone for the same program). Surface drift via UNIQUE
    -- so a botched curate doesn't double-fire webhooks.
    UNIQUE (program_id, milestone_kind)
);

CREATE INDEX IF NOT EXISTS idx_post_award_calendar_program
    ON program_post_award_calendar(program_id);

-- Customer "intentions" register: links api_key + client_profile_id to a
-- specific program the 顧問先 is applying for. The cron uses this to know
-- WHO to webhook and WHEN.
CREATE TABLE IF NOT EXISTS customer_intentions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash        TEXT NOT NULL,                          -- api_keys.key_hash
    -- Optional link to client_profiles.profile_id. When NULL the
    -- intention applies to the api_key as a whole (a solo SMB consultant
    -- using the API for themselves) rather than a specific 顧問先.
    profile_id          INTEGER,
    program_id          TEXT NOT NULL,                          -- programs.unified_id
    -- 採択 confirmation date (採択通知日). When NULL the intention is "still
    -- applying / not yet awarded" and the cron does NOT fire post-award
    -- events for it. Once the consultant updates this field, the calendar
    -- triggers begin firing on the calculated dates.
    awarded_at          TEXT,
    -- 'applying' before 採択 / 'awarded' after / 'cancelled' if the
    -- 顧問先 dropped out. Cron filters where status='awarded'.
    status              TEXT NOT NULL DEFAULT 'applying'
                            CHECK (status IN ('applying', 'awarded', 'cancelled')),
    notify_email        TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_customer_intentions_key
    ON customer_intentions(api_key_hash);
CREATE INDEX IF NOT EXISTS idx_customer_intentions_awarded
    ON customer_intentions(status, awarded_at)
 WHERE status = 'awarded';

-- Bookkeeping recorded by scripts/migrate.py.
