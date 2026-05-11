#!/usr/bin/env python3
"""SEO page chunk push wrapper.

Stage a directory of pre-split chunk files (each containing absolute
``site/{cases,laws,enforcement}/*.html`` or ``*.md`` paths, one per line,
~200 paths per chunk), and incrementally commit + push each chunk on its
own commit so that 50K+ SEO pages (HTML + Wave 17 AX companion-Markdown)
can be landed in safe ~200-page batches.

Wave 17 AX extension
--------------------
HTML chunk prefixes (original):       cases_chunk_ / laws_chunk_ / enf_chunk_
                                       → updates site/sitemap-cases.xml etc.
Companion-Markdown chunk prefixes:    md_cases_chunk_ / md_laws_chunk_ / md_enf_chunk_
                                       → updates site/sitemap-companion-md.xml

Chunks are enumerated in deterministic sort order across the chunk directory
and addressed by integer index (``--start``/``--end``). The naming convention
is the GNU ``split -l 200`` default suffix layout (``cases_chunk_aa``,
``laws_chunk_ay``, ``enf_chunk_ab`` ...); ``--chunk-dir`` should already be
populated.

Per chunk this script:

1. Reads file paths from the chunk file, filtering to existing files only.
2. ``git add`` each path.
3. Appends a fresh ``<url>...</url>`` entry to the matching sitemap
   (``sitemap-cases.xml`` / ``sitemap-laws.xml`` /
   ``sitemap-enforcement-cases.xml``) for any URL not already present.
4. ``git commit`` with a deterministic message:
   ``feat(seo): cases/laws/enforcement chunk N (M page)``.
5. ``git push`` with retry-on-fail (3 attempts, HTTP/1.1 fallback on the
   second attempt).

Use ``--dry-run`` to walk the same plan without staging, committing or pushing.

Usage
-----
    # Dry-run the first chunk to verify what will land
    python3 scripts/ops/seo_chunk_push.py \\
        --chunk-dir /tmp/seo_chunks --start 0 --end 1 --dry-run

    # Push chunks 0..5 (cases 1..5 plus enforcement chunk 0)
    python3 scripts/ops/seo_chunk_push.py \\
        --chunk-dir /tmp/seo_chunks --start 0 --end 5
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CATEGORY_PREFIXES = {
    # HTML SEO page chunks (original Wave 12 surface).
    "cases_chunk_": ("cases", "site/sitemap-cases.xml", "site/cases/"),
    "laws_chunk_": ("laws", "site/sitemap-laws.xml", "site/laws/"),
    "enf_chunk_": ("enforcement", "site/sitemap-enforcement-cases.xml", "site/enforcement/"),
    # Companion-Markdown chunks (Wave 17 AX). Each chunk file lists absolute
    # site/{cat}/{slug}.md paths; the dedicated `sitemap-companion-md.xml`
    # collects all 3 cohorts in one urlset (cases/laws/enforcement md_url
    # combined per generate_sitemap_companion_md.py). Same 200-page-per-chunk
    # cadence and HTTP/1.1 retry strategy applies.
    "md_cases_chunk_": ("cases_md", "site/sitemap-companion-md.xml", "site/cases/"),
    "md_laws_chunk_": ("laws_md", "site/sitemap-companion-md.xml", "site/laws/"),
    "md_enf_chunk_": ("enforcement_md", "site/sitemap-companion-md.xml", "site/enforcement/"),
}

SITE_HOST = "https://jpcite.com"


@dataclass(frozen=True)
class Chunk:
    """Resolved chunk plan."""

    index: int
    category: str  # 'cases' / 'laws' / 'enforcement'
    chunk_path: Path
    sitemap_path: Path
    site_dir: str  # e.g. "site/cases/"

    @property
    def chunk_label(self) -> str:
        return self.chunk_path.name


def _list_chunks(chunk_dir: Path) -> list[Chunk]:
    """Enumerate chunk files in stable sort order, mapped to a category.

    The list excludes ``*_all.txt`` aggregate files and anything that does
    not start with one of the known chunk prefixes.
    """
    chunks: list[Chunk] = []
    for entry in sorted(chunk_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.endswith("_all.txt"):
            continue
        category = None
        sitemap_path: Path | None = None
        site_dir = ""
        for prefix, (cat, sitemap_rel, sd) in CATEGORY_PREFIXES.items():
            if entry.name.startswith(prefix):
                category = cat
                sitemap_path = REPO_ROOT / sitemap_rel
                site_dir = sd
                break
        if category is None or sitemap_path is None:
            continue
        chunks.append(
            Chunk(
                index=len(chunks),
                category=category,
                chunk_path=entry,
                sitemap_path=sitemap_path,
                site_dir=site_dir,
            )
        )
    return chunks


def _read_chunk_file_paths(chunk_path: Path) -> list[Path]:
    """Read absolute file paths from a chunk file, skip blanks + comments."""
    files: list[Path] = []
    for raw in chunk_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        files.append(Path(line))
    return files


def _filter_existing(files: list[Path]) -> tuple[list[Path], list[Path]]:
    existing = [p for p in files if p.exists() and p.is_file()]
    missing = [p for p in files if p not in existing]
    return existing, missing


def _file_to_site_url(file_path: Path) -> str | None:
    """Map ``/.../site/cases/foo.html`` -> ``https://jpcite.com/cases/foo.html``.

    Returns None if the file is outside ``site/``.
    """
    parts = file_path.parts
    try:
        site_ix = parts.index("site")
    except ValueError:
        return None
    relative = "/".join(parts[site_ix + 1:])
    if not relative:
        return None
    return f"{SITE_HOST}/{relative}"


def _read_sitemap_existing_locs(sitemap_path: Path) -> set[str]:
    if not sitemap_path.exists():
        return set()
    body = sitemap_path.read_text(encoding="utf-8")
    return set(re.findall(r"<loc>([^<]+)</loc>", body))


def _append_sitemap_entries(
    sitemap_path: Path,
    new_urls: list[str],
    *,
    dry_run: bool,
) -> int:
    """Append ``<url>`` blocks for ``new_urls`` to the sitemap, keeping
    ``</urlset>`` as the final tag. Returns the count appended.
    """
    if not new_urls:
        return 0
    existing = _read_sitemap_existing_locs(sitemap_path)
    to_add = [u for u in new_urls if u not in existing]
    if not to_add:
        return 0
    if dry_run:
        return len(to_add)
    body = sitemap_path.read_text(encoding="utf-8")
    if "</urlset>" not in body:
        raise RuntimeError(f"sitemap {sitemap_path} missing </urlset> closer")
    today = _today_iso()
    entries = []
    for url in to_add:
        entries.append(
            "  <url>\n"
            f"    <loc>{url}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            "    <changefreq>monthly</changefreq>\n"
            "    <priority>0.5</priority>\n"
            "  </url>\n"
        )
    new_body = body.replace("</urlset>", "".join(entries) + "</urlset>")
    sitemap_path.write_text(new_body, encoding="utf-8")
    return len(to_add)


def _today_iso() -> str:
    """Return today's date as YYYY-MM-DD (UTC). Kept tiny + dep-free."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _run_git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def _stage_files(files: list[Path], sitemap_path: Path, *, dry_run: bool) -> int:
    """``git add`` files in safe batches. Returns count actually staged."""
    repo_root = REPO_ROOT
    rels: list[str] = []
    for f in files:
        try:
            rels.append(str(f.relative_to(repo_root)))
        except ValueError:
            # Outside repo, skip.
            continue
    sitemap_rel = str(sitemap_path.relative_to(repo_root))
    rels.append(sitemap_rel)
    if dry_run:
        return len(rels)
    # git accepts thousands of args fine; chunk just-in-case at 500.
    staged = 0
    for ix in range(0, len(rels), 500):
        batch = rels[ix:ix + 500]
        _run_git(["add", "--", *batch])
        staged += len(batch)
    return staged


def _commit(message: str, *, dry_run: bool) -> bool:
    if dry_run:
        return True
    proc = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        # Nothing to commit is OK (e.g. all files already tracked).
        out = (proc.stdout + proc.stderr).lower()
        if "nothing to commit" in out or "no changes added" in out:
            return False
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"git commit failed for: {message}")
    return True


def _push_with_retry(*, dry_run: bool, attempts: int = 3) -> bool:
    if dry_run:
        return True
    last_err = ""
    for attempt in range(1, attempts + 1):
        env = os.environ.copy()
        # On retry 2+, force HTTP/1.1 to dodge HTTP/2 stream resets that
        # occasionally trip large `site/` pushes on flaky links.
        if attempt >= 2:
            env["GIT_HTTP_VERSION"] = "HTTP/1.1"
        proc = subprocess.run(
            ["git", "push"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            env=env,
        )
        if proc.returncode == 0:
            return True
        last_err = (proc.stdout or "") + (proc.stderr or "")
        sys.stderr.write(f"push attempt {attempt}/{attempts} failed: {last_err[-400:]}\n")
    raise RuntimeError(f"git push failed after {attempts} attempts: {last_err[-400:]}")


def _process_chunk(chunk: Chunk, *, dry_run: bool) -> dict[str, int]:
    files = _read_chunk_file_paths(chunk.chunk_path)
    existing, missing = _filter_existing(files)
    urls = [u for u in (_file_to_site_url(p) for p in existing) if u]
    sitemap_appended = _append_sitemap_entries(
        chunk.sitemap_path, urls, dry_run=dry_run
    )
    staged_count = _stage_files(existing, chunk.sitemap_path, dry_run=dry_run)
    commit_message = (
        f"feat(seo): {chunk.category} chunk {chunk.index} ({len(existing)} page)"
    )
    committed = _commit(commit_message, dry_run=dry_run)
    pushed = False
    if committed:
        pushed = _push_with_retry(dry_run=dry_run)
    return {
        "chunk_index": chunk.index,
        "category": chunk.category,
        "chunk_label": chunk.chunk_label,
        "files_listed": len(files),
        "files_existing": len(existing),
        "files_missing": len(missing),
        "sitemap_appended": sitemap_appended,
        "staged_paths": staged_count,
        "committed": int(committed),
        "pushed": int(pushed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chunk-dir",
        type=Path,
        default=Path("/tmp/seo_chunks"),
        help="Directory containing chunk files (default: /tmp/seo_chunks).",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="First chunk index to process (inclusive, default 0).",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=50,
        help="Last chunk index to process (inclusive, default 50).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk the plan without staging, committing, or pushing.",
    )
    args = parser.parse_args(argv)

    chunk_dir: Path = args.chunk_dir
    if not chunk_dir.exists() or not chunk_dir.is_dir():
        sys.stderr.write(f"chunk dir not found: {chunk_dir}\n")
        return 2

    chunks = _list_chunks(chunk_dir)
    if not chunks:
        sys.stderr.write(f"no chunk files found in {chunk_dir}\n")
        return 2

    selected = [c for c in chunks if args.start <= c.index <= args.end]
    if not selected:
        sys.stderr.write(
            f"no chunks matched range {args.start}..{args.end} "
            f"(total={len(chunks)})\n"
        )
        return 2

    print(
        f"seo_chunk_push: {len(selected)} chunk(s), "
        f"range [{args.start}, {args.end}], "
        f"dry_run={args.dry_run}, total_chunks={len(chunks)}"
    )

    for chunk in selected:
        try:
            result = _process_chunk(chunk, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001 -- surface and continue
            sys.stderr.write(
                f"chunk {chunk.index} ({chunk.chunk_label}) FAILED: {exc}\n"
            )
            return 1
        print(
            f"  chunk {result['chunk_index']:>3} {result['category']:>11} "
            f"{result['chunk_label']:<22} "
            f"files={result['files_existing']}/{result['files_listed']} "
            f"(missing={result['files_missing']}) "
            f"sitemap+={result['sitemap_appended']} "
            f"staged={result['staged_paths']} "
            f"commit={'yes' if result['committed'] else 'noop'} "
            f"push={'yes' if result['pushed'] else 'noop'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
