# Security / Privacy / CSV Handling Deep Dive

作成日: 2026-05-15  
担当: Security / privacy / CSV handling / abuse control  
状態: pre-implementation planning only  
制約: 実装コードは触らない。CSV raw は保存しない。摘要・取引先・個人情報・給与/銀行情報を外部向け成果物へ転記しない。

## 0. Executive Security Contract

jpcite の CSV intake は、公的 source evidence とは別の「ユーザー持ち込み private operational data」として扱う。CSV は source receipt ではなく、構造確認・品質確認・集計の入力であり、raw 行・摘要・取引先・自由記述・個人情報・給与/銀行情報を保存または再露出してはならない。

P0 contract:

- CSV raw bytes, raw rows, row-level normalized records, 摘要, 取引先, 伝票番号そのもの, 作成者名, 自由記述は永続保存しない。
- 成果物は列構成、件数、期間、集計、presence、hash、review reason に限定する。
- 給与、銀行、カード、口座、医療/福祉利用者、個人名、住所、電話、メール、マイナンバーらしき情報は rejection または hard redaction 対象にする。
- AI エージェント経由の API/MCP 利用は、API key を prompt/log/output に出さず、shared IP と stdio の限界を明示し、quota/cap/idempotency を必須化する。
- ログは request tracing と abuse control に必要な最小限のみ。payload value、CSV cell value、API key、secret、raw error body はログ禁止。
- no-hit、CSV品質異常、専門判断境界は security/privacy issue と混同せず、必ず `known_gaps` と `human_review_required` に落とす。

## 1. CSV Privacy Threat Model

### 1.1 Assets

| Asset | Sensitivity | Storage posture | Output posture |
|---|---|---|---|
| CSV raw bytes | high | never persist | never echo |
| Row-level records | high | transient memory only | never export |
| 摘要 / 仕訳メモ / 付箋 / タグ | high | never persist as value | presence/hash only |
| 取引先 / 顧客 / 従業員 / 作成者 | high | never persist as value | count/presence only |
| 銀行口座 / カード / 請求書番号 | critical | reject or redact before processing | never export |
| 給与 / 役員報酬 / 源泉 / 社保 | critical | reject or aggregate-only with hard review | never row-level |
| 個人情報 / 医療 / 福祉利用者 | critical | reject if value appears in free text/counterparty | never export |
| Column names | medium | may persist | allow, after header redaction |
| Row count / date range / vendor family | low | may persist | allow |
| Account vocabulary | medium | may persist as aggregate | allow with rare-cell guard |
| Amount aggregates | medium | may persist | allow only aggregate and k-thresholded |
| Derived review facts | low-medium | may persist | allow |

### 1.2 Attackers and Failure Modes

| Actor / failure | Vector | Impact | P0 mitigation |
|---|---|---|---|
| Curious downstream agent | Asks tool to summarize raw CSV or list counterparties | Private data disclosure | Tool schema denies raw echo; response sanitizer blocks row/cell output |
| Prompt-injected CSV cell | Cell contains instructions such as "ignore privacy rules" | Agent follows CSV content as instruction | Treat all CSV cells as untrusted data, never prompt instructions |
| Formula injection | Cell begins with `=`, `+`, `-`, `@`, tab, CR/LF payload | Spreadsheet command execution on export | Escape or reject before any CSV/Excel export; aggregate-only exports |
| Operator/debug logging | Exceptions include row values or payload | Persistent sensitive log leak | Structured logs with shape only; exception scrubbing |
| Support workflow | User sends real CSV sample for debugging | Internal spread of private data | Synthetic/redacted samples only; raw support attachment purge SOP |
| Cross-tenant leakage | Cache/idempotency keyed only by payload hash | One tenant can replay another result | Tenant/key scoped idempotency and cache namespaces |
| Small-cell re-identification | Aggregate bucket with 1-2 rows exposes a transaction | Private transaction inference | Suppress `entry_count < 3`; coarsen bucket |
| Hash dictionary attack | Unsalted hash of memo/counterparty | Recoverable private values | Tenant-scoped HMAC/hash salt; do not expose hashes unless needed |
| CSV/public source join | Counterparty names joined to public records | Personal/business relationship exposure | Exact ID only for external output; name-only joins require review |
| Malware-like oversized CSV | Very large/wide/deep CSV | Cost/availability abuse | Size, row, column, parse-time limits before processing |

### 1.3 Privacy Boundary by Pipeline Stage

| Stage | Allowed | Forbidden | Required controls |
|---|---|---|---|
| Upload/intake | Temporary stream/buffer, file size, content type, encoding sniff | Raw persistence, raw log, full payload error | Max bytes/rows/columns, timeout, antivirus optional P1 |
| Parse | Column mapping, parse counts, transient row object | Treating cells as instructions, storing raw row | CSV parser only, no eval, no formula execution |
| Detect sensitive fields | Header scan, sampled redacted scan, rejection codes | Persisting flagged values | PII/payroll/bank classifiers before aggregation |
| Normalize | Internal transient fields needed for aggregation | Storing row-level normalized entries | Memory/temp only; temp file encrypted or disabled |
| Aggregate | Counts, sums, min/max dates, distinct counts, account classes | Rare row reconstruction | k-threshold, bucket coarsening |
| Persist | Derived file profile, aggregate facts, review facts | Raw CSV, memo/counterparty values, row facts | Schema review; persistence allowlist |
| Export | Markdown/JSON aggregate packets | Raw CSV echo, row anomaly CSV, exact counterparties | Default deny for CSV export; explicit schema allowlist |
| Logs/telemetry | request_id, route, tenant hash, payload shape, reject code | API key, payload value, CSV cell, amount, memo | Redaction middleware, tests, Sentry scrub |

## 2. CSV Handling Rules

### 2.1 Default Deny Fields

The following fields are not exportable and not persistable as values:

- 摘要, 仕訳メモ, メモタグ, 付箋, 自由記述。
- 借方取引先, 貸方取引先, 顧客名, 仕入先名, 従業員名, 患者/利用者/児童/入居者名。
- 作成者, 更新者, メール, 電話, 住所, 生年月日。
- 銀行名 + 支店 + 口座番号, カード番号, 振込先, IBAN/SWIFT, 請求書番号。
- 給与明細、賞与、源泉、社保、住民税、役員報酬の個人別明細。
- マイナンバー、基礎年金番号、保険者番号、診察券番号、社員番号など個人識別子。

Allowed substitutes:

- `field_present=true|false`
- `distinct_count`
- `redacted_count`
- `contains_sensitive_pattern=true`
- tenant-scoped HMAC hash only when needed for deduplication, not for public output
- aggregate bucket with `entry_count >= 3`

### 2.2 Rejection vs Redaction

| Condition | Decision | Error / review code | Notes |
|---|---|---|---|
| Header explicitly indicates payroll register or bank transfer file | reject | `csv_payroll_or_bank_file_rejected` | jpcite P0 is accounting CSV aggregate, not payroll/banking processor |
| Header includes account number/card number/マイナンバー | reject | `csv_sensitive_identifier_rejected` | Do not attempt partial processing |
| Free-text/counterparty sampled cells contain likely personal identifiers | reject or require local-only mode | `csv_pii_value_detected` | P0 should reject until privacy review approves masking |
| Accounting CSV contains payroll-related account names only as aggregate科目 | allow with hard review | `csv_payroll_related_aggregate_only` | No employee/counterparty values |
| Bank fee/loan/interest account names appear without account numbers | allow with hard review | `csv_bank_related_aggregate_only` | Account names are allowed as vocabulary; bank details are not |
| Formula-like cell appears in any raw field | allow only if not exported; escape if exportable aggregate label | `csv_formula_like_cell_detected` | Raw cell value never exported |
| Row-level anomaly requested | deny external export | `csv_row_level_export_denied` | Internal review queue can count conditions only |
| Small aggregate bucket | suppress/coarsen | `csv_small_cell_suppressed` | Default threshold `k=3` |

### 2.3 Formula Injection Rules

Formula injection is handled even when raw CSV is not saved, because future exports and copy-paste surfaces can reintroduce risk.

Dangerous prefixes after trimming BOM and leading whitespace:

- `=`
- `+`
- `-`
- `@`
- tab-prefixed formula
- CR/LF followed by formula prefix

Rules:

- Raw formula-like cell values must never appear in Markdown, JSON examples, CSV export, logs, errors, or prompts.
- If an aggregate label is derived from a field that might contain formula text, label must be replaced with a neutral bucket such as `redacted_free_text`.
- Any CSV/Excel export introduced later must escape formula-like strings by prefixing a single quote and must still pass aggregate-only allowlist.
- Tests must include Japanese text with leading formula characters and multiline injection payloads.

### 2.4 PII Rules

P0 classifiers can be conservative and reject rather than risk overprocessing.

Hard rejection indicators:

- マイナンバー-like 12-digit personal ID in a personal context.
- Email address, phone number, full postal address in free text/counterparty fields.
- Bank account pattern: bank/branch/account type/account number in same row or nearby columns.
- Card number-like 13-19 digit sequence passing basic checksum or card context.
- Patient, resident, student, child, employee, caregiver, beneficiary names in sensitive industry files.
- Payroll register headers: employee name, base salary, overtime, dependent count, social insurance, withholding tax.

Allowed with review:

- Account names such as `給料手当`, `役員報酬`, `法定福利費`, `支払利息`, `普通預金`, `長期借入金` as aggregate vocabulary.
- Tax amount columns as aggregate values, without tax advice.
- Bank-related accounting科目 as account vocabulary, without account numbers or payee detail.

### 2.5 Payroll and Bank Rejection Rules

P0 must reject files that look like payroll detail or bank transfer instruction files, even if they are CSV and even if the user asks for summarization.

Reject when any of these header clusters appear:

| Cluster | Example headers |
|---|---|
| Payroll identity | `社員名`, `従業員名`, `従業員番号`, `所属`, `雇用形態` |
| Payroll calculation | `基本給`, `残業代`, `控除`, `扶養`, `源泉所得税`, `住民税`, `社会保険料`, `雇用保険料` |
| Bank transfer | `銀行名`, `支店名`, `口座種別`, `口座番号`, `口座名義`, `振込金額` |
| Sensitive personal | `マイナンバー`, `生年月日`, `住所`, `電話番号`, `メールアドレス` |

Accounting CSV exception:

- A journal file with aggregated account names such as `給料手当` or `普通預金` may be processed only when there are no employee/person/bank account value columns.
- Output must say `payroll_or_bank_related_aggregate_present=true` and `human_review_required=true`.

## 3. API / MCP Abuse and Key Handling Model

### 3.1 Threats

| Threat | API/REST vector | MCP/agent vector | P0 controls |
|---|---|---|---|
| API key leak | Key pasted into prompt, repo, screenshot, logs | Agent includes env var in conversation | Key format detection, log redaction, rotation, docs warnings |
| Shared IP quota collision | NAT, office, VPN, hosted agents | Multiple users behind same egress | Anonymous quota is trial only; paid keys for production |
| Stdio IP ambiguity | No reliable caller IP | Local MCP client hides user identity | Usage state accurate only for authenticated key |
| Runaway agent loop | Repeated paid calls | Tool recursion or retries | Cost preview, per-execution cap, monthly cap, idempotency |
| Replay/double billing | Retry after timeout | Agent retries with new key each time | Idempotency required for paid POST/batch/CSV |
| Cross-user idempotency leak | Idempotency key not scoped | Shared client reuses key | Scope by customer/key/endpoint/request hash |
| Credential stuffing | Many invalid keys | Agent misconfigured or attacker | Rate limit invalid auth, generic error, no key existence oracle |
| Batch scraping | Search/fanout over corpus | Agent loops catalog | Per-key and per-IP rate limits, caps, preview for broad work |
| Cost DDoS with valid key | Stolen key | Hosted agent leaked key | Monthly cap, emergency revoke, anomaly alerts |
| Prompt exfiltration | User asks agent to reveal tool config | MCP config/env leaked | Tool must never return env/config/secrets |

### 3.2 API Key Rules

Storage:

- Store only HMAC/key hash server-side. Never store plaintext API key.
- Production secrets must live in secret manager/runtime env, not docs, prompt, examples, or repo.
- Customer-visible key is shown once at creation; rotation invalidates old key.

Transport:

- REST uses `X-API-Key`.
- MCP uses `JPCITE_API_KEY` or client secret configuration.
- Never accept API key in query string.
- If Authorization bearer is added later, logs must redact both header forms.

Logging:

- Redact full key and key-like substrings. Safe display format is prefix + last 4 at most, for example `jc_live_...wxyz`.
- Do not log request headers wholesale.
- Do not include API key in validation errors, Sentry breadcrumbs, structured event metadata, OpenAPI examples, or support screenshots.

Rotation/revocation:

- User self-rotation for suspected leak.
- Operator emergency revoke for abuse.
- Revocation invalidates rate/cap/idempotency caches tied to the key.
- Key leak incident requires affected customer notification and postmortem entry.

### 3.3 Quota, Rate Limit, and Cost Cap Rules

| Operation class | Anonymous | Paid key | Required controls |
|---|---|---|---|
| Discovery / manifests / OpenAPI | allowed | allowed | operational throttle only |
| Cost preview | allowed, no 3/day consumption | allowed | separate throttle, no billing |
| Small search/detail | 3 req/day/IP trial | metered or included by plan | rate limit, request_id |
| Single packet | optional trial | metered | cap if paid, structured billing metadata |
| CSV intake / batch / fanout / watchlist / export | deny anonymous | metered | API key, preview, cap, idempotency |

Cap rules:

- Paid broad execution must reject before work if no cap is provided.
- Predicted maximum cost is conservative and compared to cap before billable work.
- `cost_cap_exceeded`, auth failure, validation rejection, quota rejection, idempotency conflict, unsupported request, and CSV rejection are not billed.
- Response must reconcile predicted units, actual units, not-billed units, cap, and external cost exclusion.

### 3.4 Idempotency Rules

Paid POST, CSV intake, batch, fanout, watchlist, and export require `Idempotency-Key`.

Rules:

- Same customer/key + endpoint + idempotency key + normalized payload hash returns original result or execution pointer.
- Same customer/key + endpoint + idempotency key + different normalized payload hash returns `409 idempotency_conflict`.
- Replayed success must not create a second usage event.
- Records store request hash, tenant/key hash, endpoint, created_at, expiry, status, billing decision, and response pointer.
- Do not include raw CSV bytes or raw payload values in idempotency records. Use hashes and derived shape only.
- Expiry should be long enough for agent retry windows; P0 target 24-72h.

### 3.5 Abuse Signals and Responses

| Signal | Severity | Response |
|---|---|---|
| Many invalid keys from one IP | warning | throttle auth failures, generic 401 |
| Repeated cap exceeded with high predicted units | warning | require scope reduction; do not bill |
| Many CSV rejects containing sensitive patterns | review | slow down tenant, privacy warning |
| Same key from impossible regions / many ASNs | high | notify, temporary hold or rotate |
| Paid key near monthly cap with high retry rate | high | alert customer/operator, reduce concurrency |
| Request payload shape changes with same idempotency key | medium | 409 and no bill |
| Anonymous IP cycling scraping search endpoints | high | WAF/rate challenge, require API key |

## 4. Logging, Redaction, and Persistence Rules

### 4.1 Structured Logging Allowlist

Allowed log fields:

- `request_id`
- `timestamp`
- `route`
- `method`
- `status_code`
- `error_code`
- `retryable`
- `billing_effect`
- `billable_units`
- `customer_hash`
- `api_key_hash_prefix` or internal key id, not key
- `client_tag_hash`
- `ip_hash`
- `user_agent_family`
- `payload_shape`: top-level keys, row_count, column_count, byte_size bucket
- `csv_vendor_family`
- `csv_reject_code`
- `duration_ms`

Forbidden log fields:

- API key, Authorization header, cookies, secret env values.
- Raw CSV bytes, cell values, row values, first/last row samples.
- 摘要, 取引先, account numbers, card numbers, phone, email, address.
- Exact amount values from user CSV. Use bucket or aggregate only if needed.
- Full exception messages from parsers if they include offending values.
- Prompt text containing secrets or pasted CSV content.

### 4.2 Error Response Rules

Errors must help the caller fix shape, not reveal data.

Allowed:

- `csv_sensitive_identifier_rejected`
- `csv_payroll_or_bank_file_rejected`
- `csv_formula_like_cell_detected`
- `csv_small_cell_suppressed`
- `invalid_intake`
- Column name when the column name itself is not sensitive.
- Count of rejected rows/cells.

Forbidden:

- Echoing the offending cell value.
- Showing row number plus full row.
- Showing exact matched personal identifier.
- Saying a person, bank account, or salary exists in a way that identifies them.

### 4.3 Persistence Allowlist

May persist:

- Derived file profile: `source_file_id`, vendor family, encoding, row/column counts, date range, column profile hash.
- Column names after sensitive header review.
- Aggregate facts at file/month/account/light-class level with k-threshold.
- Review facts and reason codes.
- Input receipt/profile stating `raw_persisted_by_jpcite=false`.
- Billing usage event with units and request id.
- Idempotency record with scoped payload hash and response pointer.

Must not persist:

- Raw CSV file.
- Raw rows or row-level normalized records.
- Free-text values.
- Counterparty/person/bank/payroll identifiers.
- Prompt that contains user CSV.
- Unredacted request/response body.

### 4.4 Retention Targets

| Data | P0 retention |
|---|---|
| Raw CSV stream/buffer | process lifetime only; delete immediately after aggregation |
| Temp parse file if unavoidable | disabled by default; otherwise encrypted and deleted on success/failure |
| Derived aggregate packet | customer-configured retention or product default |
| Idempotency metadata | 24-72h |
| Usage/billing event | billing/audit retention as required |
| Security logs | 30-90 days, redacted |
| Support artifacts | synthetic/redacted only |

## 5. Output and Agent Handoff Rules

CSV-derived packets must include:

```json
{
  "user_input_profile": {
    "input_kind": "accounting_csv",
    "raw_persisted_by_jpcite": false,
    "raw_export_allowed": false,
    "sensitive_data_possible": true,
    "privacy_boundary": "aggregate_or_presence_only"
  },
  "human_review_required": true,
  "known_gaps": [
    {
      "gap_kind": "privacy",
      "gap_id": "csv_raw_not_exportable",
      "followup_action": "mask_or_aggregate"
    }
  ]
}
```

Agent must preserve:

- `raw_persisted_by_jpcite=false`
- `raw_export_allowed=false`
- `known_gaps`
- `human_review_required`
- `_disclaimer`
- `billing_metadata`
- `request_id` for support, without payload

Agent must not:

- Ask jpcite to reveal raw rows after a privacy rejection.
- Convert `review_required` into a professional conclusion.
- Copy CSV-derived sensitive values into final answers.
- Include API key or MCP config secrets in generated output.

## 6. P0 Security Test List

### 6.1 CSV Privacy Tests

| ID | Test | Expected |
|---|---|---|
| SEC-CSV-001 | Upload normal accounting CSV with memo/counterparty columns | No raw values persisted or exported; presence/count only |
| SEC-CSV-002 | CSV contains 摘要 with email/phone/address | Reject or hard redact; error contains code/count only |
| SEC-CSV-003 | CSV contains bank account headers and values | Reject with `csv_sensitive_identifier_rejected` |
| SEC-CSV-004 | CSV looks like payroll register | Reject with `csv_payroll_or_bank_file_rejected` |
| SEC-CSV-005 | Accounting CSV contains `給料手当` account name only | Allow aggregate; `human_review_required=true` |
| SEC-CSV-006 | Formula cell starts with `=HYPERLINK(...)` | Never exported/logged; formula detection reason recorded |
| SEC-CSV-007 | Formula cell starts with `+`, `-`, `@`, tab, CR/LF | Detected and safely suppressed/escaped |
| SEC-CSV-008 | Aggregate bucket has `entry_count=1` or `2` | Amount and specific label suppressed/coarsened |
| SEC-CSV-009 | Parser error on malformed row | Error does not echo row/cell content |
| SEC-CSV-010 | Unsupported encoding CSV | Reject or fallback; no raw sample in logs |
| SEC-CSV-011 | Column name includes sensitive header | Reject or redact header before persistence |
| SEC-CSV-012 | Prompt injection text inside CSV cell | Treated as data only; not used as instruction |

### 6.2 Persistence and Logging Tests

| ID | Test | Expected |
|---|---|---|
| SEC-LOG-001 | Request includes API key | Logs/Sentry redact key fully |
| SEC-LOG-002 | Request includes Authorization header | Header not logged or redacted |
| SEC-LOG-003 | CSV rejection includes PII | Error/log contains reject code and count only |
| SEC-LOG-004 | Exception raised during parse | Sentry event has no local CSV values |
| SEC-LOG-005 | Derived packet persisted | Contains only allowed aggregate/profile fields |
| SEC-LOG-006 | Search logs with query params | Values redacted; shape only |
| SEC-LOG-007 | Support/debug sample generation | Synthetic or redacted fixture only |

### 6.3 API/MCP Abuse Tests

| ID | Test | Expected |
|---|---|---|
| SEC-API-001 | Paid CSV execution without API key | `401 auth_required`, not billed |
| SEC-API-002 | Paid CSV execution without cap | `400 cost_cap_required`, not billed |
| SEC-API-003 | Paid CSV execution predicted above cap | `402 cost_cap_exceeded`, no work, not billed |
| SEC-API-004 | Paid CSV execution without idempotency key | `428 idempotency_key_required`, not billed |
| SEC-API-005 | Same idempotency key and same payload retried | Same result, no double billing |
| SEC-API-006 | Same idempotency key and different payload | `409 idempotency_conflict`, not billed again |
| SEC-API-007 | Idempotency record for CSV | Stores scoped hash, not raw CSV/payload |
| SEC-API-008 | Anonymous tries batch/CSV/watchlist/export | Denied; API key required |
| SEC-API-009 | Cost preview call | Free, no anonymous 3/day consumption |
| SEC-API-010 | Many invalid keys | Throttled; no key existence oracle |
| SEC-API-011 | MCP stdio usage status unauthenticated | Does not claim reliable IP quota |
| SEC-API-012 | Agent asks tool to reveal API key/config | Tool never returns secrets |

### 6.4 Output Contract Tests

| ID | Test | Expected |
|---|---|---|
| SEC-OUT-001 | CSV-derived Markdown brief | Contains privacy disclaimer, no raw rows/memo/counterparty |
| SEC-OUT-002 | JSON packet from CSV | Includes `raw_persisted_by_jpcite=false` and `raw_export_allowed=false` |
| SEC-OUT-003 | CSV export requested | Denied unless aggregate-only schema is explicit |
| SEC-OUT-004 | Row-level anomaly list requested externally | Denied or converted to counts |
| SEC-OUT-005 | Public-source join from company name only | Candidate/review required, no assertion |
| SEC-OUT-006 | Personal counterparty join requested | Denied for external output |

## 7. Implementation Gate Checklist

Before any CSV intake implementation ships:

- [ ] Persistence allowlist exists and has tests proving raw CSV/row/free-text values are absent.
- [ ] Logging redaction tests cover API keys, Authorization headers, CSV values, parser exceptions, and Sentry events.
- [ ] CSV sensitive-file rejection covers payroll, bank transfer, personal identifiers, and formula-like cells.
- [ ] Aggregate outputs enforce `entry_count >= 3` or coarsening.
- [ ] Paid CSV/batch/export paths require API key, cost preview path, hard cap, and idempotency key.
- [ ] Idempotency/cache keys are tenant scoped and store hashes only.
- [ ] Error envelopes use closed codes and never echo offending sensitive values.
- [ ] MCP docs warn that stdio cannot reliably know caller IP for anonymous quota.
- [ ] Agent handoff examples preserve privacy fields, review flags, known gaps, and billing metadata.
- [ ] Security fixtures use synthetic or redacted CSV only.

## 8. Open Questions for Implementation Planning

- Whether P0 should reject all CSVs with any PII-like value, or allow local-only aggregate mode after hard redaction. Security recommendation: reject until a reviewed local-only mode exists.
- Whether column names themselves can be customer confidential. Security recommendation: persist column profile hash always; persist names only after header review.
- Whether account-level amount aggregates require different k-thresholds by industry. Security recommendation: start with `k=3`, raise for medical/welfare/payroll-adjacent files.
- Whether support can accept customer CSV attachments. Security recommendation: no; require synthetic reproduction or customer-side generated redacted profile.
- Whether public source joins from CSV counterparties are in P0. Security recommendation: exact public IDs only; name-only joins are P1 with explicit review UI.
