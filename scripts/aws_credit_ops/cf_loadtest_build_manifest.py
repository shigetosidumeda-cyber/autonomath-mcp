#!/usr/bin/env python3
"""Build a flat S3 key manifest for the CloudFront load tester.

Walks ``s3://jpcite-credit-993693061769-202605-derived/`` and writes a
newline-delimited file with up to ``--max-keys`` keys (default 100_000).
Cheap: uses paginated ListObjectsV2, no data download.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _iter_keys(
    bucket: str,
    prefixes: list[str],
    *,
    profile: str,
    region: str,
    max_keys: int,
) -> Iterator[str]:
    import boto3

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")
    yielded = 0
    paginator = s3.get_paginator("list_objects_v2")
    for prefix in prefixes:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents") or []:
                key = obj.get("Key")
                if not key:
                    continue
                yield str(key)
                yielded += 1
                if yielded >= max_keys:
                    return


def _parse_argv(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="build CloudFront load-test manifest")
    p.add_argument("--bucket", default="jpcite-credit-993693061769-202605-derived")
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--profile", default="bookyou-recovery")
    p.add_argument(
        "--prefix",
        action="append",
        default=[
            "vendor_due_diligence_v1/",
            "houjin_360/",
            "company_public_baseline_v1/",
            "invoice_houjin_cross_check_v1/",
            "permit_renewal_calendar_v1/",
            "regulatory_change_radar_v1/",
            "subsidy_application_timeline_v1/",
        ],
        help="prefix to walk (may be passed multiple times)",
    )
    p.add_argument("--max-keys", type=int, default=100_000)
    p.add_argument(
        "--out",
        default="infra/aws/cloudfront/jpcite_packet_keys.txt",
        help="output manifest path",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with out_path.open("w", encoding="utf-8") as fp:
        for key in _iter_keys(
            args.bucket,
            list(args.prefix),
            profile=args.profile,
            region=args.region,
            max_keys=args.max_keys,
        ):
            fp.write(key + "\n")
            count += 1

    logger.info("wrote %d keys to %s", count, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
