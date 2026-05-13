# jpcite Agent Journey 6-Step Audit — 2026-05-12

Wave 17 AX runner. ax_smart_guide §3.3 + §7. NO network, NO LLM call.

**Overall**: 9.86 / 10 (GREEN)

| step | name | score | failure patterns |
| ---: | --- | ---: | ---: |
| 1 | discovery | 9.17 | 0 |
| 2 | evaluation | 10.00 | 0 |
| 3 | authentication | 10.00 | 0 |
| 4 | execution | 10.00 | 0 |
| 5 | recovery | 10.00 | 0 |
| 6 | completion | 10.00 | 0 |

## Step 1: discovery — 9.17 / 10

### Findings

- discovery surface presence: 8/8
- AI bot welcome: 6/6 UAs in robots.txt
- MCP registry visibility: 2/3 hints

### Failure patterns (agent-visible)

- none

## Step 2: evaluation — 10.00 / 10

### Findings

- evaluation docs presence: 7/7
- 8業法 fence coverage: 8/8
- recipes: 31 (target ≥ 30)

### Failure patterns (agent-visible)

- none

## Step 3: authentication — 10.00 / 10

### Findings

- auth surface files: 3/3
- magic-link flow detected: True
- jc_-prefixed token format detected: True
- oauth surfaces wired (google + github): 2.0/2

### Failure patterns (agent-visible)

- none

## Step 4: execution — 10.00 / 10

### Findings

- openapi paths: full=300 slim_gpt30=34 (floor 180)
- error envelope + idempotency files: 2/2
- Idempotency-Key references in api/: 12

### Failure patterns (agent-visible)

- none

## Step 5: recovery — 10.00 / 10

### Findings

- 'retry_after': 22 file(s) in api/+mcp/
- 'docs_url': 4 file(s) in api/+mcp/
- 'error_code': 4 file(s) in api/+mcp/
- failure-pattern penalty: -0.0

### Failure patterns (agent-visible)

- none

## Step 6: completion — 10.00 / 10

### Findings

- 'corpus_snapshot_id': 61 file(s) in src/
- 'content_hash': 11 file(s) in src/
- idempotency_cache migration: ['122_usage_events_billing_idempotency.sql', '205_stripe_event_idempotency_rollback.sql', '205_stripe_event_idempotency.sql', '087_idempotency_cache.sql']
- failure-pattern penalty: -0.0

### Failure patterns (agent-visible)

- none
