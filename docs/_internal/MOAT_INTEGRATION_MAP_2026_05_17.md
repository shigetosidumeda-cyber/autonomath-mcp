# Moat Integration Map — 21 Lane × 5 Dimensions (2026-05-17)

> Audit-only design map. READ-ONLY survey of every moat lane (M1-M11 + N1-N10)
> as it lands on disk today. Snapshot pinned at HEAD of `main` after commit
> `4ceb3a898` (N6+N7 LIVE). Authoritative for `Wave 50 RC1 → Wave 51 dim K-S`
> moat construction wave. No code change made by this doc.
>
> Source dirs walked: `src/jpintel_mcp/mcp/moat_lane_tools/` /
> `src/jpintel_mcp/mcp/autonomath_tools/` / `scripts/migrations/wave24_19*..20*` /
> `data/recipes/` / `data/artifact_templates/` / `docs/_internal/AWS_MOAT_*` /
> `docs/_internal/MOAT_*`.

## Executive summary

- **Lane count surveyed**: 21 / 21 (M1-M11 + N1-N10).
- **LIVE lanes**: 10 (M10 + N1-N9). PENDING lanes: 11 (M1-M9 + M11).
- **MCP tool count delta**: +32 over the 184-baseline → **216 tools** at default gates per `MOAT_N10_MCP_WRAPPERS_2026_05_17.md`.
- **Migrations landed**: 7 new SQL files at wave24_200..205 + the legacy wave24_198 (M7) + wave24_195 (M2).
- **Migration ID collisions**: **0**. Each lane owns a distinct wave24 number.
- **MCP tool name collisions inside N10 roster**: **0** between the 21 canonical lane wrappers.
- **MCP tool name collisions vs existing 184 cohort**: **0 active**, **5-7 latent** (see Collision §).
- **Duplicate file shadows in `src/`**: **5 files** (`moat_n4_window` ↔ `window_tools`, `moat_n5_synonym` ↔ `resolve_alias_tool`, `moat_n8_recipe` x2, `moat_n9_placeholder` x2). Not active (autonomath_tools __init__.py does not import them) but ready to fire if accidentally wired.
- **Open issues**: 8 (see Open Issues §). 1 is critical (missing migration `wave24_206_am_placeholder_mapping.sql`); the rest are dormant duplicates + brittle PENDING contracts.

## Survey method

1. `git log --oneline | grep "Lane [MN][0-9]\+\|Moat Lane"` → 12 commits landed under explicit lane labels.
2. `ls src/jpintel_mcp/mcp/moat_lane_tools/` → 23 files (1 __init__ + 1 _shared + 21 lane modules).
3. `find scripts/migrations -name "wave24_19*..20*"` → 9 SQL pairs (some rollback-only).
4. `grep -l "Lane M\|Lane N" docs/_internal/MOAT*.md docs/_internal/AWS_MOAT*.md` → 12 design docs.
5. Cross-checked every PENDING wrapper's `upstream_module` against `src/jpintel_mcp/moat/m*_*.py` (none exist yet — confirmed PENDING posture).

## Lane × Dimension matrix

Rows = lane. Columns = (migration ID | new MCP tool(s) | module path | data file | upstream dependency).

### M-series (model-driven lanes — 11 lanes, 14 MCP tools, M10 only LIVE)

| Lane | Status | Migration / table | New MCP tool(s) | Module path | Data / artifact | Upstream dep |
| ---- | ------ | ----------------- | --------------- | ----------- | --------------- | ------------ |
| M1 | PENDING | (no DB table — outputs to `am_entity_facts` + `am_relation` directly) | `extract_kg_from_text` / `get_entity_relations` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m1_kg.py` | S3 `kg_textract_mirror_2026_05_17/` (10 chunk prefixes) | upstream worker: `scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py` (regex NER, ml.c5.4xlarge×10, no GPU) |
| M2 | PENDING wrapper / LIVE table | `wave24_195_am_case_extracted_facts.sql` → 201,845 facts | `search_case_facts` / `get_case_extraction` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m2_case.py` | `am_case_extracted_facts` (50% JSIC / 32% FY / 40% program_id) | local ETL `scripts/aws_credit_ops/sagemaker_case_extract_2026_05_17.py` (4.36s vs 4h GPU per 167x memory) |
| M3 | PENDING | (no DB table — vector blobs go to S3 + later FAISS v6) | `search_figures_by_topic` / `get_figure_caption` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m3_figure.py` | `figures_raw/` S3 prefixes (CLIP-Japanese ViT-B/16) | `scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py` (ml.c5.4xlarge, $3.81 projected) |
| M4 | PENDING wrapper / FAISS LIVE | (am_law_article 353,278 rows pre-exists, mig 049) | `semantic_search_law_articles` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m4_law_embed.py` | `faiss_indexes/v4/` (post-M9 build) | `scripts/aws_credit_ops/sagemaker_embed_batch.py` + `build_faiss_v4_amlaw_expand.py` |
| M5 | PENDING wrapper / SimCSE InProgress (Day 1) | (model artifact in S3, no SQLite) | `jpcite_bert_v1_encode` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m5_simcse.py` | `s3://jpcite-credit-993693061769-202605-derived/simcse/jpcite-bert-simcse-finetune-20260517T022501Z/` | `scripts/aws_credit_ops/sagemaker_simcse_finetune_2026_05_17.py` (ml.g4dn.12xlarge×1, $282 ceiling) |
| M6 | PENDING wrapper / cross-encoder train scheduled (auto-submit watcher) | (model artifact, no SQLite) | `rerank_results` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m6_cross_encoder.py` | `cross_encoder_train/{train,val}.jsonl` + M6 model output | `scripts/aws_credit_ops/sagemaker_cross_encoder_finetune_2026_05_17.py` + `sagemaker_m6_auto_submit_after_m5.py` (gated on M5 done) |
| M7 | PENDING wrapper / DRY_RUN-verified LIVE submitted gate-pending | `wave24_198_am_relation_predicted.sql` (Lane M7 marked in header) | `predict_related_entities` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m7_kg_completion.py` | `kg_corpus/{train,val,test}.jsonl` (369K edges, 80/10/10 split) | `scripts/aws_credit_ops/kg_completion_export_2026_05_17.py` + `sagemaker_kg_completion_submit_2026_05_17.py` (4-model ensemble TransE/RotatE/ComplEx/ConvE, ml.g4dn.12xlarge×4 sequential, $375 ceiling) |
| M8 | PENDING wrapper / Batch Transform scaffold ready, awaiting M6 artifact | (no DB table — citation graph already in `am_relation`) | `find_cases_citing_law` / `find_laws_cited_by_case` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m8_citation.py` | `s3://.../citation_rerank_v0.2/` (84,800-pair scaffold) | `scripts/aws_credit_ops/sagemaker_citation_rerank_2026_05_17.py` (4 subcmds: export-candidates / register-model / submit-transform / ingest) |
| M9 | PENDING wrapper / FAISS v5 building | (no DB — chunk store on S3) | `search_chunks` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m9_chunks.py` | `corpus_export/{programs,adoption_records,nta_tsutatsu_index,court_decisions,nta_saiketsu,am_law_article}/` + `faiss_indexes/v5/` | `scripts/aws_credit_ops/corpus_chunker_2026_05_17.py` + `submit_full_corpus_embed.py` + `build_faiss_v5_chunk_expand.py` |
| **M10** | **LIVE** | (no migration — OpenSearch domain exterior) | `opensearch_hybrid_search` | `src/jpintel_mcp/mcp/autonomath_tools/opensearch_hybrid_tools.py` (the canonical reg) + `moat_lane_tools/moat_m10_opensearch.py` (no-op stub keeps roster contiguous) | OpenSearch domain `jpcite-xfact-2026-05` (r5.4xlarge×3 + r5.large×3 + ultrawarm1.medium×3 multi-AZ, ~$144/day burn) | `scripts/aws_credit_ops/opensearch_bulk_index_2026_05_17.py` (595,545 docs across 8 corpora) |
| M11 | PENDING wrapper / multi-task fine-tune Day-1 InProgress + 8-stage chain dispatcher | (model artifact + 5x-augmented multi-task corpus) | `multitask_predict` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m11_multitask.py` | `s3://.../jpcite-multitask-large-20260517T025017Z/` + `jpcite-distill-base/` (post-distill) | `scripts/aws_credit_ops/multitask_corpus_prep_2026_05_17.py` + `sagemaker_m11_chain_dispatch_2026_05_17.py` (ml.g5.4xlarge×1 sequential, $390 ceiling) |

### N-series (niche surface lanes — 10 lanes, 18 MCP tools, **9/10 LIVE**, N10 is the wrapper layer itself)

| Lane | Status | Migration / table | New MCP tool(s) | Module path | Data / artifact | Upstream dep |
| ---- | ------ | ----------------- | --------------- | ----------- | --------------- | ------------ |
| **N1** | **LIVE** | `wave24_200_am_artifact_templates.sql` (target_db=autonomath, 50 templates × 5 士業 × 10 種類) | `get_artifact_template` / `list_artifact_templates` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n1_artifact.py` | `data/artifact_templates/{税理士,会計士,行政書士,司法書士,社労士}/*.yaml` (12 each = ~50) | hydration cron: `scripts/cron/load_artifact_templates_2026_05_17.py` |
| **N2** | **LIVE** | `wave24_201_am_houjin_program_portfolio.sql` (target_db=autonomath, 5-axis 0-100 score) | `get_houjin_portfolio` / `find_gap_programs` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n2_portfolio.py` | `am_houjin_program_portfolio` | precompute: `scripts/etl/compute_portfolio_2026_05_17.py` (joins `jpi_adoption_records` for `applied_status`) |
| **N3** | **LIVE** | `wave24_202_am_legal_reasoning_chain.sql` (target_db=autonomath, 160 topics × 5 viewpoints = 800 chains) | `get_reasoning_chain` / `walk_reasoning_chain` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n3_reasoning.py` | `am_legal_reasoning_chain` (三段論法: 法令+通達 / 判例+裁決 / 学説+実務) | seeder: `scripts/build_legal_reasoning_chain.py` |
| **N4** | **LIVE** | `wave24_203_am_window_directory.sql` (target_db=autonomath, ~4,700 1次資料-backed rows) | `find_filing_window` / `list_windows` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n4_window.py` | `am_window_directory` (法務省/国税庁/47都道府県/1727市区町村/jcci/shokokai/JFC/信金界) | crawler: `scripts/etl/crawl_window_directory_2026_05_17.py` |
| **N5** | **LIVE** | (no new migration — wraps `am_alias` ~433K rows from V4 absorption) | `resolve_alias` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n5_synonym.py` | `am_alias` (exact + NFKC, sub-ms btree) | n/a (uses existing alias bank) |
| **N6** | **LIVE** | `wave24_204_am_amendment_alert_impact.sql` (target_db=autonomath) | `list_pending_alerts` / `get_alert_detail` / `ack_alert` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n6_alert.py` | `am_amendment_alert_impact` (per-houjin impact score over `am_amendment_diff` 12,116 rows) | compute cron: `scripts/cron/amendment_impact_compute_2026_05_17.py` |
| **N7** | **LIVE** | `wave24_205_am_segment_view.sql` (target_db=autonomath) | `get_segment_view` / `segment_summary` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n7_segment.py` | `am_segment_view` (jsic_major × size_band × prefecture cells) | rollup cron: `scripts/etl/compute_segment_view_2026_05_17.py` |
| **N8** | **LIVE** (file-backed) | **NO migration** (15 YAML files on disk) | `get_recipe` / `list_recipes` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n8_recipe.py` | `data/recipes/recipe_*.yaml` (15 files: 5 segments × 3 scenarios) | seeder: `scripts/build_recipes_n8_2026_05_17.py` + doc gen `scripts/build_recipe_docs_n8_2026_05_17.py` |
| **N9** | **LIVE** | **MISSING migration** `wave24_206_am_placeholder_mapping.sql` (referenced by both modules — NOT on disk) | `resolve_placeholder` | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n9_placeholder.py` | `data/placeholder_mappings.json` + (intended) `am_placeholder_mapping` table | loader: `scripts/cron/load_placeholder_mappings_2026_05_17.py` + builder `scripts/build_placeholder_mappings_n9_2026_05_17.py` |
| **N10** | **LIVE wrapper layer** | (no DB) | meta-layer; registers + envelope-stamps the other 20 lanes | `src/jpintel_mcp/mcp/moat_lane_tools/__init__.py` (+ `_shared.py` for envelope) | catalogue ordering only | gate flag `JPCITE_MOAT_LANES_ENABLED` (default ON, sub-gated by `settings.autonomath_enabled`) |

## Collision / overlap detection

### Migration ID collisions

Walked `scripts/migrations/wave24_19*..20*.sql` and the SQL files referenced inside moat_lane_tools/*.py.

| Migration ID | Owner | Status |
| ------------ | ----- | ------ |
| `wave24_195` | M2 case-extracted facts | LANDED |
| `wave24_198` | M7 KG-completion predicted edges | LANDED |
| `wave24_200` | N1 artifact templates | LANDED |
| `wave24_201` | N2 houjin portfolio | LANDED |
| `wave24_202` | N3 legal reasoning chain | LANDED |
| `wave24_203` | N4 window directory | LANDED |
| `wave24_204` | N6 amendment alert impact | LANDED |
| `wave24_205` | N7 segment view | LANDED |
| `wave24_206` | **N9 placeholder mapping** | **MISSING** (referenced in `moat_n9_placeholder.py:4` and `autonomath_tools/moat_n9_placeholder.py:4`; SQL file absent) |
| wave24_196 / 197 / 199 | (gap — none reserved by moat lanes) | — |

**Result: 0 collision.** Each lane owns a distinct wave24 number. Gap at 196/197/199 is reserved-but-unused — safe.

### MCP tool name collisions inside the 21-lane roster

Walked `@mcp.tool` decorators in `src/jpintel_mcp/mcp/moat_lane_tools/*.py`:

```
extract_kg_from_text         (M1)
get_entity_relations         (M1)
search_case_facts            (M2)
get_case_extraction          (M2)
search_figures_by_topic      (M3)
get_figure_caption           (M3)
semantic_search_law_articles (M4)
jpcite_bert_v1_encode        (M5)
rerank_results               (M6)
predict_related_entities     (M7)
find_cases_citing_law        (M8)
find_laws_cited_by_case      (M8)
search_chunks                (M9)
opensearch_hybrid_search     (M10 — registered in autonomath_tools, moat_m10 is no-op stub)
multitask_predict            (M11)
get_artifact_template        (N1)
list_artifact_templates      (N1)
get_houjin_portfolio         (N2)
find_gap_programs            (N2)
get_reasoning_chain          (N3)
walk_reasoning_chain         (N3)
find_filing_window           (N4)
list_windows                 (N4)
resolve_alias                (N5)
list_pending_alerts          (N6)
get_alert_detail             (N6)
ack_alert                    (N6)
get_segment_view             (N7)
segment_summary              (N7)
get_recipe                   (N8)
list_recipes                 (N8)
resolve_placeholder          (N9)
```

**Result: 0 collision** between the 21 canonical lane wrappers — each tool name is unique.

### File-level shadows in `src/jpintel_mcp/mcp/autonomath_tools/` (latent collisions)

Walked `git status` + `grep "@mcp.tool"` and found **5 duplicate-file shadows** in `autonomath_tools/` that define the same MCP tool name as a `moat_lane_tools/` sibling. Each shadow is **NOT** currently imported by `autonomath_tools/__init__.py`, so FastMCP does not currently see them — but the files are staged and would fire a registration collision the moment a future commit adds the import.

| Tool name | moat_lane_tools/ (active) | autonomath_tools/ (shadow, not imported) | Gate flag in shadow |
| --------- | -------------------------- | ----------------------------------------- | ------------------- |
| `resolve_alias` | `moat_n5_synonym.py` | `resolve_alias_tool.py:168` | `AUTONOMATH_RESOLVE_ALIAS_ENABLED` (default 1) |
| `find_filing_window` | `moat_n4_window.py` | `window_tools.py:270` | `JPCITE_WINDOW_DIRECTORY_ENABLED` / `AUTONOMATH_WINDOW_DIRECTORY_ENABLED` |
| `list_windows` | `moat_n4_window.py` | `window_tools.py:297` | same as above |
| `get_recipe` | `moat_n8_recipe.py` | `autonomath_tools/moat_n8_recipe.py:341` | (file orphan) |
| `list_recipes` | `moat_n8_recipe.py` | `autonomath_tools/moat_n8_recipe.py:251` | (file orphan) |
| `resolve_placeholder` | `moat_n9_placeholder.py` | `autonomath_tools/moat_n9_placeholder.py:120` | (file orphan) |

**Result: 7 latent name collisions (6 unique tool names; `find_filing_window` + `list_windows` are 2 of 7 events).** No active collision today because `autonomath_tools/__init__.py` does not import any of these shadow files. Risk: a future commit that adds e.g. `from . import moat_n8_recipe` to `autonomath_tools/__init__.py` will brick FastMCP boot.

### Tool name collisions vs the existing 184-tool baseline

Cross-walked all 184 baseline `@mcp.tool` names against the 32 N10 names. Built `/tmp/tools_all.txt` from the full mcp/ tree and ran `diff sort` → only the 3 lane-internal dupes (`get_recipe` / `list_recipes` / `resolve_placeholder`) surfaced. **0 collision with the legacy 184 cohort.**

### Schema name collisions

All N-series tables use the canonical `am_*` namespace (`am_artifact_templates`, `am_houjin_program_portfolio`, `am_legal_reasoning_chain`, `am_window_directory`, `am_amendment_alert_impact`, `am_segment_view`, `am_placeholder_mapping`). Checked against the 78-table `jpi_*` mirror + the existing 12-record-kind `am_entities` schema. **No table-name collision.** `am_amendment_alert_impact` (N6) reads from `am_amendment_diff` (Wave 21 — already shipped) — that is an intentional FK dependency, not a collision.

## Dependency DAG

Edges = "lane A's output is read by lane B".

```
M1 (KG extract)
   └─> am_entity_facts + am_relation
        ├─> M7 (KG completion ensemble; needs am_relation 369K edges export)
        │      └─> am_relation_predicted (mig 198)
        │            └─> M11 (multi-task encoder REL head consumes predicted edges)
        └─> M11 (multi-task corpus prep reads canonical edges)

M2 (case extract regex/JSIC dict)
   └─> am_case_extracted_facts (mig 195)
        └─> M8 (citation rerank candidates)
              └─> M9 (chunk store includes M8 output as a citation-annotated chunk)

M3 (CLIP figures)
   └─> S3 figures_raw/embeddings/
        └─> M10 (OpenSearch knn_vector field reserves M3 384-d output; not wired yet)

M4 (law embed via BERT batch)
   └─> faiss_indexes/v4/
        └─> M10 (OpenSearch knn_vector also reserves M4 384-d output)

M5 (SimCSE BERT fine-tune)
   └─> jpcite-bert-simcse-finetune-* (S3 model artifact)
        └─> M6 (cross-encoder fine-tune, gated on M5 terminal state via watcher)
              └─> M8 (citation rerank uses M6 cross-encoder)

M9 (corpus chunker + embed)
   └─> faiss_indexes/v5/
        └─> M10 (knn_vector population candidate)

M10 (OpenSearch hybrid search — LIVE today)
   └─> opensearch_hybrid_search MCP tool
        ⊥ no downstream lane reads M10 (terminal LIVE surface)

M11 (multi-task encoder + distillation + 5x aug)
   └─> jpcite-multitask-large + jpcite-distill-base (S3 model artifacts)
        ⊥ no downstream lane today (compounds with M5 SimCSE moat for future v5+)
```

```
N1 (artifact template bank — am_artifact_templates)
   └─> get_artifact_template + list_artifact_templates
        └─> N9 (mcp_query_bindings_jsonb references placeholder names; agent resolves
              via resolve_placeholder before invoking the bound MCP tool)

N2 (houjin portfolio — am_houjin_program_portfolio)
   └─> get_houjin_portfolio + find_gap_programs
        └─> N6 (impact score join: alert × portfolio gap pairs)

N3 (legal reasoning chain — am_legal_reasoning_chain)
   └─> get_reasoning_chain + walk_reasoning_chain
        ⊥ leaf consumer (agent-facing)

N4 (filing window — am_window_directory)
   └─> find_filing_window + list_windows
        └─> N9 (placeholder for {filing_window} resolves through find_filing_window)

N5 (alias resolver — am_alias ~433K rows)
   └─> resolve_alias
        └─> ALL downstream LIVE wrappers (used to canonicalize free-text query
              before SQLite lookup; cross-cutting infrastructure)

N6 (amendment alert impact — am_amendment_alert_impact)
   └─> list_pending_alerts + get_alert_detail + ack_alert
        ⊥ leaf (cron `dispatch_webhooks.py` is the mutation owner)

N7 (segment view — am_segment_view)
   └─> get_segment_view + segment_summary
        └─> N2 (gap analysis can use N7's program_count rollup as a fan-out target)

N8 (recipe bank — data/recipes/*.yaml)
   └─> get_recipe + list_recipes
        └─> N9 (recipe steps reference placeholder names; agent resolves them)

N9 (placeholder resolver — am_placeholder_mapping + data/placeholder_mappings.json)
   └─> resolve_placeholder
        └─> meta-consumer for N1 + N8 placeholders, resolves to MCP call schemas
              referencing ALL other lanes (cross-cutting orchestrator)

N10 (wrapper layer — moat_lane_tools/__init__.py + _shared.py)
   └─> registers + envelope-stamps M1-M11 + N1-N9
        ⊥ meta-layer
```

**Critical path** (longest topological chain): `M1 → am_relation → M7 → am_relation_predicted → M11 multi-task encoder → (downstream v5 wave)`. 4 lanes deep, all PENDING today. M2/M8/M10 form a parallel 3-lane chain through citation rerank.

**Cross-cutting infrastructure**: N5 (alias) + N9 (placeholder) + N10 (wrapper) — every other LIVE lane depends on at least one of them at the agent-handoff seam.

## Integration matrix (output → consumer)

| Producer | Output | Consumer | Notes |
| -------- | ------ | -------- | ----- |
| M1 | canonical entity + relation rows | M7, M11 | predicted edges + multi-task REL head |
| M2 | `am_case_extracted_facts` (201,845 rows) | M8, M9, M10 indexer | citation candidates + chunk corpus + OS index |
| M3 | CLIP figure 384-d vectors | M10 knn_vector (reserved field) | future multi-modal merge |
| M4 | law-article 384-d vectors → faiss v4 | M10 knn_vector + agent semantic search | hybrid BM25+vector |
| M5 | SimCSE-tuned BERT checkpoint | M6 (cross-encoder init) + future M4 re-embed | quota-saturating GPU job |
| M6 | cross-encoder checkpoint | M8 (rerank scorer) | watcher-gated launch |
| M7 | `am_relation_predicted` rows | M11 (REL head supervision) + agent KG navigation | mig 198 already landed |
| M8 | citation rerank scored pairs | agent decision layer (REST + MCP) | depends on M6 done |
| M9 | unified chunk store + faiss v5 | M10 OS bulk indexer | 595,545 docs already imagined |
| M10 | OpenSearch hybrid search response | agent (terminal LIVE surface) | coexists with FAISS v3/v4 — both surfaces live in parallel today |
| M11 | multi-task encoder + distill base | future v5 wave (cross-task transfer) | no immediate downstream |
| N1 | artifact template scaffold | N9 (placeholder resolver) + agent (sumbit-ready draft) | scaffold-only, 士業 disclaimer mandatory |
| N2 | per-houjin × program score | N6 (alert impact join), agent (gap analysis) | 5-axis 0-100 score |
| N3 | 三段論法 reasoning chain | agent (Q&A surface) | leaf — no downstream lane |
| N4 | filing window rows | N9 ({filing_window} placeholder) + agent | 7 jurisdiction kinds |
| N5 | canonical_id list | every LIVE lane (N6/N7/N9 + autonomath_tools/* alias-fence) | cross-cutting |
| N6 | amendment alert impact rows | agent (webhook fan-out) | mutation-owned by cron |
| N7 | segment rollup | N2 (gap fan-out target) + agent (BI surface) | jsic × size × pref cell |
| N8 | recipe.yaml step sequence | N9 (placeholder fan-out) + agent (call orchestration) | 15 recipes / 5 士業 × 3 scenarios |
| N9 | resolved MCP call schema | agent (orchestrator) — references ALL other lane tools | meta-orchestrator |
| N10 | registration + envelope | FastMCP surface (216 total tools) | wrapper layer |

## Open issues (8 entries)

1. **MISSING migration `wave24_206_am_placeholder_mapping.sql`** — referenced by `moat_n9_placeholder.py:4` AND `autonomath_tools/moat_n9_placeholder.py:4` but the `.sql` file does not exist on disk. N9 tool will return empty envelope (rationale = "am_placeholder_mapping table missing (migration wave24_206 not applied)") until the SQL lands. Current fallback: `data/placeholder_mappings.json` is staged but the loader `scripts/cron/load_placeholder_mappings_2026_05_17.py` writes to a table that does not yet exist. CRITICAL — block landing of N9 LIVE claim.
2. **5 duplicate-file shadows in `autonomath_tools/`** (see Collision §). Risk = future import line bricks FastMCP boot. Action options: (a) delete the shadows from `autonomath_tools/`, (b) keep them but document the no-import contract, (c) consolidate into a single import seam. Recommended (a).
3. **M10 dual-registration design**: `opensearch_hybrid_search` is registered ONLY in `autonomath_tools/opensearch_hybrid_tools.py`. `moat_lane_tools/moat_m10_opensearch.py` is intentionally a no-op stub (file present so the M1..M11+N1..N9 roster stays contiguous). N10 doc states this explicitly. Risk = a future contributor adds an `@mcp.tool` to the stub and crashes boot. Action: add an inline `assert "no @mcp.tool here"` or compile-time guard.
4. **Wave 49 organic axis vs Wave 50 RC1 moat axis** — they share `JPCITE_MOAT_LANES_ENABLED` env semantics with `settings.autonomath_enabled` sub-gating. If RC1 rolls back (`settings.autonomath_enabled=False`), the entire moat surface disappears in one toggle. That is intentional, but be aware: a Wave 49 RUM beacon outage that auto-disables autonomath will silently drop all 32 moat tools.
5. **N6 `ack_alert` semantics drift** — the wrapper docstring says "read-only ack envelope; mutation owned by the cron". Tests in `tests/test_moat_n6_n7.py` should verify that no `UPDATE` SQL fires from this code path; otherwise a future maintainer might add a stealth mutation.
6. **N7 ↔ N2 gap-fanout overlap**: N7's `segment_summary` and N2's `find_gap_programs` both rollup "programs the houjin should consider". Today N7 is broader (segment-level) and N2 is per-houjin, but if a future refactor merges them, the migration ID + tool name need to be reconciled. No conflict today.
7. **PENDING envelope `upstream_module` strings are stable contracts**: every PENDING wrapper claims its upstream lives at `jpintel_mcp.moat.m*` / `jpintel_mcp.moat.n*`. **None of those modules exist** under `src/jpintel_mcp/moat/`. The contract is implicit ("when the lane lands, the module will appear at this path"). Recommend creating empty `src/jpintel_mcp/moat/__init__.py` + per-lane stub files so the contract is statically validated.
8. **216 tool count vs manifest hold-at-139** — CLAUDE.md SOT note pins manifest at 139 until intentional bump. N10 doc claims 216 runtime. If the next release bump is not synchronized with PyPI/Smithery/Glama registries, agent clients that introspect `mcp.list_tools()` will see 32 tools their schema validation does not know about. Action: track the bump as part of v0.4.0 (or whatever the next Wave 51 release tag is).

## Commit metadata

- Author: Claude Opus 4.7 (audit-only, READ-ONLY)
- Co-authored-by: Claude Opus 4.7 (sub-agent)
- Branch: main (currently 76 commits ahead of origin/main per status)
- Snapshot of HEAD: `4ceb3a898` ("Moat Lane N6 + N7 LIVE")
- Touched files in this commit: this single doc (`docs/_internal/MOAT_INTEGRATION_MAP_2026_05_17.md`)
- Lint impact: doc-only — mypy strict + ruff 0 unaffected.

last_updated: 2026-05-17
