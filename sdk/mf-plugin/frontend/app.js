// 税務会計AI — MF Cloud iframe popup UI
// 同 origin の /mf-plugin/* に POST するだけ。token は server-side session にあり、
// この script は token に触れない。

(function () {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---- tabs --------------------------------------------------------------
  $$('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.tab;
      $$('.tab').forEach((b) => b.classList.toggle('is-active', b === btn));
      $$('.panel').forEach((p) =>
        p.classList.toggle('is-active', p.dataset.panel === id),
      );
    });
  });

  // ---- /mf-plugin/me で tenant 表示 -------------------------------------
  fetch('/mf-plugin/me', { credentials: 'same-origin' })
    .then((r) => r.json())
    .then((j) => {
      const el = $('#tenant-display');
      if (j.authed) {
        el.textContent = j.tenant_name
          ? `事業者: ${j.tenant_name}`
          : '認証済み (事業者名取得中)';
      } else {
        el.innerHTML = '<a href="/oauth/authorize">MF と連携する</a>';
      }
    })
    .catch(() => {
      $('#tenant-display').textContent = '認証状態の取得に失敗しました';
    });

  // ---- form 配線 ---------------------------------------------------------
  const ENDPOINTS = {
    subsidy: '/mf-plugin/search-subsidies',
    tax: '/mf-plugin/search-tax-incentives',
    invoice: '/mf-plugin/check-invoice-registrant',
    laws: '/mf-plugin/search-laws',
    court: '/mf-plugin/search-court-decisions',
  };

  $$('form[data-form]').forEach((form) => {
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const tab = form.dataset.form;
      const out = $(`[data-results="${tab}"]`);
      out.innerHTML = '<div class="r-empty">検索中...</div>';

      const fd = new FormData(form);
      const body = {};
      fd.forEach((v, k) => {
        if (typeof v === 'string' && v.trim()) body[k] = v.trim();
      });

      try {
        const resp = await fetch(ENDPOINTS[tab], {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok) {
          out.innerHTML = `<div class="r-error">エラー: ${escape(data.detail || resp.status)}</div>`;
          return;
        }
        renderResults(out, tab, data);
      } catch (err) {
        out.innerHTML = `<div class="r-error">通信エラー: ${escape(String(err))}</div>`;
      }
    });
  });

  function escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[c]);
  }

  function renderResults(out, tab, data) {
    const items = data.items || data.results || data.data || (Array.isArray(data) ? data : []);
    if (tab === 'invoice') {
      // 単票
      const item = data.registrant || data;
      if (!item || !item.registration_number) {
        out.innerHTML = '<div class="r-empty">該当する登録番号は見つかりませんでした。</div>';
        return;
      }
      out.innerHTML = `
        <div class="r-item">
          <h3>${escape(item.name || '(名称未取得)')}</h3>
          <div class="r-meta">登録番号: ${escape(item.registration_number)} / ${escape(item.kind || '')}</div>
          <div class="r-source"><a href="${escape(item.source_url || '#')}" target="_blank" rel="noopener">国税庁 公表情報を開く</a></div>
        </div>`;
      return;
    }
    if (!items.length) {
      out.innerHTML = '<div class="r-empty">該当する結果はありませんでした。</div>';
      return;
    }
    out.innerHTML = items.slice(0, 5).map((it) => {
      const title = escape(it.title || it.name || it.law_name || it.case_title || '(無題)');
      const meta = [it.tier, it.prefecture, it.deadline, it.law_no, it.court]
        .filter(Boolean).map(escape).join(' / ');
      const src = it.source_url || it.url;
      return `
        <div class="r-item">
          <h3>${title}</h3>
          <div class="r-meta">${meta}</div>
          ${src ? `<div class="r-source"><a href="${escape(src)}" target="_blank" rel="noopener">出典を開く</a></div>` : ''}
        </div>`;
    }).join('');
  }
})();
