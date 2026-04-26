#!/usr/bin/env python3
"""Encode tax_rulesets (migration 018) rows from a curated seed JSON file.

Reads scripts/ingest/tax_rulesets_seed.json and UPSERTs each entry into
`tax_rulesets` + `tax_rulesets_fts`. Predicates in
`eligibility_conditions_json` follow the schema consumed by
`src/jpintel_mcp/api/tax_rulesets.py::_eval_predicate`:

    Leaf predicates:
      {"op": "eq",  "field": X, "value": Y}
      {"op": "gte", "field": X, "value": N}     (numeric)
      {"op": "lte", "field": X, "value": N}     (numeric)
      {"op": "in",  "field": X, "values": [..]}
      {"op": "has_invoice_registration"}
    Compound predicates:
      {"op": "all", "of": [p1, p2, ...]}
      {"op": "any", "of": [p1, p2, ...]}
      {"op": "not", "of": predicate}

Unified id is SHA-256 of (tax_category + ruleset_kind + canonical_name)
truncated to 10 hex chars, prefixed `TAX-` — matches migration 018's
14-character pattern. Re-encoding the same (category, kind, name) yields
the same id across runs (idempotent UPSERT target).

Lineage:
  - source_url is whitelisted to www.nta.go.jp / www.mof.go.jp /
    elaws.e-gov.go.jp; aggregators (noukaweb, hojyokin-portal, biz.stayway,
    subsidymap, navit-j) are rejected at validation time.
  - fetched_at is set to UTC now at encode time (we do NOT re-fetch; the
    seed author is responsible for the original fetch).

Cliff-date policy: any effective_end_date that isn't one of the four
published cliffs (2026-09-30, 2027-09-30, 2029-09-30, 2025-12-31) is
rejected. Rows with `needs_verification: true` in the seed are written
but carry confidence <= 0.6 and a flag in eligibility_conditions.

Usage:
    python scripts/ingest/encode_tax_rulesets.py --db data/jpintel.db
    python scripts/ingest/encode_tax_rulesets.py --dry-run
    python scripts/ingest/encode_tax_rulesets.py --seed /path/to/seed.json

Exit codes:
    0  success
    1  unrecoverable IO / DB error
    2  schema validation failure (predicate / seed row rejected)
    3  output quality gate: 0 rows encoded on a non-empty seed
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_LOG = logging.getLogger("jpintel.encode_tax_rulesets")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_SEED = REPO_ROOT / "scripts" / "ingest" / "tax_rulesets_seed.json"
DEFAULT_PREVIEW = Path("/tmp/autonomath_tax_rulesets_preview.jsonl")

# Source URL whitelist — mirrors migration 018 header.
ALLOWED_SOURCE_HOSTS: frozenset[str] = frozenset(
    {
        "www.nta.go.jp",
        "www.mof.go.jp",
        "elaws.e-gov.go.jp",
        "laws.e-gov.go.jp",
    }
)

# Aggregator domains banned repo-wide (CLAUDE.md data hygiene).
BANNED_HOSTS: frozenset[str] = frozenset(
    {
        "noukaweb.com",
        "hojyokin-portal.jp",
        "biz.stayway.jp",
        "subsidymap.jp",
        "navit-j.com",
    }
)

# Published cliff dates — any other effective_end_date is rejected.
ALLOWED_CLIFF_DATES: frozenset[str] = frozenset(
    {"2026-09-30", "2027-09-30", "2029-09-30", "2025-12-31"}
)

TAX_CATEGORIES: frozenset[str] = frozenset(
    {"consumption", "corporate", "income", "property", "local", "inheritance"}
)
RULESET_KINDS: frozenset[str] = frozenset(
    {
        "registration",
        "credit",
        "deduction",
        "special_depreciation",
        "exemption",
        "preservation",
        "other",
    }
)

# Supported predicate ops (matches tax_rulesets.py::_eval_predicate exactly).
LEAF_OPS: frozenset[str] = frozenset({"eq", "gte", "lte", "in", "has_invoice_registration"})
COMPOUND_OPS: frozenset[str] = frozenset({"all", "any", "not"})
ALL_OPS: frozenset[str] = LEAF_OPS | COMPOUND_OPS

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EncodedRow:
    """Row ready for UPSERT into tax_rulesets."""

    unified_id: str
    ruleset_name: str
    tax_category: str
    ruleset_kind: str
    effective_from: str
    effective_until: str | None
    related_law_ids_json: str | None
    eligibility_conditions: str
    eligibility_conditions_json: str
    rate_or_amount: str | None
    calculation_formula: str | None
    filing_requirements: str | None
    authority: str
    authority_url: str | None
    source_url: str
    source_excerpt: str | None
    source_checksum: str | None
    confidence: float
    fetched_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Unified id
# ---------------------------------------------------------------------------


def mint_unified_id(tax_category: str, ruleset_kind: str, canonical_name: str) -> str:
    """TAX- + sha256(tax_category|ruleset_kind|canonical_name)[:10].

    Deterministic: same triple always yields the same 14-char id. Used as
    the UPSERT key — superseded rulesets keep their own ids.
    """
    blob = f"{tax_category}|{ruleset_kind}|{canonical_name}".encode()
    digest = hashlib.sha256(blob).hexdigest()[:10]
    return f"TAX-{digest}"


# ---------------------------------------------------------------------------
# Predicate validation (matches tax_rulesets.py::_eval_predicate)
# ---------------------------------------------------------------------------


def _validate_predicate(pred: Any, path: str = "$") -> list[str]:
    """Walk a predicate tree; return list of error strings (empty = OK)."""
    errs: list[str] = []
    if not isinstance(pred, dict):
        return [f"{path}: predicate must be dict, got {type(pred).__name__}"]
    op = pred.get("op")
    if not isinstance(op, str):
        return [f"{path}: predicate missing string 'op'"]
    if op not in ALL_OPS:
        return [f"{path}: unknown op {op!r} (allowed: {sorted(ALL_OPS)})"]

    if op == "eq":
        if not isinstance(pred.get("field"), str):
            errs.append(f"{path}: 'eq' requires string 'field'")
        if "value" not in pred:
            errs.append(f"{path}: 'eq' requires 'value'")
    elif op in ("gte", "lte"):
        if not isinstance(pred.get("field"), str):
            errs.append(f"{path}: {op!r} requires string 'field'")
        v = pred.get("value")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errs.append(f"{path}: {op!r} requires numeric 'value', got {type(v).__name__}")
    elif op == "in":
        if not isinstance(pred.get("field"), str):
            errs.append(f"{path}: 'in' requires string 'field'")
        if not isinstance(pred.get("values"), list):
            errs.append(f"{path}: 'in' requires list 'values'")
    elif op == "has_invoice_registration":
        # No required fields.
        pass
    elif op in ("all", "any"):
        children = pred.get("of")
        if not isinstance(children, list):
            errs.append(f"{path}: {op!r} requires list 'of'")
        else:
            for i, child in enumerate(children):
                errs.extend(_validate_predicate(child, f"{path}.of[{i}]"))
    elif op == "not":
        child = pred.get("of")
        if child is None:
            errs.append(f"{path}: 'not' requires 'of'")
        else:
            errs.extend(_validate_predicate(child, f"{path}.of"))
    return errs


# ---------------------------------------------------------------------------
# Numeric date sanity — catch 2-digit typos ('202-10-01') without calendar parse
# ---------------------------------------------------------------------------


def _is_iso_date(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    if not _ISO_DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# Seed loading & validation
# ---------------------------------------------------------------------------


def load_seed(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"seed file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"seed must be a JSON array, got {type(data).__name__}")
    return data


def validate_seed_entry(entry: dict[str, Any], idx: int) -> list[str]:
    """Return list of error strings for a single seed row (empty = OK)."""
    errs: list[str] = []
    prefix = f"seed[{idx}]"

    name = entry.get("canonical_name")
    if not isinstance(name, str) or not name.strip():
        errs.append(f"{prefix}: canonical_name missing / empty")

    tax_category = entry.get("tax_category")
    if tax_category not in TAX_CATEGORIES:
        errs.append(
            f"{prefix}: tax_category {tax_category!r} not in {sorted(TAX_CATEGORIES)}"
        )

    ruleset_kind = entry.get("ruleset_kind")
    if ruleset_kind not in RULESET_KINDS:
        errs.append(
            f"{prefix}: ruleset_kind {ruleset_kind!r} not in {sorted(RULESET_KINDS)}"
        )

    start = entry.get("effective_start_date")
    if not _is_iso_date(start):
        errs.append(f"{prefix}: effective_start_date {start!r} is not ISO YYYY-MM-DD")

    end = entry.get("effective_end_date")
    if end is not None:
        if not _is_iso_date(end):
            errs.append(f"{prefix}: effective_end_date {end!r} is not ISO YYYY-MM-DD")
        elif end not in ALLOWED_CLIFF_DATES:
            errs.append(
                f"{prefix}: effective_end_date {end!r} is not a published cliff "
                f"(allowed: {sorted(ALLOWED_CLIFF_DATES)})"
            )

    source_url = entry.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        errs.append(f"{prefix}: source_url missing")
    else:
        host = _host(source_url)
        if host in BANNED_HOSTS:
            errs.append(f"{prefix}: source_url host {host!r} is banned (aggregator)")
        elif host not in ALLOWED_SOURCE_HOSTS:
            errs.append(
                f"{prefix}: source_url host {host!r} not in whitelist "
                f"{sorted(ALLOWED_SOURCE_HOSTS)}"
            )

    legal_basis = entry.get("legal_basis")
    if legal_basis is not None and not isinstance(legal_basis, list):
        errs.append(f"{prefix}: legal_basis must be list[str] or null")
    elif isinstance(legal_basis, list):
        for j, item in enumerate(legal_basis):
            if not isinstance(item, str):
                errs.append(f"{prefix}: legal_basis[{j}] must be str")

    confidence = entry.get("confidence", 0.92)
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        errs.append(f"{prefix}: confidence must be 0..1, got {confidence!r}")

    cond_json = entry.get("eligibility_conditions_json")
    if cond_json is None:
        # Allowed — rows with no predicates are evaluated as trivially True.
        pass
    elif isinstance(cond_json, (dict, list)):
        if isinstance(cond_json, list):
            # List is implicit AND; validate each element as predicate.
            for j, child in enumerate(cond_json):
                errs.extend(
                    _validate_predicate(child, f"{prefix}.eligibility_conditions_json[{j}]")
                )
        else:
            errs.extend(
                _validate_predicate(cond_json, f"{prefix}.eligibility_conditions_json")
            )
    else:
        errs.append(
            f"{prefix}: eligibility_conditions_json must be dict / list / null, "
            f"got {type(cond_json).__name__}"
        )

    return errs


# ---------------------------------------------------------------------------
# Encode seed -> EncodedRow
# ---------------------------------------------------------------------------


def _now_iso_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def encode_entry(entry: dict[str, Any], now_iso: str) -> EncodedRow:
    """Convert a validated seed entry into an EncodedRow."""
    canonical_name = str(entry["canonical_name"]).strip()
    tax_category = str(entry["tax_category"])
    ruleset_kind = str(entry["ruleset_kind"])

    uid_override = entry.get("unified_id")
    uid = (
        uid_override
        if isinstance(uid_override, str) and uid_override.startswith("TAX-")
        else mint_unified_id(tax_category, ruleset_kind, canonical_name)
    )

    # Narrative: summary + description + optional verification flag.
    narrative_parts: list[str] = []
    summary = entry.get("summary")
    description = entry.get("description")
    if isinstance(summary, str) and summary.strip():
        narrative_parts.append(summary.strip())
    if isinstance(description, str) and description.strip():
        narrative_parts.append(description.strip())
    if entry.get("needs_verification") is True:
        narrative_parts.append(
            "[needs_verification: true] — encoded from secondary reading; "
            "re-verify against the cited primary source before relying on."
        )
    narrative = "\n\n".join(narrative_parts) if narrative_parts else canonical_name

    # legal_basis -> narrative law refs. We don't resolve to LAW-* ids here
    # (that requires migration 015's `laws` table at ingest time); we stash
    # the raw names so the related_law_ids_json column stays parseable.
    legal_basis = entry.get("legal_basis")
    related_law_ids_json: str | None = None
    if isinstance(legal_basis, list) and legal_basis:
        # Store as PENDING:<name> entries matching the ingest_laws / 015 convention.
        pending_refs = [f"PENDING:{name}" for name in legal_basis]
        related_law_ids_json = json.dumps(pending_refs, ensure_ascii=False)

    # Predicate tree — normalize list -> {all, of:[...]} for the evaluator.
    cond_json_raw = entry.get("eligibility_conditions_json")
    if cond_json_raw is None:
        eligibility_conditions_json = "{}"
    elif isinstance(cond_json_raw, list):
        eligibility_conditions_json = json.dumps(
            {"op": "all", "of": cond_json_raw}, ensure_ascii=False
        )
    else:
        eligibility_conditions_json = json.dumps(cond_json_raw, ensure_ascii=False)

    # Needs_verification downgrades confidence to ≤ 0.6 (audit signal).
    confidence = float(entry.get("confidence", 0.92))
    if entry.get("needs_verification") is True:
        confidence = min(confidence, 0.6)

    return EncodedRow(
        unified_id=uid,
        ruleset_name=canonical_name,
        tax_category=tax_category,
        ruleset_kind=ruleset_kind,
        effective_from=str(entry["effective_start_date"]),
        effective_until=entry.get("effective_end_date"),
        related_law_ids_json=related_law_ids_json,
        eligibility_conditions=narrative,
        eligibility_conditions_json=eligibility_conditions_json,
        rate_or_amount=entry.get("rate_or_amount"),
        calculation_formula=entry.get("calculation_formula"),
        filing_requirements=entry.get("filing_requirements"),
        authority=str(entry.get("authority", "国税庁")),
        authority_url=entry.get("authority_url") or "https://www.nta.go.jp/",
        source_url=str(entry["source_url"]),
        source_excerpt=entry.get("source_excerpt"),
        source_checksum=entry.get("source_checksum"),
        confidence=confidence,
        fetched_at=now_iso,
        updated_at=now_iso,
    )


# ---------------------------------------------------------------------------
# DB UPSERT
# ---------------------------------------------------------------------------


UPSERT_SQL = """
INSERT INTO tax_rulesets (
    unified_id, ruleset_name, tax_category, ruleset_kind,
    effective_from, effective_until, related_law_ids_json,
    eligibility_conditions, eligibility_conditions_json,
    rate_or_amount, calculation_formula, filing_requirements,
    authority, authority_url, source_url, source_excerpt, source_checksum,
    confidence, fetched_at, updated_at
) VALUES (
    :unified_id, :ruleset_name, :tax_category, :ruleset_kind,
    :effective_from, :effective_until, :related_law_ids_json,
    :eligibility_conditions, :eligibility_conditions_json,
    :rate_or_amount, :calculation_formula, :filing_requirements,
    :authority, :authority_url, :source_url, :source_excerpt, :source_checksum,
    :confidence, :fetched_at, :updated_at
)
ON CONFLICT(unified_id) DO UPDATE SET
    ruleset_name = excluded.ruleset_name,
    tax_category = excluded.tax_category,
    ruleset_kind = excluded.ruleset_kind,
    effective_from = excluded.effective_from,
    effective_until = excluded.effective_until,
    related_law_ids_json = excluded.related_law_ids_json,
    eligibility_conditions = excluded.eligibility_conditions,
    eligibility_conditions_json = excluded.eligibility_conditions_json,
    rate_or_amount = excluded.rate_or_amount,
    calculation_formula = excluded.calculation_formula,
    filing_requirements = excluded.filing_requirements,
    authority = excluded.authority,
    authority_url = excluded.authority_url,
    source_url = excluded.source_url,
    source_excerpt = excluded.source_excerpt,
    source_checksum = excluded.source_checksum,
    confidence = excluded.confidence,
    fetched_at = excluded.fetched_at,
    updated_at = excluded.updated_at
"""


def upsert_row(conn: sqlite3.Connection, row: EncodedRow) -> str:
    """INSERT OR UPDATE one row + sync tax_rulesets_fts. Returns 'insert'|'update'."""
    existed = (
        conn.execute(
            "SELECT 1 FROM tax_rulesets WHERE unified_id = ?", (row.unified_id,)
        ).fetchone()
        is not None
    )
    conn.execute(
        UPSERT_SQL,
        {
            "unified_id": row.unified_id,
            "ruleset_name": row.ruleset_name,
            "tax_category": row.tax_category,
            "ruleset_kind": row.ruleset_kind,
            "effective_from": row.effective_from,
            "effective_until": row.effective_until,
            "related_law_ids_json": row.related_law_ids_json,
            "eligibility_conditions": row.eligibility_conditions,
            "eligibility_conditions_json": row.eligibility_conditions_json,
            "rate_or_amount": row.rate_or_amount,
            "calculation_formula": row.calculation_formula,
            "filing_requirements": row.filing_requirements,
            "authority": row.authority,
            "authority_url": row.authority_url,
            "source_url": row.source_url,
            "source_excerpt": row.source_excerpt,
            "source_checksum": row.source_checksum,
            "confidence": row.confidence,
            "fetched_at": row.fetched_at,
            "updated_at": row.updated_at,
        },
    )
    # FTS mirror — delete-then-insert (fts5 virtual tables don't UPSERT).
    conn.execute(
        "DELETE FROM tax_rulesets_fts WHERE unified_id = ?", (row.unified_id,)
    )
    conn.execute(
        "INSERT INTO tax_rulesets_fts "
        "(unified_id, ruleset_name, eligibility_conditions, calculation_formula) "
        "VALUES (?, ?, ?, ?)",
        (
            row.unified_id,
            row.ruleset_name,
            row.eligibility_conditions,
            row.calculation_formula or "",
        ),
    )
    return "update" if existed else "insert"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    root = logging.getLogger("jpintel.encode_tax_rulesets")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--db", default=str(DEFAULT_DB), help=f"SQLite DB path (default {DEFAULT_DB})"
    )
    ap.add_argument(
        "--seed",
        type=Path,
        default=DEFAULT_SEED,
        help=f"Seed JSON array (default {DEFAULT_SEED})",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            f"Do not write to DB; emit encoded rows to {DEFAULT_PREVIEW}."
        ),
    )
    ap.add_argument(
        "--preview-out",
        type=Path,
        default=DEFAULT_PREVIEW,
        help=f"Preview JSONL path for --dry-run (default {DEFAULT_PREVIEW})",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    _configure_logging(args.verbose)

    # -------- 1) Load & validate seed --------
    try:
        seed = load_seed(args.seed)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        _LOG.error("failed to load seed %s: %s", args.seed, exc)
        return 1

    _LOG.info("loaded %d seed entries from %s", len(seed), args.seed)

    validation_errors: list[str] = []
    for idx, entry in enumerate(seed):
        if not isinstance(entry, dict):
            validation_errors.append(
                f"seed[{idx}]: entry is {type(entry).__name__}, expected dict"
            )
            continue
        validation_errors.extend(validate_seed_entry(entry, idx))

    if validation_errors:
        for err in validation_errors:
            _LOG.error(err)
        _LOG.error("seed validation failed: %d errors", len(validation_errors))
        return 2

    # -------- 2) Encode --------
    now_iso = _now_iso_utc()
    rows: list[EncodedRow] = [encode_entry(entry, now_iso) for entry in seed]
    # Duplicate unified_id detection.
    seen: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r.unified_id in seen:
            _LOG.error(
                "duplicate unified_id %s from seed[%d] and seed[%d] — "
                "(tax_category, ruleset_kind, canonical_name) triple collides",
                r.unified_id,
                seen[r.unified_id],
                i,
            )
            return 2
        seen[r.unified_id] = i
    _LOG.info("encoded %d rows (all unified_ids unique)", len(rows))

    # -------- 3) Dry-run preview --------
    if args.dry_run:
        args.preview_out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.preview_out.open("w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(
                        json.dumps(
                            {
                                "unified_id": r.unified_id,
                                "ruleset_name": r.ruleset_name,
                                "tax_category": r.tax_category,
                                "ruleset_kind": r.ruleset_kind,
                                "effective_from": r.effective_from,
                                "effective_until": r.effective_until,
                                "eligibility_conditions_json": json.loads(
                                    r.eligibility_conditions_json
                                ),
                                "source_url": r.source_url,
                                "confidence": r.confidence,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        except OSError as exc:
            _LOG.error("failed to write preview: %s", exc)
            return 1
        _LOG.info("dry-run: wrote %d preview rows -> %s", len(rows), args.preview_out)
        if not rows and len(seed) > 0:
            return 3
        return 0

    # -------- 4) UPSERT --------
    db_path = Path(args.db)
    if not db_path.exists():
        _LOG.error("DB not found: %s (run scripts/migrate.py first)", db_path)
        return 1
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            conn.execute("SELECT 1 FROM tax_rulesets LIMIT 1")
            conn.execute("SELECT 1 FROM tax_rulesets_fts LIMIT 1")
        except sqlite3.OperationalError as exc:
            _LOG.error(
                "tax_rulesets missing (%s). Apply migration 018: "
                "python scripts/migrate.py",
                exc,
            )
            return 2

        stats = {"insert": 0, "update": 0}
        try:
            conn.execute("BEGIN")
            for row in rows:
                verdict = upsert_row(conn, row)
                stats[verdict] += 1
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            _LOG.error("DB error during UPSERT: %s", exc)
            return 1

        total = stats["insert"] + stats["update"]
        _LOG.info(
            "encode complete: insert=%d update=%d total=%d",
            stats["insert"],
            stats["update"],
            total,
        )
        if total == 0 and len(seed) > 0:
            return 3
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
