# PERF-12: ruff cache + pre-commit hook + auto-format on save

SOT: 2026-05-16 (Wave 51, jpcite repo)

## TL;DR

Develop-loop velocity for the 300+ scripts and 593 src files lint sweep.
Cache is the dominant lever: ruff lands sub-second across the whole tree
once `.ruff_cache` is warm. Pre-commit hook + editor auto-format on save
keep the saved-tree byte-equivalent to what CI will lint, so the inner
loop matches the production gate without surprise re-formats.

## Baseline

Measured on `src/` + `scripts/` + `tests/` this session (M-series mac,
ruff 0.15.11, .venv interpreter):

| state                 | wall   | user  | system |
| --------------------- | ------ | ----- | ------ |
| cold (cache cleared)  | 0.334s | 1.00s | 0.24s  |
| warm 1st call         | 0.116s | 0.03s | 0.08s  |
| warm steady-state     | 0.027s | 0.03s | 0.03s  |

Cold time is dominated by ruff's initial source-tree walk + AST build for
every changed source file; warm time is just dependency-graph metadata
re-read from `.ruff_cache/`. The 12x cold→warm speedup is essentially
"free" — the cache is rebuilt automatically on every run, no opt-in
needed.

## Deliverables

Three artifacts complete PERF-12. The underlying ruff-cache wiring
already landed via PERF-8 (`.github/workflows/test.yml` actions/cache@v4
keyed on `pyproject.toml` hash) and Wave 49 Stream F
(`.pre-commit-config.yaml` ruff / ruff-format / mypy --strict hooks).
What was missing for a fresh clone:

### 1. Makefile targets — one-time install path

```makefile
pre-commit-install:
	.venv/bin/pre-commit install
	@echo "[pre-commit] hook installed at .git/hooks/pre-commit"

pre-commit-run:
	.venv/bin/pre-commit run --all-files
```

`make pre-commit-install` writes `.git/hooks/pre-commit` so every
`git commit` runs the .pre-commit-config.yaml hook chain (ruff --fix /
ruff-format / mypy / bandit / gitleaks / yamllint / distribution drift).
One-time setup per clone.

`make pre-commit-run` is the manual full-tree sweep used by CI parity
checks and whenever a developer wants to lint+format the whole repo
without committing. Ruff hits `.ruff_cache` (warm ~30ms on
`src/scripts/tests`, cold ~330ms after a `.ruff_cache` wipe) so the run
cost is dominated by mypy strict, not ruff.

### 2. `.editorconfig` — cross-editor charset / EOL / indent SOT

Keeps file saves byte-equivalent to `ruff format` output across VS Code,
Vim, JetBrains, etc. Prevents the pre-commit hook from re-rewriting a
freshly-saved file on every commit (a frequent cause of "noisy diff"
PRs).

Key sections:

- `[*]` — utf-8 / lf / trim trailing whitespace / final newline
- `[*.py]` — indent 4, max line 100 (matches ruff format declared in
  `pyproject.toml`)
- `[*.{yml,yaml}]` — indent 2 (matches yamllint config)
- `[*.{json,jsonl}]` — indent 2 (matches OpenAPI / JPCIR schemas)
- `[Makefile]` — real tabs
- `[*.md]` — preserve trailing whitespace (markdown hard line breaks)
- `[*.sjis]` — shift_jis + crlf (legacy JPO files; see CLAUDE.md
  Common gotchas — never converted to UTF-8)

### 3. `.vscode/settings.json` — auto-format on save

Force-added past `.gitignore` (project-wide `.vscode/` ignored rule)
because the auto-format-on-save contract is a shared dev experience, not
per-user preference.

Wires:

- `editor.formatOnSave: true`
- `source.fixAll.ruff: explicit` (Ctrl+S = ruff --fix)
- `source.organizeImports.ruff: explicit` (Ctrl+S = import sort)
- `[python].defaultFormatter: charliermarsh.ruff`
- `ruff.path: [".venv/bin/ruff"]` (project-local ruff, not system)
- `mypy-type-checker.args: ["--strict"]`
- `files.exclude` for `.ruff_cache` / `.mypy_cache` / `__pycache__`

Smoke-tested end-to-end by simulating what VS Code's
`source.fixAll.ruff` + `formatOnSave` would execute on a deliberately
messy file:

```python
# before (saved by editor)
import json,os
def  foo(   x ):
    return    x+1

# after Ctrl+S → ruff --fix + ruff format
def foo(x):
    return x + 1
```

3 ruff diagnostics fixed (unused imports removed, spacing normalized),
1 file reformatted. Exactly matches what `make pre-commit-run` would
emit, so the editor save and the pre-commit hook agree on canonical
form.

## Verification

```bash
$ make pre-commit-install
.venv/bin/pre-commit install
pre-commit installed at .git/hooks/pre-commit
[pre-commit] hook installed at .git/hooks/pre-commit
[pre-commit] run 'make pre-commit-run' to sweep the whole tree

$ ls -la .git/hooks/pre-commit
-rwxr-xr-x  1 shigetoumeda  staff  626  May 16 23:04 .git/hooks/pre-commit

$ time .venv/bin/ruff check src/ scripts/ tests/
Found 4 errors.
[*] 4 fixable with the `--fix` option.
.venv/bin/ruff check src/ scripts/ tests/  0.03s user 0.03s system 198% cpu 0.027 total
```

(The 4 residual errors are TC005 empty-type-checking-block warnings on
`src/jpintel_mcp/api/me.py` — pre-existing PERF-6 lazy-load proxy
artifacts, unrelated to PERF-12 and not in scope under the "no rule
additions/removals" constraint.)

## Constraints honoured

- Ruff rules unchanged — no rule additions, no rule removals, no
  per-file-ignores delta in `pyproject.toml`.
- `.pre-commit-config.yaml` unchanged (already ruff / ruff-format / mypy
  --strict / bandit / gitleaks / yamllint as of Wave 49 Stream F).
- GHA `test.yml` unchanged (PERF-8 already cached `.ruff_cache` via
  `actions/cache@1bd1e32a` keyed on
  `ruff-cache-${{ runner.os }}-${{ hashFiles('pyproject.toml') }}`).
- mypy strict + ruff 0 across PERF-12 surface.
- `[lane:solo]` marker on the commit.

## Layered state of ruff/lint stack across PERF-X streams

| layer            | source                              | landed              |
| ---------------- | ----------------------------------- | ------------------- |
| `.ruff_cache/`   | `.gitignore` (line 4)               | pre-PERF era        |
| local cache hit  | ruff 0.15.11 default behaviour      | pre-PERF era        |
| GHA cache mirror | `.github/workflows/test.yml:947-953` | **PERF-8** |
| pre-commit hooks | `.pre-commit-config.yaml`           | **Wave 49 Stream F** |
| install path     | `Makefile: pre-commit-install`      | **PERF-12** (this)  |
| editor save sync | `.editorconfig` + `.vscode/...`     | **PERF-12** (this)  |

PERF-12 sits on top of PERF-8 + Wave 49 Stream F; it does not modify
either upstream layer.
