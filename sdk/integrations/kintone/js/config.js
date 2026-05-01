/**
 * jpcite kintone plug-in — configuration screen.
 *
 * Renders the form bound to `config.html` and persists values via
 * `kintone.plugin.app.setConfig`. Two fields:
 *   - apiKey            : jpcite API key (X-API-Key)
 *   - houjinFieldCode   : kintone field code that holds 13-digit 法人番号
 */
(function (PLUGIN_ID) {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var cfg = kintone.plugin.app.getConfig(PLUGIN_ID) || {};

    var apiKeyInput = document.getElementById("jpcite-api-key");
    var houjinInput = document.getElementById("jpcite-houjin-field-code");

    apiKeyInput.value = cfg.apiKey || "";
    houjinInput.value = cfg.houjinFieldCode || "";

    document
      .getElementById("jpcite-config-form")
      .addEventListener("submit", function (ev) {
        ev.preventDefault();
        var apiKey = (apiKeyInput.value || "").trim();
        var houjinFieldCode = (houjinInput.value || "").trim();
        if (!apiKey) {
          window.alert("API キーを入力してください。");
          return;
        }
        if (!houjinFieldCode) {
          window.alert("法人番号フィールドコードを入力してください。");
          return;
        }
        kintone.plugin.app.setConfig(
          { apiKey: apiKey, houjinFieldCode: houjinFieldCode },
          function () {
            window.alert("設定を保存しました。アプリを更新してください。");
            window.location.href = "../../" + kintone.app.getId() + "/plugin/";
          }
        );
      });

    document
      .getElementById("jpcite-config-cancel")
      .addEventListener("click", function () {
        window.history.back();
      });
  });
})(kintone.$PLUGIN_ID);
