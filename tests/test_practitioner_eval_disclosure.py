"""Practitioner public eval disclosure guard.

Asserts that the public practitioner-eval surface (10 personas × 3 queries
= 30 entries) is published with each entry documenting must_include /
must_not_claim / human_review_required, and shows a real pass/fail/review
status (not just "shipped").

Spec source:
- ``tools/offline/_inbox/value_growth_dual/_m00_implementation/M00_C_proof_hardening/DC_01_jcrb_seed_synth_verified_guards.md``
- SYNTHESIS §8.6 (practitioner acceptance public版)

No LLM provider call. Pure file inspection.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
EVAL_DIR = REPO / "site" / "docs" / "practitioner-eval"
INDEX = EVAL_DIR / "index.html"

REQUIRED_PERSONAS: set[str] = {
    "bpo",
    "tax_practitioner",
    "accountant",
    "admin_scrivener",
    "ma_due_diligence",
    "finance",
    "ai_dev",
    "smb_owner",
    "municipality",
    "foreign_fdi",
}

ALLOWED_EVAL_STATUSES = {"pass", "fail", "review_required"}
ALLOWED_RESULT_KINDS = {"seed", "synth", "real"}


def _soup_or_skip(path: pathlib.Path):
    if not path.exists():
        pytest.skip(f"{path} missing — run scripts/etl/generate_practitioner_eval_pages.py")
    bs4 = pytest.importorskip("bs4", reason="needs site extras (bs4)")
    return bs4.BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def _entry_pages() -> list[pathlib.Path]:
    if not EVAL_DIR.exists():
        return []
    return [p for p in EVAL_DIR.rglob("*.html") if p.name != "index.html"]


def test_practitioner_eval_index_lists_30_entries() -> None:
    """The /docs/practitioner-eval/ index must link to >= 30 distinct entries."""
    soup = _soup_or_skip(INDEX)
    links = soup.find_all("a", class_="eval-entry")
    assert len(links) >= 30, (
        f"expected >= 30 eval-entry links on {INDEX.relative_to(REPO)}, "
        f"got {len(links)}. Spec target: 10 persona × 3 query = 30."
    )
    # Each link must have data-persona and data-query-id
    bad = [
        (a.get("href", "?"), [k for k in ("data-persona", "data-query-id") if not a.get(k)])
        for a in links
        if not a.get("data-persona") or not a.get("data-query-id")
    ]
    assert not bad, f"links missing data-persona / data-query-id: {bad[:5]}"


def test_each_entry_documents_must_include_must_not_claim_human_review() -> None:
    """Every entry HTML must carry the three documentation lists."""
    pages = _entry_pages()
    if not pages:
        pytest.skip("no entry pages yet — run generator")
    bs4 = pytest.importorskip("bs4")
    bad: list[tuple[str, list[str]]] = []
    for p in pages:
        soup = bs4.BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
        missing = []
        for klass in ("must-include", "must-not-claim", "human-review-required"):
            el = soup.find(class_=klass)
            if el is None or not el.get_text(strip=True):
                missing.append(klass)
        if missing:
            bad.append((str(p.relative_to(REPO)), missing))
    assert (
        not bad
    ), f'{len(bad)} entries missing required <dl class="..."> blocks (first 5): {bad[:5]}'


def test_each_entry_shows_pass_or_fail_not_just_shipped() -> None:
    """Every entry must declare an eval-status meta in {pass, fail, review_required}."""
    pages = _entry_pages()
    if not pages:
        pytest.skip("no entry pages yet")
    bs4 = pytest.importorskip("bs4")
    bad: list[tuple[str, str]] = []
    for p in pages:
        soup = bs4.BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
        meta = soup.find("meta", attrs={"name": "eval-status"})
        if meta is None:
            bad.append((str(p.relative_to(REPO)), "<missing>"))
            continue
        v = meta.get("content", "")
        if v not in ALLOWED_EVAL_STATUSES:
            bad.append((str(p.relative_to(REPO)), v))
    assert not bad, (
        f"{len(bad)} entries do not declare eval-status in "
        f"{sorted(ALLOWED_EVAL_STATUSES)} (first 5): {bad[:5]}. "
        f'"shipped" is explicitly disallowed — it must be a real outcome.'
    )


def test_persona_query_grid_covers_10_personas() -> None:
    """The 30 entries must cover all 10 required personas with >= 3 each."""
    soup = _soup_or_skip(INDEX)
    links = soup.find_all("a", class_="eval-entry")
    if len(links) < 30:
        pytest.skip("entry count below floor — covered by other test")
    persona_counts: dict[str, int] = {}
    for a in links:
        p = a.get("data-persona", "")
        persona_counts[p] = persona_counts.get(p, 0) + 1
    missing = REQUIRED_PERSONAS - persona_counts.keys()
    assert not missing, f"required personas not represented in eval grid: {sorted(missing)}"
    underfilled = {p: n for p, n in persona_counts.items() if p in REQUIRED_PERSONAS and n < 3}
    assert not underfilled, f"personas with < 3 queries (need 3 each): {underfilled}"


def test_each_entry_links_artifact_with_result_kind() -> None:
    """Every entry must link an artifact element carrying data-result-kind in
    {seed, synth, real}, so readers can tell whether the artifact is verified."""
    pages = _entry_pages()
    if not pages:
        pytest.skip("no entry pages yet")
    bs4 = pytest.importorskip("bs4")
    bad: list[tuple[str, str]] = []
    for p in pages:
        soup = bs4.BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
        artifacts = soup.find_all(class_="artifact")
        if not artifacts:
            bad.append((str(p.relative_to(REPO)), "no .artifact element"))
            continue
        kinds = {a.get("data-result-kind") for a in artifacts}
        if not kinds.intersection(ALLOWED_RESULT_KINDS):
            bad.append((str(p.relative_to(REPO)), f"kinds={kinds}"))
    assert not bad, (
        f"{len(bad)} entries missing artifact[data-result-kind in "
        f"{sorted(ALLOWED_RESULT_KINDS)}] (first 5): {bad[:5]}"
    )
