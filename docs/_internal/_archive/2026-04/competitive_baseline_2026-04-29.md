# Competitive & Organic Search Baseline — 2026-04-29

> Read-only investigation. Author: Claude Opus 4.7 agent. Owner: 梅田茂利 / Bookyou株式会社.
> Method: WebFetch (politely, 1/5sec) + WebSearch. No paid SEO API. No ranking-tool access.
> Re-test cadence: **2026-05-29 (T+30)**, **2026-07-01 (T+60)**, **2026-10-01 (T+150)**.

---

## TL;DR (honest)

- **Organic ranking**: 0 of 30 representative queries return zeimu-kaikei.ai in top 10 on Bing JP. Brand-name search ("zeimu-kaikei.ai 税務会計AI") also returns 0 hits. **Expected at launch — sites typically need 3-12 weeks to index.**
- **Backlinks**: 0 discoverable. Drafts exist in `docs/launch/` (HN, Reddit×7, dev.to, lobsters, note, Twitter/X, Zenn) but none are posted yet.
- **LLM citations**: 0 in WebSearch + DuckDuckGo. Perplexity returned 403 on direct fetch — confirm post-launch.
- **Competitor delta vs static `site/compare/{slug}/index.html` pages**: **3 stale claims need correction**, **1 stability concern surfaced**, **1 new pricing data-point** found that we previously called "公開情報なし".

---

## Task 1 — Competitor Delta (vs `site/compare/{slug}/index.html`)

All compare pages dated `2026-04-29`. Fetched competitor canonical URLs same day. Three stale or improvable claims surfaced.

### 1.1 jGrants (`site/compare/jgrants/index.html`) — STALE: API claim wrong

**Compare-page claim**: "API 公開なし (2026-04 時点公開情報) — 検索 UI のみ。"

**Reality (verified 2026-04-29)**: jGrants has **published REST API at `/v1/public/subsidies`** with 3 documented endpoints, and a **V2 endpoint** that adds `granttype` and `workflow` array. Documentation page dated 2024-10-07. Source: <https://developers.digital.go.jp/documents/jgrants/api/>.

- `GET /v1/public/subsidies` — search
- `GET /v1/public/subsidies/id/{id}` — detail
- `GET /v2/public/subsidies/id/{id}` — V2 detail (granttype + multi-round workflow)

**Recommended copy edit**: "jGrants は **公開 REST API あり** (`/v1` + `/v2`)。当社内部でも取込元の一つ。当社の独自性は API のラッパーではなく、複数政府ソース横断 + 制度横断 + MCP プロトコル + 一次資料 lineage。"

**Severity**: HIGH — claim "API公開なし" is factually wrong and hurts honesty credibility if a reader cross-checks. Fix before any launch outreach that links to /compare/jgrants/.

### 1.2 gBizINFO (`site/compare/gbizinfo/index.html`) — STALE: stability/TOS not noted

**Compare-page claim**: "REST API あり (申請ベース、無料、利用規約あり)。"

**Reality (verified 2026-04-29)**: Two material 2026-04 notices on gBizINFO homepage:
- 2026-04-03: **API（REST API v1 / v2）動作不安定について** (operational instability notice — still active).
- 2026-04-08: **API・データダウンロード利用規約の改定** (TOS revision).
- 2026-04-16: 事業所情報の追加予定 (planned dataset expansion).

**Recommended copy add (footnote on /compare/gbizinfo/)**: "2026-04-03 時点で gBizINFO は API 動作不安定の official notice を出しています。同時期に利用規約も改定 (2026-04-08)。当社 ingestion は冗長化しており影響軽微。読者が直接 gBizINFO API を呼ぶ場合、安定運用前提の本番統合は当面ブロックされる可能性があり。"

**Severity**: MEDIUM — neither false nor critical, but adds genuine value vs the static claim and supports the "buy-don't-build" frame in /compare/diy-scraping/.

### 1.3 ナビット 助成金なう (`site/compare/navit/index.html`) — STALE: "公開情報なし" wrong, ¥1,000/月 visible

**Compare-page claim**: 「Seat 課金 (公開価格情報なし、要問合せ)」「無料お試しあり (公開情報、期間/制限は要確認)」

**Reality (verified 2026-04-29)**: Homepage explicitly displays **¥1,000/月 paid membership** with searchable database of **147,976 national/local cases + 9,939 foundation cases** (current as of 2026-04-28 per their counter). Source: <https://www.navit-j.com/service/joseikin-now/>.

**Recommended copy edit**: 「同社公開: ¥1,000/月、147,976 件 + 9,939 件 (2026-04-28 時点)。当社 ¥3/billable unit 完全従量との比較は利用ボリューム次第 — 月 333 req 未満なら同社が安い、それ以上なら当社、という単純な break-even ¥1,000 / ¥3 = 333 リクエスト/月。」

**Severity**: HIGH — calling visible price "公開情報なし" is the most dangerous flavor of stale claim because a reader who clicks through immediately sees we were sloppy. Fix before launch.

### 1.4 国税庁 適格請求書発行事業者 (`site/compare/nta-invoice/index.html`) — OK

**Compare-page claim**: "Web API + bulk download" (公式 Web-API、月次 bulk CSV).

**Reality (verified 2026-04-29)**: Homepage links `/web-api/index.html` and `/download/index.html` — both present. The `/regulations/api-shiyo` URL we tried for spec returned 404 (different path but data access still live). Bulk format spec not surfaced from homepage; CLAUDE.md confirms PDL v1.0 delta ingestion live with monthly 4M-row bulk wired 2026-04-29 (see `scripts/cron/ingest_nta_invoice_bulk.py`).

**Severity**: NONE — claim aligns with reality.

### 1.5 freee 助成金AI (`site/compare/freee/index.html`) — OK (page is stale but compare claim is accurate)

**Compare-page claim**: "freee 顧客向けの追加機能 (公開価格情報非公表)。外部 API は提供せず (公開情報なし)。"

**Reality (verified 2026-04-29)**: The 2023-09-29 press release at corp.freee.co.jp/news is the latest dedicated announcement; no 2026-04 update found. freee.co.jp homepage mentions 「デジタル化・AI導入補助金」 resource page generically but no 助成金AI product API. Compare-page claim that there's "no public API" remains correct.

**Severity**: NONE.

### 1.6 マネーフォワード ビジネスID (`site/compare/moneyforward/index.html`) — OK

**Compare-page claim**: "会計・経費・人事 SaaS の API (顧客向け、公開仕様は限定的)。... 制度 DB API は提供せず。MCP 公開情報なし。SaaS Seat 課金 (会計プラン月額数千円〜)。"

**Reality (verified 2026-04-29)**: Pricing 個人 ¥900-2,980/月、SMB ¥2,480-6,480/月、Enterprise 要相談。クラウド請求書/経費 API documented for customer use. No 制度 DB API. No MCP. Compare claim aligns; could optionally tighten "数千円〜" to the actual ¥900〜¥6,480/月 range.

**Severity**: LOW (optional tightening).

### 1.7 帝国データバンク TDB (`site/compare/tdb/index.html`) — OK with minor tightening

**Compare-page claim**: "API は法人向け契約で別途提供 (公開価格なし)。COSMOS / 企業ファイル等は個別見積。"

**Reality (verified 2026-04-29)**: TDB COSMOSNET API service confirmed live at <https://www.tdb.co.jp/lineup/api/index.html>. Pricing **explicitly** "要件にあわせて個別にお見積り" — matches our claim. Additional tightening possible: TDB now requires **NDA before API spec disclosure** ("秘密保持契約書") — adds further friction vs our "OpenAPI 3.1 公開、API key 不要" point.

**Severity**: LOW (could strengthen our differentiation).

### 1.8 東京商工リサーチ TSR (`site/compare/tsr/index.html`) — OK

**Compare-page claim**: 「tsr-van2 等の法人向け情報サービスを提供 — Web/専用回線。API/MCP の公開仕様は公開情報なし。個別見積 (代理店経由が中心、公開価格表は無し)。」

**Reality (verified 2026-04-29)**: TSR homepage confirms enterprise contact-only model. No API spec public. No MCP. No published pricing. Compare claim aligns.

**Severity**: NONE.

### 1.9 ミラサポplus (`site/compare/mirasapo/index.html`) — OK

**Compare-page claim**: "検索 UI のみ。API 公開なし (2026-04 時点公開情報)。完全無料 (政府公式)。"

**Reality (verified 2026-04-29)**: Mirasapo plus homepage confirms portal/UI model. No API doc surfaced. Recent notices about 商用車電動化 + smart register subsidies but no API/MCP.

**Severity**: NONE.

### 1.10 自前スクレイピング DIY (`site/compare/diy-scraping/index.html`) — N/A

No external service to verify. Claim structure (cost, time, license discipline) is internal positioning. The new gBizINFO instability + TOS revision (1.2) actually strengthens this page's "license の落とし穴" section if cross-linked.

**Severity**: NONE.

### Competitor delta summary table

| # | Competitor | Compare page status | Severity | Action |
|---|---|---|---|---|
| 1 | jGrants | **STALE — claims "API公開なし", actually v1+v2 live** | HIGH | Edit `site/compare/jgrants/index.html` |
| 2 | gBizINFO | Outdated — 2026-04 instability + TOS not mentioned | MEDIUM | Add footnote to `site/compare/gbizinfo/index.html` |
| 3 | ナビット 助成金なう | **STALE — ¥1,000/月 visible, claimed "公開情報なし"** | HIGH | Edit `site/compare/navit/index.html` |
| 4 | 国税庁 適格請求書 | OK | NONE | No change |
| 5 | freee 助成金AI | OK | NONE | No change |
| 6 | マネーフォワード | OK (could tighten price range) | LOW | Optional tightening |
| 7 | 帝国データバンク | OK (could add NDA-required note) | LOW | Optional tightening |
| 8 | 東京商工リサーチ | OK | NONE | No change |
| 9 | ミラサポplus | OK | NONE | No change |
| 10 | 自前スクレイピング | N/A | NONE | Optional cross-link to gBizINFO instability |

**Aggregate**: 2 HIGH, 1 MEDIUM. The two HIGH (jGrants + Navit) should be fixed before any social outreach links the comparison pages — both errors are clearly visible to a reader who clicks through to the source.

---

## Task 2 — Organic Search Ranking Baseline (Bing JP)

**Method**: 30 representative queries × Bing JP (`bing.com/search?q=...&cc=jp&setlang=ja-jp`) on 2026-04-29. Google JP web-fetch returns near-empty page (anti-scrape) — Bing JP is the only direct-fetchable engine giving parseable results. WebSearch tool used as cross-check on brand-name query.

**Note on result quality**: Many queries return Zhihu (Chinese Q&A) or goo.ne.jp (Japanese Q&A) as top results, which is unusual and suggests Bing JP's index is **shallow** for some Japanese B2B/regulated terms. Real organic share will likely come from Google JP — **a key blind spot of this baseline is that we cannot direct-fetch Google's SERP HTML**. We should re-test using Google Search Console once domain is verified post-launch (Search Console is authenticated, no scrape risk).

### 2.1 Query × engine matrix (rank of zeimu-kaikei.ai in top 10)

| # | Query | Bing JP rank | Notes / dominant domains |
|---|---|---|---|
| 1 | 中小企業 補助金 一覧 2026 | not in top 10 | All zhihu.com (off-topic) |
| 2 | ものづくり補助金 採択率 | not in top 10 | monodukuri-hojo.jp dominates 1-10 |
| 3 | 賃上げ促進税制 計算方法 | not in top 10 | meti.go.jp #1, nta.go.jp #2 |
| 4 | インボイス制度 経過措置 | not in top 10 | ht-tax.or.jp dominates 1-10 |
| 5 | 経営力向上計画 メリット | not in top 10 | jfc-guide.com #1, sme-support.co.jp #2 |
| 6 | 中小企業基本法 改正 | not in top 10 | All zhihu.com (off-topic) |
| 7 | 適格請求書発行事業者 検索 | not in top 10 | All nta.go.jp |
| 8 | 法人番号 API | not in top 10 | nta.go.jp #1, zenn.dev #2 |
| 9 | 経済産業省 公募 一覧 2026 | not in top 10 | All zhihu.com (off-topic) |
| 10 | 中小企業 補助金 API | not in top 10 | All zhihu.com (off-topic) |
| 11 | MCP 日本 税制 | not in top 10 | Microsoft cert + DXY medical (off-topic) |
| 12 | 事業承継税制 適用要件 | not in top 10 | nta.go.jp #1, meti.go.jp #2 |
| 13 | Claude tools 日本 税制 | not in top 10 | GitHub + zhihu (Claude Code, off-topic) |
| 14 | 補助金 最新 2026 公募 | not in top 10 | All goo.ne.jp (off-topic) |
| 15 | 小規模事業者持続化補助金 対象 | not in top 10 | zhihu.com + baidu (off-topic) |
| 16 | 法人番号 検索 | not in top 10 | All nta.go.jp |
| 17 | 中小企業 基本法 全文 | not in top 10 | All zhihu.com (off-topic) |
| 18 | 法令 検索 API | not in top 10 | All e-gov.go.jp |
| 19 | 判例 検索 API | not in top 10 | courts.go.jp #1, legaldoc.jp #2 |
| 20 | jGrants API 使い方 | not in top 10 | All Roblox forum (off-topic) |
| 21 | Cursor 税制 日本 | not in top 10 | All zhihu (Cursor IDE, off-topic) |
| 22 | 補助金 検索 サイト API | not in top 10 | All goo.ne.jp (off-topic) |
| 23 | 税務会計 AI 日本 | not in top 10 | All nta.go.jp |
| 24 | 判例検索 公式 | not in top 10 | courts.go.jp #1, legaldoc.jp #2 |
| 25 | 行政処分 検索 | not in top 10 | All mlit.go.jp |
| 26 | 融資 無担保 無保証 | not in top 10 | All cmoney.tw (off-topic Taiwan) |
| 27 | スタートアップ 補助金 2026 | not in top 10 | Mostly Windows-startup misinterpretation |
| 28 | 設備投資 削除 要件 | not in top 10 | All ptt.cc (off-topic Taiwan) |
| 29 | 労働基準法 判例 | not in top 10 | All zhihu (off-topic) |
| 30 | 適格請求書 登録情報 一括 | not in top 10 | All soumunomori.com |

**Aggregate Bing JP**: **0 / 30 queries** rank zeimu-kaikei.ai in top 10. **0 / 30 queries** rank zeimu-kaikei.ai anywhere visible.

**Brand-name search**: WebSearch tool ran "zeimu-kaikei.ai 税務会計AI" — returned 10 results, **none from zeimu-kaikei.ai**. Top results: kaikeizeimukun.jp, zeimu.ai, ai-zeirishi.jp, ai-kaikei.com, prime-partners.co.jp, attax.co.jp, robon.co.jp, kaikei-ai.jp, zeimu-kaikei.jp (note: similar but different domain — 税理士法人きらり), fm-suishinkyogikai.jp.

**Bing exact-match `"zeimu-kaikei.ai"`**: returned ~44,700 results but **the domain itself does not appear** in displayed top 10 — Bing is matching on the constituent words, not the actual hostname.

**Google JP brand-name**: direct fetch of `google.com/search?q=zeimu-kaikei.ai` returned empty body (anti-scrape interstitial / JS challenge). Cannot baseline Google ranking via WebFetch — **flagged as critical blind spot**. Re-test plan = Google Search Console once DNS verifies (`docs/_internal/autonomath_com_dns_runbook.md` covers DNS for autonomath.com; site live at zeimu-kaikei.ai per launch CLI plan).

### 2.2 Conclusion (organic ranking)

**0 / 30 = 0% top-10 share at T+0**. This is the expected and honest baseline for a domain that is days from launch. Sites typically need:
- 1-3 weeks to be **indexed** (Googlebot first crawl)
- 4-8 weeks to **rank** for low-competition long-tail (e.g., "MCP 日本 税制")
- 12-26 weeks to **rank top 10** for medium-competition (e.g., "ものづくり補助金 採択率")
- 26+ weeks to **threaten top 10** for high-competition (e.g., "中小企業 補助金 一覧 2026")

The 30 queries split roughly:
- 6 high-competition (#1, 2, 7, 12, 14, 27) — 6+ months realistic for top 10
- 14 medium-competition (most regulated/法令/制度/税制 queries) — 2-4 months for top 10 of less authoritative competition
- 10 long-tail/dev-focused (#8, 10, 11, 13, 18, 19, 20, 22, 23) — these are the **realistic 1-3 month wins**, especially "MCP 日本 税制", "中小企業 補助金 API", "Claude tools 日本 税制", "法人番号 API". On these, gov sites + zhihu currently dominate but neither maps to dev-API-MCP intent — there's a real ranking gap to fill.

---

## Task 3 — Backlink Baseline

**Method**: Bing `link:zeimu-kaikei.ai` operator + Bing `"zeimu-kaikei.ai"` exact-match + DuckDuckGo HTML version.

**Result (2026-04-29)**:

| Source | Backlinks discovered |
|---|---|
| Bing `link:` operator | 0 (operator returned generic results, none link to the domain) |
| Bing `"zeimu-kaikei.ai"` exact-match | 0 (44,700 phantom results from constituent-word match — domain itself absent) |
| DuckDuckGo HTML | 0 (returned related domain `zeimu.ai` only) |

**Discoverable backlinks: 0.** This is the expected baseline for a pre-launch domain.

### 3.1 Drafted backlink targets (in `docs/launch/`)

These are not posted yet; they exist as drafts:

| File | Target platform | Expected DR |
|---|---|---|
| `docs/launch/hn.md` | Hacker News (Show HN) | DR ~89 |
| `docs/launch/lobsters.md` | Lobsters | DR ~75 |
| `docs/launch/devto.md` | dev.to | DR ~89 |
| `docs/launch/note_com.md` | note.com | DR ~88 |
| `docs/launch/reddit_claudeai.md` | r/ClaudeAI | DR ~91 |
| `docs/launch/reddit_entrepreneur.md` | r/Entrepreneur | DR ~91 |
| `docs/launch/reddit_japan.md` | r/japan | DR ~91 |
| `docs/launch/reddit_japanfinance.md` | r/JapanFinance | DR ~91 |
| `docs/launch/reddit_localllama.md` | r/LocalLLaMA | DR ~91 |
| `docs/launch/reddit_programming.md` | r/programming | DR ~91 |
| `docs/launch/reddit_sideproject.md` | r/SideProject | DR ~91 |
| `docs/launch/twitter_x_thread.md` | X / Twitter | DR ~98 (low pass-through) |
| `docs/launch_assets/zenn_intro_published.md` | Zenn | DR ~80 |
| `docs/launch_assets/email_first_500.md` | personal outreach (no DR contribution) | n/a |

**Realistic backlink trajectory**: 1-3 high-quality backlinks (HN front page, Reddit front page of relevant sub) within 2 weeks of posting; 5-15 within 6 weeks if any single post catches traction. Zero growth if all drafts stay drafts.

---

## Task 4 — LLM Citation Baseline

### 4.1 Perplexity

Direct WebFetch to `perplexity.ai/search?q=...` returned **HTTP 403** (anti-scrape). Cannot baseline programmatically. Manual visual check post-launch is the realistic path. Setting up authenticated Perplexity Pro isn't justified — re-evaluate at T+60 with manual Spot-check.

### 4.2 WebSearch tool ("zeimu-kaikei.ai 税務会計AI")

Returned 10 results, **0 from zeimu-kaikei.ai or autonomath**. Top results all from competitor / unrelated AI accounting services. WebSearch tool draws on a US-region index (per environment notes); insight into JP-specific LLM citation behavior is limited.

### 4.3 Bing Chat / Copilot

Not directly fetchable. Will manifest in Bing JP organic results as our content gets indexed.

### 4.4 LLM citation baseline

| Surface | Citations as of 2026-04-29 |
|---|---|
| Perplexity (direct fetch) | inaccessible (403) — manual re-check post-launch |
| WebSearch tool | 0 |
| Bing JP exact-match | 0 |
| Google JP (direct fetch) | inaccessible (anti-scrape) |
| ChatGPT browsing | not tested directly; reflects Bing index |

**Aggregate: 0 LLM citations at T+0.** Same root cause as ranking — index hasn't picked up the domain yet.

---

## Re-test Plan

| Date | Trigger | Re-test scope |
|---|---|---|
| **2026-05-29** (T+30) | First indexing window | All 30 queries on Bing JP + Google Search Console (post DNS+verify) + Perplexity manual spot-check |
| **2026-07-01** (T+60) | First long-tail ranking window | Same 30 queries + add 10 new queries derived from posted launch content (HN/Reddit titles) + Perplexity systematic 10-query batch |
| **2026-10-01** (T+150) | Medium-competition ranking window | Same 40 queries + Ahrefs free trial 30-day window for backlink count + LLM citation audit (Perplexity + Bing Chat + ChatGPT browsing) |

### Critical blind spot to close before T+30

**Google Search Console verification**: WebFetch cannot scrape Google SERP HTML. The only honest way to baseline Google ranking is GSC, which requires DNS TXT record verification. This must be done on or before 2026-05-06 launch day so the first SC data sample lands by 2026-05-29.

---

## Recommended actions (ranked, none assumed-approved)

| # | Action | Estimated impact on launch credibility | Type |
|---|---|---|---|
| 1 | Fix `site/compare/jgrants/index.html` "API公開なし" → "公開 REST API あり (v1+v2)" | HIGH (visible falsification) | Content correction |
| 2 | Fix `site/compare/navit/index.html` "公開情報なし" → "¥1,000/月 公開、break-even 333 req/月" | HIGH (visible falsification) | Content correction |
| 3 | Add gBizINFO 2026-04-03 instability + 04-08 TOS revision footnote to `site/compare/gbizinfo/index.html` and `site/compare/diy-scraping/index.html` (cross-link) | MEDIUM (strengthens differentiation) | Content addition |
| 4 | Verify domain in Google Search Console before 2026-05-06 launch | HIGH (closes blind spot for T+30 baseline) | Operational |
| 5 | Optional: tighten TDB compare with "NDA required before API spec" + tighten MF compare with actual ¥900-6,480/月 range | LOW | Optional tightening |

**Note**: I did not edit any compare pages — task scope was research-only.

---

## Files referenced

- Compare pages: `/Users/shigetoumeda/jpintel-mcp/site/compare/{tdb,tsr,nta-invoice,moneyforward,freee,jgrants,mirasapo,gbizinfo,navit,diy-scraping}/index.html`
- Existing competitive watch playbook: `/Users/shigetoumeda/jpintel-mcp/docs/_internal/competitive_watch.md`
- Backlink draft inventory: `/Users/shigetoumeda/jpintel-mcp/docs/launch/` + `/Users/shigetoumeda/jpintel-mcp/docs/launch_assets/`
- DNS runbook (for Google Search Console verification path): `/Users/shigetoumeda/jpintel-mcp/docs/_internal/autonomath_com_dns_runbook.md`
- This baseline: `/Users/shigetoumeda/jpintel-mcp/docs/_internal/competitive_baseline_2026-04-29.md`

---

## Method honesty note

What this baseline can and cannot tell us:

**Can**: Bing JP organic ranking on 30 queries (0/30 confirmed), backlink discoverability via Bing `link:` + exact-match (0 confirmed), competitor landing-page state on 2026-04-29 (verified 10/10 directly).

**Cannot** (without authenticated access): Google JP organic ranking, Perplexity citation pattern, ChatGPT browsing citations, Ahrefs/SEMrush backlink universe (paid tools), domain authority score. Re-test cadence above plans for closing these gaps incrementally without budget.
