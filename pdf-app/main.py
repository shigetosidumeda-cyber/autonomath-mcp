"""jpcite-pdf: weasyprint-based PDF render for artifact viewer."""
from __future__ import annotations
import os
import httpx
from fastapi import FastAPI, HTTPException, Response
from weasyprint import HTML, CSS  # type: ignore[import-untyped]


app = FastAPI(title="jpcite-pdf", version="0.1.0")
JPCITE_API_BASE = os.environ.get("JPCITE_API_BASE", "https://api.jpcite.com")
PDF_RENDER_TIMEOUT = int(os.environ.get("PDF_RENDER_TIMEOUT_SEC", "30"))


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "jpcite-pdf", "version": "0.1.0"}


@app.get("/pdf/{pack_id}")
def render_pdf(pack_id: str) -> Response:
    """Render artifact PDF from /v1/artifacts/{pack_id} JSON."""
    # Fetch artifact JSON from main API
    try:
        with httpx.Client(timeout=PDF_RENDER_TIMEOUT) as client:
            r = client.get(f"{JPCITE_API_BASE}/v1/artifacts/{pack_id}")
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail="artifact_not_found")
            r.raise_for_status()
            artifact = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"upstream_error: {e}")

    # Build HTML
    html_str = _render_html(artifact)

    # Render PDF
    try:
        pdf_bytes = HTML(string=html_str).write_pdf(
            stylesheets=[CSS(string="@page { size: A4; margin: 1.5cm; } body { font-family: 'Helvetica', sans-serif; font-size: 11pt; line-height: 1.5; }")],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"render_error: {e}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pack_id}.pdf"',
            "Cache-Control": "public, max-age=86400",
        },
    )


def _render_html(artifact: dict) -> str:
    """Build minimal artifact HTML for weasyprint."""
    pack_id = artifact.get("pack_id", "unknown")
    headline = artifact.get("headline", pack_id)
    units = artifact.get("billable_units_consumed", 0)
    tier = artifact.get("tier", "unknown")
    created_at = artifact.get("created_at", "")
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>{_esc(headline)}</title></head>
<body>
<header style="border-bottom: 2px solid #0a4d8c; padding-bottom: 8pt; margin-bottom: 16pt">
  <p style="margin:0;color:#0a4d8c;font-weight:bold;font-size:10pt">jpcite Artifact</p>
  <h1 style="margin:8pt 0 0;font-size:18pt">{_esc(headline)}</h1>
  <p style="margin:8pt 0 0;color:#64748b;font-size:9pt">pack_id: {_esc(pack_id)} / tier: {_esc(tier)} / units: {units} / {_esc(created_at)}</p>
</header>
<main>
<p>本書面は公開情報の機械整形であり、最終判断は資格専門家 (税理士・弁護士・行政書士・司法書士・社労士・中小企業診断士・弁理士) にご相談ください。</p>
<!-- TODO Wave 9: render 7 sections (baseline / insights / parts / queue / receipts / gaps / followup) -->
</main>
<footer style="margin-top:32pt;padding-top:8pt;border-top:1px solid #e2e8f0;color:#64748b;font-size:8pt">
  <p>Bookyou株式会社 (T8010001213708) / info@bookyou.net / https://jpcite.com</p>
</footer>
</body></html>"""


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
