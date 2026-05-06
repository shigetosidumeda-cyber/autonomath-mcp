# Production Readiness Loop Handoff 2026-05-07

Status: NO-GO.

作成日時: 2026-05-07 JST

この文書は、本番前改善ループの引き継ぎ用メモである。production
deploy、stage、commit、secret変更、DB migration適用、cron有効化、
workflow有効化、live ingest、rollbackは承認しない。

## 2026-05-07 07:14 JST 最新ループ結果

本ループで、追加の本番前ブロッカーを実装修正した。自動検証側は green。
deploy可否は dirty tree と operator ACK のため引き続き NO-GO。

追加修正:

- Webhook dispatcher:
  失敗HTTP配信を課金しない形へ戻した。課金は外部endpointが2xxを返し、
  delivery/watch状態を先に耐久化した後だけ実行する。billing失敗時も
  2xx deliveryはdedup済みとして再送しないため、顧客への二重通知を避ける。
- Courses:
  課金失敗時に `course_subscriptions` の active row を残さないよう修正した。
  503後の再試行が duplicate active 409 で詰まらない。
- Recurring quarterly PDF:
  PDF render成功後にbillingし、billing成功後だけcacheへpromoteする順序へ修正した。
  render失敗では課金しない。billing失敗では顧客可視cacheを残さない。
- Production boot gate:
  `JPINTEL_ENV=prod/production` では `STRIPE_SECRET_KEY` に test-mode key
  (`sk_test_...`) を許さず、`sk_live_...` / `rk_live_...` のみ通す。

最新検証:

- 課金/配信/recurring/course関連:
  `55 passed, 1 warning`。
- boot/secret/Fly周辺:
  `44 passed`。
- A packet workflow pytest targets:
  `420 passed, 2 warnings`。
- A packet Ruff targets:
  `ruff check` pass、`ruff format --check` pass、target_count `16`。
- workflow YAML:
  `.github/workflows/test.yml`, `release.yml`, `deploy.yml` は `yaml.safe_load`
  pass。
- `pre_deploy_verify.py --preflight-db autonomath.db`:
  `3 pass / 0 fail / 3`、`ok: true`。
- `production_deploy_go_gate.py --warn-only`:
  `3 pass / 2 fail / 5`、`ok: false`。

最新NO-GO:

- `dirty_tree_present:1347`
- `operator_ack:not_provided_or_unreadable`
- current_head: `29d214b8fda6fa61459288aaf57b24964d8d9db6`
- status_counts: `{"??": 468, "A": 16, "D": 1, "M": 862}`
- critical lanes:
  `billing_auth_security`, `cron_etl_ops`, `migrations`, `root_release_files`,
  `runtime_code`
- path_sha256:
  `309d86cf29f387a17a4048dc2c645653a7e1ba3cc4cbf12a154a69baf9ad88c0`
- content_sha256:
  `7b1ae3a8a69124a51aa69c20bda17f8efac956c8eccada64d00c246fed0a5463`

残作業は「コードが落ちる」問題ではなく、dirty tree のpacket reviewと
operator ACK である。production deploy、secret変更、DB migration適用、
workflow dispatchはまだ行っていない。

## 2026-05-07 追加ループ結果

本ループで、本番deploy前に自動で潰せる P0/P1 を追加処理した。

- P0 API boot graph:
  `src/jpintel_mcp/api/main.py` の未追跡 experimental API router 群
  (`artifacts`, `audit_proof`, `calculator`, `eligibility_predicate`,
  `evidence_batch`, `intel_*`, `narrative`, `wave24_endpoints`) を
  top-level hard import から外し、
  `AUTONOMATH_EXPERIMENTAL_API_ENABLED=1` の時だけ `create_app()` 内で
  lazy include する形へ変更。default-off clean checkout では
  `create_app()` が `217` routes で起動する。
- P0 MCP boot graph:
  `autonomath_tools/__init__.py` の未追跡 experimental MCP module
  (`intel_wave31`, `wave24_tools_first_half`,
  `wave24_tools_second_half`) を default import から外し、
  `AUTONOMATH_EXPERIMENTAL_MCP_ENABLED=1` の時だけ import する形へ変更。
  flag-on は対象moduleを同一packetでgit管理対象にする必要がある。
- Webhook test rate limit:
  `_check_test_rate` を SQLite-backed に変更し、複数workerでも
  `5/min/webhook_id` を共有する。migration未適用時は legacy dict
  fallback。現行の autocommit接続では短い `BEGIN IMMEDIATE` で競合を
  抑止する。
- Courses:
  D+1即時送信のcap preflightをメール送信前に閉じ、外部メール送信中に
  SQLite writer lock を保持しない。課金不可なら送信・subscription・usageを
  残さない。送信後のusage書込失敗では再送ループを作らない。
- Recurring quarterly:
  PDFは一時ファイルへrenderし、billing成功後だけcacheへpromoteする。
  `HTTPException` / `sqlite3.Error` は顧客単位の `billing_failed` とし、
  後続顧客は継続。render/content failure は `render_failed` と分離。
- Webhook dispatcher:
  外部2xx配送後のdelivery/watch状態を先に耐久化し、billing失敗時も
  同一run内の後続配送を継続する。`billing_failures > 0` ならCLI exit code
  `1` で運用検知する。

追加検証:

- `uv run pytest ...` billing/delivery/courses/recurring/saved-search/webhook/
  autonomath billing/boot/main/fly focused suite: `104 passed, 2 warnings`.
- `uv run pytest tests/test_customer_webhooks_test_rate_persisted.py
  tests/test_boot_gate.py tests/test_main.py`: `34 passed`.
- `uv run ruff check ...`: pass.
- `uv run ruff format --check ...`: pass.
- `git diff --check ...`: pass.
- `uv run python scripts/ops/release_readiness.py --warn-only`:
  GO相当、`9 pass / 0 fail / 9`。
- `uv run python scripts/ops/pre_deploy_verify.py --warn-only`:
  GO相当、`3 pass / 0 fail / 3`。
- `uv run python scripts/ops/production_deploy_go_gate.py --warn-only`:
  NO-GO、`3 pass / 2 fail / 5`。残りは
  `dirty_tree_present:1347` と `operator_ack:not_provided_or_unreadable`。
- A packetに絞った workflow pytest targets:
  `420 passed, 2 warnings`。
- workflow targetはA packet向けに43 pytest targets / 16 Ruff targetsへ整理。
  `artifact`, `gBiz`, `PSF`, `OpenAPI/distribution`, eval系は Packet B/C へ
  分離した。A packet targetの未追跡ファイルは `git add -N`
  (intent-to-add) で release_readiness の tracking条件を検証済み。
  本commit時は通常の `git add` で内容をstageする必要がある。

## 参照した現行SOT

- `docs/_internal/PRODUCTION_DEPLOY_OPERATOR_ACK_DRAFT_2026-05-07.md`
- `docs/_internal/STRICT_METERING_HARDENING_VERIFICATION_2026-05-07.md`
- `docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md`
- `docs/_internal/CURRENT_SOT_2026-05-06.md`
- `docs/_internal/production_full_improvement_start_queue_2026-05-06.md`
- `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md`

## 実施済み修正

本番前改善ループで、少なくとも次の修正・強化がローカル作業ツリーに
積まれている。

- `deploy.yml` は `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` と
  `pre_deploy_verify` / `production_deploy_go_gate` を deploy 前 hard gate
  として要求する形に強化済み。
- `entrypoint.sh` の autonomath boot migration は
  `AUTONOMATH_BOOT_MIGRATION_MODE=manifest` 前提に寄せられ、空manifestでは
  production boot時にautonomath migrationを自動適用しない。
- `production_deploy_go_gate.py` は read-only の GO/NO-GO gate として、
  Fly app文脈、secret名レジストリ、migration target境界、dirty tree、
  operator ACKを検査する。
- `pre_deploy_verify.py` は `release_readiness`、
  `production_improvement_preflight`、`perf_smoke` を集約するローカル
  pre-deploy verifier として追加・運用されている。
- `release_readiness.py` は workflow の lint/test target がgit管理対象かを
  検査し、workflowだけ先に進む事故を止める。
- strict metering hardening は、paid endpointの最終cap失敗時に usage event
  を書かず fail closed する方向でテスト拡充済み。
- delivery/courses/recurring/saved-search/webhook のfail-closed副作用は、
  課金失敗時に未課金の顧客可視成果物を残さない方向へ修正済み。具体的には、
  course即時D+1は送信/購読作成前にcap preflight、recurring quarterly PDFは
  一時ファイルへrender後にmetering成功時だけcacheへpromote、saved search
  resultsは `strict_metering=True`、webhook dispatchは外部2xx後の配送状態と
  watch状態を先に耐久化して再送を防ぎ、その後のbilling失敗はcron失敗として
  opsに上げる。
- paid artifact は audit seal persistence 失敗時に bodyを返さず
  `503 audit_seal_persist_failed` とし、usage eventを書かない設計で検証済み。
- APPI intake/deletion は production helper/boot gateで、APPI有効時に
  `CLOUDFLARE_TURNSTILE_SECRET` 不在なら fail closed する方向に寄せられている。
- gBiz v2 ingest は corporate/subsidy/certification/commendation/procurement
  のpagination、schema preflight、dry-run、rate-limit、attribution、
  per-houjin rollback、delta update reportingがローカル検証対象になっている。
- `company_public_audit_pack` 系の source receipt は `source_url`、
  `source_fetched_at`、`content_hash`、`license`、`used_in` を監査材料として扱い、
  欠損は `known_gaps` / `human_review_required` に出す方針になっている。
- migration target/danger gate は `wave24_164_gbiz_v2_mirror_tables.sql` を
  `autonomath`、`wave24_166_credit_pack_reservation.sql` を `jpintel` として
  扱い、dirty forward migrationの target宣言と危険SQLを検査する。
- P0 API boot graphはdefault-off lazy includeへ寄せた。experimental APIを
  本番公開する場合は、対象module群とmigration/schema/generatorを同一packetで
  git管理対象にする必要がある。

## 検証結果

既存SOTに記録されたローカル検証結果は次の通り。ここにある green は
deploy許可ではなく、ローカル実装証跡である。

- strict metering major endpoint bundle: `166 passed` reported.
- strict metering core API bundle: `70 passed` reported.
- invoice/laws/enforcement/case/calendar bundle: `72 passed` reported.
- court/source/saved bundle: `26 passed` reported.
- AutonoMath/evidence/ping bundle: `18 passed` reported.
- M00-D billing/security focused suite: `69 passed` reported.
- credit pack focused suite: `19 passed` reported.
- billing webhook regression suite: `20 passed` reported.
- delivery/courses/recurring/saved-search/webhook fail-closed side-effect
  integration suite: `63 passed` reported.
- gBiz attribution/field/compact/ingest contract suite: `33 passed` reported.
- gBiz monthly workflow static contract: `5 passed` reported.
- distribution static/runtime/tool-count checks: reported OK at 139 tools,
  269 routes, 227 OpenAPI paths.
- production improvement preflight + perf smoke: reported local pass with
  `/healthz` 約80 ms、`/v1/programs/search` 約423 ms、`/v1/meta` 約84 ms。
- 2026-05-07 07:15 JST 最新NO-GO観測:
  - `production_deploy_go_gate.py --warn-only`: NO-GO、`3 pass / 2 fail / 5`。
  - `pre_deploy_verify.py --preflight-db autonomath.db`: GO、`3 pass / 0 fail / 3`。
  - A packet workflow pytest targets: GO、`420 passed, 2 warnings`。
  - 現時点の機械的NO-GOは
    `dirty_tree_present:1347`、`operator_ack:not_provided_or_unreadable`。

## 現在のNO-GO理由

本番deployは現時点でNO-GO。理由は次の通り。

- dirty treeが広範囲に存在する。現時点のgate観測では
  `dirty_tree_present:1347`。
- critical dirty lanes に `billing_auth_security`, `cron_etl_ops`,
  `migrations`, `root_release_files`, `runtime_code` が含まれる。
- final operator ACK が存在しない。draftはdeploy承認でも最終ACKでもない。
- `pre_deploy_verify_clean` は機械的には true にできる状態だが、
  final ACKで人間が確認していないため未承認。
- machine-levelのNO-GOは現時点で
  `dirty_tree_present:1347`、`operator_ack:not_provided_or_unreadable`。
- workflow参照先のlint/test targetは `release_readiness` 上は green。
  ただし A packet targetの一部は intent-to-add 由来なので、最終commit時に
  実体をstageする必要がある。
- P0 API boot graph上の未追跡moduleが残る。`main.py` がimportするAPI
  router moduleをcommit対象から漏らすと、container boot時に
  `ModuleNotFoundError` またはroute欠落として現れる。
- migration/cron/workflowの変更が大きく、deploy packet単位で承認されていない。
- production secret名の最終確認、APPI disabledまたはTurnstile secret確認、
  live gBiz ingestの無効化または明示承認が未完了。
- rollback reconciliation packet、とくに credit pack reservation rollback時の
  Stripe balance transaction / idempotency evidence確認が未完了。
- Docker/Fly build contextとproduction boot時migration挙動の最終レビューが
  未完了。

## deploy前の次アクション

次の順で進める。deploy、stage、commitはこの文書では行わない。

1. `git status --short` を取り直し、dirty laneを deploy対象、後続、
   生成物、削除確認に分ける。
2. workflow参照先の未追跡 lint/test target を、workflow変更と同じpacketで
   commit対象にするか、workflow targetから外すかを決める。
3. P0 API boot graphの未追跡moduleを、`main.py` に残すもの、feature flagや
   optional importに戻すもの、後続packetへ分離するものに分類する。
4. `uv run python scripts/ops/release_readiness.py --warn-only` を再実行し、
   `workflow_targets_git_tracked` が green になる条件を固定する。
5. `uv run python scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db`
   を deploy packet直前に warningなしで通す。
6. migration packetを target DB別に分割し、runner、rollback、reconciliation
   を明記する。
7. `scripts/migrations/autonomath_boot_manifest.txt` は空allowlistを維持する。
   非空化または `AUTONOMATH_BOOT_MIGRATION_MODE=discover` はproduction DB
   mutationとして、migration packet内で個別承認する。
8. cron/workflow packetを、本番で有効化するもの、manual onlyのもの、
   docs/testだけのものに分ける。
9. production secret名を `autonomath-api` 上で名前だけ確認する。値はdocs、
   log、chat、gitに書かない。
10. APPIを明示的に無効化するか、`CLOUDFLARE_TURNSTILE_SECRET` の存在を
   名前だけ確認する。
11. live gBiz ingestを無効のままにするか、operatorが app名、secret配置、
   migration境界を承認した上で有効化する。
12. final ACKはrepo外に作り、全8 booleanを実際の確認後だけ `true` にする。
13. `--allow-dirty` を使う場合は、全編集完了後の
    `dirty_tree_fingerprint` を最終 gate出力からコピーし、critical lane
    reviewを明記する。
14. 最後に `uv run python scripts/ops/production_deploy_go_gate.py
    --operator-ack /tmp/jpcite_operator_deploy_ack_YYYY-MM-DD.json` が
    `"ok": true` になることを確認する。

## R8別CLIで実行可

R8別CLIは、production mutationを伴わない調査・検証だけ実行可。

- `git status --short`、`git diff --name-status`、`git diff --stat` の read-only
  確認。
- `rg` / `git ls-files` / `git diff --check` による対象確認。
- `uv run pytest ...` のローカル再実行。ただし外部API、live secret、
  production DBを使わない範囲に限る。
- `uv run python scripts/ops/release_readiness.py --warn-only`。
- `uv run python scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db
  --warn-only`。
- `uv run python scripts/ops/production_deploy_go_gate.py --warn-only`。
- R8 dataset versioning関連は、`tests/test_r8_dataset_versioning.py` の
  ローカル確認と docs確認のみ可。
- migration/cron/workflowの一覧化、target DB分類、承認待ち表の作成。
- `docs/_internal/` の別handoffや監査メモ作成。ただし同じ編集範囲制約が
  与えられている場合はそれを優先する。

## R8別CLIで禁止

R8別CLIは、次を実行しない。

- `git add`, `git commit`, `git push`, tag作成、release作成。
- `fly deploy`, `flyctl deploy`, Fly machine restart、rollback、scale変更。
- `fly secrets set` / `unset`、secret値の表示・記録・貼り付け。
- production DBまたは `/data/*.db` への `sqlite3` 書き込み、migration apply、
  rollback SQL適用。
- `AUTONOMATH_BOOT_MIGRATION_MODE=discover` または非空manifestを使う
  production boot。
- GitHub Actions workflowの有効化、schedule有効化、manual dispatch実行。
- live gBiz API ingest、EDINET等のlive token前提の本番取り込み。
- `site/`, OpenAPI, MCP, SDK, DXT等の生成物を一括更新してdeploy判断を混ぜる。
- R8 dataset versioningのproduction flag有効化、snapshot migration適用、
  `AUTONOMATH_SNAPSHOT_ENABLED` の本番設定変更。
- dirty treeの他人変更をrevert、cleanup、format、移動すること。

## migration承認対象

承認前に、target DB、runner、rollback、data loss、reconciliationを行単位で
確認する。

| 対象 | 現状/リスク | 承認条件 |
| --- | --- | --- |
| `wave24_164_gbiz_v2_mirror_tables.sql` | `autonomath` target。gBiz live ingestと結びつく | app名、secret配置、live ingest可否、rollback方針を承認 |
| `wave24_166_credit_pack_reservation.sql` | `jpintel` target。rollbackはidempotency evidence削除リスク | Stripe balance transaction確認と事前reconciliation SQLを承認 |
| `172`-`176` 系 source foundation | 現DB適用状態の固定が必要 | runtime `schema_migrations` と target DBを照合 |
| `177`以降 / `wave24_17x` 系 | 番号衝突と複数レーン混在リスク | PSF、Evidence Packet、derived dataをpacket分離 |
| rollback SQL全般 | 一部は破壊的 | automatic不可。operator-onlyで影響表を作る |
| `autonomath_boot_manifest.txt` | コメントのみの空allowlist。`AUTONOMATH_BOOT_MIGRATION_MODE=manifest` ではboot自動適用0件 | 空を維持。非空化またはdiscover modeはproduction DB mutationとして個別承認 |

## cron承認対象

cronは「scriptが存在する」ことと「本番でscheduleする」ことを分ける。

| 対象 | 承認前の扱い | 承認条件 |
| --- | --- | --- |
| gBiz monthly/delta ingest | live ingest NO-GO | `GBIZINFO_API_TOKEN` 配置、rate limit、DB target、failure通知を承認 |
| offline inbox ingest | manual/read-only evidence優先 | 書込先、force retag、rollback、audit logを承認 |
| precompute actionable/recommended/calendar | deployとは別packet | source freshness、cache invalidation、migration依存を承認 |
| narrative audit/SLA/report系 | operator/offline lane | 通知先、PII、customer report公開範囲を承認 |
| refresh sources daily/weekly | source foundation lane | host allowlist、TOS/license、R2/WARC方針を承認 |
| merkle/audit seal rotation系 | billing/security lane | key version、seal persistence、rollback手順を承認 |

## workflow承認対象

workflowは、target追跡、secret参照、schedule、deploy mutationの4点で承認する。

| 対象 | 現状/リスク | 承認条件 |
| --- | --- | --- |
| `deploy.yml` | ACK/gate強化済みだがdeploy mutation本体 | final ACK、pre_deploy green、GO gate greenが必須 |
| `test.yml` / `release.yml` | lint/test targetの未追跡問題 | `workflow_targets_git_tracked` green |
| `gbiz-ingest-monthly.yml` | live ingestにつながる | manual/schedule、Fly SSH、secret名、DB targetを承認 |
| refresh/precompute/populate系 workflows | cron mutationにつながる | schedule有効化前にscript、migration、rollbackを承認 |
| trust/practitioner/narrative publish系 | public artifact公開につながる | 出力先、PII、license、human reviewを承認 |
| distribution/openapi workflows | public surface driftリスク | OpenAPI/MCP/site/SDK/DXTを一括packet化 |

## 引き継ぎメモ

- deploy判断はローカルpytest greenだけでは足りない。dirty tree、operator ACK、
  migration/cron/workflow承認が揃うまでNO-GOを維持する。
- `63 passed` の統合テスト証跡は、fail-closed副作用修正の実装証跡であり、
  deploy承認ではない。
- final ACKはこのrepoに完成版を置かない。draftをそのまま使わない。
- `--warn-only` は証跡収集用であり、GO判定ではない。
- 他人の変更を戻さない。packet化できない変更は後続レーンに残す。
- P0 API boot graphはrelease packetの最初に片付ける。未追跡moduleを
  `main.py` import graphに残したままdeploy imageを作らない。
- 本文書自体は `docs/_internal/` の新規md 1ファイルであり、deploy承認ではない。
