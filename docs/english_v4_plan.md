# English V4 Launch Plan (P6-E, dd_v8_03)

Target slot: **T+150d** post AutonoMath launch (2026-05-06 + 150 = 2026-10-03).
Implementation budget: **10 working days** spread across the slot.
Owner: B6 subagent (this file is the spec, not the rollout log).

> Why a separate plan: English V4 is a Y2 ARR uplift bet (¥100-150k/mo).
> Cohort = foreign-born startup founders, visa sponsors, cross-border M&A
> teams that already pay for English Stripe / GitHub / Notion docs but
> have no Japanese counterpart for 補助金 / 融資 / 税制 lookup.
>
> The launch is **scaffolded today** (2026-04-25) so that activation is a
> single ~10-day push when the slot opens, not a multi-week dig-out from
> scratch. Today's deliverables: i18n module + style guide + this plan.

## Scope decision (locked)

- **In**: read-side localization for all 16 autonomath tools + 7 jpintel
  one-shot tools, 50+ key i18n catalog (expand to ~200), `response_language`
  parameter, llms-full.en.txt, docs/index.en.md, site/index.en.html,
  cohort outreach prep.
- **Out**: machine translation (every English string is hand-curated),
  English-only program data (we do not re-translate program content),
  English support tickets / sales motion (zero-touch ops principle).
- **Constraint**: ja default preserved. Every existing caller that does
  not pass `response_language` keeps Japanese output — no breaking change.

## Day-by-day timeline

### D1 — `am_alias.language` migration (collection-CLI)

Migration: `scripts/migrations/040_am_alias_language.sql`.

```sql
-- 040_am_alias_language.sql
-- P6-E: tag aliases by language so English fallback can resolve to
-- the official English transliteration of authorities, laws, programs.
ALTER TABLE am_alias ADD COLUMN language TEXT
    NOT NULL DEFAULT 'ja'
    CHECK (language IN ('ja','en','kana','romaji'));

CREATE INDEX ix_am_alias_language ON am_alias(canonical_id, language);

-- Backfill: alias_kind='english' rows → language='en'.
UPDATE am_alias SET language = 'en' WHERE alias_kind = 'english';
-- Backfill: alias_kind='kana' rows → language='kana'.
UPDATE am_alias SET language = 'kana' WHERE alias_kind = 'kana';
-- Backfill: rows whose alias matches a Latin-only regex → 'romaji'
-- (handled by the post-migration python script `scripts/i18n/backfill_romaji.py`
-- to keep regex out of SQLite for portability).
```

- Owner: collection CLI worker (NOT this subagent — out of scope per
  the task constraints in `feedback_data_collection_tos_ignore`).
- Verification: `SELECT language, COUNT(*) FROM am_alias GROUP BY 1`
  should show ja >> en > kana > romaji after backfill.
- Backout: `ALTER TABLE am_alias DROP COLUMN language;`
  (sqlite 3.35+; we are on 3.43, safe.)

### D2-D3 — i18n message catalog expansion (~200 keys)

Source of truth: `src/jpintel_mcp/i18n/__init__.py` (scaffolding ~50
keys landed today). D2 expands by category:

| Category | Key prefix | Count target | Source of strings |
|---|---|---|---|
| Envelope (16 tools × 4 statuses) | `envelope.<status>.<tool>` | 64 | `envelope_wrapper.DEFAULT_EXPLANATIONS` |
| Error user_message | `error.<code>` | 25 | `cs_features.USER_MESSAGES` |
| Onboarding tips | `tips.<n>` | 30 | `cs_features.onboarding_tips_for_age_days` |
| Suggestion templates | `suggest.<intent>` | 40 | `cs_features.derive_suggestions` |
| Input warnings | `warn.<rule>` | 20 | `cs_features.derive_input_warnings` |
| Meta block field labels | `meta.<field>` | 15 | (REST + MCP envelope) |
| Discovery one-shots | `oneshot.<tool>` | 14 | server.py 7 one-shots × ja+en hint |
| **Total** | | **~208** | |

D3 adds the `t()` callsite swaps: every `f"..."` literal in
`envelope_wrapper.py` and `cs_features.py` becomes `t(key, lang)`.

### D4-D5 — `response_language` parameter wiring (23 tools)

Tools that gain the parameter:

- 16 autonomath tools in `src/jpintel_mcp/mcp/autonomath_tools/`
  (the package's `__all__` list — search_tax_incentives, search_certifications,
  list_open_programs, enum_values_am, search_by_law, active_programs_at,
  related_programs, search_acceptance_stats_am, intent_of, reason_answer,
  get_am_tax_rule, search_gx_programs_am, search_loans_am,
  check_enforcement_am, search_mutual_plans_am, get_law_article_am).
- 7 one-shot discovery tools in `server.py` (smb_starter_pack,
  subsidy_combo_finder, deadline_calendar, dd_profile_am, similar_cases,
  regulatory_prep_pack, subsidy_roadmap_3yr).

Signature delta (backward compatible, ja default):

```python
def search_tax_incentives(
    ...,
    response_language: Literal["ja", "en"] | None = "ja",
) -> dict:
    ...
    explanation = t(f"envelope.{status}.search_tax_incentives",
                    response_language or "ja")
```

Where to inject: `envelope_wrapper.build_envelope` already centralises
explanation/suggestions/meta — add a single `lang` kwarg there and let
each tool pass it through.

### D6 — `llms-full.en.txt`

`scripts/regen_llms_full_en.py` (new) mirrors `regen_llms_full.py` but:
- writes to `site/llms-full.en.txt`
- pulls English aliases for program names from `am_alias WHERE language='en'`
- prepends an English overview header
- preserves the same compact-program inventory structure so AI agents
  can switch between the two with one URL change

### D7 — `docs/index.en.md` + mkdocs nav

`docs/index.en.md` (new) — English landing page mirroring `docs/index.md`.
Mkdocs material supports `i18n` plugin; we ship a hand-translated
single page first, then evaluate whether the full `mkdocs-static-i18n`
plugin is worth the build-time cost.

`mkdocs.yml` nav addition (locked in this PR):

```yaml
nav:
  - English:
      - Overview: index.en.md
      - Getting Started: getting-started.en.md
      - API Reference: api-reference.en.md
      - Pricing: pricing.en.md
```

### D8 — `site/index.en.html`

Already mature (`site/en/{about,getting-started,index,pricing,tokushoho}.html`
landed pre-launch). D8 task is a refresh pass to align with the post-launch
copy in `site/index.html` + add a top-of-page banner pointing at the new
English MCP docs.

### D9 — Cohort outreach prep (5 personas, English)

5 persona briefs translated to English (under `docs/_internal/personas.en/`
— `_internal/` excluded from public mkdocs build per `mkdocs.yml`):

1. **Foreign-born startup founder** (visa-aligned 経営管理 holder) —
   needs 創業補助金 in English to file with their Japanese lawyer.
2. **Visa sponsor** (HR ops at multinational) — needs subsidy / certification
   info in English to brief the founder team.
3. **Cross-border M&A team** (overseas PE) — needs 行政処分 +
   採択 stats in English for due diligence.
4. **Foreign accountant / tax advisor** in Japan — needs 税制特例
   sunset dates in English to advise English-speaking clients.
5. **Foreign-language LLM agent** (Claude / GPT in non-Japanese context) —
   needs llms-full.en.txt to ground its answers without hallucination.

D9 also drafts a single English launch tweet + LinkedIn post; no paid
ads, no cold outreach (organic-only principle).

### D10 — Launch + monitoring

- Flip `mkdocs.yml` nav to expose English entries.
- Publish llms-full.en.txt.
- Tweet + LinkedIn post.
- Watch for 7 days: error rate per `response_language` segment, English
  cohort signup count vs Japanese baseline, English MCP call share.
- If English share < 2% by D17, freeze further investment. If > 5%,
  fund Phase 2 (machine translation pilot for the program-content layer).

## Backward compatibility checklist

- [x] `response_language` defaults to `"ja"` everywhere.
- [x] `t(key)` defaults to `lang="ja"`.
- [x] Existing tests (`tests/test_envelope_cs_features.py`, etc.) keep
      passing without modification.
- [x] OpenAPI schema diff: only additive (new optional parameter).
- [x] No DB write paths touched on jpintel.db side.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| English strings drift from JP semantics | Style guide + tests asserting key parity |
| Catalog explodes to thousands of keys | Cap at ~200 in P6-E; never auto-translate program content |
| mkdocs-static-i18n adds build minutes | Stay on hand-curated single page until D9 outreach lands real demand |
| English cohort never materialises | D17 hard freeze; sunk cost is 10 days, recoverable |
| MT quality complaints | Never ship MT — every English string is hand-curated |

## Do not do

- Do **not** machine-translate the program rows (`programs.title_jp`,
  `summary_jp`). The corpus is legally sensitive (景表法 / 消費者契約法)
  and a bad translation creates 詐欺 risk.
- Do **not** create English-only support / sales channels.
  Zero-touch principle holds.
- Do **not** add an English tier badge or English-only price tier.
  The pricing model stays ¥3/req metered, language-agnostic.
- Do **not** rename internal `jpintel_mcp` paths to add `_en` suffixes.
  PyPI package and import path stay legacy.

## References

- Memory: `feedback_autonomath_no_ui` — value lives in API/MCP/static docs.
- Memory: `feedback_zero_touch_solo` — no English sales / CS team.
- Memory: `project_autonomath_business_model` — ¥3/req metered, no tiers.
- Source: `src/jpintel_mcp/i18n/__init__.py` — catalog scaffolding.
- Source: `docs/i18n_style_guide.md` — English tone + bilingual conventions.
- Source: `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py`
  — JP message authority (D2-D3 mirrors this).
