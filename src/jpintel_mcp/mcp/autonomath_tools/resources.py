"""jpcite MCP resources — read-only reference documents (MCP 2025-06-18).

The MCP 2025-06-18 protocol supports three primary capabilities:

  1. **tools**    — executable functions (already implemented in tools.py)
  2. **resources** — read-only reference content that the client LLM
     can read without calling a tool; they are addressable by URI and
     returned as `text/markdown` or `application/json`.
  3. **prompts**   — pre-designed query templates the client can request
     and fill with arguments (implemented in prompts.py).

This module defines read-only resources under the legacy ``autonomath://`` URI scheme.
They are self-contained static / computed documents that let a customer LLM
answer meta-questions ("what record_kinds exist?", "what does the primary
source policy say?", "which intent should I use?") without round-tripping
to a tool and burning latency.

Design intent
-------------
* Resources are **cheap** (static or 1-query snapshot). Anything that would
  take > 50 ms to compute belongs in a tool, not a resource.
* Resources are **stable URIs** — clients can cache them by URI.
* Resources carry **update-frequency metadata** (`_UpdateFrequency`) so the
  client knows when to re-read (e.g. the authority list is refreshed daily,
  but the primary-source policy never changes).
* Resources are the right place for **policy prose** (how we avoid
  hallucination, why we cite primary sources) — sending that text into every
  tool response would waste millions of tokens across our customer base.

URI scheme
----------
``autonomath://<namespace>/<slug>``

  * ``schema/`` — DB schema docs
  * ``policy/``  — policy prose
  * ``list/``    — enum / reference lists
  * ``stats/``   — freshness / coverage snapshots

This module is transport-agnostic: it exposes a pure Python registry. The
FastMCP wiring (``@mcp.resource(...)``) happens in ``register_resources()``
so it can be called at merge time with the jpintel-mcp server singleton.
"""
from __future__ import annotations

import json
import os as _os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Metadata & registry
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DB_PATH = Path(_os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
))

# Static-file roots (8 taxonomies + 5 example profiles + optional templates).
_STATIC_DIR = Path(
    _os.environ.get(
        "AUTONOMATH_STATIC_DIR",
        "/data/autonomath_static"
        if Path("/data/autonomath_static").exists()
        else str(_REPO_ROOT / "data" / "autonomath_static"),
    )
)
_EXAMPLE_DIR = _STATIC_DIR / "example_profiles"
_TEMPLATE_DIR = _STATIC_DIR / "templates"

# Mapping: resource slug → relative path under _STATIC_DIR.
_TAXONOMY_FILES: dict[str, tuple[str, str]] = {
    # slug → (relative_path, human_description)
    "seido": (
        "seido.json",
        "制度 master taxonomy (補助金 / 助成金 / 融資 / 税制 / 認定制度 codes + parent groupings).",
    ),
    "glossary": (
        "glossary.json",
        "用語 glossary — Japanese subsidy / loan / tax terminology with canonical labels.",
    ),
    "money_types": (
        "money_types.json",
        "助成区分 enum — 補助金 / 助成金 / 交付金 / 融資 / 保証 / 税制 etc. with sub-types.",
    ),
    "obligations": (
        "obligations.json",
        "Post-award 義務 catalog (報告 / 取得財産管理 / 返還事由 etc.) keyed by 制度 code.",
    ),
    "dealbreakers": (
        "dealbreakers.json",
        "Dealbreaker rules — disqualifying conditions per 制度 (税滞納 / 暴排 / 倒産 etc.).",
    ),
    "sector_combos": (
        "sector_combos.json",
        "Sector-combination matrix — which 制度 combine cleanly across industry / size axes.",
    ),
    "crop_library": (
        "agri/crop_library.json",
        "一次産業 crop library — 品目コード + 標準収量 + 標準作期 + 制度マッピング.",
    ),
    "exclusion_rules": (
        "agri/exclusion_rules.json",
        "制度併用ルール — 制度間の併給制限 / 重複申請禁止 / 排他条件.",
    ),
}

_EXAMPLE_PROFILE_FILES: dict[str, tuple[str, str]] = {
    "ichigo_20a": (
        "A_ichigo_20a.json",
        "Type A: 新規就農個人 — いちご 20a 施設栽培 (埼玉). Reference shape for 個人事業主 intake.",
    ),
    "rice_200a": (
        "D_rice_200a.json",
        "Type D: 集落営農 — 水稲 200a + 大豆輪作 (新潟). Reference shape for 大規模法人 intake.",
    ),
    "new_corp": (
        "J_new_corp.json",
        "Type C: 法人参入 — 設立 5 年以内 / 施設トマト 40a (千葉). Reference shape for 新設法人 intake.",
    ),
    "dairy_100head": (
        "Q_dairy_100head.json",
        "Type B: 既存農家 — フリーストール 100 頭酪農拡張 (北海道). Reference shape for 既存事業者 intake.",
    ),
    "minimal": (
        "N_minimal.json",
        "Minimal viable baseline — required-only fields. Use for null / edge-case testing.",
    ),
}

# 36協定 template — gated behind settings.saburoku_kyotei_enabled
# (env: AUTONOMATH_36_KYOTEI_ENABLED, default False). 36協定 is a 労基法 §36 +
# 社労士法 regulated obligation; resource exposure follows the same gate as
# the render_36_kyotei_am tool. See
# docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md.
_SABUROKU_TEMPLATE_FILE = "36_kyotei_template.txt"


@dataclass(frozen=True)
class ResourceMeta:
    """Metadata describing a single MCP resource."""

    uri: str
    name: str
    description: str
    mime_type: str = "text/markdown"
    update_frequency: str = "static"  # "static", "daily", "hourly", "on_write"
    provider: Callable[[], str] | None = None
    # Static content if provider is None.
    content: str | None = None

    def read(self) -> str:
        if self.provider is not None:
            return self.provider()
        if self.content is not None:
            return self.content
        raise ValueError(f"Resource {self.uri} has neither provider nor content")


# ---------------------------------------------------------------------------
# DB helper (read-only, never crashes)
# ---------------------------------------------------------------------------


def _safe_query(sql: str, params: tuple = ()) -> list[tuple]:
    """Safe read-only query. Returns [] on any failure so a broken DB never
    breaks resource-read. Resources are advisory, not authoritative."""
    try:
        if not _DB_PATH.exists():
            return []
        with sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True, timeout=2.0) as c:
            c.row_factory = sqlite3.Row
            return [tuple(r) for r in c.execute(sql, params).fetchall()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Static content (policy & schema prose)
# ---------------------------------------------------------------------------


_DATA_MODEL_MD = """# jpcite Data Model

jpcite returns public-program records with stable IDs, source URLs, fetched
timestamps, and lightweight relationship metadata. The model is intentionally
retrieval-first: clients should cite the returned source fields instead of
turning the result into unsupported professional advice.

## Common public fields

  - `id` / `unified_id`: stable record identifier
  - `record_kind`: program, tax_measure, certification, law, adoption,
    enforcement, statistic, corporate_entity, etc.
  - `primary_name`: display name
  - `authority`: ministry, municipality, or other public authority
  - `source_url`: primary-source URL where available
  - `source_fetched_at`: last observed timestamp where available
  - `confidence` / `quality`: retrieval confidence and coverage hints

## Relationship labels

  - prerequisite / compatible / incompatible
  - replaces / amends
  - related
  - has_authority / available_in
  - applies_to_industry / applies_to_size
  - references_law

## Client rules

  1. Treat source URLs as part of the answer, not optional metadata.
  2. Do not invent missing amounts, deadlines, or eligibility conditions.
  3. When a field is missing, say it is missing and point the user to the
     primary source for final confirmation.
  4. No LLM-generated content is written back into jpcite's source corpus.
"""

_RECORD_KINDS_MD = """# record_kind enum (discriminator values)

Every row in `am_entities.record_kind` is one of the following. This is a
**closed enum** — clients must not invent new values.

| record_kind       | meaning                            | typical authority          |
| ----------------- | ---------------------------------- | --------------------------- |
| program           | 補助金 / 融資 / 助成 / 交付金      | METI / MAFF / 各省 / 自治体 |
| tax_measure       | 租税特別措置 / 税制優遇             | 財務省 / 国税庁             |
| certification     | 認定 / 認証 / 指定                  | 各省 / 団体                 |
| law               | e-Gov 法令 (法律 / 政令 / 省令)     | e-Gov                       |
| authority         | 交付主体 (省庁・自治体) メタデータ  | self                        |
| adoption          | 採択結果レコード                    | 交付決定公示                |
| case_study        | 採択事例 (実名・事業概要)           | 交付決定公示                |
| enforcement       | 返還 / 処分 / 行政措置              | 各省 / 会計検査院           |
| statistic         | e-Stat / 公的統計ピボット           | 総務省統計局                |
| corporate_entity  | 法人番号マスタ (gBizINFO)           | 国税庁                      |

Do not confuse:

  * `program` vs `tax_measure` — if the benefit flows via tax code, it is a
    `tax_measure`. Otherwise (cash grant / loan / guarantee), it is
    `program`.
  * `law` vs `program` — a program may `references_law` a law, but they are
    separate rows.
"""

_PRIMARY_SOURCE_POLICY_MD = """# Primary-Source Policy (authoritative)

**Rule**: every fact returned by jpcite SHOULD be traceable to a
**primary source** — meaning a government-authored document hosted on a
government domain, OR an authoritative intermediary we have explicitly
whitelisted (公庫 / JETRO / NEDO).

## Why

Our customers are applicants with real money on the line. A hallucinated
grant, a wrong deadline, or a misattributed authority can cost millions of
yen and months of wasted effort. Secondary aggregators (blogs, summary
sites) are **not** primary sources, even when they are accurate — because
they go stale, and we cannot audit their provenance.

## What counts as a primary source

Whitelisted domains include (non-exhaustive):

  - `*.go.jp` (all Japanese government domains)
  - `elaws.e-gov.go.jp` (legal text)
  - `gbiz-info.go.jp` (corporate entity master)
  - `e-stat.go.jp` (official statistics)
  - `jfc.go.jp` (日本政策金融公庫)
  - `jetro.go.jp` (JETRO)
  - `nedo.go.jp` (NEDO)
  - Prefectural / municipal official domains (`*.pref.xx.jp`, `*.city.xx.jp`)

## What does NOT count

  - Commercial aggregator blogs (e.g. noukaweb, mirasapo, etc.)
  - Consultancy / advisor posts
  - Wikipedia
  - News summaries
  - Any content generated by an LLM (including ours)

## Consequences for clients

When a tool returns a row without a primary-source URL, that row is marked
`"provenance": "unverified"` and MUST be flagged to the end-user. Customers
MUST not present unverified rows as authoritative.
"""

_NO_HALLUCINATION_POLICY_MD = """# No-Hallucination Policy (for client LLMs)

jpcite is a **read-only retrieval layer over curated public data**. It does
not invent programs, rates, deadlines, or authorities. Client LLMs consuming
jpcite MUST respect this contract.

## Hard rules for client LLMs

1. **Never synthesize a program name the tool did not return.** If a user
   asks "what grant lets me buy a tractor?" and jpcite returns zero
   results, the answer is "none found in the database" — NOT an invented
   name.

2. **Never fabricate numeric values.** If `amount_max` is null in the
   envelope, do not fill it with a "typical" figure. Null means unknown.

3. **Never infer deadlines.** If `deadline` is absent, say "deadline not
   published". Do not offer "roughly end of Q1" or similar.

4. **Never merge rows.** Each `canonical_id` is distinct. A grant in
   prefecture A and a similar grant in prefecture B are two rows, not one.

5. **Always cite `source_url`.** Every user-facing claim must link back to
   the `source_url` from the envelope. If `source_url` is null, the claim
   MUST be withheld.

## Soft rules

  - Prefer `intent=i01..i10` queries (see `list/intent_types`) over ad-hoc
    keyword searches — they route through curated query plans.
  - When confidence is mixed, return the jpcite envelope verbatim and
    let the human decide. "The tool returned the following 3 rows: …" is
    always valid.

## What happens if you break this

The client application is responsible for any unsupported claims it adds on
top of jpcite data. Keep source URLs attached and avoid turning retrieved
facts into professional advice.
"""

_INTENT_TYPES_MD = """# Intent types i01–i10

The 10 pre-mapped intents a client can pass to `reason_answer`. Each intent
routes to a specific query plan; clients should prefer these over free-form
search.

| intent | name                         | plain-language purpose                              |
| ------ | ---------------------------- | -------------------------------------------------- |
| i01    | find_programs                | 条件にあう制度を探す                                  |
| i02    | check_eligibility            | 自社がある制度の対象になるか確認                      |
| i03    | compare_rounds               | 同一制度の複数回次を比較                              |
| i04    | trace_amendment_history      | 改正履歴を時系列で追う                                |
| i05    | audit_enforcement            | 処分 / 返還の履歴を確認                              |
| i06    | get_deadlines                | 締切日 / 受付期間の一覧                               |
| i07    | tax_savings_estimate         | 税制優遇の節税試算                                    |
| i08    | peer_benchmark               | 同規模自治体 / 同業他社の利用状況                      |
| i09    | application_guidance         | 申請書作成ガイダンス                                  |
| i10    | combined_package             | 補助金 + 税制 + 融資の組合せ                          |

## Routing

Internally each intent maps to a SQL query plan + optional graph traversal.
`i10` (combined_package) is special — it composes i01+i07+i06 in one call.
"""

_PROGRAM_KINDS_MD = """# program_kind enum (sub-discriminator within record_kind=program)

When `record_kind=program`, the `program_kind` facet tells you *what shape*
the benefit takes.

| program_kind | 日本語        | description                                   |
| ------------ | ------------- | --------------------------------------------- |
| subsidy      | 補助金         | 使途限定の給付金、公募審査型                     |
| grant        | 交付金         | 使途が広い給付金、割当型                         |
| loan         | 融資           | 公庫 / 信用保証 / 制度融資                       |
| guarantee    | 保証           | 信用保証 / 債務保証                              |
| aid          | 助成金         | 労働 / 職業能力開発など厚労省系                   |
| rebate       | 還付 / 助成    | 後払い型助成 (自治体に多い)                      |
| voucher      | 利用券         | 特定用途のクーポン / チケット                    |
| tax          | 税 (税額控除)  | record_kind=tax_measure と重複時の確認          |
"""


# ---------------------------------------------------------------------------
# Dynamic providers (DB-backed)
# ---------------------------------------------------------------------------


def _authority_list_md() -> str:
    rows = _safe_query(
        "SELECT canonical_id, primary_name, COALESCE(json_extract(raw_json,'$.level'),'') "
        "FROM am_entities WHERE record_kind='authority' "
        "ORDER BY primary_name LIMIT 200"
    )
    lines = [
        "# Authority canonical list",
        "",
        "All `authority_canonical` values currently used in the DB.",
        "Refreshed daily from the authority dimension table.",
        "",
        f"Count: **{len(rows)}** authorities.",
        "",
        "| canonical_id | name | level |",
        "| ------------ | ---- | ----- |",
    ]
    for r in rows:
        lines.append(f"| `{r[0]}` | {r[1]} | {r[2] or '-'} |")
    if not rows:
        lines.append("| _(DB unavailable; resource will populate on next read)_ | | |")
    return "\n".join(lines)


def _prefecture_list_md() -> str:
    jis = [
        ("01", "北海道"), ("02", "青森県"), ("03", "岩手県"), ("04", "宮城県"),
        ("05", "秋田県"), ("06", "山形県"), ("07", "福島県"), ("08", "茨城県"),
        ("09", "栃木県"), ("10", "群馬県"), ("11", "埼玉県"), ("12", "千葉県"),
        ("13", "東京都"), ("14", "神奈川県"), ("15", "新潟県"), ("16", "富山県"),
        ("17", "石川県"), ("18", "福井県"), ("19", "山梨県"), ("20", "長野県"),
        ("21", "岐阜県"), ("22", "静岡県"), ("23", "愛知県"), ("24", "三重県"),
        ("25", "滋賀県"), ("26", "京都府"), ("27", "大阪府"), ("28", "兵庫県"),
        ("29", "奈良県"), ("30", "和歌山県"), ("31", "鳥取県"), ("32", "島根県"),
        ("33", "岡山県"), ("34", "広島県"), ("35", "山口県"), ("36", "徳島県"),
        ("37", "香川県"), ("38", "愛媛県"), ("39", "高知県"), ("40", "福岡県"),
        ("41", "佐賀県"), ("42", "長崎県"), ("43", "熊本県"), ("44", "大分県"),
        ("45", "宮崎県"), ("46", "鹿児島県"), ("47", "沖縄県"),
    ]
    lines = [
        "# 47 都道府県 (JIS X 0401 prefecture codes)",
        "",
        "Use the two-digit `code` column as the `prefecture` argument in "
        "any tool that accepts one.",
        "",
        "| code | name |",
        "| ---- | ---- |",
    ]
    for code, name in jis:
        lines.append(f"| `{code}` | {name} |")
    return "\n".join(lines)


def _freshness_stats_md() -> str:
    counts = {}
    for kind_row in _safe_query(
        "SELECT record_kind, COUNT(*) FROM am_entities GROUP BY record_kind"
    ):
        counts[kind_row[0]] = kind_row[1]
    (last_update,) = (
        _safe_query("SELECT MAX(updated_at) FROM am_entities")[:1] or [(None,)]
    )[0] if _safe_query("SELECT MAX(updated_at) FROM am_entities") else (None,)
    now = datetime.now(UTC).isoformat()
    lines = [
        "# Freshness snapshot",
        "",
        f"- Snapshot captured: {now}",
        f"- Last `updated_at` in DB: {last_update or '_(unknown)_'}",
        "",
        "## Row counts by record_kind",
        "",
        "| record_kind | rows |",
        "| ----------- | ---- |",
    ]
    if counts:
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {k} | {v:,} |")
        lines.append(f"| **TOTAL** | **{sum(counts.values()):,}** |")
    else:
        lines.append("| _(DB unavailable)_ | 0 |")
    lines.extend(
        [
            "",
            "## Update cadence",
            "",
            "  - `program` / `tax_measure` — weekly sweep of authority pages",
            "  - `adoption` — on publication (usually quarterly)",
            "  - `corporate_entity` — monthly gBizINFO snapshot",
            "  - `law` — on e-Gov change notification",
            "  - `statistic` — on e-Stat release",
        ]
    )
    return "\n".join(lines)


def _target_profiles_md() -> str:
    rows = _safe_query(
        "SELECT DISTINCT json_extract(raw_json,'$.target_types') "
        "FROM am_entities WHERE record_kind='program' "
        "AND json_extract(raw_json,'$.target_types') IS NOT NULL LIMIT 80"
    )
    seen: set[str] = set()
    for (raw,) in rows:
        if not raw:
            continue
        try:
            val = json.loads(raw) if raw.startswith("[") else [raw]
            for v in val:
                seen.add(str(v))
        except Exception:
            seen.add(str(raw))
    lines = [
        "# Target profile vocabulary (partial)",
        "",
        "Observed `target_types` values across programs. This is a **drifting**",
        "vocabulary — English/Japanese and singular/plural coexist. Clients",
        "MUST normalize via the ALIAS table before comparing.",
        "",
    ]
    for v in sorted(seen)[:60]:
        lines.append(f"  - `{v}`")
    if not seen:
        lines.append("  - _(DB unavailable or no target_types observed)_")
    return "\n".join(lines)


def _graph_edge_types_md() -> str:
    return (
        "# Graph edge types (relations between entities)\n\n"
        "The graph store (`graph.sqlite::am_relation`) holds ~20K directed\n"
        "edges typed as follows:\n\n"
        "| type               | from -> to                        | notes                  |\n"
        "| ------------------ | --------------------------------- | ---------------------- |\n"
        "| prerequisite       | program → program                | A must precede B       |\n"
        "| compatible         | program ↔ program                | can be co-applied      |\n"
        "| incompatible       | program ↔ program                | mutually exclusive     |\n"
        "| replaces           | program → program                | new supersedes old     |\n"
        "| amends             | law → law / program → program    | version history        |\n"
        "| related            | any → any                         | loose association      |\n"
        "| has_authority      | program → authority              | FK-like                |\n"
        "| available_in       | program → region                 | scope filter           |\n"
        "| applies_to_industry| program → industry_jsic           | JSIC code filter       |\n"
        "| applies_to_size    | program → size_bucket             | SME / large / sole-trader |\n"
        "| references_law     | program → law                    | statutory grounding    |\n"
    )


def _certification_kinds_md() -> str:
    rows = _safe_query(
        "SELECT json_extract(raw_json,'$.certification_kind'), COUNT(*) "
        "FROM am_entities WHERE record_kind='certification' "
        "GROUP BY json_extract(raw_json,'$.certification_kind') "
        "ORDER BY 2 DESC LIMIT 40"
    )
    lines = [
        "# Certification kinds observed",
        "",
        "Sub-type distribution for `record_kind=certification`.",
        "",
        "| kind | count |",
        "| ---- | ----- |",
    ]
    if rows:
        for k, n in rows:
            lines.append(f"| {k or '_(null)_'} | {n} |")
    else:
        lines.append("| _(DB unavailable)_ | 0 |")
    return "\n".join(lines)


def _tool_manifest_md() -> str:
    return (
        "# Tool manifest (summary)\n\n"
        "jpcite exposes MCP tools for public-program retrieval. "
        "The full JSON manifest lives at\n"
        "`docs/mcp_tool_manifest.json`; this resource is a quick reference.\n\n"
        "  - `reason_answer(query, intent)` — main intent-routed search\n"
        "  - `search_programs(...)`         — filter by prefecture/industry/size\n"
        "  - `search_tax_incentives(...)`   — tax_measure rows\n"
        "  - `search_certifications(...)`   — certification rows\n"
        "  - `search_acceptance_stats(...)` — adoption statistics\n"
        "  - `list_open_programs(...)`      — active right now\n"
        "  - `active_programs_at(date)`     — active on given date\n"
        "  - `search_by_law(law_id)`        — programs referencing a law\n"
        "  - `related_programs(id)`         — graph neighborhood\n"
        "  - `enum_values(field)`           — introspection\n"
        "  - `search_loans`, `search_enforcement`, `search_sib`, …\n"
    )


def _make_taxonomy_provider(slug: str) -> Callable[[], str]:
    """Build a JSON-text provider for one taxonomy file under data/autonomath_static/.

    Returns a callable that re-reads the file each call (cheap for files <100 KB
    and ensures redeploys without restart pick up edits). Falls back to a stub
    payload with the missing-path note if the file disappears, so a broken
    deploy never breaks resource-read.
    """
    rel_path, _desc = _TAXONOMY_FILES[slug]
    full_path = _STATIC_DIR / rel_path

    def _provider() -> str:
        if not full_path.exists():
            return json.dumps(
                {
                    "error": "resource_file_missing",
                    "slug": slug,
                    "expected_path": str(full_path),
                    "hint": (
                        "File missing on disk — possible deployment drift. "
                        "Verify data/autonomath_static/ packaging in pyproject.toml."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        return full_path.read_text(encoding="utf-8")

    return _provider


def _make_example_profile_provider(slug: str) -> Callable[[], str]:
    """Build a JSON-text provider for one example profile under example_profiles/."""
    rel_filename, _desc = _EXAMPLE_PROFILE_FILES[slug]
    full_path = _EXAMPLE_DIR / rel_filename

    def _provider() -> str:
        if not full_path.exists():
            return json.dumps(
                {
                    "error": "profile_file_missing",
                    "slug": slug,
                    "expected_path": str(full_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        return full_path.read_text(encoding="utf-8")

    return _provider


def _saburoku_template_provider() -> str:
    """Read the 36協定 template text. Provider is wired only when
    settings.saburoku_kyotei_enabled is True."""
    path = _TEMPLATE_DIR / _SABUROKU_TEMPLATE_FILE
    if not path.exists():
        return (
            "# 36協定 template missing on disk\n\n"
            f"Expected at: {path}\n"
            "Verify data/autonomath_static/templates/ packaging."
        )
    return path.read_text(encoding="utf-8")


def _envelope_schema_md() -> str:
    return (
        "# Response envelope schema (v2)\n\n"
        "Every tool returns one of two envelopes.\n\n"
        "## Search envelope\n\n"
        "```json\n"
        "{\n"
        '  "total": 42,\n'
        '  "limit": 20,\n'
        '  "offset": 0,\n'
        '  "results": [ ... ],\n'
        '  "hint": "…optional …",\n'
        '  "retry_with": { "…optional…": "…" }\n'
        "}\n"
        "```\n\n"
        "## Graph envelope (only `related_programs`)\n\n"
        "```json\n"
        "{\n"
        '  "seed_id": "…",\n'
        '  "relations": [ … ],\n'
        '  "nodes":     [ … ],\n'
        '  "total_edges": 12\n'
        "}\n"
        "```\n\n"
        "## Error envelope\n\n"
        "`{ \"error\": { \"code\": \"...\", \"message\": \"...\", \"retry_with\": {...} } }`\n"
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_RESOURCES: list[ResourceMeta] = [
    ResourceMeta(
        uri="autonomath://schema/data_model",
        name="Data Model",
        description="Canonical DB schema overview (tables, columns, relationships).",
        content=_DATA_MODEL_MD,
    ),
    ResourceMeta(
        uri="autonomath://schema/record_kinds",
        name="record_kind enum",
        description="Discriminator values for am_entities.record_kind.",
        content=_RECORD_KINDS_MD,
    ),
    ResourceMeta(
        uri="autonomath://schema/envelope",
        name="Response envelope schema (v2)",
        description="Canonical JSON envelope shape every tool returns.",
        content=_envelope_schema_md(),
    ),
    ResourceMeta(
        uri="autonomath://policy/primary_source",
        name="Primary-Source Policy",
        description="Rule that every fact must trace to a government primary source.",
        content=_PRIMARY_SOURCE_POLICY_MD,
    ),
    ResourceMeta(
        uri="autonomath://policy/no_hallucination",
        name="No-Hallucination Policy",
        description=(
            "Hard rules the client LLM must follow when speaking on top of "
            "jpcite data."
        ),
        content=_NO_HALLUCINATION_POLICY_MD,
    ),
    ResourceMeta(
        uri="autonomath://list/authorities",
        name="Authority canonical list",
        description="All authority_canonical values in the DB, refreshed daily.",
        update_frequency="daily",
        provider=_authority_list_md,
    ),
    ResourceMeta(
        uri="autonomath://list/prefectures",
        name="47 Prefectures",
        description="JIS X 0401 two-digit prefecture codes and names.",
        content=_prefecture_list_md(),
    ),
    ResourceMeta(
        uri="autonomath://list/program_kinds",
        name="program_kind enum",
        description="Sub-type vocabulary for record_kind=program.",
        content=_PROGRAM_KINDS_MD,
    ),
    ResourceMeta(
        uri="autonomath://list/intent_types",
        name="Intent types (i01–i10)",
        description="The 10 pre-mapped query intents.",
        content=_INTENT_TYPES_MD,
    ),
    ResourceMeta(
        uri="autonomath://list/graph_edge_types",
        name="Graph edge types",
        description="The 11 edge types in am_relation.",
        content=_graph_edge_types_md(),
    ),
    ResourceMeta(
        uri="autonomath://list/certification_kinds",
        name="Certification kinds",
        description="Observed distribution of certification sub-kinds.",
        update_frequency="daily",
        provider=_certification_kinds_md,
    ),
    ResourceMeta(
        uri="autonomath://list/target_profiles",
        name="Target profile vocabulary",
        description="Observed target_types values (drifting vocabulary — use ALIAS).",
        update_frequency="daily",
        provider=_target_profiles_md,
    ),
    ResourceMeta(
        uri="autonomath://stats/freshness",
        name="Freshness snapshot",
        description="Row counts and last updated_at across record_kind.",
        update_frequency="hourly",
        provider=_freshness_stats_md,
    ),
    ResourceMeta(
        uri="autonomath://schema/tool_manifest",
        name="Tool manifest (summary)",
        description="Quick reference for the 23 tools; full manifest is at docs/mcp_tool_manifest.json.",
        content=_tool_manifest_md(),
    ),
    ResourceMeta(
        uri="autonomath://policy/tos_excerpt",
        name="Terms of Service excerpt",
        description="Key ToS clauses relevant to LLM clients.",
        content=(
            "# Terms of Service — relevant excerpts\n\n"
            "  - **No warranty**: jpcite data is information retrieval, not "
            "legal, tax, or application advice. Verify against the linked "
            "primary source before committing resources.\n"
            "  - **LLM output**: the client application is responsible for "
            "claims added on top of jpcite envelopes.\n"
            "  - **Rate**: ¥3 / successful request 税別 (¥3.30 税込). Anonymous use is 3 requests/day per IP.\n"
            "  - **Readonly**: all tools are idempotent and read-only.\n"
            "  - **No PII ingestion**: never send personal data into a tool "
            "argument; they are logged.\n"
            "  - Full ToS: https://jpcite.com/docs/compliance/terms_of_service/\n"
        ),
    ),
]

# ---------------------------------------------------------------------------
# Static-file resources (8 taxonomies + 5 example profiles).
# These attach the JSON payloads under data/autonomath_static/ as MCP
# `resources[]` so a client LLM can read them directly via resource URI
# without round-tripping through the legacy list_static_resources_am /
# get_static_resource_am tool pair (which remains registered for
# compatibility.
# ---------------------------------------------------------------------------

for _slug, (_rel_path, _desc) in _TAXONOMY_FILES.items():
    _full_path = _STATIC_DIR / _rel_path
    _RESOURCES.append(
        ResourceMeta(
            uri=f"autonomath://taxonomies/{_slug}",
            name=f"Taxonomy: {_slug}",
            description=_desc + " Static reference data served by jpcite.",
            mime_type="application/json",
            update_frequency="static",
            provider=_make_taxonomy_provider(_slug),
        )
    )

for _slug, (_rel_filename, _desc) in _EXAMPLE_PROFILE_FILES.items():
    _RESOURCES.append(
        ResourceMeta(
            uri=f"autonomath://example_profiles/{_slug}",
            name=f"Example profile: {_slug}",
            description=_desc + " PII-clean reference payload — copy-paste seed for prescreen / DD / eligibility tools.",
            mime_type="application/json",
            update_frequency="static",
            provider=_make_example_profile_provider(_slug),
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_SABUROKU_RESOURCE = ResourceMeta(
    uri="autonomath://templates/saburoku_kyotei",
    name="36協定 template (時間外労働・休日労働協定届)",
    description=(
        "36協定 (労基法 §36) draft template. The output is a draft requiring "
        "qualified professional confirmation; do not file as-is."
    ),
    mime_type="text/plain",
    update_frequency="static",
    provider=_saburoku_template_provider,
)


def _effective_resources() -> list[ResourceMeta]:
    """Return `_RESOURCES` plus the 36協定 template when its gate is enabled.

    Centralizes the gate so list_resources() / read_resource() / register_resources()
    all see the same view — `mcp.list_resources()` will not surface the
    saburoku entry when the env flag is off.
    """
    extra: list[ResourceMeta] = []
    try:
        # Late import — config has its own settings singleton; keep this
        # module import-safe even if pydantic-settings isn't yet wired.
        from jpintel_mcp.config import Settings

        if Settings().saburoku_kyotei_enabled:
            extra.append(_SABUROKU_RESOURCE)
    except Exception:
        # Conservative: if we can't read settings, keep the regulated
        # resource hidden (matches default-False stance).
        pass
    return [*_RESOURCES, *extra]


def list_resources() -> list[dict[str, str]]:
    """Return the MCP `resources/list` payload."""
    return [
        {
            "uri": r.uri,
            "name": r.name,
            "description": r.description,
            "mimeType": r.mime_type,
            "updateFrequency": r.update_frequency,
        }
        for r in _effective_resources()
    ]


def read_resource(uri: str) -> dict[str, Any]:
    """Return the MCP `resources/read` payload for a single URI."""
    for r in _effective_resources():
        if r.uri == uri:
            text = r.read()
            return {
                "contents": [
                    {
                        "uri": r.uri,
                        "mimeType": r.mime_type,
                        "text": text,
                    }
                ]
            }
    raise KeyError(f"unknown resource URI: {uri}")


def get_resource(uri: str) -> ResourceMeta:
    """Lookup by URI (raises KeyError)."""
    for r in _effective_resources():
        if r.uri == uri:
            return r
    raise KeyError(uri)


def register_resources(mcp: Any) -> None:
    """Wire resources into a FastMCP server instance at merge time.

    Called from server bootstrap. Keeps this module import-safe.
    The 36協定 template entry is conditionally included via
    _effective_resources() — env AUTONOMATH_36_KYOTEI_ENABLED must be true.
    """
    try:
        for r in _effective_resources():
            # Closure-captured r for the callback.
            def _make_cb(res: ResourceMeta) -> Callable[[], str]:
                def _cb() -> str:
                    return res.read()

                return _cb

            mcp.resource(
                r.uri,
                name=r.name,
                description=r.description,
                mime_type=r.mime_type,
            )(_make_cb(r))
    except AttributeError:
        # FastMCP version without .resource() — skip cleanly.
        pass
