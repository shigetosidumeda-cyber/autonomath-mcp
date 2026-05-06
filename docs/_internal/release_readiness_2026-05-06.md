# Release Readiness 2026-05-06

## Pre-deploy local verification

Deploy直前のローカル検証は次の1コマンドに集約する。

```bash
python3 scripts/ops/pre_deploy_verify.py
```

このラッパーはローカルファイルとローカルTestClientベースの軽量チェックだけを実行し、外部ネットワークや破壊操作は行わない。内部では次を順に呼び出し、全結果をJSONで集約する。

- `scripts/ops/release_readiness.py --warn-only`
- `scripts/ops/preflight_production_improvement.py --warn-only --json`
- `scripts/ops/perf_smoke.py --samples 1 --warmups 0 --threshold-ms 10000 --json`

検証結果がNGでもJSONだけ確認したい場合は次を使う。

```bash
python3 scripts/ops/pre_deploy_verify.py --warn-only
```
