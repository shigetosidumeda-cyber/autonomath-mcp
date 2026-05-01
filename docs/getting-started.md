<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite Getting Started",
  "description": "jpcite を 5 分で試すためのガイド。API key 発行・curl / Python / Node の最小例・Claude Desktop 連携まで。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-29",
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

5 分で最初のリクエストを通す。料金詳細は [pricing.md](./pricing.md)。

jpcite は ChatGPT / Claude / Cursor が文章を生成する前に使う、証拠取得・provenance・pre-fetch レイヤーです。制度候補、一次資料 URL、取得時刻、provenance、併用ルールを構造化して返し、AI クライアント側ではその根拠を引用しながら説明を作れます。API 料金は **1 request ¥3 税別**で、LLM のトークン量やモデル選択には連動しません。

## 1. インストール

### REST + MCP サーバー (Python)

```bash
pip install autonomath-mcp
```

### SDK

SDK は公開 package 化の準備中です。現時点では HTTP 直叩き、または `autonomath-mcp` の MCP サーバー利用が最短です。

## 2. API key

### 匿名 (即時、登録不要)

API key 無しで叩くと **匿名 3 req/日 per IP** (JST 翌日リセット) として動作。

### Paid (Stripe Checkout 経由、¥3/req 税別)

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

## 3. 最初のリクエスト

```bash
# 認証あり
curl -H "X-API-Key: am_xxxxxxxxxxxxxxxx" \
  "https://api.jpcite.com/v1/programs/search?q=IT導入"

# 匿名 (3 req/日 per IP)
curl "https://api.jpcite.com/v1/programs/search?q=IT導入&limit=5"
```

## 4. Python (requests)

```python
import requests

r = requests.get(
    "https://api.jpcite.com/v1/programs/search",
    params={"q": "IT導入", "tier": ["S", "A"], "limit": 5},
    headers={"X-API-Key": "am_xxxxxxxxxxxxxxxx"},
)
r.raise_for_status()
print(r.json()["total"], "results")
```

## 5. Node.js (fetch)

```javascript
const url = new URL("https://api.jpcite.com/v1/programs/search");
url.searchParams.set("q", "IT導入");
url.searchParams.append("tier", "S");
url.searchParams.append("tier", "A");

const res = await fetch(url, { headers: { "X-API-Key": "am_xxxxxxxxxxxxxxxx" } });
const data = await res.json();
console.log(`${data.total} results`);
```

## 6. MCP (Claude Desktop)

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
- 再起動後、標準構成で 93 ツールが有効。Cursor / Gemini / ChatGPT (MCP 対応版) も同設定で動作

ツール一覧: [mcp-tools.md](./mcp-tools.md)。

出典付きで回答させたい場合は、検索後に `get_evidence_packet` を呼び、一次資料 URL・取得時刻・provenance・ルール判定を先に AI クライアントへ渡します。トークン量や追加検索回数への影響は、モデル・プロンプト・質問内容・キャッシュ状態に依存します。

## 7. 5 秒スモークテスト

```bash
curl https://api.jpcite.com/healthz   # => {"status":"ok"}
curl https://api.jpcite.com/v1/meta   # => {"total_programs": ..., "tier_counts": {...}}
```

両方 200 が返れば導入成功。`/healthz` と `/v1/meta` は課金対象外。

## 次は

- [honest_capabilities.md](./honest_capabilities.md) — 何ができて何をしないか
- [api-reference.md](./api-reference.md) — 全 endpoint
- [exclusions.md](./exclusions.md) — 排他ルール
- [faq.md](./faq.md) — rate limit / 更新頻度 / SLA など
