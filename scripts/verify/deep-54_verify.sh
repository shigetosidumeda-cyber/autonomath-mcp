#!/usr/bin/env bash
# =============================================================================
# scripts/verify/deep-54_verify.sh
# =============================================================================
# Minimal per-spec verify shell for DEEP-54.
#
# Fires the DEEP-54 slice of the acceptance suite
# (tests/test_acceptance_criteria.py) via pytest -k "DEEP-54".
#
# Exit code semantics (consumed by scripts/cron/aggregate_production_gate_status.py):
#   0       = every acceptance row for DEEP-54 passed -> dashboard RESOLVED
#   non-0   = at least one acceptance row failed       -> dashboard BLOCKED
#
# Constraints:
#   - LLM API call count = 0 (acceptance suite is pure static)
#   - Idempotent / non-destructive
# =============================================================================
set -euo pipefail

REPO_ROOT="${JPCITE_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$REPO_ROOT"

PYTEST_BIN="${PYTEST_BIN:-.venv/bin/pytest}"
if [[ ! -x "$PYTEST_BIN" ]]; then
  PYTEST_BIN="python -m pytest"
fi

# -k pattern matches pytest ids like DEEP-54-1-file_existence, DEEP-54-2-..., etc.
exec $PYTEST_BIN tests/test_acceptance_criteria.py \
  -k "DEEP-54-" \
  --no-header -q --tb=line \
  -o cache_dir=/tmp/.pytest_cache_deep_54
