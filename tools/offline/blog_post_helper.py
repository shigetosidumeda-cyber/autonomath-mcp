#!/usr/bin/env python3
"""Cross-platform blog post helper for jpcite organic outreach.

Operator-only offline tool. Posts a single Markdown draft (under
``docs/announce/``) to one or more developer-blog platforms via each
platform's documented HTTP API — **token-based**, no LLM SDK imports,
so this script does NOT violate ``test_no_llm_in_production`` rules.

Supported platforms (publish target slugs):

- ``zenn``     — Zenn does NOT have a public publish API; this helper
                 falls back to "GitHub repo bind" instructions + writes a
                 ready-to-commit ``articles/<slug>.md`` snippet you can
                 ``git push`` against a zenn-cli linked repo.
- ``devto``    — https://developers.forem.com/api/v1#tag/articles  →
                 POST /api/articles  (header: ``api-key: <DEVTO_API_KEY>``)
- ``hashnode`` — https://api.hashnode.com  (GraphQL)
                 mutation: ``publishPost``  (header: ``Authorization: <HASHNODE_PAT>``)
- ``qiita``    — https://qiita.com/api/v2/docs#post-apiv2items
                 POST /api/v2/items  (header: ``Authorization: Bearer <QIITA_TOKEN>``)

Tokens loaded from ``.env.local`` (``DEVTO_API_KEY`` / ``HASHNODE_PAT`` /
``QIITA_TOKEN``). Missing tokens skip that platform.

Default mode is **dry-run** — prints the would-be POST envelope without
opening any HTTP connection. Pass ``--post`` to actually publish.

Usage::

    python3 tools/offline/blog_post_helper.py --draft zenn_jpcite_mcp.md
    python3 tools/offline/blog_post_helper.py --draft zenn_jpcite_mcp.md \
        --targets devto,qiita --post
    python3 tools/offline/blog_post_helper.py --draft zenn_jpcite_mcp.md \
        --targets zenn --post  # writes a zenn-cli-ready file under /tmp
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_LOCAL = REPO_ROOT / ".env.local"
ANNOUNCE_DIR = REPO_ROOT / "docs/announce"
INBOX_DIR = REPO_ROOT / "tools/offline/_inbox"

DEVTO_ENDPOINT = "https://dev.to/api/articles"
HASHNODE_ENDPOINT = "https://api.hashnode.com"
QIITA_ENDPOINT = "https://qiita.com/api/v2/items"


def _load_env_local() -> dict[str, str]:
    """Parse ``.env.local`` into a flat dict (no shell, no python-dotenv)."""
    env: dict[str, str] = {}
    if not ENV_LOCAL.exists():
        return env
    for raw in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        env[key] = value
    return env


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split optional Zenn-style YAML frontmatter (``---`` fenced) from the body.

    Returns a ``(meta, body)`` tuple. ``meta`` is a flat dict of
    ``key: value`` (strings only; we accept the simple shape Zenn drafts use
    and intentionally do NOT pull in a YAML lib).
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, str] = {}
    for raw in fm.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _first_h1(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return "jpcite — Japanese public-program evidence API"


def _tags_from_meta(meta: dict[str, str], fallback: list[str]) -> list[str]:
    raw = meta.get("topics") or meta.get("tags") or ""
    if raw.startswith("[") and raw.endswith("]"):
        items = [t.strip().strip('"').strip("'") for t in raw[1:-1].split(",")]
        items = [t for t in items if t]
        if items:
            return items
    return fallback


def _archive(slug: str, payload: dict[str, object]) -> pathlib.Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = INBOX_DIR / f"{ts}_blog_post_{slug}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _http_post_json(url: str, headers: dict[str, str], body: object) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - operator HTTP
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace") if exc.fp else repr(exc)
    except Exception as exc:  # pragma: no cover - operator surface
        return 0, repr(exc)


def post_devto(env: dict[str, str], title: str, body: str, tags: list[str], do_post: bool) -> dict[str, object]:
    token = env.get("DEVTO_API_KEY", "")
    if do_post and not token:
        return {"platform": "devto", "status": "skipped", "reason": "no DEVTO_API_KEY"}
    # dev.to caps tags at 4
    article_tags = [re.sub(r"[^a-zA-Z0-9]", "", t).lower() for t in tags][:4]
    payload = {
        "article": {
            "title": title,
            "body_markdown": body,
            "published": True,
            "tags": article_tags,
            "canonical_url": "https://jpcite.com/blog/jpcite-mcp-launch",
        }
    }
    if not do_post:
        return {"platform": "devto", "status": "dry-run", "payload": payload}
    code, text = _http_post_json(
        DEVTO_ENDPOINT, {"api-key": token}, payload
    )
    return {
        "platform": "devto",
        "status": "sent" if code in (200, 201) else "error",
        "http_status": code,
        "response_excerpt": text[:600],
    }


def post_hashnode(env: dict[str, str], title: str, body: str, tags: list[str], do_post: bool) -> dict[str, object]:
    token = env.get("HASHNODE_PAT", "")
    pub_id = env.get("HASHNODE_PUBLICATION_ID", "")
    if do_post and (not token or not pub_id):
        return {"platform": "hashnode", "status": "skipped", "reason": "no HASHNODE_PAT / HASHNODE_PUBLICATION_ID"}
    # Hashnode tags are objects {slug, name}; trim to 5
    tag_objs = [{"slug": re.sub(r"[^a-zA-Z0-9]", "", t).lower(), "name": t} for t in tags][:5]
    query = """
mutation publishPost($input: PublishPostInput!) {
  publishPost(input: $input) {
    post { id slug url }
  }
}
""".strip()
    payload = {
        "query": query,
        "variables": {
            "input": {
                "title": title,
                "contentMarkdown": body,
                "tags": tag_objs,
                "publicationId": pub_id or "REPLACE_ME",
            }
        },
    }
    if not do_post:
        return {"platform": "hashnode", "status": "dry-run", "payload": payload}
    code, text = _http_post_json(
        HASHNODE_ENDPOINT,
        {"Authorization": token},
        payload,
    )
    return {
        "platform": "hashnode",
        "status": "sent" if code == 200 and '"errors"' not in text else "error",
        "http_status": code,
        "response_excerpt": text[:600],
    }


def post_qiita(env: dict[str, str], title: str, body: str, tags: list[str], do_post: bool) -> dict[str, object]:
    token = env.get("QIITA_TOKEN", "")
    if do_post and not token:
        return {"platform": "qiita", "status": "skipped", "reason": "no QIITA_TOKEN"}
    qiita_tags = [{"name": t, "versions": []} for t in tags][:5]
    payload = {
        "title": title,
        "body": body,
        "tags": qiita_tags,
        "private": False,
        "tweet": False,
    }
    if not do_post:
        return {"platform": "qiita", "status": "dry-run", "payload": payload}
    code, text = _http_post_json(
        QIITA_ENDPOINT,
        {"Authorization": f"Bearer {token}"},
        payload,
    )
    return {
        "platform": "qiita",
        "status": "sent" if code in (200, 201) else "error",
        "http_status": code,
        "response_excerpt": text[:600],
    }


def post_zenn(title: str, body: str, meta: dict[str, str], do_post: bool, draft_name: str) -> dict[str, object]:
    """Zenn lacks a public publish API.

    We instead emit a zenn-cli-compatible ``articles/<slug>.md`` payload under
    ``/tmp/jpcite_zenn_articles/`` which the operator can ``git push`` into the
    Zenn-linked GitHub repo. ``do_post`` writes the file; default dry-run only
    prints the path it WOULD write.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", draft_name.replace(".md", "")).strip("-")[:50]
    out_dir = pathlib.Path("/tmp/jpcite_zenn_articles")
    out_path = out_dir / f"{slug}.md"

    # Re-emit frontmatter (Zenn drafts already carry it; keep verbatim if present)
    if meta:
        fm_lines = ["---"]
        for k, v in meta.items():
            fm_lines.append(f"{k}: {v}")
        fm_lines.append("---\n")
        full = "\n".join(fm_lines) + body
    else:
        full = body

    if not do_post:
        return {
            "platform": "zenn",
            "status": "dry-run",
            "would_write": str(out_path),
            "bytes": len(full),
            "note": "Zenn has no public publish API. Push this file under articles/ in your Zenn-linked GitHub repo.",
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full, encoding="utf-8")
    return {
        "platform": "zenn",
        "status": "written",
        "path": str(out_path),
        "bytes": len(full),
        "note": "Copy this file to articles/ in your Zenn-bound GitHub repo, then git push to publish.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", required=True, help="Markdown draft filename under docs/announce/")
    parser.add_argument(
        "--targets",
        default="zenn,devto,hashnode,qiita",
        help="Comma-separated platform slugs (default: all 4).",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Actually publish. Without this flag, dry-run only.",
    )
    args = parser.parse_args()

    draft_path = ANNOUNCE_DIR / args.draft
    if not draft_path.exists():
        print(f"ERROR: draft not found: {draft_path}", file=sys.stderr)
        return 2

    raw = draft_path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(raw)
    title = meta.get("title") or _first_h1(body)
    fallback_tags = ["mcp", "claudecode", "openapi", "japan", "ai"]
    tags = _tags_from_meta(meta, fallback_tags)

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    known = {"zenn", "devto", "hashnode", "qiita"}
    unknown = sorted(set(targets) - known)
    if unknown:
        print(f"ERROR: unknown target(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}", file=sys.stderr)
        return 2

    env = _load_env_local()
    print(f"[plan] draft={args.draft}  title={title[:80]}")
    print(f"[plan] targets={targets}  mode={'POST' if args.post else 'dry-run'}")
    print()

    results: list[dict[str, object]] = []
    for tgt in targets:
        if tgt == "zenn":
            r = post_zenn(title, body, meta, args.post, args.draft)
        elif tgt == "devto":
            r = post_devto(env, title, body, tags, args.post)
        elif tgt == "hashnode":
            r = post_hashnode(env, title, body, tags, args.post)
        elif tgt == "qiita":
            r = post_qiita(env, title, body, tags, args.post)
        else:  # unreachable due to validation above
            continue
        print(f"[{tgt}] {r.get('status')}  {r.get('http_status', '-')}")
        if "response_excerpt" in r:
            print(f"[{tgt}] {str(r['response_excerpt'])[:280]}")
        if "note" in r:
            print(f"[{tgt}] note: {r['note']}")
        results.append(r)

    out = _archive(args.draft.replace(".md", ""), {"mode": "post" if args.post else "dry-run", "results": results})
    print()
    print(f"[archive] {out}")

    if args.post:
        ok = sum(1 for r in results if r.get("status") in ("sent", "written"))
        err = sum(1 for r in results if r.get("status") == "error")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        print(f"[summary] sent/written={ok} errors={err} skipped={skipped} total={len(results)}")
        return 0 if err == 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
