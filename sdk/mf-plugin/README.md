# jpcite — マネーフォワード クラウド アプリポータル plugin

マネーフォワード クラウド (MF Cloud) のアプリポータル / アプリストア向け
公開アプリ実装。`jpcite.com` の REST API をプロキシし、MF クラウドの
ユーザー (会計 / 請求書 / 給与 / 経費 / 人事労務) が補助金・税制優遇・法令・
判例・インボイス登録番号を MF 画面内のポップアップから検索できるようにする。

```
MF クラウド (https://*.biz.moneyforward.com)
        │ <iframe src="https://mf-plugin.jpcite.com/static/index.html">
        ▼
このプラグイン (Fly.io HND, Python 3.11 + FastAPI)
        │ OAuth2 (mfc/ac/data.read scope) → 事業者名 + tenant_uid を session
        │ X-API-Key: jpcite_live_... (Bookyou 所有のサービスキー)
        ▼
api.jpcite.com (¥3.30/req metered subscription)
```

## アーキテクチャ要点

- **MF の OAuth は事業者単位 (tenant)**、個人ユーザー単位ではない。session には
  tenant_uid と事業者名のみ保持し、個人を特定する情報は持たない。
- **scope は最小限**: `mfc/ac/data.read` (会計) のみ。書込み権限は要求しない。
  検索クエリの都道府県フィルタ用に基本情報を 1 回読むだけ。
- **¥3/req fully metered**: plugin 自体は無料で利用可能。課金は jpcite.com
  API 側で 1 req = ¥3.30 (税込) の従量で発生し、Bookyou 株式会社が Stripe 経由で
  適格請求書として発行。MF の利用者に直接課金は行わない (Bookyou の
  marketplace_app_subscription に対して計上)。
- **Solo + zero-touch**: 電話サポート無し / 営業電話無し / 100% self-serve。

## 構成

| ファイル | 役割 |
|---|---|
| `oauth_callback.py` | MF OAuth2 (authorization_code grant) フロー — `/oauth/{authorize,callback,logout}` |
| `proxy_endpoints.py` | `/mf-plugin/{search-tax-incentives,search-subsidies,check-invoice-registrant,search-laws,search-court-decisions}` プロキシ |
| `app.py` | FastAPI エントリ。CSP `frame-ancestors` を MF ホスト群に限定 |
| `config.py` | env 検証 + MF OAuth エンドポイント定数 (起動時 fail-fast) |
| `frontend/index.html` | MF iframe 内ポップアップ UI (vanilla HTML) |
| `frontend/styles.css` | CSS (約 720×900 の iframe を想定) |
| `frontend/app.js` | tab 切替 + フォーム送信 + render |
| `submission/manifest.json` | MF アプリポータル 提出メタデータ |
| `submission/copy/description.ja.md` | 日本語コピー (説明文 1 段落 + 3 bullet + ユースケース) |
| `submission/copy/scope_justification.ja.md` | scope 取得理由 (read のみ・取得しない情報の明示) |
| `submission/copy/review_demo_walkthrough.ja.md` | 審査担当者向けウォークスルー |
| `submission/screenshots/icon-512x512.png` | アイコン (placeholder。実 logo は user 提供必要) |
| `submission/screenshots/01..05.png` | ハイライト 1200×630 PNG (placeholder) |
| `requirements.txt` | Python 依存 (fastapi, uvicorn, httpx, itsdangerous, pydantic) |
| `Dockerfile` / `fly.toml` | Fly.io HND デプロイ |
| `tests/test_oauth_state.py` | OAuth state CSRF + env 検証 smoke test |
| `tests/test_proxy.py` | 認可チェック / x-api-key 転送 / secrets 漏洩防止 |
| `SUBMISSION_CHECKLIST.md` | 提出までの完了状態と user アクション一覧 |

## 開発

```bash
cd sdk/mf-plugin
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env  # 値を埋める
.venv/bin/uvicorn app:app --reload --port 8080
```

## テスト

```bash
.venv/bin/python -m pytest tests/ -x
```

ネットワーク呼び出しは `httpx.MockTransport` で全モック化。実 MF / 実 jpcite
は叩かない。

## デプロイ (Fly.io)

```bash
fly launch --no-deploy --copy-config --name jpcite-mf-plugin
fly secrets set \
  MF_CLIENT_ID=...                                  \
  MF_CLIENT_SECRET=...                              \
  JPCITE_API_KEY=jpcite_live_...                    \
  JPCITE_API_BASE=https://api.jpcite.com             \
  SESSION_SECRET=$(openssl rand -hex 32)            \
  PLUGIN_BASE_URL=https://mf-plugin.jpcite.com
fly deploy
```

> 旧 `ZEIMU_KAIKEI_API_KEY` / `ZEIMU_KAIKEI_BASE_URL` も `config.py` で
> エイリアスとして受け付けるため、既存 secrets を即時差し替えなくても
> 起動自体は通る。新規セットアップでは `JPCITE_*` 名で統一する。

## 課金モデル (シンプル従量)

- 1 req = ¥3.30 (税込) の **完全従量**。tier / Pro / Free / 固定月額 plan は **存在しない**。
- 匿名 (未認証) は IP 単位で 1 日 3 リクエストまで無料。JST 翌日 00:00 リセット。
- 利用量は Stripe の metered usage と jpcite 側の usage ledger で突合する。
- 請求は Bookyou株式会社 (T8010001213708) が Stripe 経由で 適格請求書として発行。

## 競合との並走運用

このプラグインは **MF クラウドの税理士向け顧問サービス** や
**TKC モバイル業務支援 / freee 顧問サービス** と **競合せず並走** する設計:

- MF / TKC / freee 顧問サービスは「会計データ集計 + 申告連動」が主目的。
- jpcite は「補助金・税制優遇・法令・判例・インボイス公表情報の一次出典付き
  検索」のみ。仕訳・元帳・取引明細には touch しない (`mfc/ac/data.read` のみ)。
- 税理士は両方を併用することで、月次決算 (MF/TKC/freee) と
  制度案内 (jpcite) を分離できる。

## 提出

`submission/` 配下を MF アプリポータル (https://app.biz.moneyforward.com/app-portal/)
にアップロード。詳細は `SUBMISSION_CHECKLIST.md` を参照。

## go-live (人手が必要なステップ)

1. Fly.io デプロイ: 上記 `fly launch` + `fly deploy`
2. Cloudflare DNS: `mf-plugin.jpcite.com` の A/AAAA を Fly に向ける
3. MF アプリポータル登録: https://app.biz.moneyforward.com/app-portal/
   で公開アプリを作成、`client_id` / `client_secret` を取得
4. redirect_uri を `https://mf-plugin.jpcite.com/oauth/callback` で登録
5. アイコン (512×512) + ハイライト (1200×630 PNG ×5) を実環境キャプチャに差し替え
6. 提出フォームに `submission/manifest.json` の値を入力 → submit

詳細な go-live readiness は
`analysis_wave18/mf_plugin_golive_2026-05-01.md` を参照。

## 制約 (緩めない)

- **座席課金禁止** (per-request ¥3.30 のみ)
- **税理士法 §52 免責**: UI フッターに常時表示 + 全 API レスポンスに
  `_disclaimer` フィールド同梱
- **MF の事業者単位認可** を尊重し、個人ユーザーの行動ログは取らない
