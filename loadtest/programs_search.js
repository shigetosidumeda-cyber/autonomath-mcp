// k6 load test for /v1/programs/search and /v1/programs/{unified_id}.
//
// Scenario: discovery-spike simulation (HN / Zenn / Product Hunt).
//   - 70% free-text search (FTS5-triggering ja term mix + short English)
//   - 20% filter-only search (tier + prefecture, no q)
//   - 10% get_program by real unified_id
//
// Auth mix per iteration:
//   - 80%: anonymous (no X-API-Key)
//   - 20%: paid-tier key (TEST_PAID_KEY env var — never hardcode real keys)
//
// Anon rate limit (see src/jpintel_mcp/api/anon_limit.py):
//   default 100 / JST-day / /32-or-/64. k6 from a single runner IP will
//   share one bucket, so for a 7-minute run at 50 VU we MUST keep anon
//   request volume under the limit, OR raise ANON_RATE_LIMIT_PER_MONTH on
//   the staging target before running. See loadtest/README.md §"429".
//
// Thresholds enforced:
//   - http_req_duration p(95) < 300ms
//   - http_req_failed rate < 1%
//   - checks rate > 99%
//
// Run:
//   BASE_URL=https://jpintel-mcp-staging.fly.dev \
//   TEST_PAID_KEY=jpintel_xxxxxxxxxxxx \
//   k6 run loadtest/programs_search.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { Rate, Trend } from 'k6/metrics';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const PAID_KEY = __ENV.TEST_PAID_KEY || '';
const THINK_MIN_MS = Number(__ENV.THINK_MIN_MS || 250);
const THINK_MAX_MS = Number(__ENV.THINK_MAX_MS || 750);

// When hitting anonymous quota is a concern, set ANON_SKIP=1 to route 100%
// of traffic through PAID_KEY (mirrors "post-429" cooldown). Default off.
const ANON_SKIP = __ENV.ANON_SKIP === '1';

export const options = {
  scenarios: {
    discovery_spike: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 50 },   // ramp-up
        { duration: '5m', target: 50 },   // hold
        { duration: '1m', target: 0 },    // ramp-down
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<300'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
    // Per-query-type tail budgets — looser for FTS because the
    // programs_fts JOIN + MATCH path is ~3× the cost of pk lookup.
    'http_req_duration{query_type:search_fts}': ['p(95)<350'],
    'http_req_duration{query_type:search_filter}': ['p(95)<250'],
    'http_req_duration{query_type:get_program}': ['p(95)<150'],
  },
  // Emit the summary JSON that the loadtest.yml workflow uploads.
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

// ---------------------------------------------------------------------------
// Test data — real unified_ids pulled from data/jpintel.db
// (WHERE excluded=0 ORDER BY RANDOM() LIMIT 200 at 2026-04-23)
// ---------------------------------------------------------------------------

const UNIFIED_IDS = new SharedArray('unified_ids', function () {
  return [
    "UNI-111882ab25","UNI-3464232141","UNI-4234b0e2b2","UNI-f64fe3332f","UNI-d97a6ae11b",
    "UNI-2ef9ebe3ec","UNI-39848047ac","UNI-da0291c411","UNI-6b3b30de63","UNI-db00ef6b32",
    "UNI-441e58b237","UNI-c1827149c1","UNI-83cddf15c0","UNI-0f0523ce98","UNI-f60a839b4c",
    "UNI-021e28f34c","UNI-0e4be8bd7d","UNI-a4da1563af","UNI-2b3f82e27f","UNI-5761d5b4b5",
    "UNI-fc96cb6939","UNI-3021845957","UNI-1e291f298f","UNI-71fa628ef1","UNI-8ce27551ac",
    "UNI-e72662f4b2","UNI-a42ee491ef","UNI-843b29e25e","UNI-bd71fd30eb","UNI-959a4d7e23",
    "UNI-5d8be39021","UNI-d28f025285","UNI-9dfc6dc67f","UNI-7ecfe4cccd","UNI-3e5b94f059",
    "UNI-0541028b51","UNI-6d9f19e74a","UNI-29a47ad138","UNI-c7beba818e","UNI-b82fd39829",
    "UNI-016f86c70f","UNI-03e43e94f2","UNI-e457fe2c8f","UNI-1fe4aa4b15","UNI-b60700a38c",
    "UNI-c85dfdb6c6","UNI-1a7cb51f2c","UNI-fcc9684637","UNI-d2ea20c7cf","UNI-c945dccd9d",
    "UNI-bd57bdbded","UNI-873afd09ab","UNI-33a287add3","UNI-2a2d40a7e7","UNI-5560a792ef",
    "UNI-f13ef088da","UNI-bf7457ce0f","UNI-b701626601","UNI-aaf48e9c8c","UNI-7201225ec2",
    "UNI-ded8fd31f0","UNI-49f8d9011b","UNI-f1b4df5ccf","UNI-f33ed082e7","UNI-17b4afdfbc",
    "UNI-92389fb3dd","UNI-853232e868","UNI-aae3d80ff2","UNI-2e4ce236e1","UNI-38ffb816cf",
    "UNI-af59710a11","UNI-b7cc6777f7","UNI-ee8bb5ffde","UNI-5dcb2729d6","UNI-b0b9565569",
    "UNI-accbbe49da","UNI-23ffd4bd38","UNI-4e4bf71f2c","UNI-ae6f5e8a77","UNI-a9acbc6157",
    "UNI-29aeb39303","UNI-63ff4d48bb","UNI-1a5d2e8ad3","UNI-79bf284d45","UNI-434129b22a",
    "UNI-fc1e39f4c2","UNI-0c78b21ab6","UNI-67e3557c65","UNI-028e03c617","UNI-d1c4ab3acc",
    "UNI-4fc4cf3cbb","UNI-5c3c8359ae","UNI-dca8874360","UNI-752e5d918c","UNI-121c832ef2",
    "UNI-8fc9dbbd7b","UNI-d8cdc75df3","UNI-7d8a0d9782","UNI-1d60616060","UNI-c47bf7e895",
    "UNI-c95978c7e6","UNI-749842b91b","UNI-588f4d85ce","UNI-0bc2bf8986","UNI-c00f275f0f",
    "UNI-42d6bffc51","UNI-e33410de12","UNI-5fbbb1fce8","UNI-e57e21d6e0","UNI-daca4f2af8",
    "UNI-5c37e16faa","UNI-4b83512e25","UNI-193ca9f32f","UNI-e46956a43f","UNI-7f2d7d3731",
    "UNI-de3bed75fe","UNI-fff697ab43","UNI-ee9778b003","UNI-20ebdb9cd2","UNI-737d1d672a",
    "UNI-97afeea2b5","UNI-95e9ca9f5e","UNI-074c19fc26","UNI-4ba73ad65e","UNI-566a92b28e",
    "UNI-c2eeb4aa1a","UNI-4d2a53b3ac","UNI-220fc78cc2","UNI-6015604ff0","UNI-8488eebe8f",
    "UNI-a4cffdec79","UNI-3e50a3f933","UNI-9ed05bd6ea","UNI-a9ad39cae9","UNI-63753d8dca",
    "UNI-264b0be418","UNI-2c8e16ea5a","UNI-ecfea0c918","UNI-2b2da98cd7","UNI-6afcddd019",
    "UNI-af75306d82","UNI-0d762af87a","UNI-8c901ed391","UNI-10d7364294","UNI-767b6b4692",
    "UNI-2cc50c685e","UNI-6774c7dae4","UNI-589881c4ea","UNI-355a19c4ed","UNI-c6d364983a",
    "UNI-3aca00e254","UNI-26eb4eea7d","UNI-6030c47e80","UNI-2bac077a4b","UNI-517445910e",
    "UNI-796a8afe5b","UNI-e6e3de9732","UNI-3d3d5b3f06","UNI-287f9e35f9","UNI-f8c720ea45",
    "UNI-2b7ec74bdb","UNI-35090c2627","UNI-5cdfd2ed83","UNI-7f394b7dce","UNI-ce8ba52036",
    "UNI-f05ef5fd60","UNI-1af8acba11","UNI-85767d61a8","UNI-c5766b0fd5","UNI-e6ba559d43",
    "UNI-d8db7ea6ef","UNI-3b765e100c","UNI-f7e1e5c508","UNI-a46989a5fb","UNI-ee341b1dce",
    "UNI-d86438268c","UNI-bd60ed88f5","UNI-ad44d56493","UNI-e8187d0f4f","UNI-b88a641530",
    "UNI-5544db0c99","UNI-e151a09839","UNI-65bbe91f93","UNI-41ea9544cf","UNI-702c5b6c71",
    "UNI-b8c88bc151","UNI-e4b35a7e9a","UNI-bed01927c9","UNI-17161fb991","UNI-e8fc9f760b",
    "UNI-cfb3a812ae","UNI-5e6a099c2c","UNI-28ee1d9593","UNI-4ffecc2592","UNI-845a42d96e",
    "UNI-c841ff6087","UNI-f46aa07af4","UNI-5bdf23f600","UNI-119e67c23a","UNI-d06881f7d6"
  ];
});

// FTS terms: ja-primary 3+ chars so the code in programs.search_programs
// takes the programs_fts MATCH branch (len(q_clean) >= 3), not the LIKE
// fallback. Short "IT" is included on purpose to exercise the LIKE path.
const FTS_TERMS = new SharedArray('fts_terms', function () {
  return [
    '農業', '新規就農', '補助金', '就農', '経営', '認定農業者', '担い手',
    '有機', '機械', '共済', 'スマート', 'ICT', 'パイプハウス',
    '野菜', '果樹', '水稲', '畜産', '酪農', '施設園芸',
    '環境保全', '防災', '災害', 'BCP', 'インボイス',
    '6次産業化', '輸出', '販路', '加工', '流通',
    '研修', '雇用', '奨励金', '資金', '融資',
    'IT', 'DX', 'AI',  // short terms → LIKE fallback
  ];
});

// Prefectures weighted toward actually-populated ones (北海道 has 157 rows,
// 福岡県 108, etc.). Sampling from DB 2026-04-23.
const PREFECTURES = new SharedArray('prefectures', function () {
  return [
    '北海道', '北海道', '北海道',  // weight ×3
    '福岡県', '福岡県',
    '福島県', '栃木県', '群馬県', '長崎県', '香川県',
    '兵庫県', '新潟県', '長野県', '宮城県', '宮崎県',
    '千葉県', '静岡県', '佐賀県',
    '東京都', '大阪府', '愛知県', '沖縄県',  // less populated — exercises empty / sparse path
  ];
});

const TIERS = ['S', 'A', 'B'];  // skip C (noisy) and X (excluded filter blocks it)

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const errors429 = new Rate('errors_429');
const errors5xx = new Rate('errors_5xx');
const payloadBytes = new Trend('payload_bytes');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

function authHeaders() {
  // 20% of iterations authenticate with the paid-tier test key. Anon path
  // goes through anon_limit.py; paid path has no hard cap (metered, reported
  // to Stripe usage_records per request at ¥1 tax-exclusive).
  if (ANON_SKIP || (PAID_KEY && Math.random() < 0.20)) {
    return { 'X-API-Key': PAID_KEY || '' };
  }
  return {};  // anon
}

function recordStatusMetrics(res) {
  errors429.add(res.status === 429);
  errors5xx.add(res.status >= 500);
  if (res.body) payloadBytes.add(res.body.length);
}

// ---------------------------------------------------------------------------
// Query builders
// ---------------------------------------------------------------------------

function searchFTS() {
  const q = pick(FTS_TERMS);
  const limit = [10, 20, 20, 20, 50][Math.floor(Math.random() * 5)];
  const url = `${BASE_URL}/v1/programs/search?q=${encodeURIComponent(q)}&limit=${limit}`;
  const res = http.get(url, {
    headers: authHeaders(),
    tags: { query_type: 'search_fts', name: '/v1/programs/search?q' },
  });
  recordStatusMetrics(res);
  check(res, {
    'search_fts: status 200 or 429': (r) => r.status === 200 || r.status === 429,
    'search_fts: has results array when 200': (r) =>
      r.status !== 200 || (r.json('results') !== undefined && r.json('total') !== undefined),
  });
}

function searchFilter() {
  // tier + prefecture filter, no q. Hits the non-FTS branch in search_programs.
  const params = new URLSearchParams();
  // Always at least one tier.
  const nTiers = 1 + Math.floor(Math.random() * 2);
  for (let i = 0; i < nTiers; i++) params.append('tier', pick(TIERS));
  if (Math.random() < 0.7) params.set('prefecture', pick(PREFECTURES));
  params.set('limit', '20');
  const url = `${BASE_URL}/v1/programs/search?${params.toString()}`;
  const res = http.get(url, {
    headers: authHeaders(),
    tags: { query_type: 'search_filter', name: '/v1/programs/search?tier' },
  });
  recordStatusMetrics(res);
  check(res, {
    'search_filter: status 200 or 429': (r) => r.status === 200 || r.status === 429,
    'search_filter: total present when 200': (r) =>
      r.status !== 200 || r.json('total') !== undefined,
  });
}

function getProgram() {
  const uid = pick(UNIFIED_IDS);
  const url = `${BASE_URL}/v1/programs/${uid}`;
  const res = http.get(url, {
    headers: authHeaders(),
    tags: { query_type: 'get_program', name: '/v1/programs/{id}' },
  });
  recordStatusMetrics(res);
  check(res, {
    'get_program: status 200 or 429': (r) => r.status === 200 || r.status === 429,
    'get_program: unified_id echoed when 200': (r) =>
      r.status !== 200 || r.json('unified_id') === uid,
  });
}

// ---------------------------------------------------------------------------
// Default VU loop
// ---------------------------------------------------------------------------

export default function () {
  const r = Math.random();
  if (r < 0.70)      searchFTS();
  else if (r < 0.90) searchFilter();
  else               getProgram();

  // Per-VU think time. At 50 VU × avg 500ms = ~100 rps target, which sits
  // below the anon 50/month /32 limit only when runners come from many
  // disjoint IPs (single-IP anon runs will saturate in <1 minute; use
  // `ANON_RATE_LIMIT_PER_MONTH=50000000` on staging per README). Well
  // above the 37 rps baseline uvicorn ceiling documented in
  // research/perf_baseline.md.
  const think = THINK_MIN_MS + Math.random() * (THINK_MAX_MS - THINK_MIN_MS);
  sleep(think / 1000);
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data),
    'loadtest/summary_programs_search.json': JSON.stringify(data, null, 2),
  };
}

// Minimal stdout summary — k6 usually injects its own but we also want
// a deterministic stdout for grep in CI logs.
function textSummary(data) {
  const m = data.metrics;
  const dur = m.http_req_duration.values;
  const checks = m.checks ? m.checks.values.rate : 1.0;
  const failed = m.http_req_failed ? m.http_req_failed.values.rate : 0.0;
  return [
    '=== jpintel-mcp /v1/programs/search load test ===',
    `  iterations: ${m.iterations.values.count}`,
    `  http reqs : ${m.http_reqs.values.count}`,
    `  http_req_duration p50=${dur['p(50)'].toFixed(1)}ms p95=${dur['p(95)'].toFixed(1)}ms p99=${dur['p(99)'].toFixed(1)}ms`,
    `  checks rate: ${(checks * 100).toFixed(2)}%`,
    `  http_req_failed rate: ${(failed * 100).toFixed(3)}%`,
    `  errors_429 rate: ${(m.errors_429 ? m.errors_429.values.rate * 100 : 0).toFixed(3)}%`,
    `  errors_5xx rate: ${(m.errors_5xx ? m.errors_5xx.values.rate * 100 : 0).toFixed(3)}%`,
    '',
  ].join('\n');
}
