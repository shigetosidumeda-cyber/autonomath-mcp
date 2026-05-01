# jpcite — freee 会計 marketplace plugin

freee アプリストア向けの 公開 (public) アプリ実装。`jpcite.com` の REST API
をプロキシし、freee 会計のユーザーが補助金・税制優遇・インボイス登録番号を
freee 画面内のポップアップから検索できるようにする。

```
freee 会計 (https://app.secure.freee.co.jp)
        │ <iframe src="https://freee-plugin.jpcite.com/static/index.html">
        ▼
このプラグイン (Fly.io HND, Node 20)
        │ OAuth2 (read scope) → 事業所名 + 法人番号 を session に保管
        │ X-API-Key: am_live_... (Bookyou 所有のサービスキー)
        ▼
api.jpcite.com (¥3.30/req metered subscription)
```

## 構成

| ファイル | 役割 |
|---|---|
| `src/server.js` | Express エントリ、helmet + CSP frame-ancestors freee.co.jp |
| `src/lib/env.js` | env 検証 (起動時 fail-fast) + freee OAuth エンドポイント定数 |
| `src/routes/oauth.js` | freee OAuth2 (authorization_code) — `/oauth/{authorize,callback,logout}` |
| `src/routes/search.js` | `/freee-plugin/{search-tax-incentives,search-subsidies,check-invoice-registrant}` プロキシ |
| `src/routes/health.js` | `/healthz` (Fly.io probe) |
| `src/public/index.html` | freee iframe 内ポップアップ UI (vanilla HTML) |
| `src/public/styles.css` | CSS (約 720×900 の iframe を想定) |
| `src/public/app.js` | tab 切替 + フォーム送信 + render |
| `Dockerfile` / `fly.toml` | Fly.io HND デプロイ |
| `test/oauth_state.test.js` | env 検証 + OAuth 定数の smoke test |
| `test/proxy_logic.test.js` | 認可チェック / x-api-key 転送 / secrets 漏洩防止 |
| `submission/manifest.json` | freee アプリストア提出メタデータ |
| `submission/copy/*.md` | 日本語コピー (説明文・scope 理由・審査ウォークスルー) |
| `submission/screenshots/*.png` | アイコン (640×640) + ハイライト (1200×630) ×5 |

## 開発

```bash
cd sdk/freee-plugin/marketplace
cp .env.example .env  # 値を埋める
npm install
npm run dev           # node --watch src/server.js
```

## テスト

```bash
npm test
```

`node --test`. ネットワーク呼び出しは `globalThis.fetch` を差し替えてモック。
9 ケース (env 検証 6 + 認可 + プロキシヘッダ + インボイス番号正規化)。

## デプロイ (Fly.io)

```bash
fly launch --no-deploy --copy-config --name jpcite-freee-plugin
fly secrets set \
  FREEE_CLIENT_ID=...                               \
  FREEE_CLIENT_SECRET=...                           \
  JPCITE_API_KEY=am_live_...                        \
  SESSION_SECRET=$(openssl rand -hex 32)            \
  PLUGIN_BASE_URL=https://freee-plugin.jpcite.com
fly deploy
```

> 旧 `ZEIMU_KAIKEI_API_KEY` / `ZEIMU_KAIKEI_API_BASE` も `lib/env.js` で
> エイリアスとして受け付けるため、既存 secrets を即時差し替えなくても起動
> 自体は通る。新規セットアップでは `JPCITE_*` 名で統一する。

## 課金モデル (シンプル従量)

- 1 req = ¥3.30 (税込) の **完全従量**。tier / Pro / Free / 月 ¥10,000 plan は **存在しない**。
- 匿名 (未認証) は IP 単位で 1 日 3 リクエストまで無料。JST 翌日 00:00 リセット。
- 利用量は Stripe の metered usage と jpcite 側の usage ledger で突合する。
- 請求は Bookyou株式会社 (T8010001213708) が Stripe 経由で 適格請求書として発行。

## 競合との並走運用

このプラグインは **TKC モバイル業務支援** や **freee 顧問サービス** と
**競合せず並走** する設計:

- TKC / freee 顧問サービスは「会計データ集計 + 申告連動」が主目的。
- jpcite は「補助金・税制優遇・法令・判例・インボイス公表情報の一次出典付き
  検索」のみ。会計データには touch しない (read scope のみ)。
- 税理士は両方を併用することで、月次決算 (TKC/freee) と 制度案内 (jpcite)
  を分離できる。

## 制約 (緩めない)

- **LLM 推論禁止**: このプロセスから Anthropic / OpenAI を呼ばない。プラグインは
  単なるプロキシ + UI。推論は顧客側 (Claude Desktop 等) が行う。
- **座席課金禁止**: per-request ¥3.30 (税込) のみ。Pro / Free 等の tier は無し。
- **税理士法 §52 免責**: UI フッターに常時表示 + 全 API レスポンスに
  `_disclaimer` フィールド同梱。

## 申請

`submission/` 配下を freee 開発者ポータルにアップロード。詳細は
`SUBMISSION_CHECKLIST.md` を参照。

## go-live (人手が必要なステップ)

1. Fly.io デプロイ: 上記 `fly launch` + `fly deploy`
2. Cloudflare DNS: `freee-plugin.jpcite.com` の A/AAAA を Fly に向ける
3. freee 開発者ポータル登録: https://app.secure.freee.co.jp/developers/applications
   で公開アプリを作成、`client_id` / `client_secret` を取得
4. redirect_uri を `https://freee-plugin.jpcite.com/oauth/callback` で登録
5. アイコン (640×640) + ハイライト (1200×630 PNG ×5) を実環境キャプチャに差し替え
6. 提出フォームに `submission/manifest.json` の値を入力 → submit

詳細な go-live readiness は
`analysis_wave18/freee_plugin_golive_2026-05-01.md` を参照。
