# X (Twitter) thread (日本語) — T+0 publish draft (operator-only)

> **operator-only**: launch day publish 用 final draft (日本語 X)。mkdocs.yml `exclude_docs` で公開除外。
>
> Publish target: 2026-05-06 09:00 JST
> Account: operator personal X (日本語 audience)
> Format: 8-tweet thread, each <= 140 全角文字 (X 日本語 limit)、コピペ可
>
> 関連: `twitter_thread.md` (英語版、separate thread)
> Validate (memory `feedback_validate_before_apply`):
> - 数値 13,578 / 55 / ¥3 統一
> - INV-22: 必ず / 絶対 / 保証 / 業界初 / 最大 等の過剰強調削除済み
> - hashtag: #AutonoMath #補助金 #MCP #AI

---

## Tweet 1/8 — launch + hook (134 文字)

```
AutonoMath、本日 launch しました。

日本の公的制度データ (補助金・融資・税制・認定・法令・処分・適格事業者) を、
AI エージェントが 1 query で呼び出せる REST + MCP API です。

solo 開発、¥3/req 完全従量、匿名 50 req/月 per IP 無料。

https://jpcite.com

#AutonoMath #MCP #AI
```

---

## Tweet 2/8 — なぜ作ったか (138 文字)

```
2/ なぜ作ったか。

「うちの会社で使える補助金は?」を Claude に聞いても答えられないのは、
日本の制度データが PDF で散在し、47 都道府県 + 8 省庁を歩き、aggregator
は LLM 投入が grayエリアだから。

AI が即答できる API が欲しかった、というだけです。

#補助金 #AI
```

---

## Tweet 3/8 — 数値 (138 文字)

```
3/ 何が入ってるか (2026-05-06 時点)

- 制度 13,578 件 (経産省/農水省/中小企業庁/公庫/都道府県)
- 採択事例 2,286 / 融資 108 / 行政処分 1,185
- 法令 9,484 (e-Gov CC-BY)
- 適格事業者 13,801 (NTA PDL v1.0)
- 出典 URL 99%+ 付与

#AutonoMath
```

---

## Tweet 4/8 — 5 audience (139 文字)

```
4/ 想定 audience は 5 つ。

- AI agent 開発者: 72 MCP ツール at default gates、Manifest 1 行
- 税理士: 措置法を Claude で walkthrough
- 行政書士: 補助金+融資+許認可を 1 call
- SMB 経営者: ChatGPT で「うちの業種は?」
- VC/DD: 法人番号で処分歴+適格事業者横断

#AI #補助金
```

---

## Tweet 5/8 — 技術 stack (130 文字)

```
5/ 技術 stack

- SQLite + 全文検索インデックス (3-gram, 日本語複合語検索)
- ベクトル検索 (entity-fact vec、503k entities・段階的有効化中)
- FastAPI + FastMCP (protocol 2025-06-18 stdio)
- Fly.io 東京 + Cloudflare Pages + Stripe metered

#MCP #SQLite
```

---

## Tweet 6/8 — データ hygiene (139 文字)

```
6/ データの肝。

全 programs 行に一次情報源 (省庁/都道府県/公庫等) を引用。
aggregator (noukaweb / hojyokin-portal 等) は source_url から完全 ban。
過去の業界事例が 詐欺 risk を生んだ反省です。

99%+ 行に source_url + fetched_at lineage を付与。

#補助金 #データ
```

---

## Tweet 7/8 — 使い方 (138 文字)

```
7/ 使い始めは 3 通り。

1. curl https://api.jpcite.com/v1/programs/search?q=...
2. Claude Desktop: claude_desktop_config.json に
   { "command":"uvx", "args":["autonomath-mcp"] }
3. pip install autonomath-mcp

匿名 50 req/月 per IP 無料 (JST 月初リセット)。

#MCP #AI
```

---

## Tweet 8/8 — AMA + GitHub (138 文字)

```
8/ 質問・Issue 歓迎します。

- 全文検索インデックス (3-gram) の日本語落とし穴
- MCP ツール設計 tradeoff
- なぜ tier 廃止 / 完全従量にしたか
- solo + zero-touch 運営の現実

GitHub: github.com/[USERNAME]/[REPO]
PyPI: pypi.org/project/autonomath-mcp/

reply / DM open。

#AutonoMath
```

---

## Pre-publish checklist (operator)

- [ ] 8 tweet 全て 140 全角文字以下を X UI で再確認 (URL は短縮分込み)
- [ ] GitHub URL placeholder `[USERNAME]/[REPO]` を実 URL に置換
- [ ] thread の reply 連結を順序通りに
- [ ] 英語 thread (`twitter_thread.md`) と同時 publish 推奨だが、別 thread として独立
- [ ] hashtag (#AutonoMath #補助金 #MCP #AI) 4 種を散らす

---

## Post-publish

- 1/8 を pin
- HN URL は T+0 **22:30 JST** 投稿後 reply で追加。canonical: `docs/_internal/launch_dday_matrix.md` §0 (09:30 ET = HN morning peak window)
- quote tweet / RT 連投での過剰宣伝禁止 (memory `feedback_organic_only_no_ads`)
