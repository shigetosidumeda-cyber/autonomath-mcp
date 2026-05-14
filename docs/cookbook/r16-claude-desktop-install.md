# R16 — Claude Desktop に jpcite を 5 分で組み込む

Claude Desktop で jpcite MCP サーバーを使い始める最短手順。`uvx` 1 コマンド + JSON 1 つで完了。

- **Audience (cohort)**: All cohorts (install path)
- **Use case**: Claude Desktop で「東京都の設備投資補助金 5 件」など制度系プロンプトを安全に answering する
- **Disclaimer**: なし (install 手順)
- **Cost**: ¥0 install + ¥3/call (after first 3 anonymous req/day per IP)

## TL;DR

Claude Desktop の `claude_desktop_config.json` に jpcite サーバー定義を 1 行 加えるだけ。配布パッケージ名は互換性のため `autonomath-mcp` を維持しているが、サーバー名 (キー) は `jpcite` で登録できる。

## Sample (bash, macOS)

```bash
# 1. uv (uvx 同梱) 未インストールならインストール
brew install uv

# 2. Claude Desktop の MCP 設定に jpcite を追記
CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
[ -f "$CFG" ] || echo '{"mcpServers":{}}' > "$CFG"

# 3. 既存設定にマージ (jq があれば安全)
tmp=$(mktemp)
jq '.mcpServers.jpcite = {"command":"uvx","args":["autonomath-mcp"]}' "$CFG" > "$tmp" && mv "$tmp" "$CFG"

# 4. Claude Desktop を再起動して "MCP" アイコンに jpcite が出ることを確認
```

Windows/Linux は `~/.config/Claude/claude_desktop_config.json` (Linux) / `%APPDATA%\Claude\claude_desktop_config.json` (Windows) を同様に編集する。

## Expected output (Claude Desktop 内)

Claude のプロンプトで「東京都で募集中の設備投資補助金を 5 件、出典 URL 付きで」と聞くと、Claude が `search_programs` ツールを自動で呼び、以下のような構造化結果を生成のソースに用いる。

```
1. ものづくり補助金 (一般型) — 締切 2026-06-30
   出典: https://portal.monodukuri-hojo.jp/
2. 東京都中小企業設備投資支援補助金 — 締切 2026-07-15
   出典: https://www.tokyo-kosha.or.jp/...
   ...
```

## 代替手段 vs jpcite cost

| 手段 | 信頼性 | コスト |
|---|---|---|
| Claude 単体 (web search なし) | hallucination 60%+, 出典なし | LLM 料金のみ |
| Claude + 公式 web search | 出典は出るが補助金ポータル混在 (一次資料担保が弱いリスク) | LLM 料金 + 検索コスト |
| Claude + jpcite MCP | 1 次資料 URL + `source_fetched_at` 付き | LLM 料金 + jpcite ¥3/call |

**install ¥0、初回 3 req/day は anonymous で無料**。一次資料担保が弱いリスクのあるアグリゲータ (公開アグリゲータ ban 方針については [Honest capabilities](../honest_capabilities.md) を参照) を踏まないため、税理士業務向けには必須の組み合わせ。

## トラブルシュート

- `uvx: command not found` → `brew install uv` または公式の curl インストーラ (`curl -LsSf https://astral.sh/uv/install.sh | sh`)。
- Claude Desktop の MCP アイコンに jpcite が出ない → 設定 JSON の syntax をチェック (`jq . "$CFG"` でエラーが出ないこと)。
- 401 / 429 エラー → API key を発行 (`https://jpcite.com/pricing.html?src=cookbook_r16-claude-desktop-install`) し、`args` に `["autonomath-mcp"]` の代わりに `["autonomath-mcp", "--api-key", "jc_..."]` などキー渡し方法は今後の release で追加予定 (現状は環境変数 `JPCITE_API_KEY`)。

## 関連

- [R17 Cursor 設定](r17-cursor-mcp.md)
- [R20 OpenAI Agents SDK](r20-openai-agents.md)
- [MCP tools 一覧](../mcp-tools.md)
