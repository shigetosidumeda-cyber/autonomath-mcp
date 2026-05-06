# W20 — Claude Desktop (.mcpb) submission runbook

One-time owner action to submit the `.mcpb` extension bundle for jpcite to the
Claude Desktop directory. After upload, end users can install the extension
in Claude Desktop with one click and call all 126 MCP tools without any
local Python install.

## Artifact

- **File**: `dist/jpcite-0.3.4.mcpb`
- **Package size**: 74.7 kB
- **Unpacked size**: 182.9 kB (icon.png 19.1 kB + manifest.json 162.2 kB + README.md 1.6 kB)
- **shasum (sha256)**: `9a581ab3b829dac8b8704ec7162dfbbfe0af8701e9fbf6a705c8eceec17f80b3`
- **dxt internal name**: `autonomath-mcp@0.3.4` (PyPI distribution name; user-facing brand is **jpcite**)
- **Display name**: `jpcite — 日本の制度 API`

## Manifest contract

Generated from `dxt/manifest.json` at the repo root. The packed bundle is a
sanitized copy that strips the non-standard top-level keys `resources` and
`resources_gated` (the source-of-truth manifest retains them for the REST
side; Anthropic's dxt validator rejects them).

- **dxt_version**: `0.1`
- **version**: `0.3.4` (was `0.3.3`; bumped for the +30 tools landing)
- **tool count**: **126** (was 96 — full diff in §Tool delta)
  - Verified at runtime via:
    ```bash
    .venv/bin/python -c "
    import asyncio, os
    os.environ['AUTONOMATH_ENABLED'] = '1'
    os.environ['AUTONOMATH_ENGLISH_WEDGE_ENABLED'] = '1'
    from jpintel_mcp.mcp.server import mcp
    async def main():
        tools = await mcp.list_tools()
        print(len(tools))
    asyncio.run(main())
    "
    # → 126
    ```
  - Manifest parity confirmed (`names_manifest == names_runtime`).
- **description**: refreshed from `120 tools.` → `126 tools.`
- **Operator**: Bookyou株式会社, info@bookyou.net, 適格事業者 T8010001213708
- **Pricing**: ¥3/req metered (税込 ¥3.30), 3 req/day anonymous (IP-based, JST 翌日 00:00 リセット)

## Tool delta (96 → 126, +30)

All 30 new tools come from the **Wave 24** Ch10.7 landing (split across
`wave24_tools_first_half.py` / `wave24_tools_second_half.py`) plus
foreign-FDI / law-EN / amendment / treaty surfaces from migrations 090–092
that already had MCP wrappers but were never reflected in the .mcpb manifest.

```
check_foreign_capital_eligibility
find_adopted_companies_by_program
find_combinable_programs
find_complementary_subsidies
find_emerging_programs
find_fdi_friendly_subsidies
find_programs_by_jsic
find_similar_case_studies
forecast_enforcement_risk
get_compliance_risk_score
get_evidence_packet_batch
get_houjin_360_snapshot_history
get_houjin_subsidy_history
get_industry_program_density
get_law_article_en
get_program_adoption_stats
get_program_application_documents
get_program_calendar_12mo
get_program_keyword_analysis
get_program_narrative
get_program_renewal_probability
get_tax_amendment_cycle
get_tax_treaty
infer_invoice_buyer_seller
match_programs_by_capital
predict_rd_tax_credit
recommend_programs_for_houjin
score_application_probability
search_laws_en
simulate_tax_change_impact
```

Zero stale tools (no manifest entry pointed at a tool that is not in the
runtime list — clean superset bump).

## Build steps (already executed for v0.3.4)

```bash
# 1. Read source manifest at repo root
cd /Users/shigetoumeda/jpcite

# 2. Bump version + tool array via Python (preserves field order)
#    - sets m['version'] = '0.3.4'
#    - replaces '120 tools.' with '126 tools.' in description
#    - rebuilds m['tools'] from runtime list_tools() output (parity-checked)

# 3. Stage a clean copy without 'resources' / 'resources_gated' so the
#    validator passes — those keys exist in the source-of-truth manifest
#    for REST consumption but the .mcpb spec rejects them.
rm -rf /tmp/jpcite_dxt_build
mkdir -p /tmp/jpcite_dxt_build
cp -R dxt/. /tmp/jpcite_dxt_build/
.venv/bin/python -c "
import json, pathlib
p = pathlib.Path('/tmp/jpcite_dxt_build/manifest.json')
m = json.loads(p.read_text())
m.pop('resources', None); m.pop('resources_gated', None)
p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + chr(10))
"

# 4. Pack
cd /tmp/jpcite_dxt_build
npx --yes @anthropic-ai/dxt pack . /Users/shigetoumeda/jpcite/dist/jpcite-0.3.4.mcpb
# → Manifest is valid! 126 tools, package size 74.7 kB
```

## Submission (manual, one-time)

1. Sign in at <https://claude.ai/settings/extensions> as the Bookyou株式会社
   developer account (info@bookyou.net).
2. Navigate to the developer console → **Submit extension**.
3. Upload `/Users/shigetoumeda/jpcite/dist/jpcite-0.3.4.mcpb`.
4. Submission metadata to paste:
   - **Display name**: `jpcite — 日本の制度 API`
   - **Short description**: 1 line from manifest `description`
     (subsidies, loans, tax, law, invoice & corporate data — 126 tools).
   - **Long description**: paste manifest `long_description` verbatim
     (covers ¥3/req pricing, 3 req/day free, evidence packet contract,
     非弁・非税理士業務 disclaimer).
   - **Homepage**: <https://jpcite.com>
   - **Documentation**: <https://jpcite.com/docs/>
   - **Support**: <https://jpcite.com/docs/faq>
   - **Author**: Bookyou株式会社, info@bookyou.net
   - **License**: MIT
5. Click **Submit for review**. Anthropic review SLA is opaque; allow ~3
   business days.

## Verify after listing goes live

- Install fresh in Claude Desktop on a clean profile.
- Run `tools/list` and assert count == 126.
- Spot-check 3 tools: `search_programs`, `get_evidence_packet`,
  `recommend_programs_for_houjin` (the last one is a Wave 24 newcomer).
- Confirm the `_disclaimer` envelope appears on sensitive tools
  (`bundle_application_kit`, `prepare_kessan_briefing`, etc.).

## Do NOT

- Do **not** add `resources` or `resources_gated` back into the staged
  build copy — they are valid in the source manifest for REST surfaces but
  break .mcpb validation.
- Do **not** rename the dxt internal `name` field away from `autonomath-mcp`.
  The PyPI distribution name is the historical anchor; renaming it breaks
  the install path. The brand `jpcite` lives in `display_name` only.
- Do **not** ship a manifest where `len(tools)` diverges from
  `len(await mcp.list_tools())` — every Claude Desktop install will then
  silently miss tools (no error, just absent).
