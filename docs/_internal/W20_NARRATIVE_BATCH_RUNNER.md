# W20 Narrative Batch Runner

Operator-only runbook for the `am_program_narrative_full` (migration
`wave24_149`) pre-render. The substrate is the W20 fast-path that the
MCP `get_program_narrative` tool consults BEFORE falling back to the
4-section `am_program_narrative` (wave24_136) cache.

> **Non-negotiable**: jpcite production code (anything under `src/`,
> `scripts/cron/`, `scripts/etl/`, `tests/`) MUST NOT import an LLM SDK.
> All steps below run from the operator workstation under
> `tools/offline/`. See `feedback_no_operator_llm_api`.

## Table of contents

1. [Preflight](#1-preflight)
2. [Generate batch shards](#2-generate-batch-shards)
3. [Launch 25 parallel Claude Code subagents](#3-launch-25-parallel-claude-code-subagents)
4. [Ingest the JSONL inbox](#4-ingest-the-jsonl-inbox)
5. [Verify cache hit on the MCP tool](#5-verify-cache-hit-on-the-mcp-tool)
6. [Re-runs / partial recovery](#6-re-runs--partial-recovery)

---

## 1. Preflight

```bash
cd /Users/shigetoumeda/jpcite

# Ensure migration 149 is applied (idempotent — safe to re-run).
sqlite3 autonomath.db < scripts/migrations/wave24_149_am_program_narrative_full.sql
sqlite3 autonomath.db "PRAGMA table_info(am_program_narrative_full);"
# Expect 7 columns: program_id / narrative_md / counter_arguments_md /
# generated_at / model_used / content_hash / source_program_corpus_snapshot_id

# Confirm pending count.
sqlite3 data/jpintel.db \
  "SELECT COUNT(*) FROM programs WHERE excluded=0 AND tier IN ('S','A','B','C');"
# 11,601 as of 2026-05-04 (cf. CLAUDE.md "11,684 searchable" — small drift
# is expected, the script SELECTs the live count).

sqlite3 autonomath.db "SELECT COUNT(*) FROM am_program_narrative_full;"
# 0 on the first run; > 0 after partial ingest (which is the expected
# post-launch steady state — re-runs only enqueue the diff).
```

## 2. Generate batch shards

```bash
# Smoke test first (1 program, 1 shard, dry run).
.venv/bin/python tools/offline/generate_program_narratives.py \
  --shards 1 --tier S --limit 1 --dry-run

# Full sharded run, 25 parallel agents.
.venv/bin/python tools/offline/generate_program_narratives.py \
  --shards 25 --tier S,A,B,C
```

Outputs land at `tools/offline/_inbox/narrative/_batches/agentNN.json`,
one JSON file per shard. Each file contains:

* `_meta` block (agent index, shard size, tier mix, schema version,
  inbox JSONL path the subagent must write to)
* `instructions` block (narrative_md + counter_arguments_md rules,
  content_hash recipe, completion marker convention)
* `expected_row_schema` (JSON Schema the ingest cron validates against)
* `rows` (the program list the agent must cover)

The script does NOT call any LLM. It only SELECTs from
`jpintel.db.programs`, diffs against
`autonomath.am_program_narrative_full`, and writes the agent batch
files.

## 3. Launch 25 parallel Claude Code subagents

> Max Pro Plan is a fixed cost; parallelism is free. Run all 25 at
> once on the operator workstation. Do NOT use the Anthropic API.

For each `agentNN.json`, open a fresh Claude Code session and paste:

```
You are W20 narrative batch agent agent01 (of 25).

Your task is in this file:
  /Users/shigetoumeda/jpcite/tools/offline/_inbox/narrative/_batches/agent01.json

Read the _meta + instructions + expected_row_schema. For each row in
`rows`, write one JSONL line to `_meta.inbox_jsonl_path`. Each JSONL
line must conform to expected_row_schema and pass the content_hash
recipe in instructions.content_hash_rule.

When done, print exactly one line:
  AGENT_DONE shard=01/25 rows=<actual_row_count>

Do NOT call any HTTP API. Do NOT fetch source URLs (the corpus is
already in the row payload). Skip rows you cannot meet the quality bar
for; do not write low-quality fallbacks.
```

Repeat for `agent02.json` ... `agent25.json` in 24 more sessions. The
JSONL writes are append-only, one row per program; concurrent shards
write to disjoint files (`{date}_agent01.jsonl`,
`{date}_agent02.jsonl`, ...) so no locking is needed.

## 4. Ingest the JSONL inbox

After `AGENT_DONE` lands in all 25 sessions:

```bash
# (W20 ingest cron — wired in scripts/cron/ingest_offline_inbox.py;
# see ingest_narrative_inbox_full sub-command for the W20 path.)
.venv/bin/python scripts/cron/ingest_offline_inbox.py \
  --kind narrative_full \
  --inbox tools/offline/_inbox/narrative/ \
  --autonomath-db autonomath.db
```

The ingest UPSERTs into `am_program_narrative_full`:

* CONFLICT (program_id) with same `content_hash` → no-op (idempotent).
* CONFLICT with different `content_hash` → overwrite + bump
  `generated_at`.
* Schema-fail rows → moved to `tools/offline/_quarantine/narrative/`
  for manual triage.

## 5. Verify cache hit on the MCP tool

```bash
# Pick any UNI-... id you know was processed.
sqlite3 autonomath.db \
  "SELECT program_id, length(narrative_md), length(counter_arguments_md), model_used
     FROM am_program_narrative_full LIMIT 5;"

# Hit the MCP tool. The W20 fast-path returns _cache_hit=true when
# am_program_narrative_full carries the row; otherwise it falls through
# to the existing 4-section am_program_narrative path.
.venv/bin/autonomath-mcp <<< '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_program_narrative","arguments":{"program_id":"UNI-..."}}}'
```

Look for `_cache_hit: true` and a `narrative_full` block in the
response. The four-section path remains the fallback.

## 6. Re-runs / partial recovery

* Re-run step 2; the SQL `SQL_DONE` filter removes already-ingested
  programs, so only the residual goes back to the agents.
* If a single shard fails mid-run, just relaunch that shard's session;
  the inbox JSONL is append-only and the ingest is idempotent.
* To force regeneration of a stale row, delete it from
  `am_program_narrative_full` first, then re-run step 2.

---

## Appendix: smoke test gate

The `generate_program_narratives.py --limit 1` invocation in step 2 is
the canonical smoke test. The expected `agent01.json` shape is in
`tools/offline/_inbox/narrative/_batches/agent01.json` and is asserted
against `expected_row_schema` by the ingest cron — if the schema field
list drifts, the cron fails closed and quarantines the rows.
