# 税務会計AI — freee 会計 marketplace plugin

freee アプリストア向けの 公開 (public) アプリ実装。`zeimu-kaikei.ai` の REST API
をプロキシし、freee 会計のユーザーが補助金・税制優遇・インボイス登録番号を
freee 画面内のポップアップから検索できるようにする。

```
freee 会計 (https://app.secure.freee.co.jp)
        │ <iframe src="https://freee-plugin.zeimu-kaikei.ai/static/index.html">
        ▼
このプラグイン (Fly.io HND, Node 20)
        │ OAuth2 (read scope) → 事業所名 + 法人番号 を session に保管
        │ X-API-Key: zk_live_... (Bookyou 所有のサービスキー)
        ▼
api.zeimu-kaikei.ai (¥3.30/req metered subscription)
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
fly launch --no-deploy --copy-config --name zeimu-kaikei-freee-plugin
fly secrets set \
  FREEE_CLIENT_ID=...                               \
  FREEE_CLIENT_SECRET=...                           \
  ZEIMU_KAIKEI_API_KEY=zk_live_...                  \
  SESSION_SECRET=$(openssl rand -hex 32)            \
  PLUGIN_BASE_URL=https://freee-plugin.zeimu-kaikei.ai
fly deploy
```

## 制約 (緩めない)

- **LLM 推論禁止**: このプロセスから Anthropic / OpenAI を呼ばない。プラグインは
  単なるプロキシ + UI。推論は顧客側 (Claude Desktop 等) が行う。
- **座席課金禁止**: per-request ¥3.30 (税込) のみ。Pro / Free 等の tier は無し。
- **税理士法 §52 免責**: UI フッターに常時表示 + 全 API レスポンスに
  `_disclaimer` フィールド同梱。

## 申請

`submission/` 配下を freee 開発者ポータルにアップロード。詳細は
`SUBMISSION_CHECKLIST.md` を参照。
