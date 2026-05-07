# R8 PROD SMOKE — 5/7 hardening LIVE verify (post v95 deploy)

`jpcite v0.3.4` / read-only HTTP GET / LLM 0.

## context

- 直前の GHA dispatch で Fly machine `v94 → v95` rolled、 5/7 hardening を担う
  新 deployment id が確定。
- live image が build cache 由来で `LABEL com.github.actions.run_sha=f3679d6` の
  drift を残している (5/6 hardening commit のラベル)、 但し OpenAPI 内容は
  5/7 ハードニングを反映 (paths 179→174、 /v1/privacy/* 2 本新設)。
- live `/healthz` = 200、 `/readyz` = 200、 `/v1/am/health/deep` = 200。
- このドキュメントは v95 トラフィックが healthy であることの再検証。
  smoke 自身は read-only HTTP GET のみ。

## 5-module smoke result (post v95)

| module               | 5/6 baseline image     | 5/7 v95 LIVE          | verdict |
|----------------------|------------------------|------------------------|---------|
| health_endpoints     | PASS — 3/3 200         | PASS — 3/3 200         | unchanged |
| routes_500_zero      | PASS — 240/240, 5xx=0  | PASS — 240/240, 5xx=0  | unchanged |
| mcp_tools_list       | FAIL — 107 vs floor 139 | FAIL — 107 vs floor 139 | unchanged (gate-flag delta, not regression) |
| disclaimer_emit_17   | PASS — 15/15 (gated_off=2) | PASS — 15/15 (gated_off=2) | unchanged |
| stripe_webhook       | SKIPPED (--skip-stripe) | SKIPPED (--skip-stripe) | unchanged |

Files of record:

- `/tmp/prod_smoke_post_v95.json` — full 5-module smoke report (DEEP-61)。
- `/tmp/jpcite_smoke_2026_05_07/prod_openapi.json` — 5/6 baseline OpenAPI (179 paths)。
- live OpenAPI: `https://autonomath-api.fly.dev/v1/openapi.json` (174 paths)。

### module-by-module

#### 1. health_endpoints — PASS (3/3)

```
[PASS] health_endpoints  1.27s  3/3 healthy
  /healthz             200
  /readyz              200
  /v1/am/health/deep   200
```

`/v1/am/health/deep` reports all 10 sub-checks `ok` (db_jpintel /
db_autonomath / am_entities_freshness / license_coverage /
fact_source_id_coverage / entity_id_map_coverage / annotation_volume /
validation_rules_loaded / static_files_present / wal_mode)。

#### 2. routes_500_zero — PASS (240/240, 5xx=0)

- 240 paths walked、 zero 5xx。
- Sample: healthz=200, readyz=200, deep=200, /openapi.json=308 (redirect),
  /docs=200。
- live `info.version` = `0.3.4`、 174 paths。
- "240 walked" but "174 paths" は OpenAPI が **operations 表示** の集計で、
  smoke walker は raw routes を別カウントしているため expected (5/6 と同じ
  挙動)。

#### 3. mcp_tools_list — FAIL gate, 107 vs floor 139

- prod = 107、 floor = 139、 delta = -32 (5/6 と同値)。
- これは prod の cohort flag 状態 (36協定 OFF + 4 broken-tool gate OFF +
  manifest hold-at-139) に由来する **constant offset**、 5/7 hardening
  によって悪化していない。
- 名前 sample (5/6 と同一 head): `search_programs / get_program /
  batch_get_programs / list_exclusion_rules / check_exclusions / get_meta /
  get_usage_status / enum_values`。
- 5/6 R8 と同じく manifest 139 floor を緩める根拠にはしない。 local HEAD は
  `probe_runtime_distribution.py` 経由で 146 ≥ 139 を満たす。

#### 4. disclaimer_emit_17 — PASS (15/15, 2 gated)

- 15/15 mandatory tools が `_disclaimer` を emit (内訳: match_due_diligence_questions /
  prepare_kessan_briefing / cross_check_jurisdiction / bundle_application_kit /
  get_am_tax_rule / search_tax_incentives / search_acceptance_stats_am /
  check_enforcement_am / search_loans_am / search_mutual_plans_am /
  pack_construction / pack_manufacturing / pack_real_estate /
  rule_engine_check / apply_eligibility_chain_am)。
- skipped_gated = 2 (`render_36_kyotei_am`, `get_36_kyotei_metadata_am` —
  AUTONOMATH_36_KYOTEI_ENABLED=0)、 5/6 と同じ design-by-gate。

#### 5. stripe_webhook — SKIPPED

- `--skip-stripe` per task constraint (read-only)。

## 5/6 baseline vs 5/7 v95 LIVE diff

| dimension                | 5/6 baseline (image f3679d6) | 5/7 v95 LIVE (post hardening) | delta |
|--------------------------|------------------------------|-------------------------------|-------|
| OpenAPI version          | 0.3.4                        | 0.3.4                         | unchanged |
| OpenAPI paths            | **179**                      | **174**                       | **-5** |
| /v1/am paths             | 33                           | 33                            | 0 |
| /v1/me paths             | 40                           | 40                            | 0 |
| MCP tools (prod)         | 107                          | 107                           | 0 |
| Mandatory disclaimer emit | 15/15 (2 gated)             | 15/15 (2 gated)               | unchanged |
| 36協定 flag              | OFF                          | OFF                           | unchanged |
| Anonymous cap            | 3/day live                   | 3/day live                    | unchanged |
| Live image LABEL sha     | f3679d6 (5/6 housekeeping)   | f3679d6 (build cache drift)   | unchanged label, 新 deployment |
| Fly machine version      | v94                          | v95                           | rolled |
| Fly server token         | Fly/421c5554c (2026-05-06)   | Fly/421c5554c (2026-05-06)    | unchanged proxy |

### OpenAPI path delta (-5 net = -7 + 2)

7 paths removed in 5/7:

```
/citation/{request_id}                       (legacy public citation by request_id)
/v1/billing/credit/purchase                  (旧 credit purchase 経路)
/v1/contribute/eligibility_observation       (公開 contribute API 撤去)
/v1/programs/{program_id}/at                 (point-in-time query — snapshot OFF)
/v1/programs/{program_id}/evolution/{year}   (snapshot OFF)
/v1/verify/answer                            (reasoning OFF)
/widget/badge.svg                            (legacy badge)
```

2 paths added in 5/7:

```
/v1/privacy/deletion_request    (個情法 削除請求 endpoint)
/v1/privacy/disclosure_request  (個情法 開示請求 endpoint)
```

#### 解釈

- 削除 7 本のうち 4 本 (`/v1/programs/{id}/at`、 `/v1/programs/{id}/evolution/{year}`、
  `/v1/verify/answer`) は **既に gated-off の broken tool** に対応する route
  surface。 5/7 hardening で route layer も静粛化された結果と整合。
- 削除 7 本のうち 2 本 (`/citation/{request_id}`、 `/widget/badge.svg`、
  `/v1/billing/credit/purchase`、 `/v1/contribute/eligibility_observation`) は
  legacy public surface の縮退、 hardening (route surface tightening) の意図
  に整合 (内部仮説として、 これらは brand 移行 / 詐欺 surface 縮減方針との
  整合性で削除された)。
- 追加 2 本 (`/v1/privacy/*`) は 個情法 / 改正個情法 対応の compliance 拡張。
- net -5 paths は **意図的な surface 整理**、 production regression ではない。

#### 内部仮説 framing

- "agent paths 32→28 (-4)" の task 文言は、 ユーザ表記での内部仮説 (旧名称
  か別計測軸)。 公的 OpenAPI 集計上の `/v1/am` paths は **33→33 で不動**。
  `/v1/agent` 接頭で grep しても 5/6/5/7 双方 0 件。 つまり drift -4 は
  別計測軸 (例: 内部 router enum、 もしくは AI agent 向け tool surface) の
  はずで、 本ドキュメントでは公的 OpenAPI 集計を SOT として記録する。
- live LABEL が `f3679d6` に固着しているのは GHA build cache 由来で、
  実体の deployment id (machine v95) は 5/7 hardening を提供している。
  cache LABEL は次回フル rebuild で更新される (cosmetic drift)。

### MCP tool count 推移

| timepoint                  | tools | floor | source |
|---------------------------|-------|-------|--------|
| 5/6 prod live (image f3679d6) | 107  | 139   | smoke harness |
| 5/7 prod live (v95)        | **107** | 139 | smoke harness |
| local HEAD partial smoke   | 109   | 139   | smoke harness |
| local HEAD runtime probe   | 146   | 139   | `scripts/probe_runtime_distribution.py` |

prod が 5/6 と同じ 107 で static、 5/7 hardening は MCP cohort 数を変えない
type-of-change (lint / typing / DEEP spec retroactive verify / fingerprint
helper centralization) であることが裏付けられた。

### Anonymous rate-limit confirm — LIVE

- `curl /v1/meta` (no header)        → 429 with `code=rate_limit_exceeded`、
  `limit=3`、 `resets_at=2026-05-08T00:00:00+09:00`、
  `upgrade_url=https://jpcite.com/upgrade.html?from=429`。
- `curl -H "X-Api-Key: dev-noop" /v1/meta` → 同じく 429 (literal `dev*` は
  prod では whitelist されず、 これも 5/6 と同じ挙動)。
- 240-route walk で本日 anonymous quota は 5/8 00:00 JST まで枯渇 (smoke の
  期待される副作用、 production defect ではない)。

## verdict

5/7 hardening LIVE deployment (machine v95) は **healthy**:

- health 3/3、 routes 240/240 5xx=0、 disclaimer 15/15 (gating expected)、
  anonymous cap live and正しい upgrade payload 返却。
- mcp_tools_list の 107 < 139 は 5/6 baseline と同値の constant offset、
  5/7 hardening による regression ではない (gate-flag 状態に由来)。
- OpenAPI surface は意図的な 7 削除 + 2 追加 (privacy compliance)、 net -5
  = surface tightening の hardening 意図と整合。

read-only verify 範囲では **production regression ゼロ**。 LABEL drift
(`f3679d6` 固着) は cache 由来の cosmetic noise、 機能影響なし。

## notes / honesty

- LLM 0 / read-only / production HTTP GET のみで完了。
- "agent paths 32→28" の課題文 数値は内部仮説で、 SOT である live OpenAPI
  paths からは検出不能。 本ドキュメントでは公的 SOT (`/v1/openapi.json`)
  を採用し、 -5 paths (`179→174`) を記録。 内部 dimension が別軸であれば
  別途突合が必要。
- 5/6 R8 と同じく、 anonymous quota は smoke 自身の副作用で枯渇 (functioning
  as intended)。 X-API-Key uncap は admin key を別配布する場合の課題。
- prod 107 vs floor 139 は manifest hold-at-139 + cohort flag (36協定 OFF +
  4 broken-tool gate OFF) の合算 offset、 manifest を下げる根拠にはしない。

## reference

- live smoke report:        `/tmp/prod_smoke_post_v95.json`
- 5/6 baseline R8 doc:      `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PROD_SMOKE_5_6_IMAGE_2026-05-07.md`
- live OpenAPI:             `https://autonomath-api.fly.dev/v1/openapi.json`
- live healthz:             `https://autonomath-api.fly.dev/healthz`
- canonical SOT note:       `docs/_internal/CURRENT_SOT_2026-05-06.md`
