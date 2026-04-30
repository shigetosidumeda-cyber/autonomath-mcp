# jpcite — Solo Ops Handoff

**Audience**: 1-day successor (post-Scenario-10 deadman trigger). Read top-to-bottom, run the 20 procedures as needed, ship the next deploy without help.

**Confidentiality**: Internal-only. Do **not** publish to docs.jpcite.com. No secret values are written here — only secret *names* and *locations*. Actual values live in 1Password (vault: `bookyou-autonomath-prod`) and Fly Secrets.

最終更新: 2026-04-25 · Operator: 梅田茂利 (info@bookyou.net) · Entity: Bookyou株式会社 (T8010001213708) · Launch: 2026-05-06

---

## 0. First-30-minutes orientation

1. You received this doc because the deadman switch fired (no operator check-in for ≥2 weeks). 1Password emergency-access invite should be in your inbox. Accept it.
2. Read in order: `CLAUDE.md` (architecture truth), `docs/disaster_recovery.md` (RPO/RTO + Scenario 10 path), this doc (procedures).
3. Decide stance: **continue ops** / **freeze billing & maintain** / **wind down with refund**. The decision criteria are at §20.
4. If continuing: run procedure §1 (verify access) and §2 (smoke test) before doing anything else.

---

## 1. Verify access (do this first)

```bash
# Local dev box
git clone <repo> autonomath && cd autonomath
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Fly access (1Password → "Fly.io API token (autonomath-api)")
flyctl auth token
flyctl status --app autonomath-api          # must return non-error

# Cloudflare access (1Password → "Cloudflare API token (jpcite.com)")
# Verify via dashboard login, not API — we don't ship tokens to dev boxes.

# Stripe live access (1Password → "Stripe Restricted Key (live, read-only)")
stripe customers list --limit 1 --live      # 1 row = OK
```

If any of the above fail, stop and email Bookyou KK 税理士 (§19) — access recovery may require legal entity-side action.

---

## 2. Daily smoke (1 minute)

```bash
BASE_URL=https://api.jpcite.com ./scripts/smoke_test.sh
curl -s https://api.jpcite.com/meta | jq '.total_programs, .build_sha, .last_ingest_at'
curl -sI https://jpcite.com/                         # Cloudflare Pages 200
curl -sI https://api.jpcite.com/healthz              # Fly 200
```

All four must return 2xx. If any fail, jump to `docs/_internal/incident_runbook.md`.

---

## 3. Deploy: API (Fly.io)

```bash
git checkout main && git pull
ruff check src/ tests/ && .venv/bin/pytest && mypy src/  # quality gates
flyctl deploy --app autonomath-api --strategy rolling
flyctl status --app autonomath-api                       # confirm new release
BASE_URL=https://api.jpcite.com ./scripts/smoke_test.sh
```

If smoke fails: `flyctl releases rollback <prev-id> --app autonomath-api`.

## 4. Deploy: site (Cloudflare Pages)

Auto-deploys on push to `main`. To force a rebuild: Cloudflare dashboard → Pages → `autonomath` → Deployments → Retry. Static `site/` folder is the source-of-truth; `mkdocs build --strict` runs in CI to populate `site/docs/`.

## 5. Deploy: regenerate per-program SEO pages

```bash
.venv/bin/python scripts/generate_program_pages.py
git add site/programs/ && git commit -m "site: regenerate program pages"
git push                                    # Cloudflare Pages picks it up
```

Run weekly or after any meaningful `programs` table mutation.

## 6. Deploy: PyPI release

1. Bump version in `pyproject.toml` AND `server.json` (must match).
2. Update `CHANGELOG.md`.
3. `git tag v0.x.y && git push --tags`.
4. `python -m build && twine upload dist/*` (PYPI_TOKEN in 1Password: `PyPI token (autonomath-mcp)`).
5. `mcp publish server.json` for MCP registry.

## 7. Stripe webhook health

Stripe dashboard → Developers → Webhooks → endpoint `https://api.jpcite.com/v1/billing/webhook`. Health = "Receiving events" + "0 failed events past 24h". If failures: see `_internal/incident_runbook.md` §(b).

## 8. Incident triage flow

1. Sentry alert email arrives → check Sentry dashboard.
2. Identify scenario id (1-9 in `docs/disaster_recovery.md`).
3. Run scenario runbook from `_internal/incident_runbook.md`.
4. Status update on `https://status.jpcite.com` (Cloudflare Worker, edit via `site/status.html`).
5. Customer email if customer-affecting > 5 min (§14 templates).
6. Post-mortem within 24 h (template in `disaster_recovery.md` §4).

## 9. Billing: dashboard tour

Stripe live dashboard:
- **Customers** → search by email → see subscription state + invoice history.
- **Subscriptions** → all `active` rows = paying customers. `past_due` > 3 = chase week.
- **Reports** → MRR / Churn / Net volume — read-only sanity check.

Customer Portal: customers self-serve at `https://billing.stripe.com/p/login/<live_link>`. We do not log in on their behalf except during refund (§11).

## 10. Billing: per-request usage

Reported via `stripe.SubscriptionItem.create_usage_record()` from `src/jpintel_mcp/billing/usage.py`. Verify daily totals:

```bash
flyctl ssh console -a autonomath-api -C \
  'sqlite3 /data/jpintel.db "SELECT date(ts), SUM(yen) FROM request_log WHERE ts > date(\"now\",\"-7 days\") GROUP BY date(ts);"'
```

Stripe usage records ≈ this sum within 1% (lag from queue). If divergence > 5%: run `scripts/replay_stripe_usage.py`.

## 11. Refund / dispute

- **Refund**: Stripe dashboard → Payments → search by customer → Refund. Always partial (prorated against month-to-date) unless §7 leak case.
- **Dispute (chargeback)**: Stripe emails you. Respond within 7 d via dashboard → Disputes → Submit evidence: invoice PDF + usage records + ToS acceptance log.

## 12. DB recovery

See `docs/disaster_recovery.md` §Scenario 2. Critical: SHA256 verify before swap.

## 13. autonomath.db rebuild (if needed)

`autonomath.db` (8.29 GB) is read-only and rebuildable from raw sources in `data/raw/`. Procedure:

```bash
.venv/bin/python scripts/ingest/build_autonomath_db.py --output autonomath.db.new
sqlite3 autonomath.db.new "PRAGMA integrity_check;"   # must print "ok"
mv autonomath.db autonomath.db.bak.$(date +%Y%m%d) && mv autonomath.db.new autonomath.db
flyctl ssh sftp put autonomath.db /data/autonomath.db --app autonomath-api
flyctl apps restart autonomath-api
```

Rebuild time: ~6 h on a fast box. Do not run on production during business hours.

## 14. Customer comms templates

### Outage (customer-facing scenario, > 5 min)

```
Subject: [jpcite] サービス障害のお知らせ (YYYY-MM-DD)

ご利用のお客様へ

YYYY-MM-DD HH:MM JST より、API サービスに障害が発生し、HH:MM JST に復旧いたしました。
影響時間: <分>。原因: <一行>。対策: <一行>。
ご請求は障害時間中の利用分を除外して調整いたします (¥3/req metered のため、停止時間中は自動的に課金されません)。

ご迷惑をおかけし申し訳ございません。詳細は https://status.jpcite.com/postmortem/<id> に掲載いたします。

— Bookyou株式会社 / jpcite / info@bookyou.net
```

### Data issue (incorrect program info reported)

```
Subject: [jpcite] ご報告いただいた制度情報の修正完了

<お客様名> 様

ご報告いただいた <制度ID> の <フィールド> の誤りについて、一次資料 (<出典URL>) を再確認のうえ、YYYY-MM-DD に修正を反映いたしました。
キャッシュ反映まで最大 24h かかる場合があります。再度 API をお試しいただき、なお相違があればこのメールにご返信ください。

— Bookyou株式会社 / jpcite / info@bookyou.net
```

### Support (general inquiry, 48h SLA)

```
Subject: Re: <original>

ご連絡ありがとうございます。

<回答 / 解決手順>

なお、本サービスは solo operator 体制 (zero-touch) のため、深夜・週末の応答は遅延する場合があります。
緊急障害は https://status.jpcite.com/ をご確認ください。

— Bookyou株式会社 / jpcite / info@bookyou.net
```

## 15. Secret inventory (names only)

All values live in 1Password vault `bookyou-autonomath-prod`. Names below match Fly Secrets and `.env.example`.

| Secret name | Where used | 1Password item title | Rotation cadence |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | api/billing | Stripe Secret Key (live) | annual |
| `STRIPE_WEBHOOK_SECRET` | api/billing webhook | Stripe Webhook Secret (live) | annual |
| `STRIPE_PRICE_PER_REQUEST` | api/billing | Stripe Price ID per_request_v1 | n/a (price ID, not secret) |
| `STRIPE_BILLING_PORTAL_CONFIG_ID` | api/me | Stripe Billing Portal Config | n/a |
| `API_KEY_PEPPER` | api/auth | API Key Pepper (server-side hash) | annual or on-leak |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | backup cron | R2 IAM (autonomath-backups) | annual |
| `R2_ENDPOINT` | backup cron | R2 endpoint URL | n/a |
| `SENTRY_DSN` | api + mcp | Sentry DSN (autonomath prod) | n/a |
| `RESEND_API_KEY` | email service | Resend API Key | annual |
| `CLOUDFLARE_API_TOKEN` | DNS / Pages CI | Cloudflare API Token | annual |
| `FLY_API_TOKEN` | deploy | Fly.io Personal Access Token | annual |
| `PYPI_TOKEN` | release | PyPI token (autonomath-mcp) | annual |
| `MCP_REGISTRY_TOKEN` | release | MCP registry publisher token | annual |

DB backups: `s3://autonomath-backups/` (R2 nrt) + `s3://autonomath-backups-eu/` (R2 EU) + `s3://autonomath-backups-na/` (R2 NA). 90 d retention.

## 16. Domain / DNS / DNSSEC

- Registrar: Cloudflare Registrar (`jpcite.com`).
- Auto-renew: ON (verify card on file annually in November).
- DNSSEC: enabled (DS record at registrar). On rotation, re-publish DS — see Cloudflare KB.
- Defensive registrations (Y2 budget, not yet held): `.com`, `.app`, `.dev`. Acquire only if budget permits.

## 17. Emergency contacts

| Vendor | Channel | What for |
|---|---|---|
| **Stripe support (live mode)** | https://support.stripe.com → Login as `info@bookyou.net` → Create case (priority "Critical" only for outage / suspected fraud) | Webhook failures, payout holds, KYC re-verification |
| **Fly.io support (Tokyo region)** | https://fly.io/dashboard/support — paid plan = email priority. Free plan = community.fly.io | Region outages, volume corruption, hostname issues |
| **Cloudflare support** | https://dash.cloudflare.com → Support → Open ticket. Pages + DNS + R2 all under one account | Pages build failures, DNS hijack, R2 outage |
| **Anthropic (registry maintainer)** | mcp-registry@anthropic.com | MCP registry listing issues only |
| **Bookyou KK 税理士** | <Name>, <firm>, <phone>, <email> — see 1Password "Bookyou KK 顧問税理士" | 税務 / 給与 / 法人決算 / 解散手続 |
| **税務署 (文京税務署)** | 東京都文京区春日1-4-15, 03-3812-7151 | インボイス号変更、消費税届出 |
| **法務局 (東京法務局)** | 03-5213-1234 | 法人登記変更 (代表者変更、解散登記等) |

## 18. 法務 / Legal

- **特商法 (`site/tokushoho.html`)**: 必要に応じて住所・電話番号変更時に更新。8 必須項目は埋め済 (launch 前 lawyer review pass)。Updated by: ops.
- **プライバシーポリシー (`docs/compliance/privacy_policy.md`)**: 個人情報取扱事業者として要件遵守。GDPR equivalent 対応済 (data subject rights doc)。Updated by: ops, reviewed by lawyer once a year.
- **利用規約 (`docs/compliance/terms_of_service.md`)**: 改定は 30 日前メール通知必須 (規約自身に明記)。
- **電子帳簿保存法 (`docs/compliance/electronic_bookkeeping.md`)**: 領収書・請求書を Stripe Invoice + 自社保存 (R2 archive) で 7 年間保管。
- **Lawyer 連絡先**: <Name>, <firm>, <phone>, <email> — 1Password "jpcite 顧問弁護士". 着手金未支払、時間制 spot retainer。月次ではなく事案ベース。

## 19. Bookyou KK admin

- 適格請求書発行事業者番号: T8010001213708
- 登記住所: 東京都文京区小日向2-22-1
- 代表者: 梅田茂利 (本人不在時、株主総会で後継者選任)
- インボイス登録: 令和7年5月12日
- 決算月: TBD (税理士確認)
- 銀行口座: 1Password "Bookyou KK 法人口座" (Stripe payout 先と一致必須)

## 20. Stance decision tree (Scenario 10)

```
Did MRR > ¥1M sustained 60 d before incapacity?
├─ Yes → Continuing has positive cashflow
│   └─ Are you (successor) able to maintain ops part-time?
│       ├─ Yes → CONTINUE. Read CLAUDE.md fully, schedule weekly smoke.
│       └─ No  → Hire 1 contractor or sell to acquirer (§17 Anthropic / Fly community for buyer leads)
└─ No  → Cashflow likely negative within 90 d
    └─ Run scripts/wind_down.py:
        - Refund month-to-date for all active customers
        - Export customer data per data_subject_rights.md
        - Post 30-day shutdown notice on jpcite.com
        - File 法人解散 with 税理士
```

The decision must be made within 14 days of receiving deadman alert. Until decided: **freeze billing** (`flyctl secrets set STRIPE_FREEZE=1` — disables new usage records, existing customers see "サービス凍結中" 503 from billing path; reads still work).
