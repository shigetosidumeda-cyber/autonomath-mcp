"""Wave 59-H outcome verifier — runs the 5-assertion DSL across all
top-10 outcome packets that have landed in S3.

Loads every assertion JSON under ``data/outcome_assertions/``, resolves the
outcome to an S3 prefix, samples N packets from that prefix, evaluates the
5 deterministic invariants (schema_present, known_gaps_valid,
packet_size_within_band, citation_uri_valid, packet_freshness), and writes a
JSON Lines ledger to ``out/outcome_verifier_ledger_<timestamp>.jsonl``.

Pure schema + value checks. **No LLM call** — the verifier is allowed to run
on the operator side because every assertion is a deterministic predicate
implemented in ``src/jpintel_mcp/agent_runtime/outcome_assertions.py``.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import random
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Make the repo's ``src`` importable when invoked as a plain script.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SRC_DIR: Path = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jpintel_mcp.agent_runtime.outcome_assertions import (  # noqa: E402
    AssertionSpec,
    PacketVerification,
    verify_packet,
)

LOG = logging.getLogger("verify_outcomes")

#: Top-10 outcome → S3 prefix (under
#: ``s3://jpcite-credit-993693061769-202605-derived/``).
#:
#: 4 outcomes have JSON packets in S3 today; the remaining 6 either ship as
#: parquet (``source_receipts``) or have not yet been generated. The
#: verifier emits ``skipped`` rows with ``reason="no_packets_in_prefix"`` so
#: the daily GHA workflow stays green and surfaces the gap as a ledger row
#: rather than a hard failure.
OUTCOME_TO_PREFIX: dict[str, str] = {
    "application_strategy": "application_strategy_v1/",
    "company_public_baseline": "company_public_baseline_v1/",
    "invoice_registrant_public_check": "invoice_registrant_public_check_v1/",
    "local_government_permit_obligation_map": "local_government_subsidy_aggregator_v1/",
    # parquet packet (J01_source_profile); JSON-shaped JPCIR not yet emitted.
    "source_receipt_ledger": "source_receipts/",
    # Below outcomes do not yet have a dedicated S3 prefix — verifier will
    # emit ``skipped`` ledger rows. Wired here so the loader sees them.
    "client_monthly_review": "",
    "court_enforcement_citation_pack": "",
    "evidence_answer": "",
    "public_statistics_market_context": "",
    "regulation_change_watch": "",
}

DEFAULT_BUCKET: str = "jpcite-credit-993693061769-202605-derived"
DEFAULT_SAMPLE_SIZE: int = 10
DEFAULT_PROFILE: str = "bookyou-recovery"


@dataclass(frozen=True)
class OutcomeReport:
    """Roll-up for one outcome over its sampled packets."""

    outcome_id: str
    prefix: str
    sampled: int
    passed: int
    failed: int
    skipped: bool
    skip_reason: str = ""

    @property
    def all_passed(self) -> bool:
        return (not self.skipped) and self.failed == 0 and self.sampled > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "prefix": self.prefix,
            "sampled": self.sampled,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "all_passed": self.all_passed,
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_assertion_specs(directory: Path) -> list[AssertionSpec]:
    """Load every JSON assertion file under ``directory`` into specs."""

    if not directory.is_dir():
        msg = f"assertion directory not found: {directory}"
        raise FileNotFoundError(msg)
    specs: list[AssertionSpec] = []
    for path in sorted(directory.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        specs.append(AssertionSpec.from_dict(data))
    return specs


# ---------------------------------------------------------------------------
# S3 sampler
# ---------------------------------------------------------------------------


def _import_boto3_session(profile: str) -> Any:  # pragma: no cover - lazy
    """Lazy boto3 session import (keeps the script importable test-side)."""

    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = "boto3 is required for the verifier; pip install boto3"
        raise RuntimeError(msg) from exc
    return boto3.Session(profile_name=profile)


def iter_packet_keys(
    *, s3_client: Any, bucket: str, prefix: str, max_keys: int = 1000
) -> Iterator[str]:
    """Yield up to ``max_keys`` JSON packet keys under ``prefix``."""

    paginator = s3_client.get_paginator("list_objects_v2")
    yielded = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            yield key
            yielded += 1
            if yielded >= max_keys:
                return


def read_packet(*, s3_client: Any, bucket: str, key: str) -> dict[str, Any]:
    """Download + decode a JSON packet from S3."""

    buf = io.BytesIO()
    s3_client.download_fileobj(bucket, key, buf)
    payload: dict[str, Any] = json.loads(buf.getvalue().decode("utf-8"))
    return payload


# ---------------------------------------------------------------------------
# Verifier core
# ---------------------------------------------------------------------------


def verify_outcome(
    *,
    spec: AssertionSpec,
    s3_client: Any,
    bucket: str,
    sample_size: int,
    list_cap: int,
    rng: random.Random,
    now: datetime | None = None,
) -> tuple[OutcomeReport, list[PacketVerification]]:
    """Sample + verify one outcome's S3 packets."""

    prefix = OUTCOME_TO_PREFIX.get(spec.outcome_id, "")
    if not prefix:
        return (
            OutcomeReport(
                outcome_id=spec.outcome_id,
                prefix="",
                sampled=0,
                passed=0,
                failed=0,
                skipped=True,
                skip_reason="no_prefix_mapped",
            ),
            [],
        )

    # parquet outcomes (e.g. ``source_receipts/``) are skipped — the DSL only
    # speaks JPCIR JSON. The verifier emits a ``skipped`` ledger row so the
    # gap surfaces transparently.
    if spec.outcome_id == "source_receipt_ledger":
        return (
            OutcomeReport(
                outcome_id=spec.outcome_id,
                prefix=prefix,
                sampled=0,
                passed=0,
                failed=0,
                skipped=True,
                skip_reason="parquet_storage_not_jpcir_json",
            ),
            [],
        )

    keys = list(
        iter_packet_keys(
            s3_client=s3_client, bucket=bucket, prefix=prefix, max_keys=list_cap
        )
    )
    if not keys:
        return (
            OutcomeReport(
                outcome_id=spec.outcome_id,
                prefix=prefix,
                sampled=0,
                passed=0,
                failed=0,
                skipped=True,
                skip_reason="no_packets_in_prefix",
            ),
            [],
        )

    sampled = rng.sample(keys, k=min(sample_size, len(keys)))
    verifications: list[PacketVerification] = []
    passed = failed = 0
    for key in sampled:
        envelope = read_packet(s3_client=s3_client, bucket=bucket, key=key)
        verification = verify_packet(
            envelope=envelope,
            spec=spec,
            s3_key=f"s3://{bucket}/{key}",
            now=now,
        )
        verifications.append(verification)
        if verification.all_passed:
            passed += 1
        else:
            failed += 1
    return (
        OutcomeReport(
            outcome_id=spec.outcome_id,
            prefix=prefix,
            sampled=len(sampled),
            passed=passed,
            failed=failed,
            skipped=False,
        ),
        verifications,
    )


# ---------------------------------------------------------------------------
# Ledger writer
# ---------------------------------------------------------------------------


def write_ledger(
    *,
    out_path: Path,
    reports: list[OutcomeReport],
    verifications: list[PacketVerification],
    run_metadata: dict[str, Any],
) -> None:
    """Write JSON Lines ledger with metadata header + outcome summary + per-packet rows."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"row_kind": "metadata", **run_metadata}, ensure_ascii=False)
            + "\n"
        )
        for report in reports:
            fh.write(
                json.dumps(
                    {"row_kind": "outcome_summary", **report.to_dict()},
                    ensure_ascii=False,
                )
                + "\n"
            )
        for verification in verifications:
            fh.write(
                json.dumps(
                    {"row_kind": "packet_verification", **verification.to_dict()},
                    ensure_ascii=False,
                )
                + "\n"
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assertion-dir",
        type=Path,
        default=REPO_ROOT / "data" / "outcome_assertions",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "out",
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE", DEFAULT_PROFILE),
        help=f"AWS profile (default: {DEFAULT_PROFILE} or $AWS_PROFILE)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help="packets sampled per outcome",
    )
    parser.add_argument(
        "--list-cap",
        type=int,
        default=1000,
        help="max keys to list per outcome prefix (sampling pool)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fail-on-failures",
        action="store_true",
        help="exit 1 if any non-skipped outcome has failures",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    specs = load_assertion_specs(args.assertion_dir)
    LOG.info("loaded %d assertion specs from %s", len(specs), args.assertion_dir)

    rng = random.Random(args.seed)
    now = datetime.now(tz=UTC)
    stamp = _stamp(now)
    out_path = args.out_dir / f"outcome_verifier_ledger_{stamp}.jsonl"

    reports: list[OutcomeReport] = []
    verifications: list[PacketVerification] = []

    if args.dry_run:
        LOG.info("dry-run — skipping S3 calls; emitting plan only")
        reports.extend(
            OutcomeReport(
                outcome_id=spec.outcome_id,
                prefix=OUTCOME_TO_PREFIX.get(spec.outcome_id, ""),
                sampled=0,
                passed=0,
                failed=0,
                skipped=True,
                skip_reason="dry_run",
            )
            for spec in specs
        )
        write_ledger(
            out_path=out_path,
            reports=reports,
            verifications=verifications,
            run_metadata={
                "timestamp_utc": now.isoformat(),
                "bucket": args.bucket,
                "sample_size": args.sample_size,
                "dry_run": True,
                "specs_count": len(specs),
            },
        )
        LOG.info("dry-run ledger written: %s", out_path)
        return 0

    session = _import_boto3_session(args.profile)
    s3_client = session.client("s3")
    for spec in specs:
        LOG.info("verifying %s ...", spec.outcome_id)
        report, packet_verifs = verify_outcome(
            spec=spec,
            s3_client=s3_client,
            bucket=args.bucket,
            sample_size=args.sample_size,
            list_cap=args.list_cap,
            rng=rng,
            now=now,
        )
        reports.append(report)
        verifications.extend(packet_verifs)
        LOG.info(
            "  %s sampled=%d passed=%d failed=%d skipped=%s%s",
            spec.outcome_id,
            report.sampled,
            report.passed,
            report.failed,
            report.skipped,
            f" ({report.skip_reason})" if report.skipped else "",
        )

    write_ledger(
        out_path=out_path,
        reports=reports,
        verifications=verifications,
        run_metadata={
            "timestamp_utc": now.isoformat(),
            "bucket": args.bucket,
            "sample_size": args.sample_size,
            "dry_run": False,
            "specs_count": len(specs),
        },
    )
    LOG.info("ledger written: %s", out_path)

    failures = sum(r.failed for r in reports if not r.skipped)
    skipped = sum(1 for r in reports if r.skipped)
    LOG.info(
        "summary: outcomes=%d skipped=%d failures=%d packets_verified=%d",
        len(reports),
        skipped,
        failures,
        len(verifications),
    )

    if args.fail_on_failures and failures > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry
    raise SystemExit(main())
