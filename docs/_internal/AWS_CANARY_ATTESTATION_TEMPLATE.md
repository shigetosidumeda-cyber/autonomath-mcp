# AWS Canary Attestation Template (2026-05-16)

## 目的
AWS canary 実行 (Stream I) 完了後、operator が **非 AWS environment** で attestation JSON を生成。Wave 50 RC1 = AWS の credit 完全消費 + 後片付け完了の証跡。Ed25519 署名により tamper-evident、公開後 anyone が verify 可能。

## attestation schema (`jpcite.aws_canary_attestation.p0.v1`)

```json
{
  "schema_version": "jpcite.aws_canary_attestation.p0.v1",
  "attestation_id": "uuid",
  "canary_run_id": "uuid (matches scripts/teardown/run_all.sh RUN_ID)",
  "operator_pubkey_fingerprint": "ed25519:xxxx",
  "signature": "ed25519:yyyy (signed payload)",
  "signed_payload": {
    "aws_account_id": "993693061769",
    "aws_region": "us-east-1",
    "credit_consumed_usd": 19490,
    "non_credit_exposure_usd": 0,
    "live_aws_commands_executed": true,
    "live_aws_commands_completed_at": "2026-XX-XXTXX:XX:XXZ",
    "teardown_completed_at": "2026-XX-XXTXX:XX:XXZ",
    "post_teardown_attestation_verified": true,
    "preflight_state_at_start": "AWS_CANARY_READY",
    "preflight_state_at_end": "AWS_CANARY_COMPLETED",
    "spend_breakdown": {
      "s3_artifact_lake": 4800,
      "batch_playwright": 6200,
      "bedrock_ocr": 3700,
      "opensearch_index": 2800,
      "other": 1990
    },
    "artifacts_generated": {
      "source_receipt_lake_rows": 100000,
      "playwright_screenshots": 5000,
      "ocr_extracted_pages": 8000,
      "proof_pages": 150
    },
    "verify_zero_aws_passed_at": "2026-XX-XXTXX:XX:XXZ",
    "verify_zero_aws_summary": {
      "s3_buckets_remaining": 0,
      "batch_jobs_remaining": 0,
      "ecs_services_remaining": 0,
      "bedrock_throughputs_remaining": 0,
      "opensearch_domains_remaining": 0,
      "ec2_instances_remaining": 0,
      "rds_dbs_remaining": 0,
      "lambda_functions_remaining": 0,
      "eventbridge_rules_remaining": 0
    }
  }
}
```

## 生成手順 (非 AWS environment で実行)

```bash
# 1. canary 実行ログから data 収集
RUN_ID=<from scripts/teardown/run_all.sh>
cat /Users/shigetoumeda/jpcite/site/releases/$RUN_ID/teardown_attestation/*.json | jq -s

# 2. signed_payload を Python で構築 (template に値埋め)
python3 scripts/ops/build_canary_attestation.py --run-id $RUN_ID --output /tmp/attestation_unsigned.json

# 3. Ed25519 で署名 (operator が個人鍵で)
python3 scripts/ops/sign_canary_attestation.py --input /tmp/attestation_unsigned.json --output site/releases/rc1-p0-bootstrap/aws_canary_attestation.json

# 4. commit + push (Stream G に含めるか、別 PR で landing)
git add site/releases/rc1-p0-bootstrap/aws_canary_attestation.json
git commit -m "attest: AWS canary RUN_ID=$RUN_ID, USD 19,490 consumed, 0 residual"
git push origin main
```

## verify (公開後、anyone)

```bash
# public key fingerprint で署名検証
curl https://jpcite.com/releases/current/aws_canary_attestation.json | python3 -c "..."
```

## sample (mock-signed)

```json
{
  "schema_version": "jpcite.aws_canary_attestation.p0.v1",
  "attestation_id": "TEMPLATE_EXAMPLE_NOT_REAL",
  "canary_run_id": "MOCK_RUN_ID_PLACEHOLDER",
  "operator_pubkey_fingerprint": "ed25519:MOCK_FINGERPRINT_PLACEHOLDER",
  "signature": "ed25519:MOCK_SIGNATURE_PLACEHOLDER",
  "signed_payload": {
    "aws_account_id": "993693061769",
    "aws_region": "us-east-1",
    "credit_consumed_usd": 19490,
    "non_credit_exposure_usd": 0,
    "live_aws_commands_executed": true,
    "preflight_state_at_end": "AWS_CANARY_COMPLETED",
    "verify_zero_aws_summary": {
      "s3_buckets_remaining": 0,
      "batch_jobs_remaining": 0,
      "ecs_services_remaining": 0,
      "bedrock_throughputs_remaining": 0,
      "opensearch_domains_remaining": 0
    }
  }
}
```

## SOT
- `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
- `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md`
- `WAVE50_CLOSEOUT_2026_05_16.md`

---
last_updated: 2026-05-16
