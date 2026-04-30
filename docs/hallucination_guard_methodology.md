# Hallucination Guard

LLM が生成した回答に紛れる **高頻度な制度誤解** を、API 出力の前段で検出するためのフィルタ。

## 目的

`hallucination_guard` は補助金 / 税制 / 融資 / 認定 / 行政処分 / 法令 の典型的な誤解 phrase を検出し、`correction` と `law_basis` を一緒に surface する。LLM 推論は API 側では行わない (推論は顧客側 LLM)。

## データ構造

`data/hallucination_guard.yaml` (v1 = **60 entries**)。

```yaml
entries:
  - phrase: "..."         # verbatim misconception
    severity: high        # high | medium | low
    correction: "..."     # one-line correction
    law_basis: "..."      # optional 法律名 + 条
    audience: 税理士       # 税理士 | 行政書士 | SMB | VC | Dev
    vertical: 税制         # 補助金 | 税制 | 融資 | 認定 | 行政処分 | 法令
```

Grid = 5 audience × 6 vertical × 2 phrase = 60 entries。

## ランタイム

`src/jpintel_mcp/self_improve/loop_a_hallucination_guard.py`:

- `match(text) -> list[dict]` — substring scan、pure (DB / network 不使用)
- `summarize() -> dict` — severity / audience / vertical 別カウント

## 拡張 (60 → 1,500+)

cron による継続拡張は内部運用 (詳細非公開)。candidate は all `*_candidates` テーブル経由で人手 review してから昇格する。

## 関連

- [confidence_methodology.md](./confidence_methodology.md) — Bayesian Discovery / Use
- [honest_capabilities.md](./honest_capabilities.md) — 何を保証するか / しないか
