"""Funding Stack Checker — deterministic 制度併用可否 verdict (no LLM).

Reference plan: ``docs/_internal/value_maximization_plan_no_llm_api.md`` §8.4 +
§28.7. The Stack Checker resolves the everyday consultant question
「IT導入補助金 と 事業再構築補助金 を同年度に併用できるか?」 against two
already-curated rule corpora and returns:

  * ``compatible``      — 併用根拠あり (一次資料 + 出典 sourced)
  * ``incompatible``    — 併用禁止根拠あり (一括併用禁止 / 重複受給禁止)
  * ``requires_review`` — 前提認定 chain や条件付き併用 (人手確認推奨)
  * ``unknown``         — 出典不足 / heuristic のみ

Schema dependencies
-------------------

* ``autonomath.db / am_compat_matrix`` — 43,966 行
    ``(program_a_id, program_b_id, compat_status, source_url, inferred_only,
       conditions_text, rationale_short, confidence)``

  ``inferred_only=0`` の 22,290 行を **authoritative** (出典付きまたは
  人手キュレーション) と扱い、それ以外の 41,943 行は heuristic と扱う。
  CLAUDE.md "4,300 sourced + 41,000+ heuristic" の honest split を維持。

* ``data/jpintel.db / exclusion_rules`` — 181 行
    ``(rule_id, kind, severity, program_a, program_b, program_b_group_json,
       description, source_urls_json, program_a_uid, program_b_uid)``

  ``kind`` 集計: 125 exclude + 17 prerequisite + 15 absolute + 24 other.
  ``program_a / program_b`` は slug / 名称 / unified_id 混在。Migration 051 で
  ``program_a_uid / program_b_uid`` に正規化済 row のみ uid match を適用。

Algorithm
---------

For an ordered pair ``(a, b)``:

1. ``am_compat_matrix`` を ``(a, b)`` または ``(b, a)`` で 1 行検索する
   (順不同を許容)。``compat_status='compatible'/'incompatible'`` かつ
   ``inferred_only=0`` の行は authoritative — confidence 1.0 で確定。

2. ``compat_status='case_by_case'`` または ``inferred_only=1`` (heuristic)
   の場合は確定せず、3. 以降のフォールバックを継続する。

3. ``exclusion_rules`` で ``kind IN ('exclude','absolute')`` の行を
   ``program_a / program_b / program_b_group_json`` および
   ``program_a_uid / program_b_uid`` に対して検索。両 program が rule に
   登場すれば ``incompatible`` (confidence 0.9, rule fallback)。

4. ``kind='prerequisite'`` の行で a が b を前提として要求する (またはその
   逆) 場合は ``requires_review`` (confidence 0.6) に格下げ。
   依存関係そのものは「stack できる/できない」を直接決めないので、必ず
   reviewer に surface する。

5. case_by_case authoritative (sourced) は ``requires_review`` (confidence
   0.7) に格下げ。条件付き併用なので人手確認必須。

6. 1-5 すべて該当しない場合は ``unknown`` (confidence 0.0)。

stack 集計の strictness:
``incompatible > requires_review > unknown > compatible``

メモリ
------
* ``am_compat_matrix`` 43,966 行 × ~150 バイト = ~6.5MB。``__init__`` 時に
  全件を ``dict[(a, b), row]`` で読み込み、``check_pair`` は O(1)。
* ``exclusion_rules`` 181 行は trivial。

両 DB は read-only モードで開く。書き込み権限を一切持たない。

Disclaimer (mandatory)
----------------------
非 LLM rule engine は curate されたコーパスに 100% 依拠し、収録漏れ・
法令改正・公募回ごとの細則差を取りこぼし得る。出力は必ず一次資料 (公募要領 /
適正化法 17 条 / 重複受給禁止条項) と専門家 (税理士 / 行政書士 / 中小企業
診断士) で確定すること。
"""
from __future__ import annotations

import itertools
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("jpintel.services.funding_stack_checker")


Verdict = Literal[
    "compatible",
    "incompatible",
    "requires_review",
    "unknown",
]


_VERDICT_STRICTNESS: dict[str, int] = {
    "incompatible": 3,
    "requires_review": 2,
    "unknown": 1,
    "compatible": 0,
}


_DISCLAIMER_PAIR = (
    "本判定は am_compat_matrix (4,300 sourced + 約 39,000 heuristic) と "
    "exclusion_rules (181 行) の機械的照合で、税務代理 (税理士法 §52) "
    "または申請代理 (行政書士法 §1) の代替ではありません。収録漏れや "
    "公募回ごとの細則差を取りこぼし得るため、最終判断は必ず公募要領・"
    "適正化法 17 条・重複受給禁止条項などの一次資料および専門家 (税理士 / "
    "行政書士 / 中小企業診断士) によって確認してください。"
)


_DISCLAIMER_STACK = (
    "本 stack 判定は全 pair について am_compat_matrix と exclusion_rules を "
    "機械的に照合した集計で、いずれか 1 pair が incompatible / requires_review "
    "の場合はその制度組合せ全体に同等の注意が必要です。最終判断は必ず一次資料 "
    "(公募要領 / 適正化法 17 条 / 重複受給禁止条項) と専門家 (税理士 / 行政"
    "書士 / 中小企業診断士) で確定してください。"
)


# ---------------------------------------------------------------------------
# Result envelopes (plain dicts, exposed as TypedDict-style aliases for clarity)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StackVerdict:
    """Per-pair verdict envelope.

    ``rule_chain`` lists every rule (in order of evaluation) that contributed
    to the verdict, so callers can audit the reasoning.
    """

    program_a: str
    program_b: str
    verdict: Verdict
    confidence: float
    rule_chain: list[dict[str, Any]] = field(default_factory=list)
    disclaimer: str = _DISCLAIMER_PAIR

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_a": self.program_a,
            "program_b": self.program_b,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rule_chain": list(self.rule_chain),
            "_disclaimer": self.disclaimer,
        }


@dataclass(slots=True)
class StackResult:
    """Aggregate envelope for a stack of N programs (C(N, 2) pairs)."""

    program_ids: list[str]
    all_pairs_status: Verdict
    pairs: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    disclaimer: str = _DISCLAIMER_STACK

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_ids": list(self.program_ids),
            "all_pairs_status": self.all_pairs_status,
            "pairs": list(self.pairs),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "_disclaimer": self.disclaimer,
            "total_pairs": len(self.pairs),
        }


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


class FundingStackChecker:
    """Pure-SQLite + Python rule engine.

    Both DBs are opened read-only. The compat matrix is loaded fully into
    memory at construction (~6.5 MB) so ``check_pair`` is O(1); the
    exclusion rules table (181 rows) is loaded the same way.

    Thread-safety: instances are NOT thread-safe in mid-construction (the
    ``_load_*`` calls run plain sqlite cursors). Once constructed, the
    in-memory dicts are immutable for the lifetime of the instance and
    callers can use it from multiple threads concurrently.
    """

    def __init__(
        self,
        jpintel_db: Path | str,
        autonomath_db: Path | str,
    ) -> None:
        self.jpintel_db = Path(jpintel_db)
        self.autonomath_db = Path(autonomath_db)

        # Pre-loaded indexes. Populated by _load_* below.
        # Key is the unordered pair (sorted tuple) so check_pair lookups
        # do not depend on caller-supplied argument order.
        self._compat_index: dict[tuple[str, str], dict[str, Any]] = {}
        self._exclusion_rules: list[dict[str, Any]] = []

        self._load_compat_matrix()
        self._load_exclusion_rules()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _open_ro(self, path: Path) -> sqlite3.Connection:
        if not path.exists():
            raise FileNotFoundError(f"sqlite file not found: {path}")
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_compat_matrix(self) -> None:
        """Read ``am_compat_matrix`` from autonomath.db into memory.

        The table is (program_a_id, program_b_id) PK, so each ordered pair
        appears at most once. We index by the SORTED tuple so a caller
        passing ``(b, a)`` still hits the same row.
        """
        conn = self._open_ro(self.autonomath_db)
        try:
            cursor = conn.execute(
                """
                SELECT program_a_id, program_b_id, compat_status,
                       conditions_text, rationale_short, source_url,
                       confidence, inferred_only
                  FROM am_compat_matrix
                """,
            )
            for row in cursor:
                a = row["program_a_id"]
                b = row["program_b_id"]
                if not a or not b:
                    continue
                key = self._pair_key(a, b)
                # Prefer authoritative (inferred_only=0) over heuristic if
                # both directions of the same pair somehow appear.
                existing = self._compat_index.get(key)
                if (
                    existing is not None
                    and existing.get("inferred_only") == 0
                    and row["inferred_only"] != 0
                ):
                    continue
                self._compat_index[key] = {
                    "program_a_id": a,
                    "program_b_id": b,
                    "compat_status": row["compat_status"],
                    "conditions_text": row["conditions_text"],
                    "rationale_short": row["rationale_short"],
                    "source_url": row["source_url"],
                    "confidence": row["confidence"],
                    "inferred_only": int(row["inferred_only"] or 0),
                }
        finally:
            conn.close()
        logger.debug(
            "loaded am_compat_matrix index: %d unique pairs",
            len(self._compat_index),
        )

    def _load_exclusion_rules(self) -> None:
        """Read all ``exclusion_rules`` rows from data/jpintel.db.

        Schema (from migration 051): rule_id / kind / severity / program_a /
        program_b / program_b_group_json / description / source_urls_json /
        program_a_uid / program_b_uid (the _uid columns are the resolved
        ``programs.unified_id`` when discoverable; legacy rows have NULL).
        """
        conn = self._open_ro(self.jpintel_db)
        try:
            # PRAGMA introspection so we degrade gracefully on a fresh DB
            # whose schema predates migration 051 (the _uid columns).
            cols = {r[1] for r in conn.execute("PRAGMA table_info(exclusion_rules)")}
            has_uid = (
                "program_a_uid" in cols and "program_b_uid" in cols
            )
            has_group = "program_b_group_json" in cols
            has_source_urls = "source_urls_json" in cols
            has_severity = "severity" in cols

            select_cols = [
                "rule_id",
                "kind",
                "program_a",
                "program_b",
                "description",
            ]
            if has_severity:
                select_cols.append("severity")
            if has_group:
                select_cols.append("program_b_group_json")
            if has_source_urls:
                select_cols.append("source_urls_json")
            if has_uid:
                select_cols.extend(["program_a_uid", "program_b_uid"])

            sql = "SELECT " + ", ".join(select_cols) + " FROM exclusion_rules"
            cursor = conn.execute(sql)
            for row in cursor:
                keys = row.keys() if hasattr(row, "keys") else []
                rule = {
                    "rule_id": row["rule_id"],
                    "kind": row["kind"],
                    "program_a": row["program_a"],
                    "program_b": row["program_b"],
                    "description": row["description"],
                    "severity": row["severity"] if "severity" in keys else None,
                    "program_a_uid": (
                        row["program_a_uid"] if "program_a_uid" in keys else None
                    ),
                    "program_b_uid": (
                        row["program_b_uid"] if "program_b_uid" in keys else None
                    ),
                }
                # Decode the optional group column.
                group: list[str] = []
                if "program_b_group_json" in keys:
                    raw = row["program_b_group_json"]
                    if raw:
                        try:
                            decoded = json.loads(raw)
                            if isinstance(decoded, list):
                                group = [str(x) for x in decoded if x]
                        except json.JSONDecodeError:
                            group = []
                rule["program_b_group"] = group

                source_urls: list[str] = []
                if "source_urls_json" in keys:
                    raw = row["source_urls_json"]
                    if raw:
                        try:
                            decoded = json.loads(raw)
                            if isinstance(decoded, list):
                                source_urls = [str(x) for x in decoded if x]
                        except json.JSONDecodeError:
                            source_urls = []
                rule["source_urls"] = source_urls
                self._exclusion_rules.append(rule)
        finally:
            conn.close()
        logger.debug(
            "loaded exclusion_rules: %d rows", len(self._exclusion_rules)
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pair_key(a: str, b: str) -> tuple[str, str]:
        """Return an order-independent index key for the pair."""
        return (a, b) if a <= b else (b, a)

    @staticmethod
    def _rule_mentions(rule: dict[str, Any], program: str) -> bool:
        """True iff ``rule`` references ``program`` directly or via _uid / group."""
        for key in ("program_a", "program_b", "program_a_uid", "program_b_uid"):
            v = rule.get(key)
            if v and v == program:
                return True
        return program in rule.get("program_b_group", [])

    @staticmethod
    def _rule_text(rule: dict[str, Any]) -> str:
        """Return a compact one-line text summary of the rule for the chain."""
        desc = rule.get("description") or ""
        if desc:
            # Trim to keep the rule_chain envelope readable.
            return desc[:300]
        return f"{rule.get('rule_id') or ''} ({rule.get('kind') or 'rule'})"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_pair(self, program_a: str, program_b: str) -> StackVerdict:
        """Return a verdict for one ordered pair.

        Self-pairs (a == b) are never legitimate stacks; they short-circuit
        to ``incompatible`` so the caller surfaces the input mistake to the
        user instead of silently returning ``unknown``.
        """
        a = (program_a or "").strip()
        b = (program_b or "").strip()
        if not a or not b:
            return StackVerdict(
                program_a=program_a or "",
                program_b=program_b or "",
                verdict="unknown",
                confidence=0.0,
                rule_chain=[
                    {
                        "source": "input_validation",
                        "rule_text": "program_a / program_b は非空文字列が必須です。",
                        "weight": 0.0,
                    }
                ],
            )
        if a == b:
            return StackVerdict(
                program_a=a,
                program_b=b,
                verdict="incompatible",
                confidence=1.0,
                rule_chain=[
                    {
                        "source": "input_validation",
                        "rule_text": (
                            "同一 program_id を併用することはできません "
                            "(self-pair)。"
                        ),
                        "weight": 1.0,
                    }
                ],
            )

        rule_chain: list[dict[str, Any]] = []

        # --- Step 1-2: am_compat_matrix lookup ---
        compat = self._compat_index.get(self._pair_key(a, b))
        if compat is not None:
            status = compat["compat_status"]
            inferred_only = compat["inferred_only"]
            entry = {
                "source": "am_compat_matrix",
                "rule_text": (
                    compat.get("rationale_short")
                    or compat.get("conditions_text")
                    or f"compat_status={status}"
                )[:300],
                "weight": 1.0 if inferred_only == 0 else 0.3,
                "compat_status": status,
                "inferred_only": inferred_only,
                "source_url": compat.get("source_url"),
            }
            rule_chain.append(entry)

            # 1. Authoritative compatible / incompatible — terminal.
            if inferred_only == 0 and status in ("compatible", "incompatible"):
                return StackVerdict(
                    program_a=a,
                    program_b=b,
                    verdict=status,
                    confidence=1.0,
                    rule_chain=rule_chain,
                )

            # case_by_case (sourced) → requires_review unless an exclusion
            # rule overrides below. We do NOT return yet — let exclusion
            # rules win if they assert incompatibility.
            # heuristic-only rows (inferred_only=1) likewise do not
            # short-circuit; we keep gathering signal.

        # --- Step 3: exclusion_rules absolute / exclude ---
        for rule in self._exclusion_rules:
            kind = rule["kind"]
            if kind not in ("exclude", "absolute"):
                continue
            if self._rule_mentions(rule, a) and self._rule_mentions(rule, b):
                rule_chain.append(
                    {
                        "source": "exclusion_rules",
                        "rule_id": rule["rule_id"],
                        "kind": kind,
                        "severity": rule.get("severity"),
                        "rule_text": self._rule_text(rule),
                        "weight": 0.9,
                        "source_urls": rule.get("source_urls", []),
                    }
                )
                return StackVerdict(
                    program_a=a,
                    program_b=b,
                    verdict="incompatible",
                    confidence=0.9,
                    rule_chain=rule_chain,
                )

        # --- Step 4: prerequisite chain ---
        for rule in self._exclusion_rules:
            if rule["kind"] != "prerequisite":
                continue
            if self._rule_mentions(rule, a) and self._rule_mentions(rule, b):
                rule_chain.append(
                    {
                        "source": "exclusion_rules",
                        "rule_id": rule["rule_id"],
                        "kind": "prerequisite",
                        "severity": rule.get("severity"),
                        "rule_text": self._rule_text(rule),
                        "weight": 0.6,
                        "source_urls": rule.get("source_urls", []),
                        "note": (
                            "片方が他方の前提認定として参照されています。"
                            "stack 可否は前提取得の有無に依存するため reviewer 確認を推奨。"
                        ),
                    }
                )
                return StackVerdict(
                    program_a=a,
                    program_b=b,
                    verdict="requires_review",
                    confidence=0.6,
                    rule_chain=rule_chain,
                )

        # --- Step 5: case_by_case (sourced) → requires_review ---
        if compat is not None:
            status = compat["compat_status"]
            inferred_only = compat["inferred_only"]
            if status == "case_by_case" and inferred_only == 0:
                return StackVerdict(
                    program_a=a,
                    program_b=b,
                    verdict="requires_review",
                    confidence=0.7,
                    rule_chain=rule_chain,
                )
            # Authoritative compatible / incompatible already returned in
            # step 1; we only reach here for heuristic rows or sourced
            # case_by_case overridden by no exclusion rule.
            if inferred_only == 0 and status == "compatible":
                # Defensive: this shouldn't happen because step 1 returned,
                # but cover it for robustness.
                return StackVerdict(
                    program_a=a,
                    program_b=b,
                    verdict="compatible",
                    confidence=1.0,
                    rule_chain=rule_chain,
                )
            # Heuristic-only row → soft signal. Surface as compatible /
            # incompatible at low confidence so callers can see the
            # heuristic verdict without trusting it.
            if inferred_only == 1 and status in ("compatible", "incompatible"):
                return StackVerdict(
                    program_a=a,
                    program_b=b,
                    verdict=status,
                    confidence=0.3,
                    rule_chain=rule_chain,
                )
            if inferred_only == 1 and status == "case_by_case":
                return StackVerdict(
                    program_a=a,
                    program_b=b,
                    verdict="requires_review",
                    confidence=0.3,
                    rule_chain=rule_chain,
                )

        # --- Step 6: nothing found ---
        rule_chain.append(
            {
                "source": "default",
                "rule_text": (
                    "am_compat_matrix にも exclusion_rules にも該当 row が "
                    "ありません。出典不足のため判定不能。"
                ),
                "weight": 0.0,
            }
        )
        return StackVerdict(
            program_a=a,
            program_b=b,
            verdict="unknown",
            confidence=0.0,
            rule_chain=rule_chain,
        )

    def check_stack(self, program_ids: list[str]) -> StackResult:
        """Evaluate every C(N, 2) pair for a list of program ids.

        ``all_pairs_status`` is the strictest verdict observed across all
        pairs, where ``incompatible > requires_review > unknown > compatible``.
        Empty / single-item input returns ``unknown`` (nothing to stack).
        """
        ids = [str(p).strip() for p in program_ids if p and str(p).strip()]
        # Preserve order while removing dups so the caller sees their
        # original ordering in the result envelope.
        deduped: list[str] = []
        seen: set[str] = set()
        for p in ids:
            if p in seen:
                continue
            seen.add(p)
            deduped.append(p)

        if len(deduped) < 2:
            return StackResult(
                program_ids=deduped,
                all_pairs_status="unknown",
                pairs=[],
                blockers=[],
                warnings=[
                    {
                        "code": "insufficient_input",
                        "message": (
                            "stack 判定には少なくとも 2 件の program_id が必要です。"
                        ),
                    }
                ],
            )

        pairs_out: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        worst = "compatible"

        for a, b in itertools.combinations(deduped, 2):
            verdict = self.check_pair(a, b)
            entry = verdict.to_dict()
            pairs_out.append(entry)

            if verdict.verdict == "incompatible":
                blockers.append(
                    {
                        "program_a": a,
                        "program_b": b,
                        "rule_chain": entry["rule_chain"],
                    }
                )
            elif verdict.verdict == "requires_review":
                warnings.append(
                    {
                        "program_a": a,
                        "program_b": b,
                        "rule_chain": entry["rule_chain"],
                    }
                )

            if (
                _VERDICT_STRICTNESS[verdict.verdict]
                > _VERDICT_STRICTNESS[worst]
            ):
                worst = verdict.verdict

        # Cast through Verdict literal for type safety.
        all_pairs_status: Verdict
        if worst == "incompatible":
            all_pairs_status = "incompatible"
        elif worst == "requires_review":
            all_pairs_status = "requires_review"
        elif worst == "unknown":
            all_pairs_status = "unknown"
        else:
            all_pairs_status = "compatible"

        return StackResult(
            program_ids=deduped,
            all_pairs_status=all_pairs_status,
            pairs=pairs_out,
            blockers=blockers,
            warnings=warnings,
        )


__all__ = [
    "FundingStackChecker",
    "StackResult",
    "StackVerdict",
    "Verdict",
]
