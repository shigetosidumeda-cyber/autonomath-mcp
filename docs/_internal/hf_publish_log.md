# HuggingFace Dataset Publish Log

Append-only log of HF dataset publish events for
`bookyou/autonomath-japan-public-programs`. New entries at the top.

---

## 2026-04-25 17:36 JST — DEFERRED (T-11d, credential missing)

**Status**: Skipped LIVE publish. Artifacts ready in `dist/hf-dataset/`.

### Pre-flight checks (subagent F9)

| Check                                          | Result                          |
|------------------------------------------------|---------------------------------|
| `HF_TOKEN` env var                             | MISSING                         |
| `~/.cache/huggingface/token` credential file   | MISSING (only `hub/` + `xet/`)  |
| `huggingface-cli` binary in PATH               | NOT FOUND                       |
| `huggingface-cli whoami`                       | not runnable (cli missing)      |
| `dist/hf-dataset/` artifacts (E8 staged)       | OK — 6 files, 14.1 MB total     |

### Staged artifacts (verified on disk, not yet uploaded)

| File                       | Size       | Source       |
|----------------------------|-----------:|--------------|
| `programs.parquet`         | 10,767,897 | jpintel.db   |
| `laws.parquet`             |  1,952,311 | jpintel.db   |
| `case_studies.parquet`     |  1,884,531 | jpintel.db   |
| `enforcement_cases.parquet`|    133,761 | jpintel.db   |
| `README.md`                |     15,469 | E8 generated |
| `DataCard.md`              |      7,385 | E8 generated |

Expected row counts (from runbook): programs 13,578 / laws 9,484 /
case_studies 2,286 / enforcement_cases 1,185. **Not pandas-verified
this run** — token-gated; will be re-verified post-upload via
`huggingface-cli download` smoke per runbook § Verification.

### Repo target (planned)

- Repo ID: `bookyou/autonomath-japan-public-programs`
- Repo type: `dataset`
- Visibility: `public` (private=False)
- License: CC-BY 4.0 + 政府標準利用規約 v2.0 (declared in DataCard YAML
  frontmatter — operator must confirm card metadata is preserved on
  first upload)
- Initial commit message: `"Initial dataset publish (T-11d, 2026-04-25)"`

### Resumption

When operator returns:

```bash
# Install missing CLI into venv
pip install -e ".[dev]"

# Authenticate (interactive)
.venv/bin/huggingface-cli login   # paste write token

# Or set env for non-interactive:
export HF_TOKEN=hf_xxx

# Publish per runbook § Publish
.venv/bin/huggingface-cli upload \
  bookyou/autonomath-japan-public-programs \
  dist/hf-dataset/ . --repo-type dataset \
  --commit-message "Initial dataset publish (T-11d, 2026-04-25)"

# Smoke verify
huggingface-cli download bookyou/autonomath-japan-public-programs \
  --repo-type dataset --include "programs.parquet" \
  --local-dir /tmp/hf_smoke/
.venv/bin/python -c "import pandas as pd; \
  print(len(pd.read_parquet('/tmp/hf_smoke/programs.parquet')))"
# Expected: 13578
```

After successful publish, append a new entry above this one with:

- timestamp (JST)
- repo URL (https://huggingface.co/datasets/bookyou/autonomath-japan-public-programs)
- commit SHA (from `huggingface-cli upload` stdout)
- pandas read_parquet smoke result (row count == 13,578)
- total uploaded size

### Risk note

T-11d to launch (2026-05-06). HF dataset publish is **not** on the
launch-blocker critical path (per
`feedback_completion_gate_minimal.md`) — REST API + MCP registry +
PyPI are. HF publish can slip to T-7d or T-3d without affecting
launch readiness. Do not gate launch on this entry.

---
