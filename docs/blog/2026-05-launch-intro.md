---
title: "jpcite launch — 日本制度を 1 query で AI に聞く"
description: "jpcite ローンチ記事 (Intro) — 11,601 件の検索対象制度を REST + MCP 155 ツールで横断検索。¥3/billable unit 完全従量、匿名 3 req/日 per IP free。"
tags:
  - api
  - mcp
  - llm
  - japan
  - launch
published: false
date: 2026-05-06
author: Bookyou株式会社
---

# jpcite launch — 日本制度を 1 query で AI に聞く

> 公開日: 2026-05-06 / Canonical: <https://jpcite.com>

## なぜ作ったか — 「省庁ガチャ」を消すため

「うちの会社で使える補助金はありますか」「インボイス対応の特例はありますか」「この資金繰りに合う融資制度は？」
この種の質問に答えるには、**経産省・農水省・中小企業庁・47 都道府県・市区町村・公庫・国税庁** を一つひとつ歩き、
PDF を開き、要綱の脚注から「併用したら失格」のルールを掘り起こす必要があります。

jpcite はその発見・互換・実績確認のレイヤーを **1 本の REST API + MCP サーバー** に畳み込みました。

## なにが入っているか (2026-05-06 時点)

| データ | 件数 | 出典 |
|---|---|---|
| 補助金・融資・税制・認定 | **11,601 検索対象** | 47 都道府県 + 主要省庁・自治体等の公開資料 (出典 URL + 取得時刻つき) |
| 採択事例 | **2,286** | 経産省・農水省ほか採択結果一次資料 |
| 融資 | **108** | 公庫・信金・地銀の要綱 |
| 行政処分 | **1,185** | 各省庁公示 |
| 法令 | **法令メタデータ・条文参照** | e-Gov 法令 API (record により coverage は異なります) |
| 税制ルール | **50** | 国税庁通達 + 措置法 |
| 適格請求書事業者 | **13,801** | 国税庁公表サイト |
| 併用チェックルール | **181** | 一次資料に基づく併用注意点 |

## どう叩くか

### REST API

```bash
curl -sS https://api.jpcite.com/v1/programs/search \
  -G --data-urlencode 'q=設備投資 中小企業' \
  --data-urlencode 'prefecture=東京' \
  --data-urlencode 'limit=10'
```

### MCP (Claude Desktop / Cursor / ChatGPT)

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

155 個の MCP ツールを Claude / Cursor / ChatGPT などの AI クライアントから呼べます。

## 価格

- **¥3/billable unit** 税抜 (税込 ¥3.30) — 完全従量
- **匿名 3 req/日 per IP** — JST 翌日 00:00 リセット、API key 不要
- 月額固定 / シート / 年間最低なし。

## 想定 audience (5)

1. **税理士** — 法人税の措置法特例を Claude から walkthrough
2. **行政書士** — 補助金 + 融資 + 許認可を 1 call で束ねる
3. **SMB 経営者** — LINE notifications と web handoff で制度確認の続きを受け取る
4. **VC / M&A advisor** — 法人番号で行政処分歴・採択歴・適格請求書を 1 query で due diligence
5. **AI agent developer** — MCP / REST どちらでも統合、155 ツール全部叩ける

## なぜ今出すか

LLM (ChatGPT / Claude / Gemini) が日本語の制度を知らないのは、データが **散らばって、PDF で、機械可読でなく、ライセンスが曖昧** だからです。
jpcite は **(a) primary-source lineage を主要な公開行で担保**、**(b) 全文検索 + ベクトル検索 で機械可読**、**(c) ¥3 で誰でも叩ける** の 3 点で、その溝を埋めます。

## 次のステップ

- [Getting Started (5 分)](https://jpcite.com/docs/getting-started/)
- [API リファレンス](https://jpcite.com/docs/api-reference/)
- [MCP ツール一覧](https://jpcite.com/docs/mcp-tools/)
- [pricing.md](https://jpcite.com/docs/pricing/)

質問・要望は [info@bookyou.net](mailto:info@bookyou.net) または GitHub issues へ。

---

© 2026 Bookyou株式会社 · info@bookyou.net · jpcite
