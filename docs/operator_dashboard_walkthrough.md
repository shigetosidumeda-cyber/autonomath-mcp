# AutonoMath — Operator Dashboard Walkthrough

**Audience**: 梅田茂利 — solo operator. Companion to `docs/operator_daily.md`.
**Status**: operator-only. Excluded from `mkdocs build` (`exclude_docs` in `mkdocs.yml`).
**Scope**: where to look on the running site / API / Sentry to read each KPI mentioned in the daily / weekly / monthly routines. Does NOT explain how to *change* anything — for that see `docs/_internal/operators_playbook.md`.

The four operator-facing UI surfaces are:

1. `site/dashboard.html` — paid customer dashboard (B3): own usage, ¥ MTD, cap controls
2. `site/stats.html` — public stats page (B8): aggregate API health, dataset counts
3. `site/testimonials.html` — submission + moderation queue (B8)
4. `site/alerts.html` — amendment-alert subscription UI (E5) + Sentry / status page

Plus 2 read-only CLI helpers:

- `scripts/ops_quick_stats.py` — 1-shot operator KPI snapshot
- `scripts/ops_refund_helper.py` — Stripe charge advisory (no auto-action)

---

## 1. dashboard.html (B3) — paid-customer view, operator perspective

URL: `https://autonomath.ai/dashboard.html` (requires API key in `Authorization: Bearer …`).

### 1.1 What operator should look at, daily

| Element | Where | What it tells the operator |
|---------|-------|----------------------------|
| `MTD ¥` 表示 | top card | 当該 customer の今月 ¥使用量 (= MRR per customer の片鱗) |
| `Monthly cap (¥)` | settings panel | customer 自身が設定した cap、null = unlimited |
| `Cap reached banner` | top alert | customer がその月 cap に到達済か (UI で赤帯) |
| `Last 7d call count` chart | usage panel | spike / decay の有形パターン |
| `Revoke key` ボタン | settings panel | customer が key を自己 revoke したかの監査 |

### 1.2 Daily 朝 routine 連携

`scripts/ops_quick_stats.py` の `Cap usage:` 行で **cap-reached** 数が増えていたら、当該 customer の dashboard.html を **代理ログインで開かない** (zero-touch 原則 + APPI 配慮)。代わりに:

```bash
sqlite3 data/jpintel.db "SELECT customer_id, tier, monthly_cap_yen, last_used_at FROM api_keys WHERE customer_id='cus_XXXX';"
```

で確認する。dashboard.html を operator が開くのは「customer に同意取得済の screenshare 中」のみ。

### 1.3 Known gotcha

dashboard.html の MTD 表示は frontend で `usage_events` の集計を走らせる。**timezone は JST で集計**しているが、`api_keys` の認証 customer (paid tier) は **UTC リセット** (memory: rate limit reset timezones differ)。dashboard 表示と請求書の月境界が JST/UTC でずれるため、月跨ぎ 1 日は問い合わせが来やすい。月初第1営業日 routine の中で必ず check。

---

## 2. stats.html (B8) — public stats, operator として何を読むか

URL: `https://autonomath.ai/stats.html` (anonymous OK).

### 2.1 公開している指標

- 総 program 件数 (tier breakdown, excluded=0 のみ)
- 採択事例 / 融資 / 行政処分 件数
- last_ingest_at (最終 ingest 時刻、UTC)
- API uptime (直近 30d / 90d、Cloudflare Worker 計測)

### 2.2 Operator が見るべき変化

朝 routine で 5 秒だけ:

1. **last_ingest_at** が 24h 以内 か → 24h 超なら ingest cron 死亡疑い、`scripts/cron/ingest.sh` の Fly schedule 確認
2. **total_programs** が前日比 ±5% 超 → bulk delete / bulk insert 事故疑い、即 invariant runner
3. **uptime 30d** が 99.5% 以下 → DR drill 後ろ倒し検討、SLO 違反は `docs/sla.md` に従い customer 通知

### 2.3 内部値は出さない

stats.html には MAU / MRR / dispute は **出さない** (zero-touch 原則 + 競合に手の内見せない)。それらは `scripts/ops_quick_stats.py` のみで operator 自身が確認する。

---

## 3. testimonials.html (B8) — submission + moderation

URL: `https://autonomath.ai/testimonials.html`.

### 3.1 公開ビュー

- approve 済の testimonial 一覧 (匿名 / 顔出し は customer 選択)
- submission form (customer が自由記入、moderation queue 経由で公開)

### 3.2 Operator moderation queue

- admin link: `https://autonomath.ai/testimonials.html?admin=<OPS_ADMIN_TOKEN>` (env var で持つ、URL に直接埋めない)
- queue 表示 = pending / rejected / approved の 3 タブ
- pending タブで:
  - 虚偽 (採択を自社のおかげと書いてあるなど): reject + reason="false claim"
  - 個人情報 (氏名 + 会社名 + 採択額の三点セット等で identifiable): reject + reason="PII"
  - 攻撃的 / 政治 / スパム: reject + reason="spam/abuse"
  - それ以外: approve、ただし日次 max 5 件 (operator_daily §2.1)

### 3.3 削除 (APPI 対応)

approve 済 testimonial の取り下げ希望が来たら `_internal/operators_playbook.md` §6 (GDPR/APPI) 手順で `research/data_deletion_log.md` に記録 + DB から削除。dashboard / stats から消えるのは数分の Cloudflare cache 越えが必要。

---

## 4. alerts UI (E5) — amendment alert subscription + Sentry / status

### 4.1 site/alerts.html

公開 UI。customer 視点:

- 法令 / 制度の amendment が起きた時に webhook / email で通知購読
- subscription 一覧 / pause / resume / unsubscribe (alerts-unsubscribe.html)
- 詳細仕様: `docs/alerts_guide.md`

operator 視点で見る場所:

| 指標 | source | check timing |
|------|--------|-------------|
| 購読件数 (`alert_subscriptions` 行数) | `sqlite3 data/jpintel.db` | 週次 |
| webhook 配信失敗率 | Sentry breadcrumb `alerts.deliver` tag | 朝 routine で error 件数だけ |
| amendment cron 死活 | `scripts/cron/alerts.sh` の Fly schedule + Sentry | 朝 routine |

### 4.2 Sentry (operator の incident UI)

URL: Sentry dashboard, project `autonomath-prod` (env `SENTRY_DSN`).

朝 routine で見る fixed view:

- **Issues → Unresolved → level:fatal** (常に 0 が ideal)
- **Issues → Unresolved → level:error → last 12h** (件数のみ)
- **Performance → /v1/programs** p95 latency (SLO 800ms 以下)
- **Releases** タブで最新 release sha が prod = git HEAD と一致

`SENTRY_RELEASE` env を Fly secret 経由で deploy 時に注入しているので、release 不一致は deploy 失敗のシグナル。

### 4.3 status.html (cloudflare worker)

URL: `https://status.autonomath.ai` (= `site/status.html` を Cloudflare Worker で expose)。

operator が手動更新する surface。incident 中 5 分以内に:

1. `site/status.html` を編集 (incident summary + 開始時刻 UTC)
2. push → Cloudflare Pages auto-deploy
3. 解消後に「resolved at <time>」追記して再 push

スケジュール stale 化を防ぐため、**月次 ritual で必ず 1 回 status.html を `Last 30d incidents: none` 等に refresh** (incident なしでも mtime 更新)。

---

## 5. CLI helpers — UI ではないが daily で使う

### 5.1 scripts/ops_quick_stats.py

朝 / 夕で 1 発打つ snapshot tool。read-only。

```bash
.venv/bin/python scripts/ops_quick_stats.py
```

出力例:

```
=== AutonoMath ops quick stats (2026-05-06) ===
MAU: 234 (anon 198 + paid 36)
MRR (current month): ¥47,250
¥/customer avg: ¥1,313
Cap usage: 12 customers cap-set, 3 cap-reached
Sentry: 0 unresolved critical / 2 resolved
Stripe: 1 dispute in pending (¥3,510)
=== End ===
```

注意: Sentry / Stripe 行は **DB cache を読むだけ**で、API は叩かない (memory `feedback_autonomath_no_api_use` 派生 — 自前運用 script でも外部 API 呼出は禁忌)。Sentry / Stripe 値は dashboard 目視で別途確認する前提で、cache が無い場合は `(unconfigured — see Sentry dashboard)` 等を表示する。

### 5.2 scripts/ops_refund_helper.py

refund 候補の Stripe charge を 1 件指定すると、過去 dispute / 使用量 / 推奨アクション (full / partial / deny) を表示する advisory tool。

```bash
.venv/bin/python scripts/ops_refund_helper.py ch_3PXXXXXX
```

**自動 refund はしない**。出力された Stripe Dashboard URL を operator が手動で開いて、目視で refund 実行する。

---

## 6. 1 ページまとめ (朝 routine 連携 cheat sheet)

```
朝 (15 min):
  1. ops_quick_stats.py 1 発         -> cap-reached delta
  2. Sentry "Unresolved fatal"       -> 0 件確認
  3. stats.html last_ingest_at       -> 24h 以内
  -> 朝 routine done

夕 (15 min):
  1. ops_quick_stats.py 1 発         -> 数値を ops_log に
  2. 翌日 plan 1-3 行                 -> commit
  -> 夕 routine done
```

dashboard.html / testimonials.html / alerts.html を毎日見る必要は無い。週次以降の cadence で十分。
