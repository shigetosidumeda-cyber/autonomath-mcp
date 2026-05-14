# Show HN: jpcite – one API for Japanese subsidy, loan, tax, certification data

## Post body

Japan has over 9,000 public-support programs across ministries, prefectures, and government banks — each published in a different format, on a different domain, with no common schema. Existing aggregator sites repackage this data without citing primary sources, mix stale entries with current ones, and bundle monetization schemes that create downstream legal exposure (景品表示法 / 消費者契約法). For AI agents the problem compounds: naïve scraping dies on 全角/半角 normalization quirks, SQLite FTS falls apart on single-kanji overlap, and tokenizer misbehavior turns `税額控除` searches into hits for `ふるさと納税`. No reliable machine-readable source exists. Engineers building agri-tech, regtech, or accounting agents end up scraping government PDFs by hand.

I built jpcite to fix this. It's a REST + MCP server (151 tools, protocol 2025-06-18) backed by two SQLite files — a 188 MB programs/laws DB and a 7.3 GB entity-fact companion. Coverage: 9,998 programs (補助金・融資・税制・認定), 2,286 adoption case studies, 108 loan programs with three-axis decomposition (担保 / 個人保証人 / 第三者保証人 each as independent enums), 1,185 enforcement cases, and 181 structured exclusion/prerequisite rules. Every row carries a primary-source URL — a direct link to the ministry, prefecture, or 日本政策金融公庫 document — audited nightly for liveness. No aggregator URLs are allowed in the schema; violations are a regression.

Under the hood: FTS5 with the trigram tokenizer handles Japanese substring search, but trigrams generate false positive overlaps for single-kanji compounds. The workaround is phrase queries — wrapping the search term in double quotes forces a contiguous-token match. SQLite is the entire backend; no separate search engine. The API runs on Fly.io Tokyo (nrt) behind Cloudflare Pages for docs/static. Billing is Stripe metered: ¥3/request (税込 ¥3.30), anonymous quota of 50 req/month per IP (resets JST 月初 00:00), invoices conform to Japan's 適格請求書 system (T8010001213708). A 2026-04-24 expansion added laws (e-Gov, CC-BY; 6,850+ rows, continually loading) and tax rulesets (35 rows) alongside subsidy programs. Court decisions, procurement bids, and invoice registrants have schema and ingest infrastructure pre-built; data loads are coming post-launch.

Honest limits: this is a solo project, zero-touch ops, no SLA, no phone or email support. Launch-day coverage skews toward agriculture and small-business subsidies — that's where primary sources are most complete. Enforcement and court-decision coverage is thinner. I have no marketing budget; 100% organic acquisition is the operating model. If it doesn't find users on its own merits it was the wrong thing to build.

https://jpcite.com | Docs: https://jpcite.com/docs | `pip install autonomath-mcp`

---

## First comment

**Stack:**
- Python 3.12, FastAPI, FastMCP (stdio, protocol 2025-06-18)
- SQLite + FTS5 trigram tokenizer (single-file DB, no Postgres)
- Fly.io Tokyo (nrt) — closest major region to Japan government APIs
- Cloudflare Pages — static docs + per-program SEO pages (9,998 pages, generated)
- Stripe metered billing with 適格請求書 (JP invoice system) compliance
- PyPI package: `autonomath-mcp` (import path stays `jpintel_mcp` internally — legacy rename risk)

**Why ¥3/req with no tiers:**
Tiers create a sales cycle. I'm one person with a day job. Every pricing conversation I don't have is time I can spend on data quality. Stripe metered billing lets me bill a research team and a solo dev on the same plan without any SKU negotiation. If the unit economics break I'll know from the first invoice.

**Open questions for HN:**

1. Anyone running FastMCP (or any MCP server) in production? The stdio transport works fine locally and in Claude Desktop, but I'm curious what surprised people at scale — especially around session management and error propagation.

2. SQLite in prod at this read-load: any gotchas I should expect beyond WAL mode + read-only connections for API workers? I'm not anticipating high concurrency at launch but want to know where the walls are.

3. For Japanese FTS: has anyone found a better trigram false-positive mitigation than phrase queries? The current workaround is functional but feels fragile for multi-word queries.

4. Structured exclusion rules (181 of them, covering things like "program X cannot be combined with program Y" or "company with prior enforcement action is ineligible") — is there prior art in public-program APIs from other countries that handle combinatorial eligibility this cleanly?

---

https://jpcite.com | Docs: https://jpcite.com/docs | `pip install autonomath-mcp`

---

## Timing notes

**Hacker News:**
- Optimal posting window: Tuesday–Thursday, 9:00–10:00 AM ET (22:00–23:00 JST same day).
- Avoid Monday (weekend backlog still clearing) and Friday (drops off front page over weekend).
- Plan to be physically at a keyboard for at least 6 hours after posting — early comment engagement is the primary ranking signal. Answer technical questions within 20 minutes if possible.
- Do not edit the title after submission — HN penalizes edits and mods may flag it.

**Product Hunt:**
- Optimal launch: Sunday 00:00 PST (17:00 JST Sunday) to start at the top of a new PH day and accumulate votes through Monday.
- Avoid holiday weekends (US) — US voter pool drops sharply.
- Plan to be online from 00:00–06:00 PST (17:00–23:00 JST) for maker comment replies and hunter outreach.
- Six hours post-launch is the critical window; rank is largely set by then.
