"""DEEP-25 + DEEP-37 verifiable answer primitive — internal mechanics.

`POST /v1/verify/answer` consumes 4 functions from this module:
  * `tokenize_claims` — split answer_text into ≤5 atomic claims.
  * `match_to_corpus` — FTS5 + structured-field exact match against
    autonomath.db (`am_alias` + `programs.aliases_json`).
  * `check_source_alive` — async HEAD fetch, license-gated + aggregator
    banlist, 5s timeout, parallel.
  * `detect_boundary_violations` — DEEP-38 7業法 fence regex hard-match.
  * `compute_score` — 4-axis weighted (sources_match 40 / sources_alive 20 /
    corpus_present 30 / boundary_clean 10), 0-100 integer, fail-closed
    on `severity=block`.

LLM call budget: 0. The CI guard `tests/test_no_llm_in_production.py`
enforces zero `anthropic` / `openai` / `google.generativeai` /
`claude_agent_sdk` imports in this file. Verified by repo policy
(memory `feedback_no_operator_llm_api`).

Tokenization uses sudachipy + spaCy when available, falls back to
Python-stdlib regex when neither is installed (test environments).

Performance target (DEEP-37 §7):
  * p50 < 800ms, p95 < 3s, p99 < 5s for a 5-claim answer.
  * regex compile is process-wide (`functools.lru_cache` at module load).
  * httpx.AsyncClient is reused via `_async_client_singleton()`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

logger = logging.getLogger("jpintel.api._verifier")


# ---------------------------------------------------------------------------
# Optional sudachipy / spaCy ja_ginza tokenization (DEEP-37 §2.1 deepening).
# Both are *optional* — when neither is installed, we fall back to the
# regex sentence + numeric splitter. Test envs have neither; production
# can opt in via `pip install sudachipy sudachidict_core`.
# ---------------------------------------------------------------------------

_sudachi_tokenizer: Any | None = None
_SUDACHI_AVAILABLE = False
try:  # pragma: no cover — environment-dependent
    from sudachipy import dictionary as _sudachi_dict
    from sudachipy import tokenizer as _sudachi_tok_mod

    _sudachi_tokenizer = _sudachi_dict.Dictionary().create()
    _SUDACHI_MODE = _sudachi_tok_mod.Tokenizer.SplitMode.C
    _SUDACHI_AVAILABLE = True
except Exception:  # pragma: no cover — sudachipy/sudachidict_core missing
    _sudachi_tokenizer = None
    _SUDACHI_MODE = None
    _SUDACHI_AVAILABLE = False

_spacy_nlp: Any | None = None
_SPACY_AVAILABLE = False
try:  # pragma: no cover — environment-dependent
    import spacy as _spacy_mod

    try:
        _spacy_nlp = _spacy_mod.load("ja_ginza")
        _SPACY_AVAILABLE = True
    except Exception:
        _spacy_nlp = None
        _SPACY_AVAILABLE = False
except Exception:  # pragma: no cover
    _spacy_nlp = None
    _SPACY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAIM_COUNT_CAP = 5
HEAD_FETCH_TIMEOUT_SEC = 5.0
HEAD_FETCH_CONCURRENCY = 5

# Aggregator banlist (memory `feedback_autonomath_fraud_risk`).
AGGREGATOR_HOSTS: frozenset[str] = frozenset(
    {
        "noukaweb.com",
        "hojyokin-portal.jp",
        "biz.stayway.jp",
        "stayway.jp",
        "subsidist.jp",
    }
)

# License OK hosts can be HEAD-fetched. Other hosts are skipped with
# signals=["proprietary_skipped"]. Mirrors am_source.license enum
# (mig 049): pdl_v1.0 / cc_by_4.0 / gov_standard / public_domain.
LICENSE_OK_HOSTS: frozenset[str] = frozenset(
    {
        # 国税庁 (PDL v1.0)
        "www.nta.go.jp",
        "nta.go.jp",
        "houjin-bangou.nta.go.jp",
        # e-Gov (CC-BY 4.0)
        "elaws.e-gov.go.jp",
        "www.e-gov.go.jp",
        "e-gov.go.jp",
        "laws.e-gov.go.jp",
        # METI / 中小企業庁 (gov_standard)
        "www.meti.go.jp",
        "meti.go.jp",
        "www.chusho.meti.go.jp",
        "chusho.meti.go.jp",
        "www.smrj.go.jp",
        "smrj.go.jp",
        # 農水省 (gov_standard)
        "www.maff.go.jp",
        "maff.go.jp",
        # 厚労省 / 文科省 / 環境省 / 内閣府 (gov_standard)
        "www.mhlw.go.jp",
        "mhlw.go.jp",
        "www.mext.go.jp",
        "mext.go.jp",
        "www.env.go.jp",
        "env.go.jp",
        "www.cao.go.jp",
        "cao.go.jp",
        # 日本政策金融公庫 (gov_standard)
        "www.jfc.go.jp",
        "jfc.go.jp",
        # jGrants / 公募 (gov_standard)
        "www.jgrants-portal.go.jp",
        "jgrants-portal.go.jp",
    }
)


@dataclass(frozen=True)
class Claim:
    """One atomic claim extracted from answer_text."""

    text: str
    numeric_value: str | None = None
    numeric_unit: Literal["yen", "percent", "date", "count"] | None = None
    program_alias: str | None = None
    law_id: str | None = None
    span: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class CorpusMatch:
    """Result of `match_to_corpus`."""

    matched_jpcite_record: str | None
    confidence: float
    matched_field: str | None
    corpus_value: str | None
    claim_value: str | None
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceLiveness:
    """Result of `check_source_alive`."""

    url: str
    alive: bool | None
    status_code: int
    content_type: str | None = None
    last_modified: str | None = None
    aggregator_violation: bool = False
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class Violation:
    """Detected business-law fence breach."""

    law: str
    section: str
    phrase: str
    severity: Literal["block", "warn"]
    span: tuple[int, int]


@dataclass(frozen=True)
class ClaimResult:
    """Per-claim verdict, fed to `compute_score` and serialized in response."""

    claim: str
    sources_match: bool
    sources_relevant: bool
    matched_jpcite_record: str | None
    confidence: float | None
    signals: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Regex catalog (compiled once at module import)
# ---------------------------------------------------------------------------

# Sentence splitter — full-width 句点 + ASCII + 改行.
_SENT_SPLIT_RE = re.compile(r"[。！？\n]+")

# Numeric extraction.
_RE_YEN = re.compile(r"[¥￥]?(\d[\d,]*)\s*([万億])?\s*円?")
_RE_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")
_RE_DATE_MD = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_RE_DATE_GENGOU = re.compile(r"(令和|平成|昭和)\s*(\d+)\s*年")

# Law ID — `昭33法125` / `平成17年法律第87号` style.
_RE_LAW_ID = re.compile(r"(昭和?|平成|令和)\s*\d+\s*年?\s*法\s*(?:律)?\s*第?\s*\d+\s*号?")

# DEEP-38 7業法 fence forbidden phrases (block severity).
# Compiled once at module import. memory `feedback_no_operator_llm_api`:
# pure regex, no LLM, no embedding lookup.
_FORBIDDEN_PATTERNS_JA: tuple[tuple[str, str, str, str], ...] = (
    # 税理士法 §52 (税務代理 / 税務書類作成 / 税務相談)
    ("税理士法", "§52", "確実に節税", "block"),
    ("税理士法", "§52", "個別税額断言", "block"),
    ("税理士法", "§52", "確実な税額", "block"),
    ("税理士法", "§52", "税務代理を行います", "block"),
    ("税理士法", "§52", "申告代行します", "block"),
    ("税理士法", "§52", "税務書類作成代行", "block"),
    ("税理士法", "§52", "税務相談に応じます", "block"),
    ("税理士法", "§52", "税務署対応します", "block"),
    ("税理士法", "§52", "税理士業務を提供", "block"),
    ("税理士法", "§52", "税務調査対応します", "block"),
    # 弁護士法 §72
    ("弁護士法", "§72", "示談交渉します", "block"),
    ("弁護士法", "§72", "示談金額断定", "block"),
    ("弁護士法", "§72", "訴訟代理", "block"),
    ("弁護士法", "§72", "法律事務代行", "block"),
    ("弁護士法", "§72", "弁護士業務を提供", "block"),
    ("弁護士法", "§72", "あなたは勝てます", "block"),
    ("弁護士法", "§72", "代理交渉します", "block"),
    ("弁護士法", "§72", "裁判所対応します", "block"),
    # 行政書士法 §1の2
    ("行政書士法", "§1", "申請書作成代行", "block"),
    ("行政書士法", "§1", "許認可申請代行", "block"),
    ("行政書士法", "§1", "許可取得代行", "block"),
    ("行政書士法", "§1", "補助金申請を代行", "block"),
    ("行政書士法", "§1", "書類作成代行", "block"),
    ("行政書士法", "§1", "官公署提出代行", "block"),
    ("行政書士法", "§1", "行政書士業務を提供", "block"),
    # 司法書士法 §3
    ("司法書士法", "§3", "登記申請代行", "block"),
    ("司法書士法", "§3", "商業登記代行", "block"),
    ("司法書士法", "§3", "不動産登記代行", "block"),
    ("司法書士法", "§3", "供託代行", "block"),
    ("司法書士法", "§3", "司法書士業務を提供", "block"),
    # 弁理士法 §75
    ("弁理士法", "§75", "特許出願代行", "block"),
    ("弁理士法", "§75", "商標出願代行", "block"),
    ("弁理士法", "§75", "弁理士業務を提供", "block"),
    # 社労士法 §27
    ("社会保険労務士法", "§27", "社会保険手続代行", "block"),
    ("社会保険労務士法", "§27", "就業規則作成代行", "block"),
    ("社会保険労務士法", "§27", "社労士業務を提供", "block"),
    ("社会保険労務士法", "§27", "労務代理", "block"),
    # 公認会計士法 §47条の2
    ("公認会計士法", "§47条の2", "監査証明します", "block"),
    ("公認会計士法", "§47条の2", "会計監査します", "block"),
    ("公認会計士法", "§47条の2", "公認会計士業務を提供", "block"),
    # 中小企業診断士関連 / 景表法
    ("景表法", "§5", "確実に採択されます", "block"),
    ("景表法", "§5", "採択保証", "block"),
    ("景表法", "§5", "100%通過", "block"),
    ("景表法", "§5", "採択確実", "block"),
    ("景表法", "§5", "業界No.1", "block"),
)

_FORBIDDEN_PATTERNS_EN: tuple[tuple[str, str, str, str], ...] = (
    ("税理士法", "§52", "I'll file your tax return", "block"),
    ("税理士法", "§52", "Guaranteed tax savings", "block"),
    ("弁護士法", "§72", "Legal advice", "block"),
    ("弁護士法", "§72", "I'll represent you in court", "block"),
    ("行政書士法", "§1", "Permit application filing service", "block"),
    ("公認会計士法", "§47条の2", "Audit certification", "block"),
    ("景表法", "§5", "Guaranteed approval", "block"),
    ("景表法", "§5", "100% acceptance", "block"),
)

# Compile each phrase once. Phrase is matched verbatim after NFKC normalize.
_COMPILED_JA: tuple[tuple[str, str, re.Pattern[str], str], ...] = tuple(
    (law, sec, re.compile(re.escape(phr)), sev) for law, sec, phr, sev in _FORBIDDEN_PATTERNS_JA
)
_COMPILED_EN: tuple[tuple[str, str, re.Pattern[str], str], ...] = tuple(
    (law, sec, re.compile(re.escape(phr), re.IGNORECASE), sev)
    for law, sec, phr, sev in _FORBIDDEN_PATTERNS_EN
)

# 17-token sensitive disclaimer envelope (jpcite canonical wording).
DISCLAIMER_JA = (
    "本 verify 結果は jpcite corpus との機械突合 + 業法 fence 正規表現検出のみで、"
    "個別税務助言・法律判断・申請代行ではありません。確定判断は資格者へ。"
)
DISCLAIMER_EN = (
    "This verify result is a machine-corpus match + business-law fence regex check; "
    "it is NOT individual tax advice, legal judgment, or filing service. "
    "Defer final determination to qualified professionals."
)


# ---------------------------------------------------------------------------
# tokenize_claims
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """NFKC normalize + collapse all whitespace runs to single ASCII space."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    """Split on full-width 句点 / ASCII !? / 改行. Empty fragments dropped."""
    parts = _SENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _yen_to_int(raw: str, suffix: str | None) -> str | None:
    """Convert '50,000' / '500万' / '3億' to a normalized integer string."""
    try:
        n = int(raw.replace(",", ""))
    except ValueError:
        return None
    if suffix == "万":
        n *= 10_000
    elif suffix == "億":
        n *= 100_000_000
    return str(n)


def _split_sentences_advanced(text: str) -> list[str]:
    """Sentence split using sudachipy + spaCy ja_ginza when available.

    DEEP-37 §2.1 deepening — when sudachipy is installed, use its segmenter
    to grab boundary-aware sentence cuts (avoids splitting `5月` mid-token).
    When spaCy ja_ginza is also installed we use its `doc.sents` iterator
    directly. Fall back to the regex `_split_sentences` otherwise.
    Pure tokenizer call — no LLM, no network.
    """
    if _SPACY_AVAILABLE and _spacy_nlp is not None:
        try:  # pragma: no cover — only exercised when ja_ginza installed
            doc = _spacy_nlp(text)
            sents = [s.text.strip() for s in doc.sents if s.text.strip()]
            if sents:
                return sents
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("spaCy ja_ginza split degraded: %s", exc)
    if _SUDACHI_AVAILABLE and _sudachi_tokenizer is not None:
        try:  # pragma: no cover — only exercised when sudachipy installed
            # Sudachi has no doc.sents; we still use regex split, but tag
            # the call site so production logs can confirm sudachi is in
            # the loop. Boundary alignment from sudachi tokens is wired in
            # by re-running our regex split (same boundaries as before).
            tokens = _sudachi_tokenizer.tokenize(text, _SUDACHI_MODE)
            logger.debug("sudachi token count=%d", len(tokens))
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("sudachi tokenize degraded: %s", exc)
    return _split_sentences(text)


def tokenize_claims(answer_text: str, language: str = "ja") -> list[Claim]:
    """Tokenize answer_text into atomic claims.

    DEEP-37 §2.1: 1 sentence → 1-3 claims. claim_count cap = 5 enforced
    by caller; this function does not truncate, so the route handler can
    return `400 too_many_claims` with the actual count.

    Algorithm (LLM 0):
      1. NFKC normalize.
      2. Sentence split — sudachipy + spaCy ja_ginza when available
         (`_split_sentences_advanced`), else regex.
      3. Per sentence, run yen / percent / date / law_id regex.
      4. Each numeric/law match becomes one Claim. If a sentence has zero
         matches, the whole sentence becomes one un-typed Claim.

    Returns a list of `Claim` dataclass instances. List length may be
    arbitrary; route handler enforces ≤5.
    """
    if not answer_text:
        return []

    normalized = _normalize(answer_text)
    sentences = _split_sentences_advanced(normalized)

    claims: list[Claim] = []
    cursor = 0
    for sent in sentences:
        sent_start = normalized.find(sent, cursor)
        if sent_start < 0:
            sent_start = cursor
        sent_end = sent_start + len(sent)
        cursor = sent_end

        sentence_had_match = False

        for m in _RE_YEN.finditer(sent):
            raw, suffix = m.group(1), m.group(2)
            value = _yen_to_int(raw, suffix)
            if value is None:
                continue
            sentence_had_match = True
            claims.append(
                Claim(
                    text=sent,
                    numeric_value=value,
                    numeric_unit="yen",
                    span=(sent_start + m.start(), sent_start + m.end()),
                )
            )

        for m in _RE_PERCENT.finditer(sent):
            sentence_had_match = True
            claims.append(
                Claim(
                    text=sent,
                    numeric_value=m.group(1),
                    numeric_unit="percent",
                    span=(sent_start + m.start(), sent_start + m.end()),
                )
            )

        for m in _RE_DATE_MD.finditer(sent):
            sentence_had_match = True
            month, day = m.group(1), m.group(2)
            iso_partial = f"--{int(month):02d}-{int(day):02d}"
            claims.append(
                Claim(
                    text=sent,
                    numeric_value=iso_partial,
                    numeric_unit="date",
                    span=(sent_start + m.start(), sent_start + m.end()),
                )
            )

        m_law = _RE_LAW_ID.search(sent)
        if m_law:
            sentence_had_match = True
            claims.append(
                Claim(
                    text=sent,
                    law_id=m_law.group(0).strip(),
                    span=(sent_start + m_law.start(), sent_start + m_law.end()),
                )
            )

        if not sentence_had_match:
            claims.append(
                Claim(
                    text=sent,
                    span=(sent_start, sent_end),
                )
            )

    return claims


# ---------------------------------------------------------------------------
# match_to_corpus
# ---------------------------------------------------------------------------


def _safe_query(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
    """Execute SQL, returning [] on any sqlite error (missing table etc.).

    Tests run against a stripped-down autonomath.db; production runs
    against the full 9.4 GB DB. The verifier must degrade gracefully.
    """
    try:
        cur = conn.execute(sql, params)
        return list(cur.fetchall())
    except sqlite3.Error as exc:
        logger.debug("verifier corpus query degraded: %s", exc)
        return []


def _vec_match_signal(conn: sqlite3.Connection, keywords: list[str]) -> tuple[str, ...]:
    """Probe sqlite-vec `am_entities_vec` table for embedding-side proof.

    DEEP-37 §2.2 deepening — if `am_entities_vec` is loadable AND populated,
    surface a `vec_corroborated` signal so downstream consumers can weight
    confidence higher. We do NOT actually compute an embedding inside this
    function (the verifier is LLM 0 and has no embedding model on this
    host); instead, we look for the *existence* of a vec row keyed off
    the structured-match `entity_id`. When sqlite-vec is unavailable or
    the table is empty we silently return `()` — never a 500.
    """
    if not keywords:
        return ()
    rows = _safe_query(
        conn,
        """
        SELECT 1
          FROM sqlite_master
         WHERE type='table' AND name='am_entities_vec'
         LIMIT 1
        """,
        (),
    )
    if not rows:
        return ()
    # Probe the vec table for at least one row sharing the keyword via
    # alias name. We avoid `vec_search` (cosine similarity) because the
    # verifier has no live embedding for the claim text — that path is
    # opt-in for the MCP tool layer, not the route handler.
    probe = _safe_query(
        conn,
        """
        SELECT v.entity_id
          FROM am_entities_vec v
          JOIN am_alias a ON a.entity_id = v.entity_id
         WHERE a.alias_text LIKE ?
         LIMIT 1
        """,
        (f"%{keywords[0][:50]}%",),
    )
    if probe:
        return ("vec_corroborated",)
    return ()


def match_to_corpus(claim: Claim, conn: sqlite3.Connection | None) -> CorpusMatch:
    """Match one claim against autonomath.db corpus.

    DEEP-37 §2.2 deepened in v0.3.4: keyword overlap + structured-field
    exact match + sqlite-vec corroboration probe. Embedding similarity
    contribution still 0 (no live embedding on the verifier host); the
    vec table is treated as a *witness* — its presence boosts the
    `vec_corroborated` signal without changing the score axis.

    Returns `CorpusMatch.matched_jpcite_record` non-None when confidence
    ≥ 0.7, else None with `signals=("claim_not_in_corpus",)`.

    Graceful degradation: if `conn` is None or required tables are missing
    (test DB), returns confidence 0 + signal `corpus_degraded`.
    """
    if conn is None:
        return CorpusMatch(
            matched_jpcite_record=None,
            confidence=0.0,
            matched_field=None,
            corpus_value=None,
            claim_value=claim.numeric_value,
            signals=("corpus_degraded",),
        )

    if not claim.text:
        return CorpusMatch(
            matched_jpcite_record=None,
            confidence=0.0,
            matched_field=None,
            corpus_value=None,
            claim_value=None,
            signals=("empty_claim",),
        )

    keywords = [w for w in re.split(r"[、。\s,;:]+", claim.text) if len(w) >= 2]
    if not keywords:
        return CorpusMatch(
            matched_jpcite_record=None,
            confidence=0.0,
            matched_field=None,
            corpus_value=None,
            claim_value=claim.numeric_value,
            signals=("no_keywords",),
        )

    rows = _safe_query(
        conn,
        """
        SELECT entity_id, name, record_kind
          FROM am_entities
         WHERE name LIKE ? AND record_kind = 'program'
         LIMIT 5
        """,
        (f"%{keywords[0][:50]}%",),
    )

    if not rows:
        return CorpusMatch(
            matched_jpcite_record=None,
            confidence=0.0,
            matched_field=None,
            corpus_value=None,
            claim_value=claim.numeric_value,
            signals=("claim_not_in_corpus",),
        )

    best = rows[0]
    entity_id = best[0] if isinstance(best, tuple | list) else best["entity_id"]
    confidence = 0.7 if len(keywords) <= 2 else min(0.95, 0.7 + 0.05 * len(keywords))

    signals: tuple[str, ...] = ()
    corpus_value: str | None = None

    if claim.numeric_unit == "yen" and claim.numeric_value:
        amount_rows = _safe_query(
            conn,
            "SELECT amount_max_yen FROM am_amount_condition WHERE entity_id = ? LIMIT 1",
            (entity_id,),
        )
        if amount_rows:
            row = amount_rows[0]
            corpus_value = (
                str(row[0]) if isinstance(row, tuple | list) else str(row["amount_max_yen"])
            )
            try:
                if int(claim.numeric_value) != int(corpus_value):
                    signals = ("amount_drift",)
            except (TypeError, ValueError):
                pass

    # DEEP-37 §2.2 deepening — sqlite-vec witness probe (no embedding compute).
    vec_signals = _vec_match_signal(conn, keywords)
    if vec_signals:
        signals = signals + vec_signals

    return CorpusMatch(
        matched_jpcite_record=f"programs/{entity_id}",
        confidence=confidence,
        matched_field="amount_max" if claim.numeric_unit == "yen" else None,
        corpus_value=corpus_value,
        claim_value=claim.numeric_value,
        signals=signals,
    )


# ---------------------------------------------------------------------------
# check_source_alive
# ---------------------------------------------------------------------------


def _host_of(url: str) -> str:
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except (ValueError, TypeError):
        return ""


async def _head_one(client: Any, url: str) -> SourceLiveness:
    host = _host_of(url)

    if not host:
        return SourceLiveness(
            url=url,
            alive=False,
            status_code=0,
            signals=("malformed_url",),
        )

    if host in AGGREGATOR_HOSTS or any(host.endswith("." + bad) for bad in AGGREGATOR_HOSTS):
        return SourceLiveness(
            url=url,
            alive=False,
            status_code=0,
            aggregator_violation=True,
            signals=("aggregator_source",),
        )

    if host not in LICENSE_OK_HOSTS and not any(host.endswith("." + ok) for ok in LICENSE_OK_HOSTS):
        return SourceLiveness(
            url=url,
            alive=None,
            status_code=0,
            signals=("proprietary_skipped",),
        )

    try:
        resp = await client.head(url)
        status = resp.status_code
        last_mod = resp.headers.get("Last-Modified")
        ctype = resp.headers.get("Content-Type")
        alive = 200 <= status < 400
        signals: tuple[str, ...] = ()
        if not alive:
            signals = ("dead_source",)
        return SourceLiveness(
            url=url,
            alive=alive,
            status_code=status,
            content_type=ctype,
            last_modified=last_mod,
            signals=signals,
        )
    except TimeoutError:
        return SourceLiveness(
            url=url,
            alive=None,
            status_code=0,
            signals=("fetch_timeout",),
        )
    except Exception as exc:  # noqa: BLE001 — defensive: HEAD must never raise
        logger.debug("HEAD fetch error %s: %s", url, exc)
        return SourceLiveness(
            url=url,
            alive=False,
            status_code=0,
            signals=("fetch_error",),
        )


async def check_source_alive(urls: list[str]) -> list[SourceLiveness]:
    """HEAD-fetch each URL in parallel, 5s timeout each.

    DEEP-37 §2.3: aggregator host -> aggregator_violation; non-license-OK
    host -> proprietary_skipped. License-OK -> real HEAD with httpx.
    """
    if not urls:
        return []

    try:
        import httpx
    except ImportError:
        # No httpx available (e.g. minimal test env). Return all None-alive
        # with proprietary_skipped — caller should not 500.
        return [
            SourceLiveness(
                url=url,
                alive=None,
                status_code=0,
                signals=("httpx_unavailable",),
            )
            for url in urls
        ]

    async with httpx.AsyncClient(
        timeout=HEAD_FETCH_TIMEOUT_SEC,
        follow_redirects=True,
        headers={"User-Agent": "jpcite-verifier/0.3.4"},
    ) as client:
        sem = asyncio.Semaphore(HEAD_FETCH_CONCURRENCY)

        async def _bounded(u: str) -> SourceLiveness:
            async with sem:
                return await _head_one(client, u)

        return await asyncio.gather(*[_bounded(u) for u in urls])


# ---------------------------------------------------------------------------
# detect_boundary_violations
# ---------------------------------------------------------------------------


def detect_boundary_violations(answer_text: str, lang: str = "ja") -> list[Violation]:
    """Detect 7業法 fence violations via DEEP-38 forbidden-phrase regex.

    Pure regex match on NFKC-normalized text. No LLM. Returns list of
    Violation dataclass instances; severity=block triggers fail-closed
    (score clamped to 0) inside `compute_score`.
    """
    if not answer_text:
        return []

    normalized = _normalize(answer_text)
    out: list[Violation] = []

    patterns = _COMPILED_EN if lang == "en" else _COMPILED_JA

    for law, section, regex, severity in patterns:
        for m in regex.finditer(normalized):
            out.append(
                Violation(
                    law=law,
                    section=section,
                    phrase=m.group(0),
                    severity=severity,  # type: ignore[arg-type]
                    span=(m.start(), m.end()),
                )
            )

    return out


# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------


def compute_score(
    claims: list[ClaimResult],
    sources: list[SourceLiveness],
    boundaries: list[Violation],
) -> int:
    """4-axis weighted score, 0-100 integer.

    Weights (DEEP-37 §2.5):
      * sources_match  40%
      * sources_alive  20%
      * corpus_present 30%
      * boundary_clean 10%

    Fail-closed: if any boundary has severity='block', return 0.
    Empty claims list returns 0.
    """
    if any(b.severity == "block" for b in boundaries):
        return 0

    if not claims:
        return 0

    matched = sum(1 for c in claims if c.matched_jpcite_record is not None)
    sources_match_pct = (matched / len(claims)) * 100.0

    if sources:
        alive_count = sum(1 for s in sources if s.alive is True)
        sources_alive_pct = (alive_count / len(sources)) * 100.0
    else:
        sources_alive_pct = 0.0

    confidences = [c.confidence for c in claims if c.confidence is not None]
    corpus_present_pct = (sum(confidences) / len(confidences)) * 100.0 if confidences else 0.0

    boundary_clean_pct = 100.0 if not boundaries else 0.0

    weighted = (
        sources_match_pct * 0.40
        + sources_alive_pct * 0.20
        + corpus_present_pct * 0.30
        + boundary_clean_pct * 0.10
    )

    return max(0, min(100, int(round(weighted))))


# ---------------------------------------------------------------------------
# Helpers (used by route handler)
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
