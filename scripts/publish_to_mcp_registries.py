#!/usr/bin/env python3
"""LIVE submission to MCP-ecosystem registries (F6 task, 2026-04-25).

Companion to scripts/publish_to_registries.py (B10), which is *smoke-only*.
This script attempts **real** submission against each surface that has an
automatable endpoint, and otherwise records a manual GitHub-PR / web-form
checkpoint into ``docs/_internal/mcp_registry_runbook.md`` (operator-only).

Surfaces (this is the F6 5-registry slice — for the full 12, see B10):
    1. MCP Official Registry  POST /v0/publish (after GH-OAuth → JWT)
    2. DXT (Anthropic)         no public submission API; .mcpb is self-host
    3. Smithery                no public submission API; auto-index from repo
    4. Glama                   no public submission API; auto-index from repo
    5. PulseMCP / mcp.so /     manual GitHub PR or form
       Awesome MCP

Design rules (per task brief):
    - Never call Anthropic API / claude CLI / SDK.
    - Credentials only via env (GH_TOKEN, GITHUB_TOKEN, SMITHERY_TOKEN, …).
    - If credential is absent → record manual step in runbook + skip.
    - LIVE submission once-and-only-once: each call is preceded by a dry-run
      validation step against the registry's /validate endpoint where
      available.
    - Runbook records URL, expected review window, and rollback action.

Usage:
    .venv/bin/python scripts/publish_to_mcp_registries.py [--dry-run]
                    [--only mcp_registry,dxt] [--repo .]

Exit codes:
    0  every requested surface returned ok (LIVE) or skipped-manual
    1  at least one surface failed unexpectedly (e.g., 5xx, malformed JSON)
    2  CLI / arg error
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import certifi  # type: ignore

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK_PATH = REPO_ROOT / "docs" / "_internal" / "mcp_registry_runbook.md"
RESULT_JSON = REPO_ROOT / "scripts" / "mcp_publish_result.json"

REGISTRY_API = "https://registry.modelcontextprotocol.io"
REGISTRY_VALIDATE = f"{REGISTRY_API}/v0/validate"
REGISTRY_PUBLISH = f"{REGISTRY_API}/v0/publish"
REGISTRY_AUTH_GH_AT = f"{REGISTRY_API}/v0/auth/github-at"

# ---------------------------------------------------------------------------
# Tiny HTTP helpers — stdlib only, no requests dependency.
# ---------------------------------------------------------------------------


def _http(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any] | str]:
    """Return (status, parsed_or_text). Never raises on HTTP errors."""
    data: bytes | None = None
    hdr = {"accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdr["content-type"] = "application/json"
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text
    except urllib.error.URLError as e:
        return 0, f"network error: {e.reason}"


# ---------------------------------------------------------------------------
# Per-surface submission functions. Each returns dict with a fixed schema:
#   {id, title, status: live|skipped|fail, detail, url, manual_step}
# ---------------------------------------------------------------------------


@dataclass
class SubResult:
    id: str
    title: str
    status: str  # "live" | "skipped" | "fail"
    detail: str
    url: str = ""
    manual_step: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "url": self.url,
            "manual_step": self.manual_step,
        }


def _load_server_json(repo: Path) -> dict[str, Any]:
    return json.loads((repo / "server.json").read_text(encoding="utf-8"))


def submit_mcp_registry(repo: Path, dry_run: bool = False) -> SubResult:
    """1. MCP Official Registry — POST /v0/publish.

    Auth: GitHub OAuth access token via /v0/auth/github-at → JWT bearer.
    Namespace ``io.github.<org>/<name>`` requires the GH token to belong to
    the org (or the actor be an org member with publish rights).
    """
    sj = _load_server_json(repo)
    # 1a. Validate first (no auth needed)
    code, body = _http(REGISTRY_VALIDATE, "POST", body=sj)
    if code != 200:
        msg = (body.get("detail") if isinstance(body, dict) else body) or "validate fail"
        errs = body.get("errors", []) if isinstance(body, dict) else []
        err_brief = "; ".join(
            f"{e.get('location','?')}: {e.get('message','?')}" for e in errs
        )[:300]
        return SubResult(
            id="mcp_registry",
            title="MCP Official Registry",
            status="fail",
            detail=f"server.json failed /v0/validate (HTTP {code}): {msg} | {err_brief}",
            manual_step=(
                "Fix server.json schema errors above (most likely "
                "_meta.io.description ≤100 chars). server.json is owned by A9 — "
                "raise with operator before LIVE publish."
            ),
        )
    # 1b. Try to authenticate via env GH_TOKEN / GITHUB_TOKEN
    gh_token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not gh_token:
        return SubResult(
            id="mcp_registry",
            title="MCP Official Registry",
            status="skipped",
            detail="server.json validated OK, but GH_TOKEN/GITHUB_TOKEN not set; LIVE publish skipped.",
            manual_step=(
                "Run: GH_TOKEN=<token> .venv/bin/python scripts/publish_to_mcp_registries.py "
                "--only mcp_registry  (token must belong to AutonoMath GH org or have org publish rights)."
            ),
        )
    # 1c. Exchange GH access-token for registry JWT
    code, body = _http(
        REGISTRY_AUTH_GH_AT,
        "POST",
        body={"github_token": gh_token},
    )
    if code != 200 or not isinstance(body, dict) or "registry_token" not in body:
        return SubResult(
            id="mcp_registry",
            title="MCP Official Registry",
            status="fail",
            detail=f"GH→Registry token exchange failed (HTTP {code}): {body!r}"[:300],
            manual_step="Use mcp-publisher CLI device flow: `mcp-publisher login github && mcp-publisher publish --file server.json`",
        )
    jwt = body["registry_token"]
    if dry_run:
        return SubResult(
            id="mcp_registry",
            title="MCP Official Registry",
            status="skipped",
            detail="--dry-run: validate ok, GH→JWT exchange ok; LIVE POST /v0/publish not called.",
            url=f"{REGISTRY_API}/servers/{sj['name']}",
        )
    # 1d. LIVE publish
    code, body = _http(
        REGISTRY_PUBLISH,
        "POST",
        body=sj,
        headers={"authorization": f"Bearer {jwt}"},
    )
    if code in (200, 201):
        return SubResult(
            id="mcp_registry",
            title="MCP Official Registry",
            status="live",
            detail=f"Published {sj['name']}@{sj['version']} (HTTP {code}).",
            url=f"{REGISTRY_API}/servers/{sj['name']}",
        )
    return SubResult(
        id="mcp_registry",
        title="MCP Official Registry",
        status="fail",
        detail=f"POST /v0/publish HTTP {code}: {body!r}"[:300],
        manual_step="Re-run with valid GH_TOKEN scoped to the AutonoMath org.",
    )


def submit_dxt(repo: Path, dry_run: bool = False) -> SubResult:
    """2. DXT (Anthropic Desktop Extension) — no public submission API.

    DXT bundles are self-distributed: users download the .mcpb file and
    Claude Desktop installs them on double-click. There is no Anthropic
    DXT registry as of 2026-04-25. The Anthropic External Plugins
    Directory (clau.de/plugin-directory-submission) is a *separate*
    web-form, manual review 2-4 weeks. Always skipped from automation.
    """
    bundle = repo / "site" / "downloads" / "autonomath-mcp.mcpb"
    if not bundle.exists():
        return SubResult(
            id="dxt",
            title="DXT / Claude Desktop Extension",
            status="fail",
            detail=f".mcpb bundle missing at {bundle}",
            manual_step="Run: bash scripts/build_mcpb.sh",
        )
    return SubResult(
        id="dxt",
        title="DXT / Claude Desktop Extension",
        status="skipped",
        detail=(
            f".mcpb bundle present ({bundle.stat().st_size} bytes). DXT is "
            "self-distributing; no programmatic submission. Anthropic External "
            "Plugins Directory (separate, manual review) is form-based."
        ),
        url="https://autonomath.ai/downloads/autonomath-mcp.mcpb",
        manual_step=(
            "Optional: open https://clau.de/plugin-directory-submission and "
            "fill the form using docs/_internal/mcp_registry_submissions/anthropic_external_plugins.md "
            "(2-4 wk review). Bundle is already at /downloads/autonomath-mcp.mcpb."
        ),
    )


def submit_smithery(repo: Path, dry_run: bool = False) -> SubResult:
    """3. Smithery — auto-indexes any public GitHub repo with smithery.yaml.

    No public submission API. Operator action: visit smithery.ai/new and paste
    the repo URL to trigger an immediate crawl, then claim ownership.
    SMITHERY_TOKEN env not currently consumed by any documented endpoint.
    """
    sm = repo / "smithery.yaml"
    if not sm.exists():
        return SubResult(
            id="smithery",
            title="Smithery",
            status="fail",
            detail="smithery.yaml missing",
            manual_step="Restore smithery.yaml from a previous commit.",
        )
    return SubResult(
        id="smithery",
        title="Smithery",
        status="skipped",
        detail="smithery.yaml present; auto-indexed from public repo, no API submission.",
        url="https://smithery.ai/server/io.github.AutonoMath/autonomath-mcp",
        manual_step=(
            "On launch day: open https://smithery.ai/new and paste the repo "
            "URL https://github.com/AutonoMath/autonomath-mcp to force an "
            "immediate crawl. Then claim ownership via dashboard.smithery.ai."
        ),
    )


def submit_glama(repo: Path, dry_run: bool = False) -> SubResult:
    """4. Glama — auto-indexes any public GitHub repo with MCP manifest + README.

    No public submission API. Daily crawl. Listing appears within 24-48 h.
    """
    if not (repo / "README.md").exists() or not (repo / "LICENSE").exists():
        return SubResult(
            id="glama",
            title="Glama",
            status="fail",
            detail="README.md or LICENSE missing",
            manual_step="Restore README.md and LICENSE before submission.",
        )
    if not (repo / "server.json").exists():
        return SubResult(
            id="glama",
            title="Glama",
            status="fail",
            detail="server.json missing",
            manual_step="Restore server.json before submission.",
        )
    return SubResult(
        id="glama",
        title="Glama",
        status="skipped",
        detail="README + LICENSE + server.json present; Glama crawls daily, no API.",
        url="https://glama.ai/mcp/servers/AutonoMath/autonomath-mcp",
        manual_step=(
            "On launch day: ensure repo is public on GitHub. Listing appears "
            "in 24-48 h. After it appears, click 'Claim' on the Glama listing "
            "to verify GitHub ownership."
        ),
    )


def submit_pulsemcp(repo: Path, dry_run: bool = False) -> SubResult:
    """5a. PulseMCP — auto-ingest from MCP Official Registry.

    No direct submission needed if step #1 succeeded. Manual fallback form
    exists at https://www.pulsemcp.com/submit if listing missing after 7 d.
    """
    return SubResult(
        id="pulsemcp",
        title="PulseMCP",
        status="skipped",
        detail="auto-ingests from MCP Official Registry (#1) within ~1 week.",
        url="https://www.pulsemcp.com/servers/io.github.AutonoMath/autonomath-mcp",
        manual_step=(
            "If missing 7 d after MCP Official Registry publish: submit at "
            "https://www.pulsemcp.com/submit (web form; repo URL + description)."
        ),
    )


def submit_mcp_so(repo: Path, dry_run: bool = False) -> SubResult:
    """5b. mcp.so — form / GitHub-issue submission."""
    return SubResult(
        id="mcp_so",
        title="mcp.so",
        status="skipped",
        detail="mcp.so requires manual web-form or GitHub-issue submission.",
        url="https://mcp.so/submit",
        manual_step=(
            "Open https://mcp.so/submit; fields: name=AutonoMath, "
            "repo=https://github.com/AutonoMath/autonomath-mcp, "
            "category=government/finance, install=`uvx autonomath-mcp`."
        ),
    )


def submit_awesome_mcp(repo: Path, dry_run: bool = False) -> SubResult:
    """5c. Awesome MCP Servers (punkpeye) — GitHub PR.

    Could be automated via gh CLI but the entry text + section placement is
    review-bait; safer to manual-PR.
    """
    return SubResult(
        id="awesome_mcp",
        title="Awesome MCP Servers (punkpeye)",
        status="skipped",
        detail="GitHub PR submission; entry text in mcp_registries_submission.json.",
        url="https://github.com/punkpeye/awesome-mcp-servers",
        manual_step=(
            "gh repo fork punkpeye/awesome-mcp-servers --clone; insert one line under "
            "'Finance & Fintech' (alphabetical), entry text in "
            "scripts/mcp_registries_submission.json registries[].entry_draft."
        ),
    )


# ---------------------------------------------------------------------------
# Surface registry — task F6 5-surface scope.
# ---------------------------------------------------------------------------


@dataclass
class Surface:
    id: str
    title: str
    fn: Callable[[Path, bool], SubResult]
    notes: str = ""


SURFACES: list[Surface] = [
    Surface("mcp_registry", "1. MCP Official Registry", submit_mcp_registry,
            "POST /v0/publish (GH-OAuth → JWT)."),
    Surface("dxt", "2. DXT (Anthropic Desktop Extension)", submit_dxt,
            ".mcpb is self-distributing; no API."),
    Surface("smithery", "3. Smithery", submit_smithery,
            "Auto-index from public GitHub repo."),
    Surface("glama", "4. Glama", submit_glama,
            "Auto-index from public GitHub repo (daily)."),
    Surface("pulsemcp", "5a. PulseMCP", submit_pulsemcp,
            "Auto-ingest from MCP Official Registry."),
    Surface("mcp_so", "5b. mcp.so", submit_mcp_so,
            "Manual web-form / GH-issue."),
    Surface("awesome_mcp", "5c. Awesome MCP Servers (punkpeye)", submit_awesome_mcp,
            "GitHub PR."),
]


# ---------------------------------------------------------------------------
# Runbook generator
# ---------------------------------------------------------------------------


def render_runbook(results: list[SubResult]) -> str:
    today = _dt.date.today().isoformat()
    lines = [
        "# MCP Registry Submission Runbook (operator-only, auto-generated)",
        "",
        f"_Generated: {today} by `scripts/publish_to_mcp_registries.py`._",
        "",
        "Companion to `scripts/mcp_registries.md` (canonical D-0 walkthrough)",
        "and `scripts/publish_to_registries.py` (smoke validator).",
        "This file records the **outcome of automated LIVE submission attempts**",
        "and lists every step that still requires a human (web form, GitHub PR,",
        "Claude Desktop UI). For each surface, the script either:",
        "",
        "- `live` — the registry now hosts our manifest (rollback steps below)",
        "- `skipped` — no automatable endpoint or credential missing; manual step recorded",
        "- `fail` — automation tried and a remote / schema error surfaced",
        "",
        "## Per-surface outcome",
        "",
    ]
    for r in results:
        marker = {"live": "[LIVE]", "skipped": "[skip]", "fail": "[FAIL]"}.get(r.status, "[?]")
        lines.append(f"### {r.title}")
        lines.append("")
        lines.append(f"- **Status**: `{r.status}` {marker}")
        lines.append(f"- **Detail**: {r.detail}")
        if r.url:
            lines.append(f"- **URL**: <{r.url}>")
        if r.manual_step:
            lines.append(f"- **Manual step**: {r.manual_step}")
        lines.append("")
    lines.extend(
        [
            "## Credential matrix",
            "",
            "| Env var | Used by | Notes |",
            "|---|---|---|",
            "| `GH_TOKEN` / `GITHUB_TOKEN` | MCP Official Registry (#1) | "
            "Must be a GH OAuth/PAT for an account with publish rights on the "
            "`AutonoMath` org. Without it, validation runs but LIVE publish is skipped. |",
            "| `SMITHERY_TOKEN` | (reserved) | Smithery has no documented "
            "submission API as of 2026-04-25; reserved name for future use. |",
            "| (none) | Glama, PulseMCP, DXT | Crawl-driven or self-distributing. |",
            "",
            "## Rollback",
            "",
            "| Surface | Rollback |",
            "|---|---|",
            "| MCP Official Registry | "
            "`POST /v0/publish` again with `version_metadata.status=deprecated` (no full delete). |",
            "| Smithery | dashboard.smithery.ai → Unclaim listing (does not delete; just removes ownership). |",
            "| Glama | No unpublish; remove repo public visibility to drop from index next crawl. |",
            "| DXT (.mcpb) | Remove file from `site/downloads/`; Cloudflare Pages "
            "redeploys without it. Already-installed clients keep the old bundle. |",
            "| PulseMCP / mcp.so / Awesome MCP | Open issue / PR to remove entry. |",
            "",
            "## Re-run",
            "",
            "```bash",
            "# Dry-run (validate-only; never POST publish)",
            ".venv/bin/python scripts/publish_to_mcp_registries.py --dry-run",
            "",
            "# Live MCP-Registry publish (requires GH_TOKEN scoped to AutonoMath org)",
            "GH_TOKEN=<token> .venv/bin/python scripts/publish_to_mcp_registries.py --only mcp_registry",
            "",
            "# Result JSON is also written to scripts/mcp_publish_result.json",
            "```",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + token-exchange only; never POST publish",
    )
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated surface ids to run (default: all)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO_ROOT,
        help=f"repo root (default: {REPO_ROOT})",
    )
    parser.add_argument(
        "--no-runbook",
        action="store_true",
        help="skip writing docs/_internal/mcp_registry_runbook.md",
    )
    args = parser.parse_args(argv)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    repo: Path = args.repo.resolve()

    results: list[SubResult] = []
    for s in SURFACES:
        if only and s.id not in only:
            continue
        try:
            r = s.fn(repo, args.dry_run)
        except Exception as exc:  # pragma: no cover
            r = SubResult(
                id=s.id,
                title=s.title,
                status="fail",
                detail=f"unhandled exception: {exc!r}",
            )
        results.append(r)

    # Write runbook
    if not args.no_runbook:
        RUNBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNBOOK_PATH.write_text(render_runbook(results), encoding="utf-8")

    # Write JSON result (consumed by launch CLI)
    RESULT_JSON.write_text(
        json.dumps(
            {
                "generated_at": _dt.datetime.now(_dt.UTC).isoformat(),
                "dry_run": args.dry_run,
                "results": [r.to_dict() for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Human report
    print(f"AutonoMath MCP-registry publish — repo={repo} dry_run={args.dry_run}")
    print("=" * 72)
    overall_ok = True
    for r in results:
        m = {"live": "[LIVE]", "skipped": "[skip]", "fail": "[FAIL]"}.get(r.status, "[?]")
        print(f"{m:<7} {r.title}")
        print(f"        {r.detail}")
        if r.url:
            print(f"        url: {r.url}")
        if r.manual_step:
            print(f"        manual: {r.manual_step}")
        if r.status == "fail":
            overall_ok = False
    print("=" * 72)
    print(f"OVERALL: {'OK' if overall_ok else 'FAIL'} | result: {RESULT_JSON}")
    if not args.no_runbook:
        print(f"runbook: {RUNBOOK_PATH}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
