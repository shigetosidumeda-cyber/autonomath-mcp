"""Lane F — OpenSearch r5.4xlarge domain + Dim O explainable_fact bulk indexer.

Wave 50+ AWS canary burn (Lane F)
==================================

Spins up an OpenSearch r5.4xlarge.search single-node domain
``jpcite-explainable-fact-2026-05`` and bulk-indexes 35 K explainable
facts derived from ``autonomath.db`` (``am_entity_facts`` + Dim O 4-axis
envelope: source_doc / extracted_at / verified_by / confidence). The
domain alone burns **~$36/day** (r5.4xlarge.search hourly ~$1.50 ×
24h + EBS gp3 100 GB ~$0.10/day).

Operational model
-----------------
* Single-AZ (intentionally — this is a burn-purpose domain, not
  production). The dim O facts can be re-indexed from autonomath.db on
  demand if the domain is torn down.
* Node-to-node encryption + encryption-at-rest enabled (security
  defaults, not a performance trade-off).
* Bulk index batch size = 1000 docs; ~35 batches for 35 K rows.
* Index name: ``explainable-fact-2026-05``.
* Once indexed, the domain serves the Dim O verification surface
  (``services/math_engine/sweep.py`` etc. would point at it).

Constraints
-----------
* $19,490 Never-Reach budget cap respected externally; this script does
  NOT perform budget checks itself.
* Each invocation has 4 phases (each is opt-in via flag):
    --create        create the domain (returns immediately; ACTIVE in 10-20 min)
    --wait          poll until Processing==False (blocks ≤25 min)
    --index         bulk-index 35K explainable facts
    --status        print domain status + endpoint
* Default behavior with no flags = ``--status`` (read-only).

Usage
-----
::

    # Full flow (run once, then re-invoke with --wait+--index after 15 min)
    python scripts/aws_credit_ops/opensearch_index_explainable_facts_2026_05_17.py \
        --create

    python scripts/aws_credit_ops/opensearch_index_explainable_facts_2026_05_17.py \
        --wait --index

    # Status only
    python scripts/aws_credit_ops/opensearch_index_explainable_facts_2026_05_17.py \
        --status
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import sqlite3
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

_UTC = _dt.UTC

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"

DEFAULT_PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
DEFAULT_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "993693061769")

DOMAIN_NAME = os.environ.get(
    # Max 28 chars per AWS OpenSearch DomainName constraint.
    "JPCITE_OS_DOMAIN_NAME",
    "jpcite-xfact-2026-05",
)
ENGINE_VERSION = os.environ.get("JPCITE_OS_ENGINE_VERSION", "OpenSearch_2.13")
INSTANCE_TYPE = os.environ.get("JPCITE_OS_INSTANCE_TYPE", "r5.4xlarge.search")
INSTANCE_COUNT = int(os.environ.get("JPCITE_OS_INSTANCE_COUNT", "1"))
EBS_VOLUME_GB = int(os.environ.get("JPCITE_OS_EBS_GB", "100"))
INDEX_NAME = os.environ.get("JPCITE_OS_INDEX_NAME", "explainable-fact-2026-05")
TARGET_ROWS = int(os.environ.get("JPCITE_OS_TARGET_ROWS", "35000"))
BULK_BATCH = int(os.environ.get("JPCITE_OS_BULK_BATCH", "1000"))


def _import_boto3() -> Any:
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]

        return boto3
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("boto3 not installed; pip install boto3") from exc


def _session(profile: str, region: str) -> Any:
    return _import_boto3().Session(profile_name=profile, region_name=region)


def _access_policy(account_id: str, region: str, domain: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{account_id}:user/bookyou-recovery-admin"},
                    "Action": "es:*",
                    "Resource": (f"arn:aws:es:{region}:{account_id}:domain/{domain}/*"),
                }
            ],
        }
    )


def cmd_create(session: Any, region: str) -> dict[str, Any]:
    """Create the OpenSearch domain. Idempotent: returns existing if present."""
    es = session.client("opensearch")
    try:
        existing = es.describe_domain(DomainName=DOMAIN_NAME)
        status = existing["DomainStatus"]
        endpoint = status.get("Endpoint") or status.get("Endpoints", {}).get("vpc")
        return {
            "action": "ALREADY_EXISTS",
            "domain": DOMAIN_NAME,
            "processing": status.get("Processing"),
            "endpoint": endpoint,
            "arn": status.get("ARN"),
        }
    except es.exceptions.ResourceNotFoundException:
        pass

    resp = es.create_domain(
        DomainName=DOMAIN_NAME,
        EngineVersion=ENGINE_VERSION,
        ClusterConfig={
            "InstanceType": INSTANCE_TYPE,
            "InstanceCount": INSTANCE_COUNT,
            "ZoneAwarenessEnabled": False,
            "DedicatedMasterEnabled": False,
        },
        EBSOptions={
            "EBSEnabled": True,
            "VolumeType": "gp3",
            "VolumeSize": EBS_VOLUME_GB,
        },
        NodeToNodeEncryptionOptions={"Enabled": True},
        EncryptionAtRestOptions={"Enabled": True},
        DomainEndpointOptions={
            "EnforceHTTPS": True,
            "TLSSecurityPolicy": "Policy-Min-TLS-1-2-2019-07",
        },
        AccessPolicies=_access_policy(ACCOUNT_ID, region, DOMAIN_NAME),
        AdvancedSecurityOptions={
            "Enabled": False,
            "InternalUserDatabaseEnabled": False,
        },
        TagList=[
            {"Key": "Project", "Value": "jpcite"},
            {"Key": "CreditRun", "Value": "2026-05"},
            {"Key": "Lane", "Value": "F"},
        ],
    )
    status = resp["DomainStatus"]
    return {
        "action": "CREATED",
        "domain": DOMAIN_NAME,
        "processing": status.get("Processing"),
        "arn": status.get("ARN"),
    }


def cmd_status(session: Any) -> dict[str, Any]:
    es = session.client("opensearch")
    try:
        info = es.describe_domain(DomainName=DOMAIN_NAME)
    except es.exceptions.ResourceNotFoundException:
        return {"domain": DOMAIN_NAME, "exists": False}
    status = info["DomainStatus"]
    endpoint = status.get("Endpoint") or status.get("Endpoints", {}).get("vpc")
    return {
        "domain": DOMAIN_NAME,
        "exists": True,
        "processing": status.get("Processing"),
        "endpoint": endpoint,
        "arn": status.get("ARN"),
        "engine_version": status.get("EngineVersion"),
        "instance_type": status.get("ClusterConfig", {}).get("InstanceType"),
        "instance_count": status.get("ClusterConfig", {}).get("InstanceCount"),
        "ebs_volume_size_gb": status.get("EBSOptions", {}).get("VolumeSize"),
    }


def cmd_wait(session: Any, max_wait_sec: int = 1500) -> dict[str, Any]:
    """Poll describe_domain until Processing == False."""
    es = session.client("opensearch")
    start = time.monotonic()
    while time.monotonic() - start < max_wait_sec:
        info = es.describe_domain(DomainName=DOMAIN_NAME)
        st = info["DomainStatus"]
        if not st.get("Processing"):
            endpoint = st.get("Endpoint") or st.get("Endpoints", {}).get("vpc")
            return {"state": "READY", "endpoint": endpoint, "arn": st.get("ARN")}
        time.sleep(30)
    return {"state": "TIMEOUT", "elapsed_sec": int(time.monotonic() - start)}


def _load_facts_for_indexing(db_path: pathlib.Path, limit: int) -> Iterable[dict[str, Any]]:
    """Pull explainable_fact rows from autonomath.db.

    Strategy: ``am_entity_facts`` (6.12 M rows) joined with the Dim O 4-axis
    envelope where present (source_id → am_source.url for source_doc;
    created_at for extracted_at; "cron_etl_v3" default verified_by;
    confirming_source_count -> confidence band normalized to [0,1]). Cap at
    ``limit`` (default 35 K). The cap is enforced via ROWID range so the
    pull is index-only (no full scan on the 12.7 GB DB).
    """
    if not db_path.exists():
        raise FileNotFoundError(f"autonomath.db not found at {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        # Index-only pull: ORDER BY id (PK), LIMIT N, with optional source_url
        cur = con.cursor()
        sql = """
            SELECT
              f.id            AS row_id,
              f.entity_id     AS entity_id,
              f.field_name    AS field_name,
              f.field_value_text   AS value_text,
              f.field_value_numeric AS value_numeric,
              f.field_kind    AS field_kind,
              f.source_url    AS row_source_url,
              f.created_at    AS extracted_at,
              f.confirming_source_count AS csc,
              s.url           AS source_url
            FROM am_entity_facts f
            LEFT JOIN am_source s ON s.id = f.source_id
            WHERE f.field_value_text IS NOT NULL
            ORDER BY f.id
            LIMIT ?
        """
        cur.execute(sql, (limit,))
        for row in cur:
            csc = row["csc"] or 1
            # Confidence: 1 source = 0.5, 2 = 0.7, 3 = 0.85, 4+ = 0.95
            confidence = min(0.95, 0.5 + 0.15 * max(0, csc - 1) + 0.05 * max(0, csc - 2))
            source_doc = (
                row["source_url"]
                or row["row_source_url"]
                or f"in_house://am_entity_facts/{row['row_id']}"
            )
            extracted_at = row["extracted_at"] or _dt.datetime.now(_UTC).isoformat(
                timespec="seconds"
            )
            doc_id = hashlib.sha256(f"{row['entity_id']}|{row['field_name']}".encode()).hexdigest()[
                :32
            ]
            yield {
                "_id": doc_id,
                "row_id": row["row_id"],
                "entity_id": row["entity_id"],
                "field_name": row["field_name"],
                "field_kind": row["field_kind"],
                "value_text": row["value_text"],
                "value_numeric": row["value_numeric"],
                "source_doc": source_doc,
                "extracted_at": extracted_at,
                "verified_by": "cron_etl_v3",
                "confidence": confidence,
                "indexed_at": _dt.datetime.now(_UTC).isoformat(timespec="seconds"),
            }
    finally:
        con.close()


def _aws_signed_request(
    *,
    session: Any,
    method: str,
    url: str,
    body: str | None,
    region: str,
) -> tuple[int, str]:
    """Sign + send a single request to OpenSearch using SigV4."""
    try:
        from botocore.auth import (  # type: ignore[import-untyped]
            SigV4Auth,
        )
        from botocore.awsrequest import (  # type: ignore[import-untyped]
            AWSRequest,
        )
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("botocore not available for SigV4 signing") from exc
    try:
        import urllib3  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("urllib3 not available; pip install urllib3") from exc

    credentials = session.get_credentials().get_frozen_credentials()
    request = AWSRequest(method=method, url=url, data=body or "")
    if body:
        request.headers["Content-Type"] = "application/x-ndjson"
    SigV4Auth(credentials, "es", region).add_auth(request)
    http = urllib3.PoolManager()
    resp = http.request(
        method,
        url,
        body=(body or "").encode("utf-8") if body else None,
        headers=dict(request.headers.items()),
        timeout=urllib3.util.Timeout(connect=10.0, read=60.0),
    )
    return resp.status, resp.data.decode("utf-8", errors="replace")


def _ensure_index(*, session: Any, endpoint_https: str, region: str) -> None:
    url = f"{endpoint_https}/{INDEX_NAME}"
    status, body = _aws_signed_request(
        session=session, method="HEAD", url=url, body=None, region=region
    )
    if status == 200:
        return
    mapping = json.dumps(
        {
            "settings": {
                "number_of_shards": 2,
                "number_of_replicas": 0,
                "refresh_interval": "10s",
            },
            "mappings": {
                "properties": {
                    "row_id": {"type": "long"},
                    "entity_id": {"type": "keyword"},
                    "field_name": {"type": "keyword"},
                    "field_kind": {"type": "keyword"},
                    "value_text": {"type": "text"},
                    "value_numeric": {"type": "double"},
                    "source_doc": {"type": "keyword"},
                    "extracted_at": {"type": "keyword"},
                    "verified_by": {"type": "keyword"},
                    "confidence": {"type": "float"},
                    "indexed_at": {"type": "keyword"},
                }
            },
        }
    )
    status2, body2 = _aws_signed_request(
        session=session, method="PUT", url=url, body=mapping, region=region
    )
    if status2 >= 300:
        raise RuntimeError(f"index create failed: status={status2} body={body2}")


def cmd_index(session: Any, region: str, db_path: pathlib.Path) -> dict[str, Any]:
    info = cmd_status(session)
    if not info.get("exists"):
        return {"state": "DOMAIN_MISSING", "domain": DOMAIN_NAME}
    if info.get("processing"):
        return {"state": "DOMAIN_NOT_READY", "domain": DOMAIN_NAME}
    endpoint = info.get("endpoint")
    if not endpoint:
        return {"state": "NO_ENDPOINT", "domain": DOMAIN_NAME}
    endpoint_https = f"https://{endpoint}"

    _ensure_index(session=session, endpoint_https=endpoint_https, region=region)

    bulk_url = f"{endpoint_https}/_bulk"
    batch: list[str] = []
    total = 0
    batches = 0
    failures = 0

    def _flush() -> None:
        nonlocal batch, batches, failures
        if not batch:
            return
        body = "\n".join(batch) + "\n"
        status, resp_body = _aws_signed_request(
            session=session,
            method="POST",
            url=bulk_url,
            body=body,
            region=region,
        )
        if status >= 300:
            failures += 1
            print(
                f"[warn] bulk batch failed status={status} sample={resp_body[:200]}",
                file=sys.stderr,
            )
        batch = []
        batches += 1

    for doc in _load_facts_for_indexing(db_path, TARGET_ROWS):
        action = json.dumps(
            {"index": {"_index": INDEX_NAME, "_id": doc["_id"]}}, ensure_ascii=False
        )
        payload = {k: v for k, v in doc.items() if k != "_id"}
        batch.append(action)
        batch.append(json.dumps(payload, ensure_ascii=False))
        total += 1
        if len(batch) >= BULK_BATCH * 2:
            _flush()
    _flush()

    return {
        "state": "INDEXED",
        "domain": DOMAIN_NAME,
        "endpoint": endpoint,
        "index": INDEX_NAME,
        "doc_count": total,
        "batches": batches,
        "failed_batches": failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--create", action="store_true", help="create the domain")
    ap.add_argument("--wait", action="store_true", help="wait until ACTIVE")
    ap.add_argument("--index", action="store_true", help="bulk-index 35K facts")
    ap.add_argument("--status", action="store_true", help="print domain status")
    ap.add_argument(
        "--profile", default=DEFAULT_PROFILE, help="AWS profile (default bookyou-recovery)"
    )
    ap.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    ap.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help="path to autonomath.db (default: ./autonomath.db)",
    )
    ap.add_argument(
        "--max-wait-sec",
        type=int,
        default=1500,
        help="max wait seconds for --wait (default 1500 = 25min)",
    )
    args = ap.parse_args()

    if not any([args.create, args.wait, args.index, args.status]):
        args.status = True

    session = _session(args.profile, args.region)
    out: dict[str, Any] = {"domain": DOMAIN_NAME, "region": args.region}

    if args.create:
        out["create"] = cmd_create(session, args.region)
    if args.wait:
        out["wait"] = cmd_wait(session, args.max_wait_sec)
    if args.index:
        out["index"] = cmd_index(session, args.region, pathlib.Path(args.db))
    if args.status:
        out["status"] = cmd_status(session)

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
