# R8 R2 token rotation — post chat-share leak protocol — 2026-05-07

**Scope**: jpcite v0.3.4 — operator runbook landing for the
post-incident rotation procedure that closes the credential surface
when the four R2 token values
(`Access Key ID` / `Secret Access Key` / `Endpoint` / `Bucket`) end up
inside a Claude chat session — typically because the operator
screenshotted the Cloudflare `Create API Token` modal and shared it
with the AI to drive `gh secret set`.

**Doc-only change.** No production secret value lands in the repo.
No code, workflow, or schema mutated. Operator-side rotation is the
load-bearing step; this audit documents the runbook deliverable.

Companions:
- `R8_GHA_R2_SECRETS_OPERATOR_2026-05-07.md` — the prior R8 GHA-mirror
  audit that documented installing the four R2 secrets into the GHA
  store the **first** time.
- `R8_R2_KEY_MINT_2026-05-07.md` — the prior R8 key-mint hypothesis
  audit (tested whether the AI could mint via the CF public API; ruled
  out — operator manual step required).
- `R8_BACKUP_FIX_2026-05-07.md` — the workflow-level argv shell-wrap
  fix that lives upstream of this rotation procedure.
- `R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` — the broader DR audit
  from which the secret-store gap surfaced originally.

Runbook landed: `docs/runbook/r2_token_rotation_post_chat_share.md`.

---

## 1. Trigger one-liner

The operator minted `jpcite-gha-backup` at the Cloudflare R2
dashboard, screenshotted the `Create API Token` modal showing all four
credential values, and shared the screenshot with the AI to expedite
`gh secret set`. Once the values transit the chat surface they must
be treated as effectively leaked — the chat transcript on disk, any
log compaction sampling on the Anthropic side, and any clipboard
manager involved in the screenshot pipeline are all out of the
operator's direct ACL control.

Net: the token is dead-token-walking from the moment it lands in chat.
The cheap fix is rotation; the expensive failure mode is silent reuse
of the leaked token by a third party against the
`autonomath-db-backup` bucket.

## 2. Why a dedicated runbook (rather than reusing §5 of `ghta_r2_secrets.md`)

`docs/runbook/ghta_r2_secrets.md` §5 covers the **steady-state 90-day
rotation cadence** — same mechanics on the surface (revoke + mint +
re-set + verify) but a different trigger and a different ordering
imperative:

| Axis | `ghta_r2_secrets.md` §5 (cadence) | this runbook (post-leak) |
|---|---|---|
| Trigger | Calendar reminder ~80d after last rotation | Token value entered chat history (any source) |
| Urgency | Rotate before TTL expires (T+90d hard deadline) | Rotate immediately — leak window is open |
| Verify-first ordering | Optional but recommended | **Mandatory** — verify new pair works before revoke |
| Audit log review | Not required | Required if any sign of third-party hit |
| Calendar reset | Reset 90d clock from new mint | Reset 90d clock + add a "no chat-share" reminder |
| Cross-ref | Steady-state | Post-incident |

Bundling the two into a single document risks the operator confusing
"my calendar reminder fired" with "my credential leaked" — different
mental modes, different urgency. Keep the two procedures separate;
cross-reference both in each `Related:` block.

## 3. Runbook structure landed

`docs/runbook/r2_token_rotation_post_chat_share.md` (new file, 4 main
sections + Anti-patterns):

- **§1 Risk** — table breaking down the five distinct leak surfaces
  (chat transcript on disk, Anthropic log compaction, image OCR
  re-rendering, OS clipboard managers, terminal scrollback). Each row
  notes the operator's mitigation reach. Net argument: rotation is
  cheap (5 min), breach scenario is asymmetric (bucket holds the only
  off-site copy of 8.29 GB autonomath.db), so don't gamble on
  individual log-path reachability.
- **§2 Rotation procedure** — six ordered steps:
  - **§2.a** wait for the next `nightly-backup.yml` PASS to confirm
    new GHA secrets work before revoking old.
  - **§2.b** revoke the leaked token via dashboard `…` overflow menu.
  - **§2.c** mint fresh token with same name `jpcite-gha-backup` and
    same scope (Object Read & Write on `autonomath-db-backup`).
  - **§2.d** install new four values via stdin-paste `gh secret set`
    only — no screenshot, no chat, no `--body` flag, no `.env`.
  - **§2.e** verify via fresh `gh workflow run nightly-backup.yml`.
  - **§2.f** confirm leaked token is dead by sanity-probing a 403
    against the bucket from the operator's terminal.
- **§3 Future-proof** — 90-day cadence reset note (cross-ref to
  `ghta_r2_secrets.md` §5), hard rule "never share token values via
  chat" with a wrong/right table, and a chat-share recognition
  heuristic the AI can use to detect the leak the moment it lands.
- **§4 Incident response** — if there's reason to suspect the leaked
  token was actually used: §4.1 R2 access log review, §4.2 object
  integrity check (per-object SHA256 vs workflow manifest), §4.3
  Cloudflare audit log review for third-party IPs, §4.4 close-out if
  integrity check passes.
- **Anti-patterns** — five concrete don'ts (don't skip §2.a, don't
  keep leaked token as fallback, don't edit `ghta_r2_secrets.md`
  out-of-scope, don't archive the leaked credential to "audit log"
  files, don't weaken the fail-closed check in `nightly-backup.yml`).

## 4. Why this runbook is "operator-only"

`category: secret`, `operator_only: true` in the front-matter:

- The dashboard interaction (`dash.cloudflare.com → R2 → Manage R2 API
  Tokens`) is OAuth-gated and requires interactive operator login.
  AI cannot mint or revoke without operator action.
- `gh secret set` reads from the operator's local stdin; no AI-side
  source exists for the new credential pair.
- The R2 audit log (Cloudflare dashboard → R2 → bucket → Logs) is
  surfaced only in the dashboard UI in the current Cloudflare R2
  product — the public CF API exposure for `r2 access-keys` /
  `r2 api-tokens` mint endpoints is gated to a different scope per
  the `R8_R2_KEY_MINT_2026-05-07.md` probe matrix (it's not the
  operator's session-OAuth bearer; it requires a CF API token with
  the `Account → R2 API Tokens → Edit` permission group).

So the runbook documents what the operator must do; the AI's role is
recognising the leak signature and routing the operator to §2 the
moment chat-share happens.

## 5. Constraints honoured

- **LLM 0** — no LLM call inside this audit doc, the runbook, or the
  rotation procedure. The runbook is operator-driven manual steps.
- **Destructive overwrite forbidden** — both the runbook and this
  audit doc are **new** files. `docs/runbook/ghta_r2_secrets.md` is
  untouched (verified via the constraint clause + the cross-ref-only
  pattern in §3). No edits to existing files.
- **No secret value in this doc** — same standing rule as
  `R8_GHA_R2_SECRETS_OPERATOR_2026-05-07.md` and
  `R8_R2_KEY_MINT_2026-05-07.md`. The four credential values are
  named, scoped, and described, but never written down here.

## 6. Follow-ups (deferred, non-blocking)

- The chat-share recognition heuristic in §3 of the runbook is
  prose-only — it is **not** wired into a real-time scanner. A
  follow-up could add an offline regex sweep over chat transcripts
  under `~/.claude/projects/-Users-shigetoumeda/` that surfaces
  R2-pattern matches into a daily operator digest. Out of scope for
  this audit.
- The `R2_ENDPOINT` and `R2_BUCKET` values are non-secret in practice
  (account ID + bucket name); the runbook treats them as
  secret-tier-equivalent for blast-radius simplicity. A future
  hardening could distinguish the two and let the operator skip
  re-setting the non-secret pair on rotation. Out of scope.
- The 90-day cadence reset on §3 is calendar-driven (operator
  reminder). A follow-up could move the cadence to a `gh secret`
  metadata-driven check that flags any GHA secret older than 80 days.
  Out of scope.

## 7. Net deliverable

| Artifact | Path | Status |
|---|---|---|
| Operator runbook | `docs/runbook/r2_token_rotation_post_chat_share.md` | new — landed this commit |
| Audit cross-ref | `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_R2_TOKEN_ROTATION_2026-05-07.md` | new — this file |
| Steady-state cadence runbook | `docs/runbook/ghta_r2_secrets.md` §5 | untouched (constraint) |
| `nightly-backup.yml` workflow | `.github/workflows/nightly-backup.yml` | untouched (no code change required) |
| GHA secret store | `shigetosidumeda-cyber/autonomath-mcp` | operator-driven — runbook §2.d covers re-set |
| R2 token surface | Cloudflare dashboard | operator-driven — runbook §2.b/§2.c covers revoke + mint |

The doc-only delta is sufficient because the failing surface is
operator-procedural ("what do I do when I just leaked the token to
chat?"), not code-mechanical ("does the workflow run correctly?").
The workflow-level fix already landed in `R8_BACKUP_FIX_2026-05-07.md`.
