"""LINE bot conversation flow — pure deterministic state machine.

Five-step quick-reply flow that captures the four facts needed to call
``/v1/programs/search`` with a usable filter set, then renders the top 5
matches as a LINE Flex carousel-shaped message:

    Step 0 (idle)     →  user sends any text  →  reply welcome + 業種 quickreply
    Step 1 (industry) →  user picks 業種       →  reply 都道府県 quickreply
    Step 2 (prefecture)→ user picks 都道府県    →  reply 従業員数 quickreply
    Step 3 (employees) → user picks 従業員数    →  reply 年商 quickreply
    Step 4 (revenue)  →  user picks 年商       →  query DB, reply top 5
    Step 5 (results)  →  user sends any text  →  reset to step 1

There is **NO LLM call** anywhere in this module — the flow is fully
determined by the user's button choice and a single SQLite SELECT
against the `programs` table. The state machine intentionally has no
free-text path because:

    1. Free text would invite us to call an LLM, which violates the
       project's "subagent inference, no API call" rule for this surface.
    2. Free text from LINE users frequently arrives in unstable
       transliterations (郡部 vs 都市部, full-width vs half-width digits)
       which would produce mismatches against the programs.prefecture
       column. Restricting input to the 47-prefecture quick-reply
       eliminates that whole class of bug.

Persistence
-----------
The webhook handler reads/writes ``line_users.current_flow_state_json``
which is a small JSON document of the form:

    {"step": "<one of STEP_NAMES>", "answers": {<accumulated facts>}}

This module exposes:

    * ``FLOW_STEPS``        — ordered list of step names
    * ``QUICK_REPLY_BUILDERS`` — step → list[QuickReplyItem]
    * ``advance(state, choice)`` — pure function: (current state, chosen
      label) → (next state, reply payload). Receives DB connection only
      at the final step (results) and even then only does a single
      parameterised SELECT — no transactions, no writes.

Everything in this file is unit-testable without LINE / FastAPI / Stripe
ever being involved; the webhook handler in ``api/line_webhook.py`` glues
this state machine to LINE-specific I/O.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Step identifiers (stable across releases — persisted in line_users.current_
# flow_state_json so renaming requires a migration of in-flight users).
# ---------------------------------------------------------------------------

StepName = Literal["industry", "prefecture", "employees", "revenue", "results"]

FLOW_STEPS: tuple[StepName, ...] = (
    "industry",
    "prefecture",
    "employees",
    "revenue",
    "results",
)


class FlowState(TypedDict, total=False):
    """Persisted conversation state. Stored as JSON in `line_users`."""

    step: StepName
    answers: dict[str, str]


# ---------------------------------------------------------------------------
# Step 1: 業種 (7 buttons, one quickreply batch — fits in LINE's 13-button cap)
# ---------------------------------------------------------------------------
# Mapping: display label → programs.target_types tag (best-effort overlap).
# We intentionally use very coarse buckets because the programs corpus's
# target_types_json is sparse outside agriculture; coarse buckets keep
# coverage high and prevent the user from staring at "0 件" because their
# 業種 happens to be an unmapped sub-category. Falls back to "ALL" → no
# target_type filter for "その他".
INDUSTRY_CHOICES: tuple[tuple[str, str | None], ...] = (
    ("建設業", "建設業"),
    ("製造業", "製造業"),
    ("IT・情報通信業", "情報通信業"),
    ("小売業", "小売業"),
    ("サービス業", "サービス業"),
    ("農業", "農業"),
    ("その他", None),
)


# ---------------------------------------------------------------------------
# Step 2: 都道府県 — 47 prefectures + "全国" sentinel.
# ---------------------------------------------------------------------------
# LINE quickreply caps at 13 items per send. We split the 48 (+全国) into
# 4 batches and the webhook handler concatenates them into 4 successive
# bubbles. Region order: 北→南 to match the user's mental model.
PREFECTURE_BATCHES: tuple[tuple[str, ...], ...] = (
    # Batch A: 北海道・東北・関東 (12)
    ("全国", "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県",
     "福島県", "茨城県", "栃木県", "群馬県", "埼玉県"),
    # Batch B: 関東続き・中部 (12)
    ("千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県",
     "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県"),
    # Batch C: 近畿・中国 (12)
    ("三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県",
     "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県"),
    # Batch D: 四国・九州・沖縄 (12)
    ("徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県",
     "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"),
)
ALL_PREFECTURES: tuple[str, ...] = tuple(p for batch in PREFECTURE_BATCHES for p in batch)


# ---------------------------------------------------------------------------
# Step 3: 従業員数 (6 buckets; the band → an integer ceiling for SQL filtering).
# ---------------------------------------------------------------------------
# We map labels → upper-bound (inclusive) so the SQL filter is "show
# programs whose target SME size is ≤ user's bucket OR has no size
# constraint". The ceiling is a coarse classification, not a literal cap.
EMPLOYEE_CHOICES: tuple[tuple[str, int], ...] = (
    ("〜5人", 5),
    ("〜20人", 20),
    ("〜50人", 50),
    ("〜100人", 100),
    ("〜300人", 300),
    ("300人超", 9999),
)


# ---------------------------------------------------------------------------
# Step 4: 年商 (5 bands; the band → an integer ceiling 万円 unit).
# ---------------------------------------------------------------------------
# 万円 unit because that matches programs.amount_max_man_yen and lets us
# do "amount_max ≥ <revenue bucket lower bound>" without unit conversion.
REVENUE_CHOICES: tuple[tuple[str, int], ...] = (
    ("〜1億円", 10000),     # 1億円 = 10,000 万円
    ("〜3億円", 30000),
    ("〜10億円", 100000),
    ("〜30億円", 300000),
    ("30億円超", 9999999),
)


# ---------------------------------------------------------------------------
# Quick-reply builders — return LINE Messaging API quickReply.items shape.
# ---------------------------------------------------------------------------


def _quickreply_action(label: str) -> dict[str, Any]:
    """Build one quickReply item using the message action shape.

    Why message action (not postback)
    --------------------------------
    The user's reply re-enters our webhook as a normal text message
    carrying the label string. We deduplicate against the FlowState in
    persisted user record, so postback data is unnecessary and adds an
    extra mapping table to maintain. The trade-off: if a user types the
    label by hand, the same code path runs — which is fine, the label
    set is canonical.
    """
    return {
        "type": "action",
        "action": {
            "type": "message",
            "label": label[:20],   # LINE caps quickreply label at 20 chars
            "text": label,
        },
    }


def industry_quickreply() -> list[dict[str, Any]]:
    """Step 1 quickreply items."""
    return [_quickreply_action(label) for label, _ in INDUSTRY_CHOICES]


def prefecture_quickreply(batch_index: int) -> list[dict[str, Any]]:
    """Step 2 — 4 bubbles, batch_index ∈ {0,1,2,3}."""
    if not 0 <= batch_index < len(PREFECTURE_BATCHES):
        raise ValueError(f"prefecture batch_index out of range: {batch_index}")
    return [_quickreply_action(p) for p in PREFECTURE_BATCHES[batch_index]]


def employee_quickreply() -> list[dict[str, Any]]:
    """Step 3 quickreply items."""
    return [_quickreply_action(label) for label, _ in EMPLOYEE_CHOICES]


def revenue_quickreply() -> list[dict[str, Any]]:
    """Step 4 quickreply items."""
    return [_quickreply_action(label) for label, _ in REVENUE_CHOICES]


# ---------------------------------------------------------------------------
# Welcome / reset / quota messages
# ---------------------------------------------------------------------------

WELCOME_TEXT = (
    "こんにちは。AutonoMath LINE 制度検索 Bot です。\n"
    "4 つの質問にお答えいただくと、適用可能な公的支援制度を上位 5 件まで"
    "ご案内します。\n"
    "まず、貴社の業種をお選びください。"
)

RESULTS_INTRO_TEMPLATE = (
    "以下の {count} 件の制度が条件に合致しました。"
    "各制度名のリンクから一次情報元 (省庁・自治体) をご確認ください。\n"
    "本サービスは情報提供のみで、個別の適用判定は行いません。"
)

NO_RESULTS_TEXT = (
    "条件に合致する制度が見つかりませんでした。"
    "条件を変更して再度お試しください。"
)

QUOTA_EXCEEDED_TEXT = (
    "今月の無料利用枠 (50 件) を超過しました。"
    "翌月初 (JST 0:00) にリセットされます。\n"
    "API 連携をご利用の方は親 API キーで課金されます。"
)


# ---------------------------------------------------------------------------
# DB query — pure SELECT, no writes.
# ---------------------------------------------------------------------------


def _build_program_query(
    *,
    industry_tag: str | None,
    prefecture: str,
    employee_ceiling: int,  # noqa: ARG001 — column not present in v1 schema
    revenue_ceiling_man: int,
) -> tuple[str, list[Any]]:
    """Compose a parameterised SELECT against `programs` for the final step.

    Filters applied:
      * `tier IN ('S','A','B','C')` — quarantine tier X always excluded
      * `excluded = 0`
      * prefecture: exact match OR row's prefecture is NULL/'全国' (国の制度)
      * amount_max_man_yen ≥ a fraction of revenue (heuristic: programs
        whose ceiling is at least 0.1% of revenue are unlikely to be
        meaningful — this is a rough reverse-screen so a 30億円 company
        does not get a ¥10万円 program at the top).
      * industry: when the user picked a mapped 業種, OR-match on
        target_types_json LIKE '%<tag>%'. "その他" → no industry filter.

    Order: tier S→A→B→C, then amount_max desc.
    Limit: 5.

    employee_ceiling is captured but not currently filtered on because
    `programs` has no employee column in the live schema. Held in the
    signature so adding the filter later is a one-line change.
    """
    sql = [
        "SELECT unified_id, primary_name, prefecture, authority_name, ",
        "       amount_max_man_yen, official_url, source_url, tier ",
        "FROM programs ",
        "WHERE excluded = 0 AND tier IN ('S','A','B','C') ",
    ]
    params: list[Any] = []

    # Prefecture filter: exact match or 全国 (NULL or '全国' values).
    if prefecture == "全国":
        # User picked 全国 → only national programs.
        sql.append("AND (prefecture IS NULL OR prefecture = '全国' OR prefecture = '') ")
    else:
        sql.append(
            "AND (prefecture = ? OR prefecture IS NULL OR prefecture = '全国' OR prefecture = '') "
        )
        params.append(prefecture)

    # Industry filter: only when mapped. Conservative LIKE on target_types_json.
    if industry_tag:
        sql.append("AND (target_types_json LIKE ? OR target_types_json IS NULL) ")
        params.append(f"%{industry_tag}%")

    # Revenue heuristic — drop programs whose published max is laughably
    # small relative to the company. 0.1% threshold = ~30,000 万円 for a
    # 30億 company; smaller companies are unaffected because we OR-include
    # rows with NULL amount_max_man_yen (most programs do not publish a
    # max).
    threshold_man = max(1, revenue_ceiling_man // 1000)
    sql.append("AND (amount_max_man_yen IS NULL OR amount_max_man_yen >= ?) ")
    params.append(threshold_man)

    sql.append(
        "ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END, "
        "amount_max_man_yen DESC NULLS LAST "
        "LIMIT 5"
    )
    return ("".join(sql), params)


def query_top_programs(
    conn: sqlite3.Connection,
    *,
    industry_tag: str | None,
    prefecture: str,
    employee_ceiling: int,
    revenue_ceiling_man: int,
) -> list[dict[str, Any]]:
    """Return up to 5 program dicts for the final reply step.

    Pure read against the `programs` table (jpintel.db). Returns an empty
    list on any DB error so the LINE webhook can degrade to NO_RESULTS_TEXT
    rather than 500.
    """
    sql, params = _build_program_query(
        industry_tag=industry_tag,
        prefecture=prefecture,
        employee_ceiling=employee_ceiling,
        revenue_ceiling_man=revenue_ceiling_man,
    )
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    except sqlite3.Error:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        # Sqlite3.Row supports indexed and key access.
        d = {
            "unified_id": r["unified_id"],
            "primary_name": r["primary_name"],
            "prefecture": r["prefecture"] or "全国",
            "authority_name": r["authority_name"] or "",
            "amount_max_man_yen": r["amount_max_man_yen"],
            "url": r["official_url"] or r["source_url"] or "",
            "tier": r["tier"],
        }
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Render — turn a results list into a LINE-shaped reply payload.
# ---------------------------------------------------------------------------


def _format_amount(amount_max_man_yen: float | None) -> str:
    """Render the amount column for one program line."""
    if amount_max_man_yen is None:
        return "金額: 公表値なし"
    return f"上限 {int(amount_max_man_yen):,} 万円"


def render_results_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn the SELECT result into LINE reply messages.

    For simplicity (and to keep the carousel under LINE's payload size
    cap on small messages) we send one text message containing the intro
    + all 5 entries as bullet points, plus the closing reset hint. A
    Flex carousel would render prettier but adds 5KB per bubble; the
    text shape ships now and the carousel is a follow-on.
    """
    if not rows:
        return [{"type": "text", "text": NO_RESULTS_TEXT}]
    lines: list[str] = [RESULTS_INTRO_TEMPLATE.format(count=len(rows)), ""]
    for i, r in enumerate(rows, start=1):
        amt = _format_amount(r.get("amount_max_man_yen"))
        url = r.get("url") or ""
        name = r.get("primary_name") or "(無題)"
        pref = r.get("prefecture") or "全国"
        auth = r.get("authority_name") or ""
        head = f"{i}. {name} [{pref}]"
        body = f"   {auth} / {amt}"
        if url:
            body += f"\n   {url}"
        lines.append(head)
        lines.append(body)
        lines.append("")
    lines.append("もう一度検索する場合は何かメッセージを送信してください。")
    return [{"type": "text", "text": "\n".join(lines).rstrip()}]


# ---------------------------------------------------------------------------
# advance() — the state-machine driver.
# ---------------------------------------------------------------------------


def advance(
    state: FlowState | None,
    user_text: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> tuple[FlowState, list[dict[str, Any]]]:
    """Compute the next state + reply messages for an inbound user text.

    Pure function except for the SQLite SELECT at the final step. The
    caller (api/line_webhook.py) is responsible for:
      * persisting the returned `FlowState` into line_users.current_flow_state_json
      * shipping the returned `messages` to the LINE reply endpoint
      * billing the round-trip (¥3 paid / quota for free)

    Args:
        state: prior persisted FlowState, or None for new users / reset.
        user_text: the raw text the user typed (we trust LINE to deliver
            it un-mutated; see api/line_webhook.py for `len() < 64` guard).
        conn: only used at step=revenue→results to query programs.

    Returns:
        (next_state, messages). messages is a list of LINE reply objects;
        the webhook handler simply forwards them to LINE's reply API.
    """
    user_text = (user_text or "").strip()

    # Idle / reset: any text starts the flow over with the welcome prompt.
    current_step: StepName | None = state.get("step") if state else None
    answers: dict[str, str] = dict(state.get("answers", {})) if state else {}

    # Step 0 → step 1 (industry quickreply).
    if current_step is None or current_step == "results":
        return (
            {"step": "industry", "answers": {}},
            [
                {
                    "type": "text",
                    "text": WELCOME_TEXT,
                    "quickReply": {"items": industry_quickreply()},
                }
            ],
        )

    # Step 1 → step 2 (prefecture).
    if current_step == "industry":
        # Validate the label. Unknown text → re-prompt without advancing.
        valid_labels = [label for label, _ in INDUSTRY_CHOICES]
        if user_text not in valid_labels:
            return (
                {"step": "industry", "answers": answers},
                [
                    {
                        "type": "text",
                        "text": "業種をボタンからお選びください。",
                        "quickReply": {"items": industry_quickreply()},
                    }
                ],
            )
        answers["industry"] = user_text
        # Send 4 bubbles (one per prefecture batch). LINE renders quickreply
        # only on the LAST message in a reply batch — so 都道府県 batches
        # 0..2 carry no quickreply and only batch 3 does.
        msgs: list[dict[str, Any]] = [
            {"type": "text", "text": "次に都道府県を選んでください (1/4)。",
             "quickReply": {"items": prefecture_quickreply(0)}},
        ]
        return ({"step": "prefecture", "answers": answers}, msgs)

    # Step 2 → step 3 (employees).
    if current_step == "prefecture":
        if user_text not in ALL_PREFECTURES:
            # Helpful failure: re-emit the next batch of prefectures.
            # We reset to batch 0 — keeps it simple, LINE will let user scroll.
            return (
                {"step": "prefecture", "answers": answers},
                [
                    {
                        "type": "text",
                        "text": "都道府県をボタンからお選びください。",
                        "quickReply": {"items": prefecture_quickreply(0)},
                    }
                ],
            )
        answers["prefecture"] = user_text
        return (
            {"step": "employees", "answers": answers},
            [
                {
                    "type": "text",
                    "text": "従業員数の規模を選んでください。",
                    "quickReply": {"items": employee_quickreply()},
                }
            ],
        )

    # Step 3 → step 4 (revenue).
    if current_step == "employees":
        valid_labels = [label for label, _ in EMPLOYEE_CHOICES]
        if user_text not in valid_labels:
            return (
                {"step": "employees", "answers": answers},
                [
                    {
                        "type": "text",
                        "text": "従業員数をボタンからお選びください。",
                        "quickReply": {"items": employee_quickreply()},
                    }
                ],
            )
        answers["employees"] = user_text
        return (
            {"step": "revenue", "answers": answers},
            [
                {
                    "type": "text",
                    "text": "年商を選んでください。",
                    "quickReply": {"items": revenue_quickreply()},
                }
            ],
        )

    # Step 4 → step 5 (results).
    if current_step == "revenue":
        valid_labels = [label for label, _ in REVENUE_CHOICES]
        if user_text not in valid_labels:
            return (
                {"step": "revenue", "answers": answers},
                [
                    {
                        "type": "text",
                        "text": "年商をボタンからお選びください。",
                        "quickReply": {"items": revenue_quickreply()},
                    }
                ],
            )
        answers["revenue"] = user_text

        # Resolve the human labels to filter values.
        industry_tag: str | None = None
        for label, tag in INDUSTRY_CHOICES:
            if label == answers.get("industry"):
                industry_tag = tag
                break
        prefecture = answers.get("prefecture", "全国")
        employee_ceiling = 9999
        for label, ceil_e in EMPLOYEE_CHOICES:
            if label == answers.get("employees"):
                employee_ceiling = ceil_e
                break
        revenue_ceiling_man = 9999999
        for label, ceil_r in REVENUE_CHOICES:
            if label == answers.get("revenue"):
                revenue_ceiling_man = ceil_r
                break

        if conn is None:
            # Defensive — caller forgot to wire the DB. We still advance
            # so the user does not get stuck, but show no_results.
            return (
                {"step": "results", "answers": answers},
                [{"type": "text", "text": NO_RESULTS_TEXT}],
            )

        rows = query_top_programs(
            conn,
            industry_tag=industry_tag,
            prefecture=prefecture,
            employee_ceiling=employee_ceiling,
            revenue_ceiling_man=revenue_ceiling_man,
        )
        return (
            {"step": "results", "answers": answers},
            render_results_messages(rows),
        )

    # Unknown state → reset. Defensive against migration drift in
    # current_flow_state_json (if we add a new step in v2 and roll back,
    # legacy state values will hit this branch).
    return (
        {"step": "industry", "answers": {}},
        [
            {
                "type": "text",
                "text": WELCOME_TEXT,
                "quickReply": {"items": industry_quickreply()},
            }
        ],
    )


__all__ = [
    "ALL_PREFECTURES",
    "EMPLOYEE_CHOICES",
    "FLOW_STEPS",
    "FlowState",
    "INDUSTRY_CHOICES",
    "NO_RESULTS_TEXT",
    "PREFECTURE_BATCHES",
    "QUOTA_EXCEEDED_TEXT",
    "RESULTS_INTRO_TEMPLATE",
    "REVENUE_CHOICES",
    "WELCOME_TEXT",
    "advance",
    "employee_quickreply",
    "industry_quickreply",
    "prefecture_quickreply",
    "query_top_programs",
    "render_results_messages",
    "revenue_quickreply",
]
