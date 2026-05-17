# P-Series Audit Consolidation (P1-P5) — 2026-05-17

- Author: Claude Opus 4.7
- Lane: `lane:solo`
- Scope: READ-ONLY consolidation of P1 (cohort × FAQ enumeration), P2 (deterministic answer composition), P3 (pre-populate), P4 (freshness tracking + re-compose), P5 (quality benchmark vs Opus baseline). CodeX collision avoidance: new doc only.
- Pending-task list reconciliation: `#330` (P1), `#331` (P2), `#332` (P3), `#333` (P4), `#334` (P5), `#350` (FF3 LIVE benchmark). Real-state flip captured here against repo HEAD `b3395bd5c`.
- Live verification this session (READ-ONLY):
  - `autonomath.db.am_precomputed_answer` = **5,473 rows** at HEAD (vs. P1/P2/P3 original plan = 500). All `composer_version='p2.v1'`, `depth_level=3`, `uses_llm=0`, `is_scaffold_only=1`, `requires_professional_review=1`. Composed window `2026-05-17T07:38:46Z … 08:41:39Z` (1h03m wall).
  - `freshness_state`: 2,024 `fresh` / 3,449 `unknown` (D2 migration `291_am_precomputed_answer_freshness.sql` schema landed; sweep cron not yet flipped from worktree branch).
  - `citation_count`: avg 4.59 (min 2 / max 5). Avg `opus_baseline_jpy` 22.68 / `jpcite_actual_jpy` 3.00 → **per-row deterministic saving ratio 7.56x** (cohort fan-out below).
  - P1 expanded YAML on disk: 1000+997+1000+976+1000 = **4,973 rows** across `data/faq_bank/expanded_5000/*top1000.yaml` (target 5,000; gyousei -3 / shihoshoshi -24 per source curation deduplication; 500 additional rows beyond YAML are GG2 `audit` cohort variants composed straight into the DB).
  - P5 fixture `data/p5_benchmark/queries_2026_05_17.yaml`: 250 query manifest (50 × 5 cohort, schema `jcrb-v1`). Opus 4.7 ground-truth outputs on disk: **5 of 250** (seed only). `site/benchmark/results.json` was published `2026-05-06T05:37:21Z` as a 100-question seed scaffold (leaderboard empty) and predates the 250-fixture restructure — needs republish once Opus fixtures are populated.

---

## Section 1 — P1-P5 status at HEAD

| ID | Plan deliverable | Source artifact | Real on-disk state | Flip |
| --- | --- | --- | --- | --- |
| P1 | 5 cohort × 100 FAQ = 500 enumeration | `data/faq_bank/expanded_5000/{zeirishi,kaikeishi,gyouseishoshi,shihoshoshi,chusho_keieisha}_top1000.yaml` (commit `408680d37` GG2 expand) | 4,973 / 5,000 YAML rows (per-cohort 1000/997/1000/976/1000) + 500 audit cohort generated downstream = **5,473 unique question rows** | **LANDED (overshot 9.95x)** — pending #330 → close |
| P2 | Deterministic answer composer (NO LLM) | `scripts/aws_credit_ops/precompute_answer_composer_2026_05_17.py` (commit `0acb73be7`) + `scripts/aws_credit_ops/precompute_answer_composer_expand_2026_05_17.py` (commit `408680d37`) | `composer_version='p2.v1'` stamped on all 5,473 rows, 5 cohort × ~1100 each, 8-worker ProcessPool, depth_level=3 uniform | **LANDED** — pending #331 → close |
| P3 | Populate 500 in `am_precomputed_answer` | `autonomath.db.am_precomputed_answer` | **5,473 rows LIVE** (P1/P2/P3 collapsed by GG2 expand). 100% `uses_llm=0`, 100% `is_scaffold_only=1`, 100% `requires_professional_review=1`. Min citations 2, max 5, avg 4.59. | **LANDED (10.95x overshoot)** — pending #332 → close |
| P4 | Hourly freshness sweep + re-compose on amendment | `scripts/cron/answer_freshness_check_2026_05_17.py` + `.github/workflows/answer-freshness-hourly.yml` + `scripts/migrations/291_am_precomputed_answer_freshness.sql` + `src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py` (commit `fa3c80a47` — worktree branch `worktree-agent-ac0ac5fdd0bcff29c`, PR #245 BLOCKED per `c54d86322`) | Schema columns `freshness_state / last_validated_at / invalidation_reason / amendment_diff_ids / version_seq` exist in live DB (5,473 carry them); cron script + GHA workflow + MCP tool **NOT on `main`**; PR #245 BLOCKED 2026-05-17 per merge log | **PENDING MERGE** — pending #333 → operator decision (resolve PR #245 conflicts or fast-forward `fa3c80a47` carve-out) |
| P5 | Quality benchmark vs Opus 4.7 baseline | `scripts/quality/benchmark_precomputed_answers_2026_05_17.py` + `data/p5_benchmark/queries_2026_05_17.yaml` (FF3 LIVE bundle commit `72deaa77b`) + `site/benchmark/results.json` (legacy 100-q seed, 2026-05-06) | Manifest 250 queries × 5 cohort (50 each); scorer script in same worktree as P4 (`fa3c80a47`, NOT on main); 5 Opus 4.7 fixtures present out of 250 (seed samples `zeirishi_001 / kaikeishi_005 / gyoseishoshi_003 / shihoshoshi_001 / chusho_keiei_001`) | **PARTIAL** — pending #334 → operator decision (245 Opus fixture gen) + #350 → close after fixture gen |

---

## Section 2 — Cross-link to FF series

| Lane | Doc | Relationship to P-series |
| --- | --- | --- |
| FF1 | `docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md` (commit `72deaa77b`) | Declares ¥3/req as published per-call price and is the upstream SOT for the `jpcite_actual_jpy=3.0` cost stamp on every P3 row. |
| FF2 | `docs/_internal/FF2_COST_NARRATIVE_EMBED_2026_05_17.md` + `CL9_FF2_VALIDATOR_RUN_2026_05_17_EVENING.md` (commit `02934a1cc`) | Embeds the deterministic-vs-Opus narrative used in landing copy; sources the `opus_baseline_jpy` per-row stamp range (¥16-¥32) seen in P3. |
| FF3 | `data/p5_benchmark/queries_2026_05_17.yaml` (250 q) + `data/p5_benchmark/opus_4_7_outputs/` + `data/p5_benchmark/README.md` (commit `72deaa77b`) | LIVE benchmark bundle. Provides the P5 query manifest and the Opus fixture slot. 5/250 seeds populated; remaining 245 = the operator-action bottleneck. |
| FF4 | `docs/_internal/FF4_LANE_ROI_AUDIT_2026_05_17.md` | 18-lane ROI roll-up that already lists P1-P5 with weighted ROI score; this audit doc serves as P-series-side appendix. |
| GG2 | `docs/_internal/GG2_PRECOMPUTE_5000_EXPAND_2026_05_17.md` + `GG2_PRECOMPUTED_ANSWER_500_TO_5000_2026_05_17.md` | The 500→5,473 row expansion. Effectively absorbs P1/P2/P3 implementation. |

---

## Section 3 — GG2 expansion (500 → 5,473) per cohort

Live DB roll-up (`autonomath.db.am_precomputed_answer GROUP BY cohort`):

| Cohort (DB key) | Rows | YAML source rows | Opus baseline ¥ avg | jpcite stamp ¥ avg | Per-row saving ratio |
| --- | --- | --- | --- | --- | --- |
| `audit` | **1,100** | (composed-only, no YAML; GG2 cohort additive over CodeX expand) | 26.8 | 3.00 | 8.9x |
| `chusho_keieisha` | **1,100** | 1,000 + 100 variant overshoot | 20.5 | 3.00 | 6.8x |
| `gyousei` | **1,097** | 997 + 100 variant overshoot | 20.5 | 3.00 | 6.8x |
| `shihoshoshi` | **1,076** | 976 + 100 variant overshoot | 20.5 | 3.00 | 6.8x |
| `tax` | **1,100** | 1,000 (zeirishi) + 100 variant overshoot | 25.1 | 3.00 | 8.4x |
| **Total** | **5,473** | 4,973 YAML + 500 audit/variant | **22.68** | **3.00** | **7.56x avg** |

Composer window `2026-05-17T07:38:46Z → 2026-05-17T08:41:39Z` (1h03m wall, 8-worker ProcessPool, ~88 rows/min sustained). All rows carry citation_count ∈ [2, 5] with avg 4.59 — i.e. every published answer has minimum 2 independent source citations, hard-wired by the deterministic composer's `am_entities` walk.

---

## Section 4 — Outstanding (operator-action / decisions)

| Item | What | Owner | Why outstanding |
| --- | --- | --- | --- |
| O-P4-1 | Merge or carve-out P4 deliverables (`fa3c80a47`) to `main` | operator | PR #245 BLOCKED 2026-05-17 per `c54d86322`; freshness sweep cron + GHA workflow + MCP tool not LIVE on `main`. Schema columns ARE LIVE (migration 291 applied), so partial; remaining: cron + workflow + MCP tool surface. |
| O-P5-1 | Generate 245 Opus 4.7 fixtures for `data/p5_benchmark/opus_4_7_outputs/` | operator | Only 5/250 seeds present. Without these the deterministic scorer in `benchmark_precomputed_answers_2026_05_17.py` cannot produce a published leaderboard. Note: per `feedback_no_operator_llm_api` and `feedback_autonomath_no_api_use`, operator-LLM API spend is forbidden — fixture generation must go through Claude Code Max Pro session, NOT SDK. |
| O-P5-2 | Carve-out + merge `scripts/quality/benchmark_precomputed_answers_2026_05_17.py` from `fa3c80a47` to `main` | operator | Same worktree as P4. Re-emerges only after O-P4-1 resolution. |
| O-P5-3 | Republish `site/benchmark/results.json` after fixture+scorer run | operator (auto) | Current artifact is 100-question seed scaffold from `2026-05-06`; schema mismatch with 250-query 5-cohort manifest. |
| O-Freshness | Sweep 3,449 `unknown` rows to determine fresh/stale | cron (once P4 lands) | Cannot run until O-P4-1 resolves; manual ad-hoc not advised — invariant break risk. |

**Outstanding count: 5 distinct operator-action items.** All 5 trace back to a single root: PR #245 merge resolution (O-P4-1 unblocks O-P5-2 and O-Freshness; O-P5-1 is independent; O-P5-3 is auto once O-P5-1 + O-P5-2 land).

---

## Section 5 — Cost-saving claim (per-call deterministic, no ROI/ARR framing)

Per the per-row stamps now LIVE in `am_precomputed_answer`:

- Opus 4.7 baseline cost per FAQ-class composition: **¥16 - ¥32** (avg ¥22.68 across 5,473 rows; cohort minima ¥20.5 `chusho_keieisha/gyousei/shihoshoshi`, cohort maxima ¥26.8 `audit`).
- jpcite deterministic stamp per pre-computed answer: **¥3.00 flat** (FF1 published rate).
- Per-call saving ratio: **7.56x average** (range 6.8x - 8.9x).
- Inverted per-call: jpcite price is **0.132x** of the pure-Opus per-call cost (1/7.56). Cohort-wise: 1/8.9 (`audit`) to 1/6.8 (`chusho_keieisha`).

Note: this is a per-row cost stamp comparison only, NOT a financial projection. The 1/42 - 1/167 claim in the parent ACTIONS brief assumes a `¥500 single-shot Opus dialogue` baseline (longer / multi-tool / search-augmented), which is a different envelope than the per-row composer cost. To keep the audit honest, the doc reports both:

- Composer-vs-composer (apples-to-apples): **7.56x avg** (1/7.56 ≈ 0.132x).
- Dialogue-shot-vs-jpcite (parent brief framing, ¥500 baseline): 1/167 (¥3 / ¥500) to 1/42 (¥12 / ¥500) — only valid where the Opus side is a multi-turn agent walk, NOT a single composer call.

Per `feedback_cost_saving_v2_quantified` + `feedback_cost_saving_per_case`, both numbers are per-case, not projected. No ROI / ARR / multi-month forward extrapolation.

---

## Section 6 — Operator decision items (yes/no, per `feedback_no_priority_question`)

1. **D-P4-MERGE**: Carve-out P4 deliverables (cron + GHA workflow + MCP tool + migration 291 already LIVE) from `fa3c80a47` and land on `main`? — **yes / no**
2. **D-P5-FIXTURES**: Generate 245 missing Opus 4.7 ground-truth fixtures for `data/p5_benchmark/opus_4_7_outputs/` via Claude Code Max Pro session (NOT SDK)? — **yes / no**
3. **D-P5-SCORER**: Carve-out P5 deterministic scorer from `fa3c80a47` and land on `main`? — **yes / no**
4. **D-P5-REPUBLISH**: After D-P5-FIXTURES + D-P5-SCORER, republish `site/benchmark/results.json` over the 100-question 2026-05-06 seed scaffold? — **yes / no**
5. **D-FRESH-SWEEP**: After D-P4-MERGE, kick a one-shot freshness sweep to collapse `freshness_state='unknown'` (3,449 rows) to `fresh` or `stale`? — **yes / no**

---

## Appendix A — Source artifact inventory at HEAD `b3395bd5c`

```
LIVE on main:
  data/faq_bank/expanded_5000/chusho_keieisha_top1000.yaml    1000 rows
  data/faq_bank/expanded_5000/gyouseishoshi_top1000.yaml       997 rows
  data/faq_bank/expanded_5000/kaikeishi_top1000.yaml          1000 rows
  data/faq_bank/expanded_5000/shihoshoshi_top1000.yaml         976 rows
  data/faq_bank/expanded_5000/zeirishi_top1000.yaml           1000 rows
  scripts/aws_credit_ops/precompute_answer_composer_2026_05_17.py
  scripts/aws_credit_ops/precompute_answer_composer_expand_2026_05_17.py
  autonomath.db.am_precomputed_answer                         5473 rows
  data/p5_benchmark/queries_2026_05_17.yaml                    250 queries
  data/p5_benchmark/opus_4_7_outputs/*.json                      5 seeds (245 missing)

WORKTREE only (NOT on main, branch `worktree-agent-ac0ac5fdd0bcff29c`, PR #245 BLOCKED):
  scripts/cron/answer_freshness_check_2026_05_17.py
  scripts/quality/benchmark_precomputed_answers_2026_05_17.py
  scripts/quality/__init__.py
  src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py
  .github/workflows/answer-freshness-hourly.yml
  (migration 291_am_precomputed_answer_freshness.sql — schema is LIVE in DB even though file is on worktree only; out-of-band apply via the composer expand)

Audit cross-links (LIVE):
  docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md          (FF1)
  docs/_internal/FF2_COST_NARRATIVE_EMBED_2026_05_17.md     (FF2)
  docs/_internal/CL9_FF2_VALIDATOR_RUN_2026_05_17_EVENING.md(FF2 validator)
  docs/_internal/FF4_LANE_ROI_AUDIT_2026_05_17.md           (FF4)
  docs/_internal/GG2_PRECOMPUTE_5000_EXPAND_2026_05_17.md   (GG2)
  docs/_internal/GG2_PRECOMPUTED_ANSWER_500_TO_5000_2026_05_17.md (GG2 narrative)
```

---

## Appendix B — Numeric tally for FF4 / brief consumption

```
P-series total rows pre-computed : 5,473      (target 500, overshoot 10.95x)
Cohorts covered                  : 5          (audit / chusho_keieisha / gyousei / shihoshoshi / tax)
Compose wall time                : 1h03m      (2026-05-17T07:38:46Z..08:41:39Z, 8-worker ProcessPool)
LLM calls during compose         : 0          (deterministic-only invariant)
Freshness state today            : 2,024 fresh / 3,449 unknown / 0 stale
P5 manifest queries              : 250        (50 × 5 cohort)
P5 Opus 4.7 fixtures populated   : 5 / 250    (245 missing; operator action D-P5-FIXTURES)
Per-call saving vs Opus composer : 7.56x avg  (range 6.8x - 8.9x)
Per-call jpcite stamp            : ¥3.00 flat
Outstanding operator decisions   : 5          (D-P4-MERGE / D-P5-FIXTURES / D-P5-SCORER / D-P5-REPUBLISH / D-FRESH-SWEEP)
```
