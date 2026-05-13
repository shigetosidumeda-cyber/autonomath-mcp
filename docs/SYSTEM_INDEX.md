# SYSTEM_INDEX

**5-minute master entry for new sessions.** CLAUDE.md = dev guide (deep). This file = navigation hub (links).

Operator: Bookyou株式会社 (T8010001213708) / 梅田茂利 / info@bookyou.net
Brand: **jpcite** (PyPI dist: `autonomath-mcp`, import: `jpintel_mcp`) — launch 2026-05-06.

---

## 1. エレベーターピッチ

日本の公的制度 (補助金・税制・法令・融資・採択事例) を **REST API + MCP server** で提供する Japanese public-program search platform。¥3/billable unit 完全従量、anonymous 3 req/日 free、solo + zero-touch + 100% organic acquisition。

---

## 2. Component map

| Component | Path | Notes |
|---|---|---|
| REST API | [`src/jpintel_mcp/api/`](../src/jpintel_mcp/api/) | FastAPI, ~80 router files, mounted `/v1/*` (≈194-240 paths post Wave 21-23) |
| MCP server | [`src/jpintel_mcp/mcp/`](../src/jpintel_mcp/mcp/) | FastMCP stdio, **151 tools** at default gates |
| DB layer | [`src/jpintel_mcp/db/`](../src/jpintel_mcp/db/) | `schema.sql`, `session.py`, `id_translator.py` |
| Billing | [`src/jpintel_mcp/billing/`](../src/jpintel_mcp/billing/) | Stripe metered ¥3/billable unit |
| Primary DB | [`autonomath.db`](../autonomath.db) (~11 GB) + [`jpintel.db`](../jpintel.db) (~1.6 MB live) | unified post mig 032; `data/jpintel.db` ~352 MB |
| Cron | [`scripts/cron/`](../scripts/cron/) | 57 scripts (precompute, backups, ingest, RSS, KPI, webhooks) |
| ETL | [`scripts/etl/`](../scripts/etl/) | translate corpus, harvest relations, repromote amounts |
| Migrations | [`scripts/migrations/`](../scripts/migrations/) | 212 SQL files (`-- target_db: jpintel\|autonomath` header) |
| TS/JS SDK | [`sdk/agents/`](../sdk/agents/) (npm `@jpcite/agents`), [`sdk/typescript/`](../sdk/typescript/), [`sdk/python/`](../sdk/python/) | |
| VSCode ext | [`sdk/vscode-extension/`](../sdk/vscode-extension/) | |
| Browser ext | [`sdk/browser-extension/`](../sdk/browser-extension/), [`sdk/chrome-extension/`](../sdk/chrome-extension/) | |
| Plugins | [`sdk/freee-plugin/`](../sdk/freee-plugin/), [`sdk/mf-plugin/`](../sdk/mf-plugin/), [`sdk/integrations/`](../sdk/integrations/) (slack/email/excel/kintone/google-sheets) | |
| Static site | [`site/`](../site/) | jpcite.com on Cloudflare Pages, 104 entries, hand-written HTML + generated program pages |
| Tests | [`tests/`](../tests/) | unit + integration + e2e (Playwright) + `test_no_llm_in_production.py` guard |
| Offline tools | [`tools/offline/`](../tools/offline/) | only place LLM SDK imports allowed |
| DXT bundle | [`dxt/`](../dxt/) | Claude Desktop MCP bundle (manifest + icon) |
| GHA workflows | [`.github/workflows/`](../.github/workflows/) | 63 workflows (cron + CI + deploy) |

---

## 3. Wave progress

| Wave | Date | Outcome |
|---|---|---|
| W1-5 | 2026-05-04 | Historical v0.3.1 snapshot: 178 routes / 101-tool runtime (memory: project_jpcite_wave_1_to_5_complete) |
| W1-16 | 2026-05-04 | 16 wave / 154+ task; 240 route 500 ZERO; UC1-10 SOFT-GO 10/10; cron 52/52; SMOKE PASS (memory: project_jpcite_wave_1_to_16_complete) |
| W18 | 2026-04-25 | 11 audit suites (e1, h3-h9, j1-j10, k1-k10) → see [`analysis_wave18/`](../analysis_wave18/) and [`_AUDIT_FINAL_2026-04-25.md`](../analysis_wave18/_AUDIT_FINAL_2026-04-25.md) |
| W19 | 2026-04-26..28 | GitHub rename, PyPI publish ready, legal self audit, lawyer consult, venv312 — see [W19_legal_self_audit.md](_internal/W19_legal_self_audit.md), [W19_PYPI_PUBLISH_READY.md](_internal/W19_PYPI_PUBLISH_READY.md) |
| W20 | 2026-04-28..29 | Amount validation, narrative batch runner, OIDC setup, Claude Desktop submission — [W20_AMOUNT_VALIDATION_REPORT.md](_internal/W20_AMOUNT_VALIDATION_REPORT.md), [W20_PYPI_OIDC_SETUP.md](_internal/W20_PYPI_OIDC_SETUP.md) |
| W21 | 2026-04-29 | 5 composition tools live; vec bench; workflows pending — [W21_VEC_BENCH.md](_internal/W21_VEC_BENCH.md), [W21_WORKFLOWS_PENDING.md](_internal/W21_WORKFLOWS_PENDING.md) |
| W22 | 2026-04-29 | 5 wave22 tools (DD/kessan/forecast/jurisdiction/kit), inbox quality, sensitive law map — [W22_INBOX_QUALITY_AUDIT.md](_internal/W22_INBOX_QUALITY_AUDIT.md), [W22_NEW_LAW_PROGRAM_LINKS.md](_internal/W22_NEW_LAW_PROGRAM_LINKS.md), [W22_SENSITIVE_LAW_MAP.md](_internal/W22_SENSITIVE_LAW_MAP.md) |
| W23 | 2026-04-29 | 3 industry packs (construction / manufacturing / real_estate), 8 sample programs each, saved-search seeds (CLAUDE.md §"Wave 23 changelog") |
| W24 | 2026-04-24 (precompute) | 9 agents, 78 wave24_*.sql migrations, mat tables refresher — see [`analysis_wave18/wave24/`](../analysis_wave18/wave24/) |

---

## 4. Quick Links

- **Setup**: [`README.md`](../README.md), [`JPCITE_SETUP.md`](../JPCITE_SETUP.md), [`docs/getting-started.md`](getting-started.md), [`CLAUDE.md`](../CLAUDE.md)
- **Directory map**: [`DIRECTORY.md`](../DIRECTORY.md)
- **Master plan**: [`MASTER_PLAN_v1.md`](../MASTER_PLAN_v1.md)
- **API ref**: [`docs/api-reference.md`](api-reference.md), [`docs/openapi/v1.json`](openapi/v1.json)
- **MCP tools**: [`docs/mcp-tools.md`](mcp-tools.md), [`docs/_internal/mcp_tool_catalog.md`](_internal/mcp_tool_catalog.md)
- **Internal index**: [`docs/_internal/INDEX.md`](_internal/INDEX.md), [`docs/_internal/_INDEX.md`](_internal/_INDEX.md)
- **Runbooks**: [`docs/_internal/incident_runbook.md`](_internal/incident_runbook.md), [`docs/_internal/dr_backup_runbook.md`](_internal/dr_backup_runbook.md), [`docs/_internal/health_monitoring_runbook.md`](_internal/health_monitoring_runbook.md), [`docs/_internal/hf_publish_runbook.md`](_internal/hf_publish_runbook.md), [`docs/_internal/npm_publish_runbook.md`](_internal/npm_publish_runbook.md), [`docs/_internal/mcp_registry_runbook.md`](_internal/mcp_registry_runbook.md), [`docs/_internal/invoice_registrants_bulk_runbook.md`](_internal/invoice_registrants_bulk_runbook.md)
- **Compliance**: [`docs/compliance/INDEX.md`](compliance/INDEX.md)
- **Cookbook / examples**: [`docs/cookbook/`](cookbook/), [`examples/`](../examples/)
- **Deploy**: [`fly.toml`](../fly.toml), [`Dockerfile`](../Dockerfile), [`entrypoint.sh`](../entrypoint.sh), [`docs/_internal/DEPLOY_CHECKLIST_2026-05-01.md`](_internal/DEPLOY_CHECKLIST_2026-05-01.md)
- **Handoffs**: [`HANDOFF_2026-04-25.md`](../HANDOFF_2026-04-25.md), [`docs/_internal/handoff_consolidated_strategy_2026-05-01.md`](_internal/handoff_consolidated_strategy_2026-05-01.md), [`docs/_internal/handoff_full_takeover_2026-05-01.md`](_internal/handoff_full_takeover_2026-05-01.md)
- **Changelog**: [`CHANGELOG.md`](../CHANGELOG.md)

---

## 5. Materialized views (precompute layer, refreshed by `scripts/cron/precompute_refresh.py`)

W22+W23 substrate. Refresher source-of-truth: [`scripts/cron/precompute_refresh.py`](../scripts/cron/precompute_refresh.py) (33 REFRESHERS dict; counts queryable via `sqlite3 autonomath.db "SELECT name, (SELECT COUNT(*) FROM ...) FROM sqlite_master WHERE name LIKE 'mat_%' OR name LIKE 'pc_%';"`).

13 mat tables (W22+W23 cohort substrate, mat_ + key pc_ tables):

1. `mat_entity_count_by_kind` — by record_kind+canonical_status (refresh: [`analysis_wave18/wave24/refresh_mat.py`](../analysis_wave18/wave24/refresh_mat.py))
2. `mat_active_program_summary` — top-level KPI snapshot
3. `mat_tax_rule_effective_now` — currently-effective tax rules
4. `pc_top_subsidies_by_industry`
5. `pc_top_subsidies_by_prefecture`
6. `pc_law_to_program_index`
7. `pc_acceptance_stats_by_program`
8. `pc_combo_pairs`
9. `pc_seasonal_calendar`
10. `pc_starter_packs_per_audience`
11. `pc_amendment_recent_by_law`
12. `jpi_pc_program_health` (V4 absorption)
13. `am_amendment_diff` (cron-populated, baseline 0)

Run: `.venv/bin/python scripts/cron/precompute_refresh.py --only <name>` or `--all`.

---

## 6. よくある作業

| 作業 | コマンド |
|---|---|
| Local API | `.venv/bin/uvicorn jpintel_mcp.api.main:app --reload --port 8080` |
| Local MCP | `.venv/bin/autonomath-mcp` |
| Tests | `.venv/bin/pytest` (unit+integ) / `.venv/bin/pytest tests/e2e/` |
| Migration apply | `entrypoint.sh §4` (autonomath-target auto-discovered on boot, header `-- target_db: autonomath`); jpintel-target via `python scripts/migrate.py` |
| MCP tool count probe | `len(await mcp.list_tools())` (must be 151 at default gates) |
| Static pages regen | `.venv/bin/python scripts/generate_program_pages.py` |
| Source liveness | `.venv/bin/python scripts/refresh_sources.py --tier S,A` |
| OpenAPI export | `.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json` |
| Docs build | `mkdocs build --strict` |
| Logs | `fly logs -a <app>` ; cron logs in `data/*.log` |
| Release | bump `pyproject.toml` + `server.json` (must match) → tag → `python -m build && twine upload` → `mcp publish` ([CLAUDE.md §Release checklist](../CLAUDE.md)) |

---

## 7. Secrets

- **Registry**: [`docs/_internal/SECRETS_REGISTRY.md`](_internal/SECRETS_REGISTRY.md)
- **Discover script**: [`scripts/ops/discover_secrets.sh`](../scripts/ops/discover_secrets.sh) (greps env var references across the repo and produces a delta)
- **Local template**: [`.env.example`](../.env.example)
- **Fly secrets**: managed via `fly secrets set/list -a <app>`

---

## 8. Legal

- **Self audit (W19)**: [`docs/_internal/W19_legal_self_audit.md`](_internal/W19_legal_self_audit.md)
- **Lawyer consult outline (W19)**: [`docs/_internal/W19_lawyer_consult_outline.md`](_internal/W19_lawyer_consult_outline.md)
- **Sensitive law map (W22)**: [`docs/_internal/W22_SENSITIVE_LAW_MAP.md`](_internal/W22_SENSITIVE_LAW_MAP.md) — 16 sensitive tools (§52 / §72 / 行政書士法 §1 / 社労士法 / 司法書士法 §3) carrying `_disclaimer`
- **License gate**: [`src/jpintel_mcp/api/_license_gate.py`](../src/jpintel_mcp/api/_license_gate.py)
- **Compliance docs**: [`docs/compliance/`](compliance/) — 景表法 / 個情法 / AI法 / インボイス / tokushoho / pepper / honesty
- **36協定 gate**: `AUTONOMATH_36_KYOTEI_ENABLED` (default OFF, 労基法 §36 + 社労士法 supervision required)

---

## 9. 戦略

Source: [`docs/long_term_strategy.md`](long_term_strategy.md) (§1-5). Y0 launch 2026-05-06.

| § | テーマ | Current 達成度 |
|---|---|---|
| §1 三シナリオ | Y5 ARR Best ¥750M-1.5B / Base ¥150-450M / Down ¥30-60M | Y0 pre-launch — measurable from Y1+9mo gate |
| §2.1 Amendment time depth | 14,596 → Y5 100,000+ | **14,596** (mig snapshots; eligibility_hash 82% empty) |
| §2.2 Operator curation | 504 → Y5 10,000 hallucination_guard rules | **504** rejected + 181 exclusion/prerequisite rules |
| §2.3 Brand / 関係性 | Y5 200 testimonials / 50 案例 | aspirational (Y0) |
| §2.4 Compliance discipline | Tier=X quarantine / claim_strength / disclaimer / 10kw block | **operational** (CI guard `tests/test_no_llm_in_production.py`) |
| §2.5 5×5 matrix | V1 subsidy live, V2-V5 deferred | **V1 launch (2026-05-06)** ; V2 Healthcare T+90d, V3 Real Estate T+200d, V4 EN T+150d |

Cohort revenue model (8 cohorts, locked 2026-04-29) → [`CLAUDE.md` §"Cohort revenue model"](../CLAUDE.md).

---

**Last reviewed**: 2026-05-05. Update when a new wave lands or component reshapes.
