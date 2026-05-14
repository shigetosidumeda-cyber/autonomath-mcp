---
title: "Claude Code 30 秒接続"
slug: "r16-claude-code-30sec"
audience: "AI agent (Claude Code)"
intent: "claude_code_setup"
tools: ["search_programs", "get_corp_360", "list_adoptions"]
artifact_type: "claude_code_config.json"
billable_units_per_run: 1
seo_query: "Claude Code MCP jpcite セットアップ 30秒"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Claude Code 30 秒接続

## 想定 user
Anthropic 公式 CLI `Claude Code` を使う agent dev / 補助金 SaaS 開発者 / 税務会計プロダクト開発者で、CLI チャットから jpcite MCP server を 1 コマンドで登録し、対話 / コード review / 自動化 task で jpcite 151 tool を呼び出せる状態に持っていく。30 秒以内 (uvx install + `claude mcp add` 1 コマンド) で接続完了し、`/mcp` で接続状態 + tools count を目視確認するワークフロー。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- Claude Code CLI (Anthropic 公式、`brew install` or `npm i -g @anthropic-ai/claude-code`)
- `uvx` (Astral uv): `curl -LsSf https://astral.sh/uv/install.sh | sh` 後シェル再起動
- (任意) repo 別の global vs project 設定

## 入力例
```bash
# 1 コマンドで MCP 登録 (claude_code_config.json は CLI が管理)
claude mcp add jpcite -- uvx autonomath-mcp

# API key 設定 (paid 切替時のみ、anon mode は省略可)
claude mcp env jpcite JPCITE_API_KEY=jc_xxxxx

# prompt mode で使う場合: 長い PDF/検索を直接投げる前に jpcite の小さい packet を読む
packet="$(curl -sS -X POST "https://api.jpcite.com/v1/evidence/packets/query" \
  -H "X-API-Key: ${JPCITE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"query_text":"東京都 製造業 設備投資 補助金","limit":5,"include_compression":true,"source_tokens_basis":"pdf_pages","source_pdf_pages":30,"input_token_price_jpy_per_1m":300}')"
echo "$packet" | jq '{jpcite_cost_jpy, estimated_tokens_saved, source_count, known_gaps}'
claude -p "この jpcite Evidence Packet だけを根拠に、候補制度・確認質問・known_gaps を整理して。専門判断として断定しないこと。 $packet"
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
# 1. 接続前ヘルスチェック
curl https://api.jpcite.com/healthz
# 期待: {"status":"ok"}

# 2. uvx 確認
uvx --version
which uvx
```
### Python
```python
# Claude Code 経由で agent が呼ぶため、Python 直接呼出 不要
# テスト目的でローカル MCP server を spawn
import subprocess
subprocess.run(["uvx", "autonomath-mcp", "--help"], check=True)
```
### TypeScript
```ts
// Claude Code CLI 経由、TS から直接呼ぶ必要なし
// CLI prompt 例:
// > jpcite で「ものづくり補助金 第18次 埼玉県 製造業」を search_programs し、tier=S/A だけ source_url 付きで列挙して
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/mcp",
  "tools_loaded_count": 151,
  "tools_sample": [
    "search_programs", "get_corp_360", "check_invoice_status",
    "list_adoptions", "get_enforcement", "search_tax_incentives",
    "apply_eligibility_chain_am", "match_due_diligence_questions",
    "pack_construction", "pack_manufacturing", "pack_real_estate"
  ],
  "claude_cli_status": {"server": "jpcite", "status": "connected", "transport": "stdio"},
  "sample_chat": [
    {
      "user": "jpcite で「ものづくり補助金 18次 埼玉県 製造業」を search_programs し、tier=S/A だけ source_url 付きで列挙して",
      "agent_response": "search_programs を呼び出しました。- METI-MONOZUKURI-2026 (tier=S, 出典: ...) - SAITAMA-CHIIKI-2026 (tier=A)"
    }
  ],
  "known_gaps": ["claude mcp add は CLI v1.0+ 必須", "uvx not found は curl -LsSf https://astral.sh/uv/install.sh | sh で解消"]
}
```

## known gaps
- `claude mcp add` は Claude Code CLI v1.0 以降必須、旧版は `claude_code_config.json` 手動編集
- `uvx not found` は uv 未 install、`curl -LsSf https://astral.sh/uv/install.sh | sh` 後シェル再起動
- tools count 0 は `JPCITE_API_KEY` 未設定 + anon quota 切れ、key 設定 or 翌日 00:00 JST 待ち
- macOS Rosetta 環境では `uvx` のバイナリパス調整 (`arch -arm64 uvx`) 必要なケースあり
- 大量並列 tool call (10 並列以上) は rate-limit に当たる可能性、`X-Client-Tag` 分離 + 順次呼出推奨

## 関連 tool
- `search_programs` (Claude Code chat の主力、キーワード補助金検索)
- `get_corp_360` (法人 360 度ビュー、KYC 系コード review)
- `list_adoptions` (採択履歴)
- `check_invoice_status` (適格事業者状況)
- `get_program_detail` (補助金原文、要綱本文)

## 関連 recipe
- [r17-chatgpt-custom-gpt](../r17-chatgpt-custom-gpt/index.md) — ChatGPT Custom GPT、ブラウザ chatbot 化
- [r18-cursor-mcp-setup](../r18-cursor-mcp-setup/index.md) — Cursor MCP 接続、Cursor IDE 派
- [r19-codex-agents-sdk](../r19-codex-agents-sdk/index.md) — Codex Agents SDK、Codex CLI 派
- [r20-continue-cline](../r20-continue-cline/index.md) — Continue / Cline VSCode 拡張

## billable_units 試算
- 1 req 1 unit × ¥3 = ¥3
- 月 3,000 req (1 dev 日 150 lookup × 20 営業日) = ¥9,000 / 月、税込 ¥9,900
- チーム 5 人 = ¥45,000 / 月、税込 ¥49,500
- 初回 setup 30 秒 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- CLI 内利用 + チーム共有 OK、出力共有時 (Slack / GitHub PR コメント) は jpcite 出典明記
- repo の `.claude/mcp.json` commit は API key を環境変数展開で secret 漏洩防止
- Claude Code 利用規約 (Anthropic) も併読

## 業法 fence
- agent は補助ツール、判断は人間が責任
- 業務利用は Anthropic 利用規約 (商用利用条項 + データ取扱) と併せて確認
- 業法 fence (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1) — agent 出力は scaffold + 一次 URL まで
- 景表法 §5 — agent 出力は推定値含む可能性、最終判断は人間
