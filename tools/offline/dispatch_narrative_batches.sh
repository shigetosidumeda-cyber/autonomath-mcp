#!/bin/bash
# OPERATOR ONLY — instructions emitter for the W20 25-shard narrative batch.
#
# This script does NOT itself invoke `claude` or any LLM SDK. Per
# `feedback_no_operator_llm_api`, all subagent invocations must be
# launched by the operator across multiple Claude Code Max Pro Plan
# accounts (固定費), not from operator code paths. This script just
# prints the 25 commands the operator should paste / dispatch on N
# parallel terminals (or a tmux + multi-account session).
#
# WORKFLOW:
#   1. operator (run earlier): generate_program_narratives.py --shards 25 ...
#      → tools/offline/_inbox/narrative/_batches/agentNN.json (25 files)
#   2. operator: ./tools/offline/dispatch_narrative_batches.sh
#      → prints 25 instruction blocks; operator dispatches each on a
#        separate Claude Code Max Pro Plan account / terminal
#   3. each subagent reads its agentNN.json, writes one JSONL row per
#      program to tools/offline/_inbox/narrative/{date}_agentNN.jsonl,
#      and emits "AGENT_DONE shard=<i>/<n> rows=<k>" on stdout when done
#   4. operator: python tools/offline/ingest_narrative_inbox.py
#      → UPSERTs into autonomath.am_program_narrative_full
#
# Notes:
#  * `--shards 25` is the canonical fan-out (matches Wave 1-5 / 1-16 18+
#    parallel subagent precedent + leaves headroom for Max Pro Plan
#    rate limits across 2-3 accounts).
#  * Each shard is ~464 programs. At ~2 minutes / program for narrative
#    + 反駁 generation, one shard ≈ 15h wall clock. 25 in parallel ≈ 15h
#    end-to-end if all accounts saturate.
#  * Re-running the sharder after partial completion will re-pick only
#    the still-pending programs (am_program_narrative_full PRIMARY KEY
#    skip), so partial dispatch is safe.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BATCHES_DIR="${REPO_ROOT}/tools/offline/_inbox/narrative/_batches"

if [[ ! -d "${BATCHES_DIR}" ]]; then
  echo "ERROR: batches dir missing: ${BATCHES_DIR}" >&2
  echo "       run: python tools/offline/generate_program_narratives.py --shards 25 --tier S,A,B,C" >&2
  exit 2
fi

SHARDS=$(ls "${BATCHES_DIR}"/agent*.json 2>/dev/null | wc -l | tr -d ' ')
if [[ "${SHARDS}" -eq 0 ]]; then
  echo "ERROR: no agent*.json shards in ${BATCHES_DIR}" >&2
  exit 2
fi

cat <<'BANNER'
================================================================================
W20 narrative batch dispatch — 25 parallel Claude Code Max Pro subagents
================================================================================

For each shard below, open a fresh Claude Code session (different Max Pro
account if available) and paste the prompt block. Each shard is independent
— they do not share state. The ingest cron deduplicates on program_id.

The subagent prompt template uses the structured-JSON output contract
defined in expected_row_schema (see the agentNN.json file). Output goes
to a JSONL file at the path printed in _meta.inbox_jsonl_path.

NO LLM CALL is made by this dispatcher. The `claude` invocations below
are descriptive — copy/paste each into a separate terminal owned by the
operator's Max Pro account.

================================================================================

BANNER

for i in $(seq 1 "${SHARDS}"); do
  AGENT_ID=$(printf "agent%02d" "${i}")
  SHARD_FILE="${BATCHES_DIR}/${AGENT_ID}.json"
  if [[ ! -f "${SHARD_FILE}" ]]; then
    echo "WARN: shard missing: ${SHARD_FILE}" >&2
    continue
  fi
  ROW_COUNT=$(python3 -c "import json,sys; d=json.load(open('${SHARD_FILE}')); print(d['_meta']['row_count'])")
  INBOX_PATH=$(python3 -c "import json,sys; d=json.load(open('${SHARD_FILE}')); print(d['_meta']['inbox_jsonl_path'])")
  cat <<EOF
--- Shard ${i}/${SHARDS} (${AGENT_ID}, ${ROW_COUNT} programs) ---
# In a fresh Claude Code terminal (Max Pro account ${i}):
claude "Read tools/offline/_inbox/narrative/_batches/${AGENT_ID}.json. \
For every row in 'rows', generate a JSONL line conforming to expected_row_schema. \
Write all lines to ${INBOX_PATH}. \
Follow narrative_rules + counter_arguments_rules + content_hash_rule strictly. \
Do NOT invent source URLs; cite only the source_url given in each input row. \
On completion print: AGENT_DONE shard=${i}/${SHARDS} rows=${ROW_COUNT}"

EOF
done

cat <<'FOOTER'
================================================================================
After all 25 shards report AGENT_DONE, run the ingest:

  python tools/offline/ingest_narrative_inbox.py

Expected: 11,601 rows UPSERTed into autonomath.am_program_narrative_full
(primary key program_id; idempotent re-ingest via content_hash diff).

Verify:
  sqlite3 autonomath.db "SELECT COUNT(*) FROM am_program_narrative_full;"
================================================================================
FOOTER
