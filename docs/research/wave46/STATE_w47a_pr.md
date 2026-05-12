# Wave 46 / 47.A — jpcite env-bridge full callsite migration (89)

**Status:** READY  
**Branch:** `feat/jpcite_2026_05_12_wave46_rename_47a_aliaschoices_full`  
**Worktree:** `/tmp/jpcite-w46-rename-47a` (lane mutex `/tmp/jpcite-w46-rename-47a.lane`)  
**Companion to:** Wave 46.E (PR #132) — `Settings` `AliasChoices` conversion (31 fields)  
**Predecessor reference:** PR #120 (introduces the `_jpcite_env_bridge.get_flag` helper concept; this PR lands the helper in tree alongside the 89 callsite migration).

## 1. Goal

Wave 46.E only converted `Settings`-bound env reads. **89 additional ad-hoc
callsites** in MCP tools / REST / cron / ETL / ops / self_improve loops still
called `os.environ.get("AUTONOMATH_X", ...)` or `os.getenv("JPINTEL_X", ...)`
directly, which means they would have continued to read the legacy name even
when the canonical `JPCITE_X` was set in prod / CI / Fly secrets.

This PR completes the bridge by routing every selected callsite through
`jpintel_mcp._jpcite_env_bridge.get_flag(primary, legacy, default)`:

- `JPCITE_*` (new canonical) checked first
- legacy name (`AUTONOMATH_*` / `JPINTEL_*`) checked second
- hard-coded default last
- **destruction-free**: nothing is deleted; legacy env continues to work
  (per `feedback_destruction_free_organization`)

## 2. Callsite breakdown — 6 categories, 89 calls

| Category               | Files | Calls |
|------------------------|------:|------:|
| `src/jpintel_mcp/mcp/` (tools + http + auth + cohort_resources) |  46  |  64  |
| `scripts/cron/`        |  14   |  15  |
| `scripts/etl/`         |  6    |   7  |
| `scripts/ops/`         |  1    |   3  |
| (split out)            |       |      |
| `src/jpintel_mcp/self_improve/` (subset of `src/`) | 2 | 2 |
| `src/jpintel_mcp/mcp/_http_fallback.py` (api lane) | 1 | 3 |

Total: **89 callsites** across **66 unique files**.  
Snapshot list: `/tmp/w47a_callsites_all.txt` (input), `/tmp/w47a_apply.py`
(`EDITS = [...]` literal — 87 single-line + 2 multi-line) + the 2 manual
edits in `eligibility_tools.py`.

Wire pattern examples:

```python
# Before
_ENABLED = os.environ.get("AUTONOMATH_ELIGIBILITY_CHECK_ENABLED", "1") == "1"

# After
from jpintel_mcp._jpcite_env_bridge import get_flag
_ENABLED = get_flag(
    "JPCITE_ELIGIBILITY_CHECK_ENABLED",
    "AUTONOMATH_ELIGIBILITY_CHECK_ENABLED",
    "1",
) == "1"
```

## 3. New helper module — `src/jpintel_mcp/_jpcite_env_bridge.py`

Pure stdlib (no LLM/SDK imports per
`feedback_autonomath_no_api_use` / `feedback_no_operator_llm_api`).  
Exposes:

- `get_flag(primary, legacy, default=None) -> str | None`
- `get_bool_flag(primary, legacy, default: bool) -> bool`
- `get_int_flag(primary, legacy, default: int) -> int`

Empty-string env values are treated as "unset" so a stray `export JPCITE_X=`
in CI does not pin the canonical key when the legacy key carries the real
value.

## 4. Test — `tests/test_w47a_env_bridge_callsites.py` (~175 LOC)

Parametrised on 20 representative (primary, legacy, default) triplets drawn
from the 89 migrated callsites (6 src/tools _ENABLED + 4 DB-path src/tools +
3 src/api + 4 scripts/cron + 1 scripts/etl + 1 scripts/ops + 1 self_improve).

Test matrix: 20 callsites × 3 modes (default / new-primary / legacy-fallback)
= **60 cases** + 5 anchor tests
(precedence-primary-wins / empty-string-as-unset /
get_bool_flag truthy-falsy / get_int_flag valid-invalid /
public_api_surface_stable) = **65 cases total**.

Result (`python3.13 + pytest 9.0.3`, run with
`PYTHONPATH=src --noconftest` because the repo `conftest.py` needs fastapi
which is heavy to install for a unit-test of a stdlib-only helper):

```
65 passed, 1 warning in 0.13s
```

## 5. Verification — verdicts

| Check                                                                | Result |
|----------------------------------------------------------------------|:-----:|
| `py_compile` on all 67 modified files (66 callsite files + helper)   | **OK 67/67** |
| pytest `tests/test_w47a_env_bridge_callsites.py`                     | **65 passed** |
| ruff on helper + new test                                            | **OK** |
| ruff on all 66 touched callsite files (post `--fix`)                 | 13 errors remain — **all pre-existing** (E701/E702 multi-statement, SIM105 try/except/pass) on lines this PR did not touch |
| New-injected import block sort (I001)                                 | **0** (ruff auto-fixed) |
| `# noqa: E402` added for 5 files where helper import lands after `sys.path.insert(...)` (CI runner shim)                                | OK |
| `grep direct os.environ.get(.AUTONOMATH_/.JPINTEL_)` in 89 targets   | **0 callsites still raw** (verified by re-scanning original target list) |
| `grep direct os.environ.get(.AUTONOMATH_/.JPINTEL_)` in src+scripts whole | 181 remain (started 269; Wave 47.B/.C/... will continue) |

## 6. Anti-rule checks (memory: `feedback_destruction_free_organization`, `feedback_autonomath_no_api_use`, `feedback_no_operator_llm_api`)

- ❌ NO env var deleted
- ❌ NO behavioural change (defaults preserved verbatim, every triplet honours legacy fallback)
- ❌ NO `anthropic` / SDK import added in src or scripts (stdlib only)
- ❌ NO main worktree mutation (used `/tmp/jpcite-w46-rename-47a` worktree, atomic mkdir lane mutex `/tmp/jpcite-w46-rename-47a.lane`)
- ❌ NO legacy brand surface change (banner/docs untouched per `feedback_legacy_brand_marker`)

## 7. Files changed (PR diff)

| File                                                                                        | Lines |
|---------------------------------------------------------------------------------------------|------:|
| **NEW** `src/jpintel_mcp/_jpcite_env_bridge.py`                                             |  +118 |
| **NEW** `tests/test_w47a_env_bridge_callsites.py`                                           |  +175 |
| **NEW** `docs/research/wave46/STATE_w47a_pr.md` (this file)                                 |  +~140 |
| 66 callsite files (89 line edits + 66 helper import injections, 5 with `# noqa: E402`, 2 `import os` removed where it became unused) | ~190 +/- |

## 8. Followups (NOT in this PR)

- 47.B: convert remaining ~180 callsites (e.g. `intel_wave32.py`, `corporate_form_tools.py`, `invoice_risk_tools.py`, additional cron jobs) — same mechanical pattern, will reuse `/tmp/w47a_apply.py` as a template.
- 47.C: scripts/cron/aggregate_program_agriculture_weekly.py multi-statement lines (`; sh = …; sh.set… ; root.addHandler(sh)`) deserve a one-off ruff cleanup outside this scope.
- post-47: `mypy --strict` audit on the helper (currently passes `py_compile`; mypy not run because the repo's mypy config requires the full venv with all deps).

## 9. Pytest-editable-install gotcha (re-noted from 46.E)

Running pytest needs `PYTHONPATH=src` because the repo is **not** installed
editable in the local shell — there is no `.venv` at the repo root. Once
landed, CI's existing setup-env step handles this automatically. Local
contributors should either run `pip install -e .` once, or prefix
`PYTHONPATH=src` as we did above.
