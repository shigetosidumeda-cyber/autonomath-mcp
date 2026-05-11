# narrative-sla-breach-hourly cron — 20-run consecutive failure root cause + fix plan

**Date**: 2026-05-11
**Audit lane**: redteam P0 hotfix (jpcite session)
**Workflow**: `.github/workflows/narrative-sla-breach-hourly.yml`
**Failure span observed**: 2026-05-09T18:59Z → 2026-05-10T23:51Z (20 consecutive `conclusion=failure` runs, hourly cron)

## Symptom

`gh run view 25643208062 --log-failed` shows:

```
Connecting to fdaa:6f:a51:a7b:2e1:71b6:1385:2...
exec: "export": executable file not found in $PATH
Error: ssh shell: ssh: command export TG_BOT_TOKEN=$(printf '%s' '' | base64 -d); ... failed
```

Env dump from the GHA step:

```
FLY_API_TOKEN: ***          # set
TG_BOT_TOKEN:               # EMPTY
TG_CHAT_ID:                 # EMPTY
DRY_RUN: false
```

`gh secret list` confirms repository secret store carries only `FLY_API_TOKEN` (2026-05-02). **`TG_BOT_TOKEN` and `TG_CHAT_ID` are NOT registered** in the GHA repo secret store.

## Two-layer root cause

### Layer 1 — missing Telegram secrets

`TG_BOT_TOKEN` / `TG_CHAT_ID` are referenced in workflow line 60-62 as `${{ secrets.TG_BOT_TOKEN }}` / `${{ secrets.TG_CHAT_ID }}`. The repo secret store has neither, so GHA injects empty strings. The base64 round-trip in line 70-71 still produces empty strings (`printf '%s' '' | base64 -w0` = `""`).

### Layer 2 — `flyctl ssh console -C` exec model

Workflow line 72-73 invokes:

```
flyctl ssh console -a autonomath-api -C "export TG_BOT_TOKEN=...; export TG_CHAT_ID=...; /opt/venv/bin/python ..."
```

`flyctl ssh console -C <cmd>` does NOT spawn a shell on the remote — it runs `cmd` directly via `exec(2)`. `export` is a bash builtin, not an executable, so `exec: "export": executable file not found in $PATH` is raised.

**Even if both Telegram secrets were populated, the cron would still 100%-fail on this exec model.** This is not a token-rotation problem.

The Python script itself (`scripts/cron/narrative_report_sla_breach.py`) explicitly tolerates missing TG_* env vars (line 14-16 docstring: "When the env vars are missing the cron still runs (and logs the breach count) but does not push"). So the right fix is to stop trying to inject them via `export` and instead pass them as a `sh -c` wrapper command (or rely on Fly secrets set on the machine + drop the GHA-side injection entirely).

## Recommended remediation (single option)

**Option 1 (recommended): wrap in `sh -c` + add Telegram secrets to GHA store.**

Workflow patch (line 72-73 replacement):

```yaml
flyctl ssh console -a autonomath-api \
  -C "sh -c 'TG_BOT_TOKEN=\$(printf %s \"${TG_BOT_TOKEN_B64}\" | base64 -d) TG_CHAT_ID=\$(printf %s \"${TG_CHAT_ID_B64}\" | base64 -d) /opt/venv/bin/python /app/scripts/cron/narrative_report_sla_breach.py ${FLAGS}'"
```

Then register the missing secrets:

```bash
# operator action — values from @BotFather + /getUpdates
gh secret set TG_BOT_TOKEN --body "<bot-token>"
gh secret set TG_CHAT_ID   --body "<chat-id>"
```

If operator has no Telegram bot today, the script self-disables gracefully when TG_* are empty AND the `sh -c` wrapper is present — so adding only the workflow fix (no secret) still stops the 20-run failure storm (the cron will succeed with "TG_* missing, dry-mode" behavior).

### Why NOT the other two options

**Option 2 (disable cron via `on:` removal)**: would silence §10.10 (3) Hallucination Guard SLA breach surfacing. Operator would lose P0/P1 SLA breach signal entirely. Also conflicts with memory `feedback_destruction_free_organization` (no destructive workflow edits).

**Option 3 (lower cron 1h → 24h)**: cosmetic spam reduction only. Does not fix the exec model and still produces 1 failure email per day instead of 1/hour. The cron would still be 0% functional.

## Validation steps (post-fix)

1. After applying Option 1 workflow patch + setting (or not setting) TG_* secrets:
   `gh workflow run narrative-sla-breach-hourly.yml --field dry_run=true`
2. `gh run view <new-run-id> --log` → expect `conclusion=success` and no `exec: "export"` error line.
3. If TG_* secrets set: confirm Telegram operator chat receives the dry-run breach summary.
4. If TG_* secrets NOT set: confirm GHA log contains `TG_BOT_TOKEN missing — skipping push` (or equivalent, per narrative_report_sla_breach.py:14 contract) and exit 0.

## Operator decision required

- [ ] Apply Option 1 workflow patch (line 72-73 wrap in `sh -c`).
- [ ] (Optional) Register `TG_BOT_TOKEN` + `TG_CHAT_ID` GHA secrets to enable actual Telegram delivery.
- [ ] (Optional) Mirror same TG_* secrets to Fly via `fly secrets set -a autonomath-api TG_BOT_TOKEN=... TG_CHAT_ID=...` per memory `feedback_secret_store_separation` (Fly secret ≠ GHA secret).

## Related notes

- Fly app canonical name = **`autonomath-api`** (verified 2026-05-11 via `flyctl status -a autonomath-api`). The brand-rename target `jpcite-api` was never created. See `scripts/ops/production_deploy_go_gate.py:23` (`CANONICAL_FLY_APP = "autonomath-api"`) + `LEGACY_FLY_APP_ALIASES = ("jpcite-api", ...)`.
- This audit revised the stale default in `scripts/ops/post_deploy_verify_v3.sh:17` from `jpcite-api` → `autonomath-api` (same session).
- CLAUDE.md mentions of `autonomath-api` on lines 143/253 are **console-script entry-point names** from `pyproject.toml`, NOT Fly app names — correct and untouched.
- `FLY_API_TOKEN` GHA secret was rotated **2026-05-02** (per `gh secret list` UpdatedAt). Not expired, not the cause.
- Sister cron `narrative-audit-monthly.yml` likely has the same `flyctl ssh console -C "export ..."` anti-pattern — recommend grep audit before next monthly trigger:
  `rg -n 'flyctl ssh console.*-C.*export' .github/workflows/`
