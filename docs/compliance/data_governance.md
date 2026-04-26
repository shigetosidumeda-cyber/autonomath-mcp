# Data Governance Policy

**対象**: AutonoMath DB (unified_registry および関連 canonical テーブル)
**事業者**: Bookyou株式会社 (T8010001213708)
**最終改訂日**: 2026-04-24
**施行日**: 2026-04-24

---

## 1. 目的

AutonoMath は、お客様が「受給可能な制度の一次資料に到達する」ための導線を提供します。その価値の源泉は**データ品質の信頼性**にあります。本 policy は以下を目的とします:

1. 誤情報混入の防止 (詐欺リスク回避)
2. 一次資料への canonical link の維持
3. 撤回制度の適切な取り扱い
4. 誤情報発見時の修正 path の明確化

---

## 2. データソース基準 (一次資料必須)

### 2.1 許可ソース (canonical source)

DB に ingest してよいのは、以下のドメインで公開されている公式資料のみ:

| カテゴリ | ドメイン基準 | 例 |
|---|---|---|
| 国の行政機関 | `*.go.jp` | maff.go.jp, meti.go.jp, mlit.go.jp, cao.go.jp, env.go.jp |
| 地方自治体 | `*.lg.jp` | tokyo.lg.jp, pref.hokkaido.lg.jp, city.sapporo.lg.jp |
| 主要財団・協会 | `*.or.jp` (個別 whitelist) | 日本政策金融公庫、中小企業基盤整備機構、各業界団体 |
| 独立行政法人 | 公式 `*.go.jp` / `*.or.jp` | 農研機構、JETRO、中小機構 |
| 国の審議会 / 政府統計 | e-Gov, e-Stat | e-gov.go.jp, e-stat.go.jp |
| EU / 国際機関 (サブセット) | 公式 domain | `*.europa.eu`, `*.oecd.org` (該当する場合) |

### 2.2 禁止ソース (aggregator blocklist)

以下のソースからの制度情報を canonical として ingest することを**禁止**します。Wave 4-6 の信頼性検証で、一次資料との齟齬・誇張・掲載期限切れの確率が高いと判明しています。

**禁止 aggregator list**:

- `noukaweb.com`
- `hojyokin-portal.jp`
- `biz.stayway.jp`
- `nikkei.com` (新聞記事)
- `prtimes.jp` (PR)
- `wikipedia.org` (百科事典)
- その他 `*.co.jp` / 商用メディアで **「まとめサイト」的に制度情報を転載しているもの**

ただし、これらのサイトを **一次資料の existence を示唆する lead source** として内部的に参照することは可 (lead → primary source 確認 → canonical 登録のフロー)。

### 2.3 例外処理

上記分類に当てはまらないが重要性の高いソースがある場合、個別に whitelist 登録し、`canonical_source_note` フィールドに判断根拠を記録します。

---

## 3. 更新頻度

### 3.1 定期 sweep

- **週次 full sweep**: 毎週月曜 02:00 JST、全 canonical URL を re-fetch して change detection。
- **月次 deep audit**: 毎月 1 日、tier A/S 制度は manual review を含む validation。
- **日次 top-N watch**: アクセス上位 100 制度は 24 時間以内に change detection。

### 3.2 新制度検知時

- 新制度の公表 (省庁 press release / 告示) 検知時、**48 時間以内** に canonical metadata を DB に ingest。
- ingest 前に primary source で 2 点確認 (URL alive + content match)。

### 3.3 改正検知時

- 公募期間変更、交付上限変更、要件変更等を検知した場合、**72 時間以内** に DB update。
- 変更内容は `revision_history` テーブルに監査ログとして保存。

---

## 4. Tier 判定

unified_registry の tier は、**実データ充足度**に基づき厳格に判定します (2026-04-20 確立ルール)。

| Tier | 定義 | 目安件数 |
|---|---|---|
| S | 公募中 + 交付決定あり + 申請様式 link alive + 採択率公開 | 1 件 |
| A | 公募中 + 交付決定あり + 申請様式 link alive | ~50 件 |
| B | 公募中 + 一次資料 link alive | ~60 件 |
| C | 休止中だが制度存続、過去交付実績あり | ~200 件 |
| D | 制度自体が存続するが現在公募なし | ~400 件 |
| expired | 制度終了・統廃合 | 別 status |

**禁止事項**: データ空の項目を「ある」と推定して tier を水増ししない。

---

## 5. 撤回制度の扱い

### 5.1 Status 管理

撤回された制度は即時削除せず、以下の canonical_status で区別:

| status | 意味 | 検索結果への扱い |
|---|---|---|
| active | 公募中 | 標準の検索結果に含む |
| paused | 一時休止 (年度替わり待ち等) | 検索結果に含む (ラベル付) |
| expired | 制度終了 | 検索結果から除外 (名前空間 alias は保持) |
| merged | 他制度に統合 | alias で後継制度にリダイレクト |

### 5.2 Alias 保持

撤回された制度でも、お客様が過去の制度名で検索してくる可能性があるため、**alias 名は 3 年以上保持**します。

### 5.3 撤回時の情報残置

`expired` の場合でも、以下の metadata は保持:

- 過去の交付実績 (aggregate)
- 後継制度への link (あれば)
- 終了日
- 終了根拠 (告示 URL)

---

## 6. 誤情報修正 path

### 6.1 外部からの報告窓口

誤情報の報告は以下の窓口で受け付けます。

- Email: `info@bookyou.net`
- 件名: `[data-correction] 制度ID <canonical_id>`
- 推奨情報: canonical_id、誤り箇所、正しい情報の一次資料 URL

### 6.2 対応 SLA

| 重大度 | 対応期限 |
|---|---|
| critical (受給期限切れを「公募中」と誤表示等) | 24 時間以内に hotfix |
| high (交付上限額の誤表示等) | 48 時間以内 |
| medium (要件の一部誤記) | 7 日以内 |
| low (表記ゆれ、typo) | 次回週次 sweep で修正 |

### 6.3 修正後の対応

- 報告者に修正完了を email で通知 (報告者 opt-in 時)
- `revision_history` テーブルに修正根拠を記録
- 誤情報を元に誤った判断をした可能性のあるお客様への事後通知 (critical のみ、API 利用 log から過去 90 日の該当 query を抽出)

---

## 7. データ品質 metric

以下の KPI を月次で追跡します。

| metric | target |
|---|---|
| canonical URL liveness (200 OK 率) | >=99% |
| 誤情報報告件数 | 記録 (推移 watch) |
| critical 誤情報発見からの hotfix 時間 (中央値) | <=24h |
| tier S/A の manual review 完了率 | 100% (月次) |

---

## 8. データ独立性

AutonoMath は以下を**行いません**:

- 個別事業者への推薦 (A 制度より B 制度が良い等の editorial opinion)
- 制度所管機関からの sponsorship 受領 (特定制度の検索順位を上げる等の commercial bias)
- 検索結果の paid promotion

検索結果の順位は、**客観的 metric** (一致度、最新性、tier) のみで決定します。

---

## 9. 補足: 個人情報 / 要配慮個人情報 の混入防止

### 9.1 ingest 時の check

- 一次資料に個人名 (申請者氏名、採択者氏名) が掲載されている場合、当社は氏名を redact して ingest します。
- 法人名は公開情報として ingest OK (法人番号、法人名)。

### 9.2 query-side の check

- お客様 query 内の PII (email、電話、住所等) は応答 log への記録前に正規表現で redact。詳細は `privacy_policy.md` 参照。

---

## 9.3 法廷証拠 reproducibility 保証 (R8 dataset versioning)

AutonoMath の主要 8 table (`programs` / `case_studies` / `loan_programs` / `enforcement_cases` / `laws` / `tax_rulesets` / `court_decisions` / `bids`) と autonomath.db の主要 EAV 2 table (`am_entities` / `am_entity_facts`) は、**bitemporal row-level versioning** を採用しています (migration 067, 2026-04-25)。

### 9.3.1 column 構成

各 row に以下の 2 列が付加されています:

| column | 意味 | NULL の意味 |
|---|---|---|
| `valid_from` | 当該 row 内容が真実状態となった ISO-8601 timestamp | 通常は NOT NULL (backfill 済) |
| `valid_until` | 当該 row が後継 row により上書きされた timestamp | **NULL = 現役 (live row)** |

既存 column との組み合わせで **3 軸 timestamp** が完備されます:

- `valid_from` (bitemporal 起点)
- `source_fetched_at` / `fetched_at` (一次資料取得時刻)
- `source_url` (一次資料 URL — 再取得可能)

### 9.3.2 append-only update 原則

row が更新されるとき、writer は以下の atomic 操作を行います:

1. 旧 row の `valid_until` に現在時刻を書く (= retire)
2. 新 row を新規 `valid_from` 付きで INSERT (= activate)

**物理 UPDATE による上書き禁止** — 訂正削除の履歴が失われ、電子帳簿保存法 §4-3 真実性確保要件を満たせません。

### 9.3.3 法廷証拠としての利用

任意の過去日付について、以下の predicate で**当時の DB 状態**を再現可能です:

```sql
WHERE valid_from <= :as_of_date
  AND (valid_until IS NULL OR valid_until > :as_of_date)
```

これにより以下の利用 case が成立します:

- **税務調査**: 申告基準日における制度該当性を、当時のデータで再判定。
- **監査・弁護士 due diligence**: 契約締結時点の規制状態を当時のデータで再現。
- **行政書士業務記録**: 申請受付時点の交付要件を再現可能な形で保存。

エンドポイント:

- REST: `GET /v1/programs/search?as_of_date=YYYY-MM-DD`、`GET /v1/programs/{id}?as_of_date=YYYY-MM-DD`
- MCP tool: `query_at_snapshot(query_payload, as_of_date)` — response に `audit_trail` block (`source_url` + `fetched_at` + `valid_from` + `predicate` + `schema_migration`) を必ず添付。

### 9.3.4 retention

`valid_until` を持つ historical row は、対応する **法定保存期間 (10 年)** に同期して保持されます (法人税法 + 電子帳簿保存法)。10 年経過後に retire された row のみ archive 可能 (active row は retention 対象外)。

---

## 10. 更新履歴

- 2026-04-25: §9.3 (R8 dataset versioning + 法廷証拠 reproducibility 保証) 追加
- 2026-04-24: 初版策定 (Wave 15 compliance 策定時、禁止 aggregator list を Wave 4-6 知見から確定)

---

## 11. 連絡先

**Bookyou株式会社**
〒112-0006 東京都文京区小日向2-22-1
法人番号: T8010001213708
Email: `info@bookyou.net`

以上
