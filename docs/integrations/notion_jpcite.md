---
title: "Notion Database sync with jpcite (program → page)"
slug: "notion-jpcite-integration"
audience: "ops / 営業 / 経営企画"
intent: "notion_db_sync"
related_tools: ["search_programs", "get_program_full_context", "subsidy_combo_finder"]
billable_units_per_run: 12
date_created: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Notion Database sync with jpcite

社内 Notion DB の `補助金リスト` テーブルを jpcite で **毎朝自動更新** する integration。新着制度の自動追加 + 期限切れ flag + 採択公表数の差分追記、すべて Notion API + jpcite REST で完結。

## 想定 user

- 中小企業 経営企画 / 営業 / コンサルティングファーム — 顧客に共有する補助金マスタを Notion で管理
- 手動更新は週末作業で 2-4 時間 → jpcite cron で 3 分 + diff レビュー 10 分に短縮

## Notion DB schema

| プロパティ名 | type | 用途 |
| --- | --- | --- |
| 制度名 | Title | name (jpcite `programs.name`) |
| program_id | Rich text | jpcite `programs.program_id` (unique key) |
| tier | Select (S/A/B/C) | jpcite `programs.tier` |
| 申請期限 | Date | jpcite `programs.application_deadline` |
| 最大補助額 | Number | jpcite `programs.max_amount_jpy` |
| 対象業種 | Multi-select | jpcite `programs.target_jsic` |
| source_url | URL | jpcite `programs.source_url` |
| 最終更新 | Date | jpcite `programs.source_fetched_at` |
| fit_score | Number | (optional) `client_profiles` 経由 |

## 実装 (Python + cron)

```python
# notion_sync.py
import os, requests
from datetime import datetime, timezone

JPCITE = "https://api.jpcite.com"
NOTION = "https://api.notion.com/v1"
DB_ID = os.environ["NOTION_DB_ID"]
HDR_JPCITE = {"X-API-Key": os.environ["JPCITE_API_KEY"]}
HDR_NOTION = {
    "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
    "Notion-Version": "2025-04-09",
    "Content-Type": "application/json",
}

def fetch_programs():
    r = requests.get(f"{JPCITE}/v1/programs/search?tier=S,A&active=true&limit=200", headers=HDR_JPCITE)
    r.raise_for_status()
    return r.json()["results"]

def list_notion_pages():
    pages = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor: body["start_cursor"] = cursor
        r = requests.post(f"{NOTION}/databases/{DB_ID}/query", headers=HDR_NOTION, json=body)
        r.raise_for_status()
        d = r.json()
        pages.extend(d["results"])
        if not d.get("has_more"): break
        cursor = d["next_cursor"]
    return pages

def page_to_pid(pg):
    rt = (pg["properties"].get("program_id", {}).get("rich_text") or [])
    return (rt[0].get("plain_text") if rt else None)

def to_notion_props(prog):
    return {
        "制度名": {"title": [{"text": {"content": prog["name"][:200]}}]},
        "program_id": {"rich_text": [{"text": {"content": prog["program_id"]}}]},
        "tier": {"select": {"name": prog["tier"]}},
        "申請期限": ({"date": {"start": prog["application_deadline"]}}
                  if prog.get("application_deadline") else {"date": None}),
        "最大補助額": {"number": prog.get("max_amount_jpy")},
        "対象業種": {"multi_select": [{"name": t} for t in (prog.get("target_jsic") or [])]},
        "source_url": {"url": prog.get("source_url")},
        "最終更新": {"date": {"start": prog.get("source_fetched_at", datetime.now(timezone.utc).isoformat())}},
    }

def sync():
    progs = {p["program_id"]: p for p in fetch_programs()}
    pages = {page_to_pid(p): p for p in list_notion_pages()}
    pages.pop(None, None)
    created, updated = 0, 0
    for pid, prog in progs.items():
        body = {"properties": to_notion_props(prog)}
        if pid in pages:
            requests.patch(f"{NOTION}/pages/{pages[pid]['id']}", headers=HDR_NOTION, json=body).raise_for_status()
            updated += 1
        else:
            body["parent"] = {"database_id": DB_ID}
            requests.post(f"{NOTION}/pages", headers=HDR_NOTION, json=body).raise_for_status()
            created += 1
    print(f"created={created} updated={updated} total_jpcite={len(progs)}")

if __name__ == "__main__":
    sync()
```

## cron (GitHub Actions)

```yaml
# .github/workflows/notion-jpcite-sync.yml
name: notion-jpcite-sync
on:
  schedule: [{ cron: "0 0 * * *" }]  # 09:00 JST 毎日
  workflow_dispatch: {}
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install requests
      - run: python notion_sync.py
        env:
          JPCITE_API_KEY: ${{ secrets.JPCITE_API_KEY }}
          NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
          NOTION_DB_ID: ${{ secrets.NOTION_DB_ID }}
```

## cost 試算

- 200 制度 × ¥3/req = ¥600/日 × 30d = **¥18,000/月** (Notion DB 1 本分)
- 営業 1 名の手動更新削減: 2-4h × 4w/月 × ¥3,000/h = ¥24,000-48,000/月
- **ROI: 1.3-2.7 倍 + 鮮度劣化リスク回避**

## known gaps

- Notion API は 3 req/sec rate limit、200 page 更新で 70 秒
- 削除された制度 (jpcite 側 inactive 化) は手動で Notion archive 推奨
- 採択公表数の追記は別 cron に分離推奨 (本 sync は schema のみ)

## canonical source

- jpcite REST API: <https://api.jpcite.com/docs>
- Notion API: <https://developers.notion.com/reference/intro>
- recipes/r15: <https://jpcite.com/recipes/r15-grant-saas-internal-enrich/>
