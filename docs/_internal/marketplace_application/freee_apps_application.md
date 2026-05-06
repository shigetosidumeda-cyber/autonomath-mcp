# freee Apps 申請書 下書き (jpcite)

最終更新: 2026-05-05
作成者: jpcite operator (Claude セッション、内部下書き)
ステータス: 申請書下書き — ユーザー署名・提出待ち
申請 URL: https://app.secure.freee.co.jp/developers/applications/new
共通プロファイル: [common_company_profile.md](./common_company_profile.md)

注: フィールド名は freee Developers Console 「アプリケーションの新規作成」フォームの実フィールドに合わせている。最新フォームと一致しないフィールドはユーザー側で読み替えて転記する。

---

## A. アプリケーション基本情報

| フィールド | 入力値 |
| --- | --- |
| アプリ名 (App name) | jpcite |
| アプリ名 (英語表記) | jpcite |
| アプリ名 (フリガナ) | ジェーピーサイト |
| 短い説明 (Short description, 80 字以内) | 日本の補助金・税制・法令・適格請求書を REST + MCP で配信する B2B API |
| 詳細説明 (Long description) | jpcite は、日本の公的制度データ (補助金・税制・法令・判例・入札・適格請求書) を一次資料リンクと出典明示付きで REST API + MCP サーバーから配信する B2B API インフラです。freee 顧問契約者・会計事務所が顧客企業 (法人番号で 1:1 lookup) ごとに「使える補助金・税制」を自動マッチングし、仕訳の根拠リンクや適格請求書事業者検証を業務に組み込めます。料金は完全従量 ¥3 / billable unit (税別)、匿名 3 req/日 per IP は無料、月額固定なし。 |
| カテゴリー | 経理・会計支援 / API 連携 |
| 提供開始予定日 | 申請承認後 7 日以内 |
| アプリ公開状態 | 一般公開 (パブリック) |
| アプリ種別 | OAuth クライアント (read-only) |

## B. 開発・運営事業者情報

(共通プロファイル §1, §2 を転記)

| フィールド | 入力値 |
| --- | --- |
| 法人名 | Bookyou株式会社 |
| 法人名 (英文) | Bookyou, Inc. |
| 法人番号 | 8010001213708 |
| 適格請求書発行事業者番号 | T8010001213708 |
| 代表者氏名 | 梅田 茂利 |
| 代表者役職 | 代表取締役 |
| 所在地 | 〒112-0006 東京都文京区小日向2-22-1 |
| 連絡先メール | info@bookyou.net |
| 連絡先電話 | N/A (フォーム必須項目の場合は申請時に追記) |
| 公式 Web | https://jpcite.com |
| サポート窓口 URL | https://jpcite.com/support.html |
| プライバシーポリシー URL | https://jpcite.com/privacy.html |
| 利用規約 URL | https://jpcite.com/tos.html |
| 特定商取引法表示 URL | https://jpcite.com/tokushoho.html |

## C. OAuth 設定

| フィールド | 入力値 |
| --- | --- |
| OAuth Redirect URI (Production) | https://api.jpcite.com/oauth/freee/callback |
| OAuth Redirect URI (Staging) | https://api-staging.jpcite.com/oauth/freee/callback |
| Webhook URL | https://api.jpcite.com/webhooks/freee |
| ログアウト後のリダイレクト先 | https://jpcite.com/ |
| トークン有効期限 | freee デフォルトに従う (24 時間 + refresh) |

## D. 要求するスコープ (Required Scopes)

| スコープ | 用途 | 必須/任意 |
| --- | --- | --- |
| `companies:read` | 顧問契約者が連携した法人の `houjin_bangou` (法人番号) を取得し、jpcite 制度 DB と 1:1 lookup するため | 必須 |
| `deals:read` | 取引摘要から「補助金・助成金」候補を抽出し、jpcite 制度 DB と照合するため (read-only) | 必須 |

書込み (`*:write`)、ユーザー個人情報 (`users:read`)、銀行明細 (`walletables:*`) は要求しない。

## E. 課金モデル (Pricing)

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
| 決済方法 | Stripe (クレジットカード)、Stripe Tax で消費税自動計算 |
| インボイス対応 | 適格請求書発行事業者 T8010001213708 として PDF 自動発行 |
| freee へのレベニューシェア | なし (顧客は jpcite へ直接決済) |
| アプリ自体の価格表示 | 無料 (API 利用に応じた従量課金は jpcite 側で別途) |

## F. アイコン・スクリーンショット (Assets)

| フィールド | ファイル / 値 |
| --- | --- |
| アプリアイコン (512x512 PNG) | `/Users/shigetoumeda/jpcite/docs/assets/images/logo-512.png` |
| アプリアイコン (SVG) | `/Users/shigetoumeda/jpcite/site/assets/logo-v2.svg` |
| スクリーンショット 1 | jpcite 制度マッチング結果ページ (https://jpcite.com/programs/sample 等のキャプチャ) |
| スクリーンショット 2 | freee 連携後のダッシュボード (https://api.jpcite.com/dashboard キャプチャ) |
| スクリーンショット 3 | ブラウザ拡張 (Bookmarklet) で freee 取引画面に補助金候補がオーバーレイ表示される画面 (`https://jpcite.com/bookmarklet.html`) |
| 説明動画 (任意) | N/A (今回は提出しない) |

スクリーンショット撮影手順は別途 `docs/_internal/marketplace_application/screenshots_capture_plan.md` を申請直前に作成 (今回スコープ外、ユーザー実機で撮る)。

## G. データ取扱・セキュリティ (Privacy & Security)

| フィールド | 入力値 |
| --- | --- |
| 取得する個人情報 | 連携法人の法人番号 (`houjin_bangou`)、freee アカウント連携 token のみ |
| 個人データ保持期間 | アクセスログ 90 日、API key は顧客自己削除可 |
| 第三者提供 | なし (再販・転売・広告利用禁止) |
| 越境移転 | なし (Cloudflare + Fly.io 東京 NRT 主、Singapore SIN 副の DR、両方 SCC 締結済み) |
| 暗号化 | 通信 TLS 1.3、保存 AES-256 (Fly.io volume 暗号化) |
| インシデント連絡先 | info@bookyou.net、24h 以内一次回答 |
| 削除請求対応 | info@bookyou.net、30 日以内 |
| 監査ログ | https://jpcite.com/audit-log.html (顧客自己ダウンロード可) |

## H. サポート体制 (Support)

| フィールド | 入力値 |
| --- | --- |
| サポート窓口 | info@bookyou.net、https://jpcite.com/support.html |
| サポート対応時間 | 平日 10:00-18:00 JST、48 営業時間以内一次回答 |
| サポート対応言語 | 日本語、英語 |
| インシデント時の連絡 | status.jpcite.com 公開 + 影響顧客にメール通知 |
| ドキュメント | https://jpcite.com/docs/、https://api.jpcite.com/openapi.json |

## I. レビュー・公開希望

| フィールド | 入力値 |
| --- | --- |
| レビュー期間中の連絡先 | info@bookyou.net |
| 公開希望日 | 申請承認後 7 日以内 |
| マーケティング素材掲載許可 | 可 (freee Apps ストア・freee 公式ブログでの紹介を許諾) |
| プレスリリース連動 | jpcite 側で同日付プレスリリース予定 (PR TIMES 配信) |

## J. 補足・特記事項 (Additional Notes)

- jpcite は freee 顧問契約者 (会計事務所) を主要ターゲットとし、顧問先企業 (中小企業) の制度活用を支援する立場。書込み権限は要求しない。
- 適格請求書事業者検証 API は、freee 取引登録時に取引先 T 番号の有効性を 1 req で確認する用途を想定。
- 制度マッチングは法人番号 (`houjin_bangou`) を key とした 1:1 lookup のみ。freee 側顧客企業情報の二次利用・プロファイリングは行わない。
- jpcite は商標出願していない (rename で衝突回避方針)。freee 側の商標ガイドラインに従い「jpcite for freee」等の表記は事前承認を得る。

---

## K. 提出前チェックリスト (申請者 = ユーザーが確認)

- [ ] 共通プロファイル (`common_company_profile.md`) と本ドキュメントの値が一致
- [ ] privacy.html / tos.html / tokushoho.html が公開済み
- [ ] api.jpcite.com / mcp.jpcite.com が稼働中
- [ ] OAuth callback エンドポイントが 200 を返す (要 staging テスト)
- [ ] Stripe Tax 設定済み (適格請求書発行可)
- [ ] ロゴ 512x512 PNG をアップロード
- [ ] スクリーンショット 3 枚を撮影・添付
- [ ] レビュー期間中の email 受信体制 (info@bookyou.net) を確認

---

## L. 改訂履歴

- 2026-05-05: 初版作成 (Claude セッション)
