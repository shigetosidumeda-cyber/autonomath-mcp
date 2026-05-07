---
title: Cloudflare DDoS / Abuse Mitigation Runbook
updated: 2026-05-07
operator_only: true
category: incident
---

# Cloudflare DDoS / Abuse Mitigation Runbook (G5)

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-07
**Related**: `docs/runbook/cloudflare_redirect.md` (the Cloudflare API token + Zone ID provisioning this runbook reuses), `docs/runbook/cors_setup.md` (CORS allowlist that interacts with WAF rules), `docs/runbook/sentry_alert_escalation.md` §4 (this runbook is the destination of `cloudflare_ddos_detected` + `cloudflare_abuse_pattern`), `docs/runbook/fly_machine_oom.md` (origin overload symptom).

This runbook covers DDoS, scraping abuse, credential stuffing, and other
high-volume malicious patterns that hit `api.jpcite.com` or
`jpcite.com`. The defense layers, in order, are:

1. **Cloudflare edge** (always-on DDoS L3/L4, free plan rate-limit + WAF).
2. **Fly Tokyo origin** (a single shared 4 GB machine — fragile under flood).
3. **Application** (anonymous 3 req/day per IP rate limit, API-key based
   metering).

The strategy is to keep load **off** the origin by tightening Cloudflare,
not by scaling Fly.

## 1. Detection

```text
A. Sentry alert `cloudflare_ddos_detected`
   (Cloudflare email or API event: "Under attack mode auto-engaged" /
   "Threat traffic spike").
B. Sentry alert `cloudflare_abuse_pattern`
   (5xx surge or 429 surge from a single ASN / Cloudflare reports).
C. Cloudflare dashboard → Analytics & Logs → Traffic shows a > 5x spike
   over baseline.
D. Fly machine CPU pressure (> 80% sustained 5 min) — `flyctl metrics
   cpu_used_seconds_total -a autonomath-api`.
E. UptimeRobot 5xx surge for api.jpcite.com (3+ consecutive 60s checks).
F. Operator-driven: noise spike in Sentry "anonymous_quota_exceeded" log
   events (single IP burning the 3 req/day in seconds is benign — many
   IPs simultaneously is suspicious).
```

**Pre-state self-check** (90 sec — confirm the spike is malicious, not a
legitimate traffic burst from a Hacker News / Twitter post):

```bash
# 1a. Open Cloudflare dashboard → Security → Events. Filter last 1h.
#     Sort by "Action: blocked" desc; look at top source ASN + country.
# 1b. Open Cloudflare → Analytics → Traffic. Look at "Total requests" vs
#     baseline (24h ago, 7d ago).
# 1c. Fly origin metrics.
flyctl metrics cpu_used_seconds_total -a autonomath-api -p 5m
flyctl metrics http_response_time_seconds -a autonomath-api -p 5m
flyctl logs -a autonomath-api -n 200 | grep -E "(429|5\d\d)" | tail -50
# 1d. Sample request shape — is it a single endpoint being hammered?
flyctl logs -a autonomath-api -n 500 | grep "GET\|POST" | awk '{print $7}' | sort | uniq -c | sort -rn | head -10
```

Disambiguation:

* **Single endpoint, single ASN, > 1000 RPS** ⇒ targeted scrape or DDoS — §3.
* **Many endpoints, many ASNs, > 100 RPS each** ⇒ botnet / amplification —
  §3 + Under Attack mode.
* **Login or API-key endpoints, low volume but distributed** ⇒ credential
  stuffing — §4.
* **Single endpoint, baseline-shape, 200s** ⇒ legitimate traffic spike,
  do **not** engage WAF; §6 (capacity confirmation only).

## 2. Cloudflare API token + Zone ID prerequisite

The active steps reuse the token from `docs/runbook/cloudflare_redirect.md`
plus an additional scope:

```text
Required Custom Token scopes (extend the existing redirect token, do NOT mint a new one):
  - Zone.WAF:Edit
  - Zone.Firewall Services:Edit (for IP Access Rules + Rate Limiting Rules)
  - Zone.Page Rules:Edit (already present — used for Under Attack toggle on free plan)
  - Zone.Zone Settings:Edit (used for Security Level escalation)

Zone IDs needed (operator must have these in ~/.jpcite_secrets.env):
  CLOUDFLARE_ZONE_ID_JPCITE_COM       # apex + www + api subdomain
  CLOUDFLARE_ZONE_ID_ZEIMU_KAIKEI     # legacy redirect zone (rare to need during incident)
```

Confirm they're set before §3:

```bash
source ~/.jpcite_secrets.env
test -n "${CLOUDFLARE_API_TOKEN:-}" && test -n "${CLOUDFLARE_ZONE_ID_JPCITE_COM:-}"
```

## 3. Mitigation: DDoS / scraping flood

The order is "least disruptive first" — each step is a wider net.

### 3a. Tighten Security Level (60 sec to apply, mild user friction)

```bash
# Bumps the IP-reputation challenge threshold. "high" challenges Tor +
# anonymous proxies + low-reputation ASNs. Default is "medium".
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/settings/security_level" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"value":"high"}' | jq .

# Confirm.
curl "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/settings/security_level" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq .result.value
```

### 3b. Add a WAF rate-limit rule (60 sec — usually solves the targeted scrape)

For free plan: max 5 rate-limit rules per zone. Use 1 broad rule scoped
to the abused path.

```bash
# Example: cap each IP to 60 req/min on /v1/programs (typical scrape target).
curl -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/rulesets/phases/http_ratelimit/entrypoint/rules" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "expression": "(http.request.uri.path matches \"^/v1/programs\")",
    "action": "block",
    "ratelimit": {
      "characteristics": ["ip.src"],
      "period": 60,
      "requests_per_period": 60,
      "mitigation_timeout": 600
    },
    "description": "abuse-mitigation-2026-05-07-v1-programs"
  }' | jq .
```

For wider patterns, adjust `expression` (any Cloudflare Ruleset Language
predicate works):

* All API endpoints: `expression: "(http.request.uri.path matches \"^/v1/\")"`
* Site only: `expression: "(http.host eq \"jpcite.com\")"`

### 3c. Block the offending ASN / country (when 3a/3b insufficient)

```bash
# Block AS1234 (replace with the offending ASN from §1a).
curl -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/firewall/access_rules/rules" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "block",
    "configuration": {"target":"asn","value":"AS1234"},
    "notes": "abuse-mitigation-2026-05-07-asn-block"
  }' | jq .

# Country block (last resort — collateral damage on legitimate users):
#   "configuration": {"target":"country","value":"CN"}
```

### 3d. Engage Under Attack mode (last resort — affects all visitors)

Under Attack mode shows a 5-second JavaScript challenge to **every** visitor.
It defeats most botnets but breaks API access (clients without JS are blocked).

```bash
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/settings/security_level" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"value":"under_attack"}' | jq .
```

**Critical caveat**: Under Attack mode breaks `api.jpcite.com` API
clients (curl / SDK / MCP). Apply ONLY to `jpcite.com` (site) when the
attack vector is the static site — for an API-targeted attack, stick with
3a–3c. To scope Under Attack to the site only, on free plan, use a
**Page Rule** matching `jpcite.com/*` with "Security Level: I'm Under
Attack" rather than the global zone setting.

## 4. Mitigation: credential stuffing / API abuse

Different shape — distributed, slow, hits authentication / API-key
endpoints. The §3a–§3c WAF rules still apply, plus app-layer
tightening:

```bash
# 4a. Confirm anonymous-tier rate limit is enforcing. Logs should show
#     "anon_ip_quota_exceeded" returning 429 to the suspicious IPs.
flyctl logs -a autonomath-api -n 500 | grep "anon_ip_quota_exceeded" | wc -l

# 4b. If many distinct IPs are individually under the 3 req/day limit but
#     collectively flooding (slowloris / botnet pattern), tighten the
#     anonymous limit at the app layer. Adjust JPINTEL_ANON_IP_DAILY_LIMIT
#     temporarily.
flyctl secrets set JPINTEL_ANON_IP_DAILY_LIMIT=1 -a autonomath-api
# (Default is 3. Lower to 1 during the active incident; restore after.)

# 4c. Lock down API-key creation (turnstile re-CAPTCHA) — applies if the
#     attack is creating throwaway API keys.
flyctl secrets set JPINTEL_REQUIRE_TURNSTILE_FOR_KEY_ISSUE=true -a autonomath-api

# 4d. Audit recent api_keys table for suspicious creation patterns.
flyctl ssh console -a autonomath-api
sqlite3 /data/jpintel.db <<'SQL'
SELECT created_at, customer_id, api_key_id_prefix
FROM api_keys
WHERE created_at >= datetime('now', '-1 hour')
ORDER BY created_at DESC;
SQL
exit
```

## 5. Verify (every mitigation must complete this)

```bash
# 5a. Cloudflare event volume drops below baseline.
#     Dashboard → Security → Events → "Last 15 min" should show < 100 blocked
#     requests if 3a–3c were enough; otherwise repeat the §1a triage.

# 5b. Origin recovers.
flyctl metrics cpu_used_seconds_total -a autonomath-api -p 5m
# CPU should drop back below 50%.
curl -fsS --max-time 30 https://api.jpcite.com/v1/am/health/deep | jq .
# 200 + all "ok".

# 5c. Legitimate traffic still works (smoke from a clean IP).
curl -fsS https://api.jpcite.com/v1/programs?q=ものづくり&limit=5 | jq '.items | length'
# Expect: 5

# 5d. Anonymous rate limit still enforces (call 4 times from one IP, expect 4th = 429).
for i in 1 2 3 4; do
  curl -s -o /dev/null -w "%{http_code}\n" https://api.jpcite.com/v1/programs?q=test
done
# Expect: 200, 200, 200, 429
```

## 6. Capacity confirmation (when the spike was legitimate)

If §1 disambiguation showed a legitimate burst (HN front page / Twitter), the
correct response is **not** to engage WAF — engaging it punishes legitimate
viewers. Instead:

```bash
# 6a. Confirm Fly origin has headroom.
flyctl metrics memory_used_bytes -a autonomath-api -p 15m
flyctl metrics cpu_used_seconds_total -a autonomath-api -p 15m
# If memory or CPU > 80% sustained, follow docs/runbook/fly_machine_oom.md
# §5 to scale up rather than throttle.

# 6b. Cloudflare cache hit ratio.
#     Dashboard → Analytics → Cache → Hit ratio. For static site
#     (jpcite.com/*), expect > 80% during traffic burst.
#     For API (api.jpcite.com/*), cache is intentionally near-zero.

# 6c. Document the burst in CHANGELOG so future incidents disambiguate
#     faster from prior baselines.
```

## 7. Rollback

After the incident is over (no new abuse for 60 min):

```bash
# 7a. Restore Security Level.
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/settings/security_level" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"value":"medium"}' | jq .

# 7b. Remove temporary rate-limit rule (the one with the abuse-mitigation
#     description from §3b).
curl "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/rulesets/phases/http_ratelimit/entrypoint" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq '.result.rules[] | select(.description|startswith("abuse-mitigation")) | .id'
# DELETE each id:
curl -X DELETE "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID_JPCITE_COM/rulesets/phases/http_ratelimit/entrypoint/rules/<rule-id>" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"

# 7c. Restore app-layer settings (if §4b/§4c were touched).
flyctl secrets unset JPINTEL_ANON_IP_DAILY_LIMIT -a autonomath-api
flyctl secrets unset JPINTEL_REQUIRE_TURNSTILE_FOR_KEY_ISSUE -a autonomath-api
# (Re-set explicit defaults if the env baseline differs — see fly.toml.)

# 7d. ASN / country blocks: keep for 30 days then re-evaluate. Most abuse
#     ASNs are reused; aggressive removal courts re-attack.
```

## 8. Post-incident

Within 24 h:

* Append `tools/offline/_inbox/incidents/cloudflare_abuse_<yyyy-mm-dd>.md`:
  trigger, attack shape, mitigation steps actually applied, customer
  impact, time-to-mitigation, follow-up rule additions.
* If the same ASN appears 2+ times in a quarter, promote the 30-day block
  to permanent.
* If a new pattern matched no existing alert rule, open a PR adding the
  rule to `monitoring/sentry_alert_rules.yml`.
* Quarterly: review all "abuse-mitigation-*" Cloudflare rules — anything
  > 90 days old without recurrence should be removed to keep the 5-rule
  free-plan budget for future incidents.

## 9. Failure modes

* **Cloudflare token revoked / expired**: §3 commands all fail with 401.
  Mint a new token per `docs/runbook/cloudflare_redirect.md` §1, with the
  expanded scopes from §2.
* **Free plan rate-limit rule cap (5) hit**: must delete an old
  abuse-mitigation rule to add a new one. Pick the oldest by description
  date. If all 5 are active legitimate rules, escalate to Cloudflare Pro
  (¥3000/mo) or use IP Access Rules (no count cap) instead.
* **Under Attack mode breaks API customers**: scoped Page Rule didn't
  apply or operator forgot to scope. Roll back §3d immediately.
* **Origin (Fly) crashed during attack**: §3 steps don't recover the
  origin — that's `docs/runbook/fly_machine_oom.md`. Run §3 to stop new
  load **and** the OOM runbook to recover the machine, in parallel.
* **Cloudflare itself degraded**: rare. The `tls-check.yml` workflow
  detects Cloudflare edge issues weekly. During an active CF outage, Fly
  origin sees direct traffic — block at Fly's machine firewall via
  `flyctl ips list` and Fly's IP allowlist API as a last resort.

## 10. Items needing user action (one-time prerequisites)

* `CLOUDFLARE_API_TOKEN` minted with the §2 expanded scopes
  (`Zone.WAF:Edit` etc.) and stored in `~/.jpcite_secrets.env` (chmod 600).
* `CLOUDFLARE_ZONE_ID_JPCITE_COM` captured per
  `docs/runbook/cloudflare_redirect.md` §2 procedure.
* Cloudflare → Notifications → ensure DDoS + WAF events email
  `info@bookyou.net`.
* Sentry rules `cloudflare_ddos_detected` and `cloudflare_abuse_pattern`
  registered in `monitoring/sentry_alert_rules.yml` with this runbook
  as the destination.
* UptimeRobot monitor for `api.jpcite.com/v1/health` configured at 60s
  interval (faster than the default 5m to catch sub-minute outages).
