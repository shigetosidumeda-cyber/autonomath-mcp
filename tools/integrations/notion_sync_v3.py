#!/usr/bin/env python3
"""tools/integrations/notion_sync_v3.py — Notion auto-ticket on amendment/houjin hits.

Wave 35 Axis 6d (2026-05-12). Extends notion_sync_v2.py with event-
driven flows that auto-create Notion rows when:

1. Law amendment detected — new row in am_amendment_diff.
2. 法人 watch hit — new row in houjin_watch.

Modes: amendment / houjin / both.

Auth:
* NOTION_WATCH_TARGETS_JSON — JSON map keyed by customer_id:
    {"<customer_id>": {"token":"<notion>", "database_id":"<id>",
                       "client_ids":["<watch list>"]}}
* AUTONOMATH_DB_PATH

Memory: feedback_no_operator_llm_api / feedback_zero_touch_solo /
        feedback_destruction_free_organization.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notion_sync_v3")

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
RETRY_MAX = 3
RETRY_BASE_S = 1.5

_AM_DB_PATH = os.environ.get(
    "AUTONOMATH_DB_PATH", str(os.environ.get("JPINTEL_DB", "autonomath.db"))
)


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
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
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < RETRY_MAX - 1:
                wait = RETRY_BASE_S * (2**attempt)
                time.sleep(wait)
                last_exc = exc
                continue
            payload = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {exc.code} from {url}: {payload[:300]}") from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            time.sleep(RETRY_BASE_S * (2**attempt))
    raise RuntimeError(f"unable to reach {url} after {RETRY_MAX}: {last_exc!r}")


def _notion_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}


def _connect_ro(path: str) -> sqlite3.Connection | None:
    if not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, timeout=15.0, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _load_targets() -> dict[str, dict[str, Any]]:
    raw = os.environ.get("NOTION_WATCH_TARGETS_JSON")
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


def _create_notion_row(token: str, database_id: str, properties: dict[str, Any]) -> str:
    resp = _request(
        "POST",
        f"{NOTION_API_BASE}/pages",
        headers=_notion_headers(token),
        body={"parent": {"database_id": database_id}, "properties": properties},
    )
    return str(resp.get("id", ""))


def _amendment_hits(since: datetime) -> list[dict[str, Any]]:
    conn = _connect_ro(_AM_DB_PATH)
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='am_amendment_diff'"
        ).fetchone()
        if row is None:
            return []
        try:
            rows = cur.execute(
                "SELECT amendment_id, law_id, effective_from, summary "
                "FROM am_amendment_diff WHERE effective_from >= ? "
                "ORDER BY effective_from DESC LIMIT 200",
                (since.strftime("%Y-%m-%d"),),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _amendment_to_notion_properties(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": {
            "title": [
                {
                    "text": {
                        "content": f"[改正] {hit.get('law_id', '')} — {hit.get('summary', '')[:80]}"
                    }
                }
            ]
        },
        "kind": {"select": {"name": "law_amendment"}},
        "external_id": {"rich_text": [{"text": {"content": str(hit.get("amendment_id", ""))}}]},
        "law_id": {"rich_text": [{"text": {"content": str(hit.get("law_id", ""))}}]},
        "effective_from": (
            {"date": {"start": str(hit.get("effective_from"))}}
            if hit.get("effective_from")
            else {"date": None}
        ),
        "source_url": {"url": f"https://jpcite.com/laws/{hit.get('law_id', '')}.html"},
    }


def cmd_amendment(args: argparse.Namespace) -> int:
    targets = _load_targets()
    if not targets:
        log.info("amendment: no NOTION_WATCH_TARGETS_JSON; noop")
        return 0
    since = datetime.now(UTC) - timedelta(days=args.lookback_days)
    hits = _amendment_hits(since)
    log.info("amendment: %d hits since %s", len(hits), since.date())
    pushed = 0
    for customer_id, cfg in targets.items():
        token = cfg.get("token")
        db_id = cfg.get("database_id")
        if not (token and db_id):
            continue
        for hit in hits:
            try:
                _create_notion_row(token, db_id, _amendment_to_notion_properties(hit))
                pushed += 1
            except RuntimeError as exc:
                log.warning(
                    "amendment customer=%s amendment=%s: %s",
                    customer_id,
                    hit.get("amendment_id"),
                    exc,
                )
    log.info("amendment: %d pushed", pushed)
    return 0


def _houjin_hits(since: datetime) -> list[dict[str, Any]]:
    jpintel_path = os.environ.get("JPINTEL_DB", "data/jpintel.db")
    conn = _connect_ro(jpintel_path)
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='houjin_watch'"
        ).fetchone()
        if row is None:
            return []
        try:
            rows = cur.execute(
                "SELECT watch_id, houjin_bangou, last_seen_at, hit_kind, summary "
                "FROM houjin_watch WHERE last_seen_at >= ? "
                "ORDER BY last_seen_at DESC LIMIT 200",
                (since.isoformat(),),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _houjin_to_notion_properties(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": {
            "title": [
                {
                    "text": {
                        "content": f"[法人 watch] {hit.get('houjin_bangou', '')} — {hit.get('hit_kind', '')}"
                    }
                }
            ]
        },
        "kind": {"select": {"name": "houjin_watch_hit"}},
        "external_id": {"rich_text": [{"text": {"content": str(hit.get("watch_id", ""))}}]},
        "houjin_bangou": {"rich_text": [{"text": {"content": str(hit.get("houjin_bangou", ""))}}]},
        "hit_kind": {"rich_text": [{"text": {"content": str(hit.get("hit_kind", ""))}}]},
        "summary": {"rich_text": [{"text": {"content": str(hit.get("summary", ""))[:1900]}}]},
    }


def cmd_houjin(args: argparse.Namespace) -> int:
    targets = _load_targets()
    if not targets:
        return 0
    since = datetime.now(UTC) - timedelta(days=args.lookback_days)
    hits = _houjin_hits(since)
    pushed = 0
    for _customer_id, cfg in targets.items():
        token = cfg.get("token")
        db_id = cfg.get("database_id")
        scope = set(cfg.get("client_ids") or [])
        if not (token and db_id):
            continue
        for hit in hits:
            if scope and str(hit.get("houjin_bangou", "")) not in scope:
                continue
            try:
                _create_notion_row(token, db_id, _houjin_to_notion_properties(hit))
                pushed += 1
            except RuntimeError as exc:
                log.warning("houjin: %s", exc)
    log.info("houjin: %d pushed", pushed)
    return 0


def cmd_both(args: argparse.Namespace) -> int:
    rc1 = cmd_amendment(args)
    rc2 = cmd_houjin(args)
    return rc1 or rc2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notion_sync_v3")
    sub = p.add_subparsers(dest="mode", required=True)
    for name, fn in (("amendment", cmd_amendment), ("houjin", cmd_houjin), ("both", cmd_both)):
        s = sub.add_parser(name)
        s.add_argument("--lookback-days", type=int, default=7)
        s.set_defaults(func=fn)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log.info("notion_sync_v3 start mode=%s", args.mode)
    rc = int(args.func(args))
    log.info("notion_sync_v3 done mode=%s rc=%d", args.mode, rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
