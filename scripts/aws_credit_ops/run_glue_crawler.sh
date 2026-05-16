#!/usr/bin/env bash
# Start the jpcite-credit-derived-crawler and poll until the crawl finishes.
#
# Usage:
#   scripts/aws_credit_ops/run_glue_crawler.sh
#   scripts/aws_credit_ops/run_glue_crawler.sh --status-only   # do not start, just poll/print
#   scripts/aws_credit_ops/run_glue_crawler.sh --crawler NAME  # override (default jpcite-credit-derived-crawler)
#
# Behaviour:
#   1. Resolves CRAWLER name (default `jpcite-credit-derived-crawler`).
#   2. Unless --status-only, calls `aws glue start-crawler`. If the crawler is
#      already running (CrawlerRunningException), continues straight to polling.
#   3. Polls `aws glue get-crawler` every POLL_INTERVAL_SEC (default 6s) for up
#      to MAX_POLL_SEC (default 900s = 15 min). State machine:
#        State = STARTING | RUNNING | STOPPING | READY
#      Exits the poll loop when State = READY.
#   4. On READY, prints the LastCrawl status block (Status / StartTime /
#      MessagePrefix / LogGroup / LogStream) so the operator can pull the
#      CloudWatch log for the run.
#   5. Exit code:
#        0 — crawl finished and LastCrawl.Status = SUCCEEDED
#        1 — crawl finished but LastCrawl.Status != SUCCEEDED (FAILED/CANCELLED)
#        2 — usage error
#        3 — poll loop exceeded MAX_POLL_SEC
#
# Read-only outside of the start-crawler trigger. Does not create or modify
# the crawler config itself — for that, edit
# `infra/aws/glue/jpcite_credit_derived_crawler.json` and re-apply with
# `aws glue update-crawler --cli-input-json file://...`.
#
# Honours AWS_PROFILE=bookyou-recovery by default to match the rest of
# scripts/aws_credit_ops/.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

CRAWLER="${CRAWLER:-jpcite-credit-derived-crawler}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-6}"
MAX_POLL_SEC="${MAX_POLL_SEC:-900}"
STATUS_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --status-only)
      STATUS_ONLY=1
      shift
      ;;
    --crawler)
      CRAWLER="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      echo "usage: $0 [--status-only] [--crawler NAME]" >&2
      exit 2
      ;;
  esac
done

echo "[run_glue_crawler] profile=$AWS_PROFILE region=$REGION crawler=$CRAWLER"

if [ "$STATUS_ONLY" -eq 0 ]; then
  echo "[run_glue_crawler] starting crawler..."
  if ! aws glue start-crawler --name "$CRAWLER" 2>/tmp/run_glue_crawler.err; then
    if grep -q 'CrawlerRunningException' /tmp/run_glue_crawler.err; then
      echo "[run_glue_crawler] crawler already running; switching to poll-only"
    else
      cat /tmp/run_glue_crawler.err >&2
      exit 1
    fi
  fi
fi

elapsed=0
while [ "$elapsed" -lt "$MAX_POLL_SEC" ]; do
  STATE=$(aws glue get-crawler --name "$CRAWLER" --query 'Crawler.State' --output text 2>&1 || true)
  echo "[run_glue_crawler] t+${elapsed}s state=$STATE"
  if [ "$STATE" = "READY" ]; then
    break
  fi
  sleep "$POLL_INTERVAL_SEC"
  elapsed=$((elapsed + POLL_INTERVAL_SEC))
done

if [ "$STATE" != "READY" ]; then
  echo "[run_glue_crawler] timeout after ${MAX_POLL_SEC}s (state=$STATE)" >&2
  exit 3
fi

echo "[run_glue_crawler] crawl finished — last run:"
aws glue get-crawler \
  --name "$CRAWLER" \
  --query 'Crawler.LastCrawl.{Status:Status, StartTime:StartTime, MessagePrefix:MessagePrefix, LogGroup:LogGroup, LogStream:LogStream}' \
  --output json

LAST_STATUS=$(aws glue get-crawler --name "$CRAWLER" --query 'Crawler.LastCrawl.Status' --output text)
if [ "$LAST_STATUS" = "SUCCEEDED" ]; then
  echo "[run_glue_crawler] OK"
  exit 0
fi
echo "[run_glue_crawler] last crawl status=$LAST_STATUS (not SUCCEEDED)" >&2
exit 1
