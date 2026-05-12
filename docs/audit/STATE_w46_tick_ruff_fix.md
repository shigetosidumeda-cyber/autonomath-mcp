# Wave 46 tick#2 — release.yml ruff format drift fix

**Date**: 2026-05-12
**Branch**: feat/jpcite_2026_05_12_wave46_ruff_format_fix
**Base**: main @ 0e81c51e (PR #151 merged)

## Trigger

release.yml run **25716927227** = FAILED at `ruff format --check` step. 2 files exceed line length / wrapping convention introduced by recent merges (PR #141 deprecation-flag refactor wrapped `get_flag(...)` into 3-arg fallback form, but did not re-format wrappers).

## Files reformatted (2)

| file | LOC delta | nature |
| --- | --- | --- |
| `scripts/etl/generate_program_rss_feeds.py` | +3 / -1 | `DEFAULT_AUTONOMATH_DB = Path(...)` long line split onto 3 lines |
| `scripts/ops/status_probe.py` | +3 / -1 | `autonomath_db = Path(...).resolve()` long line split onto 3 lines |

**Total**: 2 file / +6 / -2 / **net +4 LOC**.

## Verify

```
ruff format --check  → "2 files already formatted"   PASS
ruff check           → "All checks passed!"          PASS
pytest tests/test_program_rss_feeds.py -v            5/5 PASS (1.51s)
git diff             format-only, 0 logic change     OK
```

## Constraint compliance

- Logic 変更 0 (Path(...) constructor arg 不変、長行のみ wrap)
- 大規模 refactor 無し (2 file, 2 行 wrap のみ)
- main worktree 不使用 (`/tmp/jpcite-w46-ruff-fix` 専用)
- rm/mv 無し、`feedback_destruction_free_organization` 遵守
- 旧 brand 無し
- LLM API 呼び出し無し

## Next

1. commit + push + PR open
2. PR CI = ruff format + ruff check + pytest 緑化 (期待)
3. admin merge → release.yml retry → PyPI/Anthropic publish chain 復旧

## Lane claim

`/tmp/jpcite-w46-ruff-fix.lane/` (mkdir atomic), AGENT_LEDGER append separately.

**Location note**: `docs/research/` is gitignored; STATE doc placed under `docs/audit/` alongside `STATE_w46_release_fix.md` (only tracked STATE convention).
