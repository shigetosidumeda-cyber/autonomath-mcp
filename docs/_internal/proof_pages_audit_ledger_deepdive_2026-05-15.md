# Proof pages / audit ledger / receipt verification UX deep dive

Date: 2026-05-15  
担当: Proof pages / audit ledger / receipt verification UX  
Status: design deep dive only. 実装コードは触らない。  
Scope: proof page URL/内容/JSON-LD設計、`source_receipt` ledger表示、`content_hash`/`corpus_snapshot`/`no-hit`/`freshness`表示、private CSV由来情報を出さない検証UX。

## 0. Executive Contract

source-backed outputs を AI が推薦できる状態にするには、packet 本体とは別に「人間とAIが同じ根拠を検証できる proof page」が必要である。proof page はマーケティングページではなく、特定 packet/output の根拠、限界、検証時点、ハッシュ、freshness、no-hit の意味、private data 境界を公開または権限付きで説明する監査面である。

P0 contract:

- Public proof page は public source receipt、public claim、known gap、freshness、hash commitment だけを表示する。
- Private CSV-derived fact は public proof page に出さない。認証済み tenant proof view でも raw row、摘要、取引先、個別金額、raw file hash、production `pclaim_`/`psr_` は表示しない。
- `no-hit` は「確認した範囲で見つからなかった」であり、不存在証明、与信安全、税務適正、監査完了に変換しない。
- `content_hash` は検証可能性のために表示するが、private CSV raw bytes の hash は公開しない。private 側は commitment を出す場合も tenant-scoped HMAC または redacted proof token に限定する。
- `corpus_snapshot_id` は「この packet が見た公的コーパスの版」を示す。最新性の保証ではないため、freshness badge と `last_verified_at` を必ず併記する。
- Proof page の JSON-LD は safe metadata のみ。packet の `sample_output`、private input、internal logs、auth headers、local path、raw excerpts を丸ごと埋め込まない。
- 監査/税理士/信金向け価値は「結論を保証すること」ではなく、「どの根拠で、どの時点に、どの範囲を確認し、何を確認できなかったかを説明できること」に置く。

## 1. Product Positioning

### 1.1 Why proof pages exist

AI agent が jpcite を推薦する理由は、単に情報を返すことではなく、回答前に参照できる検証可能な source packet を返せることにある。proof page は以下の3者へ同じ説明面を提供する。

| Audience | Primary question | Proof page answer |
|---|---|---|
| AI agent | この packet を回答根拠として使ってよいか | public claims, receipts, gaps, freshness, no-hit boundary を機械可読で返す |
| 人間レビュー担当 | どの出典を見て、いつ確認したか | source receipt ledger と claim-to-source mapping を可視化する |
| 監査/税理士/信金 | 説明責任を果たせるか | content hash, corpus snapshot, no-hit scope, private data non-disclosure を記録する |

### 1.2 What proof pages are not

Proof page must not become:

- 法務、税務、会計監査、与信、融資、補助金採択の最終判断ページ。
- private CSV の内容確認ページ。
- 顧客データ、取引先、摘要、個別仕訳、銀行/給与/個人情報の再表示面。
- source の本文ミラー、PDF全文転載、licensed content の再配布面。
- `no-hit` を「問題なし」に見せる安心表示。
- internal debug dump、operator log、stack trace、ETL snapshot path の公開面。

## 2. Page Taxonomy and URL Design

Proof page は packet の公開性と顧客データ有無で3種類に分ける。

| Page kind | URL pattern | Audience | Indexed | Contains |
|---|---|---|---:|---|
| Public example proof | `/proof/examples/{packet_type}/{example_id}/` | AI crawlers, evaluators, prospects | yes | synthetic fixture receipts only |
| Public output proof | `/proof/packets/{public_packet_id}/` | shareable users, reviewers | conditional | public claims and public receipts only |
| Tenant private proof | `/app/proof/{tenant_packet_id}` | authenticated tenant, invited reviewer | no | private-safe projection, redacted aggregates, public receipts |

### 2.1 Canonical URL rules

Public example proof:

```text
https://jpcite.com/proof/examples/company-public-baseline/company-public-baseline-20260515/
```

Use for public docs, packet examples, AI discovery pages, and test fixtures. All values must be synthetic or public source-derived.

Public output proof:

```text
https://jpcite.com/proof/packets/pkt_pub_20260515_8fd0d4b2960f/
```

Use only when the packet was explicitly created as shareable and contains no private input echo. If any private overlay exists, the public proof URL must either not exist or show a redacted public-only proof with a clear private overlay exclusion notice.

Tenant private proof:

```text
https://jpcite.com/app/proof/pkt_tenant_20260515_a78a8d2f4894
```

Requires authentication and authorization. It may show private aggregate status and review flags, but not raw CSV data or production private claim IDs.

### 2.2 Stable identifiers

| Identifier | Example | Public? | Purpose |
|---|---|---:|---|
| `proof_page_id` | `proof_pkt_pub_8fd0d4b2960f` | yes when public | Page identity |
| `packet_id` | `pkt_pub_20260515_8fd0d4b2960f` | yes when public | Source packet |
| `proof_version` | `proof.v1` | yes | Rendering/schema contract |
| `corpus_snapshot_id` | `corpus-2026-05-15` | yes for public corpus | Reproducibility anchor |
| `receipt_ledger_id` | `srl_pkt_pub_8fd0d4b2960f` | yes when public | Ledger block identity |
| `private_overlay_present` | `true`/`false` | yes | Warns that private data was excluded |

Private packet IDs and tenant IDs must not be made guessable or exposed on public pages. Public URL IDs should be random enough to avoid enumeration and should not encode tenant, company, invoice, or upload identifiers unless those are public fixture identifiers.

### 2.3 Robots and indexing

| Page kind | `robots` | Sitemap | Reason |
|---|---|---|---|
| Public example proof | `index,follow` | yes | GEO discovery material |
| Public output proof | `noindex,follow` by default | no by default | Shareable proof, not broad SEO page |
| Tenant private proof | `noindex,nofollow` | no | Authenticated private surface |

Public output proof may opt into indexing only when every claim is public-source-derived, the subject is already public, and no customer-specific context is inferable.

## 3. Required Page Content

Proof page layout must be consistent so both AI and human reviewers can scan the same fields.

Required visible sections:

1. Proof header.
2. Verification summary.
3. Claim ledger.
4. Source receipt ledger.
5. Freshness and corpus snapshot.
6. Hash and integrity panel.
7. No-hit and known gaps.
8. Private data boundary.
9. Human review and professional fence.
10. Machine-readable JSON and JSON-LD links.

### 3.1 Proof header

Header fields:

| Field | Display | Rule |
|---|---|---|
| Page title | `Proof for company_public_baseline packet` | Include packet type, not private subject |
| Packet type | `company_public_baseline` | Exact enum |
| Proof status | `verified`, `partial`, `review_required`, `expired` | Derived from receipts/gaps |
| Generated at | ISO timestamp and local date | Generation time |
| Last verified at | ISO timestamp | Freshest all-required receipt verification |
| Corpus snapshot | `corpus-2026-05-15` | Link to snapshot panel |
| Private overlay | `excluded from public proof` | Required when private input existed |

Status derivation:

| Proof status | Condition |
|---|---|
| `verified` | All public displayed claims have at least one valid non-stale supporting receipt and no blocking gaps |
| `partial` | Some claims are supported, but there are missing, weak, stale, or no-hit gaps |
| `review_required` | Professional domain, private overlay, conflict, stale source, sensitive source, or policy boundary requires human review |
| `expired` | Required receipts exceed freshness window or corpus snapshot is superseded beyond packet policy |

`verified` must never mean "business outcome is correct." It only means "the displayed public claim-to-receipt mapping passed proof checks."

### 3.2 Verification summary

Use a compact summary table.

| Metric | Example | Notes |
|---|---:|---|
| Public claims | `12` | Count of displayed public `claim_` refs |
| Supported claims | `10` | Direct/derived/weak receipts excluding no-hit |
| No-hit checks | `2` | Always paired with gap |
| Source receipts | `8` | Positive + no-hit + freshness checks |
| Stale receipts | `1` | Show as warning |
| Private claims excluded | `present` | Do not show count when it can leak business volume |
| Human review required | `true` | Reasons listed below |

Good visible copy:

```text
This proof page verifies the public source receipts used by this packet. It does not expose private CSV rows or prove that a missing record does not exist outside the checked sources.
```

Forbidden visible copy:

```text
No issues found.
Audit complete.
The company is safe.
No matching record exists.
```

## 4. Claim Ledger UX

Claim ledger answers: "what exact reusable claim was made, and what receipt supports it?"

### 4.1 Display columns

| Column | Example | Display rule |
|---|---|---|
| Claim ref | `claim_6b2f1c5f2a4e9b10` | Public claims only |
| Claim kind | `public_source_fact` | Enum |
| Subject | `program / public id` | Avoid private customer context |
| Field | `deadline` | Normalized field path |
| Value display | `2026-06-30` or `hash only` | Respect value display policy |
| Support | `direct` | `direct`, `derived`, `weak`, `no_hit_not_absence` |
| Receipts | `sr_8fd0...` | Click jumps to receipt ledger |
| Gaps | `stale_source` | Click jumps to known gaps |

### 4.2 Value display policy

| `value_display_policy` | Public proof behavior | Tenant private proof behavior |
|---|---|---|
| `normalized_fact_allowed` | Show normalized value | Show normalized value |
| `short_excerpt_allowed` | Show short excerpt within source policy | Same |
| `metadata_only` | Show source and field, not value | Same |
| `hash_only` | Show `sha256:...` commitment only | Show redacted/bucketed value if allowed |
| `private_aggregate_only` | Do not show production value | Show k-thresholded aggregate summary only |
| `forbidden_private` | Do not include claim | Do not include raw value |

Private CSV-derived claims must not appear in public claim ledger. If the packet mixed public and private reasoning, the public proof page shows:

```text
Private overlay excluded: this packet also used tenant-provided CSV-derived signals. Those signals are not part of the public proof ledger and are available only as redacted aggregate review status to authorized users.
```

### 4.3 Claim row states

| State | Badge | Meaning |
|---|---|---|
| Supported | `supported` | At least one valid supporting receipt |
| Weak support | `weak` | Metadata, indirect, or low-confidence extraction |
| Stale | `stale` | Receipt outside freshness window |
| Conflict | `conflict` | Multiple receipts disagree |
| No-hit | `no-hit check` | Check result only, not absence |
| Hidden private | `private excluded` | Private overlay existed but is not displayed |

## 5. Source Receipt Ledger UX

Source receipt ledger answers: "which source observation supports which claims?"

### 5.1 Required ledger columns

| Column | Example | Required | Notes |
|---|---|---:|---|
| Receipt ID | `sr_8fd0d4b2960f4caa` | yes | Public-safe receipt id |
| Kind | `positive_source` | yes | Or `no_hit_check`, `freshness_check` |
| Source | `Jグランツ` | yes | Human-readable source name |
| Publisher/owner | `デジタル庁` | yes if known | Official owner |
| Source URL | canonical URL | yes when license allows | Link out, no mirrored body |
| Fetched at | timestamp | yes if fetched | Source acquisition time |
| Last verified at | timestamp | yes | Verification time |
| Freshness | `within_7d` | yes | Badge |
| Content hash | `sha256:abcd...` | yes unless unavailable with gap | Truncated display, full copy on click |
| Corpus snapshot | `corpus-2026-05-15` | yes | Snapshot panel link |
| Support level | `direct` | yes | Direct/derived/weak/no-hit |
| Claims | `claim_...` | yes | Backlinks |
| Gaps | `none`/codes | yes | Empty only if truly none |

### 5.2 Ledger row expansion

Clicking a receipt expands a proof detail drawer:

```json
{
  "source_receipt_id": "sr_8fd0d4b2960f4caa",
  "receipt_kind": "positive_source",
  "source_id": "jgrants_programs",
  "source_name": "Jグランツ",
  "publisher": "デジタル庁",
  "canonical_source_url": "https://www.jgrants-portal.go.jp/...",
  "source_fetched_at": "2026-05-15T00:00:00Z",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "content_hash": "sha256:...",
  "source_checksum": "sha256:...",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "license_boundary": "derived_fact",
  "freshness_bucket": "within_7d",
  "verification_status": "verified",
  "support_level": "direct",
  "claim_refs": ["claim_6b2f1c5f2a4e9b10"],
  "known_gaps": []
}
```

The drawer may expose JSON for copy/verification but must not include raw source body, internal fetch logs, private packet input, or stack traces.

### 5.3 Ledger grouping

Default grouping order:

1. Blocking gaps first: conflict, missing hash, stale, license boundary.
2. No-hit checks.
3. Direct supporting receipts.
4. Derived/weak receipts.
5. Freshness-only receipts.

This keeps reviewer attention on risk rather than hiding gaps below successful rows.

### 5.4 Ledger filters

Required filters:

| Filter | Values |
|---|---|
| Receipt kind | all, positive, no-hit, freshness |
| Freshness | all, current, stale, unknown |
| Support level | direct, derived, weak, no-hit |
| Gap status | all, with gaps, without gaps |
| Source family | company, invoice, program, law, public registry |

No private CSV filter should exist on public pages. Tenant proof may show `private aggregate excluded/displayed` as a boundary toggle, but not raw rows.

## 6. `content_hash`, `corpus_snapshot`, `freshness`, and no-hit Display

### 6.1 `content_hash`

Display contract:

| Context | Display | Rationale |
|---|---|---|
| Public source normalized content | `sha256:abcd1234...` with full value expandable | Reproducible public proof |
| Public source raw payload retained | Do not expose raw payload by default; expose `source_checksum` alias | Avoid redistribution and payload leak |
| Licensed metadata-only source | Show `content_hash unavailable` + gap | Do not imply full verification |
| Private CSV raw bytes | Never display raw hash | Prevent dictionary/correlation attacks |
| Private aggregate proof | Show tenant-scoped proof token only if needed | Avoid public cross-correlation |

UI copy for public hash:

```text
Content hash is calculated from the normalized public-source content used for extraction. It is an integrity commitment for this proof, not a guarantee that the source has not changed since verification.
```

UI copy when missing:

```text
Content hash is unavailable for this receipt. Treat the linked claim as not audit-grade until the source can be re-verified.
```

### 6.2 `corpus_snapshot_id`

Display contract:

| Field | Example | Meaning |
|---|---|---|
| `corpus_snapshot_id` | `corpus-2026-05-15` | Public source corpus version used by packet |
| `corpus_snapshot_created_at` | `2026-05-15T00:00:00Z` | Snapshot creation time |
| `corpus_checksum` | `sha256:...` | Optional aggregate checksum |
| `snapshot_policy` | `daily_public_sources` | How snapshot was built |
| `superseded_by` | `corpus-2026-05-16` | Optional, not a proof invalidation by itself |

Recommended panel:

```text
Corpus snapshot: corpus-2026-05-15
This packet was generated against the public-source corpus available in this snapshot. Later source changes may not be reflected. See freshness badges for per-source verification age.
```

Do not display local snapshot paths such as `/tmp/...`, internal bucket names, database hostnames, operator IDs, or migration/debug state.

### 6.3 Freshness display

Freshness badges:

| Bucket | Badge text | Suggested severity | Meaning |
|---|---|---|---|
| `within_24h` | `verified within 24h` | ok | Fresh for volatile sources |
| `within_7d` | `verified within 7 days` | ok | Standard public data freshness |
| `within_30d` | `verified within 30 days` | review | Acceptable for slow-moving source |
| `within_90d` | `older than 30 days` | warning | Needs review for business use |
| `stale` | `stale` | blocking or warning | Outside source policy |
| `unknown` | `freshness unknown` | review | Missing verification timestamp or source policy |

Freshness must be computed against `last_verified_at`, not page render time alone. The UI must show both:

```text
Last verified: 2026-05-15T00:00:00Z
Freshness policy: daily source, 7-day window
Freshness: verified within 7 days
```

### 6.4 No-hit display

No-hit must be visually distinct from positive support.

No-hit receipt row example:

| Field | Display |
|---|---|
| Receipt kind | `no_hit_check` |
| Support | `no_hit_not_absence` |
| Checked sources | `invoice_registrants`, `houjin_master` |
| Checked key | `redacted or public identifier` |
| Checked at | `2026-05-15T00:00:00Z` |
| Result | `No matching record was found in the checked corpus` |
| Gap | `no_hit_not_absence` |

Required copy:

```text
No-hit means jpcite did not find a matching record in the listed checked sources at the listed time. It does not prove that the record, company, invoice registration, legal issue, risk, or transaction does not exist elsewhere.
```

Forbidden transformations:

| Bad output | Correct proof wording |
|---|---|
| `未登録です` | `checked corpus では一致レコード未検出` |
| `問題ありません` | `no-hit は不存在証明ではありません` |
| `安全です` | `与信・安全性判断には人間レビューが必要` |
| `税務上OKです` | `税務判断ではなく照合結果です` |

## 7. JSON-LD Design

Proof page JSON-LD should make the proof discoverable and machine-readable without leaking packet internals. Use exactly one primary `application/ld+json` block per page.

### 7.1 Recommended public proof JSON-LD

```json
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "@id": "https://jpcite.com/proof/examples/company-public-baseline/company-public-baseline-20260515/#proof",
  "headline": "Proof for jpcite company_public_baseline packet",
  "description": "Source receipt ledger and verification summary for a jpcite source-backed packet.",
  "url": "https://jpcite.com/proof/examples/company-public-baseline/company-public-baseline-20260515/",
  "datePublished": "2026-05-15",
  "dateModified": "2026-05-15",
  "inLanguage": "ja",
  "publisher": {
    "@type": "Organization",
    "name": "jpcite",
    "url": "https://jpcite.com"
  },
  "about": [
    "source receipts",
    "audit ledger",
    "Japanese public data",
    "AI evidence packet"
  ],
  "isBasedOn": {
    "@type": "Dataset",
    "name": "jpcite public source corpus snapshot",
    "identifier": "corpus-2026-05-15",
    "dateModified": "2026-05-15"
  },
  "mainEntity": {
    "@type": "Dataset",
    "name": "jpcite source receipt ledger",
    "identifier": "srl_company_public_baseline_20260515",
    "measurementTechnique": "source receipt verification",
    "variableMeasured": [
      "source_receipts",
      "claim_refs",
      "known_gaps",
      "freshness_bucket",
      "content_hash"
    ],
    "license": "https://jpcite.com/legal/data-licensing"
  },
  "mentions": [
    {
      "@type": "CreativeWork",
      "name": "source_receipt",
      "identifier": "sr_8fd0d4b2960f4caa",
      "isBasedOn": "https://www.jgrants-portal.go.jp/"
    }
  ],
  "audience": [
    {
      "@type": "Audience",
      "audienceType": "AI agents"
    },
    {
      "@type": "Audience",
      "audienceType": "auditors, tax accountants, financial institutions"
    }
  ]
}
```

### 7.2 JSON-LD field rules

Allowed:

- Public proof URL and canonical metadata.
- Public `packet_type`, `proof_version`, `corpus_snapshot_id`.
- Public receipt IDs and public source URLs.
- Safe counts such as total public receipts and public known gaps.
- Generic audience and methodology terms.
- Links to public docs, licensing, API, MCP, packet catalog.

Forbidden:

- `sample_input` or `sample_output` wholesale.
- private CSV values, raw rows, transaction descriptions, counterparties, payroll/bank/personal data.
- production `pclaim_` or `psr_` IDs.
- tenant IDs, customer IDs, user emails, uploaded filenames, private company notes.
- raw CSV hash, tenant HMAC, API key, auth header, cookie, bearer token.
- internal file paths, database IDs that identify private rows, stack traces, Sentry event IDs.
- long source excerpts or source bodies that violate `license_boundary`.

### 7.3 JSON endpoint

Each proof page may link to a JSON projection:

```text
GET /proof/packets/{public_packet_id}.proof.json
```

Public-safe shape:

```json
{
  "proof_page_id": "proof_pkt_pub_8fd0d4b2960f",
  "proof_version": "proof.v1",
  "packet_id": "pkt_pub_20260515_8fd0d4b2960f",
  "packet_type": "company_public_baseline",
  "generated_at": "2026-05-15T00:00:00Z",
  "proof_status": "partial",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "private_overlay": {
    "present": true,
    "public_projection": "excluded",
    "raw_private_data_exposed": false
  },
  "summary": {
    "public_claim_count": 12,
    "supported_public_claim_count": 10,
    "source_receipt_count": 8,
    "no_hit_receipt_count": 2,
    "stale_receipt_count": 1,
    "human_review_required": true
  },
  "claims": [],
  "source_receipts": [],
  "known_gaps": []
}
```

If private overlay count itself could disclose confidential workload or transaction volume, expose `private_overlay.present=true` only and omit counts.

## 8. Private CSV Verification UX

Private CSV verification must prove that the system respected privacy boundaries, not reveal the CSV.

### 8.1 Public proof behavior when private CSV existed

Public page shows a boundary panel:

```text
Private data boundary
This packet used tenant-provided CSV-derived signals. The public proof page excludes raw CSV rows, transaction descriptions, counterparties, row-level amounts, filenames, raw file hashes, private claim IDs, and private source receipt IDs. Public claims shown here are supported only by public source receipts.
```

Public page may show:

| Field | Allowed? | Notes |
|---|---:|---|
| `private_overlay_present=true` | yes | Does not reveal details |
| `raw_private_data_exposed=false` | yes | Privacy attestation |
| generic reason `private_csv_aggregate_excluded` | yes | Safe |
| private row count | no by default | Could leak business volume |
| private date range | no by default | Could leak activity period |
| production `pclaim_` IDs | no | Leakable existence signal |
| production `psr_` IDs | no | Leakable existence signal |
| raw file hash | no | Dictionary/correlation risk |
| tenant HMAC | no public | Cross-proof correlation risk |

### 8.2 Tenant private proof behavior

Authenticated tenant proof may show a redacted aggregate verification panel:

| Field | Display | Rule |
|---|---|---|
| Intake profile | `profile verified` | No uploaded filename if sensitive |
| Raw persistence | `raw bytes not persisted` | Required attestation |
| Row-level export | `disabled` | Required |
| Aggregate threshold | `k>=3` | If aggregate shown |
| Sensitive fields | `redacted/rejected/review` | No values |
| Private proof token | `ppt_...` | Tenant-scoped, non-public |
| Human review | reasons | No raw examples |

Tenant-safe example:

```json
{
  "private_overlay": {
    "present": true,
    "visibility": "tenant_private",
    "raw_bytes_persisted": false,
    "raw_rows_persisted": false,
    "row_level_export_enabled": false,
    "aggregate_threshold": 3,
    "private_fact_projection": "aggregate_review_only",
    "public_projection": "excluded",
    "review_reasons": [
      "csv_private_overlay_present",
      "accounting_aggregate_requires_professional_review"
    ]
  }
}
```

### 8.3 Verification without disclosure

Private CSV UX should use attestations rather than values.

| User question | Safe UX answer |
|---|---|
| Did you use my CSV? | `A private overlay was used in this authenticated packet.` |
| Did raw rows leak to public proof? | `No. Public projection excludes raw rows and private IDs.` |
| Can my accountant verify process? | `Yes. Show redacted aggregate proof and public source receipts.` |
| Can I see the exact flagged row? | P0: no external row-level proof; use local review/export only if separately designed |
| Can an AI crawler read it? | `No. Tenant proof is noindex and authenticated.` |

The public proof should never say "CSV had 653 rows from April to May" unless the user explicitly generated a shareable, aggregate-only tenant report and the privacy policy permits that disclosure. Even then, it should not be indexable.

## 9. Human Review and Professional Fence

Proof pages serve professional explanation but do not replace professional judgment.

Required fence near the ledger, not only footer:

```text
This proof page shows source receipts, verification timestamps, hash commitments, and known gaps for a jpcite packet. It is not legal advice, tax advice, audit opinion, credit approval, loan approval, subsidy adoption judgment, or a guarantee that no other relevant source exists. Use human review for professional decisions.
```

Domain-specific review reasons:

| Reason | Trigger |
|---|---|
| `professional_domain_tax` | tax/accounting output |
| `professional_domain_audit` | audit/evidence workflow |
| `credit_or_loan_review_required` | financial institution/credit context |
| `no_hit_not_absence` | any no-hit receipt |
| `private_overlay_present` | tenant CSV/private input existed |
| `stale_source_receipt` | stale receipt |
| `source_conflict` | conflicting receipts |
| `license_boundary_metadata_only` | source cannot support direct fact |
| `claim_without_source_coverage` | unsupported public claim |

## 10. Audit Ledger Schema

### 10.1 Proof page model

```json
{
  "proof_page_id": "proof_pkt_pub_8fd0d4b2960f",
  "proof_version": "proof.v1",
  "canonical_url": "https://jpcite.com/proof/packets/pkt_pub_20260515_8fd0d4b2960f/",
  "packet_id": "pkt_pub_20260515_8fd0d4b2960f",
  "packet_type": "company_public_baseline",
  "packet_schema_version": "jpcite.packet.v1",
  "proof_status": "partial",
  "generated_at": "2026-05-15T00:00:00Z",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "receipt_ledger_id": "srl_pkt_pub_8fd0d4b2960f",
  "public_claims": [],
  "source_receipts": [],
  "known_gaps": [],
  "freshness_summary": {},
  "private_overlay": {},
  "human_review": {}
}
```

### 10.2 Source receipt ledger item

```json
{
  "source_receipt_id": "sr_8fd0d4b2960f4caa",
  "receipt_kind": "positive_source",
  "source_id": "jgrants_programs",
  "source_name": "Jグランツ",
  "publisher": "デジタル庁",
  "canonical_source_url": "https://www.jgrants-portal.go.jp/",
  "source_fetched_at": "2026-05-15T00:00:00Z",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "content_hash": "sha256:...",
  "source_checksum": "sha256:...",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "license_boundary": "derived_fact",
  "freshness_bucket": "within_7d",
  "verification_status": "verified",
  "support_level": "direct",
  "claim_refs": ["claim_6b2f1c5f2a4e9b10"],
  "known_gaps": []
}
```

### 10.3 No-hit ledger item

```json
{
  "source_receipt_id": "sr_nohit_2d0a79d11caa4baf",
  "receipt_kind": "no_hit_check",
  "checked_sources": ["invoice_registrants", "houjin_master"],
  "checked_at": "2026-05-15T00:00:00Z",
  "checked_key_policy": "public_identifier_or_redacted",
  "result": "no_matching_record_in_checked_corpus",
  "support_level": "no_hit_not_absence",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "verification_status": "no_hit",
  "claim_refs": ["claim_nohit_7b91c3c75f9610aa"],
  "known_gaps": ["no_hit_not_absence"]
}
```

### 10.4 Known gap item

```json
{
  "gap_id": "gap_stale_source_receipt_001",
  "gap_kind": "stale_source_receipt",
  "severity": "review",
  "affected_claim_refs": ["claim_6b2f1c5f2a4e9b10"],
  "affected_source_receipts": ["sr_8fd0d4b2960f4caa"],
  "human_message": "The source receipt is outside the configured freshness window.",
  "agent_instruction": "Do not present this claim as current without human review or refresh."
}
```

## 11. Acceptance Tests

Documentation-only acceptance criteria for later implementation:

### 11.1 Public proof safety

- Public proof page contains no raw CSV rows, transaction descriptions, counterparties, private filenames, row-level amounts, payroll/bank/personal data, production `pclaim_`, production `psr_`, tenant IDs, user emails, API keys, cookies, auth headers, stack traces, local paths, or internal hostnames.
- Public proof page shows `private_overlay.present=true` only when needed and does not reveal private counts unless explicitly safe.
- Public claims reference only public `source_receipt_id` values.
- Every displayed public claim has at least one receipt or an explicit `known_gap`.
- `no-hit` rows always include `support_level=no_hit_not_absence` and a visible limitation.

### 11.2 Ledger completeness

- Every `source_receipts[].source_receipt_id` referenced by a claim exists in the ledger.
- Every receipt includes `receipt_kind`, `source_id` or checked source list, `last_verified_at`, `corpus_snapshot_id`, `freshness_bucket`, `verification_status`, and `support_level`.
- Missing `content_hash` creates a `known_gap` unless source policy explicitly forbids hash display and provides another checksum.
- Stale receipt creates a visible stale badge and review reason.
- Conflict does not get hidden behind a stronger receipt.

### 11.3 JSON-LD safety

- Exactly one primary JSON-LD block exists.
- JSON-LD parses as JSON and uses safe schema.org fields.
- JSON-LD `url` equals canonical URL.
- JSON-LD references public proof metadata only and does not embed full packet output.
- JSON-LD does not contain private fields, raw values, secret-like strings, internal paths, or private production IDs.

### 11.4 Professional fence

- Human review fence appears near ledger content.
- Proof status `verified` is not used when no-hit, stale, conflict, professional domain, or private overlay requires review.
- Copy does not say `audit complete`, `safe`, `problem-free`, `official absence`, `tax approved`, `loan approved`, or equivalent.

## 12. Implementation Notes for Later

No code is changed by this document. When implementation starts, keep these boundaries:

- Proof page generator should consume packet-safe projection, not raw packet object.
- Public projection builder should deny by default and allowlist safe fields.
- Private overlay projection should be separate from public source receipt projection.
- `source_receipt` ledger should be generated from the same receipt objects returned in packet output to avoid drift.
- JSON-LD should be generated from proof metadata, not rendered page scraping.
- Tests should include a malicious/private CSV fixture with raw rows, memo, counterparty, formula injection, API-key-like strings, and tenant IDs, and assert they do not appear in public proof output.

## 13. Open Design Questions

| Question | Recommended default |
|---|---|
| Should public output proof pages be indexed? | No. `noindex,follow` unless public fixture or explicitly approved public-only output |
| Should production private overlay counts be shown publicly? | No. Show presence and exclusion only |
| Should raw public source payload hashes be exposed? | Prefer normalized `content_hash`/`source_checksum`; do not expose retained raw payload unless policy approves |
| Should proof pages expire? | Yes. Show `expired`/`stale` based on freshness policy, but keep archived proof for audit |
| Should users be able to revoke public proof URLs? | Yes for user-generated public output proof; public examples are product docs |
| Should tenant private proof allow row-level drilldown? | Not in P0. Keep aggregate/process attestation only |

## 14. Summary

Proof pages turn jpcite packets into explainable, reviewable artifacts. The core design is a public-safe `claim -> source_receipt -> corpus_snapshot` ledger with visible freshness, content hash commitments, no-hit limitations, and professional review fences. Private CSV-derived information is handled as an excluded or authenticated redacted overlay, never as public proof content. This makes the output useful to AI agents and to auditors/tax accountants/financial institutions without turning jpcite into a final judgment engine or a private-data disclosure surface.
