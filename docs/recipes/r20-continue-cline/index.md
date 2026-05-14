---
title: "Continue / Cline 設定"
slug: "r20-continue-cline"
audience: "AI agent (Continue / Cline)"
intent: "ide_extension_setup"
tools: ["search_programs", "get_corp_360", "check_invoice_status"]
artifact_type: "continue_config.json"
billable_units_per_run: 1
seo_query: "Continue Cline jpcite MCP VSCode"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Continue / Cline 設定

## 想定 user
VSCode / JetBrains で Continue 拡張または Cline (旧 Claude Dev) を使う agent dev / OSS SaaS 開発者 / 税務会計プロダクト開発者で、IDE 内で jpcite MCP server を 1 つの tool として登録し、コード review・補助金マッチング・適格事業者検証等を agent 経由で実行したい層。Continue は VSCode + JetBrains 両対応、Cline は VSCode 拡張で auto-approve mode + checkpoint 機能を持つ。両拡張とも MCP 標準準拠で `mcpServers` config を共有可能。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- Continue 0.9+ (MCP support、Settings > MCP servers パネル) または Cline 1.4+
- VSCode 1.85+ または JetBrains 2024.1+
- `uvx` (Astral uv) 事前 install: `curl -LsSf https://astral.sh/uv/install.sh | sh` 後シェル再起動
- (任意) workspace 共有時は repo 直下の `.vscode/continue.json` に commit

## 入力例
```json
{
  "models": [],
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
curl https://api.jpcite.com/healthz

which uvx
uvx --version
```
### Python
```python
import subprocess
subprocess.run(["uvx", "autonomath-mcp", "--help"], check=True)
```
### TypeScript
```ts
// Continue / Cline chat 内のサンプル prompt:
// @jpcite search_programs keyword="DX 補助金" prefecture="東京都" tier=["S","A"]
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/mcp",
  "tools_loaded": ["search_programs", "get_corp_360", "check_invoice_status",
                    "list_adoptions", "get_enforcement", "(...合計 151 tool)"],
  "extension": "Continue 0.9.x or Cline 1.4.x",
  "sample_chat": [
    {
      "user": "@jpcite search_programs keyword='IT 導入' size='sme' limit=3",
      "agent_response": "3 件 hit: IT-DOUNYU-2026 (tier=S), ..."
    }
  ],
  "known_gaps": ["旧版は MCP 未対応", "Cline は旧名 Claude Dev"]
}
```

## known gaps
- Continue v0.8 以下は MCP 不対応、`Settings > MCP servers` パネルが見えない場合は update 必須
- Cline は旧名 `Claude Dev`、VSCode marketplace で改名済、検索時は `Cline` で hit
- 緑 dot にならない時は VSCode / JetBrains を完全終了して再起動
- WSL / Remote SSH 環境では `uvx` の path が host 側との不一致あり、フルパス指定推奨
- `tools count` 0 は API key 認証失敗、`env.JPCITE_API_KEY` の jc_ プレフィクス確認
- `.vscode/continue.json` を repo commit する場合、`env` は環境変数展開 (`${JPCITE_API_KEY}`) で secret 漏洩防止

## 関連 tool
- `search_programs` (キーワード + 業種 + 地域 + tier、agent chat の主力)
- `get_corp_360` (法人 360 度ビュー、KYC コード review 時)
- `check_invoice_status` (適格事業者状況、経理ロジックのデバッグ)
- `list_adoptions` (採択履歴、補助金 SaaS 開発時の参照)
- `get_program_detail` (補助金原文、要綱本文の即時参照)

## 関連 recipe
- [r16-claude-code-30sec](../r16-claude-code-30sec/index.md) — Claude Code 30 秒接続、CLI 派エンジニア向け
- [r17-chatgpt-custom-gpt](../r17-chatgpt-custom-gpt/index.md) — ChatGPT Custom GPT、ブラウザ chatbot 化
- [r18-cursor-mcp-setup](../r18-cursor-mcp-setup/index.md) — Cursor MCP 接続、Cursor IDE 派
- [r19-codex-agents-sdk](../r19-codex-agents-sdk/index.md) — Codex Agents SDK、Codex CLI 派

## billable_units 試算
- 1 req 1 unit × ¥3 = ¥3
- 月 1,500 req (1 dev 日 75 lookup × 20 営業日) = ¥4,500 / 月、税込 ¥4,950
- チーム 5 人 = ¥22,500 / 月、税込 ¥24,750
- 初回 install は 5 分 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- IDE 内利用 + チーム共有 OK、出力共有時は jpcite 出典明記
- `.vscode/continue.json` の repo commit は環境変数展開で secret 漏洩防止
- Continue / Cline の各利用規約 (商用利用条項) も併読

## 業法 fence
- agent は補助、判断は人
- 各拡張の利用規約も併読 (Continue / Cline / Anthropic / OpenAI 等の上位モデル提供元)
- 業法 fence (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1) — agent 出力は参考、個別助言は資格者
- 景表法 §5 — agent 出力は推定値含む可能性、最終判断は人間
