# AWS final 12 review 06/12: security, privacy, terms, Playwright, CSV

Date: 2026-05-15  
Role: final additional review 6/12, security/privacy/terms/Playwright/CSV  
AWS execution: none. No AWS CLI/API command, AWS resource creation, collection job, or deployment was performed.  
Output constraint: this file only.

## 0. Verdict

判定は **条件付きPASS**。

現行の最終SOTは、次の中核方針では整合している。

- real user CSVはAWS credit runに入れない。
- AWSで扱うCSV系は `synthetic_csv_fixture`、`header_only_synthetic_fixture`、`redacted_reviewed_fixture`、`public_official_source_csv` に限定する。
- public official CSVとprivate accounting CSVを別data classとして扱う。
- CSV-derived factはpublic source factではなくprivate overlay factとして扱う。
- Playwrightは公開ページのrendered observationであり、access bypassではない。
- CAPTCHA、login、403/429反復、robots/terms禁止、stealth/proxy回避はblockまたはmanual review。
- screenshotは各辺 `<= 1600px`。
- HARはmetadata-onlyで、body/cookie/auth/token/storageを保存しない。
- OCRは補助であり、重要fieldをOCR単独で断定しない。
- public proof/API/MCP/JSON-LD/llmsにraw CSV、raw screenshot、raw DOM、raw HAR、raw OCR全文を出さない。
- no-hitは常に `no_hit_not_absence`。

ただし、実装直前に潰すべき矛盾候補が残る。特に危険なのは、名前だけ見ると実CSVをAWSへ入れられそうに見える `private-overlay` 表現、raw public artifactsを外部exportする際の扱い、Playwright/HAR/OCRのデフォルト実装、public proof生成時の漏えいである。

この文書の追加gateを本体計画へマージすれば、security/privacy/terms面ではこれ以上大きくスマートにできる余地は少ない。次の改善は、実装でvalidatorとして強制する段階。

## 1. Files reviewed

重点確認した既存SOT:

- `docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- `docs/_internal/aws_final_consistency_07_csv_privacy_security.md`
- `docs/_internal/aws_final_consistency_08_playwright_terms.md`
- `docs/_internal/aws_credit_review_12_csv_privacy_pipeline.md`
- `docs/_internal/aws_credit_review_11_source_terms_robots.md`
- `docs/_internal/aws_scope_expansion_06_playwright_capture.md`

## 2. Final immutable decisions

### 2.1 CSV boundary

AWS credit runで許可:

- `synthetic_csv_fixture`
- `header_only_synthetic_fixture`
- `redacted_reviewed_fixture`
- `public_official_source_csv`
- provider alias maps
- leak scan corpus
- formula injection test corpus
- synthetic aggregate facts

AWS credit runで禁止:

- real user CSV bytes
- row-level private records
- normalized rows from real users
- real memo/counterparty/tag/voucher/invoice/bank/payroll/person values
- real private aggregates
- real private profile hashes
- real suppression patterns
- real user CSV-derived screenshots/logs/debug artifacts

重要な区別:

- NTA、e-Stat、J-Grants、法人番号、インボイス等の公的CSVは `public_official_source_csv`。
- freee、Money Forward、弥生などユーザー投入会計CSVは `private_accounting_csv_*`。
- 拡張子 `.csv` では判定しない。必ず `data_class`、`source_profile_id`、`private_user_data_present` で判定する。

### 2.2 Playwright boundary

Playwrightは次だけに使う。

- 公開ページのレンダリング確認
- 公開ページの可視状態の証跡化
- JavaScript表示表や自治体ページ等のDOM/visible text取得
- screenshot receipt生成
- OCR入力tile生成
- no-hit画面やerror状態の時点証跡。ただしclaim support不可の場合あり

Playwrightでやってはいけないこと:

- CAPTCHA解決
- login利用
- cookie/session再利用
- proxy rotation
- residential proxy
- stealth plugin
- hidden API reverse engineering
- rate limit回避
- robots/terms禁止path capture
- 403/429反復突破
- private user screen capture

### 2.3 Public proof boundary

public proof/API/MCP/JSON-LD/llmsに出せるもの:

- source URL
- publisher
- retrieved_at
- document date
- content hash
- capture method
- source receipt id
- claim refs
- known gaps
- attribution notice
- 短い引用または派生fact。ただしterms/license gate通過時のみ

原則出さないもの:

- raw screenshot
- raw DOM
- raw OCR text full dump
- raw HAR
- raw PDF/HTML/CSV mirror
- real CSV-derived data
- public proofの根拠URL欄にprivate CSV receipt

## 3. Contradiction review

### C06-01. `private-overlay bucket` wording can still mislead implementers

Severity: critical  
Status: fix required before AWS run

問題:

複数文書で最終的には `csv-fixture-lab` へ置換する方針があるが、実装者が古い `private-overlay bucket` 表現を拾うと、real user CSV由来aggregateをAWSへ置けると誤読しうる。

採用gate:

```json
{
  "gate_id": "csv_aws_boundary_gate",
  "required": true,
  "block_if_any": [
    "aws_prefix_name_contains_private_overlay",
    "real_user_csv_data_class_in_aws_manifest",
    "private_accounting_csv_raw_in_aws_manifest",
    "private_csv_aggregate_fact_from_real_user_in_aws_manifest",
    "private_csv_profile_hash_from_real_user_in_aws_manifest"
  ],
  "allowed_csv_data_classes": [
    "synthetic_csv_fixture",
    "header_only_synthetic_fixture",
    "redacted_reviewed_fixture",
    "public_official_source_csv"
  ]
}
```

命名正本:

- AWS credit run: `csv-fixture-lab`
- runtime private feature: `private_overlay`
- 両者を同じbucket/prefix/module名にしない。

### C06-02. Public official CSV and private accounting CSV can be mixed by file extension

Severity: critical  
Status: fix required

問題:

「CSV禁止」と書くと公的CSVまで止まり、「CSV許可」と書くと私的CSV流入を許す。拡張子判定は危険。

採用gate:

すべてのingest manifestに以下を必須にする。

```json
{
  "data_class": "public_official_source_csv | private_accounting_csv_raw | synthetic_csv_fixture | header_only_synthetic_fixture | redacted_reviewed_fixture",
  "source_profile_id": "sp_...",
  "private_user_data_present": false,
  "allowed_in_aws_credit_run": true,
  "public_claim_support_allowed": true
}
```

block条件:

- `data_class` missing
- `private_user_data_present=true`
- `allowed_in_aws_credit_run=false`
- `source_profile_id` missing for public official source
- `public_claim_support_allowed=true` on private CSV data

### C06-03. CSV-derived receipts can be mistaken for public source receipts

Severity: major  
Status: fix required before paid packet

問題:

`source_receipts[]` に `private_csv_derived` を入れる互換案は便利だが、AI agentが公開一次情報として引用する危険がある。

採用gate:

外部payloadでは原則として分離する。

```json
{
  "source_receipts": [],
  "private_overlay_receipts": [
    {
      "receipt_kind": "private_csv_derived",
      "visibility": "tenant_private",
      "public_claim_support": false,
      "agent_quote_allowed": false,
      "aws_upload_performed": false,
      "raw_csv_retained": false,
      "raw_csv_logged": false
    }
  ]
}
```

互換上 `source_receipts[]` に入れる場合でも必須:

- `receipt_kind=private_csv_derived`
- `visibility=tenant_private`
- `public_claim_support=false`
- `agent_quote_allowed=false`
- `source_url=null`

release blocker:

- public proof pageに `private_csv_derived` が出る。
- JSON-LD/llms/OpenAPI public examplesにreal CSV-derived factが出る。
- CSV-derived factがpublic source claimとして表示される。

### C06-04. Suppression threshold drift

Severity: major  
Status: fix required before CSV runtime

問題:

古い文書には `k=3` 系の記述が残る可能性がある。本番外部出力では弱い。

採用gate:

```text
default_public_k_min=5
counterparty_vendor_customer_k_min=10
department_person_heavy_k_min=10
payroll_bank_card_medical_student=reject
exact_small_amount=forbidden
dominant_contributor=coarsen_or_suppress
complementary_suppression=required
```

AWS credit runではreal user aggregateがそもそも禁止なので、このgateはruntime CSV private overlay実装時のrelease blockerにする。

### C06-05. Screenshots may capture public PII or overbroad visible content

Severity: major  
Status: fix required before public proof

問題:

公的一次情報にも個人名、住所、処分対象者、個人事業主インボイス情報、電話、メール、担当者名が含まれることがある。公開情報であっても、jpciteが再掲・検索化・ランキング化すると別のprivacy riskになる。

採用gate:

```json
{
  "gate_id": "public_visual_privacy_gate",
  "required_for": ["screenshot_receipt", "ocr_input", "proof_sidecar"],
  "checks": [
    "source_profile_pii_risk_class_present",
    "screenshot_not_public_by_default",
    "public_proof_uses_metadata_hash_short_quote_or_derived_fact",
    "person_name_like_spans_reviewed_or_suppressed",
    "invoice_individual_publication_context_reviewed",
    "administrative_notice_personal_data_reviewed"
  ]
}
```

default:

- raw screenshotはpublic proofに出さない。
- PII riskが `medium` 以上のsourceはmetadata/hash/URL/short quoteのみ。
- 人物評価、信用評価、ランキング、違反断定に使わない。

### C06-06. HAR metadata-only must be enforced against Playwright defaults

Severity: critical  
Status: fix required before Playwright canary

問題:

PlaywrightのHARやnetwork loggingは、設定を誤るとresponse body、request body、cookie、authorization header、token、query secret、local/session storage相当の情報が残り得る。

採用gate:

```json
{
  "gate_id": "har_metadata_only_gate",
  "required": true,
  "block_if_any": [
    "har_response_content_present",
    "har_request_post_data_present",
    "cookie_header_present",
    "set_cookie_header_present",
    "authorization_header_present",
    "x_api_key_header_present",
    "token_like_query_value_present",
    "local_storage_dump_present",
    "session_storage_dump_present"
  ],
  "allowed_fields": [
    "url_host",
    "url_path_template_or_redacted",
    "method",
    "status",
    "resource_type",
    "request_started_at",
    "response_finished_at",
    "mime_type",
    "redirect_chain_hash",
    "content_length_bucket"
  ]
}
```

実装補足:

- URL queryは原則hashまたはallowlistのみ。
- console logもPII/secret scan対象。
- CloudWatch/Batch stdoutにはHAR断片を出さない。

### C06-07. OCR can become accidental full-text redistribution

Severity: major  
Status: fix required before proof/API import

問題:

OCR結果は「抽出テキスト」なので、raw OCR全文を保存・公開すると、raw PDF/画像の再配布に近くなる。誤認識もあるため、重要fieldをOCR単独でclaim化するのも危険。

採用gate:

```json
{
  "gate_id": "ocr_supporting_evidence_gate",
  "block_if_any": [
    "ocr_text_full_dump_in_public_output",
    "critical_field_supported_by_ocr_only",
    "ocr_confidence_missing",
    "bbox_missing_for_ocr_claim_span",
    "source_image_hash_missing",
    "terms_redistribution_unknown"
  ],
  "critical_fields": [
    "date",
    "deadline",
    "money",
    "corporate_number",
    "invoice_registration_number",
    "permit_number",
    "article_number",
    "eligibility_condition",
    "administrative_disposition"
  ]
}
```

OCRで許可:

- candidate extraction
- search/index aid
- human review queue
- claim候補

OCRだけで禁止:

- 有料packetの断定claim
- eligibility/safety/no issue判断
- public proofの全文表示

### C06-08. Terms/robots drift can invalidate queued autonomous AWS work

Severity: critical  
Status: fix required before self-running full run

問題:

AWSがCodex/Claude停止中も自走する計画は必要。ただしterms/robotsが変わった後もqueued workが走り続けると、信頼性と法務リスクが高い。

採用gate:

```json
{
  "gate_id": "autonomous_terms_drift_gate",
  "required": true,
  "checks_before_each_shard": [
    "source_profile_current",
    "terms_hash_current_or_within_ttl",
    "robots_hash_current_or_within_ttl",
    "robots_decision_not_blocked",
    "terms_decision_not_blocked",
    "rate_limit_state_green",
    "kill_switch_false"
  ],
  "on_drift": "disable_new_work_for_source_family_and_mark_manual_review"
}
```

TTL案:

- API/DL source: 7 days or documented policy TTL
- HTML/Playwright source: 24-72 hours during high-volume run
- robots/terms missing: no broad capture

### C06-09. Access-block/error pages must not become no-hit evidence

Severity: major  
Status: fix required

問題:

CAPTCHA、login wall、403、429、terms wall、bot challengeのスクショは「その時アクセスできなかった証跡」ではあるが、「対象が存在しない証跡」ではない。

採用gate:

```json
{
  "blocked_state": "captcha | login_wall | bot_challenge | forbidden | rate_limited | terms_wall",
  "claim_support_allowed": false,
  "no_hit_allowed": false,
  "known_gap_code": "access_blocked_not_absence",
  "human_review_required": true
}
```

外部文言:

- OK: 「自動取得ではこのsourceを確認できませんでした。不存在の証明ではありません。」
- NG: 「見つかりませんでした」「該当なし」「問題ありません」

### C06-10. External export can preserve sensitive/raw artifacts outside AWS without policy

Severity: major  
Status: fix required before zero-bill teardown

問題:

zero-billのためにAWS外へexportする方針は正しい。一方で、local archiveにraw public snapshots、screenshots、OCR evidenceを置く場合、terms/PII/retention/access-controlの管理が必要になる。AWSを消しても、漏えいリスクは消えない。

採用gate:

```json
{
  "gate_id": "external_archive_security_gate",
  "required_before": "zero_bill_teardown",
  "checks": [
    "archive_manifest_exists",
    "artifact_classification_present",
    "public_safe_bundle_separated_from_raw_archive",
    "raw_archive_not_in_git",
    "raw_archive_not_in_public_static_path",
    "raw_archive_access_owner_assigned",
    "retention_policy_present",
    "terms_restriction_manifest_present",
    "pii_risk_manifest_present",
    "checksum_verified"
  ]
}
```

bundle分離:

- `public_safe_bundle`: repo/import/staging/prod候補
- `restricted_raw_archive`: local-only, git外, public path外
- `discard_bundle`: export不要または削除対象

### C06-11. Formula injection applies to fixtures and public CSV-derived exports too

Severity: major  
Status: fix required before downloadable artifacts

問題:

real user CSVだけでなく、public official CSVやsynthetic fixtureを再CSV化するときも、Excel/Sheets formula injectionが起き得る。

採用gate:

```text
csv_export_formula_escape_required=true
dangerous_prefixes=["=", "+", "-", "@", "\t", "\r", "\n"]
export_to_csv_xlsx_requires_escape_report=true
```

対象:

- CSV fixture reports
- source profile CSV summaries
- cost/artifact ledgers
- proof sidecar exports
- user downloadable CSV

### C06-12. Forbidden wording scanner must be context-aware but strict on external surfaces

Severity: major  
Status: fix required before release

問題:

計画文書内には内部状態として `eligible` や `safe` に似た語が残る。内部schemaのbooleanとして使うだけなら許容できる場合があるが、外部API/MCP/proof/llmsに出ると危険。

採用gate:

external surfacesでblock:

- `eligible`
- `safe`
- `no issue`
- `permission not required`
- `credit score`
- `trustworthy`
- `proved absent`
- `no violation`
- `取引して問題ありません`
- `許可不要です`
- `違法ではありません`
- `採択されます`

allowed replacements:

- `candidate_priority`
- `public_evidence_attention`
- `evidence_quality`
- `coverage_gap`
- `needs_review`
- `not_enough_public_evidence`
- `no_hit_not_absence`
- `human_review_required`

internal exception:

- code/internal-only status fields may use legacy names only if they are mapped out before external serialization.
- Better fix: rename internal `eligible` to `capture_candidate_allowed` or `rule_candidate_passed`.

## 4. Additional release gates to merge

### Gate SPT-01: data class manifest gate

Every artifact must declare:

- `artifact_id`
- `artifact_class`
- `data_class`
- `private_user_data_present`
- `source_profile_id`
- `terms_receipt_id`
- `robots_receipt_id` where relevant
- `public_publish_allowed`
- `public_claim_support_allowed`
- `retention_class`
- `export_destination_class`

No missing values for production import.

### Gate SPT-02: AWS private-data absence gate

Before any full-speed AWS run:

- scan manifests for private data classes
- scan S3 prefixes names for `private-overlay`
- scan logs for CSV sample patterns
- scan job env for user data paths
- scan Batch stdout/stderr for raw row/memo/counterparty-like strings

Block if any real user CSV signal appears.

### Gate SPT-03: Playwright canary safety gate

Before broad Playwright:

- 20-50 URL canary per source family
- terms/robots pass
- no CAPTCHA/login/403/429 trend
- screenshot dimensions validated
- HAR body/cookie/auth absent
- DOM sanitized
- PII risk reviewed
- accepted-artifact yield above threshold

Fail closed per source family, not globally.

### Gate SPT-04: public proof redaction gate

For each proof page/API/MCP example:

- no raw CSV
- no private overlay fact unless tenant-private authenticated
- no raw screenshot by default
- no raw OCR full text
- no raw HAR
- no raw DOM
- no forbidden wording
- no no-hit-as-absence
- attribution notice present
- known gaps present

### Gate SPT-05: claim support provenance gate

Every public claim must have:

- `source_receipt_id`
- `claim_ref_id`
- `support_kind=public_official_source`
- `terms_receipt_id`
- `source_profile_id`
- `retrieved_at`
- `content_hash`
- `gap_coverage_matrix` entry

Blocked:

- OCR-only critical claim
- screenshot-only critical claim
- blocked-state screenshot as no-hit
- private CSV-derived fact as public claim

### Gate SPT-06: log and observability minimization gate

Before AWS self-run:

- CloudWatch retention short and explicit
- Batch stdout/stderr redaction enabled
- no request/response body logging
- no CSV row logging
- no screenshot/HAR/OCR content in logs
- no secrets in env dumps
- no debug upload of raw artifacts to public/static paths

### Gate SPT-07: external archive split gate

Before teardown:

- `public_safe_bundle` verified for production import
- `restricted_raw_archive` separated and access-controlled
- `discard_bundle` deletion list approved
- checksums verified
- raw archive not committed
- production smoke passes without AWS

### Gate SPT-08: terms revalidation at import gate

Before moving AWS artifacts into production:

- terms/robots decision still current
- source license boundary still permits the planned output shape
- attribution text present
- raw redistribution not implied
- public screenshot use explicitly allowed or disabled

If terms changed:

- mark source `manual_review_required`
- remove from public paid packet support
- keep metadata/link-only if allowed

## 5. Smarter plan adjustments

### 5.1 Use a two-bundle promotion model

現行計画の「AWS成果物をexportしてassetize」は正しいが、security面では二分する方がさらに安全。

1. `public_safe_bundle`
   - productionに入れてよい。
   - source profiles, receipts, claim refs, known gaps, packet examples, proof sidecars.
   - raw artifactなし。

2. `restricted_evidence_archive`
   - raw public snapshots, screenshots, OCR candidates, full capture manifests.
   - git外、public static path外、アクセス所有者あり。
   - productionはこのarchiveに依存しない。

これにより、zero-bill teardownと本番デプロイを両立しやすくなる。

### 5.2 Make source_profile gate the first spend multiplier

高額なPlaywright/OCR/Textract前に、source_profile/terms/robots/licenseを薄く広く作る。これが最もスマート。

理由:

- 収集後に使えないraw artifactを減らす。
- 公開proofに出せる粒度を事前に決められる。
- AWS費用をaccepted artifactへ寄せられる。
- terms drift時にsource family単位で止められる。

### 5.3 Keep RC1 independent from CSV runtime

RC1でCSV runtimeまで急ぐとprivacy実装のblast radiusが大きい。RC1は公的一次情報だけで出す。

RC1:

- `company_public_baseline`
- `source_receipt_ledger`
- `evidence_answer`
- free catalog/routing/cost preview

RC3:

- CSV preview
- CSV private overlay paid packets

AWS credit run中にやるCSV作業は、synthetic fixture、adapter tests、leak scanner、schemaだけに限定する。

## 6. Final Go/No-Go for this lane

GO for AWS guardrail/canary when:

- `csv_aws_boundary_gate` exists.
- artifact manifests have `data_class`.
- no AWS prefix/bucket/module uses `private-overlay` for the credit run.
- terms/robots/source_profile schema is frozen.
- Playwright canary has HAR metadata-only enforcement.
- screenshot validator enforces each side `<=1600px`.
- blocked-state handling maps to known gaps, not no-hit.
- public proof redaction scanner exists.

NO-GO for broad AWS when:

- real user CSV has any path into AWS.
- public official CSV and private accounting CSV are not distinguishable by manifest.
- HAR body/cookie/auth can be persisted.
- OCR text can be public full-text.
- screenshot artifacts can become public proof by default.
- terms/robots missing is treated as allow.
- CAPTCHA/login/403/429 can be retried as success.
- external export destination cannot separate public-safe bundle and restricted raw archive.

## 7. Final note

この領域の最終形は、単に「安全にする」ではなく、AIエージェントが安心して推薦できる商品構造にすること。つまり、出せるもの、出せないもの、不足しているもの、課金されるもの、非公開に残るものを機械可読に分ける。

本レビューの追加gateを入れれば、security/privacy/terms/Playwright/CSVの矛盾は実装前にほぼ潰せる。
