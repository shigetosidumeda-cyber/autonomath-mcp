# CodeX CLI Handoff — jpcite Main Goal Validation Lane

**Created**: 2026-05-17 (Claude Code session, vendor-neutral SOT)
**Target CLI**: CodeX (OpenAI Codex CLI), 6-agent concurrent
**Counterpart CLI**: Claude Code (separate worktree at `/Users/shigetoumeda/jpcite/`)
**This file** is the canonical handoff. Paste into CodeX session-start prompt verbatim.

---

## TL;DR for CodeX

You are CodeX, working in **`/Users/shigetoumeda/jpcite-codex/`** (git worktree of jpcite repo), branch `codex-validation-2026-05-17`. Your job is **main goal validation + production gate 7/7 restoration + quality push** (jpcite v0.5.x → v0.6.0).

A separate Claude Code CLI is running in **`/Users/shigetoumeda/jpcite/`** on branch `main`, focused on AWS-side work (ML training, SageMaker, OpenSearch, Heavy Endpoints, pricing). **Do not touch the AWS scope or the main branch.**

Always run **6 agents concurrently** (per user directive). Stage-1 validation first, then quality, then release prep.

---

## 1. Project identity

- **Product**: jpcite (Japanese public-program database + MCP server)
- **Operator**: Bookyou株式会社 (T8010001213708), 代表 梅田茂利, info@bookyou.net
- **Live state**: Fly.io Tokyo + Cloudflare Pages + Stripe metered billing
- **PyPI package**: `autonomath-mcp` (legacy name retained; user-facing brand = **jpcite**)
- **Source import path**: `jpintel_mcp` (DO NOT rename to `autonomath_mcp` — breaks consumers)

## 2. Worktree setup (run once at CodeX session start)

```bash
# 1. Verify Claude side is at main HEAD
cd /Users/shigetoumeda/jpcite && git pull --rebase && git log --oneline -3

# 2. Create CodeX worktree
cd /Users/shigetoumeda
git -C jpcite worktree add ../jpcite-codex -b codex-validation-2026-05-17

# 3. Symlink the 15GB autonomath.db (avoid 2x storage)
cd /Users/shigetoumeda/jpcite-codex
ln -sf ../jpcite/autonomath.db autonomath.db
ln -sf ../jpcite/data/jpintel.db data/jpintel.db

# 4. Verify
ls -la autonomath.db data/jpintel.db
git -C /Users/shigetoumeda/jpcite-codex status -b
```

After this, every CodeX command runs from `/Users/shigetoumeda/jpcite-codex/`.

## 3. Anti-collision rules (CRITICAL)

| Rule | Why |
|---|---|
| **NEVER** edit files under `scripts/aws_credit_ops/` | Claude side LIVE-trains here |
| **NEVER** edit files under `src/jpintel_mcp/mcp/products/` | Claude side ships A1-A5 packs here |
| **NEVER** edit `src/jpintel_mcp/mcp/moat_lane_tools/he*.py` | Claude side ships HE-1/2/3/4 here |
| **NEVER** push to `main` branch directly | Claude side owns main, CodeX merges via Friday weekly rebase |
| **NEVER** start/stop AWS resources (SageMaker, EC2, OpenSearch, Lambda) | Claude side controls these |
| **NEVER** touch `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` | Claude side AWS authority SOT |
| **NEVER** modify `memory/MEMORY.md` | Claude exclusive |
| **ALWAYS** mark each commit `[lane:codex-solo]` (different from `[lane:solo]` to distinguish) | Conflict audit trail |
| **ALWAYS** use `bash scripts/safe_commit.sh "msg [lane:codex-solo]"` (NO `--no-verify`) | Pre-commit honored |
| **ALWAYS** check `.codex-active` sentinel file before editing a file Claude may also touch | Lock-style guard |

### Sentinel file protocol
- Before editing a file in **shared scope** (anything not explicitly assigned), write the relative path to `.codex-active` (gitignored)
- Claude side reads `.codex-active` before any cross-scope edit (rare)
- Convention: `printf "%s\n" "$(date -u +%FT%TZ) $(realpath path/to/file)" >> .codex-active`

## 4. CodeX-assigned scope (file-level allowlist)

```
src/jpintel_mcp/api/           ← REST routes, FastAPI middleware
src/jpintel_mcp/services/      ← service layer
src/jpintel_mcp/ingest/        ← data ingestion
src/jpintel_mcp/db/             ← SQLite migrations (READ-ONLY: do not add new wave24_*)
src/jpintel_mcp/billing/        ← Stripe metering
src/jpintel_mcp/email/          ← transactional email
tests/                          ← all test files (including new ones)
docs/_internal/                 ← internal docs (with `_codex_` prefix for new)
docs/api/                       ← user-facing API docs
.github/workflows/              ← CI/CD (coordinate with Claude side via handoff)
Makefile, pyproject.toml        ← build config (coordinate)
```

**Out of scope** (Claude side only):
```
scripts/aws_credit_ops/
src/jpintel_mcp/mcp/products/
src/jpintel_mcp/mcp/moat_lane_tools/he*.py
src/jpintel_mcp/mcp/moat_lane_tools/moat_n*.py (LIVE wired by Claude)
infra/aws/
scripts/migrations/wave24_2*.sql  (Claude side adds new)
```

## 5. Non-negotiable constraints (same as Claude side)

- **¥3/req metered billing only** (税込 ¥3.30). No tier SKUs / seat fees / annual minimums
- **100% organic acquisition** — no paid ads, no sales calls, no cold outreach
- **Solo + zero-touch ops** — no DPA/MSA, no Slack Connect, no phone support, no onboarding calls
- **Data hygiene** — aggregator URLs banned (`noukaweb` / `hojyokin-portal` / `biz.stayway`); 一次資料 only
- **Trademark** — DO NOT revive `jpintel` brand in user-facing copy (Intel collision); product = jpcite, operator = Bookyou株式会社
- **NO LLM API** anywhere under `src/`, `scripts/cron/`, `scripts/etl/`, `tests/` (CI guard `tests/test_no_llm_in_production.py` enforces; never weaken). Operator-only LLM tools live in `tools/offline/`
- **NEVER `--no-verify` / `--no-gpg-sign`** — fix hook root cause
- **NEVER `PRAGMA quick_check` / `PRAGMA integrity_check`** on `autonomath.db` (9.7GB, hangs 30+ min at boot)

## 6. Phase 0 — Immediate Validation (Day 1, 6 agents parallel)

These run before any code change. **All 6 in parallel.**

### Agent 0.1 — Production gate restoration audit
- Run `scripts/ops/production_deploy_readiness_gate.py` — expect 7/7 PASS but may show 4/7
- Identify 3 failing gates by name
- Cross-reference with Claude side's D5 audit (`docs/_internal/MOAT_REGRESSION_AUDIT_2026_05_17.md`)
- Output: `docs/_internal/_codex_PRODUCTION_GATE_AUDIT_2026_05_17.md`

### Agent 0.2 — pytest baseline
- Run `.venv/bin/pytest tests/ -q --tb=no 2>&1 | tail -20`
- Capture pass/fail count
- Identify failing test categories (manifest drift / JPCIR schema / scorecard fixture / public copy / xdist isolation)
- Output: `docs/_internal/_codex_PYTEST_BASELINE_2026_05_17.md`

### Agent 0.3 — mypy --strict baseline
- Run `.venv/bin/mypy src/jpintel_mcp/ --strict 2>&1 | tail -10`
- Expect 2 errors (botocore.auth pre-existing)
- Output: `docs/_internal/_codex_MYPY_BASELINE_2026_05_17.md`

### Agent 0.4 — Manifest tool count audit
- Read `scripts/distribution_manifest.yml` `tool_count_default_gates`
- Run `len(await mcp.list_tools())` via Python REPL
- Run `scripts/check_mcp_drift.py` + `scripts/probe_runtime_distribution.py`
- Compare against Claude side's H1+H2 lane (target: **218 exact**)
- Output: `docs/_internal/_codex_MCP_MANIFEST_AUDIT_2026_05_17.md`

### Agent 0.5 — Coverage baseline
- Run `.venv/bin/pytest tests/ --cov=src/jpintel_mcp --cov-report=term -q 2>&1 | tail -30`
- Expect project-wide ~26-35% (per memory `feedback_coverage_subset_vs_project_wide`)
- Identify top 10 lowest-coverage modules
- Output: `docs/_internal/_codex_COVERAGE_BASELINE_2026_05_17.md`

### Agent 0.6 — Claude side handoff review
- Read `docs/_internal/AGENT_HARNESS_REMEDIATION_PLAN_2026_05_17.md` (P0.1-P0.8 + P1.1-P1.8)
- Read all `docs/_internal/HARNESS_H*_2026_05_17.md` (if any landed yet)
- Read `docs/_internal/MOAT_INTEGRATION_MAP_2026_05_17.md` (D1 audit)
- Identify which P0/P1 items overlap with CodeX scope (most are Claude-side, but P1.7 eval SOT + P0.8 runbook + P0.4 AGENTS.md are CodeX-touch-safe)
- Output: `docs/_internal/_codex_HANDOFF_REVIEW_2026_05_17.md` (lists which items CodeX picks up vs hands back)

## 7. Phase 1 — Main goal validation (Day 1-2, 6 agents parallel)

Main `/goal` directive (original from user, 2026-05-15):
> 「この巨大な計画がすべて丁寧に バグなしで終えるまで で aws のコントロールも含めて 常に最大エージェント数を投入しながら 永遠にループし続けよ 途中で改善ができると思えば改善もして」

"巨大な計画" = jpcite v0.5.x → v0.6.0 release ready state. Validation = does current main reflect that?

### Agent 1.1 — Wave 50 RC1 closure verify
- Read `docs/_internal/WAVE50_RC1_FINAL_CLOSEOUT_2026_05_16.md`
- Verify 14 outcome contracts (`schemas/jpcir/`) all carry `estimated_price_jpy`
- Verify 20 JPCIR schemas vs `agent_runtime/contracts.py` 19 Pydantic round-trip
- Output: pass/fail per claim, `docs/_internal/_codex_WAVE50_VERIFY_2026_05_17.md`

### Agent 1.2 — Wave 51 dim K-S + L1-L6 verify
- Read `docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md`
- Verify each of K/L/M/N/O/P/Q/R/S has:
  - source module in `src/jpintel_mcp/` (or `src/jpcite/`)
  - tests/ coverage
  - MCP wrapper registered
- Verify L1 (source family) / L2 (math sweep) / L3 (cross_outcome_routing) / L4 (predictive_merge_daily) / L5 (notification_fanout) / L6 (as_of_snapshot_5y) each implemented + tested
- Output: `docs/_internal/_codex_WAVE51_VERIFY_2026_05_17.md`

### Agent 1.3 — 51 test fail triage
- For each of 51 failures from Phase 0.2, categorize:
  - A: manifest drift (218 vs 184) — Claude-side H1 fix
  - B: JPCIR schema count (22 vs 24)
  - C: scorecard fixture
  - D: public copy / static reachability
  - E: wave24_204+205.sql untracked
  - F: xdist fixture isolation
- For categories B, C, D, E, F: pick up the fix (CodeX scope)
- For category A: defer to Claude-side H1
- Output: PR with fix commits, each labeled `[lane:codex-solo]`

### Agent 1.4 — mypy strict 2 → 0
- Locate the 2 botocore.auth pre-existing errors
- Add `# type: ignore[import-untyped]` with rationale comment
- Verify `.venv/bin/mypy src/jpintel_mcp/ --strict` → 0 errors
- Commit `[lane:codex-solo]`

### Agent 1.5 — ruff 0 verify maintained
- Run `.venv/bin/ruff check src/jpintel_mcp/ scripts/ tests/`
- Expect 0 errors (Claude-side BB lane closed Wave 50 ruff hygiene)
- If any drift detected, fix and commit

### Agent 1.6 — Production gate 4/7 → 7/7 (CodeX subset)
- Identify which 3 failing gates are in CodeX scope (likely manifest sync + schema count + scorecard fixture, NOT AWS canary)
- Fix those 3 in CodeX scope
- Run `scripts/ops/production_deploy_readiness_gate.py` repeatedly until 7/7 (or until clearly Claude-side blocking)
- Commit each fix `[lane:codex-solo]`

## 8. Phase 2 — Quality push (Day 2-4, 6 agents parallel)

### Agent 2.1 — Coverage push: api/main + api/programs (current ~78% subset)
- Add tests/test_api_main_v3.py + tests/test_api_programs_v3.py (each 30+ new tests)
- Target: project-wide 26-35% → 40%+

### Agent 2.2 — Coverage push: services + ingest (current low)
- Add tests/test_services_*.py + tests/test_ingest_*.py
- Target: +50 tests, project-wide → 45%+

### Agent 2.3 — Coverage push: billing + email
- Stripe API mock OK (system boundary), DB NOT mocked
- Target: +30 tests

### Agent 2.4 — Coverage push: mcp/server.py (currently 49-74%)
- Add tests/test_mcp_server_v3.py
- Target: 74% → 85%+

### Agent 2.5 — E2E journey extend
- Extend tests/e2e/test_user_journey_*.py (5 cohort × 1 artifact 既存)
- Add 5 cohort × 2 more artifacts (15 → 25 scenarios)
- Verify each E2E flow with `JPINTEL_E2E=1` env

### Agent 2.6 — Flaky test detection + fix
- Run xdist `pytest -n 6` 3 times
- Identify flaky tests (different fail set each run)
- Add `@pytest.mark.serial` or fixture isolation
- Run sequential `pytest` to verify

## 9. Phase 3 — Release prep (Day 5-7, 6 agents parallel)

### Agent 3.1 — Version bump v0.5.1 → v0.6.0
- Edit `pyproject.toml` + `server.json` + `mcp-server.json` + `dxt/manifest.json` + `smithery.yaml`
- Pre-condition: H1 manifest contract decided (Claude-side)

### Agent 3.2 — CHANGELOG v0.6.0
- Compile Wave 50 RC1 + Wave 51 K-S + L1-L6 + HE-1-4 + N1-N10 + Pricing V3 + Stage 4 Harness
- Format: Keep-a-Changelog

### Agent 3.3 — Release notes
- `docs/releases/v0.6.0.md`
- Sales-grade narrative for organic acquisition

### Agent 3.4 — OpenAPI regen
- `.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json`
- Verify route count matches `scripts/distribution_manifest.yml`

### Agent 3.5 — Static site regen
- `mkdocs build --strict`
- `.venv/bin/python scripts/regen_llms_full.py` + `regen_llms_full_en.py`
- `make public-discovery` (after Claude-side H9 lands)

### Agent 3.6 — Final smoke + tag
- `.venv/bin/pytest tests/ -q` → 0 fail
- `make mcp-static` + `make mcp-runtime` PASS
- Production gate 7/7 PASS
- Output: ready-to-tag manifest + handoff to user for `git tag v0.6.0 && git push --tags`

## 10. Weekly merge cadence (Friday 18:00 JST)

```bash
# CodeX side prepares for merge
cd /Users/shigetoumeda/jpcite-codex
git status
git fetch origin
git rebase origin/main
# Resolve any conflicts (rare due to scope separation)
git push -u origin codex-validation-2026-05-17

# User opens PR: codex-validation-2026-05-17 → main
gh pr create --title "[codex weekly] Validation + quality push" --body "..."

# After merge, both sides pull
cd /Users/shigetoumeda/jpcite && git pull
cd /Users/shigetoumeda/jpcite-codex && git pull --rebase
```

## 11. Communication / handoff protocol

- **Daily**: Append to `docs/_internal/CROSS_CLI_HANDOFF_2026_05_17.md` (1 entry per CLI per day):
  - 状態 (Phase 0/1/2/3 + 進捗 %)
  - 完了 lane list
  - 進行中 lane list
  - 干渉 risk (もし発見したら)
- **Immediate** (干渉発見時): 該当 file path を `.codex-active` に append + 該当 lane を一時停止 + user に報告

## 12. Quality gates (must pass before each push)

1. `.venv/bin/pytest tests/test_no_llm_in_production.py` → 10/10 PASS
2. `.venv/bin/mypy src/jpintel_mcp/ --strict` → 0 errors
3. `.venv/bin/ruff check src/jpintel_mcp/ scripts/ tests/` → 0 errors
4. `.venv/bin/pytest tests/` → 51 fail → 0 fail (or progress)
5. `bash scripts/safe_commit.sh "msg [lane:codex-solo]"` → wrapper PASS (no `--no-verify`)
6. `git push origin codex-validation-2026-05-17` → success

## 13. Key files for CodeX bootstrap

Read these in order at session start:

1. **This file** (`docs/_internal/CODEX_CLI_HANDOFF_2026_05_17.md`)
2. `docs/_internal/AGENT_HARNESS_REMEDIATION_PLAN_2026_05_17.md` (P0/P1 list)
3. `CLAUDE.md` (until shrunken by Claude-side H3 lane — currently 923 lines, skim only for non-negotiable rules)
4. `docs/_internal/MOAT_INTEGRATION_MAP_2026_05_17.md` (D1 audit)
5. `docs/_internal/MOAT_REGRESSION_AUDIT_2026_05_17.md` (D5 audit, 51 fail categories)
6. `scripts/distribution_manifest.yml` (canonical counts)
7. `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` (AWS authority SOT)

## 14. AWS state — DO NOT TOUCH (read-only awareness)

Claude side has these LIVE:
- **SageMaker training**: M5 SimCSE (InProgress, 12h cap) / M11 multitask (Day 1 + 7-job chain) / M7 KG completion 4-model (TransE + RotatE + ComplEx + ConvE)
- **EC2 GPU**: g4dn.4xlarge × 1 + g4dn.12xlarge × 1 (Lane A)
- **OpenSearch**: jpcite-xfact-2026-05 (9-node cluster, 595K docs indexed)
- **Quota**: G+VT Spot vCPU 64 → 256 approved (case 177898005900961)
- **Budget**: $19,490 never-reach, $18,900 Budget Action STANDBY, 4-line CW alarm OK
- **EventBridge**: Lane D/E DISABLED (pure-burn 停止確認済), burn-metric-5min ENABLED

If CodeX needs AWS data for tests: use **mock** or **fixture**, never live API.

---

## 15. Acceptance criteria

CodeX session is **done with Phase 0-1** when:
- [ ] 6 Phase 0 agents all completed, audit docs landed
- [ ] 51 test fail → 0 (or 0-5 with explicit Claude-side dependency listed)
- [ ] mypy strict 0 (botocore.auth fixed)
- [ ] ruff 0
- [ ] Production gate 7/7 (or 6/7 with 1 explicit Claude-side gate)
- [ ] Wave 50 RC1 + Wave 51 dim K-S/L1-L6 verify passing

CodeX session is **done with Phase 2** when:
- [ ] Coverage project-wide 26% → 50%+
- [ ] E2E test 10+ scenarios PASS
- [ ] Flaky tests 0

CodeX session is **done with Phase 3** when:
- [ ] v0.6.0 version bump committed
- [ ] CHANGELOG v0.6.0 written
- [ ] Release notes published
- [ ] OpenAPI + static site regenerated
- [ ] Final smoke + ready-to-tag manifest

---

**End of CodeX Handoff. Paste this entire file into CodeX session-start prompt.**
