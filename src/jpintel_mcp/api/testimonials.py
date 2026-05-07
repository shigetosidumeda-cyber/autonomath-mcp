"""Public testimonial collection + moderation (P5-ι, brand 5-pillar 透明・誠実).

Routes:
  POST   /v1/me/testimonials       — authed (X-API-Key), submit pending row
  GET    /v1/testimonials          — public, approved rows only
  POST   /v1/admin/testimonials/{id}/approve  — operator only (admin key)
  POST   /v1/admin/testimonials/{id}/unapprove — operator only (admin key)
  DELETE /v1/me/testimonials/{id}  — owner only (matching key_hash)

Privacy posture (INV-21):
  * api_key_hash never surfaces. Public list omits it; even the admin
    endpoint only returns it indirectly via the moderation queue.
  * `name` and `organization` are optional. If a submitter posts without
    them the public list shows an anonymous "audience" (e.g. "VC").
  * `linkedin_url` is self-asserted attribution; we don't validate
    identity from it. It is shown verbatim if approved.

Anti-fake posture:
  * Submission requires an authenticated key (X-API-Key). Anonymous
    callers get 401 — fake testimonials would otherwise be free.
  * Approval is operator-gated (settings.admin_api_key). No automatic
    publication; every row stays pending until we approve it.
  * Owners can DELETE their own testimonials (matched by key_hash).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api.admin import AdminAuthDep  # noqa: TC001 (FastAPI Depends)
from jpintel_mcp.api.deps import (  # noqa: TC001 (FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
)

_log = logging.getLogger("jpintel.admin.testimonials")

# ---------------------------------------------------------------------------
# Two routers: public list path and authed write/delete path. The admin
# moderation endpoints live on a third router pinned under /v1/admin/* so
# they share the existing AdminAuthDep + include_in_schema=False posture.
# ---------------------------------------------------------------------------

# Public read — no auth, no anon-quota gating (transparency surface, same as
# /v1/meta/freshness and /v1/stats/*).
public_router = APIRouter(prefix="/v1/testimonials", tags=["testimonials"])

# Authed write — POST/DELETE under /v1/me/testimonials. Requires X-API-Key.
me_router = APIRouter(prefix="/v1/me/testimonials", tags=["testimonials", "me"])

# Operator moderation — under /v1/admin so it inherits the admin-key gate
# and stays out of the public OpenAPI spec.
admin_router = APIRouter(
    prefix="/v1/admin/testimonials",
    tags=["testimonials", "admin"],
    include_in_schema=False,
)


_AUDIENCES = ("税理士", "行政書士", "SMB", "VC", "Dev")
AudienceLiteral = Literal["税理士", "行政書士", "SMB", "VC", "Dev"]


def _validate_linkedin_url(url: str | None) -> str | None:
    """Allow only https URLs to LinkedIn-shaped hosts.

    The public testimonials.html page renders this URL as ``<a href="...">``,
    so a `javascript:` / `data:` scheme would yield XSS-on-click even after
    operator approval. We harden in depth: scheme must be https, host must
    end with the ``.linkedin.com`` apex (or be the apex itself). Empty or
    None passes through unchanged.
    """
    if url is None or not url.strip():
        return None
    candidate = url.strip()
    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"linkedin_url is not a valid URL: {exc}",
        ) from exc
    if parsed.scheme.lower() != "https":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "linkedin_url must use https://",
        )
    host = (parsed.hostname or "").lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "linkedin_url must point to *.linkedin.com",
        )
    return candidate


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestimonialSubmit(BaseModel):
    audience: AudienceLiteral
    text: Annotated[str, Field(min_length=10, max_length=2000)]
    name: Annotated[str | None, Field(default=None, max_length=80)] = None
    organization: Annotated[str | None, Field(default=None, max_length=120)] = None
    linkedin_url: Annotated[str | None, Field(default=None, max_length=300)] = None


class TestimonialSubmitResponse(BaseModel):
    received: bool
    testimonial_id: int
    pending_review: bool


class TestimonialPublic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    audience: str
    text: str
    name: str | None
    organization: str | None
    linkedin_url: str | None
    approved_at: str


class TestimonialListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    rows: list[TestimonialPublic]


# ---------------------------------------------------------------------------
# POST /v1/me/testimonials  — authed, creates pending row
# ---------------------------------------------------------------------------


@me_router.post(
    "",
    response_model=TestimonialSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_testimonial(
    payload: TestimonialSubmit,
    conn: DbDep,
    ctx: ApiContextDep,
) -> TestimonialSubmitResponse:
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "X-API-Key required to submit a testimonial",
        )

    # Defense-in-depth — DB has the same CHECK constraint, but bouncing it
    # at the API layer gives a 422 instead of a 500 on bad audience input.
    if payload.audience not in _AUDIENCES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"audience must be one of {_AUDIENCES}",
        )

    # Reject non-https + non-linkedin.com URLs at submission time so a
    # `javascript:` payload never enters the moderation queue (the public
    # testimonials.html page renders this verbatim as ``<a href=...>``).
    linkedin_url = _validate_linkedin_url(payload.linkedin_url)

    cur = conn.execute(
        """INSERT INTO testimonials(
               api_key_hash, audience, text, name, organization,
               linkedin_url, approved_at, created_at
           ) VALUES (?,?,?,?,?,?,?,?)""",
        (
            ctx.key_hash,
            payload.audience,
            payload.text,
            payload.name,
            payload.organization,
            linkedin_url,
            None,  # pending moderation
            datetime.now(UTC).isoformat(),
        ),
    )
    return TestimonialSubmitResponse(
        received=True,
        testimonial_id=int(cur.lastrowid or 0),
        pending_review=True,
    )


# ---------------------------------------------------------------------------
# DELETE /v1/me/testimonials/{id} — owner-only retraction
# ---------------------------------------------------------------------------


@me_router.delete("/{testimonial_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_testimonial(
    testimonial_id: int,
    conn: DbDep,
    ctx: ApiContextDep,
) -> None:
    if ctx.key_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-API-Key required")
    row = conn.execute(
        "SELECT api_key_hash FROM testimonials WHERE id = ?",
        (testimonial_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "testimonial not found")
    if row["api_key_hash"] != ctx.key_hash:
        # Don't leak existence to other keys — return 404 instead of 403.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "testimonial not found")
    conn.execute("DELETE FROM testimonials WHERE id = ?", (testimonial_id,))


# ---------------------------------------------------------------------------
# GET /v1/testimonials — public, approved only
# ---------------------------------------------------------------------------


def _safe_linkedin_for_render(url: str | None) -> str | None:
    """Belt-and-suspenders: even on the public list response we re-validate
    the stored ``linkedin_url`` so any pre-fix row carrying a non-https or
    non-linkedin.com URL is dropped (rendered as None) instead of being
    surfaced into the HTML <a href> on testimonials.html."""
    if url is None or not url.strip():
        return None
    try:
        return _validate_linkedin_url(url)
    except HTTPException:
        return None


@public_router.get("", response_model=TestimonialListResponse)
def list_testimonials(conn: DbDep) -> TestimonialListResponse:
    rows = conn.execute(
        """SELECT id, audience, text, name, organization,
                  linkedin_url, approved_at
             FROM testimonials
            WHERE approved_at IS NOT NULL
         ORDER BY approved_at DESC, id DESC
            LIMIT 200"""
    ).fetchall()
    return TestimonialListResponse(
        total=len(rows),
        rows=[
            TestimonialPublic(
                id=r["id"],
                audience=r["audience"],
                text=r["text"],
                name=r["name"],
                organization=r["organization"],
                linkedin_url=_safe_linkedin_for_render(r["linkedin_url"]),
                approved_at=r["approved_at"],
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# Admin moderation: approve / unapprove
# ---------------------------------------------------------------------------


class ModerationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    approved: bool
    approved_at: str | None


@admin_router.post(
    "/{testimonial_id}/approve",
    response_model=ModerationResponse,
)
def approve_testimonial(
    testimonial_id: int,
    conn: DbDep,
    _: AdminAuthDep,
) -> ModerationResponse:
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        "UPDATE testimonials SET approved_at = ? WHERE id = ?",
        (now, testimonial_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "testimonial not found")
    _log.info(
        "admin_testimonial_action",
        extra={
            "action": "approve",
            "testimonial_id": testimonial_id,
            "timestamp": now,
        },
    )
    return ModerationResponse(id=testimonial_id, approved=True, approved_at=now)


@admin_router.post(
    "/{testimonial_id}/unapprove",
    response_model=ModerationResponse,
)
def unapprove_testimonial(
    testimonial_id: int,
    conn: DbDep,
    _: AdminAuthDep,
) -> ModerationResponse:
    cur = conn.execute(
        "UPDATE testimonials SET approved_at = NULL WHERE id = ?",
        (testimonial_id,),
    )
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "testimonial not found")
    _log.info(
        "admin_testimonial_action",
        extra={
            "action": "unapprove",
            "testimonial_id": testimonial_id,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    return ModerationResponse(id=testimonial_id, approved=False, approved_at=None)
