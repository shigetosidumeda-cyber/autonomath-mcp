#!/usr/bin/env python3
"""Submit jpcite article to Hashnode via GraphQL.

Usage:
    HASHNODE_TOKEN=xxx HASHNODE_PUBLICATION_ID=xxx python scripts/publish/submit_hashnode.py

Token acquisition (~30 sec):
    https://hashnode.com/settings/developer → "Generate New Token"
    publication id: visit your blog → settings → general → copy "Publication ID"
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "publication" / "submit" / "devto_jpcite.md"


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"')
    return fm, body


def main() -> int:
    token = os.environ.get("HASHNODE_TOKEN")
    pub_id = os.environ.get("HASHNODE_PUBLICATION_ID")
    if not token or not pub_id:
        print(
            "ERROR: HASHNODE_TOKEN or HASHNODE_PUBLICATION_ID not set.\n"
            "  Token: https://hashnode.com/settings/developer (~30 sec)\n"
            "  Publication id: your blog settings → general → 'Publication ID'",
            file=sys.stderr,
        )
        return 2

    text = SRC.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    title = fm.get("title", "jpcite — Japanese public-info MCP server")
    tags_raw = fm.get("tags", "mcp,ai,rag")
    tag_slugs = [t.strip() for t in tags_raw.split(",") if t.strip()][:5]
    # Hashnode tag input: {slug, name}
    tag_objs = [{"slug": s, "name": s.capitalize()} for s in tag_slugs]

    query = (
        "mutation Publish($input: PublishPostInput!) {"
        "  publishPost(input: $input) {"
        "    post { id slug url }"
        "  }"
        "}"
    )
    variables = {
        "input": {
            "title": title,
            "contentMarkdown": body,
            "publicationId": pub_id,
            "tags": tag_objs,
            "originalArticleURL": fm.get("canonical_url", "https://jpcite.com"),
        }
    }
    payload = {"query": query, "variables": variables}
    req = urllib.request.Request(
        "https://gql.hashnode.com",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "errors" in data:
                print(f"GraphQL errors: {json.dumps(data['errors'], ensure_ascii=False)}", file=sys.stderr)
                return 1
            post = data.get("data", {}).get("publishPost", {}).get("post", {})
            print(f"OK status={resp.status} id={post.get('id')} url={post.get('url')}")
            return 0
    except urllib.error.HTTPError as e:
        print(f"HTTPError {e.code}: {e.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
