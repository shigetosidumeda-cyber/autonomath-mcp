# STATE: Wave 46.C — autonomath.db → jpcite.db symlink (entrypoint §1.4)

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave46_rename_46c_symlink`
Worktree: `/tmp/jpcite-w46-rename-46c`
Memory anchors: `project_jpcite_internal_autonomath_rename` /
`feedback_destruction_free_organization` /
`feedback_no_quick_check_on_huge_sqlite` /
`feedback_dual_cli_lane_atomic`

## Scope

Implement axis **46.C** of the plan in
`docs/_internal/W46_autonomath_to_jpcite_rename_plan.md` §3.2 (Symlink
overlay).  Add a compatibility symlink between the legacy
`/data/autonomath.db` and the canonical `/data/jpcite.db` so both env
consumers (`AUTONOMATH_DB_PATH` *and* the future `JPCITE_DB_PATH`) resolve
to the same inode.  Zero destructive op, zero PRAGMA probe, additive only.

## Files touched

| File                                        | Change             | Δ LOC |
|--------------------------------------------|--------------------|-------|
| `entrypoint.sh` §1.4 (new block, before §1.5) | +35 LOC inserted | **+35** |
| `tests/test_w46c_symlink.py`                | new file, 10 cases | +207  |
| `docs/research/wave46/STATE_w46_46c_pr.md`  | this STATE doc     | +80   |
| **Total**                                  |                    | **~322** |

Net LOC delta against `main` HEAD `2658c116`: entrypoint.sh **+35**, test
file **+207**, STATE doc **+80**.

## entrypoint diff (full §1.4 block)

```diff
@@ -25,6 +25,41 @@ if [ ! -d /data ]; then
   exit 1
 fi
 
+# 1.4. jpcite ⇄ autonomath compatibility symlink (Wave 46.C).
+# Brand rename strategy: jpcite.db is the canonical name going forward; old
+# AUTONOMATH_DB_PATH consumers still resolve through the same inode. Per
+# `project_jpcite_internal_autonomath_rename` and
+# `feedback_destruction_free_organization`: never delete or rename the
+# physical autonomath.db, only create the symlink when the new path is
+# absent. Per `feedback_no_quick_check_on_huge_sqlite`: zero PRAGMA /
+# integrity probe here — symlink ops are O(1) inode-only so boot stays well
+# under the 60s Fly grace window. Per `feedback_dual_cli_lane_atomic`:
+# additive overlay (`ln -sf` only when target missing) — safe against
+# concurrent boot.
+JPCITE_DB="${JPCITE_DB_PATH:-/data/jpcite.db}"
+AM_DB="${AUTONOMATH_DB_PATH:-/data/autonomath.db}"
+
+if [ -f "$AM_DB" ] && [ ! -e "$JPCITE_DB" ]; then
+  ln -sf "$AM_DB" "$JPCITE_DB"
+  log "[W46.C] symlink created: $JPCITE_DB -> $AM_DB"
+elif [ -f "$JPCITE_DB" ] && [ ! -e "$AM_DB" ]; then
+  # Inverse case (post-eventual-rename world): jpcite.db is the real file
+  # and autonomath.db is missing. Symlink the legacy path so old code paths
+  # remain transparent. Still no destructive op on either side.
+  ln -sf "$JPCITE_DB" "$AM_DB"
+  log "[W46.C] reverse symlink created: $AM_DB -> $JPCITE_DB"
+elif [ -e "$AM_DB" ] && [ -e "$JPCITE_DB" ]; then
+  # Both exist. If they resolve to the same inode (either is symlink to
+  # the other, or both are bind mounts of the same file), nothing to do.
+  # Otherwise split-brain — log a warning and continue; downstream §2
+  # bootstrap still operates on $DB_PATH (= AUTONOMATH_DB_PATH default).
+  am_inode=$(stat -L -c%i "$AM_DB" 2>/dev/null || stat -L -f%i "$AM_DB" 2>/dev/null || echo "?")
+  jc_inode=$(stat -L -c%i "$JPCITE_DB" 2>/dev/null || stat -L -f%i "$JPCITE_DB" 2>/dev/null || echo "?")
+  if [ "$am_inode" != "$jc_inode" ] || [ "$am_inode" = "?" ]; then
+    err "[W46.C] split-brain: $AM_DB (inode=$am_inode) and $JPCITE_DB (inode=$jc_inode) are distinct files — manual reconcile required; continuing with $AM_DB as canonical"
+  fi
+fi
+
 # Helper: compute SHA256 of a file (portable across Linux + macOS).
```

## Bugs-not-introduced verify

| Gate                                | Command                                              | Result            |
|-------------------------------------|------------------------------------------------------|-------------------|
| bash syntax                          | `bash -n entrypoint.sh`                              | SYNTAX_OK         |
| pytest new file (10 cases)           | `pytest tests/test_w46c_symlink.py`                  | **10/10 PASS**    |
| pytest pre-existing entrypoint suite | `pytest tests/test_entrypoint_vec0_boot_gate.py`     | **14/15 PASS** (1 pre-existing failure on `test_autonomath_boot_manifest_exists_and_is_empty_allowlist_by_default` reproduces on `main` HEAD `2658c116` — unrelated) |
| boot-time budget (Fly grace 60s)     | runtime test wall clock measured                     | **<3s** on macOS runner (block itself ≈ 0.0s — no disk read, only inode ops) |
| destructive op grep                  | `grep -E '(^| )(rm|mv|unlink|DROP|DELETE FROM) ' §1.4` | 0 hits          |
| sqlite probe grep                    | `grep -iE 'PRAGMA|quick_check|integrity_check|sqlite3 ' executable lines of §1.4` | 0 hits |
| forbidden brand                      | "税務会計AI" in §1.4                                  | 0 hits            |
| LLM API import                       | n/a — bash only                                      | 0                 |

Boot-time argument: §1.4 calls `[ -f "$AM_DB" ]`, optionally `ln -sf`, and
optionally `stat -L`.  All three are O(1) inode-level syscalls; the 8.29 GB
file body is never read.  This is structurally incapable of triggering the
9.7 GB `quick_check` 15-minute hang documented in
`feedback_no_quick_check_on_huge_sqlite`.

## Test cases (10)

Static / structural:

1. `test_w46c_block_present_in_entrypoint` — anchor string + env var names
2. `test_w46c_block_uses_ln_sf_only_and_no_destructive_op` — no `rm` / `mv`
   / `unlink` / `DROP` / `DELETE FROM`
3. `test_w46c_block_runs_before_seed_sync_and_r2_bootstrap` — `1.4` < `1.5`
   < `2.` ordering
4. `test_w46c_block_has_no_quick_check_or_integrity_probe` — comments may
   reference the rule, but executable lines hold no `PRAGMA` / `sqlite3`

Runtime (`bash entrypoint.sh true` against tmp_path-rewritten `/data`):

5. `test_w46c_creates_jpcite_symlink_when_autonomath_present_and_jpcite_absent`
6. `test_w46c_creates_reverse_symlink_when_jpcite_present_and_autonomath_absent`
7. `test_w46c_is_noop_when_both_paths_are_same_inode`
8. `test_w46c_logs_split_brain_when_two_distinct_files`
9. `test_w46c_is_noop_when_neither_path_exists`
10. `test_w46c_block_boots_well_under_fly_grace_window` — wall clock <10s

## Out of scope

- Physical `mv /data/autonomath.db /data/jpcite.db` — explicitly forbidden
  (plan §3.2, plan §9).
- `AUTONOMATH_*` → `JPCITE_*` env bridge — that is axis 46.D.
- SQL `am_*` → `jc_*` view overlay — that is axis 46.B.
- R2 backup key migration — Wave 60+, plan §10 OQ4.

## PR target

`main` (admin merge after CI green).  No automatic Fly deploy required
because §1.4 is no-op for the current prod inode topology (autonomath.db
exists, jpcite.db absent → first deploy creates symlink, cost ≈ 0 ms).
