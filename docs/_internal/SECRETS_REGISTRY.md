# jpcite Secrets Registry — 単一 source of truth

最終更新: 2026-05-06 (production boot gate / secret 名整合)

> **新セッションへ**: token を user に聞く前に必ず本ファイル + `scripts/ops/discover_secrets.sh` を見ること。**全 token は既にどこかに存在する**。

## 0. 結論サマリ — どこに何があるか

| 種別 | 在処 | 名前 | 確認方法 |
|---|---|---|---|
| Stripe live secret | Fly secrets (autonomath-api) | `STRIPE_SECRET_KEY` | `fly secrets list -a autonomath-api` |
| Stripe webhook | Fly secrets | `STRIPE_WEBHOOK_SECRET` | 同上 |
| Stripe billing portal | Fly secrets | `STRIPE_BILLING_PORTAL_CONFIG_ID` | 同上 |
| Stripe price ID | Fly secrets | `STRIPE_PRICE_PER_REQUEST` | 同上 |
| Stripe tax flag | Fly secrets | `STRIPE_TAX_ENABLED` | 同上 |
| R2 access key | Fly secrets + `~/.aws/credentials` (default profile) | `R2_ACCESS_KEY_ID` | `test -s ~/.aws/credentials` (値は表示しない) |
| R2 secret | Fly secrets + `~/.aws/credentials` | `R2_SECRET_ACCESS_KEY` | 同上 |
| R2 endpoint URL | Fly secrets | `R2_ENDPOINT` | `fly secrets list -a autonomath-api` |
| R2 bucket name | Fly secrets | `R2_BUCKET` | 同上 |
| AUDIT_SEAL HMAC (legacy) | Fly secrets | `AUDIT_SEAL_SECRET` | `fly secrets list -a autonomath-api` |
| AUDIT_SEAL HMAC (rotation) | Fly secrets | `JPINTEL_AUDIT_SEAL_KEYS` | 同上 |
| API key salt | Fly secrets | `API_KEY_SALT` | 同上 |
| Cloudflare Turnstile | Fly secrets | `CLOUDFLARE_TURNSTILE_SECRET` | 同上 |
| CORS origin allowlist | Fly secrets | `JPINTEL_CORS_ORIGINS` | 同上 |
| Production env flag | Fly secrets | `JPINTEL_ENV` (=production) | 同上 |
| Admin API key | Fly secrets | `ADMIN_API_KEY` | 同上 |
| Anonymous rate limit | Fly secrets | `RATE_LIMIT_FREE_PER_DAY` | 同上 |
| Invoice metadata | Fly secrets | `INVOICE_FOOTER_JA`, `INVOICE_REGISTRATION_NUMBER` | 同上 |
| Autonomath DB url/sha/pepper | Fly secrets | `AUTONOMATH_DB_URL`, `AUTONOMATH_DB_SHA256`, `AUTONOMATH_API_HASH_PEPPER` | 同上 |
| Cloudflare oauth (Wrangler) | `~/.wrangler/config/default.toml` | (oauth_token, scopes: write/admin) | `npx wrangler whoami` |
| Fly machine auth | `~/.fly/config.yml` | `access_token` | `fly auth whoami` |
| GitHub repo auth | `~/.config/gh/hosts.yml` | (gho_*) | `gh auth status` |
| Fly→GitHub deploy token | GitHub repo secret | `FLY_API_TOKEN` | `gh secret list` (jpcite repo cwd) |
| gBizINFO API token | `~/.gbiz_token` + live ingest 有効時のみ Fly secrets | `GBIZINFO_API_TOKEN` | `test -s ~/.gbiz_token`; `fly secrets list -a autonomath-api` |
| gcloud auth | `~/.config/gcloud/credentials.db` | (sqlite) | `gcloud auth list` |

### 0.1. Production boot gate / deploy precondition

`src/jpintel_mcp/api/main.py::_assert_production_secrets` は `JPINTEL_ENV=prod` / `production` のとき、下記を production boot gate として扱う。secret の値は registry に書かない。

| 名前 | 必須条件 | 備考 |
|---|---|---|
| `API_KEY_SALT` | production では必須 | placeholder 不可、32 chars 以上。rotate は全 API key 再発行級。 |
| `JPCITE_SESSION_SECRET` | production では必須 | HS256 session cookie signing secret。placeholder 不可、32 chars 以上。Google/GitHub login session forge 防止。 |
| `AUDIT_SEAL_SECRET` または `JPINTEL_AUDIT_SEAL_KEYS` | production ではどちらか 1 つ必須 | `JPINTEL_AUDIT_SEAL_KEYS` が rotation list。`AUDIT_SEAL_SECRET` は legacy single-key fallback。 |
| `STRIPE_SECRET_KEY` | production では必須 | live Stripe API secret。 |
| `STRIPE_WEBHOOK_SECRET` | production では必須 | live webhook signing secret。 |
| `CLOUDFLARE_TURNSTILE_SECRET` | `AUTONOMATH_APPI_ENABLED` が未設定/default enabled、または true 相当なら必須 | `AUTONOMATH_APPI_ENABLED=0` / `false` / `False` で APPI intake を止める場合のみ boot gate 対象外。 |
| `GBIZINFO_API_TOKEN` | core API deploy precondition ではない | live gBiz ingest (`GBIZINFO_INGEST_ENABLED` が有効な `ingest_gbiz_*` / `gbiz-ingest-monthly`) を動かすときだけ Fly secret として必須。未有効・未運用なら deploy を止めない。 |

## 1. 確認済 (実存) — もう聞かない

### Fly side (production)

`fly secrets list -a autonomath-api` で **26 個 Deployed** 確認済 (2026-05-13 時点)。これは snapshot であり、現行 boot gate の判定は §0.1 を優先する:

```
ADMIN_API_KEY, API_KEY_SALT,
AUTONOMATH_API_HASH_PEPPER, AUTONOMATH_DB_SHA256, AUTONOMATH_DB_URL,
AUDIT_SEAL_SECRET,
GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET,
GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET,
INVOICE_FOOTER_JA, INVOICE_REGISTRATION_NUMBER,
JPCITE_SESSION_SECRET,
JPINTEL_CORS_ORIGINS, JPINTEL_ENV,
RATE_LIMIT_FREE_PER_DAY,
R2_ACCESS_KEY_ID, R2_BUCKET, R2_ENDPOINT, R2_SECRET_ACCESS_KEY,
SENTRY_DSN,
STRIPE_BILLING_PORTAL_CONFIG_ID, STRIPE_PRICE_PER_REQUEST,
STRIPE_SECRET_KEY, STRIPE_TAX_ENABLED, STRIPE_WEBHOOK_SECRET
```

→ この snapshot は `AUDIT_SEAL_SECRET` fallback で audit seal boot gate を満たす構成。`JPINTEL_AUDIT_SEAL_KEYS` は rotation list を有効化するときに追加する。
→ `CLOUDFLARE_TURNSTILE_SECRET` は APPI intake を有効にする production boot gate。`AUTONOMATH_APPI_ENABLED=0` / `false` / `False` で intake を止める場合のみ未投入でもよい。
→ `GBIZINFO_API_TOKEN` は live gBiz ingest 用であり、core API の production deploy precondition ではない。

### Local side

| ファイル | 内容 |
|---|---|
| `~/.aws/credentials` | R2 keys (default profile、Fly 側と同値想定) |
| `~/.wrangler/config/default.toml` | Cloudflare oauth (write/admin scope、Pages/DNS/PageRules すべて触れる) |
| `~/.fly/config.yml` | Fly access_token (autonomath-api/autonomath-algo の app secrets minvers 同梱) |
| `~/.config/gh/hosts.yml` | GitHub PAT (repo + workflow + gist + read:org scope) |
| `~/.gbiz_token` | gBizINFO API token source (値は表示しない) |
| `~/.config/gcloud/credentials.db` | Google Cloud auth |
| `~/.jpcite_secrets_self.env` | self-generated `API_KEY_SALT` + local audit-seal draft (production Fly 名は `AUDIT_SEAL_SECRET` / `JPINTEL_AUDIT_SEAL_KEYS`) |

## 2. Fly / GitHub 側に未投入または条件付き

| 名前 | 想定経路 | 用途 | 必須? |
|---|---|---|---|
| `JPINTEL_AUDIT_SEAL_KEYS` | Fly secret | audit seal dual-key rotation | conditional: `AUDIT_SEAL_SECRET` が有効なら optional。legacy fallback をやめるなら required。 |
| `CLOUDFLARE_TURNSTILE_SECRET` | Cloudflare Turnstile dashboard → Fly secret | APPI disclosure/deletion intake Turnstile 検証 | conditional: APPI intake 有効時は production boot gate required。 |
| `GBIZINFO_API_TOKEN` | `~/.gbiz_token` から Fly secret へ投入 | live gBiz ingest (`gbiz-ingest-monthly`, `scripts/cron/ingest_gbiz_*_v2.py`) | conditional: live gBiz ingest 有効時のみ required。未有効時は deploy precondition ではない。 |
| `SENTRY_DSN` | sentry.io dashboard で取得 → Fly secret | 障害監視 | optional (workflow fail-open 設計) |
| `POSTMARK_API_TOKEN` | postmarkapp.com → Fly secret | transactional email | yes (saved_searches / KPI digest / trial expire を使うなら) |
| `TG_BOT_TOKEN` | @BotFather → GitHub repo secret | 障害 push 通知 (`narrative-sla-breach-hourly`, `narrative-audit-monthly`) | optional |
| `TG_CHAT_ID` | Telegram chat id → GitHub repo secret | 同上 | optional |
| `TELEGRAM_BOT_TOKEN` | historical alias only | current code/workflows は読まない。新規設定しない。 | no |
| `INDEXNOW_KEY` | jpcite.com 配下の static key file | search engine notify | optional |
| `CF_API_TOKEN` (analytics 専用) | dash.cloudflare.com → Fly secret | analytics-cron 専用 | optional (Wrangler oauth とは別) |
| `CF_ZONE_ID` (jpcite.com) | dash.cloudflare.com → Fly secret | analytics-cron + 301 redirect | yes (cf_redirect 使うなら) |
| `CF_PAGES_DEPLOY_HOOK` | Cloudflare Pages → Fly secret | pages-regenerate workflow | optional |
| `PYPI_API_TOKEN` | pypi.org → GitHub secret | release workflow | yes (PyPI publish 自動化) |
| `NPM_TOKEN` | npmjs.com → GitHub secret | sdk-publish workflow | yes (`@jpcite/agents` publish) |

### 2.1 GitHub workflow optional/fail-open names

The following names are referenced by GitHub workflows and are optional or workflow-specific. Missing values should not block the core production API deploy unless that workflow is being enabled as part of the same release:

| 名前 | 用途 | 扱い |
|---|---|---|
| `SLACK_WEBHOOK_INGEST` | ingest failure notification workflows | optional / fail-open |
| `SLACK_WEBHOOK_URL` | deploy / TLS notification workflows | optional / fail-open |
| `CODECOV_TOKEN` | test coverage upload | optional |
| `GH_PAT_WATCH` | competitive-watch workflow | optional |
| `INDEXNOW_HOST` | index-now workflow host override | optional |
| `LOADTEST_PRO_KEY` | staging/loadtest API key | staging only |
| `LOADTEST_WEBHOOK_SECRET` | staging/loadtest Stripe webhook signing secret | staging only |
| `STAGING_URL` | loadtest target URL | staging only |

## 3. PyPI / npm publish の現実的経路

PyPI / npm token がローカルにも GitHub にも見つからない → **3 つの経路**:

### 経路 A: Trusted Publishing (推奨、token 不要)

PyPI と npm の両方が **OIDC 経由の trusted publishing** をサポート:
- PyPI: `pypa/gh-action-pypi-publish@release/v1` を GitHub workflow で使う、trust を pypi.org で設定
- npm: `npm publish --provenance` で OIDC 経由

→ **token 不要で publish 可能**。GitHub workflow の `id-token: write` permission のみ。

### 経路 B: ローカルで対話 publish

ユーザーが手元で 1 度だけ:
```bash
# PyPI
pip install twine
twine upload dist/*   # username=__token__、password=対話入力

# npm
npm login   # ブラウザ認証
npm publish dist/agents
```

token を扱わないので registry 認証 cookie が `~/.pypirc` / `~/.npmrc` に保存される。

### 経路 C: GitHub Actions に token を設定 (従来型)

`gh secret set PYPI_API_TOKEN` / `gh secret set NPM_TOKEN` で 1 度だけ。

→ 推奨は **A (Trusted Publishing)** + **`.github/workflows/release.yml` の整備**。AI が workflow を書けば user は何もせず `git tag v0.x.y && git push --tags` で publish 自動化。

## 4. 弁護士相談について

→ **不要** (ユーザー判断 2026-05-05)。
代わりに `docs/_internal/W19_legal_self_audit.md` で **AI 自身の法律分析 + 採否判定** を実施。
旧 `W19_lawyer_consult_outline.md` は historical artifact として残置 (削除しない)。

## 5. 今後 user に「どこの token?」と聞かない約束

新セッションは下記 1-line で全状況把握可能:
```bash
bash /Users/shigetoumeda/jpcite/scripts/ops/discover_secrets.sh
```

このスクリプトが本ファイル §0 / §0.1 の存在 status を一覧化する。
**未存在の項目は `MISSING (acquire route: <URL>)` を返す** ので、ユーザー対話は不要。

## 6. 監査記録

- 2026-05-05 11:10: ユーザー指摘 (「全 token 持ってる、何度も聞かれてストレス」)
- 2026-05-05 11:11: 全面再調査 → 上記 24 項目のうち 20 個が Fly side に Deployed 済を確認
- 2026-05-05 11:12: 本 registry 作成、`secrets_inventory.md` (旧) は historical reference として保持

---

> 旧 `docs/_internal/secrets_inventory.md` は GitHub workflow 視点の doc (2026-04-29 hunt audit)。本 registry は実機 + Fly + 全 credential 在処の **operator 視点**。両方 source of truth として併存。
