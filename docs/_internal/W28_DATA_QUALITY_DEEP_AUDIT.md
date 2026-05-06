# W28 Data Quality Deep Audit

- run_at: `2026-05-05` (JST)
- scope: `am_law_article` (319,836→320,897 rows live), `program_law_refs` (1,899), `programs` (14,472), `nta_tsutatsu_index` (3,232), `tools/offline/_inbox/_archived/` (724 files / 7,329 rows)
- DBs: `autonomath.db` (am_law_article, nta_tsutatsu_index), `data/jpintel.db` (program_law_refs, programs)
- mode: read-only audit; no fixes applied
- LLM: 0 (pure SQL + curl)

> Note on counts: scope spec said `am_law_article=268,973`; actual live count at audit time is `320,897` (live ingest progressed during W26). Spec said `nta_tsutatsu_index=3,230`; actual `3,232`. Numbers below use observed values.

---

## 1. Primary-source host check (Audit 1)

### `am_law_article.source_url` (320,897 rows)
| host | rows | pct |
|---|---:|---:|
| `laws.e-gov.go.jp` | 316,348 | 98.58% |
| `www.nta.go.jp` | 3,221 | 1.00% |
| `elaws.e-gov.go.jp` | 257 | 0.08% |
| `www.mhlw.go.jp` | 10 | 0.003% |

### `am_law_article.body_en_source_url`
| host | rows | pct |
|---|---:|---:|
| `(NULL)` | 320,896 | 99.999% |
| `www.japaneselawtranslation.go.jp` | 1 | 0.0003% |

### `program_law_refs.source_url` (1,899 rows)
60+ unique go.jp / official institutional hosts. Top 10:
| host | rows |
|---|---:|
| `laws.e-gov.go.jp` | 1,367 |
| `www.mhlw.go.jp` | 74 |
| `www.mlit.go.jp` | 56 |
| `www.fsa.go.jp` | 36 |
| `www.jfc.go.jp` | 32 |
| `www.cfa.go.jp` | 26 |
| `www.meti.go.jp` | 24 |
| `www.env.go.jp` | 22 |
| `www.maff.go.jp` | 18 |
| `www.mext.go.jp` | 17 |

### Aggregator scan (noukaweb / hojyokin-portal / biz.stayway / mirasapo-plus / J-NET21)
- `am_law_article.source_url`: **0** aggregator hits
- `program_law_refs.source_url`: **0** aggregator hits
- `_inbox/_archived/**.jsonl`: **0** aggregator URLs (1 narrative file mentions "noukaweb" inside disclaimer text saying "noukaweb は一次資料ではない" — that is a *warning string*, not a citation)

**Verdict: CLEAN. All primary-source hosts are go.jp / .or.jp official institutions. Aggregator-zero policy holds.**

> One latent risk: `body_en_source_url` is 99.999% NULL — see issue **HIGH-1** below. Migration 090 added the column for foreign FDI cohort but ETL has only landed 1 row.

---

## 2. content_hash uniqueness (Audit 2)

### `am_law_article` (no `content_hash` column on this table)
- (`law_canonical_id`, `article_number`) UNIQUE constraint enforces row-level dedup at schema level → **0 duplicate pairs / 320,897 rows**
- `text_full` text-level duplication: 75,924 dupe rows / 320,589 non-null rows (23.7%). Inspected top dupes — all are statutory boilerplate strings such as `（施行期日）第一条この法律は、公布の日から施行する` (1,799 occurrences) which legitimately recur in附則 of every statute. **Not a quality defect.**

### `_inbox/_archived/` (`content_hash` field present in 7,329 / 7,329 rows)
- unique hashes: 6,976
- duplicate hash extra rows: **353**
- Top dupes: same NTA tsutatsu URL fetched 7-8x by parallel agents (e.g. `https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/08.htm` × 8). **Idempotent ingest dedupes these via UNIQUE constraint** at insert; the inbox JSONL keeps all attempts as audit trail.

**Verdict: PASS at DB layer. Inbox parallel-collision noise is by design.**

---

## 3. License field validity (Audit 3)

### `am_law_article.body_en_license`
| license | rows | pct |
|---|---:|---:|
| `cc_by_4.0` | 320,897 | 100.00% |

- 0 NULL, 0 unknown, 0 invalid

### `program_law_refs`
- No license column on this table (refs are pointers, not corpora) → not applicable

### `programs`
- No license column (programs are aggregated metadata; per-row license tracked via `am_source.license` join in autonomath.db; per CLAUDE.md A4 status: 805 unknown, 96k+ filled)

**Verdict: CLEAN at am_law_article. Note: `body_en_license` defaults to `cc_by_4.0` even on rows where `body_en` is NULL (320,896 such rows) — column is filled but data behind it is empty (issue HIGH-1).**

---

## 4. URL liveness sample (Audit 4)

100 random URLs sampled (60 from `am_law_article.source_url`, 40 from `program_law_refs.source_url`). HEAD with GET retry on 000/403/405; UA `Mozilla/5.0`; max-time 10-12s.

| status | count | pct |
|---|---:|---:|
| 200 | 90 | 90% |
| 000 (curl-side: timeout/DNS/TLS) | 7 | 7% |
| 404 | 3 | 3% |

### Non-200 detail
- `https://faq.enecho-saiene.go.jp/faq/show/55` — DNS SERVFAIL (host gone)
- `https://www.meti.go.jp/...battery/index.html` and 4 other meti.go.jp / jpo / enecho — Akamai TLS handshake stall on bot UA (manual reverify shows 200 with browser UA; counted as 000 here)
- `https://www8.cao.go.jp/okinawa/tokutei/gaiyou7.pdf` — 404 (page removed)
- `https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000159010.html` — 404
- `https://www.mext.go.jp/a_menu/shotou/shinkou/tsushinsei.html` — 404

**Real dead-rate: 4/100 = 4% (1 DNS, 3 hard 404). Akamai-blocked 5/100 are alive but bot-rejected.**

**Verdict: 4% dead, 5% bot-blocked, 90%+ live. Within tolerance for a 320k corpus where source_url_status='unknown' for 99.21% of programs (see issue MED-2).**

---

## 5. Aggregator-source 0-count verify (Audit 5)

Already covered in §1. Restated here for the audit checklist:
- `am_law_article.source_url`: 0 hits across (noukaweb | hojyokin-portal | biz.stayway | mirasapo-plus | j-net21)
- `program_law_refs.source_url`: 0 hits
- `_inbox/_archived/**.jsonl` URL fields: 0 hits

**Verdict: PASS — aggregator ban (CLAUDE.md §「Non-negotiable constraints」) holds across all corpora.**

---

## 6. Cross-source agreement rate (Audit 6)

### `programs.cross_source_verified` (JSON array of source families)
| source_count | rows | pct |
|---|---:|---:|
| 0 | 1,159 | 8.01% |
| 1 | 12,679 | 87.61% |
| 2 | 596 | 4.12% |
| **3+** | **38** | **0.26%** |

### `programs.verification_count` (integer counter, separate from above)
| count | rows | pct |
|---|---:|---:|
| 0 | 1,128 | 7.79% |
| 1 | 12,236 | 84.55% |
| 2 | 877 | 6.06% |
| **3+** | **231** | **1.60%** |

**Spec target was 10%+ programs with 3+ sources. Actual: 0.26% (cross_source_verified) / 1.60% (verification_count). FAR BELOW TARGET.**

Top source-family vocabulary (W21-2): `city_lg_jp` 4,023, `pref_lg_jp` 3,018, `maff` 1,139, `go_jp_other` 935, `or_jp` 710, `mhlw` 536. Vocabulary is normalized (no mixed languages observed).

**Verdict: BELOW TARGET (issue HIGH-2).**

---

## 7. Stale data audit (Audit 7)

| corpus | fresh ≤7d | 7-30d | >30d | NULL |
|---|---:|---:|---:|---:|
| `am_law_article.source_fetched_at` | 313,285 (97.63%) | 7,612 (2.37%) | 0 | 0 |
| `program_law_refs.fetched_at` | 1,665 (87.68%) | 234 (12.32%) | 0 | 0 |
| `programs.source_fetched_at` | 894 (6.18%) | **13,562 (93.71%)** | 0 | 16 (0.11%) |
| `nta_tsutatsu_index.refreshed_at` | 3,232 (100.00%) | 0 | 0 | 0 |

**`programs` is mostly 7-30d old (93.71%). 0 rows >30d (no truly-stale data) but the bulk of programs has not been refetched within the last week.**

**Verdict: am_law_article / program_law_refs / nta_tsutatsu_index are FRESH. programs corpus is MILDLY STALE — within 30d boundary the spec requested but trending older (issue MED-1).**

---

## 8. Content quality (Audit 8)

### `am_law_article.text_full` length distribution
| bucket | rows | pct |
|---|---:|---:|
| `>=200_chars` | 135,766 | 42.31% |
| `50-200_chars` | 146,596 | 45.68% |
| `<50_chars` | 38,227 | 11.91% |
| NULL | 308 | 0.10% |

### `<50_chars` sub-classification (38,227 rows)
| bucket | rows |
|---|---:|
| `enforce_date_boilerplate` (e.g. `（施行期日）第一条この法律は、公布の日から施行する`) | 26,649 |
| `other` (still-legitimate short statutory clauses) | 7,809 |
| `deleted` (e.g. `第二十八条削除`) | 3,498 |
| `transition_boilerplate` (`（経過措置）...`) | 163 |
| `single_line_enforce` | 108 |

Manual sample of "other" 7,809: all are legitimate short statutory clauses (e.g. `（内国法人の納税地）第十六条内国法人の法人税の納税地は、その本店又は主たる事務所の所在地とする`, `（贈与税の基礎控除）第二十一条の五贈与税については、課税価格から六十万円を控除する`).

### Placeholder / TODO scan
- `TODO|FIXME|placeholder|PLACEHOLDER`: **0**
- `（仮）|※未定`: **1**
- `現に効力|失効`: 1,029 (legitimate "失効" mentions in supersession clauses)

### `nta_tsutatsu_index.body_excerpt`
| bucket | rows | pct |
|---|---:|---:|
| `>=200_chars` | 2,094 | 64.79% |
| `50-200_chars` | 1,069 | 33.08% |
| `<50_chars` | 69 | 2.13% |

### `am_law_article.text_full IS NULL` (308 rows)
- 69 rows are `law:sozei-tokubetsu` (措置法) with title populated but text_full NULL → real ingest gap (issue MED-3)
- 239 remaining: distributed across other laws

**Verdict: Bulk of <50-char rows are legitimate statutory boilerplate (deleted/施行期日/経過措置), NOT placeholder noise. 308 NULL text_full rows are a genuine gap concentrated in 措置法.**

---

## Issues summary

| ID | severity | summary | locus |
|---|---|---|---|
| HIGH-1 | HIGH | `body_en` corpus is essentially empty: 320,896 / 320,897 NULL despite migration 090 + foreign FDI cohort dependency. License default `cc_by_4.0` populates without backing data. | `am_law_article.body_en` |
| HIGH-2 | HIGH | Cross-source verification far below 10% target: only 0.26% (cross_source_verified) / 1.60% (verification_count) reach 3+ sources. Single-source 87.6% of corpus. | `programs.cross_source_verified` / `verification_count` |
| HIGH-3 | HIGH | `program_law_refs.ref_kind` only carries the value `reference` (1,899/1,899). Schema CHECK allows `authority|eligibility|exclusion|reference|penalty` but ETL never writes the other 4 kinds → no 根拠条文 / 除外条文 / 罰則 distinction. Avg confidence 0.698 (min 0.35) is also low. | `program_law_refs.ref_kind` + `confidence` |
| MED-1 | MED | `programs.source_fetched_at`: 93.71% in the 7-30d window, only 6.18% fresh ≤7d. Trending toward staleness; 16 rows have NULL fetched_at. | `programs.source_fetched_at` |
| MED-2 | MED | `programs.source_url_status`: 99.21% (14,358) `unknown`. `source_last_check_status` NULL on 13,094 / 14,472 (90.5%). The nightly liveness sweep is not covering the bulk of the corpus. | `programs.source_url_status` |
| MED-3 | MED | 308 `am_law_article.text_full IS NULL` rows (69 in `law:sozei-tokubetsu` 措置法). Title present, body absent — real ingest gap. | `am_law_article.text_full` |
| MED-4 | MED | URL liveness: 4% hard-dead (1 DNS-gone, 3 hard 404) on a random 100-URL sample. Extrapolated to 320k = ~12,800 dead URLs. Today these silently 404 to MCP users. | `am_law_article.source_url` |
| LOW-1 | LOW | 4 `program_law_refs.source_url` rows contain comma-separated host strings (e.g. `e-gov.go.jp, mlit.go.jp`) instead of a real URL. Schema is `TEXT NOT NULL` so they pass; downstream curl will fail. | `program_law_refs.source_url` (4 rows) |
| LOW-2 | LOW | curl bot-rejection: ~5% of meti.go.jp / jpo.go.jp / enecho URLs return 000 on `Mozilla/5.0` UA via Akamai. Liveness sweep needs full browser UA + retry. | `scripts/refresh_sources.py` |
| LOW-3 | LOW | `_inbox/_archived/` 353 duplicate `content_hash` rows from parallel-agent re-fetches. Idempotent ingest absorbs them but wastes fetch budget. | inbox parallel agents |

---

## Recommendations (do NOT execute in this task)

1. **HIGH-1 / `body_en` fill** — Run `scripts/etl/batch_translate_corpus.py` against the 320,896 NULL rows (target: top-N most-cited articles first, NOT full 320k). Update `body_en_license` to NULL on rows still without `body_en` to stop the false-positive "everything is CC-BY translated" signal. Without this, the foreign-FDI cohort surface (CLAUDE.md cohort #4) has no substrate.
2. **HIGH-2 / cross-source 10% goal** — Add a W29 ingest pass that fetches each tier S/A program from a second authoritative source (pref vs. ministry) and bumps `verification_count`. Even pushing tier S+A (1,454 programs) to 3-source would lift the 3+ rate from 1.6% to ~11%.
3. **HIGH-3 / `ref_kind` diversity** — Inspect the ETL that writes `program_law_refs`. Currently every row is force-tagged `reference`. Add classifier (regex on context: 根拠 → authority, 別表 → eligibility, 罰則 → penalty, 適用除外 → exclusion). Without this, `find_complementary_programs_am` and `apply_eligibility_chain_am` cannot distinguish 根拠条文 from 例示, undercutting the §52 disclaimer surface.
4. **MED-1 / freshness** — Schedule weekly `refresh_sources.py --tier S,A,B` rather than the current monthly cadence. 16 NULL `source_fetched_at` rows: backfill from `valid_from` or set to `2026-01-01` sentinel.
5. **MED-2 / liveness coverage** — `refresh_sources.py` currently filters by tier; expand to all 14,472 rows in 4 weekly slices (3,618/wk = 30 RPS budget). Stop relying on `source_url_status='unknown'` as the modal value.
6. **MED-3 / 措置法 fill** — One-shot ingest of 措置法 + 政令 + 規則 articles via e-Gov API for the 69 missing rows; document the remaining 239 NULL distribution.
7. **MED-4 / dead URL sweep** — On the next `refresh_sources.py` run, mark `source_last_check_status >= 400` rows for human review. ~12,800 extrapolated dead URLs is a §景表法 risk if surfaced via MCP without dead-link banner.
8. **LOW-1 / 4 malformed program_law_refs.source_url** — Manual fix or DELETE; add CHECK constraint `source_url LIKE 'http%'` after cleanup.
9. **LOW-2 / curl UA** — Use full `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121` UA + 1-retry-with-15s-timeout in `refresh_sources.py`. Akamai allowlists this signature.
10. **LOW-3 / parallel-agent dedup** — Add a Bloom filter / Redis set keyed on URL inside the wave-queue dispatcher; skip-task-if-in-flight. Saves ~5% fetch budget on next wave.

---

**Audit summary**: 8/8 audits executed. Corpus is **honest at the source-host layer** (zero aggregator hits) and **fresh at the law-article layer** (97.6% ≤7d). Top gaps are: empty `body_en` corpus, single-mode `ref_kind`, and below-target cross-source verification. No HIGH defects are launch-blockers for the v0.3.2 ¥3/req surface but all three constrain cohort #4 (Foreign FDI) and the §52 advisory disclaimers.
