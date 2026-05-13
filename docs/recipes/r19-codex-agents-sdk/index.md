---
title: "Codex Agents SDK 接続"
slug: "r19-codex-agents-sdk"
audience: "AI agent (Codex)"
intent: "codex_setup"
tools: ["search_programs", "get_corp_360", "list_adoptions"]
artifact_type: "codex_mcp_config.json"
billable_units_per_run: 1
seo_query: "Codex Agents SDK jpcite MCP"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Codex Agents SDK 接続

## 想定 user
OpenAI Codex CLI v1.0+ を使う agent dev / 自動化 pipeline 開発者で、Codex MCP tool として jpcite を 1 行で登録 (`codex mcp add jpcite -- uvx autonomath-mcp`) し、ターミナル内チャットから補助金検索・法人 360 度ビュー・適格事業者検証を呼び出す層。グローバル設定 `~/.codex/mcp.json` または repo 別の `.codex/mcp.json` のいずれも対応、Codex は MCP 標準準拠で Claude Code / Cursor と同じ config 形式が使える。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- OpenAI Codex CLI v1.0+ (`npm i -g @openai/codex` or homebrew)
- `uvx` (Astral uv): `curl -LsSf https://astral.sh/uv/install.sh | sh` 後シェル再起動
- (任意) repo 別 `.codex/mcp.json` 配置

## 入力例
```bash
# 1 行で MCP 登録
codex mcp add jpcite -- uvx autonomath-mcp

# 環境変数で API key 設定
codex mcp env jpcite JPCITE_API_KEY=jc_xxxxx
```

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {"JPCITE_API_KEY": "jc_..."}
    }
  }
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl https://api.jpcite.com/v1/healthz
# 期待: {"status":"ok","tools_default_gate":139}

codex --version
uvx --version
```
### Python
```python
import subprocess
subprocess.run(["uvx", "autonomath-mcp", "--help"], check=True)
```
### TypeScript
```ts
// Codex CLI 内のサンプル prompt:
// > jpcite で「IT 導入補助金」を search_programs し、tier=S/A の 5 件を source_url 付きで列挙
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/mcp",
  "tools_loaded_count": 139,
  "tools_sample": [
    "search_programs", "get_corp_360", "check_invoice_status",
    "list_adoptions", "search_tax_incentives",
    "apply_eligibility_chain_am", "pack_construction"
  ],
  "codex_cli_status": {"server": "jpcite", "status": "connected", "transport": "stdio"},
  "sample_chat": [
    {
      "user": "jpcite で「IT 導入補助金」を search_programs し、tier=S/A の 5 件を source_url 付きで列挙",
      "agent_response": "5 件 hit: meti-it-2026-r5 (tier=S, 出典: ...), tokyo-dx-2026 (tier=A, 出典: ...), ..."
    }
  ],
  "known_gaps": ["Codex CLI v1.0+ 必須", "uvx not found は curl -LsSf https://astral.sh/uv/install.sh | sh で解消"]
}
```

## known gaps
- Codex CLI v0.x は `mcp add` コマンド未実装、`~/.codex/mcp.json` 手動編集
- `uvx not found` は uv 未 install、`curl -LsSf https://astral.sh/uv/install.sh | sh` 後シェル再起動
- tools count 0 は `JPCITE_API_KEY` 未設定 or anon quota 切れ、key 設定 or 翌日 00:00 JST 待ち
- macOS Rosetta では `uvx` のバイナリパス調整必要なケースあり
- 大量並列 tool call は rate-limit に当たる可能性、順次呼出推奨

## 関連 tool
- `search_programs` (Codex chat の主力、キーワード補助金検索)
- `get_corp_360` (法人 360 度ビュー)
- `list_adoptions` (採択履歴縦覧)
- `check_invoice_status` (適格事業者状況)
- `get_program_detail` (補助金原文)

## 関連 recipe
- [r16-claude-code-30sec](../r16-claude-code-30sec/index.md) — Claude Code CLI、Anthropic 公式
- [r17-chatgpt-custom-gpt](../r17-chatgpt-custom-gpt/index.md) — ChatGPT Custom GPT
- [r18-cursor-mcp-setup](../r18-cursor-mcp-setup/index.md) — Cursor IDE
- [r20-continue-cline](../r20-continue-cline/index.md) — Continue / Cline VSCode

## billable_units 試算
- 1 req 1 unit × ¥3 = ¥3
- 月 2,000 req (1 dev 日 100 lookup × 20 営業日) = ¥6,000 / 月、税込 ¥6,600
- チーム 5 人 = ¥30,000 / 月、税込 ¥33,000
- 初回 setup 30 秒 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- CLI 内利用 + チーム共有 OK、出力共有時は jpcite 出典明記
- `.codex/mcp.json` の repo commit は API key を環境変数展開で secret 漏洩防止
- OpenAI Codex 利用規約 (商用利用条項) も併読

## 業法 fence
- agent は補助ツール、判断は人間が責任
- 業務利用は OpenAI 利用規約 (商用利用条項 + データ取扱) と併せて確認
- 業法 fence (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1) — agent 出力は scaffold + 一次 URL まで
- 景表法 §5 — agent 出力は推定値含む可能性、最終判断は人間
