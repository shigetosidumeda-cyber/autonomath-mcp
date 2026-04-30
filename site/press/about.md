# プレスキット / Press Kit — AutonoMath

更新日 / Updated: 2026-04-23
Launch: 2026-05-06
Operator: Bookyou株式会社 (T8010001213708)

---

## 日本語 (About AutonoMath)

AutonoMath は、日本の制度データ (補助金・融資・税制優遇・認定制度) を AI エージェントから 1 API で直接呼び出せる REST + MCP サーバーです。経産省・農水省・中小企業庁・日本政策金融公庫など一次情報源から 11,684 件の検索可制度 (tier S/A/B/C; quarantine 含む登録総数 14,472) + 2,286 件の採択事例 + 108 件の融資 (担保・個人保証人・第三者保証人の三軸分解) + 1,185 件の行政処分を正規化し、Tier 分類 (S/A/B/C/X)、181 件の排他ルール (hand-seeded 35 + 要綱 一次資料 auto-extracted 146)、日本語の高速全文検索、`source_url` と `fetched_at` を 99%以上の行に付与したリネージ (12 件は小規模自治体 CMS 不在のため URL 未取得) を提供します。2026-04-24 拡張で法令 (e-Gov法令, CC-BY、 法令本文 154 件 + 法令メタデータ 9,484 件・本文ロード継続中、 法令名 resolver は 9,484 件全件で稼働) + 税務ruleset (インボイス+電帳法等、50 件) + 国税庁適格事業者 (PDL v1.0、13,801 件 delta-only ライブミラー、月次フルバルク準備中) をライブ追加済み。判例 (裁判所) / 入札 (GEPS + 自治体) はスキーマ構築済み・データロード準備中 (coming post-launch)。制度横断の `trace_program_to_law` / `find_cases_by_law` / `combined_compliance_check` を提供します。

Jグランツが申請ポータルである一方、AutonoMath は「発見 + 併用可否判定 + 実績確認 + 根拠法トレース + 判例・入札・適格事業者横断 + entity-fact 検索」の層を担います。Claude Desktop / ChatGPT / Cursor / Gemini などの MCP クライアントから stdio で直接呼び出せ、SDK は不要です。MCP プロトコル 2025-06-18 準拠、93 ツール  at default gates:  = 基本 + one-shot + 拡張 [法令・判例・入札・税務ruleset・適格事業者 + cross-dataset glue]、30 autonomath = entity-fact DB 503,930 entities + 6.12M facts + 23,805 relations を 税制優遇 / 認定制度 / 法令 / 処分 / 融資 / 共済 横断で検索)。料金は完全従量 ¥3/req 税別 (税込 ¥3.30、匿名 3 req/日 per IP 無料・JST 翌日リセット)、Stripe Tax によるインボイス制度対応。運営は独立開発者 梅田茂利 (Bookyou株式会社 代表)、ホスティングは Fly.io 東京 (nrt) リージョン。お問い合わせ: info@bookyou.net

## English (About AutonoMath)

AutonoMath is a REST + MCP API that exposes Japanese public-program data — subsidies, loans, tax incentives, and certifications — to AI agents in a single call. 11,684 searchable programs (tier S/A/B/C; total rows incl. quarantine = 14,472), 2,286 case studies (採択事例), 108 loan offerings (decomposed across collateral / personal guarantor / third-party guarantor axes), and 1,185 enforcement cases are normalized from primary sources (METI, MAFF, SME Agency, Japan Finance Corporation) with Tier scoring (S/A/B/C/X), 181 exclusion rules (35 hand-seeded + 146 primary-source auto-extracted), fast Japanese full-text search, and source lineage (`source_url` + `fetched_at` on 99%+ of rows; 12 rows are small-municipality programs lacking a dedicated CMS page). A 2026-04-24 expansion adds laws (e-Gov, CC-BY; 154 rows full-text indexed + 9,484 catalog stubs as a name resolver, body-text load incremental), tax rulesets (invoice system + electronic book retention and related rules; 50 rows live), and NTA invoice registrants (PDL v1.0; 13,801 rows live delta-only mirror, monthly full-bulk pending) — with cross-dataset glue (`trace_program_to_law`, `find_cases_by_law`, `combined_compliance_check`). Court decisions and public bids (GEPS + municipalities) have schema and ingest infrastructure pre-built; data loads are coming post-launch.

Where jGrants is the *application portal*, AutonoMath is the *discovery + compatibility + track-record + statute-trace + precedent/bid/registrant cross-reference + entity-fact lookup layer*. It speaks native MCP (stdio, protocol 2025-06-18) to Claude Desktop, ChatGPT, Cursor, and Gemini — no SDK required, 93 tools exposed at default gates :  = base + one-shot + expansion [laws / court_decisions / bids / tax_rulesets / invoice_registrants + cross-dataset glue]; 30 autonomath = entity-fact DB with 503,930 entities + 6.12M facts + 23,805 relations spanning tax incentives / certifications / laws / enforcements / loans / mutual insurance). Pricing is pure metered ¥3/request tax-exclusive (¥3.30 tax-inclusive; anonymous tier gets 3/day per IP free, JST next-day reset). Built and maintained solo by Shigetoshi Umeda (Bookyou K.K., 代表取締役); hosted on Fly.io Tokyo (nrt); billed via Stripe Tax with JP invoice-system (インボイス) compliance. Contact: info@bookyou.net

---

## Assets

- Logo / mark / favicon: [`logos.zip`](./logos.zip)
- Screenshots catalog: [`screenshots.md`](./screenshots.md)
- Founder bio: [`founders.md`](./founders.md)

## Quick facts

| | |
|---|---|
| Programs indexed | 11,684 (searchable, tier S/A/B/C; total rows incl. quarantine = 14,472) |
| Case studies (採択事例) | 2,286 |
| Loan programs (detailed) | 108 (three-axis collateral / personal-guarantor / third-party-guarantor decomposition) |
| Enforcement cases | 1,185 |
| Primary-source coverage | 99%以上 (source_url + fetched_at; 12件は小規模自治体 CMS 不在のため URL 未取得) |
| Exclusion rules | 181 (35 hand-seeded = 22 agri + 13 non-agri + 146 primary-source auto-extracted) |
| MCP tools | 69 at default gates : base + 7 one-shot + expansion [laws 154 rows full-text + 9,484 catalog stubs / tax_rulesets 50 / invoice_registrants 13,801 delta / court_decisions 2,065 / bids 362 + cross-dataset glue]; 30 autonomath: entity-fact DB 503,930 entities + 6.12M facts + 23,805 relations across tax incentives / certifications / laws / enforcements / loans / mutual insurance) |
| MCP protocol | 2025-06-18 |
| Pricing | ¥3/req 税別 metered (税込 ¥3.30; anonymous 3 req/日 per IP free, JST 翌日リセット) |
| Region | Tokyo (Fly.io nrt) |
| Launch | 2026-05-06 |
| Operator | Bookyou株式会社 (T8010001213708) |
