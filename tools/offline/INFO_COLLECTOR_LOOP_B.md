# jpcite 情報収集ループ B — 2 つ目の Claude Code CLI 用 standing prompt

本ファイルは **2 つ目の Claude Code CLI** に渡す standing prompt。
1 つ目の CLI が `egov_law_articles` (priority #1) を回しているので、
本 CLI は **それ以外の 19 source** だけを担当し、同時に走らせても衝突しないようにする。

起動方法:

```bash
cd /Users/shigetoumeda/jpcite
claude
/loop tools/offline/INFO_COLLECTOR_LOOP_B.md
```

---

## 0. 衝突回避ルール (最重要)

| 役割 | progress 状態 | inbox 出力 |
|---|---|---|
| **1 つ目 CLI (本ファイルではない方)** | `tools/offline/_inbox/_progress.json` / `_progress.md` | `tools/offline/_inbox/egov_law_articles/...` |
| **2 つ目 CLI (本ファイル)** | `tools/offline/_inbox/_progress_b.json` / `_progress_b.md` | `tools/offline/_inbox/{source_id}/...` (egov_law_articles **以外**) |

- 各 source は独自フォルダを持つので fetch 出力は衝突しない
- progress 状態だけが衝突点 → 別ファイル (`_progress_b.json`) に分離する
- **egov_law_articles は絶対に触らない**(本 CLI の queue から除外)
- 衝突した場合は本 CLI 側を優先 halt → 1 つ目を進めてから再開

---

## 1. 対象 source (priority 順 / 全 19 件)

`egov_law_articles` を除外した priority #2..#20 を本 CLI が担当する:

| # | source_id | 元 spec の seed | 想定 total |
|---|---|---|---|
| 1 | nta_tsutatsu_full | https://www.nta.go.jp/law/tsutatsu/kihon/houjin/index.htm 等 | ~3,000 |
| 2 | nta_kfs_saiketsu | https://www.kfs.go.jp/service/JP/idx/0000.html | ~10,000 |
| 3 | courts_hanrei | https://www.courts.go.jp/app/hanrei_jp/list1 等 | ~50,000 |
| 4 | jftc_dk | https://www.jftc.go.jp/dk/dkcase.html | ~500 |
| 5 | fsa_admin_disposal | https://www.fsa.go.jp/news/{R/H}{N}/{月}/index.html | ~2,000 |
| 6 | kokkai_minutes | https://kokkai.ndl.go.jp/api/meeting?... (JSON) | ~100,000 |
| 7 | estat_api | https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList?... | ~30,000 |
| 8 | geps_bids | https://www.geps.go.jp/bizportal/anken/ | ~50,000 |
| 9 | egov_public_comment | https://public-comment.e-gov.go.jp/servlet/Public?...&id=N | ~30,000 |
| 10 | egov_law_translation | https://www.japaneselawtranslation.go.jp/ja/laws/list/?page=N | ~700 |
| 11 | invoice_kohyo_zenken | https://www.invoice-kohyo.nta.go.jp/download/zenken/ (月次 zip) | 月 1 |
| 12 | erad_rd | https://www-erad-elsi.jsps.go.jp/ | ~50,000 |
| 13 | maff_excel | https://www.maff.go.jp/j/budget/koufu_kettei.html → Excel | ~100 file |
| 14 | meti_subsidy | https://www.meti.go.jp/information_2/publicoffer/ | ~3,000 |
| 15 | pref_subsidy | per-pref portal × 47 | ~50,000 |
| 16 | pref_giji | per-pref 議事録 portal × 47 | ~100,000 |
| 17 | city_giji | 政令指定都市 20 + 中核市 60 | ~500,000 |
| 18 | mof_tax_treaty | https://www.mof.go.jp/tax_policy/summary/international/tax_convention/ | ~80 国 |
| 19 | industry_certification | per-association seed × 800+ | ~800 |

**初回 init 時** に上記 19 source を `_progress_b.json` に登録する。

---

## 2. 動作仕様 (元 prompt から継承)

`tools/offline/INFO_COLLECTOR_LOOP.md` (= 1 つ目 CLI 用 spec) の **§0 鉄則 / §2 1 iter 手順 / §4 出力 schema / §5 Playwright テンプレ / §6 エラー処理 / §7 禁止事項 / §10 stdout フォーマット** をそのまま継承する。
本ファイルで上書きする差分は §0 衝突回避と §1 対象 source 限定のみ。

---

## 3. 1 iter の手順 (毎 tick これだけ)

### Step 1: progress 読み込み
`tools/offline/_inbox/_progress_b.json` を Read。なければ §1 の 19 source で init。

### Step 2: 次タスク選択
priority 順に scan して `status in {"pending","in_progress"}` の最先頭 source を選ぶ。
全 source completed なら `[DONE-B] all sources completed iter=N` を出力して loop 終了。

### Step 3: fetch / Step 4: 出力 / Step 5: 進捗更新
元 spec §3..§6 通り。

各 source ごとに必要な fetch 戦略:
- **JSON API** (kokkai_minutes / estat_api): WebFetch or urllib (offset pagination)
- **HTML index 系** (nta_tsutatsu_full / fsa_admin_disposal / meti_subsidy / mof_tax_treaty 等): WebFetch + 正規表現でリンク抽出 → 個別 page recurse
- **Playwright 必須** (courts_hanrei / nta_kfs_saiketsu / geps_bids / erad_rd / pref_giji / city_giji): viewport ≤ 1280×800 の sync_playwright で form 送信 + screenshot 必須
- **PDF / Excel / zip**: Bash + curl で `/tmp/` に DL → Read で先頭抜粋
- **per-pref / per-city seed JSON 必須** (pref_subsidy / pref_giji / city_giji / industry_certification): 初回 walk で `tools/offline/_seed/{...}.json` を作成 (他 CLI が作っていれば Read のみ)

### Step 6: 並列実行 (最大エージェント数)
1 tick = 10 sub-agent 並列、各 agent が 10 URL = 計 100 URL を取得。
DNS resolver 故障対策で **socket.getaddrinfo の monkey-patch (8.8.8.8 経由)** を全 agent script の冒頭に必ず入れる。テンプレ:

```python
import socket, dns.resolver
_r = dns.resolver.Resolver(configure=False); _r.nameservers = ['8.8.8.8','1.1.1.1']
_cache = {}; _orig = socket.getaddrinfo
def _patched(host, port, *a, **kw):
    try:
        if host not in _cache:
            ans = _r.resolve(host, 'A'); _cache[host] = str(ans[0])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (_cache[host], port))]
    except Exception:
        return _orig(host, port, *a, **kw)
socket.getaddrinfo = _patched
```

### Step 7: 次 tick schedule
ScheduleWakeup({delaySeconds: 60-180, prompt: "<<autonomous-loop-dynamic>>", reason: "..."})。
全 source completed なら schedule せずに終了。

---

## 4. stdout 1 行 summary

```
[B-{iter}] {source_id} +N ({completed}/{total}, {pct}%) — {title} ({slug})
```

接頭辞は **`[B-N]`** (1 つ目 CLI は `[I-N]` を使うので区別)。

---

## 5. progress 内 schema (`_progress_b.json`)

```json
{
  "started_at": "2026-05-05T...",
  "last_updated": "2026-05-05T...",
  "iterations": 0,
  "sources": {
    "nta_tsutatsu_full": {"status":"pending","completed_urls":0,"total_urls":3000,"next_url_index":0,"last_fetched_url":null,"quarantine":false},
    "nta_kfs_saiketsu":  {...},
    ...(19 件)
  },
  "errors": []
}
```

`egov_law_articles` は **登録しない** (= sources dict に key を作らない)。

---

## 6. 起動時 self-check (毎回 invocation の最初)

1. cwd が `/Users/shigetoumeda/jpcite` か (Bash `pwd`)
2. `tools/offline/_inbox/` が存在するか
3. `.venv/bin/python --version` OK か
4. `.venv/bin/python -c "from playwright.sync_api import sync_playwright; print('OK')"` OK か
5. `.venv/bin/python -c "import dns.resolver; print(dns.resolver.__name__)"` OK か (DNS patch 用)
6. `_progress_b.json` を Read (なければ §1 の 19 source で init)
7. user message に `stop` / `止めて` / `halt` があれば即終了
8. **`_progress.json` (1 つ目の CLI のもの) は read のみ可、write 絶対禁止**

self-check 失敗時:
```
[ABORT-B] reason=playwright_not_installed
[ABORT-B] reason=dns_module_missing
[ABORT-B] reason=cwd_mismatch
```

---

## 7. 1 つ目 CLI と同期取りたい場合

- 1 つ目 CLI が egov_law_articles 完了 → `_progress.json` の `sources.egov_law_articles.status == "completed"` になる
- そのとき本 CLI が完了していなければ、空きスロットとして egov_law_articles を本 CLI の queue に **追加** することは可 (差分 fetch 用)。ただし上書き禁止。

逆ケース (本 CLI が先に完了) も同様。

---

## 8. 完了判定

全 19 source の status="completed" → loop 終了。
`[DONE-B] all sources completed iter=N` を出力し ScheduleWakeup を打たずに exit。

---

## 9. user 監視

毎 iter 開始時に user 最新 message を確認:

- 「stop」「止めて」「halt」「終了」 → 即終了 `[HALT-B] reason=user_stop`
- 「skip <source_id>」 → 該当 source を quarantine、次 source へ
- 「focus <source_id>」 → priority queue を該当 1 本に絞る
- 「reset」 → `_progress_b.json` を退避 (`_progress_b.json.{ts}.bak`) して新規 init

---

## 10. メモリ

本 loop は `/Users/shigetoumeda/.claude/projects/-Users-shigetoumeda/memory/` へ memory を書かない。
loop 自身の状態は `_progress_b.json` に閉じ込める。

---

以上。本 prompt を読み終わったら **すぐに self-check → Step 1** を実行する。
報告は 1 行 summary のみ。詳細は `_progress_b.md` に残す。
