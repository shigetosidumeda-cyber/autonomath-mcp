"""Hepburn romaji slug helper for per-program static page URLs.

The static site emits one HTML file per indexable program at
`site/programs/{slug}.html`, where `slug = {hepburn-romaji}-{sha1-6}`.
The same slug must be reproducible from the API so result cards / share
URLs / API responses can link to the right page.

This module is the single source of truth for that derivation. The
generator script (`scripts/generate_program_pages.py`) and the FastAPI
runtime both import `program_static_slug()` and `program_static_url()`
from here so they cannot drift.

pykakasi is in the `[site]` optional-dependency group (`pyproject.toml`)
and is also installed by the production Dockerfile (`pip install
".[site]"`). The import is therefore safe at API boot. A graceful
fallback path (sha1-6 only) is kept for defensive use in test
environments where pykakasi is not present.
"""

from __future__ import annotations

import hashlib
import re

_KKS: object | None
try:  # pragma: no cover — exercised via integration only
    import pykakasi  # type: ignore[import-untyped]

    _KKS = pykakasi.kakasi()
except ImportError:  # pragma: no cover — fallback path
    _KKS = None


_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def program_static_slug(primary_name: str | None, unified_id: str) -> str:
    """Produce ``{hepburn-romaji}-{sha1-6}``.

    Mirrors ``scripts/generate_program_pages.py::slugify`` exactly. Any
    change here must be made there too — the static page filenames are
    written by that script and resolved by this function.

    - hepburn romaji via pykakasi (JA → ASCII-ish)
    - lowercase + non-[a-z0-9] collapsed to '-'
    - cap at 60 chars, trim at last word boundary
    - sha1-6 of unified_id as collision-free suffix
    """
    romaji = ""
    if _KKS is not None:
        try:
            parts = _KKS.convert(primary_name or "")  # type: ignore[attr-defined]
            romaji = " ".join(p.get("hepburn", "") for p in parts)
        except Exception:  # pragma: no cover — defensive
            romaji = ""
    romaji = romaji.lower()
    ascii_only = _NON_SLUG_RE.sub("-", romaji).strip("-")

    if len(ascii_only) > 60:
        truncated = ascii_only[:60]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        ascii_only = truncated
    if not ascii_only:
        ascii_only = "program"

    suffix = hashlib.sha1(unified_id.encode("utf-8")).hexdigest()[:6]
    return f"{ascii_only}-{suffix}"


def program_static_url(
    primary_name: str | None,
    unified_id: str,
    *,
    domain: str | None = None,
) -> str:
    """Return the canonical static-page path or absolute URL.

    With ``domain=None`` (default), returns a site-relative path
    (``/programs/{slug}.html``) suitable for use in API responses where
    the consumer joins with their own host. Pass ``domain="jpcite.com"``
    (or similar) to produce an absolute URL.
    """
    slug = program_static_slug(primary_name, unified_id)
    rel = f"/programs/{slug}.html"
    if not domain:
        return rel
    return f"https://{domain.rstrip('/')}{rel}"
