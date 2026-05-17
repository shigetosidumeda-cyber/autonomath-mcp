#!/usr/bin/env python3
"""Bulk-load placeholder_mappings.json into autonomath.am_placeholder_mapping.

Lane N9 — placeholder -> MCP query mapper loader.

Reads ``data/placeholder_mappings.json`` and INSERT OR REPLACE-es each
mapping row into ``am_placeholder_mapping`` (migration
``wave24_206_am_placeholder_mapping.sql``). Idempotent — safe to run on
every boot or as part of a cron schedule.

Resolution order for autonomath.db path:
  1. ``$AUTONOMATH_DB_PATH`` env var (production volume mount)
  2. ``REPO_ROOT/autonomath.db`` (dev / local)
  3. ``REPO_ROOT/data/autonomath.db`` (fallback)

NO LLM calls. Pure SQLite + JSON file IO.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPINGS_FILE = REPO_ROOT / "data" / "placeholder_mappings.json"


def resolve_db_path() -> Path:
    env_path = os.environ.get("AUTONOMATH_DB_PATH")
    if env_path:
        return Path(env_path)
    primary = REPO_ROOT / "autonomath.db"
    if primary.exists():
        return primary
    return REPO_ROOT / "data" / "autonomath.db"


def load_mappings_json(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict) or "mappings" not in data:
        raise ValueError(f"{path}: expected dict with 'mappings' key, got {type(data).__name__}")
    mappings = data["mappings"]
    if not isinstance(mappings, list):
        raise ValueError(f"{path}: 'mappings' must be a list, got {type(mappings).__name__}")
    return mappings


def upsert(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO am_placeholder_mapping (
            placeholder_name, source_template_ids, mcp_tool_name,
            args_template, output_path, fallback_value, value_kind,
            description, is_sensitive, license,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT (placeholder_name) DO UPDATE SET
            source_template_ids = excluded.source_template_ids,
            mcp_tool_name       = excluded.mcp_tool_name,
            args_template       = excluded.args_template,
            output_path         = excluded.output_path,
            fallback_value      = excluded.fallback_value,
            value_kind          = excluded.value_kind,
            description         = excluded.description,
            is_sensitive        = excluded.is_sensitive,
            license             = excluded.license,
            updated_at          = datetime('now')
        ;
        """,
        (
            row["placeholder_name"],
            row.get("source_template_ids"),
            row["mcp_tool_name"],
            row.get("args_template", "{}"),
            row.get("output_path", "$"),
            row.get("fallback_value"),
            row.get("value_kind", "text"),
            row["description"],
            1 if row.get("is_sensitive", 0) else 0,
            row.get("license", "jpcite-scaffold-cc0"),
        ),
    )


def main() -> int:
    db_path = resolve_db_path()
    if not db_path.exists():
        print(f"autonomath.db not found at {db_path}", file=sys.stderr)
        return 2

    if not MAPPINGS_FILE.exists():
        print(f"placeholder_mappings.json not found at {MAPPINGS_FILE}", file=sys.stderr)
        return 3

    mappings = load_mappings_json(MAPPINGS_FILE)
    if not mappings:
        print("no mappings to load", file=sys.stderr)
        return 4

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout = 5000;")
        loaded = 0
        for row in mappings:
            upsert(conn, row)
            loaded += 1
        conn.commit()
    finally:
        conn.close()
    print(f"loaded {loaded} placeholder mappings into {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
