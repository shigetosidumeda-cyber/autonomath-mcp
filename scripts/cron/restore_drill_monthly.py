#!/usr/bin/env python3
"""Monthly R2 backup restore drill (DEEP-62).

Runs once a month on the 15th at 03:00 JST via GitHub Actions
(`.github/workflows/restore-drill-monthly.yml`). Each invocation:

  1. Lists R2 keys under `autonomath/` and `jpintel/` prefixes.
  2. Picks one prefix by month parity: even=autonomath, odd=jpintel
     (alternating prevents both 9.4 GB downloads in the same month).
  3. Filters out backups <3 days old (hot tier) so we sample COLD generations.
  4. `random.choice()` to pick one .db.gz key uniformly.
  5. Downloads .db.gz from R2 to a tmp dir; times the download.
  6. gunzips to .db; times the gunzip.
  7. `PRAGMA integrity_check` — page-level corruption detector.
  8. `PRAGMA foreign_key_check` — referential integrity check.
  9. Top-10 table COUNT(*) drift check vs `data/restore_drill_expected.json`.
 10. Inserts one row into `jpintel.db.restore_drill_log` (mig 190).
 11. Cleans up the tmp dir (rmtree); never leaves 9.4 GB on disk.

Constraints
-----------
*   LLM call: 0. Pure python stdlib + sqlite3 + `_r2_client.py` (rclone).
*   R2 mutations: 0. read-only `download` / `list_keys` only — never delete,
    never upload from this script. The drill must NEVER touch the original
    backups; corrupt detection is observation-only.
*   /tmp space: ~10 GB peak when sampling autonomath (3 GB .db.gz + 9.4 GB .db).
    GHA `ubuntu-latest` provides ~14 GB free on /, sufficient. The runner
    is recycled after each job so disk hygiene at exit is best-effort.
*   Idempotent re-runs: safe; each run inserts a fresh row keyed by
    (drill_date, backup_db_kind, backup_key) — not unique, runs are append-only.

Required env: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
              R2_BUCKET (or JPINTEL_BACKUP_BUCKET).
Optional env: JPINTEL_DB_PATH (default /data/jpintel.db),
              AUTONOMATH_BACKUP_PREFIX (default autonomath/),
              JPINTEL_BACKUP_PREFIX (default jpintel/),
              RESTORE_DRILL_TMP_DIR (default $TMPDIR or /tmp),
              RESTORE_DRILL_EXPECTED_JSON (default
                data/restore_drill_expected.json).

Exit codes: 0 ok / 1 config / 2 R2 list/download / 3 integrity RED /
            4 db insert / 5 unexpected.

The cron writes a `RESTORE_DRILL_RED` sentinel to stderr on integrity
failure; the GHA workflow's `if: failure()` step picks it up and triggers
SES alert via the existing ops mailer.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cron._r2_client import R2ConfigError, download, list_keys  # type: ignore  # noqa: E402

_LOG = logging.getLogger("jpintel.cron.restore_drill")

# Top 10 tables sampled for COUNT(*) drift check. The expected ranges are
# loaded from RESTORE_DRILL_EXPECTED_JSON; if the file is missing, the drill
# still runs (status='skip').
_TOP10_AUTONOMATH = [
    "am_entities",
    "am_entity_facts",
    "am_relation",
    "am_alias",
    "am_amendment_snapshot",
    "am_application_round",
    "am_law_article",
    "am_enforcement_detail",
    "am_amount_condition",
    "am_industry_jsic",
]
_TOP10_JPINTEL = [
    "programs",
    "case_studies",
    "loan_programs",
    "enforcement_cases",
    "laws",
    "tax_rulesets",
    "court_decisions",
    "bids",
    "invoice_registrants",
    "exclusion_rules",
]


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _today_jst_str() -> str:
    """JST date string for drill_date column (YYYY-MM-DD)."""
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).strftime("%Y-%m-%d")


def _pick_kind(now: datetime) -> str:
    """Even month -> autonomath; odd month -> jpintel."""
    return "autonomath" if now.month % 2 == 0 else "jpintel"


def _candidate_keys(
    prefix: str, *, bucket: str | None, now: datetime, min_age_days: int = 3
) -> list[tuple[str, datetime, int]]:
    """List .db.gz keys under prefix with age >= min_age_days."""
    items = list_keys(prefix, bucket=bucket)
    cutoff = now - timedelta(days=min_age_days)
    return [
        (key, mtime, size)
        for (key, mtime, size) in items
        if key.endswith(".db.gz") and mtime <= cutoff and size > 0
    ]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _gunzip(src: Path, dst: Path) -> None:
    """Streamed gunzip — handles 9.4 GB autonomath without RAM blow-up."""
    with gzip.open(src, "rb") as fin, dst.open("wb") as fout:
        shutil.copyfileobj(fin, fout, length=1 << 20)


def _integrity_check(db_path: Path) -> tuple[str, float]:
    """Run PRAGMA integrity_check; return (status, seconds)."""
    t0 = time.monotonic()
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        result = (row[0] or "").strip().lower() if row else ""
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("integrity_check_failed err=%s", exc)
        return ("corrupted", time.monotonic() - t0)
    status = "ok" if result == "ok" else "corrupted"
    return (status, time.monotonic() - t0)


def _fk_check(db_path: Path) -> tuple[str, float]:
    """Run PRAGMA foreign_key_check; return (status, seconds)."""
    t0 = time.monotonic()
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("fk_check_failed err=%s", exc)
        return ("violations", time.monotonic() - t0)
    status = "ok" if not rows else "violations"
    return (status, time.monotonic() - t0)


def _top10_count_diff(
    db_path: Path, kind: str, expected_json: Path
) -> tuple[str, dict[str, dict[str, int]]]:
    """Compare top-10 table COUNT(*) vs expected ±10%. Returns (status, detail)."""
    if not expected_json.is_file():
        return ("skip", {})
    try:
        expected = json.loads(expected_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ("skip", {})
    expected_for_kind = expected.get(kind, {})
    if not expected_for_kind:
        return ("skip", {})

    tables = _TOP10_AUTONOMATH if kind == "autonomath" else _TOP10_JPINTEL
    detail: dict[str, dict[str, int]] = {}
    drift = False
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            for tbl in tables:
                if tbl not in expected_for_kind:
                    continue
                exp = int(expected_for_kind[tbl])
                try:
                    actual = int(conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
                except sqlite3.Error:
                    # Missing table is itself a drift signal but not corruption.
                    detail[tbl] = {"expected": exp, "actual": -1}
                    drift = True
                    continue
                detail[tbl] = {"expected": exp, "actual": actual}
                if exp <= 0:
                    if actual != 0:
                        drift = True
                else:
                    lo = int(exp * 0.9)
                    hi = int(exp * 1.1)
                    if not (lo <= actual <= hi):
                        drift = True
    except sqlite3.Error:
        return ("skip", {})

    return ("drift" if drift else "ok", detail)


def _backup_age_days(mtime: datetime, now: datetime) -> int:
    delta = now - mtime
    return max(0, int(delta.total_seconds() // 86400))


def _insert_drill_row(
    db_path: Path,
    *,
    drill_date: str,
    backup_db_kind: str,
    backup_key: str,
    backup_sha256: str,
    backup_size_bytes: int,
    download_seconds: float,
    gunzip_seconds: float,
    integrity_check_seconds: float,
    fk_check_seconds: float,
    integrity_status: str,
    fk_status: str,
    rto_total_seconds: float,
    sampled_age_days: int,
    top10_count_status: str,
    top10_count_detail: dict[str, dict[str, int]],
    notes: str | None,
) -> None:
    """Insert one drill row into jpintel.db.restore_drill_log (mig 190)."""
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute(
            """
            INSERT INTO restore_drill_log (
              drill_date, backup_db_kind, backup_key, backup_sha256,
              backup_size_bytes, download_seconds, gunzip_seconds,
              integrity_check_seconds, fk_check_seconds, integrity_status,
              fk_status, rto_total_seconds, sampled_age_days,
              top10_count_status, top10_count_detail, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                drill_date,
                backup_db_kind,
                backup_key,
                backup_sha256,
                backup_size_bytes,
                download_seconds,
                gunzip_seconds,
                integrity_check_seconds,
                fk_check_seconds,
                integrity_status,
                fk_status,
                rto_total_seconds,
                sampled_age_days,
                top10_count_status,
                json.dumps(top10_count_detail, ensure_ascii=False) if top10_count_detail else None,
                notes,
            ),
        )
    finally:
        conn.close()


def run_drill(
    *,
    jpintel_db: Path,
    bucket: str | None,
    autonomath_prefix: str,
    jpintel_prefix: str,
    tmp_dir: Path,
    expected_json: Path,
    rng: random.Random,
    forced_kind: str | None = None,
) -> dict[str, Any]:
    """Execute one drill cycle. Returns the inserted row payload as dict."""
    now = _now_utc()
    kind = forced_kind or _pick_kind(now)
    prefix = autonomath_prefix if kind == "autonomath" else jpintel_prefix
    _LOG.info(
        "drill_start kind=%s prefix=%s tmp=%s expected=%s",
        kind,
        prefix,
        tmp_dir,
        expected_json,
    )

    # 1. List + filter candidates
    try:
        candidates = _candidate_keys(prefix, bucket=bucket, now=now)
    except R2ConfigError as exc:
        _LOG.error("r2_config_error err=%s", exc)
        raise
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("r2_list_failed err=%s", exc)
        raise

    if not candidates:
        # No cold backups exist for this kind this month — record a skip row.
        _LOG.warning("no_candidates kind=%s prefix=%s", kind, prefix)
        # Insert a placeholder row so the drill is still observable.
        _insert_drill_row(
            jpintel_db,
            drill_date=_today_jst_str(),
            backup_db_kind=kind,
            backup_key="",
            backup_sha256="",
            backup_size_bytes=0,
            download_seconds=0.0,
            gunzip_seconds=0.0,
            integrity_check_seconds=0.0,
            fk_check_seconds=0.0,
            integrity_status="ok",
            fk_status="ok",
            rto_total_seconds=0.0,
            sampled_age_days=0,
            top10_count_status="skip",
            top10_count_detail={},
            notes="no candidates: prefix empty or all backups <3 days old",
        )
        return {"kind": kind, "status": "no_candidates"}

    # 2. Random sample
    chosen_key, chosen_mtime, chosen_size = rng.choice(candidates)
    age_days = _backup_age_days(chosen_mtime, now)
    _LOG.info(
        "drill_sampled key=%s size=%d age_days=%d (of %d candidates)",
        chosen_key,
        chosen_size,
        age_days,
        len(candidates),
    )

    # 3. Download
    tmp_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"restore_drill_{kind}_", dir=tmp_dir))
    gz_local = work_dir / Path(chosen_key).name
    db_local = work_dir / gz_local.stem  # strips .gz

    integrity_status = "ok"
    fk_status = "ok"
    top10_status = "skip"
    top10_detail: dict[str, dict[str, int]] = {}
    notes: str | None = None
    download_seconds = 0.0
    gunzip_seconds = 0.0
    int_seconds = 0.0
    fk_seconds = 0.0
    backup_sha = ""
    rto_start = time.monotonic()

    try:
        t_dl = time.monotonic()
        download(chosen_key, gz_local, bucket=bucket)
        download_seconds = time.monotonic() - t_dl

        # 4. SHA256 of gz (canonical fingerprint of the R2 object).
        backup_sha = _sha256_file(gz_local)

        # 5. Gunzip
        t_gz = time.monotonic()
        _gunzip(gz_local, db_local)
        gunzip_seconds = time.monotonic() - t_gz

        # 6. PRAGMA integrity_check
        integrity_status, int_seconds = _integrity_check(db_local)

        # 7. PRAGMA foreign_key_check (run regardless of integrity status —
        #    diagnostic info matters even on a corrupted page).
        fk_status, fk_seconds = _fk_check(db_local)

        # 8. Top-10 row count diff
        top10_status, top10_detail = _top10_count_diff(db_local, kind, expected_json)

        # Cap notes for any extra context.
        if integrity_status == "corrupted":
            notes = "RESTORE_DRILL_RED: integrity_check != ok"
        elif fk_status == "violations":
            notes = "RESTORE_DRILL_RED: foreign_key_check found violations"
        elif top10_status == "drift":
            notes = "row count drift detected (see top10_count_detail)"

    finally:
        # 9. Cleanup tmp dir always — never leave 9.4 GB behind.
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("tmp_cleanup_failed dir=%s err=%s", work_dir, exc)

    rto_total_seconds = time.monotonic() - rto_start

    # 10. Insert audit row
    drill_date = _today_jst_str()
    _insert_drill_row(
        jpintel_db,
        drill_date=drill_date,
        backup_db_kind=kind,
        backup_key=chosen_key,
        backup_sha256=backup_sha,
        backup_size_bytes=chosen_size,
        download_seconds=download_seconds,
        gunzip_seconds=gunzip_seconds,
        integrity_check_seconds=int_seconds,
        fk_check_seconds=fk_seconds,
        integrity_status=integrity_status,
        fk_status=fk_status,
        rto_total_seconds=rto_total_seconds,
        sampled_age_days=age_days,
        top10_count_status=top10_status,
        top10_count_detail=top10_detail,
        notes=notes,
    )

    payload = {
        "drill_date": drill_date,
        "backup_db_kind": kind,
        "backup_key": chosen_key,
        "backup_sha256": backup_sha,
        "backup_size_bytes": chosen_size,
        "download_seconds": round(download_seconds, 3),
        "gunzip_seconds": round(gunzip_seconds, 3),
        "integrity_check_seconds": round(int_seconds, 3),
        "fk_check_seconds": round(fk_seconds, 3),
        "integrity_status": integrity_status,
        "fk_status": fk_status,
        "rto_total_seconds": round(rto_total_seconds, 3),
        "sampled_age_days": age_days,
        "top10_count_status": top10_status,
        "top10_count_detail": top10_detail,
        "notes": notes,
    }

    if integrity_status == "corrupted" or fk_status == "violations":
        # Sentinel for GHA `if: failure()` capture.
        print("RESTORE_DRILL_RED " + json.dumps(payload), file=sys.stderr)

    _LOG.info(
        "drill_done kind=%s integrity=%s fk=%s rto=%.1fs",
        kind,
        integrity_status,
        fk_status,
        rto_total_seconds,
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--jpintel-db",
        default=os.environ.get("JPINTEL_DB_PATH", "/data/jpintel.db"),
        help="Path to jpintel.db (audit log destination).",
    )
    p.add_argument(
        "--autonomath-prefix",
        default=os.environ.get("AUTONOMATH_BACKUP_PREFIX", "autonomath/"),
    )
    p.add_argument(
        "--jpintel-prefix",
        default=os.environ.get("JPINTEL_BACKUP_PREFIX", "jpintel/"),
    )
    p.add_argument(
        "--bucket",
        default=os.environ.get("R2_BUCKET") or os.environ.get("JPINTEL_BACKUP_BUCKET"),
    )
    p.add_argument(
        "--tmp-dir",
        default=os.environ.get("RESTORE_DRILL_TMP_DIR") or os.environ.get("TMPDIR") or "/tmp",  # nosec B108 - last-resort fallback after RESTORE_DRILL_TMP_DIR + $TMPDIR; per-run scratch only
    )
    p.add_argument(
        "--expected-json",
        default=os.environ.get("RESTORE_DRILL_EXPECTED_JSON")
        or str(_REPO / "data" / "restore_drill_expected.json"),
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for random.choice (for tests / reproducible drills).",
    )
    p.add_argument(
        "--force-kind",
        choices=["autonomath", "jpintel"],
        default=None,
        help="Override month-parity rotation (for tests).",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    rng = random.Random(args.seed) if args.seed is not None else random.SystemRandom()

    jpintel_db = Path(args.jpintel_db)
    if not jpintel_db.is_file():
        _LOG.error("jpintel_db_missing path=%s", jpintel_db)
        return 1

    try:
        payload = run_drill(
            jpintel_db=jpintel_db,
            bucket=args.bucket,
            autonomath_prefix=args.autonomath_prefix,
            jpintel_prefix=args.jpintel_prefix,
            tmp_dir=Path(args.tmp_dir),
            expected_json=Path(args.expected_json),
            rng=rng,
            forced_kind=args.force_kind,
        )
    except R2ConfigError as exc:
        _LOG.error("r2_config_error err=%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("drill_unexpected_failure err=%s", exc)
        return 5

    if payload.get("integrity_status") == "corrupted" or payload.get("fk_status") == "violations":
        return 3

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
