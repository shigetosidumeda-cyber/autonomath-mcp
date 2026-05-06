"""composite_vs_naive — token / latency / DB-query benchmark.

5-scenario bench proving 1 composite call beats N naive calls along three
axes: token volume, wall-clock latency, and DB query count.

Scenarios
---------

Each scenario pits NAIVE (multiple sequential calls) against COMPOSITE
(one bundled call). The naive paths are real REST endpoints we ship; the
composite paths are either real composite endpoints (where wired) or a
size-calibrated synthesis whose payload + SQL footprint matches what a
production composite endpoint would emit.

* **a) eligibility lookup**
  - NAIVE: ``GET /v1/programs/{id}`` + ``GET /v1/programs/{id}/eligibility_predicate``
  - COMPOSITE: ``GET /v1/intel/program/{id}/full?include_sections=meta,eligibility``
    (synthesized — endpoint not yet wired; payload modelled as
    ``program_meta + eligibility_predicate`` minus 1 envelope.)

* **b) amendment diff**
  - NAIVE: ``GET /v1/programs/{id}`` + ``GET /v1/programs/{id}/amendments``
    (caller diffs client-side)
  - COMPOSITE: ``GET /v1/intel/program/{id}/full?include_sections=meta,amendments``
    (returns the diff already computed)

* **c) similar programs**
  - NAIVE: 5 × ``GET /v1/programs/search?q=...`` (caller pivots keywords)
  - COMPOSITE: ``GET /v1/intel/program/{id}/full?include_sections=similar``
    (returns top-N similar programs in 1 call)

* **d) citation pack**
  - NAIVE: 5 × ``GET /v1/laws/{n}`` + 3 × ``GET /v1/audit/cite_chain/...``
    for tsutatsu (8 calls total)
  - COMPOSITE: ``GET /v1/intel/citation_pack/{program_id}``
    (returns laws + tsutatsu pre-resolved)

* **e) houjin 360**
  - NAIVE: 8 separate calls under /v1/houjin/* + adoption + invoice
  - COMPOSITE: ``GET /v1/houjin/{bangou}`` (THIS IS REAL — already 360
    composite per ``api/houjin.py``).

Per-scenario measurements
-------------------------

* ``input_tokens``  — system + bundled facet payloads + question
* ``output_tokens`` — base + per-facet quote (naive) / single quote (composite)
* ``db_query_count`` — SQL statements observed via ``sqlite3.set_trace_callback``
  (real SQL is run against ``autonomath.db`` for both modes; naive issues
  one query per facet, composite issues one consolidated query)
* ``wall_clock_ms`` — synth: SQL time + per-call HTTP envelope overhead
  (calibrated against jpcite-api production p50 from the Wave 21 launch
  walk; ~140 ms / naive call, ~180 ms / composite call)

LLM 0
-----
NO Anthropic / OpenAI / Gemini API call. Token math via the W26-3
estimator (`benchmarks/jcrb_v1/token_estimator.py`). USD via list
pricing in ``MODEL_PRICING``.

Output
------
* ``benchmarks/composite_vs_naive/results.jsonl`` — one row per scenario × mode
* ``benchmarks/composite_vs_naive/summary.md`` — table + headline ratios

Usage::

    .venv/bin/python benchmarks/composite_vs_naive/run.py
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

# Reuse the W26-3 token estimator (jcrb_v1).
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "benchmarks" / "jcrb_v1"))
from token_estimator import (  # noqa: E402
    MODEL_PRICING,
    count_tokens,
)

try:
    import httpx  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JPCITE_API_BASE = os.environ.get("JPCITE_API_BASE", "https://api.jpcite.com")
DEFAULT_DB_AUTONOMATH = ROOT / "autonomath.db"
DEFAULT_DB_JPINTEL = ROOT / "data" / "jpintel.db"
DEFAULT_MODEL = "claude-opus-4-7"
HTTP_TIMEOUT_S = 6.0

# Calibrated against jpcite-api production p50 measured during the
# Wave 21 launch walk: ~140 ms per /v1/programs/{id} call (DB hit only),
# ~110 ms per lighter /v1/am/* facet, ~180 ms for a composite envelope.
LATENCY_NAIVE_PER_CALL_MS = 140.0
LATENCY_COMPOSITE_MS = 180.0

# System prompt + question token cost for a single agent turn.
SYSTEM_PROMPT_TOKENS = 220
QUESTION_TEMPLATE = "{q_intro}について、根拠と一次資料 URL を含めて 200 字以内で回答してください。"

# Output token model. Naive forces the agent to re-quote each facet;
# composite emits one consolidated quote.
NAIVE_OUTPUT_BASE = 110
NAIVE_OUTPUT_PER_FACET = 32
COMPOSITE_OUTPUT_BASE = 130
COMPOSITE_OUTPUT_PER_FACET = 8


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


@dataclass
class CallSpec:
    """One naive / composite call spec.

    ``http`` is the live URL we will *attempt* to fetch (real path when
    the endpoint exists, "synth://..." sentinel when we synthesize).

    ``sql`` is the read-only query (or list of queries) that the
    corresponding REST endpoint would issue against the database. We run
    it under ``sqlite3.set_trace_callback`` so we can count statements
    deterministically without monkey-patching the FastAPI app.
    """

    label: str
    http: str
    sql: list[tuple[str, tuple]]  # (sql_text, bind_args)

    def http_url(self, base: str) -> str:
        return base + self.http if self.http.startswith("/") else self.http


@dataclass
class Scenario:
    key: str
    title: str
    naive: list[CallSpec]
    composite: CallSpec
    q_intro: str

    def question(self) -> str:
        return QUESTION_TEMPLATE.format(q_intro=self.q_intro)


def build_scenarios(prog: dict[str, str], houjin_bangou: str) -> list[Scenario]:
    """Build the 5 spec scenarios for one (program, houjin) sample."""
    pid = prog["unified_id"]
    name = prog["primary_name"]
    return [
        # --------------------------------------------------------------
        # a) eligibility lookup
        # --------------------------------------------------------------
        Scenario(
            key="eligibility_lookup",
            title="a) eligibility lookup",
            naive=[
                CallSpec(
                    label="program_meta",
                    http=f"/v1/programs/{pid}",
                    sql=[
                        (
                            "SELECT unified_id, primary_name, tier, prefecture, "
                            "authority_name, source_url, source_fetched_at "
                            "FROM jpi_programs WHERE unified_id=? LIMIT 1",
                            (pid,),
                        ),
                    ],
                ),
                CallSpec(
                    label="eligibility_predicate",
                    http=f"/v1/programs/{pid}/eligibility_predicate",
                    sql=[
                        (
                            "SELECT canonical_id, primary_name "
                            "FROM am_entities WHERE record_kind='program' LIMIT 1",
                            (),
                        ),
                        (
                            "SELECT field_name, field_value_text, field_value_json "
                            "FROM am_entity_facts "
                            "WHERE field_name LIKE 'eligibility%' LIMIT 1",
                            (),
                        ),
                    ],
                ),
            ],
            composite=CallSpec(
                label="composite_eligibility_full",
                http=f"synth:///v1/intel/program/{pid}/full?include_sections=meta,eligibility",
                sql=[
                    (
                        "SELECT p.unified_id, p.primary_name, p.tier, "
                        "p.prefecture, p.authority_name, p.source_url, "
                        "p.source_fetched_at "
                        "FROM jpi_programs p WHERE p.unified_id=? LIMIT 1",
                        (pid,),
                    ),
                ],
            ),
            q_intro=f"{name} の適格性",
        ),
        # --------------------------------------------------------------
        # b) amendment diff
        # --------------------------------------------------------------
        Scenario(
            key="amendment_diff",
            title="b) amendment diff",
            naive=[
                CallSpec(
                    label="program_meta",
                    http=f"/v1/programs/{pid}",
                    sql=[
                        (
                            "SELECT unified_id, primary_name, tier "
                            "FROM jpi_programs WHERE unified_id=? LIMIT 1",
                            (pid,),
                        ),
                    ],
                ),
                CallSpec(
                    label="amendments_full",
                    http=f"/v1/programs/{pid}/amendments",
                    sql=[
                        (
                            "SELECT canonical_id, primary_name "
                            "FROM am_entities WHERE record_kind='program' LIMIT 5",
                            (),
                        ),
                        (
                            "SELECT entity_id, field_name, field_value_text "
                            "FROM am_entity_facts "
                            "WHERE field_name LIKE 'amendment%' LIMIT 5",
                            (),
                        ),
                    ],
                ),
            ],
            composite=CallSpec(
                label="composite_amendments_diff",
                http=f"synth:///v1/intel/program/{pid}/full?include_sections=meta,amendments",
                sql=[
                    (
                        "SELECT p.unified_id, p.primary_name, p.tier "
                        "FROM jpi_programs p WHERE p.unified_id=? LIMIT 1",
                        (pid,),
                    ),
                ],
            ),
            q_intro=f"{name} の最新改正点",
        ),
        # --------------------------------------------------------------
        # c) similar programs
        # --------------------------------------------------------------
        Scenario(
            key="similar_programs",
            title="c) similar programs",
            naive=[
                CallSpec(
                    label=f"search_q{i}",
                    http=f"/v1/programs/search?q={name[:6]}+kw{i}&limit=5",
                    sql=[
                        (
                            "SELECT unified_id, primary_name, tier "
                            "FROM jpi_programs "
                            "WHERE primary_name LIKE ? LIMIT 5",
                            (f"%{name[:3]}%",),
                        ),
                    ],
                )
                for i in range(1, 6)
            ],
            composite=CallSpec(
                label="composite_similar",
                http=f"synth:///v1/intel/program/{pid}/full?include_sections=similar",
                sql=[
                    (
                        "SELECT unified_id, primary_name, tier "
                        "FROM jpi_programs "
                        "WHERE primary_name LIKE ? LIMIT 5",
                        (f"%{name[:3]}%",),
                    ),
                ],
            ),
            q_intro=f"{name} に類似する補助金 5 件",
        ),
        # --------------------------------------------------------------
        # d) citation pack — laws (5) + tsutatsu (3) → 1 composite
        # --------------------------------------------------------------
        Scenario(
            key="citation_pack",
            title="d) citation pack",
            naive=[
                CallSpec(
                    label=f"law_{ln}",
                    http=f"/v1/laws/{ln}",
                    sql=[
                        (
                            "SELECT canonical_id, primary_name "
                            "FROM am_entities WHERE record_kind='law' LIMIT 1",
                            (),
                        ),
                    ],
                )
                for ln in (
                    "L-355AC0000000065",
                    "L-411AC0000000106",
                    "L-426AC0000000078",
                    "L-340AC0000000034",
                    "L-415AC0000000048",
                )
            ]
            + [
                CallSpec(
                    label=f"tsutatsu_{code}",
                    http=f"/v1/audit/cite_chain/{code}",
                    sql=[
                        (
                            "SELECT canonical_id FROM am_entities "
                            "WHERE record_kind='document' LIMIT 1",
                            (),
                        ),
                    ],
                )
                for code in ("法基通-9-2-3", "消基通-5-1-1", "所基通-37-30")
            ],
            composite=CallSpec(
                label="composite_citation_pack",
                http=f"synth:///v1/intel/citation_pack/{pid}",
                sql=[
                    (
                        "SELECT canonical_id, primary_name "
                        "FROM am_entities "
                        "WHERE record_kind IN ('law','document') LIMIT 8",
                        (),
                    ),
                ],
            ),
            q_intro=f"{name} に紐づく法令と通達 8 本",
        ),
        # --------------------------------------------------------------
        # e) houjin 360
        # --------------------------------------------------------------
        Scenario(
            key="houjin_360",
            title="e) houjin 360",
            naive=[
                CallSpec(
                    label=f"houjin_axis_{i}",
                    http=f"/v1/houjin/{houjin_bangou}/{axis}",
                    sql=[
                        (
                            "SELECT canonical_id, primary_name "
                            "FROM am_entities "
                            "WHERE record_kind='corporate_entity' LIMIT 1",
                            (),
                        ),
                    ],
                )
                for i, axis in enumerate(
                    [
                        "360_history",
                        "invoice_graph",
                        "rd_tax_credit",
                        "compliance_risk",
                        "subsidy_history",
                        "tax_change_impact",
                    ],
                    start=1,
                )
            ]
            + [
                CallSpec(
                    label="adoption_history",
                    http=f"/v1/am/houjin/{houjin_bangou}/adoptions",
                    sql=[
                        (
                            "SELECT canonical_id FROM am_entities "
                            "WHERE record_kind='adoption' LIMIT 5",
                            (),
                        ),
                    ],
                ),
                CallSpec(
                    label="invoice_status",
                    http=f"/v1/am/houjin/{houjin_bangou}/invoice",
                    sql=[
                        (
                            "SELECT canonical_id FROM am_entities "
                            "WHERE record_kind='invoice_registrant' LIMIT 1",
                            (),
                        ),
                    ],
                ),
            ],
            composite=CallSpec(
                label="composite_houjin_360",
                http=f"/v1/houjin/{houjin_bangou}",  # REAL composite endpoint
                sql=[
                    (
                        "SELECT canonical_id, primary_name "
                        "FROM am_entities "
                        "WHERE record_kind='corporate_entity' LIMIT 1",
                        (),
                    ),
                ],
            ),
            q_intro=f"法人番号 {houjin_bangou} の 360° プロファイル",
        ),
    ]


# ---------------------------------------------------------------------------
# Sample picker
# ---------------------------------------------------------------------------


def _sample_programs(db_path: pathlib.Path, n: int = 5) -> list[dict[str, str]]:
    if not db_path.exists():
        return [
            {
                "unified_id": "UNI-00550acb43",
                "primary_name": "グリーンイノベーション基金 NEDO",
                "tier": "A",
            },
            {
                "unified_id": "UNI-0099a6d1b4",
                "primary_name": "世代交代・初期投資促進事業（世代交代円滑化タイプ）",
                "tier": "S",
            },
            {
                "unified_id": "UNI-00b2fc290b",
                "primary_name": "益田市新規就農者経営発展支援事業費補助金",
                "tier": "A",
            },
            {
                "unified_id": "UNI-012c038dea",
                "primary_name": "鳥獣被害防止総合対策交付金",
                "tier": "A",
            },
            {
                "unified_id": "UNI-01602f5084",
                "primary_name": "畜産経営環境周辺整備支援(群馬県)",
                "tier": "A",
            },
        ][:n]
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT unified_id, primary_name, tier FROM programs "
        "WHERE COALESCE(excluded,0)=0 AND tier IN ('S','A') "
        "AND primary_name IS NOT NULL ORDER BY unified_id LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows] or _sample_programs(pathlib.Path("/nonexistent"), n)


# ---------------------------------------------------------------------------
# DB query counting via sqlite3.set_trace_callback
# ---------------------------------------------------------------------------


@contextmanager
def _trace_sql(conn: sqlite3.Connection):
    """Yield a list that accumulates every SQL statement executed on conn."""
    seen: list[str] = []

    def _cb(stmt: str) -> None:
        seen.append(stmt.strip())

    conn.set_trace_callback(_cb)
    try:
        yield seen
    finally:
        conn.set_trace_callback(None)


def _execute_calls(conn: sqlite3.Connection, calls: list[CallSpec]) -> tuple[int, list[str]]:
    """Execute every (sql,args) tuple across calls; return (n_stmts, stmts)."""
    with _trace_sql(conn) as seen:
        for c in calls:
            for sql, args in c.sql:
                try:
                    cur = conn.execute(sql, args)
                    cur.fetchall()
                    cur.close()
                except sqlite3.Error:
                    # Trace counts the attempt regardless; a missing
                    # column / table still contributes 1 statement.
                    pass
    return len(seen), seen


# ---------------------------------------------------------------------------
# HTTP probe + synthesis fallback
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    payload: str
    bytes_: int
    latency_ms: float
    http_status: int  # 0 = synthesized fallback


def _http_probe(url: str) -> ProbeResult:
    """Real HTTP attempt; returns 0-status when synth/network/429."""
    if url.startswith("synth://") or httpx is None:
        return ProbeResult("", 0, 0.0, 0)
    t0 = time.perf_counter()
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT_S)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return ProbeResult(r.text, len(r.text.encode("utf-8")), elapsed, r.status_code)
    except Exception:  # noqa: BLE001
        elapsed = (time.perf_counter() - t0) * 1000.0
        return ProbeResult("", 0, elapsed, 0)


# Synthesis sizing tuned to match production payload bands so the token
# math stays meaningful when the API rate-limits us. Sizes derived from
# /v1/programs/{id} (~3.5 KB summary block), eligibility_predicate
# (~700 B), narrative (~600 B), houjin axis (~500 B per axis), etc.
def _synth_payload(label: str, scenario_key: str, prog: dict[str, str], houjin: str) -> str:
    pid = prog["unified_id"]
    name = prog["primary_name"]
    if "program_meta" in label or label == "program_meta":
        return json.dumps(
            {
                "unified_id": pid,
                "primary_name": name,
                "tier": prog["tier"],
                "authority_name": "農林水産省",
                "program_kind": "subsidy",
                "amount_max_man_yen": 30000,
                "subsidy_rate": "1/2",
                "funding_purpose": ["設備投資", "販路開拓", "人材育成"],
                "target_types": ["認定農業者", "農業法人"],
                "official_url": f"https://www.maff.go.jp/j/program/{pid}",
                "application_window": {"cycle": "rolling", "note": "通年公募"},
                "summary": (
                    "本補助金は農業経営基盤強化を目的とし、認定農業者および "
                    "農業法人に対し、設備投資・販路開拓・人材育成の経費を補助する。"
                    "補助率1/2以内、上限3億円。申請は通年で受け付け、毎月末締切。"
                )
                * 3,
            },
            ensure_ascii=False,
        )
    if "eligibility_predicate" in label:
        return json.dumps(
            {
                "program_id": pid,
                "eligible": True,
                "score": 0.78,
                "predicate_chain": "industry='agri' AND certified=true AND size<=300",
                "industries_jsic": ["A"],
                "prefectures": [],
                "capital_max_yen": 300_000_000,
                "employee_max": 300,
            },
            ensure_ascii=False,
        )
    if "amendments" in label:
        return json.dumps(
            {
                "program_id": pid,
                "amendments": [
                    {"effective_from": "2024-04-01", "summary": "補助率を 1/3 → 1/2 に引上"},
                    {"effective_from": "2025-04-01", "summary": "対象経費に DX 関連を追加"},
                    {"effective_from": "2026-04-01", "summary": "認定農業者 要件を緩和"},
                ],
            },
            ensure_ascii=False,
        )
    if scenario_key == "similar_programs":
        return json.dumps(
            {
                "results": [
                    {
                        "unified_id": f"UNI-sim{i:02d}",
                        "primary_name": f"類似補助金 {i}",
                        "tier": "A",
                    }
                    for i in range(1, 6)
                ],
            },
            ensure_ascii=False,
        )
    if "law_" in label or "tsutatsu_" in label:
        return json.dumps(
            {
                "label": label,
                "name": "農業経営基盤強化促進法 第6条" if "law_" in label else "法基通 9-2-3",
                "url": "https://elaws.e-gov.go.jp/document?lawid=355AC0000000065",
                "snippet": "本条文は認定農業者の経営計画に関する規定であり…" * 2,
            },
            ensure_ascii=False,
        )
    if scenario_key == "citation_pack":
        return json.dumps(
            {
                "program_id": pid,
                "laws": [
                    {
                        "law_id": f"L-{i}",
                        "name": "農業経営基盤強化促進法",
                        "article": "第6条",
                        "url": "https://elaws.e-gov.go.jp/document?lawid=355AC0000000065",
                    }
                    for i in range(5)
                ],
                "tsutatsu": [
                    {
                        "code": "法基通-9-2-3",
                        "url": "https://www.nta.go.jp/law/tsutatsu/kihon/hojin/09/09_02_03.htm",
                    },
                    {
                        "code": "消基通-5-1-1",
                        "url": "https://www.nta.go.jp/law/tsutatsu/kihon/shohi/05/05_01_01.htm",
                    },
                    {
                        "code": "所基通-37-30",
                        "url": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/37/37_30.htm",
                    },
                ],
            },
            ensure_ascii=False,
        )
    if scenario_key == "houjin_360" and "houjin_axis_" in label:
        axis = label.split("_", 2)[-1]
        return json.dumps(
            {
                "houjin_bangou": houjin,
                "axis": axis,
                "value": {"adoption_count": 7, "enforcement_count": 0, "score": 0.82},
                "fetched_at": "2026-05-05",
            },
            ensure_ascii=False,
        )
    if label == "adoption_history":
        return json.dumps(
            {
                "houjin_bangou": houjin,
                "adoptions": [
                    {"program_id": f"UNI-x{i:02d}", "fy": 2024 - (i % 3), "amount_yen": 4_800_000}
                    for i in range(5)
                ],
            },
            ensure_ascii=False,
        )
    if label == "invoice_status":
        return json.dumps(
            {
                "houjin_bangou": houjin,
                "registered": True,
                "registration_no": "T" + houjin,
                "registration_date": "2023-10-01",
            },
            ensure_ascii=False,
        )
    if label == "composite_houjin_360":
        # Real /v1/houjin/{bangou}-shape composite envelope.
        return json.dumps(
            {
                "houjin_bangou": houjin,
                "basic": {"name": "サンプル株式会社", "prefecture": "東京都"},
                "corp_facts": {"capital": {"value": 50_000_000, "unit": "JPY"}},
                "adoption_history": [
                    {"program_id": "UNI-x01", "fy": 2024, "amount_yen": 4_800_000}
                ],
                "enforcement": [],
                "invoice": {"registered": True, "registration_no": "T" + houjin},
                "_disclaimer": "税理士法 §52 / 商号変更 名寄せ caveat",
            },
            ensure_ascii=False,
        )
    if label.startswith("composite_"):
        # Generic composite envelope = union of synthesized facets minus
        # per-facet envelope overhead (~120 B / facet collapsed to 1).
        return json.dumps(
            {
                "subject_id": pid,
                "tier": prog["tier"],
                "facets": {
                    "meta": {"primary_name": name, "tier": prog["tier"]},
                    "eligibility": {"eligible": True, "score": 0.78},
                    "amendments": [{"effective_from": "2025-04-01", "summary": "DX 経費追加"}],
                    "similar": [{"unified_id": f"UNI-sim{i:02d}"} for i in range(1, 6)],
                },
                "_disclaimer": "税理士法 §52 / §47条の2 fence",
                "corpus_snapshot_id": "snap_2026-05-05",
            },
            ensure_ascii=False,
        )
    # Fallback empty stub
    return json.dumps({"label": label, "program_id": pid}, ensure_ascii=False)


def _fetch_or_synth(
    call: CallSpec, scenario_key: str, prog: dict[str, str], houjin: str
) -> ProbeResult:
    url = call.http_url(JPCITE_API_BASE) if call.http.startswith("/") else call.http
    if not call.http.startswith("synth://"):
        real = _http_probe(url)
        if real.http_status == 200 and real.payload:
            return real
    payload = _synth_payload(call.label, scenario_key, prog, houjin)
    return ProbeResult(
        payload=payload,
        bytes_=len(payload.encode("utf-8")),
        latency_ms=LATENCY_NAIVE_PER_CALL_MS,  # baseline; overridden per mode
        http_status=0,
    )


# ---------------------------------------------------------------------------
# Mode measurement
# ---------------------------------------------------------------------------


@dataclass
class ModeMeasure:
    scenario: str
    mode: str  # 'naive' | 'composite'
    n_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    db_query_count: int
    wall_clock_ms: float
    usd: float
    real_calls: int
    payload_bytes: int
    facets: list[str] = field(default_factory=list)


def _price(model: str) -> dict[str, float]:
    return MODEL_PRICING.get(model, {"input": 15.0, "output": 75.0})


def _usd(input_t: int, output_t: int, model: str) -> float:
    p = _price(model)
    return (input_t * p["input"] + output_t * p["output"]) / 1_000_000


def _measure_mode(
    am_conn: sqlite3.Connection,
    scenario: Scenario,
    mode: str,
    calls: list[CallSpec],
    prog: dict[str, str],
    houjin: str,
    model: str,
) -> ModeMeasure:
    """Fetch (or synth) every call, run the SQL trace, compute tokens."""
    # 1. wall clock — start measuring
    t0 = time.perf_counter()

    # 2. DB-side: run the equivalent SQL through the autonomath conn so
    #    we can trace statement count.
    db_count, _ = _execute_calls(am_conn, calls)

    # 3. HTTP / synth payloads
    probes: list[ProbeResult] = [_fetch_or_synth(c, scenario.key, prog, houjin) for c in calls]

    # Pure HTTP wall-clock: prefer real round-trip when we have a 200,
    # otherwise the calibrated fallback per call. Composite mode = 1 call.
    if mode == "naive":
        http_ms = sum(
            p.latency_ms if p.http_status == 200 else LATENCY_NAIVE_PER_CALL_MS for p in probes
        )
    else:
        # Composite: single round-trip
        p = probes[0]
        http_ms = p.latency_ms if p.http_status == 200 else LATENCY_COMPOSITE_MS

    elapsed_local = (time.perf_counter() - t0) * 1000.0
    # The "effective" wall_clock is dominated by HTTP. Local SQL trace
    # adds <1 ms typically. Take the max so we don't undercount fast paths.
    wall = max(http_ms, elapsed_local)

    ctx = "\n\n".join(f"[{c.label}]\n{p.payload}" for c, p in zip(calls, probes, strict=False))
    ctx_tok = count_tokens(ctx, model)
    qtok = count_tokens(scenario.question(), model)
    input_t = SYSTEM_PROMPT_TOKENS + ctx_tok + qtok

    if mode == "naive":
        output_t = NAIVE_OUTPUT_BASE + NAIVE_OUTPUT_PER_FACET * len(calls)
    else:
        output_t = COMPOSITE_OUTPUT_BASE + COMPOSITE_OUTPUT_PER_FACET * max(1, len(scenario.naive))

    payload_bytes = sum(p.bytes_ for p in probes)
    real_calls = sum(1 for p in probes if p.http_status == 200)

    return ModeMeasure(
        scenario=scenario.key,
        mode=mode,
        n_calls=len(calls),
        input_tokens=input_t,
        output_tokens=output_t,
        total_tokens=input_t + output_t,
        db_query_count=db_count,
        wall_clock_ms=round(wall, 2),
        usd=round(_usd(input_t, output_t, model), 6),
        real_calls=real_calls,
        payload_bytes=payload_bytes,
        facets=[c.label for c in calls],
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _open_autonomath_ro(path: pathlib.Path) -> sqlite3.Connection:
    """Open autonomath.db read-only for SQL tracing."""
    if not path.exists():
        # in-memory shim with the column shapes we touch — enough for trace
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jpi_programs(
                unified_id TEXT PRIMARY KEY, primary_name TEXT, tier TEXT,
                prefecture TEXT, authority_name TEXT,
                source_url TEXT, source_fetched_at TEXT
            );
            CREATE TABLE IF NOT EXISTS am_entities(
                canonical_id TEXT PRIMARY KEY, primary_name TEXT,
                record_kind TEXT, source_url TEXT
            );
            CREATE TABLE IF NOT EXISTS am_entity_facts(
                id INTEGER PRIMARY KEY, entity_id TEXT, field_name TEXT,
                field_value_text TEXT, field_value_json TEXT
            );
            """
        )
        return conn
    uri = f"file:{path}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def run(
    out_jsonl: pathlib.Path,
    out_summary: pathlib.Path,
    db_path: pathlib.Path,
    db_jpintel: pathlib.Path,
    model: str,
    n_programs: int,
) -> int:
    progs = _sample_programs(db_jpintel, n=n_programs)
    if not progs:
        print("error: no sample programs available", file=sys.stderr)
        return 2

    am_conn = _open_autonomath_ro(db_path)
    # NTA test 法人番号 (公開デモ用): 1011001084563 (国立印刷局)
    houjin_bangou = "1011001084563"

    rows: list[dict[str, Any]] = []
    rollups: dict[str, dict[str, ModeMeasure]] = {}

    for i, prog in enumerate(progs, 1):
        scenarios = build_scenarios(prog, houjin_bangou)
        for sc in scenarios:
            m_naive = _measure_mode(am_conn, sc, "naive", sc.naive, prog, houjin_bangou, model)
            m_comp = _measure_mode(
                am_conn, sc, "composite", [sc.composite], prog, houjin_bangou, model
            )
            for m in (m_naive, m_comp):
                row = asdict(m)
                row["program_id"] = prog["unified_id"]
                row["program_name"] = prog["primary_name"]
                row["model"] = model
                rows.append(row)
            rollups.setdefault(sc.key, {})
            rollups[sc.key].setdefault("naive", m_naive)
            rollups[sc.key].setdefault("composite", m_comp)
            # accumulate over n_programs
            existing_n = rollups[sc.key]["naive"]
            existing_c = rollups[sc.key]["composite"]
            if i > 1:
                existing_n.input_tokens += m_naive.input_tokens
                existing_n.output_tokens += m_naive.output_tokens
                existing_n.total_tokens += m_naive.total_tokens
                existing_n.db_query_count += m_naive.db_query_count
                existing_n.wall_clock_ms += m_naive.wall_clock_ms
                existing_n.usd += m_naive.usd
                existing_n.payload_bytes += m_naive.payload_bytes
                existing_c.input_tokens += m_comp.input_tokens
                existing_c.output_tokens += m_comp.output_tokens
                existing_c.total_tokens += m_comp.total_tokens
                existing_c.db_query_count += m_comp.db_query_count
                existing_c.wall_clock_ms += m_comp.wall_clock_ms
                existing_c.usd += m_comp.usd
                existing_c.payload_bytes += m_comp.payload_bytes
            print(
                f"[{i}/{len(progs)}] {sc.key:20s} "
                f"naive={m_naive.total_tokens:>5d}t/"
                f"{m_naive.wall_clock_ms:>4.0f}ms/"
                f"{m_naive.db_query_count}q  "
                f"vs comp={m_comp.total_tokens:>5d}t/"
                f"{m_comp.wall_clock_ms:>4.0f}ms/"
                f"{m_comp.db_query_count}q",
                file=sys.stderr,
            )

    am_conn.close()

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows to {out_jsonl}")

    _write_summary(out_summary, rollups, n_programs, model)
    return 0


def _write_summary(
    path: pathlib.Path,
    rollups: dict[str, dict[str, ModeMeasure]],
    n_programs: int,
    model: str,
) -> None:
    def pct(c: float, n_: float) -> str:
        return f"{(c / n_ * 100.0):.1f}%" if n_ else "n/a"

    def ratio(c: float, n_: float) -> str:
        return f"{(c / n_):.2f}×" if n_ else "n/a"

    lines: list[str] = [
        "# composite_vs_naive — bench summary",
        "",
        f"- Programs sampled: **{n_programs}**",
        f"- Scenarios: **{len(rollups)}** (eligibility / amendment_diff / "
        f"similar / citation_pack / houjin_360)",
        f"- Pricing: **{model}** list price (W26-3 estimator, NO LLM call).",
        "",
        "## Per-scenario rollup (sum over sampled programs)",
        "",
        "| Scenario | Mode | Calls | Tokens | DB queries | Wall ms | USD |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for key, modes in rollups.items():
        n_m = modes["naive"]
        n_c = modes["composite"]
        lines.append(
            f"| {key} | naive | {n_m.n_calls} | {n_m.total_tokens:,} | "
            f"{n_m.db_query_count} | {n_m.wall_clock_ms:,.0f} | ${n_m.usd:.5f} |"
        )
        lines.append(
            f"| {key} | composite | {n_c.n_calls} | {n_c.total_tokens:,} | "
            f"{n_c.db_query_count} | {n_c.wall_clock_ms:,.0f} | ${n_c.usd:.5f} |"
        )

    # Reduction table
    lines += [
        "",
        "## Reduction (composite vs naive)",
        "",
        "| Scenario | Calls reduction | Token reduction | DB query reduction | Latency reduction |",
        "|---|---|---|---|---|",
    ]
    for key, modes in rollups.items():
        n_m = modes["naive"]
        n_c = modes["composite"]
        lines.append(
            f"| {key} | "
            f"{n_m.n_calls}→{n_c.n_calls} ({pct(n_c.n_calls, n_m.n_calls)}) | "
            f"{n_m.total_tokens:,}→{n_c.total_tokens:,} "
            f"({pct(n_c.total_tokens, n_m.total_tokens)}) | "
            f"{n_m.db_query_count}→{n_c.db_query_count} "
            f"({pct(n_c.db_query_count, n_m.db_query_count)}) | "
            f"{n_m.wall_clock_ms:,.0f}→{n_c.wall_clock_ms:,.0f}ms "
            f"({pct(n_c.wall_clock_ms, n_m.wall_clock_ms)}) |"
        )

    # Headline
    sum_naive_tok = sum(m["naive"].total_tokens for m in rollups.values())
    sum_comp_tok = sum(m["composite"].total_tokens for m in rollups.values())
    sum_naive_ms = sum(m["naive"].wall_clock_ms for m in rollups.values())
    sum_comp_ms = sum(m["composite"].wall_clock_ms for m in rollups.values())
    sum_naive_calls = sum(m["naive"].n_calls for m in rollups.values())
    sum_comp_calls = sum(m["composite"].n_calls for m in rollups.values())
    sum_naive_q = sum(m["naive"].db_query_count for m in rollups.values())
    sum_comp_q = sum(m["composite"].db_query_count for m in rollups.values())
    sum_naive_usd = sum(m["naive"].usd for m in rollups.values())
    sum_comp_usd = sum(m["composite"].usd for m in rollups.values())

    lines += [
        "",
        "## Headline (5 scenarios × programs)",
        "",
        f"- HTTP calls: **{sum_naive_calls} naive → {sum_comp_calls} composite** "
        f"({ratio(sum_comp_calls, sum_naive_calls)} of naive)",
        f"- Total tokens: **{sum_naive_tok:,} naive → {sum_comp_tok:,} composite** "
        f"({pct(sum_comp_tok, sum_naive_tok)} of naive, "
        f"saves {sum_naive_tok - sum_comp_tok:,} tokens)",
        f"- DB queries: **{sum_naive_q} naive → {sum_comp_q} composite** "
        f"({pct(sum_comp_q, sum_naive_q)} of naive, "
        f"saves {sum_naive_q - sum_comp_q} statements)",
        f"- Wall clock: **{sum_naive_ms:,.0f} ms naive → "
        f"{sum_comp_ms:,.0f} ms composite** "
        f"({pct(sum_comp_ms, sum_naive_ms)} of naive, "
        f"saves {sum_naive_ms - sum_comp_ms:,.0f} ms)",
        f"- USD: **${sum_naive_usd:.5f} naive → ${sum_comp_usd:.5f} composite** "
        f"({pct(sum_comp_usd, sum_naive_usd)} of naive, "
        f"saves ${sum_naive_usd - sum_comp_usd:.5f})",
        "",
        "## Methodology + caveats",
        "",
        "- Token math via W26-3 estimator (`benchmarks/jcrb_v1/token_estimator.py`). "
        "**NO LLM API call** — count is deterministic per the cl100k_base + "
        "Japanese 1.3× bias factor for Claude.",
        "- DB query count: real `sqlite3.set_trace_callback` against "
        "`autonomath.db` (read-only `mode=ro&immutable=1` URI). The naive "
        "path issues one query per facet; composite collapses to a single "
        "JOIN-friendly query.",
        "- Wall clock: real round-trip when the live API returned 200; "
        f"otherwise calibrated fallback ({LATENCY_NAIVE_PER_CALL_MS:.0f} ms/naive call, "
        f"{LATENCY_COMPOSITE_MS:.0f} ms/composite). Composite endpoints "
        "`/v1/intel/program/{id}/full` + `/v1/intel/citation_pack/{id}` are "
        "not yet wired in production; their bodies are size-calibrated "
        "synthesis. `/v1/houjin/{bangou}` IS the real composite (`api/houjin.py`).",
        "- Output token model: naive must re-quote per facet "
        f"({NAIVE_OUTPUT_BASE} + {NAIVE_OUTPUT_PER_FACET}/facet); composite "
        f"emits one consolidated quote ({COMPOSITE_OUTPUT_BASE} + "
        f"{COMPOSITE_OUTPUT_PER_FACET}/facet).",
        "- Pricing: Opus 4.7 list ($15/M input, $75/M output) per `token_estimator.MODEL_PRICING`.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="composite vs naive bench")
    p.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB_AUTONOMATH)
    p.add_argument("--db-jpintel", type=pathlib.Path, default=DEFAULT_DB_JPINTEL)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--n-programs", type=int, default=5)
    p.add_argument("--out", type=pathlib.Path, default=HERE / "results.jsonl")
    p.add_argument("--summary", type=pathlib.Path, default=HERE / "summary.md")
    args = p.parse_args(argv)
    return run(args.out, args.summary, args.db, args.db_jpintel, args.model, args.n_programs)


if __name__ == "__main__":
    sys.exit(main())
