#!/usr/bin/env bash
# Submit all jpcite-credit crawl jobs (J01..J05 + J07) sequentially with 30s spacing.
# J06 (PDF heavy, EC2 queue) is skipped unless --include-pdf is passed.
#
# Usage:
#   scripts/aws_credit_ops/submit_all.sh [--include-pdf] [--dry-run]
#
# DRY_RUN=true (env or --dry-run) previews each submit without actually submitting.
# Spacing: 30s default, override with SPACING=60 etc.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBMIT="$HERE/submit_job.sh"
SPACING="${SPACING:-30}"
INCLUDE_PDF=false
DRY_RUN="${DRY_RUN:-false}"

for arg in "$@"; do
  case "$arg" in
    --include-pdf) INCLUDE_PDF=true ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) echo "[submit_all] unknown arg: $arg" >&2; exit 64 ;;
  esac
done
export DRY_RUN

JOBS=(J01 J02 J03 J04 J05 J07)
if [ "$INCLUDE_PDF" = "true" ]; then
  JOBS=(J01 J02 J03 J04 J05 J06 J07)
fi

echo "[submit_all] mode: $([ "$DRY_RUN" = "true" ] && echo DRY_RUN || echo LIVE)"
echo "[submit_all] spacing: ${SPACING}s"
echo "[submit_all] sequence: ${JOBS[*]}"
echo ""

LAST_IDX=$((${#JOBS[@]} - 1))
for i in "${!JOBS[@]}"; do
  J="${JOBS[$i]}"
  echo "===== [$((i+1))/${#JOBS[@]}] submitting $J ====="
  if [ "$J" = "J06" ]; then
    "$SUBMIT" "$J" --ec2 || echo "[submit_all] warn: $J submit returned non-zero"
  else
    "$SUBMIT" "$J" || echo "[submit_all] warn: $J submit returned non-zero"
  fi
  if [ "$i" -lt "$LAST_IDX" ]; then
    echo "[submit_all] sleeping ${SPACING}s before next ..."
    sleep "$SPACING"
  fi
done

echo ""
echo "[submit_all] done — submitted ${#JOBS[@]} jobs."
echo "[submit_all] hint: scripts/aws_credit_ops/monitor_jobs.sh"
