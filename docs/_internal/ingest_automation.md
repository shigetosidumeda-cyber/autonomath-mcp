# Ingest 自動化 (Tiered Cadence)

**位置づけ:** 社内運用プランの正本。エンドユーザー向け機能ではない。
`data/registry.sqlite` / `data/jpintel.db` は現在手動で投入しているため、
各省庁の公表更新に追随できず stale になるリスクがある。6,771 件 × 814
ホストを毎日 全件同期するのは無駄なので、更新頻度で 3 + 1 段の tier に
分割する。

本書で定義する tier / cron / 失敗ハンドリング / rollback は、
`.github/workflows/ingest-daily.yml` 他 3 本と `scripts/ingest_tier.py`
の唯一の契約。変更は必ず本書を先に改訂する。

---

## §1 Authority 分類

`data/jpintel.db` 2026-04-23 時点の `authority_name` / `authority_level`
分布と、各 source netloc (`urlparse(source_url).netloc`) の観測ボリューム
を根拠に割り当てる。観測データの無い authority は「要 実運用 確認」と
明記し、3 ヶ月後に再配分する。

### Tier 1 — Daily (最も動く、~200 件)

- **Jグランツ (`www.jgrants-portal.go.jp` / `api.jgrants-portal.go.jp`)**
  — 公募差替え頻度が最も高く、締切当日まで入換がある。24 件直接紐付け
  + 中小企業庁系経由で数百件が流入。
- **中小企業庁 (`www.chusho.meti.go.jp`, 36 件)** — 補正予算・公募一括
  公表日に合わせた入換。
- **経済産業省メインページの公募情報 (`www.meti.go.jp` 公募枠のみ)** —
  要 実運用 確認。rss が無いのでトップ「新着情報」を poll する。
- **大型補助金ラウンド (事業再構築・ものづくり・IT 導入・省力化)** —
  事務局サイト (個別 netloc) が個別に公募開始日を打つ。
- **観測根拠:** 上記 netloc の登録件数 = ~200。Jグランツ API は仕様上
  毎日差分が立つ (締切表示・状態遷移)。

### Tier 2 — Weekly (~1,500 件)

- **農林水産省 (`www.maff.go.jp`, 803 件)**
- **厚生労働省 (`www.mhlw.go.jp`, 77 件)** — 助成金の要項改訂は月次だが
  申請期間・Q&A 追補が週次。
- **日本政策金融公庫 (`www.jfc.go.jp`, 89 件, `authority_level=financial`)**
- **国税庁 / 特許庁 / 中小機構 / 信用保証協会 など制度公表主体**
  (合計 ~40 件) — 告示改訂は年次〜四半期だが、週次で十分追いつく。
- **noukaweb 収集分 (1,176 件, `authority_name=''` 含む)** — 一次資料の
  tier が決まるまでの暫定。canonical 済の netloc に置換していく。
- **合計 ~1,500 件相当 (1 次資料ベース + noukaweb 暫定)。**

### Tier 3 — Monthly (~4,500 件)

- **47 都道府県 (`www.pref.*.lg.jp` / `*.pref.*.jp`)** — 1,085 件 /
  `authority_level=prefecture`。県の予算執行は年度単位、補正は月次。
- **市区町村サンプル (`www.city.*.lg.jp` / `www.town.*.lg.jp`)** —
  3,333 件 / `authority_level=municipality`。全件は重いので **抽出率 25 %
  を月次、残りを四半期で回す** (Tier 3 内サブローテーション、§6 参照)。
- **`www1.g-reiki.net` (例規データベース, 69 件)** — 条例更新は月次で十分。
- **合計 ~4,500 件相当。**

### Tier 4 — On-demand

- `workflow_dispatch` (GHA 手動) で任意 tier / 任意 authority を再実行。
- 将来: `/v1/admin/ingest` (認証は `ADMIN_API_KEY`、§4 参照)。
  「XX 省が令和 N 年度 公募要領を公表」みたいな個別トリガーに使う。
- 事業年度 4 月 1 日 / 10 月 1 日前後の繁忙期は cron を止めずに
  on-demand を足す運用。

### tier 数サマリ

| tier | authority netloc 概数 | program 概数 | 変更見込 |
|------|----------------------|-------------|----------|
| daily   | ~6   | ~200   | <10/day   |
| weekly  | ~15  | ~1,500 | ~30/week  |
| monthly | ~500 | ~4,500 | ~100/mo   |
| on-demand | n/a | ad-hoc | n/a      |

daily / weekly / monthly の振り分けは `scripts/ingest_tier.py` 内の
`AUTHORITY_TIERS` 定数で宣言する (§7)。

---

## §2 Scheduling (cron, UTC 表記)

既存 cron と衝突させない:

- `nightly-backup.yml` = `17 18 * * *` UTC (03:17 JST)
- `competitive-watch.yml` = `0 9 * * *` UTC (18:00 JST)
- `tls-check.yml` = 月次別枠
- pricing window は「平日 09–20 JST (00–11 UTC)」に請求系の webhook 反映が
  集中。ingest は **JST 04–06 台** の低負荷帯に固定する。

| workflow               | cron (UTC)       | JST 換算         | 目的 |
|------------------------|------------------|------------------|------|
| ingest-daily.yml       | `0 19 * * *`     | 04:00 JST 毎日   | Jグランツ等 |
| ingest-weekly.yml      | `0 20 * * 0`     | 05:00 JST 日曜   | MAFF/JFC 等 |
| ingest-monthly.yml     | `0 21 1 * *`     | 06:00 JST 月初   | 都道府県・市町村 |

- backup (03:17 JST) → daily ingest (04:00 JST) → weekly/monthly が必要日に
  積み上がる。**backup が先に終わっている前提で ingest が走る** (backup の
  世代が pre-ingest snapshot になるので rollback の基点として正しい)。
- `concurrency.group = ingest-<tier>` で **重複起動を禁止**。前の run が
  残っていたら `cancel-in-progress: false` で新規起動を待たせる
  (cancel すると途中の authority が中途半端にコミットされる)。

---

## §3 Idempotency + Lineage

migration 001 で `programs.source_url`, `source_fetched_at`,
`source_checksum` を追加済 (`scripts/migrations/001_lineage.sql`)。
`src/jpintel_mcp/ingest/canonical.py::_compute_source_checksum` が正。

短絡ロジック (authority 単位で全適用):

```
for program in fetched:
    new_checksum = sha256(canonical_payload)[:16]
    prior = programs[unified_id]
    if prior and prior.source_checksum == new_checksum:
        # skip: no UPDATE, no FTS rebuild
        rows_unchanged += 1
        continue
    UPDATE programs SET ..., source_fetched_at=NOW(), source_checksum=new
    DELETE FROM programs_fts WHERE unified_id=?
    INSERT INTO programs_fts ...
    rows_updated += 1
```

- `source_fetched_at` は **中身が変わった日時** だけ進める (初観測日を保持)。
  既存 `_ingest_programs()` の挙動と一致。
- `programs_fts` は checksum が一致したら触らない。FTS rebuild は I/O 的に
  一番重いので short-circuit の効果が最大。
- `source_url` が null の row は ingest 対象外 (noukaweb 由来の暫定 row 等)。
  canonical へ昇格した時点で tier 先を判定して編入。
- 1 run 内で同じ `unified_id` が 2 つの authority から来た場合、後勝ちで
  はなく **tier 優先順 (daily > weekly > monthly)** で採用。tier 判定は
  `scripts/ingest_tier.py::OWNER_TIER` に登録。

---

## §4 Failure Modes

ingest は **authority 単位で独立**。1 省庁の 404 / 500 / layout 変更で
ジョブ全体を落とさない。

| 失敗種別                | 挙動                                                | 次回 cron        |
|------------------------|-----------------------------------------------------|------------------|
| ホスト 404 / DNS 失敗  | 当該 authority のみ fail 記録、行は触らない         | 次回再挑戦        |
| 429 / 503 rate limit   | backoff (§5) 後 1 回再試行。だめなら skip           | 次回再挑戦        |
| HTML layout 変更で parser 0 件 | **行を消さない**。`rows_added=0` かつ直前 run が >0 なら異常としてマーク | 手動点検         |
| checksum は変わるが欠損 (key 消失) | fetched payload が `primary_name` null → reject | 手動点検         |
| DB lock (backup と競合) | 30s × 3 retry。それでも取れなければ job fail       | cron に任せる     |

**決して ingest 失敗で既存 row を DELETE しない** (stale のほうがマシ)。
`_ingest_programs` は `DELETE FROM programs` を先に撃つので、**tier 実装では
まず staging テーブルに書き、最後に MERGE する**設計にする (§7 TODO)。

**アラート:**
- 同一 authority が **3 連続 daily run で失敗 or 0 件化** →
  Slack webhook (`SLACK_WEBHOOK_INGEST`、未設定なら GitHub Issue のみ)。
- Issue label = `ingest-failure` を付けて `docs/incident_runbook.md` に
  runbook stub を追加予定。
- `/v1/admin/ingest/status` で「authority × 最終成功時刻」を返す endpoint を
  後続タスクで実装 (preview endpoint 枠)。

---

## §5 Robots / Rate-Limiting

- 全ジョブが **robots.txt を事前 GET** し `urllib.robotparser` で allow 判定。
  一致禁止なら skip + `skip_reason=robots`。
- **1 req/sec/host**、連続 60 req で 15s 追加クールダウン。gov 系で
  robots.txt が無いホストも同レートを適用。
- User-Agent = `jpintel-mcp-ingest/1.0 (+https://autonomath.ai; contact=ops@autonomath.ai)`
  (rebrand 未確定。§constraints)。
- PDF は 10 MB 上限、HTML も 2 MB で打ち切って "not-a-page" 扱い。
- 共通ユーティリティは `scripts/lib/http.py`。
  `competitive_watch.py` と後続 `ingest_tier.py` で共有する。
  既に `competitive_watch.py` 内で同等ロジックがあるので、lib 化で
  二重実装を解消するのを **本タスク内で着手 (skeleton のみ)**。

---

## §6 GHA Workflow 実装

3 本とも同型。

共通手順:
1. `actions/setup-python@v5` + `astral-sh/setup-uv@v3` で依存解決 (lockfile 利用)
2. `SENTRY_RELEASE=${{ github.sha }}` を export (ingest 起因エラーを commit に紐づけ)
3. `superfly/flyctl-actions/setup-flyctl@master` + `flyctl ssh console`
   で **Fly マシン上で** `python scripts/ingest_tier.py <tier>` を実行。
   CI の checkout で DB を書くと volume と乖離するため、**必ず prod 機上書き**。
4. 成功時: `data/ingest_log.jsonl` (append-only 運用ログ) の diff だけを
   `peter-evans/create-pull-request` で PR 化。`*.db` / `*.sqlite*` は
   `.gitignore` 済なので誤コミットされない。
5. 失敗時: `gh issue create --label ingest-failure` で Issue 起票。
6. `timeout-minutes` — daily=45, weekly=90, monthly=240 (4h 上限を monthly に寄せる)。
7. `concurrency.group` で tier ごとに直列化。

monthly の都道府県 + 市町村サブローテーションは `python scripts/ingest_tier.py monthly
--month-slot {{ run_number % 4 }}` で 25 % ずつ回す。`run_number` は GitHub
側の連番なので **毎月同じ slot** に当たる点は許容 (季節性は別 on-demand でカバー)。

secrets:
- 既存 `FLY_API_TOKEN` のみ必須。
- `SLACK_WEBHOOK_INGEST` は optional (未設定なら Issue のみ)。**新規 secret は追加しない**
  で済む構成にした。

---

## §7 `scripts/ingest_tier.py` スケルトン

- 入口: `python scripts/ingest_tier.py {daily|weekly|monthly} [--authority NAME] [--dry-run]`
- 責務: tier → authority 列 → `fetcher(authority)` → staging へ upsert
  → `canonical.py` の `_compute_source_checksum` で比較 → 差分適用
  → `emit_metrics()` で §8 ログ 1 行吐く。
- 既存の `src/jpintel_mcp/ingest/canonical.py` は **`data/unified_registry.json`
  を読んで DB 全削除→全投入**する全件 ingest。tier 実装ではこれを呼ばず、
  authority 単位の差分 upsert を自前で持つ (signature は §7 TODO に明記)。
- 共用する関数:
  - `_compute_source_checksum(enriched, entry)` — 既存を import
  - `_extract_source_url(enriched, entry)` — 既存を import
  - `_flatten_enriched_text(enriched)` — FTS 用、既存を import
- 新設 (TODO、function 署名のみ先出し):
  - `fetch_authority(name: str, *, http: HttpClient) -> Iterator[ProgramRow]`
    — 省庁別 fetcher。daily=jgrants API, weekly=MAFF/JFC HTML, monthly=pref/city。
  - `upsert_program(conn, row: ProgramRow, *, now: str) -> UpsertResult`
    — checksum 比較し added/updated/unchanged を返す。
  - `write_ingest_log(path: Path, metrics: IngestMetrics) -> None`
    — `data/ingest_log.jsonl` に 1 行追記。

この PR では skeleton (呼び出しグラフ + CLI + stub fetcher) のみ入れ、
実 fetcher は各 authority の owner チケットで段階的に埋める (TODO comment)。

---

## §8 Observability

run ごとに 1 行、構造化ログで:

```json
{"event":"ingest_done","tier":"daily","authorities_ok":12,
 "authorities_fail":0,"rows_added":5,"rows_updated":21,
 "rows_unchanged":174,"duration_s":347,"sha":"abc1234"}
```

- structlog は `src/jpintel_mcp/api/logging_config.py::get_logger()` を
  そのまま再利用 (JSON renderer)。
- `rows_unchanged` まで出すことで short-circuit が効いている証跡になる。
- Fly stdout → Sentry breadcrumbs → observability dashboard agent が後日吸い上げ。
- 同じペイロードを `data/ingest_log.jsonl` にも 1 行 append (PR に載る
  唯一の diff)。タイムシリーズを git で後追いできる。

---

## §9 Rollback

**約束:** ingest 起因の破損は 15 分以内に最後の good snapshot まで戻せる。

- `nightly-backup.yml` が 03:17 JST に `/data/backups/jpintel-YYYYMMDD-HHMMSS.db.gz`
  を生成し R2 に 14 世代まで mirror。**ingest cron (daily=04:00 JST) の直前に
  常に good snapshot がある**。
- 手順 (`docs/incident_runbook.md` に追記予定):
  ```bash
  # 1) 最新 good snapshot を特定
  aws s3 ls s3://$R2_BUCKET/jpintel-mcp/ --endpoint-url $R2_ENDPOINT | sort | tail -5

  # 2) 当該 .db.gz を Fly machine に流し込み
  flyctl ssh console -a jpintel-mcp -C "python /app/scripts/restore.py --from /data/backups/jpintel-YYYYMMDD-HHMMSS.db.gz"

  # 3) smoke
  BASE_URL=https://jpintel-mcp.fly.dev ./scripts/smoke_test.sh
  ```
- 月次 monthly ingest は「直前の daily backup から直近 weekly/monthly の
  差分だけ巻き戻せる」ように `data/ingest_log.jsonl` の行に `started_at` /
  `completed_at` / `authorities=[...]` を記録しておく。
- on-demand で「authority X 単位のみ revert」が欲しいケースは当面 out-of-scope
  (staging table を経由するようになった後で追加実装)。

---

## 制約 (本書の編集時に必ず読む)

- `data/jpintel.db` / `data/registry.sqlite` を手元で直接触らない。
- `src/jpintel_mcp/ingest/canonical.py` や `scripts/ingest/*.py` は改変しない。
  新しい wrapper (`scripts/ingest_tier.py`) 側で包む。
- rebrand (Intel 商標衝突、参照: `project_jpintel_trademark_intel_risk`) が
  fix するまで domain 固定記載は避ける。
- この仕組みは **社内運用のみ**。エンドユーザーに「自動更新中です」と
  advertise しない (SLA 化した瞬間に pager 案件が増える)。
