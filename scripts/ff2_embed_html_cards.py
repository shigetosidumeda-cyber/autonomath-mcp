#!/usr/bin/env python3
"""FF2 — idempotently embed cost-saving section into pricing.html and 5
product pages. Concurrent edits to these HTML files are common in the
jpcite repo (Wave / Stream / Edit agents), so this script re-inserts
the FF2 block only when its sentinel marker (`data-cost-saving-card="FF2"`
or `data-jpcite-cost-saving-calc`) is absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRICING_HTML = "site/pricing.html"
PRODUCT_FILES = [
    "site/products/A1_zeirishi_monthly_pack.html",
    "site/products/A2_cpa_audit_workpaper_pack.html",
    "site/products/A3_gyosei_licensing_eligibility_pack.html",
    "site/products/A4_shihoshoshi_registry_watch.html",
    "site/products/A5_sme_subsidy_companion.html",
]

PRICING_SECTION = """ <section class="cost-saving" aria-labelledby="cost-saving-h" style="margin:32px 0;border:1px solid var(--border,#e5e7eb);border-radius:12px;background:var(--bg-alt,#fafaf9);padding:24px;">
  <h2 id="cost-saving-h" style="font-size:24px;margin:0 0 12px;letter-spacing:-0.01em;">Opus 4.7 chain と比較した削減</h2>
  <p style="font-size:14px;line-height:1.7;margin:0 0 16px;color:var(--text);">jpcite の 1 回呼び出しは、Claude Opus 4.7 を 3〜7 turn 連結して同じ深さの根拠付き回答を組み立てる場合に比べて <strong>1/17 〜 1/167</strong> のコストです。下の表は <a href="/docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md">FF1 SOT</a> の §3 と完全一致しており、MCP tool description footer / OpenAPI <code>x-cost-saving</code> / <a href="/.well-known/agents.json"><code>agents.json</code></a> <code>cost_efficiency_claim</code> もこの数値を参照します。</p>

  <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 0 16px;">
   <table style="width:100%;min-width:560px;border-collapse:collapse;font-variant-numeric:tabular-nums;">
    <thead>
     <tr style="background:var(--bg-alt,#fafaf9);">
      <th scope="col" style="text-align:left;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">Tier</th>
      <th scope="col" style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">jpcite ¥ / call</th>
      <th scope="col" style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">Opus 4.7 等価 turns</th>
      <th scope="col" style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">Opus ¥ / 等価 chain</th>
      <th scope="col" style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">削減</th>
      <th scope="col" style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">削減 %</th>
     </tr>
    </thead>
    <tbody>
     <tr><th scope="row" style="text-align:left;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);"><strong>A</strong> (search/list/get_simple/enum)</th><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);"><strong>¥3</strong></td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">3 (simple)</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥54</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥51</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">94.4 %</td></tr>
     <tr><th scope="row" style="text-align:left;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);"><strong>B</strong> (search_v2 / expand / get_with_relations / batch_get)</th><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);"><strong>¥6</strong></td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">5 (medium)</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥170</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥164</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">96.5 %</td></tr>
     <tr><th scope="row" style="text-align:left;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);"><strong>C</strong> (precomputed_answer / agent_briefing / HE-1 / HE-3 / cohort)</th><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);"><strong>¥12</strong></td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">7 (deep)</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥347</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥335</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">96.5 %</td></tr>
     <tr><th scope="row" style="text-align:left;padding:10px 14px;"><strong>D</strong> (evidence_packet_full / portfolio / regulatory_impact_chain)</th><td style="text-align:right;padding:10px 14px;"><strong>¥30</strong></td><td style="text-align:right;padding:10px 14px;">7 (deep+)</td><td style="text-align:right;padding:10px 14px;">¥500</td><td style="text-align:right;padding:10px 14px;">¥470</td><td style="text-align:right;padding:10px 14px;">94.0 %</td></tr>
    </tbody>
   </table>
  </div>

  <h3 style="font-size:18px;margin:18px 0 8px;">100 query / 年 × 5 cohort の削減 (LIVE)</h3>
  <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 0 16px;">
   <table style="width:100%;min-width:560px;border-collapse:collapse;font-variant-numeric:tabular-nums;">
    <thead><tr style="background:var(--bg-alt,#fafaf9);"><th style="text-align:left;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">Cohort</th><th style="text-align:left;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">Mix</th><th style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">jpcite ¥/年</th><th style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">Opus ¥/年</th><th style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">削減 ¥/年</th><th style="text-align:right;padding:10px 14px;font-size:13px;font-weight:600;color:var(--text-muted);border-bottom:1px solid var(--border,#e5e7eb);">倍率</th></tr></thead>
    <tbody>
     <tr><th style="text-align:left;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">税理士 (Tax-Firm)</th><td style="padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">70 B + 30 C</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥780</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥22,310</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥21,530</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">28.6 x</td></tr>
     <tr><th style="text-align:left;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">会計士 (CPA)</th><td style="padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">40 B + 60 C</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥960</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥27,620</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥26,660</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">28.8 x</td></tr>
     <tr><th style="text-align:left;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">行政書士</th><td style="padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">60 B + 40 C</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥840</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥23,990</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥23,150</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">28.6 x</td></tr>
     <tr><th style="text-align:left;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">司法書士</th><td style="padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">60 A + 40 B</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥420</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥10,040</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">¥9,620</td><td style="text-align:right;padding:10px 14px;border-bottom:1px solid var(--border,#e5e7eb);">23.9 x</td></tr>
     <tr><th style="text-align:left;padding:10px 14px;">SME / 補助金</th><td style="padding:10px 14px;">30 B + 50 C + 20 D</td><td style="text-align:right;padding:10px 14px;">¥1,380</td><td style="text-align:right;padding:10px 14px;">¥36,910</td><td style="text-align:right;padding:10px 14px;">¥35,530</td><td style="text-align:right;padding:10px 14px;">26.7 x</td></tr>
    </tbody>
   </table>
  </div>

  <div id="cost-saving-calc" data-jpcite-cost-saving-calc style="margin:0 0 8px;padding:18px;border:1px solid var(--border,#e5e7eb);border-radius:8px;background:var(--bg,#ffffff);">
   <h3 style="font-size:18px;margin:0 0 10px;">削減シミュレータ — Opus を 1 日何 query 使うか?</h3>
   <p style="font-size:13px;line-height:1.6;margin:0 0 12px;color:var(--text-muted);">jpcite に置き換えた場合の年額削減 (240 営業日想定) を即時計算します。</p>
   <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;margin:0 0 12px;">
    <label style="display:flex;flex-direction:column;font-size:13px;color:var(--text);">1 日の query 数<input id="cs-n-queries" type="number" min="1" max="10000" value="5" style="margin-top:4px;padding:6px 10px;border:1px solid var(--border,#e5e7eb);border-radius:6px;width:8em;"></label>
    <label style="display:flex;flex-direction:column;font-size:13px;color:var(--text);">代表 mix<select id="cs-mix" style="margin-top:4px;padding:6px 10px;border:1px solid var(--border,#e5e7eb);border-radius:6px;">
     <option value="simple">simple (A 100%)</option>
     <option value="medium" selected>medium (60 B + 40 C)</option>
     <option value="deep">deep (40 B + 50 C + 10 D)</option>
     <option value="mixed">mixed (35 A + 35 B + 25 C + 5 D)</option>
    </select></label>
    <label style="display:flex;flex-direction:column;font-size:13px;color:var(--text);">営業日 / 年<input id="cs-wd" type="number" min="1" max="365" value="240" style="margin-top:4px;padding:6px 10px;border:1px solid var(--border,#e5e7eb);border-radius:6px;width:6em;"></label>
   </div>
   <div id="cs-result" style="font-size:15px;line-height:1.7;color:var(--text);background:var(--bg-alt,#fafaf9);padding:12px 14px;border-radius:6px;border:1px solid var(--border,#e5e7eb);">
    <strong>jpcite</strong>: <span id="cs-jpcite-yen">¥2,160</span> / 年 ・ <strong>Opus 4.7 chain</strong>: <span id="cs-opus-yen">¥61,920</span> / 年 ・ <strong>削減</strong>: <span id="cs-saving-yen">¥59,760</span> (<span id="cs-saving-ratio">28.7x</span>)
   </div>
   <p style="font-size:12px;color:var(--text-muted);margin:10px 0 0;line-height:1.6;">計算式 (verifiable): jpcite ¥/年 = n × wd × tier_¥; Opus ¥/年 = n × wd × Opus_tier_¥。係数は <a href="/docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md">FF1 SOT §3</a> と完全一致。</p>
  </div>

  <script>
  (function () {
   const TIERS = { A:{jp:3, op:54}, B:{jp:6, op:170}, C:{jp:12, op:347}, D:{jp:30, op:500} };
   const MIX = {
    simple : { A:1.00, B:0.00, C:0.00, D:0.00 },
    medium : { A:0.00, B:0.60, C:0.40, D:0.00 },
    deep   : { A:0.00, B:0.40, C:0.50, D:0.10 },
    mixed  : { A:0.35, B:0.35, C:0.25, D:0.05 }
   };
   function fmt(n) { return '¥' + Math.round(n).toLocaleString('ja-JP'); }
   function recalc() {
    const n  = Math.max(1, parseInt(document.getElementById('cs-n-queries').value || '0', 10));
    const wd = Math.max(1, parseInt(document.getElementById('cs-wd').value || '0', 10));
    const mx = MIX[document.getElementById('cs-mix').value] || MIX.medium;
    let jp = 0, op = 0;
    for (const k of ['A','B','C','D']) {
     jp += mx[k] * TIERS[k].jp;
     op += mx[k] * TIERS[k].op;
    }
    const tot_jp = n * wd * jp;
    const tot_op = n * wd * op;
    const sv = tot_op - tot_jp;
    const ratio = tot_op > 0 ? (tot_op / Math.max(tot_jp, 1)) : 0;
    document.getElementById('cs-jpcite-yen').textContent = fmt(tot_jp);
    document.getElementById('cs-opus-yen').textContent = fmt(tot_op);
    document.getElementById('cs-saving-yen').textContent = fmt(sv);
    document.getElementById('cs-saving-ratio').textContent = ratio.toFixed(1) + 'x';
   }
   document.addEventListener('DOMContentLoaded', function () {
    ['cs-n-queries','cs-wd','cs-mix'].forEach(function (id) {
     const el = document.getElementById(id);
     if (el) el.addEventListener('input', recalc);
    });
    recalc();
   });
  })();
  </script>

  <h3 style="font-size:18px;margin:18px 0 8px;">1 回 ¥500 → ¥6 (1/83) の代表例</h3>
  <p style="font-size:14px;line-height:1.7;margin:0 0 6px;color:var(--text);">Opus 4.7 を 7 turn 連結し 5 PDF を anchor 投入する Deep++ tool-calling chain は ¥497〜¥500 / 1 chain (FX ¥150/USD)。jpcite Tier B 1 call (¥6) で同じ「制度改正 + 一次資料 URL + known_gaps」をまとめて返します — <strong>83 倍の倍率削減</strong>。Tier A (¥3) の単純 search に置き換えれば <strong>167 倍</strong>、Tier C (¥12) の precomputed answer / cohort match / HE-1 evidence packet で <strong>42 倍</strong>。</p>
  <p style="font-size:13px;line-height:1.7;margin:0;color:var(--text-muted);">数値の出典・前提 FX・per-turn 計算は <a href="/docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md"><strong>FF1 SOT (JPCITE_COST_ROI_SOT_2026_05_17.md)</strong></a> §2.5 (Deep++ 7-turn) で公開。同 SOT は MCP description footer / OpenAPI <code>x-cost-saving</code> / <a href="/.well-known/agents.json"><code>agents.json</code></a> <code>cost_efficiency_claim</code> の 3 store 一致を <a href="https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/scripts/validate_cost_saving_claims_consistency.py">scripts/validate_cost_saving_claims_consistency.py</a> で gate。</p>
 </section>

"""

PRODUCT_CARDS: dict[str, dict[str, str | int]] = {
    "A1_zeirishi_monthly_pack.html": {
        "title": "税理士 月次 — 削減 (FF1 SOT §4)",
        "tier": "B",
        "jpcite_unit_yen": 6,
        "count": 12,
        "unit_label": "packets / 年",
        "opus_per_call_yen": 500,
        "opus_label": "7-turn Opus 4.7 Deep++ chain",
        "note": "12 ヶ月分 × Opus ¥500/req = ¥6,000 vs jpcite ¥72 (12 × ¥6) → <strong>83.3x</strong> / ¥5,928 削減",
    },
    "A2_cpa_audit_workpaper_pack.html": {
        "title": "会計士 監査調書 — 削減 (FF1 SOT §4)",
        "tier": "C",
        "jpcite_unit_yen": 12,
        "count": 10,
        "unit_label": "監査調書 / 期",
        "opus_per_call_yen": 300,
        "opus_label": "5-turn Opus 4.7 medium chain (監査調書 1 件)",
        "note": "監査調書 10 件 × Opus ¥300/件 = ¥3,000 vs jpcite ¥120 (10 × ¥12) → <strong>25.0x</strong> / ¥2,880 削減",
    },
    "A3_gyosei_licensing_eligibility_pack.html": {
        "title": "行政書士 適格 — 削減 (FF1 SOT §4)",
        "tier": "B",
        "jpcite_unit_yen": 6,
        "count": 1,
        "unit_label": "申請 / 件",
        "opus_per_call_yen": 170,
        "opus_label": "5-turn Opus 4.7 medium chain (適格性判定 1 件)",
        "note": "申請 1 件 × Opus ¥170 vs jpcite ¥6 (Tier B) → <strong>28.3x</strong> / ¥164 削減",
    },
    "A4_shihoshoshi_registry_watch.html": {
        "title": "司法書士 登記 watch — 削減 (FF1 SOT §4)",
        "tier": "A",
        "jpcite_unit_yen": 3,
        "count": 30,
        "unit_label": "watch / 月",
        "opus_per_call_yen": 54,
        "opus_label": "3-turn Opus 4.7 simple chain (登記簿 watch 1 件)",
        "note": "月 30 watch × Opus ¥54 = ¥1,620 vs jpcite ¥90 (30 × ¥3) → <strong>18.0x</strong> / ¥1,530 削減",
    },
    "A5_sme_subsidy_companion.html": {
        "title": "SME 補助金 候補 — 削減 (FF1 SOT §4)",
        "tier": "C",
        "jpcite_unit_yen": 12,
        "count": 5,
        "unit_label": "候補 / 案件",
        "opus_per_call_yen": 347,
        "opus_label": "7-turn Opus 4.7 deep chain (候補 1 件)",
        "note": "候補 5 件 × Opus ¥347 = ¥1,735 vs jpcite ¥60 (5 × ¥12) → <strong>28.9x</strong> / ¥1,675 削減",
    },
}


def render_product_card(info: dict[str, str | int]) -> str:
    return (
        '\n  <section class="cost-saving-card" data-cost-saving-card="FF2" '
        'style="margin:18px 0;padding:16px 18px;border:1px solid #e5e7eb;border-radius:10px;background:#fafaf9;">\n'
        f'    <h2 style="margin:0 0 8px;font-size:18px;">{info["title"]}</h2>\n'
        f'    <p style="margin:0 0 6px;font-size:14px;line-height:1.7;"><strong>Tier {info["tier"]}</strong> '
        f"(¥{info['jpcite_unit_yen']}/req): {info['count']} {info['unit_label']} を 1 cron で集約。</p>\n"
        f'    <p style="margin:0 0 6px;font-size:14px;line-height:1.7;">Opus 4.7 同等深さ: '
        f"{info['opus_label']} ≈ ¥{info['opus_per_call_yen']} / 1 chain (FX ¥150/USD anchor; FF1 SOT §2)。</p>\n"
        f'    <p style="margin:0 0 6px;font-size:15px;line-height:1.7;"><strong>削減</strong>: {info["note"]}</p>\n'
        '    <p style="margin:0;font-size:12px;color:#666;">数値検証: '
        '<a href="/docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md">FF1 SOT</a> §3 / §4 ・ '
        '<a href="/.well-known/agents.json">agents.json</a> <code>cost_efficiency_claim</code> ・ '
        "MCP tool description footer。3 store 一致は "
        "<code>scripts/validate_cost_saving_claims_consistency.py</code> で CI gate。</p>\n"
        "  </section>\n"
    )


def insert_pricing() -> bool:
    p = ROOT / PRICING_HTML
    if not p.exists():
        return False
    src = p.read_text(encoding="utf-8")
    if "data-jpcite-cost-saving-calc" in src:
        return False
    marker = " </div>\n</main>"
    if marker not in src:
        marker = "</main>"
    new = src.replace(marker, PRICING_SECTION + "\n" + marker, 1)
    p.write_text(new, encoding="utf-8")
    print(f"{PRICING_HTML}: inserted FF2 calculator + cohort table")
    return True


def insert_product(fname: str, info: dict[str, str | int]) -> bool:
    p = ROOT / "site/products" / fname
    if not p.exists():
        return False
    src = p.read_text(encoding="utf-8")
    if 'data-cost-saving-card="FF2"' in src:
        return False
    block = render_product_card(info)
    markers = [
        "<h2>jpcite ¥",
        "<h2>jpcite ",
        "<h2>1 call",
        "<h2>使い始める",
    ]
    for mk in markers:
        idx = src.find(mk)
        if idx >= 0:
            new = src[:idx] + block + src[idx:]
            p.write_text(new, encoding="utf-8")
            print(f"site/products/{fname}: inserted FF2 saving card")
            return True
    print(f"WARN: no marker for {fname}", file=sys.stderr)
    return False


def main() -> int:
    insert_pricing()
    for fname, info in PRODUCT_CARDS.items():
        insert_product(fname, info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
