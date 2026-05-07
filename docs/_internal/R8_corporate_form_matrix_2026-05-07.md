# R8 — 法人格 × 制度 matrix endpoint (M02)

| field | value |
|---|---|
| date | 2026-05-07 (JST) |
| operator | session_a — 梅田茂利 / Bookyou株式会社 |
| scope | new endpoint pair (REST × MCP) shipping 法人格 × 制度 matrix surface |
| LLM calls | 0 (pure SQL + `json_extract` over `am_program_eligibility_predicate_json`) |
| migration | none — pure read-only over existing `am_program_eligibility_predicate_json` (5,702 rows) + `programs` (jpintel.db) |
| billing | both endpoints ¥3/req metered (anonymous tier shares 3/日 IP cap) |

---

## 1. Why

Customers asking "私の法人格 (合同会社 / NPO / 学校法人 / 医療法人 / 個人事業主 等) で使える制度を絞りたい" + "個人事業主 NG 制度 を frame out したい" had to read each `programs` row's narrative manually. The 43 `am_target_profile` rows + 5,702 `am_program_eligibility_predicate_json` rows carry the form axis, but neither was previously surfaced as a single-call matrix.

Cohort revenue model (CLAUDE.md §"Cohort revenue model") names #5 補助金 consultant + #2 税理士 + #3 会計士 explicitly: consultants screen 顧問先 by 法人格 first because 個人事業主 / NPO / 学校法人 are categorically excluded from many 補助金/融資 lines. The matrix endpoint collapses that screen to a single ¥3/req call.

## 2. Surface

### 2.1 GET /v1/programs/by_corporate_form (¥3/req)
Query params:
```
form           — required, short code OR JP label
                 (kabushiki / goudou / goushi / goumei / npo /
                  ippan_shadan / koueki_shadan / ippan_zaidan /
                  koueki_zaidan / school / medical / cooperative /
                  sole / individual / foreign,
                  OR 株式会社 / 合同会社 / NPO法人 / 一般社団法人 /
                  学校法人 / 医療法人 / 個人事業主 等)
industry_jsic  — optional, 1 letter A-T (JSIC 大分類)
limit          — optional, 1..200, default 50
```

Response (envelope):
- `applied_filters` (resolved form_code + form_label + form_entity_class + industry_jsic + limit)
- `programs[]` (per row: unified_id, primary_name, tier, prefecture, authority_level, authority_name, program_kind, amount_max_man_yen, subsidy_rate, source_url, predicate_target_entity_types, predicate_industries_jsic, predicate_prefectures, predicate_funding_purposes, predicate_confidence, predicate_extraction_method)
- `count`
- `_disclaimer` (税理士法 §52 / 行政書士法 §1 fence)
- `_form_caveat` (predicate-axis precision note — corporation 1 値は会社法4種類を一括カバー)

Match semantics: a program passes when its predicate `$.target_entity_types` array contains a value compatible with `form` OR when the predicate carries no entity-type filter (treated as 'open to any 法人格'). Same logic on `$.industries_jsic` when `industry_jsic` supplied.

### 2.2 GET /v1/programs/{unified_id}/eligibility_by_form (¥3/req)
For one program, returns the explicit form-by-form verdict matrix (15 axes covering 株式会社 / 合同会社 / 合資会社 / 合名会社 / NPO / 一般社団 / 公益社団 / 一般財団 / 公益財団 / 学校 / 医療 / 事業協同組合 / 個人事業主 / 個人 / 外国法人).

Response (envelope):
- `unified_id`
- `program` (primary_name / tier / prefecture / program_kind / amount_max_man_yen / subsidy_rate / source_url)
- `matrix` keyed by form code, each entry `{label, entity_class, verdict, reason}`
  - verdict ∈ `{allowed, not_allowed, unspecified}`
  - reason cites the predicate field (e.g. `predicate の target_entity_types は sole_proprietor のみを対象としており、本法人格は含まれない`)
- `predicate_target_entity_types` (raw input echo for audit)
- `predicate_confidence`, `predicate_extraction_method` (`rule_based`/`llm_extracted`/`manual`)
- `_disclaimer`, `_form_caveat`

## 3. 15-axis closed enum (`_CORPORATE_FORMS`)

| code | JP label | am_target_profile.entity_class |
|---|---|---|
| `kabushiki` | 株式会社 | corporation |
| `goudou` | 合同会社 | corporation |
| `goushi` | 合資会社 | corporation |
| `goumei` | 合名会社 | corporation |
| `npo` | NPO法人 | npo |
| `ippan_shadan` | 一般社団法人 | association |
| `koueki_shadan` | 公益社団法人 | association |
| `ippan_zaidan` | 一般財団法人 | association |
| `koueki_zaidan` | 公益財団法人 | association |
| `school` | 学校法人 | school_corporation |
| `medical` | 医療法人 | medical_corporation |
| `cooperative` | 事業協同組合 | cooperative |
| `sole` | 個人事業主 | sole_proprietor |
| `individual` | 個人 | individual |
| `foreign` | 外資系・外国法人 | foreign |

NFKC + JP-label-aliasing on input so 全角株式会社 / 株式会社 / kabushiki all resolve identically.

## 4. Predicate-axis honesty

The predicate corpus auto-extracts a coarse axis: it distinguishes `corporation` / `sole_proprietor` / `npo` / `association` / etc, but **does not** distinguish 株式会社 vs 合同会社 vs 合資会社. A program that lists `["corporation"]` accepts every 会社法 法人 form unless 公募要領 separately excludes one.

`_form_caveat` surfaces this verbatim on every 2xx body so callers cannot over-claim "this 制度 is 合同会社-only". Sub-form distinctions (e.g. 公募要領 says 株式会社のみ) live in `programs.enriched_json` and are out of scope for the matrix axis.

The form-to-predicate-value expansion lives in `_FORM_TO_PREDICATE_VALUES`:
- `corporation` / `法人` / `株式会社` → match for kabushiki / goudou / goushi / goumei (the corpus uses any of these as a coarse positive signal)
- `npo` / `NPO` / `NPO法人` / `特定非営利活動法人` → match for npo
- `school_corporation` / `学校法人` → match for school
- `medical_corporation` / `医療法人` → match for medical
- ... see `src/jpintel_mcp/api/corporate_form.py:_FORM_TO_PREDICATE_VALUES` for full mapping

## 5. Files shipped

| path | purpose |
|---|---|
| `src/jpintel_mcp/api/corporate_form.py` | REST router (2 routes) — pure SQLite + `json_extract` |
| `src/jpintel_mcp/mcp/autonomath_tools/corporate_form_tools.py` | MCP twin (2 tools: `programs_by_corporate_form_am` + `program_eligibility_by_form_am`), shared core impl |
| `src/jpintel_mcp/api/main.py` | router registered BEFORE `programs_router` so `/v1/programs/by_corporate_form` and `/v1/programs/{unified_id}/eligibility_by_form` win the strict-query middleware first-FULL-match walk against the catchall `/v1/programs/{unified_id}` |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` | added `corporate_form_tools` import |
| `tests/test_corporate_form_endpoint.py` | 15 tests covering envelope shape, JP label normalisation, JSIC filter, 422 / 404 / 200 paths, sole-only program excludes 株式会社, no-target-entity-types marks all axes allowed, anon quota |
| `docs/openapi/v1.json` | regenerated — 219 paths total (was 217) |

## 6. MCP tool registration

`AUTONOMATH_CORPORATE_FORM_ENABLED=1` (default ON). Two tools at `_READ_ONLY` annotations:
- `programs_by_corporate_form_am(form, industry_jsic=None, limit=50)`
- `program_eligibility_by_form_am(unified_id)`

Tool count post-M02: 139 → **141** (manifest hold-at-139 still applies — count bump deferred to next intentional manifest release).

## 7. Validation

| gate | result |
|---|---|
| `pytest tests/test_corporate_form_endpoint.py` | 15/15 PASS |
| `ruff check` (new files + __init__.py) | clean |
| `mypy --strict` (new files) | 0 errors |
| OpenAPI export | 2 new paths surface |
| MCP `list_tools()` | 2 new tool names registered |
| Route ordering vs `/v1/programs/{unified_id}` catchall | corporate_form_router first FULL match — verified by walking `app.routes` |

## 8. Constraints honoured

- **NO LLM call** anywhere in code path (pure SQL + `json_extract` + Python).
- **¥3/req metered**, single billing event per call, no tier SKU.
- **AnonIpLimitDep** mounted on the router so the 3/日 anon-IP cap applies identically to programs_router siblings.
- **§52 + 行政書士法 §1 disclaimer** on every 2xx body via `_DISCLAIMER`; predicate-axis caveat via `_form_caveat`.
- **Audit seal** via `attach_seal_to_body` on paid responses (no-op for anon, mirrors api/houjin.py posture).
- **Read-only** autonomath.db open (`mode=ro` + `PRAGMA query_only=1`).
- **No cross-DB JOIN** — predicate read from autonomath.db, program metadata hydrated from jpintel.db separately. Honours CLAUDE.md "no ATTACH / cross-DB JOIN" rule.

## 9. Honest gaps

- Sub-corporation forms (株式会社 vs 合同会社 vs 合資会社) collapse to the same predicate axis. Surfaced verbatim in `_form_caveat`.
- `am_target_profile` 43-row taxonomy is referenced in code comments but the matrix uses the predicate axis directly. Joining `am_target_profile` was considered but rejected — the predicate axis is the SOT for per-program eligibility; the taxonomy is purely the closed enum that defines valid form codes.
- Programs with no predicate row (out of 14,472 total) cannot be matched — they fall back to the catchall `/v1/programs/{unified_id}` 404 path.
