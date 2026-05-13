// rum.js — Real User Monitoring beacon (public RUM beacon).
//
// Captures Web Vitals (LCP / INP / CLS / TTFB / FCP) from real browsers and
// POSTs them to /v1/rum/beacon for daily aggregation into /status/rum.json.
// Designed to be a single self-contained file with no external dependencies
// so it can ship under a tight CSP without a `unsafe-inline` rule and without
// adding another sha256 entry per page.
//
// Notes:
//  - Uses the W3C PerformanceObserver API directly (Web Vitals npm package is
//    intentionally not used — avoids module bundler step, keeps RUM under
//    ~150 LOC, and lets us inline this script inside a static Cloudflare Pages
//    deploy with zero build pipeline coupling).
//  - LCP: largest-contentful-paint observer, take the last entry before
//    visibility change / pagehide (per Core Web Vitals spec).
//  - INP: longest event duration measured by `event` PerformanceObserver
//    entries with `interactionId` > 0, capped at 200 events to keep memory
//    bounded on long-lived sessions.
//  - CLS: layout-shift entries WHERE !hadRecentInput, summed by session
//    window (gap 1s, max 5s) per spec.
//  - TTFB: navigation entry `responseStart - startTime`.
//  - FCP: first-contentful-paint entry.
//  - Beacon is sent via `navigator.sendBeacon` (preferred, non-blocking) on
//    pagehide/visibilitychange=hidden; falls back to fetch keepalive.
//  - Bot UAs are skipped (sampled bot RUM is meaningless and pollutes p75).
//  - Sampling: 100% for anonymous (no API key) sessions, 100% for authed
//    sessions — RUM volume is low enough (<2k pageviews/day) that there is
//    no need to sample down. Re-evaluate if pageviews >50k/day.
//
// CSP: include `script-src 'self'` (no inline event handlers, no eval).
// Page wiring: `<script src="/assets/rum.js" defer></script>` in <head>.

(function () {
  "use strict";

  // ---- Bot UA filter -------------------------------------------------------
  // Skip beacon entirely for known bots — their performance is irrelevant
  // and would skew p75. Pattern list mirrors the operator analytics export
  // intentionally (kept short — CF AI Audit covers the long tail).
  var BOT_RE = /(bot|spider|crawler|gptbot|claudebot|perplexity|amazonbot|googlebot|bingbot|chatgpt|oai-searchbot|bytespider|ahrefs|semrush|diffbot|cohere-ai|youbot|mistralai|applebot|facebookexternalhit|twitterbot|yandex|baiduspider)/i;
  if (BOT_RE.test(navigator.userAgent || "")) return;

  // PerformanceObserver is universal on every browser we support (Chrome ≥60,
  // Firefox ≥58, Safari ≥12). Guard anyway so old in-app webviews don't crash.
  if (typeof PerformanceObserver !== "function") return;

  var BEACON_PATH = "/v1/rum/beacon";
  var vitals = { lcp: null, inp: null, cls: 0, ttfb: null, fcp: null };
  var observers = [];

  function safeObserve(type, cb, buffered) {
    try {
      var po = new PerformanceObserver(function (list) { cb(list); });
      var opts = { type: type, buffered: !!buffered };
      po.observe(opts);
      observers.push(po);
    } catch (e) { /* unsupported entry type — skip */ }
  }

  // ---- LCP -----------------------------------------------------------------
  safeObserve("largest-contentful-paint", function (list) {
    var entries = list.getEntries();
    if (!entries.length) return;
    var last = entries[entries.length - 1];
    vitals.lcp = Math.round(last.renderTime || last.loadTime || last.startTime);
  }, true);

  // ---- FCP -----------------------------------------------------------------
  safeObserve("paint", function (list) {
    list.getEntries().forEach(function (e) {
      if (e.name === "first-contentful-paint") {
        vitals.fcp = Math.round(e.startTime);
      }
    });
  }, true);

  // ---- INP (longest event duration since session start) -------------------
  var inpEvents = [];
  safeObserve("event", function (list) {
    list.getEntries().forEach(function (e) {
      if (!e.interactionId) return;
      inpEvents.push(e.duration);
      if (inpEvents.length > 200) inpEvents.shift();
      var max = inpEvents.reduce(function (a, b) { return b > a ? b : a; }, 0);
      vitals.inp = Math.round(max);
    });
  }, false);

  // ---- CLS (sum within session window, cap-based per spec) ----------------
  var clsValue = 0, clsEntries = [], sessionValue = 0, sessionEntries = [];
  safeObserve("layout-shift", function (list) {
    list.getEntries().forEach(function (e) {
      if (e.hadRecentInput) return;
      var first = sessionEntries[0];
      var last = sessionEntries[sessionEntries.length - 1];
      if (sessionEntries.length &&
          e.startTime - last.startTime < 1000 &&
          e.startTime - first.startTime < 5000) {
        sessionValue += e.value;
        sessionEntries.push(e);
      } else {
        sessionValue = e.value;
        sessionEntries = [e];
      }
      if (sessionValue > clsValue) {
        clsValue = sessionValue;
        clsEntries = sessionEntries.slice();
        vitals.cls = Math.round(clsValue * 1000) / 1000;
      }
    });
  }, true);

  // ---- TTFB (one-shot, from navigation entry) -----------------------------
  try {
    var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    if (nav) vitals.ttfb = Math.round(nav.responseStart - nav.startTime);
  } catch (e) { /* legacy timing API absent — skip */ }

  // ---- Beacon dispatch ----------------------------------------------------
  var sent = false;
  function send() {
    if (sent) return;
    sent = true;
    try { observers.forEach(function (po) { try { po.disconnect(); } catch (e) {} }); } catch (e) {}
    var payload = {
      url: location.pathname,
      ts: Date.now(),
      lcp: vitals.lcp, inp: vitals.inp, cls: vitals.cls,
      ttfb: vitals.ttfb, fcp: vitals.fcp,
      conn: (navigator.connection && navigator.connection.effectiveType) || null,
      dpr: window.devicePixelRatio || 1,
      vw: window.innerWidth || 0
    };
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: "application/json" });
        if (navigator.sendBeacon(BEACON_PATH, blob)) return;
      }
    } catch (e) { /* fall through to fetch */ }
    try {
      fetch(BEACON_PATH, { method: "POST", body: body, keepalive: true,
        headers: { "Content-Type": "application/json" } }).catch(function () {});
    } catch (e) { /* swallow — RUM must not impact UX */ }
  }

  // Fire on the first of pagehide / visibilitychange-hidden — matches
  // web-vitals.js semantics and ensures we capture the final CLS/INP.
  addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") send();
  });
  addEventListener("pagehide", send);
  // Safety: if neither fires within 30s, send anyway so single-page sessions
  // that never navigate away still produce a beacon.
  setTimeout(send, 30000);
})();
