# Wave 49 tick#1 — mig 288 boot manifest hot-fix

## Context

PR #189 (`feat(wave49/dim-n): k=10 strict view + 7-pattern PII redact`,
merge commit `e59486eb9443e2f3e7e40ce0d913456c5b218158`) landed
`scripts/migrations/288_dim_n_k10_strict.sql` into main but did **not**
update `scripts/migrations/autonomath_boot_manifest.txt`.

`entrypoint.sh` defaults to `AUTONOMATH_BOOT_MIGRATION_MODE=manifest`
and only applies filenames listed in the allowlist. Without the entry,
schema_guard silently skips 288 on every prod boot — the new k=10
strict view `v_anon_cohort_outcomes_k10_strict` is never materialized,
blocking the Dim N Phase 1 hardening from going LIVE.

## Fix

Append-only manifest patch (15 lines added at the tail, 0 lines removed
or re-ordered). Pure additive per `feedback_destruction_free_organization`.

## Diff (manifest)

```diff
@@ -381,3 +381,18 @@
 # additive (CREATE TABLE/INDEX/VIEW IF NOT EXISTS); boot-time safe;
 # idempotent on every boot.
 283_ax_layer3.sql
+
+# 2026-05-12 Wave 49 tick#7 — Dim N Phase 1 k=10 strict parallel view.
+# Adds v_anon_cohort_outcomes_k10_strict on top of the existing
+# am_aggregated_outcome_view (mig 274 substrate, k=5 floor preserved).
+# Destruction-free by construction: the k=5 view v_anon_cohort_outcomes_
+# latest from mig 274 is NEVER dropped, altered, or relaxed; routers
+# opting into stricter privacy read the new k=10 view, legacy callers
+# continue to read the k=5 view unchanged. Pure additive (CREATE VIEW
+# IF NOT EXISTS only; no DROP/DELETE/ALTER on existing objects). NO LLM
+# SDK; pure SQLite. boot-time safe; idempotent on every boot. Without
+# this manifest entry, entrypoint.sh schema_guard ignores 288 even
+# though the SQL file is present (PR #189 merged into main as
+# e59486eb), preventing the strict view from being materialized in
+# prod — this hot-fix unblocks that path.
+288_dim_n_k10_strict.sql
```

## Verification

- Manifest line count: 383 -> 398 (15 insertions, 0 deletions).
- 283 entry untouched (last line of pre-existing block).
- `git diff --stat` reports `1 file changed, 15 insertions(+)`.
- All 3 new tests pass via `.venv/bin/python -m pytest`:
  - `test_mig288_sql_file_exists` — SQL file present on disk.
  - `test_mig288_listed_in_boot_manifest` — manifest lists 288 exactly once.
  - `test_mig274_substrate_preserved` — k=5 substrate retained (destruction-free).

## Bug-free verification (4 axes)

1. **Manifest validity**: only blank line + comment + filename lines, parses identically to existing tail entries.
2. **Existing entries untouched**: `git diff` shows pure tail append; no in-place edit on any of the 30+ pre-existing entries.
3. **Idempotency**: `288_dim_n_k10_strict.sql` uses `CREATE VIEW IF NOT EXISTS` only — safe to apply on every boot.
4. **Destruction-free**: mig 274 (`274_anonymized_query.sql`, k=5 floor) remains in the active allowlist alongside 288; new view is parallel, not replacement.

## Affected files

| Path | Change |
| --- | --- |
| `scripts/migrations/autonomath_boot_manifest.txt` | +15 (append-only) |
| `tests/test_mig288_manifest_present.py` | +71 (new) |
| `docs/research/wave49/STATE_w49_mig288_manifest_hotfix.md` | +this doc (new) |

Total LOC added: ~85.
