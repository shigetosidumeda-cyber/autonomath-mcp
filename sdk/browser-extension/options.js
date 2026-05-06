// jpcite browser extension — options page controller.
//
// 役割: API key を chrome.storage.sync.api_key に保存。
//       (sync は Chrome アカウント間で 100KB まで同期される — API key は十分収まる)

(() => {
  const input = document.getElementById("api_key");
  const status = document.getElementById("status");
  const btnSave = document.getElementById("btn-save");
  const btnClear = document.getElementById("btn-clear");

  function setStatus(msg, kind) {
    status.textContent = msg;
    status.className = "status " + (kind || "");
    if (msg) {
      setTimeout(() => {
        if (status.textContent === msg) {
          status.textContent = "";
          status.className = "status";
        }
      }, 3000);
    }
  }

  // 既存 key を読み込み
  chrome.storage.sync.get(["api_key"], (out) => {
    if (out?.api_key) input.value = out.api_key;
  });

  btnSave.addEventListener("click", () => {
    const v = input.value.trim();
    chrome.storage.sync.set({ api_key: v }, () => {
      if (chrome.runtime.lastError) {
        setStatus("保存失敗: " + chrome.runtime.lastError.message, "err");
      } else if (v) {
        setStatus("保存しました。", "ok");
      } else {
        setStatus("空欄で保存 (匿名モード)", "ok");
      }
    });
  });

  btnClear.addEventListener("click", () => {
    input.value = "";
    chrome.storage.sync.remove(["api_key"], () => {
      setStatus("クリアしました (匿名モード)", "ok");
    });
  });

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      btnSave.click();
    }
  });
})();
