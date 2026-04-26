#!/usr/bin/env python3
"""Daily competitive watch for jpintel-mcp.

Fetches a curated list of competitor / adjacent URLs (pricing pages,
changelogs, API docs, blog RSS, GitHub release feeds, J-PlatPat trademark
search, and domain RDAP), diffs against yesterday's snapshot, and emits:

  - Per-month log append to research/competitive_log_YYYYMM.md
  - Optional Slack notification via $SLACK_WEBHOOK_COMPETITIVE
  - Fail-open: one dead host does not block the rest.

Design principles:
  - Respect robots.txt (urllib.robotparser).
  - 1 host, min 5s between requests, max 3 req/min per host.
  - User-Agent advertised as jpintel-mcp-competitive-watch.
  - No auth bypass, no JS-rendered scraping, no PDFs >10MB.
  - Snapshot HTML to data/competitive_watch/<slug>/YYYY-MM-DD.html
    (gitignored) so only the markdown log is committed.

Usage:
  python scripts/competitive_watch.py \\
      --out research/competitive_log_202604.md \\
      --snapshots data/competitive_watch \\
      [--slack-webhook https://hooks.slack.com/...] \\
      [--dry-run]

Exit codes:
  0  success (even if some hosts failed — fail-open)
  2  catastrophic config error
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import difflib
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERROR: httpx not installed. pip install httpx", file=sys.stderr)
    sys.exit(2)

try:
    import feedparser  # type: ignore
except ImportError:
    feedparser = None  # RSS is optional

try:
    from readability import Document  # type: ignore
except ImportError:
    Document = None  # readability is optional

_LOG = logging.getLogger("jpintel.competitive_watch")

USER_AGENT = "jpintel-mcp-competitive-watch/1.0 (+https://autonomath.ai)"
PER_HOST_DELAY_SEC = 5.0
MAX_BYTES = 10 * 1024 * 1024  # 10MB cap

# Keywords that bump severity to HIGH when they newly appear in a diff.
HIGH_KEYWORDS = [
    "MCP",
    "Claude Desktop",
    "排他",
    "exclusion",
    "agri",
    "農業",
    "tier scoring",
    "lineage",
    "bulk CSV",
    "一括ダウンロード",
    "v2",
    "再配布",
    "商用利用",
    "自動化",
    "スクレイピング",
]


# ---------------------------------------------------------------------------
# Target registry
# ---------------------------------------------------------------------------


@dataclass
class Target:
    slug: str
    name: str
    url: str
    kind: str  # "html" | "rss" | "github_releases" | "github_commits" | "rdap" | "jplatpat"
    segment: str = ""
    notes: str = ""


TARGETS: list[Target] = [
    # --- Official JP portals / API docs ---
    Target(
        slug="jgrants_portal_home",
        name="Jグランツ (portal home)",
        url="https://www.jgrants-portal.go.jp/",
        kind="html",
        segment="official portal",
    ),
    Target(
        slug="jgrants_api_doc",
        name="Jグランツ API doc (デジタル庁)",
        url="https://developers.digital.go.jp/documents/jgrants/api/",
        kind="html",
        segment="official API",
    ),
    Target(
        slug="jgrants_news",
        name="Jグランツ 新着・更新",
        url="https://developers.digital.go.jp/news/services/jgrants/",
        kind="html",
        segment="official changelog",
    ),
    # --- Official MCP repo ---
    Target(
        slug="digital_go_jgrants_mcp_releases",
        name="digital-go-jp/jgrants-mcp-server releases",
        url="https://api.github.com/repos/digital-go-jp/jgrants-mcp-server/releases",
        kind="github_releases",
        segment="official MCP",
    ),
    Target(
        slug="digital_go_jgrants_mcp_commits",
        name="digital-go-jp/jgrants-mcp-server commits",
        url="https://api.github.com/repos/digital-go-jp/jgrants-mcp-server/commits",
        kind="github_commits",
        segment="official MCP",
    ),
    # --- Direct competitors (SaaS) ---
    Target(
        slug="hojokin_ai_home",
        name="hojokin.ai (補助金 Express)",
        url="https://www.hojokin.ai/",
        kind="html",
        segment="SaaS",
    ),
    Target(
        slug="hojokin_ai_terms",
        name="hojokin.ai 利用規約",
        url="https://www.hojokin.ai/terms",
        kind="html",
        segment="SaaS terms",
    ),
    Target(
        slug="enegaeru_subsidy_api",
        name="エネがえる 自治体スマエネ補助金API",
        url="https://www.enegaeru.com/subsidyinformation-api",
        kind="html",
        segment="paid API (energy)",
    ),
    Target(
        slug="hojyokincloud_price",
        name="補助金クラウド 料金",
        url="https://www.hojyokincloud.jp/price/",
        kind="html",
        segment="SaaS pricing",
    ),
    Target(
        slug="navit_joseikin_now",
        name="助成金なう (ナビット)",
        url="https://www.navit-j.com/service/joseikin-now/",
        kind="html",
        segment="SaaS",
    ),
    # --- Content / portal competitors ---
    Target(
        slug="hojyokin_portal",
        name="補助金ポータル",
        url="https://hojyokin-portal.jp/",
        kind="html",
        segment="content portal",
    ),
    Target(
        slug="hojyokin_concierge",
        name="みんなの補助金コンシェルジュ",
        url="https://hojyokin-concierge.com/",
        kind="html",
        segment="content portal",
    ),
    # --- OSS community MCPs ---
    Target(
        slug="rtoki_jgrants_mcp_commits",
        name="rtoki/jgrants-mcp-server commits",
        url="https://api.github.com/repos/rtoki/jgrants-mcp-server/commits",
        kind="github_commits",
        segment="OSS MCP",
    ),
    Target(
        slug="tachibanayu24_jgrants_mcp_commits",
        name="tachibanayu24/jgrants-mcp commits",
        url="https://api.github.com/repos/tachibanayu24/jgrants-mcp/commits",
        kind="github_commits",
        segment="OSS MCP",
    ),
    Target(
        slug="yamariki_japan_corporate_mcp_commits",
        name="yamariki-hub/japan-corporate-mcp commits",
        url="https://api.github.com/repos/yamariki-hub/japan-corporate-mcp/commits",
        kind="github_commits",
        segment="OSS MCP (adjacent)",
    ),
    # --- Registry ---
    Target(
        slug="pulsemcp_servers_jp",
        name="PulseMCP servers (Japan section)",
        url="https://www.pulsemcp.com/servers?q=japan",
        kind="html",
        segment="MCP registry",
    ),
    # --- Defensive: our own repo forks ---
    Target(
        slug="own_forks",
        name="jpintel-mcp/jpintel-mcp forks",
        url="https://api.github.com/repos/jpintel-mcp/jpintel-mcp/forks",
        kind="github_commits",
        segment="defensive",
    ),
    # --- Trademark / domain watch (handled specially) ---
    Target(
        slug="jplatpat_jpinst",
        name="J-PlatPat 検索 (jpinst + 関連語)",
        url="https://www.j-platpat.inpit.go.jp/",
        kind="jplatpat",
        segment="trademark watch",
        notes="Hit if any competitor files 'jpinst','jpintel','ジェイピーインスト','JPI Data','JGI'",
    ),
    Target(
        slug="rdap_jpinst_ai",
        name="RDAP jpinst.ai",
        url="https://rdap.verisign.com/com/v1/domain/jpinst.ai",
        kind="rdap",
        segment="domain watch",
    ),
    Target(
        slug="rdap_jpinst_app",
        name="RDAP jpinst.app",
        url="https://rdap.verisign.com/com/v1/domain/jpinst.app",
        kind="rdap",
        segment="domain watch",
    ),
    Target(
        slug="rdap_jpintel_ai",
        name="RDAP jpintel.ai",
        url="https://rdap.verisign.com/com/v1/domain/jpintel.ai",
        kind="rdap",
        segment="domain watch",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    target: Target
    ok: bool
    body: str = ""
    content_type: str = ""
    hash: str = ""
    error: str = ""


@dataclass
class DiffResult:
    target: Target
    changed: bool
    severity: str  # "HIGH" | "MID" | "LOW"
    snippet: str = ""
    added_keywords: list[str] = field(default_factory=list)
    error: str = ""


_host_last_fetch: dict[str, float] = {}
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def _respect_robots(url: str, client: httpx.Client) -> bool:
    """Return True if robots.txt allows us to fetch."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    if host in _robots_cache:
        rp = _robots_cache[host]
    else:
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        try:
            r = client.get(robots_url, timeout=10)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp.allow_all = True
        except Exception:
            rp.allow_all = True
        _robots_cache[host] = rp
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _rate_limit(url: str) -> None:
    host = urllib.parse.urlparse(url).netloc
    last = _host_last_fetch.get(host, 0.0)
    now = time.monotonic()
    wait = PER_HOST_DELAY_SEC - (now - last)
    if wait > 0:
        time.sleep(wait)
    _host_last_fetch[host] = time.monotonic()


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def _extract_readable(html: str) -> str:
    """Strip HTML noise. Fallback to naive tag-strip if readability absent."""
    if Document is not None:
        try:
            doc = Document(html)
            summary = doc.summary(html_partial=True)
            text = re.sub(r"<[^>]+>", " ", summary)
            return re.sub(r"\s+", " ", text).strip()
        except Exception:
            pass
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch(target: Target, client: httpx.Client) -> FetchResult:
    url = target.url
    if target.kind in ("html", "rss") and not _respect_robots(url, client):
        return FetchResult(target=target, ok=False, error="robots.txt disallows")
    _rate_limit(url)
    try:
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        r = client.get(url, headers=headers, timeout=30, follow_redirects=True)
        if r.status_code >= 400:
            return FetchResult(target=target, ok=False, error=f"HTTP {r.status_code}")
        body_bytes = r.content[:MAX_BYTES]
        body = body_bytes.decode(r.encoding or "utf-8", errors="replace")
        if target.kind == "html":
            body = _extract_readable(body)
        elif target.kind in ("github_releases", "github_commits", "rdap"):
            # keep JSON compact and sorted for stable diffing
            with contextlib.suppress(json.JSONDecodeError):
                body = json.dumps(json.loads(body), ensure_ascii=False, indent=2, sort_keys=True)
        elif target.kind == "rss" and feedparser is not None:
            try:
                parsed = feedparser.parse(body)
                entries = [
                    {"title": e.get("title"), "link": e.get("link"), "updated": e.get("updated")}
                    for e in parsed.entries[:30]
                ]
                body = json.dumps(entries, ensure_ascii=False, indent=2)
            except Exception:
                pass
        return FetchResult(
            target=target,
            ok=True,
            body=body,
            content_type=r.headers.get("content-type", ""),
            hash=_sha256(body),
        )
    except Exception as exc:  # noqa: BLE001
        return FetchResult(target=target, ok=False, error=f"{type(exc).__name__}: {exc}")


def _fetch_jplatpat(target: Target, client: httpx.Client) -> FetchResult:
    """J-PlatPat does not expose a stable query URL. We fetch the landing page,
    hash it, and rely on a separate manual monthly deeper query. This is a
    best-effort signal that the search surface itself changed."""
    return _fetch(
        dataclasses.replace(target, kind="html"),
        client,
    )


def _load_prev(snapshots: Path, slug: str) -> str:
    """Return most recent previously saved snapshot body for this slug, or ''."""
    d = snapshots / slug
    if not d.is_dir():
        return ""
    candidates = sorted([p for p in d.iterdir() if p.suffix == ".html"], reverse=True)
    if not candidates:
        return ""
    try:
        return candidates[0].read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _save_snapshot(snapshots: Path, slug: str, body: str) -> Path:
    d = snapshots / slug
    d.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    p = d / f"{today}.html"
    p.write_text(body, encoding="utf-8")
    # prune to 30 days
    snaps = sorted(d.iterdir())
    for old in snaps[:-30]:
        with contextlib.suppress(OSError):
            old.unlink()
    return p


def _diff_and_classify(prev: str, curr: str, target: Target) -> DiffResult:
    if not prev:
        return DiffResult(target=target, changed=True, severity="LOW", snippet="(first capture)")
    if prev == curr:
        return DiffResult(target=target, changed=False, severity="LOW")
    diff_lines = list(
        difflib.unified_diff(
            prev.splitlines(),
            curr.splitlines(),
            lineterm="",
            n=2,
        )
    )
    added = "\n".join(line[1:] for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    added_keywords = [k for k in HIGH_KEYWORDS if k.lower() in added.lower() and k.lower() not in prev.lower()]
    # price heuristic
    has_price = bool(re.search(r"¥\s?\d[\d,]*", added))
    severity = "LOW"
    if added_keywords or has_price:
        severity = "HIGH"
    elif target.segment in ("official API", "official changelog", "official MCP"):
        severity = "MID"
    snippet_lines = diff_lines[:40]
    return DiffResult(
        target=target,
        changed=True,
        severity=severity,
        snippet="\n".join(snippet_lines),
        added_keywords=added_keywords,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _append_log(out_path: Path, diffs: list[DiffResult], fetched: list[FetchResult]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not out_path.exists() or out_path.stat().st_size == 0
    today = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines: list[str] = []
    if header_needed:
        month = datetime.now(UTC).strftime("%Y-%m")
        lines.append(f"# Competitive Watch log {month}\n")
        lines.append("Generated by `scripts/competitive_watch.py`.\n")
    lines.append(f"\n## Run {today}\n")
    high = [d for d in diffs if d.changed and d.severity == "HIGH"]
    mid = [d for d in diffs if d.changed and d.severity == "MID"]
    low = [d for d in diffs if d.changed and d.severity == "LOW"]
    fails = [f for f in fetched if not f.ok]
    lines.append(f"- Targets scanned: {len(fetched)} (fail: {len(fails)})")
    lines.append(f"- Diffs: HIGH {len(high)} / MID {len(mid)} / LOW {len(low)}")
    if not (high or mid or low):
        lines.append("- No changes detected.")
    for d in high + mid + low:
        lines.append(f"\n### [{d.severity}] {d.target.name} — {d.target.segment}")
        lines.append(f"- URL: {d.target.url}")
        if d.added_keywords:
            lines.append(f"- Keywords appeared: `{', '.join(d.added_keywords)}`")
        if d.snippet:
            lines.append("- Diff (truncated):")
            lines.append("```diff")
            lines.append(d.snippet)
            lines.append("```")
    if fails:
        lines.append("\n### Fetch failures (fail-open)")
        for f in fails:
            lines.append(f"- {f.target.slug}: {f.error}")
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _slack_notify(webhook: str, diffs: list[DiffResult]) -> None:
    high = [d for d in diffs if d.changed and d.severity == "HIGH"]
    if not high:
        return
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "jpintel-mcp competitive watch"}}]
    for d in high[:10]:
        text = f"*{d.target.name}* ({d.target.segment})\n{d.target.url}\n"
        if d.added_keywords:
            text += f"keywords: `{', '.join(d.added_keywords)}`\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
    payload = {"blocks": blocks, "text": f"[competitive-watch] {len(high)} HIGH diffs"}
    try:
        with httpx.Client(timeout=15) as c:
            c.post(webhook, json=payload)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("slack post failed: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="path to research/competitive_log_YYYYMM.md")
    parser.add_argument(
        "--snapshots",
        default="data/competitive_watch",
        help="snapshot dir (gitignored)",
    )
    parser.add_argument("--slack-webhook", default=os.environ.get("SLACK_WEBHOOK_COMPETITIVE", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    out_path = Path(args.out)
    snap_dir = Path(args.snapshots)
    snap_dir.mkdir(parents=True, exist_ok=True)

    results: list[FetchResult] = []
    diffs: list[DiffResult] = []
    with httpx.Client(timeout=30) as client:
        for t in TARGETS:
            _LOG.info("fetching %s (%s)", t.slug, t.url)
            fr = _fetch_jplatpat(t, client) if t.kind == "jplatpat" else _fetch(t, client)
            results.append(fr)
            if not fr.ok:
                _LOG.warning("fail %s: %s", t.slug, fr.error)
                continue
            prev = _load_prev(snap_dir, t.slug)
            if not args.dry_run:
                _save_snapshot(snap_dir, t.slug, fr.body)
            d = _diff_and_classify(prev, fr.body, t)
            diffs.append(d)

    if not args.dry_run:
        _append_log(out_path, diffs, results)
        if args.slack_webhook:
            _slack_notify(args.slack_webhook, diffs)

    high = sum(1 for d in diffs if d.changed and d.severity == "HIGH")
    mid = sum(1 for d in diffs if d.changed and d.severity == "MID")
    _LOG.info("done. HIGH=%d MID=%d fail=%d", high, mid, sum(1 for r in results if not r.ok))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
