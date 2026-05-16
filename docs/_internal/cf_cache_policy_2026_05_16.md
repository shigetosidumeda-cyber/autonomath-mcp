# CloudFront Edge Cache Policy Proposal (PERF-19, 2026-05-16)

**Status:** PROPOSE-ONLY (no `aws cloudfront update-distribution` issued this tick).
**Profile:** `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, account `993693061769`).
**Lane:** `[lane:solo]`.
**Author note:** Companion to PERF-7 (`api_perf_profile_2026_05_16.md`). PERF-7 measured
the API hot path in-process and identified `json.encoder.iterencode` on `/v1/openapi.json`
(~800 KB body, ~5.0 ms / request, n = 200 in-process). Edge caching offloads the entire
serializer cost for static / discovery endpoints. PERF-19 designs the policy; rollout is
gated on an API-origin distribution (does not yet exist — see Section 4).

---

## 1. Current CF distribution inventory

`aws cloudfront list-distributions --profile bookyou-recovery --query
'DistributionList.Items[?starts_with(Comment,` + "`" + `jpcite` + "`" + `)]'`:

| Id              | Comment                                                                                                       | Origin                                                                       | Domain                          |
| --------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------- |
| `ECP9NQMJB63NV` | `jpcite packet mirror — public read-only over derived bucket (CreditRun 2026-05, AutoStop 2026-05-29)`        | S3 `jpcite-credit-993693061769-202605-derived.s3.ap-northeast-1.amazonaws.com` | `d3o4dq6u0yb45u.cloudfront.net` |

No other `jpcite-*` distribution exists. The packet mirror is **S3-origin only** — it does
not front the FastAPI (`jpintel_mcp.api.main:create_app`) at
`jpcite-api.fly.dev` / `jpcite.com`. Therefore `/v1/openapi.json`, `/v1/mcp-server.json`,
`/v1/healthz`, `/v1/outcomes/{id}` are **not currently served by any CF distribution**.

### 1.1 Current cache behavior on `ECP9NQMJB63NV`

- `DefaultCacheBehavior.CachePolicyId` = `658327ea-f89d-4fab-a63d-7e88639e58f6`
  (Managed-CachingOptimized).
- `CacheBehaviors.Quantity` = 0 — **no path-specific overrides**.
- Policy parameters: DefaultTTL 86 400 s (24 h), MaxTTL 31 536 000 s (1 y), MinTTL 1 s,
  gzip + brotli on, no header / cookie / query-string in cache key.
- `Compress: true`, `ViewerProtocolPolicy: redirect-to-https`, `Aliases.Quantity: 0`
  (CloudFront default cert only, no custom hostname).
- ResponseHeadersPolicyId = `67f7725c-6f97-4210-82d7-5512b31e9d03`
  (Managed-CORS-With-Preflight).

This is appropriate for the packet mirror (immutable derived JSON / parquet) but
**dangerous if extended to API paths verbatim** — 24 h default TTL on
`/v1/outcomes/{id}` would cache per-customer paid responses at the edge.

## 2. Proposed TTL table

| Path pattern             | Cache? | TTL    | Cache policy strategy                                          | Justification                                                                                                                          |
| ------------------------ | ------ | ------ | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `/v1/openapi.json`       | YES    | 5 min  | Custom policy: min=60, default=300, max=600; no cookies, no QS | Schema bytes change only on jpcite release. PERF-7: 5 ms / req serializer + 12 ms gzip = 17 ms saved per edge hit. ~800 KB body.        |
| `/v1/openapi.agent.json` | YES    | 5 min  | Same as `openapi.json`                                         | Same cadence as openapi.json. ~320 KB body.                                                                                            |
| `/v1/mcp-server.json`    | YES    | 1 h    | Custom policy: min=600, default=3600, max=7200; no cookies     | Released artifact, changes per `release.yml`. ~220 KB. ~3 600 s × edge-hit-ratio is a strict superset of API process savings.          |
| `/v1/healthz`            | YES    | 30 s   | Custom policy: min=10, default=30, max=60; no cookies          | Liveness, status flips on Fly deploy. 30 s ≤ Fly health-check window. Origin still hit ~1 / 30 s for fresh signal.                     |
| `/v1/meta`               | YES    | 60 s   | Custom policy: min=30, default=60, max=120; no cookies         | Anon-quota-gated counter view, low write rate. 60 s smooths burst load.                                                                |
| `/v1/outcomes/{id}` (paid) | **NEVER** | n/a    | Managed-CachingDisabled (`4135ea2d-6df8-44a3-9df3-4b5a84be39ad`) | Security: per-customer payment context (Stripe/x402/credit-wallet). NEVER edge-cache. Bearer token, `X-API-Key`, or session header is in cache-key forwarding scope of the **origin**, not the edge. |
| `/v1/outcomes/{id}/*`    | **NEVER** | n/a    | Managed-CachingDisabled                                        | Subroutes (artifacts, signatures) inherit "NEVER cache" by precedence rule.                                                            |
| `/outcomes/*.html`       | YES    | 1 h    | Custom policy: min=300, default=3600, max=86400                | Public marketing / preview pages. Regenerated by `scripts/aws_credit_ops/build_packet_preview.py`. ~10 KB / page.                       |
| `/.well-known/*.json`    | YES    | 1 h    | Custom policy: min=300, default=3600, max=86400                | Agent-discovery (mcp.json, ai-plugin.json, llms.txt-flavored). Released artifacts.                                                     |
| Default (`*`, packets)   | YES    | 24 h   | Managed-CachingOptimized (current)                             | S3-derived bucket: parquet / packet JSON immutable per CreditRun. Unchanged from current.                                              |

### 2.1 Why two custom policies (not one)

CloudFront cache policies are TTL containers — one per `(min, default, max)` triple plus
key-forwarding config. We need 3 new custom policies:

1. **`jpcite-cache-discovery-5m`** — openapi.json / openapi.agent.json
   (min=60, default=300, max=600).
2. **`jpcite-cache-released-1h`** — mcp-server.json + outcomes/*.html + .well-known/*.json
   (min=300, default=3600, max=7200 or 86400).
3. **`jpcite-cache-liveness-30s`** — healthz + meta (min=10, default=30, max=120).

Plus reuse 2 managed policies: `Managed-CachingDisabled` (paid outcomes) and
`Managed-CachingOptimized` (S3 default — current).

## 3. Rules

1. `/v1/outcomes/{id}` and `/v1/outcomes/{id}/*` MUST use `Managed-CachingDisabled`.
   Path precedence in CloudFront matches longest first; we encode it as the highest
   precedence behavior so it never falls through to a wider TTL policy.
2. Bearer / cookie / Authorization headers MUST be forwarded for paid endpoints (i.e.
   `Managed-CachingDisabled` already does this — verified against AWS docs as of
   2026-05-16).
3. No path-specific override may set `Compress: false` — gzip remains on per PERF-7.
4. ResponseHeadersPolicy stays Managed-CORS-With-Preflight (current).
5. Liveness path TTL (30 s) MUST be `≤` Fly health-check window (60 s typical) so a
   deployed-but-unhealthy app is detected within one window.

## 4. Why propose-only this tick

`ECP9NQMJB63NV` is **S3-origin** (the packet mirror), not the FastAPI. Applying these
behaviors to `ECP9NQMJB63NV` directly would 404 because S3 has no `/v1/openapi.json` key.

To realize this proposal, one of the following must land **before** rollout:

- **Option A (preferred):** Create a second CF distribution `jpcite-api-edge` with origin
  = Fly hostname `jpcite-api.fly.dev` (custom origin, HTTPS-only, no OAC), apply the 9
  path behaviors above, optionally CNAME `jpcite.com` to it.
- **Option B:** Add a second origin to `ECP9NQMJB63NV` (Fly hostname) plus the 9
  path-pattern behaviors, keeping S3 as default. Mixed-origin distributions are
  supported but harder to operate (logging, WAF, alarms split per origin).
- **Option C (lightest):** Front the API with Cloudflare instead — the
  `bookyou-recovery` AWS profile is already at $2.8K actual / $19K cap and adding a
  second CF distribution adds ~$50 / month base + bandwidth. Cloudflare Pages already
  handles `jpcite.com` static surface (Wave 49 G1 R2); routing `/v1/*` through CF
  Workers + KV is a cheaper path.

PERF-19 documents the **policy shape**. The transport-layer rollout decision (A / B / C)
sits outside the perf workstream and is referenced in `docs/_internal/api_domain_migration.md`.

## 5. Validation plan (post-rollout, not this tick)

When the API-origin distribution exists:

1. Smoke: `curl -sI https://<edge>/v1/healthz | grep -i age` — expect `Age: 0` first
   request, `Age: <n>` subsequent within 30 s window.
2. Negative: `curl -sI https://<edge>/v1/outcomes/<id> -H "X-API-Key: …" | grep -i
   x-cache` — expect `Miss from cloudfront` always; never `Hit`.
3. CloudFront real-time logs streaming → CW Logs → Athena query `count(*) where
   cs_uri_stem like '/v1/outcomes/%' and x_edge_result_type = 'Hit'` — MUST be 0.
4. PERF-7 in-process p95 (`tests/perf/test_api_p95_budget.py`) remains unchanged
   (edge offload doesn't affect in-process measurement; we add a separate
   `tests/perf/test_edge_cache_hit_ratio.py` post-rollout).

## 6. Cost note

Edge offload reduces Fly egress + CPU cost but adds CloudFront data-transfer-out
($0.114 / GB in ap-northeast-1) and request fees ($0.012 / 10 000 HTTPS req). For the
hot paths (~5 KB-800 KB JSON, agent-driven traffic dominated by openapi.json fetches),
break-even is ~30 % edge-hit-ratio vs Fly bandwidth pricing. Discovery endpoints are
expected to clear 80 %+ once agent crawlers stabilize, so the policy is net-positive.

## 7. Rollback

Each path behavior is independently revertable:

```
aws cloudfront get-distribution-config --id <api-edge-id> > /tmp/cfg.json
# delete CacheBehaviors[?PathPattern=='/v1/<hotpath>'] from cfg.json
aws cloudfront update-distribution --id <api-edge-id> \
  --distribution-config "$(cat /tmp/cfg.json)" --if-match <etag>
```

Custom cache policies are also deletable once no behavior references them.
`Managed-CachingDisabled` for `/v1/outcomes/*` is the safe default (i.e. "do not touch
this behavior" is the only acceptable rollback for paid endpoints).

---

**Lane:** `[lane:solo]`
**Commit pattern:** `perf(cloudfront): edge cache policy proposal for hot endpoints [lane:solo]`
