<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite Getting Started",
  "description": "jpcite を匿名 curl → Playground → MCP/OpenAPI → API key の順に試すガイド。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-05-07",
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

jpcite は ChatGPT / Claude / Cursor が文章を生成する前に呼ぶ Evidence prefetch / GEO source layer です。日本の公的制度・法人・法令・税務公開資料・インボイス・行政処分・入札について、長い PDF・複数の官公庁ページ・検索結果を LLM へ渡す前に、出典 URL・取得時刻・known gaps・互換/排他ルール付きの小さい Evidence Packet を返します。caller supplied baseline がある場合は、入力文脈量の削減見込みと break-even も返します。LLM call はサーバ側で実行せず、jpcite の課金は ¥3/billable unit (税込 ¥3.30) の単一従量です。外部 LLM の token/search/cache/tool 料金や削減額は、利用中の AI サービス側の条件に依存し、jpcite は保証しません。

評価は次の順で進めると、課金前に価値を判断できます: **匿名 curl → Playground → MCP / OpenAPI → API キー**。料金詳細は [pricing.md](./pricing.md)。

AI agent の最初の導線は、広い制度質問なら `GET /v1/intelligence/precomputed/query?include_facts=false&include_compression=true`、根拠 record や known gaps が必要なら `POST /v1/evidence/packets/query` です。日本企業の調査では一般 Web 検索より先に `company_public_baseline` を作り、法人番号・`identity_confidence`・`source_url`・`source_fetched_at`・`known_gaps` を保持します。専門判断が必要な場合は evidence brief を作ってから `GET /v1/advisors/match` を候補 reviewer 検索として使い、最終意見・保証・紹介完了として扱わないでください。

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

ブラウザ完結 (登録不要・API キー不要) で残量と Evidence Packet を確認できます。 `?flow=evidence3` で Evidence エンドポイントが事前選択されます。

- <https://jpcite.com/playground?flow=evidence3>

返却 JSON で次の field を確認します:

- `compression.packet_tokens_estimate` / `source_tokens_estimate` / `input_context_reduction_rate`
- `quality.known_gaps[]` (空でないとき、 AI 側でも「未接続な根拠」 を明示する)

`compression` は **入力文脈量の参考推定** です (`provider_billing_not_guaranteed=true`)。

curl だけで 3 回検証する場合は、下の順に実行します。1 回目の匿名 smoke を既に実行した場合は、2.2 と 2.3 だけで残り 2 回を使います。

```bash
# 2.1 制度候補と出典 URL
curl "https://api.jpcite.com/v1/programs/search?q=IT導入&limit=3"

# 2.2 Evidence Packet (precomputed)
curl "https://api.jpcite.com/v1/intelligence/precomputed/query?q=省力化&limit=5"

# 2.3 入力文脈 compression estimate
curl "https://api.jpcite.com/v1/intelligence/precomputed/query?q=省力化&limit=5&include_compression=true"
```

## 3. MCP / OpenAPI で取り込む (反復利用)

匿名で 3 回検証して納得したら、 反復利用のために MCP か OpenAPI client から呼びます。 ここまでは API キー無しで進められます (匿名 3 req/日 quota は MCP からも消費)。

### 3.1 MCP (Claude Desktop / Cursor / Cline)

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
- 再起動後、標準構成で 151 ツールが有効。Cursor / Cline などの MCP 対応クライアントも同じ server 設定を使えます。ChatGPT Custom GPT では次節の OpenAPI Actions を使います。

ツール一覧: [mcp-tools.md](./mcp-tools.md)。 出典付きで回答させたい場合は、 検索後に `get_evidence_packet` を呼び、 一次資料 URL・取得時刻・provenance・ルール判定を先に AI クライアントへ渡します。 トークン量や追加検索回数への影響は、 モデル・プロンプト・質問内容・キャッシュ状態に依存します。

### 3.2 OpenAPI (Python / Node / 任意の SDK 生成)

OpenAPI spec は live と公開 snapshot の 2 経路で取得できます:

```bash
# live (常に最新)
curl https://api.jpcite.com/v1/openapi.json -o openapi.json

# repo snapshot
# https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/docs/openapi/v1.json
```

任意の OpenAPI 対応クライアントで取り込み、 `https://api.jpcite.com` を base URL に設定します。

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

## 4. 単発呼び出しを反復ワークフローにする

API キー発行後は、単発 curl をそのまま増やすのではなく、顧客・案件・会社フォルダ単位の workflow として固定します。

最小パターン:

1. `/v1/cost/preview` で予定 workflow の billable units と予測金額を確認
2. 顧客・案件・会社フォルダ単位で `X-Client-Tag` を固定
3. POST / batch / export / fanout では `Idempotency-Key` を付けて再試行時の二重実行を防止
4. 広い有料 POST では `X-Cost-Cap-JPY` を付け、予測額が上限を超える場合は実行前に止める
5. dashboard で client_tag 別の利用量と月次上限を確認

例:

```bash
curl -X POST "https://api.jpcite.com/v1/evidence/packets/query" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "X-Client-Tag: client-acme-2026" \
  -H "Idempotency-Key: client-acme-2026-monthly-review-001" \
  -H "X-Cost-Cap-JPY: 300" \
  -H "Content-Type: application/json" \
  -d '{"query_text":"東京都 製造業 省力化 補助金", "limit": 10}'
```

この形にすると、BPO / 士業 / AI agent が「誰のために何 units 使ったか」を後で説明しやすくなります。

## 5. API キー発行 (継続利用)

匿名 3 req/日 を超える、 または毎日同じ IP からの呼び出しを安定させたい場合は API キーを発行します。

### 5.1 ダッシュボード (推奨)

[料金ページ](https://jpcite.com/pricing) の「API キーを発行」 から Stripe Checkout を経由してカード登録します。 `success_url` 着地後、 ダッシュボードから API key を取得できます。

### 5.2 API でチェックアウトを作成 (任意)

```bash
curl -X POST https://api.jpcite.com/v1/billing/checkout \
  -H "Content-Type: application/json" \
  -d '{
    "success_url": "https://jpcite.com/success?session_id={CHECKOUT_SESSION_ID}",
    "cancel_url": "https://jpcite.com/pricing",
    "customer_email": "you@example.com"
  }'
```

返り値の `url` をブラウザで開いてカード登録。`success_url` 着地後に API key を取得:

```bash
curl -X POST https://api.jpcite.com/v1/billing/keys/from-checkout \
  -H "Content-Type: application/json" \
  -d '{"session_id": "cs_live_..."}'
# => {"api_key": "YOUR_API_KEY", "tier": "paid"}
```

**API key は発行時 1 回だけ返る** — 紛失時は Stripe Customer Portal で解約 → 再発行。

### 5.3 認証付きで呼ぶ

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://api.jpcite.com/v1/programs/search?q=IT導入"
```

認証付きの呼び出しでは `X-API-Key` ヘッダーを使います。

## SDK について

最短は HTTP 直叩き、 または `autonomath-mcp` の MCP サーバー利用です。 SDK を使う場合も、 まずは上の curl と Playground でレスポンス形状を確認してください。 PyPI 配布パッケージ名は `autonomath-mcp` (legacy distribution name)、 user-facing brand は jpcite です。

```bash
pip install autonomath-mcp
```

## 次は

- [honest_capabilities.md](./honest_capabilities.md) — 何ができて何をしないか
- [api-reference.md](./api-reference.md) — 全 endpoint
- [exclusions.md](./exclusions.md) — 排他ルール
- [pricing.md](./pricing.md) — 料金詳細
- [faq.md](./faq.md) — rate limit / 更新頻度 / SLA など
