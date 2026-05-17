#!/usr/bin/env python3
"""Lane M10 OpenSearch read-only export/check.

Exports the live OpenSearch domain/index configuration and a bounded query
relevance sample. This script intentionally has no create, index, scale, or
delete path. OpenSearch REST calls are limited to GET and POST /_search.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_REGION: Final[str] = "ap-northeast-1"
DEFAULT_DOMAIN: Final[str] = "jpcite-xfact-2026-05"
DEFAULT_INDEX: Final[str] = "jpcite-corpus-2026-05"
DEFAULT_OUTPUT_DIR: Final[str] = str(Path(tempfile.gettempdir()) / "jpcite_m10_opensearch_export")
DEFAULT_QUERIES: Final[tuple[str, ...]] = (
    "中小企業 補助金 東京",
    "税額控除 研究開発",
    "建設業 許可 行政処分",
    "インボイス 登録番号",
    "個人情報保護法 安全管理措置",
)


def _import_boto3() -> Any:
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("boto3 is required for OpenSearch export checks") from exc
    return boto3


def _session(*, profile: str, region: str) -> Any:
    return _import_boto3().Session(profile_name=profile, region_name=region)


def _describe_domain(session: Any, *, domain: str) -> dict[str, Any]:
    opensearch = session.client("opensearch")
    return dict(opensearch.describe_domain(DomainName=domain))


def _endpoint_from_domain(domain_config: dict[str, Any]) -> str:
    status = domain_config.get("DomainStatus") or {}
    endpoint = status.get("Endpoint") or status.get("Endpoints", {}).get("vpc")
    if not endpoint:
        raise RuntimeError("OpenSearch domain has no endpoint")
    return str(endpoint)


def _signed_request(
    *,
    session: Any,
    method: str,
    url: str,
    body: str | None,
    region: str,
) -> tuple[int, str]:
    parsed = urlparse(url)
    if method not in {"GET", "POST"}:
        raise ValueError(f"read-only checker does not allow {method}")
    if method == "POST" and not parsed.path.endswith("/_search"):
        raise ValueError(f"POST is allowed only for _search: {parsed.path}")

    try:
        import urllib3
        from botocore.auth import SigV4Auth  # type: ignore[import-untyped]
        from botocore.awsrequest import AWSRequest  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("botocore and urllib3 are required for signed requests") from exc

    credentials = session.get_credentials().get_frozen_credentials()
    request = AWSRequest(
        method=method,
        url=url,
        data=body or "",
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials, "es", region).add_auth(request)
    http = urllib3.PoolManager()
    resp = http.request(
        method,
        url,
        body=(body or "").encode("utf-8") if body else None,
        headers=dict(request.headers.items()),
        timeout=urllib3.util.Timeout(connect=10.0, read=60.0),
    )
    return int(resp.status), resp.data.decode("utf-8", errors="replace")


def _search_body(*, query: str, top_n: int) -> dict[str, Any]:
    return {
        "size": max(1, min(top_n, 25)),
        "_source": {
            "includes": [
                "corpus_kind",
                "doc_key",
                "title",
                "tier",
                "prefecture",
                "city",
                "authority",
                "amount_max_man_yen",
                "source_url",
            ],
            "excludes": ["body", "embedding"],
        },
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^3", "body"],
                            "type": "best_fields",
                        }
                    }
                ],
                "minimum_should_match": 1,
            }
        },
    }


def _top_hits(search_response: dict[str, Any]) -> list[dict[str, Any]]:
    top: list[dict[str, Any]] = []
    for rank, hit in enumerate(search_response.get("hits", {}).get("hits", []), start=1):
        source = hit.get("_source") or {}
        top.append(
            {
                "rank": rank,
                "score": hit.get("_score"),
                "id": hit.get("_id"),
                "corpus_kind": source.get("corpus_kind"),
                "doc_key": source.get("doc_key"),
                "title": source.get("title"),
                "tier": source.get("tier"),
                "prefecture": source.get("prefecture"),
                "authority": source.get("authority"),
                "source_url": source.get("source_url"),
            }
        )
    return top


def _field_count(mapping: dict[str, Any]) -> int:
    def walk(node: Any) -> int:
        if not isinstance(node, dict):
            return 0
        properties = node.get("properties")
        total = len(properties) if isinstance(properties, dict) else 0
        if isinstance(properties, dict):
            total += sum(walk(child) for child in properties.values())
        for key, value in node.items():
            if key != "properties":
                total += walk(value)
        return total

    return walk(mapping)


def _json_loads(payload: str) -> Any:
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        return {"_json_parse_error": str(exc), "_raw": payload[:1000]}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows)
    )


def _planned_operations(*, domain: str, index: str, queries: list[str]) -> list[dict[str, Any]]:
    return [
        {"kind": "aws", "operation": "opensearch.describe_domain", "domain": domain},
        {"kind": "rest", "method": "GET", "path": f"/{index}/_settings"},
        {"kind": "rest", "method": "GET", "path": f"/{index}/_mapping"},
        {"kind": "rest", "method": "GET", "path": f"/{index}/_count"},
        *[
            {"kind": "rest", "method": "POST", "path": f"/{index}/_search", "query": query}
            for query in queries
        ],
    ]


def run_export(
    *,
    profile: str,
    region: str,
    domain: str,
    index: str,
    output_dir: Path,
    run_id: str,
    queries: list[str],
    top_n: int,
) -> dict[str, Any]:
    session = _session(profile=profile, region=region)
    domain_config = _describe_domain(session, domain=domain)
    endpoint = _endpoint_from_domain(domain_config)
    endpoint_https = f"https://{endpoint}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    rest_payloads: dict[str, Any] = {}
    for label, path in {
        "index_settings": f"/{index}/_settings",
        "index_mapping": f"/{index}/_mapping",
        "index_count": f"/{index}/_count",
    }.items():
        status, body = _signed_request(
            session=session,
            method="GET",
            url=f"{endpoint_https}{path}",
            body=None,
            region=region,
        )
        rest_payloads[label] = {"status": status, "body": _json_loads(body)}

    relevance_rows: list[dict[str, Any]] = []
    for idx, query in enumerate(queries, start=1):
        status, body = _signed_request(
            session=session,
            method="POST",
            url=f"{endpoint_https}/{index}/_search",
            body=json.dumps(_search_body(query=query, top_n=top_n), ensure_ascii=False),
            region=region,
        )
        parsed = _json_loads(body)
        hits = parsed.get("hits", {}) if isinstance(parsed, dict) else {}
        total = hits.get("total", {}) if isinstance(hits, dict) else {}
        relevance_rows.append(
            {
                "query_id": f"q{idx:03d}",
                "query": query,
                "status": status,
                "took_ms": parsed.get("took") if isinstance(parsed, dict) else None,
                "total": total.get("value") if isinstance(total, dict) else total,
                "top": _top_hits(parsed) if isinstance(parsed, dict) else [],
            }
        )

    files = {
        "domain_config": run_dir / "domain_config.json",
        "index_settings": run_dir / "index_settings.json",
        "index_mapping": run_dir / "index_mapping.json",
        "index_count": run_dir / "index_count.json",
        "query_relevance": run_dir / "query_relevance.jsonl",
        "summary": run_dir / "summary.json",
    }
    _write_json(files["domain_config"], domain_config)
    _write_json(files["index_settings"], rest_payloads["index_settings"])
    _write_json(files["index_mapping"], rest_payloads["index_mapping"])
    _write_json(files["index_count"], rest_payloads["index_count"])
    _write_jsonl(files["query_relevance"], relevance_rows)

    count_body = rest_payloads["index_count"]["body"]
    mapping_body = rest_payloads["index_mapping"]["body"]
    summary = {
        "run_id": run_id,
        "domain": domain,
        "index": index,
        "endpoint": endpoint,
        "document_count": count_body.get("count") if isinstance(count_body, dict) else None,
        "mapping_field_count": _field_count(mapping_body) if isinstance(mapping_body, dict) else 0,
        "query_count": len(relevance_rows),
        "non_200_query_count": sum(1 for row in relevance_rows if row["status"] != 200),
        "mutating_operations_executed": False,
        "files": {name: str(path) for name, path in files.items()},
    }
    _write_json(files["summary"], summary)
    return summary


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--dry-run-plan", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    queries = list(args.queries or DEFAULT_QUERIES)
    if args.dry_run_plan:
        print(
            json.dumps(
                {
                    "domain": args.domain,
                    "index": args.index,
                    "operations": _planned_operations(
                        domain=args.domain,
                        index=args.index,
                        queries=queries,
                    ),
                    "mutating_operations_executed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    summary = run_export(
        profile=args.profile,
        region=args.region,
        domain=args.domain,
        index=args.index,
        output_dir=Path(args.output_dir),
        run_id=args.run_id,
        queries=queries,
        top_n=args.top_n,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
