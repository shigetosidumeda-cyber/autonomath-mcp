"""Tree-definition loader.

Rule trees are curated as JSON under ``data/rule_trees/<tree_id>.json``
so operators can update eligibility logic without code changes.  The
loader resolves the data directory in this order:

1. ``JPCITE_RULE_TREES_DIR`` env var (escape hatch for tests + alt deploys).
2. ``$REPO_ROOT/data/rule_trees`` (the canonical production path).

Trees are validated through :class:`jpintel_mcp.rule_tree.models.RuleTree`,
so a malformed JSON file fails at load time with a Pydantic
``ValidationError`` rather than at first eval.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import RuleTree

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DIR = _REPO_ROOT / "data" / "rule_trees"


def _resolve_dir() -> Path:
    """Return the directory holding ``<tree_id>.json`` files."""
    override = os.environ.get("JPCITE_RULE_TREES_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_DIR


def load_rule_tree(tree_id: str, *, root_dir: Path | None = None) -> RuleTree:
    """Load and validate a tree from disk.

    Parameters
    ----------
    tree_id:
        Filename stem under the data directory (no path traversal — a
        ``/`` or ``..`` in ``tree_id`` is rejected).
    root_dir:
        Optional override (tests inject a tmp path here).  Falls back
        to :func:`_resolve_dir` when ``None``.

    Raises
    ------
    FileNotFoundError
        Tree file does not exist in the resolved directory.
    ValueError
        ``tree_id`` contains a path separator.
    pydantic.ValidationError
        Tree JSON is malformed (shape mismatch, typo'd field, etc.).
    """
    if "/" in tree_id or "\\" in tree_id or ".." in tree_id:
        raise ValueError(f"invalid tree_id (path traversal): {tree_id!r}")
    if not tree_id:
        raise ValueError("tree_id must be non-empty")
    base = (root_dir or _resolve_dir()).resolve()
    path = (base / f"{tree_id}.json").resolve()
    # Containment guard — confirm the resolved path is still under the
    # data directory after symlink resolution.  Without this a symlink
    # inside data/rule_trees pointing to /etc/passwd would still load.
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"resolved tree path {path!s} escapes data root {base!s}"
        ) from exc
    if not path.is_file():
        raise FileNotFoundError(f"rule tree file not found: {path!s}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    # If the JSON file omits "tree_id" allow the filename stem to act
    # as the default so trees don't drift between filename + content.
    payload.setdefault("tree_id", tree_id)
    return RuleTree.model_validate(payload)


def list_rule_trees(*, root_dir: Path | None = None) -> list[str]:
    """Return every available ``tree_id`` (sorted) in the data directory.

    Returns an empty list when the directory is missing (so callers
    can probe availability without try/except).
    """
    base = (root_dir or _resolve_dir()).resolve()
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.json") if p.is_file())


__all__ = ["list_rule_trees", "load_rule_tree"]
