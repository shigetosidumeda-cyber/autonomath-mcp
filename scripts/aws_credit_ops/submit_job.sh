#!/usr/bin/env bash
# Submit a single jpcite-credit crawl job to AWS Batch.
#
# Usage:
#   scripts/aws_credit_ops/submit_job.sh <job_id> [--ec2] [--heavy]
#
#   <job_id>   e.g. J01, J02, ..., J07, or deep variants like J02-deep
#   --ec2      route to jpcite-credit-ec2-spot-cpu-queue (J06 PDF heavy default)
#   --heavy    use jpcite-crawl-heavy job def (Fargate 16 vCPU / 32 GB, 2h timeout)
#              instead of jpcite-crawl (Fargate 1 vCPU / 2 GB, 30 min timeout).
#              Auto-enabled for any job_id matching *-deep (J02-deep etc).
#
# Reads the manifest URI from s3://jpcite-credit-993693061769-202605-reports/manifests/<job_id>_*.json
# (resolves to a single match; bails if 0 or 2+ matches).
#
# Submits Batch job (definition jpcite-crawl by default, jpcite-crawl-heavy with --heavy) with env vars:
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
JOB_DEF_HEAVY="${JOB_DEF_HEAVY:-jpcite-crawl-heavy}"
FARGATE_QUEUE="${FARGATE_QUEUE:-jpcite-credit-fargate-spot-short-queue}"
EC2_QUEUE="${EC2_QUEUE:-jpcite-credit-ec2-spot-cpu-queue}"
LOG_GROUP="${LOG_GROUP:-/aws/batch/jpcite-credit-2026-05}"
AUTO_STOP="${AUTO_STOP:-2026-05-29}"

usage() {
  cat <<USAGE
usage: $0 <job_id> [--ec2] [--heavy]
  job_id: J01..J07 (light) or J02-deep / J03-deep ... (heavy deep variants)
  --ec2:    route to $EC2_QUEUE instead of $FARGATE_QUEUE (J06 PDF heavy default)
  --heavy:  use $JOB_DEF_HEAVY (Fargate 16 vCPU / 32 GB / 2h timeout) instead of $JOB_DEF.
            Auto-enabled when job_id ends with -deep.
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
USE_HEAVY=false
for arg in "$@"; do
  case "$arg" in
    --ec2) USE_EC2=true ;;
    --heavy) USE_HEAVY=true ;;
    -h|--help) usage ;;
    *) echo "[submit_job] unknown arg: $arg" >&2; usage ;;
  esac
done

# Validate job_id pattern (J01..J15 or J0X-deep variants)
# J01-J07 (Wave 50 baseline) / J08-J11 (kanpou/courts/houmu/estat) /
# J12-J15 (kokkai/edinet/jpo/env, added 2026-05-16)
if ! [[ "$JOB_ID" =~ ^J(0[1-9]|1[0-5])(-deep)?$ ]]; then
  echo "[submit_job] invalid job_id: $JOB_ID (expected J01..J15 or J0X-deep / J1X-deep)" >&2
  exit 64
fi

# *-deep variants auto-route to heavy job def
if [[ "$JOB_ID" =~ -deep$ ]] && [ "$USE_HEAVY" = "false" ]; then
  echo "[submit_job] note: $JOB_ID is a deep variant — auto-enabling --heavy (jpcite-crawl-heavy)." >&2
  USE_HEAVY=true
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

if [ "$USE_HEAVY" = "true" ]; then
  JOB_DEF_EFFECTIVE="$JOB_DEF_HEAVY"
else
  JOB_DEF_EFFECTIVE="$JOB_DEF"
fi

# Resolve manifest URI from S3 prefix
# For *-deep variants we look for "<jobid_with_dash>_" or "<jobid_with_underscore>_" prefixes
# (J02-deep matches J02_deep_*.json or J02-deep_*.json).
MANIFEST_MATCH_TOKEN="${JOB_ID/-/_}"
echo "[submit_job] locating manifest for $JOB_ID (match token: ${MANIFEST_MATCH_TOKEN}) under s3://$REPORTS_BUCKET/$MANIFEST_PREFIX ..."
MANIFEST_KEYS=$(aws s3api list-objects-v2 \
  --region "$REGION" \
  --bucket "$REPORTS_BUCKET" \
  --prefix "$MANIFEST_PREFIX" \
  --query "Contents[?contains(Key,\`/${MANIFEST_MATCH_TOKEN}_\`) || ends_with(Key,\`/${MANIFEST_MATCH_TOKEN}.json\`)].Key" \
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
echo "[submit_job] job_def    = $JOB_DEF_EFFECTIVE"
echo "[submit_job] heavy      = $USE_HEAVY"
echo "[submit_job] job_name   = $JOB_NAME"
echo "[submit_job] manifest   = $MANIFEST_URI"
echo "[submit_job] raw_bucket = s3://$RAW_BUCKET/"
echo "[submit_job] tags       = $TAGS_JSON"
echo "[submit_job] log_group  = $LOG_GROUP"
echo "[submit_job] log_stream_prefix = $LOG_GROUP / $JOB_DEF_EFFECTIVE/default/<task-uuid>"

if [ "$DRY_RUN" = "true" ]; then
  echo "[submit_job] DRY_RUN — not submitting."
  exit 0
fi

JOB_OUT=$(aws batch submit-job \
  --region "$REGION" \
  --job-name "$JOB_NAME" \
  --job-queue "$QUEUE" \
  --job-definition "$JOB_DEF_EFFECTIVE" \
  --tags "$TAGS_JSON" \
  --container-overrides "$ENV_JSON" \
  --output json)

JOB_BATCH_ID=$(echo "$JOB_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('jobId',''))")
echo "[submit_job] SUBMITTED jobId=$JOB_BATCH_ID name=$JOB_NAME queue=$QUEUE"
echo "$JOB_OUT"
