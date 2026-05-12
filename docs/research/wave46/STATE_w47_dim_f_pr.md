# Wave 47 Phase 2 tick#6 — Dim F fact_signature storage extension (mig 285)

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave47_dim_f_migration`
Worktree: `/tmp/jpcite-w47-dim-f-mig`
Lane: `/tmp/jpcite-w47-dim-f-mig.lane`
Base: `origin/main` @ `cd5b7bbfb` (HEAD: Dim T mig 280 landed)
Author: Wave 47 Phase 2 永遠ループ tick#6

## What this PR does

Adds **migration 285** as a **purely additive extension** to mig 262
(`am_fact_signature`) per `feedback_explainable_fact_design.md`. Lands
two new tables + one helper view, an Ed25519-verifying bridge ETL,
and a 14-case integration test.

| Artefact                                                       | Role                                                                                                                                                                    |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/migrations/285_fact_signature_v2.sql`                 | TWO new tables on top of mig 262: `am_fact_signature_v2_attestation` (signature_id PK, fact_id, signer_pubkey, signature_bytes, signed_at) and `am_fact_signature_v2_revocation_log` (revoke_id PK, signature_id FK, reason_class CHECK enum, revoked_at, revoked_by). Plus helper view `v_am_fact_sig_v2_attestation_active`. Indexes for (fact_id, signed_at DESC), (signer_pubkey, signed_at DESC), (key_id), unique triplet, revocation lookup. |
| `scripts/migrations/285_fact_signature_v2_rollback.sql`        | Drops only the v2 tables/indexes/view. Mig 262 (`am_fact_signature`) is NEVER touched (confirmed by `test_mig_285_rollback_drops_only_v2`).                              |
| `scripts/etl/build_fact_signatures_v2.py`                      | One-shot bridge ETL. LEFT JOIN mig 262 -> mig 285 to find unbridged rows, Ed25519-verify each row against `payload_sha256` BEFORE inserting (refuse-on-fail, exit 3). Pure cryptography stdlib (Ed25519PrivateKey / Ed25519PublicKey). Cursor-paged CHUNK_SIZE=5000 walk per `feedback_no_quick_check_on_huge_sqlite`. `--dry-run` / `--max-rows N` / `--skip-verify` flags. LLM-0 by construction. |
| `tests/test_dim_f_signature_v2.py`                             | 14 cases: migration apply + idempotent re-apply, rollback safety for mig 262, 4 CHECK constraints (pubkey 64-hex, sha256 64-hex, sig 64..96 bytes), unique triplet dedup, revocation `reason_class` enum + one-per-signature, active view excludes revoked rows, boot manifest dual registration, full Ed25519 round-trip sign → INSERT → SELECT → verify, LLM-0 grep guard, legacy-brand grep guard. |
| `scripts/migrations/jpcite_boot_manifest.txt`                  | Appended `285_fact_signature_v2.sql` with explanatory header.                                                                                                            |
| `scripts/migrations/autonomath_boot_manifest.txt`              | Mirror append of the same entry.                                                                                                                                         |

## Relationship to PR #118 (round 1) and prior dim F work

PR #118 (round 1) landed the **REST file MISSING axis**:
`src/jpintel_mcp/api/fact_signature_v2.py` (277 LOC) + 7-case test.
That gave the verify endpoint a code path but the storage layer
remained the single-row-per-fact mig 262.

This PR (Wave 47 Phase 2 tick#6) closes the **storage extension axis**
that round 1 deliberately deferred — the multi-attestation +
revocation backing tables that
`feedback_explainable_fact_design.md` requires for "all fact = source +
extracted_at + verified_by + confidence 4-axis metadata + Ed25519 sign".

The two tables answer two needs round 1 couldn't:

1. **Multi-party attestation enumeration.** A single fact may be
   co-signed by operator + customer-auditor + 3rd-party notary under
   the same `payload_sha256`. mig 262 only stores ONE pointer; mig
   285 stores all rows under a unique `(fact_id, signer_pubkey,
   corpus_snapshot_id)` triplet.

2. **Explicit revocation trail.** Key rotation / key compromise /
   payload amendment now leaves an append-only row in
   `am_fact_signature_v2_revocation_log` with a `reason_class` CHECK
   enum (`key_rotated` | `key_compromised` | `payload_amended` |
   `operator_request` | `auditor_request` | `other`). The active
   view `v_am_fact_sig_v2_attestation_active` joins LEFT and filters
   `WHERE r.revoke_id IS NULL`, so verify endpoints naturally exclude
   revoked sigs without a WHERE clause in the handler.

## Verification done before this PR

* `sqlite3` syntax + idempotent re-apply + rollback verify (mig 262
  table set intact: `am_fact_signature` + `v_am_fact_signature_latest`).
* `pytest tests/test_dim_f_signature_v2.py` — **14 passed in 0.99s**.
  Includes a real Ed25519 sign → INSERT → SELECT → verify round-trip
  using `cryptography.hazmat.primitives.asymmetric.ed25519` — the
  same stdlib used by `scripts/cron/refresh_fact_signatures_weekly.py`
  in mig 262.
* `ruff check` on ETL + test — clean (no diagnostics).
* LLM-0 grep across all 4 new files — only matches are the test's
  own guard assertions / docstring (verified by inspection).
* Legacy-brand grep (`税務会計AI` / `zeimu-kaikei`) — only matches are
  the test's own guard assertions / docstring.

## Constraints honoured (per task brief)

* No overwrite of mig 262 (verified by `test_mig_285_rollback_drops_only_v2`).
* No mutation of the main worktree (lane is `/tmp/jpcite-w47-dim-f-mig`).
* No `rm` / `mv` (purely additive: 4 new files + 2 manifest appends).
* No legacy brand markers in any new file.
* No LLM API import in any new file (LLM-0 invariant preserved).
* Boot manifest registered in both `jpcite_boot_manifest.txt` and
  `autonomath_boot_manifest.txt`.

## Dim F state vector

| Axis            | Round 0 (pre #118) | Round 1 (#118)            | This PR (tick#6)                                                                       |
| --------------- | ------------------ | ------------------------- | -------------------------------------------------------------------------------------- |
| REST handler    | MISSING            | LANDED (277 LOC, 7 tests) | unchanged                                                                              |
| Storage schema  | mig 262 only       | mig 262 only              | **mig 285 added** (2 tables + 1 view, idempotent, rollback-safe)                       |
| Ed25519 verify  | sig present        | sig present               | round-trip exercised (sign + INSERT + SELECT + `Ed25519PublicKey.verify`)              |
| Revocation log  | absent             | absent                    | **landed** (`am_fact_signature_v2_revocation_log` with `reason_class` 6-value enum)    |
| Bridge ETL      | absent             | absent                    | **landed** (`build_fact_signatures_v2.py`, verify-or-refuse semantics)                 |
| Test coverage   | 7 cases (round 1)  | 7 cases (round 1)         | +14 cases here (round 1 cases unchanged)                                                |
| Boot manifest   | mig 262 only       | mig 262 only              | **mig 285 appended** to both jpcite + autonomath manifests                             |

## Next steps after merge

1. CI verify on the PR (CodeQL / lane-enforcer / acceptance / ruff /
   pytest). Lane-enforcer should accept the new mig number 285 since
   it is strictly above the current max 280.
2. Production boot — entrypoint reads the manifest and self-heals
   mig 285 onto the existing 9.7 GB autonomath.db. Pure additive so
   no impact to existing reads. No quick_check is needed (per
   `feedback_no_quick_check_on_huge_sqlite`) and none is issued.
3. One-shot bridge ETL run (out of band, on a separate tick): the
   weekly cron `refresh_fact_signatures_weekly.py` will from this
   point forward write directly into both mig 262 and mig 285. The
   bridge ETL `build_fact_signatures_v2.py` is for the historical
   backfill of pre-tick rows already in mig 262 that have no mig 285
   companion attestation. It is intentionally a one-shot tool and
   converges to zero writes once the backfill is done.
4. Wave 47 Phase 2 tick#7+ continues with the next Dim from
   `feedback_explainable_fact_design`-adjacent dimensions (Dim G
   realtime signal storage, Dim P composable tool storage adjacency).

## Files changed (count)

```
scripts/migrations/285_fact_signature_v2.sql          (new, ~156 LOC)
scripts/migrations/285_fact_signature_v2_rollback.sql (new,  ~19 LOC)
scripts/etl/build_fact_signatures_v2.py               (new, ~225 LOC)
tests/test_dim_f_signature_v2.py                      (new, ~360 LOC)
scripts/migrations/jpcite_boot_manifest.txt           (+18 LOC append)
scripts/migrations/autonomath_boot_manifest.txt       (+18 LOC append)
docs/research/wave46/STATE_w47_dim_f_pr.md            (this file, ~150 LOC)
```

Total: ~946 LOC across 7 files (4 new + 3 amended).
