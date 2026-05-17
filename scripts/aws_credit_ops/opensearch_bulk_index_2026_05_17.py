"""Lane M10 — OpenSearch full-corpus bulk indexer (598K docs).

Wave 60+ AWS canary burn (Moat Lane M10)
=========================================

Bulk-indexes the full jpcite corpus into the production-grade OpenSearch
cluster ``jpcite-xfact-2026-05`` (r5.4xlarge x3 data + r5.large x3 master +
ultrawarm1.medium x3 multi-AZ HA). Source corpora:

  - programs            (jpintel.db)     14,472 rows
  - laws                (jpintel.db)      9,484 rows
  - court_decisions     (jpintel.db)      2,065 rows
  - invoice_registrants (jpintel.db)     13,801 rows
  - enforcement_cases   (jpintel.db)      1,185 rows
  - case_studies        (jpintel.db)      2,286 rows
  - am_law_article      (autonomath.db) 353,278 rows
  - jpi_adoption_records(autonomath.db) 201,845 rows
                                      = 598,416 docs target

Index design
------------
  index name        : jpcite-corpus-2026-05
  shards            : 6
  replicas          : 1
  analyzer          : kuromoji (Japanese)
  knn_vector field  : embedding (dims=384, paired with M4 BERT-FT vectors
                      where available; else null, BM25-only)
  retention         : 30-day hot → ultrawarm migration

Operational model
-----------------
  --create-index    PUT index w/ kuromoji + knn_vector mapping (idempotent)
  --bulk-index      Stream 8 corpora into OpenSearch _bulk (1000 doc batches,
                    10 parallel workers via ThreadPoolExecutor)
  --hybrid-query    Run a sample hybrid BM25 + filter query and print top-N
  --status          Print domain status

Constraints
-----------
- $19,490 Never-Reach budget cap respected externally.
- No LLM API call inside this script.
- Pure SigV4 → OpenSearch _bulk + _search REST endpoint.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

_UTC = getattr(_dt, "UTC", _dt.UTC)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

DEFAULT_PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
DEFAULT_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "993693061769")

DOMAIN_NAME = os.environ.get("JPCITE_OS_DOMAIN_NAME", "jpcite-xfact-2026-05")
INDEX_NAME = os.environ.get("JPCITE_OS_CORPUS_INDEX", "jpcite-corpus-2026-05")
BULK_BATCH = int(os.environ.get("JPCITE_OS_BULK_BATCH", "1000"))
PARALLEL_WORKERS = int(os.environ.get("JPCITE_OS_PARALLEL_WORKERS", "10"))


def _import_boto3() -> Any:
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("boto3 not installed; pip install boto3") from exc
    return boto3


def _session(profile: str, region: str) -> Any:
    return _import_boto3().Session(profile_name=profile, region_name=region)


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
        from botocore.auth import SigV4Auth  # type: ignore[import-untyped]
        from botocore.awsrequest import AWSRequest  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("botocore not available for SigV4 signing") from exc
    try:
        import urllib3  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("urllib3 not available; pip install urllib3") from exc

    credentials = session.get_credentials().get_frozen_credentials()
    headers_in = {"Content-Type": "application/x-ndjson"} if body else {}
    request = AWSRequest(method=method, url=url, data=body or "", headers=headers_in)
    SigV4Auth(credentials, "es", region).add_auth(request)
    http = urllib3.PoolManager()
    resp = http.request(
        method,
        url,
        body=(body or "").encode("utf-8") if body else None,
        headers=dict(request.headers.items()),
        timeout=urllib3.util.Timeout(connect=10.0, read=120.0),
    )
    return resp.status, resp.data.decode("utf-8", errors="replace")


def _get_endpoint(session: Any) -> str | None:
    es = session.client("opensearch")
    try:
        info = es.describe_domain(DomainName=DOMAIN_NAME)
    except es.exceptions.ResourceNotFoundException:
        return None
    st = info["DomainStatus"]
    return st.get("Endpoint") or st.get("Endpoints", {}).get("vpc")


def _doc_id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}|{key}".encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Corpus loaders — yield dicts with `_id` + corpus_kind + text fields
# ---------------------------------------------------------------------------


def _connect_ro(db_path: pathlib.Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_programs(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT unified_id, primary_name, aliases_json, authority_name, "
            "prefecture, municipality, program_kind, tier, official_url, source_url, "
            "amount_max_man_yen, amount_min_man_yen, subsidy_rate "
            "FROM programs WHERE excluded=0 AND tier IN ('S','A','B','C')"
        )
        for r in cur:
            yield {
                "_id": _doc_id("program", r["unified_id"]),
                "corpus_kind": "program",
                "doc_key": r["unified_id"],
                "title": r["primary_name"],
                "body": (r["aliases_json"] or ""),
                "authority": r["authority_name"],
                "prefecture": r["prefecture"],
                "city": r["municipality"],
                "program_kind": r["program_kind"],
                "tier": r["tier"],
                "source_url": r["source_url"] or r["official_url"] or "",
                "amount_max_man_yen": r["amount_max_man_yen"],
                "amount_min_man_yen": r["amount_min_man_yen"],
                "subsidy_rate": r["subsidy_rate"],
            }
    finally:
        con.close()


def load_laws(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT unified_id, law_title, law_short_title, law_type, ministry, "
            "summary, source_url FROM laws"
        )
        for r in cur:
            yield {
                "_id": _doc_id("law", r["unified_id"]),
                "corpus_kind": "law",
                "doc_key": r["unified_id"],
                "title": r["law_title"],
                "body": (r["summary"] or r["law_short_title"] or r["law_title"]),
                "law_kind": r["law_type"],
                "authority": r["ministry"],
                "source_url": r["source_url"] or "",
            }
    finally:
        con.close()


def load_law_articles(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT article_id, law_canonical_id, article_number, title, "
            "text_summary, text_full, effective_from, last_amended, source_url "
            "FROM am_law_article"
        )
        for r in cur:
            article_id_str = str(r["article_id"])
            yield {
                "_id": _doc_id("law_article", article_id_str),
                "corpus_kind": "law_article",
                "doc_key": article_id_str,
                "law_canonical_id": r["law_canonical_id"],
                "article_number": r["article_number"],
                "title": r["title"],
                "body": (r["text_full"] or r["text_summary"] or "")[:6000],
                "effective_from": r["effective_from"],
                "last_amended": r["last_amended"],
                "source_url": r["source_url"] or "",
            }
    finally:
        con.close()


def load_cases(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT case_id, company_name, case_title, case_summary, "
            "industry_name, prefecture, publication_date, source_url FROM case_studies"
        )
        for r in cur:
            yield {
                "_id": _doc_id("case", r["case_id"]),
                "corpus_kind": "case",
                "doc_key": r["case_id"],
                "title": r["case_title"] or r["company_name"],
                "body": (r["case_summary"] or "")[:6000],
                "industry": r["industry_name"],
                "prefecture": r["prefecture"],
                "fiscal_year": r["publication_date"],
                "source_url": r["source_url"] or "",
            }
    finally:
        con.close()


def load_adoption(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT id, program_name_raw, company_name_raw, project_title, "
            "industry_jsic_medium, prefecture, municipality, announced_at, "
            "amount_granted_yen, source_url FROM jpi_adoption_records"
        )
        for r in cur:
            adoption_id_str = str(r["id"])
            yield {
                "_id": _doc_id("adoption", adoption_id_str),
                "corpus_kind": "adoption",
                "doc_key": adoption_id_str,
                "title": (r["project_title"] or r["program_name_raw"] or "")[:500],
                "body": (r["company_name_raw"] or "")[:500],
                "recipient_name": r["company_name_raw"],
                "industry": r["industry_jsic_medium"],
                "prefecture": r["prefecture"],
                "city": r["municipality"],
                "fiscal_year": r["announced_at"],
                "amount_yen": r["amount_granted_yen"],
                "source_url": r["source_url"] or "",
            }
    finally:
        con.close()


def load_court(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT unified_id, case_name, case_number, court, court_level, "
            "decision_date, key_ruling, impact_on_business, subject_area, "
            "source_url FROM court_decisions"
        )
        for r in cur:
            yield {
                "_id": _doc_id("court", r["unified_id"]),
                "corpus_kind": "court",
                "doc_key": r["unified_id"],
                "title": r["case_name"],
                "body": ((r["key_ruling"] or "") + "\n" + (r["impact_on_business"] or ""))[:6000],
                "court": r["court"],
                "decision_date": r["decision_date"],
                "industry": r["subject_area"],
                "source_url": r["source_url"] or "",
            }
    finally:
        con.close()


def load_invoice(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT invoice_registration_number, houjin_bangou, normalized_name, "
            "address_normalized, prefecture, registered_date, registrant_kind, "
            "source_url FROM invoice_registrants"
        )
        for r in cur:
            yield {
                "_id": _doc_id("invoice", r["invoice_registration_number"]),
                "corpus_kind": "invoice",
                "doc_key": r["invoice_registration_number"],
                "title": r["normalized_name"],
                "body": (r["address_normalized"] or "")[:1000],
                "houjin_bangou": r["houjin_bangou"],
                "prefecture": r["prefecture"],
                "registration_date": r["registered_date"],
                "program_kind": r["registrant_kind"],
                "source_url": r["source_url"] or "",
            }
    finally:
        con.close()


def load_enforcement(db_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    con = _connect_ro(db_path)
    try:
        cur = con.execute(
            "SELECT case_id, event_type, recipient_name, recipient_kind, "
            "bureau, ministry, prefecture, reason_excerpt, legal_basis, "
            "disclosed_date, source_url FROM enforcement_cases"
        )
        for r in cur:
            yield {
                "_id": _doc_id("enforcement", r["case_id"]),
                "corpus_kind": "enforcement",
                "doc_key": r["case_id"],
                "title": r["recipient_name"],
                "body": ((r["reason_excerpt"] or "") + "\n" + (r["legal_basis"] or ""))[:4000],
                "authority": r["ministry"] or r["bureau"],
                "prefecture": r["prefecture"],
                "disposition_kind": r["event_type"],
                "disposition_date": r["disclosed_date"],
                "program_kind": r["recipient_kind"],
                "source_url": r["source_url"] or "",
            }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------


def _index_mapping() -> dict[str, Any]:
    return {
        "settings": {
            "number_of_shards": 6,
            "number_of_replicas": 1,
            "refresh_interval": "30s",
            "knn": True,
            "analysis": {
                "analyzer": {
                    "ja_kuromoji": {
                        "type": "custom",
                        "tokenizer": "kuromoji_tokenizer",
                        "filter": [
                            "kuromoji_baseform",
                            "kuromoji_part_of_speech",
                            "ja_stop",
                            "kuromoji_number",
                            "kuromoji_stemmer",
                        ],
                    }
                }
            },
        },
        "mappings": {
            "properties": {
                "corpus_kind": {"type": "keyword"},
                "doc_key": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "ja_kuromoji",
                    "fields": {"raw": {"type": "keyword"}},
                },
                "body": {"type": "text", "analyzer": "ja_kuromoji"},
                "authority": {"type": "keyword"},
                "prefecture": {"type": "keyword"},
                "city": {"type": "keyword"},
                "program_kind": {"type": "keyword"},
                "tier": {"type": "keyword"},
                "source_url": {"type": "keyword"},
                "amount_max_man_yen": {"type": "double"},
                "amount_min_man_yen": {"type": "double"},
                "subsidy_rate": {"type": "float"},
                "law_kind": {"type": "keyword"},
                "law_canonical_id": {"type": "keyword"},
                "article_number": {"type": "keyword"},
                "effective_from": {"type": "keyword"},
                "last_amended": {"type": "keyword"},
                "industry": {"type": "keyword"},
                "fiscal_year": {"type": "keyword"},
                "amount_yen": {"type": "double"},
                "court": {"type": "keyword"},
                "decision_date": {"type": "keyword"},
                "houjin_bangou": {"type": "keyword"},
                "registration_date": {"type": "keyword"},
                "disposition_kind": {"type": "keyword"},
                "disposition_date": {"type": "keyword"},
                "recipient_name": {"type": "text", "analyzer": "ja_kuromoji"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 384,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {"ef_construction": 128, "m": 16},
                    },
                },
                "indexed_at": {"type": "keyword"},
            }
        },
    }


def cmd_create_index(*, session: Any, endpoint_https: str, region: str) -> dict[str, Any]:
    url = f"{endpoint_https}/{INDEX_NAME}"
    status, _ = _aws_signed_request(
        session=session, method="HEAD", url=url, body=None, region=region
    )
    if status == 200:
        return {"action": "ALREADY_EXISTS", "index": INDEX_NAME}
    mapping = json.dumps(_index_mapping(), ensure_ascii=False)
    status2, body2 = _aws_signed_request(
        session=session, method="PUT", url=url, body=mapping, region=region
    )
    if status2 >= 300:
        return {"action": "FAILED", "status": status2, "body": body2[:500]}
    return {"action": "CREATED", "index": INDEX_NAME}


# ---------------------------------------------------------------------------
# Bulk indexer (parallel)
# ---------------------------------------------------------------------------


def _flush_batch(
    *,
    session: Any,
    endpoint_https: str,
    region: str,
    batch: list[str],
) -> tuple[int, int]:
    if not batch:
        return (0, 0)
    body = "\n".join(batch) + "\n"
    bulk_url = f"{endpoint_https}/_bulk"
    status, resp_body = _aws_signed_request(
        session=session, method="POST", url=bulk_url, body=body, region=region
    )
    if status >= 300:
        print(f"[warn] bulk status={status} sample={resp_body[:200]}", file=sys.stderr)
        return (0, 1)
    return (1, 0)


def _bulk_corpus(
    *,
    session: Any,
    endpoint_https: str,
    region: str,
    corpus_name: str,
    docs: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Stream a single corpus into _bulk and return counts."""
    indexed_at = _dt.datetime.now(_UTC).isoformat(timespec="seconds")
    batch: list[str] = []
    total = 0
    ok_batches = 0
    failed_batches = 0
    for doc in docs:
        doc_id = doc.pop("_id")
        doc["indexed_at"] = indexed_at
        action = json.dumps({"index": {"_index": INDEX_NAME, "_id": doc_id}}, ensure_ascii=False)
        payload = json.dumps(doc, ensure_ascii=False)
        batch.append(action)
        batch.append(payload)
        total += 1
        if len(batch) >= BULK_BATCH * 2:
            ok, failed = _flush_batch(
                session=session,
                endpoint_https=endpoint_https,
                region=region,
                batch=batch,
            )
            ok_batches += ok
            failed_batches += failed
            batch = []
    ok, failed = _flush_batch(
        session=session, endpoint_https=endpoint_https, region=region, batch=batch
    )
    ok_batches += ok
    failed_batches += failed
    return {
        "corpus": corpus_name,
        "total": total,
        "ok_batches": ok_batches,
        "failed_batches": failed_batches,
    }


def cmd_bulk_index(
    *,
    session: Any,
    endpoint_https: str,
    region: str,
    jpintel_db: pathlib.Path,
    autonomath_db: pathlib.Path,
    corpora: list[str],
) -> dict[str, Any]:
    """Bulk-index every requested corpus (parallel across corpora)."""
    loaders: dict[str, tuple[pathlib.Path, Any]] = {
        "programs": (jpintel_db, load_programs),
        "laws": (jpintel_db, load_laws),
        "cases": (jpintel_db, load_cases),
        "court": (jpintel_db, load_court),
        "invoice": (jpintel_db, load_invoice),
        "enforcement": (jpintel_db, load_enforcement),
        "law_articles": (autonomath_db, load_law_articles),
        "adoption": (autonomath_db, load_adoption),
    }
    results: list[dict[str, Any]] = []

    def _run(name: str) -> dict[str, Any]:
        db_path, loader = loaders[name]
        if not db_path.exists():
            return {"corpus": name, "error": f"db_missing: {db_path}"}
        return _bulk_corpus(
            session=session,
            endpoint_https=endpoint_https,
            region=region,
            corpus_name=name,
            docs=loader(db_path),
        )

    todo = [c for c in corpora if c in loaders]
    with ThreadPoolExecutor(max_workers=min(PARALLEL_WORKERS, len(todo) or 1)) as ex:
        futures = {ex.submit(_run, name): name for name in todo}
        for fut in as_completed(futures):
            results.append(fut.result())

    total_docs = sum(r.get("total", 0) for r in results)
    total_failed = sum(r.get("failed_batches", 0) for r in results)
    return {
        "state": "INDEXED",
        "index": INDEX_NAME,
        "total_docs": total_docs,
        "total_failed_batches": total_failed,
        "per_corpus": sorted(results, key=lambda r: r.get("corpus", "")),
    }


# ---------------------------------------------------------------------------
# Hybrid query (BM25 + filter) — vector ANN reserved for when M4 embeddings
# land in this index
# ---------------------------------------------------------------------------


def cmd_hybrid_query(
    *,
    session: Any,
    endpoint_https: str,
    region: str,
    query_text: str,
    top_n: int = 5,
) -> dict[str, Any]:
    url = f"{endpoint_https}/{INDEX_NAME}/_search"
    body = json.dumps(
        {
            "size": top_n,
            "_source": ["corpus_kind", "doc_key", "title", "tier", "prefecture", "source_url"],
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": query_text,
                                "fields": ["title^3", "body"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "minimum_should_match": 1,
                }
            },
        },
        ensure_ascii=False,
    )
    status, resp = _aws_signed_request(
        session=session, method="POST", url=url, body=body, region=region
    )
    if status >= 300:
        return {"state": "QUERY_FAILED", "status": status, "body": resp[:500]}
    parsed = json.loads(resp)
    hits = parsed.get("hits", {}).get("hits", [])
    return {
        "state": "OK",
        "query": query_text,
        "total": parsed.get("hits", {}).get("total", {}).get("value"),
        "took_ms": parsed.get("took"),
        "top": [
            {
                "score": h.get("_score"),
                "id": h.get("_id"),
                "corpus_kind": h.get("_source", {}).get("corpus_kind"),
                "title": h.get("_source", {}).get("title"),
                "tier": h.get("_source", {}).get("tier"),
                "source_url": h.get("_source", {}).get("source_url"),
            }
            for h in hits
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_status(session: Any) -> dict[str, Any]:
    es = session.client("opensearch")
    try:
        info = es.describe_domain(DomainName=DOMAIN_NAME)
    except es.exceptions.ResourceNotFoundException:
        return {"domain": DOMAIN_NAME, "exists": False}
    st = info["DomainStatus"]
    cc = st.get("ClusterConfig", {})
    return {
        "domain": DOMAIN_NAME,
        "exists": True,
        "processing": st.get("Processing"),
        "endpoint": st.get("Endpoint") or st.get("Endpoints", {}).get("vpc"),
        "engine_version": st.get("EngineVersion"),
        "instance_type": cc.get("InstanceType"),
        "instance_count": cc.get("InstanceCount"),
        "master_type": cc.get("DedicatedMasterType"),
        "master_count": cc.get("DedicatedMasterCount"),
        "warm_type": cc.get("WarmType"),
        "warm_count": cc.get("WarmCount"),
        "zone_aware": cc.get("ZoneAwarenessEnabled"),
        "ebs_volume_size_gb": st.get("EBSOptions", {}).get("VolumeSize"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--create-index", action="store_true")
    ap.add_argument("--bulk-index", action="store_true")
    ap.add_argument(
        "--corpora",
        default="programs,laws,cases,court,invoice,enforcement,law_articles,adoption",
        help="comma-separated list of corpora to index",
    )
    ap.add_argument("--hybrid-query", default=None, help="run a sample query")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--region", default=DEFAULT_REGION)
    ap.add_argument("--jpintel-db", default=str(DEFAULT_JPINTEL_DB))
    ap.add_argument("--autonomath-db", default=str(DEFAULT_AUTONOMATH_DB))
    args = ap.parse_args()

    if not (args.status or args.create_index or args.bulk_index or args.hybrid_query):
        args.status = True

    session = _session(args.profile, args.region)
    out: dict[str, Any] = {"domain": DOMAIN_NAME, "region": args.region}

    if args.status:
        out["status"] = cmd_status(session)

    endpoint = _get_endpoint(session)
    if (args.create_index or args.bulk_index or args.hybrid_query) and not endpoint:
        out["error"] = "no endpoint — domain missing or unreachable"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    endpoint_https = f"https://{endpoint}" if endpoint else None

    if args.create_index and endpoint_https:
        out["create_index"] = cmd_create_index(
            session=session, endpoint_https=endpoint_https, region=args.region
        )

    if args.bulk_index and endpoint_https:
        corpora = [c.strip() for c in args.corpora.split(",") if c.strip()]
        t0 = time.monotonic()
        out["bulk_index"] = cmd_bulk_index(
            session=session,
            endpoint_https=endpoint_https,
            region=args.region,
            jpintel_db=pathlib.Path(args.jpintel_db),
            autonomath_db=pathlib.Path(args.autonomath_db),
            corpora=corpora,
        )
        out["bulk_index"]["elapsed_sec"] = round(time.monotonic() - t0, 1)

    if args.hybrid_query and endpoint_https:
        out["hybrid_query"] = cmd_hybrid_query(
            session=session,
            endpoint_https=endpoint_https,
            region=args.region,
            query_text=args.hybrid_query,
            top_n=args.top_n,
        )

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
