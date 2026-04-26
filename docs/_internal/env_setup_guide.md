# Environment Setup Guide (Operator-Only)

このファイルは operator (info@bookyou.net) 専用の env var 設定ガイドです。
mkdocs build からは exclude 済み。値は秘匿 (実値は 1Password に保管)。

- 想定: Fly.io Tokyo + Cloudflare Pages + Stripe metered
- 目的: 新規環境 (prod / staging / local) を 30 分で立ち上げる
- 値の出所: 1Password vault `Bookyou/AutonoMath` の以下 reference を参照
- 本ファイルには実値を絶対に記載しない (Git history に残るため)

---

## 必須 env var 一覧

### A. インボイス / 請求

| key | 用途 | 取得方法 / 1Password ref |
| --- | --- | --- |
| `INVOICE_REGISTRATION_NUMBER` | 適格請求書発行事業者番号 | 1P: `op://Bookyou/AutonoMath/invoice_registration_number` (固定値: `T8010001213708`、ただし参照経由で取得すること) |
| `INVOICE_FOOTER_JA` | 請求書 PDF 末尾の法人情報 | 1P: `op://Bookyou/AutonoMath/invoice_footer_ja` |
| `INVOICE_REGISTRATION_DATE` | 登録日 (令和7年5月12日) | 1P: `op://Bookyou/AutonoMath/invoice_registration_date` |

### B. Stripe (課金)

| key | 用途 | 取得方法 / 1Password ref |
| --- | --- | --- |
| `STRIPE_SECRET_KEY` | Stripe Secret API key | 1P: `op://Bookyou/AutonoMath/stripe_secret_key_live` (prod) / `..._test` (staging) |
| `STRIPE_PUBLISHABLE_KEY` | Stripe Publishable key | 1P: `op://Bookyou/AutonoMath/stripe_publishable_key_live` |
| `STRIPE_WEBHOOK_SECRET` | webhook 署名検証 secret | 1P: `op://Bookyou/AutonoMath/stripe_webhook_secret_live` |
| `STRIPE_PRICE_PER_REQUEST` | metered Price ID (¥3/req, 税込¥3.30) | 1P: `op://Bookyou/AutonoMath/stripe_price_per_request_live` |
| `STRIPE_METER_ID` | usage meter ID | 1P: `op://Bookyou/AutonoMath/stripe_meter_id_live` |

### C. 監視 / 観測

| key | 用途 | 取得方法 / 1Password ref |
| --- | --- | --- |
| `SENTRY_DSN` | Sentry エラー収集 | 1P: `op://Bookyou/AutonoMath/sentry_dsn_prod` |
| `SENTRY_ENVIRONMENT` | environment tag | `production` / `staging` / `local` |
| `LOG_LEVEL` | アプリ log level | `INFO` (prod) / `DEBUG` (local) |

### D. セキュリティ / Hash

| key | 用途 | 取得方法 / 1Password ref |
| --- | --- | --- |
| `PEPPER` | API key SHA-256 用 secret | 1P: `op://Bookyou/AutonoMath/pepper_v1` (rotation 時は v2, v3 と並行保持) |
| `PEPPER_PREVIOUS` | rotation 中の旧 PEPPER | 1P: `op://Bookyou/AutonoMath/pepper_previous` (rotation 終了後に空) |
| `SESSION_SECRET` | dashboard session 署名 | 1P: `op://Bookyou/AutonoMath/session_secret` |

### E. データソース / DB

| key | 用途 | 取得方法 / 1Password ref |
| --- | --- | --- |
| `JPINTEL_DB_PATH` | jpintel.db のパス | `data/jpintel.db` (固定) |
| `AUTONOMATH_DB_PATH` | autonomath.db のパス | `autonomath.db` (固定) |
| `AUTONOMATH_ENABLED` | 17 autonomath tools の有効化 | `true` (prod) |
| `S3_BACKUP_BUCKET` | DB 自動 backup 先 | 1P: `op://Bookyou/AutonoMath/s3_backup_bucket` |
| `S3_BACKUP_ACCESS_KEY` | S3 IAM key | 1P: `op://Bookyou/AutonoMath/s3_backup_access_key` |
| `S3_BACKUP_SECRET_KEY` | S3 IAM secret | 1P: `op://Bookyou/AutonoMath/s3_backup_secret_key` |

### F. メール (transactional)

| key | 用途 | 取得方法 / 1Password ref |
| --- | --- | --- |
| `EMAIL_PROVIDER_API_KEY` | Resend / Postmark 等の API key | 1P: `op://Bookyou/AutonoMath/email_provider_api_key` |
| `EMAIL_FROM_ADDRESS` | 差出人アドレス | `info@bookyou.net` (固定) |
| `EMAIL_BCC_OPS` | 運用 bcc | `info@bookyou.net` (固定) |

### G. Fly.io / deploy

| key | 用途 | 取得方法 |
| --- | --- | --- |
| `FLY_API_TOKEN` | deploy 用 token | `flyctl auth token` で取得後 1P 保存 |
| `FLY_APP_NAME` | アプリ名 | `autonomath-api-tokyo` (固定) |
| `CLOUDFLARE_API_TOKEN` | Pages deploy 用 | 1P: `op://Bookyou/AutonoMath/cloudflare_api_token` |

---

## 設定方法

### 1Password CLI からの読み出し

事前に `op signin` 済みであること。

```bash
# 単発で env を埋める (ログイン中の shell に export)
eval "$(op inject -i .env.template -o /dev/stdout 2>/dev/null | grep -v '^#')"

# または run-time で環境変数を inject (推奨。値はプロセスに残らず)
op run --env-file=.env.template -- .venv/bin/uvicorn jpintel_mcp.api.main:app
```

`.env.template` の例 (この template はリポジトリにコミット可、実値なし):

```
INVOICE_REGISTRATION_NUMBER=op://Bookyou/AutonoMath/invoice_registration_number
STRIPE_SECRET_KEY=op://Bookyou/AutonoMath/stripe_secret_key_live
PEPPER=op://Bookyou/AutonoMath/pepper_v1
SENTRY_DSN=op://Bookyou/AutonoMath/sentry_dsn_prod
EMAIL_PROVIDER_API_KEY=op://Bookyou/AutonoMath/email_provider_api_key
```

### Fly.io への secret 登録

```bash
# 1Password reference を解決して fly secrets に流し込む
op run --env-file=.env.template -- bash -c '
  flyctl secrets set \
    INVOICE_REGISTRATION_NUMBER="$INVOICE_REGISTRATION_NUMBER" \
    STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY" \
    STRIPE_WEBHOOK_SECRET="$STRIPE_WEBHOOK_SECRET" \
    STRIPE_PRICE_PER_REQUEST="$STRIPE_PRICE_PER_REQUEST" \
    PEPPER="$PEPPER" \
    SENTRY_DSN="$SENTRY_DSN" \
    EMAIL_PROVIDER_API_KEY="$EMAIL_PROVIDER_API_KEY" \
    --app autonomath-api-tokyo
'
```

### Cloudflare Pages への env 登録

Pages の env は Cloudflare dashboard か `wrangler` 経由で設定。
secret 系 (Stripe key 等) は Pages には流さない (Pages は静的サイト
配信のみ。API は Fly.io 側で受ける構成)。

---

## 設定検証

### 起動前の存在チェック

```bash
.venv/bin/python -c '
import os, sys
required = [
    "INVOICE_REGISTRATION_NUMBER",
    "INVOICE_FOOTER_JA",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_PER_REQUEST",
    "PEPPER",
    "SENTRY_DSN",
    "EMAIL_PROVIDER_API_KEY",
]
missing = [k for k in required if not os.getenv(k)]
if missing:
    print("MISSING:", missing); sys.exit(1)
print("OK: all required env vars set")
'
```

### Stripe 接続テスト

```bash
.venv/bin/python -c '
import os, stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
price = stripe.Price.retrieve(os.environ["STRIPE_PRICE_PER_REQUEST"])
print("Price OK:", price.id, price.unit_amount, price.currency)
'
```

期待出力例:

```
Price OK: price_XXX 3 jpy
```

(unit_amount は ¥3 → 整数 3。consumption tax は別途 Stripe 側で
税込 ¥3.30 として計上されます)

### Sentry 接続テスト

```bash
.venv/bin/python -c '
import os, sentry_sdk
sentry_sdk.init(dsn=os.environ["SENTRY_DSN"])
sentry_sdk.capture_message("env_setup_verification ping", level="info")
print("Sentry ping sent")
'
```

Sentry dashboard の Issues に `env_setup_verification ping` が
1-2 分以内に到着すれば OK。

### PEPPER 連続性チェック (rotation 中)

```bash
.venv/bin/python -c '
import os, hashlib
key_sample = "test-key-do-not-store"
new_hash = hashlib.sha256((key_sample + os.environ["PEPPER"]).encode()).hexdigest()
prev = os.getenv("PEPPER_PREVIOUS")
if prev:
    old_hash = hashlib.sha256((key_sample + prev).encode()).hexdigest()
    print("dual-verify mode: new=", new_hash[:8], "prev=", old_hash[:8])
else:
    print("single-pepper mode: new=", new_hash[:8])
'
```

### DB 連続性チェック

```bash
sqlite3 data/jpintel.db "SELECT COUNT(*) FROM programs WHERE excluded=0;"
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_entities;"
```

期待値の目安: programs.excluded=0 が 11,000 以上、am_entities が
410,000 以上 (CLAUDE.md の記載値が baseline)。

---

## 取扱注意

- 本 guide に登場する key 名と reference path のみが公開可能情報
- 実値は 1Password 以外に書き出さない (env file ローカル保存禁止)
- `git status` で `.env` がトラッキング対象に入っていないことを必ず確認
- PEPPER は rotate 中の dual-verify 期間 (24 時間) を経て切替
- Stripe live key と test key は混用しない (price ID も別)

不明点は info@bookyou.net まで。
