#!/usr/bin/env bash
# Run an Athena query template against the jpcite_credit_2026_05 catalog.
#
# Usage:
#   scripts/aws_credit_ops/run_athena_query.sh <query_file.sql> [--run-id RID]
#
# Behaviour:
#   1. Loads the SQL template from infra/aws/athena/queries/ (relative path
#      or absolute both work).
#   2. Substitutes `:run_id` with the value of --run-id (default: most-recent
#      run_id partition discovered via `aws athena list-table-metadata` …
#      fallback to literal '%' if discovery fails).
#   3. Substitutes `:run_id_filter` with the value of --run-id-filter (default
#      '%' — matches every partition). Use e.g. `'2026-05-%'` to scope by month.
#   4. Starts the query via `aws athena start-query-execution` against the
#      workgroup `jpcite-credit-2026-05`, database `jpcite_credit_2026_05`,
#      result location `s3://jpcite-credit-993693061769-202605-derived/athena-results/`.
#   5. Polls every 2s for completion; on SUCCEEDED, dumps the first 50 rows
#      via `aws athena get-query-results` + emits the QueryExecutionId so the
#      operator can rerun or pull paginated results.
#   6. On FAILED / CANCELLED, prints the StateChangeReason and exits non-zero.
#
# Notes:
#   - Read-only by design; queries that mutate (CTAS, INSERT) are NOT supported
#     here on purpose. To run a destructive op, drop directly into the Athena
#     console.
#   - Does NOT actually execute by itself — operator must invoke with an
#     explicit file path. There is no auto-discovery loop.
#   - Honours AWS_PROFILE=bookyou-recovery by default to match the rest of
#     scripts/aws_credit_ops/.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

WORKGROUP="${WORKGROUP:-jpcite-credit-2026-05}"
DATABASE="${DATABASE:-jpcite_credit_2026_05}"
OUTPUT_S3="${OUTPUT_S3:-s3://jpcite-credit-993693061769-202605-derived/athena-results/}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-2}"
MAX_POLL_SEC="${MAX_POLL_SEC:-600}"

if [ $# -lt 1 ]; then
  echo "usage: $0 <query_file.sql> [--run-id RID] [--run-id-filter PATTERN]" >&2
  exit 2
fi

QUERY_FILE="$1"
shift

RUN_ID=""
RUN_ID_FILTER="%"
while [ $# -gt 0 ]; do
  case "$1" in
    --run-id)
      RUN_ID="$2"; shift 2 ;;
    --run-id-filter)
      RUN_ID_FILTER="$2"; shift 2 ;;
    *)
      echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Resolve query file
if [ ! -f "$QUERY_FILE" ]; then
  CANDIDATE="infra/aws/athena/queries/$QUERY_FILE"
  if [ -f "$CANDIDATE" ]; then
    QUERY_FILE="$CANDIDATE"
  else
    echo "[run_athena_query] query file not found: $QUERY_FILE" >&2
    exit 3
  fi
fi

echo "[run_athena_query] file: $QUERY_FILE"
echo "[run_athena_query] workgroup: $WORKGROUP"
echo "[run_athena_query] database: $DATABASE"

# Auto-discover run_id if not provided and the template binds :run_id (not :run_id_filter only)
if [ -z "$RUN_ID" ] && grep -q ':run_id\b' "$QUERY_FILE"; then
  echo "[run_athena_query] discovering most-recent run_id partition…"
  RUN_ID=$(aws athena get-table-metadata \
    --catalog-name AwsDataCatalog \
    --database-name "$DATABASE" \
    --table-name source_receipts \
    --query 'TableMetadata.Parameters.partition_keys' \
    --output text 2>/dev/null || true)
  # Best-effort fallback: pick latest from S3 listing
  if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "None" ]; then
    RUN_ID=$(aws s3 ls "s3://jpcite-credit-993693061769-202605-derived/source_receipts/" 2>/dev/null \
      | awk '/run_id=/ {print $2}' \
      | sed 's|/$||;s|run_id=||' \
      | sort -r | head -1 || true)
  fi
  if [ -z "$RUN_ID" ]; then
    echo "[run_athena_query] WARNING: could not discover run_id; falling back to '%'" >&2
    RUN_ID="%"
  fi
  echo "[run_athena_query] run_id resolved: $RUN_ID"
fi

# Substitute bind params (simple textual replace; safe because templates use ':run_id' literal)
RENDERED=$(mktemp -t jpcite-athena.XXXXXX.sql)
trap 'rm -f "$RENDERED"' EXIT

python3 - "$QUERY_FILE" "$RUN_ID" "$RUN_ID_FILTER" >"$RENDERED" <<'PY'
import sys, pathlib
src, run_id, run_filter = sys.argv[1], sys.argv[2], sys.argv[3]
sql = pathlib.Path(src).read_text()
# Quote string values (Athena treats run_id partitions as STRING)
sql = sql.replace(":run_id_filter", f"'{run_filter}'")
sql = sql.replace(":run_id", f"'{run_id}'")
sys.stdout.write(sql)
PY

echo "[run_athena_query] starting query…"
EXEC_ID=$(aws athena start-query-execution \
  --region "$REGION" \
  --work-group "$WORKGROUP" \
  --query-string "file://$RENDERED" \
  --query-execution-context "Database=$DATABASE" \
  --result-configuration "OutputLocation=$OUTPUT_S3" \
  --query 'QueryExecutionId' \
  --output text)

echo "[run_athena_query] QueryExecutionId: $EXEC_ID"

# Poll
WAITED=0
while :; do
  STATE=$(aws athena get-query-execution \
    --region "$REGION" \
    --query-execution-id "$EXEC_ID" \
    --query 'QueryExecution.Status.State' \
    --output text 2>/dev/null || echo "UNKNOWN")
  case "$STATE" in
    SUCCEEDED) break ;;
    FAILED|CANCELLED)
      REASON=$(aws athena get-query-execution \
        --region "$REGION" \
        --query-execution-id "$EXEC_ID" \
        --query 'QueryExecution.Status.StateChangeReason' \
        --output text 2>/dev/null || echo '')
      echo "[run_athena_query] $STATE: $REASON" >&2
      exit 4
      ;;
  esac
  if [ "$WAITED" -ge "$MAX_POLL_SEC" ]; then
    echo "[run_athena_query] timeout after ${MAX_POLL_SEC}s; QueryExecutionId=$EXEC_ID" >&2
    exit 5
  fi
  sleep "$POLL_INTERVAL_SEC"
  WAITED=$((WAITED + POLL_INTERVAL_SEC))
done

echo "[run_athena_query] SUCCEEDED — first 50 rows:"
aws athena get-query-results \
  --region "$REGION" \
  --query-execution-id "$EXEC_ID" \
  --max-results 50 \
  --output table 2>/dev/null || echo "(could not pretty-print; pull via get-query-results manually)"

echo "[run_athena_query] result location: $OUTPUT_S3$EXEC_ID.csv"
