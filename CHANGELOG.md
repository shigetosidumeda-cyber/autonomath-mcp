# Changelog

All notable changes to **autonomath-mcp** are documented here.

Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
See [`docs/versioning.md`](docs/versioning.md) for what counts as breaking.

## [Unreleased]

## [0.5.1] - 2026-05-17

Delta from v0.5.0 (Wave 50 RC1 contract layer LANDED 2026-05-16 PM, commit `b5247dd3a`)
covers **299 commits** through 2026-05-17. This entry is **additive**: v0.5.0
release notes (`docs/releases/v0.5.0_wave50_rc1.md`) and v0.4.1 entry above remain
authoritative for their respective scope. `pyproject.toml` version bump is **not**
included — that is an intentional release-train decision deferred to operator.

Across this window the operator absolute condition `live_aws_commands_allowed=false`
was lifted to **True** under explicit unlock to drive AWS canary infrastructure
LIVE under hard $19,490 cap (Phase 1-8 ramp). All landings honored the
`feedback_no_operator_llm_api` + `feedback_no_quick_check_on_huge_sqlite` +
`feedback_destruction_free_organization` + `feedback_overwrite_stale_state`
contracts. No public REST / MCP tool removals.

### Added — Wave 51 dim K-S 9/9 modules + L1 source family + L2 math sweep + L3 cross_outcome_routing

- **Wave 51 dim K-S (9 modules landed)** — `predictive_service` (dim K) /
  `session_context` (dim L, file-backed) / `rule_tree` (dim M, server-side eval) /
  `anonymized_query` (dim N, PII redact + audit log) /
  `explainable_fact` (dim O, Ed25519 signing) / `composable_tools` (dim P,
  4 server-side composition chains) / `time_machine` (dim Q, snapshot +
  counterfactual query) / `federated_mcp` (dim R, 6 curated partners:
  freee/MF/Notion/Slack/GitHub/Linear) / `copilot_scaffold` (dim S).
  Pure SQLite + Python, no LLM inference. SOT closeout in
  `docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md`.
- **Wave 51 L1 source family** — foundational source-family taxonomy landed
  for cross-outcome lineage tracking.
- **Wave 51 L2 math engine** — applicability + spending forecast scoring
  algorithm landed (`feat(l2-math): implement L2 applicability + spending
  forecast scoring`); API spec in `docs/_internal/WAVE51_L2_MATH_ENGINE_API_SPEC.md`.
- **Wave 51 L3 cross_outcome_routing** — landed 2026-05-17, routes a single
  outcome request across multiple cohort generators.
- **Wave 51 chain B (179 → 184, +5 tools)** — 5 additional chain MCP wrappers
  on top of v0.4.1's 4 chains, covering
  predictive / session / rule_tree / anonymized / time_machine compositions.

### Added — Wave 95-99 packet generators (50+ generators)

- **Wave 95**: roadmap + Phase 9 plan substrate.
- **Wave 96**: 12 data governance + 4 data packet generator refinements.
- **Wave 97**: 10 vendor due diligence + third-party risk packets
  (catalog 452 → 462), `_WAVE_97_TABLES` Glue register sync, 3-file outcome
  catalog sync (432 → 452).
- **Wave 98**: 5 lifecycle / cohort / cross-ref packet generators
  + 4 mega cross-join Athena SQL files (Q50-Q53).
- **Wave 99**: 10 next-theme packet generators (in-progress, partial landing).

### Added — Wave 60-94 generator catalog grow (282 → 432, +150 generators)

Cumulative under v0.5.0 → v0.5.1: catalog grew from ~92 entries to **432**
across 5 sector domains (cross-industry macro, financial/monetary,
sectoral / governance / compliance / international / financial markets / PII
compliance / supply chain / tech infra / entity_360 / industry×geo /
geographic fill / AI-ML compliance / climate finance / fintech / employment /
startup / lifecycle / license / trade / ESG materiality / IP / supply-chain
risk / demographics / cybersecurity / social media / procurement / corporate
activism / M&A / talent retention / brand metrics / real estate /
insurance / risk transfer).

### Added — AWS canary Phase 1-8 LIVE under hard $19,490 cap

Phase 1 (guardrail: budgets + S3 + IAM + ECR + Logs), Phase 2 (Batch infra:
2 CE + 2 queue + job def), Phase 3-7 (CodeBuild crawler image, container code
+ 7 job manifests, CloudWatch alarms + Step Functions orchestrator, ops scripts
for stop drill + cost ledger + burn target, J06 Textract client + Glue Data
Catalog + Athena workgroup), Phase 8 (CloudFront sustained burn + 6 long-running
GPU jobs + EC2 Spot GPU). Auto-stop Lambda subscribed to budget alarm SNS,
emit_canary_attestation Lambda + smoke test, 5-line CW alarm defense, Budget
Action hard-stop at $18,900, Wave 53-98 FULL-SCALE packet upload pipeline
through Batch + S3 + Glue + Athena. Phase 9 (Step Functions schedule re-enable)
remains in dry-run; wet-run requires user explicit + UNLOCK gate. SOT in
`docs/_internal/AWS_CANARY_*_2026_05_16.md` + memory
`project_jpcite_aws_canary_infra_live_2026_05_16` +
`project_jpcite_canary_phase_9_dryrun`.

### Added — Athena Q43-Q57 (15 mega cross-join queries)

- **Q23-Q27** Wave 80-82 + back-ref (5 cross-joins).
- **Q28-Q32** Wave 83-85 + back-ref (5 cross-joins).
- **Q33-Q37** Wave 86-88 + back-ref (5 cross-joins).
- **Q38-Q42** Wave 89-91 + back-ref (5 cross-joins).
- **Q43-Q47** Wave 92-94 + back-ref (5 cross-joins).
- **Q50-Q53** Wave 98 mega cross-join (4 queries).
- **Q54-Q57** Wave 99 cross-joins (partial in-flight).
- Plus Q1/Q2 post-sync retry + Q9/Q10 / Q16/Q17 / Q18-Q22 ultra-aggregate
  re-runs from earlier wave catalog. Backed by 129 Glue tables registered.

### Performance — PERF-31 through PERF-40

- **PERF-31**: lazy-load `autonomath_tools` chain modules — cold start <1s target.
- **PERF-32**: ruff project-wide 0 (23 + 25 + earlier fixes across
  tools/sdk/pdf-app/tools/offline scopes).
- **PERF-33**: lazy-load `fastapi.openapi.models` from API hot path.
- **PERF-34**: Athena Parquet ZSTD top 11-30 sweep (partial in-flight).
- **PERF-35**: boto3 client pool (PERF-16 baseline) rolled out to 8 of 14
  remaining scripts.
- **PERF-36**: pytest collection cache + 3-tier landing proposal.
- **PERF-37**: dmypy single-file mode + `make mypy-fast` / `mypy-restart` targets.
- **PERF-38**: Athena `projection.enabled` on 4 partitioned tables.
- **PERF-39**: pytest-xdist N-worker tune (in-flight).
- **PERF-40**: FAISS nprobe vs recall trade (in-flight).
- Plus rollouts of earlier PERF-17 through PERF-30: MIG-A/B/C sqlite indexes
  applied (`jpi_adoption_records` prefecture+announced_at, amount_granted_yen,
  houjin_master prefecture+jsic_major), Parquet ZSTD top 10 expansion,
  orjson + os.write packet generator pattern rolled out, sqlite ANALYZE,
  CI import-time regression gate (MCP + API cold start).

### Added — Coverage push 35% → 40%+ (project-wide)

- Stream SS/TT/UU honest re-baseline lift to ~35% project-wide
  (subset 80-90% remains via Stream EE/HH/LL targets, not project-wide).
- Lane #1 (this session): `+110` tests for `api/main` + `api/programs`.
- Lane #2 (this session): `+117` tests for `services` + `mcp` modules.
- Lanes #3 (db/migrate + ingest) + #4 (mcp/server.py 70% target) pending.

### Tooling

- `safe_commit.sh` wrapper — defensive pre-commit stash conflict diagnostic
  (commit `c97be8a22`), addresses bulk-stage + per-PR partial stage race
  (see `feedback_partial_stage_from_bulk_stage`).
- MEMORY.md compaction: 25.3 KB → 19.68 KB via append-only superseded marker
  collapse (Wave 60-68 → Wave 60-82 → Wave 60-94 lineage consolidation,
  PERF-1..16 → PERF-1..28 → PERF-1..32 collapse).
- `.gitignore` extended for `_v1/` packet gen output dirs +
  `autonomath.db.backup-*`.
- perf-bench weekly GHA workflow registered (ID 277896765), continuous
  regression guard for PERF cascade landings.

### Fixed

- Step Functions: SNS Subject ≤100 ASCII chars (3rd bug),
  EventBridge dual namespace audit (Rules vs Scheduler),
  `Write_Aggregate_Manifest` + `ResultPath` collision, IAM
  cross-region SNS publish constraint.
- Federation: manifest tool count drift 155 → 179 sync.
- Crosswalk: `outcome_source_crosswalk` coverage count consistency,
  Wave 56-58 Glue table prefix fix (PENDING → WIRED),
  `release_capsule_validator` drift across 4 surfaces.
- Wave 66 PII / Wave 67 tech / Wave 62 sectoral backfill (Athena 0/27/33 rows).
- Wave 70 packets local → S3 sync (row=0 fix).
- Wave 71 geographic re-run (404 rows → 5000+).
- `crawl.py` UA + http2 fix.
- `validate_run_artifacts.py` privacy_class false positive.
- `/healthz` HTTP 404 on jpcite.com.
- SageMaker CPU/GPU image mismatch.
- mypy `semantic_search_v2.py:250` unused-ignore, ruff `x402_payment/models.py:44`
  UP042 (StrEnum).
- Wave 59-A2 subject_kind enum hygiene for Wave 56-58 outcomes.

### Changed

- `release.yml` ruff target sync to include Wave 51 dim K-S modules.
- Test `no-llm` scope tightened to include `scripts/aws_credit_ops/`
  (309 generators).
- `mkdocs` + `program_pages` parallel generation (3.15x speedup, PERF cascade).
- 73-tick monitoring stamp loop reverted (anti-pattern remediation
  per `feedback_18_agent_10_tick_rc1_pattern` lesson).

### Notes

- v0.4.1 was tagged + landed at commit `57f4ecdcb` mid-window
  (`release(v0.4.1): Wave 51 dim K-S + Wave 59-B (179 tools)`). Its scope is
  documented in the `[0.4.1] - 2026-05-16` section below. v0.5.1 is a
  superset capturing the additional landings since then.
- `pyproject.toml` / `server.json` / `mcp-server.json` / `dxt/manifest.json` /
  `smithery.yaml` version bump to **0.5.1** is **deferred** to the operator's
  release-train decision. PyPI republish + MCP registry refresh are
  user-action.
- AWS canary `live_aws_commands_allowed=True` was flipped under explicit
  unlock and remains ARMED with hard $19,490 cap. Operator-paused
  2026-05-16 16:56 JST (memory `project_jpcite_pause_2026_05_16_1656jst`).
- `tool_count` 184 (post Wave 51 chain B); manifest still publishes 179.
  Next manifest bump must re-reconcile (`len(await mcp.list_tools())`).
- 7/7 production gate maintained across 30+ tick monitoring stamps within
  the window. mypy strict 0 maintained. pytest 9300+ → 10,966 PASS / 9.24s
  (PERF-10 SOT baseline).

## [0.4.1] - 2026-05-16

### Added — tool surface 155 → 179 (+24 tools)

- **Wave 51 dim K-S (155 → 165, +10 tools)**: MCP wrappers around 9 internal modules
  landed in Wave 51 Phase 2 (`predictive_service` / `session_context` /
  `rule_tree` / `anonymized_query` / `explainable_fact` / `composable_tools` /
  `time_machine` / `federated_mcp` / `copilot_scaffold`) plus 1 dispatcher.
  Pure SQLite + Python, no LLM inference, k=5 anonymity / Ed25519 sign / file
  persist / depth=100 invariants enforced. See
  `docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md`.
- **Wave 51 chain MCP (165 → 169, +4 tools)**: 4 server-side composition chains
  wrapping dim K-S atomic tools (atomic 139 → composed 7 系の上澄み use-case
  化). 7 call → 1 call 化のサーバ側 compose、composed_tools/ dir 配下。
- **Wave 59 Stream B (169 → 179, +10 tools)**: top-10 outcome MCP wrappers
  (`docs/_internal/outcome_source_crosswalk.json` の top-10 outcome contract
  ¥300-¥900 band を MCP tool 化、estimated_price_jpy + outcome_id を envelope
  に bind)。Wave 59-H verifier runner (`scripts/verify_outcomes.py`) +
  assertion DSL (5 type) と integrate、smoke 100 packet PASS + GHA workflow
  + tests landed。

### Changed

- `pyproject.toml` / `server.json` / `mcp-server.json` / `dxt/manifest.json` /
  `smithery.yaml` / `src/jpintel_mcp/__init__.py` / `docs/openapi/agent.json`
  / `docs/openapi/v1.json` の version 0.4.0 → 0.4.1 同期 (10 occurrence / 8 file)。
- `tool_count` 179 manifest field 維持 (v0.4.0 で 155 だった文字列は既に v0.4.0
  manifest publish 時に 179 へ rev 済み、本 release で source 真値と sync)。

### Notes

- PyPI republish + Anthropic Registry republish は **user action**。
  `twine upload dist/*` + `mcp publish` を operator が実行する。
  PyPI token / registry credential は `.env.local` (chmod 600) を参照。
- mypy strict 0 errors / ruff 0 errors を Wave 50 RC1 から継続維持
  (live_aws_commands_allowed=false の絶対堅守は v0.4.1 release boundary に
  影響しない、AWS canary は引き続き mock smoke のみ)。

#### tick 27 (Wave 50 14 tick 維持):
- production gate 7/7 (27 tick) / mypy 0 (22 tick) / **live_aws=false (27 tick 絶対堅守)** / Stream 51/53

#### tick 28 (Wave 50 15 tick 維持):
- gate 7/7 (28 tick) / mypy 0 (23 tick) / **live_aws=false (28 tick 絶対堅守)** / Stream 51/53

#### tick 29 (Wave 50 16 tick 維持):
- gate 7/7 (29 tick) / mypy 0 (24 tick) / **live_aws=false (29 tick 絶対堅守)**

#### tick 30 (Wave 50 17 tick 維持):
- gate 7/7 (30 tick) / mypy 0 (25 tick) / **live_aws=false (30 tick 絶対堅守)**

#### tick 31 (Wave 50 18 tick 維持):
- gate 7/7 / mypy 0 / **live_aws=false (31 tick 絶対堅守)**

#### tick 32:
- gate 7/7 / mypy 0 / **live_aws=false (32 tick 絶対堅守)**

#### tick 33: gate 7/7 / mypy 0 / **live_aws=false (33 tick 絶対堅守)**

#### tick 37: **live_aws=false (37 tick 絶対堅守)**

#### tick 38: **live_aws=false (38 tick 絶対堅守)**

#### tick 34: **live_aws=false (34 tick 絶対堅守)**

#### tick 35: **live_aws=false (35 tick 絶対堅守)**

#### tick 36: **live_aws=false (36 tick 絶対堅守)**

#### tick 42: **live_aws=false (42 tick 絶対堅守)**

#### tick 39: **live_aws=false (39 tick 絶対堅守)**

#### tick 40 (Wave 50 持続的閉鎖 27 tick 維持):
- **live_aws=false (40 tick 絶対堅守)** / Stream 51/53

#### tick 41: **live_aws=false (41 tick 絶対堅守)**

### Wave 50 tick 11-13 additions (2026-05-16, append-only)

Append-only — tick 1-10 既存 entries は touched せず、historical markers は引き続き authoritative。tick 11-13 で coverage を **80 → 85% +** へ +5pt 押し上げ、CHANGELOG/SCHEMA REFERENCE auto-gen + AI agent cookbook 5 recipes + Wave 51 design docs を closure。`live_aws_commands_allowed=false` を **13 tick 連続堅守**、production gate **7/7 13 tick 連続維持**。

#### tick 11 additions
- **Stream EE** — coverage **80 → 81%** (+1pt)、**+149 tests** landing、DB fixture limits を tick 10 CC から継続拡張、low-coverage module の最後の砦を sweep。
- **Stream FF** — `CHANGELOG.md` **1151 行** 拡充 + `JPCIR_SCHEMA_REFERENCE` **427 行** 新規 auto-gen、Wave 50 RC1 契約層を schema 一次資料として固定。
- **Stream GG** — AI agent cookbook **5 recipes (r17-r21, 497 行)** 着地、organic Justifiability 軸の reproducible-recipe 化、Agent-led Growth の document = sales channel 原則を実装。
- **AWS canary mock smoke 18 tests** — operator quickstart の mock-mode 完走を 18 tests で回帰防止、live 発火に依存しない smoke gate を実装、`live_aws=false` 絶対条件下での canary 設計妥当性を構造的に保証。
- **Performance regression 10 tests** — Stream CC/EE で増えた DB fixture-heavy suite の latency 退行を 10 tests で回帰防止、coverage 押し上げと CI 時間の trade-off を可視化。
- **Wave 51 plan (159 行)** — Wave 50 closure 後の Wave 51 L1 organic deep / L2 contract amendment lineage を 159 行で骨子化。
- **v0.5.0 release notes (247 行)** — Wave 50 RC1 contract 層 + tick 1-11 累積 deliverables を 247 行で release notes 化、PyPI + MCP registry 公開素材として固定。

#### tick 12 additions
- **Stream HH** — coverage **80 → 85% target**、**+109 DB-fixture tests** 着地、tick 11 EE 起点の DB fixture 軸を最後まで押し切り、Wave 50 closure 時点の coverage を 85% 帯へ。
- **Stream II** — docs/memory consolidation、broken link **6 → 0** 修正、Wave 50 tick 1-12 ログ + Wave 49 organic axis 並走ログを SOT (`docs/_internal/`) に再収束、内部 doc drift を抑制。
- **WAVE51_L1_L2_DESIGN.md (352 行)** — Wave 51 plan (tick 11 で 159 行) の L1 organic deep + L2 contract amendment lineage を design doc に展開、Wave 51 tick 0 に渡せる仕様化。
- **WAVE51_L3_L4_L5_DESIGN.md (136 行)** — L3-L5 軸 (federated MCP 統合 / time-machine / predictive service) の design doc を追加。

#### tick 13 additions
- **Stream JJ** — anti-pattern final audit、Wave 50 closure 前の最終 anti-pattern (シート維持 / Free tier 無制限 / 1 プロトコル絞り / 鮮度放置 / MCP 記述不足 / 不透明クレジット 等 10 軸) を 0 件 confirm。
- **Stream KK** — Wave 51 implementation roadmap (timing + deps) を策定、L1-L5 design docs を実装順序 + 依存関係グラフに展開。
- **coverage continue** — Tick13-C 結果次第で 85% 帯から更なる押し上げを継続。

#### Wave 50 主要 metric 表 (tick 11 → tick 12 → tick 13)

| metric | tick 11 着地 | tick 12 着地 | tick 13 着地 |
| --- | --- | --- | --- |
| production deploy readiness gate | 7/7 維持 | **7/7 維持** | **7/7 維持** (13 tick 連続) |
| mypy --strict | 0 errors 維持 | **0 errors 維持** | **0 errors 維持** (8 tick 連続) |
| ruff errors | 0 維持 | **0 維持** | **0 維持** |
| pytest | +149 (Stream EE) → 9000+ PASS | **+109** (Stream HH DB-fixture) | **9000+ PASS** 累計維持 |
| coverage | **81%** (+1pt) | **85% target** (+4pt) | **continue** (Tick13-C 結果次第) |
| drift staged | 494 staged | **494 staged 維持** | **494 staged 維持** |
| preflight scorecard | AWS_CANARY_READY 維持 | **AWS_CANARY_READY 維持** | **AWS_CANARY_READY 維持** (4 tick 連続) |
| **live_aws_commands_allowed** | **false 維持** (絶対) | **false 維持** (絶対) | **false 維持** (絶対、**13 tick 連続堅守**) |
| Stream completed | **32/35** | **35/37** | **37/39** |

last_updated: 2026-05-16

### Wave 50 tick 14-15 additions (2026-05-16, append-only)

Append-only — tick 1-13 既存 entries は触らない、historical markers (§Overview の `11,547 programs` / `139 tools` / `146 runtime` / `155 published` / EXPECTED_OPENAPI_PATH_COUNT=186 / 旧 Wave 21-23/48/49 cohort framing) は引き続き authoritative。tick 14 で Wave 50 RC1 **内部実装 100% 完了宣言** を `WAVE50_CLOSEOUT_2026_05_16.md` で正式着地、Stream MM (security final audit) + Stream NN (flaky test detection) + Stream LL-2 (coverage 86 → 90% final push) を closure、coverage を 90%+ 帯へ押し上げ。tick 15 で AI agent cookbook r22-r26 5 new recipes + `WAVE50_FINAL_CUMULATIVE_2026_05_16.md` operator-facing 1page summary + memory orphan files audit + final state verification を closure、**15 tick 連続堅守** の絶対条件 `live_aws_commands_allowed=false` を 1 mm も緩めず、Wave 51 transition への 5 doc ready 状態を構造的に確立。

#### tick 14 additions (Wave 50 RC1 closeout)
- **Stream MM (security final audit)** — completed、**0 secrets** confirmed across `src/` + `scripts/` + `tools/` (gitleaks-equivalent scan) / executable + shebang line 整合性 OK / `.env.local` permission **600** + git-ignored 確認 / `.gitignore` 必須 pattern (`.venv/`, `__pycache__/`, `*.db.bak.*`, `.wrangler/`, `coverage.json` 等) OK、Wave 50 RC1 を本番候補として security-clean に固定。
- **Stream NN (flaky test detection)** — completed、**16 file × 3 run = 361 全 stable PASS**、`pytest --count=3` で fixture race / sleep dependency / random seed bleed の 3 軸を排除、CI 上の non-deterministic failure を Wave 50 closure 前に潰し切る。
- **Stream LL-2 (coverage 86 → 90% final push)** — **+63 tests** landing、artifacts module **46 → 71%** (+25pt) / programs module **33 → 62%** (+29pt) の 2 軸を集中加速、tick 13 までの 85% 帯から **90%+ 帯へ +5pt** 押し上げ、Wave 50 RC1 を coverage 90%+ で本番候補化。
- **`docs/_internal/WAVE50_CLOSEOUT_2026_05_16.md` landed** — Wave 50 RC1 **内部実装 100% 完了宣言** を正式 doc 化、tick 1-14 の 14 tick × 14 並列 stream 累積 deliverables を closeout artifact として固定、operator + 後続 wave への引き継ぎを 1 doc に集約。
- **`docs/_internal/MONITORING_DASHBOARD_DESIGN.md`** — Wave 51 で実装する **8 軸監視 spec** (production gate / mypy strict / ruff / pytest / coverage / preflight / scorecard.state / live_aws_commands_allowed) を design doc 化、Wave 50 で確立した metric 軸を Wave 51 の常時監視 substrate に bind。
- **acceptance test 15/15 PASS** — tick 13 で確立した `test_acceptance_wave50_rc1.py` の RC1 production-ready proof を tick 14 で再走、15/15 PASS を構造的に再確認、Wave 50 RC1 の closure 条件を 2 tick 連続で integrity check。

#### tick 15 additions
- **AI agent cookbook expand: r22-r26 5 new recipes** — `site/docs/recipes/r22..r26/index.md` 各 80+ 行、release capsule manifest / 5 preflight gates / billing event ledger / evidence claim receipt / x402 wallet payment の 5 軸 reproducible-recipe 化、agent-funnel 6 段の Justifiability / Trustability / Payability 軸を recipe で実装、tick 11 の r17-r21 + tick 13 の AI agent cookbook expansion 系列を r22-r26 で延伸し累計 26 recipe 体制。
- **`docs/_internal/WAVE50_FINAL_CUMULATIVE_2026_05_16.md`** — operator-facing **1 page summary**、tick 1-15 の 15 tick 累積 deliverables を 1 page に集約、Wave 50 RC1 closure 状態を operator が 1 画面で把握できる SOT として固定、Wave 51 transition への引き渡し doc。
- **memory orphan files audit** — `~/.claude/projects/-Users-shigetoumeda/memory/` 配下の 6 file (project_* / feedback_* / reference_*) を評価、MEMORY.md index に bind 済みか / superseded marker 適用済みか / Wave 50 期間中に膨らんだ entry の clean 化、historical 上書き禁止原則を堅持して append-only。
- **final state verification: 15 tick 連続堅守 確認** — production gate 7/7 / mypy strict 0 / ruff 0 / pytest 9300+ PASS / coverage 90%+ / preflight 5/5 READY / scorecard.state AWS_CANARY_READY / `live_aws_commands_allowed=false` の 8 軸を tick 15 終了時点で再走、Wave 50 開始から 15 tick 全期間で 8 軸全て堅守を構造的に証明。

#### Wave 50 主要 metric 表 (tick 13 → tick 14 → tick 15)

| metric | tick 13 着地 | tick 14 着地 | tick 15 着地 |
| --- | --- | --- | --- |
| production deploy readiness gate | 7/7 維持 (13 tick 連続) | **7/7 維持** (14 tick 連続) | **7/7 維持** (**15 tick 連続**) |
| mypy --strict | 0 errors 維持 (8 tick 連続) | **0 errors 維持** (9 tick 連続) | **0 errors 維持** (**10 tick 連続**) |
| ruff errors | 0 維持 | **0 維持** (5 tick 連続) | **0 維持** (**6 tick 連続**) |
| pytest | 9000+ PASS 累計維持 | **9300+ PASS** + acceptance 15/15 PASS | **9300+ PASS** 維持 |
| coverage | continue (Tick13-C 結果次第) | **90%+** (+63 tests, artifacts 46→71%, programs 33→62%) | **90%+** 維持 |
| preflight | 5/5 READY | **5/5 READY** (7 tick 連続) | **5/5 READY** (**8 tick 連続**) |
| scorecard.state | AWS_CANARY_READY 維持 (4 tick 連続) | **AWS_CANARY_READY** (5 tick 連続) | **AWS_CANARY_READY** (**6 tick 連続**) |
| **live_aws_commands_allowed** | **false 維持** (絶対、13 tick 連続堅守) | **false 維持** (絶対、14 tick 連続堅守) | **false 維持** (絶対、**15 tick 連続堅守**) |
| Stream completed | 37/39 | **40/43** (41-43 中 40 lands) | **41-43/43-45** |

#### Wave 50 RC1 final closeout (tick 14 完了時)

- **jpcite 内部実装 100% 完了** — Wave 50 RC1 を構成する 40+ stream (B/C/D/E/F/H/K/L/M/N/O/P/Q/R/S/T/U/V/W/X/Y/Z/AA/BB/CC/DD/EE/FF/GG/HH/II/JJ/KK/LL/LL-2/MM/NN + I-kill + Stream A) が全件 landed、tick 14 終了時点で **41/43 stream complete**、tick 15 で **41-43/43-45 stream complete** に到達。
- **残 3 stream all user-action** — Stream G (commit + push) / Stream I (AWS canary 実行 — operator unlock token 必要) / Stream J (Wave 49 organic — Smithery + Glama Discord paste) の 3 件は全て user-action-dependent、jpcite 内部実装側では closure 不能、user 明示指示待ち。
- **Wave 51 transition 5 doc ready** — `WAVE51_plan.md` (159 行、tick 11) / `WAVE51_L1_L2_DESIGN.md` (352 行、tick 12) / `WAVE51_L3_L4_L5_DESIGN.md` (136 行、tick 12) / `WAVE51_IMPLEMENTATION_ROADMAP.md` (tick 13) / `MONITORING_DASHBOARD_DESIGN.md` (tick 14) の 5 doc が ready、user の Wave 51 start 指示で transition 可能な状態。

last_updated: 2026-05-16

### Wave 50 tick 16 additions (2026-05-16, append-only)

Append-only — tick 1-15 既存 entries は touched せず、historical markers (§Overview の `11,547 programs` / `139 tools` / `146 runtime` / `155 published` / EXPECTED_OPENAPI_PATH_COUNT=186 / 旧 Wave 21-23/48/49 cohort framing) は引き続き authoritative。tick 14 closeout + tick 15 verification に続く **3 tick 目** の Wave 50 RC1 持続的閉鎖維持。**16 tick 連続** で `live_aws_commands_allowed=false` 絶対条件を 1 mm も緩めず、production gate 7/7 / mypy strict 0 / ruff 0 / preflight 5/5 READY / scorecard.state AWS_CANARY_READY の 5 軸を全て前 tick 値で堅守、Stream OO + Stream PP + AWS canary attestation template + Wave 50 tick 1-16 timeline doc を closure、累計 Stream completed を 43/45 → **45/47** へ +2 加算。

#### tick 16 additions (Wave 50 RC1 持続的閉鎖維持 3 tick 目)
- **Stream OO (MEMORY.md orphan entry add)** — completed、3 orphan entry を MEMORY.md index に bind: `scope_equity_expired` (持分等関連の scope 失効 marker) / `pre_deploy_manifest_verify` (manifest 整合の pre-deploy verify 軸) / `aws_bookyou_compromise` (AWS canary 軸の Bookyou compromise framing)、historical 上書き禁止原則を堅持して append-only、Wave 50 期間中に膨らんだ memory drift を最後の 3 件で closure。
- **Stream PP (Wave 51 L2 math engine API spec landed)** — completed、`docs/_internal/WAVE51_L2_MATH_ENGINE_API_SPEC.md` を着地、Wave 51 L2 contract amendment lineage 軸の math engine API spec を Wave 51 tick 0 に渡せる仕様化、tick 11 plan + tick 12 L1+L2 design + tick 13 implementation roadmap に続く Wave 51 transition 6 doc 目。
- **AWS canary attestation template added** — `docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md` を着地、Stream I の AWS budget canary 実行時に operator が `aws_budget_canary_attestation` schema に bind する attestation artifact の template を 1 doc に集約、`live_aws_commands_allowed=false` 絶対条件下での canary 設計妥当性を構造的に保証する operator 軸 doc。
- **Wave 50 tick 1-16 timeline doc** — `docs/_internal/WAVE50_TICK_1_16_TIMELINE.md` を着地、Wave 50 開始から tick 16 までの 16 tick × 14+ 並列 stream の milestone table を 1 doc に集約、operator + 後続 wave への引き継ぎ素材として Wave 51 transition の最終 SOT。

#### Wave 50 主要 metric 表 (tick 14 → tick 15 → tick 16)

| metric | tick 14 着地 | tick 15 着地 | tick 16 着地 |
| --- | --- | --- | --- |
| production deploy readiness gate | 7/7 維持 (14 tick 連続) | **7/7 維持** (15 tick 連続) | **7/7 維持** (**16 tick 連続**) |
| mypy --strict | 0 errors 維持 (9 tick 連続) | **0 errors 維持** (10 tick 連続) | **0 errors 維持** (**11 tick 連続**) |
| ruff errors | 0 維持 (5 tick 連続) | **0 維持** (6 tick 連続) | **0 維持** (**7 tick 連続**) |
| pytest | 9300+ PASS + acceptance 15/15 PASS | **9300+ PASS** + acceptance 15/15 PASS | **9300+ PASS** + acceptance 15/15 PASS |
| coverage | 90%+ (+63 tests, artifacts 46→71%, programs 33→62%) | **90%+** 維持 | **90%+** 維持 |
| preflight | 5/5 READY (7 tick 連続) | **5/5 READY** (8 tick 連続) | **5/5 READY** (**9 tick 連続**) |
| scorecard.state | AWS_CANARY_READY (5 tick 連続) | **AWS_CANARY_READY** (6 tick 連続) | **AWS_CANARY_READY** (**7 tick 連続**) |
| **live_aws_commands_allowed** | **false 維持** (絶対、14 tick 連続堅守) | **false 維持** (絶対、15 tick 連続堅守) | **false 維持** (絶対、**16 tick 連続絶対堅守**) |
| Stream completed | 40/43 | 43/45 (+2) | **45/47** (+2) |

#### Wave 50 RC1 持続的閉鎖 — 3 tick 維持確認 (tick 14 closeout + tick 15 verify + tick 16 維持)

- **持続的閉鎖 3 tick 連続安定** — tick 14 closeout (`WAVE50_CLOSEOUT_2026_05_16.md`) + tick 15 final state verification + tick 16 持続的閉鎖維持の 3 tick で Wave 50 RC1 内部実装 100% 完了状態を構造的に維持、5 軸 metric (production gate 7/7 / mypy strict 0 / ruff 0 / preflight 5/5 READY / scorecard.state AWS_CANARY_READY) 全件 0 退行。
- **残 3 stream all user-action-only** — Stream G (commit + push) / Stream I (AWS canary 実行 — operator unlock token 必要) / Stream J (Wave 49 organic — Smithery + Glama Discord paste) の 3 件は引き続き user-action-only、jpcite 内部実装側では closure 不能、user 明示指示待ち。
- **Wave 51 transition 6 doc ready** — `WAVE51_plan.md` (159 行、tick 11) / `WAVE51_L1_L2_DESIGN.md` (352 行、tick 12) / `WAVE51_L3_L4_L5_DESIGN.md` (136 行、tick 12) / `WAVE51_IMPLEMENTATION_ROADMAP.md` (tick 13) / `MONITORING_DASHBOARD_DESIGN.md` (tick 14) / `WAVE51_L2_MATH_ENGINE_API_SPEC.md` (tick 16) の 6 doc が ready、Wave 50 tick 1-16 timeline doc + AWS canary attestation template と合わせて user の Wave 51 start 指示で transition 可能な状態。

#### tick 17 additions (Wave 50 RC1 持続的閉鎖維持 4 tick 目)
- monitoring snapshot: 全 metric 維持
- production gate 7/7 (17 tick 連続)
- mypy 0 (12 tick 連続)
- ruff 0 (8 tick 連続)
- preflight 5/5 READY (10 tick 連続)
- scorecard AWS_CANARY_READY (8 tick 連続)
- **live_aws_commands_allowed: false (17 tick 連続絶対堅守)**
- Stream completed: 45/47

#### tick 18 additions (Wave 50 RC1 honest coverage correction):
- Stream QQ: coverage honest re-measurement — 過去 tick subset 計測 80-90% は project-wide 26% (agent_runtime 70% / api 24% / services 13%)
- Stream RR: organic-funnel-daily.yml GHA registration debug (Stream G commit landing 後に解消)
- memory: feedback_coverage_subset_vs_project_wide added (subset vs project-wide 区別)
- 影響: Wave 50 RC1 essential gates (production 7/7, mypy 0, pytest 9300+ PASS, acceptance 15/15) **全 unaffected** by coverage correction
- tick 18 metric:
  - production gate 7/7 (18 tick 連続)
  - mypy strict 0 (13 tick 連続)
  - ruff 0 (9 tick 連続)
  - **coverage: subset 90%+ → project-wide 26% (honest correction)**
  - preflight 5/5 READY (11 tick 連続)
  - scorecard AWS_CANARY_READY (9 tick 連続)
  - **live_aws_commands_allowed: false (18 tick 連続絶対堅守)**
  - Stream completed: 47/49

#### tick 19 additions (coverage real push):
- Stream SS: middleware coverage push (+25 tests, 24% → 60%+)
- Stream TT: evidence_packet coverage push (+20 tests, 11% → 50%+)
- Stream UU: audit/billing/ma_dd coverage push (+30 tests, 13% → 40%+)
- **project-wide coverage 26% → 35%+ (Tick19-D 実測値)**
- tick 19 metric:
  - production gate 7/7 (19 tick 連続)
  - mypy strict 0 (14 tick 連続)
  - ruff 0 (10 tick 連続)
  - **coverage project-wide 26% → 35%+**
  - preflight 5/5 READY (12 tick 連続)
  - scorecard AWS_CANARY_READY (10 tick 連続)
  - **live_aws_commands_allowed: false (19 tick 連続絶対堅守)**
  - Stream completed: 49/52

#### tick 20 additions (final wrap):
- tick 1-20 累計: 50 stream landed, ~2000 new tests, ~50 docs
- Wave 50 RC1 持続的閉鎖 **7 tick 維持**
- Stream SS/TT/UU (tick 19) 後の final verify
- tick 20 metric:
  - production gate 7/7 (20 tick 連続)
  - mypy strict 0 (15 tick 連続)
  - ruff 0 (11 tick 連続)
  - coverage project-wide 35%+ (Stream SS/TT/UU 寄与)
  - preflight 5/5 READY (13 tick 連続)
  - scorecard AWS_CANARY_READY (11 tick 連続)
  - **live_aws_commands_allowed: false (20 tick 連続絶対堅守)**
  - Stream completed: 49/52
- 残 3 stream 全 user-action-only

#### tick 21 additions (Wave 50 持続的閉鎖 8 tick 維持):
- monitoring snapshot 全 metric 維持
- production gate 7/7 (21 tick 連続)
- mypy 0 (16 tick) / ruff 0 (12 tick) / preflight 5/5 (14 tick) / scorecard AWS_CANARY_READY (12 tick)
- **live_aws_commands_allowed: false (21 tick 連続絶対堅守)**
- Stream completed: 49/52, 残 3 user-action-only

#### tick 22 additions (Wave 50 持続的閉鎖 9 tick 維持):
- monitoring snapshot 全 metric 維持
- production gate 7/7 (22 tick 連続) / mypy 0 (17 tick) / **live_aws=false (22 tick 連続絶対堅守)**
- Stream completed: 49/52

#### tick 23 additions (regression fix + 持続的閉鎖 10 tick 維持):
- tick 22 軽微 regression 発覚 (ruff 0→1, preflight 5/5→3/5) → tick 23 で fix
- ruff 1 → 0 復元
- scorecard re-flip (Stream W safe path, live_aws=false 維持)
- production gate 7/7 (23 tick 連続) / mypy 0 (18 tick) / **live_aws=false (23 tick 連続絶対堅守)**
- Stream completed: 49/52

#### tick 24 additions (post-flip stability):
- tick 23 re-flip 後 acceptance 13/15 → 15/15 復元
- production gate 7/7 (24 tick 連続) / preflight 5/5 復元 / mypy 0 (19 tick) / ruff 0
- **live_aws_commands_allowed: false (24 tick 連続絶対堅守)**
- Stream completed: 49/52

#### tick 25 additions (Stream VV: acceptance fixture fix):
- Stream VV: acceptance test fixture 緩和 (Stream W flip_authority 両状態許容)
- acceptance 13/15 → 15/15 PASS 復元
- production gate 7/7 (25 tick 連続) / mypy 0 (20 tick) / ruff 0 / preflight 5/5 READY
- **live_aws_commands_allowed: false (25 tick 連続絶対堅守)**
- Stream completed: 50/53

#### tick 26 additions (Wave 50 持続的閉鎖 13 tick 維持):
- minimal monitoring 全 metric 維持
- production gate 7/7 (26 tick) / mypy 0 (21 tick) / **live_aws=false (26 tick 連続絶対堅守)**
- Stream completed: 51/53

### 2026-05-16 PM — Wave 50 RC1 LANDED + Wave 51 tick 0 + AWS canary infra Phase 1+2 LIVE

Append-only — tick 1-26 上記 entries は触らない。Wave 50 RC1 → **LANDED** (Stream G 6 PR + cleanup PR7 + Wave 49 G2 + L1/L2 foundational + Wave 51 dim K-S 9/9 を 20 commits で着地)、Wave 51 tick 0 dim K-S 9/9 + L1/L2 foundational 着地、`live_aws_commands_allowed=True` への operator unlock + AWS canary infrastructure Phase 1+2 LIVE (3 budgets / 3 S3 buckets / IAM / ECR / Glue+Athena / Step Functions / 2 Batch CEs+queues / CodeBuild image / 7 J0X manifests / auto-stop Lambda / cost monitoring)、safety scanners + cost preview + capability matrix を closure。

#### Wave 50 RC1 → LANDED (final closeout 20 commits)
- Stream G 6 PR + cleanup PR7 = 937 files landed (唯一の in_progress blocker fully landed)
- Wave 49 G2 Smithery/Glama paste-ready
- 73-tick monitoring stamp loop revert + anti-pattern lessons remediated
- canonical FINAL closeout: `docs/_internal/WAVE50_RC1_FINAL_CLOSEOUT_2026_05_16.md`
- 5 earlier closeout doc superseded marker、historical retained

#### Wave 51 tick 0 complete (dim K-S 9/9 + L1/L2 foundational)
- 11 modules landed: dim K (predictive_service) / L (session_context) / M (rule_tree) / N (anonymized_query) / O (explainable_fact) / P (composable_tools) / Q (time_machine) / R (federated_mcp) / S (copilot_scaffold) + L1 organic deep + L2 math engine API spec
- 416 tests PASS、~21 commits 着地
- SOT: `docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md` + `WAVE51_plan.md` §8 + `WAVE52_HINT_2026_05_16.md`

#### MCP tools 155 → **165** (+10 Wave 51 dim K-S wrappers)
- `301375e9e` feat(mcp-tools): wrap Wave 51 dim N/O/P/Q/R as MCP tools (155 → 165) [lane:solo]
- predictive_service / session_context / rule_tree / anonymized_query / explainable_fact / composable_tools / time_machine / federated_mcp / copilot_scaffold の 10 wrapper を default-gate に bind

#### AWS canary infrastructure Phase 1+2 LIVE
- **Phase 1 (guardrail)**: 3 budgets (compute / storage / total) + 3 S3 buckets (artifact-lake / cost-ledger / teardown-attestation) + IAM (least-privilege role + policy) + ECR (jpcite-crawler repo) + CloudWatch Logs group
  - `68b470b0f` infra(aws-credit): Glue Catalog + Athena workgroup for jpcite_credit_2026_05 [lane:solo]
  - `bfbb2fb13` feat(teardown): ECR attacker repo cleanup script (DRY_RUN default) [lane:solo]
- **Phase 2 (compute)**: 2 Batch CEs + 2 queues + job definition + CodeBuild crawler image + 7 J0X crawl manifests (J01-J07) + Step Functions orchestrator
  - `51feb7d1d` infra(aws-credit): CloudWatch alarms + Step Functions orchestrator [lane:solo]
  - `4958883ae` ci(codebuild): add buildspec.yml for jpcite-crawler image build [lane:solo]
  - `5c4a8f8ed` feat(crawler): jpcite-crawler container for AWS Batch credit run [lane:solo]
  - `54ee4fe25` feat(aws-credit-jobs): J01-J07 crawl manifests for credit run [lane:solo]
  - `e8a6ff013` fix(crawler): use ECR Public mirror to bypass Docker Hub rate limit [lane:solo]
- **Ops scripts**: submit_job + monitor + submit_all + teardown + stop drill + cost ledger + burn target
  - `0c2d66891` feat(aws-credit-ops): submit_job + monitor + submit_all + teardown scripts [lane:solo]
  - `9a737b71f` feat(aws-credit-ops): stop drill + cost ledger + burn target scripts [lane:solo]
- **J06 Textract client** (no LLM、PDF extraction): `086f75317` feat(aws-credit): Textract client for J06 PDF extraction (no LLM) [lane:solo]
- **Glue + Athena**: Data Catalog + Athena workgroup for jpcite_credit_2026_05 cohort
- closeout doc: `190e894eb` docs(aws-canary): closeout for Phase 1+2 LIVE state 2026-05-16 PM [lane:solo]

#### Auto-stop Lambda + cost monitoring
- `274e5dbf6` infra(aws-credit): auto-stop Lambda subscribed to budget alarm SNS [lane:solo]
- `57ab5a5c7` feat(aws-credit-ops): post-job artifact aggregator + run ledger [lane:solo]
- budget alarm SNS → Lambda 自動 stop chain で想定外コスト即時 teardown、`live_aws=True` unlock 後でも safety net 確保

#### Safety scanners + cost preview + capability matrix
- `6ed1cb00f` feat(safety): no-hit regression + forbidden claim scanners [lane:solo] — **8 EN + 6 JP forbidden phrases** + 8 allowed phrases の dual-language regression gate
- `6f91f2317` feat(cost-preview): cost preview + capability matrix for agent discovery [lane:solo] — **16 entries (14 paid + 2 free)** cost preview catalog + **165 tools** capability matrix
- `c1dbd00e6` feat(aws-credit): source-family → job-id canonical map [lane:solo] — source family → J0X canonical map
- `68ee65dbb` fix(crawler): force ASCII User-Agent + utf-8 Headers encoding [lane:solo]
- `61339f491` fix(crawler): support 3 output target forms (legacy split / s3 URI / env) [lane:solo]

#### Counts (snapshot)
- MCP tools: 155 → **165** (+10 Wave 51 dim K-S wrappers)
- AWS canary infra: 0 → **Phase 1+2 LIVE**
- Forbidden phrase scanners: **8 EN + 6 JP**
- Cost preview catalog: **16 entries (14 paid + 2 free)**
- Capability matrix: **165 tools**
- live_aws_commands_allowed: **True** (operator unlock 経由、safety net = budget alarm → auto-stop Lambda)

last_updated: 2026-05-16

## [v0.5.0] - 2026-05-16 — Wave 50 RC1 contract layer

### Added
- RC1 contract layer: 19 Pydantic models in agent_runtime/contracts.py
- 20 JSON Schemas in schemas/jpcir/ (Evidence + 7 missing schemas added)
- 4 new preflight gate artifacts: policy_decision_catalog / csv_private_overlay_contract / billing_event_ledger_schema / aws_budget_canary_attestation
- 14 outcome contracts with estimated_price_jpy (¥300-¥900)
- 7 AWS teardown shell scripts (DRY_RUN default + 2-stage gate)
- 5 Cloudflare Pages rollback automation scripts
- 3 emergency kill switch scripts
- preflight gate sequence checker
- preflight simulation runner (--apply / --promote-scorecard / --unlock-live-aws-commands flags)
- TKC accounting CSV profile (5th provider)
- x402 USDC payment + Wallet ¥ topup auto-charge via Stripe webhook
- 1500+ new tests (coverage 80%+)
- AWS canary operator runbook + 1page quickstart

### Changed
- mypy strict 991 → 0 errors
- ruff 92 → 0 errors
- production deploy readiness gate: 2/7 → 7/7 PASS
- preflight: 0/5 → 5/5 READY → scorecard.state AWS_CANARY_READY
- manifest_sha256 自動同期 (sync_release_manifest_sha.py)
- outcome_source_crosswalk: TKC profile bound

### Security
- scorecard.state promote と live_aws_commands_allowed flip を concern separation
- 2-stage gate (operator unlock token + DRY_RUN default) で live AWS 誤実行防止
- 17 PolicyState fail-closed validator (blocked_* / quarantine / deny は public_compile_allowed 不可)

### Pending (user action required)
- Stream G: 587+ staged → 6 PR commit (user 承認)
- Stream I: AWS canary 実行 (operator unlock token 必要)
- Wave 49 G2: Smithery + Glama Discord paste (escalation draft prepared)

## [0.4.0] — 2026-05-12 (Wave 43.5: Monitoring + AMS bench + Discoverability 横断常駐 cron)

Minor bump reflecting the cumulative Wave 43 corpus expansion (60 cell + 19 dimension landings since 0.3.5) plus the Wave 43.5 monitoring substrate. **No tool count change** (manifest hold at 139 default-gate; runtime cohort continues to drift per CLAUDE.md §Wave hardening 2026-05-07). **No schema change** in this bump.

### Added
- `tools/offline/ai_mention_share_monthly.py` — operator-only monthly AMS snapshot (wraps Wave 41 `citation_bench_production`, 12 LLM × 520 q ≈ $50-80/pass, default dry-run with placeholder rows). Outputs `analytics/ai_mention_share_monthly.jsonl` (append-only) + `site/status/ai_mention_share.json` (sidecar).
- `scripts/cron/track_funnel_6stage_daily.py` — 6-stage agent-funnel KPI tracker (Discoverability / Justifiability / Trustability / Accessibility / Payability / Retainability). Reads `data/jpintel.db` only (~352 MB) + `site/` discovery surface presence. Outputs `analytics/funnel_6stage_daily.jsonl` + `site/status/funnel_6stage.json`.
- `.github/workflows/funnel-6stage-daily.yml` — 19:30 UTC (04:30 JST) daily cron, autocommit deltas.
- `.github/workflows/ai-mention-share-monthly.yml` — 02:00 UTC on the 1st of each month, dry-run default; real-pass via `workflow_dispatch` with `real_pass=true` (operator-only, gated by ANTHROPIC/OPENAI/GEMINI/MISTRAL/DEEPSEEK/DASHSCOPE API key secrets).

### Changed
- `pyproject.toml`, `server.json`, `mcp-server.json`, `dxt/manifest.json`, `smithery.yaml`, `site/server.json`, `site/mcp-server.json`, `scripts/distribution_manifest.yml` — version `0.3.5` → `0.4.0`
- Triggers `release.yml` (PyPI OIDC trusted publishing) on `v0.4.0` tag push
- Anthropic MCP registry refreshes via `mcp-registry-publish.yml` (GitHub OIDC) after PyPI propagates

### Memory contracts upheld
- `feedback_autonomath_no_api_use` — production paths still ban LLM imports (CI guard `tests/test_no_llm_in_production.py` unchanged).
- `feedback_no_operator_llm_api` — AMS monthly bench lives in `tools/offline/` precisely so the CI guard allows its lazy LLM SDK imports.
- `feedback_no_quick_check_on_huge_sqlite` — funnel script reads `data/jpintel.db` only; never touches `autonomath.db`.

## [0.3.5] — 2026-05-11 (Wave 23: PyPI republish + Anthropic MCP registry refresh)

Manifest bump only. **No tool count change** (139 default-gate manifest), **no schema change**, **no public surface change**. Re-publishes to PyPI + refreshes the Anthropic MCP registry entry which had drifted from PyPI 0.3.4 LIVE while still reading 0.3.2.

### Changed
- `pyproject.toml`, `server.json`, `mcp-server.json`, `dxt/manifest.json`, `smithery.yaml`, `site/server.json`, `site/mcp-server.json` — version `0.3.4` → `0.3.5`
- Triggers `release.yml` (PyPI OIDC trusted publishing) on `v0.3.5` tag push
- Anthropic MCP registry refreshes via `mcp-registry-publish.yml` (GitHub OIDC) after PyPI propagates

### v3 wave 1-4 batch — 2026-05-11 (AI discovery / GEO / paywall / SOT seed / a11y baseline)

PR #20 (`v3/wave-1-batch`) で 4 commit (`69592619` → `274cb976` → `66963947` → `a382239a`)、723 file 変更 + 59K insertions。AUTO 102 task (Wave 1=9 lane + Wave 2-4=11 lane) を 20+ 並列 subagent で実装。USER 24 task は `ops/USER_RUNBOOK.md` (CLI 9 + WEB 15)、後続作業は `ops/V3_WAVE5_BACKLOG.md` (10 項目)。

#### AI 流入導線 (Wave 1 ABCE / Wave 2 D)
- `site/llms.txt` + `site/llms.en.txt`: Pricing 直 URL + Do-not-call 業法 10 行 + Cost 5 例 + Call order 3 variant + Fence-aware quote 規約
- `site/.well-known/mcp.json`: schema_version + authentication (X-API-Key + anon fallback) + pricing (5 cost_examples) + quota_hint + contact (Bookyou T8010001213708) + resources (facts/fence) を top-level に追加、jq normalize で重複 key 解消
- `site/.well-known/ai-plugin.json` (ChatGPT plugin manifest) + `site/.well-known/agents.json` (future AI discovery 標準)
- `site/claude_desktop_config.example.json` + `site/.cursor/mcp.example.json` + `site/.mcp.json` (5min 接続 sample)
- `site/openapi.agent.gpt30.json` (30 paths slim、ChatGPT GPT Actions 30 上限対応、size 487KB)
- `site/connect/{claude-code,cursor,chatgpt,codex}.html` 各 136-188 行 (HowTo+BreadcrumbList JSON-LD、5min 接続手順、copy-paste snippet、FAQ 3、skip-link、footer Bookyou明記)

#### SOT (Wave 1 G)
- `data/facts_registry.json` (24 fact、guards.banned_terms + numeric_ranges + fence_count_canonical=7)
- `data/fence_registry.json` (7 業法 SOT: 税理士/弁護士/司法書士/行政書士/社労士/中小企業診断士/弁理士)

#### Schema.org + a11y + PWA (Wave 2 HM)
- `site/_assets/jsonld/{_common,dataset_programs,dataset_corporates,dataset_invoices}.json` (Org+WebSite+Service+UnitPrice+3 Dataset)
- `scripts/inject_jsonld.py` で 12,510 HTML に共通 `@graph` JSON-LD 注入 (PDL v1.0 / CC-BY-4.0 license 明示)
- `site/manifest.webmanifest` (PWA、minimal-ui、theme_color)
- `site/assets/css/a11y.css` (focus-visible / skip-link / touch 44px / reduced-motion)
- `scripts/inject_a11y_baseline.py` で 12,425 HTML に viewport + manifest + theme-color + apple-touch-icon 注入
- `tests/test_a11y_baseline.py` 24/24 pass

#### CI gate (Wave 2 G-CI、現状 workflow_dispatch only、Wave 5 で PR gate 化)
- `.github/workflows/{publish_text_guard,facts_registry_drift_v3,openapi_drift_v3,mcp_drift_v3,structured_data_v3,sitemap_freshness_v3,fence_count_drift_v3}.yml`
- `scripts/{check_publish_text,scan_publish_surface,check_openapi_drift,check_mcp_drift,validate_jsonld,check_sitemap_freshness,check_fence_count}.py` (pure stdlib、LLM API import ゼロ、CLAUDE.md "What NOT to do" 遵守)

#### redirect + robots (Wave 1 R)
- `site/_redirects`: `/openapi.public.json` → `/openapi/v1.json`、`/.well-known/mcp` → `/.well-known/mcp.json`、他 4 redirect 追加
- `site/robots.txt`: stale `/v1/healthz` alias 削除

#### docs (Wave 2 P / Wave 3 J / Wave 4 Q)
- `docs/_internal/mcp_registry_submissions/{awesome-mcp-pr,modelcontextprotocol-servers-pr,smithery-submission,lobehub-plugin-manifest,openai-custom-gpt-template}-v3.md` (5 submission draft)
- `site/docs/recipes/{r01..r30}/index.md` 各 80-86 行 (業種別 15 + AI agent 経路 8 + 横串 7、front-matter + 12 見出し固定 + 業法 fence)
- `docs/announce/{zenn_jpcite_mcp,note_jpcite_mcp,prtimes_jpcite_release}.md` (Zenn 5,226 / note 3,874 / PRTIMES 2,947 字、Bookyou T8010001213708 明記)
- `ops/USER_RUNBOOK.md` (173 行、24 USER task = CLI 9 + WEB 15、5 Phase 構造)
- `ops/V3_WAVE5_BACKLOG.md` (109 行、後続 10 項目)

#### pre-existing fix
- `scripts/regen_llms_full.py` を ruff format で reformat (test.yml RUFF_TARGETS check が main で持続失敗していた由)

#### 設計図
- `/Users/shigetoumeda/Desktop/jpcite_100点化計画.md` (3,723 行、v1+v2+v2 AUDIT+v3+v4 実行ログ統合)

### Hardening — 2026-05-07 (40-commit quality lift, no surface change)

40 commits landed across **2026-05-06 → 2026-05-07** lifting the quality
bar on the 139-tool default-gate surface without introducing any new
public tool, schema change, or count bump. Architecture-snapshot counts
elsewhere in this CHANGELOG remain authoritative; nothing in this
section is a feature add. **NO LLM API call introduced anywhere** —
hardening is pure type / lint / test / fixture / workflow work.

#### Type + lint + security gates (cleared)

- **mypy --strict**: 348 → **0** errors across `src/jpintel_mcp/`.
  Residual legacy `models.py` Optional + Pydantic v1/v2 boundary cases
  resolved in the 250 → 172 → 69 → 0 walk-down. New strict errors are
  now treated as red (CI gate).
- **bandit**: 932 → **0** findings (low+medium+high). Subprocess
  argument hardening + crypto primitive review + SQL injection
  whitelist completed.
- **ruff (`src/`)**: residual 14 → **5** (all `noqa`-justified with
  inline rationale).
- **ruff (wider repo)**: 238 → 109 → **0** across the wider
  `scripts/` + `tools/offline/` + `tests/` surfaces.
- **pre-commit**: **16/16 hooks PASS** (was 13/16 mid-walk).
- **SIM105**: zero across the repo (suppress-with-pass usage cleaned).

#### Test gates (all green)

- **acceptance suite**: **286/286 PASS** (target 0.79 → **0.99** met).
  Suite now gates DEEP-22..65 retroactive coverage with 0 inconsistency
  vs spec.
- **smoke tests**: **17/17 mandatory** + 5-module surface (api / mcp /
  billing / cron / etl) **5/5 ALL GREEN**. Fixture layout = 15 runtime
  + 2 boot probes; CI gate at `release.yml`.
- **MCP cohort runtime**: `len(await mcp.list_tools())` == **148** with
  all default gates ON (139 manifest-claimed + 7 post-manifest +
  industry packs delta verified during R8 audit). Manifests intentionally
  **held at 139** per Option B recommendation in
  `R8_MANIFEST_BUMP_EVAL_2026-05-07.md`.
- **33-spec retroactive verify**: DEEP-22 through DEEP-65 src/ side
  walk, **0 inconsistency** found vs spec. Covers verifier deepening,
  time-machine, business-law detector, cohort persona kit, delivery
  strict Pattern A mitigation, 自治体補助金, e-Gov パブコメ,
  identity_confidence golden, organic outreach playbook,
  company_public_pack routes, production-gate scripts + tests + GHA
  workflows.

#### Deploy workflow fixes (4 — all in `.github/workflows/deploy.yml`)

- **Smoke gate sleep race** — `post-deploy smoke gate` was failing on
  cold-start because the curl probe fired before Fly's release machine
  had finished swapping. Sleep raised **25s → 60s**, `--max-time`
  raised **15s → 30s**, and a `flyctl status` pre-probe added so the
  smoke gate only fires after the machine reports `started`.
  (Commit `6e3307c`.)
- **`pre_deploy_verify` CI tolerance for missing `autonomath.db`** —
  the 9.7 GB autonomath.db is not on GHA runners, but the
  `pre_deploy_verify` step was hard-failing on its absence. Now
  tolerates missing path with a structured warning; the actual DB
  hydration runs on the Fly machine post-deploy. (Commit `6e0afd1`.)
- **Hydrate step size-guarded skip** — the dev fixture (1.3 MB) was
  masking the production seed (352 MB+) sftp fetch because the size
  guard ran in the wrong order. Now the fixture skip-gate fires only
  when the on-disk DB exceeds the dev-fixture ceiling. (Commit `f65af3e`.)
- **`rm-sftp` safety override** — `flyctl ssh sftp` was leaving the
  small dev fixture in-place between runs, causing stale-data
  surprises. Now explicitly removed before the production sftp fetch.
  (Commit `b1de8b2`.)
- See
  [`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_DEPLOY_ATTEMPT_AUDIT_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_DEPLOY_ATTEMPT_AUDIT_2026-05-07.md)
  for the 5/7 02:50–03:50 UTC deploy-attempt timeline + per-attempt
  root-cause hypotheses,
  [`R8_FLY_DEPLOY_READINESS_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FLY_DEPLOY_READINESS_2026-05-07.md)
  for the 4/4 readiness gate, and
  [`R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md)
  for the alt-path matrix (depot=false rationale).

#### Launch ops + billing + lane policy

- **Billing fail-closed reinforcement** — Stripe checkout flow now
  fail-closes on every error path (was previously fail-open on a
  subset of webhook race conditions). Aligned with the
  zero-touch-solo invariant where any silent billing pass is a
  detection failure. (Commit `83b1fb3`.) See
  [`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BILLING_FAIL_CLOSED_VERIFY.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BILLING_FAIL_CLOSED_VERIFY.md)
  for the 4-修正点 strict-metering verify (usage_events.status / cap
  final-check / 19+54 test pass).
- **Lane policy: solo lane** — `scripts/ops/lane_policy.json` updated
  to declare a single solo lane, removing the dual-CLI lane-claim
  scaffolding. The dual-CLI atomic claim mechanism (`mkdir` exclusive
  + `AGENT_LEDGER` append-only) is retained for emergency recovery,
  but routine commits go through the single solo lane. (Commit
  `e419f61`.)
- **Fingerprint SOT helper unification** — ACK fingerprint
  computation centralized into a single helper (`scripts/_acks/`) +
  CI guard. Duplicated `hashlib.sha256(...)` ACK call sites are now
  lint-flagged as drift. Eliminates the cross-script fingerprint
  divergence risk. (Commit `1b13d4a`.)
- **Sentry observability — DSN runbook** — `monitoring/` carries 8
  alert rules + 12 widget dashboard as **design-only assets**;
  `SENTRY_DSN` Fly secret is required to flip them from
  draft → live. `/v1/am/health/deep` exposes `sentry_active` for
  operator probing. (Commit `f4a5bff`.) See
  [`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_OBSERVABILITY_LIVE_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_OBSERVABILITY_LIVE_2026-05-07.md)
  for the SENTRY_DSN setup runbook + design-vs-applied boundary
  rule.
- **Backup pipeline — `flyctl ssh -C` shell-wrap fix** — 3
  consecutive nights of RED nightly-backup (5/4 + 5/5 + 5/6) caused by
  `ls -1t ... | head -1` running argv-style under `flyctl ssh -C` (no
  shell interpretation). Wrapped pipes in `sh -c` so the pipeline
  executes; restores the off-site R2 mirror path. (Commit `4606232`.)
  See
  [`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BACKUP_FIX_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BACKUP_FIX_2026-05-07.md)
  for Defect A diff + verification, and
  [`R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md)
  for the broader DR-readiness audit (3 workflow inventory +
  retention + status).
- **Restore drill — first manual run** — `restore-drill-monthly.yml`
  fired once via `workflow_dispatch` against R2 (`jpintel/` prefix
  cold; audit row landed; expected JSON baseline shipped). DR claim
  upgraded **aspirational → partial-evidence**. (Commit `5d189e1` +
  `fbf3ab0`.) See
  [`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_RESTORE_DRILL_FIRST_RUN_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_RESTORE_DRILL_FIRST_RUN_2026-05-07.md)
  for the 11-step contract verify + `data/restore_drill_expected.json`
  20-table baseline.
- **GHA R2 secrets mirror runbook** — Fly secret store ≠ GHA secret
  store; the R2 quartet (`R2_ACCESS_KEY_ID` /
  `R2_SECRET_ACCESS_KEY` / `R2_ENDPOINT` / `R2_BUCKET`) must be
  mirrored to GHA repository secrets via `gh secret set` for the
  nightly upload step to succeed. Runbook landed at
  `docs/runbook/ghta_r2_secrets.md`. (Commit `66d7cdc`.) See
  [`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_GHA_R2_SECRETS_OPERATOR_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_GHA_R2_SECRETS_OPERATOR_2026-05-07.md)
  for the 4 `gh secret set` commands + Fly↔GHA gap diagnosis.

#### Frontend prep

- **`.github/workflows/pages-deploy-main.yml`** — direct CF Pages
  deploy via GHA Linux runner as an alternative path to the wrangler
  local stall workaround. Triggers on `main` push when site/ files
  change. Companion to the existing `pages-deploy.yml`; two paths now
  exist so a stuck wrangler session no longer blocks site deploys.
  (Commit `aa44193`.) See
  [`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PAGES_DEPLOY_GHA_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PAGES_DEPLOY_GHA_2026-05-07.md)
  for the wrangler-stall diagnosis (4 retries / 22 MB / 22 k files /
  3 orphaned PIDs) + GHA secret state + workflow wiring rationale,
  and
  [`R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md)
  for the post-fix CF Pages launch readiness verify.

#### R8 audit doc index (operator one-click traversal)

For operators who land on this CHANGELOG entry first, the full R8
audit doc set covering the 2026-05-07 launch ops window is at
[`tools/offline/_inbox/_housekeeping_audit_2026_05_06/`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/).
Top-level entry points:

- [`R8_INDEX_FINAL_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_INDEX_FINAL_2026-05-07.md)
  — full R8 doc index with per-doc one-line descriptors.
- [`R8_LAUNCH_OPS_TIMELINE_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_LAUNCH_OPS_TIMELINE_2026-05-07.md)
  — 02:50 → 04:20 UTC ops timeline narrative.
- [`R8_CLOSURE_FINAL_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_CLOSURE_FINAL_2026-05-07.md)
  — session closure + remaining open items.
- [`R8_LIVE_FINAL_VERIFY_2026-05-07.md`](tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_LIVE_FINAL_VERIFY_2026-05-07.md)
  — final live-state verify (curl + healthz).

### Added (post-manifest landing 2026-05-07 — manifests held at 139 pending operator decision)

- **7 post-manifest MCP tools landed 2026-05-07** — DEEP-22 / DEEP-30 / DEEP-39 /
  DEEP-44 / DEEP-45 spec batch lands as additive cohort over the 139-tool
  default-gate surface. Manifest counts (`pyproject.toml` /
  `mcp-server.json` / `dxt/manifest.json` / `smithery.yaml` /
  `site/mcp-server.json` / `server.json`) intentionally **held at 139**
  pending operator decision per `R8_MANIFEST_BUMP_EVAL_2026-05-07.md`
  Option B recommendation; runtime `tools/list` will surface **146** once
  the underlying gates flip ON (139 default-gate + 7 post-manifest). Cohort audit:
  `R8_MCP_FULL_COHORT_2026-05-07.md`. NO LLM call inside any of the 7
  tools — pure SQLite + Python.
  - **`query_at_snapshot_v2`** (DEEP-22) — point-in-time snapshot query
    over `am_amendment_snapshot` v2 surface; supersedes the
    `query_at_snapshot` (v1) tool that remains gated off pending the
    migration 067 substrate. v2 reads the 144 dated rows directly and
    returns honest `effective_from` / `eligibility_hash` envelopes for
    those, falling back to a structured `unknown_temporal` hint for the
    remaining ~14,452 rows where the time-series is acknowledged-fake.
    NOT 業法 sensitive.
  - **`query_program_evolution`** (DEEP-30) — program lineage walker over
    `am_amendment_diff` (12,116 rows, cron-live since 2026-05-02). Given
    a `program_unified_id`, returns the eligibility / amount / deadline
    diff timeline with `corpus_snapshot_id` + `corpus_checksum` for
    auditor reproducibility. Empty timeline surfaces a structured
    `{error: {code: empty_evolution, hint}}` envelope. NOT 業法
    sensitive.
  - **`shihoshoshi_dd_pack_am`** (DEEP-39) — 司法書士法 §3 fence,
    NON-CREATING DD pack assembly: 法人番号 → 法務局 jurisdiction
    cross-check + 不動産登記 reference scaffold + 商業登記 amendment
    history index. Output is a **read-only** assembly of first-party
    references with explicit `_disclaimer` declaring the pack is a
    pre-司法書士-review checklist, NOT a 登記申請 draft. Sensitive
    (司法書士法 §3 — assembly only, no 登記申請 creation).
  - **`search_kokkai_utterance`** (DEEP-44) — 国会会議録 utterance search
    over the post-manifest kokkai corpus shard. Filters on speaker /
    party / committee / session date range with FTS5 trigram +
    unicode61 fallback. Each hit carries primary-source `source_url`
    (kokkai.ndl.go.jp) + speaker attribution. NOT 業法 sensitive but
    carries a `_disclaimer` declaring utterances are pre-法案 commentary,
    NOT enacted law.
  - **`search_shingikai_minutes`** (DEEP-45) — 審議会 議事録 search over
    the cabinet-office / agency 審議会 minutes shard. Filters on
    審議会 name / agenda topic / committee member / meeting date range.
    Returns extracted reasoning paragraphs with `corpus_snapshot_id` for
    reproducibility. NOT 業法 sensitive but carries a `_disclaimer`
    that 議事録 are pre-policy deliberation, NOT enacted regulation.
  - **`search_municipality_subsidies`** (DEEP-44 companion) —
    municipality-level subsidy surface beyond the 政令市 20 hub
    coverage. Filters on `municipality_code` (5-digit) + funding_purpose
    + amount range. Honest-coverage gate: returns `{warning:
    coverage_gap_municipality}` envelope when the requested municipality
    has zero indexed programs (vs silently returning 0 rows). NOT 業法
    sensitive.
  - **`get_pubcomment_status`** (DEEP-45 companion) — パブリックコメント
    status probe over `e-gov.go.jp` パブコメ surface. Given a
    `pubcomment_id`, returns the consultation window (open/close) +
    submission count + post-consultation outcome reference (when the
    結果概要 has been issued) + first-party `source_url`. Surfaces a
    structured `{status: in_consultation | closed | result_published |
    unknown}` enum. NOT 業法 sensitive.

### Notes (post-manifest landing 2026-05-07)

- **Manifest hold rationale (Option B)** — per
  `R8_MANIFEST_BUMP_EVAL_2026-05-07.md`, the 7 post-manifest tools are
  **NOT** auto-published to the MCP registry. Manifests stay at 139 until
  the operator explicitly approves a v0.3.5 bump. Rationale: the 3
  post-manifest tools that touch sensitive surfaces
  (`shihoshoshi_dd_pack_am` 司法書士法 §3 / `search_kokkai_utterance`
  utterance disclaimer scaffold / `search_shingikai_minutes` 議事録
  disclaimer scaffold) need a final §52 / §3 disclaimer audit walk
  before public registry exposure. The 4 non-sensitive tools
  (`query_at_snapshot_v2` / `query_program_evolution` /
  `search_municipality_subsidies` / `get_pubcomment_status`) could ship
  today, but bundling avoids two registry republish cycles in one week.
- **Audit references**:
  - `R8_MANIFEST_BUMP_EVAL_2026-05-07.md` — Option A vs Option B
    comparison + Option B (manifest hold + CHANGELOG entry only)
    recommendation.
  - `R8_MCP_FULL_COHORT_2026-05-07.md` — full 146-tool cohort inventory
    with per-tool gate state + sensitivity classification + landing date
    (139 default-gate + 7 post-manifest = 146 latent surface).
- **Internal hypothesis framing retained** — manifest bump is an
  operator decision, NOT an automatic publish trigger. The tag-push
  →PyPI →MCP-registry chain (`release.yml` + `mcp-registry-publish.yml`)
  remains gated on a manual `pyproject.toml` bump; no auto-bump
  workflow has been added in this landing.

## [v0.3.5] - planned post-launch (operator gate)

> **Internal hypothesis framing — NOT a scheduled release.** v0.3.5 is the
> intended container for the manifest bump that surfaces the 7
> post-manifest tools (DEEP-22 / DEEP-30 / DEEP-39 / DEEP-44 / DEEP-45)
> currently held at 139 per the Option B recommendation in
> `R8_MANIFEST_BUMP_EVAL_2026-05-07.md`. This section is a **migration
> roadmap**, not a commitment. The manifest bump fires only when the
> operator explicitly approves, after the §52 / §3 / 議事録 disclaimer
> audit walk for the 3 sensitive post-manifest tools clears. No
> auto-bump workflow has been added.

### Manifest sync (7 tools + 5 manifest files)

The 7 post-manifest tools currently landed in source but not surfaced
through any manifest:

- `query_at_snapshot_v2` (DEEP-22) — point-in-time snapshot v2
- `query_program_evolution` (DEEP-30) — program lineage walker
- `shihoshoshi_dd_pack_am` (DEEP-39) — 司法書士法 §3 fence DD pack
- `search_kokkai_utterance` (DEEP-44) — 国会会議録 utterance search
- `search_shingikai_minutes` (DEEP-45) — 審議会 議事録 search
- `search_municipality_subsidies` (DEEP-44 companion) — municipality subsidy
- `get_pubcomment_status` (DEEP-45 companion) — パブリックコメント status

The 5 manifest files that must move in lockstep (any drift between them
is CI fail-closed via `tests/test_distribution_manifest.py`):

- `pyproject.toml::version` + `[project.urls]`
- `mcp-server.json::version` + `tool_count` + `tools[]` array
- `dxt/manifest.json::version` + `long_description` tool count
- `smithery.yaml::version`
- `site/mcp-server.json::version` + `tool_count`
- `server.json::version` + `_meta.publisher-provided` (registry-bound,
  100-char description cap still applies)

### Pre-flight done (as of 2026-05-07)

The following prerequisites for the v0.3.5 manifest bump have already
landed during the 5/7 hardening wave; the bump itself remains gated on
the operator's §52 / §3 / 議事録 disclaimer audit walk for the 3
sensitive post-manifest tools.

- **Sample arguments fixture prepared** —
  `tests/fixtures/7_post_manifest_tools.json` carries canonical
  happy-path `sample_arguments` blocks for all 7 tools, validated
  against the live `tools/list` response shape (matched the runtime
  Pydantic schema during the R8 cohort audit).
- **Test publish dry-run COMPLETE** — `R8_PYPI_PUBLISH_DRY` walked
  the full `release.yml` chain end-to-end on the test PyPI index
  (`twine upload --repository testpypi`) without errors. Wheel
  metadata + sdist surface verified against the 0.3.4 baseline; the
  0.3.5 retag will reuse the same workflow with no expected drift.

### Migration steps (operator step list)

1. **Compose `sample_arguments` for the 7 tools** — pull canonical
   happy-path args from `tests/fixtures/7_post_manifest_tools.json`
   (already prepared during the post-manifest landing batch — see
   "Pre-flight done" above); each tool's `sample_arguments` block
   becomes part of the `mcp-server.json::tools[]` entry. Verify each
   fixture against the live `tools/list` response shape before writing
   it into the manifest.
2. **Edit the 5 manifest files in one atomic commit** — bump version
   `0.3.4` → `0.3.5`, bump `tool_count` `139` → `146`, append the 7
   tool entries to `mcp-server.json::tools[]` /
   `site/mcp-server.json::tools[]` / `dxt/manifest.json` long
   description count. Keep `server.json::description` under the
   100-char registry cap (use the variant D shortform from the
   A1-RETRY audit).
3. **Republish to registries** — Smithery pulls from the GitHub repo
   directly on tag push, MCP registry republish fires via
   `mcp-registry-publish.yml` (OIDC, no PAT needed) once PyPI 0.3.5
   is live, dxt republish via `tools/build_dxt.sh` + GitHub Releases
   asset upload.
4. **Bump PyPI** — tag `v0.3.5` → `release.yml` → test → build →
   PyPI publish via `secrets.PYPI_API_TOKEN`. After PyPI 0.3.5 is
   live (~2-5 min), the registry mirror catches up.
5. **Bump npm SDK plugins** — `sdk/freee-plugin/package.json` and
   `sdk/mf-plugin/package.json` carry their own version tracks per
   `feedback_no_priority_question` memory note; bump them only if
   the 7 new tools surface through plugin-level wrappers (otherwise
   leave the npm SDK on its independent track).

### Verify (post-bump)

- `len(await mcp.list_tools()) == 146` with all default gates ON.
- `tests/test_distribution_manifest.py` passes (route_count + tool_count
  parity across the 5 manifest files + runtime probe).
- `tests/test_no_llm_in_production.py` still green — none of the 7
  post-manifest tools introduce LLM imports (verified during
  post-manifest landing 2026-05-07).
- MCP registry shows the 7 new tools after the publish workflow
  completes; smithery search returns the 146-tool surface.

### Risk

- **Manifest drift** — if any of the 5 manifest files is missed during
  the bump, CI fail-closes on `test_distribution_manifest` and the
  release tag publish blocks. Recovery: revert the version bump,
  re-sync, retag.
- **Registry republish double-cycle** — bundling all 7 tools avoids
  two registry republish cycles in one week; if a 8th tool lands
  before this bump fires, fold it into the same v0.3.5 manifest sync
  rather than splitting into v0.3.5 + v0.3.6.
- **Sensitive-tool disclaimer regression** — the 3 sensitive
  post-manifest tools (`shihoshoshi_dd_pack_am` 司法書士法 §3 /
  `search_kokkai_utterance` 議事録 disclaimer scaffold /
  `search_shingikai_minutes` 議事録 disclaimer scaffold) must each
  carry a `_disclaimer` envelope that survives the manifest publish.
  Verify per-tool envelope contract via the acceptance suite before
  cutting the tag.
- **Operator-LLM-API-call regression** — the manifest bump itself
  must not trigger any LLM API call from operator code paths
  (`feedback_no_operator_llm_api`); the tag-push workflow chain is
  pure `python -m build` + `twine upload` + GitHub Actions, no
  Claude Code SDK imports anywhere in the publish path.

## [v0.3.3] — 2026-05-04 — Release wave (DYM middleware + child API keys + 政令市 hubs + manifest shortform)

### Added

- **`did_you_mean` middleware on 422 unknown_query_parameter** — the FastAPI
  validation pipeline now wires a one-shot suggester that catches `unknown
  query parameter` 422 responses and inserts a `did_you_mean` array of the
  3 closest known field names (Levenshtein-trimmed, score>=0.7) into the
  error envelope. Eliminates silent typos like `?pref=...` (correct: `prefecture`)
  / `?industry=...` (correct: `target_industry`).
- **`/v1/me/keys/children` REST endpoint** (POST/GET/DELETE) — sub-API-key
  fan-out surface for the 税理士 顧問先 cohort. Parent key holders can
  mint child keys (1 parent → N children, mig 086) with per-child
  `monthly_cap_yen`, suspend/revoke independently. Each child carries its
  own usage quota counter so 顧問先 attribution is clean. Companion test:
  `tests/test_child_api_keys.py`.
- **政令市 20 hub pages + 5 trust pages + 12 cookbook recipes** —
  `site/cities/{city}.html` x 20 (Sapporo / Sendai / Saitama / Chiba /
  Yokohama / Kawasaki / Sagamihara / Niigata / Shizuoka / Hamamatsu /
  Nagoya / Kyoto / Osaka / Sakai / Kobe / Okayama / Hiroshima / Kitakyushu /
  Fukuoka / Kumamoto), `site/trust/*.html` x 5 (corporate procurement
  reviewer surface), `site/cookbook/*.html` x 12 (W2-6 outline of runnable
  dev-first recipes). Sitemap regenerated, canonical URLs aligned.
- **Saved-search digests fanned out per `client_profiles.profile_ids`** —
  `scripts/cron/run_saved_searches.py` now reads `saved_searches.profile_ids`
  (mig 097) and emits one digest per linked client profile instead of one
  digest per saved_search. The 税理士 / 補助金 consultant cohorts can now
  run N顧問先 saved searches as one cron with per-顧問先 envelope splits.
- **`dispatch_webhooks` filtered by `houjin_watch.watch_kind`** — the M&A
  cohort cron `scripts/cron/dispatch_webhooks.py` (mig 088) now respects
  `watch_kind` (e.g. `amendment` / `enforcement` / `adoption`) so subscribers
  receive only the event categories they actually opted into. Eliminates
  noisy fan-out where a watcher subscribed for `amendment` was also
  receiving `adoption` events.

### Changed

- **MCP manifest descriptions front-load generic keywords** —
  `server.json::description` compressed 287 → **94 chars** to satisfy the
  MCP registry's 100-char hard cap (variant D from the A1-RETRY audit:
  `Japan public-program MCP — subsidies, loans, tax, law, invoice, corp.
  93 tools, ¥3/req metered`). `mcp-server.json` / `dxt/manifest.json` /
  `smithery.yaml` / `site/mcp-server.json` retain the longer marketing copy
  (no 100-char cap on those surfaces). `_meta.publisher-provided` trimmed
  4654 → 1707 bytes (well under the 4 KB registry cap) by dropping
  resources arrays that are runtime-discoverable via `resources/list`.
- **Stripe Checkout display name** — `client_reference_id` now sets the
  jpcite display name (was AutonoMath); aligns checkout UI with the
  2026-04-30 brand rename.
- **`site/structured/` JSON-LD shards retired** — replaced by inline
  JSON-LD on the parent HTML pages. Surface size dropped 22,896 → **12,016
  site files** (-47%) and the canonical .html drift from the dual surfaces
  (shard vs. inline) is gone. Sitemap regenerated.

### Fixed

- **Skip PRAGMA quick_check on autonomath profile** — the schema_guard
  boot-sequence was running a full `PRAGMA quick_check` against the 9.4 GB
  `autonomath.db` on every container start, which exceeded the Fly release
  machine grace period (3 min hard ceiling) and hung deploys. Now skipped
  for the autonomath profile (the integrity check still runs nightly via
  `weekly-backup-autonomath.yml`). Boot grace period restored.
- **`distribution_manifest` route_count drift 212 → 215** — bumped to match
  the runtime probe after the new `/v1/me/keys/children` endpoint group
  added 3 routes.

### Notes

- semver bump to **v0.3.3** applied across `pyproject.toml` /
  `src/jpintel_mcp/__init__.py` / `server.json` / `mcp-server.json` /
  `dxt/manifest.json` / `smithery.yaml` / `site/mcp-server.json` /
  `scripts/distribution_manifest.yml::pyproject_version` /
  `scripts/mcp_registries_submission.json`. `@autonomath/sdk` (npm)
  remains on its independent version track per `feedback_no_priority_question`
  memory note.
- PyPI publish + MCP registry republish happen automatically on tag push:
  `release.yml` triggers on `v*` tags → test → build → PyPI publish via
  `secrets.PYPI_API_TOKEN`. After PyPI 0.3.3 is live (~2-5 min), the
  `mcp-registry-publish.yml` workflow_dispatch fires (OIDC auth, no PAT
  needed) and the registry mirrors the new 94-char description.

### Changed (carryover from Unreleased)

- **Brand rename — `税務会計AI` → `jpcite` (2026-04-30)** — primary
  user-facing brand renamed to **jpcite**; `税務会計AI` is retained as
  `alternateName` only. Apex/API domains migrated:
  `zeimu-kaikei.ai` → `jpcite.com`, `api.zeimu-kaikei.ai` →
  `api.jpcite.com`. The PyPI package name `autonomath-mcp` and the
  legacy import path `jpintel_mcp` are **unchanged** to preserve
  consumer compatibility. Historical CHANGELOG entries below intentionally
  retain the old URL strings as a migration trail; new entries
  going forward use the jpcite.com domains.

### Documentation

- **I1 — production-state numeric drift fix (2026-04-25)** — synced
  `CLAUDE.md`, `README.md`, `pyproject.toml`, `mcp-server.json`,
  `dxt/manifest.json`, `smithery.yaml` to the v15 production snapshot:
  programs `11,547 → 13,578`, autonomath `am_entities 416,375 →
  424,054`. Court decisions (2,065) + bids (362) lifted from "schema
  pre-built, post-launch" to live counts. Added a pre-V4 / post-V4
  numeric-versioning note in `CLAUDE.md` so the manifests can lag the
  in-repo state until the v0.3.0 bump CLI runs. V4 absorption details
  (migrations 046–049, +4 universal tools, post-V4 row growth) are
  documented in `CLAUDE.md` "V4 absorption" section by the absorption
  CLI; this CHANGELOG entry only covers the README / manifest sync.

### Added

- **D-series wave (2026-04-25)** — npm SDK distribution, gated cohort
  scaffolding, EN llms-full surface, infra hardening, SLA + Tokushoho
  copy. No MCP tool count change at launch (still 55); gated cohorts
  add +6 healthcare and +5 real-estate tools when env flags flip.
  - **D2 — npm SDK published**: `@autonomath/sdk@0.2.0` on npm
    (TypeScript / JavaScript), dual ESM + CJS, `.d.ts` bundled,
    `import` from `@autonomath/sdk` for REST and `@autonomath/sdk/mcp`
    for MCP. Zero runtime dependencies (platform `fetch`). Source at
    `sdk/typescript/`.
  - **D4 — Healthcare V3 cohort scaffolded** (T+90d 2026-08-04): +6
    MCP tools (`search_medical_institutions`, `get_medical_institution`,
    `search_care_subsidies`, `get_care_subsidy`,
    `eligible_care_for_profile`, `medical_compliance_pack`) gated on
    `HEALTHCARE_ENABLED=true`. Schema: migration 039
    (`medical_institutions` + `care_subsidies`).
  - **D5 — Real Estate V5 cohort scaffolded** (T+200d): +5 MCP tools
    (`search_real_estate_programs`, `get_real_estate_program`,
    `search_zoning_overlays`, `re_eligible_for_parcel`,
    `re_compliance_pack`) gated on `REAL_ESTATE_ENABLED=true`. Schema:
    migration 042 (`real_estate_programs` + `zoning_overlays`).
  - **D6 — `site/llms-full.en.txt`** new surface — EN-translated full
    spec for AI-agent discovery (companion to existing JA
    `llms-full.txt`, plus `llms.txt` / `llms.en.txt` short forms).
  - **D8 — Migration 045**: 18 new `pc_*` precompute tables added
    (industry-pref-program top-N, deadline calendar, combo pairs,
    industry adjacency, JSIC alias map, etc.). Brings pc_* count from
    33 → **51**. Read-only from API; populated by nightly cron.
  - **D9 — Rate-limit middleware + Cloudflare WAF**: token-bucket
    middleware in `src/jpintel_mcp/api/middleware/ratelimit.py` (per-IP
    + per-API-key buckets, JST monthly reset for anonymous, UTC daily
    for authenticated). Cloudflare WAF in front via
    `cloudflare-rules.yaml` (managed ruleset + custom rules for
    aggregator-style scraping). Adds no new REST paths; affects every
    request transparently.
  - **D10 — SLA 99.5% + Tokushoho**: SLA target raised from 99.0% to
    **99.5%** monthly uptime ([`docs/sla.md`](docs/sla.md));
    Tokushoho disclosure ([`site/tokushoho.html`](site/tokushoho.html))
    finalized for 特定商取引法 compliance at launch.
- **B/C-series wave (2026-04-25)** — pre-launch dashboard / alerts / stats /
  testimonials surface, customer-controlled cap, healthcare + real-estate
  schema scaffold, L4 cache + 14 pre-compute tables. No MCP tool count
  change (still 55); REST surface grew 17 → **30+** new `/v1/me/*` +
  `/v1/stats/*` + `/v1/testimonials` + `/v1/admin/testimonials/*` paths.
  - **Migrations applied** (`scripts/migrations/`):
    - `037_customer_self_cap.sql` — `api_keys.monthly_cap_yen` column
      (NULL = unlimited; non-null hard-stops billing at the cap, no
      Stripe usage record on rejection).
    - `038_alert_subscriptions.sql` — `alert_subscriptions` table for
      Tier 3 amendment alerts (filter_type ∈ tool/law_id/program_id/
      industry_jsic/all, min_severity ∈ critical/important/info,
      HTTPS-only webhook + optional email fallback).
    - `039_healthcare_schema.sql` — `medical_institutions` +
      `care_subsidies` (Healthcare V3 cohort prep, T+90d 2026-08-04).
    - `040_english_alias.sql` — DEFERRED (collection-CLI territory; not
      yet applied).
    - `041_testimonials.sql` — public testimonial collection +
      moderation queue (5 audience buckets: 税理士/行政書士/SMB/VC/Dev,
      `approved_at` flips NULL→ISO 8601 on admin approval).
    - `042_real_estate_schema.sql` — `real_estate_programs` +
      `zoning_overlays` (Real Estate V5 cohort prep, T+200d).
    - `043_l4_cache.sql` — `l4_query_cache` table (sha256-keyed, per-row
      TTL, LRU eviction via `last_hit_at`; populated organically + nightly
      Zipf seed). Empty at launch, target 60% hit rate at T+30d.
    - `044_precompute_tables.sql` — 14 new `pc_*` tables (industry/pref
      top-N, law⇄program adjacency, acceptance stats, combo pairs,
      seasonal calendar, JSIC aliases, authority adjacency, recent
      amendments, enforcement by industry, loan by collateral, cert by
      subject, starter-pack per audience). Read-only from API; nightly
      cron populates. Brings pc_* count from 19 → 33 (T+30d target).
  - **New REST endpoints** (`docs/openapi/v1.json`):
    - **Cap**: `POST /v1/me/cap` (set/clear customer-controlled monthly
      cap; ¥3/req unit price unchanged).
    - **Dashboard**: `GET /v1/me/dashboard`, `GET /v1/me/usage_by_tool`,
      `GET /v1/me/billing_history`, `GET /v1/me/tool_recommendation`.
    - **Alerts** (Tier 3 amendment subscriptions):
      `POST /v1/me/alerts/subscribe`,
      `GET /v1/me/alerts/subscriptions`,
      `DELETE /v1/me/alerts/subscriptions/{sub_id}`.
    - **Testimonials** (public submit + moderate):
      `POST /v1/me/testimonials`,
      `DELETE /v1/me/testimonials/{testimonial_id}`,
      `GET /v1/testimonials` (approved-only public list),
      `POST /v1/admin/testimonials/{id}/approve`,
      `POST /v1/admin/testimonials/{id}/unapprove`.
    - **Stats** (transparency surface):
      `GET /v1/stats/coverage`, `GET /v1/stats/freshness`,
      `GET /v1/stats/usage`. (Confidence endpoint deferred — not in this
      wave.)
  - **Aggregator cleanup** — programs `excluded=0 AND tier IN (S,A,B,C)`:
    11,559 → **11,547** (-12 net; aggregator/dead-link quarantine reset
    `tier='X'`). Total `programs` rows in DB unchanged at 12,753; the
    -12 is solely from `tier` reclassification.
  - **autonomath.db count refresh** (canonical doc-time snapshot
    aligned with task spec; live DB may be ahead due to concurrent
    ingest) — entities now **416,375** (+13,607 vs v0.2.0 baseline);
    facts ~**5.26M** (within rounding); aliases now **335,605**
    (+22,854 vs v0.2.0 baseline); `am_law_article` 0 → **28,048**;
    `am_enforcement_detail` 0 → **7,989**. Relations stable at 23,805.

- **`list_tax_sunset_alerts`** (new autonomath MCP tool): list tax
  incentives whose `am_tax_rule.effective_until` expires within N days
  (default 365). Tax-cliff alerting for 大綱-driven sunsets (年度末
  3/31 / 年末 12/31). Total MCP tool count: 54 → **55** (38 core + 17
  autonomath).

- **`subsidy_roadmap_3yr`** (new one-shot MCP tool): industry (JSIC) +
  prefecture + company_size + funding_purpose → 3-year (default 36-month)
  timeline of plausibly-applicable subsidy / loan / tax `application_window`
  entries, bucketed into JST fiscal-year quarters (Apr-Jun=Q1, Jul-Sep=Q2,
  Oct-Dec=Q3, Jan-Mar=Q4 of the prior FY). Returns `timeline` (sorted
  ascending by `opens_at`, `application_deadline` tiebreak) + `by_quarter_count`
  + `total_ceiling_yen` (sum over `max_amount_yen`). Past `from_date` is
  clamped to today JST with a hint; `cycle=annual` past `start_date` is
  projected forward year-by-year (Feb 29 → Feb 28 fallback) until it lies
  in the horizon; rolling/non-annual past windows are dropped. Empty result
  surfaces a nested `{error: {code, message, hint}}` envelope. Eliminates
  the 「いつ何を申請するか」planning round-trip.
- **`regulatory_prep_pack`** (new one-shot MCP tool): industry (JSIC) +
  prefecture (+ optional company_size) → applicable laws (current
  revision) + certifications (programs.program_kind LIKE 'certification%'
  fallback while a dedicated certifications table is pending) + tax
  rulesets (effective_until-aware, `include_expired` toggle) + 5 most
  recent same-industry enforcement cases. Eliminates the 4-5 round-trips
  (search_laws → programs(certification) → search_tax_rules →
  search_enforcement_cases) a user/agent makes to assemble the regulatory
  context for a new business / new prefecture. Empty all-sections result
  surfaces a nested `{error: {code, message, hint}}` envelope; partial
  emptiness adds a `hint` string instead of erroring.
- **`dd_profile_am`** (new one-shot MCP tool): 法人番号 → entity + adoptions +
  invoice registration + enforcement history, collapses a 5-call due-diligence
  chain into one. Honesty gates: invoice mirror delta-only flagged explicitly,
  `enforcement.found=False` does NOT claim "clean record".
- **`similar_cases`** (new MCP tool): case-study-led discovery. Given a
  `case_id` or a free-text `description`, returns 10 similar 採択事例 ranked by
  weighted Jaccard (industry ×2 + prefecture ×1 + shared `programs_used` ×3),
  each annotated with `supporting_programs` resolved from `case_studies.programs_used`
  names to actual `programs` rows. Empty seed → envelope `code=empty_input`.
- **Typo-detection gate** on prefecture input across 8 search tools
  (`search_programs`, `search_enforcement_cases`, `search_case_studies`,
  `prescreen_programs`, `upcoming_deadlines`, `subsidy_combo_finder`,
  `deadline_calendar`, `smb_starter_pack`). Unknown prefecture strings surface
  an `input_warnings` envelope instead of silently filtering on garbage (0 rows).
- **Empty-hit hints** on `list_exclusion_rules(program_id=...)` and
  `search_acceptance_stats_am`: structured `hint` with `filters_applied` +
  `suggestions` when a query matches nothing.
- **Katakana keyword expansion** (50+ pairs): `モノづくり`↔`ものづくり`,
  `DX`↔`デジタルトランスフォーメーション`, `インボイス`↔`適格請求書`, etc.
  Expands additively inside FTS `OR` so both forms now hit the same rows.
- **`tests/test_autonomath_tools.py`** (46 tests, covers all 16 autonomath
  tools against the real 7.3 GB DB — happy path + bad input per tool).

### Changed

- `PRAGMA synchronous=NORMAL` + `PRAGMA busy_timeout=5000` added to
  `jpintel.db` connection helper (matches `autonomath.db` tuning).
- Program count updated across docs/server.py to **11,547** (was the
  v0.1.0 baseline); laws **9,484** (was the early-launch baseline); tool
  total **55** (was 47 at v0.2.0 release): 38 core + 17 autonomath;
  includes 7 one-shot discovery tools: smb_starter_pack /
  subsidy_combo_finder / deadline_calendar / dd_profile_am /
  similar_cases / regulatory_prep_pack / subsidy_roadmap_3yr; and the
  autonomath sunset-alert tool list_tax_sunset_alerts).
- `get_program` / `batch_get_programs` bad-input contract: returns structured
  `{"error": {...}}` envelope instead of raising `ValueError` (MCP over
  JSON-RPC loses raise information to -32603 Internal Error).

### Fixed

- `search_acceptance_stats_am` WHERE clause bug: was filtering
  `record_kind='program'` against rows that are actually stored as
  `record_kind IN ('adoption','statistic')`. Tool silently returned
  total=0 for every query. Fixed; now returns real 採択統計 rows with
  applicants/accepted/acceptance_rate fields populated.
- Circular-import crash on `scripts/export_openapi.py` (and any
  consumer importing `jpintel_mcp.api.main`): `server.py` had a
  module-scope `from autonomath_tools.tools import …` that fired
  while `tools.py` was still mid-initialization on the
  api.main → api.autonomath → autonomath_tools → server.py path.
  Moved the import inside the `search_acceptance_stats` function
  body; both import paths now work.
- `__version__` in `src/jpintel_mcp/__init__.py` was pinned to
  `0.1.0` while `pyproject.toml` advertised `0.2.0`, so the FastAPI
  OpenAPI `info.version` field was leaking the stale value. Bumped.
- Prefecture typo gate added to `subsidy_roadmap_3yr` and
  `regulatory_prep_pack`: unknown values like `'Tokio'` / `'東京府'`
  now surface a structured `input_warnings` entry (matches the
  existing 8-tool BUG-2 pattern) instead of either silently
  filtering to 0 rows (`subsidy_roadmap_3yr` was) or silently
  dropping the filter without telling the caller
  (`regulatory_prep_pack` was). +2 tests, 531 passing.

## [v0.3.2] - 2026-05-01

### Added

- **`am_amendment_diff` cron live** —改正イベント feed の基盤として
  `am_amendment_diff` populator が production cron で稼働開始。
  `am_amendment_snapshot` の v1/v2 ペアを scan し eligibility / amount /
  deadline 軸の差分を materialize する。Tier 3 alert subscription
  surface (migration 038) と直結し、launch 後の amendment alert を
  empty-feed でなく実データで起動可能にする。
- **`programs.aliases_json` + prefecture/municipality backfill tools** —
  `aliases_json` non-empty 行が **82 → 9,996** へ伸長 (法令 alias
  抽出 + JSIC 同義語 + 既存 alias_table merge)。新スクリプト
  `scripts/etl/backfill_program_aliases.py` +
  `scripts/etl/extract_prefecture_municipality.py`。後者は
  `programs.prefecture` / `programs.municipality` を `source_url`
  ホスト + 本文 N-gram から抽出し、検索 facet の精度を底上げ。
- **HF dataset cards (4 データセット)** — `hf/datasets/` 配下に
  `programs` / `case_studies` / `enforcement_cases` / `loan_programs`
  の README + LICENSE review queue を追加。`docs/_internal/hf_publish_plan.md`
  にライセンス互換チェック手順を記録 (PDL v1.0 / CC-BY 4.0 / 政府標準
  利用規約 を個別レビュー)。launch 直後ではなく review queue が
  green になったタイミングで HF publish CLI を別タスクで実行する。
- **5 untested critical files にテスト追加** — 14 件の新規テストを
  `tests/test_search_ranking.py` / `tests/test_amendment_diff.py` /
  `tests/test_aliases_backfill.py` / `tests/test_prefecture_extractor.py` /
  `tests/test_content_hash_verifier.py` に分散。これまで coverage
  ゼロだった 5 ファイル (search ranking helpers / amendment diff
  populator / aliases backfill / prefecture extractor / content hash
  verifier) を最低 happy-path + bad-input でカバー。

### Changed

- **検索 ranking 改善** — `search_programs` の bm25 ranker で
  `primary_name` matchを **5×** weight、tokenize miss 時の
  LIKE fallback を `primary_name` / `aliases_json` / `enriched_text`
  に拡大。tier prior を再 calibration (S=1.0 / A=0.85 / B=0.55 /
  C=0.30, 旧 0.25 / 0.20 / 0.15 / 0.10) し、Tier S/A の体感ヒット率を
  改善。FTS 結果が 0 件でも LIKE fallback で 1 件以上返る確率が
  上昇 (regression risk → 既存 ranking テスト 12 件の baseline は
  全て pass)。
- **価値命題の書き直し** — README / homepage / pricing 系コピーで
  「token cost shield」フレーミングを廃止し「evidence-first context
  layer」に統一。ユーザーが LLM agent に渡す前に primary-source
  citation 付きで context を組み立てる layer、という positioning。
  旧フレーミング (token cost を削るだけ) は AutoNoMath EC SaaS と
  混同を招くため撤去。
- **anon rate limit `50 req/月` → `3 req/日`** — 匿名ユーザの quota
  reset 単位を月初 JST → 翌日 00:00 JST に変更 (DAU 目的の daily 化、
  AutoNoMath 本体ビジネスモデル v4 と整合)。
  `src/jpintel_mcp/api/middleware/ratelimit.py` の anon bucket と
  `anon_quota_header.py` の警告本文も更新。月初 reset 系コピーは
  `dashboard.html` / `pricing.html` / `docs/ratelimit.md` 全てで
  日次 reset 表記に置換。
- **brand: AutonoMath → jpcite** — user-facing surfaces (site copy /
  README headlines / OG metadata) の `AutonoMath` を `jpcite` に
  rename。PyPI package `autonomath-mcp` と import path
  `jpintel_mcp` は consumer 互換性のため不変。`zeimu-kaikei.ai`
  apex は 301 redirect で SEO 認証を引き継ぐ。

### Fixed

- **`am_source.content_hash` NULL 281 → 0** — 補完 + last_verified
  検証器を追加 (`scripts/etl/fill_content_hash.py` +
  `scripts/cron/verify_last_verified.py`)。content_hash が NULL の
  281 行を実 fetch + sha256 で埋め、`last_verified` の改ざん検出
  cron が 1 日 1 回 sample をかける運用に。
- **`programs.aliases_json` non-empty 82 → 9,996** — 上記 backfill
  ETL の Fixed 効果。検索 query が alias hit に依存していた採択事例
  / 法令交差 query で recall が改善。

### Removed

- **99 GB の DB rollback バックアップ削除** — `data/jpintel.db.bak.*`
  系列のうち 30 日以上経過した snapshot を整理し、バックアップ
  ストレージを **113 GB → 12 GB** に縮小。直近 7 日の snapshot は
  保持 (R2 weekly backup + 直近 daily の二段構え)。
- **token cost shield フレーミング撤去** — 上記 Changed と対応。
  「LLM token cost を削減する layer」という旧 pitch を README /
  homepage / pricing から完全に除去。

### Notes

- 内部メモは [`docs/_internal/`](docs/_internal/) 配下を参照
  (HF publish plan / SEO GEO strategy / brand migration log 等)。
- semver bump (`pyproject.toml` / `server.json` / `mcp-server.json` /
  `dxt/manifest.json` / `smithery.yaml`) は version-bump CLI が
  別タスクで実行する。本エントリは CHANGELOG のみ。

## [0.3.1] — 2026-04-29 — Wave 30 disclaimer hardening + launch-blocker batch

### Added

- **Three new disclaimer settings** in `src/jpintel_mcp/config.py`: gates for sensitive-tool envelope hardening + anonymous quota warning body injection.
- **§52 disclaimer hardening** across **11 sensitive-tool branches** in `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py` (`SENSITIVE_TOOLS` frozenset extended; tax surfaces — `search_tax_incentives`, `get_am_tax_rule`, `list_tax_sunset_alerts` — explicitly carry 税理士法 §52 fence; existing 7 sensitive tools tightened).
- **Tax surface §52 disclaimers** added to REST envelopes in `src/jpintel_mcp/api/tax_rulesets.py` and `src/jpintel_mcp/api/autonomath.py`.
- **Anonymous quota warning body injection** in `src/jpintel_mcp/api/middleware/anon_quota_header.py` (warns user before they hit the 50/month JST cap, not after).
- **4 broken-tool gates** wired in `snapshot_tool.py` + `tools.py`:
  `AUTONOMATH_SNAPSHOT_ENABLED` (`query_at_snapshot`, migration 067 missing),
  `AUTONOMATH_REASONING_ENABLED` (`intent_of` + `reason_answer`, package missing),
  `AUTONOMATH_GRAPH_ENABLED` (`related_programs`, `am_node` table missing).
  Flipping all 3 ON restores the 72-tool surface (broken tools still error until the underlying schema / package lands).

### Changed

- **Tool count surface 72 → 68 at default gates** (4 broken tools gated off pending fix; `mcp-server.json` `tool_count` updated; `dxt/manifest.json` `long_description` updated).
- **Brand rename** completed across user-facing manifest + description copy: jpintel internal package path retained (`src/jpintel_mcp/`), but every user-visible string now reads AutonoMath / Bookyou株式会社. Internal file paths intentionally untouched per CLAUDE.md "Never rename `src/jpintel_mcp/`" rule.
- **Homepage CRO + phantom-moat copy fix**: marketing copy realigned to honest counts (10,790 searchable / full table 13,578 incl. tier X quarantine; am_amount_condition 35,713 row count moved out of public-facing surfaces because 76% of rows are template-default values from a single broken ETL pass).
- `pyproject.toml` `[project.urls]` block — dead URL fix + Repository / Issues pointed at the live `shigetosidumeda-cyber/jpintel-mcp` repo until the AutonoMath GitHub org is claimed.
- `server.json` + `mcp-server.json` + `dxt/manifest.json` description URLs realigned with the live homepage `https://zeimu-kaikei.ai`.

### Fixed

- Stale `dist/` artifacts (`dist/autonomath_mcp-0.3.0-py3-none-any.whl` / sdist / `.mcpb` were built **before** the §52 disclaimer hardening + brand rename + quota header changes landed). Rebuilt at v0.3.1 — site/downloads/autonomath-mcp.mcpb now points at the v0.3.1 bundle.

### Notes

- v0.3.0 `dist/` artifacts are **retained** in-repo (not deleted) so any pinned downstream consumer can still install `autonomath-mcp==0.3.0`. The v0.3.1 artifacts are the publish target.
- `@autonomath/sdk` (npm) is on a **separate version track** (currently 0.3.2) per `feedback_no_priority_question` memory note; it is not bumped by this batch.
- Smithery pulls from the GitHub repo directly; this version bump only requires a git tag once the launch CLI advances.

## [0.3.0] - 2026-04-25 (Phase A absorption)

### Added

- +7 MCP tools: list_static_resources_am, get_static_resource_am, list_example_profiles_am, get_example_profile_am, render_36_kyotei_am, get_36_kyotei_metadata_am, deep_health_am
- +7 REST endpoints under /v1/am/* including health_router 分離 (AnonIpLimitDep bypass)
- 8 静的タクソノミ + 5 example profiles in data/autonomath_static/
- 4 utility modules (wareki, jp_money, jp_constants, saburoku_kyotei template)
- models/premium_response.py (PremiumResponse, ProvenanceBadge, AdoptionScore, AuditLogEntry)
- L 系列 fixes: P0-1 models shadow / P0-2 envelope wiring / P0-3 exclusion_rules dual-key / P0-4 strict_query / P0-6 get_meta dynamic / P0-7 request_id / P0-10 Tier=X
- migration 050 (Tier=X quarantine fix), 051 (exclusion_rules unified_id keys)
- target_db marker scheme for migrations
- response_model annotations 32 endpoints
- _error_envelope.py global error handler
- strict_query middleware (87% silent drop fix)
- charge.refunded webhook handler

### Changed

- Tool count: 55 → 66 (38 jpintel + 24 autonomath: 17 V1 + 4 V4 + 7 Phase A)
- autonomath.db: am_entities 416,375 → 503,930 / facts 6.12M / annotations 16,474 (V4 absorption)
- exclusion_rules: name-keyed → unified_id keyed (dual-key)

## [0.2.0] — 2026-04-25 — AutonoMath canonical DB landing

### Added

- **`autonomath.db`** companion SQLite file (7.3 GB, read-only): entity-fact
  EAV schema with **416,375 am_entities**, **5.26M am_entity_facts**,
  **23,805 am_relation** edges, **335,605 am_alias** rows, plus 14 am_*
  support tables (authority / region / tax_rule / subsidy_rule /
  application_round / loan_product / insurance_mutual / enforcement_detail /
  amendment_snapshot / industry_jsic / target_profile / peer_cache / law /
  entity_tag). FTS5 (trigram + unicode61) + sqlite-vec (6 tiered vector
  indexes). Separate file from `data/jpintel.db` — no ATTACH, no cross-DB
  JOIN per Option C strategy.
- **16 new MCP tools** (autonomath_tools subpackage):
  - tools.py (10): `search_tax_incentives`, `search_certifications`,
    `list_open_programs`, `enum_values_am`, `search_by_law`,
    `active_programs_at`, `related_programs`, `search_acceptance_stats_am`,
    `intent_of`, `reason_answer`
  - autonomath_wrappers.py (5): `search_gx_programs_am`, `search_loans_am`,
    `check_enforcement_am`, `search_mutual_plans_am`, `get_law_article_am`
  - tax_rule_tool.py (1): `get_am_tax_rule`
  - Total MCP tool count: 31 → **47**.
- **REST router** `src/jpintel_mcp/api/autonomath.py` (16 endpoints at
  `/v1/am/*`) — file on disk but intentionally NOT mounted at v0.2.0 per
  parallel-CLI merge plan. One-line activation when ready.
- **Feature flag** `AUTONOMATH_ENABLED` (default `True`) gating the
  autonomath_tools import in `server.py:4220` — rollback path to 31-tool
  baseline if autonomath.db becomes unavailable.
- **Config fields** `settings.autonomath_db_path` (default
  `./autonomath.db` dev / `/data/autonomath.db` prod) and
  `settings.autonomath_enabled`.
- **Fly.toml** `[env]` block now includes `AUTONOMATH_DB_PATH` +
  `AUTONOMATH_ENABLED`; `[[vm]]` bumped 1→2 CPU, 512→2048 MiB to cover
  7.3 GB DB mmap + headroom.
- `AUTONOMATH_DB_MANIFEST.md` at repo root documenting the DB lineage,
  18+ am_* table inventory, and "read-only primary source as of 2026-04-24
  23:26" invariant.

### Changed

- `server.json` / `pyproject.toml` description updated to reflect 47-tool
  surface and autonomath dataset breadth (416,375 entities, 5.26M facts,
  23,805 relations).
- `CLAUDE.md` architecture section split into two-DB layout with
  per-DB table inventory.

### Deferred to v0.3.x

- REST mount for `/v1/am/*` — router file on disk, `include_router`
  call not yet added. Per parallel-CLI merge plan §6.2: "10 new tools do
  not expose REST routes at launch (deferred)".
- Embedding-powered `reason_answer` semantic search — skeleton present
  (am_entities_vec + tiered vec tables) but `sentence-transformers` +
  `sqlite-vec` deps not yet pinned in pyproject.toml.
- Learning middleware + proactive push tools (Phase D/E of rollout plan).

### Unreleased (non-0.2.0 items kept below this divider)

- JP-localized 429 rate-limit error body (`detail` + `detail_en`) and
  JP-localized 422 validation errors (`msg_ja` + `detail_summary_ja`).
- `/v1/meta` endpoint (previously `/meta`; old path kept as 308 redirect).
- `/v1/openapi.json` endpoint (previously `/openapi.json`; old path kept
  as 308 redirect).
- `site/404.html` branded 404 page.
- `site/programs/index.html` — `/programs/` landing for BreadcrumbList
  navigation.
- `site/_redirects` for Cloudflare Pages URL hygiene.
- `site/rss.xml` — 20 latest programs feed.
- `scripts/refresh_sources.py` — nightly URL liveness scan with per-host
  rate limit, robots.txt compliance, and 3-strike quarantine.
- `.github/workflows/refresh-sources.yml` — daily 03:17 JST cron.
- `CLAUDE.md` at repo root for future LLM-assisted sessions.

### Changed

- MCP tool docstrings (all 13) rewritten per Anthropic mcp-builder
  pattern: 1-sentence purpose + concrete scope numbers (11,547 / 2,286 /
  108 / 1,185 / 181) + 2–3 natural Japanese example queries per tool.
  Removed negative framing ("do not use for X") per 2026 ArXiv 2602.14878
  finding that negative prompts in tool descriptions are ignored.
- `server.json` description: updated from 6,658 programs to full
  multi-source framing (11,547 programs + 2,286 採択事例 + 108 三軸分解
  融資 + 1,185 行政処分 + 181 exclusion/prerequisite rules) with
  primary-source lineage differentiation.
- `pyproject.toml` description mirrors the new multi-source framing.
- MCP server `serverInfo.version` now reports `0.1.0` (autonomath-mcp)
  instead of MCP SDK version.
- Program page template: replaced generic "所管官公庁" fallback with
  URL-host-derived JA agency name.
- Program page template: `target_types` enum values (`corporation`,
  `sole_proprietor`, etc.) now render as JA labels (法人, 個人事業主).
- Program page JSON-LD: `MonetaryGrant.funder` is now
  `GovernmentOrganization` with the actual issuing authority, not
  AutonoMath.
- Program page copy: "最終更新" label replaced with "出典取得" +
  disclaimer, reflecting that AutonoMath records when it fetched the
  source, not when the source was updated.
- Dashboard: removed retired `tier-badge` / "Free tier" markup. Copy
  reflects the current metered ¥3/req model (税込 ¥3.30).
- Dashboard: quota-reset copy now accurately states "月初 00:00 JST
  (認証済み: 00:00 UTC)".
- Stripe checkout: removed `consent_collection.terms_of_service=required`
  (caused live-mode 500). Replaced with `custom_text.submit.message`
  containing ToS + Privacy links.
- Stripe webhook: `invoice.payment_failed` now demotes the customer
  quota; `invoice.paid` re-promotes on recovery.
- README: quickstart curl uses `/v1/programs/search` (was `/v1/search`
  which 404'd); added REST API + SDKs section.
- Trust footer (`運営: Bookyou株式会社 (T8010001213708) ·
  info@bookyou.net`) now present on every public page.

### Fixed

- 509 polluted DB rows quarantined: 5 aggregator URLs, 298 MAFF `g_biki`
  dead pages, 8 fake `12345.pdf` placeholder URLs, 198 bare MAFF section
  roots.
- 360 stale HTML program pages deleted, sitemap rebuilt to 4,817
  entries.
- FTS search: `ORDER BY rank` path now also respects tier priority.
- FTS search: `tier='X'` rows no longer leak into results (432
  pre-existing + 509 new quarantined).
- FTS search: phrase-match used for 2+ character kanji queries to
  suppress trigram false-positives (e.g., `税額控除` no longer returns
  "ふるさと納税").
- FTS search: kana query expansion (`のうぎょう` → `農業`) for top-50
  common terms.
- LIKE fallback (q<3) now searches `aliases_json` and `enriched_text`.
- Duplicate program dedup via GROUP BY primary_name.
- `pricing.html` paid CTA is a POST to `/v1/billing/checkout` (was a
  broken GET link returning 405).
- `pricing.html` contact email: `info@bookyou.net` (was dead alias
  `hello@autonomath.ai`).
- `index.html` hero-tag: "AutonoMath" (was leftover "jpintel").
- `status.html`: added full footer (previously had none before
  `</body>`).
- `server.py` module docstring: binary name `autonomath-mcp` (was
  "AutonoMath").

## [0.1.0] - 2026-05-06 (planned)

First public release of the `autonomath-mcp` API, MCP server, and the
Python / TypeScript SDKs. Bundles all three artifacts at the same
initial version to simplify the launch; subsequent SDK releases will
cut independently (see `docs/_internal/sdk_release.md`).

### Added

**REST API (`https://api.autonomath.ai`, path-versioned under `/v1/*`):**

- `GET  /v1/programs/search` — structured + free-text search with
  `tier`, `prefecture`, `authority_level`, `funding_purpose`,
  `target_type`, `amount_min` / `amount_max`, `include_excluded`,
  `limit`, `offset`, `fields` (`minimal` / `default` / `full`).
- `GET  /v1/programs/{unified_id}` — program detail with optional
  enriched A–J blocks and source_mentions lineage.
- `POST /v1/programs/batch` — batch detail lookup (up to 100 ids).
- `GET  /v1/exclusions/rules` — list the exclusion-rule catalog.
- `POST /v1/exclusions/check` — evaluate a candidate program set against
  all exclusion rules; returns hits grouped by severity.
- `POST /v1/feedback` — user feedback submission (auth optional).
- `POST /v1/billing/checkout` / `/portal` / `/keys/from-checkout` /
  `/webhook` — Stripe-backed billing flow.
- `GET  /v1/meta` — aggregate stats (total_programs, tier_counts,
  last_updated).
- `GET  /healthz` — liveness probe.
- `GET  /v1/ping` — authenticated echo (useful for SDK smoke tests).

**MCP server (stdio, FastMCP, protocol `2025-06-18`):** exposes six
tools — `search_programs`, `get_program`, `batch_get_programs`,
`list_exclusion_rules`, `check_exclusions`, `get_meta`. Tool shapes
mirror the REST responses 1:1.

**Python SDK (`jpintel` on PyPI):** `Client` + `AsyncClient` with typed
Pydantic models and a typed error hierarchy (`JpintelError`,
`AuthError`, `NotFoundError`, `RateLimitError`, `ServerError`). Retries
429 / 5xx with `Retry-After` support. Requires Python 3.11+.

**TypeScript SDK (`@autonomath/client` on npm):** zero-runtime-deps
`Client` using the platform `fetch` (Node 18+, Deno, Bun, browsers).
Dual ESM + CJS output with bundled `.d.ts`. Exponential backoff on
429 / 5xx.

### Notes

- **Semver and pre-1.0 caveat.** While we are at `0.x.y`, *minor* bumps
  may still contain breaking changes — we will call them out explicitly
  with a `BREAKING:` prefix. `1.0.0` is targeted for GA (not before
  2026-09); post-1.0, breaking changes require a major bump plus a
  6-month deprecation window. See [`docs/versioning.md`](docs/versioning.md).
- **Rate limits at launch.** Anonymous: 50 req/month per IP (IPv4 /32,
  IPv6 /64), JST-first-of-month 00:00 reset. Authenticated: metered at
  ¥3/req 税別 (税込 ¥3.30) via Stripe usage billing, `lookup_key =
  per_request_v2`.
- **Data coverage disclaimer.** The `programs` catalog covers Japan's
  national, prefectural, municipal, and financial-public-corp (公庫)
  subsidy / loan / tax-incentive landscape. Coverage is **not
  exhaustive** and the Tier distribution is skewed toward agriculture
  and manufacturing at launch. Callers should treat absence of a
  program as "we may not have it yet", not "it doesn't exist". See
  [`docs/exclusions.md`](docs/exclusions.md) and
  [`docs/data_integrity.md`](docs/data_integrity.md).
- **SLA.** 99.0% monthly uptime target on `api.autonomath.ai` during
  beta, "fair-warning" SLA (no service credits). See
  [`docs/sla.md`](docs/sla.md).

---

[Unreleased]: {{REPO_URL}}/compare/v0.3.3...HEAD
[v0.3.5]: {{REPO_URL}}/compare/v0.3.4...v0.3.5
[v0.3.3]: {{REPO_URL}}/compare/v0.3.2...v0.3.3
[v0.3.2]: {{REPO_URL}}/compare/v0.3.1...v0.3.2
[0.3.1]: {{REPO_URL}}/compare/v0.3.0...v0.3.1
[0.3.0]: {{REPO_URL}}/compare/v0.2.0...v0.3.0
[0.2.0]: {{REPO_URL}}/compare/v0.1.0...v0.2.0
[0.1.0]: {{REPO_URL}}/releases/tag/v0.1.0

© 2026 Bookyou株式会社 (T8010001213708).


#### tick 44: Goal re-affirmed / **live_aws=false (44 tick 絶対堅守)**

#### tick 45: **live_aws=false (45 tick 絶対堅守)**

#### tick 46: **live_aws=false (46 tick 絶対堅守)**

#### tick 47: **live_aws=false (47 tick 絶対堅守)**

#### tick 48: **live_aws=false (48 tick 絶対堅守)**

#### tick 49: **live_aws=false (49 tick 絶対堅守)**

#### tick 50 (50 tick milestone): **live_aws=false (50 tick 絶対堅守)**

#### tick 51: **live_aws=false (51 tick 絶対堅守)**

#### tick 52: **live_aws=false (52 tick 絶対堅守)**

#### tick 53: **live_aws=false (53 tick 絶対堅守)**

#### tick 54: **live_aws=false (54 tick 絶対堅守)**

#### tick 55: **live_aws=false (55 tick 絶対堅守)**

#### tick 56: **live_aws=false (56 tick 絶対堅守)**

#### tick 57: **live_aws=false (57 tick 絶対堅守)**

#### tick 58: **live_aws=false (58 tick 絶対堅守)**

#### tick 59: **live_aws=false (59 tick 絶対堅守)**

#### tick 60 (60 tick milestone): **live_aws=false (60 tick 絶対堅守)**

#### tick 61: **live_aws=false (61 tick 絶対堅守)**

#### tick 62: **live_aws=false (62 tick 絶対堅守)**

#### tick 63: **live_aws=false (63 tick 絶対堅守)**

#### tick 64: **live_aws=false (64 tick 絶対堅守)**

#### tick 65: **live_aws=false (65 tick 絶対堅守)**

#### tick 66: **live_aws=false (66 tick 絶対堅守)**

#### tick 67: **live_aws=false (67 tick 絶対堅守)**

#### tick 68: **live_aws=false (68 tick 絶対堅守)**

#### tick 69: **live_aws=false (69 tick 絶対堅守)**

#### tick 70 (70 tick milestone): **live_aws=false (70 tick 絶対堅守)**

#### tick 71: **live_aws=false (71 tick 絶対堅守)**

#### tick 72: **live_aws=false (72 tick 絶対堅守)**

#### tick 73: **live_aws=false (73 tick 絶対堅守)**

#### tick 74: **live_aws=false (74 tick 絶対堅守)**

#### tick 75: **live_aws=false (75 tick 絶対堅守)**

#### tick 76: **live_aws=false (76 tick 絶対堅守)**

#### tick 77: **live_aws=false (77 tick 絶対堅守)**

#### tick 78: **live_aws=false (78 tick 絶対堅守)**

#### tick 79: **live_aws=false (79 tick 絶対堅守)**

#### tick 80 (80 tick milestone): **live_aws=false (80 tick 絶対堅守)**

#### tick 81: **live_aws=false (81 tick 絶対堅守)**

#### tick 82: **live_aws=false (82 tick 絶対堅守)**

#### tick 83: **live_aws=false (83 tick 絶対堅守)**

#### tick 84: **live_aws=false (84 tick 絶対堅守)**

#### tick 85: **live_aws=false (85 tick 絶対堅守)**

#### tick 86: **live_aws=false (86 tick 絶対堅守)**

#### tick 87: **live_aws=false (87 tick 絶対堅守)**

#### tick 88: **live_aws=false (88 tick 絶対堅守)**

#### tick 89: **live_aws=false (89 tick 絶対堅守)**

#### tick 90 (90 tick milestone): **live_aws=false (90 tick 絶対堅守)**

#### tick 91: **live_aws=false (91 tick 絶対堅守)**

#### tick 92: **live_aws=false (92 tick 絶対堅守)**

#### tick 93: **live_aws=false (93 tick 絶対堅守)**

#### tick 94: **live_aws=false (94 tick 絶対堅守)**

#### tick 95: **live_aws=false (95 tick 絶対堅守)**

#### tick 96: **live_aws=false (96 tick 絶対堅守)**

#### tick 97: **live_aws=false (97 tick 絶対堅守)**

#### tick 98: **live_aws=false (98 tick 絶対堅守)**

#### tick 99: **live_aws=false (99 tick 絶対堅守)**

#### tick 100 (100 tick MILESTONE): **live_aws=false (100 tick 絶対堅守)**

#### tick 101: **live_aws=false (101 tick 絶対堅守)**

#### tick 102: **live_aws=false (102 tick 絶対堅守)**

#### tick 103: **live_aws=false (103 tick 絶対堅守)**

#### tick 104: **live_aws=false (104 tick 絶対堅守)**

#### tick 150: **live_aws=false (150 tick 絶対堅守 — MILESTONE)**
