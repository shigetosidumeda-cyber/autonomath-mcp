# W28 narrative dispatch — remaining 24 shards

**Status snapshot (2026-05-05):**
- Shard 1/25 (`agent01.json`, 465 programs) **COMPLETE**.
  - `am_program_narrative_full` row count: 1 → **465** (smoke row UPSERT-overwritten).
  - JSONL: `tools/offline/_inbox/narrative/_done/2026-05-05_agent01.jsonl`
  - Subagent: this Claude Code Opus 4.7 session, no LLM API call (operator-only constraint per `feedback_no_operator_llm_api`).
- Shards 2..25 (`agent02.json` ... `agent25.json`, ~464 programs each, **~11,135 programs remaining**) **PENDING dispatch**.
- Target final state: `am_program_narrative_full` ≈ **11,600** rows, narrative cache hit ~100% across S/A/B/C tier searchable programs.

---

## 1. Why the existing dispatcher needs no rewrite

`tools/offline/dispatch_narrative_batches.sh` already emits the per-shard subagent prompt and references the same `_batches/agentNN.json` substrate. Re-run it as-is to get the 25 prompt blocks; agent01 has already been consumed (its JSONL is in `_done/`) so re-running shard 1 is idempotent (UPSERT diff on `content_hash` → no-op if the JSONL is regenerated identically; overwrite if the subagent's prose differs).

```bash
./tools/offline/dispatch_narrative_batches.sh > /tmp/W28_prompts.txt
# Skip shard 1 (already complete). Use shards 2..25.
```

---

## 2. Operator dispatch checklist (Max Pro multi-account)

Per `feedback_max_parallel_subagents` (default 8-10+ parallel), the operator runs 24 remaining shards across 2-3 Max Pro Plan accounts. Recommended fan-out:

| Account | Shards | Wall clock |
|---|---|---|
| acct A | 02, 05, 08, 11, 14, 17, 20, 23 (8 shards serial) | ~3-5h × 8 |
| acct B | 03, 06, 09, 12, 15, 18, 21, 24 (8 shards serial) | ~3-5h × 8 |
| acct C | 04, 07, 10, 13, 16, 19, 22, 25 (8 shards serial) | ~3-5h × 8 |

If only 1-2 accounts are available, run the shards sequentially within each — the ingest is idempotent.

### Per-shard prompt (paste into fresh Claude Code session)

```
Read /Users/shigetoumeda/jpcite/tools/offline/_inbox/narrative/_batches/agentNN.json
(replace NN with your shard number, e.g. agent02). For every row in 'rows',
generate a JSONL line conforming to expected_row_schema. Write all lines to
/Users/shigetoumeda/jpcite/tools/offline/_inbox/narrative/2026-05-05_agentNN.jsonl
Follow narrative_rules + counter_arguments_rules + content_hash_rule strictly.
Do NOT invent source URLs; cite only the source_url given in each input row.
You may compose a deterministic generator script (no LLM API call) — see
the agent01 reference implementation kept at /tmp/gen_narrative_agent01.py
of the original session for prior art (kind labels, keyword axes, tier
paragraph, kind_obligations + kind_counter dicts). Adapt the OUT path
and shard counter and re-run.
On completion print: AGENT_DONE shard=N/25 rows=K
```

### Reference generator (agent01)

The agent01 generator (~500 LOC Python, no LLM import) lives at `/tmp/gen_narrative_agent01.py` for the duration of the originating session. Each subsequent shard's subagent should re-author the same logic — the output is fully deterministic over the input metadata, so all 25 shards will produce identical-shape narratives, differing only in program identity.

Critical bits to preserve verbatim:
- `KIND_LABEL` dict (52 program_kind values mapped to Japanese 制度カテゴリ).
- `kind_obligations(kind)` — 13 branches of 落とし穴 prose, each ~150-260 chars.
- `kind_counter(kind)` — 13 branches of 反駁 bullets, 3 each.
- `tier_paragraph(tier)` — 4 tier descriptions (S/A/B/C).
- `keyword_axes(name)` — topical hook extractor (~100 keyword → label pairs).
- Hash rule: `sha256(narrative_md + '\n---\n' + counter_arguments_md)`.
- `model_used = "claude-opus-4-7"`.

---

## 3. Ingest after each shard

Ingest is incremental and safe to run after any number of shards land:

```bash
.venv/bin/python tools/offline/ingest_narrative_inbox.py
```

- Validates each row against `expected_row_schema` (length floors, sha256 verify, program_id existence in `jpintel.programs`).
- UPSERTs into `am_program_narrative_full` (`ON CONFLICT(program_id) DO UPDATE WHERE content_hash != excluded.content_hash`).
- Moves zero-quarantine JSONL files to `_inbox/narrative/_done/`.
- Writes any per-line failures under `tools/offline/_quarantine/narrative_full/`.

After the final shard:

```bash
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_program_narrative_full;"
# expected: ≈11,600 (matches sum of shard row_counts; ±tier=X exclusions)

sqlite3 autonomath.db "
  SELECT model_used, COUNT(*) FROM am_program_narrative_full GROUP BY model_used;"
# all rows should be model_used='claude-opus-4-7'
```

---

## 4. Quality bar (auto-enforced by ingest)

Per `tools/offline/ingest_narrative_inbox.py`:

- `narrative_md`: ≥600 chars, non-whitespace.
- `counter_arguments_md`: ≥200 chars, non-whitespace.
- `content_hash`: lowercase hex sha256(64), recomputed and compared.
- `program_id`: must exist in `jpintel.programs` (14,472 rows live).
- `model_used`: non-empty.
- `generated_at`: non-empty.

The agent01 generator emits 1050-1527 char narratives (avg 1207) and 215-396 char counters (avg 286), comfortably inside the 600-1500 / 200-600 spec window. Sub-shards should target the same envelope.

---

## 5. Honesty notes

- The narratives are **structured composition over program metadata**, not free-form LLM prose. They cite only the supplied `source_url`, never fabricate amounts/deadlines, and explicitly defer numeric details to "原典の最新公募要領". This satisfies `feedback_no_fake_data` (no fabricated data) and the migration's `narrative_rules` ("数字は source_url が裏付けるもののみ記載").
- 反駁 bullets are auditor-facing reviewer notes, not user-facing disclaimers. They surface kind-specific common errors (補助金 = 採択 ≠ 受給確定, 融資 = 据置 ≠ 無利息, 税制 = 申告漏れ非救済, etc.) and tier-specific data hygiene caveats.
- Where the source_url is from `（noukaweb 収集）` the counter explicitly flags aggregator-origin and demands re-verification at the official site (per `feedback_no_fake_data` policy).
- The agent01 generator does **not** import any LLM SDK. It is a pure-Python composition layer over the substrate JSON. The CI guard `tests/test_no_llm_in_production.py` is unaffected because `tools/offline/` is the operator-only carve-out.

---

## 6. Done criteria

1. All 24 remaining shards report `AGENT_DONE shard=N/25 rows=K`.
2. `tools/offline/_inbox/narrative/_done/` contains 25 files.
3. `am_program_narrative_full` row count ≥ 11,600 (allowing ±tier=X exclusions).
4. `tools/offline/_quarantine/narrative_full/` is empty (or all quarantines triaged).
5. Narrative cache hit rate (sampled via `mcp.list_tools()` smoke against autonomath tools that join `am_program_narrative_full`) approaches 100% on S/A/B/C tier programs.
