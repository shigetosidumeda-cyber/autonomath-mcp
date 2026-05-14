# 顧問先 100 社の月次 review を月次 API fee delta で補助する公的情報 API ——「jpcite」が拓く税理士事務所の生産性

顧問先 100 社の月次 review で使う公的情報を低い API fee で取得できる、機械整形 API・MCP サーバ「jpcite」が登場した。税理士法 §52 の fence を保ちつつ、月次伴走の調査・根拠確認を補助する。

## 月次 review の現場で起きていること

税理士事務所において、顧問先 1 社あたりの月次 review に要する時間は、平均で 2〜4 時間とされる。この時間の大半は試算表確認や仕訳承認といったコア業務ではなく、補助金・税制優遇・業法改正情報の monitoring に費やされている。

具体的には、中小企業庁の補助金公募情報、国税庁の通達、各都道府県の制度融資、e-Gov の法令改正、デジタル庁の DX 投資促進税制更新 ——これらを月次で全顧問先に対して横断する作業は、有資格者の生産性を圧迫する。100 社を担当する中堅事務所では、月次 review の前提調査だけでも大きな確認負荷になり得る。

クラウド会計ベンダーは試算表自動化を実現したが、「制度情報の構造化された取得」までは射程に入れていない。電子申告 e-Tax は申告書作成、TKC の OMS は文書管理が中心であり、公的情報を artifact として取り扱う層は空白のままだった。

## jpcite が提供する artifact レイヤ

jpcite は、国・地方自治体・独立行政法人の公開情報を機械可読 JSON / Markdown に整形し、API と MCP (Model Context Protocol) サーバ経由で提供する Bookyou 株式会社のプロダクトである。

主な対象データセットは以下のとおり。

- 中小企業庁・経済産業省の補助金公募情報 (整形後 302 paths)
- 国税庁の通達・FAQ
- e-Gov 法令データ (税法・会社法・労働法等)
- 各都道府県の制度融資・補助金
- 独立行政法人 (中小機構・JETRO 等) の支援制度

これらを recipe 単位で artifact 化しており、「顧問先 100 社のセグメント別補助金候補抽出」「税制優遇 eligibility chain 評価」「制度融資 maturity 棚卸し」など、税理士業務に直結するレシピが提供されている。

API 価格は ¥3/billable unit、匿名利用は IP あたり 3 request/日まで無料、超過分は完全従量課金。MCP server 経由であれば Claude Desktop や Cursor IDE から自然言語で artifact を引き出せる。

## 税理士法 §52 fence の設計

最も重要なのは、jpcite が「税理士業務」を侵食しない設計を貫いている点である。

税理士法 §52 は税理士業務 (税務代理・税務書類作成・税務相談) の独占を定めており、AI ベンダーが個別顧客の税務判断を提供することは違法となる。jpcite はこの fence を次の三層で防護している。

第一に、artifact はあくまで「公開情報の機械整形」であり、特定顧客の事実関係を前提とした判断を提供しない。recipe 出力は常に「該当しうる候補リスト」+ 出典 URL であり、結論ではない。

第二に、すべての API response に disclaimer header (`X-Jpcite-Disclaimer: machine-formatted public information; final judgment by licensed professional`) が付与される。SDK / MCP server も同 disclaimer を必ず表示する。

第三に、税理士業界向け recipe (r01 顧問先補助金抽出、r03 M&A DD、r07 認定支援機関伴走) は、税理士が「自身の業務遂行のために」用いる前提で設計されており、無資格者が直接顧客に提供する利用形態を ToS で禁止している。

## 節約額試算 (旧称 ROI 試算)

100 社を月次 review する中堅事務所のケースで試算する。

- 従来: 補助スタッフ 2 名 × 月給 ¥250,000 = 月次 API fee delta
- jpcite 導入後: API 約 ¥5,940 + 有資格者の最終確認 30 分/社 × 100 社 × 時給 ¥8,000 = 月次 API fee delta

月次 API fee delta ×12 = 年間参考額のAPI fee delta reference。人員再配置・業務成果・専門判断の価値は本比較に含みません。

レシピ r01「顧問先補助金抽出」は https://jpcite.com/docs/recipes/r01 で実装手順と recipe payload を公開している。実装イメージは「顧問先 CSV を input、補助金 candidate JSON + 根拠 URL + 申請期限 を output」とシンプルである。

## 業界誌読者へ

jpcite を提供する Bookyou 株式会社 (T8010001213708、東京都文京区小日向 2-22-1) は、税理士法 §52 fence を最優先で設計したアーキテクチャを公開している。recipe / disclaimer / TOS の全文は https://jpcite.com/docs/ で読める。

導入時の問い合わせは info@bookyou.net で受け付ける。営業電話は行わず、organic outreach のみで運営する方針であり、事務所側のペースで検証していただきたい。

なお、本稿で紹介した artifact は公開情報の機械整形であり、最終判断は資格専門家にご相談ください。
