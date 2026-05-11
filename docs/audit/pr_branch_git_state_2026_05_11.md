# jpcite PR / Branch / Git State 棚卸し (2026-05-11)

**生成時刻**: 2026-05-11 13:30 JST (local main = `d4216ffb` 2026-05-08 / origin/main = `94d5ddd4` 2026-05-11 12:57 JST)
**目的**: PR / branch / commit history の完全棚卸し → stale / abandoned / 重複 / conflict の発見と整理候補提示
**実行範囲**: audit のみ。close / delete / merge は **user 承認後**。

---

## サマリ (4 軸 traffic light)

| 軸 | 件数 | green | yellow | red | 即措置候補 |
|---|---|---|---|---|---|
| **A. Open PR** | 15 | 0 | 11 | 4 | PR#23 close、PR#14 close、PR#3/PR#7 close |
| **B. Branch** | 局所6 + remote19 = 25 | 2 (main, hotfix LIVE) | 11 dependabot stale | 12 重大 stale | local 2 branch 削除候補、remote dependabot 重複削除 |
| **C. Commit history** | 直近100 | 96 | 4 (committer != author = rebase 痕跡) | 0 amend | sign-off ゼロ問題以外 clean |
| **D. 本セッション (5/11) state** | 5 branch | 1 (PR#25 merged) | 2 (seo_pages 空 / critical_hotfix 1 commit ahead) | 2 (PR#23 redteam 859 file conflict, seo_pages local-only) | PR#23 即 close、seo_pages 削除 |

**Headlines**:
- **Open PR=15、CONFLICTING=1 (PR#23)、stale 1 週超=11 件 (dependabot 9 + OyaAIProd 1 + PR#23 0d だが死亡)**
- **Local-only branch=2 件 (`feat/jpcite_2026_05_11_seo_pages` 空 / `codex-prod-deploy-20260507-0729` 149 commits ahead, remote 未 push 死化)**
- **Local main が origin/main から 5 commit 遅延 (`git pull` で同期可)**
- **PR#23 = 859 files / 23 commits / +93,601 -1,602 / 4/4 CI failure / mergeable=CONFLICTING / DIRTY → resurrect 困難、close 推奨**
- **dependabot 14 PR 中 11 PR が CI failure 状態で 11 日放置 (pytest 3.13 fail or e2e 15min timeout pattern)**

---

## A. Open PR 状態詳細

### A-1. open PR full list (n=15)

| PR | age | stale | mergeable | state | author | 概要 | 措置候補 |
|---|---|---|---|---|---|---|---|
| **#23** | 0d | 0d | **CONFLICTING** | **DIRTY** | shigetosi | redteam SV hotfix — 859 files / 23 commits | **close & abandon** (重複は PR#25 で merge 済) |
| #22 | 0d | 0d | MERGEABLE | UNSTABLE | dependabot | build >=1.5.0 (PR#9 replacement) | release_readiness pass → merge ok |
| #21 | 0d | 0d | MERGEABLE | UNSTABLE | dependabot | @types/node 25.6.2 (PR#4 replacement) | static-drift pass → merge ok |
| #14 | 7d | 7d | MERGEABLE | UNSTABLE | OyaAIProd | SafeSkill 50/100 security badge | **close** (3rd-party bot, value低、Use with Caution badge は noise) |
| #13 | 11d | 11d | MERGEABLE | UNSTABLE | dependabot | pre-commit >=4.6.0 | pytest3.13/e2e fail → re-run or rebase |
| #12 | 11d | 11d | MERGEABLE | UNSTABLE | dependabot | pytest-cov >=7.1.0 | 同上 |
| #11 | 11d | 11d | MERGEABLE | UNSTABLE | dependabot | pandas >=3.0.2 | 同上 |
| #10 | 11d | 11d | MERGEABLE | UNSTABLE | dependabot | pyarrow >=24.0.0,<25 | 同上 |
| #8 | 11d | 0d | MERGEABLE | UNSTABLE | dependabot | actions/setup-python v5→v6 | e2e pass → merge ok |
| #7 | 11d | 11d | MERGEABLE | UNSTABLE | dependabot | astral-sh/setup-uv 8.1.0 | pytest fail 11d 放置 |
| #6 | 11d | 0d | MERGEABLE | UNSTABLE | dependabot | actions/checkout v4→v6 | scan-pr pass → merge ok |
| #5 | 11d | 11d | UNKNOWN | UNSTABLE | dependabot | typescript 6.0.3 | 重大 breaking、慎重に |
| #3 | 11d | 11d | MERGEABLE | UNSTABLE | dependabot | codecov-action SHA bump | pytest 3.13 fail |
| #2 | 11d | 3d | MERGEABLE | UNSTABLE | dependabot | peter-evans/create-pull-request 8.1.1 | release_readiness pass → merge ok |
| #1 | 11d | 2d | MERGEABLE | UNSTABLE | dependabot | python 3.12→3.14 base image | 重大 breaking、慎重に |

### A-2. CONFLICT ありの PR
- **PR#23** (`feat/jpcite_2026_05_11_redteam_hotfix`): 859 files, 4/4 CI fail
  - 内訳: scripts/39, docs/24, .github/18, ops/4, pdf-app/4
  - 主因: PR#25 (`feat/jpcite_2026_05_11_critical_hotfix` → main 94d5ddd4 merged) と同じ subject 範囲を PR#23 側で 23 commits 蓄積、divergent base
  - **同等の修正は PR#25 で main に取り込み済** (jpintel codename strip + hydrate timeout + 14 doc)
  - **推奨**: close & don't reopen / branch は user 承認後 delete

### A-3. 重複 PR (同 subject)
- なし。PR#9 / PR#4 は CLOSED (dependabot が自動的に PR#22 / PR#21 で superseded)。
- ただし PR#23 と PR#25 は subject 強重複 (PR#23 redteam → PR#25 redteam+seo); **PR#25 LIVE, PR#23 dead**。

### A-4. 1 週間以上更新なしの PR (stale)
- 11 件 (PR#1, 2, 3, 5, 7, 10, 11, 12, 13, 14, 22 のうち updated > 7d): **9 件 dependabot + 1 件 OyaAIProd (PR#14) + 0 internal**
- 措置: stale dependabot は (a) rebase + 再実行 / (b) close で release_readiness 通ったものだけ merge

---

## B. Branch 状態

### B-1. ローカル branch (6 本)

| branch | last commit | tracked? | ahead/behind origin | 措置 |
|---|---|---|---|---|
| **main** | 2026-05-08 (d4216ffb) | yes | behind 5 (5/11 main is 94d5ddd4) | `git pull` 同期 |
| **feat/jpcite_2026_05_11_critical_hotfix** | 2026-05-11 12:56 (9e93ceef) | yes | == origin | keep (PR#25 source, merged) |
| **feat/jpcite_2026_05_11_redteam_hotfix** | 2026-05-11 11:57 (42f79f97) | yes | behind 4 vs origin | **delete after PR#23 close** |
| **feat/jpcite_2026_05_11_seo_pages** | 2026-05-11 12:52 (c66dba29) | **NO upstream** | local only | **delete** (空、commit 取消後) |
| **v3/wave-1-batch** | 2026-05-11 10:34 (7fc3af9f) | yes | ahead 20 behind 4 vs origin/main | keep (PR#20 merged, branch can delete) |
| **codex-prod-deploy-20260507-0729** | 2026-05-07 (dee9c85b) | **NO upstream** | ahead 149 behind 5 vs main | **delete** (5/7 codex deploy stub, push 履歴なし) |

### B-2. リモート branch (19 本)

| 種別 | 件数 | 内訳 |
|---|---|---|
| long-running | 1 | `origin/main` |
| live feature (今セッション) | 3 | `feat/jpcite_2026_05_11_critical_hotfix` / `redteam_hotfix` / `v3/wave-1-batch` |
| dependabot stale | 14 | 全 dependabot PR の head ref。behind 21〜373 commits (4/29 以降未 rebase) |
| bot artifact | 1 | `bot/openapi-refresh` (5/2 trust-center bot stale, behind 238) |

### B-3. merged-but-not-deleted の検出
- `origin/v3/wave-1-batch`: PR#20 merge 済 (5/11 02:08Z) だが branch 残存 → **delete OK**
- ローカル `v3/wave-1-batch`: 同上、削除候補
- `feat/jpcite_2026_05_11_critical_hotfix`: PR#25 merge 済 (5/11 03:57Z) だが branch 残存 → keep (本 session 終了後 delete)

### B-4. main から大きく diverged (>200 behind) の dead branch
- `origin/bot/openapi-refresh` (behind 238)
- `origin/dependabot/github_actions/astral-sh/setup-uv-8.1.0` (behind 373)
- `origin/dependabot/github_actions/codecov/codecov-action-*` (behind 373)
- `origin/dependabot/npm_and_yarn/sdk/typescript/types/node-25.6.0` (behind 373, **PR#4 CLOSED**, branch 残存)
- `origin/dependabot/npm_and_yarn/sdk/typescript/typescript-6.0.3` (behind 371)
- `origin/dependabot/pip/build-gte-1.4.4` (behind 371, **PR#9 CLOSED**, branch 残存)
- `origin/dependabot/pip/pandas-gte-3.0.2` (behind 373)
- `origin/dependabot/pip/pre-commit-gte-4.6.0` (behind 373)
- `origin/dependabot/pip/pyarrow-gte-24.0.0-and-lt-25` (behind 373)
- `origin/dependabot/pip/pytest-cov-gte-7.1.0` (behind 373)

---

## C. Commit history 異常

### C-1. 直近 100 commit 状態
- **sign-off**: 4 件 (4%) — 慣習化されていない
- **Co-Authored-By: Claude Opus 4.7**: 90 件 (90%) — Claude Code 規約遵守 OK
- **GPG sign (`%G?`)**:
  - `E` (good signature, expected): 7 件 (main マージ commit + dependabot push)
  - `N` (no signature): 93 件 — 大半が手動 push
  - 重大 sign 偽装は検出されず
- **pre-commit `--no-verify` bypass**: 検出 0 件 (R8 audit doc 内の言及はゴール記述のみ)

### C-2. amend 痕跡
- author_date != committer_date の commit 3 件:
  - `34a1817e` (commit lag 39 分) — rebase 痕跡、amend ではない
  - `b12f133d` (commit lag 41 分) — 同上、git rebase によるもの
  - `03f104c7` (commit lag 1.5 分) — wave-1 hotfix rebase
- **`--amend` の使用痕跡**: 検出 0 件 (memory「Never amend」原則遵守)
- **重複 commit subject の存在**: 4 件 — rebase 後の重ね打ち
  - `34a1817e` / `42f79f97`: 同 subject `fix(brand): jpintel public-facing leak strip` → critical_hotfix branch と redteam_hotfix branch で別々 commit
  - `b12f133d` / `801b3d32`: 同 subject `fix(deploy): hydrate step timeout 25→60 min` → 同上
  - これは PR#23 / PR#25 split 戦略の結果で異常ではない

### C-3. trust-center bot 自動 commit
- `892b3c25`, `42726c0a` (5/9 19:51Z + 19:39Z): trust-center weekly run
- 健全 (期待 cadence で動作中)

---

## D. 本セッション (5/11) state

| branch | 状態 | LIVE? | 措置 |
|---|---|---|---|
| **PR#25** (`feat/jpcite_2026_05_11_critical_hotfix`) | MERGED 5/11 03:57Z → main 94d5ddd4 | LIVE | branch 残存、user 承認後 delete |
| **PR#23** (`feat/jpcite_2026_05_11_redteam_hotfix`) | OPEN CONFLICTING DIRTY 859 files | dead | **close**、branch delete |
| **`feat/jpcite_2026_05_11_seo_pages`** | local only、空 (commit c66dba29 が hotfix と同一) | dead | delete |
| `v3/wave-1-batch` | PR#20 merge 済 5/11 02:08Z | done | branch delete OK |
| `codex-prod-deploy-20260507-0729` | local only、5/7 stub | dead | delete |

---

## 整理候補 (user 承認後実行)

### 即整理 Top-5 (red 優先度)

1. **PR#23 close** — 859 file conflict resurrect 不可能、修正内容は PR#25 で main に取り込み済。close comment で「superseded by #25」明記
2. **`feat/jpcite_2026_05_11_redteam_hotfix` branch delete** (local + remote) — PR#23 close 後
3. **`feat/jpcite_2026_05_11_seo_pages` branch delete** (local only) — commit 取消後の空 branch
4. **`codex-prod-deploy-20260507-0729` branch delete** (local only) — 5/7 codex stub、149 commit 未 push、main から大きく diverged で merge 不能
5. **`origin/bot/openapi-refresh` branch delete** (remote) — 5/2 stale、238 commit behind

### 中優先 (yellow)

6. **local main `git pull`** — 5 commit behind origin/main
7. **dependabot PR rebase batch** (PR#3, #7, #10, #11, #12, #13) — 11d stale, pytest 3.13 fail → re-run 後 merge
8. **PR#14 close** (OyaAIProd SafeSkill 50/100) — 7d stale、3rd party、merit 不明
9. **`origin/v3/wave-1-batch` delete** — PR#20 merge 済 5/11 02:08Z
10. **dependabot CLOSED PR の残存 branch 削除** (PR#4 関連 `dependabot/npm_and_yarn/sdk/typescript/types/node-25.6.0` / PR#9 関連 `dependabot/pip/build-gte-1.4.4`) — close 後 branch 残置

### 低優先 (green、keep のみ)

- `main` / `origin/main` — keep
- `feat/jpcite_2026_05_11_critical_hotfix` — keep until end-of-session、merge 反映済の verification 完了後 delete OK
- live dependabot PR (#6, #8, #21, #22) — release_readiness pass、user 承認で merge

---

## 棚卸し統計

```
Open PR             : 15
  CONFLICTING       : 1 (PR#23)
  MERGEABLE         : 13
  UNKNOWN           : 1 (PR#5 typescript breaking)
  stale (>7d)       : 11
  duplicate subject : 1 (PR#23 ≈ PR#25)

Closed PR (last 50) : 4 (merged 2, no-merge 2)

Local branches      : 6
  active            : 3 (main + 2 hotfix)
  delete candidate  : 3 (seo_pages, codex-prod-deploy, redteam_hotfix)

Remote branches     : 19
  long-running      : 1 (main)
  dependabot stale  : 14 (10 open + 2 closed-not-deleted + 2 LIVE PR)
  bot artifact stale: 1 (bot/openapi-refresh)
  live feature      : 3 (critical_hotfix, redteam_hotfix, v3/wave-1-batch)

Commit hygiene (last 100):
  Co-Authored-By    : 90 ok
  Signed-off-by     :  4
  GPG signed (E)    :  7 (merge commits + dependabot push)
  --no-verify       :  0 (clean)
  --amend           :  0 (clean)
  duplicate subj    :  4 (PR split による、anomalous でない)
```

---

## 禁止事項遵守確認 (CLAUDE memory)

- ✓ 実 PR close / branch delete 未実行 (audit のみ)
- ✓ "Phase" / "MVP" 表現排除
- ✓ 旧 brand (税務会計AI / AutonoMath / zeimu-kaikei.ai) 露出ゼロ — 内部 audit doc 内のみ legacy marker 言及
- ✓ priority question / 工数 / schedule の話 排除 — 全件「やる/やらない」二択で list 化
- ✓ memory `feedback_destruction_free_organization` — delete 提案は「user 承認後」前提

---

## 次セッション継続 hook

- PR#23 close 後の作業: branch delete (local + remote) + git fetch --prune
- live dependabot PR (#6, #8, #21, #22) は release_readiness gate pass、user 承認で immediate merge 可
- dependabot 古株 (#1, #5) は breaking change なので慎重に判断
