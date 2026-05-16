#!/usr/bin/env bash
# Run a "big" Athena cross-source / cross-join query under the
# jpcite-credit-2026-05 workgroup with the 100 GB BytesScannedCutoffPerQuery
# cap. Reports bytes scanned + estimated cost + execution latency so the
# operator can decide whether to ramp scan footprint or pin LIMIT clauses.
#
# Usage:
#   scripts/aws_credit_ops/run_big_athena_query.sh <query_file.sql> [--run-id-filter PAT]
#                                                  [--budget-cap-usd N]
#                                                  [--dry-run]
#
# Behaviour:
#   1. Resolves <query_file.sql> from infra/aws/athena/big_queries/ (relative
#      or absolute both work).
#   2. Substitutes :run_id_filter with --run-id-filter (default '%').
#   3. Starts the query via aws athena start-query-execution against
#      workgroup jpcite-credit-2026-05, database jpcite_credit_2026_05,
#      result location s3://jpcite-credit-993693061769-202605-derived/athena-results/.
#   4. Polls every 5s for completion (max 30 min — big queries can take that
#      long when scanning 100 GB).
#   5. On SUCCEEDED: pulls bytes scanned + execution time + data manifest
#      from get-query-execution.Statistics, computes estimated cost at the
#      US-East Athena rate of $5.00 per TB scanned (note: ap-northeast-1
#      also bills $5.00/TB at standard tier).
#   6. If estimated cost exceeds --budget-cap-usd (default $50), prints a
#      WARNING line — does NOT cancel mid-flight because the query already
#      ran. Operator can manually re-run with tighter LIMIT.
#   7. On FAILED / CANCELLED: prints StateChangeReason and exits non-zero.
#
# Notes:
#   - Read-only by design (start-query-execution doesn't have a mutation
#     mode here). DDL on this workgroup is intentionally NOT supported.
#   - --dry-run still calls start-query-execution because Athena lacks a
#     "preview cost" API — the cheapest preview is a real query with a
#     LIMIT 0 wrapper, which this script does not auto-inject. Use the
#     EXPLAIN PLAN <sql> Athena console feature for true preview.
#   - Honours AWS_PROFILE=bookyou-recovery by default for parity with the
#     rest of scripts/aws_credit_ops/.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

WORKGROUP="${WORKGROUP:-jpcite-credit-2026-05}"
DATABASE="${DATABASE:-jpcite_credit_2026_05}"
OUTPUT_S3="${OUTPUT_S3:-s3://jpcite-credit-993693061769-202605-derived/athena-results/}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-5}"
MAX_POLL_SEC="${MAX_POLL_SEC:-1800}"
ATHENA_USD_PER_TB="${ATHENA_USD_PER_TB:-5.00}"

if [ $# -lt 1 ]; then
  echo "usage: $0 <query_file.sql> [--run-id-filter PAT] [--budget-cap-usd N] [--dry-run]" >&2
  exit 2
fi

QUERY_FILE="$1"
shift

RUN_ID_FILTER="%"
BUDGET_CAP_USD="50"
DRY_RUN="0"

while [ $# -gt 0 ]; do
  case "$1" in
    --run-id-filter)
      RUN_ID_FILTER="$2"; shift 2 ;;
    --budget-cap-usd)
      BUDGET_CAP_USD="$2"; shift 2 ;;
    --dry-run)
      DRY_RUN="1"; shift ;;
    *)
      echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Resolve query file
if [ ! -f "$QUERY_FILE" ]; then
  CANDIDATE="infra/aws/athena/big_queries/$QUERY_FILE"
  if [ -f "$CANDIDATE" ]; then
    QUERY_FILE="$CANDIDATE"
  else
    echo "[run_big_athena_query] query file not found: $QUERY_FILE" >&2
    exit 3
  fi
fi

echo "[run_big_athena_query] file:        $QUERY_FILE"
echo "[run_big_athena_query] workgroup:   $WORKGROUP"
echo "[run_big_athena_query] database:    $DATABASE"
echo "[run_big_athena_query] filter:      $RUN_ID_FILTER"
echo "[run_big_athena_query] budget cap:  \$${BUDGET_CAP_USD}"
echo "[run_big_athena_query] rate:        \$${ATHENA_USD_PER_TB}/TB"

# Substitute bind params
RENDERED=$(mktemp -t jpcite-bigq.XXXXXX.sql)
trap 'rm -f "$RENDERED"' EXIT

python3 - "$QUERY_FILE" "$RUN_ID_FILTER" >"$RENDERED" <<'PY'
import sys, pathlib
src, run_filter = sys.argv[1], sys.argv[2]
sql = pathlib.Path(src).read_text()
sql = sql.replace(":run_id_filter", f"'{run_filter}'")
sql = sql.replace(":run_id", f"'{run_filter}'")
sys.stdout.write(sql)
PY

if [ "$DRY_RUN" = "1" ]; then
  echo "[run_big_athena_query] DRY_RUN — rendered SQL:"
  cat "$RENDERED"
  exit 0
fi

echo "[run_big_athena_query] starting query…"
START_TS=$(date +%s)
EXEC_ID=$(aws athena start-query-execution \
  --region "$REGION" \
  --work-group "$WORKGROUP" \
  --query-string "file://$RENDERED" \
  --query-execution-context "Database=$DATABASE" \
  --result-configuration "OutputLocation=$OUTPUT_S3" \
  --query 'QueryExecutionId' \
  --output text)

echo "[run_big_athena_query] QueryExecutionId: $EXEC_ID"

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
      echo "[run_big_athena_query] $STATE: $REASON" >&2
      exit 4
      ;;
  esac
  if [ "$WAITED" -ge "$MAX_POLL_SEC" ]; then
    echo "[run_big_athena_query] timeout after ${MAX_POLL_SEC}s; QueryExecutionId=$EXEC_ID" >&2
    exit 5
  fi
  sleep "$POLL_INTERVAL_SEC"
  WAITED=$((WAITED + POLL_INTERVAL_SEC))
done

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

# Pull statistics
STATS=$(aws athena get-query-execution \
  --region "$REGION" \
  --query-execution-id "$EXEC_ID" \
  --query 'QueryExecution.Statistics' \
  --output json)

BYTES_SCANNED=$(echo "$STATS" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("DataScannedInBytes", 0))')
ENGINE_MS=$(echo "$STATS"   | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("EngineExecutionTimeInMillis", 0))')
TOTAL_MS=$(echo "$STATS"    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("TotalExecutionTimeInMillis", 0))')

# Estimate cost: bytes / (1 TB) * rate, rounded to 4 dp
EST_COST=$(python3 -c "print(f'{(${BYTES_SCANNED} / (1024**4)) * ${ATHENA_USD_PER_TB}:.4f}')")
BYTES_MB=$(python3 -c "print(f'{${BYTES_SCANNED} / (1024**2):.2f}')")
BYTES_GB=$(python3 -c "print(f'{${BYTES_SCANNED} / (1024**3):.4f}')")

echo ""
echo "[run_big_athena_query] === RESULT ==="
echo "  state:           SUCCEEDED"
echo "  exec_id:         $EXEC_ID"
echo "  elapsed (wall):  ${ELAPSED}s"
echo "  engine ms:       ${ENGINE_MS}"
echo "  total ms:        ${TOTAL_MS}"
echo "  bytes scanned:   ${BYTES_SCANNED} (${BYTES_MB} MiB / ${BYTES_GB} GiB)"
echo "  estimated cost:  \$${EST_COST} USD (at \$${ATHENA_USD_PER_TB}/TB)"
echo "  result S3:       ${OUTPUT_S3}${EXEC_ID}.csv"

# Budget warning
OVER_BUDGET=$(python3 -c "print('1' if ${EST_COST} > ${BUDGET_CAP_USD} else '0')")
if [ "$OVER_BUDGET" = "1" ]; then
  echo ""
  echo "[run_big_athena_query] WARNING: estimated cost \$${EST_COST} > budget cap \$${BUDGET_CAP_USD}"
  echo "[run_big_athena_query] Operator can re-run with tighter LIMIT or pinned --run-id-filter."
fi

# First 20 rows
echo ""
echo "[run_big_athena_query] First 20 rows:"
aws athena get-query-results \
  --region "$REGION" \
  --query-execution-id "$EXEC_ID" \
  --max-results 20 \
  --output table 2>/dev/null || echo "(could not pretty-print; pull via get-query-results manually)"
