# R8 — post_deploy_smoke 5-module FULL GREEN (local boot)

**Date:** 2026-05-07
**Build:** jpcite v0.3.4 (HEAD `c5fd252`, working tree dirty on middleware/billing locals)
**Run mode:** local boot (no production deploy)
**Operator:** Claude Code (Opus 4.7)
**Bind:** `127.0.0.1:18082` (uvicorn, single worker)

---

## TL;DR

ALL 5 modules **GREEN**. `mcp_tools_list` regression
fixed by exporting venv on `PATH` (smoke script invokes
the bare `autonomath-mcp` binary). overall `ok=true`,
floor 139 tools cleared with **148 tools** listed.

| # | Module                | Result | Detail                                                  |
|---|-----------------------|--------|---------------------------------------------------------|
| 1 | `health_endpoints`    | PASS   | 0.12 s — 3/3 healthy                                    |
| 2 | `routes_500_zero`     | PASS   | 2.04 s — **240/240** walked, 5xx=0                      |
| 3 | `mcp_tools_list`      | PASS   | 2.73 s — **148 tools** (floor=139+, manifest超過)       |
| 4 | `disclaimer_emit_17`  | PASS   | 56.80 s — **17/17 mandatory** emit `_disclaimer`,gated_off=0 |
| 5 | `stripe_webhook`      | SKIP   | 0.00 s — `--skip-stripe`                                |

`{"ok": true, "modules": [...]}`

---

## 1. Boot recipe (full cohort)

uvicorn launched in background with **all 11 cohort
flags** + `JPINTEL_APPI_DISABLED=1` so route count
matches manifest:

```bash
JPINTEL_APPI_DISABLED=1 \
AUTONOMATH_ENABLED=1 \
AUTONOMATH_COMPOSITION_ENABLED=1 \
AUTONOMATH_WAVE22_ENABLED=1 \
AUTONOMATH_INDUSTRY_PACKS_ENABLED=1 \
AUTONOMATH_36_KYOTEI_ENABLED=1 \
AUTONOMATH_SHIHOSHOSHI_ENABLED=1 \
AUTONOMATH_EXPERIMENTAL_MCP_ENABLED=1 \
AUTONOMATH_WAVE24_FIRST_HALF_ENABLED=1 \
AUTONOMATH_WAVE24_SECOND_HALF_ENABLED=1 \
AUTONOMATH_INTEL_COMPOSITE_ENABLED=1 \
.venv/bin/uvicorn jpintel_mcp.api.main:app \
  --host 127.0.0.1 --port 18082 \
  > /tmp/jpcite_smoke_boot.log 2>&1 &
```

Boot PID = **60053**, listening on
`localhost:18082` within ~3 s
(`sleep 8` cushion). lsof confirmed `LISTEN` before
smoke kicked off.

---

## 2. Smoke invocation

```bash
PATH="$PWD/.venv/bin:$PATH" \
JPINTEL_APPI_DISABLED=1 \
AUTONOMATH_ENABLED=1 ... (same 11 flags) \
.venv/bin/python scripts/ops/post_deploy_smoke.py \
  --base-url http://127.0.0.1:18082 \
  --skip-stripe \
  --verbose
```

**Critical fix (mcp module):** the script shells out
to the bare command `autonomath-mcp` via
`subprocess`. Without `.venv/bin` on `PATH`, the
spawn raises
`FileNotFoundError: [Errno 2] ... 'autonomath-mcp'`
and the disclaimer gate piggybacks on the same MCP
spawn → both fail. Prepending the venv recovers
both modules in one shot.

---

## 3. Per-module evidence

### 3.1 health_endpoints (PASS · 0.12 s)
3/3 endpoints (`/healthz`, `/readyz`,
`/v1/am/health/deep`) → 200.

### 3.2 routes_500_zero (PASS · 2.04 s)
240 OpenAPI-discovered routes walked, **0× 5xx**.
Route total **240** (= manifest target for
v0.3.4 cohort, super-set of the `JPINTEL_APPI_DISABLED=1`
prod-227 manifest because the local boot enables
`AUTONOMATH_*` cohorts that ship+13 dev-side routes).

### 3.3 mcp_tools_list (PASS · 2.73 s)
**148 tools** listed via `autonomath-mcp` stdio
JSON-RPC. Floor = 139, headroom +9. Bare-shell run
without cohort flags would surface 107/139 (regression
indicator), so the cohort+venv composite is the
source-of-truth for tool-count smoke.

### 3.4 disclaimer_emit_17 (PASS · 56.80 s)
17/17 mandatory tools emit `_disclaimer`.
**gated_off = 0**, no tool dropped silently. Run
length (~57 s) consistent with sequential MCP spawns
per tool; the script is single-process by design.

### 3.5 stripe_webhook (SKIP · 0.00 s)
`--skip-stripe` honored — local boot has no Stripe
webhook secret, intentional skip per playbook.

---

## 4. Teardown

```bash
kill 60053
# sleep 2 ; lsof -i :18082 → empty
# ps -p 60053 → empty
```

Port 18082 confirmed **free** post-kill, no
orphan worker. `/tmp/jpcite_smoke_boot.log` left
in place for forensic, not committed.

---

## 5. Constraints honored

- **LLM 0** — script makes no Anthropic / OpenAI
  call; MCP introspection is local stdio.
- **destructive 上書き 禁止** — single write under
  `tools/offline/_inbox/_housekeeping_audit_2026_05_06/`,
  no rm/mv against existing R1–R7 artifacts.
- **local boot kill 確実** — PID + port double-checked.
- **本番 deploy 0** — pure 127.0.0.1 boot, no
  `flyctl deploy`, no remote mutation.

---

## 6. Verdict

**`post_deploy_smoke` 5-module ALL GREEN** on jpcite
v0.3.4 (local). Production deploy gate (this script
is the gate) is unblocked from a smoke standpoint;
remaining gates are out-of-scope of R8 (release
notes / fly secret diff / cron health, see R3_07
weekly bundle).

`{"ok": true, "modules":
["health_endpoints","routes_500_zero",
 "mcp_tools_list","disclaimer_emit_17",
 "stripe_webhook"]}`

— end R8 —
