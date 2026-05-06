# jpcite 情報収集ループ C — 3 つ目の Claude Code CLI 用 standing prompt

本ファイルは **3 つ目の Claude Code CLI** に渡す standing prompt。

- A 側 CLI: `egov_law_articles` を **queue 頭から正方向** で fetch (progress: `_progress.json`)
- B 側 CLI: それ以外の 19 source を担当 (progress: `_progress_b.json`)
- **C 側 CLI (本ファイル)**: `egov_law_articles` の **queue 末尾から逆方向** で fetch (progress: `_progress_c.json`)

A と C は同じ source を共有するが queue の両端から進むため、raw ファイル単位で衝突しない。中央で出会ったら C 側が halt する。

起動方法:

```bash
cd /Users/shigetoumeda/jpcite
claude
/loop tools/offline/INFO_COLLECTOR_LOOP_C.md
```

---

## 0. 衝突回避ルール (最重要)

| 役割 | progress 状態 | queue 進行方向 | inbox 出力 |
|---|---|---|---|
| A 側 CLI | `_progress.json` | queue[0] → queue[N-1] (正方向) | `tools/offline/_inbox/egov_law_articles/raw/{ln}.json` |
| B 側 CLI | `_progress_b.json` | (egov_law_articles は触らない) | `tools/offline/_inbox/{source_id}/...` (egov_law_articles 以外) |
| **C 側 CLI** | **`_progress_c.json`** | **queue[N-1] → queue[0] (逆方向)** | A と同じ raw/ ディレクトリ |

衝突回避の具体策:

1. **raw ファイル名が lawnum 単位** なので物理的に上書き不可 (write 前に exists() チェックで skip)
2. **progress state は別ファイル** (`_progress_c.json`) に分離、A の `_progress.json` は read-only
3. **convergence check**: 毎 iter 開始時に A の `next_url_index` (head) と C の `next_url_index_back` (tail) を比較し、**head > tail** になれば C 側 halt
4. C は A が下から取り終わった可能性のある lawnum も skip する (raw exists check)

---

## 1. 対象 source

`egov_law_articles` のみ。queue は A 側と同じ `tools/offline/_inbox/egov_law_articles/_law_ids.json`。

---

## 2. 進行方向

- queue total = 9484
- C は **末尾 (index=9483) から開始**、index を decrement しながら fetch
- 既に raw に存在する lawnum (= A 側か C の前回 iter で取得済) は skip
- 1 iter = 10 sub-agent × 10 lawnum = 計 100 lawnum

例:
- iter 1: queue[9483:9383:-1] を 10 agent で分担 (各 10 件)
- iter 2: queue[9383:9283:-1] を 10 agent で分担
- ...

---

## 3. 動作仕様

`tools/offline/INFO_COLLECTOR_LOOP.md` (= A 側 spec) の **§0 鉄則 / §4 出力 schema / §5 fetch 仕様 / §6 エラー処理 / §7 禁止事項** を継承。

差分:
- queue traversal が逆方向
- progress state が `_progress_c.json`
- stdout 接頭辞が `[C-N]`
- DNS resolver 故障対策で **socket.getaddrinfo の monkey-patch (8.8.8.8 経由)** を全 agent script の冒頭に必ず入れる:

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

---

## 4. 1 iter の手順

### Step 1: A 側 progress 読み込み (read-only)
`_progress.json` を Read。`sources.egov_law_articles.next_url_index` = A の head pointer (=h)。

### Step 2: C 側 progress 読み込み / init
`_progress_c.json` を Read。なければ以下で init:

```json
{
  "started_at": "2026-05-05T...",
  "last_updated": "2026-05-05T...",
  "iterations": 0,
  "sources": {
    "egov_law_articles": {
      "status": "in_progress",
      "completed_urls_back": 0,
      "next_url_index_back": 9483,
      "last_fetched_url": null,
      "quarantine": false
    }
  },
  "errors": []
}
```

### Step 3: convergence check
- C の next_url_index_back を t (=tail pointer) とする
- **t < h** なら head と tail が交差済 → `[DONE-C] converged at index=t (A head=h)` を出力して loop 終了 (ScheduleWakeup を打たない)

### Step 4: 100 lawnum slice
queue[t:t-100:-1] (10 agent × 10 件)。t が 100 未満なら queue[t::-1] に縮める。raw に既存の lawnum は agent script 内で skip。

### Step 5: 10 sub-agent 並列 fetch
A 側 spec §3..§5 と同形式。jsonl は `2026-05-05_iter{N}_agentC{X}.jsonl` (agent 名衝突回避のため `agentC{X}` prefix 推奨)。

### Step 6: 進捗更新 (recount-from-tail)
queue を末尾から走査して、連続して raw に存在する lawnum 数を completed_urls_back とする。next_url_index_back = 9483 - completed_urls_back。atomic write `_progress_c.json`。

### Step 7: stdout summary

```
[C-{iter}] egov_law_articles +N (back={completed_urls_back}/9484, tail_idx={t}) — {title} ({slug})
```

### Step 8: 次 tick schedule
ScheduleWakeup({delaySeconds: 60-180, prompt: "<<autonomous-loop-dynamic>>", reason: "..."})。convergence なら schedule せずに終了。

---

## 5. progress 内 schema (`_progress_c.json`)

```json
{
  "started_at": "2026-05-05T...",
  "last_updated": "2026-05-05T...",
  "iterations": 0,
  "sources": {
    "egov_law_articles": {
      "status": "in_progress",
      "completed_urls_back": 0,
      "next_url_index_back": 9483,
      "last_fetched_url": null,
      "quarantine": false
    }
  },
  "errors": []
}
```

`completed_urls_back` = queue 末尾から連続で raw 存在する件数。
`next_url_index_back` = 次に fetch 開始する index (decrement 方向)。

---

## 6. 起動時 self-check (毎回 invocation の最初)

1. cwd が `/Users/shigetoumeda/jpcite` か (Bash `pwd`)
2. `tools/offline/_inbox/egov_law_articles/raw/` が存在するか
3. `.venv/bin/python --version` OK か
4. `.venv/bin/python -c "import dns.resolver; print(dns.resolver.__name__)"` OK か (DNS patch 用)
5. `_law_ids.json` を Read して total=9484 確認
6. `_progress.json` (A 側) を Read して head pointer を取得
7. `_progress_c.json` を Read (なければ init)
8. **convergence check**: head > tail なら即 `[DONE-C]` 出力して終了
9. user message に `stop` / `止めて` / `halt` / `終了` があれば即終了 `[HALT-C] reason=user_stop`
10. **`_progress.json` (A 側) と `_progress_b.json` (B 側) は read のみ可、write 絶対禁止**

self-check 失敗時:
```
[ABORT-C] reason=dns_module_missing
[ABORT-C] reason=cwd_mismatch
[ABORT-C] reason=raw_dir_missing
```

---

## 7. A 側との同期

- C 側の毎 iter Step 1 で A の head を取得
- A が中央付近まで進んだら、C は `t < h` で halt
- ただし A が一時停止 / レートリミット中でも C は独立して走り続ける (head 値は最新の disk 状態を信用、recount-from-disk で C 側の tail 計数)

---

## 8. 完了判定

- t (next_url_index_back) < h (A head) → `[DONE-C] converged at idx=t (A=h)` で halt
- queue 全件 raw 存在 (head ≥ 9484) → 同様に halt
- ScheduleWakeup を打たずに exit

---

## 9. user 監視

毎 iter 開始時に user 最新 message を確認:

- 「stop」「止めて」「halt」「終了」 → 即終了 `[HALT-C] reason=user_stop`
- 「進め」「continue」「続き」 → 即 1 iter 実行
- 「reset」 → `_progress_c.json` を退避 (`_progress_c.json.{ts}.bak`) して新規 init
- 「skip {lawnum}」 → 該当を `quarantine` に追加 (将来 fetch しない)

---

## 10. メモリ

本 loop は `/Users/shigetoumeda/.claude/projects/-Users-shigetoumeda/memory/` へ memory を書かない。
loop 自身の状態は `_progress_c.json` に閉じ込める。

---

## 11. 1 iter 雛形 (C 側 agent script)

```python
import socket, dns.resolver, urllib.request, json, hashlib, time
from pathlib import Path
from datetime import datetime, timezone

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

LAWS = [...]  # 末尾から 10 件、agentC{X} の担当分
ITER, AGENT = 1, 1
inbox = Path("tools/offline/_inbox/egov_law_articles")
raw   = inbox / "raw"; raw.mkdir(parents=True, exist_ok=True)
jl    = inbox / f"2026-05-05_iter{ITER}_agentC{AGENT}.jsonl"
ok=err=skip=0; last=None
with jl.open("a", encoding="utf-8") as f:
    for ln in LAWS:
        bp = raw/f"{ln}.json"
        if bp.exists() and bp.stat().st_size > 0:
            skip += 1; continue
        url = f"https://laws.e-gov.go.jp/api/2/law_data/{ln}?law_full_text_format=json"
        try:
            time.sleep(3)
            req = urllib.request.Request(url, headers={"User-Agent":"jpcite-collector-c/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read(); status=r.status
            bp.write_bytes(body)
            d = json.loads(body)
            title = (d.get("law_full_text") or {}).get("law_title") or (d.get("law_info") or {}).get("law_title") or ""
            row = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "source_id":"egov_law_articles","url":url,"http_status":status,
                   "content_hash":"sha256:"+hashlib.sha256(body).hexdigest(),
                   "mime":"application/json","license":"cc_by_4.0",
                   "body_path":f"tools/offline/_inbox/egov_law_articles/raw/{ln}.json",
                   "title":title,"extracted_text":body[:500].decode("utf-8","replace"),
                   "screenshot_path":None,"fetch_method":"agent_pool_dns_c","notes":""}
            f.write(json.dumps(row,ensure_ascii=False)+"\n")
            ok+=1; last=ln
        except Exception:
            err+=1
print(f"[agentC{AGENT}] ok={ok} skip={skip} err={err} last={last}")
```

---

以上。本 prompt を読み終わったら **すぐに self-check → Step 1** を実行する。
報告は 1 行 summary のみ。詳細は `_progress_c.md` に残す。
