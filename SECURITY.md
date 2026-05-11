# Security Policy

## Supported Versions
jpcite は continuous release (rolling main)。直近 30 日の commit が production と一致。古い tag は support 対象外。

## Reporting a Vulnerability

セキュリティ脆弱性発見時:

1. **公開 issue 立てない**ください
2. **email**: info@bookyou.net (Subject: `[security] jpcite vulnerability report`)
3. **SLA**: 受領 24h 以内 ack、72h 以内 triage、HIGH 以上は 7 日以内 patch + advisory

## Scope
- jpcite.com の静的 site (Cloudflare Pages)
- api.jpcite.com の REST + MCP API (Fly.io Tokyo)
- PyPI: `autonomath-mcp`
- npm: `@bookyou/jpcite` (legacy)

## Out of Scope
- 公開 information (補助金/法令/行政処分等の公開データ自体の正確性)
- 第三者依存 (Stripe / Fly / Cloudflare / Sentry の vulnerability)
- DoS / Brute force (rate limit + Cloudflare WAF で対応済)

## Bounty
現状 bounty program なし。 honor wall は SECURITY.md に追記予定。

Bookyou株式会社 (T8010001213708) — info@bookyou.net
