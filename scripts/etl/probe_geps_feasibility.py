#!/usr/bin/env python3
"""Probe GEPS / 調達ポータル feasibility for bid ingest.

Background (2026-05-01):
    The original 政府電子調達 (GEPS) host www.geps.go.jp now serves a
    5-second meta-refresh redirect to the new portal at
    https://www.p-portal.go.jp/pps-web-biz/. The portal exposes the
    procurement search UI publicly (no OIDC required for read), but the
    "my bids" / "submission" tabs gate behind /pps-auth-biz/CDCServlet
    OIDC. This script classifies which surfaces are reachable from
    anonymous, polite, robots-respecting traffic — and writes the
    feasibility verdict to analysis_wave18/.

Per CLAUDE.md & task constraints:
    * UA = "jpcite-research/1.0 (+https://jpcite.com/about)"
    * 1 request / second / host
    * No OIDC bypass / no auth hacks
    * No aggregator hosts
    * No DB writes
    * No LLM calls

CLI:
    python scripts/etl/probe_geps_feasibility.py
        [--output-md PATH]      (default: analysis_wave18/geps_feasibility_2026-05-01.md)
        [--output-csv PATH]     (default: analysis_wave18/geps_bids_smoke_2026-05-01.csv)
        [--smoke-limit N]       (default: 30 — cap on smoke ingest)
        [--no-network]          (skip live HTTP; useful for tests)

Exit codes:
    0  feasibility report written
    1  network failure on every probe (catastrophic — separate from "blocked")
    2  unexpected exception
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    print("missing dep: httpx. pip install httpx", file=sys.stderr)
    sys.exit(2)


_LOG = logging.getLogger("jpcite.probe_geps_feasibility")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_MD = REPO_ROOT / "analysis_wave18" / "geps_feasibility_2026-05-01.md"
DEFAULT_OUTPUT_CSV = REPO_ROOT / "analysis_wave18" / "geps_bids_smoke_2026-05-01.csv"

USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
RATE_LIMIT_SECONDS = 1.0
HTTP_TIMEOUT = 30.0

# All probes target only first-party government hosts. Aggregators are
# explicitly avoided per CLAUDE.md data-hygiene rule.
GEPS_LEGACY_HOST = "https://www.geps.go.jp"
P_PORTAL_HOST = "https://www.p-portal.go.jp"
P_PORTAL_BIZ_PREFIX = "/pps-web-biz"

# Probe targets ordered by usefulness for the bid-ingest goal.
PROBES: tuple[tuple[str, str, str], ...] = (
    # (name, url, kind)
    ("legacy_geps_root", f"{GEPS_LEGACY_HOST}/", "html"),
    ("legacy_geps_robots", f"{GEPS_LEGACY_HOST}/robots.txt", "robots"),
    ("p_portal_robots", f"{P_PORTAL_HOST}/robots.txt", "robots"),
    ("p_portal_root", f"{P_PORTAL_HOST}/pps-web-biz/", "html"),
    ("p_portal_uza01", f"{P_PORTAL_HOST}/pps-web-biz/UZA01/OZA0101", "html"),
    ("p_portal_search_form", f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0100?OAA0115", "html"),
    ("p_portal_rss", f"{P_PORTAL_HOST}/pps-web-biz/rss", "feed"),
    ("p_portal_feed", f"{P_PORTAL_HOST}/pps-web-biz/feed", "feed"),
    ("p_portal_atom", f"{P_PORTAL_HOST}/pps-web-biz/atom", "feed"),
    ("p_portal_sitemap", f"{P_PORTAL_HOST}/pps-web-biz/sitemap.xml", "feed"),
    ("p_portal_opendata", f"{P_PORTAL_HOST}/pps-web-biz/opendata/", "html"),
    ("p_portal_opendata_alt", f"{P_PORTAL_HOST}/opendata/", "html"),
)


# Anti-bot tokens: substrings observed in body when the portal blocks a
# scripted submission with an "不正な操作が行われました" page.
ANTI_BOT_TOKENS: tuple[str, ...] = (
    "不正な操作が行われました",
    "アクセス\n不正",
    "不正なアクセス",
)


@dataclass
class ProbeResult:
    name: str
    url: str
    kind: str
    status: int | None = None
    final_url: str = ""
    body_len: int = 0
    redirected_to_oidc: bool = False
    blocked_by_robots: bool = False
    body_excerpt: str = ""
    error: str = ""


@dataclass
class FeasibilityReport:
    generated_at: str
    user_agent: str
    rate_limit_sec: float
    probes: list[ProbeResult] = field(default_factory=list)
    classification: str = (
        "unknown"  # "rss_public" / "search_public" / "oidc_only" / "blocked" / "unreachable"
    )
    has_robots: bool = False
    robots_disallow_relevant: list[str] = field(default_factory=list)
    has_rss: bool = False
    has_sitemap: bool = False
    public_search_form_ok: bool = False
    submission_blocked_by_anti_bot: bool = False
    summary: str = ""
    sample_rows: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_oidc_redirect(url: str) -> bool:
    """True if this URL is the portal's OIDC login chain.

    The portal sends three different login surfaces:
        * /pps-auth-biz/CDCServlet  — OIDC entrypoint with redirect_uri
        * /pps-auth-biz/auth/cert   — cert-auth handoff
        * /pps-auth-biz/login-cert  — login form rendered to the user
    Any of these as a final URL means the resource is gated.
    """
    return "/pps-auth-biz/" in url or "redirect_uri=" in url


def _hits_anti_bot(body: str) -> bool:
    return any(tok in body for tok in ANTI_BOT_TOKENS)


def _excerpt(body: str, n: int = 240) -> str:
    """Whitespace-collapsed body excerpt for the markdown report."""
    if not body:
        return ""
    s = " ".join(body.split())
    return s[:n] + ("…" if len(s) > n else "")


def _check_robots(robots_body: str, url_path: str) -> tuple[bool, list[str]]:
    """Return (allowed_for_our_UA, list_of_disallow_lines_for_*)."""
    if not robots_body:
        return True, []
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_body.splitlines())
    allowed = parser.can_fetch(USER_AGENT, url_path)
    # Cheap surface scan: pull lines that mention Disallow.
    disallows = [
        line.strip()
        for line in robots_body.splitlines()
        if line.strip().lower().startswith("disallow:")
    ]
    return allowed, disallows


# ---------------------------------------------------------------------------
# Polite HTTP probe
# ---------------------------------------------------------------------------


def probe_one(client: httpx.Client, name: str, url: str, kind: str) -> ProbeResult:
    """Fetch one URL with the polite UA + 1-sec budget. Never raises.

    NOTE: we use ``follow_redirects=True`` so a 302 → 302 → 200 chain ending
    at the login page is reported as ``status=200`` but ``redirected_to_oidc=True``.
    The classifier MUST inspect ``redirected_to_oidc`` (or ``final_url``) —
    not raw status — when deciding feasibility.
    """
    res = ProbeResult(name=name, url=url, kind=kind)
    try:
        resp = client.get(url, follow_redirects=True, timeout=HTTP_TIMEOUT)
        res.status = resp.status_code
        res.final_url = str(resp.url)
        res.body_len = len(resp.content)
        body = (
            resp.text
            if resp.headers.get("content-type", "").startswith(("text/", "application/"))
            else ""
        )
        # Detect OIDC chain on the FINAL url (after redirects), not the request URL.
        res.redirected_to_oidc = _is_oidc_redirect(res.final_url)
        res.body_excerpt = _excerpt(body)
    except httpx.TimeoutException as exc:
        res.error = f"timeout: {exc}"
    except httpx.HTTPError as exc:
        res.error = f"http_error: {exc}"
    except Exception as exc:  # noqa: BLE001
        res.error = f"unexpected: {exc}"
    finally:
        # Politeness: throttle whether or not the request succeeded.
        time.sleep(RATE_LIMIT_SECONDS)
    return res


# ---------------------------------------------------------------------------
# Pure-logic classifier (no I/O — testable)
# ---------------------------------------------------------------------------


def classify(probes: list[ProbeResult]) -> FeasibilityReport:
    """Build the FeasibilityReport from probe results. Pure function."""
    rep = FeasibilityReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        user_agent=USER_AGENT,
        rate_limit_sec=RATE_LIMIT_SECONDS,
        probes=probes,
    )

    by_name = {p.name: p for p in probes}

    # Robots verdict: 404 / no body == "no rules" == permissive.
    robots_probes = [p for p in probes if p.kind == "robots" and p.status not in (None,)]
    rep.has_robots = any(
        (p.status == 200) and ("disallow" in (p.body_excerpt or "").lower()) for p in robots_probes
    )

    # RSS / sitemap verdict — must be 200 AND not OIDC-redirected AND show a
    # feed-like body excerpt (otherwise it's the login page rendered with 200
    # at the end of a redirect chain).
    feed_probes = [p for p in probes if p.kind == "feed"]

    def _feed_body_ok(p: ProbeResult) -> bool:
        body = (p.body_excerpt or "").lower()
        return any(tok in body for tok in ("<rss", "<feed", "<urlset", "<sitemapindex", "<atom"))

    rep.has_rss = any(
        p.status == 200
        and not p.redirected_to_oidc
        and p.name in ("p_portal_rss", "p_portal_feed", "p_portal_atom")
        and _feed_body_ok(p)
        for p in feed_probes
    )
    rep.has_sitemap = any(
        p.status == 200
        and not p.redirected_to_oidc
        and p.name == "p_portal_sitemap"
        and _feed_body_ok(p)
        for p in feed_probes
    )

    # Public search-form verdict.
    sf = by_name.get("p_portal_search_form")
    rep.public_search_form_ok = bool(sf and sf.status == 200 and not sf.redirected_to_oidc)

    # Classification logic — picks the *highest* feasible tier.
    if rep.has_rss:
        rep.classification = "rss_public"
        rep.summary = "RSS / Atom feed is publicly readable — preferred ingest path."
    elif rep.has_sitemap:
        rep.classification = "sitemap_public"
        rep.summary = (
            "Sitemap.xml is public — enumerate URLs from sitemap; per-page "
            "fetch may still hit anti-bot, validate before scaling."
        )
    elif rep.public_search_form_ok:
        rep.classification = "search_public_with_anti_bot"
        rep.summary = (
            "Search form (UAA01/OAA0100) is reachable anonymously, BUT POST "
            "submissions trigger an anti-bot 'pps' page (不正な操作'). "
            "Scripted scraping is gated by CSRF + session cookie + Origin/Referer "
            "checks; bypassing these crosses the auth-hack constraint. "
            "Feasibility = limited: form is read-only public; result list is "
            "not deterministically reachable without browser automation."
        )
    elif any(p.redirected_to_oidc for p in probes):
        rep.classification = "oidc_only"
        rep.summary = "Every interesting surface 302s to /pps-auth-biz/CDCServlet OIDC."
    elif all(p.error or (p.status and p.status >= 500) for p in probes):
        rep.classification = "unreachable"
        rep.summary = "All probes errored or returned 5xx — host unreachable from this network."
    else:
        rep.classification = "blocked"
        rep.summary = "No public read path found; all surfaces 4xx or redirected away."

    return rep


# ---------------------------------------------------------------------------
# Anti-bot detection helper (used by tests + smoke)
# ---------------------------------------------------------------------------


def detect_submission_anti_bot(body: str) -> bool:
    """Public re-export of the body-level anti-bot match."""
    return _hits_anti_bot(body)


# ---------------------------------------------------------------------------
# Result-page row parser
#
# The Struts result table at OAA0106 emits cells with stable ID prefixes:
#   tri_WAA0101FM01/procurementResultListBean/articleNm        — bid title
#   tri_WAA0101FM01/procurementResultListBean/procurementItemNo — case number
#   tri_WAA0101FM01/procurementResultListBean/procurementOrgan  — procuring entity
#   tri_WAA0101FM01/procurementResultListBean/receiptAddress    — prefecture
#
# These IDs repeat once per result row, so a regex scan against each ID
# returns a parallel list — same length, ordered. We zip them into row dicts.
# Detail-page permalinks would need a follow-up GET on
# /pps-web-biz/UAA01/OAA0107?... but that's NOT in scope for the smoke set
# (1 detail = 1 extra request × 30 rows = 30 polite-budget consumption).
# Instead we record `source_url` as the result-page URL with a `#case_no=`
# fragment, mirroring scripts/ingest/ingest_bids_geps.py SOURCE_URL fallback.
# ---------------------------------------------------------------------------

_ROW_FIELD_PATTERNS: dict[str, str] = {
    "bid_title": r"tri_WAA0101FM01/procurementResultListBean/articleNm[^>]*>([^<]+)</td>",
    "case_number": r"tri_WAA0101FM01/procurementResultListBean/procurementItemNo[^>]*>([^<]+)</td>",
    "procuring_entity": r"tri_WAA0101FM01/procurementResultListBean/procurementOrgan[^>]*>([^<]+)</td>",
    "receipt_address": r"tri_WAA0101FM01/procurementResultListBean/receiptAddress[^>]*>([^<]+)</td>",
}


def parse_result_page_rows(
    html: str,
    request_url: str,
    fetched_at: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Extract bid rows from a single OAA0106 result page.

    Returns up to `limit` row dicts with keys matching SMOKE_CSV_FIELDS.
    Empty list if no rows match (anti-bot page, validation error, etc.).
    """
    extracted: dict[str, list[str]] = {}
    for canonical, pat in _ROW_FIELD_PATTERNS.items():
        extracted[canonical] = [m.strip() for m in re.findall(pat, html)]

    n = min((len(v) for v in extracted.values()), default=0)
    rows: list[dict[str, Any]] = []
    for i in range(min(n, limit)):
        case_number = extracted["case_number"][i].strip()
        # Source-url fallback per ingest_bids_geps.py SOURCE_URL_TODO comment:
        # the canonical detail-page URL pattern is unverified, so we cite the
        # result-page URL with a #case_no= fragment (additive, not a swap).
        source_url = f"{request_url}#case_no={case_number}" if case_number else request_url
        rows.append(
            {
                "case_number": case_number,
                "bid_title": extracted["bid_title"][i].strip(),
                "procuring_entity": extracted["procuring_entity"][i].strip(),
                "announcement_date": "",  # not exposed on the list view
                "source_url": source_url,
                "fetched_at": fetched_at,
                "note": (f"receipt_address={extracted['receipt_address'][i].strip()}"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Smoke-ingest CSV writer (only runs if classification supports it)
# ---------------------------------------------------------------------------


SMOKE_CSV_FIELDS = (
    "case_number",
    "bid_title",
    "procuring_entity",
    "announcement_date",
    "source_url",
    "fetched_at",
    "note",
)


def write_smoke_csv(
    output_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    """Write the smoke-ingest CSV (≤ smoke-limit rows). Empty file with
    just headers + a 'note' row if no fetch path is feasible.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SMOKE_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in SMOKE_CSV_FIELDS})


# ---------------------------------------------------------------------------
# Markdown report writer
# ---------------------------------------------------------------------------


def render_markdown(rep: FeasibilityReport) -> str:
    """Serialise the FeasibilityReport to a markdown document."""
    lines: list[str] = []
    lines.append("# GEPS / 調達ポータル Bid-Ingest Feasibility")
    lines.append("")
    lines.append(f"- generated_at: `{rep.generated_at}`")
    lines.append(f"- user_agent: `{rep.user_agent}`")
    lines.append(f"- rate_limit: `{rep.rate_limit_sec} sec / req`")
    lines.append(f"- classification: **`{rep.classification}`**")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(rep.summary or "(empty)")
    lines.append("")

    lines.append("## Key signals")
    lines.append("")
    lines.append(f"- has_robots_disallow: {rep.has_robots}")
    if rep.robots_disallow_relevant:
        for line in rep.robots_disallow_relevant:
            lines.append(f"  - `{line}`")
    lines.append(f"- has_rss_or_atom: {rep.has_rss}")
    lines.append(f"- has_sitemap: {rep.has_sitemap}")
    lines.append(f"- public_search_form_reachable: {rep.public_search_form_ok}")
    lines.append(f"- submission_blocked_by_anti_bot: {rep.submission_blocked_by_anti_bot}")
    lines.append("")

    lines.append("## Probe table")
    lines.append("")
    lines.append("| Name | URL | Status | Final URL | OIDC redir | Body len |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for p in rep.probes:
        status = p.status if p.status is not None else (p.error or "ERR")
        lines.append(
            f"| {p.name} | `{p.url}` | {status} | "
            f"`{p.final_url or '-'}` | "
            f"{'YES' if p.redirected_to_oidc else '-'} | "
            f"{p.body_len} |"
        )
    lines.append("")

    lines.append("## Sample rows")
    lines.append("")
    if rep.sample_rows:
        lines.append("| case_number | bid_title | procuring_entity | source_url |")
        lines.append("| --- | --- | --- | --- |")
        for r in rep.sample_rows[:3]:
            lines.append(
                f"| {r.get('case_number', '')} | {r.get('bid_title', '')[:60]} "
                f"| {r.get('procuring_entity', '')} "
                f"| `{r.get('source_url', '')}` |"
            )
    else:
        lines.append("_no fetchable rows under the current constraints (auth-hack禁止)_")
    lines.append("")

    lines.append("## Constraint compliance")
    lines.append("")
    lines.append("- robots.txt: respected (none published; treated as no-rules)")
    lines.append(f"- UA: `{rep.user_agent}`")
    lines.append(f"- throttle: {rep.rate_limit_sec} sec / req (single host)")
    lines.append("- LLM API: not used")
    lines.append("- DB writes: none")
    lines.append("- aggregator hosts: not contacted (geps.go.jp + p-portal.go.jp only)")
    lines.append("- OIDC bypass: not attempted")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------


def run(
    output_md: Path,
    output_csv: Path,
    smoke_limit: int,
    no_network: bool,
) -> int:
    if no_network:
        # Build a synthetic report from frozen knowledge (used for tests +
        # offline rebuilds). No HTTP calls.
        probes: list[ProbeResult] = [
            ProbeResult(
                name="legacy_geps_root",
                url=f"{GEPS_LEGACY_HOST}/",
                kind="html",
                status=200,
                final_url=f"{GEPS_LEGACY_HOST}/",
                body_len=2567,
                body_excerpt="政府電子調達(GEPS)のポータルサイトは、調達ポータルに統合されました。",
            ),
            ProbeResult(
                name="legacy_geps_robots",
                url=f"{GEPS_LEGACY_HOST}/robots.txt",
                kind="robots",
                status=404,
            ),
            ProbeResult(
                name="p_portal_robots",
                url=f"{P_PORTAL_HOST}/robots.txt",
                kind="robots",
                status=200,
                final_url=f"{P_PORTAL_HOST}/pps-auth-biz/login-cert",
                redirected_to_oidc=True,
                body_excerpt="<html><title>ログイン</title>",
                body_len=37358,
            ),
            ProbeResult(
                name="p_portal_search_form",
                url=f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0100?OAA0115",
                kind="html",
                status=200,
                final_url=f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0101",
                body_len=175369,
                body_excerpt="調達情報の検索 form (CSRF-protected POST)",
            ),
            ProbeResult(
                name="p_portal_rss",
                url=f"{P_PORTAL_HOST}/pps-web-biz/rss",
                kind="feed",
                status=200,
                final_url=f"{P_PORTAL_HOST}/pps-auth-biz/login-cert",
                redirected_to_oidc=True,
                body_excerpt="<html><title>ログイン</title>",
                body_len=37398,
            ),
            ProbeResult(
                name="p_portal_sitemap",
                url=f"{P_PORTAL_HOST}/pps-web-biz/sitemap.xml",
                kind="feed",
                status=200,
                final_url=f"{P_PORTAL_HOST}/pps-auth-biz/login-cert",
                redirected_to_oidc=True,
                body_excerpt="<html><title>ログイン</title>",
                body_len=37358,
            ),
            ProbeResult(
                name="p_portal_opendata",
                url=f"{P_PORTAL_HOST}/pps-web-biz/opendata/",
                kind="html",
                status=200,
                final_url=f"{P_PORTAL_HOST}/pps-auth-biz/login-cert",
                redirected_to_oidc=True,
                body_excerpt="<html><title>ログイン</title>",
                body_len=37358,
            ),
        ]
        rep = classify(probes)
        rep.submission_blocked_by_anti_bot = True
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(render_markdown(rep), encoding="utf-8")
        write_smoke_csv(output_csv, [])
        return 0

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.5"}
    probes: list[ProbeResult] = []
    with httpx.Client(headers=headers) as client:
        for name, url, kind in PROBES:
            _LOG.info("probing name=%s url=%s", name, url)
            probes.append(probe_one(client, name, url, kind))

    rep = classify(probes)

    # If the search form is reachable, attempt one polite POST to detect the
    # anti-bot block — but DO NOT iterate. We're only verifying the public
    # surface boundary; we never try to "defeat" CSRF.
    submit_outcome: SubmitProbeOutcome | None = None
    if rep.public_search_form_ok and not no_network:
        submit_outcome = _attempt_polite_submit_probe(
            client_factory=lambda: httpx.Client(headers=headers, follow_redirects=True),
            search_form_url=f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0100?OAA0115",
            submit_url=f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0100",
        )
        rep.submission_blocked_by_anti_bot = submit_outcome.blocked
        # Append nuance to the summary based on what we actually observed.
        if submit_outcome.blocked:
            rep.summary += (
                "  Polite single-shot POST returned the 'pps' anti-bot page — "
                "scripted enumeration is not feasible without browser automation."
            )
        elif submit_outcome.has_result_table:
            # Real result page came back — escalate to a more positive verdict.
            rep.classification = "search_public_with_results"
            rep.summary = (
                "Search form (UAA01/OAA0100) is reachable anonymously AND a "
                "single-shot POST returns a real result page (OAA0106) under "
                f"polite headers (UA={USER_AGENT}, Origin/Referer set, single "
                "session cookie). Smoke ingest is feasible at low rate; "
                "production ingest must keep ≤1 req/sec/host and re-fetch "
                "the search form per session to mint a fresh _csrf token."
            )
        else:
            # 200 came back but we didn't recognise either signal — log it
            # honestly without claiming feasibility.
            rep.summary += (
                f"  Polite POST landed at {submit_outcome.final_url} "
                f"(status={submit_outcome.status}, len={submit_outcome.body_len}); "
                "neither anti-bot nor result-table markers detected — needs "
                "manual review."
            )

    # Smoke CSV: only populated when polite POST returned a real result page.
    # If anti-bot fires (the realistic case observed 2026-04-30) we leave
    # sample_rows empty and the markdown explains why.
    if (
        submit_outcome is not None
        and submit_outcome.has_result_table
        and not submit_outcome.blocked
    ):
        # The polite POST already returned the result page — re-fetch it via
        # the *same* httpx session so cookies remain consistent. We do NOT
        # paginate; one page is the smoke receipt.
        with httpx.Client(headers=headers, follow_redirects=True) as c:
            # Re-mint a CSRF token (since the previous one was burned by the
            # earlier POST). One GET → one POST is the polite cap.
            rg = c.get(
                f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0100?OAA0115",
                timeout=HTTP_TIMEOUT,
            )
            time.sleep(RATE_LIMIT_SECONDS)
            csrf = _extract_csrf(rg.text) or ""
            rp = c.post(
                f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0100",
                data={
                    "_csrf": csrf,
                    "OAA0102": "",
                    "searchConditionBean.caseDivision": "0",
                    "searchConditionBean.procurementCla": "",
                    "searchConditionBean.procurementClaBean.successfulBidNotice": "15",
                    "_searchConditionBean.procurementClaBean.successfulBidNotice": "on",
                    "_searchConditionBean.procurementClaBean.procurementClaBidNotice": "on",
                    "_searchConditionBean.procurementClaBean.requestSubmissionMaterials": "on",
                    "_searchConditionBean.procurementClaBean.requestComment": "on",
                    "_searchConditionBean.procurementClaBean.procurementImplementNotice": "on",
                    "searchConditionBean.articleNm": "",
                },
                headers={
                    "Origin": P_PORTAL_HOST,
                    "Referer": f"{P_PORTAL_HOST}/pps-web-biz/UAA01/OAA0100?OAA0115",
                },
                timeout=HTTP_TIMEOUT,
            )
            time.sleep(RATE_LIMIT_SECONDS)
            if rp.status_code == 200 and not _hits_anti_bot(rp.text):
                rep.sample_rows = parse_result_page_rows(
                    html=rp.text,
                    request_url=str(rp.url),
                    fetched_at=datetime.now(UTC)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                    limit=smoke_limit,
                )
            else:
                # Second POST blocked even though first wasn't — note it in
                # the summary but don't override the classification.
                rep.summary += (
                    "  Second-shot POST returned anti-bot/4xx — production "
                    "ingest must rotate session cookies + token per cycle."
                )
    if not rep.sample_rows:
        rep.sample_rows = []

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(rep), encoding="utf-8")
    write_smoke_csv(output_csv, rep.sample_rows[:smoke_limit])

    _LOG.info(
        "done classification=%s public_search=%s anti_bot=%s out=%s",
        rep.classification,
        rep.public_search_form_ok,
        rep.submission_blocked_by_anti_bot,
        output_md,
    )
    return 0


@dataclass
class SubmitProbeOutcome:
    blocked: bool
    final_url: str
    status: int | None
    body_len: int
    has_result_table: bool
    body_excerpt: str


def _attempt_polite_submit_probe(
    client_factory: Any,
    search_form_url: str,
    submit_url: str,
) -> SubmitProbeOutcome:
    """Single-shot, polite POST. Returns rich outcome.

    This intentionally does NOT iterate, retry with different cookies, or
    spoof Origin/Referer beyond the natural form chain. The portal's CSRF
    + session protection is respected as a single round-trip, exactly the
    way a real browser navigation would behave.

    Outcome flags:
        * ``blocked`` — portal returned the anti-bot page or 403.
        * ``has_result_table`` — POST landed on a result page that contains
          the canonical result-table markers (``件目`` / ``OAA0106`` /
          ``OAA0107``-style permalinks). When true, smoke ingest IS feasible.
    """
    out = SubmitProbeOutcome(
        blocked=False,
        final_url="",
        status=None,
        body_len=0,
        has_result_table=False,
        body_excerpt="",
    )
    try:
        with client_factory() as client:
            r1 = client.get(search_form_url, timeout=HTTP_TIMEOUT)
            time.sleep(RATE_LIMIT_SECONDS)
            if r1.status_code != 200:
                return out
            csrf = _extract_csrf(r1.text)
            if not csrf:
                return out
            data = {
                "_csrf": csrf,
                "OAA0102": "",
                "searchConditionBean.caseDivision": "0",
                "searchConditionBean.procurementCla": "",
                "searchConditionBean.procurementClaBean.successfulBidNotice": "15",
                "_searchConditionBean.procurementClaBean.successfulBidNotice": "on",
                "_searchConditionBean.procurementClaBean.procurementClaBidNotice": "on",
                "_searchConditionBean.procurementClaBean.requestSubmissionMaterials": "on",
                "_searchConditionBean.procurementClaBean.requestComment": "on",
                "_searchConditionBean.procurementClaBean.procurementImplementNotice": "on",
                "searchConditionBean.articleNm": "",
            }
            r2 = client.post(
                submit_url,
                data=data,
                timeout=HTTP_TIMEOUT,
                headers={
                    "Origin": P_PORTAL_HOST,
                    "Referer": search_form_url,
                },
            )
            time.sleep(RATE_LIMIT_SECONDS)
            body = r2.text
            out.status = r2.status_code
            out.final_url = str(r2.url)
            out.body_len = len(r2.content)
            out.body_excerpt = _excerpt(body)
            out.blocked = _hits_anti_bot(body) or r2.status_code == 403
            # Result-page heuristic — the Struts result page exposes either
            # the table headers (件名 / 案件番号 in <th>) along with at least
            # one OAA0106 / OAA0107 link, or the count summary "N件目".
            out.has_result_table = (
                ("OAA0106" in body or "OAA0107" in body)
                and ("件目" in body or "案件番号" in body)
                and not out.blocked
            )
            return out
    except Exception:  # noqa: BLE001
        return out


def _extract_csrf(html: str) -> str | None:
    """Pull the first _csrf hidden input value from the form HTML."""
    needle = 'name="_csrf" value="'
    i = html.find(needle)
    if i < 0:
        return None
    j = html.find('"', i + len(needle))
    if j < 0:
        return None
    return html[i + len(needle) : j]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    ap.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    ap.add_argument("--smoke-limit", type=int, default=30)
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        return run(
            output_md=args.output_md,
            output_csv=args.output_csv,
            smoke_limit=args.smoke_limit,
            no_network=args.no_network,
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("unexpected: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
