---
title: "ChatGPT Custom GPT 化"
slug: "r17-chatgpt-custom-gpt"
audience: "AI agent (ChatGPT)"
intent: "custom_gpt_setup"
tools: ["search_programs", "get_corp_360", "check_invoice_status"]
artifact_type: "openapi.agent.gpt30.json"
billable_units_per_run: 1
seo_query: "ChatGPT Custom GPT jpcite Action"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# ChatGPT Custom GPT 化

## 想定 user
ChatGPT Plus / Team / Enterprise を契約済の税理士事務所・行政書士事務所・中小企業診断士・補助金コンサルタント・社内担当者で、社内向け Custom GPT から jpcite API を呼び、所員・顧問先・社員からの質問に対して Evidence Packet と一次資料 URL を添えた回答案を作りたい層。Action 経由で jpcite API を呼ぶことで、ChatGPT の汎用知識ではなく 1 次資料 + corpus snapshot に基づく回答を返す。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- ChatGPT Plus / Team / Enterprise (Free / 基本プラン は Custom GPT 作成不可)
- GPT Builder 編集権限 (Team 以上で workspace admin 推奨)
- 公開 / 非公開 / 共有 (URL 限定) の運用方針

## 入力例
- GPT Builder > `Create a GPT` > `Configure` タブを開く
- `Actions` > `Add actions` > `Import from URL` > `https://jpcite.com/openapi.agent.gpt30.json` を貼付
- `Authentication` > `API Key` > Header name = `X-API-Key`、Value = `jc_...` 入力
- `Instructions` 末尾に追記: `必ず source_url と fetched_at を引用し、税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 抵触の個別助言は行わず一般情報のみ返す。`
- `Privacy policy URL` = `https://jpcite.com/privacy.html` を設定して Save

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl https://jpcite.com/openapi.agent.gpt30.json | jq '.paths | keys | length'

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/programs/search?keyword=ものづくり&prefecture=東京都&limit=5" | jq '.matches[] | {program_id, tier, source_url}'
```
### Python
```python
import os, requests
r = requests.get("https://api.jpcite.com/v1/programs/search",
    headers={"X-API-Key": os.environ["JPCITE_API_KEY"]},
    params={"keyword": "ものづくり", "prefecture": "東京都", "limit": 5})
for m in r.json()["matches"]:
    print(m["program_id"], m["tier"], m["source_url"])
```
### TypeScript
```ts
const r = await fetch(
  "https://api.jpcite.com/v1/programs/search?keyword=ものづくり&prefecture=東京都&limit=5",
  { headers: { "X-API-Key": process.env.JPCITE_API_KEY ?? "" } },
);
const d = await r.json();
for (const m of d.matches) console.log(m.program_id, m.tier, m.source_url);
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://jpcite.com/openapi.agent.gpt30.json",
  "actions_count": 30,
  "auth": "X-API-Key",
  "sample_conversation": [
    {
      "user": "東京都で使えるものづくり補助金を 3 つ教えて",
      "gpt_call": "search_programs(keyword='ものづくり', prefecture='東京都', limit=3)",
      "gpt_response": "1. METI-MONOZUKURI-2026 (tier=S, 上限 ¥12.5M, 締切 2026-07-31, 出典: ...)"
    }
  ],
  "known_gaps": ["Custom GPT は ChatGPT Plus/Team 限定", "Action は 30 endpoint 上限のため slim 版を採用"]
}
```

## known gaps
- Free ChatGPT (基本プラン) は Custom GPT 作成不可、Plus / Team / Enterprise 必須
- Action は 30 endpoint 上限のため full OpenAPI (302 REST paths) ではなく `openapi.agent.gpt30.json` (GPT Actions 30-path subset) を採用
- Custom GPT の Action 出力は ChatGPT 側で再生成される可能性があり、jpcite の生 JSON が完全に維持される保証はない
- Privacy policy URL を未設定だと Public 公開不可、Team / Enterprise の社内共有は workspace 内で完結
- Action error 時の retry は ChatGPT 側の挙動に依存、`X-API-Key` 設定ミスは `401 invalid_credentials`

## 関連 tool
- `search_programs` (キーワード + 業種 + 地域 + tier で絞り込み、Custom GPT の主力)
- `get_corp_360` (法人 360 度ビュー、KYC 系質問への応答)
- `check_invoice_status` (適格事業者状況確認、経理系 chatbot)
- `list_adoptions` (採択履歴縦覧)
- `get_program_detail` (補助金原文取得、要綱本文の引用)

## 関連 recipe
- [r16-claude-code-30sec](../r16-claude-code-30sec/index.md) — Claude Code 30 秒接続、エンジニア向け即時セットアップ
- [r18-cursor-mcp-setup](../r18-cursor-mcp-setup/index.md) — Cursor MCP 接続、IDE 内利用
- [r19-codex-agents-sdk](../r19-codex-agents-sdk/index.md) — Codex Agents SDK、Codex CLI 接続
- [r20-continue-cline](../r20-continue-cline/index.md) — Continue / Cline VSCode 拡張

## billable_units 試算
- Action 呼出 1 回 = 1 unit × ¥3 = ¥3
- 月 5,000 req (士業事務所所員 5-10 名で日 50 質問) = ¥15,000 / 月、税込 ¥16,500
- 月 20,000 req (大手事務所 30 名規模) = ¥60,000 / 月、税込 ¥66,000
- 初回設定は 5 分 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- Custom GPT 出力に jpcite 出典 (`source_url`) 明記
- 社内 chatbot 利用 OK、Public 公開時は OpenAI 利用規約と併せて確認
- Action 経由の API 呼出は jpcite 側で課金、ChatGPT 側の utterance 課金は OpenAI 規約に従う

## 業法 fence
- 税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 — agent 出力は参考、税務 / 法務 / 申請書面の個別助言は資格者
- 業務利用は OpenAI 利用規約 (商用利用条項 + データ取扱) と併せて確認
- Custom GPT の Instructions に「個別助言は行わない」旨を明記推奨
- 景表法 §5 — `tier` / `subsidy_rate` は推定 / 公示値、Custom GPT 出力末尾に注記推奨
