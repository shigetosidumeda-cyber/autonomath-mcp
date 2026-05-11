#!/usr/bin/env python3
"""Regenerate data/facts_registry.json + data/facts_registry_full.json.

Wave 18 B6 — AI-agent GEO substrate. A single fetch lets a downstream LLM
(GPT/Claude/Perplexity/Gemini) see the full surface of jpcite-tracked entities
without scraping 21k+ per-entity HTML pages.

Two output files (atomic write, idempotent):

  - data/facts_registry.json         (~1 MB lightweight index)
      schema_version + snapshot_at + snapshot_git_sha (preserved verbatim)
      guards.banned_terms / fence_count_* / numeric_ranges / forbidden_modifiers
      facts[]                        (24 core publishable facts — preserved)
      do_not_provide / data_quality_publishable_false (preserved)
      index[]                        (NEW — light per-entity surface:
                                      entity_id + kind + primary_name only)

  - data/facts_registry_full.json    (~4-5 MB full per-entity metadata)
      schema_version + snapshot_at + snapshot_git_sha
      entities[]                     (entity_id + kind + primary_name +
                                      source_url + source_url_domain +
                                      last_verified + authority + confidence
                                      + category)

Sources (read-only):
  - data/jpintel.db                  programs (11,601 tier S/A/B/C live),
                                     case_studies, enforcement_cases, laws,
                                     court_decisions
  - autonomath.db                    am_entities (503,930 rows) — fallback +
                                     enrichment when jpintel rows are missing
                                     (e.g. local dev fixture is the empty 1MB
                                     stub; production volume has the full
                                     corpus).

Selection: 4 publishable record_kinds — program, law, case_study, enforcement.
Banned aggregator hosts (smart-hojokin / noukaweb / etc.) are filtered out.
Excluded + tier='X' rows are filtered out (CLAUDE.md non-negotiable).

Brand hygiene: primary_name strings that match the legacy brand markers
(税務会計AI / jpintel / AutonoMath) are stripped before emit — those are the
old brands and surfacing them in a GEO-substrate file would un-rename the site
in AI indexes.

Idempotent: re-running produces byte-identical output for identical DB state.
CLI:
    .venv/bin/python scripts/regen_facts_registry.py
    .venv/bin/python scripts/regen_facts_registry.py --jpintel-db data/jpintel.db --autonomath-db autonomath.db
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import sys
import tempfile
from collections.abc import Iterable  # noqa: TC003 (used in runtime annotations)
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Python 3.9 lacks datetime.UTC (added in 3.11). Define a compat shim so the
# script runs under any 3.9+ interpreter (system /usr/bin/python3 is 3.9 on
# macOS 14 hosts; the project .venv runs 3.13).
UTC = timezone.utc  # noqa: UP017

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JPINTEL_DB = ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = ROOT / "autonomath.db"
DEFAULT_OUT_LIGHT = ROOT / "data" / "facts_registry.json"
DEFAULT_OUT_FULL = ROOT / "data" / "facts_registry_full.json"

# Aggregator + low-quality hosts banned per CLAUDE.md non-negotiable.
_BANNED_SOURCE_HOSTS = frozenset(
    {
        "smart-hojokin.jp",
        "noukaweb.jp",
        "hojyokin-portal.jp",
        "biz.stayway.jp",
        "stayway.jp",
        "j-net21.smrj.go.jp",  # not banned per se but de-prioritized; keep
    }
)
# The j-net21 entry above is conservative — it's a legitimate SMRJ surface,
# so re-allow it explicitly:
_BANNED_SOURCE_HOSTS = _BANNED_SOURCE_HOSTS - {"j-net21.smrj.go.jp"}

# Legacy brand tokens that must not appear in primary_name in GEO substrate.
# Case-insensitive substring match. (CLAUDE.md: "jpintel brand collides with
# Intel, do not revive in user-facing copy"; old brands AutonoMath /
# 税務会計AI / zeimu-kaikei.ai are likewise retired.)
_LEGACY_BRAND_SUBSTRINGS = (
    "jpintel",
    "autonomath",
    "AutonoMath",
    "税務会計AI",
    "zeimu-kaikei",
)


def _has_banned_host(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in _BANNED_SOURCE_HOSTS


def _has_legacy_brand(name: str | None) -> bool:
    if not name:
        return False
    low = name.lower()
    return any(tok.lower() in low for tok in _LEGACY_BRAND_SUBSTRINGS)


def _connect_ro(path: Path) -> sqlite3.Connection | None:
    """Open SQLite read-only. Returns None if file is missing or empty stub."""
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    # Empty / 0-byte placeholders (data/autonomath.db is intentionally 0B in
    # checkouts where the canonical 9 GB lives at repo root).
    if size < 4096:
        return None
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _query_iter(
    conn: sqlite3.Connection, sql: str, params: tuple = ()
) -> Iterable[sqlite3.Row]:
    try:
        cur = conn.execute(sql, params)
    except sqlite3.Error:
        return iter(())
    return cur


def _host_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower() or None
    except Exception:
        return None


def _safe_iso(value: str | None) -> str | None:
    if not value:
        return None
    return value if "T" in value else value + "T00:00:00Z"


# ------------------------------------------------------------------
# Sources
# ------------------------------------------------------------------


def harvest_programs(jpi: sqlite3.Connection | None, auto: sqlite3.Connection | None):
    """Yield (entity_id, kind, primary_name, source_url, last_verified, authority, confidence, category, tier).

    Priority: jpintel.db `programs` is the canonical SOT per CLAUDE.md. Only
    fall back to autonomath.db `am_entities(record_kind='program')` when
    jpintel side yielded zero rows (e.g. local dev fixture is empty / missing).
    """
    seen_ids: set[str] = set()
    jpi_yielded = 0
    if jpi is not None and _table_exists(jpi, "programs"):
        for row in _query_iter(
            jpi,
            """
            SELECT unified_id, primary_name, source_url, source_fetched_at,
                   authority_name, tier
              FROM programs
             WHERE excluded = 0
               AND tier IN ('S','A','B','C')
            """,
        ):
            uid = row["unified_id"]
            if not uid or uid in seen_ids:
                continue
            if _has_banned_host(row["source_url"]):
                continue
            if _has_legacy_brand(row["primary_name"]):
                continue
            seen_ids.add(uid)
            jpi_yielded += 1
            yield (
                uid,
                "program",
                row["primary_name"],
                row["source_url"],
                _safe_iso(row["source_fetched_at"]),
                row["authority_name"],
                None,
                "program",
                row["tier"],
            )
    if jpi_yielded > 0:
        # jpintel.db was authoritative; skip autonomath fallback to keep
        # registry counts honest and file size predictable.
        return
    if auto is not None and _table_exists(auto, "am_entities"):
        for row in _query_iter(
            auto,
            """
            SELECT canonical_id, primary_name, source_url, fetched_at,
                   authority_canonical, confidence
              FROM am_entities
             WHERE record_kind = 'program'
               AND canonical_status = 'active'
            """,
        ):
            uid = row["canonical_id"]
            if not uid or uid in seen_ids:
                continue
            if _has_banned_host(row["source_url"]):
                continue
            if _has_legacy_brand(row["primary_name"]):
                continue
            seen_ids.add(uid)
            yield (
                uid,
                "program",
                row["primary_name"],
                row["source_url"],
                _safe_iso(row["fetched_at"]),
                row["authority_canonical"],
                row["confidence"],
                "program",
                None,
            )


def harvest_laws(jpi: sqlite3.Connection | None, auto: sqlite3.Connection | None):
    """jpintel.laws SOT; autonomath fallback only when jpintel yields 0."""
    seen: set[str] = set()
    jpi_yielded = 0
    if jpi is not None and _table_exists(jpi, "laws"):
        for row in _query_iter(
            jpi,
            """
            SELECT unified_id, law_title, source_url, fetched_at,
                   ministry, confidence, revision_status
              FROM laws
             WHERE revision_status IN ('current', 'superseded')
            """,
        ):
            uid = row["unified_id"]
            if not uid or uid in seen:
                continue
            if _has_legacy_brand(row["law_title"]):
                continue
            seen.add(uid)
            jpi_yielded += 1
            yield (
                uid,
                "law",
                row["law_title"],
                row["source_url"],
                _safe_iso(row["fetched_at"]),
                row["ministry"],
                row["confidence"],
                "law",
                None,
            )
    if jpi_yielded > 0:
        return
    if auto is not None and _table_exists(auto, "am_entities"):
        for row in _query_iter(
            auto,
            """
            SELECT canonical_id, primary_name, source_url, fetched_at,
                   authority_canonical, confidence
              FROM am_entities
             WHERE record_kind = 'law'
               AND canonical_status = 'active'
            """,
        ):
            uid = row["canonical_id"]
            if not uid or uid in seen:
                continue
            if _has_legacy_brand(row["primary_name"]):
                continue
            seen.add(uid)
            yield (
                uid,
                "law",
                row["primary_name"],
                row["source_url"],
                _safe_iso(row["fetched_at"]),
                row["authority_canonical"],
                row["confidence"],
                "law",
                None,
            )


def harvest_cases(jpi: sqlite3.Connection | None, auto: sqlite3.Connection | None):
    """jpintel.case_studies SOT; autonomath fallback only when jpintel yields 0."""
    seen: set[str] = set()
    jpi_yielded = 0
    if jpi is not None and _table_exists(jpi, "case_studies"):
        for row in _query_iter(
            jpi,
            """
            SELECT case_id, case_title, source_url, fetched_at,
                   industry_name, confidence
              FROM case_studies
            """,
        ):
            uid = row["case_id"]
            if not uid or uid in seen:
                continue
            if _has_banned_host(row["source_url"]):
                continue
            if _has_legacy_brand(row["case_title"]):
                continue
            seen.add(uid)
            jpi_yielded += 1
            yield (
                uid,
                "case_study",
                row["case_title"],
                row["source_url"],
                _safe_iso(row["fetched_at"]),
                row["industry_name"],
                row["confidence"],
                "case_study",
                None,
            )
    if jpi_yielded > 0:
        return
    if auto is not None and _table_exists(auto, "am_entities"):
        for row in _query_iter(
            auto,
            """
            SELECT canonical_id, primary_name, source_url, fetched_at,
                   authority_canonical, confidence
              FROM am_entities
             WHERE record_kind = 'case_study'
               AND canonical_status = 'active'
            """,
        ):
            uid = row["canonical_id"]
            if not uid or uid in seen:
                continue
            if _has_banned_host(row["source_url"]):
                continue
            if _has_legacy_brand(row["primary_name"]):
                continue
            seen.add(uid)
            yield (
                uid,
                "case_study",
                row["primary_name"],
                row["source_url"],
                _safe_iso(row["fetched_at"]),
                row["authority_canonical"],
                row["confidence"],
                "case_study",
                None,
            )


def harvest_enforcement(
    jpi: sqlite3.Connection | None, auto: sqlite3.Connection | None
):
    """jpintel.enforcement_cases SOT; autonomath fallback only when jpintel yields 0."""
    seen: set[str] = set()
    jpi_yielded = 0
    if jpi is not None and _table_exists(jpi, "enforcement_cases"):
        for row in _query_iter(
            jpi,
            """
            SELECT case_id, program_name_hint, source_url, disclosed_date,
                   ministry, bureau
              FROM enforcement_cases
            """,
        ):
            uid = row["case_id"]
            if not uid or uid in seen:
                continue
            if _has_legacy_brand(row["program_name_hint"]):
                continue
            seen.add(uid)
            jpi_yielded += 1
            yield (
                uid,
                "enforcement",
                row["program_name_hint"] or f"行政処分 {uid}",
                row["source_url"],
                _safe_iso(row["disclosed_date"]),
                row["ministry"] or row["bureau"],
                None,
                "enforcement",
                None,
            )
    if jpi_yielded > 0:
        return
    if auto is not None and _table_exists(auto, "am_entities"):
        for row in _query_iter(
            auto,
            """
            SELECT canonical_id, primary_name, source_url, fetched_at,
                   authority_canonical, confidence
              FROM am_entities
             WHERE record_kind = 'enforcement'
               AND canonical_status = 'active'
            """,
        ):
            uid = row["canonical_id"]
            if not uid or uid in seen:
                continue
            if _has_legacy_brand(row["primary_name"]):
                continue
            seen.add(uid)
            yield (
                uid,
                "enforcement",
                row["primary_name"],
                row["source_url"],
                _safe_iso(row["fetched_at"]),
                row["authority_canonical"],
                row["confidence"],
                "enforcement",
                None,
            )


# ------------------------------------------------------------------
# Build outputs
# ------------------------------------------------------------------


def build_records(
    jpi: sqlite3.Connection | None, auto: sqlite3.Connection | None
) -> list[dict]:
    out: list[dict] = []
    for fn in (harvest_programs, harvest_laws, harvest_cases, harvest_enforcement):
        for (
            uid,
            kind,
            name,
            url,
            last_verified,
            authority,
            confidence,
            category,
            tier,
        ) in fn(jpi, auto):
            rec = {
                "entity_id": uid,
                "kind": kind,
                "primary_name": (name or "").strip(),
                "source_url": url,
                "source_url_domain": _host_of(url),
                "last_verified": last_verified,
                "authority": authority,
                "confidence": confidence,
                "category": category,
            }
            if tier:
                rec["tier"] = tier
            out.append(rec)
    # Stable deterministic ordering: by kind then entity_id.
    out.sort(key=lambda r: (r["kind"], r["entity_id"]))
    return out


def _compact_bulk_key(payload: dict, key: str) -> str | None:
    """Serialise `payload[key]` (a list of dicts) one-row-per-line compact.

    Output looks like:
        "index": [
        {"entity_id":"...","kind":"...","primary_name":"..."},
        {"entity_id":"...","kind":"...","primary_name":"..."}
        ]
    This keeps git diffs row-stable + cuts ~50-60% size vs full indent.
    Returns None if the key is not present.
    """
    if key not in payload:
        return None
    rows: list = payload[key]
    if not rows:
        return f'  "{key}": []'
    parts = [f'  "{key}": [']
    last = len(rows) - 1
    for i, r in enumerate(rows):
        line = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
        suffix = "," if i < last else ""
        parts.append(f"  {line}{suffix}")
    parts.append("  ]")
    return "\n".join(parts)


def write_atomic(path: Path, payload: dict, bulk_keys: tuple[str, ...] = ()) -> int:
    """Atomic write; returns final byte size.

    `bulk_keys` names list-of-dict members in `payload` to emit in compact
    one-row-per-line form (size + diff friendly). All other keys render with
    indent=2.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Render top-level scalar/object keys normally; replace bulk arrays with
    # compact one-row-per-line form after the fact.
    sentinel = "__JPCITE_BULK_PLACEHOLDER__"
    work_payload: dict = {}
    placeholders: dict[str, str] = {}
    for k, v in payload.items():
        if k in bulk_keys:
            placeholder = f"{sentinel}__{k}__"
            work_payload[k] = placeholder
            compact = _compact_bulk_key({k: v}, k)
            if compact is not None:
                placeholders[k] = compact
        else:
            work_payload[k] = v
    body = json.dumps(work_payload, ensure_ascii=False, indent=2, sort_keys=False)
    for k, compact in placeholders.items():
        # The placeholder line in `body` reads:    "k": "__JPCITE_BULK..."
        # Replace the whole line with the compact form.
        needle = f'  "{k}": "{sentinel}__{k}__"'
        if needle in body:
            body = body.replace(needle, compact, 1)
    body += "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return path.stat().st_size


def load_existing_core(path: Path) -> dict:
    """Load existing facts_registry.json core (preserve facts/guards/etc)."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def emit_light(
    records: list[dict],
    existing: dict,
    snapshot_at: str,
) -> dict:
    """Compose the lightweight registry (preserve existing facts / guards)."""
    payload: dict = {}
    # Preserve schema_version + snapshot meta + guards + facts + do_not_provide
    # if they exist in the existing file. Refresh snapshot_at to current run.
    payload["schema_version"] = existing.get("schema_version", "1.0")
    payload["snapshot_at"] = snapshot_at
    if existing.get("snapshot_git_sha"):
        payload["snapshot_git_sha"] = existing["snapshot_git_sha"]
    for k in ("guards", "facts", "do_not_provide", "data_quality_publishable_false"):
        if k in existing:
            payload[k] = existing[k]
    # NEW — lightweight index. Keep field set minimal so file stays ~1 MB
    # at 21k entries (entity_id + kind + primary_name ≈ 50-60 bytes/row).
    payload["index_count"] = len(records)
    payload["index"] = [
        {"entity_id": r["entity_id"], "kind": r["kind"], "primary_name": r["primary_name"]}
        for r in records
    ]
    return payload


def emit_full(records: list[dict], snapshot_at: str, git_sha: str | None) -> dict:
    payload: dict = {
        "schema_version": "1.0-full",
        "snapshot_at": snapshot_at,
    }
    if git_sha:
        payload["snapshot_git_sha"] = git_sha
    payload["entity_count"] = len(records)
    payload["entities"] = records
    return payload


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    p.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    p.add_argument("--out-light", type=Path, default=DEFAULT_OUT_LIGHT)
    p.add_argument("--out-full", type=Path, default=DEFAULT_OUT_FULL)
    p.add_argument(
        "--smoke",
        action="store_true",
        help="exit 0 with warning even if both DBs empty (CI fixture mode)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    jpi = _connect_ro(args.jpintel_db)
    auto = _connect_ro(args.autonomath_db)
    if jpi is None and auto is None:
        msg = (
            f"both source DBs unavailable: {args.jpintel_db} / {args.autonomath_db}"
        )
        if args.smoke:
            print(f"warning (smoke): {msg}; emitting empty index", file=sys.stderr)
        else:
            print(f"error: {msg}", file=sys.stderr)
            return 2

    records = build_records(jpi, auto)
    # Day-precision snapshot so same-day re-runs produce byte-identical
    # output (idempotence required for clean git diffs + cron predictability).
    snapshot_at = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")

    existing = load_existing_core(args.out_light)
    git_sha = existing.get("snapshot_git_sha")

    light = emit_light(records, existing, snapshot_at)
    full = emit_full(records, snapshot_at, git_sha)

    light_size = write_atomic(args.out_light, light, bulk_keys=("index",))
    full_size = write_atomic(args.out_full, full, bulk_keys=("entities",))

    print(
        f"regen_facts_registry: light={args.out_light} {light_size} bytes / "
        f"full={args.out_full} {full_size} bytes / records={len(records)}"
    )
    if jpi is not None:
        jpi.close()
    if auto is not None:
        auto.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
