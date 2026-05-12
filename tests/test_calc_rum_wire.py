"""test_calc_rum_wire.py — Wave 49 tick#3 calc RUM wire structural verify.

Validates the additive wiring done by Wave 49 tick#3 to extend the G1
organic funnel from 4 → 5 stages by adding `calc_engaged`:

  - `site/tools/cost_saving_calculator.html` loads
    `/assets/rum_funnel_collector.js` (defer) before `</body>`.
  - `site/assets/rum_funnel_collector.js` `inferStep()` maps the
    canonical calculator path → `calc_engaged`.
  - The 4 pre-existing steps (landing / free / signup / topup) remain
    intact — additive change, never destructive (see memory
    `feedback_destruction_free_organization`).
  - The calculator page dispatches `jpcite:funnel:complete` on first
    user interaction so the collector emits a step_complete beacon
    once a real engagement happens (not just a page view).

Why structural and not runtime? Wave 49 G1 is a measurement layer.
The only mistake that silently breaks the 5-stage funnel is a
typo in the path mapping or a missing script tag — a Playwright
spin-up would multiply CI minutes for one PR without catching any
additional class of bug.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CALC_HTML = REPO_ROOT / "site" / "tools" / "cost_saving_calculator.html"
RUM_JS = REPO_ROOT / "site" / "assets" / "rum_funnel_collector.js"


def _read(p: Path) -> str:
    assert p.exists(), f"required asset is missing: {p}"
    return p.read_text(encoding="utf-8")


def test_calculator_html_loads_rum_funnel_collector() -> None:
    html = _read(CALC_HTML)
    # Tag must point at the canonical absolute path so the collector
    # works on both / and /tools/cost_saving_calculator/.
    pattern = re.compile(
        r"""<script[^>]+src=["']/assets/rum_funnel_collector\.js["'][^>]*>""",
        re.IGNORECASE,
    )
    assert pattern.search(html), (
        "cost_saving_calculator.html must include "
        "<script src='/assets/rum_funnel_collector.js'> to emit Wave 49 G1 "
        "funnel beacons (step=calc_engaged)."
    )
    # The tag must be placed before </body> so deferred load is honored
    # by every browser (defer requires the script element to be a child
    # of the document, not appended later by JS).
    body_close = html.lower().rfind("</body>")
    tag_pos = pattern.search(html).start()
    assert tag_pos < body_close, (
        "rum_funnel_collector.js script tag must appear before </body>; "
        "found at pos %d, </body> at pos %d." % (tag_pos, body_close)
    )
    # The tag must use defer so it does not block the calculator's own
    # inline render() function (page-fast policy).
    deferred = re.compile(
        r"""<script[^>]+src=["']/assets/rum_funnel_collector\.js["'][^>]*\bdefer\b[^>]*>""",
        re.IGNORECASE,
    )
    assert deferred.search(html), (
        "rum_funnel_collector.js must be loaded with defer attribute "
        "so the inline calculator script (which is module-free) keeps "
        "its existing parse-then-execute timing."
    )


def test_calculator_html_dispatches_funnel_complete_event() -> None:
    html = _read(CALC_HTML)
    # Wave 49 tick#3: the page itself decides what "engaged" means.
    # The collector listens for `jpcite:funnel:complete` and turns
    # that into a step_complete beacon. Without this dispatch a page
    # view alone would emit only `view`, which is indistinguishable
    # from a bounce.
    assert "jpcite:funnel:complete" in html, (
        "cost_saving_calculator.html must dispatch CustomEvent "
        "'jpcite:funnel:complete' on first user interaction so the "
        "RUM collector can emit a step_complete beacon."
    )


def test_rum_collector_inferstep_has_calc_engaged_case() -> None:
    js = _read(RUM_JS)
    # 5th step must be present.
    assert "calc_engaged" in js, (
        "rum_funnel_collector.js inferStep() must include a "
        "'calc_engaged' return case so /tools/cost_saving_calculator "
        "is counted as a distinct funnel stage (Wave 49 tick#3 G1 5-stage)."
    )
    # Path mapping must be anchored to the canonical calculator path.
    # We allow either == or indexOf===0 form to keep the test resilient
    # against future minor refactors of the matcher.
    path_match = re.compile(
        r"""/tools/cost_saving_calculator""",
        re.IGNORECASE,
    )
    assert path_match.search(js), (
        "rum_funnel_collector.js must reference the canonical path "
        "'/tools/cost_saving_calculator' in inferStep() so the engine "
        "actually maps the calculator URL → calc_engaged."
    )


def test_rum_collector_preserves_4_pre_existing_steps() -> None:
    """Destruction-free: the 4 original funnel steps must remain.

    Memory `feedback_destruction_free_organization` forbids rm/mv-style
    edits. The additive 5-stage wire must keep landing/free/signup/topup
    intact — regression here would silently zero out 4 weeks of Wave 49
    G1 baseline data.
    """
    js = _read(RUM_JS)
    for step in ("landing", "free", "signup", "topup"):
        assert (
            f'"{step}"' in js or f"'{step}'" in js
        ), (
            f"step '{step}' must remain in rum_funnel_collector.js — "
            "the calc_engaged extension is additive and must not "
            "remove or rename the pre-existing 4 stages."
        )
