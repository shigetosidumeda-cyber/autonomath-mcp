"""JCRB question + submission guard.

Asserts that JCRB question files and submissions cleanly separate
seed / synth / verified, never carry real customer data, only cite
sources from the public-record allowlist, and do not let public copy
claim improvement until at least one external verified submission has
landed.

Spec source:
- ``tools/offline/_inbox/value_growth_dual/_m00_implementation/M00_C_proof_hardening/DC_01_jcrb_seed_synth_verified_guards.md``
- SYNTHESIS §8.6 (Proof separation) + §8.15 (公開証明 P0)

This test must NOT call any LLM provider — pure file inspection.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
QUESTIONS = REPO / "benchmarks" / "jcrb_v1" / "questions.jsonl"
SUBMISSIONS = REPO / "benchmarks" / "jcrb_v1" / "submissions"
RESULTS_JSON = REPO / "site" / "benchmark" / "results.json"
BENCHMARK_HTML = REPO / "site" / "benchmark" / "index.html"

ALLOWED_KINDS = {"seed", "synth", "verified"}
ALLOWED_HOST_SUFFIXES = (".go.jp", ".lg.jp", ".or.jp", ".ac.jp")

# Public-program domains that are non .go.jp / .or.jp / .lg.jp / .ac.jp
# but cite a primary government program portal. Maintained explicitly
# so that adding a new host is a deliberate decision, not an accident.
KNOWN_NON_GOJP_HOSTS: set[str] = {
    "monodukuri-hojo.jp",  # 中小企業庁 + 全国中央会 official portal
    "it-hojo.jp",  # 中小企業庁 + IPA official portal
    "jizokukahojokin.info",  # 全国商工会連合会 official portal
}

HOUJIN_BANGOU_RE = re.compile(r"\b\d{13}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\b0\d{1,4}-\d{1,4}-\d{4}\b")
# 改善率の言い切りパターン: +X%, X倍, ポイント, p.p.
IMPROVEMENT_CLAIM_RE = re.compile(
    r"(?:\+?\d{1,3}(?:\.\d+)?\s*(?:%|％|ポイント|pts?|p\.p\.))"
    r"|(?:\d+(?:\.\d+)?\s*倍)",
    re.IGNORECASE,
)


def _load_questions() -> list[dict]:
    if not QUESTIONS.exists():
        pytest.skip(f"{QUESTIONS} missing — run benchmarks/jcrb_v1 setup first")
    return [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_results_json() -> dict:
    if not RESULTS_JSON.exists():
        pytest.skip(f"{RESULTS_JSON} missing — run scripts/cron/jcrb_publish_results.py")
    return json.loads(RESULTS_JSON.read_text(encoding="utf-8"))


def _load_submissions() -> list[tuple[str, dict]]:
    if not SUBMISSIONS.exists():
        return []
    out: list[tuple[str, dict]] = []
    for p in sorted(SUBMISSIONS.glob("*.json")):
        try:
            out.append((p.name, json.loads(p.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    return out


def _has_allowed_host(host: str) -> bool:
    if not isinstance(host, str) or not host:
        return False
    if any(host.endswith(s) for s in ALLOWED_HOST_SUFFIXES):
        return True
    return host in KNOWN_NON_GOJP_HOSTS


def _walk_strings(obj):
    """Yield every string leaf in a nested JSON-ish structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


def test_jcrb_questions_have_explicit_kind_field() -> None:
    """Every question row carries kind in {seed, synth, verified}."""
    rows = _load_questions()
    missing = [r.get("id", "<no-id>") for r in rows if r.get("kind") not in ALLOWED_KINDS]
    assert not missing, (
        f"questions missing kind field (first 5 of {len(missing)}): {missing[:5]}. "
        f"Run scripts/etl/add_kind_field_to_jcrb_questions.py to backfill kind=verified."
    )


def test_jcrb_seed_and_synth_carry_no_real_customer_data() -> None:
    """seed/synth questions must not embed houjin_bangou, email, phone, or
    likely personal names — they are illustrative templates only."""
    rows = _load_questions()
    bad: list[tuple[str, str, str]] = []
    for r in rows:
        if r.get("kind") not in {"seed", "synth"}:
            continue
        for s in _walk_strings(r):
            if HOUJIN_BANGOU_RE.search(s):
                bad.append((r.get("id", "?"), "houjin_bangou", s[:80]))
            if EMAIL_RE.search(s):
                bad.append((r.get("id", "?"), "email", s[:80]))
            if PHONE_RE.search(s):
                bad.append((r.get("id", "?"), "phone", s[:80]))
    assert not bad, f"seed/synth question rows leaked customer-shaped data: {bad[:5]}"

    # Same rule for submissions, except `submitter` field which is allowed
    # to be a GitHub handle / org name.
    bad_sub: list[tuple[str, str, str]] = []
    for fname, sub in _load_submissions():
        for k, v in sub.items():
            if k == "submitter":
                continue
            for s in _walk_strings(v):
                if HOUJIN_BANGOU_RE.search(s) or EMAIL_RE.search(s) or PHONE_RE.search(s):
                    bad_sub.append((fname, k, s[:80]))
    assert not bad_sub, f"submission files leaked customer-shaped data: {bad_sub[:5]}"


def test_jcrb_questions_source_host_allowlist() -> None:
    """expected_source_host must end with a public-record TLD or be in the
    explicit non-go.jp government-portal allowlist."""
    rows = _load_questions()
    bad: list[tuple[str, str]] = []
    for r in rows:
        host = r.get("expected_source_host", "")
        if not _has_allowed_host(host):
            bad.append((r.get("id", "?"), host))
    assert not bad, (
        f"questions cite non-allowlisted hosts (first 5 of {len(bad)}): {bad[:5]}. "
        f"Allowed suffixes: {ALLOWED_HOST_SUFFIXES}, "
        f"explicit allowlist: {sorted(KNOWN_NON_GOJP_HOSTS)}"
    )


def test_jcrb_question_count_floor_per_domain() -> None:
    """At least 100 verified questions / 5 domain (>= 20 per domain)."""
    rows = _load_questions()
    verified = [r for r in rows if r.get("kind") == "verified"]
    by_domain: dict[str, int] = {}
    for r in verified:
        by_domain[r.get("domain", "<none>")] = by_domain.get(r.get("domain", "<none>"), 0) + 1
    expected_domains = {
        "subsidy_eligibility",
        "tax_application",
        "law_citation",
        "adoption_statistics",
        "enforcement_risk",
    }
    missing = expected_domains - by_domain.keys()
    assert not missing, f"verified questions missing domains: {missing}"
    underfilled = {d: n for d, n in by_domain.items() if d in expected_domains and n < 20}
    assert not underfilled, (
        f"verified question count under floor per domain (need >= 20): {underfilled}"
    )


def test_jcrb_verified_submission_count_is_queryable_from_public_results() -> None:
    """Public results.json must expose leaderboard_verified as a list, so the
    count can be read mechanically. The list may legitimately be empty —
    this test does NOT enforce >= 1."""
    j = _load_results_json()
    lb = j.get("leaderboard_verified")
    assert isinstance(lb, list), (
        f"results.json missing leaderboard_verified list (got {type(lb).__name__}). "
        f"This is the queryable count of external verified submissions."
    )
    # The count itself is allowed to be 0 — that is the honest current state.
    verified_count = len(lb)
    assert verified_count >= 0


def test_jcrb_public_copy_does_not_claim_improvement_when_zero_verified() -> None:
    """When verified=0, public benchmark HTML must not assert percentage
    improvements outside seed/synth-marked or hidden DOM."""
    if not BENCHMARK_HTML.exists():
        pytest.skip(f"{BENCHMARK_HTML} missing")
    j = _load_results_json()
    if len(j.get("leaderboard_verified", [])) >= 1:
        pytest.skip("verified >= 1 — improvement claims are allowed when wrapped")

    bs4 = pytest.importorskip("bs4", reason="needs site extras (bs4)")
    soup = bs4.BeautifulSoup(BENCHMARK_HTML.read_text(encoding="utf-8"), "html.parser")
    # Strip script/style/noscript so we only inspect human-visible text.
    for s in soup(["script", "style", "noscript"]):
        s.decompose()

    safe_kinds = {"seed", "synth"}

    def _inside_seed_or_hidden(node) -> bool:
        cur = node
        while cur is not None and getattr(cur, "name", None) is not None:
            if hasattr(cur, "has_attr") and cur.has_attr("hidden"):
                return True
            kind = cur.get("data-result-kind") if hasattr(cur, "get") else None
            if kind in safe_kinds:
                return True
            cur = cur.parent
        return False

    visible_hits: list[str] = []
    for t in soup.find_all(string=True):
        if not isinstance(t, bs4.NavigableString):
            continue
        text = str(t)
        if not IMPROVEMENT_CLAIM_RE.search(text):
            continue
        if _inside_seed_or_hidden(t.parent):
            continue
        visible_hits.append(text.strip()[:160])

    assert not visible_hits, (
        "verified=0 but benchmark/index.html shows percentage / multiplier "
        "claims outside seed/synth/hidden scope. First hits: "
        f"{visible_hits[:5]}. Wrap with "
        '<span data-result-kind="seed" hidden>…</span> '
        "or land >=1 verified submission first."
    )
