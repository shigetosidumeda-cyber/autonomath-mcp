# Wave 46.D — env dual-read bridge + AliasChoices first adopter

**Date:** 2026-05-12
**Branch:** `feat/jpcite_2026_05_12_wave46_rename_46d_env_dual`
**Scope:** non-destructive enablement step on the `AUTONOMATH_* / JPINTEL_* → JPCITE_*` env rename.

## Why this exists

The rename plan (`project_jpcite_internal_autonomath_rename` in user memory) cannot flip 112+ env names atomically — Fly secrets, GHA secrets, and `.env.local` are managed in three separate stores (`feedback_secret_store_separation`). A single-commit cutover would blackout one or two of those stores while the others propagate. W46.D therefore lands the **bridge** that lets every reading site dual-read at zero risk:

1. canonical name (`JPCITE_*`) wins when set;
2. legacy aliases fallback in declaration order;
3. a `DeprecationWarning` fires on legacy reads so operators can grep production logs.

Subsequent waves migrate the remaining 111 envs one-by-one (or in small clusters), each one safe to roll back independently.

## Files

| Path | LOC | Role |
| --- | --- | --- |
| `src/jpintel_mcp/_jpcite_env_bridge.py` | ~135 | New module. `get_flag` / `get_bool` / `get_int` / `get_list` + `DEFAULT_ALIAS_MAP`. |
| `src/jpintel_mcp/config.py` | +14 / -4 | Adopts `AliasChoices("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")` on **one** field (`autonomath_db_path`) as a worked example. Bridge imported for future fields. |
| `tests/test_w46d_env_bridge.py` | ~140 | 12 cases — new-wins, legacy-fallback, deprecation-warning, multiple-alias, empty-string-canonical, bool, int, list, default-map sanity. |
| `docs/research/wave46/STATE_w46_46d_pr.md` | this file | PR ledger. |

## Verification

- `pytest tests/test_w46d_env_bridge.py -v` — see PR for live output.
- `ruff check src/jpintel_mcp/_jpcite_env_bridge.py src/jpintel_mcp/config.py tests/test_w46d_env_bridge.py` — clean.
- Deprecation warning text shape: `env <LEGACY> deprecated, use <CANONICAL>` (asserted in tests).

## Out of scope (deferred)

- The remaining 111 env names. Migrated in subsequent W46.* PRs in small clusters so each one is independently revertible.
- Touching production secrets stores. Bridge is **read-only**; Fly/GHA `.env.local` are managed by the existing inventory-diff workflow.
- Brand text outside of env names (handled in W46.A/B/C views and W46.E docs).
