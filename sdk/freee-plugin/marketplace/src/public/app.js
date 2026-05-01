// Vanilla-JS popup. No build step, no React, runs as a module-less <script>.
// Intentionally tiny so freee's iframe boots fast on slow connections.

(function () {
  'use strict';

  // --- tabs --------------------------------------------------------------
  const tabs = document.querySelectorAll('.tab');
  const panels = {
    subsidy: document.getElementById('panel-subsidy'),
    tax: document.getElementById('panel-tax'),
    invoice: document.getElementById('panel-invoice'),
  };
  tabs.forEach((t) =>
    t.addEventListener('click', () => {
      tabs.forEach((x) => x.classList.remove('active'));
      t.classList.add('active');
      Object.values(panels).forEach((p) => (p.hidden = true));
      panels[t.dataset.tab].hidden = false;
    }),
  );

  // --- forms -------------------------------------------------------------
  bindSearch('form-subsidy', '/freee-plugin/search-subsidies', 'results-subsidy', renderSubsidy);
  bindSearch('form-tax', '/freee-plugin/search-tax-incentives', 'results-tax', renderTax);
  bindSearch('form-invoice', '/freee-plugin/check-invoice-registrant', 'results-invoice', renderInvoice);

  function bindSearch(formId, endpoint, resultsId, renderer) {
    const form = document.getElementById(formId);
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const params = new URLSearchParams();
      fd.forEach((v, k) => {
        if (typeof v === 'string' && v.trim()) params.set(k, v.trim());
      });
      const list = document.getElementById(resultsId);
      list.innerHTML = '<li class="empty">検索中…</li>';
      const btn = form.querySelector('.btn');
      btn.disabled = true;
      try {
        const resp = await fetch(`${endpoint}?${params.toString()}`, {
          headers: { accept: 'application/json' },
          credentials: 'same-origin',
        });
        if (resp.status === 401) {
          list.innerHTML =
            '<li class="err">freee 連携が切れました。再ログインしてください。<br><a href="/oauth/authorize">再ログイン</a></li>';
          return;
        }
        const body = await resp.json();
        if (!resp.ok) {
          list.innerHTML = `<li class="err">エラー: ${escape(body?.error || resp.status)}</li>`;
          return;
        }
        renderCompanyPill(body?._company_context);
        const items = body?.items || body?.results || [];
        if (!items.length) {
          list.innerHTML = '<li class="empty">該当するデータが見つかりませんでした。</li>';
          return;
        }
        list.innerHTML = items.slice(0, 5).map(renderer).join('');
      } catch (err) {
        list.innerHTML = `<li class="err">通信エラー: ${escape(String(err?.message || err))}</li>`;
      } finally {
        btn.disabled = false;
      }
    });
  }

  // --- renderers ---------------------------------------------------------
  function renderSubsidy(p) {
    const tier = p.tier || '';
    const url = p.source_url || `https://jpcite.com/programs/${encodeURIComponent(p.unified_id || p.id || '')}`;
    return `<li>
      <div class="title">${escape(p.primary_name || p.title || p.name || '(無題)')}</div>
      <div class="meta">
        ${tier ? `<span class="tier ${tier}">Tier ${escape(tier)}</span>` : ''}
        ${p.authority ? `<span>${escape(p.authority)}</span>` : ''}
        ${p.prefecture ? `<span>${escape(p.prefecture)}</span>` : ''}
      </div>
      <div class="deep">
        <a href="${escape(url)}" target="_blank" rel="noopener">出典を確認</a>
        ${p.unified_id ? ` · <a href="https://jpcite.com/programs/${encodeURIComponent(p.unified_id)}" target="_blank" rel="noopener">jpciteで詳細</a>` : ''}
      </div>
    </li>`;
  }

  function renderTax(t) {
    const url = t.source_url || `https://jpcite.com/tax/${encodeURIComponent(t.measure_id || t.id || '')}`;
    return `<li>
      <div class="title">${escape(t.measure_name || t.title || t.name || '(無題)')}</div>
      <div class="meta">
        ${t.law_name ? `<span>${escape(t.law_name)}</span>` : ''}
        ${t.applicable_period ? `<span>${escape(t.applicable_period)}</span>` : ''}
      </div>
      <div class="deep">
        <a href="${escape(url)}" target="_blank" rel="noopener">条文・告示を確認</a>
      </div>
    </li>`;
  }

  function renderInvoice(r) {
    const status = r.kind === 'active' || r.is_active ? '有効' : (r.kind || r.status || '失効');
    return `<li>
      <div class="title">${escape(r.name || r.normalized_name || r.registered_name || '(名称不明)')}</div>
      <div class="meta">
        <span>登録番号: ${escape(r.registration_number || r.t_number || '-')}</span>
        <span>${escape(status)}</span>
        ${r.address ? `<span>${escape(r.address)}</span>` : ''}
      </div>
      <div class="deep">
        <a href="https://www.invoice-kohyo.nta.go.jp/regno-search/simple?selRegNo=${encodeURIComponent((r.registration_number || '').replace(/^T/, ''))}" target="_blank" rel="noopener">国税庁公表サイトで確認</a>
      </div>
    </li>`;
  }

  // --- helpers -----------------------------------------------------------
  function renderCompanyPill(ctx) {
    if (!ctx?.company_name) return;
    const pill = document.getElementById('company-pill');
    pill.hidden = false;
    pill.textContent = ctx.company_name;
  }

  function escape(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
    );
  }
})();
