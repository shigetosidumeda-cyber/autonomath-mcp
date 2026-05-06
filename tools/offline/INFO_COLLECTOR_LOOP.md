# jpcite 情報収集ループ — 専用 CLI 用 standing prompt

このファイルは **新しい Claude Code CLI セッション** に渡す standing prompt である。
情報収集 1 本に専念し、本ファイルを再読み込みしながら無限ループする想定で書かれている。

起動方法 (推奨):

```bash
cd /Users/shigetoumeda/jpcite
claude
# 対話 prompt に入ったら:
/loop tools/offline/INFO_COLLECTOR_LOOP.md
```

`/loop` を interval 指定なしで起動 → dynamic mode。
各 tick (= 1 iteration = 1 source の 1 url 取得) 終了時に
`ScheduleWakeup({delaySeconds: 60-270, prompt: "<<autonomous-loop-dynamic>>", reason: "..."})`
で次 tick を schedule する。これで cache 内に留まりつつ収集を継続する。

---

## 0. プロジェクト前提 (新 CLI に context が無いので必読)

- **プロジェクト**: jpcite (運営: Bookyou株式会社, T8010001213708, 代表 梅田茂利)
- **本体**: 日本の公的制度 / 法令 / 判例 / 通達 を REST + MCP で配信する evidence-first context layer (¥3/req metered)
- **本 collector の目的**: jpcite の corpus を **一次資料 only** で水平/垂直に拡張し、API 配信に load する前段階として `tools/offline/_inbox/` に 1 行 1 url 単位で stage する
- **作業ディレクトリ**: `/Users/shigetoumeda/jpcite/`
- **作業対象 path**: `tools/offline/_inbox/{source_id}/...`、`tools/offline/_inbox/_screenshots/{source_id}/...`、`tools/offline/_inbox/_progress.json`、`tools/offline/_inbox/_progress.md`
- **触ってよい path**: 上記 inbox 配下のみ
- **触ってはいけない path**: `src/`, `tests/`, `docs/`, `scripts/`, `data/*.db`, `.github/`, `MASTER_PLAN_v1.md`, `CLAUDE.md`, `pyproject.toml`, `README.md`, `site/` (read だけ可、write 禁止)
- **git commit 禁止**: 本 loop は data 側のスナップショット蓄積のみ。コード変化なし。`git add` も `git commit` も叩かない

---

## 1. 鉄則 (絶対遵守 / 違反 = 即停止)

1. **一次資料のみ**を corpus 化する。一次資料 = 政府機関 (国・都道府県・市町村)、独立行政法人、裁判所、業界団体公式サイト
2. 禁止 aggregator (本文取得対象外):
   - `noukaweb.com`、`hojyokin-portal.jp`、`biz.stayway.jp`、`mirasapo-plus.go.jp` 本文 (J-NET21 / mirasapo は cross-link 用 reference のみ可、本文 corpus 化禁止)
3. **LLM API 完全禁止**:
   - `import anthropic` / `import openai` / `import google.generativeai` / `from claude_agent_sdk` を **どこにも書かない**
   - `os.environ.get("ANTHROPIC_API_KEY")` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` を読まない
   - 推論が必要なら sentence-transformers (intfloat/multilingual-e5-large) ローカル実行のみ可。但し本 collector では embedding 化は別 wave に委譲し、生 body の保存に専念する
4. **TOS の collection-phase 解釈**:
   - 今は商用配信判断ではなく raw fetch + content_hash + license note を残す段階
   - robots.txt deny は無視可 (商用配信時に license 再評価)
   - login 必須 / API key 必須 / 有料 source は **scope 外** とし quarantine flag で記録
5. **fail-fast でなく fail-resume**:
   - 1 url 失敗で loop を止めない。例外を捕まえて `_progress.json.errors[]` に append、次 url に進む
6. **fabrication 禁止**:
   - 取得失敗 url は空のまま残す。jsonl 行を捏造しない
   - HTTP 200 を装って空 body を保存しない
7. **viewport 1500px 厳守**:
   - Playwright の viewport.width は **必ず 1280 (推奨) または最大 1500**
   - 1500 超で screenshot を撮ると CLI 側がクラッシュする (ハード上限)
8. **既存 inbox row を上書きしない**:
   - jsonl は append-only
   - 同一 url を再 fetch する場合は新 row として追記 (`fetched_at` で時系列保持)
9. **`_progress.json` は atomic write**:
   - `_progress.json.tmp` に書いてから `os.rename` で置換
   - 部分書き込みで JSON が壊れると loop 全停止
10. **stop 検知**:
    - user の最新 message に「stop」「止めて」「halt」が含まれていたら ScheduleWakeup を **打たず** に終了
    - その場合の最後の出力は `[HALT] reason=user_stop iter=N` の 1 行だけ

---

## 2. 1 iteration の手順 (毎 tick これだけやる)

### Step 1: progress 読み込み

`tools/offline/_inbox/_progress.json` を Read。なければ Step 1.1 (init) へ。

### Step 1.1: 初回 init (progress.json 不在時のみ)

下記の 20 source を初期 queue として登録、status="pending" / completed_urls=0 で `_progress.json` を作成。
priority 順は §3 表の通り。同時に空の `_progress.md` を作成。

### Step 2: 次タスク選択

priority 順に scan して `status in {"pending", "in_progress"}` の最先頭 source を選ぶ。
その source の `next_url_index` 番目の url を取得する (§3 表の seed と pagination 規則から導出)。
全 source completed なら Step 7 へ (loop 終了)。

### Step 3: fetch 実行

§3 表の `method` 列に従って fetch:

- **WebFetch**: HTML / JSON / XML / 静的 PDF index に使う。Claude Code 標準ツール
- **Bash + curl**: WebFetch で取れない (binary, very large, custom header) 場合のフォールバック。`curl -sSL -o /tmp/<slug>.<ext> --max-time 60 -A "jpcite-collector/1.0 (+info@bookyou.net)" <url>` のあと Read で開く
- **Playwright (Bash 経由)**: JS render / form 送信 / pagination / SPA に使う。下記テンプレ使用 (§5)
- **PDF**: `Read` tool が PDF 直読みできるので、curl で `/tmp/` に落としてから Read

各 fetch の前に **3 秒 sleep** (server 礼儀)。連続 fetch で attack 扱いされないように。

### Step 4: 出力 (jsonl append + raw body 保存)

jsonl path:
```
tools/offline/_inbox/{source_id}/{YYYY-MM-DD}.jsonl
```

1 行 schema (1 url = 1 row):

```json
{
  "fetched_at": "2026-05-05T11:32:15Z",
  "source_id": "egov_law_articles",
  "url": "https://laws.e-gov.go.jp/api/2/law_data/415AC1000000086",
  "http_status": 200,
  "content_hash": "sha256:abc123...",
  "mime": "application/json",
  "license": "cc_by_4.0",
  "body_path": "tools/offline/_inbox/egov_law_articles/raw/415AC1000000086.json",
  "title": "個人情報の保護に関する法律",
  "extracted_text": "(短い title + 第一条抜粋、最大 500 字)",
  "screenshot_path": null,
  "fetch_method": "WebFetch",
  "notes": ""
}
```

raw body は `tools/offline/_inbox/{source_id}/raw/{slug}.{ext}` に別保存。content_hash は body の sha256:

```python
import hashlib
content_hash = "sha256:" + hashlib.sha256(body_bytes).hexdigest()
```

### Step 5: スクリーンショット (Playwright 系のみ)

Playwright 利用時は **常に screenshot を撮り** `screenshot_path` に記録する。
viewport は **必ず ≤ 1500px**。推奨 1280×800。

テンプレ (Bash で `python -c` インライン実行):

```bash
.venv/bin/python << 'PYEOF'
from playwright.sync_api import sync_playwright
import sys, hashlib, pathlib, datetime

URL = "<URL_HERE>"
SOURCE = "<SOURCE_ID>"
SLUG = "<URL_DERIVED_SLUG>"
SCREENSHOT_DIR = pathlib.Path(f"tools/offline/_inbox/_screenshots/{SOURCE}")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_PATH = SCREENSHOT_DIR / f"{SLUG}.png"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},  # 必ず 1500 以下
        user_agent="jpcite-collector/1.0 (+info@bookyou.net)",
        locale="ja-JP",
    )
    page = context.new_page()
    page.goto(URL, wait_until="networkidle", timeout=30000)
    page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
    html = page.content()
    title = page.title()
    browser.close()

print("OK", SCREENSHOT_PATH, len(html), title[:80])
PYEOF
```

`full_page=True` で縦は伸びるが幅は viewport 固定 → 1280px 幅 PNG が確実。

撮った screenshot を Read して目視確認したい場合は **Read tool** を使う (Claude Code が画像を読める)。

### Step 6: progress 更新 + summary 出力

`_progress.json` を atomic 更新:
- `iterations += 1`
- `last_updated = now()`
- `sources[source_id].completed_urls += 1`
- `sources[source_id].next_url_index += 1`
- `sources[source_id].last_fetched_url = url`
- 全 url 完了なら `sources[source_id].status = "completed"`

`_progress.md` を regenerate (テンプレ §6)。

stdout に 1 行 summary:

```
[I-47] egov_law_articles +1 (200/9484, 2.1%) — 個人情報の保護に関する法律 (415AC1000000086)
```

### Step 7: 次 tick schedule

全 source completed → ScheduleWakeup を呼ばずに `[DONE] all sources completed iter=N` 出力で終了。

そうでない → `ScheduleWakeup({delaySeconds: 90, prompt: "<<autonomous-loop-dynamic>>", reason: "次 url を取得 (egov_law_articles)"})` を呼ぶ。
delaySeconds は 60-270 の範囲で、長い fetch (Playwright) 直後は 60、軽い fetch (WebFetch JSON) 後は 90 程度。
**300 秒以上にはしない** (cache TTL を超えると context 再 prefill で遅い)。

---

## 3. 収集対象 source 定義 (priority 順)

| # | source_id | seed url | method | pagination 規則 | license | 想定 total |
|---|---|---|---|---|---|---|
| 1 | `egov_law_articles` | `https://laws.e-gov.go.jp/api/2/law_data/{lawnum}?law_full_text_format=json` | WebFetch | 既存 9,484 件の lawnum を `data/jpintel.db` の `laws.law_id` から SELECT (read-only)。なければ `https://laws.e-gov.go.jp/api/2/laws?ja=true&limit=500&offset=N` で walk | cc_by_4.0 | 9,484 |
| 2 | `nta_tsutatsu_full` | `https://www.nta.go.jp/law/tsutatsu/kihon/houjin/index.htm` (法基通) + `/shotoku/index.htm` (所基通) + `/shohi/index.htm` (消基通) | WebFetch (HTML index → 各通達 page) | index page をパース → 各 pageへ recurse | gov_standard | ~3,000 |
| 3 | `nta_kfs_saiketsu` | `https://www.kfs.go.jp/service/JP/idx/0000.html` | Playwright (年・税目別 index) | 年×税目の組合せ全走査 | gov_standard | ~10,000 |
| 4 | `courts_hanrei` | `https://www.courts.go.jp/app/hanrei_jp/list1` (民事) + `/list2` (行政) + `/list3` (刑事) | Playwright (検索 form 送信) | 年単位で 1947→現在 walk、結果は事件番号で個別 page | gov_standard | ~50,000+ |
| 5 | `jftc_dk` | `https://www.jftc.go.jp/dk/dkcase.html` | WebFetch (HTML index) → curl で PDF DL → Read | 年別 index、各事件 PDF | gov_standard | ~500 |
| 6 | `fsa_admin_disposal` | `https://www.fsa.go.jp/news/{R/H}{N}/{month}/index.html` | WebFetch | 年月 walk (令和元年 5 月以降) | gov_standard | ~2,000 |
| 7 | `kokkai_minutes` | `https://kokkai.ndl.go.jp/api/meeting?startRecord=1&maximumRecords=100&recordPacking=json` | WebFetch (JSON API) | startRecord += 100 で walk | public_domain | ~100,000+ |
| 8 | `estat_api` | `https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList?appId=&limit=100` (appId 不要 path) | WebFetch (JSON) | offset += 100 | gov_standard | ~30,000 stat tables |
| 9 | `geps_bids` | `https://www.geps.go.jp/bizportal/anken/` | Playwright (検索 form) | 公示日範囲で年月 walk | gov_standard | ~50,000/年 |
| 10 | `egov_public_comment` | `https://public-comment.e-gov.go.jp/servlet/Public?CLASSNAME=PCMMSTDETAIL&id=N` | WebFetch | id を 1 から linear walk | gov_standard | ~30,000 |
| 11 | `egov_law_translation` | `https://www.japaneselawtranslation.go.jp/ja/laws/list/?page=N&limit=100` | WebFetch | page walk、各 law detail へ | gov_standard | ~700 |
| 12 | `invoice_kohyo_zenken` | `https://www.invoice-kohyo.nta.go.jp/download/zenken/` | Bash (curl で zip DL) → unzip → Read で先頭 100 行 | 月初 zip 1 本 (4M 行)、unzip して `tools/offline/_inbox/invoice_kohyo_zenken/raw/{YYYY-MM}.csv` に保存。jsonl は zip 単位 1 row | pdl_v1.0 | 月 1 回 |
| 13 | `erad_rd` | `https://www-erad-elsi.jsps.go.jp/` | Playwright (検索) | 公開課題 search、年度 walk | gov_standard | ~50,000 |
| 14 | `maff_excel` | `https://www.maff.go.jp/j/budget/koufu_kettei.html` | WebFetch (HTML index) → curl で Excel DL | 年度別 Excel link 抽出 | gov_standard | ~100 file |
| 15 | `meti_subsidy` | `https://www.meti.go.jp/information_2/publicoffer/` | WebFetch (HTML 一覧) | 年月別 walk | gov_standard | ~3,000 |
| 16 | `pref_subsidy` | per-pref seed (下記 §3.1) | WebFetch | 都道府県 47 × 年度 | gov_standard | ~50,000 |
| 17 | `pref_giji` | per-pref 議事録 portal (下記 §3.2) | Playwright | 47 都道府県議会、回別 walk | gov_standard | ~100,000 |
| 18 | `city_giji` | 政令指定都市 20 + 中核市 60 議会 | Playwright | 都市別 walk | gov_standard | ~500,000 |
| 19 | `mof_tax_treaty` | `https://www.mof.go.jp/tax_policy/summary/international/tax_convention/` | WebFetch (HTML index) → 各国 PDF | 80 国 walk | gov_standard | ~80 国 |
| 20 | `industry_certification` | per-association seed (下記 §3.3) | WebFetch | 業界団体 800+ | proprietary (本文要 license 確認、index のみ corpus) | ~800 |

### §3.1 都道府県 補助金 portal seed (47)

47 件分は個別 portal を持つ。各 source の `next_url_index` は portal 番号 (1..47)。
portal URL 一覧 (`tools/offline/_seed/pref_subsidy_portals.json` を新規作成して列挙する。下記がテンプレ):

```json
[
  {"pref": "北海道", "url": "https://www.pref.hokkaido.lg.jp/kk/keieisien.html"},
  {"pref": "青森県", "url": "https://www.pref.aomori.lg.jp/sangyo/..."},
  // ... 47 件、初回 init 時に新 CLI が WebFetch で 47 件補完して書く
]
```

初回 iteration で seed JSON を作成 (47 portal の URL を Web 検索 + WebFetch で確認しつつ列挙)。
以降は seed JSON を読んで walk。

### §3.2 都道府県議会 議事録 portal seed (47)

同様に `tools/offline/_seed/pref_giji_portals.json` を初回 walk で作成。
ヒント: ほとんどの議会が `kaigiroku.net` または独自システムを使う。
seed 例:

```json
[
  {"pref": "北海道", "system": "kaigiroku.net", "url": "https://www.dgs-kaigiroku.dbsr.jp/hokkaido/index.html"},
  {"pref": "東京都", "system": "custom", "url": "https://asp.db-search.com/tokyo/"},
  ...
]
```

### §3.3 業界団体認定 seed (800+)

`tools/offline/_seed/industry_certifications.json` を初回 walk で作成。
カテゴリ: ISO 認定/JIS マーク/業種別マーク/エコマーク/くるみん/ユースエール/健康経営優良法人 等。

---

## 4. 出力 schema (再掲・厳守)

### 4.1 inbox jsonl row (1 url = 1 row)

```json
{
  "fetched_at": "2026-05-05T11:32:15Z",
  "source_id": "egov_law_articles",
  "url": "https://laws.e-gov.go.jp/api/2/law_data/415AC1000000086",
  "http_status": 200,
  "content_hash": "sha256:abc123...",
  "mime": "application/json",
  "license": "cc_by_4.0",
  "body_path": "tools/offline/_inbox/egov_law_articles/raw/415AC1000000086.json",
  "title": "個人情報の保護に関する法律",
  "extracted_text": "(title + 第一条 + 最大 500 字)",
  "screenshot_path": null,
  "fetch_method": "WebFetch",
  "notes": ""
}
```

### 4.2 progress.json

```json
{
  "started_at": "2026-05-05T10:00:00Z",
  "last_updated": "2026-05-05T11:32:15Z",
  "iterations": 47,
  "sources": {
    "egov_law_articles": {
      "status": "in_progress",
      "completed_urls": 200,
      "total_urls": 9484,
      "next_url_index": 201,
      "last_fetched_url": "https://laws.e-gov.go.jp/api/2/law_data/...",
      "quarantine": false
    },
    ...
  },
  "errors": [
    {"ts": "2026-05-05T11:30:00Z", "source_id": "courts_hanrei", "url": "...", "kind": "http_503", "msg": "..."}
  ]
}
```

### 4.3 progress.md (人間用、毎 iteration regenerate)

```md
# jpcite 情報収集ループ 進捗

開始: 2026-05-05 10:00 JST
最終更新: 2026-05-05 11:32 JST
iterations: 47

## ソース別

| # | source | status | done | total | % | quarantine |
|---|---|---|---|---|---|---|
| 1 | egov_law_articles | in_progress | 200 | 9484 | 2.1% | - |
| 2 | nta_tsutatsu_full | pending | 0 | ~3000 | 0% | - |
| ... | | | | | | |

## エラー (直近 10)

- 2026-05-05 11:30 courts_hanrei /list1 → 503 timeout (quarantine 1h)
```

---

## 5. Playwright テンプレ (再掲)

```bash
.venv/bin/python << 'PYEOF'
from playwright.sync_api import sync_playwright
import sys, hashlib, pathlib, datetime, json, re

URL = "<URL>"
SOURCE_ID = "<SOURCE>"
# slug は url から英数字 + - のみで生成
SLUG = re.sub(r"[^a-zA-Z0-9_-]", "_", "<SLUG>")[:80]

ROOT = pathlib.Path("/Users/shigetoumeda/jpcite")
SHOT_DIR = ROOT / "tools/offline/_inbox/_screenshots" / SOURCE_ID
RAW_DIR = ROOT / "tools/offline/_inbox" / SOURCE_ID / "raw"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)
shot = SHOT_DIR / f"{SLUG}.png"
raw  = RAW_DIR  / f"{SLUG}.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},  # 必ず ≤ 1500
        user_agent="jpcite-collector/1.0 (+info@bookyou.net)",
        locale="ja-JP",
    )
    page = ctx.new_page()
    try:
        page.goto(URL, wait_until="networkidle", timeout=30000)
    except Exception as e:
        print("ERR_NAVIGATE", e)
        sys.exit(1)
    page.screenshot(path=str(shot), full_page=True)
    html = page.content()
    raw.write_text(html, encoding="utf-8")
    print(json.dumps({
        "title": page.title(),
        "screenshot": str(shot.relative_to(ROOT)),
        "raw": str(raw.relative_to(ROOT)),
        "content_hash": "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "len": len(html),
    }, ensure_ascii=False))
    browser.close()
PYEOF
```

エラー時 (navigate 失敗 / timeout) は exit 1。
loop 側は exit code を見て progress.errors に append し次 url へ進む。

---

## 6. エラー処理表

| 症状 | 行動 |
|---|---|
| HTTP 200 + body 空 | URL 構築ミスとして errors に記録、次 url へ。3 連続発生で source quarantine (1 時間) |
| HTTP 403 / 401 | 60 秒待って再 try。それでも 403 → source quarantine (24 時間)、次 source へ |
| HTTP 429 | Retry-After header があればその秒数待つ。なければ 120 秒待つ |
| HTTP 500 / 503 | 30 秒待って再 try。3 連続で source quarantine (1 時間) |
| Playwright timeout | viewport を 1024×768 に縮小して再 try。それでも失敗で次 url |
| Cookie / login 必須 | source quarantine (永続)、scope 外として記録 |
| robots.txt deny | 無視。collection-phase 判断 |
| HTML が想定と違う構造 | extracted_text に空文字、notes に "structure_drift" を入れて raw のみ保存 |
| binary (zip/xlsx/pdf) | body_path に保存し extracted_text は空、mime を正しく設定 |
| 文字化け | charset を `<meta charset>` から推定、それでも失敗なら `cp932` フォールバック |

quarantine 期間が過ぎたら次回 init で status を pending に戻す。

---

## 7. 禁止事項 (絶対)

1. LLM SDK import (anthropic / openai / google.generativeai / claude_agent_sdk) を **書かない**
2. LLM API key env var (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY`) を **読まない**
3. aggregator (noukaweb 等) の本文を corpus 化しない
4. fetched url の捏造 (実 fetch せず JSON 行を作る) 禁止
5. viewport width > 1500px の screenshot 禁止
6. license 未確認の content を licensed 扱い (cc_by_4.0 等) で記録しない (不明なら "unknown")
7. progress.json を atomic でなく書き換えない (壊すと全停止)
8. 既存 jsonl 行を上書き編集しない (append-only)
9. `git commit` / `git add` を叩かない
10. `src/`, `tests/`, `docs/`, `scripts/`, `data/*.db`, `.github/`, `MASTER_PLAN_v1.md`, `CLAUDE.md`, `pyproject.toml`, `README.md`, `site/` を **編集** しない (read のみ可)
11. 同一 url を 1 iteration 内で複数回 fetch しない (rate limit 対策)
12. delaySeconds を 60 未満 / 300 以上に設定しない
13. 1 iteration で複数 source を跨いで処理しない (1 iter = 1 url 厳守)
14. Playwright で `headless=False` を使わない (server で X 不要)
15. `os.system` / `subprocess.call` で `rm -rf` 等の destructive 命令を打たない

---

## 8. 完了判定

- 全 20 source (+seed JSON 由来の追加 source) の status="completed" → loop 終了
- ScheduleWakeup を打たずに `[DONE] all sources completed iter=N` 出力
- progress.md に最終 summary を残す
- exit

ただし `total_urls` は推定値なので、実際の walk 中に増減することがある。
全部完了は `next_url_index >= total_urls` かつ source_walk が「もう次 page なし」を返した時点。

---

## 9. user message 監視

毎 iteration 開始時に最新の user message を確認 (loop 側が prompt として渡してくる場合あり)。

- 「stop」「止めて」「halt」「終了」 → 即終了 ([HALT] reason=user_stop)
- 「skip <source_id>」 → 該当 source を quarantine、次 source へ
- 「focus <source_id>」 → priority queue を該当 source 1 本に絞る
- 「reset」 → progress.json を退避 (`_progress.json.{ts}.bak`) して新規 init
- 上記以外 → 通常 iteration

---

## 10. 各 iteration の出力フォーマット (stdout)

最後に必ず 1 行 summary を出す:

```
[I-{iter}] {source_id} +1 ({completed}/{total}, {pct}%) — {title} ({slug})
```

例:

```
[I-47] egov_law_articles +1 (200/9484, 2.1%) — 個人情報の保護に関する法律 (415AC1000000086)
```

エラー時:

```
[I-47] courts_hanrei ERR http_503 url=https://... — quarantined 1h
```

詳細はこの 1 行以外には書かない (token 節約)。詳細を見たい場合 user は `_progress.md` を Read する。

---

## 11. 起動 / 再起動 / 停止

### 起動
```bash
cd /Users/shigetoumeda/jpcite
claude
# 対話 prompt で:
/loop tools/offline/INFO_COLLECTOR_LOOP.md
```

### 再起動 (新セッション、続きから)
- `_progress.json` を読み込んで自動 resume
- 同じ `/loop tools/offline/INFO_COLLECTOR_LOOP.md` で OK

### 停止
- Ctrl+C で即停止 (ScheduleWakeup が打たれていなければ次 tick は無し)
- もしくは user 側 prompt に `stop` と書く → 次 iteration で正常終了

### 状態確認 (別セッションから)
```bash
cat /Users/shigetoumeda/jpcite/tools/offline/_inbox/_progress.md
ls /Users/shigetoumeda/jpcite/tools/offline/_inbox/
```

---

## 12. メモリへの書き込みについて

本 loop は `/Users/shigetoumeda/.claude/projects/-Users-shigetoumeda/memory/` へ memory を書かない。
理由: 他 CLI セッションのワークと混ぜたくないため。
loop 自身の状態は `_progress.json` に閉じ込める。

---

## 13. 起動時 self-check (毎回 invocation の最初)

1. 自分の cwd が `/Users/shigetoumeda/jpcite` か確認 (Bash `pwd`)
2. `tools/offline/_inbox/` が存在するか確認 (なければ mkdir)
3. `.venv/bin/python` が動くか (`--version`)
4. `playwright` が install 済か (`.venv/bin/python -c "import playwright; print(playwright.__version__)"`)
5. `_progress.json` を Read (なければ init)
6. user message に `stop` 系があれば即終了
7. 上記 OK なら Step 2 (次タスク選択) へ進む

self-check で問題があれば 1 行報告して halt:
```
[ABORT] reason=playwright_not_installed
```

---

以上。本 prompt を読み終わったら **すぐに Step 1 (progress 読み込み) を実行** し、1 url 取得して終わる。
報告は 1 行 summary のみ。詳細は `_progress.md` に残す。
