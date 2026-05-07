# Reddit post — T+0 publish draft (operator-only)

> **operator-only**: launch day Reddit publish 用 final draft。mkdocs.yml `exclude_docs` で公開除外。
>
> Publish timing: 2026-05-06 launch day (subreddit ごとに timing 注意)
> Account: operator personal Reddit (3 ヶ月以上の karma 推奨、新 account はスパム認定 risk)
> Format: title + self-text body, English
>
> Validate (memory `feedback_validate_before_apply`):
> - 数値 14,472 / 66 / ¥3 統一
> - INV-22: 過剰強調削除済み
> - 自演 upvote / sockpuppet NG (Reddit shadowban worthy)

---

## Subreddit recommendation

| Subreddit | Self-promo OK? | Recommendation | Note |
|---|---|---|---|
| **r/MachineLearning** | Saturday only ([P] flair) | **POST** (T+0 if Sat, else next Sat) | Strict self-promo, but Show-Tell on Saturday is welcomed if technical |
| **r/LocalLLaMA** | Yes (MCP context) | **POST** (T+0) | MCP / agent tooling fits, ~150k members |
| **r/Japan** | Limited (lifestyle sub) | **SKIP** | Audience mismatch (生活・観光 sub) |
| **r/programming** | NO (self-promo restricted) | **AVOID** | Mod removes self-promo aggressively |
| **r/Japanese** | Limited (language sub) | **SKIP** | Audience mismatch |
| **r/SaaS** | Yes | **POST** (T+0) | metered pricing 議論が刺さる |

**Primary target**: r/LocalLLaMA + r/SaaS (T+0 launch day)
**Secondary target**: r/MachineLearning (next Self-Promotion Saturday, if not Sat already)

---

## Post 1: r/LocalLLaMA (T+0, English, MCP context)

### Title (max 300 chars, keep pithy)

```
[Show] jpcite: MCP server for 11k+ Japanese government subsidy/loan/tax data, ¥3/billable unit metered
```

### Body

```
Solo dev (Tokyo) launching jpcite today — a REST + MCP server that
exposes Japanese public-program data to AI agents (Claude Desktop, Cursor,
ChatGPT, Gemini) in a single call.

**What's in it (2026-05-06 launch):**

- 14,472 programs (subsidies, loans, tax incentives, certifications) from
  METI, MAFF, SME Agency, JFC, 47 prefectures
- 2,286 case studies (採択事例), 108 loans with 3-axis collateral decomp,
  1,185 enforcement cases
- 9,484 laws (e-Gov, CC-BY)
- 13,801 invoice registrants (NTA, PDL v1.0, delta-only live mirror)
- 503,930 entities + 6.12M facts in entity-fact EAV layer
- 181 exclusion / prerequisite rules
- major public rows with source_url + fetched_at lineage

**MCP-native, 139 tools, protocol 2025-06-18:**

- search_programs, prescreen, deadlines, exclusions
- 7 one-shot discovery tools (smb_starter_pack, subsidy_combo_finder,
  deadline_calendar, dd_profile_am, similar_cases, regulatory_prep_pack,
  subsidy_roadmap_3yr)
- Cross-dataset glue: trace_program_to_law, find_cases_by_law,
  combined_compliance_check
- 28 autonomath tools backed by entity-fact DB (17 V1 + 4 metadata tools + 7 static dataset tools)

**Pricing:**

¥3/billable unit (~$0.02), pure metered. No tiers, no seats. Anonymous gets 50
req/month free per IP. Stripe metered + Stripe Tax for JP invoice
compliance.

**Tech:**

Python + FastAPI + FastMCP + SQLite 全文検索インデックス (3-gram) + ベクトル検索, hosted on
Fly.io Tokyo. primary-source URL coverage for major public rows; aggregators (noukaweb,
hojyokin-portal, etc.) banned from source_url for trust reasons.

**Try it:**

- `pip install autonomath-mcp` then add to Claude Desktop config
- curl https://api.jpcite.com/v1/programs/search?q=...
- 3 req/day free, no signup

Repo: https://github.com/[USERNAME]/[REPO]
Docs: https://jpcite.com/docs/
PyPI: https://pypi.org/project/autonomath-mcp/

Happy to discuss 全文検索インデックス (3-gram) pitfalls for Japanese, MCP tool design
tradeoffs, the metered-only choice, or solo + zero-touch ops at this
data scale.
```

---

## Post 2: r/SaaS (T+0, English, business model angle)

### Title

```
Launching a metered-only B2B API today (¥3/billable unit, no tiers, no seats) — feedback wanted
```

### Body

```
Solo founder (Tokyo) launching jpcite today — a REST + MCP API that
exposes Japanese public-program data (subsidies, loans, tax incentives,
laws, enforcement, invoice registrants) to AI agents.

I went pure metered, deliberately:

- ¥3/billable unit (~$0.02), no tier SKU, no seat fees, no annual minimum
- Anonymous 3 req/day free per IP, JST daily reset
- Stripe metered billing + Stripe Tax for JP invoice compliance

The thinking: AI agent workflows don't have "Pro user" semantics. There's
no individual seat. There's no "company plan." Agents make N calls and
pay for N calls. Tier SKUs introduce overhead (decision friction, tier
upgrade modeling, seat reconciliation) that returns zero value.

I also chose:

- Solo + zero-touch ops — no sales calls, no DPA negotiation, no Slack
  Connect, no onboarding
- 100% organic acquisition — no ads, no cold outreach
- Self-service only

Coverage at launch:

- 14,472 programs across 8 ministries, 47 prefectures
- 2,286 case studies, 108 loans, 1,185 enforcement cases
- 9,484 laws, 13,801 invoice registrants
- primary-source URL coverage for major public rows, aggregators banned

Genuinely interested in pushback on:

1. Will B2B buyers tolerate metered-only at this scale?
2. Will solo + zero-touch break under enterprise procurement requirements?
3. Is "anonymous 3/day free" enough as the acquisition top-of-funnel?

Site: https://jpcite.com
Pricing: https://jpcite.com/docs/pricing/
PyPI: https://pypi.org/project/autonomath-mcp/

Reply / DM open for dialog.
```

---

## Pre-publish checklist (operator)

- [ ] subreddit ごとの rules ページ再読 (sidebar の "Rules" + "Self-Promotion")
- [ ] Reddit account age & karma 確認 (新 account = shadowban risk)
- [ ] 数値 14,472 / 66 / ¥3 統一確認
- [ ] GitHub URL placeholder `[USERNAME]/[REPO]` を実 URL に置換
- [ ] flair 設定: r/LocalLLaMA = `[Show]`, r/SaaS = (適切な flair)
- [ ] r/MachineLearning は Saturday only — 平日 publish なら次週 Sat
- [ ] r/programming, r/Japan, r/Japanese は SKIP (上表参照)

---

## Post-publish

- 自演 upvote NG, friends に upvote 依頼 NG (Reddit ban worthy)
- comment 質問は 24h 以内 reply (interactive layer)
- 同 content を複数 sub に同時投稿しない (cross-posting restriction)
- 1 sub 1 投稿、follow-up 投稿は 1 週間以上 interval

---

## Reference

- r/LocalLLaMA rules: https://www.reddit.com/r/LocalLLaMA/about/rules
- r/SaaS rules: https://www.reddit.com/r/SaaS/about/rules
- r/MachineLearning self-promo policy:
  https://www.reddit.com/r/MachineLearning/wiki/index
- INV-22 enforcement: 比較強調 / "industry-first" 等を排除済み
