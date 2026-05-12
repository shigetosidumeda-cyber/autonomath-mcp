# Wave 47 — Dim S (embedded copilot scaffold) migration PR — STATE

- **Date**: 2026-05-12 (Wave 46 永遠ループ tick#5)
- **Dim**: S — embedded copilot scaffold (per `feedback_copilot_scaffold_only_no_llm`)
- **Branch**: `feat/jpcite_2026_05_12_wave47_dim_s_migration`
- **Worktree**: `/tmp/jpcite-w47-dim-s-mig` (lane claim: `/tmp/jpcite-w47-dim-s-mig.lane`)
- **Base**: `origin/main` @ `537d23776`
- **PR**: filled at push time

## Purpose

Storage substrate for the Dim S "embedded copilot scaffold" surface. The
widget is dropped into a customer SaaS (freee / MoneyForward / Notion /
Slack); inside that widget the customer's OWN agent talks to OUR MCP
proxy. **Operator-side LLM API calls = 0** (per
`feedback_copilot_scaffold_only_no_llm` + `feedback_no_operator_llm_api`).

## Files (5 new + 2 manifest edits)

| Path | LOC | Role |
| ---- | --- | ---- |
| `scripts/migrations/279_copilot_scaffold.sql` | 109 | schema (config + audit) |
| `scripts/migrations/279_copilot_scaffold_rollback.sql` | 25 | rollback (drops only Dim S surface) |
| `scripts/etl/seed_copilot_widgets.py` | 206 | 4-host-SaaS canonical seed |
| `src/jpintel_mcp/api/copilot_scaffold.py` | 151 | REST helpers (LLM-0 by construction) |
| `tests/test_dim_s_copilot_scaffold.py` | 458 | 19 cases (mig + seed + scaffold + LLM-0 guard) |
| `scripts/migrations/jpcite_boot_manifest.txt` | +14 | register 279 |
| `scripts/migrations/autonomath_boot_manifest.txt` | +14 | register 279 mirror |

## Schema (migration 279)

- `am_copilot_widget_config` (PK=`widget_id` INTEGER AUTOINCREMENT)
  - `host_saas` UNIQUE (length 1..64)
  - `embed_url` (https-only CHECK)
  - `mcp_proxy_url` (https-only CHECK)
  - `oauth_scope` (cap 512 chars)
  - `enabled` BOOLEAN (0/1), `created_at`, `updated_at`
  - Indexes: `host`, `enabled+host`
- `am_copilot_session_log` (PK=`session_id` INTEGER AUTOINCREMENT)
  - `widget_id` FK → `am_copilot_widget_config(widget_id)`
  - `user_token_hash` (sha256 hex, length=64 CHECK)
  - `started_at`, `ended_at` (CHECK `ended_at >= started_at`)
  - Indexes: `widget+started DESC`, `started`, partial on active sessions
- `v_copilot_widget_enabled` helper view (alphabetical by host_saas)

## Seed (4 widgets)

| host_saas | embed_url | mcp_proxy_url | oauth_scope |
| --------- | --------- | ------------- | ----------- |
| freee | `https://jpcite.ai/embed/copilot/freee` | `https://jpcite.ai/mcp/proxy/freee` | `read:invoice read:journal read:taxrate` |
| moneyforward | `https://jpcite.ai/embed/copilot/moneyforward` | `https://jpcite.ai/mcp/proxy/moneyforward` | `read:bookkeeping read:tax read:expense` |
| notion | `https://jpcite.ai/embed/copilot/notion` | `https://jpcite.ai/mcp/proxy/notion` | `read:database read:page` |
| slack | `https://jpcite.ai/embed/copilot/slack` | `https://jpcite.ai/mcp/proxy/slack` | `chat:write commands users:read` |

## LLM-0 verify

```
$ grep -E "anthropic|openai" src/jpintel_mcp/api/copilot_scaffold.py
# 0 hits in code (only the docstring "MUST NOT pull in any LLM SDK"
# disclaimer remains, which is the negative assertion — guarded by
# tests/test_dim_s_copilot_scaffold.py::test_no_llm_token_in_copilot_scaffold_api
# which strips comments + docstrings before scanning)
```

Test scan also runs against:
- `scripts/migrations/279_copilot_scaffold.sql` (any layer)
- `scripts/migrations/279_copilot_scaffold_rollback.sql`
- `scripts/etl/seed_copilot_widgets.py`
- `src/jpintel_mcp/api/copilot_scaffold.py`

→ all 0 hits for `import anthropic` / `import openai` / `from anthropic` /
`from openai` / `google.generativeai`.

## Pytest result

```
collected 19 items
tests/test_dim_s_copilot_scaffold.py ...................   [100%]
============================== 19 passed in 1.77s ==============================
```

Coverage:
1. `test_mig_279_applies_clean` — every table/view present
2. `test_mig_279_is_idempotent` — re-apply is no-op
3. `test_mig_279_rollback_drops_all` — clean rollback
4. `test_check_host_saas_not_empty` — empty host_saas rejected
5. `test_check_embed_url_https_only` — http://… rejected
6. `test_check_mcp_proxy_url_https_only` — ftp://… rejected
7. `test_check_token_hash_length` — short token_hash rejected
8. `test_check_ended_at_after_started_at` — backward time rejected
9. `test_seed_inserts_4_widgets`
10. `test_seed_is_idempotent`
11. `test_seed_dry_run_writes_nothing`
12. `test_view_excludes_disabled`
13. `test_scaffold_open_close_session` — sha256 hash, raw token never stored,
    double-close noop
14. `test_scaffold_lists_enabled_widgets`
15. `test_manifest_jpcite_lists_279`
16. `test_manifest_autonomath_lists_279`
17. `test_no_llm_token_in_copilot_scaffold_api` — **LLM-0 verify**
18. `test_no_llm_import_in_etl_or_migration`
19. `test_no_legacy_brand_in_new_files`

## SQLite syntax / idempotency verify (manual)

```
mig 279 applied OK
mig 279 re-apply OK (idempotent)
rollback applied OK
full cycle OK
```

## ruff

- `ruff check` — All checks passed (3 py files)
- `ruff format` — formatted on commit (2 files reformatted, 1 already
  formatted)

## Migration number rationale

- 271 = K (rule_tree) on dim-k worktree
- 272 = L (session_context) merged to main (commit 066d817a7)
- 273 = M (rule_tree_v2_chain) on dim-m worktree
- 274 = N (anonymized_query) merged to main
- 275 = O (explainable_fact) on dim-o worktree
- 276 = P (composable_tools) on dim-p worktree
- 277 = Q (time_machine) on dim-q worktree
- 278 = R (federated_mcp_recommendation) on dim-r worktree (reserved)
- **279 = S (copilot_scaffold) — THIS PR**

## Hard constraints upheld

- `feedback_dual_cli_lane_atomic` — `/tmp/jpcite-w47-dim-s-mig.lane`
  mkdir lock held before any work
- `feedback_completion_gate_minimal` — gate = pytest 19/19 +
  SQLite syntax + LLM-0 grep on the named file. Not gated on global
  CI green.
- `feedback_copilot_scaffold_only_no_llm` — scaffold + MCP proxy + OAuth
  bridge ONLY. No LLM SDK import, no completion call, no prompt/response
  column.
- `feedback_no_operator_llm_api` — operator side never calls an LLM
  API. The MCP proxy forwards tool/data calls only.
- `feedback_destruction_free_organization` — pure additive (CREATE IF
  NOT EXISTS + new files). No rm/mv. No existing file is overwritten
  except the boot manifests, which gain a 14-line trailing block.
- No PR #150 overwrite — new branch, new PR.
- Main worktree untouched.
- Brand: only jpcite. No `税務会計AI` / `zeimu-kaikei.ai`.

## Not in this PR (explicit out-of-scope)

- The `/v1/copilot/*` REST routes (would touch `api/router.py` and
  conflict with sibling Dim K-R PRs). The helper functions
  (`list_enabled_widgets` / `get_proxy_descriptor` / `open_session` /
  `close_session`) are wire-ready; the router include lives in a
  follow-up integration PR.
- Embed HTML/JS scaffold under `site/embed/`. The widget config table
  points to those URLs; the actual static assets are scoped to a
  separate Wave 48 site PR.
- MCP proxy server-side implementation (Streamable HTTP forwarding).
  Out of scope for the storage-layer PR.

## Risk

- Low. Pure additive schema, FK to a new table only, no existing call
  site touched. CI risk surface = boot manifest + ruff format.
- Operator side LLM API surface unchanged at 0 calls.
