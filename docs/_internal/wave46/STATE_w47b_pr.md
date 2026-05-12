# STATE: Wave 46.B — Docker image jpcite namespace alias + Fly app jpcite-api design

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave46_rename_47b_docker_namespace`
Worktree: `/tmp/jpcite-w46-rename-47b`
Lane claim: `/tmp/jpcite-w46-rename-47b.lane/`
Memory anchors:
- `project_jpcite_internal_autonomath_rename`
- `feedback_destruction_free_organization` (autonomath-api app delete禁止)
- `feedback_dual_cli_lane_atomic`
- `feedback_no_quick_check_on_huge_sqlite`
- `feedback_no_operator_llm_api`
- `feedback_overwrite_stale_state`

## Scope

Wave 46.B is the **design-only** PR that introduces:

1. A new Fly app target (`jpcite-api`) without touching the legacy
   `autonomath-api` app.
2. Additive OCI/vendor labels in `Dockerfile` so the same image declares
   both lineages (`AutonoMath API` as the OCI standard title; `jpcite-mcp`
   as alt-title + `com.bookyou.jpcite.*` vendor labels).
3. A dispatch-only GHA workflow (`deploy-jpcite-api.yml`) so an operator
   can fire a one-off deploy of the new app for smoke validation, while
   the production cutover (DNS, CF Pages, R2 keys) is deferred to a later
   wave per user judgment.

Per `feedback_destruction_free_organization`, the legacy `fly.toml` is
NOT edited. Per `feedback_destruction_free_organization` + the explicit
task prompt, the existing `autonomath-api` app must not be deleted; this
PR is purely additive.

## Files touched (4 new + 1 additive edit)

| File                                                      | Change                                | Δ LOC |
|-----------------------------------------------------------|---------------------------------------|-------|
| `fly.jpcite.toml`                                         | NEW: app=jpcite-api overlay           | +132  |
| `Dockerfile`                                              | +14 LOC (alt-title + 4 vendor labels) | +14   |
| `.github/workflows/deploy-jpcite-api.yml`                 | NEW: dispatch-only deploy workflow    | +213  |
| `tests/test_w47b_fly_config.py`                           | NEW: 22 parity + safety cases         | +210  |
| `docs/_internal/wave46/STATE_w47b_pr.md`                  | this STATE doc                        | +180  |
| **Total**                                                 |                                       | **~749** |

Net new files: 4 (toml + yml + py + md). Net edits: 1 (Dockerfile,
additive only — no LABEL deleted).

## fly.jpcite.toml structural diff vs. fly.toml

Only three intentional drifts; all other sections are structurally
identical (verified by `tests/test_w47b_fly_config.py`).

```diff
- app = "autonomath-api"
+ app = "jpcite-api"
+ kill_signal = "SIGINT"
+ kill_timeout = "30s"
```

| Section              | fly.toml (autonomath-api)              | fly.jpcite.toml (jpcite-api)              | Δ |
|----------------------|----------------------------------------|-------------------------------------------|---|
| `app`                | `autonomath-api`                       | `jpcite-api`                              | ✱ |
| `primary_region`     | `nrt`                                  | `nrt`                                     | = |
| `kill_signal`        | (implicit SIGTERM)                     | `SIGINT` (explicit, uvicorn graceful)     | ✱ |
| `kill_timeout`       | (implicit)                             | `30s` (explicit drain window)             | ✱ |
| `[build].dockerfile` | `Dockerfile`                           | `Dockerfile`                              | = |
| `[env]` matrix       | identical 8 keys                       | identical 8 keys                          | = |
| `[deploy].strategy`  | `immediate`                            | `immediate`                               | = |
| `[[mounts]]`         | jpintel_data → /data, 40gb             | jpintel_data → /data, 40gb                | = |
| `[http_service]`     | 8080, force_https, suspend, 1 min, 50/100 conc | identical                          | = |
| `/healthz` check     | 30s int, 10s to, 60s grace, GET        | identical                                 | = |
| `[metrics]`          | port 9091, path /metrics               | identical                                 | = |
| `[[vm]]`             | shared 2 cpu × 4096 MB                 | identical                                 | = |

The `kill_signal=SIGINT` choice mirrors the uvicorn `CMD` line in the
Dockerfile — uvicorn responds to SIGINT with a graceful shutdown (drain
active requests), while default SIGTERM hard-exits. The legacy app inherits
the Fly default; making it explicit on the new app makes drain semantics
unambiguous from day-1 without retro-touching the SOT file.

## Dockerfile LABEL diff (additive)

```diff
 LABEL org.opencontainers.image.title="AutonoMath API"
 LABEL org.opencontainers.image.vendor="Bookyou株式会社"
 LABEL org.opencontainers.image.licenses="MIT"
 LABEL org.opencontainers.image.source="https://github.com/shigetosidumeda-cyber/jpintel-mcp"
+
+# Wave 46.B namespace alias (2026-05-12) — jpcite brand identification, additive only.
+# (...context comment block...)
+LABEL org.opencontainers.image.alt-title="jpcite-mcp"
+LABEL org.opencontainers.image.alt-vendor="Bookyou株式会社"
+LABEL com.bookyou.jpcite.brand="jpcite"
+LABEL com.bookyou.jpcite.app="jpcite-api"
+LABEL com.bookyou.jpcite.rename-wave="46.B"
```

Standard OCI title remains `AutonoMath API` so downstream registries
(Glama, Smithery, PulseMCP, container scanners) still match the existing
autonomath-api lineage. `alt-title` is a vendor extension consumed only
by jpcite-side tooling. The `com.bookyou.jpcite.*` namespace is reserved
for our own metadata and cannot collide with the OCI spec.

Layer ordering is verified by
`test_dockerfile_alt_labels_come_after_legacy` so OCI-spec scanners that
stop at the first `title` keep seeing the historically-stable string.

## Dispatch workflow guard rails

`.github/workflows/deploy-jpcite-api.yml` design constraints (enforced by
`test_jpcite_workflow_is_dispatch_only` and
`test_jpcite_workflow_targets_jpcite_api_not_autonomath`):

- `workflow_dispatch` is the ONLY trigger; no `schedule`, no
  `workflow_run`, no `push`. The operator (user) must explicitly fire
  each run.
- `flyctl deploy` line: `-c fly.jpcite.toml -a jpcite-api`. Test asserts
  `autonomath-api` never appears in any `flyctl deploy` invocation.
- Same `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` + `production_deploy_go_gate.py`
  gates as the legacy workflow — new app does not bypass production
  safety checks.
- `verify-app-exists` step: if the operator forgot
  `flyctl apps create jpcite-api`, the run hard-fails before
  `flyctl deploy` so no half-created state lands on Fly.
- Default smoke target is `https://jpcite-api.fly.dev` (Fly-internal
  hostname); `https://api.jpcite.com` is only used after the DNS cutover
  wave lands.
- 60s post-deploy propagation sleep per
  `feedback_post_deploy_smoke_propagation`.
- No sftp from autonomath-api → keeps the legacy app's volume untouched;
  new app pulls jpintel.db via the Dockerfile R2 build-arg on first
  boot (same path as Wave 24 SKIP_HYDRATE).

## Bugs-not-introduced verify

| Gate                                      | Command                                                  | Result |
|-------------------------------------------|----------------------------------------------------------|--------|
| fly.jpcite.toml TOML parse                | `python3.12 -c "tomllib.loads(...)"`                     | OK     |
| fly.toml TOML parse (untouched)           | `python3.12 -c "tomllib.loads(...)"`                     | OK     |
| YAML parse on new workflow                | `python3.12 -c "yaml.safe_load(...)"`                    | OK     |
| pytest new file (22 cases)                | `pytest tests/test_w47b_fly_config.py -v`                | **22/22 PASS** |
| pytest legacy fly health test (regression)| `pytest tests/test_fly_health_check.py -v`               | **1/1 PASS** |
| Forbidden brand "税務会計AI" in new files | `grep -nE "税務会計AI" <new files>`                      | 0 hits |
| Legacy LABEL deletion check               | `grep -E '^LABEL.*AutonoMath API' Dockerfile`            | still present |
| autonomath-api app reference (legacy)     | `grep -c "autonomath-api" fly.toml`                      | unchanged |

Parity verdict: **STRUCTURAL PARITY HOLDS** on all 8 sections; only the
three intentional fields (`app`, `kill_signal`, `kill_timeout`) differ,
and each delta is explicitly asserted by a dedicated test.

## Why dispatch-only (no cron, no workflow_run)

Per the task prompt and `feedback_no_priority_question`:

- Real cutover requires three coordinated waves (Fly app create, DNS
  flip, CF Pages config). Auto-firing this workflow would race the DNS
  step and produce a half-cutover state.
- User judgment gates whether this app even gets created on Fly. If
  user decides Wave 47.C is the cutover wave, the dispatch is fired
  manually with the right SHA.
- Dispatch-only is the lowest-blast-radius landing — file lands in main,
  CI verifies the structure, zero production effect.

## Open questions deferred to later waves

1. **Fly app creation** (`flyctl apps create jpcite-api --org bookyou`) is
   a one-off operator command, not part of this PR.
2. **Secret mirror**: per `feedback_secret_store_separation`, Fly secrets
   are namespaced by app. The full secret matrix (SENTRY_DSN, STRIPE_*,
   API_KEY_SALT, AUTONOMATH_DB_URL, …) must be re-set on `jpcite-api`
   via `flyctl secrets set -a jpcite-api`. Inventory script lives
   outside this PR.
3. **DNS cutover** (`api.jpcite.com` → jpcite-api): CF Pages + CNAME
   change happens in a dedicated wave only after this app is healthy
   on `jpcite-api.fly.dev`.
4. **CF Pages app rename / R2 key prefix migration** (`autonomath-api/` →
   `jpcite-api/`): separate wave.
5. **Legacy app retirement timeline**: NEVER hard-delete (per
   `feedback_destruction_free_organization`); will get a banner +
   superseded marker once jpcite-api carries 100% of traffic for ≥30
   days.

## PR target

- Branch: `feat/jpcite_2026_05_12_wave46_rename_47b_docker_namespace`
- Base: `main` (HEAD `92528cc75`)
- Labels: design-only, no production effect
- Reviewers: solo / admin merge
- CI surface: pytest (22 new cases), ruff, structural-drift gates;
  Fly deploy workflow does NOT fire (no `workflow_run` trigger).

## Net effect summary

This PR lands as zero-impact design scaffolding. After merge:

- `autonomath-api` app keeps serving 100% of `api.jpcite.com` traffic.
- The image build still produces the same OCI artifact (additive labels
  only) — no behavior change to the live machine.
- A second deploy lane (`jpcite-api` Fly app + dispatch workflow) is
  available for the next wave to exercise without further code change.
- All test gates green; legacy file invariants pinned by
  `test_legacy_fly_toml_untouched_signature` so any future accidental
  edit to `fly.toml` lights up here.
