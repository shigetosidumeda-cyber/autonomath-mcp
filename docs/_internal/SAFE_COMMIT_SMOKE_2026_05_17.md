# safe_commit.sh smoke test — 2026-05-17

Smoke verification of `scripts/safe_commit.sh` wrapper (landed sha c97be8a22).

## Scenarios

### Scenario A — happy path
- Trivial change committed via wrapper.
- Expected: HEAD moves, exit 0, output reports `HEAD moved`.
- Result: pending (this file is the change).

### Scenario B — --no-verify rejected
- Pass `--no-verify` flag to wrapper.
- Expected: rejected with FATAL message, exit 3, HEAD unchanged.

### Scenario C — pre-commit auto-fix
- Trigger end-of-file-fixer (file lacking trailing newline).
- Expected: either succeeds (auto-fix re-staged) OR surfaces clear diagnostic with remediation steps.
