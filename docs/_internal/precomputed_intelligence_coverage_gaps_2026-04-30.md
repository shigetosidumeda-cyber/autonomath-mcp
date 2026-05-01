# Precomputed intelligence non-program coverage gaps (2026-04-30)

Scope: `/v1/intelligence/precomputed/query` after the natural-language
program fallback. Local sweep used `EvidencePacketComposer.compose_for_query`
against `autonomath.db` and `data/jpintel.db`, `limit=10`,
`include_facts=false`, `include_rules=false`, `include_compression=false`.

Update after the compact non-program fallback plus exact-identifier
structured misses: the endpoint now returns law/tax/enforcement/adoption
records for the relevant non-program intents. Local
`bench_prefetch_probe.py --limit 5` now reports `zero_result_queries=0`
(`zero_result_rate=0.0`) across the 30-query set.

Important caveat: two exact-identifier queries are **not evidence hits**.
They return `record_kind=structured_miss` with
`lookup.status=not_found_in_local_mirror`, `official_absence_proven=false`,
and checked-table metadata. This prevents downstream LLM/UI callers from
treating "no rows" as either a blank answer or an official clean/absent
finding.

The table below is the pre-fallback investigation log and remains useful for
next-step routing/corpus work:

| id | query | current precomputed result | existing dataset / route that could satisfy it | note |
|---:|---|---:|---|---|
| 11 | 法人番号 4120101047866 の採択履歴 | 0 | `autonomath.db:jpi_adoption_records` via `/v1/houjin/{bangou}` | Exact corpus hit: 8 adoption rows. `am_entities` also has `houjin:4120101047866` (`株式会社アンド・アイ`). |
| 12 | 株式会社メルカリ 法人番号 採択事例 | 0 | Houjin/adoption corpus, but no current REST name-search route | Local `houjin_master` / `am_entities` did not contain a `メルカリ` exact/substring hit. Needs either a broader houjin name index/route or a different seed company. |
| 13 | 法人番号 1010001034730 の行政処分有無 | 1 structured miss | `am_enforcement_detail` / `/v1/houjin/{bangou}` if the corpus has the entity | Exact local probe found no `am_entities` row and 0 `am_enforcement_detail` / `jpi_enforcement_cases` rows for this number, so the endpoint returns a local-mirror miss, not a clean-record claim. |
| 14 | 適格請求書発行事業者 T8010001213708 登録日 | 1 structured miss | `/v1/invoice_registrants/{invoice_registration_number}` and `invoice_registrants` / `jpi_invoice_registrants` | Exact local probe found 0 rows. The endpoint now returns a structured local-mirror miss with the NTA official lookup URL, not a registration date. |
| 18 | 個人情報保護法 漏洩 報告義務 | 0 | `/v1/laws/search?q=個人情報保護法` over `laws` | Exact law exists: `LAW-2ba9492b49` (`個人情報の保護に関する法律`). Current law summaries are thin e-Gov catalog summaries, so article-level breach-reporting answer would need article/fact extraction or query decomposition. |
| 22 | 固定資産税 償却資産 軽減措置 | 0 | `tax_rulesets` partially | Current hits are corporate asset accounting/depreciation rules (`少額減価償却資産`, `一括償却資産`, IT subsidy accounting), not local fixed-asset-tax relief. Treat as tax corpus gap for this specific intent. |
| 25 | 消費税 簡易課税 みなし仕入率 | 0 | `/v1/tax_rulesets/search?q=簡易課税` over `tax_rulesets` | Exact ruleset exists: `TAX-db595d7d5f`, rate/amount `業種別みなし仕入率 40%-90%`. |
| 26 | 過去3年の建設業 業務停止 | 0 | `autonomath.db:am_enforcement_detail` | Broad enforcement corpus has matching rows (probe: 89 rough matches for 建設 + 停止). Existing REST `/v1/enforcement-cases/search` is the narrower 1,185-row 会計検査院/subsidy surface and returned 0 for this shape. |
| 27 | 宅地建物取引業 免許取消 直近 | 0 | `autonomath.db:am_enforcement_detail` | Broad enforcement corpus has matching rows (probe: 33 rough matches for 宅建/宅地 + 取消). Needs route/query layer over `am_enforcement_detail`, not the current subsidy enforcement REST route. |
| 28 | 建設業 営業停止 東京都 | 0 | `autonomath.db:am_enforcement_detail` | Broad enforcement corpus has matching rows (probe: 90 rough matches for 建設 + 東京 authority; recent examples include 東京都 construction/safety actions). |
| 29 | 労働者派遣事業 行政処分 件数 | 0 | `autonomath.db:am_enforcement_detail` | Broad enforcement corpus has matching rows (probe: 72 rough 派遣 matches). Existing REST route has only 1 rough match in `enforcement_cases`. |
| 30 | 金融商品取引業 業務改善命令 | 0 | `autonomath.db:am_enforcement_detail` | Broad enforcement corpus has matching rows (probe: 145 rough 金融/証券 + 改善 matches, many from TSE-style improvement/monitoring records). |

Implication: the next coverage lift is not another `jpi_programs` fallback.
The precomputed query router needs a small intent/router layer that can return
compact, citation-bearing bundles from:

- Houjin/adoption/invoice/enforcement joins for corporate-number queries.
- `invoice_registrants` exact T-number lookup, including structured miss
  metadata when the mirror is incomplete.
- `laws` for statute lookup, with an honest caveat for article-level questions.
- `tax_rulesets` for tax ruleset lookups.
- Broad `am_enforcement_detail` for licensing/administrative-action queries;
  `/v1/enforcement-cases/search` covers a different, narrower corpus.
