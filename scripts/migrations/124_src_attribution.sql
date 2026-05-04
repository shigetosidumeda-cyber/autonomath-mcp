-- target_db: jpintel
-- migration 124_src_attribution
--
-- §4.6 (jpcite_ai_discovery_paid_adoption_plan_2026-05-04.md) — distribution
-- attribution recovery (organic-only). Add `src` column to both
-- analytics_events and funnel_events so we can split paid conversion by
-- the discovery channel that brought the visitor in.
--
-- §4.6 lists `src=` codes that get sprinkled across distribution surfaces:
--   * llms.txt           -> ?src=llmstxt
--   * cookbook recipes   -> ?src=cookbook_<slug>
--   * integrations/chatgpt -> ?src=chatgpt_actions
--   * integrations/openai-custom-gpt -> ?src=gpt_custom
--   * mcp-server.json install_url -> ?src=mcp_registry
--   * (other channels: claude_mcp, cursor_mcp, cline_mcp, hn_launch,
--     zenn_intro, outreach_firm_01)
--
-- The recorder middleware (api/middleware/analytics_recorder.py) extracts
-- `src` from the request query string, validates against a closed allowlist
-- (no free-text — keeps the table from being polluted by typos / spam),
-- and writes it to the new column. The funnel beacon (api/funnel_events.py)
-- accepts `src` either as part of the body properties or carried in the
-- page URL.
--
-- Posture:
--   * src is OPTIONAL — visitors arriving without ?src= write NULL
--     (treated as "direct/unknown" in the rollup).
--   * The classifier lives in code, not the DB, so adding new src codes
--     requires no schema change.
--   * Idempotent: ALTER TABLE ADD COLUMN raises "duplicate column" on
--     re-apply; entrypoint.sh + migrate.py both treat that as success.
--
-- Indexes:
--   * Partial index on `src IS NOT NULL` so the rollup never scans the
--     full analytics_events table just to compute per-src counts.
--   * Same for funnel_events.

-- ---- 1. analytics_events: add src column -----------------------------------
ALTER TABLE analytics_events ADD COLUMN src TEXT;

CREATE INDEX IF NOT EXISTS idx_analytics_events_src_ts
    ON analytics_events(src, ts DESC)
    WHERE src IS NOT NULL;

-- ---- 2. funnel_events: add src column --------------------------------------
ALTER TABLE funnel_events ADD COLUMN src TEXT;

CREATE INDEX IF NOT EXISTS idx_funnel_events_src_ts
    ON funnel_events(src, ts DESC)
    WHERE src IS NOT NULL;

-- ---- 3. Combined hot path for the §4.6 rollup ------------------------------
-- (src, event_name) ordered so the analytics_split endpoint can emit
-- "first_paid_within_7d_per_src" without a second pass.
CREATE INDEX IF NOT EXISTS idx_funnel_events_src_event_ts
    ON funnel_events(src, event_name, ts DESC)
    WHERE src IS NOT NULL AND is_bot = 0;
