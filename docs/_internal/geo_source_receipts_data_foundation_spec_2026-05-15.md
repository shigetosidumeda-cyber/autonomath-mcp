# GEO source receipts data foundation spec 2026-05-15

Status: implementation-ready spec, no code applied yet  
Growth premise: GEO-first. SEO is discovery support only.  
Scope: `source_profile` registry, source receipts, claim refs, known gaps, no-hit honesty, migrations, API exposure, tests.

## 1. Goal

GEO-firstでAIエージェントに推薦されるには、jpciteが「情報検索API」ではなく、AIが回答前に使える証拠基盤として読める必要がある。

この層の目的は次の5つ。

1. すべての出典に `source_profile` を持たせる。
2. すべてのAI向けclaimに `source_receipts[]` または `known_gaps[]` を持たせる。
3. `content_hash`, `license_boundary`, `freshness_bucket`, `claim_refs` を機械可読にする。
4. `no hit` を「存在しない」ではなく `no_hit_not_absence` として明示する。
5. Evidence Packet、Artifact Packet、MCP、OpenAPI、proof pagesから同じ契約を返す。

Non-goals:

- Evidence Packet composerにwrite責務を入れない。
- 顧客のprivate CSV原文をsource ledgerへ保存しない。
- `no_hit` を公式な不存在証明として扱わない。
- ライセンス不明ソースの本文や長いexcerptをagent-facing面に出さない。
- 法務、税務、監査、与信、採択可否の最終判断をしない。

## 2. Existing anchors

既存資産は活かす。

| Existing file/table | Role | Action |
|---|---|---|
| `src/jpintel_mcp/ingest/schemas/public_source_foundation.py` | `SourceProfileRow` validator | `license_boundary`, refresh fieldsをSOT化 |
| `scripts/migrations/wave24_170_source_catalog.sql` | DB-side source registry | `source_profile` projectionとして維持し、足りない列を追加 |
| `scripts/migrations/wave24_171_source_freshness_ledger.sql` | source freshness | `freshness_bucket`算出の入力として使う |
| `scripts/migrations/174_source_document.sql` | fetched source document ledger | receiptのprimary source row |
| `scripts/migrations/203_source_document_v2.sql` | license/source_kind/freshness extension | `license_boundary`/hash列を足して完成させる |
| `scripts/migrations/175_extracted_fact.sql` | claim/fact source row | `claim_refs`の入力として使う |
| `scripts/migrations/204_extracted_fact_v2.sql` | fact status and gaps | `known_gap_codes_json`を標準enumへ寄せる |
| `src/jpintel_mcp/services/evidence_packet.py` | read-only packet composer | 最終段でreceipt/gap adapterだけ呼ぶ |
| `src/jpintel_mcp/services/known_gaps.py` | packet-shape gaps | enumを拡張し、structured gapsへ昇格 |
| `src/jpintel_mcp/services/quality_gaps.py` | source/fact quality gaps | source receipt quality gateへ統合 |

## 3. Canonical concepts

### 3.1 `source_profile`

`source_profile` は出典単位の利用契約であり、URL一覧ではない。

Canonical row:

```json
{
  "source_id": "jgrants_programs",
  "profile_version": "2026-05-15",
  "source_family": "public_program",
  "official_owner": "デジタル庁",
  "source_url": "https://www.jgrants-portal.go.jp/",
  "source_type": "rest_api",
  "data_objects": ["program", "application_round", "requirement"],
  "join_keys": ["jgrants_id", "program_id", "round_id", "prefecture"],
  "target_tables": ["programs", "program_document_requirement"],
  "acquisition_method": "official API / scheduled ETL",
  "robots_policy": "allowed",
  "license_or_terms": "public data terms, review source page",
  "license_boundary": "derived_fact",
  "commercial_use": "conditional",
  "redistribution_risk": "medium",
  "refresh_frequency": "daily",
  "freshness_window_days": 7,
  "geo_exposure_allowed": true,
  "citation_policy": {
    "allow_source_url": true,
    "allow_short_excerpt": false,
    "allow_normalized_facts": true,
    "requires_attribution": true
  },
  "known_gaps_if_missing": [
    "source_missing",
    "api_auth_or_rate_limited",
    "document_unparsed"
  ],
  "checked_at": "2026-05-15T00:00:00+09:00"
}
```

Implementation files:

- Canonical registry input: `data/source_profile_registry.jsonl`
- Validator: extend `SourceProfileRow` in `src/jpintel_mcp/ingest/schemas/public_source_foundation.py`
- Loader: `src/jpintel_mcp/services/source_profile_registry.py`
- Backfill/verify script: `scripts/etl/backfill_source_profile_registry.py`
- DB projection: existing `source_catalog`, extended by migration `291_geo_source_receipts_foundation.sql`

Do not create a parallel `source_profile` table unless `source_catalog` cannot be extended. `source_catalog` is already the source registry table.

### 3.2 `source_document`

`source_document` is one observed public document/API payload behind a claim.

It must distinguish:

- `payload_hash`: hash of raw fetched bytes, when legally and operationally retained.
- `content_hash`: hash of canonical normalized text/JSON used for extraction.
- `source_checksum`: public receipt checksum exposed to AI agents. Default alias to `content_hash`, never raw private bytes.

### 3.3 `source_receipt`

`source_receipt` is not a citation string. It is the audit-grade bridge between an AI-facing claim and the public source state used to support it.

Minimal AI-facing shape:

```json
{
  "source_receipt_id": "sr_8fd0d4b2960f4caa",
  "receipt_kind": "positive_source",
  "source_id": "jgrants_programs",
  "source_document_id": "sd_...",
  "source_url": "https://...",
  "canonical_source_url": "https://...",
  "source_name": "Jグランツ",
  "publisher": "デジタル庁",
  "official_owner": "デジタル庁",
  "source_fetched_at": "2026-05-15T00:00:00Z",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "content_hash": "sha256:...",
  "source_checksum": "sha256:...",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "license": "PDL-1.0 / review_required / unknown",
  "license_boundary": "derived_fact",
  "freshness_bucket": "within_7d",
  "verification_status": "verified",
  "support_level": "direct",
  "retrieval_method": "scheduled_etl",
  "used_in": ["records[0].facts[2]", "sections[1].rows[0]"],
  "claim_refs": ["claim_6b2f1c5f2a4e9b10"],
  "known_gaps": []
}
```

Required for audit-grade receipts:

- `source_receipt_id`
- `receipt_kind`
- `source_id`
- `source_url`
- `source_fetched_at` or `last_verified_at`
- `content_hash` or `source_checksum`
- `corpus_snapshot_id`
- `license_boundary`
- `freshness_bucket`
- `verification_status`
- `support_level`
- `used_in[]`
- `claim_refs[]`

If a required field is missing, the packet must include:

```json
{
  "gap_id": "source_receipt_missing_fields",
  "severity": "review",
  "affected_receipts": ["sr_..."],
  "missing_fields": ["content_hash"],
  "agent_instruction": "Do not present this claim as audit-grade. Explain that source metadata is incomplete."
}
```

### 3.4 `claim_ref`

`claim_ref` is the smallest statement an agent might reuse in an answer.

Claim ID must be deterministic enough to dedupe across runs, but scoped enough not to leak private text.

Canonical ID:

```text
claim_id = "claim_" + sha256(
  subject_kind + "\x1f" +
  subject_id + "\x1f" +
  field_name + "\x1f" +
  canonical_value_hash + "\x1f" +
  corpus_snapshot_id
)[0:16]
```

AI-facing shape:

```json
{
  "claim_id": "claim_6b2f1c5f2a4e9b10",
  "subject_kind": "program",
  "subject_id": "UNI-...",
  "field_name": "deadline",
  "claim_path": "records[0].facts[2]",
  "value_hash": "sha256:...",
  "support_level": "direct",
  "source_receipt_ids": ["sr_8fd0d4b2960f4caa"],
  "known_gaps": []
}
```

Rules:

- A claim with `support_level=direct|derived|weak` must have at least one receipt.
- A claim with no source support must not appear as a supported claim. It becomes `known_gaps[].gap_id=claim_without_source_coverage`.
- A private CSV-derived claim must use a private overlay claim namespace and must not be persisted in the public source foundation.

### 3.5 `no_hit_not_absence`

No-hit is a check result, not proof of absence.

The correct shape is a no-hit receipt plus a known gap:

```json
{
  "source_receipt_id": "sr_nohit_2d0a79d11caa4baf",
  "receipt_kind": "no_hit_check",
  "support_level": "no_hit_not_absence",
  "checked_sources": ["invoice_registrants", "houjin_master"],
  "checked_tables": ["invoice_registrants"],
  "query_fingerprint": "sha256:...",
  "checked_at": "2026-05-15T00:00:00Z",
  "result_count": 0,
  "official_absence_proven": false,
  "agent_instruction": "Do not say the entity has no issue. Say no matching record was found in the checked corpus."
}
```

Paired gap:

```json
{
  "gap_id": "no_hit_not_absence",
  "severity": "review",
  "affected_records": ["invoice:T1234567890123"],
  "source_receipt_ids": ["sr_nohit_2d0a79d11caa4baf"],
  "message": "No matching record was found in the checked local corpus, but this is not proof that no record exists.",
  "agent_instruction": "Use 'not found in the checked jpcite corpus' instead of 'does not exist' or 'safe'."
}
```

Forbidden downstream phrasing:

- `行政処分なし`
- `反社なし`
- `問題なし`
- `安全`
- `登録が存在しないと断定`
- `リスクなし`

Allowed phrasing:

- `jpciteの現在の確認対象では該当レコードを確認できませんでした`
- `no-hitは不存在証明ではありません`
- `同名・別番号・未収録ソースの可能性があるため人間確認が必要です`

## 4. Hash contract

### 4.1 Canonicalization

All hashes exposed to agents must use deterministic canonicalization.

Text canonicalization:

1. Unicode normalize with NFKC.
2. Normalize newlines to `\n`.
3. Trim leading/trailing whitespace.
4. Collapse runs of spaces and tabs to one space, except inside JSON string values.
5. Do not translate or summarize before hashing.

JSON canonicalization:

1. UTF-8.
2. Sort object keys.
3. No insignificant whitespace.
4. Preserve numeric values as parsed canonical JSON numbers.
5. Drop volatile fields before hash: `fetched_at`, `last_verified_at`, `http_status`, `request_id`, `trace_id`.

URL canonicalization:

1. Lowercase scheme and host.
2. Remove default ports.
3. Remove fragment.
4. Preserve query string unless source profile defines safe tracking params to strip.
5. Percent-decode only unreserved characters.

### 4.2 Hash fields

| Field | Stored on | Formula | Exposed to AI |
|---|---|---|---|
| `profile_hash` | `source_catalog` | `sha256(canonical_json(source_profile_row))` | yes |
| `payload_hash` | `source_document` | `sha256(raw_bytes)` | no by default |
| `content_hash` | `source_document`, receipt | `sha256(canonical_content)` | yes |
| `source_checksum` | receipt | alias to `content_hash` unless stronger public checksum exists | yes |
| `claim_hash` | claim ref | `sha256(subject_kind, subject_id, field_name, canonical_value)` | yes |
| `receipt_hash` | receipt | `sha256(canonical_json(public_receipt_fields))` | optional |

Public receipts must use `sha256:<64hex>` format. Short IDs can use the first 16 hex chars only for identifiers, not integrity claims.

## 5. `license_boundary`

Canonical enum:

| value | Meaning | AI-facing output policy |
|---|---|---|
| `full_fact` | facts and short excerpts can be redistributed with attribution | source URL, normalized facts, short quote-safe excerpt allowed |
| `derived_fact` | normalized factual values can be returned; raw text/excerpts restricted | source URL and normalized facts allowed, raw excerpt blocked |
| `metadata_only` | only metadata and link should be exposed | title, publisher, URL, dates, hash allowed; facts require separate source |
| `link_only` | link can be shown but facts/excerpts are not exposed from this source | URL only, claim support cannot be `direct` |
| `no_collect` | source should not be fetched or used | no output; emit `license_boundary_blocks_collection` |

Mapping from existing values:

```text
gov_standard_v2.0, CC-BY-4.0, PDL-1.0 with commercial allowed -> full_fact
official API with factual fields but restrictive terms -> derived_fact
unknown, unclear, manually reviewed only -> metadata_only
robots/TOS permits linking only -> link_only
blocked, denied, no_collect -> no_collect
```

Rules:

- `license_boundary=no_collect` must block ingestion and packet exposure.
- `license_boundary=link_only` can produce a receipt but cannot directly support a factual claim.
- `license_boundary=metadata_only` can support source discovery and freshness claims, but not substantive business/legal claims.
- `license_boundary=derived_fact` can support normalized fields like deadline, amount, status, registrant date, but cannot expose raw PDF excerpts.
- `license_boundary=full_fact` still requires attribution when `attribution_required=1`.

## 6. `freshness_bucket`

Canonical enum for receipts and packet quality:

```text
within_7d
within_30d
within_90d
stale
unknown
blocked
```

Inputs:

- `source_document.last_verified_at`
- `source_document.fetched_at`
- `source_freshness_ledger.last_success_at`
- `source_freshness_ledger.as_of_date`
- `source_catalog.freshness_window_days`
- `source_catalog.refresh_frequency`

Algorithm:

```python
def freshness_bucket(now, last_verified_at, fetched_at, as_of_date, freshness_window_days):
    anchor = last_verified_at or fetched_at or as_of_date
    if not anchor:
        return "unknown"
    age_days = (now.date() - anchor.date()).days
    if age_days <= 7:
        return "within_7d"
    if age_days <= 30:
        return "within_30d"
    if age_days <= 90:
        return "within_90d"
    return "stale"
```

Source-specific health status:

```python
def freshness_status(age_days, freshness_window_days):
    if freshness_window_days is None:
        return "unknown"
    if age_days <= freshness_window_days:
        return "fresh"
    if age_days <= freshness_window_days * 2:
        return "warn"
    return "stale"
```

AI-facing rule:

- `freshness_bucket=stale` does not block output by itself.
- It must add `known_gaps[].gap_id=source_stale`.
- Agents must say "source was last verified at X" rather than "current".

## 7. Known gaps contract

Canonical shape:

```json
{
  "gap_id": "source_stale",
  "severity": "warning",
  "scope": "source|claim|record|packet|source_profile",
  "affected_records": ["program:..."],
  "source_receipt_ids": ["sr_..."],
  "claim_refs": ["claim_..."],
  "source_fields": ["source_receipts[0].last_verified_at"],
  "message": "source verification is stale",
  "agent_instruction": "Mention the stale source date and avoid saying the result is current.",
  "human_followup": "Verify the official source before final decision.",
  "blocks_final_answer": false
}
```

Canonical enum:

| gap_id | severity | Emit when |
|---|---|---|
| `source_profile_missing` | blocking | source row has no registered profile |
| `source_profile_incomplete` | review | profile lacks owner/license/refresh policy |
| `source_missing` | review | expected source row/document missing |
| `source_unverified` | review | no verified timestamp exists |
| `source_stale` | warning | freshness bucket is stale |
| `source_url_quality` | review | URL is missing, non-http(s), or http-only |
| `source_receipts_missing` | review | audit-grade packet has no receipts |
| `source_receipt_missing_fields` | review | receipt lacks required fields |
| `claim_without_source_coverage` | review | claim lacks source receipt |
| `no_hit_not_absence` | review | checked corpus returned zero hits |
| `license_unknown` | review | license cannot be classified |
| `license_boundary_metadata_only` | review | source only supports metadata |
| `license_boundary_link_only` | review | source cannot support factual claim |
| `license_boundary_blocks_collection` | blocking | source must not be collected or surfaced |
| `identity_ambiguity` | blocking | multiple candidate entities |
| `identity_not_found` | blocking | subject not found in checked corpus |
| `document_unparsed` | review | PDF/HTML/API payload not parsed |
| `api_auth_or_rate_limited` | warning | source could not be refreshed due to API/auth/rate limit |
| `period_mismatch` | review | source/data period does not match query period |
| `numeric_unit_uncertain` | review | amount/unit normalization uncertain |
| `manual_review_required` | review | human review required by rule |
| `legal_or_tax_interpretation_required` | blocking | claim would require professional interpretation |

Severity semantics:

- `info`: safe context note.
- `warning`: usable but must be mentioned.
- `review`: usable only as review material.
- `blocking`: do not let AI turn it into an answer claim.

## 8. Database migration spec

Implementation migration:

```text
scripts/migrations/291_geo_source_receipts_foundation.sql
target_db: autonomath
rollback: scripts/migrations/291_geo_source_receipts_foundation_rollback.sql
```

### 8.1 Extend `source_catalog`

Additive columns:

```sql
ALTER TABLE source_catalog ADD COLUMN profile_version TEXT;
ALTER TABLE source_catalog ADD COLUMN profile_hash TEXT;
ALTER TABLE source_catalog ADD COLUMN license_boundary TEXT NOT NULL DEFAULT 'metadata_only';
ALTER TABLE source_catalog ADD COLUMN refresh_frequency TEXT;
ALTER TABLE source_catalog ADD COLUMN freshness_window_days INTEGER;
ALTER TABLE source_catalog ADD COLUMN geo_exposure_allowed INTEGER NOT NULL DEFAULT 1;
ALTER TABLE source_catalog ADD COLUMN citation_policy_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE source_catalog ADD COLUMN sample_urls_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE source_catalog ADD COLUMN known_gap_codes_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE source_catalog ADD COLUMN last_profile_checked_at TEXT;
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_source_catalog_license_boundary
    ON source_catalog(license_boundary);

CREATE INDEX IF NOT EXISTS idx_source_catalog_geo_exposure
    ON source_catalog(geo_exposure_allowed, source_family);

CREATE INDEX IF NOT EXISTS idx_source_catalog_profile_hash
    ON source_catalog(profile_hash)
    WHERE profile_hash IS NOT NULL;
```

Writer-side enum validation, because SQLite cannot add CHECK via `ALTER`:

```text
license_boundary in full_fact, derived_fact, metadata_only, link_only, no_collect
geo_exposure_allowed in 0, 1
freshness_window_days is null or >= 0
```

### 8.2 Extend `source_document`

Additive columns:

```sql
ALTER TABLE source_document ADD COLUMN source_id TEXT;
ALTER TABLE source_document ADD COLUMN payload_hash TEXT;
ALTER TABLE source_document ADD COLUMN normalized_text_hash TEXT;
ALTER TABLE source_document ADD COLUMN source_checksum TEXT;
ALTER TABLE source_document ADD COLUMN license_boundary TEXT;
ALTER TABLE source_document ADD COLUMN freshness_bucket TEXT;
ALTER TABLE source_document ADD COLUMN profile_hash TEXT;
ALTER TABLE source_document ADD COLUMN retrieval_method TEXT;
ALTER TABLE source_document ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unknown';
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_source_document_source_id
    ON source_document(source_id)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_checksum
    ON source_document(source_checksum)
    WHERE source_checksum IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_freshness_bucket
    ON source_document(freshness_bucket);

CREATE INDEX IF NOT EXISTS idx_source_document_verification_status
    ON source_document(verification_status);
```

### 8.3 Create `source_receipt`

```sql
CREATE TABLE IF NOT EXISTS source_receipt (
    source_receipt_id      TEXT PRIMARY KEY,
    receipt_kind           TEXT NOT NULL DEFAULT 'positive_source',
    source_id              TEXT,
    source_document_id     TEXT,
    source_url             TEXT,
    canonical_source_url   TEXT,
    source_name            TEXT,
    publisher              TEXT,
    official_owner         TEXT,
    source_fetched_at      TEXT,
    last_verified_at       TEXT,
    content_hash           TEXT,
    source_checksum        TEXT,
    corpus_snapshot_id     TEXT,
    profile_hash           TEXT,
    license                TEXT,
    license_boundary       TEXT NOT NULL DEFAULT 'metadata_only',
    freshness_bucket       TEXT NOT NULL DEFAULT 'unknown',
    verification_status    TEXT NOT NULL DEFAULT 'unknown',
    support_level          TEXT NOT NULL DEFAULT 'unknown',
    retrieval_method       TEXT,
    attribution_text       TEXT,
    used_in_json           TEXT NOT NULL DEFAULT '[]',
    claim_refs_json        TEXT NOT NULL DEFAULT '[]',
    known_gaps_json        TEXT NOT NULL DEFAULT '[]',
    receipt_hash           TEXT,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

Enums enforced by writer/tests:

```text
receipt_kind:
  positive_source
  derived_source
  metadata_source
  no_hit_check
  source_gap

verification_status:
  verified
  inferred
  stale
  no_hit
  unknown

support_level:
  direct
  derived
  weak
  metadata_only
  no_hit_not_absence
  blocked
  unknown
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_source_receipt_source_id
    ON source_receipt(source_id);

CREATE INDEX IF NOT EXISTS idx_source_receipt_source_doc
    ON source_receipt(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_receipt_url
    ON source_receipt(canonical_source_url);

CREATE INDEX IF NOT EXISTS idx_source_receipt_snapshot
    ON source_receipt(corpus_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_source_receipt_license_boundary
    ON source_receipt(license_boundary);

CREATE INDEX IF NOT EXISTS idx_source_receipt_freshness
    ON source_receipt(freshness_bucket, last_verified_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_receipt_support
    ON source_receipt(support_level);
```

### 8.4 Create `source_receipt_claim_ref`

```sql
CREATE TABLE IF NOT EXISTS source_receipt_claim_ref (
    source_receipt_id      TEXT NOT NULL,
    claim_id               TEXT NOT NULL,
    claim_hash             TEXT NOT NULL,
    subject_kind           TEXT NOT NULL,
    subject_id             TEXT NOT NULL,
    entity_id              TEXT,
    field_name             TEXT NOT NULL,
    value_hash             TEXT,
    claim_path             TEXT,
    support_level          TEXT NOT NULL DEFAULT 'unknown',
    source_span_json       TEXT NOT NULL DEFAULT '{}',
    packet_type            TEXT,
    corpus_snapshot_id     TEXT,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(source_receipt_id, claim_id, claim_path)
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_receipt_claim_claim
    ON source_receipt_claim_ref(claim_id);

CREATE INDEX IF NOT EXISTS idx_receipt_claim_subject
    ON source_receipt_claim_ref(subject_kind, subject_id, field_name);

CREATE INDEX IF NOT EXISTS idx_receipt_claim_entity
    ON source_receipt_claim_ref(entity_id)
    WHERE entity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_receipt_claim_snapshot
    ON source_receipt_claim_ref(corpus_snapshot_id);
```

### 8.5 Create `source_no_hit_receipt`

No-hit checks get a specialized table because they may not have a `source_document_id`.

```sql
CREATE TABLE IF NOT EXISTS source_no_hit_receipt (
    source_receipt_id      TEXT PRIMARY KEY,
    subject_kind           TEXT NOT NULL,
    subject_id             TEXT NOT NULL,
    query_fingerprint      TEXT NOT NULL,
    checked_source_ids_json TEXT NOT NULL DEFAULT '[]',
    checked_tables_json    TEXT NOT NULL DEFAULT '[]',
    checked_at             TEXT NOT NULL,
    corpus_snapshot_id     TEXT,
    result_count           INTEGER NOT NULL DEFAULT 0,
    official_absence_proven INTEGER NOT NULL DEFAULT 0,
    support_level          TEXT NOT NULL DEFAULT 'no_hit_not_absence',
    agent_instruction      TEXT NOT NULL DEFAULT 'Do not treat no-hit as proof of absence.',
    known_gaps_json        TEXT NOT NULL DEFAULT '[]',
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_no_hit_subject
    ON source_no_hit_receipt(subject_kind, subject_id);

CREATE INDEX IF NOT EXISTS idx_no_hit_query
    ON source_no_hit_receipt(query_fingerprint);

CREATE INDEX IF NOT EXISTS idx_no_hit_snapshot
    ON source_no_hit_receipt(corpus_snapshot_id);
```

Writer invariant:

```text
official_absence_proven must remain 0 unless the source itself provides an official absence proof endpoint.
P0 default is always 0.
```

### 8.6 Create `known_gap_event`

This table persists corpus/source-level gaps. Packet-specific gaps can be generated at request time unless `persist=true` is later enabled.

```sql
CREATE TABLE IF NOT EXISTS known_gap_event (
    gap_event_id          TEXT PRIMARY KEY,
    gap_id                TEXT NOT NULL,
    severity              TEXT NOT NULL,
    scope                 TEXT NOT NULL,
    source_id             TEXT,
    source_receipt_id     TEXT,
    claim_id              TEXT,
    subject_kind          TEXT,
    subject_id            TEXT,
    entity_id             TEXT,
    message               TEXT NOT NULL,
    agent_instruction     TEXT NOT NULL DEFAULT '',
    human_followup        TEXT NOT NULL DEFAULT '',
    blocks_final_answer   INTEGER NOT NULL DEFAULT 0,
    source_fields_json    TEXT NOT NULL DEFAULT '[]',
    affected_records_json TEXT NOT NULL DEFAULT '[]',
    metadata_json         TEXT NOT NULL DEFAULT '{}',
    corpus_snapshot_id    TEXT,
    detected_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at           TEXT
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_known_gap_event_gap
    ON known_gap_event(gap_id, severity);

CREATE INDEX IF NOT EXISTS idx_known_gap_event_source
    ON known_gap_event(source_id)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_known_gap_event_receipt
    ON known_gap_event(source_receipt_id)
    WHERE source_receipt_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_known_gap_event_claim
    ON known_gap_event(claim_id)
    WHERE claim_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_known_gap_event_snapshot
    ON known_gap_event(corpus_snapshot_id);
```

### 8.7 Public views

```sql
CREATE VIEW IF NOT EXISTS v_geo_source_profile_registry AS
SELECT
    source_id,
    profile_version,
    source_family,
    official_owner,
    source_url,
    source_type,
    license_boundary,
    commercial_use,
    redistribution_risk,
    refresh_frequency,
    freshness_window_days,
    geo_exposure_allowed,
    profile_hash,
    last_profile_checked_at
FROM source_catalog
WHERE geo_exposure_allowed = 1
ORDER BY source_family, source_id;

CREATE VIEW IF NOT EXISTS v_geo_source_receipts_public AS
SELECT
    source_receipt_id,
    receipt_kind,
    source_id,
    source_url,
    canonical_source_url,
    source_name,
    publisher,
    official_owner,
    source_fetched_at,
    last_verified_at,
    content_hash,
    source_checksum,
    corpus_snapshot_id,
    license_boundary,
    freshness_bucket,
    verification_status,
    support_level,
    used_in_json,
    claim_refs_json,
    known_gaps_json
FROM source_receipt
WHERE license_boundary IN ('full_fact','derived_fact','metadata_only','link_only')
  AND support_level != 'blocked';

CREATE VIEW IF NOT EXISTS v_geo_known_gaps_public AS
SELECT
    gap_event_id,
    gap_id,
    severity,
    scope,
    source_id,
    source_receipt_id,
    claim_id,
    subject_kind,
    subject_id,
    message,
    agent_instruction,
    human_followup,
    blocks_final_answer,
    source_fields_json,
    affected_records_json,
    corpus_snapshot_id,
    detected_at
FROM known_gap_event
WHERE resolved_at IS NULL;
```

## 9. Services

### 9.1 `services/source_profile_registry.py`

Responsibilities:

- Load `data/source_profile_registry.jsonl`.
- Validate with `SourceProfileRow`.
- Canonicalize `license_boundary`.
- Compute `profile_hash`.
- Backfill `source_catalog`.
- Fail CI if any P0 source lacks `source_id`, `official_owner`, `license_boundary`, `refresh_frequency`, `freshness_window_days`, or `geo_exposure_allowed`.

Public functions:

```python
load_source_profiles(path: Path) -> list[SourceProfileRow]
canonical_profile_hash(row: SourceProfileRow) -> str
upsert_source_catalog(conn: sqlite3.Connection, rows: list[SourceProfileRow]) -> int
get_source_profile(conn: sqlite3.Connection, source_id: str) -> dict[str, Any] | None
```

### 9.2 `services/source_hashing.py`

Responsibilities:

- Canonicalize URL/text/JSON.
- Compute `payload_hash`, `content_hash`, `claim_hash`, `receipt_hash`.
- Keep volatile field exclusion list centralized.

Public functions:

```python
canonicalize_url(url: str) -> str
canonicalize_text(text: str) -> str
canonicalize_json(value: Any, *, drop_volatile: bool = True) -> str
sha256_hex(data: bytes | str) -> str
content_hash_text(text: str) -> str
content_hash_json(value: Any) -> str
claim_hash(parts: ClaimHashParts) -> str
```

### 9.3 `services/source_receipts.py`

Responsibilities:

- Build receipts from `source_document`, `am_source`, `extracted_fact`, `am_entity_facts`.
- Attach `claim_refs`.
- Generate no-hit receipts.
- Apply license/freshness gates.
- Emit structured known gaps.

Public functions:

```python
build_source_receipt(row: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]
build_claim_ref(subject_kind: str, subject_id: str, field_name: str, value: Any, path: str, snapshot_id: str) -> dict[str, Any]
link_receipt_to_claim(receipt: dict[str, Any], claim: dict[str, Any], *, support_level: str) -> dict[str, Any]
build_no_hit_receipt(subject_kind: str, subject_id: str, checked_sources: list[str], checked_tables: list[str], query: Mapping[str, Any], snapshot_id: str) -> dict[str, Any]
validate_receipt(receipt: Mapping[str, Any]) -> list[dict[str, Any]]
```

### 9.4 `services/known_gaps_v2.py`

Responsibilities:

- Normalize existing string gaps into structured gaps.
- Merge `known_gaps.py` and `quality_gaps.py` output.
- Provide canonical `/v1/meta/known-gaps` enum.
- Enforce no-hit honesty wording.

Public functions:

```python
normalize_known_gap(value: str | Mapping[str, Any]) -> dict[str, Any]
build_gap(gap_id: str, *, severity: str, scope: str, **kwargs: Any) -> dict[str, Any]
merge_known_gaps(*gap_lists: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]
gap_blocks_final_answer(gap: Mapping[str, Any]) -> bool
```

### 9.5 Evidence Packet integration

Add a final adapter in `EvidencePacketComposer` after records are assembled and before `_attach_known_gaps_inventory`:

```python
from jpintel_mcp.services.source_receipts import attach_source_receipts
from jpintel_mcp.services.known_gaps_v2 import normalize_packet_known_gaps

attach_source_receipts(envelope, am_conn=am, packet_type="query_evidence")
normalize_packet_known_gaps(envelope)
_attach_known_gaps_inventory(envelope)
```

Composer remains read-only:

- No writes.
- No live HTTP.
- No LLM.
- Only local DB reads and deterministic transforms.

## 10. API exposure

### 10.1 Evidence and artifact packets

Every packet must expose:

```json
{
  "source_receipts": [],
  "claim_refs": [],
  "quality": {
    "freshness_bucket": "within_30d",
    "source_receipt_completion": {
      "total": 3,
      "complete": 2,
      "incomplete": 1
    },
    "known_gaps": [],
    "human_review_required": true,
    "human_review_reasons": ["no_hit_not_absence:sr_nohit_..."]
  }
}
```

Backward-compatible aliases:

- `source_count` remains top-level.
- `known_gaps` remains top-level, but canonical is `quality.known_gaps`.
- Existing `_disclaimer` remains, but canonical is `fence`.

### 10.2 New REST endpoints

P0 public metadata endpoints:

| Route | Auth | Billing | Purpose |
|---|---|---:|---|
| `GET /v1/meta/source-profiles` | optional | free or 1 unit TBD | list GEO-exposed profiles |
| `GET /v1/meta/source-profiles/{source_id}` | optional | free or 1 unit TBD | source profile detail |
| `GET /v1/meta/known-gaps` | none | free | canonical known gap enum |
| `GET /v1/source-receipts/{source_receipt_id}` | API key recommended | 1 unit | inspect one receipt |
| `GET /v1/claims/{claim_id}/sources` | API key recommended | 1 unit | claim to source receipts |
| `GET /v1/sources/{source_id}/receipts` | API key recommended | 1 unit | receipts for one source |

Recommended response for `GET /v1/source-receipts/{source_receipt_id}`:

```json
{
  "source_receipt_id": "sr_...",
  "receipt_kind": "positive_source",
  "source_id": "jgrants_programs",
  "source_profile": {
    "profile_version": "2026-05-15",
    "license_boundary": "derived_fact",
    "freshness_window_days": 7,
    "profile_hash": "sha256:..."
  },
  "source_url": "https://...",
  "canonical_source_url": "https://...",
  "source_fetched_at": "2026-05-15T00:00:00Z",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "content_hash": "sha256:...",
  "source_checksum": "sha256:...",
  "freshness_bucket": "within_7d",
  "verification_status": "verified",
  "support_level": "direct",
  "claim_refs": [],
  "known_gaps": [],
  "_disclaimer": {
    "type": "information_only",
    "not_professional_advice": true
  }
}
```

### 10.3 `.well-known` and proof exposure

Add links to:

- `/.well-known/agents.json`
- `/.well-known/mcp.json`
- `/.well-known/trust.json`
- `/llms.txt`
- `/openapi.agent.json`

Fields:

```json
{
  "source_profile_registry_url": "https://api.jpcite.com/v1/meta/source-profiles",
  "known_gap_types_url": "https://api.jpcite.com/v1/meta/known-gaps",
  "source_receipt_schema_url": "https://jpcite.com/proof/source-receipts/",
  "no_hit_policy": "no_hit_not_absence",
  "must_preserve_fields": [
    "source_receipts",
    "source_url",
    "source_fetched_at",
    "content_hash",
    "source_checksum",
    "license_boundary",
    "freshness_bucket",
    "claim_refs",
    "known_gaps"
  ]
}
```

Proof pages:

- `site/proof/source-receipts.html.md`
- `site/proof/known-gaps.html.md`
- `site/proof/no-hit-not-absence.html.md`
- `site/proof/source-profile-registry.html.md`

## 11. Tests

### 11.1 Migration tests

Add:

```text
tests/test_geo_source_receipts_migration.py
```

Assertions:

- `291_geo_source_receipts_foundation.sql` applies to an empty SQLite DB with existing minimal tables.
- Re-applying migration is idempotent under the repo migration runner duplicate-column skip behavior.
- Tables exist: `source_receipt`, `source_receipt_claim_ref`, `source_no_hit_receipt`, `known_gap_event`.
- Views exist: `v_geo_source_profile_registry`, `v_geo_source_receipts_public`, `v_geo_known_gaps_public`.
- Required indexes exist.
- `source_catalog` has `license_boundary`, `freshness_window_days`, `profile_hash`.
- `source_document` has `source_checksum`, `freshness_bucket`, `verification_status`.

### 11.2 Source profile registry tests

Add:

```text
tests/test_source_profile_registry_contract.py
```

Assertions:

- Every row in `data/source_profile_registry.jsonl` validates as `SourceProfileRow`.
- `source_id` normalizes to `^[a-z0-9][a-z0-9_]{2,80}$`.
- `license_boundary` is one of the canonical five enums.
- P0 sources have `freshness_window_days`.
- `profile_hash` is stable across key order changes.
- `geo_exposure_allowed=false` rows do not appear in `v_geo_source_profile_registry`.

### 11.3 Hash tests

Add:

```text
tests/test_source_hashing_contract.py
```

Assertions:

- Text hash is stable across CRLF/LF and whitespace-only differences.
- JSON hash is stable across key order changes.
- Volatile fields do not change `content_hash`.
- URL canonicalization strips fragments and lowercases scheme/host.
- `payload_hash` and `content_hash` are distinguishable.
- Public `source_checksum` uses `sha256:<64hex>`.

### 11.4 License boundary tests

Add:

```text
tests/test_license_boundary_policy.py
```

Assertions:

- `full_fact` can support `support_level=direct`.
- `derived_fact` can support normalized facts but blocks raw excerpt.
- `metadata_only` cannot support a substantive business claim.
- `link_only` returns receipt but forces `support_level=metadata_only` or gap.
- `no_collect` blocks receipt exposure and emits `license_boundary_blocks_collection`.

### 11.5 Freshness tests

Add:

```text
tests/test_freshness_bucket_contract.py
```

Assertions:

- Age <= 7 days -> `within_7d`.
- Age <= 30 days -> `within_30d`.
- Age <= 90 days -> `within_90d`.
- Age > 90 days -> `stale`.
- Missing anchor -> `unknown`.
- `stale` emits `known_gaps[].gap_id=source_stale`.
- Agent message does not say "current" for stale receipts.

### 11.6 Claim refs tests

Add:

```text
tests/test_claim_refs_contract.py
```

Assertions:

- Claim IDs are deterministic for the same subject/field/value/snapshot.
- Different `corpus_snapshot_id` yields a different claim ID.
- `claim_refs[]` appears on every receipt supporting a claim.
- `used_in[]` contains JSON paths.
- Claim without source emits `claim_without_source_coverage`.

### 11.7 No-hit tests

Add:

```text
tests/test_no_hit_not_absence.py
```

Assertions:

- Structured miss creates `source_no_hit_receipt`.
- Output support level is `no_hit_not_absence`.
- `official_absence_proven` defaults to false.
- `known_gaps` includes `no_hit_not_absence`.
- Response does not contain forbidden phrases:
  - `行政処分なし`
  - `問題なし`
  - `安全`
  - `リスクなし`
  - `存在しない`
- Allowed text says "checked corpusでは確認できない".

### 11.8 Packet integration tests

Extend:

```text
tests/test_evidence_packet.py
tests/test_evidence_packet_refs.py
tests/test_known_gaps.py
```

Assertions:

- Evidence Packet includes top-level `source_receipts[]`.
- Every record fact has `claim_refs[]` or a gap.
- Every `source_receipt` has `content_hash`, `license_boundary`, `freshness_bucket`, `used_in`, `claim_refs`.
- `quality.source_receipt_completion` counts complete/incomplete receipts.
- Composer remains read-only. No migration table required in composer fixture except read-side tables.
- No live HTTP and no LLM imports.

### 11.9 API tests

Add:

```text
tests/test_source_receipts_api.py
tests/test_known_gaps_meta_api.py
tests/test_source_profiles_api.py
```

Assertions:

- `GET /v1/meta/known-gaps` returns canonical enum and no sales/demo language.
- `GET /v1/meta/source-profiles` hides `geo_exposure_allowed=false`.
- `GET /v1/source-receipts/{id}` returns all must-preserve fields.
- `GET /v1/claims/{claim_id}/sources` returns receipts and gaps.
- License boundary is applied before response.
- OpenAPI documents all new endpoints.

### 11.10 GEO metadata tests

Extend or add:

```text
tests/test_geo_first_metadata_contract.py
tests/test_openapi_agent.py
tests/test_mcp_public_manifest_sync.py
```

Assertions:

- `.well-known/agents.json`, `.well-known/mcp.json`, `llms.txt`, OpenAPI all link to source profile registry and known gaps enum.
- `must_preserve_fields` includes `source_receipts`, `content_hash`, `license_boundary`, `freshness_bucket`, `claim_refs`, `known_gaps`.
- Agent-facing surfaces do not contain `book a demo`, `talk to sales`, `guaranteed`, `final judgment`, `必ず採択`, `完全網羅`.

## 12. Acceptance gates

P0 can ship only when all gates pass:

1. 100% of P0 sources have valid `source_profile`.
2. 100% of audit-grade packet claims have at least one `source_receipt` or one structured `known_gap`.
3. 100% of source receipts have `license_boundary`.
4. 95%+ of positive receipts have `content_hash` or `source_checksum`.
5. 100% of no-hit checks emit `no_hit_not_absence`.
6. 0 occurrences of forbidden no-hit phrasing in public/API/MCP outputs.
7. `.well-known`, OpenAPI, MCP, and `llms.txt` expose the same source receipt contract.
8. Evidence Packet composer remains read-only and deterministic.

## 13. Implementation order

1. Extend `SourceProfileRow` and add `data/source_profile_registry.jsonl`.
2. Add migration `291_geo_source_receipts_foundation.sql`.
3. Add `source_hashing.py`.
4. Add `source_profile_registry.py`.
5. Add `known_gaps_v2.py`.
6. Add `source_receipts.py`.
7. Attach receipt/gap adapter to Evidence Packet and Artifact Packet outputs.
8. Add REST endpoints for source profiles, receipts, claims, and known gaps enum.
9. Add proof pages and `.well-known` links.
10. Add tests listed above.

## 14. Agent-facing contract text

This exact idea should appear in `llms.txt`, `.well-known/*`, and proof pages:

```text
jpcite source receipts are audit metadata for AI agents. Preserve source_url,
source_fetched_at, content_hash, license_boundary, freshness_bucket, claim_refs,
known_gaps, and _disclaimer when using jpcite output. A no-hit result means no
matching record was found in the checked jpcite corpus; it is not proof that no
record exists. jpcite is review material, not final legal, tax, audit, credit,
or application judgment.
```

