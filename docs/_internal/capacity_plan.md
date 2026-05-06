# Capacity plan — jpcite on Fly.io

_Baseline: 2026-04-23 ／ Launch target: 2026-05-06 (nrt single shared-cpu-1x)_

本文書は launch 時点 (HN / Zenn / Product Hunt 同時掲載) を想定した
容量計画である。数値は benchmark で裏付けたものと "unverified estimate"
を明示的に区別する。裏付けは
`research/perf_baseline.md` と
`loadtest/` の k6 結果 (repo-internal; 公開対象外)。

## TL;DR

- 単機 shared-cpu-1x + uvicorn 1 worker の read 天井は **約 37 req/s**
  (実測、`perf_baseline.md`)。
- SQLite FTS5 は **少なくとも 1100 req/s** 捌ける (CPU cost 0.9ms/req、
  実測 `perf_baseline.md`)。律速は uvicorn + GIL であって SQLite では無い。
- Launch 同時刻に >10 rps が 5 分以上続き p95>500ms なら
  `shared-cpu-2x` + `--workers 2` へ上げる。手順は § Scale-up playbook。
- バンド幅は free tier (100GB/月) で launch 月は余裕。
  `fields=full` を有料枠に閉じ込めている前提が崩れない限り、
  CDN を前段に置く閾値には当面届かない。

---

## 1. Fly shared-cpu-1x baseline

`fly.toml` 現状:

```toml
[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
```

| Quota | Value | Source |
|---|---|---|
| vCPU (burst) | 1 shared / 16 cores pool | Fly.io docs |
| CPU 持続レート | ~6% of 1 core = **60ms CPU / 1s wall** | Fly.io "shared-cpu-1x" policy |
| RAM | 512 MB | fly.toml |
| Disk | 1 GB volume (mount `/data`) | fly.toml `jpintel_data` |
| Egress bandwidth | 100 GB / 月 無料、超過 $0.02/GB | Fly.io pricing |
| Ingress | 無料 | 同上 |
| Concurrency soft limit | 50 requests / hard 100 | fly.toml `http_service.concurrency` |

CPU 持続レート の 60ms/s = **16.6 req/s 相当**
(1 req が 60ms の CPU 時間を使うと仮定)。
実測 37 req/s が出ているのは、1 req の CPU 時間が実質 15-20ms であること、
および shared-cpu のバースト余裕が常時 100% 取れている時間帯が launch
月で多いことを示している (unverified estimate: 土日昼間はさらに余裕が
減る可能性あり)。

## 2. SQLite ceiling on this hardware

`perf_baseline.md` 実測:

| 指標 | 数値 | 備考 |
|---|---|---|
| bare-metal (ASGI スタック抜き) のクエリ 1 本 | 0.9 ms | FTS5 MATCH + COUNT + SELECT + 20 行 `_row_to_program` |
| 計算上の上限 | ~1,100 req/s / core | 0.9 ms/req ベース |
| 実測 end-to-end (uvicorn 1 worker, 10 concurrent) | **37 req/s** | FastAPI + Pydantic + anyio threadpool dispatch が律速 |
| p50 / p95 / p99 @ 10 workers | 270 / 327 / 384 ms | 同上、load-under-10-workers |

**結論**: SQLite は律速ではない。uvicorn の sync-route dispatch (GIL + threadpool)
が天井を作っている。スケールの第一手は uvicorn worker を増やすこと。

FTS5 専用の備考:
- `programs_fts` 仮想テーブルは 6,445 ドキュメント (excluded=0 の行)
  をカバー。MATCH クエリの cost は O(log N) なので、現サイズでは
  全件 LIKE の 10 倍以上速い (実測: `q=農業` FTS 30ms、
  `q=IT` (2 文字、LIKE fallback) 25ms — 短すぎて FTS に入らないケースは
  LIKE のほうが "運良く" 速い場合がある)。
- `len(q) < 3` で LIKE fallback に落ちる設計 (`programs.py:228`) は
  20,000 行を超えたあたりで律速になる。閾値を 2 に下げる or
  trigram インデックスを張るかは 10k 行超えてから再評価。unverified
  estimate: 6k → 20k の道のりは早くて 2026-H2。

## 3. Scale-up triggers

以下の**どれか 1 つ**が 5 分以上続いたら、Scale-up playbook (§4) を
実行する。Fly dashboard / Sentry / `/v1/admin/health` のアラート経由。

| Trigger | 閾値 | 意味 |
|---|---|---|
| 持続 RPS | > 10 req/s (1 分移動平均) | 単機 uvicorn の余裕代 1/3 を食った |
| p95 latency | > 500 ms | anyio threadpool が詰まり始め |
| 5xx rate | > 0.5 % (5 分窓) | sqlite busy-timeout or unhandled exception |
| Memory | > 400 MB (80% of 512) | row cache + Python heap の合算、OOM まで 20% |
| CPU throttle events | Fly metric `vcpu_stolen_pct` > 20% | shared pool で隣人にやられている |
| Egress | > 2 GB / 日 | 月 100GB の半分を 15 日で使うペース |

**10 rps は計測値 37rps の 27% に過ぎない**ことに注意。残り 73% は
spike 吸収しろ (favicon / health-check / 調査 curl / JSON-LD crawler) を
想定している。その前提が崩れると launch 当日アウト。

## 4. Scale-up playbook

### 4.1 shared-cpu-1x → shared-cpu-2x (+ workers)

コスト差 **¥855/月 → ¥1,710/月** (unverified: 為替 150 ¥/$ 固定計算)。
手数: **10 分**。

```bash
# 1. VM class 変更
fly scale vm shared-cpu-2x -a autonomath-api

# 2. uvicorn worker 数を 2 へ
# Dockerfile or start command 側で --workers 2 にする
# (WAL mode なので複数 reader プロセス OK、write は 1 本固定)

# 3. concurrency 上限も引き上げ
# fly.toml:
#   soft_limit = 100  # 50 -> 100
#   hard_limit = 200  # 100 -> 200
```

期待効果: 実測 37 rps → **~70 rps** (worker 数 × シングル値、
unverified: GIL の割り当て次第で 80-90% 効率)。

### 4.2 shared-cpu-2x → shared-cpu-4x or performance-2x

「同時 100 req/s を 1 時間以上」のフェーズに入ったら。
コスト差 **¥1,710 → ¥3,420 (shared-4x)** or **¥1,710 → ¥4,500 (performance-2x)**。

performance クラスは vCPU が dedicated になるので throttle が消える。
latency 分散が安定するのはこちらで、しかし絶対 throughput は
shared-4x (cores=4) のほうが高い (unverified estimate)。選択は
「tail latency がキャップ」なら performance、「throughput がキャップ」なら shared。

### 4.3 dedicated (performance-4x / 8x)

同時 200 rps を継続する場合。月 ¥9k+。この段階に届くならユーザー規模
が ARR ¥500万 + なので、¥9k は誤差。

### 4.4 LiteFS for multi-writer / multi-region

**launch 時点では不要**。以下が揃ったら検討:
- 東京 nrt 以外の region (シンガポール / SFO) にユーザー母集団がいる
- write QPS が >5 (ingest が API 経由になった時)
- 単機の RPO (recovery point objective) が許容できなくなった

LiteFS 導入はアプリ層改修が要る (write を primary に forward する
connection routing)。2026-H2 以降の宿題。nightly backup
(`scripts/backup.py`) で RPO 24h 相当は既に確保されているので、
launch 月は発動しない。

## 5. Bandwidth implications of pagination / response-size

現行仕様 (`programs.py:210` 周辺):

- `limit` は 1..100 で hard cap 済み (Query 引数 `le=100`)。
- `offset` は上限なし。ただし total 6,445 件しか無いので
  `offset>6445` は空配列を返すだけでコストは O(limit)。
- `fields=default` 応答サイズ: **~8 KB / 20 rows** (実測)。
- `fields=full` 応答サイズ: **~60 KB / 20 rows** (unverified estimate:
  `enriched_json` + `source_mentions_json` が行ごとに 2-3 KB 乗る前提)。

### 5.1 "fields=full をどう制限するか" の位置付け

`/v1/programs/search?fields=full&limit=100` が 1 回で 300 KB。
100 req/s で回すと **30 MB/s = 2.6 TB/日**。free 100 GB/月 は半日で枯れる。
そのまま 1 ヶ月 = **¥78,000 (egress only)**。shared-cpu-2x の月額の
45 倍。

現状 `fields=full` は tier 制限が**かかっていない**。launch 前に:

- [ ] `fields=full` を `tier == paid` に限定
  (`require_key` 内で判定、free は 400 or auto-downgrade)、OR
- [ ] `fields=full & limit>20` を 400、OR
- [ ] response-size middleware で byte cap (例: 256 KB) をかけ超過は
  `warning` header 付きで切り捨て。

このいずれかが launch blocker。ペイロード最適化 (Task context で言及)
の落としどころもここ。

### 5.2 pagination 挙動の副作用

`COUNT(*)` が毎回全件スキャンなのは baseline で既に flagged。ただし
6,445 行程度の FTS MATCH COUNT は 0.3ms 程度で律速ではない
(unverified: 100k 行超えで再計測必要)。

## 6. Cost curve

¥150/$ 換算 (2026-04-23 時点為替)。

| 段階 | 構成 | 月額 (machine) | 月額 (egress @ 100GB 以下) | 月額 (egress @ 1TB) | RPS 耐性 |
|---|---|---:|---:|---:|---:|
| 0. Launch | shared-cpu-1x ×1, 512MB | ¥855 | ¥0 | ¥2,700 | ~37 rps |
| 1. Workers up | shared-cpu-2x ×1, `--workers 2` | ¥1,710 | ¥0 | ¥2,700 | ~70 rps |
| 2. Dedicated | performance-2x ×1 | ¥4,500 | ¥0 | ¥2,700 | ~150 rps (unverified) |
| 3. HA | shared-cpu-2x ×2 (nrt + nrt) behind proxy | ¥3,420 | ¥0 | ¥2,700 | ~140 rps |
| 4. CDN edge | 2x + CloudFlare Free tier | ¥3,420 | ¥0 | ¥0 (CF 吸収) | 実質無限 (cache hit 分) |
| 5. Multi-region | LiteFS primary=nrt + replica=iad | ¥6,840+ | ¥? | ¥? | region-local |

### CloudFront / CF を前段に置く境目

判断基準は **egress bandwidth cost > CDN 料金 の交点**。

- Fly egress: $0.02/GB = ¥3/GB
- CloudFlare Free: **無制限**、ただし enterprise SLA 無し
- CloudFront: $0.12/GB (アジア) = ¥18/GB 超、つまり**使うと高くなる**
- Fastly / Cloudflare Pro: 月 $20 = ¥3,000 固定 + 超過

**結論**: コスト最適は **Cloudflare Free** を挟むこと。判断境目は egress
ではなく「rate-limit 耐性が欲しくなった時」。HN/PH launch で scraper
が来るなら CF の bot fight mode が欲しい、という使い所。

bandwidth 境目だけで言えば、egress が **¥3,000/月** (1 TB/月) を超えた
時点で Cloudflare Pro のほうが安い。Fly free tier 100GB で収まるうちは
Fly 直出しのほうが simple。

## 7. 未検証項目 (launch 前に確認したい)

以下は現時点で unverified estimate。k6 run で数値化すべき:

1. **staging での実 rps ceiling** — Fly の shared-cpu-1x 実機で
   37 rps が出るか。laptop 計測なのでズレあり。
2. **memory pressure under load** — 512MB 中 row cache + LRU + Pydantic
   heap の合計。k6 50 VU で `/proc/self/status` を Sentry に送らせて確認。
3. **WAL file growth** — write は無いが、ingest cron (`scripts/ingest_tier.py`)
   実行中に `programs_fts` の trigger が動く。checkpoint が追いつかないと
   `-wal` が膨張して disk full になる。volume 1GB に対する watermark 監視が必要。
4. **anon_rate_limit が load 下で fail-open し過ぎていないか** —
   busy DB の時 `DB error on increment; failing open` パスに落ちるので、
   rate-limit が抜け穴になる可能性。k6 中にログを grep して confirm。
5. **fly proxy の 502 閾値** — uvicorn 側の response が 30s 以上かかると
   Fly proxy が 502 を返す。現状そんな遅いパスは無いが、sqlite lock で
   詰まった時に観測したい。

## 8. Operational notes for launch day

- `fly logs -a autonomath-api --since 5m | grep -E "500|timeout|busy"` を
  常駐ウィンドウに。
- Fly metrics dashboard で `vcpu_stolen_pct` と `fly_app_concurrency`
  を 1 分粒度で監視。
- k6 `loadtest/programs_search.js` を事前 (launch D-1) に staging で
  1 回流し、数値を `research/perf_baseline.md` に追記。
- Scale-up playbook (§4) は D-Day 中に人力で判断 & 実行。自動 scaling は
  有効にしない (秒単位の誤判定で ¥ 吹っ飛ばすより、ミス許容な手動のが安い)。

---

## 付録 A: RPS の定性分類

| シナリオ | 期待 RPS (unverified) | 当機 (1-worker) で捌けるか |
|---|---:|---|
| 定常 (SEO botのみ) | 0.1-0.5 | 余裕 |
| Zenn 記事掲載 + Twitter | 2-5 burst 30 分 | 余裕 |
| HN front page | 10-30 sustained 2h | **ギリ** — 要 monitoring |
| Product Hunt #1 | 30-80 sustained 1 day | **越える** — Scale-up trigger 発動 |
| 複数同時 hit | 80-200 burst 数分 | §4.2 まで先回りで上げる |

Launch 初日は Zenn + HN 中心と見積もっている (Product Hunt は日本
向けには wave が薄い)。shared-cpu-1x + `min_machines_running=1` のままで
**8 割の確率で生き残る**(unverified estimate)。残り 2 割は §4.1 に
10 分で上げる準備だけしておく。
