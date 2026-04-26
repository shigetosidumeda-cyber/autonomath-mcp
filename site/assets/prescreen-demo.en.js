// Prescreen demo widget (EN copy) — posts profile to /v1/programs/prescreen and
// renders the top matches. Anonymous calls hit the per-IP free quota
// (50 req/month, JST first-of-month reset) — no API key needed.
//
// API base is read from the <form data-api-base> attribute on the
// landing <form>. To point at a local API during development,
// temporarily edit that attribute in site/en/index.html.
//
// Mirrors site/assets/prescreen-demo.js but with all user-visible
// string literals translated to English. JS hooks (ids, names, fetch
// payload keys) are identical so the same backend handles both pages.
(function () {
  "use strict";

  var form = document.getElementById("ps-form");
  var submit = document.getElementById("ps-submit");
  var resultsEl = document.getElementById("ps-results");
  // Wave 17 a11y: dedicated status live-region so screen readers
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
          '<a class="ps-name" href="/programs/' + escapeHtml(r.unified_id) + '.html">' +
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
          'Anonymous limit reached (50 req/month per IP). <a href="/dashboard.html">Issue an API key</a> (Free 50 req/month; overage ¥3/req, ¥3.30 tax incl.).'
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
          // canonical `error` envelope still pass through unchanged.
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
        '<a class="btn btn-primary" href="/dashboard.html">Get more with an API key (Free 50 req/month)</a>' +
        '<a class="btn btn-secondary" href="/en/getting-started.html">Connect via MCP</a>' +
        "</div>";
      resultsEl.innerHTML =
        '<p class="ps-status">' + escapeHtml(summary) + "</p>" + renderRows(data.results || []) + ctaHtml;
      // Announce only the summary, not the full result HTML — screen
      // readers were re-reading every row on each render before this.
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
