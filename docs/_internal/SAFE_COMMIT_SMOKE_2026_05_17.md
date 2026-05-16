# safe_commit.sh smoke test — 2026-05-17

Smoke verification of `scripts/safe_commit.sh` wrapper (landed sha `c97be8a22`).
Conducted by /goal loop safe_commit validation lane on 2026-05-17.

## Wrapper contract (from script header)

1. Capture pre-commit HEAD SHA.
2. Run `git commit "$@"` with NO `--no-verify` / NO `--no-gpg-sign` (rejected defensively).
3. Verify HEAD moved. If not, print loud diagnostic identifying root cause.
4. Exit non-zero on no-op so caller scripts / CI cannot silently treat as success.

## Scenarios

### Scenario A — happy path (successful commit)

- Action: created this file, `git add`, ran wrapper with `-m "docs(smoke): safe_commit.sh validation [lane:solo]"`.
- Pre-HEAD: `7993ec36a1f6eac97a939221229edea76567d8c7`
- Post-HEAD: `cae13cf87a9db98a15c59eff9b53d872273a4b07`
- Exit code: `0`
- Pre-commit output: all hooks Passed/Skipped, `[main cae13cf87]` line emitted.
- Verdict: **PASS** — HEAD advanced, wrapper exited 0 cleanly.

Note: Wrapper does NOT print an explicit `HEAD moved: <old> → <new>` line on the
happy path — it only emits diagnostics on the no-op branch. This matches the
script contract (silent success, loud failure) and is correct behavior.

### Scenario B — `--no-verify` rejected

- Action: ran `bash scripts/safe_commit.sh --no-verify -m "should be rejected [lane:solo]"`.
- Pre-HEAD: `cae13cf87a9db98a15c59eff9b53d872273a4b07`
- Post-HEAD: `cae13cf87a9db98a15c59eff9b53d872273a4b07` (unchanged)
- Exit code: `3`
- Output: `[safe_commit] FATAL: '--no-verify' is forbidden by repo policy` + `fix the hook failure instead of bypassing`.
- Verdict: **PASS** — wrapper short-circuited before invoking `git commit`, HEAD unchanged.

Additional verify: `--no-gpg-sign` (the script's other forbidden flag) was also
tested positionally (`-m "msg" --no-gpg-sign`) and rejected identically (exit 3).
The reject loop iterates `$@` and matches by case, so flag position does not matter.

### Scenario C — pre-commit auto-fix collision

- Action: wrote file with trailing whitespace AND missing EOF newline to trigger
  `end-of-file-fixer` + `trailing-whitespace` hooks; staged + ran wrapper.
- Pre-HEAD: `cae13cf87a9db98a15c59eff9b53d872273a4b07`
- Post-HEAD: `cae13cf87a9db98a15c59eff9b53d872273a4b07` (unchanged on first attempt)
- Exit code: `1`
- Hook output: both `fix end of files` and `trim trailing whitespace` reported
  `Failed` / `files were modified by this hook` / `Fixing docs/_internal/SAFE_COMMIT_AUTOFIX_TEST.md`.
- Wrapper diagnostic surfaced correctly:
  ```
  ================================================================
  [safe_commit] COMMIT ABORTED — HEAD did not advance.
  [safe_commit]   exit_code        = 1
  [safe_commit]   sha (before/after) = cae13cf87...
  [safe_commit]   stash patches Δ   = 0
  ================================================================
  [safe_commit] Root cause: a pre-commit hook auto-fixed files mid-run.
  [safe_commit] Remediation:
  [safe_commit]   1. Inspect the diff:           git diff
  [safe_commit]   2. Re-stage the auto-fixes:    git add -u
  [safe_commit]   3. Retry the commit:           scripts/safe_commit.sh -m "..."
  ```
- Remediation cycle: `git add -u` + retry → HEAD moved to `23a77fec5...`, exit 0.
- Verdict: **PASS** — wrapper correctly detected the no-op, identified the root
  cause via log grep, and emitted the documented 3-step remediation.

## Summary

| Scenario | Expected behavior | Actual | Verdict |
|---|---|---|---|
| A: happy path | HEAD moves, exit 0 | HEAD `7993ec36a` → `cae13cf87`, exit 0 | PASS |
| B: `--no-verify` reject | FATAL message, exit non-zero, HEAD unchanged | exit 3, HEAD unchanged | PASS |
| C: pre-commit auto-fix | HEAD unchanged on first try, clear diagnostic with remediation | exit 1, full diagnostic + 3-step remediation, retry succeeds | PASS |

## Bugs found

None. The wrapper behaves exactly per its documented contract on all three scenarios.

## Notes / observations

- `--no-gpg-sign` (the script's other forbidden flag) is also rejected; tested
  positionally to confirm the `for arg in "$@"` loop matches regardless of
  argument order.
- Log tee'd to mktemp and grep'd for the `files were modified by this hook` /
  `Stashed changes conflicted` heuristics; the heuristic branch fired correctly
  on scenario C.
- `PATCHES_DELTA` was `0` on scenario C (no stash patches landed under
  `~/.cache/pre-commit/`). This is because pre-commit only saves a patch when
  the stash-restore step fails; in this case the hooks simply re-wrote files
  in-place without stashing. The wrapper still classified the failure correctly
  via the log-grep heuristic.
- Cumulative commits landed during smoke: `cae13cf87` (scenario A) and
  `23a77fec5` (scenario C remediation). Final commit will follow.
