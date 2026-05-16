# Wave 49 G1 RUM Beacon Production Activation — Operator Runbook

Status: OPEN (drafted 2026-05-16, Wave 50 tick#9 Stream DD)
Author: Claude (Stream DD)
Scope: Cloudflare Pages Function `/api/rum_beacon` + R2 bucket `jpcite-rum-beacon-funnel` の production 接続を確立し、Wave 49 G1 aggregator の真の流入計測を開始するための **operator-only** 手順書。

---

## § 1. 背景

Wave 50 tick#9 の Stream DD 走査で以下の 2 gap が発覚:

1. **Pages Function 未 bind**: `https://jpcite.com/api/rum_beacon` への POST が 404 を返す。`functions/api/rum_beacon.ts` は repo に landed (Stream S 完了) しているが、Cloudflare Pages dashboard 上で routes に bind されていないため production に exposed されていない。
2. **R2 secret 不在**: `.env.local` (canonical secrets store, memory `reference_secrets_store`) と GHA secret 双方に `R2_ENDPOINT` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` が未設定。`.github/workflows/organic-funnel-daily.yml` は secret 不在で aggregator が `boto3.exceptions.NoCredentialsError` を投げる。

Stream S で aggregator (`scripts/cron/aggregate_organic_funnel_daily.py`) + GHA workflow (`.github/workflows/organic-funnel-daily.yml`) + dashboard + alert は完成済み (Wave 50 tick#6 着地)。本 runbook は production 接続のみを残務として closure する。

Wave 49 G1 成功基準: **organic funnel uniq_visitor >= 10 が UTC 日付ベースで 3 連続日**。本 runbook 着地後、daily cron が 04:30 JST に R2 → aggregator → state file の 3 段 rollup を実行し、3 連続日達成時に GitHub Issue が自動起票される。

---

## § 2. Step 1 — Cloudflare Pages Function bind 確認 + 必要なら再 deploy

### 2.1 Dashboard で routes 確認

URL: <https://dash.cloudflare.com/> → 該当アカウント → Workers & Pages → Pages → jpcite-site (project 名) → Settings → Functions → Routes

確認項目:

- `/api/rum_beacon` が routes 一覧に含まれているか
- もし含まれていなければ Pages Function が **deploy されていない**

### 2.2 deploy 状況確認 + 再 deploy

```bash
cd /Users/shigetoumeda/jpcite
ls functions/api/rum_beacon.ts  # 存在確認 (landed)
npx wrangler pages deployment list --project-name jpcite-site | head -5
```

最新 deployment が `rum_beacon.ts` landed commit (Stream S 完了 commit) を含むかを確認。含まなければ:

```bash
npx wrangler pages deploy site/ --project-name jpcite-site --branch main
```

deploy 完了後 5 分待ち、再度 dashboard routes に `/api/rum_beacon` が登場するか確認。

---

## § 3. Step 2 — R2 bucket 作成 + secret 設定

### 3.1 R2 bucket 作成

URL: <https://dash.cloudflare.com/> → 該当アカウント → R2 → Create bucket

- Bucket name: `jpcite-rum-beacon-funnel`
- Location hint: `Asia-Pacific (APAC)` (Tokyo 寄せ、Fly nrt と整合)
- Default encryption: 標準 (AES-256)

### 3.2 R2 API token 発行

R2 dashboard → Manage R2 API Tokens → Create API Token

- Token name: `jpcite-rum-beacon-funnel-rw`
- Permissions: **Object Read & Write**
- Specify bucket(s): `jpcite-rum-beacon-funnel` のみ
- TTL: なし (運用上 rotate は別途)

発行後の `Access Key ID` + `Secret Access Key` + `S3-compatible endpoint` を控える。**この時点で `.env.local` を Read してから secret 登録に進む** (memory `reference_secrets_store` 準拠)。

### 3.3 GHA secret 設定

```bash
gh secret set R2_ENDPOINT --body "https://<account>.r2.cloudflarestorage.com" --repo bookyou/jpcite
gh secret set R2_ACCESS_KEY_ID --body "<id>" --repo bookyou/jpcite
gh secret set R2_SECRET_ACCESS_KEY --body "<secret>" --repo bookyou/jpcite
gh secret set R2_BUCKET --body "jpcite-rum-beacon-funnel" --repo bookyou/jpcite
```

**注意**: `gh secret set --body 'string'` を直接渡す形式を使う (memory `feedback_gh_secret_set_stdin` 準拠 — stdin 経由は trailing newline で Bearer\n injection 不正)。

### 3.4 `.env.local` 同期

```bash
cd /Users/shigetoumeda/jpcite
# Read で現在の内容確認後、以下 4 keys を append (重複なきよう)
# R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com
# R2_ACCESS_KEY_ID=<id>
# R2_SECRET_ACCESS_KEY=<secret>
# R2_BUCKET=jpcite-rum-beacon-funnel
chmod 600 .env.local
```

`.env.local` は git-ignored (canonical secrets SOT、memory `reference_secrets_store`)。Fly secret 側にも同 4 keys を mirror (memory `feedback_secret_store_separation`):

```bash
flyctl secrets set \
  R2_ENDPOINT="https://<account>.r2.cloudflarestorage.com" \
  R2_ACCESS_KEY_ID="<id>" \
  R2_SECRET_ACCESS_KEY="<secret>" \
  R2_BUCKET="jpcite-rum-beacon-funnel" \
  --app jpcite-api
```

---

## § 4. Step 3 — Production smoke

### 4.1 endpoint POST smoke

```bash
curl -X POST https://jpcite.com/api/rum_beacon \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"smoke-1","page":"/","step":"landing","event":"view","ts":1715900000000}' \
  -i
```

期待: `HTTP/2 204` + `access-control-allow-origin: https://jpcite.com` ヘッダ。404 / 500 / 403 はすべて失敗扱い (§ 7 troubleshooting 参照)。

### 4.2 R2 書き込み確認

```bash
npx wrangler r2 object list jpcite-rum-beacon-funnel --prefix funnel/2026-05-16/
```

期待: `funnel/2026-05-16/smoke-1-1715900000000.json` 相当の 1 object listed。

---

## § 5. Step 4 — Aggregator first run (dry-run)

```bash
gh workflow run organic-funnel-daily.yml -F dry_run=true --repo bookyou/jpcite
gh run watch --repo bookyou/jpcite
```

期待出力:

- workflow run status: `completed success`
- step `Run organic funnel aggregator` の stdout に `funnel rollup` 行
- `analytics/organic_funnel_daily.jsonl` + `site/status/organic_funnel_state.json` は dry-run なので **commit されない** (workflow `if: inputs.dry_run != 'true'` で guard)
- ローカル fetch で artifact があれば内容確認 (任意)

---

## § 6. Step 5 — Aggregator first run (live)

```bash
gh workflow run organic-funnel-daily.yml -F dry_run=false --repo bookyou/jpcite
gh run watch --repo bookyou/jpcite
```

期待:

- `git pull origin main` で `analytics/organic_funnel_daily.jsonl` (append 1 row) + `site/status/organic_funnel_state.json` の commit 着地
- 翌日 04:30 JST (19:30 UTC) に GHA scheduled run が自動開始

---

## § 7. Step 6 — 3 連続 uniq>=10 観測待機

### 7.1 日次確認

```bash
cd /Users/shigetoumeda/jpcite
git pull origin main
cat site/status/organic_funnel_state.json | jq .g1_state
```

期待 (3 連続未達時):

```json
{
  "achieved": false,
  "consecutive_days": 0|1|2,
  "last_uniq_visitor": <int>,
  "threshold": 10
}
```

### 7.2 達成時の挙動

3 連続日 `uniq_visitor >= 10` 達成時、workflow の "Detect G1 achievement transition" step が `::organic-funnel-g1-achieved::` stdout marker を検出し、"Open G1 achievement Issue" step が `gh issue create` を実行 (label: `wave49`, `organic-funnel`)。Issue title は **"Wave 49 G1 達成: organic funnel uniq>=10 が 3 日連続"**。

---

## § 8. Troubleshooting

### 8.1 `/api/rum_beacon` が 404

- `wrangler pages deploy site/ --project-name jpcite-site` を再実行
- dashboard → Functions → Routes に `/api/rum_beacon` が登場するまで 2-5 分待機
- それでも 404 なら `functions/_routes.json` に `"/api/*"` の include 行があるか確認

### 8.2 endpoint は 200 だが R2 に object 書き込まれない

- `gh secret list --repo bookyou/jpcite | grep R2_` で 4 keys 全てあるか確認
- 値の typo (endpoint URL の `<account>` placeholder 残り、bucket 名違い) を確認
- Cloudflare Pages Function logs (`wrangler pages deployment tail`) で `R2 binding` エラーを確認

### 8.3 aggregator が 0 row

- Bot UA filter が aggressive すぎる (rum_beacon.ts BOT_RE と aggregate_organic_funnel_daily.py BOT_RE が同期している確認)
- 日付 mismatch: aggregator は UTC 日付 yesterday を default にする (`--date YYYY-MM-DD` で override 可)
- R2 prefix mismatch: aggregator は `funnel/{YYYY-MM-DD}/` を読む (rum_beacon.ts が書く path と一致確認)

---

## § 9. SOT marker + 関連 path

- Wave 49 plan SOT: [WAVE49_plan.md](./WAVE49_plan.md) § 3.1 organic funnel measure / § 4.1 G1 success criterion
- Stream S 完了 SOT: Wave 50 tick#6 (本 CLAUDE.md tick 6-7 completion log § Stream S)
- Stream DD 完了 SOT: 本 runbook + Wave 50 tick#9 completion log
- Pages Function source: `/Users/shigetoumeda/jpcite/functions/api/rum_beacon.ts`
- Aggregator source: `/Users/shigetoumeda/jpcite/scripts/cron/aggregate_organic_funnel_daily.py`
- GHA workflow: `/Users/shigetoumeda/jpcite/.github/workflows/organic-funnel-daily.yml`
- Aggregator output (append-only): `/Users/shigetoumeda/jpcite/analytics/organic_funnel_daily.jsonl`
- 14-day rolling state: `/Users/shigetoumeda/jpcite/site/status/organic_funnel_state.json`
- secrets canonical SOT: `/Users/shigetoumeda/jpcite/.env.local` (chmod 600, git-ignored)
- Fly secret mirror app: `jpcite-api` (Tokyo)
- GHA secret mirror repo: `bookyou/jpcite`

last_updated: 2026-05-16
