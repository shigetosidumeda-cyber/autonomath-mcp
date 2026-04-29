-- target_db: jpintel
-- 096_client_profiles.sql
-- Client profile registry for 補助金コンサル fan-out (navit cancel trigger #1).
--
-- Business context:
--   * 補助金コンサル / 認定支援機関 manage 50–200 顧問先 (clients). Today the
--     saved-search digest fires ONCE per saved_search row regardless of how
--     many 顧問先 the consultant covers — the consultant has to manually map
--     "did this digest item match my 顧問先 A or 顧問先 B?" out-of-band.
--   * `client_profiles` is the consultant's per-顧問先 metadata: business
--     classification (JSIC major), 都道府県, employee_count, capital_yen,
--     plus a target_types_json hint and a last_active_program_ids_json
--     "previously notable" cache. With this on file the cron can fan out
--     ONE saved_search × N profiles = N digests so each 顧問先 gets a
--     tailored result set.
--   * Each per-profile digest fires `report_usage_async` at ¥3 (matches the
--     existing saved_searches.digest billing path; project_autonomath_business_model).
--
-- Pricing impact:
--   * CRUD endpoints are FREE (POST bulk_import / GET / DELETE). They are
--     CRUD on the customer's own row tree, not metered surfaces.
--   * The saved_searches cron (097) joins profile_ids_json × client_profiles
--     so every per-profile fan-out is a separate ¥3 delivery. A consultant
--     with 200 顧問先 and one weekly saved_search fires ~200 deliveries per
--     week → ¥600 / week ≈ ¥2,600 / month. That is the "navit cancel"
--     break-even: the consultant pays MORE than navit's ¥1,000/月 only when
--     they have ≥40 顧問先 actively under navit-style monitoring.
--
-- Idempotency:
--   * `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`. Safe to
--     re-apply via `scripts/migrate.py` and entrypoint.sh self-heal loop.
--   * No DROP / ALTER paths.
--
-- DOWN:
--   `DROP TABLE client_profiles;` — no companion rollback file because the
--   table is forward-only customer data and the consultant can re-import
--   their CSV in seconds.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS client_profiles (
    profile_id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash                  TEXT NOT NULL,                  -- api_keys.key_hash (HMAC PK)
    name_label                    TEXT NOT NULL,                  -- consultant-facing label e.g. "○○商事"
    -- JSIC (日本標準産業分類) major code, e.g. 'E' = 製造業, 'I' = 卸売・小売.
    -- Free-text up to 4 chars to allow major+medium when the consultant
    -- knows it; the matcher only requires major prefix overlap.
    jsic_major                    TEXT,
    prefecture                    TEXT,                            -- '東京都' / '大阪府' / NULL = 全国
    employee_count                INTEGER,                         -- nullable, 中小企業判定用
    capital_yen                   INTEGER,                         -- nullable, 中小企業判定用
    -- JSON array of target_type tokens (e.g. ["製造業","設備投資"]). Mirrors
    -- programs.target_types_json so the matcher can OR-LIKE against the
    -- saved_search query verbatim.
    target_types_json             TEXT NOT NULL DEFAULT '[]',
    -- JSON array of unified_id strings the consultant has flagged as
    -- "this 顧問先 previously cared about / applied for". Used by the
    -- post_award trigger (098) to resolve which intentions still apply.
    last_active_program_ids_json  TEXT NOT NULL DEFAULT '[]',
    created_at                    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at                    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Per-consultant list query (`GET /v1/me/client_profiles`) hits this directly.
CREATE INDEX IF NOT EXISTS idx_client_profiles_key
    ON client_profiles(api_key_hash);

-- Bulk-import dedup probe: same name_label + same key_hash should be a
-- single row (consultant re-uploads a corrected CSV, we update in place).
CREATE INDEX IF NOT EXISTS idx_client_profiles_key_label
    ON client_profiles(api_key_hash, name_label);

-- Bookkeeping recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
