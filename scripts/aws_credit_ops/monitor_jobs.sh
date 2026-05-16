#!/usr/bin/env bash
# Monitor jpcite-credit Batch jobs from the last 24h.
#
# Output:
#   1. Status counts (SUCCEEDED / RUNNING / FAILED / PENDING / RUNNABLE / SUBMITTED / STARTING)
#      across both jpcite-credit-* queues.
#   2. Top 5 most recent jobs with name + status + created/started/stopped + duration.
#   3. Last 10 lines of the most recent job's CloudWatch log stream
#      (from $LOG_GROUP, default /aws/batch/jpcite-credit-2026-05).
#
# Read-only. Safe to run any time. Cheap (~3 API calls + one logs:GetLogEvents).
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

LOG_GROUP="${LOG_GROUP:-/aws/batch/jpcite-credit-2026-05}"
FARGATE_QUEUE="${FARGATE_QUEUE:-jpcite-credit-fargate-spot-short-queue}"
EC2_QUEUE="${EC2_QUEUE:-jpcite-credit-ec2-spot-cpu-queue}"
HOURS="${HOURS:-24}"

echo "[monitor] window: last ${HOURS}h"
echo "[monitor] queues: $FARGATE_QUEUE, $EC2_QUEUE"
echo "[monitor] log group: $LOG_GROUP"

STATUSES=(SUBMITTED PENDING RUNNABLE STARTING RUNNING SUCCEEDED FAILED)

# Collect (queue, jobId, name, status, createdAt, startedAt, stoppedAt) rows into a temp jsonl
TMP=$(mktemp -t jpcite-monitor.XXXXXX)
trap 'rm -f "$TMP"' EXIT

CUTOFF_MS=$(python3 -c "import time; print(int((time.time() - ${HOURS}*3600) * 1000))")

for Q in "$FARGATE_QUEUE" "$EC2_QUEUE"; do
  if ! aws batch describe-job-queues --region "$REGION" --job-queues "$Q" >/dev/null 2>&1; then
    echo "[monitor] queue not found, skipping: $Q" >&2
    continue
  fi
  for ST in "${STATUSES[@]}"; do
    aws batch list-jobs \
      --region "$REGION" \
      --job-queue "$Q" \
      --job-status "$ST" \
      --max-results 100 \
      --query "jobSummaryList[*].{q:'${Q}',id:jobId,name:jobName,status:status,created:createdAt,started:startedAt,stopped:stoppedAt}" \
      --output json 2>/dev/null \
      | python3 -c "
import json,sys
cutoff=${CUTOFF_MS}
for r in json.load(sys.stdin) or []:
  c=r.get('created') or 0
  if c >= cutoff:
    print(json.dumps(r))
" >> "$TMP" || true
  done
done

# Status counts
echo ""
echo "[monitor] status counts (last ${HOURS}h, both queues):"
python3 -c "
import json,sys
from collections import Counter
c=Counter()
with open('$TMP') as f:
  for line in f:
    line=line.strip()
    if not line: continue
    r=json.loads(line)
    c[r.get('status','UNKNOWN')] += 1
order=['SUBMITTED','PENDING','RUNNABLE','STARTING','RUNNING','SUCCEEDED','FAILED']
for k in order:
  if c[k] or k in ('RUNNING','SUCCEEDED','FAILED'):
    print(f'  {k:<12} {c[k]:>4}')
extra=[k for k in c if k not in order]
for k in sorted(extra):
  print(f'  {k:<12} {c[k]:>4}')
print(f'  {\"TOTAL\":<12} {sum(c.values()):>4}')
"

# Top 5 most recent
echo ""
echo "[monitor] top 5 most recent jobs:"
TOP5=$(python3 -c "
import json,sys
rows=[]
with open('$TMP') as f:
  for line in f:
    line=line.strip()
    if not line: continue
    rows.append(json.loads(line))
rows.sort(key=lambda r: r.get('created') or 0, reverse=True)
for r in rows[:5]:
  c=(r.get('created') or 0)/1000
  st=(r.get('started') or 0)/1000
  sp=(r.get('stopped') or 0)/1000
  dur='-'
  if sp and st:
    dur=f'{int(sp-st)}s'
  elif st:
    import time
    dur=f'{int(time.time()-st)}s (running)'
  import datetime
  ts=datetime.datetime.utcfromtimestamp(c).strftime('%Y-%m-%dT%H:%M:%SZ') if c else '-'
  print(f'  {r[\"status\"]:<10} {r[\"name\"]:<50} created={ts} dur={dur} id={r[\"id\"]}')
print('--first-id--')
for r in rows[:1]:
  print(r['id'])
")
echo "$TOP5" | grep -v '^--first-id--' | grep -v '^[a-f0-9-]\{36\}$' || true
MOST_RECENT_ID=$(echo "$TOP5" | awk '/^--first-id--$/{flag=1;next} flag{print; exit}')

# Last 10 log lines from most recent
echo ""
if [ -z "${MOST_RECENT_ID:-}" ]; then
  echo "[monitor] no recent jobs found, skipping log tail."
  exit 0
fi
echo "[monitor] log tail for most recent job: $MOST_RECENT_ID"

DESC=$(aws batch describe-jobs --region "$REGION" --jobs "$MOST_RECENT_ID" --output json 2>/dev/null || echo '{}')
STREAM=$(echo "$DESC" | python3 -c "
import json,sys
d=json.load(sys.stdin)
jobs=d.get('jobs',[])
if not jobs: print(''); sys.exit(0)
c=jobs[0].get('container') or {}
print(c.get('logStreamName',''))
")

if [ -z "$STREAM" ]; then
  echo "  (no logStreamName yet — job may still be RUNNABLE/STARTING)"
  exit 0
fi

echo "  stream: $LOG_GROUP / $STREAM"
aws logs get-log-events \
  --region "$REGION" \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$STREAM" \
  --limit 10 \
  --output json 2>/dev/null \
  | python3 -c "
import json,sys,datetime
d=json.load(sys.stdin)
for ev in d.get('events',[]):
  t=datetime.datetime.utcfromtimestamp(ev['timestamp']/1000).strftime('%H:%M:%S')
  msg=ev['message'].rstrip()
  print(f'    [{t}] {msg}')
" || echo "  (could not fetch log events — stream may be empty)"
