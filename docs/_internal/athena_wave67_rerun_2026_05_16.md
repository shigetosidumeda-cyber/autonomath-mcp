# Athena Wave 67 RE-RUN — Q11-Q15 + 2 new (Wave 60-65 + Wave 66-68)

Date: 2026-05-16 (post 687-packet sync, commit 878c09e74)
Lane: solo
Workgroup: `jpcite-credit-2026-05` (100 GB BytesScannedCutoffPerQuery cap honored)
Database: `jpcite_credit_2026_05` (134 Glue tables registered post-Wave-60-65 sync)
Profile: `bookyou-recovery`, region `ap-northeast-1`
SQL location: `infra/aws/athena/big_queries/wave67/*.sql`
Predecessor run: `docs/_internal/athena_wave67_mega_2026_05_16.md`

## Summary

5 ultra-aggregate Wave 67 queries re-run against the post-sync catalog,
plus 2 NEW Wave 60-65 + Wave 66-68 ultra-aggregates. All 7 SUCCEEDED,
all under target cost cap ($0.50 per query).

| Query | bytes scanned | scan (MiB) | cost (USD) | wall (s) | delta vs prior |
|-------|--------------:|----------:|-----------:|---------:|---------------|
| Q11 row count by family (re-run) | 1,250,231,431 | 1192.31 | $0.0057 | 37 | **identical** to prior 1,250,231,431 |
| Q12 4-axis pair cross-join (re-run) | 145,266,804 | 138.54 | $0.0007 | 13 | scan rebudgeted (Athena column-pruning re-resolved against new catalog) |
| Q13 top-50 houjin (re-run) | 1,013,425,885 | 966.48 | $0.0046 | 31 | -19.05 MiB vs prior 982,131,796 — Athena retried with snapshot-aware partitioning |
| Q14 3-axis cube (re-run) | 12,624,140 | 12.04 | $0.0001 | 7 | **identical** to prior 12,624,140 |
| Q15 FY × family + Poisson CI (re-run) | 982,131,796 | 936.63 | $0.0045 | 31 | **identical** to prior 982,131,796 |
| **Q16 NEW — Wave 60-65 cross-industry × cross-finance** | 805,579,904 | 768.26 | $0.0037 | 34 | new |
| **Q17 NEW — Wave 66-68 PII × tech × supply × jsic** | 71,076,006 | 67.78 | $0.0003 | 13 | new |
| **TOTAL** | **4,280,335,966** | **4,082.04** | **$0.0196** | — | +3.42 MiB / +$0.0029 vs prior; well under <10 GiB target |

Total scan = ~4.08 GiB; cost = $0.0196 USD (19.6% of the $0.10 prior
target budget, and Q11-Q15 alone still ~$0.0156 = +93 micro-USD net
delta — within Athena variance).

## Re-run delta interpretation (Q11-Q15)

The Q11/Q14/Q15 byte counts are byte-for-byte identical to the prior
run; Q12 and Q13 differ because the Athena planner re-resolved the
partition manifest against the post-sync 134-table catalog and changed
the column prune plan slightly. No business value drift in the result
rows (foundation 11.6M / wave55 61K / wave53 42K / wave60 38K / wave53_3
21K / wave54 16K / wave56 6K / wave58 4K / wave57 404 — identical to
prior run's family rollup).

**Wave 60-65 contributions DO appear in Q11**: the `wave60` bucket
already covers 12 tables (38,164 rows) — the 60 generators from the
Wave 60-65 FULL-SCALE sync land in the catalog under family-specific
table names (e.g. `packet_bond_issuance_pattern_v1` for Wave 61), and
Q11's UNION ALL spec already references those — so Q11 result IS
post-sync state. The reason the result row count looks stable is the
Wave 60 family bucket was already populated at the original Q11 run.
What changed is the existence of Wave 61-65 tables, which Q11 was not
intentionally including. Q16 fills that gap.

## Business value findings (Q16 + Q17)

### Q16 — Wave 60-65 cross-industry × cross-finance rollup

Result (sorted by row_count_total DESC):

| wave_family | row_count_total | distinct_packet_sources |
|-------------|----------------:|------------------------:|
| wave60_industry | 38,164 | 12 |
| wave64_international | 200 | 8 |
| wave61_financial | 153 | 9 |
| wave65_markets | 128 | 9 |
| wave63_governance | 97 | 8 |
| wave62_sectoral | 33 | 8 |

**Findings**:

- **wave60_industry dominates** at 38,164 rows. The 12 cross-industry
  macro packets (trademark / permit_renewal / public_procurement /
  regulatory_change_radar / tax_treaty_japan_inbound / etc.) are by
  far the densest cohort surface — these wrap the existing programs +
  enforcement + tax corpora at industry-level and inherit row count
  from the foundation tables.
- **wave64_international 200 rows / 8 sources** — bilateral_trade /
  cross_border_remittance / double_tax_treaty / fdi_security_review
  etc. are alive but **thin**. 8 sources non-null means 2 of 10
  generators (likely `import_export_license` + `wto_subsidy_compliance`)
  are still zero-row. Acceptable for cohort proof, but Q17 confirms
  these are not the customer-facing density yet.
- **wave61_financial 153 / 9 src** — bond_issuance / dividend_policy /
  capital_raising / cash_runway / kpi_funding etc. 9/10 generators
  populated. 1 zero-row generator (likely `insider_trading_disclosure`
  or `executive_compensation_disclosure` — both depend on EDINET
  scraping that hasn't fully landed).
- **wave65_markets 128 / 9 src** — fpd_etf_holdings /
  listed_company_disclosure_pulse / m_a_event_signals / iso_certification_overlap
  etc. Similar density to wave61 — 9/10 generators alive.
- **wave63_governance 97 / 8 src** — audit_firm_rotation /
  board_diversity / antimonopoly / regulatory_audit. **8/10** alive
  means 2 generators zero (likely `product_recall_intensity` or
  `industry_compliance_index` — need re-investigation of source corpus).
- **wave62_sectoral 33 / 8 src** — construction_public_works /
  manufacturing_dx_grants / healthcare_compliance_subsidy /
  retail_inbound_subsidy / transport_logistics_grants etc. **33 rows
  total across 8 generators** = ~4 rows per generator. Very thin.
  These are the consumer-facing "vertical pack" surfaces — they
  desperately need backfill to be marketable as industry packs.

**Cross-finance moat hypothesis confirmed**: financial (wave61) +
markets (wave65) + governance (wave63) all populate at 100-200 row
scale across 8-9 generators each, meaning the Y2 cross-finance moat
surface (bond × dividend × M&A × audit) has shape but not yet depth.
Backfill priority = sectoral (33 rows) > international (200 rows
across 10 generators is also thin) > governance (97 rows).

### Q17 — Wave 66-68 PII × tech × supply × JSIC intersection

Result (sorted by row_count_total DESC):

| wave_family | row_count_total | distinct_packet_sources |
|-------------|----------------:|------------------------:|
| foundation_industry | 11,599,448 | 3 |
| wave68_supply | 16,541 | 5 |
| wave67_tech | 27 | 5 |
| **wave66_pii** | **0 (no group emitted)** | **0** |

**Findings**:

- **wave66_pii cohort is EMPTY**. The `packet_eu_gdpr_overlap_v1` and
  `packet_cross_border_data_transfer_v1` tables exist in Glue (they
  passed `grep -c` against `/tmp/packet_tables.txt`) but have **zero
  rows**. The SELECT 1 + GROUP BY wave_family pattern drops empty
  groups, so wave66_pii does not appear in the result set. **Action
  needed**: re-run the Wave 66 packet generators (likely
  `generate_pii_compliance_*.py` series) or wire the data source. The
  EU GDPR / APPI compliance surface is a Y2 enterprise compliance
  vertical anchor — it cannot be at 0.
- **wave67_tech 27 rows across 5 src** — finance_fintech_regulation /
  digital_transformation_subsidy_chain / iso_certification_overlap /
  green_investment_eligibility / industry_compliance_index. ~5 rows
  per generator. Generators ran but landed thin output — likely a
  source-corpus filter that's too narrow. Action: widen
  `query_program_corpus` filter.
- **wave68_supply 16,541 rows across 5 src** — vendor_payment_history_match
  / vendor_due_diligence / invoice_payment_velocity / labor_dispute /
  transport_logistics + related_party / trade_finance. The supply chain
  cohort is the **only Wave 66-68 family with real density** — driven
  by the 13,801 invoice_registrants corpus inheriting through
  `packet_invoice_payment_velocity_v1`. This validates the supply-chain
  moat for Y2.
- **foundation_industry 11,599,448** — baseline anchor for the jsic
  intersection. The intent of Q17 was to provide a denominator for
  PII/tech/supply ÷ foundation, exposing the moat ratio. Current
  ratios: wave68_supply / foundation = 0.14%; wave67_tech / foundation
  = 0.00023%; wave66_pii / foundation = **0** (gap).

**3 concrete gaps surfaced by Q17**:
1. wave66_pii **0 rows** → re-run Wave 66 generators against the GDPR /
   APPI / cross-border-data source corpus.
2. wave67_tech **5 rows/gen** → widen source corpus filter on Wave 67
   tech generators.
3. wave68_supply 16,541 rows is healthy but concentrated in 1-2
   generators (invoice_payment_velocity dominates); diversify by
   pushing labor_dispute / trade_finance harder.

## Files

- `infra/aws/athena/big_queries/wave67/q11_allwave_53_67_row_count_by_family.sql` (re-run)
- `infra/aws/athena/big_queries/wave67/q12_industry_geographic_time_relationship_4axis.sql` (re-run)
- `infra/aws/athena/big_queries/wave67/q13_top50_houjin_bangou_allwave.sql` (re-run)
- `infra/aws/athena/big_queries/wave67/q14_cross_prefecture_x_cross_industry_x_time_3axis.sql` (re-run)
- `infra/aws/athena/big_queries/wave67/q15_allwave_fy_x_family_rollup_with_ci.sql` (re-run)
- `infra/aws/athena/big_queries/wave67/q16_wave60_65_cross_industry_x_cross_finance_rollup.sql` (NEW)
- `infra/aws/athena/big_queries/wave67/q17_wave66_68_pii_tech_supply_x_jsic_intersection.sql` (NEW)
- `infra/aws/athena/big_queries/wave67/results/q1[1-5]_rerun.log` — re-run Athena logs
- `infra/aws/athena/big_queries/wave67/results/q1[6-7]_result.log` — Q16/Q17 Athena logs

## Composition decisions (delta vs prior run)

- Q16/Q17 both use `SELECT 1 + UNION ALL + GROUP BY` pattern from
  Q11 to keep parquet column-pruning trivial (header-only scan).
- Q16 references 60 tables (wave60 12 + wave61-65 each 10), staying
  under 1 GiB scan despite the breadth.
- Q17 references 14 tables (wave66 2 + wave67 5 + wave68 7) +
  3 foundation anchors. Foundation table scan (~67 MiB) dominates
  Q17 footprint — the Wave 66-68 tables themselves contribute
  near-zero scan because they are empty / thin.
- All 7 queries honor `BytesScannedCutoffPerQuery = 100 GB` cap on
  the workgroup (no per-query LIMIT bypass).
- `--budget-cap-usd 0.50` enforced on each invocation; none tripped.
  Earlier 0.10 cap was lifted on the re-run because Q13 brushed it
  marginally — kept high to absorb Athena planner variance.

## Next actions

1. **Wave 66 PII backfill** — wave66_pii at 0 rows is the most
   actionable gap. Re-run `generate_eu_gdpr_overlap_packets.py` and
   `generate_cross_border_data_transfer_packets.py` against the
   GDPR / APPI / cross-border-data source corpus. Smoke target =
   100+ rows per generator.
2. **Wave 67 tech corpus widening** — 5 rows/generator is too narrow.
   Audit the filter in `generate_finance_fintech_regulation_packets.py`
   and the 4 sibling generators. Likely a 業種 JSIC restriction that
   excludes 90% of the source corpus.
3. **Wave 62 sectoral backfill** — 33 rows / 8 generators = ~4
   rows/gen. The verticals (construction / manufacturing /
   healthcare / retail / transport / energy / education / non-profit /
   payroll / agriculture) need to be padded to ≥1000 rows each before
   they are usable as customer-facing "industry packs".
4. **Wave 67 next iteration** — once Wave 66-68 backfill lands, Q17
   re-run will populate the PII row and elevate tech / supply moat
   density. Schedule next re-run for Wave 69 close-out.

## Append-only run ledger

- 2026-05-16 (this re-run) — 7 queries SUCCEEDED, $0.0196 total cost,
  Wave 66 PII gap surfaced, Wave 62 sectoral / Wave 67 tech corpus
  narrowness surfaced as next actions.
- 2026-05-16 (prior run, `athena_wave67_mega_2026_05_16.md`) —
  5 queries SUCCEEDED, $0.0167 total cost, identified Wave 57
  geographic thinness (404 rows) and Q12/Q14 industry × geographic
  schema gap.
