#!/usr/bin/env python3
"""Thin CLI shim around `jpintel_mcp.email.scheduler.main()`.

Kept for parity with the ops runbook / nightly workflow references. All the
real logic lives in `src/jpintel_mcp/email/scheduler.py` so the module is
also invokable as `python -m jpintel_mcp.email.scheduler`.

Usage (inside the Fly.io machine):
    /app/.venv/bin/python /app/scripts/send_scheduled_emails.py
    /app/.venv/bin/python /app/scripts/send_scheduled_emails.py --dry-run

Exit code 0 means the run completed (sends may individually have failed —
see the JSON summary on stderr). Non-zero means the dispatcher itself hit
an unhandled error; inspect stderr for the traceback.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `src/` importable when this script is invoked directly (e.g. from the
# Fly.io machine before the package is pip-installed into .venv). When the
# package IS already installed, this sys.path prepend is a harmless no-op.
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Default DB path to the Fly.io mount unless JPINTEL_DB_PATH is already set.
os.environ.setdefault("JPINTEL_DB_PATH", "/data/jpintel.db")

from jpintel_mcp.email.scheduler import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
