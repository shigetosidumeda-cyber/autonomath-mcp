# Wave 51 L2 数学エンジン API spec — sweep / pareto / montecarlo

**status**: 設計のみ / 実装禁止 (design doc only, no implementation)
**author**: jpcite ops
**date**: 2026-05-16
**SOT marker**: `docs/_internal/WAVE51_L2_MATH_ENGINE_API_SPEC.md`
**parent**: `docs/_internal/WAVE51_L1_L2_DESIGN.md` (Wave 51 L1+L2 baseline)
**scope**: L2 (Vertical depth) — 14 outcome 内 LLM 不要数学エンジン。3 algorithm × 3 MCP tool × 3 REST endpoint の API 表面を凍結

---

## 0. 位置付け

Wave 51 L2 は RC1 contract layer の上に **pure math engine** を積む。`composed_tools/` 3 new entry を MCP 経由で 1 call exposure、Anthropic / OpenAI / Google AI SDK の import は 0 件、reasoning は `rule_id` + `parameter trace` の string list のみで完結する。本 doc は **Pydantic model 表面 + MCP tool manifest + REST endpoint OpenAPI sketch + 配置 + test fixture** を凍結し、Wave 51 実装フェーズの contract 入り口となる。

---

## 1. Pydantic model (StrictModel)

### 1.1 MathEngineRequest

```python
class MathEngineRequest(StrictModel):
    request_id: str  # UUID v4
    algorithm: Literal["sweep", "pareto", "montecarlo"]
    outcome_contract_id: str  # 14 outcome のいずれか
    parameter_dimensions: tuple[ParameterDimension, ...]
    objective_axes: tuple[ObjectiveAxis, ...]  # for pareto / montecarlo
    max_candidates: int = 200  # sweep
    n_samples: int = 5000  # montecarlo
    seed: int = 0  # deterministic
    as_of_date: str | None = None  # time-machine integration (Dim Q)

class ParameterDimension(StrictModel):
    name: str  # e.g., "subsidy_amount", "industry_code", "prefecture"
    type: Literal["enum", "range", "boolean"]
    values: tuple[Any, ...]  # for enum / boolean
    min: float | None = None  # for range
    max: float | None = None  # for range
    step: float | None = None  # for range

class ObjectiveAxis(StrictModel):
    name: str  # e.g., "cost", "risk", "match_score"
    direction: Literal["minimize", "maximize"]
    weight: float = 1.0  # for weighted combination
    distribution: Literal["empirical", "norm", "beta", "triangular"] | None = None  # montecarlo only
```

### 1.2 MathEngineResult

```python
class MathEngineResult(StrictModel):
    schema_version: Literal["jpcite.math_engine.p0.v1"]
    request_id: str
    algorithm: Literal["sweep", "pareto", "montecarlo"]
    outcome_contract_id: str
    ranked_candidates: tuple[RankedCandidate, ...]
    pareto_front: tuple[RankedCandidate, ...] | None  # for pareto
    summary_stats: dict[str, float]  # montecarlo: mean/p5/p25/p50/p75/p95
    computation_time_ms: float
    request_time_llm_call_performed: Literal[False] = False  # NO LLM 厳守

class RankedCandidate(StrictModel):
    candidate_id: str
    parameter_values: dict[str, Any]
    objective_scores: dict[str, float]
    rank: int
    reasoning_path: tuple[str, ...]  # rule_id list, 自然言語禁止
    confidence_bucket: Literal["high", "medium", "low"]
```

**Pydantic model count**: 5 (MathEngineRequest / ParameterDimension / ObjectiveAxis / MathEngineResult / RankedCandidate)

---

## 2. MCP tool manifest (composed_tools/)

既存 `jpcite_route` / `preview_cost` / `execute_packet` / `get_packet` に加わる **新 3 tool**。各 tool は `composed_tools/` 配下に MCP manifest entry を持つ。

| tool name | algorithm | description (preview) |
|---|---|---|
| `composed_tools/sweep_outcome_grid` | sweep | grid sweep over parameter_dimensions, top-N by weighted objective |
| `composed_tools/pareto_outcome_front` | pareto | non-dominated front extraction over objective_axes |
| `composed_tools/montecarlo_outcome_uncertainty` | montecarlo | distribution sampling + p5/p25/p50/p75/p95 summary |

manifest entry 共通 schema (excerpt):

```yaml
- name: composed_tools/sweep_outcome_grid
  description: deterministic grid sweep, NO LLM, returns ranked candidates
  input_schema_ref: $defs/MathEngineRequest
  output_schema_ref: $defs/MathEngineResult
  cost_class: math_engine_p0
  llm_call: false
```

---

## 3. REST endpoint (api/jpcite_facade.py 拡張)

`api/jpcite_facade.py` に 3 endpoint 追加 (or 新 facade `api/jpcite_math_facade.py` 分離可、実装時判断)。

| method | path | algorithm | requestBody | response |
|---|---|---|---|---|
| POST | `/v1/jpcite/math/sweep` | sweep | `MathEngineRequest` | `MathEngineResult` |
| POST | `/v1/jpcite/math/pareto` | pareto | `MathEngineRequest` | `MathEngineResult` |
| POST | `/v1/jpcite/math/montecarlo` | montecarlo | `MathEngineRequest` | `MathEngineResult` |

OpenAPI sketch (sweep 抜粋):

```yaml
/v1/jpcite/math/sweep:
  post:
    operationId: math_sweep
    requestBody:
      required: true
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/MathEngineRequest'
    responses:
      '200':
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/MathEngineResult'
```

pareto / montecarlo も同形 ($ref のみ差し替え)。

---

## 4. implementation 配置 (Wave 51 実装フェーズ)

```
src/jpintel_mcp/services/math_engine/
├── sweep.py          # grid enumeration + weighted ranking
├── pareto.py         # non-dominated sort (O(N^2) for N <= 200, fast enough)
├── montecarlo.py     # numpy.random.default_rng(seed) + scipy.stats sampling
├── _common.py        # shared StrictModel, schema_version constant
└── _validators.py    # ParameterDimension / ObjectiveAxis runtime validation
```

依存: **numpy + scipy のみ** (既存依存)。`import anthropic` / `import openai` / `import google.generativeai` は import-guard で禁止。

---

## 5. test fixture 設計

| test file | 件数 | 主眼 |
|---|---|---|
| `tests/test_math_engine_sweep.py` | ~25 | grid 200 candidate / deterministic seed / NO LLM import guard / perf < 100ms |
| `tests/test_math_engine_pareto.py` | ~20 | non-dominated front correctness / 2-3 objective axes / perf < 200ms |
| `tests/test_math_engine_montecarlo.py` | ~25 | seed=0 reproducibility / 5000 sample / p5/p95 stat / perf < 500ms |
| `tests/test_math_engine_integration.py` | ~15 | 3 algorithm cross / outcome_contract_id × 14 / as_of_date time-machine |

**test fixture count: 4 file × 85 tests 合計**。共通 fixture:

- **deterministic**: `seed=0` で同入力 → 同出力 (`assert result_a == result_b`)。
- **NO LLM**: `mypy --strict` + `pytest` 内 `import` 監視 (anthropic / openai / google AI SDK が import tree に居ない事を確認)。
- **performance**: `pytest-benchmark` で sweep 200 / pareto 200 / montecarlo 5000 の上限 ms 超過時 FAIL。
- **schema lock**: `schema_version="jpcite.math_engine.p0.v1"` を破壊する PR は CI block。

---

## 6. NO LLM 厳守

- Anthropic / OpenAI / Google AI SDK **import 0** (実装 + test 両方)。
- 全 reasoning は `rule_id` + `parameter trace` の string list (`RankedCandidate.reasoning_path`)。
- 自然言語 summary 生成は **別 stream** (Wave 52+ で copilot scaffold 検討、本 Wave では out of scope)。
- `request_time_llm_call_performed: Literal[False] = False` を MathEngineResult に固定し、型システムレベルで LLM 呼出を排除。

---

## 7. summary numbers

- **Pydantic model**: 5 (Request / Dimension / Axis / Result / Candidate)
- **MCP tool**: 3 (`composed_tools/{sweep,pareto,montecarlo}_outcome_*`)
- **REST endpoint**: 3 (POST `/v1/jpcite/math/{sweep,pareto,montecarlo}`)
- **service module**: 5 (`sweep.py` / `pareto.py` / `montecarlo.py` / `_common.py` / `_validators.py`)
- **test file**: 4 (sweep / pareto / montecarlo / integration), 合計 ~85 tests
- **schema_version**: `jpcite.math_engine.p0.v1`

---

## 8. back-link

- **parent design doc**: [`WAVE51_L1_L2_DESIGN.md`](WAVE51_L1_L2_DESIGN.md) (L1 source expansion + L2 math engine baseline)
- **prior**: Wave 50 RC1 contract layer (14 outcome / 19 Pydantic model / 20 JSON Schema)
- **next**: `docs/_internal/WAVE51_plan.md` (未作成、本 spec を contract 入り口に起票予定)

---

**SOT marker**: `docs/_internal/WAVE51_L2_MATH_ENGINE_API_SPEC.md`
**status**: design doc only, no implementation in this PR
