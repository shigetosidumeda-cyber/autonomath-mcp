// Re-export of the runtime entry point so `manifest.json` paths resolve to
// `js/jpcite.js` while `index.js` keeps the legible top-level location.
//
// kintone serves both files; the manifest only references `js/jpcite.js`,
// but `index.js` (in the plug-in root) is convenient for the developer
// reading the source. Keeping the runtime in one file avoids a duplicated
// codepath. We use a synchronous require shim to load `../index.js`.
//
// In the kintone runtime there is no module loader, so we instead inline
// the same source. To prevent drift, the build script (`npm run pack`)
// bundles `../index.js` into here. Until that script lands the file below
// is byte-identical to `index.js`.
(function () {
  "use strict";

  var PLUGIN_ID = kintone.$PLUGIN_ID;
  var API_BASE = "https://api.jpcite.com";
  var USER_AGENT_NOTE = "jpcite-kintone/0.3.2";
  var CONTAINER_ID = "jpcite-kintone-button-container";
  var MODAL_ID = "jpcite-kintone-modal";

  function loadConfig() {
    var raw = kintone.plugin.app.getConfig(PLUGIN_ID) || {};
    return {
      apiKey: (raw.apiKey || "").trim(),
      houjinFieldCode: (raw.houjinFieldCode || "").trim()
    };
  }

  function asString(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v;
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    return "";
  }

  function escapeHtml(s) {
    return asString(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fetchHoujin(apiKey, bangou) {
    var url = API_BASE + "/v1/houjin/" + encodeURIComponent(bangou);
    return fetch(url, {
      method: "GET",
      headers: {
        "X-API-Key": apiKey,
        Accept: "application/json",
        "X-Client": USER_AGENT_NOTE
      }
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        var e = new Error("AUTH_ERROR");
        e.code = "AUTH_ERROR";
        throw e;
      }
      if (res.status === 404) {
        var e2 = new Error("NOT_FOUND");
        e2.code = "NOT_FOUND";
        throw e2;
      }
      if (res.status === 429) {
        var e3 = new Error("RATE_LIMITED");
        e3.code = "RATE_LIMITED";
        throw e3;
      }
      if (!res.ok) {
        var e4 = new Error("HTTP_" + res.status);
        e4.code = "HTTP_" + res.status;
        throw e4;
      }
      return res.json();
    });
  }

  function renderModal(bangou, payload) {
    var doc = document;
    removeModal();
    var name =
      asString(payload.name) ||
      asString(payload.houjin_name) ||
      "(名称不明)";
    var addr =
      asString(payload.address) || asString(payload.houjin_address) || "";
    var invoiceFlag = payload.qualified_invoice
      ? "登録あり (T" + escapeHtml(asString(bangou)) + ")"
      : "登録なし";
    var enforcement = payload.enforcement_count
      ? "該当 " + escapeHtml(asString(payload.enforcement_count)) + " 件"
      : "該当なし";
    var adoption = payload.adoption_count
      ? escapeHtml(asString(payload.adoption_count)) + " 件"
      : "0 件";
    var modal = doc.createElement("div");
    modal.id = MODAL_ID;
    modal.className = "jpcite-modal";
    modal.innerHTML =
      '<div class="jpcite-modal-card" role="dialog" aria-labelledby="jpcite-modal-title">' +
      '  <header class="jpcite-modal-header">' +
      '    <h2 id="jpcite-modal-title">jpcite 法人 360</h2>' +
      '    <button type="button" class="jpcite-modal-close" aria-label="閉じる">×</button>' +
      "  </header>" +
      '  <dl class="jpcite-modal-body">' +
      "    <dt>法人番号</dt><dd>" + escapeHtml(bangou) + "</dd>" +
      "    <dt>名称</dt><dd>" + escapeHtml(name) + "</dd>" +
      "    <dt>住所</dt><dd>" + escapeHtml(addr) + "</dd>" +
      "    <dt>適格請求書発行事業者</dt><dd>" + invoiceFlag + "</dd>" +
      "    <dt>行政処分</dt><dd>" + enforcement + "</dd>" +
      "    <dt>採択履歴</dt><dd>" + adoption + "</dd>" +
      "  </dl>" +
      '  <footer class="jpcite-modal-footer">' +
      '    <a href="https://jpcite.com/houjin/' + encodeURIComponent(bangou) +
      '" target="_blank" rel="noopener">jpcite.com で全項目を見る</a>' +
      '    <span class="jpcite-cost">¥3/req metered (税込 ¥3.30)</span>' +
      "  </footer>" +
      "</div>";
    doc.body.appendChild(modal);
    modal
      .querySelector(".jpcite-modal-close")
      .addEventListener("click", removeModal);
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) removeModal();
    });
  }

  function renderError(bangou, code) {
    var doc = document;
    removeModal();
    var modal = doc.createElement("div");
    modal.id = MODAL_ID;
    modal.className = "jpcite-modal";
    var msg;
    switch (code) {
      case "AUTH_ERROR":
        msg = "API キーが無効です。kintone のプラグイン設定を確認してください。";
        break;
      case "NOT_FOUND":
        msg = "該当する法人番号が見つかりませんでした。";
        break;
      case "RATE_LIMITED":
        msg = "リクエスト制限に達しました。しばらく時間をおいてください。";
        break;
      default:
        msg = "リクエストに失敗しました (" + escapeHtml(code) + ")。";
    }
    modal.innerHTML =
      '<div class="jpcite-modal-card" role="dialog">' +
      '  <header class="jpcite-modal-header">' +
      "    <h2>jpcite エラー</h2>" +
      '    <button type="button" class="jpcite-modal-close" aria-label="閉じる">×</button>' +
      "  </header>" +
      '  <p class="jpcite-modal-error">法人番号 ' + escapeHtml(bangou) +
      " - " + msg + "</p>" +
      "</div>";
    doc.body.appendChild(modal);
    modal
      .querySelector(".jpcite-modal-close")
      .addEventListener("click", removeModal);
  }

  function removeModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing);
    }
  }

  function injectButton(record) {
    var cfg = loadConfig();
    if (!cfg.apiKey || !cfg.houjinFieldCode) return;
    var bangou = (record[cfg.houjinFieldCode] || {}).value || "";
    bangou = String(bangou).replace(/\D/g, "");
    if (bangou.length !== 13) return;
    var headerEl = kintone.app.record.getHeaderMenuSpaceElement();
    if (!headerEl || document.getElementById(CONTAINER_ID)) return;
    var btn = document.createElement("button");
    btn.id = CONTAINER_ID;
    btn.type = "button";
    btn.className = "jpcite-btn";
    btn.textContent = "jpcite で見る";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      btn.textContent = "取得中…";
      fetchHoujin(cfg.apiKey, bangou)
        .then(function (payload) {
          renderModal(bangou, payload);
        })
        .catch(function (err) {
          renderError(bangou, (err && err.code) || "UNKNOWN");
        })
        .then(function () {
          btn.disabled = false;
          btn.textContent = "jpcite で見る";
        });
    });
    headerEl.appendChild(btn);
  }

  kintone.events.on(
    ["app.record.detail.show", "mobile.app.record.detail.show"],
    function (event) {
      try {
        injectButton(event.record);
      } catch (e) {
        if (window.console) {
          // eslint-disable-next-line no-console
          console.warn("[jpcite-kintone] inject failed:", e);
        }
      }
      return event;
    }
  );
})();
