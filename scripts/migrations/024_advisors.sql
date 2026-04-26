-- 024_advisors.sql
-- 士業 (certified advisor) affiliate matching surface — advisors self-serve
-- sign up, we surface them next to matching program search results, and
-- take a flat ¥3,000 / percent commission per converted referral via Stripe
-- Connect (Express).
--
-- Business context:
--   * AutonoMath core = ¥1/req metered API over 補助金/融資/税制 (CLAUDE.md).
--   * This table is a separate revenue stream: the advisor pays us, not the
--     API user. Default commission = ¥3,000 per conversion (commission_model
--     'flat'); 'percent' alternative is capped at 30% by CHECK constraint
--     for ethics + to stay below any plausible 士業法 objection threshold.
--   * No cookies, no 3rd-party tracking: referrals ride on a single-use
--     `referral_token` (32 hex, URL param).
--
-- Why NOT extended `api_keys` / subscribers:
--   * Different principal. An advisor is an ongoing business entity
--     identified by 法人番号; an api_keys row is a consumer of the API
--     identified by key_hash. Joining them confuses the billing direction.
--   * Different lifecycle. Advisors need verification (onboarding + Stripe
--     Connect + optional manual review). api_keys are issued instantly at
--     Checkout completion.
--   * Different payout direction. api_keys => WE charge THEM (Stripe usage
--     records). advisors => WE PAY THEM (Stripe Transfer / Connect).
--
-- Source-discipline note (CLAUDE.md §Data hygiene):
--   source_url on every row must be a primary government list (中小企業庁
--   認定支援機関 公表一覧 preferred). Aggregators (noukaweb, hojyokin-portal,
--   biz.stayway, etc.) remain banned. For self-serve signups the primary
--   source is the signup form itself — use the canonical form URL
--   (https://autonomath.ai/advisors-signup.html) as source_url.
--
-- PII posture (APPI):
--   * houjin_bangou (法人番号) is PUBLIC for incorporated entities — not PII.
--   * 個人番号 (マイナンバー) is NEVER stored. If a sole-proprietor advisor
--     lacks a houjin_bangou we require a 任意団体/屋号 stub and a
--     Stripe-side identity verification instead of storing anything
--     individual-number-shaped.
--   * contact_email + contact_phone are business contacts; dashboard login
--     happens via Stripe Connect Express portal (issuer: Stripe) OR a
--     magic-link email, never via a password we store.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op. The
-- runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- advisors -- 士業 / 認定支援機関 profile
-- ============================================================================
CREATE TABLE IF NOT EXISTS advisors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou TEXT NOT NULL UNIQUE,          -- 13 digits (public for incorporated entities)
    firm_name TEXT NOT NULL,
    firm_name_kana TEXT,
    firm_type TEXT NOT NULL,                     -- see CHECK below
    specialties_json TEXT NOT NULL,              -- JSON array: e.g. ["subsidy","loan","tax"]
    industries_json TEXT,                        -- JSON array: e.g. ["agri","manufacture"]
    prefecture TEXT NOT NULL,                    -- canonical ('東京都', not '東京')
    city TEXT,
    address TEXT,
    contact_url TEXT,                            -- HTTPS advisor landing / contact form
    contact_email TEXT,
    contact_phone TEXT,
    intro_blurb TEXT,                            -- ≈200字 自己紹介
    success_count INTEGER NOT NULL DEFAULT 0,    -- cumulative verified conversions (ranking signal)
    commission_rate_pct INTEGER NOT NULL DEFAULT 5
        CHECK (commission_rate_pct BETWEEN 1 AND 30),
    commission_yen_per_intro INTEGER DEFAULT 3000,
    commission_model TEXT NOT NULL DEFAULT 'flat'
        CHECK (commission_model IN ('flat', 'percent')),
    stripe_connect_account_id TEXT,              -- 'acct_...' (set after Connect onboarding)
    verified_at TEXT,                            -- NULL = unverified; ranking gate
    source_url TEXT NOT NULL,                    -- primary source (中小企業庁 list URL, or signup form URL)
    source_fetched_at TEXT NOT NULL,             -- ISO 8601 UTC when source_url was last fetched
    active INTEGER NOT NULL DEFAULT 1,           -- 0 = paused / self-deactivated
    disabled_reason TEXT,                        -- free-form; set when active=0
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (firm_type IN (
        '税理士法人',
        '認定支援機関',
        '社会保険労務士',
        '中小企業診断士',
        '行政書士',
        '弁護士',
        '銀行',
        '商工会議所',
        'その他'
    )),
    CHECK (active IN (0, 1)),
    CHECK (length(houjin_bangou) = 13)
);

CREATE INDEX IF NOT EXISTS idx_advisors_prefecture
    ON advisors(prefecture);
CREATE INDEX IF NOT EXISTS idx_advisors_firm_type
    ON advisors(firm_type);
CREATE INDEX IF NOT EXISTS idx_advisors_verified
    ON advisors(verified_at);
CREATE INDEX IF NOT EXISTS idx_advisors_active
    ON advisors(active);

-- ============================================================================
-- advisor_referrals -- one row per click-tracked introduction
-- ============================================================================
-- Single-use token flow (no cookies, APPI-light):
--   1. User hits /v1/advisors/track with {advisor_id}. We mint a 32-hex
--      referral_token, INSERT row, return redirect URL = advisor.contact_url
--      ?ref=<token>.
--   2. Advisor later reports conversion via /v1/advisors/report-conversion
--      with the same referral_token. We set converted_at + compute
--      commission_yen.
--   3. Payout cron runs the Stripe Transfer and sets commission_paid_at +
--      stripe_transfer_id.
--
-- ip_hash stored instead of raw IP (APPI 通信の秘密 + PII minimization).
-- referral_token is UNIQUE so a leaked URL cannot be replayed into a second
-- conversion by a bad-actor advisor.
CREATE TABLE IF NOT EXISTS advisor_referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referral_token TEXT NOT NULL UNIQUE,         -- 32 hex chars, single-use
    advisor_id INTEGER NOT NULL REFERENCES advisors(id),
    source_query_hash TEXT,                      -- sha256 digest of query params that matched
    source_program_id TEXT,                      -- unified_id of the program that seeded the match
    ip_hash TEXT,                                -- sha256(ip + salt) — for fraud detection only
    clicked_at TEXT NOT NULL,                    -- ISO 8601 UTC
    advisor_notified_at TEXT,                    -- when we emailed the advisor (optional)
    converted_at TEXT,                           -- NULL = not yet converted
    conversion_value_yen INTEGER,                -- optional, for 'percent' model
    conversion_evidence_url TEXT,                -- advisor-supplied proof (e.g. contract PDF URL)
    commission_yen INTEGER,                      -- computed at conversion time
    commission_paid_at TEXT,                     -- set when Stripe Transfer succeeds
    stripe_transfer_id TEXT                      -- 'tr_...'
);

CREATE INDEX IF NOT EXISTS idx_advisor_referrals_advisor
    ON advisor_referrals(advisor_id, clicked_at);
CREATE INDEX IF NOT EXISTS idx_advisor_referrals_converted
    ON advisor_referrals(converted_at);
CREATE INDEX IF NOT EXISTS idx_advisor_referrals_unpaid
    ON advisor_referrals(commission_paid_at) WHERE commission_paid_at IS NULL;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
