(()=>{'use strict';const API_BASE=(typeof window!=='undefined'&&window.JPCITE_API_BASE)||(typeof window!=='undefined'&&window.location&&window.location.hostname==='jpcite.com'?'https://api.jpcite.com':'');const api=(p)=>API_BASE.replace(/\/$/,'')+p;const KEY_NAME='am_api_key';const $=(sel,root=document)=>root.querySelector(sel);const escapeHtml=(s)=>String(s).replace(/[&<>"']/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let storageMode='localStorage';const memStore=Object.create(null);const store={get(){try{const v=localStorage.getItem(KEY_NAME);if(v){storageMode='localStorage';return v;}}catch(_){}
try{const v=sessionStorage.getItem(KEY_NAME);if(v){storageMode='sessionStorage';return v;}}catch(_){}
if(memStore[KEY_NAME]){storageMode='memory';return memStore[KEY_NAME];}
	return'';},set(v){try{localStorage.setItem(KEY_NAME,v);storageMode='localStorage';return;}catch(_){}
try{sessionStorage.setItem(KEY_NAME,v);storageMode='sessionStorage';return;}catch(_){}
memStore[KEY_NAME]=v;storageMode='memory';},clear(){try{localStorage.removeItem(KEY_NAME);}catch(_){}
	try{sessionStorage.removeItem(KEY_NAME);}catch(_){}
	delete memStore[KEY_NAME];},mode(){return storageMode;},};function authHeader(){const k=store.get();return k?{'X-API-Key':k}:{};}
function _readCookie(name){if(typeof document==='undefined'||!document.cookie)return'';const parts=document.cookie.split(';');for(let i=0;i<parts.length;i++){const seg=parts[i].trim();if(!seg)continue;const eq=seg.indexOf('=');const k=eq<0?seg:seg.slice(0,eq);if(k===name){return eq<0?'':decodeURIComponent(seg.slice(eq+1));}}
return'';}
function csrfHeaders(){const tok=_readCookie('am_csrf');return tok?{'X-CSRF-Token':tok}:{};}
async function fetchJSON(path,opts={}){const init=Object.assign({},opts);init.headers=Object.assign({'Accept':'application/json'},authHeader(),opts.body?{'Content-Type':'application/json'}:{},opts.headers||{});let _timer=null;if(!init.signal){const ctrl=new AbortController();init.signal=ctrl.signal;_timer=setTimeout(()=>ctrl.abort(),opts.timeoutMs||15000);}
let resp;try{resp=await fetch(api(path),init);}catch(err){if(err&&err.name==='AbortError'){const e=new Error('タイムアウト — 回線が遅いか、サーバが応答していません。');e.status=0;e.timeout=true;throw e;}
throw err;}finally{if(_timer)clearTimeout(_timer);}
let body=null;const text=await resp.text();if(text){try{body=JSON.parse(text);}catch{body=null;}}
if(!resp.ok){const detail=(body&&(body.detail||body.message))||`HTTP ${resp.status}`;const err=new Error(detail);err.status=resp.status;err.body=body;throw err;}
return body;}
function setStatus(msg,isError=false){const el=$('#dash2-key-status');if(!el)return;el.textContent=msg||'';el.style.color=isError?'var(--danger)':'var(--text-muted)';}
function renderStorageWarning(){const status=$('#dash2-key-status');if(!status)return;let warn=document.getElementById('dash2-key-storage-warning');const mode=store.mode();let msg='';if(mode==='sessionStorage'){msg='プライベートブラウジングで API キーは現在のタブのみ保持されます。';}else if(mode==='memory'){msg='ブラウザ保存が無効のため、API キーはこのページを離れると失われます。';}
if(!msg){if(warn)warn.remove();return;}
if(!warn){warn=document.createElement('p');warn.id='dash2-key-storage-warning';warn.className='stat-note';warn.style.cssText='margin:6px 0 0;color:var(--danger);';warn.setAttribute('role','status');status.parentNode.insertBefore(warn,status.nextSibling);}
warn.textContent=msg;}
const SECTIONS=['dash2-summary','dash2-tool-usage','dash2-billing-history','dash2-recommend','dash2-alerts',];function showSections(on){SECTIONS.forEach((id)=>{const el=document.getElementById(id);if(!el)return;if(on){el.removeAttribute('hidden');el.style.display='';}else{el.style.display='none';}});}
function detachFromLegacyHide(){if(!Array.isArray(window.__dashPostEls))return;const ids=new Set(SECTIONS);window.__dashPostEls=window.__dashPostEls.filter((el)=>(!el||!el.id||!ids.has(el.id)));}
const V2_DUNNING_COPY=Object.freeze({past_due:'💳 直近のお支払いに失敗しました。Stripe ポータルから支払い方法を更新してください。',unpaid:'⚠️ お支払い未確定です。サービス停止前に Stripe ポータルからご確認ください。',incomplete:'⚠️ お支払い未確定です。サービス停止前に Stripe ポータルからご確認ください。',canceled:'ℹ️ サブスクリプションはキャンセル済みです。当月末まで API アクセス可能です。',});function renderV2Dunning(data){const banner=document.getElementById('dash-dunning-banner');if(!banner)return;const status=data&&typeof data.subscription_status==='string'?data.subscription_status.toLowerCase():null;const msg=status&&V2_DUNNING_COPY[status];if(!msg){banner.hidden=true;banner.style.display='none';return;}
const msgEl=document.getElementById('dash-dunning-msg');if(msgEl)msgEl.textContent=msg;const portalLink=document.getElementById('dash-dunning-portal');if(portalLink&&!portalLink.dataset.v2Bound){portalLink.dataset.v2Bound='1';portalLink.addEventListener('click',async(e)=>{e.preventDefault();try{const body=await fetchJSON('/v1/me/billing-portal',{method:'POST',headers:csrfHeaders()});if(body&&body.url)window.location=body.url;}catch(err){setStatus(err.message||'Stripe ポータル URL を取得できませんでした。',true);}});}
banner.hidden=false;banner.style.display='block';}
function renderV2PeriodEnd(data){const wrap=document.getElementById('dash-period-end');if(!wrap)return;const iso=data&&typeof data.current_period_end==='string'?data.current_period_end:null;if(!iso){const dateEl=document.getElementById('dash-period-end-date');const existing=dateEl&&dateEl.textContent&&dateEl.textContent!=='—';if(!existing){wrap.hidden=true;wrap.style.display='none';}
return;}
const date=String(iso).slice(0,10);if(!/^\d{4}-\d{2}-\d{2}$/.test(date))return;const dateEl=document.getElementById('dash-period-end-date');if(dateEl)dateEl.textContent=date;wrap.hidden=false;wrap.style.display='';}
async function loadSummary(){const data=await fetchJSON('/v1/me/dashboard?days=30');renderV2Dunning(data);renderV2PeriodEnd(data);const headline=$('#dash2-summary-headline');if(headline){headline.innerHTML=`${data.last_30_calls.toLocaleString()} <span class="unit">calls / </span>`+`¥${data.last_30_amount_yen.toLocaleString()}<span class="unit"> spent (30d)</span>`;}
const fill=$('#dash2-cap-fill');if(fill){if(data.monthly_cap_yen&&data.monthly_cap_yen>0){const pct=Math.min(100,Math.round((data.month_to_date_amount_yen/data.monthly_cap_yen)*100));fill.style.width=pct+'%';}else{fill.style.width='0%';}}
const note=$('#dash2-summary-note');if(note){const cap=data.monthly_cap_yen;const mtd=data.month_to_date_amount_yen;if(cap&&cap>0){const remain=data.cap_remaining_yen!=null?data.cap_remaining_yen:Math.max(0,cap-mtd);note.textContent=`今月: ¥${mtd.toLocaleString()} / ¥${cap.toLocaleString()} (残 ¥${remain.toLocaleString()})。`+`単価 ¥${data.unit_price_yen}/req 税別。リセット: 翌月 1 日 00:00 JST。`;}else{note.textContent=`今月: ¥${mtd.toLocaleString()}。月次予算 cap 未設定の場合は利用量に応じて課金されます。`;}}
const capInput=$('#dash2-cap-input');if(capInput&&data.monthly_cap_yen!=null){capInput.value=String(data.monthly_cap_yen);}
renderSparkline(data.series||[]);}
function renderSparkline(series){const svg=$('#dash2-spark');if(!svg)return;const w=300,h=60;const n=series.length;if(n===0){svg.innerHTML='';return;}
const gap=2;const barW=Math.max(1,Math.floor((w-gap*(n-1))/n));const maxV=Math.max(1,...series.map((d)=>d.calls||0));const baseY=h-4;const maxBarH=h-8;const rects=series.map((d,i)=>{const v=d.calls||0;const bh=maxV>0?Math.round((v/maxV)*maxBarH):0;const x=i*(barW+gap);const y=baseY-bh;return`<rect x="${x}" y="${y}" width="${barW}" height="${bh}" fill="#1e3a8a"><title>${escapeHtml(d.date)}: ${v} calls</title></rect>`;}).join('');svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.innerHTML=rects;}
async function loadToolUsage(){const data=await fetchJSON('/v1/me/usage_by_tool?days=30&limit=10');const tbody=$('#dash2-tool-tbody');if(!tbody)return;if(!data.top||data.top.length===0){tbody.innerHTML=`<tr><td colspan="4" style="padding:14px 4px;color:var(--text-muted);">利用履歴なし — まずは <a href="/docs/">Docs</a> から API を叩いてみてください。</td></tr>`;return;}
tbody.innerHTML=data.top.map((row)=>`
      <tr style="border-bottom:1px solid var(--border);">
        <td style="padding:8px 4px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;">${escapeHtml(row.endpoint)}</td>
        <td style="padding:8px 4px;text-align:right;">${row.calls.toLocaleString()}</td>
        <td style="padding:8px 4px;text-align:right;">¥${row.amount_yen.toLocaleString()}</td>
        <td style="padding:8px 4px;text-align:right;color:var(--text-muted);">${row.avg_latency_ms != null ? row.avg_latency_ms + ' ms' : '—'}</td>
      </tr>
    `).join('');}
let _lastInvoices=[];async function loadBillingHistory(){const data=await fetchJSON('/v1/me/billing_history');_lastInvoices=data.invoices||[];const tbody=$('#dash2-billing-tbody');const note=$('#dash2-billing-note');if(!tbody)return;if(_lastInvoices.length===0){tbody.innerHTML=`<tr><td colspan="4" style="padding:14px 4px;color:var(--text-muted);">請求書はまだありません — 翌月 1 日に Stripe から発行されます。</td></tr>`;if(note)note.textContent='Stripe Customer Portal と同期 (5 分キャッシュ)。請求書はまだありません。';return;}
tbody.innerHTML=_lastInvoices.map((inv)=>`
      <tr style="border-bottom:1px solid var(--border);">
        <td style="padding:8px 4px;">${escapeHtml(inv.period_start || '—')} 〜 ${escapeHtml(inv.period_end || '—')}</td>
        <td style="padding:8px 4px;">${escapeHtml(inv.status)}</td>
        <td style="padding:8px 4px;text-align:right;">¥${(inv.amount_paid_yen || 0).toLocaleString()}</td>
        <td style="padding:8px 4px;">${inv.hosted_invoice_url ? `<a href="${escapeHtml(inv.hosted_invoice_url)}"target="_blank"rel="noopener">View</a>` : '—'}${inv.invoice_pdf ? `·<a href="${escapeHtml(inv.invoice_pdf)}"target="_blank"rel="noopener">PDF</a>` : ''}</td>
      </tr>
    `).join('');if(note)note.textContent=`${_lastInvoices.length} 件 (5 分キャッシュ、cached_at: ${escapeHtml(data.cached_at || '—')})。`;}
function downloadInvoices(format){if(_lastInvoices.length===0){setStatus('請求書はまだありません。月次サイクルで Stripe から発行されます。',true);return;}
let body,mime,ext;if(format==='csv'){const cols=['id','number','period_start','period_end','amount_due_yen','amount_paid_yen','currency','status','hosted_invoice_url','created'];const escape=(v)=>{if(v==null)return'';const s=String(v);return/[",\n]/.test(s)?`"${s.replace(/"/g, '""')}"`:s;};body=cols.join(',')+'\n'+_lastInvoices.map((inv)=>cols.map((c)=>escape(inv[c])).join(',')).join('\n');mime='text/csv;charset=utf-8';ext='csv';}else{body=JSON.stringify(_lastInvoices,null,2);mime='application/json;charset=utf-8';ext='json';}
const blob=new Blob([body],{type:mime});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`jpcite-billing-${new Date().toISOString().slice(0, 10)}.${ext}`;document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(url);}
async function recommendTool(intent){const data=await fetchJSON(`/v1/me/tool_recommendation?intent=${encodeURIComponent(intent)}&limit=5`);const ol=$('#dash2-rec-list');if(!ol)return;if(!data.tools||data.tools.length===0){ol.innerHTML=`<li>マッチするツールがありませんでした。</li>`;return;}
const fb=data.fallback_used?'<p class="stat-note" style="margin:0 0 8px;color:var(--text-muted);">(キーワードで一致なし → 汎用候補にフォールバック)</p>':'';ol.innerHTML=fb+data.tools.map((t)=>`
      <li style="margin-bottom:8px;">
        <code>${escapeHtml(t.endpoint)}</code> — ${escapeHtml(t.name)}
        <span class="stat-note" style="color:var(--text-muted);">(信頼度 ${(t.confidence * 100).toFixed(0)}%)</span>
        <br><span class="stat-note">${escapeHtml(t.why)}</span>
      </li>
    `).join('');}
async function saveCap(yenOrNull){return fetchJSON('/v1/me/cap',{method:'POST',headers:{'X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({monthly_cap_yen:yenOrNull}),});}
const _RE_INTERNAL_IPV4=new RegExp('^(?:'+'127(?:\\.\\d{1,3}){3}'+'|10(?:\\.\\d{1,3}){3}'+'|192\\.168(?:\\.\\d{1,3}){2}'+'|172\\.(?:1[6-9]|2\\d|3[01])(?:\\.\\d{1,3}){2}'+'|169\\.254(?:\\.\\d{1,3}){2}'+'|0(?:\\.\\d{1,3}){3}'+')$');const _RE_INTERNAL_IPV6=/^(?:::1|fe80:|fc[0-9a-f]{2}:|fd[0-9a-f]{2}:)/i;function _isInternalHost(host){if(!host)return true;const h=host.replace(/^\[|\]$/g,'').toLowerCase();if(_RE_INTERNAL_IPV4.test(h))return true;if(_RE_INTERNAL_IPV6.test(h))return true;if(h==='localhost')return true;return false;}
function validateWebhookUrl(url){if(!url)return null;if(url.length>2048)return'webhook_url が長すぎます (2048 文字以内)';let parsed;try{parsed=new URL(url);}
catch{return'webhook_url が URL として不正です';}
if(parsed.protocol!=='https:')return'webhook_url は https:// で始まる必要があります';if(!parsed.hostname)return'webhook_url にホスト名が必要です';if(_isInternalHost(parsed.hostname))return'webhook_url が internal/loopback IP を指しています';return null;}
function showAlertBanner(msg,isError){const el=$('#dash2-alerts-banner');if(!el)return;el.textContent=msg;el.style.display=msg?'':'none';if(isError){el.style.background='#fff0f0';el.style.color='var(--danger)';el.style.borderColor='var(--danger)';}else{el.style.background='#f0f9ff';el.style.color='var(--text)';el.style.borderColor='var(--border)';}
if(!isError&&msg){setTimeout(()=>{if(el.textContent===msg){el.style.display='none';}},4000);}}
async function loadAlerts(){const data=await fetchJSON('/v1/me/alerts/subscriptions');const tbody=$('#dash2-alerts-tbody');if(!tbody)return;const rows=Array.isArray(data)?data:(data&&data.subscriptions)||[];if(rows.length===0){tbody.innerHTML='<tr><td colspan="7" style="padding:14px 4px;color:var(--text-muted);">'+'登録中の subscription はありません。下記フォームから新規登録してください。'+'</td></tr>';return;}
tbody.innerHTML=rows.map((sub)=>`
      <tr style="border-bottom:1px solid var(--border);" data-sub-id="${escapeHtml(String(sub.id))}">
        <td style="padding:8px 4px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">${escapeHtml(String(sub.id))}</td>
        <td style="padding:8px 4px;">${escapeHtml(sub.filter_type || '')}</td>
        <td style="padding:8px 4px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;">${escapeHtml(sub.filter_value || '—')}</td>
        <td style="padding:8px 4px;">${escapeHtml(sub.min_severity || '')}</td>
        <td style="padding:8px 4px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--text-muted);">${sub.webhook_url ? escapeHtml(sub.webhook_url) : '—'}</td>
        <td style="padding:8px 4px;color:var(--text-muted);">${sub.email ? escapeHtml(sub.email) : '—'}</td>
        <td style="padding:8px 4px;text-align:right;">
          <button type="button" class="btn-danger dash2-alerts-delete"
                  data-sub-id="${escapeHtml(String(sub.id))}"
                  style="padding:4px 10px;font-size:12px;">削除</button>
        </td>
      </tr>
    `).join('');}
async function subscribeAlert(formData){return fetchJSON('/v1/me/alerts/subscribe',{method:'POST',headers:{'X-Requested-With':'XMLHttpRequest'},body:JSON.stringify(formData),});}
async function deleteAlert(id){return fetchJSON(`/v1/me/alerts/subscriptions/${encodeURIComponent(id)}`,{method:'DELETE',headers:{'X-Requested-With':'XMLHttpRequest'},});}
function yieldToMain(){return new Promise((r)=>setTimeout(r,0));}
async function loadAll(){if(!store.get()){showSections(false);setStatus('API key 未保存 — 上記フォームから貼り付けてください。');return;}
setStatus('読み込み中…');showSections(true);try{await loadSummary();await yieldToMain();await loadToolUsage();await yieldToMain();await loadBillingHistory();await yieldToMain();try{await loadAlerts();}catch(e){if(e.status!==401){const tbody=document.getElementById('dash2-alerts-tbody');if(tbody){tbody.innerHTML='<tr><td colspan="7" style="padding:14px 4px;color:var(--danger);">'+'subscription 一覧取得に失敗: '+escapeHtml(e.message||String(e))+'</td></tr>';}}else{throw e;}}
setStatus('読み込み完了。');}catch(e){if(e.status===401){store.clear();showSections(false);setStatus('API key が無効でした。再度入力してください。',true);}else{setStatus(`エラー: ${e.message || e}`,true);}}}
	function bind(){const form=$('#dash2-key-form');if(form){form.addEventListener('submit',(e)=>{e.preventDefault();const inp=$('#dash2-key-input');const v=(inp&&inp.value||'').trim();if(!v)return;store.set(v);if(inp)inp.value='';renderStorageWarning();try{if(typeof window.jpciteTrack==='function'){window.jpciteTrack('dashboard_signin_success',{mode:'x_api_key_localstorage',});}}catch(_e){}
loadAll();});}
const clearBtn=$('#dash2-key-clear');if(clearBtn){clearBtn.addEventListener('click',()=>{store.clear();showSections(false);setStatus('API key を削除しました。');const warn=document.getElementById('dash2-key-storage-warning');if(warn)warn.remove();});}
const recForm=$('#dash2-rec-form');if(recForm){recForm.addEventListener('submit',async(e)=>{e.preventDefault();const intent=($('#dash2-rec-intent')||{}).value||'';if(!intent.trim())return;try{await recommendTool(intent.trim());}
catch(err){if(err.status===401){setStatus('API key が無効です。',true);}else{const ol=$('#dash2-rec-list');if(ol)ol.innerHTML=`<li style="color:var(--danger);">エラー: ${escapeHtml(err.message || String(err))}</li>`;}}});}
const capSave=$('#dash2-cap-save');if(capSave){capSave.addEventListener('click',async()=>{const v=($('#dash2-cap-input')||{}).value;const num=v?parseInt(v,10):null;if(num!=null&&(Number.isNaN(num)||num<0)){setStatus('上限は 0 以上の整数で指定してください (¥)。',true);return;}
try{await saveCap(num);setStatus(num!=null?`Cap saved: ¥${num.toLocaleString()}`:'Cap removed.');await loadSummary();}catch(e){setStatus(`Cap save failed: ${e.message || e}`,true);}});}
const capClear=$('#dash2-cap-clear');if(capClear){capClear.addEventListener('click',async()=>{try{await saveCap(null);const inp=$('#dash2-cap-input');if(inp)inp.value='';setStatus('Cap removed.');await loadSummary();}catch(e){setStatus(`Cap clear failed: ${e.message || e}`,true);}});}
const csv=$('#dash2-billing-csv');if(csv)csv.addEventListener('click',()=>downloadInvoices('csv'));const json=$('#dash2-billing-json');if(json)json.addEventListener('click',()=>downloadInvoices('json'));const alertsForm=$('#dash2-alerts-form');if(alertsForm){alertsForm.addEventListener('submit',async(e)=>{e.preventDefault();const honeypot=$('#dash2-alerts-company-url');if(honeypot&&honeypot.value){showAlertBanner('subscription を登録しました。',false);return;}
const filterType=($('#dash2-alerts-filter-type')||{}).value||'';const filterValue=(($('#dash2-alerts-filter-value')||{}).value||'').trim();const severity=($('#dash2-alerts-severity')||{}).value||'important';const webhook=(($('#dash2-alerts-webhook')||{}).value||'').trim();const email=(($('#dash2-alerts-email')||{}).value||'').trim();if(filterType!=='all'&&!filterValue){showAlertBanner(`filter_value は filter_type='${filterType}' のとき必須です。`,true);return;}
if(!webhook&&!email){showAlertBanner('webhook_url か email のどちらか 1 つ以上を入力してください。',true);return;}
const webhookErr=validateWebhookUrl(webhook);if(webhookErr){showAlertBanner(webhookErr,true);return;}
const payload={filter_type:filterType,min_severity:severity,};if(filterType!=='all')payload.filter_value=filterValue;if(webhook)payload.webhook_url=webhook;if(email)payload.email=email;const submit=$('#dash2-alerts-submit');if(submit)submit.disabled=true;try{const created=await subscribeAlert(payload);showAlertBanner(`subscription #${created.id} を登録しました。`,false);const fv=$('#dash2-alerts-filter-value');const wb=$('#dash2-alerts-webhook');const em=$('#dash2-alerts-email');if(fv)fv.value='';if(wb)wb.value='';if(em)em.value='';await loadAlerts();}catch(err){if(err.status===401){showAlertBanner('API key が無効です。再度入力してください。',true);}else{showAlertBanner(`登録失敗: ${err.message || String(err)}`,true);}}finally{if(submit)submit.disabled=false;}});}
const alertsTbody=$('#dash2-alerts-tbody');if(alertsTbody){alertsTbody.addEventListener('click',async(e)=>{const target=e.target;if(!(target instanceof Element))return;const btn=target.closest('.dash2-alerts-delete');if(!btn)return;const id=btn.getAttribute('data-sub-id');if(!id)return;if(!window.confirm(`subscription #${id} を削除しますか？ (deactivate、再開は新規登録が必要)`)){return;}
btn.disabled=true;try{await deleteAlert(id);showAlertBanner(`subscription #${id} を削除しました。`,false);await loadAlerts();}catch(err){if(err.status===404){showAlertBanner(`subscription #${id} は既に削除されています。`,true);await loadAlerts();}else if(err.status===401){showAlertBanner('API key が無効です。',true);}else{showAlertBanner(`削除失敗: ${err.message || String(err)}`,true);btn.disabled=false;}}});}}
function boot(){bind();detachFromLegacyHide();setTimeout(detachFromLegacyHide,50);setTimeout(detachFromLegacyHide,250);store.get();renderStorageWarning();loadAll();}
if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',boot);}else{boot();}})();
