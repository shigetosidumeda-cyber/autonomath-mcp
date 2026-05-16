"""Cached boto3 client factory shared by ``scripts/aws_credit_ops/`` modules.

boto3 client construction goes through a Session-level credential resolution
+ endpoint discovery + metadata cache warm-up. Empirically this adds
200-500 ms per ``boto3.client(...)`` call on a cold runtime (Lambda init,
GitHub Actions runner, fresh `python -m scripts.aws_credit_ops.xxx` invocation).

Most of our ops scripts construct the *same* (service, region) pair on every
run -- often 2 or 3 times across the codebase, sometimes inside a hot loop.
This module memoises construction per ``(service, region_name)`` tuple so the
cold-start tax is paid exactly once per process.

Usage::

    from scripts.aws_credit_ops._aws import s3_client, ce_client, get_client

    s3 = s3_client()                       # region defaults to ap-northeast-1
    ce = ce_client(region_name="us-east-1")  # CE only lives in us-east-1
    batch = get_client("batch")            # arbitrary service

The cache is process-local. There is no eviction -- boto3 clients are cheap
to hold (sockets are lazily opened by botocore and reused across calls). To
hard-reset the cache (e.g. between unit tests that mock boto3), call
:func:`reset_cache`.

The factory does **not** change any AWS behavior. Credentials, region, retry
config, and signing all come from the underlying boto3 default
``Session`` -- this module is purely a memoisation layer.
"""

from __future__ import annotations

from functools import cache
from typing import Any

DEFAULT_REGION: str = "ap-northeast-1"
"""Tokyo region; matches ``aws_credit_ops`` canonical region across scripts."""


def _import_boto3() -> Any:
    """Import boto3 lazily so unit tests without boto3 installed still load.

    boto3 is heavy (imports botocore + pulls service models lazily); the
    indirection keeps module-import side effects light and lets test
    runners that mock the AWS surface avoid the dependency entirely.
    """
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:  # pragma: no cover - environment guard
        msg = (
            "boto3 is not installed. Install it in the operator environment "
            "(pip install boto3) before invoking aws_credit_ops scripts."
        )
        raise RuntimeError(msg) from exc
    return boto3


@cache
def get_client(service: str, region_name: str = DEFAULT_REGION) -> Any:
    """Return a cached boto3 client for ``(service, region_name)``.

    Calls with identical arguments return the *same* underlying client
    instance -- no second ``Session`` construction, no second metadata
    cache warm-up. This saves 200-500 ms on the second-through-N-th call
    in a single process.
    """
    boto3 = _import_boto3()
    return boto3.client(service, region_name=region_name)


def s3_client(region_name: str = DEFAULT_REGION) -> Any:
    """Return the cached S3 client. Convenience wrapper for the hot path."""
    return get_client("s3", region_name=region_name)


def ce_client(region_name: str = "us-east-1") -> Any:
    """Return the cached Cost Explorer client.

    Cost Explorer is a global service surfaced via us-east-1; the default
    here intentionally diverges from :data:`DEFAULT_REGION` to match AWS
    behavior (callers that pass a different region get their own cache
    slot via the keyword arg).
    """
    return get_client("ce", region_name=region_name)


def batch_client(region_name: str = DEFAULT_REGION) -> Any:
    """Return the cached AWS Batch client."""
    return get_client("batch", region_name=region_name)


def sns_client(region_name: str = DEFAULT_REGION) -> Any:
    """Return the cached SNS client."""
    return get_client("sns", region_name=region_name)


def cloudwatch_client(region_name: str = DEFAULT_REGION) -> Any:
    """Return the cached CloudWatch client."""
    return get_client("cloudwatch", region_name=region_name)


def sagemaker_client(region_name: str = DEFAULT_REGION) -> Any:
    """Return the cached SageMaker client."""
    return get_client("sagemaker", region_name=region_name)


def textract_client(region_name: str = DEFAULT_REGION) -> Any:
    """Return the cached Textract client."""
    return get_client("textract", region_name=region_name)


def reset_cache() -> None:
    """Drop all cached clients. Intended for unit tests that mock boto3."""
    get_client.cache_clear()


__all__ = [
    "DEFAULT_REGION",
    "batch_client",
    "ce_client",
    "cloudwatch_client",
    "get_client",
    "reset_cache",
    "s3_client",
    "sagemaker_client",
    "sns_client",
    "textract_client",
]
