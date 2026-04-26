-- Durable background-task queue
-- audit: bg-task-durability (2026-04-25)
--
-- FastAPI BackgroundTasks live in process memory: a SIGTERM (rolling deploy,
-- Fly machine replace, OOM) between enqueue and execute silently drops the
-- task. The welcome email contains the raw API key on first issuance, so a
-- lost welcome = paid customer never sees their key = 詐欺 / 景表法 risk.
-- This table backs `_bg_task_queue.py` + `_bg_task_worker.py` so the same
-- side-effects (welcome email, key-rotated notice, Stripe status refresh,
-- dunning email, Stripe usage sync) survive a process restart.
--
-- Design notes:
--   * `kind` is the dispatcher key (welcome_email / key_rotated_email /
--     stripe_status_refresh / dunning_email / stripe_usage_sync). The worker
--     dispatches by `kind` -> handler so adding a new task type does not
--     require a schema change.
--   * `payload_json` carries kwargs the handler needs (email recipient,
--     api_key, tier, etc.). Handlers must NOT trust DB rows that were
--     valid at enqueue time but might have rotated/revoked since (e.g.
--     re-fetch api_keys on dispatch when the lookup is cheap).
--   * `dedup_key` lets a caller make enqueue idempotent: a duplicate
--     Stripe webhook delivery already short-circuits via
--     stripe_webhook_events, but the per-task dedup is a second line of
--     defence (e.g. retry of `_send_welcome` for the same key_hash).
--   * Exponential backoff on retry: 60s * 2^attempts, cap 1h. After
--     `max_attempts` the row flips to status='failed' for operator review.

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

-- Hot path: claim_next() pulls the oldest due-and-pending row. Partial
-- index keeps it tiny even after months of completed-but-retained rows.
CREATE INDEX IF NOT EXISTS idx_bg_task_queue_pending
    ON bg_task_queue(status, next_attempt_at)
    WHERE status IN ('pending', 'processing');

-- Operator/forensic queries: "show me every welcome_email from last hour".
CREATE INDEX IF NOT EXISTS idx_bg_task_queue_kind
    ON bg_task_queue(kind, created_at);
