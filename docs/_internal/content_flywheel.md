# Content Flywheel — Week 5-8

**目的**: Week 5-8 (2026-05-20 〜 2026-06-16) の 4 週間で **20 本の深い長文記事** を投下し、オーガニック流入と API 試用の起点をつくる。

**絶対ルール (README 由来)**:
- 薄い programmatic SEO 頁 4,685 本を自動生成する試みは **禁止** (Google Helpful Content penalty リスク)。
- 本計画は「深い 5,000 字以上 × 20 本 / 月」で立ち上げ、記事は API docs からも引用される二重資産にする。
- 営業ゼロ原則維持。docs と記事だけが営業マン。

---

## 1. Content pillars (3 本のみ)

| Pillar | テーマ | 想定読者 | 本数 |
|--------|-------|---------|------|
| **A. 都道府県 × 業種 deep dive** | 「青森県 × スマート農業」のような地域 × ドメインの制度解体 | 事業者・AI プロダクトオーナー (非技術者含む) | 10 |
| **B. Meta: AI × 補助金** | Claude / MCP / RAG で制度データをどう扱うか | AI 開発者 (Builder 層) | 6 |
| **C. 事例 / 比較** | Jグランツや他 API との比較、併用シナリオ | Business 層 (内製 RAG 検討) | 4 |

トピック爆発を防ぐため、Pillar は 3 本で固定する。4 本目を足したくなったら、まず既存 Pillar の深化に回す。

**47 × 5 = 235 の全探索はやらない**。検索ボリューム × 制度密度 (unified_registry tier S+A の数) で上位 10 県 × 業種だけ選ぶ。

---

## 2. 20 記事 concrete list

各記事: タイトル / target KW / slug / word target / 参照 unified_id / data points 3 つ / publish week.

### Pillar A (10本) — 都道府県 × 業種 deep dive

| # | タイトル | target KW | slug | 週 |
|---|---------|-----------|------|----|
| A1 | 青森県 × スマート農業: 認定新規就農者が使える補助金 2026 完全ガイド | `青森県 認定新規就農者 補助金 2026` | `/articles/aomori-smart-agri-2026` | W5 |
| A2 | 北海道 × 酪農 DX: 環境保全型農業の交付金と併用可能な設備投資支援 | `北海道 酪農 補助金 DX 2026` | `/articles/hokkaido-dairy-dx-2026` | W5 |
| A3 | 千葉県 × 植物工場: 経営継承・発展支援 + 地域資源活用 | `千葉県 植物工場 補助金` | `/articles/chiba-plant-factory-2026` | W5 |
| A4 | 長野県 × 果樹経営: 新規就農者 + 6 次産業化で積む 3 段ロケット | `長野県 果樹 補助金 6次産業化` | `/articles/nagano-fruit-6th-2026` | W5 |
| A5 | 新潟県 × 水稲大規模: 経営所得安定対策 + 米粉製造設備補助 | `新潟県 水稲 経営所得安定対策 補助金` | `/articles/niigata-rice-scale-2026` | W6 |
| A6 | 鹿児島県 × 畜産: 畜産クラスター事業 と公庫スーパー L 資金の併用 | `鹿児島 畜産クラスター 公庫 L 資金` | `/articles/kagoshima-livestock-2026` | W6 |
| A7 | 宮崎県 × 施設園芸: A 重油高騰対策 + 環境制御導入 | `宮崎県 施設園芸 補助金 燃油` | `/articles/miyazaki-greenhouse-2026` | W6 |
| A8 | 熊本県 × 加工・業務用野菜: 産地パワーアップ事業 完全読解 | `熊本県 産地パワーアップ 補助金` | `/articles/kumamoto-veg-processing-2026` | W7 |
| A9 | 茨城県 × 有機農業: みどりの食料システム戦略 実装補助金 | `茨城 有機農業 補助金 みどり戦略` | `/articles/ibaraki-organic-2026` | W7 |
| A10 | 静岡県 × 茶業: 茶業振興 + 輸出向け GFP 認定 | `静岡 茶業 補助金 輸出` | `/articles/shizuoka-tea-2026` | W8 |

各記事共通:
- **word target**: 5,000-7,000 字 (画像・表除く)
- **data points 3 つ**: (1) tier S/A 制度 top 3 の unified_id + 金額上限, (2) 県内採択実績 (adoption DB 138K から抽出), (3) 併用可否マトリクス (exclusion_rules 参照)
- **source programs**: 最低 5 unified_id (S か A のみ)

### Pillar B (6本) — AI × 補助金 meta

| # | タイトル | target KW | slug | 週 |
|---|---------|-----------|------|----|
| B1 | Claude Desktop で補助金を正しく調べる方法 — MCP サーバー接続 10 分 | `Claude Desktop 補助金 MCP` | `/articles/claude-desktop-subsidy-mcp` | W5 |
| B2 | MCP サーバーで日本の制度検索を自動化する設計パターン | `MCP サーバー 補助金 自動化` | `/articles/mcp-subsidy-patterns` | W6 |
| B3 | RAG における日本の制度データの扱い方 — chunk 戦略と evaluation | `RAG 補助金 chunk 戦略` | `/articles/rag-subsidy-chunking` | W6 |
| B4 | 補助金 RAG の幻覚を減らす 3 つのガード — 金額・期限・事業者類型 | `補助金 RAG 幻覚 対策` | `/articles/subsidy-rag-guardrails` | W7 |
| B5 | Claude 4.7 Tool Use で制度検索エージェントを作る (AutonoMath + search) | `Claude Tool Use 補助金 エージェント` | `/articles/claude-tooluse-subsidy-agent` | W7 |
| B6 | LangChain / LlamaIndex から AutonoMath を叩く最短パス | `LangChain 補助金 API 日本` | `/articles/langchain-llamaindex-jpintel` | W8 |

各記事:
- **word target**: 5,000 字
- **data points 3 つ**: curl / Python / TypeScript の 3 言語スニペット + eval 数値 (retrieval precision / recall) + token cost 比較
- **source programs**: 代表 3 件のみ (認定新規就農者 / ものづくり補助金 / 事業再構築)

### Pillar C (4本) — 事例 / 比較

| # | タイトル | target KW | slug | 週 |
|---|---------|-----------|------|----|
| C1 | Jグランツ × AutonoMath 併用方法 — 申請導線と制度横断検索の棲み分け | `Jグランツ API 併用 補助金検索` | `/articles/jgrants-vs-jpintel` | W5 |
| C2 | 補助金 API 国産 3 種 + 海外 2 種 を叩き比べた | `補助金 API 比較 日本` | `/articles/subsidy-api-comparison-2026` | W6 |
| C3 | 内製 RAG で制度 Q&A を作った事例 — 社内ナレッジ + AutonoMath | `社内 RAG 補助金 事例` | `/articles/internal-rag-subsidy-case` | W7 |
| C4 | 農業法人 100ha クラスの資金計画を MCP で組み立てた walkthrough | `農業法人 補助金 資金計画 MCP` | `/articles/agri-corp-financial-plan-mcp` | W8 |

各記事:
- **word target**: 5,000-8,000 字 (C2/C4 は表と図が多く長め)
- **data points 3 つ**: API レスポンス JSON 抜粋 + latency 実測 + 各 API の field 網羅率表
- **source programs**: C4 のみ実名 30+ unified_id 引用、他は 5-10 件

---

## 3. Deep-dive structure template (5,000字記事の骨格)

```
H1: タイトル (target KW は自然に含める、stuffing 禁止)

Intro (200-300字)
  - 実在のユーザー状況を 2-3 文で
    例: 「青森県弘前市で 3 ha のりんご園を継いだ 32 歳。
        父の代には補助金を使わず回していたが、2026年の
        改植と省力化には 2,000 万円が足りない。」
  - 本記事で 5 本の制度を解体して併用パスを出す、と宣言

H2: 制度一覧 (800-1,200字)
  - 表形式: unified_id / 正式名称 / tier / 金額上限 / 所管 / 公式 URL
  - 各制度に 1-2 行の「要するに何」コメント

H2: 併用シナリオ (1,000-1,500字)
  - exclusion_rules を pull し、併用可/不可を明示
  - 「制度 X と Y は併用可だが、Z を足すと X の対象経費から
    Y 分を控除される」のような実務的な注意点
  - Mermaid の sequence / flowchart で視覚化

H2: 申請 timeline (600-800字)
  - Gantt 風の図 (Mermaid gantt で OK)
  - 公募開始 → 締切 → 審査 → 交付決定 → 事業実施 → 実績報告 → 精算
  - 制度間の時期依存 (先に A 採択が要件になる B など)

H2: FAQ (600-800字)
  - 実際に寄せられる質問 5-7 本 (Zenn コメント / X DM / 問合せから拾う)
  - Q&A 形式、1 問 80-150字

H2: API で引く (400-600字)
  - curl 1 発で同じ結果が出ることを示す
    curl -H "x-api-key: $KEY" \
      "https://api.jpcite.com/v1/programs/search?prefecture=青森県&funding_purpose=設備投資&tier=S&tier=A"
  - レスポンス JSON の要約
  - Python / TypeScript SDK での同等コード (1 記事につき 1 言語でよい)

H2: 公式ソース (200字 + リンク集)
  - 参照した公式 URL を全件、canonical_source_url で一覧化
  - 「最終確認日: 2026-04-23」明記
  - stale になった場合の freshness-check script 運用を 1 行で紹介
```

**必須**: 最下部に「この記事の制度データは AutonoMath API の unified_id XXX-YYY から抽出。
API docs の [programs/search](./api-reference.md) に同データが reference として埋め込まれています」の相互リンク。
→ 記事 = コンテンツ + API reference の二重資産化。

---

## 4. Production workflow (1 本 2h / 20 本 = 40h)

| 工程 | 時間 | 内容 |
|------|------|------|
| 1. Draft | 60 min | Claude で骨格生成 → AutonoMath DB から unified_id / 金額 / URL を lineage 付きで pull → 本文化 |
| 2. Fact edit | 30 min | 梅田が**事実だけ**確認 (金額・期限・URL)。文章の好みは後回し |
| 3. Polish | 30 min | AI-ism (「いかがでしたか」「まとめ」的冗長) 排除、具体例差し込み |
| 4. Publish | 10 min | Zenn 投稿 (primary) |
| 5. Cross-post | 10 min | 1 週間後に Note へリライト転載 + X thread 10 posts |

**週次リズム**: 月 5 本 × 4 週 = 20 本。
- 月曜: A 系 1 本 + B 系 1 本 draft
- 火曜: 上記 polish + publish
- 水曜: C 系 1 本 draft → publish
- 木曜: A 系 1 本 draft → publish (+ 先週記事の Note 転載)
- 金曜: B/A 1 本 draft → publish (+ X thread 再投下)

---

## 5. Anti-patterns (明示的に禁止)

| 禁止事項 | 理由 |
|---------|------|
| 「〜の補助金一覧」で分析なし | 薄いページ、Helpful penalty 直撃 |
| 記事間で 3 段落以上の boilerplate | 複製判定 |
| 金額レンジの自動生成テーブルを記事本体にする | programmatic 扱い |
| target KW を H2 に 3 回以上詰める | stuffing |
| タイトルに「2026 年最新」と入れたのに 2026 固有情報ゼロ | misleading → penalty |
| 「まとめ」「いかがでしたか」「〜ではないでしょうか」 | AI 生成臭 |
| 公式 URL なしで金額を書く | 詐欺リスク (Autonomath 系教訓) |
| 7 本以上の制度を 1 記事で同時に深掘り | 読了率死亡、分割せよ |

---

## 6. Distribution + re-use

| 媒体 | タイミング | 形式 |
|------|----------|------|
| **Zenn** (primary) | 公開日 | full 5,000字 + code block |
| **Note.com** (secondary) | +7 日 | リライト、code block 減らし narrative 強化、Business 層向け |
| **X thread** | 公開日当日 | 10 posts に chunk、最終 post で記事リンク |
| **API docs reference** | 公開日 | `docs/api-reference.md` の該当 endpoint に「関連記事」として相互リンク |
| **JSON-LD** | 各記事 launch 時 | Article schema + FAQPage schema、構造化データで検索 UX 強化 |
| **GitHub README** | Month 終了時 | 人気 top 5 を README 下部に恒久リンク |

**二重資産化の要**: 記事の unified_id 引用は API docs から逆リンクされ、
読者は記事 → docs → 試用 → API key の導線に落ちる。

---

## 7. Measurement

- **記事単体 KPI**: D+60 で 500 unique visitors / 月。
  未達なら Pillar / title / KW を逆算。
- **Conversion KPI**: 記事 → API key 発行の conversion rate 1% 以上。
- **Top 3 記事**: 月末に conversion 降順で 3 本抽出、
  「何が効いたか」を reverse engineer して次月 Pillar weight を調整。
- **測定 stack**: Plausible (軽量・JP 向け・Cookie 不要) + Stripe 側 UTM。
- **ダッシュボード**: `site/analytics/content.html` に一覧、週次更新。

---

## 8. Risk: freshness

制度の金額・公募期限・対象要件は年度更新で変わる。記事内の具体値が DB と乖離すると信頼失墜。

**Freshness check script**:

```
scripts/content_freshness_check.py
  - 全記事 markdown を parse
  - 本文中の unified_id を抽出
  - AutonoMath DB の current snapshot と照合
  - 金額 / 期限 / 所管 / URL が変わった unified_id を列挙
  - 差分レポートを /tmp/freshness_YYYYMMDD.md に出力
  - 差分ありの記事に [STALE] ラベルを frontmatter に書き込み
```

- **頻度**: 月 1 (毎月 1 日 05:00 JST cron)
- **対応**: STALE 記事は 7 日以内に手動更新、頭に「最終確認日」更新表記
- **public signal**: 各記事フッターに「最終確認日」固定表示、
  読者がいつでも鮮度判定可能

---

## Appendix: topic scoring rubric

20 本の選定基準は**等加重 5 軸の和**:
1. 検索ボリューム (Google Keyword Planner)
2. 制度密度 (unified_registry tier S+A 件数)
3. adoption 実績件数 (138K adoption DB)
4. 他メディア (Jグランツ記事 / 農水省 PDF) の薄さ
5. AI 開発者目線での「データで示せる深さ」

Pillar 内 > 上位 10/6/4 → 20 本。来月以降は直近 conversion top 3 の隣接地域 / 業種に weight を寄せる。
