---
title: "Recipes"
date_modified: "2026-05-13"
license: "PDL v1.0 / CC-BY-4.0"
---

# Recipes

jpcite の recipe は、公開情報の根拠確認、法人・制度・登録情報の照合、AI ツール連携を短時間で試すための実装例です。このページは recipe の索引です。個別の手順、前提、出力例は各 recipe ページで確認してください。

## 業務別 recipe

- [r01-tax-firm-monthly-review](r01-tax-firm-monthly-review/) - 税理士事務所の月次レビュー前に、法人・制度・税務関連の確認材料を整理
- [r02-pre-closing-subsidy-check](r02-pre-closing-subsidy-check/) - 決算前に補助金・制度候補を確認し、顧問先への質問を準備
- [r03-sme-ma-public-dd](r03-sme-ma-public-dd/) - SME M&A の公開情報 DD 用 evidence packet を作成
- [r04-shinkin-borrower-watch](r04-shinkin-borrower-watch/) - 信金・金融機関の取引先モニタリング候補を根拠付きで整理
- [r05-gyosei-licensing-eligibility](r05-gyosei-licensing-eligibility/) - 行政書士の許認可・制度確認の初回ヒアリング材料を作成
- [r06-sharoushi-grant-match](r06-sharoushi-grant-match/) - 社労士向けに助成金・労務関連制度の確認候補を整理
- [r07-shindanshi-monthly-companion](r07-shindanshi-monthly-companion/) - 中小企業診断士の月次伴走で使う制度・公開情報メモを作成
- [r08-benrishi-ip-grant-monitor](r08-benrishi-ip-grant-monitor/) - 弁理士・知財支援向けに IP 関連制度の更新を確認
- [r09-bpo-grant-triage-1000](r09-bpo-grant-triage-1000/) - BPO で多数企業の補助金候補を一次トリアージ
- [r10-cci-municipal-screen](r10-cci-municipal-screen/) - 商工会議所・自治体の管内企業向け制度案内候補を作成

## データ照合・監視 recipe

- [r11-ec-invoice-bulk-verify](r11-ec-invoice-bulk-verify/) - EC・経理の適格請求書発行事業者番号を一括確認
- [r12-audit-firm-kyc-sweep](r12-audit-firm-kyc-sweep/) - 監査法人向けの KYC・独立性確認材料を整理
- [r13-shihoshoshi-registry-watch](r13-shihoshoshi-registry-watch/) - 司法書士向けの登記・法人情報ウォッチ
- [r14-public-bid-watch](r14-public-bid-watch/) - 公共調達・入札情報の監視
- [r24-houjin-6source-join](r24-houjin-6source-join/) - 法人番号を起点に 6 系統の公開情報を結合
- [r25-adoption-bulk-export](r25-adoption-bulk-export/) - 採択履歴などの公開情報を一括 export
- [r26-enforcement-rss-slack](r26-enforcement-rss-slack/) - 行政処分・公表情報の RSS / Slack 通知
- [r27-law-amendment-program-link](r27-law-amendment-program-link/) - 法改正と制度ページの関連確認
- [r28-edinet-program-trigger](r28-edinet-program-trigger/) - EDINET 情報をきっかけに制度・公開情報確認を開始
- [r29-municipal-grant-monitor](r29-municipal-grant-monitor/) - 自治体補助金の更新監視
- [r30-invoice-revoke-watch](r30-invoice-revoke-watch/) - 適格事業者登録の抹消・変更を検知

## AI ツール連携 recipe

- [r16-claude-code-30sec](r16-claude-code-30sec/) - Claude Code から jpcite を呼び出す最短セットアップ
- [r17-chatgpt-custom-gpt](r17-chatgpt-custom-gpt/) - ChatGPT Custom GPT 連携
- [r18-cursor-mcp-setup](r18-cursor-mcp-setup/) - Cursor MCP 連携
- [r19-codex-agents-sdk](r19-codex-agents-sdk/) - Codex / Agents SDK 連携
- [r20-continue-cline](r20-continue-cline/) - Continue / Cline 連携
- [r21-langchain-llamaindex-rag](r21-langchain-llamaindex-rag/) - LangChain / LlamaIndex / RAG からの利用
- [r22-n8n-zapier-webhook](r22-n8n-zapier-webhook/) - n8n / Zapier / Webhook 連携
- [r23-slack-bot](r23-slack-bot/) - Slack bot からの照会

## 注意

- recipe は公開情報の確認と evidence packet 作成を補助する例です。税務、法務、監査、投資、融資、許認可の判断を代替しません。
- 料金や匿名枠は [Pricing](/pricing.html) の現行表示を確認してください。
- 個人事業主情報や取引先情報を扱う場合は、利用目的、アクセス権限、保存期間を事前に確認してください。
