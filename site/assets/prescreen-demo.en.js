// Prescreen demo widget (EN copy) — posts profile to /v1/programs/prescreen and
// renders the top matches. Anonymous calls hit the per-IP free quota
// (3 req/day, JST next-day 00:00 reset) — no API key needed.
//
// API base is read from the <form data-api-base> attribute on the
// landing <form>. To point at a local API during development,
// temporarily edit that attribute in site/en/index.html.
//
// Mirrors site/assets/prescreen-demo.src.js but with all user-visible
// string literals translated to English. JS hooks (ids, names, fetch
// payload keys) are identical so the same backend handles both pages.
(function () {
  "use strict";

  var form = document.getElementById("ps-form");
  var submit = document.getElementById("ps-submit");
  var resultsEl = document.getElementById("ps-results");
  // a11y: dedicated status live-region so screen readers
  // announce only the short summary instead of the full results HTML
  // re-rendered into #ps-results. Element may not exist on older
  // static snapshots — degrade silently.
  var statusLiveEl = document.getElementById("ps-status-live");
  function announce(msg) {
    if (statusLiveEl) statusLiveEl.textContent = msg || "";
  }
  if (!form || !submit || !resultsEl) return;

  function resolveEndpoint() {
    // Resolve per-submit so test harnesses and staging can override at runtime.
    var base = form.getAttribute("data-api-base") || "";
    return base.replace(/\/+$/, "") + "/v1/programs/prescreen";
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c];
    });
  }

  function formatAmount(manYen) {
    if (manYen == null) return "Amount not disclosed";
    if (manYen >= 10000) {
      // 1 oku-yen = 100 million yen. Render as "¥X.X 100M" for EN.
      return "¥" + (manYen / 10000).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "00M";
    }
    // 1 man-yen = 10,000 yen.
    return "¥" + (manYen * 10000).toLocaleString("en-US");
  }

  // Resolve the per-program SEO page URL. The API ships a `static_url`
  // field (e.g. "/programs/100-nen-fuudo-...-a0d253.html") computed from
  // primary_name + unified_id via utils/slug.py. Older API builds may
  // not return it; fall back to the program list page rather than emit a
  // guaranteed 404 (`/programs/UNI-xxxx.html` is NOT a real file —
  // static pages are slug-named).
  function programHref(r) {
    if (r && typeof r.static_url === "string" && r.static_url) {
      return r.static_url;
    }
    return "/programs/";
  }

  // Last results object, captured for the post-render handoff buttons
  // (Send to tax advisor / PDF / Share URL). Holds a flat object the
  // buttons read synchronously so they don't have to re-fetch the API.
  var lastResults = null;

  function renderRows(results) {
    if (!results.length) {
      return (
        '<p class="ps-status">No programs matched these criteria. Try changing the prefecture or planned investment amount.</p>'
      );
    }
    var items = results
      .map(function (r) {
        var tier = r.tier || "";
        var reasonsHtml = (r.match_reasons || [])
          .map(function (x) {
            return "<li>" + escapeHtml(x) + "</li>";
          })
          .join("");
        var caveatsHtml = (r.caveats || [])
          .map(function (x) {
            return "<li>" + escapeHtml(x) + "</li>";
          })
          .join("");
        var sourceHtml = r.official_url
          ? '<p class="ps-source">Source: <a rel="noopener noreferrer nofollow" target="_blank" href="' +
            escapeHtml(r.official_url) +
            '">' +
            escapeHtml(r.official_url) +
            "</a></p>"
          : "";
        return (
          '<li class="ps-row">' +
          '<div class="ps-row-head">' +
          (tier ? '<span class="ps-tier t-' + escapeHtml(tier) + '">Tier ' + escapeHtml(tier) + "</span>" : "") +
          '<a class="ps-name" href="' + escapeHtml(programHref(r)) + '">' +
          escapeHtml(r.primary_name || r.unified_id) +
          "</a>" +
          '<span class="ps-amount">Up to ' +
          escapeHtml(formatAmount(r.amount_max_man_yen)) +
          "</span>" +
          "</div>" +
          (reasonsHtml ? '<ul class="ps-reasons">' + reasonsHtml + "</ul>" : "") +
          (caveatsHtml ? '<ul class="ps-caveats">' + caveatsHtml + "</ul>" : "") +
          sourceHtml +
          "</li>"
        );
      })
      .join("");
    return '<ul class="ps-list">' + items + "</ul>";
  }

  // Format one result as a numbered block in a tax-advisor mailto body.
  // Plain text only — Japanese mail clients still mishandle HTML mail.
  function _resultPlainBlock(r, index) {
    var lines = [];
    lines.push((index + 1) + ". " + (r.primary_name || r.unified_id));
    var origin = (typeof window !== "undefined" && window.location && window.location.origin) || "https://jpcite.com";
    var path = (typeof r.static_url === "string" && r.static_url) ? r.static_url : "/programs/";
    lines.push("   URL: " + origin + path);
    if (r.amount_max_man_yen != null) {
      var amount = (r.amount_max_man_yen >= 10000)
        ? ("¥" + (r.amount_max_man_yen / 10000).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "00M")
        : ("¥" + (r.amount_max_man_yen * 10000).toLocaleString("en-US"));
      lines.push("   Max amount: " + amount);
    } else {
      lines.push("   Max amount: not disclosed");
    }
    if (r.tier) {
      lines.push("   Tier: " + r.tier);
    }
    if (r.official_url) {
      lines.push("   Source: " + r.official_url);
    }
    return lines.join("\n");
  }

  // Tax Accountant Act §52 disclaimer: the program list returned by
  // jpcite is a mechanical primary-source candidate set, not advice
  // on whether to apply or how to file. Always append this note in the
  // mail body footer.
  function _mailtoBody(results) {
    var n = results.length;
    var origin = (typeof window !== "undefined" && window.location && window.location.origin) || "https://jpcite.com";
    var blocks = results.map(function (r, i) { return _resultPlainBlock(r, i); }).join("\n\n");
    return [
      "Hello,",
      "",
      "I ran a jpcite prescreen for our company and got the following " + n + " candidate program(s).",
      "Could you please review and advise whether we should apply?",
      "",
      blocks,
      "",
      "----",
      "Tax Accountant Act §52 disclaimer:",
      "This list is a mechanical candidate match against primary sources.",
      "Whether we are eligible to apply, and how to file, is the judgment",
      "of a licensed 税理士 / 行政書士.",
      "",
      "Source: jpcite",
      origin + "/",
    ].join("\n");
  }

  function _openMailToTaxAdvisor() {
    if (!lastResults || !lastResults.length) return;
    var subject = "[jpcite] " + lastResults.length + " candidate program(s) for review";
    var body = _mailtoBody(lastResults);
    // mailto: limits vary across clients (Gmail web ~2KB, Outlook ~2083 chars,
    // Apple Mail ~64KB). Trim defensively at 1900 chars so the most common
    // 2KB cap doesn't drop the §52 disclaimer at the end.
    var MAX = 1900;
    if (body.length > MAX) {
      body = body.slice(0, MAX) + "\n... (see the page for the full list)";
    }
    var href = "mailto:?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
    window.location.href = href;
  }

  function _printToPdf() {
    // Browser native print → "Save as PDF". No backend, no SaaS dep.
    // The CSS print styles (styles.css `@media print`) hide nav / form /
    // CTA so only the result list ends up on paper.
    if (typeof window.print === "function") {
      window.print();
    }
  }

  // Build a `?ids=UNI-a,UNI-b,...` query string for the share URL.
  // Caps total characters at 1800 to stay inside common URL length
  // limits (Twitter card preview, LINE share, copy-paste behaviour).
  function _buildShareUrl() {
    if (!lastResults || !lastResults.length) return null;
    var ids = lastResults.map(function (r) { return r.unified_id; }).filter(Boolean);
    var origin = (typeof window !== "undefined" && window.location && window.location.origin) || "https://jpcite.com";
    var url = origin + "/programs/share.html?ids=" + encodeURIComponent(ids.join(","));
    if (url.length > 1800) {
      url = url.slice(0, 1800);
    }
    return url;
  }

  function _copyShareUrl() {
    var url = _buildShareUrl();
    if (!url) return;
    var copied = false;
    try {
      if (navigator && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        navigator.clipboard.writeText(url).then(function () {
          announce("Share URL copied");
        }, function () {
          // Promise reject path → fall through to legacy execCommand.
        });
        copied = true;
      }
    } catch (_) {
      copied = false;
    }
    if (!copied) {
      // Legacy textarea + execCommand("copy") fallback for browsers /
      // contexts that block navigator.clipboard (HTTP, embedded WebView).
      try {
        var ta = document.createElement("textarea");
        ta.value = url;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        announce("Share URL copied");
      } catch (_) {
        // Last resort: prompt() lets the user copy manually.
        try { window.prompt("Copy this URL", url); } catch (__) {}
      }
    }
  }

  function _handoffButtonsHtml() {
    return (
      '<div class="ps-handoff" role="group" aria-label="Share / send results">' +
      '<button type="button" class="btn btn-primary" data-ps-action="mailto-tax-advisor">Send to tax advisor</button>' +
      '<button type="button" class="btn btn-secondary" data-ps-action="print-pdf">Save as PDF</button>' +
      '<button type="button" class="btn btn-secondary" data-ps-action="copy-share-url">Copy share URL</button>' +
      "</div>"
    );
  }

  // Single delegated click handler — survives every re-render of
  // resultsEl.innerHTML because the listener lives on resultsEl itself.
  resultsEl.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.getAttribute) return;
    var action = t.getAttribute("data-ps-action");
    if (!action) return;
    e.preventDefault();
    if (action === "mailto-tax-advisor") {
      _openMailToTaxAdvisor();
    } else if (action === "print-pdf") {
      _printToPdf();
    } else if (action === "copy-share-url") {
      _copyShareUrl();
    }
  });

  function setBusy(on) {
    submit.disabled = on;
    submit.textContent = on ? "Searching…" : "Show top 5";
    resultsEl.setAttribute("aria-busy", on ? "true" : "false");
  }

  function showError(msg) {
    resultsEl.classList.add("is-visible");
    resultsEl.innerHTML = '<p class="ps-error">' + escapeHtml(msg) + "</p>";
    announce("Error: " + msg);
  }

  // Variant of showError for trusted, static HTML (e.g. the 429 upgrade
  // pitch which embeds a literal <a href="/dashboard.html"> link). Never
  // pass user-controlled or API-returned strings to this function.
  function showRichError(html) {
    resultsEl.classList.add("is-visible");
    resultsEl.innerHTML = '<p class="ps-error">' + html + "</p>";
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();

    var honeypot = form.elements["company_url"];
    if (honeypot && honeypot.value) {
      resultsEl.classList.add("is-visible");
      resultsEl.innerHTML = '<p class="ps-status">Submitted</p>';
      return;
    }

    setBusy(true);

    var prefecture = form.elements["prefecture"].value || null;
    var formType = form.elements["form_type"].value;
    var investment = form.elements["planned_investment_man_yen"].value;

    var body = { limit: 5 };
    // The select option for "nationwide / no prefecture filter" still
    // carries the Japanese value "全国" so the backend payload matches
    // the JA page exactly.
    if (prefecture && prefecture !== "全国") body.prefecture = prefecture;
    if (formType === "true") body.is_sole_proprietor = true;
    else if (formType === "false") body.is_sole_proprietor = false;
    if (investment) body.planned_investment_man_yen = Number(investment);

    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 15000);

    try {
      var resp = await fetch(resolveEndpoint(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (resp.status === 429) {
        showRichError(
          'Anonymous limit reached (3 req/day per IP). <a href="/dashboard.html">Issue an API key</a> (Free 3 req/day; overage ¥3/req, ¥3.30 tax incl.).'
        );
        return;
      }
      if (!resp.ok) {
        var text = "";
        try {
          var j = await resp.json();
          // FastAPI 422 returns `detail` as an ARRAY of error objects.
          // String(array) produces "[object Object]" garbage, so detect
          // that case first and prefer the JA summary emitted by
          // api/main.py:_validation_handler (the EN page intentionally
          // surfaces the JA summary because the per-field msg_ja is the
          // only translated copy the API ships today), falling back to a
          // per-field join. Plain string `detail` (401/404/etc.) and the
          // canonical `error` response shape still pass through unchanged.
          if (Array.isArray(j.detail)) {
            text =
              j.detail_summary_ja ||
              j.detail
                .map(function (e) {
                  return e.msg_ja || e.msg || "";
                })
                .filter(Boolean)
                .join(", ") ||
              "Validation failed.";
          } else {
            text = j.detail || j.error || JSON.stringify(j);
          }
        } catch (_) {
          text = "HTTP " + resp.status;
        }
        showError("Request failed: " + text);
        return;
      }
      var data = await resp.json();
      // Capture for the post-render handoff buttons (Send to tax advisor /
      // PDF / Share URL). Stored as a flat array of result objects so the
      // buttons can build mail bodies / share URLs synchronously.
      lastResults = (data.results || []).slice();
      var summary =
        "Showing top " +
        ((data.results || []).length) +
        " of " +
        (data.total_considered || 0).toLocaleString("en-US") +
        " candidates, ranked by fit.";
      resultsEl.classList.add("is-visible");
      // Trailing CTA links are static literals — safe to inject without escaping.
      // Highest-intent moment after rendering matches → ask for the next step.
      var ctaHtml =
        '<div class="ps-cta">' +
        '<a class="btn btn-primary" href="/dashboard.html">Get more with an API key (Free 3 req/day)</a>' +
        '<a class="btn btn-secondary" href="/en/getting-started.html">Connect via MCP</a>' +
        "</div>";
      // SMB owner → tax advisor reseller handoff: surface mailto + print-to-PDF
      // + copy-share-URL right under the result list so SMB owners hand the
      // candidate list off without copy-pasting. Only render when we actually
      // have results — empty / error states keep the original CTAs as the
      // only next step.
      var handoffHtml = (lastResults.length > 0) ? _handoffButtonsHtml() : "";
      resultsEl.innerHTML =
        '<p class="ps-status">' + escapeHtml(summary) + "</p>" + renderRows(data.results || []) + handoffHtml + ctaHtml;
      // Announce only the summary, not the full result HTML — screen
      // readers were re-reading each rendered row before this.
      announce(summary);
    } catch (err) {
      if (err && err.name === "AbortError") {
        showError("Timeout — slow connection or unresponsive server. Please try again.");
      } else {
        showError(
          "Network error. Please retry in a moment (" +
            (err && err.message ? err.message : "unknown") +
            ")"
        );
      }
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  });
})();
