# Use the predicate JSON cache for token savings (renamed → use_predicate_for_certainty.md)

> **W28-9 reframe 2026-05-05**: this page is retained at the legacy slug for inbound link continuity. The canonical title is now **`use_predicate_for_certainty.md`** in the same folder — primary value reframed from "token savings" (secondary, raw token math alone is a small net loss at typical workloads per W28-4) to "verdict certainty + verify-time savings" (primary, ~30 min → ~3 min per query). Content below kept for traceability; treat the certainty doc as the source of truth.

Status: customer-facing integration brief (W26-6, 2026-05-05). Numbers below are **measured against the live `autonomath.db` snapshot** (12,753 predicate rows populated, 1 narrative-full row sampled). Per-call savings on your model + prompt are workload-dependent — see `docs/bench_methodology.md` for the paired A/B protocol.

---

## TL;DR

For "does program X cover corp Y?" eligibility checks, call **`get_program_eligibility_predicate(program_id)`** instead of re-reading the narrative MD with `get_program_narrative`. The predicate is a tiny structured JSON the LLM evaluates with boolean logic — typical token savings **50%+** vs. parsing the prose, more on bulk fan-outs.

`get_program_narrative` stays the right tool for **display** (showing the user a vetted Japanese explanation). It is **not** the right tool when the LLM only needs a verdict.

---

## 1. Why the predicate path is cheaper

| Axis | `get_program_eligibility_predicate` | `get_program_narrative` |
|---|---|---|
| Output shape | Single JSON object: `{industries_jsic, prefectures, capital_max_yen, employee_max, ...}` | Up to 4 prose sections (overview / eligibility / application_flow / pitfalls) |
| Per-program payload (measured 2026-05-05 against `autonomath.db`) | predicate_json: **min 2 B / median ≈209 B / max 2,399 B** across 12,753 rows | narrative_full sampled: **1,061 B for one program** (4-section narrative is larger, multi-row) |
| Customer LLM work | Boolean evaluation: `predicate.prefectures.includes("大阪府") && predicate.employee_max >= 10` — single-pass JSON parse | Read 4 sections, paraphrase, decide, double-check — multi-pass reasoning, hallucination repair turns |
| Output / reasoning tokens | Near-zero (verdict collapses to "対象 / 対象外 / 不明 (axis missing)") | Higher (the LLM restates the eligibility paragraph in its own words) |
| Stable across queries | Yes — keyed `program_id`, predicate is per-program | Yes for cache hits, but the LLM still re-reasons each time |

**Honest caveat**: a missing axis on the predicate means **"unknown"**, NOT **"no constraint"** (per the `notes` field on every response). That is by design — `rule_based` extraction over `jpi_programs.enriched_json` covers partial axes only. The customer LLM must verify `source_url` before any final eligibility decision (行政書士法 §1 fence). Both tools carry a `_disclaimer` envelope from W26-6 onward.

---

## 2. Same program, two paths (sample case)

Program: `UNI-001e7aa325` (秋田県 農業 program — selected because it carries a full predicate row).

**Path A — predicate-first (recommended for eligibility checks):**

```jsonc
// 1 MCP call: get_program_eligibility_predicate(program_id="UNI-001e7aa325")
// Server response payload (predicate body, ≈192 bytes for this program):
{
  "industries_jsic": ["A"],
  "prefectures": ["秋田県"],
  "prefecture_jis": ["05"],
  "crop_categories": ["facility_flower", "facility_vegetable",
                      "fruit_tree", "livestock", "open_vegetable", "paddy"]
}
// LLM verdict: prefectures includes "秋田県"? jsic A? → 対象 / 対象外 in O(1).
```

**Path B — narrative-first (re-reason from prose, NOT recommended for eligibility):**

```jsonc
// 1 MCP call: get_program_narrative(program_id="UNI-001e7aa325", section="all")
// Server response payload: up to 4 sections × hundreds-to-thousands of bytes each.
// Sampled narrative_full row: 1,061 bytes for ONE program (single-row cache).
// 4-section am_program_narrative output is larger.
// LLM verdict: read prose → paraphrase eligibility → cite → may hallucinate constraints.
```

**Token impact (estimated at the response surface for THIS program):**

- Predicate path: ~190 B JSON → ~50-80 input tokens (Japanese + ASCII mixed at jpcite_char_weighted_v1).
- Narrative path: ~1,000 B prose → ~300-450 input tokens, plus the LLM's reasoning / cite-paraphrase output overhead.
- Reduction at the response: **~50-80%** for eligibility verdicts on small predicates, larger on dense narratives.

For 100-program fan-outs (営業 funnel pre-screen), the gap compounds: predicate stays O(N × 200B), narrative grows O(N × 1KB+) and the LLM's reasoning cost compounds linearly.

---

## 3. When to use which

**Use `get_program_eligibility_predicate` when:**

- You already have a `program_id` (from `search_programs`, `list_open_programs`, `recommend_similar_program`, etc.).
- You need a verdict, not an explanation: "does corp Y match?" / "filter these 50 programs to ones that cover 大阪府 製造業 with 10 employees".
- You are fan-out screening (N programs × 1 corp). Each predicate fetch is independent and parallelizable.
- The end product is a boolean / short list, not a prose recommendation.

**Use `get_program_narrative` when:**

- You will surface the explanation to a human user (LINE bot, dashboard tooltip, email).
- You need application flow / pitfalls / overview prose, NOT just eligibility.
- The customer asked "なぜこの制度が当社に合っているのか?" — predicate cannot answer "why".

**Recommended pattern**: predicate-first to score / shortlist, narrative-second only on the survivors that the user actually wants to read.

---

## 4. Verifying the savings on your own workload

```bash
# Count how many predicates exist + size distribution.
sqlite3 autonomath.db \
  "SELECT COUNT(*), AVG(length(predicate_json)),
          MIN(length(predicate_json)), MAX(length(predicate_json))
   FROM am_program_eligibility_predicate_json;"
# 2026-05-05 snapshot: 12753 rows, avg 209.16 B, min 2 B, max 2,399 B.

# Inspect any program's predicate vs narrative size.
sqlite3 autonomath.db \
  "SELECT length(predicate_json), program_id
   FROM am_program_eligibility_predicate_json LIMIT 5;"
```

Then run your own paired A/B with the customer LLM (Opus 4.7 / Sonnet 4.7 / GPT-5.x — your choice) on a representative query set. Use the formula in `docs/integrations/token-efficiency-proof.md` §4 to convert tokens-saved to ¥-saved net of the ¥3.30/req metering fee.

---

## 5. Disclaimer surface (W26-6)

Both tools now carry a `_disclaimer` envelope (added 2026-05-05):

- `get_program_eligibility_predicate`: predicate is search-derived, missing axis = unknown not "no constraint", 行政書士法 §1 / 税理士法 §52 fence — verify primary source.
- `get_program_narrative`: pre-generated prose, NOT 申請代理 (行政書士法 §1) — and the disclaimer itself reminds the LLM to switch to the predicate tool when it only needs a verdict.

Customer LLMs that already obey the `_disclaimer` block on other sensitive tools will receive the predicate-first hint automatically on every `get_program_narrative` response.
