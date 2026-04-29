"""景表法 (INV-22) response sanitizer middleware.

Risk model (analysis_wave18/.../05_property_invariants.md::INV-22):
    Stating that a 補助金 / 融資 is "必ず採択される" or "絶対に通る" or
    "保証します" is a 景品表示法 (Act Against Unjustifiable Premiums and
    Misleading Representations) violation. Even if no docstring contains
    those phrases (covered by tests/test_invariants_critical.py::test_inv22),
    a generated answer-string assembled at runtime can still emit them.

Design:
    - Run as a Starlette middleware that wraps every JSON response, after
      handlers, before security headers / CORS.
    - Decode the body once, regex-match a small **affirmative** phrase set,
      EXCLUDE negation contexts (「絶対に〜ではない」「必ずしも〜とは限らない」
      「無保証」 etc.), then apply a token-level replacement only for
      affirmative hits.
    - On any sanitization, set `x-content-sanitized: 1` header and emit a
      structured warning log so we can audit false positives in production
      without breaking the response.
    - false-positive budget: < 1%. We keep the affirmative phrase set tight
      ("必ず採択", "絶対に〜られる", "確実に〜できる", "保証します",
      "間違いなく〜") and skip bare 「保証」 because financial language
      ("信用保証協会", "保証料", "債務保証") is everywhere in this corpus.

Public surface:
    sanitize_response_text(s) -> (clean_text, hits)
    ResponseSanitizerMiddleware  — wires into FastAPI app

The middleware is body-aware: it skips bodies that aren't JSON (SSE, OpenAPI
spec at /openapi.json, /healthz plaintext) and skips bodies > 1 MB to avoid
latency regression on large search payloads. Search payloads are well
under 1 MB at the current 11k-row corpus.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from jpintel_mcp.config import settings
from jpintel_mcp.security.pii_redact import redact_response_text
from jpintel_mcp.security.prompt_injection_sanitizer import (
    sanitize_prompt_injection,
)
from jpintel_mcp.self_improve.loop_a_hallucination_guard import (
    match as _hallu_match,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

logger = logging.getLogger("jpintel.sanitizer")

# Affirmative phrase patterns, each with a replacement.
#
# We do NOT match bare 「保証」 / 「絶対」 / 「必ず」 / 「確実」 because the
# corpus is full of legitimate uses:
#   - 信用保証協会, 債務保証, 保証料   (loan guarantor entities)
#   - 確実な実施, 必要書類の確実な提出 (procedural language)
#   - 絶対値, 必須                    (math / form-required)
# Instead we look for *value-claim* phrasings only.
#
# Negation guards ('〜ではない', 'とは限らない', '無保証') are checked on a
# small character window (50 chars after the match) so the regex itself
# stays simple. False-positive budget < 1% per the v8 plan.
_AFFIRMATIVE_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # 「必ず採択」「必ず受給」「必ず通る」「必ず貰える」 → 対象となる場合があります
    (
        re.compile(r"必ず(採択|受給|通る|貰える|もらえる|当選|当たる)"),
        "対象となる場合があります",
        "must-grant",
    ),
    # 「絶対に〜」 affirmative form: 絶対に通る / 絶対に採択される / 絶対に得られる
    # We require an action verb after to avoid 「絶対値」 「絶対王者」 hits.
    (
        re.compile(r"絶対に[぀-ゟ゠-ヿ一-鿿]{0,8}(通る|採択|得られる|もらえる|貰える|受給|当選)"),
        "対象となる場合があります",
        "absolute-grant",
    ),
    # 「確実に貰える」「確実に採択」 — pairs 確実 with grant verbs
    (
        re.compile(r"確実に(貰える|もらえる|採択|受給|通る|当選)"),
        "対象となる場合があります",
        "certain-grant",
    ),
    # 「保証します」「採択を保証」「成功を保証」 - explicit warranty phrases
    (
        re.compile(r"(採択|成功|受給|当選)を保証(します|いたします)?"),
        "対象となる場合があります",
        "warrant-grant",
    ),
    (
        re.compile(r"保証します"),
        "対象となる場合があります",
        "warrant-self",
    ),
    # 「間違いなく〜」 + grant verb. Bare 「間違いなく」 is rare so no narrow
    # verb suffix needed, but we keep the same structure for symmetry.
    (
        re.compile(r"間違いなく[぀-ゟ゠-ヿ一-鿿]{0,6}(通る|採択|得られる|もらえる|受給|当選)"),
        "対象となる場合があります",
        "no-mistake-grant",
    ),
)

# Negation markers in the 30-char window AFTER a hit. If any appears we
# treat the hit as a negation context and do not sanitize.
_NEGATION_AFTER = re.compile(r"(ではない|ではありません|とは限らない|わけではない|わけではありません|保証はない|保証はありません|無保証|必ずしも)")

# Negation markers in the 30-char window BEFORE a hit (rarer but possible:
# 「○○とは異なり、必ずしも〜」).
_NEGATION_BEFORE = re.compile(r"(必ずしも|決して|限らず)")

# Don't bother with very large bodies; search responses are small.
_MAX_SCAN_BYTES = 1_000_000


def _is_negation_context(text: str, start: int, end: int) -> bool:
    """Return True iff a negation guard surrounds the match span.

    Looks at the 30 chars on each side. The cheap check rules out the
    common "必ずしも〜とは限らない" / "保証はありません" patterns without
    requiring a full parse.
    """
    after = text[end : end + 30]
    if _NEGATION_AFTER.search(after):
        return True
    before_start = max(0, start - 30)
    before = text[before_start:start]
    return bool(_NEGATION_BEFORE.search(before))


def sanitize_response_text(text: str) -> tuple[str, list[str]]:
    """Sanitize a single string. Returns (sanitized, hit_pattern_ids).

    Four cascaded layers run on every JSON str leaf:
        0. PII redactor (S7 critical fix) — masks 法人番号 / email / 電話
           BEFORE every other layer so downstream regex / hallucination
           cache never sees raw 個人情報 (APPI § 31 / § 33). Gated by
           ``AUTONOMATH_PII_REDACT_RESPONSE_ENABLED`` (default on); 代表者名
           and 郵便番号 sub-toggles default off pending legal review.
        1. INV-22 (景表法) affirmative phrase rewrite (this module).
        2. Prompt-injection override stripping
           (``security.prompt_injection_sanitizer``).
        3. Hallucination_guard surface-form detection
           (``self_improve.loop_a_hallucination_guard.match``) — flags
           known-false claims from the 60-phrase YAML cache. This layer
           is *non-rewriting*: it only annotates the hit list with
           ``loop_a-{severity}`` ids so the envelope sentinel surfaces a
           warning. We do NOT auto-substitute the corrections at runtime
           — corrections are factual claims and must be operator-reviewed
           before they hit a customer LLM (per memory
           feedback_no_fake_data + feedback_autonomath_fraud_risk).

    Hit ids are merged into the same flat list — caller logs / envelope
    sentinels distinguish ``pii-houjin`` / ``pii-email`` / ``pii-phone``
    (S7) from ``must-grant`` / ``warrant-self`` (INV-22), ``pi-ignore`` /
    ``pi-jailbreak`` (injection), and ``loop_a-high`` / ``loop_a-medium``
    (hallucination_guard) by prefix.
    """
    if not text:
        return text, []
    hits: list[str] = []
    out = text
    # Layer 0: PII redactor (S7 critical fix). Runs FIRST so subsequent
    # layers operate on already-masked text — no INV-22 / injection /
    # loop_a callbacks ever see raw 法人番号 / email / 電話. Gated by
    # AUTONOMATH_PII_REDACT_RESPONSE_ENABLED (default on); flip "0" /
    # "false" via env for one-flag rollback.
    if getattr(settings, "pii_redact_response_enabled", True):
        out, pii_hits = redact_response_text(out)
        hits.extend(pii_hits)
    for pat, repl, pid in _AFFIRMATIVE_RULES:
        # Build replacement function so we can skip negation contexts.
        # Default-arg binding pins each loop variable to this closure so
        # the next iteration's `out`/`pid`/`repl` cannot bleed in.
        def _replace(
            m: re.Match[str],
            _pid: str = pid,
            _repl: str = repl,
            _haystack: str = out,
        ) -> str:
            if _is_negation_context(_haystack, m.start(), m.end()):
                return m.group(0)
            hits.append(_pid)
            return _repl

        out = pat.sub(_replace, out)
    # Layer 2: prompt-injection guard. Gated by
    # AUTONOMATH_PROMPT_INJECTION_GUARD env (default on).
    out, pi_hits = sanitize_prompt_injection(out)
    hits.extend(pi_hits)
    # Layer 3: hallucination_guard substring scan over the 60-phrase YAML.
    # `_load()` inside loop_a is `lru_cache(maxsize=1)`, so the only
    # per-request cost is 60 substring checks against `out`. Gated by
    # AUTONOMATH_HALLUCINATION_GUARD_ENABLED (default on). Pure annotation
    # — text is never rewritten here.
    if getattr(settings, "hallucination_guard_enabled", True):
        try:
            hg_hits = _hallu_match(out)
        except Exception:
            # Same defensive posture as the other layers: a YAML / cache
            # bug must NEVER 500 a healthy tool result. Swallow + log.
            logger.warning("hallucination_guard_match_failed", exc_info=True)
            hg_hits = []
        for h in hg_hits:
            sev = h.get("severity", "unknown")
            hits.append(f"loop_a-{sev}")
    return out, hits


def _walk_and_sanitize(node: Any) -> tuple[Any, list[str]]:
    """Walk a JSON-decoded node, sanitizing str leaves. Returns (clean, hits)."""
    all_hits: list[str] = []
    if isinstance(node, str):
        clean, hits = sanitize_response_text(node)
        all_hits.extend(hits)
        return clean, all_hits
    if isinstance(node, dict):
        out_d: dict[str, Any] = {}
        for k, v in node.items():
            clean, hits = _walk_and_sanitize(v)
            out_d[k] = clean
            all_hits.extend(hits)
        return out_d, all_hits
    if isinstance(node, list):
        out_l: list[Any] = []
        for v in node:
            clean, hits = _walk_and_sanitize(v)
            out_l.append(clean)
            all_hits.extend(hits)
        return out_l, all_hits
    return node, all_hits


def _rebuild_response(
    *,
    body: bytes,
    status_code: int,
    raw_headers: list[tuple[bytes, bytes]],
    media_type: str | None,
    extra_headers: dict[str, str] | None = None,
    drop_content_length: bool = False,
) -> Response:
    """Rebuild a Response while preserving multi-value headers.

    Wave 16 P1 fix: ``Response(headers=dict(orig.headers))`` collapses
    duplicate ``Set-Cookie`` rows into the FIRST one — Python ``dict``
    only retains one value per key. That silently drops the companion
    ``am_csrf`` cookie set by ``api/me._set_session_cookie`` whenever a
    response passes through this middleware (i.e. every JSON response).
    Manipulating ``raw_headers`` directly preserves duplicate keys.
    """
    resp = Response(
        content=body, status_code=status_code, media_type=media_type
    )
    # Replace the auto-built raw_headers (which carry only the
    # content-length + content-type Starlette wrote) with the upstream
    # set, then re-append the recomputed content-length / media-type.
    preserved: list[tuple[bytes, bytes]] = []
    for k, v in raw_headers:
        kl = k.lower()
        if drop_content_length and kl == b"content-length":
            continue
        preserved.append((kl, v))
    # Strip the content-length / content-type Starlette just stamped so
    # we don't end up with two of each — we'll rely on the upstream
    # values (preserved) and let Starlette re-stamp content-length on
    # the body we just wrote when drop_content_length is True.
    resp.raw_headers = [
        (k, v) for (k, v) in resp.raw_headers
        if k.lower() not in (b"content-length", b"content-type")
    ] + preserved
    if extra_headers:
        for k, v in extra_headers.items():
            resp.headers[k] = v
    if drop_content_length:
        # Rewrite content-length to the new body length.
        resp.headers["content-length"] = str(len(body))
    return resp


class ResponseSanitizerMiddleware(BaseHTTPMiddleware):
    """Wraps JSON responses, sanitizes affirmative grant phrases (景表法)."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)

        # Only scan JSON bodies. SSE / openapi.json / plaintext / HTML pages
        # like /v1/subscribers/unsubscribe pass through unchanged.
        ctype = response.headers.get("content-type", "")
        if "application/json" not in ctype.lower():
            return response

        # APPI §31 / §33 intake responses must echo the operator contact
        # (`info@bookyou.net`) verbatim — that's the address the data
        # subject needs in order to escalate. The PII layer-0 redactor
        # would otherwise mask it to `<email-redacted>`, defeating the
        # legal obligation to provide a contact channel. Skip the
        # `/v1/privacy/` prefix entirely; these handlers never emit data
        # subject PII (they only mint a request_id + the operator's own
        # contact + a fixed SLA integer) so there is no S7 risk in
        # passing the body through unmodified.
        # Same exemption applies to the P3.5 refund-request intake at
        # `/v1/billing/refund_request` — the response carries the operator
        # contact + request_id only, no requester PII.
        if request.url.path.startswith("/v1/privacy/"):
            return response
        if request.url.path == "/v1/billing/refund_request":
            return response
        # `/v1/me/alerts/*` echoes the caller's own delivery email back so
        # the user can confirm what they just registered. The email belongs
        # to the same authenticated principal (X-API-Key) and is the only
        # surface where the cron resolves "who to notify"; redacting it to
        # `<email-redacted>` would defeat the confirmation handshake. The
        # endpoint never emits third-party PII (it only returns the row
        # the caller created or owns).
        if request.url.path.startswith("/v1/me/alerts"):
            return response

        # Snapshot raw headers BEFORE iterating the body — Starlette's
        # StreamingResponse strips Content-Length once the body iterator
        # is consumed, but multi-Set-Cookie headers must survive the
        # rebuild (Wave 16 CSRF dual-cookie depends on this).
        upstream_raw_headers = list(response.raw_headers)

        # StreamingResponse: read body iter into memory once. For typical
        # search responses (< 100 KB) this is essentially free.
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
            if len(body) > _MAX_SCAN_BYTES:
                # Punt: do not scan, do not block. Logging only.
                logger.warning(
                    "response_sanitize_skip_oversize path=%s bytes=%d",
                    request.url.path,
                    len(body),
                )
                return _rebuild_response(
                    body=body,
                    status_code=response.status_code,
                    raw_headers=upstream_raw_headers,
                    media_type=response.media_type,
                )

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not actually JSON despite the header — leave it alone.
            return _rebuild_response(
                body=body,
                status_code=response.status_code,
                raw_headers=upstream_raw_headers,
                media_type=response.media_type,
            )

        clean, hits = _walk_and_sanitize(payload)
        if not hits:
            # Common path: nothing matched. Re-emit the original bytes so we
            # don't pay a re-encode cost on every response.
            return _rebuild_response(
                body=body,
                status_code=response.status_code,
                raw_headers=upstream_raw_headers,
                media_type=response.media_type,
            )

        # Sanitization happened. Re-encode, set a debug header, and emit a
        # structured warning. We never raise: silently passing through
        # bad copy is far worse than the small operator noise of a warn log.
        new_body = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        logger.warning(
            "response_sanitized path=%s status=%d hits=%s",
            request.url.path,
            response.status_code,
            ",".join(sorted(set(hits))),
        )
        return _rebuild_response(
            body=new_body,
            status_code=response.status_code,
            raw_headers=upstream_raw_headers,
            media_type="application/json",
            extra_headers={"x-content-sanitized": "1"},
            drop_content_length=True,
        )


__all__ = [
    "ResponseSanitizerMiddleware",
    "sanitize_response_text",
]
