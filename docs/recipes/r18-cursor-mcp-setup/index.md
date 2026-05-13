---
title: "Cursor MCP 接続"
slug: "r18-cursor-mcp-setup"
audience: "AI agent (Cursor)"
intent: "mcp_setup"
tools: ["search_programs", "get_corp_360", "list_adoptions"]
artifact_type: "cursor_mcp_config.json"
billable_units_per_run: 1
seo_query: "Cursor MCP 設定 jpcite"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Cursor MCP 接続

## 想定 user
Cursor 0.42 以降 (MCP 対応) を使う agent dev / 補助金 SaaS 開発者 / 税務会計プロダクト開発者で、コード中に出現する法人番号・補助金 ID・適格事業者番号 (T + 13 桁) をエディタ離脱なしに jpcite で即座に lookup したい層。`.cursor/mcp.json` を repo に commit して所内で同一ツール構成を共有する運用、または `~/.cursor/mcp.json` で個人 global 設定にする 2 通り。Cursor chat から `@jpcite search_programs q=...` で MCP tool 呼出を直接トリガーできる。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- Cursor 0.42+ (MCP support、Settings > MCP パネルが存在する版)
- `Settings > MCP` 編集権限
- `uvx` (Astral uv) を事前 install: `curl -LsSf https://astral.sh/uv/install.sh | sh` 後シェル再起動
- (任意) WSL 環境の場合は `~/.local/bin/uvx` のフルパス記載

## 入力例
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
# 期待: {"status":"ok","tools_default_gate":139,"corpus_snapshot_id":"2026-05-07"}

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
// Cursor chat 内のサンプル prompt:
// @jpcite search_programs q="DX 補助金" prefecture="東京都" tier=["S","A"] limit=10
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/mcp",
  "tools_loaded": ["search_programs", "get_corp_360", "list_adoptions", "check_invoice_status",
                    "get_enforcement", "(...合計 139 tool、Settings > MCP で tools count を確認)"],
  "sample_chat": [
    {
      "user": "@jpcite search_programs q='ものづくり' prefecture='東京都' tier=['S','A'] limit=5",
      "agent_response": "5 件 hit: METI-MONOZUKURI-2026 (tier=S), TOKYO-DX-2026 (tier=A), ..."
    }
  ],
  "known_gaps": ["Cursor 旧版は MCP 未対応", "WSL 環境では uvx パス調整必要"]
}
```

## known gaps
- Cursor 0.41 以下は MCP 設定パネルなし (0.42 必須)、Settings > MCP が出ない場合は Cursor を update
- WSL 環境では `uvx` の path が `/mnt/c/...` 経由になる可能性、`~/.local/bin/uvx` のフルパス指定推奨
- 緑 dot にならない時は Cursor を一度完全終了 (cmd+Q / Alt+F4) してから再起動
- `tools count` 0 は API key 認証失敗、`env.JPCITE_API_KEY` の jc_ プレフィクスを確認
- `.cursor/mcp.json` を repo commit する場合、`env.JPCITE_API_KEY` は環境変数展開 (`${JPCITE_API_KEY}`) で secret 漏洩防止

## 関連 tool
- `search_programs` (Cursor chat の主力、キーワード補助金検索)
- `get_corp_360` (法人 360 度ビュー、KYC 系コード review)
- `list_adoptions` (採択履歴、補助金 SaaS 開発時の参照)
- `check_invoice_status` (適格事業者状況、経理ロジックのデバッグ)
- `get_program_detail` (補助金原文、要綱本文の即時参照)

## 関連 recipe
- [r16-claude-code-30sec](../r16-claude-code-30sec/) — Claude Code 30 秒接続、CLI 派のエンジニア向け
- [r17-chatgpt-custom-gpt](../r17-chatgpt-custom-gpt/) — ChatGPT Custom GPT、ブラウザ chatbot 化
- [r19-codex-agents-sdk](../r19-codex-agents-sdk/) — Codex Agents SDK、Codex CLI 派
- [r20-continue-cline](../r20-continue-cline/) — Continue / Cline VSCode 拡張、VSCode 派

## billable_units 試算
- 1 req 1 unit × ¥3 = ¥3
- 月 2,000 req (1 dev 日 100 lookup × 20 営業日) = ¥6,000 / 月、税込 ¥6,600
- チーム 5 人 = ¥30,000 / 月、税込 ¥33,000
- 初回 install + 設定は 5 分 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- IDE 内利用 + チーム共有 OK、出力共有時 (Slack / GitHub PR コメント等) は jpcite 出典明記
- `.cursor/mcp.json` の repo commit は API key を環境変数展開で secret 漏洩防止
- Cursor 利用規約 (商用利用条項) と併せて確認

## 業法 fence
- agent は補助ツール、判断は人間が責任
- 業務利用は Cursor 利用規約も併読
- 業法 fence (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1) — agent 出力は参考、個別助言は資格者
- 景表法 §5 — agent 出力は推定値含む、最終判断は人間
