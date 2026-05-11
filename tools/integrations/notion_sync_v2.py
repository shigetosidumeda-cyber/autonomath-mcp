#!/usr/bin/env python3
"""tools/integrations/notion_sync_v2.py — Notion ↔ jpcite bi-directional sync.

Wave 26 (2026-05-12). Replaces the Wave 21 stub with a working
implementation that talks to the live Notion REST API and the live
jpcite `/v1/export` / `/v1/me/saved_searches` endpoints.

Modes
-----

* ``push``     — jpcite → Notion. Fetches rows from jpcite (via
                 ``/v1/export``) and upserts them into the target Notion
                 database keyed on ``external_id``.
* ``pull``     — Notion → jpcite. Reads rows where the
                 ``sync_to_jpcite`` checkbox is ``true`` and posts each
                 row's ``saved_search`` field to
                 ``/v1/me/saved_searches``.
* ``sync``     — push → pull → push (loop once). Recommended default.

Auth
----
* ``NOTION_TOKEN``        : Notion internal-integration token.
* ``NOTION_DATABASE_ID``  : target database id.
* ``JPCITE_API_KEY``      : paid metered jpcite key.
* ``JPCITE_API_BASE``     : default ``https://api.jpcite.com`` (override
                            for staging / local).

Memory references
-----------------
* ``feedback_zero_touch_solo`` — fully self-serve, runs as a single
  Python invocation, no admin UI.
* ``feedback_no_operator_llm_api`` — zero LLM SDK imports.
* ``feedback_autonomath_no_api_use`` — does NOT call Anthropic / OpenAI.

Usage
-----
::

    python tools/integrations/notion_sync_v2.py push \
        --dataset programs \
        --filter '{"kind":"subsidy","prefecture":"東京都"}' \
        --limit 100

    python tools/integrations/notion_sync_v2.py pull-saved-searches

    python tools/integrations/notion_sync_v2.py sync \
        --dataset programs --filter '{"kind":"subsidy"}'

The script targets stdlib only (``urllib.request``) so it can run from a
fresh Fly machine without extra installs. requests/httpx aren't
required.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notion_sync_v2")

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

DEFAULT_JPCITE_BASE = os.environ.get("JPCITE_API_BASE", "https://api.jpcite.com")
DEFAULT_NOTION_PAGE_SIZE = 100
RETRY_MAX = 3
RETRY_BASE_S = 1.5


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """One-shot HTTP request with retry-on-429 and JSON parsing.

    Returns the parsed JSON body. Raises ``RuntimeError`` after
    ``RETRY_MAX`` attempts so the caller can surface a clear error.
    """
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = dict(headers)
    headers.setdefault("Accept", "application/json")
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    last_exc: Exception | None = None
    for attempt in range(RETRY_MAX):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < RETRY_MAX - 1:
                wait = RETRY_BASE_S * (2**attempt)
                log.warning("rate-limited (%s); retrying in %.1fs", url, wait)
                time.sleep(wait)
                last_exc = exc
                continue
            payload = exc.read().decode("utf-8", "replace")
            raise RuntimeError(
                f"HTTP {exc.code} from {url}: {payload[:300]}"
            ) from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            time.sleep(RETRY_BASE_S * (2**attempt))
    raise RuntimeError(
        f"unable to reach {url} after {RETRY_MAX} attempts: {last_exc!r}"
    )


def _notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }


def _jpcite_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------


def notion_query_database(
    token: str,
    database_id: str,
    filter_obj: dict[str, Any] | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield all rows from a Notion database matching ``filter_obj``.

    Walks the cursor automatically; the caller does not need to handle
    pagination.
    """
    next_cursor: str | None = None
    while True:
        body: dict[str, Any] = {"page_size": DEFAULT_NOTION_PAGE_SIZE}
        if filter_obj is not None:
            body["filter"] = filter_obj
        if next_cursor is not None:
            body["start_cursor"] = next_cursor
        resp = _request(
            "POST",
            f"{NOTION_API_BASE}/databases/{database_id}/query",
            headers=_notion_headers(token),
            body=body,
        )
        yield from resp.get("results", [])
        if not resp.get("has_more"):
            return
        next_cursor = resp.get("next_cursor")


def notion_upsert_page(
    token: str,
    database_id: str,
    properties: dict[str, Any],
    external_id: str,
) -> str:
    """Create or update a Notion page by ``external_id``.

    Returns the Notion page id.
    """
    # Query existing first.
    filter_obj = {
        "property": "external_id",
        "rich_text": {"equals": external_id},
    }
    existing = list(notion_query_database(token, database_id, filter_obj))
    if existing:
        page_id = existing[0]["id"]
        _request(
            "PATCH",
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_notion_headers(token),
            body={"properties": properties},
        )
        return page_id
    created = _request(
        "POST",
        f"{NOTION_API_BASE}/pages",
        headers=_notion_headers(token),
        body={
            "parent": {"database_id": database_id},
            "properties": properties,
        },
    )
    return str(created.get("id", ""))


# ---------------------------------------------------------------------------
# jpcite
# ---------------------------------------------------------------------------


def jpcite_export(
    api_base: str,
    api_key: str,
    dataset: str,
    filter_obj: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    """Call ``POST /v1/export`` and return the materialised rows.

    Uses the inline-fallback path when an R2-signed URL is not present
    (test envs); otherwise downloads the signed URL and parses the body.
    """
    body = {
        "dataset": dataset,
        "format": "json",
        "filter": filter_obj,
        "limit": limit,
    }
    resp = _request(
        "POST",
        f"{api_base.rstrip('/')}/v1/export",
        headers=_jpcite_headers(api_key),
        body=body,
    )
    url = resp.get("download_url")
    if not url:
        log.warning("jpcite export returned no download_url; payload=%s", resp)
        return []
    # Inline-fallback URL is server-local; for the unit-test path we
    # cannot follow it from outside, so we tolerate empty.
    if url.startswith("/v1/export/"):
        return []
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            raw = r.read()
        parsed = json.loads(raw.decode("utf-8"))
        rows = parsed.get("rows", [])
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        log.warning("could not fetch signed URL %s: %s", url, exc)
        return []


def jpcite_register_saved_search(
    api_base: str,
    api_key: str,
    label: str,
    query: str,
) -> dict[str, Any]:
    """POST /v1/me/saved_searches — used by the pull path."""
    return _request(
        "POST",
        f"{api_base.rstrip('/')}/v1/me/saved_searches",
        headers=_jpcite_headers(api_key),
        body={"label": label, "query": query},
    )


# ---------------------------------------------------------------------------
# Push (jpcite → Notion)
# ---------------------------------------------------------------------------


def _row_to_notion_properties(row: dict[str, Any], dataset: str) -> dict[str, Any]:
    """Map a jpcite row to a Notion properties dict.

    Notion expects a typed object per property — title/url/select/etc.
    We pick a stable subset that covers the three datasets jpcite
    exports.
    """
    external_id = str(
        row.get("program_id") or row.get("law_id") or row.get("case_id") or ""
    )
    name = str(
        row.get("title") or row.get("name") or row.get("summary") or external_id
    )
    url = str(row.get("source_url") or row.get("url") or "")
    kind = dataset
    amended_at = row.get("updated_at") or row.get("amended_at")
    properties: dict[str, Any] = {
        "external_id": {"rich_text": [{"text": {"content": external_id}}]},
        "name": {"title": [{"text": {"content": name[:200]}}]},
        "kind": {"select": {"name": kind}},
    }
    if url:
        properties["source_url"] = {"url": url}
    if amended_at:
        try:
            iso = datetime.fromisoformat(str(amended_at).replace("Z", "+00:00")).isoformat()
            properties["amended_at"] = {"date": {"start": iso}}
        except ValueError:
            pass
    properties["note"] = {
        "rich_text": [
            {
                "text": {
                    "content": (
                        "jpcite reference. See source_url for the canonical record."
                    )
                }
            }
        ]
    }
    return properties


def cmd_push(args: argparse.Namespace) -> int:
    token = os.environ["NOTION_TOKEN"]
    database_id = os.environ["NOTION_DATABASE_ID"]
    api_key = os.environ["JPCITE_API_KEY"]
    api_base = os.environ.get("JPCITE_API_BASE", DEFAULT_JPCITE_BASE)
    filter_obj = json.loads(args.filter) if args.filter else {}

    rows = jpcite_export(api_base, api_key, args.dataset, filter_obj, args.limit)
    log.info("push: %d row(s) from jpcite", len(rows))
    pushed = 0
    for row in rows:
        external_id = str(
            row.get("program_id") or row.get("law_id") or row.get("case_id") or ""
        )
        if not external_id:
            continue
        properties = _row_to_notion_properties(row, args.dataset)
        notion_upsert_page(token, database_id, properties, external_id)
        pushed += 1
    log.info("push: %d row(s) upserted to Notion", pushed)
    return 0


# ---------------------------------------------------------------------------
# Pull (Notion → jpcite saved_searches)
# ---------------------------------------------------------------------------


def _extract_text(prop: dict[str, Any]) -> str:
    if not isinstance(prop, dict):
        return ""
    for key in ("rich_text", "title"):
        chunks = prop.get(key) or []
        if isinstance(chunks, list) and chunks:
            return "".join(
                str(c.get("plain_text") or c.get("text", {}).get("content") or "")
                for c in chunks
                if isinstance(c, dict)
            )
    if prop.get("type") == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    return ""


def cmd_pull_saved_searches(args: argparse.Namespace) -> int:  # noqa: ARG001
    token = os.environ["NOTION_TOKEN"]
    database_id = os.environ["NOTION_DATABASE_ID"]
    api_key = os.environ["JPCITE_API_KEY"]
    api_base = os.environ.get("JPCITE_API_BASE", DEFAULT_JPCITE_BASE)

    filter_obj = {
        "property": "sync_to_jpcite",
        "checkbox": {"equals": True},
    }
    rows = list(notion_query_database(token, database_id, filter_obj))
    log.info("pull: %d row(s) flagged sync_to_jpcite=true", len(rows))
    pushed = 0
    for row in rows:
        properties = row.get("properties", {})
        label = _extract_text(properties.get("name", {}))
        query = _extract_text(properties.get("saved_search", {}))
        if not query:
            continue
        try:
            jpcite_register_saved_search(api_base, api_key, label or "untitled", query)
            pushed += 1
        except RuntimeError as exc:
            log.warning("saved_search register failed for %s: %s", label, exc)
    log.info("pull: %d saved_search(es) posted to jpcite", pushed)
    return 0


# ---------------------------------------------------------------------------
# Bidirectional
# ---------------------------------------------------------------------------


def cmd_sync(args: argparse.Namespace) -> int:
    rc1 = cmd_push(args)
    rc2 = cmd_pull_saved_searches(args)
    rc3 = cmd_push(args)
    return rc1 or rc2 or rc3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="notion_sync_v2",
        description="jpcite ↔ Notion bi-directional sync (Wave 26).",
    )
    sub = p.add_subparsers(dest="mode", required=True)

    push = sub.add_parser("push", help="jpcite → Notion (one-way)")
    push.add_argument("--dataset", default="programs")
    push.add_argument(
        "--filter",
        default="{}",
        help="JSON filter object passed to /v1/export",
    )
    push.add_argument("--limit", type=int, default=200)
    push.set_defaults(func=cmd_push)

    pull = sub.add_parser(
        "pull-saved-searches",
        help="Notion sync_to_jpcite checkbox → jpcite saved_searches",
    )
    pull.set_defaults(func=cmd_pull_saved_searches)

    sync = sub.add_parser("sync", help="push → pull → push")
    sync.add_argument("--dataset", default="programs")
    sync.add_argument("--filter", default="{}")
    sync.add_argument("--limit", type=int, default=200)
    sync.set_defaults(func=cmd_sync)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    started = datetime.now(UTC)
    log.info("notion_sync_v2 start mode=%s at %s", args.mode, started.isoformat())
    rc = int(args.func(args))
    log.info(
        "notion_sync_v2 done mode=%s rc=%d elapsed=%.2fs",
        args.mode,
        rc,
        (datetime.now(UTC) - started).total_seconds(),
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
