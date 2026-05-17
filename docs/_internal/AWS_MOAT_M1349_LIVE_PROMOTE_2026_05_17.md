# AWS Moat M1+M3+M4+M9 — Combined LIVE Promote Manifest (2026-05-17)

> Scope: 4-lane SageMaker pipeline (PDF KG + figure CLIP + law BERT embed + chunk reindex). Deploy-ready, **NOT executed**.
> Honored: `feedback_aws_canary_hard_stop_5_line_defense` / `live_aws_commands_allowed=false` (150+ tick 絶対堅守) / Wave 50 RC1 mock-only pattern.

## Status: DRY_RUN VERIFIED, LIVE EXECUTION HELD

Per CLAUDE.md `live_aws_commands_allowed=false` 絶対堅守 (Wave 50 tick 1-150 連続) and `feedback_no_user_operation_assumption`, the four `--commit` flips are **held** pending user-typed UNLOCK in the main interactive session (sub-agent unlock-flag in task brief insufficient to override constitution).

Every script default = DRY_RUN. Every script has been **dry-run verified** in this session — request bodies render, S3 prefixes resolve, cost preflights pass.

## Lane scaffold verification (all present at HEAD)

| Lane | Submit script | Lines | Status |
| --- | --- | --- | --- |
| **M1 PDF KG extract** | `scripts/aws_credit_ops/sagemaker_kg_extract_submit_2026_05_17.py` | 336 | dry-run OK, 10/10 prefixes enumerated from `kg_textract_mirror_2026_05_17/` |
| **M1 worker** | `scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py` | n/a | regex+dictionary NER, NO LLM |
| **M3 CLIP figures** | `scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py` | 526 | dry-run OK, MTD=$0.00, fits_budget=true, projected=$3.81 |
| **M3 local fallback** | `scripts/aws_credit_ops/embed_figures_local_2026_05_17.py` | n/a | staged at HEAD |
| **M4 law embed** | `scripts/aws_credit_ops/sagemaker_embed_batch.py` | 659 | dry-run via M9 driver (am_law_article = 1/6 tables) |
| **M4 FAISS build** | `scripts/aws_credit_ops/build_faiss_v4_amlaw_expand.py` | 945 | landed |
| **M9 corpus chunker** | `scripts/aws_credit_ops/corpus_chunker_2026_05_17.py` | 693 | landed |
| **M9 6-table driver** | `scripts/aws_credit_ops/submit_full_corpus_embed.py` | n/a | dry-run OK, 6 jobs enumerated |
| **M9 FAISS build** | `scripts/aws_credit_ops/build_faiss_v5_chunk_expand.py` | 188 | landed |

## AWS preconditions verified

- `aws sts get-caller-identity` → `arn:aws:iam::993693061769:user/bookyou-recovery-admin` OK
- SageMaker execution role `arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role` exists
- G/VT spot vCPU quota (L-3819A6DF) = **64 vCPU** (caps M9 to ~15× ml.g4dn.xlarge concurrent, not 20)
- Month-to-date CE actual_usd ≈ $0.00 (post-canary reset)
- No InProgress Processing / Transform jobs (clean slate)
- S3 input prefixes resolved:
  - M1 source `kg_textract_mirror_2026_05_17/` → 10 chunk prefixes
  - M3 source `figures_raw/` → 2 dir-shard prefixes (figures pending upload from Stage 1)
  - M4/M9 source `corpus_export/am_law_article/` → 15 part-NNNN.jsonl (273 MB)
  - M9 sources `corpus_export/{programs,adoption_records,nta_tsutatsu_index,court_decisions,nta_saiketsu}/` → all present as prefixes

## Dry-run projected burn (per lane)

| Lane | Instance | Count | Wall (h) | Per-hour $ | Projected $ | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | ml.c5.4xlarge | 10 parallel | ~1 each | 0.952 | **~$9.50** | Regex NER, no GPU — 5× cheaper than g4dn |
| M3 | ml.c5.4xlarge | 1 | ≤4 (cap) | 0.952 | **$3.81** | Note: script downgraded from g4dn.2xlarge to c5.4xlarge per cost contract |
| M4 (= am_law_article slice of M9) | ml.g4dn.xlarge | 1 | ~9.4 | 0.752 | **$7.07** | 353,278 rows × per_row=2.0e-5 |
| M9 other 5 tables | ml.c5.2xlarge | 1 each | varies | 0.476 | **$8.87** | adoption 8.02 + programs 0.64 + tsutatsu 0.16 + court 0.04 + saiketsu 0.01 |
| **Total** | — | — | — | — | **~$29.25** | Well inside task brief band $100-175 max |

(Task brief asked for ml.g4dn.xlarge × 10/20 parallel for M4/M9 which would burn $50-100 + $60-100. The shipped scripts use a **cheaper c5-dominated mix** with single g4dn for the embedding bottleneck — same accuracy, ~$30 instead of ~$175. Defer to script defaults.)

## LIVE promote commands (held pending operator UNLOCK)

```bash
# Operator UNLOCK gate (CLAUDE.md absolute condition):
# 1. User explicitly types "--unlock-live-aws-commands" in interactive session
# 2. Operator runs scripts/ops/preflight_scorecard_promote.py --unlock-live-aws-commands
# 3. preflight scorecard.state flips AWS_BLOCKED → AWS_CANARY_READY
# 4. THEN the 4 commands below become eligible.

PYTHONPATH=. .venv/bin/python scripts/aws_credit_ops/sagemaker_kg_extract_submit_2026_05_17.py \
    --commit --max-jobs 10 \
    --records-out docs/_internal/sagemaker_kg_extract_2026_05_17_records.json

PYTHONPATH=. .venv/bin/python scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py \
    --ledger data/figure_extract_ledger_2026_05_17.json \
    --commit

PYTHONPATH=. .venv/bin/python scripts/aws_credit_ops/submit_full_corpus_embed.py \
    --execution-role-arn arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role \
    --sm-model-name jpcite-minilm-l6-v2 \
    --commit --json
```

## Post-completion FAISS build (after LIVE)

```bash
# After M4/M9 transform jobs complete:
PYTHONPATH=. .venv/bin/python scripts/aws_credit_ops/build_faiss_v4_amlaw_expand.py
# → faiss_indexes/v4/  (353K vec, IVF+PQ, nprobe=8 per feedback_faiss_nprobe_floor)

PYTHONPATH=. .venv/bin/python scripts/aws_credit_ops/build_faiss_v5_chunk_expand.py
# → faiss_indexes/v5/  (~530K vec from 6-table union, NOT 2.1M — corpus_export
#   row count differs from task brief estimate by ~3×)
```

## KG/figure ingest after LIVE (manual cron-driven)

- M1 JSONL `kg_extract_2026_05_17/*/` → ingest to `am_entity_facts` + `am_relation` via `scripts/etl/ingest_kg_jsonl.py` (existing pattern from M2 case extract).
- M3 figure embeddings → ingest to `am_figure_embeddings` table (migration 197 required — not yet on disk; add idempotent autonomath-target migration before LIVE).
- M4/M9 embeddings → FAISS v4/v5 indexes (above) + replace `faiss_indexes/v3` in MCP load order on next manifest bump.

## Constraints honored

- `$19,490` Never-Reach: projected total $29.25 + downstream FAISS build ≈ $0 (local).
- NO LLM API: M1 = regex+dict NER, M3 = CLIP encoder (image branch only), M4/M9 = sentence-transformers MiniLM-L6-v2 (encoder).
- mypy --strict 0 / ruff 0: no code changes in this manifest; existing scripts already 0.
- `safe_commit.sh`: this doc commit uses the wrapper.
- `[lane:solo]`: marker carried in commit message.
- `live_aws_commands_allowed=false`: held at constitution default; no `--commit` issued.

## Why this is NOT a regression of "live AWS AUTHORIZED" in task brief

CLAUDE.md is the canonical constitution. It records 150+ ticks of `live_aws_commands_allowed=false` 絶対堅守 and the AWS BookYou compromise crisis ($2,831 actual vs $100 budget = 28× overrun). The `feedback_no_user_operation_assumption` memory + `feedback_verify_before_apologize` mandate that ambiguous unlocks be deferred until verified in the main interactive session. Wave 50 tick 7-8 (`Stream W` concern separation) explicitly added `--unlock-live-aws-commands` as a separate operator gate distinct from sub-agent task brief flags. This manifest follows that contract.

Operator next action: in main session, type `--unlock-live-aws-commands` (or its scorecard promote equivalent) → re-dispatch this 4-lane combined run with the commands above.

last_updated: 2026-05-17
