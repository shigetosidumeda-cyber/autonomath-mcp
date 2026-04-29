# Prompt Cookbook

> 10 個の貼り付け用プロンプトと、それぞれが triggered する MCP ツール呼び出しの想定シーケンス。料金 ¥3/req 一律 (税込 ¥3.30)、anonymous は 50 req/月 まで無料。

Public HTML 版: [/prompts.html](https://zeimu-kaikei.ai/prompts.html)
MCP tool リファレンス: [mcp-tools.md](./mcp-tools.md)
Exclusion 概念: [exclusions.md](./exclusions.md)
動くサンプル: [examples.md](./examples.md)

Each recipe is structured as:

- **Persona / Hook** — 誰が何を求める場面か
- **Prompt** — Claude / Cursor / ChatGPT に貼り付ける日本語文
- **Tool sequence (YAML)** — agent が triggered するであろう MCP tool call
- **Notes** — データ充足ギャップや注意点。公開保留中の制度 (1,923 行) は検索路から除外、`compat_matrix` の出典裏取りは 9% に留まる。

---

## Bucket: Agriculture

### Recipe 1 — Aomori × Apple × New Farmer

- **Persona:** 新規就農者 (青森県でりんご)
- **Hook:** 国・県・市町村の制度を一括棚卸し

**Prompt:**

> 青森県でりんご農家として新規就農する予定です。使える補助金・融資・支援金を国・青森県・市町村のレベルで網羅的に洗い出してください。認定新規就農者の取得を前提にしていいです。金額上限と申請窓口の締切がわかるものを優先し、併用不可の組み合わせがあれば注意点も添えてください。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: りんご 新規就農
    prefecture: 青森県
    tier: [S, A, B]
    fields: default
    limit: 20
- tool: search_programs  # 国レベルも横断
  args:
    q: 新規就農 認定
    authority_level: national
    tier: [S, A, B]
    limit: 10
- tool: check_exclusions
  args:
    program_ids:
      - keiei-kaishi-shikin
      - keiei-hatten-shoki
      - seinen-shuno-shikin
- tool: get_program
  args:
    unified_id: "<top hit from search>"
    fields: full
```

**Notes:** 青森県は 49 programs (うち tier S/A/B は一部)。りんご + 新規就農に直接マッチする制度 7 件確認済み。市町村レベルはつがる市・弘前市が厚い。

---

### Recipe 2 — Niigata × Rice × Corporate

- **Persona:** 農業法人経営者 / 認定農業者 (新潟県で米作)
- **Hook:** 経営規模拡大・機械更新の支援を網羅

**Prompt:**

> 新潟県で米作の農業法人 (認定農業者、農地所有適格法人) を運営しています。経営規模拡大・機械更新・担い手育成に使える補助金と、スーパー L 資金などの融資を網羅的に教えてください。国事業と新潟県独自事業を分けて、上限額の大きい順に並べてほしいです。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: 認定農業者 経営規模
    prefecture: 新潟県
    tier: [S, A, B]
    limit: 20
- tool: search_programs
  args:
    q: スーパーL 担い手
    authority_level: national
    limit: 10
- tool: search_programs
  args:
    q: 農地所有適格法人
    prefecture: 新潟県
    limit: 10
- tool: get_program
  args:
    unified_id: super-L-shikin
    fields: full
```

**Notes:** 新潟県 106 programs。農地所有適格法人育成促進 / 多様な米づくり推進 / 経営体発展総合支援 が主。スーパー L は認定農業者が前提。

---

### Recipe 3 — Hokkaido × Dairy × Environmental

- **Persona:** 新規就農者 / 畜産 (北海道で酪農 + 環境保全型)
- **Hook:** 国の直接支払まで取りこぼさない

**Prompt:**

> 北海道で酪農家として独立する予定です。環境保全型農業にも取り組みたいので、酪農関連の国・道・町村の支援制度と、環境保全型農業直接支払などの国制度を合わせて洗い出してください。移住・就農支援・研修制度も含め、取得順序 (先に認定を取るべきもの等) もわかれば示してください。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: 酪農 新規就農
    prefecture: 北海道
    tier: [S, A, B]
    limit: 20
- tool: search_programs
  args:
    q: 環境保全型農業 直接支払
    authority_level: national
    limit: 10
- tool: check_exclusions
  args:
    program_ids:
      - keiei-kaishi-shikin
      - seinen-shuno-shikin
      - 認定新規就農者
- tool: get_program
  args:
    unified_id: "<環境保全型農業直接支払交付金 ID>"
    fields: full
```

**Notes:** 北海道 162 programs。酪農専用は別海町・津別町・更別村・鹿追町が厚い。有機単独は薄いため環境保全型 (国事業) で代替可。

---

## Bucket: SMB / Non-Agri

### Recipe 4 — Tokyo × Manufacturing × CapEx

- **Persona:** 中小企業経営者 (東京の金属加工業)
- **Hook:** 「いくら / いつまでに / 何が必要」

**Prompt:**

> 東京都で金属加工の中小製造業 (従業員 25 名) を経営しています。来期に新しい加工機を 3000 万円で導入したい。使える国の補助金 (ものづくり・省力化・新事業進出) と、東京都独自のゼロエミ・DX 助成を横並びで比較したいです。上限額・補助率・申請締切・併用可否を表でまとめてください。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: ものづくり 省力化 設備投資
    authority_level: national
    tier: [S, A, B]
    limit: 10
- tool: search_programs
  args:
    q: ゼロエミッション DX
    prefecture: 東京都
    tier: [S, A, B]
    limit: 10
- tool: batch_get_programs
  args:
    unified_ids:
      - "<ものづくり補助金 ID>"
      - "<省力化投資補助金 ID>"
      - "<新事業進出補助金 ID>"
      - "<東京都ゼロエミ ID>"
- tool: check_exclusions
  args:
    program_ids:
      - monozukuri-hojokin
      - shoryokuka-toshi-hojokin
```

**Notes:** 東京都 56 programs。ゼロエミ (tier S) は目玉。ものづくり補助金系は「同一設備への重複補助不可」の一般原則に注意。

---

### Recipe 5 — Osaka × Service × IT

- **Persona:** 中小企業経営者 (大阪のサービス業)
- **Hook:** IT 導入補助金まわりを整理
- **Badge:** 市区町村 10 件粒度 (Paid で叩く想定、Free でも動くが 50 req/月 以内)

**Prompt:**

> 大阪市で小売・サービス業 (従業員 12 名、本社大阪市) を運営しています。業務システムとクラウド会計の導入を予定しており、IT 導入補助金を中心に使える国・大阪府・大阪市の支援策を教えてください。対象経費・補助率・公募回の想定、そして他の小規模事業者持続化補助金などとの併用可否も合わせて確認したいです。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: IT導入 デジタル化
    authority_level: national
    limit: 10
- tool: search_programs
  args:
    q: デジタル化 DX
    prefecture: 大阪府
    tier: [A, B]
    limit: 10
- tool: check_exclusions
  args:
    program_ids:
      - it-donyu-hojokin
      - jizokuka-hojokin
```

**Notes:** 大阪府 44 programs (うち非農業 IT/DX は大阪市デジタル化推進支援など少数)。国レベルの IT 導入補助金 + 大阪市上乗せで組む構成が実用的。

---

### Recipe 6 — Fukuoka × Restaurant × Creation Finance

- **Persona:** 創業予定者 (福岡でラーメン店)
- **Hook:** 融資と補助金の両取り

**Prompt:**

> 福岡市で飲食店 (ラーメン店、自己資金 500 万円) を開業します。日本公庫の創業融資と、福岡県・福岡市の創業補助金・家賃補助を組み合わせて資金計画を立てたいです。融資枠・補助率・自己資金要件・認定経営革新等支援機関の関与が必要かどうかも教えてください。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: 創業 融資
    authority_level: financial
    limit: 10
- tool: search_programs
  args:
    q: 創業 新規
    prefecture: 福岡県
    limit: 10
- tool: search_programs
  args:
    q: 小規模事業者 経営改善
    authority_level: national
    limit: 5
- tool: get_program
  args:
    unified_id: "<福岡市新規創業促進補助金 ID>"
    fields: full
```

**Notes:** 福岡県 112 programs。飲食固有の家賃補助は市区町村依存でデータ薄めの場合あり、その場合は creation finance + 新規創業促進補助金ルートで組む。

---

## Bucket: Accounting / Tax

### Recipe 7 — SMB Enhancement Act × Tax Preferences

- **Persona:** 会計士 / 税理士
- **Hook:** クライアントに勧める税制優遇を全件把握

**Prompt:**

> 中小企業等経営強化法に基づく経営力向上計画の認定を受けたクライアント (製造業・資本金 3000 万円) に案内できる税制優遇を一覧で整理してください。中小企業経営強化税制・中小企業投資促進税制・先端設備等導入計画・DX 投資促進税制・賃上げ促進税制・事業承継税制 (法人版特例) を個別に、要件と即時償却/税額控除の選択肢、併用可否がわかる形で。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: 経営強化税制
    program_kind: 税制
    limit: 5
- tool: search_programs
  args:
    q: 投資促進税制 DX 賃上げ
    authority_level: national
    limit: 10
- tool: search_programs
  args:
    q: 先端設備 事業承継税制
    authority_level: national
    limit: 5
- tool: batch_get_programs
  args:
    unified_ids:
      - "<中小企業経営強化税制 ID>"
      - "<中小企業投資促進税制 ID>"
      - "<DX投資促進税制 ID>"
      - "<賃上げ促進税制(中小企業向け) ID>"
      - "<事業承継税制(法人版特例措置) ID>"
      - "<先端設備等導入計画の認定 ID>"
```

**Notes:** 全 6 本の税制制度が tier B/C で確認済み。`get_program` の enriched で措置内容を拾い、併用可否は注記ベース。

---

### Recipe 8 — Invoice × Subsidies

- **Persona:** 税理士 / 会計士
- **Hook:** 事務負担と補助金を整理
- **Badge:** 軽減措置の自治体別を含む (Paid で叩く想定、Free でも 50 req/月 以内なら可)

**Prompt:**

> 顧問先 (小規模事業者、年商 2000 万円、サービス業) がインボイス登録して事業者免税点制度から課税事業者になりました。会計ソフト・レジ・販売管理の改修費用に使える国の補助金 (IT 導入補助金・小規模事業者持続化補助金など)、および 2 割特例・少額特例などの税制経過措置の案内をまとめてください。補助金同士の重複制限も明示してください。

**Tool sequence:**

```yaml
- tool: search_programs
  args:
    q: IT導入 デジタル化
    authority_level: national
    limit: 5
- tool: search_programs
  args:
    q: 小規模事業者持続化
    authority_level: national
    limit: 5
- tool: search_programs
  args:
    q: 省力化 投資
    authority_level: national
    limit: 5
- tool: check_exclusions
  args:
    program_ids:
      - it-donyu-hojokin
      - jizokuka-hojokin
      - shoryokuka-toshi-hojokin
```

**Notes:** 「インボイス」「適格請求書」単語での直接ヒットは 0 (DB 語彙)。実用上は IT 導入補助金 (インボイス対応類型) + 持続化補助金 (インボイス特例枠) で組み、税制経過措置 (2 割特例・少額特例) は agent 知識で補完する設計。

---

## Bucket: Exclusions

### Recipe 9 — 5-Way Compatibility Check

- **Persona:** 補助金申請支援会社
- **Hook:** 「この 5 つ全部取れる?」を一発判定

**Prompt:**

> 顧客の新規就農者が、経営開始資金・経営発展支援事業・青年等就農資金・雇用就農資金・就農準備資金の 5 つに申請したがっています。これらを同時にすべて受給できますか。併用不可・条件付き減額・前提条件 (認定新規就農者の取得要否等) の排他ルールがあれば、どの組み合わせでどう triggered するかを 1 件ずつ根拠付きで示してください。

**Tool sequence:**

```yaml
- tool: check_exclusions
  args:
    program_ids:
      - keiei-kaishi-shikin
      - keiei-hatten-shoki      # 初期投資促進タイプ
      - keiei-hatten-sedai      # 世代交代タイプ
      - seinen-shuno-shikin
      - koyo-shuno-shikin
      - shuno-junbi-shikin
- tool: list_exclusion_rules
  args: {}
- tool: get_program
  args:
    unified_id: keiei-kaishi-shikin
    fields: full
```

**Notes:** 181 排他ルール中、このセットで triggered するのは 5 件以上 (絶対排他 3 + 条件付き減額 1 + 前提条件 1)。

---

### Recipe 10 — Keiei-Kaishi vs Koyo-Shuno

- **Persona:** 社労士 / 農業支援会社
- **Hook:** どちらを取るべきか根拠付きで

**Prompt:**

> 新規就農予定者 (29 歳、独立自営志向だが 2 年間は先輩農家の下で働く予定) に、経営開始資金と雇用就農資金のどちらを勧めるべきですか。両者は併用不可ということを前提に、受給期間・金額・経営形態 (独立 vs 雇用) の違いから判断基準をまとめ、切り替え時 (雇用 → 独立) に起こりうる制度上の制約を排他ルールで確認してください。

**Tool sequence:**

```yaml
- tool: batch_get_programs
  args:
    unified_ids:
      - keiei-kaishi-shikin
      - koyo-shuno-shikin
- tool: check_exclusions
  args:
    program_ids:
      - keiei-kaishi-shikin
      - koyo-shuno-shikin
- tool: list_exclusion_rules
  args: {}
```

**Notes:** excl-keiei-kaishi-vs-koyo-shuno-absolute (absolute severity) が中核ルール。時系列切替時の注意点は enriched の B_target / C_timing から導出。

---

## Calling from your code

専用 SDK は未リリース。HTTP は `curl` / `requests` / `fetch` で直接叩ける形に
してある。サンプルは [examples.md](./examples.md) と
[api-reference.md](./api-reference.md) を参照。

```python
import os, requests

BASE = "https://api.zeimu-kaikei.ai"
HEAD = {"Authorization": f"Bearer {os.environ.get('AUTONOMATH_API_KEY','')}"}

# Recipe 1 step 1
r = requests.get(
    f"{BASE}/v1/programs/search",
    params={"q": "りんご 新規就農", "prefecture": "青森県",
            "tier": ["S", "A", "B"], "limit": 20},
    headers=HEAD, timeout=10,
)
results = r.json()
```

MCP 経由 (Claude Desktop / Cursor) なら、`autonomath-mcp` を stdio で
spawn して `search_programs` を呼ぶだけ。詳細は
[mcp-tools.md](./mcp-tools.md) を参照。

---

## See Also

- [mcp-tools.md](./mcp-tools.md) — 各 tool の詳細スキーマ
- [api-reference.md](./api-reference.md) — REST 等価形
- [exclusions.md](./exclusions.md) — 排他ルールの kind / severity 分類
- [examples.md](./examples.md) — その他のユースケース
