"""Sitemap audit endpoint — companion-Markdown coverage stats.

Wave 41 Agent F — expose the live state of ``site/sitemap-companion-md.xml``
and the actual ``site/{cat}/*.md`` inventory on disk so downstream agents and
external SEO crawlers can verify coverage without parsing the 3 MB sitemap
themselves.

Public + unmetered. Anonymous IP quota applies via ``AnonIpLimitDep``. The
endpoint is read-only and pulls from disk every request (no caching) because
the sitemap is regenerated multiple times per day on chunk-push waves and
stale numbers would defeat the audit purpose.

Endpoints
---------
    GET /v1/audit/sitemap?type=companion-md
        Roll-up coverage: { sitemap_url_count, on_disk_md_count, gap,
        by_category: {cases, laws, enforcement}, generated_at }

Memory references
-----------------
- feedback_no_priority_question : no MVP / phase / tier framing.
- project_jpcite_2026_05_07_state : 9,178 sitemap URL surface live.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status

_log = logging.getLogger("jpintel.api.sitemap_audit")

router = APIRouter(prefix="/v1/audit", tags=["audit"])

# Resolve repo root relative to this file. ``src/jpintel_mcp/api/sitemap_audit.py``
# → parents[3] is the repo root. We resolve at import time so a Fly volume mount
# pointing at /app does not break the lookup at runtime.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SITE_DIR = _REPO_ROOT / "site"
_SITEMAP_COMPANION_MD = _SITE_DIR / "sitemap-companion-md.xml"

_CATEGORIES: tuple[str, ...] = ("cases", "laws", "enforcement")
_URL_RE = re.compile(r"<loc>([^<]+)</loc>")


def _count_sitemap_urls() -> tuple[int, dict[str, int]]:
    """Return (total_url_count, per-category-count) from the companion-md sitemap.

    Per-category counts are derived from the URL path component: a <loc>
    pointing at ``https://jpcite.com/cases/<slug>.md`` is bucketed into
    ``cases``. Anything outside the three known buckets is summed into
    ``other`` (defensive — should be empty in production).
    """
    if not _SITEMAP_COMPANION_MD.exists():
        return (0, {c: 0 for c in _CATEGORIES})
    text = _SITEMAP_COMPANION_MD.read_text(encoding="utf-8")
    urls = _URL_RE.findall(text)
    by_cat: dict[str, int] = {c: 0 for c in _CATEGORIES}
    other = 0
    for u in urls:
        matched = False
        for cat in _CATEGORIES:
            if f"/{cat}/" in u:
                by_cat[cat] += 1
                matched = True
                break
        if not matched:
            other += 1
    if other:
        by_cat["other"] = other
    return (len(urls), by_cat)


def _count_on_disk_md() -> tuple[int, dict[str, int]]:
    """Return (total_md_files, per-category-count) under site/{cat}/*.md.

    Excludes ``index.md`` and ``README.md`` — those are surface-level
    indexes, not companion-Markdown records.
    """
    by_cat: dict[str, int] = {c: 0 for c in _CATEGORIES}
    total = 0
    for cat in _CATEGORIES:
        cat_dir = _SITE_DIR / cat
        if not cat_dir.is_dir():
            continue
        count = 0
        for p in cat_dir.iterdir():
            if not p.is_file() or p.suffix != ".md" or p.name in {"index.md", "README.md"}:
                continue
            count += 1
        by_cat[cat] = count
        total += count
    return (total, by_cat)


def _coverage_envelope() -> dict[str, Any]:
    sitemap_total, sitemap_by_cat = _count_sitemap_urls()
    disk_total, disk_by_cat = _count_on_disk_md()
    gap = sitemap_total - disk_total
    coverage_pct = round(disk_total / sitemap_total * 100, 2) if sitemap_total else 0.0
    per_cat: dict[str, dict[str, int]] = {}
    for cat in _CATEGORIES:
        per_cat[cat] = {
            "sitemap_urls": sitemap_by_cat.get(cat, 0),
            "on_disk_md": disk_by_cat.get(cat, 0),
            "gap": sitemap_by_cat.get(cat, 0) - disk_by_cat.get(cat, 0),
        }
    if "other" in sitemap_by_cat:
        per_cat["other"] = {
            "sitemap_urls": sitemap_by_cat["other"],
            "on_disk_md": 0,
            "gap": sitemap_by_cat["other"],
        }
    # Render the sitemap path relative to repo root when possible — falls back
    # to the absolute path in test environments where the sitemap lives in a
    # tmp_path outside of REPO_ROOT.
    try:
        sitemap_path_str = str(_SITEMAP_COMPANION_MD.relative_to(_REPO_ROOT))
    except ValueError:
        sitemap_path_str = str(_SITEMAP_COMPANION_MD)
    return {
        "type": "companion-md",
        "sitemap_url_count": sitemap_total,
        "on_disk_md_count": disk_total,
        "gap": gap,
        "coverage_pct": coverage_pct,
        "by_category": per_cat,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sitemap_path": sitemap_path_str,
    }


@router.get(
    "/sitemap",
    summary="Sitemap coverage audit",
    description=(
        "Return current coverage of `sitemap-companion-md.xml` vs the actual "
        "`.md` files on disk. Useful for verifying CF Pages propagation and "
        "detecting gaps where the sitemap leads the chunk-push pipeline. "
        "Public + unmetered. Anonymous IP quota applies."
    ),
)
def get_sitemap_audit(
    type: Annotated[
        Literal["companion-md"],
        Query(description="Sitemap surface to audit. Currently only 'companion-md'."),
    ] = "companion-md",
) -> dict[str, Any]:
    """Return coverage rollup for the requested sitemap surface."""
    if type != "companion-md":
        # Defensive — pydantic Literal already constrains this, but keep the
        # 422 path explicit so future surfaces can be added cleanly.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported sitemap type: {type}",
        )
    return _coverage_envelope()


