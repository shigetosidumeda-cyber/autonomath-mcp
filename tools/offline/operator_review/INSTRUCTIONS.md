# INSTRUCTIONS — codex / operator pickup

## 立ち上がり前 (現時点 2026-05-06)

- 本 dir の 5 file (+ 1 CSV) は **static draft**
- 寄稿 0 件 (DEEP-31 form 未公開) のため operator action は **不要**
- pickup blocker 一覧:
  1. DEEP-31 contribution form 公開 (FE)
  2. DEEP-28 migration (`mig_028_contribution_queue.sql`) 適用済
  3. DEEP-33 migration (`mig_033_contributor_trust.sql`) 適用済
  4. 寄稿 1+ 件 / 1 ヶ月

立ち上がり前は draft 維持のみ。 review_queue_cli.py を / Users / shigetoumeda / jpcite / tools / offline / operator_review / 配下にも 動かさない (codex lane が触らない)。

## 立ち上がり後 (DEEP-31 form 公開後 + 寄稿 1+ 件で trigger)

順番に:

### 1. CLI を canonical lane へ move

```
mkdir -p /Users/shigetoumeda/jpcite/tools/offline/operator_review
mv /Users/shigetoumeda/jpcite/tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_06/contribution-review-tools/review_queue_cli.py \
   /Users/shigetoumeda/jpcite/tools/offline/operator_review/review_queue_cli.py
mv /Users/shigetoumeda/jpcite/tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_06/contribution-review-tools/dry_run_data.csv \
   /Users/shigetoumeda/jpcite/tools/offline/operator_review/dry_run_data.csv
```

(残 4 md は draft 置きでも OK、 必要に応じて docs/operator/ へ tree-promote)

### 2. SQLite contribution_queue / contributor_trust 確認

```
sqlite3 /Users/shigetoumeda/jpcite/data/autonomath.db ".schema contribution_queue"
sqlite3 /Users/shigetoumeda/jpcite/data/autonomath.db ".schema contributor_trust"
```

両方 schema が出れば DEEP-28 + DEEP-33 migration 適用済。

### 3. dry-run smoke

```
python /Users/shigetoumeda/jpcite/tools/offline/operator_review/review_queue_cli.py \
       --dry-run /Users/shigetoumeda/jpcite/tools/offline/operator_review/dry_run_data.csv
```

期待値:
- 10 row 読込
- auto_approve = 3 程度 (税理士 cohort + trust >= 0.95)
- auto_reject = 2-3 程度 (aggregator / 業法 fence / PII / 2σ outlier の sample 含む)
- needs_manual = 残り

### 4. monthly review schedule 設定

`monthly_schedule.md` の iCal block を Google Calendar に import。

### 5. 1st review fire

queue に 1+ 件で 即実行 OK (毎月 1 日まで 待つ必要なし、 立ち上がり 1 回目だけ 任意 timing):

```
python /Users/shigetoumeda/jpcite/tools/offline/operator_review/review_queue_cli.py --interactive
```

---

## operator effort cap

- **30 分 / 月 cap**
- queue 60+ 件 → GHA cron `contribution-queue-monitor.yml` が auto-pause + alert
- alert 受領後 7 日以内に追加 review

## safety nets

| layer | mechanism |
|-------|-----------|
| client-side aggregator block | DEEP-31 form regex + autocomplete |
| server-side aggregator double check | review_queue_cli.py の `detect_aggregator()` |
| 業法 fence | DEEP-38 detector phrase mirror in `FENCE_PHRASES` |
| APPI individual PII | `PII_PATTERNS` (mynumber / phone / email) |
| outlier | DEEP-33 `outlier_sigma > 2.0` |
| SLA | GHA `contribution-queue-monitor.yml` cron alert |

## constraints (recap)

- LLM 呼出 0 (pure SQLite + argparse + regex)
- paid plan 提案 NG
- 工数 / phase 提案 NG
- aggregator NG
- jpcite 文脈のみ
- 個人 PII scrubber は DEEP-31 client-side + 本 CLI server-side の 2 段
