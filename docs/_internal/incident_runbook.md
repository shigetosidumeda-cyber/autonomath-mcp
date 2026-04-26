# Incident runbook — AutonoMath

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

Solo on-call. Blunt on purpose. Skim, act, verify.

Common prep (run first):

```bash
flyctl status --app AutonoMath
flyctl logs  --app AutonoMath | tail -200
flyctl releases --app AutonoMath | head -5
```

Roll-back anywhere below:

```bash
flyctl releases rollback <id> --app AutonoMath
```

---

## (a) 5xx spike on `/v1/programs/search`

**Symptom:** Sentry spike + UptimeRobot degraded + users tweet.

**Diagnose:**
1. Sentry: top frame. If `sqlite3.OperationalError: database is locked` → SQLite lock. If `TimeoutError` / `ReadTimeout` → Fly volume / disk stall.
2. `flyctl logs | grep -E 'OperationalError|status=5' | tail -50`.
3. `flyctl ssh console -a AutonoMath -C 'sqlite3 /data/jpintel.db "PRAGMA integrity_check;"'` — must print `ok`.

**Fix:**
```bash
# Restart the machine (drops long-held reader conns)
flyctl apps restart AutonoMath

# Re-smoke
BASE_URL=https://AutonoMath.fly.dev ./scripts/smoke_test.sh
```

Still 5xx after restart → roll back to last-known-good release id (see top).

**Verify:** p95 < 400 ms and Sentry rate back to baseline for 10 min.

---

## (b) Stripe webhook dead-lettering

**Symptom:** Stripe dashboard shows failing events for endpoint `https://<DOMAIN_PLACEHOLDER>/v1/billing/webhook`. Users pay but get no key.

**Diagnose:**
1. Stripe dashboard → Webhooks → endpoint → Recent events. Look at the error column.
2. Error `400 invalid signature` → `STRIPE_WEBHOOK_SECRET` on Fly does not match the `whsec_…` shown in Stripe UI.
3. Error `401 / 403` → endpoint URL drifted (e.g. domain change).
4. Error `5xx` → real bug; read Sentry, go to §(a).

**Fix (signature mismatch):**
```bash
# Pull current secret from Stripe dashboard, then:
flyctl secrets set STRIPE_WEBHOOK_SECRET=whsec_... --app AutonoMath
# (Deploys a new release automatically.)

# Replay the last hour of failed events from your dev box:
stripe events resend evt_xxx --live
# or trigger a small known event:
stripe trigger invoice.paid --live
```

**Verify:** Stripe dashboard → endpoint shows 2xx on the replay. One real paying user gets their API key.

---

## (c) DB corrupt / disk full

**Symptom:** `database disk image is malformed` OR `disk full` in logs. `/meta` returns 500.

**Diagnose:**
```bash
flyctl ssh console -a AutonoMath -C 'df -h /data'
flyctl ssh console -a AutonoMath -C 'sqlite3 /data/jpintel.db "PRAGMA integrity_check;"'
```

**Fix (restore from latest nightly — produced by `.github/workflows/nightly-backup.yml`):**

```bash
# 1. Stop traffic (scale to 0 so no writes happen during restore)
flyctl scale count 0 --app AutonoMath

# 2. Identify the current volume
flyctl volumes list --app AutonoMath

# 3. Download latest backup from Cloudflare R2 (bucket jpintel-backups)
aws s3 ls    s3://jpintel-backups/AutonoMath/ --endpoint-url $R2_ENDPOINT | sort | tail -3
aws s3 cp    s3://jpintel-backups/AutonoMath/<latest>.db.gz . --endpoint-url $R2_ENDPOINT
aws s3 cp    s3://jpintel-backups/AutonoMath/<latest>.db.gz.sha256 . --endpoint-url $R2_ENDPOINT
shasum -a 256 -c <latest>.db.gz.sha256
gunzip <latest>.db.gz

# 4. Create a fresh volume (same region), upload the restored DB to it
flyctl volumes create jpintel_data --region nrt --size 3 --app AutonoMath
flyctl ssh sftp shell --app AutonoMath
#   put <latest>.db /data/jpintel.db

# 5. Detach old broken volume via fly.toml (mounts source stays jpintel_data — fly picks newest)
#    Confirm by listing volumes; destroy old one only after §Verify passes.
flyctl scale count 1 --app AutonoMath
```

**Verify:**
```bash
curl -s https://AutonoMath.fly.dev/meta | jq .total_programs  # must match pre-incident
BASE_URL=https://AutonoMath.fly.dev ./scripts/smoke_test.sh
```

Then destroy the old volume (`flyctl volumes destroy <old-id>`).

---

## (d) API key leaked publicly

**Symptom:** Someone posts `sk_live_…` on GitHub / X / Discord. Or user emails saying their key was in a screenshot.

**Diagnose:** No diagnosis — you can see the key. Grab the first 8 chars for matching.

**Fix:**
```bash
flyctl ssh console --app AutonoMath
sqlite3 /data/jpintel.db
```

```sql
-- Confirm the key exists (key_hash is sha256 of the full key; match by prefix if user told you first 8 chars)
SELECT key_hash, key_prefix, tier, revoked_at FROM api_keys WHERE key_prefix = 'sk_live_';

-- Revoke
UPDATE api_keys SET revoked_at = datetime('now') WHERE key_hash = '<full_sha256_hash>';

-- Or by prefix if you only have the leaked snippet
UPDATE api_keys SET revoked_at = datetime('now') WHERE key_prefix = '<first_8_chars>';
```

Email the affected user (lookup via `customer_id` in same row → Stripe → email), tell them to rotate via `/v1/me/rotate-key`.

**Verify:**
```bash
curl -H "x-api-key: <leaked>" https://AutonoMath.fly.dev/v1/programs/search?q=a
# -> 401
```

---

## (e) DDoS / abuse spike

**Symptom:** Fly metrics: RPS jumps 10x+, CPU saturates. Logs dominated by one UA / ASN / country.

**Diagnose:**
```bash
flyctl logs --app AutonoMath | awk '{print $NF}' | sort | uniq -c | sort -rn | head -20
```

Identify: single IP / country / user-agent / ASN.

**Fix (Cloudflare firewall rule — UI → Security → WAF → Custom rules):**

Template (paste into expression editor, adjust, hit Deploy):

```
# Block by country
(ip.geoip.country in {"RU" "CN" "KP"})

# Block by ASN (spam bot farms)
(ip.geoip.asnum in {14061 63949})

# Block by UA
(http.user_agent contains "bad-bot-name")

# Challenge everything else hitting /v1/ for 1 hour
(http.request.uri.path contains "/v1/") and (not cf.client.bot)
# Action: Managed Challenge
```

Tighten the per-process rate limit as a stop-gap:

```bash
# Halve the free cap; paid tier は metered (hard cap なし) なので対象外
flyctl secrets set \
  RATE_LIMIT_FREE_PER_DAY=50 \
  --app AutonoMath
```

Paid tier は pure metered で `429` の選択肢がないため、ここでは絞れない。
Paid 側で abusive trafic が来たら個別 API key を `api_keys.revoked_at = NOW()`
で直接 revoke する (詳細は `docs/secrets_rotation.md` のキー revoke 節)。

Raise or disable the per-IP anon limit (e.g. tighten to 25 / IP / day, or
switch off entirely when a Cloudflare WAF rule above takes over):

```bash
# Tighten
flyctl secrets set ANON_RATE_LIMIT_PER_DAY=25 --app AutonoMath
# Or disable (the WAF now owns rate-limiting)
flyctl secrets set ANON_RATE_LIMIT_ENABLED=False --app AutonoMath
```

**Verify:** RPS drops to baseline within 2 min. Revert rate-limit secrets after storm.

---

## (f) Total Fly outage

**Symptom:** `flyctl status` hangs or returns `app unreachable`. Fly status page red. You cannot ssh, cannot deploy, cannot roll back.

**Fix — DNS flip to Cloudflare Pages static mirror** (see `docs/launch_war_room.md` D-4 CDN plan):

1. Cloudflare dashboard → `<DOMAIN_PLACEHOLDER>` → DNS.
2. Delete (or pause) the `A`/`AAAA` record pointing at Fly.
3. Add `CNAME <DOMAIN_PLACEHOLDER> -> jpintel-mirror.pages.dev`, proxied (orange cloud).
4. TTL was already set to 300 at T-3d, so propagation is < 5 min.

The static mirror serves landing + pricing. All API routes under `/v1/` and `/meta` return **HTTP 503** from a static `status.json` with a one-line "Fly.io outage, see <provider status>".

Post on X + pinned HN comment: "Upstream provider outage, static site up, API back when Fly recovers." Do not promise ETA.

**Verify:**
```bash
dig +short <DOMAIN_PLACEHOLDER>     # points at Cloudflare
curl -sI https://<DOMAIN_PLACEHOLDER>/ | head -3       # 200
curl -sI https://<DOMAIN_PLACEHOLDER>/v1/programs/search | head -3  # 503
```

When Fly recovers: flip DNS back, smoke, post recovery note.
