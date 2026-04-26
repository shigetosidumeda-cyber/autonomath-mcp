# LinkedIn post (English) — T+0 publish draft (operator-only)

> **operator-only**: launch day LinkedIn publish 用 final draft。mkdocs.yml `exclude_docs` で公開除外。
>
> Publish target: 2026-05-06 09:00 JST
> Account: operator personal LinkedIn
> Audience cohort: dev-leaning + VC-leaning (technical decision-makers, fund analysts, SaaS founders)
> Tone: professional, first-person, no marketing puffery
> Length: 1,427 chars (within 1,500 cap)
>
> Validate (memory `feedback_validate_before_apply`):
> - 数値 13,578 / 66 / ¥3 統一
> - INV-22: 過剰強調 ("must", "absolute", "guaranteed", "industry-first") 削除済み
> - LinkedIn 営業 DM 案内禁止 (memory `feedback_organic_only_no_ads`)

---

## Post body (1,427 chars)

```
Today I'm launching AutonoMath — a REST + MCP API exposing Japanese
public-program data to AI agents in a single call.

For the past few years, anyone trying to surface Japanese government
subsidies, loans, or tax incentives via AI has hit the same wall.
Government data is PDF-first, scattered across 8 ministries, 47
prefectures, and ~1,700 municipalities. Aggregators exist but live in
TOS gray-area for LLM ingestion. There has been no clean API for
"is this company eligible for this program, with primary-source URLs
and case-study evidence."

What's in it (2026-05-06 launch):

- 13,578 programs (METI, MAFF, SME Agency, JFC, all 47 prefectures)
- 2,286 case studies, 108 loans (3-axis collateral decomposition),
  1,185 enforcement cases
- 9,484 laws (e-Gov, CC-BY), 13,801 invoice registrants (NTA, PDL v1.0)
- 503,930 entities + 6.12M facts in entity-fact EAV layer
- 99%+ rows ship with source_url + fetched_at lineage
- 181 exclusion rules for compatibility checks

Architecture choices that I think are interesting:

- MCP-native: 72 tools, protocol 2025-06-18, stdio. One Manifest line
  plugs into Claude Desktop / Cursor / ChatGPT / Gemini. No SDK to
  maintain across clients.
- SQLite FTS5 trigram for Japanese compound-word search; sqlite-vec
  for the 504k-entity vec layer (gradual activation).
- Pure metered ¥3/req (~$0.02). No tier SKUs, no seat fees, no annual
  minimums. Anonymous 50 req/month free per IP.
- Aggregator sources are explicitly banned. Every program cites a
  primary government URL.

Distribution choices:

- Solo + zero-touch ops. No sales calls, no DPA negotiation, no Slack
  Connect, no onboarding meetings.
- 100% organic acquisition — no ads, no cold outreach, no paid
  placements.

If you build AI agents that touch Japanese SMBs, accountants, certified
support orgs, or do DD on Japanese companies, I'd be glad to hear how
it performs in your workflow.

Press kit: https://autonomath.ai/press/
Docs: https://autonomath.ai/docs/
PyPI: https://pypi.org/project/autonomath-mcp/

#MCP #ClaudeDesktop #JapanTech #SaaS #AIagents
```

---

## Pre-publish checklist (operator)

- [ ] LinkedIn UI で 1,500 char cap 確認 (上記 1,427)
- [ ] press kit + docs URL 動作確認 (200 / valid TLS)
- [ ] PyPI URL 動作確認 (publish 完了後)
- [ ] hashtag 5 種 (#MCP #ClaudeDesktop #JapanTech #SaaS #AIagents)
- [ ] LinkedIn の audience 設定: Public (Anyone)
- [ ] First image: AutonoMath logo placeholder (launch 後正式版で差し替え)

---

## Post-publish

- 自演 like / comment NG (LinkedIn 規約)
- DM での営業 follow-up 案内禁止 (memory `feedback_organic_only_no_ads`)
- comment が来たら 24h 以内に reply (interactive layer は維持)
- 過剰な repost / 連投禁止 (organic only)

---

## Reference

- Why metered-only: memory `project_autonomath_business_model`
- Why solo + zero-touch: memory `feedback_zero_touch_solo`
- Why no UI features: memory `feedback_autonomath_no_ui`
- INV-22 enforcement: 比較強調・"industry-first" 等を全て削除済み
