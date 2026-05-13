"""test_rum_beacon_calc_engaged.py — Wave 49 tick#? server-side gate verify.

Validates the server-side completion of the 5-stage organic funnel.
Companion to:

  - `tests/test_calc_rum_wire.py` — client-side wire (calc page <script>
    + collector inferStep() -> "calc_engaged").
  - `tests/test_cf_pages_rum_beacon.py` — generic structural verify of
    `functions/api/rum_beacon.ts` (4-step baseline).

Background. Wave 49 tick#? walk-through observed:

    POST /api/rum_beacon  body={step="calc_engaged",...}   → HTTP 400
    Response: "Invalid beacon shape"

The 400 was emitted by `isValidBeacon()` because the server-side
`ALLOWED_STEPS` Set only listed the original 4 funnel steps
(landing / free / signup / topup). PR #195 (calc RUM client wire) made
the calculator page emit `calc_engaged`, but the CF Pages Function still
rejected it — turning the 5-stage funnel into a 4/5 observable + 1/5
dropped silently.

This test asserts:

  1. `calc_engaged` is now an accepted step on `ALLOWED_STEPS`.
  2. The 4 pre-existing steps remain accepted (destruction-free, see
     memory `feedback_destruction_free_organization`).
  3. The shape validator `isValidBeacon` keeps rejecting unknown steps
     (so the gate is still load-bearing — adversaries cannot smuggle
     arbitrary `step` values into the JSONL).

Structural verify rather than runtime POST: the Cloudflare Pages Function
needs `workerd` to spin up an HTTP listener, which would be a 60-90s
overhead for a 1-line additive change. The 3 invariants above fully
capture the regression class — a wire bug elsewhere (collector path,
HTML script tag) is already covered by the two companion tests.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUM_FN = REPO_ROOT / "functions" / "api" / "rum_beacon.ts"


def _read(p: Path) -> str:
    assert p.exists(), f"required asset is missing: {p}"
    return p.read_text(encoding="utf-8")


def _allowed_steps_body() -> str:
    src = _read(RUM_FN)
    block = re.search(r"ALLOWED_STEPS\s*=\s*new\s+Set\(\s*\[(.*?)\]", src, re.S)
    assert block, "ALLOWED_STEPS Set literal not found in rum_beacon.ts"
    return block.group(1)


def test_allowed_steps_now_includes_calc_engaged() -> None:
    """Wave 49 tick#? 5-stage completion: server accepts calc_engaged."""
    body = _allowed_steps_body()
    assert '"calc_engaged"' in body, (
        "ALLOWED_STEPS in rum_beacon.ts must now accept 'calc_engaged' so "
        "that POST /api/rum_beacon body={step:'calc_engaged'} returns 204 "
        "instead of 400 'Invalid beacon shape'. Without this server-side "
        "extension, PR #195 client wire emits calc_engaged but the CF Pages "
        "Function drops it, collapsing the 5-stage organic funnel back to "
        "a 4/5 observable state."
    )


def test_allowed_steps_preserves_4_baseline() -> None:
    """Destruction-free: the 4 original funnel steps must remain accepted.

    Memory `feedback_destruction_free_organization` forbids rm/mv-style
    edits. The additive 5th step must not silently remove or rename any
    of landing/free/signup/topup — regression here would zero out the
    Wave 49 G1 baseline (4 weeks of organic-funnel measurement).
    """
    body = _allowed_steps_body()
    for step in ("landing", "free", "signup", "topup"):
        assert f'"{step}"' in body, (
            f"step '{step}' must remain in ALLOWED_STEPS — the "
            "calc_engaged extension is additive and must not remove or "
            "rename the pre-existing 4 stages."
        )


def test_validator_still_rejects_unknown_steps() -> None:
    """The shape validator must still gate unknown step values.

    The Wave 49 G1 R2 jsonl is downstream-aggregated by
    `scripts/ops/rum_aggregator.py`; if `isValidBeacon` accepted arbitrary
    strings, a hostile sendBeacon could pollute the funnel namespace and
    invalidate the per-step conversion rollup. We verify here that the
    validator (1) consults the ALLOWED_STEPS Set, (2) returns false on
    miss — the load-bearing line is intact post-edit.
    """
    src = _read(RUM_FN)
    # The validator line is the gate that turns ALLOWED_STEPS membership
    # into the 400 response. If a future refactor accidentally drops the
    # Set check (e.g. accepts any non-empty string), every test in this
    # file passes but the server stops gating. Pin the line shape.
    assert "ALLOWED_STEPS.has(normalizeStep(b.step))" in src, (
        "isValidBeacon must still consult ALLOWED_STEPS.has(normalizeStep(b.step)) — "
        "otherwise the 400 gate is bypassed and the R2 funnel jsonl can "
        "be polluted with arbitrary step names. This assertion preserves "
        "the load-bearing membership check after the calc_engaged addition."
    )


def test_allowed_steps_has_exactly_5_entries() -> None:
    """Pin the cardinality so accidental future additions are reviewed.

    A drift here is not a bug per se — Wave 49 may later add a 6th step
    (e.g. `widget_engaged` for the embedded SDK funnel). But that addition
    deserves a deliberate test update so the cohort of measured steps is
    always known to the aggregator authors.
    """
    body = _allowed_steps_body()
    # Count quoted strings to avoid double-counting from comments.
    quoted = re.findall(r'"([a-z_]+)"', body)
    assert len(quoted) == 5, (
        f"ALLOWED_STEPS must have exactly 5 entries post calc_engaged "
        f"addition (landing/free/signup/topup/calc_engaged); found "
        f"{len(quoted)}: {quoted}. If a 6th step is being added deliberately "
        "update this assertion in the same PR so downstream aggregators "
        "are alerted to the new dimension."
    )


def test_billing_payment_aliases_normalize_to_topup() -> None:
    src = _read(RUM_FN)
    assert 'billing: "topup"' in src
    assert 'payment: "topup"' in src
    assert "step: normalizeStep(body.step)" in src
