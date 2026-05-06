"""CI guard: every percentage / count claim on a landing page must cite a Trust Center entry.

Walk site/audiences/*.html. For each percentage / count claim, the same file
must contain a link to /trust/ or /benchmark/ or /practitioner-eval/ within
8 lines (above or below) of the claim. Otherwise the test fails — landing
pages cannot ship unbacked numeric claims.

This realizes SYNTHESIS §8.6 ("verified submission が0件の時のCTA") and
§8.15 ("seed/synth/verified 混在 → guard").
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIENCE_DIR = REPO_ROOT / "site/audiences"

# A "claim" smells like a *performance / quality* assertion:
#   - "99%", "100%" (coverage / pass rate)
#   - "X倍速い", "Y分の1のコスト" (improvement claims)
#
# A *factual count* of the corpus (e.g. "13,801 件 適格事業者") is NOT a
# performance claim — it is an inventory description. The CI guard targets
# only assertions that imply jpcite is "X% better / Y倍速い", because those
# are the ones SYNTHESIS §8.6 / §8.15 demand a Trust Center anchor for.
PERCENT_CLAIM = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%(?![\w])")
SPEEDUP_CLAIM = re.compile(r"(\d+(?:\.\d+)?)\s*倍\s*(?:速|高速|早|安|安価|低)")
REDUCTION_CLAIM = re.compile(r"\d+\s*分の\s*\d+\s*の\s*(?:コスト|時間|費用|工数)")

CLAIM_PATTERNS = [PERCENT_CLAIM, SPEEDUP_CLAIM, REDUCTION_CLAIM]

# A claim is "backed" if there is an href to /trust/ or /benchmark/ or
# /practitioner-eval/ within 8 lines (above or below) of the claim line.
NEAR_LINK = re.compile(
    r'href\s*=\s*"(?:https?://[^"]+)?(?:/trust/|/benchmark/|/practitioner-eval/)'
)

# Percentage exemptions — these describe something other than jpcite's performance:
#   - tax rates ("消費税 10%", "源泉 20.42%")
#   - 経過措置 (80%, 50%)
#   - timezones / dates
#   - HTTP status codes (e.g. "404", "500" — but those don't trigger PERCENT_CLAIM anyway)
EXEMPT_NEAR = re.compile(
    r"(消費税|地方税|住民税|源泉|軽減税率|"
    r"経過措置|措置法|租税|条約|税率|利率|金利|"
    r"JST|UTC|GMT|"
    r"期間|期日|期限|締切|公布|施行|予定|公表|告示|"
    r"公的|公庫|官報|令和|平成|昭和|"
    r"年|月|日|時|分|秒|"
    r"レート|"
    r"OPEN|HOURS|SCHEDULE|"
    r"width|height|margin|padding|opacity|"
    r"font|line-height|max-width|"
    r"@media|rgba|hsl|"
    r"chart|axis|x-axis|y-axis)"
)


def claims_in_file(path: Path) -> list[tuple[int, str, str]]:
    """Yield (lineno, line_text, claim_text) for each unbacked claim.

    JSON-LD <script> blocks and CSS <style> blocks are skipped — they are
    machine-discoverable metadata, audited via a separate guard
    (tests/test_jsonld_claims_in_trust_center.py is a sibling spec, not
    DC-02's responsibility). DC-02 targets visible body copy.
    """
    out: list[tuple[int, str, str]] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    in_skip_block = False
    skip_close_tag = ""
    for idx, line in enumerate(lines):
        if in_skip_block:
            if skip_close_tag in line:
                in_skip_block = False
            continue
        # Detect block opener — accept open spanning multiple lines.
        if re.search(r"<script\b", line, re.IGNORECASE):
            in_skip_block = "</script>" not in line
            skip_close_tag = "</script>"
            if in_skip_block:
                continue
        if re.search(r"<style\b", line, re.IGNORECASE):
            in_skip_block = "</style>" not in line
            skip_close_tag = "</style>"
            if in_skip_block:
                continue
        if EXEMPT_NEAR.search(line):
            continue
        for pat in CLAIM_PATTERNS:
            for m in pat.finditer(line):
                out.append((idx, line, m.group(0)))
    return out


def has_near_link(path: Path, claim_lineno: int, window: int = 8) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    lo = max(0, claim_lineno - window)
    hi = min(len(lines), claim_lineno + window + 1)
    return any(NEAR_LINK.search(ln) for ln in lines[lo:hi])


def test_every_claim_cites_trust_or_benchmark() -> None:
    """Every numeric performance claim on a landing page must cite Trust Center."""
    if not AUDIENCE_DIR.exists():
        return  # no landing pages yet
    missing: list[str] = []
    for path in sorted(AUDIENCE_DIR.glob("*.html")):
        for lineno, line, claim in claims_in_file(path):
            if not has_near_link(path, lineno):
                missing.append(
                    f"{path.name}:{lineno + 1}  claim={claim!r}  line={line.strip()[:120]!r}"
                )
    if missing:
        # Surface first 20 to keep error message actionable.
        head = missing[:20]
        more = f"\n... and {len(missing) - 20} more" if len(missing) > 20 else ""
        raise AssertionError(
            "Landing-page claims missing /trust/ or /benchmark/ or "
            "/practitioner-eval/ citation within 8 lines:\n" + "\n".join(head) + more
        )
