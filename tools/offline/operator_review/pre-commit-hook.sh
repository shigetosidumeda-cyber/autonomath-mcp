#!/usr/bin/env bash
# DEEP-60 dual-CLI lane policy pre-commit hook (jpcite).
#
# Install:
#   cp pre-commit-hook.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Configuration (env or .git/config):
#   JPCITE_LANE              = session_a | codex     (required)
#   JPCITE_SESSION           = free-form id (logged in ledger; default 'unspecified')
#   JPCITE_LANE_OVERRIDE     = override reason (>= 24 chars) [optional]
#   JPCITE_LANE_SIGNOFF      = operator name authorising override [optional]
#
# Behaviour:
#   - resolves repo root via `git rev-parse --show-toplevel`
#   - locates lane_policy_enforcer.py at the canonical inbox path
#   - runs --check; non-zero exit aborts the commit
#   - LLM API calls = 0; pure subprocess + python stdlib

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  echo "[lane-hook] not inside a git repository; skipping." >&2
  exit 0
fi

ENFORCER="${REPO_ROOT}/tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/deep60_lane_enforcer/lane_policy_enforcer.py"

if [[ ! -f "${ENFORCER}" ]]; then
  echo "[lane-hook] enforcer not found at ${ENFORCER}; skipping (warn only)." >&2
  exit 0
fi

LANE="${JPCITE_LANE:-}"
if [[ -z "${LANE}" ]]; then
  LANE="$(git config --get jpcite.lane 2>/dev/null || true)"
fi
if [[ -z "${LANE}" ]]; then
  echo "[lane-hook] FAIL: JPCITE_LANE env or 'git config jpcite.lane' is required." >&2
  echo "[lane-hook]   set: export JPCITE_LANE=session_a   (or codex)" >&2
  exit 1
fi

SESSION="${JPCITE_SESSION:-$(git config --get jpcite.session 2>/dev/null || echo unspecified)}"

CMD=(python3 "${ENFORCER}" --check --lane "${LANE}" --session "${SESSION}")

if [[ -n "${JPCITE_LANE_OVERRIDE:-}" ]]; then
  CMD+=(--bypass-with-reason "${JPCITE_LANE_OVERRIDE}")
fi
if [[ -n "${JPCITE_LANE_SIGNOFF:-}" ]]; then
  CMD+=(--operator-signoff "${JPCITE_LANE_SIGNOFF}")
fi

echo "[lane-hook] running: ${CMD[*]}"
if ! "${CMD[@]}"; then
  echo "[lane-hook] commit BLOCKED by lane policy. See messages above." >&2
  echo "[lane-hook] override:" >&2
  echo "  JPCITE_LANE_OVERRIDE='operator override: <>=24 chars reason>' \\" >&2
  echo "  JPCITE_LANE_SIGNOFF=<operator-name> git commit ..." >&2
  exit 1
fi

exit 0
