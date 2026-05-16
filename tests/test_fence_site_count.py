"""Wave 46 tick6#10 - site/ 全 page fence_count 8/8 整合 grep verify.

Memory: feedback_destruction_free_organization / feedback_completion_gate_minimal

Canonical fence count = 8 業法 (税理士 / 弁護士 / 会計士 / 行政書士 / 司法書士 /
社労士 / 弁理士 / 労基)。site/ surface には旧 "6 業法" / "7 業法" / "5 業法 + 36協定"
ドリフトが 12 行残存していた (8 ファイル横断、main HEAD 3ac9f652)。

本 test は再発防止のための grep ベース invariant:
 1. site/*.html / site/*.md / site/llms.txt に "6 業法" "7 業法" "5 業法" が
    surface text として現れないこと
 2. canonical legal-fence.html / pricing.html は "8 業法" を含むこと

surface text の改ざんは行わない (法律名そのもの・36協定 などは触らず)。
あくまで fence_count の数値整合 (7→8 漏れ) を強制する。
"""

from __future__ import annotations

import re
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[1] / "site"

# Drift パターン: "<N> 業法" の N が 5/6/7 のいずれか
# (8 / 全 8 / 8/8 は OK、また「中小企業診断士登録規則」のような単独引用も OK)
DRIFT_RE = re.compile(r"[567]\s*業法")
CANONICAL_RE = re.compile(r"8\s*業法")


def _iter_target_files() -> list[Path]:
    targets: list[Path] = []
    for pattern in ("**/*.html", "**/*.md", "**/*.txt", "**/*.json"):
        for path in SITE_ROOT.glob(pattern):
            # node_modules / generated chunk は除外
            if "node_modules" in path.parts:
                continue
            targets.append(path)
    return targets


def test_no_5_6_7_gyohou_drift_in_site() -> None:
    """site/ 配下に "5 業法" / "6 業法" / "7 業法" surface text が無いこと。"""
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_target_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if DRIFT_RE.search(line):
                offenders.append((path.relative_to(SITE_ROOT), lineno, line.strip()[:200]))
    assert not offenders, f"fence_count drift detected ({len(offenders)} line(s)):\n" + "\n".join(
        f"  {p}:{ln}: {snippet}" for p, ln, snippet in offenders[:30]
    )


def test_legal_fence_page_states_8_gyohou() -> None:
    """canonical legal-fence.html が "8 業法" を含むこと。"""
    canonical = SITE_ROOT / "legal-fence.html"
    text = canonical.read_text(encoding="utf-8")
    assert CANONICAL_RE.search(text), "legal-fence.html does not declare '8 業法'"


def test_legal_fence_md_states_8_gyohou() -> None:
    """legal-fence.html.md companion が "8 業法" を含むこと。"""
    companion = SITE_ROOT / "legal-fence.html.md"
    text = companion.read_text(encoding="utf-8")
    assert CANONICAL_RE.search(text), "legal-fence.html.md does not declare '8 業法'"


def test_purchasing_page_states_8_gyohou() -> None:
    """法人購買 1-screen page が "8 業法" 表記であること。"""
    purchasing = SITE_ROOT / "trust" / "purchasing.html"
    text = purchasing.read_text(encoding="utf-8")
    assert CANONICAL_RE.search(text), "trust/purchasing.html does not declare '8 業法'"


def test_llms_txt_states_8_gyohou() -> None:
    """site/llms.txt の法令フェンス description が "8 業法" 表記であること。"""
    llms = SITE_ROOT / "llms.txt"
    text = llms.read_text(encoding="utf-8")
    assert CANONICAL_RE.search(text), "site/llms.txt does not declare '8 業法'"


def test_connect_pages_state_8_gyohou_fence() -> None:
    """site/connect/*.html (ChatGPT/Claude Code/Codex/Cursor) が "8 業法 fence" を含む。"""
    connect_dir = SITE_ROOT / "connect"
    expected = ["chatgpt.html", "claude-code.html", "codex.html", "cursor.html"]
    for name in expected:
        path = connect_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "8 業法" in text, f"connect/{name} does not mention '8 業法'"
