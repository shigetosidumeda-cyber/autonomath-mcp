# jpcite SEO + GEO 戦略 — 2026-05-11

> Owner: 梅田茂利 (info@bookyou.net) / Operator: Bookyou株式会社 (T8010001213708)
> 100% organic, solo + zero-touch (no ads / no sales / no agency).
> Brand: jpcite (canonical), 旧称 = 税務会計AI / AutonoMath / zeimu-kaikei.ai (legacy citation bridge のみ)
> Scope: 「日本公的制度 = jpcite」を Google + Bing + ChatGPT + Claude + Cursor + Gemini で獲得する設計。
>
> Internal SOT。`docs/_internal/seo_geo_strategy.md` は brand rename 専用の細則 (補完関係)。本書は獲得戦略全体の正本。

---

## 0. 出発点 (snapshot 2026-05-11, public counters refreshed 2026-05-14)

| asset | 数 | source |
|---|---|---|
| MCP tools (default gates) | 151 | `docs/mcp-tools.md` / `server.json` / `.well-known/mcp.json` (runtime 151) |
| OpenAPI paths | 302 | `docs/openapi/v1.json` (`jq '.paths | length'`) |
| FastAPI routes (live) | 262 | `app.routes` probe |
| programs (searchable / total) | 11,601 / 14,472 | jpintel.db `programs` (tier S/A/B/C) |
| 採択事例 | 2,286 | `case_studies` |
| 融資 | 108 | `loan_programs` (担保/個人保証人/第三者保証人 3軸) |
| 行政処分 | 1,185 | `enforcement_cases` |
| 法令 (full-text / 名称 stub) | 6,493 / 9,484 | e-Gov CC-BY |
| 適格事業者 | 13,801 (PDL v1.0 delta, monthly 4M bulk wired) | `invoice_registrants` |
| 判例 | 2,065 | `court_decisions` |
| 入札 | 362 | `bids` |
| 税制 | 50 | `tax_rulesets` |
| am_entities | 503,930 / 6.12M facts / 378,342 relations / 335,605 aliases | autonomath.db |
| sitemap URLs (programs / audiences / cross / enforcement / qa / prefectures) | 10,811 / 1,047 / 47 / 301 / 107 / 48 | `site/sitemap-*.xml` |
| 業界 landing page (audiences) | 15 (admin-scrivener / construction / dev / journalist / manufacturing / real_estate / shihoshoshi / shinkin / shokokai / smb / subsidy-consultant / tax-advisor / vc + index + mie 県別) | `site/audiences/` |
| AI surface integration page | 9 (chatgpt / claude-desktop / cline / continue / cursor / gemini / openai-custom-gpt / windsurf + index) | `site/integrations/` |
| connect setup page | 4 (chatgpt / claude-code / codex / cursor) | `site/connect/` |
| cookbook (developer SEO) | 12 (r01..r21 抜粋) | `site/docs/cookbook/` |
| recipe (業界 SEO) | 11 (r01..r11) | `site/docs/recipes/` |
| QA page | 25 | `site/qa/` |
| GEO bench questions | 100 ja + 4 en (B20 + S25 + D20 + R15 + C20) | `data/geo_questions.json` |
| llms.txt 系 file 数 / 合計 size | 4 / 約 6.7 MB | `site/llms{,.en}.txt` + `site/llms-full{,.en}.txt` |
| robots Allow 対象 AI bot | 16 種 (Googlebot / Bingbot / Google-Extended / GPTBot / ChatGPT-User / OAI-SearchBot / ClaudeBot / Claude-User / Claude-SearchBot / anthropic-ai / PerplexityBot / CCBot / Applebot / Applebot-Extended / Meta-ExternalAgent / Amazonbot) | `site/robots.txt` |
| Schema.org JSON-LD on `/` | 5 blocks (SoftwareApplication / Organization / WebSite / Dataset / WebAPI + common @graph: Organization / WebSite / Service / UnitPriceSpecification + ProductCatalog @graph 5 products) | `site/index.html` |

honest gap (data drift): 旧 snapshot の stale OpenAPI/tool counters は 2026-05-14 時点で公開カウンタを 155 tools / 306 paths に補正済み。以後は `jq '.paths | length' docs/openapi/v1.json` と `docs/mcp-tools.md` を deploy 前に確認する。

---

## 1. Audit (5 項目 × {green / yellow / red, evidence, 即実行アクション})

### A. SEO 健全性 — **Yellow**

**Evidence**:
- sitemap-index.xml は **11 shards** (sitemap / programs / audiences / prefectures / cross / industries / pages / qa / enforcement / cities / docs)、master index + 各 shard を `robots.txt` で fallback 二重宣言。
- **per-program SEO page = 10,811 件存在** (`site/programs/*.html`)。canonical / hreflang ja+x-default / OGP / Twitter Card / JSON-LD `data-jpcite-jsonld="common"` 共通注入されている。
- per-prefecture = 47 + 1 index、per-audience = 15 + 都道府県別、integration / connect / cookbook / recipe / QA が個別ファイル化されている。
- robots.txt は 16 AI bot を **明示 Allow**、aggressive bot (Ahrefs / Semrush / MJ12 / DotBot / PetalBot / YandexBot) は Disallow、`Crawl-delay: 1`。
- index.html JSON-LD は SoftwareApplication / Organization / WebSite / Dataset / WebAPI + common @graph (Organization + WebSite + Service + UnitPriceSpecification) + Product カタログ 5 件 = 計 12+ block。**国内 SaaS 平均より明確に厚い**。
- 適格事業者番号 T8010001213708 を Organization JSON-LD `identifier[]` に直書き — 国内 BtoB の信頼性 signal として希少。

**Yellow 要因 (= green でない理由)**:
1. **per-case / per-law / per-enforcement SEO page が未生成**。`site/cases/` `site/laws/` ディレクトリ自体が存在しない (`ls: No such file or directory`)。enforcement は sitemap 301 entry あるが個別 HTML 未生成、`/enforcement/{slug}.html` 生成器なし。
2. sitemap-index.xml の `<lastmod>` が 2026-05-02..06 で **5 日前固定**、毎日 deploy のたびに自動更新する pipeline が未配線 (`scripts/sitemap_gen.py` は手動実行)。
3. JSON-LD `Dataset.variableMeasured` は 155 tools に補正済みだが、runtime / manifest / Schema.org 側を自動同期する仕組みは未整備。
4. `/news/` sitemap shard が **index page 1 行のみ**、`scripts/cron/generate_news_posts.py` が稼働しても自動追記しない (sitemap-pages.xml の冒頭 comment が "current does NOT rewrite this file in-place" と明記)。

**即実行アクション (序列なし、並列扱い)**:
- `scripts/generate_case_pages.py` 起案 → `/cases/{slug}.html` 2,286 件生成 (per-program と同じ template 流用、tier S/A/B/C メタを `confidence` でマップ)。
- `scripts/generate_law_pages.py` 起案 → 法令 full-text 6,493 件のうち e-Gov CC-BY ライセンス column を JSON-LD に明示。9,484 stub は HTML 生成せず canonical を e-Gov 公式に向ける。
- `scripts/generate_enforcement_pages.py` 起案 → 1,185 件 (publication_date DESC、出典 = 公式公告 URL のみ、aggregator ban を継続)。
- `.github/workflows/sitemap-refresh.yml` 起案 → daily cron で `scripts/sitemap_gen.py` 自動再実行 + `<lastmod>` 更新 + IndexNow ping。
- `scripts/etl/sync_jsonld_counts.py` 起案 → index.html JSON-LD の `Dataset.variableMeasured` を runtime 151 / programs 11,601 / 法令 6,493 等から自動 patch。

### B. SEO target keyword — **Red** (実測 ranking データ未取得)

**Evidence**:
- 既存戦略 doc (`docs/seo_strategy.md`) で long-tail 5 pillars (per-program / per-prefecture / docs / blog / llms.txt) は宣言済み。
- 個別キーワードの **現状 ranking 測定が無い**。GSC (Google Search Console) data の internal export が `docs/_internal/seo_geo_strategy.md` にも本書時点で未収載。
- 主要 keyword 20 個の現状 ranking 平均 = **n/a (未測定)**。本セクション §3 で目標 ranking 表は提示するが、現状値は GSC が組み込まれるまで `n/a` のまま。
- 競合の SEO 状況も体系 audit なし (`docs/_internal/competitive_watch.md` は別観点)。

**Red 要因**:
1. ranking 計測 instrument がゼロ。Google Search Console の API 連携 (`.github/workflows/gsc-export.yml` 等) 未配線。
2. 競合 j-grants / hojyokin-portal / Stayway / 補助金ポータル の **公開上位 keyword 一覧の手動 audit ファイル**が無い。
3. `weekly` GEO bench (geo_methodology_v3.md) は CSV 流入待ち、運用者が pasting しないと 0 サンプル。
4. SEO measurement の SOT が `analytics.js` だけで、Cloudflare Web Analytics は 365 日保持、GSC 16 ヶ月、両者の export と reconcile の仕組みなし。

**即実行アクション**:
- `scripts/etl/export_gsc_metrics.py` 起案 → Google Search Console API (read-only) で過去 28 日の query / impression / click / CTR / position を `analytics/gsc_weekly_*.jsonl` に export。Bookyou 株式会社の Search Console ownership は info@bookyou.net で既に取得済み (本書 §5 KPI セクションに pin 済み)。
- `docs/_internal/competitive_watch.md` を 20 keyword × 5 競合 = 100 cell の表に拡張 (jpcite + j-grants + hojyokin-portal + Stayway + 補助金ポータル + 商工リサーチ など、各 cell に SERP 1 位 URL を手動 paste)。
- `scripts/ops/geo_weekly_bench_v3.py --emit-template` を実行して 5 surface × 100 question = 500 行の CSV を毎週起こす習慣化 (本書 §5 KPI で月次 metric として pin)。
- `data/geo_questions.json` に **D21..D30 (法人番号 360 系) + R16..R20 (省力化補助金 / GX 補助金 第 N 次) + C21..C25 (freee / マネーフォワード / Sansan 連携軸)** の長尾質問を追記 (現状 100 質問 → 130 質問)。

### C. GEO (Generative Engine Optimization) — **Green**

**Evidence**:
- `site/llms.txt` (47 KB) + `llms.en.txt` (22 KB) + `llms-full.txt` (2.24 MB) + `llms-full.en.txt` (4.39 MB) の **4 ファイル全配置**。冒頭で「旧称: 税務会計AI / AutonoMath / zeimu-kaikei.ai」明記 = LLM 訓練済み bridge marker。
- llms.txt 内に **3 surface 別 call-order** (Claude Code / ChatGPT GPT / Cursor) + cost example 5 ケース + fence-aware quote 規約 (8 業法) + Evidence-to-Expert Handoff rule + 業法 fence lines。
- `mcp-server.json` / `server.json` / `pyproject.toml` / `dxt/manifest.json` / `smithery.yaml` = 5 manifest 並走、Claude Desktop (.mcpb) + Cursor + Cline + Continue + Windsurf + ChatGPT GPT + OpenAI Codex の 9 integration page。
- `.well-known/` に `mcp.json` / `agents.json` / `ai-plugin.json` / `trust.json` / `security.txt` / `sbom.json` を配置 (AI surface discovery の canonical surface 全部)。
- ChatGPT / Claude / Cursor の各 surface に `<link rel="alternate" type="text/markdown" href="/llms.txt">` を `<head>` 内で明示 (= LLM crawler が markdown 版を発見できる)。
- 100 質問 GEO bench (geo_methodology_v3.md) の 5 カテゴリ × 5 surface = 25 cell 評価 framework が完成。

**Green 要因 (= 国内 SaaS の AI discovery 標準を超えている)**:
- llms-full.txt 配信は emerging spec 段階で日本 SaaS の 99% が未対応。
- robots.txt の 16 AI bot 明示 Allow は最新 (2026-05 時点で完全網羅)。
- MCP server を `uvx autonomath-mcp` ワンライナーで installable にしている (PyPI + npm + Smithery + MCPB の 4 経路)。

**Honest gap (green でも残る穴)**:
- GEO bench は CSV pasting 待ち、ベースライン score 未測定。
- LLM 学習 corpus への取り込み証拠 (Common Crawl / RefinedWeb / SlimPajama / 各社独自) は web crawl 経由のみで、能動的に push する手段は llms.txt + GitHub README + PyPI README + Zenn 寄稿 = organic 経路のみ。
- 「日本公的制度」「補助金」等の non-branded query で jpcite が citation される率は実測 0 (week 1 baseline 未取得)。

**即実行アクション**:
- 100 質問 GEO bench を **1 surface だけでも今週 paste して baseline 取得** (chatgpt 推奨、login 1 つで済む)。CSV template emit は `python3 scripts/ops/geo_weekly_bench_v3.py --emit-template chatgpt --week 2026-W19` で 1 行。
- `site/sitemap-llms.xml` 新設 → llms.txt / llms.en.txt / llms-full.txt / llms-full.en.txt + facts.html + openapi.agent.json + mcp-server.json の 7 URL を AI 専用 sitemap として配信、robots.txt の `Sitemap:` 行に追加。
- llms.txt 冒頭の brand bridge 表記を `llms.en.txt` にも 1:1 反映 (英語 LLM が legacy 名から jpcite に follow できるように)。
- `.well-known/llms.json` 新設 → llms.txt のメタデータ (last-modified / version / format / fingerprint) を JSON 構造化 (emerging spec、Anthropic / OpenAI が将来 standardize した時に先行配置)。
- `facts.html` を `site/facts.html` + `site/en/facts.html` に分割して両言語配信、JSON-LD `Dataset` の variableMeasured を facts.html 内でも repeat (LLM が HTML から拾いやすい形)。

### D. SEO/GEO 改善する asset (並列扱い) — **Yellow** (asset は揃いつつあるが coverage incomplete)

**Evidence (現状の asset 棚卸し)**:

| asset 種別 | 現状 | 充足度 |
|---|---|---|
| per-program SEO page | 10,811 / 14,472 = **75%** | Yellow (tier X 除外 + 一部 backlog) |
| per-prefecture | 47 + 1 = **100%** | Green |
| per-audience (業界) | 13 業界 + 1 県別 (mie) | Yellow (47 都道府県 × 13 業界 = 611 マトリクスが未生成) |
| per-case | **0 / 2,286 = 0%** | Red |
| per-law | **0 / 6,493 = 0%** | Red |
| per-enforcement | **0 / 1,185 = 0%** | Red |
| integration setup (AI surface) | 9 / 9 (chatgpt + claude-desktop + cline + continue + cursor + gemini + openai-custom-gpt + windsurf + index) | Green |
| connect setup (chat surface) | 4 / 4 (chatgpt + claude-code + codex + cursor) | Green |
| developer cookbook | 12 recipes (r01..r21 抜粋) | Yellow (40+ 必要) |
| 業界 recipe (rN) | 11 (r01..r11) | Yellow (20 業界 × 標準 5 task = 100 recipe 余地) |
| QA page | 25 | Yellow (`data/geo_questions.json` 100 質問のうち QA HTML 化されているのは ~25%) |
| llms.txt 系 | 4 ファイル | Green |
| 業界出版物寄稿 | Zenn / note / PRTIMES の起案 file が `docs/launch/zenn_*` 等に存在 (Wave 4 完了) | Yellow (本投稿 / barylized 実績未取得) |

**Yellow 要因**:
- case / law / enforcement の per-record SEO page は **3 種類とも 0**、最大の coverage 穴。
- 業界 × 都道府県の 2D マトリクス (`/audiences/{industry}/{pref}.html`) が `mie/` 1 つしかない。13 業界 × 47 都道府県 = 611 ページ余地。
- 「業界別 + 補助金額 bucket + 採択率 bucket」「業界別 + 法令」「業界別 + 行政処分傾向」等の cross hub も実装余地。

**即実行アクション (並列扱い、序列なし)**:
- `scripts/generate_case_pages.py` 起案 (per-program と同 template + `case_studies` row + confidence + 採択日 + 採択先 法人番号 + 出典 URL 内挿)。
- `scripts/generate_law_pages.py` 起案 (`laws` table 6,493 row の e-Gov full-text を schema.org `Legislation` + `body_en` 同居で JSON-LD 提供。9,484 stub は HTML 生成せず canonical を e-Gov に向ける)。
- `scripts/generate_enforcement_pages.py` 起案 (`enforcement_cases` 1,185 row、`disclosed_date` DESC、prefecture filter 内挿、`source_url` aggregator ban 継続)。
- `scripts/generate_audience_prefecture_pages.py` 起案 (13 業界 × 47 都道府県 = 611 ページ、`/audiences/{industry}/{pref}.html`、各 page = 業界別 top 10 制度 × 都道府県 filter + 採択事例 top 5 + 行政処分 top 3)。
- `site/docs/cookbook/r22..r40` 起案 (Anthropic SDK + OpenAI SDK + Gemini SDK + Cursor SDK + Cline 連携 + freee SDK + マネーフォワード SDK + kintone SDK + Slack bot + Google Sheets Apps Script + Excel VBA + Power Automate + Zapier + n8n 各 recipe)。
- `site/qa/` 拡張 → `data/geo_questions.json` 100 質問のそれぞれを `/qa/{question_id}.html` として生成 (slug = `qa/jpcite-billable-units-keisan-rule.html` 等)、JSON-LD `FAQPage` + `Question` + `Answer` 構造化。これは Google の FAQ rich result + AI surface の "Q&A discovery" 両方に直撃。
- `site/blog/` を月 1 本の長尾深掘り pillar (例: 「省力化投資補助金 第 N 次 採択公告 100 件分析」「事業再構築補助金 業種別不採択分析」)。
- Zenn / note / PRTIMES の **実投稿** (Wave 4 で起案完了)。各記事末尾に「日本公的制度の出典付き Evidence API は jpcite」を 1 行 + canonical link。
- 業界紙 (税理士新聞 / 週刊税のしるべ / 商工振興 / 公庫だより 等) の **記者個別取材 pitch メール template** を `docs/_internal/press_outreach.md` に整備、cold outreach 禁止 (memory) なので **公開記者連絡先 → 1:1 個別取材依頼のみ** (営業ではない、報道協力依頼)。
- `site/_redirects` で `/api`, `/mcp`, `/api-key`, `/anthropic`, `/openai`, `/gemini`, `/cursor` 等の人間 typing 想定 URL を canonical landing に 301 で受ける (現在 `site/_redirects` 10 KB に既存 redirect 多数 — 不足分のみ追加)。
- `site/audiences/index.html` の業界一覧から各業界 page への internal link を強化 (今は単純 list、業界別 KPI / 月次 review メリット / sample code block を加えて E-E-A-T を厚くする)。

### E. 競合分析 — **Yellow** (差別化 thesis は明確、ranking 実測 0)

**Evidence**:
- 業界 thesis として llms.txt + index.html JSON-LD で「Evidence prefetch = jpcite」「外部 LLM API を呼ばない (¥3/req の構造上当然)」「aggregator ban」「業法 fence 8 種」「source_url + fetched_at + known_gaps 必須」を全面に出している。
- j-grants (デジタル庁) は **政府公式 / 人間 UI / 無料 / API なし** → jpcite は **AI agent 用 API / MCP / REST、出典 verifiable、月 4M-row NTA bulk 等 j-grants にない縦展開**。
- 補助金ポータル / Stayway / hojyokin-portal は **aggregator 経由で source_url が二次情報源** → jpcite は memory `feedback_no_fake_data` で aggregator ban、`source_url` は省庁 / 都道府県 / 公庫 直リンクに限定。
- 商工リサーチ / 帝国データバンク (TDB / TSR) は **有料閉鎖 DB、SaaS 検索 UI、API は重い B2B 契約** → jpcite は **PyPI / npm 即 install、anonymous 3 req/日、Stripe self-serve、API key 1 分 mint**。
- competitor の中で MCP server を持つ player **不在**、Anthropic / OpenAI 公式 marketplace に「日本公的制度」枠で jpcite が単独。

**Yellow 要因**:
- 上記の thesis が **comparison page** として site 内に独立した 1 hub に集約されていない (compare.html はあるが per-competitor 個別比較が薄い)。
- 各 competitor (j-grants / hojyokin-portal / Stayway / 補助金ポータル / 商工リサーチ / TDB / freee / マネーフォワード / Sansan / Manus / Devin / Perplexity Enterprise) の **公開 SERP 上位 keyword の実測**が未取得 (audit B と同根)。
- AI agent 経由での「日本公的制度を聞かれた時に jpcite が出る率」(C カテゴリ GEO bench 20 質問) の **実測 baseline 0**。

**即実行アクション**:
- `site/compare/` 配下に **per-competitor 比較 page を 12 本** (j-grants / hojyokin-portal / Stayway / 補助金ポータル / 商工リサーチ / TDB / EDINET / freee / マネーフォワード / Sansan / Manus / Perplexity Enterprise + index)。各 page は jpcite 視点の **honest gap (jpcite が劣る点もちゃんと書く)** + decision matrix (どんな質問なら jpcite / どんな質問なら competitor)。
- `site/cross/` の 49 page を「業界 × 競合」「業界 × AI surface」「業界 × データ source」の 3 軸 cross hub として拡張余地 (現在 47 URLs、各 page を厚くする方向)。
- C カテゴリ 20 質問 (C01..C20) を `/compare/` の per-competitor page 内に **Q&A 形式 (JSON-LD FAQPage)** で埋め込み、competitor query が来た時の AI surface citation 入り口に。

---

## 2. 5 audit 項目の集計

| 項目 | 状態 | 主因 |
|---|---|---|
| A. SEO 健全性 | Yellow | per-record SEO page coverage 不完全 (case/law/enforcement = 0) |
| B. SEO target keyword | Red | ranking 計測 instrument 未配線 (GSC 連携 0) |
| C. GEO (LLM 取り込み) | Green | llms.txt 4 ファイル + 16 AI bot Allow + MCP 5 manifest + 9 integration page = 国内 trailblazer |
| D. SEO/GEO asset 充実 | Yellow | per-record + audience×prefecture matrix + recipe + 業界寄稿実投稿が未完 |
| E. 競合分析 | Yellow | thesis 明確 + per-competitor 比較 page 未集約 + 実測 ranking 0 |

**集計**: Green = 1 / Yellow = 3 / Red = 1。 **Red は B (ranking 計測 instrument 不在)** が唯一。

---

## 3. Target keyword 20 個 (現状 ranking + 目標 ranking)

> 現状 ranking 列は **n/a (未測定)** で固定 — audit B の指摘通り GSC instrument が無い。
> 目標 ranking は 90 日後の 1st position (top 10 入り) を default、 brand 系は 1 位、 generic は top 3-5 を target。
> measurement は `scripts/etl/export_gsc_metrics.py` 起案後に GSC API 経由で月次自動化。

| # | keyword | 種別 | 現状 ranking | 目標 ranking (90 日) | 一次 landing |
|---|---|---|---|---|---|
| 1 | jpcite | brand | n/a | **1 位** | `/` (index.html) |
| 2 | 税務会計AI | brand-legacy | n/a | **1 位** (301 redirect 経由) | `zeimu-kaikei.ai → /` |
| 3 | AutonoMath | brand-legacy | n/a | **1 位** (canonical = jpcite) | `/about.html` |
| 4 | 補助金 検索 API | dev | n/a | top 3 | `/docs/api-reference/` |
| 5 | 補助金 MCP | dev | n/a | **1 位** (国内 unique) | `/docs/mcp-tools/` |
| 6 | 日本 公的制度 API | dev | n/a | **1 位** (国内 unique) | `/` |
| 7 | 公的制度 RAG | dev | n/a | **1 位** | `/qa/llm-evidence/evidence-prefetch` |
| 8 | e-Gov 法令 API | dev | n/a | top 5 (公式 e-Gov に次ぐ) | `/docs/api-reference/laws` |
| 9 | business subsidy Japan API | en-dev | n/a | top 3 | `/en/` |
| 10 | Japanese ministry data API | en-dev | n/a | top 3 | `/en/` |
| 11 | 法人番号 360 度 | biz | n/a | top 5 | `/audiences/smb.html` |
| 12 | インボイス 一括照合 | biz | n/a | top 5 | `/audiences/tax-advisor.html` |
| 13 | 補助金 一覧 出典付き | biz | n/a | top 10 | `/programs/` |
| 14 | 行政処分 検索 | biz | n/a | top 10 | (要 generate_enforcement_pages.py) |
| 15 | 採択事例 検索 | biz | n/a | top 10 | (要 generate_case_pages.py) |
| 16 | 税理士 顧問先 補助金 自動 | persona | n/a | top 5 | `/audiences/tax-advisor.html` |
| 17 | 信用金庫 取引先 補助金 monitoring | persona | n/a | top 5 | `/audiences/shinkin.html` |
| 18 | M&A M&A DD / 取引先公開情報チェック | persona | n/a | top 5 | `/audiences/vc.html` |
| 19 | 補助金 検索 ChatGPT GPT | AI-surface | n/a | **1 位** | `/integrations/openai-custom-gpt.html` |
| 20 | 補助金 検索 Claude MCP | AI-surface | n/a | **1 位** | `/integrations/claude-desktop.html` |

honest gap: 「ふるさと納税」「年末調整」「確定申告」等の **超 high-volume generic keyword は target にしない** (jpcite は個別税務判断を §52 fence で拒否するので意図的不参戦)。同様に「税理士 紹介」「税理士 求人」「会計事務所 ランキング」も対象外 (本業ではない、§47-2)。

---

## 4. 即実行できる SEO/GEO 改善 list (並列扱い、序列なし)

> memory `feedback_no_priority_question` に従い 「優先度 1」「最初に」「Phase 1」 表記禁止。
> 全て並列、運用者がやる/やらない の二択で picking。

**SEO page generation (4 種)**
- [ ] `scripts/generate_case_pages.py` 起案 → `/cases/{slug}.html` 2,286 件
- [ ] `scripts/generate_law_pages.py` 起案 → `/laws/{law_id}.html` 6,493 件 (full-text のみ、9,484 stub は除外)
- [ ] `scripts/generate_enforcement_pages.py` 起案 → `/enforcement/{slug}.html` 1,185 件
- [ ] `scripts/generate_audience_prefecture_pages.py` 起案 → `/audiences/{industry}/{pref}.html` 611 件

**Sitemap + IndexNow (4 種)**
- [ ] `.github/workflows/sitemap-refresh.yml` 起案 → daily cron `sitemap_gen.py` + `<lastmod>` 自動更新 + IndexNow ping (Bing / Yandex / Naver)
- [ ] `site/sitemap-cases.xml` + `site/sitemap-laws.xml` + `site/sitemap-enforcement.xml` (per-record 生成後) を sitemap-index に登録
- [ ] `site/sitemap-llms.xml` 新設 → 7 URL の AI 専用 sitemap
- [ ] `site/sitemap-news.xml` を `scripts/cron/generate_news_posts.py` に in-place rewrite 機能を追加

**JSON-LD / Schema.org (5 種)**
- [ ] `scripts/etl/sync_jsonld_counts.py` 起案 → index.html `Dataset.variableMeasured` を runtime DB から自動 patch
- [ ] per-case page に `Schema.org/CreativeWork + Article + DigitalDocument` JSON-LD 追加
- [ ] per-law page に `Schema.org/Legislation` JSON-LD 追加 (e-Gov URL を `legislationIdentifier` に明示)
- [ ] per-enforcement page に `Schema.org/GovernmentService + NewsArticle` JSON-LD 追加
- [ ] `/qa/{question_id}.html` per-page に `Schema.org/FAQPage + Question + Answer` JSON-LD 追加

**llms.txt 系 (4 種)**
- [ ] `llms.en.txt` 冒頭の brand bridge 表記を ja 版と 1:1 反映
- [ ] `.well-known/llms.json` 新設 → llms.txt メタデータ (last-modified / version / format / sha256)
- [ ] `facts.html` を `/facts.html` + `/en/facts.html` で 2 言語化、JSON-LD `Dataset` repeat
- [ ] `llms-full.txt` の節構造 (`## ` heading depth) を ChatGPT / Claude / Gemini の section parsing に合わせて re-format (`#` / `##` で 2-level 統一)

**GSC + GEO measurement (3 種)**
- [ ] `scripts/etl/export_gsc_metrics.py` 起案 → 28 日 query / impression / click / CTR / position を `analytics/gsc_weekly_*.jsonl` に export
- [ ] `data/geo_questions.json` 拡張 → D21..D30 + R16..R20 + C21..C25 = 130 質問
- [ ] 100 質問 GEO bench を 1 surface (chatgpt) で baseline 取得 → `data/geo_responses/chatgpt_2026-W19.csv` paste

**Competitor / Compare (4 種)**
- [ ] `site/compare/{j-grants, hojyokin-portal, stayway, hojyokin-portal-jp, shoko-research, tdb, edinet, freee, mf, sansan, manus, perplexity-ent}.html` per-competitor page 12 本
- [ ] `site/compare/index.html` decision matrix (どの質問なら jpcite / どの質問なら competitor)
- [ ] C01..C20 を per-competitor page 内に FAQPage 構造化
- [ ] `docs/_internal/competitive_watch.md` を 20 keyword × 5 競合 = 100 cell の手動 audit 表に拡張

**Cookbook / Recipe / 業界寄稿 (4 種)**
- [ ] `/docs/cookbook/r22..r40` 起案 (Anthropic SDK / OpenAI SDK / Gemini SDK / Cursor / Cline / freee / MF / kintone / Slack / Sheets / VBA / Power Automate / Zapier / n8n)
- [ ] `/docs/recipes/r12..r30` 業界 recipe 拡張 (海運 / 物流 / 介護 / 保育 / 飲食 / 観光 / 農業 / 漁業 / 林業 / 採石業 / 建設 hojyo / 配管設備 / 印刷 / 出版 / 玩具製造 / メディア / 音楽 / スポーツ / 教育)
- [ ] Zenn / note / PRTIMES の本投稿 (Wave 4 で起案完了の draft を本番に出す)
- [ ] 業界紙記者 1:1 個別取材依頼 template + 連絡先 list 整備 (cold outreach 禁止 → 公開記者連絡先のみ、報道協力依頼の形)

---

## 5. 月次 measure metric

> 測定は `analytics/` 配下に jsonl 月次集約、`docs/bench/` 配下に geo_week_*.json 週次集約。
> KPI source は GSC / Cloudflare Web Analytics / Stripe metered usage / geo_weekly_bench_v3。
> 数値目標は memory `feedback_no_mvp_no_workhours` に従い「期日 + 工数」を書かず、 measurement protocol のみを記す。

**SEO 月次 metric**:
- GSC indexed pages 数 (`jpcite.com` property 単位)、目標 = sitemap URL の 85%+ を index 入り
- GSC organic clicks 数 (28 日 rolling)
- GSC organic impressions 数
- GSC average CTR
- GSC average position (top 20 query)
- top 20 keyword (本書 §3) の position 推移
- GSC top query × top page rank (どの query がどの page を呼んでいるか)
- per-record SEO page 数 (programs / cases / laws / enforcement / audience-pref) の coverage %
- Schema.org rich result 出現率 (`urlInspection.indexStatusResult.richResults` API)
- 旧 zeimu-kaikei.ai property の indexed page 数 → 0 への漸近

**GEO 月次 metric**:
- 100 質問 × 5 surface = 500 cell の citation rate (geo_weekly_v3.json)
- カテゴリ別 (B / S / D / R / C) citation rate
- 4 週 trend
- llms.txt の last-modified diff (週次)
- robots.txt の AI bot fetch ログ (Cloudflare Analytics で UA filter)
- `.well-known/mcp.json` `agents.json` の fetch 数
- ChatGPT GPT registry / Anthropic MCP registry / Cursor MCP marketplace 上の jpcite (autonomath-mcp) 表示順位

**Cross metric (SEO ↔ GEO bridge)**:
- 「jpcite」brand keyword の GSC click 数 / month vs ChatGPT B カテゴリ citation rate (相関を見る)
- 「補助金 検索 API」「補助金 MCP」 generic keyword の GSC click 数 vs ChatGPT S/D/R カテゴリ citation rate

**運用 health metric**:
- sitemap-index.xml の `<lastmod>` 鮮度 (daily cron 稼働率)
- per-program page の 404 率 (deploy 後 24h 内)
- AI bot crawl ログ (Cloudflare Worker `logpush` で GPTBot / ClaudeBot / PerplexityBot のリクエスト数)
- 旧 zeimu-kaikei.ai 301 redirect chain 健全性 (curl chain check 自動化)

---

## 6. 禁止事項 (本書 SOT)

memory に明記の以下は本書内でも厳格遵守:
- **広告予算 / Google Ads / LinkedIn Ads / Facebook Ads 一切提案禁止** (`feedback_organic_only_no_ads`)
- **SEO consultant / marketing agency / 外注 提案禁止** (`feedback_zero_touch_solo`)
- **「3 ヶ月で完了」「N 時間かかる」「採用」表現禁止** (`feedback_no_cost_schedule_hr`)
- **「Phase 1 / Phase 2 / MVP」表記禁止** (`feedback_no_mvp_no_workhours`)
- **「最初に X / 優先度 1 / どれから?」質問禁止、 やる/やらない 二択のみ** (`feedback_no_priority_question`)
- **本書内 即実行 list を運用者が picking する形式に統一**

---

## 7. 関連 docs / memory

- memory: `project_jpcite_rename.md` (2026-04-30 ブランド統一 SOT)
- memory: `feedback_legacy_brand_marker.md` (旧称表記の最小化)
- memory: `project_jpcite_2026_05_07_state.md` (LIVE confirmed b1de8b2)
- memory: `feedback_organic_only_no_ads.md`
- memory: `feedback_zero_touch_solo.md`
- memory: `feedback_no_mvp_no_workhours.md`
- memory: `feedback_no_priority_question.md`
- memory: `feedback_no_cost_schedule_hr.md`
- docs: `docs/_internal/seo_geo_strategy.md` (brand rename 細則、本書と補完)
- docs: `docs/_internal/seo_technical_audit.md` (技術 SEO の baseline、2026-04-23)
- docs: `docs/seo_strategy.md` (Brand-5 Pillar v8、長尾 5 pillar 設計)
- docs: `docs/bench/geo_methodology_v3.md` (週次 GEO bench protocol)
- data: `data/geo_questions.json` (100 ja + 4 en = 104 質問)
- script: `scripts/sitemap_gen.py` / `scripts/generate_program_pages.py` / `scripts/generate_prefecture_pages.py`
- workflow: `.github/workflows/competitive-watch.yml` / `index-now-cron.yml` / `tls-check.yml`

---

## 8. 本書の運用ルール

- 本書は **正本**。`docs/_internal/seo_geo_strategy.md` は brand rename 細則として併存 (memory `feedback_destruction_free_organization` に従い破壊禁止)。
- ranking 実測の数値が入ったら **本書をその場で update** (overwrite 方針、 memory `feedback_overwrite_stale_state`)。historical はファイル名 `seo_geo_strategy_2026_05_11.md` で snapshot として残る。
- 即実行 list の picking は運用者の judgement、本書は **やる手段とその効果の説明** に徹する。
- 「やらない」決定も memory に追加 (例: 「ふるさと納税 keyword は §52 fence 抵触で意図的不参戦」)。
