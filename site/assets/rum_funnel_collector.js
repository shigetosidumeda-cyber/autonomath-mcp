// rum_funnel_collector.js — Wave 49 G1 organic funnel beacon.
//
// Sibling of `rum.js` (Wave 16 E1, Core Web Vitals). This collector
// targets the 5-step organic funnel (Wave 49 tick#3 calc wire):
//
//   landing       → user lands on /index.html
//   free          → user reads /onboarding.html (free 3 req/day intro)
//   signup        → user reaches /pricing.html and clicks the topup CTA
//   topup         → completed by Stripe webhook on the server side; this
//                   file only emits the *visit* and *click* upstream events.
//   calc_engaged  → user opens /tools/cost_saving_calculator and interacts
//                   (cost-saving v2 reproducibility surface, organic-only
//                    monetization moat — Wave 49 tick#3 G1 measurement).
//
// Why a separate beacon from rum.js?
//   - rum.js measures Core Web Vitals (performance / page health).
//   - rum_funnel_collector.js measures *conversion* (organic funnel).
//   - Different aggregation cadences and retention windows.
//   - Different POST endpoint (`/api/rum_beacon`) → keeps the existing
//     `/v1/rum/beacon` aggregator (rum_aggregator.py) untouched.
//
// CSP-safe (no inline handlers, no eval). 100% sampling — Wave 49 G1
// target is only 10 uniq sessions/day, so we cannot afford to sample.
//
// Page wiring: `<script src="/assets/rum_funnel_collector.js" defer></script>`
// in the <head> of index.html / onboarding.html / pricing.html.

(function () {
  "use strict";

  // ---- Bot UA filter -----------------------------------------------------
  // Mirrors `rum.js` and `functions/api/rum_beacon.ts` — bot beacons
  // would inflate session counts and skew Wave 49 G1 acceptance.
  var BOT_RE = /(bot|spider|crawler|gptbot|claudebot|perplexity|amazonbot|googlebot|bingbot|chatgpt|oai-searchbot|bytespider|ahrefs|semrush|diffbot|cohere-ai|youbot|mistralai|applebot|facebookexternalhit|twitterbot|yandex|baiduspider)/i;
  if (BOT_RE.test(navigator.userAgent || "")) return;

  var BEACON_PATH = "/api/rum_beacon";
  var SESSION_KEY = "jpcite_funnel_sid";
  var STORAGE = (function () {
    try {
      var s = window.sessionStorage;
      var probe = "__jpcite_probe__";
      s.setItem(probe, "1");
      s.removeItem(probe);
      return s;
    } catch (_e) {
      return null;
    }
  })();

  // ---- Step inference ----------------------------------------------------
  // Map path → funnel step. Unknown paths default to "landing" so any new
  // top-of-funnel page we add later still emits something useful.
  function inferStep() {
    var p = (location.pathname || "/").toLowerCase();
    if (p === "/" || p === "/index" || p === "/index.html") return "landing";
    if (p.indexOf("/onboarding") === 0) return "free";
    if (p.indexOf("/pricing") === 0) return "signup";
    if (p.indexOf("/topup") === 0 || p.indexOf("/checkout") === 0) return "topup";
    // Wave 49 tick#3: calculator engagement (cost-saving v2 surface).
    // Anchored to the canonical tool path so future locales (/en/tools/…)
    // can be added without disturbing the other 4 steps.
    if (p.indexOf("/tools/cost_saving_calculator") === 0) return "calc_engaged";
    return "landing";
  }

  // ---- Session ID (sticky across pageviews within one tab) ---------------
  function sessionId() {
    if (STORAGE) {
      var prior = STORAGE.getItem(SESSION_KEY);
      if (prior) return prior;
    }
    var fresh = newUuid();
    if (STORAGE) {
      try { STORAGE.setItem(SESSION_KEY, fresh); } catch (_e) { /* swallow */ }
    }
    return fresh;
  }
  function newUuid() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      try { return crypto.randomUUID(); } catch (_e) { /* fall through */ }
    }
    // RFC4122-style fallback (low-entropy but adequate for uniq counting)
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  // ---- Beacon dispatch ---------------------------------------------------
  function emit(event) {
    var payload = {
      session_id: sessionId(),
      page: location.pathname,
      step: inferStep(),
      event: event,
      ts: Date.now()
    };
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: "application/json" });
        if (navigator.sendBeacon(BEACON_PATH, blob)) return;
      }
    } catch (_e) { /* fall through */ }
    try {
      fetch(BEACON_PATH, {
        method: "POST",
        body: body,
        keepalive: true,
        headers: { "Content-Type": "application/json" }
      }).catch(function () {});
    } catch (_e) { /* RUM must never throw on the page */ }
  }

  // ---- Auto-fire: view --------------------------------------------------
  // Emit `view` as soon as DOM is parseable. Defer-loaded script ensures
  // DOMContentLoaded has fired (or is imminent); guard for race.
  function fireView() { emit("view"); }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", fireView, { once: true });
  } else {
    fireView();
  }

  // ---- Auto-fire: cta_click --------------------------------------------
  // Any element marked with `data-funnel-cta` (e.g. a "Start free" or
  // "Topup ¥1,000" button) emits a cta_click beacon when clicked. We use
  // bubble-phase delegation so dynamically-injected CTAs are caught.
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    while (t && t !== document.body) {
      if (t.nodeType === 1 && t.getAttribute && t.getAttribute("data-funnel-cta") !== null) {
        emit("cta_click");
        return;
      }
      t = t.parentNode;
    }
  }, true);

  // ---- Auto-fire: step_complete ----------------------------------------
  // Pages can fire a custom DOM event `jpcite:funnel:complete` when the
  // user has finished the page's intended action. The collector listens
  // and emits a step_complete beacon. This decouples completion semantics
  // from the collector so each page can define "complete" on its own
  // terms (e.g. /onboarding = scrolled past "Free 3 req/day" section,
  // /pricing = OAuth flow returned).
  document.addEventListener("jpcite:funnel:complete", function () {
    emit("step_complete");
  });
})();
