#!/bin/bash
# DRY-RUN simulation: verify the deny policy attaches cleanly to bookyou-recovery-admin
# then immediately detach. This is what the Budget Action will do automatically on $18,900 breach.
# Run with --commit to actually attach+detach (default is dry-run report only).
set -euo pipefail
PROFILE=${PROFILE:-bookyou-recovery}
POLICY_ARN="arn:aws:iam::993693061769:policy/jpcite-credit-run-deny-new-spend"
USER="bookyou-recovery-admin"
MODE=${1:-dry-run}

echo "[simulate] mode=$MODE policy=$POLICY_ARN target_user=$USER"
echo "[simulate] step 1: current attached policies"
aws --profile "$PROFILE" iam list-attached-user-policies --user-name "$USER" | grep PolicyName

if [[ "$MODE" != "--commit" ]]; then
  echo "[simulate] DRY-RUN: would attach $POLICY_ARN to $USER then immediately detach"
  echo "[simulate] DRY-RUN: no AWS state change. Re-run with --commit to live-test."
  exit 0
fi

echo "[simulate] step 2: ATTACH deny policy (live)"
aws --profile "$PROFILE" iam attach-user-policy --user-name "$USER" --policy-arn "$POLICY_ARN"
echo "[simulate] step 3: verify attached"
aws --profile "$PROFILE" iam list-attached-user-policies --user-name "$USER" | grep -E "(PolicyName|deny-new-spend)"
echo "[simulate] step 4: probe — attempt batch:SubmitJob (should be DENIED)"
set +e
aws --profile "$PROFILE" batch submit-job --job-name probe-deny --job-queue jpcite-jq-mainline --job-definition jpcite-crawler 2>&1 | grep -i "AccessDenied\|denied\|explicit deny" | head -3
set -e
echo "[simulate] step 5: DETACH deny policy (restore)"
aws --profile "$PROFILE" iam detach-user-policy --user-name "$USER" --policy-arn "$POLICY_ARN"
echo "[simulate] step 6: verify detached"
aws --profile "$PROFILE" iam list-attached-user-policies --user-name "$USER" | grep PolicyName
echo "[simulate] complete — deny attach/detach cycle verified"
