#!/usr/bin/env bash
# Print the CloudWatch dashboard URL for the jpcite-credit 2026-05 run.
#
# Dashboard: jpcite-credit-2026-05 (region us-east-1, multi-region widgets)
# Widgets:
#   Row 1 (single-value): actual_spend / forecasted_spend / batch_running / batch_failed_24h
#   Row 2 (line graph, 6h): Batch jobs over time (submitted/runnable/running/succeeded/failed × 2 queues)
#   Row 3 (line graph, daily): S3 BucketSizeBytes + NumberOfObjects (raw/derived/reports)
#   Row 4 (line graph, 7d):   Billing EstimatedCharges
#   Row 5 (line graph):        Batch CE vCPU usage (Fargate + EC2)
#
# Read-only. No AWS calls. Safe to run any time.
set -euo pipefail

DASHBOARD_NAME="${DASHBOARD_NAME:-jpcite-credit-2026-05}"
REGION="${REGION:-us-east-1}"

URL="https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=${DASHBOARD_NAME}"

echo "[open-dashboard] name:   ${DASHBOARD_NAME}"
echo "[open-dashboard] region: ${REGION}"
echo "[open-dashboard] url:    ${URL}"
echo ""
echo "Open in browser:"
echo "  open '${URL}'"
