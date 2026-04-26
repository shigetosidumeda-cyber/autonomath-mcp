(function(){"use strict";var form=document.getElementById("ps-form");var submit=document.getElementById("ps-submit");var resultsEl=document.getElementById("ps-results");var statusLiveEl=document.getElementById("ps-status-live");function announce(msg){if(statusLiveEl)statusLiveEl.textContent=msg||"";}
if(!form||!submit||!resultsEl)return;function resolveEndpoint(){var base=form.getAttribute("data-api-base")||"";return base.replace(/\/+$/,"")+"/v1/programs/prescreen";}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;",}[c];});}
function formatAmount(manYen){if(manYen==null)return"金額非公開";if(manYen>=10000){return(manYen/10000).toLocaleString("ja-JP",{maximumFractionDigits:1})+" 億円";}
return manYen.toLocaleString("ja-JP")+" 万円";}
function renderRows(results){if(!results.length){return('<p class="ps-status">条件に一致する制度は見つかりませんでした。都道府県や投資額を変えて再試行してください。</p>');}
var items=results.map(function(r){var tier=r.tier||"";var reasonsHtml=(r.match_reasons||[]).map(function(x){return"<li>"+escapeHtml(x)+"</li>";}).join("");var caveatsHtml=(r.caveats||[]).map(function(x){return"<li>"+escapeHtml(x)+"</li>";}).join("");var sourceHtml=r.official_url?'<p class="ps-source">出典: <a rel="noopener noreferrer nofollow" target="_blank" href="'+
escapeHtml(r.official_url)+'">'+
escapeHtml(r.official_url)+"</a></p>":"";return('<li class="ps-row">'+'<div class="ps-row-head">'+
(tier?'<span class="ps-tier t-'+escapeHtml(tier)+'">Tier '+escapeHtml(tier)+"</span>":"")+'<a class="ps-name" href="/programs/'+escapeHtml(r.unified_id)+'.html">'+
escapeHtml(r.primary_name||r.unified_id)+"</a>"+'<span class="ps-amount">上限 '+
escapeHtml(formatAmount(r.amount_max_man_yen))+"</span>"+"</div>"+
(reasonsHtml?'<ul class="ps-reasons">'+reasonsHtml+"</ul>":"")+
(caveatsHtml?'<ul class="ps-caveats">'+caveatsHtml+"</ul>":"")+
sourceHtml+"</li>");}).join("");return'<ul class="ps-list">'+items+"</ul>";}
function setBusy(on){submit.disabled=on;submit.textContent=on?"検索中…":"上位 5 件を見る";resultsEl.setAttribute("aria-busy",on?"true":"false");}
function showError(msg){resultsEl.classList.add("is-visible");resultsEl.innerHTML='<p class="ps-error">'+escapeHtml(msg)+"</p>";announce("エラー: "+msg);}
function showRichError(html){resultsEl.classList.add("is-visible");resultsEl.innerHTML='<p class="ps-error">'+html+"</p>";}
form.addEventListener("submit",async function(e){e.preventDefault();var honeypot=form.elements["company_url"];if(honeypot&&honeypot.value){resultsEl.classList.add("is-visible");resultsEl.innerHTML='<p class="ps-status">送信完了</p>';return;}
setBusy(true);var prefecture=form.elements["prefecture"].value||null;var formType=form.elements["form_type"].value;var investment=form.elements["planned_investment_man_yen"].value;var body={limit:5};if(prefecture&&prefecture!=="全国")body.prefecture=prefecture;if(formType==="true")body.is_sole_proprietor=true;else if(formType==="false")body.is_sole_proprietor=false;if(investment)body.planned_investment_man_yen=Number(investment);var ctrl=new AbortController();var timer=setTimeout(function(){ctrl.abort();},15000);try{var resp=await fetch(resolveEndpoint(),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:ctrl.signal,});if(resp.status===429){showRichError('匿名上限 (50 req/月 per IP) に達しました。<a href="/dashboard.html">API キーを発行</a> (Free 50 req/月、追加は ¥3/req 税込 ¥3.30)。');return;}
if(!resp.ok){var text="";try{var j=await resp.json();if(Array.isArray(j.detail)){text=j.detail_summary_ja||j.detail.map(function(e){return e.msg_ja||e.msg||"";}).filter(Boolean).join(", ")||"入力検証に失敗しました。";}else{text=j.detail||j.error||JSON.stringify(j);}}catch(_){text="HTTP "+resp.status;}
showError("エラーが発生しました: "+text);return;}
var data=await resp.json();var summary="候補 "+
(data.total_considered||0).toLocaleString("ja-JP")+" 件から適合度が高い順に 上位 "+
((data.results||[]).length)+" 件を表示。";resultsEl.classList.add("is-visible");var ctaHtml='<div class="ps-cta">'+'<a class="btn btn-primary" href="/dashboard.html">続きを API キーで取得 (Free 50 req/月)</a>'+'<a class="btn btn-secondary" href="/getting-started.html">MCP で接続する</a>'+"</div>";resultsEl.innerHTML='<p class="ps-status">'+escapeHtml(summary)+"</p>"+renderRows(data.results||[])+ctaHtml;announce(summary);}catch(err){if(err&&err.name==="AbortError"){showError("タイムアウト — 回線が遅いか、サーバが応答していません。再度お試しください。");}else{showError("ネットワークエラーが発生しました。時間をおいて再試行してください ("+
(err&&err.message?err.message:"unknown")+")");}}finally{clearTimeout(timer);setBusy(false);}});})();