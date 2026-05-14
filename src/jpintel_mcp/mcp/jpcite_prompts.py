"""jpcite MCP prompts (Wave 15 A2) — 3 recurring agent workflows.

Exposes 3 prompt templates under the user-facing jpcite brand so an MCP
client can request a single ``prompts/get`` and obtain a pre-orchestrated
multi-tool playbook. These templates mirror the
``recurring_agent_workflows`` block published in
``site/.well-known/mcp.json`` and bridge it to a runtime MCP capability
the agent can actually invoke.

The 3 workflows
---------------
* ``company_folder_intake``     — 1 社のフォルダ作成
* ``monthly_client_review``     — 顧問先 1 社の月次レビュー
* ``counterparty_dd``           — DD / 監査 prep counterparty risk pack

Design
------
* No LLM calls inside the templates themselves; they return ``messages``
  arrays the client LLM consumes. The templates encode jpcite's expert
  opinion on the right tool order (``previewCost`` first → first paid
  evidence call → fan-out tools).
* Disclaimer envelope (业法 fence) is appended to every template so an
  agent rendering output cannot accidentally cross the §52 / §72 / §1
  fence.
* Wired into FastMCP via ``register_jpcite_prompts(mcp)``. Idempotent
  + tolerant of FastMCP versions without ``.prompt()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class _PromptArg:
    name: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class _JpcitePrompt:
    name: str
    title: str
    description: str
    arguments: tuple[_PromptArg, ...]
    system_message: str
    user_template: str

    def arguments_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "name": a.name,
                "description": a.description,
                "required": a.required,
            }
            for a in self.arguments
        ]

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for arg in self.arguments:
            if arg.name in args:
                out[arg.name] = str(args[arg.name])
            elif arg.required:
                raise ValueError(f"missing required argument: {arg.name}")
        extra = set(args) - {a.name for a in self.arguments}
        if extra:
            raise ValueError(f"unknown argument(s): {sorted(extra)}")
        return out

    def render(self, args: dict[str, Any]) -> dict[str, Any]:
        validated = self.validate(args)
        rendered_user = _substitute(self.user_template, validated)
        return {
            "description": self.description,
            "messages": [
                {
                    "role": "assistant",
                    "content": {"type": "text", "text": self.system_message},
                },
                {
                    "role": "user",
                    "content": {"type": "text", "text": rendered_user},
                },
            ],
        }


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _substitute(template: str, args: dict[str, Any]) -> str:
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in args:
            return str(args[key])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_sub, template)


# ---------------------------------------------------------------------------
# Common disclaimer (差し込み必須)
# ---------------------------------------------------------------------------


_FENCE_FOOTER = (
    "\n\n---\n"
    "**業法 fence (差し込み必須):**\n"
    "- 税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 / 司法書士法 §73 を踏み越えない。\n"
    "- 個別の税務 / 法律 / 申請書面作成 助言は登録 業法資格者へ誘導すること。\n"
    "- 出典 URL (source_url) と取得日 (fetched_at) を必ず提示すること。\n"
    "- jpcite 出力は evidence packet であり, 最終 専門家 判断ではない。\n"
)


_SYSTEM_PREAMBLE = (
    "You are following the jpcite `{name}` recurring agent workflow. Rules:\n"
    "  1. Call `previewCost` FIRST before any paid evidence run.\n"
    "  2. Set `X-API-Key` after the 3 req/day anonymous quota is exhausted.\n"
    "  3. Set `X-Client-Tag: <client_slug>` so per-顧問先 attribution rolls up.\n"
    "  4. Preserve `source_url`, `source_fetched_at`, `corpus_snapshot_id`, "
    "`known_gaps`, `identity_confidence` on every quoted row.\n"
    "  5. Never claim `final_legal_or_tax_judgment`, `audit_complete`, "
    "`credit_safe`, or `subsidy_or_loan_approved`. jpcite is retrieval support.\n"
    "  6. Use `mcp://jpcite/legal/fence.md` as the SOT for 業法 fence wording.\n"
)


def _system_for(name: str) -> str:
    return _SYSTEM_PREAMBLE.replace("{name}", name)


# ---------------------------------------------------------------------------
# 3 templates
# ---------------------------------------------------------------------------


_PROMPTS: tuple[_JpcitePrompt, ...] = (
    _JpcitePrompt(
        name="company_folder_intake",
        title="会社フォルダ Brief intake (previewCost first)",
        description=(
            "1 社の新規フォルダ intake. previewCost → createCompanyPublicBaseline "
            "→ createCompanyFolderBrief → queryEvidencePacket の sequence で "
            "公開ベースライン + brief + evidence packet を生成. Brief preview は 1 billable unit、"
            "Pack workflow は previewCost の実行前見積もり units で確認します。"
        ),
        arguments=(
            _PromptArg(
                "company_houjin_bangou",
                "13-digit 国税庁 法人番号 (チェックディジット含む)",
            ),
            _PromptArg(
                "client_tag",
                "X-Client-Tag header 用の顧問先 slug (例: client-abc, prospect-2026q2)",
            ),
        ),
        system_message=_system_for("company_folder_intake"),
        user_template=(
            "## Target\n"
            "- 法人番号: {company_houjin_bangou}\n"
            "- client_tag: {client_tag}\n\n"
            "## Sequence\n"
            "1. **previewCost** — planned_calls の見積もり units と税込目安を表示し, 続行可否を 1 行で報告.\n"
            "2. **createCompanyPublicBaseline** (first paid call, ¥3/req)\n"
            "   - X-API-Key + X-Client-Tag: {client_tag}\n"
            "   - input: houjin_bangou={company_houjin_bangou}\n"
            "   - 出力 source_url / source_fetched_at / corpus_snapshot_id を保存.\n"
            "3. **createCompanyFolderBrief**\n"
            "   - baseline の identity_confidence + known_gaps を input に, "
            "1 ページ A4 サイズの brief を生成.\n"
            "   - 業種 (JSIC 大分類), 所在都道府県, 法人格, 適格事業者番号 (T 付き) を必ず含める.\n"
            "4. **queryEvidencePacket** ×N (採択 / 行政処分 / 適格事業者 / 法令引用 を順に)\n"
            "   - 各 packet の records 数 / known_gaps / caveats を箇条書きで列挙.\n\n"
            "## Output\n"
            "- markdown table 形式で見積もり内訳 (call_name | estimated_units | cumulative_cost_jpy_inc_tax | source_url 抜粋)\n"
            "- 末尾に handoff_packet (user_goal / source_url / known_gaps / candidate_program_ids / "
            "jurisdiction_or_prefecture) を JSON で同梱.\n"
            f"{_FENCE_FOOTER}"
        ),
    ),
    _JpcitePrompt(
        name="monthly_client_review",
        title="顧問先 月次レビュー (100 req / 月)",
        description=(
            "1 顧問先 × 月 100 req の伴走レビュー. previewCost → queryEvidencePacket "
            "→ prescreenPrograms の sequence で前月差分 + 新規 candidate を抽出. "
            "¥3/req × 100 = ¥330 (税込) / 顧問先 / 月."
        ),
        arguments=(
            _PromptArg(
                "client_tag",
                "顧問先 slug (X-Client-Tag header)",
            ),
            _PromptArg(
                "target_month",
                "対象月 YYYY-MM (例: 2026-05)",
            ),
            _PromptArg(
                "client_profile_summary",
                "顧問先プロファイル 1 行要約 (業種 JSIC + 都道府県 + 規模 + 直近投資計画)",
            ),
        ),
        system_message=_system_for("monthly_client_review"),
        user_template=(
            "## Client\n"
            "- client_tag: {client_tag}\n"
            "- target_month: {target_month}\n"
            "- profile: {client_profile_summary}\n\n"
            "## Sequence\n"
            "1. **previewCost** — 100 req ¥330 を表示し, 続行可否を確認.\n"
            "2. **queryEvidencePacket** (first paid call) ×K\n"
            "   - X-API-Key + X-Client-Tag: {client_tag}\n"
            "   - 前月 ({target_month} 1 ヶ月前) との差分: 新規告示 / 改正 / 採択結果 / 行政処分.\n"
            "   - corpus_snapshot_id を必ず記録 (前月 snapshot と diff 比較する).\n"
            "3. **prescreenPrograms** ×N\n"
            "   - 顧問先 profile に基づく candidate 上位 10. 1 行ずつ:\n"
            "     `program_name | authority | deadline | amount_cap | confidence | source_url`.\n"
            "   - confidence は identity_confidence + eligibility_confidence の 2 軸で.\n\n"
            "## Output\n"
            "- ## 前月差分 (改正 / 採択 / 処分) — markdown table\n"
            "- ## 新規 candidate 上位 10 — markdown table\n"
            "- ## 専門家 handoff 推奨 — どの行が 税理士 / 行政書士 確認必要か明示.\n"
            "- 末尾に corpus_snapshot_id / known_gaps を JSON.\n"
            f"{_FENCE_FOOTER}"
        ),
    ),
    _JpcitePrompt(
        name="counterparty_dd",
        title="M&A / DD / 監査 prep counterparty pack",
        description=(
            "取引先 / 買収候補 1 社の DD prep. previewCost → createCompanyPublicBaseline "
            "→ createCompanyPublicAuditPack → match_advisors の sequence. "
            "47 req ¥155.10 (税込)."
        ),
        arguments=(
            _PromptArg(
                "counterparty_houjin_bangou",
                "取引先 13-digit 法人番号",
            ),
            _PromptArg(
                "deal_context",
                "DD context (例: 株式譲渡 / 事業承継 / 与信再評価 / 取引開始前 KYC)",
            ),
            _PromptArg(
                "client_tag",
                "X-Client-Tag (deal slug)",
            ),
        ),
        system_message=_system_for("counterparty_dd"),
        user_template=(
            "## Target\n"
            "- counterparty_houjin_bangou: {counterparty_houjin_bangou}\n"
            "- deal_context: {deal_context}\n"
            "- client_tag: {client_tag}\n\n"
            "## Sequence\n"
            "1. **previewCost** — 47 req ¥155.10 を表示, 続行可否確認.\n"
            "2. **createCompanyPublicBaseline** (first paid call)\n"
            "   - X-API-Key + X-Client-Tag: {client_tag}\n"
            "   - identity_confidence / corp 法人格 / 適格事業者番号 / 商号変遷 を保存.\n"
            "3. **createCompanyPublicAuditPack**\n"
            "   - 会計検査院 不当事例 / 行政処分 / 排他ルール / 適格事業者 失効 を含む audit pack.\n"
            "   - 処分が 0 件でも 'クリーン (会計検査院公表分)' と限定句で記載.\n"
            "4. **match_advisors_v1_advisors_match_get**\n"
            "   - jurisdiction (都道府県) + 業種 + 案件規模 に基づく専門家 candidate (税理士 / 公認会計士 / "
            "司法書士 / 行政書士).\n\n"
            "## Output\n"
            "- ## 与信 / 処分 / 排他 リスク table — 1 行 1 リスク, severity (high/medium/low) + 出典.\n"
            "- ## 適格事業者 status (T 番号 / 登録日 / 失効有無).\n"
            "- ## 専門家 handoff candidates — 上位 5 (jurisdiction match score 付き).\n"
            "- 末尾に must_not_claim 明示 (professional_review_complete / tax_or_legal_judgment_complete / "
            "audit_complete / credit_safe / final_eligibility_confirmed).\n"
            f"{_FENCE_FOOTER}"
        ),
    ),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_jpcite_prompts() -> list[dict[str, Any]]:
    return [
        {
            "name": p.name,
            "description": p.description,
            "arguments": p.arguments_payload(),
        }
        for p in _PROMPTS
    ]


def get_jpcite_prompt(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    for p in _PROMPTS:
        if p.name == name:
            return p.render(arguments)
    raise KeyError(f"unknown jpcite prompt: {name}")


def _make_typed_callback(prompt: _JpcitePrompt) -> Callable[..., list[dict[str, Any]]]:
    """Build a callback with an explicit named-parameter signature so FastMCP's
    ``func_metadata`` introspection picks up each argument as a distinct
    ``PromptArgument``.

    FastMCP renders prompts via ``inspect.signature(fn)``; a bare
    ``def _cb(**kwargs)`` collapses to a single ``kwargs`` argument and
    fails validation. We build a fresh function via ``exec`` for each
    prompt so the introspected signature matches its declared arguments.
    """
    arg_names = [a.name for a in prompt.arguments]
    required = {a.name for a in prompt.arguments if a.required}

    def _renderer(_args: dict[str, Any]) -> list[dict[str, Any]]:
        payload = get_jpcite_prompt(prompt.name, _args)
        return payload["messages"]

    # Build explicit signature: def _cb(a, b, c): ...
    params_src = ", ".join(
        f"{n}" if n in required else f"{n}=None" for n in arg_names
    )
    body_src = (
        f"def _cb({params_src}):\n"
        f"    _args = {{{', '.join(f'{n!r}: {n}' for n in arg_names)}}}\n"
        f"    return _renderer(_args)\n"
    )
    ns: dict[str, Any] = {"_renderer": _renderer}
    exec(body_src, ns)  # noqa: S102 — controlled scope, no external input
    cb = ns["_cb"]
    cb.__name__ = prompt.name
    cb.__doc__ = prompt.description
    return cb


def register_jpcite_prompts(mcp: Any) -> None:
    """Wire the 3 jpcite prompts into a FastMCP server at boot."""
    try:
        for p in _PROMPTS:
            cb = _make_typed_callback(p)
            mcp.prompt(
                p.name,
                description=p.description,
            )(cb)
    except AttributeError:
        pass


__all__ = [
    "list_jpcite_prompts",
    "get_jpcite_prompt",
    "register_jpcite_prompts",
]
