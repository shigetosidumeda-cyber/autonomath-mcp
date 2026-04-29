# Confidence — Methodology (P5-attribution)

`/v1/stats/confidence` は 税務会計AI の **Bayesian 信頼度** ダッシュボードです。
tool 単位で **Discovery** (見つけられる確率) と **Use** (実 action に変わる確率) を
推定し、95% credible interval と一緒に公開しています。本ページはそのモデル定義 (式・前提・PII の扱い) をまとめたものです。

## 1. 数値目標

| 指標 | T+90d | Y1 |
| --- | --- | --- |
| Discovery | 90% | 95% |
| Use | 80% | 92% |

これは v8 plan の P5-attribution セクションで合意した北極星 (north-star) 値です。

## 2. 定義

### 2.1 Discovery

> Discovery_T = P(found_result | invoked)

- **trial**: tool `T` への 1 回の呼び出し
- **success**: その呼び出しが 1 行以上の結果を返した (= `result_count > 0`、
  もしくは `result_bucket != "0"`) もの
- データ源: `query_log_v2` の `tool` / `result_bucket` / `result_count` 列

「呼び出した結果ゼロ件」は **見つけられなかった** の状態で、Discovery のミスとして
カウントします。これがモデルがゼロ件 SERP を penalize する数学的な理由です。

### 2.2 Use

> Use_T = P(returned_within_7d | first_invocation)

- **trial**: 各 (api_key_hash, tool) の **最初** のイベント (= 初回呼び出し)
- **success**: 同じ (api_key_hash, tool) で 7 日以内に再度の呼び出しがあった
- データ源: `usage_events` の `key_hash` / `endpoint` / `ts` 列

匿名 (`key_hash IS NULL`) のリクエストは識別不能なので Use の計算から除外します。
Discovery は匿名でも計算できますが、Use の母集団は authenticated 顧客に限定します。

7 日 window は **「retention の確認」を「one-shot trial」と切り分ける** ための
閾値で、長すぎる (e.g. 30 日) と "1 回だけ試して 3 週間放置" まで hit に入って
しまい、短すぎる (e.g. 1 日) と LLM の context が切れた翌日訪問が miss になります。

## 3. Bayesian モデル

各 tool の確率は独立 Bernoulli プロセスとしてモデル化します。

- **事前分布**: `Beta(1, 1)` (= Uniform[0, 1])
- **事後分布**: `Beta(α + hits, β + trials − hits)` (共役事前による閉形式)
- **95% credible interval**: `scipy.stats.beta.interval(0.95, α, β)`

### 3.1 サンプル計算

`Beta(1, 1)` + 80 hit / 100 trial を観測した場合:

```
posterior     = Beta(1 + 80, 1 + 100 − 80) = Beta(81, 21)
posterior mean = 81 / (81 + 21) = 0.7941…
95% CI        ≈ [0.711, 0.866]
```

事後平均は 79.4% で、Use の T+90d 目標 (80%) を **わずかに下回ります**。CI は
71%–87% なので「目標 80% を下回ったかどうか」は trial を増やさないと統計的に
判断できません。これが **「targets are earned by data, not preloaded」** の
意味で、勝手に勝利宣言できないようになっています。

### 3.2 Cohort 集計

- 各 tool の事後分布は **5 つの公開 audience cohort** に分解して併記します:
  - `tax_advisor` / `admin_scrivener` / `smb` / `vc` / `developer` / `other`
- それより細かい (= 個別顧客に近い) granularity は **一切** 公開しません。
  Cohort `other` は 5 audience に分類できなかった残余バケツです。

### 3.3 全体への重み付け

ヘッドライン値はトリガー回数で重み付けした posterior mean です:

```
discovery_weighted = Σ (discovery_T × trials_T) / Σ trials_T
```

これにより、**呼び出し数の少ない tool が 100% でヘッドラインを引き上げる**
artifacts を避けています。

## 4. PII / プライバシー

- `query_log_v2` には INV-21 によって PII redaction が適用済みです
  (raw 法人番号 / email / 電話番号は格納されない)。Confidence モデルは tool
  名と結果バケットのみ参照し、フリーテキストには触れません。
- `usage_events` は `key_hash` (SHA-256 + pepper の不可逆ハッシュ) を扱うのみ
  で、API key の生値は見ません。
- 公開エンドポイント `/v1/stats/confidence` の出力は **per-tool aggregates +
  cohort buckets** だけで、per-customer breakdown は返却しません。

## 5. 更新サイクル

| 場所 | 更新タイミング |
| --- | --- |
| `/v1/stats/confidence` (live) | リクエスト時に live SQL + 5 分 in-memory cache |
| `analytics/confidence_<DATE>.json` (snapshot) | 1 日 1 回 cron (`scripts/cron/confidence_update.py`) |
| `site/confidence.html` (公開ダッシュボード) | live + 履歴の 2 系統表示 |

## 6. 既知の制約

- **新 tool の cold-start**: trial 数が小さい段階では CI 幅が広く、ヘッドラインを
  引き上げるべきかどうかの統計的判断が難しい。trial = 30 を超えるまでは
  目視で慎重に評価。
- **Use の 7 日 window は固定**: 業界によっては 14 日が妥当な可能性も
  ありますが、まずは 7 日でベースラインを取ります。再評価ターゲット = T+180d。
- **Discovery と Use は独立計算**: 結合確率 P(use | discovery) は推定して
  おらず、現状は周辺確率のみ。Y1 で結合 model に拡張予定。

## 7. 実装ファイル

- `src/jpintel_mcp/analytics/bayesian.py` — モデル本体 (Beta posterior + CI)
- `src/jpintel_mcp/api/confidence.py` — `/v1/stats/confidence` REST endpoint
- `scripts/cron/confidence_update.py` — 日次スナップショット
- `site/confidence.html` — 公開ダッシュボード
- `tests/test_bayesian.py` — モデル検証テスト
