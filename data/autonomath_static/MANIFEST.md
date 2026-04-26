# autonomath_static — MANIFEST

Static knowledge artifacts copied verbatim from the AutonoMath knowledge base
(`/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/`) into jpintel-mcp
for downstream MCP exposure. No content transformation; byte-identical to source
(`cmp` clean as of 2026-04-25).

- Copied at: 2026-04-25
- License: Proprietary — Bookyou株式会社 internal compilation (T8010001213708)
- Source repo: `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/`
- Wiring (loaders / MCP tool registration) intentionally deferred to a separate phase.

Row counts: `lines` = file line count (matches the spec); `records` = parsed
data records (top-level array length, or sum of nested arrays for grouped dicts).

| # | File | Bytes | Lines | Records | Description |
|---|------|------:|------:|--------:|-------------|
| 1 | `seido.json`              |  74,727 | 2,685 | 82 programs (594 nested entries) | 制度 taxonomy: subsidy/loan/tax program catalog with combinability rules, eligibility, amounts, deadlines, guardrails, source hints. |
| 2 | `glossary.json`           |  30,997 |   780 | 46 nodes + 14 relations | Domain dictionary graph (nodes + relations) for 制度・税務・補助金 terminology. |
| 3 | `money_types.json`        |   4,299 |   106 | 7 categories (cash/tax/loan/nontax/defer/reduce/equity) | Money-type enum: canonical taxonomy of financial instrument categories. |
| 4 | `obligations.json`        |  13,474 |   469 | 10 program groups (42 obligation entries) | Deadline / post-award obligation registry per program family (monozukuri, shinjigyou-shinshutsu, safety-kyosai, chinage-sokushin, kyoka-zeisei, …). |
| 5 | `dealbreakers.json`       |   6,265 |   165 | 9 universal + 5 program-specific groups (22 dict entries total) | Application rejection-trigger registry: hard universal disqualifiers and program-specific dealbreakers with source evidence. |
| 6 | `agri/crop_library.json`  | 224,161 | 8,684 | 10 categories + 54 crops | Crop taxonomy: categorized crop library with category metadata (`_meta`, `categories`, `crops`). |
| 7 | `agri/exclusion_rules.json` | 23,046 |   309 | 22 rules | Agri-program exclusion / mutual-exclusivity rules with metadata. |
| 8 | `sector_combos.json`      |  45,716 |   860 | 13 combos (150 nested dict entries) | Sector-level program-stacking patterns: pre-validated 制度 combinations with stacking_order, prerequisites, compatibility notes, estimated annual impact. |

Total bytes: **422,685** across 8 files (14,058 lines).

## Source paths (verbatim)

| File | Source |
|------|--------|
| seido.json              | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/seido.json` |
| glossary.json           | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/glossary.json` |
| money_types.json        | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/money_types.json` |
| obligations.json        | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/obligations.json` |
| dealbreakers.json       | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/dealbreakers.json` |
| agri/crop_library.json  | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/agri/crop_library.json` |
| agri/exclusion_rules.json | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/agri/exclusion_rules.json` |
| sector_combos.json      | `/Users/shigetoumeda/Autonomath/backend/knowledge_base/data/sector_combos.json` |

## Refresh protocol

These are static snapshots. To refresh: re-copy from source paths above and
re-run `cmp` to confirm byte-identity, then bump the "Copied at" date.
