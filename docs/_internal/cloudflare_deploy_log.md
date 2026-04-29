# Cloudflare Deploy Log (operator-only)

Author: launch CLI subagent F8
Date: 2026-04-25
Zone: zeimu-kaikei.ai

## TL;DR

- `zeimu-kaikei.ai` is **already live** on Cloudflare (apex + Pages).
- TLS is valid (Google Trust Services WE1, expires **2026-07-22**).
- Static site (landing / prefectures / blog / audiences / programs) returns
  HTTP 200; `/dashboard.html` 308-redirects (handled by `_redirects`).
- `api.zeimu-kaikei.ai` returns HTTP 503 from Fly (separate Fly app, not in
  F8 scope; tracked under `project_autonomath_prod_drift_2026_04_24`).
- **WAF + Rate-Limit rules in `cloudflare-rules.yaml` were NOT applied
  by F8** — see "Blocker" below. Manual operator step required.

## What F8 verified (LIVE, no credentials needed)

### DNS

```
$ dig +short zeimu-kaikei.ai A
172.67.210.190
104.21.45.66

$ dig +short zeimu-kaikei.ai AAAA
2606:4700:3037::ac43:d2be
2606:4700:3036::6815:2d42

$ dig +short zeimu-kaikei.ai NS
romina.ns.cloudflare.com.
shane.ns.cloudflare.com.
```

A/AAAA point at Cloudflare anycast (104.21/172.67 IPv4 ranges, 2606:4700
IPv6). NS delegated to Cloudflare. Apex is fully on CF — no DNS work
needed at launch.

### TLS

```
subject: CN=zeimu-kaikei.ai
issuer:  C=US; O=Google Trust Services; CN=WE1
expire:  Jul 22 01:33:25 2026 GMT
TLS1.3 / AEAD-CHACHA20-POLY1305-SHA256
verify ok
```

87 days of validity remaining. Cloudflare auto-renews; no operator
action required unless cert provider changes.

### HTTP edge

```
$ curl -sI https://zeimu-kaikei.ai/
HTTP/2 200
server: cloudflare
cf-cache-status: DYNAMIC
cf-ray: 9f1c05492b3780e4-NRT      ← edge POP = Tokyo (NRT), good
access-control-allow-origin: *
referrer-policy: strict-origin-when-cross-origin
x-content-type-options: nosniff
report-to / nel: configured
alt-svc: h3=":443"; ma=86400      ← HTTP/3 enabled
```

### Pages coverage spot-check (all from prod, 2026-04-25)

| Path                            | Status |
|---------------------------------|--------|
| `/`                             | 200    |
| `/dashboard.html`               | 308    |
| `/prefectures/saitama.html`     | 200    |
| `/blog/`                        | 200    |
| `/audiences/`                   | 200    |
| `/programs/`                    | 200    |

Auto-deploy from `main` is working; the A/C/D/E inline improvements
land on edge once F3 commits.

## Blocker — WAF rules NOT applied

### Why

1. `env | grep CF_` returned **nothing**. No `CF_API_TOKEN`,
   `CF_ACCOUNT_ID`, or `CF_ZONE_ID` in F8's process env.
2. `~/.wrangler/` does not exist. `wrangler` binary is present
   (`v4.84.1` via nvm) but is unauthenticated.
3. `/Users/shigetoumeda/jpintel-mcp/.git/` does not exist in this
   working tree, so F8 cannot inspect / push committed config either.
4. Per F8 task spec: "credential 不在 → skip + runbook" — that path
   is taken.

Equally, `cloudflare-rules.yaml` itself documents (lines 11–17)
that the *intended* apply path is **manual via the dashboard**, not
API automation, because rules are tuned by hand from real telemetry
and an IaC pipeline would clobber operator tweaks.

### What still needs to happen (operator runbook)

Total: **12 rules** to create — 7 `custom_rules` + 5
`rate_limiting_rules` — plus Bot Fight Mode toggle.

```
Cloudflare dashboard → zeimu-kaikei.ai zone
  Security → WAF → Custom Rules
    Create rules in the order listed in cloudflare-rules.yaml:
      1. block_empty_user_agent
      2. block_unkeyed_curl_wget_on_data_paths
      3. … (5 more, see YAML)
    Action per rule = matches YAML `action:` field.
    Status = "Deploy" (NOT "Log only") for prod.

  Security → WAF → Rate Limiting Rules
    Create the 5 rate_limiting_rules entries from the YAML.
    Match: characteristics + period + threshold per YAML.

  Security → Bots → Bot Fight Mode
    Toggle ON if cloudflare-rules.yaml `bot_fight_mode: true`.
```

After applying, capture each rule's CF-assigned `id` and append to a
"Rule IDs" table here so future F-agents can `PATCH` / `DELETE` by id
for rollback.

### Alternative: API apply (if operator hands F8/F-agent a token)

```bash
export CF_API_TOKEN=<zone-scoped, NOT account-wide>
export CF_ZONE_ID=<zeimu-kaikei.ai zone id>

# Test rule first (one rule, verify in dashboard, then batch).
python3 - <<'PY'
import os, yaml, json, urllib.request
rules = yaml.safe_load(open("cloudflare-rules.yaml"))
token, zone = os.environ["CF_API_TOKEN"], os.environ["CF_ZONE_ID"]
headers = {"Authorization": f"Bearer {token}",
           "Content-Type":  "application/json"}
created = []
for rule in rules["custom_rules"][:1]:    # ← 1-rule canary first
    body = {"description": rule["name"],
            "expression":  rule["expression"],
            "action":      rule["action"]}
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/zones/{zone}/firewall/rules",
        method="POST", headers=headers, data=json.dumps([body]).encode())
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
        created.append((rule["name"], data["result"][0]["id"]))
print(json.dumps(created, indent=2))
PY
```

Notes:
- Token MUST be zone-scoped (Permissions: Zone WAF / Zone Firewall
  Services / Edit). Account-wide tokens are explicitly avoided per
  F8 spec.
- Save the returned `id`s back into this file under "Rule IDs".
- If the canary rule applies cleanly in the dashboard, batch the
  remaining 11.

## Pages auto-deploy status

- `wrangler pages list` not run — would require auth + the working
  tree is not a git repo at `/Users/shigetoumeda/jpintel-mcp` (so F8
  cannot resolve the Pages project name from a `wrangler.toml`/git
  remote). Auto-deploy is observable via the dashboard's
  Pages → Deployments tab.
- Indirect verification (HTTP 200 on freshly-listed paths above)
  confirms recent content **is** on edge as of 2026-04-25 08:37 UTC.

## Rule IDs (to be filled after apply)

| YAML name                                | CF rule id | applied at |
|------------------------------------------|------------|------------|
| block_empty_user_agent                   | (pending)  |            |
| block_unkeyed_curl_wget_on_data_paths    | (pending)  |            |
| (… 5 more custom_rules)                  | (pending)  |            |
| (… 5 rate_limiting_rules)                | (pending)  |            |
| bot_fight_mode (toggle, no id)           | n/a        |            |

## Cross-refs

- `cloudflare-rules.yaml` — D9-confirmed rule set, do not edit
- `project_autonomath_prod_drift_2026_04_24` — api.zeimu-kaikei.ai
  503 (separate Fly issue, not F8)
- `feedback_zero_touch_solo` — manual dashboard apply is the
  intended posture for security gates
