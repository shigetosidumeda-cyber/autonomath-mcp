"""AA1-G1 Textract OCR submitter for older NTA 裁決 + 通達 PDFs (2026-05-17).

Older 裁決 (vol 1-42, before HTML became canonical) and a subset of
prefectural 通達 are published as scanned PDFs. To lift the saiketsu
backlog from 137 / ~3,300 toward the canonical 3,163 published cases,
~3,000 older PDFs must run through Textract (TABLES + FORMS) before
their structured fields can land in ``nta_saiketsu`` / ``am_chihouzei_tsutatsu``.

Cost contract
-------------
Textract TABLES + FORMS = $0.05 / page.

  worst_case = 3,000 PDF x 30 pages x $0.05 = $4,500
  realistic  = ~$1,500 (median older 裁決 = 15-20 pages)

This stays well below the $19,490 hard-stop NeverReach band (memory:
`feedback_aws_canary_hard_stop_5_line_defense`). The 4-tier defence
(CW $14K / Budget $17K / slowdown $18.3K / CW $18.7K Lambda) remains
primary; this script trusts that envelope but additionally caps its
own daily budget at $700 by default.

Geography
---------
Textract is offered in ``ap-southeast-1`` but **not** ``ap-northeast-1``
(memory: established in Lane C burn ramp). Reuse the existing Singapore
staging bucket ``jpcite-credit-textract-apse1-202605`` whose IAM role +
SSE-KMS + budget envelope already cover this run.

Constraints
-----------
* AWS profile ``bookyou-recovery`` (memory: secret store separation).
* NO LLM. Textract is OCR / structured extraction, not inference.
* ``robots.txt`` respected at PDF fetch time. PDFs are primary-source
  NTA / KFS / 都道府県 公開資料 only (PDL v1.0 / gov_standard).
* DRY_RUN default. ``--commit`` lifts the guard.
* ``[lane:solo]``.

Usage
-----
::

    .venv/bin/python scripts/aws_credit_ops/textract_nta_bulk_2026_05_17.py \\
        --manifest data/etl_g1_nta_manifest_2026_05_17.json \\
        --pdf-source nta_saiketsu \\
        --max-pdfs 100 \\
        --parallel 4 \\
        --dry-run

    .venv/bin/python scripts/aws_credit_ops/textract_nta_bulk_2026_05_17.py \\
        --manifest data/etl_g1_nta_manifest_2026_05_17.json \\
        --pdf-source nta_saiketsu --max-pdfs 1500 --parallel 8 --commit
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger("jpcite.aws.g1_textract")

DEFAULT_MANIFEST: Final = Path("data/etl_g1_nta_manifest_2026_05_17.json")
DEFAULT_PROFILE: Final = "bookyou-recovery"
DEFAULT_TEXTRACT_REGION: Final = "ap-southeast-1"
DEFAULT_STAGE_BUCKET: Final = "jpcite-credit-textract-apse1-202605"
DEFAULT_OUTPUT_BUCKET: Final = "jpcite-credit-993693061769-202605-derived"
DEFAULT_OUTPUT_PREFIX: Final = "nta_corpus_raw/2026-05-17/textract/"
DEFAULT_PARALLEL: Final = 4
DEFAULT_MAX_PDFS: Final = 100
DEFAULT_PER_PAGE_USD: Final = 0.05
DEFAULT_DAILY_BUDGET_USD: Final = 700.0
DEFAULT_DELAY_SEC: Final = 1.0
DEFAULT_USER_AGENT: Final = (
    "Bookyou-jpcite-g1-textract/2026.05.17 (+https://jpcite.com; info@bookyou.net)"
)
DEFAULT_HARD_STOP_USD: Final = 19490.0


@dataclass(slots=True)
class PdfJob:
    """One PDF unit slated for Textract."""

    source_url: str
    sha256_hex: str
    expected_pages: int
    s3_in_key: str | None = None
    s3_out_prefix: str | None = None
    textract_job_id: str | None = None
    status: str = "PENDING"
    cost_usd_estimated: float = 0.0


@dataclass(slots=True)
class RunLedger:
    """Append-only ledger row for the bulk run."""

    run_id: str
    started_at_utc: str
    finished_at_utc: str = ""
    total_pdfs_submitted: int = 0
    total_pages_estimated: int = 0
    total_cost_usd_estimated: float = 0.0
    jobs: list[PdfJob] = field(default_factory=list)
    dry_run: bool = True


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    data: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("manifest must be JSON object")
    return data


def _enumerate_pdf_candidates(
    manifest: dict[str, object],
    *,
    pdf_source: str,
    max_pdfs: int,
) -> list[PdfJob]:
    """Plan-side PDF enumerator.

    The real implementation would query autonomath.db for
    ``nta_saiketsu.source_url LIKE '%.pdf'`` style rows. This planning
    phase emits a synthetic candidate list driven by the manifest's
    ``estimated_pdf_count`` so the operator runbook + cost projection
    are correct.
    """
    ocr_spec_raw = manifest.get("textract_ocr")
    if not isinstance(ocr_spec_raw, dict):
        raise SystemExit("manifest.textract_ocr missing")
    estimated_pages = int(ocr_spec_raw.get("estimated_pages_per_pdf", 30) or 30)
    candidates: list[PdfJob] = []
    for idx in range(min(max_pdfs, 3000)):
        synthetic_hex = f"{pdf_source[:8]:_<8}{idx:024d}"[:64]
        candidates.append(
            PdfJob(
                source_url=(f"https://www.kfs.go.jp/service/JP/scan_legacy/{idx:04d}.pdf"),
                sha256_hex=synthetic_hex,
                expected_pages=estimated_pages,
                cost_usd_estimated=estimated_pages * DEFAULT_PER_PAGE_USD,
            )
        )
    return candidates


def _project_cost(jobs: list[PdfJob]) -> tuple[int, float]:
    total_pages = sum(j.expected_pages for j in jobs)
    total_cost = total_pages * DEFAULT_PER_PAGE_USD
    return total_pages, total_cost


def _stage_pdf_to_s3_dry(
    job: PdfJob,
    *,
    bucket: str,
    output_prefix: str,
) -> PdfJob:
    """Dry-run path: assign computed S3 keys without uploading."""
    job.s3_in_key = f"in/{job.sha256_hex[:2]}/{job.sha256_hex}.pdf"
    job.s3_out_prefix = f"{output_prefix}{job.sha256_hex[:2]}/{job.sha256_hex}/"
    job.status = "STAGED_DRY"
    return job


def _submit_textract_dry(job: PdfJob) -> PdfJob:
    """Dry-run path: simulate Textract start_document_analysis."""
    job.textract_job_id = f"dry_run_{job.sha256_hex[:16]}"
    job.status = "TEXTRACT_DRY_SUBMITTED"
    return job


def _enforce_budget_guard(
    cumulative_cost: float,
    *,
    daily_cap: float,
    hard_stop: float,
) -> bool:
    """Return True if it's safe to submit one more job."""
    if cumulative_cost >= hard_stop:
        logger.error(
            "HARD STOP $%.0f reached at cumulative $%.2f",
            hard_stop,
            cumulative_cost,
        )
        return False
    if cumulative_cost >= daily_cap:
        logger.warning(
            "daily cap $%.0f reached at cumulative $%.2f — stopping politely",
            daily_cap,
            cumulative_cost,
        )
        return False
    return True


def _write_ledger(ledger: RunLedger, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": ledger.run_id,
        "started_at_utc": ledger.started_at_utc,
        "finished_at_utc": ledger.finished_at_utc,
        "dry_run": ledger.dry_run,
        "total_pdfs_submitted": ledger.total_pdfs_submitted,
        "total_pages_estimated": ledger.total_pages_estimated,
        "total_cost_usd_estimated": ledger.total_cost_usd_estimated,
        "jobs": [
            {
                "source_url": j.source_url,
                "sha256_hex": j.sha256_hex,
                "expected_pages": j.expected_pages,
                "s3_in_key": j.s3_in_key,
                "s3_out_prefix": j.s3_out_prefix,
                "textract_job_id": j.textract_job_id,
                "status": j.status,
                "cost_usd_estimated": j.cost_usd_estimated,
            }
            for j in ledger.jobs
        ],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--pdf-source",
        default="nta_saiketsu",
        choices=("nta_saiketsu", "am_chihouzei_tsutatsu", "nta_bunsho_kaitou"),
    )
    parser.add_argument("--max-pdfs", type=int, default=DEFAULT_MAX_PDFS)
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    parser.add_argument("--region", default=DEFAULT_TEXTRACT_REGION)
    parser.add_argument("--stage-bucket", default=DEFAULT_STAGE_BUCKET)
    parser.add_argument("--output-bucket", default=DEFAULT_OUTPUT_BUCKET)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--daily-cap", type=float, default=DEFAULT_DAILY_BUDGET_USD)
    parser.add_argument("--hard-stop", type=float, default=DEFAULT_HARD_STOP_USD)
    parser.add_argument(
        "--ledger-output",
        type=Path,
        default=Path("data/textract_nta_bulk_2026_05_17_ledger.json"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default true; plan-only.",
    )
    parser.add_argument(
        "--commit",
        action="store_false",
        dest="dry_run",
        help="Lift --dry-run; actually submit Textract jobs.",
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
    candidates = _enumerate_pdf_candidates(
        manifest, pdf_source=args.pdf_source, max_pdfs=args.max_pdfs
    )
    total_pages, projected_cost = _project_cost(candidates)
    logger.info(
        "candidates=%d pages=%d projected_cost_usd=%.2f daily_cap=%.0f hard_stop=%.0f",
        len(candidates),
        total_pages,
        projected_cost,
        args.daily_cap,
        args.hard_stop,
    )
    ledger = RunLedger(
        run_id=f"textract_nta_bulk_2026_05_17_{int(time.time())}",
        started_at_utc=_utc_now_iso(),
        dry_run=args.dry_run,
    )
    cumulative_cost = 0.0
    for job in candidates:
        if not _enforce_budget_guard(
            cumulative_cost,
            daily_cap=args.daily_cap,
            hard_stop=args.hard_stop,
        ):
            break
        if args.dry_run:
            job = _stage_pdf_to_s3_dry(
                job,
                bucket=args.stage_bucket,
                output_prefix=args.output_prefix,
            )
            job = _submit_textract_dry(job)
        else:
            # Live submission path intentionally left as a stub — operator
            # invokes the existing textract_bulk_submit_2026_05_17.py for
            # the actual side-effects so the AA1-G1 lane stays plan-only
            # during gate review. Same boto3 contract; same SSE-KMS bucket.
            logger.info("would-submit %s (pages=%d)", job.source_url, job.expected_pages)
            job.status = "WOULD_SUBMIT_LIVE"
        cumulative_cost += job.cost_usd_estimated
        ledger.jobs.append(job)
        ledger.total_pdfs_submitted += 1
        ledger.total_pages_estimated += job.expected_pages
        ledger.total_cost_usd_estimated = cumulative_cost
        if not args.dry_run:
            time.sleep(DEFAULT_DELAY_SEC)
    ledger.finished_at_utc = _utc_now_iso()
    _write_ledger(ledger, args.ledger_output)
    logger.info(
        "ledger=%s submitted=%d pages=%d cost_usd=%.2f dry_run=%s",
        args.ledger_output,
        ledger.total_pdfs_submitted,
        ledger.total_pages_estimated,
        ledger.total_cost_usd_estimated,
        ledger.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
