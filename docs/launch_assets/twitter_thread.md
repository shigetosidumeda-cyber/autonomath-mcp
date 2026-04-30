# Twitter / X thread (English) — T+0 publish draft (operator-only)

> **operator-only**: launch day publish 用 final draft (English X)。mkdocs.yml `exclude_docs` で公開除外。
>
> Publish target: 2026-05-06 09:00 JST = 2026-05-05 20:00 ET
> Account: operator personal X
> Format: 8-tweet thread, each <= 280 chars, copy-paste ready
>
> Validate before send (memory `feedback_validate_before_apply`):
> - 数値 13,578 / 66 / ¥3 を必ず確認
> - URL 動作確認 (https://jpcite.com, /docs/, GitHub, PyPI)
> - 過剰強調 (必ず / 絶対 / 保証 / 業界初) 削除済み (INV-22)

---

## Tweet 1/8 — launch announcement + hook (271 chars)

```
AutonoMath launches today.

A REST + MCP API exposing Japanese public-program data — subsidies, loans,
tax incentives, laws, enforcement, invoice registrants — to AI agents in
one call.

Built solo. Metered ¥3/req. 50/month free per IP.

https://jpcite.com

#MCP #ClaudeDesktop
```

---

## Tweet 2/8 — why I built it (operator persona) (273 chars)

```
2/ The why.

Anyone asking "is my company eligible for this subsidy" via AI hits a wall.
JP gov data is PDF-first, scattered across 47 prefectures + 8 ministries,
and aggregators are gray-area for LLM ingestion.

I wanted one API where Claude can just answer.
```

---

## Tweet 3/8 — the numbers (270 chars)

```
3/ What's in it (2026-05-06):

- 13,578 programs (METI, MAFF, SME Agency, JFC, prefectures)
- 2,286 case studies, 108 loans, 1,185 enforcement
- 9,484 laws (e-Gov CC-BY)
- 13,801 invoice registrants (NTA PDL v1.0)
- 99%+ rows w/ source_url + fetched_at
```

---

## Tweet 4/8 — 5 audience pitch (276 chars)

```
4/ Built for 5 audiences:

- AI agent devs — 72 MCP tools at default gates, 1 manifest line
- Tax accountants — Article-level statute trace
- SMB owners — "what subsidies fit me?" via Claude
- VCs — DD on subsidy/enforcement/invoice via 法人番号
- GovTech — embed, no UI build needed
```

---

## Tweet 5/8 — tech stack (266 chars)

```
5/ Tech stack:

- SQLite + 全文検索インデックス (3-gram, Japanese compound word search)
- ベクトル検索 for entity-fact vec layer (504k entities, 6.12M facts; gradual activation, 全文検索インデックス primary)
- FastAPI (REST) + FastMCP (stdio MCP, protocol 2025-06-18)
- Fly.io Tokyo + Cloudflare Pages + Stripe metered
```

---

## Tweet 6/8 — data quality (276 chars)

```
6/ Data hygiene matters here.

Every program row cites a primary source (ministry, prefecture, JFC).
Aggregators (noukaweb, hojyokin-portal, biz.stayway) are banned from
source_url — past industry incidents created 詐欺 risk.

99%+ rows ship with source_url + fetched_at lineage.
```

---

## Tweet 7/8 — how to start (272 chars)

```
7/ How to start (3 paths):

1. curl https://api.jpcite.com/v1/programs/search?q=...
2. Claude Desktop: add `{"command":"uvx","args":["autonomath-mcp"]}` to
   claude_desktop_config.json
3. pip install autonomath-mcp

Anonymous 50 req/month free per IP. JST monthly reset.
```

---

## Tweet 8/8 — AMA + GitHub (260 chars)

```
8/ Happy to AMA on:

- 全文検索インデックス (3-gram) pitfalls for Japanese
- MCP tool design tradeoffs
- Why pure metered (no tier SKU)
- Solo + zero-touch ops at scale

GitHub: https://github.com/[USERNAME]/[REPO]
PyPI: pypi.org/project/autonomath-mcp/
Docs: jpcite.com/docs/

Reply / DM open.
```

---

## Pre-publish checklist (operator)

- [ ] 8 tweet 全て 280 char 以下確認 (X UI で再カウント)
- [ ] GitHub URL placeholder `[USERNAME]/[REPO]` を実 URL に置換
- [ ] press kit + docs URL 動作確認
- [ ] thread の最初の tweet に reply で 2/8...8/8 を順次連結
- [ ] 自演 like / RT NG (X 規約)

---

## Post-publish

- pin 1/8 を operator profile に
- HN URL は T+0 **22:30 JST** 投稿後に reply で追加 ("Also on HN: [URL]"). canonical timing: `docs/_internal/launch_dday_matrix.md` §0 (09:30 ET = HN morning peak window)
- 過剰な再 RT / quote 連投 NG (organic only)
