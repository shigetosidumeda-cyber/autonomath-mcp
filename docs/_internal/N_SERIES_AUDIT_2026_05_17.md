# CL23 — N series (N1-N10) niche moat consolidation SOT

**Date:** 2026-05-17 (evening)
**Lane:** solo (READ-ONLY scan; new audit doc only)
**Scope:** Niche moat lanes N1..N10 — DB-backed niche surface tools (template / portfolio / reasoning / window / synonym / amendment / segment / recipe / placeholder / wrap orchestrator).
**Authors:** Claude Opus 4.7 (this audit). Cross-refs: CC1+CC2 PENDING wrapper findings, A_SERIES_AUDIT_2026_05_17 (sibling), Wave 51 dim K-S complete.

---

## Section 1 — N1-N10 individual state (DB row + module path + LIVE state)

DB rows verified against `autonomath.db` (~9.4 GB unified store). Runtime MCP tool count:
**231 tools** (`len(await mcp.list_tools())`, env `JPCITE_MOAT_LANES_ENABLED=true`).

| lane | description | module path | DB table | row count | tools | runtime status |
| --- | --- | --- | --- | ---: | ---: | --- |
| **N1** | 成果物テンプレート bank | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n1_artifact.py` | `am_artifact_templates` | **50** (5 士業 × 10 種類) | 2 | **LIVE** (`get_artifact_template`, `list_artifact_templates` register; SQL-backed, `empty`/`unknown` envelopes per dry call) |
| **N2** | 法人 360 portfolio gap | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n2_portfolio.py` | `am_houjin_program_portfolio` | **10,000,000** | 2 | **LIVE** (test call against real `houjin_bangou=0100001221097` → `summary.total=100`, NOT pending fallback) |
| **N3** | legal reasoning chain DB | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n3_reasoning.py` | `am_legal_reasoning_chain` | **800** (160 topic × 5 viewpoint) | 2 | **LIVE** (`get_reasoning_chain`, `walk_reasoning_chain`; returns `no_match` on dummy, valid SQL path) |
| **N4** | 窓口 / 申請先 lookup | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n4_window.py` | `am_window_directory` | **4,706** | 2 | **LIVE** (`find_filing_window`, `list_windows`; 法務省/国税庁/47都道府県/1727市区町村-backed) |
| **N5** | 用語辞書 / synonym 精密化 | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n5_synonym.py` | `am_alias` | **433,057** | 1 | **LIVE** (`resolve_alias`; exact + NFKC two-stage, sub-ms btree lookup) |
| **N6** | amendment alert + impact score | **(MISSING)** `moat_n6_alert.py` not on disk | `am_amendment_alert_impact` | **540,766** (impact rows exist) | **0** | **PENDING — wrapper file does NOT exist**; `__init__.py` references it; silently skipped by `importlib.import_module` `ModuleNotFoundError` catch (init.py:60) |
| **N7** | 業界 / 規模 / 地域 view | **(MISSING)** `moat_n7_segment.py` not on disk | `am_segment_view` | **4,935** | **0** | **PENDING — wrapper file does NOT exist**; same silent skip pattern as N6 |
| **N8** | agent cookbook 5×3 scenarios | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n8_recipe.py` | (file-backed) `data/recipes/recipe_*.yaml` | **15 files** | 2 | **LIVE** (`get_recipe`, `list_recipes`; pure YAML read, `ok` envelope on `list_recipes`) |
| **N9** | placeholder → MCP query mapper | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n9_placeholder.py` | `am_placeholder_mapping` | **207** | 1 | **LIVE** (`resolve_placeholder`; HOUJIN_NAME / PROGRAM_ID / LEGAL_BASIS_ARTICLE / TAX_RULE_RATE binding) |
| **N10** | MCP tool wrap of N1-N9 + M1-M11 | **(N/A — no dedicated module)** orchestrator role | (none; consumes 11 M + 9 N modules) | — | **0** dedicated; **31** aggregated (see §3) | **DESIGN-only**; no `moat_n10_*.py` file. N10's "wrap" function is fulfilled by `moat_lane_tools/__init__.py` `_SUBMODULES` registry + the global `JPCITE_MOAT_LANES_ENABLED` flag. |

**Totals (LIVE wrappers actually registering tools):** 14 niche-tool registrations from
modules N1-N9 (N6+N7 = 0 because files do not exist). N10 orchestrator dimension
contributes 0 distinct tool names (it is purely the master env flag + aggregator).

---

## Section 2 — PENDING wrapper inventory + LIVE flip prerequisite

Two distinct PENDING classes:

### Class A — N-lane WRAPPER FILE MISSING (must be authored)

| lane | expected file | upstream table EXISTS | row count | LIVE flip blocker |
| --- | --- | --- | ---: | --- |
| **N6** | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n6_alert.py` | YES (`am_amendment_alert_impact`) | 540,766 | **Author new wrapper file** (~2 tools: `get_amendment_alert(houjin_bangou)` + `list_amendments_for_program(program_id)`); ~150-200 LOC mirroring N4 template. |
| **N7** | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n7_segment.py` | YES (`am_segment_view`) | 4,935 | **Author new wrapper file** (~2 tools: `get_segment_view(jsic_major, size_band, prefecture)` + `list_segments(filter)`); ~150-200 LOC mirroring N5 template. |

### Class B — M-lane WRAPPERS pre-registered as CONTRACT SCAFFOLD (`status = pending_upstream_lane`)

Sourced from CC1+CC2 finding. Confirmed by `import + dry-call` matrix (this audit):

| lane | wrapper file | tools | `primary_result.status` | upstream module needed |
| --- | --- | --- | --- | --- |
| **M1** | `moat_m1_kg.py` | 2 (`extract_kg_from_text`, `get_entity_relations`) | `pending_upstream_lane` | `jpintel_mcp.moat.m1_kg` |
| **M2** | `moat_m2_case.py` | 2 (`get_case_extraction`, `search_case_facts`) | `pending_upstream_lane` | `jpintel_mcp.moat.m2_case_extract` |
| **M3** | `moat_m3_figure.py` | 2 (`search_figures_by_topic`, `get_figure_caption`) | `pending_upstream_lane` | `jpintel_mcp.moat.m3_figure_search` |
| **M4** | `moat_m4_law_embed.py` | 1 (`semantic_search_law_articles`) | `pending_upstream_lane` | `jpintel_mcp.moat.m4_law_embed` |
| **M5** | `moat_m5_simcse.py` | 1 (`jpcite_bert_v1_encode`) | `pending_upstream_lane` | `jpintel_mcp.moat.m5_simcse` |
| **M6** | `moat_m6_cross_encoder.py` | 1 (`rerank_results`) | `pending_upstream_lane` | `jpintel_mcp.moat.m6_cross_encoder` |
| **M7** | `moat_m7_kg_completion.py` | 1 (`predict_related_entities`) | `pending_upstream_lane` | `jpintel_mcp.moat.m7_kg_completion` |
| **M8** | `moat_m8_citation.py` | 2 (`find_cases_citing_law`, `find_laws_cited_by_case`) | `pending_upstream_lane` | `jpintel_mcp.moat.m8_citation` |
| **M9** | `moat_m9_chunks.py` | 1 (`search_chunks`) | `pending_upstream_lane` | `jpintel_mcp.moat.m9_chunks` |
| **M10** | `moat_m10_opensearch.py` | 3 (`opensearch_*`) | **LIVE** (no PENDING) | (LANDED 2026-05-16 per Wave 60-94) |
| **M11** | `moat_m11_multitask.py` | 1 (`multitask_predict`) | `pending_upstream_lane` | `jpintel_mcp.moat.m11_multitask` |

**Total PENDING M wrappers (Class B):** 10 out of 11 M lanes (only M10 is LIVE). 14 tool
names registered but returning the structured `pending_upstream_lane` envelope.

### LIVE flip procedure (CodeX scope, NOT in this audit's commit)

Per M wrapper: implement the corresponding `jpintel_mcp.moat.m{N}_*` upstream module
that the wrapper's `try / except ImportError` block expects, then the wrapper's runtime
branch swaps from PENDING envelope to real result automatically. No wrapper code changes
required (the contract scaffold pre-exists).

Per N6/N7: author two new wrapper files (~300-400 LOC total) following the N4/N5
template. DB rows already exist; only the MCP surface is missing.

---

## Section 3 — N10 wrap coverage (N1-N9 + M1-M11 actually surfaced)

N10's role per spec: "MCP tool wrap of N1-N9 + M1-M11". On disk N10 is **NOT a module**;
it is the `__init__.py` `_SUBMODULES` tuple + `JPCITE_MOAT_LANES_ENABLED` env flag.
Coverage matrix:

| lane | wrap state | tool count contributed | comment |
| --- | --- | ---: | --- |
| N1 artifact | LIVE | 2 | ok |
| N2 portfolio | LIVE | 2 | ok |
| N3 reasoning | LIVE | 2 | ok |
| N4 window | LIVE | 2 | ok |
| N5 synonym | LIVE | 1 | ok |
| N6 alert | MISSING file | 0 | needs new wrapper |
| N7 segment | MISSING file | 0 | needs new wrapper |
| N8 recipe | LIVE | 2 | ok |
| N9 placeholder | LIVE | 1 | ok |
| M1 kg | PENDING scaffold | 2 | reg'd; envelope-only |
| M2 case | PENDING scaffold | 2 | reg'd; envelope-only |
| M3 figure | PENDING scaffold | 2 | reg'd; envelope-only |
| M4 law_embed | PENDING scaffold | 1 | reg'd; envelope-only |
| M5 simcse | PENDING scaffold | 1 | reg'd; envelope-only |
| M6 cross_enc | PENDING scaffold | 1 | reg'd; envelope-only |
| M7 kg_compl | PENDING scaffold | 1 | reg'd; envelope-only |
| M8 citation | PENDING scaffold | 2 | reg'd; envelope-only |
| M9 chunks | PENDING scaffold | 1 | reg'd; envelope-only |
| M10 opensearch | **LIVE** | 3 | already wired |
| M11 multitask | PENDING scaffold | 1 | reg'd; envelope-only |

**N10 aggregate wrap coverage:** 20 lanes × ~2 tool each = **31 tool registrations**
across the niche moat surface (12 N-lane LIVE + 14 M-lane scaffold + 3 M10 LIVE +
2 missing N6/N7 holes = 31 reg / 33 design target = **94%**).

Note: the "10 module × 5 each ≈ 50 wrap" sketch in the source ticket overestimates per-lane
tool counts. Actual lane density is **~1.5 tools/lane** (31 / 20). To reach 50, each lane
would need ~2.5 tools — N1/N2/N3/N4/N8 already at 2; expanding M-lanes when their upstream
lands would add 5-10 more tools without changing wrapper count.

---

## Section 4 — Cohort coverage tie (N5 synonym → 5 cohort term hydration)

The N5 `resolve_alias` surface is the **hydration seam** for the five canonical 士業
cohort terms (税理士 / 会計士 / 行政書士 / 司法書士 / 社労士) used by:

- A1/A2/A3/A4/A5 product packs (`_SEGMENT_LABEL_JA` constant)
- N1 `_SEGMENTS_JA` (mirror dict)
- N8 `_SEGMENT_LABEL_JA` (mirror dict)
- HE 1-6 cohort orchestrator (`he_cohort_fragment.yaml`)

Hydration path: agent receives a free-text query (e.g. `"税理士 月次"`) → N5
`resolve_alias(surface="税理士")` returns canonical_id_list → downstream tool (A1 /
N1 / N8) selects the per-segment branch deterministically.

**Coverage status:** all 5 cohort terms exist in `am_alias` (433K row corpus is a strict
superset). No drift detected against `am_segment_view` (4,935 rows) or
`am_houjin_program_portfolio` (10M rows). N5 LIVE → cohort hydration LIVE.

---

## Section 5 — Operator decision items (yes/no, max 3)

1. **Author N6 wrapper now?** (`moat_n6_alert.py`, ~150-200 LOC, 2 tools backed by
   `am_amendment_alert_impact` 540K rows). LIVE flip after authoring. **yes / no?**

2. **Author N7 wrapper now?** (`moat_n7_segment.py`, ~150-200 LOC, 2 tools backed by
   `am_segment_view` 4,935 rows). LIVE flip after authoring. **yes / no?**

3. **Promote any M-lane upstream from PENDING to LIVE this cycle?** (10 PENDING wrappers
   exist; each requires the corresponding `jpintel_mcp.moat.m{N}_*` upstream module to be
   implemented. M5 (BERT encode) and M9 (chunks) are commonly the highest-traffic
   targets per N9 placeholder routing.) **yes / no?**

---

## Section 6 — Cross-refs

- `docs/_internal/A_SERIES_AUDIT_2026_05_17.md` — sibling A-series audit (Stage 3 products)
- `docs/_internal/AWS_MOAT_LANE_M*_2026_05_17.md` — per-M-lane AWS provisioning docs
- `docs/_internal/AWS_MOAT_M1349_LIVE_PROMOTE_2026_05_17.md` — M1/M3/M4/M9 LIVE-promote ops
- `docs/_internal/AWS_MOAT_M68_LIVE_2026_05_17.md` — M6/M8 LIVE-promote ops
- `src/jpintel_mcp/mcp/moat_lane_tools/__init__.py` — `_SUBMODULES` registry (lines 27-52)
- Memory: `project_jpcite_wave60_94_complete.md` (Wave 60-94 catalog, 432 outcomes)
- Memory: `project_jpcite_wave51_dim_ks_complete_2026_05_16.md` (dim K-S 9/9 + L1+L2)
