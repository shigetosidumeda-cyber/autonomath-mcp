"""Multi-agent orchestration API — invoke external SaaS from jpcite (Wave 43.2.6).

Dimension F (multi-agent orchestration). Builds on the Wave 26
``functions/webhook_router_v2.ts`` (inbound HMAC fan-out to Slack /
Discord / Teams) by adding the **outbound** half: a jpcite-side route
that takes a jpcite query result and pushes it into the customer's
freee / MoneyForward / Notion / Slack instance using the customer's own
API token.

Endpoints (mounted at ``/v1/orchestrate/*``):

  POST /v1/orchestrate/freee
      仕訳科目 (account_item) -> program match. Body carries the customer's
      freee personal access token + a list of account items. We loop each
      account through ``programs.search`` keyword fence (税額控除, 助成金,
      etc.) and return up to 5 matched program_id + source_url per row.
      The customer's freee token is NEVER stored — used in-request only.

  POST /v1/orchestrate/mf
      MoneyForward Cloud 経費 同フロー. account_code -> program match.
      Same single-shot pattern: token is request-scoped and dropped on
      reply.

  POST /v1/orchestrate/notion
      法令改正 (am_amendment_diff row) -> Notion database ticket. The
      customer supplies their Notion integration token + target
      database_id; we POST a single page per diff row containing program
      name, amendment summary, source_url, and the §52 disclaimer.

  POST /v1/orchestrate/slack
      Alert fan-out via the customer's Slack incoming-webhook URL. Body
      carries the webhook URL + a structured alert (kind / title /
      summary / url). One HTTP POST per call, Block Kit format. Mirrors
      ``functions/webhook_router_v2.ts buildSlackBlockKit``.

Pricing (project_autonomath_business_model — immutable):

  * 1 req = ``ORCHESTRATE_UNIT_COUNT`` (default 3) billable units. The 3x
    multiplier reflects the composition cost: we (a) query jpintel.db,
    (b) compose the per-target payload, (c) POST the external SaaS API
    once per row. Anonymous tier rejected with 402 — we need a metered
    paid key here.
  * Per-key rate floor: 1 orchestration / 10s. Defends against an agent
    loop that would otherwise blow ¥1,000 of usage in 60s.
  * §52 disclaimer attached to every response (verbatim from
    ``api/tax_rulesets.py:_TAX_DISCLAIMER``).

Memory references
-----------------
* ``feedback_zero_touch_solo`` — every action is fully self-service.
  The customer brings their own freee / MF / Notion / Slack token; we
  store nothing. No admin onboarding, no Slack-Connect.
* ``feedback_no_operator_llm_api`` — this module does NOT import
  anthropic / openai / google.generativeai / claude_agent_sdk. All
  composition is pure Python + SQLite + urllib.
* ``feedback_autonomath_no_api_use`` — we don't call our own LLM API
  from this surface either. The customer's LLM is the only LLM in the
  loop.
* ``feedback_ax_4_pillars`` — Layer-3 (Orchestration) surface. Lets an
  AI agent drive jpcite -> external-SaaS without a human in the loop.

Design notes
------------
* No new tables. Every output is composed from existing jpintel.db
  rows (programs / laws / am_amendment_diff via best-effort) at request
  time.
* No persistent token storage. The customer's token is read from the
  request body and dropped after the single outbound POST. Logs redact
  the token before structured emission.
* Outbound HTTP uses stdlib ``urllib.request`` to keep this file free
  of httpx / requests churn — matches the Wave 26
  ``tools/integrations/notion_sync_v2.py`` stdlib-only posture.
* Brand: jpcite. No legacy zeimu-kaikei.ai / autonomath strings in
  user-facing copy.
"""

from __future__ import annotations

import json
import logging
import sqlite3  # noqa: TC003 (runtime: DB connection type)
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_usage,
    require_metered_api_key,
)
from jpintel_mcp.api.tax_rulesets import _TAX_DISCLAIMER

logger = logging.getLogger("jpintel.orchestrator_v2")

router = APIRouter(prefix="/v1/orchestrate", tags=["orchestrate"])

# ---------------------------------------------------------------------------
# Pricing + limits
# ---------------------------------------------------------------------------

# 1 orchestrate call = ``ORCHESTRATE_UNIT_COUNT`` units. 3x covers the
# composition cost (query + payload + outbound POST). Stripe records this
# as quantity=3 against the orchestrate.<target> endpoint name.
ORCHESTRATE_UNIT_COUNT = 3

# Minimum seconds between two orchestrate calls from the same key. 10s caps
# an agent loop at 6 calls/min × ¥9 = ¥54/min. Plenty of room to revoke
# from /v1/me/keys before the daily cap blows.
ORCHESTRATE_MIN_INTERVAL_S = 10

# Per-call payload row cap. Each row maps to one outbound HTTP POST so
# orchestration cost is bounded by the row count. 20 covers the typical
# 仕訳 monthly fan-out without letting one call burn ¥60.
ORCHESTRATE_MAX_ROWS = 20

# Outbound HTTP timeout. External SaaS APIs (freee / MF / Notion / Slack)
# all p99 < 5s. 8s gives headroom without holding the Fly worker hostage.
ORCHESTRATE_HTTP_TIMEOUT_S = 8

# Allowed target names. Adding a new target requires:
#   (1) new ``/v1/orchestrate/{target}`` route + body model below,
#   (2) new ``_invoke_<target>`` helper below,
#   (3) a smoke test in tests/test_dimension_f_orchestration.py.
_ALLOWED_TARGETS: tuple[str, ...] = ("freee", "mf", "notion", "slack")

# In-memory rate-floor state. Matches export.py pattern.
_orchestrate_rate_state: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _FreeeAccountRow(BaseModel):
    """One row from the customer's freee 仕訳 export."""

    model_config = ConfigDict(extra="forbid")

    account_item: str = Field(..., min_length=1, max_length=120)
    amount_yen: int | None = Field(None, ge=0)


class FreeeOrchestrateRequest(BaseModel):
    """POST /v1/orchestrate/freee body."""

    model_config = ConfigDict(extra="forbid")

    freee_token: str = Field(
        ...,
        min_length=4,
        max_length=512,
        description=(
            "freee personal access token. Request-scoped — NEVER stored. "
            "We use it ONCE on this request to push the matched rows into "
            "the customer's freee workspace (best-effort; non-2xx is "
            "returned in the response but does NOT 5xx the call)."
        ),
    )
    company_id: int = Field(
        ...,
        ge=1,
        description="freee 事業所 ID.",
    )
    rows: list[_FreeeAccountRow] = Field(
        ...,
        min_length=1,
        max_length=ORCHESTRATE_MAX_ROWS,
    )


class _MfAccountRow(BaseModel):
    """One row from a MoneyForward Cloud 経費 export."""

    model_config = ConfigDict(extra="forbid")

    account_code: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=480)


class MfOrchestrateRequest(BaseModel):
    """POST /v1/orchestrate/mf body."""

    model_config = ConfigDict(extra="forbid")

    mf_token: str = Field(..., min_length=4, max_length=512)
    office_id: str = Field(..., min_length=1, max_length=64)
    rows: list[_MfAccountRow] = Field(
        ...,
        min_length=1,
        max_length=ORCHESTRATE_MAX_ROWS,
    )


class NotionOrchestrateRequest(BaseModel):
    """POST /v1/orchestrate/notion body."""

    model_config = ConfigDict(extra="forbid")

    notion_token: str = Field(..., min_length=4, max_length=512)
    database_id: str = Field(..., min_length=8, max_length=64)
    amendment_keys: list[str] = Field(
        ...,
        min_length=1,
        max_length=ORCHESTRATE_MAX_ROWS,
        description=(
            "Free-text search keys (program_name / law name / am_amendment_diff "
            "subject substring). Each key resolves to up to 1 Notion page."
        ),
    )


class SlackOrchestrateRequest(BaseModel):
    """POST /v1/orchestrate/slack body."""

    model_config = ConfigDict(extra="forbid")

    slack_webhook_url: str = Field(
        ...,
        min_length=24,
        max_length=512,
        pattern=r"^https://hooks\.slack\.com/services/.+",
    )
    kind: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=2000)
    url: str = Field(..., min_length=4, max_length=1024)
    event: Literal["info", "warn", "alert"] = "info"


class _OrchestrateResultRow(BaseModel):
    target: Literal["freee", "mf", "notion", "slack"]
    input_key: str
    matched_program_id: str | None = None
    matched_program_name: str | None = None
    source_url: str | None = None
    delivery_status: int = Field(
        ...,
        description="HTTP status returned by the external SaaS. 0 = network failure.",
    )


class OrchestrateResponse(BaseModel):
    target: Literal["freee", "mf", "notion", "slack"]
    rows_in: int
    rows_matched: int
    rows_delivered: int
    results: list[_OrchestrateResultRow]
    metered_units: int
    disclaimer: str = Field(alias="_disclaimer")
    generated_at: str

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rate_floor_check(key_hash: str) -> None:
    """Raise 429 if the same key called this surface in the last 10s."""
    now = time.monotonic()
    last = _orchestrate_rate_state.get(key_hash)
    if last is not None and (now - last) < ORCHESTRATE_MIN_INTERVAL_S:
        retry_after = int(ORCHESTRATE_MIN_INTERVAL_S - (now - last)) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "orchestrate rate limit (1/10s per key)",
                "retry_after_s": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    _orchestrate_rate_state[key_hash] = now


def _match_program(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    """Best-effort programs.search by keyword. Returns first row or None.

    The search fence here is deliberately narrow — we LIKE-match against
    ``program_name`` only so an ambiguous ``account_item='通信費'`` row
    doesn't pull in 1000 hits. Empty hits return None which the caller
    surfaces as ``matched_program_id=null`` (still ¥3/req — the
    composition cost was paid regardless).
    """
    key = key.strip()
    if not key:
        return None
    cur = conn.cursor()
    try:
        row = cur.execute(
            """
            SELECT program_id, name, source_url
              FROM programs
             WHERE tier IN ('S','A','B','C')
               AND excluded = 0
               AND (name LIKE ? OR aliases_json LIKE ?)
             ORDER BY
               CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END
             LIMIT 1
            """,
            (f"%{key}%", f"%{key}%"),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("programs lookup failed for %r: %s", key, exc)
        return None
    if row is None:
        return None
    columns = set(row.keys())
    return {
        "program_id": row["program_id"] if "program_id" in columns else row[0],
        "name": row["name"] if "name" in columns else row[1],
        "source_url": row["source_url"] if "source_url" in columns else row[2],
    }


def _http_post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> int:
    """POST JSON via stdlib urllib. Returns HTTP status or 0 on network failure.

    Token redaction happens before logging — we log the URL and status,
    never the body or the Authorization header.
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — outbound to allow-listed SaaS hosts
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "jpcite-orchestrate/1.0 (+https://jpcite.com)",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=ORCHESTRATE_HTTP_TIMEOUT_S) as resp:  # noqa: S310
            return int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        # 4xx / 5xx from the target SaaS — return the code, do NOT 5xx here.
        return int(getattr(exc, "code", 502))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("orchestrate POST to %s failed: %s", url, exc)
        return 0


# ---------------------------------------------------------------------------
# Target-specific invokers (one per allowed target)
# ---------------------------------------------------------------------------


def _invoke_freee(token: str, company_id: int, payload: dict[str, Any]) -> int:
    """POST a single 仕訳 tag note via freee receipts API best-effort.

    We do NOT create journal entries automatically — that would be a
    税理士法 §52 boundary issue. Instead we attach a NOTE rows on the
    target receipt (sebuk-shed surface). If the freee org doesn't have
    the receipts add-on the API returns 4xx which we surface honestly.
    """
    url = "https://api.freee.co.jp/api/1/receipts"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "company_id": company_id,
        "description": payload.get("description", "")[:480],
        "issue_date": datetime.now(UTC).date().isoformat(),
        "memo": (payload.get("memo") or "")[:240],
    }
    return _http_post_json(url, headers, body)


def _invoke_mf(token: str, office_id: str, payload: dict[str, Any]) -> int:
    """POST a single 経費 memo via MoneyForward Cloud API best-effort."""
    url = "https://expense.moneyforward.com/api/external/v1/office_member_expenses"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "office_id": office_id,
        "remark": payload.get("description", "")[:480],
        "account_code": payload.get("account_code", "")[:120],
        "amount": int(payload.get("amount_yen") or 0),
    }
    return _http_post_json(url, headers, body)


def _invoke_notion(token: str, database_id: str, payload: dict[str, Any]) -> int:
    """POST a single page to a Notion database with program-amendment context."""
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }
    body = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {
                "title": [{"text": {"content": payload.get("title", "")[:200]}}],
            },
            "Source": {
                "url": payload.get("source_url") or "https://jpcite.com",
            },
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": payload.get("summary", "")[:1900]}},
                    ],
                },
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": _TAX_DISCLAIMER[:1900]}},
                    ],
                },
            },
        ],
    }
    return _http_post_json(url, headers, body)


def _invoke_slack(webhook_url: str, payload: dict[str, Any]) -> int:
    """POST a Block Kit message to a Slack incoming-webhook URL."""
    emoji = {"info": "ℹ️", "warn": "⚠️", "alert": "🚨"}.get(payload.get("event", "info"), "ℹ️")
    title = payload.get("title", "")[:140]
    summary = payload.get("summary", "")[:2900]
    body = {
        "text": title,
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {title}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"<{payload.get('url', 'https://jpcite.com')}|jpcite> · "
                            f"kind=`{payload.get('kind', 'orchestrate')}`"
                        ),
                    }
                ],
            },
        ],
    }
    return _http_post_json(webhook_url, {}, body)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/freee",
    response_model=OrchestrateResponse,
    response_model_by_alias=True,
)
async def orchestrate_freee(
    body: FreeeOrchestrateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: ApiContextDep,
    db: DbDep,
) -> OrchestrateResponse:
    """Map freee 仕訳 account_item rows -> jpcite programs and PUSH a memo."""
    require_metered_api_key(ctx, "orchestrate.freee")
    _rate_floor_check(cast("str", ctx.key_hash))
    results: list[_OrchestrateResultRow] = []
    delivered = 0
    matched = 0
    for row in body.rows:
        match = _match_program(db, row.account_item)
        status_code = 0
        if match is not None:
            matched += 1
            status_code = _invoke_freee(
                body.freee_token,
                body.company_id,
                {
                    "description": f"jpcite match: {match['name']}",
                    "memo": match.get("source_url") or "",
                },
            )
            if 200 <= status_code < 300:
                delivered += 1
        results.append(
            _OrchestrateResultRow(
                target="freee",
                input_key=row.account_item,
                matched_program_id=(match or {}).get("program_id"),
                matched_program_name=(match or {}).get("name"),
                source_url=(match or {}).get("source_url"),
                delivery_status=status_code,
            )
        )
    log_usage(
        db,
        ctx,
        endpoint="orchestrate.freee",
        params={"rows": len(body.rows)},
        background_tasks=background_tasks,
        request=request,
        quantity=ORCHESTRATE_UNIT_COUNT,
        strict_metering=True,
    )
    return OrchestrateResponse(
        target="freee",
        rows_in=len(body.rows),
        rows_matched=matched,
        rows_delivered=delivered,
        results=results,
        metered_units=ORCHESTRATE_UNIT_COUNT,
        disclaimer=_TAX_DISCLAIMER,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@router.post(
    "/mf",
    response_model=OrchestrateResponse,
    response_model_by_alias=True,
)
async def orchestrate_mf(
    body: MfOrchestrateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: ApiContextDep,
    db: DbDep,
) -> OrchestrateResponse:
    """Map MoneyForward 経費 rows -> jpcite programs and PUSH a memo."""
    require_metered_api_key(ctx, "orchestrate.mf")
    _rate_floor_check(cast("str", ctx.key_hash))
    results: list[_OrchestrateResultRow] = []
    delivered = 0
    matched = 0
    for row in body.rows:
        match = _match_program(db, row.account_code)
        status_code = 0
        if match is not None:
            matched += 1
            status_code = _invoke_mf(
                body.mf_token,
                body.office_id,
                {
                    "account_code": row.account_code,
                    "description": row.description or f"jpcite match: {match['name']}",
                    "amount_yen": 0,
                },
            )
            if 200 <= status_code < 300:
                delivered += 1
        results.append(
            _OrchestrateResultRow(
                target="mf",
                input_key=row.account_code,
                matched_program_id=(match or {}).get("program_id"),
                matched_program_name=(match or {}).get("name"),
                source_url=(match or {}).get("source_url"),
                delivery_status=status_code,
            )
        )
    log_usage(
        db,
        ctx,
        endpoint="orchestrate.mf",
        params={"rows": len(body.rows)},
        background_tasks=background_tasks,
        request=request,
        quantity=ORCHESTRATE_UNIT_COUNT,
        strict_metering=True,
    )
    return OrchestrateResponse(
        target="mf",
        rows_in=len(body.rows),
        rows_matched=matched,
        rows_delivered=delivered,
        results=results,
        metered_units=ORCHESTRATE_UNIT_COUNT,
        disclaimer=_TAX_DISCLAIMER,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@router.post(
    "/notion",
    response_model=OrchestrateResponse,
    response_model_by_alias=True,
)
async def orchestrate_notion(
    body: NotionOrchestrateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: ApiContextDep,
    db: DbDep,
) -> OrchestrateResponse:
    """Map amendment keys -> jpcite programs and PUSH one Notion page each."""
    require_metered_api_key(ctx, "orchestrate.notion")
    _rate_floor_check(cast("str", ctx.key_hash))
    results: list[_OrchestrateResultRow] = []
    delivered = 0
    matched = 0
    for key in body.amendment_keys:
        match = _match_program(db, key)
        status_code = 0
        if match is not None:
            matched += 1
            status_code = _invoke_notion(
                body.notion_token,
                body.database_id,
                {
                    "title": f"[jpcite] {match['name']}",
                    "summary": (
                        f"key={key} matched program_id={match['program_id']}. "
                        "Confirm primary source before acting."
                    ),
                    "source_url": match.get("source_url"),
                },
            )
            if 200 <= status_code < 300:
                delivered += 1
        results.append(
            _OrchestrateResultRow(
                target="notion",
                input_key=key,
                matched_program_id=(match or {}).get("program_id"),
                matched_program_name=(match or {}).get("name"),
                source_url=(match or {}).get("source_url"),
                delivery_status=status_code,
            )
        )
    log_usage(
        db,
        ctx,
        endpoint="orchestrate.notion",
        params={"rows": len(body.amendment_keys)},
        background_tasks=background_tasks,
        request=request,
        quantity=ORCHESTRATE_UNIT_COUNT,
        strict_metering=True,
    )
    return OrchestrateResponse(
        target="notion",
        rows_in=len(body.amendment_keys),
        rows_matched=matched,
        rows_delivered=delivered,
        results=results,
        metered_units=ORCHESTRATE_UNIT_COUNT,
        disclaimer=_TAX_DISCLAIMER,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@router.post(
    "/slack",
    response_model=OrchestrateResponse,
    response_model_by_alias=True,
)
async def orchestrate_slack(
    body: SlackOrchestrateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: ApiContextDep,
    db: DbDep,
) -> OrchestrateResponse:
    """One-shot Slack alert via the customer's incoming-webhook URL."""
    require_metered_api_key(ctx, "orchestrate.slack")
    _rate_floor_check(cast("str", ctx.key_hash))
    status_code = _invoke_slack(
        body.slack_webhook_url,
        {
            "kind": body.kind,
            "title": body.title,
            "summary": body.summary,
            "url": body.url,
            "event": body.event,
        },
    )
    delivered = 1 if 200 <= status_code < 300 else 0
    results = [
        _OrchestrateResultRow(
            target="slack",
            input_key=body.kind,
            matched_program_id=None,
            matched_program_name=None,
            source_url=body.url,
            delivery_status=status_code,
        )
    ]
    log_usage(
        db,
        ctx,
        endpoint="orchestrate.slack",
        params={"kind": body.kind, "event": body.event},
        background_tasks=background_tasks,
        request=request,
        quantity=ORCHESTRATE_UNIT_COUNT,
        strict_metering=True,
    )
    return OrchestrateResponse(
        target="slack",
        rows_in=1,
        rows_matched=1,
        rows_delivered=delivered,
        results=results,
        metered_units=ORCHESTRATE_UNIT_COUNT,
        disclaimer=_TAX_DISCLAIMER,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@router.get("/targets")
async def list_targets() -> dict[str, Any]:
    """List orchestration targets + per-call pricing for AI agent self-discovery."""
    return {
        "targets": list(_ALLOWED_TARGETS),
        "unit_count_per_call": ORCHESTRATE_UNIT_COUNT,
        "yen_per_call": ORCHESTRATE_UNIT_COUNT * 3,
        "rate_floor_s": ORCHESTRATE_MIN_INTERVAL_S,
        "max_rows_per_call": ORCHESTRATE_MAX_ROWS,
        "http_timeout_s": ORCHESTRATE_HTTP_TIMEOUT_S,
        "disclaimer": _TAX_DISCLAIMER,
    }
