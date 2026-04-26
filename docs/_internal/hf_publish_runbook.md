# HuggingFace Dataset Publish Runbook (Operator Only)

This runbook covers the operator workflow for publishing
`bookyou/autonomath-japan-public-programs` to HuggingFace Hub. Internal-only:
do not link from public docs.

## Status (2026-04-25, T-11d)

**LIVE publish DEFERRED** — credential check failed:

- `HF_TOKEN` env var: **MISSING**
- `~/.cache/huggingface/token` credential file: **MISSING** (only `hub/`
  + `xet/` cache directories exist; no auth token persisted)
- `huggingface-cli` binary: **NOT INSTALLED** in active venv
  (`pip install -e ".[dev]"` not yet run, or huggingface_hub not
  resolved into `.venv/bin/`)

Operator must manually:

1. Create a write-scoped HF token at https://huggingface.co/settings/tokens
2. `export HF_TOKEN=hf_xxx` (or `huggingface-cli login` to persist)
3. Confirm `bookyou` org exists or fall back to operator personal namespace
4. Run the steps in **Publish** below

E8 has staged the artifacts in `dist/hf-dataset/` already (4 parquet,
24,502 rows, 14.1 MB + README + DataCard). No re-export needed unless
data drift detected.

## Prerequisites

- HuggingFace account: https://huggingface.co/bookyou (org or user namespace)
- HF write token: https://huggingface.co/settings/tokens (scope: `write`)
- `huggingface_hub` CLI installed (added to `[dev]` extras in `pyproject.toml`):

  ```bash
  pip install -e ".[dev]"
  ```

- Tested locally with the export script (see § Smoke test below)

## One-time setup

```bash
# 1. Login to HuggingFace (stores token in ~/.cache/huggingface/token)
.venv/bin/huggingface-cli login
# Paste the write token from https://huggingface.co/settings/tokens

# 2. Create the dataset repo (one-time)
.venv/bin/huggingface-cli repo create autonomath-japan-public-programs \
  --type dataset \
  --organization bookyou
```

## Smoke test (no upload)

Always run the export locally first and verify counts before publishing.

```bash
# Regenerate parquet + copy README/DataCard into dist/hf-dataset/
.venv/bin/python scripts/hf_dataset_export.py --output dist/hf-dataset/

# Sanity check row counts
.venv/bin/python -c "
import pandas as pd
for t in ['programs', 'laws', 'case_studies', 'enforcement_cases']:
    df = pd.read_parquet(f'dist/hf-dataset/{t}.parquet')
    print(f'{t:20s} {len(df):>7,} rows')
"
# Expected (as of 2026-04-25):
#   programs              13,578 rows
#   laws                   9,484 rows
#   case_studies           2,286 rows
#   enforcement_cases      1,185 rows
```

## Publish

```bash
# Upload the entire dist/hf-dataset/ directory in one shot
.venv/bin/huggingface-cli upload \
  bookyou/autonomath-japan-public-programs \
  dist/hf-dataset/ \
  . \
  --repo-type dataset \
  --commit-message "Weekly refresh $(date -u +%Y-%m-%d)"
```

Notes:

- The third positional argument (`.`) is the destination path inside the
  repo. Using `.` flattens `dist/hf-dataset/` to the repo root.
- HuggingFace deduplicates by file content hash, so re-uploading
  identical parquet files is a no-op (does not consume bandwidth).
- HF storage quota is generous for datasets but soft-capped — keep a
  rolling 4-week archive locally and trim older versions on the Hub
  if storage approaches the quota.

## Rate limit considerations

- **HF upload rate limit** is roughly 1,000 files/hour per token. Our
  dataset is 6 files (4 parquet + README + DataCard), so we are well
  under the limit.
- **HF download rate limit** is per-IP — not relevant for publishing.
- **Re-publish during outages**: if the upload fails partway through,
  re-running the same `huggingface-cli upload` is idempotent.
- **Token rotation**: rotate the write token quarterly. Old tokens can be
  revoked at https://huggingface.co/settings/tokens without affecting
  published artifacts.

## Update cadence

Weekly via GitHub Actions cron — schedule defined in
`.github/workflows/hf_dataset_publish.yml` (TBD; not yet wired up at the
time of writing). The workflow should:

1. Check out `main`.
2. Run the canonical ingest (refresh primary sources).
3. Run `scripts/hf_dataset_export.py`.
4. Upload to HF using a repository secret `HF_WRITE_TOKEN`.
5. Tag the commit with `hf-publish-YYYY-MM-DD`.

Until the workflow exists, run the publish step manually each Monday.

## Rollback

If a bad publish needs to be reverted:

```bash
# List recent commits on the dataset
.venv/bin/huggingface-cli repo-history \
  bookyou/autonomath-japan-public-programs \
  --repo-type dataset

# Revert to a previous commit (HF supports git-style operations)
git -C ~/cache/huggingface/dataset/bookyou/autonomath-japan-public-programs \
  revert <commit-sha>
```

Or upload a corrected snapshot with a clear commit message — HF retains
the full history, so users on a pinned revision are unaffected.

## Verification post-publish

```bash
# Verify the dataset is loadable from the Hub
.venv/bin/python -c "
from datasets import load_dataset
ds = load_dataset(
    'bookyou/autonomath-japan-public-programs',
    data_files={'programs': 'programs.parquet'},
)
print(ds)
"
```

## What NOT to do

- Do NOT include any file from `data/jpintel.db.bak.*` — these are
  backup snapshots and may contain quarantine-tier rows.
- Do NOT publish the `autonomath.db` companion DB — it is gated behind
  `AUTONOMATH_ENABLED` and includes fact-level enrichment that is not
  yet ready for open redistribution.
- Do NOT include API keys, telemetry data, or anything from
  `usage_events`, `api_keys`, `subscribers` tables.
- Do NOT skip the dataset card update when schema changes — downstream
  users rely on `README.md` for column documentation.
- Do NOT publish during a database migration — wait until the migration
  has fully landed and the row counts have stabilized.
