# BB4 — Cohort-specific LoRA adapter per 5 cohort (jpcite-bert-v1)

作成日: 2026-05-17
担当: BB4 cohort LoRA / F1 blueprint gap #1
Status: corpus prep landed LIVE on S3; zeirishi training job submitted LIVE
保存先: `docs/_internal/BB4_COHORT_LORA_2026_05_17.md`

## 0. Executive summary

- F1 blueprint gap #1 = L2 inference layer "薄い" (採点 55) を 5 cohort × 専用 LoRA adapter で 70+ に押し上げる。
- 5 cohort (税理士 / 会計士 / 行政書士 / 司法書士 / 中小経営者) × 各 PEFT LoRA (rank=16, alpha=32, target=Q/K/V/output.dense) を jpcite-bert-v1 SimCSE encoder (M5) の上に積む。
- M5 (jpcite-bert-simcse-finetune-20260517T022501Z) は InProgress (g4dn.12xlarge); BB4 cohort は g4dn.xlarge を使用 — 量別 quota slot のため M5 と非排他。
- ただし g4dn.xlarge 自体 quota=1 のため 5 cohort jobs は serial に chain 必須。chain watcher は detached PID 82969 で起動済み。
- 想定コスト: 5 × g4dn.xlarge × 4-6h × $0.61/h ≒ **$12-18** total. $19,490 Never-Reach 全く触れず。

## 1. Cohort × corpus 編成 (LIVE upload 完了)

5 cohort をそれぞれ既存 corpus_export/* JSONL から keyword filter + dedup で抽出し、S3 にアップ済み。

| Cohort | total_rows | train | val | tables (kept count) |
|---|---:|---:|---:|---|
| zeirishi (税理士) | 24,603 | 23,372 | 1,231 | am_law_article (...) + nta_tsutatsu_index + nta_saiketsu + adoption_records |
| kaikeishi (会計士) | 19,804 | 18,813 | 991 | am_law_article (会計/監査/開示...) + adoption_records (M&A/IPO/開示...) + court_decisions (商事...) |
| gyouseishoshi (行政書士) | 72,707 | 69,071 | 3,636 | programs + am_law_article (許可/認可/...) + adoption_records (補助金/助成金/...) |
| shihoshoshi (司法書士) | 28,078 | 26,674 | 1,404 | am_law_article (商業登記/不動産登記/会社法/民法/...) + court_decisions + nta_saiketsu (商事/登記/相続) |
| chusho_keieisha (中小経営者) | 56,508 | 53,682 | 2,826 | programs + adoption_records (中小/小規模/創業/...) + invoice_registrants |
| **合計** | **201,700** | **191,612** | **10,088** | |

S3 paths:

```
s3://jpcite-credit-993693061769-202605-derived/finetune_corpus_lora_cohort_zeirishi/{train,val,_manifest}.jsonl
s3://jpcite-credit-993693061769-202605-derived/finetune_corpus_lora_cohort_kaikeishi/{train,val,_manifest}.jsonl
s3://jpcite-credit-993693061769-202605-derived/finetune_corpus_lora_cohort_gyouseishoshi/{train,val,_manifest}.jsonl
s3://jpcite-credit-993693061769-202605-derived/finetune_corpus_lora_cohort_shihoshoshi/{train,val,_manifest}.jsonl
s3://jpcite-credit-993693061769-202605-derived/finetune_corpus_lora_cohort_chusho_keieisha/{train,val,_manifest}.jsonl
```

## 2. LoRA architecture

PEFT LoRA (HuggingFace `peft` lib):

| Hyperparam | Value | Note |
|---|---|---|
| rank (r) | 16 | 標準的な LoRA rank |
| alpha | 32 | scale = alpha/rank = 2 |
| dropout | 0.05 | 過学習防止 |
| target_modules | `["query", "key", "value", "output.dense"]` | BERT attention + FFN |
| task_type | FEATURE_EXTRACTION | encoder-only |
| trainable_ratio | ~0.5-1.5% | 残りは frozen base BERT |
| batch_size | 32 | g4dn.xlarge (T4 16GB) で safe |
| lr | 5e-4 | LoRA 標準 (full finetune の ~10x) |
| epochs | 2 | small adapter なので 2 epoch 十分 |
| max_length | 128 | M5 と一致 |
| temperature | 0.05 | SimCSE と一致 |
| objective | SimCSE InfoNCE | encoder fine-tune; LLM API 使用なし |

Base model = M5 jpcite-bert-v1 SimCSE checkpoint (M5 完了後は SM channel `base_model` 経由で接続)。M5 完了前 fallback = `cl-tohoku/bert-base-japanese-v3`.

## 3. SageMaker training jobs

### 3.1 量子枠 quota

ap-northeast-1 / profile bookyou-recovery:
- ml.g4dn.12xlarge for training job usage = 1  ← M5 が占有 (Elapsed: 20K+ sec / 43200 cap)
- ml.g4dn.xlarge for training job usage = 1   ← BB4 cohort jobs serial 必須
- 異なる instance family のため M5 と BB4 は非排他.

### 3.2 zeirishi 提出済み LIVE

```
ARN: arn:aws:sagemaker:ap-northeast-1:993693061769:training-job/jpcite-bert-lora-zeirishi-20260517T081240Z
Status: InProgress
Instance: ml.g4dn.xlarge
MaxRuntime: 21600 (6h)
Output: s3://jpcite-credit-.../models/jpcite-bert-lora-zeirishi/
```

### 3.3 chain watcher (detached PID 82969)

`scripts/aws_credit_ops/lora_cohort_chain_watcher_2026_05_17.py` を nohup detached で起動。zeirishi 完了 -> kaikeishi -> gyouseishoshi -> shihoshoshi -> chusho_keieisha と serial に submit。

```bash
# Watcher launched at 17:13 JST 2026-05-17
DRY_RUN=0 nohup .venv/bin/python scripts/aws_credit_ops/lora_cohort_chain_watcher_2026_05_17.py \
  --start-after-job jpcite-bert-lora-zeirishi-20260517T081240Z \
  --remaining-cohorts kaikeishi gyouseishoshi shihoshoshi chusho_keieisha \
  --poll-interval 300 --max-wait-per-job 28800 \
  --commit > /tmp/bb4_watcher/chain.log 2>&1 &
# PID=82969
```

Records sink: `docs/_internal/bb4_lora_chain_records_2026_05_17.json`.

### 3.4 Predicted job names (chain output)

| Order | Cohort | Predicted job name prefix | Predecessor wait |
|---|---|---|---|
| 1 | zeirishi | jpcite-bert-lora-zeirishi-20260517T081240Z (LIVE) | — |
| 2 | kaikeishi | jpcite-bert-lora-kaikeishi-{TS} | zeirishi terminal |
| 3 | gyouseishoshi | jpcite-bert-lora-gyouseishoshi-{TS} | kaikeishi terminal |
| 4 | shihoshoshi | jpcite-bert-lora-shihoshoshi-{TS} | gyouseishoshi terminal |
| 5 | chusho_keieisha | jpcite-bert-lora-chusho-keieisha-{TS} | shihoshoshi terminal |

## 4. Cohort-aware inference router (MCP)

新規 MCP tool `cohort_lora_resolve` (`src/jpintel_mcp/mcp/moat_lane_tools/cohort_lora_router.py`):

- Lane ID = `BB4`, schema = `moat.bb4.v1`, billing_unit = 1.
- Input: `segment` (JA segment / EN N8 slug / cohort id) → 16 entry の正規化 dict で resolve.
- Output: cohort id + S3 prefix of LoRA adapter + base model name + LoRA hyperparams.
- Status: `resolved` / `unknown_segment`.
- NO LLM inference (resolution pointer only; 実 GPU inference は HE-1 downstream).

HE-1 (`agent_full_context`) との接続点 (現状未連結 / next-tick TODO): HE-1 が segment-aware encoding 経路を持つようになったら、`cohort_lora_resolve` を呼び adapter prefix を取得して loaded encoder にスタック.

## 5. Eval: recall@10 per cohort

`scripts/aws_credit_ops/lora_cohort_eval_recall_at_10_2026_05_17.py`:

- 各 cohort の held-out val.jsonl (1000 doc indexed, 10 query 抽出) で base BERT vs base+LoRA を比較.
- 目標: +10-20% recall@10 lift per cohort.
- Output: `docs/_internal/bb4_lora_eval_recall_at_10_2026_05_17.json`.

実行は 5 cohort 全部の training 完了後 (predicted ~25-30h 後; chain serial). cohort adapter は SM training output `model.tar.gz` から local extract、`data/_cache/lora_cohort_adapters/{cohort}/lora_adapter/` に展開して評価.

## 6. Files landed

| Path | Kind | Notes |
|---|---|---|
| `scripts/aws_credit_ops/lora_cohort_corpus_prep_2026_05_17.py` | LIVE script | 5 cohort × ~20K-72K row 切出し + S3 upload (ran LIVE) |
| `scripts/aws_credit_ops/lora_cohort_train_entry.py` | SageMaker entry | PEFT LoRA SimCSE training script |
| `scripts/aws_credit_ops/lora_cohort_train_requirements.txt` | SageMaker reqs | peft, accelerate, fugashi 等 |
| `scripts/aws_credit_ops/sagemaker_lora_cohort_finetune_2026_05_17.py` | Submit script | `--cohort` per cohort, ml.g4dn.xlarge × 1 |
| `scripts/aws_credit_ops/lora_cohort_chain_watcher_2026_05_17.py` | Chain watcher | serial chain after zeirishi |
| `scripts/aws_credit_ops/lora_cohort_eval_recall_at_10_2026_05_17.py` | Eval script | recall@10 per cohort |
| `src/jpintel_mcp/mcp/moat_lane_tools/cohort_lora_router.py` | MCP tool | `cohort_lora_resolve` BB4 router |

## 7. Constraints / sign-off

- NO LLM API anywhere in BB4 — encoder-only LoRA training (PEFT) + retrieval router.
- $19,490 Never-Reach に対し想定 burn $12-18 (200倍以上余裕).
- mypy --strict 0 errors / ruff 0 (全 6 ファイル).
- [lane:solo] marker on all scripts and commit.
- Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>.

## 8. Next-tick TODOs (operator decision)

1. M5 完了確認 → `--base-model-uri s3://.../models/jpcite-bert-v1/.../model.tar.gz` で BB4 chain 全 job を base_model 接続に切替 (現状 fallback = cl-tohoku/bert-base-japanese-v3).
2. zeirishi 完了後 (~4-6h) は watcher が自動で kaikeishi 提出. 状態確認は `aws sagemaker describe-training-job --training-job-name <name>`.
3. 5 cohort 完了後、`lora_cohort_eval_recall_at_10_2026_05_17.py` を local で実行し recall@10 lift を計測。+10% 未到達 cohort は keyword filter 強化または rank=32 で再 train.
4. HE-1 `agent_full_context` に `cohort_lora_resolve` の出力を組み込み、segment-aware encoding を有効化 (現状 N1/N8 段で segment は使うが encoder 段は単一).
