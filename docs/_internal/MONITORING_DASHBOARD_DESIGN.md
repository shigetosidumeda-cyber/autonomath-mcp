# Monitoring Dashboard Design (Wave 50 / Wave 49)

Status: DESIGN ONLY (実装は Wave 51 以降)
Owner: jpcite operator
Last updated: 2026-05-16

## 目的

Wave 50 RC1 launch 後の運用監視を **1 dashboard** で集約する。
Wave 49 organic axis + Wave 50 RC1 軸 + AWS canary 軸 + 5 preflight gate 軸を統合表示し、operator (solo) が 30 秒で「今日全部 green か」を判断できる single page を提供する。

## 監視 8 軸

| # | 軸 | 内容 | 健全 SLO |
|---|------|------|----------|
| 1 | Wave 49 G1 organic funnel | daily uniq visitor / 6 stage (Discover→Justify→Trust→Access→Pay→Retain) conversion rate / 3 連続観測 streak | 3 連続日 stage1 > 0 |
| 2 | Wave 49 G2 listing | Smithery + Glama + Anthropic registry の HTTP status / Discord escalation 状態 | 3 surfaces すべて 200 |
| 3 | Wave 49 G3 cron 5/5 | 5 daily cron (organic / pricing / discovery / openapi / capsule) の last 24h SUCCESS rate / next run schedule | 5/5 SUCCESS |
| 4 | Wave 49 G4 x402 | `am_x402_payment_log` row count / `first_txn_detected.json` content | row delta ≥ 0 (negative 不可) |
| 5 | Wave 49 G5 wallet | `am_credit_transaction_log` topup count / balance update 履歴 | balance update lag < 24h |
| 6 | AWS canary 8/8 prereq | scorecard.state / live_aws / preflight 5/5 / 4 budget guards / 7 teardown scripts / aws CLI / token (live_aws_unlock + teardown) | 8/8 OK |
| 7 | Wave 50 production gate 7/7 | validate_release_capsule / agent_runtime_contracts / openapi_drift / mcp_drift / release_capsule_route / aws_blocked_preflight_state / cloudflarepages_typecheck | 7/7 PASS |
| 8 | Quality gate 4 軸 | mypy 0 / ruff 0 / pytest 9300+ / coverage 90% | 全 4 軸 green |

## Data source

- **GitHub Actions API** (`gh run list --workflow=<name> --limit 1 --json`) — cron + workflow status
- **autonomath.db direct query** (`sqlite3 file:autonomath.db?mode=ro`, read-only attach) — x402 / wallet ログ
- **site/releases/rc1-p0-bootstrap/\*.json** — preflight artifacts (scorecard / live_aws / canary_prereq)
- **production gate scripts の subprocess** — `python scripts/release/validate_release_capsule.py --check-only` 等を subprocess で叩いて exit code 収集
- **.well-known/{agents,llms,trust,jpcite-release}.json** — discovery surfaces の curl HEAD で 200 確認

## Output format

- **single page HTML** at `site/status/index.html`
  - Tailwind CDN + 純粋 fetch('./dashboard_state.json')、LLM 推論 0
  - 8 軸を 4×2 グリッドで配置、各カードは status badge (green/yellow/red) + 最終更新時刻 + 直近 3 観測スパークライン
- **JSON state** at `site/status/dashboard_state.json`
  - schema: `{ "updated_at": "...", "axes": [{ "id": "g1_organic", "status": "green", "value": ..., "history": [...] }] }`
- **更新 cadence**: 30 分 (push 系ではなく pull 型 cron)

## Implementation 候補 (Wave 51 で実装)

- `scripts/cron/dashboard_aggregator_30min.py` — 8 軸 collector + JSON 書出
- `.github/workflows/dashboard-30min.yml` — cron `*/30 * * * *`、aggregator 実行 + `site/status/` commit
- `site/status/index.html` — Tailwind CDN + JSON fetch、static page (Cloudflare Pages 配信)
- artifact path: `site/status/dashboard_state.json` (Pages auto-deploy で即時公開)

## Non-goal

- **Grafana / Datadog 等の SaaS 監視** — organic only / zero-touch / solo 原則に違反、SaaS dependency 増やさない
- **LLM 経由の自然言語 summary** — NO LLM API 原則 (¥0.5/req 構造で自前 API 呼び禁止)、status badge + 数字のみ
- **リアルタイム push (SSE / WebSocket)** — 30 分 cadence で operator 判断に十分、cost/complexity 増だけで実益なし
- **alert / pager 連携** — solo 運用、メール通知のみ十分 (Wave 51 で必要なら GitHub notification mail で代替)

## Wave 51 implementation trigger

以下 **all 3** が満たされたら Wave 51 で実装着手:

1. Wave 50 RC1 が production gate 7/7 green で landed
2. Wave 49 G1 organic funnel で 3 連続日 stage1 観測達成
3. AWS canary 8/8 prereq scorecard が green に到達 (live_aws_unlock 後)

3 条件未達のうちは本 doc を SOT として保持し、aggregator 実装は着手しない。
