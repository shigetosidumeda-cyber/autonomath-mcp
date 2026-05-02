"""Intent matcher + decision-tree binder for AutonoMath Layer 7.

Pipeline:
    raw_query (str, JP)
        -> classify_intent()     -- keyword scorer, 10-way softmax over Intent list
        -> extract_slots()       -- rule-based regex/keyword slot filling
        -> load_tree()           -- read reasoning/trees/<intent_id>.yaml
        -> bind_precomputed()    -- lookup precompute.py cache for compat/incompat/etc
        -> render_skeleton()     -- string.format the answer_skeleton with filled values
                                    returning a dict the LLM can paste-into

The LLM call itself is a stub — we do not call Claude here. The whole point is
to produce an answer_skeleton with every verifiable value (URL, date, amount,
partner program list) already filled in, so the LLM's job reduces to
natural-language polish — drastically reducing hallucination surface.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # loaded lazily; we fall back to a minimal parser below

from . import query_types
from .precompute import (
    PrecomputedCache,
    canonical_program_id,
    load_cache,
)

PKG_ROOT = Path(__file__).resolve().parent
TREES_DIR = PKG_ROOT / "trees"


# ---------------------------------------------------------------------------
# YAML loading (yaml package is not always installed — minimal fallback)
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    text = path.read_text()
    if yaml is not None:
        return yaml.safe_load(text)
    # Fallback: extract only top-level keys we actually need for bind/render.
    # This is brittle — use real yaml if available.
    result: Dict[str, Any] = {}
    key: Optional[str] = None
    buf: List[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if m:
            if key is not None:
                result[key] = "\n".join(buf).strip()
                buf = []
            key = m.group(1)
            val = m.group(2).strip()
            if val:
                result[key] = val
                key = None
        else:
            buf.append(line)
    if key is not None:
        result[key] = "\n".join(buf).strip()
    return result


# ---------------------------------------------------------------------------
# Intent classification (keyword scorer)
# ---------------------------------------------------------------------------

def classify_intent(query: str) -> Tuple[str, float, List[Tuple[str, int]]]:
    """Return (best_intent_id, confidence_0_to_1, all_scores[] for audit)."""
    scores: Dict[str, int] = {i.id: 0 for i in query_types.INTENTS}
    q = query
    for intent_id, keywords in query_types.INTENT_KEYWORDS:
        for kw in keywords:
            if kw in q:
                scores[intent_id] += len(kw)  # longer match = stronger signal
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_id, best_score = ranked[0]
    total = sum(scores.values())
    confidence = (best_score / total) if total > 0 else 0.0
    # If no signal, default to the broad-catch intent 01
    if best_score == 0:
        best_id = "i01_filter_programs_by_profile"
        confidence = 0.0
    return best_id, round(confidence, 3), ranked


# ---------------------------------------------------------------------------
# Slot extraction — rule-based per intent. Deliberately narrow; a real system
# would pass this through an LLM with a tool schema.
# ---------------------------------------------------------------------------

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

JSIC_LETTER_KW = {
    "A": ["農業", "林業"],
    "B": ["漁業"],
    "C": ["鉱業"],
    "D": ["建設業"],
    "E": ["製造業", "食品製造"],
    "F": ["電気", "ガス", "熱供給", "水道"],
    "G": ["情報通信", "IT業", "ソフトウェア"],
    "H": ["運輸", "物流"],
    "I": ["卸売", "小売"],
    "J": ["金融", "保険"],
    "K": ["不動産"],
    "L": ["学術研究", "専門・技術"],
    "M": ["宿泊", "飲食"],
    "N": ["生活関連", "娯楽"],
    "O": ["教育", "学習支援"],
    "P": ["医療", "福祉"],
    "Q": ["複合サービス"],
    "R": ["サービス業"],
}

SIZE_KW = {
    "sole": ["個人事業主", "フリーランス", "一人親方"],
    "small": ["小規模", "従業員5人", "従業員10人"],
    "sme": ["中小企業", "従業員30人", "従業員50人", "従業員100人"],
    "mid": ["中堅", "従業員300人", "従業員500人"],
    "large": ["大企業"],
}

THEME_KW = {
    "賃上げ": ["賃上げ", "賃金引き上げ", "時給"],
    "DX": ["DX", "デジタル化", "IT導入"],
    "GX_脱炭素": ["GX", "脱炭素", "カーボンニュートラル"],
    "省エネ": ["省エネ"],
    "人材育成": ["人材育成", "教育訓練"],
    "事業再構築": ["事業再構築", "業態転換"],
    "輸出": ["輸出", "海外展開"],
    "研究開発": ["研究開発", "試験研究"],
}

LIFECYCLE_KW = {
    "親族内承継": ["親族内承継", "親族承継"],
    "第三者承継_MA売手": ["M&A 売手", "売却", "事業譲渡(売手)"],
    "第三者承継_MA買手": ["M&A 買手", "M&A 買い手", "買収"],
    "従業員承継": ["従業員承継", "EBO"],
    "廃業_再チャレンジ": ["廃業", "再チャレンジ"],
    "廃業_清算のみ": ["清算", "会社解散"],
}

CERT_KW = [
    # Primary chusho-meti certifications (ordered: longest-most-specific first)
    "認定経営革新等支援機関", "経営革新等支援機関",
    "先端設備等導入計画", "経営力向上計画", "経営革新計画",
    "事業継続力強化計画", "地域経済牽引事業計画", "事業適応計画",
    "事業再編計画", "創業支援等事業計画", "特例承継計画",
    "経営発達支援計画", "異分野連携新事業分野開拓計画",
    "地域産業資源活用事業計画", "農商工等連携事業計画",
    # Brand-name certifications (commonly asked by name)
    "健康経営優良法人", "ホワイト500", "ブライト500", "ネクストブライト1000",
    "健康企業宣言", "スポーツエールカンパニー",
    "えるぼし", "くるみん", "ユースエール", "もにす",
    "SECURITY ACTION", "サイバーセキュリティお助け隊",
    "GAP認証", "エコアクション21", "低炭素建築物認定",
    "長期優良住宅", "Sマーク", "ハラール認証",
    "安全衛生優良企業", "SAFE", "ホワイトマーク",
    "情報処理支援機関", "スマートSMEサポーター",
    "事業承継計画",
]

MUNI_POP_KW = {
    "政令市": ["政令市", "政令指定都市"],
    "中核市": ["中核市", "中核 市"],
    "under_10k": ["人口1万", "人口 1 万", "人口1,000", "人口1千"],
    "10k_30k": ["人口3万", "人口 3 万", "人口2万", "人口 2 万"],
    "30k_100k": ["人口10万", "人口 10 万", "人口5万", "人口 5 万", "人口7万"],
    "100k_300k": ["人口30万", "人口 30 万", "人口20万", "人口 20 万", "人口15万"],
    "300k_plus": ["人口50万", "人口 50 万", "人口40万", "人口100万"],
}

CATEGORY_KW = {
    "空家対策": ["空家", "空き家"],
    "結婚新生活": ["結婚新生活", "結婚支援", "新婚", "婚活", "結婚 支援", "結婚 新生活"],
    "子育て": ["子育て", "子ども支援", "児童手当"],
    "移住定住": ["移住", "定住", "Uターン", "Iターン", "Jターン"],
    "省エネ": ["省エネ", "脱炭素", "カーボン", "再エネ", "再生可能", "太陽光", "EV"],
    "水道PFI": ["PFI", "上下水道", "水道 広域"],
    "ふるさと納税": ["ふるさと納税", "ふるさと 納税"],
    "地域振興": ["地域振興", "商店街", "街づくり"],
    "農業": ["農業振興", "担い手", "就農", "農業 補助"],
    "観光": ["観光振興", "インバウンド"],
    "創業": ["創業支援", "起業支援"],
}


def _extract_prefecture(q: str) -> Optional[str]:
    for p in PREFECTURES:
        if p in q:
            return p
    # allow "東京" -> "東京都" shorthand
    for p in PREFECTURES:
        stem = p[:-1] if p.endswith(("県", "府", "都")) else p
        if stem in q and stem != p:
            return p
    return None


def _extract_enum(q: str, kw_table: Dict[str, List[str]]) -> Optional[str]:
    for key, kws in kw_table.items():
        for kw in kws:
            if kw in q:
                return key
    return None


def _extract_theme(q: str) -> Optional[str]:
    return _extract_enum(q, THEME_KW)


def _extract_employee_count(q: str) -> Optional[int]:
    m = re.search(r"従業員\s*(\d+)\s*人", q)
    if m:
        return int(m.group(1))
    return None


def _extract_program_names(q: str, candidate_ids: List[str]) -> List[str]:
    hits: List[str] = []
    for cid in candidate_ids:
        if not cid:
            continue
        if cid in q:
            hits.append(cid)
    # Also catch common aliases that canonical might have normalized away
    alias_map = {
        "ものづくり補助金": "ものづくり・商業・サービス生産性向上促進補助金",
        "事業再構築補助金": "中小企業等事業再構築促進補助金",
        "IT導入補助金": "IT導入補助金",
        "持続化補助金": "小規模事業者持続化補助金",
        "省力化投資補助金": "中小企業省力化投資補助金",
    }
    for alias, canonical in alias_map.items():
        if alias in q and canonical not in hits:
            # only add if the canonical actually exists
            if canonical in candidate_ids or any(canonical in c for c in candidate_ids):
                hits.append(canonical)
    return hits


def extract_slots(intent_id: str, query: str, cache: PrecomputedCache) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    if intent_id == "i01_filter_programs_by_profile":
        slots["prefecture"] = _extract_prefecture(query)
        slots["jsic_industry"] = _extract_enum(query, JSIC_LETTER_KW)
        slots["business_size"] = _extract_enum(query, SIZE_KW)
        slots["employee_count"] = _extract_employee_count(query)
        slots["active_on"] = "2026-04-23"
    elif intent_id == "i02_program_deadline_documents":
        all_programs = list(cache.program_compat_closure.keys()) + list(cache.program_incompat_closure.keys())
        hits = _extract_program_names(query, list(set(all_programs)))
        slots["program_id"] = hits[0] if hits else None
        m = re.search(r"第?\s*(\d+)\s*[次回]", query)
        slots["round"] = int(m.group(1)) if m else None
        for dt in ["公募要領", "申請様式", "QA", "記入例", "完了報告書", "交付規程"]:
            if dt in query:
                slots["doc_type"] = dt
                break
    elif intent_id == "i03_program_successor_revision":
        all_programs = list(cache.program_compat_closure.keys()) + list(cache.program_incompat_closure.keys())
        hits = _extract_program_names(query, list(set(all_programs)))
        # Fallback: scan known succession-prone program keywords + free-text.
        if not hits:
            # Common keywords that appear in replaced programs in our data.
            candidates = [
                "技能実習制度", "育成就労制度", "技能実習", "育成就労",
                "ものづくり補助金", "IT導入補助金",
                "事業再構築補助金", "キャリアアップ助成金", "経営強化税制",
                "所得拡大促進税制", "賃上げ促進税制", "投資促進税制",
                "事業承継税制", "少額減価償却資産",
            ]
            for c in candidates:
                if c in query:
                    hits = [c]
                    break
        slots["program_id"] = hits[0] if hits else None
        m = re.search(r"令和\s*(\d+)\s*年度", query)
        if m:
            slots["fiscal_year"] = 2018 + int(m.group(1))  # 令和1=2019, 令和8=2026
        m2 = re.search(r"(202\d)\s*年度?", query)
        if m2 and "fiscal_year" not in slots:
            slots["fiscal_year"] = int(m2.group(1))
    elif intent_id == "i04_tax_measure_sunset":
        all_measures = list(cache.tax_measure_validity.keys())
        names = {cache.tax_measure_validity[mid].get("name", ""): mid
                 for mid in all_measures}
        # crude: find the longest tax-measure name contained in query
        best_mid = None
        best_len = 0
        for name, mid in names.items():
            if not name:
                continue
            stripped = canonical_program_id(name)
            if stripped and stripped in query and len(stripped) > best_len:
                best_mid = mid
                best_len = len(stripped)
        # fallback by keyword
        if best_mid is None:
            if "2割特例" in query or "インボイス" in query:
                # invoice_rules don't have validity_index; leave as None
                pass
            elif "賃上げ促進税制" in query:
                for name, mid in names.items():
                    if "賃上げ促進税制" in name:
                        best_mid = mid
                        break
        slots["measure_id"] = best_mid
        slots["as_of_date"] = "2026-04-23"
    elif intent_id == "i05_certification_howto":
        for c in CERT_KW:
            if c in query:
                slots["certification_id"] = c
                break
    elif intent_id == "i06_compat_incompat_stacking":
        all_programs = list(cache.program_compat_closure.keys()) + list(cache.program_incompat_closure.keys())
        hits = _extract_program_names(query, list(set(all_programs)))
        slots["program_ids"] = hits
    elif intent_id == "i07_adoption_cases":
        all_programs = list(cache.program_compat_closure.keys()) + list(cache.program_incompat_closure.keys())
        hits = _extract_program_names(query, list(set(all_programs)))
        slots["program_id"] = hits[0] if hits else None
        m = re.search(r"第\s*(\d+)\s*[回次]", query)  # 第N回 or 第N次
        slots["round"] = int(m.group(1)) if m else None
        slots["prefecture"] = _extract_prefecture(query)
        slots["industry_jsic"] = _extract_enum(query, JSIC_LETTER_KW)
    elif intent_id == "i08_similar_municipality_programs":
        slots["muni_population_band"] = _extract_enum(query, MUNI_POP_KW)
        slots["program_category"] = _extract_enum(query, CATEGORY_KW)
        # cluster keywords -> pref cluster enum
        cluster_kw = {
            "北海道東北": ["北海道東北", "東北"],
            "関東": ["関東"],
            "北陸甲信越": ["北陸", "甲信越"],
            "東海": ["東海"],
            "近畿": ["近畿", "関西"],
            "中国四国": ["中国四国", "中国地方", "四国"],
            "九州沖縄": ["九州", "沖縄"],
        }
        slots["pref_cluster"] = _extract_enum(query, cluster_kw)
        # source municipality (muni name followed by 市/区/町/村)
        import re as _re
        m_muni = _re.search(r"([一-龥ァ-ヴー]{2,6}(?:市|区|町|村))", query)
        if m_muni:
            slots["source_municipality"] = m_muni.group(1)
            # Auto-infer population band for major cities if not set
            if not slots.get("muni_population_band"):
                major = {
                    "横浜市": "300k_plus", "大阪市": "300k_plus", "名古屋市": "300k_plus",
                    "札幌市": "300k_plus", "福岡市": "300k_plus", "川崎市": "300k_plus",
                    "神戸市": "300k_plus", "京都市": "300k_plus", "さいたま市": "300k_plus",
                    "仙台市": "300k_plus", "広島市": "300k_plus", "千葉市": "300k_plus",
                    "北九州市": "300k_plus", "堺市": "300k_plus", "新潟市": "100k_300k",
                    "浜松市": "300k_plus", "静岡市": "100k_300k", "熊本市": "300k_plus",
                    "相模原市": "300k_plus", "岡山市": "300k_plus",
                }
                if slots["source_municipality"] in major:
                    slots["muni_population_band"] = major[slots["source_municipality"]]
        # infer muni from "人口X万"
        m = _re.search(r"人口\s*(\d+)\s*万", query)
        if m:
            n = int(m.group(1))
            if n < 3:
                slots["muni_population_band"] = "under_10k" if n == 1 else "10k_30k"
            elif n < 10:
                slots["muni_population_band"] = "10k_30k"
            elif n < 30:
                slots["muni_population_band"] = "30k_100k"
            elif n < 50:
                slots["muni_population_band"] = "100k_300k"
            else:
                slots["muni_population_band"] = "300k_plus"
        # If still no category but intent was classified as i08, use a broad default
        # so peer comparison at least fires general municipal programs.
        if not slots.get("program_category"):
            # Heuristic fallback: if query mentions 補助金/制度/支援 generically,
            # treat as 地域振興 so broad pref/dc/ordinance walk is triggered.
            if any(kw in query for kw in ("補助金", "支援制度", "制度比較", "比較")):
                slots["program_category"] = "地域振興"
    elif intent_id == "i09_succession_closure":
        slots["lifecycle_stage"] = _extract_enum(query, LIFECYCLE_KW) or "第三者承継_MA買手"
    elif intent_id == "i10_wage_dx_gx_themed":
        slots["theme"] = _extract_theme(query)
        m = re.search(r"(202\d)\s*年度?", query)
        slots["fiscal_year"] = int(m.group(1)) if m else 2026
    return slots


# ---------------------------------------------------------------------------
# Tree loading + skeleton rendering
# ---------------------------------------------------------------------------

def load_tree(intent_id: str) -> Dict[str, Any]:
    path = TREES_DIR / f"{intent_id}.yaml"
    return _load_yaml(path)


# ---------------------------------------------------------------------------
# Precomputed binding — per intent we pull the relevant closures from cache
# ---------------------------------------------------------------------------

def bind_precomputed(intent_id: str, slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    bound: Dict[str, Any] = {"precomputed": {}}

    # DB-backed binds (bind_registry / bind_iXX.py) — Wave-2 data layer. Every
    # binder returns {bound_ok, ctx, source_urls, notes}. We stash the payload
    # in bound["db_bind"] so render_skeleton can merge ctx into the template.
    try:
        from .bind_registry import bind as _db_bind
        bound["db_bind"] = _db_bind(intent_id, slots, cache)
    except Exception as e:  # pragma: no cover — defensive
        bound["db_bind"] = {
            "bound_ok": False, "ctx": {}, "source_urls": [],
            "notes": [f"bind_registry import/exec error: {type(e).__name__}: {e}"],
        }

    if intent_id == "i02_program_deadline_documents":
        pid = slots.get("program_id")
        if pid:
            bound["precomputed"]["compat_partners"] = cache.program_compat_closure.get(pid, [])
            bound["precomputed"]["incompat_partners"] = cache.program_incompat_closure.get(pid, [])
            bound["precomputed"]["prereq_certs"] = cache.program_prereq_closure.get(pid, [])
    elif intent_id == "i04_tax_measure_sunset":
        mid = slots.get("measure_id")
        if mid:
            bound["precomputed"]["validity"] = cache.tax_measure_validity.get(mid)
    elif intent_id == "i05_certification_howto":
        cid = slots.get("certification_id")
        if cid:
            bound["precomputed"]["unlocks_programs"] = cache.certification_unlocks.get(cid, [])
    elif intent_id == "i06_compat_incompat_stacking":
        pids = slots.get("program_ids") or []
        pair_verdicts: List[Dict[str, Any]] = []
        for i, a in enumerate(pids):
            for b in pids[i + 1:]:
                verdict = _pair_verdict(a, b, cache)
                pair_verdicts.append({"a": a, "b": b, **verdict})
        bound["precomputed"]["pair_verdicts"] = pair_verdicts
        # also pull full closures per program
        bound["precomputed"]["closures"] = {
            pid: {
                "compat": cache.program_compat_closure.get(pid, []),
                "incompat": cache.program_incompat_closure.get(pid, []),
                "prereq": cache.program_prereq_closure.get(pid, []),
            } for pid in pids
        }
    elif intent_id == "i09_succession_closure":
        # Pull any program that mentions succession/廃業 keywords from the graph
        succession_keys = ["事業承継", "引継ぎ", "承継", "廃業"]
        succession_programs = sorted({
            pid for pid in (list(cache.program_compat_closure.keys())
                            + list(cache.program_incompat_closure.keys()))
            if any(k in pid for k in succession_keys)
        })
        bound["precomputed"]["succession_programs"] = succession_programs
        bound["precomputed"]["tax_measures"] = [
            v for v in cache.tax_measure_validity.values()
            if "事業承継" in (v.get("name") or "") or "事業再編" in (v.get("name") or "")
        ]
    elif intent_id == "i10_wage_dx_gx_themed":
        theme = slots.get("theme")
        theme_kw_map = {
            "賃上げ": ["賃上げ促進税制", "所得拡大促進税制", "キャリアアップ助成金", "業務改善助成金"],
            "DX": ["IT導入補助金", "ものづくり", "DX投資促進税制"],
            "GX_脱炭素": ["省エネ補助金", "カーボン"],
            "省エネ": ["省エネ補助金"],
            "研究開発": ["試験研究費", "Go-Tech"],
        }
        keys = theme_kw_map.get(theme or "", [])
        matches = sorted({
            pid for pid in (list(cache.program_compat_closure.keys())
                            + list(cache.program_incompat_closure.keys()))
            if any(k in pid for k in keys)
        })
        tax_matches = [
            v for v in cache.tax_measure_validity.values()
            if any(k in (v.get("name") or "") for k in keys)
        ]
        bound["precomputed"]["themed_programs"] = matches
        bound["precomputed"]["themed_tax_measures"] = tax_matches

    return bound


def _pair_verdict(a: str, b: str, cache: PrecomputedCache) -> Dict[str, Any]:
    if b in cache.program_incompat_closure.get(a, []):
        return {"verdict": "violation", "reason": "incompatible (transitive or direct)"}
    if b in cache.program_compat_closure.get(a, []):
        return {"verdict": "combine_ok", "reason": "explicit combine_ok in exclusion_rules"}
    if b in cache.program_prereq_closure.get(a, []):
        return {"verdict": "prerequisite", "reason": "b is prerequisite of a"}
    return {"verdict": "unknown", "reason": "pair not in 03_exclusion_rules"}


# ---------------------------------------------------------------------------
# Skeleton rendering — fills {var} placeholders with precomputed + slot values.
# Unknown keys are left as "<<<missing:key>>>" so the LLM can recognize the gap.
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z_0-9]*)\}")


def render_skeleton(tree: Dict[str, Any], slots: Dict[str, Any], bound: Dict[str, Any],
                    intent_id: Optional[str] = None) -> str:
    skeleton = tree.get("answer_skeleton") or ""
    # Flatten slots + precomputed into one dict for format()
    ctx: Dict[str, Any] = {}
    ctx.update({k: _fmt(v) for k, v in slots.items()})
    pre = bound.get("precomputed", {}) or {}
    # DB-backed bind ctx wins over slots. All 10 intents now have a bind_iXX
    # module registered in bind_registry — the legacy per-intent blocks below
    # are fallbacks used only when db_bind.bound_ok is False (e.g. DB missing
    # or slot under-specified).
    db_bind = bound.get("db_bind") or {}
    db_bind_ctx = db_bind.get("ctx") or {}
    db_bind_ok = bool(db_bind.get("bound_ok"))
    if db_bind_ctx:
        ctx.update(db_bind_ctx)

    # ---- Fallback stubs for the 4 new binders (i04/i06/i09/i10) when db_bind
    # bound_ok=False. These mirror Wave-1 precompute-only output so the skeleton
    # never shows <<<missing>>> for bound tokens when DB is unreachable. When
    # db_bind.bound_ok=True (the normal case) we skip them so the richer DB
    # values dominate. Keys already present via db_bind_ctx are NOT overwritten.
    def _fb(key: str, value: str) -> None:
        if key not in db_bind_ctx:
            ctx[key] = value

    if intent_id == "i06_compat_incompat_stacking" and not db_bind_ok:
        pvs = pre.get("pair_verdicts") or []
        closures = pre.get("closures") or {}
        pids = slots.get("program_ids") or []
        _fb("program_list_bullets", "\n".join(
            f"- {p} (incompat={len(closures.get(p, {}).get('incompat', []))}, "
            f"compat={len(closures.get(p, {}).get('compat', []))}, "
            f"prereq={len(closures.get(p, {}).get('prereq', []))})"
            for p in pids
        ) or "(制度未指定)")
        if pvs:
            vset = {p["verdict"] for p in pvs}
            if "violation" in vset:
                _fb("overall_verdict", "violation")
            elif vset == {"unknown"}:
                _fb("overall_verdict", "unknown")
            elif "combine_ok" in vset and "unknown" not in vset:
                _fb("overall_verdict", "combine_ok")
            else:
                _fb("overall_verdict", "mixed")
        else:
            _fb("overall_verdict", "unknown")
        mtx = ["| A | B | verdict | reason |", "|---|---|---|---|"]
        violations = []
        for p in pvs:
            mtx.append(f"| {p['a']} | {p['b']} | {p['verdict']} | {p.get('reason','')} |")
            if p["verdict"] == "violation":
                violations.append(f"- {p['a']} × {p['b']}: {p.get('reason','')}")
        _fb("pair_matrix_table", "\n".join(mtx))
        _fb("violation_detail_bullets", "\n".join(violations) or "(違反ペアなし)")
        _fb("suggested_stack_patterns",
            "- 国 + 県 + 税制 の3層は同一経費でない限り典型的 stack\n"
            "- IT導入補助金 + 持続化補助金 は 同一経費重複不可")
    elif intent_id == "i04_tax_measure_sunset" and not db_bind_ok:
        v = pre.get("validity") or {}
        if v:
            _fb("measure_name", v.get("name", "(未解決)"))
            _fb("tax_category", v.get("tax_category", ""))
            _fb("root_law", v.get("root_law", ""))
            _fb("period_from", v.get("application_period_from", ""))
            _fb("period_to", v.get("application_period_to", ""))
            status = v.get("status", "unknown")
            _fb("status", status)
            _fb("period_to_label", {
                "active": "現在適用中", "expired": "期限切れ",
                "not_yet_active": "未開始", "unknown": "期間データ欠落",
            }.get(status, status))
            _fb("days_remaining", str(v.get("days_remaining", "-")))
            _fb("abolition_date", v.get("abolition_note") or "(廃止予定なし/未公表)")
            _fb("successor_measure", "(後継情報 precompute 外)")
            _fb("transition_rule", "(経過措置 precompute 外)")
            _fb("latest_fy", "8")
            _fb("latest_revision_note", "(税制改正大綱の改正履歴は未収録 — am_amendment_snapshot 拡張で順次対応)")
            _fb("extension_signal", "(2026-04-23 時点で延長公表なし)")
            warnings = []
            if status == "active" and isinstance(v.get("days_remaining"), int) and v["days_remaining"] < 365:
                warnings.append(f"🔥 期限まで残 {v['days_remaining']} 日")
            if v.get("abolition_note"):
                warnings.append(f"⚠ 廃止メモ: {v['abolition_note']}")
            if status == "expired":
                warnings.append("🛑 既に期限切れ — 後継制度または延長の確認必要")
            _fb("proactive_warnings", "\n".join(f"- {w}" for w in warnings) or "- 特記事項なし")
            _fb("citation_urls", f"- {v.get('official_url') or '(URL不明)'}")
    elif intent_id == "i09_succession_closure" and not db_bind_ok:
        progs = pre.get("succession_programs") or []
        taxes = pre.get("tax_measures") or []
        _fb("subsidy_bullets", "\n".join(f"- {p}" for p in progs) or "- (該当補助金なし)")
        _fb("tax_measure_bullets", "\n".join(
            f"- {t.get('name','?')} (期限 {t.get('application_period_to','?')})"
            for t in taxes
        ) or "- (該当税制なし)")
        _fb("loan_bullets", "- (08_loan_programs 未bind fallback)")
        _fb("prerequisite_certs", "- 経営承継円滑化法 認定")
        _fb("stack_pattern_example",
            "- 事業承継・引継ぎ補助金 + 事業承継税制 + 信用保証別枠")
        _fb("timing_warnings", "- 事業承継税制は認定申請期限あり")
        _fb("advisor_recommendations", "- 税理士 + (M&A時) 弁護士 + 金融機関")
        _fb("expiring_measures", "- 事業承継税制 特例措置 (令和9年度末まで)")
        _fb("budget_range_label", _fmt(slots.get("budget_range_yen")))
    elif intent_id == "i10_wage_dx_gx_themed" and not db_bind_ok:
        progs = pre.get("themed_programs") or []
        taxes = pre.get("themed_tax_measures") or []
        _fb("subsidy_bullets", "\n".join(f"- {p}" for p in progs[:8]) or "- (テーマ該当なし)")
        _fb("tax_bullets", "\n".join(
            f"- {t.get('name','?')} (期限 {t.get('application_period_to','?')})"
            for t in taxes
        ) or "- (該当税制なし)")
        _fb("loan_bullets", "- (融資データ 未bind fallback)")
        _fb("compat_summary",
            "- 賃上げ促進税制 × キャリアアップ助成金: 別経費で両取り可")
        _fb("stack_strategy_bullets", "- 国補助金 + 税制優遇 + 県制度融資 の3層")
        _fb("prerequisite_certs", "- 経営革新計画 / 経営力向上計画")
        _fb("scoring_boost_rules", "- 賃上げ加点 (ものづくり補助金/事業再構築補助金)")
        _fb("expiring_measures", "\n".join(
            f"- {t.get('name')} 期限 {t.get('application_period_to')}" for t in taxes[:5]
        ) or "- (該当なし)")
        _fb("target_size", slots.get("target_size") or "(未指定)")
        _fb("top_n", str(min(len(progs), 8)))
    # NOTE: i01 / i02 / i03 / i05 / i07 / i08 are fully db_bind-driven — no
    # fallback needed (their binders are Wave-2 completed).

    # Generic slots/precompute — fill remaining placeholders that weren't overridden
    for k, v in slots.items():
        ctx.setdefault(k, _fmt(v))
    for k, v in pre.items():
        ctx.setdefault(k, _fmt(v))

    if "citation_urls" not in ctx:
        ctx["citation_urls"] = "(1次資料: canonical URL を bind — embedding agent担当)"
    if "national_bullets" not in ctx and intent_id == "i01_filter_programs_by_profile":
        ctx["national_bullets"] = "<<<precompute gap: applicable_programs not yet ingested>>>"

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        return f"<<<missing:{key}>>>"

    return _PLACEHOLDER_RE.sub(sub, skeleton)


def _fmt(v: Any) -> str:
    if v is None:
        return "(未指定)"
    if isinstance(v, list):
        if not v:
            return "(該当なし)"
        lines = []
        for item in v[:20]:
            if isinstance(item, dict):
                # pick a small tidy rendering
                parts = [f"{k}={item[k]}" for k in list(item.keys())[:4]]
                lines.append("- " + " / ".join(parts))
            else:
                lines.append(f"- {item}")
        if len(v) > 20:
            lines.append(f"... (他 {len(v) - 20} 件)")
        return "\n".join(lines)
    if isinstance(v, dict):
        return " / ".join(f"{k}={v[k]}" for k in list(v.keys())[:6])
    return str(v)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    query: str
    intent_id: str
    confidence: float
    intent_scores: List[Tuple[str, int]]
    slots: Dict[str, Any]
    bound: Dict[str, Any]
    answer_skeleton: str


def match(query: str, cache: Optional[PrecomputedCache] = None) -> MatchResult:
    cache = cache or load_cache()
    intent_id, confidence, scores = classify_intent(query)
    slots = extract_slots(intent_id, query, cache)
    tree = load_tree(intent_id)
    bound = bind_precomputed(intent_id, slots, cache)
    skeleton = render_skeleton(tree, slots, bound, intent_id=intent_id)
    return MatchResult(
        query=query,
        intent_id=intent_id,
        confidence=confidence,
        intent_scores=scores,
        slots=slots,
        bound=bound,
        answer_skeleton=skeleton,
    )


# ---------------------------------------------------------------------------
# CLI (for sanity checks)
# ---------------------------------------------------------------------------

def main() -> None:
    import sys
    q = " ".join(sys.argv[1:]) or "東京都 製造業 従業員30人で使える補助金は?"
    r = match(q)
    print(f"INTENT: {r.intent_id} (conf {r.confidence})")
    print("SLOTS:", json.dumps(r.slots, ensure_ascii=False, indent=2))
    print("SKELETON:")
    print(r.answer_skeleton)


if __name__ == "__main__":
    main()
