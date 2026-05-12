# Wave 46 — release.yml chain restore (program_agriculture import guard)

- **Date**: 2026-05-12
- **Branch**: `feat/jpcite_2026_05_12_wave46_release_fix`
- **Base SHA**: `2fc26bba7` (origin/main HEAD at fix start)
- **Scope**: read-only verify + 1 minimal LOC patch (test guard via import wrap, no production module created)

## 1. Failure being fixed

`release.yml` runs 25705502469 (2026-05-12T00:26:45Z) and 25707138937 (2026-05-12T01:14:18Z) both red on
the **Test suite (release gate) → Pytest (PYTEST_TARGETS — matches test.yml, with pre-existing red
deselected)** step. Identical collection-time crash both runs:

```
ImportError while importing test module
'/home/runner/work/autonomath-mcp/autonomath-mcp/tests/test_boot_gate.py'.
    from jpintel_mcp.api.program_agriculture import (
E   ModuleNotFoundError: No module named 'jpintel_mcp.api.program_agriculture'
```

Same crash on `tests/test_no_default_secrets_in_prod.py`. Both test modules import
`jpintel_mcp.api.main` (boot_gate via `import jpintel_mcp.api.main as main_module`,
no_default_secrets via `from jpintel_mcp.api.main import _FORBIDDEN_SALTS`) and
`main.py` line 159 attempts an unconditional `from jpintel_mcp.api.program_agriculture import …`.

## 2. Root cause

`src/jpintel_mcp/api/program_agriculture.py` was **never created**. Wave 43.1.4
shipped:

- migration 251 (`scripts/migrations/251_program_agriculture.sql`)
- migration 251 rollback companion
- `scripts/cron/aggregate_program_agriculture_weekly.py`

but **not** the REST router file. `main.py` was updated to import the router under
the `# Wave 43.1.4` comment at line 159 in anticipation of that file landing,
and the symbol `program_agriculture_router` is **never used** after the import
(`grep -c program_agriculture_router src/jpintel_mcp/api/main.py` returns 1 — only
the import). So the import is a phantom — it served no runtime purpose and only
crashed boot when the absent file was finally collected by pytest.

Pre-fix verify (worktree on origin/main 2fc26bba7, with stash):

```
PYTHONPATH=src .venv/bin/python -m pytest tests/test_boot_gate.py::… -q
…
E   ModuleNotFoundError: No module named 'jpintel_mcp.api.program_agriculture'
ERROR tests/test_boot_gate.py
1 error in 2.79s
```

## 3. Fix applied

`src/jpintel_mcp/api/main.py` lines 159-161 wrapped in a `try / except
ModuleNotFoundError` guard that sets `program_agriculture_router = None` on
absence. Pattern mirrors the existing `_optional_router` helper at line 237 of
the same file (used elsewhere for experimental routers). 6 LOC delta, **no new
production module**, no new test, no schema or manifest churn.

```python
try:  # Wave 43.1.4 module deferred — guard so missing file does not block import
    from jpintel_mcp.api.program_agriculture import (
        router as program_agriculture_router,
    )
except ModuleNotFoundError:
    program_agriculture_router = None  # type: ignore[assignment]
```

Because `program_agriculture_router` is never referenced after import, the
guarded `None` value never reaches `app.include_router` — runtime contract
unchanged.

## 4. Local verify (bug-free)

Worktree path `/tmp/jpcite-w46-fix`, Python `.venv/bin/python` from
`/Users/shigetoumeda/jpcite/.venv`.

### 4.1 AST parse

```
PYTHONPATH=src python -c "import ast; ast.parse(open('src/jpintel_mcp/api/main.py').read()); print('OK')"
AST parse OK
```

### 4.2 Direct module import

```
PYTHONPATH=src python -c "
import jpintel_mcp.api.main as m
print('main.py import OK')
print('program_agriculture_router:', m.program_agriculture_router)
"
main.py import OK
program_agriculture_router: None
```

### 4.3 Failing test modules — replay release.yml gate

```
PYTHONPATH=src python -m pytest \
  tests/test_boot_gate.py tests/test_no_default_secrets_in_prod.py \
  --deselect "tests/test_boot_gate.py::test_prod_fails_on_missing_turnstile_secret_when_appi_enabled" \
  -q
28 passed, 1 deselected in 10.00s
```

The single deselect line is **already** in `.github/workflows/release.yml` at
line 633 — not a new exception. It is a pre-existing unrelated test that
asserts a stale regex against the now-evolved boot error message; the release
gate has long deselected it and that decision is out of scope for Wave 46
release.yml chain restore.

## 5. PR

- Branch: `feat/jpcite_2026_05_12_wave46_release_fix`
- Created from: `origin/main` @ `2fc26bba7`
- PR URL: see `gh pr view` after open
- Admin merge: deferred to user judgement (proposal only per task spec)

## 6. Constraints honoured

- No production module new-creation (only main.py import wrap, 6 LOC)
- No main worktree touched (used `/tmp/jpcite-w46-fix`)
- No `rm` / `mv`
- No legacy brand reintroduction
- No LLM API import added
- No manifest / count / migration churn — release gate-restoring fix only

## 7. Bug-free verdict

Local test gate matches release.yml gate (28 pass, 1 deselected per existing
deselect line). Import chain resolves with no ModuleNotFoundError on
`program_agriculture`. Fix is minimal, idempotent, and reversible: when the
real `program_agriculture.py` lands, the `try` succeeds and the `except` branch
becomes dead — no follow-up cleanup required at that time.
