# jpcite プレスキット / Press Kit

更新日 / Updated: 2026-04-25
Launch: 2026-05-06
Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
Press contact: [info@bookyou.net](mailto:info@bookyou.net)

このページは記者・媒体・パートナー向けのプレス資料です。
引用・転載は出典明記のうえ自由に行えます。
追加資料 (高解像度ロゴ・スクリーンショット・追加コメント) のリクエストは
上記メールへ件名「jpcite press kit」でご連絡ください。

---

## 目次

1. [Boilerplate (300字)](#boilerplate-300字)
2. [Boilerplate (1,000字)](#boilerplate-1000字)
3. [Fact sheet](#fact-sheet)
4. [参考コメント × 5](#参考コメント--5)
5. [Use case × 5 audience](#use-case--5-audience)
6. [Logo / asset](#logo--asset)
7. [Press contact](#press-contact)
8. [Downloadable](#downloadable)

---

## Boilerplate (300字)

jpcite は、日本の公的制度データ — 補助金・融資・税制優遇・認定制度・法令・行政処分・税務ルールセット・適格事業者 — を AI エージェントから 1 API で参照できる REST + MCP サーバーです。経産省・農水省・中小企業庁・日本政策金融公庫などの公開資料から 11,601 検索可制度 + 2,286 採択事例 + 108 融資 + 1,185 行政処分 + e-Gov 法令メタデータ・条文参照 (record により coverage は異なります) + 13,801 適格事業者を正規化し、併用チェックルール・全文検索インデックス・出典 URL リネージ (snapshot ベース、リアルタイム同期ではありません) を提供します。MCP / OpenAPI 対応クライアントから利用できます。料金は ¥3/billable unit 税別 (税込 ¥3.30)、匿名 3 req/日 per IP 無料。運営は Bookyou株式会社 (代表 梅田茂利)。Launch: 2026-05-06。

---

## Boilerplate (1,000字)

jpcite は、日本の公的制度に関する主要な公開データ — 補助金・融資・税制優遇・認定制度・法令・行政処分・税務ルールセット・適格事業者・採択事例 — を、AI エージェントが 1 つの API で横断検索できる REST + MCP サーバーです。経済産業省・農林水産省・中小企業庁・日本政策金融公庫・総務省・国税庁・e-Gov 法令データ提供システムなど、原典に近い公開資料を優先して機械可読データを構築しています。

**収録データ (2026-05-07 時点)**:

- 制度 (補助金・融資・税制・認定): 14,472 件
- 採択事例 (採択事例): 2,286 件
- 融資 (担保・個人保証人・第三者保証人 三軸分解): 108 件
- 行政処分: 1,185 件
- 法令 (e-Gov, CC-BY): 法令メタデータ・条文参照 (record により coverage は異なります)
- 税務 ruleset (インボイス + 電帳法): 50 件
- 適格事業者 (国税庁 PDL v1.0): 13,801 件 (delta-only ライブミラー、月次フルバルク準備中)
- entity-fact DB: 503,930 entities + 6.12M facts + 177,381 relations + 335,605 aliases
- 法令メタデータ: 9,484 件 / 行政処分 cases: 1,185 件
- 排他ルール: 181 本 (手動確認 + 資料抽出)
- 出典 URL (`source_url` + `fetched_at`): 多くの公開行に付与

**特徴**:

- **MCP 対応**: 標準構成 155 ツール、protocol 2025-06-18 準拠
- **AI agent first**: Claude Desktop / ChatGPT / Cursor / Gemini が直接接続可能
- **横断検索**: `trace_program_to_law` (制度→根拠法令)、`find_cases_by_law` (法令→判例)、`combined_compliance_check` (制度+処分+適格事業者を一括チェック)
- **日本語特化**: 全文検索インデックス (3-gram 分割) による複合語検索、Hepburn slug 自動生成
- **税制対応**: Stripe Tax + 国内インボイス制度 (適格請求書発行事業者) 対応

**Jグランツとの違い**: Jグランツが申請ポータルであるのに対し、jpcite は「発見 + 併用可否判定 + 実績確認 + 根拠法トレース + 判例・入札・適格事業者横断 + entity-fact lookup」の層を担います。データ収集と申請前確認を AI エージェントで支援する仕組みです。

**料金**: ¥3/billable unit 税別 (税込 ¥3.30) の従量制。階層プラン・席課金・年間最低額なし。匿名 3 req/日 per IP は無料 (JST 翌日 00:00 リセット)。

**運営**: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708、代表 梅田茂利)、Fly.io 東京 (nrt) リージョンでホスティング。

Launch: 2026-05-06。Press contact: info@bookyou.net

---

## Fact sheet

| 項目 | 値 |
|---|---|
| 製品名 | jpcite |
| ドメイン | https://jpcite.com |
| 運営法人名 | Bookyou株式会社 |
| 法人番号 | T8010001213708 |
| 設立日 | 2024-XX-XX (登記) |
| 法人登録 (適格請求書) | 2025-05-12 (令和7年) |
| 所在地 | 東京都文京区小日向2-22-1 |
| 代表者 | 梅田茂利 (Shigetoshi Umeda) |
| 資本金 | 非公開 |
| 従業員数 | 1 名 |
| Launch 日 | 2026-05-06 |
| 価格 | ¥3/billable unit 税別 (税込 ¥3.30) |
| 無料枠 | 匿名 3 req/日 per IP (JST 翌日 00:00 リセット) |
| 制度件数 | 14,472 |
| 採択事例件数 | 2,286 |
| 融資件数 | 108 (三軸分解: 担保 / 個人保証人 / 第三者保証人) |
| 行政処分件数 | 1,185 |
| 法令 | 法令メタデータ・条文参照 (e-Gov, CC-BY; record により coverage は異なります) |
| 税務 ruleset 件数 | 50 (インボイス + 電帳法) |
| 適格事業者件数 | 13,801 (PDL v1.0 ライブミラー、delta-only) |
| entity-fact 件数 | 503,930 entities + 6.12M facts + 177,381 relations + 335,605 aliases |
| 法令メタデータ / 行政処分 cases | 9,484 / 1,185 |
| 排他ルール件数 | 181 |
| MCP ツール数 | 標準構成 151 |
| MCP プロトコル | 2025-06-18 |
| ホスティング | Fly.io Tokyo (nrt) |
| 静的サイト | Cloudflare Pages |
| 課金 | Stripe Metered + Stripe Tax (JP インボイス対応) |
| 主な導線 | 検索、ドキュメント、GitHub、MCP レジストリ |
| 営業活動 | セルフサービス中心 |
| ライセンス | API: 商用利用可 (規約に従う) / コード: 一部 OSS |
| 直近メジャー版 | v0.4.0 |

---

## 参考コメント × 5

> 注: quote 1 のみが Bookyou株式会社 代表 梅田茂利の発言で、引用可能です。quote 2-5 は想定ユースケースに基づく参考コメントであり、実顧客の推薦・証言ではありません。記事掲載時は「想定発言」「参考コメント」等の明示をお願いします。

### 1. Operator (Bookyou株式会社 代表、梅田茂利)

> 「日本の制度データは政府サイトに散らばっていて、一次資料を 1 件 1 件辿るのは現実的ではありませんでした。AI エージェントが 1 query で横断アクセスできれば、補助金・融資・税制の確認時間を短縮しやすくなります。jpcite はそのための最小単位です。¥3/billable unit の従量制にしたのは、階層プランや席課金の意思決定を挟まず、必要な時だけ使える形にしたかったからです。」

### 2. Persona — Dev (個人開発者 / SaaS スタートアップ) (想定発言 / sample)

> 「補助金 API を使いたかったが、商用集約サイトは規約上 LLM 投入が gray エリアになりがちでした。jpcite は MCP に直接刺さり、出典 URL と更新日時 (snapshot) が付くので、Claude / ChatGPT で reasoning 材料として扱いやすい。匿名 3 req/日 per IP の枠は試作レベルの確認に十分でした。」
>
> ※ 想定発言。

### 3. Persona — 税理士 / 認定支援機関 (想定発言 / sample)

> 「クライアントから『使える補助金は?』と聞かれた時、要綱を都度確認するコストが大きい。jpcite で発見 → 排他ルール確認 → 採択事例まで一気通貫で見えるのは、士業の意思決定 layer に直接効きます。法令への参照 (snapshot ベース) も付くので、出典確認の手間が減ります。」
>
> ※ 上記は想定ユースケースに基づく sample であり、税務・法的助言ではありません。実際の制度判断は士業の方ご自身による一次資料確認が前提です。

### 4. Persona — 中小企業 経営者 / 経理 (想定発言 / sample)

> 「適格事業者 (インボイス) の参照、現行制度 snapshot の確認、補助金の候補リストアップを、別々のサイトを行き来せずに 1 つの AI チャットで初動できるのが助かる。Claude Desktop に繋ぐだけで使える設定は社内で共有できる範囲でした。最終判断は一次資料と顧問 (税理士・社労士等) の確認が前提です。」
>
> ※ 想定発言。jpcite は snapshot ベースのデータ提供であり、リアルタイムの法令改正追跡や法的助言は提供しません。

### 5. Persona — VC / アナリスト (想定発言 / sample)

> 「採択事例 2,286 件 + 行政処分 1,185 件 + 適格事業者 13,801 件 + entity-fact 503,930 件を横断 query できるのは DD の初動に組み込みやすい。Tier 分類と出典 URL + 更新日時 (snapshot) が付いているので、AI agent に投げても fact の trail が残る。」
>
> ※ 想定発言。投資判断・DD は別途一次資料確認が前提です。

---

## Use case × 5 audience

> 注: 本セクションのコメントは想定ユースケースに基づく参考文であり、実顧客の発言ではありません。記事掲載時はその旨明示をお願いします。

### Audience 1: AI agent 開発者 (Claude / ChatGPT / Cursor / Gemini)

**Use case**: MCP stdio で `search_programs` → `prescreen` → `subsidy_combo_finder` を chain。Claude Desktop の設定 JSON に 1 行追加するだけで AI agent が日本の制度を即時に reasoning できる。

**Quote (想定発言)**: 「SDK を書かずに 155 ツール使えるのは、Manifest 1 行で済む MCP の本来の使い方だと思います。」(persona: AI app dev / sample)

### Audience 2: 税理士 / 認定支援機関 / 行政書士

**Use case**: クライアント面談中に MCP / Web で候補制度を確認し、LINE notifications でフォローアップや web handoff を受け取る。顧客の前ではブラウザで出典と snapshot 時点の注意点まで確認できる。

**Quote (想定発言)**: 「面談中に検索 → 排他ルール確認 → snapshot 時点の申請期限まで初動できるのは、士業の参照工程を短縮します (最終判断は一次資料確認が前提)。」(persona: 税理士 / sample)

### Audience 3: SMB (中小企業) 経営者 / 経理担当

**Use case**: ChatGPT Custom GPT の Actions や Claude Desktop / Cursor の MCP から jpcite を呼ぶと、「うちの会社で使える補助金は?」に一次資料 URL 付きの制度のみを Tier 順に提示できます。集約サイト由来の hallucination を抑制。

**Quote (想定発言)**: 「『一次資料 URL + 更新日時』が前提なのが大きい。集約サイトでは何が信用できるか分からなかった。」(persona: 経理担当 / sample)

### Audience 4: VC / アナリスト / 企業 DD

**Use case**: 投資先の DD で `combined_compliance_check` を実行 → 行政処分 + 適格事業者 + 採択事例を一括取得。entity-fact DB で関連企業 graph まで引ける。

**Quote (想定発言)**: 「Tier S/A だけ抽出して DD の初動に組み込みたい。fact-trail が AI 出力で消えないのが価値です (最終判断は一次資料確認が前提)。」(persona: VC アナリスト / sample)

### Audience 5: GovTech / 自治体 / 商工会議所

**Use case**: 自治体 web に embed widget を追加し、「使える補助金 Q&A」を提供。料金は ¥3/billable unit (税別) の従量制。住民問い合わせの一次受けを軽減。

**Quote (想定発言)**: 「自治体側のシステムに手を入れずに、住民問い合わせの初動レベルの検索が組み込めるのは助かる。」(persona: 自治体担当 / sample)

---

## Logo / asset

> 注: ロゴ利用の詳細は、公開資料または press contact へお問い合わせください。

| アセット | URL | 形式 |
|---|---|---|
| ロゴ pack (zip) | https://jpcite.com/press/logos.zip | SVG / PNG (1x, 2x, 3x) |
| Brand mark | https://jpcite.com/press/assets/mark.svg | SVG |
| Wordmark | https://jpcite.com/press/assets/wordmark.svg | SVG |
| Favicon | https://jpcite.com/favicon.ico | ICO |
| OGP 画像 | https://jpcite.com/assets/og.png | PNG 1200x630 |
| スクリーンショット pack | https://jpcite.com/press/screenshots.md | PNG |

**ロゴ利用規約**:

- 配色変更不可、最小サイズ 24px
- 商用記事内の引用・スクリーンショット内表示は事前許諾不要
- ロゴ単独使用 (アイキャッチ等) は info@bookyou.net へ件名「Logo use」で連絡

---

## Press contact

press / earned media / partnership 一次窓口:

**Email**: [info@bookyou.net](mailto:info@bookyou.net)

- 件名 prefix: `[press]` または `[partnership]`
- 受付時間: JST 営業日中、通常 2 営業日以内を目安に返信
- お問い合わせはメールでお願いします

法人:

- 商号: Bookyou株式会社
- 適格請求書発行事業者番号: T8010001213708
- 所在地: 東京都文京区小日向2-22-1
- 代表者: 梅田茂利

---

## Downloadable

> 公開中:

| Bundle | URL |
|---|---|
| Press kit ZIP (この資料 + ロゴ + screenshots) | https://jpcite.com/press/jpcite-press-kit.zip |
| Logos pack (SVG/PNG) | https://jpcite.com/press/logos.zip |
| OGP 画像 pack | https://jpcite.com/press/og-pack.zip |
| Fact sheet PDF | https://jpcite.com/press/fact-sheet.pdf |

公開までは本ページ + `https://jpcite.com/press/about.md` + `https://jpcite.com/press/founders.md` + `https://jpcite.com/press/screenshots.md` を参照資料としてご利用ください。

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
