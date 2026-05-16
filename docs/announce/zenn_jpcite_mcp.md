---
title: "jpcite MCP — 日本の補助金 11,601+ / 法令 9,484+ / 行政処分 1,185+ を Claude Code から横断検索する"
emoji: "🏛️"
type: "tech"
topics: ["mcp", "claudecode", "ai", "rag", "openapi", "stripe"]
published: true
---

## TL;DR (300 字)

`uvx autonomath-mcp` の 1 行で Claude Code に統合できる MCP server を公開しました。日本の公的制度 11,601+ 補助金 / 9,484+ 法令メタ / 1,185+ 行政処分 / 13,801+ 適格事業者 / 22,258+ 行政処分詳細を、法人番号 1 つで横断照会できます。155 tool、`source_url + fetched_at + content_hash` を付ける Evidence Packet 設計、業法フェンス 8 種 (税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47-2 / 行政書士法 §1の2 / 司法書士法 §3 / 社会保険労務士法 §27 / 弁理士法 §75 / 労働基準法 §36) の sensitive surface では個別税務・法律助言に踏み込みません。¥3/billable unit 完全従量、無料 3 req/IP/日 (API key 不要)。Stripe Checkout 1 分で metered billing 開始、月額固定費ゼロ、解約は dashboard 1 click。Bookyou株式会社 (T8010001213708) 提供。

## なぜ作ったか (背景)

日本の公的情報 (補助金 / 法令 / 行政処分 / 許認可 / 適格事業者) は 7+ サイト分散していて、士業や中小企業の担当者は毎回 e-Gov / 中小企業庁 / 経産省 / 国税庁 / gBizINFO / 各府省サイトを横断検索する手作業を強いられています。AI agent に「この法人に紐づく採択履歴と行政処分と適格事業者ステータスをまとめて出して」と頼んでも、AI 側は学習データのみで答える場合があり、出典 URL や最新性は別途確認が必要です。jpcite はこの「公開情報の snapshot を AI に根拠付きで渡す」一点を解決するために設計されています。

データ自体は政府が無料で出している公開情報なので、提供価値は (a) 7+ サイトの normalize、(b) `source_url + fetched_at + content_hash` の Evidence Packet 付与、(c) 法人番号での横断 join、(d) Stripe metered billing、(e) MCP / REST / GPT Actions / Codex の 4 surface 提供、の 5 つに絞っています。

## 何ができるか (5 商品)

1. **会社フォルダ Brief / Pack** — 法人番号 1 つで baseline + 採択履歴 + 行政処分 + インボイス + 関連法令を 18 req (¥59.40 税込) で 1 PDF artifact に。M&A 前 DD、新規取引前 KYC、内部監査 evidence 用途の確認材料をまとめます。
2. **顧問先月次レビュー** — 100 社 × 月次 = ¥330/月の前提例。インボイス取消 / 行政処分新着 / 採択結果 monitor を月初 1 batch で fan-out、変更があれば Slack / メールで notify。会計事務所の月次定例準備で使う確認材料をまとめます。
3. **受付前エビデンス整理パック** — 1000 案件 triage = ¥52,800/月。顧客問合せの法人名から baseline + 業種 + 規模を 3 req で fetch し、担当者振分に必要な根拠を Evidence Packet として揃えます。対応文や判断は利用者側の AI・担当者が作成します。
4. **M&A M&A DD / 取引先公開情報チェック** — 1 社 = ¥155.10 (47 req)。法人公開情報 6 源泉 + 行政処分 5 年遡及 + 適格事業者推移 + 採択補助金履歴 + 関連法令 + 役員兼任を 1 通の DD report に。FA / 監査法人の前段 screening を AI で内製化できます。
5. **相談前プレ診断** — 50 件 = ¥1,320 (400 req)。士業 (税理士 / 行政書士 / 社労士) の初回相談前に、相談者の法人状態を 8 req で先回り fetch する前提例。面談前の確認材料として使えます。

## どう使うか (5 min 接続、4 surface)

### Claude Code

```bash
curl -O https://jpcite.com/claude_desktop_config.example.json
# ~/Library/Application Support/Claude/claude_desktop_config.json に統合
# または:
claude mcp add jpcite -- uvx autonomath-mcp
```

`claude_desktop_config.json` の `mcpServers` に 1 block 追加するだけで、Claude 側の tool picker に 151 個の jpcite tool が即時 enumerate されます。`/mcp` で接続状況、`/tools` で tool 一覧、`/usage jpcite` で当月の従量見込みを確認できます。

### ChatGPT Custom GPT

Action import URL = `https://jpcite.com/openapi.agent.gpt30.json` (30 paths、GPT Actions 上限内)

ChatGPT の Custom GPT 設定で `Add actions` → `Import from URL` に上記 URL を貼るだけです。GPT Actions の 30 paths 上限に合わせて 151 → 30 tool に絞った subset を別 OpenAPI として配信しています。Authentication は `API key` 方式、header `X-API-Key` に `jc_xxx` を入れる設計です。

### Cursor

```bash
curl -O https://jpcite.com/.cursor/mcp.example.json -o .cursor/mcp.json
```

Cursor の `.cursor/mcp.json` に MCP server を 1 block 追加。Cursor IDE 内の AI chat / Cmd+K / Composer から jpcite tool を直接呼べます。プロジェクト root に置けばチーム共有、`~/.cursor/mcp.json` に置けば user 全体共有です。

### OpenAI Codex / Agents SDK

```python
from agents import Agent, hosted_mcp
mcp = hosted_mcp(server_url="https://api.jpcite.com/mcp")
agent = Agent(name="jp_subsidy", tools=mcp.list_tools())  # 155 tool 即時利用
```

OpenAI Agents SDK の `hosted_mcp` で remote MCP として叩く 1-import 構成です。tool discovery → call → response の 3 step は SDK が cover、認証は header injection で完結します。

## アーキテクチャ

- REST + MCP 2 経路 (FastAPI + FastMCP stdio)
- Backend = SQLite FTS5 (統合 corpus 9.4GB + トリグラム FTS index 352MB)
- 503,930 entities / 6.12M facts / 378,342 relations / 14,596 amendment snapshots
- Evidence Packet (`source_url + fetched_at + content_hash`) を付与
- 8 業法 fence の sensitive surface では個別税務・法律助言に踏み込まない
- Wave 21 で 5 chain tools、Wave 22 で 5 composition tools、Wave 23 で industry packs 拡張
- Fly.io 単一 region (NRT) + Cloudflare edge + Stripe metered billing
- Anon 3 req/IP/日 の AnonIpLimit gate (key 不要で playground 体験可)

Backend が SQLite なのは「データが月次 bulk 更新で write が少ない / read が圧倒的 / FTS5 で全文検索性能が出る / single-binary で migration が要らない」の 4 点を満たすからです。9.4 GB は SSD では mmap で全 page resident にできるので、コールド hit でも p50 50ms 以下を維持しています。

## ライセンスとデータ源

- 国税庁 適格事業者: **PDL v1.0** (出典明記で API 再配布可、2026-04-24 TOS 直接確認済)
- e-Gov 法令: **CC-BY-4.0** (法令全文 + 改正履歴 + 施行日)
- 中小企業庁 / 経産省 / 各府省 補助金: 政府標準利用規約 v2.0
- gBizINFO 法人活動: gBizINFO 利用規約 (経産省提供)
- 行政処分: 各府省サイトの公開情報 (出典明記必須)
- 各データに `license` field 明示、API response の `meta.license` で配信側でも自動引用可能

## 価格

- ¥3/billable unit 完全従量 (税込 ¥3.30)
- 無料 3 req/IP/日 (anon、API key 不要)
- Stripe Checkout 1 分で API key 発行
- 月額固定費なし、解約は dashboard から 1 click
- 100 req = ¥330 / 1,000 req = ¥3,300 / 10,000 req = ¥33,000 (税込)
- 法人 invoice 必要なら適格請求書 (T8010001213708) を月次自動発行

## GitHub / PyPI / Smithery

- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: `pip install autonomath-mcp==0.4.0`
- Smithery: https://smithery.ai/server/jpcite (申請中)
- awesome-mcp-servers PR: (open 予定)

## 作者

**Bookyou株式会社** (T8010001213708)、代表取締役 梅田茂利、info@bookyou.net、東京都文京区小日向 2-22-1。商号は「ブックユー」と読みます。法人 invoice / 適格請求書 / 個別契約はこのメール 1 本で 24h 以内に返信します。

## 次ステップ

https://jpcite.com/playground で 3 回試して artifact を体感してください。法人番号 (13 桁) を入れて「会社フォルダパック」を叩くと、3 商品の sample artifact が即時生成されます。API key 不要、3 req/IP/日 まで無料、Stripe 課金は 4 req 目以降のみです。
