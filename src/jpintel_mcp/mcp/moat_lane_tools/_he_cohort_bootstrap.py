"""Fragment-file loader for HE-5 / HE-6 cohort-specific extensions.

Registered as a single entry in ``moat_lane_tools/__init__._SUBMODULES``
so the cohort-specific packages (``he5_cohort_deep`` /
``he6_cohort_ultra``) are discovered through this bootstrap rather than
hardcoded into the registry tuple. Adding a new cohort tool family is
then a single-line edit to ``he_cohort_fragment.yaml`` — no edit to
``__init__.py`` and therefore no parallel-lane contention.
"""

from __future__ import annotations

import importlib
import logging
import pathlib

logger = logging.getLogger("jpintel.mcp.moat_lane_tools._he_cohort_bootstrap")


def _parse_fragment_packages(text: str) -> list[str]:
    """Extract ``- package: NAME`` rows from the minimal YAML manifest."""
    fragments: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- package:"):
            name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if name:
                fragments.append(name)
    return fragments


def _load() -> None:
    manifest_path = pathlib.Path(__file__).resolve().parent / "he_cohort_fragment.yaml"
    if not manifest_path.exists():
        logger.debug("HE cohort bootstrap: manifest absent, nothing to load")
        return
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("HE cohort bootstrap: cannot read manifest: %s", exc)
        return
    fragments = _parse_fragment_packages(text)
    if not fragments:
        logger.debug("HE cohort bootstrap: manifest empty")
        return
    parent_pkg = __name__.rsplit(".", 1)[0]
    for pkg in fragments:
        try:
            importlib.import_module(f"{parent_pkg}.{pkg}")
        except ModuleNotFoundError:
            logger.debug("HE cohort bootstrap: skipping missing package %s", pkg)
        except ImportError as exc:
            logger.warning("HE cohort bootstrap: failed to import %s: %s", pkg, exc)


_load()


__all__ = ["_parse_fragment_packages"]
