"""Wave 46 tick7#6 - fence_count 8 法令対応表 + API docs propagation drift sweep.

Memory: feedback_destruction_free_organization / feedback_completion_gate_minimal

Wave 46 tick6 (PR #143) cleared site/ surface drift to 0 with `test_fence_site_count.py`.
This test is the **extra** sweep for the residual drift surfaces outside `site/*`:

 1. `docs/schemas/*.json` — agent / API contract schemas must not pin a stale 5/6/7
    業法 count (canonical = 8 per data/fence_registry.json + facts_registry.json).
 2. `site/connect/*.html` — each connector page must enumerate all 8 法令 (税理士法 /
    弁護士法 / 司法書士法 / 行政書士法 / 社労士法 / 公認会計士法 / 弁理士法 / 労働基準法 §36).
    The bare "8 業法 fence" string is already covered by `test_fence_site_count.py`;
    this test adds a stricter law-enumeration invariant.
 3. `scripts/check_publish_text.py` — fence-count gate comment must reference the
    current canonical (8 業法), not a stale "canonical 7 業法" floor that confuses
    future readers.

Banned: surface text 改ざん (法律名そのものは不変; 列挙の漏れだけを正す),
main worktree edit, 旧 brand 再導入, LLM API import.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. docs/schemas/*.json fence_count claim整合
# ---------------------------------------------------------------------------


def test_schemas_no_stale_5_6_7_gyohou() -> None:
    """docs/schemas/*.json 配下に "5 業法" / "6 業法" / "7 業法" が無いこと。"""
    schemas_dir = ROOT / "docs" / "schemas"
    if not schemas_dir.exists():
        return
    drift_re = re.compile(r"[567]\s*業法")
    offenders: list[tuple[str, int, str]] = []
    for path in sorted(schemas_dir.rglob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if drift_re.search(line):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, lineno, line.strip()[:200]))
    assert not offenders, (
        f"fence_count drift in docs/schemas/ ({len(offenders)} line(s)):\n"
        + "\n".join(f"  {p}:{ln}: {snippet}" for p, ln, snippet in offenders[:20])
    )


def test_client_company_folder_schema_declares_8_gyohou() -> None:
    """client_company_folder_v1_response.schema.json が "8 業法" 表記であること。"""
    schema = ROOT / "docs" / "schemas" / "client_company_folder_v1_response.schema.json"
    if not schema.exists():
        return
    text = schema.read_text(encoding="utf-8")
    assert re.search(r"8\s*業法", text), (
        "client_company_folder_v1_response.schema.json must declare '8 業法' "
        "to match data/fence_registry.json canonical_count=8"
    )


# ---------------------------------------------------------------------------
# 2. site/connect/*.html law-enumeration completeness
# ---------------------------------------------------------------------------


# fence_registry 順に並べた 8 法令の正準名。
# 同等の正式名であれば略号 (§52 / §72 / §73 / §19 / §27 / §47条の2 / §75 / §36) で識別。
LAW_TOKENS_REQUIRED = [
    "税理士法",  # §52
    "弁護士法",  # §72
    "司法書士法",  # §73
    "行政書士法",  # §19
    "社労士法",  # §27 — 社会保険労務士法 略
    "公認会計士法",  # §47条の2
    "弁理士法",  # §75
    "労働基準法",  # §36 (36協定)
]


def test_connect_pages_enumerate_all_8_laws() -> None:
    """site/connect/*.html (chatgpt / claude-code / codex / cursor) が
    `<details>` ブロック内で 8 法令全てを列挙していること。

    fence_registry canonical_count=8 だが、connector page の `<details>` summary
    が "8 業法 fence" としか書かれていないと AI agent には fence の対象が不明確。
    本 test は agent context 不足 (Layer 1 AX) の再発防止 invariant。
    """
    connect_dir = ROOT / "site" / "connect"
    expected_files = ["chatgpt.html", "claude-code.html", "codex.html", "cursor.html"]
    failures: list[str] = []
    for name in expected_files:
        path = connect_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        missing = [law for law in LAW_TOKENS_REQUIRED if law not in text]
        if missing:
            failures.append(f"{name}: missing {missing}")
    assert not failures, (
        "site/connect/ pages must enumerate all 8 laws (税理士法 / 弁護士法 / "
        "司法書士法 / 行政書士法 / 社労士法 / 公認会計士法 / 弁理士法 / 労働基準法):\n"
        + "\n".join(f"  {fail}" for fail in failures)
    )


# ---------------------------------------------------------------------------
# 3. scripts/check_publish_text.py fence-count comment 整合
# ---------------------------------------------------------------------------


def test_check_publish_text_comment_does_not_pin_canonical_7() -> None:
    """scripts/check_publish_text.py の fence-count gate コメントが
    旧 "canonical 7 業法" を文字通り宣言していないこと。
    """
    script = ROOT / "scripts" / "check_publish_text.py"
    text = script.read_text(encoding="utf-8")
    assert "canonical 7 業法" not in text, (
        "scripts/check_publish_text.py contains the stale 'canonical 7 業法' "
        "comment; update to reflect the post-Wave-46 canonical=8."
    )


# ---------------------------------------------------------------------------
# 4. fence_registry consistency (sanity)
# ---------------------------------------------------------------------------


def test_fence_registry_canonical_is_8() -> None:
    """data/fence_registry.json canonical_count must be 8 (post Wave 46 tick5)."""
    registry = ROOT / "data" / "fence_registry.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data.get("canonical_count") == 8, (
        f"fence_registry canonical_count={data.get('canonical_count')}, expected 8"
    )


def test_facts_registry_guard_is_8() -> None:
    """data/facts_registry.json guards.fence_count_canonical must be 8."""
    registry = ROOT / "data" / "facts_registry.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    canon = data.get("guards", {}).get("fence_count_canonical")
    assert canon == 8, f"facts_registry fence_count_canonical={canon}, expected 8"
