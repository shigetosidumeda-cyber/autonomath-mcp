# DEEP-61 — jpcite v0.3.4 post-deploy smoke runbook

**Owner:** solo-ops (Bookyou株式会社)
**Lane:** session A
**Status:** draft, 2026-05-07
**Spec:** `docs/_internal/deep61_smoke_runbook.md` (sketch)
**Companion DEEP IDs:** DEEP-25 (verify primitives), DEEP-58 (dashboard), DEEP-59 (acceptance CI), DEEP-60 (lane enforcer)

This runbook is the minimum-viable gate that runs **after** every Fly deploy of `api.jpcite.com` and **before** the operator marks a release green. Five modules, five hand-offs, no LLM calls, ~120 second wall clock on a healthy deploy.

---

## Prerequisites

Before kicking off the smoke:

1. `fly deploy` completed and the new machine reports `status=passing` in `fly status`.
2. `entrypoint.sh` boot log shows: `autonomath self-heal migrations: applied=N skipped=M` (no `error=` lines).
3. `pyproject.toml` and `server.json` versions match (e.g. both `0.3.4`).
4. CORS allowlist contains `https://jpcite.com`, `https://www.jpcite.com`, `https://api.jpcite.com` (regression caught 2026-04-29).
5. The smoke laptop has the project venv active (`autonomath-mcp` binary on PATH) **or** the operator passes `--mcp-cmd` pointing to a remote stdio bridge.
6. No Anthropic / OpenAI / Gemini env vars set in the shell. The smoke script aborts at import if an LLM SDK is loaded.

---

## One-shot run

```bash
cd ~/jpcite
.venv/bin/python tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/deep61_smoke_runbook/post_deploy_smoke.py \
    --base-url https://api.jpcite.com \
    --module all \
    --report-out /tmp/jpcite_smoke_v034.json
```

Expected stderr (one line per module, in order — `health` runs first so a broken deploy fails in <2 s):

```
[PASS] health_endpoints       0.42s  3/3 healthy
[PASS] routes_500_zero       58.13s  240/240 walked, 5xx=0, sample=[('/healthz',200),('/readyz',200),('/v1/am/health/deep',200)]
[PASS] mcp_tools_list         9.81s  142 tools listed (floor=139+)
[PASS] disclaimer_emit_17    23.55s  17/17 sensitive tools emit _disclaimer
[PASS] stripe_webhook         1.97s  first=200 second=200 idempotent=True
```

Expected stdout (single JSON line, machine-readable):

```json
{"ok": true, "modules": ["health_endpoints", "routes_500_zero", "mcp_tools_list", "disclaimer_emit_17", "stripe_webhook"]}
```

Exit 0 = green to release. Exit 1 = stop, do not promote, do not flip the public DNS record.

---

## Module 1 — health_endpoints

Confirms the three hand-rolled health surfaces that Fly grace and Cloudflare load-balancer probes hit:

| Path                  | Owner                                | Notes                                                         |
| --------------------- | ------------------------------------ | ------------------------------------------------------------- |
| `/healthz`            | `api.main`                           | Liveness only — never touches the DB. 200 even if DB is cold. |
| `/readyz`             | `api.main`                           | Readiness — opens jpintel.db + autonomath.db both, fails 503 if either path is missing. |
| `/v1/am/health/deep`  | `api.autonomath` (Phase A)           | Deep — runs schema_guard + counts on `am_entities`, `programs`. |

Failure mode: any non-200 → exit 1. Most common cause is `data/autonomath.db` placeholder vs root-level real file mismatch (CLAUDE.md "common gotchas").

## Module 2 — routes_500_zero

Walks the 240-row sample list at `240_routes_sample.txt`. Anonymous-tier reads only — the script does not POST. Pass = zero responses in `[500, 600)`. Connection errors count as failures.

The sample is a deterministic union of:

- 5 sitemap / OpenAPI / docs surfaces.
- 47 prefecture program-search permutations.
- 16 JSIC major industry surfaces.
- ~60 `/v1/me/*` cohort + billing + saved-search probes.
- ~70 `/v1/am/*` autonomath surfaces (V4 + Phase A + Wave 21-23).
- ~40 `/v1/site/*` static + cohort + sitemap + RSS surfaces.

If `5xx>0`, the report JSON's `results[*].detail.five_xx` field shows the first 25 offenders for triage.

## Module 3 — mcp_tools_list

Spawns `autonomath-mcp` over stdio, sends a JSON-RPC 2.0 `initialize` + `notifications/initialized` + `tools/list` triple, and asserts `len(tools) >= 139`. Floor is configurable via `--mcp-min-tools`; do not lower below 139 without bumping CLAUDE.md and the manifests.

Failure modes:

- Binary missing → install editable: `pip install -e ".[dev,site]"`.
- Timeout → an expensive import is now happening on cold start; investigate `src/jpintel_mcp/mcp/server.py:4220` autonomath import block.
- Count below floor → flip-gate regression (see CLAUDE.md "Wave 21-22 changelog"); diff `len(await mcp.list_tools())` against last green release.

## Module 4 — disclaimer_emit_17

For each entry in `17_sensitive_tools.json`, calls the tool over MCP stdio with the listed `sample_arguments` and asserts the response envelope contains a `_disclaimer` field somewhere reachable (`result._disclaimer`, `result.content[].text` JSON-decoded, etc.).

The 17 surfaces span the seven statutory fences carried by `jpcite-disclaimer-spec`:

- 税理士法 §52 (kessan / ruleset / pack tools).
- 弁護士法 §72 (DD / enforcement / rule-engine).
- 行政書士法 §1 (application kit / acceptance stats / chain composition).
- 司法書士法 §3 (jurisdiction cross-check).
- 社労士法 §2 / 労基法 §36 (36協定 + DD social-insurance branch).
- 貸金業法 §3 (loan search).
- 保険業法 §3 (mutual plan search).

Failure means `_disclaimer` was scrubbed by a regression somewhere between the tool body and the FastMCP envelope wrapper. Do not promote — disclaimers are statutory, not cosmetic.

## Module 5 — stripe_webhook

POSTs a synthetic `invoice.paid` event twice with the same idempotency key (`evt_jpcite_deep61_smoke_0001`). Pass requires both responses are in `{200, 202, 204, 400}` **and** identical (the `idempotency_cache` table introduced in migration 087 must produce a bit-for-bit replay).

400 is allowed because some signed-webhook deployments verify the signature first; the value of the smoke is that the **second** POST behaves the same as the first.

Skip with `--skip-stripe` if Stripe is in maintenance mode or the operator is doing a code-only rollback.

---

## Failure → rollback path

1. **Capture the report.** `cat /tmp/jpcite_smoke_v034.json` and attach to the rollback ticket.
2. **Decide rollback or fix-forward.**
   - 5xx > 0 on `/v1/me/*` paths → almost always a missing migration. Fix-forward is fine if `entrypoint.sh` log shows the migration applied; otherwise rollback.
   - Disclaimer regression → **always rollback**. Statutory exposure outweighs revenue gap.
   - MCP count drop → check whether a gate flag flipped without a CLAUDE.md update; rollback if intentional, fix-forward otherwise.
3. **Rollback command.** `fly releases list --app jpcite-api`, then `fly releases rollback <prev_id> --app jpcite-api`. Verify with a second smoke run targeting the rolled-back image.
4. **Post-mortem.** File under `docs/_internal/postmortem/jpcite_v0.3.X_<reason>.md`; cross-link DEEP-61 report path.

---

## Operational caveats

- Run order is intentional: `health → routes → mcp → disclaimer → stripe`. A broken deploy that fails health saves ~95 s of useless route walking.
- The 240 list is **not** a fuzzer; it is a regression net. Adding a route to production should add a row here within the same PR.
- `--module=routes` / `--module=mcp` etc. let the operator iterate on a single module during incident triage without re-running the full set.
- Cron-friendly: GHA workflow `post-deploy-smoke.yml` (sketch) invokes this script with `--report-out` and uploads the artifact. CI gating happens in DEEP-59, not here.
