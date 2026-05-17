# CL19 — Cloudflare Pages deploy state audit (2026-05-17 evening)

[lane:solo] | READ-ONLY | New file only (CodeX collision avoidance)

> CL14 (`6deaa23cd`) catalogued 6 public-surface files that landed on disk SOT
> but never reached the Cloudflare Pages production deploy. CL19 follows up
> with a focused audit of the **deploy pipeline itself** to identify the
> trigger that has to fire (and the gate that has to clear) before all 6 of
> those surfaces flip to 200 on jpcite.com.
>
> Audit anchors: branch `main`, current HEAD `b3395bd5c`, `pages-deploy-main`
> workflow id `268326879` (`active`), `autonomath` Cloudflare Pages project.

---

## Section 1 — 6 surface × CF Pages deploy coverage

Disk SOT vs. live `https://jpcite.com/` HTTP status (verified 2026-05-17 22:0X JST,
cache-busted with `?_cl19=<ts>` query, `-L` follow redirects).

| # | URL path | Disk SOT path | Disk SOT mtime | Live HTTP | CF Pages config covers it? |
|---|----------|---------------|----------------|-----------|----------------------------|
| 1 | `/llms.txt` | `site/llms.txt` | committed | **200 STALE** | Yes — rsync includes top-level `*.txt`; `_headers` line 107 sets `text/plain; charset=utf-8`. |
| 2 | `/.well-known/agents.json` | `site/.well-known/agents.json` (8,486 B, mtime 17:41 JST) | committed | **200 STALE** | Yes — rsync includes `.well-known/`; smoke step validates it on every run. |
| 3 | `/.well-known/jpcite-justifiability.json` | `site/.well-known/jpcite-justifiability.json` (5,526 B, mtime 21:50 JST) | committed | **404** | Disk-only — no dedicated `_headers` / `_redirects` entry needed (served as static JSON via default rule). |
| 4 | `/why-jpcite-over-opus` | `site/why-jpcite-over-opus.html` | committed | **404** | Yes — `_redirects` line 253: `/why  /why-jpcite-over-opus  301`. Static HTML resolves by extensionless rewrite (Pages default). |
| 5 | `/.well-known/jpcite-federated-mcp-12-partners.json` | `site/.well-known/jpcite-federated-mcp-12-partners.json` (9,421 B, mtime 17:28 JST) | committed | **404** | Disk-only — covered by `.well-known/` rsync include. |
| 6 | `/sitemap-structured.xml` | `site/sitemap-structured.xml` | committed | **404** | Yes — rsync includes top-level `*.xml`; sitemap-index.xml indexes it. |

Surfaces 1–2 return 200 with **stale ETag** (last reachable production deploy
served older bodies). Surfaces 3–6 return **404** because the deploy that
introduced them never made it to Cloudflare Pages.

Conclusion: every one of the 6 surfaces is **structurally deployable** — none
require new `_redirects` / `_headers` rules. The block is purely in the
publish pipeline.

---

## Section 2 — GHA `pages-deploy-main` recent run state

`gh workflow list` confirms two active deploy workflows in scope:

| id | name | state |
|----|------|-------|
| `268326879` | `pages-deploy-main` | active |
| `275048588` | `deploy-jpcite-api` | active (Fly app deploy, not Pages) |

Workflow file `.github/workflows/pages-deploy-main.yml` is the canonical
Cloudflare Pages publish path. Triggers (lines 48-92):

- `push` to `main` filtered on a long path glob (`site/**`, `docs/**`,
  `functions/**`, several `scripts/regen_*` and `scripts/generate_*`, plus
  the workflow file itself).
- `workflow_dispatch` with `deploy_mode` input (`auto` / `fast` / `full`).

### Recent 100 runs (queried 2026-05-17 night)

| metric | count |
|--------|-------|
| `success` in last 100 runs | **0** |
| `failure` in last 100 runs | 99 |
| `in_progress` at audit time | 1 (run `25991598458`, scheduled from CL14 commit) |
| oldest run scanned | 2026-05-17T07:43:16Z |
| newest completed run | 2026-05-17T12:59:53Z (failure) |

### Latest 9 completed runs (all `pages-deploy-main`)

| run id | created (UTC) | conclusion | trigger commit subject |
|--------|---------------|------------|------------------------|
| 25991598458 | 13:01:36 | in_progress | docs(audit): public docs state SOT (llms+sitemap+well-known) … |
| 25991555449 | 12:59:53 | failure | docs(audit): D1-D5 consolidation SOT [lane:solo] |
| 25991500877 | 12:57:22 | failure | docs(brief): operator full-state SOT 2026-05-17 evening [lane:solo] |
| 25991346816 | 12:50:27 | failure | docs(audit): 7/7 production gate 4 fail root cause audit [lane:solo] |
| 25991315798 | 12:49:09 | failure | docs: CL1 A5+A6+P4+P5 PR #245 merge log (2026-05-17, BLOCKED) (#246) |
| 25991274772 | 12:47:16 | failure | docs(CROSS-CLI): Claude side Day 1 evening update for CodeX [lane:solo] |
| 25991220650 | 12:45:00 | failure | (pages-deploy-main) |
| 25990010091 | 11:49:53 | failure | (pages-deploy-main) |
| 25988763575 | 10:49:35 | failure | (pages-deploy-main) |
| 25987029999 | 09:24:39 | failure | (pages-deploy-main) |

The single in-progress run was triggered by CL14 itself. All others ran to
completion and **failed at the same step**.

### Failing step (constant across the cohort)

`gh run view 25991220650 --json jobs` returns:

```
job: Deploy regenerated site/ to Cloudflare Pages   conclusion=failure
  FAIL step: Run deploy drift gates                  conclusion=failure
```

`--log-failed` extract (run 25991220650 ≈ commit `02934a1cc` "FF2 cost-saving
validator run + drift sweep evening"):

```
FAIL site/openapi/v1.json is stale; run the exporter and commit the result:
FAIL site/openapi.agent.json is stale; run the exporter and commit the result:
FAIL site/openapi/agent.json is stale; run the exporter and commit the result:
FAIL site/openapi.agent.gpt30.json is stale; run the exporter and commit the result:
FAIL site/.well-known/openapi-discovery.json: tier agent size_bytes=547936
     does not match site/openapi.agent.json (560505)
FAIL site/.well-known/openapi-discovery.json: tier agent sha256_prefix='9a0ab17dfe015027'
     does not match site/openapi.agent.json ('0dae3d387feb212c')
FAIL site/.well-known/openapi-discovery.json: tier gpt30 size_bytes=384394
     does not match site/openapi.agent.gpt30.json (380898)
FAIL site/.well-known/openapi-discovery.json: tier gpt30 sha256_prefix='b0f1303e6a9bcf3f'
     does not match site/openapi.agent.gpt30.json ('2029f23507d361d7')
##[error]Process completed with exit code 1.
```

Source: workflow step `Run deploy drift gates` (lines 345-355 of
`pages-deploy-main.yml`), which calls:

- `scripts/check_openapi_drift.py`
- `scripts/check_mcp_drift.py`
- `scripts/check_agent_runtime_contracts.py --repo-root .`
- `scripts/ops/validate_release_capsule.py --repo-root .`

The drift gate trips **before** the Cloudflare Pages publish step
(`Publish to Cloudflare Pages` at line 477), so no upload to CF is even
attempted on these runs. The 6 surface files sit in disk SOT but the artifact
never ships.

---

## Section 3 — Root cause hypotheses (ranked)

### Primary cause (LIKELY) — `site/openapi.agent.json` family is stale on disk

The drift gate works by:

1. Re-running the OpenAPI exporter into a fresh `/tmp/` directory.
2. Diffing each of `site/openapi/v1.json`, `site/openapi.agent.json`,
   `site/openapi/agent.json`, `site/openapi.agent.gpt30.json` against the
   regenerated copy.
3. Verifying `site/.well-known/openapi-discovery.json` records each tier's
   `size_bytes` + `sha256_prefix`.

The failure log shows actual sizes (560,505 B for `openapi.agent.json`;
380,898 B for `openapi.agent.gpt30.json`) which exactly match the on-disk
file sizes I captured (`stat -f "%z"` returns the same bytes). But the
exporter's regeneration of those same paths yields different byte content,
meaning **the OpenAPI generator code has drifted vs. the committed
artefacts** since the last clean run.

Likely source of drift: Wave 23/24 + Wave 50/51 added Japanese-character
descriptions to several Pydantic models (`AMLawArticleResponse`,
`AttributionBlock`, `BidOut`, `FirmType` enum). The committed JSON contains
raw CJK code points; the GHA-side regeneration uses `json.dumps` with
`ensure_ascii=True`, producing `税理士法人`-style
escapes. The visible diff in the log (line 3629-3636) is exactly the
ASCII-escape vs. literal-CJK delta.

This is a **single-axis fix**: rerun `scripts/export_openapi.py` and
`scripts/export_agent_openapi.py` with the same `ensure_ascii` setting CI
uses, then commit the regenerated `site/openapi*.json` and re-run the
sha256/size accounting in `site/.well-known/openapi-discovery.json`.

### Secondary cause (POSSIBLE) — `_headers` / `_redirects` parity is fine

I scanned `site/_headers` (550 lines, 25,139 B) and `site/_redirects` (253
lines, 13,822 B). Surface 4 (`/why-jpcite-over-opus`) has its alias rule on
line 253. Surfaces 1, 2, 3, 5, 6 inherit the default static-serve rules; no
new entry is required for any of them. The 404 on surfaces 3-6 is **not**
caused by missing redirect / header rules — those files would resolve as
soon as they reach the CF artifact.

### Tertiary cause (RULED OUT) — Cloudflare secret rotation

Step `Check Cloudflare Pages secrets` (lines 114-125) errors hard on missing
`CF_API_TOKEN` / `CF_ACCOUNT_ID`. The drift gate runs after this step
succeeds, so the secrets are still in place. The block is local to the drift
check, not credential rot.

---

## Section 4 — Trigger options (operator action items)

> READ-ONLY audit. Claude has not run any of these. Pick one of the three
> options below; the drift gate must be cleared **first**.

### Step 0 — REQUIRED: clear the OpenAPI drift gate (separate lane)

Before any trigger option below can succeed, a separate lane must run:

```bash
python3 scripts/export_openapi.py
python3 scripts/export_agent_openapi.py
python3 scripts/regen_structured_sitemap_and_llms_meta.py
# Manually re-sync site/.well-known/openapi-discovery.json size_bytes and
# sha256_prefix for tiers `agent` and `gpt30` (helper script may exist
# under scripts/ — `grep -l openapi-discovery scripts/` to locate).
scripts/safe_commit.sh -m "fix(openapi): clear drift gate — agent + gpt30 + discovery resync [lane:solo]"
git push origin main
```

This commit itself satisfies the path filter of `pages-deploy-main` (it
touches `site/.well-known/openapi-discovery.json` + `site/openapi*.json`),
so the deploy will re-trigger automatically on push.

### Option A — Manual workflow trigger (after Step 0)

```bash
gh workflow run pages-deploy-main.yml -f deploy_mode=fast
```

Pros: explicit, low cost (uses cached generated artifacts), fast (~3-5 min).
Risk: if the cache is empty, the workflow auto-falls back to `full`, which
needs `FLY_API_TOKEN` and a 8-12 min Fly snapshot — still safe but slower.

### Option B — Empty commit auto-trigger (after Step 0)

```bash
git commit --allow-empty -m "chore(deploy): bump for CF Pages republish [lane:solo]"
git push origin main
```

Pros: zero-config; goes through the normal push gate.
Risk: **does not actually trigger** `pages-deploy-main` — the workflow's
path filter (lines 53-81) requires a real change under `site/**` or one of
the named scripts, so an empty commit is filtered out. Use only with Option A.

### Option C — Local `wrangler pages deploy site/` (after Step 0)

```bash
npx wrangler pages deploy site/ --project-name=autonomath --branch=main
```

Pros: bypasses GHA entirely; full operator control.
Risk: documented at the top of `pages-deploy-main.yml` (lines 1-9) —
**macOS local runs stalled 4× during the 2026-05-07 launch window**
because the >100 MB artifact upload hit CF Pages API rate-limit on resume.
The workflow was specifically authored to avoid this path. Do not use
unless GHA is offline.

### Recommendation

**Option A** after **Step 0** is the lowest-risk single-line trigger. Step 0
is the structural fix the deploy needs; Option A just gives the operator a
predictable manual lever instead of waiting for the next qualifying push.

---

## Section 5 — Expected curl status after successful deploy

After Step 0 lands and the next `pages-deploy-main` run completes
successfully, all 6 surfaces should return **200**. Verification script:

```bash
for url in \
  "https://jpcite.com/llms.txt" \
  "https://jpcite.com/.well-known/agents.json" \
  "https://jpcite.com/.well-known/jpcite-justifiability.json" \
  "https://jpcite.com/why-jpcite-over-opus" \
  "https://jpcite.com/.well-known/jpcite-federated-mcp-12-partners.json" \
  "https://jpcite.com/sitemap-structured.xml"
do
  Q="cl19_verify=$(date +%s)"
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 -L "${url}?${Q}")
  printf "%-3s  %s\n" "$code" "$url"
done
```

Expected output (all 200):

```
200  https://jpcite.com/llms.txt
200  https://jpcite.com/.well-known/agents.json
200  https://jpcite.com/.well-known/jpcite-justifiability.json
200  https://jpcite.com/why-jpcite-over-opus
200  https://jpcite.com/.well-known/jpcite-federated-mcp-12-partners.json
200  https://jpcite.com/sitemap-structured.xml
```

The `pages-deploy-main.yml` smoke step (lines 487-534) further verifies
`/.well-known/agents.json` byte-identity via JSON-tool parse, and the
`Post-deploy smoke (generated pages …)` step (lines 536-575) re-checks
representative source-backed paths through the `functions/[[path]].ts`
catch-all. None of those smoke checks include the 4 new surfaces yet — a
follow-up CL should add them (separate lane, not part of CL19).

---

## Notes / cross-references

- CL14 audit doc: `docs/_internal/CL14_PUBLIC_DOCS_STATE_SOT_2026_05_17.md`
  (commit `6deaa23cd`).
- 6 surface introduction commits:
  - GG10 justifiability: `02adbcde9` "feat(GG10): Justifiability landing —
    why jpcite over raw Opus 4.7 [lane:solo]"
  - FF2 cost-saving: `076f466f0` "FF2 customer surfaces"
  - DD1 federated-mcp-12: history not yet committed under one tag — file
    mtime 17:28 JST (after `02adbcde9`).
- Workflow comment (lines 1-9 of `pages-deploy-main.yml`) documents the
  macOS-stall rationale for using GHA Linux runners.
- AGENTS.md / CLAUDE.md `safe_commit.sh` policy honoured for this audit:
  no `--no-verify`, Co-Authored-By trailer present.
