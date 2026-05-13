"""Test that no cross-database ATTACH / JOIN patterns leak into production code.

Enforces the CLAUDE.md "Architecture" gotcha:

    Database: two separate SQLite files, no ATTACH / cross-DB JOIN.

      * `data/jpintel.db` (~352 MB) — core REST/MCP surface tables.
      * `autonomath.db` (~9.4 GB at repo root) — entity-fact EAV schema +
        78 mirrored `jpi_*` tables from the V4 absorption.

The two files are operationally independent. Production code must open
each connection separately and stitch results in Python; `ATTACH
DATABASE` against the sibling file, or a qualified SQL identifier of the
form `jpintel.am_*` / `autonomath.programs` (which only works under
ATTACH), is a regression that:

  * breaks read-only deploys (Fly volume mounts each DB at a distinct
    path and not both into one sqlite process),
  * defeats the per-DB SHA / size-based boot self-heal in
    `entrypoint.sh` §2 / §4 (see CLAUDE.md gotcha block),
  * couples 9.4 GB autonomath.db page-cache pressure with the 352 MB
    jpintel.db hot-path tools, regressing p99 on the cheap surface.

The only tolerated location is the physical-merge migration:

    scripts/migrations/032_*.sql

per CLAUDE.md "V4 absorption" — that migration is the one-shot copy
that populated the 78 `jpi_*` mirrors inside autonomath.db. Once
landed, no other script needs the cross-DB ATTACH path.

Three-axis detection strategy (all axes must stay green):

  * **Axis 1 — `ATTACH DATABASE` literal**: regex over `.py` / `.sql` /
    `.sh` files under `src/` + `scripts/`. Flags both the SQL DDL form
    (`ATTACH DATABASE 'path' AS alias`) and the Python `conn.execute("...
    ATTACH DATABASE ...")` form. String-literal context inside Python is
    intentionally not stripped — the wrapping `conn.execute` IS the
    runtime call.
  * **Axis 2 — Cross-DB qualifier `jpintel.am_`**: regex flags any
    identifier like `jpintel.am_entities`, `jpintel.am_relation`, etc.
    Such a qualifier only resolves under `ATTACH DATABASE ... AS
    jpintel`, so flagging the qualifier catches a JOIN even if the
    ATTACH lives in another file the test cannot trace.
  * **Axis 3 — Cross-DB qualifier `autonomath.programs`**: symmetric
    flag for the reverse direction — `programs` is a jpintel.db table,
    so `autonomath.programs` only resolves under
    `ATTACH DATABASE ... AS autonomath`.

`scripts/migrations/032_*.sql` is the SOLE exemption — it is the
physical merge migration and is allowed to ATTACH/JOIN by definition.

Scope: walks `src/` + `scripts/` (`.py`, `.sql`, `.sh`). The test file
itself is excluded (it names the patterns as the content of the rule
it enforces). `scripts/__pycache__/` and `scripts/_archive/` are
excluded for hygiene.

Pre-commit / CI integration: pytest exits with rc=1 on assertion
failure, which `pre-commit` / GHA `pytest -x` treat as fail-closed.
Do **not** wrap the assertions in try/except — fail-closed is the
contract.
"""

from __future__ import annotations

import pathlib
import re

# Files allowed to carry the cross-DB patterns. ONLY the physical merge
# migration that absorbed jpintel.db into autonomath.db (per CLAUDE.md
# "V4 absorption"). Anything else is a regression.
ALLOWED_PATH_PREFIXES = ("scripts/migrations/032_",)

# Production scan scope. `src/` is the import package + REST + MCP code.
# `scripts/` covers cron + ETL + ops + migrations + bootstrap. Both must
# stay free of ATTACH / cross-DB qualifiers outside the allowlist.
PRODUCTION_DIRS = ("src", "scripts")

# Hygiene exclusions: caches + legacy quarantine never deploy.
EXCLUDED_PATH_FRAGMENTS = (
    "scripts/_archive/",
    "scripts/__pycache__/",
    "__pycache__/",
)

# File suffixes that can carry SQL. `.py` files frequently embed SQL via
# `conn.execute("...")`, `.sql` is bare SQL, `.sh` covers bootstrap
# helpers like `scripts/bootstrap_eval_db.sh` that pipe SQL into
# `sqlite3` via a heredoc.
SCANNED_SUFFIXES = (".py", ".sql", ".sh")

# Axis 1: literal ATTACH DATABASE pattern. Case-insensitive, tolerates
# whitespace variation (`ATTACH  DATABASE`, `attach\tdatabase`, etc.).
_ATTACH_RE = re.compile(r"ATTACH\s+DATABASE", re.IGNORECASE)

# Axis 2: `jpintel.am_X` qualifier — the `jpintel` schema alias dotted
# into an `am_*` table name. Only meaningful under an `ATTACH ... AS
# jpintel`, so the qualifier alone is a smoking gun even when the
# ATTACH itself is in a sibling file.
_JPINTEL_AM_RE = re.compile(r"\bjpintel\.am_[A-Za-z0-9_]+")

# Axis 3: `autonomath.programs` qualifier — `programs` is a jpintel.db
# table, so the qualifier only resolves under `ATTACH ... AS
# autonomath`. We also catch `autonomath.programs.<col>` shapes used in
# docstrings and code.
_AUTONOMATH_PROGRAMS_RE = re.compile(r"\bautonomath\.programs\b")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _is_excluded(rel_posix: str) -> bool:
    return any(frag in rel_posix for frag in EXCLUDED_PATH_FRAGMENTS)


def _is_allowlisted(rel_posix: str) -> bool:
    return any(rel_posix.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


def _iter_scanned_files() -> list[pathlib.Path]:
    """Yield production files under `src/` + `scripts/` with a scanned suffix."""
    out: list[pathlib.Path] = []
    for prod_dir in PRODUCTION_DIRS:
        base = REPO_ROOT / prod_dir
        if not base.exists():
            continue
        for suffix in SCANNED_SUFFIXES:
            for path in base.rglob(f"*{suffix}"):
                rel = path.relative_to(REPO_ROOT).as_posix()
                if _is_excluded(rel):
                    continue
                if _is_allowlisted(rel):
                    continue
                out.append(path)
    return out


def _read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _scan_pattern(path: pathlib.Path, pattern: re.Pattern[str]) -> list[str]:
    """Return list of `line N: <matched text>` hits for `pattern` in `path`."""
    hits: list[str] = []
    text = _read_text(path)
    if not text:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = pattern.search(line)
        if m:
            hits.append(f"line {lineno}: {m.group(0)}")
    return hits


def test_no_attach_database_in_production() -> None:
    """Axis 1: no `ATTACH DATABASE` literal outside the migration-032
    allowlist. Catches both SQL DDL and Python `conn.execute(...)` forms.
    """
    violations: list[str] = []
    for path in _iter_scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        # Self-reference: this test file documents the pattern as the
        # content of the rule it enforces. Skip self.
        if rel == "tests/test_no_cross_db_attach.py":
            continue
        for hit in _scan_pattern(path, _ATTACH_RE):
            violations.append(f"{rel}: {hit}")
    assert not violations, (
        "`ATTACH DATABASE` leaked into production code outside "
        "scripts/migrations/032_*.sql allowlist:\n  - "
        + "\n  - ".join(violations)
        + "\n\nCLAUDE.md: 'Database: two separate SQLite files, no "
        "ATTACH / cross-DB JOIN.' Open each connection separately and "
        "stitch results in Python."
    )


def test_no_jpintel_am_qualifier_in_production() -> None:
    """Axis 2: no `jpintel.am_*` qualifier outside the migration-032
    allowlist. The qualifier only resolves under `ATTACH ... AS jpintel`,
    so even the bare identifier is a regression.
    """
    violations: list[str] = []
    for path in _iter_scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == "tests/test_no_cross_db_attach.py":
            continue
        for hit in _scan_pattern(path, _JPINTEL_AM_RE):
            violations.append(f"{rel}: {hit}")
    assert not violations, (
        "Cross-DB qualifier `jpintel.am_*` found outside "
        "scripts/migrations/032_*.sql allowlist:\n  - "
        + "\n  - ".join(violations)
        + "\n\nThe `am_*` tables live in autonomath.db, not jpintel.db. "
        "Open each connection separately."
    )


def test_no_autonomath_programs_qualifier_in_production() -> None:
    """Axis 3: no `autonomath.programs` qualifier outside the migration-
    032 allowlist. The `programs` table lives in jpintel.db; the
    qualifier only resolves under `ATTACH ... AS autonomath`.
    """
    violations: list[str] = []
    for path in _iter_scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == "tests/test_no_cross_db_attach.py":
            continue
        for hit in _scan_pattern(path, _AUTONOMATH_PROGRAMS_RE):
            violations.append(f"{rel}: {hit}")
    assert not violations, (
        "Cross-DB qualifier `autonomath.programs` found outside "
        "scripts/migrations/032_*.sql allowlist:\n  - "
        + "\n  - ".join(violations)
        + "\n\nThe `programs` table lives in jpintel.db, not autonomath.db. "
        "Open each connection separately."
    )


# --- Synthesized-leak detection tests -----------------------------------
# Verify the scanner functions themselves detect the patterns. Without
# these, a typo in the regex (e.g. `ATACH` instead of `ATTACH`) would
# silently let real leaks through.

_SYNTHESIZED_ATTACH_LEAKS = (
    "ATTACH DATABASE 'data/jpintel.db' AS jp;",
    "attach database '/tmp/x.db' as x;",
    'conn.execute("ATTACH DATABASE \'foo\' AS bar")',
    "ATTACH\tDATABASE '/x' AS y",
)

_SYNTHESIZED_JPINTEL_AM_LEAKS = (
    "SELECT * FROM jpintel.am_entities;",
    "SELECT a.id FROM autonomath.am_relation a JOIN jpintel.am_alias b ON a.id=b.id;",
    "jpintel.am_entity_facts",
)

_SYNTHESIZED_AUTONOMATH_PROGRAMS_LEAKS = (
    "SELECT * FROM autonomath.programs;",
    "JOIN autonomath.programs p ON p.id = x.program_id",
    "autonomath.programs.tier",
)


def test_scan_attach_detects_synthesized_leaks(tmp_path: pathlib.Path) -> None:
    """Synthesized leak: every entry in `_SYNTHESIZED_ATTACH_LEAKS` must
    be flagged by `_ATTACH_RE`. Guards against regex drift.
    """
    misses: list[str] = []
    for stmt in _SYNTHESIZED_ATTACH_LEAKS:
        leak_file = tmp_path / "synthesized_attach.sql"
        leak_file.write_text(f"{stmt}\n", encoding="utf-8")
        hits = _scan_pattern(leak_file, _ATTACH_RE)
        if not hits:
            misses.append(f"`{stmt}` not detected")
    assert not misses, "ATTACH leak not flagged:\n  - " + "\n  - ".join(misses)


def test_scan_jpintel_am_detects_synthesized_leaks(tmp_path: pathlib.Path) -> None:
    """Synthesized leak: every entry in `_SYNTHESIZED_JPINTEL_AM_LEAKS`
    must be flagged by `_JPINTEL_AM_RE`.
    """
    misses: list[str] = []
    for stmt in _SYNTHESIZED_JPINTEL_AM_LEAKS:
        leak_file = tmp_path / "synthesized_jp_am.sql"
        leak_file.write_text(f"{stmt}\n", encoding="utf-8")
        hits = _scan_pattern(leak_file, _JPINTEL_AM_RE)
        if not hits:
            misses.append(f"`{stmt}` not detected")
    assert not misses, "jpintel.am_ leak not flagged:\n  - " + "\n  - ".join(misses)


def test_scan_autonomath_programs_detects_synthesized_leaks(tmp_path: pathlib.Path) -> None:
    """Synthesized leak: every entry in
    `_SYNTHESIZED_AUTONOMATH_PROGRAMS_LEAKS` must be flagged by
    `_AUTONOMATH_PROGRAMS_RE`.
    """
    misses: list[str] = []
    for stmt in _SYNTHESIZED_AUTONOMATH_PROGRAMS_LEAKS:
        leak_file = tmp_path / "synthesized_am_programs.sql"
        leak_file.write_text(f"{stmt}\n", encoding="utf-8")
        hits = _scan_pattern(leak_file, _AUTONOMATH_PROGRAMS_RE)
        if not hits:
            misses.append(f"`{stmt}` not detected")
    assert not misses, (
        "autonomath.programs leak not flagged:\n  - " + "\n  - ".join(misses)
    )


def test_allowlist_path_is_recognized(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Sanity: `scripts/migrations/032_*.sql` is recognized as the sole
    allowlisted prefix. Adding any other prefix without updating
    ALLOWED_PATH_PREFIXES would silently widen the exemption.
    """
    assert ALLOWED_PATH_PREFIXES == ("scripts/migrations/032_",), (
        "ALLOWED_PATH_PREFIXES drifted from CLAUDE.md spec — the only "
        "tolerated cross-DB path is `scripts/migrations/032_*.sql` "
        "(the physical merge of jpintel into autonomath per V4 "
        "absorption). Edits to this tuple must be reviewed against "
        "CLAUDE.md Architecture section."
    )
    # Spot-check the allowlist predicate.
    assert _is_allowlisted("scripts/migrations/032_jpintel_absorption.sql") is True
    assert _is_allowlisted("scripts/migrations/032_anything.sql") is True
    assert _is_allowlisted("scripts/migrations/074_programs_merged_from.sql") is False
    assert _is_allowlisted("scripts/migrations/160_am_adoption_trend_monthly.sql") is False
    assert _is_allowlisted("scripts/unify_dbs.py") is False
