<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite Getting Started",
  "description": "jpcite を匿名 curl → Playground → MCP/OpenAPI → API key の順に試すガイド。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-05-03",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "jpcite",
    "url": "https://jpcite.com/"
  },
  "publisher": {
    "@type": "Organization",
    "name": "jpcite",
    "logo": {
      "@type": "ImageObject",
      "url": "https://jpcite.com/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://jpcite.com/docs/getting-started/"
  }
}
</script>

# Getting Started

jpcite は ChatGPT / Claude / Cursor が文章を生成する前に呼ぶ Evidence prefetch layer です。 長い PDF・複数の官公庁ページ・検索結果を LLM へ渡す前に、 出典 URL・取得時刻・known gaps・互換/排他ルール付きの小さい Evidence Packet を返します。 caller supplied baseline がある場合だけ、 入力文脈量の削減見込みと break-even を返します。 外部 LLM の請求額削減は保証しません。 LLM call はサーバ側で実行せず、 jpcite の課金は ¥3/req (税込 ¥3.30) の単一従量、 LLM トークン量やモデル選択には連動しません。

評価は次の順で進めると、課金前に価値を判断できます: **匿名 curl → Playground → MCP / OpenAPI → API キー**。料金詳細は [pricing.md](./pricing.md)。

## 1. 匿名 curl で 5 秒スモーク (登録不要)

API キー無しで叩くと **匿名 3 req/日 per IP** (JST 翌日 00:00 リセット) として動作します。 `/healthz` と `/v1/meta` は **課金対象外**。

```bash
# 1.1 ヘルスチェック (課金対象外)
curl https://api.jpcite.com/healthz   # => {"status":"ok"}
curl https://api.jpcite.com/v1/meta   # => {"total_programs": ..., "tier_counts": {...}}

# 1.2 制度検索 — 匿名枠 1 リクエストを消費
curl "https://api.jpcite.com/v1/programs/search?q=IT導入&limit=5"
```

返ってくる record の `source_url` が省庁・自治体・公庫の一次資料に直リンクしていることと、 `source_fetched_at` (jpcite が出典を最後に取得した時刻) が付いていることを確認します。

## 2. Playground で Evidence Packet を確認する

ブラウザ完結 (登録不要・API キー不要) で残量と Evidence Packet を確認できます。 `?flow=evidence3` で Evidence エンドポイントが事前選択され、 `source_tokens_basis=pdf_pages` · `source_pdf_pages=30` · `input_token_price_jpy_per_1m=300` がデフォルト入力されます。

- <https://jpcite.com/playground.html?flow=evidence3>

返却 JSON で次の field を確認します:

- `compression.packet_tokens_estimate` / `source_tokens_estimate` / `input_context_reduction_rate`
- `compression.cost_savings_estimate.break_even_met` (caller baseline がある時のみ true / false が出る)
- `agent_recommendation.recommend_for_cost_savings` (条件付き)
- `agent_recommendation.cost_savings_decision` (`supported_by_caller_baseline` または `needs_caller_baseline`)
- `quality.known_gaps[]` (空でないとき、 AI 側でも「未接続な根拠」 を明示する)

`compression` は **入力文脈量だけの参考推定** で、 外部 LLM の請求額削減は保証しません (`provider_billing_not_guaranteed=true`)。

curl だけで 3 回検証する場合は、下の順に実行します。1 回目の匿名 smoke を既に実行した場合は、2.2 と 2.3 だけで残り 2 回を使います。

```bash
# 2.1 制度候補と出典 URL
curl "https://api.jpcite.com/v1/programs/search?q=IT導入&limit=3"

# 2.2 Evidence Packet (precomputed)
curl "https://api.jpcite.com/v1/intelligence/precomputed/query?q=省力化&limit=5"

# 2.3 入力文脈 compression estimate + break_even_met
curl "https://api.jpcite.com/v1/intelligence/precomputed/query?q=省力化&limit=5&source_tokens_basis=pdf_pages&source_pdf_pages=30&input_token_price_jpy_per_1m=300"
```

## 3. MCP / OpenAPI で取り込む (反復利用)

匿名で 3 回検証して納得したら、 反復利用のために MCP か OpenAPI client から呼びます。 ここまでは API キー無しで進められます (匿名 3 req/日 quota は MCP からも消費)。

### 3.1 MCP (Claude Desktop / Cursor / Cline / ChatGPT MCP 対応版)

Protocol: `2025-06-18`。`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) を編集:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

- `uv` 未導入なら `brew install uv` か `pip install uv`
- `pip install autonomath-mcp` 済みなら `"command": "autonomath-mcp"`
- ワンクリック: [jpcite MCP bundle](/downloads/autonomath-mcp.mcpb) を Claude Desktop で開く
- 再起動後、 標準構成で 93 ツールが有効。 Cursor / Gemini / ChatGPT (MCP 対応版) も同設定で動作

ツール一覧: [mcp-tools.md](./mcp-tools.md)。 出典付きで回答させたい場合は、 検索後に `get_evidence_packet` を呼び、 一次資料 URL・取得時刻・provenance・ルール判定を先に AI クライアントへ渡します。 トークン量や追加検索回数への影響は、 モデル・プロンプト・質問内容・キャッシュ状態に依存します。

### 3.2 OpenAPI (Python / Node / 任意の SDK 生成)

OpenAPI spec は live と committed snapshot の 2 経路で取得できます:

```bash
# live (常に最新)
curl https://api.jpcite.com/v1/openapi.json -o openapi.json

# repo snapshot
# https://github.com/.../blob/main/docs/openapi/v1.json
```

任意の OpenAPI generator で client を生成し、 `https://api.jpcite.com` を base URL に設定します。

### 3.3 Python (requests)

```python
import requests

r = requests.get(
    "https://api.jpcite.com/v1/programs/search",
    params={"q": "IT導入", "tier": ["S", "A"], "limit": 5},
)
r.raise_for_status()
print(r.json()["total"], "results")
```

### 3.4 Node.js (fetch)

```javascript
const url = new URL("https://api.jpcite.com/v1/programs/search");
url.searchParams.set("q", "IT導入");
url.searchParams.append("tier", "S");
url.searchParams.append("tier", "A");

const res = await fetch(url);
const data = await res.json();
console.log(`${data.total} results`);
```

## 4. API キー発行 (継続利用)

匿名 3 req/日 を超える、 または毎日同じ IP からの呼び出しを安定させたい場合は API キーを発行します。

### 4.1 ダッシュボード (推奨)

[料金ページ](https://jpcite.com/pricing.html) の「API キーを発行」 から Stripe Checkout を経由してカード登録します。 `success_url` 着地後、 ダッシュボードから API key を取得できます。

### 4.2 API でチェックアウトを作成 (任意)

```bash
curl -X POST https://api.jpcite.com/v1/billing/checkout \
  -H "Content-Type: application/json" \
  -d '{
    "success_url": "https://jpcite.com/success.html?session_id={CHECKOUT_SESSION_ID}",
    "cancel_url": "https://jpcite.com/pricing.html",
    "customer_email": "you@example.com"
  }'
```

返り値の `url` をブラウザで開いてカード登録。`success_url` 着地後に API key を取得:

```bash
curl -X POST https://api.jpcite.com/v1/billing/keys/from-checkout \
  -H "Content-Type: application/json" \
  -d '{"session_id": "cs_live_..."}'
# => {"api_key": "am_xxxxxxxxxxxxxxxx", "tier": "paid"}
```

**API key は発行時 1 回だけ返る** — 紛失時は Stripe Customer Portal で解約 → 再発行。

### 4.3 認証付きで呼ぶ

```bash
curl -H "X-API-Key: am_xxxxxxxxxxxxxxxx" \
  "https://api.jpcite.com/v1/programs/search?q=IT導入"
```

`X-API-Key` または `Authorization: Bearer am_...` のどちらでも受け付けます。

## SDK について

最短は HTTP 直叩き、 または `autonomath-mcp` の MCP サーバー利用です。 SDK を使う場合も、 まずは上の curl と Playground でレスポンス形状を確認してください。 PyPI 配布パッケージ名は `autonomath-mcp` (legacy distribution name)、 user-facing brand は jpcite です。

```bash
pip install autonomath-mcp
```

## 次は

- [honest_capabilities.md](./honest_capabilities.md) — 何ができて何をしないか
- [api-reference.md](./api-reference.md) — 全 endpoint
- [exclusions.md](./exclusions.md) — 排他ルール
- [pricing.md](./pricing.md) — 料金詳細と `break_even_met` の正しい読み方
- [faq.md](./faq.md) — rate limit / 更新頻度 / SLA など
