/* AutonoMath feedback widget.
 *
 * Self-contained vanilla JS. Exposes window.AutonoMathFeedback.mount().
 *
 * Backend schema (src/jpintel_mcp/api/feedback.py) accepts ONLY:
 *   message (required, 1..4000), rating (1..5), endpoint (<=256), request_id (<=128).
 * The UI also collects category + email + page_url locally; we fold those into
 * the `message` body (as prefix lines) and pass `page_url` as `endpoint` so they
 * survive to the DB without changing the API contract.
 *
 * Rate limit: 10/day per IP hash (anonymous) or key_hash (authed).
 */
(function () {
  "use strict";
  if (window.AutonoMathFeedback) return;

  var API_URL =
    (window.AUTONOMATH_API_BASE || "https://api.zeimu-kaikei.ai").replace(/\/+$/, "") +
    "/v1/feedback";

  var STYLE_ID = "am-fb-style";
  var CSS = [
    ".am-fb-fab{position:fixed;right:20px;bottom:20px;z-index:2147483000;",
    "background:#1f2937;color:#fff;border:0;border-radius:999px;padding:10px 16px;",
    "font:500 13px/1.4 'Noto Sans JP',system-ui,sans-serif;cursor:pointer;",
    "box-shadow:0 4px 14px rgba(0,0,0,.18)}",
    ".am-fb-fab:hover{background:#111827}",
    ".am-fb-fab:focus-visible{outline:2px solid #6366f1;outline-offset:2px}",
    ".am-fb-backdrop{position:fixed;inset:0;background:rgba(17,24,39,.48);",
    "z-index:2147483001;display:flex;align-items:center;justify-content:center;padding:16px}",
    ".am-fb-dialog{background:#fff;color:#111827;border-radius:10px;max-width:460px;width:100%;",
    "box-shadow:0 16px 48px rgba(0,0,0,.25);font:400 14px/1.5 'Noto Sans JP',system-ui,sans-serif}",
    ".am-fb-hd{padding:16px 20px;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between}",
    ".am-fb-hd h2{margin:0;font-size:15px;font-weight:700}",
    ".am-fb-x{background:transparent;border:0;font-size:20px;line-height:1;cursor:pointer;color:#6b7280;padding:4px 8px}",
    ".am-fb-x:hover{color:#111827}",
    ".am-fb-bd{padding:16px 20px;display:grid;gap:12px}",
    ".am-fb-lbl{font-size:12px;font-weight:600;color:#374151;margin:0 0 4px}",
    ".am-fb-bd select,.am-fb-bd input,.am-fb-bd textarea{",
    "width:100%;box-sizing:border-box;border:1px solid #d1d5db;border-radius:6px;",
    "padding:8px 10px;font:inherit;color:#111827;background:#fff}",
    ".am-fb-bd textarea{min-height:120px;resize:vertical}",
    ".am-fb-bd select:focus,.am-fb-bd input:focus,.am-fb-bd textarea:focus{",
    "outline:0;border-color:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.18)}",
    ".am-fb-count{font-size:11px;color:#6b7280;text-align:right;margin:2px 0 0}",
    ".am-fb-ft{padding:12px 20px 16px;display:flex;justify-content:flex-end;gap:8px;border-top:1px solid #e5e7eb}",
    ".am-fb-btn{border:0;border-radius:6px;padding:8px 14px;font:500 13px 'Noto Sans JP',system-ui,sans-serif;cursor:pointer}",
    ".am-fb-btn[disabled]{opacity:.55;cursor:not-allowed}",
    ".am-fb-btn-p{background:#4f46e5;color:#fff}",
    ".am-fb-btn-p:hover:not([disabled]){background:#4338ca}",
    ".am-fb-btn-s{background:#f3f4f6;color:#374151}",
    ".am-fb-btn-s:hover{background:#e5e7eb}",
    ".am-fb-msg{padding:10px 20px;font-size:13px;border-top:1px solid #e5e7eb}",
    ".am-fb-err{color:#b91c1c;background:#fef2f2}",
    ".am-fb-ok{color:#047857;background:#ecfdf5}",
    ".am-fb-kbd{font-size:11px;color:#6b7280;margin:0;padding:0 20px 10px}",
    "@media (prefers-color-scheme:dark){",
    ".am-fb-dialog{background:#1f2937;color:#f3f4f6}",
    ".am-fb-hd,.am-fb-ft,.am-fb-msg{border-color:#374151}",
    ".am-fb-hd h2{color:#f3f4f6}",
    ".am-fb-lbl{color:#d1d5db}",
    ".am-fb-bd select,.am-fb-bd input,.am-fb-bd textarea{background:#111827;color:#f3f4f6;border-color:#374151}",
    ".am-fb-btn-s{background:#374151;color:#f3f4f6}",
    ".am-fb-btn-s:hover{background:#4b5563}",
    ".am-fb-count,.am-fb-kbd{color:#9ca3af}",
    ".am-fb-err{background:#450a0a;color:#fecaca}",
    ".am-fb-ok{background:#064e3b;color:#a7f3d0}",
    "}"
  ].join("");

  function injectCss() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
        if (k === "text") el.textContent = attrs[k];
        else if (k === "html") el.innerHTML = attrs[k];
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
        else el.setAttribute(k, attrs[k]);
      }
    }
    if (children) {
      for (var i = 0; i < children.length; i++) {
        if (children[i] != null) el.appendChild(children[i]);
      }
    }
    return el;
  }

  var CATEGORIES = [
    ["bug", "バグ / 不具合"],
    ["data_error", "データの誤り"],
    ["feature_request", "機能リクエスト"],
    ["pricing", "料金・課金"],
    ["other", "その他"]
  ];

  function buildDialog(state) {
    var txt = h("textarea", {
      id: "am-fb-text",
      maxlength: "2000",
      placeholder: "ご意見・不具合・ご要望を自由にどうぞ",
      required: "required",
      oninput: function () {
        count.textContent = txt.value.length + " / 2000";
      }
    });
    var count = h("p", { class: "am-fb-count", text: "0 / 2000" });

    var catOpts = CATEGORIES.map(function (c) {
      return h("option", { value: c[0], text: c[1] });
    });
    var cat = h("select", { id: "am-fb-cat" }, catOpts);
    cat.value = "other";

    var email = h("input", {
      id: "am-fb-email",
      type: "email",
      placeholder: "you@example.com",
      autocomplete: "email"
    });
    try {
      var saved = window.localStorage.getItem("AutonoMathEmail");
      if (saved) email.value = saved;
    } catch (_) {}

    var msgBox = h("div", { id: "am-fb-msg", style: "display:none" });

    var cancel = h("button", {
      type: "button",
      class: "am-fb-btn am-fb-btn-s",
      text: "キャンセル",
      onclick: function () {
        state.close();
      }
    });
    var submit = h("button", {
      type: "submit",
      class: "am-fb-btn am-fb-btn-p",
      text: "送信"
    });

    var body = h("div", { class: "am-fb-bd" }, [
      h("div", null, [
        h("label", { class: "am-fb-lbl", for: "am-fb-cat", text: "カテゴリ" }),
        cat
      ]),
      h("div", null, [
        h("label", { class: "am-fb-lbl", for: "am-fb-text", text: "内容" }),
        txt,
        count
      ]),
      h("div", null, [
        h("label", {
          class: "am-fb-lbl",
          for: "am-fb-email",
          text: "メール (任意 — 返信が必要な場合のみ)"
        }),
        email
      ])
    ]);

    var form = h(
      "form",
      {
        class: "am-fb-dialog",
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "am-fb-title",
        onsubmit: function (e) {
          e.preventDefault();
          state.send(txt, cat, email, msgBox, submit);
        }
      },
      [
        h("div", { class: "am-fb-hd" }, [
          h("h2", { id: "am-fb-title", text: "フィードバックを送信" }),
          h("button", {
            type: "button",
            class: "am-fb-x",
            "aria-label": "閉じる",
            text: "×",
            onclick: function () {
              state.close();
            }
          })
        ]),
        body,
        msgBox,
        h("p", { class: "am-fb-kbd", text: "Ctrl+Enter で送信 / Esc で閉じる" }),
        h("div", { class: "am-fb-ft" }, [cancel, submit])
      ]
    );

    // Ctrl+Enter submit handler on textarea
    txt.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        if (!submit.disabled) form.requestSubmit();
      }
    });

    return { form: form, textarea: txt };
  }

  function open(opts) {
    if (document.getElementById("am-fb-root")) return;

    var root = h("div", {
      id: "am-fb-root",
      class: "am-fb-backdrop",
      onclick: function (e) {
        if (e.target === root) close();
      }
    });

    function close() {
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener("keydown", onKey);
    }

    function onKey(e) {
      if (e.key === "Escape") close();
    }

    function send(txt, cat, email, msgBox, submit) {
      var text = txt.value.trim();
      if (!text) {
        showMsg(msgBox, "内容を入力してください。", true);
        return;
      }
      // Persist email locally for next time.
      try {
        if (email.value) {
          window.localStorage.setItem("AutonoMathEmail", email.value.trim());
        }
      } catch (_) {}

      // Backend only accepts message/rating/endpoint/request_id. Fold extras
      // into the message prefix so they land in DB without contract change.
      var prefix =
        "[category=" + cat.value + "]" +
        (email.value ? " [email=" + email.value.trim() + "]" : "") +
        " [ua=" + (navigator.userAgent || "").slice(0, 120) + "]" +
        (document.referrer ? " [ref=" + document.referrer.slice(0, 200) + "]" : "") +
        "\n";
      var body = {
        message: (prefix + text).slice(0, 4000),
        endpoint: (location.href || "").slice(0, 256)
      };

      submit.disabled = true;
      submit.textContent = "送信中…";
      fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      })
        .then(function (r) {
          if (r.ok) {
            showMsg(msgBox, "ありがとうございます。", false);
            setTimeout(close, 2000);
            return;
          }
          return r.text().then(function (t) {
            var m = "送信に失敗しました (HTTP " + r.status + ")";
            if (r.status === 429) m = "本日の送信上限に達しました。明日以降に再度お試しください。";
            else if (t) m += ": " + t.slice(0, 200);
            showMsg(msgBox, m, true);
            submit.disabled = false;
            submit.textContent = "送信";
          });
        })
        .catch(function (err) {
          showMsg(msgBox, "ネットワークエラー: " + (err && err.message ? err.message : err), true);
          submit.disabled = false;
          submit.textContent = "送信";
        });
    }

    var state = { close: close, send: send };
    var built = buildDialog(state);
    root.appendChild(built.form);
    document.body.appendChild(root);
    document.addEventListener("keydown", onKey);
    setTimeout(function () {
      built.textarea.focus();
    }, 40);
  }

  function showMsg(el, text, isErr) {
    el.textContent = text;
    el.className = "am-fb-msg " + (isErr ? "am-fb-err" : "am-fb-ok");
    el.style.display = "block";
  }

  function mount(containerSelector, opts) {
    opts = opts || {};
    injectCss();

    var onClick = function () {
      open(opts);
    };

    var container = null;
    if (containerSelector && containerSelector !== "body") {
      container = document.querySelector(containerSelector);
    }

    if (container) {
      // Inline button (caller provided a slot).
      var inline = h("button", {
        type: "button",
        class: "am-fb-fab",
        style: "position:static;box-shadow:none",
        text: "フィードバック",
        onclick: onClick
      });
      container.appendChild(inline);
    } else {
      // Floating FAB on body.
      if (document.getElementById("am-fb-fab")) return;
      var fab = h("button", {
        id: "am-fb-fab",
        type: "button",
        class: "am-fb-fab",
        "aria-label": "フィードバックを送信",
        text: "フィードバック",
        onclick: onClick
      });
      document.body.appendChild(fab);
    }
  }

  window.AutonoMathFeedback = { mount: mount, open: function () { open({}); } };
})();
