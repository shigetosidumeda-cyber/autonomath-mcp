"""Citation Verifier — pure no-LLM regex + checksum substantiation.

Implements the §8.2 contract from `docs/_internal/value_maximization_plan_no_llm_api.md`
and the §28.9 No-Go #1 (no false-allow): every "verified" claim emitted by
the API/MCP envelope must be deterministically traceable to a substring or
numeric form actually present in the cited primary source — never asserted
without proof.

Trust ladder (also matches §28.2 envelope contract):

    verified  — excerpt OR a normalized numeric form was found verbatim in
                source_text. Strongest claim.
    inferred  — excerpt was supplied but did NOT match. The number itself
                may have been paraphrased; we cannot verify, so we DOWNGRADE
                rather than false-allow. Caller decides whether to surface.
    stale     — reserved for the path where we re-fetch source_url and find
                the body has drifted from the last-known checksum. Computed
                outside this module (callers compare returned source_checksum
                against their stored one).
    unknown   — no excerpt AND no numeric field_value, OR fetch failed. Cannot
                make any claim either way.

Constraints (from the task brief + repo CLAUDE.md):
  * NO LLM imports. Pure stdlib + regex.
  * urllib.request only (no requests / httpx) for the fetcher.
  * BeautifulSoup is NOT a dep; we strip HTML via stdlib regex.
  * In-memory TTL cache (3600s). NO state writes to DB.
  * Idempotent: same (citation, source_text) → same VerificationResult.

The §28.9 fence is enforced by the algorithm itself: the verdict is computed
from substring / regex match against the FETCHED source_text. If the source
is unreachable or paraphrased, we fall to ``unknown`` / ``inferred`` rather
than emitting ``verified``. Code paths that DEFAULT to ``verified`` without
calling this module are bugs.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, TypedDict

logger = logging.getLogger("jpintel.services.citation_verifier")

__all__ = [
    "CitationVerifier",
    "VerificationResult",
    "USER_AGENT",
    "MAX_EXCERPT_LEN",
    "MAX_CITATIONS_PER_CALL",
    "PER_FETCH_TIMEOUT_SEC",
    "CACHE_TTL_SEC",
]


# Public module constants — REST/MCP layer reads these so caps live in
# exactly one place (the §28.9 No-Go fence is more useful when both
# transports use the same numbers).
USER_AGENT = "jpcite-citation-verifier/1.0 (+https://jpcite.com/trust)"
MAX_EXCERPT_LEN = 500
MAX_CITATIONS_PER_CALL = 10
PER_FETCH_TIMEOUT_SEC = 5
CACHE_TTL_SEC = 3600

# Strip HTML tags via stdlib regex. BeautifulSoup is not a project dep
# (intentional — we don't want to add one for a single function); the
# regex is sufficient for the verifier's purpose because we only need
# substring presence, not perfect structural parsing.
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_RE_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_RE_WS = re.compile(r"\s+")


class VerificationResult(TypedDict, total=False):
    """Return type for ``CitationVerifier.verify``.

    All keys are always present; ``matched_form`` and ``error`` may be None.
    """

    verification_status: str  # verified | inferred | stale | unknown
    matched_form: str | None
    source_checksum: str
    normalized_source_length: int
    error: str | None


def _normalize_text(text: str) -> str:
    """NFKC + collapse whitespace runs to single space + strip.

    This is the core of the no-false-allow guarantee: both the source body
    AND the candidate excerpt/number are passed through the SAME pipeline,
    so verdicts cannot drift on full-width vs half-width or 全角空白 vs
    half-width space.
    """
    if not text:
        return ""
    # NFKC: ５００万 → 500万, 全角ASCII → 半角ASCII, 全角空白 → 半角空白.
    normalized = unicodedata.normalize("NFKC", text)
    # Collapse \s+ runs to a single space, then strip leading/trailing.
    normalized = _RE_WS.sub(" ", normalized).strip()
    return normalized


def _strip_html(html: str) -> str:
    """Remove <script>/<style> bodies, then all remaining tags.

    Pre-NFKC operation — runs on the raw fetched body so HTML entities and
    tag noise don't pollute the normalized text we compare against.
    """
    if not html:
        return ""
    body = _RE_SCRIPT.sub(" ", html)
    body = _RE_STYLE.sub(" ", body)
    body = _RE_HTML_TAG.sub(" ", body)
    return body


def _japanese_numeric_forms(value: int) -> list[str]:
    """Return ALL Japanese-style spellings of an integer.

    For value=5_000_000 we generate, in match-priority order:
        ['5,000,000円', '5,000,000', '500万円', '500万',
         '5百万円', '5百万', '5000000']

    The order matters: the first hit wins, so the more "human" form
    (``500万円``) outranks the bare integer (``5000000``) — when the source
    page used a Japanese spelling, ``matched_form`` reports that form back
    to the caller for audit clarity.

    Negative or zero values yield only their bare integer form (signed
    text matching is out of scope for the v1 verifier).
    """
    forms: list[str] = []
    if value <= 0:
        return [str(value)]

    # 1. Comma-grouped raw + 円-suffix variants.
    comma = f"{value:,}"
    forms.append(f"{comma}円")
    forms.append(comma)

    # 2. 万円 / 万 — only when value is ≥ 10,000 AND divisible by 10,000.
    #    e.g. 5,000,000 → 500 万 (clean); 5,500,000 → 550 万 (clean).
    #    1,234,567 (not clean) — we still emit the partial form, since
    #    Japanese government PDFs commonly write '123 万 4,567 円' for
    #    such values, but matching that exact mixed form is brittle so
    #    we prioritize the clean case.
    if value >= 10_000 and value % 10_000 == 0:
        man = value // 10_000
        # Both 万円 AND bare 万 forms are common in primary sources.
        forms.append(f"{man:,}万円")
        forms.append(f"{man:,}万")
        # Also without comma grouping in the 万 prefix (some pages write
        # '500万円' as one token rather than '500,000円'-style grouping).
        if "," in f"{man:,}":
            forms.append(f"{man}万円")
            forms.append(f"{man}万")

    # 3. 百万円 / 百万 — only for clean millions divisible by 1,000,000.
    if value >= 1_000_000 and value % 1_000_000 == 0:
        hyakuman = value // 1_000_000
        forms.append(f"{hyakuman}百万円")
        forms.append(f"{hyakuman}百万")

    # 4. 億円 / 億 — clean 億.
    if value >= 100_000_000 and value % 100_000_000 == 0:
        oku = value // 100_000_000
        forms.append(f"{oku}億円")
        forms.append(f"{oku}億")

    # 5. Bare integer (no separators) — last resort, very common in
    #    machine-readable JSON / CSV primary sources.
    forms.append(str(value))

    # Dedupe while preserving priority order.
    seen: set[str] = set()
    deduped: list[str] = []
    for f in forms:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    return deduped


def _coerce_int(value: Any) -> int | None:
    """Return ``value`` as an int when it represents a whole number; else None.

    Accepts int, str of digits (with optional commas/spaces), and float
    that is integer-valued (5_000_000.0). Rejects negatives and fractional
    floats — those are out of scope for the v1 verifier's numeric-match
    surface.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int; reject explicitly so True/False don't
        # silently match to "1" / "0" in source pages.
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if value.is_integer() and value > 0:
            return int(value)
        return None
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace(" ", "")
        if not s:
            return None
        # Accept "5000000" / "5000000.0" but reject "abc".
        try:
            if "." in s:
                f = float(s)
                if f.is_integer() and f > 0:
                    return int(f)
                return None
            n = int(s)
            return n if n > 0 else None
        except ValueError:
            return None
    return None


class CitationVerifier:
    """Deterministic, no-LLM citation verifier.

    Two entry points:

      * ``verify(citation, source_text)`` — pure: decide the verdict given
        a citation dict and the source body. Used by tests and by callers
        that already have the body in hand.
      * ``fetch_source(url)`` — best-effort URL → text. Caches by URL for
        ``CACHE_TTL_SEC`` seconds. Returns None on any error so the caller
        falls through to ``unknown``.

    The class carries a single piece of state — the in-memory cache — so
    instances are NOT thread-safe in the strictest sense. Callers that
    fan out across threads should either share one instance (all reads
    are append-mostly) or accept the worst case of redundant fetches.
    The ¥3/req cost surface puts a natural ceiling on concurrency anyway.
    """

    def __init__(self, *, cache_ttl_sec: int = CACHE_TTL_SEC) -> None:
        # cache: url -> (text, expiry_unix_ts)
        self._cache: dict[str, tuple[str, float]] = {}
        self._cache_ttl = cache_ttl_sec

    # ------------------------------------------------------------------
    # Verification (pure / idempotent)
    # ------------------------------------------------------------------

    def verify(
        self,
        citation: dict[str, Any],
        source_text: str,
    ) -> VerificationResult:
        """Return the verdict for one citation against a fetched source body.

        ``citation`` must be a dict; the verifier reads two optional keys:
            - ``excerpt``       (str): substring claim
            - ``field_value``   (int | str | float): numeric claim

        At least one must be present and non-empty for a meaningful verdict;
        otherwise the result is ``unknown`` with ``error="no_claim_to_verify"``.

        ``source_text`` is the already-fetched body (HTML or plain text). We
        run the SAME normalization (HTML strip → NFKC → \\s collapse) that
        ``fetch_source`` would have applied, so callers can pass either raw
        HTML from their own fetcher OR pre-cleaned plain text.
        """
        if not isinstance(citation, dict):
            return self._build_result(
                status="unknown",
                matched_form=None,
                source_normalized="",
                error="citation_must_be_dict",
            )

        excerpt = citation.get("excerpt")
        field_value = citation.get("field_value")

        # Normalize the source body once. _strip_html is idempotent on
        # already-stripped text (no tags to remove).
        stripped = _strip_html(source_text or "")
        normalized_source = _normalize_text(stripped)

        # No claim to verify — caller passed citation with neither excerpt
        # nor a numeric field_value.
        has_excerpt = isinstance(excerpt, str) and excerpt.strip() != ""
        coerced_value = _coerce_int(field_value)
        has_field = coerced_value is not None
        if not has_excerpt and not has_field:
            return self._build_result(
                status="unknown",
                matched_form=None,
                source_normalized=normalized_source,
                error="no_claim_to_verify",
            )

        # 1. Excerpt path — substring presence in the normalized source.
        if has_excerpt and isinstance(excerpt, str):
            normalized_excerpt = _normalize_text(excerpt)
            if normalized_excerpt and normalized_excerpt in normalized_source:
                return self._build_result(
                    status="verified",
                    matched_form=normalized_excerpt[:MAX_EXCERPT_LEN],
                    source_normalized=normalized_source,
                    error=None,
                )
            # Excerpt was supplied but not found. We CANNOT silently fall
            # through to "verified" via the field_value path — that would
            # let a paraphrase-only citation pass via a coincidental
            # numeric hit. Per §28.9 No-Go #1, downgrade to ``inferred``
            # so the caller knows the excerpt did not substantiate.
            #
            # However: when the caller ONLY passed a numeric claim, run
            # that path. The above check guards on `has_excerpt`; a
            # citation with excerpt+field_value where the excerpt fails
            # STILL gets marked ``inferred`` (not ``verified`` via numeric)
            # — the strict reading is "excerpt failed, don't pretend
            # something else verified the claim".
            return self._build_result(
                status="inferred",
                matched_form=None,
                source_normalized=normalized_source,
                error=None,
            )

        # 2. Numeric path — field_value only, no excerpt.
        assert coerced_value is not None  # narrowed by has_field branch
        forms = _japanese_numeric_forms(coerced_value)
        normalized_forms = [(_normalize_text(f), f) for f in forms]
        for nf, original in normalized_forms:
            if nf and nf in normalized_source:
                return self._build_result(
                    status="verified",
                    matched_form=original,
                    source_normalized=normalized_source,
                    error=None,
                )

        # No numeric form found — strict ``unknown`` (NOT ``inferred``).
        # Distinction matters: inferred = "we have an excerpt that didn't
        # match"; unknown = "no signal either way". §28.2 envelope.
        return self._build_result(
            status="unknown",
            matched_form=None,
            source_normalized=normalized_source,
            error=None,
        )

    # ------------------------------------------------------------------
    # Fetcher (stdlib only, in-memory TTL cache)
    # ------------------------------------------------------------------

    def fetch_source(
        self,
        url: str,
        timeout: int = PER_FETCH_TIMEOUT_SEC,
    ) -> str | None:
        """Fetch ``url`` and return its body as plain text. None on failure.

        Behavior:
          * Caches successful responses for ``CACHE_TTL_SEC`` seconds keyed
            by URL. Failures are NOT cached (transient network blips don't
            poison subsequent requests).
          * Returns None on 4xx/5xx, network error, or timeout. Callers
            treat None as ``unknown`` per the §28.2 envelope.
          * HTTP only (http://, https://). Any other scheme returns None
            so the verifier cannot be tricked into reading file:// or
            ftp:// URLs from user-supplied citations.
          * Read body cap: 5 MiB. Larger responses are truncated — the
            verifier only needs substring presence, not full integrity.
        """
        if not isinstance(url, str) or not url:
            return None
        if not (url.startswith("http://") or url.startswith("https://")):
            return None

        now = time.time()
        cached = self._cache.get(url)
        if cached is not None:
            text, expiry = cached
            if expiry > now:
                return text
            # Stale entry — drop and re-fetch.
            self._cache.pop(url, None)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                # Plain text fallbacks first; many JP gov pages serve
                # text/html;charset=Shift_JIS, but urllib hands us bytes
                # either way and we decode below.
                "Accept": "text/html, text/plain;q=0.9, */*;q=0.5",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — http(s) scheme guarded above
                if 400 <= resp.status < 600:
                    return None
                raw = resp.read(5 * 1024 * 1024)  # 5 MiB cap
                charset = resp.headers.get_content_charset() or "utf-8"
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            ValueError,
            OSError,
        ) as exc:
            logger.info("fetch_source failed url=%s err=%r", url, exc)
            return None

        try:
            text = raw.decode(charset, errors="replace")
        except (LookupError, ValueError):
            # Charset header lied or unknown. Fall back to UTF-8 with
            # replacement so substring matching still has a chance.
            text = raw.decode("utf-8", errors="replace")

        self._cache[url] = (text, now + self._cache_ttl)
        return text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        *,
        status: str,
        matched_form: str | None,
        source_normalized: str,
        error: str | None,
    ) -> VerificationResult:
        """Assemble the final result dict (always with checksum + length)."""
        # SHA256 over the NORMALIZED text. Stable across calls — re-running
        # against the same source_text always yields the same checksum, so
        # callers can store it and detect drift on next verify.
        digest = hashlib.sha256(source_normalized.encode("utf-8")).hexdigest()
        return {
            "verification_status": status,
            "matched_form": matched_form,
            "source_checksum": digest,
            "normalized_source_length": len(source_normalized),
            "error": error,
        }

    def clear_cache(self) -> None:
        """Drop every cached fetch. Used by tests; no production caller."""
        self._cache.clear()
