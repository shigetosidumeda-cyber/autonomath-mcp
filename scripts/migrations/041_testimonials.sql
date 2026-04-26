-- 041_testimonials.sql
-- Public testimonial collection + moderation (P5-ι, brand 5-pillar 透明・誠実).
--
-- Business context:
--   AutonoMath wants 5+ testimonials at T+90d, 100+ at Y5. Testimonials are
--   submitted by authenticated API-key holders, attached to one of 5 audience
--   buckets, and held in a moderation queue until the operator approves them.
--   Approval flips approved_at from NULL → ISO 8601 UTC; only approved rows
--   are surfaced via GET /v1/testimonials.
--
-- Why a separate table (not feedback / advisors):
--   * feedback (003_feedback.sql) is private bug-report intake. It's never
--     surfaced publicly and has its own daily-bucket rate limit.
--   * advisors (024_advisors.sql) is a payout-direction registry — different
--     principal, different lifecycle, different rate limits.
--   * testimonials are PUBLIC after approval, must remain anonymous-friendly
--     (`name` optional), and need a moderation gate that admin owns.
--
-- Privacy posture (INV-21 PII redaction integrity):
--   * api_key_hash is stored so the operator can dedupe submissions per key
--     and so a customer can DELETE their own testimonials. NEVER surfaced.
--   * `name` and `organization` are OPTIONAL — submitter can stay anonymous.
--     The public list shows whatever the submitter chose to share.
--   * `linkedin_url` is OPTIONAL. We do not validate identity from it; it's
--     a self-asserted attribution link.
--   * No email, no phone, no address — all fake-testimonial vectors that
--     don't add to the brand signal anyway.
--
-- Audience enum (5 buckets):
--   税理士 / 行政書士 / SMB / VC / Dev — picked from 5 audience pillars in
--   v8 plan. CHECK constraint enforced at the DB layer so the API can rely
--   on it without a parallel Python whitelist (matches the bounded-text-to-
--   select rule from feedback_bounded_text_to_select).
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op. The
-- runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS testimonials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash TEXT NOT NULL,
    audience TEXT NOT NULL CHECK (audience IN ('税理士','行政書士','SMB','VC','Dev')),
    text TEXT NOT NULL,
    name TEXT,                                  -- optional anonymous OK
    organization TEXT,
    linkedin_url TEXT,
    approved_at TEXT,                           -- NULL = pending moderation
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Public list path (approved rows ordered by approval time, descending).
CREATE INDEX IF NOT EXISTS idx_testimonials_approved
    ON testimonials(approved_at)
    WHERE approved_at IS NOT NULL;

-- Submitter dedupe path (operator can see all rows from one key).
CREATE INDEX IF NOT EXISTS idx_testimonials_key_hash
    ON testimonials(api_key_hash);

-- Moderation queue path (pending = approved_at IS NULL).
CREATE INDEX IF NOT EXISTS idx_testimonials_pending
    ON testimonials(created_at)
    WHERE approved_at IS NULL;
