---
title: GHA R2 secrets mirror runbook
updated: 2026-05-07
operator_only: true
category: secret
---

# GHA R2 secrets mirror runbook — Fly secret store ≠ GHA secret store

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Status**: actionable — required to close the off-site DR durability gap
that surfaced in the 2026-05-07 R8 backup/restore drill audit.
**Related**: `docs/runbook/disaster_recovery.md` §2 (R2 token quartet),
`docs/runbook/litestream_setup.md` Step 2 (same R2 token set), `docs/runbook/secret_rotation.md`
(boot-gated Fly secrets — different scope).
**Last reviewed**: 2026-05-07

This runbook is the operator procedure to mirror the four `R2_*` secrets
into the **GitHub repository** secret store so that nightly-backup,
weekly-backup-autonomath, and restore-drill-monthly workflows can talk to
Cloudflare R2.

The Fly secret store and the GitHub repository secret store are **two
independent stores**. Setting a secret in one does NOT propagate to the
other. The R2 quartet currently lives only in the Fly secret store
(`autonomath-api` app), so all three R2-touching GHA workflows fail the
"Upload to Cloudflare R2 and rotate" step (and equivalents) with
`::error::R2 secrets not fully configured`.

## §1 Root cause — two independent secret stores

| Store | Scope | Consumer | Set with |
|---|---|---|---|
| Fly.io app secrets (`autonomath-api`) | Runtime env on the Fly machine | `src/jpintel_mcp/` Python code, Fly cron | `flyctl secrets set X=... -a autonomath-api` |
| GitHub repository secrets (`shigetosidumeda-cyber/autonomath-mcp`) | Workflow env on `ubuntu-latest` runners | `.github/workflows/*.yml` | `gh secret set X` |

Status snapshot 2026-05-07:

- **Fly secrets** (production runtime — verified via `flyctl secrets list -a autonomath-api`):
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, `R2_BUCKET` all **deployed**.
- **GHA repository secrets** (CI workflows — verified via `gh secret list`):
  `FLY_API_TOKEN`, `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` only — **R2 quartet absent**.

Effect:

- `nightly-backup.yml` Upload step fails fail-closed (workflow run 25477213040 captured the error).
- `weekly-backup-autonomath.yml` skips R2 upload with a warning (8.3 GB autonomath.db has no off-site mirror past the on-machine `/data/backups-autonomath/` retention).
- `restore-drill-monthly.yml` cannot read from R2 to verify a backup, so the DEEP-62 audit row never lands.

The fix is **not** to copy values out of Fly (the Fly CLI does not echo secret values; `flyctl ssh tunnel` to extract them via the runtime env hit the wireguard timeout this session). The fix is to mint or re-use an R2 API token at the Cloudflare dashboard and `gh secret set` the four values into the GHA store directly.

## §2 R2 API token — get the value

Two paths. Both produce the same four values; pick whichever is faster.

### §2.1 Path A — re-use the existing token

If the operator's password manager (or `.env.local` / Bitwarden) already
has the R2 token that was set into Fly, **re-use it**. There is no benefit
to minting a second token; rotating one without the other creates the same
"two stores diverged" failure mode in reverse. The only requirement is
that the token still has Object Read & Write on the
`autonomath-backups` bucket (or whatever bucket the `R2_BUCKET` Fly secret
points at — currently `autonomath-backups`).

Verify the token is still alive before reusing it:

```bash
# Quick aws-cli probe against R2 (Object Read scope is enough for this).
AWS_ACCESS_KEY_ID="<paste from password manager>" \
AWS_SECRET_ACCESS_KEY="<paste from password manager>" \
AWS_DEFAULT_REGION=auto \
aws s3 ls "s3://autonomath-backups/" \
  --endpoint-url "https://<accountid>.r2.cloudflarestorage.com" \
  | head -5
# expected: a few jpintel-*.db.gz keys; non-zero exit means the token is dead.
```

### §2.2 Path B — mint a fresh token

If no password-manager copy exists, or the existing token is expired:

1. Open the Cloudflare dashboard → R2 → **Manage API Tokens** → **Create Token**.
2. Token name: `autonomath-backup-gha-2026-05-07` (date-stamp helps the 90-day rotation audit).
3. Permissions: **Object Read & Write** scope on `autonomath-backups` bucket only (least privilege — do not grant Admin Read & Write or All buckets).
4. TTL: 90 days (matches the rotation cadence below). Cloudflare will not let you pin to "no expiration" on Object scope tokens; pick the longest available.
5. Click **Create API Token**. Cloudflare shows the credential **once** — copy:
   - Access Key ID (alphanumeric, ~32 chars)
   - Secret Access Key (longer base64-style)
   - The S3 endpoint URL (`https://<accountid>.r2.cloudflarestorage.com`)
   - The bucket name (`autonomath-backups`, or whatever your bucket is named)
6. Paste the four values into the operator password manager **before** closing the modal — there is no way to recover the secret access key after dismissal.

Note: the Fly secret values stay untouched in this path. After the next
90-day rotation cycle (§5) you can rotate both stores in lockstep so they
keep drifting in sync.

## §3 GHA secret set — four commands (stdin paste)

Run from the repo root. `gh secret set` reads stdin when the value is not
passed as a flag, which keeps the secret out of shell history. Paste the
value, hit Return, then Ctrl-D.

```bash
gh secret set R2_ACCESS_KEY_ID
# (paste Access Key ID, Return, Ctrl-D)

gh secret set R2_SECRET_ACCESS_KEY
# (paste Secret Access Key, Return, Ctrl-D)

gh secret set R2_ENDPOINT
# (paste https://<accountid>.r2.cloudflarestorage.com, Return, Ctrl-D)

gh secret set R2_BUCKET
# (paste autonomath-backups, Return, Ctrl-D)
```

Repository scope is the default (`gh secret set` writes to
`shigetosidumeda-cyber/autonomath-mcp` from the repo root). If for any
reason the working directory is wrong, pin explicitly:

```bash
gh secret set R2_ACCESS_KEY_ID --repo shigetosidumeda-cyber/autonomath-mcp
```

Do **not** use `--body` or `--body-file` with the literal value pasted
into the command — that puts the secret into shell history and may leak
into `.zsh_history` / clipboard managers / terminal scrollback. The
stdin-paste form above is the only safe variant for solo zero-touch.

## §4 Verify

```bash
# 1. Listing should now show six entries (FLY_API_TOKEN, ACK_YAML, plus the R2 quartet).
gh secret list
# expected: at least
#   R2_ACCESS_KEY_ID         Updated 2026-05-07
#   R2_BUCKET                Updated 2026-05-07
#   R2_ENDPOINT              Updated 2026-05-07
#   R2_SECRET_ACCESS_KEY     Updated 2026-05-07

# 2. Trigger an immediate run of nightly-backup so the R2 upload step fires now,
#    not at 18:17 UTC.
gh workflow run nightly-backup.yml

# 3. Watch the run — the "Upload to Cloudflare R2 and rotate" step should
#    transition to PASS within 5-10 minutes (depends on Fly SFTP throughput).
gh run watch
# (interrupt with Ctrl-C once the Upload step turns green; rotation runs after.)

# 4. Confirm an artifact landed on R2 with the same SHA256 the workflow emitted.
aws s3 ls "s3://autonomath-backups/autonomath-api/" \
  --endpoint-url "https://<accountid>.r2.cloudflarestorage.com" \
  | tail -3
# expected: today's jpintel-YYYYMMDD-HHMMSS.db.gz + .sha256 + .manifest.json triplet.

# 5. Optional — kick the weekly autonomath workflow too if waiting until 2026-05-10
#    is too long. 8.3 GB SFTP pull, ~25 min run.
gh workflow run weekly-backup-autonomath.yml
```

If the Upload step still fails after the four `gh secret set` commands:

- **Symptom**: `::error::R2 secrets not fully configured`. Means at least
  one of the four secrets is empty / wrong scope. Re-run `gh secret list`;
  every entry should carry today's `Updated` date. Re-set any whose date
  is older or whose name is mistyped.
- **Symptom**: `aws s3 cp` 403 / `InvalidAccessKeyId`. Means the token is
  scoped wrong (Read-only) or to the wrong bucket. Mint a new token per
  §2.2 with **Object Read & Write** on `autonomath-backups` and re-set.
- **Symptom**: the workflow passes the secret check but fails on `aws s3
  cp`. Means `R2_ENDPOINT` is wrong (missing scheme, missing accountid).
  Verify the endpoint matches `https://<accountid>.r2.cloudflarestorage.com`
  exactly — no trailing slash, no path component.

## §5 Ongoing rotation (90-day cadence)

R2 API tokens minted via §2.2 carry a 90-day TTL (Cloudflare's max for
Object-scope tokens at time of writing). Schedule a calendar reminder for
**~80 days after `gh secret set`** so the rotation closes before the
token expires.

```bash
# 1. Mint a fresh token at the Cloudflare dashboard (same scope as §2.2).
# 2. Update both stores in the same operator session — DO NOT update one
#    and walk away. Diverged stores cause silent off-site DR loss until
#    the next backup workflow run surfaces the failure.

# 2a. GHA store (this runbook).
gh secret set R2_ACCESS_KEY_ID
gh secret set R2_SECRET_ACCESS_KEY
# (R2_ENDPOINT and R2_BUCKET typically don't change on token rotation —
#  re-set only if the bucket or accountid changed.)

# 2b. Fly store (cross-runbook — disaster_recovery §2 + litestream Step 2).
flyctl secrets set R2_ACCESS_KEY_ID="<new>" -a autonomath-api
flyctl secrets set R2_SECRET_ACCESS_KEY="<new>" -a autonomath-api

# 3. Trigger nightly-backup immediately to verify the new token is live.
gh workflow run nightly-backup.yml

# 4. Once the new token is verified live in BOTH stores, revoke the old
#    token at the Cloudflare dashboard so a leaked-old-token scenario
#    cannot replay against the bucket.
```

If the operator forgets and the token expires mid-rotation: the workflow
will fail with `aws s3 cp` 403 / `InvalidAccessKeyId`. The recovery is
identical to §5 step 1-3 (mint new + set both stores + trigger workflow).
There is no data loss because the on-machine `/data/backups/` directory
keeps a 14-day local retention regardless of R2 reachability.

## Anti-patterns

- **Do NOT** generate a separate R2 token for GHA "to keep it isolated".
  The Fly + GHA workflows hit the same R2 bucket with the same access
  pattern. Two tokens means two rotation deadlines, two leak surfaces,
  and twice the chance of a diverged-stores outage. One token, two
  stores, lockstep rotation.
- **Do NOT** set the secret via `--body "<paste>"` (shell history leak)
  or via the GitHub web UI form (no audit trail outside the GitHub
  events log). Stdin paste via the bare `gh secret set <NAME>` form is
  the only safe variant.
- **Do NOT** weaken the fail-closed check in `nightly-backup.yml` to
  silence the workflow while you are figuring out the rotation. The
  fail-closed semantics (2026-05-03 hardening) are what made this gap
  visible in the first place — silencing it would push the next outage
  into an "off-site DR durability is gone and we did not notice" mode.
- **Do NOT** commit the R2 token to `.env.local`, `fly.toml`, or any file
  under `data/` / `scripts/` / `tests/`. The CI grep gate
  (`tests/test_no_default_secrets_in_prod.py`) blocks placeholders;
  there is no equivalent gate for an actual leaked R2 secret because by
  the time it lands in the repo, the token is already burned.
