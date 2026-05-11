/*
 * webmcp_init.js — jpcite WebMCP early preview wiring (Wave 17 AX Layer 3).
 *
 * Exposes 4 browser-resident agent tools through Chrome 145+ WebMCP
 * (`navigator.modelContext.registerTool`) so a co-located agent can invoke
 * jpcite REST endpoints structurally (89% token reduction vs. screenshot
 * scraping: ~2000 token preview blob → 20-100 token JSON envelope).
 *
 * Design constraints:
 *  - NO LLM API import. Every tool delegates to api.jpcite.com REST (¥3/req
 *    metered, anonymous 3 req/day/IP). The browser is a pass-through.
 *  - NO blocking work on initial parse. Loaded with `defer`; registration
 *    happens after DOMContentLoaded so LCP / FID are unaffected.
 *  - Feature-detected polyfill: pre-145 Chrome / Firefox / Safari fall back
 *    to a window-scoped tool registry that the same agent SDK can read.
 *  - CSP-friendly: external bundle, `'self'` script-src is sufficient.
 */
(function () {
  'use strict';

  var API_BASE = 'https://api.jpcite.com';

  /* --- polyfill ----------------------------------------------------------
   * Chrome 145+ ships navigator.modelContext natively. Anything earlier,
   * and Firefox / Safari, get a window-scoped shim so the registration
   * surface is identical for callers. Agent SDKs that look for the polyfill
   * can introspect `window.__jpcite_webmcp_tools` to discover the catalogue.
   */
  var nativeAvailable = (typeof navigator !== 'undefined' &&
                        'modelContext' in navigator &&
                        navigator.modelContext &&
                        typeof navigator.modelContext.registerTool === 'function');

  if (!nativeAvailable) {
    if (typeof navigator !== 'undefined') {
      var polyfillRegistry = {};
      navigator.modelContext = navigator.modelContext || {};
      navigator.modelContext.__polyfill = true;
      navigator.modelContext.registerTool = function (descriptor) {
        if (!descriptor || typeof descriptor.name !== 'string') {
          throw new TypeError('registerTool requires { name, description, handler }');
        }
        polyfillRegistry[descriptor.name] = descriptor;
        return { name: descriptor.name, unregister: function () { delete polyfillRegistry[descriptor.name]; } };
      };
      navigator.modelContext.listTools = function () {
        return Object.keys(polyfillRegistry).map(function (k) {
          var d = polyfillRegistry[k];
          return { name: d.name, description: d.description, inputSchema: d.inputSchema };
        });
      };
      navigator.modelContext.callTool = function (name, args) {
        var d = polyfillRegistry[name];
        if (!d) { return Promise.reject(new Error('tool_not_registered: ' + name)); }
        return Promise.resolve().then(function () { return d.handler(args || {}); });
      };
      window.__jpcite_webmcp_tools = polyfillRegistry;
    }
  }

  /* --- shared fetch helper -----------------------------------------------
   * Returns the parsed JSON body with a thin envelope. Errors surface as
   * structured `{ ok:false, error, status }` so agents do not have to do
   * try/catch and timestamp parsing manually.
   */
  function callJpciteRest(path, query) {
    var url = new URL(API_BASE + path);
    if (query && typeof query === 'object') {
      Object.keys(query).forEach(function (k) {
        var v = query[k];
        if (v !== undefined && v !== null && v !== '') { url.searchParams.set(k, String(v)); }
      });
    }
    return fetch(url.toString(), {
      method: 'GET',
      headers: { 'Accept': 'application/json', 'X-Client-Surface': 'webmcp-browser' },
      credentials: 'omit',
      mode: 'cors'
    }).then(function (resp) {
      return resp.json().then(function (body) {
        return {
          ok: resp.ok,
          status: resp.status,
          body: body,
          source: 'api.jpcite.com',
          fetched_at: new Date().toISOString()
        };
      }).catch(function () {
        return { ok: false, status: resp.status, body: null, error: 'non_json_response' };
      });
    }).catch(function (err) {
      return { ok: false, status: 0, error: String(err && err.message || err) };
    });
  }

  /* --- tool catalogue ----------------------------------------------------
   * 4 tools mirror the playground top tabs so an agent visiting either
   * site/playground.html or site/index.html sees the same surface.
   */
  var TOOLS = [
    {
      name: 'search_jpcite_programs',
      description: '日本の公的制度 (補助金・融資・税制・認定) を一次資料 URL 付きで検索する。匿名 3 req/日 無料。',
      inputSchema: {
        type: 'object',
        properties: {
          q: { type: 'string', description: '日本語自由文 (例: 製造業 設備投資 東京)' },
          tier: { type: 'string', enum: ['S', 'A', 'B', 'C'], description: '網羅深度の絞り込み' },
          prefecture: { type: 'string', description: '都道府県名 (例: 東京都)' },
          limit: { type: 'integer', minimum: 1, maximum: 50, default: 10 }
        },
        required: ['q']
      },
      handler: function (args) {
        return callJpciteRest('/v1/programs/search', {
          q: args.q, tier: args.tier, prefecture: args.prefecture, limit: args.limit || 10
        });
      }
    },
    {
      name: 'lookup_houjin_360',
      description: '13 桁法人番号から 法人 360 (登記・適格事業者・処分履歴・採択履歴) を 1 call で取得する。',
      inputSchema: {
        type: 'object',
        properties: {
          houjin_bangou: { type: 'string', pattern: '^[0-9]{13}$', description: '13 桁法人番号' }
        },
        required: ['houjin_bangou']
      },
      handler: function (args) {
        var hb = String(args.houjin_bangou || '').replace(/[^0-9]/g, '');
        return callJpciteRest('/v1/houjin/' + encodeURIComponent(hb) + '/full_context', {});
      }
    },
    {
      name: 'search_invoice_registrants',
      description: '国税庁 適格請求書発行事業者 (T 番号) を法人番号・登録番号から検索する。PDL v1.0、出典明記済。',
      inputSchema: {
        type: 'object',
        properties: {
          t_number: { type: 'string', description: 'T で始まる 14 桁登録番号 (T+13 桁)' },
          houjin_bangou: { type: 'string', description: '13 桁法人番号 (T 番号と排他)' }
        }
      },
      handler: function (args) {
        var t = args.t_number ? String(args.t_number).replace(/^T?/i, 'T') : null;
        var path = t ? ('/v1/invoice_registrants/' + encodeURIComponent(t))
                     : ('/v1/invoice_registrants/lookup');
        var query = t ? {} : { houjin_bangou: args.houjin_bangou };
        return callJpciteRest(path, query);
      }
    },
    {
      name: 'search_enforcement_cases',
      description: '行政処分 (業種別) を法人名・処分種別・年で横断検索する。1,185 件、一次資料 URL 付き。',
      inputSchema: {
        type: 'object',
        properties: {
          q: { type: 'string', description: '法人名 / キーワード' },
          authority: { type: 'string', description: '処分庁 (例: 国土交通省関東地方整備局)' },
          year: { type: 'integer', minimum: 2010, maximum: 2030 }
        }
      },
      handler: function (args) {
        return callJpciteRest('/v1/enforcement/search', {
          q: args.q, authority: args.authority, year: args.year
        });
      }
    }
  ];

  /* --- register on ready -------------------------------------------------
   * DOMContentLoaded gate prevents the registerTool call from blocking the
   * initial paint. The page is fully interactive before WebMCP wiring.
   */
  function registerAll() {
    if (typeof navigator === 'undefined' || !navigator.modelContext) { return; }
    TOOLS.forEach(function (descriptor) {
      try {
        navigator.modelContext.registerTool(descriptor);
      } catch (err) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[jpcite webmcp] register failed for ' + descriptor.name, err);
        }
      }
    });
    window.__jpcite_webmcp_ready = true;
    window.dispatchEvent(new CustomEvent('jpcite:webmcp-ready', {
      detail: { tool_count: TOOLS.length, native: nativeAvailable }
    }));
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', registerAll);
    } else {
      registerAll();
    }
  }
})();
