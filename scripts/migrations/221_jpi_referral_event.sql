-- migration 221_jpi_referral_event
-- target_db: jpintel
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #6 (organic acquisition tracking)
--
-- Purpose
-- -------
-- jpcite is 100% organic — no paid ads, no affiliate links, no
-- analytics tag (Plausible / Fathom / GA4 都て削除). We are still
-- accountable for understanding which **organic channel** is driving
-- conversion (= a signup or first paid API call).
--
-- This table captures **first-party** referral signal:
--
--   - HTTP referer header (best-effort, often stripped by mobile)
--   - utm_source / utm_medium / utm_campaign on the landing URL
--   - "discovered_via" — the user can self-report on signup
--     ("AI assistant" / "blog post" / "Twitter" / "search" / "other")
--
-- Crucially, NO third-party JavaScript is required — we read the
-- referer + UTM params server-side at the moment of first-touch.
--
-- Privacy posture
-- ---------------
-- - No cross-site cookies, no fingerprinting, no fingerprintjs.
-- - We log the **anonymized** IP (truncated to /24 for IPv4, /56 for
--   IPv6) — not the raw IP. This still gives us a country-level signal
--   for organic-by-region without enabling de-anonymization.
-- - The `key_hash` is set ONLY after the user signs up + makes their
--   first paid call; pre-signup rows stay anonymous.
-- - 1-year retention. After that the row is hash-only.
--
-- Surface contract
-- ----------------
-- - REST: NO public list endpoint.
-- - Aggregated: `scripts/ops/referral_rollup.py` emits a monthly
--   referral-by-source CSV (operator only).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jpi_referral_event (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Touch attribution
    touch_kind          TEXT    NOT NULL,                    -- 'first' | 'last' | 'conversion'
    touched_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Source signals (referrer header + UTM params)
    referer_host        TEXT,                                -- "chat.openai.com" / "github.com"
    referer_full        TEXT,                                -- full Referer (up to 500 chars; truncated)
    utm_source          TEXT,
    utm_medium          TEXT,
    utm_campaign        TEXT,
    utm_term            TEXT,
    utm_content         TEXT,
    -- Landing page on jpcite
    landing_path        TEXT    NOT NULL,                    -- "/programs/123" / "/playground" / "/"
    -- Optional self-report
    self_reported_via   TEXT,                                -- 'ai_assistant' | 'blog' | 'twitter' | 'search' | 'word_of_mouth' | 'other'
    -- Tie to identity AFTER conversion. NULL while anonymous.
    key_hash            TEXT,
    -- Anonymized network signal (no raw IP).
    network_prefix      TEXT,                                -- "203.104.209.0/24" or "2001:db8::/56"
    country_iso2        TEXT,                                -- best-effort from CF-IPCountry; NULL if unknown
    -- User-Agent class only (not the full string — that's PII-adjacent
    -- and prone to fingerprinting). We bucket into 'browser_desktop' /
    -- 'browser_mobile' / 'bot_friendly' / 'curl' / 'sdk' / 'unknown'.
    ua_class            TEXT    NOT NULL DEFAULT 'unknown',
    CONSTRAINT ck_referral_kind CHECK (touch_kind IN ('first', 'last', 'conversion')),
    CONSTRAINT ck_referral_ua_class CHECK (ua_class IN (
        'browser_desktop', 'browser_mobile', 'bot_friendly', 'curl', 'sdk', 'unknown'
    ))
);

-- Time-windowed analytics index (the most common operator query).
CREATE INDEX IF NOT EXISTS idx_jpi_referral_chrono
    ON jpi_referral_event(touched_at DESC);

-- Source rollup (group by referer_host).
CREATE INDEX IF NOT EXISTS idx_jpi_referral_source
    ON jpi_referral_event(referer_host, touched_at DESC)
    WHERE referer_host IS NOT NULL;

-- Conversion attribution: when a key_hash gets attached, we want to
-- pull all touches.
CREATE INDEX IF NOT EXISTS idx_jpi_referral_key
    ON jpi_referral_event(key_hash, touched_at DESC)
    WHERE key_hash IS NOT NULL;

-- UTM rollup index.
CREATE INDEX IF NOT EXISTS idx_jpi_referral_utm
    ON jpi_referral_event(utm_source, utm_medium, touched_at DESC)
    WHERE utm_source IS NOT NULL;
