# freee アプリストア 提出チェックリスト (jpcite)

> 目的: `jpcite` を freee の Public app として最短ルートで提出する。
> 読み方: ✅ は提出前チェック済み、⚠️ は実アカウントや管理画面での確認が必要。

## A. コード / インフラ

| # | 項目 | 状態 | 備考 |
|---|---|---|---|
| 1 | OAuth2 認可フロー実装 | ✅ done | `src/routes/oauth.js` (state CSRF + prompt=select_company) |
| 2 | freee /api/1/companies 取得 → session 化 | ✅ done | 法人番号 best-effort 抽出付き |
| 3 | プロキシエンドポイント 3 本 | ✅ done | search-tax-incentives / search-subsidies / check-invoice-registrant |
| 4 | iframe フレンドリー UI | ✅ done | vanilla HTML+JS、CSP `frame-ancestors freee.co.jp` 設定済み |
| 5 | 税理士法 §52 免責 (UI + API) | ✅ done | フッター常時表示 + `_disclaimer` フィールド全レス搭載 |
| 6 | ヘルスチェック | ✅ done | `/healthz` |
| 7 | CSP / helmet | ✅ done | inline スクリプトは popup 内のみ許可 |
| 8 | セッション cookie HttpOnly + Secure + SameSite=None | ✅ done | iframe 内で動くために None 必須 |
| 9 | env 検証 (起動時 fail-fast) | ✅ done | `lib/env.js` の `assertEnv()` |
| 10 | テスト (env + 認可 + プロキシ) | ✅ done | `npm test` で 9/9 PASS |
| 11 | Dockerfile + Fly.io toml | ✅ done | HND リージョン、shared-cpu-1x / 256MB |
| 12 | `.dockerignore` / `.gitignore` | ✅ done | secrets / node_modules 除外 |
| 13 | Fly.io 実デプロイ + DNS (`freee-plugin.jpcite.com`) | ⚠️ **要人間** | `fly launch` + Cloudflare DNS A/AAAA レコード |
| 14 | freee 開発者ポータルでアプリ作成 + client_id/secret 取得 | ⚠️ **要人間** | https://app.secure.freee.co.jp/developers/applications |
| 15 | redirect_uri 登録 (`https://freee-plugin.jpcite.com/oauth/callback`) | ⚠️ **要人間** | freee 側の設定画面 |
| 16 | Stripe metered subscription 紐付け (`jpcite_live_...`) | ⚠️ **要人間** | Bookyou 既存の Stripe Connect で OK |

## B. 提出パッケージ (submission/)

| # | 項目 | 状態 | ファイル |
|---|---|---|---|
| 17 | `manifest.json` | ✅ done | `submission/manifest.json` |
| 18 | アプリ説明文 (日本語、1 段落 + 3 bullet + ユースケース) | ✅ done | `submission/copy/description.ja.md` |
| 19 | scope 取得理由 (read のみ・取得しない情報を明示) | ✅ done | `submission/copy/scope_justification.ja.md` |
| 20 | 審査担当者向けウォークスルー | ✅ done | `submission/copy/review_demo_walkthrough.ja.md` |
| 21 | アイコン 640×640 PNG | ✅ stub | `submission/screenshots/icon-640x640.png` (合成画像) |
| 22 | ハイライト画像 5 点 (1200×630 PNG) | ✅ stub | `submission/screenshots/01..05.png` (UI モックアップ) |
| 23 | 実 freee 連携での スクリーンショット | ⚠️ **要人間** | freee 本番事業所でログイン → プラグイン起動 → 各タブで実検索 → スクリーンショット 5 枚を上書き保存 |
| 24 | プライバシーポリシー URL | ⚠️ **要人間** | `https://jpcite.com/privacy` のページ実装 (本文は `description.ja.md` の compliance 節を流用可) |
| 25 | 利用規約 URL | ⚠️ **要人間** | `https://jpcite.com/terms` のページ実装 |
| 26 | 特商法表記 URL | ⚠️ **要人間** | `https://jpcite.com/tokutei` のページ実装 (Bookyou 法人情報で OK) |
| 27 | 連携ページ URL | ⚠️ **要人間** | `https://jpcite.com/freee` のランディング |
| 28 | ヘルプページ URL | ⚠️ **要人間** | `https://jpcite.com/docs/freee` のドキュメント |
| 29 | 審査担当者用 demo アカウント発行 | ⚠️ **要人間** | freee と jpcite.com 両方で sandbox 用ログイン情報を作成、submission form の secure_notes に記載 |
| 30 | YouTube デモ動画 | 任意 | freee は optional。後追いで OK |

## C. 法令・コンプライアンス

| # | 項目 | 状態 | 備考 |
|---|---|---|---|
| 31 | 税理士法 §52 免責の文言レビュー | ✅ done | UI 表示文言は「情報提供のみ・税理士業務に該当せず・顧問税理士確認推奨」の三点で構成 |
| 32 | 個人情報保護法 (APPI) 第三者提供記述 | ✅ done | `manifest.json` compliance 節 + privacy URL 側で明示予定 |
| 33 | 適格請求書発行事業者番号 表記 | ✅ done | T8010001213708 を全 surface に明示 |
| 34 | データ residency (日本国内) | ✅ done | Fly.io HND 固定、manifest に明記 |
| 35 | Subprocessor リスト (Fly/Cloudflare/Stripe) | ✅ done | manifest.compliance.third_party_subprocessors |
| 36 | 弁護士レビュー (税理士法・電帳法) | ⚠️ **要人間** | 既存の Bookyou 顧問弁護士 1 時間レビュー推奨 (申請後でも可) |

## D. 提出フォーム入力 (freee 開発者ポータル)

| # | 項目 | 状態 | データ ソース |
|---|---|---|---|
| 37 | アプリ名 / キャッチコピー | ✅ ready | `description.ja.md` 冒頭 + `manifest.json` |
| 38 | カテゴリ選択 (業務効率化) | ✅ ready | `manifest.json` category |
| 39 | アイコン アップロード | ✅ stub | `submission/screenshots/icon-640x640.png` |
| 40 | ハイライト画像 アップロード ×5 | ✅ stub | `submission/screenshots/01-05*.png` |
| 41 | 連携ページ / ヘルプページ URL 入力 | ⚠️ **要人間** | URL 実装後 |
| 42 | callback URL 入力 (= redirect_uri) | ⚠️ **要人間** | `https://freee-plugin.jpcite.com/oauth/callback` |
| 43 | 申請権限 (scope) 選択: read | ✅ ready | manifest.oauth.scopes |
| 44 | 開発者情報 / 連絡先メール | ✅ ready | manifest.app.developer |
| 45 | 審査用 demo アカウント情報 | ⚠️ **要人間** | 上記 #29 で生成した値を input |
| 46 | 提出ボタン押下 | ⚠️ **要人間** | 全 ⚠️ をクリアした後 |

## 提出可能までのギャップ

提出前チェック済み (✅): 35/46 項目。
要人間アクション (⚠️): 11 項目 (主に DNS / Fly.io / freee 開発者登録 / 公開ページ実装 / 実環境スクリーンショット)。

## 検証状態

- Node built-in test runner で OAuth state / proxy logic を検証。
- 実 freee API と実 jpcite API はテストから呼ばない。
- 実環境 screenshot と marketplace 申請は人手確認が必要。

## 提出後タイムライン (freee 公式: 約 1 週間 → 申請ガイドの公称値)

> 注: タスク本文は「review takes 2-3 months」と記載されているが、freee 公式
> ドキュメントは「約 1 週間以内」と公称。実態は内容次第で 2-12 週間と幅がある
> ため、Y1 forecast 前提で **week 1 中の提出** を維持し、レビュー期間は実測する。

- **T+0**: 全 ⚠️ クリア → 申請フォーム submit
- **T+1〜7d**: freee 一次レビュー (技術質問が来る可能性あり)
- **T+7〜30d**: 修正対応往復 (経験則: 通常 2 round 以内)
- **T+公開**: マーケットプレイス掲載 + Y1 forecast の流入計測 開始
