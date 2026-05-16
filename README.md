<p align="center">
  <a href="https://jpcite.com"><img src="https://jpcite.com/assets/github-social-card.png" alt="jpcite — Evidence-first context layer for Japanese public-program data" width="800"></a>
</p>

# jpcite — Evidence-first context layer for Japanese public-program data

mcp-name: io.github.shigetosidumeda-cyber/autonomath-mcp

**v0.4.0 LIVE on Fly.io Tokyo** — production at `api.jpcite.com`. Current public docs, manifests, and release tags are the source of truth for version and pricing.

[![PyPI version](https://img.shields.io/pypi/v/autonomath-mcp.svg)](https://pypi.org/project/autonomath-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![MCP 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-6E56CF.svg)](https://modelcontextprotocol.io/)
[![Made in Japan](https://img.shields.io/badge/made%20in-%F0%9F%87%AF%F0%9F%87%B5-red.svg)](https://jpcite.com)

[![smithery badge](https://smithery.ai/badge/@bookyou/jpcite)](https://smithery.ai/server/@bookyou/jpcite)
[![Glama MCP](https://img.shields.io/badge/Glama-MCP%20Server-7C3AED.svg?logo=anthropic&logoColor=white)](https://glama.ai/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp)
[![mcp.so](https://img.shields.io/badge/mcp.so-Listed-2563EB.svg)](https://mcp.so/server/jpcite/bookyou)
[![mcphub.dev](https://img.shields.io/badge/mcphub-Listed-0EA5E9.svg)](https://mcphub.dev/servers/jpcite)
[![awesome-mcp](https://img.shields.io/badge/awesome--mcp-pending-yellow.svg)](https://github.com/punkpeye/awesome-mcp-servers/pull/6192)

**Launch state (2026-05-07 hardening)** — quality gates cleared, LIVE on Fly Tokyo:

[![mypy strict](https://img.shields.io/badge/mypy%20strict-0%20errors-4c1.svg)](./CHANGELOG.md)
[![bandit](https://img.shields.io/badge/bandit-0%20findings-4c1.svg)](./CHANGELOG.md)
[![acceptance](https://img.shields.io/badge/acceptance-286%2F286-4c1.svg)](./tests/)
[![smoke](https://img.shields.io/badge/smoke-17%2F17%20%2B%205%2F5-4c1.svg)](./tests/)
[![pre-commit](https://img.shields.io/badge/pre--commit-16%2F16-4c1.svg)](./.pre-commit-config.yaml)
[![ruff](https://img.shields.io/badge/ruff-0%20violations-4c1.svg)](./pyproject.toml)
[![API status](https://img.shields.io/badge/api-LIVE%20Fly%20Tokyo-4c1.svg)](https://jpcite.com/status)

jpcite は、AI agent / 業務ワークフローが回答文を書く前に使う制度データ圧縮レイヤーです。長い PDF・検索結果・官公庁ページを毎回 LLM に投げる前に、source_url、content_hash、取得日時、known gaps、互換・排他ルール付きの小さい Evidence Packet へ変換します。公開 catalog の現在値は `docs/mcp-tools.md` と `site/.well-known/*` を参照してください。LLM は呼び出さず、民間まとめサイトにも依存しません。通常の検索・取得は ¥3/billable unit、anon 3/日 free。

*English: jpcite is a context-compression layer for Japanese institutional public data before AI agents draft answers. It turns long PDFs, search results, and official web pages into compact Evidence Packets with source URLs, content hashes, fetched timestamps, known gaps, and compatibility/exclusion rules. The live public catalogue is exposed through `docs/mcp-tools.md` and `site/.well-known/*`. No server-side LLM calls, no aggregator scraping. ¥3/billable unit for normal search/detail calls, 3/day free anonymous.*

Use jpcite when an AI answer needs Japanese public-program evidence, source URLs, fetched_at metadata, compatibility rules, enforcement checks, or known gaps before drafting prose. Skip it for short general questions, translation, brainstorming, or topics that do not need source-linked Japanese institutional data.

Evidence Packet lets a caller give GPT/Claude compact, source-linked input before drafting: `source_url`, `source_fetched_at`, `known_gaps`, and caller-supplied input-context estimates can be compared with the caller baseline to explain what context was used. JSON Evidence Packets may also include top-level `decision_insights` (`why_review`, `next_checks`, `evidence_gaps`) for AI answer scaffolding. `/v1/intel/match` adds AI-facing `next_questions`, `eligibility_gaps`, and `document_readiness` so an agent can turn matched programs into customer interview questions, eligibility-gap checks, and document-readiness lists. `/v1/intel/bundle/optimal` `decision_support` explains the selected bundle's rationale, decision signals, and follow-up actions; `/v1/intel/houjin/{houjin_id}/full` `decision_support` turns corporate 360 evidence into corporate DD, credit-precheck notes, and monitoring suggestions. Funding stack/compat `next_actions` are AI-facing follow-up actions for compatibility tables, pre-application checks, and alternative bundle proposals. Output tokens, reasoning tokens, tool calls, search, cache behavior, and model choice remain controlled by the caller.

## How jpcite compares to single-source MCP servers

jpcite is the **横断 + Evidence Packet** layer. The 3 active single-source Japanese MCP servers each handle one slice — they are **complementary**, not competitive:

- **vs jgrants-mcp** ([`digital-go-jp/jgrants-mcp-server`](https://github.com/digital-go-jp/jgrants-mcp-server), 5 tools, jGrants 補助金 only): jpcite adds 法令 / 判例 / 行政処分 / 適格事業者 / 法人 360° / 排他併用判定. Use jgrants-mcp for the grant application path; use jpcite for cross-source compliance check. → [/compare/jgrants-mcp/](https://jpcite.com/compare/jgrants-mcp/)
- **vs tax-law-mcp** ([`kentaroajisaka/tax-law-mcp`](https://github.com/kentaroajisaka/tax-law-mcp), 7 tools, e-Gov + NTA + KFS live scrape): jpcite adds 50 structured tax_rulesets + 9,484 e-Gov laws + 28,201 article rows pre-indexed (median <100ms, no live-scrape latency) + 通達 cross-ref to 制度 / 採択 / 行政処分. Use jpcite for pre-indexed answers + 通達 cross-ref; use tax-law-mcp for ad-hoc lookups. → [/compare/tax-law-mcp/](https://jpcite.com/compare/tax-law-mcp/)
- **vs japan-corporate-mcp** ([`yamariki-hub/japan-corporate-mcp`](https://github.com/yamariki-hub/japan-corporate-mcp), 8 tools, gBizINFO + EDINET + e-Stat live API, 3 user keys required): jpcite ships pre-indexed 166,969 法人 + 13,801 適格事業者 + 1,185 行政処分 + 22,258 enforcement detail with anonymous trial (no user API key required). Use jpcite for analyst pre-screening; use japan-corporate-mcp for live regulator pulls when keys are already provisioned. → [/compare/japan-corporate-mcp/](https://jpcite.com/compare/japan-corporate-mcp/)

## What this is

An evidence-first output layer over Japanese institutional public data, exposed as REST + MCP. Published rows carry a source URL, a content_hash, and a fetched_at timestamp so downstream AI agents can cite back to verifiable official source pages without re-crawling or sending long raw documents into the model.

## Latest release — 2026-05-12 (LIVE)

**v0.4.0** is live in production at `api.jpcite.com` on Fly.io Tokyo + Cloudflare Pages + Stripe metered billing. The 5/12 release keeps pricing and public tool count stable while aligning the MCP/OpenAPI manifests, monitoring substrate, and discovery surfaces.

- **Wave 21** (5 composition tools, AUTONOMATH_COMPOSITION_ENABLED, default ON): `apply_eligibility_chain_am`, `find_complementary_programs_am`, `simulate_application_am`, `track_amendment_lineage_am`, `program_active_periods_am`.
- **Wave 22** (5 compounding-call tools, AUTONOMATH_WAVE22_ENABLED, default ON): `match_due_diligence_questions`, `prepare_kessan_briefing`, `forecast_program_renewal`, `cross_check_jurisdiction`, `bundle_application_kit`. Migration 104 seeds 60 DD question templates across 7 categories.
- **Wave 23** (3 industry packs, AUTONOMATH_INDUSTRY_PACKS_ENABLED, default ON): `pack_construction` (JSIC D), `pack_manufacturing` (JSIC E), `pack_real_estate` (JSIC K). Each returns top programs + 国税不服審判所 裁決事例 + 通達 references in one envelope.
- **Section A data quality lift** — A4 done (`am_source.content_hash` NULL 281→0), A5 partial (`last_verified` 1→94), A6 done (`am_entity_facts.source_id` 0→81,787), D9 done (`programs.aliases_json` 82→9,996), B13 partial (prefecture 欠損 9,509→6,011), E1 done (`license_review_queue.csv` 1,425 行).
- **33 DEEP spec retroactive verify** — DEEP-22 through DEEP-65 walked on src/ side, **0 inconsistency vs spec**. Covers verifier deepening, time-machine, business-law detector, cohort persona kit, 自治体補助金, e-Gov パブコメ, identity_confidence golden, organic outreach playbook.
- **業法 8-fence** — every sensitive surface (税理士法 §52・弁護士法 §72・公認会計士法 §47の2・行政書士法 §1の2・司法書士法 §3・社会保険労務士法 §27・弁理士法 §75・労働基準法 §36) carries a `_disclaimer` envelope; 36協定 renderer is gated behind `AUTONOMATH_36_KYOTEI_ENABLED` (default off) pending 社労士 supervision review.
- **Deploy hardening** — 4 fixes in `.github/workflows/deploy.yml` (smoke gate sleep 25s→60s + `--max-time` 15s→30s + `flyctl status` pre-probe + size-guarded hydrate skip + explicit `rm -f` before sftp). Fly p99 machine swap exceeds 25s and the previous timing produced false-positive smoke fails.

See [`CHANGELOG.md`](./CHANGELOG.md) for the full 40-commit walk.

## What this isn't

- Not legal advice (弁護士法 § 72)
- Not tax advice (税理士法 § 52)
- Not 行政書士 work (行政書士法 § 1の2)
- Not real-time amendment tracking (snapshot data, partial historical diffs)
- Verify primary sources before any business decision

## Coverage

- **Source-linked records** — most published rows include `source_url`, `content_hash`, and `source_fetched_at`; known source gaps are surfaced. Known second-tier aggregator pages are excluded from citation sources where detected.
- **11,601 searchable programs** across 47 prefectures + national (補助金・融資・税制・認定; tier S=114 / A=1,340 / B=4,186 / C=5,961; full catalog = 14,472, 2,871 publication-review rows)
- **2,286 採択事例 + 108 融資 (担保・個人保証人・第三者保証人 三軸分解) + 1,185 行政処分 + 22,258 enforcement-detail records + 2,065 court decisions + 362 bids**
- **6,493 laws full-text indexed + 9,484 law metadata records** (e-Gov CC-BY; full-text coverage is incremental — name resolver covers all 9,484, body text index covers 6,493) **+ 50 tax rulesets + 13,801 invoice registrants (PDL v1.0 delta)**
- **181 exclusion / prerequisite rules** (125 exclude + 17 prerequisite + 15 absolute + 24 other) — surfaced as structured eligibility predicates, not free-text
- Standard public MCP configuration, protocol 2025-06-18, stdio. See [`docs/mcp-tools.md`](./docs/mcp-tools.md) for the current public tool catalogue and arguments. Optional labor-agreement tools are disabled unless explicitly enabled.
- **REST API** — endpoints under `/v1/programs/*`, `/v1/laws/*`, `/v1/tax_rulesets/*`, `/v1/case-studies/*`, `/v1/loan-programs/*`, `/v1/enforcement-cases/*`, `/v1/exclusions/*`, `/v1/am/*`. OpenAPI: [`docs/openapi/v1.json`](./docs/openapi/v1.json)
- **No LLM inside the service** — no external LLM calls in the data/evidence path. Content endpoints are generated from the corpus and deterministic application code; reasoning lives in the caller's agent.
- **Freshness transparency** — per-source `source_fetched_at` distribution exposed at `GET /v1/stats/freshness`
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
        "JPCITE_API_KEY": "jc_xxx",
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
# Primary (X-API-Key header, used across our docs).
# Use --data-urlencode for non-ASCII query params — passing 補助金 / 設備投資
# raw in the URL breaks the HTTP request line on most curl builds and returns
# a 400 bad_request envelope.
curl -G "https://api.jpcite.com/v1/programs/search" \
  --data-urlencode "q=設備投資" \
  --data-urlencode "prefecture=東京都" \
  -H "X-API-Key: jc_xxx"

# Browser and agent examples should prefer X-API-Key.
```

Get an API key at <https://jpcite.com/pricing.html#api-paid>. Manage existing
keys, usage, and billing at <https://jpcite.com/dashboard>.

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

165 tools at default gates, MCP protocol `2025-06-18`, FastMCP over stdio. 完全なリストと引数は [docs/mcp-tools.md](./docs/mcp-tools.md) を参照 (Single source of truth)。

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

Program records prioritize primary sources such as 経産省, 農林水産省 (MAFF), 日本政策金融公庫 (JFC), 総務省, and 47 都道府県公報. Most public records carry `source_url` + `source_fetched_at` lineage, with known gaps documented. Public structured data is exposed through inline JSON-LD, `sitemap-structured.xml`, and the `.well-known` discovery files; the retired `/structured/` export path is intentionally not public.

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

The standard distribution exposes 165 tools for Japanese public-program
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

## Known limitations

jpcite is a public-record evidence layer, not a legal, tax, audit,
credit, or filing decision service. Corpus coverage, source freshness, and
field-level provenance vary by source family. Responses include
`source_url`, `source_fetched_at`, `known_gaps`, and disclaimers where
applicable so callers can verify primary sources before business decisions.

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

## Wave 50 status (2026-05-16, append-only)

Wave 50 RC1 contract layer 完成 + production deploy preflight gate substrate landed. Architecture-snapshot counts above remain authoritative; this section is **additive** alongside the 2026-05-07 hardening / 2026-05-12 v0.4.0 LIVE markers.

- **mypy strict**: tick 5 → tick 6 で **71 → 0 errors achieved** (Optional / Pydantic v1↔v2 boundary 残務 sweep + Python target version 引き直し).
- **pytest**: **8215/8628 PASS, 0 fail** (tick 6 で coverage gap top 5 を +190 tests で fill、collected 8628 維持).
- **production deploy readiness gate**: tick 4 で **7/7 PASS** 達成、tick 5 で G5 schema sync gap により 6/7 一時 regression、tick 6 e2e で **7/7 再達成**、tick 7 で **7/7 維持**.
- **RC1 contract layer**: **19 Pydantic models + 20 JSON Schema** (agent_runtime/contracts.py + schemas/jpcir/、`scripts/check_schema_contract_parity.py` で双方向 round-trip 0 drift).
- **Release Capsule**: **21 artifacts in manifest + 14 outcome contracts + 3 inline packets** (`estimated_price_jpy` ¥300-¥900 band 実値 fill 完了).
- **AWS canary readiness**: **8/8 prerequisites** (IAM role / budget envelope / SNS topic / teardown attestation / DRY_RUN smoke 30/30 / `aws_budget_canary_attestation` schema bind / `release_capsule_manifest.json` 登録 / `.github/workflows/aws-canary.yml` ready).
- **Stream G staged drift**: tick 5 340 → tick 6 479 → tick 7 540+ (target、3 PR commit + push + CI green 一気通貫).
- **preflight READY**: 4/5 (tick 6) → **5/5** (tick 7 目標、AWS_CANARY_READY flip target).

last_updated: 2026-05-16
for use in environments where shields.io is unreachable.

## Wave 50 RC1 status badges (2026-05-16, append-only)

Additive to the 2026-05-07 hardening / 2026-05-12 v0.4.0 LIVE / above Wave 50 status section markers. Existing badge / metric sections remain authoritative.

[![production gate](https://img.shields.io/badge/production%20gate-7%2F7%20PASSING-4c1.svg)](./docs/_internal/WAVE50_RC1_2026-05-16.md)
[![mypy strict](https://img.shields.io/badge/mypy%20strict-0%20errors-4c1.svg)](./CHANGELOG.md)
[![pytest](https://img.shields.io/badge/pytest-8215%2B%20PASS-4c1.svg)](./tests/)
[![coverage](https://img.shields.io/badge/coverage-76%25-4c1.svg)](./tests/)
[![AWS canary](https://img.shields.io/badge/AWS%20canary-READY%20(operator%20unlock%20pending)-yellow.svg)](./docs/runbook/aws_canary.md)

### Wave 50 RC1 final state (2026-05-16)

- **production deploy readiness gate**: **7/7 PASSING** (tick 6 で regression を経て tick 7-9 で 7/7 維持)
- **mypy strict**: **0 errors** (tick 6 で 71 → 0 achieved、新規 strict error は red gate)
- **pytest**: **8215+ PASS, 0 fail** (collected 8628、tick 8-9 で coverage gap top 5 + high-impact 5 module で +200+ tests landed)
- **coverage**: **76+%** (tick 7 73.52% → tick 8 75%+ → tick 9 76-77%)
- **preflight**: **5/5 READY** (Stream A 5 preflight artifact 全件 READY 達成、tick 9 で Stream A → completed)
- **preflight_scorecard.state**: **AWS_CANARY_READY** (tick 9 Stream Y で AWS_BLOCKED → AWS_CANARY_READY 進行)
- **live_aws_commands_allowed**: **false** (絶対条件堅守、operator token gate `--unlock-live-aws-commands` 経由でのみ flip 可)
- **22+ Stream landed in 10 tick** (Stream A/B/C/D/E/F/G/H/I/K/L/M/N/O/P/Q/R/S/T/U/V/W/X/Y/Z 累計 24/26 completed)
- **RC1 contract layer**: 19 Pydantic models + 20 JSON Schema、`scripts/check_schema_contract_parity.py` で双方向 round-trip 0 drift
- **Release Capsule**: 21 artifacts in manifest + 14 outcome contracts (¥300-¥900 band 実値 fill 完了) + 3 inline packets
- **AWS canary readiness**: 8/8 prerequisites + 追加 4 gate audit OK、Stream W concern separation で `live_aws=true` flip を operator token gate 経由のみに分離

last_updated: 2026-05-16
