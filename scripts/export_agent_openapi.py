"""Export the agent-safe OpenAPI projection.

Usage:
    uv run python scripts/export_agent_openapi.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jpintel_mcp.api.main import create_app
from jpintel_mcp.api.openapi_agent import build_agent_openapi_schema


def _write(path: Path, schema: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/openapi/agent.json"),
        help="Repo docs output path.",
    )
    parser.add_argument(
        "--site-out",
        type=Path,
        default=Path("site/docs/openapi/agent.json"),
        help="Static site output path.",
    )
    args = parser.parse_args()

    app = create_app()
    schema = build_agent_openapi_schema(app.openapi())
    _write(args.out, schema)
    _write(args.site_out, schema)
    print(f"[ok] wrote {args.out}")
    print(f"[ok] wrote {args.site_out}")


if __name__ == "__main__":
    main()
