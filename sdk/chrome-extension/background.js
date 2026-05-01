// jpcite Chrome 拡張 — service worker (manifest v3 background).
//
// 役割: 右クリック menu「jpcite で開く」を全ページに登録し、選択テキストを
// 法人番号 (13桁) / 適格請求書番号 (T+13桁) / 一般クエリ に振り分けて
// api.jpcite.com の対応エンドポイントを新タブで開く。
//
// 仕様メモ:
//   - LLM API 呼出は禁止 (CLAUDE.md 非交渉制約)。本拡張は URL を組み立てて
//     ブラウザに新タブを開かせるだけで、サーバ側で LLM を呼ぶことはない。
//   - 全件 ¥3/req 課金。匿名 3 req/日 無料 (IPベース、JST 翌日 00:00 リセット)。
//   - host_permissions は空 (manifest)。fetch を内部で行わないので不要。
//
// 13桁判定:
//   13桁数字 (T プレフィックス可) → 法人番号 → /v1/houjin/{13digits}
//   それ以外 → 一般クエリ → /v1/programs/search?q=<encoded>

const API_BASE = "https://api.jpcite.com/v1";

function buildLookupUrl(rawText) {
  const text = (rawText || "").trim();
  if (!text) return null;
  // T プレフィックス対応 (適格請求書発行事業者番号フォーマット)。
  // 国税庁 法人番号は数字のみ 13桁、jpcite の /v1/houjin/{n} はどちらでも受ける。
  const digits = text.replace(/\D/g, "");
  if (/^T?\d{13}$/i.test(text) && digits.length === 13) {
    return `${API_BASE}/houjin/${digits}`;
  }
  return `${API_BASE}/programs/search?q=${encodeURIComponent(text)}`;
}

function openLookup(rawText) {
  const url = buildLookupUrl(rawText);
  if (!url) return;
  chrome.tabs.create({ url, active: true });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "jpcite-lookup-selection",
    title: "jpcite で照会 (\"%s\")",
    contexts: ["selection"]
  });
  chrome.contextMenus.create({
    id: "jpcite-lookup-page",
    title: "jpcite を開く",
    contexts: ["page"]
  });
});

chrome.contextMenus.onClicked.addListener((info, _tab) => {
  if (info.menuItemId === "jpcite-lookup-selection" && info.selectionText) {
    openLookup(info.selectionText);
  } else if (info.menuItemId === "jpcite-lookup-page") {
    chrome.tabs.create({ url: "https://jpcite.com/", active: true });
  }
});

// popup.js から「open」メッセージを受けてタブを開く (popup の window.open は
// 一部環境で popup を閉じる前に発火しないため、background に委譲する)。
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "jpcite-open") {
    openLookup(msg.text);
    sendResponse({ ok: true });
  }
  return false;
});
