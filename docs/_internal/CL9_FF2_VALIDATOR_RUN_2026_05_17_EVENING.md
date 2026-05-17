# CL9 — FF2 Cost-Saving Validator Run + Drift Sweep (Evening 2026-05-17)

> Read-only full-surface scan of the FF2 cost-saving consistency invariant.
> Identification only — drift fixes are scheduled on a separate lane
> (CL / CodeX), per CL9 dispatch directive.

Status: **DRIFT DETECTED** (351 errors on 2 newly-landed OpenAPI surfaces).
Lane: `lane:solo` (read-only). Author: jpcite operator (Bookyou株式会社).
Cross-ref: `scripts/validate_cost_saving_claims_consistency.py` (FF2 gate),
`docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md` (SOT §3).

---

## 1. Validator output (summary line)

```text
FF2 consistency check: SOT(ok=1, err=0); MCP(tools=465, err=0);
OpenAPI(ops=766, err=351); agents.json(checks=4, err=0); TOTAL_ERR=351
```

Expected: `TOTAL_ERR=0`. Observed: **TOTAL_ERR=351** — gate **FAIL**.

### 1.1 Breakdown by store

| Store | Items checked | Errors | Status |
|---|---:|---:|---|
| SOT doc (`docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md`) | 1 | 0 | PASS |
| MCP tool description footers (4 manifests, 465 tool entries) | 465 | 0 | PASS |
| OpenAPI `x-cost-saving` extensions | 766 ops | 351 | **FAIL** |
| `site/.well-known/agents.json#cost_efficiency_claim` | 4 checks | 0 | PASS |

OpenAPI is the **sole drift store**. All other surfaces are consistent.

---

## 2. Drift identification (OpenAPI-only)

### 2.1 By file

```text
317 errors  site/docs/openapi/v1.json     (317 ops, 0 with x-cost-saving)
 34 errors  site/docs/openapi/agent.json  ( 34 ops, 0 with x-cost-saving)
---
351 total
```

Both files have **zero** `x-cost-saving` extensions on any operation.

### 2.2 Comparator: working OpenAPI mirrors

For contrast, the older mirrors (which the FF2 wave originally instrumented)
still pass:

| OpenAPI file | Ops | with `x-cost-saving` | Status |
|---|---:|---:|---|
| `site/openapi/v1.json` | 317 | **317** | PASS |
| `site/openapi/agent.json` | 34 | **34** | PASS |
| `site/docs/openapi/v1.json` | 317 | 0 | **MISS** |
| `site/docs/openapi/agent.json` | 34 | 0 | **MISS** |

The newer `site/docs/openapi/*.json` surfaces are mirrors landed by a later
wave; they were generated without the FF2 extension wiring. The validator
(`OPENAPI_TARGETS` in `scripts/validate_cost_saving_claims_consistency.py`
lines 59–66) scans them, so they trigger 351 drift errors despite the
narrative being unchanged.

### 2.3 Drift before/after (per operation)

For every operation in `site/docs/openapi/v1.json` and
`site/docs/openapi/agent.json`:

```text
before (current):  operation has no "x-cost-saving" key
after  (expected): operation has "x-cost-saving": {
                     tier: A|B|C|D,
                     yen: 3|6|12|30,
                     opus_turns: 3|5|7|7,
                     opus_yen: 54|170|347|500,
                     saving_pct: 94.4|96.5|96.5|94.0,
                     saving_yen: 51|164|335|470
                   }
```

Per-op fix is a copy of the matching tier block from the
`site/openapi/v1.json` / `site/openapi/agent.json` siblings (same path key).

Representative missing entries (first 10 of 351):

```text
site/docs/openapi/v1.json::GET /citation/{request_id}
site/docs/openapi/v1.json::GET /healthz
site/docs/openapi/v1.json::GET /readyz
site/docs/openapi/v1.json::GET /v1/a2a/agent_card
site/docs/openapi/v1.json::GET /v1/a2a/skills
site/docs/openapi/v1.json::POST /v1/a2a/skills/negotiate
site/docs/openapi/v1.json::GET /v1/a2a/skills/{skill_name}
site/docs/openapi/v1.json::POST /v1/a2a/task
site/docs/openapi/v1.json::GET /v1/a2a/task/{task_id}
site/docs/openapi/v1.json::GET /v1/agent_card
```

Full enumerated list reproducible via:

```bash
.venv/bin/python scripts/validate_cost_saving_claims_consistency.py 2>&1
```

---

## 3. Spot-check results (other surfaces)

### 3.1 SOT canonical (`docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md`)

| Tier | yen | opus_turns | opus_yen | saving_pct | saving_yen | Match SOT? |
|---|---:|---:|---:|---:|---:|---|
| A | 3 | 3 | 54 | 94.4 | 51 | PASS |
| B | 6 | 5 | 170 | 96.5 | 164 | PASS |
| C | 12 | 7 | 347 | 96.5 | 335 | PASS |
| D | 30 | 7 | 500 | 94.0 | 470 | PASS |

Matches CL9 directive expected quintuple **exactly**.

### 3.2 MCP tool description footer (random sample, n=10)

Random seed 42, sampled from `mcp-server.full.json` (184 tools total in that
manifest; 4 manifests scanned by validator yield 465 footers checked).

| Tool name | `¥3/¥6/¥12/¥30` marker | `Opus` marker | Footer? |
|---|---|---|---|
| get_am_tax_rule | yes | yes | PASS |
| search_bids | yes | yes | PASS |
| get_usage_status | yes | yes | PASS |
| supplier_chain_am | yes | yes | PASS |
| session_multi_step_eligibility_chain | yes | yes | PASS |
| check_enforcement_am | yes | yes | PASS |
| audit_batch_evaluate | yes | yes | PASS |
| get_court_decision | yes | yes | PASS |
| temporal_compliance_audit_chain | yes | yes | PASS |
| recommend_similar_case | yes | yes | PASS |

10/10 PASS. Validator MCP store err=0 (465/465).

### 3.3 OpenAPI `x-cost-saving` extension — working mirror sample

`site/openapi/v1.json` 317 ops × `x-cost-saving` present = 317/317 PASS.
Sample (10 ops, none missing): all FF2-shaped.

### 3.4 `llms.txt` "Cost saving claim (machine readable)" section

`site/llms.txt` quotes:

- Tier A (¥3 / req) ≈ 3-turn Opus 4.7 (~¥54). Saving 94.4% / ¥51 / req — **match**.
- Tier B (¥6 / action) ≈ 5-turn (~¥170). Saving 96.5% / ¥164 — **match**.
- Tier C (¥12 / action) ≈ 7-turn deep (~¥347). Saving 96.5% / ¥335 — **match**.
- Tier D (¥30 / action) ≈ 7-turn deep+ (~¥500). Saving 94.0% / ¥470 — **match**.

llms.txt = PASS.

### 3.5 `site/.well-known/agents.json#cost_efficiency_claim`

```json
{
  "vs_baseline": "Claude Opus 4.7 / 7-turn evidence-gathering chain",
  "baseline_yen_per_query": 500,
  "jpcite_yen_per_query_range": [3, 30],
  "saving_ratio_min": 17,
  "saving_ratio_max": 167,
  "tiers": {
    "A": {"jpcite_yen": 3,  "opus_equiv_turns": 3, "opus_equiv_yen": 54,
          "saving_pct": 94.4, "saving_yen": 51 },
    "B": {"jpcite_yen": 6,  "opus_equiv_turns": 5, "opus_equiv_yen": 170,
          "saving_pct": 96.5, "saving_yen": 164},
    "C": {"jpcite_yen": 12, "opus_equiv_turns": 7, "opus_equiv_yen": 347,
          "saving_pct": 96.5, "saving_yen": 335},
    "D": {"jpcite_yen": 30, "opus_equiv_turns": 7, "opus_equiv_yen": 500,
          "saving_pct": 94.0, "saving_yen": 470}
  }
}
```

All 4 tiers match SOT quintuple. Validator agents.json store err=0 (4/4).

### 3.6 `site/pricing.html` (4-tier table)

`¥3/billable unit` per-page marker found ×12; tier ¥3/¥6/¥12/¥30 surface
present in title, description, hero, FAQ. Narrative consistent with SOT
(headline ¥3, tier B/C/D inferred from `pricing.html` mid-page table
synthesised on render). pricing.html = PASS (no validator-gated surface
here; consistency is by inspection).

---

## 4. Conclusion + next-lane handoff

- Narrative SOT is intact (¥3/¥6/¥12/¥30, 3/5/7/7 turns, 54/170/347/500 Opus
  ¥, 94.4/96.5/96.5/94.0 %, 51/164/335/470 ¥ saving) and **all
  customer-facing surfaces except 2 OpenAPI mirrors** report the same
  quintuple.
- The 2 drift files are `site/docs/openapi/v1.json` and
  `site/docs/openapi/agent.json` — both with **zero** `x-cost-saving`
  extensions. These were landed by a later wave that did not re-run the FF2
  extension-embedder.
- Drift fix is **out of scope for this lane (CL9 lane:solo, read-only)**.
  Suggested fix recipe for the follow-up lane:
  1. Re-run `scripts/ff2_embed_cost_saving_footer.py`
     (or the OpenAPI-specific sibling) over `site/docs/openapi/*.json`.
  2. Tier classification per operation can be copied from the existing
     `site/openapi/v1.json` / `site/openapi/agent.json` siblings keyed by
     `(path, method)`.
  3. Re-run the validator until `TOTAL_ERR=0`.

This audit makes no edits to validator-scanned surfaces. Only this new
audit document is added.

---

## 5. Reproducibility

```bash
cd /Users/shigetoumeda/jpcite
.venv/bin/python scripts/validate_cost_saving_claims_consistency.py 2>&1 | head -1
# → FF2 consistency check: SOT(ok=1, err=0); MCP(tools=465, err=0);
#   OpenAPI(ops=766, err=351); agents.json(checks=4, err=0); TOTAL_ERR=351

.venv/bin/python scripts/validate_cost_saving_claims_consistency.py 2>&1 \
  | grep -oE "site/docs/openapi/[^:]+" | sort | uniq -c
#  → 34 site/docs/openapi/agent.json
#   317 site/docs/openapi/v1.json
```
