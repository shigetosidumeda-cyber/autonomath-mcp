# jpcite English wedge — foreign-investor cohort

> Reference guide for the 5 English-first MCP tools and 5 REST endpoints
> shipped under `mcp/autonomath_tools/english_wedge.py` and
> `api/english_wedge.py`. Built for foreign-invested SaaS startups
> entering Japan, cross-border M&A pipelines, and FATCA-compliance SaaS
> vendors that need machine-queryable Japanese public-program data with
> primary-source URLs.

## Audience

- Foreign-invested SaaS startups planning Japan entry (KK / GK incorporation, J-visa, 経営管理 visa)
- Cross-border M&A teams running due diligence on Japanese targets
- FATCA / CRS compliance SaaS vendors needing tax-treaty + WHT data
- In-house counsel + cross-border tax advisors at multinationals
- JETRO consultants triangulating against primary-source data

## Why this wedge exists

Japanese public-program data (subsidies, tax incentives, statutes, court
decisions, regulatory enforcement) is overwhelmingly Japanese-only.
JETRO publishes excellent narrative guides, but a foreign-invested entity
that wants to wire Japanese eligibility checks into an LLM agent or DD
pipeline still has to translate the source documents row by row.

The English wedge solves that **without involving an LLM in the
translation loop**: it surfaces the e-Gov 日本法令外国語訳 corpus
(Japanese Ministry of Justice, CC-BY 4.0) plus the Ministry of Finance's
bilateral tax-treaty matrix plus per-program foreign-capital eligibility
flags, all keyed by the same primary-source URLs the Japanese surface
uses.

## Pricing

Same as every other surface on jpcite:

- **¥3 per billable unit** (税込 ¥3.30), metered, no tier
- Anonymous trial: 3 requests/day per IP, JST 翌日 00:00 reset
- Paid keys: ¥3/req metered, no seat fee, no annual minimum

The US SaaS instinct to charge `$0.10/req` or `¥10/req` for an
English-language API is **explicitly rejected**. Solo + zero-touch
operations means no premium tier and no FX uplift; the English surface
is the same Japanese substrate exposed in English with the same metered
contract.

## Operator constraints

- **No LLM in the translation loop.** English text comes from the
  hand-curated `am_law_article.body_en` column (migration 090, e-Gov CC-BY 4.0).
  Translation backfill is a separate offline ETL wave; this wedge only reads.
- **No aggregator.** Every row cites e-Gov / MoF / NTA primary source URLs.
  No JETRO compilation, no second-hand FATCA SaaS feed, no Wikipedia.
- **Disclaimer envelope mandatory.** All five tools surface a `_disclaimer`
  field declaring the response 税理士法 §52 / 国際課税 / 弁護士法 §72 /
  FDI 規制 fence. Output is information retrieval, not advice.
- **Single billing event per call.** A tool that internally runs N SQL
  queries still bills as 1 unit (¥3).

## 5 MCP tools

### `search_laws_en(q: str, limit: int = 10)`

Keyword search restricted to `am_law_article` rows where `body_en IS NOT NULL`.
Returns hits with English title + EN body excerpt + e-Gov source URL.
Sensitive (弁護士法 §72 / 国際課税 fence).

```json
{
  "query": "withholding tax",
  "lang": "en",
  "total": 3,
  "limit": 10,
  "offset": 0,
  "results": [
    {
      "law_canonical_id": "law:income-tax-act",
      "law_name_ja": "所得税法",
      "article_number": "第212条",
      "title": "Withholding Liability",
      "body_en_excerpt": "A person who pays a non-resident or foreign corporation domestic-source income ...",
      "body_en_source_url": "https://www.japaneselawtranslation.go.jp/...",
      "body_en_license": "cc_by_4.0",
      "lang": "en"
    }
  ],
  "_disclaimer": "The English text returned here is a courtesy translation ...",
  "_billing_unit": 1,
  "_next_calls": [
    {"tool": "get_law_article_en", "args": {"law_id": "law:income-tax-act", "article_no": "第212条"}, "rationale": "..."},
    {"tool": "search_laws", "args": {...}, "rationale": "Fall back to JP catalog when EN corpus is thin."}
  ]
}
```

### `get_law_article_en(law_id: str, article_no: str)`

Exact `(law_id, article_no)` lookup, returning the EN translation when
present and a graceful JP fallback warning when not. Mirrors
`law_article_tool.get_law_article(lang='en')` but is a foreign-cohort
first-class entry point. Sensitive (弁護士法 §72).

The JP article is always the only legally authoritative version. When
no EN translation exists, the response carries:

```json
{
  "lang_resolved": "ja",
  "warning": "english_translation_unavailable: e-Gov 日本法令外国語訳 has not yet supplied a CC-BY 4.0 translation for this article. The Japanese body is returned as a fallback."
}
```

### `get_tax_treaty(country_a: str, country_b: str = "JPN")`

Bilateral DTA lookup over `am_tax_treaty` (33 rows live, schema seeds
~80 jurisdictions). `country_b` defaults to `"JPN"` since every row is
bilateral with Japan. Sensitive (税理士法 §52 / 国際課税 fence).

Returned fields:

- `treaty_kind`: `comprehensive` / `tax_info_exchange` / `partial`
- `dta_signed_date`, `dta_in_force_date`
- `withholding_tax_pct`: `{ dividend_general, dividend_parent_subsidiary, interest, royalty }` — treaty rates (not statutory). NULL = "see treaty article" (distinct from 0.0 = exempt under treaty).
- `pe_days_threshold`: PE service days threshold (NULL = OECD default 183d)
- `info_exchange`: `standard` / `crs_only` / `limited` / `none`
- `moaa_arbitration`: BEPS Action 14 仲裁条項 in force (boolean)
- `source_url`: MoF page (政府標準利用規約 v2.0)

### `check_foreign_capital_eligibility(houjin_bangou: str, program_id: str)`

Returns the most-restrictive `foreign_capital_eligibility` flag across
all `am_subsidy_rule` rows for the given program. `houjin_bangou` is
input echo only (the flag is per-program, not per-corp). Sensitive
(行政書士法 §1 / FDI 規制).

Severity ordering (most restrictive wins):

1. `excluded` — text explicitly excludes 外資系 / 外国法人
2. `case_by_case` — text says 「個別協議」/「事務局判断」
3. `eligible_with_caveat` — eligible but extra docs (経営管理 visa / J-visa / 事業所登記) needed
4. `eligible` — text explicitly confirms foreign-capital OK
5. `silent` (default) — text does not address the question. Japanese statutory presumption is permissive; most national programs do NOT exclude foreign-owned KKs unless they explicitly say so.

### `find_fdi_friendly_subsidies(industry_jsic: str, foreign_pct: int = 100, limit: int = 20)`

Filter programs by industry JSIC (major A-T or numeric medium/minor) AND
`foreign_capital_eligibility != 'excluded'`. Ranks by eligibility flag
(eligible > eligible_with_caveat > case_by_case > silent).

`foreign_pct` is **input echo only** — the database has no per-program
foreign-equity threshold; the field exists so the caller can record the
assumption that fed the lookup. Sensitive (行政書士法 §1 / FDI 規制).

## 5 REST endpoints

```
GET  /v1/en/laws/search?q=corporate+tax&limit=10
GET  /v1/en/laws/{law_id}/articles/{article_no}
GET  /v1/en/tax_treaty/{country_a}?country_b=JPN
GET  /v1/en/foreign_capital_eligibility?program_id=...&houjin_bangou=...
GET  /v1/en/fdi_subsidies?industry_jsic=E&foreign_pct=100&limit=20
```

The MCP impl in `mcp/autonomath_tools/english_wedge.py` is the single
source of truth — REST is a thin wrapper.

## Migration dependencies

- **090** (`scripts/migrations/090_law_article_body_en.sql`):
  `am_law_article.body_en` + `body_en_source_url` + `body_en_fetched_at`
  + `body_en_license` columns. Backfill via offline ETL.
- **091** (`scripts/migrations/091_tax_treaty.sql`): `am_tax_treaty`
  table with 8 hand-curated seed rows; subsequent expansion to 33 rows
  via `scripts/seed_tax_treaty_matrix.py`.
- **092** (`scripts/migrations/092_foreign_capital_eligibility.sql`):
  `am_subsidy_rule.foreign_capital_eligibility` column with heuristic
  on-boot backfill.

## License

- English law text: e-Gov 日本法令外国語訳 (CC-BY 4.0). The Japanese
  original is the only legally authoritative version.
- Tax treaty rows: 政府標準利用規約 v2.0 (gov_standard) from MoF + NTA
  primary sources.
- Subsidy / program data: program-specific (typically 政府標準利用規約 v2.0).

## Disclaimer

This wedge is **information retrieval, not legal or tax advice**. Every
response carries a `_disclaimer` envelope declaring the surface 税理士法
§52 / 弁護士法 §72 / 行政書士法 §1 / FDI 規制 fence. For binding
interpretation, consult a Japanese qualified attorney / 税理士 / 行政書士.
jpcite (operator: Bookyou株式会社, T8010001213708) assumes no liability
for downstream legal or tax decisions.
