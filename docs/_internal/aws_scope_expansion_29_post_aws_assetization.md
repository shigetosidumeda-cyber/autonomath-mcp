# AWS Scope Expansion 29/30: Post-AWS Assetization Plan

Date: 2026-05-15

Role: continuation operations / AWS shutdown assetization

Output file only: `/Users/shigetoumeda/jpcite/docs/_internal/aws_scope_expansion_29_post_aws_assetization.md`

AWS execution status: no AWS CLI/API commands executed. No AWS resources created, modified, or deleted by this document.

## 0. Executive Conclusion

AWS credit should be used as a short, intense public-primary-information factory, not as a permanent runtime dependency.

After the credit run, jpcite should own:

- immutable source snapshots
- normalized `source_profiles`
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- no-hit ledgers
- deterministic packet fixtures
- public proof pages
- agent-facing static discovery files
- offline update/regeneration scripts
- pricing and packaging assets

AWS should then be fully drained and deleted so that the service can operate without AWS spend.

The post-AWS product should feel to AI agents like:

> "I can cheaply retrieve a source-backed Japanese public-information packet instead of browsing uncertain pages or making unsupported claims."

The post-AWS product should feel to end users like:

> "I can ask my AI for a concrete business/legal/procurement/compliance output, and it can buy a cheap packet with citations, gaps, and source receipts."

The main design implication is that AWS outputs must be transformed into repo/static/assets/db artifacts that are:

- small enough to deploy
- immutable by version
- independently verifiable by checksum
- generated from public primary sources
- free of private CSV raw data
- safe for `no_hit_not_absence`
- useful without request-time LLM calls

## 1. Non-Negotiables

### 1.1 AWS Must End at Zero Ongoing Bill

The AWS credit run is temporary.

After final export:

- no S3 bucket remains unless the owner explicitly accepts ongoing bill risk
- no ECR image remains
- no Batch compute environment remains
- no ECS cluster remains
- no EC2 instance remains
- no EBS volume or snapshot remains
- no OpenSearch domain remains
- no Glue crawler/database/table remains unless confirmed zero cost and explicitly accepted
- no Athena output bucket remains
- no CloudWatch log group remains unless explicitly retained outside zero-bill requirement
- no NAT Gateway, Elastic IP, Load Balancer, ENI, Lambda, Step Functions, or scheduler remains

Recommended final state is "AWS account contains no jpcite tagged resources."

### 1.2 AWS Is a Factory, Not the Product Runtime

AWS is used to produce assets.

The production jpcite runtime should be able to serve:

- static packet examples
- static proof pages
- static indexes
- static DB chunks
- local or existing-hosting generated responses

without reaching into AWS.

### 1.3 Raw CSV Never Becomes a Stored Asset

Private user CSV files from freee, Money Forward, Yayoi, or generic accounting exports must not be stored in:

- AWS
- repo
- static assets
- logs
- telemetry
- proof pages
- screenshots
- packet examples

Only safe derived facts may be used, for example:

- period coverage
- account-category aggregates
- transaction count bands
- amount bands
- vendor identifiers after suppression and safety checks
- missing-field indicators
- accounting-software format family

Any assetization process that sees raw CSV must fail closed.

### 1.4 Public Primary Information Only

The asset base should prioritize Japanese public primary information:

- laws
- ordinances
- regulations
- public notices
- guidelines
- standards metadata
- permits
- registrations
- grants
- procurement
- statistics
- enforcement actions
- court and administrative decisions
- official agency pages
- official downloadable files

Non-primary sources can be used only as discovery hints, never as evidence in paid outputs.

### 1.5 No Hallucination Product Contract

Every generated output must be traceable to:

- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit_checks[]` where applicable
- `algorithm_trace`
- `request_time_llm_call_performed=false`

If evidence is insufficient, the packet should say so instead of filling gaps.

### 1.6 No-Hit Is Not Absence

The asset layer must encode:

```json
{
  "no_hit_semantics": "no_hit_not_absence"
}
```

Forbidden:

- "問題なし"
- "リスクなし"
- "該当なしと断定"
- "登録されていないことを証明"
- "処分歴なしと証明"

Allowed:

- "この検索条件・この取得範囲・この時点ではヒットを確認できませんでした"
- "未取得範囲があります"
- "表記ゆれや別法人の可能性があります"
- "追加確認が必要です"

## 2. What Must Be Assetized

### 2.1 Asset Classes

| Asset class | Purpose | Stored after AWS | Production use |
|---|---:|---:|---|
| `source_profile` | official source catalog | yes | source selection, proof pages, GEO |
| `source_snapshot` | immutable raw/public snapshot reference or allowed copy | conditional | audit, regeneration |
| `source_receipt` | evidence of retrieval | yes | every paid output |
| `extracted_record` | normalized entity/rule/opportunity/notice | yes | packet generation |
| `claim_graph` | claim-to-source mapping | yes | hallucination control |
| `known_gap` | missing coverage statement | yes | honest output |
| `no_hit_check` | negative-search ledger | yes | safe no-hit wording |
| `algorithm_rule` | deterministic generation rules | yes | output engine |
| `packet_fixture` | example paid output | yes | proof, tests, GEO |
| `proof_page` | public explanation page | yes | AI discovery |
| `eval_case` | regression prompt/case | yes | release gate |
| `pricing_map` | packet price and cost preview | yes | billing UX |
| `update_manifest` | post-AWS refresh schedule | yes | operations |

### 2.2 Storage Classes

Use five storage classes.

#### S0: Repo Contract Assets

Small, human-readable, versioned in git.

Examples:

- schemas
- source profile metadata
- packet catalog
- pricing map
- rules
- sample fixtures
- eval cases
- documentation

Suggested path:

```text
data/contracts/
data/source_profiles/
data/packet_catalog/
data/pricing/
data/evals/
docs/_internal/
```

#### S1: Static Runtime DB Assets

Deployed as static files.

Examples:

- compressed JSONL shards
- SQLite shards
- DuckDB/Parquet shards if supported by runtime tooling
- prebuilt indexes
- proof-page indexes

Suggested path:

```text
public/assets/db/{dataset_version}/
public/assets/db/current.json
public/assets/db/index.json
```

#### S2: Static Proof Assets

Public, agent-readable, safe for GEO.

Examples:

- proof pages
- packet examples
- capability pages
- source coverage pages
- benchmark pages
- screenshot thumbnails where allowed

Suggested path:

```text
public/proof/
public/packets/examples/
public/assets/evidence/
public/.well-known/
```

#### S3: Local Archive Assets

Not deployed by default, but kept on local disk or offline storage.

Examples:

- full AWS run export
- full source snapshots
- full screenshot receipts
- OCR intermediates
- full extraction logs
- cost/artifact ledgers

Suggested path:

```text
/Users/shigetoumeda/jpcite_artifacts/aws-runs/{run_id}/
/Users/shigetoumeda/jpcite_artifacts/source-archives/{dataset_version}/
/Users/shigetoumeda/jpcite_artifacts/checksums/{dataset_version}/
```

Rationale:

- avoids bloating git
- avoids ongoing AWS bill
- preserves auditability
- allows later regeneration

#### S4: Excluded Assets

Must not be kept.

Examples:

- raw private CSV
- secrets
- AWS credentials
- paid third-party proprietary datasets
- pages whose terms disallow storage
- CAPTCHA-protected content obtained through bypass
- full copyrighted text where only citation/snippet is allowed
- screenshots containing private user data

## 3. Proposed Directory Layout

### 3.1 Repo Layout

```text
jpcite/
  data/
    contracts/
      packet_output.schema.json
      source_receipt.schema.json
      claim_ref.schema.json
      known_gap.schema.json
      no_hit_check.schema.json
      algorithm_trace.schema.json
    source_profiles/
      registry.json
      nta_houjin.json
      nta_invoice.json
      egov_law.json
      egov_public_comment.json
      kanpo.json
      gbizinfo.json
      estat.json
      p_portal.json
      mlit_negative.json
      fsa_registry.json
      caa_disposals.json
      jftc_decisions.json
      local_government_index.json
    packet_catalog/
      packets.json
      packet_dependencies.json
      packet_examples_manifest.json
    pricing/
      packet_prices.json
      unit_prices.json
      preview_policy.json
      billing_copy.json
    evals/
      geo_prompts.jsonl
      forbidden_claim_cases.jsonl
      no_hit_cases.jsonl
      csv_privacy_cases.jsonl
      packet_regression_cases.jsonl

  public/
    assets/
      db/
        index.json
        current.json
        2026-05-aws-credit-run-01/
          manifest.json
          checksums.sha256
          source_profiles.min.json
          source_receipts.index.json.zst
          claim_graph.index.json.zst
          known_gaps.index.json.zst
          no_hit.index.json.zst
          packets.index.json.zst
          verticals/
            construction.sqlite.zst
            real_estate.sqlite.zst
            transport.sqlite.zst
            grants.sqlite.zst
            procurement.sqlite.zst
            compliance.sqlite.zst
            tax_labor.sqlite.zst
            vendor_risk.sqlite.zst
          search/
            source_text.lexicon.json.zst
            entity_aliases.json.zst
            rule_index.json.zst
      evidence/
        screenshots/
          index.json
          thumbnails/
        pdf/
          index.json
    proof/
      index.html
      sources/
      packets/
      pricing/
      coverage/
      evals/
    .well-known/
      jpcite-capabilities.json
      jpcite-packet-catalog.json
      jpcite-source-coverage.json
```

### 3.2 Local Archive Layout

```text
/Users/shigetoumeda/jpcite_artifacts/
  aws-runs/
    2026-05-aws-credit-run-01/
      export_manifest.json
      cost_artifact_ledger.csv
      checksums.sha256
      s3_export_listing.json
      batch_job_listing.json
      source_snapshots/
      extraction_outputs/
      screenshot_receipts/
      ocr_outputs/
      eval_outputs/
      packet_outputs/
      cleanup_evidence/
  offline-regeneration/
    scripts/
    input_manifests/
    output_manifests/
  local-update-runs/
    2026-06-01/
    2026-06-08/
```

This local archive can be backed up to non-AWS storage chosen by the owner. The plan does not assume any paid cloud storage after AWS.

## 4. Versioning Model

### 4.1 Dataset Version

Every published asset set gets a stable version:

```text
{YYYY-MM}-{run_name}-{sequence}
```

Example:

```text
2026-05-aws-credit-run-01
```

### 4.2 Immutable Version, Mutable Pointer

Immutable:

```text
public/assets/db/2026-05-aws-credit-run-01/
```

Mutable pointer:

```text
public/assets/db/current.json
```

`current.json` should contain:

```json
{
  "dataset_version": "2026-05-aws-credit-run-01",
  "published_at": "2026-05-20T00:00:00+09:00",
  "manifest_path": "/assets/db/2026-05-aws-credit-run-01/manifest.json",
  "status": "current",
  "previous_dataset_version": null
}
```

### 4.3 Source Version

Each `source_profile` gets:

```json
{
  "source_id": "egov_law",
  "profile_version": "2026-05-15",
  "official_name": "e-Gov法令検索",
  "source_type": "official_primary",
  "jurisdiction": "JP",
  "retrieval_modes": ["api", "bulk_download", "html", "screenshot"],
  "license_boundary": "verify_before_redistribution",
  "no_hit_semantics": "no_hit_not_absence",
  "default_update_frequency": "weekly",
  "proof_page_path": "/proof/sources/egov_law"
}
```

### 4.4 Record Version

Each normalized record gets:

```json
{
  "record_id": "sha256:...",
  "source_id": "egov_law",
  "dataset_version": "2026-05-aws-credit-run-01",
  "source_record_key": "official-stable-id-if-any",
  "retrieved_at": "2026-05-18T10:00:00+09:00",
  "observed_valid_from": null,
  "observed_valid_to": null,
  "content_hash": "sha256:...",
  "canonical_hash": "sha256:...",
  "schema_version": "1.0"
}
```

## 5. Manifest Contract

### 5.1 Top-Level Runtime Manifest

`public/assets/db/{dataset_version}/manifest.json` should be the entry point.

Minimum fields:

```json
{
  "dataset_version": "2026-05-aws-credit-run-01",
  "created_at": "2026-05-20T00:00:00+09:00",
  "created_from": {
    "aws_account_id": "993693061769",
    "aws_profile_name": "bookyou-recovery",
    "region": "us-east-1",
    "aws_run_id": "2026-05-aws-credit-run-01",
    "aws_resources_deleted_after_export": true
  },
  "runtime_dependency": {
    "aws_required": false,
    "request_time_llm_required": false,
    "private_csv_persisted": false
  },
  "files": [],
  "source_coverage": {},
  "packet_coverage": {},
  "quality_gates": {},
  "known_global_gaps": [],
  "checksums_path": "checksums.sha256"
}
```

### 5.2 File Manifest

Each file entry:

```json
{
  "path": "verticals/grants.sqlite.zst",
  "media_type": "application/zstd+sqlite",
  "size_bytes": 12345678,
  "sha256": "abc...",
  "record_count": 12345,
  "asset_class": "runtime_db",
  "contains_private_csv": false,
  "contains_raw_source_html": false,
  "contains_screenshot": false,
  "license_boundary": "redistributable_summary_only",
  "required_for_packets": ["grant_opportunity_radar", "csv_overlay_grant_match"]
}
```

### 5.3 Source Coverage Manifest

```json
{
  "source_id": "nta_invoice",
  "coverage_status": "partial",
  "retrieval_window": {
    "started_at": "2026-05-18T00:00:00+09:00",
    "ended_at": "2026-05-18T04:00:00+09:00"
  },
  "retrieval_modes_used": ["api", "download"],
  "records_observed": 1000000,
  "records_normalized": 999500,
  "records_failed": 500,
  "known_gaps_count": 3,
  "no_hit_supported": true,
  "safe_no_hit_wording_id": "nta_invoice_no_hit_v1"
}
```

## 6. Data Asset Categories by Business Value

### 6.1 High-Revenue Packet Families

Prioritize post-AWS assetization around packet families that AI agents can sell to end users.

| Packet family | User asks AI | Paid asset value | Key public data |
|---|---|---:|---|
| Grant opportunity | "使える補助金を探して" | high | J-Grants, ministries, local gov, gBizINFO, e-Gov, CSV-derived facts |
| Permit readiness | "この事業に許認可が必要？" | high | e-Gov, ministries, local gov, industry registries |
| Vendor public check | "この取引先を公的情報で確認して" | high | NTA, invoice, gBizINFO, EDINET, enforcement, registries |
| Compliance change impact | "法改正で何が変わった？" | high | e-Gov, public comments,官報, ministry notices |
| Procurement radar | "入札案件を探して" | medium/high | p-portal, JETRO, local gov,公告 |
| Tax/labor event radar | "今月やる税務労務は？" | medium/high | NTA, pension, MHLW, minimum wage, CSV-derived facts |
| Standards/certification check | "この製品に規格や表示義務は？" | medium/high | JISC, METI, CAA, PMDA, NITE, MIC |
| Local regulation check | "この自治体で営業できる？" | medium/high | local gov pages, ordinances, permit pages |
| Regional market/stat facts | "この地域で出店判断したい" | medium | e-Stat, GSI, MLIT, local open data |
| Dispute/enforcement research | "処分・審決・判例を見たい" | medium | courts, JFTC, CAA, FSA, MLIT, MHLW |

### 6.2 Assetization Rule

If a source does not directly enable a sellable packet, it should be lower priority.

The post-AWS asset base should be evaluated by:

```text
asset_value_score =
  packet_revenue_potential
  * agent_recommendability
  * evidence_quality
  * update_feasibility
  * reuse_count
  / maintenance_cost
```

Where:

- `packet_revenue_potential`: likely willingness to pay
- `agent_recommendability`: whether an AI agent can explain why to buy
- `evidence_quality`: official primary, stable IDs, timestamps
- `update_feasibility`: can be refreshed locally after AWS
- `reuse_count`: number of packet families relying on it
- `maintenance_cost`: local update burden

## 7. Post-AWS Update Strategy

### 7.1 Three Refresh Lanes

#### Lane A: Lightweight Frequent Updates

Runs locally or on existing hosting without AWS.

Frequency: daily to weekly.

Sources:

- NTA invoice status checks
- NTA corporate number differential checks
- e-Gov update feeds
- J-Grants current opportunities
- public comment current items
- procurement current tenders
- ministry news pages with stable RSS/feed
- selected enforcement pages

Output:

- small diff files
- updated `known_gaps`
- updated `source_last_checked_at`
- updated `current.json` pointer only if release gates pass

#### Lane B: Medium Scheduled Updates

Runs weekly or monthly.

Sources:

- gBizINFO
- EDINET metadata
- p-portal broader crawl
- local government high-value pages
- industry permit registries
- standards/certification indexes
- court/enforcement databases

Output:

- new DB shard candidates
- packet fixture refresh
- proof page refresh
- eval reruns

#### Lane C: Heavy Rebuilds

Runs manually, not on AWS unless a future explicit paid budget is approved.

Frequency: quarterly or as needed.

Sources:

- full law XML bulk
- large PDF/OCR corpus
- large local government recrawl
- screenshot receipt rebuild
- full vertical DB rebuild

Output:

- new dataset version
- migration notes
- full checksum set
- release candidate assets

### 7.2 Local Update Command Shape

Do not make post-AWS updates depend on AWS.

Expected local commands, to be implemented later:

```bash
pnpm data:sources:check --lane A
pnpm data:diff --since current
pnpm data:packets:regen --changed-only
pnpm data:evaluate --gates release
pnpm data:publish-assets --dataset-version YYYY-MM-local-N
```

The command names can change to match repo conventions, but the separation should remain:

1. check source changes
2. normalize/extract
3. compute diffs
4. regenerate affected packets
5. run gates
6. publish version pointer

### 7.3 Existing Hosting Update Option

If existing hosting already supports scheduled functions or cron at no extra meaningful cost, use it only for Lane A.

Allowed:

- small HEAD/GET checks
- manifest refresh
- feed polling
- source availability checks
- proof page status refresh

Not allowed:

- large crawling
- headless browser bulk crawling
- OCR
- private CSV processing persistence
- costly compute loops

## 8. Regeneration Model

### 8.1 Dependency Graph

Every packet type should declare dependencies.

Example:

```json
{
  "packet_id": "grant_opportunity_radar",
  "depends_on_sources": [
    "j_grants",
    "local_government_grants",
    "gbizinfo",
    "egov_law",
    "industry_permit_registry"
  ],
  "depends_on_algorithms": [
    "grant_matching_v1",
    "known_gap_builder_v1",
    "no_hit_formatter_v1"
  ],
  "depends_on_private_overlay": "optional_derived_facts_only"
}
```

When `j_grants` changes, only packets depending on J-Grants should be regenerated.

### 8.2 Deterministic Packet Generation

Packet generation should be deterministic:

```text
inputs + source version + algorithm version + pricing version = same packet
```

Each packet output should contain:

```json
{
  "packet_id": "grant_opportunity_radar",
  "packet_version": "1.0",
  "dataset_version": "2026-05-aws-credit-run-01",
  "algorithm_version": "grant_matching_v1",
  "request_time_llm_call_performed": false,
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "no_hit_checks": [],
  "algorithm_trace": {},
  "billing_metadata": {},
  "human_review_required": false,
  "_disclaimer": "公的一次情報に基づく機械生成の整理であり、専門家判断の代替ではありません。"
}
```

### 8.3 Changed-Only Regeneration

The regeneration engine should compute:

```text
changed_sources -> impacted_records -> impacted_claims -> impacted_packets -> impacted_proof_pages
```

This enables cheap post-AWS operation.

### 8.4 Algorithm Trace Retention

Every algorithmic output should include enough trace to debug:

- input source IDs
- rule IDs applied
- score components
- thresholds
- rejected candidates
- known gaps
- human review flag reason

Do not include:

- raw private CSV rows
- secrets
- internal prompts
- credentials
- private user identifiers beyond safe derived facts

## 9. Diff Monitoring

### 9.1 Source-Level Diff

Each source check should produce:

```json
{
  "source_id": "egov_law",
  "checked_at": "2026-06-01T09:00:00+09:00",
  "previous_hash": "sha256:old",
  "current_hash": "sha256:new",
  "diff_status": "changed",
  "change_type": ["content", "structure"],
  "severity": "needs_review",
  "impacted_assets": []
}
```

### 9.2 Diff Types

Track at least:

- `availability_changed`
- `content_changed`
- `schema_changed`
- `record_added`
- `record_removed`
- `record_updated`
- `redirect_changed`
- `file_hash_changed`
- `dom_selector_changed`
- `screenshot_visual_changed`
- `terms_changed`
- `robots_changed`

### 9.3 Severity Scoring

```text
severity_score =
  source_priority_weight
  + packet_dependency_weight
  + legal_effect_weight
  + user_visible_weight
  + schema_break_weight
  - confidence_discount
```

Severity classes:

- `ignore`: no material change
- `watch`: update metadata only
- `regen`: regenerate affected packets
- `review`: human review before publish
- `block`: do not publish current update

### 9.4 Visual Diff for Difficult Sources

For sources that are difficult to fetch as clean API/HTML:

- use Playwright locally for narrow checks
- screenshot width must be <= 1600px
- store screenshot hash
- store thumbnail only in public assets when allowed
- store full screenshot only in local archive if terms permit
- never bypass CAPTCHA or access controls

Screenshot receipt fields:

```json
{
  "source_id": "local_government_permit_page",
  "url": "https://example.lg.jp/...",
  "captured_at": "2026-06-01T09:00:00+09:00",
  "viewport": {
    "width": 1440,
    "height": 1200
  },
  "screenshot_sha256": "sha256:...",
  "thumbnail_path": "/assets/evidence/screenshots/thumbnails/...",
  "full_screenshot_public": false,
  "capture_method": "playwright",
  "access_control_bypassed": false
}
```

## 10. Evidence Retention

### 10.1 Receipt Is More Important Than Full Copy

For many public sources, retaining a full copy is less important than retaining:

- official URL
- stable source ID
- timestamp
- retrieval method
- content hash
- extracted claim
- source snippet where allowed
- screenshot hash where useful
- PDF/document hash
- known gaps

This keeps assets legally and operationally safer.

### 10.2 Retention Tiers

| Tier | Kept in repo | Kept in static assets | Kept local archive | Purpose |
|---|---:|---:|---:|---|
| R0 schema/manifest | yes | yes | yes | runtime contract |
| R1 normalized facts | yes/sometimes | yes | yes | production packets |
| R2 source receipts | yes/sometimes | yes | yes | proof |
| R3 source snapshots | no/rare | no/rare | yes | regeneration |
| R4 screenshots | thumbnails only | thumbnails only | full if allowed | difficult-page proof |
| R5 OCR intermediates | no | no | yes | rebuild/debug |
| R6 private CSV raw | no | no | no | prohibited |

### 10.3 Checksum Discipline

Every non-trivial artifact gets SHA-256.

Required files:

```text
checksums.sha256
manifest.json
export_manifest.json
import_manifest.json
cleanup_manifest.json
```

Release should fail if:

- a manifest file references a missing file
- a checksum does not match
- a file exists but is not referenced
- a public asset has `contains_private_csv=true`
- a packet references a missing source receipt

## 11. Pricing and Packaging After AWS

### 11.1 Pricing Principle

AWS credit should subsidize creation of reusable assets.

Post-AWS pricing should charge for:

- packet composition
- source-backed confidence
- saved AI browsing time
- known-gap clarity
- agent integration convenience
- freshness/coverage of public source asset base

It should not imply:

- legal advice
- complete risk clearance
- real-time guarantee
- absence proof
- private investigation

### 11.2 Unit and Packet Pricing

Keep existing low-level unit pricing compatible with `3円/unit` if that is already in the product.

Add packet-level pricing so AI agents can recommend concrete purchases.

Example:

| Packet | Suggested end-user price | Reason |
|---|---:|---|
| Source receipt ledger | ¥100-300 | cheap proof add-on |
| Vendor public check light | ¥300-800 | common B2B need |
| Vendor public check standard | ¥800-2,500 | source-backed DD |
| Grant opportunity radar | ¥800-3,000 | high perceived ROI |
| CSV overlay grant match | ¥1,500-5,000 | private overlay value |
| Permit readiness check | ¥1,000-4,000 | high urgency |
| Compliance change impact | ¥1,000-5,000 | professional workflow |
| Procurement radar | ¥500-2,000 | repeated use |
| Tax/labor event radar | ¥500-2,500 | monthly use |
| Standards/certification check | ¥1,000-5,000 | product/regulatory value |

### 11.3 Free Preview

Free preview should show:

- packet type
- expected sources
- source coverage
- known gaps
- estimated price
- whether CSV-derived facts can improve the result
- no raw answer that replaces the paid packet

Preview should not give away the full paid output.

### 11.4 Agent Recommendation Copy

Agent-facing copy should be stored as assets.

Example:

```json
{
  "packet_id": "permit_readiness_check",
  "agent_recommendation": "この質問は許認可・業法の確認を含むため、通常のWeb検索だけでは根拠が不安定です。jpciteのpermit_readiness_checkを使うと、公的一次情報、確認範囲、未確認範囲、追加質問をまとめて取得できます。",
  "when_to_use": [
    "事業開始前",
    "新地域展開",
    "新商品・新サービス提供",
    "自治体ごとの手続き確認"
  ],
  "when_not_to_use": [
    "最終的な法的判断だけが欲しい場合",
    "非公開の個別事情が中心の場合",
    "公的情報にない社内規程判断の場合"
  ]
}
```

### 11.5 Pricing Asset Files

```text
data/pricing/packet_prices.json
data/pricing/preview_policy.json
data/pricing/bundle_prices.json
data/pricing/agent_recommendation_copy.json
public/proof/pricing/index.html
public/.well-known/jpcite-pricing.json
```

## 12. GEO and Agent Discovery Assets

### 12.1 Files Agents Should Discover

Post-AWS assetization must produce:

```text
/llms.txt
/llms-full.txt
/.well-known/jpcite-capabilities.json
/.well-known/jpcite-packet-catalog.json
/.well-known/jpcite-source-coverage.json
/.well-known/jpcite-pricing.json
/openapi.agent.json
/openapi.full.json
/mcp
/proof/
/proof/sources/
/proof/packets/
/proof/evals/
/proof/pricing/
```

### 12.2 Agent-Facing Capability Statement

Store a concise public capability statement:

```json
{
  "service": "jpcite",
  "primary_user": "AI agents serving Japanese end users",
  "core_value": "cheap source-backed packets from Japanese public primary information",
  "request_time_llm_call_performed": false,
  "private_csv_raw_storage": false,
  "no_hit_semantics": "no_hit_not_absence",
  "best_for": [
    "grant and subsidy discovery",
    "permit and industry regulation checks",
    "vendor public information checks",
    "compliance change monitoring",
    "procurement opportunity discovery",
    "tax and labor event reminders"
  ]
}
```

### 12.3 Proof Pages

Each proof page should answer:

- What packet is this?
- What sources does it use?
- What does it not prove?
- What does no-hit mean?
- How much does it cost?
- Why should an AI agent recommend it?
- What exact JSON fields does it return?
- What quality gates protect against hallucination?

## 13. Post-AWS Production Runtime

### 13.1 Runtime Should Read Static Assets

The app should serve paid/free outputs by reading:

- packet catalog
- pricing map
- source profile index
- runtime DB shards
- proof assets

The runtime should not need:

- AWS S3
- AWS Batch
- AWS Lambda
- AWS OpenSearch
- AWS Bedrock
- AWS Textract
- AWS Athena
- AWS Glue

### 13.2 Runtime Query Pattern

For a request:

```text
user/agent request
-> classify packet type
-> cost preview
-> load relevant static index
-> apply deterministic algorithm
-> attach source receipts
-> attach claim refs
-> attach known gaps
-> attach billing metadata
-> return packet
```

### 13.3 Static DB Performance Budget

Targets:

- first manifest fetch: < 100 KB
- packet catalog: < 500 KB compressed
- common packet runtime shard: < 10 MB compressed
- vertical shard: preferably < 50 MB compressed
- full static DB set: acceptable if deployed as versioned assets, but avoid loading all at once

Shard by:

- vertical
- source family
- region
- update frequency
- packet dependency

## 14. Data Model for Static DB

### 14.1 Core Tables

For SQLite/DuckDB shards:

```sql
source_profiles(source_id, profile_version, official_name, source_type, jurisdiction, update_frequency, proof_url)
source_receipts(receipt_id, source_id, url, retrieved_at, method, content_hash, screenshot_hash, license_boundary)
entities(entity_id, entity_type, canonical_name, identifiers_json, aliases_json)
records(record_id, source_id, entity_id, record_type, canonical_hash, valid_from, valid_to, payload_json)
claims(claim_id, record_id, claim_type, claim_text, normalized_value_json, confidence, citation_json)
claim_refs(packet_id, claim_id, receipt_id, role)
known_gaps(gap_id, source_id, packet_id, gap_type, description, severity)
no_hit_checks(check_id, source_id, query_json, checked_at, result_count, semantics, safe_wording_id)
algorithm_rules(rule_id, algorithm_id, version, rule_type, rule_json)
packet_examples(packet_id, example_id, vertical, price_band, payload_json)
```

### 14.2 Public Identifiers

Prefer stable public identifiers:

- corporate number
- invoice registration number
- EDINET code
- permit/registration number
- procurement notice ID
- law ID
- article number
- public comment case ID
- official document number
- local government code
- statistical area code

Where no stable ID exists, create:

```text
source_id + normalized_url + canonical_title + content_hash
```

### 14.3 Entity Resolution

Entity resolution should be conservative.

Allowed:

- exact corporate number match
- exact invoice number match
- exact official registry number match
- normalized legal name plus address only as weak candidate

Required output:

- `match_confidence`
- `match_basis`
- `needs_review` where weak

Forbidden:

- merging entities based only on similar names
- hiding ambiguity
- claiming identity when only alias-level similarity exists

## 15. Local Regeneration Algorithms

### 15.1 Grant Matching

Inputs:

- public grant rules
- target industry
- location
- company size band
- CSV-derived revenue/expense bands if provided
- known gaps

Output classes:

- `eligible`
- `likely`
- `needs_review`
- `not_enough_info`
- `out_of_scope`

Never output "guaranteed eligible."

### 15.2 Permit Rule Check

Inputs:

- business activity
- location
- facility type
- employee count band
- sales channel
- regulated goods/services
- local government rules
- national industry laws

Algorithm:

- decision table
- rule graph traversal
- required additional facts
- known gap expansion

Output:

- likely permits/registrations to check
- responsible agency
- official source receipts
- missing facts
- safe next actions

### 15.3 Vendor Public Check

Inputs:

- corporate number or company name
- invoice number if present
- public registries
- enforcement/public notice sources
- procurement/award data
- EDINET/gBizINFO where available

Score:

```text
public_evidence_risk_attention_score
```

Always pair with:

- `evidence_quality_score`
- `coverage_gap_score`

Do not call it credit score.

### 15.4 Compliance Change Impact

Inputs:

- law/regulation diffs
- public comments
- ministry notices
-官報/告示
- industry mapping
- affected packet catalog

Algorithm:

- structural diff
- article/section mapping
- deadline extraction
- affected business activity mapping
- action candidate generation

Output:

- what changed
- who may be affected
- by when
- what to check
- sources
- gaps

### 15.5 CSV Overlay

Raw CSV is processed only ephemerally.

Input:

- local/browser/upload transient file

Derived facts:

- period
- format family
- account category totals
- vendor count band
- recurring payment bands
- payroll/tax/labor-related category bands
- revenue band
- expense band

Output:

- derived fact summary
- packet request enrichment
- no raw rows

Suppression:

- small groups suppressed
- rare vendors suppressed unless public identifier provided
- formula-like cells neutralized
- PII fields excluded

## 16. Import Pipeline from AWS Export to Repo/Static Assets

### 16.1 Import Stages

Stage I0: Freeze AWS run

- stop new AWS jobs
- wait for jobs to finish or cancel
- produce export manifest
- produce checksums

Stage I1: Local download/export

- copy all allowed artifacts to local archive
- verify checksums
- record missing artifacts

Stage I2: Classify assets

- S0 repo contract
- S1 static runtime DB
- S2 static proof
- S3 local archive
- S4 excluded

Stage I3: Convert assets

- normalize JSON
- compress large JSONL
- shard DB
- build search indexes
- build proof indexes
- create thumbnails

Stage I4: Safety scan

- private CSV leak scan
- secret scan
- raw source redistribution boundary check
- no-hit wording scan
- prohibited claim scan
- license boundary scan

Stage I5: Quality gates

- schema validation
- checksum validation
- packet regression tests
- GEO discovery tests
- pricing consistency tests
- static asset size tests

Stage I6: Publish to repo/static

- commit small contract assets
- place deployable assets under `public/assets/db/{dataset_version}`
- update `current.json`
- update proof pages

Stage I7: AWS cleanup

- delete AWS resources
- verify zero jpcite resources
- save cleanup evidence to local archive and repo doc

### 16.2 Import Manifest

Create:

```text
public/assets/db/{dataset_version}/import_manifest.json
```

Fields:

```json
{
  "dataset_version": "2026-05-aws-credit-run-01",
  "imported_at": "2026-05-20T00:00:00+09:00",
  "source_export_manifest_sha256": "sha256:...",
  "files_imported": [],
  "files_excluded": [],
  "safety_scans": {
    "private_csv_leak": "pass",
    "secret_scan": "pass",
    "no_hit_wording": "pass",
    "license_boundary": "pass"
  },
  "release_gate_status": "pass"
}
```

## 17. Quality Gates

### 17.1 Release Blockers

Block release if:

- raw CSV appears in any artifact
- source receipt missing for a claim
- `no_hit` is worded as proof of absence
- packet has price but no billing metadata
- packet uses unapproved source
- artifact checksum mismatch
- large static assets break deployment limits
- `request_time_llm_call_performed` is missing or true for deterministic packets
- private credentials appear
- AWS URL is required for production packet serving
- source terms prohibit public redistribution and asset is public
- known high-value source has no `known_gaps` entry despite partial coverage

### 17.2 Soft Warnings

Warn but do not necessarily block:

- source stale beyond target frequency
- screenshot missing when DOM extraction succeeded
- weak entity match
- low evidence quality score
- high coverage gap score
- packet example missing for low-priority vertical

### 17.3 Post-AWS Zero-Bill Gate

Production launch can happen before AWS deletion only if there is an explicit deadline for deletion.

But final completion is not achieved until:

- all required artifacts are exported
- production no longer depends on AWS
- AWS resources are deleted
- cleanup evidence is saved
- no ongoing AWS bill source remains for jpcite

## 18. Ongoing Operations Without AWS

### 18.1 Weekly Routine

Weekly:

1. run Lane A source checks
2. review diff report
3. regenerate changed-only packets
4. run release gates
5. update `current.json` only if pass
6. publish proof-page update
7. record operation log

### 18.2 Monthly Routine

Monthly:

1. run Lane B source checks
2. review high-value verticals
3. update pricing/packet examples if needed
4. refresh GEO proof pages
5. run agent prompt evals
6. archive old local outputs

### 18.3 Quarterly Routine

Quarterly:

1. decide if heavy rebuild is necessary
2. if no AWS budget exists, run local subset only
3. rebuild high-value shards
4. compare coverage metrics against prior version
5. update public coverage statement

## 19. Asset Freshness Display

Every packet should show:

```json
{
  "dataset_version": "2026-05-aws-credit-run-01",
  "source_freshness": [
    {
      "source_id": "j_grants",
      "last_checked_at": "2026-06-01T09:00:00+09:00",
      "freshness_status": "fresh"
    }
  ],
  "known_staleness": [],
  "not_real_time": true
}
```

Public copy should say:

> "このpacketは公的一次情報の取得時点・確認範囲を明示します。リアルタイム網羅や不存在証明ではありません。"

## 20. Revenue-Oriented Asset Priorities

### 20.1 P0 Asset Families

P0 after AWS:

1. Grants and subsidies
2. Permit / industry regulation
3. Vendor public check
4. Compliance change impact
5. Procurement radar
6. Tax/labor event radar
7. Agent discovery and pricing assets

These are easiest for AI agents to recommend because the end-user job is concrete and paid value is obvious.

### 20.2 P1 Asset Families

1. Local government permit expansion
2. Standards/certification checks
3. Regional statistics and geospatial facts
4. Court/dispute/enforcement research
5. Sector-specific professional packs

### 20.3 P2 Asset Families

1. Deep OCR archive expansion
2. Broad historical comparisons
3. Long-tail local rules
4. Rare industry rule packs
5. Advanced benchmark/eval pages

## 21. Mapping to Main Plan Execution Order

The merged order should be:

### M0: Freeze Product Contract

Before AWS run:

- packet schema
- source receipt schema
- claim ref schema
- known gap schema
- no-hit wording
- pricing map draft
- manifest schema

Reason: AWS artifacts must be generated into a stable contract.

### M1: Build AWS Guardrails and Autonomous Run Plan

Before AWS run:

- budget stop lines
- IAM boundary
- tag policy
- job queues
- kill switch
- export manifest target
- zero-bill cleanup list

Reason: Codex/Claude rate limits must not stop AWS jobs, but cost boundaries must stop runaway spend.

### M2: Run AWS Public Information Factory

AWS work:

- collect public primary sources
- Playwright difficult pages
- screenshot receipts <= 1600px width
- OCR where useful
- extract normalized records
- create source receipts
- create claim graph
- create no-hit ledgers
- create packet fixtures
- run evals

Reason: use expiring credit to build durable corpus.

### M3: Export and Assetize

Immediately after AWS run:

- export artifacts
- checksum
- local archive
- convert to static DB
- create proof pages
- create pricing/discovery assets
- run safety gates

Reason: transfer value out of AWS before deletion.

### M4: Implement/Finalize P0 Runtime

In repo:

- static DB readers
- packet composers
- REST facade
- MCP tools
- cost preview
- proof pages
- `llms.txt`
- `.well-known`
- `openapi.agent.json`

Reason: turn assets into paid product.

### M5: Staging and Production Deploy

Deploy:

- staging with current asset version
- run regression/eval
- production rollout
- monitor logs
- verify no AWS runtime dependency

Reason: deploy quickly after asset import, before source freshness decays.

### M6: AWS Drain and Deletion

After production no longer depends on AWS:

- delete compute
- delete indexes
- delete buckets after local export verification
- delete logs
- delete support resources
- verify no jpcite resources
- save cleanup evidence

Reason: user requires no further AWS charges.

### M7: Post-AWS Lightweight Operations

Ongoing:

- local/hosting source checks
- changed-only regeneration
- proof refresh
- pricing iteration
- GEO eval
- packet sales monitoring

Reason: keep value alive without AWS bill.

## 22. Specific Post-AWS Work Items

### P0 Engineering

1. Add manifest schemas.
2. Add static DB manifest loader.
3. Add packet dependency graph.
4. Add changed-only regeneration runner.
5. Add source freshness model.
6. Add no-hit wording validator.
7. Add source receipt completeness validator.
8. Add private CSV leak scanner.
9. Add pricing map validator.
10. Add proof page generator.
11. Add `.well-known` asset generator.
12. Add local update run log.

### P0 Product

1. Finalize 7-10 sellable packet types.
2. Define free preview for each.
3. Define paid output fields for each.
4. Define recommended price bands.
5. Define agent recommendation copy.
6. Define "when not to use" copy.
7. Define refund/quality posture if source gaps are high.

### P0 Operations

1. Decide local archive destination.
2. Decide maximum static asset size for deployment.
3. Decide screenshot public/private boundary.
4. Decide update frequency per source.
5. Decide release owner for source term changes.
6. Decide AWS deletion acceptance checklist.

## 23. Risks and Controls

### 23.1 Repo Bloat

Risk:

- committing huge generated assets makes repo slow

Control:

- keep schemas/manifests in git
- keep deployable compressed shards only if size fits
- keep full archive outside repo
- shard by vertical
- use `current.json` pointer

### 23.2 Static Hosting Limits

Risk:

- large DB files exceed hosting limits

Control:

- max shard size target
- compressed assets
- lazy load by packet
- store only runtime indexes publicly
- keep full archive local

### 23.3 Stale Public Information

Risk:

- users rely on old data

Control:

- freshness field on every packet
- source `last_checked_at`
- known staleness warnings
- Lane A local updates
- no real-time claims

### 23.4 Legal/Terms Boundary

Risk:

- public source allows viewing but not bulk redistribution

Control:

- license boundary per source
- store receipts and hashes where full copy is unsafe
- public snippets only when allowed
- full local archive only if allowed
- source terms diff monitoring

### 23.5 False Confidence

Risk:

- packets look authoritative beyond evidence

Control:

- no-hit safe wording
- `known_gaps[]`
- evidence quality score
- coverage gap score
- human review flag
- explicit disclaimers

### 23.6 Private CSV Leak

Risk:

- raw financial data leaks into assets

Control:

- raw CSV never stored
- derived facts only
- leak scanner
- suppression
- fixture-only public examples
- fail-closed import

### 23.7 AWS Cleanup Race

Risk:

- delete AWS before export verification

Control:

- export manifest
- checksum verification
- local archive check
- static DB smoke test
- only then delete

### 23.8 AWS Runtime Dependency

Risk:

- production accidentally reads S3/OpenSearch

Control:

- environment check forbids AWS URLs in production runtime config
- static asset smoke test with network restrictions
- dependency scan
- post-cleanup production smoke

## 24. Metrics After AWS

### 24.1 Asset Metrics

- number of source profiles
- number of source receipts
- number of normalized records
- number of claim refs
- number of known gaps
- number of no-hit ledgers
- number of packet examples
- number of proof pages
- percent of packets with complete receipts
- percent of sources with freshness targets

### 24.2 Product Metrics

- preview-to-paid conversion
- packet revenue by type
- average packet price
- API/MCP unit usage
- agent discovery page hits
- proof page hits
- cost preview completion
- refund/support issues by packet

### 24.3 Quality Metrics

- forbidden no-hit wording count
- missing source receipt count
- stale source count
- private leak scanner failures
- weak entity match rate
- high coverage gap packet rate
- eval pass rate

### 24.4 Maintenance Metrics

- local update runtime
- changed source count per week
- changed-only regeneration count
- static asset size growth
- manual review queue size
- source terms change count

## 25. Pricing the Data Asset Itself

The AWS credit creates an asset base.

The product can monetize it in three layers:

### Layer 1: API/MCP Units

Low-level usage, compatible with agent workflows.

Example:

- source lookup
- source receipt fetch
- packet preview
- no-hit check
- claim graph fetch

### Layer 2: Paid Packets

Most important revenue layer.

Example:

- `grant_opportunity_radar`
- `permit_readiness_check`
- `vendor_public_check`
- `compliance_change_impact`
- `procurement_radar`
- `tax_labor_event_radar`

### Layer 3: Bundles

For repeated workflows.

Example:

- monthly SMB review bundle
- vendor onboarding bundle
- grant search bundle
- compliance watch bundle
- professional office client-pack bundle

## 26. What AWS Should Produce Specifically for Assetization

AWS run should emit these final folders before cleanup:

```text
final_export/
  manifest.json
  checksums.sha256
  source_profiles/
  source_receipts/
  extracted_records/
  claim_graph/
  known_gaps/
  no_hit_ledgers/
  packet_fixtures/
  proof_pages/
  eval_reports/
  pricing_assets/
  geo_assets/
  screenshot_receipts/
  cost_artifact_ledger/
  cleanup_precheck/
```

Every folder should be usable by the local import pipeline.

## 27. What Not to Assetize

Do not assetize:

- AWS job logs that contain secrets
- raw private CSV
- user-uploaded files
- temporary OCR scratch files unless safe and local-only
- full browser HAR with cookies
- screenshots with session identifiers
- CAPTCHA pages
- blocked pages
- AI-generated prose without source refs
- unsupported "risk-free" claims
- incomplete outputs without `known_gaps`

## 28. Final Acceptance Criteria

The post-AWS assetization is complete when:

1. `public/assets/db/current.json` points to a valid dataset version.
2. The dataset manifest validates.
3. Checksums pass.
4. Static DB shards are loadable.
5. P0 packet fixtures render.
6. Proof pages render.
7. `.well-known` and `llms.txt` assets are present.
8. Pricing assets validate.
9. No raw CSV is present.
10. No forbidden no-hit wording is present.
11. Every paid packet claim has `claim_refs`.
12. Every `claim_ref` resolves to a `source_receipt`.
13. `known_gaps` exist for partial coverage.
14. Production can run with AWS network access disabled.
15. AWS resources are deleted after verified export.
16. Cleanup evidence is saved locally and summarized in repo docs.

## 29. Final Recommended Operating Posture

Use AWS once to create a strong first corpus.

Then operate jpcite as:

- static-data-first
- deterministic-output-first
- source-receipt-first
- agent-discovery-first
- paid-packet-first
- no-AWS-bill-first

This fits the service concept better than keeping a live cloud retrieval system.

The core promise becomes:

> "日本の公的一次情報を、AIエージェントが安く・速く・根拠付きで使える成果物に変換しておく。"

That promise survives AWS shutdown because the value is in the curated, versioned, source-backed asset base and packet generation contract, not in the temporary infrastructure used to build it.

