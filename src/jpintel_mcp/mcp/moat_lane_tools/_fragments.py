"""Moat lane fragment loader (non-invasive submodule extension).

The canonical ``__init__.py`` _SUBMODULES tuple is the historical
registry for the M*/N*/HE* moat surface. New lanes (GG / FF / SS) are
loaded *additively* by listing their submodule names in
``_register_fragments.yaml``. This keeps ``__init__.py`` untouched —
parallel agents working on the moat surface no longer collide on the
same tuple line range.

Loader semantics
----------------
* Reads ``_register_fragments.yaml`` next to this module.
* For each name under ``submodules:`` it ``importlib.import_module`` the
  full dotted path. Import side-effects register MCP tools via
  ``@mcp.tool``.
* ``ModuleNotFoundError`` is silenced (partial-checkout safe).
* Real ``ImportError`` is logged but never raised — boot continues with
  the LIVE moat surface intact.
* The YAML parser is intentionally minimal (no pyyaml dependency in
  this seam) so loader boot stays at zero new imports.

Bootstrapping
-------------
``_shared.py`` imports this module exactly once at first use. Because
21 of the existing moat submodules import ``_shared`` already, the
fragment loader is exercised on every server boot path *without*
editing ``__init__.py``.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger("jpintel.mcp.moat_lane_tools._fragments")

_FRAGMENT_FILE = Path(__file__).resolve().parent / "_register_fragments.yaml"

# Module-level flag so the loader runs exactly once even if many
# submodules import _shared concurrently.
_LOADED: bool = False


def _parse_submodules(yaml_text: str) -> list[str]:
    """Tiny YAML subset parser — extracts the ``submodules:`` list.

    Accepts the canonical shape::

        submodules:
          - get_outcome_with_chunks
          - some_other_lane

    Lines starting with ``#`` are comments. Anything outside the
    ``submodules:`` block is ignored. We avoid pulling in pyyaml here
    so the moat surface boot remains dependency-light.
    """
    out: list[str] = []
    in_block = False
    for raw in yaml_text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        if not in_block:
            if stripped.startswith("submodules:"):
                in_block = True
            continue
        # Inside the submodules block.
        if not line.startswith((" ", "\t")):
            # Top-level key — block ended.
            in_block = False
            continue
        if stripped.startswith("- "):
            name = stripped[2:].strip().strip('"').strip("'")
            if name:
                out.append(name)
    return out


def load_fragments() -> int:
    """Load every fragment submodule listed in the YAML.

    Returns the count of successfully imported submodules (0 when the
    YAML is missing). Safe to call repeatedly; subsequent calls are
    no-ops once the loader has run once.
    """
    global _LOADED
    if _LOADED:
        return 0
    _LOADED = True
    if not _FRAGMENT_FILE.exists():
        return 0
    try:
        yaml_text = _FRAGMENT_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("fragment loader: cannot read %s: %s", _FRAGMENT_FILE, exc)
        return 0
    names = _parse_submodules(yaml_text)
    pkg = __name__.rsplit(".", 1)[0]
    loaded = 0
    for name in names:
        try:
            importlib.import_module(f"{pkg}.{name}")
            loaded += 1
        except ModuleNotFoundError:
            logger.debug("fragment loader: submodule %s absent — skipping", name)
        except ImportError as exc:
            logger.warning("fragment loader: failed to import %s: %s", name, exc)
    return loaded
