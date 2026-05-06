# monthly review schedule (Google Calendar setup)

## fixed-date cadence

- **毎月 1 日 09:00 JST** に固定
- 30 分 / 月 cap (cap 超過は auto-pause で safety)
- LLM 呼出 0、 jpcite 文脈のみ

## Google Calendar event

| field | value |
|-------|-------|
| title | jpcite contribution review |
| time | 月初 1 日 09:00 - 09:30 JST |
| recurrence | monthly (每月 1 日) |
| reminder | 1 日前 09:00 + 当日 1 時間前 (08:00) |
| description | `cd /Users/shigetoumeda/jpcite && python tools/offline/operator_review/review_queue_cli.py --interactive --month $(date +%Y-%m)` |
| color | jpcite blue |

### iCal クイック設定

`File > Import` で以下を `.ics` 化:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:jpcite contribution review
DTSTART;TZID=Asia/Tokyo:20260601T090000
DTEND;TZID=Asia/Tokyo:20260601T093000
RRULE:FREQ=MONTHLY;BYMONTHDAY=1
DESCRIPTION:cd /Users/shigetoumeda/jpcite && python tools/offline/operator_review/review_queue_cli.py --interactive --month $(date +%Y-%m)
BEGIN:VALARM
TRIGGER:-P1D
ACTION:DISPLAY
END:VALARM
BEGIN:VALARM
TRIGGER:-PT1H
ACTION:DISPLAY
END:VALARM
END:VEVENT
END:VCALENDAR
```

## 例外時の追加 schedule

- 月初 review で `pending >= 60` を観測 → 15 日 09:00 JST に 1 回限り追加 review (例外時のみ)
- 30 - 60 件 / 月初 → 通常 cadence で消化
- 0 - 29 件 / 月初 → 即終了、 残時間は 翌月へ

## operator 不在月

- skip OK、 翌月 catch up
- queue が 60+ で滞留した場合は GHA cron `contribution-queue-monitor.yml` が operator alert (Slack / email)
- alert を受けてから 7 日以内に追加 review を入れる

## 完了 marker

review session 終了時の自動 log:

```
/var/log/jpcite/review_YYYYMM.log
```

最終行に `session counts {...}` JSON を 残す。 翌月 kickoff の確認はこの log 1 ファイルだけで足りる。
