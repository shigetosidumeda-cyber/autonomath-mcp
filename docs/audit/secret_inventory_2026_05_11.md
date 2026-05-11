# jpcite GH Secret Inventory + 1-line 取得経路 (2026-05-11)

audit owner: jpcite ops (info@bookyou.net)
scope: `.github/workflows/*.yml` (100 files) で `${{ secrets.* }}` 参照される全 secret
upstream audit: `docs/audit/workflow_cron_state_2026_05_11.md`

## 0. Headline

| 指標 | 値 |
| --- | --- |
| workflow yml で参照される secret 名 (unique) | **41** |
| GH repo に設定済 | **8** |
| GITHUB_TOKEN (GHA 自動付与、設定不要) | 1 |
| **真未設定** | **33** |
| HIGH (workflow 直接 fail) | 9 |
| MEDIUM (部分機能 fail / fallback path 有) | 12 |
| LOW (warning-only path / dispatch-only) | 12 |
| 即実行 cmd 数 (`/tmp/jpcite_secret_setup.sh`) | **33** |

## 1. 設定済 (8 種)

```
CF_ACCOUNT_ID                       2026-05-11
CF_API_TOKEN                        2026-05-11
FLY_API_TOKEN                       2026-05-02
PRODUCTION_DEPLOY_OPERATOR_ACK_YAML 2026-05-07
R2_ACCESS_KEY_ID                    2026-05-07
R2_BUCKET                           2026-05-07
R2_ENDPOINT                         2026-05-07
R2_SECRET_ACCESS_KEY                2026-05-07
```

## 2. HIGH (workflow が直接 fail、9 種)

| secret | 用途 workflow | 取得経路 (1 行) | 設定 cmd |
| --- | --- | --- | --- |
| `TG_BOT_TOKEN` | narrative-sla-breach-hourly (15 連続 fail 直接原因) | Telegram `@BotFather` に `/newbot` 送信 → name 入力 → token copy | `gh secret set TG_BOT_TOKEN --body '<paste>'` |
| `TG_CHAT_ID` | narrative-sla-breach-hourly | bot に hi 送信 → `curl https://api.telegram.org/bot<TG_BOT_TOKEN>/getUpdates` → `chat.id` 抜き | `gh secret set TG_CHAT_ID --body '<paste>'` |
| `NPM_TOKEN` | sdk-publish / sdk-publish-agents / sdk-republish / mcp-registry-publish | https://www.npmjs.com/settings/<user>/tokens → Generate New Token (Granular Access, scope=@autonomath, packages:write) | `gh secret set NPM_TOKEN --body '<paste>'` |
| `PYPI_API_TOKEN` | sdk-publish (python lane) | https://pypi.org/manage/account/token/ → Add API token → scope=project autonomath-mcp → copy | `gh secret set PYPI_API_TOKEN --body '<paste>'` |
| `JPCITE_API_KEY` | practitioner-eval-publish | `curl -X POST https://api.jpcite.com/v1/me/login_request -d '{"email":"info@bookyou.net"}'` → magic link → `POST /v1/me/api_keys` → copy | `gh secret set JPCITE_API_KEY --body '<paste>'` |
| `JPCITE_ACCEPTANCE_KEY` | acceptance_check (週次) | 本番 API で acceptance scope 専用 key を発行 (`POST /v1/me/api_keys` body=`{"scope":"acceptance"}`) | `gh secret set JPCITE_ACCEPTANCE_KEY --body '<paste>'` |
| `CLOUDFLARE_API_TOKEN` | pages-deploy-main / production-gate-dashboard-daily 他 (yml 側で `CF_API_TOKEN` でなく `CLOUDFLARE_API_TOKEN` を参照する箇所が 3 ファイル) | 既存 `CF_API_TOKEN` 値を mirror (`gh secret list` 後に値を再貼付) | `gh secret set CLOUDFLARE_API_TOKEN --body '<paste-same-as-CF_API_TOKEN>'` |
| `CLOUDFLARE_ACCOUNT_ID` | production-gate-dashboard-daily 他 (yml 側 alias) | 既存 `CF_ACCOUNT_ID` 値を mirror | `gh secret set CLOUDFLARE_ACCOUNT_ID --body '<paste-same-as-CF_ACCOUNT_ID>'` |
| `JPINTEL_DB_R2_URL` | production-gate-dashboard-daily (DB pre-signed URL) | R2 dashboard → bucket=`jpcite-db-backup` → object=`autonomath.db` → Generate pre-signed URL (1y TTL) | `gh secret set JPINTEL_DB_R2_URL --body '<paste>'` |

## 3. MEDIUM (部分機能 fail / fallback 有、12 種)

| secret | 用途 | 取得経路 | 設定 cmd |
| --- | --- | --- | --- |
| `CF_ZONE_ID` | tls-check / index-now-cron | https://dash.cloudflare.com → jpcite.com → 右サイドバー API → Zone ID copy | `gh secret set CF_ZONE_ID --body '<paste>'` |
| `POSTMARK_TOKEN` | egov-pubcomment-daily / billing-health-cron | https://account.postmarkapp.com → Servers → jpcite → API Tokens → Server Token copy | `gh secret set POSTMARK_TOKEN --body '<paste>'` |
| `POSTMARK_API_TOKEN` | trial-expire-cron 他 (別 token slot として参照) | 同上の Server Token を mirror、または Account Token を Postmark Account → API Tokens で生成 | `gh secret set POSTMARK_API_TOKEN --body '<paste>'` |
| `POSTMARK_FROM_TX` | trial-expire-cron / billing-health-cron (送信元 from address) | Postmark で verified sender address (例: `noreply@bookyou.net`) | `gh secret set POSTMARK_FROM_TX --body 'noreply@bookyou.net'` |
| `POSTMARK_FROM_REPLY` | trial-expire-cron (reply-to address) | Postmark で verified address (例: `info@bookyou.net`) | `gh secret set POSTMARK_FROM_REPLY --body 'info@bookyou.net'` |
| `SENTRY_DSN` | 32 workflow (alert 配信全般) | https://sentry.io → jpcite project → Settings → Client Keys (DSN) copy | `gh secret set SENTRY_DSN --body '<paste>'` |
| `OPERATOR_EMAIL_TO` | egov-pubcomment-daily (通知先) | bookyou.net 受信可能 address (`info@bookyou.net`) | `gh secret set OPERATOR_EMAIL_TO --body 'info@bookyou.net'` |
| `AWS_ACCESS_KEY_ID` | production-gate-dashboard-daily (S3 fallback 経路) | R2 互換のため `R2_ACCESS_KEY_ID` 値を mirror | `gh secret set AWS_ACCESS_KEY_ID --body '<paste-same-as-R2_ACCESS_KEY_ID>'` |
| `AWS_SECRET_ACCESS_KEY` | production-gate-dashboard-daily | `R2_SECRET_ACCESS_KEY` 値を mirror | `gh secret set AWS_SECRET_ACCESS_KEY --body '<paste-same-as-R2_SECRET_ACCESS_KEY>'` |
| `JPCITE_BRAND_GITHUB_TOKEN` | rebrand-notify-once (dispatch-only) | https://github.com/settings/tokens → Fine-grained → repo=jpcite-brand, scope=contents:write | `gh secret set JPCITE_BRAND_GITHUB_TOKEN --body '<paste>'` |
| `CROSS_REPO_PAT` | weekly-digest 他 cross-repo dispatch | 同 token を Fine-grained で repo=multiple, scope=actions:write | `gh secret set CROSS_REPO_PAT --body '<paste>'` |
| `GH_PAT_WATCH` | weekly-digest watch lane | 同 token を Fine-grained で repo=jpcite, scope=metadata:read+actions:read | `gh secret set GH_PAT_WATCH --body '<paste>'` |

## 4. LOW (warning-only path / dispatch-only、12 種)

| secret | 用途 | 取得経路 | 設定 cmd |
| --- | --- | --- | --- |
| `SLACK_WEBHOOK_URL` | 通知 hop general | https://api.slack.com/apps → Incoming Webhooks → Add New Webhook → channel=#jpcite-ops → copy | `gh secret set SLACK_WEBHOOK_URL --body '<paste>'` |
| `SLACK_WEBHOOK_OPS` | ops 通知 | 同上で channel=#jpcite-ops, dedicated webhook | `gh secret set SLACK_WEBHOOK_OPS --body '<paste>'` |
| `SLACK_WEBHOOK_INGEST` | ingest 系 11 workflow | 同上で channel=#jpcite-ingest | `gh secret set SLACK_WEBHOOK_INGEST --body '<paste>'` |
| `SLACK_WEBHOOK_COMPETITIVE` | competitive-watch | 同上で channel=#jpcite-watch | `gh secret set SLACK_WEBHOOK_COMPETITIVE --body '<paste>'` |
| `GSC_TOKEN` | refresh-sources / brand-signals (Google Search Console) | https://console.cloud.google.com → IAM → Service account → Keys → JSON → base64 encode | `gh secret set GSC_TOKEN --body '<paste>'` |
| `BING_TOKEN` | refresh-sources / brand-signals (Bing Webmaster) | https://www.bing.com/webmasters → Settings → API Access → API Key copy | `gh secret set BING_TOKEN --body '<paste>'` |
| `INDEXNOW_HOST` | index-now-cron | host literal (`jpcite.com`) | `gh secret set INDEXNOW_HOST --body 'jpcite.com'` |
| `INDEXNOW_KEY` | index-now-cron | UUID v4 生成 + `https://jpcite.com/<KEY>.txt` に同 key を 200 で返す静的 file 配置 | `gh secret set INDEXNOW_KEY --body '<uuid>'` |
| `CODECOV_TOKEN` | test (codecov upload) | https://app.codecov.io/gh/<owner>/jpcite → Settings → Repository Upload Token copy | `gh secret set CODECOV_TOKEN --body '<paste>'` |
| `STAGING_URL` | e2e (default fallback あり) | staging URL literal (`https://staging.jpcite.com`)、staging 未稼働なら prod URL | `gh secret set STAGING_URL --body 'https://api.jpcite.com'` |
| `LOADTEST_PRO_KEY` | loadtest (dispatch-only) | k6 cloud / Artillery Pro の API key | `gh secret set LOADTEST_PRO_KEY --body '<paste>'` |
| `LOADTEST_WEBHOOK_SECRET` | loadtest (dispatch-only) | 任意の HMAC secret (`openssl rand -hex 32`) | `gh secret set LOADTEST_WEBHOOK_SECRET --body "$(openssl rand -hex 32)"` |

## 5. 設定方針

1. **HIGH 9 種を最優先**で fill (workflow 即時 fail を止める)
2. **MEDIUM 12 種**は機能別に決める。`POSTMARK_*` 系は Postmark account 作成済かで一括 fill 可
3. **LOW 12 種**は warning-only path or dispatch-only なので、organic 流入が立ち上がるまで放置可
4. `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` / `AWS_*` は既存 secret を mirror するだけなので最も簡単 (yml 改修よりは secret 多重設定の方が retry コスト低)

## 6. memory `feedback_secret_store_separation`

GH secret と Fly secret は **完全別 namespace**。本 audit は GH side のみ。
Fly side は `fly secrets list -a jpcite-api` で別 audit。
`.env.local` を SOT に GH + Fly 両 mirror 必須。

## 7. 即実行 script

`/tmp/jpcite_secret_setup.sh` 参照。33 cmd 連発、各行は token を fill するだけで実行可。

---

END
