"""Deep health check for jpintel-mcp.

Pure function (no FastAPI binding). Mirrors AutonoMath's
``/api/v1/health/deep`` shape but checks jpintel-mcp's own deps:
the unified ``autonomath.db`` (am_* + jpi_* + entity_id_map) plus the
program shard at ``data/jpintel.db``, and the static knowledge bundle
under ``data/autonomath_static/``.

Each check is independent and fault-tolerant: one failing must NEVER
crash the others. The aggregate ``status`` is:

* ``unhealthy`` — any check is ``fail``
* ``degraded`` — any check is ``warn`` (and none ``fail``)
* ``ok`` — every check is ``ok``

Stdlib only (sqlite3 / datetime / zoneinfo / pathlib).
"""

from __future__ import annotations

import importlib.metadata
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jpintel_mcp.config import settings

# ---- module constants -------------------------------------------------------

# DB paths come from Settings (env: JPINTEL_DB_PATH, AUTONOMATH_DB_PATH).
# In prod these resolve to /data/jpintel.db and /data/autonomath.db on the
# Fly volume; in dev they default to ./data/jpintel.db and ./autonomath.db.
# The previous parents[3] walk broke in prod because the installed package
# lives under /opt/venv/lib/python3.12/site-packages/, not the repo tree.
JPINTEL_DB: Path = settings.db_path
AUTONOMATH_DB: Path = settings.autonomath_db_path
# Static taxonomies live alongside jpintel.db in `data/autonomath_static/`
# both in dev and (post-deploy) on the Fly volume at /data/autonomath_static/.
# Override via AUTONOMATH_STATIC_DIR if the operator stages them elsewhere
# (e.g. baked into the image at /seed/autonomath_static).
_static_env = os.environ.get("AUTONOMATH_STATIC_DIR", "").strip()
if _static_env:
    STATIC_ROOT: Path = Path(_static_env)
else:
    STATIC_ROOT = JPINTEL_DB.parent / "autonomath_static"
STATIC_MANIFEST: Path = STATIC_ROOT / "MANIFEST.md"
STATIC_FILES: tuple[str, ...] = (
    "seido.json",
    "glossary.json",
    "money_types.json",
    "obligations.json",
    "dealbreakers.json",
    "sector_combos.json",
    "agri/crop_library.json",
    "agri/exclusion_rules.json",
)

JST: ZoneInfo = ZoneInfo("Asia/Tokyo")

# Thresholds (KB rot etc.) — keep aligned with Autonomath canonical defaults.
_FRESHNESS_WARN_DAYS: int = 90
_LICENSE_NULL_RATIO_WARN: float = 0.01
_FACT_SOURCE_NULL_RATIO_WARN: float = 0.90
_ENTITY_ID_MAP_RATIO_WARN: float = 0.30
_JPINTEL_PROGRAM_COUNT_WARN: int = 1000
_AM_ENTITIES_COUNT_WARN: int = 100_000


# ---- helpers ----------------------------------------------------------------


def _open_ro(path: Path) -> sqlite3.Connection:
    """Open a sqlite db read-only via URI to avoid creating an empty file."""
    uri = f"file:{path}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


def _read_version() -> str:
    """Read installed package version via importlib.metadata.

    Distributed wheels carry the version in their metadata, so this works in
    prod where pyproject.toml is not on disk. In dev (editable install) it
    still resolves to the value from pyproject.toml.
    """
    try:
        v = importlib.metadata.version("autonomath-mcp")
        return f"v{v}" if not v.startswith("v") else v
    except importlib.metadata.PackageNotFoundError:
        return "v0.0.0+unknown"


def _check(
    name_status: str,
    details: str,
    value: int | float | str | None = None,
) -> dict[str, Any]:
    return {"status": name_status, "details": details, "value": value}


# ---- individual checks -------------------------------------------------------


def _check_db_jpintel_reachable() -> dict[str, Any]:
    try:
        if not JPINTEL_DB.exists():
            return _check("fail", f"db missing: {JPINTEL_DB}", None)
        with _open_ro(JPINTEL_DB) as con:
            n = con.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
        if n <= 0:
            return _check("fail", "programs table empty", n)
        if n < _JPINTEL_PROGRAM_COUNT_WARN:
            return _check(
                "warn",
                f"programs={n} below {_JPINTEL_PROGRAM_COUNT_WARN}",
                n,
            )
        return _check("ok", f"programs={n}", n)
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_db_autonomath_reachable() -> dict[str, Any]:
    try:
        if not AUTONOMATH_DB.exists():
            return _check("fail", f"db missing: {AUTONOMATH_DB}", None)
        with _open_ro(AUTONOMATH_DB) as con:
            n = con.execute("SELECT COUNT(*) FROM am_entities").fetchone()[0]
        if n < _AM_ENTITIES_COUNT_WARN:
            return _check(
                "warn",
                f"am_entities={n} below {_AM_ENTITIES_COUNT_WARN}",
                n,
            )
        return _check("ok", f"am_entities={n}", n)
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_am_entities_freshness() -> dict[str, Any]:
    """Newest am_source.first_seen — warn if older than 90 days."""
    try:
        with _open_ro(AUTONOMATH_DB) as con:
            row = con.execute("SELECT MAX(first_seen) FROM am_source").fetchone()
        raw = row[0] if row else None
        if not raw:
            return _check("warn", "no first_seen rows in am_source", None)
        # Try common ISO-ish shapes: 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SS', etc.
        parsed: datetime | None = None
        candidates = [raw, raw.replace("Z", "+00:00") if "Z" in raw else raw]
        for cand in candidates:
            try:
                parsed = datetime.fromisoformat(cand)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
            except ValueError:
                return _check("warn", f"unparseable first_seen={raw!r}", raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age = datetime.now(UTC) - parsed
        days = age.days
        if age > timedelta(days=_FRESHNESS_WARN_DAYS):
            return _check(
                "warn",
                f"newest am_source is {days}d old (> {_FRESHNESS_WARN_DAYS})",
                days,
            )
        return _check("ok", f"newest am_source is {days}d old", days)
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_license_coverage() -> dict[str, Any]:
    """NULL license ratio in am_source — warn if > 1%."""
    try:
        with _open_ro(AUTONOMATH_DB) as con:
            total, null_count = con.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN license IS NULL OR license = '' THEN 1 ELSE 0 END) "
                "FROM am_source"
            ).fetchone()
        if not total:
            return _check("warn", "am_source empty", 0)
        ratio = (null_count or 0) / total
        if ratio > _LICENSE_NULL_RATIO_WARN:
            return _check(
                "warn",
                f"NULL license ratio={ratio:.4f} (> {_LICENSE_NULL_RATIO_WARN})",
                round(ratio, 6),
            )
        return _check("ok", f"NULL license ratio={ratio:.4f}", round(ratio, 6))
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_fact_source_id_coverage() -> dict[str, Any]:
    """NULL source_id ratio in am_entity_facts — warn only if > 90%."""
    try:
        with _open_ro(AUTONOMATH_DB) as con:
            # Two-query form is ~2x faster than a single CASE-aggregate at 6M
            # rows: SQLite uses idx_am_efacts_source (partial / null-aware) for
            # the NULL count and table-stat for COUNT(*).
            total = con.execute(
                "SELECT COUNT(*) FROM am_entity_facts"
            ).fetchone()[0]
            null_count = con.execute(
                "SELECT COUNT(*) FROM am_entity_facts WHERE source_id IS NULL"
            ).fetchone()[0]
        if not total:
            return _check("warn", "am_entity_facts empty", 0)
        ratio = (null_count or 0) / total
        if ratio > _FACT_SOURCE_NULL_RATIO_WARN:
            return _check(
                "warn",
                f"NULL source_id ratio={ratio:.4f} "
                f"(worsened past tech-debt cap {_FACT_SOURCE_NULL_RATIO_WARN})",
                round(ratio, 6),
            )
        return _check(
            "ok",
            f"NULL source_id ratio={ratio:.4f} (within tech-debt cap)",
            round(ratio, 6),
        )
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_entity_id_map_coverage() -> dict[str, Any]:
    """jpi_programs rows with an entity_id_map row — warn if mapped < 30%."""
    try:
        with _open_ro(AUTONOMATH_DB) as con:
            total = con.execute("SELECT COUNT(*) FROM jpi_programs").fetchone()[0]
            if not total:
                return _check("fail", "jpi_programs empty", 0)
            mapped = con.execute(
                "SELECT COUNT(*) FROM jpi_programs p "
                "WHERE EXISTS (SELECT 1 FROM entity_id_map e "
                "WHERE e.jpi_unified_id = p.unified_id)"
            ).fetchone()[0]
        ratio = mapped / total
        if ratio < _ENTITY_ID_MAP_RATIO_WARN:
            return _check(
                "warn",
                f"mapped ratio={ratio:.4f} (< {_ENTITY_ID_MAP_RATIO_WARN})",
                round(ratio, 6),
            )
        return _check(
            "ok", f"mapped ratio={ratio:.4f} ({mapped}/{total})", round(ratio, 6)
        )
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_annotation_volume() -> dict[str, Any]:
    """am_entity_annotation must be non-empty (migration 046 applied)."""
    try:
        with _open_ro(AUTONOMATH_DB) as con:
            n = con.execute("SELECT COUNT(*) FROM am_entity_annotation").fetchone()[0]
        if n == 0:
            return _check(
                "fail", "am_entity_annotation=0 (migration 046 not applied?)", 0
            )
        return _check("ok", f"am_entity_annotation={n}", n)
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_validation_rules_loaded() -> dict[str, Any]:
    try:
        with _open_ro(AUTONOMATH_DB) as con:
            n = con.execute("SELECT COUNT(*) FROM am_validation_rule").fetchone()[0]
        if n == 0:
            return _check("fail", "am_validation_rule=0", 0)
        return _check("ok", f"am_validation_rule={n}", n)
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_static_files_present() -> dict[str, Any]:
    """MANIFEST + 8 known JSON files."""
    try:
        if not STATIC_MANIFEST.exists():
            return _check("fail", f"MANIFEST missing: {STATIC_MANIFEST}", None)
        missing: list[str] = []
        for rel in STATIC_FILES:
            if not (STATIC_ROOT / rel).exists():
                missing.append(rel)
        present = len(STATIC_FILES) - len(missing)
        if missing:
            return _check(
                "warn",
                f"missing files: {missing} ({present}/{len(STATIC_FILES)} present)",
                present,
            )
        return _check(
            "ok",
            f"all {len(STATIC_FILES)} static files present",
            present,
        )
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


def _check_wal_mode() -> dict[str, Any]:
    try:
        with _open_ro(AUTONOMATH_DB) as con:
            mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        mode_s = str(mode).lower()
        if mode_s != "wal":
            return _check("warn", f"journal_mode={mode_s} (expected wal)", mode_s)
        return _check("ok", "journal_mode=wal", mode_s)
    except Exception as e:  # noqa: BLE001
        return _check("fail", f"{type(e).__name__}: {e}", None)


# ---- aggregate --------------------------------------------------------------

# Ordered registry of (name, callable). Tests rely on this list.
CHECKS: tuple[tuple[str, Any], ...] = (
    ("db_jpintel_reachable", _check_db_jpintel_reachable),
    ("db_autonomath_reachable", _check_db_autonomath_reachable),
    ("am_entities_freshness", _check_am_entities_freshness),
    ("license_coverage", _check_license_coverage),
    ("fact_source_id_coverage", _check_fact_source_id_coverage),
    ("entity_id_map_coverage", _check_entity_id_map_coverage),
    ("annotation_volume", _check_annotation_volume),
    ("validation_rules_loaded", _check_validation_rules_loaded),
    ("static_files_present", _check_static_files_present),
    ("wal_mode", _check_wal_mode),
)


def _aggregate(checks: dict[str, dict[str, Any]]) -> str:
    statuses = {c.get("status") for c in checks.values()}
    if "fail" in statuses:
        return "unhealthy"
    if "warn" in statuses:
        return "degraded"
    return "ok"


# 30-second response cache: heartbeat doesn't need real-time. Each check is
# pure-read sqlite + filesystem stat; aggregating these every <30s is wasted
# work. Pass force=True to bypass (debugging / post-deploy verification).
_CACHE: dict[str, Any] = {"ts": 0.0, "doc": None}
_CACHE_TTL: float = 30.0  # seconds


def get_deep_health(force: bool = False) -> dict[str, object]:
    """Run every registered check; return aggregate health document.

    Each check is invoked under its own try/except so a single failure cannot
    propagate to siblings or the caller. Checks run in parallel via a
    ThreadPoolExecutor — they are sync sqlite3 / filesystem ops that release
    the GIL on I/O, so threads cut wall time roughly N-fold.

    Set ``force=True`` to bypass the 30-second response cache.
    """
    now_mono = time.monotonic()
    if (
        not force
        and _CACHE["doc"] is not None
        and now_mono - _CACHE["ts"] < _CACHE_TTL
    ):
        return _CACHE["doc"]

    checks: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fn): name for name, fn in CHECKS}
        for future in as_completed(futures, timeout=8):
            name = futures[future]
            try:
                result = future.result()
                if not isinstance(result, dict) or "status" not in result:
                    result = _check("fail", f"malformed result: {result!r}", None)
            except Exception as e:  # noqa: BLE001 — fault tolerance
                result = _check(
                    "fail", f"unhandled {type(e).__name__}: {e}", None
                )
            checks[name] = result

    # Restore registration order so callers see a stable, predictable layout
    # (tests + dashboards may iterate by insertion order).
    ordered: dict[str, dict[str, Any]] = {
        name: checks[name] for name, _ in CHECKS if name in checks
    }

    now_utc = datetime.now(UTC)
    now_jst = now_utc.astimezone(JST)
    doc: dict[str, object] = {
        "status": _aggregate(ordered),
        "version": _read_version(),
        "checks": ordered,
        "timestamp_utc": now_utc.isoformat(),
        "evaluated_at_jst": now_jst.isoformat(),
    }
    _CACHE["ts"] = now_mono
    _CACHE["doc"] = doc
    return doc
