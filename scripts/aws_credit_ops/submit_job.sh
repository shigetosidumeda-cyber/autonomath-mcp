#!/usr/bin/env bash
# Submit a single jpcite-credit crawl job to AWS Batch.
#
# Usage:
#   scripts/aws_credit_ops/submit_job.sh <job_id> [--ec2]
#
#   <job_id>   e.g. J01, J02, ..., J07
#   --ec2      route to jpcite-credit-ec2-spot-cpu-queue (J06 PDF heavy default)
#
# Reads the manifest URI from s3://jpcite-credit-993693061769-202605-reports/manifests/<job_id>_*.json
# (resolves to a single match; bails if 0 or 2+ matches).
#
# Submits Batch job (definition jpcite-crawl) with env vars:
#   JOB_MANIFEST_S3_URI  full s3:// URI of the manifest
#   OUTPUT_S3_BUCKET     jpcite-credit-993693061769-202605-raw
#   REPORTS_S3_BUCKET    jpcite-credit-993693061769-202605-reports
#   AWS_DEFAULT_REGION   ap-northeast-1
#
# Tags every job with Project=jpcite, CreditRun=2026-05, Workload=<job_id>, AutoStop=2026-05-29.
#
# Idempotent by name pattern: job name = jpcite-<lower(job_id)>-<utc_yyyymmddHHMMSS>.
# Re-submitting the same <job_id> produces a fresh timestamped name; AWS Batch dedupes nothing,
# so the caller is responsible for not double-submitting unless that is the intent.
#
# DRY_RUN=true previews the submission without calling submit-job.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"
DRY_RUN="${DRY_RUN:-false}"

REPORTS_BUCKET="${REPORTS_BUCKET:-jpcite-credit-993693061769-202605-reports}"
RAW_BUCKET="${RAW_BUCKET:-jpcite-credit-993693061769-202605-raw}"
MANIFEST_PREFIX="${MANIFEST_PREFIX:-manifests/}"
JOB_DEF="${JOB_DEF:-jpcite-crawl}"
FARGATE_QUEUE="${FARGATE_QUEUE:-jpcite-credit-fargate-spot-short-queue}"
EC2_QUEUE="${EC2_QUEUE:-jpcite-credit-ec2-spot-cpu-queue}"
LOG_GROUP="${LOG_GROUP:-/aws/batch/jpcite-credit-2026-05}"
AUTO_STOP="${AUTO_STOP:-2026-05-29}"

usage() {
  cat <<USAGE
usage: $0 <job_id> [--ec2]
  job_id: J01 | J02 | J03 | J04 | J05 | J06 | J07
  --ec2:  route to $EC2_QUEUE instead of $FARGATE_QUEUE (J06 PDF heavy default)
env:
  DRY_RUN=true   preview only
  AWS_PROFILE    default: bookyou-recovery
  REGION         default: ap-northeast-1
USAGE
  exit 64
}

if [ "$#" -lt 1 ]; then
  usage
fi

# Handle -h/--help before job_id pattern validation
case "${1:-}" in
  -h|--help) usage ;;
esac

JOB_ID="$1"
shift
USE_EC2=false
for arg in "$@"; do
  case "$arg" in
    --ec2) USE_EC2=true ;;
    -h|--help) usage ;;
    *) echo "[submit_job] unknown arg: $arg" >&2; usage ;;
  esac
done

# Validate job_id pattern
if ! [[ "$JOB_ID" =~ ^J0[1-7]$ ]]; then
  echo "[submit_job] invalid job_id: $JOB_ID (expected J01..J07)" >&2
  exit 64
fi

# J06 defaults to EC2 queue (PDF heavy) unless caller explicitly says fargate
if [ "$JOB_ID" = "J06" ] && [ "$USE_EC2" = "false" ]; then
  echo "[submit_job] note: J06 is PDF heavy — defaulting to EC2 queue. Override with FARGATE_QUEUE only if intentional." >&2
  USE_EC2=true
fi

if [ "$USE_EC2" = "true" ]; then
  QUEUE="$EC2_QUEUE"
else
  QUEUE="$FARGATE_QUEUE"
fi

# Resolve manifest URI from S3 prefix
echo "[submit_job] locating manifest for $JOB_ID under s3://$REPORTS_BUCKET/$MANIFEST_PREFIX ..."
MANIFEST_KEYS=$(aws s3api list-objects-v2 \
  --region "$REGION" \
  --bucket "$REPORTS_BUCKET" \
  --prefix "$MANIFEST_PREFIX" \
  --query "Contents[?contains(Key,\`/${JOB_ID}_\`) || ends_with(Key,\`/${JOB_ID}.json\`)].Key" \
  --output text 2>/dev/null || true)

# Normalize whitespace
MANIFEST_KEYS=$(echo "$MANIFEST_KEYS" | tr '\t' '\n' | sed '/^$/d')
NUM_KEYS=$(echo "$MANIFEST_KEYS" | grep -c . || true)

if [ "$NUM_KEYS" = "0" ] || [ -z "$MANIFEST_KEYS" ]; then
  echo "[submit_job] ERROR: no manifest found for $JOB_ID under s3://$REPORTS_BUCKET/$MANIFEST_PREFIX" >&2
  exit 65
fi
if [ "$NUM_KEYS" -gt 1 ]; then
  echo "[submit_job] ERROR: multiple manifests matched $JOB_ID (expected 1):" >&2
  echo "$MANIFEST_KEYS" >&2
  exit 65
fi

MANIFEST_KEY="$MANIFEST_KEYS"
MANIFEST_URI="s3://$REPORTS_BUCKET/$MANIFEST_KEY"

# Job name (idempotent by pattern; timestamp gives uniqueness for resubmission)
# Use tr for lowercase — bash 3.2 (macOS default) lacks the ${VAR,,} expansion.
TS="$(date -u +%Y%m%dT%H%M%SZ)"
JOB_ID_LOWER="$(printf '%s' "$JOB_ID" | tr '[:upper:]' '[:lower:]')"
JOB_NAME="jpcite-${JOB_ID_LOWER}-${TS}"

# Tags
declare -a TAGS=(
  "Project=jpcite"
  "CreditRun=2026-05"
  "Workload=$JOB_ID"
  "AutoStop=$AUTO_STOP"
)
TAG_ARG=$(IFS=,; echo "${TAGS[*]}")
# Convert to "Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 ..." style for --tags
TAGS_JSON=$(python3 -c "
import json, sys
pairs=sys.argv[1].split(',')
d={p.split('=',1)[0]: p.split('=',1)[1] for p in pairs}
print(json.dumps(d))
" "$TAG_ARG")

# Container env override
ENV_JSON=$(python3 -c "
import json
env=[
  {'name':'JOB_MANIFEST_S3_URI','value':'$MANIFEST_URI'},
  {'name':'OUTPUT_S3_BUCKET','value':'$RAW_BUCKET'},
  {'name':'REPORTS_S3_BUCKET','value':'$REPORTS_BUCKET'},
  {'name':'AWS_DEFAULT_REGION','value':'$REGION'},
  {'name':'JPCITE_JOB_ID','value':'$JOB_ID'},
]
print(json.dumps({'environment':env}))
")

echo "[submit_job] job_id     = $JOB_ID"
echo "[submit_job] queue      = $QUEUE"
echo "[submit_job] job_def    = $JOB_DEF"
echo "[submit_job] job_name   = $JOB_NAME"
echo "[submit_job] manifest   = $MANIFEST_URI"
echo "[submit_job] raw_bucket = s3://$RAW_BUCKET/"
echo "[submit_job] tags       = $TAGS_JSON"
echo "[submit_job] log_group  = $LOG_GROUP"
echo "[submit_job] log_stream_prefix = $LOG_GROUP / $JOB_DEF/default/<task-uuid>"

if [ "$DRY_RUN" = "true" ]; then
  echo "[submit_job] DRY_RUN — not submitting."
  exit 0
fi

JOB_OUT=$(aws batch submit-job \
  --region "$REGION" \
  --job-name "$JOB_NAME" \
  --job-queue "$QUEUE" \
  --job-definition "$JOB_DEF" \
  --tags "$TAGS_JSON" \
  --container-overrides "$ENV_JSON" \
  --output json)

JOB_BATCH_ID=$(echo "$JOB_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('jobId',''))")
echo "[submit_job] SUBMITTED jobId=$JOB_BATCH_ID name=$JOB_NAME queue=$QUEUE"
echo "$JOB_OUT"
