# Hallucination Guard

LLM が生成した回答に紛れやすい **高頻度な制度誤解** を検出し、注意書きと確認すべき根拠を返すための仕組みです。

## 目的

補助金 / 税制 / 融資 / 認定 / 行政処分 / 法令の典型的な誤解表現を検出し、`correction` と `law_basis` を一緒に返します。jpcite サーバー側で LLM 推論は行いません。

## 返す内容

| field | 意味 |
|---|---|
| `phrase` | 検出された誤解表現 |
| `severity` | 注意の強さ |
| `correction` | どう直して読むべきか |
| `law_basis` | 関連する根拠法令・制度資料 |
| `audience` | 主な利用者カテゴリ |
| `vertical` | 補助金、税制、融資などの領域 |

## 拡張方針

誤解表現は、公開資料・利用者からのフィードバック・検証済みの失敗例をもとに増やします。追加前に人が確認し、誤検出が多い表現は公開レスポンスに昇格しません。

## 関連

- [confidence_methodology.md](./confidence_methodology.md) — Bayesian Discovery / Use
- [honest_capabilities.md](./honest_capabilities.md) — 何を保証するか / しないか
