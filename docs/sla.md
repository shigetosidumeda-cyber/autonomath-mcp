# Service Level Targets

本ページは jpcite の稼働目標と障害時の連絡方針を説明するものです。利用規約と矛盾する場合は、利用規約が優先します。

- 最終更新: 2026-05-01
- 対象: `https://api.jpcite.com/v1/*` と MCP サーバー
- 対象外: 静的サイト、ドキュメント、ステージング環境、外部サービス側の障害

## 稼働目標

- 月次稼働率の目標: 99.0%
- 監視対象: `GET /healthz`
- 判定: 複数地点の外形監視で連続 2 分以上失敗した区間を障害として扱います

この数値は運用品質の目標であり、返金・損害賠償を保証するものではありません。従量課金のため、成立しなかったリクエストには課金されません。

## 除外事項

以下は稼働率の計算から除外します。

- 事前告知した計画メンテナンス
- 地震、火災、通信事業者障害などの不可抗力
- DDoS、脆弱性対応、法令遵守、知財保護のための緊急停止
- Fly.io、Cloudflare、Stripe など上流サービスの公開障害
- API キー誤設定、rate limit 超過、クライアント側ネットワークなど利用者環境の問題
- ベータまたは実験的機能

## 障害通知

- 公開状況: `https://jpcite.com/status.html`
- 連絡先: [特定商取引法に基づく表記](./compliance/tokushoho.md)
- 全面停止など影響が大きい障害では、復旧状況を status page または登録メールで案内します

## データ保護目標

- RPO: 24 時間
- RTO: 4 時間

これらも運用目標であり、個別の復旧時間を保証するものではありません。

## English Summary

- Target availability: 99.0% monthly for the production API.
- Downtime is measured through external health checks.
- This is an operational target, not a warranty or service-credit commitment.
- Failed requests are not billed under the metered pricing model.
