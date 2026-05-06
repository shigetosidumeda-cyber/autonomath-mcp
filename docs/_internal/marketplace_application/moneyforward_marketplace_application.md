# MoneyForward Marketplace パートナー申請書 下書き (jpcite)

最終更新: 2026-05-05
作成者: jpcite operator (Claude セッション、内部下書き)
ステータス: 申請書下書き — ユーザー署名・提出待ち
申請 URL: https://biz.moneyforward.com/marketplace/partner-application
共通プロファイル: [common_company_profile.md](./common_company_profile.md)

注: フィールド名は MoneyForward Marketplace 「パートナー申請」フォームの実フィールドに合わせている。最新フォームと一致しないフィールドはユーザー側で読み替えて転記する。

---

## A. パートナー (事業者) 基本情報

(共通プロファイル §1, §2 を転記)

| フィールド | 入力値 |
| --- | --- |
| 会社名 | Bookyou株式会社 |
| 会社名 (英文) | Bookyou, Inc. |
| 会社名 (フリガナ) | ブックユーカブシキガイシャ |
| 法人番号 | 8010001213708 |
| 適格請求書発行事業者番号 | T8010001213708 (令和7年5月12日登録) |
| 代表者氏名 | 梅田 茂利 |
| 代表者役職 | 代表取締役 |
| 設立年 | 2025年 |
| 資本金 | N/A (フォーム必須なら申請時に追記) |
| 従業員数 | 1名 (代表のみ、AI agent 運用) |
| 本社所在地 (郵便番号) | 〒112-0006 |
| 本社所在地 (住所) | 東京都文京区小日向2-22-1 |
| Web サイト | https://jpcite.com |
| 業種 | SaaS / 公的データ API インフラ |
| 主要事業 | 日本の公的制度データ (補助金・税制・法令・判例・入札・適格請求書) を REST + MCP で配信する B2B API インフラの企画・開発・運営 |

## B. 申請担当者

| フィールド | 入力値 |
| --- | --- |
| 担当者氏名 | 梅田 茂利 |
| 担当者役職 | 代表取締役 |
| 担当者メール | info@bookyou.net |
| 担当者電話 | N/A (フォーム必須なら申請時に追記) |
| 連絡可能時間帯 | 平日 10:00-18:00 JST |
| 連絡優先手段 | メール |

## C. 提供サービス概要

| フィールド | 入力値 |
| --- | --- |
| サービス名 | jpcite |
| サービス名 (フリガナ) | ジェーピーサイト |
| サービス URL | https://jpcite.com |
| サービス開始時期 | 2026年5月 (本申請承認後の MF 連携公開を予定) |
| サービス概要 (200 字) | jpcite は、日本の公的制度データ (補助金・税制・法令・判例・入札・適格請求書) を一次資料リンクと出典明示付きで REST API + MCP サーバーから配信する B2B API インフラです。MoneyForward クラウド会計と連携し、顧客企業 (法人番号で 1:1 lookup) ごとに「使える補助金・税制根拠」を仕訳画面から参照可能にします。料金は ¥3/billable unit 完全従量、月額固定なし。 |
| サービスカテゴリ | API 連携 / 経理・会計支援 / 業務効率化 |
| ターゲット顧客 | 会計事務所、税理士法人、中小企業の経理担当者、freee/MoneyForward 連携 SaaS ベンダー |
| 想定利用シーン | (1) 仕訳登録時に取引摘要から該当する補助金・助成金の根拠リンクを自動表示、(2) 取引先 T 番号 (適格請求書事業者) の有効性を 1 req で検証、(3) 顧客企業の法人番号から「使える制度」リストを月次自動レポート |

## D. 連携方式 (Integration)

| フィールド | 入力値 |
| --- | --- |
| 連携方式 | REST API + MCP (Model Context Protocol) |
| 連携方向 | jpcite → MF クラウド (read-only)。MF → jpcite はなし |
| 認証方式 | OAuth 2.0 (MF 標準フロー) |
| 必要権限 (スコープ) | 法人情報 read (`houjin_bangou` 取得目的)、取引明細 read (摘要から制度抽出目的) |
| 書込み権限 | 一切要求しない (read-only) |
| OAuth Redirect URI | https://api.jpcite.com/oauth/moneyforward/callback |
| Webhook 受信 URL | https://api.jpcite.com/webhooks/moneyforward |
| API ベース URL | https://api.jpcite.com (REST), https://mcp.jpcite.com (MCP SSE) |
| OpenAPI 定義 | https://api.jpcite.com/openapi.json |
| MCP マニフェスト | https://mcp.jpcite.com/manifest.json |
| 接続テスト用 staging | https://api-staging.jpcite.com (申請審査時に提供可) |

## E. 課金モデル (Pricing & GMV)

| フィールド | 入力値 |
| --- | --- |
| 課金主体 | jpcite (Bookyou株式会社) が顧客から直接受領 |
| 課金方式 | API 完全従量制 (Metered) |
| 単価 | ¥3 / billable unit (税別、税込 ¥3.30) |
| 課金単位の定義 | 通常検索・詳細取得は 1 unit。batch / export は事前提示の式で算出 |
| 無料枠 | 匿名 3 req/日 per IP (JST 00:00 reset、登録不要) |
| 階層プラン | なし |
| 最低利用期間 | なし |
| 解約違約金 | なし |
| 決済 | Stripe (クレジットカード)、Stripe Tax で消費税自動計算 |
| インボイス | 適格請求書 (T8010001213708) を Stripe 経由で PDF 自動発行 |
| MoneyForward 経由の課金 | なし (顧客は jpcite に直接決済) |
| 月額予想 GMV (MF 経由) | ¥0 (MF 経由の課金フローを使わないため) |
| MoneyForward へのレベニューシェア | なし (MF 経由決済が発生しないため) |
| マーケットプレイス掲載料 | MF 規約に従う |

## F. データ取扱方針

| フィールド | 入力値 |
| --- | --- |
| 取得するデータ | 連携 MF 顧客企業の法人番号 (`houjin_bangou`)、取引摘要 (補助金マッチング目的のみ) |
| 利用目的 | (1) jpcite 制度 DB との 1:1 lookup、(2) 摘要からの制度候補抽出 |
| データ保管場所 | Cloudflare (CDN) + Fly.io (origin)。リージョン Tokyo (NRT) 主、Singapore (SIN) 副 |
| 越境移転 | DR 用 SIN 副リージョンへの非同期レプリケーションのみ。SCC 締結済み |
| 保持期間 | アクセスログ 90 日、API key は顧客自己削除可、取引摘要は処理後即廃棄 (永続保存しない) |
| 第三者提供 | なし (再販・転売・広告利用禁止) |
| 個人情報の取扱 | jpcite は公的制度データ (オープンデータ) のみを配信。MF 顧客の個人情報は処理目的の一時利用のみ、永続保存しない |
| 暗号化 | 通信 TLS 1.3、保存 AES-256 |
| 削除請求対応 | info@bookyou.net、30 日以内 |
| インシデント連絡 | info@bookyou.net + status.jpcite.com 公開 |
| プライバシーポリシー | https://jpcite.com/privacy.html |
| 利用規約 | https://jpcite.com/tos.html |
| 特定商取引法表示 | https://jpcite.com/tokushoho.html |
| データ利用ライセンス | https://jpcite.com/data-licensing.html |

## G. セキュリティ・SLA

| フィールド | 入力値 |
| --- | --- |
| ISMS / Pマーク等の認証 | N/A (現時点で未取得、launch 後の取得計画あり) |
| SLA (目標) | 99.5% / 月 |
| 応答時間 (目標) | P95 < 500ms (REST 通常検索) |
| インシデント時 RTO / RPO | RTO 4h、RPO 1h (DR 副リージョン NRT → SIN) |
| 脆弱性対応 | CVSS 7.0 以上は 72h 以内、それ以下は次回リリース |
| ペネトレーションテスト | launch 前に 1 回実施予定 |
| ステータス公開 | https://jpcite.com/status.html |

## H. アイコン・素材 (Assets)

| フィールド | ファイル / 値 |
| --- | --- |
| サービスロゴ (512x512 PNG) | `/Users/shigetoumeda/jpcite/docs/assets/images/logo-512.png` |
| サービスロゴ (SVG) | `/Users/shigetoumeda/jpcite/site/assets/logo-v2.svg` |
| スクリーンショット 1 | MF 仕訳画面に jpcite 制度根拠リンクがオーバーレイ表示される画面 |
| スクリーンショット 2 | jpcite 制度マッチング結果ダッシュボード (https://api.jpcite.com/dashboard) |
| スクリーンショット 3 | 適格請求書事業者検証 API の curl サンプル (`https://jpcite.com/docs/invoice-lookup.html`) |
| 紹介動画 (任意) | N/A (今回は提出しない) |

スクリーンショット撮影手順は別途ユーザー実機で撮影。

## I. サポート体制

| フィールド | 入力値 |
| --- | --- |
| サポート窓口 | info@bookyou.net |
| サポート受付時間 | 平日 10:00-18:00 JST |
| 一次回答 SLA | 48 営業時間以内 |
| 対応言語 | 日本語、英語 |
| 公開ドキュメント | https://jpcite.com/docs/ (日本語)、https://jpcite.com/en/docs/ (英語) |
| FAQ / よくある質問 | https://jpcite.com/support.html |

## J. マーケティング・PR

| フィールド | 入力値 |
| --- | --- |
| MoneyForward 公式マーケティング素材への利用許諾 | 可 |
| 共同プレスリリースの可否 | 可 (内容事前確認の上) |
| MF Marketplace への掲載文面の確認方法 | info@bookyou.net 宛の text 送付で可 |
| 既存ユーザー数 | N/A (launch 直後、申請時点で追記) |
| 既存パートナーシップ | freee Apps (同時申請中) |

## K. 補足・特記事項

- jpcite は MF クラウド顧客の取引データを永続保存しない。摘要テキストは制度マッチング処理後に即廃棄、出力 (制度候補リスト) のみを返す。
- MF 経由の課金フロー (アプリ内課金 / レベニューシェア) は使用しない。MF Marketplace は「連携先サービス」としての掲載のみを希望。
- jpcite は商標出願していない (rename で衝突回避方針)。MF 商標ガイドラインに従い「jpcite for MoneyForward」等の表記は事前承認を得る。
- 法人番号による 1:1 lookup は完全に決定論的な操作 (LLM 推論を含まない)。誤マッチによる仕訳影響リスクは低い。
- 制度根拠の引用は一次資料 (e-Gov 法令データ、各省庁告示、自治体例規) へのリンクを必ず含む。

---

## L. 提出前チェックリスト (申請者 = ユーザーが確認)

- [ ] 共通プロファイル (`common_company_profile.md`) と本ドキュメントの値が一致
- [ ] privacy.html / tos.html / tokushoho.html / data-licensing.html が公開済み
- [ ] api.jpcite.com / mcp.jpcite.com が稼働中、staging も稼働中
- [ ] OAuth callback エンドポイントが 200 を返す (MF staging で疎通テスト)
- [ ] Stripe Tax 設定済み (適格請求書発行可)
- [ ] ロゴ 512x512 PNG をアップロード
- [ ] スクリーンショット 3 枚を撮影・添付
- [ ] info@bookyou.net 受信体制を確認 (申請審査期間中の問い合わせ用)
- [ ] freee Apps 申請 (同時提出) との内容整合を確認

---

## M. 改訂履歴

- 2026-05-05: 初版作成 (Claude セッション)
