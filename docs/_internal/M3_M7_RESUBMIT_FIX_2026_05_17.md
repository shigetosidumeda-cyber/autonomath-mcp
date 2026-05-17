# M3 + M7 fix re-submit — 2026-05-17

## Root causes (first wet-run, commit fa8d0d2c4)

### M3 — SageMaker Processing Job code-channel path bug
SageMaker mounts the entire S3 `code/` channel prefix at
`/opt/ml/processing/input/code/`. The upload key was
`figure_embeddings_code/{job_name}/embed.py` but the channel mounted
the broad `figure_embeddings_code/` prefix, placing the file at
`/opt/ml/processing/input/code/{job_name}/embed.py`. The
`ContainerEntrypoint` expected `/opt/ml/processing/input/code/embed.py`
flat, so the container exited 1 before any embedder work.

### M7 — PyKEEN argparse dash-vs-underscore bug (4 jobs)
SageMaker passes HyperParameters verbatim as `--<key> <value>` to the
training entrypoint. The submission script used underscore dict keys
(`batch_size`, `embedding_dim`, ...) so the launch command became
`--batch_size 512` etc. The PyKEEN entrypoint argparse defines those
options with dashes (`--batch-size`, `--embedding-dim`, ...), so all 4
training jobs exited 2 immediately with `unrecognized arguments`.

### M3 — bonus model fix
The 135 figure embeddings previously populated used English
`openai/clip-vit-base-patch32`. Re-running with the Japanese
`rinna/japanese-clip-vit-b-16` improves moat depth on Japanese
hou-rei PDF figures.

## Fixes

### M3 — `sagemaker_clip_figure_submit_2026_05_17.py`
1. `_upload_code_channel` uploads to per-job sub-prefix
   `figure_embeddings_code/{job_name}/embed.py` and returns the
   sub-prefix in the meta dict.
2. `_build_processing_inputs` takes the per-job sub-prefix and uses it
   as the `S3Uri` for the `code` input channel — SageMaker mounts only
   that sub-prefix so `embed.py` sits flat under the mount root.
3. `_build_processing_request` and `main()` thread the per-job
   sub-prefix through.
4. `_stamp_job_name()` emits `jpcite-figure-clip-jp-…` so re-submitted
   Japanese-CLIP jobs are distinguishable from earlier English-CLIP
   attempts.
5. `EMBEDDER_SCRIPT` pins `transformers==4.36.2` + `torchvision==0.15.2`
   to match the base SageMaker `pytorch-inference:2.0.0-gpu-py310`
   image's PyTorch 2.0 (transformers >=4.45 requires torch >=2.4 and
   refuses to load otherwise — observed in the first wet-run after the
   path fix).

### M7 — `sagemaker_kg_completion_submit_2026_05_17.py`
HyperParameters dict keys flipped from underscore → dash to match the
PyKEEN entrypoint argparse:

| Before | After |
| --- | --- |
| `embedding_dim` | `embedding-dim` |
| `batch_size` | `batch-size` |
| `negative_samples` | `negative-samples` |
| `learning_rate` | `learning-rate` |

SageMaker-meta keys (`sagemaker_program`, `sagemaker_submit_directory`,
`sagemaker_container_log_level`, `sagemaker_region`) keep their
underscore form — the framework consumes those directly and never
forwards them to argparse.

## Re-submit ARNs

### M3 (Processing Job)
- `arn:aws:sagemaker:ap-northeast-1:993693061769:processing-job/jpcite-figure-clip-jp-20260517T084359Z-8e495f`
- Instance: `ml.c5.4xlarge` (g4dn.2xlarge quota = 0 for Processing).
- Status at submit: `InProgress`.

### M7 (Training Jobs — 4 PyKEEN models, parallel)
Each model placed on a distinct `ml.g4dn.*` size to side-step the
per-instance-type quota of 1 (g4dn.12xlarge was already occupied by an
unrelated SimCSE finetune):

- TransE  → `ml.g4dn.2xlarge`  → `jpcite-kg-transe-20260517T084028Z`
- RotatE  → `ml.g4dn.4xlarge`  → `jpcite-kg-rotate-20260517T084028Z`
- ComplEx → `ml.g4dn.8xlarge`  → `jpcite-kg-complex-20260517T084028Z`
- ConvE   → `ml.g4dn.16xlarge` → `jpcite-kg-conve-20260517T084028Z`

ARNs:
- `arn:aws:sagemaker:ap-northeast-1:993693061769:training-job/jpcite-kg-transe-20260517T084028Z`
- `arn:aws:sagemaker:ap-northeast-1:993693061769:training-job/jpcite-kg-rotate-20260517T084028Z`
- `arn:aws:sagemaker:ap-northeast-1:993693061769:training-job/jpcite-kg-complex-20260517T084028Z`
- `arn:aws:sagemaker:ap-northeast-1:993693061769:training-job/jpcite-kg-conve-20260517T084028Z`

## Cost projection

- M3 wall cap 4 h × $0.952/h c5.4xlarge = **$3.81**
- M7 wall cap 24 h × g4dn.{2,4,8,16}xlarge mix ≈ **$120–160 absolute ceiling**
- Total: **<$170 absolute, ~$127 realistic**.
- `$19,490 Never-Reach` cap untouched (MTD 2026-05-17 was $0.00 at
  submit; preflight gate at $18,000 hard-stop).

## Verification post-submit

```
aws sagemaker describe-processing-job --processing-job-name jpcite-figure-clip-jp-20260517T084359Z-8e495f
# CodeS3Uri = …/figure_embeddings_code/jpcite-figure-clip-jp-20260517T084359Z-8e495f/   (per-job, flat embed.py)
# Status = InProgress

aws sagemaker describe-training-job --training-job-name jpcite-kg-transe-20260517T084028Z
# HyperParameters.batch-size = "512"  (dash, argparse-compatible)
# Status = InProgress
```

Both flips confirmed by `aws sagemaker describe-*-job` queries after
submit.
