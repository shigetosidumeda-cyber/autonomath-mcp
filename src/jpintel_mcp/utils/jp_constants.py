"""Japanese-domain lookup tables (industries, prefectures, niche programs).

Ported VERBATIM from Autonomath as of 2026-04-25:

  - INDUSTRY_ALIAS_TO_JSIC: backend/recommendation/adoption_lookup.py:79-102
    (originally `_INDUSTRY_ALIASES`)
  - PREFECTURE_TO_REGION:   backend/recommendation/adoption_lookup.py:415-432
    (originally `_REGIONS`; the task description cited 320-336 but the
    map actually lives at 415-432)
  - INDUSTRY_KEYWORDS:      backend/recommendation/factors.py:31-58
    (originally `_INDUSTRY_SPECIFIC_KEYWORDS`)
  - NICHE_PROGRAM_KEYWORDS: backend/recommendation/factors.py:22-29
    (originally `_NICHE_KEYWORDS`, materialised as a frozenset for O(1)
    membership; the source tuple holds 27 unique strings — the task brief's
    "19 items" undercount was reconciled to the real source figure)

Verified counts (against Autonomath HEAD as of 2026-04-25):
  INDUSTRY_ALIAS_TO_JSIC = 22 pairs   (task brief said ~23)
  PREFECTURE_TO_REGION   = 47 entries (matches)
  INDUSTRY_KEYWORDS      = 13 sectors (matches)
  NICHE_PROGRAM_KEYWORDS = 27 keywords (task brief said 19)

Pure-stdlib, O(1) lookups (dict / frozenset). No CLI / MCP wiring here.
"""

from __future__ import annotations

# ── 業種ゆらぎの正規化 (JSIC 大分類 / 日常語 → 正規化キー) ──────────
INDUSTRY_ALIAS_TO_JSIC: dict[str, str] = {
    "農業": "農業、林業",
    "林業": "農業、林業",
    "漁業": "漁業",
    "製造": "製造業",
    "製造業": "製造業",
    "建設": "建設業",
    "建設業": "建設業",
    "小売": "卸売業、小売業",
    "卸売": "卸売業、小売業",
    "卸売業": "卸売業、小売業",
    "小売業": "卸売業、小売業",
    "it": "情報通信業",
    "IT": "情報通信業",
    "情報通信": "情報通信業",
    "飲食": "宿泊業、飲食サービス業",
    "宿泊": "宿泊業、飲食サービス業",
    "飲食業": "宿泊業、飲食サービス業",
    "医療": "医療、福祉",
    "福祉": "医療、福祉",
    "不動産": "不動産業、物品賃貸業",
    "運輸": "運輸業、郵便業",
    "教育": "教育、学習支援業",
}


# ── 都道府県 → 地方ブロック ──────────────────────────────────────
PREFECTURE_TO_REGION: dict[str, str] = {
    "北海道": "北海道",
    "青森県": "東北", "岩手県": "東北", "宮城県": "東北", "秋田県": "東北",
    "山形県": "東北", "福島県": "東北",
    "茨城県": "関東", "栃木県": "関東", "群馬県": "関東", "埼玉県": "関東",
    "千葉県": "関東", "東京都": "関東", "神奈川県": "関東",
    "新潟県": "中部", "富山県": "中部", "石川県": "中部", "福井県": "中部",
    "山梨県": "中部", "長野県": "中部", "岐阜県": "中部", "静岡県": "中部",
    "愛知県": "中部",
    "三重県": "近畿", "滋賀県": "近畿", "京都府": "近畿", "大阪府": "近畿",
    "兵庫県": "近畿", "奈良県": "近畿", "和歌山県": "近畿",
    "鳥取県": "中国", "島根県": "中国", "岡山県": "中国", "広島県": "中国",
    "山口県": "中国",
    "徳島県": "四国", "香川県": "四国", "愛媛県": "四国", "高知県": "四国",
    "福岡県": "九州", "佐賀県": "九州", "長崎県": "九州", "熊本県": "九州",
    "大分県": "九州", "宮崎県": "九州", "鹿児島県": "九州",
    "沖縄県": "沖縄",
}


# ── 業種特化キーワード ──────────────────────────────────────────
INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "農業": ("農", "就農", "水産", "畜産", "果樹", "みどり", "スマート農", "新規就農", "農林"),
    "医療": (
        "医療", "クリニック", "診療", "医療機関", "医療DX", "病院",
        "看護", "歯科", "薬局", "医師", "ヘルスケア", "修学資金",
    ),
    "介護": (
        "介護", "福祉", "処遇改善", "障害福祉", "児童福祉", "高齢",
        "離職防止", "キャリアアップ", "育児", "両立支援", "生活衛生",
    ),
    "建設": ("建設", "建築", "工事", "インフラ", "住宅", "リフォーム"),
    "製造業": ("ものづくり", "製造", "生産性向上", "技術開発", "設備投資"),
    "IT": ("IT", "デジタル", "DX", "AI", "ソフトウェア", "生成AI", "情報通信"),
    "飲食": ("飲食", "外食", "レストラン", "食品"),
    "小売": ("小売", "商店街", "物販"),
    "観光": ("観光", "宿泊", "ツーリズム", "インバウンド", "旅館", "地域観光"),
    "運輸": ("運輸", "物流", "トラック", "配送"),
    "メディア": (
        "メディア", "コンテンツ", "映像", "放送", "音楽", "ゲーム",
        "アニメ", "映画", "エンタメ", "IP", "出版", "クリエイター",
        "文化芸術", "デジタルコンテンツ",
    ),
    "不動産": (
        "空き家", "リフォーム", "住宅", "賃貸", "長期優良住宅",
        "不動産", "土地活用", "建物所有", "建物賃貸",
    ),
    "金融": ("金融", "フィンテック", "FinTech"),
}


# ── ニッチ・特化型プログラムを示すキーワード ────────────────────
NICHE_PROGRAM_KEYWORDS: frozenset[str] = frozenset({
    "NEDO", "SBIR", "JST", "研究開発型", "研究助成", "学術",
    "ZEB", "ZEH", "建築物", "住宅省エネ", "耐震改修",
    "省エネルギー投資促進", "省エネ・非化石", "大規模成長投資",
    "IP360", "Go-Tech", "グローバル枠", "グローバル展開",
    "ゲーム", "アニメ", "映画", "実写", "酒類", "酒蔵",
    "漁業", "林業", "鉱業",
})


# ── helpers ─────────────────────────────────────────────────────
def normalize_industry(raw: str) -> str:
    """Map fuzzy industry input → canonical JSIC 大分類.

    Returns ``raw`` unchanged if no alias matches (matching the upstream
    Autonomath behaviour, where ``_normalize_industry`` falls back to the
    raw string when nothing maps).
    """
    if not raw:
        return raw
    return INDUSTRY_ALIAS_TO_JSIC.get(raw, raw)


def prefecture_region(pref: str) -> str | None:
    """Map prefecture (e.g. ``東京都``) to its regional block.

    Returns ``None`` for unknown / empty input.
    """
    if not pref:
        return None
    return PREFECTURE_TO_REGION.get(pref)


def is_niche_program(name: str) -> bool:
    """True iff ``name`` contains any niche-program keyword (substring match)."""
    if not name:
        return False
    for kw in NICHE_PROGRAM_KEYWORDS:
        if kw in name:
            return True
    return False


def industry_relevance_keywords(industry: str) -> tuple[str, ...]:
    """Return the keyword tuple associated with ``industry``.

    Empty tuple if the industry is not registered.
    """
    if not industry:
        return ()
    return INDUSTRY_KEYWORDS.get(industry, ())
