---
title: "Show HN draft — jpcite"
slug: "hn_show_hn_jpcite"
audience: "operator (Hacker News submission)"
intent: "hn_show_hn_draft"
status: "draft — pending account age ≥30d + manual submission"
date_created: "2026-05-11"
license: "operator_internal"
---

# Show HN: jpcite — Japanese public-program evidence API for AI agents

> このドキュメントは Hacker News `Show HN:` 投稿のドラフトです。Claude が起案 → operator (info@bookyou.net) が account age ≥30d を満たすアカウントで手動投稿。

## 投稿条件 check-list

- [ ] HN account age ≥ 30 日 (Show HN gate)
- [ ] account karma ≥ 5 (downvote 対象になりにくい)
- [ ] 既出 (Ask HN / Show HN) と被らない (`hn.algolia.com` で `jpcite` 検索 → 0 件確認済 2026-05-11)
- [ ] 投稿時間帯: 火-木 08:00-10:00 EST (= 21:00-23:00 JST) が front page 滞留時間最大
- [ ] 投稿後 1 時間以内に friendly な comment 1-2 件 (sock-puppet ではない、本人の補足のみ)

## Title (≤80 chars)

```
Show HN: jpcite – Japanese public-program evidence API for AI agents
```

## URL field

```
https://jpcite.com
```

## Body (≤4000 chars target、submission box 表示余裕を持って)

```
Hi HN! I built jpcite — a Japanese public-program (補助金 / 法令 / 適格事業者 /
行政処分 / 採択) evidence API that you can plug into Claude, ChatGPT, Cursor,
or any MCP-capable agent.

The problem: LLMs hallucinate badly on Japanese public data. "What grants can
a 30-employee construction firm in Osaka apply for in 2026?" → you get a
plausible-sounding answer with fake program IDs, expired deadlines, and
made-up source URLs. The data exists (METI, 中小企業庁, 国税庁, e-Gov etc.),
but it's scattered across ~200 ministry / prefecture sites, each with its
own quirks. No agent has been able to use it reliably.

What jpcite gives you:

  * 11,601 searchable programs (補助金 / 融資 / 税制 / 認定) with tier scores,
    deadlines, and one-clickable canonical source URLs from the issuing
    ministry / prefecture (aggregators are banned by policy — every row
    must cite a primary government source)
  * 503,930 entities + 6.12M facts + 177,381 relation edges (programs ↔ laws
    ↔ adoptions ↔ enforcement)
  * 9,484 laws (full-text e-Gov mirror, CC-BY-4.0) — 6,493 already searchable
    via FTS5
  * 13,801 invoice registrants (delta + monthly 4M-row bulk via NTA PDL v1.0)
  * 2,065 court decisions, 1,185 administrative enforcement cases, 2,286
    採択事例, 362 active bids
  * Coverage check, license fence (税理士法 §52 / 行政書士法 §1 / 司法書士法 §3
    / 弁護士法 §72 etc. baked into the response envelope so the AI knows
    when to defer to a licensed professional)

Surfaces:

  * REST API:   https://api.jpcite.com  (OpenAPI 3.1, 182 paths)
  * MCP stdio:  pip install autonomath-mcp && autonomath-mcp
  * MCP HTTP:   https://api.jpcite.com/mcp  (Streamable HTTP, 2025-06-18)
  * Registry:   https://registry.modelcontextprotocol.io/servers/jpcite
  * Discovery:  https://jpcite.com/.well-known/mcp.json

Tools / resources / prompts:

  * 120 MCP tools (default gate, verified via `await mcp.list_tools()`)
  * 28 MCP resources (programs, laws, cases, enforcement, catalog)
  * 7 MCP prompts (monthly review / DD / 採択監視 etc.)
  * AX (Agent eXperience) score: 44/44 across Access + Context + Tools +
    Orchestration pillars
  * Agent Journey audit: 10/10 step coverage (discovery → onboarding →
    daily-use → exit)

Pricing & operations:

  * ¥3 / billable unit (税込 ¥3.30), fully metered. No tier SKUs, no seat
    fees, no annual minimums.
  * Anonymous tier: 3 req / day / IP, free (JST midnight reset)
  * 100% organic acquisition. Solo operation. Zero-touch (no sales calls,
    no DPA negotiation, no Slack Connect, no onboarding calls)
  * Stripe metered billing, Fly.io Tokyo, Cloudflare Pages
  * Open-source CLI / SDK on PyPI + npm; server side closed but openapi.json
    is public domain

Why no LLM-on-LLM:

  * The operator does NOT call Claude / OpenAI / Gemini from production
    code. The customer's agent reads jpcite responses verbatim; we just
    serve evidence. This keeps unit economics sane at ¥3/req (an LLM call
    per request would burn ~¥0.5-2 in API cost and reduce margin to <50%).
  * Everything inside `src/` / `scripts/cron/` / `scripts/etl/` / `tests/`
    is LLM-import-free, enforced by a CI guard.

I'd love feedback from anyone who:

  * Builds Claude / ChatGPT / Cursor / Codex agents that need to answer
    Japanese-government questions
  * Runs a 税理士 / 行政書士 / 中小企業診断士 office and wants to ship a
    customer-facing AI assistant
  * Has opinions on MCP server design / AX (Agent eXperience) patterns

Happy to AMA in the comments. Disclosure: I am the founder & sole operator
(梅田茂利, Bookyou株式会社 — T8010001213708, Tokyo).

Repo / docs:
  * Cookbook:    https://jpcite.com/docs/cookbook/
  * Recipes:     https://jpcite.com/recipes/  (30 task-shaped walkthroughs)
  * Compare:     https://jpcite.com/compare/  (vs j-grants / hojyokin-portal)
  * Status:      https://status.jpcite.com/
  * Onboarding:  https://jpcite.com/onboarding/  (30 秒で claude-code 接続)
```

## Comment 1 (本人補足、投稿後 5-15 分で投下)

```
A few things I'd add that wouldn't fit in the body:

* Honest gaps: municipal grants have a 7-14 day ingest lag; only S/A tier
  programs are reflected same-day. The invoice registrant table is a delta
  feed today, monthly bulk lands 1st-of-month at 03:00 JST.
* Why JP-only: the legal landscape for grants / tax / corporate ID is
  Japan-specific enough that pretending to do "global compliance" would be
  dishonest. We solve one market deeply.
* On hallucination: every response includes `fetched_at` (UTC ISO 8601) and
  `source_url` to the issuing authority. If we can't cite, we don't return
  the row. This is enforced at insert-time, not as a post-hoc filter.
```

## Comment 2 (技術質問への先回り、必要に応じて)

```
For folks asking about the MCP transport split:

* stdio launcher (`autonomath-mcp` from PyPI) for desktop clients
  (Claude Desktop, Cursor, Continue, Cline)
* Streamable HTTP at https://api.jpcite.com/mcp for serverless agents
  and CI-driven runs
* Both serve the same 120 tools / 28 resources / 7 prompts; the HTTP path
  carries proper SSE keep-alives and works behind Cloudflare.

OAuth Device Flow is wired for the HTTP path so headless agents can
authenticate without an embedded browser.
```

## 投稿後 monitoring

- 1h で 5+ comment が付くか確認、front page (≥ position #30) 滞留時間 4-6h を目標
- HN moderator から「Show HN タグ修正」依頼が来たら即対応
- 内容批判 / data quality 質問は必ず本人が一次資料を貼って回答 — sock-puppet 禁止

## fall-back: 滞留 < 2h で flagged されたら

- 翌週同曜日同時刻に修正版 (intro tighten + 抽象から具体) を再投稿
- 24h 連続再投稿は HN 慣行違反 — 必ず 1 週間以上空ける

## canonical source

- HN Show HN guideline: <https://news.ycombinator.com/showhn.html>
- HN posting best practices: <https://news.ycombinator.com/newsguidelines.html>
- jpcite homepage: <https://jpcite.com/>
- jpcite docs cookbook: <https://jpcite.com/docs/cookbook/>
