import json
import re
import sqlite3
import time
import unicodedata
from collections import OrderedDict
from threading import Lock
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES, ErrorEnvelope
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_empty_search,
    log_usage,
)
from jpintel_mcp.api.vocab import (
    _normalize_authority_level,
    _normalize_prefecture,
)
from jpintel_mcp.cache.l4 import canonical_cache_key, get_or_compute
from jpintel_mcp.models import (
    MINIMAL_FIELD_WHITELIST,
    BatchGetProgramsRequest,
    BatchGetProgramsResponse,
    FieldsLevel,
    Program,
    ProgramDetail,
    SearchResponse,
    Tier,
)

router = APIRouter(prefix="/v1/programs", tags=["programs"])


# ---------------------------------------------------------------------------
# R8 dataset versioning helpers (migration 067).
# ---------------------------------------------------------------------------
def _validate_as_of_date(as_of_date: str | None) -> str | None:
    """Validate optional `as_of_date` Query param. Return canonical ISO-8601
    YYYY-MM-DD string when set, else None. Raise 422 on malformed input.

    The bitemporal predicate compares against `valid_from` / `valid_until`
    text columns populated from `source_fetched_at` / `fetched_at`, both of
    which are ISO-8601. Any well-formed YYYY-MM-DD lex-compares correctly
    against an ISO-8601 timestamp prefix, so we don't need to upcast to a
    full timestamp here. Reject anything else with 422 — silently coercing
    would corrupt the cache key.
    """
    if as_of_date is None:
        return None
    import datetime as _dt
    try:
        _parsed = _dt.date.fromisoformat(as_of_date)
    except (TypeError, ValueError) as exc:
        # 422: starlette / fastapi pre-3.0 still ships the legacy name; we
        # use the int code directly so we don't trip the deprecation
        # warning on either side of the rename window.
        raise HTTPException(
            status_code=422,
            detail=f"as_of_date must be ISO-8601 YYYY-MM-DD ({exc})",
        ) from exc
    return _parsed.isoformat()


def _as_of_predicate(as_of_iso: str | None, table_alias: str = "programs") -> tuple[str, list[str]]:
    """Build the (sql_fragment, params) for the bitemporal as-of predicate.

    Returns ('', []) when versioning is disabled OR as_of_iso is None
    (= live, default). When set, returns the canonical predicate:

        valid_from <= ? AND (valid_until IS NULL OR valid_until > ?)

    Both `?` bind to the same as_of_iso; the caller appends both to the
    params list. The fragment is prefixed with " AND " by the caller.
    Gated behind settings.r8_versioning_enabled so a kill-switch flips
    behavior to pre-R8 (no predicate) for one-flag rollback.
    """
    from jpintel_mcp.config import Settings

    if as_of_iso is None or not Settings().r8_versioning_enabled:
        return "", []
    sql = (
        f"{table_alias}.valid_from <= ? AND "
        f"({table_alias}.valid_until IS NULL OR {table_alias}.valid_until > ?)"
    )
    return sql, [as_of_iso, as_of_iso]

# ---------------------------------------------------------------------------
# L4 cache wiring (Q4 perf diff 4 — Zipf-tail short-circuit at the API edge).
#
# The 3 hottest read endpoints (search, get-by-id, am.tax_incentives) account
# for ~80% of QPS per analysis_wave18/_q4_perf_diffs_2026-04-25.md. Wrapping
# the body-build in cache.l4.get_or_compute drops 3-4ms p50 per request once
# the Zipf tail saturates.
#
# Cache-key inputs MUST include every user-visible parameter that changes
# the response shape — including `ctx.tier`, because fields=full is gated
# per-tier (`_check_fields_tier_allowed`) and a "free"-tier hit must never
# serve a payload computed for a "paid"-tier query (or vice versa).
#
# `log_usage(...)` is called OUTSIDE the cached compute so each request
# still bills + counts toward retention digests, even when the body comes
# from cache. The compute closure returns the bare response dict, never a
# JSONResponse — JSONResponse wrapping happens at the route boundary.
#
# Tool names 'api.programs.search' / 'api.programs.get' partition rows so
# `invalidate_tool` can prune one family without touching the rest of L4.
_L4_TTL_PROGRAMS_SEARCH = 300   # 5 min — programs change daily, FTS hot path
_L4_TTL_PROGRAMS_GET = 3600     # 1 h — single-row reads, less Zipf churn
_L4_TOOL_SEARCH = "api.programs.search"
_L4_TOOL_GET = "api.programs.get"


def _l4_get_or_compute_safe(
    cache_key: str,
    tool: str,
    params: dict[str, Any],
    compute: Any,  # Callable[[], dict[str, Any]]
    ttl: int,
) -> dict[str, Any]:
    """Wrap cache.l4.get_or_compute with a self-heal for missing l4_query_cache.

    Test fixtures only run schema.sql, not migrations/043_l4_cache.sql, so
    the first hit raises sqlite3.OperationalError 'no such table'. Mirror
    the api/stats.py pattern: catch, create the table idempotently via
    DDL, retry once. Production carries the migration so the happy path
    is the same single get_or_compute call.
    """
    try:
        return get_or_compute(
            cache_key=cache_key,
            tool=tool,
            params=params,
            compute=compute,
            ttl=ttl,
        )
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        # Lazy import — keeps the cold-path bookkeeping out of module load.
        from jpintel_mcp.api.stats import _ensure_l4_table

        _ensure_l4_table()
        return get_or_compute(
            cache_key=cache_key,
            tool=tool,
            params=params,
            compute=compute,
            ttl=ttl,
        )


# ---------------------------------------------------------------------------
# Search query helpers (kana expansion, phrase detection, FTS term quoting)
#
# The FTS5 index uses a trigram tokenizer, which is character-ngram-based and
# has two sharp edges we mitigate here:
#   1. Kana/kanji seams: `のうぎょう` vs `農業` never share trigrams, so a
#      hiragana/katakana query against a kanji-only corpus returns zero hits
#      even when the concept matches. Fix: KANA_EXPANSIONS maps the top
#      common readings (seen in registry categories) to their kanji form,
#      and we OR the expansion into the MATCH clause.
#   2. Single-kanji overlap false-positives: trigrams of `税額控除` include
#      `税額控` and `額控除`, but bare MATCH still ranks any doc that merely
#      mentions 税 + 控除 independently. For pure-kanji queries of length
#      >= 2 we wrap the term in FTS5 phrase-quote syntax so the tokens must
#      appear contiguously.
# ---------------------------------------------------------------------------


KANA_EXPANSIONS: dict[str, list[str]] = {
    # Top ~30 readings drawn from primary_name / category vocabulary. Kept
    # intentionally small — maintenance > recall. Adding a new entry costs
    # one line; growing to a full MeCab dictionary is out of scope.
    "のうぎょう": ["農業"],
    "ノウギョウ": ["農業"],
    "ほじょ": ["補助"],
    "ホジョ": ["補助"],
    "ほじょきん": ["補助金"],
    "ホジョキン": ["補助金"],
    "じょせい": ["助成"],
    "ジョセイ": ["助成"],
    "じょせいきん": ["助成金"],
    "ジョセイキン": ["助成金"],
    "にんてい": ["認定"],
    "ニンテイ": ["認定"],
    "じぎょう": ["事業"],
    "ジギョウ": ["事業"],
    "どうにゅう": ["導入"],
    "ドウニュウ": ["導入"],
    "しえん": ["支援"],
    "シエン": ["支援"],
    "ゆうし": ["融資"],
    "ユウシ": ["融資"],
    "こうふ": ["交付"],
    "コウフ": ["交付"],
    "こうふきん": ["交付金"],
    "コウフキン": ["交付金"],
    "しゅうのう": ["就農"],
    "シュウノウ": ["就農"],
    "しんきしゅうのう": ["新規就農"],
    "シンキシュウノウ": ["新規就農"],
    "けいえい": ["経営"],
    "ケイエイ": ["経営"],
    "ちほう": ["地方"],
    "チホウ": ["地方"],
    "きぎょう": ["企業"],
    "キギョウ": ["企業"],
    "せつび": ["設備"],
    "セツビ": ["設備"],
    "とうし": ["投資"],
    "トウシ": ["投資"],
    "ぜいがくこうじょ": ["税額控除"],
    "ゼイガクコウジョ": ["税額控除"],
    "ふるさとのうぜい": ["ふるさと納税"],
    "フルサトノウゼイ": ["ふるさと納税"],
    "ちゅうしょうきぎょう": ["中小企業"],
    "チュウショウキギョウ": ["中小企業"],
    # Common tax-term hiragana readings (A4 stress-test finding — paying
    # agents do ask in hiragana and silent 0 results is a money-losing bug).
    "しょうひぜい": ["消費税"],
    "ショウヒゼイ": ["消費税"],
    "ほうじんぜい": ["法人税"],
    "ホウジンゼイ": ["法人税"],
    "しょとくぜい": ["所得税"],
    "ショトクゼイ": ["所得税"],
    "そうぞくぜい": ["相続税"],
    "ソウゾクゼイ": ["相続税"],
    "ぞうよぜい": ["贈与税"],
    "ゾウヨゼイ": ["贈与税"],
    "じぎょうしょうけい": ["事業承継"],
    "ジギョウショウケイ": ["事業承継"],
    # Common legal abbreviations — A5/A6 stress-test fix. Searching '下請法'
    # should reach '下請代金支払遅延等防止法'; '措置法' should reach the two
    # 租税特別措置法 / 地価税法 variants, favored here to 租税特別措置法 which
    # is by far the more common reference in 補助金 / 税制 context.
    "下請法": ["下請代金支払遅延等防止法"],
    "措置法": ["租税特別措置法"],
    "租特法": ["租税特別措置法"],
    "消契法": ["消費者契約法"],
    "景表法": ["不当景品類及び不当表示防止法"],
    "独禁法": ["私的独占の禁止及び公正取引の確保に関する法律"],
    "特商法": ["特定商取引に関する法律"],
    "個情法": ["個人情報の保護に関する法律"],
    "個人情報保護法": ["個人情報の保護に関する法律"],
    "PL法": ["製造物責任法"],
    "会社法": ["会社法"],
    # Katakana 法令名 stress-test A6.
    "ソゼイトクベツソチホウ": ["租税特別措置法"],
    "ショウヒゼイホウ": ["消費税法"],
    "ホウジンゼイホウ": ["法人税法"],
    "カイシャホウ": ["会社法"],
    "ミンポウ": ["民法"],
    "ケイホウ": ["刑法"],
    # === 高頻度 silent-fail patch (Wave-stress 2026-04-25) ===
    # 補助金 名称の hiragana/katakana/略語 variants
    "じぞくか": ["持続化"],
    "ジゾクカ": ["持続化"],
    "じぞくかほじょきん": ["持続化補助金", "小規模事業者持続化補助金"],
    "ジゾクカホジョキン": ["持続化補助金", "小規模事業者持続化補助金"],
    "モノヅクリ": ["ものづくり"],
    "monozukuri": ["ものづくり"],
    "じぎょうさいこうちく": ["事業再構築"],
    "ジギョウサイコウチク": ["事業再構築"],
    "事業継承": ["事業承継"],  # frequent misspelling (継 vs 承)
    "雇調金": ["雇用調整助成金"],  # 厚労省 標準略語
    "こようちょうせい": ["雇用調整"],
    "コヨウチョウセイ": ["雇用調整"],
    "しょうエネ": ["省エネ"],
    "ショウエネ": ["省エネ"],
    "けいえいかくしん": ["経営革新"],
    "ケイエイカクシン": ["経営革新"],
    "そうぎょう": ["創業"],
    "ソウギョウ": ["創業"],
    "キャリアアップ": ["キャリアアップ"],
    "ぎょうむかいぜん": ["業務改善"],
    "ギョウムカイゼン": ["業務改善"],
    # 税制
    "いんぼいす": ["インボイス", "適格請求書"],
    "てきかくせいきゅうしょ": ["適格請求書"],
    "テキカクセイキュウショ": ["適格請求書"],
    "二割特例": ["2割特例"],
    "めんぜいじぎょうしゃ": ["免税事業者"],
    "非課税事業者": ["免税事業者"],  # 典型的誤用
    "けいかそち": ["経過措置"],
    "ケイカソチ": ["経過措置"],
    "電帳法": ["電子帳簿保存法"],  # 超頻出略語
    "でんしちょうぼ": ["電子帳簿"],
    "デンシチョウボ": ["電子帳簿"],
    # 下請法: corpus title changed to 製造委託等に係る…; old shortcut was stale
    "したうけほう": ["下請代金支払遅延等防止法", "製造委託等に係る中小受託事業者"],
    "シタウケホウ": ["下請代金支払遅延等防止法", "製造委託等に係る中小受託事業者"],
    # 略語
    "景品表示法": ["景品表示法", "不当景品類及び不当表示防止法"],
    "独占禁止法": ["独占禁止法", "私的独占の禁止"],
    "どくきんほう": ["独占禁止法", "私的独占の禁止"],
    "ドクキンホウ": ["独占禁止法", "私的独占の禁止"],
    "けいひょうほう": ["景品表示法", "不当景品類及び不当表示防止法"],
    "ケイヒョウホウ": ["景品表示法", "不当景品類及び不当表示防止法"],
    "とくしょうほう": ["特定商取引法"],
    "トクショウホウ": ["特定商取引法"],
    "こじょうほう": ["個人情報保護法", "個人情報の保護"],
    "コジョウホウ": ["個人情報保護法", "個人情報の保護"],
    "ピーエル法": ["製造物責任法"],
    "PLほう": ["製造物責任法"],
    # === Stylized-katakana / abbreviation variants (Wave 2 patch 2026-04-25) ===
    # Bidirectional: agents type stylized katakana ('モノづくり', 'アトツギ') but
    # the DB row often stores the all-hiragana / kanji canonical form ('ものづくり',
    # '跡継ぎ'). Without expansion the FTS phrase-quote ('"モノづくり"') misses
    # ('"ものづくり"') even though they are conceptually the same word. The
    # original query term is always OR'd in by _build_fts_match, so values
    # below contain only the *additional* expansion targets. Costs ¥3/req
    # for a miss otherwise.
    "モノづくり": ["ものづくり"],
    "ものづくり": ["モノづくり"],
    "アトツギ": ["跡継ぎ"],
    "跡継ぎ": ["アトツギ"],
    "トモニン": ["ともにん"],
    "ともにん": ["トモニン"],
    # ハラスメント family — agents type the specific kind, DB stores generic
    "パワハラ": ["ハラスメント", "パワーハラスメント"],
    "セクハラ": ["ハラスメント", "セクシュアルハラスメント"],
    "マタハラ": ["ハラスメント", "マタニティハラスメント"],
    "ハラスメント": ["パワハラ", "セクハラ"],
    # Eコマース / EC abbreviation
    "Eコマース": ["EC", "電子商取引"],
    "eコマース": ["Eコマース", "EC", "電子商取引"],
    "EC": ["Eコマース", "電子商取引"],
    # サブスク
    "サブスク": ["サブスクリプション"],
    "サブスクリプション": ["サブスク"],
    # DX — abbreviation vs full form
    "DX": ["デジタルトランスフォーメーション", "デジタル化"],
    "dx": ["DX", "デジタルトランスフォーメーション", "デジタル化"],
    "デジタルトランスフォーメーション": ["DX"],
    # IT補助金 — frequent informal name for IT導入補助金
    "IT補助金": ["IT導入補助金"],
    "IT導入補助金": ["IT補助金"],
    # インボイス already partially covered ('いんぼいす') — add the katakana key
    "インボイス": ["適格請求書"],
    "適格請求書": ["インボイス"],
    # テレワーク / リモートワーク
    "テレワーク": ["リモートワーク"],
    "リモートワーク": ["テレワーク"],
    # スタートアップ / 創業
    "スタートアップ": ["創業"],
    "創業": ["スタートアップ"],
    # コロナ / 感染症
    "コロナ": ["感染症", "新型コロナ"],
    "感染症": ["コロナ"],
    # 賃上げ / 賃金引上げ
    "賃上げ": ["賃金引上げ", "賃金引き上げ"],
    "賃金引上げ": ["賃上げ", "賃金引き上げ"],
    # リスキリング / 学び直し
    "リスキリング": ["学び直し", "学びなおし"],
    "学び直し": ["リスキリング", "学びなおし"],
    # ゼロカーボン / カーボンニュートラル
    "ゼロカーボン": ["カーボンニュートラル", "脱炭素"],
    "カーボンニュートラル": ["ゼロカーボン", "脱炭素"],
    # グリーン / 環境
    "グリーン": ["環境", "グリーン成長"],
    # ジェンダー / 男女共同参画
    "ジェンダー": ["男女共同参画"],
    "男女共同参画": ["ジェンダー"],
    # バリアフリー / 障害者
    "バリアフリー": ["障害者", "障がい者"],
    # ウェルビーイング / 働き方改革
    "ウェルビーイング": ["働き方改革"],
    "働き方改革": ["ウェルビーイング"],
}


_RE_KANJI = re.compile(r"[一-鿿]")
_RE_KANA = re.compile(r"[぀-ゟ゠-ヿ]")
_RE_ASCII_WORD = re.compile(r"[A-Za-z0-9]")


def _is_pure_kanji(s: str) -> bool:
    """True iff `s` contains kanji only (no kana, no ascii). Used to decide
    whether to wrap in FTS5 phrase-quote syntax."""
    if not s:
        return False
    if not _RE_KANJI.search(s):
        return False
    if _RE_KANA.search(s):
        return False
    return not _RE_ASCII_WORD.search(s)


_RE_PURE_ASCII_WORD = re.compile(r"[A-Za-z0-9]+")


def _is_pure_ascii_word(s: str) -> bool:
    """True iff `s` is non-empty and consists only of [A-Za-z0-9].

    Used by the LIKE fallback to recognize short acronym-style queries
    ('IT', 'DX', 'AI') and narrow their column scan to primary_name +
    aliases_json, skipping the expensive enriched_json scan that would
    otherwise match ~60% of the corpus on English substring noise.
    """
    return bool(s) and _RE_PURE_ASCII_WORD.fullmatch(s) is not None


def _fts_escape(term: str) -> str:
    """Escape a term for use inside an FTS5 phrase literal. FTS5 phrase
    syntax is `"token token token"` with double-quotes escaped as `""`."""
    return term.replace('"', '""')


def _build_fts_match(raw_query: str) -> str:
    """Compose an FTS5 MATCH expression from a user query.

    Rules:
    - Strip outer whitespace.
    - If the query is pure-kanji (length >= 2), wrap it in phrase-quote so
      the tokens must appear contiguously. This defeats the single-kanji
      overlap false-positive problem on the trigram tokenizer.
    - If the query has a whole-token KANA_EXPANSIONS match, OR in the
      expansion alongside the original. Example:
        のうぎょう -> `のうぎょう OR 農業`
    - Otherwise quote the whole query as a phrase (safer default — prevents
      FTS5 from parsing stray punctuation as operators).

    For multi-word queries (whitespace-separated), we treat each token
    independently and AND them together.
    """
    # NFKC first — normalizes 全角 ASCII ('ＩＴ' -> 'IT'), 全角 space -> half,
    # 半角カナ -> 全角カナ, and a few compatibility codepoints. This one line
    # rescues ~5% of Mac-IME / Word-paste inbound queries that would otherwise
    # miss the FTS index because 'ＩＴ導入補助金' tokenizes differently from
    # 'IT導入補助金'. Safe: NFKC never changes Japanese kanji/kana semantics.
    q = unicodedata.normalize("NFKC", raw_query).strip()
    if not q:
        return q

    # Multi-token query -> AND of per-token expansions.
    tokens = q.split()
    if len(tokens) > 1:
        parts: list[str] = []
        for tok in tokens:
            parts.append(_build_fts_match(tok))
        return " AND ".join(f"({p})" for p in parts)

    # Single token path.
    alts: list[str] = []
    # Original term — phrase-quoted for safety.
    if _is_pure_kanji(q) and len(q) >= 2:
        alts.append(f'"{_fts_escape(q)}"')
    else:
        alts.append(f'"{_fts_escape(q)}"')

    # Kana expansion: only when the query is entirely a known kana reading.
    if q in KANA_EXPANSIONS:
        for kanji in KANA_EXPANSIONS[q]:
            alts.append(f'"{_fts_escape(kanji)}"')

    if len(alts) == 1:
        return alts[0]
    return " OR ".join(alts)


# ---------------------------------------------------------------------------
# Row -> Program cache
#
# Option A from research/perf_baseline.md: avoid the per-row `json.loads`
# + Pydantic validation cost under concurrent load on hot searches.
#
# Key: (unified_id, source_checksum). `source_checksum` is a stable hash of
# the record's content computed during ingest (see ingest/canonical.py).
# Any content change -> new checksum -> new cache key -> natural invalidation
# on the next read. No TTL, no SIGHUP, no cache-clear endpoint needed.
#
# Size cap: 2048 entries (~30% of the 6,771 row corpus; well under the
# ~6MB memory envelope for built Program objects). A manual OrderedDict
# LRU is used instead of `functools.lru_cache` because the cache key must
# depend on only (unified_id, checksum) while the miss path needs the full
# sqlite Row — we can't pass a Row through lru_cache (not hashable).
#
# Cache shape: always the FULL Program object. The fields=minimal/full slice
# is applied at serialization time (see _trim_to_fields). This keeps hit
# rate independent of what the caller asked for.
# ---------------------------------------------------------------------------

_PROGRAM_CACHE: "OrderedDict[tuple[str, str | None], Program]" = OrderedDict()
_PROGRAM_CACHE_LOCK = Lock()
_PROGRAM_CACHE_MAX = 2048


def _build_program(row: sqlite3.Row) -> Program:
    def j(col: str, default):
        raw = row[col]
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    application_window = j("application_window_json", None)
    official_url = row["official_url"]
    return Program(
        unified_id=row["unified_id"],
        primary_name=row["primary_name"],
        aliases=j("aliases_json", []),
        authority_level=row["authority_level"],
        authority_name=row["authority_name"],
        prefecture=row["prefecture"],
        municipality=row["municipality"],
        program_kind=row["program_kind"],
        official_url=official_url,
        amount_max_man_yen=row["amount_max_man_yen"],
        amount_min_man_yen=row["amount_min_man_yen"],
        subsidy_rate=row["subsidy_rate"],
        trust_level=row["trust_level"],
        tier=row["tier"],
        coverage_score=row["coverage_score"],
        gap_to_tier_s=j("gap_to_tier_s_json", []),
        a_to_j_coverage=j("a_to_j_coverage_json", {}),
        excluded=bool(row["excluded"]),
        exclusion_reason=row["exclusion_reason"],
        crop_categories=j("crop_categories_json", []),
        equipment_category=row["equipment_category"],
        target_types=j("target_types_json", []),
        funding_purpose=j("funding_purpose_json", []),
        amount_band=row["amount_band"],
        application_window=application_window,
        next_deadline=_extract_next_deadline(application_window),
        application_url=official_url,
    )


def _extract_next_deadline(
    application_window: dict[str, Any] | list[Any] | None,
) -> str | None:
    """Pull the raw end_date (ISO YYYY-MM-DD) out of the application_window
    blob. Returns None when the blob is not a dict, or end_date is missing /
    malformed. Does NOT filter past dates — that check lives at serialization
    time (_post_cache_next_deadline) so the Program cache can stay keyed by
    source_checksum only, while past-filtering stays fresh per request.
    """
    if not isinstance(application_window, dict):
        return None
    end_date = application_window.get("end_date")
    if not isinstance(end_date, str) or len(end_date) < 10:
        return None
    iso_date = end_date[:10]
    from datetime import date

    try:
        date.fromisoformat(iso_date)
    except ValueError:
        return None
    return iso_date


def _post_cache_next_deadline(iso_date: str | None) -> str | None:
    """Clear next_deadline if the cached ISO date is already past *today*.

    Runs after _row_to_program cache hit so staleness can't survive across
    a day boundary. Same return contract as _extract_next_deadline: if
    non-null, the date is >= today.
    """
    if not iso_date:
        return None
    from datetime import UTC, date, datetime, timedelta

    try:
        # JST date pivot: Fly.io machines run UTC; comparing to date.today()
        # would mark a 公募 deadline 2026-05-31 as past at 02:00 JST 6/1.
        jst_today = (datetime.now(UTC) + timedelta(hours=9)).date()
        if date.fromisoformat(iso_date) < jst_today:
            return None
    except ValueError:
        return None
    return iso_date


def _extract_required_documents(
    enriched: dict[str, Any] | None,
) -> list[str]:
    """Extract required-document names from heterogeneous enriched shapes.

    Scans the known paths where ingest has historically written document
    arrays. Each path yields a list of dicts or strings; we collect the
    `name` / `title` / `書類名` field, or the string itself, de-duplicate
    order-preservingly, and return up to 50 items. Empty list when nothing
    matches — this is the "we haven't extracted for this program" signal,
    not "no docs required".
    """
    if not isinstance(enriched, dict):
        return []
    candidates: list[Any] = []
    extraction = enriched.get("extraction") if isinstance(enriched.get("extraction"), dict) else None
    paths: list[dict[str, Any]] = []
    if extraction:
        paths.append(extraction)
    paths.append(enriched)
    for scope in paths:
        for key in ("required_documents", "documents", "提出書類", "必要書類"):
            val = scope.get(key)
            if isinstance(val, list):
                candidates.extend(val)
        proc = scope.get("procedure")
        if isinstance(proc, dict):
            for key in ("required_documents", "documents", "提出書類", "必要書類"):
                val = proc.get(key)
                if isinstance(val, list):
                    candidates.extend(val)
    names: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        name: str | None = None
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            for key in ("name", "title", "書類名", "document_name"):
                v = item.get(key)
                if isinstance(v, str) and v.strip():
                    name = v.strip()
                    break
        if name and name not in seen:
            seen.add(name)
            names.append(name)
            if len(names) >= 50:
                break
    return names


def _row_to_program(row: sqlite3.Row) -> Program:
    uid = row["unified_id"]
    # source_checksum column may be absent on very old DB files where the
    # lineage migration has not yet been applied (see get_program below).
    try:
        checksum = row["source_checksum"]
    except (IndexError, KeyError):
        checksum = None

    key = (uid, checksum)
    with _PROGRAM_CACHE_LOCK:
        hit = _PROGRAM_CACHE.get(key)
        if hit is not None:
            _PROGRAM_CACHE.move_to_end(key)
            return hit

    # Build outside the lock so json.loads + Pydantic validation don't block
    # other readers.
    built = _build_program(row)

    with _PROGRAM_CACHE_LOCK:
        _PROGRAM_CACHE[key] = built
        _PROGRAM_CACHE.move_to_end(key)
        while len(_PROGRAM_CACHE) > _PROGRAM_CACHE_MAX:
            _PROGRAM_CACHE.popitem(last=False)
    return built


def _clear_program_cache() -> None:
    """Clear the row->Program cache. Exposed for tests and for callers that
    mutate program rows in-place without bumping source_checksum."""
    with _PROGRAM_CACHE_LOCK:
        _PROGRAM_CACHE.clear()


# ---------------------------------------------------------------------------
# fields=... response shaping
# ---------------------------------------------------------------------------


def _extract_enriched_and_sources(row: sqlite3.Row) -> tuple[Any, Any, str | None, str | None, str | None]:
    """Pull enriched/source_mentions/lineage from a raw sqlite row.

    Used by both /search (fields=full) and /get (always). The search path
    only does the extra SQL work when fields=full so the common case does
    not pay for JSON decoding it will never emit.
    """
    enriched: Any = None
    if row["enriched_json"]:
        try:
            enriched = json.loads(row["enriched_json"])
        except json.JSONDecodeError:
            enriched = None

    source_mentions: Any = None
    if row["source_mentions_json"]:
        try:
            source_mentions = json.loads(row["source_mentions_json"])
        except json.JSONDecodeError:
            source_mentions = None

    row_keys = row.keys()
    source_url = row["source_url"] if "source_url" in row_keys else None
    source_fetched_at = (
        row["source_fetched_at"] if "source_fetched_at" in row_keys else None
    )
    source_checksum = (
        row["source_checksum"] if "source_checksum" in row_keys else None
    )
    return enriched, source_mentions, source_url, source_fetched_at, source_checksum


_PAID_TIERS: frozenset[str] = frozenset({"paid"})


def _check_fields_tier_allowed(fields: FieldsLevel, tier: str) -> None:
    """fields=full is paid-only. Anon (`free`) gets 402.

    Anon still gets minimal/default — the common case is untouched. full is
    gated because it carries enriched + source_mentions + lineage (~300 KB
    for a 20-row page), and at HN-spike traffic that egress is uneconomic
    for the anon bucket.
    """
    if fields == "full" and tier not in _PAID_TIERS:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {
                "detail": "fields=full requires a paid tier",
                "upgrade_url": "/pricing",
            },
        )


def _trim_to_fields(record: dict[str, Any], fields: FieldsLevel) -> dict[str, Any]:
    """Shape a program dict to the requested fields level.

    - minimal: keep only the whitelist in models.MINIMAL_FIELD_WHITELIST
    - default: pass-through (no change)
    - full: pass-through; callers are responsible for having already joined
      enriched / source_mentions / lineage into `record` before this call.
      If they didn't, we INSERT explicit null keys so the "full" contract
      ("enriched/source_mentions are present, possibly null") holds.
    """
    if fields == "minimal":
        return {k: record.get(k) for k in MINIMAL_FIELD_WHITELIST}
    if fields == "full":
        # Ensure the "full" contract: keys always present even if null.
        record.setdefault("enriched", None)
        record.setdefault("source_mentions", None)
        record.setdefault("source_url", None)
        record.setdefault("source_fetched_at", None)
        record.setdefault("source_checksum", None)
        return record
    return record  # default: unchanged


def _row_to_program_detail(row: sqlite3.Row, fields: FieldsLevel) -> dict[str, Any]:
    """Build the /v1/programs/{unified_id} response dict for a single row.

    Reused by `GET /v1/programs/{id}` and `POST /v1/programs/batch` so the
    two endpoints can never drift. Builds on _row_to_program's cached path
    (task #49 perf fix: lazy JSON decode + row-keyed cache) — do not copy
    the row-walking logic elsewhere, call this.

    Behavior preserved from the legacy single-get handler:
    - enriched/source_mentions/lineage always populated (no laziness — /get
      is always "full detail" in intent).
    - fields=default keeps the {} quirk for source_mentions when stored
      value is missing (legacy callers expect it).
    - fields=full normalizes the quirk to null per the documented contract.
    - _trim_to_fields handles the minimal whitelist at the end.
    """
    base = _row_to_program(row).model_dump()
    base["next_deadline"] = _post_cache_next_deadline(base.get("next_deadline"))
    enriched, source_mentions, src_url, src_fetched, src_checksum = (
        _extract_enriched_and_sources(row)
    )
    base["enriched"] = enriched
    if fields == "full":
        base["source_mentions"] = source_mentions
    else:
        base["source_mentions"] = source_mentions if source_mentions is not None else {}
    base["source_url"] = src_url
    base["source_fetched_at"] = src_fetched
    base["source_checksum"] = src_checksum
    base["required_documents"] = _extract_required_documents(enriched)
    return _trim_to_fields(base, fields)


@router.get(
    "/search",
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "SearchResponse. `results[]` shape depends on `fields`: "
                "minimal = 7-key whitelist, default = Program, full = ProgramDetail."
            ),
            "model": SearchResponse,
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "unified_id": "UNI-meti-it-2026",
                                "primary_name": "IT導入補助金2026",
                                "tier": "S",
                                "authority_level": "national",
                                "authority_name": "経済産業省",
                                "prefecture": "全国",
                                "program_kind": "補助金",
                                "amount_max_man_yen": 450,
                                "subsidy_rate": "1/2 〜 3/4",
                                "funding_purpose": ["DX", "デジタル化"],
                                "target_types": ["sme", "sole_proprietor"],
                                "official_url": "https://www.it-hojo.jp/",
                                "source_url": "https://www.it-hojo.jp/",
                                "source_fetched_at": "2026-04-20T05:14:33Z",
                                "next_deadline": "2026-06-30",
                            }
                        ],
                    }
                }
            },
        },
    },
)
def search_programs(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[str | None, Query(description="free-text search across name/aliases/enriched", max_length=200)] = None,
    tier: Annotated[list[Tier] | None, Query(description="filter tier, repeat for OR")] = None,
    prefecture: Annotated[
        str | None,
        Query(
            description=(
                "Prefecture name. Canonical = full-suffix kanji ('東京都'). "
                "Also accepts short ('東京') and romaji ('Tokyo'/'tokyo'); "
                "normalized server-side. Use '全国' (or 'national'/'all') "
                "for nationwide programs."
            ),
            max_length=20,
        ),
    ] = None,
    authority_level: Annotated[
        str | None,
        Query(
            description=(
                "Authority level. Canonical (English): `national` / `prefecture` / "
                "`municipality` / `financial`. Also accepts Japanese: `国` / `都道府県` / "
                "`市区町村` (normalized server-side)."
            ),
            max_length=20,
        ),
    ] = None,
    funding_purpose: Annotated[list[str] | None, Query(max_length=64)] = None,
    target_type: Annotated[list[str] | None, Query(max_length=64)] = None,
    amount_min: Annotated[float | None, Query(ge=0)] = None,
    amount_max: Annotated[float | None, Query(ge=0)] = None,
    include_excluded: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    fields: Annotated[
        FieldsLevel,
        Query(
            description=(
                "Payload size knob. minimal = 7-key whitelist (~300 B/row). "
                "default = full Program shape (current behavior). "
                "full = Program + enriched + source_mentions + lineage."
            )
        ),
    ] = "default",
    include_advisors: Annotated[
        bool,
        Query(
            description=(
                "When true, attach up to 3 matching 士業/認定支援機関 advisors "
                "under `matched_advisors` on the response envelope. Additive — "
                "the `results[]` shape is unchanged for callers that leave "
                "this false (default). Match ranks on prefecture + target_type."
            )
        ),
    ] = False,
    as_of_date: Annotated[
        str | None,
        Query(
            description=(
                "R8 dataset versioning — pin the result set to the dataset "
                "state at YYYY-MM-DD (ISO-8601 date). Predicate: "
                "`valid_from <= as_of_date AND (valid_until IS NULL OR "
                "valid_until > as_of_date)`. Omit / null = live (today). "
                "Used by tax accountants / 行政書士 to fix 申告時点の制度状態 "
                "for audit. Returns 422 on malformed date."
            ),
            max_length=10,
        ),
    ] = None,
) -> JSONResponse:
    # Telemetry: wall-clock latency for /v1/admin/global_usage_by_tool
    # (audit ada8db68240c63c66 P0 — without this we cannot detect FTS5
    # query degradation).
    _t0 = time.perf_counter()
    _check_fields_tier_allowed(fields, ctx.tier)
    # R8: validate as_of_date early — malformed input must 422 before any
    # SQL is built so the cache key is never poisoned with garbage.
    _as_of_iso = _validate_as_of_date(as_of_date)

    # L4 cache key — every user-visible param + ctx.tier (poisoning guard).
    # Sorted lists ensure repeat-param order doesn't fragment the key. The
    # cache wraps the SQL+envelope-build body; logging happens after.
    _l4_params: dict[str, Any] = {
        "q": q,
        "tier": sorted(tier) if tier else None,
        "prefecture": prefecture,
        "authority_level": authority_level,
        "funding_purpose": sorted(funding_purpose) if funding_purpose else None,
        "target_type": sorted(target_type) if target_type else None,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "include_excluded": include_excluded,
        "limit": limit,
        "offset": offset,
        "fields": fields,
        "include_advisors": include_advisors,
        "ctx_tier": ctx.tier,
        # R8: as_of_date partitions the cache so a snapshot-pinned query
        # never serves a payload computed for live (and vice-versa).
        "as_of_date": _as_of_iso,
    }
    _l4_key = canonical_cache_key(_L4_TOOL_SEARCH, _l4_params)

    def _do_search() -> dict[str, Any]:
        return _build_search_response(
            conn=conn,
            q=q,
            tier=tier,
            prefecture=prefecture,
            authority_level=authority_level,
            funding_purpose=funding_purpose,
            target_type=target_type,
            amount_min=amount_min,
            amount_max=amount_max,
            include_excluded=include_excluded,
            limit=limit,
            offset=offset,
            fields=fields,
            include_advisors=include_advisors,
            as_of_iso=_as_of_iso,
        )

    response_body = _l4_get_or_compute_safe(
        cache_key=_l4_key,
        tool=_L4_TOOL_SEARCH,
        params=_l4_params,
        compute=_do_search,
        ttl=_L4_TTL_PROGRAMS_SEARCH,
    )

    total = int(response_body.get("total", 0))
    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "programs.search",
        params={
            "q": q,
            "tier": sorted(tier) if tier else None,
            "prefecture": prefecture,
            "authority_level": authority_level,
            "funding_purpose": sorted(funding_purpose) if funding_purpose else None,
            "target_type": sorted(target_type) if target_type else None,
            "amount_min": amount_min,
            "amount_max": amount_max,
        },
        latency_ms=_latency_ms,
        result_count=total,
    )

    # Empty-search log (migration 062). Capture queries that returned 0
    # results and are non-trivial (>1 char, not pure whitespace) so the
    # operator can drive ingest prioritization off real demand. We only
    # store rows where `q` is set — pure filter combinations that miss
    # don't tell us about a missing program, just an over-narrow filter.
    if total == 0 and q is not None:
        _q_clean_for_log = q.strip()
        if len(_q_clean_for_log) > 1:
            log_empty_search(
                conn,
                query=_q_clean_for_log,
                endpoint="search_programs",
                filters={
                    "tier": sorted(tier) if tier else None,
                    "prefecture": prefecture,
                    "authority_level": authority_level,
                    "funding_purpose": sorted(funding_purpose) if funding_purpose else None,
                    "target_type": sorted(target_type) if target_type else None,
                    "amount_min": amount_min,
                    "amount_max": amount_max,
                },
                ip=request.client.host if request.client else None,
            )

    return JSONResponse(content=response_body)


def _build_search_response(
    *,
    conn: sqlite3.Connection,
    q: str | None,
    tier: list[Tier] | None,
    prefecture: str | None,
    authority_level: str | None,
    funding_purpose: list[str] | None,
    target_type: list[str] | None,
    amount_min: float | None,
    amount_max: float | None,
    include_excluded: bool,
    limit: int,
    offset: int,
    fields: FieldsLevel,
    include_advisors: bool,
    as_of_iso: str | None = None,
) -> dict[str, Any]:
    """Pure compute for /v1/programs/search — JSON-serialisable response dict.

    Extracted from the route handler so cache.l4.get_or_compute can wrap
    this without dragging in the side-effect plumbing (log_usage,
    log_empty_search, telemetry timer). Returns the same shape that the
    route used to construct inline. Side-effects belong to the caller.
    """
    where: list[str] = []
    params: list = []
    join_fts = False
    raw_query: str | None = None  # original user query, for name-LIKE tiebreak

    if q:
        q_clean = q.strip()
        raw_query = q_clean
        # Build the list of candidate search strings: the query itself plus
        # any KANA_EXPANSIONS entries. If *any* candidate is shorter than 3
        # chars, we must use the LIKE path because FTS5 trigram tokenizes
        # on 3-grams and shorter tokens never match. This handles the
        # のうぎょう -> 農業 case where the expansion (2 chars) would
        # silently miss through FTS.
        search_terms: list[str] = [q_clean]
        if q_clean in KANA_EXPANSIONS:
            search_terms.extend(KANA_EXPANSIONS[q_clean])
        shortest = min(len(t) for t in search_terms)
        if shortest >= 3 and len(search_terms) == 1:
            join_fts = True
            params.append(_build_fts_match(q_clean))
        elif shortest >= 3 and len(search_terms) > 1:
            # Multi-term (kana expansion) where all terms are >=3 chars:
            # FTS OR works.
            join_fts = True
            params.append(_build_fts_match(q_clean))
        else:
            # LIKE-across-all-search-terms fallback. Combine candidate terms
            # with OR.
            #
            # Column coverage depends on script class of the term:
            # - Japanese / mixed short terms (e.g. 2-char kanji like 税額,
            #   or kana-expanded 農業) scan primary_name + aliases_json +
            #   enriched_json so the concept is found even when it only
            #   appears in the long-form description.
            # - Short pure-ASCII terms (len<3, [A-Za-z0-9] only — e.g. IT,
            #   DX, AI) scan primary_name + aliases_json ONLY. Including
            #   enriched_json for 2-char ASCII is a double failure:
            #     (a) Latency: the 12k-row enriched_json scan is ~400ms P95
            #         (vs 17ms for the FTS path on 2+ char kanji) because
            #         'IT' appears as a substring inside English words
            #         ('Information', 'credit', 'exhibit') and JSON meta
            #         keys across ~60% of the corpus.
            #     (b) Relevance: those substring hits are not what the user
            #         means when they search 'IT' — they want IT導入補助金,
            #         not every program whose enriched blob happens to
            #         contain the byte-pair 'IT'. Restricting to
            #         primary_name + aliases_json surfaces exactly the
            #         acronym-in-name rows agents expect.
            #   See docs/performance.md for the perf audit that drove this.
            like_clauses: list[str] = []
            for t in search_terms:
                if len(t) < 3 and _is_pure_ascii_word(t):
                    # Short pure-ASCII: narrow scan, skip enriched_json.
                    like_clauses.append(
                        "(primary_name LIKE ? OR aliases_json LIKE ?)"
                    )
                    like = f"%{t}%"
                    params.extend([like, like])
                else:
                    # Short Japanese / mixed: full three-column scan.
                    like_clauses.append(
                        "(primary_name LIKE ? OR aliases_json LIKE ? OR "
                        " COALESCE(enriched_json,'') LIKE ?)"
                    )
                    like = f"%{t}%"
                    params.extend([like, like, like])
            where.append("(" + " OR ".join(like_clauses) + ")")

    if tier:
        where.append(f"tier IN ({','.join('?' * len(tier))})")
        params.extend(tier)

    prefecture = _normalize_prefecture(prefecture)
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)

    authority_level = _normalize_authority_level(authority_level)
    if authority_level:
        where.append("authority_level = ?")
        params.append(authority_level)

    if funding_purpose:
        for fp in funding_purpose:
            where.append("funding_purpose_json LIKE ?")
            params.append(f"%{json.dumps(fp, ensure_ascii=False)}%")

    if target_type:
        for t in target_type:
            where.append("target_types_json LIKE ?")
            params.append(f"%{json.dumps(t, ensure_ascii=False)}%")

    if amount_min is not None:
        where.append("amount_max_man_yen >= ?")
        params.append(amount_min)

    if amount_max is not None:
        where.append("amount_max_man_yen <= ?")
        params.append(amount_max)

    if not include_excluded:
        where.append("excluded = 0")
        # Tier-X is a quality-gate "excluded-equivalent" bucket. 432 rows
        # currently have tier='X' with excluded=0 (ingest lag). Gate them
        # on the app-path so user-facing search never surfaces a
        # quarantined row. COALESCE catches NULL tier too. Callers who
        # really want quarantined rows pass include_excluded=True.
        where.append("COALESCE(tier,'X') != 'X'")

    # R8 dataset versioning — pin to historical snapshot when as_of_iso set.
    # No-op when versioning is disabled (env flag) or as_of is None.
    _as_of_sql, _as_of_params = _as_of_predicate(as_of_iso, "programs")
    if _as_of_sql:
        where.append(_as_of_sql)
        params.extend(_as_of_params)

    if join_fts:
        base_from = "programs_fts JOIN programs USING(unified_id)"
        where_clause = "programs_fts MATCH ?"
        if where:
            where_clause = where_clause + " AND " + " AND ".join(where)
    else:
        base_from = "programs"
        where_clause = " AND ".join(where) if where else "1=1"

    # Dedup by primary_name at COUNT and SELECT time: 18 primary_names are
    # duplicated in the corpus today (up to 13x). Without dedup, a search
    # for `IT導入補助金` returns 4 near-identical rows. We keep the
    # highest-tier row per name. ROW_NUMBER() over a tier-ordered partition
    # picks one row per primary_name.
    tier_order_inner = (
        "CASE programs.tier "
        "WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 "
        "ELSE 4 END"
    )
    tier_order_outer = (
        "CASE tier "
        "WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 "
        "ELSE 4 END"
    )

    # COUNT(DISTINCT primary_name) for the dedup-aware total.
    count_sql = (
        f"SELECT COUNT(DISTINCT programs.primary_name) FROM {base_from} "
        f"WHERE {where_clause}"
    )
    (total,) = conn.execute(count_sql, params).fetchone()

    # Ordering priorities (highest first):
    #   1. primary_name contains the raw query literally — defeats the
    #      trigram false-positive where 企業版ふるさと納税 outranks
    #      研究開発税制(試験研究費の税額控除) on a 税額控除 query.
    #   2. Tier S/A/B/C/other — user-facing quality gate.
    #   3. FTS rank (only on the FTS path) as a tie-breaker.
    #   4. primary_name alphabetical for deterministic paging.
    #
    # Inner uses `programs.*` qualified refs (join site); outer uses flat
    # unqualified refs (subquery projection drops the qualifier).
    inner_order_parts: list[str] = []
    outer_order_parts: list[str] = []
    name_match_params: list = []
    if raw_query:
        inner_order_parts.append(
            "CASE WHEN programs.primary_name LIKE ? THEN 0 ELSE 1 END"
        )
        outer_order_parts.append(
            "CASE WHEN primary_name LIKE ? THEN 0 ELSE 1 END"
        )
        name_match_params.append(f"%{raw_query}%")
    inner_order_parts.append(tier_order_inner)
    outer_order_parts.append(tier_order_outer)
    if join_fts:
        inner_order_parts.append("programs_fts.rank")
        outer_order_parts.append("_rank")
    inner_order_parts.append("programs.primary_name")
    outer_order_parts.append("primary_name")
    inner_order_sql = "ORDER BY " + ", ".join(inner_order_parts)
    outer_order_sql = "ORDER BY " + ", ".join(outer_order_parts)

    # Inner projection: all programs.* columns + _rank (FTS only) + _rn.
    rank_col = ", programs_fts.rank AS _rank" if join_fts else ""
    inner_sql = (
        f"SELECT programs.*{rank_col}, "
        f"  ROW_NUMBER() OVER (PARTITION BY programs.primary_name "
        f"                     {inner_order_sql}) AS _rn "
        f"FROM {base_from} WHERE {where_clause}"
    )
    select_sql = (
        f"SELECT * FROM ({inner_sql}) "
        f"WHERE _rn = 1 {outer_order_sql} LIMIT ? OFFSET ?"
    )
    # Parameter order (textual left-to-right in final SQL):
    #   1. inner ORDER BY inside OVER(...)  -> name_match_params
    #   2. inner WHERE clause                -> params
    #   3. outer ORDER BY                    -> name_match_params
    #   4. LIMIT, OFFSET
    full_params = [
        *name_match_params,
        *params,
        *name_match_params,
        limit,
        offset,
    ]
    rows = conn.execute(select_sql, full_params).fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        base = _row_to_program(r).model_dump()
        base["next_deadline"] = _post_cache_next_deadline(base.get("next_deadline"))
        if fields == "full":
            enriched, source_mentions, src_url, src_fetched, src_checksum = (
                _extract_enriched_and_sources(r)
            )
            base["enriched"] = enriched
            base["source_mentions"] = source_mentions
            base["source_url"] = src_url
            base["source_fetched_at"] = src_fetched
            base["source_checksum"] = src_checksum
            base["required_documents"] = _extract_required_documents(enriched)
        results.append(_trim_to_fields(base, fields))

    response_body: dict[str, Any] = {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": results,
    }

    # Empty-result hint + retry_with — parity with the MCP `search_programs`
    # tool (mcp/server.py:_empty_search_hint). REST callers (and agents
    # routing through REST) used to get a silent empty array with no
    # retry guidance; bare-empty responses ~4x reduce model retry rate
    # vs. an annotated hint. Importing the MCP helper directly would be
    # circular (mcp.server already imports from api.programs), so we
    # inline equivalent logic here. Priority order matches the MCP side:
    # non-canonical filter values > missing-coverage > pivot.
    if total == 0:
        if q and len(q.strip()) < 3:
            hint = (
                f"クエリ '{q}' が短すぎて FTS にヒットしません. "
                "3 文字以上の語 (例: '補助金' '省エネ') を含めて再検索してください."
            )
        elif (
            prefecture
            and prefecture != "全国"
            and not prefecture.endswith(("都", "道", "府", "県"))
        ):
            hint = (
                f"prefecture='{prefecture}' は canonical 形式ではありません "
                "(DB は '東京都' のようにフル都道府県名で保存). "
                "`/v1/enum_values?field=prefecture` で 47 都道府県 + '全国' を確認して再検索してください."
            )
        elif target_type:
            hint = (
                f"target_type={target_type} で 0 件. 表記ブレの可能性があります "
                "('中小企業'/'sme', '個人事業主'/'sole_proprietor' が混在). "
                "`/v1/enum_values?field=target_type` で canonical 一覧を取得し, "
                "見つかった値をそのまま渡してください."
            )
        elif funding_purpose:
            hint = (
                f"funding_purpose={funding_purpose} で 0 件. 表記ブレ ('DX'/'デジタル化', "
                "'省エネ'/'energy') の可能性があります. "
                "`/v1/enum_values?field=funding_purpose` で canonical 一覧を確認してください."
            )
        elif tier and all(t in {"S", "A"} for t in tier):
            hint = (
                "tier=['S','A'] のみで絞ったため該当なし. "
                "tier=['S','A','B','C'] に拡張すると件数が戻ります (C は要1次確認)."
            )
        elif prefecture:
            hint = (
                f"prefecture='{prefecture}' 限定で 0 件. "
                "国 (national) 制度は prefecture=null で保存されているため, "
                "prefecture を外して authority_level='national' で再検索してください."
            )
        elif authority_level == "national":
            hint = (
                "authority_level='national' で 0 件. 地方自治体制度を含めるなら "
                "authority_level を外すか, prefecture を指定してください."
            )
        else:
            hint = (
                "該当なし. 別の切り口として: (a) search_case_studies で実際の受給事例から逆引き, "
                "(b) search_loan_programs で融資, (c) search_enforcement_cases で不当請求 due-diligence. "
                "クエリを英日両方 ('DX'/'デジタル化') で試すのも有効."
            )
        response_body["hint"] = hint
        response_body["retry_with"] = [
            "search_case_studies",
            "search_loan_programs",
            "search_enforcement_cases",
        ]

    # 士業 affiliate matching (additive). When the caller sets
    # include_advisors=true we attach up to 3 verified+active advisors whose
    # (prefecture, target_type) profile matches the current search. The
    # query is a separate round-trip but index-backed (idx_advisors_prefecture);
    # kept out of the hot path when the flag is false. Safe degrade: if
    # migration 024 isn't applied yet, the advisors table simply doesn't
    # exist and we return an empty list rather than 500.
    if include_advisors:
        industry_hint: str | None = None
        # target_type is the closest analog of "industry" in the programs
        # schema today. Take the first supplied target_type; empty ⇒ None.
        if target_type:
            industry_hint = target_type[0]
        try:
            from jpintel_mcp.api.advisors import query_matching_advisors

            response_body["matched_advisors"] = query_matching_advisors(
                conn,
                prefecture=prefecture,
                industry=industry_hint,
                limit=3,
            )
        except sqlite3.OperationalError:
            # advisors table not yet present (migration 024 not applied).
            response_body["matched_advisors"] = []

    return response_body


@router.post(
    "/batch",
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Batch ProgramDetail lookup. `results[]` is ordered by the deduped "
                "input `unified_ids`. Ids not found in the DB go to `not_found` — "
                "this is NOT a 404, because partial success is the point of batch."
            ),
            "model": BatchGetProgramsResponse,
        },
        422: {
            "model": ErrorEnvelope,
            "description": (
                "input validation failed (empty list, >50 ids, bad shape). "
                "`error.code='invalid_enum'`."
            ),
        },
    },
)
def batch_get_programs(
    payload: BatchGetProgramsRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Resolve up to 50 unified_ids in a single round-trip.

    Shape parity with GET /v1/programs/{unified_id} (same ProgramDetail per
    result), so SDK callers can chunk(ids, 50) and stitch locally without
    per-id round trips. The 50-cap IS the pagination; do not add a paging
    envelope.

    Order contract: `results[i]` corresponds to the i-th element of the
    *deduped* input list (first occurrence wins). Missing ids go to
    `not_found`, NOT a 404 — partial success is the whole point.

    # Quota accounting — TODO(W2):
    # Batch counts as 1 "get_program" unit against the per-key daily quota
    # today (log_usage inserts a single usage_events row). Spec calls for
    # N units per N-id batch. The existing accounting model is "one row
    # per request" (see api/deps._enforce_quota + usage_events schema). A
    # credits / weight column is a separate ticket — out of scope here.
    # When credits lands, swap the single log_usage call below for an
    # N-weighted accounting path.
    """
    # Batch is hardcoded fields=full (spec §3 "predictable schema across 50
    # rows at once"), so anon callers must upgrade. Sequential GET with
    # fields=default remains available to anon.
    _check_fields_tier_allowed("full", ctx.tier)
    # Dedupe while preserving first-occurrence order. Pydantic already
    # enforced 1 <= len(unified_ids) <= 50; this is the in-handler safety
    # net in case someone calls the function directly (e.g. from MCP).
    seen: set[str] = set()
    unified_ids: list[str] = []
    for uid in payload.unified_ids:
        if uid in seen:
            continue
        seen.add(uid)
        unified_ids.append(uid)

    if not unified_ids:
        # min_length=1 in the model catches this earlier (422); belt-and-braces
        # for direct callers.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "unified_ids required"
        )
    if len(unified_ids) > 50:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unified_ids cap is 50, got {len(unified_ids)}",
        )

    # Single SQL round-trip: IN-list with a placeholder per id. sqlite
    # hard-caps parameter count at 999 by default, so 50 is well under.
    placeholders = ",".join("?" * len(unified_ids))
    rows = conn.execute(
        f"SELECT * FROM programs WHERE unified_id IN ({placeholders})",
        unified_ids,
    ).fetchall()
    by_id: dict[str, sqlite3.Row] = {r["unified_id"]: r for r in rows}

    # Batch endpoint uses the "full" contract: enriched/source_mentions/
    # lineage keys always present even if null. This is the documented
    # shape for agent clients that want a predictable schema across 50
    # rows at once. Callers who want fields=default can issue single gets.
    results: list[dict[str, Any]] = []
    not_found: list[str] = []
    for uid in unified_ids:
        row = by_id.get(uid)
        if row is None:
            not_found.append(uid)
            continue
        # Any exception here bubbles up as a 500 per the ticket spec:
        # "a single broken row in a batch of 50 should bubble up as a 500;
        # partial success is for 'not found', not for exceptions".
        results.append(_row_to_program_detail(row, "full"))

    # Digest material (W7): group by the set of ids requested. Sort so any
    # permutation of the same set hashes identically.
    log_usage(
        conn,
        ctx,
        "programs.get",
        params={"batch_ids": sorted(unified_ids)},
    )
    return JSONResponse(
        content={"results": results, "not_found": not_found}
    )


@router.get(
    "/{unified_id}",
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "ProgramDetail. Shape depends on `fields`: "
                "minimal = 7-key whitelist, default = Program shape, "
                "full = Program + enriched + source_mentions + lineage (keys always present, may be null)."
            ),
            "model": ProgramDetail,
            "content": {
                "application/json": {
                    "example": {
                        "unified_id": "UNI-meti-jizokuka-2026",
                        "primary_name": "小規模事業者持続化補助金",
                        "tier": "S",
                        "authority_level": "national",
                        "authority_name": "全国商工会連合会",
                        "prefecture": "全国",
                        "program_kind": "補助金",
                        "amount_max_man_yen": 200,
                        "subsidy_rate": "2/3",
                        "funding_purpose": ["販路開拓", "業務効率化"],
                        "target_types": ["sole_proprietor", "sme"],
                        "official_url": "https://r3.jizokukahojokin.info/",
                        "source_url": "https://r3.jizokukahojokin.info/",
                        "source_fetched_at": "2026-04-20T05:14:33Z",
                        "next_deadline": "2026-06-12",
                        "enriched": None,
                        "source_mentions": {},
                        "source_checksum": "sha256:abc123",
                        "required_documents": ["事業計画書", "経費明細書"],
                    }
                }
            },
        },
        404: {
            "model": ErrorEnvelope,
            "description": "program not found — `error.code='no_matching_records'`.",
        },
    },
)
def get_program(
    unified_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
    fields: Annotated[
        FieldsLevel,
        Query(
            description=(
                "Payload size knob. minimal = 7-key whitelist. "
                "default = Program + enriched + source_mentions + lineage (current behavior — "
                "this endpoint has always returned ProgramDetail, so default == full in shape; "
                "the two values differ only in the guarantee that full's enriched/source_mentions "
                "keys are present even when null)."
            )
        ),
    ] = "default",
    as_of_date: Annotated[
        str | None,
        Query(
            description=(
                "R8 dataset versioning — pin lookup to dataset state at "
                "YYYY-MM-DD (ISO-8601). When set, the row is filtered with "
                "`valid_from <= as_of_date AND (valid_until IS NULL OR "
                "valid_until > as_of_date)`. Omit / null = live (today)."
            ),
            max_length=10,
        ),
    ] = None,
) -> JSONResponse:
    _as_of_iso = _validate_as_of_date(as_of_date)
    # 404 path stays uncached — if a row gets ingested or un-quarantined
    # we want the next request to discover it, not be pinned for 1h.
    if _as_of_iso is not None:
        _as_of_sql, _as_of_params = _as_of_predicate(_as_of_iso, "programs")
        if _as_of_sql:
            row = conn.execute(
                f"SELECT * FROM programs WHERE unified_id = ? AND {_as_of_sql}",
                (unified_id, *_as_of_params),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM programs WHERE unified_id = ?", (unified_id,)
            ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?", (unified_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "program not found")

    # Tier-X is a quality-gate quarantine. Stale slug links must 404 so we
    # never serve a quarantined row, matching the /search path's exclusion
    # behavior. Admin tooling that really wants a tier-X row can query the
    # DB directly.
    row_tier = row["tier"]
    if (row_tier or "X") == "X":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "program not found")

    # L4 cache: single-row reads change daily at most (programs are
    # ingested nightly), so 1h TTL is comfortably under the freshness
    # contract. Key includes ctx.tier because fields=full payload is
    # tier-gated (`_check_fields_tier_allowed` upstream of batch).
    _l4_params: dict[str, Any] = {
        "unified_id": unified_id,
        "fields": fields,
        "ctx_tier": ctx.tier,
        # R8: as_of_date partitions the cache so a snapshot-pinned lookup
        # never serves a payload computed for live (and vice-versa).
        "as_of_date": _as_of_iso,
    }
    _l4_key = canonical_cache_key(_L4_TOOL_GET, _l4_params)

    def _do_get() -> dict[str, Any]:
        return _row_to_program_detail(row, fields)

    body = _l4_get_or_compute_safe(
        cache_key=_l4_key,
        tool=_L4_TOOL_GET,
        params=_l4_params,
        compute=_do_get,
        ttl=_L4_TTL_PROGRAMS_GET,
    )
    log_usage(conn, ctx, "programs.get", params={"unified_id": unified_id})
    return JSONResponse(content=body)
