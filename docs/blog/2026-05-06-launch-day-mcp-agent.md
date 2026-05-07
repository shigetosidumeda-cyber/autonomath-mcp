---
title: "jpcite: 日本の公的制度データを AI クライアントに渡す MCP サーバー"
description: "jpcite ローンチ記事 — Claude Desktop や Cursor から、日本の補助金・融資・税制・法令データを出典付きで検索する MCP サーバー。"
tags:
  - mcp
  - claude
  - llm
  - python
  - japan
published: false
---

# jpcite: 日本の公的制度データを AI クライアントに渡す MCP サーバー

LLM に「東京都で使える設備投資補助金を教えて」と聞くと、古い制度名、終了済みの募集回、出典不明の URL が混ざることがあります。

これはモデルの能力だけの問題ではありません。日本の制度情報が、省庁、都道府県、市区町村、公庫、PDF、Q&A、別紙に分散しているためです。

jpcite は MCP サーバーとして、補助金・融資・税制・認定・法令・採択事例・行政処分などを AI クライアントへ渡します。返却データには、可能な限り `source_url` と `source_fetched_at` を含めます。

## 30 秒でセットアップ

`~/Library/Application Support/Claude/claude_desktop_config.json` に追加します。

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

`uvx` がなければ、`pip install autonomath-mcp` のあと `command` を `"autonomath-mcp"` に変えてください。

!!! info "API key"
    匿名 3 req/日 per IP までは API key なしで試せます。それ以上利用する場合は `JPCITE_API_KEY` を設定してください。

    ```json
    {
      "mcpServers": {
        "jpcite": {
          "command": "uvx",
          "args": ["autonomath-mcp"],
          "env": {
            "JPCITE_API_KEY": "am_xxxxxxxxxxxxxxxx"
          }
        }
      }
    }
    ```

## 使い方の例

**ユーザー**

> 埼玉県で、設備投資に使える補助金を上限額の大きい順に 5 件教えて。出典も付けて。

**AI クライアントのツール呼び出し例**

```python
search_programs(
    q="設備投資",
    prefecture="埼玉県",
    limit=5
)
```

**ユーザー**

> このうち 2 つを同時に使うとき、注意点はある？

**AI クライアントのツール呼び出し例**

```python
check_exclusions(
    program_ids=["UNI-1111111111", "UNI-2222222222"]
)
```

AI クライアントは、検索、詳細取得、併用チェック、根拠資料の取得を必要に応じて組み合わせられます。

## 主なツール

| 用途 | ツール |
|---|---|
| 制度検索 | `search_programs` |
| 制度詳細 | `get_program` |
| 複数制度の比較 | `batch_get_programs` |
| 併用チェック | `check_exclusions` |
| 採択事例 | `search_case_studies` |
| 融資 | `search_loan_programs` |
| 行政処分 | `search_enforcement_cases` |
| 法令 | `search_laws` |
| 税務公開資料 | `find_saiketsu` / `cite_tsutatsu` |
| 適格請求書発行事業者 | `search_invoice_registrants` |
| 出典パケット | `get_evidence_packet` |

## jpcite がやること、やらないこと

jpcite は、公開資料を検索し、構造化し、出典付きで返します。jpcite サーバー側で外部 LLM API は呼びません。

一方で、jpcite は税務助言、法律相談、申請代行、採択確率の保証を行いません。AI クライアントが最終回答を作る前に、`source_url` の原文と取得時刻を確認してください。

## 価格

- **¥3/billable unit 税別** (税込 ¥3.30)
- 匿名 3 req/日 per IP は無料
- 月額固定、シート課金、年間最低額はありません

## まとめ

- AI クライアントから日本の公的制度データを出典付きで検索できる
- REST API と MCP の両方で利用できる
- LLM に大量の Web 検索をさせる前に、構造化済みの資料を渡せる
- 最終判断は一次資料、担当窓口、専門家で確認する

**jpcite:** <https://jpcite.com>
