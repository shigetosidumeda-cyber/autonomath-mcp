#!/usr/bin/env python3
"""tools/integrations/linear_ticket_v2.py — Linear auto-issue creator.

Wave 35 Axis 6d (2026-05-12). Reads jpcite event sources and creates a
Linear issue for every:
* 採択取消 — adoption_revocation row added today
* 行政処分 — enforcement_cases row added/changed today
* 法令改正 — am_amendment_diff row with newly confirmed effective_from

Each issue is filed in the customer's Linear team. Configuration via
LINEAR_TARGETS_JSON.

Memory: feedback_no_operator_llm_api / feedback_zero_touch_solo.
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
log = logging.getLogger("linear_ticket_v2")

LINEAR_API_URL = "https://api.linear.app/graphql"
RETRY_MAX = 3
RETRY_BASE_S = 1.5

_AM_DB_PATH = os.environ.get(
    "AUTONOMATH_DB_PATH", str(os.environ.get("JPINTEL_DB", "autonomath.db"))
)
_JPINTEL_DB_PATH = os.environ.get("JPINTEL_DB", "data/jpintel.db")


def _linear_post(api_key: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}, ensure_ascii=False).encode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(RETRY_MAX):
        req = urllib.request.Request(
            LINEAR_API_URL, data=body, method="POST",
            headers={"Authorization": api_key, "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < RETRY_MAX - 1:
                wait = RETRY_BASE_S * (2 ** attempt)
                time.sleep(wait)
                last_exc = exc
                continue
            text = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"Linear HTTP {exc.code}: {text[:300]}") from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            time.sleep(RETRY_BASE_S * (2 ** attempt))
    raise RuntimeError(f"Linear unreachable after {RETRY_MAX}: {last_exc!r}")


_CREATE_ISSUE_GQL = """
mutation IssueCreate(
  $teamId: String!,
  $title: String!,
  $description: String,
  $labelIds: [String!],
  $priority: Int
) {
  issueCreate(input: {
    teamId: $teamId,
    title: $title,
    description: $description,
    labelIds: $labelIds,
    priority: $priority
  }) {
    success
    issue { id identifier title url }
  }
}
"""


def _linear_create_issue(*, api_key: str, team_id: str, title: str,
                         body: str, label_ids: list[str] | None = None,
                         priority: int = 2) -> dict[str, Any]:
    variables = {
        "teamId": team_id,
        "title": title[:255],
        "description": body[:60_000],
        "labelIds": label_ids or [],
        "priority": priority,
    }
    out = _linear_post(api_key, _CREATE_ISSUE_GQL, variables)
    data = out.get("data") or {}
    return (data.get("issueCreate") or {}).get("issue") or {}


def _ro_connect(path: str) -> sqlite3.Connection | None:
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


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _revocation_hits(lookback_days: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    since = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
    for path in (_AM_DB_PATH, _JPINTEL_DB_PATH):
        conn = _ro_connect(path)
        if conn is None:
            continue
        try:
            for tbl in ("adoption_revocations", "am_adoption_revocation",
                        "jpi_adoption_revocation"):
                if not _table_exists(conn, tbl):
                    continue
                try:
                    rows = conn.execute(
                        f"SELECT * FROM {tbl} "  # noqa: S608
                        "WHERE COALESCE(revoked_at, created_at) >= ? "
                        "ORDER BY COALESCE(revoked_at, created_at) DESC LIMIT 100",
                        (since,),
                    ).fetchall()
                    out.extend({**dict(r), "_source_table": tbl} for r in rows)
                    break
                except sqlite3.Error:
                    continue
        finally:
            conn.close()
        if out:
            break
    return out


def _enforcement_hits(lookback_days: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    since = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
    conn = _ro_connect(_JPINTEL_DB_PATH)
    if conn is None:
        return out
    try:
        if _table_exists(conn, "enforcement_cases"):
            try:
                rows = conn.execute(
                    "SELECT case_id, houjin_bangou, action_kind, action_at, "
                    "title, source_url FROM enforcement_cases "
                    "WHERE action_at >= ? ORDER BY action_at DESC LIMIT 100",
                    (since,),
                ).fetchall()
                out = [dict(r) for r in rows]
            except sqlite3.Error:
                pass
    finally:
        conn.close()
    return out


def _amendment_hits(lookback_days: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    since = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    conn = _ro_connect(_AM_DB_PATH)
    if conn is None:
        return out
    try:
        if _table_exists(conn, "am_amendment_diff"):
            try:
                rows = conn.execute(
                    "SELECT amendment_id, law_id, effective_from, summary "
                    "FROM am_amendment_diff WHERE effective_from >= ? "
                    "ORDER BY effective_from DESC LIMIT 100",
                    (since,),
                ).fetchall()
                out = [dict(r) for r in rows]
            except sqlite3.Error:
                pass
    finally:
        conn.close()
    return out


def _load_targets() -> dict[str, dict[str, Any]]:
    raw = os.environ.get("LINEAR_TARGETS_JSON")
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


def _fan_out(*, kind: str, hits: list[dict[str, Any]], title_fn: Any, body_fn: Any) -> int:
    targets = _load_targets()
    if not targets:
        return 0
    pushed = 0
    for customer_id, cfg in targets.items():
        api_key = cfg.get("api_key"); team_id = cfg.get("team_id")
        labels = cfg.get("label_ids") or []
        if not (api_key and team_id):
            continue
        for hit in hits:
            try:
                issue = _linear_create_issue(
                    api_key=api_key, team_id=team_id,
                    title=title_fn(hit), body=body_fn(hit),
                    label_ids=labels, priority=cfg.get("priority", 2),
                )
                if issue:
                    pushed += 1
            except RuntimeError as exc:
                log.warning("%s customer=%s: %s", kind, customer_id, exc)
    return pushed


def cmd_revocation(args: argparse.Namespace) -> int:
    hits = _revocation_hits(args.lookback_days)
    log.info("revocation: %d hits", len(hits))
    n = _fan_out(
        kind="revocation", hits=hits,
        title_fn=lambda h: f"[採択取消] {h.get('program_id', '')} — {h.get('houjin_bangou', '')}",
        body_fn=lambda h: (
            "## 採択取消\n"
            f"- 制度: {h.get('program_id', '')}\n"
            f"- 法人番号: {h.get('houjin_bangou', '')}\n"
            f"- 取消日: {h.get('revoked_at') or h.get('created_at') or 'unknown'}\n"
            f"- 取消理由: {h.get('reason', '')}\n"
            f"- 出典: {h.get('source_url', '')}\n"
        ),
    )
    log.info("revocation: %d Linear issues", n)
    return 0


def cmd_enforcement(args: argparse.Namespace) -> int:
    hits = _enforcement_hits(args.lookback_days)
    log.info("enforcement: %d hits", len(hits))
    n = _fan_out(
        kind="enforcement", hits=hits,
        title_fn=lambda h: f"[行政処分] {h.get('action_kind', '')} — {h.get('houjin_bangou', '')}",
        body_fn=lambda h: (
            "## 行政処分\n"
            f"- 法人番号: {h.get('houjin_bangou', '')}\n"
            f"- 処分種別: {h.get('action_kind', '')}\n"
            f"- 処分日: {h.get('action_at', '')}\n"
            f"- 件名: {h.get('title', '')}\n"
            f"- 出典: {h.get('source_url', '')}\n"
        ),
    )
    log.info("enforcement: %d Linear issues", n)
    return 0


def cmd_amendment(args: argparse.Namespace) -> int:
    hits = _amendment_hits(args.lookback_days)
    log.info("amendment: %d hits", len(hits))
    n = _fan_out(
        kind="amendment", hits=hits,
        title_fn=lambda h: f"[法令改正] {h.get('law_id', '')} {h.get('effective_from', '')}",
        body_fn=lambda h: (
            "## 法令改正\n"
            f"- amendment_id: {h.get('amendment_id', '')}\n"
            f"- law_id: {h.get('law_id', '')}\n"
            f"- effective_from: {h.get('effective_from', '')}\n"
            f"- summary: {h.get('summary', '')}\n"
            f"- jpcite link: https://jpcite.com/laws/{h.get('law_id', '')}.html\n"
        ),
    )
    log.info("amendment: %d Linear issues", n)
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    rc1 = cmd_revocation(args)
    rc2 = cmd_enforcement(args)
    rc3 = cmd_amendment(args)
    return rc1 or rc2 or rc3


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="linear_ticket_v2")
    sub = p.add_subparsers(dest="mode", required=True)
    for name, fn in (("revocation", cmd_revocation), ("enforcement", cmd_enforcement),
                     ("amendment", cmd_amendment), ("all", cmd_all)):
        s = sub.add_parser(name)
        s.add_argument("--lookback-days", type=int, default=7)
        s.set_defaults(func=fn)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log.info("linear_ticket_v2 start mode=%s", args.mode)
    rc = int(args.func(args))
    log.info("linear_ticket_v2 done mode=%s rc=%d", args.mode, rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
