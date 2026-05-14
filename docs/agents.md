# Using jpcite from an AI agent

> Sample integrations for Anthropic Claude / OpenAI / Cursor / Continue / GPT Actions.
> All examples assume `JPCITE_API_KEY` is set (start anonymous with the 3 req/day free tier — no key needed).
> Last sync: 2026-05-11 (Wave 17 AX role-specific deep-dive).

## What jpcite gives an agent

| Surface | Endpoint | Auth | Cap |
|---------|----------|------|-----|
| REST API | `https://api.jpcite.com/v1/*` | Anonymous (3 req/day per IP, JST 翌日 00:00 reset) **or** `X-API-Key: jc_…` | Anon: 3 req/day. Auth: 税別 ¥3/billable unit (税込 ¥3.30). |
| MCP (stdio) | `pip install autonomath-mcp && autonomath-mcp` | API key via env (`JPCITE_API_KEY` / legacy `AUTONOMATH_API_KEY`) | Same as REST |
| MCP (Streamable HTTP) | `POST https://api.jpcite.com/mcp` | `X-API-Key` header | Same as REST |
| Static markdown | `https://jpcite.com/{path}.md` | None | No rate limit |
| OpenAPI 3.1 | `https://api.jpcite.com/v1/openapi.json` (static mirror: `https://jpcite.com/openapi/v1.json`) | None | n/a (306 paths) |
| Agent capability JSON | `https://jpcite.com/agent.json` | None | n/a |

## Sample 1 — Anthropic Claude (Tool use, REST)

```python
# tools/offline/example_claude_jpcite.py
# NOTE: this lives under tools/offline/ because it imports anthropic.
# Do NOT place this file under src/, scripts/cron/, scripts/etl/, or tests/.
# That is enforced by tests/test_no_llm_in_production.py.

import os
import anthropic
import requests

client = anthropic.Anthropic()

JPCITE_TOOLS = [{
    "name": "jpcite_search_programs",
    "description": "Search Japanese subsidy/loan/tax-incentive programs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "JA query like '中小企業 補助金 DX'"},
            "limit": {"type": "integer", "default": 5}
        },
        "required": ["q"]
    }
}]


def call_jpcite(name: str, args: dict) -> dict:
    if name == "jpcite_search_programs":
        r = requests.get(
            "https://api.jpcite.com/v1/programs/search",
            params={"q": args["q"], "limit": args.get("limit", 5)},
            headers={"X-API-Key": os.environ["JPCITE_API_KEY"]},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    raise ValueError(f"unknown tool: {name}")


def ask(user_msg: str) -> str:
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        tools=JPCITE_TOOLS,
        messages=[{"role": "user", "content": user_msg}],
    )
    while msg.stop_reason == "tool_use":
        tool_calls = [b for b in msg.content if b.type == "tool_use"]
        results = [
            {
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": str(call_jpcite(tc.name, tc.input)),
            }
            for tc in tool_calls
        ]
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            tools=JPCITE_TOOLS,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": msg.content},
                {"role": "user", "content": results},
            ],
        )
    return next(b.text for b in msg.content if b.type == "text")


if __name__ == "__main__":
    print(ask("DXに使える補助金を3件、出典URL付きで教えて"))
```

## Sample 2 — Anthropic Claude Desktop (MCP, stdio)

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "/Users/you/.venvs/jpcite/bin/autonomath-mcp",
      "env": {
        "JPCITE_API_KEY": "jc_live_xxx"
      }
    }
  }
}
```

After restart, Claude Desktop sees 151 tools under the `jpcite` namespace.

## Sample 3 — OpenAI Chat Completions (function calling, REST)

```python
# tools/offline/example_openai_jpcite.py
# Same offline-only placement rule as Sample 1.

import os
import openai
import requests

client = openai.OpenAI()

FUNCS = [{
    "type": "function",
    "function": {
        "name": "jpcite_search_programs",
        "description": "Search Japanese subsidy/loan/tax-incentive programs.",
        "parameters": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "limit": {"type": "integer", "default": 5}
            },
            "required": ["q"]
        }
    }
}]


def call_jpcite(args: dict) -> str:
    r = requests.get(
        "https://api.jpcite.com/v1/programs/search",
        params={"q": args["q"], "limit": args.get("limit", 5)},
        headers={"X-API-Key": os.environ["JPCITE_API_KEY"]},
        timeout=10,
    )
    r.raise_for_status()
    return r.text


def ask(user_msg: str) -> str:
    msgs = [{"role": "user", "content": user_msg}]
    rsp = client.chat.completions.create(
        model="gpt-4o",
        messages=msgs,
        tools=FUNCS,
    )
    choice = rsp.choices[0]
    while choice.finish_reason == "tool_calls":
        msgs.append(choice.message.model_dump())
        for tc in choice.message.tool_calls:
            args = __import__("json").loads(tc.function.arguments)
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": call_jpcite(args),
            })
        rsp = client.chat.completions.create(model="gpt-4o", messages=msgs, tools=FUNCS)
        choice = rsp.choices[0]
    return choice.message.content
```

## Sample 4 — GPT Actions (custom GPT)

Builder → Configure → Actions → Import from URL:

```
https://jpcite.com/openapi.agent.gpt30.json
```

This is the slim 30-tool subset purpose-built for GPT Actions (the full 302-path spec exceeds the GPT Actions size limit).

Authentication = "API Key" → "Custom" → Header name `X-API-Key`. Privacy policy = `https://jpcite.com/privacy.html`.

## Sample 5 — Cursor IDE (.mcp.json)

`.mcp.json` at repo root (Cursor reads it automatically):

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        "JPCITE_API_KEY": "${env:JPCITE_API_KEY}"
      }
    }
  }
}
```

Cursor surfaces the 151 jpcite tools alongside its built-in toolset.

## Sample 6 — Continue.dev (config.json)

```json
{
  "mcpServers": [
    {
      "name": "jpcite",
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": { "JPCITE_API_KEY": "${env:JPCITE_API_KEY}" }
    }
  ]
}
```

## Sample 7 — Anthropic Claude Code (.mcp.json in any repo)

Same shape as Cursor. Place at the repo root; Claude Code picks it up on session start.

## Sample 8 — Plain HTTP from anywhere

```bash
# Anonymous (3 req/day per IP)
curl -s "https://api.jpcite.com/v1/programs/search?q=DX&limit=3" | jq '.items[].title'

# Authenticated
curl -s -H "X-API-Key: $JPCITE_API_KEY" \
     "https://api.jpcite.com/v1/programs/search?q=DX&limit=3" \
	 | jq '.items[].title'
```

## Sample 9 — `claude -p` prompt mode

Use jpcite before asking Claude to reason over a Japanese public-program question. The packet is the small input Claude reads instead of repeated PDF/search context.

```bash
packet="$(
  curl -sS -X POST "https://api.jpcite.com/v1/evidence/packets/query" \
    -H "X-API-Key: ${JPCITE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
      "query_text": "東京都 製造業 設備投資 補助金",
      "limit": 5,
      "include_compression": true,
      "source_tokens_basis": "pdf_pages",
      "source_pdf_pages": 30,
      "input_token_price_jpy_per_1m": 300
    }'
)"

echo "$packet" | jq '{jpcite_cost_jpy, estimated_tokens_saved, source_count, known_gaps}'

claude -p "次の jpcite Evidence Packet だけを根拠に、候補制度、確認質問、known_gaps を日本語で短く整理して。専門判断として断定しないこと。

$packet"
```

## Sample 10 — GitHub Actions curl gate

```yaml
jobs:
  monthly-client-review:
    runs-on: ubuntu-latest
    steps:
      - name: Build compact evidence before agent prompt
        env:
          JPCITE_API_KEY: ${{ secrets.JPCITE_API_KEY }}
        run: |
          set -euo pipefail
          curl -fsS -X POST "https://api.jpcite.com/v1/evidence/packets/query" \
            -H "X-API-Key: ${JPCITE_API_KEY}" \
            -H "X-Client-Tag: client-review-2026-05" \
            -H "Content-Type: application/json" \
            -d '{
              "query_text": "顧問先 月次 補助金 税制 期限",
              "limit": 5,
              "include_compression": true,
              "source_tokens_basis": "token_count",
              "source_token_count": 18500,
              "input_token_price_jpy_per_1m": 300
            }' \
            | tee evidence-packet.json \
            | jq '{jpcite_cost_jpy, estimated_tokens_saved, source_count, known_gaps}'
```

## Static markdown access (no auth, no rate limit)

Every public HTML page has a `.md` sibling:

```
https://jpcite.com/programs/{slug}.html      → .md sibling
https://jpcite.com/cases/{id}.html           → /cases/{id}.md   (GitHub-style)
https://jpcite.com/laws/{slug}               → /laws/{slug}.md
https://jpcite.com/enforcement/{id}          → /enforcement/{id}.md
```

Frontmatter includes `canonical`, `lang`, `est_tokens`, `fetched_at`, `source_url`, `license`. For downstream indexing of public static pages, prefer the `.md` over the `.html` because it skips the HTML parser. For AI answers over jpcite corpora, call the evidence/output endpoints first so the model receives compact source packets instead of repeatedly reading long raw context.

## Compliance checklist for agents that resell jpcite output

- Cite `source_url` (first-party government URL from the response) in your output.
- Display `est_tokens` / `fetched_at` if your downstream user is a regulated profession (税理士 / 会計士 / 行政書士 / 社労士 / 司法書士).
- Respect the `_disclaimer` envelope on sensitive tools (§52 / §72 / §1 / §3 surfaces). Do not strip it.
- Surface "出典取得 YYYY-MM-DD" (when fetched) — never "最終更新" (currency claim). Past 景表法 / 消費者契約法 risk.

## See also

- `https://api.jpcite.com/v1/openapi.json` — full 306-path OpenAPI 3.1
- `https://jpcite.com/openapi/v1.json` — static mirror for crawlers/importers
- `https://jpcite.com/openapi.agent.gpt30.json` — slim 30-tool GPT-Actions subset
- `https://jpcite.com/agent.json` — agent capability summary
- `https://jpcite.com/.well-known/mcp.json` — MCP capability descriptor
- `https://jpcite.com/llms.txt` — site-wide AI ingestion index (llms.txt v2)
- `https://jpcite.com/robots.txt` — fine-grain brand-aware bot policy
- `docs/integrations/` — per-platform integration guides (Claude Desktop, Cursor, Continue, GPT Actions, etc.)
- `docs/quickstart/dev_5min.md` — 5-minute localhost → CF Pages preview
- `.cursorrules`, `.windsurfrules`, `.agent.md` — IDE / vendor-neutral context injection
- `CLAUDE.md` — full repo SOT (architecture + constraints)
