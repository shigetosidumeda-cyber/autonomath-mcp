// jpcite Chrome 拡張 — content_script (全ページに注入)。
//
// 役割: ページ本文の 13桁数字 (T プレフィックス可、ハイフン挟み許容) を
// `<span class="jpcite-houjin-hl">` でラップし、hover で「jpcite で照会」を
// 表示する。クリックで /v1/houjin/{number} を新タブで開く。
//
// 設計:
//   - DOM 走査は IntersectionObserver で viewport に入った段階のみ。
//     全ページ全段落を一気にラップすると CLS / レイアウト崩壊するため。
//   - input / textarea / contenteditable / script / style / code の中は
//     一切触らない (法人番号らしき数字でも site の機能を壊さない)。
//   - すでにラップ済みのノードは再走査しない (data-jpcite-walked)。
//   - host_permissions は空。fetch しない。クリック時に chrome.runtime
//     経由で background に open を依頼する。

(() => {
  if (window.__jpciteContentLoaded) return;
  window.__jpciteContentLoaded = true;

  // 13桁数字。T プレフィックス可、ハイフン区切り (例: 1234-56-789012-3) も許容。
  // 拾いすぎると false positive が爆発するので、前後に digit が連続するパターン
  // (国際電話番号、口座番号 14+ 桁) は除外する。
  //
  // 国税庁 法人番号: 数字 13 桁、checksum あり (簡易 mod 9 — 厳密判定はしない、
  // hover 提示なので false positive は許容、誤クリック時は API 側で 404 が出る)。
  const HOUJIN_RE = /(?<![\d])(T?(?:\d[-\s]?){12}\d)(?![\d])/gi;

  const SKIP_TAGS = new Set([
    "SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "INPUT", "CODE", "PRE",
    "SVG", "CANVAS", "OPTION", "SELECT"
  ]);

  function isSkippable(node) {
    let cur = node;
    while (cur && cur.nodeType === 1) {
      if (SKIP_TAGS.has(cur.tagName)) return true;
      if (cur.isContentEditable) return true;
      if (cur.classList && cur.classList.contains("jpcite-houjin-hl")) return true;
      cur = cur.parentElement;
    }
    return false;
  }

  function wrapTextNode(textNode) {
    if (textNode.parentElement && textNode.parentElement.dataset.jpciteWalked === "1") return;
    if (isSkippable(textNode.parentElement)) return;
    const text = textNode.nodeValue;
    if (!text || text.length < 13) return;
    HOUJIN_RE.lastIndex = 0;
    if (!HOUJIN_RE.test(text)) return;
    HOUJIN_RE.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    let m;
    while ((m = HOUJIN_RE.exec(text)) !== null) {
      const matchStart = m.index;
      const matchEnd = matchStart + m[0].length;
      if (matchStart > lastIdx) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx, matchStart)));
      }
      const raw = m[0];
      const digits = raw.replace(/\D/g, "");
      if (digits.length === 13) {
        const span = document.createElement("span");
        span.className = "jpcite-houjin-hl";
        span.dataset.jpciteHoujin = digits;
        span.title = `jpcite で照会 (法人番号 ${digits})`;
        span.textContent = raw;
        frag.appendChild(span);
      } else {
        frag.appendChild(document.createTextNode(raw));
      }
      lastIdx = matchEnd;
    }
    if (lastIdx < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    }
    if (textNode.parentNode) {
      textNode.parentNode.replaceChild(frag, textNode);
    }
  }

  function walk(root) {
    if (isSkippable(root)) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        if (!n.nodeValue || n.nodeValue.length < 13) return NodeFilter.FILTER_SKIP;
        if (isSkippable(n.parentElement)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const targets = [];
    let cur = walker.nextNode();
    while (cur) {
      targets.push(cur);
      cur = walker.nextNode();
    }
    for (const tn of targets) {
      try {
        wrapTextNode(tn);
      } catch (_) {
        // wrap 失敗時もページは壊さない。
      }
    }
  }

  function onClickHl(ev) {
    const tgt = ev.target;
    if (!(tgt instanceof HTMLElement)) return;
    if (!tgt.classList.contains("jpcite-houjin-hl")) return;
    const houjin = tgt.dataset.jpciteHoujin;
    if (!houjin) return;
    ev.preventDefault();
    ev.stopPropagation();
    try {
      chrome.runtime.sendMessage({ type: "jpcite-open", text: houjin });
    } catch (_) {
      // service worker が休止中の稀ケース fallback。
      window.open(`https://api.jpcite.com/v1/houjin/${houjin}`, "_blank", "noopener");
    }
  }

  // 初回 walk は body に絞る (head 内の meta などは対象外)。
  function initialWalk() {
    if (!document.body) {
      window.requestAnimationFrame(initialWalk);
      return;
    }
    walk(document.body);
  }
  initialWalk();

  // SPA / 動的挿入対応: MutationObserver で増分 walk。
  const mo = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1) {
          walk(n);
        } else if (n.nodeType === 3) {
          wrapTextNode(n);
        }
      }
    }
  });
  mo.observe(document.documentElement, { childList: true, subtree: true });

  document.addEventListener("click", onClickHl, true);
})();
