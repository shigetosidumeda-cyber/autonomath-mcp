// playground.bundle.js — external playground JS bundle for /playground.
// Loaded via <script src="/assets/playground.bundle.js" defer> from playground.html.
// Single IIFE: vanilla JS controller for the interactive REST API try-it surface.
//   - ENDPOINTS catalog (local OpenAPI mirror, ~6 KB priority routes)
//   - 3-step Evidence wizard (UA select / SSE stream / final output)
//   - SSE EventSource fallback (POST -> readable stream chunked parsing)
//   - UA switcher (curl / Claude Code / Cursor / Cline / ChatGPT)
//   - Anonymous quota counter (3 req/IP/day reset JST 00:00)
//   - successCount nudge (sessionStorage gated)
// SOURCE: extracted verbatim from playground.html inline <script> at line 1211.
// The HTML inline block is now commented-out keep-for-audit per
// feedback_destruction_free_organization; the canonical runtime path is THIS file.
// CSP: now loadable under script-src 'self' (no unsafe-inline needed).
// LCP target: parser-blocking 2,376 LOC inline -> defer-loaded external bundle.
// Regenerate sidecar with scripts/cwv_hardening_patch.py if a future inline edit
// lands; do NOT hand-edit this bundle without updating playground.html mirror.

/*
  playground.html — vanilla JS controller.

  Architecture:
    ENDPOINTS         — local mirror of priority routes from the
                        OpenAPI spec. Each entry declares method, path,
                        path/query/body params + widget hint + sane
                        defaults. We do NOT fetch /v1/openapi.json on
                        page-load (292 KB; would block first paint).
    state             — currentEndpoint, currentParams, isInflight,
                        successCount (sessionStorage), nudgeDismissed.
    render          — rebuilds the param form when endpoint changes.
    buildUrl        — composes the current URL + JSON body from state.
    send            — fetch + measure duration + parse JSON +
                        render response panel + extract quota header +
                        bump successCount.

  Why no debounce on the URL preview but yes on Send:
    The URL preview is a pure string transform (no network); rebuilding
    it on every keystroke is cheap and shows the user exactly what will
    be sent. The Send button has a 500ms gate to absorb double-clicks
    that would otherwise burn quota.

  No localStorage persistence of the bearer token — the token only lives
  in the DOM, intentionally, so a stale tab does not leak a key after
  the user walks away.
*/
'use strict';

(function() {
  // ----- 1. Local OpenAPI mirror (priority endpoints) ---------------------
  // Mirrors /v1/openapi.json paths verbatim (verified against prod
  // 2026-04-29 dump). Adding params here only — never inventing names
  // that the API does not accept (validation would 422 and confuse the
  // visitor). Defaults are chosen so the first request reliably returns rows.
  const ENDPOINTS = [
    {
      id: 'intelligence.precomputed.query',
      method: 'GET',
      path: '/v1/intelligence/precomputed/query',
      title: 'Evidence Packet / 文脈量見積もり',
      desc: '回答前に出典付き evidence bundle を取得。PDFページ数を渡すと入力文脈量の参考比較を返す。',
      params: [
        { name: 'q', type: 'text', label: '質問', placeholder: '東京都の設備投資補助金は?', defaultValue: '東京都の設備投資補助金は?' },
        { name: 'prefecture', type: 'text', label: '都道府県', placeholder: '東京都' },
        { name: 'tier', type: 'enum', label: 'tier', options: ['', 'S', 'A', 'B', 'C'] },
        { name: 'limit', type: 'number', label: 'limit', defaultValue: '5' },
        { name: 'include_facts', type: 'checkbox', label: 'raw facts も含める' },
        { name: 'include_compression', type: 'checkbox', label: 'compression estimate を含める', defaultChecked: true },
        { name: 'source_tokens_basis', type: 'enum', label: '比較対象', options: ['unknown', 'pdf_pages'], defaultValue: 'pdf_pages' },
        { name: 'source_pdf_pages', type: 'number', label: 'LLMに読ませる予定だったPDFページ数', placeholder: '30', defaultValue: '30' },
        { name: 'input_token_price_jpy_per_1m', type: 'number', label: '入力token単価の参考値 (円 / 100万token)', placeholder: '300', defaultValue: '300' },
      ],
    },
    {
      id: 'evidence.packets.query',
      method: 'POST',
      path: '/v1/evidence/packets/query',
      title: 'Evidence Packet / 複数レコード根拠パケット',
      desc: '検索条件から出典付き evidence packet を作成。回答生成前の根拠、known gaps、入力文脈量の見積もりを返す。',
      params: [
        { name: 'query_text', type: 'text', label: 'query_text', in: 'body', required: true, placeholder: '東京都の設備投資補助金は?', defaultValue: '東京都の設備投資補助金は?' },
        { name: 'filters', type: 'json', label: 'filters (JSON)', in: 'body', placeholder: '{"prefecture":"東京都"}', defaultValue: '{"prefecture":"東京都"}' },
        { name: 'limit', type: 'number', label: 'limit', in: 'body', defaultValue: '5' },
        { name: 'include_facts', type: 'checkbox', label: 'records[].facts[] を含める', in: 'body', defaultChecked: true },
        { name: 'include_rules', type: 'checkbox', label: 'rules[] を含める', in: 'body' },
        { name: 'include_compression', type: 'checkbox', label: 'compression estimate を含める', in: 'body', defaultChecked: true },
        { name: 'fields', type: 'enum', label: 'fields', in: 'body', options: ['default', 'full'], defaultValue: 'default' },
        { name: 'packet_profile', type: 'enum', label: 'packet_profile', in: 'body', options: ['full', 'brief', 'verified_only', 'changes_only'], defaultValue: 'full' },
        { name: 'source_tokens_basis', type: 'enum', label: '比較対象', in: 'body', options: ['unknown', 'pdf_pages', 'token_count'], defaultValue: 'pdf_pages' },
        { name: 'source_pdf_pages', type: 'number', label: 'PDFページ数', in: 'body', placeholder: '30', defaultValue: '30' },
        { name: 'source_token_count', type: 'number', label: 'source_token_count', in: 'body', placeholder: '18500' },
        { name: 'input_token_price_jpy_per_1m', type: 'number', label: '入力token単価の参考値 (円 / 100万token)', in: 'body', placeholder: '300', defaultValue: '300' },
        { name: 'output_format', type: 'enum', label: 'output_format', in: 'query', options: ['json', 'csv', 'md'], defaultValue: 'json' },
      ],
    },
    // Keep this page limited to routes exposed by the public OpenAPI surface.
    {
      id: 'houjin.lookup',
      method: 'GET',
      path: '/v1/houjin/{bangou}',
      title: '法人 360 lookup (gBizINFO + 採択 + 行政処分)',
      desc: '法人番号 13 桁で 1 GET。 meta + adoption_history + enforcement + invoice_status を返す。',
      params: [
        { name: 'bangou', type: 'text', label: '法人番号 (13桁)', isPath: true, required: true, placeholder: '1180301018771', defaultValue: '1180301018771' },
      ],
    },
    {
      id: 'funding_stack.check',
      method: 'POST',
      path: '/v1/funding_stack/check',
      title: 'Funding Stack / 制度併用可否チェック',
      desc: '2〜5 件の制度 ID または名称を pair ごとに判定し、併用可否、warnings、next_actions を返す。',
      params: [
        { name: 'program_ids', type: 'array', label: 'program_ids (2〜5件、改行/カンマ区切り)', in: 'body', required: true, defaultValue: 'UNI-71f6029070\nUNI-00550acb43' },
      ],
    },
    {
      id: 'programs.search',
      method: 'GET',
      path: '/v1/programs/search',
      title: '補助金 / 融資 / 税制 / 認定 を横断検索',
      desc: '11,601 active programs を tier S/A/B/C で。 匿名でも全フィールド返却。',
      params: [
        { name: 'q',                type: 'text',   label: 'キーワード',         placeholder: 'IT導入', defaultValue: 'IT導入' },
        { name: 'tier',             type: 'multi',  label: 'tier (繰返し可)',     options: ['S','A','B','C'], defaultValue: '' },
        { name: 'prefecture',       type: 'text',   label: '都道府県',           placeholder: '東京都' },
        { name: 'authority_level',  type: 'enum',   label: '実施主体',           options: ['', 'national', 'prefecture', 'municipality'] },
        { name: 'amount_min',       type: 'number', label: '金額下限 (円)',      placeholder: '1000000' },
        { name: 'amount_max',       type: 'number', label: '金額上限 (円)',      placeholder: '50000000' },
        { name: 'limit',            type: 'number', label: 'limit',              defaultValue: '5' },
        { name: 'offset',           type: 'number', label: 'offset',             defaultValue: '0' },
        { name: 'fields',           type: 'enum',   label: 'fields',             options: ['default', 'minimal', 'full'], defaultValue: 'minimal' },
      ],
    },
    {
      id: 'programs.get',
      method: 'GET',
      path: '/v1/programs/{unified_id}',
      title: '制度 1 件詳細取得',
      desc: 'unified_id (PRG-xxxxxxxxxx) で確定取得。 出典 URL + fetched_at 付き。',
      params: [
        // Default = a real prod unified_id (IT導入補助金) so the visitor's
        // first GET on this endpoint returns a 200 with primary-source URL,
        // not a 404 confusion. Verified via curl 2026-04-29.
        { name: 'unified_id', type: 'text',   label: 'unified_id', isPath: true, required: true, placeholder: 'UNI-71f6029070', defaultValue: 'UNI-71f6029070' },
        { name: 'fields',     type: 'enum',   label: 'fields',     options: ['default', 'minimal', 'full'], defaultValue: 'default' },
      ],
    },
    {
      id: 'am.tax_incentives',
      method: 'GET',
      path: '/v1/am/tax_incentives',
      title: '税制特例検索 (特別償却・税額控除・繰越欠損金)',
      desc: '税制特例・税額控除・特別償却などの一次資料付き検索。',
      params: [
        { name: 'query',         type: 'text',   label: 'キーワード',     placeholder: '中小企業 投資', defaultValue: '中小企業' },
        { name: 'authority',     type: 'enum',   label: '所管庁',         options: ['', '国税庁', '財務省', '経済産業省', '中小企業庁', '農林水産省', '総務省', '国土交通省', '厚生労働省', '自治体'] },
        { name: 'industry',      type: 'text',   label: '業種',           placeholder: '製造業' },
        { name: 'target_year',   type: 'number', label: '対象年 (西暦)',  placeholder: '2026' },
        { name: 'target_entity', type: 'enum',   label: '対象事業者',     options: ['', '中小企業', '小規模事業者', '個人事業主', '大企業', '認定事業者', '青色申告者', '農業法人', '特定事業者等'] },
        { name: 'limit',         type: 'number', label: 'limit',          defaultValue: '5' },
        { name: 'offset',        type: 'number', label: 'offset',         defaultValue: '0' },
      ],
    },
    {
      id: 'am.loans',
      method: 'GET',
      path: '/v1/am/loans',
      title: '融資検索 (公庫 / 商工中金 / 自治体制度融資 — 3 軸保証)',
      desc: 'am_loan_product。 担保 / 個人保証人 / 第三者保証人 を独立 boolean で。',
      params: [
        { name: 'loan_kind',                type: 'enum',     label: '融資種別',          options: ['', 'ippan','trou','seirei','sanko','sogyo','rinsei','saigai','shingiseikyu','kiki','other'] },
        { name: 'no_collateral',            type: 'checkbox', label: '無担保' },
        { name: 'no_personal_guarantor',    type: 'checkbox', label: '個人保証人なし' },
        { name: 'no_third_party_guarantor', type: 'checkbox', label: '第三者保証人なし' },
        { name: 'min_amount_yen',           type: 'number',   label: '金額下限 (円)' },
        { name: 'max_amount_yen',           type: 'number',   label: '金額上限 (円)',     placeholder: '30000000' },
        { name: 'name_query',               type: 'text',     label: '商品名 (部分一致)', placeholder: 'マル経' },
        { name: 'limit',                    type: 'number',   label: 'limit',             defaultValue: '5' },
      ],
    },
    {
      id: 'invoice.search',
      method: 'GET',
      path: '/v1/invoice_registrants/search',
      title: '適格請求書発行事業者 検索',
      desc: '返却行には PDL v1.0 attribution を付与。全件 bulk は国税庁の公式ダウンロードを参照。収録 13,801 rows。',
      params: [
        { name: 'q',                  type: 'text',   label: '事業者名 (前方一致)', placeholder: 'トヨタ', defaultValue: 'トヨタ' },
        { name: 'houjin_bangou',      type: 'text',   label: '法人番号 (13桁)',     placeholder: '1180301018771' },
        { name: 'kind',               type: 'enum',   label: '区分',                options: ['', 'corporate', 'individual'] },
        { name: 'prefecture',         type: 'text',   label: '都道府県',            placeholder: '東京都' },
        { name: 'registered_after',   type: 'date',   label: '登録日 from (YYYY-MM-DD)' },
        { name: 'registered_before',  type: 'date',   label: '登録日 to (YYYY-MM-DD)' },
        { name: 'active_only',        type: 'checkbox', label: '取消・期限切れを除外', defaultChecked: true },
        { name: 'limit',              type: 'number', label: 'limit',               defaultValue: '5' },
        { name: 'offset',             type: 'number', label: 'offset',              defaultValue: '0' },
      ],
    },
    {
      id: 'invoice.get',
      method: 'GET',
      path: '/v1/invoice_registrants/{invoice_registration_number}',
      title: '適格事業者 1 件詳細 (T番号 lookup)',
      desc: 'T + 13 桁の登録番号で exact lookup。 delta 未収録なら 200 + not_in_mirror=true。',
      params: [
        // Default value is a valid example format. Visitors can paste any
        // real invoice registration number.
        { name: 'invoice_registration_number', type: 'text', label: 'T番号 (T1234567890123)', isPath: true, required: true, placeholder: 'T3810649779313', defaultValue: 'T3810649779313' },
      ],
    },
    {
      id: 'laws.search',
      method: 'GET',
      path: '/v1/laws/search',
      title: '法令検索 (e-Gov メタデータ + 法令本文)',
      desc: 'CC-BY 4.0 (e-Gov)。 法令本文・改正情報・施行日。',
      params: [
        { name: 'q',                       type: 'text',   label: 'キーワード',     placeholder: '消費税', defaultValue: '消費税' },
        { name: 'law_type',                type: 'enum',   label: '法令種別',       options: ['', 'constitution','act','cabinet_order','imperial_order','ministerial_ordinance','rule','notice','guideline'] },
        { name: 'ministry',                type: 'text',   label: '所管府省',       placeholder: '財務省' },
        { name: 'currently_effective_only',type: 'checkbox', label: '現行のみ',     defaultChecked: true },
        { name: 'include_repealed',        type: 'checkbox', label: '廃止を含める' },
        { name: 'promulgated_from',        type: 'date',   label: '公布日 from' },
        { name: 'promulgated_to',          type: 'date',   label: '公布日 to' },
        { name: 'limit',                   type: 'number', label: 'limit',          defaultValue: '5' },
        { name: 'offset',                  type: 'number', label: 'offset',         defaultValue: '0' },
      ],
    },
    {
      id: 'court.search',
      method: 'GET',
      path: '/v1/court-decisions/search',
      title: '判例検索 (判決 / 決定 / 命令 — 2,065 rows)',
      desc: '最高裁 / 高裁 / 地裁。 関連法令 ID で逆引き可。',
      params: [
        { name: 'q',                  type: 'text',   label: 'キーワード',     placeholder: '消費税 仕入控除', defaultValue: '消費税' },
        { name: 'court_level',        type: 'enum',   label: '審級',           options: ['', 'supreme', 'high', 'district', 'summary', 'family'] },
        { name: 'decision_type',      type: 'enum',   label: '判決種別',       options: ['', '判決', '決定', '命令'] },
        { name: 'subject_area',       type: 'text',   label: '分野',           placeholder: '租税' },
        { name: 'references_law_id',  type: 'text',   label: '関連法令 ID',    placeholder: 'LAW-xxxxxxxxxx' },
        { name: 'decided_from',       type: 'date',   label: '判決日 from' },
        { name: 'decided_to',         type: 'date',   label: '判決日 to' },
        { name: 'limit',              type: 'number', label: 'limit',          defaultValue: '5' },
        { name: 'offset',             type: 'number', label: 'offset',         defaultValue: '0' },
      ],
    },
    {
      id: 'cases.search',
      method: 'GET',
      path: '/v1/case-studies/search',
      title: '採択事例検索 (2,286 rows)',
      desc: '実際に補助金を獲得した法人 / 個人事業主の事例。 法人番号一部付き。',
      params: [
        { name: 'q',              type: 'text',   label: 'キーワード',         placeholder: 'IT導入', defaultValue: 'IT導入' },
        { name: 'prefecture',     type: 'text',   label: '都道府県',           placeholder: '北海道' },
        { name: 'industry_jsic',  type: 'text',   label: 'JSIC コード prefix', placeholder: 'A' },
        { name: 'houjin_bangou',  type: 'text',   label: '法人番号 (13桁)',    placeholder: '' },
        { name: 'program_used',   type: 'text',   label: '使った制度',         placeholder: 'IT導入' },
        { name: 'min_employees',  type: 'number', label: '従業員下限' },
        { name: 'max_employees',  type: 'number', label: '従業員上限' },
        { name: 'limit',          type: 'number', label: 'limit',              defaultValue: '5' },
        { name: 'offset',         type: 'number', label: 'offset',             defaultValue: '0' },
      ],
    },
    {
      id: 'tax_rulesets.search',
      method: 'GET',
      path: '/v1/tax_rulesets/search',
      title: '税務判定ルールセット検索 (50 rows)',
      desc: 'インボイス・電子帳簿保存・特別償却 等の判定ロジック。 _disclaimer 付き。',
      params: [
        { name: 'q',             type: 'text', label: 'キーワード',  placeholder: 'インボイス', defaultValue: 'インボイス' },
        { name: 'tax_category',  type: 'text', label: '税目',        placeholder: 'consumption' },
        { name: 'ruleset_kind',  type: 'text', label: 'kind',        placeholder: 'registration' },
        { name: 'effective_on',  type: 'date', label: 'effective_on (YYYY-MM-DD)' },
        { name: 'limit',         type: 'number', label: 'limit',     defaultValue: '5' },
        { name: 'offset',        type: 'number', label: 'offset',    defaultValue: '0' },
      ],
    },
  ];

  const API_BASE = 'https://api.jpcite.com';
  const STORAGE_KEY = 'pg-success-count';
  const NUDGE_KEY = 'pg-nudge-dismissed-stage';
  // Anonymous quota is 3 req/day per IP. The nudge cadence is aligned to
  // that quota: 1=copy curl, 2=MCP/OpenAPI, 3 (or quota=0)=pricing/API key.
  const NUDGE_THRESHOLD = 1;
  const SEND_DEBOUNCE_MS = 500;
  const VALUE_FIELD_GROUPS = [
    {
      id: 'risk',
      title: 'リスクサマリ',
      subtitle: '法人360の赤黄緑、要注意ポイント、確認が必要な前提',
      keys: [
        'risk_summary',
        'riskSummary',
      ],
    },
    {
      id: 'decision',
      title: '判断に効く点',
      subtitle: '採用、見送り、追加確認を決める材料',
      keys: [
        'decision_insights',
        'decisionInsights',
        'why_this_matters',
        'whyThisMatters',
        'why_this_bundle',
        'whyThisBundle',
        'why_this_bundle_matters',
        'whyThisBundleMatters',
        'tradeoffs',
        'recommended_position',
        'recommendedPosition',
        'decision_guidance',
        'decisionGuidance',
        'decision_points',
        'decisionPoints',
        'agent_recommendation',
        'agentRecommendation',
        'value_reasons',
        'valueReasons',
      ],
    },
    {
      id: 'signals',
      title: '出典横断シグナル',
      subtitle: '一次資料、引用検証、既知の欠落の見える化',
      keys: [
        'cross_source_signals',
        'crossSourceSignals',
        'source_signals',
        'sourceSignals',
        'evidence_signals',
        'evidenceSignals',
        'evidence_value',
        'evidenceValue',
        'citation_signals',
        'citationSignals',
        'quality_signals',
        'qualitySignals',
      ],
    },
    {
      id: 'actions',
      title: '次にやること',
      subtitle: '人がそのまま動ける確認・申請準備ステップ',
      keys: [
        'next_actions',
        'nextActions',
        'next_checks',
        'nextChecks',
        'recommended_next_actions',
        'recommendedNextActions',
        'next_steps',
        'nextSteps',
        'action_items',
        'actionItems',
        'next_calls',
        'nextCalls',
      ],
    },
    {
      id: 'fundingStack',
      title: '併用可否・確認行動',
      subtitle: 'Funding Stack の pair verdict、blocker、warning、次の確認',
      keys: [
        'funding_stack',
        'fundingStack',
        'all_pairs_status',
        'allPairsStatus',
        'pairs',
        'verdicts',
        'blockers',
        'warnings',
      ],
    },
    {
      id: 'knownGaps',
      title: '確認範囲・既知の欠落',
      subtitle: '未確認、古い出典、低信頼、追加確認が必要な範囲',
      keys: [
        'known_gaps',
        'knownGaps',
        'known_gaps_inventory',
        'knownGapsInventory',
      ],
    },
    {
      id: 'questions',
      title: '次の質問',
      subtitle: '顧客に追加で確認すべき入力項目と理由',
      keys: [
        'next_questions',
        'nextQuestions',
      ],
    },
    {
      id: 'eligibilityGaps',
      title: '適格性の不足',
      subtitle: '申請可否の判断前に埋める不足条件や未確認条件',
      keys: [
        'eligibility_gaps',
        'eligibilityGaps',
      ],
    },
    {
      id: 'documents',
      title: '書類準備',
      subtitle: '必要書類、準備済み書類、不足証憑の確認',
      keys: [
        'document_readiness',
        'documentReadiness',
      ],
    },
  ];
  const VALUE_CODE_LABELS = {
    use_jpcite_prefetch: 'jpcite の Evidence Packet を先に使う判断です。',
    use_evidence_packet: '出典付き Evidence Packet として使う価値があります。',
    broaden_query_or_skip: 'この条件では検索語を広げるか、別エンドポイントで確認します。',
    supported_by_source_linked_records: '一次資料 URL 付きのレコードが判断材料になります。',
    no_records_returned: 'この条件では該当レコードが返っていません。',
    records_returned_without_source_links: 'レコードはありますが、出典リンクが不足しています。',
    source_linked_records_returned: '一次資料 URL 付きの候補が返っています。',
    precomputed_summary_available: '事前計算済み要約があり、回答前の確認に使えます。',
    pdf_fact_refs_available: 'PDF 内の根拠参照があります。',
    known_gaps_exposed: '既知の欠落も明示され、過信しにくくなっています。',
    no_request_time_llm: 'このリクエスト時に LLM 生成を行っていません。',
    no_live_web_search: 'ライブ Web 検索なしで再現しやすい結果です。',
    caller_baseline_break_even_met: '指定した比較基準で入力文脈量の比較結果があります。',
    caller_baseline_evaluated: '指定した比較基準で入力文脈量を評価済みです。',
    context_savings_baseline_needed: '文脈量比較には、比較基準の指定が必要です。',
    needs_caller_baseline: '入力文脈量の比較には、呼び出し側の基準値が必要です。',
    supported_by_caller_baseline: '呼び出し側の基準値に基づく比較結果があります。',
    source_url_missing: '出典 URL が未接続です。',
    source_fetched_at_missing: '出典の取得日時が未接続です。',
    source_stale: '出典が古いため再確認が必要です。',
    license_unknown: 'ライセンス条件が未確認です。',
    license_blocked: 'ライセンス上そのまま出力できません。',
    low_confidence: '抽出信頼度が低く、人間確認が必要です。',
    citation_unverified: '引用が未検証です。',
    structured_miss: '構造化できていない情報があります。',
    conflict: '出典間に矛盾があります。',
    human_review_required: '人間による確認が必要です。',
    audit_seal_not_issued: '監査 seal が未発行です。',
    red: '赤: 要注意',
    yellow: '黄: 要確認',
    green: '緑: 大きな警戒シグナルは未検出',
    high: '高',
    medium: '中',
    low: '低',
    critical: '重大',
    watch: '監視',
    ready: '準備済み',
    missing: '不足',
    pending: '未開始',
    unknown: '未確認',
    not_ready: '未準備',
    partial: '一部準備',
    compatible: '併用可',
    incompatible: '併用不可',
    requires_review: '要確認',
    allow: '可',
    deny: '不可',
    review: '要確認',
    primary_bundle: '主案 bundle',
  };
  const VALUE_KEY_LABELS = {
    records_returned: '返却レコード',
    source_linked_records: '一次資料 URL 付きレコード',
    source_linked_records_returned: '一次資料 URL 付きレコード',
    precomputed_records: '事前計算済みレコード',
    pdf_fact_refs: 'PDF 根拠参照',
    known_gap_count: '既知の欠落',
    known_gaps: '既知の欠落',
    knownGaps: '既知の欠落',
    known_gaps_inventory: '既知の欠落内訳',
    knownGapsInventory: '既知の欠落内訳',
    citation_count: '引用',
    citation_verified_count: '検証済み引用',
    citation_inferred_count: '推定引用',
    citation_stale_count: '要再確認の引用',
    citation_unknown_count: '未判定引用',
    fact_provenance_coverage_pct_avg: 'fact provenance coverage',
    message_ja: 'メッセージ',
    why_this_matters: '重要な理由',
    risk_summary: 'リスクサマリ',
    riskSummary: 'リスクサマリ',
    risk_level: 'リスク水準',
    riskLevel: 'リスク水準',
    overall_risk: '総合リスク',
    overallRisk: '総合リスク',
    risk_score: 'リスクスコア',
    riskScore: 'リスクスコア',
    severity: '重要度',
    confidence: '信頼度',
    all_pairs_status: '全ペア判定',
    allPairsStatus: '全ペア判定',
    total_pairs: '判定ペア数',
    totalPairs: '判定ペア数',
    verdict: '判定',
    program_a: '制度A',
    programA: '制度A',
    program_b: '制度B',
    programB: '制度B',
    recommended_position: '推奨位置づけ',
    recommendedPosition: '推奨位置づけ',
    why_this_bundle: 'bundle の理由',
    whyThisBundle: 'bundle の理由',
    tradeoffs: 'トレードオフ',
    action_id: 'アクションID',
    actionId: 'アクションID',
    action_type: 'アクション種別',
    actionType: 'アクション種別',
    label_ja: 'アクション',
    labelJa: 'アクション',
    detail_ja: '詳細',
    detailJa: '詳細',
    entity_match_confidence: '法人照合信頼度',
    entityMatchConfidence: '法人照合信頼度',
    human_review_required: '人間確認',
    gap_code: '欠落コード',
    gapCode: '欠落コード',
    gap_type: '不足種別',
    gapType: '不足種別',
    required_by: '要求元',
    requiredBy: '要求元',
    impact: '影響',
    expected: '期待値',
    reason_code: '理由コード',
    reasonCode: '理由コード',
    code: 'コード',
    category: '分類',
    priority: '優先度',
    source: '出典',
    scope: '確認範囲',
    checked_scope: '確認済み範囲',
    checkedScope: '確認済み範囲',
    remedy: '補う確認',
    field: '確認項目',
    question: '質問',
    blocking: '必須確認',
    semi_blocking: '要確認',
    semiBlocking: '要確認',
    gap: '不足',
    requirement: '条件',
    missing_input: '不足入力',
    missingInput: '不足入力',
    document_name: '書類名',
    documentName: '書類名',
    document: '書類',
    required_document_count: '必要書類数',
    requiredDocumentCount: '必要書類数',
    forms_with_url_count: 'URL付き様式数',
    formsWithUrlCount: 'URL付き様式数',
    signature_required_count: '押印/署名必要数',
    signatureRequiredCount: '押印/署名必要数',
    signature_unknown_count: '押印/署名未確認数',
    signatureUnknownCount: '押印/署名未確認数',
    needs_user_confirmation: '利用者確認',
    needsUserConfirmation: '利用者確認',
    status: '状態',
  };
  let lastQuotaRemaining = null;

  // ----- 2. State + DOM lookups ------------------------------------------
  let currentEndpoint = ENDPOINTS[0];
  let lastSendAt = 0;
  let inflight = false;

  const $ = (id) => document.getElementById(id);
  const els = {
    endpoint: $('pg-endpoint'),
    endpointDesc: $('pg-endpoint-desc'),
    params: $('pg-params'),
    bearer: $('pg-bearer'),
    urlText: $('pg-url-text'),
    urlPreview: $('pg-url-preview'),
    send: $('pg-send'),
    reset: $('pg-reset'),
    response: $('pg-response'),
    status: $('pg-status'),
    duration: $('pg-duration'),
    body: $('pg-body'),
    valueFields: $('pg-value-fields'),
    valueSummary: $('pg-value-summary'),
    valueGrid: $('pg-value-grid'),
    headersToggle: $('pg-headers-toggle'),
    headers: $('pg-headers'),
    quota: $('pg-quota'),
    quotaRemaining: $('pg-quota-remaining'),
    quotaCta: $('pg-quota-cta'),
    nudge: $('pg-nudge'),
    nudgeText: $('pg-nudge-text'),
    nudgeLink: $('pg-nudge-link'),
    nudgeDismiss: $('pg-nudge-dismiss'),
    conversionCta: $('pg-conversion-cta'),
    conversionTitle: $('pg-conversion-title'),
    conversionText: $('pg-conversion-text'),
    conversionPrimary: $('pg-conversion-primary'),
    conversionSecondary: $('pg-conversion-secondary'),
    flowHint: $('pg-flow-hint'),
    copyCurl: $('pg-copy-curl'),
    openPostman: $('pg-open-postman'),
    openHttpie: $('pg-open-httpie'),
  };

  // ----- 3. Helpers ------------------------------------------------------
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeText(node, value) {
    // Use textContent rather than innerHTML to avoid any reflected-XSS risk
    // when echoing a status line or response body the API returned.
    node.textContent = value == null ? '' : String(value);
  }

  function isPlainObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value);
  }

  function ctaContainers(body) {
    const out = [];
    if (isPlainObject(body)) out.push(body);
    if (isPlainObject(body && body.detail)) out.push(body.detail);
    if (isPlainObject(body && body.error)) out.push(body.error);
    if (isPlainObject(body && body.error && body.error.detail)) out.push(body.error.detail);
    return out;
  }

  function firstValue(containers, key) {
    for (const item of containers) {
      if (item[key] != null) return item[key];
    }
    return null;
  }

  function safeHref(value) {
    if (typeof value !== 'string') return '';
    const trimmed = value.trim();
    if (!trimmed) return '';
    try {
      const url = new URL(trimmed, window.location.href);
      if (url.protocol === 'https:' || url.protocol === 'http:') return url.href;
    } catch (_e) {}
    return '';
  }

  function firstUrl(containers, keys) {
    for (const item of containers) {
      if (!isPlainObject(item)) continue;
      for (const key of keys) {
        const href = safeHref(item[key]);
        if (href) return href;
      }
    }
    return '';
  }

  function conversionUrl(conversionCta) {
    if (typeof conversionCta === 'string') return safeHref(conversionCta);
    if (!isPlainObject(conversionCta)) return '';
    const primary = isPlainObject(conversionCta.primary) ? conversionCta.primary : null;
    const actions = Array.isArray(conversionCta.actions) ? conversionCta.actions : [];
    return firstUrl([conversionCta, primary].concat(actions), [
      'direct_checkout_url',
      'checkout_url',
      'url',
      'href',
      'action_url',
      'primary_url',
    ]);
  }

  function hideConversionCta() {
    if (!els.conversionCta) return;
    els.conversionCta.hidden = true;
    if (els.conversionSecondary) els.conversionSecondary.hidden = true;
  }

  function renderConversionCta(body, status) {
    if (!els.conversionCta) return;
    const containers = ctaContainers(body);
    const conversionCta = firstValue(containers, 'conversion_cta');
    const directCheckoutUrl = firstUrl(containers, ['direct_checkout_url']);
    const trialSignupUrl = firstUrl(containers, ['trial_signup_url']);
    const upgradeUrl = firstUrl(containers, ['upgrade_url']);
    const primaryFromConversion = conversionUrl(conversionCta);
    const hasQuotaCta = (status === 429 || directCheckoutUrl || trialSignupUrl) &&
      (directCheckoutUrl || trialSignupUrl || upgradeUrl);

    if (hasQuotaCta) {
      safeText(els.conversionTitle, 'API キーで継続');
      safeText(els.conversionText, '本日の匿名枠に達しました。API キーを発行すると、同じレスポンス形式で継続利用できます。');
      safeText(els.conversionPrimary, 'API キーを発行');
      els.conversionPrimary.href = directCheckoutUrl || upgradeUrl || 'pricing.html#api-paid';
      els.conversionPrimary.dataset.cta = 'playground-429-direct-checkout';
      if (trialSignupUrl) {
        safeText(els.conversionSecondary, 'トライアルを開始');
        els.conversionSecondary.href = trialSignupUrl;
        els.conversionSecondary.hidden = false;
      } else {
        els.conversionSecondary.hidden = true;
      }
      els.conversionCta.hidden = false;
      return;
    }

    if (conversionCta || primaryFromConversion) {
      safeText(els.conversionTitle, '完成物に変換');
      safeText(els.conversionText, 'この根拠から、申請前チェック、併用/排他表、顧客説明文を作れます。');
      safeText(els.conversionPrimary, '完成物に変換');
      els.conversionPrimary.href = primaryFromConversion || upgradeUrl || 'pricing.html#api-paid';
      els.conversionPrimary.dataset.cta = 'playground-artifact-conversion';
      els.conversionSecondary.hidden = true;
      els.conversionCta.hidden = false;
      return;
    }

    hideConversionCta();
  }

  function hideValueFields() {
    if (!els.valueFields) return;
    els.valueFields.hidden = true;
    if (els.valueGrid) els.valueGrid.innerHTML = '';
    if (els.valueSummary) safeText(els.valueSummary, '');
  }

  function isEmptyValue(value) {
    if (value == null) return true;
    if (typeof value === 'string') return value.trim() === '';
    if (Array.isArray(value)) return value.length === 0 || value.every(isEmptyValue);
    if (isPlainObject(value)) return Object.keys(value).length === 0;
    return false;
  }

  function collectValueContainers(value, out, depth) {
    if (depth > 4 || out.length > 120) return;
    if (isPlainObject(value)) {
      out.push(value);
      const priority = [
        'evidence_packet',
        'evidencePacket',
        'packet',
        'bundle',
        'decision_support',
        'decisionSupport',
        'data',
        'result',
        'payload',
        'quality',
        'agent_recommendation',
        'agentRecommendation',
        'evidence_value',
        'evidenceValue',
        'matched_programs',
        'matchedPrograms',
        'pairs',
        'verdicts',
        'funding_stack',
        'fundingStack',
      ];
      for (const key of priority) {
        const child = value[key];
        if (isPlainObject(child) || Array.isArray(child)) {
          collectValueContainers(child, out, depth + 1);
        }
      }
      for (const key of Object.keys(value)) {
        if (priority.indexOf(key) >= 0) continue;
        const child = value[key];
        if (isPlainObject(child) || Array.isArray(child)) {
          collectValueContainers(child, out, depth + 1);
        }
      }
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value.slice(0, 8)) {
        collectValueContainers(item, out, depth + 1);
      }
    }
  }

  function responseValueContainers(body) {
    const out = [];
    collectValueContainers(body, out, 0);
    return out;
  }

  function fieldsByKeys(containers, keys) {
    const found = [];
    for (const key of keys) {
      for (const item of containers) {
        if (!isPlainObject(item)) continue;
        if (!Object.prototype.hasOwnProperty.call(item, key)) continue;
        const value = item[key];
        if (!isEmptyValue(value)) found.push({ key: key, value: value });
      }
    }
    return found;
  }

  function normalizeValueText(text) {
    return String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
  }

  function shortenText(text, maxLen) {
    const normalized = normalizeValueText(text);
    if (normalized.length <= maxLen) return normalized;
    return normalized.slice(0, Math.max(0, maxLen - 3)).trim() + '...';
  }

  function humanKey(key) {
    if (VALUE_KEY_LABELS[key]) return VALUE_KEY_LABELS[key];
    return String(key)
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/_/g, ' ');
  }

  function humanValueText(value) {
    if (typeof value === 'string') {
      const trimmed = normalizeValueText(value);
      return VALUE_CODE_LABELS[trimmed] || trimmed;
    }
    if (typeof value === 'number') {
      try { return new Intl.NumberFormat('ja-JP').format(value); }
      catch (_e) { return String(value); }
    }
    if (typeof value === 'boolean') return value ? 'はい' : 'いいえ';
    return '';
  }

  function pushValueItem(out, text) {
    const cleaned = shortenText(text, 180);
    if (!cleaned) return;
    if (out.indexOf(cleaned) >= 0) return;
    out.push(cleaned);
  }

  function addPrimitivePair(out, key, value) {
    if (isEmptyValue(value)) return;
    if (isPlainObject(value) || Array.isArray(value)) return;
    pushValueItem(out, humanKey(key) + ': ' + humanValueText(value));
  }

  function addDecisionItems(out, value) {
    if (!isPlainObject(value)) return;
    if (value.recommendation != null) pushValueItem(out, humanValueText(value.recommendation));
    if (value.evidence_decision != null) pushValueItem(out, humanValueText(value.evidence_decision));
    if (value.recommended_position != null) addPrimitivePair(out, 'recommended_position', value.recommended_position);
    if (value.recommendedPosition != null) addPrimitivePair(out, 'recommendedPosition', value.recommendedPosition);
    if (value.recommend_for_evidence === true) {
      pushValueItem(out, '出典付きの根拠確認に使える状態です。');
    }
    if (value.recommend_for_cost_savings === true) {
      pushValueItem(out, '入力文脈量の比較基準も評価済みです。');
    }
    if (value.cost_savings_decision != null) {
      pushValueItem(out, humanValueText(value.cost_savings_decision));
    }
    if (value.message != null) pushValueItem(out, value.message);
    if (value.message_ja != null) pushValueItem(out, value.message_ja);
    appendValueItems(out, value.why_this_matters, 'decision', 1);
    appendValueItems(out, value.whyThisMatters, 'decision', 1);
    appendValueItems(out, value.why_this_bundle, 'decision', 1);
    appendValueItems(out, value.whyThisBundle, 'decision', 1);
    appendValueItems(out, value.why_this_bundle_matters, 'decision', 1);
    appendValueItems(out, value.whyThisBundleMatters, 'decision', 1);
    appendValueItems(out, value.tradeoffs, 'decision', 1);
    appendValueItems(out, value.why_review, 'decision', 1);
    appendValueItems(out, value.whyReview, 'decision', 1);
    appendValueItems(out, value.decision_insights, 'decision', 1);
    appendValueItems(out, value.decisionInsights, 'decision', 1);
    appendValueItems(out, value.evidence_gaps, 'signals', 1);
    appendValueItems(out, value.evidenceGaps, 'signals', 1);
    appendValueItems(out, value.value_reasons, 'decision', 1);
    appendValueItems(out, value.reason_codes, 'decision', 1);
  }

  function addRiskItems(out, value) {
    if (!isPlainObject(value)) return;
    [
      'headline',
      'summary',
      'message',
      'message_ja',
      'messageJa',
      'verdict',
      'note',
    ].forEach(function (key) {
      if (typeof value[key] === 'string') pushValueItem(out, value[key]);
    });
    [
      'risk_level',
      'riskLevel',
      'overall_risk',
      'overallRisk',
      'risk_score',
      'riskScore',
      'severity',
      'confidence',
      'entity_match_confidence',
      'entityMatchConfidence',
      'human_review_required',
    ].forEach(function (key) {
      if (value[key] != null) addPrimitivePair(out, key, value[key]);
    });
    [
      'risk_factors',
      'riskFactors',
      'risk_flags',
      'riskFlags',
      'flags',
      'findings',
      'public_record_flags',
      'publicRecordFlags',
      'adverse_events',
      'adverseEvents',
      'enforcement_events',
      'enforcementEvents',
      'invoice_flags',
      'invoiceFlags',
      'attention_points',
      'attentionPoints',
      'watch_points',
      'watchPoints',
      'known_gaps',
      'knownGaps',
      'next_checks',
      'nextChecks',
    ].forEach(function (key) {
      appendValueItems(out, value[key], 'risk', 1);
    });
  }

  function addKnownGapItems(out, value) {
    if (!isPlainObject(value)) return;
    [
      'message',
      'message_ja',
      'messageJa',
      'summary',
      'description',
      'reason',
      'gap',
      'note',
    ].forEach(function (key) {
      if (typeof value[key] === 'string') pushValueItem(out, value[key]);
    });
    [
      'gap_code',
      'gapCode',
      'code',
      'reason_code',
      'reasonCode',
      'category',
      'severity',
      'status',
      'source',
      'scope',
      'checked_scope',
      'checkedScope',
      'field',
      'remedy',
      'priority',
      'human_review_required',
    ].forEach(function (key) {
      if (value[key] != null) addPrimitivePair(out, key, value[key]);
    });
    [
      'items',
      'gaps',
      'known_gaps',
      'knownGaps',
      'missing_fields',
      'missingFields',
      'unverified_sources',
      'unverifiedSources',
      'stale_sources',
      'staleSources',
      'conflicts',
      'next_checks',
      'nextChecks',
    ].forEach(function (key) {
      appendValueItems(out, value[key], 'knownGaps', 1);
    });
  }

  function addSignalItems(out, value) {
    if (!isPlainObject(value)) return;
    [
      'records_returned',
      'source_linked_records',
      'source_linked_records_returned',
      'precomputed_records',
      'pdf_fact_refs',
      'known_gap_count',
      'citation_count',
      'citation_verified_count',
      'citation_inferred_count',
      'citation_stale_count',
      'citation_unknown_count',
    ].forEach(function (key) {
      if (value[key] != null) addPrimitivePair(out, key, value[key]);
    });
    if (typeof value.fact_provenance_coverage_pct_avg === 'number') {
      pushValueItem(out, humanKey('fact_provenance_coverage_pct_avg') + ': ' +
        Math.round(value.fact_provenance_coverage_pct_avg * 100) + '%');
    }
    if (value.web_search_performed_by_jpcite === false) {
      pushValueItem(out, 'jpcite はこのリクエストでライブ Web 検索を行っていません。');
    }
    if (value.request_time_llm_call_performed === false) {
      pushValueItem(out, 'jpcite はこのリクエストで LLM 生成を行っていません。');
    }
    appendValueItems(out, value.citations, 'signals', 1);
    appendValueItems(out, value.signals, 'signals', 1);
  }

  function addFundingStackItems(out, value) {
    if (!isPlainObject(value)) return;
    [
      'all_pairs_status',
      'allPairsStatus',
      'verdict',
      'confidence',
      'total_pairs',
      'totalPairs',
      'incompatible_count',
      'incompatibleCount',
      'case_by_case_count',
      'caseByCaseCount',
      'unknown_count',
      'unknownCount',
      'missing_count',
      'missingCount',
    ].forEach(function (key) {
      if (value[key] != null) addPrimitivePair(out, key, value[key]);
    });
    if (value.program_a != null && value.program_b != null && value.verdict != null) {
      pushValueItem(out, String(value.program_a) + ' + ' + String(value.program_b) + ': ' + humanValueText(value.verdict));
    }
    [
      'summary',
      'message',
      'message_ja',
      'messageJa',
      'label_ja',
      'labelJa',
      'detail_ja',
      'detailJa',
      'reason',
    ].forEach(function (key) {
      if (typeof value[key] === 'string') pushValueItem(out, value[key]);
    });
    [
      'pairs',
      'verdicts',
      'blockers',
      'warnings',
      'next_actions',
      'nextActions',
      'rule_chain',
      'ruleChain',
    ].forEach(function (key) {
      appendValueItems(out, value[key], 'fundingStack', 1);
    });
  }

  function addObjectTextFields(out, value, groupId) {
    const preferred = [
      'headline',
      'title',
      'label',
      'label_ja',
      'labelJa',
      'summary',
      'message',
      'message_ja',
      'messageJa',
      'insight',
      'question',
      'prompt',
      'gap',
      'description',
      'reason',
      'why_this_matters',
      'whyThisMatters',
      'action',
      'next_action',
      'action_type',
      'actionType',
      'step',
      'detail_ja',
      'detailJa',
      'note',
      'name',
      'verdict',
      'impact',
    ];
    for (const key of preferred) {
      if (typeof value[key] === 'string') pushValueItem(out, value[key]);
    }
    [
      'items',
      'insights',
      'signals',
      'actions',
      'steps',
      'why_review',
      'whyReview',
      'risk_summary',
      'riskSummary',
      'risk_factors',
      'riskFactors',
      'risk_flags',
      'riskFlags',
      'decision_insights',
      'decisionInsights',
      'next_actions',
      'nextActions',
      'next_checks',
      'nextChecks',
      'next_questions',
      'nextQuestions',
      'questions',
      'eligibility_gaps',
      'eligibilityGaps',
      'gaps',
      'document_readiness',
      'documentReadiness',
      'documents',
      'required_documents',
      'requiredDocuments',
      'missing_documents',
      'missingDocuments',
      'ready_documents',
      'readyDocuments',
      'pending_documents',
      'pendingDocuments',
      'evidence_needed',
      'evidenceNeeded',
      'evidence_gaps',
      'evidenceGaps',
      'known_gaps',
      'knownGaps',
      'known_gaps_inventory',
      'knownGapsInventory',
      'findings',
      'attention_points',
      'attentionPoints',
      'watch_points',
      'watchPoints',
      'value_reasons',
      'valueReasons',
      'reason_codes',
      'reasonCodes',
    ].forEach(function (key) {
      appendValueItems(out, value[key], groupId, 1);
    });
  }

  function addContextPairs(out, value) {
    [
      'field',
      'missing_input',
      'missingInput',
      'requirement',
      'gap_type',
      'gapType',
      'required_by',
      'requiredBy',
      'impact',
      'expected',
      'document_name',
      'documentName',
      'document',
      'required_document_count',
      'requiredDocumentCount',
      'forms_with_url_count',
      'formsWithUrlCount',
      'signature_required_count',
      'signatureRequiredCount',
      'signature_unknown_count',
      'signatureUnknownCount',
      'needs_user_confirmation',
      'needsUserConfirmation',
      'status',
      'priority',
      'severity',
      'risk_level',
      'riskLevel',
      'overall_risk',
      'overallRisk',
      'risk_score',
      'riskScore',
      'gap_code',
      'gapCode',
      'reason_code',
      'reasonCode',
      'code',
      'category',
      'scope',
      'checked_scope',
      'checkedScope',
      'remedy',
      'program_a',
      'programA',
      'program_b',
      'programB',
      'verdict',
      'all_pairs_status',
      'allPairsStatus',
      'total_pairs',
      'totalPairs',
      'action_id',
      'actionId',
      'action_type',
      'actionType',
      'label_ja',
      'labelJa',
      'detail_ja',
      'detailJa',
      'human_review_required',
      'blocking',
      'semi_blocking',
      'semiBlocking',
    ].forEach(function (key) {
      if (value[key] != null) addPrimitivePair(out, key, value[key]);
    });
  }

  function addFallbackPairs(out, value) {
    let added = 0;
    for (const key of Object.keys(value)) {
      if (added >= 4) break;
      if (/_url$|Url$|href|endpoint/i.test(key)) continue;
      const child = value[key];
      if (isPlainObject(child) || Array.isArray(child) || isEmptyValue(child)) continue;
      addPrimitivePair(out, key, child);
      added += 1;
    }
  }

  function appendValueItems(out, value, groupId, depth) {
    if (out.length >= 8 || depth > 2 || isEmptyValue(value)) return;
    if (Array.isArray(value)) {
      for (const item of value.slice(0, 8)) {
        appendValueItems(out, item, groupId, depth + 1);
        if (out.length >= 8) break;
      }
      return;
    }
    if (isPlainObject(value)) {
      const before = out.length;
      if (groupId === 'risk') addRiskItems(out, value);
      if (groupId === 'decision') addDecisionItems(out, value);
      if (groupId === 'knownGaps') addKnownGapItems(out, value);
      if (groupId === 'signals') addSignalItems(out, value);
      if (groupId === 'fundingStack') addFundingStackItems(out, value);
      addObjectTextFields(out, value, groupId);
      addContextPairs(out, value);
      if (out.length === before) addFallbackPairs(out, value);
      return;
    }
    pushValueItem(out, humanValueText(value));
  }

  function valueItems(value, groupId) {
    const out = [];
    appendValueItems(out, value, groupId, 0);
    return out.slice(0, 6);
  }

  function combinedValueItems(foundFields, groupId) {
    const out = [];
    const fieldKeys = [];
    const perFieldLimit = foundFields.length > 1 ? 2 : 6;
    for (const found of foundFields) {
      const items = valueItems(found.value, groupId);
      let contributed = false;
      for (const item of items.slice(0, perFieldLimit)) {
        const before = out.length;
        pushValueItem(out, item);
        if (out.length > before) contributed = true;
        if (out.length >= 6) break;
      }
      if (contributed && fieldKeys.indexOf(found.key) < 0) {
        fieldKeys.push(found.key);
      }
      if (out.length >= 6) break;
    }
    return {
      fieldKey: fieldKeys.slice(0, 3).join(' + ') + (fieldKeys.length > 3 ? ' +' + (fieldKeys.length - 3) : ''),
      items: out.slice(0, 6),
    };
  }

  function renderValueFields(body) {
    if (!els.valueFields || !els.valueGrid) return;
    const containers = responseValueContainers(body);
    const groups = [];
    for (const group of VALUE_FIELD_GROUPS) {
      const foundFields = fieldsByKeys(containers, group.keys);
      if (!foundFields.length) continue;
      const combined = combinedValueItems(foundFields, group.id);
      if (!combined.items.length) continue;
      groups.push({
        title: group.title,
        subtitle: group.subtitle,
        fieldKey: combined.fieldKey,
        items: combined.items,
      });
    }
    if (!groups.length) {
      hideValueFields();
      return;
    }
    safeText(els.valueSummary, 'レスポンス内の価値フィールドを、人が判断しやすい形に抜き出しました。JSON 全文は下に残しています。');
    els.valueGrid.innerHTML = groups.map(function (group) {
      const itemsHtml = group.items.map(function (item) {
        return '<li>' + escapeHtml(item) + '</li>';
      }).join('');
      return '<section class="pg-value-block">' +
        '<div class="pg-value-block-head">' +
        '<h3 class="pg-value-title">' + escapeHtml(group.title) + '</h3>' +
        '<span class="pg-value-field-key"><code>' + escapeHtml(group.fieldKey) + '</code></span>' +
        '</div>' +
        '<p class="pg-value-subtitle">' + escapeHtml(group.subtitle) + '</p>' +
        '<ul class="pg-value-list">' + itemsHtml + '</ul>' +
        '</section>';
    }).join('');
    els.valueFields.hidden = false;
  }

  /**
   * Render a value as JSON with very small client-side syntax highlight.
   * Pure regex pass — does NOT eval — handles strings (incl. escaped
   * quotes), numbers, bool, null, and keys. Cap at 200 KB to avoid
   * pathological pretty-print on huge responses.
   */
  function highlightJson(obj) {
    let json;
    try {
      json = JSON.stringify(obj, null, 2);
    } catch (_e) {
      return escapeHtml(String(obj));
    }
    if (json.length > 200000) {
      return escapeHtml(json.slice(0, 200000)) + '\n\n... (truncated at 200 KB — full body in DevTools Network tab)';
    }
    json = escapeHtml(json);
    json = json.replace(
      /("(\\u[0-9a-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(\.\d+)?([eE][+-]?\d+)?)/g,
      function (match) {
        let cls = 'json-number';
        if (/^"/.test(match)) {
          cls = /:$/.test(match) ? 'json-key' : 'json-string';
        } else if (/true|false/.test(match)) {
          cls = 'json-bool';
        } else if (/null/.test(match)) {
          cls = 'json-null';
        }
        return '<span class="' + cls + '">' + match + '</span>';
      }
    );
    return json;
  }

  /**
   * Compose URL from current endpoint + form values.
   * Returns { url, query, path, body, bodyError } — display strips empty values
   * because the user gets confused when they see `?q=&tier=` with a lot
   * of empty pairs.
   */
  function paramLocation(param) {
    if (param.isPath) return 'path';
    return param.in || 'query';
  }

  function splitArrayValue(value) {
    return String(value || '')
      .split(/[\n,]+/)
      .map(function (v) { return v.trim(); })
      .filter(Boolean);
  }

  function buildUrl() {
    const ep = currentEndpoint;
    let path = ep.path;
    const params = new URLSearchParams();
    const pathSubstitutions = {};
    const requestBody = {};
    let hasBody = false;
    let bodyError = '';

    function addBodyValue(name, value, force) {
      if (!force && isEmptyValue(value)) return;
      requestBody[name] = value;
      hasBody = true;
    }

    for (const param of ep.params) {
      const inputs = els.params.querySelectorAll('[data-name="' + param.name + '"]');
      const location = paramLocation(param);
      if (param.type === 'multi') {
        // multi-select renders as multiple <select> — read .selectedOptions
        const sel = inputs[0];
        const values = [];
        if (sel && sel.selectedOptions) {
          for (const opt of sel.selectedOptions) {
            if (opt.value) values.push(opt.value);
          }
        }
        if (location === 'body') {
          addBodyValue(param.name, values, param.required);
        } else {
          for (const value of values) params.append(param.name, value);
        }
        continue;
      }
      const el = inputs[0];
      if (!el) continue;
      let val;
      if (param.type === 'checkbox') {
        if (location === 'body') {
          addBodyValue(param.name, !!el.checked, true);
        } else if (el.checked) {
          params.append(param.name, 'true');
        }
        continue;
      } else if (param.type === 'array') {
        const values = splitArrayValue(el.value);
        if (location === 'body') {
          addBodyValue(param.name, values, param.required);
        } else {
          for (const value of values) params.append(param.name, value);
        }
        continue;
      } else if (param.type === 'json') {
        val = (el.value || '').trim();
        if (val === '') {
          if (location === 'body' && param.required) addBodyValue(param.name, null, true);
          continue;
        }
        try {
          const parsed = JSON.parse(val);
          if (location === 'body') addBodyValue(param.name, parsed, true);
          else params.append(param.name, val);
        } catch (e) {
          bodyError = bodyError || (param.name + ' は有効な JSON ではありません: ' + (e && e.message ? e.message : String(e)));
        }
        continue;
      } else {
        val = (el.value || '').trim();
      }
      if (param.isPath) {
        pathSubstitutions[param.name] = val || '';
      } else if (location === 'body') {
        if (val === '' && !param.required) continue;
        if (param.type === 'number') {
          const n = Number(val);
          if (val !== '' && Number.isFinite(n)) {
            addBodyValue(param.name, n, true);
          } else if (param.required) {
            addBodyValue(param.name, null, true);
          } else if (val !== '') {
            bodyError = bodyError || (param.name + ' は数値で入力してください。');
          }
        } else {
          addBodyValue(param.name, val, param.required);
        }
      } else if (val !== '') {
        params.append(param.name, val);
      }
    }

    // path-param substitution
    for (const [k, v] of Object.entries(pathSubstitutions)) {
      path = path.replace('{' + k + '}', encodeURIComponent(v));
    }

    const qs = params.toString();
    const url = API_BASE + path + (qs ? '?' + qs : '');
    return {
      url: url,
      query: qs,
      path: path,
      body: hasBody ? requestBody : null,
      bodyError: bodyError,
    };
  }

  function paramFieldHtml(p) {
    const label = '<span>' + escapeHtml(p.label || p.name) + (p.required ? ' <span style="color:var(--danger)">*</span>' : '') + '</span>';
    const baseAttr = 'data-name="' + escapeHtml(p.name) + '" id="pg-p-' + escapeHtml(p.name) + '"';
    if (p.type === 'enum') {
      const opts = (p.options || []).map(function (o) {
        const sel = (o === (p.defaultValue || '')) ? ' selected' : '';
        const disp = o === '' ? '(なし)' : o;
        return '<option value="' + escapeHtml(o) + '"' + sel + '>' + escapeHtml(disp) + '</option>';
      }).join('');
      return '<div class="pg-field"><label for="pg-p-' + escapeHtml(p.name) + '">' + label + '</label>' +
             '<select ' + baseAttr + '>' + opts + '</select></div>';
    }
    if (p.type === 'multi') {
      const opts = (p.options || []).map(function (o) {
        return '<option value="' + escapeHtml(o) + '">' + escapeHtml(o) + '</option>';
      }).join('');
      return '<div class="pg-field"><label for="pg-p-' + escapeHtml(p.name) + '">' + label +
             '<span class="pg-hint">⌘ / Ctrl で複数選択</span></label>' +
             '<select multiple size="4" ' + baseAttr + '>' + opts + '</select></div>';
    }
    if (p.type === 'checkbox') {
      const checked = p.defaultChecked ? ' checked' : '';
      return '<div class="pg-field"><div class="pg-checkbox-row">' +
             '<input type="checkbox" ' + baseAttr + checked + '>' +
             '<label for="pg-p-' + escapeHtml(p.name) + '">' + escapeHtml(p.label || p.name) + '</label>' +
             '</div></div>';
    }
    if (p.type === 'json' || p.type === 'array') {
      const placeholder = p.placeholder ? ' placeholder="' + escapeHtml(p.placeholder) + '"' : '';
      const rows = p.type === 'array' ? '3' : '4';
      const def = p.defaultValue ? escapeHtml(p.defaultValue) : '';
      return '<div class="pg-field"><label for="pg-p-' + escapeHtml(p.name) + '">' + label + '</label>' +
             '<textarea rows="' + rows + '" ' + baseAttr + placeholder + ' spellcheck="false">' + def + '</textarea></div>';
    }
    let inputType = 'text';
    if (p.type === 'number') inputType = 'number';
    if (p.type === 'date') inputType = 'date';
    const placeholder = p.placeholder ? ' placeholder="' + escapeHtml(p.placeholder) + '"' : '';
    const def = p.defaultValue ? ' value="' + escapeHtml(p.defaultValue) + '"' : '';
    return '<div class="pg-field"><label for="pg-p-' + escapeHtml(p.name) + '">' + label + '</label>' +
           '<input type="' + inputType + '" ' + baseAttr + placeholder + def + '></div>';
  }

  function renderEndpointSelect() {
    const html = ENDPOINTS.map(function (ep, i) {
      return '<option value="' + i + '">' + escapeHtml(ep.method + ' ' + ep.path) + ' — ' + escapeHtml(ep.title) + '</option>';
    }).join('');
    els.endpoint.innerHTML = html;
  }

  function renderParams() {
    const html = currentEndpoint.params.map(paramFieldHtml).join('');
    els.params.innerHTML = html;
    safeText(els.endpointDesc, currentEndpoint.desc || '');
    // Wire up onchange/oninput → URL preview update.
    const inputs = els.params.querySelectorAll('input, select, textarea');
    for (const inp of inputs) {
      inp.addEventListener('input', updateUrlPreview);
      inp.addEventListener('change', updateUrlPreview);
    }
    updateUrlPreview();
  }

  function applyQueryParamsToCurrentEndpoint(qs) {
    if (!qs) return;
    let touched = false;
    for (const param of currentEndpoint.params) {
      if (!qs.has(param.name)) continue;
      const inputs = els.params.querySelectorAll('[data-name="' + param.name + '"]');
      const input = inputs[0];
      if (!input) continue;
      const values = qs.getAll(param.name).map(function (v) { return String(v); });
      if (param.type === 'multi') {
        const wanted = new Set(values.flatMap(function (v) { return splitArrayValue(v); }));
        for (const opt of input.options || []) {
          opt.selected = wanted.has(opt.value);
        }
        touched = true;
        continue;
      }
      if (param.type === 'checkbox') {
        const raw = (values[values.length - 1] || '').trim().toLowerCase();
        input.checked = !['', '0', 'false', 'no', 'off'].includes(raw);
        touched = true;
        continue;
      }
      input.value = values[values.length - 1] || '';
      touched = true;
    }
    if (touched) updateUrlPreview();
  }

  function updateUrlPreview() {
    const { url } = buildUrl();
    safeText(els.urlText, url);
    const methodEl = els.urlPreview.querySelector('.pg-url-method');
    if (methodEl) safeText(methodEl, currentEndpoint.method);
    updateExportLinks(url);
  }

  function updateExportLinks(url) {
    // Postman: postman://... can hijack the user's app. Use the public web
    // builder instead — it's URL-agnostic, no install required.
    els.openPostman.href = 'https://www.postman.com/runner?url=' + encodeURIComponent(url);
    // HTTPie web — accepts ?url= deep-link.
    els.openHttpie.href = 'https://httpie.io/app?url=' + encodeURIComponent(url);
  }

  function shellQuote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
  }

  function buildCurl() {
    const { url, body } = buildUrl();
    const method = (currentEndpoint.method || 'GET').toUpperCase();
    const bearer = (els.bearer.value || '').trim();
    const parts = ['curl -sS'];
    if (method !== 'GET') parts.push('-X ' + method);
    parts.push(shellQuote(url));
    parts.push('-H ' + shellQuote('Accept: application/json'));
    if (bearer) {
      parts.push('-H ' + shellQuote('Authorization: Bearer ' + bearer));
    }
    if (body != null) {
      parts.push('-H ' + shellQuote('Content-Type: application/json'));
      parts.push('--data-raw ' + shellQuote(JSON.stringify(body)));
    }
    return parts.join(' \\\n  ');
  }

  // ----- 4. Quota indicator ----------------------------------------------
  function updateQuota(remainingHeader) {
    if (remainingHeader == null) return; // no header → keep existing display
    const n = parseInt(remainingHeader, 10);
    if (isNaN(n)) return;
    lastQuotaRemaining = n;
    safeText(els.quotaRemaining, String(Math.max(0, n)));
    // Anonymous quota = 3 req/day per IP. warn when 1 left, over when 0.
    let state = 'ok';
    if (n <= 0) state = 'over';
    else if (n <= 1) state = 'warn';
    els.quota.dataset.state = state;
    els.quotaCta.hidden = (state === 'ok');
  }

  // ----- 5. Send -------------------------------------------------------
  async function send() {
    const now = Date.now();
    if (inflight) return;
    if (now - lastSendAt < SEND_DEBOUNCE_MS) return;
    lastSendAt = now;
    inflight = true;
    els.send.disabled = true;
    safeText(els.send, '送信中…');
    hideConversionCta();
    hideValueFields();

    const request = buildUrl();
    const url = request.url;
    const requestBody = request.body;
    const bodyError = request.bodyError;
    const bearer = (els.bearer.value || '').trim();
    const headers = { 'Accept': 'application/json' };
    if (bearer) headers['Authorization'] = 'Bearer ' + bearer;
    const method = (currentEndpoint.method || 'GET').toUpperCase();

    if (bodyError) {
      inflight = false;
      els.send.disabled = false;
      safeText(els.send, '送信 (Send)');
      els.response.hidden = false;
      els.status.textContent = 'INVALID';
      els.status.dataset.class = '4xx';
      safeText(els.duration, '-- ms');
      els.body.innerHTML = highlightJson({ error: 'invalid_request_body', detail: bodyError });
      els.headers.innerHTML = '';
      return;
    }
    const fetchOptions = {
      method: method,
      headers: headers,
      credentials: 'omit',
    };
    if (requestBody != null && method !== 'GET' && method !== 'HEAD') {
      headers['Content-Type'] = 'application/json';
      fetchOptions.body = JSON.stringify(requestBody);
    }

    const t0 = performance.now();
    let resp, body, errMsg;
    try {
      resp = await fetch(url, fetchOptions);
      const text = await resp.text();
      try { body = JSON.parse(text); }
      catch (_e) { body = { _raw: text }; }
    } catch (e) {
      errMsg = e && e.message ? e.message : String(e);
    }
    const ms = Math.round(performance.now() - t0);

    inflight = false;
    els.send.disabled = false;
    safeText(els.send, '送信 (Send)');

    els.response.hidden = false;
    if (errMsg) {
      els.status.textContent = 'NETWORK';
      els.status.dataset.class = '5xx';
      safeText(els.duration, ms + ' ms');
      els.body.innerHTML = highlightJson({ error: 'fetch failed', detail: errMsg, hint: 'CORS / DNS / offline. Try again or open DevTools Network tab.' });
      els.headers.innerHTML = '';
      return;
    }

    const statusClass = String(resp.status).charAt(0) + 'xx';
    safeText(els.status, resp.status + ' ' + (resp.statusText || ''));
    els.status.dataset.class = statusClass;
    safeText(els.duration, ms + ' ms');
    els.body.innerHTML = highlightJson(body);
    renderValueFields(body);
    renderConversionCta(body, resp.status);

    // Render response headers (collapsible). fetch does not expose all
    // headers due to CORS — only "simple" + explicitly Access-Control-
    // Expose-Headers'd ones. The X-Anon-Quota-Remaining is exposed by the
    // server middleware; if it ever stops, we fall back gracefully.
    const headerEntries = [];
    if (resp.headers && resp.headers.forEach) {
      resp.headers.forEach(function (v, k) {
        headerEntries.push([k, v]);
      });
    }
    headerEntries.sort(function (a, b) { return a[0].localeCompare(b[0]); });
    els.headers.innerHTML = headerEntries.map(function (kv) {
      return '<dt>' + escapeHtml(kv[0]) + '</dt><dd>' + escapeHtml(kv[1]) + '</dd>';
    }).join('') || '<dd>(ヘッダーなし — fetch の CORS 制約により公開ヘッダー以外は取得できません)</dd>';

    // Quota: try X-Anon-Quota-Remaining (lowercase via fetch Headers API).
    const quotaHdr = resp.headers.get('x-anon-quota-remaining') || resp.headers.get('X-Anon-Quota-Remaining');
    updateQuota(quotaHdr);

    // Bump success counter (2xx only) → maybe show conversion nudge.
    let count = 0;
    try { count = parseInt(sessionStorage.getItem(STORAGE_KEY) || '0', 10) || 0; }
    catch (_e) {}
    if (resp.ok) {
      try {
        count += 1;
        sessionStorage.setItem(STORAGE_KEY, String(count));
      } catch (_e) {}
    }
    // Always re-evaluate the nudge: quota may have dropped to 0 without a
    // 2xx (e.g. an upstream 429), in which case we still want stage 3.
    if (resp.ok || resp.status === 429 || (lastQuotaRemaining != null && lastQuotaRemaining <= 0)) {
      maybeShowNudge(count);
    }

    // Analytics breadcrumb (GA4 dataLayer if present).
    try {
      if (window.dataLayer && typeof window.dataLayer.push === 'function') {
        window.dataLayer.push({
          event: 'playground_request',
          endpoint_id: currentEndpoint.id,
          status: resp.status,
          duration_ms: ms,
        });
      }
    } catch (_e) { /* analytics best-effort */ }

    // Funnel beacon: request, success, and quota-exhaustion signals.
    try {
      if (typeof window.jpciteTrack === 'function') {
        window.jpciteTrack('playground_request', {
          endpoint_id: currentEndpoint.id,
          status: resp.status,
        });
        if (resp.ok) {
          window.jpciteTrack('playground_success', {
            endpoint_id: currentEndpoint.id,
            success_count: count,
          });
        }
        // Quota header reads "remaining"; <=0 means the next call will 429.
        if (lastQuotaRemaining != null && lastQuotaRemaining <= 0) {
          window.jpciteTrack('playground_quota_exhausted', {
            endpoint_id: currentEndpoint.id,
          });
        }
      }
    } catch (_e) { /* analytics best-effort */ }
  }

  // ----- 5b. 3-stage nudge ----------------------------------------------
  // Stage 1 (1st success): tell the visitor to copy the curl one-liner so
  // they can replay the request offline. Validates "you can hit this from
  // your shell, no SDK".
  // Stage 2 (2nd success): point at MCP install + OpenAPI import. This is
  // the recurring-use surface — visitors who get here are evaluating
  // whether to integrate, not just curious.
  // Stage 3 (3rd success OR quota_remaining <= 0): pricing + API key.
  // The hard quota fence is upstream (HTTP 429); this nudge is the soft
  // pre-fence so they don't hit a wall cold.
  const NUDGE_STAGES = [
    {
      // Stage 1
      text: '1 リクエスト成功。 オフラインで再現するなら下の curl をコピー →',
      label: 'curl をコピー →',
      href: '#pg-copy-curl',
      action: function() {
        if (els.copyCurl && els.copyCurl.click) els.copyCurl.click();
      },
    },
    {
      // Stage 2
      text: '2 リクエスト成功。 繰り返し使うなら MCP / OpenAPI を取り込み →',
      label: 'MCP / OpenAPI →',
      href: '/docs/getting-started/',
    },
    {
      // Stage 3 (or quota exhausted before reaching it)
      text: '今日の無料枠を使い切りました。このまま API キーで同じ品質の結果を継続取得できます →',
      label: 'API キー発行 →',
      href: 'pricing.html#api-paid',
    },
  ];

  function nudgeStageFor(count, quotaRemaining) {
    // Quota exhaustion always promotes to the final stage.
    if (quotaRemaining != null && quotaRemaining <= 0) return 2;
    if (count >= 3) return 2;
    if (count === 2) return 1;
    if (count === 1) return 0;
    return -1;
  }

  function maybeShowNudge(count) {
    const stageIdx = nudgeStageFor(count, lastQuotaRemaining);
    if (stageIdx < 0 || stageIdx >= NUDGE_STAGES.length) return;
    let dismissed = '';
    try { dismissed = sessionStorage.getItem(NUDGE_KEY) || ''; } catch (_e) {}
    // dismissed value records the latest dismissed stage index. Re-show only
    // when the next stage unlocks.
    const dismissedIdx = parseInt(dismissed, 10);
    if (!isNaN(dismissedIdx) && dismissedIdx >= stageIdx) return;

    const stage = NUDGE_STAGES[stageIdx];
    safeText(els.nudgeText, stage.text);
    safeText(els.nudgeLink, stage.label);
    els.nudgeLink.setAttribute('href', stage.href);
    els.nudgeLink.dataset.cta = 'playground-nudge-stage-' + (stageIdx + 1);
    els.nudgeLink.onclick = function(ev) {
      if (typeof stage.action === 'function') {
        ev.preventDefault();
        stage.action();
      }
      // else: regular navigation
    };
    els.nudge.classList.add('is-visible');
  }

  function dismissNudge() {
    els.nudge.classList.remove('is-visible');
    const count = (function() {
      try { return parseInt(sessionStorage.getItem(STORAGE_KEY) || '0', 10) || 0; }
      catch (_e) { return 0; }
    })();
    const stageIdx = nudgeStageFor(count, lastQuotaRemaining);
    try { sessionStorage.setItem(NUDGE_KEY, String(Math.max(0, stageIdx))); } catch (_e) {}
  }

  // ----- 6. Wire-up ------------------------------------------------------
  function init() {
    renderEndpointSelect();
    const qs = new URLSearchParams(window.location.search || '');
    const requestedEndpoint = (qs.get('endpoint') || qs.get('tool') || '').trim();
    let idx = -1;
    if (requestedEndpoint) {
      idx = ENDPOINTS.findIndex(function(ep) {
        return ep.id === requestedEndpoint || ep.path === requestedEndpoint;
      });
    }
    if (idx < 0 && qs.get('flow') === 'evidence3') {
      idx = ENDPOINTS.findIndex(function(ep) {
        return ep.id === 'intelligence.precomputed.query';
      });
      if (idx >= 0 && els.flowHint) els.flowHint.hidden = false;
      initEvidence3Wizard(qs);
    }
    if (idx >= 0) {
      currentEndpoint = ENDPOINTS[idx];
      els.endpoint.value = String(idx);
    }
    renderParams();
    applyQueryParamsToCurrentEndpoint(qs);

    els.endpoint.addEventListener('change', function() {
      currentEndpoint = ENDPOINTS[parseInt(els.endpoint.value, 10) || 0];
      renderParams();
    });

    els.send.addEventListener('click', send);
    els.reset.addEventListener('click', function() {
      // Re-render with original defaults (lose current values).
      renderParams();
      els.bearer.value = '';
      els.response.hidden = true;
      hideConversionCta();
      hideValueFields();
    });

    els.bearer.addEventListener('input', updateUrlPreview);

    els.headersToggle.addEventListener('click', function() {
      const open = els.headers.classList.toggle('is-open');
      els.headersToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      safeText(els.headersToggle, open ? 'レスポンスヘッダー (折りたたむ)' : 'レスポンスヘッダー (展開)');
    });

    els.copyCurl.addEventListener('click', async function() {
      const cmd = buildCurl();
      // Fires before clipboard so we capture intent even if clipboard write fails.
      try {
        if (typeof window.jpciteTrack === 'function') {
          window.jpciteTrack('quickstart_copy', {
            snippet: 'playground-curl',
            endpoint_id: currentEndpoint && currentEndpoint.id,
          });
        }
      } catch (_e) {}
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(cmd);
        } else {
          // Fallback: textarea + execCommand.
          const ta = document.createElement('textarea');
          ta.value = cmd;
          ta.style.position = 'fixed'; ta.style.top = '-1000px';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
        }
        const original = els.copyCurl.textContent;
        safeText(els.copyCurl, 'コピー済み ✓');
        setTimeout(function() { safeText(els.copyCurl, original); }, 2500);
      } catch (e) {
        // Last-resort fallback: prompt so the user can manually copy.
        // Some restrictive browsers (Safari iOS) without
        // navigator.clipboard expose only this path.
        window.prompt('curl コマンド (手動でコピーしてください):', cmd);
      }
    });

    els.nudgeDismiss.addEventListener('click', dismissNudge);

    // If we already have N >= threshold from a prior session this tab,
    // show the nudge immediately (sessionStorage scope = this tab).
    try {
      const count = parseInt(sessionStorage.getItem(STORAGE_KEY) || '0', 10) || 0;
      maybeShowNudge(count);
    } catch (_e) {}

    // Submit on ⌘/Ctrl + Enter inside any form field.
    els.params.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        send();
      }
    });
    els.bearer.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        send();
      }
    });

    updateUrlPreview();
  }

  // ----- 7. evidence3 wizard (SSE 3-step + AI agent UA snippets) -----------
  // The wizard reuses the public anonymous quota (3 req/IP/day). Each step
  // opens an EventSource at /v1/playground/evidence3/stream?step=N&... which
  // dispatches SSE events { status | section | done | error } at ~200ms
  // progress events (see src/jpintel_mcp/api/playground_stream.py). Section payloads
  // are rendered into a per-step grid; the raw stream log stays visible for
  // debugging.
  //
  // UA detection picks one of {claude, chatgpt, cursor, cline, browser}
  // from navigator.userAgent. Each agent gets a tailored install snippet
  // so the visitor sees the exact 1-line command for their environment.

  const EV3_SSE_BASE = (function () {
    // Match the anonymous API host (same origin policy + CORS allowlist).
    // Allow override via <meta name="jpcite-api-base"> for local dev.
    const meta = document.querySelector('meta[name="jpcite-api-base"]');
    if (meta && meta.content) return meta.content.replace(/\/$/, '');
    return 'https://api.jpcite.com';
  })();

  function detectAgentUA() {
    // navigator.userAgent is the canonical surface. We additionally probe a
    // small set of vendor hints because Anthropic / OpenAI custom clients
    // sometimes set product names without the literal "Mozilla/" prefix.
    const ua = (navigator.userAgent || '').toLowerCase();
    if (/claude/.test(ua) || /anthropic/.test(ua)) return 'claude';
    if (/chatgpt|openai|gptbot/.test(ua)) return 'chatgpt';
    if (/cursor/.test(ua)) return 'cursor';
    if (/cline|continue\.dev/.test(ua)) return 'cline';
    return 'browser';
  }

  const EV3_AGENT_SNIPPETS = {
    claude: {
      display: 'Claude (Desktop / Code / claude.ai)',
      badge: 'Claude',
      snippet: 'claude mcp add jpcite -- uvx autonomath-mcp',
      hint: 'Claude Desktop / Claude Code に 1 行追加すると 151 tools が即利用可能。続きは API キーで継続できます。',
    },
    chatgpt: {
      display: 'ChatGPT (Custom GPT / Actions)',
      badge: 'ChatGPT',
      snippet: 'Action URL: https://api.jpcite.com/openapi.agent.gpt30.json\nAuth: Bearer jc_xxxx (発行後)',
      hint: 'ChatGPT の Custom GPT に Action として登録。anonymous でも 3 req/日 までは無認証で試せます。',
    },
    cursor: {
      display: 'Cursor',
      badge: 'Cursor',
      snippet: '// ~/.cursor/mcp.json\n{\n  "mcpServers": {\n    "jpcite": {\n      "command": "uvx",\n      "args": ["autonomath-mcp"]\n    }\n  }\n}',
      hint: '~/.cursor/mcp.json に jpcite サーバーを追加 → Cursor 再起動で 151 tools が候補に。',
    },
    cline: {
      display: 'Cline (VS Code)',
      badge: 'Cline',
      snippet: '// Cline → MCP Servers → Add server\n// Command: uvx\n// Args: autonomath-mcp\n// Env: JPCITE_API_KEY=jc_xxxx (任意)',
      hint: 'VS Code の Cline 拡張から MCP Server を追加。anonymous は 3 req/日 までキー不要。',
    },
    browser: {
      display: '通常 browser',
      badge: 'browser',
      snippet: '# 試行用 curl (anonymous 3 req/日)\ncurl -sS \'https://api.jpcite.com/v1/intelligence/precomputed/query?intent=capex_subsidy\' \\\n  -H \'Accept: application/json\'',
      hint: 'AI agent からの接続は検出できませんでした。curl / Postman / HTTPie で同じ URL を即試せます。',
    },
  };

  function applyAgentPanel(agent) {
    const cfg = EV3_AGENT_SNIPPETS[agent] || EV3_AGENT_SNIPPETS.browser;
    const display = document.getElementById('ev3-agent-display');
    const badge = document.getElementById('ev3-agent-badge');
    const snip = document.getElementById('ev3-agent-snippet');
    const hint = document.getElementById('ev3-agent-hint');
    if (display) display.textContent = cfg.display;
    if (badge) badge.textContent = cfg.badge;
    if (snip) snip.textContent = cfg.snippet;
    if (hint) hint.textContent = cfg.hint;
    const switchBtns = document.querySelectorAll('#ev3-agent-panel .ev3-agent-switch button');
    for (let i = 0; i < switchBtns.length; i++) {
      switchBtns[i].setAttribute('aria-pressed', switchBtns[i].dataset.agent === agent ? 'true' : 'false');
    }
  }

  function ev3SetStepState(stepNum, state) {
    const stepEl = document.getElementById('ev3-step-' + stepNum);
    if (stepEl) stepEl.dataset.state = state;
    const cell = document.querySelector('.ev3-progress-cell[data-step="' + stepNum + '"]');
    if (cell) cell.dataset.state = state === 'locked' ? 'pending' : state === 'done' ? 'done' : 'active';
    const progress = document.getElementById('ev3-progress');
    if (progress && state === 'active') progress.setAttribute('aria-valuenow', String(stepNum));
    // expand body for active|done, collapse for locked
    const body = document.getElementById('ev3-step-' + stepNum + '-body');
    if (body) {
      body.hidden = (state === 'locked');
    }
  }

  function ev3SetStepStatus(stepNum, label, state) {
    const el = document.getElementById('ev3-step-' + stepNum + '-status');
    if (!el) return;
    el.textContent = label;
    if (state) el.dataset.state = state;
  }

  function ev3AppendLog(stepNum, eventName, data) {
    const log = document.getElementById('ev3-step-' + stepNum + '-log');
    if (!log) return;
    log.hidden = false;
    const line = document.createElement('div');
    line.className = 'ev3-log-line';
    line.dataset.event = eventName;
    // tiny inline pretty-print: section name first, then key fields
    let head = eventName;
    if (data && typeof data === 'object') {
      if (data.name) head += ': ' + data.name;
      else if (data.phase) head += ': ' + data.phase;
      else if (data.step != null) head += ': step ' + data.step + ' done';
    }
    const span = document.createElement('span');
    span.className = 'ev3-log-key';
    span.textContent = head;
    line.appendChild(span);
    if (data) {
      const json = document.createElement('span');
      json.textContent = ' ' + JSON.stringify(data);
      line.appendChild(json);
    }
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  function ev3AppendSection(stepNum, sectionName, sectionData) {
    const grid = document.getElementById('ev3-step-' + stepNum + '-grid');
    if (!grid) return;
    grid.hidden = false;
    const card = document.createElement('div');
    card.className = 'ev3-section-card';
    card.dataset.section = sectionName;
    const title = document.createElement('p');
    title.className = 'ev3-section-card-title';
    title.textContent = sectionName;
    card.appendChild(title);
    const value = document.createElement('p');
    value.className = 'ev3-section-card-value';
    // summarize: count / first key
    let summary = '';
    if (sectionData == null) {
      summary = '(empty)';
    } else if (Array.isArray(sectionData)) {
      summary = sectionData.length + ' 件';
    } else if (typeof sectionData === 'object') {
      const keys = Object.keys(sectionData);
      const k = keys[0];
      if (k != null) {
        summary = k + ' = ' + JSON.stringify(sectionData[k]);
        if (keys.length > 1) summary += ' +' + (keys.length - 1);
      } else {
        summary = '(no keys)';
      }
    } else {
      summary = String(sectionData);
    }
    value.textContent = summary;
    card.appendChild(value);
    grid.appendChild(card);
  }

  function ev3UpdateAnonPill(remaining) {
    const pill = document.getElementById('ev3-anon-pill');
    const span = document.getElementById('ev3-anon-remain');
    if (!pill || !span) return;
    if (remaining == null || isNaN(remaining)) {
      span.textContent = '--';
      return;
    }
    span.textContent = String(Math.max(0, remaining));
    let state = 'ok';
    if (remaining <= 0) state = 'over';
    else if (remaining <= 1) state = 'warn';
    pill.dataset.state = state;
  }

  // Try to pull quota_remaining from any non-stream JSON response we touch.
  // The SSE stream does NOT carry HTTP response headers, but a follow-up
  // probe call to GET /v1/me/quota or /healthz?probe=1 can fill the gap.
  function ev3ProbeQuota() {
    // Use a cheap public route. If CORS strips X-Anon-Quota-Remaining, we
    // also accept a JSON body field named `quota_remaining`.
    try {
      fetch(EV3_SSE_BASE + '/v1/me/quota', { credentials: 'omit', headers: { Accept: 'application/json' } })
        .then(function (r) {
          const hdr = r.headers.get('x-anon-quota-remaining') || r.headers.get('X-Anon-Quota-Remaining') || r.headers.get('x-anon-remaining');
          if (hdr != null) ev3UpdateAnonPill(parseInt(hdr, 10));
          return r.json().catch(function () { return null; });
        })
        .then(function (j) {
          if (j && typeof j.quota_remaining === 'number') ev3UpdateAnonPill(j.quota_remaining);
        })
        .catch(function () { /* offline / no route → keep '--' */ });
    } catch (_e) {}
  }

  function ev3RunStep(stepNum, params) {
    return new Promise(function (resolve, reject) {
      const qs = new URLSearchParams();
      qs.set('step', String(stepNum));
      Object.keys(params || {}).forEach(function (k) {
        if (params[k] != null && params[k] !== '') qs.set(k, String(params[k]));
      });
      const url = EV3_SSE_BASE + '/v1/playground/evidence3/stream?' + qs.toString();
      let es;
      try {
        es = new EventSource(url);
      } catch (e) {
        reject(e);
        return;
      }
      ev3SetStepStatus(stepNum, 'SSE 接続中…', 'streaming');
      // EventSource maps named SSE events via addEventListener; the
      // server-side playground_stream emits status / section / done / error.
      es.addEventListener('status', function (ev) {
        try {
          const data = JSON.parse(ev.data);
          ev3AppendLog(stepNum, 'status', data);
          ev3SetStepStatus(stepNum, (data.phase || 'streaming') + ' …', 'streaming');
        } catch (_e) {}
      });
      es.addEventListener('section', function (ev) {
        try {
          const data = JSON.parse(ev.data);
          ev3AppendLog(stepNum, 'section', data);
          ev3AppendSection(stepNum, data.name || 'section', data.data);
        } catch (_e) {}
      });
      es.addEventListener('done', function (ev) {
        try {
          const data = JSON.parse(ev.data);
          ev3AppendLog(stepNum, 'done', data);
          ev3SetStepStatus(stepNum, 'done (' + (data.elapsed_ms || 0) + ' ms, ' + (data.billable_units || 1) + ' unit)', 'done');
          if (data.next && stepNum === 3) {
            const link = document.getElementById('ev3-open-artifact');
            if (link) {
              link.href = data.next;
              link.hidden = false;
            }
          }
          es.close();
          // After each step, refresh the anon quota pill (in case the
          // billable unit was deducted from the anonymous bucket).
          ev3ProbeQuota();
          resolve(data);
        } catch (e) {
          es.close();
          reject(e);
        }
      });
      es.addEventListener('error', function (ev) {
        // EventSource fires `error` both for transport errors AND for our
        // server-side `event: error` payloads. Try to JSON-parse the data.
        try {
          if (ev && ev.data) {
            const data = JSON.parse(ev.data);
            ev3AppendLog(stepNum, 'error', data);
            ev3SetStepStatus(stepNum, 'error: ' + (data.message || 'unknown'), 'error');
          } else {
            ev3SetStepStatus(stepNum, 'SSE 切断 (transport error)', 'error');
          }
        } catch (_e) {
          ev3SetStepStatus(stepNum, 'SSE 切断', 'error');
        }
        es.close();
        reject(new Error('sse_error'));
      });
    });
  }

  function ev3CollectIntents() {
    const boxes = document.querySelectorAll('input[name="ev3-intent"]:checked');
    const out = [];
    for (let i = 0; i < boxes.length; i++) out.push(boxes[i].value);
    return out.join(',');
  }

  function initEvidence3Wizard(qs) {
    const wizard = document.getElementById('evidence3-wizard');
    if (!wizard) return;
    wizard.hidden = false;
    wizard.classList.add('is-active');

    // 1. UA detection → install snippet panel.
    applyAgentPanel(detectAgentUA());
    const switchBtns = document.querySelectorAll('#ev3-agent-panel .ev3-agent-switch button');
    for (let i = 0; i < switchBtns.length; i++) {
      switchBtns[i].addEventListener('click', function () {
        applyAgentPanel(this.dataset.agent || 'browser');
      });
    }

    // 2. Initial anon-quota probe (X-Anon-Quota-Remaining / quota_remaining).
    ev3ProbeQuota();

    // 3. Pre-fill houjin_bangou if it came in via ?hb=...
    const hb = qs && qs.get('hb');
    if (hb && /^\d{13}$/.test(hb)) {
      const inp = document.getElementById('ev3-houjin');
      if (inp) inp.value = hb;
    }

    // 4. Step 1 wiring.
    const houjinInput = document.getElementById('ev3-houjin');
    const run1 = document.getElementById('ev3-run-1');
    const next1 = document.getElementById('ev3-next-1');
    function refreshRun1() {
      if (run1) run1.disabled = !houjinInput || !/^\d{13}$/.test(houjinInput.value);
    }
    if (houjinInput) {
      houjinInput.addEventListener('input', refreshRun1);
      refreshRun1();
    }
    if (run1) {
      run1.addEventListener('click', function () {
        run1.disabled = true;
        ev3SetStepStatus(1, 'streaming…', 'streaming');
        ev3RunStep(1, {
          houjin_bangou: houjinInput && houjinInput.value,
          intent: ev3CollectIntents(),
          jsic: (document.getElementById('ev3-jsic') || {}).value || '',
        }).then(function () {
          if (next1) next1.disabled = false;
          try { if (typeof window.jpciteTrack === 'function') window.jpciteTrack('evidence3_step_done', { step: 1 }); } catch (_e) {}
        }).catch(function () {
          run1.disabled = false;
        });
      });
    }
    if (next1) {
      next1.addEventListener('click', function () {
        ev3SetStepState(1, 'done');
        ev3SetStepState(2, 'active');
        const run2 = document.getElementById('ev3-run-2');
        if (run2) run2.disabled = false;
        ev3SetStepStatus(2, '準備完了', 'ready');
        const target = document.getElementById('ev3-step-2');
        if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }

    // 5. Step 2 wiring.
    const run2 = document.getElementById('ev3-run-2');
    const next2 = document.getElementById('ev3-next-2');
    if (run2) {
      run2.addEventListener('click', function () {
        run2.disabled = true;
        ev3SetStepStatus(2, 'streaming…', 'streaming');
        ev3RunStep(2, {
          houjin_bangou: houjinInput && houjinInput.value,
          intent: ev3CollectIntents(),
        }).then(function () {
          if (next2) next2.disabled = false;
          try { if (typeof window.jpciteTrack === 'function') window.jpciteTrack('evidence3_step_done', { step: 2 }); } catch (_e) {}
        }).catch(function () {
          run2.disabled = false;
        });
      });
    }
    if (next2) {
      next2.addEventListener('click', function () {
        ev3SetStepState(2, 'done');
        ev3SetStepState(3, 'active');
        const run3 = document.getElementById('ev3-run-3');
        if (run3) run3.disabled = false;
        ev3SetStepStatus(3, '準備完了', 'ready');
        const target = document.getElementById('ev3-step-3');
        if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }

    // 6. Step 3 wiring.
    const run3 = document.getElementById('ev3-run-3');
    if (run3) {
      run3.addEventListener('click', function () {
        run3.disabled = true;
        ev3SetStepStatus(3, 'streaming…', 'streaming');
        const sel = document.querySelector('input[name="ev3-output"]:checked');
        ev3RunStep(3, {
          houjin_bangou: houjinInput && houjinInput.value,
          intent: ev3CollectIntents(),
        }).then(function () {
          ev3SetStepState(3, 'done');
          const final = document.getElementById('ev3-final-cta');
          if (final) final.classList.add('is-visible');
          try {
            if (typeof window.jpciteTrack === 'function') {
              window.jpciteTrack('evidence3_step_done', { step: 3 });
              window.jpciteTrack('evidence3_complete', { output: sel ? sel.value : 'dd_checklist' });
            }
          } catch (_e) {}
        }).catch(function () {
          run3.disabled = false;
        });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
