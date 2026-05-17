# Launch posts — drafts only

12 draft launch posts for jpcite (autonomath-mcp v0.4.0). Operator-only directory; not published.

## File index

| File | Platform | Format |
|------|----------|--------|
| `hn.md` | Hacker News | Show HN title + first comment |
| `reddit_programming.md` | r/programming | Long technical post |
| `reddit_japan.md` | r/japan | JP-life angle for foreign founders |
| `reddit_sideproject.md` | r/SideProject | Solo founder build journey |
| `reddit_localllama.md` | r/LocalLLaMA | MCP + local agents |
| `reddit_claudeai.md` | r/ClaudeAI | Claude Code + MCP integration tutorial |
| `reddit_entrepreneur.md` | r/Entrepreneur or r/SaaS | Pricing model rationale |
| `reddit_japanfinance.md` | r/japanfinance | Small-business owner accessibility |
| `devto.md` | dev.to | Long-form architecture + pricing essay |
| `lobsters.md` | lobste.rs | Architecture-focused short post |
| `twitter_x_thread.md` | Twitter / X | 6-tweet launch thread |
| `note_com.md` | note.com | Long-form JP narrative |

---

## Recommended posting order

The HN sweet spot is **Tuesday-Thursday, 06:30-09:30 PT (= 22:30-01:30 JST)**. Anchor everything around the HN slot.

### Day 0 (HN day — Tue/Wed/Thu)

1. **T-30min** — Pre-launch check (see checklist below). Confirm jpcite.com is up, demo curl returns 200, Stripe metering live.
2. **T-0** — Submit `hn.md` to https://news.ycombinator.com/submit. Title goes in Title field, URL field is `https://jpcite.com`, "first comment" goes in the first comment slot **immediately after** submission.
3. **T+5min** — Post `twitter_x_thread.md` from founder X account. Quote-tweet the HN URL once it's live.
4. **T+15min** — Post `lobsters.md` to lobste.rs (lobste.rs traffic peaks alongside HN, do them together).
5. **T+30min** — Post `reddit_programming.md` to r/programming.
6. **T+45min** — Post `reddit_localllama.md` to r/LocalLLaMA (different audience, no cannibalization risk).
7. **T+60min** — Post `reddit_claudeai.md` to r/ClaudeAI.

### Day 1 (next day)

8. **JST 09:00** — Post `note_com.md` to note.com (JP-domestic morning peak).
9. **JST 11:00** — Post `reddit_japanfinance.md` to r/japanfinance.
10. **JP afternoon (UTC night)** — Post `devto.md` to dev.to (publishes for US morning).

### Day 2

11. **US morning** — Post `reddit_sideproject.md` to r/SideProject.
12. **US afternoon** — Post `reddit_entrepreneur.md` to r/Entrepreneur (or r/SaaS — pick the one with better engagement signal that week).
13. **JST evening** — Post `reddit_japan.md` to r/japan (cultural-fit subreddit, do later as the launch matures).

### Posting cadence rules

- **Never post the same content to two subreddits within 1 hour.** Reddit anti-spam will shadow-ban.
- **Always reply to every comment in the first 4 hours** of any HN / Reddit post. Engagement velocity is the ranking signal.
- **Don't cross-link launches in tweets** — keep the X thread pointing at our URLs only.
- **No upvote brigading.** No asking friends to upvote. HN and Reddit both auto-flag this and will ban.

---

## Pre-launch checklist

Run through these **30 minutes before the HN submission**. If any fail, abort and fix.

### Live infrastructure

- [ ] `curl -sS -o /dev/null -w "%{http_code}\n" https://jpcite.com/` returns `200`
- [ ] `curl -sS -o /dev/null -w "%{http_code}\n" https://api.jpcite.com/healthz` returns `200`
- [ ] Demo curl returns valid JSON with `total > 0`:
  ```bash
  curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
  ```
- [ ] `https://api.jpcite.com/v1/openapi.json` returns valid OpenAPI v3 spec
- [ ] Stripe webhook live + test charge of ¥3 succeeds (use test API key)
- [ ] Anonymous 3/日 rate limit verified — 51st request returns `429` with reset hint
- [ ] HTTP fallback working: `uvx autonomath-mcp` from a clean machine boots into HTTP mode and answers a search

### Content polish

- [ ] GitHub README first paragraph matches the value-prop in `hn.md` (no contradiction in counts)
- [ ] `https://jpcite.com/docs/pricing/` clearly states "¥3/billable unit, 3/日 free anonymously, no tiers"
- [ ] `https://jpcite.com/about.html` shows Bookyou株式会社 + T8010001213708 + 梅田茂利 (legal display compliance)
- [ ] Disclaimer page (`/compliance/landing_disclaimer/`) lists 税理士法 §52, 弁護士法 §72, 行政書士法 §1
- [ ] PyPI page for `autonomath-mcp` shows `0.3.0` as latest (not `0.2.0`)
- [ ] GitHub repo description matches the launch tagline
- [ ] OpenAPI link is reachable from README badges

### Numbers consistency check

All public posts cite these numbers — verify any one of them on the live API matches the draft text:

- [ ] `programs` count ≈ 11,601 (off by ≤50 OK)
- [ ] `laws` count ≈ 9,484
- [ ] `court_decisions` count ≈ 2,065
- [ ] `tax_rulesets` count = 50
- [ ] `invoice_registrants` count ≈ 13,801
- [ ] `case_studies` ≈ 2,286
- [ ] `enforcement_cases` ≈ 1,185
- [ ] MCP tool count = 184 at default gates (verify with `len(mcp._tool_manager.list_tools())`)
- [ ] DB size statement ≈ 8.29 GB matches actual `ls -lh autonomath.db`

### Operator readiness

- [ ] Founder X account ready, profile link points to jpcite.com
- [ ] HN account has karma > 0 (Show HN posts from 0-karma accounts get auto-flagged)
- [ ] Reddit account on each target subreddit has at least the minimum karma the sub requires (some require 100+)
- [ ] info@bookyou.net is monitored — first 4 hours after HN post will see inbound emails
- [ ] GitHub Issues open + at least one labeled "good first issue" so the repo doesn't look dead

### Honest-positioning compliance

- [ ] Every draft mentions "not tax advice" or 税理士法 §52 in body (NOT just title)
- [ ] No draft claims SOC2 / ISO / GDPR-audited (we don't have those)
- [ ] No draft claims customer counts, revenue, or "trusted by X companies"
- [ ] No draft claims real-time legal-amendment tracking (it's monthly snapshots)
- [ ] No draft mentions failed/blocked work (jpintel rename, blueberry pivot, prior MVP attempts)

---

## Notes

- All drafts are text-only; user posts manually
- Drafts assume `https://github.com/shigetosidumeda-cyber/autonomath-mcp` is the public repo (verified via `git remote -v` 2026-04-29)
- Operator: Bookyou株式会社 (T8010001213708), 梅田茂利, info@bookyou.net
- If a subreddit auto-flags one of these for "spam" because they perceive it as promotional — message the moderators with `info@bookyou.net` and the operator T-number; do NOT delete and repost (that triggers stricter flagging)
