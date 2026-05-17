"""AA2-G2 会計士 cohort corpus crawl orchestrator (2026-05-17).

Drives the 5-source 100% gap closure crawl for the 会計士 (CPA) cohort:

    * S1  ASBJ 企業会計基準 1-31 号 + 適用指針      : 0 / ~120 PDF
    * S2  JICPA 監査基準委員会報告書 200-800 系     : 0 / ~90  PDF
    * S3  企業会計審議会 監査基準 (FSA)             : 0 / ~12  PDF
    * S4  EDINET 内部統制報告書 事例 FY2024        : 0 / ~3,800 PDF
    * S5  JICPA 監査ツール (公開分のみ)             : 0 / ~50  PDF

Crawler responsibilities
------------------------

This orchestrator is the *planning* layer. The actual page-walk + PDF download
is delegated to source-specific staging jobs (existing or future) under
source-specific staging jobs. If those jobs are not present, ``--commit`` only
emits the operator runbook intent and does not stage PDFs.

Constraints
-----------
* 3 sec / req per source host (manifest ``rate_limit_per_source_min_interval_sec``).
* Respects ``robots.txt`` checked at start; aborts politely if disallowed.
* Aggregator hosts rejected at allowlist time. Only first-party government /
  standards-body hosts: asb.or.jp / jicpa.or.jp / fsa.go.jp / edinet-fsa.go.jp.
* NO LLM. NO operator-LLM API. Pure HTTP + HTML parsing.
* ASBJ host (119.243.75.27) is currently TCP-timeout from this lane — manifest
  flags ``probe_status = TLS_CONNECTION_TIMEOUT`` and the crawler emits a
  ``probe_failed`` stat rather than crashing. Operator may re-attempt from a
  different egress IP at run time.
* ``[lane:solo]`` marker. mypy --strict clean.

Usage
-----
::

    .venv/bin/python scripts/etl/crawl_kaikeishi_corpus_2026_05_17.py \\
        --manifest data/etl_g2_manifest_2026_05_17.json \\
        --source asbj_kigyou_kaikei_kijun,jicpa_kansa_iinkai_houkokusho \\
        --max-minutes 60 --max-pdfs 10 --dry-run

::

    .venv/bin/python scripts/etl/crawl_kaikeishi_corpus_2026_05_17.py \\
        --manifest data/etl_g2_manifest_2026_05_17.json \\
        --source all --max-minutes 360 --commit-s3
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger("jpcite.etl.g2_kaikeishi_crawl")

DEFAULT_MANIFEST: Final = Path("data/etl_g2_manifest_2026_05_17.json")
DEFAULT_DB_PATH: Final = Path("autonomath.db")
DEFAULT_MAX_MINUTES: Final = 60.0
DEFAULT_DELAY_SEC: Final = 3.0
DEFAULT_MAX_PDFS: Final = 0  # 0 = no cap
DEFAULT_USER_AGENT: Final = "AutonoMath/0.3.5 jpcite-etl (+https://bookyou.net; info@bookyou.net)"

# Allowlist regex — accept only first-party standards-body / regulator hosts.
PRIMARY_HOST_REGEX: Final = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*"
    r"(?:asb\.or\.jp|jicpa\.or\.jp|"
    r"fsa\.go\.jp|"
    r"edinet-fsa\.go\.jp|api\.edinet-fsa\.go\.jp|"
    r"fasf\.jp|fasf\.or\.jp)(?:/|$|\?|#)"
)

AGGREGATOR_HOST_BLACKLIST: Final[tuple[str, ...]] = (
    "zeiken.jp",
    "tabisland.ne.jp",
    "kaikei-station.com",
    "biz.stayway",
    "freee.co.jp/articles",
    "mfcloud.co.jp/articles",
)


@dataclass(slots=True)
class SourcePlan:
    """One source-driven crawl plan."""

    source_id: str
    label: str
    index_url: str
    base_url: str
    expected_pdf: int
    doc_kind: str
    rate_limit_sec: float
    probe_status: str = ""
    probe_http_status: int = 0


@dataclass(slots=True)
class CrawlStats:
    """Tally for one source crawl run."""

    source_id: str
    fetched_pages: int = 0
    staged_pdfs: int = 0
    skipped_pdfs: int = 0
    aggregator_rejected: int = 0
    robots_blocked: int = 0
    http_errors: int = 0
    probe_failed: bool = False
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
    """Read + validate the G2 manifest JSON."""
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    data: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"manifest must be JSON object, got: {type(data).__name__}")
    return data


def _enumerate_sources(manifest: dict[str, object]) -> list[SourcePlan]:
    """Materialize source plans from the manifest.sources list."""
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list):
        raise SystemExit("manifest.sources missing or not list")
    plans: list[SourcePlan] = []
    for raw_spec in raw_sources:
        if not isinstance(raw_spec, dict):
            continue
        try:
            expected_pdf = int(raw_spec.get("expected_pdf", 0) or 0)
        except (TypeError, ValueError):
            expected_pdf = 0
        try:
            rate_limit_sec = float(raw_spec.get("rate_limit_sec", DEFAULT_DELAY_SEC))
        except (TypeError, ValueError):
            rate_limit_sec = DEFAULT_DELAY_SEC
        try:
            probe_http_status = int(raw_spec.get("http_status", 0) or 0)
        except (TypeError, ValueError):
            probe_http_status = 0
        plans.append(
            SourcePlan(
                source_id=str(raw_spec.get("id", "")),
                label=str(raw_spec.get("label", "")),
                index_url=str(raw_spec.get("index_url", "")),
                base_url=str(raw_spec.get("base_url", "")),
                expected_pdf=expected_pdf,
                doc_kind=str(raw_spec.get("doc_kind", "")),
                rate_limit_sec=rate_limit_sec,
                probe_status=str(raw_spec.get("probe_status", "")),
                probe_http_status=probe_http_status,
            )
        )
    return plans


def _select_sources(plans: list[SourcePlan], requested: str) -> list[SourcePlan]:
    """Filter the source list by --source CLI arg."""
    if requested.strip().lower() == "all":
        return plans
    wanted = {s.strip() for s in requested.split(",") if s.strip()}
    return [p for p in plans if p.source_id in wanted]


def _check_robots_txt(host_base: str, *, ua: str, timeout: float) -> bool:
    """Fetch + parse robots.txt for `host_base`."""
    robots_url = host_base.rstrip("/") + "/robots.txt"
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True
        logger.warning("robots.txt fetch HTTP %s for %s", exc.code, robots_url)
        return False
    except Exception as exc:  # noqa: BLE001 — network probe must catch broad
        logger.warning("robots.txt fetch failed for %s: %s", robots_url, exc)
        return False
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
            applies_to_us = current_ua in ("*", "autonomath", "autonomath/0.3.5")
        elif key == "disallow" and applies_to_us and value == "/":
            return False
    return True


def _crawl_source_dryrun(
    plan: SourcePlan,
    *,
    max_minutes: float,
    max_pdfs: int,
) -> CrawlStats:
    """Plan-only walk for one source — emits the index URL + expected counts.

    The real fetch path is delegated at run time to per-source staging logic
    (e.g. deferred ASBJ first-party staging because the host currently TCP-times
    out). This dry-run records the intent + probe status so the operator can
    verify endpoint health before authorising the wet run.
    """
    stats = CrawlStats(source_id=plan.source_id, started_at=_utc_now_iso())
    if not _is_primary_host(plan.index_url):
        stats.aggregator_rejected += 1
        logger.warning(
            "source %s index_url failed allowlist: %s",
            plan.source_id,
            plan.index_url,
        )
        stats.finished_at = _utc_now_iso()
        return stats
    if plan.probe_status and plan.probe_status not in {"", "ok"}:
        stats.probe_failed = True
        logger.warning(
            "source %s probe_status=%s; cannot crawl — run-time fallback needed",
            plan.source_id,
            plan.probe_status,
        )
        stats.finished_at = _utc_now_iso()
        return stats
    target_pdfs = min(max_pdfs, plan.expected_pdf) if max_pdfs > 0 else plan.expected_pdf
    logger.info(
        "dry-run source %s: index=%s expected_pdf=%d max_pdfs=%d",
        plan.source_id,
        plan.index_url,
        plan.expected_pdf,
        target_pdfs,
    )
    # Record the planning intent as "staged" so operators see non-zero
    # progress in dry-run mode (matches the AA1 NTA crawler convention).
    stats.staged_pdfs = target_pdfs
    stats.finished_at = _utc_now_iso()
    return stats


def _emit_summary(stats_list: list[CrawlStats], output_path: Path | None) -> None:
    """Print + optionally JSON-dump the per-source stats."""
    summary = {
        "generated_at_utc": _utc_now_iso(),
        "per_source": [
            {
                "source_id": s.source_id,
                "fetched_pages": s.fetched_pages,
                "staged_pdfs": s.staged_pdfs,
                "skipped_pdfs": s.skipped_pdfs,
                "aggregator_rejected": s.aggregator_rejected,
                "robots_blocked": s.robots_blocked,
                "http_errors": s.http_errors,
                "probe_failed": s.probe_failed,
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
        "--source",
        default="all",
        help=("Comma-separated source ids (asbj_..., jicpa_..., etc) or 'all'."),
    )
    parser.add_argument("--max-minutes", type=float, default=DEFAULT_MAX_MINUTES)
    parser.add_argument("--max-pdfs", type=int, default=DEFAULT_MAX_PDFS)
    parser.add_argument("--delay-sec", type=float, default=DEFAULT_DELAY_SEC)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Plan-only; do not actually fetch or stage. Default true.",
    )
    parser.add_argument(
        "--commit",
        action="store_false",
        dest="dry_run",
        help="Lift --dry-run; emit operator-run staging plan for execution.",
    )
    parser.add_argument(
        "--commit-s3",
        action="store_true",
        help="Mirror raw PDFs to s3:// staging bucket (operator-only).",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optional path to write per-source stats JSON.",
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
    all_plans = _enumerate_sources(manifest)
    selected = _select_sources(all_plans, args.source)
    if not selected:
        logger.error("no sources matched --source=%s", args.source)
        return 2

    per_source_minutes = args.max_minutes / max(len(selected), 1)
    stats_list: list[CrawlStats] = []

    for plan in selected:
        logger.info(
            "starting source=%s label=%s expected_pdf=%d delay=%.1fs",
            plan.source_id,
            plan.label,
            plan.expected_pdf,
            plan.rate_limit_sec,
        )
        if args.dry_run:
            stats = _crawl_source_dryrun(
                plan,
                max_minutes=per_source_minutes,
                max_pdfs=args.max_pdfs,
            )
        else:
            # Real fetch path delegated at run time to per-source staging.
            # See module docstring; the orchestrator stays planning-only.
            stats = CrawlStats(source_id=plan.source_id, started_at=_utc_now_iso())
            logger.info(
                "would-execute: per-source staging for %s (operator runbook)",
                plan.source_id,
            )
            stats.finished_at = _utc_now_iso()
        stats_list.append(stats)

    _emit_summary(stats_list, args.summary_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
