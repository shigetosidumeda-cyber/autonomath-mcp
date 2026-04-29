"""Client profile registry for 補助金コンサル fan-out (navit cancel trigger #1).

Endpoints under /v1/me/client_profiles:
    - POST   /v1/me/client_profiles/bulk_import   CSV upload, ≤200 rows
    - GET    /v1/me/client_profiles               list calling key's profiles
    - DELETE /v1/me/client_profiles/{profile_id}  hard-delete one profile

Why a separate router (not folded into me.py / saved_searches.py):
    * me.py is the dashboard-cookie surface. client_profiles are managed by
      the calling API key (X-API-Key / Authorization: Bearer) so MCP tools
      and CI callers can wire 顧問先 metadata in without touching the
      browser flow.
    * saved_searches.py owns the digest payload; this router owns the
      consultant's per-顧問先 metadata. The cron joins the two via
      saved_searches.profile_ids_json (migration 097).

Authentication:
    Authenticated via require_key (ApiContextDep). Anonymous tier rejected
    with 401 — there is no key to attach the profile tree to.

Cost posture:
    * **CRUD is FREE.** POST/GET/DELETE on the customer's own profile rows
      are CRUD calls, not metered surfaces. They still count against the
      per-key middleware rate limit.
    * **Fan-out is metered.** The saved_searches cron joins
      saved_searches.profile_ids_json × client_profiles and emits one ¥3
      digest per (saved_search, profile_id) pair. That billing path is
      owned by `scripts/cron/run_saved_searches.py` — this router only
      maintains the metadata.

§52 fence:
    Profile metadata is consultant-supplied; we don't surface tax or legal
    advice anywhere here. Disclaimer is rendered by the digest template
    (saved_search_digest) — the CRUD endpoint surface stays clean.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
)

router = APIRouter(prefix="/v1/me/client_profiles", tags=["client-profiles"])

logger = logging.getLogger("jpintel.client_profiles")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard cap on profiles per key. 200 = navit's most aggressive comparable
# tier (consultants servicing 200 SMB clients) per the audience page math.
# Above 200 we want the explicit 409 rather than a silent runaway billing
# loop on the saved_search fan-out.
MAX_CLIENT_PROFILES_PER_KEY = 200

# Bulk-import row cap. Same number as the per-key cap — a single CSV
# uploads the entire 顧問先 list in one POST.
MAX_BULK_IMPORT_ROWS = 200

# Per-row validation. Free-text labels capped at 128 chars (matches
# saved_searches.name); JSIC major prefix capped at 4 chars
# (e.g. 'E' / 'E13' / 'E133').
_NAME_MAX_LEN = 128
_JSIC_MAX_LEN = 4
_PREFECTURE_MAX_LEN = 20

# Required columns in the CSV. Other columns are accepted and ignored
# so the consultant can paste their own export verbatim.
_CSV_REQUIRED = ("name_label",)
_CSV_OPTIONAL = (
    "jsic_major",
    "prefecture",
    "employee_count",
    "capital_yen",
    "target_types",
    "last_active_program_ids",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ClientProfileResponse(BaseModel):
    profile_id: int
    name_label: str
    jsic_major: str | None
    prefecture: str | None
    employee_count: int | None
    capital_yen: int | None
    target_types: list[str]
    last_active_program_ids: list[str]
    created_at: str
    updated_at: str


class BulkImportResponse(BaseModel):
    imported: int
    updated: int
    skipped: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    total_after_import: int


class DeleteResponse(BaseModel):
    ok: bool
    profile_id: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    # Tolerate "1,000" / "1000人" / "￥1,000,000" — strip non-digit suffixes.
    digits = re.sub(r"[^\d-]", "", s)
    if not digits or digits == "-":
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_list_field(raw: str | None) -> list[str]:
    """Parse a CSV cell that holds a list. Accepts:
    - JSON array literal: '["A","B"]'
    - Pipe-separated:    'A|B|C'
    - Semicolon-separated: 'A;B;C'
    - Single token:      'A'
    Returns [] on empty / unparseable.
    """
    if raw is None:
        return []
    s = raw.strip()
    if not s:
        return []
    # JSON array first.
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (TypeError, ValueError):
            pass
    # Pipe / semicolon split.
    for sep in ("|", ";"):
        if sep in s:
            return [token.strip() for token in s.split(sep) if token.strip()]
    return [s]


def _row_to_response(row: dict[str, Any]) -> ClientProfileResponse:
    try:
        target_types = json.loads(row["target_types_json"] or "[]")
        if not isinstance(target_types, list):
            target_types = []
    except (TypeError, ValueError):
        target_types = []
    try:
        last_active = json.loads(row["last_active_program_ids_json"] or "[]")
        if not isinstance(last_active, list):
            last_active = []
    except (TypeError, ValueError):
        last_active = []
    return ClientProfileResponse(
        profile_id=row["profile_id"],
        name_label=row["name_label"],
        jsic_major=row["jsic_major"],
        prefecture=row["prefecture"],
        employee_count=row["employee_count"],
        capital_yen=row["capital_yen"],
        target_types=[str(x) for x in target_types],
        last_active_program_ids=[str(x) for x in last_active],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_one_row(
    raw: dict[str, Any], idx: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate a single CSV row. Returns (cleaned, error). Exactly one is
    None — if the row is valid we return (cleaned, None); on validation
    failure we return (None, error_dict)."""
    name_label_raw = raw.get("name_label")
    if not isinstance(name_label_raw, str) or not name_label_raw.strip():
        return None, {"row_index": idx, "error": "missing_name_label"}
    name_label = name_label_raw.strip()
    if len(name_label) > _NAME_MAX_LEN:
        return None, {"row_index": idx, "error": "name_label_too_long",
                      "max": _NAME_MAX_LEN}

    jsic_raw = raw.get("jsic_major")
    jsic = jsic_raw.strip() if isinstance(jsic_raw, str) else None
    if jsic is not None and not jsic:
        jsic = None
    if jsic is not None and len(jsic) > _JSIC_MAX_LEN:
        return None, {"row_index": idx, "error": "jsic_major_too_long",
                      "max": _JSIC_MAX_LEN}

    pref_raw = raw.get("prefecture")
    prefecture = pref_raw.strip() if isinstance(pref_raw, str) else None
    if prefecture is not None and not prefecture:
        prefecture = None
    if prefecture is not None and len(prefecture) > _PREFECTURE_MAX_LEN:
        return None, {"row_index": idx, "error": "prefecture_too_long",
                      "max": _PREFECTURE_MAX_LEN}

    employee_count = _coerce_int(raw.get("employee_count"))
    if employee_count is not None and employee_count < 0:
        return None, {"row_index": idx, "error": "employee_count_negative"}
    capital_yen = _coerce_int(raw.get("capital_yen"))
    if capital_yen is not None and capital_yen < 0:
        return None, {"row_index": idx, "error": "capital_yen_negative"}

    target_types = _parse_list_field(raw.get("target_types"))
    last_active = _parse_list_field(raw.get("last_active_program_ids"))

    cleaned = {
        "name_label": name_label,
        "jsic_major": jsic,
        "prefecture": prefecture,
        "employee_count": employee_count,
        "capital_yen": capital_yen,
        "target_types_json": json.dumps(
            target_types, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ),
        "last_active_program_ids_json": json.dumps(
            last_active, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ),
    }
    return cleaned, None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/bulk_import",
    response_model=BulkImportResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_import_client_profiles(
    ctx: ApiContextDep,
    conn: DbDep,
    file: Annotated[UploadFile, File(description="CSV with name_label header")],
    upsert: Annotated[bool, Form()] = True,
) -> BulkImportResponse:
    """Upload a CSV of 顧問先 metadata. Up to 200 rows per call.

    Required column: `name_label`.
    Optional columns: `jsic_major`, `prefecture`, `employee_count`,
    `capital_yen`, `target_types`, `last_active_program_ids`.
    Multi-value columns (`target_types`, `last_active_program_ids`)
    accept JSON arrays, pipe-separated, or semicolon-separated values.

    Returns 401 for anonymous callers — this is a per-key surface.
    Returns 400 on missing required column / unparseable CSV / >200 rows.
    Returns 409 when the per-key cap (MAX_CLIENT_PROFILES_PER_KEY) would
    be exceeded by the import.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "client_profiles require an authenticated API key",
        )

    # Slurp the upload. UploadFile streams to disk above ~1MB but the
    # spec caps us at 200 rows so a strict in-memory read stays cheap.
    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Fall back to cp932 (Excel JP default) so a consultant's hand-
        # exported CSV imports cleanly.
        try:
            text = raw_bytes.decode("cp932")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"csv encoding could not be decoded as utf-8 or cp932: {exc}",
            ) from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "csv has no header row"
        )
    headers = {h.strip() for h in reader.fieldnames if h}
    missing_required = [h for h in _CSV_REQUIRED if h not in headers]
    if missing_required:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"csv missing required columns: {missing_required}",
        )

    cleaned_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader, start=1):
        if idx > MAX_BULK_IMPORT_ROWS:
            errors.append({"row_index": idx, "error": "exceeded_row_cap",
                           "cap": MAX_BULK_IMPORT_ROWS})
            break
        cleaned, err = _validate_one_row(raw, idx)
        if err:
            errors.append(err)
            continue
        if cleaned is not None:
            cleaned_rows.append(cleaned)

    # Per-key cap pre-flight.
    (existing_count,) = conn.execute(
        "SELECT COUNT(*) FROM client_profiles WHERE api_key_hash = ?",
        (ctx.key_hash,),
    ).fetchone()
    if upsert:
        # When upserting, only NEW name_labels add to the count.
        if cleaned_rows:
            placeholders = ",".join("?" for _ in cleaned_rows)
            new_label_check = conn.execute(
                f"SELECT name_label FROM client_profiles "
                f"WHERE api_key_hash = ? AND name_label IN ({placeholders})",
                (ctx.key_hash, *[r["name_label"] for r in cleaned_rows]),
            ).fetchall()
            existing_labels = {r["name_label"] for r in new_label_check}
        else:
            existing_labels = set()
        net_new = sum(
            1 for r in cleaned_rows if r["name_label"] not in existing_labels
        )
    else:
        existing_labels = set()
        net_new = len(cleaned_rows)

    if existing_count + net_new > MAX_CLIENT_PROFILES_PER_KEY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            (
                f"client_profiles cap reached "
                f"(have {existing_count}, importing {net_new}, "
                f"max {MAX_CLIENT_PROFILES_PER_KEY}); delete some "
                f"before importing"
            ),
        )

    imported = 0
    updated = 0
    skipped = 0
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    for r in cleaned_rows:
        if upsert and r["name_label"] in existing_labels:
            conn.execute(
                """UPDATE client_profiles
                      SET jsic_major = ?, prefecture = ?,
                          employee_count = ?, capital_yen = ?,
                          target_types_json = ?,
                          last_active_program_ids_json = ?,
                          updated_at = ?
                    WHERE api_key_hash = ? AND name_label = ?""",
                (
                    r["jsic_major"], r["prefecture"],
                    r["employee_count"], r["capital_yen"],
                    r["target_types_json"], r["last_active_program_ids_json"],
                    now,
                    ctx.key_hash, r["name_label"],
                ),
            )
            updated += 1
            continue
        try:
            conn.execute(
                """INSERT INTO client_profiles(
                        api_key_hash, name_label, jsic_major, prefecture,
                        employee_count, capital_yen, target_types_json,
                        last_active_program_ids_json, created_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    ctx.key_hash, r["name_label"], r["jsic_major"],
                    r["prefecture"], r["employee_count"], r["capital_yen"],
                    r["target_types_json"],
                    r["last_active_program_ids_json"],
                    now, now,
                ),
            )
            imported += 1
        except Exception as exc:  # noqa: BLE001 — capture per-row, do not halt
            logger.warning(
                "client_profile.import_row_failed name=%s err=%s",
                r["name_label"], exc,
            )
            errors.append({"name_label": r["name_label"],
                           "error": "insert_failed", "detail": str(exc)})
            skipped += 1

    (total_after,) = conn.execute(
        "SELECT COUNT(*) FROM client_profiles WHERE api_key_hash = ?",
        (ctx.key_hash,),
    ).fetchone()

    return BulkImportResponse(
        imported=imported,
        updated=updated,
        skipped=skipped,
        errors=errors,
        total_after_import=total_after,
    )


@router.get(
    "",
    response_model=list[ClientProfileResponse],
)
def list_client_profiles(
    ctx: ApiContextDep,
    conn: DbDep,
) -> list[ClientProfileResponse]:
    """Return all client_profiles owned by the calling key.

    Ordered by profile_id ascending so the dashboard renders stably.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "client_profiles require an authenticated API key",
        )
    rows = conn.execute(
        """SELECT profile_id, name_label, jsic_major, prefecture,
                  employee_count, capital_yen, target_types_json,
                  last_active_program_ids_json, created_at, updated_at
             FROM client_profiles
            WHERE api_key_hash = ?
         ORDER BY profile_id ASC""",
        (ctx.key_hash,),
    ).fetchall()
    return [_row_to_response(dict(r)) for r in rows]


@router.delete(
    "/{profile_id}",
    response_model=DeleteResponse,
)
def delete_client_profile(
    profile_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
) -> DeleteResponse:
    """Hard-delete a client_profile. 404 when the id is not the caller's."""
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "client_profiles require an authenticated API key",
        )
    row = conn.execute(
        "SELECT profile_id FROM client_profiles "
        "WHERE profile_id = ? AND api_key_hash = ?",
        (profile_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "client_profile not found"
        )
    conn.execute(
        "DELETE FROM client_profiles "
        "WHERE profile_id = ? AND api_key_hash = ?",
        (profile_id, ctx.key_hash),
    )
    return DeleteResponse(ok=True, profile_id=profile_id)


__all__ = [
    "MAX_BULK_IMPORT_ROWS",
    "MAX_CLIENT_PROFILES_PER_KEY",
    "router",
]
