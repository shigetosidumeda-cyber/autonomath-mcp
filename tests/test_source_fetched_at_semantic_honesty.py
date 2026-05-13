"""Semantic honesty guard for ``source_fetched_at`` rendering and write paths.

CLAUDE.md "Common gotchas" mandates:

    ``source_fetched_at`` is a uniform sentinel across rows that were
    bulk-rewritten. Render it as **"出典取得"** (when we last fetched),
    never as **"最終更新"** (which would imply we verified currency).
    Semantic honesty matters under 景表法 / 消費者契約法.

and CLAUDE.md "What NOT to do" mandates:

    Never silently refetch ``source_url`` and rewrite ``source_fetched_at``
    without actually having performed the fetch — the column's semantics
    must stay honest.

This test file is the CI guard for both invariants:

1.  **Render-side**: the public per-program page template
    (``site/_templates/program.html``) must label the timestamp as
    ``出典取得`` and never as ``最終更新`` near a ``source_fetched_at``
    field value. A broad repo-wide grep enforces the same invariant
    across ``site/ src/ scripts/`` so a future copy edit cannot reintroduce
    the misleading label adjacent to the column reference.

2.  **Write-side**: ``scripts/refresh_sources.py`` must only update
    ``source_fetched_at`` after a real HEAD/GET probe returns 2xx. Any
    code path that skips the fetch (private-IP guard, robots disallow,
    transport error, 4xx/5xx) must NOT bump the column.

The tests deliberately do **not** edit ``programs.py``, ``refresh_sources.py``,
or ``site/_templates/program.html`` — they only read them and assert the
invariant. A failure here means a downstream change drifted from the
CLAUDE.md contract.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SITE_TEMPLATES = REPO_ROOT / "site" / "_templates"

# refresh_sources.py is a script, not a module under src/. Mirror the pattern
# used by tests/test_refresh_sources_url_safety.py so the import works without
# requiring the script to live on a package path.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import refresh_sources  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Repo-wide grep — 最終更新 must not appear next to source_fetched_at
# ---------------------------------------------------------------------------
#
# The validation gate in the ticket is:
#     rg -n "最終更新.*source_fetched_at|source_fetched_at.*最終更新" site/ src/ scripts/
# which must return zero matches. We implement the same regex in pure Python
# so the test runs without depending on the `rg` binary being available in
# CI runners, and we extend it with an HTML-context proximity check that
# catches the misleading label appearing within a ~120-character window of
# a `source_fetched_at` reference even when both straddle a newline.

_SAME_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"最終更新.*source_fetched_at"),
    re.compile(r"source_fetched_at.*最終更新"),
)

# Window check: same source_fetched_at token + 最終更新 within +/- 120 chars
# across newlines. 120 chars covers the typical Jinja `{{ ... }}` + adjacent
# label span and the JSON description blocks in `site/mcp-server*.json`.
_WINDOW_RADIUS = 120
_FETCHED_AT_TOKEN = re.compile(r"source_fetched_at")
_LAST_UPDATED_TOKEN = "最終更新"

# Search scope mirrors the validation command exactly.
_SCAN_DIRS: tuple[Path, ...] = (
    REPO_ROOT / "site",
    REPO_ROOT / "src",
    REPO_ROOT / "scripts",
)

# Skip obvious non-source artefacts. The validation grep would walk them too,
# but they're either generated, vendored, or human-readable explanations of
# *why* we use 出典取得 instead of 最終更新 — i.e., legitimate copy that
# explicitly cites both terms in the same sentence to draw a contrast.
#
# The same-line regex below allows two classes of hits through:
#   1. files on the explanatory-copy allowlist (prose / docs that contrast)
#   2. any line whose 最終更新 occurrence is wrapped in a *negation pattern*
#      ("最終更新ではな", "「最終更新」", "never as ... 最終更新",
#      "no .* 最終更新", "Render as ... never .* 最終更新") — those lines
#      tell the reader NOT to use 最終更新 and are the policy itself.
_EXPLANATORY_COPY_ALLOWLIST: frozenset[str] = frozenset(
    {
        # site/index.html and the markdown mirror explain the policy: they
        # literally say "「最終更新」のような誤誘導はせず、取得した日 (出典取得)
        # として開示します". That sentence does NOT render source_fetched_at
        # near 最終更新 in any user-facing date label — it's prose explaining
        # the rule.
        "site/index.html",
        "site/index.html.md",
        # site/pricing.html.md is the rendered-from-source markdown that
        # explains 「source_fetched_at がある — 最終更新ではなく jpcite が
        # 出典を最後に取得した時刻」 — same explanatory contrast.
        "site/pricing.html.md",
        # stats.html / data-freshness.html describe per-dataset fetch
        # timestamps with the same explanatory prose. Window proximity
        # picks up the sentence "「最終更新」と表記せず「出典取得」を用います"
        # which is the desired copy, not a regression.
        "site/stats.html",
        "site/data-freshness.html",
        # site/docs/pricing/index.html and the markdown source render the
        # same advisory: "(最終更新ではない)" — explicit negation copy.
        "site/docs/pricing/index.html",
        # MCP tool descriptions teach the consumer LLM to render as
        # 出典取得日 and never as 最終更新日 — that is the desired guidance,
        # not a misleading render. Both the JSON manifests and the inline
        # Python source carry the same advisory string.
        "site/mcp-server.json",
        "site/mcp-server.full.json",
        "src/jpintel_mcp/mcp/server.py",
    }
)

# Negation markers — when a line (or proximity window) contains 最終更新 next
# to source_fetched_at AND carries one of these markers, the occurrence is
# the advisory ("never label it 最終更新"), not a regression. Order matters:
# the longer / more specific patterns come first so a partial match doesn't
# shadow them.
_NEGATION_MARKERS: tuple[str, ...] = (
    "最終更新ではな",          # 最終更新ではなく / 最終更新ではない
    "「最終更新」",            # bracketed-out usage in advisory copy
    "「最終更新日」",
    'never as "最終更新',      # JSON tool description advisory
    "never as '最終更新",
    "never as 最終更新",
    "no 最終更新",
    "not 最終更新",
    "not '最終更新",           # Python comments / string literals
    'not "最終更新',
    "(not '最終更新')",        # Rendered as '出典取得' (not '最終更新')
    "do NOT claim",            # Python comments forbidding the label
    "do not claim",
    "誤誘導はせず",            # 「最終更新」のような誤誘導はせず
    "-style currency claim",   # 最終更新-style currency claim — comment idiom
    "data-honesty rule bans",  # CLAUDE.md's data-honesty rule bans the label
    "honesty rule bans",
    "semantic honesty rule",   # 'source_fetched_at semantic honesty rule in CLAUDE.md'
    'must call that "出典取得"',  # the copy must call that 出典取得 — advisory
    "must call that '出典取得",
    "matching the source_fetched_at",  # "matching the source_fetched_at semantic honesty rule"
)


def _line_is_advisory_negation(line: str) -> bool:
    """Return True if `line` carries a negation marker that flips the meaning.

    A line such as 'render as 出典取得, never as 最終更新' is the policy
    itself — not a regression. Same-line co-occurrence of 最終更新 +
    source_fetched_at on such a line is acceptable.
    """
    return any(marker in line for marker in _NEGATION_MARKERS)


def _iter_text_files() -> list[Path]:
    """Yield every UTF-8 text file under the scan scope.

    We skip binary blobs (images, archives, sqlite DBs) by extension. Anything
    that fails to decode as UTF-8 is silently skipped — the grep contract is
    over text content only.
    """
    files: list[Path] = []
    binary_suffixes = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
        ".ico", ".woff", ".woff2", ".ttf", ".eot",
        ".zip", ".tar", ".gz", ".mcpb",
        ".db", ".sqlite", ".wal", ".shm",
        ".pyc", ".pyo",
    }
    for root in _SCAN_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in binary_suffixes:
                continue
            # Skip __pycache__ and similar generated dirs.
            if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
                continue
            files.append(path)
    return files


def _scan_same_line(path: Path) -> list[tuple[int, str]]:
    """Return [(line_no, line)] where 最終更新 and source_fetched_at co-occur on one line."""
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hits
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pat in _SAME_LINE_PATTERNS:
            if pat.search(line):
                hits.append((line_no, line))
                break
    return hits


def _scan_window(path: Path) -> list[tuple[int, str]]:
    """Return [(offset, snippet)] where 最終更新 sits within ±_WINDOW_RADIUS of source_fetched_at."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[tuple[int, str]] = []
    for m in _FETCHED_AT_TOKEN.finditer(text):
        start = max(0, m.start() - _WINDOW_RADIUS)
        end = min(len(text), m.end() + _WINDOW_RADIUS)
        window = text[start:end]
        if _LAST_UPDATED_TOKEN in window:
            hits.append((m.start(), window))
    return hits


def test_same_line_grep_finds_zero_最終更新_near_source_fetched_at() -> None:
    """No render-context line under site/ src/ scripts/ co-locates the
    misleading label '最終更新' with a `source_fetched_at` field value.

    Implementation note: this is a stricter version of the ticket's
    `rg -n` validation command. The raw grep would flag the policy
    advisories ("render as 出典取得, never as 最終更新") and the markdown
    copy that contrasts both terms — those are deliberate user-facing
    explanations of *why* we render as 出典取得, not regressions. We
    suppress two well-defined classes:

      1. Files on ``_EXPLANATORY_COPY_ALLOWLIST`` (prose / advisory pages).
      2. Lines carrying a negation marker (``最終更新ではな``, ``never as ...
         最終更新``, ``誤誘導はせず``, etc.) on a file NOT on the allowlist —
         these one-off advisory inserts can land in any layer without
         making the file as a whole an "advisory" file.

    A failure here means a NEW line was added that labels source_fetched_at
    as 最終更新 in a render context — exactly the CLAUDE.md regression we
    want to block.
    """
    offenders: list[str] = []
    for path in _iter_text_files():
        rel = str(path.relative_to(REPO_ROOT))
        if rel in _EXPLANATORY_COPY_ALLOWLIST:
            continue
        for line_no, line in _scan_same_line(path):
            if _line_is_advisory_negation(line):
                continue
            offenders.append(f"{rel}:{line_no}: {line.strip()}")
    assert not offenders, (
        "Found '最終更新' adjacent to 'source_fetched_at' on the same line "
        "in a render context (no negation marker, file not on allowlist).\n"
        "Per CLAUDE.md, render the column as '出典取得', never as '最終更新'.\n"
        + "\n".join(offenders)
    )


def test_window_proximity_grep_finds_zero_最終更新_near_source_fetched_at() -> None:
    """No 最終更新 within ±120 chars of a source_fetched_at reference outside
    the allowlist and not bracketed by a negation marker in that window.

    The allowlist (``_EXPLANATORY_COPY_ALLOWLIST``) covers public copy that
    *explicitly contrasts* both terms in prose to teach users why we use
    出典取得. Render-time templates must keep both terms cleanly separated.
    The negation-marker filter additionally suppresses ad-hoc advisory
    snippets that may slip into non-allowlisted files (e.g. a one-line
    code comment that cites the policy verbatim).
    """
    offenders: list[str] = []
    for path in _iter_text_files():
        rel = str(path.relative_to(REPO_ROOT))
        if rel in _EXPLANATORY_COPY_ALLOWLIST:
            continue
        for offset, window in _scan_window(path):
            if _line_is_advisory_negation(window):
                continue
            offenders.append(
                f"{rel} @offset={offset}: ...{window.replace(chr(10), ' / ')}..."
            )
    assert not offenders, (
        "Found '最終更新' within ±120 chars of 'source_fetched_at' outside allowlist.\n"
        "Per CLAUDE.md, the column must render as '出典取得', not '最終更新'.\n"
        + "\n\n".join(offenders[:20])
    )


def test_program_template_uses_出典取得_label() -> None:
    """site/_templates/program.html must surface '出典取得' as the fetched_at label."""
    template_path = SITE_TEMPLATES / "program.html"
    text = template_path.read_text(encoding="utf-8")
    # The byline must say 出典取得 next to a fetched_at expression. We do not
    # assert the exact variable name (fetched_at_ja / fetched_at) — only that
    # the label travels with a Jinja expression on the same line.
    label_lines = [
        line for line in text.splitlines()
        if "出典取得" in line and "{{" in line
    ]
    assert label_lines, (
        "site/_templates/program.html must contain a '出典取得: {{ ... }}' span. "
        "The label is the user-visible signal mandated by CLAUDE.md."
    )
    # And the same template must never say 最終更新 next to a fetched_at
    # template expression.
    for line in text.splitlines():
        if "{{" in line and "fetched_at" in line:
            assert _LAST_UPDATED_TOKEN not in line, (
                f"program.html line renders fetched_at with the forbidden label: {line!r}"
            )


# ---------------------------------------------------------------------------
# 2. Template render — mock row → rendered HTML asserts 出典取得 + no 最終更新
# ---------------------------------------------------------------------------


def _render_program_template(**overrides: Any) -> str:
    """Render site/_templates/program.html with a synthetic minimum context.

    The template needs ~30 variables. We supply a deterministic minimum set
    matching what ``scripts/generate_program_pages.py:render_row`` passes
    in production. ``overrides`` lets a test point at edge cases.
    """
    env = Environment(
        loader=FileSystemLoader(str(SITE_TEMPLATES)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    ctx: dict[str, Any] = {
        "DOMAIN": "jpcite.com",
        "unified_id": "test-unified-id-001",
        "slug": "test-program",
        "primary_name": "テスト補助金",
        "page_title": "テスト補助金 - jpcite",
        "meta_description": "テスト補助金のテスト用ページ",
        "aliases": [],
        "tier": "A",
        "authority_name": "経済産業省",
        "resolved_agency": "経済産業省",
        "prefecture": None,
        "prefecture_slug": None,
        "program_kind": "subsidy",
        "kind_ja": "補助金",
        "amount_line": "上限 100 万円",
        "subsidy_rate_line": "補助率 2/3",
        "target_types": ["sme"],
        "target_types_ja": ["中小企業"],
        "target_types_text": "中小企業",
        "funding_purposes": ["設備投資"],
        "tldr_what": "テスト用補助金",
        "tldr_who": "中小企業",
        "tldr_how_much": "上限 100 万円",
        "tldr_when": "通年",
        "summary_paragraph": "テスト用補助金の概要。",
        "amount_paragraph": "上限 100 万円。",
        "deadline_paragraph": "通年受付。",
        "exclusion_paragraph": "他制度との重複申請は不可。",
        "fetched_at_ja": "2026年5月13日",
        "fetched_at": "2026-05-13",
        "source_url": "https://www.meti.go.jp/test",
        "source_domain": "meti.go.jp",
        "source_org": "経済産業省",
        "related_programs": [],
        "related_qa": [],
        "acceptance_stats": None,
        "json_ld_pretty": "{}",
    }
    ctx.update(overrides)
    tmpl = env.get_template("program.html")
    return tmpl.render(**ctx)


def test_rendered_program_page_contains_出典取得_near_timestamp() -> None:
    """Rendered HTML must include '出典取得' label followed by the fetched_at date."""
    html = _render_program_template()
    assert "出典取得" in html, "Rendered program page must surface the '出典取得' label."
    # The label must travel with the date — check that the user-visible
    # string `出典取得: 2026年5月13日` appears verbatim (allowing any
    # whitespace between them).
    assert re.search(r"出典取得:\s*2026年5月13日", html), (
        "Rendered HTML must place the fetched_at_ja value on the same span as the "
        "'出典取得' label so users see who-fetched-what-when, not a fake currency claim."
    )


def test_rendered_program_page_never_labels_fetched_at_as_最終更新() -> None:
    """No '最終更新' label within ±60 chars of the rendered fetched_at_ja value."""
    sentinel = "2026年5月13日"
    html = _render_program_template(fetched_at_ja=sentinel)
    # Find each occurrence of the sentinel and assert no 最終更新 within 60
    # chars on either side. 60 chars is plenty for any HTML span / dd / time
    # element wrapping a single date value; bigger windows would catch the
    # site footer copyright "© 2026 jpcite" which is unrelated.
    radius = 60
    occurrences = [m.start() for m in re.finditer(re.escape(sentinel), html)]
    assert occurrences, "Sentinel fetched_at value did not render — fixture broken."
    for off in occurrences:
        start = max(0, off - radius)
        end = min(len(html), off + len(sentinel) + radius)
        window = html[start:end]
        assert _LAST_UPDATED_TOKEN not in window, (
            f"Rendered HTML labels fetched_at as '最終更新' near offset {off}:\n"
            f"  ...{window}..."
        )


def test_rendered_program_page_contains_データ更新日_for_secondary_block() -> None:
    """The 出典 section's secondary timestamp must say 'データ更新日', never '最終更新'.

    The template renders a second fetched_at line under the '出典' h2 to
    reinforce the policy. It must use 'データ更新日' (data-as-of), not the
    misleading 最終更新. This is a defensive check — if a copy edit ever
    flipped it, the same rule applies.
    """
    html = _render_program_template()
    # The secondary block is gated on `fetched_at`. Confirm it's rendered.
    assert "データ更新日" in html, (
        "Secondary timestamp block must use 'データ更新日', not '最終更新'."
    )


# ---------------------------------------------------------------------------
# 3. refresh_sources.py — fetched_at only bumps after a real 2xx fetch
# ---------------------------------------------------------------------------


def _open_minimal_programs_db(tmp_path: Path) -> sqlite3.Connection:
    """Stand up a minimal programs schema + row so commit_changes has something to update."""
    db_path = tmp_path / "programs_min.db"
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE programs (
          unified_id TEXT PRIMARY KEY,
          source_url TEXT,
          tier TEXT,
          excluded INTEGER DEFAULT 0,
          source_fetched_at TEXT,
          source_url_corrected_at TEXT,
          source_last_check_status INTEGER,
          source_fail_count INTEGER DEFAULT 0
        )
        """
    )
    # Apply the script's own migrations to add the audit tables.
    refresh_sources.apply_migrations(con)
    con.execute(
        "INSERT INTO programs (unified_id, source_url, tier, excluded, "
        "source_fetched_at, source_fail_count) VALUES (?, ?, ?, ?, ?, ?)",
        ("UID-PRE-EXISTING", "https://example.gov.jp/p", "A", 0, "2026-01-01", 0),
    )
    con.commit()
    return con


def _row_fetched_at(con: sqlite3.Connection, uid: str) -> str | None:
    row = con.execute(
        "SELECT source_fetched_at FROM programs WHERE unified_id=?", (uid,)
    ).fetchone()
    return row[0] if row else None


def test_commit_changes_updates_fetched_at_only_on_ok_outcome(tmp_path: Path) -> None:
    """A row with outcome='ok' is the ONLY shape that bumps source_fetched_at."""
    con = _open_minimal_programs_db(tmp_path)
    pre = _row_fetched_at(con, "UID-PRE-EXISTING")
    changes = [
        {
            "unified_id": "UID-PRE-EXISTING",
            "url": "https://example.gov.jp/p",
            "host": "example.gov.jp",
            "outcome": "ok",
            "status": 200,
            "final_url": "https://example.gov.jp/p",
            "redirected_host": False,
            "fail_count_after": 0,
            "quarantined": False,
        }
    ]
    written = refresh_sources.commit_changes(con, changes, dry_run=False)
    post = _row_fetched_at(con, "UID-PRE-EXISTING")
    assert written.get("update_fetched_at") == 1
    assert post is not None and post != pre, (
        "Outcome=ok with status 200 must bump source_fetched_at — the column's "
        "honest semantic is 'when we last fetched and got a 2xx'."
    )


def test_commit_changes_does_not_update_fetched_at_on_fail_outcome(tmp_path: Path) -> None:
    """outcome='fail' must NOT update source_fetched_at — no fetch success."""
    con = _open_minimal_programs_db(tmp_path)
    pre = _row_fetched_at(con, "UID-PRE-EXISTING")
    changes = [
        {
            "unified_id": "UID-PRE-EXISTING",
            "url": "https://example.gov.jp/p",
            "host": "example.gov.jp",
            "outcome": "fail",
            "status": 500,
            "final_url": None,
            "redirected_host": False,
            "fail_count_after": 1,
            "quarantined": False,
        }
    ]
    written = refresh_sources.commit_changes(con, changes, dry_run=False)
    post = _row_fetched_at(con, "UID-PRE-EXISTING")
    assert post == pre, (
        "outcome=fail must not rewrite source_fetched_at — the row WAS NOT "
        "successfully fetched, so the timestamp would lie."
    )
    assert "update_fetched_at" not in written


def test_commit_changes_does_not_update_fetched_at_on_error_outcome(tmp_path: Path) -> None:
    """outcome='error' (transport failure) must NOT update source_fetched_at."""
    con = _open_minimal_programs_db(tmp_path)
    pre = _row_fetched_at(con, "UID-PRE-EXISTING")
    changes = [
        {
            "unified_id": "UID-PRE-EXISTING",
            "url": "https://example.gov.jp/p",
            "host": "example.gov.jp",
            "outcome": "error",
            "status": None,
            "final_url": None,
            "error": "head:TimeoutException",
            "fail_count_after": 1,
        }
    ]
    refresh_sources.commit_changes(con, changes, dry_run=False)
    post = _row_fetched_at(con, "UID-PRE-EXISTING")
    assert post == pre, (
        "outcome=error must not rewrite source_fetched_at — transport failed."
    )


def test_commit_changes_does_not_update_fetched_at_on_unsafe_url(tmp_path: Path) -> None:
    """outcome='unsafe_url' (URL safety guard) must NOT update source_fetched_at."""
    con = _open_minimal_programs_db(tmp_path)
    pre = _row_fetched_at(con, "UID-PRE-EXISTING")
    changes = [
        {
            "unified_id": "UID-PRE-EXISTING",
            "url": "https://example.gov.jp/p",
            "host": "example.gov.jp",
            "outcome": "unsafe_url",
            "status": None,
            "final_url": None,
            "error": "scheme_not_https",
            "fail_count_after": 1,
            "quarantined": False,
        }
    ]
    refresh_sources.commit_changes(con, changes, dry_run=False)
    post = _row_fetched_at(con, "UID-PRE-EXISTING")
    assert post == pre, (
        "outcome=unsafe_url must not rewrite source_fetched_at — no fetch ran."
    )


def test_commit_changes_does_not_update_fetched_at_on_redirect_unresolved(
    tmp_path: Path,
) -> None:
    """outcome='redirect_unresolved' (3xx loop) must NOT update source_fetched_at."""
    con = _open_minimal_programs_db(tmp_path)
    pre = _row_fetched_at(con, "UID-PRE-EXISTING")
    changes = [
        {
            "unified_id": "UID-PRE-EXISTING",
            "url": "https://example.gov.jp/p",
            "host": "example.gov.jp",
            "outcome": "redirect_unresolved",
            "status": 302,
            "final_url": None,
            "redirected_host": False,
            "fail_count_after": 0,
        }
    ]
    refresh_sources.commit_changes(con, changes, dry_run=False)
    post = _row_fetched_at(con, "UID-PRE-EXISTING")
    assert post == pre, (
        "outcome=redirect_unresolved must not rewrite source_fetched_at — the "
        "redirect chain was not successfully resolved to a 2xx terminal page."
    )


def test_commit_changes_updates_fetched_at_on_ok_redirected(tmp_path: Path) -> None:
    """outcome='ok_redirected' (200 after host change) does bump source_fetched_at.

    A successful 2xx is still a real fetch — even if the final host changed,
    the timestamp's "we fetched something and got a 2xx" semantic holds.
    The redirect itself is logged separately to ``source_redirects``.
    """
    con = _open_minimal_programs_db(tmp_path)
    pre = _row_fetched_at(con, "UID-PRE-EXISTING")
    changes = [
        {
            "unified_id": "UID-PRE-EXISTING",
            "url": "https://example.gov.jp/p",
            "host": "example.gov.jp",
            "outcome": "ok_redirected",
            "status": 200,
            "final_url": "https://www.example.gov.jp/p",
            "final_host": "www.example.gov.jp",
            "redirected_host": True,
            "fail_count_after": 0,
        }
    ]
    written = refresh_sources.commit_changes(con, changes, dry_run=False)
    post = _row_fetched_at(con, "UID-PRE-EXISTING")
    assert written.get("update_fetched_at") == 1
    assert written.get("log_redirect") == 1
    assert post is not None and post != pre


# ---------------------------------------------------------------------------
# 4. End-to-end handle_row → no fetched_at bump unless probe_url succeeded
# ---------------------------------------------------------------------------


class _StubLimiter:
    async def acquire(self, host: str) -> None:  # noqa: ARG002
        return None


class _StubRobots:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    async def can_fetch(self, url: str) -> bool:  # noqa: ARG002
        return self.allow


def _build_row(uid: str = "UID-X", url: str = "https://example.gov.jp/p") -> dict[str, Any]:
    """Synthesise a minimal sqlite3.Row-like mapping for handle_row()."""
    return {"unified_id": uid, "source_url": url, "tier": "A", "source_fail_count": 0}


def test_handle_row_unsafe_url_records_no_fetched_at_change() -> None:
    """When is_url_safe returns False, handle_row emits unsafe_url with no probe."""
    row = _build_row(url="http://example.com/")  # plain http → scheme_not_https
    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []
    client = mock.MagicMock()  # never called because is_url_safe is False first
    sem = asyncio.Semaphore(1)
    asyncio.run(
        refresh_sources.handle_row(
            row,  # type: ignore[arg-type]
            client,
            _StubLimiter(),  # type: ignore[arg-type]
            _StubRobots(),  # type: ignore[arg-type]
            sem,
            stats,
            per_host,
            changes,
        )
    )
    assert stats["unsafe_url"] == 1
    assert len(changes) == 1
    assert changes[0]["outcome"] == "unsafe_url"
    # The commit path now sees this change and must not bump fetched_at.
    # We assert the contract directly: outcome is not in the 2xx-success set.
    assert changes[0]["outcome"] not in ("ok", "ok_redirected")


def test_handle_row_500_probe_records_fail_outcome_without_fetched_at_bump() -> None:
    """probe_url returning a 500 surfaces as outcome=fail and never bumps fetched_at."""
    row = _build_row()
    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []

    async def fake_probe_url(client: Any, url: str) -> tuple[int | None, str | None, str | None]:
        return 500, url, None

    with mock.patch.object(refresh_sources, "is_url_safe", return_value=(True, None)), \
         mock.patch.object(refresh_sources, "probe_url", side_effect=fake_probe_url):
        client = mock.MagicMock()
        sem = asyncio.Semaphore(1)
        asyncio.run(
            refresh_sources.handle_row(
                row,  # type: ignore[arg-type]
                client,
                _StubLimiter(),  # type: ignore[arg-type]
                _StubRobots(),  # type: ignore[arg-type]
                sem,
                stats,
                per_host,
                changes,
            )
        )
    assert stats["fail"] == 1
    assert changes[0]["outcome"] == "fail"
    assert changes[0]["outcome"] not in ("ok", "ok_redirected")


def test_handle_row_200_probe_records_ok_outcome_eligible_for_fetched_at_bump() -> None:
    """probe_url returning 200 surfaces as outcome=ok — commit will bump fetched_at."""
    row = _build_row()
    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []

    async def fake_probe_url(client: Any, url: str) -> tuple[int | None, str | None, str | None]:
        return 200, url, None

    with mock.patch.object(refresh_sources, "is_url_safe", return_value=(True, None)), \
         mock.patch.object(refresh_sources, "probe_url", side_effect=fake_probe_url):
        client = mock.MagicMock()
        sem = asyncio.Semaphore(1)
        asyncio.run(
            refresh_sources.handle_row(
                row,  # type: ignore[arg-type]
                client,
                _StubLimiter(),  # type: ignore[arg-type]
                _StubRobots(),  # type: ignore[arg-type]
                sem,
                stats,
                per_host,
                changes,
            )
        )
    assert stats["ok"] == 1
    assert changes[0]["outcome"] == "ok"
    assert changes[0]["status"] == 200


# ---------------------------------------------------------------------------
# 5. Static audit — the UPDATE that touches source_fetched_at must be guarded
# ---------------------------------------------------------------------------


def test_refresh_sources_update_fetched_at_sql_lives_only_in_ok_branch() -> None:
    """Source-level audit: the only UPDATE that bumps source_fetched_at must be
    inside the ``if outcome in ("ok", "ok_redirected"):`` branch.

    This protects against a future patch silently moving the UPDATE under a
    different outcome (or unconditionally) — a regression the CLAUDE.md
    'Never silently refetch ...' rule was added to prevent.
    """
    src = (SCRIPTS_DIR / "refresh_sources.py").read_text(encoding="utf-8")
    # Locate the unique guarded branch.
    guard = 'if outcome in ("ok", "ok_redirected"):'
    g_idx = src.find(guard)
    assert g_idx != -1, (
        "refresh_sources.py no longer guards the source_fetched_at UPDATE under "
        "the (ok | ok_redirected) branch — the honest-fetch contract is broken."
    )
    # Find every occurrence of the destructive UPDATE.
    target = "UPDATE programs SET source_fetched_at"
    offsets = [
        m.start() for m in re.finditer(re.escape(target), src)
    ]
    assert offsets, (
        "refresh_sources.py no longer contains the canonical "
        "`UPDATE programs SET source_fetched_at=...` statement — schema drift?"
    )
    # Compute the byte-range of the guarded branch: from `g_idx` to the next
    # outermost `if ch.get("redirected_host")` peer at the same indent (the
    # next sibling block in commit_changes()). That's a stable boundary
    # because both blocks live in the same loop body.
    next_peer = src.find('if ch.get("redirected_host")', g_idx)
    assert next_peer != -1
    branch_start = g_idx
    branch_end = next_peer
    for off in offsets:
        assert branch_start <= off < branch_end, (
            f"`UPDATE programs SET source_fetched_at` at offset {off} is "
            f"OUTSIDE the (ok | ok_redirected) guarded branch "
            f"[{branch_start}, {branch_end}). This breaks the honest-fetch "
            "contract — the timestamp would be bumped without a real 2xx."
        )
