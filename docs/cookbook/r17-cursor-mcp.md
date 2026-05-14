# R17 — Cursor IDE に jpcite を組み込む

Cursor IDE の `.cursor/mcp.json` で jpcite MCP サーバーを agent tool として接続する。

- **Audience (cohort)**: All cohorts (install path)
- **Use case**: Cursor 上で「この事業計画書テキストに合う補助金を 5 件、出典 URL 付きで」と聞いて agent が自動 fetch
- **Disclaimer**: なし (install 手順)
- **Cost**: ¥0 install + ¥3/call

## TL;DR

`~/.cursor/mcp.json` (user 全体) または リポジトリ root の `.cursor/mcp.json` (project ローカル) に jpcite サーバー定義を追記し、Cursor Settings → MCP で enable する。

## Sample (bash)

```bash
# user 全体に登録 (推奨初手)
mkdir -p "$HOME/.cursor"
cat > "$HOME/.cursor/mcp.json" <<'JSON'
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
JSON

# Project ローカル (チーム共有したい場合) は repo root に同じ JSON を置く
# .cursor/ をリポジトリに含める
mkdir -p .cursor
cp "$HOME/.cursor/mcp.json" .cursor/mcp.json
```

Cursor を再起動 → Settings → MCP → "jpcite" が表示されたら enable。Cursor agent が補助金 / 法令系プロンプトで自動的に `search_programs` などを発火する。

## Expected output (Cursor 内)

```
You: この計画書 (manufacturing/設備投資/愛知県) に該当する S tier 補助金を 5 件
Cursor: [tool: jpcite.search_programs called]
1. ものづくり補助金 (一般型) — 締切 2026-06-30
   出典: https://portal.monodukuri-hojo.jp/
   tier: S
2. 愛知県 設備投資促進補助金 — 締切 2026-07-01
   出典: https://www.pref.aichi.jp/...
   tier: S
   ...
```

## 代替手段 vs jpcite cost

| 手段 | 信頼性 | コスト |
|---|---|---|
| Cursor 標準 web search | 出典 URL は出るがアグリゲータ多 (一次資料担保が弱いリスク) | LLM 料金 + 検索コスト |
| Cursor + 自前 RAG | 補助金 corpus 構築 + 維持工数 | 月数十万 |
| Cursor + jpcite MCP | 1 次資料 URL + tier 表示 + `source_fetched_at` 付き | LLM 料金 + jpcite ¥3/call |

**install ¥0、初回 3 req/day は anonymous で無料**。`.cursor/mcp.json` を repo に commit すれば チーム全員で同じ tool が即使える。

## トラブルシュート

- MCP セクションに jpcite が出ない → Cursor を完全終了 (Cmd+Q / File > Exit) して再起動。
- `uvx: command not found` → `brew install uv` または `curl -LsSf https://astral.sh/uv/install.sh | sh`。
- ツール呼び出しが失敗する → `uvx autonomath-mcp` を terminal で直接動かして stderr を確認 (起動時 health log が出る)。

## 関連

- [R16 Claude Desktop install](r16-claude-desktop-install.md)
- [R20 OpenAI Agents SDK](r20-openai-agents.md)
- [MCP tools 一覧](../mcp-tools.md)
