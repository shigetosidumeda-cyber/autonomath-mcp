"""Canonical 47 都道府県 slug + JA name pairs.

Usage:
    from scripts._pref_slugs import PREFECTURES
    for slug, name_ja in PREFECTURES:
        ...

Slugs are romaji (hepburn-ish) lowercase, no diacritics, ASCII-only.
Order: ISO 3166-2:JP-01 (北海道) → JP-47 (沖縄県). Keep this canonical.
"""

from __future__ import annotations

PREFECTURES: list[tuple[str, str]] = [
    ("hokkaido", "北海道"),
    ("aomori", "青森県"),
    ("iwate", "岩手県"),
    ("miyagi", "宮城県"),
    ("akita", "秋田県"),
    ("yamagata", "山形県"),
    ("fukushima", "福島県"),
    ("ibaraki", "茨城県"),
    ("tochigi", "栃木県"),
    ("gunma", "群馬県"),
    ("saitama", "埼玉県"),
    ("chiba", "千葉県"),
    ("tokyo", "東京都"),
    ("kanagawa", "神奈川県"),
    ("niigata", "新潟県"),
    ("toyama", "富山県"),
    ("ishikawa", "石川県"),
    ("fukui", "福井県"),
    ("yamanashi", "山梨県"),
    ("nagano", "長野県"),
    ("gifu", "岐阜県"),
    ("shizuoka", "静岡県"),
    ("aichi", "愛知県"),
    ("mie", "三重県"),
    ("shiga", "滋賀県"),
    ("kyoto", "京都府"),
    ("osaka", "大阪府"),
    ("hyogo", "兵庫県"),
    ("nara", "奈良県"),
    ("wakayama", "和歌山県"),
    ("tottori", "鳥取県"),
    ("shimane", "島根県"),
    ("okayama", "岡山県"),
    ("hiroshima", "広島県"),
    ("yamaguchi", "山口県"),
    ("tokushima", "徳島県"),
    ("kagawa", "香川県"),
    ("ehime", "愛媛県"),
    ("kochi", "高知県"),
    ("fukuoka", "福岡県"),
    ("saga", "佐賀県"),
    ("nagasaki", "長崎県"),
    ("kumamoto", "熊本県"),
    ("oita", "大分県"),
    ("miyazaki", "宮崎県"),
    ("kagoshima", "鹿児島県"),
    ("okinawa", "沖縄県"),
]

SLUG_TO_JA: dict[str, str] = dict(PREFECTURES)
JA_TO_SLUG: dict[str, str] = {ja: slug for slug, ja in PREFECTURES}

# Region grouping for the index page (so 47 link grid is scannable, not flat).
REGIONS: list[tuple[str, list[str]]] = [
    ("北海道・東北", ["hokkaido", "aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima"]),
    ("関東", ["ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa"]),
    (
        "中部",
        [
            "niigata",
            "toyama",
            "ishikawa",
            "fukui",
            "yamanashi",
            "nagano",
            "gifu",
            "shizuoka",
            "aichi",
        ],
    ),
    ("近畿", ["mie", "shiga", "kyoto", "osaka", "hyogo", "nara", "wakayama"]),
    ("中国", ["tottori", "shimane", "okayama", "hiroshima", "yamaguchi"]),
    ("四国", ["tokushima", "kagawa", "ehime", "kochi"]),
    (
        "九州・沖縄",
        ["fukuoka", "saga", "nagasaki", "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa"],
    ),
]

assert sum(len(slugs) for _, slugs in REGIONS) == 47, "REGIONS must cover 47 prefectures"
assert len(PREFECTURES) == 47, "PREFECTURES must have exactly 47 entries"
