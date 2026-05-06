---
title: freee / MoneyForward marketplace submission
updated: 2026-05-04
operator_only: true
category: deploy
---

# Runbook: freee アプリストア + MoneyForward アプリポータル 提出

> Operator-only manual procedure. Both marketplaces require interactive
> 開発者ポータル sign-in, OAuth client creation, and human review of submitted
> assets — none of this can be automated.

両 marketplace は同じ 提出パターンに従う。先に共通ステップを終わらせ、最後の
review submit だけを 2 ベンダごとに行う。

## 0. 前提条件

| 項目 | freee | MoneyForward |
|------|-------|--------------|
| 開発者ポータル URL | <https://app.secure.freee.co.jp/developers/applications> | <https://app.biz.moneyforward.com/app-portal/> |
| OAuth scope | `read` | `mfc/ac/data.read` |
| Client 認証 | client_secret_post | CLIENT_SECRET_BASIC |
| アイコンサイズ | 640×640 PNG | 512×512 PNG |
| 提出 manifest | `sdk/freee-plugin/marketplace/submission/manifest.json` | `sdk/mf-plugin/submission/manifest.json` |
| アイコン (実) | `sdk/freee-plugin/marketplace/submission/screenshots/icon-640x640.png` (jpcite logo, 640x640 RGBA) | `sdk/mf-plugin/submission/screenshots/icon-512x512.png` (jpcite logo, 512x512 RGBA) |

> アイコンは 2026-05-04 に `site/assets/favicon-512.png` を流用 (MF) +
> 640×640 拡大版 (freee) で実画像化済み。差替不要。

## 1. インフラ準備 (両 marketplace 共通)

### 1.1 Fly.io デプロイ

```bash
# freee plugin
cd /Users/shigetoumeda/jpcite/sdk/freee-plugin/marketplace
fly launch --copy-config --no-deploy --org bookyou --region hnd --name jpcite-freee-plugin
fly deploy

# MF plugin
cd /Users/shigetoumeda/jpcite/sdk/mf-plugin
fly launch --copy-config --no-deploy --org bookyou --region hnd --name jpcite-mf-plugin
fly deploy
```

### 1.2 Cloudflare DNS

| Zone | Subdomain | Type | Target |
|------|-----------|------|--------|
| jpcite.com | freee-plugin | CNAME | jpcite-freee-plugin.fly.dev |
| jpcite.com | mf-plugin | CNAME | jpcite-mf-plugin.fly.dev |

両方とも proxy ON、TLS は Cloudflare Universal SSL で十分。

### 1.3 Fly secret 投入

```bash
# freee
fly secrets set --app jpcite-freee-plugin \
  FREEE_CLIENT_ID=...      FREEE_CLIENT_SECRET=... \
  JPCITE_API_KEY=...       SESSION_SECRET="$(openssl rand -hex 32)"

# MF
fly secrets set --app jpcite-mf-plugin \
  MF_CLIENT_ID=...         MF_CLIENT_SECRET=... \
  JPCITE_API_KEY=...       SESSION_SECRET="$(openssl rand -hex 32)"
```

## 2. 公開ページ実装 (両方共通)

`https://jpcite.com/{privacy,terms,tokutei,freee,mf,docs/freee,docs/mf}` を
Cloudflare Pages 側で公開。`sdk/freee-plugin/marketplace/submission/copy/` と
`sdk/mf-plugin/submission/copy/` の文言を流用 → `site/` 配下に静的 HTML 化 →
push → Pages 自動デプロイ。

## 3. freee 開発者ポータル 提出

1. <https://app.secure.freee.co.jp/developers/applications> でログイン (Bookyou)
2. 「アプリ作成」→ アプリ名 = `jpcite — 補助金/税制優遇/インボイス検索`
3. callback URL = `https://freee-plugin.jpcite.com/oauth/callback`
4. scope = `read` のみ
5. アプリ情報入力:
   - アイコン: `sdk/freee-plugin/marketplace/submission/screenshots/icon-640x640.png` をアップロード
   - ハイライト画像 5 点: `submission/screenshots/01..05.png` をアップロード
   - 説明文: `submission/copy/description.ja.md` をコピー
   - scope 取得理由: `submission/copy/scope_justification.ja.md` をコピー
   - プライバシーポリシー URL: `https://jpcite.com/privacy`
   - 利用規約 URL: `https://jpcite.com/terms`
   - 特商法表記 URL: `https://jpcite.com/tokutei`
   - 連携ページ URL: `https://jpcite.com/freee`
   - ヘルプページ URL: `https://jpcite.com/docs/freee`
   - 審査用 demo アカウント: secure_notes 欄に sandbox 認証情報を記載
6. 開発者情報・連絡先 = `info@bookyou.net`
7. 申請ボタン押下
8. T+1〜7d で freee 一次レビュー、修正対応 1-2 round 想定 (公称 SLA 約 1 週間)

## 4. MoneyForward アプリポータル 提出

1. <https://app.biz.moneyforward.com/app-portal/> でログイン (Bookyou)
2. 「アプリ開発」→ 新規アプリ作成
3. redirect_uri = `https://mf-plugin.jpcite.com/oauth/callback`
4. scope = `mfc/ac/data.read` のみ
5. クライアント認証方式 = CLIENT_SECRET_BASIC
6. アプリ情報入力:
   - アイコン: `sdk/mf-plugin/submission/screenshots/icon-512x512.png`
   - ハイライト画像 5 点: `submission/screenshots/01..05-*.png`
   - 説明文: `submission/copy/description.ja.md`
   - scope 取得理由: `submission/copy/scope_justification.ja.md`
   - 各種 URL: privacy / terms / tokutei / mf 連携 / docs/mf
   - 審査用 demo アカウント: フォーム内 secure_notes
7. 提出ボタン押下
8. T+1〜14d で MF 一次レビュー、修正対応 1-2 round 想定 (公式 SLA 未公表)

## 5. 提出後 monitoring

- freee: 開発者ポータルの「アプリ状況」タブを毎日チェック
- MF: アプリポータルの「申請履歴」+ 担当者からのメール (info@bookyou.net)
- 公開後は両 marketplace の analytics で 流入 / 連携完了 / disconnect 件数を週次計測

## 6. 失敗パターンと対処

| 症状 | 原因 | 対処 |
|------|------|------|
| `redirect_uri_mismatch` | callback URL の登録 typo | アプリ管理画面で URL を再保存し fly secret も再 set |
| iframe で `Refused to display in a frame` | CSP `frame-ancestors` に対象 host が無い | `app.py` (MF) / `src/middleware.js` (freee) の CSP allow-list を更新して再 deploy |
| OAuth callback で 401 | `client_secret` が古い、または fly secret 未投入 | 開発者ポータルで secret 再生成 → fly secrets set → fly deploy |
| MF 一次レビュー差戻し: 「scope justification 不足」 | scope 取得理由が抽象的 | `submission/copy/scope_justification.ja.md` に「取得しないデータ」リストを明示し再提出 |

## 7. 内部コミュニケーション

両 marketplace 通過後、`site/index.html` の対応バッジ (freee app store / MF
連携) を有効化。`site/llms.txt` の sameAs にもストア URL を追加。
