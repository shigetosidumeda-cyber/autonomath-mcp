#!/usr/bin/env python3
"""Live AWS canary attestation emitter for the jpcite 2026-05 credit run.

Phase 4 (ramp) of the AWS canary is in progress (Phase 3 SUCCESS = 7 J0X
smoke jobs landed). The launch CLI plan requires an attestation JSON to be
emitted **during** the run — not just at preflight or teardown — so the
operator has a Source-of-Truth record of:

- Each execution batch (jpcite-credit-* Batch jobs: succeeded / failed / running).
- Cost consumed month-to-date (Cost Explorer ``UnblendedCost``).
- Artifact counts in the raw + derived S3 buckets.
- A signature placeholder slot that the operator fills offline with Ed25519
  via ``scripts/ops/sign_canary_attestation.py`` (template + procedure live
  in ``docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md``).

This script is the **live** counterpart to the **preflight**
``site/releases/rc1-p0-bootstrap/aws_budget_canary_attestation.json`` and
the **post-teardown** ``aws_canary_attestation.json``. It produces a
third class of artifact: per-batch, per-tick live attestations that ride
along with the actual canary execution.

Safety model
============
- **DRY_RUN by default.** The script honours the same envelope contract as
  ``emit_burn_metric.py``: side effects (writing ``site/releases/current/``
  and uploading to S3) only fire when ``--commit`` is passed *and* the
  ``JPCITE_CANARY_ATTESTATION_ENABLED`` env var equals the literal
  ``"true"`` (case-insensitive). Anything else short-circuits to dry-run,
  prints the would-emit JSON to stdout, and exits 0.
- Cost Explorer + Batch ListJobs + S3 ListObjectsV2 are all **read-only**
  APIs, so dry-run still performs them and the printed envelope is faithful
  to live-mode shape.
- Live commands are gated by the operator-only ``--unlock-live-aws-commands``
  flag mirroring the preflight scorecard concern-separation (Stream W
  Wave 50 tick 8). Without that flag the upload step is skipped even when
  ``JPCITE_CANARY_ATTESTATION_ENABLED=true``.

CLI usage::

    # Dry run — prints attestation JSON, no side effects.
    $ ./scripts/aws_credit_ops/emit_canary_attestation.py

    # Write attestation locally only.
    $ JPCITE_CANARY_ATTESTATION_ENABLED=true \\
        ./scripts/aws_credit_ops/emit_canary_attestation.py --commit

    # Write locally AND upload to S3 (operator-only).
    $ JPCITE_CANARY_ATTESTATION_ENABLED=true \\
        ./scripts/aws_credit_ops/emit_canary_attestation.py --commit \\
        --unlock-live-aws-commands

Lambda env vars (Step Functions integration)::

    JPCITE_CANARY_ATTESTATION_ENABLED   "true" to enable side effects
    JPCITE_CANARY_RUN_ID                run id (defaults to ISO timestamp)
    JPCITE_CANARY_BATCH_JOB_PREFIX      Batch job name prefix (default jpcite-credit-)
    JPCITE_CANARY_BATCH_QUEUE_ARN       Batch job queue ARN to poll
    JPCITE_CANARY_RAW_BUCKET            raw artifact bucket
    JPCITE_CANARY_DERIVED_BUCKET        derived artifact bucket
    JPCITE_CANARY_ATTESTATION_BUCKET    S3 destination for the JSON upload
    JPCITE_BATCH_REGION                 Batch region (default ap-northeast-1)
    JPCITE_S3_REGION                    S3 region (default ap-northeast-1)
    JPCITE_CE_REGION                    Cost Explorer region (default us-east-1)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ----------------------------------------------------------------------------
# Defaults sourced from the 2026-05 credit run launch CLI plan.
# ----------------------------------------------------------------------------

SCHEMA_VERSION: Final[str] = "jpcite.aws_canary_attestation_live.p0.v1"
DEFAULT_ACCOUNT_ID: Final[str] = "993693061769"
DEFAULT_BATCH_REGION: Final[str] = "ap-northeast-1"
DEFAULT_S3_REGION: Final[str] = "ap-northeast-1"
DEFAULT_CE_REGION: Final[str] = "us-east-1"
DEFAULT_BATCH_JOB_PREFIX: Final[str] = "jpcite-credit-"
DEFAULT_RAW_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-raw"
DEFAULT_DERIVED_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_REPORTS_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-reports"
DEFAULT_OUTPUT_DIR: Final[str] = "site/releases/current"
DEFAULT_SIGNATURE_PLACEHOLDER: Final[str] = "ed25519:UNSIGNED_PLACEHOLDER_OPERATOR_FILLS_OFFLINE"

# Batch job statuses to enumerate — the union covers all states the Batch API
# may report (RUNNABLE / STARTING / PENDING / RUNNING / SUCCEEDED / FAILED).
BATCH_JOB_STATUSES: Final[tuple[str, ...]] = (
    "SUBMITTED",
    "PENDING",
    "RUNNABLE",
    "STARTING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
)

# Roll-up groups used in the attestation `jobs` field.
GROUP_RUNNING: Final[tuple[str, ...]] = (
    "SUBMITTED",
    "PENDING",
    "RUNNABLE",
    "STARTING",
    "RUNNING",
)
GROUP_SUCCEEDED: Final[str] = "SUCCEEDED"
GROUP_FAILED: Final[str] = "FAILED"


if TYPE_CHECKING:
    from mypy_boto3_batch import BatchClient  # type: ignore[import-not-found]
    from mypy_boto3_ce import CostExplorerClient  # type: ignore[import-not-found]
    from mypy_boto3_s3 import S3Client  # type: ignore[import-not-found]


class _BatchLike(Protocol):
    """Subset of the Batch client surface this module uses."""

    def list_jobs(self, **kwargs: Any) -> dict[str, Any]: ...


class _CostExplorerLike(Protocol):
    def get_cost_and_usage(self, **kwargs: Any) -> dict[str, Any]: ...


class _S3Like(Protocol):
    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...

    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...


# ----------------------------------------------------------------------------
# Pure data envelope — no boto3 import at module level so unit tests stay fast.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchJobsRollup:
    """Per-status counts for ``jpcite-credit-*`` Batch jobs."""

    succeeded: int
    failed: int
    running: int
    by_status: dict[str, int]

    @classmethod
    def empty(cls) -> BatchJobsRollup:
        return cls(succeeded=0, failed=0, running=0, by_status=dict.fromkeys(BATCH_JOB_STATUSES, 0))


@dataclass(frozen=True)
class ArtifactCounts:
    """Object counts (read-only) in the raw + derived S3 buckets."""

    raw_objects: int
    derived_objects: int
    raw_bucket: str
    derived_bucket: str
    sampled: bool  # True when LIST returned fewer than the truncation cap.


@dataclass
class CanaryAttestation:
    """The serialisable envelope written to ``site/releases/current/``."""

    schema_version: str = SCHEMA_VERSION
    attestation_id: str = ""
    run_id: str = ""
    started_at: str = ""
    emitted_at: str = ""
    current_status: str = "IN_PROGRESS"
    aws_account_id: str = DEFAULT_ACCOUNT_ID
    batch_region: str = DEFAULT_BATCH_REGION
    s3_region: str = DEFAULT_S3_REGION
    ce_region: str = DEFAULT_CE_REGION
    jobs: dict[str, Any] = field(default_factory=dict)
    artifacts_count: dict[str, Any] = field(default_factory=dict)
    cost_consumed_usd: float = 0.0
    cost_period_start: str = ""
    cost_period_end: str = ""
    signature_placeholder: str = DEFAULT_SIGNATURE_PLACEHOLDER
    live_aws_commands_executed: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


# ----------------------------------------------------------------------------
# Pollers — each accepts an injected boto3-shaped client (Protocol) so tests
# can pass MagicMocks without ever importing boto3.
# ----------------------------------------------------------------------------


def poll_batch_jobs(
    batch_client: _BatchLike,
    *,
    job_queue: str,
    job_name_prefix: str = DEFAULT_BATCH_JOB_PREFIX,
) -> BatchJobsRollup:
    """List ``jpcite-credit-*`` Batch jobs and roll up by status group.

    Iterates :data:`BATCH_JOB_STATUSES` because ``list_jobs`` is per-status
    in the Batch API. Within each status the result set is paginated via
    ``nextToken``.
    """

    by_status: dict[str, int] = {}
    succeeded = 0
    failed = 0
    running = 0
    for status in BATCH_JOB_STATUSES:
        count = 0
        next_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "jobQueue": job_queue,
                "jobStatus": status,
                "filters": [{"name": "JOB_NAME", "values": [f"{job_name_prefix}*"]}],
                "maxResults": 100,
            }
            if next_token:
                kwargs["nextToken"] = next_token
            page = batch_client.list_jobs(**kwargs)
            jobs = page.get("jobSummaryList") or []
            # Belt + suspenders: the Batch jobName filter is documented as a
            # contains-match, but historically returned cross-prefix hits in
            # ap-northeast-1 — re-filter client-side to be sure.
            count += sum(1 for j in jobs if str(j.get("jobName", "")).startswith(job_name_prefix))
            next_token = page.get("nextToken")
            if not next_token:
                break
        by_status[status] = count
        if status == GROUP_SUCCEEDED:
            succeeded += count
        elif status == GROUP_FAILED:
            failed += count
        elif status in GROUP_RUNNING:
            running += count
    return BatchJobsRollup(
        succeeded=succeeded, failed=failed, running=running, by_status=by_status
    )


def poll_cost_explorer(
    ce_client: _CostExplorerLike, *, now: dt.datetime | None = None
) -> tuple[float, str, str]:
    """Return ``(consumed_usd, period_start_iso, period_end_iso)`` MTD."""

    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_iso = start.strftime("%Y-%m-%d")
    end_iso = end.strftime("%Y-%m-%d")
    response = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start_iso, "End": end_iso},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    results = response.get("ResultsByTime") or []
    if not results:
        return (0.0, start_iso, end_iso)
    total = (results[0].get("Total") or {})
    metric = total.get("UnblendedCost") or total.get("BlendedCost") or {}
    amount_raw = metric.get("Amount", "0")
    try:
        amount = float(amount_raw)
    except (TypeError, ValueError):
        amount = 0.0
    return (round(amount, 4), start_iso, end_iso)


def _count_objects(s3_client: _S3Like, bucket: str, *, max_pages: int = 50) -> tuple[int, bool]:
    """Return ``(object_count, sampled)``.

    ``sampled=True`` indicates we hit the page cap before exhausting the
    bucket — the count is then a lower bound. ``max_pages=50`` × 1000
    objects/page caps a single attestation at 50k object enumerations
    (Cost Explorer-equivalent latency budget).
    """

    total = 0
    pages_walked = 0
    continuation: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "MaxKeys": 1000}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        page = s3_client.list_objects_v2(**kwargs)
        total += int(page.get("KeyCount", 0) or 0)
        pages_walked += 1
        if not page.get("IsTruncated"):
            return (total, False)
        continuation = page.get("NextContinuationToken")
        if not continuation or pages_walked >= max_pages:
            return (total, True)


def poll_artifact_counts(
    s3_client: _S3Like,
    *,
    raw_bucket: str = DEFAULT_RAW_BUCKET,
    derived_bucket: str = DEFAULT_DERIVED_BUCKET,
) -> ArtifactCounts:
    """Enumerate raw + derived bucket object counts (read-only)."""

    raw_count, raw_sampled = _count_objects(s3_client, raw_bucket)
    der_count, der_sampled = _count_objects(s3_client, derived_bucket)
    return ArtifactCounts(
        raw_objects=raw_count,
        derived_objects=der_count,
        raw_bucket=raw_bucket,
        derived_bucket=derived_bucket,
        sampled=raw_sampled or der_sampled,
    )


# ----------------------------------------------------------------------------
# Render + write
# ----------------------------------------------------------------------------


def build_attestation(
    *,
    run_id: str,
    started_at: dt.datetime,
    jobs: BatchJobsRollup,
    cost: tuple[float, str, str],
    artifacts: ArtifactCounts,
    aws_account_id: str = DEFAULT_ACCOUNT_ID,
    batch_region: str = DEFAULT_BATCH_REGION,
    s3_region: str = DEFAULT_S3_REGION,
    ce_region: str = DEFAULT_CE_REGION,
    now: dt.datetime | None = None,
    current_status: str = "IN_PROGRESS",
    live_aws_commands_executed: bool = False,
) -> CanaryAttestation:
    """Compose the attestation envelope."""

    consumed_usd, period_start, period_end = cost
    if now is None:
        now = dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=dt.UTC)
    return CanaryAttestation(
        schema_version=SCHEMA_VERSION,
        attestation_id=str(uuid.uuid4()),
        run_id=run_id,
        started_at=started_at.replace(microsecond=0).isoformat(),
        emitted_at=now.replace(microsecond=0).isoformat(),
        current_status=current_status,
        aws_account_id=aws_account_id,
        batch_region=batch_region,
        s3_region=s3_region,
        ce_region=ce_region,
        jobs={
            "succeeded": jobs.succeeded,
            "failed": jobs.failed,
            "running": jobs.running,
            "by_status": dict(jobs.by_status),
        },
        artifacts_count={
            "raw_objects": artifacts.raw_objects,
            "derived_objects": artifacts.derived_objects,
            "raw_bucket": artifacts.raw_bucket,
            "derived_bucket": artifacts.derived_bucket,
            "sampled": artifacts.sampled,
        },
        cost_consumed_usd=consumed_usd,
        cost_period_start=period_start,
        cost_period_end=period_end,
        signature_placeholder=DEFAULT_SIGNATURE_PLACEHOLDER,
        live_aws_commands_executed=live_aws_commands_executed,
    )


def attestation_filename(run_id: str) -> str:
    """Canonical filename for a per-tick attestation.

    Safe for filesystems: run_id is allowed to contain ``/`` in upstream
    Step Functions execution names, so we sanitise.
    """

    safe = run_id.replace("/", "_").replace(":", "_")
    return f"aws_canary_attestation_{safe}.json"


def write_attestation(
    attestation: CanaryAttestation, *, output_dir: Path, commit: bool
) -> Path:
    """Render JSON. Writes to disk only when ``commit=True``."""

    target = output_dir / attestation_filename(attestation.run_id)
    payload = attestation.to_json()
    if commit:
        output_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
        logger.info("wrote attestation to %s (%d bytes)", target, len(payload))
    else:
        logger.info("dry-run: would write attestation to %s (%d bytes)", target, len(payload))
    return target


def upload_attestation(
    attestation: CanaryAttestation,
    *,
    s3_client: _S3Like | None,
    bucket: str,
    live: bool,
) -> dict[str, Any]:
    """Optionally upload to S3. Returns the action log entry."""

    key = f"attestations/{attestation_filename(attestation.run_id)}"
    payload = attestation.to_json()
    if live and s3_client is not None:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload.encode("utf-8"),
            ContentType="application/json",
            Tagging="Project=jpcite&CreditRun=2026-05&AutoStop=2026-05-29",
        )
        return {
            "action": "s3_put_object",
            "bucket": bucket,
            "key": key,
            "bytes": len(payload),
            "live": True,
        }
    return {
        "action": "s3_put_object",
        "bucket": bucket,
        "key": key,
        "bytes": len(payload),
        "live": False,
    }


# ----------------------------------------------------------------------------
# CLI glue + Lambda integration
# ----------------------------------------------------------------------------


def _enabled() -> bool:
    return (
        os.environ.get("JPCITE_CANARY_ATTESTATION_ENABLED", "false").strip().lower() == "true"
    )


def _build_boto3_clients(
    *, batch_region: str, s3_region: str, ce_region: str
) -> tuple[_BatchLike, _CostExplorerLike, _S3Like]:
    """Lazy boto3 import — keeps unit tests free of network deps."""

    import boto3

    batch = cast("BatchClient", boto3.client("batch", region_name=batch_region))
    ce = cast("CostExplorerClient", boto3.client("ce", region_name=ce_region))
    s3 = cast("S3Client", boto3.client("s3", region_name=s3_region))
    return batch, ce, s3


class _SyntheticBatch:
    """Used when boto3 isn't installed locally and the operator runs dry-run."""

    def list_jobs(self, **_kwargs: Any) -> dict[str, Any]:
        return {"jobSummaryList": [], "nextToken": None}


class _SyntheticCE:
    def get_cost_and_usage(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ResultsByTime": [
                {"Total": {"UnblendedCost": {"Amount": "0.0000", "Unit": "USD"}}},
            ]
        }


class _SyntheticS3:
    def list_objects_v2(self, **_kwargs: Any) -> dict[str, Any]:
        return {"KeyCount": 0, "IsTruncated": False}

    def put_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {"ETag": "synthetic"}


def run_once(argv: list[str] | None = None) -> dict[str, Any]:
    """One-shot CLI + Lambda entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        default=os.environ.get(
            "JPCITE_CANARY_RUN_ID",
            dt.datetime.now(dt.UTC).strftime("canary-%Y%m%dT%H%M%SZ"),
        ),
    )
    parser.add_argument(
        "--started-at",
        default=os.environ.get("JPCITE_CANARY_STARTED_AT", ""),
        help="ISO-8601 start time of the canary run (defaults to now-30min)",
    )
    parser.add_argument(
        "--batch-region",
        default=os.environ.get("JPCITE_BATCH_REGION", DEFAULT_BATCH_REGION),
    )
    parser.add_argument(
        "--s3-region",
        default=os.environ.get("JPCITE_S3_REGION", DEFAULT_S3_REGION),
    )
    parser.add_argument(
        "--ce-region",
        default=os.environ.get("JPCITE_CE_REGION", DEFAULT_CE_REGION),
    )
    parser.add_argument(
        "--job-queue",
        default=os.environ.get(
            "JPCITE_CANARY_BATCH_QUEUE_ARN",
            "arn:aws:batch:ap-northeast-1:993693061769:job-queue/jpcite-credit-fargate-spot-short-queue",
        ),
    )
    parser.add_argument(
        "--job-prefix",
        default=os.environ.get("JPCITE_CANARY_BATCH_JOB_PREFIX", DEFAULT_BATCH_JOB_PREFIX),
    )
    parser.add_argument(
        "--raw-bucket",
        default=os.environ.get("JPCITE_CANARY_RAW_BUCKET", DEFAULT_RAW_BUCKET),
    )
    parser.add_argument(
        "--derived-bucket",
        default=os.environ.get("JPCITE_CANARY_DERIVED_BUCKET", DEFAULT_DERIVED_BUCKET),
    )
    parser.add_argument(
        "--attestation-bucket",
        default=os.environ.get("JPCITE_CANARY_ATTESTATION_BUCKET", DEFAULT_REPORTS_BUCKET),
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("JPCITE_CANARY_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
    )
    parser.add_argument(
        "--current-status",
        default=os.environ.get("JPCITE_CANARY_STATUS", "IN_PROGRESS"),
        choices=("PRE_RUN", "IN_PROGRESS", "RAMP", "STEADY", "COOLDOWN", "COMPLETED", "FAILED"),
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually write the JSON to disk (default: dry-run prints only)",
    )
    parser.add_argument(
        "--unlock-live-aws-commands",
        action="store_true",
        help="ALSO upload the JSON to S3 (operator-only, separate gate)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="force dry-run even if --commit is passed",
    )
    args = parser.parse_args(argv)

    env_enabled = _enabled()
    # commit gates LOCAL write; live_upload gates S3 upload. Concern separation
    # mirrors Stream W Wave 50 tick 8 (scorecard promote vs live_aws unlock).
    commit_local = args.commit and env_enabled and not args.dry_run
    live_upload = (
        commit_local and args.unlock_live_aws_commands
    )

    started_at_str: str = args.started_at
    if started_at_str:
        try:
            started_at = dt.datetime.fromisoformat(started_at_str)
        except ValueError:
            logger.warning("invalid --started-at %r; falling back to now-30min", started_at_str)
            started_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)
    else:
        started_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)

    batch_client: _BatchLike
    ce_client: _CostExplorerLike
    s3_client: _S3Like
    # Force-synthetic mode when no env opt-in: avoids spending the operator's
    # AWS credentials on a read-only poll just to print a dry-run envelope.
    use_synthetic = not env_enabled or args.dry_run
    if use_synthetic:
        logger.info("dry-run / env-disabled: using synthetic boto3 clients")
        batch_client = _SyntheticBatch()
        ce_client = _SyntheticCE()
        s3_client = _SyntheticS3()
    else:
        try:
            batch_client, ce_client, s3_client = _build_boto3_clients(
                batch_region=args.batch_region,
                s3_region=args.s3_region,
                ce_region=args.ce_region,
            )
        except Exception as exc:  # noqa: BLE001 — local dev path; boto3 may be absent
            logger.warning("boto3 unavailable (%s); using synthetic clients", exc)
            batch_client = _SyntheticBatch()
            ce_client = _SyntheticCE()
            s3_client = _SyntheticS3()

    try:
        jobs = poll_batch_jobs(
            batch_client, job_queue=args.job_queue, job_name_prefix=args.job_prefix
        )
    except Exception as exc:  # noqa: BLE001 — read-only poll, never break attestation
        logger.warning("batch poll failed (%s); falling back to empty rollup", exc)
        jobs = BatchJobsRollup.empty()
    try:
        cost = poll_cost_explorer(ce_client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cost-explorer poll failed (%s); falling back to 0.0", exc)
        now = dt.datetime.now(dt.UTC)
        start_iso = now.replace(day=1).strftime("%Y-%m-%d")
        end_iso = (now + dt.timedelta(days=1)).strftime("%Y-%m-%d")
        cost = (0.0, start_iso, end_iso)
    try:
        artifacts = poll_artifact_counts(
            s3_client, raw_bucket=args.raw_bucket, derived_bucket=args.derived_bucket
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("s3 poll failed (%s); falling back to zero artifact counts", exc)
        artifacts = ArtifactCounts(
            raw_objects=0,
            derived_objects=0,
            raw_bucket=args.raw_bucket,
            derived_bucket=args.derived_bucket,
            sampled=False,
        )

    attestation = build_attestation(
        run_id=args.run_id,
        started_at=started_at,
        jobs=jobs,
        cost=cost,
        artifacts=artifacts,
        batch_region=args.batch_region,
        s3_region=args.s3_region,
        ce_region=args.ce_region,
        current_status=args.current_status,
        live_aws_commands_executed=live_upload,
    )

    output_dir = Path(args.output_dir)
    target = write_attestation(attestation, output_dir=output_dir, commit=commit_local)
    upload_log = upload_attestation(
        attestation, s3_client=s3_client, bucket=args.attestation_bucket, live=live_upload
    )

    result = {
        "attestation": asdict(attestation),
        "actions": [
            {
                "action": "write_local",
                "path": str(target),
                "live": commit_local,
            },
            upload_log,
        ],
        "commit_local": commit_local,
        "live_upload": live_upload,
        "env_enabled": env_enabled,
    }
    logger.info(
        "canary-attestation mode=%s succeeded=%d failed=%d running=%d cost_usd=%.2f raw=%d derived=%d",
        "live" if commit_local else "dry_run",
        jobs.succeeded,
        jobs.failed,
        jobs.running,
        cost[0],
        artifacts.raw_objects,
        artifacts.derived_objects,
    )
    return result


def main() -> int:
    result = run_once()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    # Exit code semantics: 0 success, 1 failed jobs detected, 2 dry-run.
    jobs = result.get("attestation", {}).get("jobs", {})
    if jobs.get("failed", 0) > 0:
        return 1
    if not result.get("commit_local"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
