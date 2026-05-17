---
title: Gmail Filter for GitHub Actions Noise
updated: 2026-05-12
operator_only: true
category: monitoring
---

# Runbook: Gmail Filter for GitHub Actions Noise

**Status**: active
**Owner**: solo operator (info@bookyou.net)
**Last reviewed**: 2026-05-12 (Wave 43)

## Why

Wave 31-43 で 100+ workflow run / 50+ PR を回した結果、`notifications@github.com`
から info@bookyou.net に **71+ 通の自動通知** が累積した。

- GitHub Actions bot (`github-actions[bot]`) の workflow / PR / dependabot 通知が
  inbox を埋め、人間からの mail (顧客・税務・銀行) が埋もれる
- Solo + zero-touch 原則 (`feedback_zero_touch_solo`) では「人的トリアージを必要と
  する状態」自体が反則。bot 通知は自動で skip inbox + label 振り分け必須
- repo subscription OFF (`gh api -X PUT /repos/.../subscription`) と
  workflow `concurrency:` だけでは抑え切れない (PR review request / push 通知が
  残る) → Gmail filter で最終 floor を作る

この runbook は **claude が代行不可** な Gmail web UI 操作を user (info@bookyou.net)
が実施する手順を SOT 化する。

## Prerequisites

- Gmail web (`https://mail.google.com`) に info@bookyou.net で sign in 済み
- `notifications@github.com` から 1 通以上 mail 受信済 (filter test material)
- 各 wave で `feedback_github_notification_throttle.md` の 3 軸を全部 set する
  方針を理解済 (本 filter は 3 軸目)

## What (3 filter 構成)

### Filter A: Workflow run / action_required

- **From**: `notifications@github.com`
- **Subject**: `(workflow run|action_required)`
  - 例: "Run failed: deploy", "Action required: re-run workflow"
- **Action**:
  - [x] Skip the Inbox (Archive it)
  - [x] Mark as read
  - [x] Apply label: `GitHub/Workflow` (新規作成 / nested label)
  - [x] Also apply filter to matching conversations (既存 mail にも遡及適用)

### Filter B: Dependabot / dependency updates

- **From**: `notifications@github.com`
- **Subject**: `(dependabot|build\(deps\))`
  - 例: "[Dependabot] Bump axios from 1.6.0 to 1.7.0",
    "build(deps): bump @types/node"
- **Action**:
  - [x] Skip the Inbox
  - [x] Mark as read
  - [x] Apply label: `GitHub/Dependabot`
  - [x] Also apply filter to matching conversations

### Filter C: Wave 自動 PR (feat(wave...))

- **From**: `notifications@github.com`
- **Subject**: `Re: [shigetosidumeda-cyber/autonomath-mcp]`
- **Subject contains**: `feat\(wave`
  - 例: "Re: [shigetosidumeda-cyber/autonomath-mcp] feat(wave-43): gmail filter docs"
- **Action**:
  - [x] Skip the Inbox
  - [x] Mark as read
  - [x] Apply label: `GitHub/Wave`
  - [x] Also apply filter to matching conversations

---

## Step-by-step (Gmail web UI 操作)

### Step 1: 設定画面を開く

1. Gmail web を browser で開く
2. 右上の歯車 icon (Settings) クリック
3. ドロワー下の **"See all settings"** クリック

### Step 2: Filter tab に遷移

4. 上部 tab 列から **"Filters and Blocked Addresses"** を選択
5. ページ中央の **"Create a new filter"** リンククリック (既存 filter 一覧の下)

### Step 3: Filter A 作成

6. 開いた検索条件 form に入力:
   - **From**: `notifications@github.com`
   - **Subject**: `(workflow run|action_required)`
   - **Has the words**: 空のまま
   - **Doesn't have**: 空のまま
   - **Size**: 空のまま
7. 右下 **"Create filter"** クリック
8. 次画面で以下 checkbox に check:
   - [x] **Skip the Inbox (Archive it)**
   - [x] **Mark as read**
   - [x] **Apply the label** → drop-down で "New label..." → name = `GitHub/Workflow`
     → "Create"
   - [x] **Also apply filter to matching conversations** (画面下部)
9. **"Create filter"** クリック

### Step 4: Filter B 作成

10. Step 2 → Step 3 と同じ手順を Filter B 条件で繰り返す:
    - **From**: `notifications@github.com`
    - **Subject**: `(dependabot|build\(deps\))`
    - Label: `GitHub/Dependabot`

### Step 5: Filter C 作成

11. Step 2 → Step 3 と同じ手順を Filter C 条件で繰り返す:
    - **From**: `notifications@github.com`
    - **Subject**: `Re: [shigetosidumeda-cyber/autonomath-mcp]`
    - **Has the words**: `feat(wave`
    - Label: `GitHub/Wave`

---

## Verification

filter 適用 5 分後に以下を確認:

- [ ] Gmail inbox から `github-actions[bot]` の通知が **消えている**
  (未読数が顕著に減る、目安 30+ 通減)
- [ ] 左 sidebar の labels セクションに `GitHub/Workflow`, `GitHub/Dependabot`,
  `GitHub/Wave` の 3 label が表示され、それぞれ click すると過去通知が一覧表示
- [ ] 新着の github-actions bot 通知 (次 wave で workflow が走った時) が
  inbox に来ず、該当 label に直接落ちる

## Rollback

filter で重要 mail (例: security alert) を取りこぼした場合:

1. Settings → "Filters and Blocked Addresses" tab
2. 該当 filter 行の **"delete"** リンククリック
3. confirm dialog で "OK"
4. 必要なら labels 内の過去 mail を手動で inbox に戻す
   (mail を開いて "Move to Inbox" button)

## Out of scope

- **Mobile app (iOS / Android)**: filter は Gmail server 側で動くので
  mobile でも同じく適用される。mobile UI からの filter 編集は非対応 (web のみ)
- **Multi-account**: bookyou.net 以外の Gmail account (個人 gmail.com 等) は
  対象外。各 account で個別に filter 設定が必要
- **Workspace 制限**: bookyou.net は xrea mail (`reference_bookyou_mail`) なので
  Workspace ではない。Gmail forwarding 経由で受信している場合 filter は
  Gmail 側で動く

## Bulk mark-as-read (one-shot cleanup)

71+ 通の既存 unread を一気に既読化する方法は 2 つ:

### Option 1: web UI (推奨、30 秒)

1. https://github.com/notifications を browser で開く
2. 右上 "Mark all as read" button クリック (or shortcut `Shift + Esc`)
3. confirmation dialog で "Mark all as read"
4. これで GitHub 側 thread = 全部 read。Gmail 側 email は別途 filter で処理 (filter 適用後は新着分のみ skip inbox 対象)

### Option 2: gh CLI + 個人 PAT

`gh` の OAuth token (`gho_*`) は default `notifications` scope を持たない。代替:

1. https://github.com/settings/tokens/new で fine-grained PAT 発行 (scope=`notifications` のみ、expiration=24h で十分)
2. `GH_TOKEN=ghp_xxx gh api -X PUT /notifications -F last_read_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"`
3. 200 returned で全 thread read 化
4. PAT は使い終わったら settings/tokens で revoke

`gh auth refresh -h github.com -s notifications` は interactive で background 実行不可なので claude session からは無理。

## Related

- `feedback_github_notification_throttle.md` — 4 軸 throttle 原則
- `feedback_zero_touch_solo.md` — 営業 0 + solo zero-touch
- `feedback_no_user_operation_assumption.md` — user 操作必須と決めつけ禁止
  原則だが、Gmail filter は GraphQL/API 未提供で **真に user 操作が唯一の手段**。bulk mark-read は PAT 発行で claude 代行可
- `runbook/github_rename.md` — repo rename 時 filter C subject pattern 要更新
- `.github/workflows/dependabot-auto-merge.yml` — Wave 43 追加。dependabot patch/minor PR 自動 merge で thread 自体を高速 close (email 累積前)

## Changelog

- 2026-05-12 (Wave 43): 初版作成。3 filter 構成 + verification + rollback
- 2026-05-12 (Wave 43 追記): bulk mark-as-read 2 option + dependabot auto-merge 言及 + 4 軸更新
