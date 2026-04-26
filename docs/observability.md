# Observability — Operator Runbook (internal)

> **このページは公開ドキュメントから除外** されている (`mkdocs.yml::exclude_docs`).
> 運用上の機密情報 (Sentry プロジェクト ID、Fly metrics endpoint、Stripe webhook
> secret 取扱い) を含むため、公開リポジトリ参照のみで完結する。
> Solo operator: 梅田茂利 / info@bookyou.net.

最終更新: 2026-04-25 (launch convergence wave 24)

---

## 目次

1. [SLO](#slo)
2. [Sentry 設定手順](#sentry)
3. [Fly metrics](#fly-metrics)
4. [Cloudflare Pages analytics](#cf-analytics)
5. [Stripe revenue & dispute](#stripe)
6. [Alert rules (4 件 + pager)](#alerts)
7. [On-call rotation](#oncall)

---

## SLO

<a id="slo"></a>

| 指標 | Target | 計測 | 月間予算 |
|---|---|---|---|
| API availability | **99.5%** | UptimeRobot 1-min probe + Fly health check | 21.6 min downtime |
| API P95 latency (`/v1/programs/search`) | < 800 ms | Fly metrics histogram | — |
| MCP availability (stdio) | 99.0% | passive (ユーザー報告 + GitHub issue) | 7.3 hr |
| Cost overrun | ≤ 100% of monthly cap (¥10,000) | `scripts/cron/stripe_cost_alert.py` | hard alert at 80% |

**注:** `docs/sla.md` (公開) では 99.0% と表記している。99.5% はこの runbook
における internal target で、99.0% を契約上の保証 (SLA) として、99.5% を
運用 KPI (SLO) として 2-tier 管理する。

### Downtime budget

- Monthly: 21.6 min ( = 30 days × 24 hr × 60 min × (1 − 0.995) )
- Weekly: 5.04 min
- 単一 incident で月予算の 50% (10.8 min) を超えたら postmortem 必須
  (`docs/_internal/incident_runbook.md`)

---

## Sentry 設定手順

<a id="sentry"></a>

### 起動条件 (two-gate)

`src/jpintel_mcp/api/main.py::_init_sentry` は **両方** を満たす場合のみ
`sentry_sdk.init(...)` を呼ぶ:

1. `SENTRY_DSN` env var が空でない
2. `JPINTEL_ENV=prod`

dev / test / staging では DSN が漏れていても init しない。これは P1-5
(Sentry エラー数アラート) を staging ノイズで誤発報させないため。

### 初期化パラメータ

```python
sentry_sdk.init(
    dsn=settings.sentry_dsn,
    environment=settings.sentry_environment,  # "production"
    traces_sample_rate=0.1,        # 10% sample (cost 抑制)
    profiles_sample_rate=0.1,      # idem
    send_default_pii=False,        # PII redaction default ON
    include_local_variables=False, # X-API-Key, Stripe-Signature 漏出防止
    max_breadcrumbs=50,
    before_send=sentry_before_send,                # api/sentry_filters.py
    before_send_transaction=sentry_before_send_transaction,
)
```

スクラバ (`src/jpintel_mcp/api/sentry_filters.py`) が以下 header を `[scrubbed]`
に置換: `x-api-key / authorization / cookie / stripe-signature /
x-forwarded-for / fly-client-ip / x-real-ip`. `/billing` 配下の request body
+ query_string も丸ごと drop する。

### Cron からの capture

`src/jpintel_mcp/observability/sentry.py` が `safe_capture_exception` /
`safe_capture_message` を提供する。FastAPI lifespan を経由しない cron 系
スクリプトは:

```python
from jpintel_mcp.observability import safe_capture_message
safe_capture_message("budget 80% reached", level="warning", month="2026-05")
```

Cron 側も同じ two-gate で active 化する (DSN 設定 + `JPINTEL_ENV=prod`).

### Sentry プロジェクト設定

| 項目 | 値 |
|---|---|
| Org | `bookyou` |
| Project slug | `autonomath-api` |
| DSN secret | Fly: `flyctl secrets set SENTRY_DSN=...` |
| Quota plan | Developer (free) → 5k errors / 10k transactions / month |
| Retention | 30 days (default) |
| Email contact point | info@bookyou.net |

DSN ローテーション: Sentry UI の Project Settings → Client Keys (DSN)
で revoke + new key 発行 → `flyctl secrets set SENTRY_DSN=...` →
`flyctl deploy` で機械再起動.

---

## Fly metrics

<a id="fly-metrics"></a>

`fly.toml::[metrics]` で port 9091 / path `/metrics` を expose. Prometheus
形式. Fly が組み込みで scrape しダッシュボード化する (
[https://fly-metrics.net/](https://fly-metrics.net/) — Grafana embed).

主要メトリクス:

- `fly_app_running_machines` (P0-3 alert 用)
- `fly_instance_load_average_1m`
- HTTP histogram: `fly_app_http_response_time_seconds_bucket{path,status}`
- `fly_app_concurrency` — soft 50 / hard 100 (`fly.toml::http_service.concurrency`)

Custom app-level メトリクスは現状 expose しない (FastAPI に `prometheus-client`
を入れていない). 次の launch wave で追加予定. それまでは structlog JSON
ライン (`autonomath.query` channel) を Cloudflare R2 に日次 archive し、
`scripts/analyze_telemetry.py` で集計する.

---

## Cloudflare Pages analytics

<a id="cf-analytics"></a>

- 静的 site (`autonomath.ai/`, `autonomath.ai/docs/`) は Cloudflare Pages
- Web Analytics (free tier) を `site/` の HTML head にスニペット注入済 (
  `overrides/partials/footer.html`).
- 計測対象: page view / referrer / 国コード / Core Web Vitals (LCP / FID / CLS)
- ダッシュボード: Cloudflare dash → Web Analytics → `autonomath.ai`
- PII 非収集. IP / cookie 不使用 (Cloudflare の cookieless analytics 機能).

KPI:
- 日次 unique visitors
- `/docs/getting-started` → checkout 流入率 (現在ベースライン取得中)
- 4xx / 5xx 比率 (Cloudflare Pages 側 — Fly オリジン側とは別)

---

## Stripe revenue & dispute

<a id="stripe"></a>

### Revenue 計測

- Stripe Dashboard → Reports → Revenue (MRR / cohort)
- Webhook ログ: `jpintel.billing` structlog channel + `usage_events` table
- `scripts/cron/stripe_cost_alert.py` が MTD 手数料を集計し、80%/100%/150% で
  Sentry message 発報.

### Dispute / chargeback

- Stripe Radar が自動検知. webhook `charge.dispute.created` を listen し
  `src/jpintel_mcp/api/billing/webhook.py` でログ + Sentry capture.
- 対応 SLA: 7 日以内に Stripe Dashboard で evidence 提出.
- 月次 dispute rate > 1% で P1 alert (Stripe 側で account suspension 警告
  しきい値が約 0.75% — それを下回る防衛ライン).

### 事前監視

- `docs/disaster_recovery.md` の Stripe smoke test を週次 cron で実行
  (`scripts/stripe_smoke_e2e.py`). Test mode webhook 送受信を検証。

---

## Alert rules (4 件 + pager)

<a id="alerts"></a>

このプロダクトは **solo + zero-touch** (`feedback_zero_touch_solo`) なので
alert rule は最小限に絞る。**Slack / Discord / SMS / Twilio は使わない** —
すべて email + Sentry の 2 channel.

| # | Severity | Trigger | Channel | Pager (即時応答必須) |
|---|---|---|---|---|
| **1** | **Critical** | Fly machines = 0 (app fully down) **OR** `/healthz` ≥ 3 連続失敗 | Sentry fatal + email | YES — 30 min 以内 |
| **2** | **High** | 5xx error rate > 2% (15 min window) **OR** Sentry 新規 issue volume > 20 / hour | Sentry error + email | NO — 4 hr 以内 |
| **3** | **Medium** | Monthly cost > 80% of budget (¥8,000) **OR** Stripe dispute rate > 1% / month | Sentry warning + email | NO — 24 hr 以内 |
| **4** | **Low** | P95 latency > 800 ms (1 hr window) **OR** zero-result query rate > 30% | Sentry info + email digest (週次) | NO — 翌週レビュー |

### Pager threshold

**Pager に乗るのは Severity 1 のみ**. Email digest は Severity 1-3 すべて。
Severity 4 は週次の `weekly_digest.py` 出力に集約され、即時通知しない
(false positive 抑制).

### Alert routing

```
Sentry → email (info@bookyou.net) … 全 severity
Sentry → mobile push (Sentry iOS app) … Severity 1 のみ
                                          ↑
                                      Sentry UI で
                                      Notification Settings →
                                      Workflow → 「fatal level only」
```

Twilio / Slack / Discord webhook は導入しない (運用負荷とノイズリスク).

### False positive 抑制

- `JPINTEL_ENV != prod` の場合は init 自体スキップ (上述 two-gate)
- `before_send` で 4xx (validation error) を drop — 顧客側ミスを Sentry
  に流さない (`api/sentry_filters.py`).
- Sentry rate limit を quota の 50% で artificial drop 設定 (free tier
  保護).

---

## On-call rotation

<a id="oncall"></a>

**全シフト = 梅田茂利 (info@bookyou.net) solo**.

- 平日 / 週末 / 祝日 すべて単独
- 旅行中・移動中も Sentry iOS push が届く設定
- バックアップ on-call なし (solo + zero-touch 制約上構造的に不可)
- 30 min 以内応答できないと判明した場合のみ:
  1. status page (`autonomath.ai/status`) に手動で incident 起票
  2. `service@autonomath.ai` 自動応答に "investigating" を一時掲示
  3. 復旧後 24 hr 以内に postmortem を `docs/_internal/incidents/` に記録

### Escalation

solo なので escalation 先は無い。重大障害 (24 hr+ downtime) 発生時は:
- Cloudflare Pages を maintenance mode に切替 (静的バナー)
- Stripe metered billing を一時停止 (新規 usage_record 送信を止める)
- 原因解析後、影響顧客全員に手動 email (Postmark)

---

## 関連 doc

- `docs/sla.md` (公開、99.0% target)
- `docs/monitoring.md` (公開、alert policy 概観)
- `docs/disaster_recovery.md` (内部、`exclude_docs`)
- `docs/_internal/incident_runbook.md` (内部)
- `docs/_internal/observability_dashboard.md` (内部、Grafana layout)
