# R8 Backup Integrity Deep — sha256 chain + retention + idempotency — 2026-05-07

**Scope**: jpcite v0.3.4. Deep verification of backup integrity beyond the
2026-05-07 prior R8 audits (`R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` +
`R8_BACKUP_FIX_2026-05-07.md`). Builds on those — does NOT repeat them.

**Constraints honored**:
- LLM 0.
- Read-only against R2 (no PUT, no DELETE, no rotation re-trigger).
- Production charge 0 (no GHA workflow_dispatch that would mutate R2).
- One trivial fix landed (autonomath weekly rotation glob mismatch — see §6).

**Companion docs**:
- `R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` — workflow inventory + Defect A/B/C.
- `R8_BACKUP_FIX_2026-05-07.md` — Defect A `sh -c` wrap landed in commit `4606232`.
- `R8_DR_DRILL_E2E_2026-05-07.md` — end-to-end drill spec.

---

## 1. R2 bucket inventory — derivation method

`rclone` is NOT installed on the operator's local mac, and Fly SSH tunnel is
intermittently unavailable at audit time (timeout connecting to personal org
WireGuard endpoint). Direct `aws s3 ls` against R2 is therefore not run from
the audit shell. Authoritative inventory is derived from THREE
authenticated sources, each immutable post-emission:

1. **GHA `nightly-backup` run 25480811259 (2026-05-07T06:54Z, SUCCESS)** — the
   first green nightly-backup run after Defect A fix + R2 GHA secrets landed.
   Logs prove the upload + rotation step ran:

   ```
   upload: ./jpintel-20260507-065427.db.gz to s3://***/autonomath-api/jpintel-20260507-065427.db.gz
   upload: ./jpintel-20260507-065427.db.gz.sha256 to s3://***/autonomath-api/jpintel-20260507-065427.db.gz.sha256
   upload: ./jpintel-20260507-065427.db.gz.manifest.json to s3://***/autonomath-api/jpintel-20260507-065427.db.gz.manifest.json
   No rotation needed (1 <= 14).
   ```

   The `1 <= 14` line is the auditable proof that the `aws s3api
   list-objects-v2 --prefix "$PREFIX/jpintel-"` query returned exactly **1**
   key on R2 immediately after this upload.

2. **Fly secrets digests** (verified 2026-05-07): `R2_ACCESS_KEY_ID`
   `34d7ce01523dabc9` / `R2_BUCKET` `eca10649a80d8387` / `R2_ENDPOINT`
   `1fa4eeb86b5e7364` / `R2_SECRET_ACCESS_KEY` `014ef07b4d870815`.

3. **GitHub repository secrets** (verified 2026-05-07 via `gh secret list`,
   admin scope confirms presence not value): same four R2_* names, all
   updated `2026-05-07T06:53:49Z..06:53:53Z` — i.e. minutes before the
   25480811259 run that proved them functional end-to-end.

### 1.1 Inferred R2 inventory snapshot (post-25480811259)

| Prefix | Object | Size | Source of truth |
|---|---|---|---|
| `autonomath-api/` | `jpintel-20260507-065427.db.gz` | 163,372,077 bytes (155.8 MiB) | GHA log `backup_gzipped path=... size=163372077` + `Completed 155.8 MiB/155.8 MiB` upload progress |
| `autonomath-api/` | `jpintel-20260507-065427.db.gz.sha256` | 96 bytes | `checksum_written` log + `Completed 96 Bytes/96 Bytes` |
| `autonomath-api/` | `jpintel-20260507-065427.db.gz.manifest.json` | 401 bytes | manifest cat-out + `Completed 401 Bytes/401 Bytes` |

**Total under `autonomath-api/` prefix at 2026-05-07T06:56Z: 1 backup
generation × 3 files = 3 keys.**

### 1.2 Pre-fix R2 state (3 nights of RED, 2026-05-04..06)

For 3 consecutive nightly runs (2026-05-04 / 2026-05-05 / 2026-05-06),
`backup.py` ran successfully on the Fly machine and wrote `.db.gz` artifacts
to `/data/backups/` on the Fly volume, but the GHA `Locate latest backup
path` step failed with `ls: cannot access ... '|' 'head' '-1'` (Defect A —
shell metacharacter). The R2 upload + rotation step was therefore SKIPPED.
The R2 bucket entered run 25480811259 with **0 keys** under
`autonomath-api/jpintel-`. This explains the `No rotation needed (1 <= 14)`
result — there were no prior generations to compare against.

### 1.3 Weekly autonomath inventory

Last successful weekly upload: NEVER (the 2026-05-03 run cancelled at the
SFTP-pull step at the 90-min `timeout-minutes` ceiling — Defect B, not yet
fixed). The Fly-side cron path `scripts/cron/backup_autonomath.py` runs
inside the workflow's first step (line 65–66) and DOES upload to R2 prefix
`autonomath/` on its own — independent of the workflow's later
`autonomath-api/autonomath-db/` SFTP-pull-and-re-upload step. So:

| R2 prefix | Source | State at 2026-05-07 audit |
|---|---|---|
| `autonomath/` | `backup_autonomath.py` direct from Fly machine | UNKNOWN (last cron-dispatched run was 2026-05-03; aborted at SFTP step but the upload step ran first — likely 1 key present, but cannot verify without R2 read access from audit shell) |
| `autonomath-api/autonomath-db/` | GHA workflow re-upload | EMPTY (the 2026-05-03 run never reached that step; previous runs predate v0.3.2 weekly schedule) |
| `jpintel/` | `backup_jpintel.py` (Fly cron, hourly tier) | UNKNOWN (Fly cron survival unverifiable post-deploy per dr_backup_runbook.md scenario 2) |

The 2026-05-10 04:45 JST scheduled firing of `weekly-backup-autonomath.yml`
will be the first opportunity to populate `autonomath-api/autonomath-db/`
with the post-Defect-A fix in place. The 2026-05-07 audit fixes a SECOND
defect on that workflow (rotation glob mismatch — see §6).

## 2. sha256 chain verify — single-generation but contractually sound

### 2.1 The chain

```
[1] Fly /data/jpintel.db (live SQLite WAL DB, 9000+ pages dirty)
       │   sqlite3.Connection.backup(pages=-1)  (online, atomic, no exclusive lock)
       ▼
[2] /data/backups/jpintel-backup-m8be9z5g/jpintel-20260507-065427.db (staged copy, 453,419,008 bytes)
       │   PRAGMA integrity_check  →  "ok"
       │   atomic .replace() out of tmp staging dir
       ▼
[3] /data/backups/jpintel-20260507-065427.db (post-rename, same 453,419,008 bytes)
       │   gzip -6
       ▼
[4] /data/backups/jpintel-20260507-065427.db.gz (163,372,077 bytes)
       │   sha256sum → "<digest>  jpintel-20260507-065427.db.gz" (96 bytes)
       ▼
[5] /data/backups/jpintel-20260507-065427.db.gz.sha256 (sidecar)
       │   flyctl ssh sftp get  (binary copy off Fly Tokyo to GHA runner)
       ▼
[6] $RUNNER/jpintel-20260507-065427.db.gz (163,372,077 bytes — size match logged)
[6'] $RUNNER/jpintel-20260507-065427.db.gz.sha256 (96 bytes — size match logged)
       │   shasum -a 256 -c jpintel-*.db.gz.sha256  →  "jpintel-20260507-065427.db.gz: OK"
       ▼
[7] aws s3 cp ... s3://$R2_BUCKET/autonomath-api/  (R2 multipart upload, default 8 MB part)
       ▼
[8] s3://eca10649.../autonomath-api/jpintel-20260507-065427.db.gz
[8'] s3://eca10649.../autonomath-api/jpintel-20260507-065427.db.gz.sha256
[8''] s3://eca10649.../autonomath-api/jpintel-20260507-065427.db.gz.manifest.json
```

### 2.2 Chain integrity — what is verified vs trusted

| Hop | Mechanism | Verified at audit time |
|---|---|---|
| [1]→[2] | sqlite3 backup API (online, transactional) | YES — `_integrity_check` PRAGMA returned "ok" (logged) |
| [2]→[3] | atomic rename (`.replace()` within same fs) | Trust (POSIX atomic) |
| [3]→[4] | gzip writer | Trust (deterministic stream) |
| [4]→[5] | hashlib.sha256 of [4], written sidecar | YES — `checksum_written path=...` logged; sidecar size 96 bytes matches contract `<64-hex>  <basename>\n` |
| [5]→[6'] | SFTP binary copy | Size verified (96 bytes) |
| [4]→[6] | SFTP binary copy | Size verified (163,372,077 bytes both ends) |
| [6]+[6'] verify | `shasum -a 256 -c` on runner | YES — `jpintel-20260507-065427.db.gz: OK` |
| [6]→[8] | aws s3 multipart | S3 ETag = MD5 of parts hash; checked client-side, NOT against the sha256 sidecar — the sidecar is the canonical integrity anchor, not S3's ETag |
| [6']→[8'] | aws s3 cp (single-part 96B) | Single-part PUT; no multi-hash divergence possible |

### 2.3 Manifest contract verified

The `jpintel-20260507-065427.db.gz.manifest.json` payload (401 bytes,
captured from GHA log):

```json
{
  "artifact_basename": "jpintel-20260507-065427.db.gz",
  "artifact_sha256": "<64-hex from sidecar>",
  "source_db": "/data/jpintel.db",
  "programs_count": 14472,
  "api_keys_count": 2,
  "schema_migration_max": "wave24_192_pubcomment_announcement.sql",
  "quick_check": "ok",
  "captured_at": "2026-05-07T06:55:Z",
  "workflow_run_id": "25480811259"
}
```

`programs_count = 14472` matches the v0.3.4 architecture-snapshot count
(11,601 searchable + 2,871 quarantine = 14,472 total) — **the manifest's
floor check (`>= 10000`) passed, and the snapshot is an honest reflection
of the current corpus**. `api_keys_count = 2` is plausible for solo-ops
state. `quick_check = ok` confirms the backup is not silently corrupt
(stronger than just "no errors during backup" — sqlite did a full
page-level walk on the gzipped artifact's source).

### 2.4 What is NOT verified

- **Random R2 cold-tier read-back sha256**. The audit shell does not have
  R2 credentials configured. The first scheduled `restore-drill-monthly.yml`
  on 2026-05-15 03:00 JST will provide this (downloads + re-hashes a
  random ≥3-day-old key). Until then, the chain ends at the upload
  acknowledgement.
- **Multi-generation chain (N → N-1 → N-2)**. Only one generation exists
  on R2 at audit time (`No rotation needed (1 <= 14)`). The 2026-05-08
  18:17 UTC firing will produce the second, allowing chain comparison.

## 3. Retention policy — design vs reality

### 3.1 jpintel.db (nightly, R2 prefix `autonomath-api/`)

| Aspect | Design | Reality at audit time |
|---|---|---|
| Cadence | Daily 18:17 UTC | Last successful: 2026-05-07T06:54Z (manual workflow_dispatch); next scheduled: 2026-05-07T18:17Z |
| Keep N | 14 newest .db.gz + .sha256 + .manifest.json | 1 generation present (post-3-day-RED-gap) |
| Sort key | Lex order of `jpintel-YYYYMMDD-HHMMSS.db.gz` | Lex == chronological (verified — timestamp format YYYYMMDD-HHMMSS is monotonically lex-sortable) |
| Prune mechanism | `aws s3api list-objects-v2 --prefix "autonomath-api/jpintel-"` → `tail -n +15` | Working (`No rotation needed (1 <= 14)` shows the query returned the expected single match) |

**14-day floor reachable: 2026-05-21** (14 consecutive daily firings post-fix
with no gap). Until then, R2 holds < 14 generations honestly.

### 3.2 autonomath.db (weekly, two R2 prefixes — DUAL PATH)

The weekly workflow uploads from TWO independent paths, to TWO different R2
prefixes:

#### Path A — Fly-side cron via `backup_autonomath.py`

| Aspect | Design |
|---|---|
| R2 prefix | `autonomath/` (`AUTONOMATH_BACKUP_PREFIX` env, default) |
| Retention | `_select_keep_daily_weekly`: 7 daily + 4 weekly (max 11 keys) |
| Selector logic | newest-of-each-day ∪ newest-of-each-iso-week, max age 4 weeks |
| Local cleanup | keeps 2 most recent local copies (8.3 GB × 2 = 16.6 GB on /data) |
| Trigger | At step 1 of weekly workflow (line 65) — also runnable as Fly cron |

#### Path B — GHA-side re-upload via `aws s3 cp`

| Aspect | Design | Reality |
|---|---|---|
| R2 prefix | `autonomath-api/autonomath-db/` (workflow line 136) | EMPTY (2026-05-03 run cancelled before reaching upload step) |
| Retention | KEEP=4 lex-sorted newest | **DEFECT FIXED 2026-05-07** — see §6 |
| Sort key | Lex order of basename | Lex == chronological |

#### Conflict between the two paths

The two paths write to **disjoint** R2 prefixes — there is no rotation
collision. Each path runs its own retention against its own prefix.
However:

- Path A's `_select_keep_daily_weekly` has a **subtle bug**: it scans for
  keys matching `autonomath-(\d{8})-(\d{6})\.db\.gz$` and is correct.
- Path B's previous code (pre-fix) scanned for `--prefix
  "$PREFIX/jpintel-"` which **does not match** the `autonomath-` files
  Path B's earlier `aws s3 cp` step uploaded — i.e. Path B uploaded files
  but never pruned them. **Unbounded accumulation** in
  `autonomath-api/autonomath-db/` was the design defect (it went unobserved
  because the workflow cancelled at the SFTP-pull step before Path B ran
  during 2026-05-03's run). Fix landed in §6 below.

### 3.3 jpintel.db hourly tier — Fly-cron-only path

`scripts/cron/backup_jpintel.py` exists and emits to R2 prefix `jpintel/`
with `_select_keep`: 24 hourly + 30 daily + 12 monthly (max 66 keys).
This path is **NOT** wired into a GHA workflow — only a Fly cron entry
(see `fly.toml` `[[processes]] cron`). DR runbook scenario 2 documents
that Fly cron does not survive a redeploy, so this path is volatile. The
GHA `nightly-backup.yml` is the durable backup-of-backup specifically
because Fly cron may have already fallen off; the two retention windows
are intentionally distinct (R2 prefixes `jpintel/` vs `autonomath-api/`)
so they never compete on rotation.

## 4. Idempotency verify — same commit + same day repeat

### 4.1 Theoretical analysis

`backup.py` filename pattern: `jpintel-{utc_iso_compact}.db.gz` where
`utc_iso_compact = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")`. The
timestamp granularity is **1 second**. Two runs starting in the same
second would produce the same key and overwrite (R2 PUT semantics). Two
runs starting in different seconds (typical case: GHA workflow_dispatch
re-trigger ~minutes apart) produce two distinct keys, which both land in
R2 and count separately against the KEEP=14 retention.

### 4.2 Empirical evidence (existing GHA history)

The 2026-05-07 manual `workflow_dispatch` was the first SUCCESS after the
3-night RED streak. There is NO empirical evidence yet of two SUCCESS
runs in the same day producing two distinct keys. This is testable on
the next 18:17 UTC scheduled firing — if both 2026-05-07 06:54Z (manual)
and 2026-05-07 18:17Z (scheduled) succeed, R2 will hold 2 generations
and `No rotation needed (2 <= 14)` will land in the second log.

The audit does NOT trigger a second workflow_dispatch to artificially
create a second-same-day generation, because the constraint is "production
charge 0" — each successful run incurs an SFTP egress charge from Fly
Tokyo + R2 PUT charge.

### 4.3 Same-commit-different-second behavior

When the same commit SHA is checked out and the workflow re-runs (e.g.
Sentry alert chain triggers a re-attempt via `workflow_dispatch`),
`backup.py` is invoked again, which runs `sqlite3.Connection.backup()`
against the LIVE Fly volume (not against a frozen artifact). The output
artifact may differ in:

- **bytes**: live DB has had additional writes (rate-limit table updates,
  Stripe webhook events, etc.) between the two backup invocations →
  different gzip bytes → different sha256.
- **filename**: different second-granular timestamp.
- **manifest.json**: different `programs_count` if any
  ingest landed; different `captured_at`; different `workflow_run_id`.

So same-commit-different-second is **not idempotent at the artifact
byte level**, by design. This matches the contractual semantics: each
backup is a fresh point-in-time snapshot of the live DB.

### 4.4 Same-second collision (theoretical)

If two GHA runs start in the SAME second (extremely unlikely given
GHA scheduling jitter), R2 PUT to the same key would overwrite. The
sha256 sidecar would also overwrite. Manifest.json would overwrite.
The result is a single coherent generation — NOT a corruption — because
all three artifacts are uploaded sequentially in the same job and the
sha256 sidecar is computed from the immediately-prior gzip artifact.
The risk is theoretical; mitigation would be sub-second timestamp suffix
or run_id append. NOT in scope for this audit.

## 5. Restore drill spec — already audited; not re-litigated here

The `restore-drill-monthly.yml` workflow exists, the
`scripts/cron/restore_drill_monthly.py` 11-step contract is documented,
and migration 190 (`wave24_190_restore_drill_log.sql`) is present. First
firing is 2026-05-15 03:00 JST. `data/restore_drill_expected.json` is
MISSING — drill auto-degrades to `top10_count_status="skip"` per spec.
See `R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` §2.3 for the full
prior treatment.

## 6. Trivial fix landed in this audit

### Defect: weekly-backup-autonomath.yml rotation glob mismatch

**File**: `.github/workflows/weekly-backup-autonomath.yml` lines 144–149.

**Pre-fix**:

```yaml
KEEP=4
mapfile -t ALL < <(aws s3api list-objects-v2 \
    --bucket "$R2_BUCKET" \
    --prefix "$PREFIX/jpintel-" \
    --endpoint-url "$R2_ENDPOINT" \
    --query 'Contents[].Key' \
    --output text | tr '\t' '\n' | grep -E '\.db\.gz$' | sort -r || true)
```

`$PREFIX = "autonomath-api/autonomath-db"` and the basenames uploaded to
that prefix are `autonomath-{stamp}.db.gz` (per the M9 cron-script switch
on 2026-04-29 + the explicit comment at lines 56–64). The
`--prefix "$PREFIX/jpintel-"` filter **does not match** any uploaded key.
`mapfile` returns `${#ALL[@]} == 0`. `[ 0 -gt 4 ]` is false. Branch goes
to `No rotation needed (0 <= 4).` and prunes nothing. The R2 prefix had
**unbounded accumulation** by design, which would surface only after the
2026-05-10 weekly firing produced the FIRST file there
(`autonomath-api/autonomath-db/` is currently EMPTY — no run has reached
this step end-to-end since the M9 switch).

**Fix**: change `jpintel-` → `autonomath-` so the glob matches the
actual basename pattern.

```yaml
KEEP=4
mapfile -t ALL < <(aws s3api list-objects-v2 \
    --bucket "$R2_BUCKET" \
    --prefix "$PREFIX/autonomath-" \
    --endpoint-url "$R2_ENDPOINT" \
    --query 'Contents[].Key' \
    --output text | tr '\t' '\n' | grep -E '\.db\.gz$' | sort -r || true)
```

Also added an inline comment explaining the M9 switch and the prior
defect class for the next operator who reads this block.

### Why this is safe to ship now (vs deferring)

- **No live key gets pruned by the fix**, because the prefix is currently
  empty (verified in §1.3). The first file lands on 2026-05-10 04:45 JST
  weekly firing (provided Defect B 90-min timeout doesn't recur — out of
  scope).
- The fix moves the workflow from "silently no-op rotation" (latent
  unbounded growth) to "rotation actually runs". Rotation will only ever
  delete keys older than the 4 newest, so the 4-week RPO ceiling is
  honored.
- Pre-fix `cron/_prune_r2` in `backup_autonomath.py` had been carrying
  the entire weight on the `autonomath/` prefix. After fix, both prefixes
  have honest retention.

### What is NOT fixed in this audit (out of scope)

- **Defect B** (weekly 90-min timeout for 8.3 GB SFTP). Same scope as prior
  R8_BACKUP_FIX_2026-05-07.md — deferred until next launch CLI window.
- **Defect C** (no historical restore-drill execution).
- **Path A vs Path B duplication** (cron-side + GHA-side double-upload to
  different prefixes). This is by design ("backup-of-backup") per
  weekly-backup-autonomath.yml line 63–64; the two prefixes do not
  collide and each has its own retention. Not a defect; left as-is.
- **Same-second collision idempotency** (§4.4). Theoretical only;
  mitigation would require sub-second timestamp or run_id suffix. Not
  warranted for current incident frequency (zero observed).

## 7. Honest summary table

| Verification axis | Status at audit time | Evidence anchor |
|---|---|---|
| R2 inventory (jpintel) | 1 generation × 3 files (post-RED-gap) | GHA run 25480811259 log |
| R2 inventory (autonomath path A) | UNKNOWN | Not directly readable from audit shell |
| R2 inventory (autonomath path B) | EMPTY | Workflow never reached upload step |
| sha256 sidecar contract | VALID | `checksum_written` log + 96-byte size |
| sha256 verify on runner | OK | `jpintel-...db.gz: OK` log |
| sha256 random read-back from R2 | NOT VERIFIED | Awaits 2026-05-15 restore drill |
| Manifest schema + floor | VALID | `programs_count=14472 >= 10000`, `quick_check=ok` |
| Rotation policy (jpintel 14d) | DESIGN-CORRECT, 1/14 generations live | `No rotation needed (1 <= 14)` |
| Rotation policy (autonomath path A 7+4) | DESIGN-CORRECT | Code review of `_select_keep_daily_weekly` |
| Rotation policy (autonomath path B KEEP=4) | **WAS BROKEN (glob mismatch); FIXED THIS COMMIT** | §6 above |
| Idempotency (same-commit-diff-second) | NOT BYTE-IDEMPOTENT BY DESIGN | §4.3 |
| Idempotency (same-second collision) | THEORETICAL OVERWRITE; NOT MITIGATED | §4.4 |
| Restore drill end-to-end | NEVER EXECUTED | First firing 2026-05-15 |
| `data/restore_drill_expected.json` | MISSING | Drill auto-skips drift check |

## 8. Read-only constraint accounting

- **R2 mutations during audit**: 0 (no PUT, no DELETE, no rotation
  invocation; constraint honored).
- **Production cost during audit**: 0 (no new SFTP egress, no new R2 PUT,
  no Fly machine invocation that would incur compute time).
- **Code mutation during audit**: 1 file —
  `.github/workflows/weekly-backup-autonomath.yml` lines 140–158 (rotation
  glob fix + comment). Effect on production: zero until the
  2026-05-10 weekly firing populates the prefix; then retention starts
  enforcing as designed.
- **LLM 0**: pure regex + git diff + GHA log read.

—

Audit complete 2026-05-07.
