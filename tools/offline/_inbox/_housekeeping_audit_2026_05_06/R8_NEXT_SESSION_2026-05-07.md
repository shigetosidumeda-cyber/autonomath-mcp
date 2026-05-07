# R8 — Next Session Candidate Plan (2026-05-07)

> **Framing**: this document is an *internal hypothesis* of the next session
> queue. Step 3-4 are **NOT YET EXECUTED**. No production deploy / DNS cutover /
> Stripe live mode / public publish has occurred. NO-GO conditions remain in
> force until the operator interactive sign in Step 2 completes.

> **Constraint reminder**: LLM API call count for this document = 0. No
> destructive overwrite (this file is new). All claims in §1 are derived from
> existing R8 audit artifacts under
> `tools/offline/_inbox/_housekeeping_audit_2026_05_06/`.

---

## §1 Cumulative Progress (2026-05-06 → 2026-05-07)

### 1.1 Commit / file delta

| Metric | Value | Source |
|---|---|---|
| Commits since 2026-05-06 00:00 JST | **28** | `git log --since="2026-05-06 00:00" --until="2026-05-07 23:59" --oneline` |
| Files touched (cumulative) | **~2,369** | `git log … --shortstat` aggregate |
| Insertions | ~302,269 | same |
| Deletions | ~44,279 | same |

(Prior internal estimate "27 commit / ~2,200+ file change" was conservative;
actual is 28 commits / ~2,369 files.)

### 1.2 Quality bars

| Bar | 2026-05-06 baseline | 2026-05-07 current | Δ | Source |
|---|---|---|---|---|
| `mypy --strict` errors (src/) | 348 | **69** | **-279 (-80.2%)** | `R8_FINAL_IMPLEMENTATION_MANIFEST_2026-05-07.md` |
| `ruff` residual lint | 14 | **5** | -9 | latest commit `2953db1` summary |
| Acceptance YAML rows | 252 | **286** | +34 (+13.5%) | `R8_ACCEPTANCE_CRITERIA_CI_GUARD.md` |
| Acceptance pass | 252/252 | **286/286** | 100 % | same |
| Automation ratio | 0.97 | **0.99** | +0.02 | same |
| Smoke modules | 4/4 | **5/5 ALL GREEN** | +1 module | latest run |
| MCP tool count (manifest) | 146 | **148** | +2 (post-manifest hold) | `mcp/manifest_v0.3.4.json` |
| DEEP spec inconsistencies | unknown | **0 / 33** | — | `R8_33_SPEC_RETROACTIVE_VERIFY.md` |
| Production gate (5 axis) | not run | **4/5 PASS** | — | `R7_FAILURE_MODES.md` |
| R8 audit doc count | 0 | **11+** | +11 | this folder listing |

### 1.3 Residual lint (5)

- 4 × `B008` (FastAPI `Depends(...)` default) — false positive, **skip
  confirmed** (FastAPI idiom).
- 1 × `A002` (builtin shadowing in `id_translator`) — **skip confirmed**
  (public API stability > stylistic rename).

### 1.4 Manifest decision

- **Option B confirmed**: hold manifest at v0.3.4 / 148 tools (2 post-manifest
  routes documented but not registered). Bump to v0.3.5 + sample\_arguments
  composition for the 7 post-manifest tools is queued in Step 1 below.

### 1.5 Operator-only blocker remaining

Truly *only* operator-side, *only one* interactive item:
1. ACK YAML interactive sign with `info@bookyou.net` (PGP / S/MIME / ED25519 —
   choose-one) — see `R8_ACK_YAML_DRAFT_2026-05-07.yaml`.

The other operator items (Fly secret push, public OAuth client registration)
are non-interactive credentials paste and admin-console clicks; they do **not**
require human creative decision-making, only access tokens the AI cannot hold.

---

## §2 Four-Step Next-Session Plan

### Step 1 — AI-completable (1-2 hour) **(no operator gate)**

| ID | Task | Acceptance | Risk |
|---|---|---|---|
| 1.1 | `mypy --strict` 69 → 0 across src/ | exit code 0 | Low. residual is 22× `no-untyped-call` + 17× `untyped-decorator` + 30× misc; the 22 + 17 are mechanical type-stub additions, the 30 misc need case-by-case. |
| 1.2 | Manifest bump v0.3.4 → **v0.3.5**, register 7 post-manifest tools, attach `sample_arguments` per tool | manifest schema validate green; tool count 148 → **155**; CI `manifest_lint` green | Low. tools are already wired in routers; only manifest entry + sample needed. |
| 1.3 | CHANGELOG.md final entry for 5/6-5/7 hardening (28 commit rollup) | entry present, semver = 0.3.5 | Trivial. |
| 1.4 | Re-run 5-module smoke + acceptance after 1.1/1.2 | 5/5 green, 286/286 pass | Low. |

> **Gate to Step 2**: Step 1 PASS = mypy 0, manifest 155 tools, smoke 5/5,
> acceptance 286/286.

### Step 2 — Operator interactive (1 hour) **(human-in-the-loop)**

| ID | Task | Operator action | Verification |
|---|---|---|---|
| 2.1 | `.env.local` populate (5 mandatory secrets) | paste tokens locally | `python scripts/check_secrets.py` exits 0 |
| 2.2 | Fly secret push (autonomath-api app, Tokyo region) | `fly secrets set …` from `R8_FLY_SECRET_SETUP_GUIDE.md` | `fly secrets list` shows 5 + 36 協定 + APPI keys |
| 2.3 | ACK YAML sign with `info@bookyou.net` | choose PGP / S/MIME / ED25519, sign `R8_ACK_YAML_DRAFT_2026-05-07.yaml` | signature verifies; commit signed YAML |

> **Gate to Step 3**: 2.1-2.3 all complete → NO-GO removed.

### Step 3 — Launch (1 day) **(NOT YET EXECUTED)**

| ID | Task | Rollback |
|---|---|---|
| 3.1 | `fly deploy` autonomath-api Tokyo region | `fly releases rollback` |
| 3.2 | DNS cutover: `jpcite.com` / `api.jpcite.com` / `docs.jpcite.com` | revert A/AAAA records |
| 3.3 | Stripe live mode 切替 | webhook secret swap; Stripe dashboard → test mode |
| 3.4 | Cloudflare Pages deploy (docs site) | Pages rollback button |

> **Hypothesis only**. No deploy attempt has been made. NO-GO triggers in
> `R8_HIGH_RISK_PENDING_LIST.md` still apply.

### Step 4 — Post-launch verify (1 week) **(NOT YET EXECUTED)**

| ID | Task | Cadence |
|---|---|---|
| 4.1 | 5-module smoke 本番再走 | day 0, day 1, day 7 |
| 4.2 | 公開 OAuth client (Google / GitHub) 登録 | day 1 |
| 4.3 | PyPI / npm / MCP Registry / Smithery / DXT publish | day 2 |
| 4.4 | Billing fail-closed re-verify (live Stripe) | day 3 |
| 4.5 | Cron job verification (etl + ops lanes) | day 1 |

---

## §3 Risk register (carried forward)

- **R-1** mypy strict 69 残: 30 misc が ABI 変更を要求する場合は v0.3.5 では型
  注記のみ・実装変更は v0.3.6 に分割（destructive 上書き禁止原則の回避策）。
- **R-2** Step 2.3 ACK 署名: PGP/S/MIME/ED25519 の選択は operator 判断。AI は
  draft までで停止する。
- **R-3** Step 3 DNS cutover: 既存 zeimu-kaikei.ai 301 redirect chain が壊れる
  可能性 → `R8_HIGH_RISK_PENDING_LIST.md` の検証手順を踏むこと。
- **R-4** Step 4.3 publish: PyPI 名前衝突 (`jpcite` vs 旧 `autonomath-api`) を
  pre-flight check 必須。

---

## §4 Done definition for next session

```
[ ] Step 1.1 mypy --strict 69 → 0
[ ] Step 1.2 manifest v0.3.5 / 155 tools / sample_arguments green
[ ] Step 1.3 CHANGELOG entry for 5/6-5/7 rollup
[ ] Step 1.4 smoke 5/5 + acceptance 286/286 re-run green
[ ] Step 2.1-2.3 operator sign-off received
```

Step 3-4 are *queued* for the session **after** Step 2 completes, and require a
separate explicit operator GO.

---

## §5 Provenance

- Source artifacts (all under `tools/offline/_inbox/_housekeeping_audit_2026_05_06/`):
  - `R7_SYNTHESIS.md` — R7 closure
  - `R7_FAILURE_MODES.md` — production gate matrix
  - `R7_AI_DOABLE.md` — Step 1 backlog provenance
  - `R7_OPERATOR_ACTIONS.md` — Step 2 / 3 / 4 provenance
  - `R8_FINAL_IMPLEMENTATION_MANIFEST_2026-05-07.md` — current state
  - `R8_ACCEPTANCE_CRITERIA_CI_GUARD.md` — 286-row baseline
  - `R8_FLY_SECRET_SETUP_GUIDE.md` — Step 2.2 procedure
  - `R8_ACK_YAML_DRAFT_2026-05-07.yaml` — Step 2.3 draft
  - `R8_HIGH_RISK_PENDING_LIST.md` — NO-GO maintained
  - `R8_DEEP_CROSS_REFERENCE_MATRIX.md` — DEEP-1..65 traceability
  - `R8_33_SPEC_RETROACTIVE_VERIFY.md` — 0 / 33 inconsistency
  - `R8_LANE_LEDGER_AUDIT_2026-05-07.md` — atomic claim audit
- Git provenance: `git log --since="2026-05-06 00:00" --until="2026-05-07 23:59"`
  (28 commits, ~2,369 files, +302k / -44k lines).
- LLM API call count for this document: **0**.

---
*Document author: jpcite operator (Claude Code Max Pro session, 2026-05-07).*
*Status: candidate — awaiting operator GO for Step 1 execution.*
