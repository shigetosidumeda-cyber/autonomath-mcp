---
title: R2 token rotation runbook — post chat-share leak protocol
updated: 2026-05-07
operator_only: true
category: secret
---

# R2 token rotation runbook — post chat-share leak protocol

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Trigger**: an R2 API token's four credential values
(`Access Key ID` / `Secret Access Key` / `Endpoint` / `Bucket`) were
shared into a Claude chat session — typically as a screenshot of the
Cloudflare dashboard `Create API Token` modal, or as plain text in the
prompt. Once a credential transits the chat surface it must be treated
as effectively leaked and rotated.
**Related**:
`docs/runbook/ghta_r2_secrets.md` (the GHA mirror procedure — install
new values into the GHA secret store after rotation),
`docs/runbook/secret_rotation.md` (boot-gated Fly secrets — distinct
scope, but the same "stdin-paste only" hygiene rule applies),
`docs/runbook/disaster_recovery.md` §2 (R2 token quartet referenced by
nightly-backup / restore-drill workflows),
`docs/runbook/litestream_setup.md` Step 2 (same R2 token set on the Fly
side).
**Related audit doc**:
`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_R2_TOKEN_ROTATION_2026-05-07.md`
**Last reviewed**: 2026-05-07

This runbook is the operator procedure to rotate the
`jpcite-gha-backup` R2 API token (Object Read & Write scope on
`autonomath-db-backup`) after the credential pair was exposed to chat
history. It is the post-incident counterpart to the steady-state 90-day
rotation cadence in `ghta_r2_secrets.md` §5 — same mechanics, different
trigger.

## §1 Risk — chat-share is an effective leak

The token modal at `dash.cloudflare.com → R2 → Manage R2 API Tokens →
Create API Token` displays the credential pair **once**. When the
operator sends a screenshot of that modal (or the four values as plain
text) into a Claude chat:

| Surface | Reachability | Mitigation? |
|---|---|---|
| Chat transcript on disk (`~/.claude/projects/...`) | reachable by any process running as the operator's user | none — file ACL is `chmod 600` but any locally compromised process gets the value |
| Anthropic-side log compaction / training-set sampling | gated by enterprise-account opt-out + Anthropic internal policy, but **not** under operator's control | unknowable — must assume worst-case |
| Image OCR / future re-rendering of the screenshot | same as transcript reach | none |
| OS-level clipboard managers if the screenshot was pasted | reachable by other apps with clipboard accessibility entitlement | depends on macOS app sandbox state |
| Terminal scrollback if the four values were ever pasted via shell | indefinite until the terminal app's history is cleared | `history -c` does not clear scrollback in iTerm2 / Apple Terminal |

Net: once the pair is in chat, treat the token as compromised. Do not
gamble on whether a particular log path is "really reachable" — the
rotation is cheap (5 minutes), the breach scenario is asymmetric, and
the bucket holds the only off-site copy of `autonomath.db`
(8.29 GB unified primary DB). A leaked Object-Read-and-Write token can
silently overwrite or delete every backup object — replay is the
high-impact failure mode, not just exfiltration.

## §2 Rotation procedure — six steps

Order matters: verify the new secrets work **before** revoking the old
token, then revoke immediately. Don't skip step (a) — if the new
secrets are misconfigured you lose off-site DR while you debug.

### §2.a — wait for the next `nightly-backup` PASS

Confirm the new four secrets that the operator just installed into the
GHA repository secret store actually work end-to-end. Trigger the
workflow manually so you don't wait for the 18:17 UTC cron:

```bash
gh workflow run nightly-backup.yml
gh run watch
# Watch for the "Upload to Cloudflare R2 and rotate" step to turn green.
```

Verify the upload landed:

```bash
aws s3 ls "s3://autonomath-db-backup/autonomath-api/" \
  --endpoint-url "https://<accountid>.r2.cloudflarestorage.com" \
  | tail -3
# expected: today's jpintel-YYYYMMDD-HHMMSS.db.gz + .sha256 + .manifest.json triplet.
```

Only proceed to step (b) **after** the upload step is green. If the
step is red, fix the GHA secret values per
`docs/runbook/ghta_r2_secrets.md` §3 and re-run before rotating.

### §2.b — revoke the leaked token at the Cloudflare dashboard

1. Open `dash.cloudflare.com → R2 → Manage R2 API Tokens`.
2. Locate the token row named `jpcite-gha-backup` (the one whose four
   values were shared into chat).
3. Click the three-dot `…` overflow menu at the right edge of the row.
4. Click **Revoke**. Cloudflare confirms with a modal — confirm.
5. The row's status flips to **Revoked**. Any S3-compatible client
   using the old Access Key ID immediately receives `403 InvalidAccessKeyId`
   on the next request — there is no grace period.

Do **not** skip the revoke step. Leaving the leaked token live "just
in case the new one fails" extends the breach window indefinitely.

### §2.c — mint a fresh token (same name, same scope)

Stay in `dash.cloudflare.com → R2 → Manage R2 API Tokens`:

1. Click **Create API Token**.
2. Token name: `jpcite-gha-backup` (re-use the same name — keeps the
   GHA secret-store nomenclature stable; Cloudflare allows duplicate
   names because the underlying ID is what's unique).
3. Permissions: **Object Read & Write** scope on `autonomath-db-backup`
   bucket only. Do **not** grant `Admin Read & Write` or `All buckets`
   — least privilege; matches §2.2 of `ghta_r2_secrets.md`.
4. TTL: 90 days (Cloudflare's max for Object-scope tokens). The 90-day
   cadence in §3 below covers the next rotation.
5. Click **Create API Token**.

### §2.d — install the new four values into GHA via stdin paste

**Do not screenshot the modal.** **Do not paste the four values into
chat.** **Do not put them into a `.env` file**. The only supported
input path is `gh secret set` reading stdin, run from the operator's
local terminal with the Cloudflare modal still open:

```bash
gh secret set R2_ACCESS_KEY_ID
# (paste the new Access Key ID, Return, Ctrl-D)

gh secret set R2_SECRET_ACCESS_KEY
# (paste the new Secret Access Key, Return, Ctrl-D)

# R2_ENDPOINT and R2_BUCKET typically don't change on token rotation —
# re-set them only if the bucket or accountid changed.
gh secret set R2_ENDPOINT
gh secret set R2_BUCKET
```

After all four are set, copy the four values **once** into the
operator's password manager (Bitwarden / 1Password — anywhere outside
chat and outside the repo) before closing the Cloudflare modal. The
secret access key is unrecoverable post-modal-dismiss.

Anti-pattern reminder (same as `ghta_r2_secrets.md` §3): never use
`gh secret set --body "<paste>"` — that lands the value in `.zsh_history`
and any clipboard manager running on the host.

### §2.e — verify the new secrets via a workflow run

```bash
gh workflow run nightly-backup.yml
gh run watch
# expected: Upload step green within 5-10 minutes.
```

Cross-check the new artifact landed under the same bucket prefix as in
step (a). If the upload step is red, the most likely cause is a typo
in the paste — re-set the offending secret and re-run. Do **not**
re-instate the leaked token while debugging.

### §2.f — confirm the leaked token is dead

Step (b) already revoked it. Sanity-check from the operator's
terminal — a probe with the **leaked** Access Key ID (which the
operator should have on hand from step (b)'s pre-revoke screenshot)
must now 403:

```bash
AWS_ACCESS_KEY_ID="<leaked Access Key ID — value from the chat-shared screenshot>" \
AWS_SECRET_ACCESS_KEY="<leaked Secret Access Key>" \
AWS_DEFAULT_REGION=auto \
aws s3 ls "s3://autonomath-db-backup/" \
  --endpoint-url "https://<accountid>.r2.cloudflarestorage.com"
# expected: An error occurred (InvalidAccessKeyId) when calling the ListObjectsV2 operation
```

If the probe **succeeds** instead of 403'ing, step (b) failed — return
to the dashboard, locate the leaked-credential row, and revoke again.
A successful probe means the rotation is incomplete.

After confirming 403, immediately wipe the leaked-credential strings
from any temporary file they were stored in for this verification.

## §3 Future-proofing

### 90-day rotation cadence

Schedule a calendar reminder for **~80 days after each `gh secret set`**
so the rotation closes before the 90-day TTL expires. The procedure is
identical to §2 above except step (b) becomes "revoke the previous
non-leaked token" — same mechanics, lower urgency.

The 90-day cadence is the same as `ghta_r2_secrets.md` §5 — they are
complementary: the steady-state cadence runs even when no leak
occurred; this runbook (§2) runs whenever a chat-share happens
**regardless** of how recent the previous rotation was.

### Hard rule — never share token values via chat

| Wrong | Right |
|---|---|
| Screenshot the `Create API Token` modal and paste into chat | Copy the four values into the operator password manager, then `gh secret set` from a terminal where chat cannot read |
| Paste any of the four values as plain text in a chat prompt | Same — stdin paste only |
| Save the screenshot anywhere on disk for "reference" | The Cloudflare modal is the canonical reference; once dismissed, regen via §2.c. Never store screenshots of credentials |
| Tell the operator-AI "I'll send you the secret next" | Same rule — the AI does not need the value. Only `gh secret set` needs it |

The class of incident this runbook handles is exclusively "operator
sent the value to me anyway". The fix is to recognise the leak the
moment it lands and rotate immediately — not to debate whether this
particular chat surface "really" persists the value.

### Defensive sentinel — chat-share recognition heuristic

If you see any of the following in a chat session, assume a leak has
occurred and route the operator to this runbook:

- A screenshot containing the strings `Access Key ID`,
  `Secret Access Key`, and `https://[a-f0-9]{32}\.r2\.cloudflarestorage\.com`.
- A code block or message containing four lines that look like a base64
  string + a longer base64 string + an `r2.cloudflarestorage.com` URL
  + a bucket name.
- Any explicit mention of "I just pasted the R2 token" / "here is the
  R2 secret" / "here are the four values".

Recognition failure is not catastrophic — the rotation is cheap — but
silent recognition success means the rotation is already in motion
when the operator finishes typing.

## §4 Incident response — if the leaked token was actually used

The standard rotation (§2) closes the door, but if there is reason to
suspect the leaked token was **already** used by a third party between
chat-share and revoke, escalate to:

### §4.1 R2 access log review

```bash
# Cloudflare dashboard → R2 → autonomath-db-backup bucket → Logs tab.
# Look at the Access Log for the window starting from the chat-share
# timestamp and ending at the §2.b revoke timestamp.
# Filter by `cf.r2.access_key_id == <leaked Access Key ID>`.
```

Anything other than the expected `nightly-backup` / `weekly-backup-autonomath`
/ `restore-drill-monthly` workflow IPs (GitHub Actions egress ranges)
is a third-party hit. Cross-check timestamps against
`gh run list -w nightly-backup.yml -L 20` to rule out workflow runs.

### §4.2 Object integrity check

```bash
# For every backup object touched in the leak window, re-validate the
# SHA256 against the workflow-emitted manifest:
gh run list -w nightly-backup.yml -L 20 --json databaseId,createdAt,conclusion \
  | jq -r '.[] | select(.conclusion=="success") | .databaseId'
# For each run id, gh run view <id> --log emits the SHA256 of the uploaded gz.
# Pull each object from R2 and re-hash, compare to the workflow log.
aws s3 cp "s3://autonomath-db-backup/autonomath-api/jpintel-YYYYMMDD-HHMMSS.db.gz" - \
  --endpoint-url "https://<accountid>.r2.cloudflarestorage.com" | sha256sum
# Mismatch on any object = the leaked token was used to overwrite a backup.
```

A mismatch is a **disaster recovery integrity event** — the local
`/data/backups/` directory's 14-day on-Fly retention is then the only
remaining trustworthy copy. Do not delete the suspect R2 object;
preserve it for forensics, restore from Fly local instead.

### §4.3 Cloudflare audit log

```bash
# Cloudflare dashboard → Manage Account → Audit Log.
# Filter by `Action contains "r2"` and the window starting from
# chat-share timestamp.
# Look for: token reads, bucket-policy mutations, object-key
# enumerations, especially any that did not originate from the
# operator's account-IP range.
```

If audit log entries from third-party IPs are present, the breach is
not just "credentials in transit" — it has been weaponised. At that
point: rotate every R2 token (not just the leaked one), rotate the
Cloudflare account password + 2FA seed, and consider rotating
`FLY_API_TOKEN` and `STRIPE_SECRET_KEY` as adjacent blast-radius
defensive moves. Document the timeline in
`tools/offline/_inbox/_housekeeping_audit_2026_05_06/` (or the
session-current audit inbox).

### §4.4 If the integrity check passes

The leaked token was revoked before any third-party hit landed. Close
the incident with a one-line note in the audit doc
(`R8_R2_TOKEN_ROTATION_2026-05-07.md` — see Related), update the next
90-day rotation deadline, and resume normal ops. No customer-facing
disclosure required because no customer data is in the R2 backup
bucket beyond the operator-authored programs corpus (already public).

## Anti-patterns

- **Do NOT** skip §2.a (verify new secrets work before revoking old).
  Revoking first and finding the new pair misconfigured turns a
  10-minute rotation into an off-site DR outage of unknown duration.
- **Do NOT** mint the new token under a different name to "keep the
  leaked one as a fallback". The leaked token must die. Fallback is
  the on-Fly local `/data/backups/` 14-day retention — not a
  compromised credential.
- **Do NOT** edit `docs/runbook/ghta_r2_secrets.md` to reference this
  runbook unless the operator explicitly asks. That doc is the
  steady-state mirror procedure; this runbook is the post-leak
  variant. Cross-references already exist in the front-matter
  `Related:` block above.
- **Do NOT** put the leaked credential pair into a `.env.local` /
  `data/` / `scripts/` file "for the audit log". The audit doc
  records the rotation event, not the credential. Forensic forensic
  tooling needs only the Access Key ID prefix (~first 8 chars), which
  is non-secret.
- **Do NOT** weaken the fail-closed `R2 secrets not fully configured`
  check in `nightly-backup.yml`. The check is what surfaces a botched
  rotation within 24 hours instead of letting it persist silently.
