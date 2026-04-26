#!/usr/bin/env bash
# ------------------------------------------------------------------
# AutonoMath nightly source URL liveness refresh (K5 / launch wave 18).
#
# Drives 80% → 90% alive coverage by re-checking source_url for tier
# S + A rows every night. Wraps `scripts/refresh_sources.py` with the
# polite-crawler defaults already baked in there (per-host rate
# limit, robots.txt respect, redirect logging, 3-strike quarantine).
#
# Why this is just a thin wrapper:
#   refresh_sources.py already handles HEAD → fallback GET, and the
#   programs schema already has source_last_check_status +
#   source_fail_count columns (added at script startup as idempotent
#   ALTER TABLEs — see refresh_sources.py:55-79). Adding a separate
#   `source_url_dead` flag would be redundant: rows with
#   `source_fail_count >= 3` are already auto-quarantined to tier='X'
#   and excluded=1, which the search path already filters out.
#
# Required env: NONE (uses settings.db_path).
# Optional env:
#   AUTONOMATH_DB_PATH    Override DB path (default data/jpintel.db).
#   REFRESH_TIERS         Tier filter (default "S,A").
#   REFRESH_MAX_ROWS      Cap rows per run (default unset = all).
#   REFRESH_REPORT_DIR    Where to write JSON reports (default data/).
#   DRY_RUN=1             Use --dry-run on refresh_sources.py.
#
# Exit codes:
#   0 success
#   1 config error (Python missing, repo layout broken)
#   2 refresh_sources.py reported failures (still runs to completion;
#     2 means "alive coverage below 90% — investigate")
#
# Suggested cadence: daily 03:00 JST (18:00 UTC) on the Fly machine.
# Use `flyctl ssh console` + crontab, or schedule via GitHub Actions
# repo dispatch.
# ------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${REPO_ROOT}/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"

if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "[refresh-cron] ERROR: python3 not found" >&2
  exit 1
fi

REFRESHER="${REPO_ROOT}/scripts/refresh_sources.py"
if [ ! -f "$REFRESHER" ]; then
  echo "[refresh-cron] ERROR: refresh_sources.py missing at ${REFRESHER}" >&2
  exit 1
fi

TIERS="${REFRESH_TIERS:-S,A}"
DRY_RUN="${DRY_RUN:-0}"
DB_PATH="${AUTONOMATH_DB_PATH:-${REPO_ROOT}/data/jpintel.db}"
REPORT_DIR="${REFRESH_REPORT_DIR:-${REPO_ROOT}/data}"
DATESTAMP="$(date -u +%Y-%m-%d)"
REPORT_PATH="${REPORT_DIR}/refresh_sources_${DATESTAMP}.json"

mkdir -p "$REPORT_DIR"

log() { printf '[refresh-cron] %s %s\n' "$(date -u +%FT%TZ)" "$1"; }

ARGS=(--tier "$TIERS" --report "$REPORT_PATH")
[ -n "${REFRESH_MAX_ROWS:-}" ] && ARGS+=(--max-rows "$REFRESH_MAX_ROWS")
[ "$DRY_RUN" = "1" ] && ARGS+=(--dry-run)
[ -n "${AUTONOMATH_DB_PATH:-}" ] && ARGS+=(--db "$DB_PATH")

log "start  tiers=${TIERS}  report=${REPORT_PATH}  dry_run=${DRY_RUN}"
"$PY" "$REFRESHER" "${ARGS[@]}"
RC=$?
log "refresh_sources.py exit=${RC}"

# Post-run: compute aliveness ratio for tiers in scope. If <90%, exit 2
# so the cron host (Fly cron / GHA) surfaces the alert. We do NOT block
# the cron itself — the next pass will retry.
if [ -f "$REPORT_PATH" ]; then
  export REPORT_PATH
  ALIVE_PCT="$("$PY" - <<'PY'
import json, os, sys
p = os.environ.get("REPORT_PATH", "")
try:
    d = json.load(open(p))
except Exception:
    print("0")
    sys.exit(0)
# refresh_sources.py emits a top-level "summary" with status_counts.
# We count any non-2xx as not-alive for this gate.
sc = (d.get("summary") or {}).get("status_counts") or {}
ok = sum(int(v) for k, v in sc.items() if k.startswith("2"))
total = sum(int(v) for v in sc.values()) or 1
print(f"{(ok / total) * 100:.2f}")
PY
)"
  log "alive_pct=${ALIVE_PCT}%"
  AWK_THRESHOLD=90.0
  if ! awk -v p="$ALIVE_PCT" -v t="$AWK_THRESHOLD" 'BEGIN { exit (p+0 < t+0) ? 1 : 0 }'; then
    log "BELOW threshold ${AWK_THRESHOLD}% — operator should review ${REPORT_PATH}"
    exit 2
  fi
fi

log "done"
exit 0
