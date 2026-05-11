#!/usr/bin/env python3
"""Track post-publication reactions across organic-outreach surfaces.

Daily cron. Pulls public reaction counts (views / likes / comments) from
each platform's public read-only endpoint and appends a JSONL snapshot to
``analytics/publication_reactions_w41.jsonl`` so we can trend Day-1..Day-30
engagement curves per channel without paying for any analytics platform.

Pure ``urllib.request`` — no LLM SDK imports — so this script is safe to
live under ``scripts/cron/`` per the ``test_no_llm_in_production`` rule.

Platforms covered (all read-only, no auth required for public posts):

- Zenn:       ``https://zenn.dev/api/articles/<slug>``  → likedCount / commentsCount / readingTime
- note.com:   ``https://note.com/api/v2/notes/<slug>``   → likeCount / replyCount (best-effort)
- Qiita:      ``https://qiita.com/api/v2/items/<item_id>``  → likes_count / stocks_count / comments_count
- dev.to:     ``https://dev.to/api/articles/<id>``       → positive_reactions_count / comments_count
- Hashnode:   GraphQL ``post(slug, publicationHost)``     → reactionCount / responseCount
- HN:         ``https://hacker-news.firebaseio.com/v0/item/<id>.json``  → score / descendants
- Product Hunt: ``https://api.producthunt.com/v2/api/graphql`` (PAT optional)

Targets are declared in ``analytics/publication_reactions_targets.json``
so the operator can edit URLs/slugs without touching this file.

Usage::

    python3 scripts/cron/track_publication_reactions.py            # snapshot all targets
    python3 scripts/cron/track_publication_reactions.py --dry-run  # print only
    python3 scripts/cron/track_publication_reactions.py --platforms zenn,hn  # subset
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ANALYTICS_DIR = REPO_ROOT / "analytics"
TARGETS_FILE = ANALYTICS_DIR / "publication_reactions_targets.json"
SNAPSHOT_FILE = ANALYTICS_DIR / "publication_reactions_w41.jsonl"

USER_AGENT = "jpcite-reaction-tracker/1.0 (+https://jpcite.com)"


def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> tuple[int, object | str]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - read-only public endpoint
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text[:600]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body[:600]
    except Exception as exc:  # pragma: no cover - network surface
        return 0, repr(exc)


def probe_zenn(slug: str) -> dict[str, object]:
    url = f"https://zenn.dev/api/articles/{slug}"
    code, body = _http_get_json(url)
    out: dict[str, object] = {"platform": "zenn", "slug": slug, "http_status": code}
    if code == 200 and isinstance(body, dict):
        art = body.get("article", body)
        out["liked_count"] = art.get("likedCount") or art.get("liked_count")
        out["comments_count"] = art.get("commentsCount") or art.get("comments_count")
        out["reading_time"] = art.get("readingTime")
    else:
        out["error"] = body if isinstance(body, str) else json.dumps(body)[:200]
    return out


def probe_note(slug: str) -> dict[str, object]:
    url = f"https://note.com/api/v2/notes/{slug}"
    code, body = _http_get_json(url)
    out: dict[str, object] = {"platform": "note", "slug": slug, "http_status": code}
    if code == 200 and isinstance(body, dict):
        data = body.get("data", body)
        out["like_count"] = data.get("likeCount") or data.get("like_count")
        out["reply_count"] = data.get("commentCount") or data.get("reply_count")
    else:
        out["error"] = body if isinstance(body, str) else json.dumps(body)[:200]
    return out


def probe_qiita(item_id: str) -> dict[str, object]:
    url = f"https://qiita.com/api/v2/items/{item_id}"
    code, body = _http_get_json(url)
    out: dict[str, object] = {"platform": "qiita", "item_id": item_id, "http_status": code}
    if code == 200 and isinstance(body, dict):
        out["likes_count"] = body.get("likes_count")
        out["stocks_count"] = body.get("stocks_count")
        out["comments_count"] = body.get("comments_count")
        out["page_views_count"] = body.get("page_views_count")  # may be None
    else:
        out["error"] = body if isinstance(body, str) else json.dumps(body)[:200]
    return out


def probe_devto(article_id: str) -> dict[str, object]:
    url = f"https://dev.to/api/articles/{article_id}"
    code, body = _http_get_json(url)
    out: dict[str, object] = {"platform": "devto", "article_id": article_id, "http_status": code}
    if code == 200 and isinstance(body, dict):
        out["positive_reactions_count"] = body.get("positive_reactions_count")
        out["public_reactions_count"] = body.get("public_reactions_count")
        out["comments_count"] = body.get("comments_count")
        out["page_views_count"] = body.get("page_views_count")
    else:
        out["error"] = body if isinstance(body, str) else json.dumps(body)[:200]
    return out


def probe_hashnode(slug: str, host: str) -> dict[str, object]:
    query = """
query Post($slug: String!, $host: String!) {
  publication(host: $host) {
    post(slug: $slug) { id title reactionCount responseCount views }
  }
}
""".strip()
    payload = json.dumps({"query": query, "variables": {"slug": slug, "host": host}}).encode("utf-8")
    req = urllib.request.Request("https://gql.hashnode.com/", data=payload, method="POST")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Content-Type", "application/json")
    out: dict[str, object] = {"platform": "hashnode", "slug": slug, "host": host}
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - read-only GraphQL
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            post = (((data.get("data") or {}).get("publication") or {}).get("post") or {})
            out["http_status"] = resp.status
            out["reaction_count"] = post.get("reactionCount")
            out["response_count"] = post.get("responseCount")
            out["views"] = post.get("views")
    except Exception as exc:  # pragma: no cover
        out["http_status"] = 0
        out["error"] = repr(exc)
    return out


def probe_hn(item_id: str) -> dict[str, object]:
    url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
    code, body = _http_get_json(url)
    out: dict[str, object] = {"platform": "hn", "item_id": item_id, "http_status": code}
    if code == 200 and isinstance(body, dict):
        out["score"] = body.get("score")
        out["descendants"] = body.get("descendants")
        out["title"] = body.get("title")
        out["dead"] = body.get("dead", False)
    else:
        out["error"] = body if isinstance(body, str) else json.dumps(body)[:200]
    return out


def probe_producthunt(post_slug: str) -> dict[str, object]:
    """Product Hunt has no token-free public API; we return slug-only metadata.

    To enable live tracking, set ``PRODUCT_HUNT_PAT`` and switch this to the
    GraphQL ``post(slug: $slug)`` query — kept off the default path because
    PAT setup is operator-side and we want this cron to stay zero-auth.
    """
    return {
        "platform": "producthunt",
        "slug": post_slug,
        "http_status": 0,
        "note": "Product Hunt requires PAT for read API; track manually on producthunt.com/posts/<slug>.",
    }


# Default placeholder targets. ``analytics/`` is git-ignored so the operator
# updates the on-disk file with the real slugs/ids; if the file is missing
# (fresh checkout, CI runner) the cron falls back to these placeholders so
# the run still completes (rows will be 404/0 — expected on first day).
DEFAULT_TARGETS: list[dict[str, str]] = [
    {"platform": "zenn", "slug": "shigetosidumeda-cyber/jpcite-mcp-launch", "note": "update once published"},
    {"platform": "note", "slug": "n0000000000a0", "note": "replace once posted"},
    {"platform": "qiita", "item_id": "0000000000000000000a", "note": "replace once posted"},
    {"platform": "devto", "article_id": "0000000", "note": "replace once posted"},
    {"platform": "hashnode", "slug": "jpcite-mcp-launch", "host": "bookyou.hashnode.dev", "note": "replace host once blog created"},
    {"platform": "hn", "item_id": "0", "note": "replace with Show HN item id"},
    {"platform": "producthunt", "slug": "jpcite", "note": "manual tracking"},
]


def load_targets() -> list[dict[str, str]]:
    if not TARGETS_FILE.exists():
        # First-run convenience: write the seed file under analytics/ (gitignored)
        # so the operator can edit it in-place. Falls back to DEFAULT_TARGETS if
        # the dir is read-only (CI runner).
        try:
            ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
            TARGETS_FILE.write_text(json.dumps(DEFAULT_TARGETS, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        return DEFAULT_TARGETS
    return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout only, do not append JSONL.")
    parser.add_argument("--platforms", default="", help="Comma-separated subset of platforms to probe.")
    args = parser.parse_args()

    targets = load_targets()
    if args.platforms:
        wanted = {p.strip() for p in args.platforms.split(",") if p.strip()}
        targets = [t for t in targets if t.get("platform") in wanted]

    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    snapshots: list[dict[str, object]] = []

    for t in targets:
        platform = t.get("platform")
        if platform == "zenn":
            r = probe_zenn(t.get("slug", ""))
        elif platform == "note":
            r = probe_note(t.get("slug", ""))
        elif platform == "qiita":
            r = probe_qiita(t.get("item_id", ""))
        elif platform == "devto":
            r = probe_devto(t.get("article_id", ""))
        elif platform == "hashnode":
            r = probe_hashnode(t.get("slug", ""), t.get("host", ""))
        elif platform == "hn":
            r = probe_hn(t.get("item_id", ""))
        elif platform == "producthunt":
            r = probe_producthunt(t.get("slug", ""))
        else:
            r = {"platform": platform, "error": "unknown platform"}
        r["snapshot_at_utc"] = ts
        snapshots.append(r)

    for r in snapshots:
        keys = [k for k in r if k not in ("platform", "snapshot_at_utc")]
        kv = " ".join(f"{k}={r[k]}" for k in keys[:8])
        print(f"[{r['platform']}] {kv}")

    if args.dry_run:
        print(f"[dry-run] would append {len(snapshots)} rows to {SNAPSHOT_FILE}")
        return 0

    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_FILE.open("a", encoding="utf-8") as fh:
        for r in snapshots:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[snapshot] appended {len(snapshots)} rows -> {SNAPSHOT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
