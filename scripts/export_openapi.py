"""Dump the FastAPI OpenAPI schema to `docs/openapi/v1.json`.

Mirrors what `.github/workflows/openapi.yml` does, but runnable locally.

By default the preview / roadmap endpoints (legal, accounting, calendar) are
**excluded** — they are gated behind `settings.enable_preview_endpoints` and
the stable public export should not leak unimplemented routes. Pass
`--include-preview` to produce an extended export that advertises them
(useful for "roadmap-as-contract" handouts to prospects / partners).

Usage
-----
    python scripts/export_openapi.py
    python scripts/export_openapi.py --include-preview --out docs/openapi/v1_preview.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_app(include_preview: bool):
    # Flip the setting BEFORE importing the API module so `create_app()` sees
    # it. The setting is consulted once at app-construction time.
    if include_preview:
        # Purge any already-imported jpintel_mcp modules so Settings re-reads
        # env vars and the preview routers are included.
        import os

        os.environ["JPINTEL_ENABLE_PREVIEW_ENDPOINTS"] = "true"
        for mod in list(sys.modules):
            if mod.startswith("jpintel_mcp"):
                del sys.modules[mod]

    from jpintel_mcp.api.main import create_app

    return create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-preview",
        action="store_true",
        help="Include preview/roadmap endpoints in the output (default: exclude).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/openapi/v1.json"),
        help="Output path (default: docs/openapi/v1.json).",
    )
    args = parser.parse_args()

    app = _build_app(include_preview=args.include_preview)
    schema = app.openapi()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    preview_paths = [
        p
        for p in schema.get("paths", {})
        if p.startswith(("/v1/legal", "/v1/accounting", "/v1/calendar"))
    ]
    mode = "with preview" if args.include_preview else "stable"
    print(
        f"wrote {args.out} ({mode}), "
        f"{len(schema.get('paths', {}))} paths "
        f"({len(preview_paths)} preview)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
