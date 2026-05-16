#!/usr/bin/env python3
"""Wave 43.1.3 weekly cron: refresh 民間助成財団 ingest.

Wraps ``scripts/etl/fill_programs_foundation_2x.py`` for weekly cadence.
Memory `feedback_no_operator_llm_api` honored — pure stdlib + subprocess.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("jpcite.cron.refresh_foundation_weekly")

REPO_ROOT = Path(__file__).resolve().parents[2]
ETL_SCRIPT = REPO_ROOT / "scripts" / "etl" / "fill_programs_foundation_2x.py"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    started = datetime.now(UTC).isoformat()
    logger.info("refresh_foundation_weekly started at %s", started)
    if not ETL_SCRIPT.exists():
        logger.error("ETL script missing: %s", ETL_SCRIPT)
        return 2
    max_rows = os.environ.get("FOUNDATION_MAX_ROWS", "2000")
    cmd = [
        sys.executable,
        str(ETL_SCRIPT),
        "--source",
        "all",
        "--max-rows",
        str(max_rows),
    ]
    logger.info("invoking: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        logger.error("ETL timed out after 30 min")
        return 3
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    logger.info("refresh_foundation_weekly finished rc=%d (started=%s)", r.returncode, started)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
