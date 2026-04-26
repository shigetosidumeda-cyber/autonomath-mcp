---
title: "AutonoMath launch — 1 query で AI に聞く"
description: "AutonoMath ローンチ — 13,578 件の補助金・融資・税制・認定を REST + MCP 72 ツールで横断検索。¥3/req 完全従量、50 req/月 per IP 無料。"
tags:
  - api
  - mcp
  - llm
  - japan
  - launch
  - claude
  - python
published: true
date: 2026-05-06
author: Bookyou株式会社 (T8010001213708)
---

> **operator-only file**: launch day Zenn / blog publish 用 final 版。
> B10 の `docs/blog/2026-05-launch-intro.md` (published: false) を frontmatter `published: true` + 数値最新化したものです。
> mkdocs.yml `exclude_docs` で公開除外しているのは launch 直前 review のため。
> launch day に operator が Zenn (https://zenn.dev) または自社 blog にコピペ publish 想定。

# AutonoMath launch — 日本制度を 1 query で AI に聞く

> 公開日: 2026-05-06 / 運営: Bookyou株式会社 (T8010001213708) / Canonical: <https://autonomath.ai>

## なぜ作ったか — 「省庁ガチャ」を消すため

「うちの会社で使える補助金はありますか」「インボイス対応の特例はありますか」「この資金繰りに合う融資制度は?」

この種の質問に答えるには、**経産省・農水省・中小企業庁・47 都道府県・市区町村・公庫・国税庁** を一つひとつ歩き、
PDF を開き、要綱の脚注から「併用したら失格」のルールを掘り起こす必要があります。

AutonoMath はその発見・互換・実績確認のレイヤーを **1 本の REST API + MCP サーバー** に畳み込みました。

## なにが入っているか (2026-05-06 時点)

| データ | 件数 | 出典 |
|---|---|---|
| 補助金・融資・税制・認定 (programs, tier S/A/B/C) | **13,578** | 47 都道府県 + 全省庁一次資料 (出典 URL + 取得時刻つき) |
| 採択事例 (case_studies) | **2,286** | 経産省・農水省ほか採択結果一次資料 |
| 融資 (loan_programs, 担保/個人保証人/第三者保証人 三軸) | **108** | 公庫・信金・地銀の要綱 |
| 行政処分 (enforcement_cases) | **1,185** | 各省庁公示 |
| 法令 (laws, e-Gov CC-BY) | **9,484** | e-Gov 法令 API |
| 税制 ruleset (インボイス・電帳法) | **35** | 国税庁通達 + 措置法 |
| 適格請求書事業者 (invoice_registrants, PDL v1.0) | **13,801** (delta) | 国税庁公表サイト |
| 排他・前提ルール | **181** | 要綱から抽出 (35 hand-seeded + 146 auto-extracted) |
| autonomath エンティティ | **503,930** + 6.12M facts + 23,805 relations | EAV エンティティ事実 DB (V4 + Phase A absorption 完了) |

## どう叩くか

### REST API

```bash
curl -sS https://api.autonomath.ai/v1/programs/search \
  -G --data-urlencode 'q=設備投資 中小企業' \
  --data-urlencode 'prefecture=東京' \
  --data-urlencode 'limit=10'
```

### MCP (Claude Desktop / Cursor / ChatGPT)

`claude_desktop_config.json` に以下を追加:

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

**72 ツール** (38 jpintel + 28 autonomath = 17 V1 + 4 V4 universal + 7 Phase A absorption、protocol 2025-06-18) が即座に Claude Desktop / Cursor / ChatGPT から呼べます。

代表的な MCP ツール例:

- `search_programs` — 制度横断検索 (FTS5 trigram)
- `prescreen` — 業種・所在地・規模で適合制度を絞り込み
- `subsidy_combo_finder` — 排他ルール 181 本を踏まえた併用候補
- `trace_program_to_law` — 制度 → 根拠法令 / 条文単位 trace
- `combined_compliance_check` — 制度 + 行政処分 + 適格事業者を一括 DD

## 価格

- **¥3/request** 税抜 (税込 ¥3.30) — 完全従量
- **匿名 50 req/月 per IP** — JST 月初 00:00 リセット、API key 不要
- 月額固定 / シート / 年間最低なし

AI agent の workflow が「Pro user / Free user」semantics を持たないため、tier ベース価格を意図的に廃止しました。

## 想定 audience (5)

1. **AI agent 開発者** — Claude / Cursor / ChatGPT の Manifest 1 行で 72 ツール、SDK 不要
2. **税理士 / 認定支援機関** — 措置法特例を Claude から条文単位で walkthrough
3. **行政書士** — 補助金 + 融資 + 許認可を 1 call で束ねる
4. **SMB 経営者 / 経理** — ChatGPT で「うちの業種で使える制度ある?」を月 50 件まで無料
5. **VC / M&A advisor / DD** — 法人番号で行政処分歴・採択歴・適格請求書を 1 query で due diligence

## 技術 stack (はまった所込み)

- Python + FastAPI (REST)
- FastMCP (stdio MCP server, protocol 2025-06-18)
- SQLite FTS5 trigram (日本語複合語検索)
- sqlite-vec (503,930 entities の vec layer・段階的有効化中、現状は FTS5 trigram + unicode61 がプライマリ)
- Fly.io Tokyo (nrt) ホスティング
- Stripe Metered + Stripe Tax (JP インボイス対応)
- Cloudflare Pages (静的サイト)

技術的にはまった所:

1. **FTS5 trigram の偽 single-kanji 一致**
   `税額控除` で検索すると `ふるさと納税` も hit。phrase query (引用符) で対処。
2. **MCP プロトコル 2025-06-18 の 72 ツール schema validation**
   FastMCP の register pattern + tool schema 整合
3. **適格事業者の差分配信 (NTA PDL v1.0)**
   月次フルバルク + 日次 delta、JST/UTC 境界処理
4. **Stripe checkout の `consent_collection` pitfall**
   `terms_of_service: required` で 500 を踏んだ事例。`custom_text.submit.message` で回避

## なぜ今出すか

LLM (ChatGPT / Claude / Gemini) が日本語の制度を知らないのは、データが **散らばって、PDF で、機械可読でなく、ライセンスが曖昧** だからです。

AutonoMath は **(a) primary-source lineage を 99%+ 担保**、**(b) FTS5 + sqlite-vec で機械可読**、**(c) ¥3 で誰でも叩ける** の 3 点で、その溝を埋めます。

aggregator (noukaweb / hojyokin-portal 等) は source_url から完全 ban しています。過去の業界事例が 詐欺 risk を生んだ反省で、一次資料引用以外は採用していません。

## 次のステップ

- [Getting Started (5 分)](https://autonomath.ai/docs/getting-started/)
- [API リファレンス](https://autonomath.ai/docs/api-reference/)
- [MCP ツール一覧](https://autonomath.ai/docs/mcp-tools/)
- [pricing.md](https://autonomath.ai/docs/pricing/)
- GitHub: <https://github.com/[USERNAME]/[REPO]>
- PyPI: <https://pypi.org/project/autonomath-mcp/>

質問・要望は [info@bookyou.net](mailto:info@bookyou.net) または GitHub issues へ。

電話・対面・営業 cold call は zero-touch 方針のため対応していません。

---

© 2026 Bookyou株式会社 (T8010001213708) · info@bookyou.net · AutonoMath
