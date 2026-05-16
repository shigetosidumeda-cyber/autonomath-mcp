# jpcite Performance SOT — Development + System Baseline + Roadmap (2026-05-16)

PERF-10 deliverable. Single-source-of-truth that supersedes the three
older perf docs in this directory:

- `perf_baseline_2026-04-25.md` (E2 v6 baseline — historical)
- `perf_baseline_v15_2026-04-25.md` (I8 v15 baseline — historical)
- `performance_audit_2026-04-30.md` (post-V4 storage/import audit — historical)

This doc lives alongside the in-flight PERF-1..PERF-9 parallel agents
(task IDs #200–#208). It records measurements honestly: where actual
numbers were captured in this session they are inline; where they are
the responsibility of an in-flight PERF agent and have not yet landed
they are marked `TBD (PERF-N)`.

Owner: ongoing.
Captured: 2026-05-16 PM, branch `main`, HEAD `7650e1074`.

## 1. Current state baseline (measured this session unless noted)

### 1.1 Dev cycle

| Metric | Cold | Warm | Incremental | Notes |
|---|---:|---:|---:|---|
| `pytest --collect-only` | **9.24s** | TBD (PERF-1) | n/a | 10,966 tests collected. `addopts = ["-n", "auto", "--dist", "loadscope", "--durations=10"]` in pyproject.toml — xdist+loadscope already on. |
| pytest full run wall time | TBD (PERF-1) | TBD (PERF-1) | n/a | Subset coverage push lands at 73-90%, project-wide ≈26% (Stream QQ honest re-measurement). Recent GHA test.yml runs: 113s..850s, mean ≈361s, mostly cancelled / 2 failures. |
| mypy `--strict` whole repo | TBD (PERF-2) | TBD (PERF-2) | TBD (PERF-2) | Config pinned `python_version="3.11"`, `incremental=true`, `cache_dir=".mypy_cache"`. Strict residual = **0 errors** (15+ tick streak per CLAUDE.md). PERF-2 comment in `pyproject.toml` claims cold ≈31s over 593 files, hot <1s, dmypy sub-second incremental. Not independently re-measured this session. |
| mypy on single file (cold-process, no incremental) | <1s | n/a | n/a | `.venv/bin/mypy --no-incremental scripts/aws_credit_ops/_packet_base.py` → Success. |
| ruff `check src/` | 0.4s | 0.4s | n/a | `.ruff_cache` exists; 35 errors observed (separate from mypy state). |
| ruff on single file | **0.015s** | 0.015s | n/a | `.venv/bin/ruff check src/jpintel_mcp/api/main.py`. |
| GHA `test.yml` wall time | **mean ≈361s n=9** | n/a | n/a | Last 10 runs (failures included); recent finishes at 833s + 850s, suggesting steady-state nearer 800-900s for full pass. |
| GHA other workflows | TBD (PERF-8) | n/a | n/a | 167 workflows in `.github/workflows/`. CodeQL + lane-enforcer + openapi run in parallel with test. |

### 1.2 System

| Metric | Value | Source | Notes |
|---|---:|---|---|
| API p95 latency (HTTP, all 9 endpoints, n=500) | **188.3 ms worst-case** | I8 v15 baseline 2026-04-25 | 4.25× under 800 ms SLA. `/v1/programs/search?q=持続化補助金` was the slowest. Not re-measured this session. |
| MCP `tools/list` P95 | 203 ms | I8 v15 | 59 tools then; today 184 published at default gates. New measurement TBD (PERF-6). |
| MCP `tools/call search_programs` P95 | 12.8 ms | I8 v15 | |
| API cold boot (`from jpintel_mcp.api.main import app`) | **7.12 s wall (2.89s user)** | This session | Slower than the 5.45s 2026-04-30 audit — additional routes + Wave 50/51 contracts layer. PERF-6/PERF-7 may move this back under 3s by lazy-loading scipy/stripe/autonomath_tools. |
| MCP cold boot (`from jpintel_mcp.mcp.server import run`) | **1.83 s wall (1.22s user)** | This session | Unchanged from 2026-04-30 audit. |
| FAISS smoke query (5 random queries) | <1 s total | `docs/_internal/faiss_v2_complete_2026_05_16.md` | v2 IVF+PQ, 74,812 vectors, nprobe=max(32, nlist//2). Build time: index `add` 2.29 s, train 2.92 s. Recall@10 = 1.0. No p95 measurement yet — PERF-4 owns. |
| Athena bytes scanned per query (8 big queries) | **mean ≈297 MB / max 861 MB** | `docs/_internal/athena_real_burn_2026_05_16.md` | 8 queries aggregate 2.22 GiB scanned, $0.010824 burn at $5/TB, wall ~76 s total. Workgroup cap = 100 GB BytesScannedCutoffPerQuery. |
| Athena large-table partition layout | JSON / SerDe heavy | PERF-3 | Wave 56-58 packets land as JSON; first Q1/Q2 retry scanned 0 bytes because tables were SerDe-mismatched. Parquet migration in flight (PERF-3). |
| S3 object count (canary derived bucket) | **524,290 objects** | `docs/_internal/aws_armed_state_pm4_2026_05_16.md` | Distributed across 200+ packet catalog prefixes after Waves 53-79. PERF-5 is auditing prefix layout for hot-spot. |
| 法人360 single-shard | 86,849 objects / 252,463,349 bytes | `docs/_internal/AWS_CANARY_RUN_2026_05_16.md` | Local generation 33s vs Fargate Batch ≈167× slower (Fargate startup dominates). |
| `autonomath.db` size on volume | **12 GB (repo root) / 9.4 GB (logical)** | `du -sh autonomath.db` this session | Largest single artifact. Boot-time integrity_check disabled (size-based skip in entrypoint.sh §2 + §4, Wave 13/18 fix). |
| `data/jpintel.db` size | **432 MB** | `du -sh` this session | Up from 360 MB at 2026-04-30 audit. FTS5 trigram p50 ≈ 6 ms (unchanged from 2026-04-30). |
| Total `data/` directory | 531 MB | this session | |

## 2. Target metrics + budget

These targets are the gate for PERF-1..PERF-9 closure. Numbers are
aspirational, not committed; PERF agents land partial improvements
incrementally.

| Metric | Current | Target | Budget rationale |
|---|---:|---:|---|
| pytest full run cold (local) | TBD | **<180 s** | 10K tests, 8-way xdist on M-series Mac → ≤25 ms/test wall amortized. Current `loadscope` dist should fit. |
| pytest full run on CI (GHA ubuntu-latest) | ≈800 s (estimate) | **<360 s** | Sharding 4-way across GHA jobs unlocks linear speedup, target ≤2 GHA-minutes per shard. |
| mypy `--strict` cold full repo | ≈31 s (per pyproject comment) | **≤30 s** | Hold. Daemon (dmypy) keeps incremental <1 s; PERF-2 already configured. |
| mypy incremental (single file edit) | <1 s | **<500 ms** | sqlite-backed fine-grained cache (`mypy.fine_grained_cache=true`). |
| ruff src/ | 0.4 s | 0.4 s | Already excellent. Hold. |
| GHA `test.yml` wall | ≈800-900 s | **<360 s** | PERF-8 will parallelize + cache pip + .venv across jobs. |
| API p95 HTTP | 188.3 ms (4.25× margin) | **<300 ms** | Hold — keep 2.6× margin under 800 ms SLA. |
| API cold boot | 7.1 s | **<3 s** | PERF-6/PERF-7: lazy-load scipy.stats, stripe, autonomath_tools. Estimated saving 2.5 s. |
| MCP cold boot | 1.83 s | **<1.5 s** | PERF-6: lazy register 184 tools (currently all eager). |
| MCP `tools/list` P95 (184 tools) | TBD | **<300 ms** | Linear in tool count; ~3.5 ms/tool serialization headroom. |
| FAISS p95 query | unmeasured | **<50 ms** | 74,812 vectors, IVF+PQ, nprobe tuning is PERF-4. |
| Athena avg bytes scanned per query | 297 MB | **<100 MB** for partition-targeted | Parquet + partition projection (PERF-3) cuts JSON scan ~10×. |
| Athena $/query | $0.0014 mean | **<$0.0005** | Falls out of bytes-scanned reduction. |
| S3 prefix hot-spot | 524K flat | **<200 obj/prefix p99** | PERF-5 redesign; today's 86K-object law packet shard violates this. |

## 3. Landed improvements (PERF-1..PERF-9 — current status)

As of HEAD `7650e1074` (2026-05-16 PM), the PERF-1..PERF-9 task tickets
(#200–#208) are all marked `in_progress` except PERF-9 which is
`completed`. No PERF agent commits have landed on `main` yet — the
in-flight work is staged on worktrees / lane-claimed but unmerged.

Status snapshot:

| Task | Subject | Status | Landed evidence |
|---|---|---|---|
| PERF-1 | pytest 10K+ test parallel + sharding | in_progress | `pyproject.toml: addopts = ["-n", "auto", "--dist", "loadscope"]` already live. Sharding across GHA jobs not yet on `main`. |
| PERF-2 | mypy strict daemon + incremental cache | in_progress | `pyproject.toml: [tool.mypy] incremental=true cache_dir=".mypy_cache"` + PERF-2 comment block live; cold/hot timings claimed but unverified this session. |
| PERF-3 | Athena Parquet / partition projection migration | in_progress | ETL `scripts/aws_credit_ops/etl_raw_to_derived.py` exists; targeted migration of Wave 56-58 JSON → Parquet still partial (Athena Q1/Q2 0-byte scan documented). |
| PERF-4 | FAISS query latency p95 + IVF nprobe optimization | in_progress | v2 index built (74,812 vectors, recall@10=1.0, smoke <1s). No nprobe sweep / p95 histogram landed. |
| PERF-5 | S3 prefix layout (524K files) redesign | in_progress | Audit doc TBD. 法人360 shard (86,849 objects in one prefix) is the canonical hot-spot example. |
| PERF-6 | MCP 184 tools lazy load + startup time | in_progress | No code change on `main`; cold boot still 1.83 s. |
| PERF-7 | API hot-path profiling + p95 budget | in_progress | I8 v15 baseline (188.3 ms worst P95) remains the latest measurement. |
| PERF-8 | CI/CD GHA pipeline parallelism + cache | in_progress | 167 workflows present; no per-workflow caching diff merged. |
| PERF-9 | Repo structure audit + scripts/ modularization | **completed** | 829 Python files in `scripts/`, 301 specifically in `scripts/aws_credit_ops/`. Modularization audit landed; concrete reorg pending follow-up. |

Net landed measurable improvement on `main` this session: **0** PERF-N
commits. Improvements remain in worktrees / agent staging.

## 4. Pending improvements + ETA

ETA expressed as "next deliverable that should land on `main`",
ordered by leverage.

| Priority | Item | Owner | Expected impact | ETA marker |
|---|---|---|---|---|
| P0 | Lazy-load `scipy.stats`, `stripe`, `autonomath_tools` at API boot | PERF-6/PERF-7 | API cold 7.1 s → ~4.5 s | next PERF tick |
| P0 | Parquet migration for Wave 56-58 packet tables | PERF-3 | Athena scan -90% on time-series + geo aggregations | next PERF tick |
| P0 | pytest 4-shard CI matrix | PERF-1/PERF-8 | GHA test.yml ≈800s → ≈240s | next PERF tick |
| P1 | FAISS nprobe sweep + p95 histogram | PERF-4 | First honest p95 measurement; tune nprobe to land <50 ms | next PERF tick |
| P1 | mypy dmypy daemon binding to Makefile `typecheck-fast` (already mentioned in pyproject) | PERF-2 | Sub-second incremental during local dev | next PERF tick |
| P1 | S3 prefix sharding for 法人360 + adoption corpus | PERF-5 | Sub-prefix hot-spot mitigation; faster `aws s3 ls` paging | next PERF tick |
| P2 | MCP lazy-register 184 tools | PERF-6 | MCP cold 1.83 s → ~1.2 s; `tools/list` p95 cut | follow-up |
| P2 | GHA pip + uv cache across workflows | PERF-8 | -30-90 s per workflow boot | follow-up |
| P2 | Drop 2.36 GB DEAD vec / FTS-uni objects from `autonomath.db` | (existing audit follow-up) | -25% DB size, faster cold open | follow-up; requires VACUUM window |
| P3 | scripts/ modularization concrete reorg | PERF-9 follow-up | DX clarity; not perf-critical | optional |

## 5. Anti-patterns observed

These are real foot-guns either currently in production or recently
removed. Document them so future PERF iterations don't re-introduce.

1. **JsonSerDe for large Athena tables (PERF-3 root cause)**. Wave
   56-58 packet generators wrote JSON Lines; the Athena external table
   used `org.openx.data.jsonserde.JsonSerDe` over the entire object
   tree. First Q1/Q2 retry scanned 0 bytes because the SerDe path
   silently mismatched the directory layout. Parquet + explicit
   partition columns is the only safe shape at >10⁵ object scale.
2. **Local-runtime packet generators forced through AWS Batch**.
   Documented in `feedback_packet_local_gen_300x_faster.md`: 86,849
   法人360 packets generated in 33 s local vs ~6 hour Batch fan-out.
   Fargate Spot startup ≈30 s/task dominates when compute is <5
   s/unit. Rule of thumb: `<5 s/unit → local + aws s3 sync 64-128
   parallel`.
3. **Eager `scipy.stats` import at API boot via
   `analytics.bayesian`**. 2026-04-30 audit pinned 1.2 s of 5.45 s
   cold boot on a single import chain only used inside the
   `/v1/confidence` route. Still un-fixed on `main`; cold boot has
   since risen to 7.1 s.
4. **`PRAGMA integrity_check` on 9.7 GB SQLite at boot**. Wave 18
   root-cause: 30+ min hang on every machine boot, took prod down for
   38 minutes 2026-05-11. `entrypoint.sh` §4 now size-skips, but the
   rule generalizes: never `quick_check` / `integrity_check` /
   `sha256sum` on multi-GB SQLite or DB blobs at any cold path.
5. **8 ad-hoc `sqlite3.connect(...)` callsites with no perf
   pragmas**. 2026-04-30 audit listed them
   (`api/_audit_seal.py`, `api/houjin.py`, etc.) — extracting a shared
   `_open_ro(path)` helper to apply `cache_size=-262144 / mmap_size=2
   GiB / temp_store=MEMORY / query_only=1` is a documented 5-20 ms
   per-request cold-cache win that hasn't been picked up yet.
6. **128 GB of `autonomath.db.{bak,pre}.*` at repo root**.
   2026-04-30 audit flagged it; today's `du` shows 12 GB at root
   still includes some of those. Disk-pressure / accidental rsync
   risk for Fly volume operations.
7. **Fargate cross-region SNS publish** (recent Phase-4 finding,
   `feedback_aws_cross_region_sns_publish.md`). Silent failure;
   per-region SNS topic is the only correct shape.
8. **Subset-only coverage reporting reported as project-wide**
   (Wave 50 Stream QQ honest re-measurement). DB-fixture-heavy
   coverage subsets landed 73-90 %, but project-wide is ≈26 %.
   Don't quote subset numbers as if they were project-wide. Sets
   the wrong gate for any "coverage 90 %" perf-related claim.

## Appendix A — Artifact paths referenced

- `/Users/shigetoumeda/jpcite/pyproject.toml` — pytest + mypy config
- `/Users/shigetoumeda/jpcite/.github/workflows/test.yml` — CI test workflow
- `/Users/shigetoumeda/jpcite/docs/_internal/perf_baseline_2026-04-25.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/perf_baseline_v15_2026-04-25.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/performance_audit_2026-04-30.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/faiss_v2_complete_2026_05_16.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/athena_real_burn_2026_05_16.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_RUN_2026_05_16.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/aws_armed_state_pm4_2026_05_16.md`

last_updated: 2026-05-16
