# Confidence (信頼度ダッシュボード)

`/v1/stats/confidence` はツール単位の **発見確率** (見つけられる確率) と **再利用確率** (実 action に変わる確率) を統計的に推定し、95% 区間と一緒に公開する。

## 1. 数値目標

| 指標 | T+90d | Y1 |
| --- | --- | --- |
| Discovery | 90% | 95% |
| Use | 80% | 92% |

## 2. 定義

### Discovery

```
Discovery_T = P(found_result | invoked)
```

- **trial:** tool への 1 回の呼び出し
- **success:** `result_count > 0` を返したもの
- **入力:** `query_log_v2.tool` / `result_bucket` / `result_count`

### Use

```
Use_T = P(returned_within_7d | first_invocation)
```

- **trial:** 各 (api_key_hash, tool) の **最初** のイベント
- **success:** 同じ (api_key_hash, tool) で 7 日以内に再呼び出し
- **入力:** `usage_events.key_hash` / `endpoint` / `ts`
- 匿名 (`key_hash IS NULL`) は識別不能のため Use の母集団から除外

7 日 window は「retention の確認」を「one-shot trial」と切り分けるための閾値。

## 3. Bayesian モデル

各 tool の確率を独立 Bernoulli プロセスとしてモデル化。

- **事前分布:** `Beta(1, 1)` (= Uniform[0, 1])
- **事後分布:** `Beta(α + hits, β + trials − hits)`
- **95% CI:** `scipy.stats.beta.interval(0.95, α, β)`

### サンプル

`Beta(1, 1)` + 80 hit / 100 trial:

```
posterior     = Beta(81, 21)
posterior mean = 0.7941
95% CI        ≈ [0.711, 0.866]
```

事後平均 79.4% は Use の T+90d 目標 (80%) をわずかに下回る。「目標 80% を下回ったかどうか」は trial を増やさないと統計的に判断できない (= **targets are earned by data, not preloaded**)。

### Cohort 集計

- 公開 audience cohort: `tax_advisor` / `admin_scrivener` / `smb` / `vc` / `developer` / `other` (= 5 audience に分類できなかった残余)
- それより細かい (個別顧客に近い) granularity は **公開しない**

### 全体への重み付け

```
discovery_weighted = Σ (discovery_T × trials_T) / Σ trials_T
```

呼び出し数の少ない tool が 100% でヘッドラインを引き上げる artifact を回避。

## 4. PII / プライバシー

- `query_log_v2` は INV-21 で PII redaction 済み (raw 法人番号 / email / 電話番号は格納されない)
- `usage_events.key_hash` は SHA-256 + pepper の不可逆ハッシュのみ
- `/v1/stats/confidence` の出力はツール単位の集約値とコホート bucket のみで、顧客ごとの内訳は返さない

## 5. 更新サイクル

| 場所 | 更新タイミング |
| --- | --- |
| `/v1/stats/confidence` (live) | リクエスト時に live SQL + 5 分 cache |
| `analytics/confidence_<DATE>.json` (日次スナップショット) | 日次 cron |
| `site/confidence.html` (公開ダッシュボード) | live + 履歴 |

## 6. 既知の制約

- **新 tool の cold-start:** trial 数小だと CI 幅が広く、ヘッドラインを引き上げる統計的判断が難しい。trial = 30 を超えるまでは目視評価
- **Use の 7 日 window は固定:** 業界によっては 14 日が妥当な可能性、再評価ターゲット = T+180d
- **Discovery と Use は独立計算:** 結合確率 P(use | discovery) は推定せず周辺確率のみ。Y1 で結合 model に拡張予定
