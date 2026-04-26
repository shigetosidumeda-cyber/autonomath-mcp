# reasoning/ — archived 2026-04-25

## Why archived
Layer 7 v0.1.0 — 「決定木 + graph traversal cache」のスケルトンのみ。本番 path 未接続。
K3 audit (`analysis_wave18/_k3_dead_code_2026-04-25.md`) confirmed:
- `__init__.py` は `__version__ = "0.1.0"` のみ
- `bind_i01..i10` / `bind_registry` / `precompute` / `samples` / `bound_samples` / `match` / `query_route` / `query_types` 全て直接 import 0 件
- `envelope_wrapper.py` 内に `from reasoning.query_route import route` (top-level `reasoning`、jpintel_mcp.reasoning ではない) があるが、try/except で捕捉される soft import。`reasoning` は sys.path top-level に無いので必ず ImportError → None fallback

`tests/test_autonomath_tools.py::test_intent_of_happy_or_subsystem_unavailable` は subsystem 不在を想定して書かれている。archive 後も "subsystem_unavailable" envelope path で pass。

## When to revive
- intent classification / query routing を本番 envelope に組み込む判断時
- `bind_i01..i10` の決定木を本番 retrieval ranking に投入するとき
- `query_route.route()` を `envelope_wrapper.py` の explain_empty 生成で正式採用する判断時

## Recovery steps
```bash
mv src/jpintel_mcp/_archive/reasoning_2026-04-25 src/jpintel_mcp/reasoning
# envelope_wrapper.py の try import を `from jpintel_mcp.reasoning.query_route import route` に正式化するか、
# sys.path に top-level `reasoning` を追加して既存 try を活かすか選択
.venv/bin/pytest tests/test_autonomath_tools.py -q
```

## Files (18)
- `__init__.py` (`__version__ = "0.1.0"`)
- `bind_i01.py` … `bind_i10.py` 10 intent decision trees
- `bind_registry.py` registry index
- `bound_samples.py` precomputed bound samples
- `match.py` match scorer
- `precompute.py` graph cache builder
- `query_route.py` route() entrypoint (envelope_wrapper soft consumer)
- `query_types.py` enum
- `samples.py` raw training samples
- `trees/` (subdir, decision-tree pickled artifacts)
