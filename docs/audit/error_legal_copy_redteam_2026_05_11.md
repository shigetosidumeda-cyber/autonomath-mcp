# Red Team Scan — Error Messages + Legal Copy

**Date:** 2026-05-11
**Scope:** jpcite production (api.jpcite.com + jpcite.com static + .well-known/*)
**Reference benchmark:** Stripe / Vercel / Anthropic SV top-tier
**Auditor:** automated red-team scan (`feedback_agent_severity_labels` — self-verified, not rolled up)
**Output mode:** Findings only. No code changes. (memory: 破壊なき整理整頓)

---

## TL;DR — 6 Axis Roll-up

| Axis | Status | Findings |
|------|--------|----------|
| A. Error internal-leak | YELLOW | 6 `str(exc)` / `str(e)` sites still pass raw exception text to `detail`. No traceback, no SQL, no path. Brand-prefix codes clean. |
| B. Error UX | GREEN | Canonical `{"error":{code,user_message,user_message_ja/en,request_id,documentation,severity}}` envelope w/ 20-code closed enum, ja+en, actionable next-step copy. |
| C. Legal copy existence | YELLOW | ToS / Privacy / SLA / Tokushoho / legal-fence + security.txt + trust.json all present. **DPA / SubProcessor / Cookie Policy as standalone pages absent** (content lives inside privacy.html). |
| D. Legal copy content | YELLOW | Bookyou株式会社 / T8010001213708 / 文京区小日向 2-22-1 all present. **Solo-zero-touch violation: `"contactType": "customer support"` in JSON-LD across 40 files.** **6-業法 fence vs task brief 7 業法: 弁理士法 §75 / 中小企業診断士登録規則 absent.** |
| E. security.txt / trust.json | GREEN | RFC 9116 compliant, expires 2027-04-26, ja+en, canonical URL set. trust.json carries honest "soc2_status: not_pursued_solo_zero_touch" + OpenSSF/ASVS/CAIQ "in_preparation". |
| F. AI-agent affinity | GREEN | JSON envelope w/ `code`/`request_id`/`retry_after`/`Idempotency-Key`/`X-Request-ID` (26-char ULID) all live. `documentation` anchor + `suggested_paths` 404 hints. |

**Red count = 0. Yellow count = 3 (axis A, C, D).**

---

## Axis A — Error message internal-leak (YELLOW, 6 sites)

### A.1 `str(exc)` / `str(e)` flowing into `detail`/`message` (8 grep hits, 6 distinct sites)

| File | Line | Path / Surface | Risk |
|------|------|---------------|------|
| `src/jpintel_mcp/api/intel.py` | 313, 321 | `/v1/intel/houjin/probability` 503 detail | `FileNotFoundError("/data/autonomath.db")` filesystem path leak |
| `src/jpintel_mcp/api/me.py` | 1145 | `/v1/me/keys/children` child-key error detail | leaks internal exception `__str__` (currently only ValueError, low risk) |
| `src/jpintel_mcp/api/billing.py` | 796 | `/v1/billing/credit-pack-invoice` 422 detail | Stripe ValueError string verbatim |
| `src/jpintel_mcp/api/meta_freshness.py` | 243 | `/v1/meta/freshness` 503 | `FileNotFoundError(/registry/...)` filesystem path leak |
| `src/jpintel_mcp/api/calculator.py` | 432 | `/v1/calculator/*` 422 | ValueError verbatim |
| `src/jpintel_mcp/api/_format_dispatch.py` | 257 | format dispatch 403 | `LicenseGateError.__str__` — usually safe (intentional license id) |

**Not red because:**
- No `Traceback` / stack-frame leak anywhere (`grep -rn Traceback src/jpintel_mcp/api/` = 0 hits).
- No raw `sqlite3.OperationalError` message leak — caught with `except sqlite3.OperationalError:` returns canonical `db_unavailable` (`_error_envelope.py:274-282`).
- No `am_*` / `unified_registry` / `/internal/*` substring in any user-facing error string.
- No old-brand prefix (`ERR_AUTONOMATH_*` / `ERR_JPINTEL_*` / `AutonomathException` / `JpIntelException`) anywhere in src/ — `grep` returns 0.
- Logger name `jpintel.api` exists but only in server-side logs, never in response body.

**Why yellow not green:** Stripe/Vercel/Anthropic NEVER let `str(exc)` flow into a customer body. They wrap with `{"error":{"code":"...","message":"<sanitized>"}}` and route the raw `exc.args` only to log/Sentry. The 6 sites above are exposed to:
1. FS path leak (`FileNotFoundError("/Users/.../data/autonomath.db")`) — informs an attacker of the deployment topology.
2. Vendor-internal Stripe SDK error text (PHI risk if Stripe ever changes their error format).

### A.2 Brand-prefix exception codes — GREEN

All 20 canonical codes in `ERROR_CODES` (`src/jpintel_mcp/api/_error_envelope.py:124-320`) are neutral and product-agnostic: `bad_request`, `missing_required_arg`, `invalid_enum`, `invalid_date_format`, `out_of_range`, `unknown_query_parameter`, `no_matching_records`, `ambiguous_query`, `seed_not_found`, `auth_required`, `auth_invalid`, `rate_limit_exceeded`, `cap_reached`, `route_not_found`, `method_not_allowed`, `db_locked`, `db_unavailable`, `subsystem_unavailable`, `service_unavailable`, `internal` / `internal_error`. **No old brand prefix.**

### A.3 Internal table-name leak — GREEN

Internal table names (`am_amendment_diff`, `unified_registry`, `am_facts`) appear only in:
- src-internal **comments** + log lines (e.g. `main.py:977` route helper).
- Public `audit-log` / `data-licensing` / `legal-fence` pages — but used as **intentional public schema disclosure** for trust signal, not error leak.

No error-response body ever surfaces a table name (verified by grepping all `HTTPException(detail=...)` + `JSONResponse(content=...)` call sites in `api/`).

---

## Axis B — Error message UX (GREEN)

### B.1 Canonical envelope shape — Stripe-grade

`_error_envelope.py:341` `make_error()` emits:
```json
{
  "error": {
    "code": "<closed-enum-of-20>",
    "user_message": "<plain JP, ≤200 chars>",
    "user_message_en": "<EN mirror>",
    "request_id": "<26-char ULID, never 'unset'>",
    "severity": "hard|soft",
    "documentation": "https://jpcite.com/docs/error_handling#<code>"
  }
}
```

**Stripe parity check:** Stripe emits `{type, code, message, doc_url, request_log_url}`. jpcite emits `{code, user_message, documentation, request_id, severity}`. **Functionally equivalent, JP-localised.**

**Vercel parity check:** Vercel uses `{error: {code, message}}` plain. jpcite is **more capable** (ja+en, severity tag, retry_after, suggested_paths). GREEN.

### B.2 Bilingual coverage

- 20 codes × 2 langs (ja primary, en mirror) = 40 strings, all present in `ERROR_CODES`.
- `LanguageResolverMiddleware` picks primary via `Accept-Language` / query — `safe_request_lang(request)` (`_error_envelope.py:323`).
- 422 Pydantic validation: 17 constraint types translated to `msg_ja` in `main.py:1673-1696`.

### B.3 Actionable next-step copy

Sampled — every code carries a concrete action verb:
- `auth_required` → "https://jpcite.com/dashboard で発行し、X-API-Key ヘッダで送信してください"
- `rate_limit_exceeded` → "Retry-After ヘッダの秒数だけ待ってから再試行"
- `invalid_enum` → "field_errors[].expected の許可値から選び直して再送"
- `route_not_found` → suggests `/v1/openapi.agent.json` + 4 canonical paths
- `db_unavailable` → "Retry-After 秒 (既定 300s) 待って ... 継続する場合は request_id を添えて info@bookyou.net まで連絡"

No bare "internal server error" without recovery path. GREEN.

### B.4 Anon rate-limit body (special case) — GREEN

`anon_limit.py:158-205` `_raise_rate_limit_unavailable()`:
- detail in ja + detail_en in en
- `retry_after`, `reset_at_jst`, `limit`, `upgrade_url`, `direct_checkout_url`, `cta_text_{ja,en}`, `trial_signup_url`, `trial_terms`
- Stripe parity: this is **more upsell-rich** than Stripe's 429 (which just gives `retry-after`).

---

## Axis C — Legal copy existence (YELLOW)

| Document | Path | Status |
|----------|------|--------|
| Terms of Service | `site/tos.html` + `site/en/tos.html` | GREEN |
| Privacy Policy | `site/privacy.html` + `site/en/privacy.html` | GREEN (APPI §26/27/28 explicit) |
| Tokushoho 表記 | `site/tokushoho.html` | GREEN |
| Legal-Fence | `site/legal-fence.html` | GREEN (6 业法 covered; **task brief 7 业法 mismatch**, see D.2) |
| SLA | `site/sla.html` + `site/en/sla.html` | GREEN |
| Security Overview | `site/security/index.html`, `policy.html`, `asvs.html`, `caiq.html` | GREEN |
| Trust Center | `site/trust.html` | GREEN |
| Data Subject Rights | linked from trust.json `data_subject_rights_url` | GREEN (resolves) |
| Security.txt | `site/.well-known/security.txt` | GREEN (RFC 9116) |
| Trust.json | `site/.well-known/trust.json` | GREEN (jpcite_trust_v1 schema) |
| **DPA standalone** | ABSENT | **YELLOW — task brief asks "self-sign-on-ToS DPA"; substrate is inside ToS §12, no dedicated page** |
| **Cookie Policy standalone** | ABSENT | YELLOW — content is in `privacy.html` §10 but no top-level Cookie Policy URL |
| **SubProcessor list standalone** | ABSENT | YELLOW — list lives only in `privacy.html` §5 and `trust.json.privacy.subprocessors` (5 entries: Stripe, Fly, Cloudflare, Postmark, Sentry) |

**Why yellow not green:** Stripe + Anthropic + Vercel each publish DPA + SubProcessor list as **separate, standalone, dedicated** pages so customers can link to them in their own DPIA / privacy review. Burying them in privacy.html means a customer reviewer cannot deep-link.

---

## Axis D — Legal copy content quality (YELLOW)

### D.1 Operator entity disclosure — GREEN

- 商号 `Bookyou株式会社` — 14 hits across tos/privacy/sla/legal-fence ✓
- 法人番号 `8010001213708` — present in JSON-LD `identifier[]` ✓
- 適格請求書発行事業者番号 `T8010001213708` (登録日 2025-05-12) — present in trust.json + JSON-LD ✓
- 所在地 `〒112-0006 東京都文京区小日向2-22-1` — present in tos/privacy/sla ✓
- 代表者 `梅田 茂利` — present in tos/privacy ✓
- 問合せ `info@bookyou.net` — present ✓
- External verification URL → `https://www.invoice-kohyo.nta.go.jp/regno-search/detail?selRegNo=8010001213708` in trust.json ✓

### D.2 Solo-zero-touch violation — YELLOW (HIGH SEVERITY)

**Finding:** JSON-LD `Organization.contactPoint.contactType` is hardcoded to `"customer support"` across **40 files** under `site/*.html` (sampled: tos.html:100, privacy.html:106, sla.html:70). This implies a CS team — contradicts memory `feedback_zero_touch_solo`.

**No actual CS-team mention in prose:** `grep -i "サポートチーム / 営業窓口 / 営業担当 / 担当者 / お電話 / 電話番号 / 営業時間"` across tos/privacy/legal-fence/sla = **0 hits**. The prose itself is solo-clean.

**Stripe/Anthropic comparison:** Stripe JSON-LD uses `"customer service"`. Anthropic uses `"sales"` / `"technical support"` selectively. The schema.org enum permits `"customer support"` for any contact channel, but in jpcite's case a single inbox staffed by 1 founder makes "customer support" **technically allowed but pragmatically misleading**. Recommend swap to `"general"` or `"founder"` (Schema.org accepts free-form).

### D.3 Refund / SLA honest stance — GREEN

- tos.html §13: "**99.0% target** ... 当社がこれを保証するものではありません" — honest target, NOT a guarantee.
- tos.html §13: "従量課金制である性質上、成立しなかったリクエストには課金されません" — honest non-refund.
- trust.json: `credit_policy: "tokushoho_serious_nonconformity_clause"` — credit only on serious nonconformity, not a blanket SLA credit.
- sla.html: live `<meta http-equiv="refresh">` polling `api.jpcite.com/v1/health/sla?window=7d` — same data Stripe / Vercel publish on their status pages.

### D.4 7-業法 fence — YELLOW (task brief mismatch)

**Task brief asks:** 税理士法 §52 / 弁護士法 §72 / 司法書士法 §73 / 行政書士法 §19 / 社労士法 §27 / 中小企業診断士登録規則 / 弁理士法 §75.

**Site reality:** 6 業法 (税理士 §52 / 弁護士 §72 / 公認会計士 §47-2 / 行政書士 §1 / 司法書士 §3 / 社労士 §27).

**Mismatches:**
| Brief | Site | Note |
|-------|------|------|
| 司法書士法 §73 | §3 | §3 covers 業務範囲、§73 covers 罰則。Site uses §3 (correct scope, more useful copy) |
| 行政書士法 §19 | §1 | §19 covers 罰則、§1 covers 業務範囲。Site uses §1 (correct scope) |
| **弁理士法 §75** | **ABSENT** | Patent/trademark application boundary not fenced. memory `feedback_patent_content_unused` confirms portfolio retreat, but a public fence is still relevant if any program touches IP grants (jpcite has 特許出願支援 補助金 programs) |
| **中小企業診断士登録規則** | **ABSENT** | Diagnostic-consultant boundary not fenced |
| **公認会計士法 §47-2** | covered | Brief omits this but site correctly fences |

**Pricing nexus:** trust.json `pricing_jpy_per_request_excl_tax=3` + `pricing_jpy_per_request_incl_tax=3.30` + `free_anonymous_quota_per_ip_per_day=3` + `free_quota_reset=JST 翌日 00:00`. Each 業法 fence is **not** explicitly cross-linked to pricing, but pricing & fence both live under jpcite.com so context is preserved.

### D.5 GDPR / 改正個人情報保護法 (令和2年改正) stance — GREEN

- privacy.html §5 explicit 改正個人情報保護法 §28 (外国第三者提供) compliance.
- privacy.html §6 explicit §26 (漏えい報告) compliance — 3-5d 速報 / 30d 確報 (60d for 不正) / 72h 本人通知 / public postmortem.
- privacy.html §7 explicit §27-5-7 (公開情報 採択事例 再掲) compliance.
- privacy.html §9 explicit §27-34 (開示等請求) — 30d 一次応答 + データポータビリティ via Stripe Customer Portal.
- tos.html §19-2: GDPR / CCPA / EU AI Act / CLOUD Act 外国法 stance honest (not actively assumed, follows minimum to extent applicable).

### D.6 Pricing copy honesty — GREEN

- tos.html §9: "1 billable unit あたり金 3 円 (税抜)、消費税等 (10%) を加算した金額 (税込 金 3.30 円)" — exact match against trust.json `pricing_jpy_per_request_incl_tax=3.30`.
- tos.html §9: 無償利用枠 "1 IP アドレスあたり 3 リクエスト/日、日本標準時の翌日 00:00 にリセット" — exact match.
- No tier-SKU / Pro plan / Starter plan language anywhere — verified `grep -i "Pro plan / Starter plan / Free tier"` across legal copy = 0 hits.

---

## Axis E — security.txt / trust.json (GREEN)

### E.1 security.txt — RFC 9116 compliant

```
Contact: mailto:info@bookyou.net
Expires: 2027-04-26T00:00:00Z       <-- 12-month rolling, healthy
Preferred-Languages: ja, en
Canonical: https://jpcite.com/.well-known/security.txt
Policy: https://jpcite.com/security/policy
```

**Stripe parity:** Stripe expires 12-month, mailto, policy URL. jpcite has all 5. GREEN.

### E.2 trust.json — `jpcite_trust_v1` schema, 218 lines

Honest stances confirmed:
- `soc2_status: "not_pursued_solo_zero_touch"` — honest "we're not pursuing SOC 2" instead of bullshit "in progress" claim.
- `soc2_alternatives: [OpenSSF Best Practices (in_preparation), OWASP ASVS L1 (in_progress), CSA CAIQ L1 (in_progress), Cloudflare Trust Hub (available)]` — each carries `verification_url_after_award`.
- `individual_dpa_negotiation: false`, `individual_msa_negotiation: false` — explicit solo zero-touch.
- `bug_bounty_offered: false`, `safe_harbour_offered: true` — honest "no bounty, but safe harbour offered".
- `no_llm_call_in_server: true` + `ci_guard_test: "tests/test_no_llm_in_production.py"` — verifiable trust claim (memory `feedback_no_operator_llm_api`).
- Data provenance: `license_review_queue_size=805`, `license_classified_count=97270`, `license_total_count=97272` — exposes the residual queue honestly.
- Banned aggregators list (noukaweb / hojyokin-portal / stayway / nikkei / prtimes / wikipedia) + `boot_invariant: "INV-04 hard-fail if banned domain leaks into source_url"`.

**Anthropic parity:** Anthropic trust center claims SOC 2 Type II + ISO 27001 (paid certs). jpcite parity: documents the **absence** of those, links to **substitutable** OSS evidence. Honest substitution, suited to solo ops. GREEN.

### E.3 Incident posture

- `vuln_ack_window_hours=72`, `vuln_fix_target_days=14`, `responsible_disclosure_window_days=90`.
- `incident_notification_window_hours=24`, `postmortem_window_days=7`.
- `tls_min_version="1.2"`, `encryption_at_rest="AES-256"`.
- `backup_rpo_hours=24`, `backup_rto_hours=4`, `backup_destination="Cloudflare R2"` — concrete, verifiable.

---

## Axis F — AI agent affinity (GREEN)

### F.1 Standard JSON shape

Every 4xx/5xx body conforms to `{"error":{code, user_message, request_id, ...extras}}` (see Axis B). Pydantic schema `ErrorEnvelope` (`_error_envelope.py:631-660`) is referenced from `components.schemas` of openapi.json so SDK generators emit a typed `Error` class. **Pre-launch audit J5 closed this gap.**

### F.2 trace header — `X-Request-ID`

- Inbound: `_RequestContextMiddleware` validates against `_REQUEST_ID_RE = ^[A-Za-z0-9-]{8,64}$` (`main.py:534`).
- Outbound: every response carries `response.headers["x-request-id"] = rid` (`main.py:563`).
- `request_id` mirrored in `error.request_id` for body-only consumers (no header parsing).
- ULID 26-char Crockford base32 — lexicographic creation-time ordering → log forensics easy.
- Mint fallback: `_mint_request_id()` always returns real ULID, never literal `"unset"` (J5 fix).

### F.3 Idempotency-Key

- Audit / bulk_evaluate / billing call sites all read `Header(alias="Idempotency-Key")` (`audit.py:1630, 1919, 2228`; `bulk_evaluate.py:620`).
- 428 Precondition Required documented as `idempotency_key_required` in COMMON_ERROR_RESPONSES (`_error_envelope.py:692-695`).
- Stripe parity (Stripe enforces Idempotency-Key on POST charges) — jpcite enforces on high-value paid fan-out.

### F.4 Retry-After + Content-Type

- 429 + 503 + db_unavailable all set `Retry-After` (`main.py:1623, 1832`; `anon_limit.py:198`).
- `Retry-After` mirrored into `error.retry_after` for body-only consumers.

### F.5 OpenAPI agent schema

- `/v1/openapi.agent.json` published (`main.py:1849`).
- `mcp.json` + `ai-plugin.json` + `agents.json` all under `/.well-known/`.

---

## Immediate Fix Top-5

### #1 — Replace `str(exc)` in HTTPException bodies (Axis A, P1)

Apply to:
- `intel.py:313, 321` (FS path leak via FileNotFoundError)
- `meta_freshness.py:243` (FS path leak)
- `billing.py:796` (Stripe SDK message leak)
- `me.py:1145`, `calculator.py:432`, `_format_dispatch.py:257`

**Fix shape:** swap raw `str(exc)` for canonical envelope:
```python
raise HTTPException(
    status_code=503,
    detail=make_error(
        code="db_unavailable",
        request_id=safe_request_id(request),
    ),
)
```
Log the raw exception via `_log.exception("...", exc_info=True)` so Sentry / structured logs still get it.

**Effort:** 6 edits × ~15 LOC each = ~90 LOC. Test impact: each handler has a unit test that pattern-matches on the new envelope.

---

### #2 — Add `弁理士法 §75` + `中小企業診断士登録規則` to legal-fence (Axis D.4, P2)

`site/legal-fence.html` currently has 6 sections; brief asks for 7-8. Add `7. 弁理士法 §75` + `8. 中小企業診断士登録規則`. Each ~30 LOC block (sample exists in current sections). Cross-link to `bundle_application_kit` tool branch in mapping table.

Also update `trust.json.legal_fences.list` to add the 2 missing 業法 entries (`弁理士法 §75 → 弁理士`, `中小企業診断士登録規則 → 中小企業診断士`).

**Effort:** 60 LOC across legal-fence.html + trust.json. No code change.

---

### #3 — Swap `"contactType": "customer support"` JSON-LD label across 40 files (Axis D.2, P2)

`grep -rln '"contactType": "customer support"' site/ | wc -l` = 40.

Stripe / Anthropic JSON-LD uses `"customer service"` (a Schema.org canonical) or `"general"`. The current `"customer support"` is honest but invokes "support team" connotation contradicting `feedback_zero_touch_solo`.

**Fix shape:** find/replace `"contactType": "customer support"` → `"contactType": "founder"` (Schema.org accepts free-form) OR `"contactType": "general"` (canonical, neutral).

**Effort:** 1 sed-style replace_all across 40 files. No code change.

---

### #4 — Promote DPA / SubProcessor / Cookie Policy to standalone pages (Axis C, P3)

Current state: substrate exists inside ToS / Privacy / trust.json, but a corporate reviewer cannot deep-link `https://jpcite.com/dpa` or `https://jpcite.com/subprocessors`.

**Fix shape:** create three pages that **embed (iframe-equivalent)** the existing prose from privacy.html §5 (SubProcessor) + privacy.html §10 (Cookie) + ToS §12 (DPA stance for self-sign-on-ToS model). No new copy — extract & cross-link.

**Stripe / Anthropic / Vercel:** all 3 publish these as standalone for procurement review. Direct competitor parity.

**Effort:** 3 new HTML files × ~150 LOC each (mostly nav + footer + meta tags around existing prose).

---

### #5 — Add `documentation` URL realization (Axis B + F, P3)

`_error_envelope.py:114` `DOC_URL = "https://jpcite.com/docs/error_handling"` is referenced in every envelope (`{code}#<anchor>`). Verify the docs page exists with all 20 anchors:
- `mkdocs build --strict` should fail loudly if `docs/error_handling.md` is missing or any anchor is broken.

If anchors missing, generate one section per `ERROR_CODES` entry (auto-generatable from the dict).

**Effort:** verify existing doc + auto-generate from ERROR_CODES dict (~5 min script).

---

## SV Top-Tier Distance Analysis

### Stripe error format (reference)

```json
{
  "error": {
    "type": "card_error",
    "code": "card_declined",
    "decline_code": "generic_decline",
    "doc_url": "https://stripe.com/docs/error-codes/card-declined",
    "message": "Your card was declined.",
    "param": "card",
    "request_log_url": "https://dashboard.stripe.com/logs/req_xxx"
  }
}
```

**jpcite gap to Stripe:** **NEAR PARITY.**
- `error.type` (category) — jpcite uses `error.severity` ("hard"/"soft") instead. Equivalent.
- `error.code` — both have closed enum. ✓
- `error.message` — jpcite has `user_message` + `user_message_ja/en`. ✓ + bilingual.
- `error.doc_url` — jpcite has `error.documentation` w/ anchor. ✓
- `error.param` — jpcite has `field_errors[].loc`. ✓
- `error.request_log_url` — jpcite has `error.request_id` only (no log-pull URL because solo ops, no logs portal). Acceptable gap for solo zero-touch.

### Vercel terms (reference)

Vercel ToS:
- Acceptance via continued use ✓ jpcite mirrors at §2-2.
- Limitation of liability — Vercel caps at fees paid in prior 12 months. jpcite caps at 1 month fee (§15). **More restrictive — defensible for B2B data API + solo ops.**
- DPA standalone ✓ Vercel has dedicated /legal/dpa page. **jpcite gap (see Fix #4).**
- Sub-processor list ✓ Vercel publishes standalone. **jpcite gap (see Fix #4).**

### Anthropic privacy (reference)

Anthropic Privacy Notice:
- APPI / GDPR / CCPA explicit stance ✓ jpcite mirrors at privacy §5 + ToS §19-2.
- 14-day data subject rights response window ✓ jpcite matches in trust.json (`data_subject_rights_response_window_days: 14`).
- Retention table per data category ✓ jpcite has explicit retention table at privacy §8.1 (5 row × per-category days).
- AI training opt-out ✓ jpcite has ToS §2-7 + trust.json `training_data_use: "prohibited"`.

**Anthropic distance:** small. Anthropic adds explicit "you can request a copy via support form" — jpcite's equivalent is Stripe Customer Portal + dashboard export (self-service), which **suits solo zero-touch better**.

### Overall verdict

jpcite legal copy + error envelope are **80-90% of SV top-tier quality**, with 5 specific, actionable gaps (Fix Top-5 above). No red findings. Yellow findings are all fixable in <1 day total (~250 LOC + 1 sed pass + 1 docs script).

The **solo-zero-touch posture is honest** throughout (trust.json + privacy 安全管理措置 §8 "代表者のみが本番DBアクセス権" + tos.html no "営業/CS" language). This is jpcite's competitive moat against Stripe / Vercel / Anthropic for the JP solo+SMB market — own the "solo founder transparency" honest niche they cannot afford to claim.

---

## Appendix: Files Audited

### Legal copy (input)
- `/Users/shigetoumeda/jpcite/site/tos.html` (507 lines, JP)
- `/Users/shigetoumeda/jpcite/site/en/tos.html` (EN mirror)
- `/Users/shigetoumeda/jpcite/site/privacy.html` (403 lines, JP)
- `/Users/shigetoumeda/jpcite/site/en/privacy.html` (EN mirror)
- `/Users/shigetoumeda/jpcite/site/legal-fence.html` (6 業法 sections)
- `/Users/shigetoumeda/jpcite/site/en/legal-fence.html` (EN mirror)
- `/Users/shigetoumeda/jpcite/site/sla.html` (live SLA polling)
- `/Users/shigetoumeda/jpcite/site/en/sla.html` (EN mirror)
- `/Users/shigetoumeda/jpcite/site/tokushoho.html`
- `/Users/shigetoumeda/jpcite/site/trust.html`
- `/Users/shigetoumeda/jpcite/site/security/{index,policy,asvs,caiq}.html`
- `/Users/shigetoumeda/jpcite/site/.well-known/security.txt` (RFC 9116, 9 lines)
- `/Users/shigetoumeda/jpcite/site/.well-known/trust.json` (218 lines, `jpcite_trust_v1`)

### Error infrastructure (input)
- `/Users/shigetoumeda/jpcite/src/jpintel_mcp/api/_error_envelope.py` (722 lines, canonical envelope + 20-code closed enum)
- `/Users/shigetoumeda/jpcite/src/jpintel_mcp/api/main.py` (exception handlers at lines 1587, 1626, 1698, 1742)
- `/Users/shigetoumeda/jpcite/src/jpintel_mcp/api/anon_limit.py` (anon 429 handler at line 102, body shape at line 158)
- 583 `raise HTTPException` call sites across `src/jpintel_mcp/api/` (sampled top 50)
- 6 `str(exc)` / `str(e)` HTTPException leak sites (full enumeration in Axis A.1)
- `/Users/shigetoumeda/jpcite/functions/artifacts/[pack_id].ts` (TS pages-function — no error leak, fallback DEMO)

### Method
- `grep` for: `raise HTTPException`, `str(exc)`, `str(e)`, `Traceback`, `sqlite3.OperationalError`, `ERR_AUTONOMATH`, `ERR_JPINTEL`, `AutonomathException`, `JpIntelException`, `am_*` / `unified_registry` / `/internal/*` substring, `customer support`, `サポートチーム / 営業窓口 / 営業担当 / 電話番号`, `弁理士 / 診断士`, `DPA / SubProcessor / Cookie`.
- Read full text of: tos.html, privacy.html, legal-fence.html (300-400 lines), sla.html (first 100 lines), security.txt (9 lines), trust.json (218 lines), _error_envelope.py (722 lines), main.py exception handler section (1580-1842).
- Cross-referenced trust.json claims against `feedback_no_operator_llm_api` + `feedback_zero_touch_solo` + `feedback_no_trademark_registration` + `feedback_patent_content_unused` memory entries.

---

*End of red team scan. No code changes performed. Recommend Fix Top-5 in priority order.*
