# jpcite LLM耐性事業計画

更新日: 2026-04-30
対象: `jpcite` / `jpintel-mcp` / `https://jpcite.com/about`
ステータス: 内部計画。法的意見ではなく、事業・販売・技術・表示リスクの統合計画。

## 0. ブラッシュアップ要旨

この版では、計画を「これから大きく作るもの」ではなく、既存実装をどう束ねると価値が最大化するかに寄せる。

重要な修正は次の通り。

| 観点 | 修正後の方針 |
|---|---|
| 競争軸 | AI回答ではなく、LLM・SaaS・士業業務に渡す Evidence Layer として売る |
| 既存実装 | `source_manifest`、`citations.verify`、`bulk_evaluate`、`saved_searches`、`customer_webhooks`、`cost.preview` は「作る」ではなく「Evidence Packetに接続する」 |
| 価格訴求 | `¥3/billable unit` は「常にLLMより安い」ではない。paid search / grounding、長文投入、再検索、監査証跡を置き換える条件で刺さる |
| UI | 新規SaaS画面を増やさない。API、MCP、OpenAPI、CSV、Webhook、ZIP、Widgetで届ける |
| 法務表示 | `100%`、`全件`、`必ず`、`保証`、`政府公認`、`ChatGPTより正確` は使わない。数値は分母・算定日・除外条件を併記する |
| 最初の売り方 | 顧問先CSVを持つ補助金コンサル・認定支援機関向けの Client Evidence Brief を最初の商用デモにする |

短く言えば、今やるべきことは次である。

> 既存の検索・出典・CSV・Webhook・監査ログを、1つの Evidence Packet として再利用可能にする。

## 1. 結論

jpcite は「AIが日本の制度を答えるサービス」として売るべきではない。Claude、ChatGPT、その他LLMは、補助金候補の説明文、制度の要約、一般的な比較表、申請書風の下書きをすでに作れる。ここで正面から競争すると、価格も差別化も弱くなる。

jpcite の勝ち筋は、**LLMの回答を検証可能にする日本公的情報のデータレイヤー**である。

短い表現では、次の位置づけにする。

> AIが書く。jpciteが裏取りする。

顧客が継続的に買うものは文章ではない。買うものは、一次資料URL、取得日時、ライセンス、checksum、スナップショットID、監査ログ、差分通知、併用不可・前提条件の構造化照合、法人・制度・法令・税制・行政処分の横断データである。

## 2. 現状理解

公開サイト上の jpcite は、日本の公的制度をAIから検索できるサービスとして説明されている。収録範囲は、検索対象制度 11,684 件、採択事例 2,286 件、融資商品 108 件、行政処分 1,185 件、法令メタデータ 9,484 件、判例 2,065 件、税制ルールセット 50 件、適格請求書発行事業者 13,801 件である。提供形態は REST API + MCP、LINE bot、法令改正アラート、埋込ウィジェット、士業案件紹介で、価格は `¥3/billable unit` 税別の完全従量を軸にしている。

参照:

- [About](https://jpcite.com/about)
- [Pricing](https://jpcite.com/pricing)
- [README.md](../../README.md)
- [docs/pricing.md](../pricing.md)
- [site/trust.html](../../site/trust.html)

ローカル上の主要資産は以下である。

| 資産 | 内容 | 戦略上の意味 |
|---|---:|---|
| `data/jpintel.db` | core検索DB。programs 14,472、searchable 11,684、laws 9,484、case 2,286、loan 108、enforcement 1,185 | REST/MCPの実用検索の正本 |
| `autonomath.db` | entities 503,930、facts 6,124,990、relations 177,381、aliases 335,605、sources 97,272 | 横断グラフ、fact provenance、DD用途の中核 |
| MCP runtime | 実行時 93 tools (旧表記 89 → 93 へ更新済) | AI agentから呼ばれる導線 |
| OpenAPI / runtime | 公開spec、docs、runtimeでendpoint数にdriftあり | REST連携・SDK・SaaS組込の導線。数値は自動生成に寄せる |
| Trust Center | snapshot、鮮度、ライセンス、監査ログ、No-LLM invariant | B2Bでの信頼材料 |

ただし、endpoint数・tool数・無料枠・公開件数は現時点で複数箇所にdriftがある。計画書の数値をそのまま公開値にしない。監査上、docs、site、committed OpenAPI、runtime OpenAPIでendpoint数が割れており、無料枠も `50 req/月` と `3 req/日` が混在している。`README`、`docs/openapi/v1.json`、公開サイト、runtime OpenAPI、DB実測のどれを正本にするかを決め、生成で揃える。

既に商用化に使える部品は次である。ここを未実装タスクとして扱わない。

| 実装状態 | 既存部品 | 価値 | 次にやること |
|---|---|---|---|
| 実装済み | `POST /v1/me/clients/bulk_evaluate` | 顧問先CSVから候補制度ZIPを返せる | ZIPに `evidence.csv` と出典列を増やし、初回デモの主役にする |
| 実装済み | `/v1/me/saved_searches` | 保存条件とdigestの土台 | Evidence Packet endpointと `diff_id` をdigestに入れる |
| 実装済み | `/v1/me/webhooks` | 顧客システムへの差分配信の土台 | payloadに `evidence_packet_endpoint`、`corpus_snapshot_id`、`diff_id` を入れる |
| 実装済み | `POST /v1/citations/verify` | 引用が本当にsource内にあるか検証できる | `verification_status="verified"` の根拠としてEvidence Packetへ接続する |
| 実装済み | `/v1/source_manifest/{program_id}` | program単位のsource rollup | fact provenance coverageを正直に表示し、過剰な「全件出典」を避ける |
| 部分実装 | `src/jpintel_mcp/api/cost.py` / bulk cost preview | 従量課金の不安を下げる | runtime mountとdocs反映を確認し、Token Cost Shieldの見積・デモとつなげる |
| 実装済み | `/v1/am/dd_batch`, `/v1/am/dd_export` | 法人DD dossierの土台 | 価格表現を実装済みbundle単価と整合させる |
| 部分実装 | v2 response envelope | citation / meta / warning の共通形 | Evidence Packetを独自形にしすぎず、v2 envelopeの延長として定義する |
| 部分実装 | audit seal helper / migration | 後から検証できる応答の土台 | call siteと取得APIに接続する |
| 未完成 | `am_amendment_diff` | Change Watchの中核 | 非空化するまで「稼働済み差分配信」と言わない |

注意点として、公開値と実測値は定義を分ける必要がある。searchable program の `source_url` 充足は高い一方、全 programs ベースでは充足率が下がる。今後は「検索対象」「全収録」「fact単位」「entity単位」を分けて公開する。

## 3. LLM単体との差別化

LLMが強い領域と、jpcite が残すべき領域を明確に分ける。

| 領域 | LLM単体の代替可能性 | jpcite の方針 |
|---|---:|---|
| 制度の自然文説明 | 高い | 売らない。顧客側LLMに任せる |
| 補助金候補の一般回答 | 高い | 単発Q&Aとしては主力にしない |
| 比較表・提案文 | 高い | Evidence Packetから顧客側LLMが生成 |
| 申請書・相談文風の下書き | 高いが法務リスクも高い | 提供しない、または有資格者確認前提 |
| 一次資料URL・取得日時・checksum | 低い | 中核価値 |
| 再現可能な検索結果 | 低い | snapshotとrequest replayで商品化 |
| 顧問先・投資先リストの一括照合 | 低い | CSV/batch/APIで商品化 |
| 差分検知・保存検索・webhook | 低い | 継続課金の中心 |
| 併用不可・前提条件・除外理由 | 中から低 | rule engineとして強化 |
| 監査ログ・証拠ZIP・DD dossier | 低い | 高単価用途 |

jpcite のメッセージは、以下に寄せる。

- LLMは答えを作る。jpciteは、その答えを検証できる根拠を返す。
- 回答ではなく、出典URL、取得日時、ライセンス、checksum、ルール判定を買う。
- 似た回答は誰でも生成できる。監査に耐える evidence packet は生成しにくい。
- jGrantsは申請窓口。jpciteは候補探索・条件照合・検証のデータレイヤー。
- No server-side LLM。顧客側AIに、検証可能な公的情報だけを供給する。

## 4. ポジショニング

旧ポジション:

> 日本の制度をAIから検索できるサービス。

新ポジション:

> LLM・士業・SaaS・社内AIエージェントが、日本の公的制度情報を出典付きで検証するための API / MCP データレイヤー。

さらに短い営業コピー:

> ChatGPTで文章は作れます。jpciteは、その文章に貼れる一次資料・取得日時・監査ログを返します。

この位置づけなら、LLMは競合だけでなく販路になる。ChatGPT Apps / Connectors、Claude MCP connector、Cursor、社内RAG、SaaS組込が jpcite を呼び出す構造を作れる。

## 5. 商品設計

API本体は、現行の `¥3/billable unit` を維持し、導入目的別パッケージとして見せる。Starter / Pro / Enterprise のようなAPI tierは増やさない。例外は、公開サイト埋込のためにorigin制限・ブランド表示・fair use管理が必要な Widget と、DD bundle のartifact-size単位である。ここは「API tier」ではなく「配布形態・成果物サイズ」として整理する。

| パッケージ | 買う人 | 提供価値 | 主な出力 | 初期価格方針 |
|---|---|---|---|---|
| Evidence API / MCP | AI agent開発者、SaaS、RAG開発者 | 補助金、融資、法令、税制、判例、行政処分を一次資料付きで取得 | Search Result + Evidence Packet | `¥3/billable unit` |
| Advisor Screening Layer | 補助金コンサル、行政書士、税理士、認定支援機関 | 顧問先CSVから候補制度、締切、除外理由、出典を一括取得 | Client Evidence Brief | `¥3 × billing unit` の用途別見積 |
| Compliance / DD Layer | VC、M&A、金融機関、CFO、経理 | 法人番号、行政処分、採択、インボイス、法令を横断確認 | DD Evidence Dossier | 実装済みDD bundle単価に寄せる。高単価化するなら別商品定義が必要 |
| Change Watch Layer | 士業、SaaS、管理部門 | 法改正、制度変更、締切、失効を保存条件で監視 | Watch Event Packet | `¥3/通知` またはAPI従量 |
| Embedded Evidence Layer | 士業サイト、金融機関、SaaS | 自社UI内で根拠付き制度検索を提供 | Widget Result + Source Footer | Widget Business `¥10,000/月`、Whitelabel `¥30,000/月` |

主力は Evidence API、Advisor Screening、DD、Change Watch の4つにする。LINEは単純Q&Aとしてではなく、リマインド、保存検索、T番号/OCR、通知導線に寄せる。

### 5.1 UI方針

UIを事業の主戦場にしない。AIが開発する前提では、独自UIを増やすほど品質がばらつき、見た目の調整に時間を吸われ、肝心のデータ品質・出典・検証が弱くなる。

機械的な方針は以下にする。

| 判断 | 方針 |
|---|---|
| 新しい画面を作るか | まず作らない。API、MCP、OpenAPI、CSV、JSON、Webhookで済ませる |
| ダッシュボードを作るか | billing、usage、API key、上限設定だけに限定する |
| 顧客向けUIを作るか | Widgetや既存サイト埋込に限定し、独自SaaS画面を増やさない |
| デザインをどうするか | 既存CSSと既存ページ構造を使う。AIにゼロからUIを作らせない |
| 価値をどこに置くか | UIではなく、Evidence Packet、出典、checksum、監査ログ、差分通知に置く |
| UIで説明するか | 説明文を増やさず、出力例、JSON、CSV、証拠ZIPで見せる |

UIが必要な場合も、画面単位ではなく部品単位で考える。

- API key発行
- usage/cap表示
- Evidence Packet表示
- source_url / fetched_at / checksum 表示
- saved search管理
- webhook設定
- export download

これ以外のUIは、売上か信頼性に直結するまで作らない。

## 6. Evidence Packet 仕様

自然文回答を主役にしない。主役は Evidence Packet とする。

```json
{
  "packet_id": "evp_...",
  "generated_at": "2026-04-30T00:00:00+09:00",
  "api_version": "v1",
  "corpus_snapshot_id": "corpus-2026-04-29",
  "query": {
    "user_intent": "東京都で使える設備投資補助金",
    "normalized_filters": {
      "prefecture": "東京都",
      "program_kind": "補助金"
    }
  },
  "answer_not_included": true,
  "records": [
    {
      "entity_id": "UNI-...",
      "primary_name": "...",
      "record_kind": "program",
      "facts": [
        {
          "fact_id": 12345,
          "field": "amount_max_man_yen",
          "value": 450,
          "confidence": 0.9,
          "source": {
            "url": "https://...",
            "publisher": "経済産業省",
            "fetched_at": "2026-04-28T00:00:00Z",
            "checksum": "sha256:...",
            "license": "政府標準利用規約 v2.0"
          }
        }
      ],
      "rules": [
        {
          "rule_id": "excl-...",
          "verdict": "defer",
          "evidence_url": "https://...",
          "note": "未登録の併用条件が残るため一次資料確認が必要"
        }
      ]
    }
  ],
  "quality": {
    "freshness_bucket": "within_30d",
    "coverage_score": 0.82,
    "known_gaps": ["J_statistics"],
    "human_review_required": true
  },
  "verification": {
    "replay_endpoint": "/v1/programs/UNI-...?fields=full",
    "provenance_endpoint": "/v1/am/provenance/...",
    "freshness_endpoint": "/v1/meta/freshness"
  },
  "_disclaimer": {
    "type": "information_only",
    "not_legal_or_tax_advice": true
  }
}
```

Evidence Packet はゼロから別基盤を作らない。既存の v2 response envelope、`source_manifest`、provenance、`citations.verify`、`am_amendment_diff`、CSV、Webhook を束ねる composer として作る。

実装優先度:

1. `src/jpintel_mcp/services/evidence_packet.py` を作り、program詳細、source manifest、provenance、rule verdict、snapshotを同じ形に束ねる。
2. `src/jpintel_mcp/services/token_compression.py` を作り、LLMを呼ばずに `jpcite_char_weighted_v1` のような決定的推定でtoken見積を返す。
3. `GET /v1/evidence/packets/program/{program_id}` を最小REST endpointにする。初期引数は `include_facts`, `include_rules`, `include_compression`, `input_token_price_jpy_per_1m`, `format=json|csv|md` で足りる。
4. MCP tool `get_evidence_packet(subject_kind, subject_id, ...)` を追加する。ただしRESTと同じ service を呼び、別実装にしない。
5. `source_manifest` の fact provenance coverage は正直に返す。program cohortで未接続のfactがある場合、`unknown` または `inherited_from_program_source` として出す。
6. paid responseで `audit_seal` を付ける。ただしキャッシュ済みEvidence本体にsealを混ぜず、リクエストごとに後付けする。
7. 顧客側LLMが packet を自然文に変換する examples を用意する。

Evidence Packetのcache keyには、少なくとも次を入れる。

```text
subject_kind
subject_id
include_facts
include_rules
include_compression
fields
input_token_price_jpy_per_1m
corpus_snapshot_id または source_checksum
```

Webhook payloadにはフルEvidence Packetを入れず、参照を入れる。

```json
{
  "event_type": "program.amended",
  "timestamp": "...",
  "data": {
    "entity_id": "...",
    "diff_id": "...",
    "field_name": "...",
    "source_url": "...",
    "corpus_snapshot_id": "...",
    "evidence_packet_endpoint": "/v1/evidence/packets/program/..."
  }
}
```

## 7. 競合整理

| 競合層 | 現状 | jpcite の勝ち筋 |
|---|---|---|
| JGrants API | デジタル庁が公開APIを提供。補助金一覧・詳細・V2 detail が存在する | 無料APIのラッパーでは勝てない。JGrants外の自治体制度、融資、税制、法令、処分、採択、併用リスクを横断する |
| JGrants MCP | デジタル庁系リポジトリでJグランツMCPが公開されている | 「補助金MCP」ではなく「公的制度の検証レイヤー」として差別化する |
| 補助金SaaS | 申請支援、金融機関営業、士業向けUIが強い | UIや申請代行で正面衝突せず、裏側のAPI / Widget / MCPとして入る |
| 法務AI | LegalOn、MNTSQ、Hubble等は契約レビュー・CLMが主戦場 | 契約書レビューでは戦わず、公的制度・税制・行政処分・法人番号DDを補完する |
| 汎用LLM | Web search、citations、connectors、MCP接続が進む | LLMを競合ではなく上位の表現レイヤーと見る。jpcite は根拠取得・検証・差分の下位レイヤーになる |

重要な前提として、JGrants APIとJGrants MCPは強い無料代替である。したがって比較ページや営業資料で「JGrantsにAPIがない」といった古い主張は使わない。

### 7.1 競合・差別化監査メモ

2026-04-30時点で、ChatGPT、Claude、GeminiはWeb検索、引用、Deep Research、外部コネクタ、MCP接続を備えている。したがって、jpciteは「AIが日本の制度を答える」市場で勝負しない。単発の自然文回答、制度要約、一般的な候補提示、調査レポート生成は汎用LLMとAI検索が強い。

jpciteの競争領域は、回答生成ではなく、回答の下に置く検証可能な公的情報レイヤーである。価値は、一次資料URL、取得時刻、license、checksum、corpus_snapshot_id、replay endpoint、rule verdict、known gaps、差分通知、監査ログを同じ形式で返せることにある。

| 競合層 | 勝てる条件 | 負ける条件 |
|---|---|---|
| ChatGPT / Claude / Gemini | `source_url`, `fetched_at`, `checksum`, `snapshot_id`, `license`, `rule verdict`, `audit log` を構造化して返す | 単発の「使える補助金を教えて」「制度を要約して」 |
| AI検索 / Deep Research | 調査結果ではなく、LLMに投入する前の検証済み材料を返す | 多分野の市場調査、海外情報、ニュース調査 |
| Web search API | URL羅列ではなく、日本制度向け正規化field、締切、併用不可、除外理由を返す | 顧客が検索・抽出・保存・監査のpipelineを自前で持つ |
| スクレイピング / ブラウザ自動化 | スクレイパー保守、ライセンス、checksum、差分監視を顧客が持ちたくない | 対象サイトが少なく、自前Playwright等で十分 |
| 社内RAG | 社内文書RAGに外部の日本公的情報corpusとして接続する | 顧客が公的制度corpusとprovenanceを既に整備済み |
| JGrants API / MCP | JGrants外の自治体、融資、税制、法令、行政処分、採択例、併用リスクを横断する | 補助金一覧・詳細だけで足りる |

Web search APIやスクレイピング基盤は、URL発見・ページ取得・抽出には強い。しかし、それだけでは日本の補助金、融資、税制、法令、行政処分、採択事例、法人番号を業務判断に使える形へ正規化し、後から同じ根拠を検証するところまでは担保しない。jpciteは検索APIではなく、制度・法人・法令を結ぶEvidence Packet APIとして売る。

社内RAGは競合ではなく導入先である。顧客の社内文書RAGに、jpciteの日本公的情報corpusを外部根拠データとして接続させる。顧客側LLMが文章を書く。jpciteは、文章に貼れる根拠と監査情報を返す。

参照:

- [JGrants API docs](https://developers.digital.go.jp/documents/jgrants/api/)
- [JGrants MCP server](https://github.com/digital-go-jp/jgrants-mcp-server)
- [OpenAI Connectors in ChatGPT](https://help.openai.com/en/articles/11487775-connectors-in-chatgpt)
- [Claude Web Search](https://support.anthropic.com/en/articles/10684626-enabling-and-using-web-search)
- [Claude MCP connector](https://docs.anthropic.com/en/docs/agents-and-tools/mcp-connector)
- [Tavily Pricing](https://www.tavily.com/pricing)

## 8. 初期ICP

優先順位は次の通り。

| 優先 | ICP | 理由 | 初期オファー |
|---:|---|---|---|
| 1 | 補助金コンサル、行政書士、中小企業診断士、認定支援機関 | 顧問先ごとの制度探索、締切確認、併用確認を反復する | 顧問先CSV一括スクリーニング |
| 2 | AIエージェント開発者、RAG/SaaS開発者 | MCP/RESTをそのまま部品化できる | Evidence API無料50req、examples、MCP quickstart |
| 3 | VC、M&A、地域金融機関、CFO | 法人番号起点の公的情報DDは構造化API価値が残る | DD Evidence Dossier |
| 4 | 税理士・会計事務所 | 顧問先相談に対する候補探索需要がある。ただし税務判断は資格者側 | 税制・補助金・法令の出典付き初期調査 |
| 5 | 補助金SaaS・業務SaaS | OEM/Widget/APIとして大きいが商談が長い | Widget、API、webhook |

避ける市場:

- 補助金申請代行そのもの
- 契約書レビューAI
- 一般中小企業向けの有料チャット単体
- 無料補助金検索ポータル
- 採択率保証、申請成功報酬、受給保証

## 9. 収益構造

期間予測ではなく、売上が増える機械的な式として管理する。LLMで代替されやすい単純Q&Aは主力にしない。売上は、業務API、batch、Widget、DD、通知、士業紹介に寄せる。

基本式:

```text
定常売上 =
  paid_api_requests * ¥3
+ paid_alerts * ¥3
+ paid_line_questions * ¥3
+ widget_business_count * ¥10,000
+ widget_whitelabel_count * ¥30,000
+ advisor_conversions * ¥3,000
+ dd_evidence_cases * case_price
```

粗利は外部LLM APIを使わない前提で高く保つ。原価を増やす実装、特にサーバー側LLM推論と手作業CSは避ける。

| 収益レバー | 増やし方 | 注意点 |
|---|---|---|
| paid_api_requests | Evidence Packet、batch、provenance、rule checkを増やす | 単純な自然文Q&Aで増やさない |
| paid_alerts | saved search、差分検知、webhookを課金対象にする | 通知だけでなく証拠URLを必ず返す |
| Widget | 士業・金融・SaaSサイトに埋め込む | UI開発を増やさず、既存Widgetを使う |
| advisor_conversions | 士業紹介の成約だけを課金 | 非保証、広告表記、個人情報同意が必要 |
| DD evidence cases | 法人番号起点の証拠ZIPを案件課金にする | 商業DBの代替ではなく公的情報補完に留める |

売上を上げるためにやることは、以下に限定する。

| やること | なぜ効くか |
|---|---|
| 1リクエストでEvidence Packetを返す | 顧客側LLMやSaaSがそのまま使える |
| 既存CSV/batchに証拠列を足す | 顧問先・投資先・取引先の一括処理で利用量が増える |
| 既存saved searchをEvidence Packetに接続する | 単発検索から継続監視に変わる |
| 既存webhookに `diff_id` とpacket参照を入れる | 顧客の業務システムに残る |
| audit sealを実レスポンスに付ける | 後から検証できるのでB2B価値が上がる |
| 既存DD exportをEvidence Dossierとして見せる | 案件単価を上げやすい |

やらないこと:

- 自然文チャットの回答品質で課金しない。
- UIの見た目で差別化しない。
- 契約書レビュー、税務判断、申請書作成に広げない。
- 個別開発、個別オンボーディング、手作業レポートで売上を作らない。

### 9.1 Token Cost Shield

jpcite は「安い検索API」として売らない。訴求は **高額LLMに長文ページを読ませる前に、必要な根拠だけを圧縮して渡す前処理レイヤー** にする。

中核コピー:

> 高額LLMに読む前に、jpciteが根拠を圧縮する。

言い換えると、LLMのトークンを「探索」ではなく「説明生成・判断補助」に使わせる。jpcite は公募要領、自治体ページ、法令、税制、行政処分を Evidence Packet に変換し、LLMへ渡す入力文量とweb search回数を抑える。

#### 基本式

価格は変わるため、固定の節約額ではなく式で管理する。

```text
LLM費用(円) =
  R * ((Pi * Ti + Pc * Tc + Po * To) / 1,000,000)
+ R * (Ptool * Qtool / 1,000)

jpcite費用(円) = 3 * Nj

R      = 円/USD
Ti     = 通常入力tokens
Tc     = キャッシュ入力tokens
To     = 出力tokens。reasoning / thinking tokens を含む
Pi/Pc/Po = 各token単価 USD / 1M tokens
Qtool  = web search / tool call 数
Ptool  = tool call 単価 USD / 1K calls
Nj     = jpcite request数
```

jpcite が刺さる条件:

```text
jpcite費用 < 回避できたLLM入力tokens費 + 回避できたweb search費 + 回避できた再試行費
```

実装と販売資料では、次の純便益式で管理する。

```text
NetJPY =
  R * ((Pi * ΔTi + Pc * ΔTc + Po * ΔTo) / 1,000,000)
+ R * Σ(Ptool_k * ΔQ_k / 1,000)
- 3 * Nj

NetJPY > 0 のとき、純粋なAPI原価でもjpcite併用が成立する。
```

#### 価格監査メモ 2026-04-30

`¥3/billable unit` は「LLMより常に安い」価格ではない。例として `R = 150円/USD` で換算する。実表示では為替、価格取得日、モデル、キャッシュ、無料枠、tool feeの扱いを必ず併記する。

`¥3` で買える入力token数は次の式で出す。

```text
tokens_equivalent = 3 * 1,000,000 / (R * input_usd_per_1m)
R = 150 の場合、tokens_equivalent = 20,000 / input_usd_per_1m
```

代表的な価格帯で見ると、次のようになる。

| 比較対象 | 入力 USD/1M | 出力 USD/1M | ¥3と等価な入力tokens | ¥3と等価な出力tokens | 見方 |
|---|---:|---:|---:|---:|---|
| 高性能標準モデル | 2.50 | 15.00 | 約8,000 | 約1,333 | 標準的な比較軸 |
| 高額reasoning / pro系 | 5.00 | 25.00-30.00 | 約4,000 | 約667-800 | 深い調査では刺さりやすい |
| Claude Sonnet級 | 3.00 | 15.00 | 約6,667 | 約1,333 | 汎用比較の主対象 |
| Gemini Pro級 | 1.25-2.00 | 10.00-12.00 | 約10,000-16,000 | 約1,667-2,000 | long contextやthinkingで増えやすい |
| mini / Flash級 | 0.10-0.75 | 0.40-4.50 | 約26,667-200,000 | 約4,444-50,000 | 単純処理では価格で勝ちにくい |

検索・groundingの有料枠では、別の見方ができる。

| 検索・tool | 例示単価 | 1回あたり円換算 | `¥3` のbreak-even |
|---|---:|---:|---:|
| Web search | `$10 / 1K calls` | 約¥1.50 | 2回 |
| 高めのsearch preview | `$25 / 1K calls` | 約¥3.75 | 1回 |
| Gemini 3 Search | `$14 / 1K search queries` | 約¥2.10 | 約2 queries |
| Gemini 2.5 Grounding | `$35 / 1K grounded prompts` | 約¥5.25 | 1 grounded prompt |
| Tavily Pay-as-you-go | `$0.008 / credit` | 約¥1.20 | 3 credits |

この表から、単純な短文抽出では「LLMの方が安い」ことがある。特に低価格モデル、キャッシュhit、Batch/Flex、無料grounding枠内では価格訴求は弱い。したがって訴求対象は、安価モデルで済む軽作業ではなく、以下に限定する。

- web searchを何度も回す調査
- PDF/HTML/公募要領を長文で読ませる調査
- 高額モデルでreasoning / thinkingを走らせる調査
- 顧問先・投資先・取引先の一括処理
- 同じ保存条件を繰り返し確認する変更監視
- 出典・checksum・監査証跡が必要なB2B用途

#### ユースケース別の保守的モデル

これは広告表示用の確定値ではなく、ベンチ設計前のモデルである。公開する場合は、後述のpaired A/Bベンチで実測する。

| ユースケース | パターン | LLMだけ tokens | LLMだけ web search | jpcite併用 tokens | jpcite併用 web search | jpcite req | token削減率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 補助金調査: 1社・1テーマ・候補10件 | 保守 | 45k | 8 | 18k | 2 | 6 | 60% |
| 補助金調査: 1社・1テーマ・候補10件 | 標準 | 75k | 15 | 14k | 1 | 5 | 81% |
| 顧問先CSV一括: 100社 | 保守 | 1.2M | 400 | 350k | 25 | 180 | 71% |
| 顧問先CSV一括: 100社 | 標準 | 2.5M | 800 | 260k | 10 | 130 | 90% |
| 法人DD: 1法人 | 保守 | 160k | 25 | 75k | 8 | 25 | 53% |
| 法人DD: 1法人 | 標準 | 280k | 50 | 62k | 4 | 18 | 78% |
| 法令/税制確認: 1論点 | 保守 | 40k | 8 | 18k | 3 | 6 | 55% |
| 法令/税制確認: 1論点 | 標準 | 70k | 12 | 14k | 1 | 4 | 80% |
| 変更監視: 20条件 | 保守 | 350k | 80 | 160k | 20 | 100 | 54% |
| 変更監視: 20条件 | 標準 | 800k | 200 | 70k | 5 | 30 | 91% |

一番主張しやすいのは、顧問先CSV一括、法人DD、変更監視である。単発の軽い検索ではなく、同じ探索を何度も繰り返すほど jpcite の圧縮効果が出る。

#### 実装に入れるフィールド

Evidence Packet に圧縮メトリクスを入れる。

```json
"compression": {
  "packet_tokens_estimate": 820,
  "source_tokens_estimate": 18500,
  "avoided_tokens_estimate": 17680,
  "compression_ratio": 0.044,
  "estimate_method": "jpcite_char_weighted_v1",
  "source_tokens_basis": "pdf_pages",
  "cost_savings_estimate": {
    "currency": "JPY",
    "input_token_price_jpy_per_1m": 300.0,
    "gross_input_savings_jpy": 5.3,
    "jpcite_billable_units": 1,
    "jpcite_cost_jpy_ex_tax": 3,
    "net_savings_jpy_ex_tax": 2.3
  }
}
```

実装方針:

- モデル価格はhard-codeしない。
- `input_token_price_jpy_per_1m` をquery paramまたは設定値で受ける。
- `source_tokens_estimate` が不明な場合は `null` にする。
- `avoided_tokens_estimate` は推定値として返し、保証値にしない。
- RESTとMCPで同じcomposerを使う。

推奨追加:

- `src/jpintel_mcp/services/token_compression.py`
- `src/jpintel_mcp/services/evidence_packet.py`
- `GET /v1/evidence/packets/{subject_kind}/{subject_id}`
- MCP tool `get_evidence_packet(...)`

#### ベンチ方法

公開数値を出すなら、同じ質問を同じモデルで比較する paired A/B にする。

| arm | 入力 | tools | 目的 |
|---|---|---|---|
| `direct_web` | 質問だけ | provider web searchあり | LLMが自力で深掘り調査した場合のtokens/search/cost |
| `jpcite_packet` | 質問 + Evidence Packet | web searchなし | jpcite前処理でtokens/search/costがどれだけ下がるか |

測る指標:

- `input_tokens`
- `output_tokens`
- `reasoning_tokens` / `thinking_tokens`
- `web_searches`
- `jpcite_requests`
- `yen_cost_per_answer`
- `latency`
- `citation_rate`
- `hallucination_rate`

公開できる表現:

> 当社指定ベンチでは、raw PDF/HTMLをLLMへ直接投入する方式と比べ、LLM入力トークン数の中央値がX%低下しました。

避ける表現:

- トークン費を必ず90%削減
- AIコスト90%削減
- 何円節約できます
- 業界最安
- ChatGPTより安い/正確

必要な注記:

> 比較対象: raw PDF/HTMLをLLMへ投入する社内基準実装。対象: ベンチ実施日時点の補助金・税制・融資クエリN件。指標: LLM入力トークン数。LLM出力トークン、jpcite API利用料、通信費、人件費、無料枠、キャッシュ効果は別掲。結果はモデル、プロンプト、取得件数、顧客環境により変動します。

参照:

- [docs/pricing.md](../pricing.md)
- [site/line.html](../../site/line.html)
- [site/widget.html](../../site/widget.html)
- [site/advisors.html](../../site/advisors.html)
- [analysis_wave18/_k7_cost_model_2026-04-25.md](../../analysis_wave18/_k7_cost_model_2026-04-25.md)
- [OpenAI API Pricing](https://developers.openai.com/api/docs/pricing)
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Google Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)

## 10. データ品質・モート計画

品質モートは「件数」ではない。一次資料、checksum、freshness、provenance、eval、cross-linkを同時に公開できることがモートである。

### 10.1 強み

- `data/jpintel.db` は制度検索の実用面が強い。検索可能program 11,684件、法令catalog 9,484件、採択事例、融資、行政処分を同一APIで扱える。
- `autonomath.db` は 50万entity、612万fact、17.7万relation、33.5万alias を持ち、単純検索ではなく横断グラフの土台がある。
- 一次資料志向が明確で、aggregator依存ではなく go.jp、lg.jp、NTA、e-Gov 等を主軸にしている。
- `autonomath.db` の source content hash は高く、`jpintel.db` laws の checksum coverage は高いため、再現性・改ざん検知の土台がある。公開時は分母と算定日を併記する。
- core eval の土台があり、CI gate化できる。

### 10.2 弱み

- 公開主張は定義を明確にしないと危険。program全体とsearchable対象で `source_url` 充足率が異なる。
- `source_lineage_audit` は一次資料扱いでも、監査済み率は別に公開する必要がある。
- `fetched_at` と `verified_at` が混同されやすい。取得日と再検証日を分ける。
- fact単位provenanceが弱い。`am_entity_facts.source_id` は約18%、`source_url` は約45%で、属性単位の説明責任は改善が必要。
- program-law join table が弱い。法令参照の決定的リンクを増やす。
- 金額・時系列は高信頼と参考値を分けて返す。

### 10.3 公開すべき品質指標

| 指標 | 公開値の出し方 | ローンチ時の文言 |
|---|---|---|
| Coverage | table別件数、検索可能件数、excluded件数 | 検索可能program 11,684件、全table件数は別掲 |
| Primary Source Rate | source_type と source_url充足を分ける | 一次資料分類、program source_url、fact source_url を別表示 |
| Citation Rate | API回答で `source_url` を返した割合 | 回答単位のcitation_rateを継続公開 |
| Checksum Coverage | source/table別 hash充足率 | laws / programs を分母つきで別表示。programsは改善対象として公開 |
| Freshness | fetched_at分布、stale件数、broken URL件数 | 取得日と再検証日を分離 |
| Provenance Coverage | entity/fact/source単位で分ける | fact-level provenanceは改善中と明記 |
| Eval | per-tool precision/shape gate、last run日 | core gold suite、AutonoMath eval拡張中 |
| Cross-link | relation数、law reference数、join table充足 | program-law決定リンクは改善中 |
| Known Limits | 欠損・低信頼領域 | 金額抽出、時系列、fact-level provenanceは既知制約 |

### 10.4 データローンチゲート

| Gate | Block条件 |
|---|---|
| DB integrity | `PRAGMA integrity_check` が `ok` でない |
| Checksum manifest | `data/jpintel.db` / `autonomath.db` のSHA256未記録、または配布物と不一致 |
| Source URL | tier S/A の `source_url` 欠損 > 0、またはbroken high-priority URL未処理 |
| Freshness | tier S/A の stale / broken URL が注記なしに残る |
| Citation | public API回答の citation_rate が定義済み閾値を下回る。high-stakes toolsはsource_url欠損でblock |
| Eval | core gold suite失敗、または hallucination_rate > 2% |
| Provenance | 新規ingestで `source_url` / `fetched_at` / `checksum` のいずれか未付与 |
| Disclosure | README/docs/APIの件数・品質値がDB実測と不一致 |

## 11. 技術改善チェックリスト

現状の弱点は、機能不足よりも「証拠面の未接続・数値drift・空の差分ログ」である。

### 11.1 必ず直す

| テーマ | 差別化への直結 | 具体パス |
|---|---|---|
| 公開数値・manifest drift を止める | 信頼性の前提 | [README.md](../../README.md), [server.json](../../server.json), [mcp-server.json](../../mcp-server.json), [docs/launch_checklist.md](../launch_checklist.md) |
| `source_url` 品質gateを固定 | 一次資料つきが最大の価値 | [scripts/data_quality_audit.py](../../scripts/data_quality_audit.py), [src/jpintel_mcp/api/transparency.py](../../src/jpintel_mcp/api/transparency.py) |
| `am_amendment_diff` を空で出さない | 差分・監査ログはLLM単体にない価値 | [src/jpintel_mcp/api/audit_log.py](../../src/jpintel_mcp/api/audit_log.py), [scripts/cron/refresh_amendment_diff.py](../../scripts/cron/refresh_amendment_diff.py) |
| `audit_seal` を実レスポンスに接続 | 監査証跡・改ざん検知 | [src/jpintel_mcp/api/_audit_seal.py](../../src/jpintel_mcp/api/_audit_seal.py), [scripts/migrations/089_audit_seal_table.sql](../../scripts/migrations/089_audit_seal_table.sql) |
| Stripe従量課金 e2e + reconciliation | `¥3/billable unit` 商用化の根幹 | [src/jpintel_mcp/api/billing.py](../../src/jpintel_mcp/api/billing.py), [src/jpintel_mcp/billing/stripe_usage.py](../../src/jpintel_mcp/billing/stripe_usage.py), [scripts/cron/stripe_reconcile.py](../../scripts/cron/stripe_reconcile.py) |
| DB配布と uvx fallback の商用検証 | MCP体験が空検索にならないこと | [src/jpintel_mcp/mcp/_http_fallback.py](../../src/jpintel_mcp/mcp/_http_fallback.py), [AUTONOMATH_DB_MANIFEST.md](../../AUTONOMATH_DB_MANIFEST.md) |
| 決済後APIキー発行導線 | 有料転換の必須導線 | [site/go.html](../../site/go.html), [site/success.html](../../site/success.html) |

### 11.2 次に直す

| テーマ | 差別化への直結 |
|---|---|
| MCP/REST parity matrix を自動生成 | Agent連携で「MCPでもRESTでも同じ証拠」が売れる |
| evalをAutonoMath toolsまで拡張 | 品質指標を公開できる |
| 既存 RSS / webhook / saved search をEvidence Packet参照へ接続 | 「最新差分を監査可能に配信」はLLM回答より強い |
| 法令本文・NTA bulk・入札/判例のデータ拡張 | 出典つき検索対象の厚みが増す |
| fact-level provenance改善 | `source_id` 18%台から重要field優先で50%超へ |

### 11.3 余力が出たらやる

| テーマ | 差別化への直結 |
|---|---|
| audit seal の取得/検証 API | 税理士・監査法人向けに「後から検証できるAPI」になる |
| signed DB bundle / manifest / checksum 公開 | 再現可能なDB配布はLLM SaaSとの差別化 |
| confidence / data_quality / cross-source contradiction 公開 | 「わからない」を数値で返すAPIになる |
| Healthcare / Real Estate は core green 後に限定開放 | 新領域より証拠レイヤーの再利用性を優先 |

## 12. 機械的に良くする手順

スケジュールではなく、赤い項目を上から潰す。AIに実装させる場合も、この順番でissue化する。

| 順位 | やること | 完了条件 |
|---:|---|---|
| 1 | 公開文言を「AI回答」から「出典付き検証API」に変更 | about、top、pricing、docsで表現が揃う |
| 2 | tool数・endpoint数・件数・無料枠・料金のcanonical sourceを作る | README、site、OpenAPI、server.json、runtimeでdriftがない |
| 3 | 匿名無料枠を `50 req/月` か `3 req/日` のどちらかに統一する | docs/pricing、site/pricing、config、anon_limitが一致する |
| 4 | cost preview のruntime mountとdocsを確認する | `/v1/cost/preview` またはbulk preview導線が実際に叩ける |
| 5 | `source_url` 欠損とbroken URLを処理する | tier S/Aで欠損・brokenが残らない |
| 6 | Evidence Packet schemaを固定する | v2 envelope、source_manifest、citations.verifyと矛盾しない |
| 7 | Evidence Packet に圧縮メトリクスを入れる | `packet_tokens_estimate`, `source_tokens_estimate`, `avoided_tokens_estimate` が返る |
| 8 | Token Cost Shield ベンチを作る | `direct_web` と `jpcite_packet` のpaired A/Bで測れる |
| 9 | `corpus_snapshot_id` と `checksum` を標準返却する | 同じsnapshotで再実行できる |
| 10 | `audit_seal` をpaid responseに接続する | レスポンスを後から検証できる |
| 11 | `am_amendment_diff` を非空にする | 差分RSS/APIが空ではない |
| 12 | Stripe usage reconciliationを通す | `usage_events` とStripe集計のズレを検知できる |
| 13 | 既存bulk/CSVのZIPに証拠列を追加する | 顧問先・投資先リストをEvidence付きで一括処理できる |
| 14 | 既存saved searchをpacket/digestに接続する | 同じ条件を保存し、根拠つきで再実行できる |
| 15 | 既存webhook payloadにpacket参照を入れる | 差分が顧客側システムに届き、後から検証できる |
| 16 | 既存DD exportをEvidence Dossierとして整える | 法人番号から証拠ZIP/JSONを出せる |
| 17 | MCP/REST parityを自動検査する | MCPとRESTで返る証拠がズレない |
| 18 | evalを拡張する | search、provenance、rule、diffで回帰検知できる |
| 19 | UIを削る | 新規画面ではなくAPI/docs/examplesで提供できる |

## 13. 販売導線を良くする手順

販売もスケジュールではなく、機械的に「この入力を見せれば買う理由が伝わる」形にする。

最初に売るべき相手は、顧問先を20-200社持つ補助金コンサル、認定支援機関、中小企業診断士である。売るものはチャットではなく、`顧問先CSV -> 候補制度 -> 除外理由 -> 出典URL -> checksum -> 再現情報` の **Client Evidence Brief** である。

| 優先 | 売る相手 | 売るもの | 価値 | 位置づけ |
|---:|---|---|---|---|
| 1 | 補助金コンサル、認定支援機関、中小企業診断士 | Client Evidence Brief | 顧問先ごとの制度探索、締切、除外理由、出典確認を一括化 | 最初の有料転換 |
| 2 | VC、M&Aアドバイザー、地域金融機関 | DD Evidence Dossier | 法人番号起点で行政処分、採択履歴、インボイス、関連制度を証拠化 | 案件単価を上げる |
| 3 | 税理士事務所、商工会議所、金融機関サイト | Embedded Evidence Widget | 自社サイト上で一次資料つき制度検索を出せる | 継続固定収益 |
| 4 | AIエージェント/RAG/SaaS開発者 | Evidence API / MCP | LLMに日本制度データを根拠付きで渡せる | 流入・組込導線 |
| 5 | 士業、SaaS、管理部門 | Change Watch | 保存条件の差分をメール/Webhookで受け取れる | 継続利用を作る |

価格はSKUではなく、用途別の見積テンプレートとして見せる。

| パッケージ | 課金単位 | 利用量モデル | 目安 | 注意点 |
|---|---:|---:|---:|---|
| Client Evidence Brief | `¥3 × billing unit` | 100顧問先 × 4回 × 7 unit | 約¥8,400 | 最初のデモに向く |
| Change Watch | `¥3 / digest or delivery` | 100保存条件 × 20回 | 約¥6,000 | `am_amendment_diff` 非空化が前提 |
| DD Evidence Dossier | `¥3 × 法人 + bundle_units` | 10法人 + deal bundle 1,000 units | 約¥3,030/案件 | 実装済みbundle単価に寄せる |
| DD Case Dossier | 同上 | 30法人 + case bundle 3,333 units | 約¥10,089/案件 | `¥30,000-100,000/案件` と言うなら別商品定義が必要 |
| Widget Business | 月額 | 10,000 req含む | ¥10,000/月 | API tierではなく埋込配布形態 |
| Widget Whitelabel | 月額 | 100,000 req fair use | ¥30,000/月 | 高利用時の容量管理が必要 |
| Evidence API/MCP | `¥3/billable unit` | 1,000-10,000 req | ¥3,000-¥30,000 | 開発者流入と組込導線 |

導入障壁と対策:

| 障壁 | 影響 | 対策 |
|---|---|---|
| JGrants API/MCPが無料で存在する | 補助金検索だけでは弱い | JGrants外の自治体、融資、税制、行政処分、採択、除外理由を売る |
| `¥3/billable unit` が安すぎて価値が伝わらない | 「ただの安いAPI」に見える | 出典、checksum、snapshot、監査ログを前面に出す |
| 士業法・税務判断リスク | 顧客が判断代替と誤解する | 「候補探索・出典提示・条件照合」までに限定 |
| 顧問先情報の入力抵抗 | CSV投入を嫌がる | 最初は匿名ラベル、都道府県、業種、従業員数だけでデモ |
| 請求不安 | 従量課金で警戒される | cost preview、月額cap、`X-Cost-Cap-JPY` を見せる |
| 公開表記のdrift | 信頼低下 | 無料枠、件数、tool数、endpoint数を正本から生成する |

営業資料は文章で説得しない。必ず「入力 -> 出力 -> 出典 -> 監査情報」の順で見せる。

良いデモ:

```text
入力:
  顧問先CSV 10社
  columns: name_label, prefecture, jsic_major, employee_count, target_types

操作:
  1. cost preview: row_count=10, estimated_yen=30 を表示
  2. commit=true で ZIP を生成
  3. 1社分の候補CSVを開き、上位5件を確認
  4. 1制度を full detail で開き、source_url / fetched_at / checksum を表示
  5. 除外理由・defer理由・免責文を確認
  6. 同じ条件を saved search にして、次回以降は差分通知にする

クロージング:
  AI回答ではなく、顧問先ごとの証拠パケットを納品する。
```

悪いデモ:

```text
入力: 会社の悩み
出力: AIが自然文でアドバイス
```

悪いデモはLLM単体と差が出ないため、作らない。

## 14. 法務・表示・信頼性

jpcite は「士業判断の代替」ではなく、「士業・開発者・AIエージェントが検証可能な出典付き事実層」として売る。

公開数値は必ず次を併記する。

```text
metric_name
denominator
numerator
as_of
source
exclusions
refresh_frequency
```

「全件」「100%」「完全」「即時」「必ず」「保証」「最安」「No.1」「政府公認」「公式DB」は、根拠資料と法務レビューがない限り使用しない。

AIコスト削減は保証値ではなく、条件付きベンチ結果としてのみ表示する。比較対象、モデル、価格取得日、為替、プロンプト、対象クエリ数、外部ツール費、jpcite利用料、キャッシュ・無料枠の扱いを併記する。

公共情報については、次の文言を標準にする。

> 公的機関の公開情報を当社が取得・整理したものであり、政府または所管機関の公認・保証を意味しません。二次利用時は出典表示、加工表示、第三者権利の確認を行ってください。

### 14.1 主なリスク

| リスク | 避けること | 方針 |
|---|---|---|
| 弁護士法 | 違法/適法、勝ち筋、法律相談、契約・申立書作成 | 判例・法令・行政処分の検索と関連条文候補に留める |
| 税理士法 | 税額確定、節税判断、申告書記載、税務相談 | 一般情報・候補制度・出典提示に留め、税理士確認を明示 |
| 行政書士法 | 申請書作成、提出代行、許認可の具体相談 | 公募要領URL、締切、必要書類チェックリストまで |
| 景表法 | 100%正確、完全網羅、必ず採択、LLMより正確 | as of日付、収録範囲、欠落、既知制約を明示 |
| 個人情報 | 顧問先名や税務情報を不用意にログ保存 | 入力禁止、PII redaction、保持期間、漏えいSOP |
| 政府データ利用 | 政府公認・公式DB誤認、出典/加工表示漏れ | source_url、license、加工表示、第三者権利注意 |
| MCP security | token passthrough、SSRF、session hijacking | read-only、最小権限、audience/resource検証、監査ログ |

参照:

- [弁護士法 e-Gov](https://laws.e-gov.go.jp/api/1/lawdata/324AC1000000205)
- [税理士法 e-Gov](https://laws.e-gov.go.jp/api/1/lawdata/326AC1000000237)
- [行政書士法 e-Gov](https://laws.e-gov.go.jp/api/1/lawdata/326AC1000000004)
- [公共データ利用規約 PDL 1.0](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)

### 14.2 禁止表現

- AIが申請可否を判定
- この補助金は受給できます
- この税制特例は適用できます
- 法的に問題ありません
- 申請書を自動作成
- 監査調書を自動生成
- 必ず採択
- 採択率保証
- 失格を防ぐ
- 100%正確
- 全件出典
- 一次資料100%
- 無制限
- 最安
- No.1
- 政府公認
- 公式データベース
- ChatGPT/Claudeは使えない

### 14.3 推奨表現

- 公開一次資料に基づく検索結果を返します。
- 候補制度、関連条文、出典URL、取得時刻、checksumを提示します。
- 適用可否・申請可否・税務判断は、所管窓口または有資格者が確認してください。
- 機械的な条件照合であり、法的・税務・行政手続上の確定判断ではありません。
- 収録範囲、欠落、更新遅延は透明性ページで開示します。

### 14.4 免責文案

サイト上部または検索結果直下:

> jpciteは、日本の公的制度に関する公開情報を検索し、出典URL・取得時刻・照合理由を提示する情報提供サービスです。法律相談、税務相談、申請書類の作成・提出代行、受給可否・採択可否の保証は行いません。最終判断は一次資料、所管窓口、または資格を有する専門家に確認してください。

API/MCPレスポンス:

```json
"_disclaimer": {
  "type": "information_only",
  "message": "本レスポンスは公開一次資料の検索・照合結果であり、法律相談、税務相談、申請書作成・提出代行、受給・採択の保証ではありません。source_url、source_fetched_at、corpus_snapshot_idを確認し、確定判断は所管窓口または有資格者へ確認してください。"
}
```

## 15. サイト修正方針

| 対象 | 現状リスク | 修正方針 |
|---|---|---|
| `site/about.html` | meta description に「一次資料100%」が残る | 分母・算定日つきの `source_url付与率` に変更 |
| `site/about.html` | 「AIから検索できる」は許容。ただしAI回答サービスに見える | 「AI回答ではなく出典付き検索API」を追記 |
| `site/about.html` | 「適合判定の層」は強い | 「候補探索・条件照合の層」に弱める |
| `site/index.html` | 「申請可否を機械判定」は強すぎる | 「公開条件を機械照合」に変更 |
| `site/index.html` | 「監査資料の自動生成」は士業・監査表現として強い | 「監査資料に貼れる出典・スナップショット情報を出力」に変更 |
| `site/index.html` | 損失額やAI比較に根拠が必要 | 根拠がなければ削除、または「リスクになり得る」に弱める |
| `site/pricing.html` / `docs/pricing.md` / `config.py` | 無料枠が `50 req/月` と `3 req/日` で混在 | どちらかに統一し、正本から生成 |
| `site/advisors.html` | 「景表法・士業法に準拠」は強い | 「準拠を目的とした表示設計」に弱める |
| `site/advisors.html` | 成約手数料がある場合に「広告ではありません」は危険 | 手数料、表示順位基準、資格確認方法、利益相反を明記 |
| ToS / サイト | 「No server-side LLM」と「AI生成物が含まれる場合」の整合 | サーバー側LLMを使わない範囲、顧客側LLM連携時の下流表示義務を分けて書く |
| ToS | LLM組込時の下流表示義務が不足 | 免責・出典・取得時刻の併示義務を追加 |
| 士業紹介 | 紹介・広告・利益相反・個人情報の整理が必要 | 報酬条件、非保証、資格確認、個人情報同意を別条項化 |

## 16. 営業文言

### 補助金コンサル向け

ChatGPTで文章は作れます。ただ、頻繁に変わる公募・締切・併用リスク・一次資料URLを、顧問先ごとに追い続けるのは別問題です。jpcite は顧問先プロフィールから候補制度、締切、排他ルール、採択例を API/MCP で返します。

### 税理士向け

顧問先からの「使える税制・補助金はありますか」に、措置法・税制特例・制度情報・出典URLつきで初期回答を作れます。税務判断は先生、一次資料の収集と候補抽出は jpcite です。

### 開発者向け

日本の補助金・融資・税制・法令を LLM に読ませるための MCP / REST API です。JGrants の単純ラッパーではなく、一次資料URL、採択例、行政処分、法人番号、法令メタデータを横断して返します。

### VC / M&A 向け

法人番号から、公的に確認できる採択履歴、行政処分、インボイス登録、関連制度をまとめて取得できます。商業DBの代替ではなく、DDチェックリストに入れる公的データの補完APIです。

## 17. 実行順序

最初にやることは機能追加ではない。信頼性の穴を塞ぎ、LLMとの差別化をサイトとAPIに反映する。

1. 公開文言を「AI回答」から「出典付き検証API」に変更する。
2. endpoint数、tool数、件数、無料枠、料金の正本を決め、README/site/docs/OpenAPI/runtimeのdriftを止める。
3. `source_url` 欠損、broken URL、manifest drift、tool数 drift を修正する。
4. Evidence Packet の標準schemaを決め、既存 `source_manifest`、`citations.verify`、v2 envelopeに接続する。
5. `audit_seal` と `corpus_snapshot_id` を paid endpoint に接続する。
6. Stripe従量課金のlive smokeとreconciliationを通す。
7. 既存 `bulk_evaluate` を使い、顧問先CSV一括スクリーニングのデモを作る。
8. JGrants API/MCPとの差分比較を公開する。
9. 既存 saved search / webhook / digest をEvidence Packet参照つきにする。
10. 既存DD exportをDD Evidence Dossierとして見せる。
11. Healthcare / Real Estate 等の縦展開は core green 後に限定開放する。

## 18. 判定KPI

期間ではなく、状態で判定する。以下が緑になれば良くなっている。赤ならそこを直す。

| 領域 | 緑の状態 | 赤の状態 |
|---|---|---|
| 公開数値 | README、site、manifest、OpenAPI、runtimeで件数・tool数・endpoint数・料金が一致 | どこかで数字がズレる |
| 無料枠 | `50 req/月` または `3 req/日` の一方に統一される | docsと実装で無料枠が割れる |
| citation | high-stakes responseがsource_urlなしで返らない | 根拠なしの断定が出る |
| freshness | `fetched_at` と `verified_at` が分離して表示される | 取得日を更新日・検証日と誤認させる |
| checksum | 重要sourceでchecksumが返る | 後から同一性を検証できない |
| provenance | 重要fieldにsource_id/source_urlがある | fact単位の根拠がない |
| diff | 差分API/RSSが非空で、変更理由が追える | `am_amendment_diff` が空、または使われていない |
| audit seal | paid responseを後から検証できる | 監査証跡がDBにあるだけで返っていない |
| billing | usage_eventsとStripeがreconcileできる | 請求漏れ・過請求を検知できない |
| batch | 既存CSV/JSON listがEvidence列つきで処理できる | 1件ずつ手で投げる必要がある、または証拠列がない |
| token_cost | Evidence Packetに圧縮メトリクスが入り、paired A/Bで検証できる | 「何%削減」の根拠がない |
| webhook | 保存条件の差分を `diff_id` / packet参照つきで外部へ送れる | 顧客が毎回見に来る必要がある、またはpayloadだけでは検証できない |
| UI | 画面追加なしで価値が届く | 新規画面が必要になる |
| legal | 申請可否・税務判断・法律判断をしない | 判断・保証に見える表現が残る |
| revenue | API/batch/webhook/DD/Widgetで売上が立つ | 単純Q&A課金に依存する |

## 19. 参考資料

ローカル:

- [README.md](../../README.md)
- [docs/pricing.md](../pricing.md)
- [docs/long_term_strategy.md](../long_term_strategy.md)
- [docs/go_no_go_gate.md](../go_no_go_gate.md)
- [docs/per_tool_precision.md](../per_tool_precision.md)
- [docs/hallucination_guard_methodology.md](../hallucination_guard_methodology.md)
- [docs/confidence_methodology.md](../confidence_methodology.md)
- [docs/compliance/terms_of_service.md](../compliance/terms_of_service.md)
- [docs/compliance/privacy_policy.md](../compliance/privacy_policy.md)
- [docs/audit_trail.md](../audit_trail.md)
- [site/about.html](../../site/about.html)
- [site/trust.html](../../site/trust.html)
- [site/sources.html](../../site/sources.html)
- [src/jpintel_mcp/mcp/server.py](../../src/jpintel_mcp/mcp/server.py)
- [src/jpintel_mcp/api/main.py](../../src/jpintel_mcp/api/main.py)
- [src/jpintel_mcp/api/billing.py](../../src/jpintel_mcp/api/billing.py)
- [src/jpintel_mcp/api/audit_log.py](../../src/jpintel_mcp/api/audit_log.py)
- [src/jpintel_mcp/api/_audit_seal.py](../../src/jpintel_mcp/api/_audit_seal.py)

外部:

- [jpcite about](https://jpcite.com/about)
- [jpcite pricing](https://jpcite.com/pricing)
- [jpcite trust](https://jpcite.com/trust)
- [JGrants API docs](https://developers.digital.go.jp/documents/jgrants/api/)
- [JGrants MCP server](https://github.com/digital-go-jp/jgrants-mcp-server)
- [OpenAI Connectors in ChatGPT](https://help.openai.com/en/articles/11487775-connectors-in-chatgpt)
- [OpenAI API Pricing](https://openai.com/api/pricing/)
- [Claude Web Search](https://support.anthropic.com/en/articles/10684626-enabling-and-using-web-search)
- [Anthropic Claude Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Anthropic MCP connector](https://docs.anthropic.com/en/docs/agents-and-tools/mcp-connector)
- [Google Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Tavily Pricing](https://www.tavily.com/pricing)
- [消費者庁 比較広告](https://www.caa.go.jp/policies/policy/representation/fair_labeling/representation_regulation/comparative_advertising/)
- [消費者庁 表示に関するQ&A](https://www.caa.go.jp/policies/policy/representation/fair_labeling/faq/representation/)
- [公共データ利用規約 PDL 1.0](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [弁護士法 e-Gov](https://laws.e-gov.go.jp/api/1/lawdata/324AC1000000205)
- [税理士法 e-Gov](https://laws.e-gov.go.jp/api/1/lawdata/326AC1000000237)
- [行政書士法 e-Gov](https://laws.e-gov.go.jp/api/1/lawdata/326AC1000000004)

## 20. 最終方針

jpcite の継続価値は、LLMより上手に文章を書くことではない。LLMの回答を、一次資料、取得日時、checksum、snapshot、provenance、監査ログ、差分通知で検証可能にすることである。

この方向なら、ClaudeやChatGPTは敵だけではない。顧客が使う表現レイヤーになる。jpciteはその下で、LLMが毎回取りに行くには面倒で、業務上は必ず必要になる根拠データを供給する。

したがって、今後の優先順位は次の通り。

1. AI回答を売らない。Evidence Packetを売る。
2. 単発検索を売らない。batch、saved search、webhook、監査ログを売る。
3. 件数を誇らない。品質指標と既知制約を公開する。
4. 申請可否・税務判断・法律判断をしない。候補探索・条件照合・出典提示に留める。
5. LLMを競合としてだけ見ない。jpciteを呼び出す上位の表現レイヤーとして使う。
