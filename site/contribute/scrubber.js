// Contribution form client-side scrubber.
// Vanilla JS, no framework, no build step. Loaded by site/contribute/index.html.
// Mirrors server-side contribution gates so genuine users don't reach
// the network round-trip with reject-shape data.
// Defenses are duplicated server-side (regex, banlist, program_id check).

(function () {
  "use strict";

  // -- aggregator banlist (kept in sync with api/contribute.py _AGGREGATOR_BANLIST)
  var AGGREGATOR_BANLIST = [
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "stayway.jp",
    "subsidies-japan",
    "jgrant-aggregator",
    "nikkei.com",
    "prtimes.jp",
    "wikipedia.org"
  ];

  // -- PII patterns (mirror server _PII_*_RE)
  var PII = {
    mynumber: /(?:^|[^\d])(\d{12})(?=[^\d]|$)/g,
    phone: /(?:\+?81[-\s]\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}|0\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}|0[789]0[-\s.]?\d{4}[-\s.]?\d{4})/g,
    email: /[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}/g,
    postal: /\d{3}-\d{4}/g,
    banchi: /\d+丁目\d+番/g
  };

  // -- forbidden phrases (static fallback if CDN fails).
  // CDN load is best-effort; baseline list always works offline.
  var FORBIDDEN_PHRASES = [
    "採択保証", "確実に採択", "絶対通る", "認可", "100% 採択", "完全合法"
  ];

  // -- 業法 boundary by cohort
  var BOUNDARY = {
    "税理士":              "税理士法 §52: 観察された事実のみ — 税務判断 / 助言は税理士のみ",
    "公認会計士":          "公認会計士法 §47条の2: 監査・証明業務は公認会計士のみ",
    "司法書士":            "司法書士法 §3: 登記・供託 / 裁判所提出書類は司法書士のみ",
    "補助金_consultant":   "補助金等適正化法 §29: 不正受給 / 虚偽申請に対する罰則",
    "anonymous":           "観察された事実のみ — 判断 / 助言は所轄士業 / 専門家"
  };

  // ---------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------
  function $(id) { return document.getElementById(id); }

  function strip(text, re) {
    return text.replace(re, "");
  }

  function detectPII(text) {
    var hits = [];
    if (PII.mynumber.test(text)) { hits.push("マイナンバー (12 桁)"); }
    PII.mynumber.lastIndex = 0;
    if (PII.phone.test(text))    { hits.push("電話番号"); }
    PII.phone.lastIndex = 0;
    if (PII.email.test(text))    { hits.push("メールアドレス"); }
    PII.email.lastIndex = 0;
    if (PII.postal.test(text))   { hits.push("郵便番号"); }
    PII.postal.lastIndex = 0;
    if (PII.banchi.test(text))   { hits.push("丁目番地"); }
    PII.banchi.lastIndex = 0;
    return hits;
  }

  function scrubText(text) {
    var out = text;
    out = strip(out, PII.mynumber);
    out = strip(out, PII.phone);
    out = strip(out, PII.email);
    out = strip(out, PII.postal);
    out = strip(out, PII.banchi);
    return out;
  }

  function detectForbidden(text) {
    var hits = [];
    for (var i = 0; i < FORBIDDEN_PHRASES.length; i++) {
      if (text.indexOf(FORBIDDEN_PHRASES[i]) !== -1) {
        hits.push(FORBIDDEN_PHRASES[i]);
      }
    }
    return hits;
  }

  function isBannedAggregator(url) {
    var lower = (url || "").toLowerCase();
    for (var i = 0; i < AGGREGATOR_BANLIST.length; i++) {
      if (lower.indexOf(AGGREGATOR_BANLIST[i]) !== -1) {
        return AGGREGATOR_BANLIST[i];
      }
    }
    return null;
  }

  // SHA-256 hex via crypto.subtle (per APPI fence — raw 法人番号 never leaves client)
  function sha256Hex(text) {
    var enc = new TextEncoder();
    return crypto.subtle.digest("SHA-256", enc.encode(text)).then(function (buf) {
      var arr = Array.from(new Uint8Array(buf));
      return arr.map(function (b) {
        return b.toString(16).padStart(2, "0");
      }).join("");
    });
  }

  // ---------------------------------------------------------------------
  // Wire up
  // ---------------------------------------------------------------------
  function populateYears() {
    var sel = $("observed_year");
    var now = new Date().getFullYear();
    for (var y = now; y >= 2015; y--) {
      var opt = document.createElement("option");
      opt.value = String(y); opt.textContent = String(y);
      sel.appendChild(opt);
    }
  }

  function refreshTextValidation() {
    var ta = $("observed_eligibility_text");
    var counter = $("text-counter");
    var piiWarn = $("pii-warn");
    var phraseWarn = $("phrase-warn");

    var text = ta.value || "";
    counter.textContent = text.length + " / 2000";
    counter.classList.toggle("over", text.length < 50 || text.length > 2000);

    var hits = detectPII(text);
    if (hits.length > 0) {
      piiWarn.textContent = "PII 検出: " + hits.join(", ") + " — 自動削除されました。観察事実のみ記述してください。";
      piiWarn.classList.add("on");
      // auto-strip; preserve cursor offset
      var pos = ta.selectionStart;
      var clean = scrubText(text);
      ta.value = clean;
      try { ta.setSelectionRange(Math.min(pos, clean.length), Math.min(pos, clean.length)); } catch (e) { /* ignore */ }
    } else {
      piiWarn.classList.remove("on");
    }

    var phraseHits = detectForbidden(ta.value);
    if (phraseHits.length > 0) {
      phraseWarn.textContent = "禁止語句: " + phraseHits.join(", ") + " — 観察 vs 判断 を区別してください (block ではなく注意のみ)。";
      phraseWarn.classList.add("on");
    } else {
      phraseWarn.classList.remove("on");
    }
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments;
      var ctx = this;
      if (t) { clearTimeout(t); }
      t = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function refreshSubmitGate() {
    var ack = $("consent_acknowledged").checked;
    var text = ($("observed_eligibility_text").value || "").length;
    var program = ($("program_id").value || "").length;
    var year = $("observed_year").value;
    var outcome = $("observed_outcome").value;
    var firstUrl = (document.querySelector("input[name=source_url]").value || "").trim();
    var ok = ack && program > 0 && text >= 50 && text <= 2000 && year && outcome && firstUrl.length > 0;
    $("submit-btn").disabled = !ok;
  }

  function setupCohortBoundary() {
    var sel = $("cohort");
    sel.addEventListener("change", function () {
      var msg = BOUNDARY[sel.value] || "";
      $("boundary-text").innerHTML = msg ? "<details open><summary>業法境界</summary>" + msg + "</details>" : "";
    });
  }

  function setupUrlAdd() {
    $("url-add").addEventListener("click", function () {
      var inputs = document.querySelectorAll("input[name=source_url]");
      if (inputs.length >= 5) { return; }
      var div = $("urls");
      var inp = document.createElement("input");
      inp.type = "url"; inp.name = "source_url"; inp.placeholder = "https://*.go.jp/...";
      div.appendChild(inp);
    });
  }

  function collectUrls() {
    var inputs = document.querySelectorAll("input[name=source_url]");
    var urls = [];
    for (var i = 0; i < inputs.length; i++) {
      var v = (inputs[i].value || "").trim();
      if (v) { urls.push(v); }
    }
    return urls;
  }

  function showError(id, msg) {
    var el = $(id);
    el.textContent = msg;
    el.classList.add("on");
  }

  function clearError(id) {
    $(id).classList.remove("on");
  }

  async function onSubmit(ev) {
    ev.preventDefault();
    clearError("submit-err");
    clearError("url-err");

    // Aggregator URL reject (client-side; server re-checks)
    var urls = collectUrls();
    if (urls.length === 0) {
      showError("url-err", "一次資料 URL を 1 件以上入力してください。");
      return;
    }
    for (var i = 0; i < urls.length; i++) {
      var banned = isBannedAggregator(urls[i]);
      if (banned) {
        showError("url-err",
          "aggregator URL は使用不可: " + banned + " — 一次資料 (*.go.jp / *.lg.jp / 公庫 等) を引用してください。");
        return;
      }
    }

    // 法人番号 client-side hash
    var raw = ($("houjin_bangou").value || "").trim();
    if (!/^\d{13}$/.test(raw)) {
      showError("submit-err", "法人番号 13 桁を入力してください。");
      return;
    }
    var hash;
    try {
      hash = await sha256Hex(raw);
    } catch (e) {
      showError("submit-err", "法人番号 hash 化に失敗しました。Browser を更新してください。");
      return;
    }

    var payload = {
      cohort: $("cohort").value || null,
      program_id: $("program_id").value.trim(),
      observed_year: parseInt($("observed_year").value, 10),
      observed_eligibility_text: $("observed_eligibility_text").value,
      observed_amount_yen: ($("observed_amount_yen").value
        ? parseInt($("observed_amount_yen").value, 10) : null),
      observed_outcome: $("observed_outcome").value,
      source_urls: urls,
      houjin_bangou_hash: hash,
      tax_pro_credit_name: $("tax_pro_credit_name").value || null,
      public_credit_consent: $("public_credit_consent").checked,
      consent_acknowledged: $("consent_acknowledged").checked
    };

    var resp;
    try {
      resp = await fetch("/v1/contribute/eligibility_observation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } catch (e) {
      showError("submit-err", "送信エラー: ネットワークを確認してください。");
      return;
    }
    if (!resp.ok) {
      var detail = "送信が拒否されました (" + resp.status + ")";
      try {
        var body = await resp.json();
        if (body && body.detail) { detail += ": " + body.detail; }
      } catch (e) { /* ignore */ }
      showError("submit-err", detail);
      return;
    }
    var body = await resp.json();
    var id = body.contribution_id || "";
    window.location.href = "/contribute/thanks/?id=" + encodeURIComponent(id);
  }

  function init() {
    populateYears();
    setupCohortBoundary();
    setupUrlAdd();

    var ta = $("observed_eligibility_text");
    ta.addEventListener("input", debounce(function () {
      refreshTextValidation();
      refreshSubmitGate();
    }, 250));

    [
      "consent_acknowledged",
      "program_id",
      "observed_year",
      "observed_outcome"
    ].forEach(function (id) {
      $(id).addEventListener("change", refreshSubmitGate);
      $(id).addEventListener("input", refreshSubmitGate);
    });

    $("contrib-form").addEventListener("submit", onSubmit);
    refreshSubmitGate();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // expose for tests / DevTools poking
  window.__jpciteContribute = {
    detectPII: detectPII,
    scrubText: scrubText,
    detectForbidden: detectForbidden,
    isBannedAggregator: isBannedAggregator,
    sha256Hex: sha256Hex
  };
})();
