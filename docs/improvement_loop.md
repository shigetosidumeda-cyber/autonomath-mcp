# AutonoMath — Post-Launch Improvement Loop

**Owner:** 梅田茂利, info@bookyou.net (Bookyou株式会社)
**Constraint set:** Solo + zero-touch ops, 100% organic acquisition, ¥3/req metered only, no paid tooling beyond GitHub + email + Stripe + Fly + CF.
**Time budget:** 4–6 h/week (hard cap: 6 h/week per operator memory).

---

## 1. The Weekly Loop

One calendar cadence, fully mechanical once running.

### Monday 09:00 JST — Digest fires

```
weekly_digest.py runs via GitHub Actions (cron '0 0 * * 1' = Monday 09:00 JST)
→ Downloads last 7 days of Cloudflare R2 telemetry archives
→ Runs standard queries (zero-result rate, P95 latency, error rate, top queries, new API keys)
→ Emails plain-text report to info@bookyou.net via Postmark
```

Operator reads digest in under 30 min. Identify ≤5 signals worth acting on. If nothing actionable, skip to Friday.

### Monday 10:00 JST — Issue triage

Convert each signal to a GitHub Issue using the templates in `.github/ISSUE_TEMPLATE/signal_*.md` (see Section 4). Each Issue gets:
- **Title:** the signal in plain Japanese or English (e.g. "zero-result burst: 令和7年度 農業次世代投資資金")
- **Body:** paste the digest evidence block verbatim
- **Label:** exactly one of `bug | perf | data-gap | docs-gap | feature-request | abuse | growth-opp`
- **Priority label:** `PC0 | PC1 | PC2 | PC3 | PC4` (see Section 2)

Time budget: 30 min. If Issue creation takes longer, the signal is too vague — close it, log the query, revisit next week.

### Monday 11:00 JST – Friday 17:00 JST — Fix window

Work Issues in strict priority order (PC0 first). Each fix:

```
branch → code change → ruff + pytest pass → PR → CI green → merge → auto-deploy
```

Never squash priority. A PC0 blocks everything else until resolved.

### Friday 17:00 JST — Weekly publish + community

```bash
# 1. Confirm what shipped
gh pr list --state merged \
  --search "merged:>$(date -v-7d +%Y-%m-%d)" \
  --json title,url,labels

# 2. Publish blog post (auto-deploys via Cloudflare Pages)
#    File: site/blog/YYYY-MM-DD-week-N.md
#    Template: see Section 6

# 3. Reply to any open GitHub / Zenn comments (cap: 30 min total)
```

---

## 2. Priority Framework

### 5-Level Scale

| Level | Scope | SLA | Example |
|-------|-------|-----|---------|
| **PC0** | Broken for a paying customer — billing, auth, data returning wrong result for a paid key | **4 hours** | Stripe webhook failure; paid key returns 401 |
| **PC1** | Broken for anonymous tier or a vocal named user; widespread 5xx | **24 hours** | Zero-result rate > 30% site-wide; error in a public Zenn comment with repro |
| **PC2** | Degraded perf or zero-results on 中核 use cases (農業・建設・製造 subsidies) | **1 week** | P95 > 2000 ms on /v1/programs/search; invoice_registrants still empty |
| **PC3** | Data gap where user is blocked but has a workaround | **2 weeks** | A prefecture has < 5 programs; a court_decisions query returns 0 rows |
| **PC4** | Feature requests, long-tail polish, nice-to-haves | **Next quarter batch** | New export format; additional filter enum value |

### Decision Tree

When a signal arrives:

```
(a) Does it affect a paying API key?
    YES → PC0 (billing/auth/data wrong) or PC1 (degraded but not broken)
    NO  ↓

(b) Does it block a common query class?
    (run: SELECT query, COUNT(*) FROM zero_result_log GROUP BY query ORDER BY COUNT DESC LIMIT 10)
    TOP-10 HIT → PC1 or PC2
    LONG-TAIL → PC3
    NO  ↓

(c) Is it polish/feature/cosmetic?
    YES → PC4
```

When in doubt between two levels, assign the higher (more urgent) one. Downgrade later if the week is already full of PC0/PC1 work.

---

## 3. Signal Sources

Three channels. Everything eventually becomes a GitHub Issue.

### 3.1 Telemetry (autonomath.query log → Cloudflare R2)

Surfaced every Monday by `weekly_digest.py`. Key signals:

| Signal | Threshold | Action |
|--------|-----------|--------|
| Zero-result query rate | > 20% 7-day avg | Check data-gap heuristics (Section 5) |
| P95 latency `/v1/programs/search` | > 1500 ms | PC2 perf issue |
| 5xx error rate | > 1% | PC1 |
| New API keys registered | Flat for 4 weeks | Distribution review (see Section 8) |
| Specific query repeated ≥ 10× with 0 results | Any single query | PC2/PC3 data gap |

### 3.2 Direct User Feedback

- **Email** to info@bookyou.net — treat as PC1 unless clearly a feature request (PC4)
- **GitHub Issues** on this repo — already structured; apply priority label on receipt
- **Zenn comments** on published articles — check every Monday morning before triage
- **HN / X / Reddit** — check if any mention "AutonoMath" or "autonomath-mcp"; use organic search (no paid monitoring)

### 3.3 External Monitoring (always-on, non-weekly)

| Source | What it catches | Response |
|--------|-----------------|----------|
| Sentry | New error classes, unhandled exceptions | PC0/PC1 depending on paying-customer impact |
| Fly.io alerts | Machine count = 0, OOM, deploy failure | PC0 immediately |
| Stripe webhook failures | Payment processing down | PC0 immediately |
| UptimeRobot / Fly health check | `/healthz` failing | PC0 immediately |
| TLS/cert expiry | Certificate approaching expiry | PC2 (schedule renewal before expiry) |

These fire outside the weekly cadence. PC0 incidents interrupt everything.

---

## 4. Signal → Issue Conversion Templates

Five templates cover 90% of recurring signal types. Each is a Markdown file dropped into `.github/ISSUE_TEMPLATE/`. GitHub renders them as guided forms for Issues created manually; for operator-created Issues from digest output, paste the relevant sections from the template body.

Templates created at `.github/ISSUE_TEMPLATE/`:

- `signal_zero_result.md` — query returns 0 results consistently
- `signal_latency.md` — P95 latency regression
- `signal_billing.md` — Stripe webhook or checkout failure
- `signal_sentry.md` — new Sentry error class appearing N+ times
- `signal_user_feedback.md` — email or Zenn/HN comment originated

See the template files for full field lists. The key discipline: **paste the digest SQL row verbatim** in the "Evidence" field so the Issue is self-contained.

---

## 5. Data-Gap Detection Heuristics

Run these SQL one-liners directly against `data/jpintel.db` when the digest shows a zero-result burst. Each maps a query pattern to a specific gap and a suggested priority.

### H1 — 法人番号 with 0 results → invoice_registrants not loaded

```sql
-- Any query term matching the 13-digit 法人番号 pattern returning 0 results
SELECT q.query, COUNT(*) AS hits
FROM zero_result_log q
WHERE q.query REGEXP '^[0-9]{13}$'
GROUP BY q.query
ORDER BY hits DESC
LIMIT 10;
-- If hits > 10: invoice_registrants table is 0 rows (schema ready, data load pending)
-- Action: PC2 — load PDL v1.0 国税庁 適格事業者 bulk; see docs/canonical/
```

### H2 — 令和 + year with 0 results → deadline data stale

```sql
SELECT q.query, COUNT(*) AS hits
FROM zero_result_log q
WHERE q.query LIKE '%令和%'
GROUP BY q.query
ORDER BY hits DESC
LIMIT 20;
-- If hits > 10 for a specific 令和N年度: check search_deadlines has rows for that year
SELECT MIN(deadline_date), MAX(deadline_date) FROM deadlines;
-- Action: PC2 if current 令和 year is absent from deadlines table
```

### H3 — 自治体 with < 5 programs → prefecture data gap

```sql
SELECT p.prefecture, COUNT(*) AS cnt
FROM programs p
WHERE p.excluded = 0 AND p.tier IN ('S','A','B','C')
  AND p.prefecture IS NOT NULL
GROUP BY p.prefecture
HAVING cnt < 5
ORDER BY cnt ASC;
-- Cross-reference against zero_result_log for those prefectures
-- Action: PC3 if the 自治体 appears in zero_result_log ≥ 10 times
```

### H4 — 農業 subcategory with 0 results → crop_categories gap

```sql
-- Queries mentioning specific crop names that appear ≥ 10× with 0 results
SELECT q.query, COUNT(*) AS hits
FROM zero_result_log q
WHERE q.query LIKE '%作%' OR q.query LIKE '%園%' OR q.query LIKE '%畜%'
GROUP BY q.query
HAVING hits >= 10
ORDER BY hits DESC;
-- Action: PC3 — check if that crop_category enum value exists in programs table
```

### H5 — court_decisions or bids with 0 results → expansion tables empty

```sql
SELECT 'court_decisions' AS tbl, COUNT(*) AS rows FROM court_decisions
UNION ALL
SELECT 'bids', COUNT(*) FROM bids;
-- If 0 rows and digest shows queries for 判例 or 入札: PC2 data load
```

---

## 6. Growth-Loop Integration

The improvement loop IS the marketing. Public evidence of quality compounds over time.

### Weekly Cadence

| Day | Activity | Time budget |
|-----|----------|-------------|
| Monday | Reply to open GitHub Issues + Zenn comments (from previous week) | 30 min (part of triage hour) |
| Wednesday | If a significant fix shipped (PC0/PC1), post 1 tweet/toot organically — link to the commit or blog draft | 10 min |
| Friday | Publish "shipped this week" blog post (see template below) | 30 min |
| First Friday of month | Publish monthly retrospective — 1-page: what changed, what signals drove it, what's next | 60 min |

**No paid promotion, no cold outreach, no newsletters to external lists.** The blog post URL is the only distribution channel.

### Weekly Blog Post Template

File: `site/blog/YYYY-MM-DD-week-N.md`

```markdown
---
title: "Week N — AutonoMath 改善ログ"
date: YYYY-MM-DD
---

## 今週対応したシグナル

- [PC0/PC1] ... (リンク to merged PR)
- [PC2] ...

## データ追加

- 追加したプログラム数 / 修正した source_url 数

## 来週の予定

- 上位未解決シグナル ≤ 3件

---
*AutonoMath は ¥3/リクエスト従量課金の日本語公的制度データベースAPI。[ドキュメント →](https://autonomath.ai/docs)*
```

This generates indexed public changelogs that LLMs and search engines can cite — the GEO/SEO compounding effect.

### Growth Signal to Watch

Weekly: **unique API key count** + **MCP install count** (from PyPI download stats + MCP registry download counters).

```bash
# API keys registered this week
sqlite3 data/jpintel.db \
  "SELECT COUNT(*) FROM api_keys WHERE created_at > datetime('now', '-7 days');"

# PyPI weekly downloads (via pypistats)
pip install pypistats && pypistats recent autonomath-mcp --format json
```

**If both metrics are flat for 4 consecutive weeks:** the bottleneck is distribution, not product quality. Pause the feature improvement loop. Publish a deeper Zenn article or update the MCP registry descriptions. Do NOT add features until traffic resumes.

---

## 7. Minimum Viable Operator Time

**Target: 5.5 h/week. Hard cap: 6 h/week.**

| Phase | Day | Time |
|-------|-----|------|
| Digest read + triage (≤5 signals) | Monday AM | 30 min |
| GitHub Issue creation | Monday AM | 30 min |
| Fix top 3 Issues (avg PC2 fix ~80 min each) | Mon–Fri | 4 h |
| Weekly blog post (shipped this week) | Friday PM | 30 min |
| Community replies (GitHub/Zenn) | Monday AM | 30 min |
| **Total** | | **5.5 h** |

### Efficiency Rules

1. **PC4 items never enter the active week.** Batch them into a quarterly sweep (label + close with "next quarter" comment). This protects the 4 h core fix window.
2. **No Issue gets more than 2 h without a check-in decision.** If a fix is taking longer, timebox it: ship a workaround (e.g. a friendlier error message), open a follow-up Issue, and move on.
3. **The digest is the only input to triage.** Do not respond to signals mid-week that aren't already in the digest unless they are PC0. Everything else waits for Monday.
4. **No async collaboration tools.** GitHub Issues is the only coordination surface. No Notion, no Linear, no Jira.

---

## 8. Kill / Pause Criteria

Three hard stops. If any trigger, normal loop work halts.

### K1 — Time overrun: operator burning out

**Trigger:** Loop consumes > 8 h/week for 3 consecutive weeks.
**Action:** Immediately cut all PC4 from active backlog. Re-score remaining Issues. If still > 8 h after cutting PC4, cut PC3 as well. The loop should return to ≤ 6 h before resuming normal cadence.

### K2 — Zero signal volume: traffic too low to iterate

**Trigger:** Digest shows < 5 unique external queries/day for 4 consecutive weeks (i.e., traffic is almost entirely synthetic/test).
**Action:** Pause the improvement loop. Dedicate the 5.5 h/week to distribution instead:
- Publish a new Zenn article targeting a specific use case
- Update MCP registry descriptions + keywords
- Refresh the `llms.txt` / `llms-full.txt` so LLM crawlers index updated capability statements
- Do NOT add features. Revisit positioning.

### K3 — PC0 incident exceeds 24 h

**Trigger:** A PC0 issue (paying-customer impact) is not resolved within 24 hours from detection.
**Action:** Stop all non-PC0 work immediately. Diagnose the structural cause (not just the symptom). Document the root cause in `docs/_internal/incident_runbook.md`. The fix must include a prevention mechanism — not just a patch. Resume normal loop only after the prevention is merged and deployed.

---

## Appendix: Stack Reference

All tooling is already in the stack. No new services required.

| Tool | Role in loop |
|------|-------------|
| GitHub Actions | Runs `weekly_digest.py` on cron `0 0 * * 1` (Mon 09:00 JST) |
| Postmark | Delivers digest email to info@bookyou.net |
| Cloudflare R2 | Stores 7-day rolling telemetry archives |
| DuckDB (in digest script) | Aggregates telemetry queries without loading into SQLite |
| Sentry | Real-time error alerting (PC0/PC1) |
| Fly.io alerts | Machine health (PC0) |
| Stripe Events API | Webhook failure rate (PC0) |
| Cloudflare Pages | Auto-deploys blog posts on merge to `main` |
| GitHub Issues | Only backlog surface. Labels: `bug`, `perf`, `data-gap`, `docs-gap`, `feature-request`, `abuse`, `growth-opp`, `PC0`–`PC4` |
| `gh` CLI | Friday shipped-this-week query (see Section 1) |
| `pypistats` | Weekly MCP install count proxy |

---

*Last updated: 2026-04-24. Operator: 梅田茂利 / Bookyou株式会社 / info@bookyou.net*
