# Wave 48 — x402 full payment chain PR (tick#6)

- **Branch**: `feat/jpcite_2026_05_12_wave48_x402_full_payment_chain`
- **Lane**: `/tmp/jpcite-w48-x402-payment.lane` (atomic mkdir claim per
  `feedback_dual_cli_lane_atomic`)
- **Worktree**: `/tmp/jpcite-w48-x402-payment` (detached from `origin/main`)
- **PR**: (filled by `gh pr create` step below)

## Goal

Close the implementation gap between Wave 47 Dim V x402 *storage* (migration
282 `am_x402_endpoint_config` + `am_x402_payment_log`) and a working
in-process **HTTP 402 → proof verify → 200** chain that tests and dev
callers can exercise without an RPC dependency.

## Surface

### 1. `src/jpintel_mcp/api/x402_payment.py` (~370 LOC)

- `X402PaymentMiddleware` — Starlette middleware that gates registered
  endpoints behind HTTP 402.
- `build_challenge`, `_expected_proof`, `_record_payment` — proof factory,
  sha256 verify primitive, append-only audit insert.
- Diagnostic router (3 endpoints under `/v1/x402`):
  - `GET /payment/preview?endpoint_path=...` → fresh 402 challenge
  - `GET /payment/quote?endpoint_path=...&payer_address=...&challenge_nonce=...`
    → expected proof string (dev helper).
  - `GET /payment/log/recent?limit=20` → recent settled payments.

### 2. 5 gated endpoints (from `am_x402_endpoint_config` seed)

| Path                    | Required USDC | Owner          |
| ----------------------- | ------------- | -------------- |
| `/v1/search`            | 0.001         | search router  |
| `/v1/programs`          | 0.001         | programs       |
| `/v1/cases`             | 0.001         | case_studies   |
| `/v1/audit_workpaper`   | 0.001         | audit_workpaper |
| `/v1/semantic_search`   | 0.001         | semantic_search |

The middleware passes through any path NOT in `am_x402_endpoint_config`.

### 3. `tests/test_x402_payment_chain.py` (~400 LOC, 19 tests)

Layered scenarios:

1. No header → 402 + challenge payload
2. Header without payer → 401 missing_payer_or_nonce
3. Header without nonce → 401
4. Wrong proof → 402 + verify_failed (NOT 401)
5. Valid proof → 200 + payment_id + audit row
6. Same for all 5 gated paths
7. Replay same txn_hash → idempotent (1 audit row only)
8. Non-gated path → pass-through 200
9. Diagnostic `preview` → 200 challenge / 404 for unregistered
10. Diagnostic `log/recent` → settled rows visible
11. Middleware ordering: x402 sits AFTER Idempotency, BEFORE RateLimit
12. Router included in main.py
13. LLM-0 verify (zero anthropic/openai/google.generativeai imports)
14. Brand discipline (no 税務会計AI / zeimu-kaikei.ai literal)
15. Proof determinism (same args → same sha256)
16. Proof varies with payer
17. Nonce randomness (50 fresh → 50 distinct)

## Wire (`src/jpintel_mcp/api/main.py`)

```
# import (≈ L62-65)
from jpintel_mcp.api.x402_payment import (
    X402PaymentMiddleware,
    router as x402_payment_router,
)

# middleware add (≈ L1573, after IdempotencyMiddleware, before RateLimit)
app.add_middleware(X402PaymentMiddleware)

# router include (≈ L2473, after billing_v2_router)
app.include_router(x402_payment_router)
```

Middleware ordering: Starlette processes middleware LIFO of registration
order, so the LATER-added X402PaymentMiddleware runs BEFORE the
EARLIER-added IdempotencyMiddleware. That places the proof-verify check
ahead of the Idempotency-Key cache (so a 402 challenge can never be
cached as the idempotent reply for a later valid proof) but behind the
rate-limit gate (so a 429'd request never burns a fresh challenge nonce).

## Verify (bag-of-bytes)

```
$ ruff check src/jpintel_mcp/api/x402_payment.py tests/test_x402_payment_chain.py
All checks passed!

$ PYTHONPATH=src pytest tests/test_x402_payment_chain.py -q
...................                                                      [100%]
19 passed in 1.12s

$ grep -E "import (anthropic|openai|google\.generativeai)" \
       src/jpintel_mcp/api/x402_payment.py tests/test_x402_payment_chain.py
(no output)

$ python -c "from jpintel_mcp.api import main; print('main module OK')"
main module OK
```

## Hard constraints honoured

- NO real USDC on-chain call (mock sha256 proof only).
- NO secret touched (sftp / Fly secret / `.env.local` read-only).
- NO `rm` / `mv` on tracked files.
- NO main worktree edit (all work in `/tmp/jpcite-w48-x402-payment`).
- NO legacy brand literal (税務会計AI / zeimu-kaikei.ai) in new code.
- NO LLM SDK import (`feedback_no_operator_llm_api`).
- Reads only canonical `am_x402_*` tables; never writes to
  `x402_tx_bind` (owned by `billing_v2.x402_issue_key`).

## Next ticks

- Edge wiring: `functions/x402_handler.ts` should forward real on-chain
  proofs to the origin via the same `X-Payment-*` header contract.
- OpenAPI export: the 3 diagnostic endpoints under `/v1/x402` plus the
  402 response shape on the 5 gated paths should land in
  `site/openapi.json` (a follow-up tick).
- Stripe / ACP rail parity: equivalent `acp_payment.py` chain so callers
  can switch rails without changing URL.
