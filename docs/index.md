<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite Documentation",
  "description": "jpcite は、日本政府の公開制度データ (補助金・融資・税制・認定制度) 11,684 件 + 採択事例 2,286 + 融資 108 + 行政処分 1,185 を一次資料 URL 付きで横断検索する REST API + MCP サーバー。Bookyou株式会社 (info@bookyou.net) が運営。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-29",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://jpcite.com/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://jpcite.com/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://jpcite.com/docs/"
  }
}
</script>

# jpcite docs

日本の公的制度を一次資料 URL 付きで横断検索する **REST API + MCP サーバー**。Bookyou株式会社 (T8010001213708) が運営。

## データ収録 (Coverage)

| データ種別 | 検索対象 件数 |
|---|---|
| 補助金 / 助成金 / 認定 | 11,684 (tier S/A/B/C) |
| 採択事例 | 2,286 |
| 融資 (担保 / 個人保証人 / 第三者保証人 三軸) | 108 |
| 行政処分 | 1,185 |
| 法令本文 (全文検索対象) | 154 |
| 法令メタデータ (resolver 用) | 9,484 |
| 判例 | 2,065 |
| 税制ルールセット | 50 |
| 適格請求書発行事業者 | 13,801 |
| 排他 / 前提ルール | 181 |

tier ラベルは enrichment 充足度を表す指標です。各レコードの一次資料 URL を必ず参照してください。能力と境界の詳細: [honest_capabilities.md](./honest_capabilities.md)。

## 提供形態

- **REST API** — `https://api.jpcite.com/v1/*`
- **MCP server** (`autonomath-mcp`) — Claude Desktop / Cursor / ChatGPT / Gemini から **89 ツール** at default gates。stdio 経由、SDK 不要

## 価格

完全従量 **¥3 / req 税別** (税込 ¥3.30)。匿名 50 req/月 per IP は無料 (JST 月初リセット)。tier プラン無し、最低額無し、契約無し。詳細: [pricing.md](./pricing.md)。

## Jグランツ との位置関係

**Jグランツ** は経産省運営の公式 **申請ポータル** (申請・審査管理が目的)。**jpcite** は政府公開データの **検索 API + MCP**。レイヤーが異なる — jpcite は申請を代行しない。

## 次のステップ

- [getting-started.md](./getting-started.md) — 5 分で最初のリクエスト
- [api-reference.md](./api-reference.md) — 全 API 経路
- [mcp-tools.md](./mcp-tools.md) — 89 MCP ツール
- [exclusions.md](./exclusions.md) — 排他ルール
- [pricing.md](./pricing.md) — 料金
- [faq.md](./faq.md) — よくある質問
- [honest_capabilities.md](./honest_capabilities.md) — 何ができて何をしないか
