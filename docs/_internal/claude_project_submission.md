# Anthropic Claude Project — jpcite 提出 worksheet (Wave 16 G2)

> **Goal**: Anthropic 公式の Claude Project marketplace (招待制 / partnerships
> directory) に jpcite を提出する。public marketplace は organic only path
> で、partnerships@anthropic.com 宛 inbound mail (xrea SMTP 経由) が最小経路。
> Pre-flight は全て Claude が代行可。**真 user 操作 = Claude.ai account で
> 招待コードが届いた後の Workspace 追加 + Publish ボタン押下のみ**。

## 1. Anthropic 側 channel 一覧 (organic only)

| channel | URL | 招待制? | 代行可 |
| --- | --- | --- | --- |
| MCP registry (公式) | https://github.com/modelcontextprotocol/registry | OPEN (PR) | ✓ (Wave 15 G6 で 5 registry submit 済) |
| Claude Desktop directory | claude.ai/desktop | OPEN | ✓ |
| Anthropic partnerships | partnerships@anthropic.com | INBOUND mail のみ | ✓ (本ドキュメント) |
| Claude Workspaces marketplace | claude.ai/workspaces | 招待制 | △ (招待コード入手後は user 操作) |
| Claude Code skill marketplace | claude.ai/code/skills | 招待制 | △ |

本ドキュメントは **partnerships@anthropic.com 経路**を主軸とする。
MCP registry / Desktop directory は Wave 15 G6 で既に submission 済
(`docs/_internal/W20_CLAUDE_DESKTOP_SUBMISSION.md` 参照)。

## 2. Inbound mail (partnerships@anthropic.com) — 本文 draft

### 2-1. Subject

```
[MCP Server Submission] jpcite — Japanese public-program evidence (139 tools / 8.29GB unified DB)
```

### 2-2. From / Reply-To

| 項目 | 値 |
| --- | --- |
| From | info@bookyou.net (Bookyou株式会社 / 適格請求書発行事業者 T8010001213708) |
| Reply-To | info@bookyou.net |
| Date | 2026-05-11 |

### 2-3. Body (en + ja 併記)

```
Dear Anthropic Partnerships team,

I'm Shigetoshi Umeda, founder of Bookyou Inc. (Tokyo, Japan;
qualified-invoice issuer T8010001213708), submitting jpcite for
consideration in the Claude Project / MCP partnerships directory.

## What jpcite is

jpcite is a Japanese public-program evidence database, exposed both
as a REST API and as an MCP stdio server. Coverage as of 2026-05-11:

- 11,601 searchable programs (subsidies / loans / tax / certifications)
- 6,493 laws full-text + 9,484 law catalog stubs (e-Gov CC-BY 4.0)
- 2,065 court decisions + 1,185 enforcement cases + 362 bids
- 13,801 invoice registrants (NTA PDL v1.0; monthly 4M-row bulk wired)
- 50 tax rulesets + 33 tax-treaty rows (international tax cohort)
- 503,930 entities + 6.12M facts in a unified 8.29 GB SQLite DB

MCP exposes **139 tools** at default gates (protocol 2025-06-18),
covering search, eligibility chain composition, amendment lineage,
due-diligence question matching, and 22 cross-reference cohort surfaces.

## Why Claude users benefit

1. **First-party-only sources** — every row cites a primary URL
   (METI / MAFF / NTA / e-Gov / JFC / prefectural). Aggregators
   (noukaweb, hojyokin-portal) are explicitly excluded; we treat
   aggregator citations as a 詐欺 (fraud) risk.
2. **Disclaimer envelopes** on every sensitive tool (税理士法 §52,
   弁護士法 §72, 行政書士法 §1, 社労士法 §27) keep Claude users
   inside the boundary of "evidence retrieval", never crossing into
   individual legal/tax advice.
3. **¥3 / billable unit fully metered** (税込 ¥3.30), anonymous 3
   req/day free tier — no tier SKU, no seat fee, zero-touch ops.
4. **No LLM inside the server** — `tests/test_no_llm_in_production.py`
   guards `src/`, `scripts/cron/`, `scripts/etl/`, `tests/` against
   any `anthropic` / `openai` / `google.generativeai` import. The
   reasoning happens client-side (in Claude), never inside our API.

## Distribution channels live today

- PyPI: `pip install autonomath-mcp` (v0.3.4)
- npm: `npx autonomath-mcp` (mirrored)
- MCP registry: https://github.com/modelcontextprotocol/registry
- Smithery, mcp.so, OpenTools, Glama, claude-mcp.com (5 registries submitted Wave 15)
- Cursor: `.mcp.json` shipped at repo root (auto-detect)
- ChatGPT: openapi.agent.gpt30.json (Actions Import, Wave 16 G1)

## Asks

1. Listing in the Claude Project / partnerships marketplace if you maintain one.
2. Feedback on the MCP tool surface (139 tools may be too many for one
   server — we can split into 4 servers by cohort if you prefer).
3. Any safety / disclaimer pattern Anthropic would like us to adopt.

## Material to verify our claims

- Public site: https://jpcite.com
- Source code: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- OpenAPI: https://jpcite.com/openapi.agent.gpt30.json (30-path GPT slim)
            https://jpcite.com/openapi/v1.json (full 219 paths)
- MCP manifest: https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/server.json
- Operator: Bookyou Inc., 〒112-0006 東京都文京区小日向2-22-1
- T8010001213708 (qualified-invoice issuer, registered 令和7年5月12日)

Happy to provide read-only API keys for diligence.

Best regards,
Shigetoshi Umeda
Bookyou Inc.
info@bookyou.net
https://jpcite.com

---

(日本語)

Anthropic Partnerships ご担当者様

Bookyou株式会社 代表取締役 梅田茂利と申します。Anthropic 様の Claude
Project / MCP partnerships directory への jpcite 掲載をご検討いただけ
ないかと存じ、ご連絡差し上げます。

jpcite は日本の公的制度 (補助金・融資・税制・認定・法令・判例・行政
処分・適格事業者) を一次出典 (官公庁・自治体・公庫・国税庁・e-Gov 等)
付きで横断検索する evidence DB で、REST API および MCP stdio server の
両方で公開しています (2026-05-11 時点で 139 MCP tools / 11,601 programs
/ 6,493 法令全文 + 9,484 catalog / 8.29 GB unified SQLite)。

- 一次出典のみ (aggregator 排除)
- 全 sensitive tool に disclaimer envelope (税理士法 §52 等)
- ¥3/req 完全従量、anonymous tier 3 req/日 無料
- LLM をサーバ内で呼ばない (推論は Claude 側に完全に任せる)

ご検討よろしくお願い申し上げます。

Bookyou株式会社
梅田茂利
info@bookyou.net
https://jpcite.com
```

## 3. Attach (mail 本文 + URL)

| item | URL |
| --- | --- |
| OpenAPI (30-path slim) | https://jpcite.com/openapi.agent.gpt30.json |
| OpenAPI (full 219 path) | https://jpcite.com/openapi/v1.json |
| MCP server.json | https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/server.json |
| llms.txt | https://jpcite.com/llms.txt |
| Privacy | https://jpcite.com/privacy.html |
| Pricing | https://jpcite.com/pricing.html |

## 4. SMTP 送信経路

`tools/offline/submit_claude_project_mail.py` を本セッションで作成 (G2/G3)。

| 項目 | 値 |
| --- | --- |
| SMTP server | `s374.xrea.com:587` (STARTTLS) |
| SMTP user | `info@bookyou.net` |
| SMTP password | `XREA_SMTP_PASSWORD` (`.env.local`) |
| From | info@bookyou.net |
| To | partnerships@anthropic.com |
| 文字符号化 | UTF-8 (Japanese parts) |

`reference_secrets_store` (memory) と `reference_bookyou_mail` (memory)
の手順を踏襲する。LLM API は使わない (送信は SMTP plain)。

## 5. 真 user 操作のみ (Claude 代行不可)

1. **partnerships@anthropic.com からの返信を info@bookyou.net で受信** (xrea webmail)
2. **招待コード受領後の Claude.ai workspace 追加** (CAPTCHA + 招待 token)
3. **Workspace marketplace の Publish ボタン押下** (実物の Anthropic 内画面)
4. **Anthropic から DPA 等の契約書 inbound が来た場合の signing**
   (zero-touch 原則上、DPA negotiation は **しない**。返信が来たら
   user に転送するだけ、契約条項調整は user 判断)

## 6. submission 後の monitoring

- Anthropic からの返信は xrea inbox 経由 (Postmark とは別経路)
- 返信が 30 日無い場合は **再送しない** (organic only / no cold outreach)
- 公式 partnerships directory 公開時に jpcite が出るか週次 grep
  (Wave 22 `competitive-watch.yml` workflow)

## 7. NG パターン (絶対やらない)

| やらない | 理由 |
| --- | --- |
| cold outreach の連投 | organic only / spam 認定 risk |
| LinkedIn / X DM での営業 | 1:1 営業は zero-touch 違反 |
| DPA / MSA negotiation | solo + zero-touch 原則 (memory) |
| 旧 brand (AutonoMath / jpintel) で営業 | 商標衝突 (memory) |
| MVP / Phase / フェーズ提案 | 禁句 (memory) |

## 8. 文責

- 起案 2026-05-11 (Wave 16 G2, jpcite session)
- 送信 attempt: `tools/offline/submit_claude_project_mail.py` で実行
- 送信状況 (success / fail / queued) は同スクリプトの stdout に出力
