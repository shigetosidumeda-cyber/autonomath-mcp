# Wave 46 — Task 46.F STATE
## `autonomath_boot_manifest.txt` → `jpcite_boot_manifest.txt` destruction-free alias

| Key | Value |
|---|---|
| Task | 46.F (Wave 46 internal `autonomath → jpcite` rename, tick3#4) |
| Lane | `/tmp/jpcite-w46-rename-46f.lane` (atomic mkdir, single owner) |
| Worktree | `/tmp/jpcite-w46-rename-46f` (detached → `feat/jpcite_2026_05_12_wave46_rename_46f_manifest_alias`) |
| Base SHA | `bfcd2b600` (origin/main HEAD at start) |
| Branch | `feat/jpcite_2026_05_12_wave46_rename_46f_manifest_alias` |
| PR | (filled by `gh pr create`, see §6) |
| Date (JST) | 2026-05-12 |
| Constraint memory | `feedback_destruction_free_organization`, `feedback_dual_cli_lane_atomic`, `feedback_no_quick_check_on_huge_sqlite`, `feedback_no_operator_llm_api` |

---

## 1. Goal

Land a **destruction-free** alias of the boot-time migration manifest under the
new `jpcite` brand while keeping the legacy `autonomath` filename live, so
that:

- `entrypoint.sh` reads either filename without behavioural change.
- A one-sided rollback (revert of either file) never leaves boot without a
  manifest.
- Production self-heal for `schema_guard` keeps working on Wave 45's 8-item
  allowlist.
- Wave 13 size-based-gate root concern, Wave 22/45 schema_guard semantics, and
  the `feedback_no_quick_check_on_huge_sqlite` rule are all preserved (no new
  cold-start work is introduced).

## 2. Files changed

| File | LOC delta | Purpose |
|---|---|---|
| `scripts/migrations/jpcite_boot_manifest.txt` | **+126 / -0** (new) | Byte-identical copy of `autonomath_boot_manifest.txt` (sha256 `ce069d23…924076`). Tracked in git; both files must move in lock-step. |
| `entrypoint.sh` | **+20 / -1** (§2 boot self-heal block) | Replaces the single `am_mig_manifest=` default with an env-override + dual-candidate loop. Preference order: `AUTONOMATH_BOOT_MIGRATION_MANIFEST` env → `jpcite_boot_manifest.txt` → `autonomath_boot_manifest.txt`. |
| `tests/test_w46f_manifest_alias.py` | **+133 / -0** (new) | 6 regression tests: presence × 2, byte-identity, payload non-empty, `entrypoint.sh` dual-read block, env-override ordering, `bash -n` syntax. |
| `scripts/migrations/README.md` | **+10 / -0** | Documents the alias rule, drift-cron pointer, and the "edit both files in the same commit" obligation. |
| `docs/research/wave46/STATE_w46_46f_pr.md` | **+150 / -0** (new — this file) | STATE snapshot. |

Total: 4 changed + 2 new = **+439 / -1**.

## 3. entrypoint.sh §2 diff (full)

```diff
@@ entrypoint.sh §2 (autonomath boot self-heal)
       am_mig_mode="${AUTONOMATH_BOOT_MIGRATION_MODE:-manifest}"
-      am_mig_manifest="${AUTONOMATH_BOOT_MIGRATION_MANIFEST:-/app/scripts/migrations/autonomath_boot_manifest.txt}"
+      # Wave 46 46.F: jpcite_boot_manifest.txt aliases autonomath_boot_manifest.txt.
+      # Dual-read: prefer explicit env override, else prefer the jpcite-named copy,
+      # fall back to the legacy autonomath-named copy. Both files are tracked in
+      # git and MUST be kept byte-identical (see scripts/migrations/README.md).
+      if [ -n "${AUTONOMATH_BOOT_MIGRATION_MANIFEST:-}" ]; then
+        am_mig_manifest="$AUTONOMATH_BOOT_MIGRATION_MANIFEST"
+      else
+        am_mig_manifest=""
+        for am_mig_manifest_candidate in \
+          /app/scripts/migrations/jpcite_boot_manifest.txt \
+          /app/scripts/migrations/autonomath_boot_manifest.txt; do
+          if [ -f "$am_mig_manifest_candidate" ]; then
+            am_mig_manifest="$am_mig_manifest_candidate"
+            break
+          fi
+        done
+        # Keep the variable defined even if neither file is on disk so the
+        # existing "$am_mig_manifest missing" log path stays intact.
+        : "${am_mig_manifest:=/app/scripts/migrations/jpcite_boot_manifest.txt}"
+      fi
       am_mig_in_manifest() {
```

Net LOC delta on `entrypoint.sh`: **+20 / -1** (one-line default → 20-line
override-then-loop block). The downstream code in §2 (`am_mig_in_manifest`,
`case "$am_mig_mode" in manifest|discover|off`, the `am_mig_id` loop) is
unchanged.

## 4. Manifest diff verdict

```
$ sha256sum scripts/migrations/{jpcite,autonomath}_boot_manifest.txt
ce069d2352935136ee2fbe64dabbc571596d121e8cf84922e99fa7d975924076  scripts/migrations/jpcite_boot_manifest.txt
ce069d2352935136ee2fbe64dabbc571596d121e8cf84922e99fa7d975924076  scripts/migrations/autonomath_boot_manifest.txt

$ diff scripts/migrations/jpcite_boot_manifest.txt scripts/migrations/autonomath_boot_manifest.txt
(no output — files are byte-identical)

$ wc -l scripts/migrations/{jpcite,autonomath}_boot_manifest.txt
     126 scripts/migrations/jpcite_boot_manifest.txt
     126 scripts/migrations/autonomath_boot_manifest.txt
```

**Verdict: IDENTICAL.** Both files carry the same Wave 40 (5 entries) + Wave 45
(3 entries) + comment header. The pair MUST be updated together; the
`scripts/migrations/README.md` Wave 46 paragraph and the
`test_manifests_are_byte_identical` unit test enforce this.

## 5. Test result

```
$ uv run --python 3.12 --with pytest python -m pytest tests/test_w46f_manifest_alias.py -v
============================= test session starts ==============================
collecting ... collected 6 items

tests/test_w46f_manifest_alias.py::test_both_manifests_exist                  PASSED [ 16%]
tests/test_w46f_manifest_alias.py::test_manifests_are_byte_identical          PASSED [ 33%]
tests/test_w46f_manifest_alias.py::test_manifest_payload_nonempty             PASSED [ 50%]
tests/test_w46f_manifest_alias.py::test_entrypoint_dual_read_block_present    PASSED [ 66%]
tests/test_w46f_manifest_alias.py::test_entrypoint_env_override_still_respected PASSED [ 83%]
tests/test_w46f_manifest_alias.py::test_entrypoint_bash_syntax_ok             PASSED [100%]
========================= 6 passed, 1 warning in 1.26s =========================
```

`bash -n entrypoint.sh` — clean (return code 0).

## 6. Future-update rule

Manifest updates MUST touch **both** files in the same commit. Enforcement:

1. `tests/test_w46f_manifest_alias.py::test_manifests_are_byte_identical` — PR
   gate (fails CI on drift).
2. `scripts/migrations/README.md` — explicit "Rule: any manifest edit MUST be
   applied to BOTH files in the same commit" paragraph.
3. A scheduled drift check (`scripts/cron/check_alias_drift.py`) is planned for
   46.G/46.H — out of scope for this PR.

## 7. Forbidden / not done

- **No deletion** of `autonomath_boot_manifest.txt` (per
  `feedback_destruction_free_organization`).
- **No `mv`** — both files exist independently and are git-tracked.
- **No main-worktree mutation** — work is in `/tmp/jpcite-w46-rename-46f`.
- **No legacy-brand promotion** — the `autonomath_*` filename is documented
  only as the fallback alias for an in-flight rename.
- **No LLM API import** — test file uses only stdlib + `pytest`.
- **No `quick_check` on `autonomath.db`** — this patch does not touch the
  size-gated SQLite section of `entrypoint.sh §2`.

## 8. PR

PR URL: **(filled by `gh pr create` step below)**

```
Title: feat(wave46/46.F): alias autonomath_boot_manifest -> jpcite_boot_manifest (dual-read)
Body  : see §1-§7 above + ACK Wave 46 destruction-free rename plan.
```
