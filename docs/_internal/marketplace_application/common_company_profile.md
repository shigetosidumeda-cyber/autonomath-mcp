# Common Company Profile (freee Apps + MoneyForward Marketplace 共通)

最終更新: 2026-05-05
作成者: jpcite operator (Claude セッション、内部下書き)
ステータス: 申請書下書き — ユーザー署名・提出待ち

両マーケットプレイス申請書で共通利用される事業者情報。値は本ファイルを single source とし、各申請書はここを参照する。

---

## 1. 事業者基本情報

| 項目 | 値 |
| --- | --- |
| 法人名 (商号) | Bookyou株式会社 |
| 法人名 (英文表記) | Bookyou, Inc. |
| 法人番号 | 8010001213708 |
| 適格請求書発行事業者 (インボイス) 登録番号 | T8010001213708 |
| インボイス登録日 | 令和7年 (2025年) 5月12日 |
| 代表者役職 | 代表取締役 |
| 代表者氏名 | 梅田 茂利 (Umeda Shigetoshi) |
| 設立 | 2025年 |
| 資本金 | N/A (申請フォームで必須の場合は別途記入) |
| 本店所在地 (郵便番号) | 〒112-0006 |
| 本店所在地 (住所) | 東京都文京区小日向2-22-1 |
| 業種 | SaaS / 公的データ API インフラ |
| 事業内容 | 日本の公的制度データ (補助金・税制・法令・判例・入札・適格請求書) を REST API + MCP (Model Context Protocol) サーバーで配信。AI agent / 業務システム / 会計事務所向け B2B API。 |

## 2. 連絡先

| 項目 | 値 |
| --- | --- |
| 代表メール | info@bookyou.net |
| 申請担当者 | 梅田 茂利 |
| 申請担当者メール | info@bookyou.net |
| 申請担当者電話 | N/A (公開していないため、非公開フィールド指定があれば別途記入) |
| 技術問い合わせ窓口 | info@bookyou.net |
| サポート窓口 (公開) | https://jpcite.com/support |
| 公開サイト URL | https://jpcite.com |
| 法人情報ページ (about) | https://jpcite.com/about.html |
| 特定商取引法表示 | https://jpcite.com/tokushoho.html |
| プライバシーポリシー | https://jpcite.com/privacy.html |
| 利用規約 (ToS) | https://jpcite.com/tos.html |
| データ利用規約 / ライセンス | https://jpcite.com/data-licensing.html |
| ステータスページ | https://jpcite.com/status.html (公開時) |

## 3. プロダクト概要 (申請書冒頭の「プロダクト紹介」フィールド共通文)

> jpcite は、日本の公的制度データ (補助金・税制・法令・判例・入札・適格請求書) を一次資料リンクと出典明示付きで REST API + MCP サーバーから配信する B2B API インフラです。AI agent や業務システムから「制度マッチング」「税制根拠引用」「適格請求書事業者検証」を 1 リクエスト単位で実行できます。料金は完全従量で ¥3 / billable unit (税別、税込 ¥3.30)、匿名 3 req/日 per IP は無料、月額固定・最低利用期間・解約違約金なし。Bookyou株式会社 (適格請求書発行事業者 T8010001213708) が運営。

(120 字短縮版)

> 日本の補助金・税制・法令・適格請求書を REST API + MCP で配信する B2B API。¥3/billable unit 完全従量、月額固定なし。Bookyou株式会社運営、適格請求書発行事業者番号 T8010001213708。

## 4. 課金モデル (両マーケットプレイス共通の説明)

- 課金主体: jpcite (Bookyou株式会社) が顧客から直接受領
- 決済: Stripe (クレジットカード)、Stripe Tax で消費税自動計算
- 課金単位: ¥3 / billable unit (税別、税込 ¥3.30)。通常検索・詳細取得は 1 unit、batch / export は事前提示の式で算出
- 無料枠: 匿名 3 req/日 per IP (JST 00:00 reset、登録不要)
- 階層プラン: なし
- 最低利用期間: なし
- 解約違約金: なし
- マーケットプレイス経由のレベニューシェア: 想定なし (顧客は jpcite に直接決済)

## 5. データ取扱方針 (両マーケットプレイス共通)

- 個人情報の取扱: jpcite は公的制度データ (オープンデータ) のみを配信。顧客企業の個人情報・取引データは原則保持しない
- 認証情報: API key (jpcite 側で発行) または OAuth (パートナー連携時)。顧客のクラウド会計データへのアクセスは read-only に限定
- データ保管: Cloudflare (CDN) + Fly.io (origin)。リージョン Tokyo (NRT) 主、Singapore (SIN) 副
- ログ保持: アクセスログ 90 日、エラーログ 90 日。個人情報は含まない
- 第三者提供: なし (再販・転売・広告利用禁止)
- 削除請求: info@bookyou.net 受付、30 日以内に対応
- 詳細: https://jpcite.com/privacy.html

## 6. 技術仕様 (両マーケットプレイス共通)

| 項目 | 値 |
| --- | --- |
| API 形式 | REST (HTTPS, JSON) + MCP (Model Context Protocol, stdio + SSE) |
| 認証方式 | Bearer API key (HTTPS only)、OAuth 2.0 (パートナー連携時) |
| Base URL | https://api.jpcite.com (REST), https://mcp.jpcite.com (MCP SSE) |
| ルート数 | 240+ (v0.4 時点) |
| MCP tool 数 | 120+ (v0.4 時点) |
| OpenAPI / Swagger | https://api.jpcite.com/openapi.json |
| MCP マニフェスト | https://mcp.jpcite.com/manifest.json |
| SLA (目標) | 99.5% / 月、応答 P95 < 500ms |
| Rate limit | 匿名 3 req/日、API key 60 req/分 (デフォルト、商談で調整可) |
| データ更新頻度 | 制度: 週次、適格請求書: 日次 (国税庁 bulk)、判例: 週次 |
| インシデント連絡 | info@bookyou.net + status.jpcite.com 公開 |

## 7. 申請に同梱する添付ファイル (共通)

| ファイル | 用途 | パス (本リポジトリ) |
| --- | --- | --- |
| ロゴ 512x512 PNG | アプリアイコン | `/Users/shigetoumeda/jpcite/docs/assets/images/logo-512.png` |
| ロゴ SVG | ベクター版 | `/Users/shigetoumeda/jpcite/site/assets/logo-v2.svg` |
| サービス概要 1 ページ | 申請補足資料 | (本ドキュメントの §3 を出力) |
| 法人登記事項証明書 (写) | 提出指定時のみ | N/A (法務局オンライン取得、申請時に取得) |
| 適格請求書登録通知書 (写) | 提出指定時のみ | N/A (国税庁通知書 PDF、申請時に添付) |

## 8. 署名・提出者 (両申請書共通)

- 提出者: 梅田 茂利 (代表取締役)
- 署名方法: 各マーケットプレイス指定の電子署名フローに従う
- 申請日: ユーザー提出時の日付を記入

---

## 改訂履歴

- 2026-05-05: 初版作成 (Claude セッション)
