# jpcite — AI Agent Platform 掲載/登録 Checklist (8 platforms)

**作成日**: 2026-05-11
**対象**: jpcite (PyPI 名 `autonomath-mcp` v0.4.0) を AI agent エコシステムへ流す ための **operator (梅田) が手動 submission する手順書**
**前提**: Bookyou株式会社 (T8010001213708) / info@bookyou.net / canonical = `https://jpcite.com` / 100% organic + solo + zero-touch
**Claude 自動 submission 不可**: 各 platform の認証/同意ボタン/CAPTCHA があるため、Claude (= 私) は manifest 整備までしか担当できない。本書は **user が読んで実行する** 手順書

---

## 0. 横断的に必要な asset (1 度作れば 8 platform で再利用)

| asset | path / URL | 状態 | 用途 |
|---|---|---|---|
| logo SVG (square 1:1) | `site/assets/logo.svg` `site/assets/logo-v2.svg` `site/assets/mark.svg` `site/assets/mark-v2.svg` | green | Smithery / mcp.so / Cursor / Gemini |
| logo PNG 512×512 | `site/assets/favicon-512.png` | green | DXT / GPT Store / Plugin store |
| logo PNG 192×192 | `site/assets/favicon-192.png` | green | Gemini Extensions |
| icon for DXT | `dxt/icon.png` | green | Claude Desktop Extension |
| apple-touch-icon | `site/assets/apple-touch-icon.png` | green | OG fallback |
| OG image landscape | `site/assets/og.png` `site/assets/og-twitter.png` | green | GPT Store カバー / Note 寄稿 |
| OG image square | `site/assets/og-square.png` | green | Anthropic registry square preview |
| MCP preview screenshots | `site/assets/mcp_preview_1.png` `mcp_preview_2.png` (+ `.webp`) | green | Cursor / Smithery / mcp.so |
| GitHub social card | `site/assets/github-social-card.png` (+ `.webp`) | green | GitHub repo Open Graph |
| README badge | `site/assets/README_badge.svg` | green | repo / 寄稿記事 |
| favicon variant | `site/assets/favicon-v2.svg` `favicon.svg` `favicon-16.png` `favicon-32.png` `favicon-192.webp` `favicon-512.webp` | green | sitewide |
| 紹介動画 (30s〜90s) | **未作成** | **red** | 任意だが Gemini Extensions / GPT Store で訴求力↑ |
| OG per page (programs/laws/cases) | `site/og/*.png` (10+ 枚) | green | 寄稿/SNS |

**asset の追加が必要なもの (即修正候補)**:
1. **30-90秒 紹介動画** (mp4 + 字幕) — GPT Store / Gemini Extensions / Cursor MCP store で訴求力差が出る。Loom or QuickTime で 1 take 録画 → mp4
2. **square 1024×1024 logo PNG** (現状 512 まで) — Anthropic registry / Smithery で 1024 を要求するケースあり
3. **長辺 1920 banner PNG** (現状 og.png は 1200×630) — Cursor 一覧の hero に高解像要求

---

## 1. Anthropic MCP registry (mcp.so / mcpregistry.io / .well-known/mcp.json)

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **green** |
| **registry URL** | (a) `https://modelcontextprotocol.io/registry` (正式) (b) `https://mcp.so/` (community) (c) `https://mcpregistry.io/` (community) |
| **必要 manifest** | `server.json` (root 直下、`$schema=https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json` に準拠、name=`io.github.shigetosidumeda-cyber/autonomath-mcp` v0.4.0 既に整備済) |
| **AI agent crawl 用** | `https://jpcite.com/.well-known/mcp.json` (jpcite_ai_discovery_v1.0 schema、generated_at=2026-05-07、155 tools、auth/pricing/recurring_workflows/trust_surfaces 完備) |
| **必要 asset** | logo SVG (mark.svg) + 1024 png (推奨) + README screenshot |
| **必要 metadata** | name / description / version / repository / packages[pypi=autonomath-mcp] / categories=[government,legal,finance,data,compliance] / license=MIT |
| **必要 verification** | (a) GitHub OAuth login (`shigetosidumeda-cyber/autonomath-mcp` owner) (b) `.well-known/mcp.json` が `https://jpcite.com` で 200 を返すこと |
| **submission 手順** | (1) `npx @modelcontextprotocol/inspector` でローカル動作確認 → (2) `mcp publish server.json` CLI (公式 registry) → (3) mcp.so は `https://mcp.so/server/submit` で GitHub URL 入力 → (4) mcpregistry.io も同様に web form |
| **review SLA** | 公式 = 自動 (CI verify pass = 即時掲載)、mcp.so = 24-72h human review |
| **掲載後の更新方法** | `server.json` の version bump → `mcp publish server.json` 再実行 → mcp.so は repo の git tag を pull する |
| **規約遵守** | tool description に「これは助言ではない」明記 (済)、anonymous tier 必須 (3 req/IP/日、済)、harmful category 禁止 (該当なし) |
| **失敗時の救済** | rejection 理由 typical: (a) `server.json` schema 不適合 → JSON Schema CLI で再 validate (b) tool name 重複 → `name` 接頭辞を `io.github.shigetosidumeda-cyber/` のままにする (c) tool count 過多 → categories を最大 5 に絞る |
| **即修正 top-3** | (1) `mcp publish server.json` をまだ叩いていない → 即実行 (2) mcp.so の web form 未提出 (3) GitHub repo 名 `autonomath-mcp` (legacy) を README で「user-facing brand = jpcite」と明記 (済だが registry preview にも反映確認) |

---

## 2. ChatGPT GPT Store (GPT 作成 → publish)

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **yellow** (Action 用 OpenAPI 30 paths 配信済、GPT 自体は未作成) |
| **registry URL** | `https://chat.openai.com/gpts/editor` (ChatGPT Plus/Team/Enterprise アカウントでアクセス) |
| **必要 manifest** | OpenAPI 3.0 (max 30 operations) = `https://jpcite.com/openapi.agent.gpt30.json` (既に slim 版配信済、Wave 1 Lane E) |
| **必要 asset** | (a) GPT アイコン PNG 512×512 (= `site/assets/favicon-512.png` 流用可) (b) cover 画像 (任意、og.png 流用可) |
| **必要 metadata** | name=「jpcite — 日本の制度 情報源」 / description (300字以内) / category=「Productivity / Research」 / conversation starters (4 個推奨) / prompt instructions = `site/connect/chatgpt.html` の 500字テンプレ |
| **必要 verification** | (a) ChatGPT Plus/Team/Enterprise 加入 (operator アカウント) (b) `chat.openai.com → Settings → Builder Profile` で `jpcite.com` の DNS verification (TXT record `openai-domain-verification=...`) を完了させる必要あり (c) Privacy URL = `https://jpcite.com/privacy.html` を Configure → Privacy policy URL に入力 |
| **submission 手順** | (1) ChatGPT → Explore GPTs → Create → Configure (2) Name / Description / Instructions を入力、Instructions に `site/connect/chatgpt.html` Configure テンプレ貼付 (3) Capabilities = Web Browsing OFF (jpcite が source 提供) (4) Actions → Import from URL = `https://jpcite.com/openapi.agent.gpt30.json` (5) Authentication = API Key (Auth Type: Custom, Custom Header Name: `X-API-Key`、現行 `Bearer` ではなく `X-API-Key` ヘッダが正) — ※ai-plugin.json 内の Bearer 記述と矛盾あり、ChatGPT 側は X-API-Key へ寄せる (6) Privacy policy URL に `https://jpcite.com/privacy.html` (7) Save → 公開範囲 = Public (8) GPT Store の category タグを設定 |
| **review SLA** | Public publish 時 24-72h の human review (OpenAI policy check)、Private/Link は即時 |
| **掲載後の更新方法** | `openapi.agent.gpt30.json` の path 変更時は GPT Builder で「Refresh schema」をクリック、Instructions 改訂は GPT Builder から直接編集 → Publish |
| **規約遵守** | OpenAI Usage Policies: 法律/税務 助言 禁止 (jpcite Instructions に 8 業法 fence 既に記載) / 個人情報収集 禁止 (anon 経路無し) / 子供向け提供 禁止 (該当なし) |
| **失敗時の救済** | rejection 理由 typical: (a) 「provides legal/tax advice」誤検知 → Instructions に「does NOT provide legal/tax advice; references public records only」を冒頭に追記 (b) DNS verification 失敗 → CF DNS の TXT record 反映待ち (最大 24h)、`dig TXT jpcite.com` で確認 (c) Action OpenAPI schema 不適合 → `https://jpcite.com/openapi.agent.gpt30.json` の `operationId` が unique か、`servers[0].url` が `https://api.jpcite.com` か |
| **即修正 top-3** | (1) ChatGPT Settings → Builder Profile で `jpcite.com` の domain verification 未実施 (2) ai-plugin.json の `auth.type=none` と Custom GPT が要求する `X-API-Key` の整合性確認 (3) GPT cover 画像 (1280×800 推奨) が未作成 → og.png をリサイズ |

---

## 3. OpenAI Plugin Store (legacy ai-plugin.json)

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **yellow** (manifest 配信済だが、OpenAI ChatGPT Plugins は **2024-04-09 で公式 deprecated**、後継 = GPT Actions / Custom GPT。**新規 submission は受け付けていない**) |
| **registry URL** | (deprecated) かつての URL `https://chat.openai.com/?model=plugins` は無効化 |
| **必要 manifest** | `https://jpcite.com/.well-known/ai-plugin.json` (v1 schema、既に配信済) |
| **必要 asset** | (deprecated 経路につき即時利益なし。logo_url = `https://jpcite.com/logo.svg` は 404、`/assets/logo.svg` 又は `/assets/mark.svg` に修正必要) |
| **必要 metadata** | name_for_human / name_for_model / description_for_model / api.url / auth / logo_url / contact_email / legal_info_url |
| **必要 verification** | 不要 (deprecated) |
| **submission 手順** | **不要** (新規受付終了)。**保持目的**: 「ai-plugin.json を置いている」事実は AI agent crawler (Anthropic / Perplexity / 独自 RAG bot) が discovery シグナルとして拾うので、削除せず維持 |
| **review SLA** | N/A |
| **掲載後の更新方法** | `ai-plugin.json` を更新するだけ。retrieve は crawler 任せ |
| **規約遵守** | OpenAI deprecation 後も schema v1 は無害、保持 OK |
| **失敗時の救済** | logo_url の 404 を解消 (下記参照) |
| **即修正 top-3** | (1) `logo_url` が `https://jpcite.com/logo.svg` (404) → `https://jpcite.com/assets/logo.svg` または `https://jpcite.com/assets/mark.svg` に修正 (2) `description_for_model` 内に `sk_` prefix が残存 (現行は `jc_`) → 文言再点検 (3) `is_user_authenticated: false` 確認、anon 3req/IP/日と整合 |

---

## 4. Cursor MCP store (.cursor/mcp.json + Cursor MCP marketplace)

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **green** (config 配信済 + connect page 整備済) |
| **registry URL** | (a) Cursor アプリ内 `Settings → MCP → Browse` (b) `https://cursor.directory/mcp` (community marketplace) (c) `https://docs.cursor.com/context/model-context-protocol` |
| **必要 manifest** | `https://jpcite.com/.cursor/mcp.example.json` を配信 (operator copy → `.cursor/mcp.json` に配置する snippet) |
| **必要 asset** | logo SVG + 1〜2 枚 screenshot (Cursor IDE 内で jpcite tool が呼ばれている画面) → `site/assets/mcp_preview_1.png`, `mcp_preview_2.png` 流用可 |
| **必要 metadata** | display name=`jpcite — Japanese public-program evidence MCP` / categories=[government,legal,finance,data,compliance] / brand=jpcite / publisher=Bookyou株式会社 / install command=`uvx autonomath-mcp` / repo URL |
| **必要 verification** | (a) GitHub repo owner (b) MCP server が stdio で起動できること (c) Cursor 0.42+ で `Settings → MCP → jpcite` が緑 dot 表示 |
| **submission 手順** | (1) `site/connect/cursor.html` を一次案内ページに維持 (2) cursor.directory に GitHub PR で `mcp-servers.json` に jpcite エントリ追加 (`https://github.com/pontusab/cursor.directory`) (3) Cursor 公式 marketplace は現状 community-driven、operator が cursor.directory に PR + Cursor Discord で告知 |
| **review SLA** | cursor.directory PR = maintainer review 1-7 日 |
| **掲載後の更新方法** | `mcp.example.json` 改訂 → cursor.directory PR で metadata update |
| **規約遵守** | Cursor MCP ToS: 自前 LLM call 禁止 (CLAUDE.md `No LLM API` policy 遵守、green)、stdio transport 必須 (smithery.yaml に明記、green) |
| **失敗時の救済** | rejection 理由 typical: (a) `mcp.example.json` の JSON 構文エラー → `jq` で validate (b) `uvx autonomath-mcp` 起動失敗 → PyPI 公開 + `uvx` cache clear 確認 (c) tools count 過多 (151) → Cursor 側 UI で page 化される、問題なし |
| **即修正 top-3** | (1) cursor.directory に PR 未提出 (2) `.cursor/mcp.example.json` の `JPCITE_API_KEY` placeholder を `"<your-jpcite-api-key>"` に書き換え (3) Cursor IDE 動作 screenshot (MCP 緑 dot + tools 151) を追加撮影 |

---

## 5. Claude Project marketplace (Anthropic Claude.ai Projects)

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **yellow** (Connector / Custom Integration の Public marketplace は段階的 rollout 中、operator アカウントで private 共有は可能) |
| **registry URL** | (a) `https://claude.ai/projects` (operator Project) (b) `https://claude.ai/directory` (Public marketplace、enterprise tier 中心、個人開発者 onboarding 段階的) |
| **必要 manifest** | (a) MCP Connector = `https://api.jpcite.com/mcp` (HTTP transport) + `server.json` (b) Project Instructions に jpcite 8 業法 fence + workflow 貼付 |
| **必要 asset** | logo PNG 256×256 (favicon-512 リサイズ) + 1 枚 screenshot |
| **必要 metadata** | Project name=「jpcite — 日本公的情報リサーチ」 / description / Custom Instructions / Connector URL / API key (operator が顧客に発行する jc_ 始まりキー) |
| **必要 verification** | (a) Claude.ai Pro/Team/Enterprise アカウント (b) Project への Connector 追加権限 (c) `https://api.jpcite.com/mcp` が CORS で `https://claude.ai` を許可 (CLAUDE.md `CORS allowlist` per JPINTEL_CORS_ORIGINS 環境変数) |
| **submission 手順** | (1) Claude.ai → Projects → Create Project (2) Custom Instructions に site/connect/claude-code.html を adapt して貼付 (3) Connector → Add → MCP → URL `https://api.jpcite.com/mcp` 入力 → header `X-API-Key: jc_...` (4) Project を Org 内シェア → 段階的に Public へ (Anthropic から marketplace 招待を受け取った時のみ) |
| **review SLA** | Private = 即時、Public marketplace = Anthropic Partnerships team 招待制 (operator から `info@bookyou.net` 経由で `partnerships@anthropic.com` に inbound 申請可だが個別 SLA) |
| **掲載後の更新方法** | Connector の URL 不変、`/mcp` endpoint 側で tools 追加すれば自動反映、Instructions は Project 編集画面から手動 |
| **規約遵守** | Anthropic Usage Policies: 助言 禁止 (fence 既設置)、PII 取得 禁止 (anon 経路は IP のみ)、Enterprise Customer Agreement の DPA 要求は **operator が zero-touch 方針につき marketplace public は当面 private シェア中心** |
| **失敗時の救済** | (a) `https://api.jpcite.com/mcp` への CORS 403 → `JPINTEL_CORS_ORIGINS` に `https://claude.ai` `https://*.claude.ai` 追加 (b) `X-API-Key` 認証失敗 → `jc_` prefix キーが Stripe Checkout 経由で発行されているか確認 (c) Public marketplace 招待が来ない → operator から partnerships@anthropic.com に簡潔な inbound (1 段落: Bookyou + jpcite + 155 tools + ¥3/req metered + 100% organic) |
| **即修正 top-3** | (1) operator Claude.ai Pro/Team アカウントで Project を 1 つ作って Connector を生で配線 → 動作 screenshot 撮影 (2) `JPINTEL_CORS_ORIGINS` Fly secret に `https://claude.ai` 追加 (3) `partnerships@anthropic.com` への short inbound メール起案 (本文 280字以内) |

---

## 6. Codex (Anthropic) MCP catalog / OpenAI Codex CLI

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **green** (connect page + HostedMCPTool snippet 整備済) |
| **registry URL** | (a) OpenAI Codex CLI は GitHub `openai/codex` / Agents SDK `openai/openai-agents-python` の README から `HostedMCPTool` を case study として参照 (b) Anthropic Codex (Claude Code) 経路は `claude mcp add jpcite -- uvx autonomath-mcp` が canonical |
| **必要 manifest** | (a) Anthropic 側 = `claude-code.html` 案内 + `server.json` (mcp 公式 registry) (b) OpenAI 側 = `https://api.jpcite.com/mcp` HTTP endpoint を `HostedMCPTool` で参照、`tool_config={'type':'mcp','server_url':...}` |
| **必要 asset** | logo SVG (流用可) + `codex.html` 内 30 行 Python snippet (整備済) |
| **必要 metadata** | server_label=`jpcite` / server_url=`https://api.jpcite.com/mcp` / require_approval=`never` / headers={`X-API-Key`: env var} |
| **必要 verification** | (a) `https://api.jpcite.com/mcp` が HTTP/streamable transport で 200 を返す (b) anon 3 req/IP/日 が `X-API-Key` 無しで通る (c) `pip install openai-agents` 後に動作確認 |
| **submission 手順** | (1) `openai/openai-agents-python` GitHub Discussions に jpcite を hosted MCP example として post (2) Anthropic Claude Code 側は既に `claude mcp add` が動くため追加 submission 不要 (3) Codex CLI (Anthropic) 側は `~/.config/claude-code/config.json` example として `connect/codex.html` の snippet を GitHub Gist で公開 |
| **review SLA** | GitHub Discussion = 即時掲載、Anthropic Codex Catalog 公式 = mcp 公式 registry (上記 §1) と統合 |
| **掲載後の更新方法** | endpoint URL 不変なら無更新、tools 追加は `/mcp` 経由で自動反映 |
| **規約遵守** | OpenAI Agents SDK ToS: hosted MCP 経由でも application data の OpenAI 側保管禁止 (jpcite は source_url ペアのみ返却、PII なし、green) |
| **失敗時の救済** | (a) `https://api.jpcite.com/mcp` が 503 → Fly Tokyo machine status 確認 (`flyctl status`) (b) `HostedMCPTool` 構築エラー → openai-agents v1.0+ 必須、`pip install -U openai-agents` (c) CORS 不要 (server-to-server) |
| **即修正 top-3** | (1) `openai/openai-agents-python` GitHub Discussions / Issues に `jpcite hosted MCP example` post 未実施 (2) `connect/codex.html` の `HostedMCPTool` snippet を独立 GitHub Gist 化 → URL を README に追加 (3) `https://api.jpcite.com/mcp` の HTTP transport conformance を MCP Inspector で再確認 |

---

## 7. Gemini Extensions (Google Gemini agent platform)

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **red** (Gemini Extensions 専用 manifest 未配信、Gemini はまだ MCP native 非対応で OpenAPI 経由のみ) |
| **registry URL** | (a) Google AI Studio = `https://aistudio.google.com/` → Extensions (b) Gemini Extensions Developer = `https://developers.google.com/gemini/extensions` (c) Google Workspace Marketplace との中継経路 |
| **必要 manifest** | (a) `extension.json` (Gemini 専用 schema、未配信) (b) OpenAPI 3.0 (max ~30 operations、`openapi.agent.gpt30.json` 流用可だが Gemini は `securitySchemes` の OAuth2 を強く推奨) (c) Discovery Document (Google API Discovery format、optional) |
| **必要 asset** | logo PNG 192×192 (= favicon-192.png 流用可) + cover banner 1280×720 + 30s 紹介動画 (推奨) |
| **必要 metadata** | display_name=「jpcite — 日本公的情報」 / short_description (80字) / long_description / category=「Productivity / Research」 / supported_languages=[ja, en] / supported_regions=[JP] |
| **必要 verification** | (a) Google Cloud Project 作成 + Project ID 取得 (b) OAuth 2.0 client ID 発行 (`https://console.cloud.google.com/apis/credentials`) (c) `jpcite.com` の Google Search Console verification (DNS TXT or `<meta name="google-site-verification">`) (d) Privacy policy URL = `https://jpcite.com/privacy.html` |
| **submission 手順** | (1) Google Cloud Console で project 作成 → OAuth 2.0 設定 → Extension manifest を Gemini Extension Developer console から登録 (2) `extension.json` 作成 (jpcite OpenAPI を参照する形) (3) Test mode で動作確認 (operator アカウント内) (4) Public listing 申請 (Google Trust & Safety review、最大 4-6 週間) |
| **review SLA** | Public publish = 4-6 週間 (Google Trust & Safety review)、Private/Unlisted = 即時 |
| **掲載後の更新方法** | `extension.json` 更新 → Gemini Extension Developer console から re-submit |
| **規約遵守** | Google API Services User Data Policy: ユーザーデータ取得時の同意 (jpcite は anon 3req/IP のみ、PII 取得なし、green) / Generative AI Prohibited Use Policy: 法律/医療/金融 助言 禁止 (fence 既設置、green) |
| **失敗時の救済** | (a) OAuth が UX 上重い (operator 側) → API key 経路を併設 (`X-API-Key` header) (b) review 長期化 → Gemini Trust & Safety から「PII 取得明確化」要求が来た場合は `agents.json` の `geo_eligibility: Japan-only` を引用 (c) 「Generative AI policy」誤検知 → jpcite Instructions / description に「retrieval-only, no generation, no advice」を明示 |
| **即修正 top-3** | (1) `extension.json` (Gemini schema) 未作成 → site/.well-known/ または site/integrations/gemini/ に配信 (2) Google Search Console での `jpcite.com` verification 未実施 → DNS TXT 追加 (3) Google Cloud Console で OAuth client ID 未発行 → operator が 1 度 console から実行 |

---

## 8. Perplexity Spaces / Anthropic API direct

| 項目 | 値 / 手順 |
|---|---|
| **現在の対応度** | **yellow** (Anthropic API direct = MCP HTTP endpoint で即動作、Perplexity Spaces は MCP 経路 GA 待ち) |
| **registry URL** | (a) Anthropic Claude API = `https://api.anthropic.com/v1/messages` の `mcp_servers` パラメータで `server_url=https://api.jpcite.com/mcp` を渡す経路 (Claude 4.7 以降ネイティブ) (b) Perplexity Spaces = `https://www.perplexity.ai/spaces` でカスタム source 設定 (MCP は 2026Q1 段階で limited beta、operator が waitlist 登録) |
| **必要 manifest** | (a) Anthropic = `server.json` + HTTP endpoint `https://api.jpcite.com/mcp` (b) Perplexity = `llms.txt` `llms-full.txt` `agents.json` 配信 (既に green) + Spaces 側で `https://jpcite.com/sources` のような source URL を貼付 |
| **必要 asset** | logo + 1 段落 description (= mcp.json の `description` 流用) |
| **必要 metadata** | (Anthropic) server_label=`jpcite` / server_url / auth_token=`X-API-Key` (Perplexity) Space name / description / source URLs / refresh frequency |
| **必要 verification** | (a) Anthropic = API key を operator が `https://console.anthropic.com/` で発行 (本人利用、再配布なし) (b) Perplexity Spaces = Perplexity Pro アカウント + sources URL が 200 |
| **submission 手順** | (1) Anthropic 経路は **registry 不要**: 顧客側で Messages API に `mcp_servers=[{server_url:'https://api.jpcite.com/mcp', authorization_token:'jc_...'}]` を渡せば即時利用、operator は何も submit しない (2) Perplexity Spaces は MCP GA 待ちのため、当面は `llms.txt` `llms-full.txt` を crawl してもらう経路で運用、Perplexity Discover Feed への submission は別途 `https://www.perplexity.ai/contact` から inbound |
| **review SLA** | Anthropic = N/A (顧客直叩き)、Perplexity = MCP GA 段階で改めて確認 |
| **掲載後の更新方法** | (Anthropic) 不要 (Perplexity) `llms.txt` `llms-full.txt` 改訂 → crawler が次回更新時に拾う |
| **規約遵守** | Anthropic Usage Policies (既に対応済) / Perplexity ToS: 一次資料への deeplink 必須 (jpcite は全 response に `source_url` 同梱、green) |
| **失敗時の救済** | (a) Anthropic 顧客が `mcp_servers` を知らない → `connect/claude-code.html` を Anthropic Cookbook に PR で寄稿 (b) Perplexity MCP beta 招待来ない → `llms.txt` `llms-full.txt` `llms-full.en.txt` の crawl 経路を SEO/GEO 戦略で維持 (`docs/_internal/seo_geo_strategy.md` 参照) |
| **即修正 top-3** | (1) Anthropic Cookbook (`https://github.com/anthropics/anthropic-cookbook`) に `mcp_servers` 例として jpcite 1 件 PR 起案 (2) Perplexity Spaces beta waitlist 未登録 → `https://www.perplexity.ai/contact` から 1 通 (3) `llms.txt` の冒頭 200 字を Perplexity Discover が拾いやすい形 (1 段落 plain text + URL 5 個以下) に整える |

---

## 全体サマリ (operator が次に動く)

| # | platform | 対応度 | 即 submission 可? | 完了後の効果 |
|---|---|---|---|---|
| 1 | Anthropic MCP registry | green | **YES** (`mcp publish server.json` を operator が叩く) | Claude Code / Cursor / Codex から自動発見 |
| 2 | ChatGPT GPT Store | yellow | NO (DNS verification + GPT 作成 + Public review 24-72h) | ChatGPT 全体に露出 |
| 3 | OpenAI Plugin Store | yellow | N/A (deprecated、manifest 保持のみ) | crawler シグナル維持 |
| 4 | Cursor MCP store | green | **YES** (cursor.directory に PR) | Cursor 全 user に露出 |
| 5 | Claude Project marketplace | yellow | partial (private 即時、public は招待制) | Anthropic Enterprise tier に露出 |
| 6 | Codex MCP catalog | green | **YES** (GitHub Discussions post + Gist) | Codex/Agents SDK 開発者に露出 |
| 7 | Gemini Extensions | red | NO (`extension.json` + GCP project + 4-6 週 review) | Google Gemini に露出 |
| 8 | Perplexity Spaces / Anthropic direct | yellow | Anthropic 経路は即 (顧客側のみ)、Perplexity は waitlist | Perplexity / Claude API 顧客に露出 |

**即 submission 可能 platform 数**: **3** (Anthropic MCP registry、Cursor MCP store、Codex MCP catalog)
**残り 5 platform**: ChatGPT/Claude Project は operator アカウント + 短い手続き、Gemini は別途 GCP project が必要、Plugin store は deprecated、Perplexity は waitlist

---

## 横断的 即修正 top-5 (8 platform に共通で効く)

1. **`ai-plugin.json` の `logo_url` を 404 から fix** (`https://jpcite.com/logo.svg` → `/assets/logo.svg` または `/assets/mark.svg`) — Plugin store / GPT Store / Gemini で参照される
2. **square 1024×1024 PNG logo を作成** (現状 512 まで) — Anthropic registry / Smithery で要求
3. **30-90秒 紹介動画 mp4 を作成** — GPT Store / Gemini Extensions / Cursor で訴求差
4. **`extension.json` (Gemini schema) を site/.well-known/ に配信** — Gemini への入口開通
5. **Anthropic Cookbook に `mcp_servers` 利用例 PR 起案** — Anthropic API 直叩き顧客への露出
