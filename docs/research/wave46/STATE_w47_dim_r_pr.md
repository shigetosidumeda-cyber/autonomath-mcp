# Wave 47 Dim R migration + federated MCP storage PR (W46 tick#4 loop)

date: 2026-05-12
branch: feat/jpcite_2026_05_12_wave47_dim_r_migration
PR#: TBD (open after push)

## Scope

Land the **storage substrate** behind Dim R (`federated_mcp_recommendation`,
per feedback_federated_mcp_recommendation). jpcite positions itself as
the agent **hub**: when a query exits its own answerable surface
(payroll transactions, calendar workflows, doc collaboration, code
review), the hub emits a curated handoff recommendation pointing the
agent at one of 6 partner MCP servers (freee / MoneyForward / Notion /
Slack / GitHub / Linear). The agent client then talks to the partner
MCP server directly — jpcite never proxies that traffic.

Wave 47 adds the **catalogue** (`am_federated_mcp_partner`) + **audit
log** (`am_handoff_log`) + a **6-partner seed ETL** without touching the
recommendation kernel or making any external MCP server call.

## Files added

| Path                                                       | LOC | Purpose                                       |
| ---------------------------------------------------------- | --- | --------------------------------------------- |
| `scripts/migrations/278_federated_mcp.sql`                 |  93 | `am_federated_mcp_partner` + `am_handoff_log` + 4 indices |
| `scripts/migrations/278_federated_mcp_rollback.sql`        |  18 | rollback (drop indices + tables)              |
| `scripts/etl/seed_federated_mcp_partners.py`               | 197 | 6 curated partner seed ETL                    |
| `tests/test_dim_r_federated_mcp.py`                        | 360 | 14 integration tests (mig + ETL + log + brand) |
| `scripts/migrations/jpcite_boot_manifest.txt`              | +11 | append `278_federated_mcp.sql`                |
| `scripts/migrations/autonomath_boot_manifest.txt`          | +11 | append `278_federated_mcp.sql`                |

Migration LOC: 93 (mig) + 18 (rollback) + 22 (manifest entries) = **~133 LOC of migration substrate**.
Total PR LOC: ~679 (incl. test + ETL).

## 6-partner curated shortlist

| partner_id | name                       | server_url                         | capability_tag           |
| ---------- | -------------------------- | ---------------------------------- | ------------------------ |
| freee      | freee 会計                  | https://mcp.freee.co.jp/v1         | accounting\|invoice\|tax |
| mf         | マネーフォワード クラウド     | https://mcp.moneyforward.com/v1    | accounting\|invoice\|payroll |
| notion     | Notion                     | https://mcp.notion.com/v1          | doc\|kb\|collab          |
| slack      | Slack                      | https://mcp.slack.com/v1           | chat\|notify\|workflow   |
| github     | GitHub                     | https://mcp.github.com/v1          | code\|issue\|pr\|review  |
| linear     | Linear                     | https://mcp.linear.app/v1          | issue\|product\|cycle    |

## Verify

- `sqlite3 < 278_federated_mcp.sql` clean (2 tables + 4 indices).
- 2nd apply idempotent (every CREATE uses `IF NOT EXISTS`).
- Rollback drops tables + indices cleanly.
- ETL seed apply → 6 inserted; 2nd apply → 0 inserted, 6 updated (no dupes).
- Dry-run → 6 inserted plan, 0 rows actually written.
- `pytest tests/test_dim_r_federated_mcp.py -v` → **14 passed / 0 failed / 0.98s**.
- `capability_tag` pipe-separated for all 6 partners (none empty).
- `last_health_at` = NULL on fresh seed (DEGRADED-safe semantics; cron probe fills it).
- `am_handoff_log` indices `idx_am_handoff_log_partner` used in `EXPLAIN QUERY PLAN`.
- No legacy brand markers (`zeimu-kaikei.ai` / `税務会計AI`) in migration / rollback / ETL.
- No LLM SDK imports (`anthropic` / `openai`) in ETL.
- Both boot manifests (`jpcite_boot_manifest.txt` + `autonomath_boot_manifest.txt`) register `278_federated_mcp.sql`.

## Hard constraints honored

- **No external MCP server call.** Pure local seed; the agent client (Claude / Cursor / etc.) connects to partner servers directly using the recorded `server_url`.
- **No LLM API call.** Pure SQLite + deterministic seed.
- **No rm/mv on existing files.** Pure additive (CREATE TABLE/INDEX IF NOT EXISTS, INSERT OR UPDATE on partner_id PK).
- **Soft FK on `am_handoff_log.partner_id`.** Deleting a partner row does NOT cascade-erase the historical audit trail.
- **Brand discipline.** Only `jpcite` (and `autonomath` as historical db filename) in identifiers + comments.
