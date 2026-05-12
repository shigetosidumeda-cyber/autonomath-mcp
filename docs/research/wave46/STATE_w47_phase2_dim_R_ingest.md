# Wave 47 Phase 2 tick#4 — Dim R federated_mcp partner ETL actual run

date: 2026-05-12
branch: feat/jpcite_2026_05_12_wave47_phase2_dim_r_ingest
ref: PR #167 (storage substrate landed) — this STATE doc is the actual
     ETL run snapshot that loads the 6 curated MCP partner rows.
parent feedback: `feedback_federated_mcp_recommendation`

## Scope

Wave 47 Phase 2 closes Dim R by **actually running** the seed ETL
(`scripts/etl/seed_federated_mcp_partners.py`) against the local
`data/autonomath.db`. The storage substrate (migration 278) was landed
in PR #167 and only created the empty `am_federated_mcp_partner` +
`am_handoff_log` tables; this tick exercises the seed path so the
catalogue actually contains the 6 partner rows the recommendation
surface needs.

This run does **NOT** touch production. It is the local dev-DB seed
that exercises the same code path the production cron will execute,
and the row count + idempotency are recorded here as the audit trail.

## Hard constraints honoured

* **NO external MCP server call.** Pure local SQLite UPSERT.
* **NO LLM API import.** `grep -iE "^(import|from)\s+(anthropic|openai|langchain|llama_index|claude)"`
  on `seed_federated_mcp_partners.py` + `278_federated_mcp.sql` returns
  zero hits (matches `feedback_no_operator_llm_api`).
* **No legacy brand.** Identifiers/comments use `jpcite` only.
* **No PRAGMA quick_check** on autonomath.db (per
  `feedback_no_quick_check_on_huge_sqlite`).
* **No rm/mv.** Worktree isolation via
  `/tmp/jpcite-w47-phase2-dim-r/` (separate from main worktree).

## Steps executed

```text
1. git worktree add /tmp/jpcite-w47-phase2-dim-r \
       -b feat/jpcite_2026_05_12_wave47_phase2_dim_r_ingest main
2. sqlite3 data/autonomath.db < scripts/migrations/278_federated_mcp.sql
3. python3 scripts/etl/seed_federated_mcp_partners.py \
       --db data/autonomath.db --dry-run
   ->  INFO: federated_mcp partner seed dry-run:
            inserted=6 updated=0 (total=6)
   ->  exit=0
4. python3 scripts/etl/seed_federated_mcp_partners.py \
       --db data/autonomath.db
   ->  INFO: federated_mcp partner seed applied:
            inserted=6 updated=0 (total=6)
   ->  exit=0
5. python3 scripts/etl/seed_federated_mcp_partners.py \
       --db data/autonomath.db   # idempotency probe
   ->  INFO: federated_mcp partner seed applied:
            inserted=0 updated=6 (total=6)
   ->  exit=0
```

## Row count snapshot

```text
$ sqlite3 data/autonomath.db \
      "SELECT COUNT(*) FROM am_federated_mcp_partner;"
6
```

## 6 partner rows verified

| partner_id | name                       | server_url                              | capability_tag                | last_health_at |
| ---------- | -------------------------- | --------------------------------------- | ----------------------------- | -------------- |
| freee      | freee 会計                 | https://mcp.freee.co.jp/v1              | accounting\|invoice\|tax      | NULL           |
| mf         | マネーフォワード クラウド  | https://mcp.moneyforward.com/v1         | accounting\|invoice\|payroll  | NULL           |
| notion     | Notion                     | https://mcp.notion.com/v1               | doc\|kb\|collab               | NULL           |
| slack      | Slack                      | https://mcp.slack.com/v1                | chat\|notify\|workflow        | NULL           |
| github     | GitHub                     | https://mcp.github.com/v1               | code\|issue\|pr\|review       | NULL           |
| linear     | Linear                     | https://mcp.linear.app/v1               | issue\|product\|cycle         | NULL           |

`last_health_at = NULL` is the seed default. The out-of-band
HTTPS-HEAD probe (`scripts/cron/`) fills it later; callers treat NULL
as DEGRADED per the migration 278 contract.

## Index + audit log shape verified

```text
$ sqlite3 data/autonomath.db \
      "SELECT name FROM sqlite_master \
       WHERE type='index' AND tbl_name='am_federated_mcp_partner';"
sqlite_autoindex_am_federated_mcp_partner_1   -- PK
idx_am_federated_mcp_partner_capability
idx_am_federated_mcp_partner_health
```

```text
$ sqlite3 data/autonomath.db "PRAGMA table_info(am_handoff_log);"
0|handoff_id|INTEGER|0||1
1|source_query|TEXT|1||0
2|partner_id|TEXT|1||0
3|response_summary|TEXT|1|''|0
4|requested_at|TEXT|1|strftime('%Y-%m-%dT%H:%M:%fZ','now')|0
```

`am_handoff_log` is the append-only audit trail. Wave 47 Phase 2
tick#4 does not write to it directly (no recommendation traffic in
this run); a separate seed run is unnecessary because the table is
populated on live recommendation calls.

## Bug-free verify

| Gate                                            | Result                                    |
| ----------------------------------------------- | ----------------------------------------- |
| ETL `--dry-run` exit                            | 0                                         |
| ETL `--apply` exit (1st run)                    | 0                                         |
| ETL `--apply` exit (2nd run, idempotency)       | 0 (inserted=0 / updated=6)                |
| 6 partner row presence (freee/mf/notion/slack/github/linear) | All 6 present                |
| `am_federated_mcp_partner` CHECK constraint     | `length(capability_tag) > 0` holds        |
| LLM API import (anthropic/openai/etc.)          | 0 hits in ETL + migration                 |
| External MCP server call                        | 0 (pure local sqlite3)                    |
| PRAGMA quick_check on autonomath.db             | not run (per feedback)                    |
| Legacy brand (税務会計AI/AutonoMath/zeimu-kaikei.ai) | 0 in ETL + STATE                      |
| `am_handoff_log` schema (5 cols incl. AUTOINCREMENT) | verified                              |
| Indexes (capability, health)                    | both created                              |

## Cost posture

`feedback_no_operator_llm_api` honoured: 0 Anthropic/OpenAI/Claude
SDK import, 0 paid API call, 0 yen incurred. Future cron
`partner_health_probe.py` will use HTTPS HEAD (non-LLM) for the
periodic `last_health_at` refresh.
