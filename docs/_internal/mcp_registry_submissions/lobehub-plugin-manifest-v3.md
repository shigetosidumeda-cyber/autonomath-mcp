# LobeHub plugin manifest v3 (jp/zh/en bilingual draft)

## Hosting URL (production endpoint)
https://jpcite.com/.well-known/lobehub-plugin.json

## Source repo path (where the manifest lives in jpcite repo)
`web/public/.well-known/lobehub-plugin.json` (or `site/.well-known/lobehub-plugin.json` per static-site layout)

## Manifest JSON (final, multi-lang)

```json
{
  "$schema": "https://chat-preview.lobehub.com/schemas/plugin.json",
  "api": [
    {
      "url": "https://api.jpcite.com/openapi.json",
      "name": "jpcite-openapi"
    }
  ],
  "author": "Bookyou株式会社",
  "createdAt": "2026-05-11",
  "homepage": "https://jpcite.com",
  "identifier": "jpcite",
  "manifest": "https://jpcite.com/.well-known/lobehub-plugin.json",
  "meta": {
    "avatar": "https://jpcite.com/favicon.svg",
    "tags": ["mcp", "japan", "subsidy", "regtech", "evidence", "open-data"],
    "title": {
      "en-US": "jpcite — Japanese Public-Program Evidence MCP",
      "ja-JP": "jpcite — 日本公的制度 Evidence MCP",
      "zh-CN": "jpcite — 日本公共制度 Evidence MCP"
    },
    "description": {
      "en-US": "Japanese public-program evidence layer for AI agents. 139 tools across subsidies, loans, licenses, dispositions, qualified-invoice registry, and e-Gov laws. Joinable by 13-digit corporate number. Anonymous 3 req/day/IP free, ¥3/billable unit metered. PDL v1.0 + CC-BY-4.0 compliant.",
      "ja-JP": "AI エージェント向け日本公的制度 Evidence レイヤー。補助金・融資・許認可・行政処分・適格事業者・法令を法人番号 1 つで横断照会する 139 tool。無料 3 req/IP/日、¥3/req 従量。PDL v1.0 / CC-BY-4.0 準拠。",
      "zh-CN": "面向 AI 智能体的日本公共制度 Evidence 层。补助金、融资、许可、行政处分、合格发票登记、e-Gov 法令共 139 个工具。按法人番号横向检索。匿名 3 次/日/IP 免费,¥3/请求计量。PDL v1.0 / CC-BY-4.0 合规。"
    }
  },
  "version": "0.3.4",
  "settings": [
    {
      "key": "JPCITE_API_KEY",
      "label": {
        "en-US": "API Key (optional)",
        "ja-JP": "API キー (任意)",
        "zh-CN": "API 密钥 (可选)"
      },
      "type": "string",
      "required": false,
      "description": {
        "en-US": "Optional. Anonymous 3 req/day per IP works without key. ¥3/billable unit metered with key.",
        "ja-JP": "省略可。匿名 3 req/IP/日 は無料。鍵あり時は ¥3/req 従量課金。",
        "zh-CN": "可选。匿名 3 次/日/IP 免费。配置密钥后按 ¥3/请求计量。"
      }
    }
  ]
}
```

## Differentiation vs `japan-gov-mcp` (LobeHub 既存掲載, ~50+ tools)

LobeHub には既に `japan-gov-mcp` (50+ tools) が掲載されている。jpcite は同カテゴリ内で以下 5 軸で差別化する:

| 軸 | japan-gov-mcp | **jpcite** |
|---|---|---|
| Tool 数 | ~50 | **139** (約 2.8 倍の breadth) |
| Evidence contract | なし | `source_url` + `source_fetched_at` + `content_hash` 全 payload に同梱 |
| License 表記 | ad-hoc | **PDL v1.0 + CC-BY-4.0** ペイロード schema 内蔵 |
| 業法 fence | 未確認 | **7 業法**プログラム的拒否 (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 / 司法書士法 §73 / 社労士法 §27 / 中小企業診断士登録規則 / 弁理士法 §75) |
| SOT data layer | API direct | **facts_registry** 中間 SOT — agents が一貫した unified_id で参照可 |
| 課金 | 不明 | 匿名 3 req/IP/日 free + ¥3/req 従量 Stripe 自動精算、tier なし、営業なし |

## Tags strategy
- Primary: `mcp`, `japan`, `regtech`, `evidence`
- Secondary: `subsidy`, `open-data`, `legal-tech`, `claude`, `cursor`, `chatgpt`
- Avoid: `tax-advice`, `legal-advice` (業法 fence 違反のリスク表記)

## Submission steps
1. Deploy `web/public/.well-known/lobehub-plugin.json` to https://jpcite.com (verify 200)
2. Open https://lobehub.com/plugins → "Submit Plugin"
3. Paste manifest URL: https://jpcite.com/.well-known/lobehub-plugin.json
4. LobeHub bot validates schema and creates PR to lobehub-community repo
5. Respond to maintainer review within 24h
6. Listing live at https://lobehub.com/plugins/jpcite (or auto-slug)

## Post-listing verification
- [ ] Listing page returns 200
- [ ] All three locales (ja-JP / en-US / zh-CN) render correctly
- [ ] Tool count badge >= 139
- [ ] Differentiation section vs japan-gov-mcp visible
- [ ] Cross-link from https://jpcite.com to LobeHub listing
- [ ] Cross-link from LobeHub listing back to https://jpcite.com

## Maintainer
- Bookyou株式会社 (T8010001213708, 東京都文京区小日向2-22-1)
- info@bookyou.net
- https://jpcite.com
- Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp
