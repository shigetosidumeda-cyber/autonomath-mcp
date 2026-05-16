#!/usr/bin/env python3
"""Generate ``subsidy_application_timeline_v1`` packets (Wave 53 type #5 of 5).

業種 (JSIC major) × 都道府県 × 会計年度 ごとの 補助金申請カレンダー。
For each cohort cell we pre-render:

* the chronologically sorted set of program ``application_open_date`` /
  ``application_close_date`` / ``announced_date`` rounds,
* a per-month bucket histogram (Jan..Dec) of close-dates for quick glance,
* upcoming-soon (next 60 days from generated_at) round samples,
* `n_open` / `n_upcoming` / `n_recently_closed` counts.

Cohort
------

::

    cohort = (jsic_major × prefecture × fiscal_year)

Design ceiling 22 × 47 × 4 = 4,136 cells, observed typically ~2,000-3,000
non-empty. ``--limit`` caps for smoke runs.

CLI::

    python scripts/aws_credit_ops/generate_subsidy_timeline_packets.py \\
        --output-prefix out/packets/subsidy_application_timeline_v1/ \\
        --limit 50

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB (top-N truncation on round samples).
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

# PERF-23: orjson + os.write per-packet hot path. The
# entity_to_program lookup table and manifest writes stay on stdlib
# ``json`` because they are not on the per-packet loop.
from scripts.aws_credit_ops._packet_base import (
    _dumps_compact,
    _write_bytes_fast,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("generate_subsidy_timeline_packets")

SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
PACKAGE_KIND: Final[str] = "subsidy_application_timeline_v1"
MAX_PACKET_BYTES: Final[int] = 25 * 1024
PER_AXIS_RECORD_CAP: Final[int] = 10
DEFAULT_DB_PATH: Final[str] = "autonomath.db"
DEFAULT_JPINTEL_DB_PATH: Final[str] = "data/jpintel.db"
S3_PUT_USD_PER_1K: Final[float] = 0.005
UPCOMING_WINDOW_DAYS: Final[int] = 60
RECENTLY_CLOSED_WINDOW_DAYS: Final[int] = 30

DEFAULT_DISCLAIMER: Final[str] = (
    "本 subsidy application timeline packet は am_application_round と "
    "programs を業種 × 地域 × 会計年度 で集計した descriptive 指標です。"
    "実際の申請可否・締切は所管官庁の公示確認が必須 (税理士法 §52 / "
    "行政書士法 §1の2 boundaries)。"
)


@dataclass(frozen=True)
class PacketResult:
    cohort_id: str
    s3_key: str
    bytes_written: int
    total_rounds: int
    status: str


@dataclass
class RunManifest:
    started_at: str
    finished_at: str | None = None
    output_prefix: str = ""
    dry_run: bool = True
    total_cohorts: int = 0
    packets_written: int = 0
    packets_skipped_empty: int = 0
    bytes_total: int = 0
    s3_put_cost_usd_estimate: float = 0.0
    results: list[PacketResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_prefix": self.output_prefix,
            "dry_run": self.dry_run,
            "total_cohorts": self.total_cohorts,
            "packets_written": self.packets_written,
            "packets_skipped_empty": self.packets_skipped_empty,
            "bytes_total": self.bytes_total,
            "s3_put_cost_usd_estimate": round(self.s3_put_cost_usd_estimate, 4),
            "results_sample": [r.__dict__ for r in self.results[:50]],
        }


@dataclass(frozen=True)
class RoundRow:
    program_unified_id: str
    program_name: str
    jsic_major: str
    prefecture: str
    fiscal_year: str
    round_label: str
    status: str | None
    application_open_date: str | None
    application_close_date: str | None
    announced_date: str | None
    budget_yen: int | None
    source_url: str | None


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _today() -> dt.date:
    return datetime.now(tz=UTC).date()


def _fiscal_year_from_iso(value: str | None) -> str:
    if not isinstance(value, str) or len(value) < 7:
        return ""
    year_str = value[:4]
    month_str = value[5:7]
    if not (year_str.isdigit() and month_str.isdigit()):
        return ""
    year = int(year_str)
    month = int(month_str)
    fy = year - 1 if month < 4 else year
    return f"FY{fy}"


def _normalise(value: str | None, fallback: str = "UNKNOWN") -> str:
    if value is None:
        return fallback
    stripped = str(value).strip()
    if not stripped:
        return fallback
    return stripped


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def build_program_lookup(jpintel_conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not _table_exists(jpintel_conn, "programs"):
        return out
    sql = (
        "SELECT unified_id, primary_name, prefecture, "
        "       json_extract(a_to_j_coverage_json, '$.industry') "
        "  FROM programs WHERE excluded = 0"
    )
    with contextlib.suppress(sqlite3.Error):
        for row in jpintel_conn.execute(sql):
            uid = row[0]
            if not isinstance(uid, str):
                continue
            out[uid] = {
                "primary_name": str(row[1] or ""),
                "prefecture": str(row[2] or ""),
            }
    return out


def enumerate_rounds(
    autonomath_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection,
) -> Iterator[RoundRow]:
    """Iterate ``am_application_round`` joined to ``programs`` metadata."""

    if not _table_exists(autonomath_conn, "am_application_round"):
        return

    program_lookup = build_program_lookup(jpintel_conn)

    # Build entity_id -> unified_id mapping when am_entities carries the link.
    entity_to_program: dict[str, str] = {}
    if _table_exists(autonomath_conn, "am_entities"):
        with contextlib.suppress(sqlite3.Error):
            for row in autonomath_conn.execute(
                "SELECT canonical_id, "
                "       json_extract(raw_json, '$.unified_id') AS unified_id, "
                "       UPPER(COALESCE("
                "         json_extract(raw_json, '$.industry_jsic_major'), "
                "         SUBSTR(json_extract(raw_json, '$.industry_jsic_medium'), 1, 1), "
                "         'UNKNOWN'"
                "       )) AS jsic_major "
                "  FROM am_entities WHERE record_kind = 'program'"
            ):
                cid = row[0]
                uid = row[1]
                jm = row[2]
                if isinstance(cid, str):
                    entity_to_program[cid] = json.dumps(
                        {"unified_id": uid, "jsic_major": jm or "UNKNOWN"}
                    )

    sql = (
        "SELECT program_entity_id, round_label, status, "
        "       application_open_date, application_close_date, "
        "       announced_date, budget_yen, source_url "
        "  FROM am_application_round"
    )
    for row in autonomath_conn.execute(sql):
        cid = str(row["program_entity_id"] or "")
        entity_meta_raw = entity_to_program.get(cid)
        unified_id = ""
        jsic_major = "UNKNOWN"
        if entity_meta_raw:
            meta = json.loads(entity_meta_raw)
            unified_id = str(meta.get("unified_id") or "") or ""
            jsic_major = str(meta.get("jsic_major") or "UNKNOWN") or "UNKNOWN"
        program = program_lookup.get(unified_id, {})
        program_name = str(program.get("primary_name") or "")
        prefecture = _normalise(program.get("prefecture") or None)
        # Use announced_date or application_open_date for fiscal_year derivation.
        fy = _fiscal_year_from_iso(row["announced_date"] or row["application_open_date"])
        if not fy:
            fy = "UNKNOWN_FY"
        yield RoundRow(
            program_unified_id=unified_id,
            program_name=program_name,
            jsic_major=jsic_major,
            prefecture=prefecture,
            fiscal_year=fy,
            round_label=str(row["round_label"] or ""),
            status=row["status"],
            application_open_date=row["application_open_date"],
            application_close_date=row["application_close_date"],
            announced_date=row["announced_date"],
            budget_yen=(int(row["budget_yen"]) if row["budget_yen"] is not None else None),
            source_url=row["source_url"],
        )


def aggregate_cohorts(
    rounds: Iterator[RoundRow],
    *,
    limit: int | None,
    today: dt.date,
) -> Iterator[dict[str, Any]]:
    agg: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in rounds:
        key = (r.jsic_major, r.prefecture, r.fiscal_year)
        bucket = agg.setdefault(
            key,
            {
                "rounds": [],
                "by_close_month": dict.fromkeys(range(1, 13), 0),
                "n_open": 0,
                "n_upcoming": 0,
                "n_recently_closed": 0,
                "freshest_close": None,
                "distinct_programs": set(),
            },
        )
        bucket["distinct_programs"].add(r.program_unified_id)
        if r.status == "open":
            bucket["n_open"] += 1
        close_date = r.application_close_date
        if isinstance(close_date, str) and len(close_date) >= 10:
            with contextlib.suppress(ValueError):
                close_dt = dt.date.fromisoformat(close_date[:10])
                bucket["by_close_month"][close_dt.month] += 1
                delta = (close_dt - today).days
                if 0 <= delta <= UPCOMING_WINDOW_DAYS:
                    bucket["n_upcoming"] += 1
                elif -RECENTLY_CLOSED_WINDOW_DAYS <= delta < 0:
                    bucket["n_recently_closed"] += 1
                cur_fresh = bucket["freshest_close"]
                if cur_fresh is None or close_date > str(cur_fresh):
                    bucket["freshest_close"] = close_date
        bucket["rounds"].append(
            {
                "program_unified_id": r.program_unified_id,
                "program_name": r.program_name,
                "round_label": r.round_label,
                "status": r.status,
                "application_open_date": r.application_open_date,
                "application_close_date": r.application_close_date,
                "announced_date": r.announced_date,
                "budget_yen": r.budget_yen,
                "source_url": r.source_url,
            }
        )

    for emitted, ((jsic, pref, fy), bucket) in enumerate(sorted(agg.items())):
        rounds_list = bucket["rounds"]
        rounds_list.sort(key=lambda d: d.get("application_close_date") or "9999-12-31")
        bucket["rounds"] = rounds_list[:PER_AXIS_RECORD_CAP]
        bucket["distinct_programs"] = len(bucket["distinct_programs"])
        bucket["jsic_major"] = jsic
        bucket["prefecture"] = pref
        bucket["fiscal_year"] = fy
        bucket["cohort_id"] = f"{jsic}.{pref}.{fy}"
        yield bucket
        if limit is not None and (emitted + 1) >= limit:
            return


def render_packet(bucket: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    cohort_id = bucket["cohort_id"]
    package_id = f"subsidy_application_timeline_v1:{cohort_id}"

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "申請可否・締切は所管官庁公示が一次情報。税理士・行政書士の"
                "確認が必須 (税理士法 §52 / 行政書士法 §1の2 boundaries)。"
            ),
        }
    ]
    rounds_list = list(bucket.get("rounds", []))
    if not rounds_list:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "このコホートで募集ラウンド観測なし — 「制度ゼロ」を意味"
                    "しません。一次官公庁ウェブ確認が必要"
                ),
            }
        )
    if bucket.get("freshest_close") is None:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "close_date 鮮度不明 — 一次官公庁公示の確認が必要",
            }
        )

    sources = [
        {
            "source_url": "https://www.meti.go.jp/policy/mono_info_service/mono/index.html",
            "source_fetched_at": None,
            "publisher": "METI 補助金検索 (canonical landing)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.maff.go.jp/j/supply/hozyo/index.html",
            "source_fetched_at": None,
            "publisher": "MAFF 補助金等情報",
            "license": "gov_standard",
        },
    ]

    by_close_month_raw = bucket.get("by_close_month", {})
    by_close_month_norm: dict[str, int] = {
        str(int(m)): int(v) for m, v in dict(by_close_month_raw).items()
    }

    envelope: dict[str, Any] = {
        "object_id": package_id,
        "object_type": "packet",
        "created_at": generated_at,
        "producer": PRODUCER,
        "request_time_llm_call_performed": False,
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id,
        "package_kind": PACKAGE_KIND,
        "generated_at": generated_at,
        "cohort_definition": {
            "cohort_id": cohort_id,
            "jsic_major": bucket["jsic_major"],
            "prefecture": bucket["prefecture"],
            "fiscal_year": bucket["fiscal_year"],
        },
        "metrics": {
            "n_open": int(bucket["n_open"]),
            "n_upcoming": int(bucket["n_upcoming"]),
            "n_recently_closed": int(bucket["n_recently_closed"]),
            "distinct_programs": int(bucket["distinct_programs"]),
            "by_close_month": by_close_month_norm,
        },
        "timeline_rounds": rounds_list,
        "freshest_close": bucket.get("freshest_close"),
        "sources": sources,
        "known_gaps": known_gaps,
        "jpcite_cost_jpy": 0,
        "disclaimer": DEFAULT_DISCLAIMER,
    }
    return envelope


def validate_jpcir_header(envelope: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(envelope.get("object_id"), str) or not envelope["object_id"]:
        errors.append("object_id missing")
    if envelope.get("object_type") != "packet":
        errors.append("object_type must be packet")
    if envelope.get("producer") != PRODUCER:
        errors.append("producer mismatch")
    if envelope.get("request_time_llm_call_performed") is not False:
        errors.append("request_time_llm_call_performed must be false")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    return (not errors, errors)


def _import_boto3() -> Any:  # pragma: no cover
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = "boto3 not installed"
        raise RuntimeError(msg) from exc
    return boto3


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    rest = uri[len("s3://") :]
    bucket, _slash, key = rest.partition("/")
    return bucket, key


def upload_packet(
    *,
    envelope: dict[str, Any],
    output_prefix: str,
    dry_run: bool,
    s3_client: Any | None,
    local_out_dir: Path,
) -> tuple[str, int]:
    # PERF-23 hot path: orjson + os.write, 1 packet/file Athena contract
    # preserved.
    cohort_id = envelope["cohort_definition"]["cohort_id"]
    body = _dumps_compact(envelope)
    bytes_written = len(body)
    if bytes_written > MAX_PACKET_BYTES:
        msg = f"packet {cohort_id} exceeds {MAX_PACKET_BYTES}: {bytes_written}"
        raise ValueError(msg)
    if output_prefix.startswith("s3://"):
        bucket, key_prefix = _parse_s3_uri(output_prefix)
        key = f"{key_prefix.rstrip('/')}/{cohort_id}.json"
        if dry_run or s3_client is None:
            local_path = local_out_dir / f"{cohort_id}.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes_fast(local_path, body)
            return key, bytes_written
        s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
        return key, bytes_written
    local_path = Path(output_prefix).expanduser() / f"{cohort_id}.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_fast(local_path, body)
    return str(local_path), bytes_written


def open_db_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists() or db_path.stat().st_size == 0:
        msg = f"database not found or empty: {db_path}"
        raise RuntimeError(msg)
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA query_only=1")
        conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def run(
    *,
    autonomath_db_path: Path,
    jpintel_db_path: Path,
    output_prefix: str,
    limit: int | None,
    dry_run: bool,
    local_out_dir: Path,
) -> RunManifest:
    manifest = RunManifest(started_at=_now_utc_iso(), output_prefix=output_prefix, dry_run=dry_run)
    s3_client: Any | None = None
    if output_prefix.startswith("s3://") and not dry_run:
        s3_client = _import_boto3().client("s3")

    autonomath_conn = open_db_ro(autonomath_db_path)
    jpintel_conn = open_db_ro(jpintel_db_path)
    try:
        rounds_iter = enumerate_rounds(autonomath_conn, jpintel_conn)
        cohort_iter = aggregate_cohorts(rounds_iter, limit=limit, today=_today())
        for bucket in cohort_iter:
            manifest.total_cohorts += 1
            generated_at = _now_utc_iso()
            envelope = render_packet(bucket, generated_at=generated_at)
            ok, errors = validate_jpcir_header(envelope)
            if not ok:
                logger.warning(
                    "schema validation failed %s: %s",
                    bucket["cohort_id"],
                    "; ".join(errors),
                )
                continue
            if not bucket.get("rounds"):
                manifest.packets_skipped_empty += 1
                continue
            key, written = upload_packet(
                envelope=envelope,
                output_prefix=output_prefix,
                dry_run=dry_run,
                s3_client=s3_client,
                local_out_dir=local_out_dir,
            )
            manifest.packets_written += 1
            manifest.bytes_total += written
            manifest.results.append(
                PacketResult(
                    cohort_id=bucket["cohort_id"],
                    s3_key=key,
                    bytes_written=written,
                    total_rounds=len(bucket["rounds"]),
                    status="dry_run" if dry_run else "written",
                )
            )
    finally:
        with contextlib.suppress(sqlite3.Error):
            autonomath_conn.close()
        with contextlib.suppress(sqlite3.Error):
            jpintel_conn.close()

    manifest.s3_put_cost_usd_estimate = (manifest.packets_written / 1000.0) * S3_PUT_USD_PER_1K
    manifest.finished_at = _now_utc_iso()
    return manifest


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Pre-generate subsidy_application_timeline_v1 packets for the "
            "(jsic_major × prefecture × fiscal_year) cohort cross-product."
        ),
    )
    p.add_argument("--output-prefix", required=True)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--jpintel-db", default=DEFAULT_JPINTEL_DB_PATH)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--local-out-dir", default="out/subsidy_application_timeline_v1")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--manifest-out", default=None)
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    dry_run = not args.commit
    if os.environ.get("DRY_RUN") == "0" and not args.commit:
        logger.warning("DRY_RUN=0 set but --commit missing — staying in dry-run.")
    autonomath_db_path = Path(args.db)
    jpintel_db_path = Path(args.jpintel_db)
    local_out_dir = Path(args.local_out_dir)
    local_out_dir.mkdir(parents=True, exist_ok=True)
    started_t = time.perf_counter()
    try:
        manifest = run(
            autonomath_db_path=autonomath_db_path,
            jpintel_db_path=jpintel_db_path,
            output_prefix=str(args.output_prefix),
            limit=int(args.limit) if args.limit is not None else None,
            dry_run=dry_run,
            local_out_dir=local_out_dir,
        )
    except RuntimeError as exc:
        logger.error("run failed: %s", exc)
        return 1

    manifest_path = (
        Path(args.manifest_out)
        if args.manifest_out is not None
        else local_out_dir / "run_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - started_t
    logger.info(
        "run done: cohorts=%d written=%d empty=%d bytes_total=%d "
        "s3_put_usd~=%.4f manifest=%s dry_run=%s elapsed=%.1fs",
        manifest.total_cohorts,
        manifest.packets_written,
        manifest.packets_skipped_empty,
        manifest.bytes_total,
        manifest.s3_put_cost_usd_estimate,
        manifest_path,
        manifest.dry_run,
        elapsed,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
