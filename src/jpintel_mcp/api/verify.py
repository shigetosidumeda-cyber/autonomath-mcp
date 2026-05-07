"""DEEP-25 verifiable answer primitive — REST surface.

`POST /v1/verify/answer` — accepts `{answer_text, claimed_sources, language}`,
runs the 5-function verifier pipeline (`_verifier.py`) and returns the
4-axis verifiability score + per-claim breakdown + boundary violations +
hallucination signals + 17-token sensitive disclaimer + ¥3 cost.

Pricing posture
---------------
¥3 per call (税込 ¥3.30). claim_count cap = 5; 6+ -> 400 with
``too_many_claims`` so agents must split the answer. Anonymous tier
shares the 3 req/day IP limit; authenticated keys are billable per call.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside this endpoint. Pure regex / FTS5 / SQLite / async
  HEAD fetch via `_verifier.py`. The CI guard
  `tests/test_no_llm_in_production.py` enforces zero
  `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk`
  imports under `src/jpintel_mcp/api/`.
* `_disclaimer` is the 17-token sensitive envelope (jpcite canonical
  wording, mirrors Wave 30 §52 hardening).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from jpintel_mcp.api._verifier import (
    CLAIM_COUNT_CAP,
    DISCLAIMER_EN,
    DISCLAIMER_JA,
    ClaimResult,
    check_source_alive,
    compute_score,
    detect_boundary_violations,
    match_to_corpus,
    tokenize_claims,
)
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.verify")

router = APIRouter(prefix="/v1/verify", tags=["verify"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class VerifyAnswerRequest(BaseModel):
    """Input to POST /v1/verify/answer."""

    answer_text: Annotated[
        str,
        Field(
            min_length=1,
            max_length=20_000,
            description="Other-LLM answer to verify against jpcite corpus.",
        ),
    ]
    claimed_sources: Annotated[
        list[str],
        Field(
            max_length=10,
            description=(
                "URLs the answer cites. License-OK hosts are HEAD-fetched; "
                "aggregators are rejected with `aggregator_source` signal."
            ),
        ),
    ] = []
    language: Annotated[
        str,
        Field(
            pattern=r"^(ja|en)$",
            description="Answer language. ja or en.",
        ),
    ] = "ja"


class PerClaimResponse(BaseModel):
    claim: str
    sources_match: bool
    sources_relevant: bool
    matched_jpcite_record: str | None = None
    confidence: float | None = None
    signals: list[str] = []


class BoundaryViolationResponse(BaseModel):
    law: str
    section: str
    phrase: str
    severity: str


class VerifyAnswerResponse(BaseModel):
    verifiability_score: int = Field(..., ge=0, le=100)
    per_claim: list[PerClaimResponse]
    boundary_violations: list[BoundaryViolationResponse]
    hallucination_signals: list[str]
    request_id: str
    language: str
    answer_hash: str
    disclaimer: str = Field(..., alias="_disclaimer", serialization_alias="_disclaimer")
    cost_yen: int = Field(default=3, alias="_cost_yen", serialization_alias="_cost_yen")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open autonomath.db read-only. Returns None if file missing.

    The route degrades gracefully when the test harness lacks the
    full corpus; per-claim signals will surface `corpus_degraded`
    rather than 500.
    """
    try:
        from jpintel_mcp.config import settings

        path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    except Exception:  # noqa: BLE001 — defensive
        path = os.environ.get("AUTONOMATH_DB_PATH", "")

    if not path or not os.path.exists(path):
        return None

    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.debug("autonomath.db open failed: %s", exc)
        return None


def _ip_hash(request: Request) -> str:
    """Salted sha256 of client IP — APPI 配慮, never raw."""
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else ""
    )
    if not ip:
        return ""
    salt = os.environ.get("API_KEY_SALT", "jpcite-verify-salt").encode("utf-8")
    return hashlib.sha256(salt + ip.encode("utf-8")).hexdigest()


def _persist_log(
    *,
    request_id: str,
    answer_hash: str,
    score: int,
    per_claim: list[dict[str, Any]],
    sources: list[Any],
    boundaries: list[Any],
    language: str,
    api_key_id: int | None,
    client_ip_hash: str,
) -> None:
    """Best-effort INSERT into verify_log. Never raise — audit is post-hoc.

    If the table or DB is unavailable, log debug and continue. The user-
    facing response is unaffected.
    """
    conn = _open_autonomath_ro()
    if conn is None:
        return

    try:
        alive_count = sum(1 for s in sources if getattr(s, "alive", None) is True)
        dead_count = sum(1 for s in sources if getattr(s, "alive", None) is False)
        boundary_count = len(boundaries)
        boundary_json = (
            json.dumps(
                [
                    {
                        "law": b.law,
                        "section": b.section,
                        "phrase": b.phrase,
                        "severity": b.severity,
                    }
                    for b in boundaries
                ],
                ensure_ascii=False,
            )
            if boundaries
            else None
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO verify_log (
                request_id, answer_hash, score, per_claim_json,
                source_alive_count, source_dead_count,
                boundary_violations_count, boundary_violations_json,
                language, api_key_id, client_ip_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                answer_hash,
                score,
                json.dumps(per_claim, ensure_ascii=False),
                alive_count,
                dead_count,
                boundary_count,
                boundary_json,
                language,
                api_key_id,
                client_ip_hash,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        logger.debug("verify_log insert degraded: %s", exc)
    finally:
        with contextlib.suppress(Exception):  # noqa: BLE001
            conn.close()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/answer", response_model=VerifyAnswerResponse, response_model_by_alias=True)
async def verify_answer(
    payload: VerifyAnswerRequest,
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
) -> VerifyAnswerResponse:
    """Verify an LLM-generated answer against the jpcite corpus.

    Returns 0-100 verifiability score, per-claim match breakdown,
    boundary_violations (税理士法 §52 etc.), and the 17-token
    sensitive disclaimer.

    Errors:
      * 400 too_many_claims when tokenize yields >5 atomic claims.
      * 422 from pydantic when answer_text empty or language invalid.

    R8 BUGHUNT 2026-05-07: ¥3 metering wired here. Pre-fix the
    endpoint advertised ``cost_yen: 3`` in the response but never
    called ``log_usage`` — authenticated callers were billed ¥0,
    burning revenue per call. AnonIpLimitDep was the only gate.
    """
    started = time.monotonic()
    request_id = uuid.uuid4().hex
    answer_hash = hashlib.sha256(payload.answer_text.encode("utf-8")).hexdigest()

    # 1. Tokenize. Cap = 5; 6+ rejected with 400.
    claims = tokenize_claims(payload.answer_text, language=payload.language)
    if len(claims) > CLAIM_COUNT_CAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "too_many_claims",
                "claim_count": len(claims),
                "max_per_call": CLAIM_COUNT_CAP,
                "developer_message": (
                    f"answer_text yielded {len(claims)} atomic claims; "
                    f"max = {CLAIM_COUNT_CAP}. Split your answer into "
                    f"{CLAIM_COUNT_CAP}-claim chunks for verification."
                ),
            },
        )

    # 2. Match each claim against the corpus.
    conn = _open_autonomath_ro()
    try:
        claim_results: list[ClaimResult] = []
        per_claim_payload: list[dict[str, Any]] = []
        all_signals: list[str] = []
        for c in claims:
            match = match_to_corpus(c, conn)
            sources_match = match.matched_jpcite_record is not None
            cr = ClaimResult(
                claim=c.text,
                sources_match=sources_match,
                sources_relevant=sources_match,
                matched_jpcite_record=match.matched_jpcite_record,
                confidence=match.confidence if sources_match else None,
                signals=match.signals,
            )
            claim_results.append(cr)
            per_claim_payload.append(
                {
                    "claim": c.text,
                    "sources_match": sources_match,
                    "sources_relevant": sources_match,
                    "matched_jpcite_record": match.matched_jpcite_record,
                    "confidence": match.confidence if sources_match else None,
                    "signals": list(match.signals),
                }
            )
            all_signals.extend(match.signals)
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()

    # 3. HEAD-fetch claimed_sources in parallel.
    sources = await check_source_alive(payload.claimed_sources)
    for s in sources:
        all_signals.extend(s.signals)

    # 4. Detect business-law boundary violations.
    boundaries = detect_boundary_violations(payload.answer_text, lang=payload.language)

    # 5. Compute the final 4-axis weighted score.
    score = compute_score(claim_results, sources, boundaries)

    # 6. Persist audit log (best-effort, never raises).
    _persist_log(
        request_id=request_id,
        answer_hash=answer_hash,
        score=score,
        per_claim=per_claim_payload,
        sources=sources,
        boundaries=boundaries,
        language=payload.language,
        api_key_id=ctx.key_id,
        client_ip_hash=_ip_hash(request),
    )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.debug(
        "verify_answer request_id=%s score=%d claims=%d boundaries=%d elapsed_ms=%d",
        request_id,
        score,
        len(claim_results),
        len(boundaries),
        elapsed_ms,
    )

    # R8 BUGHUNT 2026-05-07: bill ¥3 / call for authenticated keys.
    # Anonymous callers (key_hash is None) are silently skipped by
    # log_usage and are already gated by AnonIpLimitDep at 3/IP/day.
    log_usage(
        conn,
        ctx,
        "verify.answer",
        latency_ms=elapsed_ms,
        result_count=len(claim_results),
        params={
            "language": payload.language,
            "claim_count": len(claim_results),
            "claimed_sources_count": len(payload.claimed_sources),
        },
        strict_metering=True,
    )

    disclaimer = DISCLAIMER_EN if payload.language == "en" else DISCLAIMER_JA

    return VerifyAnswerResponse.model_validate(
        {
            "verifiability_score": score,
            "per_claim": [
                PerClaimResponse(
                    claim=p["claim"],
                    sources_match=p["sources_match"],
                    sources_relevant=p["sources_relevant"],
                    matched_jpcite_record=p["matched_jpcite_record"],
                    confidence=p["confidence"],
                    signals=p["signals"],
                )
                for p in per_claim_payload
            ],
            "boundary_violations": [
                BoundaryViolationResponse(
                    law=b.law,
                    section=b.section,
                    phrase=b.phrase,
                    severity=b.severity,
                )
                for b in boundaries
            ],
            "hallucination_signals": sorted(set(all_signals)),
            "request_id": request_id,
            "language": payload.language,
            "answer_hash": answer_hash,
            "disclaimer": disclaimer,
            "cost_yen": 3,
        }
    )
