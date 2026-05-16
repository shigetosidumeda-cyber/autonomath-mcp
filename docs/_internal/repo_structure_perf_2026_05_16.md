# PERF-9: scripts/aws_credit_ops Modularization Proposal (2026-05-16)

**Status**: PROPOSAL-ONLY — no files moved yet.
**Scope**: `scripts/aws_credit_ops/` directory only.
**Lane**: `[lane:solo]`

---

## 1. Current Size (honest counts, `find -maxdepth 1`)

| metric                                            | count |
|---                                                |---:   |
| total files (`*.py` + `*.sh`)                     | **327** |
| `.py` files                                       | **301** |
| `.sh` files                                       | **26**  |
| `generate_*.py` (all variants)                    | **272** |
| of which `generate_*_packets.py` (Wave packets)   | **269** |
| of which non-packet generators (deep/ultradeep/showcase manifests) | **3**   |

Existing subdirectories under `scripts/aws_credit_ops/`: only `__pycache__/` (none of the proposed clusters are pre-existing).

## 2. Import Audit

Cross-imports inside `scripts/aws_credit_ops/`:

```
262  from scripts.aws_credit_ops._packet_base    import (...)
261  from scripts.aws_credit_ops._packet_runner  import run_generator
```

Other `scripts.*` cross-references: **0** (no fan-out into sibling `scripts/` subtrees).

**Cycle status**: NO cycles detected. The shape is a strict star — `_packet_base.py` + `_packet_runner.py` at the centre, 262 generators as leaves. Both shared modules only import stdlib (`__future__`, `collections.abc`, `dataclasses`, `datetime`, `pathlib`, `typing`, plus stdlib internals via `_packet_base`).

## 3. Cluster Breakdown

| cluster (proposed dir)         | members (top-level patterns)                                                                                                                  | count |
|---                             |---                                                                                                                                            |---:   |
| `packet_generators/`           | `generate_*_packets.py`                                                                                                                       | **269** |
| `manifest_generators/`         | `generate_deep_manifests.py`, `generate_ultradeep_manifests.py`, `generate_sample_packet_showcase.py`                                          | **3**   |
| `batch_ops/`                   | `submit_*.sh`, `monitor_jobs.sh`, `teardown_credit_run.sh`, `submit_job.sh`, `submit_all.sh`, `submit_houjin360_batches.sh`, etc.              | **10**  |
| `embed_ops/`                   | `sagemaker_*`, `faiss_*`, `build_embeddings_db.py`, `build_faiss_index_from_embeddings.py`, `build_faiss_index_gpu.py`, `build_faiss_v2_*.py`  | **8**   |
| `glue_athena_ops/`             | `run_glue_crawler.sh`, `run_athena_query.sh`, `run_big_athena_query.sh`, registration helpers                                                  | **6**   |
| `cost_ops/`                    | `cost_ledger.sh`, `burn_target.py`, `stop_drill.sh`, `continuous_burn_monitor.sh`, `emit_burn_metric.py`, `enable_burn_schedule.sh`            | **5**   |
| `infra_lambda/`                | `deploy_*.sh` (auto-stop, burn-metric, attestation, cf-loadtest), `cf_loadtest_*`, `cloudfront_packet_mirror_setup.sh`, `create_sns_topic_*`, `open_dashboard.sh`, `get_schedule.sh`, `emit_canary_attestation.py`, `entrypoint_gpu_burn.sh` | **15**  |
| `validation_etl/`              | `validate_run_artifacts.py`, `aggregate_run_ledger.py`, `etl_raw_to_derived.py`, `export_corpus_to_s3.py`, `export_to_r2.sh`, `sample_search_packet.py`, `render_packet_preview.py`, `textract_batch.py`, `j16_textract_apse1.py` | **9**   |
| **top level (shared/leave)**   | `_packet_base.py`, `_packet_runner.py`                                                                                                         | **2**   |
| **unclassified (manual triage in PR1)** | residual                                                                                                                              | ~0–5  |

Coverage of the cluster table: **327 − 2 (shared) − ~5 (residual)** ≈ 320 / 327.

## 4. Proposed Structure

```
scripts/aws_credit_ops/
├── _packet_base.py             # KEEP at top level — referenced by 262 generators
├── _packet_runner.py           # KEEP at top level — referenced by 261 generators
├── packet_generators/          # 269 × generate_*_packets.py
├── manifest_generators/        # 3 × generate_*_manifests.py
├── batch_ops/                  # 10 × submit_/monitor_/teardown_
├── embed_ops/                  # 8 × sagemaker_/faiss_/build_embeddings*/build_faiss*
├── glue_athena_ops/            # 6 × run_glue_/run_athena_/register_
├── cost_ops/                   # 5 × cost_/burn_/stop_drill
├── infra_lambda/               # 15 × deploy_/cf_loadtest_/cloudfront_/emit_canary
└── validation_etl/             # 9 × validate_/aggregate_/etl_/export_/textract_
```

### Constraint: `_packet_base.py` + `_packet_runner.py` STAY top-level

262/269 packet generators reference these two modules. Moving them would force 262 import-path rewrites and would break every concurrent agent currently spawning packet runs. Keep at top level until packet generators are renamed in PR1, then re-evaluate in PR9.

## 5. Migration Plan (cluster-by-cluster, small PRs)

| PR  | scope                                        | files moved | risk      | blocking? |
|---  |---                                           |---:         |---        |---        |
| 1   | `packet_generators/` (269 generators)        | 269         | **HIGH**  | YES — must be done first or last, never mid-stream |
| 2   | `manifest_generators/`                       | 3           | low       | NO |
| 3   | `batch_ops/`                                 | 10          | low       | NO |
| 4   | `embed_ops/`                                 | 8           | low       | NO |
| 5   | `glue_athena_ops/`                           | 6           | low       | NO |
| 6   | `cost_ops/`                                  | 5           | low       | NO |
| 7   | `infra_lambda/`                              | 15          | medium    | touches Lambda deploy scripts — verify Lambda update workflow first |
| 8   | `validation_etl/`                            | 9           | low       | NO |
| 9   | post-move: consider folding shared modules   | 2           | high      | NO — defer |

### Per-PR checklist

1. `git mv` the cluster files (preserves git blame).
2. Update any `import` paths inside the moved files (mostly none — only PR1 touches the 262 `_packet_base`/`_packet_runner` references, which IF we leave shared modules at top level remain valid).
3. Update GHA workflows (`*.yml`) — `grep -rn "scripts/aws_credit_ops/generate_" .github/`.
4. Update `Makefile` targets — `grep -n "scripts/aws_credit_ops/" Makefile`.
5. Update `infra/aws/batch/*.json` job definitions if any reference packet generators by full path.
6. Run `pytest -q -x` then `mypy --strict scripts/aws_credit_ops/`.

### Concurrent-agent safety

- PR1 (269 generators) cannot land while any agent is generating packets. Schedule for a maintenance gap.
- PRs 2–8 each move <20 files and touch disjoint name patterns. Safe to interleave with active waves.
- DO NOT mix two cluster moves in one PR.

## 6. Risks

1. **262-edge fan-out**: `_packet_base.py` and `_packet_runner.py` are referenced by 262/261 files. Any rename or relocation must update every leaf. Keep at top level.
2. **GHA workflow drift**: at least 4 GHA workflows reference `scripts/aws_credit_ops/*.py` by full path. Update lock-step with each cluster move.
3. **AWS Batch JobDefinition paths**: container entry points may reference full script paths. Audit `infra/aws/batch/*.json` before PR1.
4. **Concurrent agents**: ~12 agents currently producing packets/manifests in parallel. PR1 must serialize; PRs 2–8 are tolerable.
5. **No cycles detected today**, but moving to packages risks introducing them via `__init__.py` re-exports. Use empty `__init__.py` (no re-export logic).

## 7. Next Action

PROPOSAL-only. No files moved in this commit. Subsequent PRs land cluster-by-cluster after concurrent-agent quiescence windows are confirmed.

---

*Generated by PERF-9 audit, 2026-05-16. Source counts re-runnable via `find scripts/aws_credit_ops -maxdepth 1 -name "*.py" -type f | wc -l` and `grep -h "^from scripts\.aws_credit_ops" scripts/aws_credit_ops/*.py | sort | uniq -c | sort -rn | head -20`.*
