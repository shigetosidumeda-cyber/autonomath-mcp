"""AWS Batch entrypoint for jpcite-crawler.

Flow:
    1. Read ``JOB_MANIFEST_S3_URI`` env var (``s3://bucket/key.json``).
    2. Download the manifest JSON via boto3.
    3. Build ``SourcePolicy`` + ``TargetSpec`` list from the manifest.
    4. Crawl URLs with ``crawl.Fetcher`` (robots + rate-limit + retry).
    5. Emit jpcite contract artifacts under ``/work/out/``:
           run_manifest.json
           object_manifest.jsonl  [+ .parquet when pyarrow available]
           source_receipts.jsonl
           source_profile_delta.jsonl
           known_gaps.jsonl
           quarantine.jsonl
           raw/<sha256>.bin          (only when license_boundary allows)
    6. Upload the entire ``/work/out/`` tree to
       ``s3://<output_bucket>/<output_prefix>/`` from the manifest.

NO LLM API calls. NO outbound traffic beyond manifest targets and the
AWS regional endpoints used by boto3.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
import crawl
import manifest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _log(level: str, msg: str, **fields: Any) -> None:
    """Structured one-line JSON log to stderr.

    AWS Batch routes stdout/stderr to CloudWatch; the cost-control doc
    warns against bulk log volume so this module keeps lines short and
    machine-readable. Bodies / payloads are never logged.
    """

    payload: dict[str, Any] = {"level": level, "msg": msg}
    payload.update(fields)
    sys.stderr.write(manifest.canonical_dumps(payload))
    sys.stderr.write("\n")
    sys.stderr.flush()


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/key`` -> ``("bucket", "key")``."""

    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"invalid S3 URI: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def _load_manifest_from_s3(s3: Any, uri: str) -> dict[str, Any]:
    bucket, key = _parse_s3_uri(uri)
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest {uri!r} root is not a JSON object")
    return data


def _build_policy(spec: dict[str, Any]) -> crawl.SourcePolicy:
    # follow_mode is opt-in per manifest; absent or typo'd values fall
    # through _coerce_follow_mode to FollowMode.NONE so the existing
    # 26 J01..J07 SUCCEEDED runs reproduce byte-for-byte.
    follow_mode = crawl._coerce_follow_mode(spec.get("follow_mode"))
    return crawl.SourcePolicy(
        source_id=str(spec.get("source_id", "unknown")),
        publisher=str(spec.get("publisher", "")),
        license_boundary=str(spec.get("license_boundary", "derived_fact")),
        respect_robots=bool(spec.get("respect_robots", True)),
        user_agent=str(
            spec.get("user_agent")
            or os.environ.get(
                "JPCITE_USER_AGENT",
                "jpcite-crawler/0.1.0 (+ops@bookyou.net)",
            )
        ),
        request_delay_seconds=float(
            spec.get(
                "request_delay_seconds",
                float(os.environ.get("JPCITE_DEFAULT_DELAY_SECONDS", "1.0")),
            )
        ),
        max_retries=int(
            spec.get(
                "max_retries",
                int(os.environ.get("JPCITE_MAX_RETRIES", "3")),
            )
        ),
        timeout_seconds=float(
            spec.get(
                "timeout_seconds",
                float(os.environ.get("JPCITE_DEFAULT_TIMEOUT_SECONDS", "30")),
            )
        ),
        follow_mode=follow_mode,
        follow_max_per_page=int(spec.get("follow_max_per_page", 50)),
        follow_max_total=int(spec.get("follow_max_total", 5000)),
        follow_max_depth=int(spec.get("follow_max_depth", 1)),
    )


def _build_targets(
    spec: dict[str, Any],
) -> tuple[list[crawl.TargetSpec], list[dict[str, Any]]]:
    """Build target list with per-entry resilience.

    Returns ``(targets, malformed_entries)``. A malformed entry never kills
    the whole job — the bad row is recorded in ``malformed_entries`` so the
    caller can emit a known_gap and continue crawling the rest of the
    manifest. The previous behaviour (raise ValueError on any bad row)
    caused every J0X-deep retry to exit with code 1 the moment a single
    malformed entry slipped in. Per-URL failure isolation is now the
    contract.
    """

    raw = spec.get("target_urls")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        # Whole-list malformed -> log + treat as empty + emit one job-scope
        # known_gap. Still better than dying.
        return [], [
            {
                "index": -1,
                "reason": "target_urls_not_a_list",
                "type": type(raw).__name__,
            }
        ]

    out: list[crawl.TargetSpec] = []
    malformed: list[dict[str, Any]] = []
    for i, entry in enumerate(raw):
        try:
            if isinstance(entry, str):
                out.append(crawl.TargetSpec(url=entry, target_id=f"t{i:06d}"))
            elif isinstance(entry, dict):
                url = entry.get("url")
                if not isinstance(url, str) or not url:
                    malformed.append(
                        {
                            "index": i,
                            "reason": "missing_or_empty_url",
                            "entry_preview": str(entry)[:120],
                        }
                    )
                    continue
                out.append(
                    crawl.TargetSpec(
                        url=str(url),
                        target_id=str(entry.get("target_id") or f"t{i:06d}"),
                        parser=str(entry.get("parser", "raw")),
                        license_boundary=str(
                            entry.get(
                                "license_boundary",
                                spec.get("license_boundary", "derived_fact"),
                            )
                        ),
                        etag=entry.get("etag"),
                        last_modified=entry.get("last_modified"),
                        extras=entry.get("extras", {}),
                    )
                )
            else:
                malformed.append(
                    {
                        "index": i,
                        "reason": "entry_not_string_or_object",
                        "type": type(entry).__name__,
                    }
                )
        except Exception as exc:
            # Any unexpected build failure (e.g. unhashable extras) is
            # isolated to this entry only.
            malformed.append(
                {
                    "index": i,
                    "reason": f"target_build_failed:{type(exc).__name__}",
                    "error": str(exc),
                }
            )
    return out, malformed


def _emit_artifacts(
    ctx: manifest.JobContext,
    policy: crawl.SourcePolicy,
    results: list[crawl.FetchResult],
    out_dir: Path,
    malformed_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write the seven standard JSONL artifacts + run_manifest.json.

    Returns a summary dict used to build the run_manifest envelope.

    ``claim_refs.jsonl`` is always emitted (header-only when no claims
    were extracted) so the Glue ``claim_refs`` table is registered and
    Athena cross-source big queries can execute even when this job did
    not extract claim references. The header line carries the contract
    version ``jpcir.p0.v1``; downstream ETL skips it when materialising
    the Parquet partition.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"

    receipt_path = out_dir / "source_receipts.jsonl"
    object_path = out_dir / "object_manifest.jsonl"
    gaps_path = out_dir / "known_gaps.jsonl"
    quarantine_path = out_dir / "quarantine.jsonl"
    profile_delta_path = out_dir / "source_profile_delta.jsonl"
    claim_refs_path = out_dir / "claim_refs.jsonl"

    accepted = 0
    failed = 0
    gap_count = 0

    with (
        manifest.JsonlWriter(receipt_path) as receipts,
        manifest.JsonlWriter(object_path) as objects,
        manifest.JsonlWriter(gaps_path) as gaps,
        manifest.JsonlWriter(quarantine_path) as quarantine,
    ):
        # First, surface manifest-time malformed entries as known_gaps so
        # downstream auditors can see exactly which manifest rows were
        # skipped without crawling. These never count toward accepted /
        # failed — they're shape errors, not fetch errors.
        for bad in (malformed_targets or []):
            affected = [str(bad.get("entry_preview", "")) or f"index:{bad.get('index')}"]
            gaps.write(
                manifest.build_known_gap_row(
                    gap_id="source_receipt_incomplete",
                    severity="review",
                    scope="record",
                    affected_records=affected,
                    message=f"manifest_target_malformed: {bad.get('reason', 'unknown')}",
                    agent_instruction=(
                        "Do not assert facts about this manifest entry; the row "
                        "could not be parsed and was skipped without a fetch."
                    ),
                )
            )
            gap_count += 1

        for result in results:
            # license / robots short-circuit -> known_gap, not failure
            if result.skipped_reason and not result.ok and result.http_status is None:
                gap_id = _skip_to_gap_id(result.skipped_reason)
                gaps.write(
                    manifest.build_known_gap_row(
                        gap_id=gap_id,
                        severity="review",
                        scope="source",
                        affected_records=[result.target.url],
                        message=f"skipped: {result.skipped_reason}",
                        agent_instruction=(
                            "Do not assert facts about this URL; this source was not collected."
                        ),
                    )
                )
                gap_count += 1
                continue

            if not result.ok:
                failed += 1
                quarantine.write(
                    {
                        "url": result.target.url,
                        "target_id": result.target.target_id,
                        "http_status": result.http_status,
                        "error": result.error,
                        "elapsed_ms": result.elapsed_ms,
                    }
                )
                continue

            # Successful fetch path
            accepted += 1
            receipt_id = f"sr_{uuid.uuid4().hex[:16]}"

            # Persist raw body when license allows; link_only never persists.
            raw_uri: str | None = None
            if (
                result.content_bytes
                and result.target.license_boundary
                in {"full_fact", "derived_fact"}
            ):
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"{result.content_sha256.split(':', 1)[1]}.bin"
                raw_path.write_bytes(result.content_bytes)
                raw_uri = f"s3://{ctx.output_bucket}/{ctx.output_prefix.rstrip('/')}/raw/{raw_path.name}"

            receipt_row = manifest.build_source_receipt_row(
                ctx=ctx,
                receipt_id=receipt_id,
                source_url=result.target.url,
                content_hash=result.content_sha256,
                license_boundary=result.target.license_boundary,
            )
            receipts.write(receipt_row)

            obj_extras: dict[str, Any] = {
                "http_status": result.http_status,
                "content_type": result.content_type or "",
                "elapsed_ms": result.elapsed_ms,
                "skipped_reason": result.skipped_reason,
            }
            # Follow-mode provenance: when a target was emitted by the
            # link-follow queue, stamp the parent URL + depth so the
            # auditor can trace a PDF back to the HTML index that linked
            # to it. Empty for the original manifest entries.
            if result.target.follow_parent_url:
                obj_extras["follow_parent_url"] = result.target.follow_parent_url
                obj_extras["follow_depth"] = result.target.follow_depth
            obj_row = manifest.build_object_manifest_row(
                artifact_id=f"art_{uuid.uuid4().hex[:16]}",
                ctx=ctx,
                artifact_kind="source_document_manifest",
                s3_uri=raw_uri
                or f"s3://{ctx.output_bucket}/{ctx.output_prefix.rstrip('/')}/source_receipts.jsonl",
                format_="binary" if raw_uri else "metadata_only",
                record_count=1,
                byte_size=len(result.content_bytes),
                sha256=result.content_sha256,
                license_boundary=result.target.license_boundary,
                extras=obj_extras,
            )
            objects.write(obj_row)

    # source_profile_delta — one row per source (the policy itself).
    with manifest.JsonlWriter(profile_delta_path) as profiles:
        profiles.write(
            {
                "source_id": policy.source_id,
                "publisher": policy.publisher,
                "license_boundary": policy.license_boundary,
                "respect_robots": policy.respect_robots,
                "user_agent": policy.user_agent,
                "request_delay_seconds": policy.request_delay_seconds,
                "no_hit_policy": "no_hit_not_absence",
            }
        )

    # Always emit claim_refs.jsonl so the Glue ``claim_refs`` table is
    # registered (Athena cross-source big queries depend on the table
    # existing even when this particular job extracted zero claim refs).
    # The header line carries the contract version and is the only row
    # an empty-claim job ever writes — downstream ETL drops the header
    # before materialising the Parquet partition.
    with manifest.JsonlWriter(claim_refs_path) as claim_refs:
        claim_refs.write({"version": "jpcir.p0.v1"})

    # Best-effort parquet copy of object_manifest.
    parquet_path = out_dir / "object_manifest.parquet"
    parquet_emitted = manifest.maybe_write_object_manifest_parquet(
        object_path,
        parquet_path,
    )

    return {
        "accepted_count": accepted,
        "failed_count": failed,
        "known_gap_count": gap_count,
        "object_manifest_parquet": parquet_emitted,
    }


def _skip_to_gap_id(reason: str) -> str:
    if reason == "license_boundary_blocks_collection":
        return "license_boundary_blocks_collection"
    if reason in {"robots_disallow", "robots_fetch_failed"}:
        return "license_unknown"
    if reason == "not_modified":
        return "freshness_stale_or_unknown"
    return "source_receipt_incomplete"


def _upload_dir(s3: Any, local_dir: Path, bucket: str, prefix: str) -> int:
    """Upload every file under ``local_dir`` to ``s3://bucket/prefix/...``.

    Returns the number of objects uploaded.
    """

    uploaded = 0
    base = local_dir.resolve()
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        key = f"{prefix.rstrip('/')}/{rel}"
        extra: dict[str, Any] = {
            "Metadata": {
                "jpcite-project": "jpcite",
                "jpcite-credit-run": "2026-05",
            }
        }
        # Best-effort content-type hint.
        if rel.endswith(".json") or rel.endswith(".jsonl"):
            extra["ContentType"] = "application/json"
        elif rel.endswith(".parquet"):
            extra["ContentType"] = "application/octet-stream"
        s3.upload_file(str(path), bucket, key, ExtraArgs=extra)
        uploaded += 1
    return uploaded


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def run() -> int:
    # Accept both env var names so manual `submit_job.sh` (JOB_MANIFEST_S3_URI)
    # and the Step Functions orchestrator (JPCITE_MANIFEST_S3) can share the
    # same container image without a name collision. The former takes
    # precedence when both are present so existing successful invocations
    # remain bit-for-bit identical.
    manifest_uri = (
        os.environ.get("JOB_MANIFEST_S3_URI", "").strip()
        or os.environ.get("JPCITE_MANIFEST_S3", "").strip()
    )
    if not manifest_uri:
        _log(
            "error",
            "manifest_env_missing",
            detail="set JOB_MANIFEST_S3_URI or JPCITE_MANIFEST_S3 to s3://bucket/key.json",
        )
        return 2

    work_dir = Path(os.environ.get("JPCITE_WORK_DIR", "/work"))
    out_dir = work_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client("s3")

    try:
        spec = _load_manifest_from_s3(s3, manifest_uri)
    except Exception as exc:
        _log("error", "manifest_load_failed", uri=manifest_uri, error=str(exc))
        traceback.print_exc(file=sys.stderr)
        return 3

    run_id = str(
        spec.get("run_id")
        or os.environ.get("JPCITE_RUN_ID")
        or f"credit-{uuid.uuid4().hex[:12]}"
    )
    job_id = str(
        spec.get("job_id")
        or os.environ.get("JPCITE_JOB_ID")
        or os.environ.get("AWS_BATCH_JOB_ID", "")
        or "j-unknown"
    )
    # Output target resolution priority:
    #   1) spec["output_bucket"] + spec["output_prefix"] (legacy split form)
    #   2) spec["output_prefix"] as s3://bucket/prefix URI (master plan canonical form)
    #   3) env OUTPUT_S3_BUCKET + spec["output_prefix"] (Batch container override)
    raw_out_prefix = str(spec.get("output_prefix") or f"runs/{run_id}/{job_id}")
    if "output_bucket" in spec:
        output_bucket = str(spec["output_bucket"])
        output_prefix = raw_out_prefix
    elif raw_out_prefix.startswith("s3://"):
        without_scheme = raw_out_prefix[len("s3://"):]
        bucket_part, _, key_part = without_scheme.partition("/")
        output_bucket = bucket_part
        output_prefix = key_part or f"runs/{run_id}/{job_id}"
    else:
        env_bucket = os.environ.get("OUTPUT_S3_BUCKET", "").strip()
        if not env_bucket:
            _log(
                "error",
                "output_bucket_unresolved",
                detail="manifest lacks output_bucket and output_prefix is not s3:// URI, env OUTPUT_S3_BUCKET unset",
            )
            return 4
        output_bucket = env_bucket
        output_prefix = raw_out_prefix

    ctx = manifest.JobContext(
        run_id=run_id,
        job_id=job_id,
        source_id=str(spec.get("source_id", "unknown")),
        output_bucket=output_bucket,
        output_prefix=output_prefix,
        container_image_digest=os.environ.get("JPCITE_IMAGE_DIGEST", ""),
    )
    _log(
        "info",
        "manifest_loaded",
        run_id=run_id,
        job_id=job_id,
        source_id=ctx.source_id,
        target_count=len(spec.get("target_urls") or []),
    )

    policy = _build_policy(spec)
    targets, malformed_targets = _build_targets(spec)
    if malformed_targets:
        _log(
            "warn",
            "manifest_targets_malformed",
            run_id=run_id,
            job_id=job_id,
            malformed_count=len(malformed_targets),
            sample=malformed_targets[:3],
        )

    # Surface follow-mode posture on every boot so CloudWatch makes the
    # opt-in visible without grepping the manifest. Default-NONE jobs
    # log once + move on; PDF-only / same-domain jobs log the caps too.
    _log(
        "info",
        "follow_mode_configured",
        run_id=run_id,
        job_id=job_id,
        follow_mode=policy.follow_mode.value,
        follow_max_per_page=policy.follow_max_per_page,
        follow_max_total=policy.follow_max_total,
        follow_max_depth=policy.follow_max_depth,
    )

    status = "succeeded"
    stop_reason: str | None = None
    summary: dict[str, Any] = {
        "accepted_count": 0,
        "failed_count": 0,
        "known_gap_count": 0,
    }
    results: list[crawl.FetchResult] = []
    follow_emitted_total = 0

    try:
        with crawl.Fetcher(policy) as fetcher:
            results = fetcher.fetch_many(targets)
            follow_emitted_total = fetcher.follow_emitted_total
    except KeyboardInterrupt:
        status = "interrupted"
        stop_reason = "sigterm_or_spot_interrupt"
        _log("warn", "interrupted", run_id=run_id, job_id=job_id)
    except Exception as exc:
        # Fetch-time exceptions must NOT kill artifact emission. Whatever
        # partial results came back are still serialized so the operator
        # can audit progress + decide whether to re-run.
        status = "failed"
        stop_reason = f"unhandled_exception: {type(exc).__name__}"
        _log("error", "unhandled", run_id=run_id, job_id=job_id, error=str(exc))
        traceback.print_exc(file=sys.stderr)

    # Always emit artifacts — even on partial / failed fetch, the malformed
    # targets and any successful FetchResults still need to land as
    # auditable rows. _emit_artifacts is per-row resilient internally.
    try:
        summary = _emit_artifacts(
            ctx, policy, results, out_dir, malformed_targets=malformed_targets
        )
    except Exception as exc:
        # If artifact emission itself fails, surface but do not raise.
        _log(
            "error",
            "artifact_emit_failed",
            run_id=run_id,
            job_id=job_id,
            error=str(exc),
        )
        traceback.print_exc(file=sys.stderr)
        if status == "succeeded":
            status = "artifact_emit_failed"
            stop_reason = f"artifact_emit_failed: {type(exc).__name__}"

    # run_manifest is always written, even on failure, so the operator
    # can audit partial progress.
    manifest.write_run_manifest(
        out_dir / "run_manifest.json",
        ctx,
        status=status,
        input_count=len(targets),
        output_count=summary.get("accepted_count", 0) + summary.get("failed_count", 0),
        failure_count=summary.get("failed_count", 0),
        accepted_count=summary.get("accepted_count", 0),
        known_gap_count=summary.get("known_gap_count", 0),
        stop_reason=stop_reason,
        extras={
            "object_manifest_parquet": summary.get("object_manifest_parquet", False),
            "policy": {
                "license_boundary": policy.license_boundary,
                "respect_robots": policy.respect_robots,
                "request_delay_seconds": policy.request_delay_seconds,
                "max_retries": policy.max_retries,
                "follow_mode": policy.follow_mode.value,
                "follow_max_per_page": policy.follow_max_per_page,
                "follow_max_total": policy.follow_max_total,
                "follow_max_depth": policy.follow_max_depth,
            },
            "follow_stats": {
                "follow_mode": policy.follow_mode.value,
                "follow_emitted_total": follow_emitted_total,
                # output_count includes both originals + followed children;
                # follow_emitted_total tells the auditor how much of the
                # output_count came from link-following.
            },
        },
    )

    # Best-effort upload. A failure here surfaces the error but does
    # not overwrite the original status.
    try:
        uploaded = _upload_dir(s3, out_dir, output_bucket, output_prefix)
        _log(
            "info",
            "upload_complete",
            run_id=run_id,
            job_id=job_id,
            uploaded=uploaded,
            output_uri=f"s3://{output_bucket}/{output_prefix.rstrip('/')}/",
        )
    except Exception as exc:
        _log("error", "upload_failed", run_id=run_id, job_id=job_id, error=str(exc))
        traceback.print_exc(file=sys.stderr)
        if status == "succeeded":
            status = "upload_failed"
            stop_reason = f"upload_failed: {type(exc).__name__}"

    if status == "succeeded":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(run())
