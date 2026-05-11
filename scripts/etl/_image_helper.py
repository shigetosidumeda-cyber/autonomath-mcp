"""_image_helper.py — sips-backed image post-processing for ETL screenshots.

Background
----------
Claude Code's `Read` tool crashes on PNG/JPEG inputs > 1900 px on the
long axis. The operator memory `feedback_image_resize` documents this
hard ceiling: every screenshot the helper layer ever writes must be
≤ 1600 px to survive the CLI. We use macOS `sips` because it is the
zero-dependency native binary, present on every operator session, and
loss-less enough for debug-grade screenshots.

On Linux GHA runners `sips` is absent — we degrade gracefully via
Pillow if it's importable, else leave the image untouched (the
screenshot is debug-only on the runner side, the operator will not
Read it from there). All paths return successfully so callers don't
need to try/except.

Public surface
--------------
    sips_resize_inplace(path, max_width=1600)
        Resize `path` to at most `max_width` px wide, preserving aspect.

    is_cli_safe(path)
        Return True iff the image's long axis ≤ 1600 px.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("jpcite.etl.image_helper")

MAX_CLI_SAFE_PX = 1600


def _have_sips() -> bool:
    """Return True iff `sips` is on PATH (macOS operator sessions)."""
    return shutil.which("sips") is not None


def _sips_dimensions(path: Path) -> tuple[int, int] | None:
    """Probe (width, height) via `sips -g`; None on failure."""
    if not _have_sips():
        return None
    try:
        out = subprocess.check_output(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("sips probe failed for %s: %s", path, exc)
        return None
    w = h = -1
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            w = int(line.split(":", 1)[1].strip())
        elif line.startswith("pixelHeight:"):
            h = int(line.split(":", 1)[1].strip())
    if w <= 0 or h <= 0:
        return None
    return w, h


def _sips_resize(path: Path, max_width: int) -> bool:
    """In-place resize via sips. Returns True on success."""
    if not _have_sips():
        return False
    try:
        subprocess.check_call(
            ["sips", "--resampleWidth", str(max_width), str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("sips resize failed for %s: %s", path, exc)
        return False


def _pillow_resize(path: Path, max_width: int) -> bool:
    """Fallback resize via Pillow if installed (Linux runners)."""
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        with Image.open(path) as img:
            w, h = img.size
            if w <= max_width:
                return True
            ratio = max_width / float(w)
            new_h = max(1, int(h * ratio))
            resized = img.resize((max_width, new_h), Image.LANCZOS)
            resized.save(path)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("Pillow resize failed for %s: %s", path, exc)
        return False


def sips_resize_inplace(path: Path | str, *, max_width: int = MAX_CLI_SAFE_PX) -> None:
    """Resize `path` so its width is at most `max_width` px.

    Tries `sips` first (operator macOS sessions), then Pillow
    (Linux GHA runners), then degrades silently. Never raises —
    screenshots are debug-only and must not break the ETL flow.
    """
    p = Path(path)
    if not p.exists():
        logger.debug("sips_resize_inplace: missing path %s", p)
        return

    if max_width > MAX_CLI_SAFE_PX:
        logger.warning(
            "max_width=%d > %d ceiling — clamping for CLI safety",
            max_width,
            MAX_CLI_SAFE_PX,
        )
        max_width = MAX_CLI_SAFE_PX

    dims = _sips_dimensions(p)
    if dims is not None and dims[0] <= max_width:
        # Already CLI-safe — no rewrite needed.
        return

    if _sips_resize(p, max_width):
        return

    if _pillow_resize(p, max_width):
        return

    logger.debug(
        "no resize tool available; leaving %s untouched (debug-only screenshot)",
        p,
    )


def is_cli_safe(path: Path | str) -> bool:
    """Return True iff `path`'s long axis is ≤ MAX_CLI_SAFE_PX."""
    p = Path(path)
    dims = _sips_dimensions(p)
    if dims is None:
        # Without dimensions we can't be sure; assume unsafe and let
        # the caller resize defensively.
        return False
    return max(dims) <= MAX_CLI_SAFE_PX
