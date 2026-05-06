"""AutonoMath MCP NTA primary-source corpus tools (migration 102).

Four tools sit on top of the four nta_* tables created by migration 102:

  * ``find_saiketsu``       — 国税不服審判所 公表裁決事例 search
  * ``cite_tsutatsu``       — 通達 article lookup by code (法基通-9-2-3 etc.)
  * ``find_shitsugi``       — 国税庁 質疑応答事例 search
  * ``find_bunsho_kaitou``  — 国税庁 文書回答事例 search

Each tool emits a citation envelope with `_disclaimer` declaring the output
information retrieval, NOT 税務助言 (税理士法 §52). Every result row carries
`source_url` so the customer LLM can cite primary source verbatim.

Gate: AUTONOMATH_NTA_CORPUS_ENABLED (default True). The tools are read-only.

License: All rows are PUBLIC government documents (NTA / 国税不服審判所 利用規約;
PDL v1.0 / ministry standard). source_url + license columns are mandatory.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath, execute_with_retry
from .error_envelope import make_error
from .tools import (
    _clamp_limit,
    _clamp_offset,
    _db_error,
    _like_escape,
    _safe_tool,
    _validate_iso_date,
)

logger = logging.getLogger("jpintel.mcp.nta_corpus")


# Disclaimer text that wraps every result envelope (税理士法 §52 fence).
_DISCLAIMER_NTA = (
    "本 response は国税庁 / 国税不服審判所 公開資料の citation のみで、"
    "税務助言 (税理士法 §52) ではありません。掲載の裁決事例・質疑応答事例・"
    "文書回答事例・通達は公表時点の解釈であり、改正・廃止・新通達発出により "
    "現在の取扱が変更されている場合があります。個別案件は資格を有する税理士・"
    "弁護士に必ずご相談ください。各 row の source_url で一次資料を確認してください。"
)


_TAX_TYPE_LITERAL = Literal[
    "所得税",
    "法人税",
    "消費税",
    "相続税",
    "贈与税",
    "国税通則",
    "印紙税",
    "源泉所得税",
    "評価",
    "国際課税",
    "その他",
]

_SHITSUGI_CATEGORY_LITERAL = Literal[
    "shotoku",
    "gensen",
    "joto",
    "sozoku",
    "hyoka",
    "hojin",
    "shohi",
    "inshi",
    "hotei",
]

_BUNSHO_CATEGORY_LITERAL = Literal[
    "shotoku",
    "gensen",
    "joto-sanrin",
    "sozoku",
    "zoyo",
    "hyoka",
    "hojin",
    "shohi",
    "shozei",
    "sonota",
]


def _is_enabled() -> bool:
    return getattr(settings, "autonomath_nta_corpus_enabled", True)


def _envelope(
    results: list[dict[str, Any]], *, total: int, limit: int, offset: int
) -> dict[str, Any]:
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": results,
        "_disclaimer": _DISCLAIMER_NTA,
    }


# ---------------------------------------------------------------------------
# 1. find_saiketsu — 国税不服審判所 公表裁決事例 search
# ---------------------------------------------------------------------------


if _is_enabled():

    @mcp.tool(annotations=_READ_ONLY)
    @_safe_tool
    def find_saiketsu(
        query: Annotated[
            str,
            Field(
                description=(
                    "Free-text query against decision title + summary + fulltext "
                    "(FTS5 trigram on nta_saiketsu_fts). Use 2+ char kanji "
                    "compounds for precision (e.g. '居住者判定' / '重加算税')."
                ),
                min_length=1,
                max_length=200,
            ),
        ],
        tax_type: Annotated[
            _TAX_TYPE_LITERAL | None,
            Field(description="Optional 税目 filter ('所得税' / '法人税' / '消費税' / etc.)."),
        ] = None,
        year_from: Annotated[
            int | None,
            Field(
                description="Optional minimum decision year (西暦, e.g. 2020).", ge=1985, le=2100
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Max rows. Clamped to [1, 50]. Default 10.", ge=1, le=50),
        ] = 10,
        offset: Annotated[
            int,
            Field(description="Pagination offset. Default 0.", ge=0),
        ] = 0,
    ) -> dict[str, Any]:
        """[DISCOVER-CASE-LAW] 国税不服審判所 (KFS) 公表裁決事例 を全文検索 (FTS5 trigram on nta_saiketsu)。出力は citation のみで税務助言 (税理士法 §52) ではない。出典 source_url で原典確認必須。

        WHAT: Returns matching 裁決事例 rows with title / fiscal_period / tax_type /
        decision_date / decision_summary / source_url. The full text is not
        returned (cite by source_url instead — file size discipline).

        WHEN:
          - "居住者判定で争われた裁決事例は?"
          - "重加算税の隠ぺい仮装認定が覆った事例"
          - "外国子会社合算税制の取消事例 直近 3 年"

        WHEN NOT:
          - 通達の条文を直接引きたい → ``cite_tsutatsu``.
          - 国税庁公式の質疑応答 → ``find_shitsugi``.
          - 文書回答事例 (事前照会回答) → ``find_bunsho_kaitou``.

        RETURN: {total, limit, offset, results[{volume_no, case_no,
        decision_date, fiscal_period, tax_type, title, decision_summary,
        source_url}], _disclaimer}.

        LIMITATIONS:
          - Coverage is 直近 ~5 年 of published 裁決事例. 古い volume rows are
            ingested incrementally — older years may show 0 hits.
          - tax_type is parsed from KFS volume index <h2> labels and may be
            empty for some rows.
          - decision_date may be NULL when the page header lacks a 元号 date.
        """
        limit = _clamp_limit(limit, cap=50)
        offset = _clamp_offset(offset)
        q = (query or "").strip()
        if not q:
            return make_error(
                code="missing_required_arg",
                message="query is required.",
                hint="Pass a 2+ char kanji compound, e.g. query='居住者判定'.",
                field="query",
                limit=limit,
                offset=offset,
            )

        conn = connect_autonomath()
        # Build FTS5 query — trigram tolerates kanji as-is.
        # Escape FTS5 reserved chars by phrase-quoting.
        fts_q = '"' + q.replace('"', '""') + '"'

        where_extra: list[str] = []
        params: list[Any] = [fts_q]
        if tax_type:
            where_extra.append("s.tax_type LIKE ? ESCAPE '\\'")
            params.append(f"%{_like_escape(tax_type)}%")
        if year_from is not None:
            where_extra.append("(s.decision_date IS NOT NULL AND substr(s.decision_date,1,4) >= ?)")
            params.append(str(year_from))

        where_sql = ""
        if where_extra:
            where_sql = "AND " + " AND ".join(where_extra)

        sql_count = (
            "SELECT COUNT(*) FROM nta_saiketsu s "
            "JOIN nta_saiketsu_fts f ON f.rowid = s.id "
            f"WHERE f.nta_saiketsu_fts MATCH ? {where_sql}"
        )
        sql_data = (
            "SELECT s.id, s.volume_no, s.case_no, s.decision_date, s.fiscal_period, "
            "s.tax_type, s.title, s.decision_summary, s.source_url "
            "FROM nta_saiketsu s "
            "JOIN nta_saiketsu_fts f ON f.rowid = s.id "
            f"WHERE f.nta_saiketsu_fts MATCH ? {where_sql} "
            "ORDER BY s.decision_date DESC NULLS LAST, s.volume_no DESC, s.case_no DESC "
            "LIMIT ? OFFSET ?"
        )

        try:
            total = execute_with_retry(conn, sql_count, tuple(params))[0][0]
            rows = execute_with_retry(conn, sql_data, tuple(params + [limit, offset]))
        except sqlite3.Error as exc:
            return _db_error(exc, "find_saiketsu", limit=limit, offset=offset)

        results = [
            {
                "id": r["id"],
                "volume_no": r["volume_no"],
                "case_no": r["case_no"],
                "decision_date": r["decision_date"],
                "fiscal_period": r["fiscal_period"],
                "tax_type": r["tax_type"],
                "title": r["title"],
                "decision_summary": r["decision_summary"],
                "source_url": r["source_url"],
            }
            for r in rows
        ]
        return _envelope(results, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# 2. cite_tsutatsu — 通達 article lookup by code
# ---------------------------------------------------------------------------


if _is_enabled():

    @mcp.tool(annotations=_READ_ONLY)
    @_safe_tool
    def cite_tsutatsu(
        code: Annotated[
            str,
            Field(
                description=(
                    "Tsutatsu article code in '<prefix>-<article_number>' form. "
                    "Prefixes: 法基通 (法人税基本通達) / 所基通 (所得税基本通達) / "
                    "消基通 (消費税基本通達) / 相基通 (相続税基本通達) / "
                    "評基通 (財産評価基本通達). Examples: '法基通-9-2-3', "
                    "'所基通-36-1', '消基通-5-1-1'. Hyphen separator on the "
                    "article side; eda-ban use 'の' (e.g. '法基通-37-3の2')."
                ),
                min_length=3,
                max_length=80,
            ),
        ],
    ) -> dict[str, Any]:
        """[CITE-TSUTATSU] Lookup a 通達 article by code. Returns title + body excerpt + source_url. 出力は citation のみで税務助言 (税理士法 §52) ではない。

        WHAT: Direct lookup against ``nta_tsutatsu_index`` (which projects
        ``am_law_article`` rows where ``article_kind='tsutatsu'``). For deep
        dives use the existing ``get_law_article_am`` tool with the
        ``law_canonical_id`` returned here.

        WHEN:
          - "法基通 9-2-3 の本文を引きたい"
          - "所基通 36-1 の発出時期は?"
          - "消基通 5-1-1 を citation した resp の source_url は?"

        WHEN NOT:
          - 法令本文 (措置法・基本三法) → ``get_law_article_am``.
          - 裁決事例 → ``find_saiketsu``.
          - Q&A 形式の事例 → ``find_shitsugi``.

        RETURN: {total: 0|1, results[{code, law_canonical_id, article_number,
        title, body_excerpt, parent_code, source_url, last_amended}], _disclaimer}.
        Returns 0 results if the code does not match an indexed row — the
        ingest cron may not have refreshed yet, or the code uses a
        non-canonical separator.

        LIMITATIONS:
          - Only 法人税基本通達 / 消費税基本通達 are fully ingested at present
            (~2,007 articles). 所得税基本通達 / 相続税基本通達 / 財産評価基本通達
            are pending — those codes will return 0 until the ingest cron lands.
          - body_excerpt is the first 500 chars; the full body lives in
            ``am_law_article.text_full`` (use ``get_law_article_am``).
        """
        code = (code or "").strip()
        if not code:
            return make_error(
                code="missing_required_arg",
                message="code is required.",
                hint="Pass code='法基通-9-2-3' or similar.",
                field="code",
            )

        conn = connect_autonomath()
        try:
            rows = execute_with_retry(
                conn,
                """SELECT code, law_canonical_id, article_number, title,
                          body_excerpt, parent_code, source_url, last_amended,
                          refreshed_at
                   FROM nta_tsutatsu_index WHERE code = ?""",
                (code,),
            )
        except sqlite3.Error as exc:
            return _db_error(exc, "cite_tsutatsu", limit=1, offset=0)

        results: list[dict[str, Any]] = []
        if rows:
            results.append(dict(rows[0]))
        return _envelope(results, total=len(results), limit=1, offset=0)


# ---------------------------------------------------------------------------
# 3. find_shitsugi — 国税庁 質疑応答事例 search
# ---------------------------------------------------------------------------


if _is_enabled():

    @mcp.tool(annotations=_READ_ONLY)
    @_safe_tool
    def find_shitsugi(
        question_kw: Annotated[
            str,
            Field(
                description=(
                    "Free-text query against question + answer + related_law "
                    "(FTS5 trigram on nta_shitsugi_fts). Use 2+ char kanji "
                    "compounds (e.g. '医療費控除' / '損害賠償金')."
                ),
                min_length=1,
                max_length=200,
            ),
        ],
        category: Annotated[
            _SHITSUGI_CATEGORY_LITERAL | None,
            Field(
                description=(
                    "Optional 税目 category. URL-stem values: shotoku (所得税) / "
                    "gensen (源泉所得税) / joto (譲渡所得) / sozoku (相続税) / "
                    "hyoka (評価) / hojin (法人税) / shohi (消費税) / "
                    "inshi (印紙税) / hotei (法定調書)."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Max rows. Clamped to [1, 50]. Default 10.", ge=1, le=50),
        ] = 10,
        offset: Annotated[
            int,
            Field(description="Pagination offset. Default 0.", ge=0),
        ] = 0,
    ) -> dict[str, Any]:
        """[DISCOVER-QA] 国税庁 質疑応答事例 を全文検索 (FTS5 trigram on nta_shitsugi)。出力は citation のみで税務助言 (税理士法 §52) ではない。出典 source_url で原典確認必須。

        WHAT: Returns matching Q&A pairs with question (照会要旨) / answer
        (回答要旨) / related_law (関係法令通達) / category / source_url.

        WHEN:
          - "ガス爆発事故の損害賠償金は課税? 質疑応答事例"
          - "医療費控除 通勤費 質疑応答"
          - "中小企業者の判定 消費税 公式 Q&A"

        WHEN NOT:
          - 通達条文の直接引用 → ``cite_tsutatsu``.
          - 裁決例 → ``find_saiketsu``.
          - 文書回答事例 (事前照会回答) → ``find_bunsho_kaitou``.

        RETURN: {total, limit, offset, results[{slug, category, question,
        answer, related_law, source_url}], _disclaimer}.

        LIMITATIONS:
          - Coverage tracks 国税庁公開ページ which may be ~10,000 items;
            ingest is incremental and a freshly-launched 質疑応答 may not
            appear for 1-7 days.
          - related_law is free-text and may concatenate multiple law refs.
        """
        limit = _clamp_limit(limit, cap=50)
        offset = _clamp_offset(offset)
        q = (question_kw or "").strip()
        if not q:
            return make_error(
                code="missing_required_arg",
                message="question_kw is required.",
                hint="Pass a 2+ char kanji compound, e.g. question_kw='医療費控除'.",
                field="question_kw",
                limit=limit,
                offset=offset,
            )

        conn = connect_autonomath()
        fts_q = '"' + q.replace('"', '""') + '"'
        where_extra = ""
        params: list[Any] = [fts_q]
        if category:
            where_extra = "AND s.category = ?"
            params.append(category)

        try:
            total = execute_with_retry(
                conn,
                "SELECT COUNT(*) FROM nta_shitsugi s "
                "JOIN nta_shitsugi_fts f ON f.rowid=s.id "
                f"WHERE f.nta_shitsugi_fts MATCH ? {where_extra}",
                tuple(params),
            )[0][0]
            rows = execute_with_retry(
                conn,
                "SELECT s.id, s.slug, s.category, s.question, s.answer, "
                "s.related_law, s.source_url FROM nta_shitsugi s "
                "JOIN nta_shitsugi_fts f ON f.rowid=s.id "
                f"WHERE f.nta_shitsugi_fts MATCH ? {where_extra} "
                "ORDER BY s.id DESC LIMIT ? OFFSET ?",
                tuple(params + [limit, offset]),
            )
        except sqlite3.Error as exc:
            return _db_error(exc, "find_shitsugi", limit=limit, offset=offset)

        results = [dict(r) for r in rows]
        return _envelope(results, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# 4. find_bunsho_kaitou — 国税庁 文書回答事例 search
# ---------------------------------------------------------------------------


if _is_enabled():

    @mcp.tool(annotations=_READ_ONLY)
    @_safe_tool
    def find_bunsho_kaitou(
        topic: Annotated[
            str,
            Field(
                description=(
                    "Free-text query against request_summary + answer "
                    "(FTS5 trigram on nta_bunsho_kaitou_fts). 文書回答事例 are "
                    "formal pre-ruling letters; queries should be specific "
                    "事案 keywords."
                ),
                min_length=1,
                max_length=200,
            ),
        ],
        category: Annotated[
            _BUNSHO_CATEGORY_LITERAL | None,
            Field(
                description=(
                    "Optional 税目 category. URL-stem: shotoku (所得税) / "
                    "gensen (源泉) / joto-sanrin (譲渡・山林) / sozoku (相続税) / "
                    "zoyo (贈与税) / hyoka (評価) / hojin (法人税) / "
                    "shohi (消費税) / shozei (諸税) / sonota (その他)."
                )
            ),
        ] = None,
        date_from: Annotated[
            str | None,
            Field(description="Minimum response_date (ISO YYYY-MM-DD)."),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Max rows. Clamped to [1, 50]. Default 10.", ge=1, le=50),
        ] = 10,
        offset: Annotated[
            int,
            Field(description="Pagination offset. Default 0.", ge=0),
        ] = 0,
    ) -> dict[str, Any]:
        """[DISCOVER-RULING] 国税庁 文書回答事例 (事前照会回答) を全文検索。出力は citation のみで税務助言 (税理士法 §52) ではない。出典 source_url で原典確認必須。

        WHAT: 文書回答事例 are formal NTA written responses to pre-ruling
        inquiries from taxpayers. Each row contains 照会の趣旨 + 回答 +
        response_date + source_url.

        WHEN:
          - "M&A における持株会社化の文書回答"
          - "事業承継税制 適用関係 文書回答"
          - "ストックオプション 文書回答"

        WHEN NOT:
          - 一般 Q&A → ``find_shitsugi``.
          - 裁決例 (争訟結果) → ``find_saiketsu``.
          - 通達条文 → ``cite_tsutatsu``.

        RETURN: {total, limit, offset, results[{slug, category, response_date,
        request_summary, answer, source_url}], _disclaimer}.

        LIMITATIONS:
          - 文書回答事例 are 事案固有の判断 — citing one as 一般則 is risky.
            Always read the 照会の趣旨 carefully before using the response in
            advice.
          - Some older 文書回答 are PDF-only and parsing is best-effort —
            answer may be truncated or empty.
        """
        limit = _clamp_limit(limit, cap=50)
        offset = _clamp_offset(offset)
        q = (topic or "").strip()
        if not q:
            return make_error(
                code="missing_required_arg",
                message="topic is required.",
                hint="Pass a specific 事案 keyword, e.g. topic='事業承継税制'.",
                field="topic",
                limit=limit,
                offset=offset,
            )
        if date_from is not None:
            _, err = _validate_iso_date(date_from, field="date_from")
            if err is not None:
                return err

        conn = connect_autonomath()
        fts_q = '"' + q.replace('"', '""') + '"'
        where_extras: list[str] = []
        params: list[Any] = [fts_q]
        if category:
            where_extras.append("b.category = ?")
            params.append(category)
        if date_from:
            where_extras.append("(b.response_date IS NOT NULL AND b.response_date >= ?)")
            params.append(date_from)

        where_sql = ""
        if where_extras:
            where_sql = "AND " + " AND ".join(where_extras)

        try:
            total = execute_with_retry(
                conn,
                "SELECT COUNT(*) FROM nta_bunsho_kaitou b "
                "JOIN nta_bunsho_kaitou_fts f ON f.rowid=b.id "
                f"WHERE f.nta_bunsho_kaitou_fts MATCH ? {where_sql}",
                tuple(params),
            )[0][0]
            rows = execute_with_retry(
                conn,
                "SELECT b.id, b.slug, b.category, b.response_date, "
                "b.request_summary, b.answer, b.source_url FROM nta_bunsho_kaitou b "
                "JOIN nta_bunsho_kaitou_fts f ON f.rowid=b.id "
                f"WHERE f.nta_bunsho_kaitou_fts MATCH ? {where_sql} "
                "ORDER BY b.response_date DESC NULLS LAST, b.id DESC "
                "LIMIT ? OFFSET ?",
                tuple(params + [limit, offset]),
            )
        except sqlite3.Error as exc:
            return _db_error(exc, "find_bunsho_kaitou", limit=limit, offset=offset)

        results = [dict(r) for r in rows]
        return _envelope(results, total=total, limit=limit, offset=offset)


__all__ = [
    "find_saiketsu",
    "cite_tsutatsu",
    "find_shitsugi",
    "find_bunsho_kaitou",
]
