-- jpintel-mcp canonical schema
-- Generated on ingest from Autonomath unified_registry + enriched/ + exclusion_rules

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS programs (
    unified_id TEXT PRIMARY KEY,
    primary_name TEXT NOT NULL,
    aliases_json TEXT,
    authority_level TEXT,
    authority_name TEXT,
    prefecture TEXT,
    municipality TEXT,
    program_kind TEXT,
    official_url TEXT,
    amount_max_man_yen REAL,
    amount_min_man_yen REAL,
    subsidy_rate REAL,
    trust_level TEXT,
    tier TEXT,
    coverage_score REAL,
    gap_to_tier_s_json TEXT,
    a_to_j_coverage_json TEXT,
    excluded INTEGER DEFAULT 0,
    exclusion_reason TEXT,
    crop_categories_json TEXT,
    equipment_category TEXT,
    target_types_json TEXT,
    funding_purpose_json TEXT,
    amount_band TEXT,
    application_window_json TEXT,
    enriched_json TEXT,
    source_mentions_json TEXT,
    source_url TEXT,
    source_fetched_at TEXT,
    source_checksum TEXT,
    -- HTTP status code from the last `scripts/refresh_sources.py` liveness
    -- probe (NULL = never probed). Read by migration 074 to classify
    -- tier-X rows as `dead_official_url` when ≥ 400. Added to the
    -- canonical schema so a fresh volume gets the column at init_db()
    -- time; the legacy ALTER in `refresh_sources.py:79` is now a no-op
    -- on those volumes.
    source_last_check_status INTEGER,
    updated_at TEXT NOT NULL,
    -- R8 dataset versioning (migration 067). NULL valid_until = current
    -- (live) row; non-NULL marks the row as superseded. Backfilled from
    -- source_fetched_at on existing rows; new ingest writes both at
    -- insert time. See docs/compliance/data_governance.md §「法廷証拠
    -- reproducibility 保証」.
    valid_from TEXT,
    valid_until TEXT
);

CREATE INDEX IF NOT EXISTS idx_programs_tier ON programs(tier);
CREATE INDEX IF NOT EXISTS idx_programs_prefecture ON programs(prefecture);
CREATE INDEX IF NOT EXISTS idx_programs_authority_level ON programs(authority_level);
CREATE INDEX IF NOT EXISTS idx_programs_program_kind ON programs(program_kind);
CREATE INDEX IF NOT EXISTS idx_programs_amount_max ON programs(amount_max_man_yen);
CREATE INDEX IF NOT EXISTS idx_programs_source_fetched ON programs(source_fetched_at);
-- migration 056 P1 composite index for FTS post-dedup ORDER BY
CREATE INDEX IF NOT EXISTS idx_programs_tier_name ON programs(tier, primary_name);
-- R8 (migration 067): bitemporal range query support.
CREATE INDEX IF NOT EXISTS ix_programs_valid ON programs(valid_from, valid_until);

CREATE VIRTUAL TABLE IF NOT EXISTS programs_fts USING fts5(
    unified_id UNINDEXED,
    primary_name,
    aliases,
    enriched_text,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS exclusion_rules (
    rule_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    severity TEXT,
    program_a TEXT,
    program_b TEXT,
    program_b_group_json TEXT,
    description TEXT,
    source_notes TEXT,
    source_urls_json TEXT,
    extra_json TEXT,
    -- 011_external_data_tables.sql additions (kept here so a fresh volume
    -- that runs schema.sql before migrations still ends up with the
    -- correct final shape).
    source_excerpt TEXT,
    condition TEXT,
    -- 051_exclusion_rules_uid_keys.sql additions (P0-3 / J10 / K4 fix):
    -- legacy program_{a,b} keys are slug / Japanese name / unified_id
    -- mixed; the _uid columns store the resolved programs.unified_id when
    -- discoverable so callers can pass either form to check_exclusions
    -- without a silent miss.
    program_a_uid TEXT,
    program_b_uid TEXT
);

CREATE INDEX IF NOT EXISTS idx_exclusion_program_a ON exclusion_rules(program_a);
CREATE INDEX IF NOT EXISTS idx_exclusion_program_b ON exclusion_rules(program_b);
CREATE INDEX IF NOT EXISTS idx_exclusion_kind ON exclusion_rules(kind);
CREATE INDEX IF NOT EXISTS idx_exclusion_program_a_uid ON exclusion_rules(program_a_uid);
CREATE INDEX IF NOT EXISTS idx_exclusion_program_b_uid ON exclusion_rules(program_b_uid);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash TEXT PRIMARY KEY,
    customer_id TEXT,
    tier TEXT NOT NULL,
    stripe_subscription_id TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    last_used_at TEXT,
    -- Customer self-serve monthly cap (migration 037, P3-W). NULL = unlimited
    -- (default for legacy rows). Set via POST /v1/me/cap. Enforced by
    -- _CustomerCapMiddleware: when month-to-date Stripe-billable spend
    -- (count(usage_events where metered=1, status<400) * ¥3) reaches the cap,
    -- subsequent requests return 503 + {cap_reached: true} until JST 月初.
    -- Does NOT change the ¥3/req unit price (immutable).
    monthly_cap_yen INTEGER,
    -- Stripe subscription state cache (migration 052, P0 dunning banner).
    -- Written by Stripe webhook handler on subscription.created / .updated /
    -- .deleted / invoice.payment_failed / invoice.paid. Read by /v1/me so
    -- the static dashboard can surface dunning state without calling Stripe
    -- live on every page load.
    --   stripe_subscription_status: one of 'active' | 'trialing' | 'past_due'
    --     | 'canceled' | 'unpaid' | 'incomplete' | 'incomplete_expired'.
    --     NULL on free / anon keys; /v1/me translates NULL to 'no_subscription'.
    --   stripe_subscription_status_at: epoch seconds, last webhook write.
    --   stripe_subscription_current_period_end: epoch seconds, mirrors
    --     Stripe Subscription.current_period_end.
    --   stripe_subscription_cancel_at_period_end: 0/1, mirrors Stripe.
    stripe_subscription_status TEXT,
    stripe_subscription_status_at INTEGER,
    stripe_subscription_current_period_end INTEGER,
    stripe_subscription_cancel_at_period_end INTEGER,
    -- bcrypt dual-path (migration 073, Wave 16 P1). Set at issue time on
    -- new keys; NULL on legacy rows. Cost factor 12. require_key()
    -- prefers bcrypt verify when this column is non-NULL, otherwise falls
    -- back to the legacy HMAC-SHA256 path (PRIMARY KEY lookup already
    -- proves possession in that case). NEVER serves as a lookup index;
    -- bcrypt hashes are non-deterministic.
    key_hash_bcrypt TEXT,
    -- Trial-signup columns (migration 076, conversion-pathway audit
    -- 2026-04-29). Populated only on tier='trial' rows; NULL on
    -- 'paid' / 'free' / 'anonymous' keys. trial_email is captured at
    -- magic-link verify so the cron's expiration mail doesn't need to
    -- join trial_signups. trial_started_at == created_at for trial rows
    -- but is duplicated here so the cron index can target a single
    -- column. trial_expires_at is created_at + 14d. trial_requests_used
    -- is bumped by the request middleware for tier='trial' rows; when
    -- it reaches 200 the daily expire_trials cron revokes the key (and
    -- the per-request middleware can short-circuit immediately on hit).
    trial_email TEXT,
    trial_started_at TEXT,
    trial_expires_at TEXT,
    trial_requests_used INTEGER NOT NULL DEFAULT 0,
    -- Parent / child columns (migration 086, SaaS B2B fan-out).
    -- `id` mirrors SQLite's implicit rowid; populated explicitly at
    -- issuance time via last_insert_rowid() so the FK below resolves.
    -- `parent_key_id` is NULL on parent rows; non-NULL on child rows
    -- where it points at the parent's `id`. `label` is a free-text
    -- ≤64-char human identifier (`prod`, `customer_a`); NULL on parents,
    -- required at issuance on children. Server-side rule: a child cannot
    -- spawn grandchildren (refusal in billing.keys.issue_child_key).
    -- Stripe-side: children share parent's stripe_subscription_id so
    -- billing aggregates to the parent — children are invisible to Stripe.
    id INTEGER,
    parent_key_id INTEGER REFERENCES api_keys(id),
    label TEXT,
    -- Spike-guard opt-in (migration 087, anti-runaway 三点セット D).
    -- INTEGER N>=1 = enabled (current-hour usage > N * trailing-24h-avg
    -- → 503 + Retry-After: 3600). NULL / 0 = disabled (default).
    -- Customer sets via POST /v1/me/spike_guard.
    spike_threshold_factor INTEGER,
    -- Last 4 chars of the raw API key, captured at issuance. Surfaced in
    -- email notices (welcome / rotated / dunning) so customers can match
    -- the alert against the key fragment shown on success.html. The full
    -- raw key never leaves the issuance request — only the last 4 chars
    -- are stored, so leaking this column does NOT compromise the key.
    -- NULL on legacy rows pre-dating this column; render fallbacks use
    -- "????" placeholder.
    key_last4 TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_keys_customer ON api_keys(customer_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_tier ON api_keys(tier);
-- Partial index for dunning admin queries — only non-active states.
CREATE INDEX IF NOT EXISTS idx_api_keys_subscription_status
    ON api_keys(stripe_subscription_status)
    WHERE stripe_subscription_status IS NOT NULL
      AND stripe_subscription_status != 'active';
-- UNIQUE on `id` is required so the inline `parent_key_id REFERENCES
-- api_keys(id)` clause above resolves on fresh DBs (the table PK is
-- `key_hash`, so `id` would otherwise be a non-unique INTEGER column
-- and SQLite would reject the FK at first use). Mirrors the
-- migration-086 fix.
--
-- IMPORTANT: SQLite only treats a NON-partial UNIQUE INDEX as a valid
-- FK referent. A `WHERE id IS NOT NULL` partial index is rejected at
-- runtime with "foreign key mismatch — api_keys referencing api_keys".
-- Multiple-NULL rows remain legal because SQLite treats each NULL as
-- distinct under the UNIQUE constraint, so backfilling legacy rows is
-- still safe (they all carry NULL until the first issuance).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_api_keys_id
    ON api_keys(id);
-- Parent->children fan-out lookup (migration 086).
CREATE INDEX IF NOT EXISTS idx_api_keys_parent_key_id
    ON api_keys(parent_key_id)
    WHERE parent_key_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    ts TEXT NOT NULL,
    status INTEGER,
    metered INTEGER DEFAULT 0,
    params_digest TEXT,
    stripe_record_id TEXT,
    stripe_synced_at TEXT,
    -- Migration 061: search-quality regression telemetry. Both nullable;
    -- backfilled NULL on existing rows. latency_ms is wall-clock per-call
    -- latency in milliseconds (time.perf_counter), result_count is the
    -- number of rows returned by a search endpoint (NULL for non-search).
    latency_ms INTEGER,
    result_count INTEGER,
    -- Migration 085: optional caller-supplied attribution tag (X-Client-Tag
    -- header). Max 32 chars, alphanumeric+hyphen+underscore (validated by
    -- ClientTagMiddleware). NULL when the caller did not pass the header.
    -- Used by 税理士 顧問先 invoice line-item passthrough — purely metadata
    -- for cost allocation, NOT a pricing or cap input.
    client_tag TEXT,
    -- Per-request weight for Stripe metered billing. Default 1 = a normal
    -- single-row endpoint. Multi-row endpoints (batch_get_programs,
    -- bulk_evaluate, …) write quantity=N so a single audit row carries
    -- the same total ¥3 × N as N quantity=1 rows would, but with one
    -- Stripe usage_record + one idempotency key. Mirrors
    -- `log_usage(quantity=...)`.
    quantity INTEGER NOT NULL DEFAULT 1,
    -- Migration 122: stable logical request key derived from HTTP
    -- Idempotency-Key. Prevents duplicate usage_events / Stripe increments
    -- when a 2xx handler records usage but response-cache finalization fails.
    billing_idempotency_key TEXT,
    FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_usage_key_ts ON usage_events(key_hash, ts);
CREATE INDEX IF NOT EXISTS idx_usage_events_key_params ON usage_events(key_hash, params_digest, ts);
CREATE INDEX IF NOT EXISTS idx_usage_events_stripe_sync
    ON usage_events (stripe_synced_at)
    WHERE stripe_synced_at IS NULL;
-- Migration 061: composite index for /v1/admin/global_usage_by_tool 24h
-- per-endpoint aggregation.
CREATE INDEX IF NOT EXISTS idx_usage_events_endpoint_created
    ON usage_events(endpoint, ts);
-- Migration 085: per-tag monthly aggregate for /v1/me/usage?group_by=client_tag.
-- Partial index keeps the on-disk footprint trivial — only non-NULL tags
-- materialize an entry.
CREATE INDEX IF NOT EXISTS idx_usage_events_client_tag
    ON usage_events(key_hash, client_tag, ts)
    WHERE client_tag IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_events_billing_idempotency
    ON usage_events(key_hash, billing_idempotency_key)
    WHERE billing_idempotency_key IS NOT NULL;

-- Migration 062: empty-search log. Every 0-result search query is captured
-- here so the operator can drive ingest prioritization off real demand.
-- ip_hash is sha256(ip || daily_salt), NEVER raw IP. See
-- api/admin_telemetry.py::_ip_hash for the rotation policy.
CREATE TABLE IF NOT EXISTS empty_search_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    filters_json TEXT,
    ip_hash      TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_empty_search_log_query
    ON empty_search_log(query);
CREATE INDEX IF NOT EXISTS idx_empty_search_log_created
    ON empty_search_log(created_at DESC);

-- Migration 111 (P0-10, 2026-04-30): per-request analytics row for EVERY
-- HTTP request — including anonymous callers (key_hash NULL). Where
-- `usage_events` is purpose-built for billing reconciliation against
-- Stripe and rejects NULL key_hash by FK + NOT NULL, this table captures
-- the universe of traffic for adoption/funnel/feature-coverage analytics.
-- Recorded by `AnalyticsRecorderMiddleware` (api/middleware/analytics_recorder.py)
-- in BackgroundTasks so the response hot-path is never blocked.
--
-- PII rule: raw IP NEVER stored — `anon_ip_hash` is sha256(ip||daily_salt)
-- via `deps.hash_ip_for_telemetry`. `key_hash` is the same HMAC-derived
-- hash already stored in `api_keys.key_hash` (NOT raw key material).
-- `path` is the URL path with no query string and no T-numbers / law IDs
-- (path-param values stripped via `redact_pii`).
CREATE TABLE IF NOT EXISTS analytics_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    status        INTEGER NOT NULL,
    latency_ms    INTEGER,
    key_hash      TEXT,           -- NULL for anonymous traffic
    anon_ip_hash  TEXT,           -- sha256(ip||daily_salt); NULL if key_hash present
    client_tag    TEXT,           -- X-Client-Tag, validated; NULL when absent
    is_anonymous  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_analytics_events_ts
    ON analytics_events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_events_path_ts
    ON analytics_events(path, ts DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_events_key_ts
    ON analytics_events(key_hash, ts DESC)
    WHERE key_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_analytics_events_anon_ts
    ON analytics_events(anon_ip_hash, ts DESC)
    WHERE anon_ip_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS schema_migrations (
    id TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    source TEXT,
    created_at TEXT NOT NULL,
    unsubscribed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_subscribers_email ON subscribers(email);
CREATE INDEX IF NOT EXISTS idx_subscribers_created_at ON subscribers(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT,
    customer_id TEXT,
    tier TEXT,
    message TEXT NOT NULL,
    rating INTEGER,
    endpoint TEXT,
    request_id TEXT,
    ip_hash TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_key_hash ON feedback(key_hash);
CREATE INDEX IF NOT EXISTS idx_feedback_ip_hash ON feedback(ip_hash);

-- Per-IP MONTHLY quota for anonymous callers (no X-API-Key). See
-- scripts/migrations/007_anon_rate_limit.sql for rationale. Decoupled from
-- api_keys on purpose (no FK) so anon IPs can never be JOINed to a customer.
-- Column kept as `date` for schema stability post 2026-04-23 daily→monthly
-- switch; now stores YYYY-MM-01 (first-of-month JST) as the bucket key.
CREATE TABLE IF NOT EXISTS anon_rate_limit (
    ip_hash TEXT NOT NULL,
    date TEXT NOT NULL,          -- YYYY-MM-01 in JST (first of month, bucket key)
    call_count INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (ip_hash, date)
);

CREATE INDEX IF NOT EXISTS idx_anon_date ON anon_rate_limit(date);

-- Activation-sequence scheduler (D+1/3/7/14/30 post-signup emails). Full
-- rationale + UNIQUE / idx reasoning in
-- `scripts/migrations/008_email_schedule.sql` (+ 010 for the D+1 extension).
-- Short version: each api_key issuance inserts N rows via
-- `billing.keys.issue_key()`; the daily cron
-- (`scripts/send_scheduled_emails.py`) picks `sent_at IS NULL AND
-- send_at <= now()` and dispatches through the existing Postmark client.
--
-- D+0 is NOT in this table — it is sent synchronously from
-- `api/billing.py::_send_welcome_safe` because it carries the one-time
-- raw API key which must never be persisted (only the hash ever hits the
-- DB). `day0` is accepted in the CHECK only so audit / backfill tooling
-- can record retroactive rows after the fact; the runtime code path does
-- not INSERT day0 rows.
CREATE TABLE IF NOT EXISTS email_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id TEXT NOT NULL,
    email TEXT NOT NULL,
    kind TEXT NOT NULL
        CHECK(kind IN ('day0','day1','day3','day7','day14','day30')),
    send_at TIMESTAMP NOT NULL,
    sent_at TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    template_model_json TEXT,
    created_at TIMESTAMP NOT NULL,
    UNIQUE(api_key_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_email_schedule_due
    ON email_schedule(send_at, sent_at);
CREATE INDEX IF NOT EXISTS idx_email_schedule_api_key
    ON email_schedule(api_key_id);

-- ---------------------------------------------------------------------------
-- External-data tables (see scripts/migrations/011_external_data_tables.sql
-- for full rationale). Kept here so fresh volumes end up with the final
-- shape without relying on migration order. Re-applying 011 on a fresh DB
-- is a no-op (everything is CREATE IF NOT EXISTS; the ALTER TABLE is
-- handled by the duplicate-column fallback in scripts/migrate.py).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS program_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_name TEXT NOT NULL,
    form_name TEXT,
    form_type TEXT,
    form_format TEXT,
    form_url_direct TEXT,
    pages INTEGER,
    signature_required INTEGER,
    support_org_needed INTEGER,
    completion_example_url TEXT,
    source_url TEXT,
    source_excerpt TEXT,
    fetched_at TEXT,
    confidence REAL,
    UNIQUE(program_name, form_url_direct)
);

CREATE INDEX IF NOT EXISTS idx_program_documents_program_name
    ON program_documents(program_name);
CREATE INDEX IF NOT EXISTS idx_program_documents_form_type
    ON program_documents(form_type);

CREATE TABLE IF NOT EXISTS case_studies (
    case_id TEXT PRIMARY KEY,
    company_name TEXT,
    houjin_bangou TEXT,
    is_sole_proprietor INTEGER,
    prefecture TEXT,
    municipality TEXT,
    industry_jsic TEXT,
    industry_name TEXT,
    employees INTEGER,
    founded_year INTEGER,
    capital_yen INTEGER,
    case_title TEXT,
    case_summary TEXT,
    programs_used_json TEXT,
    total_subsidy_received_yen INTEGER,
    outcomes_json TEXT,
    patterns_json TEXT,
    publication_date TEXT,
    source_url TEXT,
    source_excerpt TEXT,
    fetched_at TEXT,
    confidence REAL
);

CREATE INDEX IF NOT EXISTS idx_case_studies_houjin_bangou
    ON case_studies(houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_case_studies_prefecture
    ON case_studies(prefecture);
CREATE INDEX IF NOT EXISTS idx_case_studies_industry_jsic
    ON case_studies(industry_jsic);
-- migration 056 P1 indexes
CREATE INDEX IF NOT EXISTS idx_case_studies_pubdate
    ON case_studies(publication_date DESC, case_id);

-- migration 057: FTS5 trigram for case_studies free-text search.
-- Replaces the 4-column LIKE scan in the /v1/case-studies/search q= path.
-- Triggers (case_studies_fts_ai/au/ad) are also created in 057_case_studies_fts.sql
-- for the live DB. Test DBs created via init_db() seed FTS rows manually
-- alongside their case_studies inserts to avoid trigger ordering surprises.
CREATE VIRTUAL TABLE IF NOT EXISTS case_studies_fts USING fts5(
    case_id UNINDEXED,
    company_name,
    case_title,
    case_summary,
    source_excerpt,
    tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS case_studies_fts_ai AFTER INSERT ON case_studies BEGIN
    INSERT INTO case_studies_fts (case_id, company_name, case_title, case_summary, source_excerpt)
    VALUES (NEW.case_id, COALESCE(NEW.company_name, ''), COALESCE(NEW.case_title, ''), COALESCE(NEW.case_summary, ''), COALESCE(NEW.source_excerpt, ''));
END;
CREATE TRIGGER IF NOT EXISTS case_studies_fts_au AFTER UPDATE ON case_studies BEGIN
    UPDATE case_studies_fts
        SET company_name=COALESCE(NEW.company_name, ''),
            case_title=COALESCE(NEW.case_title, ''),
            case_summary=COALESCE(NEW.case_summary, ''),
            source_excerpt=COALESCE(NEW.source_excerpt, '')
        WHERE case_id=NEW.case_id;
END;
CREATE TRIGGER IF NOT EXISTS case_studies_fts_ad AFTER DELETE ON case_studies BEGIN
    DELETE FROM case_studies_fts WHERE case_id=OLD.case_id;
END;

CREATE TABLE IF NOT EXISTS enforcement_cases (
    case_id TEXT PRIMARY KEY,
    event_type TEXT,
    program_name_hint TEXT,
    recipient_name TEXT,
    recipient_kind TEXT,
    recipient_houjin_bangou TEXT,
    is_sole_proprietor INTEGER,
    bureau TEXT,
    intermediate_recipient TEXT,
    prefecture TEXT,
    ministry TEXT,
    occurred_fiscal_years_json TEXT,
    amount_yen INTEGER,
    amount_project_cost_yen INTEGER,
    amount_grant_paid_yen INTEGER,
    amount_improper_grant_yen INTEGER,
    amount_improper_project_cost_yen INTEGER,
    reason_excerpt TEXT,
    legal_basis TEXT,
    source_url TEXT,
    source_section TEXT,
    source_title TEXT,
    disclosed_date TEXT,
    disclosed_until TEXT,
    fetched_at TEXT,
    confidence REAL
);

CREATE INDEX IF NOT EXISTS idx_enforcement_program_name_hint
    ON enforcement_cases(program_name_hint);
CREATE INDEX IF NOT EXISTS idx_enforcement_houjin_bangou
    ON enforcement_cases(recipient_houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_enforcement_prefecture
    ON enforcement_cases(prefecture);
CREATE INDEX IF NOT EXISTS idx_enforcement_legal_basis
    ON enforcement_cases(legal_basis);
CREATE INDEX IF NOT EXISTS idx_enforcement_disclosed_date
    ON enforcement_cases(disclosed_date);
-- migration 056 P0/P1 indexes
CREATE INDEX IF NOT EXISTS idx_enforcement_ministry
    ON enforcement_cases(ministry);
CREATE INDEX IF NOT EXISTS idx_enforcement_disclosed_desc
    ON enforcement_cases(disclosed_date DESC, case_id);

CREATE TABLE IF NOT EXISTS new_program_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_name TEXT NOT NULL,
    mentioned_in TEXT,
    ministry TEXT,
    budget_yen INTEGER,
    program_kind_hint TEXT,
    expected_start TEXT,
    policy_background_excerpt TEXT,
    source_url TEXT,
    source_pdf_page TEXT,
    fetched_at TEXT,
    confidence REAL,
    UNIQUE(candidate_name, source_url)
);

CREATE INDEX IF NOT EXISTS idx_new_program_candidates_name
    ON new_program_candidates(candidate_name);
CREATE INDEX IF NOT EXISTS idx_new_program_candidates_ministry
    ON new_program_candidates(ministry);

CREATE TABLE IF NOT EXISTS loan_programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_name TEXT NOT NULL,
    provider TEXT,
    loan_type TEXT,
    amount_max_yen INTEGER,
    loan_period_years_max INTEGER,
    grace_period_years_max INTEGER,
    interest_rate_base_annual REAL,
    interest_rate_special_annual REAL,
    rate_names TEXT,
    security_required TEXT,
    target_conditions TEXT,
    official_url TEXT,
    source_excerpt TEXT,
    fetched_at TEXT,
    confidence REAL,
    -- 013_loan_risk_structure.sql: three orthogonal risk axes.
    -- Values: 'required' | 'not_required' | 'negotiable' | 'unknown'.
    collateral_required TEXT,
    personal_guarantor_required TEXT,
    third_party_guarantor_required TEXT,
    security_notes TEXT,
    UNIQUE(program_name, provider)
);

CREATE INDEX IF NOT EXISTS idx_loan_programs_program_name
    ON loan_programs(program_name);
CREATE INDEX IF NOT EXISTS idx_loan_programs_provider
    ON loan_programs(provider);
-- migration 056 P1 composite sort index
CREATE INDEX IF NOT EXISTS idx_loan_programs_amount_desc
    ON loan_programs(amount_max_yen DESC, id);
-- Indexes on the 013 risk-axis columns are created by migration
-- 013_loan_risk_structure.sql so they can reference columns that only
-- exist after the migration's ALTER TABLE has run. On fresh volumes
-- the migration still executes after this schema.sql pass, so the
-- final shape is identical.

-- ---------------------------------------------------------------------------
-- 012_case_law.sql: courts.go.jp 判例 (judicial rulings). Mirrored here so
-- fresh volumes end up with the final shape. `confidence` is TEXT (values
-- like "high"/"medium") because courts.go.jp exposes no numeric score —
-- differs from the REAL confidence used in the 011 tables.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS case_law (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_name TEXT NOT NULL,
    court TEXT,
    decision_date TEXT,
    case_number TEXT,
    subject_area TEXT,
    key_ruling TEXT,
    parties_involved TEXT,
    impact_on_business TEXT,
    source_url TEXT,
    source_excerpt TEXT,
    confidence TEXT,
    pdf_url TEXT,
    category TEXT,
    fetched_at TEXT,
    UNIQUE(case_number, court)
);

CREATE INDEX IF NOT EXISTS idx_case_law_court ON case_law(court);
CREATE INDEX IF NOT EXISTS idx_case_law_subject_area ON case_law(subject_area);
CREATE INDEX IF NOT EXISTS idx_case_law_decision_date ON case_law(decision_date);
CREATE INDEX IF NOT EXISTS idx_case_law_category ON case_law(category);

-- ---------------------------------------------------------------------------
-- 014_business_intelligence_layer.sql: houjin-pivoted join hub across 6 new
-- datasets + materialized peer-density view + row-level lineage audit.
-- Canonical mirror so fresh volumes end up with the final shape before the
-- numbered migration file runs. Source: scripts/migrations/014_*.sql.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS houjin_master (
    houjin_bangou TEXT PRIMARY KEY,
    normalized_name TEXT NOT NULL,
    alternative_names_json TEXT,
    address_normalized TEXT,
    prefecture TEXT,
    municipality TEXT,
    corporation_type TEXT,
    established_date TEXT,
    close_date TEXT,
    last_updated_nta TEXT,
    data_sources_json TEXT,
    total_adoptions INTEGER NOT NULL DEFAULT 0,
    total_received_yen INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_houjin_name
    ON houjin_master(normalized_name);
CREATE INDEX IF NOT EXISTS idx_houjin_prefecture
    ON houjin_master(prefecture, municipality);
CREATE INDEX IF NOT EXISTS idx_houjin_ctype
    ON houjin_master(corporation_type);
CREATE INDEX IF NOT EXISTS idx_houjin_active
    ON houjin_master(close_date) WHERE close_date IS NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS houjin_master_fts USING fts5(
    houjin_bangou UNINDEXED,
    normalized_name,
    alternative_names,
    address,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS adoption_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou TEXT NOT NULL,
    program_id_hint TEXT,
    program_name_raw TEXT,
    company_name_raw TEXT,
    round_label TEXT,
    round_number INTEGER,
    announced_at TEXT,
    prefecture TEXT,
    municipality TEXT,
    project_title TEXT,
    industry_raw TEXT,
    industry_jsic_medium TEXT,
    amount_granted_yen INTEGER,
    amount_project_total_yen INTEGER,
    source_url TEXT NOT NULL,
    source_pdf_page TEXT,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.85,
    FOREIGN KEY (houjin_bangou)
        REFERENCES houjin_master(houjin_bangou) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_adoption_houjin
    ON adoption_records(houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_adoption_program_hint
    ON adoption_records(program_id_hint);
CREATE INDEX IF NOT EXISTS idx_adoption_jsic_pref
    ON adoption_records(industry_jsic_medium, prefecture);
CREATE INDEX IF NOT EXISTS idx_adoption_announced
    ON adoption_records(announced_at);
CREATE INDEX IF NOT EXISTS idx_adoption_round
    ON adoption_records(program_id_hint, round_number);

CREATE VIRTUAL TABLE IF NOT EXISTS adoption_fts USING fts5(
    record_id UNINDEXED,
    project_title,
    industry_raw,
    company_name_raw,
    program_name_raw,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS industry_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statistic_source TEXT NOT NULL,
    statistic_year INTEGER,
    jsic_code_large TEXT,
    jsic_name_large TEXT,
    jsic_code_medium TEXT,
    jsic_name_medium TEXT,
    prefecture TEXT,
    area_code TEXT,
    area_type TEXT,
    scale_code TEXT,
    scale_employees_bucket TEXT,
    org_type TEXT,
    establishment_count INTEGER,
    employee_count_total INTEGER,
    employee_count_male INTEGER,
    employee_count_female INTEGER,
    regular_employee_total INTEGER,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.95,
    UNIQUE(statistic_source, statistic_year, jsic_code_medium, prefecture, area_code, scale_code, org_type)
);

CREATE INDEX IF NOT EXISTS idx_industry_stats_jsic_pref
    ON industry_stats(jsic_code_medium, prefecture, scale_code);
CREATE INDEX IF NOT EXISTS idx_industry_stats_year
    ON industry_stats(statistic_year);
CREATE INDEX IF NOT EXISTS idx_industry_stats_large
    ON industry_stats(jsic_code_large, prefecture);

CREATE TABLE IF NOT EXISTS support_org (
    org_id TEXT PRIMARY KEY,
    org_type TEXT NOT NULL,
    org_name TEXT NOT NULL,
    houjin_bangou TEXT,
    prefecture TEXT,
    municipality TEXT,
    services_json TEXT,
    specialties_json TEXT,
    registration_date TEXT,
    registration_expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    contact_url TEXT,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.9
);

CREATE INDEX IF NOT EXISTS idx_support_org_type
    ON support_org(org_type, status);
CREATE INDEX IF NOT EXISTS idx_support_org_pref
    ON support_org(prefecture, org_type);
CREATE INDEX IF NOT EXISTS idx_support_org_houjin
    ON support_org(houjin_bangou) WHERE houjin_bangou IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_support_org_active
    ON support_org(status, prefecture) WHERE status = 'active';

CREATE VIRTUAL TABLE IF NOT EXISTS support_org_fts USING fts5(
    org_id UNINDEXED,
    org_name,
    services,
    specialties,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS ministry_faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_name_hint TEXT,
    ministry TEXT,
    category TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_section TEXT,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.92,
    UNIQUE(program_name_hint, question)
);

CREATE INDEX IF NOT EXISTS idx_faq_program_hint
    ON ministry_faq(program_name_hint);
CREATE INDEX IF NOT EXISTS idx_faq_ministry_cat
    ON ministry_faq(ministry, category);

CREATE VIRTUAL TABLE IF NOT EXISTS ministry_faq_fts USING fts5(
    faq_id UNINDEXED,
    question,
    answer,
    category,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS verticals_deep (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical_code TEXT NOT NULL,
    vertical_label TEXT NOT NULL,
    wave_number INTEGER,
    record_type TEXT NOT NULL,
    record_title TEXT NOT NULL,
    record_summary TEXT,
    ministry TEXT,
    prefecture TEXT,
    program_id_hint TEXT,
    effective_from TEXT,
    effective_until TEXT,
    source_url TEXT NOT NULL,
    source_excerpt TEXT,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.88
);

CREATE INDEX IF NOT EXISTS idx_verticals_code
    ON verticals_deep(vertical_code);
CREATE INDEX IF NOT EXISTS idx_verticals_type
    ON verticals_deep(record_type, ministry);
CREATE INDEX IF NOT EXISTS idx_verticals_program
    ON verticals_deep(program_id_hint) WHERE program_id_hint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_verticals_wave
    ON verticals_deep(wave_number, vertical_code);

CREATE VIRTUAL TABLE IF NOT EXISTS verticals_deep_fts USING fts5(
    vertical_id UNINDEXED,
    vertical_label,
    record_title,
    record_summary,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS industry_program_density (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jsic_code_medium TEXT NOT NULL,
    prefecture TEXT NOT NULL,
    program_id TEXT NOT NULL,
    peer_count INTEGER NOT NULL,
    total_granted_yen INTEGER,
    avg_granted_yen INTEGER,
    stddev_granted_yen REAL,
    min_granted_yen INTEGER,
    max_granted_yen INTEGER,
    latest_announced_at TEXT,
    last_refreshed_at TEXT NOT NULL,
    UNIQUE(jsic_code_medium, prefecture, program_id)
);

CREATE INDEX IF NOT EXISTS idx_density_program
    ON industry_program_density(program_id);
CREATE INDEX IF NOT EXISTS idx_density_peer_count
    ON industry_program_density(peer_count DESC);
CREATE INDEX IF NOT EXISTS idx_density_segment
    ON industry_program_density(jsic_code_medium, prefecture, peer_count DESC);

CREATE TABLE IF NOT EXISTS source_lineage_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_key TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    primary_source INTEGER NOT NULL DEFAULT 1,
    audited_at TEXT,
    audit_status TEXT NOT NULL DEFAULT 'unaudited',
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_lineage_table_row
    ON source_lineage_audit(table_name, row_key);
CREATE INDEX IF NOT EXISTS idx_lineage_domain
    ON source_lineage_audit(source_domain, primary_source);
CREATE INDEX IF NOT EXISTS idx_lineage_flag
    ON source_lineage_audit(audit_status)
    WHERE audit_status != 'clean';

-- ---------------------------------------------------------------------------
-- === Laws catalog (mirrored from migration 015_laws.sql, 2026-04-24) ===
-- 015_laws.sql: e-Gov 法令 API V2 (CC-BY 4.0) ingestion target. Mirrored
-- here so fresh volumes end up with the final shape before the numbered
-- migration file runs. Re-applying 015 is a no-op (CREATE IF NOT EXISTS).
-- Source: scripts/migrations/015_laws.sql.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS laws (
    unified_id TEXT PRIMARY KEY,              -- LAW-<10 lowercase hex>
    law_number TEXT NOT NULL,                 -- 昭和三十八年法律第百四十七号 / 令和六年政令第X号
    law_title TEXT NOT NULL,                  -- 正式名称
    law_short_title TEXT,                     -- 略称 / 略語
    law_type TEXT NOT NULL,                   -- 'constitution' | 'act' | 'cabinet_order'
                                              -- | 'imperial_order' | 'ministerial_ordinance'
                                              -- | 'rule' | 'notice' | 'guideline'
    ministry TEXT,                            -- 所管府省
    promulgated_date TEXT,                    -- ISO 8601 (公布日)
    enforced_date TEXT,                       -- ISO 8601 (施行日, may differ from promulgated)
    last_amended_date TEXT,                   -- ISO 8601
    revision_status TEXT NOT NULL DEFAULT 'current',  -- 'current' | 'superseded' | 'repealed'
    superseded_by_law_id TEXT,                -- self-FK (current 法令 that replaced this one)
    article_count INTEGER,                    -- 条文数
    full_text_url TEXT,                       -- e-Gov 法令検索 permalink (for humans)
    summary TEXT,                             -- 2-3 line abstract (for LLM retrieval)
    subject_areas_json TEXT,                  -- JSON list[str]: ['subsidy_clawback','tax_credit',...]
    source_url TEXT NOT NULL,                 -- primary source (e-Gov preferred)
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.95,    -- 0..1, matches 011/014 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'LAW-'),
    CHECK(revision_status IN ('current','superseded','repealed')),
    FOREIGN KEY(superseded_by_law_id) REFERENCES laws(unified_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_laws_ministry ON laws(ministry);
CREATE INDEX IF NOT EXISTS idx_laws_type ON laws(law_type, revision_status);
CREATE INDEX IF NOT EXISTS idx_laws_enforced ON laws(enforced_date);
CREATE INDEX IF NOT EXISTS idx_laws_number ON laws(law_number);
CREATE INDEX IF NOT EXISTS idx_laws_current
    ON laws(law_type) WHERE revision_status = 'current';

-- laws_fts — trigram FTS mirror for search_laws. Same tokenizer as
-- programs_fts; single-kanji false-positive gotcha applies (see CLAUDE.md).
CREATE VIRTUAL TABLE IF NOT EXISTS laws_fts USING fts5(
    unified_id UNINDEXED,
    law_title,
    law_short_title,
    law_number,
    summary,
    tokenize='trigram'
);

-- program_law_refs — N:M linkage programs ⇌ laws. Programs CASCADE on
-- delete (orphan refs are meaningless); laws RESTRICT (revision flows via
-- superseded_by_law_id, not deletion).
CREATE TABLE IF NOT EXISTS program_law_refs (
    program_unified_id TEXT NOT NULL,         -- programs.unified_id (UNI-*)
    law_unified_id TEXT NOT NULL,             -- laws.unified_id (LAW-*)
    ref_kind TEXT NOT NULL,                   -- 'authority' (根拠) | 'eligibility'
                                              -- | 'exclusion' | 'reference' | 'penalty'
    article_citation TEXT,                    -- '第5条第2項' etc. — empty string if whole-law
    source_url TEXT NOT NULL,                 -- where we learned the ref (program page / 要綱 PDF)
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC
    confidence REAL NOT NULL DEFAULT 0.9,
    PRIMARY KEY(program_unified_id, law_unified_id, ref_kind, article_citation),
    CHECK(ref_kind IN ('authority','eligibility','exclusion','reference','penalty')),
    FOREIGN KEY(program_unified_id) REFERENCES programs(unified_id) ON DELETE CASCADE,
    FOREIGN KEY(law_unified_id)     REFERENCES laws(unified_id)     ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_plr_law ON program_law_refs(law_unified_id);
CREATE INDEX IF NOT EXISTS idx_plr_kind ON program_law_refs(ref_kind);
CREATE INDEX IF NOT EXISTS idx_plr_fetched ON program_law_refs(fetched_at);

-- ---------------------------------------------------------------------------
-- === Court decisions catalog (mirrored from migration 016_court_decisions.sql, 2026-04-24) ===
-- 016_court_decisions.sql: courts.go.jp hanrei_jp 判例 catalog (supersets 012
-- case_law). Adds `court_decisions` with HAN-<10 hex> unified_id, trigram FTS
-- mirror, `enforcement_decision_refs` N:M linkage to 011 enforcement_cases,
-- and backward-compat `case_law_v2` view. Mirrored here so fresh volumes end
-- up with the final shape before the numbered migration file runs. Source:
-- scripts/migrations/016_court_decisions.sql.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS court_decisions (
    unified_id TEXT PRIMARY KEY,              -- HAN-<10 lowercase hex>
    case_name TEXT NOT NULL,                  -- 事件名 (e.g., 所得税更正処分取消請求事件)
    case_number TEXT,                         -- 平成29年(行ヒ)第123号 / 令和5年(受)第456号
    court TEXT,                               -- 裁判所名 (最高裁判所第三小法廷 / 東京地方裁判所 etc.)
    court_level TEXT NOT NULL,                -- 'supreme' | 'high' | 'district' | 'summary' | 'family'
    decision_date TEXT,                       -- ISO 8601 (言渡日)
    decision_type TEXT NOT NULL,              -- '判決' | '決定' | '命令'
    subject_area TEXT,                        -- '租税' / '行政' / '補助金適正化法' / ...
    related_law_ids_json TEXT,                -- JSON list[str]: ['LAW-...','LAW-...']
    key_ruling TEXT,                          -- 判示事項の要約 (2-5 lines)
    parties_involved TEXT,                    -- 当事者 (概要・匿名化後)
    impact_on_business TEXT,                  -- 実務影響 (LLM retrieval-friendly summary)
    precedent_weight TEXT NOT NULL DEFAULT 'informational',
                                              -- 先例価値:
                                              --   'binding'       = 最高裁 or 大法廷
                                              --   'persuasive'    = 高裁・地裁のリーディングケース
                                              --   'informational' = 事例参考
    full_text_url TEXT,                       -- courts.go.jp hanrei_jp permalink
    pdf_url TEXT,                             -- 全文 PDF ミラー
    source_url TEXT NOT NULL,                 -- primary source (courts.go.jp required)
    source_excerpt TEXT,                      -- 原文抜粋 (引用根拠用)
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.9,     -- 0..1, matches 014/015 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'HAN-'),
    CHECK(court_level IN ('supreme','high','district','summary','family')),
    CHECK(decision_type IN ('判決','決定','命令')),
    CHECK(precedent_weight IN ('binding','persuasive','informational')),
    UNIQUE(case_number, court)
);

CREATE INDEX IF NOT EXISTS idx_court_decisions_court_level
    ON court_decisions(court_level);
CREATE INDEX IF NOT EXISTS idx_court_decisions_subject_area
    ON court_decisions(subject_area);
CREATE INDEX IF NOT EXISTS idx_court_decisions_decision_date
    ON court_decisions(decision_date);
CREATE INDEX IF NOT EXISTS idx_court_decisions_weight
    ON court_decisions(precedent_weight, court_level);
CREATE INDEX IF NOT EXISTS idx_court_decisions_type
    ON court_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_court_decisions_binding
    ON court_decisions(subject_area) WHERE precedent_weight = 'binding';

-- court_decisions_fts — trigram FTS mirror for search_court_decisions. Same
-- tokenizer as programs_fts / laws_fts; single-kanji false-positive gotcha
-- applies (see CLAUDE.md).
CREATE VIRTUAL TABLE IF NOT EXISTS court_decisions_fts USING fts5(
    unified_id UNINDEXED,
    case_name,
    subject_area,
    key_ruling,
    impact_on_business,
    tokenize='trigram'
);

-- enforcement_decision_refs — N:M linkage enforcement_cases ⇌ court_decisions.
-- enforcement_cases CASCADE on delete (orphan refs are noise); court_decisions
-- RESTRICT (rulings are persistent jurisprudence).
CREATE TABLE IF NOT EXISTS enforcement_decision_refs (
    enforcement_case_id TEXT NOT NULL,        -- enforcement_cases.case_id
    decision_unified_id TEXT NOT NULL,        -- court_decisions.unified_id (HAN-*)
    ref_kind TEXT NOT NULL,                   -- 'direct' | 'related' | 'precedent'
    source_url TEXT,                          -- where we learned the ref (judgment / 検査報告)
    fetched_at TEXT,                          -- ISO 8601 UTC
    PRIMARY KEY(enforcement_case_id, decision_unified_id, ref_kind),
    CHECK(ref_kind IN ('direct','related','precedent')),
    FOREIGN KEY(enforcement_case_id)
        REFERENCES enforcement_cases(case_id) ON DELETE CASCADE,
    FOREIGN KEY(decision_unified_id)
        REFERENCES court_decisions(unified_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_edr_decision
    ON enforcement_decision_refs(decision_unified_id);
CREATE INDEX IF NOT EXISTS idx_edr_kind
    ON enforcement_decision_refs(ref_kind);
CREATE INDEX IF NOT EXISTS idx_edr_fetched
    ON enforcement_decision_refs(fetched_at);

-- case_law_v2 — backward-compat projection over court_decisions in the 012
-- case_law column shape. Lets new readers target the view so the physical
-- `case_law` table can be dropped later without breaking them.
CREATE VIEW IF NOT EXISTS case_law_v2 AS
SELECT
    unified_id            AS unified_id,
    case_name             AS case_name,
    court                 AS court,
    decision_date         AS decision_date,
    case_number           AS case_number,
    subject_area          AS subject_area,
    key_ruling            AS key_ruling,
    parties_involved      AS parties_involved,
    impact_on_business    AS impact_on_business,
    source_url            AS source_url,
    source_excerpt        AS source_excerpt,
    confidence            AS confidence,
    pdf_url               AS pdf_url,
    subject_area          AS category,
    fetched_at            AS fetched_at
FROM court_decisions;

-- ---------------------------------------------------------------------------
-- === Bids catalog (mirrored from migration 017_bids.sql, 2026-04-24) ===
-- 017_bids.sql: 入札 (public procurement) catalog sourced from GEPS
-- (p-portal.go.jp) + self-gov top-7 JV + ministry procurement pages. Uses
-- BID-<10 hex> unified_id and trigram FTS mirror. Soft refs only on
-- procuring_houjin_bangou / program_id_hint (no hard FK). Mirrored here so
-- fresh volumes end up with the final shape before the numbered migration
-- file runs. Source: scripts/migrations/017_bids.sql.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bids (
    unified_id TEXT PRIMARY KEY,              -- BID-<10 lowercase hex>
    bid_title TEXT NOT NULL,                  -- 案件名
    bid_kind TEXT NOT NULL,                   -- 'open' (一般競争) | 'selective' (指名競争)
                                              -- | 'negotiated' (随意契約) | 'kobo_subsidy' (公募型補助)
    procuring_entity TEXT NOT NULL,           -- 発注機関名 (e.g. 国土交通省関東地方整備局)
    procuring_houjin_bangou TEXT,             -- 13-digit 法人番号 (soft ref; NO FK to houjin_master)
    ministry TEXT,                            -- 所管府省 (national procurements)
    prefecture TEXT,                          -- 都道府県 (self-gov procurements / 地方整備局)
    program_id_hint TEXT,                     -- programs.unified_id (soft ref; NO FK)
    announcement_date TEXT,                   -- ISO 8601 公告日
    question_deadline TEXT,                   -- ISO 8601 質問受付期限
    bid_deadline TEXT,                        -- ISO 8601 入札書提出期限
    decision_date TEXT,                       -- ISO 8601 落札決定日
    budget_ceiling_yen INTEGER,               -- 予定価格 / 契約限度額 (税込 if disclosed)
    awarded_amount_yen INTEGER,               -- 落札金額 (税込 if disclosed)
    winner_name TEXT,                         -- 落札者名 (as published)
    winner_houjin_bangou TEXT,                -- 落札者 法人番号 (soft ref; NO FK)
    participant_count INTEGER,                -- 入札参加者数
    bid_description TEXT,                     -- 調達概要 / 仕様要旨
    eligibility_conditions TEXT,              -- 参加資格要件 (等級 / 所在地 / 実績 etc.)
    classification_code TEXT,                 -- '役務' | '物品' | '工事' (or finer JGS code)
    source_url TEXT NOT NULL,                 -- primary source (GEPS / ministry / *.lg.jp)
    source_excerpt TEXT,                      -- relevant passage for audit
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.9,     -- 0..1, matches 014/015 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'BID-'),
    CHECK(bid_kind IN ('open','selective','negotiated','kobo_subsidy'))
);

CREATE INDEX IF NOT EXISTS idx_bids_procuring_entity
    ON bids(procuring_entity);
CREATE INDEX IF NOT EXISTS idx_bids_deadline
    ON bids(bid_deadline);
CREATE INDEX IF NOT EXISTS idx_bids_ministry_pref
    ON bids(ministry, prefecture);
CREATE INDEX IF NOT EXISTS idx_bids_winner_houjin
    ON bids(winner_houjin_bangou) WHERE winner_houjin_bangou IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bids_program_hint
    ON bids(program_id_hint) WHERE program_id_hint IS NOT NULL;

-- bids_fts — trigram FTS mirror for search_bids. Same tokenizer as
-- programs_fts / laws_fts; single-kanji false-positive gotcha applies
-- (see CLAUDE.md).
CREATE VIRTUAL TABLE IF NOT EXISTS bids_fts USING fts5(
    unified_id UNINDEXED,
    bid_title,
    bid_description,
    procuring_entity,
    winner_name,
    tokenize='trigram'
);

-- ---------------------------------------------------------------------------
-- === Tax rulesets catalog (mirrored from migration 018_tax_rulesets.sql, 2026-04-24) ===
-- 018_tax_rulesets.sql: 税務判定ルールセット sourced from 国税庁 タックスアンサー
-- / 一問一答 / インボイス Q&A. Uses TAX-<10 hex> unified_id and trigram FTS
-- mirror. Narrative `eligibility_conditions` for humans + structured
-- `eligibility_conditions_json` predicates for the judgment engine.
-- Mirrored here so fresh volumes end up with the final shape before the
-- numbered migration file runs. Source: scripts/migrations/018_tax_rulesets.sql.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tax_rulesets (
    unified_id TEXT PRIMARY KEY,              -- TAX-<10 lowercase hex>
    ruleset_name TEXT NOT NULL,               -- '適格請求書発行事業者登録', '2割特例', '住宅ローン控除' ...
    tax_category TEXT NOT NULL,               -- 'consumption' | 'corporate' | 'income'
                                              -- | 'property' | 'local' | 'inheritance'
    ruleset_kind TEXT NOT NULL,               -- 'registration' | 'credit' | 'deduction'
                                              -- | 'special_depreciation' | 'exemption'
                                              -- | 'preservation' | 'other'
    effective_from TEXT NOT NULL,             -- ISO 8601 (施行日)
    effective_until TEXT,                     -- ISO 8601, NULL = 現行 (無期限)
                                              -- Cliff dates to flag:
                                              --   2026-09-30 (2割特例 終了)
                                              --   2027-09-30 (80% 経過措置 終了)
                                              --   2029-09-30 (50% 経過措置 / 少額特例 終了)
    related_law_ids_json TEXT,                -- JSON list[str]: ['LAW-xxxxxxxxxx', ...]
    eligibility_conditions TEXT,              -- narrative (for humans / LLM retrieval)
    eligibility_conditions_json TEXT,         -- structured predicates for judgment engine
                                              --   e.g. [{"op":"AND","terms":[
                                              --     {"field":"annual_revenue_yen","cmp":"<=","val":10000000},
                                              --     {"field":"business_type","cmp":"in","val":["sole_prop","corp"]}
                                              --   ]}]
    rate_or_amount TEXT,                      -- '10%' / '¥400,000 上限' / '控除率 2%' ...
    calculation_formula TEXT,                 -- '課税売上高 × 0.8 × 税率' etc.
    filing_requirements TEXT,                 -- 届出書式 / 提出先 / 期限 narrative
    authority TEXT NOT NULL,                  -- '国税庁' | '財務省' | '地方税' (e.g. 総務省 / 都道府県税事務所)
    authority_url TEXT,                       -- authority's landing page
    source_url TEXT NOT NULL,                 -- primary source (whitelist: nta/mof/e-Gov)
    source_excerpt TEXT,                      -- raw Q&A text / 通達抜粋 (≤2,000 chars)
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.92,    -- 0..1, matches 011/014/015 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'TAX-'),
    CHECK(tax_category IN ('consumption','corporate','income','property','local','inheritance')),
    CHECK(ruleset_kind IN ('registration','credit','deduction','special_depreciation','exemption','preservation','other'))
);

CREATE INDEX IF NOT EXISTS idx_tax_category_kind
    ON tax_rulesets(tax_category, ruleset_kind);
CREATE INDEX IF NOT EXISTS idx_tax_effective
    ON tax_rulesets(effective_from, effective_until);
CREATE INDEX IF NOT EXISTS idx_tax_authority
    ON tax_rulesets(authority);

-- tax_rulesets_fts — trigram FTS mirror for search_tax_rulesets. Same
-- tokenizer as programs_fts / laws_fts; single-kanji false-positive gotcha
-- applies (see CLAUDE.md).
CREATE VIRTUAL TABLE IF NOT EXISTS tax_rulesets_fts USING fts5(
    unified_id UNINDEXED,
    ruleset_name,
    eligibility_conditions,
    calculation_formula,
    tokenize='trigram'
);

-- ---------------------------------------------------------------------------
-- === Invoice registrants catalog (mirrored from migration 019_invoice_registrants.sql, 2026-04-24) ===
-- 019_invoice_registrants.sql: 適格請求書発行事業者 master from 国税庁 bulk
-- download (PDL v1.0; commercial redistribution OK with 出典明記 + 編集加工
-- 注記 — see src/jpintel_mcp/api/attribution.py). PRIMARY KEY is the T-prefix
-- invoice_registration_number (not houjin_bangou — sole proprietors often
-- lack one). Mirrored here so fresh volumes end up with the final shape
-- before the numbered migration file runs. Source:
-- scripts/migrations/019_invoice_registrants.sql.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS invoice_registrants (
    invoice_registration_number TEXT PRIMARY KEY,  -- 'T' + 13 digits (14 chars total)
    houjin_bangou TEXT,                            -- 13 digits; NULL for sole proprietors / other
    normalized_name TEXT NOT NULL,                 -- 事業者名 (公表名称)
    address_normalized TEXT,                       -- 所在地 (normalized)
    prefecture TEXT,                               -- 都道府県
    registered_date TEXT NOT NULL,                 -- 登録日 (ISO 8601)
    revoked_date TEXT,                             -- 取消日 (NULL = 未取消)
    expired_date TEXT,                             -- 失効日 (NULL = 未失効)
    registrant_kind TEXT NOT NULL,                 -- 'corporation' | 'sole_proprietor' | 'other'
    trade_name TEXT,                               -- 屋号等 (nullable)
    last_updated_nta TEXT,                         -- NTA's timestamp on this record
    source_url TEXT NOT NULL,                      -- https://www.invoice-kohyo.nta.go.jp/download/...
    source_checksum TEXT,                          -- optional SHA-256 of raw bulk file
    confidence REAL NOT NULL DEFAULT 0.98,         -- 一次公表 → high
    fetched_at TEXT NOT NULL,                      -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                      -- ISO 8601 UTC of last row write
    CHECK(length(invoice_registration_number) = 14
          AND substr(invoice_registration_number, 1, 1) = 'T'),
    CHECK(registrant_kind IN ('corporation', 'sole_proprietor', 'other'))
    -- NOTE: No hard FOREIGN KEY on houjin_bangou. Soft reference only —
    -- individual sole_proprietors often have no houjin_bangou. The join
    -- to houjin_master (migration 014) is performed at query time.
);

-- Partial index on houjin_bangou: large chunk of rows are NULL (sole props),
-- partial index keeps size down and still accelerates join to houjin_master.
CREATE INDEX IF NOT EXISTS idx_invoice_registrants_houjin
    ON invoice_registrants(houjin_bangou) WHERE houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_name
    ON invoice_registrants(normalized_name);

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_prefecture
    ON invoice_registrants(prefecture);

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_registered
    ON invoice_registrants(registered_date);

-- "Currently active" queries: WHERE revoked_date IS NULL AND expired_date IS NULL.
-- Composite index supports both the filter and ordering by registration date.
CREATE INDEX IF NOT EXISTS idx_invoice_registrants_active
    ON invoice_registrants(revoked_date, expired_date);

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_kind
    ON invoice_registrants(registrant_kind);

-- ============================================================================
-- device_codes (023_device_codes migration; duplicated here so init_db()
-- on a fresh test/dev DB gets the table without running migrations separately)
-- ============================================================================
CREATE TABLE IF NOT EXISTS device_codes (
    device_code TEXT PRIMARY KEY,
    user_code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    client_fingerprint TEXT,
    scope TEXT DEFAULT 'api:read api:metered',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    poll_interval_sec INTEGER NOT NULL DEFAULT 5,
    last_polled_at TEXT,
    activated_at TEXT,
    linked_api_key_id TEXT,
    verification_uri TEXT NOT NULL,
    verification_uri_complete TEXT NOT NULL,
    stripe_checkout_session_id TEXT,
    stripe_customer_id TEXT,
    raw_pickup TEXT,
    raw_pickup_consumed_at TEXT,
    CHECK(status IN ('pending','activated','expired','denied')),
    FOREIGN KEY(linked_api_key_id) REFERENCES api_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_device_codes_status ON device_codes(status);
CREATE INDEX IF NOT EXISTS idx_device_codes_user_code ON device_codes(user_code);
CREATE INDEX IF NOT EXISTS idx_device_codes_expires ON device_codes(expires_at);

-- ============================================================================
-- testimonials (041_testimonials migration; duplicated here so init_db()
-- on a fresh test/dev DB gets the table without running migrations separately)
-- ============================================================================
CREATE TABLE IF NOT EXISTS testimonials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash TEXT NOT NULL,
    audience TEXT NOT NULL CHECK (audience IN ('税理士','行政書士','SMB','VC','Dev')),
    text TEXT NOT NULL,
    name TEXT,
    organization TEXT,
    linkedin_url TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_testimonials_approved
    ON testimonials(approved_at)
    WHERE approved_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_testimonials_key_hash
    ON testimonials(api_key_hash);
CREATE INDEX IF NOT EXISTS idx_testimonials_pending
    ON testimonials(created_at)
    WHERE approved_at IS NULL;

-- ============================================================================
-- stripe_webhook_events (053_stripe_webhook_events migration; duplicated here
-- so init_db() on a fresh test/dev DB gets the table without running
-- migrations separately). Event-level dedup: every event["id"] Stripe
-- delivers gets one row. The webhook handler short-circuits on duplicate
-- event_id so retries cannot fire side-effects (welcome email, live retrieve)
-- twice. Stripe event ids are globally unique across livemode + testmode.
-- ============================================================================
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    livemode INTEGER NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_stripe_webhook_events_received_at
    ON stripe_webhook_events(received_at DESC);

-- ============================================================================
-- postmark_webhook_events (059_postmark_webhook_events migration; duplicated
-- here so init_db() on a fresh test/dev DB gets the table without running
-- migrations separately). Event-level dedup keyed on Postmark MessageID.
-- The webhook handler short-circuits on duplicate so retries cannot fire
-- _suppress side-effects twice (which would create stray subscriber rows /
-- thrash unsubscribed_at). audit: a9fd80e134b538a32 (2026-04-25).
-- ============================================================================
CREATE TABLE IF NOT EXISTS postmark_webhook_events (
  message_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,  -- bounce, spam_complaint, etc.
  received_at TEXT NOT NULL,
  processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_postmark_webhook_received
  ON postmark_webhook_events(received_at);

-- ============================================================================
-- audit_log (058_audit_log migration; duplicated here so init_db() on a
-- fresh test/dev DB gets the table without running migrations separately).
-- 不正アクセス禁止法 incident response baseline. P1 from API key rotation
-- audit (a4298e454aab2aa43, 2026-04-25): rotate_key + login + billing-portal
-- + cap-change had no forensic trail. Every row is one event; key_hash
-- columns hold sha256 hashes only — raw API keys never touch this table.
-- See src/jpintel_mcp/api/_audit_log.py::log_event for the helper.
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,  -- key_rotate, key_revoke, login, login_failed, billing_portal, cap_change
  key_hash TEXT,             -- old key hash (or current for non-rotation events)
  key_hash_new TEXT,         -- new key hash on rotate (NULL for other events)
  customer_id TEXT,
  ip TEXT,
  user_agent TEXT,
  metadata TEXT              -- JSON for event-specific fields
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_key_hash ON audit_log(key_hash);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type, ts DESC);

-- ============================================================================
-- advisory_locks (063_advisory_locks migration; duplicated here so init_db()
-- on a fresh test/dev DB gets the table without running migrations
-- separately). App-level advisory locks for SQLite keyed by TEXT, with TTL
-- so a crashed holder cannot wedge a key forever. See
-- src/jpintel_mcp/api/_advisory_lock.py for the helper.
-- audit: a23909ea8a7d67d64 (2026-04-25).
-- ============================================================================
CREATE TABLE IF NOT EXISTS advisory_locks (
    key TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    ttl_s INTEGER NOT NULL DEFAULT 30,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_advisory_locks_expires
    ON advisory_locks(expires_at);

-- ============================================================================
-- bg_task_queue (060_bg_task_queue migration; duplicated here so init_db()
-- on a fresh test/dev DB gets the table without running migrations
-- separately). Durable replacement for FastAPI BackgroundTasks: every
-- side-effect that used to ride add_task (welcome email, key-rotated
-- notice, Stripe status refresh, dunning email, Stripe usage sync) now
-- lands in this table on commit and is drained by the worker spawned in
-- main.py's lifespan. A SIGTERM between commit and execute no longer
-- drops the side-effect — the worker picks the row up after restart.
-- See src/jpintel_mcp/api/_bg_task_queue.py + _bg_task_worker.py.
-- audit: bg-task-durability (2026-04-25)
-- ============================================================================
CREATE TABLE IF NOT EXISTS bg_task_queue (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    dedup_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_bg_task_queue_pending
    ON bg_task_queue(status, next_attempt_at)
    WHERE status IN ('pending', 'processing');

CREATE INDEX IF NOT EXISTS idx_bg_task_queue_kind
    ON bg_task_queue(kind, created_at);

-- ============================================================================
-- appi_disclosure_requests (066_appi_disclosure_requests migration; duplicated
-- here so init_db() on a fresh test/dev DB gets the table without running
-- migrations separately). APPI §31 disclosure-request intake. Every row is
-- one request from a data subject; the operator processes it manually
-- within 14 days. No automatic disclosure — this table only records the
-- request + operator notification side-effect. See P4 audit 2026-04-25
-- and docs/_internal/privacy_appi_31.md.
-- ============================================================================
CREATE TABLE IF NOT EXISTS appi_disclosure_requests (
    request_id TEXT PRIMARY KEY,
    requester_email TEXT NOT NULL,
    requester_legal_name TEXT NOT NULL,
    target_houjin_bangou TEXT,
    identity_verification_method TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',
    processed_at TEXT,
    processed_by TEXT
);

CREATE INDEX IF NOT EXISTS ix_appi_disclosure_requests_received_at
    ON appi_disclosure_requests(received_at DESC);

CREATE INDEX IF NOT EXISTS ix_appi_disclosure_requests_status
    ON appi_disclosure_requests(status);

-- ============================================================================
-- appi_deletion_requests (068_appi_deletion_requests migration; duplicated
-- here so init_db() on a fresh test/dev DB gets the table without running
-- migrations separately). APPI §33 個人情報削除請求 intake — symmetrical
-- to §31 disclosure (above). Every row is one deletion request from a data
-- subject; the operator processes it manually within 30 days (§33-3 法定
-- 上限). No automatic deletion — this table only records the request +
-- operator notification side-effect plus the operator's processed
-- decision (deletion_completed_categories at processing time).
-- ============================================================================
CREATE TABLE IF NOT EXISTS appi_deletion_requests (
    request_id TEXT PRIMARY KEY,
    requester_email TEXT NOT NULL,
    requester_legal_name TEXT NOT NULL,
    target_houjin_bangou TEXT,
    target_data_categories TEXT NOT NULL,
    identity_verification_method TEXT NOT NULL,
    deletion_reason TEXT,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',
    processed_at TEXT,
    processed_by TEXT,
    deletion_completed_categories TEXT
);

CREATE INDEX IF NOT EXISTS ix_appi_del_received
    ON appi_deletion_requests(received_at);

CREATE INDEX IF NOT EXISTS ix_appi_del_status
    ON appi_deletion_requests(status);

-- ============================================================================
-- refund_requests + stripe_tax_cache (071_stripe_edge_cases migration;
-- duplicated here so init_db() on a fresh test/dev DB gets the tables
-- without running migrations separately).
--
-- refund_requests: customer-initiated refund intake. Manual review only —
--   we never auto-refund. Mirrors the §31 / §33 APPI intake pattern. Memory
--   `feedback_autonomath_no_api_use` requires already-billed ¥3/req metering
--   stay billed until manual review completes.
--
-- stripe_tax_cache: last successful Stripe Tax calculation per customer.
--   Used by `stripe_tax_with_fallback()` for graceful degrade when Stripe
--   Tax API returns 5xx. We never default to 0% (消費税法 §63 mis-issue
--   risk on the 適格請求書 per-rate table requirement).
-- ============================================================================
CREATE TABLE IF NOT EXISTS refund_requests (
    request_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    amount_yen INTEGER,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_refund_requests_received
    ON refund_requests(received_at DESC);

CREATE INDEX IF NOT EXISTS ix_refund_requests_status
    ON refund_requests(status);

CREATE INDEX IF NOT EXISTS ix_refund_requests_customer
    ON refund_requests(customer_id);

CREATE TABLE IF NOT EXISTS stripe_tax_cache (
    customer_id TEXT PRIMARY KEY,
    rate_bps INTEGER NOT NULL,
    jurisdiction TEXT NOT NULL DEFAULT 'JP',
    tax_amount_yen INTEGER,
    cached_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_stripe_tax_cache_cached_at
    ON stripe_tax_cache(cached_at DESC);

-- ============================================================================
-- email_unsubscribes (migration 072, P2.6.4 / 特電法 §3)
--   Master suppression list — checked BEFORE any broadcast / activation /
--   digest send. Transactional security mails (D+0 welcome with the
--   one-time API key, key_rotated, dunning) are exempt per §3-2 i and
--   stay suppressible only via the per-list flags. See
--   scripts/migrations/072_email_unsubscribes.sql for the full rationale.
-- ============================================================================
CREATE TABLE IF NOT EXISTS email_unsubscribes (
    email TEXT PRIMARY KEY,
    unsubscribed_at TEXT NOT NULL DEFAULT (datetime('now')),
    reason TEXT
);

-- ============================================================================
-- trial_signups (migration 076, conversion-pathway audit 2026-04-29)
--   Email-only trial signup. Magic-link verification → time-boxed
--   tier='trial' api_keys row (14 days, 200 reqs hard cap, no Stripe). The
--   trial is NOT a Free tier SKU; pricing stays ¥3/req metered post-trial.
--   See scripts/migrations/076_trial_signup.sql for the full rationale.
--
--   api_keys.trial_email / .trial_started_at / .trial_expires_at /
--   .trial_requests_used columns are added by ALTER TABLE in the migration
--   file; on a fresh schema.sql boot they are CREATE-d inline below by
--   re-stating the api_keys table, which is impossible without a CREATE OR
--   REPLACE. Instead, init_db() runs migrations on top of schema.sql so
--   the four columns land via the migration file's ALTER TABLE statements
--   (idempotent — `migrate.py` skips already-applied rows). Tests that
--   build a fresh DB hit init_db() which runs both the schema and the
--   migrations, so trial_* columns appear automatically.
-- ============================================================================
CREATE TABLE IF NOT EXISTS trial_signups (
    email TEXT NOT NULL,
    email_normalized TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_ip_hash TEXT,
    verified_at TEXT,
    issued_api_key_hash TEXT,
    FOREIGN KEY(issued_api_key_hash) REFERENCES api_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_trial_signups_ip_recent
    ON trial_signups(created_ip_hash, created_at);

CREATE INDEX IF NOT EXISTS idx_trial_signups_verified
    ON trial_signups(verified_at)
    WHERE verified_at IS NOT NULL;

-- Cron sweep: WHERE tier='trial' AND revoked_at IS NULL ORDER BY
-- trial_expires_at. Partial-index keeps scan cost ≈ open-trial count.
CREATE INDEX IF NOT EXISTS idx_api_keys_trial_expiry
    ON api_keys(trial_expires_at)
    WHERE tier = 'trial' AND revoked_at IS NULL;


-- ============================================================================
-- am_idempotency_cache (migration 087, anti-runaway 三点セット)
-- 24h replay cache for POST endpoints with Idempotency-Key. Mirrors the
-- migration so a fresh DB created via `init_db(schema.sql)` (e.g. tests
-- that don't run the migration runner) still has the table and replays
-- bulk_evaluate / batch endpoints correctly without "idem cache store
-- failed" warnings.
-- ============================================================================
CREATE TABLE IF NOT EXISTS am_idempotency_cache (
    cache_key       TEXT PRIMARY KEY,
    response_blob   TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_am_idempotency_cache_expires
    ON am_idempotency_cache(expires_at);
