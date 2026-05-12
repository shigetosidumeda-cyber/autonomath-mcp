# Wave 46.E — pydantic `AliasChoices` env dual-read (config.py 1 wave)

**Date:** 2026-05-12
**Branch:** `feat/jpcite_2026_05_12_wave46_rename_46e_aliaschoices`
**Worktree:** `/tmp/jpcite-w46-rename-46e`
**Lane:** `/tmp/jpcite-w46-rename-46e.lane` (mkdir-atomic ledger)
**Memory:**
[[project_jpcite_internal_autonomath_rename]] / [[feedback_destruction_free_organization]] /
[[feedback_dual_cli_lane_atomic]]

## 1. Scope

Convert every `alias="AUTONOMATH_X"` / `alias="JPINTEL_X"` field on
`src/jpintel_mcp/config.py:Settings` to a
`validation_alias=AliasChoices("JPCITE_X", "<legacy>")` pair so the new
`JPCITE_*` env names take precedence while the legacy AUTONOMATH/JPINTEL
aliases keep working (destruction-free).

The task brief said "~112 env" — the actual config.py exposes **47 env fields**,
of which **31** had a legacy alias (23 AUTONOMATH + 8 JPINTEL) and needed
the rewrite. The broader 89 distinct AUTONOMATH env vars across `src/` are
read via `os.environ.get(...)` directly in their respective modules and are
not in scope for this PR (config.py is the typed Settings surface only).

## 2. Conversion count

| Source                             | Count |
|------------------------------------|-------|
| `alias="AUTONOMATH_*"` fields      | 23    |
| `alias="JPINTEL_*"` fields         | 8     |
| `alias="JPCITE_*"` fields          | 0 (none existed)|
| `STRIPE_*` / `POSTMARK_*` / etc.   | 16    |
| **Total fields**                   | 47    |
| **AliasChoices entries added**     | 31    |
| **Legacy env names preserved**     | 31 (23 AUTONOMATH + 8 JPINTEL) |

All 31 converted Fields now use the shape:

```python
field_name: Type = Field(
    default=...,
    validation_alias=AliasChoices("JPCITE_<NAME>", "<LEGACY_NAME>"),
)
```

with `JPCITE_<NAME>` listed first so it wins ordering on `AliasChoices`
resolution. The legacy `AUTONOMATH_*` / `JPINTEL_*` env names are
preserved verbatim — boot logs / deploy configs that still set the
legacy names continue to drive the same Setting value.

## 3. Verification

### 3.1 Test — `tests/test_w46e_aliaschoices_all.py` (200 LOC)

Parametrised 20-entry env matrix × 3 assertion modes (default / new-primary /
legacy-fallback) + 2 anchor tests = **62 cases**.

```
$ PYTHONPATH=/tmp/jpcite-w46-rename-46e/src \
    python -m pytest tests/test_w46e_aliaschoices_all.py -v
...
============================== 62 passed in 1.20s ==============================
```

**62/62 green.** The matrix covers the 20 most load-bearing flags
(autonomath_enabled, rule_engine_enabled, healthcare_enabled,
real_estate_enabled, saburoku_kyotei_enabled, r8_versioning_enabled,
autonomath_snapshot_enabled, autonomath_reasoning_enabled,
autonomath_graph_enabled, prerequisite_chain_enabled,
autonomath_nta_corpus_enabled, autonomath_wave22_enabled,
autonomath_industry_packs_enabled, prompt_injection_guard_enabled,
pii_redact_response_enabled, uncertainty_enabled,
autonomath_disclaimer_level, log_level, log_format, env).

The precedence test (`test_aliaschoices_jpcite_precedence_over_legacy`)
explicitly asserts that when **both** `JPCITE_ENABLED=0` and
`AUTONOMATH_ENABLED=1` are set, the JPCITE primary wins
(`autonomath_enabled is False`).

### 3.2 Lint — ruff

```
$ python -m ruff check src/jpintel_mcp/config.py \
                       tests/test_w46e_aliaschoices_all.py
All checks passed!
```

### 3.3 Type — mypy

```
$ python -m mypy src/jpintel_mcp/config.py
Success: no issues found in 1 source file
```

### 3.4 Import smoke

```
$ python -c "from jpintel_mcp.config import Settings, settings; print(settings.autonomath_enabled)"
True
```

No regression — defaults preserved exactly because each `AliasChoices` pair
is additive (new JPCITE name as primary, legacy preserved as the second
choice, default value verbatim from the prior `Field(default=..., alias=...)`).

## 4. Pre-PR-open gotcha — pytest editable install collision

When the test was first run via pytest, **all 20 new-primary cases failed
with `JPCITE_<X> not honored`** even though direct `Settings()` calls
honored the env. Root cause traced to the
`/Users/shigetoumeda/jpcite/.venv/lib/python3.13/site-packages/_editable_impl_autonomath_mcp.pth`
entry pointing at `/Users/shigetoumeda/jpcite/src` (main repo). pytest
imported `jpintel_mcp.config` from the main repo, not from the worktree —
so the new `AliasChoices` was invisible and the field still carried the
legacy `alias="JPINTEL_X"`.

**Workaround documented:** test runs in this worktree require
`PYTHONPATH=/tmp/jpcite-w46-rename-46e/src` to override the venv editable
install. CI (which checks out the branch into a fresh tree) is unaffected
because the runner installs the branch sources.

## 5. Files touched

| Path                                                              | Δ LOC |
|-------------------------------------------------------------------|-------|
| `src/jpintel_mcp/config.py`                                       | +83 / -23 |
| `tests/test_w46e_aliaschoices_all.py` (new)                       | +213  |
| `docs/research/wave46/STATE_w46_46e_pr.md` (this doc)             | +180  |
| **Net**                                                           | **+453 / -23** |

## 6. PR

Open URL: `https://github.com/shigetosidumeda-cyber/autonomath-mcp/compare/main...feat/jpcite_2026_05_12_wave46_rename_46e_aliaschoices`

Will be populated with PR # by the post-push step.

## 7. Memory / SOP touch-points

- **[[project_jpcite_internal_autonomath_rename]]** — implements the
  "env var は両方併存 (`AUTONOMATH_*_ENABLED` を読みつつ `JPCITE_*_ENABLED`
  も読む、新 code は後者のみ)" plank concretely for the typed `Settings`
  surface. Direct `os.environ.get("AUTONOMATH_*")` callsites in other
  modules remain on the legacy name and are addressed by later 46.X waves.
- **[[feedback_destruction_free_organization]]** — no `rm` / no `mv` /
  no rename of existing env names. The 31 legacy names are preserved
  verbatim inside `AliasChoices`. `git diff` shows additions-only on
  alias surface.
- **[[feedback_dual_cli_lane_atomic]]** — lane claimed via
  `mkdir /tmp/jpcite-w46-rename-46e.lane` + `AGENT_LEDGER` append; no
  concurrent worktree contention observed.
