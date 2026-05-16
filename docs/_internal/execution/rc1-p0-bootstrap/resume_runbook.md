# RC1 P0 Bootstrap Resume Runbook

This runbook is the human-readable companion to `execution_state.json`. Treat
the JSON file as the source of truth for resuming after Codex or Claude rate
limits.

## Current Phase

- Phase: `local_preflight_contracts`
- Status: `blocked_before_aws_preflight`
- Live AWS: disabled
- Mutating AWS: disabled
- Scorecard: `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`

## Resume Commands

Run from repo root `/Users/shigetoumeda/jpcite`:

```sh
.venv/bin/python scripts/ops/check_execution_resume_state.py
.venv/bin/python scripts/ops/aws_credit_local_preflight.py --warn-only
.venv/bin/pytest -q tests/test_execution_resume_state.py tests/test_aws_credit_local_preflight.py
jq '.state, .live_aws_commands_allowed, .blocking_gates' site/releases/rc1-p0-bootstrap/preflight_scorecard.json
```

Expected state today:

- `execution resume state: ok`
- `gate_state` remains `AWS_BLOCKED_PRE_FLIGHT`
- `live_aws_commands_allowed` remains `false`
- blocking gates remain listed until preflight, spend, and teardown gates pass

## Stop Conditions

Stop before any live AWS command if any of these is true:

- `execution_state.json` has `live_aws.enabled: true` while preflight status is not passed.
- `preflight_scorecard.json` has `live_aws_commands_allowed: true` while state is not `AWS_CANARY_READY`.
- A resume command starts with `aws ` or declares `mutating_aws: true`.
- Cash-bill guard, spend simulation, or teardown simulation is missing.
- AWS credentials or profile changes are required.

## Scope

Allowed before preflight:

- docs and runbooks
- local scripts and validators
- fixtures and tests
- schema and release-capsule contract checks
- local CSV sample audits such as `csv_sample_audit.md`
- service delta notes such as `current_service_delta.md`

Not allowed before preflight:

- AWS credential changes
- resource creation or queue submission
- Batch, Bedrock, Textract, OpenSearch, ECS, ECR, S3, Glue, Athena, IAM, or
  CloudFormation live commands
- production deploys that depend on temporary AWS artifacts
