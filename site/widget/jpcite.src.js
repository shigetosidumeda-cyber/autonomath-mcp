/*!
 * jpcite Embed Widget SDK
 * 補助金検索 widget — 税理士事務所・商工会議所・中小企業支援サイト向け
 *
 * Usage (auto-init):
 *   <script src="https://jpcite.com/widget/jpcite.js"></script>
 *   <div data-jpcite-widget
 *        data-key="wgt_live_..."
 *        data-filters="industry,prefecture,target"
 *        data-theme="light"></div>
 *
 * Usage (programmatic):
 *   const w = new Jpcite.Widget({
 *     container: '#my-div',
 *     key: 'wgt_live_...',
 *     filters: ['industry', 'prefecture', 'target'],
 *     theme: 'light',    // 'light' | 'dark'
 *     language: 'ja',    // 'ja' | 'en'
 *     limit: 5,
 *     onResult: function (program) { ... }
 *   });
 *
 * Operated by Bookyou Inc. AGPL-compatible, no build step,
 * no external deps, vanilla JS. UMD wrap — works as <script> or CommonJS.
 * See site/widget/docs.html for the full integration guide.
 *
 * Brand history note (kept for back-compat): this SDK was previously
 * distributed as autonomath.js. The CSS class prefix and data attribute
 * accept both `jpcite-widget*` (new, primary) and `autonomath-widget*`
 * (legacy alias) so host pages targeting either selector keep working
 * through a 6-month deprecation window.
 *
 * Copyright 2026 Bookyou株式会社
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    var api = factory();
    root.Jpcite = root.Jpcite || {};
    root.Autonomath = root.Autonomath || {};
    for (var k in api) {
      if (Object.prototype.hasOwnProperty.call(api, k)) {
        root.Jpcite[k] = api[k];
        root.Autonomath[k] = api[k]; // backwards-compatible alias
      }
    }
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // -------------------------------------------------------------------------
  // Config
  // -------------------------------------------------------------------------

  var SCRIPT_VERSION = "1.1.0";
  var DEFAULT_API_BASE = "https://api.jpcite.com";
  var PROGRAM_PAGE_BASE = "https://jpcite.com/programs/";

  // i18n — tiny on purpose; widget is not a full CMS.
  var I18N = {
    ja: {
      search: "検索",
      searching: "検索中...",
      no_results: "該当する制度が見つかりませんでした。",
      error_origin: "この診断入口はこのサイトで有効化されていません。",
      error_quota: "この widget key の請求状態を確認できません。サイト運営者へお問い合わせください。",
      error_billing: "利用量を記録できませんでした。少し時間を置いて再度お試しください。",
      error_rate: "短時間にリクエストが多すぎます。しばらくお待ちください。",
      error_network: "通信エラーが発生しました。",
      error_invalid_key: "埋め込みキーを確認してください。",
      filter_prefecture: "都道府県",
      filter_industry: "業種",
      filter_target: "対象",
      filter_all: "すべて",
      freetext: "キーワード",
      freetext_placeholder: "例: IT導入補助金 / 省エネ",
      amount_label: "上限金額",
      deadline_label: "締切",
      fetched_label: "出典取得",
      questions_label: "相談前の確認",
      view_detail: "詳細を見る",
      source_label: "一次資料",
      powered_by: "Powered by jpcite",
      results_summary: "件ヒット"
    },
    en: {
      search: "Search",
      searching: "Searching...",
      no_results: "No matching programs found.",
      error_origin: "This origin is not allowed for this key.",
      error_quota: "This widget key's billing state could not be confirmed. Contact the site owner.",
      error_billing: "Usage could not be recorded. Please try again shortly.",
      error_rate: "Too many requests. Please wait a moment.",
      error_network: "Network error.",
      error_invalid_key: "Invalid widget key.",
      filter_prefecture: "Prefecture",
      filter_industry: "Industry",
      filter_target: "Target",
      filter_all: "All",
      freetext: "Keyword",
      freetext_placeholder: "e.g. IT subsidy",
      amount_label: "Max amount",
      deadline_label: "Deadline",
      fetched_label: "Source fetched",
      questions_label: "Before consultation",
      view_detail: "View details",
      source_label: "Source",
      powered_by: "Powered by jpcite",
      results_summary: " results"
    }
  };

  // -------------------------------------------------------------------------
  // CSS — injected once per page so host sites don't need to import the
  // stylesheet separately. Keep minimal; host CSS can override via the
  // prefixed `.jpcite-widget-*` class names (primary) or the legacy
  // `.autonomath-widget-*` aliases. Both selectors live in the same rule
  // so existing host overrides keep applying during the deprecation window.
  // -------------------------------------------------------------------------

  // Primary (new) and legacy (kept for 6-month deprecation) <style> ids.
  // Injecting under both ids lets older auto-init runs / hosts that probe
  // by id continue to detect "the widget stylesheet is already on the page".
  var STYLE_ID_NEW = "jpcite-widget-style";
  var STYLE_ID = "autonomath-widget-style"; // legacy alias kept on purpose
  var CSS = [
    ".jpcite-widget,.autonomath-widget{",
    "font-family:'Noto Sans JP',system-ui,-apple-system,sans-serif;",
    "font-size:14px;color:#111827;background:#ffffff;",
    "border:1px solid #e5e7eb;border-radius:10px;padding:16px 18px;",
    "max-width:720px;box-sizing:border-box;line-height:1.5}",
    ".jpcite-widget *,.autonomath-widget *{box-sizing:border-box}",
    ".jpcite-widget--dark,.autonomath-widget--dark{background:#0f172a;color:#f8fafc;border-color:#1e293b}",
    ".jpcite-widget__form,.autonomath-widget__form{display:grid;gap:10px;margin-bottom:14px}",
    ".jpcite-widget__row,.autonomath-widget__row{display:flex;gap:8px;flex-wrap:wrap}",
    ".jpcite-widget__field,.autonomath-widget__field{flex:1 1 160px;display:flex;flex-direction:column;min-width:120px}",
    ".jpcite-widget__label,.autonomath-widget__label{font-size:12px;font-weight:600;color:#374151;margin:0 0 4px}",
    ".jpcite-widget--dark .jpcite-widget__label,.autonomath-widget--dark .autonomath-widget__label{color:#cbd5e1}",
    ".jpcite-widget__input,.jpcite-widget__select,.autonomath-widget__input,.autonomath-widget__select{",
    "width:100%;border:1px solid #d1d5db;border-radius:6px;padding:8px 10px;",
    "background:#ffffff;color:#111827;font:inherit}",
    ".jpcite-widget--dark .jpcite-widget__input,.jpcite-widget--dark .jpcite-widget__select,",
    ".autonomath-widget--dark .autonomath-widget__input,.autonomath-widget--dark .autonomath-widget__select{",
    "background:#1e293b;color:#f8fafc;border-color:#334155}",
    ".jpcite-widget__input:focus,.jpcite-widget__select:focus,",
    ".autonomath-widget__input:focus,.autonomath-widget__select:focus{",
    "outline:none;border-color:#4f46e5;box-shadow:0 0 0 3px rgba(79,70,229,.18)}",
    ".jpcite-widget__submit,.autonomath-widget__submit{",
    "border:0;border-radius:6px;padding:9px 18px;background:#4f46e5;color:#ffffff;",
    "font:600 14px/1 'Noto Sans JP',system-ui,sans-serif;cursor:pointer}",
    ".jpcite-widget__submit:hover,.autonomath-widget__submit:hover{background:#4338ca}",
    ".jpcite-widget__submit[disabled],.autonomath-widget__submit[disabled]{opacity:.55;cursor:not-allowed}",
    ".jpcite-widget__status,.autonomath-widget__status{font-size:12px;color:#6b7280;margin:6px 0 8px;min-height:16px}",
    ".jpcite-widget--dark .jpcite-widget__status,.autonomath-widget--dark .autonomath-widget__status{color:#94a3b8}",
    ".jpcite-widget__error,.autonomath-widget__error{color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;",
    "padding:8px 12px;border-radius:6px;font-size:13px;margin:8px 0}",
    ".jpcite-widget--dark .jpcite-widget__error,.autonomath-widget--dark .autonomath-widget__error{color:#fecaca;background:#450a0a;border-color:#7f1d1d}",
    ".jpcite-widget__results,.autonomath-widget__results{list-style:none;margin:0;padding:0;display:grid;gap:10px}",
    ".jpcite-widget__item,.autonomath-widget__item{border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;background:#ffffff}",
    ".jpcite-widget--dark .jpcite-widget__item,.autonomath-widget--dark .autonomath-widget__item{background:#1e293b;border-color:#334155}",
    ".jpcite-widget__name,.autonomath-widget__name{margin:0 0 4px;font-size:15px;font-weight:700;color:#111827}",
    ".jpcite-widget--dark .jpcite-widget__name,.autonomath-widget--dark .autonomath-widget__name{color:#f8fafc}",
    ".jpcite-widget__meta,.autonomath-widget__meta{margin:0 0 6px;font-size:12px;color:#6b7280;display:flex;gap:10px;flex-wrap:wrap}",
    ".jpcite-widget--dark .jpcite-widget__meta,.autonomath-widget--dark .autonomath-widget__meta{color:#94a3b8}",
    ".jpcite-widget__tag,.autonomath-widget__tag{display:inline-block;padding:1px 8px;background:#eef2ff;color:#3730a3;",
    "border-radius:999px;font-size:11px}",
    ".jpcite-widget--dark .jpcite-widget__tag,.autonomath-widget--dark .autonomath-widget__tag{background:#312e81;color:#c7d2fe}",
    ".jpcite-widget__amount,.autonomath-widget__amount{font-weight:600;color:#111827}",
    ".jpcite-widget--dark .jpcite-widget__amount,.autonomath-widget--dark .autonomath-widget__amount{color:#f8fafc}",
    ".jpcite-widget__actions,.autonomath-widget__actions{margin-top:6px;display:flex;gap:12px;flex-wrap:wrap;font-size:13px}",
    ".jpcite-widget__questions,.autonomath-widget__questions{margin:6px 0 0;padding-left:18px;font-size:12px;color:#4b5563}",
    ".jpcite-widget--dark .jpcite-widget__questions,.autonomath-widget--dark .autonomath-widget__questions{color:#cbd5e1}",
    ".jpcite-widget__link,.autonomath-widget__link{color:#4f46e5;text-decoration:none;font-weight:500}",
    ".jpcite-widget__link:hover,.autonomath-widget__link:hover{text-decoration:underline}",
    ".jpcite-widget--dark .jpcite-widget__link,.autonomath-widget--dark .autonomath-widget__link{color:#a5b4fc}",
    ".jpcite-widget__footer,.autonomath-widget__footer{margin-top:10px;font-size:11px;color:#9ca3af;text-align:right}",
    ".jpcite-widget__footer a,.autonomath-widget__footer a{color:inherit;text-decoration:none}",
    ".jpcite-widget__footer a:hover,.autonomath-widget__footer a:hover{text-decoration:underline}",
    ".jpcite-widget--dark .jpcite-widget__footer,.autonomath-widget--dark .autonomath-widget__footer{color:#64748b}"
  ].join("");

  function injectCss() {
    if (typeof document === "undefined") return;
    // Skip if either id already present — older autonomath.js may have
    // injected the legacy id, in which case our jpcite-* selectors are
    // already there too (they share the same rules).
    if (document.getElementById(STYLE_ID_NEW)) return;
    if (document.getElementById(STYLE_ID)) return;
    var headEl = document.head || document.getElementsByTagName("head")[0];
    // Primary <style id="jpcite-widget-style">
    var sNew = document.createElement("style");
    sNew.id = STYLE_ID_NEW;
    sNew.type = "text/css";
    sNew.appendChild(document.createTextNode(CSS));
    headEl.appendChild(sNew);
    // Legacy <style id="autonomath-widget-style"> — empty placeholder so
    // existing host probes for the legacy id keep returning a node, but
    // we do NOT duplicate CSS payload (the new sheet already covers both
    // selector chains via comma-joined rules above).
    if (!document.getElementById(STYLE_ID)) {
      var sLegacy = document.createElement("style");
      sLegacy.id = STYLE_ID;
      sLegacy.type = "text/css";
      sLegacy.setAttribute("data-jpcite-legacy-alias", "true");
      // Empty body — selectors live in the primary sheet.
      headEl.appendChild(sLegacy);
    }
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
        if (k === "className") el.className = attrs[k];
        else if (k === "textContent") el.textContent = attrs[k];
        else if (k === "innerHTML") throw new Error("innerHTML forbidden");
        else if (k.indexOf("on") === 0 && typeof attrs[k] === "function") {
          el.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        } else el.setAttribute(k, attrs[k]);
      }
    }
    if (children) {
      for (var i = 0; i < children.length; i++) {
        var c = children[i];
        if (c == null) continue;
        if (typeof c === "string") el.appendChild(document.createTextNode(c));
        else el.appendChild(c);
      }
    }
    return el;
  }

  function resolveContainer(spec) {
    if (!spec) return null;
    if (typeof spec === "string") return document.querySelector(spec);
    if (spec.nodeType === 1) return spec;
    return null;
  }

  function formatYen(max) {
    if (max == null || max === "") return "";
    var n = Number(max);
    if (!isFinite(n) || n <= 0) return "";
    if (n >= 10000) return "約 " + Math.round(n / 10000 * 10) / 10 + " 億円";
    if (n >= 1) return n.toLocaleString("ja-JP") + " 万円";
    return "";
  }

  function t(lang, key) {
    var dict = I18N[lang] || I18N.ja;
    return dict[key] || key;
  }

  // -------------------------------------------------------------------------
  // Widget class
  // -------------------------------------------------------------------------

  function Widget(opts) {
    if (!(this instanceof Widget)) return new Widget(opts);
    opts = opts || {};
    this.key = opts.key || "";
    this.container = resolveContainer(opts.container);
    this.filters = (opts.filters && opts.filters.length)
      ? opts.filters
      : ["industry", "prefecture", "target"];
    this.theme = opts.theme === "dark" ? "dark" : "light";
    this.language = opts.language === "en" ? "en" : "ja";
    this.limit = Math.max(1, Math.min(20, parseInt(opts.limit, 10) || 5));
    this.apiBase = (opts.apiBase || DEFAULT_API_BASE).replace(/\/+$/, "");
    this.onResult = typeof opts.onResult === "function" ? opts.onResult : null;
    this._enumValues = null;
    this._branding = true; // assume branding on until enum_values says otherwise

    if (!this.key) { this._fatal("missing data-key"); return; }
    if (!this.container) { this._fatal("container not found"); return; }
    if (!/^wgt_live_[0-9a-f]{32}$/.test(this.key)) {
      this._fatal(t(this.language, "error_invalid_key"));
      return;
    }

    injectCss();
    this._render();
    this._fetchEnumValues();
  }

  Widget.prototype._fatal = function (msg) {
    if (!this.container) {
      if (typeof console !== "undefined") console.error("[jpcite-widget]", msg);
      return;
    }
    this.container.textContent = "";
    var box = h("div", { className: "jpcite-widget autonomath-widget" }, [
      h("div", { className: "jpcite-widget__error autonomath-widget__error" }, [msg])
    ]);
    this.container.appendChild(box);
  };

  Widget.prototype._render = function () {
    this.container.textContent = "";
    var darkSuffix = this.theme === "dark"
      ? " jpcite-widget--dark autonomath-widget--dark" : "";
    this.rootEl = h("div", {
      className: "jpcite-widget autonomath-widget" + darkSuffix,
      // Set BOTH attributes so auto-init scans + host CSS / DevTools
      // probes for either name keep matching during the deprecation window.
      "data-jpcite-widget-mounted": "true",
      "data-autonomath-widget-mounted": "true"
    });
    var form = h("form", { className: "jpcite-widget__form autonomath-widget__form", onsubmit: this._onSubmit.bind(this) });
    var row = h("div", { className: "jpcite-widget__row autonomath-widget__row" });

    // Free-text input always rendered
    row.appendChild(this._renderField(
      "q",
      t(this.language, "freetext"),
      h("input", {
        className: "jpcite-widget__input autonomath-widget__input",
        type: "text",
        name: "q",
        placeholder: t(this.language, "freetext_placeholder"),
        "aria-label": t(this.language, "freetext")
      })
    ));

    // Filter selects, placeholder until enum_values loads
    for (var i = 0; i < this.filters.length; i++) {
      var key = this.filters[i];
      var labelKey = "filter_" + key;
      var label = t(this.language, labelKey);
      var sel = h("select", { className: "jpcite-widget__select autonomath-widget__select", name: key, "aria-label": label }, [
        h("option", { value: "" }, [t(this.language, "filter_all")])
      ]);
      row.appendChild(this._renderField(key, label, sel));
    }

    form.appendChild(row);
    form.appendChild(h("div", { className: "jpcite-widget__row autonomath-widget__row" }, [
      h("button", { type: "submit", className: "jpcite-widget__submit autonomath-widget__submit" },
        [t(this.language, "search")])
    ]));
    this.rootEl.appendChild(form);
    this.statusEl = h("div", { className: "jpcite-widget__status autonomath-widget__status", role: "status", "aria-live": "polite" });
    this.rootEl.appendChild(this.statusEl);
    this.errorEl = h("div", { className: "jpcite-widget__error autonomath-widget__error", style: "display:none", role: "alert" });
    this.rootEl.appendChild(this.errorEl);
    this.resultsEl = h("ul", { className: "jpcite-widget__results autonomath-widget__results" });
    this.rootEl.appendChild(this.resultsEl);
    this.footerEl = h("div", { className: "jpcite-widget__footer autonomath-widget__footer" });
    this.rootEl.appendChild(this.footerEl);
    this._renderFooter();
    this.formEl = form;
    this.container.appendChild(this.rootEl);
  };

  Widget.prototype._renderField = function (name, label, input) {
    return h("div", { className: "jpcite-widget__field autonomath-widget__field" }, [
      h("label", { className: "jpcite-widget__label autonomath-widget__label", "for": "jpcite-f-" + name }, [label]),
      (function (inp) { inp.id = "jpcite-f-" + name; return inp; })(input)
    ]);
  };

  Widget.prototype._renderFooter = function () {
    this.footerEl.textContent = "";
    if (this._branding) {
      var link = h("a", {
        href: "https://jpcite.com/widget.html",
        target: "_blank",
        rel: "noopener"
      }, [t(this.language, "powered_by")]);
      this.footerEl.appendChild(link);
    }
  };

  Widget.prototype._fetchEnumValues = function () {
    var self = this;
    var url = this.apiBase + "/v1/widget/enum_values?key=" + encodeURIComponent(this.key);
    return fetch(url, { method: "GET", mode: "cors", credentials: "omit" })
      .then(function (r) {
        if (!r.ok) {
          return r.json().catch(function () { return null; }).then(function (body) {
            throw { status: r.status, body: body };
          });
        }
        return r.json();
      })
      .then(function (data) {
        self._enumValues = data || {};
        if (data && data.widget) {
          self._branding = data.widget.branding !== false;
          self._renderFooter();
        }
        self._populateSelects(data || {});
      })
      .catch(function (err) { self._handleFetchError(err); });
  };

  Widget.prototype._populateSelects = function (data) {
    var mapping = {
      prefecture: data.prefectures || [],
      industry: data.industries || [],
      target: data.target_types || []
    };
    for (var i = 0; i < this.filters.length; i++) {
      var key = this.filters[i];
      var selector = 'select[name="' + key + '"]';
      var sel = this.formEl.querySelector(selector);
      if (!sel) continue;
      var items = mapping[key] || [];
      for (var j = 0; j < items.length; j++) {
        var item = items[j];
        var code = item.code != null ? String(item.code) : "";
        var label = item.label_ja || item.label_en || code;
        sel.appendChild(h("option", { value: code }, [label]));
      }
    }
  };

  Widget.prototype._onSubmit = function (ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    this._runSearch();
    return false;
  };

  Widget.prototype._collectParams = function () {
    var out = { key: this.key, limit: this.limit };
    var q = this.formEl.querySelector('input[name="q"]');
    if (q && q.value.trim()) out.q = q.value.trim();
    var map = { prefecture: "prefecture", industry: "industry", target: "target" };
    for (var i = 0; i < this.filters.length; i++) {
      var k = this.filters[i];
      var sel = this.formEl.querySelector('select[name="' + k + '"]');
      if (sel && sel.value) out[map[k]] = sel.value;
    }
    return out;
  };

  Widget.prototype._runSearch = function () {
    var self = this;
    this.errorEl.style.display = "none";
    this.errorEl.textContent = "";
    this.statusEl.textContent = t(this.language, "searching");
    var submit = this.formEl.querySelector("button[type=submit]");
    if (submit) submit.disabled = true;

    var params = this._collectParams();
    var qs = [];
    for (var k in params) {
      if (!Object.prototype.hasOwnProperty.call(params, k)) continue;
      var v = params[k];
      if (v == null || v === "") continue;
      qs.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
    }
    var url = this.apiBase + "/v1/widget/search?" + qs.join("&");
    return fetch(url, { method: "GET", mode: "cors", credentials: "omit" })
      .then(function (r) {
        if (!r.ok) {
          return r.json().catch(function () { return null; }).then(function (body) {
            throw { status: r.status, body: body };
          });
        }
        return r.json();
      })
      .then(function (data) {
        self._renderResults(data);
        self.statusEl.textContent = (data && typeof data.total === "number")
          ? (data.total + t(self.language, "results_summary"))
          : "";
      })
      .catch(function (err) { self._handleFetchError(err); })
      .then(function () { if (submit) submit.disabled = false; });
  };

  Widget.prototype._renderResults = function (data) {
    this.resultsEl.textContent = "";
    var results = (data && data.results) ? data.results : [];
    if (!results.length) {
      this.resultsEl.appendChild(h("li", { className: "jpcite-widget__item autonomath-widget__item" }, [
        t(this.language, "no_results")
      ]));
      return;
    }
    // Update branding from widget レスポンス (server may flip it)
    if (data && data.widget && typeof data.widget.branding === "boolean") {
      this._branding = data.widget.branding;
      this._renderFooter();
    }
    for (var i = 0; i < results.length; i++) {
      this.resultsEl.appendChild(this._renderItem(results[i]));
      if (this.onResult) {
        try { this.onResult(results[i]); } catch (e) { /* user callback */ }
      }
    }
  };

  Widget.prototype._renderItem = function (program) {
    var lang = this.language;
    var tagCls = "jpcite-widget__tag autonomath-widget__tag";
    var tags = [];
    if (program.prefecture) tags.push(h("span", { className: tagCls }, [program.prefecture]));
    if (program.authority_level) tags.push(h("span", { className: tagCls }, [program.authority_level]));
    if (program.program_kind) tags.push(h("span", { className: tagCls }, [program.program_kind]));

    var meta = h("div", { className: "jpcite-widget__meta autonomath-widget__meta" });
    if (tags.length) { for (var i = 0; i < tags.length; i++) meta.appendChild(tags[i]); }

    var amount = formatYen(program.amount_max_man_yen);
    if (amount) {
      meta.appendChild(h("span", { className: "jpcite-widget__amount autonomath-widget__amount" }, [
        t(lang, "amount_label") + ": " + amount
      ]));
    }
    if (program.next_deadline) {
      meta.appendChild(h("span", {}, [t(lang, "deadline_label") + ": " + program.next_deadline]));
    }
    if (program.source_fetched_at) {
      meta.appendChild(h("span", {}, [
        t(lang, "fetched_label") + ": " + String(program.source_fetched_at).slice(0, 10)
      ]));
    }

    var linkCls = "jpcite-widget__link autonomath-widget__link";
    var actions = h("div", { className: "jpcite-widget__actions autonomath-widget__actions" });
    var detailUrl = program.static_url || program.public_url ||
      (PROGRAM_PAGE_BASE + encodeURIComponent(program.unified_id || ""));
    actions.appendChild(h("a", {
      className: linkCls,
      href: detailUrl,
      target: "_blank",
      rel: "noopener"
    }, [t(lang, "view_detail")]));
    var sourceUrl = program.official_url || program.source_url;
    if (sourceUrl) {
      actions.appendChild(h("a", {
        className: linkCls,
        href: sourceUrl,
        target: "_blank",
        rel: "noopener"
      }, [t(lang, "source_label")]));
    }

    var children = [
      h("p", { className: "jpcite-widget__name autonomath-widget__name" }, [program.primary_name || program.unified_id || ""]),
      meta,
      actions
    ];
    var qs = program.prescreen_questions || program.next_questions || [];
    if (qs && qs.length) {
      children.splice(2, 0, h("ul", { className: "jpcite-widget__questions autonomath-widget__questions" },
        [h("li", {}, [t(lang, "questions_label") + ": " + String(qs[0])])]
      ));
    }
    return h("li", { className: "jpcite-widget__item autonomath-widget__item" }, children);
  };

  Widget.prototype._handleFetchError = function (err) {
    var lang = this.language;
    var msg;
    if (!err || err.status == null) {
      msg = t(lang, "error_network");
    } else if (err.status === 401) {
      msg = t(lang, "error_invalid_key");
    } else if (err.status === 403) {
      // Distinguish origin error from generic 403
      var body = err.body || {};
      var detail = body.detail || body.error || "";
      if (/origin/i.test(String(detail))) msg = t(lang, "error_origin");
      else msg = t(lang, "error_network");
    } else if (err.status === 429) {
      msg = t(lang, "error_rate");
    } else if (err.status === 402) {
      msg = t(lang, "error_quota");
    } else if (err.status === 503 && err.body && err.body.error === "billing_queue_unavailable") {
      msg = t(lang, "error_billing");
    } else {
      msg = t(lang, "error_network");
    }
    this.errorEl.textContent = msg;
    this.errorEl.style.display = "block";
    this.statusEl.textContent = "";
  };

  Widget.prototype.destroy = function () {
    if (this.container) this.container.textContent = "";
  };

  // -------------------------------------------------------------------------
  // Auto-init scanner
  // -------------------------------------------------------------------------

  function autoInit() {
    if (typeof document === "undefined") return;
    var nodes = document.querySelectorAll("[data-jpcite-widget], [data-autonomath-widget]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      // Either mounted attribute is treated as "already mounted" so we
      // don't double-init when both jpcite.js and autonomath.js are
      // loaded on the same page during the deprecation overlap.
      if (el.getAttribute("data-jpcite-widget-mounted") === "true") continue;
      if (el.getAttribute("data-autonomath-widget-mounted") === "true") continue;
      var filters = (el.getAttribute("data-filters") || "industry,prefecture,target")
        .split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      try {
        new Widget({
          container: el,
          key: el.getAttribute("data-key") || "",
          filters: filters,
          theme: el.getAttribute("data-theme") || "light",
          language: el.getAttribute("data-language") || "ja",
          limit: parseInt(el.getAttribute("data-limit"), 10) || 5,
          apiBase: el.getAttribute("data-api-base") || undefined
        });
      } catch (e) {
        if (typeof console !== "undefined") console.error("[jpcite-widget]", e);
      }
    }
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", autoInit);
    } else {
      // Already loaded — run async so host-page scripts that register
      // additional widgets after our script tag still get picked up.
      setTimeout(autoInit, 0);
    }
  }

  return {
    Widget: Widget,
    autoInit: autoInit,
    version: SCRIPT_VERSION
  };
});
