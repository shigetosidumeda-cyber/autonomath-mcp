# Product Hunt: jpcite — Japanese public-program evidence API

## Submission form fields (https://www.producthunt.com/posts/new)

### Tagline (60 chars max)

```
Japanese public-program evidence API for AI agents
```

(58 chars)

### Name

```
jpcite
```

### Description (≤260 chars)

```
Evidence API for Japan's public programs — 11,601 subsidies, 9,484
statutes, 1,185 enforcement records, 13,801 invoice registrants.
182 OpenAPI paths + 139 MCP tools. ¥3/req metered. Built for AI
agents (Claude/ChatGPT/Cursor) with source_url + content_hash
on every payload.
```

(259 chars including newlines)

### Topics (Product Hunt picks 3–4)

- Artificial Intelligence
- Developer Tools
- API
- Open Source (partial — server is closed, evidence corpus is open-licensed)

### Maker comment (first comment on the launch post, ≤2,000 chars)

```
Hi PH! I'm the solo operator of jpcite — an evidence API for
Japan's public-program data (subsidies, statutes, court rulings,
enforcement actions, invoice registrants).

Why this matters: every Western AI model is trained on Wikipedia +
US/EU government open data. Japanese public programs (中小企業庁
subsidies, e-Gov 法令, 国税庁 通達, 適格事業者 registry) are NOT
in the training data, NOT crawled by SerpAPI / Brave / DuckDuckGo
at any depth, and are spread across 7+ government sites with
inconsistent formats. So asking Claude / ChatGPT 'what subsidy
matches this 法人?' returns a confident-sounding 2024 hallucination.

jpcite is the evidence layer underneath. 11,601 programs + 9,484
statutes + 2,065 court decisions + 1,185 enforcement records +
13,801 invoice registrants, every row with source_url +
fetched_at + content_hash. 182 OpenAPI paths and 139 MCP tools so
agents can probe by 法人番号 / 業種 / 都道府県 / 制度 ID under one
evidence-packet contract.

Stack: SQLite FTS5 trigram + sqlite-vec on a 9.4 GB blob baked into
the Docker image, FastAPI + FastMCP stdio + GraphQL under one
binary on Fly.io Tokyo, Stripe metered (¥3/req ≈ $0.02), 3 req/IP/day
free, no monthly fee, 1-click cancel.

Honest framing: this is regulated information. We do NOT generate
individualized professional advice — 7 業法 fences (税理士法 §52,
弁護士法 §72, 金商法 §29, ...) gate the surface so the API stays
on the 'evidence retrieval' side and the licensed professional
stays on the 'advice' side. Every response carries an
X-Jpcite-Disclaimer header making that boundary explicit.

If you're building an agent that needs to know anything about a
Japanese 法人 — M&A FA, tax-accountant 顧問先 monitoring, KYC,
業法 改正 alerts, 採択 monitoring — try the playground (no key,
3 req/IP/day free) at https://jpcite.com/playground.

Happy to answer anything — the corpus pipelines, the 業法 fence
spec, the SQLite-mostly architecture, why we keep LLMs OFF the
production code path. I'm here all day.
```

## Assets (operator preparation checklist)

- [ ] **Gallery logo**: 240×240 PNG, transparent background.
      Source: ``site/assets/logo.svg`` → ``site/assets/logo_240.png``.
- [ ] **Thumbnail**: 800×600 PNG. Hero shot of the homepage.
- [ ] **Gallery images** (1270×760 PNG, up to 6):
  - [ ] 1: Homepage hero (CTA + 11,601 programs counter).
  - [ ] 2: Playground (search / 結果 / X-Jpcite-Evidence header visible).
  - [ ] 3: MCP tool list in Claude Desktop screenshot.
  - [ ] 4: OpenAPI 182-path explorer.
  - [ ] 5: GraphQL playground.
  - [ ] 6: Stripe Checkout (¥3/req metered).
- [ ] **Demo video / GIF** (≤4 min, optional but ranks higher):
      Loom screen recording of 5-min onboarding (anon → 法人番号 search →
      Claude Desktop tool call → upgrade to API key).

## Posting strategy (operator notes)

- Product Hunt 1-day rank cycle starts at **00:01 PT** (= 16:01 JST).
  Submitting earlier in the day-cycle gives the post a full 24h
  vote window.
- The first 60 minutes are critical — Top 5 of the day captures
  most of the downstream traffic.
- Anti-patterns Product Hunt explicitly forbids:
  - Asking for upvotes off-platform (Slack/Discord/Twitter "please vote").
  - Re-uploading a previously-launched product without major changes.
  - Faking maker badges.
- Acceptable: simply announcing the launch on Twitter / Bluesky /
  LinkedIn pointing back to the PH page (PH does this themselves
  and it's tracked as a normal vote source).

## Reaction tracking

After launch, edit ``analytics/publication_reactions_targets.json`` and
fill in the real PH slug (visible in the URL ``producthunt.com/posts/<slug>``).
Product Hunt requires a PAT for the read API, so the cron snapshots
``http_status: 0`` + a manual-tracking note until ``PRODUCT_HUNT_PAT``
is added to ``.env.local`` and ``scripts/cron/track_publication_reactions.py``
``probe_producthunt`` is upgraded.
