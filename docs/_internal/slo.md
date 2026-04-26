# SLO + Error Budget — AutonoMath

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

> **Internal runbook** (`mkdocs.yml::exclude_docs`). Public commitment lives
> in `docs/sla.md` (99.0% contractual). This file defines the **operational**
> targets (SLOs) we run to, the error budgets they generate, alarm
> thresholds, and the solo escalation path.
> Operator: Bookyou株式会社 / 梅田茂利 / info@bookyou.net.

最終更新: 2026-04-26
施行: launch (2026-05-06)
レビュー周期: 四半期 (`docs/sla.md` §7.2 と同期)

---

## 1. なぜ SLO を 4 本に絞るか

メモリ `feedback_completion_gate_minimal`: 「done でないと本番出せない最小
5-8 本」。SLO も同じ思想で **最小 4 本**。dashboard
(`docs/_internal/observability_dashboard.md`) の panel は 12 あるが、
**契約・人間判断・ページャ起動の根拠** にする SLO は 4 本だけに固定する。
他の signal (CPU/mem/disk/WAL) は capacity warning であって SLO ではない。

メモリ `feedback_zero_touch_solo`: solo + zero-touch なので
PagerDuty / Datadog / Slack Connect は採用しない。SLO の通知経路は
**Sentry email + Sentry iOS push + UptimeRobot email** の 3 つだけ。
有料 SaaS 追加は禁止。

---

## 2. 4 本の SLO

| # | SLO | Target | 計測ソース | Window |
|---|---|---|---|---|
| **S1** | API availability (`api.autonomath.ai/v1/*`) | **99.5%** monthly | UptimeRobot 1-min probe of `/healthz` (multi-region majority vote) | カレンダー月 |
| **S2** | `/v1/programs/prescreen` p95 latency | **< 500 ms** | `autonomath.query` structlog `latency_ms` field, p95 over 1h sliding window | 1 hour |
| **S3** | Stripe webhook ingest 成功率 | **≥ 99.9%** | `stripe_webhook_events` insert success / Stripe Events API delivery_attempt | 7 day rolling |
| **S4** | Anonymous rate limit accuracy | **±5%** of nominal 50/月/IP | `anon_rate_limit` table audit (per-IP monthly count vs. cap) | カレンダー月 |

### S1 数値根拠

- 99.5% = 月間最大 **21.6 min** ダウンタイム
- 99.0% は SLA (公開), 99.5% は SLO (内部)。**0.5% を error budget として
  consume** することで、計画再起動 (release / migrate / volume scale) を
  burn せずに吸収できる
- Fly.io single-machine NRT region の実績 baseline ≥ 99.7%
  (`docs/_internal/perf_baseline_v15_2026-04-25.md`) を踏まえて 99.5% は
  conservative target
- 99.9% は single-region single-machine では構造的に到達不可。multi-region
  は launch+90d までは Fly cost と運用負荷に見合わない

### S2 数値根拠

- prescreen は profile match → ranked top-N を返す **同期 SQL 路線**。
  L4 cache (`api/_health_deep.py` 30s TTL とは別、`cache/l4.py`) hit 時
  ~50 ms、miss 時 ~250 ms (`perf_baseline_v15_2026-04-25.md` 実測)
- p95 < 500 ms は **miss path 込み + FTS5 trigram fallback** を許容する
  上限。これを超えたら L4 cache 失効頻度 / WAL bloat / sqlite vacuum を
  疑う
- LLM agent 用途 (MCP 経由含む) で 1 turn あたり 2-3 prescreen 連打は
  普通。p95 500 ms × 3 = 1.5 s が agent 1 turn の許容予算。これを越える
  と user 体感が degrade

### S3 数値根拠

- Stripe webhook 失敗 = **顧客が払ったが key が発行されない** 直結事故。
  メモリ `feedback_autonomath_fraud_risk` の core risk
- 99.9% = 1000 webhook あたり 1 失敗まで許容。launch 1 ヶ月の想定
  webhook 量 (subscription create + invoice paid + invoice payment_failed
  合算) は ~300/月、つまり **0 失敗を許容する月が 3 ヶ月に 1 回出る**
  運用感
- 100% を SLO にすると release window の deploy race で false alarm が
  増える。99.9% は signature mismatch / dedup race を吸収する余裕

### S4 数値根拠

- Anonymous 50/月/IP は free → paid の **唯一の friction point**。これが
  甘い (例えば 100 まで通る) と paid 転換が消える、厳しい (40 で打ち切る)
  と SLA 侵害クレームが来る
- ±5% = 50 ± 2.5 → 47-53 の範囲は許容。JST 月初 reset 境界の clock skew
  と分散 race condition を吸収する
- 計測は `anon_rate_limit` テーブルを月初に SQL 集計するだけで済む
  (cron `scripts/cron/anon_quota_audit.py`、launch +1 週で書く予定)

---

## 3. Error budget calc

### S1 (availability)

```
budget_min  = month_total_min * (1 - 0.995)
            = (30 * 24 * 60) * 0.005 = 21.6 min/month
weekly      = 5.04 min
single_event = budget * 0.5 = 10.8 min
                 ↑ 単一インシデントで月予算 50% 越えたら postmortem 必須
```

### S2 (latency)

```
budget_breach_count = total_requests * 0.05  ← p95 = 5% breach 許容
                      ≒ 50 breaches per 1000 prescreen calls in 1h window
alarm_at = breach_count > 100 in 1h (= 2x budget)
```

### S3 (webhook)

```
budget = total_webhooks * 0.001 = 1 fail per 1000
         ≒ ~0.3 fail/month at launch volume → 1 fail/month は warn
                                              2 fail/month は alarm
```

### S4 (rate limit accuracy)

```
budget = ±5% of 50 = 2.5 req
audit_breach = | actual_max_per_IP - 50 | > 5
alarm_at = >1% of unique IPs in breach (= structural drift, not edge race)
```

---

## 4. Alarm threshold + notification

すべて Sentry email + UptimeRobot email + Sentry iOS push のいずれか。
**Slack / Discord / PagerDuty / Datadog / Twilio は使わない**
(`feedback_zero_touch_solo`).

| SLO | Warn (budget 50%) | Alarm (budget 100%) | Pager (budget 200%) |
|---|---|---|---|
| S1 | 月内 10.8 min downtime | 月内 21.6 min | 月内 43.2 min OR 単発 ≥10 min |
| S2 | p95 ≥ 500 ms 30 min 連続 | p95 ≥ 500 ms 1 h 連続 | p95 ≥ 1000 ms 15 min |
| S3 | 月内 1 webhook 失敗 | 月内 2 webhook 失敗 | 任意の signature mismatch (即時) |
| S4 | unique IP の 1% で >+5 | unique IP の 5% で >+5 | カレンダー月終了時 |

**Pager (= Sentry iOS push 即応)** は S1 / S3 のみ。S2 / S4 は email
digest で十分 (顧客側 friction はあるが破滅的ではない)。

---

## 5. 計測実装ステータス

| SLO | 既存実装 | 不足 | 追加コミット |
|---|---|---|---|
| S1 | UptimeRobot 設定 (`observability.md` §Alert rules), `/healthz` (`api/meta.py:101`), `/readyz` (`api/main.py:872`), `/v1/am/health/deep` (`api/_health_deep.py`) | — | — |
| S2 | `_QueryTelemetryMiddleware` (`api/main.py:244`) が全 request の latency_ms を `autonomath.query` に出力 | prescreen の **business field** (tier_dist / result_count / profile fill) | `api/prescreen.py` に `autonomath.prescreen` channel 追加 (本 wave) |
| S3 | `stripe_webhook_events` table + `api/billing.py:709` `stripe.event` info log | webhook 失敗の structured event log | 既存 `logger.error` で十分 (failure path に残る) |
| S4 | `anon_rate_limit` table + `api/anon_limit.py` の 429 path | per-IP monthly audit cron | launch+1w に `scripts/cron/anon_quota_audit.py` 追加予定 |

新規追加 channel:
- `autonomath.prescreen` — `{event:"prescreen", tier, total_considered, result_count, tier_dist, caveat_count, profile_filled}`
- `autonomath.keys` — `{event:"key.issued", tier, key_hash_prefix, has_subscription, has_email, issued_at}`

両 channel は既存 `_query_log` (`autonomath.query`) と同じ structlog
JSON pipeline を流れる (`api/logging_config.py`). 追加 dependency なし。

---

## 6. Escalation path (solo)

`docs/observability.md` §On-call rotation を参照。要点:

1. **全シフト = 梅田茂利 solo**. backup on-call 不在
2. Pager 起動時の SLA: 30 min 以内応答 (Sentry iOS push を移動中も拾う)
3. 30 min 応答不可と判明した瞬間: status page (`autonomath.ai/status`)
   に手動で incident を起票し、`service@autonomath.ai` 自動応答に
   "investigating" を一時掲示
4. 24 hr+ ダウン: Cloudflare Pages を maintenance mode に切替, Stripe
   metered billing の usage_record 送信を停止
5. 復旧後 24 hr 以内に postmortem を `docs/_internal/incidents/` に記録

**escalation 先は無い** (solo 構造上)。代わりに **kill-switch** を運用:

- `docs/_internal/launch_kill_switch.md` の手順で全 traffic を Cloudflare
  Pages 静的 fallback に切替 (10 min 以内検証済)
- Stripe 課金停止 (`scripts/cron/stripe_disable_metering.py`、launch
  済み)

---

## 7. SLO レビュー周期

- **月次**: error budget の burn rate を `analytics/` 集計 cron で確認、
  S1-S4 の前月実績を `docs/_internal/slo_log.md` (TBD, launch+30d で
  作成) に追記
- **四半期**: SLA レビュー (`docs/sla.md` §7.2) と同期、target を
  下方/上方修正、または SLO 本数を見直す。**SLO は最大 4 本** の制約は
  維持 — 増やす場合は別の SLO を retire
- **年次**: launch+12mo に dual SLA (99.0%) → 単一 SLA (99.5%) 統合を
  検討

---

## 8. 関連 doc

- `docs/sla.md` — 公開、契約上の保証 (99.0%)
- `docs/observability.md` — Sentry / Fly metrics / alert routing
- `docs/_internal/observability_dashboard.md` — Grafana 12 panel layout
- `docs/_internal/incident_runbook.md` — §(a)-(f) 障害対応手順
- `docs/_internal/operator_absence_runbook.md` — solo の不在時 fallback
- `docs/disaster_recovery.md` — RPO/RTO 運用詳細
