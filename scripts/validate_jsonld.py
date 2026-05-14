#!/usr/bin/env python3
"""validate_jsonld: extract <script type="application/ld+json"> blocks from site/**/*.html
and verify each published block is parseable JSON.

Source templates under ``site/_templates`` intentionally contain Jinja
placeholders such as ``{{ json_ld_pretty | safe }}``; those are not published
HTML and are rendered before deploy. This gate validates the generated/static
surface only.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Non-greedy match, case-insensitive on the type attribute.
JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def main() -> int:
    targets = [
        path
        for path in (ROOT / "site").rglob("*.html")
        if "_templates" not in path.relative_to(ROOT / "site").parts
    ]
    invalid: list[str] = []
    total_blocks = 0

    for f in targets:
        if not f.is_file():
            continue
        try:
            text = f.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        rel = f.relative_to(ROOT)
        for idx, m in enumerate(JSONLD_RE.finditer(text)):
            total_blocks += 1
            payload = m.group(1).strip()
            if not payload:
                invalid.append(f"{rel}#{idx} EMPTY")
                continue
            try:
                json.loads(payload)
            except json.JSONDecodeError as e:
                invalid.append(f"{rel}#{idx} INVALID: {e.msg} @ line {e.lineno}")

    print(f"scanned files={len(targets)} jsonld_blocks={total_blocks}")
    if invalid:
        for v in invalid[:50]:
            print("FAIL", v)
        if len(invalid) > 50:
            print(f"... and {len(invalid) - 50} more")
        print(f"\n{len(invalid)} invalid JSON-LD blocks")
        return 1
    print("OK: all JSON-LD blocks parse")
    return 0


if __name__ == "__main__":
    sys.exit(main())
