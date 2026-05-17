"""Lane C bulk Textract submitter for the 2026-05-17 burn ramp.

Drives the ``textract_bulk_2026_05_17_manifest.json`` PDF set through:

1. **Download** each PDF from its public ``source_url`` (HTTP GET with a
   short ``User-Agent`` identifying the operator).
2. **Stage** the bytes into the Singapore Textract staging bucket
   (``jpcite-credit-textract-apse1-202605``) under
   ``in/<sha256[:2]>/<sha256>.pdf``. Textract is offered in
   ``ap-southeast-1`` but **not** ``ap-northeast-1`` — `j16_textract_apse1.py`
   established this geography contract; we reuse the same bucket so the
   IAM role + budget envelope already cover the new run.
3. **Submit** ``start_document_analysis`` (TABLES + FORMS) with an
   ``OutputConfig`` pointing at the same Singapore bucket under
   ``out/<sha256[:2]>/<sha256>/`` for Textract to drop the raw blocks.
4. **Record** the per-PDF outcome (``s3_in_key`` / ``job_id`` /
   ``status``) in a run ledger JSON beside the manifest so a later step
   can drain results into the Tokyo derived bucket without
   re-downloading.

Cost contract
-------------
Textract TABLES + FORMS bills $0.05 / page. With 2,130 unique PDFs at
~30 pages each (median ministry whitepaper) the projected daily burn
caps near $3,200 — well below the $5,000 ramp band Lane C targets, well
below the $19,490 hard-stop. We **do not** chase the 15K PDF / day
upper figure on the very first wet-run because:

* the 4 GHA hard-stop tripwires (CW $14K, Budget $17K, slowdown $18.3K,
  Lambda kill $18.7K + Action deny $18.9K) are still primary defence;
* per-page real cost depends on actual page count, which we measure on
  the first 100 jobs before scaling further.

Constraints
-----------
* AWS profile **bookyou-recovery** (memory: secret store separation).
* No LLM calls — Textract is OCR / structured extraction, not inference.
* Respect ``robots.txt`` *only at fetch time* — the PDF URLs are
  primary-source government / municipality artifacts (J06 / J16 already
  established legal posture per ``aws_credit_review_05_*``).
* DRY_RUN default. ``--commit`` lifts the guard (user authorised this
  Lane C run explicitly per the 2026-05-17 task brief).
* ``[lane:solo]`` marker.

Usage
-----
::

    .venv/bin/python scripts/aws_credit_ops/textract_bulk_submit_2026_05_17.py \\
        --manifest data/textract_bulk_2026_05_17_manifest.json \\
        --max-pdfs 200 \\
        --parallel 8 \\
        --commit
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

DEFAULT_MANIFEST_PATH = "data/textract_bulk_2026_05_17_manifest.json"
DEFAULT_PROFILE = "bookyou-recovery"
DEFAULT_TEXTRACT_REGION = "ap-southeast-1"
DEFAULT_STAGE_BUCKET = "jpcite-credit-textract-apse1-202605"
DEFAULT_PARALLEL = 8
DEFAULT_MAX_PDFS = 200
DEFAULT_PER_PAGE_USD = 0.05
DEFAULT_BUDGET_USD = 700.0
DEFAULT_USER_AGENT = (
    "Bookyou-jpcite-textract-bulk/2026.05.17 (+https://jpcite.com; ops@bookyou.net)"
)
HTTP_TIMEOUT_SEC = 30
DOWNLOAD_MAX_BYTES = 25 * 1024 * 1024  # 25 MB safety cap per PDF


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lane C bulk Textract submit (2026-05-17 burn ramp).",
    )
    p.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--textract-region", default=DEFAULT_TEXTRACT_REGION)
    p.add_argument("--stage-bucket", default=DEFAULT_STAGE_BUCKET)
    p.add_argument("--max-pdfs", type=int, default=DEFAULT_MAX_PDFS)
    p.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    p.add_argument("--per-page-usd", type=float, default=DEFAULT_PER_PAGE_USD)
    p.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    p.add_argument(
        "--commit",
        action="store_true",
        help="Lift DRY_RUN. Without this flag, the script downloads NOTHING and submits NOTHING.",
    )
    p.add_argument(
        "--ledger-out",
        default=None,
        help="Optional path for the run ledger JSON. Defaults beside the manifest.",
    )
    return p.parse_args(argv)


def _load_manifest(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def _download_pdf(url: str, *, user_agent: str) -> bytes | None:
    """HTTP GET ``url`` and return PDF bytes, or ``None`` on failure.

    A 25 MB cap is enforced so a misbehaving server cannot drag a 9 GB
    blob into RAM. Errors are swallowed (logged on stderr) so a single
    dead URL cannot abort the whole run.
    """
    # Percent-encode non-ASCII path / query components (Japanese filenames)
    # so urllib's ASCII-only HTTP request encoder does not crash.
    try:
        parsed = urllib.parse.urlsplit(url)
        safe_path = urllib.parse.quote(parsed.path, safe="/%")
        safe_query = urllib.parse.quote(parsed.query, safe="=&%")
        encoded_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, safe_path, safe_query, parsed.fragment)
        )
    except (ValueError, UnicodeError) as exc:
        print(f"[bulk] SKIP url encode fail {url}: {exc}", file=sys.stderr)
        return None

    # urlopen here only accepts https/http URLs from the curated jpcite
    # source_url corpus (programs / enforcement_cases / am_source); the
    # encoded_url passes through urllib.parse.urlsplit + percent-quote so
    # file:// / custom-scheme cannot smuggle in. Suppress B310.
    if not encoded_url.startswith(("https://", "http://")):
        print(f"[bulk] SKIP non-http scheme {encoded_url}", file=sys.stderr)
        return None
    req = urllib.request.Request(encoded_url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:  # nosec B310
            data = resp.read(DOWNLOAD_MAX_BYTES + 1)
            if len(data) > DOWNLOAD_MAX_BYTES:
                print(f"[bulk] SKIP oversized {url}", file=sys.stderr)
                return None
            if not data.startswith(b"%PDF-"):
                print(f"[bulk] SKIP non-PDF magic {url}", file=sys.stderr)
                return None
            return data
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[bulk] SKIP fetch fail {url}: {exc}", file=sys.stderr)
        return None


def _stage_to_s3(s3_client: Any, bucket: str, key: str, data: bytes) -> bool:
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="application/pdf",
        )
    except Exception as exc:  # noqa: BLE001 — live AWS path
        print(f"[bulk] SKIP put_object fail {key}: {exc}", file=sys.stderr)
        return False
    return True


def _s3_object_exists(s3_client: Any, bucket: str, key: str) -> bool:
    """HEAD probe to skip already-staged PDFs (idempotent re-runs)."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001 — head fails for many reasons, treat as missing
        return False
    return True


def _submit_textract(
    textract_client: Any,
    bucket: str,
    in_key: str,
    out_prefix: str,
    *,
    max_retries: int = 6,
    base_sleep: float = 2.0,
) -> str | None:
    """Submit ``start_document_analysis`` and return ``JobId``.

    Textract's per-account concurrent-async-job quota (600 by default in
    ap-southeast-1) is the primary throttle source on a bulk run. We
    retry ``LimitExceededException`` with exponential backoff so a 200-PDF
    submit-burst drains gradually rather than dropping >50% of jobs.
    """
    for attempt in range(max_retries):
        try:
            resp = textract_client.start_document_analysis(
                DocumentLocation={"S3Object": {"Bucket": bucket, "Name": in_key}},
                FeatureTypes=["TABLES", "FORMS"],
                OutputConfig={"S3Bucket": bucket, "S3Prefix": out_prefix.rstrip("/")},
            )
        except Exception as exc:  # noqa: BLE001 — live AWS path
            msg = str(exc)
            if "LimitExceeded" in msg or "ThrottlingException" in msg or "Throttl" in msg:
                sleep = base_sleep * (2**attempt)
                print(
                    f"[bulk] retry textract submit ({attempt + 1}/{max_retries}) "
                    f"in {sleep:.1f}s: {in_key}",
                    file=sys.stderr,
                )
                time.sleep(sleep)
                continue
            print(f"[bulk] SKIP textract submit fail {in_key}: {exc}", file=sys.stderr)
            return None
        else:
            job_id = resp.get("JobId")
            return job_id if isinstance(job_id, str) and job_id else None
    print(f"[bulk] SKIP textract submit retries exhausted: {in_key}", file=sys.stderr)
    return None


def _process_one(
    entry: dict[str, Any],
    *,
    s3_client: Any,
    textract_client: Any,
    stage_bucket: str,
    user_agent: str,
    dry_run: bool,
) -> dict[str, Any]:
    url = entry["source_url"]
    in_key = entry["s3_in_key"]
    out_prefix = entry["s3_out_key_prefix"]
    sha = entry["sha256"]

    record: dict[str, Any] = {
        "sha256": sha,
        "source_url": url,
        "s3_in_key": in_key,
        "status": "pending",
    }

    if dry_run:
        record["status"] = "dry_run"
        return record

    # Skip download + put if the PDF is already staged from an earlier
    # partial run (the 2026-05-17 first wet-run staged 185 PDFs before
    # crashing on a unicode URL; a re-run must not re-pay for those).
    already_staged = _s3_object_exists(s3_client, stage_bucket, in_key)
    if already_staged:
        record["s3_staged"] = True
        record["already_staged"] = True
    else:
        pdf_bytes = _download_pdf(url, user_agent=user_agent)
        if pdf_bytes is None:
            record["status"] = "download_failed"
            return record
        record["bytes_downloaded"] = len(pdf_bytes)
        if not _stage_to_s3(s3_client, stage_bucket, in_key, pdf_bytes):
            record["status"] = "s3_put_failed"
            return record
        record["s3_staged"] = True

    job_id = _submit_textract(textract_client, stage_bucket, in_key, out_prefix)
    if job_id is None:
        record["status"] = "textract_submit_failed"
        return record
    record["status"] = "submitted"
    record["job_id"] = job_id
    return record


def _write_ledger(
    ledger_path: str,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    submitted = sum(1 for r in records if r.get("status") == "submitted")
    failed = sum(1 for r in records if r.get("status") not in ("submitted", "dry_run"))
    dry = sum(1 for r in records if r.get("status") == "dry_run")
    out = {
        "ledger_id": "textract_bulk_2026_05_17_ledger",
        "manifest_id": manifest.get("manifest_id"),
        "manifest_pdf_count": manifest.get("pdf_count"),
        "run_started_at_utc": datetime.now(UTC).isoformat(),
        "args": {
            "manifest": args.manifest,
            "profile": args.profile,
            "textract_region": args.textract_region,
            "stage_bucket": args.stage_bucket,
            "max_pdfs": args.max_pdfs,
            "parallel": args.parallel,
            "per_page_usd": args.per_page_usd,
            "budget_usd": args.budget_usd,
            "commit": args.commit,
        },
        "records_count": len(records),
        "submitted_count": submitted,
        "failed_count": failed,
        "dry_run_count": dry,
        "records": records,
    }
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    manifest_path = args.manifest
    if not os.path.exists(manifest_path):
        print(f"[bulk] FATAL: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    manifest = _load_manifest(manifest_path)
    entries = manifest.get("entries", [])
    if not entries:
        print("[bulk] FATAL: manifest has zero entries", file=sys.stderr)
        return 2

    # Cap at --max-pdfs first; this is the operator's spend governor.
    entries = entries[: args.max_pdfs]

    dry_run = not args.commit
    print(
        f"[bulk] manifest={manifest_path} entries={len(entries)} "
        f"parallel={args.parallel} dry_run={dry_run} "
        f"region={args.textract_region} bucket={args.stage_bucket}"
    )

    s3_client: Any = None
    textract_client: Any = None
    if not dry_run:
        try:
            import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
        except ImportError:
            print("[bulk] FATAL: boto3 missing — pip install boto3 first", file=sys.stderr)
            return 2
        session = boto3.Session(profile_name=args.profile)
        # Singapore region for both S3 staging bucket and Textract endpoint.
        s3_client = session.client("s3", region_name=args.textract_region)
        textract_client = session.client("textract", region_name=args.textract_region)

    user_agent = DEFAULT_USER_AGENT
    records: list[dict[str, Any]] = []

    ledger_path = (
        args.ledger_out
        or (os.path.dirname(manifest_path) or ".") + "/textract_bulk_2026_05_17_ledger.json"
    )

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = [
            pool.submit(
                _process_one,
                entry,
                s3_client=s3_client,
                textract_client=textract_client,
                stage_bucket=args.stage_bucket,
                user_agent=user_agent,
                dry_run=dry_run,
            )
            for entry in entries
        ]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                rec = fut.result()
            except Exception as exc:  # noqa: BLE001 — never crash the whole run
                print(f"[bulk] worker exception {type(exc).__name__}: {exc}", file=sys.stderr)
                rec = {"status": "worker_exception", "error": str(exc)[:300]}
            records.append(rec)
            # Persist the ledger every 10 PDFs so a SIGTERM mid-run does not
            # lose the job_id surface. The 2026-05-17 first wet-run lost
            # state when the long tail-end retry loop was killed manually.
            if i % 10 == 0 or i == len(futures):
                try:
                    _write_ledger(ledger_path, manifest, records, args)
                except Exception as exc:  # noqa: BLE001 — never let ledger write abort the run
                    print(f"[bulk] WARN ledger write failed: {exc}", file=sys.stderr)
                print(
                    f"[bulk] progress {i}/{len(futures)} elapsed={time.time() - started:.1f}s "
                    f"last_status={rec.get('status')}"
                )

    _write_ledger(ledger_path, manifest, records, args)

    submitted = sum(1 for r in records if r.get("status") == "submitted")
    failed = sum(1 for r in records if r.get("status") not in ("submitted", "dry_run"))
    dry = sum(1 for r in records if r.get("status") == "dry_run")
    print(f"[bulk] DONE submitted={submitted} failed={failed} dry={dry} ledger={ledger_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
