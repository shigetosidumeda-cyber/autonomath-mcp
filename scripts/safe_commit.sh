#!/usr/bin/env bash
# safe_commit.sh — defensive git commit wrapper.
#
# Background
# ----------
# Root-cause diagnostic 2026-05-17 (this script's landing commit) traced a
# recurring "silent commit abort" pattern to pre-commit framework auto-fix
# hooks (ruff --fix / end-of-file-fixer / trim trailing whitespace) modifying
# staged files mid-flight. In that case the framework prints "files were
# modified by this hook" and exits 1, git aborts, but the abort line is easy
# to miss when buffered behind a large batch of Wave-* output. Symptom:
# all hooks marked "Passed", yet no [main XXX] line appears, git log shows
# no new commit, git push reports "Everything up-to-date".
#
# This wrapper:
#  1. Captures the pre-commit HEAD SHA.
#  2. Runs `git commit "$@"` (NO --no-verify, NO --no-gpg-sign).
#  3. Verifies HEAD moved. If not, prints a loud diagnostic summarising:
#       - whether hooks reported file modifications
#       - whether stash patches were left behind under ~/.cache/pre-commit/
#       - the staged + unstaged state at abort time
#       - the exact remediation (re-stage hook auto-fixes, retry).
#  4. Exits non-zero so caller scripts / CI cannot silently treat the
#     no-op as success.
#
# Constraints honoured
# --------------------
# - Never adds `--no-verify` (memory feedback_loop_never_stop / CLAUDE.md
#   "What NOT to do" / repository policy).
# - Never weakens any hook.
# - Hooks continue to run with full strictness.
#
# Usage
# -----
#   scripts/safe_commit.sh -m "subject line [lane:solo]"
# or
#   scripts/safe_commit.sh -m "$(cat <<'EOF'
#   subject
#
#   body
#   EOF
#   )"

set -u
# Note: we intentionally do NOT set -e — we want to inspect git's exit code
# rather than abort on the first failure.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "[safe_commit] FATAL: not inside a git work tree" >&2
    exit 2
fi
cd "$REPO_ROOT" || exit 2

SHA_BEFORE="$(git rev-parse HEAD 2>/dev/null)"
if [ -z "$SHA_BEFORE" ]; then
    echo "[safe_commit] FATAL: cannot resolve HEAD" >&2
    exit 2
fi

PATCH_DIR="${HOME}/.cache/pre-commit"
PATCHES_BEFORE=0
if [ -d "$PATCH_DIR" ]; then
    PATCHES_BEFORE="$(find "$PATCH_DIR" -maxdepth 1 -name 'patch*' -type f 2>/dev/null | wc -l | tr -d ' ')"
fi

# Reject --no-verify defensively even if invoked by mistake.
for arg in "$@"; do
    case "$arg" in
        --no-verify|--no-gpg-sign)
            echo "[safe_commit] FATAL: '$arg' is forbidden by repo policy" >&2
            echo "[safe_commit] fix the hook failure instead of bypassing" >&2
            exit 3
            ;;
    esac
done

# Run the commit. Tee output to a log so the diagnostic can quote the tail
# without depending on terminal scrollback.
LOG="$(mktemp -t safe_commit.XXXXXX)"
trap 'rm -f "$LOG"' EXIT

git commit "$@" 2>&1 | tee "$LOG"
COMMIT_RC=${PIPESTATUS[0]}

SHA_AFTER="$(git rev-parse HEAD 2>/dev/null)"

if [ "$SHA_BEFORE" != "$SHA_AFTER" ]; then
    # Success — HEAD moved.
    if [ "$COMMIT_RC" -ne 0 ]; then
        echo "[safe_commit] WARNING: commit exit code was $COMMIT_RC but HEAD moved" >&2
        echo "[safe_commit] tail of log:" >&2
        tail -20 "$LOG" >&2
    fi
    exit 0
fi

# HEAD did not move — surface diagnostics.
PATCHES_AFTER=0
if [ -d "$PATCH_DIR" ]; then
    PATCHES_AFTER="$(find "$PATCH_DIR" -maxdepth 1 -name 'patch*' -type f 2>/dev/null | wc -l | tr -d ' ')"
fi
PATCHES_DELTA=$((PATCHES_AFTER - PATCHES_BEFORE))

cat >&2 <<EOF

================================================================
[safe_commit] COMMIT ABORTED — HEAD did not advance.
[safe_commit]   exit_code        = $COMMIT_RC
[safe_commit]   sha (before/after) = $SHA_BEFORE
[safe_commit]   stash patches Δ   = $PATCHES_DELTA   (in $PATCH_DIR)
================================================================
EOF

# Heuristic: pre-commit auto-fix modified staged files.
if grep -Eq 'files were modified by this hook|Stashed changes conflicted with hook auto-fixes' "$LOG"; then
    cat >&2 <<'EOF'
[safe_commit] Root cause: a pre-commit hook auto-fixed files mid-run.
[safe_commit] Remediation:
[safe_commit]   1. Inspect the diff:           git diff
[safe_commit]   2. Re-stage the auto-fixes:    git add -u
[safe_commit]   3. Retry the commit:           scripts/safe_commit.sh -m "..."
EOF
elif grep -Eq 'Stashed changes conflicted' "$LOG"; then
    cat >&2 <<EOF
[safe_commit] Root cause: stash-restore conflicted with hook auto-fixes.
[safe_commit] Inspect the latest patch under $PATCH_DIR
[safe_commit] then either apply it manually or re-stage and retry.
EOF
elif [ "$COMMIT_RC" -ne 0 ]; then
    cat >&2 <<'EOF'
[safe_commit] git commit returned non-zero. Tail of log:
EOF
    tail -30 "$LOG" >&2
else
    cat >&2 <<'EOF'
[safe_commit] git commit returned 0 but HEAD did not move.
[safe_commit] Likely causes:
[safe_commit]   - nothing was actually staged (check `git status`)
[safe_commit]   - a commit-msg hook silently rewrote the message to empty
[safe_commit]   - GPG signing prompt was skipped non-interactively
[safe_commit] Tail of log:
EOF
    tail -30 "$LOG" >&2
fi

exit 1
