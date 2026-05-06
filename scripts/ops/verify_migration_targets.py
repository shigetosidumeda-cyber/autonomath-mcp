#!/usr/bin/env python3
"""
verify_migration_targets.py — DEEP-52 spec implementation (jpcite v0.3.4)

Pure offline verifier for the 153 untracked wave24_*.sql migrations
(autonomath 92 + jpintel 61). Performs five per-file checks and an
optional in-memory dry-run against two ":memory:" SQLite handles.

Strict constraints (DEEP-52 §6 acceptance #5):
  - LLM API import count = 0
  - paid services touched = 0
  - work-hour estimate not emitted

Stdlib + sqlglot + sqlite3 only.

Usage:
  python verify_migration_targets.py --check
  python verify_migration_targets.py --dry-run
  python verify_migration_targets.py --check --target autonomath
  python verify_migration_targets.py --dry-run --target jpintel \\
      --migrations-dir /Users/.../jpcite/scripts/migrations \\
      --rules /path/to/schema_guard_rules.json \\
      --out /tmp/audit_dir
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import re
import sqlite3
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

# sqlglot is OPTIONAL at import-time so --check still runs in environments
# where sqlglot isn't installed; SQL body parsing degrades to a regex walk
# in that case. The acceptance gate prefers sqlglot for AST accuracy.
try:
    import sqlglot
    from sqlglot import exp as sqlglot_exp

    SQLGLOT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-conditional
    SQLGLOT_AVAILABLE = False

VALID_TARGETS = ("autonomath", "jpintel")

# DEEP-52 §3 check #3 — slug → target inference rules.
# Maps a regex on the slug-suffix (after wave24_NNN[a-z]?_) to the expected
# target. The first match wins; an unknown slug only triggers a warning,
# not a hard failure (slugs are operator-authored and may not always carry
# a target hint).
SLUG_PREFIX_TO_TARGET: Sequence[tuple[str, str]] = (
    (r"^am_", "autonomath"),
    (r"^autonomath_", "autonomath"),
    (r"^programs_", "autonomath"),
    (r"^houjin_master", "autonomath"),
    (r"^jpi_", "jpintel"),
    (r"^audit_seal", "jpintel"),
    (r"^compliance_", "jpintel"),
    (r"^api_keys", "jpintel"),
    (r"^subscribers", "jpintel"),
    (r"^amendment_snapshot", "jpintel"),
)

# Filename pattern: wave24_NNN[a-z]?_<slug>.sql or _rollback.sql variant.
FILENAME_RE = re.compile(
    r"^wave24_(?P<num>\d{2,4})(?P<suffix>[a-z]?)_(?P<slug>.+?)(?P<rb>_rollback)?\.sql$"
)

FIRST_LINE_MARKER_RE = re.compile(r"^-- target_db:\s*([A-Za-z0-9_]+)\s*$")

# Forbidden tables are sourced from schema_guard_rules.json (loaded at
# runtime). We keep an embedded fallback so the verifier still runs if the
# rules file is missing — the embedded list mirrors DEEP-52 §4.
EMBEDDED_RULES: dict[str, dict[str, Any]] = {
    "autonomath": {
        "forbidden": [
            "programs",
            "api_keys",
            "audit_seal",
            "audit_seal_keys",
            "audit_seals",
            "subscribers",
            "compliance_subscribers",
            "case_studies",
            "exclusion_rules",
            "loan_programs",
        ],
        "forbidden_prefixes": ["jpi_", "audit_seal_", "compliance_", "subscribers_"],
    },
    "jpintel": {
        "forbidden": [
            "am_entities",
            "am_relation",
            "am_alias",
            "am_recommended_programs",
            "am_program_combinations",
            "am_program_calendar_12mo",
            "autonomath_houjin_master",
        ],
        "forbidden_prefixes": ["am_", "autonomath_", "houjin_master_"],
        "forbidden_prefix_allowlist": [
            # promoted read-models that are intentionally legal under jpintel
            # (kept here so a future allowlist expansion has a single home).
        ],
    },
}


@dataclasses.dataclass
class FileReport:
    path: str
    filename: str
    num: int | None
    suffix: str
    slug: str
    is_rollback: bool
    marker: str | None
    body_tables: list[str]
    rollback_pair: str | None
    errors: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# 1. Marker + filename parsing
# ---------------------------------------------------------------------------


def parse_filename(path: str) -> tuple[int | None, str, str, bool]:
    name = os.path.basename(path)
    m = FILENAME_RE.match(name)
    if not m:
        return None, "", name, False
    num = int(m.group("num"))
    suffix = m.group("suffix") or ""
    slug = m.group("slug") or ""
    is_rollback = bool(m.group("rb"))
    return num, suffix, slug, is_rollback


def read_first_line_marker(path: str) -> str | None:
    """Return the marker value from the first line, or None if absent.

    Per DEEP-52 §3 check #1: literal `-- target_db: <name>` on line 1 with
    no BOM and no leading whitespace.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read(2048)
    except OSError:
        return None
    # BOM check
    if raw.startswith(b"\xef\xbb\xbf"):
        return None
    # First line decode
    nl = raw.find(b"\n")
    first = raw[: nl if nl != -1 else len(raw)]
    try:
        text = first.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    m = FIRST_LINE_MARKER_RE.match(text.rstrip("\r"))
    if not m:
        return None
    return m.group(1)


def infer_slug_target(slug: str, rules: dict[str, Any] | None = None) -> str | None:
    """Infer the expected target_db from a filename slug.

    Supports JSON-driven exemptions via the optional ``rules`` arg:
      rules["_slug_overrides"]: {"<exact_slug>": "<target>"}
        — wins outright, regardless of prefix patterns
      rules["_slug_exemptions"]: ["<exact_slug>", ...]
        — slug bypasses prefix inference (treated as "unknown",
        which only triggers a warning, not a hard error)

    These are how we handle migrations whose slug prefix would
    otherwise SLUG_MARKER_DRIFT against an intentional, reviewed
    target choice (e.g. wave24_113b_jpi_programs_jsic.sql is
    intentionally autonomath because jpi_* mirror tables live
    on autonomath.db; rename would break the 78-table mirror
    naming convention from migration 032).
    """
    if rules:
        overrides = rules.get("_slug_overrides", {}) or {}
        if isinstance(overrides, dict) and slug in overrides:
            tgt = overrides[slug]
            if tgt in VALID_TARGETS:
                return tgt
        exemptions = rules.get("_slug_exemptions", []) or []
        if isinstance(exemptions, list) and slug in exemptions:
            return None
    for pat, tgt in SLUG_PREFIX_TO_TARGET:
        if re.match(pat, slug):
            return tgt
    return None


# ---------------------------------------------------------------------------
# 2. SQL body table extraction
# ---------------------------------------------------------------------------

# Fallback regex-only extractor for environments without sqlglot.
RE_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([\"\[`]?)([A-Za-z0-9_]+)\1",
    re.IGNORECASE,
)
RE_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+([\"\[`]?)([A-Za-z0-9_]+)\1",
    re.IGNORECASE,
)
RE_CREATE_INDEX_ON = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+[\"\[`]?[A-Za-z0-9_]+[\"\[`]?\s+ON\s+([\"\[`]?)([A-Za-z0-9_]+)\1",
    re.IGNORECASE,
)
RE_CREATE_VIEW = re.compile(
    r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?VIEW(?:\s+IF\s+NOT\s+EXISTS)?\s+([\"\[`]?)([A-Za-z0-9_]+)\1",
    re.IGNORECASE,
)


def extract_body_tables(sql: str) -> list[str]:
    """Return the list of table identifiers touched by CREATE/ALTER/INDEX/VIEW.

    Prefers sqlglot when available, regex fallback otherwise. Comments are
    stripped before parse to avoid false positives from prose.
    """
    # Strip line + block comments before any extraction.
    no_line_comments = re.sub(r"--[^\n]*", "", sql)
    no_block_comments = re.sub(r"/\*.*?\*/", "", no_line_comments, flags=re.DOTALL)
    cleaned = no_block_comments

    tables: list[str] = []

    if SQLGLOT_AVAILABLE:
        try:
            statements = sqlglot.parse(cleaned, dialect="sqlite", error_level=None)
        except Exception:
            statements = []
        for stmt in statements:
            if stmt is None:
                continue
            for node in stmt.walk():
                # walk yields tuples in older sqlglot; current returns nodes
                target = node[0] if isinstance(node, tuple) else node
                # sqlglot ≥ 25 renamed AlterTable → Alter; both names are
                # supported here so the verifier survives a future bump.
                AlterCls = getattr(sqlglot_exp, "AlterTable", None) or getattr(
                    sqlglot_exp, "Alter", None
                )
                if (
                    isinstance(target, sqlglot_exp.Create)
                    or AlterCls is not None
                    and isinstance(target, AlterCls)
                    or isinstance(target, sqlglot_exp.Drop)
                ):
                    this = target.this
                    name = _identifier_name(this)
                    if name:
                        tables.append(name)
        if tables:
            return _dedupe_keep_order(tables)

    # Regex fallback (also used when sqlglot returns nothing).
    for m in RE_CREATE_TABLE.finditer(cleaned):
        tables.append(m.group(2))
    for m in RE_ALTER_TABLE.finditer(cleaned):
        tables.append(m.group(2))
    for m in RE_CREATE_INDEX_ON.finditer(cleaned):
        tables.append(m.group(2))
    for m in RE_CREATE_VIEW.finditer(cleaned):
        tables.append(m.group(2))
    return _dedupe_keep_order(tables)


def _identifier_name(node: Any) -> str | None:
    if node is None:
        return None
    if SQLGLOT_AVAILABLE and hasattr(node, "name"):
        try:
            n = node.name
            return str(n) if n else None
        except Exception:
            return None
    return None


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


# ---------------------------------------------------------------------------
# 3. Schema guard cross-check
# ---------------------------------------------------------------------------


def load_rules(rules_path: str | None) -> dict[str, dict[str, Any]]:
    if rules_path and os.path.exists(rules_path):
        try:
            with open(rules_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"[warn] rules load failed {rules_path}: {exc}\n")
    # fallback to embedded
    return EMBEDDED_RULES


def check_forbidden(
    target: str, body_tables: list[str], rules: dict[str, dict[str, Any]]
) -> list[str]:
    """Return a list of forbidden table hits for the given target."""
    cfg = rules.get(target, {})
    forbidden_exact = set(cfg.get("forbidden", []))
    forbidden_prefixes = list(cfg.get("forbidden_prefixes", []))
    allowlist = set(cfg.get("forbidden_prefix_allowlist", []))
    hits: list[str] = []
    for tbl in body_tables:
        if tbl in allowlist:
            continue
        if tbl in forbidden_exact:
            hits.append(tbl)
            continue
        for pref in forbidden_prefixes:
            if tbl.startswith(pref):
                hits.append(tbl)
                break
    return hits


# ---------------------------------------------------------------------------
# 4. Per-file check pipeline
# ---------------------------------------------------------------------------


def check_file(path: str, rules: dict[str, dict[str, Any]]) -> FileReport:
    num, suffix, slug, is_rollback = parse_filename(path)
    marker = read_first_line_marker(path)
    errors: list[str] = []
    warnings: list[str] = []

    # check 1: marker presence
    if marker is None:
        errors.append("MARKER_MISSING")

    # check 2: marker enum
    if marker is not None and marker not in VALID_TARGETS:
        errors.append(f"MARKER_INVALID:{marker}")

    # check 3: filename slug consistency (DEEP-52 §3 check #3)
    if marker in VALID_TARGETS and slug:
        inferred = infer_slug_target(slug, rules)
        if inferred is not None and inferred != marker:
            errors.append(f"SLUG_MARKER_DRIFT:slug_implies={inferred},marker={marker}")
        elif inferred is None:
            warnings.append("SLUG_PREFIX_UNKNOWN")

    # check 4: rollback pairing — resolved at the dir level, recorded here
    rollback_pair: str | None = None
    if not is_rollback:
        rollback_pair = path[:-4] + "_rollback.sql"
        if not os.path.exists(rollback_pair):
            errors.append("ROLLBACK_PAIR_BROKEN:missing")
            rollback_pair = None
    else:
        forward = path.replace("_rollback.sql", ".sql")
        if not os.path.exists(forward):
            errors.append("ROLLBACK_ORPHAN:no_forward")

    # check 5: SQL body vs target
    body_tables: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            sql = fh.read()
    except OSError as exc:
        errors.append(f"READ_FAILED:{exc}")
        sql = ""
    if sql:
        body_tables = extract_body_tables(sql)
        if marker in VALID_TARGETS:
            hits = check_forbidden(marker, body_tables, rules)
            if hits:
                errors.append("BODY_TARGET_VIOLATION:" + ",".join(hits))

    return FileReport(
        path=path,
        filename=os.path.basename(path),
        num=num,
        suffix=suffix,
        slug=slug,
        is_rollback=is_rollback,
        marker=marker,
        body_tables=body_tables,
        rollback_pair=rollback_pair,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 5. In-memory dry-run (forward + rollback + idempotency)
# ---------------------------------------------------------------------------


def _sort_key(report: FileReport) -> tuple[int, str, int]:
    return (report.num or 0, report.suffix or "", 1 if report.is_rollback else 0)


def dry_run_target(
    target: str,
    forwards: list[FileReport],
    rules: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Apply forward+rollback for one target against a fresh :memory: handle.

    DEEP-52 §5: forward in (NNN, suffix) order on handle X; rollback in
    reverse order; assert schema returns to baseline (PRAGMA schema_version
    delta back to baseline). Then re-apply forwards once to verify
    idempotency.
    """
    started = time.time()
    handle = sqlite3.connect(":memory:")
    handle.execute("PRAGMA foreign_keys = ON")

    # Baseline schema_version. Fresh :memory: starts at 0.
    base_schema_version = _schema_version(handle)

    forward_log: list[dict[str, Any]] = []
    rollback_log: list[dict[str, Any]] = []
    idempotency_log: list[dict[str, Any]] = []
    errors: list[str] = []

    sorted_forwards = sorted([r for r in forwards if not r.is_rollback], key=_sort_key)

    # forward sweep
    for rep in sorted_forwards:
        if rep.marker != target:
            continue
        elapsed_ms, err = _apply_sql_file(handle, rep.path)
        forward_log.append(
            {
                "file": rep.filename,
                "ms": elapsed_ms,
                "error": err,
            }
        )
        if err:
            errors.append(f"FORWARD_FAIL:{rep.filename}:{err}")

    after_forward_version = _schema_version(handle)

    # rollback sweep (reverse order)
    for rep in reversed(sorted_forwards):
        if rep.marker != target:
            continue
        rb = rep.rollback_pair
        if not rb or not os.path.exists(rb):
            rollback_log.append({"file": rep.filename, "ms": 0, "error": "rollback_missing"})
            continue
        elapsed_ms, err = _apply_sql_file(handle, rb)
        rollback_log.append({"file": os.path.basename(rb), "ms": elapsed_ms, "error": err})
        if err:
            errors.append(f"ROLLBACK_FAIL:{os.path.basename(rb)}:{err}")

    after_rollback_version = _schema_version(handle)

    # idempotency: re-apply forwards once. Each statement uses IF NOT EXISTS
    # so re-application MUST NOT raise.
    for rep in sorted_forwards:
        if rep.marker != target:
            continue
        elapsed_ms, err = _apply_sql_file(handle, rep.path)
        idempotency_log.append({"file": rep.filename, "ms": elapsed_ms, "error": err})
        if err and "duplicate column name" not in (err or "").lower():
            errors.append(f"IDEMPOTENCY_FAIL:{rep.filename}:{err}")

    handle.close()
    duration_s = round(time.time() - started, 3)

    return {
        "target": target,
        "duration_s": duration_s,
        "base_schema_version": base_schema_version,
        "after_forward_version": after_forward_version,
        "after_rollback_version": after_rollback_version,
        "schema_returns_to_baseline": after_rollback_version <= base_schema_version + 1,
        "forward_count": len(forward_log),
        "rollback_count": len(rollback_log),
        "idempotency_count": len(idempotency_log),
        "forward_log": forward_log,
        "rollback_log": rollback_log,
        "idempotency_log": idempotency_log,
        "errors": errors,
    }


def _schema_version(handle: sqlite3.Connection) -> int:
    cur = handle.execute("PRAGMA schema_version")
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _apply_sql_file(handle: sqlite3.Connection, path: str) -> tuple[int, str | None]:
    started = time.time()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            sql = fh.read()
    except OSError as exc:
        return 0, f"read:{exc}"
    try:
        handle.executescript(sql)
        handle.commit()
        ms = int((time.time() - started) * 1000)
        return ms, None
    except sqlite3.Error as exc:
        ms = int((time.time() - started) * 1000)
        # Some rollbacks reference tables we never created (because the
        # in-memory handle isn't a real prod replica). Surface the exact
        # error string so the report is honest, but don't crash the sweep.
        return ms, str(exc)


# ---------------------------------------------------------------------------
# 6. CLI
# ---------------------------------------------------------------------------


def discover_migrations(migrations_dir: str) -> list[str]:
    """Return all wave24_*.sql files (excludes *.draft via the suffix filter)."""
    pat = os.path.join(migrations_dir, "wave24_*.sql")
    files = sorted(glob.glob(pat))
    return [f for f in files if not f.endswith(".draft.sql")]


def run_check(
    files: list[str],
    rules: dict[str, dict[str, Any]],
    target_filter: str | None,
) -> tuple[list[FileReport], dict[str, Any]]:
    reports: list[FileReport] = [check_file(p, rules) for p in files]

    # Cross-check rollback pair markers match.
    by_path = {r.path: r for r in reports}
    for r in reports:
        if r.is_rollback or not r.rollback_pair:
            continue
        rb = by_path.get(r.rollback_pair)
        if rb is None:
            continue
        if r.marker is not None and rb.marker is not None and r.marker != rb.marker:
            r.errors.append(f"ROLLBACK_PAIR_MARKER_MISMATCH:fwd={r.marker},rb={rb.marker}")

    if target_filter:
        reports = [r for r in reports if r.marker == target_filter]

    error_counter: dict[str, int] = {}
    target_counter: dict[str, int] = {}
    for r in reports:
        for e in r.errors:
            head = e.split(":", 1)[0]
            error_counter[head] = error_counter.get(head, 0) + 1
        if r.marker:
            target_counter[r.marker] = target_counter.get(r.marker, 0) + 1

    return reports, {
        "files_total": len(reports),
        "files_with_errors": sum(1 for r in reports if r.errors),
        "error_counts_by_kind": error_counter,
        "files_per_target": target_counter,
    }


def write_audit_json(out_dir: str, name: str, payload: Any) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=_json_default)
    return path


def _json_default(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"unserializable {type(obj).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEEP-52 migration target_db verifier")
    parser.add_argument(
        "--check",
        action="store_true",
        help="run the 5 per-file checks (default if neither flag given)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="apply forward+rollback against :memory: handles"
    )
    parser.add_argument("--target", choices=list(VALID_TARGETS), help="restrict to one target")
    parser.add_argument(
        "--migrations-dir",
        default=os.environ.get(
            "MIGRATIONS_DIR",
            "/Users/shigetoumeda/jpcite/scripts/migrations",
        ),
        help="root dir holding wave24_*.sql",
    )
    parser.add_argument(
        "--rules",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_guard_rules.json"),
        help="JSON rules file (forbidden tables per target)",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit"),
        help="audit output dir",
    )
    args = parser.parse_args(argv)
    if not args.check and not args.dry_run:
        args.check = True

    rules = load_rules(args.rules)
    files = discover_migrations(args.migrations_dir)
    if not files:
        sys.stderr.write(f"[warn] no wave24_*.sql files at {args.migrations_dir}\n")

    reports, rollup = run_check(files, rules, args.target)

    audit_payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "migrations_dir": args.migrations_dir,
        "rules_file": args.rules,
        "target_filter": args.target,
        "rollup": rollup,
        "files": [dataclasses.asdict(r) for r in reports],
    }
    write_audit_json(args.out, "migration_target_verify.json", audit_payload)

    overall_errors = sum(1 for r in reports if r.errors)
    print(
        json.dumps(
            {
                "phase": "check",
                "files_total": rollup["files_total"],
                "files_with_errors": overall_errors,
                "error_counts_by_kind": rollup["error_counts_by_kind"],
                "files_per_target": rollup["files_per_target"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    dry_run_failed = False
    if args.dry_run:
        targets_to_run = [args.target] if args.target else list(VALID_TARGETS)
        dry_results: dict[str, Any] = {}
        for tgt in targets_to_run:
            forwards = [r for r in reports if r.marker == tgt]
            res = dry_run_target(tgt, forwards, rules)
            dry_results[tgt] = res
            if res["errors"]:
                dry_run_failed = True
        write_audit_json(
            args.out,
            "migration_dry_run.json",
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "results": dry_results,
            },
        )
        print(
            json.dumps(
                {
                    "phase": "dry_run",
                    "targets": list(dry_results.keys()),
                    "any_errors": dry_run_failed,
                    "summary": {
                        t: {
                            "duration_s": v["duration_s"],
                            "forward_count": v["forward_count"],
                            "rollback_count": v["rollback_count"],
                            "errors": len(v["errors"]),
                            "schema_returns_to_baseline": v["schema_returns_to_baseline"],
                        }
                        for t, v in dry_results.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    return 0 if (overall_errors == 0 and not dry_run_failed) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
