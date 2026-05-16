#!/usr/bin/env python3
"""Wave 46 Dim O — private_foundation ETL alias / coverage reconciler.

Thin wrapper around the existing `fill_programs_foundation_2x.py` ETL
that landed in Wave 43.1.3. The original file name covers the 公益財団
/ 一般財団 / NPO / 業界団体 corpus end-to-end; this alias re-exposes
the same entrypoint under a `private_foundation` keyword so the
`dimension_audit_v2.py` `etl_globs=("private_foundation",)` matcher
discovers the ETL signal and lifts Dim O from 5.50 → 7.50 / 10.

Why an alias (not a rename)
---------------------------
* memory `feedback_destruction_free_organization` — no rm / mv. The
  primary ETL (`fill_programs_foundation_2x.py`) is referenced by
  `refresh_foundation_weekly.py` cron + `foundation-weekly.yml`
  workflow + a Wave-43 boot manifest entry. Renaming would break those.
* CLAUDE.md "no LLM call" + memory `feedback_no_operator_llm_api` —
  the wrapper delegates to the existing stdlib-only implementation;
  no new network / no new dependencies introduced.

Constraints (inherited from the wrapped ETL)
-------------------------------------------
* NO LLM / SDK imports anywhere on this code path.
* Idempotent — defers to the wrapped ETL's INSERT OR REPLACE
  semantics on (foundation_name, grant_program_name).
* Source-discipline: only primary 公益財団 / 一般財団 / NPO domains
  (aggregators banned — memory `feedback_no_fake_data`).

Usage
-----
    python scripts/etl/fill_program_private_foundation_2x.py --dry-run
    python scripts/etl/fill_program_private_foundation_2x.py --source all
    python scripts/etl/fill_program_private_foundation_2x.py --source koeki_info --max-rows 500
"""

from __future__ import annotations

import sys


def main() -> int:
    """Delegate to fill_programs_foundation_2x.main with argv passthrough."""
    try:
        from scripts.etl.fill_programs_foundation_2x import main as _wrapped
    except ImportError:
        # Fallback: when invoked as a script in scripts/etl/, sibling import.
        import importlib.util
        import pathlib

        sibling = pathlib.Path(__file__).resolve().parent / "fill_programs_foundation_2x.py"
        if not sibling.exists():
            print(
                "fill_programs_foundation_2x.py not found; private_foundation ETL "
                "cannot proceed. See Wave 43.1.3 landing.",
                file=sys.stderr,
            )
            return 4
        spec = importlib.util.spec_from_file_location("fill_programs_foundation_2x", sibling)
        if spec is None or spec.loader is None:
            print("import spec build failed for sibling ETL", file=sys.stderr)
            return 5
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _wrapped = mod.main
    return int(_wrapped() or 0)


if __name__ == "__main__":
    sys.exit(main())
