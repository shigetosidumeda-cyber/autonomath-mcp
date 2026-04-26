"""Japanese currency parsing/formatting utilities.

Pure-stdlib helpers that turn human-written Japanese money strings into
``int`` yen (and back).  Inspired by ``Autonomath/backend/accounting_helpers``
which used a one-liner regex (``r"[,\\s¥￥円]"``) to clean noise before
``float()``; this module hardens that idea for the wider variety of forms
that show up in 補助金 / 融資 / 税制 documents (万 / 億 / △ / parentheses /
ranges / full-width digits / mixed numerals).

Public API:
    parse_yen(s)       -> int                  # one value
    parse_yen_range(s) -> tuple[int, int]      # "100万〜500万" etc.
    format_yen(n)      -> str                  # 1500 -> "1,500円"

Design notes:
    * 万 = 10_000, 億 = 100_000_000.  Mixed forms ("1億2,000万") are
      additive: each token's numeral times its trailing unit, summed.
    * Negative markers: ``△`` ``▲`` (Japanese accounting), ``-`` ``−`` ``ー``
      (ASCII / Unicode minus / chouon used colloquially), and matched
      parentheses ``(500)`` / ``（500）``.
    * Percentage strings ('50%', '50％') raise ``ValueError`` — they are
      rates, not amounts, and silently coercing them would corrupt downstream
      eligibility math.
    * Floats are truncated, not rounded (``int(1000.7) == 1000``).  This
      matches accounting convention where partial yen are dropped.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["parse_yen", "parse_yen_range", "format_yen"]


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_OKU = 100_000_000
_MAN = 10_000

# Noise that surrounds a numeric token but carries no value:
#   ¥ ￥ 円 commas whitespace
_NOISE_RE = re.compile(r"[,\s¥￥]")

# Unit + numeral token finder used after noise stripping.
# Captures groups: (numeral, unit) where unit ∈ {億, 万, ""}.
# Numeral is digits + optional decimal point.
_TOKEN_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(億|万)?")

# Range separator candidates (post-NFKC, post-noise).
# Note: keep the literal "から" check in code, not regex, so we don't
# accidentally split numerals that contain it (none do, but explicit > clever).
_RANGE_SEPARATORS: tuple[str, ...] = ("〜", "~", "から", "-", "–", "—", "ー")

# Negative markers that prefix a number (Japanese accounting + ASCII / Unicode).
_NEG_PREFIXES: tuple[str, ...] = ("△", "▲", "-", "−", "ー")


def _normalize(raw: str) -> str:
    """NFKC + strip + noise removal.  Does NOT strip 円 (caller decides)."""
    s = unicodedata.normalize("NFKC", raw).strip()
    return s


def _strip_yen_suffix(s: str) -> str:
    """Drop trailing ``円`` (one or many).  Internal-only."""
    while s.endswith("円"):
        s = s[:-1]
    return s


def _strip_paren_negative(s: str) -> tuple[str, bool]:
    """If wrapped in matching parens, strip them and report negative."""
    s = s.strip()
    if (
        len(s) >= 2
        and s[0] in ("(", "（")
        and s[-1] in (")", "）")
    ):
        return s[1:-1].strip(), True
    return s, False


def _strip_neg_prefix(s: str) -> tuple[str, bool]:
    """Strip a single leading negative marker, if present."""
    for p in _NEG_PREFIXES:
        if s.startswith(p) and len(s) > len(p):
            rest = s[len(p):]
            # Guard: don't treat lone '-' or '−' followed by non-numeric
            # as negation; require the next char to be digit, decimal,
            # or an opening paren (so "△(500)" peels too).
            if rest and (rest[0].isdigit() or rest[0] in (".", "(", "（")):
                return rest, True
    return s, False


def _parse_clean(s: str) -> int:
    """Parse a normalized, noise-free, sign-free string of digit+unit tokens."""
    if not s:
        raise ValueError("empty value")
    # Reject percentage forms — they are rates, not amounts.
    # NFKC turns ％ into %, so we only need to check for "%".
    if "%" in s:
        raise ValueError(f"percentage is not a yen amount: {s!r}")

    # Strip 円 occurrences anywhere (e.g. "1億2000万円" or interior "1億円").
    s = s.replace("円", "")
    # Re-strip noise (commas re-introduced or 円 removal exposed spaces).
    s = _NOISE_RE.sub("", s)
    if not s:
        raise ValueError("no numeric content")

    # Greedy tokenise: each match contributes (numeral * unit_multiplier).
    pos = 0
    total = 0.0
    matched_any = False
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if not m or m.end() == pos:
            raise ValueError(f"unparseable fragment at {pos}: {s!r}")
        numeral_s, unit = m.group(1), m.group(2) or ""
        try:
            numeral = float(numeral_s)
        except ValueError as exc:
            raise ValueError(f"bad numeral {numeral_s!r}") from exc
        if unit == "億":
            total += numeral * _OKU
        elif unit == "万":
            total += numeral * _MAN
        else:
            total += numeral
        matched_any = True
        pos = m.end()
    if not matched_any:
        raise ValueError(f"no numeric tokens: {s!r}")
    # Truncate (not round) to match accounting convention.
    return int(total) if total >= 0 else -int(-total)


def parse_yen(s: str | int | float | None) -> int:
    """Parse a Japanese currency string into integer yen.

    Handles ``'1,000'``, ``'¥1,000'``, ``'￥1,000'``, ``'1,000円'``,
    ``'1万'``, ``'1万円'``, ``'1.5万'``, ``'1億'``, ``'1億2,000万'``,
    ``'△500'`` (negative — Japanese accounting triangle),
    ``'(500)'`` (negative — Western accounting paren),
    full-width digits via NFKC, ``int`` / ``float`` passthrough
    (floats are *truncated*, not rounded).

    Raises ``ValueError`` for empty/None input or for percentage strings
    (``'50%'`` is a rate, not an amount).
    """
    if s is None:
        raise ValueError("None is not a yen amount")
    if isinstance(s, bool):  # bool is an int subclass; reject explicitly
        raise ValueError(f"bool is not a yen amount: {s!r}")
    if isinstance(s, int):
        return int(s)
    if isinstance(s, float):
        # Truncate toward zero — accounting drops fractional yen.
        return int(s)
    if not isinstance(s, str):
        raise ValueError(f"unsupported type: {type(s).__name__}")

    raw = _normalize(s)
    if not raw:
        raise ValueError("empty string")

    # Negative-detection: peel layers in either order until no marker
    # remains.  Each peel toggles the sign, so e.g. "△(500)" or "(△500)"
    # both negate twice -> positive 500.
    body = raw
    is_neg = False
    while True:
        body, peeled_paren = _strip_paren_negative(body)
        body, peeled_prefix = _strip_neg_prefix(body)
        if not peeled_paren and not peeled_prefix:
            break
        if peeled_paren:
            is_neg = not is_neg
        if peeled_prefix:
            is_neg = not is_neg

    value = _parse_clean(body)
    return -value if is_neg else value


# ---------------------------------------------------------------------------
# Range parsing
# ---------------------------------------------------------------------------


def _split_range(s: str) -> tuple[str, str] | None:
    """Find the FIRST occurrence of any range separator and split.

    Returns (left, right) or None.  Order matters: longer separators
    first so that "から" wins over "-" when both could match.
    """
    # Sort separators by length descending so "から" > "-" precedence.
    for sep in sorted(_RANGE_SEPARATORS, key=len, reverse=True):
        # Skip "-" / "ー" if at position 0 (that's a sign, not a range).
        idx = s.find(sep, 1)
        if idx > 0:
            return s[:idx], s[idx + len(sep):]
    return None


def parse_yen_range(s: str) -> tuple[int, int]:
    """Parse a Japanese currency range into ``(low, high)`` yen.

    Examples
    --------
    >>> parse_yen_range("100万〜500万")
    (1000000, 5000000)
    >>> parse_yen_range("100万円から500万円")
    (1000000, 5000000)
    >>> parse_yen_range("100-500万")
    (1000000, 5000000)
    >>> parse_yen_range("500万")
    (5000000, 5000000)

    Ambiguity rule for ``"100-500万"``: the trailing 万 / 億 unit applies
    to *all* numerals on the right-hand side that lack a unit of their
    own.  This matches how the form is read aloud in Japanese.
    """
    if s is None:
        raise ValueError("None is not a yen range")
    if not isinstance(s, str):
        raise ValueError(f"unsupported type: {type(s).__name__}")
    raw = _normalize(s)
    if not raw:
        raise ValueError("empty string")

    split = _split_range(raw)
    if split is None:
        v = parse_yen(raw)
        return v, v

    left_raw, right_raw = split
    left_raw = left_raw.strip()
    right_raw = right_raw.strip()
    if not left_raw or not right_raw:
        raise ValueError(f"malformed range: {s!r}")

    # Detect trailing unit on the RIGHT side; if present and the LEFT
    # side has no unit, propagate it leftward.  We only touch the bare
    # numeral case ("100" + "500万" -> "100万" + "500万"); if the user
    # already wrote "100万-500億" we leave both alone.
    left_yen_stripped = _strip_yen_suffix(left_raw)
    right_yen_stripped = _strip_yen_suffix(right_raw)
    left_has_unit = "万" in left_yen_stripped or "億" in left_yen_stripped
    right_has_unit = "万" in right_yen_stripped or "億" in right_yen_stripped
    if right_has_unit and not left_has_unit:
        # Propagate the rightmost unit (億 dominates if both appear).
        unit = "億" if "億" in right_yen_stripped else "万"
        left_raw = left_yen_stripped + unit

    low = parse_yen(left_raw)
    high = parse_yen(right_raw)
    if low > high:
        low, high = high, low
    return low, high


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _trim_trailing_zero(x: float) -> str:
    """Format a float with up to 1 decimal, dropping trailing .0."""
    s = f"{x:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return s


def format_yen(n: int, *, unit: str = "auto") -> str:
    """Format an integer yen amount as a human string.

    ``unit``:
        * ``"yen"``  — always ``"5,000,000円"`` style.
        * ``"man"``  — always ``"500万円"`` style (1 decimal max).
        * ``"oku"``  — always ``"1.2億円"`` style (1 decimal max).
        * ``"auto"`` (default) — pick the best unit:
            - ``< 10,000`` yen           -> 円
            - ``< 100,000,000`` yen      -> 万円
            - ``>= 100,000,000`` yen     -> 億円

    Negative amounts are prefixed with ``-`` (not ``△``) for unambiguous
    machine-readability; callers that need 三角 can re-format.
    """
    if not isinstance(n, int) or isinstance(n, bool):
        raise ValueError(f"format_yen requires int, got {type(n).__name__}")
    if unit not in ("auto", "yen", "man", "oku"):
        raise ValueError(f"unknown unit: {unit!r}")

    sign = "-" if n < 0 else ""
    a = abs(n)

    if unit == "auto":
        if a >= _OKU:
            unit = "oku"
        elif a >= _MAN:
            unit = "man"
        else:
            unit = "yen"

    if unit == "yen":
        return f"{sign}{a:,}円"
    if unit == "man":
        return f"{sign}{_trim_trailing_zero(a / _MAN)}万円"
    # oku
    return f"{sign}{_trim_trailing_zero(a / _OKU)}億円"
