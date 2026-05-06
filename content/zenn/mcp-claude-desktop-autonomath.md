---
title: "Claude Desktop から日本の補助金 9,998 件を直接引ける MCP サーバーを書いた"
emoji: "🗂️"
type: "tech"
topics: ["mcp", "claude", "python", "llm"]
published: false
---

## 背景: Claude に「東京都の農業補助金」を聞くと何が起きるか

Claude Desktop に「東京都で使える農業補助金を教えて」と聞いてみたことがある人は、同じ体験をしているはずです。

- 制度名が 2020 年で止まっている
- 金額が一桁違う
- URL を踏むと 404
- そもそも実在しない制度を自信満々に提案してくる

これは Claude が悪いのではなく、LLM の学習データに日本の制度情報が薄いこと、そして「最終更新 2024-12」のような鮮度情報が存在しないことが原因です。補助金は年度ごとに改正されるので、学習データに書いてあった時点で既に古い。

この「hallucinate する制度情報を、LLM に正しいデータを渡すことで抑える」ための MCP サーバーとして **jpcite** を書きました。9,998 件の補助金・融資・税制・認定制度を一次資料 URL とセットで返します。

## MCP (Model Context Protocol) が解法である理由

MCP は Anthropic が 2024 年末に公開したプロトコルで、LLM が外部ツールを呼ぶための規格です。特徴は3点。

1. **tool の description が LLM に渡る** — 自然言語で「この tool はこう使う」と書ける
2. **stdio / SSE 両対応** — Claude Desktop はローカル stdio で動くのでレイテンシが低い
3. **クライアントが tool を自律的に選ぶ** — ユーザーが「検索して」と明示しなくても、質問の文脈から LLM が tool を選ぶ

既存の RAG パイプライン (embedding → vector search → prompt injection) と違い、MCP は **LLM 自身が何を検索するか決める**。これが制度情報と相性が良い。「東京都 かつ 農業 かつ 設備投資」のような複合条件を、LLM が質問から組み立てて API に投げてくれる。

## 30 秒でセットアップ

`~/Library/Application Support/Claude/claude_desktop_config.json` に以下を追加。

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

`uvx` が入っていない場合は `pip install autonomath-mcp` でもOK。その場合は `command: "autonomath-mcp"` と書く。

Claude Desktop を再起動すると、右下の金槌アイコンに `autonomath` の 139 ツール (31 コア + 16 autonomath) が並びます。

:::message
API key は匿名 50 req/月 per IP (JST 月初 00:00 リセット) までは不要です。それ以上使う場合は `env: { "AUTONOMATH_API_KEY": "..." }` を config に追加してください。課金は ¥3/req 税別 (税込 ¥3.30) の完全従量で、tier はありません。
:::

## 実際の会話例

筆者の Claude Desktop での実機ログを抜粋します。

**Turn 1 (user):** 埼玉県鴻巣市で 100ha の米農家をやっている法人が、設備投資で使える国の補助金を上限金額順に5件教えて。

**Claude (tool call):** `search_programs({"prefecture": "埼玉県", "target_types": ["法人"], "funding_purpose": ["設備投資"], "crop_categories": ["米"], "limit": 5, "sort": "amount_desc"})`

**Claude (回答):** 以下の5件がヒットしました。金額は上限です。
1. 農業経営基盤強化準備金制度 (全国, 税制, 準備金上限なし, 出典: 農水省 xxx)
2. 強い農業・担い手づくり総合支援交付金 (全国, 補助金, 上限5,000万円)
3. ...

**Turn 2 (user):** この中で、世帯所得 1200 万円だと除外されるものある？

**Claude (tool call):** `check_exclusions({"unified_ids": [...], "household_income": 12000000})`

**Claude (回答):** 3番目の「xxx交付金」は世帯所得 1000 万円以下という除外要件があります。残り4件は該当なし。

このやり取りで LLM は `search_programs` と `check_exclusions` を自律的に選んでいる。ユーザーは「検索して」とは一度も言っていない。

## 主要 MCP tool の使い分け (31 コア抜粋)

| tool | 使いどき | 典型的な引数 |
|------|---------|-------------|
| `search_programs` | 条件から制度を探す | prefecture, target_types, funding_purpose |
| `get_program` | 特定の unified_id の詳細を引く | unified_id |
| `list_exclusion_rules` | 除外ルール 181 本を一覧 | (なし) |
| `check_exclusions` | 候補制度に対して除外判定 | unified_ids[], 申請者属性 |
| `get_meta` | DB の件数・最終更新日を確認 | (なし) |

`get_meta` は地味だが重要で、「このデータは何日時点のものか」を LLM が自分で確認できる。古いデータを新しいかのように回答するのを抑えます。

## 16 autonomath tool (entity-fact DB)

v0.2.0 で追加された autonomath.db（7.3 GB, 読み取り専用）backed の 16 tool。
entity-fact semantic layer として **402,768 entities + 5.26M facts + 23,615 relations + 312k aliases** を
税制優遇 / 認定制度 / 法令 / 処分 / 融資 / 共済 の 9 record_kind 横断で検索できます。
FTS5 trigram + unicode61 + sqlite-vec の tiered index を併用。

| tool | 使いどき |
|------|---------|
| `search_tax_incentives` | 税制優遇制度を横断検索 |
| `search_certifications` | 認定制度を横断検索 |
| `list_open_programs` | 現在開催中の制度を一覧 |
| `enum_values_am` | autonomath 側の enum 値を取得 |
| `search_by_law` | 根拠法令から制度を逆引き |
| `active_programs_at` | 特定時点で有効だった制度を取得 |
| `related_programs` | 関連制度 (relation graph 経由) |
| `search_acceptance_stats_am` | 採択統計を entity-fact 経由で検索 |
| `intent_of` | 自然文から意図を推定 |
| `reason_answer` | 根拠付きで質問に答える |
| `get_am_tax_rule` | 税務ルール本体を取得 |
| `search_gx_programs_am` | GX 関連制度を横断検索 |
| `search_loans_am` | 融資商品を entity-fact 経由で検索 |
| `check_enforcement_am` | 行政処分詳細を照会 |
| `search_mutual_plans_am` | 共済プランを横断検索 |
| `get_law_article_am` | 法令条文を取得 |

## 注意点: 制度は毎年改正される

API は毎週更新していますが、制度そのものは年度替わりで消える・条件が変わる・金額が変わる。なので tool の返り値には必ず `source_url` (一次資料 URL) が入っています。

:::message alert
ユーザーに金額や期限を最終的に伝える前に、**必ず source_url を踏んで原文確認**してください。LLM に「このURL踏んで内容確認して」と追加で聞くのが現実的な運用です。jpcite は**予測はしない、データを出すだけ**という方針です (詳細は [補助金 API で『採択率予測』を実装しなかった理由](./why-no-shouritsu-yosoku) を参照)。
:::

## まとめ

- MCP は「LLM に鮮度の高いデータを渡す」用途と相性が良い
- jpcite は 9,998 件の制度を stdio MCP 139 ツール (31 コア + 16 autonomath) (protocol 2025-06-18) で提供、¥3/req 税別 (税込 ¥3.30) 従量、匿名 50 req/月 per IP 無料 (JST 月初リセット)
- 制度改正が早いので、一次資料 URL を必ず踏む運用にする

関連記事:
- [補助金 API で『採択率予測』を実装しなかった理由](./why-no-shouritsu-yosoku)
- [2026 年、LLM 引用 SEO (GEO) の実測レポート](./llm-citation-seo-2026)
- [LLM エージェントが使う API を設計する時に守った 7 つの前提](./api-design-7-principles)

リンク:
- PyPI: https://pypi.org/project/autonomath-mcp/
- GitHub: https://github.com/bookyou/autonomath-mcp

---

jpcite: https://jpcite.com (Bookyou株式会社)
