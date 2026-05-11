# jpcite Discovery Map 2026-05-11

8 露出 surface × 「登録手順 / 期待 organic reach / memory 制約遵守 / 失敗パターン」を並列 map 化。

- 序列無し (memory: `feedback_no_priority_question` / `feedback_no_mvp_no_workhours`)
- 広告ゼロ、organic only (memory: `feedback_organic_only_no_ads`)
- solo + zero-touch (memory: `feedback_zero_touch_solo`)
- スケジュール / 工数 / フェーズ分け 表記なし (memory: `feedback_no_cost_schedule_hr`)

入力 SOT:
- `site/.well-known/mcp.json` (schema_version=jpcite_ai_discovery_v1.0, ¥3/req, anonymous 3/day/IP)
- `site/llms.txt` (canonical=https://jpcite.com、139 MCP tools)
- `site/robots.txt` (GPTBot/ClaudeBot/PerplexityBot 等 Allow / + 10 sitemap-*.xml shard)
- `site/sitemap-*.xml` (11 shard、64,870 lines `sitemap-programs.xml` が最大)
- `CLAUDE.md` 8 cohort revenue model
- `docs/announce/PUBLISH_ORDER_2026_05_11.md` (寄稿 8 本、3 green + 5 yellow)

期待 reach 表記:
- **large** = 月間 organic discovery 1,000+ visits/installs/calls 期待
- **medium** = 月間 100-1,000
- **small** = 月間 0-100

---

## 1. AI agent platform registries

### 1.1 Anthropic MCP registry (mcp.so / mcpregistry.io 等)

**登録/掲載手順**:
1. `server.json` を canonical url `https://jpcite.com/server.json` で公開 (既に存在、自動 GET 可能).
2. `https://mcp.so/submit` フォームから「Server name=jpcite」「manifest=https://jpcite.com/server.json」「homepage=https://jpcite.com」「license=Public」を投稿. Anthropic 公式 registry の場合は GitHub repo `modelcontextprotocol/servers` に PR で `community/jpcite/README.md` を追加し、`uvx autonomath-mcp` install 手順、139 tools 説明、Bookyou株式会社 + T8010001213708 を記載.
3. `mcpregistry.io` の場合は GitHub OAuth → 「Add server」→ `mcp-server.json` URL を貼り付け. tags=[`japan`,`subsidy`,`evidence`,`rag`,`legal`,`tax`].
4. registry side に `description=Evidence prefetch API and MCP tools for Japanese public-program research` を pin.
5. `.mcpb` artifact `https://jpcite.com/downloads/autonomath-mcp.mcpb` を Claude Desktop extension index に同時登録.

**期待 organic reach**: **large**. mcp.so の上位 Japanese tag は数千 install/月の前例あり. 139 tools の数は registry 比較上位.

**memory 制約遵守**: anonymous 3/day/IP は registry 側 README で「free trial」と書ける. API key 発行は Stripe Checkout self-service (営業介在ゼロ).

**失敗パターン**: jpcite 名称が generic に埋もれ、検索クエリ「Japanese subsidy MCP」で 5 位以下に落ちる. → 改善: registry README に concrete cohort 名 (税理士 / M&A / 監査) を 1 行入れ、competitor `compare/` 9 本へ link.

### 1.2 Cursor MCP store

**登録/掲載手順**:
1. Cursor docs に従い `cursor_mcp_settings.json` snippet を公式 README に追加 (`{"jpcite": {"command":"uvx","args":["autonomath-mcp"]}}`).
2. Cursor の community MCP directory PR (GitHub `cursor-ai/community-mcp`) を出し、「@jpcite」 mention で 139 tools が discoverable と明示.
3. Cursor `.cursor/rules` ファイルで「日本企業/補助金/税制の質問は @jpcite に first hop」を seed.
4. `site/.cursor/` 配下に既存の Cursor profile を Cursor 側ドキュメントから直リンクで induce.
5. Cursor Twitter 公式 / Discord で MCP 紹介 thread に organic reply (Anthropic 同様 self-service).

**期待 organic reach**: **medium**. Cursor 日本 dev base は数万、MCP store 経由の install は数百/月想定.

**memory 制約遵守**: 営業ゼロ. Cursor 側に承認プロセスなし、self-publish.

**失敗パターン**: Cursor user が「日本特化 = 自分には関係ない」と離脱. → 改善: README 冒頭に「英訳 e-Gov + 租税条約 33 国 (FDI cohort)」を 1 行で出して非日本 user の onboarding を salvage.

### 1.3 ChatGPT GPT Store

**登録/掲載手順**:
1. ChatGPT Plus アカウントで Custom GPT を作成、name = `jpcite — 日本制度 Evidence Prefetch`.
2. Actions → Import OpenAPI from `https://api.jpcite.com/v1/openapi.agent.json` (billing/webhook 除外済 agent-safe subset).
3. Instructions に `llms.txt` の `### ChatGPT GPT` block (lines 110-115) を貼る. fence rule (`// fence: 税理士法§52` 等) を ChatGPT 出力 contract に組込.
4. Conversation starters 4 本: `法人番号で会社フォルダを作って` / `事業再構築×ものづくり 併用可?` / `30日以内に締切る東京の補助金は?` / `適格請求書発行事業者番号を確認したい`.
5. Public で publish, GPT Store category=「Productivity」 + 「Research」.

**期待 organic reach**: **large**. GPT Store 日本特化 top 10 は数千 conversation/月. jpcite の専門性 (11,601 programs + 13,801 invoice_registrants + 2,065 court_decisions) は GPT Store 上で稀少.

**memory 制約遵守**: anonymous 3/day/IP は ChatGPT user 側で共有 IP となり、heavy use 時に X-API-Key prompt が発火 (self-service path).

**失敗パターン**: GPT Store ranking algorithm が conversation 数 weighted → 初期 thin 状態で discovery 落ち. → 改善: llms.txt + zenn 記事から「ChatGPT で jpcite を呼ぶ方法」直リンク誘導.

### 1.4 Claude Project Marketplace

**登録/掲載手順**:
1. claude.ai の Project marketplace (community 出展 surface) に `jpcite Evidence Prefetch` を public project として登録.
2. Project knowledge に `llms.txt` + `llms-full.txt` を直接アップロード.
3. Custom instructions に `### Claude Code (MCP stdio + Read/Edit)` block (lines 105-108) を貼る. uvx 手順 + fence rule 同梱.
4. Project icon = jpcite favicon (https://jpcite.com/favicon.ico).
5. Anthropic Discord (#community-projects) に self-introduction post (organic, 1 回限り).

**期待 organic reach**: **medium**. Claude Project marketplace は新興、日本特化は希少なので絶対数は小だが conversion rate (project → 実 API call) は高い見込.

**memory 制約遵守**: Anthropic Discord post は CS チーム介在せず operator 本人のみ. zero-touch.

**失敗パターン**: Claude Project は MCP 不要 (knowledge 同梱で完結) のため API/MCP に流れない. → 改善: project instruction に「最新行は MCP `search_programs` で取得」を明記、knowledge は freeze 状態であることを断る.

### 1.5 Codex (Anthropic) / Gemini Extensions

**登録/掲載手順**:
1. Anthropic Codex (hosted_mcp 連携) の場合: `https://jpcite.com/mcp-server.json` を Codex 設定 UI に直接貼り付ける. anonymous 3/day/IP は IP 共有問題があるため X-API-Key 推奨を Codex 側 docs にリンク.
2. Gemini Extensions の場合: Google Workspace Marketplace に「jpcite」拡張を申請. manifest = `https://jpcite.com/.well-known/ai-plugin.json` を流用.
3. Gemini Code Assist の context provider として `jpcite.com/llms.txt` を Google Drive 経由で参照可能にする (任意).
4. Codex / Gemini が GPTBot / Google-Extended で `robots.txt` allow 済を verify.
5. `compare/freee` (Gemini ユーザ層 = freee 顧客と被る) ページ link で自然流入を狙う.

**期待 organic reach**: **medium**. Codex は Anthropic 社員 / 内部 dogfooding 由来の認知ルート、Gemini Extensions は Workspace 公式 directory.

**memory 制約遵守**: Workspace Marketplace は app 審査ありだが、jpcite は app でなく URL ベースの context provider なので承認軽い.

**失敗パターン**: Codex 用語 / Gemini Extensions 仕様が頻繁に変わる → 1 surface dead でも他 7 surface で補填可.

---

## 2. Developer SEO

### 2.1 GitHub repo SEO (README / Topics / Discussions)

**登録/掲載手順**:
1. GitHub repo 公開. README に Hero section: 「jpcite — Japanese public-program Evidence prefetch API + MCP (139 tools)」, badges (PyPI version / MCP protocol version / OpenAPI valid).
2. Repository Topics: `mcp` `mcp-server` `claudeai` `claude` `anthropic` `openai` `chatgpt` `cursor` `cline` `gemini` `rag` `evidence` `japan` `subsidy` `tax` `llm-tools` `agent` `openapi` `fastapi` `python`.
3. GitHub Discussions を Open. 5 seed thread: 「導入手順 (Claude Desktop / Cursor / Cline)」「139 tools の使い分け」「ChatGPT Custom GPT との連携」「Japanese tax/legal fence の出力規約」「料金 ¥3/req と無料 3/day/IP の境界」.
4. Repo Settings → Pages = off (site/ は CF Pages 配信のため). Repo Description = mcp.json `description` と完全一致.
5. CHANGELOG.md を毎 release で更新、Releases page で「Sourcemap = `https://jpcite.com/sitemap-index.xml`」を pin.

**期待 organic reach**: **large**. Topics `mcp` / `mcp-server` は GitHub Trending Japan で頻繁に上位、Trending 達成すると数千 stars/月.

**memory 制約遵守**: GitHub Discussions は self-service Q&A (CS チーム 不要). issue trackerは「24h 以内 best effort」のみ明示.

**失敗パターン**: Topics 上限超過 (GitHub topics 上限 20) で削られる. → 改善: 効きどころは `mcp-server` / `claudeai` / `rag` / `japan` の 4 軸に絞り残りは README に書く.

### 2.2 PyPI / npm package page SEO

**登録/掲載手順**:
1. PyPI `autonomath-mcp` package description (long_description) を `llms.txt` の英訳版で full text 投入. classifiers = `Development Status :: 5`, `Topic :: Office/Business`, `Topic :: Scientific/Engineering :: Artificial Intelligence`.
2. PyPI Project URLs: Homepage=https://jpcite.com, Documentation=https://jpcite.com/docs, Repository=GitHub, Changelog=https://jpcite.com/changelog, Funding=Stripe direct (¥3/req).
3. npm `@jpcite/agents` (v0.3.4 で publish 済の参考 agent 5 種) の README.md に 5 種 use case を embed. tags=[`mcp`,`anthropic`,`japan`,`evidence`,`rag`].
4. PyPI Stats を README に embed (badges.io). Download count を organic social proof として表示.
5. PyPI search 上位を狙うため keyword は `japanese subsidy`, `mcp server`, `evidence prefetch`, `corporate registry japan`.

**期待 organic reach**: **medium**. PyPI search `mcp` 上位は数千 dl/月実績の前例あり.

**memory 制約遵守**: PyPI / npm は self-publish、承認ゼロ.

**失敗パターン**: PyPI 1.5MB upload limit を超える dependency (sqlite-vec 等) のため install fail. → 改善: extras 分割 (`autonomath-mcp[full]` vs `autonomath-mcp[minimal]`).

### 2.3 GitHub trending (Python / TypeScript)

**登録/掲載手順**:
1. Repo に「First commit から 1 週間で 50 stars」を organic 形成 (Zenn / note / X 経由).
2. Trending page の言語 filter「Python」+ Spoken Language「Japanese」で上位狙い.
3. 関連 Awesome list (`awesome-mcp-servers`, `awesome-japan-ai`, `awesome-claude-code`) に PR で jpcite を追記.
4. Hacktoberfest 等の community campaign で「good first issue」を 10 件 open し organic contributor を誘発.
5. README badges に `https://hits.seeyoufarm.com` 風の viewer count を入れて social proof.

**期待 organic reach**: **medium**. trending 1 日載れば数千 visit、stars 数百一気. ただし日本特化のため英語圏 trending では continuous 上位は困難.

**memory 制約遵守**: trending は organic only な metric、操作不可.

**失敗パターン**: 一過性で trending 落ちる. → 改善: weekly release + changelog blog 連動で再 trending 機会を循環.

---

## 3. Technical content platform

### 3.1 Zenn / Qiita / note (技術記事)

**登録/掲載手順**:
1. Zenn: `zenn_jpcite_mcp.md` (green、即時 publish 可) を Zenn Book / Article で publish. Topics=[`mcp`,`claudecode`,`ai`,`rag`,`openapi`,`stripe`]. Tweet button + LinkedIn share button 同梱.
2. Qiita: 同じ記事を「139 個の MCP tools を 1 行で使える Python ライブラリの作り方」リフレームで publish. tag=[`Python`,`MCP`,`Claude`,`FastAPI`,`OpenAPI`]. Qiita organization は無し (solo).
3. note: `note_jpcite_mcp.md` (green) を note magazine で publish, 「日本企業向け AI agent 開発者向け」マガジンに格納. SNS 拡散 起点.
4. dev.to: 英語訳版 (llms.en.txt + en/* の翻訳資産) を「Japanese subsidy database for AI agents」として publish, tags=[`mcp`,`anthropic`,`rag`,`python`,`japan`].
5. Hashnode: SEO/GEO 視点で「Why we made jpcite.com llms.txt + GPTBot allow + sitemap-llms」記事を publish.

**期待 organic reach**: **large**. Zenn / Qiita の MCP / Claude tag 上位は数千 PV/記事 の前例. note は SNS 拡散経由で同等の reach.

**memory 制約遵守**: 寄稿は self-publish, 編集介在ゼロ.

**失敗パターン**: 同一内容を 5 platform に貼ると Google duplicate content penalty. → 改善: 各 platform で headline + intro + closing を変える (本論共通可、canonical link を相互設定).

### 3.2 dev.to / Hashnode (英語)

**登録/掲載手順**:
1. dev.to: 翻訳した `zenn_jpcite_mcp.md` の英訳版を「How we built a 139-tool MCP server for Japanese public records」で publish. canonical_url=Zenn 版に向ける.
2. Hashnode: 「Open-sourcing our llms.txt + GPTBot allowlist for a Japanese AI evidence API」technical post.
3. tag=[`mcp`,`anthropic`,`rag`,`fastapi`,`openapi`,`python`,`japan`,`legal-tech`,`fintech`].
4. Series 化で 5 本 cluster (`#1 MCP architecture`, `#2 OpenAPI agent-safe subset`, `#3 SQLite FTS5 trigram pitfalls`, `#4 Anonymous quota + Stripe metered`, `#5 GEO via llms.txt + sitemap-llms.xml`).
5. dev.to の `# discuss` thread で「What's missing in your country's public records?」を聞き、organic 比較を induce.

**期待 organic reach**: **medium**. dev.to 日本特化は thin だが、`mcp` / `rag` / `agent` tag 経由で英語圏 dev に届く副流効果.

**memory 制約遵守**: self-publish, 承認ゼロ.

**失敗パターン**: 英語 dev は日本制度の値打ちが分からない. → 改善: 「あなたの国でも同じ手法を再現する OSS template」とフレーミング. ライセンスは Public 表明.

---

## 4. 公式 + 業界 publication

### 4.1 PRTIMES (公的リリース)

**登録/掲載手順**:
1. PRTIMES アカウント (Bookyou株式会社, T8010001213708) で `prtimes_jpcite_release.md` (green) を release. カテゴリ=「サービス」「テクノロジー」「金融・ファイナンス」.
2. release 添付物: jpcite 動作 screenshot (Claude Desktop / Cursor / ChatGPT GPT), `data-freshness` dashboard screenshot, `trust/purchasing` 1-screen summary screenshot, 8 cohort revenue model diagram.
3. release 末尾に「無料 3 req/IP/日 トライアル」+「API key Stripe 即時発行」+「Bookyou株式会社 info@bookyou.net 24h 以内対応」を明記.
4. PRTIMES の RSS 連動 → 日経 / 東洋経済 等の自動 ingest 経路に乗せる.
5. release 後 24h で Google Search Console と Cloudflare Analytics で referral 計測 (PUBLISH_ORDER_2026_05_11.md A/B/C 指標).

**期待 organic reach**: **medium-large**. PRTIMES の release は SEO benefit 月数千 impressions、業界紙 ingest 二次 reach 大.

**memory 制約遵守**: 営業電話なし、release URL 公開のみ. 「広報担当」表記は人的チーム想起させない範囲で OK (PUBLISH_ORDER 監査 green).

**失敗パターン**: 競合 release に埋もれ自然 indexing 弱. → 改善: PRTIMES 内の「テクノロジー」カテゴリ trend trigger を月次 release で循環.

### 4.2 業界紙 (税理士新聞 / TKC 月報 / 行政書士界 / M&A Online / 中小企業診断士界)

**登録/掲載手順** (各紙 contact form 経由):
1. 税理士新聞: `zeirishi_shimbun_jpcite.md` (yellow, ¥1/req → ¥3/req patch 後) を寄稿. 編集部 contact から「税理士 AI 化 寄稿」打診.
2. TKC 月報: `tkc_journal_jpcite.md` (yellow) を寄稿. TKC NF 系列の編集部 contact 経由.
3. 月刊行政書士 / 日本行政書士会連合会会報: `gyosei_kaiho_jpcite.md` (yellow) を寄稿.
4. M&A Online / M&A 仲介協会会報: `ma_online_jpcite.md` (yellow) を寄稿.
5. 中小企業診断協会会報 / 月刊企業診断: `shindanshi_kaiho_jpcite.md` (yellow) を寄稿.

各寄稿に jpcite.com link、Bookyou株式会社 + T8010001213708、無料 3 req/IP/日 トライアル を必ず embed.

**期待 organic reach**: **medium**. 業界紙 1 本あたり読者は数千-数万、ただし conversion (記事 → 実 API call) は organic web より高い (専門家層).

**memory 制約遵守**: 寄稿は organic outreach、営業電話なし (PUBLISH_ORDER 監査 green).

**失敗パターン**: 編集側が「AI = 自社専門領域への脅威」と embargo. → 改善: 寄稿冒頭で 7 業法 fence を明示し「専門家業務を代替しない」スタンスを先に提示 (既に 5 本ともこのスタンス).

### 4.3 日経 / 東洋経済 オンライン (long shot)

**登録/掲載手順**:
1. 日経 BP / 日経クロステック 編集部 contact (info@nikkei.bp.com 等) に PRTIMES release を起点として打診. テーマ = 「中小企業向け AI agent 経由の公的制度 evidence prefetch」.
2. 東洋経済オンライン「テクノロジー」セクションへ寄稿 pitch (自社 release ではなく寄稿).
3. 寄稿テーマ案: 「中小企業庁 11,601 制度を AI agent が 1 req ¥3 で横断検索する技術構造」「7 業法 fence を遵守した AI tool 設計」「solo + zero-touch + organic only で日本初の MCP 制度 DB を公開」.
4. 寄稿成立可否は編集判断に依存、ダメなら自社 blog で同記事を publish + 日経 referral 無視で organic SEO だけ拾う.
5. 日経 / 東洋経済 1 度の掲載で organic SEO authority が向上 (backlink から domain authority 上昇).

**期待 organic reach**: **small-medium** (掲載成立時 large). 掲載成立確率は低い (long shot 明示).

**memory 制約遵守**: 自社側に PR エージェント不要、operator 本人が pitch.

**失敗パターン**: 編集に返信なし. → 改善: PRTIMES + 業界紙経由で indirect な引用を経て authority を貯めてから 6 ヶ月後再 pitch.

---

## 5. Community / forum

### 5.1 HackerNews Show HN

**登録/掲載手順**:
1. Show HN タイトル: `Show HN: jpcite — 139 MCP tools for Japanese public-record evidence prefetch (¥3/req)`.
2. 本文に 5 段落: (1) why we built it (LLM が日本制度を hallucinate する問題), (2) what's inside (11,601 programs / 13,801 invoice / 2,065 court / 2,286 adoption), (3) tech stack (FastAPI + SQLite FTS5 + sqlite-vec + MCP 2025-06-18), (4) pricing (¥3/req metered, 3 req/IP/day free anonymous), (5) how to try in 60 sec (`uvx autonomath-mcp` or import OpenAPI to ChatGPT Custom GPT).
3. Hero link = https://jpcite.com/playground (interactive REST explorer, anon quota live).
4. submit timing は HN 米国朝 (JST 22-24 時) で organic upvote velocity を確保.
5. Show HN comments に operator 本人 (info@bookyou.net) が直返信 (24h 以内).

**期待 organic reach**: **medium-large**. Show HN front page 達成で数万 visits、API call は数百, GitHub stars 数百一気.

**memory 制約遵守**: HN は organic only platform、ads ban あり.

**失敗パターン**: 日本特化が英語圏 HN で discount される. → 改善: 「same blueprint applies to US public records」「Open-source the GPTBot allowlist + llms.txt scheme」と generic 価値を冒頭で押し出す.

### 5.2 Product Hunt

**登録/掲載手順**:
1. Product Hunt launch (Maker = 梅田茂利 / Bookyou株式会社). category = 「Developer Tools」「Artificial Intelligence」「APIs」.
2. Hero gallery 5 枚: Claude Desktop screen / Cursor MCP servers screen / ChatGPT Custom GPT Actions / Stripe Checkout 1-min flow / data-freshness dashboard.
3. Tagline = `Evidence prefetch for Japanese public records. 139 MCP tools. ¥3/req.`
4. First comment (Maker) で why/what/how の 3 段落 + free 3 req/IP/day を明記.
5. PH Hunter (Hunter 不在で self-hunt 可). organic upvote のため日本 dev / X コミュニティに 1 度だけ launch post.

**期待 organic reach**: **medium**. PH top 5 of the day 達成で数千 visits、jpcite の日本特化 + 英語 docs 完備で英語 dev 流入も拾える.

**memory 制約遵守**: PH は organic only.

**失敗パターン**: PH algorithm が英語専用 product に偏る. → 改善: 英語 site (`/en/*`) と llms.en.txt の存在を gallery で前面.

### 5.3 Reddit (r/LocalLLaMA / r/ChatGPT / r/japan)

**登録/掲載手順**:
1. r/LocalLLaMA: 「Released a 139-tool MCP server for Japanese public records (Claude Desktop / Cursor / Cline supported)」technical post.
2. r/ChatGPT: 「Built a Custom GPT for Japanese subsidies and tax — uses an evidence API behind it」 use-case post.
3. r/MachineLearning: 「Sharing the OpenAPI agent-safe subset pattern we used for ChatGPT Actions」educational post.
4. r/japan: 「Made a free 3 req/day API for searching Japanese public subsidies/invoices/court rulings」consumer-facing post (英語 + 日本語両併記).
5. r/programming, r/Python: 「FastAPI + SQLite FTS5 trigram 落とし穴 + workaround」technical post.

**期待 organic reach**: **medium**. Reddit は 1 post 数千 view 程度、subreddit moderator が self-promo を制限する場合あり.

**memory 制約遵守**: Reddit 各 subreddit の self-promotion rule を遵守、organic post のみ.

**失敗パターン**: r/LocalLLaMA は local model 専門で API 紹介は flat. → 改善: 「Claude Desktop でも uvx 1 行で動く」を強調し agentic frontier に positioning.

### 5.4 Twitter/X 日本 dev コミュニティ

**登録/掲載手順**:
1. operator Twitter/X (Bookyou株式会社 or 梅田茂利) で「jpcite — Japanese 制度 Evidence Prefetch + MCP 139 tools (¥3/req)」launch thread.
2. thread 5 ツイート: (1) why, (2) what (counts), (3) Claude Desktop 60s install, (4) Cursor / ChatGPT integration screenshot, (5) link to https://jpcite.com/playground.
3. hashtag = `#MCP`,`#ClaudeCode`,`#AIエージェント`,`#補助金`,`#税理士DX`,`#行政書士AI`,`#中小企業`.
4. retweet trigger: AI 業界インフルエンサ (organic reply 経由でのみ、DM cold outreach はしない).
5. 各 publish の moment に Zenn / note / PRTIMES / Show HN を thread tail で連動.

**期待 organic reach**: **medium**. 業界 dev インフルエンサ 1 RT で数千 impressions, jpcite link で数十 click-through.

**memory 制約遵守**: cold DM 禁止 (営業介在), organic reply のみ.

**失敗パターン**: 日本 dev X は MCP 認知低い. → 改善: 「Claude Desktop に貼る 1 行設定」demo GIF を thread head に置き onboarding hurdle を下げる.

---

## 6. Government / academic surface

### 6.1 e-Gov メールマガジン / 政府 open data カタログ登録

**登録/掲載手順**:
1. e-Gov 利用者向けメルマガに「e-Gov 法令 (CC-BY 4.0) を活用した AI evidence API」を投書. 投稿先 = e-Gov 運営事務局.
2. 政府 open data カタログ (data.go.jp) に「jpcite OpenAPI 仕様 (政府公開 dataset 横断検索 endpoint)」を datasets として登録. metadata = `https://api.jpcite.com/v1/openapi.json`, license=「Public 表明 + 元データ各 license に従属」.
3. data.go.jp の dataset 登録時、tag=[`横断`,`AI`,`MCP`,`evidence`,`OpenAPI`].
4. e-Gov 法令 API の利用事例として政府 portal に listing reciprocity を依頼.
5. METI / NTA / 中小企業庁 の dataset ページ末尾に「2 次利用事例 jpcite」を依頼.

**期待 organic reach**: **small-medium**. 政府 portal は流入数は小だが信頼性 stamp として大. 業界紙 / 自治体経由の二次引用が組合せ効果.

**memory 制約遵守**: 政府 portal 登録は self-service, 営業介在不要.

**失敗パターン**: 政府事務局返信遅延 → 改善: メルマガ + データカタログ + 各省 portal の 3 経路を並列に出して 1 つでも刺さるのを待つ.

### 6.2 日本デジタル庁 GovTech リスト

**登録/掲載手順**:
1. デジタル庁 GovTech カタログ (gov-base) に「jpcite — 公的制度 evidence API」を登録. 申請先 = digital.go.jp お問い合わせ form.
2. metadata = operator (Bookyou株式会社 T8010001213708), 提供 dataset (programs/laws/court/invoice/enforcement), pricing (¥3/req metered + free 3/day/IP).
3. GovTech meetup / unconference (organic 参加) で 1 度だけ jpcite を紹介.
4. デジタル庁の「ベース・レジストリ」連携検討時の事例として listing 依頼.
5. デジタル庁 RSS / メルマガで定期的に jpcite update を依頼 (organic, 1 month interval).

**期待 organic reach**: **small**. GovTech リスト経由の直接流入は thin、ただし政府関係者 / 自治体経由の二次拡散が起点になる.

**memory 制約遵守**: GovTech リスト登録は organic.

**失敗パターン**: デジタル庁 review process が遅延. → 改善: PRTIMES + 業界紙経由で先に公知化してから GovTech catalog にエビデンス済みで再申請.

### 6.3 学会 (情報処理学会 / 人工知能学会) のリソース紹介

**登録/掲載手順**:
1. 情報処理学会 IPSJ-MAGAZINE 「研究リソース紹介」コーナーに jpcite を投稿. テーマ = 「日本制度 evidence prefetch を MCP で実装した OSS の知見」.
2. 人工知能学会 全国大会 / SIG-AGI / SIG-DOCMAS にデモ枠申請. presentation 内容 = 「LLM hallucination 防止のための evidence prefetch アーキテクチャ」.
3. 各学会の学生向け論文 / 卒論 で jpcite を引用してもらえる導線として「データセット引用形式」を `data-licensing.html` に記載.
4. arXiv に「jpcite: Evidence Prefetch Layer for Japanese Public-Record LLM Agents」technical paper を投稿 (cs.AI / cs.IR).
5. 学会 portal の「ツールリスト」「リソースリスト」に listing 依頼.

**期待 organic reach**: **small**. 学会経由は数十-数百流入だが、引用 chain で長期 SEO authority に効く.

**memory 制約遵守**: 学会発表は self-service paper / poster 提出.

**失敗パターン**: 学会の review cycle が長く即効性 thin. → 改善: arXiv pre-print + Zenn 同時 publish で速度確保.

---

## 7. GEO (Generative Engine Optimization)

### 7.1 llms.txt / llms-full.txt の AI 学習データ取り込み経路

**登録/掲載手順**:
1. `https://jpcite.com/llms.txt` (既存) + `llms-full.txt` + 英語版 `llms.en.txt` + `llms-full.en.txt` を public 公開. robots.txt で全 AI crawler に Allow.
2. llmstxt.org の community list (GitHub の `llmstxt/awesome-llms-txt` 等) に jpcite を PR で追加.
3. llms.txt 内に「Docs / Examples / Q&A / Comparisons / Trust signals」セクションを既に網羅 (現状 418 行).
4. ChatGPT / Claude / Gemini / Perplexity が学習時に取り込むよう、毎月 last_modified header を更新.
5. llms.txt の `mtime` を sitemap に書き込み、Google Search Console / Bing Webmaster で submit.

**期待 organic reach**: **large**. AI 学習データに 1 回取り込まれると、AI 回答内の citation として無限再生 (organic GEO の核心).

**memory 制約遵守**: llms.txt は self-publish、誰の承認も不要.

**失敗パターン**: AI 各社の crawler が `llms.txt` を読まない (まだ慣習として確立途上). → 改善: sitemap-llms.xml + meta tag (`<meta name="llms-txt" content="https://jpcite.com/llms.txt">`) を全ページに埋め込み、明示的に AI crawler に告知.

### 7.2 GPTBot / ClaudeBot / Google-Extended / PerplexityBot 等 crawler welcome

**登録/掲載手順**:
1. `site/robots.txt` で 18 種 AI/answer crawler を明示 Allow (既に Googlebot / Bingbot / DuckDuckBot / Google-Extended / GPTBot / ChatGPT-User / OAI-SearchBot / ClaudeBot / Claude-User / Claude-SearchBot / anthropic-ai / PerplexityBot / CCBot / Applebot / Applebot-Extended / Meta-ExternalAgent / Amazonbot / Bytespider が Allow).
2. Crawl-delay: 1 で過度な burst を防ぐが、AI crawler には fast crawl を許す.
3. cloudflare の AI crawler analytics で実 crawl rate を毎月確認.
4. crawler が 404 / 5xx を踏まないよう全ページの health probe を月次 run.
5. AhrefsBot / SemrushBot / MJ12bot / DotBot / PetalBot / YandexBot は Disallow (SEO scraper).

**期待 organic reach**: **large**. AI crawler が一度 crawl すれば AI 回答内 citation が継続発生.

**memory 制約遵守**: robots.txt は self-publish.

**失敗パターン**: AI crawler が 404 page (例: 削除済 program ID) を踏んで domain reputation 下げ. → 改善: 削除 page には HTTP 410 Gone を返し、リダイレクト先を提示.

### 7.3 sitemap-llms.xml (AI 専用 sitemap)

**登録/掲載手順**:
1. `sitemap-llms.xml` を新規作成、`llms.txt` + `llms.en.txt` + `llms-full.txt` + `llms-full.en.txt` + `mcp-server.json` + `openapi.agent.json` + `openapi.json` + `.well-known/*.json` を listing.
2. robots.txt の Sitemap: directive に追記.
3. lastmod は llms.txt 更新時刻と sync.
4. Google Search Console / Bing Webmaster Tools で sitemap submit.
5. llmstxt.org の sitemap-llms.xml 標準仕様策定 thread に jpcite を実例として提示.

**期待 organic reach**: **medium**. 仕様確立過渡期、現時点では small だが先行投資効果.

**memory 制約遵守**: self-publish.

**失敗パターン**: AI crawler が sitemap-llms.xml をまだサポートしない. → 改善: 通常 sitemap-index.xml にも同じ URL を含めて redundant fallback.

---

## 8. 直接 outreach 不可、organic only の経路

### 8.1 業界 influencer の自然引用待ち (税理士 YouTuber / 行政書士 SNS)

**登録/掲載手順**:
1. influencer が「日本制度 AI ツール」を検索した時に jpcite が surface するよう、業界紙 / Zenn / PRTIMES 経由で indirect 露出を蓄積.
2. 業界 influencer の content (税理士 YouTuber 動画 / 行政書士 note / 診断士 LinkedIn post) で jpcite が natural cite される時、operator が retweet で organic amplify (DM cold outreach は禁止).
3. influencer が試したくなる hook を「無料 3 req/IP/日 即試行」「Claude Desktop 60 秒 install」で web に常設.
4. influencer 個人 SNS で言及されたら operator 本人 (info@bookyou.net) が 24h 以内に organic reply.
5. influencer 発信のスクショや引用は trust/customer-quote として site/audiences 配下に reciprocity link で掲載 (許諾後のみ).

**期待 organic reach**: **medium-large** (引用成立時). 1 influencer の cite で数千流入の前例あり.

**memory 制約遵守**: cold DM 禁止 (営業介在), organic 引用待ちと自然反応のみ.

**失敗パターン**: 引用ゼロが続く. → 改善: influencer 自身が見つけやすいよう Zenn / 業界紙 / PRTIMES の cluster を恒常的に保つ.

### 8.2 AI agent dev の認知 (Anthropic / OpenAI 社員の自然 discover)

**登録/掲載手順**:
1. Anthropic / OpenAI / Google / Cursor / Cline 社員が「日本 MCP server」を検索した時、jpcite が GitHub Topics / mcp.so / Zenn / Awesome list の各経路で発見されるように cluster を維持.
2. 各社の MCP / agent showcase 事例集に「Japanese public records」例として jpcite を candidate listing (organic, 各社 PR や case study ページに jpcite を勝手に掲載は不可、各社側からの inbound 申し出を待つ).
3. Anthropic Discord / OpenAI dev community / Cursor Discord / Cline GitHub Discussions に self-introduce を 1 度だけ行い、その後は organic reply のみ.
4. operator は MCP 規格策定 (modelcontextprotocol/specification GitHub repo) の議論に substantive 貢献し、その文脈で自然に jpcite を引用.
5. AI 社員が jpcite を試した時にすぐ動くよう、anon quota + Claude Desktop config example を最短経路に常設.

**期待 organic reach**: **small-medium** (社員引用成立時 large). Anthropic 社員 1 人が tweet で言及すれば数千 visits の前例.

**memory 制約遵守**: cold outreach / 営業 ban, organic only.

**失敗パターン**: AI 社員に discover されない. → 改善: 「MCP server サンプルの一つ」「日本特化の OSS reference」として organic surface を増やし、検索流入の確率を底上げ.

---

## 期待 reach summary table

| # | Surface | 期待 organic reach |
|---|---------|--------------------|
| 1.1 | Anthropic MCP registry (mcp.so 等) | **large** |
| 1.2 | Cursor MCP store | medium |
| 1.3 | ChatGPT GPT Store | **large** |
| 1.4 | Claude Project Marketplace | medium |
| 1.5 | Codex / Gemini Extensions | medium |
| 2.1 | GitHub repo SEO | **large** |
| 2.2 | PyPI / npm package page | medium |
| 2.3 | GitHub trending | medium |
| 3.1 | Zenn / Qiita / note | **large** |
| 3.2 | dev.to / Hashnode | medium |
| 4.1 | PRTIMES | medium-large |
| 4.2 | 業界紙 5 系統 | medium |
| 4.3 | 日経 / 東洋経済 | small (掲載成立時 large) |
| 5.1 | HackerNews Show HN | medium-large |
| 5.2 | Product Hunt | medium |
| 5.3 | Reddit | medium |
| 5.4 | Twitter/X 日本 dev | medium |
| 6.1 | e-Gov メルマガ / data.go.jp | small-medium |
| 6.2 | デジタル庁 GovTech | small |
| 6.3 | 情報処理学会 / 人工知能学会 | small |
| 7.1 | llms.txt / llms-full.txt | **large** |
| 7.2 | GPTBot / ClaudeBot allow | **large** |
| 7.3 | sitemap-llms.xml | medium |
| 8.1 | 業界 influencer 自然引用 | medium-large (引用成立時) |
| 8.2 | AI agent dev 自然 discover | small-medium (社員引用成立時 large) |

**large** 評価: 1.1 / 1.3 / 2.1 / 3.1 / 7.1 / 7.2 (6 surface)
**medium-large** 評価: 4.1 / 5.1 / 8.1 (3 surface)

---

## 失敗パターン × 改善経路 cross-cut

複数 surface に共通する failure mode と最小修復経路:

| failure mode | 該当 surface | 改善経路 |
|--------------|--------------|----------|
| 「日本特化 = 自分には関係ない」で英語圏 dev 離脱 | 1.2 / 3.2 / 5.1 / 5.2 | 英訳 e-Gov + 33 国租税条約 + 「OSS template として再現可能」を冒頭で出す |
| platform algorithm に thin 状態で discovery 落ち | 1.3 / 5.2 / 2.3 | llms.txt + 業界紙 + Zenn の 3 経路で初期 organic upvote / install を循環 |
| AI crawler が新仕様 (llms.txt / sitemap-llms.xml) をまだ読まない | 7.1 / 7.3 | 通常 sitemap-index.xml に冗長 listing + meta tag fallback |
| 編集 / review プロセスが長く即効性 thin | 4.3 / 6.1 / 6.2 / 6.3 | self-publish chain (Zenn / GitHub / PRTIMES) で先に authority を蓄積、6 ヶ月後に formal channel 再 pitch |
| 引用ゼロが続く (influencer / AI 社員) | 8.1 / 8.2 | organic discovery surface を恒常的に増やし、検索流入確率を底上げ |
| 短期一過性で trending / front page 落ち | 1.3 / 2.3 / 5.1 / 5.2 | weekly release + changelog blog 連動で再 trending 機会を循環 |

---

## 8 surface 並列展開時の構造特性

- **全 surface 並列**: 序列なし. 1 surface 失敗時に他 7 surface で補填可能な冗長設計.
- **organic only**: 全 surface で広告予算ゼロ, cold outreach ゼロ.
- **solo zero-touch**: 全 surface で営業 / CS / 法務チーム不要. operator (info@bookyou.net, 24h 以内) が組成.
- **self-service path**: 全 surface のゴール = jpcite.com playground または `uvx autonomath-mcp` で試行開始 → Stripe Checkout self-mint で paid 移行.
- **重複資産 leverage**: 5 surface (PRTIMES / 業界紙 / Zenn / note / Show HN) は全て `llms.txt` + `mcp-server.json` + `openapi.agent.json` の同一 SOT を引用、Drift Free.

---

## reach 補強の 4 cross-cut

surface の組合せで reach 増幅:

1. **「Zenn (3.1) → Show HN (5.1) → mcp.so (1.1)」3 連発**: 1 週間内 publish で AI dev community 内の自己強化ループ.
2. **「PRTIMES (4.1) → 業界紙 (4.2) → 業界 influencer (8.1)」3 連発**: 業界専門家層の信頼 stamp + 自然引用.
3. **「llms.txt (7.1) → GPTBot allow (7.2) → AI agent dev discover (8.2)」3 連発**: GEO 起点で AI 回答内 citation を継続発生.
4. **「GitHub trending (2.3) → PyPI / npm (2.2) → Codex / Gemini (1.5)」3 連発**: developer SEO 起点で AI platform 内の発見性を補強.

各 cluster は並列に進行、各 surface 単発でも degenerate しない構造.
