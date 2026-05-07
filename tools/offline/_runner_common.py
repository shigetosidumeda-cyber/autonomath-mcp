"""Shared helpers for tools/offline/run_*_batch.py subagent runners.

OPERATOR ONLY. No LLM SDK imports. Imported by sibling run_*_batch.py
helpers; never imported from src/, scripts/cron/, or scripts/etl/.

The role of this module: keep prompt rendering / JSON-Schema rendering /
inbox path conventions consistent across the 7+ helpers so a single
audit can certify all of them at once.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
INBOX_BASE = Path(__file__).resolve().parent / "_inbox"

# Make `from src.jpintel_mcp.ingest.schemas import ...` and
# `from jpintel_mcp.ingest.schemas import ...` both resolvable from
# operator-side invocations.
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_today_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def chunk(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    if size <= 0:
        size = 1
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def query_rows(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Read-only SELECT helper. No write paths in this module."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def inbox_path(tool_slug: str, batch_id: int) -> Path:
    """Compute inbox JSONL path. {date}-batch_{id}.jsonl per spec."""
    INBOX_BASE.mkdir(parents=True, exist_ok=True)
    sub = INBOX_BASE / tool_slug
    sub.mkdir(parents=True, exist_ok=True)
    date = utc_today_compact()
    return sub / f"{date}-batch_{batch_id:06d}.jsonl"


def render_prompt(
    title: str,
    purpose: str,
    rules: list[str],
    out_path: Path,
    schema_title: str,
    schema_json: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    """Render a self-contained subagent prompt.

    The prompt is dumped to stdout (not invoked). Operator copies it into
    a Claude Code subagent session, which writes one JSONL row per item
    into `out_path`, then `scripts/cron/ingest_offline_inbox.py` validates
    and ingests.
    """
    rules_md = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rules))
    schema_md = json.dumps(schema_json, ensure_ascii=False, indent=2)
    rows_md = json.dumps(rows, ensure_ascii=False, indent=2)
    return f"""\
# {title} (subagent prompt)

## 目的
{purpose}

## 出力先
{out_path}

`{out_path.name}` に **JSON Lines** (1 行 = 1 row) で書き込むこと。
1 行 = 上記スキーマに準拠した JSON object。

## 出力スキーマ ({schema_title}, Pydantic v2 JSON Schema)
```json
{schema_md}
```

## ルール
{rules_md}

## 入力 row list (この batch で処理)
```json
{rows_md}
```

## 注意
- 本 prompt は LLM SDK を一切呼ばず、subagent (Claude Code Task tool 等) 経由で
  operator が手動で実行する想定。
- 投入後の検証は `scripts/cron/ingest_offline_inbox.py` が
  上記 Pydantic schema で行い、fail 行は `_quarantine/` へ moved。
- clause_quote / source_clause_quote 等の literal-quote 列は **改変禁止**。
"""


def emit(
    *,
    tool_slug: str,
    batch_id: int,
    rows: list[dict[str, Any]],
    schema_title: str,
    schema_json: dict[str, Any],
    title: str,
    purpose: str,
    rules: list[str],
    dry_run: bool,
) -> Path:
    """Render the prompt + schema + rows to stdout.

    Returns the inbox path (not yet written; subagent populates it).
    """
    out = inbox_path(tool_slug, batch_id)
    prompt = render_prompt(
        title=title,
        purpose=purpose,
        rules=rules,
        out_path=out,
        schema_title=schema_title,
        schema_json=schema_json,
        rows=rows,
    )
    print("=" * 78)
    print(f"# tool: {tool_slug}")
    print(f"# batch_id: {batch_id}")
    print(f"# rows: {len(rows)}")
    print(f"# inbox path: {out}")
    print(f"# dry_run: {dry_run}")
    print("=" * 78)
    print(prompt)
    return out
