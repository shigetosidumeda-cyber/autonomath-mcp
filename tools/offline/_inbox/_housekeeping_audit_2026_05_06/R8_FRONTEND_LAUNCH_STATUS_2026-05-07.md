# R8 — Frontend launch status (2026-05-07)

**Companion doc** to `R8_LAUNCH_LIVE_STATUS_2026-05-07.md`. Where that doc covers the live Fly API axis, this one focuses on the **Cloudflare Pages frontend axis** picked up from the `HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md` baton. The previous codex CLI stopped immediately before a Pages deploy on user request — this audit re-grounds the inherited state and lays out the next-step plan for the next CLI without assuming production write authority.

Internal-hypothesis framing kept: "frontend live" means the Pages artifact reflects 5/7 hardening (¥3/billable_unit copy + link-checker fix + rsync-safe artifact); the API axis live-ness is independently tracked in `R8_LAUNCH_LIVE_STATUS_2026-05-07.md`.

**Follow-up correction (2026-05-07 12:55 JST):** the later GHA deploy attempt
re-deployed GitHub remote `main` at `f3679d6926...`, because local `main` was 31
commits ahead of `origin/main` and had not been pushed. `flyctl image show -a
autonomath-api` now reports image tag `deployment-01KR08RKZW3CGDCNJQER4QV728`,
but the label is still `GH_SHA=f3679d6926...`. Therefore the API axis is healthy
but still on the 5/6 code image; 5/7 hardening is not live on Fly.

## §1 Inherited context (from `HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md`)

**Stop-condition snapshot** (151-line handoff, 11:51 JST):

- 3 dirty files in worktree at stop time:
  - `docs/integrations/ai-recommendation-template.md` — replaced broken public links to excluded docs (`/docs/bench_methodology.md`, `/docs/bench_results_template.md`) with `/benchmark/` or repository-reference text.
  - `server.json` — public pricing metadata flipped from `billable_request` / `¥3/リクエスト` to `billable_unit` / `¥3/課金単位`.
  - `site/practitioner-eval/index.html` — stopped putting a template literal URL directly in `innerHTML`, because the static link checker reads `/practitioner-eval/${p.persona_slug}.html` as a broken literal.
- Validation already run (all PASS):
  - `.venv/bin/mkdocs build --strict` → PASS
  - `python3 scripts/check_distribution_manifest_drift.py` → OK (manifest matches static surfaces)
  - artifact link checker on `/tmp/jpcite-pages.ziTFoZ` → `checked_html=12585 checked_links=462136 broken=0`
  - JSON validation for `mcp-server.json` / `server.json` / `docs/openapi/v1.json` / `openapi.agent.json` → PASS
- Local OpenAPI counts observed: `docs/openapi/v1.json paths: 186` (NOT the stale 227 figure from earlier docs). Manifest-drift checker is aligned to this count; do NOT blindly restore 227 without rerunning the exporter/guard.
- Validated artifact: `/tmp/jpcite-pages.ziTFoZ` (built from `site/` with the rsync-exclude rules; under `/tmp` — safest behavior is rebuild a fresh artifact + re-validate before deploy).
- Loop stopped on user request, no production deploy executed in that CLI. Live `https://jpcite.com/` remains pre-handoff stale until the next CLI pushes the artifact.
- Older subagent findings (`11,684`, `154 full text`, `¥3/req`, `227 paths`) flagged stale unless re-reproduced against current worktree.

## §2 4-axis launch status (re-grounded)

| axis | state | source-of-truth |
|---|---|---|
| **Fly api (autonomath-api)** | LIVE and healthy, but still serving remote-main `f3679d6` code. A later GHA run produced a newer Fly image tag, yet its `GH_SHA` label remains `f3679d6`; local 5/7 hardening was not pushed to GitHub and therefore was not deployed by GHA. `/healthz` 200. | `R8_DEPLOY_ATTEMPT_AUDIT_2026-05-07.md` correction + follow-up `flyctl image show` |
| **Cloudflare Pages (autonomath project)** | **STALE — pre-handoff baseline.** Previous codex CLI built and validated `/tmp/jpcite-pages.ziTFoZ` but did NOT execute `wrangler pages deploy`. Live `jpcite.com` does not yet carry: (a) `/docs/integrations/ai-recommendation-template.md` link fix, (b) `server.json` `billable_unit` rename, (c) `/practitioner-eval/index.html` template-literal-link fix. | `HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md` §Status + §Notes |
| **DNS** | Cutover already complete. `jpcite.com` apex → Cloudflare (104.21.14.100, 172.67.158.158). `api.jpcite.com` → CNAME `568j9g9.autonomath-api.fly.dev`. CF TTL ≤ 5 min. Legacy `zeimu-kaikei.ai` apex retained on CF for 301 redirect runway. | `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` §3 |
| **Stripe** | Live keys deployed (`STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` + `STRIPE_PRICE_PER_REQUEST` + `STRIPE_BILLING_PORTAL_CONFIG_ID` + `STRIPE_TAX_ENABLED`). Live activation confirmed indirectly via anonymous rate-limit returning `limit:3` on `/v1/meta` (paid path runtime live). Operator UI confirmation step (Dashboard "Activate live mode" 1-click) may already be done. | `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` §1 row 7 + §7 row 3 |

Net: **3 of 4 axes already live.** Frontend axis is the single remaining code-side step the AI can execute end-to-end without a logged-in operator browser session.

## §3 Frontend deploy plan (next CLI, idempotent)

**Project**: Cloudflare Pages `autonomath` (legacy project name; brand surface remains jpcite per CLAUDE.md non-negotiables).

**Artifact**: rebuild fresh under `/tmp/jpcite-pages.XXXXXX` since the inherited `ziTFoZ` lives in `/tmp` and may be GC'd between CLIs. Use the same rsync-exclude rules as the validated build:

```bash
ARTIFACT="$(mktemp -d /tmp/jpcite-pages.XXXXXX)"
rsync -a --delete \
  --exclude '_templates/' \
  --exclude '*.src.js' \
  --exclude '*.src.css' \
  --exclude '*.map' \
  --include 'press/*.md' \
  --include 'security/policy.md' \
  --exclude '*.md' \
  site/ "$ARTIFACT/"
```

Then re-validate (mkdocs strict + manifest-drift + link checker + 4 JSON files) before push. Deploy:

```bash
npx --yes wrangler whoami
npx --yes wrangler pages deploy "$ARTIFACT" \
  --project-name=autonomath \
  --branch=main \
  --commit-hash="$(git rev-parse HEAD)" \
  --commit-message="manual site artifact deploy $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --commit-dirty
```

Use `--commit-dirty` only if the tree is still dirty at deploy time. The predecessor 3-file frontend fix was later committed in `7ee0b08`; subsequent debug/review edits changed the dirty-tree fingerprint again, so the next CLI must either commit the reviewed diff first or generate a fresh operator ACK fingerprint before using a dirty deploy.

**Post-deploy smoke** (verifies stale strings removed):

```bash
Q="deploy_check=$(date +%s)"
curl -fsSL "https://jpcite.com/?$Q" | tee /tmp/jpcite_index.html >/dev/null
! rg -n '11,684|本文 154|¥3/req|¥3/リクエスト|OpenAPI paths 227|見逃さない' /tmp/jpcite_index.html
rg -n '11,601|6,493|billable unit' /tmp/jpcite_index.html
curl -fsSL "https://jpcite.com/server.json?$Q" | python3 -m json.tool >/dev/null
curl -fsSL "https://jpcite.com/mcp-server.json?$Q" | python3 -m json.tool >/dev/null
curl -fsSL "https://jpcite.com/docs/openapi/v1.json?$Q" | python3 -m json.tool >/dev/null
curl -fsSL "https://jpcite.com/openapi.agent.json?$Q" | python3 -m json.tool >/dev/null
curl -fsSI "https://api.jpcite.com/healthz"
```

## §4 真の残: OAuth + Stripe live activation (UI-only, AI-undoable)

After the frontend deploy lands, the residual launch surface is operator-UI only:

| step | reach | reason |
|---|---|---|
| Google OAuth client (Drive integration) | OPERATOR | `console.cloud.google.com` requires logged-in browser session on operator account — no CLI/API path for client_id minting |
| GitHub OAuth client (Gist export) | OPERATOR | `github.com/settings/developers` requires same |
| Stripe live mode activation gate | OPERATOR-or-CONFIRM-DONE | `dashboard.stripe.com` Dashboard 1-click; live keys already deployed and rate-limit confirms paid path live, so this likely is already done |

These are 5–15 min UI tasks each. Cannot be performed by AI; purely physical-access gating, not policy choice.

## §5 Internal-hypothesis framing maintained

- "Frontend deploy" is the **single AI-executable** step remaining on the launch checklist; the AI should execute it without escalation.
- "OAuth client registration" is **not** AI-doable — the AI is not authorized to log into `console.cloud.google.com` or `github.com/settings/developers` as the operator. The next CLI should not propose to "automate" those steps; they are operator-only by physical-access gating, not by policy preference.
- "Live frontend" does not collapse into "live revenue surface" — Stripe live activation is independent (already done by indirect signal). The Pages deploy alone updates copy/JSON manifests; it does not flip a payment gate.
- The 5/7 hardening wave is **not** on the API axis yet. GHA deploys GitHub's
  remote `main`, not local unpushed commits; push/commit discipline must happen
  before using `gh workflow run deploy.yml --ref main` as a forward deploy path.
  The Pages deploy can still update static surfaces from a local artifact, but
  that would not imply the API image has the same 5/7 source.
- "Verify before bump" applies to OpenAPI paths: 186 is current truth, 227 is stale. Do not restore 227 without re-running the exporter/guard.

## §6 Cross-references

- `tools/offline/_inbox/HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md` — predecessor CLI baton (3 dirty files + validated artifact + suggested next steps).
- `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` — sibling axis doc covering Fly api / DNS / Stripe / signed ACK YAML.
- `R8_NEXT_SESSION_2026-05-07.md` — Step 1–4 plan; Steps 1+3a+3b absorbed by AI per `R8_LAUNCH_LIVE_STATUS` §10. Frontend deploy resolves Step 2 / 3c.
- `R8_ACK_YAML_LIVE_SIGNED_2026-05-07.yaml` — operator-ack signed for the earlier dirty-tree state. If any new debug/review diff remains uncommitted, rerun the GO gate with a fresh ACK fingerprint or commit the reviewed files before deployment.
- `R8_PRODUCTION_GATE_DASHBOARD_SUMMARY_2026-05-07.md` — gate dashboard 5/5 GREEN.
- `R8_FLY_DEPLOY_READINESS_2026-05-07.md` + `R8_FLY_SECRET_SETUP_GUIDE.md` — pre-deploy readiness + secret guide (now resolves to "verified deployed").
- `R8_CLOSURE_FINAL_2026-05-07.md` — 25+ R8 doc consolidated closure.
- `docs/_internal/CURRENT_SOT_2026-05-06.md` + `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md` — 5/6 SOT pointers for execution order, dirty-tree handling, re-probe requirements.

## §7 Verdict

**Frontend axis: 1 deploy command from live.** The artifact is validated, rsync rules are stable, link checker is 0 broken, JSON manifests parse clean. The next CLI should rebuild a fresh `/tmp/jpcite-pages.XXXXXX`, re-validate, then deploy from either a clean committed tree or a freshly acknowledged dirty fingerprint. Post-deploy smoke greps for the stale strings the hardening wave removed; if any reappear, rollback is `wrangler pages deployment list` + redeploy the previous successful build.

**Combined launch state after frontend deploy lands**: frontend LIVE (Pages 5/7
static hardening) + Stripe live (paid path confirmed) + DNS cutover done, while
Fly remains healthy on the 5/6 `f3679d6` code image until reviewed local commits
are pushed and deployed. OAuth client registration remains operator-UI residual
(≤15 min total).
