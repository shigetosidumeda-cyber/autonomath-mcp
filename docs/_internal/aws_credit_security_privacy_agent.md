# AWS Credit Run Security / Privacy / Logging Plan

作成日: 2026-05-15  
対象: jpcite AWS credit run  
クレジット残高: USD 19,493.94  
期間: 1-2週間  
担当範囲: security / privacy / logs / CSV / secrets / publication boundary  
状態: planning only。実装コード、AWS CLI、AWS リソース作成はこの文書の範囲外。

## 0. Executive Contract

AWS credit run は、短期間で source lake、OCR、Parquet、proof pages、評価ログを作るための加速枠であり、private data を増やす枠ではない。安全な消化の前提は次の通り。

- raw CSV は保存しない、S3 に置かない、ログに出さない、成果物に転記しない。
- public official source と private overlay は bucket、prefix、KMS key、IAM role、ログ、公開手順を分離する。
- 公開可能なのは official source 由来の URL、取得時刻、hash、license/terms note、正規化後の source receipt、集計済み proof だけ。
- private overlay はユーザー持ち込み CSV、内部評価メモ、非公開事業判断、tenant/customer 文脈を含むため、public page、OpenAPI example、MCP catalog、JSON-LD、marketing proof に混ぜない。
- CloudWatch、S3 server access logs、Athena query result、Glue crawler logs、Batch/ECS logs は payload value を持たない shape-only telemetry に制限する。
- AWS credit を消化するためにセキュリティ設定を緩めない。消化額よりも漏えい防止、削除可能性、再現性、公開境界を優先する。

## 1. Data Classification

| Class | Examples | Storage | Public output |
|---|---|---|---|
| Public source raw | 官公庁 HTML/PDF/API payload、取得 URL、HTTP metadata | S3 public-source raw bucket。SSE-KMS 必須。公開 bucket ではない | 原文再配布は terms 確認後のみ。原則は URL/hash/引用最小限 |
| Public source normalized | JSONL/Parquet、source receipt、checksum manifest | S3 public-source normalized bucket/prefix | source receipt、proof ledger、aggregate は可 |
| Derived public proof | proof pages、receipt coverage、no-hit reason、known gaps | S3 artifact bucket。release gate 後に公開先へ同期可 | 可。ただし private overlay 混入 scan 後 |
| Private overlay | CSV profile、tenant scoped aggregate、quality findings、idempotency metadata | private bucket/prefix。別 KMS key。短期 TTL | 不可。公開は aggregate template only |
| Raw CSV / row records | uploaded bytes、cell values、摘要、取引先、自由記述、行単位正規化 | 永続保存禁止。transient memory only | 絶対不可 |
| Secrets | AWS credentials、API keys、webhooks、KMS admin material、customer keys | Secrets Manager / runtime secret only | 絶対不可 |
| Logs | request_id、job_id、counts、duration、status、reject code | CloudWatch with retention | 公開不可。必要なら集計のみ |

## 2. Public Source / Private Overlay Separation

### 2.1 Required Boundary

AWS 側の保管単位は少なくとも次に分ける。

| Boundary | Purpose | Allowed content | Forbidden content |
|---|---|---|---|
| `public-source-raw` | official source mirror | public URL payload、fetch metadata、checksum | CSV、tenant id、customer data、API key、operator note |
| `public-source-normalized` | normalized source data | JSONL/Parquet、source receipt candidates | row-level private overlay、manual private notes |
| `private-overlay` | CSV-derived aggregate and QA | CSV file profile、column map、counts、k-thresholded aggregates | raw CSV bytes、raw rows、cell values |
| `run-artifacts` | release/eval outputs | public-safe proof pages、coverage reports、scan reports | private overlay unless explicitly marked internal |
| `logs-audit` | S3 access logs / audit exports | bucket access logs、inventory reports | payload body、CSV samples |

Naming may differ, but the boundary must be enforceable through separate buckets or separate prefixes with distinct IAM policies and KMS keys. For this run, separate buckets are preferred because accidental public sync and Athena/Glue crawl scope are easier to constrain.

### 2.2 Promotion Rule

Data may move only in this direction:

`public-source-raw -> public-source-normalized -> run-artifacts -> public site candidate`

Private overlay may contribute only aggregate feature flags to internal evaluation, never to public source receipts:

`private-overlay -> internal QA aggregate -> release gate evidence`

No path may move from `private-overlay` to `public site candidate` without a written privacy exception, manual review, and leak scan.

## 3. S3 Bucket Policy Requirements

Every run bucket must have these baseline controls:

- Block Public Access enabled at account and bucket level.
- Object Ownership set to bucket-owner-enforced.
- ACLs disabled.
- TLS-only access enforced.
- SSE-KMS required for all `PutObject`.
- Unencrypted object upload denied.
- Cross-account access denied unless explicitly allowlisted for a named audit role.
- Delete operations limited to cleanup/operator role, not batch worker role.
- Public website hosting disabled for all AWS run buckets.
- Lifecycle rules set before bulk ingest starts.

### 3.1 Public Source Buckets

Public source buckets are not public buckets. They hold public-source-derived data, but access stays private until release artifacts pass gates.

Required policy posture:

- Read/write allowed only to `jpcite-credit-run-ingest-role`, `jpcite-credit-run-normalize-role`, and read-only audit role.
- `PutObject` requires KMS key for public source.
- `GetObject` denied to anonymous principal and wildcard principal.
- `ListBucket` allowed only to run roles and audit role.
- `DeleteObject` denied to ingest/normalize roles.
- Optional replication/export uses a separate artifact promotion role.

### 3.2 Private Overlay Bucket

Private overlay bucket is stricter than public source buckets.

Required policy posture:

- No public access, no cross-account access, no replication to public buckets.
- Read/write allowed only to CSV aggregation job role and security audit role.
- KMS key is separate from public-source KMS key.
- Batch/OCR/source crawler roles cannot read private overlay.
- Glue crawlers and Athena workgroups must not crawl/query private overlay unless a dedicated internal workgroup is used.
- S3 Inventory for this bucket must exclude object metadata that could contain customer labels.
- Lifecycle expiration defaults to 14 days for temporary aggregates unless an explicit retention reason exists.

### 3.3 Artifact Bucket

Artifact bucket may contain public candidates but is still private until promotion.

Required policy posture:

- Write allowed only to generator/eval roles.
- Read allowed to audit/release roles.
- Promotion role can read only `public-safe/` prefix.
- `internal/`, `private-overlay-derived/`, `debug/`, and `failed/` prefixes are denied to promotion role.
- Any public sync target must consume only the release manifest, not a broad bucket prefix.

## 4. KMS / SSE

### 4.1 Keys

Use separate customer-managed KMS keys:

| KMS key | Scope | Who can decrypt | Notes |
|---|---|---|---|
| Public source key | raw/normalized official source data | ingest, normalize, audit | Does not imply public readability |
| Private overlay key | CSV-derived aggregates and private QA | CSV aggregate role, security audit | No public artifact role |
| Artifact key | generated public-safe candidates | generator, eval, release audit | Promotion reads only manifest-approved objects |
| Logs key | CloudWatch export / S3 logs | audit/security roles | Operators can inspect metadata without payload values |

### 4.2 Key Policy Rules

- KMS admin is separate from KMS decrypt users.
- Batch/ECS jobs get decrypt only for the bucket they need.
- No wildcard `kms:Decrypt` across all keys.
- No sharing KMS decrypt permission with public deployment or docs publishing credentials.
- Key rotation enabled where supported.
- Disable/delete key is restricted to break-glass admin and should not be part of routine cleanup.
- CloudTrail records KMS decrypt activity for private overlay key.

## 5. CSV Handling

### 5.1 Absolute Rule

Raw CSV is prohibited in all persistent surfaces:

- S3 objects
- CloudWatch logs
- Batch/ECS task logs
- Athena query results
- Glue tables
- OpenSearch indexes
- local debug artifacts
- proof pages
- public examples
- support attachments
- prompt transcripts

CSV may be read only as a transient input stream for validation and aggregation.

### 5.2 Allowed CSV-Derived Outputs

Allowed outputs are shape and aggregate only:

- provider family guess: `freee`, `money_forward`, `yayoi`, `unknown`
- header presence after redaction
- row count
- date range
- parse status
- reject/review code
- column mapping confidence
- aggregate amount buckets
- account category counts
- k-thresholded counts where `entry_count >= 3`
- formula-like cell count
- sensitive-pattern count
- `human_review_required=true|false`

### 5.3 Forbidden CSV-Derived Outputs

Never persist or publish:

- 摘要、仕訳メモ、自由記述
- 取引先、顧客名、従業員名、作成者
- invoice number、receipt number、bank account、card number
- row-level normalized records
- row anomaly extracts
- exact rare transaction buckets
- raw parse errors containing values
- model prompts containing cell values

### 5.4 Rejection Defaults

Reject rather than redact when files look like:

- payroll detail
- bank transfer instruction
- customer/patient/student/resident/person roster
- files containing My Number-like identifiers
- files with bank account/card number columns
- files where free-text values are required to produce the requested result

## 6. CloudWatch / Logs / Telemetry Limits

### 6.1 Allowed Log Fields

Logs may include:

- `timestamp`
- `request_id`
- `job_id`
- `tenant_hash` or `customer_hash`
- `role`
- `service`
- `bucket_class`
- `object_count`
- `byte_count`
- `row_count`
- `column_count`
- `status`
- `reject_code`
- `duration_ms`
- `cost_tag`
- `source_domain`
- `source_url_hash`
- `sha256` for public source object

### 6.2 Forbidden Log Fields

Logs must not include:

- API keys, AWS credentials, session tokens, signed URLs
- raw CSV bytes, row values, cell values
- 摘要, 取引先, personal names, addresses, phone, email
- prompt bodies with private values
- full request/response bodies
- raw exception bodies from third-party services
- object keys that embed customer names or private source labels
- SQL query text if it includes literal private values

### 6.3 Retention

| Log group | Retention | Notes |
|---|---:|---|
| Batch/ECS worker logs | 7-14 days | Shape-only. No payload. |
| Ingest/fetch logs | 14-30 days | public source metadata only |
| CSV validation logs | 7 days | reject code/count only |
| CloudTrail management events | 90+ days | security audit |
| S3 access logs / inventory | 30-90 days | bucket/object metadata only |
| Cost/budget logs | 90 days | no payload |

Longer retention requires a written reason and confirmation that logs are payload-free.

## 7. IAM Minimum Privilege

### 7.1 Role Split

| Role | Allowed | Explicitly denied |
|---|---|---|
| Ingest role | fetch public sources, write public-source raw, read own manifests | private overlay read/write, artifact promotion, delete |
| Normalize role | read public-source raw, write normalized, Glue/Athena public workgroup | private overlay, KMS private key, public sync |
| OCR/extract role | read public-source raw PDFs, write extraction candidates | private overlay, secrets read, artifact promotion |
| CSV aggregate role | transient CSV processing, write private aggregate only | public artifact write, public-source delete, raw CSV persistence |
| Eval/generator role | read normalized public source, write run artifacts | private overlay unless using internal aggregate allowlist |
| Release promotion role | read release manifest and `public-safe/` artifacts | private/internal/debug prefixes, private KMS key |
| Audit role | read metadata, policies, logs, inventories | write/delete data, start spend-heavy jobs |
| Cleanup role | delete tagged transient resources and expired objects | read private payload values unless separately approved |

### 7.2 Global Conditions

All workload roles should be constrained by:

- required tags: `Project=jpcite`, `CreditRun=2026-05`, `Environment=credit-run`
- region allowlist for the run
- bucket allowlist
- KMS key allowlist
- no IAM user/role creation by worker roles
- no policy attachment by worker roles
- no Secrets Manager broad read
- no public ACL or public bucket policy changes

### 7.3 Athena / Glue

- Use separate Athena workgroups for public-source and private-overlay analysis.
- Public-source workgroup output must not point to private overlay bucket.
- Private-overlay workgroup output must use private overlay KMS key and short retention.
- Glue crawlers must be scoped to explicit public prefixes. No bucket-root crawls.
- Table names must not include customer names.
- Query result buckets must have the same or stricter controls as the queried data.

## 8. Secrets Handling

Secrets are not credit-run artifacts.

Required posture:

- AWS credentials are not committed, pasted into docs, embedded in notebooks, or stored in S3.
- Runtime secrets live in the appropriate secret manager or environment secret store.
- Logs show secret presence only, never value.
- API keys are redacted to prefix plus last four characters at most.
- Signed URLs are treated as secrets and never logged or published.
- Any key used by a batch worker is scoped to the minimum source/service and expires or is rotated after the run.
- If a secret appears in S3, logs, repo, prompt, issue, screenshot, or artifact, stop the run, revoke/rotate, delete exposed copies, and record the incident.

## 9. Public Release Gate

No artifact from the AWS run can be published until it passes these gates:

1. Release manifest lists every object to publish.
2. Object source is `public-safe/` or equivalent release prefix.
3. No object came directly from private overlay.
4. CSV leak scan passes: no row values, no counterparties, no memo/free-text, no payroll/bank detail.
5. Secret scan passes: no key-like values, signed URLs, tokens, credentials.
6. PII scan passes: no emails, phone numbers, addresses, personal identifiers outside public official source context.
7. Source receipt completeness passes: URL, access date, hash, source type, known gaps.
8. License/terms note exists for source family.
9. Small-cell aggregate suppression is enforced.
10. Manual reviewer signs off on publication boundary.

Publication should consume the manifest, not broad sync commands or wildcard prefixes.

## 10. Incident / Stop Conditions

Stop spend-heavy jobs immediately if any of these occur:

- raw CSV appears in S3, CloudWatch, Athena, OpenSearch, or artifact output
- private overlay appears in public-safe artifact
- any API key, AWS credential, signed URL, webhook, or token is logged
- bucket public access is enabled
- KMS encryption is missing on new objects
- worker role gains broad `s3:*`, `kms:*`, `iam:*`, or `secretsmanager:*`
- Athena/Glue crawls a bucket root or private prefix unintentionally
- Cost Explorer/Budgets visibility is unavailable while spend-heavy jobs are running
- operator cannot identify which job wrote a suspicious object

Immediate response:

1. Pause new jobs.
2. Preserve minimal audit metadata.
3. Delete exposed artifacts from publication candidates.
4. Rotate affected secrets if any.
5. Re-scan buckets/logs/artifacts.
6. Document root cause and restart only after policy or workflow correction.

## 11. Absolutely Do Not Do

- Do not spend credit by uploading real customer CSVs or private datasets to S3.
- Do not store raw CSV, even in a "temporary" bucket.
- Do not log request bodies, CSV samples, parsed rows, or model prompts containing private data.
- Do not use public S3 buckets for the run.
- Do not make a bucket public because the underlying official source is public.
- Do not combine public source and private overlay in the same bucket root or Glue database.
- Do not give batch jobs admin policies.
- Do not let worker roles read all Secrets Manager secrets.
- Do not use wildcard public sync from artifact buckets.
- Do not publish debug pages, failed outputs, exception dumps, Athena result dumps, or worker logs.
- Do not include customer names, tenant names, or private labels in S3 object keys.
- Do not create long-lived OpenSearch indexes containing private overlay.
- Do not rely on AWS Budgets as a hard technical stop.
- Do not chase full USD 19,493.94 consumption at the expense of security controls.

## 12. Acceptance Checklist

Before Day 1 scale-up:

- [ ] Bucket/classification map approved.
- [ ] Public source and private overlay are separated by bucket or enforceable prefix plus IAM/KMS boundaries.
- [ ] Block Public Access, TLS-only, and SSE-KMS requirements are enabled for all run buckets.
- [ ] KMS keys are separated for public source, private overlay, artifacts, and logs.
- [ ] IAM roles are split by ingest, normalize, OCR, CSV aggregate, eval/generator, release, audit, cleanup.
- [ ] CloudWatch log field allowlist is documented for every job family.
- [ ] CSV raw persistence is technically and operationally prohibited.
- [ ] Athena/Glue scopes are explicit and do not crawl bucket roots.
- [ ] Release manifest process exists.
- [ ] Secret scan, CSV leak scan, PII scan, and publication-boundary review are required before any public output.

Before final cleanup:

- [ ] Spend-heavy jobs stopped.
- [ ] Transient private overlay objects expired or deleted according to retention rule.
- [ ] Artifact manifest retained.
- [ ] Bucket inventory and KMS decrypt audit reviewed.
- [ ] No public access findings remain.
- [ ] Final ledger records what was generated, what was deleted, and what remains private.
