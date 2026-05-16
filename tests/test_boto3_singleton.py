"""Smoke tests for :mod:`scripts.aws_credit_ops._aws` client pooling.

These tests assert the contract documented in the module: ``lru_cache``
returns the same client instance for the same ``(service, region_name)``
tuple. They do **not** exercise AWS — boto3 client construction is
local + offline (no credentials needed to instantiate a client object).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_aws_cache() -> None:
    """Clear the module-level lru_cache before every test.

    Other test modules may have warmed the cache; resetting keeps each
    test hermetic.
    """
    pytest.importorskip("boto3")
    from scripts.aws_credit_ops import _aws

    _aws.reset_cache()


def test_get_client_returns_same_instance_for_same_args() -> None:
    """Two calls with identical args must return the SAME object."""
    from scripts.aws_credit_ops._aws import get_client

    s3_a = get_client("s3", region_name="ap-northeast-1")
    s3_b = get_client("s3", region_name="ap-northeast-1")

    assert s3_a is s3_b, "lru_cache must return identical client instance"


def test_get_client_distinct_for_different_service() -> None:
    """Different services share no cache slot."""
    from scripts.aws_credit_ops._aws import get_client

    s3 = get_client("s3", region_name="ap-northeast-1")
    sns = get_client("sns", region_name="ap-northeast-1")

    assert s3 is not sns


def test_get_client_distinct_for_different_region() -> None:
    """Different regions share no cache slot (e.g. CE us-east-1 vs apne1)."""
    from scripts.aws_credit_ops._aws import get_client

    apne1 = get_client("s3", region_name="ap-northeast-1")
    use1 = get_client("s3", region_name="us-east-1")

    assert apne1 is not use1


def test_s3_client_convenience_wrapper_matches_get_client() -> None:
    """``s3_client()`` is a thin alias for ``get_client('s3', ...)``."""
    from scripts.aws_credit_ops._aws import get_client, s3_client

    a = s3_client()
    b = get_client("s3", region_name="ap-northeast-1")

    assert a is b


def test_ce_client_default_region_is_us_east_1() -> None:
    """Cost Explorer is global → us-east-1 endpoint."""
    from scripts.aws_credit_ops._aws import ce_client, get_client

    a = ce_client()
    b = get_client("ce", region_name="us-east-1")

    assert a is b


def test_reset_cache_clears_cached_clients() -> None:
    """After ``reset_cache``, the next call rebuilds the client."""
    from scripts.aws_credit_ops._aws import get_client, reset_cache

    first = get_client("s3", region_name="ap-northeast-1")
    reset_cache()
    second = get_client("s3", region_name="ap-northeast-1")

    # New construction → different object identity. (boto3 returns a
    # fresh client every time the underlying factory is called.)
    assert first is not second


def test_convenience_wrappers_are_all_pooled() -> None:
    """Each convenience wrapper hits the same lru_cache as ``get_client``.

    The wrappers forward ``region_name`` as a keyword arg with the
    :data:`DEFAULT_REGION` default; the test mirrors that exact call
    shape so the lru_cache slots line up (lru_cache distinguishes
    positional vs keyword arg passing in its cache key).
    """
    from scripts.aws_credit_ops._aws import (
        DEFAULT_REGION,
        batch_client,
        cloudwatch_client,
        get_client,
        s3_client,
        sagemaker_client,
        sns_client,
        textract_client,
    )

    pairs = [
        (s3_client(), get_client("s3", region_name=DEFAULT_REGION)),
        (batch_client(), get_client("batch", region_name=DEFAULT_REGION)),
        (sns_client(), get_client("sns", region_name=DEFAULT_REGION)),
        (cloudwatch_client(), get_client("cloudwatch", region_name=DEFAULT_REGION)),
        (sagemaker_client(), get_client("sagemaker", region_name=DEFAULT_REGION)),
        (textract_client(), get_client("textract", region_name=DEFAULT_REGION)),
    ]
    for wrapper, direct in pairs:
        assert wrapper is direct
