#!/usr/bin/env bash
# Submit N parallel invocations of the jpcite-cf-loadtest Lambda.
#
# Each invocation runs --requests fetches at --concurrency concurrency.
# Defaults: 5 invocations × 10_000 req × 64 concurrency = 50_000 req per submission.
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/cf_loadtest_invoke.sh [N=5]
#
# DRY_RUN default: prints planned invocations + projection without
# calling lambda invoke. Set CF_INVOKE_COMMIT=1 to actually submit.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
REGION="${REGION:-ap-northeast-1}"
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-cf-loadtest}"
N="${1:-5}"
REQUESTS="${JPCITE_CF_REQUESTS:-10000}"
CONCURRENCY="${JPCITE_CF_CONCURRENCY:-64}"
SEED_BASE="${JPCITE_CF_SEED_BASE:-1000}"
COMMIT="${CF_INVOKE_COMMIT:-0}"
OUTDIR="${CF_INVOKE_OUTDIR:-/tmp/cf_loadtest_responses}"

if ! [[ "$N" =~ ^[0-9]+$ ]] || [ "$N" -lt 1 ]; then
  echo "usage: $0 [N=5]" >&2
  exit 2
fi

mkdir -p "$OUTDIR"

echo "[invoke] plan:"
echo "  region          = $REGION"
echo "  function        = $FUNCTION_NAME"
echo "  invocations     = $N"
echo "  requests/inv    = $REQUESTS"
echo "  concurrency/inv = $CONCURRENCY"
echo "  total_requests  = $(( N * REQUESTS ))"
echo "  commit          = $COMMIT"
echo "  out_dir         = $OUTDIR"

if [ "$COMMIT" != "1" ]; then
  echo "[invoke] DRY_RUN — set CF_INVOKE_COMMIT=1 to submit"
  exit 0
fi

for i in $(seq 1 "$N"); do
  SEED=$(( SEED_BASE + i ))
  PAYLOAD=$(printf '{"requests":%d,"concurrency":%d,"seed":%d}' "$REQUESTS" "$CONCURRENCY" "$SEED")
  OUT="$OUTDIR/inv_${i}_seed_${SEED}.json"
  echo "[invoke] $i/$N  seed=$SEED  → $OUT"
  aws lambda invoke \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --invocation-type RequestResponse \
    --payload "$PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    "$OUT" >/dev/null &
done

wait
echo "[invoke] all $N invocations completed — see $OUTDIR/"
ls -la "$OUTDIR"
