# AutonoMath プレスキット / Press Kit

更新日 / Updated: 2026-04-25
Launch: 2026-05-06
Operator: Bookyou株式会社 (法人番号 T8010001213708)
Press contact: [info@bookyou.net](mailto:info@bookyou.net)

このページは記者・媒体・パートナー向けの自由利用 (organic earned coverage)
プレス資料です。引用・転載は出典明記のうえ自由に行えます。
追加資料 (高解像度ロゴ・スクリーンショット pack・追加 quote) のリクエストは
上記メールへ件名「AutonoMath press kit」でご連絡ください。

---

## 目次

1. [Boilerplate (300字)](#boilerplate-300字)
2. [Boilerplate (1,000字)](#boilerplate-1000字)
3. [Fact sheet](#fact-sheet)
4. [自作 quote × 5 (operator + persona)](#自作-quote--5-operator--persona)
5. [Use case × 5 audience](#use-case--5-audience)
6. [Logo / asset](#logo--asset)
7. [Press contact](#press-contact)
8. [Downloadable](#downloadable)

---

## Boilerplate (300字)

AutonoMath は、日本の公的制度データ — 補助金・融資・税制優遇・認定制度・法令・行政処分・税務ruleset・適格事業者 — を AI エージェントから 1 API で呼び出せる REST + MCP サーバーです。経産省・農水省・中小企業庁・日本政策金融公庫など一次情報源から 10,790 検索可制度 (tier S/A/B/C; 登録総数 13,578) + 2,286 採択事例 + 108 融資 + 1,185 行政処分 + 9,484 法令 + 13,801 適格事業者を正規化し、Tier 分類・181 排他ルール・FTS5 trigram 検索・出典 URL リネージを提供します。Claude Desktop / ChatGPT / Cursor / Gemini が stdio で直接呼び出せ、SDK 不要。料金は完全従量 ¥3/req 税別、匿名 50 req/月 per IP 無料。運営は Bookyou株式会社 (代表 梅田茂利)。Launch: 2026-05-06。

---

## Boilerplate (1,000字)

AutonoMath は、日本の公的制度に関するあらゆるデータ — 補助金・融資・税制優遇・認定制度・法令・行政処分・税務ruleset・適格事業者・採択事例 — を、AI エージェントが 1 つの API で横断検索できる REST + MCP サーバーです。経済産業省・農林水産省・中小企業庁・日本政策金融公庫・総務省・国税庁・e-Gov 法令データ提供システムなど、一次情報源 (primary source) のみから機械可読データを構築しています。

**収録データ (2026-04-25 時点)**:

- 制度 (補助金・融資・税制・認定): 13,578 件
- 採択事例 (採択事例): 2,286 件
- 融資 (担保・個人保証人・第三者保証人 三軸分解): 108 件
- 行政処分: 1,185 件
- 法令 (e-Gov, CC-BY): 9,484 件 (継続ロード中)
- 税務 ruleset (インボイス + 電帳法): 35 件
- 適格事業者 (国税庁 PDL v1.0): 13,801 件 (delta-only ライブミラー、月次フルバルク準備中)
- entity-fact DB: 503,930 entities + 6.12M facts + 23,805 relations + 335,605 aliases
- am_law_article: 28,048 件 / am_enforcement_detail: 22,258 件
- 排他ルール: 181 本 (35 hand-seeded + 146 一次資料 auto-extracted)
- 出典 URL (`source_url` + `fetched_at`): 99% 以上の行に付与

**特徴**:

- **MCP ネイティブ**: 72 ツール (39 jpintel + 33 autonomath at default gates)、protocol 2025-06-18 準拠、stdio transport、SDK 不要
- **AI agent first**: Claude Desktop / ChatGPT / Cursor / Gemini が直接接続可能
- **横断検索 glue**: `trace_program_to_law` (制度→根拠法令)、`find_cases_by_law` (法令→判例)、`combined_compliance_check` (制度+処分+適格事業者を一括チェック)
- **日本語特化**: FTS5 trigram tokenizer による複合語検索、Hepburn slug 自動生成
- **税制対応**: Stripe Tax + 国内インボイス制度 (適格請求書発行事業者) 対応

**Jグランツとの違い**: Jグランツが申請ポータルであるのに対し、AutonoMath は「発見 + 併用可否判定 + 実績確認 + 根拠法トレース + 判例・入札・適格事業者横断 + entity-fact lookup」の層を担います。データ収集と申請の橋渡しを AI エージェントに任せる新しい工法です。

**料金**: ¥3/req 税別 (税込 ¥3.30) の完全従量制。tier SKU・seat 課金・年間最低額なし。匿名 50 req/月 per IP は無料 (JST 月初リセット)。

**運営**: Bookyou株式会社 (法人番号 T8010001213708、代表 梅田茂利)、Fly.io 東京 (nrt) リージョンでホスティング。Solo + zero-touch 運営、100% organic acquisition。

Launch: 2026-05-06。Press contact: info@bookyou.net

---

## Fact sheet

| 項目 | 値 |
|---|---|
| 製品名 | AutonoMath |
| PyPI パッケージ | `autonomath-mcp` |
| ドメイン | https://autonomath.ai |
| 運営法人名 | Bookyou株式会社 |
| 法人番号 | T8010001213708 |
| 設立日 | 2024-XX-XX (登記) |
| 法人登録 (適格請求書) | 2025-05-12 (令和7年) |
| 所在地 | 東京都文京区小日向2-22-1 |
| 代表者 | 梅田茂利 (Shigetoshi Umeda) |
| 資本金 | 非公開 (solo bootstrapped) |
| 従業員数 | 1 名 (代表のみ、solo + zero-touch ops) |
| Launch 日 | 2026-05-06 |
| 価格 | ¥3/req 税別 (税込 ¥3.30) 完全従量 |
| 無料枠 | 匿名 50 req/月 per IP (JST 月初リセット) |
| 制度件数 | 13,578 |
| 採択事例件数 | 2,286 |
| 融資件数 | 108 (三軸分解: 担保 / 個人保証人 / 第三者保証人) |
| 行政処分件数 | 1,185 |
| 法令件数 | 9,484 (e-Gov, CC-BY、継続ロード中) |
| 税務 ruleset 件数 | 35 (インボイス + 電帳法) |
| 適格事業者件数 | 13,801 (PDL v1.0 ライブミラー、delta-only) |
| entity-fact 件数 | 503,930 entities + 6.12M facts + 23,805 relations + 335,605 aliases |
| am_law_article / am_enforcement_detail | 28,048 / 22,258 |
| 排他ルール件数 | 181 (35 hand-seeded + 146 auto-extracted) |
| MCP ツール数 | 66 (38 jpintel + 28 autonomath: 17 V1 + 4 V4 universal + 7 Phase A absorption) |
| MCP プロトコル | 2025-06-18 |
| ホスティング | Fly.io Tokyo (nrt) |
| 静的サイト | Cloudflare Pages |
| 課金 | Stripe Metered + Stripe Tax (JP インボイス対応) |
| 取得チャネル | 100% organic (SEO / GEO / GitHub stars / MCP registry) |
| 営業活動 | なし (zero-touch、self-service only) |
| ライセンス | API: 商用利用可 (規約に従う) / コード: 一部 OSS |
| 直近メジャー版 | v0.3.0 (autonomath.db unified primary, V4 + Phase A absorption) |

---

## 自作 quote × 5 (operator + persona)

> 注: 以下の 5 quote は launch 時点の社内 quote (operator) + 想定 persona に基づく自作で、実顧客発言ではありません。実顧客 quote は launch 後の case study 収集 (T+3d 以降) で正式採取します。

### 1. Operator (Bookyou株式会社 代表、梅田茂利)

> 「日本の制度データは政府サイトに散らばっていて、一次資料を 1 件 1 件辿るのは現実的ではありませんでした。AI エージェントが 1 query で横断アクセスできれば、補助金・融資・税制の判断時間を大幅に短縮できます。AutonoMath はそのための最小単位です。完全従量 ¥3/req にしたのは、tier や seat の意思決定が AI エージェントの workflow を阻害するから。zero-touch で solo 運営できる範囲だけ作りました。」

### 2. Persona — Dev (個人開発者 / SaaS スタートアップ)

> 「補助金 API を使いたかったが、商用 aggregator は規約上 LLM 投入が grayエリアでした。AutonoMath は MCP に直接刺さって、出典 URL も付くので、Claude / ChatGPT で安心して reasoning 材料に使えます。¥3/req は試作レベルなら無料枠で十分でした。」

### 3. Persona — 税理士 / 認定支援機関

> 「クライアントから『使える補助金は?』と聞かれた時、要綱を都度確認するコストが大きい。AutonoMath で発見 → 排他ルール確認 → 採択事例まで一気通貫で見えるのは、士業の意思決定 layer に直接効きます。法令 trace まで対応するのは他にない。」

### 4. Persona — 中小企業 経営者 / 経理

> 「適格事業者 (インボイス) の確認、法令改正の追跡、補助金の申請可否を、別々のサイトを行き来せずに 1 つの AI チャットで聞けるのが助かる。Claude Desktop に繋ぐだけで使える設定は社内で共有できる範囲でした。」

### 5. Persona — VC / アナリスト

> 「採択事例 2,286 件 + 行政処分 1,185 件 + 適格事業者 13,801 件 + entity-fact 503,930 件を横断 query できるのは DD 工程に直接効きます。Tier 分類と出典 URL が付いているので、AI agent に投げても fact の trail が残る。」

---

## Use case × 5 audience

### Audience 1: AI agent 開発者 (Claude / ChatGPT / Cursor / Gemini)

**Use case**: MCP stdio で `search_programs` → `prescreen` → `subsidy_combo_finder` を chain。Claude Desktop の設定 JSON に 1 行追加するだけで AI agent が日本の制度を即時に reasoning できる。

**Quote**: 「SDK を書かずに 72 ツール使えるのは、Manifest 1 行で済む MCP の本来の使い方だと思います。」(persona: AI app dev)

### Audience 2: 税理士 / 認定支援機関 / 行政書士

**Use case**: クライアント面談中に AutonoMath LINE bot に「製造業 / 従業員 30 / 設備投資 / 関東」と打って候補制度をリストアップ。LINE で完結するので顧客の前で開ける。

**Quote**: 「面談中に検索 → 排他ルール確認 → 申請期限まで答えられるのは、士業の信頼度を底上げします。」(persona: 税理士)

### Audience 3: SMB (中小企業) 経営者 / 経理担当

**Use case**: ChatGPT に「うちの会社で使える補助金は?」と聞くと、AutonoMath MCP 経由で実在制度のみ (一次資料あり) を Tier 順に提示。誤答や architectured hallucination を avoidance。

**Quote**: 「『一次資料あり』が前提なのが大きい。aggregator は何が信用できるか分からなかった。」(persona: 経理担当)

### Audience 4: VC / アナリスト / 企業 DD

**Use case**: 投資先の DD で `combined_compliance_check` を実行 → 行政処分 + 適格事業者 + 採択事例を一括取得。entity-fact DB で関連企業 graph まで引ける。

**Quote**: 「Tier S/A だけ抽出して投資判断に組み込みたい。fact-trail が AI 出力で消えないのが価値です。」(persona: VC アナリスト)

### Audience 5: GovTech / 自治体 / 商工会議所

**Use case**: 自治体 web に embed widget を 1 行追加で「使える補助金 Q&A」を提供。¥10,000/月 で 10,000 req 含み、住民問い合わせを軽減。

**Quote**: 「自治体側のシステムに手を入れずに、住民が使えるレベルの検索が即日入るのは助かる。」(persona: 自治体担当)

---

## Logo / asset

> 注: ロゴは launch 後 (法務確認後) に正式版を公開予定。launch 前の draft は内部レビュー中。

| アセット | URL (placeholder) | 形式 |
|---|---|---|
| ロゴ pack (zip) | https://autonomath.ai/press/logos.zip | SVG / PNG (1x, 2x, 3x) |
| Brand mark | https://autonomath.ai/press/assets/mark.svg | SVG |
| Wordmark | https://autonomath.ai/press/assets/wordmark.svg | SVG |
| Favicon | https://autonomath.ai/favicon.ico | ICO |
| OGP 画像 | https://autonomath.ai/assets/og.png | PNG 1200x630 |
| スクリーンショット pack | https://autonomath.ai/press/screenshots.md | PNG |

**ロゴ利用規約 (launch 後正式版で確定)**:

- 配色変更不可、最小サイズ 24px
- 商用記事内の引用・スクリーンショット内表示は事前許諾不要
- ロゴ単独使用 (アイキャッチ等) は info@bookyou.net へ件名「Logo use」で連絡

---

## Press contact

press / earned media / partnership 一次窓口:

**Email**: [info@bookyou.net](mailto:info@bookyou.net)

- 件名 prefix: `[press]` または `[partnership]`
- 受付時間: JST 営業日中、SLA 24h 以内 (organic 受け身運営のため solo)
- 電話・対面・営業 cold call は対応していません (zero-touch ops)

法人:

- 商号: Bookyou株式会社
- 法人番号: T8010001213708
- 所在地: 東京都文京区小日向2-22-1
- 代表者: 梅田茂利

---

## Downloadable

> launch 後 (2026-05-06) に公開:

| Bundle | URL (placeholder) |
|---|---|
| Press kit ZIP (この資料 + ロゴ + screenshots) | https://autonomath.ai/press/autonomath-press-kit.zip |
| Logos pack (SVG/PNG) | https://autonomath.ai/press/logos.zip |
| OGP 画像 pack | https://autonomath.ai/press/og-pack.zip |
| Fact sheet PDF | https://autonomath.ai/press/fact-sheet.pdf |

launch 前は本ページ + `https://autonomath.ai/press/about.md` + `https://autonomath.ai/press/founders.md` + `https://autonomath.ai/press/screenshots.md` を一次資料としてご利用ください。

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
