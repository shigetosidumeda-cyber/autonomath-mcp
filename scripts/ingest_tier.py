#!/usr/bin/env python3
"""Tiered ingest driver for jpintel-mcp.

Entry point for the daily / weekly / monthly ingest workflows under
.github/workflows/ingest-*.yml. Designed to run ON the Fly production
machine (writes land on /data/jpintel.db) — NOT inside GitHub Actions
checkout. See docs/ingest_automation.md for the full contract.

Skeleton status: wiring + CLI + metrics are real; per-authority fetchers
are stubs marked with TODO. Each fetcher will be landed in its own PR
keyed to the authority owner.

Usage:
    python scripts/ingest_tier.py daily
    python scripts/ingest_tier.py weekly --authority "農林水産省"
    python scripts/ingest_tier.py monthly --month-slot 2
    python scripts/ingest_tier.py daily --dry-run

Exit codes:
    0   driver success (per-authority failures logged in ingest_log.jsonl)
    2   CLI / config error (bad tier, missing DB, etc.) — hard fail
    3   unexpected driver crash (every authority failed; unlikely in steady state)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Re-use the canonical ingest helpers (checksum + lineage extraction).
# These live in the API package so the same functions produce the same
# checksums whether called from a one-shot `canonical.run()` or from this
# tier driver. DO NOT fork them.
try:
    from jpintel_mcp.ingest.canonical import (
        _compute_source_checksum,
        _extract_source_url,
        _flatten_enriched_text,
    )
except ImportError:  # pragma: no cover - allows standalone skeleton exec
    _compute_source_checksum = None  # type: ignore[assignment]
    _extract_source_url = None  # type: ignore[assignment]
    _flatten_enriched_text = None  # type: ignore[assignment]

from scripts.lib.http import HttpClient

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOG = logging.getLogger("jpintel.ingest_tier")

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------
#
# Keep authority names aligned with the distinct authority_name values in
# data/jpintel.db. A rebinding here is the only contract change needed when
# moving an authority between tiers.
#
# `netlocs` is an allowlist for the fetcher to walk (so e.g. the weekly
# MAFF fetcher won't accidentally recurse out to chusho.meti.go.jp).
#
# AUTHORITY_TIERS doubles as the OWNER_TIER lookup used by §3 conflict
# resolution: whichever tier the authority lives in wins for that unified_id.


@dataclass(frozen=True)
class AuthoritySpec:
    name: str
    netlocs: tuple[str, ...]
    kind: str  # "api" | "html" | "pdf-index" | "g-reiki" | "unknown"


AUTHORITY_TIERS: dict[str, list[AuthoritySpec]] = {
    "daily": [
        AuthoritySpec(
            name="Jグランツ",
            netlocs=("www.jgrants-portal.go.jp", "api.jgrants-portal.go.jp"),
            kind="api",
        ),
        AuthoritySpec(
            name="中小企業庁",
            netlocs=("www.chusho.meti.go.jp",),
            kind="html",
        ),
        AuthoritySpec(
            name="経済産業省（公募枠）",
            netlocs=("www.meti.go.jp",),
            kind="html",
        ),
        AuthoritySpec(
            name="大型補助金事務局",
            netlocs=(
                # Filled per-round — each campaign site registers here.
                # Empty by default so first run is a no-op.
            ),
            kind="html",
        ),
    ],
    "weekly": [
        AuthoritySpec(
            name="農林水産省",
            netlocs=("www.maff.go.jp",),
            kind="html",
        ),
        AuthoritySpec(
            name="厚生労働省",
            netlocs=("www.mhlw.go.jp",),
            kind="html",
        ),
        AuthoritySpec(
            name="日本政策金融公庫",
            netlocs=("www.jfc.go.jp",),
            kind="html",
        ),
        AuthoritySpec(
            name="国税庁",
            netlocs=("www.nta.go.jp",),
            kind="html",
        ),
        AuthoritySpec(
            name="特許庁",
            netlocs=("www.jpo.go.jp",),
            kind="html",
        ),
        AuthoritySpec(
            name="中小機構",
            netlocs=("www.smrj.go.jp",),
            kind="html",
        ),
        # noukaweb rehost — provisional until canonical replacement lands.
        AuthoritySpec(
            name="（noukaweb 収集）",
            netlocs=("www.noukaweb.com",),
            kind="html",
        ),
    ],
    "monthly": [
        # Prefectures: one synthetic authority per ken. netlocs pattern is
        # documented; fetcher expands it at runtime from the 47-list.
        AuthoritySpec(
            name="都道府県（47）",
            netlocs=("*.pref.*.lg.jp", "*.pref.*.jp"),
            kind="html",
        ),
        AuthoritySpec(
            name="市区町村（サンプリング）",
            netlocs=("*.city.*.lg.jp", "*.town.*.lg.jp", "*.city.*.jp", "*.town.*.jp"),
            kind="html",
        ),
        AuthoritySpec(
            name="例規データベース",
            netlocs=("www1.g-reiki.net",),
            kind="g-reiki",
        ),
    ],
}

DB_PATH = Path(os.environ.get("JPINTEL_DB_PATH", "/data/jpintel.db"))
INGEST_LOG_PATH = Path(os.environ.get("JPINTEL_INGEST_LOG_PATH", "/data/ingest_log.jsonl"))
FAILURE_STREAK_THRESHOLD = 3  # §4: 3-consecutive-fail → Slack/Issue alert


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ProgramRow:
    """Fetched-from-source snapshot of one program, pre-checksum.

    Fetchers return these. The driver computes the checksum + compares to
    `programs.source_checksum` to decide add / update / unchanged.
    """
    unified_id: str
    primary_name: str
    authority_name: str
    authority_level: str | None  # national | prefecture | municipality | financial
    source_url: str | None
    official_url: str | None
    enriched: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpsertResult:
    unified_id: str
    action: str  # "added" | "updated" | "unchanged" | "rejected"
    reject_reason: str | None = None


@dataclass
class AuthorityResult:
    name: str
    ok: bool
    rows_added: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_rejected: int = 0
    error: str | None = None


@dataclass
class IngestMetrics:
    tier: str
    started_at: str
    completed_at: str
    authorities_ok: int
    authorities_fail: int
    rows_added: int
    rows_updated: int
    rows_unchanged: int
    duration_s: float
    sha: str | None
    authorities: list[AuthorityResult]

    def to_log_line(self) -> dict[str, Any]:
        return {
            "event": "ingest_done",
            "tier": self.tier,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "authorities_ok": self.authorities_ok,
            "authorities_fail": self.authorities_fail,
            "rows_added": self.rows_added,
            "rows_updated": self.rows_updated,
            "rows_unchanged": self.rows_unchanged,
            "duration_s": round(self.duration_s, 2),
            "sha": self.sha,
            "authorities": [dataclasses.asdict(a) for a in self.authorities],
        }


# ---------------------------------------------------------------------------
# Fetcher dispatch
# ---------------------------------------------------------------------------


def fetch_authority(spec: AuthoritySpec, *, http: HttpClient) -> Iterator[ProgramRow]:
    """Dispatch to a per-authority fetcher.

    Skeleton: yields nothing. Each fetcher below is a TODO stub so the
    driver runs end-to-end without DB writes and emits a metrics line
    with rows_added=0 on first deploy. This is intentional — we land the
    GHA plumbing first, then fill fetchers one by one.
    """
    name = spec.name
    if name == "Jグランツ":
        yield from _fetch_jgrants(http)
    elif name == "中小企業庁":
        yield from _fetch_chusho(http)
    elif name == "農林水産省":
        yield from _fetch_maff(http)
    elif name == "厚生労働省":
        yield from _fetch_mhlw(http)
    elif name == "日本政策金融公庫":
        yield from _fetch_jfc(http)
    elif name == "都道府県（47）":
        yield from _fetch_prefectures(http)
    elif name == "市区町村（サンプリング）":
        yield from _fetch_municipalities(http, month_slot=_month_slot_from_env())
    else:
        _LOG.info("no fetcher for authority=%s (skeleton)", name)
        return
        yield  # pragma: no cover  (generator shape)


# -- per-authority stubs -----------------------------------------------------

def _fetch_jgrants(http: HttpClient) -> Iterator[ProgramRow]:  # noqa: ARG001
    # TODO(owner=@shigeto): implement via jgrants OpenAPI (digital.go.jp)
    # Signature: yields ProgramRow per 公募. Use authority_level='national',
    # authority_name='Jグランツ' (or the publishing ministry when known).
    # Expected ~24 direct + ~150 relay = ~170 rows/run.
    return iter(())


def _fetch_chusho(http: HttpClient) -> Iterator[ProgramRow]:  # noqa: ARG001
    # TODO(owner=@shigeto): HTML walk of www.chusho.meti.go.jp/koukai.
    # ~13 existing + new rounds. Layout stable; PDF links OK via lib.http.
    return iter(())


def _fetch_maff(http: HttpClient) -> Iterator[ProgramRow]:  # noqa: ARG001
    # TODO(owner=@shigeto): weekly walk of www.maff.go.jp. 800+ rows.
    # PDF-heavy. Expect PDF layout drift — plan for a parser-diff test.
    return iter(())


def _fetch_mhlw(http: HttpClient) -> Iterator[ProgramRow]:  # noqa: ARG001
    # TODO(owner=@shigeto): 雇用調整助成金系 index walk.
    return iter(())


def _fetch_jfc(http: HttpClient) -> Iterator[ProgramRow]:  # noqa: ARG001
    # TODO(owner=@shigeto): JFC site search shortcut already proven in
    # reference_canonical_enrichment.md. Reuse Playwright or headless path
    # OUTSIDE this hot path — if we need JS, shell to a helper script.
    return iter(())


def _fetch_prefectures(http: HttpClient) -> Iterator[ProgramRow]:  # noqa: ARG001
    # TODO(owner=@shigeto): walk the 47 *.pref.*.lg.jp / *.pref.*.jp roots
    # using scripts/prefecture_walker.py logic (currently one-shot; turn
    # into a library).
    return iter(())


def _fetch_municipalities(http: HttpClient, *, month_slot: int) -> Iterator[ProgramRow]:  # noqa: ARG001
    # TODO(owner=@shigeto): pick ~25% of the ~500 muni netlocs per slot.
    # Slot 0..3 cover all municipalities across 4 months.
    assert 0 <= month_slot <= 3
    return iter(())


def _month_slot_from_env() -> int:
    raw = os.environ.get("JPINTEL_MONTH_SLOT", "0")
    try:
        v = int(raw)
    except ValueError:
        v = 0
    return max(0, min(3, v))


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def upsert_program(
    conn: sqlite3.Connection,
    row: ProgramRow,
    *,
    now: str,
    dry_run: bool,
) -> UpsertResult:
    """Compare new checksum to current row; add / update / unchanged / reject.

    We do NOT delete on failure (§4). The row is only touched when the new
    checksum differs. FTS is rebuilt only on actual change.
    """
    if not row.unified_id or not row.primary_name:
        return UpsertResult(
            unified_id=row.unified_id or "<missing>",
            action="rejected",
            reject_reason="missing unified_id or primary_name",
        )

    if _compute_source_checksum is None:
        return UpsertResult(
            unified_id=row.unified_id,
            action="rejected",
            reject_reason="canonical helpers not importable",
        )

    new_checksum = _compute_source_checksum(row.enriched, row.extras)
    row.source_url or _extract_source_url(row.enriched, row.extras) if _extract_source_url else row.source_url

    cur = conn.execute(
        "SELECT source_checksum FROM programs WHERE unified_id=?",
        (row.unified_id,),
    ).fetchone()

    if cur is None:
        if dry_run:
            return UpsertResult(unified_id=row.unified_id, action="added")
        # TODO(owner=@shigeto): full INSERT mirroring canonical._ingest_programs
        # schema (see src/jpintel_mcp/ingest/canonical.py). Kept as TODO in
        # skeleton — driver still logs metrics for planning.
        return UpsertResult(unified_id=row.unified_id, action="added")

    if cur[0] == new_checksum:
        return UpsertResult(unified_id=row.unified_id, action="unchanged")

    if dry_run:
        return UpsertResult(unified_id=row.unified_id, action="updated")
    # TODO(owner=@shigeto): UPDATE + rebuild FTS row for this unified_id only.
    return UpsertResult(unified_id=row.unified_id, action="updated")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_tier(tier: str, *, authority_filter: str | None, dry_run: bool) -> IngestMetrics:
    specs = AUTHORITY_TIERS[tier]
    if authority_filter:
        specs = [s for s in specs if s.name == authority_filter]
        if not specs:
            raise SystemExit(f"no authority in tier={tier} matches --authority={authority_filter}")

    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    now_iso = started_at

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    results: list[AuthorityResult] = []
    total_add = total_upd = total_unch = 0

    with HttpClient() as http:
        for spec in specs:
            r = AuthorityResult(name=spec.name, ok=True)
            try:
                for row in fetch_authority(spec, http=http):
                    up = upsert_program(conn, row, now=now_iso, dry_run=dry_run)
                    if up.action == "added":
                        r.rows_added += 1
                    elif up.action == "updated":
                        r.rows_updated += 1
                    elif up.action == "unchanged":
                        r.rows_unchanged += 1
                    else:
                        r.rows_rejected += 1
                        _LOG.warning("rejected id=%s reason=%s", up.unified_id, up.reject_reason)
                if not dry_run:
                    conn.commit()
            except Exception as exc:  # per-authority isolation (§4)
                conn.rollback()
                r.ok = False
                r.error = f"{type(exc).__name__}: {exc}"
                _LOG.exception("authority failed name=%s", spec.name)
            results.append(r)
            total_add += r.rows_added
            total_upd += r.rows_updated
            total_unch += r.rows_unchanged

    conn.close()
    completed_at = datetime.now(UTC).isoformat()
    duration = time.monotonic() - started

    metrics = IngestMetrics(
        tier=tier,
        started_at=started_at,
        completed_at=completed_at,
        authorities_ok=sum(1 for r in results if r.ok),
        authorities_fail=sum(1 for r in results if not r.ok),
        rows_added=total_add,
        rows_updated=total_upd,
        rows_unchanged=total_unch,
        duration_s=duration,
        sha=os.environ.get("SENTRY_RELEASE") or os.environ.get("GITHUB_SHA"),
        authorities=results,
    )
    return metrics


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def emit_metrics(metrics: IngestMetrics) -> None:
    """Emit §8 structured-log line on stdout AND append to ingest_log.jsonl."""
    line = metrics.to_log_line()
    print(json.dumps(line, ensure_ascii=False))

    try:
        INGEST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with INGEST_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as exc:
        _LOG.warning("ingest_log append failed path=%s err=%s", INGEST_LOG_PATH, exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Tiered ingest driver for jpintel-mcp.")
    parser.add_argument("tier", choices=["daily", "weekly", "monthly"])
    parser.add_argument("--authority", default=None, help="limit to a single authority name")
    parser.add_argument("--month-slot", type=int, default=None,
                        help="monthly: municipality rotation slot (0..3)")
    parser.add_argument("--dry-run", action="store_true", help="no DB writes")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.month_slot is not None:
        os.environ["JPINTEL_MONTH_SLOT"] = str(args.month_slot)

    if not DB_PATH.exists():
        _LOG.error("DB not found at %s (are you running on the Fly machine?)", DB_PATH)
        return 2

    try:
        metrics = run_tier(args.tier, authority_filter=args.authority, dry_run=args.dry_run)
    except SystemExit:
        raise
    except Exception:
        _LOG.exception("ingest_tier driver crashed")
        return 3

    emit_metrics(metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
