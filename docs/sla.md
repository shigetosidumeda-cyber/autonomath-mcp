# SLA (Service Level Agreement)

> **要約 (summary):** 税務会計AI の正式な可用性コミットメント。月次稼働率 **99.5%** を target とし、違反時は metered 構造に整合した service credit (¥3 単位の return / 翌月減額) を提供する。本 SLA は "fair warning" ではなく、利用規約 (terms_of_service.md) と一体の正式条項として位置づける。

最終更新: 2026-04-25
施行日: 2026-05-06 (launch)
事業者: Bookyou株式会社 (T8010001213708)

---

## 1. 対象範囲 (Service Coverage)

本 SLA は以下を対象とする。

| 対象 | URL | 備考 |
|---|---|---|
| **本番 REST API** | `https://api.zeimu-kaikei.ai/v1/*` | Fly.io nrt (東京) リージョン |
| **本番 MCP server** | `autonomath-mcp` (PyPI 配布、stdio) | クライアントから接続できることが対象 (クライアント側不具合は対象外) |

対象外:

- `https://zeimu-kaikei.ai/` (marketing / landing page)
- `https://zeimu-kaikei.ai/docs/` (docs site)
- `https://staging.zeimu-kaikei.ai` (staging 環境)
- 各種 CDN 静的アセット (Cloudflare Pages 上の `site/*`)

---

## 2. 可用性目標 (Availability Target)

### 2.1 Target

- **月次稼働率: 99.5%** (カレンダー月、UTC 基準)
- 99.5% は月あたり最大 **約 21.6 分 (=21 分 36 秒)** のダウンタイムを許容する水準である
- launch 直後 (2026-05-06 〜 2026-08-31) は新環境の安定化期間とし、target を **99.0%** (月あたり最大約 7.3 時間) として運用する
- 2026-09-01 以降は本書の 99.5% target を正式適用する

### 2.2 算定式 (Calculation Method)

```
月次稼働率 (%) = (月内総時間 - ダウンタイム時間) / 月内総時間 × 100
```

- 月内総時間: カレンダー月の総時間 (例: 30 日月 = 720 h、31 日月 = 744 h、2 月 = 672 h or 696 h)
- ダウンタイム時間: 後述の external uptime monitor が連続 2 分以上「DOWN」を検出した区間の合計
- 単発のリクエスト失敗や 1 分未満の瞬断は計上しない (transient failure を除外)

### 2.3 計測方法

- 外部 uptime monitor (UptimeRobot または Better Stack、launch 前に確定) が `GET /healthz` を **1 分間隔** で監視する
- monitor は東京・大阪・シンガポール の 3 地点から並行 probe を実行し、過半数 fail で初めて DOWN と判定する (false positive 抑制)
- 月次の uptime % は monitor の公開 status page で第三者に検証可能な形で公表する
- 自社内部計測は補助情報のみとし、**契約上の判定は第三者 monitor の数値を採用**する

---

## 3. データ保護目標 (Data Protection)

### 3.1 RPO (Recovery Point Objective): 24 時間

- 日次 snapshot を Fly.io 永続ボリュームから別リージョン (Fly.io iad) の低頻度ストレージへ転送
- 最悪ケースでも損失は前日 00:00 JST 以降の新規書込のみ
- 詳細は `disaster_recovery.md` 参照

### 3.2 RTO (Recovery Time Objective): 4 時間

- Fly.io machine 消失時: 別 machine への snapshot リストア + DNS 切替で 4 時間以内の復旧を目標
- 静的 fallback (Cloudflare Pages) への切替は 10 分以内 (kill-switch rehearsal で検証済)

---

## 4. SLA 除外項目 (Exclusions)

以下はダウンタイムとして計上**しない**:

1. **計画メンテナンス**: 事前 24 時間以上の告知を伴う計画停止 (data refresh、schema migration、Fly.io 指示の再起動含む)
2. **不可抗力**: 地震・火災・戦争・パンデミック・通信事業者の広域障害等、当社の合理的支配を超える事象
3. **DDoS / 攻撃起因の停止**: 第三者による不正アクセスを起因とする停止
4. **upstream platform 障害**: Fly.io そのもの (platform-level)、Cloudflare、Stripe、Sentry 等の外部依存 SaaS の障害 — `status.fly.io` 等の公式 status page で確認できるもの
5. **利用者側の問題**: API key 誤設定、rate limit 超過、client 側 network、SDK バージョン不整合
6. **法令遵守・知財保護のための緊急サービス停止**: 行政処分・差止命令・著作権者からの正当な請求に基づく停止
7. **β 版機能の停止**: ドキュメントで明示的に β 版・experimental と位置づけられた endpoint の停止 (`/v1/am/*` 等)

---

## 5. サービスクレジット (Service Credits)

### 5.1 Credit 適用条件

月次稼働率が target (99.5%) を下回った場合、利用者は以下の credit を申請できる。

| 月次稼働率 | Credit 額 |
|---|---|
| 99.5% 〜 99.0% | 当月課金額の **10%** |
| 99.0% 〜 95.0% | 当月課金額の **25%** |
| 95.0% 未満 | 当月課金額の **50%** |

- credit は ¥3/req (税抜) 単位で計算し、翌月の Stripe 請求から減額する形で適用する
- 当月課金額が ¥0 の場合 (無料枠内利用)、credit は発生しない (metered 構造による自動的 no-charge が代替)
- credit の上限は当月課金額を超えない

### 5.2 Credit 申請方法

- 申請窓口: `info@bookyou.net`
- 件名: `[sla-credit] <対象月 YYYY-MM> - <登録email>`
- 申請期限: 対象月の翌月末日まで (期限経過後は失効)
- 当社は申請受領後 14 日以内に、external monitor の記録を確認し credit 適用可否を回答する

### 5.3 Credit の性質

- credit は本サービスの利用料金に対する減額 / 返金として提供する
- 現金での返金は原則行わない (Stripe 請求調整が困難な場合のみ例外的に対応)
- credit は他の利用者・第三者へ譲渡できない

### 5.4 metered 構造による自動緩和

本サービスは 1 リクエストあたり課金する metered 構造のため、**ダウンタイム期間中はリクエストが成立せず、課金も発生しない**。これにより、credit 制度がなくとも、ダウンタイム時間に比例した料金負担は利用者に発生しない。Credit 制度は、ダウンタイム以外の品質劣化 (latency 急増、error rate 上昇等) に対する追加保護として位置づける。

---

## 6. 障害通知 (Incident Communication)

### 6.1 通知 channel

- **public status page**: `https://status.zeimu-kaikei.ai` (external monitor 提供、第三者検証可能)
- **登録 email**: P1 (全面停止) 障害時に登録ユーザー全員に email 通知
- **docs site**: 重大インシデントは `docs/_internal/incident_log.md` (公開予定) に postmortem を掲載

### 6.2 一次回答 SLA

| 重大度 | 一次回答期限 | 定義 |
|---|---|---|
| **P1** (全面停止) | 1 時間以内 | API endpoint の 50% 以上が 5xx を返す状態 |
| **P2** (部分機能停止) | 4 時間以内 | 特定 endpoint または特定 dataset のみ影響 |
| **P3** (品質劣化) | 1 営業日以内 | latency 急増、partial result 等 |

solo ops 運営のため、24/7 専任エンジニアは配置していない。一次回答は up to 1h であり、根本原因分析・恒久対策は別途 postmortem として公開する。

---

## 7. 運用前提 (Operational Context)

### 7.1 solo + zero-touch 原則

- 当社は 1 名 (代表 梅田茂利) で運営する zero-touch SaaS である
- 24/7 監視は automated monitor + on-call alert により行い、専任 NOC は設置していない
- 本 SLA の数値は、この体制下で現実的かつ持続可能に達成可能な target として設定している

### 7.2 SLA レビューサイクル

- 本 SLA は **四半期ごと (Q1/Q2/Q3/Q4 初旬)** に見直す
- 実績 uptime が target を 2 期連続で下回った場合、インフラ増強または target 下方修正のいずれかを選択する
- 改訂履歴は本ファイルの git log を参照

---

## 8. 関連文書

- [利用規約 (Terms of Service)](compliance/terms_of_service.md) — 第 6 条 (SLA / サポート) と本書は整合
- [特定商取引法に基づく表記](compliance/tokushoho.md) — 「不良品 (役務の不適合) への対応」と本書 §5 credit は整合
- Disaster Recovery Plan (`docs/disaster_recovery.md`、内部運用 doc) — RPO/RTO の運用詳細
- Observability (`docs/observability.md`、内部運用 doc) — 計測の技術詳細

---

## 9. 連絡先

**Bookyou株式会社**
〒112-0006 東京都文京区小日向2-22-1
法人番号: T8010001213708
Email: [info@bookyou.net](mailto:info@bookyou.net)

---

## English (secondary)

**Target availability:** 99.5% monthly uptime for `api.zeimu-kaikei.ai`, measured by an external uptime monitor.

**Calculation:** `(month_total_hours - downtime_hours) / month_total_hours × 100`. Downtime requires ≥2 consecutive minutes of DOWN signal from a third-party multi-region monitor.

**Excluded:** planned maintenance (24h notice), force majeure, DDoS, Fly.io / upstream SaaS outages, client-side issues, legal takedowns, β-tagged endpoints.

**Service credits:** 10% / 25% / 50% of monthly charge for 99.5–99.0% / 99.0–95.0% / <95.0% uptime respectively. Applied as next-invoice discount in ¥3 units. The metered pricing model (¥3/req, no-request = no-charge) automatically mitigates downtime cost.

**Operations:** solo + zero-touch. No 24/7 NOC. Initial response 1h (P1) / 4h (P2) / 1 business day (P3).

**Review:** quarterly. Effective 2026-05-06 (launch); 99.5% target enforced from 2026-09-01 onward.

Contact: [info@bookyou.net](mailto:info@bookyou.net).
