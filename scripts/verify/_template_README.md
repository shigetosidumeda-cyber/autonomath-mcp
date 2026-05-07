# scripts/verify/

Per-spec verify shell scripts for the 33 DEEP specs (DEEP-22..54).

Each `deep-NN_verify.sh` fires the matching slice of `tests/test_acceptance_criteria.py`
via `pytest -k "DEEP-NN"`, so an exit code of `0` means every acceptance row for that
spec passed (RESOLVED in the DEEP-58 dashboard) and a non-zero code means at least one
acceptance row failed (BLOCKED in the dashboard).

The aggregator `scripts/cron/aggregate_production_gate_status.py` resolves each script
via the convention `scripts/verify/<spec_id.lower()>_verify.sh`, e.g. `deep-22_verify.sh`.

Constraints:
- LLM API call count = 0 (each script merely invokes the offline acceptance suite)
- Idempotent (re-running is safe)
- Non-destructive (read-only on the working tree)
