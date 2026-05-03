"""CSV bulk eligibility evaluation for 補助金コンサル fan-out (consultant
trigger #1 of the trio).

Endpoint:
    POST /v1/me/clients/bulk_evaluate

Why a separate router (not folded into client_profiles.py):
    * client_profiles.py owns CRUD on the consultant's 顧問先 metadata
      (FREE, no metering). This router owns the metered batch evaluation
      surface where the consultant uploads a CSV of 顧問先 and gets
      eligibility ranking for each one.
    * Distinct billing posture: bulk_evaluate is metered ¥3 × N rows
      (project_autonomath_business_model). client_profiles CRUD is FREE.

Flow:
    1. Consultant POSTs multipart/form-data with `file` (CSV) and optional
       form fields: `program_filter` (default "all"), `commit` (bool;
       false = cost preview, true = actually evaluate + bill),
       `idempotency_key` (required when commit=true).
    2. Server parses CSV, validates columns, computes per-row eligibility
       against `programs` (excludes Tier X / excluded=1).
    3. When commit=false: returns estimated row count + ¥-cost preview
       so the consultant can confirm before billing. NO billing.
    4. When commit=true: emits one ¥3 usage_event per row, returns a ZIP
       containing one CSV per client (program_id, primary_name, tier,
       fit_score, reasons).
    5. Idempotency: when commit=true, the (api_key_hash, idempotency_key)
       tuple is checked against `am_idempotency_cache`. Re-submission
       returns the cached response without re-billing.

CSV format (UTF-8 or CP932 / Shift-JIS auto-detected):
    Required column: name_label
    Optional columns: jsic_major, prefecture, employee_count, capital_yen,
                      target_types, last_active_program_ids,
                      houjin_bangou, annual_revenue_yen, interest_categories
    Multi-value columns accept JSON / pipe / semicolon separators.

Constraints:
    * NO LLM / NO Anthropic API. Pure SQL + Python template assembly.
    * Solo + zero-touch — no operator approval. Consultant pre-views cost,
      confirms, and the fan-out runs synchronously inside the request.
    * Cap at 200 rows per CSV (mirrors client_profiles.MAX_BULK_IMPORT_ROWS).
    * Returns ZIP containing N CSVs + a manifest.json so the consultant
      can post-process programmatically.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import logging
import re
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

from jpintel_mcp.api.deps import (  # noqa: TC001
    ApiContextDep,
    DbDep,
    log_usage,
    require_metered_api_key,
)
from jpintel_mcp.api.idempotency_context import (
    billing_event_index,
    billing_idempotency_key,
)
from jpintel_mcp.api.middleware.cost_cap import _parse_cap_header

logger = logging.getLogger("jpintel.bulk_evaluate")

router = APIRouter(prefix="/v1/me/clients", tags=["bulk-evaluate"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_BULK_EVAL_ROWS = 200
PRICE_PER_ROW_YEN = 3
ENDPOINT_LABEL = "clients.bulk_evaluate"

_CSV_REQUIRED = ("name_label",)
_NAME_MAX_LEN = 128
_JSIC_MAX_LEN = 4
_PREFECTURE_MAX_LEN = 20

# Per-client result cap. Each client gets the top-K matched programs to keep
# the ZIP at a sane size. 50 mirrors the prescreen default.
_PER_CLIENT_RESULT_CAP = 50


# ---------------------------------------------------------------------------
# CSV helpers (mirror client_profiles helpers; kept local so future schema
# divergence between bulk_import and bulk_evaluate doesn't entangle the two)
# ---------------------------------------------------------------------------


def _coerce_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    digits = re.sub(r"[^\d-]", "", s)
    if not digits or digits == "-":
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_list_field(raw: str | None) -> list[str]:
    if raw is None:
        return []
    s = raw.strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (TypeError, ValueError):
            pass
    for sep in ("|", ";"):
        if sep in s:
            return [token.strip() for token in s.split(sep) if token.strip()]
    return [s]


def _decode_csv(raw_bytes: bytes) -> str:
    """utf-8-sig first, fallback cp932 (Excel JP)."""
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw_bytes.decode("cp932")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"csv encoding could not be decoded as utf-8 or cp932: {exc}",
            ) from exc


def _parse_csv_rows(raw_bytes: bytes) -> list[dict[str, Any]]:
    text = _decode_csv(raw_bytes)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "csv has no header row"
        )
    headers = {h.strip() for h in reader.fieldnames if h}
    missing = [h for h in _CSV_REQUIRED if h not in headers]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"csv missing required columns: {missing}",
        )
    rows: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader, start=1):
        if idx > MAX_BULK_EVAL_ROWS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"csv exceeds row cap of {MAX_BULK_EVAL_ROWS}",
            )
        name = raw.get("name_label")
        if not isinstance(name, str) or not name.strip():
            # Skip silently instead of failing the whole batch — surface
            # the skip count in the manifest.
            continue
        if len(name.strip()) > _NAME_MAX_LEN:
            continue
        rows.append(raw)
    if not rows:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "csv contained no rows with a valid name_label",
        )
    return rows


# ---------------------------------------------------------------------------
# Eligibility scoring (pure SQL, no LLM)
# ---------------------------------------------------------------------------


def _evaluate_one_client(
    conn: Any,
    client: dict[str, Any],
) -> list[dict[str, Any]]:
    """Score every active program against one client_profile row.

    Returns up to _PER_CLIENT_RESULT_CAP top matches. Pure heuristic:
        +3 prefecture exact match
        +3 prefecture is the program's prefecture OR program is national
        +1 jsic_major prefix overlap with target_types_json
        +1 employee_count <= small-business threshold (300)
        +0.5 program is Tier S/A (signal of curated quality)
    """
    pref = (client.get("prefecture") or "").strip() or None
    jsic = (client.get("jsic_major") or "").strip() or None
    target_types = _parse_list_field(client.get("target_types"))
    employee_count = _coerce_int(client.get("employee_count"))

    # Candidate fetch: Tier-X / excluded dropped, plus prefecture filter.
    where = ["excluded = 0", "COALESCE(tier,'X') != 'X'"]
    args: list[Any] = []
    if pref:
        where.append("(prefecture = ? OR prefecture IS NULL)")
        args.append(pref)
    sql = (
        "SELECT unified_id, primary_name, tier, prefecture, program_kind, "
        "       authority_level, target_types_json, "
        "       amount_max_man_yen "
        "  FROM programs "
        f" WHERE {' AND '.join(where)} "
        " ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 "
        "                   WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 9 END, "
        "          primary_name "
        " LIMIT 500"
    )
    rows = conn.execute(sql, args).fetchall()
    scored: list[dict[str, Any]] = []
    for r in rows:
        score = 0.0
        reasons: list[str] = []
        program_pref = r["prefecture"]
        if pref and program_pref == pref:
            score += 3
            reasons.append(f"prefecture_match:{pref}")
        elif program_pref is None:
            score += 3
            reasons.append("national_program")
        if jsic:
            try:
                tt = json.loads(r["target_types_json"] or "[]")
            except (TypeError, ValueError):
                tt = []
            if isinstance(tt, list) and any(jsic in str(x) for x in tt):
                score += 1
                reasons.append(f"jsic_overlap:{jsic}")
        if target_types:
            try:
                tt = json.loads(r["target_types_json"] or "[]")
            except (TypeError, ValueError):
                tt = []
            if isinstance(tt, list):
                hits = [x for x in target_types if any(x in str(t) for t in tt)]
                if hits:
                    score += 1
                    reasons.append(f"target_type_overlap:{hits[0]}")
        if employee_count is not None and employee_count <= 300:
            score += 1
            reasons.append("smb_threshold")
        if r["tier"] in ("S", "A"):
            score += 0.5
            reasons.append("curated_tier")
        if score <= 0:
            continue
        scored.append({
            "program_id": r["unified_id"],
            "primary_name": r["primary_name"],
            "tier": r["tier"],
            "prefecture": program_pref,
            "program_kind": r["program_kind"],
            "fit_score": round(score, 2),
            "reasons": ";".join(reasons),
            "amount_max_man_yen": r["amount_max_man_yen"],
        })
    scored.sort(key=lambda m: m["fit_score"], reverse=True)
    return scored[:_PER_CLIENT_RESULT_CAP]


# ---------------------------------------------------------------------------
# ZIP assembly
# ---------------------------------------------------------------------------


def _build_zip(
    rows: list[dict[str, Any]],
    results: list[list[dict[str, Any]]],
    timestamp: str,
) -> bytes:
    buf = io.BytesIO()
    manifest: dict[str, Any] = {
        "generated_at": timestamp,
        "client_count": len(rows),
        "result_cap_per_client": _PER_CLIENT_RESULT_CAP,
        "files": [],
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for client_row, matches in zip(rows, results, strict=False):
            label = (client_row.get("name_label") or "client").strip()
            safe_label = re.sub(r"[^\w一-鿿぀-ゟ゠-ヿ-]+", "_", label)[:60]
            csv_name = f"{safe_label}.csv"
            # Disambiguate collisions
            existing = {f["filename"] for f in manifest["files"]}
            if csv_name in existing:
                csv_name = f"{safe_label}_{len(existing)}.csv"
            buf_csv = io.StringIO()
            writer = csv.writer(buf_csv)
            writer.writerow([
                "program_id", "primary_name", "tier", "prefecture",
                "program_kind", "fit_score", "reasons", "amount_max_man_yen",
            ])
            for m in matches:
                writer.writerow([
                    m["program_id"], m["primary_name"], m["tier"],
                    m["prefecture"] or "", m["program_kind"] or "",
                    m["fit_score"], m["reasons"],
                    m["amount_max_man_yen"] or "",
                ])
            zf.writestr(csv_name, buf_csv.getvalue())
            manifest["files"].append({
                "filename": csv_name,
                "name_label": label,
                "match_count": len(matches),
            })
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    return buf.getvalue()


def _zip_stream_response(
    zip_bytes: bytes,
    idem_key: str,
    *,
    replay: bool = False,
    row_count: int | None = None,
    billed_yen: int | None = None,
) -> StreamingResponse:
    headers = {
        "Content-Disposition": (
            f"attachment; filename=bulk_evaluate_{idem_key}.zip"
        ),
    }
    if replay:
        headers["X-Idempotent-Replay"] = "1"
    if row_count is not None:
        headers["X-Row-Count"] = str(row_count)
    if billed_yen is not None:
        headers["X-Billed-Yen"] = str(billed_yen)
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Idempotency cache wrappers (am_idempotency_cache, migration 087)
# ---------------------------------------------------------------------------


# Schema (migration 087): am_idempotency_cache(cache_key TEXT PK,
# response_blob TEXT, expires_at TEXT, created_at TEXT). cache_key is
# sha256(api_key_hash || ':' || endpoint || ':' || body || ':' || key);
# we mirror that fingerprint here so /bulk_evaluate replays reuse the
# same cache surface as the IdempotencyMiddleware (24h TTL, lazy-evict).
_BULK_EVAL_CACHE_TTL_HOURS = 24


def _idem_cache_key(key_hash: str, idem_key: str) -> str:
    h = hashlib.sha256()
    h.update(key_hash.encode("utf-8"))
    h.update(b":/v1/me/clients/bulk_evaluate:")
    h.update(idem_key.encode("utf-8"))
    return h.hexdigest()


def _payload_signature(raw_bytes: bytes, *, program_filter: str, row_count: int) -> str:
    h = hashlib.sha256()
    h.update(raw_bytes)
    h.update(b":program_filter:")
    h.update(program_filter.strip().lower().encode("utf-8"))
    h.update(b":row_count:")
    h.update(str(row_count).encode("ascii"))
    return h.hexdigest()


def _check_commit_cost_cap(raw_header: str | None, predicted_yen: int) -> None:
    cap_yen = _parse_cap_header(raw_header)
    if cap_yen is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {
                "code": "cost_cap_required",
                "message": (
                    "X-Cost-Cap-JPY is required when commit=true. "
                    f"Predicted cost is ¥{predicted_yen}."
                ),
                "predicted_yen": predicted_yen,
                "unit_price_yen": PRICE_PER_ROW_YEN,
            },
        )
    if predicted_yen > cap_yen:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {
                "code": "cost_cap_exceeded",
                "message": (
                    f"Predicted cost ¥{predicted_yen} exceeds "
                    f"X-Cost-Cap-JPY ¥{cap_yen}."
                ),
                "predicted_yen": predicted_yen,
                "cost_cap_yen": cap_yen,
                "unit_price_yen": PRICE_PER_ROW_YEN,
            },
        )


def _idem_lookup(
    conn: Any, key_hash: str, idem_key: str
) -> dict[str, Any] | None:
    """Return the cached payload for (key_hash, idem_key), or None.

    Uses the migration-087 schema (cache_key, response_blob, expires_at).
    Lazy-evict: rows past expires_at are treated as cold misses so the
    daily sweep cron is belt-and-suspenders only.
    """
    cache_key = _idem_cache_key(key_hash, idem_key)
    try:
        row = conn.execute(
            "SELECT response_blob, expires_at FROM am_idempotency_cache "
            "WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    except Exception:  # noqa: BLE001 — table may not exist in old test DBs
        return None
    if row is None:
        return None
    try:
        blob = row["response_blob"]
        expires_at = row["expires_at"]
    except (IndexError, KeyError, TypeError):
        blob = row[0]
        expires_at = row[1]
    if not blob or not expires_at:
        return None
    try:
        if datetime.fromisoformat(
            str(expires_at).replace("Z", "+00:00")
        ) <= datetime.now(UTC):
            with contextlib.suppress(Exception):
                conn.execute(
                    "DELETE FROM am_idempotency_cache WHERE cache_key = ?",
                    (_idem_cache_key(key_hash, idem_key),),
                )
            return None
    except ValueError:
        return None
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        return None


def _billing_idempotency_key_was_used(
    conn: Any,
    key_hash: str,
    billing_key: str,
) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM usage_events "
            "WHERE key_hash = ? "
            "AND (billing_idempotency_key = ? "
            "OR substr(billing_idempotency_key, 1, ?) = ?) "
            "LIMIT 1",
            (
                key_hash,
                billing_key,
                len(billing_key) + 1,
                f"{billing_key}:",
            ),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def _idem_reserve_payload(
    conn: Any,
    key_hash: str,
    idem_key: str,
    *,
    payload_signature: str,
    program_filter: str,
    row_count: int,
) -> bool:
    """Durably bind an idempotency key to one payload before billing."""
    cache_key = _idem_cache_key(key_hash, idem_key)
    expires_at = (
        datetime.now(UTC) + timedelta(hours=_BULK_EVAL_CACHE_TTL_HOURS)
    ).isoformat()
    created_at = datetime.now(UTC).isoformat()
    payload = {
        "payload_signature": payload_signature,
        "program_filter": program_filter,
        "row_count": row_count,
        "reserved": True,
        "generated_at": created_at,
    }
    try:
        conn.execute(
            "INSERT INTO am_idempotency_cache("
            "  cache_key, response_blob, expires_at, created_at"
            ") VALUES (?,?,?,?)",
            (
                cache_key,
                json.dumps(payload, ensure_ascii=False),
                expires_at,
                created_at,
            ),
        )
        return True
    except sqlite3.IntegrityError:
        # A racing request reserved the same key. The caller re-reads below;
        # billing remains protected by the stable billing idempotency key.
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "idem cache reserve failed key_hash=%s idem=%s",
            key_hash[:8] if key_hash else None, idem_key,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "code": "idempotency_cache_unavailable",
                "message": (
                    "Could not safely reserve idempotency_key before billing. "
                    "Retry with the same idempotency_key."
                ),
            },
        ) from exc


def _idem_store(
    conn: Any, key_hash: str, idem_key: str, payload: dict[str, Any]
) -> None:
    """Persist the response payload under the migration-087 schema.

    Failure is non-fatal: when the table does not yet exist (old test DB)
    or the write loses a race, the next caller simply sees a cache miss
    and re-runs the evaluation.
    """
    cache_key = _idem_cache_key(key_hash, idem_key)
    expires_at = (
        datetime.now(UTC) + timedelta(hours=_BULK_EVAL_CACHE_TTL_HOURS)
    ).isoformat()
    created_at = datetime.now(UTC).isoformat()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO am_idempotency_cache("
            "  cache_key, response_blob, expires_at, created_at"
            ") VALUES (?,?,?,?)",
            (
                cache_key,
                json.dumps(payload, ensure_ascii=False),
                expires_at,
                created_at,
            ),
        )
    except Exception:  # noqa: BLE001 — non-fatal
        logger.warning(
            "idem cache store failed key_hash=%s idem=%s",
            key_hash[:8] if key_hash else None, idem_key,
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/bulk_evaluate")
async def bulk_evaluate_clients(
    ctx: ApiContextDep,
    conn: DbDep,
    file: Annotated[UploadFile, File(description="CSV with name_label header")],
    commit: Annotated[bool, Form()] = False,
    program_filter: Annotated[str, Form()] = "all",
    idempotency_key: Annotated[str | None, Form()] = None,
    x_cost_cap_jpy: Annotated[str | None, Header(alias="X-Cost-Cap-JPY")] = None,
    idempotency_key_header: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> Any:
    """Pre-evaluate program eligibility for ALL clients in a CSV batch.

    When `commit=false` (default): returns JSON cost preview only. NO billing.
    When `commit=true`: bills ¥3 × N rows, returns a ZIP archive (one CSV
        per client + manifest.json). `idempotency_key` form field or
        `Idempotency-Key` header REQUIRED on commit so accidental retries
        don't double-bill. `X-Cost-Cap-JPY` REQUIRED
        on commit so callers explicitly approve the predicted charge.

    Returns:
        - JSON {"row_count": N, "estimated_yen": 3*N, "preview": true}
          when commit=false.
        - application/zip stream when commit=true.

    Errors:
        - 401 if anon (no key to bill).
        - 400 on missing required columns / bad encoding / row cap /
              missing X-Cost-Cap-JPY on commit.
        - 402 if predicted charge exceeds X-Cost-Cap-JPY.
        - 409 if commit=true but idempotency_key already used with a
              different payload signature.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "bulk_evaluate requires an authenticated API key",
        )

    raw_bytes = await file.read()
    rows = _parse_csv_rows(raw_bytes)
    n = len(rows)
    payload_signature = _payload_signature(
        raw_bytes,
        program_filter=program_filter,
        row_count=n,
    )

    if not commit:
        # Cost preview path. FREE — no usage_event, no Stripe report.
        return JSONResponse({
            "preview": True,
            "row_count": n,
            "estimated_yen": PRICE_PER_ROW_YEN * n,
            "program_filter": program_filter,
            "next_step": (
                "POST again with commit=true and idempotency_key=<uuid> "
                "and X-Cost-Cap-JPY>=estimated_yen to actually evaluate "
                "and bill."
            ),
        })

    require_metered_api_key(ctx, "bulk_evaluate commit")

    # commit=true — billing path requires idempotency.
    form_idem_key = idempotency_key.strip() if idempotency_key else None
    header_idem_key = (
        idempotency_key_header.strip() if idempotency_key_header else None
    )
    if form_idem_key and header_idem_key and form_idem_key != header_idem_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "idempotency_payload_mismatch",
                "message": (
                    "idempotency_key form field and Idempotency-Key header "
                    "must match when both are supplied."
                ),
            },
        )
    idem_key = form_idem_key or header_idem_key
    if not idem_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "idempotency_key form field or Idempotency-Key header is "
            "required when commit=true",
        )
    billing_key = f"{ENDPOINT_LABEL}:{ctx.key_hash}:{idem_key}"
    already_billed_retry = False

    cached = _idem_lookup(conn, ctx.key_hash, idem_key)
    if cached is not None:
        cached_signature = cached.get("payload_signature")
        if cached_signature and cached_signature != payload_signature:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": "idempotency_payload_mismatch",
                    "message": (
                        "This idempotency_key was already used with a "
                        "different CSV payload or program_filter."
                    ),
                },
            )
        if "rows" not in cached or "results" not in cached:
            logger.info("idem key reserved without final result; re-evaluating")
        else:
            # Replay path — return cached ZIP without re-billing.
            try:
                cached_rows = cached.get("rows", [])
                cached_results = cached.get("results", [])
                cached_ts = cached.get(
                    "generated_at", datetime.now(UTC).isoformat()
                )
                zip_bytes = _build_zip(cached_rows, cached_results, cached_ts)
                return _zip_stream_response(zip_bytes, idem_key, replay=True)
            except Exception:  # noqa: BLE001
                logger.warning("idem replay failed; falling through to live eval")
        already_billed_retry = _billing_idempotency_key_was_used(
            conn, ctx.key_hash, billing_key
        )
    else:
        if _billing_idempotency_key_was_used(conn, ctx.key_hash, billing_key):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": "idempotency_key_already_used",
                    "message": (
                        "This idempotency_key was already used for a billed "
                        "bulk_evaluate request. Use a new idempotency_key."
                    ),
                },
            )
        reserved = _idem_reserve_payload(
            conn,
            ctx.key_hash,
            idem_key,
            payload_signature=payload_signature,
            program_filter=program_filter,
            row_count=n,
        )
        if not reserved:
            cached = _idem_lookup(conn, ctx.key_hash, idem_key)
            if cached is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    {
                        "code": "idempotency_key_in_use",
                        "message": (
                            "This idempotency_key is already being processed. "
                            "Retry with the same CSV payload."
                        ),
                    },
                )
            cached_signature = cached.get("payload_signature")
            if cached_signature and cached_signature != payload_signature:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    {
                        "code": "idempotency_payload_mismatch",
                        "message": (
                            "This idempotency_key was already used with a "
                            "different CSV payload or program_filter."
                        ),
                    },
                )
            if "rows" in cached and "results" in cached:
                cached_rows = cached.get("rows", [])
                cached_results = cached.get("results", [])
                cached_ts = cached.get(
                    "generated_at", datetime.now(UTC).isoformat()
                )
                zip_bytes = _build_zip(cached_rows, cached_results, cached_ts)
                return _zip_stream_response(zip_bytes, idem_key, replay=True)

    from jpintel_mcp.api.middleware.customer_cap import (
        projected_monthly_cap_response,
    )

    if not already_billed_retry:
        cap_response = projected_monthly_cap_response(conn, ctx.key_hash, n)
        if cap_response is not None:
            return cap_response
        _check_commit_cost_cap(x_cost_cap_jpy, PRICE_PER_ROW_YEN * n)

    # Live eval path.
    results: list[list[dict[str, Any]]] = []
    for client_row in rows:
        results.append(_evaluate_one_client(conn, client_row))

    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    zip_bytes = _build_zip(rows, results, timestamp)

    # Bill: ¥3 × N rows. Single log_usage call with quantity=N produces
    # ONE usage_events audit row (so the operator dashboard reads "1 batch
    # request, N billed units") + ONE Stripe usage_record with quantity=N
    # (Stripe-side aggregation by `usage_event_id` idempotency key prevents
    # double-charges on retries). The previous implementation looped N times
    # with quantity=1 — same dollar total but N rows + N Stripe POSTs +
    # N idempotency keys, which fragmented the reconciliation surface and
    # increased the risk of partial-success Stripe outages.
    if not already_billed_retry:
        billing_key_token = billing_idempotency_key.set(billing_key)
        billing_event_token = billing_event_index.set(0)
        try:
            log_usage(
                conn=conn,
                ctx=ctx,
                endpoint=ENDPOINT_LABEL,
                status_code=200,
                params={"program_filter": program_filter, "row_count": n},
                quantity=n,
                result_count=n,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("bulk_evaluate billing row failed", exc_info=True)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {
                    "code": "billing_unavailable",
                    "message": (
                        "Bulk evaluation completed, but the billing audit row "
                        "could not be written. No ZIP was delivered; retry with "
                        "the same idempotency_key."
                    ),
                },
            ) from exc
        finally:
            billing_event_index.reset(billing_event_token)
            billing_idempotency_key.reset(billing_key_token)
        if not _billing_idempotency_key_was_used(conn, ctx.key_hash, billing_key):
            logger.warning(
                "bulk_evaluate billing row not recorded after log_usage"
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {
                    "code": "billing_unavailable",
                    "message": (
                        "Bulk evaluation completed, but the billing audit row "
                        "was not recorded. No ZIP was delivered; retry with "
                        "the same idempotency_key."
                    ),
                },
            )
    else:
        logger.info("bulk_evaluate rebuilding cached ZIP for already billed retry")

    # Stash idempotency so retries reuse the same evaluation.
    _idem_store(
        conn, ctx.key_hash, idem_key,
        {
            "rows": rows,
            "results": results,
            "generated_at": timestamp,
            "payload_signature": payload_signature,
            "program_filter": program_filter,
            "row_count": n,
        },
    )

    return _zip_stream_response(
        zip_bytes,
        idem_key,
        replay=already_billed_retry,
        row_count=n,
        billed_yen=None if already_billed_retry else PRICE_PER_ROW_YEN * n,
    )


__all__ = ["MAX_BULK_EVAL_ROWS", "PRICE_PER_ROW_YEN", "router"]
