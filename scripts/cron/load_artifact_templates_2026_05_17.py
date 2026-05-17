#!/usr/bin/env python3
"""Bulk-load 50 artifact template YAML files into autonomath.am_artifact_templates.

Lane N1 — 実務成果物テンプレート bank loader.

Reads every ``data/artifact_templates/{segment}/{artifact_type}.yaml`` and
INSERT OR REPLACE-es it into ``am_artifact_templates``. Idempotent — safe
to run on every boot or as part of a cron schedule.

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
TEMPLATE_ROOT = REPO_ROOT / "data" / "artifact_templates"


def resolve_db_path() -> Path:
    env_path = os.environ.get("AUTONOMATH_DB_PATH")
    if env_path:
        return Path(env_path)
    primary = REPO_ROOT / "autonomath.db"
    if primary.exists():
        return primary
    return REPO_ROOT / "data" / "autonomath.db"


def load_yaml_as_json(path: Path) -> dict[str, Any]:
    """Templates are emitted as JSON-as-YAML, so json.loads round-trips."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected dict at top level, got {type(data).__name__}")
    return data


def upsert(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    structure = json.dumps({"sections": data["sections"]}, ensure_ascii=False, sort_keys=False)
    placeholders = json.dumps(data["placeholders"], ensure_ascii=False, sort_keys=False)
    bindings = json.dumps(data["mcp_query_bindings"], ensure_ascii=False, sort_keys=False)
    conn.execute(
        """
        INSERT INTO am_artifact_templates (
            segment, artifact_type, artifact_name_ja, version,
            authority, sensitive_act,
            is_scaffold_only, requires_professional_review,
            uses_llm, quality_grade,
            structure_jsonb, placeholders_jsonb, mcp_query_bindings_jsonb,
            license, notes, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT (segment, artifact_type, version) DO UPDATE SET
            artifact_name_ja = excluded.artifact_name_ja,
            authority = excluded.authority,
            sensitive_act = excluded.sensitive_act,
            is_scaffold_only = excluded.is_scaffold_only,
            requires_professional_review = excluded.requires_professional_review,
            uses_llm = excluded.uses_llm,
            quality_grade = excluded.quality_grade,
            structure_jsonb = excluded.structure_jsonb,
            placeholders_jsonb = excluded.placeholders_jsonb,
            mcp_query_bindings_jsonb = excluded.mcp_query_bindings_jsonb,
            license = excluded.license,
            notes = excluded.notes,
            updated_at = datetime('now')
        ;
        """,
        (
            data["segment"],
            data["artifact_type"],
            data["artifact_name_ja"],
            data.get("version", "v1"),
            data["authority"],
            data["sensitive_act"],
            1 if data.get("is_scaffold_only", True) else 0,
            1 if data.get("requires_professional_review", True) else 0,
            1 if data.get("uses_llm", False) else 0,
            data.get("quality_grade", "draft"),
            structure,
            placeholders,
            bindings,
            data.get("license", "jpcite-scaffold-cc0"),
            data.get("disclaimer", ""),
        ),
    )


def main() -> int:
    db_path = resolve_db_path()
    if not db_path.exists():
        print(f"autonomath.db not found at {db_path}", file=sys.stderr)
        return 2

    template_files = sorted(TEMPLATE_ROOT.glob("*/*.yaml"))
    if not template_files:
        print(f"no template files found under {TEMPLATE_ROOT}", file=sys.stderr)
        return 3

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout = 5000;")
        loaded = 0
        for tf in template_files:
            data = load_yaml_as_json(tf)
            upsert(conn, data)
            loaded += 1
        conn.commit()
    finally:
        conn.close()
    print(f"loaded {loaded} artifact templates into {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
