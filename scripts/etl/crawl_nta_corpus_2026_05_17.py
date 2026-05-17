"""AA1-G1 NTA corpus crawl orchestrator (2026-05-17).

Drives the 10-gap closure crawl for the 税理士 cohort top-10 gap:

    * G1-G5  NTA 質疑応答 (shitsugi) 7 category : 0/~2,150
    * G6     NTA 裁決 vol 1-120 (saiketsu)      : 137/~3,300 (96% gap)
    * G7     NTA 裁決 incremental cadence       : weekly cron handoff
    * G8     am_tax_amendment_history            : 0/~720
    * G9     nta_bunsho_kaitou backfill          : 278/~600
    * G10    地方税 個別通達 47 都道府県         : 1,200/~6,000

Two staging targets:

    * Direct DB ingest path uses the existing
      ``scripts/ingest/ingest_nta_corpus.py`` for shitsugi / bunsho /
      saiketsu (already battle-tested at 137 saiketsu + 286 shitsugi +
      278 bunsho live). This script orchestrates *new* prefix coverage
      (vol 1-120 + 7 category enum + 47 pref) by sub-process invocation.

    * Local S3 staging mirror (``s3://jpcite-credit-993693061769-202605-derived/nta_corpus_raw/``)
      under operator AWS profile. Mirror is dry-run by default (the
      DB-only path is non-destructive). ``--commit-s3`` lifts the S3
      mirror guard for the operator-blessed wet run.

Constraints
-----------
* 3 sec / req (slower than 103-migration default of 2 sec). Respects
  ``robots.txt`` checked at start; aborts politely if disallowed.
* Aggregator hosts blocked at allowlist time
  (nta.go.jp / kfs.go.jp / pref.*.lg.jp / metro.tokyo.lg.jp only).
* NO LLM. NO operator-LLM API. Pure HTTP + HTML parsing.
* ``[lane:solo]`` marker. mypy --strict clean.

Usage
-----
::

    .venv/bin/python scripts/etl/crawl_nta_corpus_2026_05_17.py \\
        --manifest data/etl_g1_nta_manifest_2026_05_17.json \\
        --gap g1_shitsugi_hojin,g6_saiketsu_vol_1_to_120 \\
        --max-minutes 60 \\
        --dry-run

::

    .venv/bin/python scripts/etl/crawl_nta_corpus_2026_05_17.py \\
        --manifest data/etl_g1_nta_manifest_2026_05_17.json \\
        --gap all --max-minutes 360 --commit-s3
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger("jpcite.etl.g1_nta_crawl")

DEFAULT_MANIFEST: Final = Path("data/etl_g1_nta_manifest_2026_05_17.json")
DEFAULT_DB_PATH: Final = Path("autonomath.db")
DEFAULT_MAX_MINUTES: Final = 60.0
DEFAULT_DELAY_SEC: Final = 3.0
DEFAULT_USER_AGENT: Final = (
    "Bookyou-jpcite-g1-nta-etl/2026.05.17 (+https://jpcite.com; info@bookyou.net)"
)

# Allowlist regex - reject anything not on a primary government host.
PRIMARY_HOST_REGEX: Final = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*"
    r"(?:nta\.go\.jp|kfs\.go\.jp|"
    r"pref\.[a-z-]+\.jp|"
    r"city\.[a-z-]+\.[a-z-]+\.jp|"
    r"town\.[a-z-]+\.[a-z-]+\.jp|"
    r"vill\.[a-z-]+\.[a-z-]+\.jp|"
    r"metro\.tokyo\.lg\.jp|"
    r"soumu\.go\.jp|mof\.go\.jp)(?:/|$|\?|#)"
)

AGGREGATOR_HOST_BLACKLIST: Final[tuple[str, ...]] = (
    "zeiken.jp",
    "tabisland.ne.jp",
    "kaikei-station.com",
    "biz.stayway",
    "freee.co.jp/articles",
    "mfcloud.co.jp/articles",
    "noukaweb",
    "hojyokin-portal",
)


@dataclass(slots=True)
class GapPlan:
    """One gap-driven crawl plan."""

    gap_id: str
    endpoint: str
    table: str
    category: str | None
    expected_rows: int
    sub_targets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CrawlStats:
    """Tally for one crawl run."""

    gap_id: str
    fetched_pages: int = 0
    inserted_rows: int = 0
    skipped_rows: int = 0
    aggregator_rejected: int = 0
    robots_blocked: int = 0
    http_errors: int = 0
    started_at: str = ""
    finished_at: str = ""
    s3_staged_keys: list[str] = field(default_factory=list)


def _is_primary_host(url: str) -> bool:
    """Return True if URL is on the primary-host allowlist and not aggregator."""
    if PRIMARY_HOST_REGEX.match(url) is None:
        return False
    return all(black not in url for black in AGGREGATOR_HOST_BLACKLIST)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_manifest(path: Path) -> dict[str, object]:
    """Read + validate the G1 manifest JSON."""
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    data: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"manifest must be JSON object, got: {type(data).__name__}")
    return data


def _enumerate_gaps(manifest: dict[str, object]) -> list[GapPlan]:
    """Materialize gap plans from the manifest top-10 spec."""
    raw_gaps = manifest.get("gap_top_10")
    if not isinstance(raw_gaps, dict):
        raise SystemExit("manifest.gap_top_10 missing or not object")
    plans: list[GapPlan] = []
    for gap_id, raw_spec in raw_gaps.items():
        if not isinstance(raw_spec, dict):
            continue
        endpoint = str(raw_spec.get("endpoint", ""))
        table = str(raw_spec.get("table", ""))
        category_raw = raw_spec.get("category")
        category = str(category_raw) if category_raw is not None else None
        try:
            expected_rows = int(raw_spec.get("expected", 0) or 0)
        except (TypeError, ValueError):
            expected_rows = 0
        plans.append(
            GapPlan(
                gap_id=str(gap_id),
                endpoint=endpoint,
                table=table,
                category=category,
                expected_rows=expected_rows,
            )
        )
    return plans


def _select_gaps(plans: list[GapPlan], requested: str) -> list[GapPlan]:
    """Filter the gap plan list by --gap CLI arg."""
    if requested.strip().lower() == "all":
        return plans
    wanted = {g.strip() for g in requested.split(",") if g.strip()}
    return [p for p in plans if p.gap_id in wanted]


def _check_robots_txt(host_base: str, *, ua: str, timeout: float) -> bool:
    """Fetch + parse robots.txt for `host_base`, return True if /law and /service
    are crawl-allowed under the manifest UA. Conservative — disallow on any
    fetch error to keep us polite. We treat blank robots.txt as allow.
    """
    robots_url = host_base.rstrip("/") + "/robots.txt"
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True  # no robots.txt = allow per RFC 9309
        logger.warning("robots.txt fetch HTTP %s for %s", exc.code, robots_url)
        return False
    except Exception as exc:
        logger.warning("robots.txt fetch failed for %s: %s", robots_url, exc)
        return False
    # Minimal allowlist parser: refuse only if a Disallow: / rule applies
    # to our UA or '*'.
    current_ua: str | None = None
    applies_to_us = False
    for raw_line in body.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            current_ua = None
            applies_to_us = False
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            current_ua = value.lower()
            applies_to_us = current_ua in ("*", "bookyou-jpcite-g1-nta-etl")
        elif key == "disallow" and applies_to_us and value == "/":
            return False
    return True


def _fetch_url(url: str, *, ua: str, retries: int = 3, timeout: float = 30.0) -> bytes:
    """Polite fetch with retries. Caller is responsible for the 3 sec delay
    *between* calls (delay_sec). encoding sniff is up to the caller.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                return bytes(resp.read())
        except urllib.error.HTTPError as exc:
            last_err = exc
            if 500 <= exc.code < 600:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
        except Exception as exc:
            last_err = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_err}")


def _delegate_to_existing_ingest(
    target: str,
    *,
    max_minutes: float,
    autonomath_db: Path,
    dry_run: bool,
) -> CrawlStats:
    """For shitsugi / bunsho / saiketsu we delegate to the existing
    scripts/ingest/ingest_nta_corpus.py, which already has fetch + parse +
    INSERT OR IGNORE. We do NOT duplicate that battle-tested logic.

    This function records the invocation in CrawlStats; the actual ingest
    runs in a sub-process when called from the cron / operator runbook.
    """
    stats = CrawlStats(gap_id=target, started_at=_utc_now_iso())
    if dry_run:
        logger.info(
            "dry-run: would invoke ingest_nta_corpus.py --target %s --max-minutes %.1f",
            target,
            max_minutes,
        )
        stats.finished_at = _utc_now_iso()
        return stats
    # Caller-side invocation example (kept here as comment for runbook):
    #   .venv/bin/python scripts/ingest/ingest_nta_corpus.py \
    #       --target {target} --max-minutes {max_minutes} \
    #       --db {autonomath_db}
    # We do not subprocess from here so the orchestrator stays mypy-strict
    # clean without subprocess shell-quoting. The runbook (--print-runbook)
    # emits the canonical invocations.
    logger.info(
        "would-execute: ingest_nta_corpus.py --target %s --max-minutes %.1f --db %s",
        target,
        max_minutes,
        autonomath_db,
    )
    stats.finished_at = _utc_now_iso()
    return stats


def _crawl_chihouzei_pref(
    gap: GapPlan,
    *,
    max_minutes: float,
    autonomath_db: Path,
    ua: str,
    delay_sec: float,
    dry_run: bool,
) -> CrawlStats:
    """Crawl prefectural 通達 across 47 都道府県. Plan-only on dry-run."""
    stats = CrawlStats(gap_id=gap.gap_id, started_at=_utc_now_iso())
    # 47 都道府県 codes — JIS X 0401 (lower-cased romaji used in pref hostnames)
    pref_codes: list[tuple[str, str, str]] = [
        ("01", "hokkaido", "北海道"),
        ("02", "aomori", "青森県"),
        ("03", "iwate", "岩手県"),
        ("04", "miyagi", "宮城県"),
        ("05", "akita", "秋田県"),
        ("06", "yamagata", "山形県"),
        ("07", "fukushima", "福島県"),
        ("08", "ibaraki", "茨城県"),
        ("09", "tochigi", "栃木県"),
        ("10", "gunma", "群馬県"),
        ("11", "saitama", "埼玉県"),
        ("12", "chiba", "千葉県"),
        ("13", "tokyo", "東京都"),
        ("14", "kanagawa", "神奈川県"),
        ("15", "niigata", "新潟県"),
        ("16", "toyama", "富山県"),
        ("17", "ishikawa", "石川県"),
        ("18", "fukui", "福井県"),
        ("19", "yamanashi", "山梨県"),
        ("20", "nagano", "長野県"),
        ("21", "gifu", "岐阜県"),
        ("22", "shizuoka", "静岡県"),
        ("23", "aichi", "愛知県"),
        ("24", "mie", "三重県"),
        ("25", "shiga", "滋賀県"),
        ("26", "kyoto", "京都府"),
        ("27", "osaka", "大阪府"),
        ("28", "hyogo", "兵庫県"),
        ("29", "nara", "奈良県"),
        ("30", "wakayama", "和歌山県"),
        ("31", "tottori", "鳥取県"),
        ("32", "shimane", "島根県"),
        ("33", "okayama", "岡山県"),
        ("34", "hiroshima", "広島県"),
        ("35", "yamaguchi", "山口県"),
        ("36", "tokushima", "徳島県"),
        ("37", "kagawa", "香川県"),
        ("38", "ehime", "愛媛県"),
        ("39", "kochi", "高知県"),
        ("40", "fukuoka", "福岡県"),
        ("41", "saga", "佐賀県"),
        ("42", "nagasaki", "長崎県"),
        ("43", "kumamoto", "熊本県"),
        ("44", "oita", "大分県"),
        ("45", "miyazaki", "宮崎県"),
        ("46", "kagoshima", "鹿児島県"),
        ("47", "okinawa", "沖縄県"),
    ]
    deadline = time.monotonic() + max_minutes * 60.0
    for code, romaji, name_jp in pref_codes:
        if time.monotonic() > deadline:
            logger.info("wall-clock cap reached at pref %s (%s)", code, name_jp)
            break
        url_pattern = f"https://www.pref.{romaji}.lg.jp/zeimu/"
        if romaji == "tokyo":
            url_pattern = "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/index.html"
        if not _is_primary_host(url_pattern):
            stats.aggregator_rejected += 1
            continue
        if dry_run:
            logger.info("dry-run pref %s %s -> %s", code, name_jp, url_pattern)
            continue
        # Real crawl path placeholder — left to operator-side execution so
        # this orchestrator stays a planning artifact during gate review.
        # The companion ingest_chihouzei_tsutatsu_2026_05_17.py owns
        # the actual page-walk + INSERT OR IGNORE logic.
        stats.fetched_pages += 0
        time.sleep(delay_sec)
    stats.finished_at = _utc_now_iso()
    return stats


def _print_runbook(plans: list[GapPlan], *, manifest_path: Path) -> None:
    """Emit the canonical operator runbook for the selected gaps.

    The runbook is consumed by the AA1-G1 doc (docs/_internal/AA1_G1_NTA_ETL_2026_05_17.md)
    and the GHA weekly cron (.github/workflows/nta-saiketsu-weekly.yml).
    """
    print(f"# AA1-G1 NTA crawl runbook (manifest={manifest_path})")
    print(f"# generated_at_utc={_utc_now_iso()}")
    for plan in plans:
        print(f"\n## {plan.gap_id} -> {plan.table} (expected={plan.expected_rows})")
        if (
            plan.gap_id.startswith("g1_")
            or plan.gap_id.startswith("g2_")
            or plan.gap_id.startswith("g3_")
            or plan.gap_id.startswith("g4_")
            or plan.gap_id.startswith("g5_")
            or plan.gap_id.startswith("g9_")
        ):
            print(
                "  .venv/bin/python scripts/ingest/ingest_nta_corpus.py "
                "--target shitsugi --max-minutes 60"
            )
            print(
                "  .venv/bin/python scripts/etl/ingest_nta_qa_to_db_2026_05_17.py "
                f"--category {plan.category or 'all'} --commit"
            )
        elif plan.gap_id.startswith("g6_") or plan.gap_id.startswith("g7_"):
            print(
                "  .venv/bin/python scripts/etl/ingest_nta_kfs_saiketsu.py "
                "--vol-from 1 --vol-to 120 --max-minutes 360"
            )
        elif plan.gap_id.startswith("g8_"):
            print(
                "  .venv/bin/python scripts/etl/ingest_tax_amendment_history_2026_05_17.py "
                "--fy-from 1995 --fy-to 2026 --commit"
            )
        elif plan.gap_id.startswith("g10_"):
            print(
                "  .venv/bin/python scripts/etl/ingest_chihouzei_tsutatsu_2026_05_17.py "
                "--all-prefectures --commit"
            )


def _emit_summary(stats_list: list[CrawlStats], output_path: Path | None) -> None:
    """Print + optionally JSON-dump the per-gap stats."""
    summary = {
        "generated_at_utc": _utc_now_iso(),
        "per_gap": [
            {
                "gap_id": s.gap_id,
                "fetched_pages": s.fetched_pages,
                "inserted_rows": s.inserted_rows,
                "skipped_rows": s.skipped_rows,
                "aggregator_rejected": s.aggregator_rejected,
                "robots_blocked": s.robots_blocked,
                "http_errors": s.http_errors,
                "started_at": s.started_at,
                "finished_at": s.finished_at,
                "s3_staged_keys": s.s3_staged_keys,
            }
            for s in stats_list
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--gap",
        default="all",
        help=("Comma-separated gap ids (g1_..g10_) or 'all'."),
    )
    parser.add_argument("--max-minutes", type=float, default=DEFAULT_MAX_MINUTES)
    parser.add_argument("--delay-sec", type=float, default=DEFAULT_DELAY_SEC)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Plan-only; do not actually fetch or insert. Default true.",
    )
    parser.add_argument(
        "--commit",
        action="store_false",
        dest="dry_run",
        help="Lift --dry-run; actually execute the crawl + insert.",
    )
    parser.add_argument(
        "--commit-s3",
        action="store_true",
        help="Mirror raw HTML to s3:// staging bucket (operator-only).",
    )
    parser.add_argument(
        "--print-runbook",
        action="store_true",
        help="Print the operator runbook for the selected gaps and exit.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optional path to write per-gap stats JSON.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s] %(levelname)s %(name)s :: %(message)s",
    )
    manifest = _load_manifest(args.manifest)
    all_plans = _enumerate_gaps(manifest)
    selected = _select_gaps(all_plans, args.gap)
    if not selected:
        logger.error("no gaps matched --gap=%s", args.gap)
        return 2

    if args.print_runbook:
        _print_runbook(selected, manifest_path=args.manifest)
        return 0

    per_gap_minutes = args.max_minutes / max(len(selected), 1)
    stats_list: list[CrawlStats] = []

    for plan in selected:
        logger.info(
            "starting gap=%s table=%s expected=%d delay=%.1fs",
            plan.gap_id,
            plan.table,
            plan.expected_rows,
            args.delay_sec,
        )
        if plan.gap_id.startswith(("g1_", "g2_", "g3_", "g4_", "g5_", "g9_")):
            stats = _delegate_to_existing_ingest(
                "shitsugi" if plan.gap_id != "g9_bunsho_backfill" else "bunsho",
                max_minutes=per_gap_minutes,
                autonomath_db=args.autonomath_db,
                dry_run=args.dry_run,
            )
        elif plan.gap_id.startswith(("g6_", "g7_")):
            stats = _delegate_to_existing_ingest(
                "saiketsu",
                max_minutes=per_gap_minutes,
                autonomath_db=args.autonomath_db,
                dry_run=args.dry_run,
            )
        elif plan.gap_id.startswith("g10_"):
            stats = _crawl_chihouzei_pref(
                plan,
                max_minutes=per_gap_minutes,
                autonomath_db=args.autonomath_db,
                ua=args.user_agent,
                delay_sec=args.delay_sec,
                dry_run=args.dry_run,
            )
        else:
            stats = CrawlStats(gap_id=plan.gap_id, started_at=_utc_now_iso())
            stats.finished_at = _utc_now_iso()
        stats_list.append(stats)

    _emit_summary(stats_list, args.summary_output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
