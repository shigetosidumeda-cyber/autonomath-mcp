# Operator Handoff — Frontend Deploy via `pages-deploy-main.yml` (2026-05-07)

Operator-side runbook to unblock the production frontend deploy after this
CLI's local wrangler path was abandoned (5/5 retries — see
`R8_WRANGLER_LOCAL_ABANDONED_2026-05-07.md` in the same directory for the
closure narrative).

The repo-side workflow is already wired and concurrency-guarded; only the
two secrets and one trigger are missing.

Internal hypothesis framing only — the recommendation below depends on a CF
rate-limit hypothesis that this session did not lab-isolate. The post-deploy
smoke step inside the workflow is the actual acceptance gate; treat it as the
ground truth, not the upstream prose.

## Expected wall time

5–10 minutes total, dominated by the CF dashboard token mint UI.

| Step | Where | Wall time |
|---|---|---|
| 1. Mint CF API token | dash.cloudflare.com | 2–4 min |
| 2. `gh secret set CF_API_TOKEN` | local terminal | < 30 s |
| 3. `gh secret set CF_ACCOUNT_ID` | local terminal | < 30 s |
| 4. `gh workflow run pages-deploy-main.yml` + watch | local terminal | 3–5 min (the workflow itself, including post-deploy smoke) |

## Step 1 — Mint a Cloudflare API token

1. Open `https://dash.cloudflare.com/profile/api-tokens`.
2. Click **Create Token** → **Custom token** → **Get started**.
3. Token name: `jpcite-pages-deploy-main` (any name; this is the recommended
   convention for traceability).
4. Permissions — add exactly one row:
   - **Account** → **Cloudflare Pages** → **Edit**
5. Account Resources: **Include → Specific account → (the account that owns
   the `autonomath` Pages project)**.
6. Optionally set a TTL; leave blank for no expiry if you want this to be a
   standing CI secret.
7. **Continue to summary** → **Create Token** → copy the token string. CF only
   shows it once.

Sanity check (optional):

```bash
TOKEN='<paste>'
curl -fsS -H "Authorization: Bearer $TOKEN" \
  https://api.cloudflare.com/client/v4/user/tokens/verify \
  | python3 -m json.tool
```

Expect `"status": "active"`.

## Step 2 — Set `CF_API_TOKEN` as a repo secret

From `/Users/shigetoumeda/jpcite`:

```bash
gh secret set CF_API_TOKEN
# paste the token at the prompt, then Enter, then Ctrl-D (or just Enter on a
# blank line, depending on your gh version)
```

Verify:

```bash
gh secret list | grep -E '^CF_API_TOKEN'
# expect: CF_API_TOKEN  Updated <timestamp>
```

## Step 3 — Set `CF_ACCOUNT_ID` as a repo secret

The account ID is on the right sidebar of any page inside that CF account's
dashboard (e.g. the `autonomath` Pages project page). It is a 32-char hex
string.

```bash
gh secret set CF_ACCOUNT_ID
# paste the account ID
```

Verify:

```bash
gh secret list | grep -E '^CF_ACCOUNT_ID'
```

Note: the workflow header at `.github/workflows/pages-deploy-main.yml` lines
22–28 explicitly forbids introducing `CLOUDFLARE_*` aliases. Use exactly
`CF_API_TOKEN` and `CF_ACCOUNT_ID`.

## Step 4 — Trigger the workflow

```bash
gh workflow run pages-deploy-main.yml --ref main
```

Watch the run:

```bash
gh run list -w pages-deploy-main.yml -L 1
gh run watch "$(gh run list -w pages-deploy-main.yml -L 1 --json databaseId -q '.[0].databaseId')"
```

What "good" looks like:

- Step `Check Cloudflare Pages secrets` → `available=true` (no
  `::warning::` line).
- Step `Build static artifact` → prints artifact size (~ several hundred MB)
  and file count (≈ 13,010 today).
- Step `Validate critical JSON manifests` → no Python tracebacks.
- Step `Publish to Cloudflare Pages` → `cloudflare/pages-action@v1.5.0`
  prints `Deploying ... Success!` plus a `*.pages.dev` preview URL.
- Step `Post-deploy smoke` → 4 URLs OK, ends with `post-deploy smoke OK`.
- Overall conclusion `success`.

If `Post-deploy smoke` fails on the apex `https://jpcite.com/...` URLs but
the publish step succeeded, the deploy itself shipped — the smoke retry loop
already gives 6 attempts × exponential sleep, so a transient CF edge cache
miss is normally absorbed. Re-run only if the conclusion is `failure`.

## After the run

Cross-check the live JSON surfaces against the just-deployed worktree:

```bash
Q="deploy_check=$(date +%s)"
for url in \
  "https://jpcite.com/server.json?$Q" \
  "https://jpcite.com/mcp-server.json?$Q" \
  "https://jpcite.com/docs/openapi/v1.json?$Q" \
  "https://jpcite.com/openapi.agent.json?$Q"
do
  echo "--- $url"
  curl -fsSL "$url" | python3 -m json.tool > /dev/null && echo OK
done
```

This is the same 4-URL check the workflow runs internally; running it from
your shell confirms the apex domain is responding from your egress, not just
from the GHA runner.

## Failure modes / fallbacks

| Symptom | Likely cause | Action |
|---|---|---|
| Step `Check Cloudflare Pages secrets` emits `::warning::` and the run ends `success` (no-op) | Either secret missing or empty | Re-run Step 2 / 3, then Step 4 |
| `Publish to Cloudflare Pages` returns `Authentication error` | Token scope wrong (e.g. Zone instead of Pages) or token expired | Re-mint per Step 1 with **Account → Cloudflare Pages → Edit**, then re-run Step 2 |
| `Publish to Cloudflare Pages` returns `Account not found` | `CF_ACCOUNT_ID` mismatched against token scope | Re-check the right-sidebar account ID on the same dashboard the token was minted from |
| `Post-deploy smoke` fails all 6 attempts on every URL | Likely a Cloudflare edge propagation delay or a domain config drift | Wait 2–3 min, re-trigger the workflow; if still failing, fall back to alternative path A in `R8_WRANGLER_LOCAL_ABANDONED_2026-05-07.md` §5 (CF Pages dashboard direct git integration) |
| Workflow runs but no `site/` paths changed | `paths` filter on the `push` trigger excluded the change set | Use `workflow_dispatch` (this Step 4 already does) — that path bypasses `paths` filtering |

If the operator path itself also degrades (e.g. GHA-side rate-limit observed),
the closure narrative lists alternative paths A–D in
`R8_WRANGLER_LOCAL_ABANDONED_2026-05-07.md` §5; A is the recommended fallback.

## Hypothesis framing (preserved)

The recommendation that GHA will side-step CF's bulk-upload rate limit rests
on (a) GHA's rotating runner egress pool and (b) CF's per-token / per-IP
limiter window resetting between runs — both stated in the workflow header.
Neither is lab-isolated by this session. Treat the post-deploy smoke step as
the actual gate; if it fails consistently, the hypothesis must be revisited.

---

**Status**: Two secrets + one `gh workflow run` away from a green frontend
deploy. Wall time 5–10 min, dominated by the CF dashboard token mint.
