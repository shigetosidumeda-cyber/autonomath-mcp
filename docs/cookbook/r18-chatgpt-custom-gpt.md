# R18 — ChatGPT Custom GPT に jpcite Action を入れる

ChatGPT の Custom GPT (GPT-Builder) の Actions に jpcite の **agent-safe OpenAPI** を import し、GPT が自動で `search_programs` 等を呼び出すようにする。

- **Audience (cohort)**: All cohorts (ChatGPT エンドユーザー / 顧問先共有 GPT 配布)
- **Use case**: 顧問先に「補助金を聞ける GPT」をリンクで配る、社内ナレッジ GPT に補助金 fact tool を追加
- **Disclaimer**: 行政書士法 §1 / 税理士法 §52 / 弁護士法 §72 (各レスポンスに `_disclaimer` envelope が自動付与)
- **Cost**: ¥0 GPT 設定 + ¥3/billable unit (jpcite 側) + ChatGPT Plus / Team 料金 (OpenAI 側)

## TL;DR

完全 OpenAPI (`/v1/openapi.json`) は ChatGPT Actions には広すぎる。Agent-safe subset (`/v1/openapi.agent.json`) を import すれば GPT が選択しやすい操作面に絞られる。

## Sample (GPT-Builder)

1. ChatGPT → Explore GPTs → Create → Configure → Actions → "Import from URL" を選ぶ。
2. URL 欄に以下を貼る:

   ```
   https://api.jpcite.com/v1/openapi.agent.json?src=cookbook_r18-chatgpt-custom-gpt
   ```

3. Authentication: **API Key** を選び、Auth Type = Custom, Header name = `X-API-Key`, Value = `jc_...` (jpcite ダッシュボードで発行)。
4. Privacy policy URL に `https://jpcite.com/compliance/privacy_policy/?src=cookbook_r18-chatgpt-custom-gpt` を入れる (Custom GPT 公開には必須)。
5. System prompt 例:

   ```
   You are a Japanese subsidy / tax / law assistant. ALWAYS call jpcite tools
   first to fetch facts (with source_url + source_fetched_at), then summarize.
   Never invent program names or amounts. If a known_gaps field is present,
   surface it to the user.
   ```

## Expected output (ChatGPT)

GPT がプロンプトを受けて `programs.search` (action) を発火し、結果を summarize:

```
[Action: jpcite.programs.search called]
1. ものづくり補助金 (UNI-...) — 締切 2026-06-30
   出典: https://portal.monodukuri-hojo.jp/ (取得: 2026-04-29)
2. 東京都中小企業設備投資支援補助金 — 締切 2026-07-15
   出典: https://www.tokyo-kosha.or.jp/... (取得: 2026-04-29)

※ 行政書士法 §1: 申請書面の作成は行政書士の独占業務です。
```

## 代替手段 vs jpcite cost

| 手段 | コスト (1 query) | 備考 |
|---|---|---|
| ChatGPT 単体 (browse) | 8-15 LLM call/query × ¥30-200 = **¥300-2,000** | hallucination 60%+, 出典は出るがアグリゲータ混在 |
| ChatGPT + 公式 web search のみ | 同上 | 一次資料 vs アグリゲータの判定なし |
| ChatGPT + jpcite Action | **¥3/call** + ChatGPT 料金 | tier 厳密、`source_url` 一次のみ、`_disclaimer` 自動 |

**約 100-650 倍の per-query コスト削減 + 出典信頼性の向上**。

## Caveat / 制約

- ChatGPT Custom GPT の Actions は **同期的** (long-running 不可)。jpcite endpoint は P95 < 500 ms に最適化済みで問題なし。
- GPT に渡す API key は ユーザー単位ではなく GPT 単位。**メーター API key を 1 つ専用に発行** し、ダッシュボードで `cap` を設定して使用上限を制御する。
- ChatGPT Free / 一部地域では Custom GPT 機能が利用できない場合がある (OpenAI 側制約)。

## 関連

- [R16 Claude Desktop install](r16-claude-desktop-install.md)
- [R19 Gemini extension](r19-gemini-extension.md)
- [API reference: agent-safe OpenAPI](../api-reference.md)
