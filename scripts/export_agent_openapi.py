"""Export the agent-safe OpenAPI projection.

Usage:
    uv run python scripts/export_agent_openapi.py

The agent projection is built off the live FastAPI app schema, so it inherits
the same FastAPI/Pydantic docstring leak surface as the full export. We apply
the same A3-style leak sanitizer used by `scripts/export_openapi.py` (shared
helpers `sanitize_openapi_schema_leaks` + `assert_no_openapi_leaks`) so internal
table names / DB filenames / Wave/migration markers / operator script paths
never reach the published agent specs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jpintel_mcp.api.main import create_app
from jpintel_mcp.api.openapi_agent import build_agent_openapi_schema

# Reuse the leak sanitizer + post-write gate defined in the sibling script so
# the denylist lives in exactly one place.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from export_openapi import (  # noqa: E402
    assert_no_openapi_leaks,
    sanitize_openapi_schema_leaks,
)


def _write(path: Path, schema: dict) -> None:
    payload = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    assert_no_openapi_leaks(payload, label=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


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
    parser.add_argument(
        "--site-root-out",
        type=Path,
        default=Path("site/openapi.agent.json"),
        help="Static site root alias output path.",
    )
    parser.add_argument(
        "--site-directory-out",
        type=Path,
        default=Path("site/openapi/agent.json"),
        help="Static site directory alias output path.",
    )
    args = parser.parse_args()

    app = create_app()
    schema = build_agent_openapi_schema(app.openapi())
    # Apply the same A3-style leak sanitizer used by the full exporter so the
    # agent projection inherits the rules without duplicating the denylist.
    sanitize_openapi_schema_leaks(schema)
    _write(args.out, schema)
    _write(args.site_root_out, schema)
    _write(args.site_out, schema)
    _write(args.site_directory_out, schema)
    print(f"[ok] wrote {args.out}")
    print(f"[ok] wrote {args.site_root_out}")
    print(f"[ok] wrote {args.site_out}")
    print(f"[ok] wrote {args.site_directory_out}")


if __name__ == "__main__":
    main()
