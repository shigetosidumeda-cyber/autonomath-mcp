#!/usr/bin/env bash
# Create / update the jpcite CloudFront packet mirror distribution.
#
# Idempotent: on first run creates OAC + distribution + bucket policy
# attachment. Subsequent runs verify the distribution exists and re-print
# the domain.
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/cloudfront_packet_mirror_setup.sh
#
# Default DRY_RUN — set CF_MIRROR_COMMIT=1 to actually create.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
REGION="${REGION:-ap-northeast-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"
BUCKET="${BUCKET:-jpcite-credit-993693061769-202605-derived}"
OAC_NAME="${OAC_NAME:-jpcite-packet-mirror-oac}"
COMMENT="${COMMENT:-jpcite packet mirror — public read-only over derived bucket (CreditRun 2026-05, AutoStop 2026-05-29)}"
COMMIT="${CF_MIRROR_COMMIT:-0}"
TAG_PROJECT="${TAG_PROJECT:-jpcite}"
TAG_CREDITRUN="${TAG_CREDITRUN:-2026-05}"
TAG_AUTOSTOP="${TAG_AUTOSTOP:-2026-05-29}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OAC_DOC="$ROOT/infra/aws/cloudfront/jpcite_packet_mirror_oac.json"
DIST_DOC="$ROOT/infra/aws/cloudfront/jpcite_packet_mirror_distribution.json"
POLICY_TPL="$ROOT/infra/aws/cloudfront/jpcite_packet_mirror_bucket_policy_template.json"

for f in "$OAC_DOC" "$DIST_DOC" "$POLICY_TPL"; do
  [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done

CALLER_REF="jpcite-packet-mirror-$(date -u +%Y%m%d%H%M%S)"

if [ "$COMMIT" != "1" ]; then
  cat <<EOF
[DRY_RUN] would:
  1. create OAC from $OAC_DOC
  2. render $DIST_DOC with caller_ref=$CALLER_REF + OAC id, then create-distribution
  3. wait for Status=InProgress→Deployed
  4. merge AllowCloudFrontServicePrincipalReadOnly into bucket $BUCKET policy
  5. tag distribution Project=$TAG_PROJECT CreditRun=$TAG_CREDITRUN AutoStop=$TAG_AUTOSTOP
Set CF_MIRROR_COMMIT=1 to execute.
EOF
  exit 0
fi

echo "[setup] step 1/5  Origin Access Control"
EXISTING_OAC_ID=$(aws cloudfront list-origin-access-controls --query "OriginAccessControlList.Items[?Name=='$OAC_NAME'].Id | [0]" --output text 2>/dev/null || echo "None")
if [ "$EXISTING_OAC_ID" != "None" ] && [ -n "$EXISTING_OAC_ID" ]; then
  OAC_ID="$EXISTING_OAC_ID"
  echo "  reuse OAC $OAC_ID"
else
  OAC_ID=$(aws cloudfront create-origin-access-control \
    --origin-access-control-config "file://$OAC_DOC" \
    --query 'OriginAccessControl.Id' --output text)
  echo "  created OAC $OAC_ID"
fi

echo "[setup] step 2/5  render + create distribution"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

RENDERED="$WORK/distribution_rendered.json"
sed -e "s/CALLER_REF_PLACEHOLDER/$CALLER_REF/" \
    -e "s/OAC_ID_PLACEHOLDER/$OAC_ID/" \
    "$DIST_DOC" > "$RENDERED"

# Look for an already-existing distribution that points at the same origin.
EXISTING_DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, '$BUCKET')].Id | [0]" \
  --output text 2>/dev/null || echo "None")

if [ "$EXISTING_DIST_ID" != "None" ] && [ -n "$EXISTING_DIST_ID" ]; then
  DIST_ID="$EXISTING_DIST_ID"
  echo "  reuse distribution $DIST_ID"
else
  DIST_ID=$(aws cloudfront create-distribution \
    --distribution-config "file://$RENDERED" \
    --query 'Distribution.Id' --output text)
  echo "  created distribution $DIST_ID"
fi

DIST_DOMAIN=$(aws cloudfront get-distribution \
  --id "$DIST_ID" \
  --query 'Distribution.DomainName' --output text)
DIST_ARN="arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${DIST_ID}"

echo "[setup] step 3/5  tag distribution"
aws cloudfront tag-resource \
  --resource "$DIST_ARN" \
  --tags "Items=[{Key=Project,Value=$TAG_PROJECT},{Key=CreditRun,Value=$TAG_CREDITRUN},{Key=AutoStop,Value=$TAG_AUTOSTOP}]" >/dev/null
echo "  tagged $DIST_ARN"

echo "[setup] step 4/5  merge bucket policy"
POLICY_RENDERED="$WORK/bucket_policy_rendered.json"
sed -e "s/DIST_ID_PLACEHOLDER/$DIST_ID/" "$POLICY_TPL" > "$POLICY_RENDERED"
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "file://$POLICY_RENDERED" >/dev/null
echo "  bucket policy applied to $BUCKET"

echo "[setup] step 5/5  summary"
cat <<EOF

[setup] done.
  distribution_id     = $DIST_ID
  distribution_arn    = $DIST_ARN
  distribution_domain = $DIST_DOMAIN
  oac_id              = $OAC_ID
  bucket              = $BUCKET
  caller_ref          = $CALLER_REF

next:
  - wait for Status=Deployed (typically 5-10 min):
      aws cloudfront get-distribution --id $DIST_ID --query 'Distribution.Status'
  - build manifest:
      .venv/bin/python scripts/aws_credit_ops/cf_loadtest_build_manifest.py --max-keys 10000
  - smoke (DRY_RUN):
      .venv/bin/python scripts/aws_credit_ops/cf_loadtest_runner.py \\
        --distribution-domain $DIST_DOMAIN --requests 10000
EOF
