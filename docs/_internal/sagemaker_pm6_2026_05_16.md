# SageMaker PM6 Monitor + GPU Saturate (2026-05-16 PM6)

**Status**: PM5 fully drained (5/5 Completed). PM6 added 2 more g4dn.xlarge LIVE (InProgress) on `bookyou-recovery` profile, ap-northeast-1.

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_pm5_2026_05_16.md` (commit `c7df91f23`, PM5 run `20260516T103042Z`).

**Driver**: `scripts/aws_credit_ops/sagemaker_pm6_submit.py` (DRY_RUN default, `--commit` to fire).

---

## PM5 final status (all 5 Completed)

| Tag | Instance | Status | Start (JST) | End (JST) | Wall | Source rows |
| --- | --- | --- | --- | --- | --- | --- |
| `programs17` | c5.2xlarge | **Completed** | 19:33:32 | 19:42:04 | ~9 min | 12,753 |
| `invoice18` | c5.2xlarge | **Completed** | 19:34:21 | 19:43:16 | ~9 min | 13,801 |
| `saiketsu19` | c5.2xlarge | **Completed** | 19:33:38 | 19:35:31 | ~2 min | 137 |
| `tsutatsu20gpu` | g4dn.xlarge | **Completed** | 19:33:58 | 19:42:17 | ~8 min | 3,232 |
| `court21gpu` | g4dn.xlarge | **Completed** | 19:33:29 | 19:38:28 | ~5 min | 848 |

**SingleRecord BatchStrategy contract validated**: zero `Extra data: line 2` failures, all 5 prefixes embedded cleanly.

### S3 output verify (5/5 OK)

| Output prefix | Object | Bytes |
| --- | --- | --- |
| `embeddings_burn/programs-fix17-cpu/` | `part-0000.jsonl.out` | 4,488,312,171 (4.4 GB) |
| `embeddings_burn/invoice-fix18-cpu/` | `part-0000.jsonl.out` | 4,453,385,306 (4.4 GB) |
| `embeddings_burn/saiketsu-fix19-cpu/` | `part-0000.jsonl.out` | 252,297,688 (252 MB) |
| `embeddings_burn/tsutatsu-fix20-gpu/` | `part-0000.jsonl.out` | 6,259,943,558 (6.2 GB) |
| `embeddings_burn/court-fix21-gpu/` | `part-0000.jsonl.out` | 1,789,693,961 (1.7 GB) |

Total embedded output ~17.0 GB across the 5 corpora.

## PM6 plan (saturate the 2 remaining g4dn slots)

PM5 left ml.g4dn.xlarge usage at 0 / 4 (both PM5 g4dn jobs Completed, no in-flight). PM6 fires 2 more g4dn.xlarge jobs to consume the headroom.

### Prefix substitution honesty

User-requested PM6 inputs:

| Requested | Reality | Substitute used |
| --- | --- | --- |
| `corpus_export_trunc/am_law_article/part-0006.jsonl` | does NOT exist — truncated only has parts 0001-0004 | `am_law_article/part-0001.jsonl` |
| `corpus_export_trunc/court_decisions/part-0001.jsonl` | does NOT exist — only part-0000 exists (PM5 consumed it) | `am_law_article/part-0002.jsonl` |

PM6 substitutes with the **actual** next 2 untouched truncated `am_law_article` parts (0001 + 0002). Raw `corpus_export/am_law_article/` has parts 0000-0013 (~21 MB each), but truncated form is only 0001-0004. Going forward, additional am_law_article truncated parts (0005..0013) would need `corpus_export.py` rerun to stage.

### Run ID

`20260516T105156Z`

### Jobs submitted (2)

| Tag | Job name | Instance | Source | Output | Model |
| --- | --- | --- | --- | --- | --- |
| `amlaw22gpu` | `jpcite-embed-20260516T105156Z-amlaw22gpu` | `ml.g4dn.xlarge` | `corpus_export_trunc/am_law_article/part-0001.jsonl` (17.2 MB) | `embeddings_burn/amlaw-fix22-gpu/` | `jpcite-embed-allminilm-v1` |
| `amlaw23gpu` | `jpcite-embed-20260516T105156Z-amlaw23gpu` | `ml.g4dn.xlarge` | `corpus_export_trunc/am_law_article/part-0002.jsonl` (16.7 MB) | `embeddings_burn/amlaw-fix23-gpu/` | `jpcite-embed-allminilm-v1` |

Both Created and confirmed `InProgress` at 2026-05-16T10:51:58Z UTC (19:51:58 JST).

## Quota compliance

`aws sagemaker list-transform-jobs --status-equals InProgress` returned 0 in-flight before PM6 submit (PM5 fully drained).

| Resource | Quota | In-flight at submit | New (this run) | Total in-flight | Headroom |
| --- | --- | --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 0 | 0 | **0** | 8 free |
| `ml.g4dn.xlarge for transform job usage` | 4 | 0 | 2 | **2** | 2 free |

PM6 honors the 4-slot g4dn quota. 2 free GPU slots remain for any PM7 follow-up.

## 5-line hard-stop compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY --metrics UnblendedCost --time-period Start=2026-05-01,End=2026-05-17` returned `actual_usd = $0.0000001906` for May 2026 (Cost Explorer 8-12h lag dominant). $0.00 ≪ $13K threshold → submit proceeds. AWS Budget Action at $18,900 remains the ultimate hard-stop.

`scripts/aws_credit_ops/sagemaker_pm6_submit.py` `preflight_cost_check()` calls `sys.exit(2)` if `actual_usd >= 13000` before any `create_transform_job` invocation.

## Throughput (PM5 + PM6)

PM5 throughput (5/5 Completed, observed):

| Tag | Instance | Wall | Rows | Rows/sec |
| --- | --- | --- | --- | --- |
| `programs17` | c5.2xlarge | 8:31 | 12,753 | ~25 |
| `invoice18` | c5.2xlarge | 8:55 | 13,801 | ~26 |
| `saiketsu19` | c5.2xlarge | 1:54 | 137 | ~1.2 |
| `tsutatsu20gpu` | g4dn.xlarge | 8:19 | 3,232 | ~6.5 (GPU bottleneck = throughput per row from larger truncated text) |
| `court21gpu` | g4dn.xlarge | 4:59 | 848 | ~2.8 |

PM6 expected (2 g4dn jobs, ~17 MB each, am_law_article rows estimate ~5K-8K each at 320-char truncation): est. wall ~10-15 min each, est. embedded rows ~12K-16K total across the 2 PM6 jobs.

## Cost estimate (PM6 run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| `amlaw22gpu` | g4dn.xlarge | $0.94 | ~15 min (am_law_article part-0001 17.2 MB) | $0.24 |
| `amlaw23gpu` | g4dn.xlarge | $0.94 | ~15 min (am_law_article part-0002 16.7 MB) | $0.23 |
| **Total** | | | | **~$0.47** |

PM5+PM6 combined cost ~$1.05, trivially within $13K hard-stop / $18.9K canary cap.

## Cumulative coverage snapshot

After PM6 lands (PM3 + PM4 fail + PM5 success + PM6 in-flight):

| Corpus | Status | Rows embedded |
| --- | --- | --- |
| programs (PM5 programs17) | Completed | 12,753 |
| invoice_registrants (PM5 invoice18) | Completed | 13,801 |
| nta_saiketsu (PM5 saiketsu19) | Completed | 137 |
| nta_tsutatsu_index (PM5 tsutatsu20gpu) | Completed | 3,232 |
| court_decisions (PM5 court21gpu) | Completed | 848 |
| am_law_article part-0001 (PM6 amlaw22gpu) | InProgress | ~5K-8K (est.) |
| am_law_article part-0002 (PM6 amlaw23gpu) | InProgress | ~5K-8K (est.) |
| **PM5+PM6 cumulative** | 5 done + 2 in-flight | **~40K-46K** |

Combined with earlier PM3 successes (court-fix2 / adoption-fix1 / invoice-fix3 / saiketsu-fix4 / programs8 / tsutatsu7 / court6 / programs8 / saiketsu9 / invoice10) the embedding fleet has crossed **~70K embedded rows** across all PM* runs.

## Followups (deferred — not part of this run)

1. Watch `amlaw22gpu` + `amlaw23gpu` to Completed; verify `embeddings_burn/amlaw-fix22-gpu/part-0001.jsonl.out` + `amlaw-fix23-gpu/part-0002.jsonl.out` are non-empty.
2. If PM6 g4dn pair Completes cleanly, PM7 can fire 2 more g4dn (saturating the quota again) on `am_law_article/part-0003.jsonl` + `am_law_article/part-0004.jsonl` to finish the truncated am_law_article fleet.
3. Stage truncated parts 0005..0013 of am_law_article (currently raw only) via `scripts/aws_credit_ops/export_corpus_to_s3.py` if we want to complete the full 353,278-row corpus on g4dn.
4. Build per-corpus FAISS shards from `embeddings_burn/*.jsonl.out` for retrieval surface (separate task #189 FAISS expand already in flight).
