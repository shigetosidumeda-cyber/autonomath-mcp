# Moat N8 + N9 — Recipe bank + Placeholder mapper (2026-05-17)

Companion to lane N1 (`am_artifact_templates`, 50 scaffold bank). N8 is
the deterministic call-sequence recipe bank; N9 is the canonical
placeholder -> MCP tool resolver. Together they let an agent stitch a
realistic 士業 deliverable end-to-end from jpcite alone, with no
free-form LLM prose involved.

## Coverage

### N8 — 15 recipes (5 segments x 3 scenarios)

- **税理士 (tax)**
  - `recipe_tax_monthly_closing` (13 steps, ¥39, 60s)
  - `recipe_tax_year_end_adjustment` (14 steps, ¥42, 90s)
  - `recipe_tax_corporate_filing` (18 steps, ¥54, 120s)
- **会計士 (audit)**
  - `recipe_audit_workpaper_compile` (14 steps, ¥42, 90s)
  - `recipe_audit_internal_control` (12 steps, ¥36, 90s)
  - `recipe_audit_consolidation` (18 steps, ¥54, 120s)
- **行政書士 (gyousei)**
  - `recipe_subsidy_application_draft` (13 steps, ¥39, 75s)
  - `recipe_license_renewal` (11 steps, ¥33, 60s)
  - `recipe_contract_compliance_check` (11 steps, ¥33, 60s)
- **司法書士 (shihoshoshi)**
  - `recipe_corporate_setup_registration` (13 steps, ¥39, 90s)
  - `recipe_director_change_registration` (9 steps, ¥27, 45s)
  - `recipe_real_estate_transfer` (11 steps, ¥33, 60s)
- **AX エンジニア / FDE (ax_fde)**
  - `recipe_client_onboarding` (11 steps, ¥27, 60s)
  - `recipe_domain_expertise_transfer` (10 steps, ¥30, 75s)
  - `recipe_compliance_dashboard` (12 steps, ¥60, 90s)

### N9 — 207 placeholders across 48 mapping groups

Highlights:
- Houjin identity (17): HOUJIN_BANGOU / HOUJIN_NAME / REGISTERED_ADDRESS /
  REPRESENTATIVE_NAME / CAPITAL_YEN / EMPLOYEE_COUNT / INDUSTRY_JSIC_MAJOR / ...
- Invoice (4): INVOICE_REGISTRANT_T / INVOICE_STATUS / ...
- Program (17): PROGRAM_NAME / PROGRAM_KIND / PROGRAM_DEADLINE /
  PROGRAM_LIFECYCLE_STATUS / PROGRAM_ELIGIBILITY_CHAIN / ...
- Law / article (7): LAW_NAME / LEGAL_BASIS_ARTICLE / ARTICLE_EFFECTIVE_DATE / ...
- Tax rule (9): TAX_RULE_NAME / TAX_RULE_RATE / TAX_RULE_SUNSET_DATE /
  TAX_RULE_TSUTATSU_CITE / TAX_RULE_APPLICABLE / ...
- Enforcement (5), Court decision (5), Audit (6), Client / fiscal (10),
  Amendment lineage (3), Sunset (3), Adoption / similar cases (4),
  Exclusion / compatibility (3), Jurisdiction (3), Loan (4),
  Deadline (3), Treaty / foreign capital (6), DD questions (3),
  Corpus / health (3), Provenance (4), Kit / scaffold (3),
  Kessan briefing (2), Route (4), Houjin 360 panel (2), Search (3),
  SIB scaffold (2), License (4), Contract (3), Corporate setup (5),
  Director change (4), Real estate (4), Watch list (2),
  API key / wallet (5), Recipe metadata (4), Static / examples (2),
  Federated (1), Kokkai / Shingikai / Pubcomment (4), Municipality (1),
  NTA corpus (2), URLs (3), Operator identity (3), Disclaimer (6),
  Cohort / region (5), Bids / policy upstream (5), Succession (1),
  Evidence packet (2), Tax chain (1), Fact signature (2),
  Shihoshoshi DD (1), Invoice risk (2)

## Files

### Data
- `data/recipes/recipe_*.yaml` — 15 machine-readable recipe SOT
- `data/placeholder_mappings.json` — 207 mapping SOT

### Code
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n8_recipe.py` —
  `list_recipes(segment)` + `get_recipe(recipe_name)` (file-backed, no DB)
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n9_placeholder.py` —
  `resolve_placeholder(placeholder_name, context_dict_json)` (DB-backed,
  reads `am_placeholder_mapping`)

### Migrations (already landed)
- `scripts/migrations/wave24_206_am_placeholder_mapping.sql` (+ rollback)

### Generators
- `scripts/build_recipes_n8_2026_05_17.py` — regenerate 15 YAMLs
- `scripts/build_placeholder_mappings_n9_2026_05_17.py` — regenerate JSON
- `scripts/build_recipe_docs_n8_2026_05_17.py` — render 15 markdown docs

### Cron loaders
- `scripts/cron/load_placeholder_mappings_2026_05_17.py` — bulk-load
  JSON into `am_placeholder_mapping` (idempotent)

### Docs
- `docs/_internal/recipes_n8/recipe_*.md` — 15 human-readable recipe docs

### Tests
- `tests/test_moat_n8_n9.py` — 18 tests (10 N8 + 8 N9 + 3 catalog SOT)

## Hard constraints

- **NO LLM inference** in any of the new MCP tools. The whole point is
  deterministic, fact-anchored resolution.
- **§-aware disclaimer envelope** on every response (canonical
  `_shared.DISCLAIMER` referencing 税理士法 §52 / 公認会計士法 §47条の2 /
  弁護士法 §72 / 行政書士法 §1 / 司法書士法 §3).
- **Scaffold-only**: every recipe carries `no_llm_required = true` and a
  `disclaimer` field naming the controlling 業法; every sensitive
  placeholder carries `is_sensitive = 1`.
- **mypy --strict 0 errors** on both new modules.
- **ruff 0 errors** on the entire delivered surface.
- **18 / 18 tests PASS**.

## Recovery procedure

If `data/recipes/` and `data/placeholder_mappings.json` get wiped by a
git-clean / PC restart (they are untracked artifacts), regenerate with:

```bash
.venv/bin/python scripts/build_recipes_n8_2026_05_17.py
.venv/bin/python scripts/build_placeholder_mappings_n9_2026_05_17.py
.venv/bin/python scripts/build_recipe_docs_n8_2026_05_17.py
```

To re-seed the autonomath DB table (after running the wave24_206
migration):

```bash
.venv/bin/python scripts/cron/load_placeholder_mappings_2026_05_17.py
```
