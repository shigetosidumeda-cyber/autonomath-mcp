# Pre-commit stash conflict — root cause + defensive wrapper

**Filed**: 2026-05-17 by jpcite goal-loop diagnostic lane (paired with
`SESSION_2026_05_17_AM_DIRECT_BASH_PROGRESS.md` §"Pre-commit framework
stash conflict").
**Reporter symptoms**:
- All pre-commit hooks marked **Passed** (ruff / ruff-format / mypy /
  bandit / gitleaks / distribution-manifest-drift)
- The expected `[main XXX] subject` line never appears in stdout
- `git log` shows no new commit
- `git push` returns `Everything up-to-date`

## Root cause (verified)

The pre-commit framework runs `pre_commit.staged_files_only._unstaged_changes_cleared`
(`/Users/shigetoumeda/jpcite/.venv/lib/python3.12/site-packages/pre_commit/staged_files_only.py`).
When the working tree has BOTH staged AND unstaged changes on tracked
files, the framework:

1. Saves the unstaged diff to `~/.cache/pre-commit/patchTIMESTAMP-PID`.
2. Runs `git -c submodule.recurse=0 checkout -- .` to wipe unstaged
   changes from the index.
3. Runs the configured hooks against the staged content.
4. In `finally`, runs `git apply patchTIMESTAMP-PID` to restore the
   stash.

There are **two failure modes**:

### Mode A — auto-fix hook modified a staged file (most common in jpcite)

Hooks like `ruff --fix` (`.pre-commit-config.yaml` rev `v0.15.11`) or
`end-of-file-fixer` / `trim trailing whitespace` (`pre-commit-hooks`
`v5.0.0`) re-write the staged content. The framework then re-stages the
auto-fix and emits a "files were modified by this hook" line, exiting
non-zero. Git aborts the commit. Visible output:

```
ruff (legacy alias)......................................Passed
... 14 more lines saying "Passed"
[INFO] Restored changes from /Users/shigetoumeda/.cache/pre-commit/patchN-M.
```

The crucial abort line is easy to miss when:
- A Wave-* batch generator is also flooding the same TTY
- stdout/stderr are merged in pipes
- The terminal scrollback is shallower than the hook output

### Mode B — stash-restore patch conflict (rare; logged loudly)

If the auto-fix touched the SAME lines as the user's unstaged diff,
`git apply` of the stash patch fails. The framework logs:

```
[WARNING] Stashed changes conflicted with hook auto-fixes... Rolling back fixes...
```

It then does a hard checkout + retries `git apply`. In practice this
recovery succeeds, but the rollback erases the hook auto-fixes
silently — the next commit attempt will hit Mode A again.

### Evidence collected 2026-05-17 (this diagnostic lane)

- pre-commit framework version: **4.6.0** (venv 3.12). System
  `pre-commit` not installed.
- Hook config: `/Users/shigetoumeda/jpcite/.pre-commit-config.yaml`
  pins ruff `v0.15.11`, mypy `v1.20.0`, bandit `1.7.9`,
  pre-commit-hooks `v5.0.0`, yamllint `v1.35.1`, gitleaks `v8.21.2`.
- `git config core.hookspath` empty (no override) — the standard
  `.git/hooks/pre-commit` shim invokes `.venv/bin/python -mpre_commit
  hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit`.
- Leftover patches under `~/.cache/pre-commit/`: 147+ files dated
  2026-05-16 23:04 → present, confirming repeated stash cycles during
  the rate-limit window concurrent batch.

The stash patches are intentionally kept by pre-commit as forensic
breadcrumbs (`Restored changes from ...` log line points the operator
at the recovery file). They are NOT a leak.

## Defensive guard: `scripts/safe_commit.sh`

The wrapper:

1. Records `HEAD` before invoking `git commit "$@"`.
2. Forwards every argument (including `-m`, multi-line HEREDOC, etc.)
   to `git commit` unchanged.
3. **Rejects** `--no-verify` / `--no-gpg-sign` — they violate
   `CLAUDE.md "What NOT to do"` and `feedback_loop_never_stop`.
4. Tees the combined stdout+stderr to a temp log so it can quote the
   tail in the diagnostic without depending on terminal scrollback.
5. Verifies `HEAD` advanced.
6. If `HEAD` did not move, surfaces a loud diagnostic block including:
   - the pre-commit exit code
   - before/after SHA
   - delta in stash-patch count (Δ ≥ 1 indicates a real pre-commit
     run; Δ = 0 means git aborted before hooks ran, e.g. empty
     commit, message-only failure)
   - a heuristic root-cause hint (`files were modified by this hook`
     / `Stashed changes conflicted` / generic non-zero exit)
   - the remediation steps verbatim.
7. Exits non-zero so loop callers cannot silently treat the no-op as
   success.

## Usage

```bash
# Single-line message
scripts/safe_commit.sh -m "subject line [lane:solo]"

# Multi-line with HEREDOC (preserves formatting)
scripts/safe_commit.sh -m "$(cat <<'EOF'
subject line

body line 1
body line 2

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

Hooks continue to run with full strictness; no `--no-verify` or
`--no-gpg-sign` is ever introduced.

## What this fix does NOT change

- The pre-commit configuration (`.pre-commit-config.yaml`) is
  untouched.
- No hooks are weakened, skipped, or reordered.
- The git `.git/hooks/pre-commit` shim is untouched (it remains the
  standard pre-commit framework template).
- Leftover patch files under `~/.cache/pre-commit/` are NOT auto-cleaned
  by the wrapper — they remain as forensic recovery artifacts. Operators
  may run `find ~/.cache/pre-commit -name 'patch*' -mtime +7 -delete`
  manually to prune ones older than a week.

## Operator action remaining

When `safe_commit.sh` reports Mode A:

```
git diff                         # see what the auto-fix changed
git add -u                       # re-stage the auto-fix
scripts/safe_commit.sh -m "..."  # retry; this time hooks find nothing to fix
```

When pre-commit reports Mode B (`Stashed changes conflicted`), the
stash patch under `~/.cache/pre-commit/patchN-M` contains the user's
unstaged diff. Apply it manually with `git apply ~/.cache/pre-commit/patchN-M`
after the auto-fixes have been committed.

last_updated: 2026-05-17
