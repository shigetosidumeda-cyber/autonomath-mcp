"""Lane E — Athena sustained burn Lambda wrapper.

This module is the Lambda entry point for the
``jpcite-athena-sustained-2026-05`` EventBridge schedule. It defers all
logic to ``scripts/aws_credit_ops/athena_sustained_query_2026_05_17.py``
which is co-zipped into the deployment artifact.

The Lambda runs **one Athena query per fire** (the EventBridge rule
``rate(5 minutes)`` produces 288 fires/day → ~$50/day burn at
~$0.17/query average).
"""

from __future__ import annotations

from typing import Any

from athena_sustained_query_2026_05_17 import lambda_handler as _runner_handler


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Forward to the canonical runner — keeps deployment surface thin."""
    return _runner_handler(event, context)
