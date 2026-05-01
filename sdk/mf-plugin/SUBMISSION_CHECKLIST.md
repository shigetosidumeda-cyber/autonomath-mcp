# MF アプリポータル 提出チェックリスト (jpcite)

> 目的: `jpcite` を MF クラウドの公開アプリとして最短ルートで提出する。
> 読み方: ✅ は提出前チェック済み、⚠️ は実アカウントや管理画面での確認が必要。

## A. コード / インフラ

| # | 項目 | 状態 | 備考 |
|---|---|---|---|
| 1 | OAuth2 認可フロー実装 (CLIENT_SECRET_BASIC) | ✅ done | `oauth_callback.py` (state CSRF + secrets.compare_digest) |
| 2 | MF tenant 取得 → session 化 | ✅ done | tenant_uid + 表示名のみ。仕訳・元帳には触れない |
| 3 | refresh_token フロー | ✅ done | `refresh_access_token()` 実装 (proxy から呼べる形) |
| 4 | revoke endpoint への logout 連携 | ✅ done | `/oauth/logout` → MF revoke (best-effort) |
| 5 | プロキシエンドポイント 5 本 | ✅ done | search-subsidies / search-tax-incentives / check-invoice-registrant / search-laws / search-court-decisions |
| 6 | `/mf-plugin/me` (UI 用 認可状態 endpoint) | ✅ done | token は返さない |
| 7 | iframe フレンドリー UI | ✅ done | vanilla HTML+JS、CSP `frame-ancestors` で MF ホスト群 7 箇所許可 |
| 8 | 税理士法 §52 免責 (UI + API) | ✅ done | フッター常時表示 + `_disclaimer` フィールド全 JSON 同梱 |
| 9 | ヘルスチェック | ✅ done | `/healthz` |
| 10 | CSP / セキュリティヘッダ | ✅ done | inline スクリプトは popup 内のみ |
| 11 | セッション cookie HttpOnly + Secure + SameSite=None | ✅ done | iframe 内で動くために None 必須 |
| 12 | env 検証 (起動時 fail-fast) | ✅ done | `config.py` の `load_settings()` |
| 13 | テスト (env + 認可 + プロキシ + CSP) | ✅ done | `pytest tests/` で全 PASS |
| 14 | Dockerfile + Fly.io toml | ✅ done | HND リージョン、shared-cpu-1x / 256MB |
| 15 | `.dockerignore` / `.gitignore` | ✅ done | secrets / .venv 除外 |
| 16 | Fly.io 実デプロイ + DNS (`mf-plugin.jpcite.com`) | ⚠️ **要人間** | `fly launch` + Cloudflare DNS A/AAAA |
| 17 | MF アプリポータルでアプリ作成 + Client ID/Secret 取得 | ⚠️ **要人間** | https://app.biz.moneyforward.com/app-portal/ |
| 18 | redirect_uri 登録 (`https://mf-plugin.jpcite.com/oauth/callback`) | ⚠️ **要人間** | アプリポータル「アプリ開発」画面 |
| 19 | Stripe metered subscription 紐付け (`jpcite_live_...`) | ⚠️ **要人間** | Bookyou 既存の Stripe で OK |

## B. 提出パッケージ (submission/)

| # | 項目 | 状態 | ファイル |
|---|---|---|---|
| 20 | `manifest.json` | ✅ done | `submission/manifest.json` |
| 21 | アプリ説明文 (日本語、1 段落 + 3 bullet + ユースケース) | ✅ done | `submission/copy/description.ja.md` |
| 22 | scope 取得理由 (mfc/ac/data.read のみ・取得しない情報を明示) | ✅ done | `submission/copy/scope_justification.ja.md` |
| 23 | 審査担当者向けウォークスルー | ✅ done | `submission/copy/review_demo_walkthrough.ja.md` |
| 24 | アイコン 512×512 PNG | ✅ stub | `submission/screenshots/icon-512x512.png` (単色 PNG) |
| 25 | ハイライト画像 5 点 (1200×630 PNG) | ✅ stub | `submission/screenshots/01..05-*.png` |
| 26 | 実 logo PNG (Bookyou 公式) | ⚠️ **要人間** | user から提供必要 |
| 27 | 実 MF 連携での screenshot 5 枚 | ⚠️ **要人間** | MF 本番事業所でログイン → プラグイン起動 → 各タブで実検索 → 1200×630 取得 |
| 28 | プライバシーポリシー URL | ⚠️ **要人間** | `https://jpcite.com/privacy` (description.ja の compliance 節を流用可) |
| 29 | 利用規約 URL | ⚠️ **要人間** | `https://jpcite.com/terms` |
| 30 | 特商法表記 URL | ⚠️ **要人間** | `https://jpcite.com/tokutei` |
| 31 | 連携ページ URL | ⚠️ **要人間** | `https://jpcite.com/mf` |
| 32 | ヘルプページ URL | ⚠️ **要人間** | `https://jpcite.com/docs/mf` |
| 33 | 審査担当者用 demo アカウント発行 | ⚠️ **要人間** | MF 側 `mf-review@bookyou.net` + jpcite.com 側 sandbox 認証情報 |

## C. 法令・コンプライアンス

| # | 項目 | 状態 | 備考 |
|---|---|---|---|
| 34 | 税理士法 §52 免責の文言レビュー | ✅ done | UI + API + manifest の三箇所で一貫 |
| 35 | 個人情報保護法 (APPI) 第三者提供記述 | ✅ done | `manifest.json` compliance 節 |
| 36 | 適格請求書発行事業者番号 表記 | ✅ done | T8010001213708 を全 surface に明示 |
| 37 | データ residency (日本国内) | ✅ done | Fly.io HND 固定 |
| 38 | Subprocessor リスト (Fly/Cloudflare/Stripe) | ✅ done | manifest.compliance.third_party_subprocessors |
| 39 | 弁護士レビュー (税理士法・電帳法) | ⚠️ **要人間** | freee 提出時のレビュー結果を流用可 (大きな差分なし) |

## D. 提出フォーム入力 (MF アプリポータル)

| # | 項目 | 状態 | データ ソース |
|---|---|---|---|
| 40 | アプリ名 / キャッチコピー | ✅ ready | `description.ja.md` 冒頭 + `manifest.json` |
| 41 | カテゴリ選択 (業務効率化) | ✅ ready | `manifest.json` category |
| 42 | アイコン アップロード | ✅ stub | `submission/screenshots/icon-512x512.png` (差し替え推奨) |
| 43 | ハイライト画像 アップロード ×5 | ✅ stub | `submission/screenshots/01-05*.png` (差し替え推奨) |
| 44 | 連携ページ / ヘルプページ URL 入力 | ⚠️ **要人間** | URL 実装後 |
| 45 | callback URL 入力 (= redirect_uri) | ⚠️ **要人間** | `https://mf-plugin.jpcite.com/oauth/callback` |
| 46 | 申請 scope 選択: mfc/ac/data.read | ✅ ready | `manifest.oauth.scopes` |
| 47 | クライアント認証方式 (CLIENT_SECRET_BASIC) | ✅ ready | アプリ登録画面で選択 |
| 48 | 開発者情報 / 連絡先メール | ✅ ready | `manifest.app.developer` |
| 49 | 審査用 demo アカウント情報 | ⚠️ **要人間** | 上記 #33 で生成した値を input |
| 50 | 提出ボタン押下 | ⚠️ **要人間** | 全 ⚠️ クリア後 |

## 提出可能までのギャップ

提出前チェック済み (✅): 35/50 項目。
要人間アクション (⚠️): 15 項目 (主に DNS / Fly.io / MF 開発者登録 / 公開ページ実装 / 実環境 screenshot / logo)。

## 検証状態

- pytest で OAuth state / proxy logic を検証。
- 実 MF API と実 jpcite API はテストから呼ばない。
- 実環境 screenshot と marketplace 申請は人手確認が必要。

## 提出後タイムライン (MF 公式 SLA は未公表)

> 注: MF 公式は審査期間の SLA を公開していない。freee の「約 1 週間」と
> 同等を仮定し、内容次第で 2-12 週間と幅を持たせる。

- **T+0**: 全 ⚠️ クリア → アプリポータル「申請」ボタン押下
- **T+1〜14d**: MF 一次レビュー (技術質問が来る可能性あり)
- **T+14〜45d**: 修正対応往復 (経験則: 通常 2 round 以内)
- **T+公開**: アプリストア掲載 + 流入計測 開始

## 仮定事項 (公式 docs で確証取れず env で吸収)

1. **OAuth ホスト**: `app.biz.moneyforward.com/oauth/{authorize,token,revoke}` を
   既定とする。実 アプリポータル登録時に異なるホストが提示されたら `MF_AUTHORIZE_URL` /
   `MF_TOKEN_URL` / `MF_REVOKE_URL` で env 上書き。
2. **scope 命名**: `mfc/ac/data.read` を会計プロダクトの read 用とする。実 アプリポータル
   登録画面で別 string が指定されたら env (`MF_SCOPE`) で上書き。
3. **tenant 情報取得 endpoint**: `GET /tenants` (Bearer access_token) を best-effort で叩き、
   `data[0].uid` / `data[0].name` を採用。失敗しても session は作る (UI で「事業者名取得中」表示)。
4. **review SLA**: 公式公表なし。freee 並みの 1-2 週間を仮定。

## 比較: freee plugin path vs MF plugin path

| 観点 | freee plugin | MF plugin |
|---|---|---|
| Runtime | Node 20 + Express | Python 3.11 + FastAPI |
| OAuth scope 体系 | 粗い (`read`) | 細かい (`mfc/ac/data.read` 等プロダクト×操作軸) |
| 認可単位 | アプリと事業所の組合せ | 事業者 (tenant) 単位 |
| Client 認証 | client_secret_post 既定 | CLIENT_SECRET_BASIC 既定 |
| iframe ホスト | `app.secure.freee.co.jp` 単一 | MF クラウドの製品別 7 ホスト |
| 開発者ポータル | https://app.secure.freee.co.jp/developers/applications | https://app.biz.moneyforward.com/app-portal/ |
| 公開審査 SLA | 公称 1 週間 | 未公表 (推定 1-2 週間) |
| referral fee | freee Partner Program 経由で 10% 還元前提 | 公式 partner fee 体系は未確認 (`mfc/ac/data.read` 単独利用なら別途交渉) |
| 提出物 schema | 公式 schema URL 公開 | 公式 schema URL 未公開 → アプリポータル UI フォーム転記 |
| 同一仕様 | manifest 構造、税理士法免責、¥3.30/req metering、tokutei 表示、qualified-invoice 番号、subprocessor list、tier 課金禁止 | (左記すべてと同一) |
