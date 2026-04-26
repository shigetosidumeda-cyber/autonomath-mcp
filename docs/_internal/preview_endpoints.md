# Preview / Roadmap Endpoints

This page documents the **contract-only scaffolds** for three future endpoints
(legal / accounting / calendar). These routes exist in code today but are
**not enabled by default**. They ship behind a feature flag so we can:

1. Publish a **credible future contract** that SDK codegen, MCP clients, and
   marketing pages can reference before the implementation is ready.
2. Keep the public OpenAPI export (`docs/openapi/v1.json`) **clean** — no
   unimplemented routes leaking into customer surface area.
3. Give W5-W8 ingest lanes a concrete **data shape target** to build toward.

## Feature flag

```bash
# default (stable)
JPINTEL_ENABLE_PREVIEW_ENDPOINTS=false

# publish the contract
JPINTEL_ENABLE_PREVIEW_ENDPOINTS=true
```

Behavior:

| flag   | calling a preview route       | OpenAPI export                      |
| ------ | ----------------------------- | ----------------------------------- |
| off    | `404 Not Found` (unmounted)   | excluded                            |
| on     | `501 Not Implemented` + body  | included (roadmap-as-contract)      |

`501` is the standards-compliant "planned, not yet implemented" code — a
clearer signal than `404` that the endpoint will exist.

## Endpoints

### 1. `GET /v1/legal/items` — target W6 (2026-05-27)

Resolve a 法令名 + 条文 to the canonical 法律条文 text and its last revision
date.

- **Source (future):** e-Gov 法令 API
  (https://elaws.e-gov.go.jp/api/1/)
- **Query params:** `law`, `article`, `subject` (optional)
- **Response shape:**
  ```json
  {
    "law_name": "労働基準法",
    "law_number": "昭和二十二年法律第四十九号",
    "article_number": "15",
    "article_text": "使用者は、労働契約の締結に際し、労働者に対して賃金、労働時間その他の労働条件を明示しなければならない。...",
    "revision_date": "2024-04-01",
    "source_url": "https://elaws.e-gov.go.jp/document?lawid=322AC0000000049",
    "fetched_at": "2026-04-23T10:00:00Z"
  }
  ```
- **501 body:** `{"detail": "endpoint under development, target W6", "eta": "2026-05-27"}`

### 2. `POST /v1/accounting/invoice-validate` — target W7 (2026-06-10)

Validate an インボイス適格請求書発行事業者登録番号 against 国税庁's public
Web-API.

- **Source (future):** 国税庁 Web-API
  (https://www.invoice-kohyo.nta.go.jp/web-api/)
- **Body:** `{"invoice_number": "T1234567890123"}` (14 chars: `T` + 13 digits)
- **Response shape:**
  ```json
  {
    "invoice_number": "T1234567890123",
    "is_registered": true,
    "registration_date": "2023-10-01",
    "company_name": "株式会社サンプル",
    "company_kana": "カブシキガイシャサンプル",
    "address": "東京都千代田区...",
    "last_synced": "2026-04-23T10:00:00Z"
  }
  ```
- **501 body:** `{"detail": "endpoint under development, target W7", "eta": "2026-06-10"}`

### 3. `GET /v1/calendar/deadlines` — target W8 (2026-06-24)

Return upcoming submission deadlines for a given program.

- **Source:** existing `enriched.C_procedure.submission_deadline` if
  populated, plus a crawl of the program's `source_url` for 公募締切 detection.
- **Query params:** `program_id`, `months_ahead` (default 3, 1..12)
- **Response shape:**
  ```json
  {
    "program_id": "UNI-...",
    "deadlines": [
      {
        "round": "第5回",
        "open_date": "2026-05-01",
        "close_date": "2026-06-15",
        "submission_method": "jGrants",
        "confidence": 0.92
      }
    ]
  }
  ```
- **501 body:** `{"detail": "endpoint under development, target W8", "eta": "2026-06-24"}`

## OpenAPI export

```bash
# stable (default — what ships to customers)
python scripts/export_openapi.py

# roadmap-as-contract (for prospects / partner previews)
python scripts/export_openapi.py --include-preview --out docs/openapi/v1_preview.json
```

See also: `docs/GENERALIZATION_ROADMAP.md` §1 row (c) — the W8 exit criterion
"legal / accounting / calendar の 3 endpoint が public".
