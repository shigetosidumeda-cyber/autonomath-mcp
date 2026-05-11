# jpcite Agent Journey 6-Step Audit — 2026-05-11

Wave 17 AX runner. ax_smart_guide §3.3 + §7. NO network, NO LLM call.

**Overall**: 8.95 / 10 (GREEN)

| step | name | score | failure patterns |
| ---: | --- | ---: | ---: |
| 1 | discovery | 9.17 | 0 |
| 2 | evaluation | 8.88 | 3 |
| 3 | authentication | 10.00 | 0 |
| 4 | execution | 10.00 | 0 |
| 5 | recovery | 5.67 | 1 |
| 6 | completion | 10.00 | 0 |

## Step 1: discovery — 9.17 / 10

### Findings

- discovery surface presence: 8/8
- AI bot welcome: 6/6 UAs in robots.txt
- MCP registry visibility: 2/3 hints

### Failure patterns (agent-visible)

- none

## Step 2: evaluation — 8.88 / 10

### Findings

- evaluation docs presence: 7/7
- 8業法 fence coverage: 5/8
- recipes: 31 (target ≥ 30)

### Failure patterns (agent-visible)

- fence_registry missing 8業法 entry: 社会保険労務士法
- fence_registry missing 8業法 entry: 公認会計士法
- fence_registry missing 8業法 entry: 労働基準法

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

- openapi paths: full=220 slim_gpt30=34 (floor 180)
- error envelope + idempotency files: 2/2
- Idempotency-Key references in api/: 11

### Failure patterns (agent-visible)

- none

## Step 5: recovery — 5.67 / 10

### Findings

- 'retry_after': 15 file(s) in api/+mcp/
- 'docs_url': 0 file(s) — recovery hint missing
- 'error_code': 3 file(s) in api/+mcp/
- failure-pattern penalty: -1.0

### Failure patterns (agent-visible)

- agent cannot self-recover: 'docs_url' absent from api/+mcp/

## Step 6: completion — 10.00 / 10

### Findings

- 'corpus_snapshot_id': 56 file(s) in src/
- 'content_hash': 10 file(s) in src/
- idempotency_cache migration: ['122_usage_events_billing_idempotency.sql', '205_stripe_event_idempotency_rollback.sql', '205_stripe_event_idempotency.sql', '087_idempotency_cache.sql']
- failure-pattern penalty: -0.0

### Failure patterns (agent-visible)

- none

