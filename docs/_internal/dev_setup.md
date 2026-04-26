# Dev Setup

Minimal checklist for new maintainers. Covers local env + the pre-commit
hook chain that guards every commit.

## 1. Python env

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

CI runs on 3.11 / 3.12 / 3.13 (see `.github/workflows/test.yml`). Local dev
should use 3.13 to match production (Fly image).

## 2. Pre-commit hooks

Install once per clone:

```bash
pip install pre-commit
pre-commit install
```

This wires `.git/hooks/pre-commit` to run Ruff, gitleaks, yamllint, and the
stock hygiene hooks on every `git commit`. Configuration lives in
`.pre-commit-config.yaml`.

### Run every hook across the whole tree

Useful before opening a PR, or after pulling large changes:

```bash
pre-commit run --all-files
```

### Run a single hook

```bash
pre-commit run ruff --all-files
pre-commit run gitleaks --all-files
```

### Run the manual-stage hooks (mypy)

`mypy` is marked `stages: [manual]` so it does not slow down every commit.
Run it explicitly before pushing:

```bash
pre-commit run mypy --all-files --hook-stage manual
```

### Skip hooks (emergency only)

```bash
git commit --no-verify -m "..."
```

Do **not** use this routinely. The hooks catch leaked secrets, broken YAML,
and lint drift — skipping them means they surface as a CI red later, or
worse, as a secret pushed to a public repo that then has to be rotated.
If a hook is wrong, fix the hook config, not the commit.

### Update hook versions

Periodically (~monthly) bump pinned revs:

```bash
pre-commit autoupdate
pre-commit run --all-files  # verify the bumps didn't regress anything
git add .pre-commit-config.yaml && git commit -m "chore: bump pre-commit hooks"
```

Keep the Ruff version in `.pre-commit-config.yaml` >= the floor declared in
`pyproject.toml`'s `[dev]` extras; otherwise CI ruff and local ruff can
disagree.

## 3. What each hook guards

| Hook | What it catches |
|------|-----------------|
| `ruff` (lint + format) | Python style drift, unused imports, formatting |
| `gitleaks` | Leaked API keys, tokens, webhook secrets in staged diff |
| `yamllint` | Malformed GitHub Actions workflows, indentation errors |
| `check-yaml` / `check-json` / `check-toml` | Syntax errors in config files |
| `check-added-large-files` | Commits >500 KB (data dumps, lockfiles, blobs) |
| `end-of-file-fixer` / `trailing-whitespace` | Small hygiene fixes |
| `mypy` (manual) | Type regressions in `src/jpintel_mcp/` |

## 4. Allowlisted fixtures

`.gitleaks.toml` exempts a small set of paths where placeholder secrets are
**expected** to live (`.env.example`, `tests/fixtures/`,
`sdk/*/tests/fixtures/`, OpenAPI sample responses). Keep that list tight —
when in doubt, add a per-line `# gitleaks:allow` comment instead of a new
path entry.

## 5. Troubleshooting

- **Hook install fails with SSL error**: pre-commit clones each hook repo
  into `~/.cache/pre-commit/`. Corporate MITM proxies sometimes break this;
  set `GIT_SSL_NO_VERIFY=1` only as a last resort.
- **Ruff version drift**: if local Ruff fires differently than CI, check
  `pre-commit-config.yaml` rev vs the version installed in `.venv` via
  `pip show ruff`. Align them.
- **Gitleaks false positive**: prefer `# gitleaks:allow` on the offending
  line. Only widen `.gitleaks.toml` allowlist for whole directories of
  known fixtures.
