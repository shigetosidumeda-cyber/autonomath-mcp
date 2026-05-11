---
title: "LangChain / LlamaIndex RAG"
slug: "r21-langchain-llamaindex-rag"
audience: "AI agent (LangChain/LlamaIndex)"
intent: "rag_setup"
tools: ["search_programs", "get_program_detail", "get_corp_360"]
artifact_type: "rag_pipeline.py"
billable_units_per_run: 1
seo_query: "LangChain LlamaIndex jpcite RAG ツール"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# LangChain / LlamaIndex RAG

## 想定 user
LangChain (0.3+) / LlamaIndex (0.10+) を使って RAG bot を構築する agent dev / SaaS 開発者 / 大学研究者で、補助金原文 (要綱本文) を検索コーパスに、メタデータ (program_id / tier / deadline / source_url) を構造化フィルタとして使う層。jpcite を 1 つの retrieval tool として登録し、agent 推論側で組み合わせ。LLM API の選定 (OpenAI / Anthropic / Bedrock / VertexAI / GROQ 等) は agent 構築者責任、本 recipe は jpcite tool wrapping のみ。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- `langchain` 0.3+ または `llama-index` 0.10+
- Python 3.10+ (3.11 推奨、async tool 利用時)
- (任意) Vector DB (Chroma / Pinecone / Weaviate / pgvector) — jpcite メタデータと併用するハイブリッド検索用

## 入力例
```python
from langchain.tools import Tool
from jpcite import Client
c = Client()
search_tool = Tool(
    name="jpcite_search",
    description="日本の補助金・税制を keyword + 業種 + 地域 で検索",
    func=lambda q: c.search_programs(keyword=q, limit=10),
)
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl "https://api.jpcite.com/v1/programs/search?keyword=ものづくり&prefecture=東京都&limit=5"

curl https://api.jpcite.com/v1/openapi.json | jq '.paths | keys | length'
```
### Python
```python
import os
from langchain.tools import Tool
from jpcite import Client
c = Client(api_key=os.environ.get("JPCITE_API_KEY"))
tools = [
    Tool(name="jpcite_search", description="補助金検索",
         func=lambda q: c.search_programs(keyword=q, limit=10)),
    Tool(name="jpcite_detail", description="補助金原文取得",
         func=lambda pid: c.get_program_detail(program_id=pid)),
    Tool(name="jpcite_corp", description="法人 360 度ビュー",
         func=lambda hb: c.get_corp_360(corp_number=hb)),
]
# agent 構築 (LLM は呼出側で初期化、本 recipe では具体的 LLM 非依存)
```
### TypeScript
```ts
import { DynamicTool } from "@langchain/core/tools";
import { jpcite } from "@jpcite/sdk";
const searchTool = new DynamicTool({
  name: "jpcite_search", description: "日本の補助金検索",
  func: async (q: string) => {
    const r = await jpcite.search_programs({ keyword: q, limit: 10 });
    return JSON.stringify(r);
  },
});
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/openapi.json",
  "tools_registered": ["jpcite_search", "jpcite_detail", "jpcite_corp"],
  "agent_invocation_example": {
    "user_query": "中小製造業向け補助金を 3 つ挙げて",
    "tool_calls": [
      {"tool": "jpcite_search", "args": {"keyword": "中小製造業", "limit": 3}},
      {"tool": "jpcite_detail", "args": {"program_id": "METI-MONOZUKURI-2026"}}
    ],
    "agent_response": "1. METI-MONOZUKURI-2026 (出典: ...) 2. ..."
  },
  "known_gaps": ["RAG コーパス保存は別途 vector DB", "LLM 部分は agent 構築者責任"]
}
```

## known gaps
- 補助金原文 PDF は別 endpoint (`get_program_detail` で本文 markdown + PDF URL を返却)
- Vector DB との連携は別 recipe、本 recipe は jpcite を retrieval tool として wrapping するまで
- LangChain 0.3 への migration で `initialize_agent` deprecated → `create_react_agent` 推奨
- LlamaIndex 0.10 系は `ServiceContext` → `Settings` API へ移行済
- 大量 doc embedding は jpcite ではなく Vector DB 側でローカルに行う設計

## 関連 tool
- `search_programs` (キーワード + 業種 + 地域 + tier、RAG の主力 retrieval)
- `get_program_detail` (補助金原文取得、agent への文脈注入)
- `get_corp_360` (法人 360 度ビュー、agent 推論側の事実 grounding)
- `list_adoptions` (採択履歴、類似事例検索)
- `apply_eligibility_chain_am` (排他ルールチェック、Wave 21)

## 関連 recipe
- [r17-chatgpt-custom-gpt](../r17-chatgpt-custom-gpt/) — ChatGPT Custom GPT、SDK 不使用パス
- [r19-codex-agents-sdk](../r19-codex-agents-sdk/) — Codex Agents SDK、コード生成型 agent
- [r22-n8n-zapier-webhook](../r22-n8n-zapier-webhook/) — n8n / Zapier、ノーコード接続

## billable_units 試算
- 1 req 1 unit × ¥3 = ¥3
- agent 1 query 平均 3-5 tool call = ¥9-15 / query
- 月 1,000 query = ¥9,000-15,000 / 月、税込 ¥9,900-16,500
- RAG embed 後の検索は keyword + LLM コスト (LLM 側別途)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- RAG 出力に jpcite 出典 (`source_url`) 明記
- agent SaaS への組込 OK、最終出力 (chat / レポート / PDF) に jpcite 出典明記
- LLM ベンダーの利用規約 (商用利用条項 + データ取扱) と併せて確認

## 業法 fence
- agent 出力は参考、税務 / 法務判断は資格者
- LLM ベンダー利用規約も併読 (OpenAI / Anthropic / Google / AWS / GROQ 等)
- 業法 fence (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1) — agent 出力は scaffold + 一次 URL まで
- 景表法 §5 — agent 出力は推定値含む可能性、最終判断は人間

## canonical_source_walkthrough

> 一次資料 / canonical source への walk-through。Wave 21 C6 で全 30 recipes に追加。

### 使う tool
- **MCP tool**: `REST API + LangChain Tool wrap`
- **REST endpoint**: `/v1/programs/search (RAG context)`
- **jpcite.com docs**: <https://jpcite.com/recipes/r21-langchain-llamaindex-rag/>

### expected output
- LangChain Tool.run() → JSON dump → vector embed → query
- 全 response に `fetched_at` (UTC ISO 8601) + `source_url` (一次資料 URL) 必須
- `_disclaimer` envelope (税理士法 §52 / 行政書士法 §1 / 司法書士法 §3 / 弁護士法 §72 等の業法 fence 該当時)

### 失敗時 recovery
- **404 Not Found**: LangChain 0.3+ 必須、旧版は tool spec mismatch
- **429 Too Many Requests**: API key 経由 ¥3/req、batch 化で cost 下げ
- **5xx / timeout**: 60s wait

### canonical source (一次資料)
- 国税庁 適格事業者公表サイト: <https://www.invoice-kohyo.nta.go.jp/>
- 中小企業庁 補助金一覧: <https://www.chusho.meti.go.jp/>
- e-Gov 法令検索: <https://laws.e-gov.go.jp/>
- 国立国会図書館 NDL: <https://www.ndl.go.jp/>
- jpcite 一次資料 license 表: <https://jpcite.com/legal/licenses>
