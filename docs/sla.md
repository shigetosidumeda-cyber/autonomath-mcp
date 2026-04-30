# SLA (Service Level Agreement)

利用規約 ([compliance/terms_of_service.md](compliance/terms_of_service.md)) と一体の正式条項。

- 最終更新: 2026-04-29
- 施行日: 2026-05-06 (launch)
- 事業者: Bookyou株式会社 (T8010001213708)

## 1. 対象範囲

| 対象 | URL |
|---|---|
| 本番 REST API | `https://api.jpcite.com/v1/*` |
| 本番 MCP server | `autonomath-mcp` (PyPI 配布、stdio) |

対象外: marketing / landing page、docs site、staging 環境、CDN 静的アセット。

## 2. 可用性目標

- **月次稼働率: 99.5%** (カレンダー月、UTC 基準)
- launch 直後 (2026-05-06 〜 2026-08-31) は **99.0%** で運用、2026-09-01 以降 99.5% を正式適用
- 99.5% は月最大 **約 21.6 分** のダウンタイムを許容

### 算定式

```
月次稼働率 (%) = (月内総時間 - ダウンタイム時間) / 月内総時間 × 100
```

ダウンタイム = 外部 uptime monitor (3 地点並行 probe、過半数 fail で DOWN 判定) が連続 2 分以上 DOWN を検出した区間の合計。1 分未満の瞬断は計上せず。

monitor は `GET /healthz` を 1 分間隔で監視、月次 uptime % は public status page で公表 (契約上は第三者 monitor 数値を採用)。

## 3. データ保護

- **RPO (Recovery Point Objective): 24 時間** — 日次のスナップショットを別リージョン低頻度ストレージへ転送
- **RTO (Recovery Time Objective): 4 時間** — Fly.io machine 消失時、別 machine への restore + DNS 切替
- 静的 fallback (Cloudflare Pages) への切替は 10 分以内

## 4. 除外項目 (ダウンタイムに計上しない)

1. **計画メンテナンス** (24 時間以上の事前告知)
2. **不可抗力** (地震・火災・戦争・パンデミック・通信事業者広域障害等)
3. **DDoS / 攻撃起因の停止**
4. **upstream platform 障害** (Fly.io / Cloudflare / Stripe / Sentry 等の status page 公開分)
5. **利用者側の問題** (API key 誤設定、rate limit 超過、client network、SDK 不整合)
6. **法令遵守 / 知財保護のための緊急停止**
7. **β 版機能** (`/v1/am/*` 等の experimental endpoint)

## 5. サービスクレジット

| 月次稼働率 | Credit 額 |
|---|---|
| 99.5% 〜 99.0% | 当月課金額の **10%** |
| 99.0% 〜 95.0% | 当月課金額の **25%** |
| 95.0% 未満 | 当月課金額の **50%** |

- credit は ¥3/req 単位で計算、翌月 Stripe 請求から減額
- 当月課金額 ¥0 (無料枠内利用) の場合 credit 発生なし
- credit 上限 = 当月課金額

### 申請方法

- 窓口: `info@bookyou.net`
- 件名: `[sla-credit] <対象月 YYYY-MM> - <登録email>`
- 期限: 対象月の翌月末日 (経過後失効)
- 受領後 14 日以内に外部 monitor 記録を確認、credit 適用可否を回答

### metered 構造による自動緩和

ダウンタイム期間中はリクエストが成立せず課金も発生しない。Credit はそれに加えた追加保護 (latency 急増・error rate 上昇等の品質劣化対応)。

## 6. 障害通知

- **public status page:** `https://status.jpcite.com`
- **登録 email:** P1 障害時に登録ユーザーへ通知

| 重大度 | 一次回答期限 | 定義 |
|---|---|---|
| **P1** (全面停止) | 1 時間以内 | API endpoint の 50% 以上が 5xx |
| **P2** (部分機能停止) | 4 時間以内 | 特定 endpoint または特定 dataset のみ影響 |
| **P3** (品質劣化) | 1 営業日以内 | latency 急増、partial result 等 |

## 7. レビューサイクル

- 四半期ごと (Q1/Q2/Q3/Q4 初旬) に見直し
- 実績が target を 2 期連続で下回った場合、インフラ増強または target 下方修正を選択
- 改訂履歴は本ファイルの git log

## 8. 関連文書

- [利用規約](compliance/terms_of_service.md) — 第 6 条 (SLA / サポート) と本書は整合
- [特定商取引法に基づく表記](compliance/tokushoho.md) — 「不良品 (役務の不適合) への対応」と本書 §5 と整合

## 9. 連絡先

**Bookyou株式会社**
〒112-0006 東京都文京区小日向2-22-1
適格請求書発行事業者番号: T8010001213708
Email: [info@bookyou.net](mailto:info@bookyou.net)

---

## English (secondary)

- **Target availability:** 99.5% monthly uptime for `api.jpcite.com`, third-party uptime monitor.
- **Calculation:** `(month_total_hours - downtime_hours) / month_total_hours × 100`. Downtime requires ≥2 consecutive minutes of DOWN signal from a 3-region monitor.
- **Excluded:** planned maintenance (24h notice), force majeure, DDoS, upstream SaaS outages, client-side issues, legal takedowns, β-tagged endpoints.
- **Service credits:** 10% / 25% / 50% of monthly charge for 99.5–99.0% / 99.0–95.0% / <95.0% uptime. Applied as next-invoice discount in ¥3 units. Metered pricing (¥3/req, no-request = no-charge) automatically mitigates downtime cost.
- **Initial response:** 1h (P1) / 4h (P2) / 1 business day (P3).
- **Review:** quarterly. Effective 2026-05-06 (launch); 99.5% target enforced from 2026-09-01 onward.

Contact: [info@bookyou.net](mailto:info@bookyou.net).
