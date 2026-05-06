# W22 Inbox Quality Audit

- run_at: `2026-05-05T03:47:14.678806+00:00`
- inbox_root: `/Users/shigetoumeda/jpcite/tools/offline/_inbox`
- files: active=22, archived=212, done=1, total=235
- rows_total: **2434**

## 1. URL duplicates
- unique_urls: 2416
- duplicate_urls (>=2 occurrences): **11**
- extra duplicate rows (sum of count-1): 11

Top duplicates:
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/040219/01.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/110427/index.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/141027/kaisei.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/070622/01.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/160425/index.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/190222/index.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/130325/index.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/20180606/index.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/160412/index.htm`
  - x2 `https://www.nta.go.jp/law/tsutatsu/kobetsu/kansetsu/1806xx_2/index.htm`

## 2. content_hash uniqueness
- unique_hashes: 2417
- duplicate_hashes: **10**
- extra duplicate rows: 10

Top hash duplicates:
  - x2 `sha256:6db40e1792d030ec8bbf42ec0f96780c4184e302a5ae4b7e122d9bb4abc6e7e4`
  - x2 `sha256:6c3f06479177f37c1da49e7ff1a0b16f48bd8b90416e8ddea021761b3d5fd213`
  - x2 `sha256:7b3d08e09bc2c0e72d5724c62b6ec3274f2066a039aa166e88949113d7ee5e2c`
  - x2 `sha256:93f8c82d5c3e851154516d048ca68449bf89a39ccd673b02862675a8a2724db8`
  - x2 `sha256:1a966e79d5d45b9b9af1370c1840373eb75e2ab8f13b77a83cd5dba3a50da8ab`
  - x2 `sha256:1ba603c7cd04ec147fa9503daabb072bda4e770ec407fa57ab7119cfa96746d1`
  - x2 `sha256:45cbc9cd3b63501d50b147c62db4a21ec663d5ec5593628991cc9b11d67881a4`
  - x2 `sha256:fd9fb8f5058f4fd515847c81fdf936919938e74e7dc15d185497b420bf5e80d4`
  - x2 `sha256:31b6ae78e5fd42b120f0d4a99bd1da86a326e457c8008ffbb8900c71259c437c`
  - x2 `sha256:db5924196a172c36e842ca73168fe5f72596fd223849cd11a4162ec7fa486065`

## 3. License validity
- valid set: `cc_by_4.0, gov_standard, pdl_v1.0, proprietary, public_domain, unknown`
- invalid license rows: **0**

Distribution:
  - `cc_by_4.0`: 2227
  - `gov_standard`: 200
  - `<missing>`: 7  <- INVALID

## 4. Empty / short body
- empty_body_count: **8**
- short_body_count (<50 chars): **0**

Empty samples (first 10):
  - `jsic_classification/2026-05-04-trial.jsonl:1` source=`` url=``
  - `jsic_classification/2026-05-04-trial.jsonl:2` source=`` url=``
  - `_archived/egov_law_articles/2026-05-05_iter17_agent3.jsonl:10` source=`egov_law_articles` url=`https://laws.e-gov.go.jp/api/2/law_data/325M50000002025?law_full_text_format=json`
  - `program_narrative/_done/2026-05-04-trial.jsonl:1` source=`` url=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:2` source=`` url=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:3` source=`` url=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:4` source=`` url=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:5` source=`` url=``

## 5. HTTP status distribution
- pct_200: **99.96%**

Distribution:
  - `200`: 2426
  - `<missing>`: 7
  - `0`: 1

## 6. Aggregator (詐欺リスク source) detection
- blocklist domains: `noukaweb, hojyokin-portal, biz.stayway, mirasapo-plus, j-net21`
- matched rows: **0**
- **CLEAN: 0 aggregator hits.**

## 7. Timestamp validity (ISO-8601 + within 30d)
- invalid_iso: **7**
- stale (older than 30d) or future (>24h ahead): **0**
- threshold_30d_ago: `2026-04-05T03:47:14.678806+00:00`

Invalid ts samples:
  - `jsic_classification/2026-05-04-trial.jsonl:1` fetched_at=``
  - `jsic_classification/2026-05-04-trial.jsonl:2` fetched_at=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:1` fetched_at=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:2` fetched_at=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:3` fetched_at=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:4` fetched_at=``
  - `program_narrative/_done/2026-05-04-trial.jsonl:5` fetched_at=``

## 8. Dir row counts vs progress.json

### Per-directory row counts (active+archived+done)
| dir | rows |
|---|---:|
| `egov_law_articles` | 2227 |
| `nta_tsutatsu_full` | 200 |
| `_done` | 5 |
| `jsic_classification` | 2 |

### Per-source progress.json vs actual inbox row count
| source_id | status | progress_completed | progress_total | pct | inbox_rows(by source_id) | delta |
|---|---|---:|---:|---:|---:|---:|
| `egov_law_articles` | in_progress | 2226 | 9484 | 23.47% | 2227 | 1 |
| `nta_tsutatsu_full` | pending | 0 | 3000 | 0.0% | 200 | 200 |
| `nta_kfs_saiketsu` | pending | 0 | 10000 | 0.0% | 0 | 0 |
| `courts_hanrei` | pending | 0 | 50000 | 0.0% | 0 | 0 |
| `jftc_dk` | pending | 0 | 500 | 0.0% | 0 | 0 |
| `fsa_admin_disposal` | pending | 0 | 2000 | 0.0% | 0 | 0 |
| `kokkai_minutes` | pending | 0 | 100000 | 0.0% | 0 | 0 |
| `estat_api` | pending | 0 | 30000 | 0.0% | 0 | 0 |
| `geps_bids` | pending | 0 | 50000 | 0.0% | 0 | 0 |
| `egov_public_comment` | pending | 0 | 30000 | 0.0% | 0 | 0 |
| `egov_law_translation` | pending | 0 | 700 | 0.0% | 0 | 0 |
| `invoice_kohyo_zenken` | pending | 0 | 1 | 0.0% | 0 | 0 |
| `erad_rd` | pending | 0 | 50000 | 0.0% | 0 | 0 |
| `maff_excel` | pending | 0 | 100 | 0.0% | 0 | 0 |
| `meti_subsidy` | pending | 0 | 3000 | 0.0% | 0 | 0 |
| `pref_subsidy` | pending | 0 | 50000 | 0.0% | 0 | 0 |
| `pref_giji` | pending | 0 | 100000 | 0.0% | 0 | 0 |
| `city_giji` | pending | 0 | 500000 | 0.0% | 0 | 0 |
| `mof_tax_treaty` | pending | 0 | 80 | 0.0% | 0 | 0 |
| `industry_certification` | pending | 0 | 800 | 0.0% | 0 | 0 |

## Parse errors
- count: **0**

## Verdict
- **REVIEW** issues: URL dups: 11, empty bodies: 8, ts issues: 7
