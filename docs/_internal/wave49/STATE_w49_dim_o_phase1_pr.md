# Wave 49 tick#8 — Dim O Phase 1 provenance backfill v2 + attach middleware (PR runbook)

Date: 2026-05-12 (JST)
Lane: `feat/jpcite_2026_05_12_wave49_dim_o_phase1_prov`
Worktree: `/tmp/jpcite-w49-dim-o-prov` (atomic claim `/tmp/jpcite-w49-dim-o-prov.lane`)
Parent: Wave 47 Phase 2 (migration 275 + build_explainable_fact_metadata.py landed)
Owner agent: 1 (single-lane PR)

## Context — Dim O / explainable_fact_design

Wave 47 Phase 2 shipped the 4-axis explainability substrate:

* **Migration 275** (`am_fact_metadata` + `am_fact_attestation_log` + `v_am_fact_explainability` view) lands the 4 axes:
  * `source_doc` — primary URL / corpus anchor
  * `extracted_at` — ISO-8601 UTC timestamp
  * `verified_by` — extractor / attester pipeline identifier
  * `confidence_lower`/`confidence_upper` — band in [0.0, 1.0]
* **`scripts/etl/build_explainable_fact_metadata.py` v1** — walks `am_fact_signature` (migration 262 substrate) and UPSERTs into `am_fact_metadata`, appending one row to `am_fact_attestation_log` per change.

### Gap closed by this PR

The v1 walker only covers `fact_id`s that already have an `am_fact_signature` row. A non-zero fraction of `am_entity_facts` (the 6.12M-row EAV) have NO signature yet because:

* legacy extraction pre-dates migration 262 signing;
* Wave 47 Phase 2 smoke runs used `--max-rows` and truncated;
* daily axis-3 amendment_diff_v3 / fill ETLs do not chain through `am_fact_signature`.

The Wave 49 Phase 1 v2 backfill walks `am_entity_facts` directly and writes `am_fact_metadata` rows where `source_doc IS NULL` OR no metadata row exists.

## Files added (3, additive only)

| path | LOC | purpose |
| ---- | --: | ------- |
| `scripts/etl/provenance_backfill_6M_facts_v2.py` | ~330 | Walks `am_entity_facts` in 1000-row indexed-cursor chunks (target 6,000 batches ≈ 6.12M rows). Per fact_id: derives `source_doc` via `am_source.url` join, `confidence` → ±0.05 band, `extracted_at` from row `created_at`, `verified_by = etl_prov_backfill_v2`. UPSERTs to `am_fact_metadata` + APPENDs to `am_fact_attestation_log`. Idempotent (skips rows with non-NULL `source_doc`). Ed25519 sign optional — when key env missing, deterministic 64-byte placeholder satisfies migration 275 CHECK. NO `PRAGMA quick_check` on the 9.7 GB DB. |
| `src/jpintel_mcp/api/_provenance_attach.py` | ~170 | Response middleware `attach(payload, fact_ids=None, *, db_path=None) -> dict`. Reads from `v_am_fact_explainability` view and surfaces a JSON-LD-compatible `provenance` sidecar (`@context: schema.org/`, `@type: Dataset`, `facts: [...]`). Additive — input payload not mutated. Soft-fails (no exception) on missing DB / migration / fact_id. Auto-extracts fact_ids from top-level `fact_id`, `fact_ids`, and `results[*].fact_id`. |
| `tests/test_dim_o_provenance_attach.py` | ~280 | 13 tests covering: 4-axis attach happy path, soft-fail on missing DB/fact_id/empty payload, top-level + list extraction with dedupe, ETL v2 backfill + idempotent + dry-run + placeholder-sig + real Ed25519 sign + never-touches-`am_fact_signature` regression guard + LLM SDK import regression scan + lookup helper. |

## 4-axis metadata surfaced

The middleware emits (when fact_id(s) resolve):

```json
{
  "provenance": {
    "@context": "https://schema.org/",
    "@type": "Dataset",
    "facts": [
      {
        "fact_id": "F-12345",
        "source_doc": "https://elaws.e-gov.go.jp/...",
        "extracted_at": "2026-05-12T01:23:45.000Z",
        "verified_by": "etl_build_explainable_fact_metadata_v1",
        "confidence": {"lower": 0.85, "upper": 0.95},
        "attestation_count": 3,
        "latest_signed_at": "2026-05-12T01:23:45.000Z",
        "ed25519_sig_present": true
      }
    ]
  }
}
```

## Ed25519 wiring policy

* **Same key as v1** — reuses Fly secret `AUTONOMATH_FACT_SIGN_PRIVATE_KEY` (Ed25519 32-byte seed). One key rotates for both v1 + v2 attestations + Wave 43.2.5 signing.
* **NEVER committed.** Tests cover real-key + placeholder paths in isolation; no key material lands in the repo.
* **Optional in v2.** v2 is allowed to backfill without a key so CI runs without secret leakage. Real sign happens on the next nightly v1 run (which re-UPSERTs with a real signature). The v2 placeholder is a 64-byte zero blob that still satisfies the `am_fact_metadata.ed25519_sig` length CHECK.
* **Append-only log.** Each UPSERT writes one `am_fact_attestation_log` row (`attester = etl_prov_backfill_v2`, `notes = wave49_phase1_backfill`). The chain is auditable independently of the latest signature in `am_fact_metadata`.

## Verify (local lane)

```
$ ruff check scripts/etl/provenance_backfill_6M_facts_v2.py \
             src/jpintel_mcp/api/_provenance_attach.py \
             tests/test_dim_o_provenance_attach.py
All checks passed!

$ pytest tests/test_dim_o_provenance_attach.py -q
.............  [100%]
13 passed in 1.02s
```

13/13 PASS. Ed25519 commit count = 0 (regression test enforces).

## Hard constraints honored

* No new env vars; no new external deps (cryptography already pinned by v1).
* No `PRAGMA quick_check` (9.7 GB DB footgun per `feedback_no_quick_check_on_huge_sqlite`).
* Never mutates `am_fact_signature` (Wave 43.2.5 substrate) — regression test enforces.
* Append-only attestation log; no UPDATE/DELETE on `am_fact_attestation_log`.
* No LLM SDK import in any of the 3 files (regression scan enforces).
* Soft-fail middleware: missing DB → payload returned unchanged.
* Additive JSON-LD sidecar (existing envelope fields untouched).

## Out of scope (Phase 2+)

* `/v1/facts/{fact_id}/why` REST endpoint (migration 275 doc mentions it — defer to a follow-up PR with billing wire).
* Actual 6.12M-row batch execution on autonomath.db prod (this PR ships the script; nightly cron picks it up).
* Federated MCP discovery exposing `provenance` on tool responses (Dim R intersection).

## PR title

`feat(wave49): Dim O Phase 1 — provenance backfill v2 + attach middleware (4-axis JSON-LD)`
