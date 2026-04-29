# Secrets inventory

Generated 2026-04-29 by hunt audit. Single source of truth for every secret /
environment variable consumed by GitHub Actions workflows or Fly machine cron
scripts. Update this file whenever a new secret is added or retired.

Two scopes:

* **GitHub repository secrets** — set at `Settings → Secrets and variables →
  Actions`, consumed via `${{ secrets.NAME }}` in `.github/workflows/*.yml`.
  Verify with the GitHub UI.
* **Fly machine secrets / env** — set via `flyctl secrets set NAME=… -a
  autonomath-api`, consumed via `os.environ.get("NAME")` inside
  `scripts/cron/*.py` running on the Fly machine. Verify with
  `flyctl secrets list -a autonomath-api`.

A workflow that does `flyctl ssh console -C "/app/.venv/bin/python …"`
inherits the Fly machine's env, so any secret consumed *only* inside the
script lives in the Fly side, not the GitHub side.

## GitHub repository secrets

| Secret | Consumed by | Required? | Notes |
|---|---|---|---|
| `FLY_API_TOKEN` | 27 workflows (every `flyctl ssh` cron + deploy + nightly-backup + weekly-backup-autonomath) | yes | Single deploy token with ssh + sftp scope on app `autonomath-api`. |
| `GITHUB_TOKEN` | pages-preview, pages-regenerate (implicit on every workflow) | auto | Provided by GitHub; only listed where explicitly referenced. |
| `R2_ENDPOINT` | nightly-backup, weekly-backup-autonomath | yes | Cloudflare R2 S3 endpoint, e.g. `https://<acct>.r2.cloudflarestorage.com`. |
| `R2_ACCESS_KEY_ID` | nightly-backup, weekly-backup-autonomath | yes | R2 access key. |
| `R2_SECRET_ACCESS_KEY` | nightly-backup, weekly-backup-autonomath | yes | R2 secret. |
| `R2_BUCKET` | nightly-backup, weekly-backup-autonomath | yes | Target bucket (e.g. `autonomath-backups`). |
| `CF_API_TOKEN` | analytics-cron, pages-preview | yes (analytics) / yes (pages) | Scope = "Account.Account Analytics:Read" for analytics; Pages deploy scope for pages-preview. |
| `CF_ACCOUNT_ID` | pages-preview | yes | Cloudflare account id. |
| `CF_ZONE_ID` | analytics-cron | yes | Zone id for `zeimu-kaikei.ai`. |
| `CF_PAGES_DEPLOY_HOOK` | pages-regenerate | yes | Cloudflare Pages deploy hook URL. |
| `INDEXNOW_HOST` | index-now-cron | yes | The host being pinged (e.g. `zeimu-kaikei.ai`). |
| `INDEXNOW_KEY` | index-now-cron | yes | IndexNow key file token. |
| `SENTRY_DSN` | 14 cron workflows (every cron with Sentry alerting) | optional | Workflows fail-open if missing. |
| `SLACK_WEBHOOK_INGEST` | 7 ingest workflows | optional | Driver-failure alerts. |
| `SLACK_WEBHOOK_URL` | deploy, tls-check | optional | Generic ops channel. |
| `SLACK_WEBHOOK_COMPETITIVE` | competitive-watch | optional | HIGH-severity competitive alerts. |
| `GH_PAT_WATCH` | competitive-watch | optional | Lifts GitHub API rate limit for unauthenticated polling. |
| `PYPI_API_TOKEN` | release, sdk-publish | yes | PyPI publish token. Trusted publishing preferred — token is fallback. |
| `NPM_TOKEN` | sdk-publish | yes (TS SDK) | npm publish token. |
| `CODECOV_TOKEN` | test | optional | Coverage upload. |
| `LOADTEST_PRO_KEY` | loadtest | optional | API key for paid-tier loadtest path. |
| `LOADTEST_WEBHOOK_SECRET` | loadtest | optional | HMAC for loadtest's customer-webhook path. |
| `STAGING_URL` | loadtest | yes | Target staging URL for loadtest. |

## Fly machine secrets / env

These live on the Fly machine via `flyctl secrets set`. Consumed by cron
scripts under `scripts/cron/` running inside `flyctl ssh console`. None are
referenced in `.github/workflows/*.yml` because the workflows just `ssh -C
"/app/.venv/bin/python …"` and let the script read its own env.

| Env var | Consumer | Required? | Notes |
|---|---|---|---|
| `JPINTEL_DB_PATH` | backup_jpintel.py | optional | Defaults to `/data/jpintel.db`. |
| `JPINTEL_BACKUP_BUCKET` | backup_jpintel.py | yes (R2 path) | R2 bucket name; same as `R2_BUCKET` in GitHub side. |
| `JPINTEL_BACKUP_PREFIX` | backup_jpintel.py | optional | Object key prefix; defaults to `nightly/jpintel`. |
| `JPINTEL_BACKUP_LOCAL_DIR` | backup_jpintel.py | optional | Local dump dir on Fly volume; defaults to `/data/backups`. |
| `JPINTEL_LOG_LEVEL` | backup_jpintel.py | optional | Defaults to `INFO`. |
| `AUTONOMATH_DB_PATH` | backup_autonomath.py | optional | Defaults to `autonomath.db` (current dir). |
| `AUTONOMATH_DB_URL` | backup_autonomath.py | optional | Alternative source URL for restore probe. |
| `AUTONOMATH_DB_SHA256` | backup_autonomath.py | optional | Pinned hash for integrity check. |
| `AUTONOMATH_BACKUP_LOCAL_DIR` | backup_autonomath.py | optional | Local dump dir; defaults to `/data/backups/autonomath`. |
| `AUTONOMATH_BACKUP_PREFIX` | backup_autonomath.py | optional | Object key prefix; defaults to `weekly/autonomath`. |
| `AUTONOMATH_BUDGET_JPY` | predictive_billing_alert.py | optional | Per-month budget cap; alerts when cumulative cost projects over this number. |
| `R2_BUCKET` | backup_jpintel.py, backup_autonomath.py | yes (R2 path) | Same value as GitHub-side `R2_BUCKET`. |
| `OPERATOR_EMAIL` | predictive_billing_alert.py and other alert paths | optional | Postmark "to" address for low-volume alerts. Defaults to `info@bookyou.net`. |
| `POSTMARK_API_TOKEN` | run_saved_searches.py, send_daily_kpi_digest.py, expire_trials.py | yes (email surfaces) | Server token. |
| `POSTMARK_FROM` | as above | optional | Defaults to a Bookyou-owned address. |
| `SENTRY_DSN` | every cron with `safe_capture_message` | optional | Fly side mirrors GitHub side — set both. |
| `SENTRY_ENVIRONMENT` | every cron with Sentry breadcrumbs | optional | Defaults to `production`. |
| `INDEXNOW_HOST` | index_now_ping.py | yes (when index-now path is on) | Mirrors GitHub side. |
| `INDEXNOW_KEY` | index_now_ping.py | yes (when index-now path is on) | Mirrors GitHub side. |
| `CF_API_TOKEN` | cf_analytics_export.py | yes | Mirrors GitHub side. |
| `CF_ZONE_ID` | cf_analytics_export.py | yes | Mirrors GitHub side. |
| `DRY_RUN` | every cron supporting `--dry-run` | optional | Boolean-ish (`true`/`1`); when set, scripts skip DB writes and external POSTs. Recommended for one-shot debugging. |

## Verification commands

```bash
# GitHub side
gh secret list

# Fly side
flyctl secrets list -a autonomath-api

# Sanity check: every secret referenced in a workflow has a Fly mirror if the
# workflow shells into Fly.
grep -hoE "secrets\.[A-Z_][A-Z0-9_]+" .github/workflows/*.yml | sed 's/secrets\.//' | sort -u
grep -hoE "os\.(environ|getenv)\.?(get)?\(['\"][A-Z_][A-Z0-9_]+['\"]" scripts/cron/*.py \
    | sed -E "s/.*['\"]([A-Z_][A-Z0-9_]+)['\"].*/\\1/" | sort -u
```

## Security notes

* Never log secret values. Cron scripts log only **presence** (`SENTRY_DSN
  configured` / `Postmark token missing — skipping email`).
* `flyctl secrets list` only shows names + revision — values are never read
  back. Rotate via `flyctl secrets set NAME=newvalue` (zero-downtime).
* `FLY_API_TOKEN` is the keys-to-the-kingdom token. Audit usage via
  `flyctl tokens list`. Rotate if any GitHub action ran an unverified
  third-party action.
* PyPI / npm publish tokens are scoped to the single package each.
  `PYPI_API_TOKEN` is `pypi-` prefixed; `NPM_TOKEN` is `npm_` prefixed —
  rotation is the same operation in both registries.
* R2 credentials live on Cloudflare — rotation is independent of Fly /
  GitHub.
