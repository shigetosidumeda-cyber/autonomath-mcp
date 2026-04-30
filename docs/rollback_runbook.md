# jpcite — Rollback Runbook (operator-only)

> **operator-only**: launch 直後 30 分の即時監視 + rollback 手順。`mkdocs.yml::exclude_docs` で公開除外。
>
> Launch day: **2026-05-06 (水) JST** · 適用範囲: T+0 〜 T+1d (それ以降は `disaster_recovery.md`)
>
> Owner: **梅田茂利** / info@bookyou.net / Bookyou株式会社 (T8010001213708)

最終更新: 2026-04-25 · 関連 doc: `launch_checklist.md` (時系列), `go_no_go_gate.md` (判定), `disaster_recovery.md` (wider DR), `_internal/incident_runbook.md` (minute-by-minute)

---

## 0. 本 doc と `disaster_recovery.md` の使い分け

| 場面 | 使う doc |
|---|---|
| **launch 後 30 分以内** の異常検知 + 即 revert | **本 doc (rollback_runbook.md)** |
| launch 後 24h-30d の障害 (Scenario 1-9) | `disaster_recovery.md` |
| operator 不在 (Scenario 10) | `solo_ops_handoff.md` |
| 1 分単位の commands リスト | `_internal/incident_runbook.md` |

本 doc は **launch 直後の "とりあえず元に戻す" 用**。深い analysis は後回しにし、まず traffic を直前 build に戻すことを最優先する。

---

## 1. Launch 後 30 分の key metric

T+0 の各投稿時刻 (X 09:00 / mail 10:00 / HN 20:00) **直後 30 分** に集中監視する 5 metric。

### 1.1 監視ダッシュボード

| metric | source | 正常域 | 警告域 | 即時 rollback 域 |
|---|---|---|---|---|
| **5xx error rate** | Sentry / Fly metrics | < 0.5% | 0.5-2% | **≥ 2% (15 min window)** |
| **P95 latency** (`/v1/programs/search`) | Fly metrics | < 800 ms | 800-1500 ms | **≥ 1500 ms (5 min window)** |
| **Sentry 新規 issue volume** | Sentry web UI | < 5 / hour | 5-20 / hour | **> 20 / hour** |
| **Stripe webhook fail** | Stripe dashboard | 0 件 | 1-3 件 | **≥ 4 件 / 15 min** |
| **Fly machine count** | `flyctl status` | n_target | < n_target | **0 (full down)** |

### 1.2 監視コマンド (毎 5 分実行 = 6 回 / 30 min)

```bash
# 5xx + Fly machine
flyctl status --app autonomath-api
flyctl logs --app autonomath-api --region nrt | tail -100 | grep -E "^[5][0-9][0-9] " | wc -l

# Stripe webhook
# → Stripe Dashboard → Developers → Webhooks → endpoint health

# Sentry issue volume
# → https://bookyou.sentry.io/issues/?project=autonomath-api&statsPeriod=1h

# Smoke (毎 5 分)
BASE_URL=https://api.jpcite.com ./scripts/smoke_test.sh
curl -sI https://api.jpcite.com/healthz
curl -sI https://jpcite.com/
```

### 1.3 ログ集約先

- **Fly logs**: `flyctl logs --app autonomath-api --region nrt` (real-time)
- **Sentry**: web UI at `https://bookyou.sentry.io/issues/?project=autonomath-api`
- **Cloudflare Pages**: dashboard → Pages → autonomath → Deployments
- **Stripe events**: dashboard → Developers → Events
- **R2 backup status**: `aws s3 ls s3://autonomath-backups/jpintel.db/ --endpoint-url $R2_ENDPOINT | tail -3`
- **本 launch incident log**: `docs/_internal/dr_drill_log.md` の launch 当日 entry に書き足す

---

## 2. 5xx 増加の判定フロー

```
5xx rate を 5 分ごとに計測
    │
    ├─ < 0.5%               → 通常運用、wake-up routine 継続
    ├─ 0.5-2% (15 min 持続)  → §3 `5xx 軽度上昇 流れ` へ
    └─ ≥ 2% (15 min window) → §4 `即 rollback 流れ` へ
```

### 2.1 5xx 計測

`Fly metrics` ダッシュボードの `fly_app_http_response_time_seconds_bucket{path,status}` を 15 min window で集計。手計算用フォールバック:

```bash
# 直近 1000 行のうち 5xx の割合
flyctl logs --app autonomath-api --region nrt -n 1000 \
  | grep -oE '"status": [0-9]+' | sort | uniq -c
# (200 / 4xx / 5xx の分布が出る → 5xx ÷ total)
```

### 2.2 ログ場所の優先順位

5xx の根本原因を特定する優先順:

1. **Fly logs** (`flyctl logs --region nrt`) — uvicorn の traceback がここに出る
2. **Sentry issue** — 新規 issue が前面に出るので click → traceback / breadcrumb 確認
3. **`/data/jpintel.db` の `request_log` table** — 該当時刻の request 履歴 (response code 含む) が SQLite に追記されている
4. **Stripe events** — billing 系 5xx は Stripe webhook 起源の可能性

### 2.3 一過性 vs 構造的の判定

- 5xx が **1 IP 起源 + ratelimit** → 一過性 (放置で 5 分で消える)
- 5xx が **複数 IP 起源 + 同一 endpoint** → **構造的 → §4 rollback**
- 5xx が **`/v1/billing/*` のみ** → Stripe outage の可能性 → `disaster_recovery.md::Scenario 4`

---

## 3. 5xx 軽度上昇 (0.5-2%) の流れ — rollback せず観察

### Step 1. 観察期間の延長

- 5 分 → 15 分 → 30 分の窓で持続するか確認
- 30 分連続で 0.5-2% に留まる場合は §4 (rollback) へ昇格

### Step 2. 即時 mitigation

- 該当 endpoint の rate limit を一時的に下げる: `flyctl secrets set ANON_RATE_LIMIT=20 --app autonomath-api` (default 50/月 → 20/月)
- 大量の同一 query の場合: `response_cache` table の TTL を延長 (`scripts/extend_cache_ttl.py`)
- Sentry issue を `Resolve` せず `Investigating` に flag

### Step 3. 投稿経路へのアナウンス

- `https://status.jpcite.com/` (Cloudflare Worker、`site/status.html` 編集) に「監視中」のお知らせを 5 分以内に表示
- X や HN の reply には「監視中、現状 service は継続稼働」のスタンスで応答 (false reassurance しない)

---

## 4. 即 rollback (5xx ≥ 2% / Sentry 新規 > 20 / latency ≥ 1500ms / machine 0)

### 4.1 Fly machine 前バージョンへ revert

```bash
# 1. 直前 release の id を確認
flyctl releases list --app autonomath-api | head -5

# 2. 直前 release に rollback
flyctl releases rollback <prev-release-id> --app autonomath-api

# 3. status 確認
flyctl status --app autonomath-api
flyctl checks list --app autonomath-api

# 4. smoke 再走
BASE_URL=https://api.jpcite.com ./scripts/smoke_test.sh
```

**目安所要時間**: 90 秒 〜 3 分 (Fly auto-restart 込み)。

#### Fly primary machine entrypoint 注意

A2 agent の指摘 (primary machine entrypoint 問題) の通り、`fly.toml::[processes]` で複数 process group がある場合は **primary process** (= `app` group) のみ rollback すれば十分。`worker` group は影響範囲が異なる場合があるので個別判断:

```bash
flyctl status --app autonomath-api --json | jq '.Machines[] | {id, state, processGroup: .config.processes}'
```

`processGroup == "app"` のみ release 単位で revert。`worker` 系は手動で `flyctl machine restart <id>` でも可。

### 4.2 Stripe price revert

新 release で `STRIPE_PRICE_PER_REQUEST` を変更していた場合、価格 ID も旧値に戻す:

```bash
# 旧 price ID は 1Password "Stripe Price ID per_request_v1 (old)" に保管
flyctl secrets set STRIPE_PRICE_PER_REQUEST=<old-price-id> --app autonomath-api

# 注意: live mode の Stripe Price は archive せず両方残す。新 price で active subscription があるなら proration を Stripe 側で処理。
```

billing は **immutable principle** に従い「旧 price 復活」ではなく「新 price をフリーズ + 旧 price を新規 default に切替」が安全。

### 4.3 Cloudflare Pages rollback

site (jpcite.com) 側で landing copy / docs に異常がある場合:

```bash
# Cloudflare dashboard → Pages → autonomath → Deployments
# → 直前の Production deployment を選択 → "Rollback to this deployment" click
```

CLI 派は `wrangler pages deployment list --project-name=autonomath` で deployment id を確認後、dashboard で 1 click rollback。

### 4.4 Smoke test 再走 + アナウンス

- `BASE_URL=https://api.jpcite.com ./scripts/smoke_test.sh` PASS 確認
- `curl -s https://api.jpcite.com/meta` で `build_sha` が **旧** SHA に戻ったことを確認
- `https://status.jpcite.com/` に「障害復旧」を 10 分以内に表示
- X / HN comment に「rollback 完了、root cause 調査中、postmortem は 24h 以内」を投稿
- 影響顧客がいれば `solo_ops_handoff.md::§14` の outage email template 送信

---

## 5. Data corruption (`/data/jpintel.db` malformed) → R2 backup restore

`disaster_recovery.md::Scenario 2` の launch 直後抜粋。**A2 agent が指摘した primary machine entrypoint 問題** との整合のため、scale 0 → restore → scale 1 の順で実施する。

### 5.1 検出

- Sentry に `sqlite3.DatabaseError: database disk image is malformed` が出る
- `/meta` endpoint が 500 を返す
- cron `PRAGMA integrity_check` (起動時実行) が fail

### 5.2 復旧手順 (launch 当日緊急版)

```bash
# 1. 書き込み停止 (primary process group のみ scale 0)
#    process group が単一の場合、これで全停止になる
flyctl scale count 0 --app autonomath-api --process-group app

# 2. 現 volume id を控える
flyctl volumes list --app autonomath-api

# 3. R2 から最新 snapshot を pull (必ず SHA 検証)
aws s3 cp s3://autonomath-backups/jpintel.db/<latest-YYYY-MM-DD>.db.gz . \
  --endpoint-url $R2_ENDPOINT
aws s3 cp s3://autonomath-backups/jpintel.db/<latest-YYYY-MM-DD>.db.gz.sha256 . \
  --endpoint-url $R2_ENDPOINT
shasum -a 256 -c <latest-YYYY-MM-DD>.db.gz.sha256
# → "OK" 出力必須

# 4. 解凍 + Fly volume へ SFTP (新 volume を作る pattern が安全)
gunzip <latest-YYYY-MM-DD>.db.gz
flyctl volumes create data --size 25 --region nrt --app autonomath-api
flyctl ssh sftp put <latest-YYYY-MM-DD>.db /data/jpintel.db --app autonomath-api

# 5. machine 再起動
flyctl scale count 1 --app autonomath-api --process-group app

# 6. integrity 再確認
flyctl ssh console -a autonomath-api -C \
  'sqlite3 /data/jpintel.db "PRAGMA integrity_check;"'
# → "ok" 必須

# 7. /meta 数値確認
curl -s https://api.jpcite.com/meta | jq '.total_programs'
# → 13,578 程度 (前日比 ±1% 以内)
```

**目安所要時間**: 25-40 min (R2 download 5-10 min + SFTP upload 5 min + 起動 + verify)。

### 5.3 RPO 確認

R2 nightly snapshot は 04:00 JST = launch 当日 09:00 JST 投稿の場合、最大 **5 時間分の write 損失**。launch 当日に登録された API key / subscriber は失われる可能性があるため、復旧後に Stripe events から最近の checkout を re-replay:

```bash
.venv/bin/python scripts/replay_stripe_usage.py --since "2026-05-06T04:00:00Z"
```

`stripe_usage_queue` table から欠落分を補完。Stripe webhook は 3 日間自動再送するので、Stripe 側起源のデータは 3 日以内に自然回復。

### 5.4 autonomath.db corruption

`autonomath.db` (8.29 GB unified primary) が malformed の場合:

- 復旧優先度は **低** (read-only、新 write なし、launch traffic に直接影響しない部分が多い)
- 即時策: `AUTONOMATH_ENABLED=0` で 28 autonomath tools を一時 disable → MCP は 38 jpintel tools のみで稼働継続
- 後日: `solo_ops_handoff.md::§13` の rebuild 手順 (~6h) で再生成

```bash
flyctl secrets set AUTONOMATH_ENABLED=0 --app autonomath-api
flyctl machine restart <id> --app autonomath-api
```

55 → 38 tools に減るが、core (programs / case / loans / enforcement) は稼働継続。

---

## 6. Rollback 後の post-mortem (T+24h 以内)

`disaster_recovery.md::§4` Template §A を使う:

```
# Post-mortem: launch-rollback-2026-05-06 — <one-line summary>

Date: 2026-05-06
Duration: HH:MM JST → HH:MM JST
Customers affected: <count> / <% of launch day MAU>
RPO observed: <minutes>
RTO observed: <minutes>
SLO impact: <minutes consumed of monthly 21.6-min budget>

## What happened (timeline, JST)
- HH:MM — first symptom (e.g. 5xx > 2%)
- HH:MM — operator detected via Sentry / wake-up routine
- HH:MM — root cause identified
- HH:MM — rollback executed (Fly release X → X-1)
- HH:MM — smoke green, launch traffic restored

## Root cause
<2-3 paragraphs, blameless>

## Action items
- [ ] <runbook update>     / due: T+7d
- [ ] <code fix>            / due: T+14d
- [ ] <invariant test added>/ due: T+30d

## Customer comms
- [x] Status page note posted at HH:MM
- [x] Affected customer email sent at HH:MM (template: solo_ops_handoff.md::§14)
- [ ] Public retrospective blog post by T+30d (if customer-affecting > 1 h)
```

格納場所: `docs/_internal/dr_drill_log.md` の launch 当日 entry に追記。

---

## 7. Rollback 防止のための事前 check (launch 当日朝に再確認)

T+0 の **08:00 JST** に必ず通すリスト (`launch_checklist.md::T+0::08:00 JST` と同期):

- [ ] `flyctl status --app autonomath-api` で全 machine `started`
- [ ] `flyctl releases list --app autonomath-api` で **直前 stable release id** を控える (rollback target)
- [ ] R2 直近 snapshot id + SHA を控える (Scenario 2 復旧用)
- [ ] Stripe `STRIPE_PRICE_PER_REQUEST` の new + old price id を 1Password で確認
- [ ] Cloudflare Pages 直前 deployment id を控える
- [ ] `_internal/incident_runbook.md` を web で開いておく (CLI 操作中の参照用)

これら 6 件は **launch 当日朝の付箋** に書き出して目に入る場所に置く (operator 単独運用、`feedback_zero_touch_solo`)。

---

## 8. Rollback しない判断 (false alarm 抑制)

以下は **rollback しない**:

- 5xx が **特定 1 IP** で発生し ratelimit に乗っている → 仕様通り (anonymous 50/月 超過)
- launch 直後 30 分の **HN traffic burst** で latency 一時上昇 (P95 800-1200 ms) → Fly auto-scale で 5-10 min で正常化
- Sentry に **既存 known issue** の breadcrumb が出るだけ → 新規 issue 件数で判定
- Cloudflare Pages CDN cache miss が一時増 → Cloudflare 側 stabilize で解消

これらで rollback すると **opportunity cost** (launch 失敗) が大きく、復帰判断こそ慎重にする。

---

## 9. 関連 doc

- `launch_checklist.md` — 11 日前から 30 日後までの時系列
- `go_no_go_gate.md` — T-1d の Go/No-Go 判定
- `disaster_recovery.md` — 10 scenarios formal RPO / RTO
- `solo_ops_handoff.md` — Scenario 10 successor / customer outage email template
- `_internal/incident_runbook.md` — 1 分単位 commands
- `observability.md` — Sentry / Fly metrics / Stripe alert rule の internal 設定

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
