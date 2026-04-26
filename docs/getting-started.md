<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "AutonoMath Getting Started",
  "description": "AutonoMath を 5 分で試すためのガイド。API key 発行・curl / Python / Node の最小例・Claude Desktop 連携まで。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://autonomath.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://autonomath.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://autonomath.ai/docs/getting-started/"
  }
}
</script>

# Getting Started

> **要約 (summary):** AutonoMath を 5 分で試すためのガイド。API key 発行・curl / Python / Node の最小例・Claude Desktop 連携まで。

## 1. インストール (Install)

### Python (REST + MCP server)

```bash
pip install autonomath-mcp
```

### SDK (pre-release)

SDK は PyPI / npm にはまだ publish していない。git から直接インストールする:

```bash
# Python SDK (package 名は歴史的に `jpintel`、service 名は AutonoMath)
pip install "git+https://github.com/AutonoMath/autonomath-mcp#subdirectory=sdk/python"

# TypeScript SDK
npm install "github:AutonoMath/autonomath-mcp#main" --prefix ./sdk/typescript
```

PyPI / npm への公開は launch 後。それまでは直接 HTTP を叩くか、`autonomath-mcp` の MCP server を利用。

## 2. API key を取得する (Get an API key)

### Free (即時発行)

API key 未設定でリクエストを送ると自動的に **匿名 Free (50 req/月 per IP、JST 月初 00:00 リセット)** 扱いになる。以下の `curl` がそのまま動く。

50 req/月を超えて使いたければ Stripe Checkout でカードを登録する。

### Paid (Stripe 経由、¥3/req 税別・税込 ¥3.30 従量)

```bash
curl -X POST https://api.autonomath.ai/v1/billing/checkout \
  -H "Content-Type: application/json" \
  -d '{
    "success_url": "https://autonomath.ai/success.html?session_id={CHECKOUT_SESSION_ID}",
    "cancel_url": "https://autonomath.ai/pricing.html",
    "customer_email": "you@example.com"
  }'
```

返り値の `url` にブラウザで飛ぶと Stripe Checkout。カード登録完了後、`success_url?session_id=...` が返る。landing 側を使うなら `https://autonomath.ai/success.html?session_id=...` (API key 自動発行 + curl snippet 表示) で終わる。自前の UI から叩くなら:

```bash
curl -X POST https://api.autonomath.ai/v1/billing/keys/from-checkout \
  -H "Content-Type: application/json" \
  -d '{"session_id": "cs_live_..."}'
# => {"api_key": "am_xxxxxxxxxxxxxxxx", "tier": "paid", "customer_id": "cus_..."}
```

**API key は発行時 1 回だけ返る** — 保存し忘れると `/v1/billing/portal` でサブスクリプション解約後、再発行する必要がある。

詳細は [pricing.md](./pricing.md) と [api-reference.md#billing](./api-reference.md#billing) 参照。

## 3. 最初のリクエスト (curl)

```bash
curl -H "X-API-Key: am_xxxxxxxxxxxxxxxx" \
  "https://api.autonomath.ai/v1/programs/search?q=IT導入"
```

API key 無しでも動く (匿名 Free、50 req/月 per IP):

```bash
curl "https://api.autonomath.ai/v1/programs/search?q=IT導入&limit=5"
```

## 4. Python 例 (requests, stdlib のみ)

```python
import requests

API_KEY = "am_xxxxxxxxxxxxxxxx"
BASE = "https://api.autonomath.ai"

r = requests.get(
    f"{BASE}/v1/programs/search",
    params={"q": "IT導入", "tier": ["S", "A"], "limit": 5},
    headers={"X-API-Key": API_KEY},
)
r.raise_for_status()
print(r.json()["total"], "results")
```

## 5. Node.js 例 (fetch)

```javascript
const API_KEY = "am_xxxxxxxxxxxxxxxx";
const BASE = "https://api.autonomath.ai";

const url = new URL(`${BASE}/v1/programs/search`);
url.searchParams.set("q", "IT導入");
url.searchParams.append("tier", "S");
url.searchParams.append("tier", "A");

const res = await fetch(url, { headers: { "X-API-Key": API_KEY } });
const data = await res.json();
console.log(`${data.total} results`);
```

## 6. MCP (Claude Desktop) 設定

MCP protocol: `2025-06-18`。推奨は `uvx` 経由 (venv 不要、起動時に最新版へ自動更新)。`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) を編集:

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

- `uv` 未導入なら `brew install uv` か `pip install uv`
- `pip install autonomath-mcp` した場合は `"command": "autonomath-mcp"`
- ワンクリック: [autonomath-mcp.mcpb](/downloads/autonomath-mcp.mcpb) をダウンロードして Claude Desktop で開く
- 再起動後、72 tools が有効 (38 コア + 28 autonomath = 17 V1 + 4 V4 universal + 7 Phase A absorption)。38 コアは `search_programs`, `get_program`, `batch_get_programs`, `search_case_studies`, `get_case_study`, `search_loan_programs`, `get_loan_program`, `search_enforcement_cases`, `get_enforcement_case`, `list_exclusion_rules`, `check_exclusions`, `get_meta`, `enum_values`, `prescreen_programs`, `upcoming_deadlines`, `smb_starter_pack`, `subsidy_combo_finder`, `deadline_calendar`, `dd_profile_am`, `similar_cases`, `regulatory_prep_pack`, `subsidy_roadmap_3yr`, `search_laws`, `get_law`, `list_law_revisions`, `search_court_decisions`, `get_court_decision`, `find_precedents_by_statute`, `search_bids`, `get_bid`, `bid_eligible_for_profile`, `search_tax_rules`, `get_tax_rule`, `evaluate_tax_applicability`, `search_invoice_registrants`, `trace_program_to_law`, `find_cases_by_law`, `combined_compliance_check` (詳細は [mcp-tools.md](./mcp-tools.md))。28 autonomath (entity-fact DB) は 17 V1: `search_tax_incentives`, `search_certifications`, `list_open_programs`, `enum_values_am`, `search_by_law`, `active_programs_at`, `related_programs`, `search_acceptance_stats_am`, `intent_of`, `reason_answer`, `get_am_tax_rule`, `search_gx_programs_am`, `search_loans_am`, `check_enforcement_am`, `search_mutual_plans_am`, `get_law_article_am`, `list_tax_sunset_alerts`、加えて 4 V4 universal: `get_annotations`, `validate`, `get_provenance`, `get_provenance_for_fact`、7 Phase A: `list_static_resources_am`, `get_static_resource_am`, `list_example_profiles_am`, `get_example_profile_am`, `render_36_kyotei_am`, `get_36_kyotei_metadata_am`, `deep_health_am`
- Cursor / Gemini / ChatGPT (MCP 対応) も同じ設定で動く

詳細は [mcp-tools.md](./mcp-tools.md)。

## 7. 5 秒スモークテスト (5-second smoke test)

動作確認用:

```bash
# health check (認証不要)
curl https://api.autonomath.ai/healthz
# => {"status":"ok"}

# dataset 全体像 (正規は /v1/meta。legacy /meta は 308 redirect)
curl https://api.autonomath.ai/v1/meta
# => {"total_programs": 13578, "tier_counts": {...}, ...}
```

両方 200 が返れば導入成功。

## 次は

- [api-reference.md](./api-reference.md) — 全エンドポイントの param / response 定義
- [exclusions.md](./exclusions.md) — 排他ルールの使い方
- [faq.md](./faq.md) — rate limit / データ更新頻度 / SLA 等
