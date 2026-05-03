"""Did-you-mean suggester for unknown query parameters (R12 §2.1, W2-3 D1).

Background
----------
The :class:`StrictQueryMiddleware` (sibling module ``strict_query.py``)
returns HTTP 422 with ``unknown_query_parameter`` when a caller passes a
query key that no declared :class:`Depends` / :class:`Query` parameter
on the matched route consumes. The R12 audit (2026-05-03) walked the
"developer first 5 minutes" path and found that a pure
``perfecture=東京`` typo (Levenshtein 1 from ``prefecture``) yields the
full closed list of allowed keys but no nudge — devs and LLM agents
both spend cycles diffing the lists by eye.

This module supplies a single stdlib helper, :func:`suggest_query_keys`,
backed by :func:`difflib.get_close_matches`. It is intentionally tiny
and stateless so the middleware can stay focused on the routing/matching
walk and the suggester can be unit-tested in isolation.

Design notes
------------
* **stdlib only.** ``difflib`` ships with CPython — no rapidfuzz wheel
  to add to the deploy bundle, no extra import time on cold start.
* **Case-insensitive comparison, original-case echo.** Caller might
  send ``Perfecture`` or ``PREFECTURE``; we lowercase both sides for the
  Levenshtein-ish ratio but echo back the canonical (declared) key in
  its original casing so the suggestion is copy-paste correct.
* **Cutoff 0.6.** Default for :func:`difflib.get_close_matches`. Hits
  ``perfecture → prefecture`` (single-char insert), ``query → q``
  (substring), and other common typos while filtering out unrelated
  short keys.
* **Flat dict shape.** Returns ``{unknown_key: suggested_key, ...}`` —
  not a list of tuples — so SDKs can index into it by the unknown key
  directly. Keys with no close match are omitted (vs returning ``None``)
  so downstream iteration is trivial.
* **No suggestion ⇒ omit.** Wire shape carries an empty dict in that
  case (still serialised as ``did_you_mean: {}``) — ``make_error``
  drops only literal ``None`` values, but an empty dict is a meaningful
  "we tried, no match" signal that callers can short-circuit on.
"""

from __future__ import annotations

import difflib

__all__ = ["suggest_query_keys"]

# Similarity cutoff for difflib.get_close_matches. 0.6 is the difflib
# default and empirically lands on the cases we care about (single-char
# insert/swap, substring containment) without dragging in unrelated
# keys.
_CUTOFF: float = 0.6


def suggest_query_keys(unknown: list[str], expected: list[str]) -> dict[str, str]:
    """Map each unknown query key → closest expected key.

    Parameters
    ----------
    unknown
        Query keys the caller sent that the matched route did not
        declare. Order is preserved by ``difflib`` — callers typically
        pass an already-sorted list so the wire shape is deterministic.
    expected
        The closed set of declared query keys for the matched route.
        Includes alias names (FastAPI surfaces the alias as the wire
        name on the ``ModelField``).

    Returns
    -------
    dict[str, str]
        ``{unknown_key: suggested_expected_key}`` for every unknown key
        whose closest expected match scores ≥ :data:`_CUTOFF`. Keys
        with no match are omitted.

    Examples
    --------
    >>> suggest_query_keys(
    ...     ["perfecture"], ["prefecture", "tier", "limit", "q"]
    ... )
    {'perfecture': 'prefecture'}

    >>> suggest_query_keys(["totally_made_up"], ["prefecture"])
    {}
    """
    if not unknown or not expected:
        return {}

    # Build a lowercase index so the comparison is case-insensitive but
    # the echo is canonical-cased.
    lower_to_canonical: dict[str, str] = {}
    for e in expected:
        lower_to_canonical.setdefault(e.lower(), e)

    out: dict[str, str] = {}
    for u in unknown:
        cand = difflib.get_close_matches(
            u.lower(), list(lower_to_canonical.keys()), n=1, cutoff=_CUTOFF
        )
        if not cand:
            continue
        out[u] = lower_to_canonical[cand[0]]
    return out
