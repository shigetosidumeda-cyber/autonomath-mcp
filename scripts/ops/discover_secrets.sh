#!/usr/bin/env bash
# Wave 19 §discover — 全 secret/token の在処を 1 コマンドで列挙する。
# 値は echo しない (presence only)。新 Claude Code セッションが最初に走らせる。
#
# Usage:
#   bash scripts/ops/discover_secrets.sh
#
# Exit code:
#   0 = 全 required item が存在
#   1 = required の missing あり
#
# ユーザーへの問い合わせを発生させない (user が「持ってる」と言ったものは必ずどこかにある)。

set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
JPCITE_DIR="$ROOT"
HOME_DIR="${HOME}"

R='\033[31m'
G='\033[32m'
Y='\033[33m'
B='\033[36m'
N='\033[0m'

ok=0
miss=0

check() {
    local name="$1"
    local where="$2"
    local cmd="$3"
    local required="$4"  # yes / optional
    if eval "$cmd" >/dev/null 2>&1; then
        printf "${G}✓${N} %-40s %s\n" "$name" "$where"
        ok=$((ok+1))
    else
        if [ "$required" = "yes" ]; then
            printf "${R}✗${N} %-40s %s ${R}(REQUIRED)${N}\n" "$name" "$where"
            miss=$((miss+1))
        else
            printf "${Y}-${N} %-40s %s ${Y}(optional)${N}\n" "$name" "$where"
        fi
    fi
}

echo
printf "${B}=== jpcite secret discovery ===${N}\n"
echo "scanned at: $(date)"
echo "host: $(hostname)"
echo "user: $(whoami)"
echo

printf "${B}--- 1. Local credential files ---${N}\n"
check "AWS/R2 credentials"          "~/.aws/credentials"                "test -s ${HOME_DIR}/.aws/credentials"   yes
check "Cloudflare Wrangler oauth"   "~/.wrangler/config/default.toml"   "test -s ${HOME_DIR}/.wrangler/config/default.toml" yes
check "Fly access_token"            "~/.fly/config.yml"                 "test -s ${HOME_DIR}/.fly/config.yml"     yes
check "GitHub gh CLI auth"          "~/.config/gh/hosts.yml"            "test -s ${HOME_DIR}/.config/gh/hosts.yml" yes
check "gBizINFO API token source"   "~/.gbiz_token (value not printed)" "test -s ${HOME_DIR}/.gbiz_token"          optional
check "gcloud credentials"          "~/.config/gcloud/credentials.db"   "test -s ${HOME_DIR}/.config/gcloud/credentials.db" optional
check "self-managed env"            "~/.jpcite_secrets_self.env"        "test -s ${HOME_DIR}/.jpcite_secrets_self.env" optional
check "PyPI ~/.pypirc"              "~/.pypirc"                         "test -s ${HOME_DIR}/.pypirc"             optional
check "npm ~/.npmrc"                "~/.npmrc"                          "test -s ${HOME_DIR}/.npmrc"               optional

echo

printf "${B}--- 2. CLI authentications (live check) ---${N}\n"
check "fly auth whoami"             "fly CLI login"                     "fly auth whoami"                            yes
check "gh auth status"              "gh CLI login"                      "gh auth status"                             yes
check "wrangler whoami"             "Cloudflare wrangler login"         "cd ${JPCITE_DIR} && npx --yes wrangler whoami" yes
check "1Password CLI"               "/usr/local/bin/op (account configured)" "op account list | grep -q ."          optional
check "gcloud active account"       "gcloud auth list"                  "gcloud auth list 2>&1 | grep -q ACTIVE"     optional

echo

printf "${B}--- 3. Fly secrets (autonomath-api) ---${N}\n"
if fly auth whoami >/dev/null 2>&1; then
    fly_secrets="$(fly secrets list -a autonomath-api 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -v '^$' | grep -v '^─' || true)"
    fly_required=(
        "ADMIN_API_KEY"
        "STRIPE_SECRET_KEY"
        "STRIPE_WEBHOOK_SECRET"
        "STRIPE_BILLING_PORTAL_CONFIG_ID"
        "STRIPE_PRICE_PER_REQUEST"
        "STRIPE_TAX_ENABLED"
        "API_KEY_SALT"
        "AUTONOMATH_API_HASH_PEPPER"
        "AUTONOMATH_DB_SHA256"
        "AUTONOMATH_DB_URL"
        "INVOICE_FOOTER_JA"
        "INVOICE_REGISTRATION_NUMBER"
        "JPCITE_EDGE_AUTH_SECRET"
        "JPCITE_SESSION_SECRET"
        "JPINTEL_CORS_ORIGINS"
        "JPINTEL_ENV"
        "RATE_LIMIT_FREE_PER_DAY"
        "R2_ACCESS_KEY_ID"
        "R2_SECRET_ACCESS_KEY"
        "R2_BUCKET"
        "R2_ENDPOINT"
    )
    fly_optional=(
        "SENTRY_DSN"
        "POSTMARK_API_TOKEN"
        "INDEXNOW_KEY"
        "CF_API_TOKEN"
        "CF_ZONE_ID"
        "CF_PAGES_DEPLOY_HOOK"
    )
    for s in "${fly_required[@]}"; do
        if echo "$fly_secrets" | grep -qx "$s"; then
            printf "${G}✓${N} %-40s %s\n" "$s" "Fly Deployed"
            ok=$((ok+1))
        else
            printf "${R}✗${N} %-40s %s ${R}(REQUIRED)${N}\n" "$s" "Fly missing"
            miss=$((miss+1))
        fi
    done

    audit_has_legacy=false
    audit_has_rotation=false
    if echo "$fly_secrets" | grep -qx "AUDIT_SEAL_SECRET"; then
        audit_has_legacy=true
    fi
    if echo "$fly_secrets" | grep -qx "JPINTEL_AUDIT_SEAL_KEYS"; then
        audit_has_rotation=true
    fi
    if $audit_has_legacy || $audit_has_rotation; then
        if $audit_has_rotation; then
            printf "${G}✓${N} %-40s %s\n" "AUDIT_SEAL_SECRET or JPINTEL_AUDIT_SEAL_KEYS" "Fly boot gate (rotation list present)"
        else
            printf "${G}✓${N} %-40s %s\n" "AUDIT_SEAL_SECRET or JPINTEL_AUDIT_SEAL_KEYS" "Fly boot gate (legacy fallback present)"
        fi
        ok=$((ok+1))
    else
        printf "${R}✗${N} %-40s %s ${R}(REQUIRED)${N}\n" "AUDIT_SEAL_SECRET or JPINTEL_AUDIT_SEAL_KEYS" "Fly missing"
        miss=$((miss+1))
    fi

    appi_disabled=false
    if grep -Eq '^[[:space:]]*AUTONOMATH_APPI_ENABLED[[:space:]]*=[[:space:]]*"(0|false|False)"' fly.toml 2>/dev/null; then
        appi_disabled=true
    fi
    if echo "$fly_secrets" | grep -qx "CLOUDFLARE_TURNSTILE_SECRET"; then
        printf "${G}✓${N} %-40s %s\n" "CLOUDFLARE_TURNSTILE_SECRET" "Fly Deployed (APPI boot gate)"
        ok=$((ok+1))
    elif $appi_disabled; then
        printf "${G}✓${N} %-40s %s\n" "CLOUDFLARE_TURNSTILE_SECRET" "Fly not required (AUTONOMATH_APPI_ENABLED=0)"
        ok=$((ok+1))
    else
        printf "${Y}-${N} %-40s %s ${Y}(conditional: required unless APPI disabled)${N}\n" "CLOUDFLARE_TURNSTILE_SECRET" "Fly missing"
    fi

    if echo "$fly_secrets" | grep -qx "GBIZINFO_API_TOKEN"; then
        printf "${G}✓${N} %-40s %s\n" "GBIZINFO_API_TOKEN" "Fly Deployed (live gBiz ingest)"
        ok=$((ok+1))
    else
        printf "${Y}-${N} %-40s %s ${Y}(conditional: live gBiz ingest only; not deploy precondition)${N}\n" "GBIZINFO_API_TOKEN" "Fly missing"
    fi

    for s in "${fly_optional[@]}"; do
        if echo "$fly_secrets" | grep -qx "$s"; then
            printf "${G}✓${N} %-40s %s\n" "$s" "Fly Deployed"
            ok=$((ok+1))
        else
            printf "${Y}-${N} %-40s %s ${Y}(optional)${N}\n" "$s" "Fly missing"
        fi
    done
    if echo "$fly_secrets" | grep -qx "TELEGRAM_BOT_TOKEN"; then
        printf "${Y}-${N} %-40s %s ${Y}(legacy ignored; use TG_BOT_TOKEN)${N}\n" "TELEGRAM_BOT_TOKEN" "Fly secret"
    fi
else
    echo "  (skipped — fly CLI not authenticated)"
fi

echo

printf "${B}--- 4. GitHub repository secrets ---${N}\n"
if (cd "$JPCITE_DIR" && gh secret list >/dev/null 2>&1); then
    gh_secrets="$(cd "$JPCITE_DIR" && gh secret list 2>/dev/null | awk '{print $1}')"
    gh_required=(
        "FLY_API_TOKEN"
    )
    gh_optional=(
        "PYPI_API_TOKEN"
        "NPM_TOKEN"
        "R2_ACCESS_KEY_ID"
        "R2_SECRET_ACCESS_KEY"
        "R2_BUCKET"
        "R2_ENDPOINT"
        "CF_API_TOKEN"
        "CF_ZONE_ID"
        "CF_PAGES_DEPLOY_HOOK"
        "INDEXNOW_HOST"
        "INDEXNOW_KEY"
        "SENTRY_DSN"
        "POSTMARK_API_TOKEN"
        "SLACK_WEBHOOK_URL"
        "SLACK_WEBHOOK_INGEST"
        "GH_PAT_WATCH"
        "CODECOV_TOKEN"
        "LOADTEST_PRO_KEY"
        "LOADTEST_WEBHOOK_SECRET"
        "STAGING_URL"
        "TG_BOT_TOKEN"
        "TG_CHAT_ID"
    )
    for s in "${gh_required[@]}"; do
        if echo "$gh_secrets" | grep -qx "$s"; then
            printf "${G}✓${N} %-40s %s\n" "$s" "GitHub secret"
            ok=$((ok+1))
        else
            printf "${R}✗${N} %-40s %s ${R}(REQUIRED)${N}\n" "$s" "GitHub missing"
            miss=$((miss+1))
        fi
    done
    for s in "${gh_optional[@]}"; do
        if echo "$gh_secrets" | grep -qx "$s"; then
            printf "${G}✓${N} %-40s %s\n" "$s" "GitHub secret"
            ok=$((ok+1))
        else
            printf "${Y}-${N} %-40s %s ${Y}(optional)${N}\n" "$s" "GitHub missing"
        fi
    done
    if echo "$gh_secrets" | grep -qx "TELEGRAM_BOT_TOKEN"; then
        printf "${Y}-${N} %-40s %s ${Y}(legacy ignored; use TG_BOT_TOKEN)${N}\n" "TELEGRAM_BOT_TOKEN" "GitHub secret"
    fi
else
    echo "  (skipped — gh CLI not authenticated, or not in jpcite repo)"
fi

echo
printf "${B}--- summary ---${N}\n"
printf "  ${G}✓ found:${N} %d\n" "$ok"
printf "  ${R}✗ missing required:${N} %d\n" "$miss"
echo
echo "Source of truth: docs/_internal/SECRETS_REGISTRY.md"
echo "Auto-publish via OIDC trusted-publishing (no token needed for PyPI/npm) — see SECRETS_REGISTRY.md §3 経路 A"
echo

if [ "$miss" -gt 0 ]; then
    exit 1
fi
exit 0
