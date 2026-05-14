# Show HN: jpcite — a public-program evidence API for Japan (MCP / OpenAPI / GraphQL)

## Title (≤80 chars, HN spec)

Show HN: jpcite – Japanese public-program evidence API for Claude/ChatGPT/Cursor

## URL

https://jpcite.com

## Text (HN allows ~2,000 chars)

```
jpcite is a Japanese-government public-program evidence API
(11,601 subsidies + 9,484 statutes + 2,065 court decisions +
1,185 enforcement records + 13,801 invoice registrants) exposed as
a 302-path REST/OpenAPI surface + a 151-tool MCP server + a GraphQL endpoint.

Why I built it: ask Claude or GPT "what subsidies match this 法人番号?"
and you get a confident, undated, source-less answer trained on 2024.
The actual data lives across 7+ Japanese government sites
(中小企業庁 / 経産省 / 国税庁 / e-Gov / gBizINFO / 法務局 / 各府省)
that no Western evaluator has crawled. So tax accountants, M&A FAs,
and consultants still do it by hand — 20–40h/month at 100 顧問先.

jpcite is the 'evidence layer' under that. Every response carries
source_url + fetched_at + content_hash (immutable evidence packet),
and 8 業法 fences (税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47条の2 / 行政書士法 §1の2
/ 司法書士法 §3 / 社会保険労務士法 §27 / 弁理士法 §75 / 労働基準法 §36) gate the surface so the API
never produces individualized professional advice — that's the job
of the licensed professional who consumes the artifact.

Stack:
- SQLite FTS5 trigram + sqlite-vec, 9.4GB unified corpus
- FastAPI + FastMCP stdio + GraphQL (FastAPI) under one process
- Fly.io Tokyo + Cloudflare Pages + Stripe metered billing
- ¥3/req (~$0.02), 3 req/IP/day anonymous, no monthly fee, 1-click cancel

What's interesting technically:
- 302 REST/OpenAPI paths + 151 MCP tools + 5 GraphQL types under one
  evidence-packet contract; no service mesh, single binary, all on
  one 9.4GB SQLite blob baked into the Docker image.
- Sub-API-key fan-out (parent issues child keys per 顧問先) lets a
  tax-accountant cron 100 client searches as one billable call set.
- e-Gov 法令 amendment lineage table (am_amendment_diff) tracks
  per-article diffs over time so 'show me what changed since the
  last 決算' is one SQL query, not a 7-tab document diff session.
- AnonIpLimit middleware lets the playground stay tokenless (3
  req/IP/day, JST reset) without exposing a free SKU.

Open licensing: 国税庁 invoice registrants under PDL v1.0 (directly
confirmed with NTA TOS), e-Gov 法令 under CC-BY-4.0. We re-distribute
under those licenses with explicit citation in every payload.

Try it:
- curl https://api.jpcite.com/v1/programs?q=DX&tier=A
- uvx autonomath-mcp (Claude Desktop / Cursor MCP)
- https://jpcite.com/playground (no key)

GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
PyPI: pip install autonomath-mcp==0.4.0

I'm the solo operator. Happy to talk about anything — the
法令 ingestion pipeline, the MCP tool-design choices, the §52 fence
spec, the FTS5 trigram false-overlap kanji bug, why I keep one
9.4GB SQLite over Postgres+Redis, the Stripe metered billing
edge cases, the 'no LLM in production' invariant we enforce in CI.
```

## Posting strategy (operator notes)

- HN posting time targets: Tuesday–Thursday 08:00–10:00 PT
  (= JST 24:00–26:00 翌日 火曜 26 時, i.e. 水曜 02:00 JST).
- Account requirements: ≥30d age, ≥20 karma (existing account
  `shigeto_umeda` qualifies as of 2026-05).
- Use https://news.ycombinator.com/submit  — not via API
  (HN does not have a public submit API; this is a user-OAuth-only
  surface, hence the only outright user-operation step in Wave 41).
- Within first 60 minutes: respond to every top-level comment
  with a substantive reply. HN ranking is gated by comment velocity
  in the first hour.
- Anti-patterns: don't beg for upvotes in Slack/Discord, don't
  cross-post to /r/programming simultaneously (HN front page
  detects this), don't reply with marketing copy.

## Reaction tracking

Once submitted, edit ``analytics/publication_reactions_targets.json`` and
replace the placeholder ``hn`` ``item_id`` with the real HN item id
(visible in the URL ``/item?id=XXXXXX``). The
``scripts/cron/track_publication_reactions.py`` cron will then start
snapshotting score / descendants every 24h into
``analytics/publication_reactions_w41.jsonl``.
