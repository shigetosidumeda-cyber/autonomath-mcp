# jpcite (旧 税務会計AI) — Japanese Institutional Data Search API + MCP Server

*Rebranded 2026-04-30 — `税務会計AI` (alternateName) は jpcite に改名されました。*

*Updated 2026-04-30 — v0.3.1*

[![PyPI version](https://img.shields.io/pypi/v/autonomath-mcp.svg)](https://pypi.org/project/autonomath-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![MCP 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-6E56CF.svg)](https://modelcontextprotocol.io/)
[![CodeQL](https://github.com/shigetosidumeda-cyber/jpintel-mcp/workflows/CodeQL/badge.svg)](https://github.com/shigetosidumeda-cyber/jpintel-mcp/actions/workflows/codeql.yml)
[![Made in Japan](https://img.shields.io/badge/made%20in-%F0%9F%87%AF%F0%9F%87%B5-red.svg)](https://jpcite.com)

日本の制度 (補助金 11,684 / 法令本文 154 + 法令メタデータ 9,484 / 判例 2,065 / 税制 50 / 適格事業者 13,801 / 採択事例 2,286 / 行政処分 1,185) を REST + MCP API で検索。一次資料 URL 付き、¥3/req、anon 50/月 free。

*English: Search Japanese institutional data via REST + MCP API. 11,684 subsidies + 154 laws full-text + 9,484 law catalog stubs (full-text load incremental) + 2,065 court decisions + 50 tax rulesets + 13,801 invoice registrants + 2,286 adoption cases + 1,185 enforcement records. Primary-source URLs, ¥3/request, 50/month free anonymous.*

## What this is

A search index over Japanese institutional public data, exposed as REST + MCP. Returns records with primary-source URLs.

## What this isn't

- Not legal advice (弁護士法 § 72)
- Not tax advice (税理士法 § 52)
- Not 行政書士 work (行政書士法 § 1)
- Not real-time amendment tracking (snapshot data, partial historical diffs)
- Verify primary sources before any business decision

## Coverage

- **11,684 searchable programs** across 47 prefectures + national (補助金・融資・税制・認定; tier S=114 / A=1,340 / B=4,186 / C=6,044; full table = 14,472, tier X quarantine = 2,788)
- **2,286 採択事例 + 108 融資 (担保・個人保証人・第三者保証人 三軸分解) + 1,185 行政処分 + 2,065 court decisions + 362 bids**
- **154 laws full-text indexed + 9,484 law catalog stubs** (e-Gov CC-BY; full-text load incremental — name resolver covers all 9,484, body text 154) **+ 50 tax rulesets + 13,801 invoice registrants (PDL v1.0 delta)**
- **181 exclusion / prerequisite rules** (125 exclude + 17 prerequisite + 15 absolute + 24 other)
- **89 MCP tools** at default gates (39 core + 50 autonomath, includes Wave 21 + Wave 22 composition tools + Wave 23 industry pack wrappers `pack_construction` / `pack_manufacturing` / `pack_real_estate` that bundle programs + saiketsu + 通達 in 1 req), protocol 2025-06-18, stdio. 36協定 2 tools held behind `AUTONOMATH_36_KYOTEI_ENABLED` gate
- **REST API** — endpoints under `/v1/programs/*`, `/v1/laws/*`, `/v1/tax_rulesets/*`, `/v1/case-studies/*`, `/v1/loan-programs/*`, `/v1/enforcement-cases/*`, `/v1/exclusions/*`, `/v1/am/*`. OpenAPI: [`docs/openapi/v1.json`](./docs/openapi/v1.json)
- **Primary-source URLs on 99%+ of rows** (source_url + fetched_at; 12 rows lack URL because the originating small-municipality CMS has no dedicated page; aggregators are excluded)
- **¥3/req metered** (税込 ¥3.30), anonymous 50 req/月 free (no signup; JST 月初リセット)

## 30-second quickstart (Claude Desktop)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop, then ask: 「農業に使える東京都の補助金を教えて。」

### HTTP fallback (uvx インストール時)

`uvx autonomath-mcp` で取得した wheel には DB が同梱されていないため、起動時に
ローカル DB が空であることを検知し、自動で **`api.jpcite.com` への HTTP fallback**
モードに切替えます。匿名 50 req/月 は IP 単位で同一に適用 (¥3/req メータリングも同じ)。

```jsonc
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        // optional: API key (匿名 50 req/月 を超える場合)
        "AUTONOMATH_API_KEY": "ak_live_xxx",
        // optional: staging / self-hosted upstream
        "AUTONOMATH_API_BASE": "https://api.jpcite.com"
      }
    }
  }
}
```

HTTP fallback で完全に動作するツール (top 10): `search_programs` / `get_program` /
`search_case_studies` / `search_loan_programs` / `search_enforcement_cases` /
`search_tax_incentives` / `search_certifications` / `list_open_programs` /
`dd_profile_am` (REST chain hint) / `rule_engine_check` (remote_only)。それ以外
の 89 tools は `error: "remote_only_via_REST_API"` を返し、対応する REST URL を
案内します。フル機能を使う場合はリポジトリを clone してローカル DB を取得して
ください。

## 30-second quickstart (REST)

```bash
# Primary (X-API-Key header, used across our docs)
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都" \
  -H "X-API-Key: YOUR_API_KEY"

# Also supported: Bearer token
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Get an API key at <https://jpcite.com/>.

### Output sample

`GET /v1/programs/search?q=農業&prefecture=東京都` returns (truncated to 1 result):

```json
{
  "total": 47,
  "results": [
    {
      "program_id": "tokyo_agri_dx_2026",
      "name": "東京都 農業 DX 推進事業補助金",
      "amount_yen_max": 5000000,
      "deadline": "2026-06-30",
      "source_url": "https://www.metro.tokyo.lg.jp/.../agri_dx.html",
      "tier": "A"
    }
  ]
}
```

## MCP tools

89 tools at default gates (39 コア + 50 autonomath; includes Wave 21 + Wave 22 composition tools + Wave 23 industry pack wrappers [pack_construction / pack_manufacturing / pack_real_estate]), MCP protocol `2025-06-18`, FastMCP over stdio. 完全なリストと引数は [docs/mcp-tools.md](./docs/mcp-tools.md) を参照 (Single source of truth)。

| Group | Coverage |
|-------|----------|
| **Core (39)** | Programs, Case Studies, Loans, Enforcement, Exclusions, Laws, Court Decisions, Bids, Tax Rulesets, Quota probe (get_usage_status) |
| **AutonoMath universal (16)** | Entity/Fact DB (search_tax_incentives, search_certifications, list_open_programs, enum_values_am, search_by_law, active_programs_at, related_programs, search_acceptance_stats_am, intent_of, reason_answer, get_am_tax_rule, search_gx_programs_am, search_loans_am, check_enforcement_am, search_mutual_plans_am, get_law_article_am) |
| **V4 universal (4)** | get_annotations, validate, get_provenance, get_provenance_for_fact |
| **Phase A (5)** | list_static_resources_am, get_static_resource_am, list_example_profiles_am, get_example_profile_am, deep_health_am (36協定 template gated off) |
| **Lifecycle / graph (4)** | unified_lifecycle_calendar, program_lifecycle, program_abstract_structured, graph_traverse |
| **Other (4)** | prerequisite_chain, rule_engine_check, query_at_snapshot, list_tax_sunset_alerts |

Full list: [docs/mcp-tools.md](https://jpcite.com/docs/mcp-tools/)

## REST API & SDKs

> WARNING: Both SDKs are pre-release — direct git install only. PyPI / npm publish pending.

**OpenAPI spec**

- Live: <https://api.jpcite.com/openapi.json>
- Committed copy: [`docs/openapi/v1.json`](./docs/openapi/v1.json)

**Python SDK** (`autonomath`) — hand-written, lives at [`sdk/python/autonomath/`](./sdk/python/autonomath/). Not yet on PyPI. Direct install from git:

```bash
pip install "git+https://github.com/shigetosidumeda-cyber/jpintel-mcp.git#subdirectory=sdk/python"
```

**TypeScript / JavaScript SDK** (`@autonomath/sdk`) — lives at [`sdk/typescript/src/`](./sdk/typescript/src/). Not yet on npm. Direct install from git:

```bash
npm install "git+https://github.com/shigetosidumeda-cyber/jpintel-mcp.git#subdirectory=sdk/typescript"
```

The package ships dual ESM + CJS output with `.d.ts` and exposes both REST (`@autonomath/sdk`) and MCP (`@autonomath/sdk/mcp`) entry points. Zero runtime dependencies (uses platform `fetch`).

**Runnable examples**

- Python: [`examples/python/`](./examples/python/) — search by prefecture, check exclusions, program detail, pandas CSV export
- TypeScript: [`examples/typescript/`](./examples/typescript/) — search, exclusions, MCP CLI, Next.js page

## Install (Python)

```bash
pip install autonomath-mcp
# or
uvx autonomath-mcp
```

## Data sources

All programs cite primary sources — 経産省, 農林水産省 (MAFF), 日本政策金融公庫 (JFC), 総務省, and 47 都道府県公報. 99%+ records carry `source_url` + `source_fetched_at` lineage (12 rows are small-municipality programs lacking a dedicated CMS page). Schema documented at [/docs/json_ld_strategy](https://jpcite.com/docs/json_ld_strategy).

## Evaluation

Tool quality is publicly verifiable: see [`evals/`](./evals/) for a 79-query gold-standard suite (`gold.yaml` + `run.py`) covering 農業 / 製造 / IT / 創業 / 都道府県 / 税制 / 融資 / 採択事例 / prescreen / 行政処分 / cross-dataset / edge cases / 7 one-shot discovery tools (smb_starter_pack / deadline_calendar / subsidy_combo_finder / similar_cases / subsidy_roadmap_3yr / regulatory_prep_pack). Every `expected_ids` list was generated by calling the live MCP tool against `data/jpintel.db`; CI runs the suite on every PR. Per-tool precision table: see [`docs/per_tool_precision.md`](./docs/per_tool_precision.md). Run locally with `.venv/bin/python evals/run.py`.

## Self-serve dashboards & transparency

- **Dashboard** (authenticated): `GET /v1/me/dashboard` — month-to-date spend, request count, cap state, top tools. See [`docs/dashboard_guide.md`](./docs/dashboard_guide.md).
- **Amendment alerts**: `POST /v1/me/alerts/subscribe` — subscribe by tool / law_id / program_id / industry_jsic / all, with severity gating (critical / important / info). See [`docs/alerts_guide.md`](./docs/alerts_guide.md).
- **Stats** (public transparency): `GET /v1/stats/coverage` (per-prefecture / authority / kind program counts), `GET /v1/stats/freshness` (per-source `source_fetched_at` distribution), `GET /v1/stats/usage` (anonymised request volume).

## Pricing — pay-per-request, no tiers

- **¥3 per request** (税込 ¥3.30) — fully metered, Stripe billing
- **First 50 requests/month free** (anonymous, IP-based, JST monthly reset)
- **No subscription tiers, no seat fees, no annual minimums, no signup required**

## Roadmap (gated cohorts)

These cohorts ship with the schema in place at launch; tools are
gated behind feature flags and primary-source ingest is rolling.

- **V4 absorption** (complete 2026-04-25, ships in v0.3.0) —
  Autonomath absorption CLI landed migrations 046–049 (annotations /
  validation rules / program health + 3 ALTERs) and four universal
  MCP tools (`get_annotations`, `validate`, `get_provenance/{entity}`,
  `get_provenance/fact/{fact}`). Ingest landed: examiner_feedback
  (~16,474 annotations from 8,189 program-resolved feedback) / gbiz
  (~79,876 new corp entities + ~861K corp.* facts) / case-study
  supplement (~1,901 new rows). Tool count 55 → **59**; `am_entities`
  424,054 → **503,930**; `am_entity_facts` 5.26M → **6.12M**. **v0.3.0
  manifest bump landed 2026-04-25** — `pyproject.toml` / `server.json` /
  `mcp-server.json` / `dxt/manifest.json` / `smithery.yaml` now report
  the post-V4 / post-Phase-A numbers. No env flag — universal once shipped.
- **Phase A absorption** (complete 2026-04-25, ships in v0.3.0) —
  +7 MCP tools (`list_static_resources_am`, `get_static_resource_am`,
  `list_example_profiles_am`, `get_example_profile_am`,
  `render_36_kyotei_am`, `get_36_kyotei_metadata_am`, `deep_health_am`)
  + 8 静的タクソノミ + 5 example profiles + 4 utility modules
  (`wareki` / `jp_money` / `jp_constants` / `templates/saburoku_kyotei`)
  + `models/premium_response.py` + `/v1/am/health/deep` mounted on
  `health_router` (no AnonIpLimitDep). Default-gate runtime tool count: **89**
  (36協定 2 tools held behind `AUTONOMATH_36_KYOTEI_ENABLED`; healthcare +
  real_estate cohorts also gated off pending plan execution; `query_at_snapshot` +
  `intent_of` + `reason_answer` gated off pending fix).
- **Healthcare V3** (T+90d, 2026-08-04) — `medical_institutions` +
  `care_subsidies` (migration 039); +6 MCP tools when
  `HEALTHCARE_ENABLED=true`. Plan: [`docs/healthcare_v3_plan.md`](./docs/healthcare_v3_plan.md).
- **Real Estate V5** (T+200d) — `real_estate_programs` +
  `zoning_overlays` (migration 042); +5 MCP tools when
  `REAL_ESTATE_ENABLED=true`. Plan: [`docs/real_estate_v5_plan.md`](./docs/real_estate_v5_plan.md).

## SLA & infrastructure

- **Monthly uptime target: 99.5%** on `api.jpcite.com` (Fly.io
  Tokyo + Cloudflare Pages + Cloudflare WAF). Token-bucket rate-limit
  middleware + WAF managed-ruleset are in front of every request.
  See [`docs/sla.md`](./docs/sla.md).
- **Tokushoho disclosure** — full statutory disclosure under 特定商取引法
  at [`site/tokushoho.html`](./site/tokushoho.html).
- **Spec surfaces** — `site/llms.txt` and `site/llms-full.txt` (JA);
  `site/llms.en.txt` and `site/llms-full.en.txt` (EN) for AI-agent
  discovery.

## Support

- Docs: <https://jpcite.com/docs/>
- Issues: <https://github.com/shigetosidumeda-cyber/jpintel-mcp/issues>
- Email: <info@bookyou.net>

## License

MIT © 2026 [Bookyou株式会社](https://bookyou.net) (T8010001213708) — 代表 梅田茂利
</content>
</invoke>

## Badges

[![PyPI version](https://img.shields.io/pypi/v/autonomath-mcp)](https://pypi.org/project/autonomath-mcp/)
[![PyPI downloads](https://img.shields.io/pypi/dm/autonomath-mcp)](https://pypi.org/project/autonomath-mcp/)
[![License](https://img.shields.io/github/license/shigetosidumeda-cyber/jpintel-mcp)](./LICENSE)
[![MCP 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-6E56CF)](https://modelcontextprotocol.io/specification/2025-06-18)
[![API status](https://img.shields.io/badge/api-status-4c1)](https://jpcite.com/status)

Offline / mirrored copies of the same badges live in [`badges/`](./badges/)
for use in environments where shields.io is unreachable.
