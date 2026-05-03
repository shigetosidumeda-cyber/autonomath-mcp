# R19 — Gemini に jpcite を function declaration で渡す

Google Gemini API の `tools` (function declarations) で jpcite の主要 5 ツールを露出し、Gemini agent が補助金 / 法令 query で自動呼出する。

- **Audience (cohort)**: All cohorts (Gemini ユーザー / Vertex AI 利用社内アプリ)
- **Use case**: 自社の Gemini-backed アプリに「補助金 fact tool」を 1 declaration で追加
- **Disclaimer**: §52 / §72 / §1 (応答に `_disclaimer` envelope が乗る)
- **Cost**: ¥0 declaration + ¥3/call (jpcite 側) + Gemini API 料金

## TL;DR

Gemini の function calling は OpenAI と同形式で declaration を渡せる。jpcite の主要 5 endpoint を JSON で宣言し、`function_call` 発火時に jpcite REST に転送する thin proxy を 1 ハンドラに書くだけ。

## Sample (python)

```python
import google.generativeai as genai
import requests, os

JPCITE = "https://api.jpcite.com"
HEADERS = {"X-API-Key": os.environ["JPCITE_API_KEY"]}

TOOLS = [{
    "function_declarations": [
        {
            "name": "jpcite_search_programs",
            "description": "日本の補助金 / 助成金 / 融資 / 税制 / 認定制度を都道府県 × 業種 × 用途で検索",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "FTS5 keyword (例: 設備投資)"},
                    "prefecture": {"type": "string"},
                    "tier": {"type": "array", "items": {"type": "string", "enum": ["S","A","B","C"]}},
                    "limit": {"type": "integer"},
                },
                "required": ["q"],
            },
        },
        # 他: jpcite_get_program / jpcite_search_laws / jpcite_search_case_studies / jpcite_check_exclusions
    ]
}]

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-1.5-pro", tools=TOOLS)

resp = model.generate_content(
    "東京都の設備投資補助金を tier=S,A で 5 件、出典 URL 付きで列挙して",
)

# function_call が返ったら jpcite に転送
for part in resp.candidates[0].content.parts:
    fc = getattr(part, "function_call", None)
    if fc and fc.name == "jpcite_search_programs":
        r = requests.get(f"{JPCITE}/v1/programs/search",
                         params=dict(fc.args), headers=HEADERS).json()
        # r を Gemini に function_response として返し、最終回答 generate
        ...
```

## Expected output (function_call payload)

```json
{
  "function_call": {
    "name": "jpcite_search_programs",
    "args": {
      "q": "設備投資",
      "prefecture": "東京都",
      "tier": ["S", "A"],
      "limit": 5
    }
  }
}
```

jpcite からの response (`results[].source_url` / `tier` / `_disclaimer`) を Gemini に function_response として返し、Gemini が要約 + 出典付き応答を生成。

## 代替手段 vs jpcite cost

| 手段 | per-query | 備考 |
|---|---|---|
| Gemini 単体 (Google Search grounding 含む) | grounding 料金 + LLM 料金 | 出典は出るが補助金分野は noise 多 |
| 自社 corpus + Vertex AI Search | corpus 構築 工数 + index 維持 | 月数十万 |
| Gemini + jpcite function call | **¥3/call** + Gemini 料金 | tier 厳密、`source_url` 一次のみ、`_disclaimer` 自動 |

**hallucination 低減 + 法的免責 envelope を Gemini agent 上で自動発火**。

## Caveat

- Gemini API の function calling は SDK の引数命名が随時変わる。本サンプルは `google-generativeai >= 0.7` 前提。
- `tools` declaration が長くなる場合は openapi-to-fc 変換を介して `/v1/openapi.agent.json` から自動生成するのが楽。

## 関連

- [R18 ChatGPT Custom GPT Action](r18-chatgpt-custom-gpt.md)
- [R20 OpenAI Agents SDK](r20-openai-agents.md)
- [API reference](../api-reference.md)
