# 競合モニタリング / Competitive Watch

> 要約: AutonoMath の Weeks 5-8 (2026-05-06 launch 以降) に向けた、JP 補助金・制度データ領域の競合自動監視設計。
> 目的は「営業のため」ではなく **decisional awareness** — 週次で優先順位を揺さぶる情報が入るようにする。
> Scan 設計: 2026-04-23 / Owner: 梅田茂利 / Last reviewed: 2026-04-23

既存の静的ランドスケープ分析は repo 内 `research/competitive_landscape.md` を参照。本書はそれを毎日自動で差分化するための **運用 playbook**。

---

## 1. 監視対象 (5-10 競合)

| # | 名前 | URL | セグメント | 国 | Watch points | Kill 条件 → 応手 |
|---|------|-----|-----------|----|--------------|----------------|
| 1 | **Jグランツ (デジタル庁)** | https://www.jgrants-portal.go.jp/ / https://developers.digital.go.jp/documents/jgrants/api/ / https://developers.digital.go.jp/news/services/jgrants/ | 公式 API (application layer) | JP | API schema 変更 / v2 公開 / bulk CSV・一括 DL 開放 / 農業 filter 追加 / ライセンス (CC-BY 改悪・排他条項) | **公的 API が exclusion / tier scoring / lineage を組み込んだら** → 我々の moat は "agri-depth + MAFF + JFC + speed of updates" に収束。ドキュメント側で "what jGrants does not do" を明示、MAFF/JFC 拡張を加速。 |
| 2 | **digital-go-jp/jgrants-mcp-server** | https://github.com/digital-go-jp/jgrants-mcp-server | 公式 MCP wrapper (OSS / MIT) | JP | Release / commit 頻度 / tool 追加 (特に `search_by_industry`, `exclusion_*`) / README の用途拡張 | **agri-specific tool を追加してきたら** → 我々の agri-MCP の差は記述的差だけ。記事で "lineage + tier + 排他ルール" の比較表を即日公開。 |
| 3 | **hojokin.ai / 補助金 Express (株式会社2WINS)** | https://www.hojokin.ai/ / https://www.hojokin.ai/terms | SaaS (申請書 AI 作成) | JP | 価格ページ / 機能 / API 公開の有無 / MCP 対応発表 / 対象補助金の数 | **公開 REST API / MCP を出したら** → 申請レイヤーまで垂直統合されると dev 囲い込みが強まる。我々は "API 下流" に特化。comparison 記事 + data-source breadth で差別化。価格 undercut は unit economics を踏み越えない。 |
| 4 | **エネがえる 自治体スマエネ補助金 API (国際航業)** | https://www.enegaeru.com/subsidyinformation-api | 有料 REST API (energy vertical) | JP | 価格改定 (startup ¥300k/mo, standard ¥400k/mo, unlimited ¥750k/mo, initial ¥1.5M) / 対象拡張 (agri / 全業種) / MCP 対応 | **energy→agri に横展開してきたら** → 営業力+700社基盤が脅威。我々の "no 営業電話 / 5min onboarding / 20x 安い" を強調。MCP-native を死守。 |
| 5 | **補助金クラウド (Stayway)** | https://www.hojyokincloud.jp/price/ / https://stayway.co.jp/news/1438/ | SaaS (application workflow) | JP | 価格公開の有無 / API 公開 / 6ヶ月 min 緩和 / 金融機関チャネル拡大 | **API or dev 窓口を開いたら** → 金融機関ディストリビューションと組まれると分厚い。我々は dev-first tone を記事で強化、API ドキュ品質で勝つ。 |
| 6 | **助成金なう (ナビット)** | https://www.navit-j.com/service/joseikin-now/ | SaaS (UI / B2B コンサル) | JP | 価格 / 収録件数 (現 147k+) / AI 診断の API 化 / 農業タグ追加 | **API 公開 or 農業 vertical 追加** → 広域 vs 深掘りの勝負。我々は agri 精度と lineage 監査で引き離す。 |
| 7 | **補助金ポータル / みんなの補助金コンシェルジュ** | https://hojyokin-portal.jp/ / https://hojyokin-concierge.com/ | コンテンツ media / 検索 | JP | SEO キーワード侵食 / "agri 補助金" 特集 / API or MCP の気配 | **SEO で "agri 補助金 API" を刈られたら** → SEO は時間勝負。note/Qiita での技術記事 (MCP + agri) で dev 層を押さえる。 |
| 8 | **freee 補助金** | https://corp.freee.co.jp/news/20230929freee_subsidy.html | SMB 会計バンドル (無料配布) | JP | API / 独立プロダクト化 / 農業会計連携 / ChatGPT plugin | **freee が subsidy API を公開 + free distribution に乗ったら** → 1M SMB 基盤は手強い。我々は "regulated / agri / audit-grade lineage" に vertical 深化。 |
| 9 | **コミュニティ OSS MCP 群 (rtoki / tachibanayu24 / hal-fujita / yamariki-hub 等)** | https://github.com/rtoki/jgrants-mcp-server / https://github.com/tachibanayu24/jgrants-mcp / https://github.com/yamariki-hub/japan-corporate-mcp / https://lobehub.com/mcp/hal-fujita-jgrants-mcp-chatbot | OSS MCP (hobby) | JP | Star 急増 / agri tool 追加 / 商用 fork / LICENSE 変更 (MIT→非 OSS) / PulseMCP ranking 昇位 | **1000★ 超 + 商用 fork が出たら** → dev mindshare を食われる。即 PulseMCP 露出 + 比較記事 + SLA/有料サポートの線で差別化。 |
| 10 | **PulseMCP "Japan" カテゴリ 全体** | https://www.pulsemcp.com/servers | MCP registry | intl | 新規 "subsidy" / "補助金" / "agri" 命名サーバ登場 / ranking 上昇 | **agri-補助金 MCP が先に登録されたら** → 先取り記事 + PulseMCP 内 description 差別化。同期で GitHub topic と keyword を揃える。 |

> **Licensing watch (特記)**: Jグランツ API が「自動化禁止」「排他用途禁止」条項を追加した瞬間、本サービスの agri 排他ルール生成の一部ロジック (排他メタデータの下流配布) が制限されうる。API ドキュ規約条項のテキスト差分を daily で diff。該当語 = `自動`, `一括`, `再配布`, `商用`, `排他`, `スクレイピング`。

---

## 2. 自動監視 cron 設計 — `scripts/competitive_watch.py`

### 2.1 仕様概要
- **実行**: GitHub Actions scheduled (`0 9 * * *` JST 18:00 = `0 9 * * *` UTC) / 手動 `workflow_dispatch`。
- **対象 artefact**: 上表の URL 群 (pricing / changelog / API doc / RSS / GitHub releases)。
- **取得方法**: `httpx` + `User-Agent: AutonoMath-competitive-watch/1.0 (+https://jpcite.com)`、robots.txt 尊重、1 host あたり 1 req/5sec、`If-Modified-Since` + ETag、エラー時 fail-open (他 host は継続)。
- **Diff**: 直近スナップショット (`data/competitive_watch/<slug>/YYYY-MM-DD.html`) と前日版を `difflib.unified_diff`、本文は `readability-lxml` で抽出してノイズ除去。
- **出力**: 差分があれば `research/competitive_log_YYYYMM.md` に追記 (+diff summary + URL + hash)、さらに alert トリガーに該当すれば Slack Incoming Webhook に Post。
- **GitHub monitor**: `GET https://api.github.com/repos/<owner>/<repo>/releases` と `/commits?since=...` を public で叩く (token 任意)。release/ commit があれば Slack + log 追記。
- **RSS**: hojokin.ai / freee / Stayway / digital-go-jp/news の feed を `feedparser` で取得、新エントリを alert。

### 2.2 アラートトリガー
| トリガー | 条件 | Severity |
|---|---|---|
| **価格変更** | pricing URL 内の `¥\d+,?\d*` パターン差分 or `/price`, `/pricing`, `/plan` path の HTML hash 変化 | HIGH |
| **キーワード出現** | 本文に新規出現 `MCP` / `Claude Desktop` / `排他` / `exclusion` / `agri` / `農業` / `tier scoring` / `lineage` / `API` + `v2` / `bulk` / `一括` / `公開` | HIGH |
| **GitHub release** | 対象 repo に新規 release tag または default branch への 10+ 行 commit | MID |
| **商標 watch** | J-PlatPat 簡易検索 scrape で `jpinst` / `jpintel` / `ジェイピーインスト` / `JPI Data` を含む新規出願 | HIGH |
| **ドメイン watch** | `jpinst.ai` / `jpinst.app` / `jpinst.jp` / `jpintel.ai` / `jpintel.app` RDAP/WHOIS クエリで新規登録検出 | HIGH |
| **ライセンス文言** | 上表 Jグランツ / digital-go-jp repo 内の `LICENSE` / `terms` / `利用規約` 本文に `排他` / `自動化` / `再配布` / `商用` の語差分 | HIGH |
| **GitHub fork (我々の repo)** | `AutonoMath/AutonoMath` の fork で LICENSE が変わる or `LICENSE` 内容 hash が異なる fork を検出 | MID |

### 2.3 Non-aggressive scraping
- 全 GET は 5 秒間隔、1 host 1 分最大 3 req。
- robots.txt を `urllib.robotparser` で毎日先に読み、`Disallow` は skip。
- 失敗時は `research/competitive_log_YYYYMM.md` に "FAIL: host=... reason=..." と一行記録し次ホストへ。
- **禁止事項**: 認証突破 / JS 実行を要する pricing 取得 (必要な場合は手動週次レビューで対応) / PDF を 10MB 以上落とす / API key 埋め込みのテスト呼び出し。

### 2.4 スナップショット保存
```
data/competitive_watch/
  jgrants_api_doc/2026-04-23.html
  jgrants_api_doc/hash.txt   # 直近 hash と last_modified を JSON
  hojokin_ai_terms/2026-04-23.html
  ...
research/competitive_log_202604.md
```
Git に commit するのは `research/competitive_log_YYYYMM.md` だけ (HTML snapshot は `data/` = gitignore)。

---

## 3. GitHub Actions workflow — `.github/workflows/competitive-watch.yml`

- `schedule: cron "0 9 * * *"` (UTC 09:00 = JST 18:00)
- `workflow_dispatch: {}`
- Job: `ubuntu-latest`, timeout 20min, concurrency `competitive-watch` (cancel-in-progress: false)
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` (python 3.12)
  3. `pip install httpx readability-lxml feedparser`
  4. Restore snapshot cache (`actions/cache` keyed by `competitive-watch-snapshots-v1`)
  5. `python scripts/competitive_watch.py --out research/competitive_log_$(date -u +%Y%m).md`
  6. Slack 通知 (`SLACK_WEBHOOK_COMPETITIVE` secret) — diff ありの場合のみ
  7. 差分があれば `peter-evans/create-pull-request@v6` で `research/competitive_log_*.md` だけを PR 化 (auto-merge しない、梅田レビュー前提、label `competitive-watch`)
  8. 失敗は `::warning::` で吸収し exit 0 (毎日の継続を優先)

**secrets 必要**: `SLACK_WEBHOOK_COMPETITIVE` (optional, 無ければ PR のみ), `GH_PAT_WATCH` (optional, rate limit 用)。どちらも無くても workflow 自体は動く (fail-open)。

---

## 4. 手動 週次レビュー — 毎週 金曜 30min

- **時刻**: 毎金 17:00-17:30 JST
- **場所**: `research/competitive_log_YYYYMM.md` を上から当週分だけ読む
- **出力**: `research/competitive_log_YYYYMM.md` 末尾に `## Weekly review YYYY-MM-DD` セクションを追加し以下を 5 行で書く:
  1. 今週最も優先順位を揺らす差分は何か (1 行)
  2. 次週 dev 優先順位にどう反映するか (1-2 行)
  3. 既存 `docs/competitive_watch.md` の kill 条件を発動するか (yes/no + 理由)
  4. 商標・ドメイン watch にアクションがあるか (弁理士に即相談レベルか)
  5. "見送り" で OK のものを明記 (過剰反応を防ぐ)
- **原則**: 1 週間の差分に対する応手は **最大 1 つ**。全部拾いにいかない。

---

## 5. 攻め手 (ethical / 模倣しない)

| Trigger | 応手 |
|---|---|
| 競合が MCP 対応を発表 | **我々は既に MCP-native (day 1)** の事実を note / Qiita / X 投稿。機能比較表を公開 (relative / データ優位 のみ、競合の code は触らない)。 |
| 競合が我々より低価格 | unit economics を割らない範囲で我々を調整。または "包括 (all-vertical)" tier を上に追加して価格比較軸をずらす。**絶対にコスト割れ undercut はしない**。 |
| 競合が新データソース (例: 都道府県単独 portal) を取込 | 公開情報であれば我々も取込評価。独自スクレイピング契約なら手を出さない。lineage 上 "同ソース" になるだけで、我々の agri 深さは変わらない点を記事で示す。 |
| 公式 API v2 / bulk CSV 公開 | 即 ingest、"ms-level freshness" と "MAFF/JFC merged" を差別化軸に切り替え。kill 条件発動なら documentation の angle を "free 層は jGrants 公式で十分 / 有料は agri 拡張" に明示書き換え。 |

---

## 6. 守り手

### 6.1 商標 watch
- 対象ワード: `jpinst`, `jpintel`, `ジェイピーインスト`, `ジェイピーインテル`, `JPI Data`, `JPIデータ`, `JGI`, `jp-inst`, `jp inst`
- ソース: [J-PlatPat 簡易検索](https://www.j-platpat.inpit.go.jp/) (URL パラメタで検索 POST、日次 cron)
- 検出時: Slack HIGH + 弁理士即連絡 (相談先は repo 内 `research/trademark_jp.md` のリストを参照)
- 新規出願類似が出たら、**異議申立期間 (登録公報発行日から 2 ヶ月以内)** を `competitive_log` にデッドライン記載

### 6.2 ドメイン watch
- 対象: `jpinst.ai`, `jpinst.app`, `jpinst.jp`, `jpinst.dev`, `jpinst.io`, `jpinst.co`, `jpintel.ai`, `jpintel.app`, `jpintel.jp`, `jpintel.io`
- 方法: RDAP (`https://rdap.verisign.com/com/v1/domain/<name>`) + `.jp` は JPRS WHOIS、日次
- 空き→取得検出: Slack HIGH + 梅田判断で防衛取得 (¥2k/年程度、launch 前に予防取得推奨)
- すでに取得済みのものは redirect 設定までを repo 内 `research/domain_shortlist.md` に追記

### 6.3 GitHub fork watch
- 対象: `github.com/shigetosidumeda-cyber/jpintel-mcp` の全 fork
- チェック: `GET /repos/.../forks` で各 fork の `LICENSE` raw を取得、hash 比較
- 異 hash 検出: Slack HIGH。MIT→proprietary 変更 / 著作権表記削除はライセンス違反の可能性 → OSSコミュニティに周知 or 削除要請 (GitHub DMCA 可だが濫用しない)

---

## 7. Non-goals (明記)

以下は **明確にやらない**。逸脱リスクの事前コミット。

1. **競合 code の reverse engineering** — GitHub public repo の clone 読みは OK、非公開バイナリや API 経由の挙動抽出はしない。
2. **偽レビュー / review bombing** — Product Hunt / G2 / Qiita / note で competitor に低評価投稿しない。自社 post も "honest review, no bots"。
3. **unit economics 割れの値下げ** — 我々のインフラ+データ整備原価を下回る価格は出さない。competitor pricing に反応して割り込むのは「負け」扱い。
4. **全顧客 / 全 deal を取りに行く営業** — 自動監視は「知るため」であって「潰すため」ではない。agri / MCP-native / lineage-tracked という我々のコア顧客以外の deal は追わない。
5. **Competitor サイトへの過剰スクレイピング** — robots.txt 違反 / レート超過 / 認証突破 / API 規約違反は即停止。監視は "公開情報の差分取り" の範囲に限る。
6. **FUD マーケティング** — 競合製品を誤解させるような比較記事を書かない。比較は事実 + 公開情報 + date-stamped にする。

---

## 8. 想定スケジュール

| Week | 作業 |
|------|------|
| W5 (5/6-5/12) | `scripts/competitive_watch.py` v1 実装 / `.github/workflows/competitive-watch.yml` 投入 / snapshot baseline 取得 |
| W6 (5/13-5/19) | Slack alert + PR 自動生成を有効化 / 金曜 review routine 1 回目 |
| W7 (5/20-5/26) | J-PlatPat / RDAP / GitHub fork watch を追加 / 誤検知 tuning |
| W8 (5/27-6/2) | 1 ヶ月分の `competitive_log_202605.md` を振り返り、kill 条件 / severity を見直し本 `competitive_watch.md` を更新 |

---

## 9. Sources / 参考

- 研究編 (静的ランドスケープ) — repo 内 `research/competitive_landscape.md`
- 商標 JP メモ — repo 内 `research/trademark_jp.md`
- ドメイン shortlist — repo 内 `research/domain_shortlist.md`
- [Jグランツ 開発者サイト ニュース](https://developers.digital.go.jp/news/services/jgrants/)
- [Jグランツ API doc](https://developers.digital.go.jp/documents/jgrants/api/)
- [PulseMCP servers](https://www.pulsemcp.com/servers)

---

*最終更新: 2026-04-23 梅田茂利. Weeks 5-8 完了時に自己レビューし、kill 条件と severity ラベルを再調整すること (feedback_agent_severity_labels.md 準拠 — severity を鵜呑みにせず検証)。*
