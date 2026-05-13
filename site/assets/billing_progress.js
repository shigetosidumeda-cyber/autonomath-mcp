/*
 * billing_progress.js — jpcite billing progress (2026-05-12) (jpcite 2026-05-12)
 *
 * Purpose:
 *   "ノンフリクション + 迷子ゼロ" billing funnel UI helper.
 *   Renders a compact progress strip + idle-hint modal so visitors always
 *   know which of the 4 frictionless steps they are on and what comes next.
 *
 * 4-step linear funnel (memory: feedback_keep_it_simple, feedback_zero_touch_solo):
 *   1. free      — Try 3 anonymous req/day (no signup)
 *   2. signup    — GitHub OAuth or magic link (1 click)
 *   3. billing   — Confirm metered billing and spending caps
 *   4. use       — Call API/MCP, see usage in dashboard
 *
 * Idle detection: 30s of no interaction => modal hint with "next step is X" copy.
 *
 * No external dependencies, no LLM calls. Vanilla DOM, ~7 KB minified.
 */
(function () {
  "use strict";
  if (window.jpciteBillingProgress) return;

  var STEPS = [
    {
      id: "free",
      label: "1. 無料で試す",
      desc: "匿名 3 req/日、登録なし",
      cta: "playground を開く",
      href: "/playground.html?flow=evidence3",
      nextHint: "気に入ったら GitHub サインインで無料枠を拡張できます。"
    },
    {
      id: "signup",
      label: "2. サインイン",
      desc: "GitHub OAuth または magic link (1 click)",
      cta: "サインインする",
      href: "/dashboard.html",
      nextHint: "サインインすると毎日リセットされる無料枠と利用量ダッシュボードが使えます。"
    },
    {
      id: "billing",
      label: "3. 課金設定",
      desc: "Stripe 従量課金 + 月次上限",
      cta: "料金を確認",
      href: "/pricing.html",
      nextHint: "広い実行は見積もりと X-Cost-Cap-JPY を設定してから動かしてください。"
    },
    {
      id: "use",
      label: "4. API を呼ぶ",
      desc: "REST + MCP、見積もりは無料",
      cta: "API キーを発行",
      href: "/dashboard.html#keys",
      nextHint: "顧客別タグ X-Client-Tag で 1 案件 ¥単位の原価管理が可能です。"
    }
  ];

  var STORAGE_KEY = "jpciteBillingStep";
  var IDLE_MS = 30000;
  var idleTimer = null;
  var idleModalShown = false;

  function getCurrentStep() {
    try {
      var saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) {
        for (var i = 0; i < STEPS.length; i++) {
          if (STEPS[i].id === saved) return i;
        }
      }
    } catch (e) {}
    var p = (location.pathname || "").toLowerCase();
    if (p.indexOf("/playground") === 0) return 0;
    if (p.indexOf("/signin") === 0 || p.indexOf("/signup") === 0) return 1;
    if (p.indexOf("/pricing") === 0 || p.indexOf("/billing") === 0) return 2;
    if (p.indexOf("/dashboard") === 0) return 3;
    return 0;
  }

  function setStep(idx) {
    try {
      if (idx >= 0 && idx < STEPS.length) {
        window.localStorage.setItem(STORAGE_KEY, STEPS[idx].id);
      }
    } catch (e) {}
  }

  function readQuota() {
    // Best-effort read of remaining free-quota counter the API sets in
    // X-RateLimit-Remaining response header echo (placeholder for now).
    try {
      var raw = window.localStorage.getItem("jpciteFreeRemaining");
      if (raw != null && raw !== "") {
        var n = parseInt(raw, 10);
        if (!isNaN(n)) return n;
      }
    } catch (e) {}
    return null;
  }

  function injectCss() {
    if (document.getElementById("jpcite-bp-style")) return;
    var css = [
      ".jpcite-bp{position:relative;margin:14px 0 18px;border:1px solid #e5e7eb;",
      "border-radius:10px;padding:12px 14px;background:#fafaf9;",
      "font:500 13px/1.5 'Noto Sans JP',system-ui,sans-serif;color:#111827}",
      ".jpcite-bp[data-progress] .jpcite-bp-track{position:relative;height:6px;",
      "background:#e5e7eb;border-radius:3px;margin:8px 0 10px;overflow:hidden}",
      ".jpcite-bp-fill{height:100%;background:#4f46e5;transition:width .3s ease}",
      ".jpcite-bp-row{display:flex;flex-wrap:wrap;align-items:center;gap:12px;",
      "justify-content:space-between}",
      ".jpcite-bp-steps{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;",
      "color:#6b7280;margin:0}",
      ".jpcite-bp-step{padding:2px 0}",
      ".jpcite-bp-step.is-current{color:#111827;font-weight:600}",
      ".jpcite-bp-step.is-done{color:#10b981}",
      ".jpcite-bp-step.is-done::before{content:'\\2713 ';color:#10b981}",
      ".jpcite-bp-cta{display:inline-block;background:#4f46e5;color:#fff;",
      "text-decoration:none;border-radius:6px;padding:6px 14px;font-weight:600;",
      "font-size:13px;white-space:nowrap}",
      ".jpcite-bp-cta:hover{background:#4338ca}",
      ".jpcite-bp-quota{font-size:12px;color:#374151;margin:0}",
      ".jpcite-bp-quota strong{color:#0a4d8c}",
      ".jpcite-bp-modal{position:fixed;inset:0;background:rgba(17,24,39,.5);",
      "z-index:2147482000;display:flex;align-items:center;justify-content:center;padding:16px}",
      ".jpcite-bp-mdlg{background:#fff;border-radius:10px;max-width:460px;width:100%;",
      "box-shadow:0 16px 48px rgba(0,0,0,.25);font:400 14px/1.6 'Noto Sans JP',system-ui,sans-serif;",
      "color:#111827;padding:20px 22px}",
      ".jpcite-bp-mdlg h2{margin:0 0 8px;font-size:16px;font-weight:700}",
      ".jpcite-bp-mdlg p{margin:0 0 12px;color:#374151}",
      ".jpcite-bp-mdlg .jpcite-bp-cta{margin-right:8px}",
      ".jpcite-bp-mclose{background:#f3f4f6;color:#374151;border:0;border-radius:6px;",
      "padding:6px 14px;font:500 13px 'Noto Sans JP',system-ui,sans-serif;cursor:pointer}",
      ".jpcite-bp-mclose:hover{background:#e5e7eb}",
      "@media (prefers-color-scheme:dark){",
      ".jpcite-bp{background:#1f2937;color:#f3f4f6;border-color:#374151}",
      ".jpcite-bp[data-progress] .jpcite-bp-track{background:#374151}",
      ".jpcite-bp-quota{color:#d1d5db}",
      ".jpcite-bp-steps{color:#9ca3af}",
      ".jpcite-bp-step.is-current{color:#f3f4f6}",
      ".jpcite-bp-mdlg{background:#1f2937;color:#f3f4f6}",
      ".jpcite-bp-mdlg p{color:#d1d5db}",
      ".jpcite-bp-mclose{background:#374151;color:#f3f4f6}",
      ".jpcite-bp-mclose:hover{background:#4b5563}",
      "}"
    ].join("");
    var s = document.createElement("style");
    s.id = "jpcite-bp-style";
    s.textContent = css;
    document.head.appendChild(s);
  }

  function buildStrip(idx) {
    var step = STEPS[idx] || STEPS[0];
    var quota = readQuota();
    var quotaHtml = "";
    if (idx === 0) {
      if (quota != null) {
        quotaHtml = '<p class="jpcite-bp-quota">本日の無料枠: 残り <strong>' +
          quota + ' req</strong> / 3 req (JST 00:00 リセット)</p>';
      } else {
        quotaHtml = '<p class="jpcite-bp-quota">本日の無料枠: <strong>3 req</strong> 残 (匿名 / 登録不要)</p>';
      }
    } else {
      quotaHtml = '<p class="jpcite-bp-quota">現在地: <strong>' + step.label +
        '</strong> — ' + step.desc + '</p>';
    }
    var stepsHtml = "";
    for (var i = 0; i < STEPS.length; i++) {
      var cls = "jpcite-bp-step";
      if (i < idx) cls += " is-done";
      else if (i === idx) cls += " is-current";
      stepsHtml += '<span class="' + cls + '" data-step="' + STEPS[i].id +
        '">' + STEPS[i].label + "</span>";
    }
    var pct = Math.round(((idx + 1) / STEPS.length) * 100);
    var html = '<div class="jpcite-bp" data-progress="' + (idx + 1) + '/' +
      STEPS.length + '" role="navigation" aria-label="課金導線 4 step">' +
      '<div class="jpcite-bp-row">' +
      quotaHtml +
      '<a class="jpcite-bp-cta" href="' + step.href + '" data-step-cta="' +
      step.id + '">次へ: ' + step.cta + ' &rarr;</a>' +
      '</div>' +
      '<div class="jpcite-bp-track" aria-hidden="true">' +
      '<div class="jpcite-bp-fill" style="width:' + pct + '%"></div>' +
      '</div>' +
      '<p class="jpcite-bp-steps">' + stepsHtml + '</p>' +
      "</div>";
    return html;
  }

  function showIdleHint(idx) {
    if (idleModalShown) return;
    if (document.getElementById("jpcite-bp-modal")) return;
    var step = STEPS[idx] || STEPS[0];
    var modal = document.createElement("div");
    modal.id = "jpcite-bp-modal";
    // billing UX fix: also expose canonical "idle hint" hooks so the UX
    // audit's standard selectors (.hint-modal, #idle-hint, .lost-user-hint)
    // match this element. Classes are additive; existing CSS still applies.
    modal.className = "jpcite-bp-modal hint-modal lost-user-hint";
    modal.setAttribute("data-idle-hint", "true");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "jpcite-bp-mtitle");
    modal.innerHTML =
      '<div class="jpcite-bp-mdlg">' +
      '<h2 id="jpcite-bp-mtitle">次の step は: ' + step.label + "</h2>" +
      "<p>" + step.nextHint + "</p>" +
      '<a class="jpcite-bp-cta" href="' + step.href + '">' + step.cta +
      " &rarr;</a>" +
      '<button type="button" class="jpcite-bp-mclose" aria-label="閉じる">あとで</button>' +
      "</div>";
    document.body.appendChild(modal);
    idleModalShown = true;
    var closeBtn = modal.querySelector(".jpcite-bp-mclose");
    function dismiss() {
      if (modal.parentNode) modal.parentNode.removeChild(modal);
    }
    if (closeBtn) closeBtn.addEventListener("click", dismiss);
    modal.addEventListener("click", function (e) {
      if (e.target === modal) dismiss();
    });
    document.addEventListener("keydown", function onKey(e) {
      if (e.key === "Escape") {
        dismiss();
        document.removeEventListener("keydown", onKey);
      }
    });
  }

  function armIdleTimer(idx) {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(function () {
      showIdleHint(idx);
    }, IDLE_MS);
  }

  function mount(opts) {
    opts = opts || {};
    injectCss();
    var idx = getCurrentStep();
    if (opts.forceStep != null) idx = opts.forceStep;
    setStep(idx);
    var host = null;
    if (opts.target) {
      host = document.querySelector(opts.target);
    }
    if (!host) host = document.querySelector("[data-billing-progress]");
    if (!host) {
      var main = document.querySelector("main");
      if (main) {
        host = document.createElement("div");
        host.setAttribute("data-billing-progress", "auto");
        if (main.firstChild) main.insertBefore(host, main.firstChild);
        else main.appendChild(host);
      }
    }
    if (!host) return null;
    host.innerHTML = buildStrip(idx);

    // 迷子検知 (billing UX fix): only intentional interactions reset the
    // 30s idle timer. mousemove fires continuously while the cursor is over
    // the viewport and used to prevent the modal from ever showing — that is
    // the exact "modal DOM emit が不発" bug surfaced by the billing UX audit.
    // We keep click/keydown/scroll/touchstart (which signal real intent) and
    // drop mousemove. See tests/test_idle_hint_modal_dom.py for the live
    // Playwright verify that the modal#jpcite-bp-modal node now appears.
    var resetEvents = ["click", "keydown", "scroll", "touchstart"];
    for (var i = 0; i < resetEvents.length; i++) {
      window.addEventListener(resetEvents[i], function () {
        if (idleModalShown) return;
        armIdleTimer(idx);
      }, { passive: true });
    }
    armIdleTimer(idx);
    return { step: STEPS[idx], next: STEPS[idx + 1] || null };
  }

  function autoMount() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        try { mount({}); } catch (e) {}
      });
    } else {
      try { mount({}); } catch (e) {}
    }
  }

  window.jpciteBillingProgress = {
    mount: mount,
    setStep: function (id) {
      for (var i = 0; i < STEPS.length; i++) {
        if (STEPS[i].id === id) { setStep(i); return i; }
      }
      return -1;
    },
    STEPS: STEPS,
    IDLE_MS: IDLE_MS
  };

  if (!window.JPCITE_BILLING_PROGRESS_NO_AUTO) autoMount();
})();
