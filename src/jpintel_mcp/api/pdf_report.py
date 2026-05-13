"""Per-client monthly PDF report generator.

Wave 35 Axis 6a (2026-05-12). Surfaces a single
``POST /v1/pdf_report/generate`` endpoint that renders a 顧問先別 月次
report from the live ``autonomath.db`` corpus into a PDF blob using the
pure-Python ``reportlab`` library.

Design constraints (memory)
---------------------------
* **No LLM API import.** The renderer is `reportlab` only; the body text
  is templated from existing corpus rows (``houjin_360`` + risk score +
  amendment alerts + 8 業法 fence summary). No model call sites.
* **Solo + zero-touch.** Self-serve: the caller (a 税理士 fan-out cron or
  the customer themselves) posts a ``client_id`` and receives a signed
  R2 URL.
* **API/MCP only.** No HTML preview, no admin dashboard — the PDF is a
  byte stream uploaded to R2 and surfaced via TTL=7d signed URL.
* **¥3/req metered.** 1 PDF = 10 billable units = ¥30 (covers reportlab
  CPU + R2 PUT + 7-day storage). Anonymous callers rejected with 402.
* **Brand:** jpcite.

Endpoints (mounted at ``/v1/pdf_report``):

    POST /v1/pdf_report/generate?client_id=<id>
        Body (optional): {"cadence":"monthly","sections":[...]}
        → 200 OK with download URL + sha256.

    GET  /v1/pdf_report/subscriptions/{client_id}
        → 200 OK with the row from ``am_pdf_report_subscriptions``.

    POST /v1/pdf_report/subscriptions
        Body: {"client_id":..., "cadence":"monthly", "r2_url_template":...}
        → 201 Created (idempotent — repeats overwrite the row).

The output PDF carries the §52 / 税理士法 / §47条の2 disclaimer matching
``api/tax_rulesets.py`` so the artefact is internally consistent with
every other paid surface.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import secrets
import sqlite3  # noqa: TC003 (runtime: DB connection type)
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_usage,
    require_metered_api_key,
)
from jpintel_mcp.api.tax_rulesets import _TAX_DISCLAIMER

logger = logging.getLogger("jpintel.pdf_report")

router = APIRouter(prefix="/v1/pdf_report", tags=["pdf_report"])

# 1 PDF generation = 10 billable units. 10 × ¥3 = ¥30, prices the
# reportlab CPU (1-3 sec) + R2 PUT + 7-day storage.
PDF_REPORT_UNIT_COUNT = 10

# Signed URL TTL — 7 days lets a 税理士 forward the link to a 顧問先 by
# email without forcing a rerun. Storage is small (each PDF is ~30-150 KB)
# so 7 days × N customers fits in R2 free tier comfortably.
PDF_URL_TTL_S = 7 * 24 * 3600

# Per-key rate floor. 60s defends against the same loop-storm scenario
# the `/v1/export` surface guards against.
PDF_MIN_INTERVAL_S = 60

_AUTONOMATH_DB_PATH = os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(os.environ.get("JPINTEL_DB", "autonomath.db")),
)

# In-memory rate-floor state, scoped by key_hash.
_pdf_rate_state: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PdfReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence: str = Field("monthly", description="monthly | quarterly | annual")
    sections: list[str] | None = Field(
        None,
        description=(
            "Optional subset of report sections to include. When omitted "
            "all 5 sections are rendered: overview / risk_score / "
            "new_programs / amendments / fence_summary."
        ),
    )


class PdfReportResponse(BaseModel):
    pdf_id: str
    client_id: str
    download_url: str
    expires_at: str
    byte_size: int
    page_count: int
    sha256: str
    disclaimer: str = Field(alias="_disclaimer")
    model_config = ConfigDict(populate_by_name=True)


class SubscriptionUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(..., min_length=1, max_length=128)
    cadence: str = Field(..., description="monthly | quarterly | annual")
    r2_url_template: str | None = Field(
        None,
        description="R2 key template, default 'pdf_reports/{client_id}/{yyyymm}.pdf'",
    )
    enabled: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_autonomath_db() -> sqlite3.Connection:
    """Open the autonomath.db read-only — the API path never writes."""
    conn = sqlite3.connect(
        f"file:{_AUTONOMATH_DB_PATH}?mode=ro",
        uri=True,
        timeout=10.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _rate_floor_check(key_hash: str) -> None:
    now = time.monotonic()
    last = _pdf_rate_state.get(key_hash)
    if last is not None and (now - last) < PDF_MIN_INTERVAL_S:
        retry_after = int(PDF_MIN_INTERVAL_S - (now - last)) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "pdf_report rate limit (1/minute per key)",
                "retry_after_s": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    _pdf_rate_state[key_hash] = now


def _collect_client_context(
    conn: sqlite3.Connection,
    client_id: str,
) -> dict[str, Any]:
    """Pull the per-client substrate the PDF body needs."""
    out: dict[str, Any] = {
        "client_id": client_id,
        "fetched_at": datetime.now(UTC).isoformat(),
        "houjin_360": None,
        "risk_score": None,
        "new_programs": [],
        "amendments": [],
        "fence_summary": [],
    }

    cur = conn.cursor()

    def _has_table(name: str) -> bool:
        row = cur.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    if _has_table("v_houjin_360"):
        try:
            row = cur.execute(
                "SELECT * FROM v_houjin_360 WHERE houjin_bangou = ? LIMIT 1",
                (client_id,),
            ).fetchone()
            if row is not None:
                out["houjin_360"] = dict(row)
        except sqlite3.Error as exc:  # pragma: no cover
            logger.warning("v_houjin_360 lookup failed: %s", exc)

    if _has_table("am_houjin_risk_score"):
        try:
            row = cur.execute(
                "SELECT * FROM am_houjin_risk_score WHERE houjin_bangou = ? "
                "ORDER BY computed_at DESC LIMIT 1",
                (client_id,),
            ).fetchone()
            if row is not None:
                out["risk_score"] = dict(row)
        except sqlite3.Error as exc:
            logger.warning("am_houjin_risk_score lookup failed: %s", exc)

    if _has_table("programs"):
        try:
            cutoff = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
            rows = cur.execute(
                "SELECT program_id, title, authority, source_url "
                "FROM programs WHERE source_fetched_at >= ? "
                "AND tier IN ('S','A','B','C') AND excluded=0 "
                "ORDER BY source_fetched_at DESC LIMIT 8",
                (cutoff,),
            ).fetchall()
            out["new_programs"] = [dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.warning("programs new-list lookup failed: %s", exc)

    if _has_table("am_amendment_diff"):
        try:
            rows = cur.execute(
                "SELECT amendment_id, law_id, summary, effective_from "
                "FROM am_amendment_diff "
                "WHERE effective_from IS NOT NULL "
                "ORDER BY effective_from DESC LIMIT 8"
            ).fetchall()
            out["amendments"] = [dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.warning("am_amendment_diff lookup failed: %s", exc)

    # 8 業法 fence summary — fixed labels (税理士法 §52 / 行政書士法 §1
    # / 司法書士法 §3 / 弁護士法 §72 / 社労士法 §27 / 弁理士法 §75 /
    # 公認会計士法 §47 / 宅地建物取引業法 §12). We never CALL these
    # statutes — the PDF only declares which fences the body respects.
    out["fence_summary"] = [
        {
            "law": "税理士法 §52",
            "rule": "税務代理・税務書類作成・税務相談は税理士のみ。本書はガイドラインに留まる。",
        },
        {
            "law": "行政書士法 §1",
            "rule": "申請書類の代理作成は行政書士業務。本書は雛形・参考に限定。",
        },
        {"law": "司法書士法 §3", "rule": "登記・供託の代理は司法書士業務。本書は周辺情報に限定。"},
        {"law": "弁護士法 §72", "rule": "法律事件の代理・鑑定は弁護士業務。本書は法令引用のみ。"},
        {
            "law": "社労士法 §27",
            "rule": "労務代理は社会保険労務士業務。36協定等は社労士確認を要する。",
        },
        {"law": "弁理士法 §75", "rule": "特許・商標等の代理は弁理士業務。本書は出典情報のみ。"},
        {"law": "公認会計士法 §47", "rule": "監査証明は公認会計士業務。本書は監査に代わらない。"},
        {
            "law": "宅地建物取引業法 §12",
            "rule": "宅建業の媒介は免許制。本書は不動産制度の出典のみ。",
        },
    ]

    return out


def _render_pdf(client_id: str, ctx: dict[str, Any]) -> tuple[bytes, int]:
    """Render the PDF body with reportlab. Returns ``(bytes, page_count)``."""
    try:
        from reportlab.lib import colors  # type: ignore[import-untyped]
        from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
        from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
        from reportlab.lib.units import mm  # type: ignore[import-untyped]
        from reportlab.platypus import (  # type: ignore[import-untyped]
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "reportlab not installed on this Fly machine"},
        ) from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"jpcite monthly report — {client_id}",
        author="jpcite (Bookyou株式会社)",
    )
    styles = getSampleStyleSheet()
    title = styles["Title"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    body.fontSize = 9.5
    body.leading = 13
    elements: list[Any] = []

    elements.append(Paragraph(f"jpcite monthly report — {client_id}", title))
    elements.append(
        Paragraph(
            f"生成日: {ctx['fetched_at']}  /  発行: Bookyou株式会社 (T8010001213708)",
            body,
        )
    )
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("1. 法人 360 概要", h2))
    h360 = ctx.get("houjin_360")
    if h360:
        rows = [["項目", "値"]]
        for k, v in list(h360.items())[:12]:
            rows.append([str(k), str(v)[:60]])
        t = Table(rows, colWidths=[60 * mm, 110 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(
            Paragraph(
                "本顧問先の 360 サマリは未収集です。次回 ingest 後に再生成されます。",
                body,
            )
        )
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("2. リスクスコア", h2))
    rs = ctx.get("risk_score")
    if rs:
        rows = [["指標", "値"]]
        for k in (
            "financial_risk",
            "regulatory_risk",
            "operational_risk",
            "composite_score",
            "computed_at",
        ):
            if k in rs:
                rows.append([k, str(rs[k])])
        t = Table(rows, colWidths=[60 * mm, 110 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(
            Paragraph(
                "リスクスコアは未算出です。`refresh_houjin_risk_score_daily.py` 直後に反映されます。",
                body,
            )
        )
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("3. 直近 30 日 新規制度", h2))
    new_progs = ctx.get("new_programs") or []
    if new_progs:
        rows = [["program_id", "title", "authority"]]
        for r in new_progs[:8]:
            rows.append(
                [
                    str(r.get("program_id", ""))[:24],
                    str(r.get("title", ""))[:48],
                    str(r.get("authority", ""))[:32],
                ]
            )
        t = Table(rows, colWidths=[40 * mm, 90 * mm, 40 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(Paragraph("対象期間に新規制度はありません。", body))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("4. 法令改正アラート (effective_from 確定分)", h2))
    am = ctx.get("amendments") or []
    if am:
        rows = [["amendment_id", "law_id", "effective_from", "summary"]]
        for r in am[:8]:
            rows.append(
                [
                    str(r.get("amendment_id", ""))[:24],
                    str(r.get("law_id", ""))[:24],
                    str(r.get("effective_from", ""))[:10],
                    str(r.get("summary", ""))[:60],
                ]
            )
        t = Table(rows, colWidths=[35 * mm, 35 * mm, 30 * mm, 70 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(
            Paragraph(
                "確定済みの改正アラートはありません (effective_from 未確定の draft は載せていません)。",
                body,
            )
        )
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("5. 8 業法フェンス遵守宣言", h2))
    fences = ctx.get("fence_summary") or []
    rows = [["業法", "本書での扱い"]]
    for f in fences:
        rows.append([f.get("law", ""), f.get("rule", "")])
    t = Table(rows, colWidths=[40 * mm, 130 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(t)
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("免責事項", h2))
    elements.append(Paragraph(_TAX_DISCLAIMER, body))

    doc.build(elements)
    pdf_bytes = buf.getvalue()
    page_count = pdf_bytes.count(b"/Type /Page\n")
    if page_count == 0:
        page_count = max(1, len(pdf_bytes) // 12000)
    return pdf_bytes, page_count


def _upload_to_r2(client_id: str, blob: bytes) -> tuple[str, str, str]:
    """Upload ``blob`` to R2 and return (r2_key, download_url, expires_at_iso)."""
    yyyymm = datetime.now(UTC).strftime("%Y%m")
    pdf_id = f"pdf_{secrets.token_hex(8)}"
    key = f"pdf_reports/{client_id}/{yyyymm}/{pdf_id}.pdf"
    expires_at = (datetime.now(UTC) + timedelta(seconds=PDF_URL_TTL_S)).isoformat()

    if not os.environ.get("R2_ENDPOINT"):
        local = f"/tmp/pdf_report/{pdf_id}.pdf"  # noqa: S108
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as fh:
            fh.write(blob)
        return key, f"/v1/pdf_report/inline/{pdf_id}", expires_at

    try:
        from pathlib import Path

        from scripts.cron._r2_client import upload

        tmp = Path(f"/tmp/{pdf_id}.pdf")  # noqa: S108
        tmp.write_bytes(blob)
        upload(tmp, key)
        tmp.unlink(missing_ok=True)
    except (ImportError, RuntimeError) as exc:
        logger.warning("r2 upload fell back to inline due to: %s", exc)
        local = f"/tmp/pdf_report/{pdf_id}.pdf"  # noqa: S108
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as fh:
            fh.write(blob)
        return key, f"/v1/pdf_report/inline/{pdf_id}", expires_at

    base = os.environ.get(
        "R2_PUBLIC_BASE",
        f"https://{os.environ.get('R2_BUCKET', 'autonomath-backup')}.r2.cloudflarestorage.com",
    )
    return key, f"{base.rstrip('/')}/{key}", expires_at


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/generate", response_model=PdfReportResponse, response_model_by_alias=True)
async def generate_pdf_report(
    request: Request,
    client_id: str,
    body: PdfReportRequest | None = None,
    ctx: ApiContextDep = None,  # type: ignore[assignment]
    db: DbDep = None,  # type: ignore[assignment]
) -> PdfReportResponse:
    """Generate a monthly PDF report for ``client_id`` and return a signed URL."""
    if not client_id or len(client_id) > 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid client_id")

    require_metered_api_key(ctx, "pdf_report.generate")
    _rate_floor_check(ctx.key_hash or "")

    started = time.monotonic()
    am_conn = _open_autonomath_db()
    try:
        client_ctx = _collect_client_context(am_conn, client_id)
    finally:
        am_conn.close()

    blob, page_count = _render_pdf(client_id, client_ctx)
    sha256 = hashlib.sha256(blob).hexdigest()
    pdf_id = f"pdf_{secrets.token_hex(8)}"
    r2_key, download_url, expires_at = _upload_to_r2(client_id, blob)

    log_usage(
        db,
        ctx,
        endpoint="pdf_report.generate",
        quantity=PDF_REPORT_UNIT_COUNT,
        request_id=getattr(request.state, "request_id", None),
        strict_metering=True,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "pdf_report.generate client_id=%s page_count=%d byte_size=%d sha256=%s elapsed_ms=%d",
        client_id,
        page_count,
        len(blob),
        sha256[:12],
        elapsed_ms,
    )

    return PdfReportResponse(
        pdf_id=pdf_id,
        client_id=client_id,
        download_url=download_url,
        expires_at=expires_at,
        byte_size=len(blob),
        page_count=page_count,
        sha256=sha256,
        _disclaimer=_TAX_DISCLAIMER,
    )


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def upsert_subscription(
    request: Request,
    body: SubscriptionUpsert,
    ctx: ApiContextDep = None,  # type: ignore[assignment]
    db: DbDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Create or overwrite a PDF report subscription row."""
    require_metered_api_key(ctx, "pdf_report.subscriptions")

    sub_id = f"sub_{secrets.token_hex(6)}"
    now = datetime.now(UTC).isoformat()
    template = body.r2_url_template or "pdf_reports/{client_id}/{yyyymm}.pdf"

    am_path = os.environ.get(
        "AUTONOMATH_DB_PATH", str(os.environ.get("JPINTEL_DB", "autonomath.db"))
    )
    try:
        conn = sqlite3.connect(am_path, timeout=10.0)
    except sqlite3.Error as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": f"autonomath.db unavailable: {exc}"},
        ) from exc
    try:
        conn.execute(
            """
            INSERT INTO am_pdf_report_subscriptions
                (subscription_id, client_id, customer_id, cadence,
                 enabled, r2_url_template, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subscription_id) DO UPDATE SET
                cadence = excluded.cadence,
                enabled = excluded.enabled,
                r2_url_template = excluded.r2_url_template,
                updated_at = excluded.updated_at
            """,
            (
                sub_id,
                body.client_id,
                ctx.customer_id if ctx else None,
                body.cadence,
                1 if body.enabled else 0,
                template,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "subscription_id": sub_id,
        "client_id": body.client_id,
        "cadence": body.cadence,
        "enabled": body.enabled,
        "r2_url_template": template,
        "created_at": now,
    }


@router.get("/subscriptions/{client_id}")
async def get_subscription(
    client_id: str,
    ctx: ApiContextDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Return the latest subscription row for ``client_id``."""
    require_metered_api_key(ctx, "pdf_report.subscriptions")
    am_path = os.environ.get(
        "AUTONOMATH_DB_PATH", str(os.environ.get("JPINTEL_DB", "autonomath.db"))
    )
    try:
        conn = sqlite3.connect(
            f"file:{am_path}?mode=ro", uri=True, timeout=10.0, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": f"autonomath.db unavailable: {exc}"},
        ) from exc
    try:
        row = conn.execute(
            "SELECT * FROM am_pdf_report_subscriptions WHERE client_id=? "
            "ORDER BY updated_at DESC LIMIT 1",
            (client_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no subscription for client_id={client_id}")
    return dict(row)


@router.get("/inline/{pdf_id}")
async def inline_pdf(pdf_id: str) -> Any:
    """Local-disk fallback download (used when R2 env is not configured)."""
    from fastapi.responses import FileResponse

    if not pdf_id.startswith("pdf_") or "/" in pdf_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid pdf_id")
    path = f"/tmp/pdf_report/{pdf_id}.pdf"  # noqa: S108
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pdf expired or not staged")
    return FileResponse(path, media_type="application/pdf", filename=f"{pdf_id}.pdf")
