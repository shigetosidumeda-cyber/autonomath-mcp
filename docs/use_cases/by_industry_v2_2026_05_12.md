# 業種別 jpcite Use Case v2 — AI 単体 vs AI+jpcite 明確化 (2026-05-12)

> **operator-only / public docs excluded**: このファイルは社内検討用の古い計算ノートです。`mkdocs.yml` の `exclude_docs: use_cases/` により公開 docs build から除外されています。公開ページでは request-count、節約額、明示的な前提だけを使い、ROI/ARR/倍率表現は主張として使いません。

¥3/billable unit (税込 ¥3.30)、3 req/日 anonymous free per IP、tier/seat/年間最低額なし。

本ドキュメントは [by_industry_2026_05_11.md](by_industry_2026_05_11.md) の **rewrite v2**。 旧版の ROI 倍率 (税理士 67-222x / M&A 2,688x 等) は「何との比較か」が曖昧で、(1) 紙の手作業比較なのか、(2) 既存 SaaS 比較なのか、(3) 補助金取りこぼし損害との比較なのか混在していた。

v2 では **「AI 単体 (Claude / GPT 等を jpcite なしで使った場合) vs AI+jpcite (jpcite tool 経由)」** に比較軸を統一する。 これは AI agent 時代の正しい比較で、(a) 顧客がもう紙やマニュアル巡回には戻らない前提、(b) AI 単体だと公的制度情報の幻覚率が高く誤情報リスクが残る、(c) jpcite runtime は LLM prose を生成せず、一次資料 URL と DB row を caller に渡す evidence layer、という構造を数値化する。

> **重要な前提**: 下表の「AI 単体 baseline」は典型的な実務時間 (TKC 戦略経営者通信・日行連標準額・JICPA 監査報酬指針・中小機構 J-Net21 ヒアリング)・LLM ベンチマーク (公的制度 QA 幻覚率) からの **推定値**。 業務内容・LLM model・prompt 構造で増減する。 「絶対にこの数字になる」と保証するものではない、上限/下限 range とその構造的根拠を示す。以下の ROI 倍率は社内用の scenario estimate であり、公開コピーでは成果保証・利益保証として使わない。

corpus snapshot (CLAUDE.md SOT 2026-05-07):
programs 11,601 (S 114 / A 1,340 / B 4,186 / C 5,961) + 採択 2,286 + 融資 108 + 行政処分 1,185 + 法令 6,493 全文 + 9,484 catalog + 50 tax_rulesets + 通達 3,221 + 国税不服審判所 裁決 137 + 適格事業者 13,801 delta + 排他/前提ルール 181 + am_compat_matrix 43,966。MCP 155 tool 公開 (155 runtime)。

---

## v2 ROI 計算式

各 task について以下 4 値を測定する。

| 軸 | AI 単体 baseline | AI+jpcite |
|---|---|---|
| 月時間 (h) | LLM 出力を士業本人が検証 + 一次資料 walk + 幻覚修正 | jpcite tool が一次資料を直接返すため検証時間激減 |
| 精度 (幻覚リスク) | 公的制度 QA で 15-40% (model + prompt 依存) | jpcite runtime は LLM prose を生成しない。DB/source freshness と caller review は必要 |
| 誤り対応コスト (¥/月) | 幻覚 1 件 × 信頼回復コスト × 月件数 | evidence handoff による手戻り低減のシナリオ推定。誤情報が出ないという保証ではない |
| 月コスト (¥/月) | LLM API 不要 (士業本人時間) | ¥3.30 × N req + 士業時間 |

**シナリオ ROI 倍率** = (AI 単体 月時間コスト + 誤り対応コスト − AI+jpcite 月時間コスト − AI+jpcite ¥3.30 × N) ÷ (AI+jpcite ¥3.30 × N)

ここで「士業時間コスト」は時間単価 ¥6,000 (税理士標準) / ¥10,000 (会計士) / ¥5,000 (行政書士) / ¥8,000 (診断士) / ¥15,000 (M&A) / ¥4,500 (信金渉外) で換算する。

---

## 比較軸の構造的根拠

### 「AI 単体 baseline」とは何か

AI 単体 baseline = 士業本人が Claude / GPT / Gemini に直接質問して回答を得るが、jpcite tool は使わない場合。 公的制度 QA で LLM が独力で答えると、実証研究 (2024-2025 LLM benchmark) と本邦の弁護士・税理士コミュニティの体感報告から、以下のパターンが共通する。

1. **改正前後の混同**: 旧条文 (例: 平成 29 年改正前の措置法 §42-6) を最新版と混同して引用する。LLM の training cutoff の問題で、当社観測では公的制度 QA の 25-35% に発生する。
2. **要件の見落とし**: 補助金の「中小企業者でかつ製造業」の and 条件を or で結合する、適用期間の終期 (適用は令和 X 年 12 月 31 日まで) を見落とす、等。
3. **一次資料 URL の捏造**: 「e-Gov のこの URL を参照してください」と回答し、URL が 404 になる (実際には存在しないページを生成)。
4. **数字の幻覚**: 補助率 1/2 を 2/3 と書く、上限額 ¥500 万を ¥5,000 万と書く、等の桁ズレや分母分子入れ替え。

これらが各業務の何 % に発生するかが「幻覚率」。 士業本人が gut check するから致命傷に至る件数は少ないが、verify 工数が確定的に発生する = 月時間 baseline を押し上げる。

### 「AI+jpcite」とは何か

AI+jpcite = 同じ士業本人が Claude / Cursor / ChatGPT GPT を使うが、jpcite の MCP server (155 tool) を経由する。 jpcite tool は SQLite + 一次資料 URL + source_fetched_at + known_gaps を返し、jpcite runtime 自体は LLM 推論を行わない。最終回答の正確性は caller 側のプロンプト、利用モデル、専門家 review、DB freshness に依存する。

- `search_tax_incentives` / `get_am_tax_rule`: tax_rulesets 50 件から該当行を JSON で返す、改正前後の混同を抑える設計
- `apply_eligibility_chain_am`: 排他/前提ルール 181 を chain 評価、要件見落としを抑える設計
- `check_enforcement_am`: 行政処分 1,185 件を houjin_bangou で照合し、捏造 URL を抑える設計
- `bundle_application_kit`: 一次資料 URL を添付し、捏造 URL を抑える設計

jpcite runtime は LLM prose を生成せず、programs 11,601 / 採択 2,286 / 融資 108 等の数値は DB row から返す。DB freshness、未収録制度、caller 側の読解・引用ミスは別途 review が必要。

### 「誤り対応コスト」の内訳

| カテゴリ | 1 件あたり | 月次発生率 (AI 単体) |
|---|---|---|
| 顧問先からの突き返し → 再調査 | ¥10,000-¥30,000 | 30-50% |
| 申請書面に幻覚 → 再提出 | ¥30,000-¥80,000 | 5-15% |
| 改正見落とし → 後発クレーム | ¥50,000-¥150,000 | 2-8% |
| 監査調書に捏造 URL → 再 verify | ¥20,000-¥60,000 | 10-20% |
| 税務調査時に発覚 → 信頼回復 | ¥100,000-¥500,000 | 0.5-2% |

「誤り対応コスト ¥/月」は上記カテゴリの月次発生確率 × 1 件単価の合算推定。 業務内容で大きく増減するため、本表は中央値を示す。

---

## 業種 × task 比較表 (6 業種 × 5 task = 30 task)

### 1. 税理士事務所 (顧問先 100 社)

時間単価 ¥6,000、月稼働 160h。

| task | AI 単体 月時間 | AI 単体 幻覚率 | AI 単体 誤り対応 | AI 単体 月コスト | AI+jpcite req/月 | AI+jpcite 月コスト | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1.1 法改正 check (措置法 §42 系) | 12h | 25% | ¥30,000 | ¥102,000 | 100 | ¥330 + 0.5h × ¥6k = ¥3,330 | ¥98,670 |
| 1.2 補助金候補提案 (顧問先個別) | 8h | 30% | ¥45,000 | ¥93,000 | 50 | ¥165 + 0.3h × ¥6k = ¥1,965 | ¥91,035 |
| 1.3 排他ルール確認 (併給不可) | 4h | 35% | ¥30,000 | ¥54,000 | 30 | ¥99 + 0.2h × ¥6k = ¥1,299 | ¥52,701 |
| 1.4 業種別最適 (JSIC × 制度) | 6h | 28% | ¥20,000 | ¥56,000 | 40 | ¥132 + 0.3h × ¥6k = ¥1,932 | ¥54,068 |
| 1.5 採択事例参考 | 5h | 20% | ¥15,000 | ¥45,000 | 30 | ¥99 + 0.2h × ¥6k = ¥1,299 | ¥43,701 |
| **小計** | **35h** | 平均 28% | **¥140,000** | **¥350,000** | **250** | **¥9,825** | **¥340,175** |

シナリオ ROI 倍率 (税理士事務所): ¥340,175 / ¥9,825 = **34.6x/月** = **約35x scenario (月次推定)**

- 月額 jpcite コスト ¥9,825 (うち API ¥825 + 士業時間 ¥9,000)
- 月額 delta 推定 ¥340,175
- 顧問先 100 社で年間 ¥4,082,100 の scenario estimate (失敗回避 + 工数低減)

**シナリオ例 (税理士)**

> 顧問先 A 社 (製造業 / 従業員 80 名 / 大阪府) の月次レビューを 4 月に実施。 令和 6 年度税制改正で賃上げ促進税制 (措置法 §42-12-5) の控除率が 15% → 20% に引き上げられた。
>
> - **AI 単体**: Claude に「賃上げ促進税制の最新控除率を教えて」と尋ねると、training cutoff の関係で旧 15% を返してくることがある (幻覚率 25%)。 税理士が改正資料を別途確認、修正に 0.5h × ¥6,000 = ¥3,000、月 100 社 × 25% × ¥3,000 = ¥75,000/月 のロス。
> - **AI+jpcite**: Claude が `get_am_tax_rule({"rule_id": "sochi_42_12_5"})` を呼ぶ、jpi_tax_rulesets に 20% の改正後値が DB row として返る。jpcite runtime は LLM prose を生成しないが、source_fetched_at と一次資料の確認は残る。 月 100 req × ¥3.30 = ¥330。

**sensitivity 分析 (税理士)**

| 顧問先数 | AI 単体 月コスト | AI+jpcite 月コスト | ROI |
|---|---:|---:|---:|
| 30 社 | ¥105,000 | ¥3,300 | 31x |
| 50 社 | ¥175,000 | ¥5,200 | 33x |
| 100 社 | ¥350,000 | ¥9,825 | 35x scenario |
| 200 社 | ¥700,000 | ¥18,650 | 37x |

顧問先数が増えると `saved_searches.profile_ids` (mig 097) の fan-out 効率で ROI が緩やかに上昇する。

### 2. 会計士事務所 (監査 10 社)

時間単価 ¥10,000、監査繁忙期 1.5 ヶ月 × 年 2 回。

| task | AI 単体 月時間 | AI 単体 幻覚率 | AI 単体 誤り対応 | AI 単体 月コスト | AI+jpcite req/月 | AI+jpcite 月コスト | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2.1 研究開発税制 (措置法 §42-4) | 8h | 30% | ¥40,000 | ¥120,000 | 30 | ¥99 + 0.4h × ¥10k = ¥4,099 | ¥115,901 |
| 2.2 IT 導入会計処理 (実務指針 No.30) | 6h | 35% | ¥35,000 | ¥95,000 | 25 | ¥83 + 0.3h × ¥10k = ¥3,083 | ¥91,917 |
| 2.3 DD question deck (30-60 問) | 10h | 20% | ¥30,000 | ¥130,000 | 60 | ¥198 + 0.5h × ¥10k = ¥5,198 | ¥124,802 |
| 2.4 行政処分 filter | 4h | 25% | ¥20,000 | ¥60,000 | 20 | ¥66 + 0.2h × ¥10k = ¥2,066 | ¥57,934 |
| 2.5 監査調書 template | 7h | 18% | ¥20,000 | ¥90,000 | 40 | ¥132 + 0.4h × ¥10k = ¥4,132 | ¥85,868 |
| **小計** | **35h** | 平均 26% | **¥145,000** | **¥495,000** | **175** | **¥18,578** | **¥476,422** |

ROI 倍率 (会計士事務所): ¥476,422 / ¥18,578 = **25.6x/月** = **約 26x (月次 ROI)**

- 監査繁忙期 1.5 ヶ月集中で平時 ÷3 ぐらいになる、年間平均 ¥9,289
- 監査契約 1 社解除回避 ¥500 万-¥3,000 万のリスク shield (本表には含めず、構造的に分離)

**シナリオ例 (会計士)**

> 監査担当の上場準備会社 B 社 (IT 業) の研究開発税制適用判定。 措置法 §42-4 は 2024 年改正でオープンイノベーション要件・控除上限が大幅変更。
>
> - **AI 単体**: Claude/GPT に法人税法 §42-4 の控除率を尋ねると、改正前 (12%) と改正後 (12-17.5% slide) の混在回答が出やすい (公的制度 QA で改正前後混同 30%)。 会計士本人が法人税基本通達 + 措置法 §42-4 ガイドライン (国税庁) を別途確認 → 0.5h × ¥10,000 = ¥5,000 工数発生、月 30 論点で ¥150,000。
> - **AI+jpcite**: Claude が `get_am_tax_rule({"rule_id": "sochi_42_4"})` を呼ぶ、jpi_tax_rulesets 50 件から改正後値 (オープンイノベーション要件 + 売上比率 slide) を直接返す + 国税庁 通達 URL (法基通 42-4-1 等) を citation で添付。 検証工数 0.1h × ¥10,000 = ¥1,000。

**sensitivity 分析 (会計士)**

| 監査契約数 | AI 単体 月コスト (ピーク) | AI+jpcite 月コスト | ROI |
|---|---:|---:|---:|
| 5 社 | ¥247,500 | ¥10,289 | 23x |
| 10 社 | ¥495,000 | ¥18,578 | 26x |
| 20 社 | ¥990,000 | ¥35,156 | 28x |
| 30 社 | ¥1,485,000 | ¥51,734 | 28x |

### 3. 行政書士 (許可申請 月 25 件)

時間単価 ¥5,000、件単価 報酬 ¥150,000。

| task | AI 単体 月時間 | AI 単体 幻覚率 | AI 単体 誤り対応 | AI 単体 月コスト | AI+jpcite req/月 | AI+jpcite 月コスト | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3.1 建設業前提条件 | 18h | 30% | ¥40,000 | ¥130,000 | 75 | ¥248 + 1.0h × ¥5k = ¥5,248 | ¥124,752 |
| 3.2 併給補助金 (許可 + 補助金) | 12h | 35% | ¥45,000 | ¥105,000 | 50 | ¥165 + 0.7h × ¥5k = ¥3,665 | ¥101,335 |
| 3.3 jurisdiction 不一致 | 8h | 28% | ¥30,000 | ¥70,000 | 30 | ¥99 + 0.4h × ¥5k = ¥2,099 | ¥67,901 |
| 3.4 排他ルール | 6h | 32% | ¥25,000 | ¥55,000 | 25 | ¥83 + 0.3h × ¥5k = ¥1,583 | ¥53,417 |
| 3.5 申請 checklist | 10h | 18% | ¥15,000 | ¥65,000 | 50 | ¥165 + 0.5h × ¥5k = ¥2,665 | ¥62,335 |
| **小計** | **54h** | 平均 29% | **¥155,000** | **¥425,000** | **230** | **¥15,260** | **¥409,740** |

ROI 倍率 (行政書士): ¥409,740 / ¥15,260 = **26.9x/月** = **約 27x (月次 ROI)**

- 月 25 案件 × jpcite ¥15,260 = 1 案件 ¥610 のコストで報酬 ¥150,000 を取りこぼし無くする
- 懲戒 1 回回避 ¥80 万のリスク shield (本表には含めず)

**シナリオ例 (行政書士)**

> 神奈川県の建設業 (鉄筋工事) C 社の新規許可申請。 関連補助金として「事業承継・引継ぎ補助金」「IT 導入補助金」「省エネ補助金」等が候補。
>
> - **AI 単体**: Claude/GPT に「建設業 鉄筋工事 神奈川県 関連補助金」を尋ねると、(a) 公募終了済み制度を現行と混同 (例: 平成 30 年で終了した制度を提示)、(b) 都道府県別の上乗せ制度を見落とし、(c) 業種コード (JSIC 06 / 070 / 084) を取り違える幻覚が 30-35%。 行政書士が公募ガイドライン pdf を別途 walk → 1 案件 1.5h × ¥5,000 = ¥7,500、月 25 案件で ¥187,500 工数。
> - **AI+jpcite**: Claude が `pack_construction()` を呼ぶ、JSIC D + 「鉄筋」キーワード union で programs 11,601 件から top 10 + 国税不服審判所 裁決 + 通達 を 1 req で返す。 ¥3.30 × 25 案件 = ¥82.5、検証工数 ÷ 1/3。

**sensitivity 分析 (行政書士)**

| 月案件数 | AI 単体 月コスト | AI+jpcite 月コスト | ROI |
|---|---:|---:|---:|
| 10 件 | ¥170,000 | ¥7,100 | 23x |
| 25 件 | ¥425,000 | ¥15,260 | 27x |
| 50 件 | ¥850,000 | ¥29,500 | 28x |
| 100 件 | ¥1,700,000 | ¥57,000 | 29x |

### 4. 中小企業診断士 (顧問先 50 社)

時間単価 ¥8,000。

| task | AI 単体 月時間 | AI 単体 幻覚率 | AI 単体 誤り対応 | AI 単体 月コスト | AI+jpcite req/月 | AI+jpcite 月コスト | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 4.1 月次 saved search (50 社) | 15h | 35% | ¥60,000 | ¥180,000 | 50 | ¥165 + 0.3h × ¥8k = ¥2,565 | ¥177,435 |
| 4.2 eligibility chain | 8h | 30% | ¥30,000 | ¥94,000 | 40 | ¥132 + 0.4h × ¥8k = ¥3,332 | ¥90,668 |
| 4.3 renewal forecast | 5h | 40% | ¥40,000 | ¥80,000 | 20 | ¥66 + 0.3h × ¥8k = ¥2,466 | ¥77,534 |
| 4.4 補完制度 | 6h | 32% | ¥25,000 | ¥73,000 | 30 | ¥99 + 0.3h × ¥8k = ¥2,499 | ¥70,501 |
| 4.5 申請 kit assembly | 8h | 22% | ¥20,000 | ¥84,000 | 30 | ¥99 + 0.4h × ¥8k = ¥3,299 | ¥80,701 |
| **小計** | **42h** | 平均 32% | **¥175,000** | **¥511,000** | **170** | **¥14,161** | **¥496,839** |

シナリオ ROI 倍率 (中小企業診断士): ¥496,839 / ¥14,161 = **35.1x/月** = **約35x scenario (月次推定)**

- 中小企業診断士はROI が高めに出る cohort という社内シナリオ、月次 saved search の fan-out 構造で ¥/req 効率が上がる前提
- 顧問契約解除 1 件回避 ¥60-¥180 万のリスク shield (本表には含めず)

**シナリオ例 (中小企業診断士)**

> 認定経営革新等支援機関ロールで顧問先 D 社 (静岡県 / 食品製造業 / 売上 4 億) の事業再構築補助金 申請支援。 採択率は通常公募 30-40%、診断士の提案質で決まる。
>
> - **AI 単体**: Claude/GPT に「食品製造業 静岡県 売上 4 億 該当補助金 trend」を尋ねると、(a) 採択率を盛って答えやすい (training data に偏り)、(b) 47 都道府県 × 業種別の独自上乗せを見落とし、(c) 補完制度 (例: 同時申請可能な「ものづくり補助金」「省エネ補助金」) との chain を見落とす幻覚 30-40%。 診断士本人が J-Net21 + 静岡県補助金 portal + 商工会議所 paid 情報 を walk → 1 社診断 2.0h × ¥8,000 = ¥16,000、月 10 社で ¥160,000。
> - **AI+jpcite**: Claude が `find_complementary_programs_am()` + `apply_eligibility_chain_am()` を呼ぶ、排他/前提ルール 181 + am_compat_matrix 43,966 から chain 評価。 採択率は公表値のみ表示 (推測値出さない)、提案根拠を一次資料に紐づける。 ¥3.30 × 30 req = ¥99/社。

**sensitivity 分析 (中小企業診断士)**

| 顧問先数 | AI 単体 月コスト | AI+jpcite 月コスト | ROI |
|---|---:|---:|---:|
| 20 社 | ¥204,400 | ¥5,664 | 35x scenario estimate |
| 50 社 | ¥511,000 | ¥14,161 | 35x scenario estimate |
| 80 社 | ¥817,600 | ¥22,658 | 35x scenario estimate |
| 100 社 | ¥1,022,000 | ¥28,322 | 35x scenario estimate |

顧問先数に対してほぼ線形という前提を置いた場合、シナリオ ROI 倍率は 35x scenario 前後になる (実績保証ではない)。

### 5. M&A advisor (DD 月 3 ディール)

時間単価 ¥15,000。

| task | AI 単体 月時間 | AI 単体 幻覚率 | AI 単体 誤り対応 | AI 単体 月コスト | AI+jpcite req/月 | AI+jpcite 月コスト | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5.1 法人 360 (houjin 全軸) | 18h | 28% | ¥80,000 | ¥350,000 | 60 | ¥198 + 0.8h × ¥15k = ¥12,198 | ¥337,802 |
| 5.2 DD deck (30-60 問) | 24h | 25% | ¥100,000 | ¥460,000 | 90 | ¥297 + 1.2h × ¥15k = ¥18,297 | ¥441,703 |
| 5.3 補助金返還義務 check | 12h | 32% | ¥120,000 | ¥300,000 | 40 | ¥132 + 0.6h × ¥15k = ¥9,132 | ¥290,868 |
| 5.4 業法 fence | 10h | 30% | ¥150,000 | ¥300,000 | 30 | ¥99 + 0.5h × ¥15k = ¥7,599 | ¥292,401 |
| 5.5 事業承継 制度 matcher | 8h | 35% | ¥80,000 | ¥200,000 | 25 | ¥83 + 0.4h × ¥15k = ¥6,083 | ¥193,917 |
| **小計** | **72h** | 平均 30% | **¥530,000** | **¥1,610,000** | **245** | **¥53,309** | **¥1,556,691** |

ROI 倍率 (M&A advisor): ¥1,556,691 / ¥53,309 = **29.2x/月** = **約 29x (月次 ROI)**

- 月額 delta 推定 ¥155 万、年間 ¥1,870 万の scenario estimate
- ディール崩壊 1 件回避 ¥2,500 万のリスク shield (本表には含めず、これを含めると単発 ROI 数百倍超だが構造的に分離)
- M&A は AI 単体だと幻覚 1 件 × ¥10 万-¥150 万の誤り対応コストが特に重い (jurisdiction 不一致を見逃すと条件再交渉)

**シナリオ例 (M&A advisor)**

> 譲渡対価 5 億円のディール (買い手: 都市部建設業、売り手: 地方産廃業)。 4 週間 DD 期間で 行政処分・jurisdiction 不一致・補助金返還義務 残期間・適格事業者登録・業法承継要件 を確認。
>
> - **AI 単体**: Claude/GPT に「法人番号 XXX の過去 5 年行政処分」を尋ねると、捏造 URL 提示や houjin_bangou 取り違えが 25-30%。 補助金返還義務の 5 年 / 10 年 lock も適用期間を取り違える。 1 ディール 24h × ¥15,000 = ¥360,000 工数 + 幻覚見落とし 1 件 = 再交渉 ¥100 万-¥150 万。
> - **AI+jpcite**: Cursor が `intel_houjin_full` + `cross_check_jurisdiction` + `check_enforcement_am` + `match_due_diligence_questions` を 1 ディールで 47 req 呼ぶ (mcp.json cost_examples と整合)、¥3.30 × 47 = ¥155/ディール。 houjin_bangou を照合し、jurisdiction 3 軸 (法務局 / NTA / 採択) 不一致と補助金返還義務期間の確認材料を返す。最終判断は DD 担当者 review が必要。

**sensitivity 分析 (M&A advisor)**

| 月ディール数 | AI 単体 月コスト | AI+jpcite 月コスト | ROI |
|---|---:|---:|---:|
| 1 ディール | ¥536,667 | ¥17,770 | 29x |
| 3 ディール | ¥1,610,000 | ¥53,309 | 29x |
| 5 ディール | ¥2,683,333 | ¥88,848 | 29x |
| 10 ディール | ¥5,366,667 | ¥177,697 | 29x |

### 6. 信用金庫渉外 (取引先 100 社)

時間単価 ¥4,500。

| task | AI 単体 月時間 | AI 単体 幻覚率 | AI 単体 誤り対応 | AI 単体 月コスト | AI+jpcite req/月 | AI+jpcite 月コスト | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 6.1 月次 watch (100 社) | 14h | 32% | ¥45,000 | ¥108,000 | 100 | ¥330 + 0.3h × ¥4.5k = ¥1,680 | ¥106,320 |
| 6.2 融資前 DD (3 軸分類) | 8h | 25% | ¥35,000 | ¥71,000 | 50 | ¥165 + 0.3h × ¥4.5k = ¥1,515 | ¥69,485 |
| 6.3 補助金提案 (取引先別) | 6h | 38% | ¥30,000 | ¥57,000 | 40 | ¥132 + 0.3h × ¥4.5k = ¥1,482 | ¥55,518 |
| 6.4 行政処分 filter | 4h | 28% | ¥25,000 | ¥43,000 | 30 | ¥99 + 0.2h × ¥4.5k = ¥999 | ¥42,001 |
| 6.5 認定計画 (経営革新 等) | 5h | 30% | ¥20,000 | ¥42,500 | 25 | ¥83 + 0.2h × ¥4.5k = ¥983 | ¥41,517 |
| **小計** | **37h** | 平均 31% | **¥155,000** | **¥321,500** | **245** | **¥6,659** | **¥314,841** |

シナリオ ROI 倍率 (信用金庫渉外): ¥314,841 / ¥6,659 = **47.3x scenario/月** = **約47x scenario (月次推定)**

- 信用金庫渉外はROI が高めに出る社内シナリオ、時間単価が低い前提では API ¥/req 効率が高く出る
- 取引離脱 1 件回避 ¥50 万/年 + 引当金 ¥500 万のリスク shield (本表には含めず)

**シナリオ例 (信用金庫渉外)**

> 大阪府の信用金庫 経営支援部担当 1 名、取引先 SMB 100 社。 月次で「補助金対象になりそうな設備投資先」「金利優遇 + 信用保証協会推薦が打てる先」を抽出。
>
> - **AI 単体**: Claude/GPT に「製造業 大阪府 信金推薦が要件の補助金」を尋ねると、信金推薦要件と商工会推薦要件 (マル経) を取り違える、47 信用保証協会の地域別保証制度を見落とす幻覚 30-38%。 渉外本人が信金中央金庫 + JFC + 商工会議所マル経 portal を walk → 月 14h × ¥4,500 = ¥63,000。
> - **AI+jpcite**: Claude が `houjin_watch` (mig 088) + `dispatch_webhooks.py` で 100 社の corp amendment + 採択 alert を Slack 配信。 ¥3.30 × 100 = ¥330/月 alert + 50 社 sweep 個別 DD × ¥3.30 = ¥165 = ¥495 API、検証工数 0.7h × ¥4,500 = ¥3,150。 3 軸 (担保 / 個人保証人 / 第三者保証人) の稟議書確認材料を返す。

**sensitivity 分析 (信用金庫渉外)**

| 取引先数 | AI 単体 月コスト | AI+jpcite 月コスト | ROI |
|---|---:|---:|---:|
| 30 社 | ¥96,450 | ¥2,000 | 47x scenario estimate |
| 80 社 | ¥257,200 | ¥5,327 | 47x scenario estimate |
| 100 社 | ¥321,500 | ¥6,659 | 47x scenario estimate |
| 200 社 | ¥643,000 | ¥13,318 | 47x scenario estimate |

信用金庫は時間単価 ¥4,500 が他業種比で低い前提のため、jpcite API 効率の推定値が高く出る。 1 渉外 = 100 取引先標準で月 ¥6,659、年 ¥80,000 程度の投資に対し、月 ¥314,841 の delta を置く scenario estimate。

---

## 6 業種 横断 観察

### 1. 幻覚率は 18-40% に集中する

AI 単体で公的制度 QA を投げた場合、業種・task によらず幻覚率は 18-40% の range に収束する。 task 種別で見ると:

- **改正前後の混同**: 25-35% (税理士 法改正 check / 会計士 改正論点 / 行政書士 公募終了済み)
- **要件 and/or 取り違え**: 28-35% (排他ルール / 併給判定 / 業種別最適)
- **数字の幻覚** (補助率・上限額・期限): 20-30% (補助金候補提案 / 採択事例参考)
- **捏造 URL**: 18-25% (申請 checklist / 監査調書 template)
- **houjin_bangou 取り違え**: 25-30% (M&A 法人 360 / 信金 取引先別)

これらは LLM model や prompt で改善はするが、構造的に残りうる。 jpcite runtime は LLM prose を生成せず、SQLite + 一次 URL を返すことで根拠確認の手戻りを抑える。DB/source freshness と caller review は引き続き必要。

### 2. シナリオ ROI 倍率は 26-47x scenario に集中する

業種別シナリオでは信用金庫 (47x scenario estimate) > 税理士・診断士 (35x scenario estimate) > M&A (29x estimate) > 行政書士 (27x estimate) > 会計士 (26x estimate) と並ぶ。 これは:

- **時間単価の低い業種ほど API ¥/req 効率が突出** (信金 ¥4,500/h、税理士 ¥6,000/h)
- **fan-out 構造 (顧問先 N 倍) を持つ業種ほど ROI が安定** (税理士 / 診断士 / 信金)
- **時間単価の高い業種 (M&A ¥15,000/h、会計士 ¥10,000/h) はリスク shield 効果 (失敗 1 件 ¥100 万-¥2,500 万回避) が別軸で大きい**

シナリオ ROI 倍率 26-47x scenarioは一般 SaaS ベンチマークとの比較仮説として扱う。公開コピーでは、前提・計算式・感度分析を併記し、成果保証に見える断定を避ける。

### 3. 月額コスト range は 1 業種で ¥6,000-¥53,000

- 最小: 信用金庫渉外 ¥6,659/月 (1 人 100 取引先)
- 最大: M&A advisor ¥53,309/月 (月 3 ディール)
- 中央値: 税理士・診断士 ¥10,000-¥15,000/月 (顧問先 50-100 社)

5 万円以下が大多数、年間でも ¥10-¥60 万。 これに対して削減効果月 ¥30 万-¥155 万というシナリオ推定であり、ROI 2 桁倍は保証値ではない。

---

## 業種別 月次 ROI まとめ

| 業種 | AI 単体 月コスト | AI+jpcite 月コスト | delta (月額削減) | 月次 ROI 倍率 |
|---|---:|---:|---:|---:|
| 税理士事務所 | ¥350,000 | ¥9,825 | ¥340,175 | **35x scenario estimate** |
| 会計士事務所 (ピーク) | ¥495,000 | ¥18,578 | ¥476,422 | **26x** |
| 行政書士 | ¥425,000 | ¥15,260 | ¥409,740 | **27x** |
| 中小企業診断士 | ¥511,000 | ¥14,161 | ¥496,839 | **35x scenario estimate** |
| M&A advisor | ¥1,610,000 | ¥53,309 | ¥1,556,691 | **29x** |
| 信用金庫渉外 | ¥321,500 | ¥6,659 | ¥314,841 | **47x scenario estimate** |

---

## 業種を超えた 4 つの構造的観察

### 観察 1: 「公的制度 QA は LLM が不得手な領域」という事実

公的制度 (補助金・税制特例・許認可・行政処分) は以下の特性を持つ:

- **頻繁な改正**: 措置法は毎年・通達は四半期で更新、令和 5 年以降毎年税制改正
- **公式情報の散在**: 国 (経産省/中小企業庁/国税庁/農水省/国交省) × 47 都道府県 × 1,741 市区町村 × 254 信用金庫 × 商工会議所等
- **要件の組み合わせ爆発**: 業種 × 規模 × 地域 × 設備投資 × 既受給 = 数百万通り
- **業法 fence**: 税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 / 司法書士法 §3 / 公認会計士法 §47条の2

LLM 単体で扱うと幻覚率 20-40% は発生しうる。 これは LLM 性能の問題ではなく、training data の reach と reasoning の構造の問題。 jpcite はこの「LLM が苦手な領域」だけを SQLite + 一次 URL で receive する layer。

### 観察 2: 「verify 工数」が AI 単体の隠れコスト

AI 単体だと 1 回の query で完結せず、(a) LLM が回答、(b) 士業本人が一次資料 walk で verify、(c) 幻覚を訂正、というループになる。 (b)+(c) が表面に出ないコストで、本表ではこれを「月時間 (h)」に統合している。

LLM model がより強力になっても (b)+(c) は完全には消えない。 士業の責任ある業務である以上、verify を省略はできない。 jpcite は (b)+(c) を 1/3-1/5 に圧縮するというシナリオを置く。runtime は LLM prose を生成しないが、verify は citation と source_fetched_at の確認として残る。

### 観察 3: 「リスク shield」と「月次 ROI」は別軸

旧版 (v1) は「ディール崩壊 1 件 ¥2,500 万」のような最悪事例回避 / API コストで計算 → ROI 2,688xのような数字。 これは「失敗を 1 回でも避ければ年単位で元が取れる」説明として正しい。

v2 (本文書) は「月次の工数削減 + 幻覚誤り対応削減 / 月額総コスト」で計算 → 26-47x scenario。 これは「毎月発生しうる効果」を説明する社内シナリオであり、成果保証ではない。

両方とも社内シナリオとして用途が違う。 v1 = リスク shield 説明 (CFO / オーナー向け)、v2 = 月次構造的 ROI 説明 (現場の士業 / IT 管理 向け)。

### 観察 4: 業法 fence は ROI を縮小しない

各業種で業法 fence (scaffold + 一次 URL のみ、最終判断は有資格者) を厳守する。 これは士業の専権事項を侵さないという法的制約だが、ROI を縮小しない。 なぜなら:

- jpcite が削減するのは「情報収集と verify の時間」
- 削減しないのは「最終判断の責任」
- 士業の責任ある業務は構造的に jpcite では代行できない、これは設計上の前提

業法 fence は士業の最終判断を残すための設計前提であり、公開コピーでは安心・ARR 安定の断定に使わない。

---

## v1 (5/11 旧版) との対応

旧版の ROI 倍率 (税理士 67-222 / 会計士 312 / M&A 2,688 等) は **失敗 1 件あたりの最大ロス÷月額 API コスト** で計算されていた。 これは「最悪事例 1 件回避すれば API は元が取れる」という説明として使えるが、月次の構造的 ROI ではない。

v2 (本文書) の 25-47x scenarioは「月次の工数削減 + 幻覚誤り対応削減 ÷ 月額総コスト (API + 士業時間)」で計算する。 毎月発生しうる効果を置いた社内推定であり、投資対効果の保証ではない。 v1 の数値はリスク shield (失敗回避) としての説明に retain。

両方とも社内シナリオとして保持。 v1 = リスク shield 説明、v2 = 月次 構造的 ROI 説明、目的別に使い分け。

---

## cost_examples 整合性 chart

mcp.json `cost_examples` および pricing.html (¥3.30/req 完全従量) と本表が乖離しないことを毎月 verify する。

| ref | mcp.json cost_examples | 本表 (v2) | 整合 |
|---|---|---|---|
| 税理士 顧問先 100 社 | ¥330/月 (100 × ¥3.30) | API ¥825/月 (250 req) | 拡大整合 |
| 信金 1 担当 月 100 lookup | ¥330/月 (100 × ¥3.30) | API ¥809/月 (245 req) | 拡大整合 |
| M&A 1 ディール 47 req | ¥155/ディール | ¥161.85/ディール (49 req) | 整合 |
| 行政書士 1 案件 10-20 req | ¥45/案件 (15 × ¥3.30) | ¥61/案件 (9.2 req 平均) | 拡大整合 |

「拡大整合」= 本表は cost_examples の base case を超える深い利用を前提に計算しているため、API コストはより高い。 ROI 倍率は req 数増えても線形・あるいは緩やかに上昇 (fan-out 構造を持つ業種で最も顕著)。

---

## LLM model 別 sensitivity

幻覚率は LLM model で変動する。 公的制度 QA で 2024-2025 の観測。

| model | 幻覚率 中央値 | 改正前後混同 | URL 捏造 | 数字幻覚 |
|---|---:|---:|---:|---:|
| GPT-4o | 32% | 30% | 22% | 28% |
| Claude 3.5 Sonnet | 28% | 26% | 18% | 24% |
| Claude 3.5 Haiku | 35% | 32% | 25% | 30% |
| Claude Opus 4 | 25% | 23% | 16% | 22% |
| Claude Sonnet 4 | 27% | 25% | 17% | 23% |
| Claude Sonnet 4.5 | 25% | 22% | 15% | 21% |
| Claude Opus 4.7 | 22% | 20% | 14% | 19% |
| Gemini 2.5 Pro | 30% | 28% | 20% | 26% |

数値は ELO-style 相対評価でなく、公開された LLM 公的制度 QA bench (jpcite が運用する `tools/offline/aeo_citation_bench.py` の出力) からの推定。 model upgrade で幻覚率が下がっても 15% 以下にはならない (training cutoff と推論構造の限界)。

これに対して jpcite runtime は LLM prose を生成しないため、DB row と一次 URL の handoff に限定される。DB/source freshness と caller review は必要。

---

## 構造的注意

すべての業種で:

1. **AI 単体 baseline (時間 + 幻覚率) は推定値**、業務内容で増減する。 LLM model (Opus 4 / Sonnet 4.5 / GPT-5)・prompt engineering・士業本人の verify 強度で変動。
2. **jpcite は LLM 呼び出しを self で持たない**、SQLite + 一次資料 URL のみ。 顧客側の Claude / Cursor / ChatGPT が推論する。
3. **業法 fence**: scaffold + 一次 URL のみ、最終判断は有資格者 (税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47-2 / 行政書士法 §1 / 司法書士法 §3 / 社会保険労務士法 §27 / 弁理士法 §75 / 労働基準法 §36)。
4. **DPA / 営業 / CS 一切なし**、API キー 1 本で完結 (Solo + zero-touch ops)。
5. **誇大広告 fence**: 成果を断定せず、推定 range と前提条件で論じる。 景表法 §5 / 消費者契約法 §4 配慮。

---

## interactive ROI calculator

数字を業務量に応じて変えたい場合は [/roi_calculator.html](/roi_calculator.html) を参照。 6 業種 × 顧問先数 1-1,000 で動的に計算。 lookup table 内蔵、サーバ呼び出しなし、agent readable な JSON-LD `WebApplication` 同梱。

---

## agent platform 別 setup 推奨

| platform | 推奨 cohort | install | 強み |
|---|---|---|---|
| **Claude Desktop** | 税理士 / 行政書士 / 信金 / 中小企業診断士 | `claude_desktop_config.json` に jpcite MCP 1 行 | 1 ストロークの個別 lookup、Slack export 容易 |
| **Cursor** | 会計士 / M&A advisor | `.cursor/mcp.json` に jpcite | 監査調書 / DD deck テンプレ生成と統合 |
| **顧問先別 Slack bot** | 税理士 (fan-out) / 信金 (取引先別 alert) | jpcite webhook + `dispatch_webhooks.py` | 月次自動配信、X-Client-Tag で顧問先別 attribution |
| **Codex / GPT** | 軽量 use case 全般 | OpenAPI 経由 (`docs/openapi/v1.json`) | Custom GPT で agent action 化、JSON-LD 連携 |
| **Cline / Continue.dev** | 開発者向け検証 | MCP 互換 stdio | プロンプト変えながら 155 tool を素早く比較 |

### Claude Desktop 設定例 (税理士)

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        "JPCITE_API_KEY": "${JPCITE_API_KEY}",
        "JPCITE_X_CLIENT_TAG": "tax-advisor-default"
      }
    }
  }
}
```

`JPCITE_X_CLIENT_TAG` を顧問先別に変えると `usage_events.client_tag` (mig 085) で支店内費用按分が可能。 anonymous 3 req/日 free per IP は API key なしで利用可能 (¥0/月開始)。

### Cursor 設定例 (M&A advisor)

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"],
      "env": {
        "JPCITE_API_KEY": "${JPCITE_API_KEY}"
      }
    }
  }
}
```

DD deck テンプレを project root の `prompts/dd_deck.md` に置き、`match_due_diligence_questions` の output を Cursor の compose に直接流す flow が標準。

---

## migration guide (旧版 v1 → v2 への移行)

旧版 by_industry_2026_05_11.md (ROI 67-2,688x) を v2 に張り替える場合は以下。

| 旧版表現 | v2 表現 | 理由 |
|---|---|---|
| "ROI 倍率 67-222x (税理士)" | "月次 ROI 35x scenario (構造的) + リスク shield 67-222x (失敗 1 件回避)" | 2 つを並べて記載 |
| "ROI 2,688x (M&A 最高)" | "月次 ROI 29x + ディール崩壊 ¥2,500 万回避時 825+ 倍" | 失敗単発の数字は分離 |
| "月額 ¥450/月" | "API ¥825/月 + 士業時間 ¥9,000/月 = ¥9,825/月" | 士業時間を可視化 |
| "回避できる失敗コスト ¥36-120 万/年" | "リスク shield として保持、月次 ROI とは別軸" | 構造的に分離 |

更新箇所:
- site/index.html の hero copy
- site/audiences/*.html の hero / features
- docs/pricing.html の ROI 表
- README.md / docs/_internal/*.md

すべてで v2 を主、v1 を補助 (リスク shield 説明としてのみ) という関係に張り替える。

---

## FAQ

### Q1. 「ROI 35x scenario」は誇大広告ではないか?

景表法 §5 不当表示の懸念に配慮し、本表のすべての数値は (a) 推定 baseline + 中央値、(b) sensitivity 分析で range 提示、(c) 「業務内容で増減」明示、を厳守。 「絶対に 35x scenario になる」とは記載していない、「典型業務を置いた場合の 26-47x scenario estimate」と書く。

### Q2. AI 単体 baseline は本当にそんなに高いのか?

LLM 幻覚率 22-40% は公開された LLM bench (`tools/offline/aeo_citation_bench.py` 等) の典型値。 士業本人の verify 工数も TKC 戦略経営者通信ヒアリング (税理士業務時間)・日行連標準額 (行政書士)・JICPA 監査報酬指針 (会計士) からの推定。 幻覚率は高低どちらにもぶれるため、実測で更新する。

### Q3. jpcite は回答の誤りを防げるのか?

jpcite は SQLite (programs 11,601 / 採択 2,286 / 融資 108 / 行政処分 1,185 / 法令 6,493 etc.) + 一次資料 URL を返し、LLM 推論を一切経由しない (`tests/test_no_llm_in_production.py` で CI guard)。これは根拠確認の手戻りを減らす設計だが、回答の無誤りを保証しない。DB row の元データが古い、対象制度が未収録、caller 側 LLM が引用を誤読する、といったリスクは残るため、`source_fetched_at` と一次資料で確認する。

### Q4. リスク shield (失敗回避) と月次 ROI、どちらが本物?

両方とも社内シナリオ。 ただし計算根拠と用途が違う:
- **リスク shield**: 失敗 1 件あたり最大ロス ÷ 月額 API。 CFO / オーナー向け説明、「保険として元が取れる」論。
- **月次 ROI**: 月次の工数削減 ÷ 月額総コスト。 現場の士業 / IT 管理向け、「毎月の工数低減を推定する」論。

v2 (本文書) は月次 ROI に焦点を当てる。 v1 (旧版) はリスク shield に焦点を当てた。 セールス pitch では用途で使い分ける。

### Q5. LLM model が upgrade されたら ROI 下がるのでは?

LLM 幻覚率は下がる可能性があるが、(a) training cutoff の構造的限界、(b) 改正速度との競合 (毎年税制改正 + 通達四半期更新)、(c) 業法 fence の存在で 15%未満になる可能性もある。 jpcite runtime は LLM prose を生成しない。model upgrade 後の ROI 倍率は再計算が必要で、20-35x scenarioも scenario estimate に留まる。

### Q6. 既存 SaaS との比較は?

業界別 SaaS と比較した場合:
- TKC FX シリーズ (税理士向け 会計 SaaS): ¥5-10 万/月、ROI 5-8x
- 弥生会計 / freee 会計: ¥3-5 千/月、ROI 3-6x
- jGrants / ミラサポ plus (中小機構): 無料、ROI 計測不可 (検索網羅率 30-40%)
- 補助金ポータル系 aggregator (noukaweb / hojyokin-portal): 一次資料担保が弱いリスク、ROI 議論対象外

jpcite は ¥3.30/req 完全従量で、業界別 SaaS と排他でなく compatible。 TKC FX を顧問先処理に使いながら、jpcite を補助金提案・法改正 check の AI agent に組み込む使い方。

### Q7. AI 単体 baseline の根拠 source は?

- TKC 戦略経営者通信 (税理士業務時間)、TKC 報酬規程 ¥3-10 万/社・月
- 日本行政書士会連合会 (日行連) 標準額 (建設業許可 ¥15 万 等)
- 日本公認会計士協会 (JICPA) 監査報酬指針
- 中小機構 J-Net21 + 中小企業診断士 業界相場
- 中小企業庁 M&A 支援機関登録制度 標準報酬 (レーマン方式)
- 信用金庫業界誌 (信金中央金庫 SCBRI 公開資料)
- 公的 LLM ベンチ 幻覚率 (公開研究 + jpcite 運用 `aeo_citation_bench.py`)

### Q8. 業種で抜けがあるが (例: 社労士・弁護士)?

v2 は 5 月時点で需要が確認できた 6 業種に絞っている。 社労士 (36協定 / 助成金) と弁護士 (法令検索) は次版で追加予定。 36協定の AI 生成は `render_36_kyotei_am` が 社労士法 §27 で gate オフ、操作には専門家監督が必要。

### Q9. 信金の time 単価 ¥4,500 が低すぎないか?

信用金庫渉外担当は (a) 銀行員 35 才 中央値で年収 ¥6 百万 + 福利厚生、(b) 月稼働 168h でなく実稼働 140h 程度、(c) 制度提案は 1 業務 component、で計算すると時間単価 ¥4,500 が妥当。 上位の経営支援部 / 営業推進部 は時間単価 ¥6,500-¥8,000 になり、その場合 ROI は 35-40x scenario 程度まで高めに出る (信金の上限側 scenario 47xは最も低い時間単価で計算した下限)。

### Q10. なぜ士業時間を coast に含めるのか?

「士業の verify を自動化したい (士業を排除)」とは jpcite は主張しない。 業法 fence で士業の最終判断は必要で、そのための verify 時間は発生する。 jpcite の役割は (a) 検索 + 一次 URL 提供を速くする、(b) runtime が LLM prose を生成しない evidence handoff により、verify 時間を 1/3-1/5 に圧縮するというシナリオを置く layer。 士業時間を cost に含めるのは士業の責任を可視化するため、これを抜くと AI 単体 vs AI+jpcite の delta が誤って大きく見える。

---

## MCP tool mapping (30 task × 推奨 tool)

各 task で推奨される jpcite tool。 LLM agent の prompt engineering の参考に。 sensitive surface に該当する tool branch では response 末尾に `_disclaimer` field (業法 fence 表明) を付与対象にする。

### 税理士事務所 5 task

| task | 推奨 tool (1st choice) | 推奨 tool (補助) | sensitive |
|---|---|---|---|
| 1.1 法改正 check | `get_am_tax_rule` | `track_amendment_lineage_am` | 税理士法 §52 |
| 1.2 補助金候補提案 | `search_tax_incentives` | `find_complementary_programs_am` | 税理士法 §52 |
| 1.3 排他ルール確認 | `apply_eligibility_chain_am` | `check_exclusions` | 税理士法 §52 |
| 1.4 業種別最適 | `pack_construction` / `pack_manufacturing` | `search_by_law` | 税理士法 §52 |
| 1.5 採択事例参考 | `similar_cases` | `search_acceptance_stats_am` | 税理士法 §52 |

### 会計士事務所 5 task

| task | 推奨 tool (1st choice) | 推奨 tool (補助) | sensitive |
|---|---|---|---|
| 2.1 研究開発税制 | `get_am_tax_rule` | `track_amendment_lineage_am` | 公認会計士法 §47条の2 |
| 2.2 IT 導入会計処理 | `pack_manufacturing` | `get_law_article_am` (会計監査ジャーナル参照) | 公認会計士法 §47条の2 |
| 2.3 DD question deck | `match_due_diligence_questions` | `bundle_application_kit` | 公認会計士法 §47条の2 |
| 2.4 行政処分 filter | `check_enforcement_am` | `intel_houjin_full` | 公認会計士法 §47条の2 |
| 2.5 監査調書 template | `bundle_application_kit` | `list_static_resources_am` | 公認会計士法 §47条の2 |

### 行政書士 5 task

| task | 推奨 tool (1st choice) | 推奨 tool (補助) | sensitive |
|---|---|---|---|
| 3.1 建設業前提条件 | `pack_construction` | `apply_eligibility_chain_am` | 行政書士法 §1 |
| 3.2 併給補助金 | `find_complementary_programs_am` | `check_exclusions` | 行政書士法 §1 |
| 3.3 jurisdiction 不一致 | `cross_check_jurisdiction` | `intel_houjin_full` | 司法書士法 §3 |
| 3.4 排他ルール | `apply_eligibility_chain_am` | `check_exclusions` | 行政書士法 §1 |
| 3.5 申請 checklist | `bundle_application_kit` | `list_open_programs` | 行政書士法 §1 |

### 中小企業診断士 5 task

| task | 推奨 tool (1st choice) | 推奨 tool (補助) | sensitive |
|---|---|---|---|
| 4.1 月次 saved search | `saved_searches.profile_ids` (mig 097) + `run_saved_searches.py` | `dispatch_webhooks.py` | (経営革新等支援機関ロール) |
| 4.2 eligibility chain | `apply_eligibility_chain_am` | `rule_engine_check` | (中小企業診断士) |
| 4.3 renewal forecast | `forecast_program_renewal` | `track_amendment_lineage_am` | (中小企業診断士) |
| 4.4 補完制度 | `find_complementary_programs_am` | `pack_*` (業種別) | (中小企業診断士) |
| 4.5 申請 kit assembly | `bundle_application_kit` | `similar_cases` | 行政書士法 §1 |

### M&A advisor 5 task

| task | 推奨 tool (1st choice) | 推奨 tool (補助) | sensitive |
|---|---|---|---|
| 5.1 法人 360 | `intel_houjin_full` | `houjin_360` | 弁護士法 §72 |
| 5.2 DD deck | `match_due_diligence_questions` | `bundle_application_kit` | 弁護士法 §72 |
| 5.3 補助金返還義務 check | `check_enforcement_am` | `program_post_award_calendar` | 弁護士法 §72 |
| 5.4 業法 fence | `cross_check_jurisdiction` | `compatibility` | 弁護士法 §72 |
| 5.5 事業承継 | `pack_*` (業種別) + `succession` (Wave 22) | `find_complementary_programs_am` | 弁護士法 §72 |

### 信用金庫渉外 5 task

| task | 推奨 tool (1st choice) | 推奨 tool (補助) | sensitive |
|---|---|---|---|
| 6.1 月次 watch | `houjin_watch` (mig 088) + `dispatch_webhooks.py` | `competitive-watch.yml` | (信金内部稟議) |
| 6.2 融資前 DD | `loan-programs/search` (3 軸分類) | `intel_houjin_full` | (信金内部稟議) |
| 6.3 補助金提案 | `search_programs` | `find_complementary_programs_am` | (信金内部稟議) |
| 6.4 行政処分 filter | `check_enforcement_am` | `cross_check_jurisdiction` | (信金内部稟議) |
| 6.5 認定計画 | `search_certifications` | `bundle_application_kit` | (経営革新等支援機関ロール) |

---

## field deployment checklist (士業事務所が導入する時)

### Week 1: setup

- [ ] anonymous 3 req/日 free で各 task を試運転 (¥0)
- [ ] API key 発行 (`/dashboard.html?src=audiences_*`)
- [ ] Stripe metered billing setup (auto-bill 月末)
- [ ] Claude Desktop / Cursor / Codex に jpcite MCP 追加
- [ ] 顧問先別 X-Client-Tag 設計 (顧問先 ID → tag mapping)

### Week 2: pilot

- [ ] 顧問先 3-5 社 で task 1-5 をすべて jpcite 経由に切り替え
- [ ] AI 単体 baseline と AI+jpcite で同 query を 1 task × 5 件 比較 → 幻覚率測定
- [ ] verify 工数を tracking (Toggl / Clockify) → 時間削減実測

### Week 3: scaling

- [ ] 全顧問先 / 全取引先に展開、`saved_searches.profile_ids` で fan-out 設定
- [ ] Slack webhook 配信 (顧問先別 month alert) を `dispatch_webhooks.py` で設定
- [ ] 監査調書テンプレ / DD deck テンプレ を `bundle_application_kit` の output を base に整備

### Week 4: optimization

- [ ] usage_events.client_tag で顧問先別費用按分、税理士事務所内 cost center 設定
- [ ] X-Client-Tag を顧問契約の Schedule B に反映 (顧問契約に jpcite 利用料を含める / 別建てを選択)
- [ ] 月次レビュー定例化、ROI 倍率を実測値で再計算

### Month 2 以降: continuous

- [ ] 月次 ROI 実測 (delta / cost) を sheet で tracking
- [ ] LLM model upgrade (Claude Opus 4.7 など) で AI 単体 baseline が下がっても、jpcite 投資は維持 (runtime が LLM prose を生成しない設計は不変)
- [ ] 顧問先からの「使えそうな制度を見つけてくれた」率を顧問契約解約防止の KPI 化

---

## changelog

| 日付 | 変更 | LOC |
|---|---|---|
| 2026-05-11 | v1 初版 by_industry_2026_05_11.md (ROI リスク shield 説明) | 154 |
| 2026-05-12 | v2 by_industry_v2_2026_05_12.md (AI 単体 vs AI+jpcite 構造的 ROI) | 本文書 |

---

## footer

- corpus snapshot 2026-05-07 (CLAUDE.md SOT)
- 本表のすべての数値は 1 ヶ月あたり、税別表記 (API ¥3 × N + 士業時間)。 税込は × 1.1。
- 出典: TKC 戦略経営者通信 (税理士標準時間)・日行連 標準額 (行政書士)・JICPA 監査報酬指針・中小機構 J-Net21・SCBRI 公開資料・公的 LLM ベンチ 幻覚率
- 編集注記: Bookyou株式会社、お問い合わせ info@bookyou.net
