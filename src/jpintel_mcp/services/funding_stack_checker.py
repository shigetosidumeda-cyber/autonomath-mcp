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
   の場合は確定せず、3. 以降のフォールバックを継続する。特に
   ``inferred_only=1`` かつ ``source_url`` なしの ``incompatible`` は
   hard blocker ではなく、``requires_review`` として一次資料確認へ回す。

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
NextAction = dict[str, Any]


_VERDICT_STRICTNESS: dict[str, int] = {
    "incompatible": 3,
    "requires_review": 2,
    "unknown": 1,
    "compatible": 0,
}


_NEXT_ACTION_IDS_BY_VERDICT: dict[Verdict, tuple[str, ...]] = {
    "incompatible": (
        "same_expense_check",
        "split_cost_basis",
        "choose_alternative_bundle",
        "verify_primary_rule",
    ),
    "requires_review": (
        "contact_program_office",
        "confirm_prerequisite_certification",
        "separate_expense_categories",
    ),
    "unknown": (
        "fetch_primary_source",
        "mark_unknown_not_safe",
        "add_manual_review",
    ),
    "compatible": (
        "keep_evidence",
        "retain_cost_allocation_docs",
    ),
}


_HEURISTIC_INCOMPATIBLE_NEXT_ACTION_IDS: tuple[str, ...] = (
    "verify_inferred_incompatibility",
    "contact_program_office",
    "add_manual_review",
)


_NEXT_ACTION_DETAILS: dict[str, dict[str, Any]] = {
    "same_expense_check": {
        "label_ja": "同一経費・同一資産の重複を点検する",
        "detail_ja": (
            "両制度の申請書、見積書、発注書、請求書、支払証憑を突合し、"
            "同じ経費・設備・役務を二重に補助対象へ入れていないか確認してください。"
        ),
        "reason": (
            "incompatible 判定では、同一経費の重複受給または一括併用禁止に"
            "該当する可能性が最優先の確認事項です。"
        ),
        "source_fields": (
            "verdict",
            "confidence",
            "rule_chain[].source",
            "rule_chain[].rule_text",
        ),
    },
    "split_cost_basis": {
        "label_ja": "経費分離の根拠資料を作る",
        "detail_ja": (
            "制度ごとに対象経費、事業範囲、支払時期、証憑番号を分けた"
            "配賦表を作成し、後日監査で説明できる形にしてください。"
        ),
        "reason": (
            "併用不可または要確認の組合せでも、経費が明確に分かれる場合は"
            "個別確認の余地があるためです。"
        ),
        "source_fields": (
            "program_a",
            "program_b",
            "rule_chain[].rule_text",
            "rule_chain[].source_urls",
        ),
    },
    "choose_alternative_bundle": {
        "label_ja": "代替の制度組合せを検討する",
        "detail_ja": (
            "blocker になった pair を外し、同じ資金使途を満たす別制度や"
            "申請順序に置き換えられないか比較してください。"
        ),
        "reason": (
            "1 つでも incompatible pair があると stack 全体の実行可能性が"
            "下がるため、早い段階で代替 bundle を用意する必要があります。"
        ),
        "source_fields": (
            "all_pairs_status",
            "blockers[].program_a",
            "blockers[].program_b",
            "blockers[].rule_chain",
        ),
    },
    "verify_primary_rule": {
        "label_ja": "一次資料の禁止条項を確認する",
        "detail_ja": (
            "公募要領、交付規程、重複受給禁止条項、適正化法 17 条の"
            "該当箇所を確認し、判定根拠の URL と確認日を残してください。"
        ),
        "reason": (
            "本エンジンは curated corpus の照合であり、公募回ごとの細則差や"
            "改正を取りこぼす可能性があるためです。"
        ),
        "source_fields": (
            "rule_chain[].source_url",
            "rule_chain[].source_urls",
            "rule_chain[].rule_text",
        ),
    },
    "verify_inferred_incompatibility": {
        "label_ja": "推定判定の一次資料を確認する",
        "detail_ja": (
            "source_url のない heuristic incompatible です。公募要領、交付規程、"
            "FAQ、重複受給禁止条項を確認し、禁止根拠が見つかるまでは"
            "hard blocker として扱わないでください。"
        ),
        "reason": (
            "inferred_only=1 の推定は明示的な併用禁止根拠ではなく、"
            "制度事務局または一次資料で確認すべきレビュー対象だからです。"
        ),
        "source_fields": (
            "rule_chain[].compat_status",
            "rule_chain[].inferred_only",
            "rule_chain[].evidence_level",
            "rule_chain[].source_url",
            "hard_blocker",
        ),
    },
    "contact_program_office": {
        "label_ja": "制度事務局へ併用条件を照会する",
        "detail_ja": (
            "対象経費、申請年度、採択・交付決定の順序、他制度併用の有無を"
            "具体的に示して、事務局へ確認してください。"
        ),
        "reason": (
            "requires_review 判定は条件付き併用や前提認定の解釈が残っており、"
            "機械判定だけで許可扱いにできないためです。"
        ),
        "source_fields": (
            "verdict",
            "confidence",
            "warnings[].rule_chain",
            "rule_chain[].note",
        ),
    },
    "confirm_prerequisite_certification": {
        "label_ja": "前提認定・採択順序を確認する",
        "detail_ja": (
            "片方の制度がもう一方の認定、採択、交付決定を前提にしていないか、"
            "必要な取得順序と証明書類を確認してください。"
        ),
        "reason": (
            "前提 chain は併用可否そのものではなく、取得済みかどうかで結論が変わる条件だからです。"
        ),
        "source_fields": (
            "rule_chain[].kind",
            "rule_chain[].note",
            "rule_chain[].rule_text",
            "rule_chain[].source_urls",
        ),
    },
    "separate_expense_categories": {
        "label_ja": "対象経費区分と事業範囲を分ける",
        "detail_ja": (
            "設備費、外注費、ソフトウェア費などの区分ごとに、どちらの制度で"
            "申請するかを明確化し、重複しない事業範囲に整理してください。"
        ),
        "reason": (
            "条件付き併用では、経費区分と事業範囲が分離できるかが事務局確認の中心になるためです。"
        ),
        "source_fields": (
            "program_a",
            "program_b",
            "rule_chain[].rule_text",
        ),
    },
    "fetch_primary_source": {
        "label_ja": "公募要領・交付規程を取得する",
        "detail_ja": (
            "両制度の最新の公募要領、交付規程、FAQ を取得し、他制度併用・"
            "重複受給・対象経費の条項を確認してください。"
        ),
        "reason": (
            "unknown 判定は corpus に十分な根拠がない状態であり、安全な併用可とは扱えないためです。"
        ),
        "source_fields": (
            "verdict",
            "confidence",
            "rule_chain[].source",
            "rule_chain[].rule_text",
        ),
    },
    "mark_unknown_not_safe": {
        "label_ja": "判定不能を安全扱いにしない",
        "detail_ja": (
            "社内メモや顧客説明では「併用可」ではなく「出典不足で未確定」と"
            "明記し、申請前チェックリストに残してください。"
        ),
        "reason": (
            "データ未収録は許可根拠ではなく、後から禁止条項が見つかるリスクがあるためです。"
        ),
        "source_fields": (
            "verdict",
            "confidence",
            "rule_chain[].source",
        ),
    },
    "add_manual_review": {
        "label_ja": "専門家または担当者レビューに回す",
        "detail_ja": (
            "税理士、行政書士、中小企業診断士、または制度担当者に、"
            "資金使途と経費一覧を添えて確認依頼してください。"
        ),
        "reason": (
            "本判定は税務代理・申請代理の代替ではなく、最終判断には人手確認が必要なためです。"
        ),
        "source_fields": (
            "_disclaimer",
            "rule_chain",
            "warnings",
        ),
    },
    "keep_evidence": {
        "label_ja": "併用可の根拠を保存する",
        "detail_ja": (
            "compatible 判定の rule_chain、一次資料 URL、確認日、対象公募回を"
            "申請フォルダに保存してください。"
        ),
        "reason": ("併用可でも後日の照会や監査で、判断時点の根拠を提示できる必要があるためです。"),
        "source_fields": (
            "verdict",
            "confidence",
            "rule_chain[].source_url",
            "rule_chain[].rule_text",
        ),
    },
    "retain_cost_allocation_docs": {
        "label_ja": "経費配賦資料を保管する",
        "detail_ja": (
            "制度ごとの対象経費、支払証憑、成果物、事業期間が重複しないことを"
            "示す配賦表と証憑一式を保管してください。"
        ),
        "reason": (
            "併用可能な組合せでも、同一経費の二重計上は別途問題になる可能性があるためです。"
        ),
        "source_fields": (
            "program_a",
            "program_b",
            "rule_chain[].rule_text",
        ),
    },
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


def _next_action(action_id: str) -> NextAction:
    detail = _NEXT_ACTION_DETAILS[action_id]
    return {
        "action_id": action_id,
        "label_ja": detail["label_ja"],
        "detail_ja": detail["detail_ja"],
        "reason": detail["reason"],
        "source_fields": list(detail["source_fields"]),
    }


def _next_actions_for_verdict(verdict: Verdict) -> list[NextAction]:
    return [_next_action(action_id) for action_id in _NEXT_ACTION_IDS_BY_VERDICT[verdict]]


def _next_actions_for_ids(action_ids: tuple[str, ...]) -> list[NextAction]:
    return [_next_action(action_id) for action_id in action_ids]


def _dedupe_next_actions(action_groups: list[list[NextAction]]) -> list[NextAction]:
    actions: list[NextAction] = []
    seen: set[str] = set()
    for group in action_groups:
        for action in group:
            action_id = str(action.get("action_id") or "")
            if not action_id or action_id in seen:
                continue
            seen.add(action_id)
            actions.append(dict(action))
    return actions


def _make_stack_verdict(
    *,
    program_a: str,
    program_b: str,
    verdict: Verdict,
    confidence: float,
    rule_chain: list[dict[str, Any]],
    next_action_ids: tuple[str, ...] | None = None,
) -> StackVerdict:
    return StackVerdict(
        program_a=program_a,
        program_b=program_b,
        verdict=verdict,
        confidence=confidence,
        rule_chain=list(rule_chain),
        next_actions=(
            _next_actions_for_ids(next_action_ids)
            if next_action_ids is not None
            else _next_actions_for_verdict(verdict)
        ),
        hard_blocker=any(step.get("hard_blocker") is True for step in rule_chain),
    )


def _aggregate_stack_next_actions(pairs: list[dict[str, Any]]) -> list[NextAction]:
    action_groups: list[list[NextAction]] = []
    for status in ("incompatible", "requires_review", "unknown"):
        for pair in pairs:
            if pair.get("verdict") == status:
                action_groups.append(list(pair.get("next_actions", [])))
    if action_groups:
        return _dedupe_next_actions(action_groups)

    return _dedupe_next_actions(
        [
            list(pair.get("next_actions", []))
            for pair in pairs
            if pair.get("verdict") == "compatible"
        ]
    )


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
    next_actions: list[NextAction] = field(default_factory=list)
    hard_blocker: bool = False
    disclaimer: str = _DISCLAIMER_PAIR

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_a": self.program_a,
            "program_b": self.program_b,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rule_chain": list(self.rule_chain),
            "next_actions": list(self.next_actions),
            "hard_blocker": self.hard_blocker,
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
    next_actions: list[NextAction] = field(default_factory=list)
    disclaimer: str = _DISCLAIMER_STACK

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_ids": list(self.program_ids),
            "all_pairs_status": self.all_pairs_status,
            "pairs": list(self.pairs),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "next_actions": list(self.next_actions),
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
            has_uid = "program_a_uid" in cols and "program_b_uid" in cols
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
                    "program_a_uid": (row["program_a_uid"] if "program_a_uid" in keys else None),
                    "program_b_uid": (row["program_b_uid"] if "program_b_uid" in keys else None),
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
        logger.debug("loaded exclusion_rules: %d rows", len(self._exclusion_rules))

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
            return _make_stack_verdict(
                program_a=program_a or "",
                program_b=program_b or "",
                verdict="unknown",
                confidence=0.0,
                rule_chain=[
                    {
                        "source": "input_validation",
                        "rule_text": "program_a / program_b は非空文字列が必須です。",
                        "weight": 0.0,
                        "evidence_level": "input_validation",
                        "hard_blocker": False,
                    }
                ],
            )
        if a == b:
            return _make_stack_verdict(
                program_a=a,
                program_b=b,
                verdict="incompatible",
                confidence=1.0,
                rule_chain=[
                    {
                        "source": "input_validation",
                        "rule_text": ("同一 program_id を併用することはできません (self-pair)。"),
                        "weight": 1.0,
                        "evidence_level": "input_validation",
                        "hard_blocker": True,
                    }
                ],
            )

        rule_chain: list[dict[str, Any]] = []

        # --- Step 1-2: am_compat_matrix lookup ---
        compat = self._compat_index.get(self._pair_key(a, b))
        if compat is not None:
            status = compat["compat_status"]
            inferred_only = compat["inferred_only"]
            source_url = compat.get("source_url")
            has_source_url = bool(str(source_url or "").strip())
            evidence_level = (
                "authoritative"
                if inferred_only == 0
                else "sourced_heuristic"
                if has_source_url
                else "heuristic"
            )
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
                "source_url": source_url,
                "evidence_level": evidence_level,
                "hard_blocker": (
                    status == "incompatible" and (inferred_only == 0 or has_source_url)
                ),
            }
            rule_chain.append(entry)

            # 1. Authoritative compatible / incompatible — terminal.
            if inferred_only == 0 and status in ("compatible", "incompatible"):
                return _make_stack_verdict(
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
                        "evidence_level": "explicit_rule",
                        "hard_blocker": True,
                    }
                )
                return _make_stack_verdict(
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
                        "evidence_level": "explicit_rule",
                        "hard_blocker": False,
                    }
                )
                return _make_stack_verdict(
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
                return _make_stack_verdict(
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
                return _make_stack_verdict(
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
                if status == "incompatible" and not bool(
                    str(compat.get("source_url") or "").strip()
                ):
                    rule_chain[-1]["note"] = (
                        "source_url のない heuristic incompatible です。"
                        "明示的な併用禁止根拠が確認できるまでは hard blocker "
                        "ではなく reviewer 確認として扱います。"
                    )
                    return _make_stack_verdict(
                        program_a=a,
                        program_b=b,
                        verdict="requires_review",
                        confidence=0.3,
                        rule_chain=rule_chain,
                        next_action_ids=_HEURISTIC_INCOMPATIBLE_NEXT_ACTION_IDS,
                    )
                return _make_stack_verdict(
                    program_a=a,
                    program_b=b,
                    verdict=status,
                    confidence=0.3,
                    rule_chain=rule_chain,
                )
            if inferred_only == 1 and status == "case_by_case":
                return _make_stack_verdict(
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
                "evidence_level": "none",
                "hard_blocker": False,
            }
        )
        return _make_stack_verdict(
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
                        "message": ("stack 判定には少なくとも 2 件の program_id が必要です。"),
                    }
                ],
                next_actions=_next_actions_for_verdict("unknown"),
            )

        pairs_out: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        worst = "compatible"

        for a, b in itertools.combinations(deduped, 2):
            verdict = self.check_pair(a, b)
            entry = verdict.to_dict()
            pairs_out.append(entry)

            is_soft_incompatible = (
                verdict.verdict == "incompatible" and entry.get("hard_blocker") is False
            )
            effective_verdict: Verdict = (
                "requires_review" if is_soft_incompatible else verdict.verdict
            )

            if verdict.verdict == "incompatible" and not is_soft_incompatible:
                blockers.append(
                    {
                        "program_a": a,
                        "program_b": b,
                        "rule_chain": entry["rule_chain"],
                        "next_actions": entry["next_actions"],
                        "hard_blocker": entry["hard_blocker"],
                    }
                )
            elif verdict.verdict == "requires_review" or is_soft_incompatible:
                warnings.append(
                    {
                        "program_a": a,
                        "program_b": b,
                        "rule_chain": entry["rule_chain"],
                        "next_actions": entry["next_actions"],
                        "hard_blocker": entry["hard_blocker"],
                    }
                )

            if _VERDICT_STRICTNESS[effective_verdict] > _VERDICT_STRICTNESS[worst]:
                worst = effective_verdict

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
            next_actions=_aggregate_stack_next_actions(pairs_out),
        )


__all__ = [
    "FundingStackChecker",
    "StackResult",
    "StackVerdict",
    "Verdict",
]
