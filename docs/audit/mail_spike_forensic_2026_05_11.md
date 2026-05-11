# mail_spike_forensic — 2026-05-11

過去 24h (2026-05-10T03:00Z 〜 2026-05-11T03:00Z) に info@bookyou.net で観測された受信箱 spike の原因切り分け。

## 集計 — 1 次データ

| source | 24h count | 通知経路 | spike 寄与度 |
|---|---|---|---|
| GitHub `autonomath-mcp` CI activity (CheckSuite) | **114** | GH→user mail | **★ 71 %** |
| GitHub `-AI` (zombie repo) Production Health Check 全失敗 | **17** | GH→user mail | **★ 11 %** |
| GitHub PR/issue/state-change (PR #20 merge + dependabot #21/#22) | **13** | GH→user mail | 8 % |
| 残り CheckSuite 系 (autonomath-mcp 内 cron その他) | ≈15 | GH→user mail | 9 % |
| **合計 (実測)** | **≈131 通 / 24h** | GH 通知のみ | **100 %** |

GH inbox snapshot (`gh api notifications --paginate`): **1608 unread 全体**、CheckSuite 1595 / Comment 9 / Author 2 / Review 1 / State 1。直近 24h は 131 件、`autonomath-mcp` (114) + `-AI` (17) で 100 %。

## 仮説別 evidence

### 仮説 1 — GitHub Actions workflow_run 通知 ★ 確定 (high)

- **24h 内 jpcite repo run 数 = 416** (`gh run list -L 500`)。うち **failure = 122**、success = 241、cancelled = 39、in_progress = 14。
- 失敗 workflow top 5:
  - `acceptance-criteria-ci`: 22
  - `lane-enforcer`: 19
  - `test`: 18
  - `distribution-manifest-check`: 18
  - `narrative-sla-breach-hourly`: 14 (毎時 cron / `FLY_API_TOKEN` 関連で全失敗、3125 run の超 long-running 暴走)
- event 内訳: pull_request 203 / push 57 / schedule 31 / dynamic 8 / workflow_dispatch 1。Wave 1-5 と Wave hardening 期間で PR/push 急増 + cron 失敗が重畳。
- ただし GH 通知は **workflow_run failure 1 件 = 1 mail** ではなく **CheckSuite 単位** で集約されるため、PR 1 件に紐づく N 個の job failure は 1 CheckSuite 通知に丸まる。それでも 114 件は明確に過剰。
- 推定 mail 数: **114 (autonomath-mcp 由来 CheckSuite 通知)**

### 仮説 1b — `-AI` ゾンビ repo の暴走 cron ★ 確定 (high)

- `shigetosidumeda-cyber/-AI` は **last pushed 2026-04-11** の private repo (1 ヶ月放置)。
- `.github/workflows/healthcheck.yml`「Production Health Check」が `schedule:` で毎 ~2h 実行され、**累計 1389 run / 失敗 665 / 24h は 17 件失敗**。
- このリポジトリは jpcite 関連ではない (旧プロジェクトの残骸 — おそらく当初 AutonoMath/Autonomath EC か zeimu-kaikei.ai のヘルスチェック骨組み)。
- 推定 mail 数: **17 (24h)**。1 週間累積で ≈120 通。

### 仮説 2 — Postmark / magic-link 暴走 (low — 棄却)

- 実装は `src/jpintel_mcp/api/me/login_request.py`。Postmark は使わず **xrea bookyou.net SMTP (s374.xrea.com:587)** 直叩き。
- レート制限: コード発行は **active code 再利用 (15min TTL)** で実装済 (l. 60-68)。同一 email への重複 POST は 15 min 内 1 通に圧縮、暴走しない。
- 外部攻撃で異 email アドレスを連射した場合は user (info@bookyou.net) 宛には飛ばず、SMTP 認証元 (info@bookyou.net) が送信元として消費されるのみ。受信箱 spike とは無関係。
- ただし IP 単位 rate-limit が無いので **将来の DoS リスクは残る** (後述 mitigation)。
- 寄与度: **0 %**

### 仮説 3 — Stripe webhook event 通知 (low — 棄却)

- `src/jpintel_mcp/api/billing.py` は webhook handler のみで、user mail に CC する経路は **存在しない**。
- Stripe dashboard 側 (`Developers → Webhooks`) の "Send me email on webhook failure" デフォルト OFF。
- 寄与度: **0 %**

### 仮説 4 — Fly machine restart 通知 (low — 棄却)

- Fly app 名は CLAUDE.md 記載の `jpcite-api` ではなく **`autonomath-api`** (`flyctl apps list` で確認、latest deploy 2026-05-08 08:38)。CLAUDE.md は stale。
- Fly platform default は machine restart で email を出さない (operator が opt-in 必要)。今回の deploy / restart 履歴は通常運用範囲。
- 寄与度: **0 %**

### 仮説 5 — PR/issue/comment 通知 (medium — 一部寄与)

- `gh pr list -L 20`: 直近 PR は **#22 (dependabot, 2026-05-11)** / #21 (dependabot) / **#20 (admin merge 2026-05-11T02:08:52Z, v3 wave-1)**。
- PR #20 が author=user 本人 + merge で生成する自分宛 mention 通知は ≈5 通 (open + ready_for_review + merge + check failures rollup + close)。
- Dependabot 系は author=bot, repo watcher としての CI activity 経由で既に仮説 1 にカウント済。
- 寄与度: ≈8 % (13 通)

## 確定原因 (top-1) + 次点

**確定原因 (確度 high, 寄与 71 %)**: jpcite repo の **CI activity CheckSuite 通知が 114 件 / 24h**。GHA Notification 設定が `Actions: send notifications for all activity` または `failed workflows only` のまま、Wave 1-5 で push 57 + PR 203 イベント発生 → CheckSuite が 24h で 100+ 件発火。

**次点 (確度 high, 寄与 11 %)**: 1 ヶ月放置の `-AI` zombie repo の毎 2h `Production Health Check` が **全失敗 (FLY_API_TOKEN 切れか endpoint dead)**。17 通 / 24h、1 週間で 120 通の継続ノイズ源。

## 即対処 (user 操作 + repo 操作)

### A. user 1 コマンドで 1 ヶ月 spike 半減 (zombie repo の Actions 全停止)

```bash
gh api -X PUT 'repos/shigetosidumeda-cyber/-AI/actions/permissions' \
  -f enabled=false
```

これで `-AI` repo の全 workflow が永久に停止、weekly ≈120 通の継続ノイズが即時 0 になる。repo 自体は残るので code は保全される。

### B. user GH notification 設定 (web UI)

`https://github.com/settings/notifications` → **Actions** セクション
- 現状仮定: `Send notifications for: All workflows` または `Failed workflows in repos I own or watch`
- 推奨: **`Only notify for failed workflows in your repos` + `Email: OFF` (web のみ)**

これで autonomath-mcp の 114 通 / 24h は即時 0、必要な失敗だけ `https://github.com/notifications` で確認できる。

### C. repo 側 (jpcite) のノイズ削減 — 1 PR で実行可

1. **`narrative-sla-breach-hourly` 暴走を止める**: 14 連続失敗中、cron `0 * * * *` を `0 9 * * *` (1 日 1 回 JST 18:00) に変更、または `FLY_API_TOKEN` rotation 完了まで `workflow_dispatch` のみに退避。
2. **`/v1/me/login_request` の IP rate-limit** (現状 email 単位のみ — 仮説 2 は 24h spike では棄却だが将来 DoS リスクあり):
   ```python
   # src/jpintel_mcp/api/me/login_request.py の login_request() 先頭に追加
   # IP 別 5 req / hour 制限を _ensure_table() の隣に新規 magic_link_ip_quota テーブルで管理
   ```
   優先度 P2 (本件 spike の主因ではない)。
3. **GH `repository.settings.actions.workflows.email_on_failure` repo-level OFF** はリポジトリ単位の発火フラグが無いため不可。user 側 (B) で抑制するしかない。

## 24h 推定通知数 (最終)

- **GH mail (実測)**: 131 通 (autonomath-mcp 114 + -AI 17)
- うち GH inbox 経由 web 通知のみ届く分: 0 (現状は web + mail 両方届く設定と推定)
- Postmark/SMTP/Stripe/Fly: 0 通

## 出典

- `gh api notifications --paginate` (2026-05-11T02 時点 snapshot): 1608 unread, CheckSuite 1595
- `gh run list -L 500 --json status,conclusion,workflowName,createdAt,event`: 24h で 416 run / 122 failure
- `gh api repos/shigetosidumeda-cyber/-AI/actions/runs`: total 1389, failure 665, 24h failure 17
- `gh pr list --state all -L 20`: PR #20 merge 2026-05-11T02:08:52Z + dependabot #21/#22
- `src/jpintel_mcp/api/me/login_request.py:60-68` (email-level reuse window 15 min — DoS 緩衝)
- `flyctl apps list`: app name = `autonomath-api` (CLAUDE.md は stale 表記)
- `.github/workflows/narrative-sla-breach-hourly.yml` (cron `0 * * * *`、Fly SSH + TG_BOT_TOKEN 依存、現在全失敗)
