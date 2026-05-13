# R20 — OpenAI Agents SDK で jpcite を MCP サーバーとして使う

OpenAI Agents SDK の `MCPServerStdio` 1-liner で jpcite の 151 ツールを agent から即座に使えるようにする。

- **Audience (cohort)**: All cohorts (OpenAI Agents で社内アプリを書く developer)
- **Use case**: 自社 agent パイプラインに「日本の制度 fact tool」を 1 行で追加、ChatGPT より細粒度に制御
- **Disclaimer**: §52 / §72 / §1 (応答に `_disclaimer` envelope が自動付与)
- **Cost**: ¥0 setup + ¥3/call (jpcite 側) + OpenAI API 料金

## TL;DR

OpenAI Agents SDK は MCP サーバーを stdio 経由で標準サポート。`uvx autonomath-mcp` を `MCPServerStdio` で包むだけで jpcite の 151 ツールが Agent の tool surface に乗る。

## Sample (python)

```python
import asyncio, os
from agents import Agent, Runner
from agents.mcp.server import MCPServerStdio

async def main():
    async with MCPServerStdio(
        name="jpcite",
        params={
            "command": "uvx",
            "args": ["autonomath-mcp"],
            "env": {"JPCITE_API_KEY": os.environ["JPCITE_API_KEY"]},
        },
    ) as jpcite:
        agent = Agent(
            name="補助金 agent",
            model="gpt-4o-mini",
            instructions=(
                "日本の補助金 / 法令 / 採択事例を答える時は、必ず jpcite の "
                "tool を最初に呼んで source_url + source_fetched_at を取得して "
                "から要約せよ。known_gaps があれば必ず開示せよ。"
            ),
            mcp_servers=[jpcite],
        )

        result = await Runner.run(
            agent,
            "東京都で募集中の設備投資補助金を tier=S,A で 5 件、出典 URL 付きで",
        )
        print(result.final_output)

asyncio.run(main())
```

## Expected output (Agent 最終応答)

```
1. ものづくり補助金 (一般型) — 締切 2026-06-30
   出典: https://portal.monodukuri-hojo.jp/ (取得: 2026-04-29)
2. 東京都中小企業設備投資支援補助金 — 締切 2026-07-15
   出典: https://www.tokyo-kosha.or.jp/... (取得: 2026-04-29)
   ...
※ 行政書士法 §1 / 税理士法 §52: 申請書面作成・税務判定は専門家へ。
```

## 代替手段 vs jpcite cost

| 手段 | per-query | 備考 |
|---|---|---|
| OpenAI Agent + web_search tool のみ | LLM + 検索コスト | 補助金分野は出典が荒い + hallucination |
| OpenAI Agent + 自前 RAG | corpus 構築 工数 | 月数十万 |
| OpenAI Agent + jpcite MCP | **¥3/call** + LLM 料金 | tier 厳密、`source_url` 一次のみ、`_disclaimer` 自動 |

**SDK 1 行追加で 151 ツールを agent surface に乗せられる**。OpenAI 内部で `mcp_servers=[...]` がそのまま tool registration になるため、Agent が自動で適切なツールを選ぶ。

## Caveat

- `agents` SDK は OpenAI 公式 (`openai-agents-python`) の前提。バージョンが古いと `MCPServerStdio` のシグネチャが違う場合あり。
- jpcite MCP の `_disclaimer` envelope を Agent が "見て" 応答に転記するためには、上記 `instructions` で明示するのが確実。
- macOS 上の `uvx` 初回実行は数十秒かかる場合がある (キャッシュ後は < 1 秒)。

## 関連

- [R16 Claude Desktop install](r16-claude-desktop-install.md)
- [R17 Cursor MCP](r17-cursor-mcp.md)
- [MCP tools 一覧](../mcp-tools.md)
