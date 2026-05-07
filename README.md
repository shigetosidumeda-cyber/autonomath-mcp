<p align="center">
  <a href="https://jpcite.com"><img src="https://www.jpcite.com/assets/github-social-card.png" alt="jpcite — Evidence-first context layer for Japanese public-program data" width="800"></a>
</p>

# jpcite — Evidence-first context layer for Japanese public-program data

mcp-name: io.github.shigetosidumeda-cyber/autonomath-mcp

**v0.3.4 LIVE on Fly.io Tokyo** — production at `api.jpcite.com` (deployment `01KR0AGKRFD39QZZJ10VWYZXS5`, GH_SHA `b1de8b2`, snapshot 2026-05-07). Current public docs and release tags are the source of truth for version and pricing.

[![PyPI version](https://img.shields.io/pypi/v/autonomath-mcp.svg)](https://pypi.org/project/autonomath-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![MCP 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-6E56CF.svg)](https://modelcontextprotocol.io/)
[![Made in Japan](https://img.shields.io/badge/made%20in-%F0%9F%87%AF%F0%9F%87%B5-red.svg)](https://jpcite.com)

**Launch state (2026-05-07 hardening)** — quality gates cleared, LIVE on Fly Tokyo:

[![mypy strict](https://img.shields.io/badge/mypy%20strict-0%20errors-4c1.svg)](./CHANGELOG.md)
[![bandit](https://img.shields.io/badge/bandit-0%20findings-4c1.svg)](./CHANGELOG.md)
[![acceptance](https://img.shields.io/badge/acceptance-286%2F286-4c1.svg)](./tests/)
[![smoke](https://img.shields.io/badge/smoke-17%2F17%20%2B%205%2F5-4c1.svg)](./tests/)
[![pre-commit](https://img.shields.io/badge/pre--commit-16%2F16-4c1.svg)](./.pre-commit-config.yaml)
[![ruff](https://img.shields.io/badge/ruff-0%20violations-4c1.svg)](./pyproject.toml)
[![API status](https://img.shields.io/badge/api-LIVE%20Fly%20Tokyo-4c1.svg)](https://jpcite.com/status)

LLM agent / RAG パイプラインに渡す前の compact context を REST + MCP で返します。公開行には 出典 URL + content_hash + 取得日時 が付き、官公庁・自治体・公庫・公式事業者ページなど確認可能な出典を優先します。**11,601 searchable programs / 9,484 laws / 1,185 enforcement cases + 22,258 enforcement-detail records / 139 MCP tools default (146 cohort runtime) / 33 DEEP spec verified / 業法 7-fence (弁護士法 §72・税理士法 §52・行政書士法 §1・社労士法 §27・司法書士法 §3・宅建業法 §47・労基法 §36) / median 7 day freshness**。LLM は呼び出さず、民間まとめサイトにも依存しません。通常の検索・取得は ¥3/billable unit、anon 3/日 free。

*English: Evidence-first context layer for Japanese public-program data, exposed as REST + MCP. Published rows return source URL + content_hash + fetched_at so an LLM agent or RAG pipeline can ground answers on verifiable official sources — no LLM calls inside the service, no aggregator scraping. **11,601 searchable programs / 9,484 laws / 1,185 enforcement cases + 22,258 enforcement-detail records / 139 MCP tools default (146 cohort runtime) / 33 DEEP spec verified / 7-statute professional fence / median 7 day freshness.** ¥3/billable unit for normal search/detail calls, 3/day free anonymous.*

Use jpcite when an AI answer needs Japanese public-program evidence, source URLs, fetched_at metadata, compatibility rules, enforcement checks, or known gaps before drafting prose. Skip it for short general questions, translation, brainstorming, or topics that do not need source-linked Japanese institutional data.

Evidence Packet lets a caller give GPT/Claude compact, source-linked input before drafting: `source_url`, `source_fetched_at`, `known_gaps`, and caller-supplied input-context estimates can be compared with the caller baseline to explain what context was used. JSON Evidence Packets may also include top-level `decision_insights` (`why_review`, `next_checks`, `evidence_gaps`) for AI answer scaffolding. `/v1/intel/match` adds AI-facing `next_questions`, `eligibility_gaps`, and `document_readiness` so an agent can turn matched programs into customer interview questions, eligibility-gap checks, and document-readiness lists. `/v1/intel/bundle/optimal` `decision_support` explains the selected bundle's rationale, decision signals, and follow-up actions; `/v1/intel/houjin/{houjin_id}/full` `decision_support` turns corporate 360 evidence into corporate DD, credit-precheck notes, and monitoring suggestions. Funding stack/compat `next_actions` are AI-facing follow-up actions for compatibility tables, pre-application checks, and alternative bundle proposals. Output tokens, reasoning tokens, tool calls, search, cache behavior, and model choice remain controlled by the caller.

## How jpcite compares to single-source MCP servers

jpcite is the **横断 + Evidence Packet** layer. The 3 active single-source Japanese MCP servers each handle one slice — they are **complementary**, not competitive:

- **vs jgrants-mcp** ([`digital-go-jp/jgrants-mcp-server`](https://github.com/digital-go-jp/jgrants-mcp-server), 5 tools, jGrants 補助金 only): jpcite adds 法令 / 判例 / 行政処分 / 適格事業者 / 法人 360° / 排他併用判定. Use jgrants-mcp for the grant application path; use jpcite for cross-source compliance check. → [/compare/jgrants-mcp/](https://jpcite.com/compare/jgrants-mcp/)
- **vs tax-law-mcp** ([`kentaroajisaka/tax-law-mcp`](https://github.com/kentaroajisaka/tax-law-mcp), 7 tools, e-Gov + NTA + KFS live scrape): jpcite adds 50 structured tax_rulesets + 9,484 e-Gov laws + 28,201 article rows pre-indexed (median <100ms, no live-scrape latency) + 通達 cross-ref to 制度 / 採択 / 行政処分. Use jpcite for pre-indexed answers + 通達 cross-ref; use tax-law-mcp for ad-hoc lookups. → [/compare/tax-law-mcp/](https://jpcite.com/compare/tax-law-mcp/)
- **vs japan-corporate-mcp** ([`yamariki-hub/japan-corporate-mcp`](https://github.com/yamariki-hub/japan-corporate-mcp), 8 tools, gBizINFO + EDINET + e-Stat live API, 3 user keys required): jpcite ships pre-indexed 166,969 法人 + 13,801 適格事業者 + 1,185 行政処分 + 22,258 enforcement detail with anonymous trial (no user API key required). Use jpcite for analyst pre-screening; use japan-corporate-mcp for live regulator pulls when keys are already provisioned. → [/compare/japan-corporate-mcp/](https://jpcite.com/compare/japan-corporate-mcp/)

## What this is

An evidence-first context layer over Japanese institutional public data, exposed as REST + MCP. Published rows carry a source URL, a content_hash, and a fetched_at timestamp so downstream LLM agents or RAG pipelines can cite back to verifiable official source pages without re-crawling.

## Latest hardening — 2026-05-07 (LIVE)

**v0.3.4** is live in production at `api.jpcite.com` on Fly.io Tokyo + Cloudflare Pages + Stripe metered billing. The 5/7 hardening pass cleared every quality gate without changing the public surface (no new tools, no schema changes, no count bumps).

- **Wave 21** (5 composition tools, AUTONOMATH_COMPOSITION_ENABLED, default ON): `apply_eligibility_chain_am`, `find_complementary_programs_am`, `simulate_application_am`, `track_amendment_lineage_am`, `program_active_periods_am`.
- **Wave 22** (5 compounding-call tools, AUTONOMATH_WAVE22_ENABLED, default ON): `match_due_diligence_questions`, `prepare_kessan_briefing`, `forecast_program_renewal`, `cross_check_jurisdiction`, `bundle_application_kit`. Migration 104 seeds 60 DD question templates across 7 categories.
- **Wave 23** (3 industry packs, AUTONOMATH_INDUSTRY_PACKS_ENABLED, default ON): `pack_construction` (JSIC D), `pack_manufacturing` (JSIC E), `pack_real_estate` (JSIC K). Each returns top programs + 国税不服審判所 裁決事例 + 通達 references in one envelope.
- **Section A data quality lift** — A4 done (`am_source.content_hash` NULL 281→0), A5 partial (`last_verified` 1→94), A6 done (`am_entity_facts.source_id` 0→81,787), D9 done (`programs.aliases_json` 82→9,996), B13 partial (prefecture 欠損 9,509→6,011), E1 done (`license_review_queue.csv` 1,425 行).
- **33 DEEP spec retroactive verify** — DEEP-22 through DEEP-65 walked on src/ side, **0 inconsistency vs spec**. Covers verifier deepening, time-machine, business-law detector, cohort persona kit, 自治体補助金, e-Gov パブコメ, identity_confidence golden, organic outreach playbook.
- **業法 7-fence** — every sensitive surface (税理士法 §52・弁護士法 §72・行政書士法 §1・社労士法 §27・司法書士法 §3・宅建業法 §47・労基法 §36) carries a `_disclaimer` envelope; 36協定 renderer is gated behind `AUTONOMATH_36_KYOTEI_ENABLED` (default off) pending 社労士 supervision review.
- **Deploy hardening** — 4 fixes in `.github/workflows/deploy.yml` (smoke gate sleep 25s→60s + `--max-time` 15s→30s + `flyctl status` pre-probe + size-guarded hydrate skip + explicit `rm -f` before sftp). Fly p99 machine swap exceeds 25s and the previous timing produced false-positive smoke fails.

See [`CHANGELOG.md`](./CHANGELOG.md) for the full 40-commit walk.

## What this isn't

- Not legal advice (弁護士法 § 72)
- Not tax advice (税理士法 § 52)
- Not 行政書士 work (行政書士法 § 1)
- Not real-time amendment tracking (snapshot data, partial historical diffs)
- Verify primary sources before any business decision

## Coverage

- **Source-linked records** — most published rows include `source_url`, `content_hash`, and `source_fetched_at`; known source gaps are surfaced. Known second-tier aggregator pages are excluded from citation sources where detected.
- **11,601 searchable programs** across 47 prefectures + national (補助金・融資・税制・認定; tier S=114 / A=1,340 / B=4,186 / C=5,961; full catalog = 14,472, 2,871 publication-review rows)
- **2,286 採択事例 + 108 融資 (担保・個人保証人・第三者保証人 三軸分解) + 1,185 行政処分 + 22,258 enforcement-detail records + 2,065 court decisions + 362 bids**
- **6,493 laws full-text indexed + 9,484 law metadata records** (e-Gov CC-BY; full-text coverage is incremental — name resolver covers all 9,484, body text index covers 6,493) **+ 50 tax rulesets + 13,801 invoice registrants (PDL v1.0 delta)**
- **181 exclusion / prerequisite rules** (125 exclude + 17 prerequisite + 15 absolute + 24 other) — surfaced as structured eligibility predicates, not free-text
- **139 MCP tools** in the standard public configuration, protocol 2025-06-18, stdio. See [`docs/mcp-tools.md`](./docs/mcp-tools.md) for the current public tool catalogue and arguments. Optional labor-agreement tools are disabled unless explicitly enabled.
- **REST API** — endpoints under `/v1/programs/*`, `/v1/laws/*`, `/v1/tax_rulesets/*`, `/v1/case-studies/*`, `/v1/loan-programs/*`, `/v1/enforcement-cases/*`, `/v1/exclusions/*`, `/v1/am/*`. OpenAPI: [`docs/openapi/v1.json`](./docs/openapi/v1.json)
- **No LLM inside the service** — no external LLM calls in the data/evidence path. Content endpoints are generated from the corpus and deterministic application code; reasoning lives in the caller's agent.
- **Median 7-day freshness** on tier S/A program rows; per-source `source_fetched_at` distribution exposed at `GET /v1/stats/freshness`
- **¥3/billable unit metered** (tax-exclusive; 税込 ¥3.30). Normal search/detail calls are 1 unit; batch/export endpoints document their formula. Anonymous 3 req/日 free (no signup; JST 翌日リセット)

## 30-second quickstart (Claude Desktop)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop, then ask: 「東京都で設備投資に使える補助金を教えて。」

### HTTP fallback (uvx インストール時)

`uvx autonomath-mcp` で取得した wheel には DB が同梱されていないため、起動時に
ローカル DB が空であることを検知し、自動で **`api.jpcite.com` への HTTP fallback**
モードに切替えます。匿名 3 req/日 は IP 単位で同一に適用し、paid key は ¥3/billable unit でメータリングします。

```jsonc
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        // optional: jpcite API key (匿名 3 req/日 を超える場合)
        // This is sent to api.jpcite.com as X-API-Key; it is not an LLM key.
        "JPCITE_API_KEY": "am_xxx",
        // optional: custom upstream
        "JPCITE_API_BASE": "https://api.jpcite.com"
      }
    }
  }
}
```

このキーは jpcite API 用です。jpcite サービス内で OpenAI / Anthropic / Gemini などの
LLM API は呼びません。

HTTP fallback で完全に動作するツール (top 10): `search_programs` / `get_program` /
`search_case_studies` / `search_loan_programs` / `search_enforcement_cases` /
`search_tax_incentives` / `search_certifications` / `list_open_programs` /
`dd_profile_am` (REST chain hint) / `rule_engine_check` (remote_only)。上記以外
の default-on MCP tools は `error: "remote_only_via_REST_API"` を返し、対応する REST URL を
案内します。フル機能を使う場合はリポジトリを clone してローカル DB を取得して
ください。

## 30-second quickstart (REST)

```bash
# Primary (X-API-Key header, used across our docs)
curl "https://api.jpcite.com/v1/programs/search?q=設備投資&prefecture=東京都" \
  -H "X-API-Key: am_xxx"

# Also supported: Bearer token
curl "https://api.jpcite.com/v1/programs/search?q=設備投資&prefecture=東京都" \
  -H "Authorization: Bearer am_xxx"
```

Get an API key at <https://jpcite.com/dashboard>.

### Output sample

`GET /v1/programs/search?q=設備投資&prefecture=東京都` returns (truncated to 1 result):

```json
{
  "total": 47,
  "results": [
    {
      "unified_id": "UNI-example-energy-dx",
      "primary_name": "東京都 中小企業 省エネ設備導入支援",
      "amount_max_man_yen": 500,
      "application_window": {"end_date": "2026-06-30"},
      "source_url": "https://www.metro.tokyo.lg.jp/.../energy-dx.html",
      "source_fetched_at": "2026-04-30T00:00:00+09:00",
      "tier": "A"
    }
  ]
}
```

## MCP tools

139 tools at default gates, MCP protocol `2025-06-18`, FastMCP over stdio. 完全なリストと引数は [docs/mcp-tools.md](./docs/mcp-tools.md) を参照 (Single source of truth)。

| Group | Coverage |
|-------|----------|
| **Core** | Programs, Case Studies, Loans, Enforcement, Exclusions, Laws, Court Decisions, Bids, Tax Rulesets, Quota probe (get_usage_status) |
| **Audit / composition** | audit_batch_evaluate, compose_audit_workpaper, resolve_citation_chain |
| **jpcite generic** | Entity/Fact DB, funding stack, evidence/source manifests, lifecycle/graph/rule-engine, tax/certification/loan/enforcement wrappers |
| **V4 universal** | get_annotations, validate, get_provenance, get_provenance_for_fact |
| **Static resources** | list_static_resources_am, get_static_resource_am, list_example_profiles_am, get_example_profile_am, deep_health_am |
| **NTA corpus** | cite_tsutatsu, find_bunsho_kaitou, find_saiketsu, find_shitsugi |
| **Eligibility composition** | apply_eligibility_chain_am, find_complementary_programs_am, program_active_periods_am, simulate_application_am, track_amendment_lineage_am |
| **Application composition** | bundle_application_kit, cross_check_jurisdiction, forecast_program_renewal, match_due_diligence_questions, prepare_kessan_briefing |
| **Industry packs** | pack_construction, pack_manufacturing, pack_real_estate |
| **Corporate layer** | get_houjin_360_am, list_edinet_disclosures, search_invoice_by_houjin_partial |

Full list: [docs/mcp-tools.md](https://jpcite.com/docs/mcp-tools/)

## REST API & SDKs

> WARNING: The MCP package is published on PyPI; REST SDKs remain pre-release.

**OpenAPI spec**

- Agent-safe import: <https://api.jpcite.com/v1/openapi.agent.json> (`docs/openapi/agent.json`) for ChatGPT Custom GPT Actions and AI tool importers.
- Full developer spec: <https://api.jpcite.com/v1/openapi.json> (`docs/openapi/v1.json`) for SDK generators, Postman, and complete REST reference.
- AI-facing value fields: Evidence Packet `decision_insights` summarizes why to review, next checks, and evidence gaps; `/v1/intel/match` `next_questions`, `eligibility_gaps`, and `document_readiness` summarize customer questions, unresolved eligibility checks, and document readiness; funding stack/compat `next_actions` turn pair verdicts into compatibility-table checks, pre-application checklist items, and alternative bundle prompts; `/v1/intel/bundle/optimal` `decision_support` summarizes bundle rationale, decision signals, and next actions; `/v1/intel/houjin/{houjin_id}/full` `decision_support` summarizes corporate DD questions, credit precheck notes, and monitoring suggestions.

**Python MCP package** (`autonomath-mcp`) — package name is kept for client compatibility:

```bash
pip install autonomath-mcp
```

**TypeScript / JavaScript SDK** (`@autonomath/sdk`) — package name is kept for compatibility. Public package release is pending; the REST API v1 surface is the stable contract while the SDK remains pre-release.

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

Program records prioritize primary sources such as 経産省, 農林水産省 (MAFF), 日本政策金融公庫 (JFC), 総務省, and 47 都道府県公報. Most public records carry `source_url` + `source_fetched_at` lineage, with known gaps documented. Public structured data is exposed through `/structured/`, `sitemap-structured.xml`, and inline JSON-LD on generated program pages.

## Evaluation

Tool quality is publicly verifiable: see [`evals/`](./evals/) for a 79-query gold-standard suite (`gold.yaml` + `run.py`) covering 農業 / 製造 / IT / 創業 / 都道府県 / 税制 / 融資 / 採択事例 / prescreen / 行政処分 / cross-dataset / edge cases / 7 one-shot discovery tools (smb_starter_pack / deadline_calendar / subsidy_combo_finder / similar_cases / subsidy_roadmap_3yr / regulatory_prep_pack). Every `expected_ids` list was generated against the local evaluation snapshot; CI runs the suite on every PR. Per-tool precision table: see [`docs/per_tool_precision.md`](./docs/per_tool_precision.md). Run locally with `.venv/bin/python evals/run.py`.

## Self-serve dashboards & transparency

- **Dashboard** (authenticated): `GET /v1/me/dashboard` — month-to-date spend, request count, cap state, top tools. See [`docs/dashboard_guide.md`](./docs/dashboard_guide.md).
- **Amendment alerts**: `POST /v1/me/alerts/subscribe` — subscribe by tool / law_id / program_id / industry_jsic / all, with severity gating (critical / important / info). See [`docs/alerts_guide.md`](./docs/alerts_guide.md).
- **Stats** (public transparency): `GET /v1/stats/coverage` (per-prefecture / authority / kind program counts), `GET /v1/stats/freshness` (per-source `source_fetched_at` distribution), `GET /v1/stats/usage` (anonymised request volume).

## Pricing — metered units, no tiers

- **¥3 per billable unit** (税込 ¥3.30) — normal search/detail calls are 1 unit, while batch/export endpoints bill by documented fan-out units
- **First 3 requests/day free** (anonymous, IP-based, JST daily reset)
- **No subscription tiers, no seat fees, no annual minimums**; anonymous trial calls do not require signup and remain capped at 3 requests/day per IP.
- **Cost preview and context estimates** — use `/v1/cost/preview` for jpcite billable-unit estimates. Use evidence packet `include_compression=true` to compare caller-supplied input-context estimates with the caller baseline. Provider output/reasoning/search/cache costs remain outside jpcite.

## Optional disabled domains

The standard distribution exposes 139 tools for Japanese public-program
search, evidence, provenance, tax rulesets, laws, court decisions, bids,
invoice registrants, and related entity facts. Additional domain-specific
surfaces are intentionally disabled unless enabled through support-managed
feature flags.

- Labor-agreement renderers are disabled by default and are not part of the
  public tool surface.
- Healthcare and real-estate datasets are disabled by default until their
  primary-source coverage and disclaimers are ready for public use.
- Experimental reasoning tools are disabled by default; production calls
  should use the documented search, evidence, provenance, and rule-check tools.

Use [`docs/mcp-tools.md`](./docs/mcp-tools.md) for the current public tool
catalogue and [`docs/honest_capabilities.md`](./docs/honest_capabilities.md)
for capability boundaries.

## SLA & infrastructure

- **Monthly uptime target: 99.0%** on `api.jpcite.com` (Fly.io
  Tokyo + Cloudflare Pages + Cloudflare WAF). Token-bucket rate-limit
  middleware + WAF managed-ruleset are in front of every request.
  See [`docs/sla.md`](./docs/sla.md).
- **Tokushoho disclosure** — full statutory disclosure under 特定商取引法
  at [`site/tokushoho.html`](./site/tokushoho.html).
- **Spec surfaces** — `site/llms.txt` and `site/llms-full.txt` (JA);
  `site/llms.en.txt` and `site/llms-full.en.txt` (EN) for AI-agent
  discovery.

## Known limitations (2026-05-07 LIVE)

Honest snapshot of the residual gaps that exist in the live `v0.3.4` deployment:

- **Frontend stale-state recovery in progress** — some Cloudflare Pages cohort routes still render against pre-rename brand text in cached HTML; full purge sweep underway. The REST + MCP API surface is unaffected.
- **OAuth UI residual** — dashboard sign-in still surfaces the legacy provider button layout. Server-side OAuth chains (`/v1/auth/*`) work correctly; the cosmetic cleanup is queued on the frontend track.
- **Tool count drift** — manifests claim 139 tools while the runtime cohort serves 146 (7 post-manifest tools landed in source: DEEP-37/44/45/49..58/64/65). This is intentional hold-at-139 per `R8_MANIFEST_BUMP_EVAL_2026-05-07.md`; the next intentional manifest bump will reconcile.
- **3 broken tools gated off** — `query_at_snapshot` (migration 067 missing), `intent_of`, `reason_answer` (reasoning package missing). Surfaced via env flags, not removed.
- **`am_amount_condition` quality** — 250,946 rows on disk; majority are template-default ¥500K/¥2M values from a broken ETL pass. Re-validation in progress, do not surface aggregate count externally.
- **`am_amendment_snapshot` time-series fidelity** — 14,596 captures; only ~2,500 carry content hash and 144 carry definitive `effective_from` dates. Time-series only firm on the 144 dated rows.
- **Construction saiketsu corpus thinness** — `nta_saiketsu` has only 137 rows; the construction industry pack yields 0-1 法人税/消費税 citations per call. Not a code defect, will compound naturally as ingest matures.

## Support

- Docs: <https://jpcite.com/docs/> (search: built-in lunr; [Algolia DocSearch](https://docsearch.algolia.com/apply/) integration pending OSS-program approval)
- Email: <info@bookyou.net>

## License

MIT © 2026 jpcite

---

Keywords: mcp, mcp-server, mcp-tools, claude, rag, agent-tools, japan, japanese, legal-tech, subsidies, grants, loans, tax, tax-incentives, corporate-registry, enforcement, evidence, citation, government, compliance, jpcite, autonomath-mcp, 補助金, 助成金, 融資, 税制優遇, 認定制度, 採択事例, 行政処分, 国税庁, e-Gov, mcp-2025-06-18
## Badges

[![PyPI version](https://img.shields.io/pypi/v/autonomath-mcp)](https://pypi.org/project/autonomath-mcp/)
[![PyPI downloads](https://img.shields.io/pypi/dm/autonomath-mcp)](https://pypi.org/project/autonomath-mcp/)
[![License](https://img.shields.io/github/license/shigetosidumeda-cyber/autonomath-mcp)](./LICENSE)
[![MCP 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-6E56CF)](https://modelcontextprotocol.io/specification/2025-06-18)
[![API status](https://img.shields.io/badge/api-status-4c1)](https://jpcite.com/status)

Offline / mirrored copies of the same badges live in [`badges/`](./badges/)
for use in environments where shields.io is unreachable.
