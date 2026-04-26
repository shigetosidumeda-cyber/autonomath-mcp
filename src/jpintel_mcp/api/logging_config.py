"""Structlog configuration for jpintel-mcp.

JSON lines on stdout (Fly.io ingests stdout). Dev mode (JPINTEL_LOG_FORMAT=console)
gives pretty colored output. contextvars carry request_id + api_key_hash_prefix
bound by middleware / deps.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, merge_contextvars


def _shared_processors() -> list[Any]:
    return [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    level_no = getattr(logging, level.upper(), logging.INFO)

    renderer: Any
    if fmt == "console":
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    else:
        renderer = structlog.processors.JSONRenderer()

    shared = _shared_processors()

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level_no)

    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(level_no, logging.INFO))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_api_key_context(key_hash: str | None, tier: str) -> None:
    if key_hash:
        bind_contextvars(api_key_hash_prefix=key_hash[:8], tier=tier)
    else:
        bind_contextvars(api_key_hash_prefix=None, tier=tier)
