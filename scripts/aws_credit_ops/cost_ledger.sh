#!/usr/bin/env bash
# Hourly cost ledger for jpcite credit run
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
START="${1:-$(date -u -v-1d +%Y-%m-%d)}"
END="${2:-$(date -u +%Y-%m-%d)}"
echo "[cost-ledger] window: $START -> $END"
aws ce get-cost-and-usage \
  --region us-east-1 \
  --time-period "Start=${START},End=${END}" \
  --granularity DAILY \
  --metrics UnblendedCost NetUnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE | python3 -c "
import json,sys
d=json.load(sys.stdin)
for row in d.get('ResultsByTime',[]):
  tp=row['TimePeriod']
  print(f\"\\n=== {tp['Start']} -> {tp['End']} ===\")
  groups=sorted(row.get('Groups',[]),key=lambda g:-float(g['Metrics'].get('UnblendedCost',{}).get('Amount','0')))
  total_gross=total_net=0.0
  for g in groups[:15]:
    svc=g['Keys'][0]
    gross=float(g['Metrics']['UnblendedCost']['Amount'])
    net=float(g['Metrics']['NetUnblendedCost']['Amount'])
    if gross>0.01 or net>0.001:
      print(f'  {svc:<40} gross=\\$ {gross:>10.2f}  net=\\$ {net:>10.4f}')
    total_gross+=gross
    total_net+=net
  print(f'  {\"TOTAL\":<40} gross=\\$ {total_gross:>10.2f}  net=\\$ {total_net:>10.4f}')
"
