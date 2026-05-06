"""DEEP-64 — synthetic 1,200-entry identity_confidence golden set generator.

Spec: ``tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_64_identity_confidence_golden_set.md``

Builds ``tests/fixtures/identity_confidence_golden.yaml`` deterministically
(seed = 20260507) with 200 samples per axis × 6 axes = 1,200 entries.

This is the **first-pass synthetic** generator (DEEP-64 §6 stratified sourcing
from am_alias / am_entities is a follow-up phase). Templates use a small base
of brand stems + connectors so the produced YAML is reviewable without N=1200
hand-curation. NO LLM API.

Run
---

    .venv/bin/python scripts/ops/generate_identity_confidence_golden.py

Re-running with the same seed regenerates byte-identical YAML.
"""

from __future__ import annotations

import pathlib
import random

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT_PATH = REPO_ROOT / "tests" / "fixtures" / "identity_confidence_golden.yaml"

SEED = 20260507
PER_AXIS = 200

# Brand stems chosen to be NFKC-stable, kana-safe (axis 2 fold), and varied
# enough that axis 4/5 partial substrings hit real overlaps. 60 stems is
# enough for 200 samples per axis × small jitter.
BRAND_STEMS_KANA: tuple[str, ...] = (
    "サンライズ",
    "コウヨウ",
    "アサヒ",
    "ミドリ",
    "サクラ",
    "ヤマト",
    "フジ",
    "ニッポン",
    "トウキョウ",
    "オオサカ",
    "キョウト",
    "ナゴヤ",
    "ヨコハマ",
    "コウベ",
    "サッポロ",
    "センダイ",
    "ヒロシマ",
    "フクオカ",
    "ナハ",
    "カナザワ",
    "ハカタ",
    "ニイガタ",
    "シズオカ",
    "オカヤマ",
    "クマモト",
    "カゴシマ",
    "アオモリ",
    "アキタ",
    "イワテ",
    "ヤマガタ",
    "フクシマ",
    "イバラキ",
    "トチギ",
    "グンマ",
    "サイタマ",
    "チバ",
    "カナガワ",
    "トヤマ",
    "イシカワ",
    "フクイ",
    "ヤマナシ",
    "ナガノ",
    "ギフ",
    "ミエ",
    "シガ",
    "ナラ",
    "ワカヤマ",
    "トットリ",
    "シマネ",
    "ヤマグチ",
    "トクシマ",
    "カガワ",
    "エヒメ",
    "コウチ",
    "サガ",
    "ナガサキ",
    "オオイタ",
    "ミヤザキ",
    "オキナワ",
    "ホッカイドウ",
)

COHORTS: tuple[str, ...] = ("kabushiki", "godo", "yugen", "ippan", "sole")


def _katakana_to_hiragana(s: str) -> str:
    """Katakana U+30A1..U+30F6 -> Hiragana U+3041..U+3096."""
    out = []
    for ch in s:
        cp = ord(ch)
        if 0x30A1 <= cp <= 0x30F6:
            out.append(chr(cp - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _katakana_to_halfwidth(s: str) -> str:
    """Katakana -> half-width katakana (rough mapping for kana fold test).

    Only covers the 60 stems above; uses NFKD then keeps half-width forms.
    For fixture purposes we just emit the half-width katakana counterparts
    of common stems via a small lookup (good enough for axis 2 calibration).
    """
    table = str.maketrans(
        {
            "ア": "ｱ", "イ": "ｲ", "ウ": "ｳ", "エ": "ｴ", "オ": "ｵ",
            "カ": "ｶ", "キ": "ｷ", "ク": "ｸ", "ケ": "ｹ", "コ": "ｺ",
            "サ": "ｻ", "シ": "ｼ", "ス": "ｽ", "セ": "ｾ", "ソ": "ｿ",
            "タ": "ﾀ", "チ": "ﾁ", "ツ": "ﾂ", "テ": "ﾃ", "ト": "ﾄ",
            "ナ": "ﾅ", "ニ": "ﾆ", "ヌ": "ﾇ", "ネ": "ﾈ", "ノ": "ﾉ",
            "ハ": "ﾊ", "ヒ": "ﾋ", "フ": "ﾌ", "ヘ": "ﾍ", "ホ": "ﾎ",
            "マ": "ﾏ", "ミ": "ﾐ", "ム": "ﾑ", "メ": "ﾒ", "モ": "ﾓ",
            "ヤ": "ﾔ", "ユ": "ﾕ", "ヨ": "ﾖ",
            "ラ": "ﾗ", "リ": "ﾘ", "ル": "ﾙ", "レ": "ﾚ", "ロ": "ﾛ",
            "ワ": "ﾜ", "ヲ": "ｦ", "ン": "ﾝ",
            "ガ": "ｶﾞ", "ギ": "ｷﾞ", "グ": "ｸﾞ", "ゲ": "ｹﾞ", "ゴ": "ｺﾞ",
            "ザ": "ｻﾞ", "ジ": "ｼﾞ", "ズ": "ｽﾞ", "ゼ": "ｾﾞ", "ゾ": "ｿﾞ",
            "ダ": "ﾀﾞ", "ヂ": "ﾁﾞ", "ヅ": "ﾂﾞ", "デ": "ﾃﾞ", "ド": "ﾄﾞ",
            "バ": "ﾊﾞ", "ビ": "ﾋﾞ", "ブ": "ﾌﾞ", "ベ": "ﾍﾞ", "ボ": "ﾎﾞ",
            "パ": "ﾊﾟ", "ピ": "ﾋﾟ", "プ": "ﾌﾟ", "ペ": "ﾍﾟ", "ポ": "ﾎﾟ",
            "ャ": "ｬ", "ュ": "ｭ", "ョ": "ｮ", "ッ": "ｯ", "ー": "ｰ",
        }
    )
    return s.translate(table)


def _make_houjin_bangou(seq: int) -> str:
    """Build a 13-digit houjin_bangou using a deterministic counter."""
    # Pseudo-checkdigit but we only need uniqueness + valid length for the
    # fixture; checksum semantics are out of scope for axis 1 calibration.
    return f"{1010000000000 + seq:013d}"


def _entry(
    *,
    eid: str,
    axis: str,
    query: str,
    candidate: dict,
    expected_min: float,
    expected_max: float,
    cohort: str,
    address_match: bool | str,
    notes: str,
) -> dict:
    e: dict = {
        "id": eid,
        "axis": axis,
        "query": query,
        "expected_confidence_min": expected_min,
        "expected_confidence_max": expected_max,
        "cohort": cohort,
        "address_match": address_match,
        "notes": notes,
    }
    e.update(candidate)
    return e


def gen_axis1(rng: random.Random) -> list[dict]:
    """Axis 1 — houjin_bangou exact. expected score 1.0."""
    out: list[dict] = []
    for i in range(PER_AXIS):
        bangou = _make_houjin_bangou(i)
        out.append(
            _entry(
                eid=f"id_axis1_{i + 1:03d}",
                axis="houjin_bangou_exact",
                query=bangou,
                candidate={"candidate_houjin_bangou": bangou},
                expected_min=0.99,
                expected_max=1.00,
                cohort=rng.choice(COHORTS),
                address_match=True,
                notes="国税庁 houjin_bangou exact match (synthetic)",
            )
        )
    return out


def gen_axis2(rng: random.Random) -> list[dict]:
    """Axis 2 — kana_normalized. Hiragana <-> Katakana, half-width <-> full-width.

    Half of the samples use hiragana<>katakana, half use half-width<>full-width.
    All samples set address_match=True (DEEP-18 §1: kana_normalized requires addr).
    """
    out: list[dict] = []
    for i in range(PER_AXIS):
        stem = BRAND_STEMS_KANA[i % len(BRAND_STEMS_KANA)]
        if i % 2 == 0:
            # hiragana query <-> katakana candidate
            query = "かぶしきがいしゃ" + _katakana_to_hiragana(stem)
            candidate_name = "株式会社" + stem
            sub_notes = "hiragana<>katakana fold"
        else:
            # half-width katakana query <-> full-width candidate
            query = "ｶﾌﾞｼｷｶﾞｲｼｬ" + _katakana_to_halfwidth(stem)
            candidate_name = "株式会社" + stem
            sub_notes = "half-width<>full-width fold"
        out.append(
            _entry(
                eid=f"id_axis2_{i + 1:03d}",
                axis="kana_normalized",
                query=query,
                candidate={"candidate_houjin_name": candidate_name},
                expected_min=0.90,
                expected_max=0.97,
                cohort="kabushiki",
                address_match=True,
                notes=f"kana_normalized — {sub_notes}",
            )
        )
    return out


def gen_axis3(rng: random.Random) -> list[dict]:
    """Axis 3 — legal_form_variant. (株) <-> ㈱ <-> 株式会社, address_match=False."""
    # Pairs are (query_form, candidate_form). Both forms must reduce to the
    # same bare brand under NFKC + strip_legal_form. ㈱ (U+3231) decomposes
    # to (株) under NFKC, so the pair is robust. (同) and (有) have no
    # widely-deployed single-codepoint enclosed variants — we use the
    # parenthesized-half-width form for one half of the pair instead.
    pairs = (
        ("(株)", "株式会社"),
        ("㈱", "株式会社"),
        ("(株)", "株式会社"),
        ("(同)", "合同会社"),
        ("(同)", "合同会社"),
        ("(有)", "有限会社"),
        ("(有)", "有限会社"),
    )
    out: list[dict] = []
    for i in range(PER_AXIS):
        prefix_q, prefix_c = pairs[i % len(pairs)]
        stem = BRAND_STEMS_KANA[i % len(BRAND_STEMS_KANA)]
        query = f"{prefix_q}{stem}"
        candidate_name = f"{prefix_c}{stem}"
        cohort = "kabushiki"
        if "合同" in prefix_c:
            cohort = "godo"
        elif "有限" in prefix_c:
            cohort = "yugen"
        out.append(
            _entry(
                eid=f"id_axis3_{i + 1:03d}",
                axis="legal_form_variant",
                query=query,
                candidate={"candidate_houjin_name": candidate_name},
                expected_min=0.85,
                expected_max=0.95,
                cohort=cohort,
                address_match=False,
                notes=f"legal-form pair {prefix_q} <-> {prefix_c}",
            )
        )
    return out


def gen_axis4(rng: random.Random) -> list[dict]:
    """Axis 4 — partial_with_address. partial brand prefix + same address."""
    out: list[dict] = []
    for i in range(PER_AXIS):
        stem = BRAND_STEMS_KANA[i % len(BRAND_STEMS_KANA)]
        # Partial: take first 3 kana
        partial = stem[:3]
        candidate_name = f"株式会社{stem}サービス"
        out.append(
            _entry(
                eid=f"id_axis4_{i + 1:03d}",
                axis="partial_with_address",
                query=partial,
                candidate={
                    "candidate_houjin_name": candidate_name,
                    "candidate_houjin_bangou": _make_houjin_bangou(i + 10000),
                },
                expected_min=0.78,
                expected_max=0.90,
                cohort="kabushiki",
                address_match=True,
                notes="partial brand + same prefecture+municipality",
            )
        )
    return out


def gen_axis5(rng: random.Random) -> list[dict]:
    """Axis 5 — partial_only. partial brand prefix + no address signal."""
    out: list[dict] = []
    for i in range(PER_AXIS):
        stem = BRAND_STEMS_KANA[i % len(BRAND_STEMS_KANA)]
        partial = stem[:3]
        candidate_name = f"株式会社{stem}コーポレーション"
        out.append(
            _entry(
                eid=f"id_axis5_{i + 1:03d}",
                axis="partial_only",
                query=partial,
                candidate={
                    "candidate_houjin_name": candidate_name,
                    "candidate_houjin_bangou": _make_houjin_bangou(i + 20000),
                },
                expected_min=0.55,
                expected_max=0.72,
                cohort="kabushiki",
                address_match=False,
                notes="同名異住所 false-positive risk",
            )
        )
    return out


def gen_axis6(rng: random.Random) -> list[dict]:
    """Axis 6 — alias_only. am_alias hit, no name overlap."""
    out: list[dict] = []
    for i in range(PER_AXIS):
        stem = BRAND_STEMS_KANA[i % len(BRAND_STEMS_KANA)]
        out.append(
            _entry(
                eid=f"id_axis6_{i + 1:03d}",
                axis="alias_only",
                query=f"旧{stem}商店",
                candidate={
                    "candidate_houjin_name": f"株式会社{stem}ホールディングス",
                    "candidate_houjin_bangou": _make_houjin_bangou(i + 30000),
                    "alias_only": True,
                },
                expected_min=0.45,
                expected_max=0.62,
                cohort="kabushiki",
                address_match="n/a",
                notes="am_alias trade_name / former_name only",
            )
        )
    return out


def main() -> None:
    rng = random.Random(SEED)
    entries: list[dict] = []
    entries.extend(gen_axis1(rng))
    entries.extend(gen_axis2(rng))
    entries.extend(gen_axis3(rng))
    entries.extend(gen_axis4(rng))
    entries.extend(gen_axis5(rng))
    entries.extend(gen_axis6(rng))
    assert len(entries) == 1200, len(entries)

    # de-dupe id check
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids), "duplicate id"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# DEEP-64 identity_confidence golden set — 1,200 entries (200 × 6 axes).\n"
        "# Auto-generated by scripts/ops/generate_identity_confidence_golden.py (seed=20260507).\n"
        "# Edit the generator, NOT this file.\n"
        "# Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_64_identity_confidence_golden_set.md\n"
        "# LLM API 0 — pure stdlib + pyyaml.\n"
        "\n"
    )
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(
            entries,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    print(f"wrote {len(entries)} entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
