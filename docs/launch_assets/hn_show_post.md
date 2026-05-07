# Hacker News — Show HN final post (operator-only)

> **operator-only**: HN Show 投稿 form 用 final draft。mkdocs.yml `exclude_docs` で公開除外。
>
> Submit URL: https://news.ycombinator.com/submit
> Submit timing: 2026-05-06 **22:30 JST = 09:30 ET = 06:30 PT** (09:30 ET = HN morning peak window)
> Canonical timeline: `docs/_internal/launch_dday_matrix.md` §0 Firing order summary
> Account: operator personal HN
> Format: title (<=80 chars) + URL + first comment (800-1500 chars)
>
> Validate (memory `feedback_validate_before_apply`):
> - 数値 14,472 / 66 / ¥3 統一
> - INV-22: 過剰強調削除済み (no "must", "absolute", "guaranteed")
> - 自演 upvote / sockpuppet NG (HN ban worthy)

---

## Title (78 chars)

```
Show HN: jpcite – Japanese public-program API for AI agents (¥3/billable unit)
```

Note: HN title length max 80 chars. Above is 73 chars (counting the leading
"Show HN: ", title body 64 chars). En-dash variant kept; ASCII-only fallback:

```
Show HN: jpcite - Japanese public-program API for AI agents (3 yen/billable unit)
```

---

## URL field

```
https://jpcite.com
```

Note: HN guideline — point to product page, not GitHub repo. GitHub URL goes
in the first comment.

---

## First comment (1,189 chars, within 800-1500 target)

```
Hi HN, Shigetoshi here. Solo dev in Tokyo.

jpcite is a REST + MCP API that exposes Japanese public-program data
to AI agents in one call: subsidies, loans, tax incentives, certifications,
laws, enforcement cases, invoice registrants.

What:
- 14,472 programs (METI, MAFF, SME Agency, JFC, 47 prefectures)
- 2,286 case studies, 108 loans (3-axis collateral / personal-guarantor /
  third-party-guarantor decomposition), 1,185 enforcement cases
- 9,484 laws (e-Gov, CC-BY)
- 13,801 invoice registrants (NTA, PDL v1.0, delta-only live mirror)
- 503,930 entities + 6.12M facts in entity-fact EAV layer
- 181 exclusion / prerequisite rules curated from public program guidelines
- major public rows with source_url + fetched_at lineage

Why:
Japanese gov subsidy data is PDF-first, scattered across 8 ministries +
47 prefectures + 1700 municipalities. Aggregators exist but are gray-area
for LLM ingestion (TOS prohibits redistribution to AI). I wanted one API
where Claude / Cursor / ChatGPT can answer "is my company eligible?" with
primary-source URLs attached.

How:
MCP-native, 139 tools, protocol 2025-06-18, stdio transport. One Manifest
line plugs it into Claude Desktop. Backed by SQLite 全文検索インデックス (3-gram, Japanese
compound-word search) + ベクトル検索 for the entity-fact layer. Hosted on
Fly.io Tokyo. Stripe metered + Stripe Tax for JP invoice compliance.

Pricing:
Pure metered ¥3/billable unit (~$0.02). No tiers, no seat fees, no annual
minimums. Anonymous gets 3 req/day free per IP, JST daily reset.

Data:
Aggregators (noukaweb, hojyokin-portal, biz.stayway) are explicitly banned
from source_url — past industry incidents created 詐欺 risk. Every program
cites a primary source.

Open questions I'd like HN to push on:
1. Pure-metered viability vs Free/Pro tier expectations
2. MCP-only distribution vs traditional SDK
3. 全文検索インデックス (3-gram) の単漢字 false positive
4. Solo + zero-touch ops at this data scale (can it last?)

Repo: https://github.com/[USERNAME]/[REPO]
PyPI: https://pypi.org/project/autonomath-mcp/
Docs: https://jpcite.com/docs/

Will be here all day to answer.
```

---

## Pre-submit checklist (operator)

- [ ] Title 80 chars 以下確認 (HN form 自体が cap)
- [ ] URL `https://jpcite.com` 動作確認 (200 / valid TLS)
- [ ] First comment 800-1500 chars 確認 (上記 1,189)
- [ ] GitHub URL placeholder `[USERNAME]/[REPO]` を実 URL に置換
- [ ] PyPI page `pypi.org/project/autonomath-mcp/` 動作確認
- [ ] HN guideline 再読: https://news.ycombinator.com/showhn.html
- [ ] 自分の HN account が "Show HN" に値する age があるか確認
  (新 account はスパム認定されやすい)
- [ ] Submit 直後に first comment を post (HN 慣習)
- [ ] 自演 upvote NG, friends に upvote 依頼 NG (organic only)

---

## Post-submit

- HN URL を operator memo に記録
- T+0 X (twitter) thread に reply で `Also on HN: [URL]` を追加 (1 回のみ)
- Comment に質問が来たら 24h 以内に reply (zero-touch だが HN は exception
  で interactive)
- /front page に乗ったか乗らないかで一喜一憂しない (organic = pull-based)

---

## Reference

- Show HN guidelines: https://news.ycombinator.com/showhn.html
- Past Show HN about MCP: search "Show HN MCP" on https://hn.algolia.com
- INV-22 enforcement: 「業界初」「最大」「絶対」等の比較強調を本文/title から排除済み
