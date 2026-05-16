# AWS scope expansion 06: Playwright / Chromium capture foundation

Date: 2026-05-15  
Account: `993693061769`  
AWS CLI profile for later execution: `bookyou-recovery`  
Default region: `us-east-1`  
Mode: planning only. Do not run AWS commands from this document until the operator explicitly starts the AWS run.

## 0. Executive Summary

This document adds a browser-rendering capture foundation to the AWS credit plan.

The purpose is to collect durable, source-backed evidence from Japanese public primary-information sites where ordinary HTTP fetches are weak:

- JavaScript-rendered public pages
- pages whose useful facts appear only after layout/rendering
- government pages with visual tables or embedded PDF links
- pages where DOM, screenshot, PDF print, and network metadata together create stronger provenance

The foundation uses Playwright with Chromium inside AWS Batch / ECS / Fargate / EC2 workers. It produces:

- screenshots whose stored image dimensions are **1600 px or less per side**
- DOM snapshots
- visible-text snapshots
- optional Chromium PDF prints where terms allow
- HAR-like request metadata without response bodies
- console metadata without secrets
- OCR input image tiles
- capture manifests that can become `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, and no-hit ledgers

It does **not** bypass access controls. It does not solve CAPTCHA. It does not rotate proxies to evade rate limits. It does not log in. It does not scrape private user data. It does not use request-time LLM calls.

This is best treated as new job family:

- `J25 Browser render capture foundation`
- downstream of `J01 source profile sweep` and `J11/J06 source targeting`
- upstream of `J12 receipt audit`, `J15 packet/proof materialization`, `J16 GEO/no-hit evaluation`, and `J17 OCR expansion`

## 1. Fit With The Unified jpcite Plan

### 1.1 What This Adds

The existing AWS plan already covers public source lake snapshots, PDF extraction, OCR expansion, proof fixtures, GEO evaluation, and release gates.

This browser capture layer fills the gap between:

- simple HTTP fetch/parquet extraction
- expensive OCR/Textract
- public proof pages

It gives jpcite a richer evidence layer:

1. A public page can be proven not only by downloaded HTML, but also by rendered screenshot and DOM state.
2. A hard-to-parse public table can be turned into OCR input tiles and visible-text snippets.
3. A source receipt can cite exact capture method, viewport, timestamp, checksums, HTTP status, canonical URL, and truncation gaps.
4. A proof page can show that jpcite derived facts from public primary sources instead of model memory.

### 1.2 What This Must Not Change

The core product contract remains unchanged:

- `source_receipts[]` must back claims.
- `claim_refs[]` must connect packet claims to receipts.
- `known_gaps[]` must disclose missing or partial evidence.
- no-hit means `no_hit_not_absence`.
- `request_time_llm_call_performed=false`.
- private CSV raw data must not enter AWS.
- AWS is a temporary artifact factory, not the permanent production dependency.
- after the credit run, AWS resources are deleted unless the operator explicitly chooses a small residual storage posture.

### 1.3 Correct Order In The Whole Plan

Browser capture should not be first. It is expensive compared with direct fetch, and it has legal/rate-limit risk if run broadly without source classification.

Correct order:

1. Freeze output contract and packet schema.
2. Build/confirm source registry and terms/robots ledger.
3. Direct-fetch all sources that can be fetched cleanly.
4. Select only pages where browser rendering adds value.
5. Run Playwright pilot.
6. Promote successful source patterns into high-volume capture.
7. Generate screenshots/DOM/PDF/HAR/OCR input.
8. Convert accepted captures into receipt candidates.
9. Run receipt completeness, leak, terms, and no-hit gates.
10. Materialize packet fixtures and public proof assets.
11. Deploy product surfaces.
12. Export artifacts and perform zero-bill cleanup.

## 2. Non-Negotiable Safety Rules

### 2.1 Access Restrictions

The browser workers must not:

- solve CAPTCHA
- use CAPTCHA-solving services
- use stealth plugins to disguise automation
- rotate proxies to evade site-level throttles
- spoof residential users
- bypass login or paywalls
- click through access restrictions
- submit forms unless the form is explicitly public, official, and approved in the source profile
- bypass robots.txt or published terms
- defeat rate limits
- use private credentials
- process private CSV/user uploads

If a page returns CAPTCHA, bot challenge, login wall, 401, 403, or repeated 429:

- stop that URL pattern
- record `blocked_reason`
- add a `known_gaps[]` candidate
- do not retry aggressively

### 2.2 Public-Only Scope

Allowed input:

- Japanese government and public-sector primary-information pages
- official public registries
- public law/regulation pages
- public subsidy/procurement pages
- public notices
- public statistical pages
- public pages from official institutions where source terms allow automated access

Disallowed input:

- end-user accounting CSVs
- private customer documents
- logged-in dashboards
- screenshots of user screens
- anything requiring credentials
- anything where terms/robots prohibit collection

### 2.3 No Request-Time LLM

Browser capture is deterministic infrastructure. It must not call an LLM to decide what a page means during capture.

Allowed:

- deterministic DOM extraction
- static selectors
- visible text extraction
- checksums
- OCR input generation
- later offline public-only classification if separately approved under the Bedrock batch plan

Not allowed:

- using an LLM at request time to invent facts
- producing unreceipted claims
- letting an LLM rewrite no-hit into proof of absence

## 3. Target Use Cases

### 3.1 Public Evidence Capture

For each target source URL:

- store rendered screenshot tiles
- store DOM snapshot
- store visible text
- store HTTP status chain and final URL
- store resource metadata
- store console errors
- store content hash
- store capture timestamp
- store legal/robots decision id

This supports source-backed answers such as:

- "this subsidy page had these eligibility criteria on this date"
- "this deadline appears on the rendered official page"
- "this legal basis link was visible on the official page"
- "this company/invoice registry lookup returned this official rendered state"

### 3.2 OCR Input For Hard Visual Pages

Some public sources expose scanned PDFs, image-based tables, or visually rendered pages.

Browser capture should generate OCR-ready image tiles:

- PNG
- max width 1600
- max height 1600
- stable device scale factor
- language hint `ja`
- source URL and tile coordinates
- content hash and screenshot hash

The OCR itself belongs to downstream jobs such as `J17`. This document designs the input foundation.

### 3.3 Proof Page Material

Public proof pages can reference:

- screenshot tile ids
- DOM text snippets
- source receipt ids
- capture method
- timestamp
- source terms status
- known limitations

The proof page should not expose raw HAR bodies, cookies, or excessive console logs.

### 3.4 GEO / Agent Discovery Material

AI agents should be able to understand that jpcite has:

- public-source evidence artifacts
- exact capture provenance
- freshness metadata
- safe no-hit semantics
- API/MCP outputs that can cite source receipts

Browser artifacts should therefore feed:

- packet examples
- OpenAPI examples
- MCP examples
- `.well-known` and `llms.txt` proof links
- GEO eval fixtures

## 4. Architecture

### 4.1 Components

| Component | Purpose | Preferred AWS service |
|---|---|---|
| Source registry | approved URL/source patterns and terms decisions | S3/Parquet, generated by J01 |
| Capture request builder | creates capture requests from source registry and source lake | AWS Batch job or local preflight artifact |
| Capture queue | immutable request shards | S3 manifests + AWS Batch array jobs |
| Browser worker | Playwright/Chromium renderer | AWS Batch on EC2 Spot first; Fargate for smaller/simple jobs |
| Artifact bucket | temporary outputs | S3, deleted after export if zero-bill posture |
| Cost ledger | estimated and observed job-level cost | S3/Parquet |
| Quality gate | validates artifact dimensions, schemas, hashes, redaction | AWS Batch validation job |
| Stop controller | disables queues/cancels jobs/terminates compute | Batch/ECS/EC2 control job, with operator confirmation at high lines |
| Export packager | final tar/zstd/parquet/jsonl/checksum bundles | Batch job |

### 4.2 Why AWS Batch First

Use AWS Batch as the primary scheduler because:

- it can run large job arrays
- it can use EC2 Spot capacity for high-throughput browser work
- it can retry failed jobs with caps
- it can continue running after Codex/Claude rate limits
- it does not require an always-on web service
- it can be drained and deleted after the run

Fargate is useful for small stateless runs and smoke tests. EC2 Spot is better for large Chromium capture because browser rendering is CPU/memory heavy and task startup overhead matters.

### 4.3 Recommended Compute Modes

#### Mode A: Fargate Smoke

Use for:

- first 100-2,000 URLs
- validating container image
- validating artifact schema
- verifying screenshot dimensions
- verifying robots/terms skip logic
- low operational complexity

Task size:

- 2 vCPU
- 4-8 GB memory
- ephemeral storage 20-50 GB
- concurrency 5-20

#### Mode B: EC2 Spot Standard Capture

Use for:

- 20,000-500,000 URL captures
- high-throughput screenshot/DOM/HAR generation
- repeated capture with controlled retry

Instance families:

- compute optimized current generation where available
- memory at least 2-4 GB per concurrent Chromium process
- no GPU required
- use mixed instance policies to avoid Spot scarcity

Worker density:

- start with 1 Chromium context per vCPU
- reduce to 0.5-0.75 per vCPU for heavy Japanese government pages
- cap memory at 70% of instance memory
- kill workers that exceed memory/time budgets

#### Mode C: Fargate Fallback

Use only when:

- EC2 Spot interruption is too high
- a source requires very short isolated tasks
- operational simplicity beats cost

Do not use Fargate to burn credit blindly. It is useful but can be less cost-efficient for large browser runs.

### 4.4 Network Shape

Preferred network:

- public subnets
- no inbound rules
- outbound HTTPS/HTTP only
- assign public IPv4 only while tasks run
- no NAT Gateway
- S3 Gateway Endpoint where practical
- no cross-region data movement
- all artifacts in `us-east-1`

Why no NAT Gateway:

- browser workers need outbound internet to public sites
- NAT Gateway adds hourly and per-GB charges
- public-subnet workers with no inbound access are simpler for a short, disposable batch run

Important public IPv4 note:

- public IPv4 addresses are charged hourly while in use
- this is acceptable during short capture windows
- no Elastic IPs should be allocated
- all public IP-bearing resources must be deleted at cleanup

### 4.5 Container Image

Base:

- Linux
- Node.js LTS
- Playwright pinned version
- Chromium browser installed via Playwright image or deterministic install
- Japanese fonts: Noto Sans CJK / Noto Serif CJK
- CA certificates
- image processing tool for dimension checks and tile conversion
- optional PDF utilities for validation

No secrets:

- no AWS long-lived credentials in image
- no browser profile baked into image
- no cookies
- no private data

Runtime environment:

- `RUN_ID`
- `REQUEST_SHARD_URI`
- `OUTPUT_PREFIX`
- `MAX_CONCURRENCY`
- `MAX_CAPTURE_SECONDS`
- `MAX_TILES_PER_PAGE`
- `MAX_SCREENSHOT_EDGE_PX=1600`
- `ALLOW_PDF_PRINT=false|true`
- `HAR_CONTENT_MODE=omit`
- `ROBOTS_POLICY=strict`
- `RATE_LIMIT_POLICY=strict`
- `REQUEST_TIME_LLM_CALL_PERFORMED=false`

## 5. Capture Algorithm

### 5.1 Per-URL Flow

1. Load `capture_request`.
2. Validate source profile.
3. Confirm terms/robots allow decision.
4. Confirm URL host and path match allowlist.
5. Enforce per-host rate limit.
6. Create fresh non-persistent browser context.
7. Set viewport with width <= 1600 and device scale factor 1.
8. Navigate with a strict timeout.
9. Wait for `domcontentloaded`; optionally wait briefly for network quiet.
10. Detect blocking states: CAPTCHA, login, repeated 403/429, terms wall.
11. If blocked, record a blocked result and stop.
12. Extract canonical URL, title, meta, visible text, and sanitized DOM.
13. Capture screenshot tiles, each <= 1600 x 1600.
14. Optionally print PDF if allowed and useful.
15. Save HAR-style metadata without bodies/cookies.
16. Save console metadata with redaction/truncation.
17. Generate OCR input tile manifest.
18. Close browser context.
19. Write result manifest and cost ledger row.
20. Validate output dimensions and schema before marking accepted.

### 5.2 Viewport Policy

Default viewports:

- `desktop_1365x900`
- `desktop_1440x1000`
- optional `desktop_1600x1200`
- optional `mobile_390x844` only if the source profile says mobile rendering is materially different

Stored screenshots must satisfy:

- max width <= 1600 px
- max height <= 1600 px
- device scale factor = 1 unless explicitly justified
- no single stored full-page image taller than 1600 px

For long pages:

- compute document height
- capture clipped tiles
- each tile has `x`, `y`, `width`, `height`
- max tile count is bounded
- if truncated, record `capture_truncated=true` and add `known_gaps[]`

### 5.3 Screenshot Types

| Type | Required | Max size | Purpose |
|---|---|---:|---|
| `viewport_main` | yes | 1600 x 1600 | proof of rendered first view |
| `tile_sequence` | conditional | each tile 1600 x 1600 | long-page OCR/evidence |
| `element_table` | conditional | 1600 x 1600 | relevant public table blocks |
| `error_state` | conditional | 1600 x 1600 | blocked/failed state evidence |

Do not store full-page screenshots as one tall image if the height exceeds 1600 px.

### 5.4 DOM Snapshot Policy

Store:

- URL
- title
- canonical link
- meta description
- visible text blocks
- heading structure
- link list
- table text where available
- selected DOM subtree hashes
- final document hash

Do not store:

- cookies
- local storage
- session storage
- browser profile data
- private tokens
- response bodies from third-party analytics
- raw JavaScript bundles unless explicitly needed and allowed

### 5.5 HAR / Network Metadata Policy

HAR-style output should be metadata-only.

Allowed fields:

- request URL after redaction
- method
- status
- content type
- resource type
- timing summary
- transfer size
- redirect chain
- final URL
- domain
- blocked/failed reason

Disallowed fields:

- cookies
- authorization headers
- set-cookie headers
- request/response bodies
- full query strings when token-like parameters are present
- third-party tracking payloads

Use `omitContent` behavior or equivalent. HAR is a provenance/debug artifact, not a data lake of page bodies.

### 5.6 Console Metadata Policy

Store:

- console event type
- source URL/domain
- message hash
- first 200-500 safe characters after redaction
- location URL after redaction
- count by type

Do not store:

- full stack traces with query secrets
- long payloads
- private browser state

Console logs are mainly for quality diagnostics:

- JavaScript errors
- failed resources
- blocked mixed content
- navigation instability

### 5.7 PDF Print Policy

Chromium PDF print is optional.

Allow only when:

- source terms allow it
- page is public
- generated PDF helps preserve visual layout
- file size cap is satisfied

Skip PDF when:

- source is already a PDF and direct download is cleaner
- page is very long
- page has dynamic content that prints poorly
- PDF would contain overlays or irrelevant navigation

Generated PDFs must have:

- source URL
- timestamp
- capture id
- checksum
- page count
- file size
- print settings

## 6. Artifact Layout

Temporary S3 layout:

```text
s3://<temp-artifact-bucket>/runs/<run_id>/browser_capture/
  requests/
    part-00000.capture_request.jsonl
  results/
    accepted/part-00000.capture_result.jsonl
    skipped/part-00000.capture_result.jsonl
    failed/part-00000.capture_result.jsonl
  artifacts/
    <source_id>/<capture_id>/
      manifest.json
      screenshot/
        viewport_main.png
        tile_0000.png
        tile_0001.png
      dom/
        dom_snapshot.json
        visible_text.txt
      pdf/
        rendered.pdf
      network/
        har_metadata.json
        console_events.jsonl
      ocr_input/
        ocr_tile_manifest.jsonl
  qa/
    dimension_audit.parquet
    redaction_audit.parquet
    terms_robots_audit.parquet
    capture_quality_report.md
  ledgers/
    cost_ledger.parquet
    host_rate_ledger.parquet
    blocked_ledger.parquet
  export/
    browser_capture_export_manifest.json
    checksums.sha256
```

All buckets are temporary unless the operator explicitly approves residual storage. For zero ongoing bill, export and delete.

## 7. Schemas

### 7.1 `capture_request`

```json
{
  "schema_version": "browser_capture_request.v1",
  "run_id": "aws-credit-2026-05-15-r01",
  "capture_id": "cap_01HY...",
  "source_id": "egov_law",
  "source_profile_id": "srcprof_egov_law_v1",
  "source_family": "law_regulation",
  "url": "https://example.go.jp/public/page",
  "canonical_expected_host": "example.go.jp",
  "official_source_class": "government_primary",
  "terms_decision_id": "terms_...",
  "robots_decision_id": "robots_...",
  "robots_allowed": true,
  "capture_mode": "chromium_render",
  "viewport_profile": "desktop_1440x1000",
  "max_screenshot_edge_px": 1600,
  "max_tiles_per_page": 12,
  "allow_pdf_print": false,
  "allow_har_metadata": true,
  "allow_console_metadata": true,
  "allow_ocr_input_tiles": true,
  "timeout_ms": 45000,
  "host_rate_limit_key": "example.go.jp",
  "priority": 50,
  "max_attempts": 2,
  "requested_by_job": "J25",
  "request_time_llm_call_performed": false
}
```

### 7.2 `capture_result`

```json
{
  "schema_version": "browser_capture_result.v1",
  "run_id": "aws-credit-2026-05-15-r01",
  "capture_id": "cap_01HY...",
  "source_id": "egov_law",
  "url_requested": "https://example.go.jp/public/page",
  "url_final": "https://example.go.jp/public/page",
  "captured_at": "2026-05-15T10:00:00Z",
  "status": "accepted",
  "http_status_main": 200,
  "capture_method": "playwright_chromium",
  "browser_version": "chromium-<pinned>",
  "viewport": {
    "width": 1440,
    "height": 1000,
    "device_scale_factor": 1
  },
  "screenshot_policy": {
    "max_edge_px": 1600,
    "full_page_single_image_stored": false,
    "tile_count": 4,
    "truncated": false
  },
  "artifact_refs": {
    "manifest": "s3://.../manifest.json",
    "viewport_main_png": "s3://.../viewport_main.png",
    "dom_snapshot_json": "s3://.../dom_snapshot.json",
    "visible_text_txt": "s3://.../visible_text.txt",
    "har_metadata_json": "s3://.../har_metadata.json",
    "console_events_jsonl": "s3://.../console_events.jsonl",
    "ocr_tile_manifest_jsonl": "s3://.../ocr_tile_manifest.jsonl"
  },
  "hashes": {
    "dom_sha256": "sha256:...",
    "visible_text_sha256": "sha256:...",
    "viewport_main_png_sha256": "sha256:...",
    "artifact_manifest_sha256": "sha256:..."
  },
  "quality": {
    "dom_text_chars": 18234,
    "screenshot_dimensions_valid": true,
    "redaction_passed": true,
    "terms_robots_passed": true,
    "blocked_detected": false,
    "known_gap_required": false
  },
  "request_time_llm_call_performed": false
}
```

### 7.3 `screenshot_tile`

```json
{
  "schema_version": "screenshot_tile.v1",
  "capture_id": "cap_01HY...",
  "tile_id": "tile_0003",
  "image_uri": "s3://.../tile_0003.png",
  "image_sha256": "sha256:...",
  "viewport_width": 1440,
  "viewport_height": 1000,
  "clip": {
    "x": 0,
    "y": 3000,
    "width": 1440,
    "height": 1000
  },
  "image_width": 1440,
  "image_height": 1000,
  "max_edge_px": 1600,
  "ocr_ready": true,
  "language_hint": "ja",
  "contains_blocked_page": false
}
```

### 7.4 `dom_snapshot`

```json
{
  "schema_version": "dom_snapshot.v1",
  "capture_id": "cap_01HY...",
  "url_final": "https://example.go.jp/public/page",
  "title": "Public page title",
  "canonical_url": "https://example.go.jp/public/page",
  "headings": [
    {"level": 1, "text": "制度名"}
  ],
  "links": [
    {
      "text": "PDF",
      "href_redacted": "https://example.go.jp/file.pdf",
      "same_site": true
    }
  ],
  "tables": [
    {
      "table_index": 0,
      "row_count": 12,
      "column_count": 5,
      "text_sha256": "sha256:..."
    }
  ],
  "visible_text_sha256": "sha256:...",
  "dom_sha256": "sha256:...",
  "redaction_policy": "public_safe_v1"
}
```

### 7.5 `har_metadata`

```json
{
  "schema_version": "har_metadata.v1",
  "capture_id": "cap_01HY...",
  "url_final": "https://example.go.jp/public/page",
  "entries": [
    {
      "request_url_redacted": "https://example.go.jp/public/page",
      "method": "GET",
      "status": 200,
      "resource_type": "document",
      "content_type": "text/html",
      "duration_ms": 431,
      "transfer_size_bytes": 52134,
      "same_site": true
    }
  ],
  "bodies_stored": false,
  "cookies_stored": false,
  "authorization_headers_stored": false,
  "query_redaction_applied": true
}
```

### 7.6 `blocked_result`

```json
{
  "schema_version": "browser_capture_result.v1",
  "capture_id": "cap_01HY...",
  "status": "skipped_blocked",
  "blocked_reason": "captcha_detected",
  "retry_allowed": false,
  "known_gap_candidate": {
    "gap_type": "render_capture_unavailable",
    "reason": "captcha_or_bot_challenge",
    "safe_user_text": "The official page could not be rendered automatically. This is not evidence that the underlying fact is absent."
  },
  "request_time_llm_call_performed": false
}
```

### 7.7 `cost_ledger`

```json
{
  "schema_version": "browser_capture_cost_ledger.v1",
  "run_id": "aws-credit-2026-05-15-r01",
  "job_id": "J25",
  "capture_id": "cap_01HY...",
  "compute_mode": "batch_ec2_spot",
  "vcpu_seconds": 360,
  "memory_gb_seconds": 1440,
  "task_seconds": 180,
  "public_ipv4_seconds_estimate": 180,
  "s3_put_count": 16,
  "s3_bytes_written": 12400000,
  "cloudwatch_log_bytes": 9000,
  "estimated_cost_usd": 0.0123,
  "accepted_artifact": true
}
```

## 8. Source Profile Additions

Each `source_profile` should gain browser-specific fields:

```json
{
  "browser_capture": {
    "eligible": true,
    "reason": "js_rendered_public_table",
    "robots_mode": "strict",
    "terms_mode": "allow_public_archival_capture",
    "max_urls_per_run": 5000,
    "max_concurrency_per_host": 1,
    "min_delay_ms_per_host": 3000,
    "allowed_viewports": ["desktop_1440x1000"],
    "allow_pdf_print": false,
    "allow_har_metadata": true,
    "allow_ocr_input_tiles": true,
    "max_tiles_per_page": 12,
    "blocked_selectors": [],
    "required_evidence": ["dom", "viewport_screenshot", "visible_text"],
    "no_hit_semantics": "no_hit_not_absence"
  }
}
```

Do not run browser capture for a source without this profile.

## 9. Cost Model

### 9.1 Pricing References To Verify Before Execution

Pricing must be rechecked immediately before execution in the AWS Billing console or official pricing pages.

Current planning assumptions are based on:

- AWS Batch has no additional service charge; underlying compute/storage services are billed.
- Fargate in `us-east-1` is billed by vCPU-second, GB-second, OS/architecture, and ephemeral storage.
- Public IPv4 addresses are billed hourly while in use.
- S3 costs include storage, requests, and data transfer patterns.
- CloudWatch Logs can become material if raw logs are verbose.
- NAT Gateway has hourly and data processing charges; avoid it.

Official references:

- https://aws.amazon.com/batch/pricing/
- https://aws.amazon.com/fargate/pricing/
- https://aws.amazon.com/vpc/pricing/
- https://aws.amazon.com/s3/pricing/
- https://aws.amazon.com/cloudwatch/pricing/
- https://docs.aws.amazon.com/batch/latest/userguide/what-is-batch.html
- https://playwright.dev/docs/screenshots
- https://playwright.dev/docs/browser-contexts

### 9.2 Fargate Formula

For a Fargate task:

```text
task_compute_cost =
  task_seconds *
  (
    vcpu_count * fargate_vcpu_second_rate
    + memory_gb * fargate_memory_gb_second_rate
    + extra_ephemeral_storage_gb * ephemeral_storage_gb_second_rate
  )
```

Using the published `us-east-1` Linux/x86 example rates from the Fargate pricing page:

```text
vcpu_second_rate ~= 0.000011244 USD
memory_gb_second_rate ~= 0.000001235 USD
extra_ephemeral_storage_gb_second_rate ~= 0.0000000308 USD
```

Example:

```text
2 vCPU, 4 GB memory, 180 seconds
compute ~= 180 * ((2 * 0.000011244) + (4 * 0.000001235))
compute ~= 0.00494 USD per capture task
```

This excludes S3 requests/storage, CloudWatch logs, public IPv4 time, retries, and OCR.

### 9.3 EC2 Spot Formula

For EC2 Spot:

```text
worker_hour_cost =
  sum(instance_spot_hourly_price * running_hours)
  + public_ipv4_hourly_cost
  + EBS_gb_month_prorated
  + CloudWatch/S3/request costs
```

Then:

```text
cost_per_accepted_capture =
  total_worker_hour_cost / accepted_capture_count
```

Spot prices change. Do not hardcode them in product logic. Record the observed price and instance family in the cost ledger.

### 9.4 Practical Budget Bands

| Band | Scope | Expected useful spend | Purpose |
|---|---|---:|---|
| Pilot | 500-2,000 URLs | USD 50-200 | prove schema, timing, legality, image dimension, cleanup |
| Standard | 50,000-150,000 URLs | USD 800-2,500 | cover high-value render-only pages |
| Broad | 200,000-600,000 URLs | USD 2,500-6,000 | capture broader public program/local gov pages |
| Stretch | 600,000-1,000,000+ URLs | USD 6,000-9,000 | only if terms allow and accepted artifact rate stays high |

This module should not consume all USD 19,493.94 by itself. It is a multiplier for OCR, receipt generation, proof pages, and GEO evidence. If capture quality is low, spend should shift back to PDF/OCR/source lake/QA jobs.

### 9.5 Hidden Cost Risks

| Risk | Why it matters | Control |
|---|---|---|
| NAT Gateway | hourly + data processing costs | do not create NAT unless separately approved |
| Public IPv4 | charged while workers run | short-lived workers; no Elastic IPs |
| CloudWatch Logs | verbose browser logs can be large | log metadata only; cap logs per capture |
| S3 PUT/list | many tiny artifacts | batch manifests; compact after run |
| S3 storage | screenshots can grow quickly | compress, cap tiles, export/delete |
| Data transfer out | exporting large artifacts from AWS can cost | estimate export size before drain |
| Cross-region movement | unnecessary transfer charges | keep all work in `us-east-1` |
| Retries | bad pages can multiply cost | max attempts 2; host-level circuit breakers |
| Long pages | tile count explosion | max tiles per page and truncation gaps |

## 10. Throughput Design

### 10.1 Rate Limits

Default host policy:

- max 1 concurrent capture per host
- minimum 3 seconds between navigations per host
- exponential backoff on 429/503
- immediate stop on CAPTCHA/login wall
- stop host after repeated 403/429

Large official domains may allow more, but only if the source profile explicitly approves it.

### 10.2 Batch Array Strategy

Use immutable request shards:

- shard size: 100-500 URLs
- one Batch array child processes one shard
- child-level concurrency: 1-4 Chromium workers
- job timeout: 30-120 minutes per shard
- max attempts: 1 or 2
- failed URL outputs are explicit, not hidden in logs

This prevents the run from depending on an interactive Codex/Claude session after launch.

### 10.3 Self-Running AWS Design

Once the operator starts the run, AWS should continue without Codex/Claude:

- request manifests are already in S3
- Batch queues hold the work
- workers write progress ledgers
- stop controller reads ledgers and budget lines
- cleanup runbook is prewritten

Codex/Claude rate limits should not pause active AWS jobs. However, AWS must still stop at cost and safety limits.

### 10.4 Pacing For Fast Production Deployment

Fast lane:

1. capture 500-2,000 high-value URLs
2. generate accepted receipts and proof fixtures
3. import to repo
4. run release gates
5. deploy RC1

Full lane:

1. continue broader capture in AWS
2. expand source coverage
3. generate more receipts/proof examples
4. import accepted batches only
5. deploy RC2/RC3

Do not wait for the full AWS credit run to finish before first production deploy if RC1 evidence is already strong.

## 11. Quality Gates

### 11.1 Acceptance Gates

A capture is accepted only if:

- source profile is eligible
- terms/robots decision passed
- final URL host is allowed
- status is not CAPTCHA/login/access-blocked
- screenshot dimensions are <= 1600 px per side
- DOM snapshot exists or failure is explained
- visible text exists or failure is explained
- hashes exist for every artifact
- redaction audit passes
- no private CSV/user data is present
- `request_time_llm_call_performed=false`

### 11.2 Rejection Gates

Reject or skip if:

- robots disallow
- terms prohibit
- CAPTCHA/bot challenge appears
- login wall appears
- page requires credentials
- source redirects outside allowlist
- image dimension exceeds 1600 px
- artifact lacks checksum
- HAR includes bodies/cookies/auth headers
- console log contains token-like secrets
- repeated retries are needed
- source returns high error rate

### 11.3 Release Blockers

Browser capture must block production import if:

- any screenshot exceeds dimension policy
- raw HAR bodies are stored
- cookies/auth headers are stored
- terms/robots decision is missing
- no-hit wording implies proof of absence
- capture claims are not linked to `source_receipts[]`
- `known_gaps[]` are missing for truncated/blocked pages
- private CSV or user content appears in any artifact

## 12. Integration With jpcite Outputs

### 12.1 `source_receipt` Candidate Mapping

Browser capture can create receipt candidates:

```json
{
  "source_receipt_id": "sr_cap_01HY...",
  "source_id": "egov_law",
  "source_url": "https://example.go.jp/public/page",
  "captured_at": "2026-05-15T10:00:00Z",
  "capture_method": "playwright_chromium",
  "artifact_refs": {
    "screenshot_tiles": ["tile_0000", "tile_0001"],
    "dom_snapshot": "dom_snapshot.json",
    "visible_text": "visible_text.txt"
  },
  "hashes": {
    "artifact_manifest_sha256": "sha256:..."
  },
  "limitations": [],
  "request_time_llm_call_performed": false
}
```

### 12.2 `claim_refs` Mapping

Downstream extraction can reference:

- DOM text span hash
- OCR tile id
- screenshot coordinate box
- page URL
- capture timestamp
- source receipt id

Example:

```json
{
  "claim_ref_id": "cr_...",
  "claim_id": "deadline_...",
  "source_receipt_id": "sr_cap_...",
  "evidence_pointer": {
    "type": "screenshot_tile_box",
    "tile_id": "tile_0002",
    "box": {"x": 220, "y": 410, "width": 540, "height": 90}
  },
  "extraction_method": "ocr_or_dom_candidate",
  "human_review_required": true
}
```

### 12.3 `known_gaps` Mapping

Use `known_gaps[]` for:

- page truncated due to tile cap
- CAPTCHA or bot challenge
- login wall
- robots/terms skip
- PDF print skipped
- DOM unavailable but screenshot exists
- screenshot unavailable but DOM exists

Safe wording:

```text
This source could not be fully rendered or captured automatically. This is a capture limitation, not evidence that the underlying fact is absent.
```

### 12.4 Packet Examples This Enables

New or improved packet examples:

- `evidence_answer` with screenshot-backed source receipts
- `application_strategy` with rendered subsidy page evidence
- `source_receipt_ledger` with DOM/screenshot/PDF provenance
- `agent_routing_decision` that explains when browser capture was needed
- `company_public_baseline` with official registry render evidence
- `public_program_deadline_watch` using rendered pages and no-hit-safe gaps
- `law_policy_change_watch` using official rendered page deltas
- `procurement_opportunity_digest` using rendered procurement pages
- `local_government_subsidy_matrix` using page/table screenshots plus OCR inputs

## 13. Playwright Implementation Notes

### 13.1 Browser Context

Use a fresh non-persistent context for every capture or small URL group:

- no persistent cookies
- no reused login state
- locale `ja-JP`
- timezone `Asia/Tokyo` for rendering consistency if needed
- user agent identifying automated public-source archival capture
- service workers blocked where possible
- viewport fixed
- JavaScript enabled unless source profile says direct/static mode is enough

### 13.2 Request Handling

Default allow:

- document
- stylesheet
- script
- image
- font
- fetch/xhr needed for page data

Default block:

- media
- websocket unless required
- third-party trackers if source profile allows blocking without changing content

Be careful: blocking too aggressively can change official page rendering. Record any blocking policy in the manifest.

### 13.3 Timeouts

Recommended defaults:

- navigation timeout: 20-30 seconds
- total capture timeout per URL: 45-75 seconds
- heavy source timeout: up to 120 seconds only if source profile approves
- tile capture timeout: bounded by max tile count

Timeout is not a no-hit. Timeout becomes a `known_gaps[]` candidate.

### 13.4 Determinism

Record:

- Playwright version
- Chromium version
- container image digest
- fonts installed
- viewport
- device scale factor
- timezone
- locale
- source profile version
- terms/robots decision version

This makes captures reproducible enough for proof and QA.

## 14. Stop Conditions

### 14.1 Global AWS Spend Lines

Inherit the unified plan lines:

| Line | Action for browser capture |
|---:|---|
| USD 17,000 | stop broad/low-value browser expansion; continue only accepted high-yield sources |
| USD 18,300 | stop browser stretch unless accepted artifact rate is excellent |
| USD 18,900 | no new browser jobs; drain/export/cleanup only |
| USD 19,100-19,300 | manual approval only; browser capture normally off |
| USD 19,300 | emergency stop |

### 14.2 Module-Specific Spend Lines

Recommended `J25` module caps:

| Line | USD | Action |
|---|---:|---|
| Pilot cap | 200 | stop and review schema/error/cost |
| Standard cap | 2,500 | continue only if accepted artifacts are high value |
| Broad cap | 6,000 | stop low-value hosts and reallocate to OCR/QA/proof generation |
| Hard module cap | 9,000 | stop browser capture unless operator explicitly reallocates budget |

### 14.3 Quality Stop Conditions

Stop a host if:

- CAPTCHA/bot challenge rate > 1%
- 403/429/503 rate > 5% over 100 attempts
- accepted capture rate < 70% after pilot
- average accepted artifact cost exceeds planned threshold by 3x
- terms/robots uncertainty appears
- artifacts fail redaction
- screenshots exceed dimension policy
- CloudWatch logs exceed expected volume

### 14.4 Safety Stop Conditions

Stop all browser jobs if:

- NAT Gateway is created unexpectedly
- public IPv4 spend keeps increasing after queue drain
- any private data is detected
- HAR bodies/cookies/auth headers are found
- workers access domains outside allowlist
- Cost Explorer or billing indicates non-credit eligible spend exposure

## 15. Zero-Bill Cleanup

Browser capture creates many short-lived resources. Cleanup must be explicit.

### 15.1 Drain

1. Disable new Batch job submissions.
2. Cancel queued browser capture jobs.
3. Let accepted running jobs finish only if under spend lines.
4. Terminate stuck jobs.
5. Export accepted artifacts and manifests.
6. Generate checksum ledger.
7. Confirm repo/non-AWS import target has final artifacts.

### 15.2 Delete Compute

Delete:

- AWS Batch job queues
- AWS Batch compute environments
- ECS clusters used by Batch/Fargate
- running/stopped ECS tasks
- EC2 Spot instances
- Launch Templates created for this run
- Auto Scaling groups
- EBS volumes
- EBS snapshots
- ECR repositories/images

### 15.3 Delete Network Artifacts

Delete:

- NAT Gateways if any were accidentally created
- Elastic IPs
- load balancers if any
- ENIs left by ECS/Fargate
- security groups created for capture
- route tables/subnets/VPC only if dedicated to this run
- VPC endpoints if created only for this run

### 15.4 Delete Storage And Logs

For strict zero bill:

- export S3 artifacts away from AWS
- verify checksums
- delete all S3 objects
- delete buckets
- delete CloudWatch log groups
- delete CloudWatch dashboards/alarms if not needed
- delete Athena query result buckets
- delete Glue databases/tables/crawlers if any
- delete temporary DynamoDB/SQS/Step Functions resources if used

### 15.5 Final Verification

Final inventory must show no tagged resources remaining:

- `Project=jpcite`
- `RunId=<run_id>`
- `CostRun=aws-credit-2026-05`
- `Owner=bookyou-recovery`

Also verify:

- no running EC2/ECS/Fargate/Batch resources
- no EIP/public IPv4 resources
- no NAT Gateway
- no non-empty S3 buckets from the run
- no ECR repositories from the run
- no CloudWatch log groups from the run

## 16. Production Deployment Implications

Browser capture should accelerate production, not delay it.

Use the first accepted capture batch to produce:

- proof-page examples
- OpenAPI example payloads
- MCP example outputs
- `source_receipt` fixtures
- `known_gaps` fixtures
- screenshot-backed public evidence pages

Production RC1 should require only a small high-confidence slice:

- 3-5 source families
- 30-100 excellent browser-captured receipts
- zero privacy leaks
- zero dimension-policy failures
- passing no-hit wording tests
- passing discovery/GEO tests

Broader AWS capture can continue in parallel for RC2/RC3, as long as spend controls remain active.

## 17. Recommended Integration Sequence

1. Add `browser_capture` fields to source profile schema.
2. Add `capture_request` and `capture_result` schemas to artifact manifest spec.
3. Build local Playwright prototype against 5-10 allowed public URLs.
4. Validate screenshot tiling <= 1600 px per side.
5. Build Docker image.
6. Run Fargate smoke only after operator starts AWS run.
7. Run `J25` pilot on 500-2,000 URLs.
8. Review accepted artifact rate and terms/robots audit.
9. Promote to EC2 Spot Batch standard run.
10. Feed accepted captures into receipt generation.
11. Feed screenshot tiles into OCR input queue.
12. Generate packet/proof examples.
13. Run release gates.
14. Deploy RC1 from accepted artifacts.
15. Continue broader capture only if useful.
16. Export artifacts.
17. Delete all AWS resources for zero-bill posture.

## 18. Open Decisions Before Execution

These are implementation decisions, not blockers for the plan:

1. Whether to use only EC2 Spot for standard capture or keep a Fargate fallback queue.
2. Whether generated PDFs are useful enough to enable by default for selected sources.
3. Whether to store accessibility snapshots in addition to DOM/visible text.
4. Whether to allow mobile viewport captures for specific government pages.
5. How many local government sites are terms/robots-approved for broad capture.
6. Whether to store screenshots in PNG only or add WebP/JPEG derivatives for proof pages.
7. Whether OCR should run in AWS immediately after `J25` or after manual QA of capture quality.

## 19. Bottom Line

Yes, AWS can run Playwright/Chromium capture safely and at scale.

The valuable version is not "scrape everything with a browser." The valuable version is:

- approve sources first
- render only public primary-information pages
- keep every screenshot <= 1600 px per side
- capture DOM/text/network metadata with redaction
- generate OCR-ready tiles
- convert accepted artifacts into source receipts and known gaps
- stop on legal/rate-limit/cost signals
- export and delete all AWS resources at the end

This makes jpcite more defensible for AI agents because it can show rendered primary-source evidence, not just cached URLs or model-generated summaries.
