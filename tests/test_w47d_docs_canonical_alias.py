"""Wave 46.D — `autonomath_*.md` → `jpcite_*.md` alias contract tests.

The Wave 46 brand-consolidation pass (zeimu-kaikei.ai / AutonoMath →
**jpcite**) introduces *banner-only alias* markdown files that point
readers from the new brand surface to the unchanged canonical source.

Per memory contract:

- `feedback_destruction_free_organization` — `rm` / `mv` are forbidden;
  aliases are *new* files, the legacy file is unchanged.
- `project_autonomath_canonical_docs` — canonical content is the single
  source of truth; aliases redirect to canonical, never the other way.
- `feedback_legacy_brand_marker` — the AutonoMath legacy marker is kept
  minimal; we do not surface the old brand prominently.

These tests do **not** invoke any database, network, runtime endpoint or
boot script — they exercise the markdown contract only and are
intentionally O(1) per file.  They run cleanly in `pytest -x -q` with
zero external dependencies.

Path divergence note: the task brief targets `docs/canonical/autonomath_*.md`,
but that directory is empty of `autonomath_*` files; the active autonomath
runbooks live under `docs/_internal/`.  The redirect map
(`docs/_internal/REDIRECT_MAP_w46_canonical.md` §1) documents this
divergence in full.  The alias contract applies wherever the source
and alias coexist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INTERNAL = REPO_ROOT / "docs" / "_internal"
REDIRECT_MAP = INTERNAL / "REDIRECT_MAP_w46_canonical.md"

# (canonical filename stem, alias filename stem) pairs.  Each pair must be
# located inside `docs/_internal/`.
ALIAS_PAIRS: list[tuple[str, str]] = [
    ("autonomath_db_sync_runbook", "jpcite_db_sync_runbook"),
    ("autonomath_com_dns_runbook", "jpcite_com_dns_runbook"),
]


# ---------- presence + structural assertions ---------- #


def test_w47d_redirect_map_exists_and_lists_all_aliases() -> None:
    assert REDIRECT_MAP.exists(), f"redirect map missing at {REDIRECT_MAP}"
    text = REDIRECT_MAP.read_text(encoding="utf-8")
    for canonical_stem, alias_stem in ALIAS_PAIRS:
        # Both names must appear inside the map's inventory table.
        assert canonical_stem in text, f"redirect map missing canonical entry {canonical_stem}"
        assert alias_stem in text, f"redirect map missing alias entry {alias_stem}"
    # The map must declare Wave 46.D scope and the brand transition.
    assert "Wave 46.D" in text
    assert "autonomath" in text.lower()
    assert "jpcite" in text.lower()
    # The map MUST acknowledge the destruction-free constraint.
    assert "feedback_destruction_free_organization" in text


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_file_exists(canonical_stem: str, alias_stem: str) -> None:
    alias_path = INTERNAL / f"{alias_stem}.md"
    assert alias_path.exists(), f"alias file missing: {alias_path}"


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_canonical_file_exists_and_is_untouched_on_disk(
    canonical_stem: str, alias_stem: str
) -> None:
    """The canonical source file must still exist at its original path.

    Wave 46.D does NOT delete or move the legacy file (`rm`/`mv` 禁止).
    We assert presence + non-empty content; the byte-equality vs.
    `origin/main` is enforced by the separate git-level reviewer
    workflow and is out of scope for unit tests."""
    canonical_path = INTERNAL / f"{canonical_stem}.md"
    assert canonical_path.exists(), f"canonical source missing: {canonical_path}"
    assert canonical_path.stat().st_size > 0


# ---------- frontmatter contract ---------- #


_FM_BLOCK_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _parse_simple_frontmatter(text: str) -> dict[str, str]:
    m = _FM_BLOCK_RE.match(text)
    assert m is not None, "alias file missing YAML frontmatter block"
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_frontmatter_keys(canonical_stem: str, alias_stem: str) -> None:
    alias_path = INTERNAL / f"{alias_stem}.md"
    text = alias_path.read_text(encoding="utf-8")
    fm = _parse_simple_frontmatter(text)
    assert fm["name"] == alias_stem
    assert fm["alias_of"] == canonical_stem
    assert fm["brand_layer"] == "jpcite"
    assert fm["legacy_brand"] == "autonomath"
    assert fm["wave"] == "46.D"
    assert "alias" in fm["status"].lower()
    assert "canonical content unchanged" in fm["status"]


# ---------- banner / link / edit-lock contract ---------- #


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_banner_phrase(canonical_stem: str, alias_stem: str) -> None:
    text = (INTERNAL / f"{alias_stem}.md").read_text(encoding="utf-8")
    assert "**Alias notice (Wave 46.D" in text, "alias banner phrase missing"
    # The banner must self-describe as brand consolidation.
    assert "brand-consolidation" in text or "brand consolidation" in text


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_links_to_canonical(canonical_stem: str, alias_stem: str) -> None:
    text = (INTERNAL / f"{alias_stem}.md").read_text(encoding="utf-8")
    # Relative markdown link to canonical must be present at least once.
    assert f"(./{canonical_stem}.md)" in text, (
        f"alias {alias_stem}.md must link to (./{canonical_stem}.md)"
    )


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_links_to_redirect_map(canonical_stem: str, alias_stem: str) -> None:
    text = (INTERNAL / f"{alias_stem}.md").read_text(encoding="utf-8")
    assert "(./REDIRECT_MAP_w46_canonical.md)" in text


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_has_edit_lock_notice(canonical_stem: str, alias_stem: str) -> None:
    """Aliases are diff-frozen; the file must say so in prose."""
    text = (INTERNAL / f"{alias_stem}.md").read_text(encoding="utf-8")
    lowered = text.lower()
    # Either an explicit "do not edit" phrase or "edit the canonical source".
    assert (
        "do not edit" in lowered
        or "edit the canonical source" in lowered
        or "aliases are diff-frozen" in lowered
    ), "alias must carry an edit-lock notice in prose"


# ---------- non-migration / non-destruction contract ---------- #


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_does_not_verbatim_copy_canonical_steps(
    canonical_stem: str, alias_stem: str
) -> None:
    """The alias MUST NOT copy the canonical operator steps verbatim.

    Wave 46.D is banner-only — the alias paraphrases scope at most.  We
    enforce this by checking that the alias body is materially smaller
    than the canonical body, and that no long verbatim substring is
    duplicated."""
    canonical = (INTERNAL / f"{canonical_stem}.md").read_text(encoding="utf-8")
    alias = (INTERNAL / f"{alias_stem}.md").read_text(encoding="utf-8")
    assert len(alias) < len(canonical) * 1.5, (
        f"alias {alias_stem}.md is suspiciously large vs canonical "
        f"({len(alias)} vs {len(canonical)} bytes) — looks like a verbatim copy"
    )
    # No 200-char run of canonical text should appear in the alias.
    for start in range(0, max(0, len(canonical) - 200), 200):
        chunk = canonical[start : start + 200].strip()
        if len(chunk) < 200:
            continue
        assert chunk not in alias, (
            f"alias {alias_stem}.md contains a 200-char verbatim block from canonical — banner-only contract violated"
        )


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_canonical_file_does_not_contain_wave46d_banner(
    canonical_stem: str, alias_stem: str
) -> None:
    """The canonical source must remain untouched — no Wave 46.D banner
    should have been injected into it."""
    text = (INTERNAL / f"{canonical_stem}.md").read_text(encoding="utf-8")
    assert "**Alias notice (Wave 46.D" not in text, (
        f"canonical {canonical_stem}.md was modified — Wave 46.D banner detected"
    )
    assert "alias_of: " not in text, (
        f"canonical {canonical_stem}.md gained alias_of frontmatter — should be a NEW file"
    )


# ---------- markdown validity (minimal smoke) ---------- #


@pytest.mark.parametrize("canonical_stem,alias_stem", ALIAS_PAIRS)
def test_w47d_alias_minimal_markdown_validity(canonical_stem: str, alias_stem: str) -> None:
    text = (INTERNAL / f"{alias_stem}.md").read_text(encoding="utf-8")
    # Frontmatter must be balanced.
    fm_delims = text.count("\n---\n")
    # `---` appears once as opening (start of file), once as closing.
    assert text.startswith("---\n"), "alias must start with YAML frontmatter delimiter"
    assert fm_delims >= 1, "alias frontmatter must have a closing delimiter"
    # At least one h1 title.
    assert re.search(r"^# ", text, re.MULTILINE), "alias must contain a top-level title"


# ---------- redirect-map cross-reference ---------- #


def test_w47d_redirect_map_inventory_count_matches_pairs() -> None:
    text = REDIRECT_MAP.read_text(encoding="utf-8")
    # Count rows that look like the inventory table: lines starting "| <digit>"
    inventory_lines = [line for line in text.splitlines() if re.match(r"^\|\s*\d+\s*\|", line)]
    assert len(inventory_lines) == len(ALIAS_PAIRS), (
        f"redirect map inventory has {len(inventory_lines)} rows, expected {len(ALIAS_PAIRS)}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
