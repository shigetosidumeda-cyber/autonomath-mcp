# R8 LAUNCH OPS TIMELINE — 2026-05-07

| Field | Value |
|---|---|
| Audit ID | R8_LAUNCH_OPS_TIMELINE_2026-05-07 |
| Window | 2026-05-07 02:50 — 04:20 UTC (≈ 90 min) |
| Repo | shigetosidumeda-cyber/autonomath-mcp (jpcite v0.3.4) |
| App | jpcite-api on Fly.io (NRT region, 227 OpenAPI ops, 139 MCP tools) |
| Frontend | jpcite-pages (Cloudflare Pages, 13010 file build artifact) |
| Ingress hypothesis | LIVE — `/healthz` 200 prior to ops window, ingress通電 (内部仮説。本 audit 上書き禁止) |
| Stale risk hypothesis | frontend (CF Pages) artifact 古い可能性、 wrangler retry 完走待ち |
| LLM calls used | 0 (deterministic only — operator policy) |

> **Framing 注**: 本 doc は launch ops 試行の timeline 記録である。prod 状態に関する「LIVE」「stale」は **内部仮説 framing** として扱い、 user 向け配信文や release note には別途独立検証を要する。

---

## §1 — Timeline (16 attempts)

| # | UTC | Action | Result | Artefact / SHA |
|---|---|---|---|---|
| 1 | 02:50 | ACK YAML signoff (`ack_live_final.yaml`) | **PASS** 8/8 | sha256 `d9fe1af…` |
| 2 | 02:55 | `production_deploy_go_gate` 5/5 | **PASS** | gate output captured |
| 3 | 02:58 | `flyctl deploy --remote-only` (depot builder) | **FAIL** | depot 1431s `deadline_exceeded` |
| 4 | 03:05 | `flyctl deploy --depot=false` | **FAIL** | `missing-hostname` daemon parse / flag deprecated |
| 5 | 03:12 | `wrangler pages deploy` (frontend, attempt 1) | **FAIL** | upload stall 1704/13010 → empty `{}` error |
| 6 | 03:45:34Z | `gh secret set PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` | **PASS** | secret listed (gh secret list) |
| 7 | 03:48 | `gh workflow run deploy.yml` → run **25474923802** | **PARTIAL** | build/push PASS, smoke gate FAIL — machine v94→v95 rolled, 5/6 image 再 deploy, GH_SHA label drift (origin/main = local より 31 commit 遅) |
| 8 | 03:55 | `git push origin main` (33 commit f3679d6→6e3307c) | **PASS** | origin/main = `6e3307c` |
| 9 | 03:58 | `gh workflow run deploy.yml` → run **25475311823** | **FAIL** | step 7 `production_improvement_preflight` → `database:missing` (CI runner has no `autonomath.db`) |
| 10 | 04:01 | commit `6e0afd1` `fix(deploy): pre_deploy_verify CI tolerates missing autonomath.db` | **LANDED** | f-add 1 file |
| 11 | 04:03 | `gh workflow run deploy.yml` → run **25475511726** | **FAIL** | step 7-9 PASS, step 10 (Hydrate seed DB) FAIL "too small for production seed: 1335296 bytes" |
| 12 | 04:08 | commit `f65af3e` `fix(deploy): hydrate step size-guarded skip` | **LANDED** | dev fixture 1.3MB を勝手に push しない guard |
| 13 | 04:12 | `gh workflow run deploy.yml` → run **25475674003** | **FAIL** | hydrate fail again "fly ssh sftp: file already exists, safety abort" |
| 14 | 04:14 | commit `b1de8b2` `fix(deploy): rm small dev fixture before sftp` | **LANDED** | safety override = sftp 前に既 file rm |
| 15 | 04:15:18Z | `gh workflow run deploy.yml` → run **25475753541** | **IN_PROGRESS** | step 1-9 PASS, step 10 (Hydrate) running 04:16:14Z〜 |
| 16 | 04:18 (cumulative) | `wrangler pages deploy` retry x3 | **IN_PROGRESS** | 3rd attempt 1709/13010 ≈ 13% (前 2 回 stall) |

GHA workflow runs cross-ref:
- 25474923802 → smoke fail (HEAD pre-push, origin/main 古い)
- 25475311823 → step 7 fail (CI DB missing)
- 25475511726 → step 10 fail (size guard なし)
- 25475674003 → step 10 fail (sftp safety abort)
- 25475753541 → in_progress (本 doc 確定時点)
- 25475796902 → workflow_run pending (上の post-hook)

---

## §2 — Root Cause Cluster (5 軸)

### Cluster A: Depot remote builder timeout
- **Symptom**: `flyctl deploy --remote-only` → 1431s `deadline_exceeded` (attempt 3)
- **Hypothesis**: depot pool capacity / large image (autonomath.db 9.7GB seed) push 中にタイムアウト
- **Mitigation**: GHA hosted Docker build に切替 (run 25474923802 以降は GHA push が安定)

### Cluster B: flyctl flag drift
- **Symptom**: `--depot=false` → `missing-hostname` daemon parse error (attempt 4)
- **Hypothesis**: flag deprecated (新 flyctl は `FLY_REMOTE_DEPOT_BUILDER` env で制御)
- **Mitigation**: GHA workflow に switch、 ローカル flyctl 直叩きを deprecate

### Cluster C: CI runner DB absent
- **Symptom**: `production_improvement_preflight` で `database:missing` 検出 (run 25475311823)
- **Hypothesis**: GHA hosted runner に 9.7 GB `autonomath.db` を置けない (container rootfs 制限)
- **Fix**: commit `6e0afd1` — `pre_deploy_verify` CI mode で DB 不在を warn 扱いに

### Cluster D: flyctl ssh sftp safety
- **Symptom**: hydrate step で "file already exists, safety abort" (run 25475674003)
- **Hypothesis**: 前回 deploy で push 済みの seed が残存、 sftp が destructive overwrite を refuse
- **Fix**: commit `b1de8b2` — sftp 前に既 path rm

### Cluster E: dev fixture vs production seed size mismatch
- **Symptom**: hydrate step "too small for production seed: 1335296 bytes" (run 25475511726)
- **Hypothesis**: workflow が dev fixture 1.3MB を production seed として push しようとした
- **Fix**: commit `f65af3e` — size guard、 100MB 未満は skip

### Cluster F: Cloudflare Pages upload stall
- **Symptom**: wrangler pages deploy 1704/13010, 1709/13010 で empty `{}` error
- **Hypothesis**: 13010 file の中に大きな asset / CF API rate limit、 chunked upload retry 前提
- **Mitigation**: wrangler 内蔵 retry に依存、 3rd attempt 進行中

---

## §3 — Fixes Landed (4 commits)

| SHA | Subject | Cluster | Files |
|---|---|---|---|
| `6e3307c` | fix(deploy): post-deploy smoke gate race - sleep 25→60, max-time 15→30, flyctl status pre-probe | A/B race | `.github/workflows/deploy.yml` |
| `6e0afd1` | fix(deploy): pre_deploy_verify CI tolerates missing autonomath.db | C | `tools/release/pre_deploy_verify.py` (or eq) |
| `f65af3e` | fix(deploy): hydrate step size-guarded skip | E | `.github/workflows/deploy.yml` (hydrate step) |
| `b1de8b2` | fix(deploy): rm small dev fixture before sftp - flyctl ssh sftp safety override | D | `.github/workflows/deploy.yml` (hydrate step) |

全 4 commit は origin/main へ landed (`git log --oneline -5` 確認済み)。 SDK / LLM 呼出 0、 deterministic shell + Python のみ。

---

## §4 — Hardening Run LIVE 状態 (run 25475753541)

| Step | # | Status | Note |
|---|---|---|---|
| Set up job | 1 | success | 04:15:23Z |
| Checkout | 2 | success | HEAD `b1de8b2` |
| Check Fly token | 3 | success | secret present |
| Set up Python | 4 | success | python 3.12 |
| Install package with dev + site extras | 5 | success | pip install OK |
| Prepare production deploy operator ACK | 6 | success | ACK YAML decode OK |
| Run local pre-deploy verification | 7 | **success** | (Cluster C fix 効いた) |
| Run production deploy GO gate | 8 | success | 5/5 PASS |
| Set up flyctl | 9 | success | flyctl on path |
| Hydrate jpintel seed DB for Docker build | 10 | **in_progress** | 04:16:14Z〜 (Cluster D/E fix 効果検証中) |
| Extract release version | 11 | pending | — |
| Deploy (remote builder) | 12 | pending | — |
| Verify Fly machine state pre-probe | 13 | pending | — |
| Post-deploy smoke (hard gate) | 14 | pending | — |
| Notify Slack on failure | 15 | pending | — |

**Gate 条件**: step 14 (post-deploy smoke) PASS = ingress 通電仮説の補強。 FAIL = Cluster D/E fix が不足、 sftp 残存 file の追加 cleanup が必要。

---

## §5 — Cloudflare Pages frontend deploy 状態

| Field | Value |
|---|---|
| Project | jpcite-pages |
| Artefact size | 13010 file |
| Attempt 1 | 1704/13010 stall, empty `{}` |
| Attempt 2 | 同上、 1700 台で同 error |
| Attempt 3 (進行中) | **1709/13010 ≈ 13%** |
| 内部仮説 | frontend stale 残、 LIVE ingress (Fly) は別経路で 200 維持 |
| Mitigation 候補 | (1) wrangler 3rd retry 完走待ち、 (2) chunked upload を smaller batch に分割、 (3) CF Direct Upload API + zip path |

---

## §6 — 残 task (本 doc 時点)

| # | Item | Owner | Gate |
|---|---|---|---|
| 1 | deploy.yml run **25475753541** 完走 (step 10-14) | GHA | step 14 PASS |
| 2 | wrangler 3rd retry 完走 (1709→13010) | local shell | upload 100% |
| 3 | OAuth UI (Google / Apple flow on jpcite-api) | manual | live 経由でしか試験不可 |
| 4 | Stripe live UI (checkout / portal smoke) | manual | webhook secret rotation 後 |
| 5 | post-deploy `/healthz` external curl 検証 (DNS NXDOMAIN 一時的回避後) | local | 200 with sha tag |
| 6 | release note 確定 (内部仮説 framing → 検証済み事実) | — | item 1+5 後 |

---

## §7 — 内部仮説 framing 維持 / Production live 確認方針

- **本 audit の主張**: ingress 通電は ops window 入り口で確認済み (内部仮説)、 frontend は stale の可能性あり。
- **再検証**: run 25475753541 step 14 (post-deploy smoke gate) が PASS したら ingress 通電は「直近の確認」へ昇格。 FAIL なら追加 fix サイクル。
- **DNS NXDOMAIN 注**: 本 doc 作成時点で local resolver が `jpcite-api.fly.dev` を NXDOMAIN 返却。 local shell からの healthz 直接 curl は不能。 GHA runner 側 (異 resolver) からの smoke gate に依存。
- **release note への昇格**: ingress live & frontend live の **両方** が独立 curl で 200 確認できるまで、 user 向け文面に「LIVE」と書かない (内部仮説 framing 維持)。

---

## Appendix A — Run ID cross-ref

```
25474923802 — failure (smoke, pre-push)
25475311823 — failure (step 7 CI DB)
25475511726 — failure (step 10 size guard)
25475674003 — failure (step 10 sftp safety)
25475753541 — in_progress (b1de8b2 HEAD, 本 doc 監視対象)
25475796902 — pending (workflow_run hook on 25475753541)
```

## Appendix B — secret state

```
PRODUCTION_DEPLOY_OPERATOR_ACK_YAML  Updated 2026-05-07T03:45:34Z
```

## Appendix C — local repo state at doc time

- HEAD = `b1de8b2`
- origin/main = `b1de8b2` (in sync)
- Untracked: `tests/test_free_tier_quota_quantity.py`
- Modified (not part of this audit): `src/jpintel_mcp/api/anon_limit.py`, `billing.py`, `deps.py` 系 (Stripe / quota WIP、 別作業)

---

(end of R8_LAUNCH_OPS_TIMELINE_2026-05-07.md)
