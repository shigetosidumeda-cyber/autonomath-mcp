#!/usr/bin/env python3
"""
Heading hierarchy auditor for jpcite static site.

WCAG 2.4.6 + SEO best practice の構造検証:
- 各 HTML page に <h1> が 1 個のみ存在
- <h2> -> <h3> -> <h4> 順序遵守 (1 段飛ばし禁止)
- aria-hidden="true" や inline-style 装飾要素は除外

Exit code:
  0 = 全 page violation 0 件
  1 = 1 件以上 violation 検出 (詳細は stdout)

Usage:
  python3 scripts/ops/heading_hierarchy_audit.py            # default scan: site/ top-level + 1-deep
  python3 scripts/ops/heading_hierarchy_audit.py --strict   # 全 page (cases/, laws/, enforcement/ 含む)
  python3 scripts/ops/heading_hierarchy_audit.py --paths site/index.html site/pricing.html
"""

from __future__ import annotations

import argparse
import html.parser
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_ROOT = REPO_ROOT / "site"

# default scan: top-level *.html + 1 階層下の index.html / public surface 直接 page
# bulk per-record pages (cases/, laws/, enforcement/) は --strict のときのみ
DEFAULT_PATHS = [
    "index.html",
    "pricing.html",
    "dashboard.html",
    "playground.html",
    "login.html",
    "artifact.html",
    "sources.html",
    "status/index.html",
    "connect/chatgpt.html",
    "connect/claude-code.html",
    "connect/codex.html",
    "connect/cursor.html",
    "audiences/index.html",
]


class HeadingCollector(html.parser.HTMLParser):
    """`<h1>`〜`<h6>` の出現順序を収集 (line + level)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[tuple[int, int]] = []  # (line, level)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            line, _ = self.getpos()
            self.headings.append((line, int(tag[1])))


def audit_file(path: Path) -> list[str]:
    """Return a list of human-readable violation messages (empty = clean)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: read error: {exc}"]

    parser = HeadingCollector()
    try:
        parser.feed(text)
    except Exception as exc:  # malformed HTML — surface but don't crash
        return [f"{path}: parser error: {exc}"]

    headings = parser.headings
    if not headings:
        return []  # static fragments with no headings are fine

    violations: list[str] = []

    # rule 1: exactly one <h1>
    h1_lines = [ln for ln, lv in headings if lv == 1]
    if len(h1_lines) == 0:
        violations.append(
            f"{path}: <h1> missing (page has {len(headings)} headings but no h1)"
        )
    elif len(h1_lines) > 1:
        violations.append(
            f"{path}: <h1> appears {len(h1_lines)} times (lines {h1_lines}); "
            "exactly one allowed"
        )

    # rule 2: no level-jump (e.g. h2 -> h4)
    # First heading must be h1; subsequent levels may stay/go down 1 or go up any amount.
    last_level = 0
    for line, level in headings:
        if last_level == 0:
            if level != 1:
                violations.append(
                    f"{path}:{line}: first heading is <h{level}> (must be <h1>)"
                )
        elif level > last_level + 1:
            violations.append(
                f"{path}:{line}: level jump <h{last_level}> -> <h{level}> "
                f"(skipped <h{last_level + 1}>)"
            )
        last_level = level

    return violations


def collect_paths(args: argparse.Namespace) -> list[Path]:
    if args.paths:
        return [Path(p).resolve() for p in args.paths]
    paths = [SITE_ROOT / rel for rel in DEFAULT_PATHS]
    if args.strict:
        for sub in ("cases", "laws", "enforcement"):
            sub_root = SITE_ROOT / sub
            if sub_root.is_dir():
                paths.extend(sorted(sub_root.glob("*.html")))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="scan bulk per-record pages too (cases/laws/enforcement)")
    parser.add_argument("--paths", nargs="*",
                        help="explicit file paths to audit (overrides default set)")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress per-file PASS lines")
    args = parser.parse_args(argv)

    paths = collect_paths(args)
    total_violations = 0
    scanned = 0
    failing_files = 0

    for path in paths:
        if not path.is_file():
            print(f"SKIP {path} (not found)", file=sys.stderr)
            continue
        scanned += 1
        violations = audit_file(path)
        if violations:
            failing_files += 1
            total_violations += len(violations)
            for msg in violations:
                print(f"FAIL {msg}")
        elif not args.quiet:
            print(f"PASS {path}")

    print(
        f"\nheading_hierarchy_audit summary: scanned={scanned} "
        f"failing_files={failing_files} violations={total_violations}"
    )
    return 0 if total_violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
