# jpcite contribution review — 30 分 / 月 checklist

monthly fixed-date: **毎月 1 日 09:00 JST**

寄稿件数 target: 30 - 100 件 / 月。 1 件 review 18 秒 - 1 分 (cohort 別 trust score 高い 寄稿は 即 approve)。

---

## 09:00 — kickoff

```
cd /Users/shigetoumeda/jpcite
python tools/offline/operator_review/review_queue_cli.py --month $(date +%Y-%m) --summary-only
```

- pending 件数を確認
- target: 30 - 100 件
- 60+ 件 → auto-pause flag (GHA cron alert) を確認、 必要なら 15 日 09:00 JST に 1 回追加
- 0 件 → skip OK、 翌月へ

## 09:05 — auto-batch

trust >= 0.95 かつ cohort=税理士 を 自動 approve、 明確 reject (aggregator / 業法 fence / PII / 2σ outlier) を 自動 reject。

```
python tools/offline/operator_review/review_queue_cli.py --month $(date +%Y-%m) --auto-approve-trust-above 0.95
```

- output JSON で `auto_approved` / `auto_rejected` を確認
- 残件 (manual review 必要) は次の interactive で処理

## 09:10 - 09:25 — interactive review

```
python tools/offline/operator_review/review_queue_cli.py --month $(date +%Y-%m) --interactive
```

各 row につき以下を 18 秒 - 1 分:

1. cohort + trust_score を 上から流し見
2. observed_eligibility_text を黙読
3. source_urls が 一次資料 (官公署 site) かどうか
4. 業法 fence 自己 check (DEEP-38 detector が phrase をハイライト)
5. APPI 配慮 (houjin_bangou は hash 受領済、 個人 PII 残骸が無いか目視)
6. キー入力:
   - `a` approve → quality_flag=community_verified が UPDATE される
   - `r` reject → R1-R5 から 番号選択
   - `s` skip (判断保留、 翌月の queue に残る)
   - `q` quit (緊急中断)

## 09:25 - 09:30 — wrap

- log を確認
  ```
  ls -la /var/log/jpcite/review_$(date +%Y%m).log
  tail -n 20 /var/log/jpcite/review_$(date +%Y%m).log
  ```
- 翌月分の calendar 通知が セットされているか目視 (Google Calendar)
- queue が 30+ 残っていれば DEEP-33 の trust_score 配分を再点検 cue として `_inbox/notes/review-followup-YYYY-MM.md` に 1 行 memo

---

## 自己 check 項目

- [ ] aggregator URL (noukaweb 等) は server-side double check で reject 済 (R1)
- [ ] 業法 fence phrase (採択保証 / 確実な税額 等) は R2 で reject
- [ ] 個人 PII (マイナンバー / 電話 / email) は R3 で reject
- [ ] program_id mismatch は R4 で reject
- [ ] 2σ outlier は R5 で reject (DEEP-33 outlier_sigma 自動付与)
- [ ] 法人番号は hash 受領 (raw 13桁が text に残っていないか)
- [ ] LLM 呼出 0 (本 CLI は pure SQLite + regex)

## auto-pause 条件

- 月初 1 回の review で `pending >= 60` → GHA `contribution-queue-monitor.yml` が operator alert
- 不在月 skip OK、 翌月 catch up
