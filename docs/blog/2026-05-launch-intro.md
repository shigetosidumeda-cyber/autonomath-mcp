---
title: "AutonoMath launch — 日本制度を 1 query で AI に聞く"
description: "AutonoMath ローンチ記事 (Intro) — 13,578 件の補助金・融資・税制・認定を REST + MCP 72 ツールで横断検索。¥3/req 完全従量、50 req/月 per IP free。"
tags:
  - api
  - mcp
  - llm
  - japan
  - launch
published: false
date: 2026-05-06
author: Bookyou株式会社 (T8010001213708)
---

# AutonoMath launch — 日本制度を 1 query で AI に聞く

> 公開日: 2026-05-06 / 運営: Bookyou株式会社 (T8010001213708) / Canonical: <https://autonomath.ai>

## なぜ作ったか — 「省庁ガチャ」を消すため

「うちの会社で使える補助金はありますか」「インボイス対応の特例はありますか」「この資金繰りに合う融資制度は？」
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
| autonomath エンティティ | **503,930** + 6.12M facts + 23,805 relations | EAV エンティティ事実 DB (V4 + Phase A absorption 済み) |

## どう叩くか

### REST API

```bash
curl -sS https://api.autonomath.ai/v1/programs/search \
  -G --data-urlencode 'q=設備投資 中小企業' \
  --data-urlencode 'prefecture=東京' \
  --data-urlencode 'limit=10'
```

### MCP (Claude Desktop / Cursor / ChatGPT)

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

72 ツール (39 jpintel + 33 autonomath at default gates) が即座に Claude / Cursor / ChatGPT から呼べます。

## 価格

- **¥3/request** 税抜 (税込 ¥3.30) — 完全従量
- **匿名 50 req/月 per IP** — JST 月初 00:00 リセット、API key 不要
- 月額固定 / シート / 年間最低なし。

## 想定 audience (5)

1. **税理士** — 法人税の措置法特例を Claude から walkthrough
2. **行政書士** — 補助金 + 融資 + 許認可を 1 call で束ねる
3. **SMB 経営者** — LINE で「うちの業種で使える制度ある？」を月 10 件まで無料
4. **VC / M&A advisor** — 法人番号で行政処分歴・採択歴・適格請求書を 1 query で due diligence
5. **AI agent developer** — MCP / REST どちらでも統合、72 ツール全部叩ける

## なぜ今出すか

LLM (ChatGPT / Claude / Gemini) が日本語の制度を知らないのは、データが **散らばって、PDF で、機械可読でなく、ライセンスが曖昧** だからです。
AutonoMath は **(a) primary-source lineage を 99%+ 担保**、**(b) FTS5 + sqlite-vec で機械可読**、**(c) ¥3 で誰でも叩ける** の 3 点で、その溝を埋めます。

## 次のステップ

- [Getting Started (5 分)](https://autonomath.ai/docs/getting-started/)
- [API リファレンス](https://autonomath.ai/docs/api-reference/)
- [MCP ツール一覧](https://autonomath.ai/docs/mcp-tools/)
- [pricing.md](https://autonomath.ai/docs/pricing/)

質問・要望は [info@bookyou.net](mailto:info@bookyou.net) または GitHub issues へ。

---

© 2026 Bookyou株式会社 (T8010001213708) · info@bookyou.net · AutonoMath
