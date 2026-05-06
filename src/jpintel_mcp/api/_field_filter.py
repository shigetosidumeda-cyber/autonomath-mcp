"""Partial-response (`?fields=`) projection helper.

Customer-side LLM contexts pay per token both ways. This helper lets a
caller opt in to a sparse projection of an existing response envelope so
only the fields they actually consume are paid for.

Design invariants
-----------------

* **Opt-in only.** Callers who omit ``?fields=`` get the unmodified full
  envelope. Default behaviour is unchanged so legacy SDKs / cron jobs
  never break.
* **Protected envelope keys are never stripped.** ``_disclaimer``,
  ``corpus_snapshot_id``, ``corpus_checksum``, ``audit_seal``, and
  ``_billing_unit`` form the legal-responsibility wrapper around every
  metered response (景表法 / 消費者契約法 / 会計士 reproducibility / Stripe
  metered billing audit). Stripping any of them risks turning a citation-
  bearing answer into an unattributed claim. The helper enforces this even
  if the caller explicitly requests a narrower projection.
* **Dotted paths** (``results.id,results.name``) are first-class so list
  endpoints can shrink each row item without the caller having to know the
  envelope's outer keys.
* **Unknown / malformed field tokens are silently ignored** rather than
  raising. Customer agents over-ask for safety; a typo in one token must
  not blow up the entire response.

Wire shape
----------

Returns the same dict (mutated copy — input is not mutated) with non-
selected keys dropped. Outer envelope keys not on the projection list are
removed; protected keys stay regardless.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

#: Fields that MUST survive every projection. These carry the legal +
#: billing envelope and identify the corpus state the response was
#: computed against. Removing any of them would orphan downstream audit /
#: reproducibility / billing flows.
PROTECTED_FIELDS: frozenset[str] = frozenset(
    {
        "_disclaimer",
        "_disclaimer_en",
        "_disclaimer_gbiz",
        "_attribution",
        "corpus_snapshot_id",
        "corpus_checksum",
        "audit_seal",
        "_billing_unit",
    }
)


def _parse_fields(fields_str: str) -> tuple[set[str], dict[str, set[str]]]:
    """Parse a ``fields=`` query string into top-level + nested selectors.

    Examples
    --------
    >>> _parse_fields("id,name,source_url")
    ({'id', 'name', 'source_url'}, {})
    >>> _parse_fields("results.id,results.name,total")
    ({'total', 'results'}, {'results': {'id', 'name'}})
    """
    top: set[str] = set()
    nested: dict[str, set[str]] = {}
    if not fields_str:
        return top, nested
    for raw in fields_str.split(","):
        token = raw.strip()
        if not token:
            continue
        if "." in token:
            parent, _, child = token.partition(".")
            parent = parent.strip()
            child = child.strip()
            if not parent or not child:
                continue
            top.add(parent)
            nested.setdefault(parent, set()).add(child)
        else:
            top.add(token)
    return top, nested


def _project_dict(
    obj: dict[str, Any],
    keep: set[str],
    nested: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Return a shallow dict projection that always keeps protected keys."""
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if k in PROTECTED_FIELDS or k in keep:
            if nested and k in nested and isinstance(v, list):
                child_keep = nested[k]
                projected_list: list[Any] = []
                for item in v:
                    if isinstance(item, dict):
                        projected_list.append(_project_dict(item, child_keep, None))
                    else:
                        projected_list.append(item)
                out[k] = projected_list
            elif nested and k in nested and isinstance(v, dict):
                out[k] = _project_dict(v, nested[k], None)
            else:
                out[k] = v
    return out


def apply_fields_filter(envelope: dict[str, Any], fields_str: str | None) -> dict[str, Any]:
    """Project ``envelope`` down to ``fields_str``-selected keys.

    Parameters
    ----------
    envelope:
        Full response dict (already JSON-serialisable).
    fields_str:
        Comma-separated field selector from ``?fields=``. ``None`` or empty
        returns the envelope unchanged (deep-copied for safety).

    Returns
    -------
    dict
        New dict — input is never mutated. Protected fields
        (:data:`PROTECTED_FIELDS`) are always included.

    Behaviour
    ---------
    * Top-level only: ``fields=id,name`` keeps those keys plus protected
      ones.
    * Dotted: ``fields=results.id,results.name`` projects each list/dict
      child of ``results`` to only those fields.
    * Mixed: ``fields=total,results.id`` keeps ``total`` and projects
      ``results``.
    * Unknown fields are ignored (no error).
    * Non-dict input is returned unchanged.
    """
    if not isinstance(envelope, dict):
        return envelope
    if not fields_str:
        return deepcopy(envelope)
    keep, nested = _parse_fields(fields_str)
    if not keep and not nested:
        return deepcopy(envelope)
    # deepcopy first so callers/cache layers never see in-place mutation.
    src = deepcopy(envelope)
    return _project_dict(src, keep, nested)


__all__ = ["PROTECTED_FIELDS", "apply_fields_filter"]
