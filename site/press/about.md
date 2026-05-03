# プレスキット / Press Kit — jpcite

更新日 / Updated: 2026-04-23
Launch: 2026-05-06
Operator: Bookyou株式会社

---

## 日本語 (About jpcite)

jpcite は、日本の制度データ (補助金・融資・税制優遇・認定制度) を AI エージェントから 1 API で直接呼び出せる REST + MCP サーバーです。経産省・農水省・中小企業庁・日本政策金融公庫などの一次資料をもとに、11,684 件の検索可能な制度、2,286 件の採択事例、108 件の融資、1,185 件の行政処分を整理しています。各データには一次資料 URL と取得日時を付け、制度の併用可否や前提条件を確認するための排他・前提ルール 181 件も提供します。法令、税務 ruleset、適格請求書発行事業者、判例、入札情報とも横断できるため、AI が回答を作る前に根拠を確認する Evidence Layer として利用できます。

Jグランツが申請ポータルである一方、jpcite は「発見 + 併用可否判定 + 実績確認 + 根拠法トレース + 判例・入札・適格事業者横断」の層を担います。Claude Desktop / Cursor / Cline は MCP、ChatGPT Custom GPT は OpenAPI Actions で呼び出せ、SDK は不要です。料金は完全従量 ¥3/req 税別 (税込 ¥3.30、匿名 3 req/日 per IP 無料・JST 翌日リセット)。運営は Bookyou株式会社。お問い合わせ: info@bookyou.net

## English (About jpcite)

jpcite is a REST + MCP API that exposes Japanese public-program data — subsidies, loans, tax incentives, and certifications — to AI agents in a single call. It organizes 11,684 searchable programs, 2,286 case studies, 108 loan offerings, and 1,185 enforcement cases from primary sources such as METI, MAFF, the SME Agency, and Japan Finance Corporation. Rows carry primary-source URLs and acquisition timestamps, and 181 exclusion/prerequisite rules help agents check whether programs can be combined. jpcite also connects program data with laws, tax rulesets, invoice registrants, court decisions, and public bids for citation-first AI workflows.

Where jGrants is the application portal, jpcite is the discovery, compatibility, track-record, statute-trace, precedent/bid, and invoice-registrant cross-reference layer. Claude Desktop / Cursor / Cline use native MCP (protocol 2025-06-18); ChatGPT Custom GPTs call the same data through OpenAPI Actions. Pricing is pure metered ¥3/request tax-exclusive (¥3.30 tax-inclusive; anonymous traffic gets 3/day per IP free, JST next-day reset). Operated by Bookyou K.K. Contact: info@bookyou.net

---

## Assets

- Logo / mark / favicon: [`logos.zip`](./logos.zip)
- Screenshots catalog: [`screenshots.md`](./screenshots.md)
- Background note: [`founders.md`](./founders.md)

## Quick facts

| | |
|---|---|
| Programs indexed | 11,684 searchable programs |
| Case studies (採択事例) | 2,286 |
| Loan programs (detailed) | 108 (three-axis collateral / personal-guarantor / third-party-guarantor decomposition) |
| Enforcement cases | 1,185 |
| Primary-source coverage | 主要な公開行に source_url + fetched_at を付与。欠落行は backfill せず明示 |
| Exclusion rules | 181 public-rule entries for compatibility and prerequisite checks |
| MCP tools | 93 tools for program search, eligibility checks, evidence packets, laws, tax rulesets, invoice registrants, court decisions, and bids |
| MCP protocol | 2025-06-18 |
| Pricing | ¥3/req 税別 metered (税込 ¥3.30; anonymous 3 req/日 per IP free, JST 翌日リセット) |
| Region | Japan |
| Launch | 2026-05-06 |
| Operator | Bookyou株式会社 |
