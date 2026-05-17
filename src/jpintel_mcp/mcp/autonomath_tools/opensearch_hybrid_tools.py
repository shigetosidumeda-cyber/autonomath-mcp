"""opensearch_hybrid_tools — Moat Lane M10 OpenSearch hybrid search MCP wrapper.

Wave 60+ AWS canary burn (Moat Lane M10, 2026-05-17)
====================================================

Wraps the production-grade ``jpcite-xfact-2026-05`` cluster (r5.4xlarge x3
data + r5.large x3 master + ultrawarm1.medium x3 multi-AZ HA) as a single
MCP tool: ``opensearch_hybrid_search``. The cluster has the full corpus
indexed (programs + laws + law_articles + cases + adoption + court +
invoice + enforcement, ~600 K docs) with a kuromoji analyzer and a
knn_vector field reserved for the M4 BERT-FT 384-d embedding pairing.

Hard constraints
----------------
- NO LLM call. Pure SigV4-signed ``_search`` request.
- Single ``¥3/req`` billing event per call (caller-supplied envelope).
- §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope (retrieval surface
  only — NOT a 採択 forecast / 法的意見 / 税務助言 / 行政書士業務).
- Gate: ``AUTONOMATH_OPENSEARCH_HYBRID_ENABLED`` (default ON when
  ``settings.autonomath_enabled``).

Hybrid composition
------------------
- BM25 multi_match over ``title^3`` + ``body`` (kuromoji-analyzed JA).
- Optional ``corpus_kind`` / ``prefecture`` / ``tier`` term filters.
- Optional ``min_amount_man_yen`` range filter on ``amount_max_man_yen``.
- (Reserved) vector ANN over ``embedding`` field — requires the caller
  to supply a 384-d vector; when omitted the tool falls back to BM25-only.

Returns
-------
dict with keys ``state`` / ``took_ms`` / ``total`` / ``top`` (list of
hits, each with ``score`` / ``corpus_kind`` / ``doc_key`` / ``title`` /
``prefecture`` / ``source_url``) plus ``_billing_unit`` / ``_disclaimer``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.autonomath.opensearch_hybrid")

_ENABLED = (
    get_flag(
        "JPCITE_OPENSEARCH_HYBRID_ENABLED",
        "AUTONOMATH_OPENSEARCH_HYBRID_ENABLED",
        "1",
    )
    == "1"
)

DOMAIN_NAME = os.environ.get("JPCITE_OS_DOMAIN_NAME", "jpcite-xfact-2026-05")
INDEX_NAME = os.environ.get("JPCITE_OS_CORPUS_INDEX", "jpcite-corpus-2026-05")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
AWS_PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
# Endpoint can be cached as env var to avoid an ES describe-domain hop on
# every call. When unset the tool resolves it lazily once per process.
_CACHED_ENDPOINT_ENV = "JPCITE_OS_ENDPOINT"

_DISCLAIMER_OPENSEARCH_HYBRID = (
    "本 response は OpenSearch BM25 + (オプション) k-NN による retrieval "
    "結果で、採択 / 法的判断 / 税務助言を担保するものではありません。"
    "結果は corpus snapshot 上の類似度順位で、行政書士法 §1 / 税理士法 §52 / "
    "公認会計士法 §47条の2 / 弁護士法 §72 / 司法書士法 §3 の業務範囲は含みません。"
    "確定判断は士業へ、primary source 確認必須。"
)


def _resolve_endpoint() -> str | None:
    """Resolve the OpenSearch endpoint (process-cache via env)."""
    cached = os.environ.get(_CACHED_ENDPOINT_ENV)
    if cached:
        return cached
    try:
        import boto3
    except ImportError:  # pragma: no cover
        logger.warning("boto3 not installed; opensearch_hybrid_search disabled")
        return None
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    es = session.client("opensearch")
    try:
        info = es.describe_domain(DomainName=DOMAIN_NAME)
    except Exception as exc:  # noqa: BLE001
        logger.warning("describe_domain failed: %s", exc)
        return None
    st = info["DomainStatus"]
    endpoint_value = st.get("Endpoint") or st.get("Endpoints", {}).get("vpc")
    if endpoint_value:
        os.environ[_CACHED_ENDPOINT_ENV] = str(endpoint_value)
        return str(endpoint_value)
    return None


def _signed_post(*, url: str, body: str) -> tuple[int, str]:
    try:
        import boto3
        import urllib3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"missing AWS SDK / urllib3: {exc}") from exc

    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    credentials = session.get_credentials().get_frozen_credentials()
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"Content-Type": "application/x-ndjson"},
    )
    SigV4Auth(credentials, "es", AWS_REGION).add_auth(request)
    http = urllib3.PoolManager()
    resp = http.request(
        "POST",
        url,
        body=body.encode("utf-8"),
        headers=dict(request.headers.items()),
        timeout=urllib3.util.Timeout(connect=10.0, read=30.0),
    )
    return resp.status, resp.data.decode("utf-8", errors="replace")


def _opensearch_hybrid_search_impl(
    *,
    query: str,
    corpus_kind: str | None = None,
    prefecture: str | None = None,
    tier: str | None = None,
    min_amount_man_yen: float | None = None,
    top_n: int = 10,
    embedding: list[float] | None = None,
) -> dict[str, Any]:
    endpoint = _resolve_endpoint()
    if not endpoint:
        return {
            "state": "ENDPOINT_UNAVAILABLE",
            "domain": DOMAIN_NAME,
            "_billing_unit": 0,
            "_disclaimer": _DISCLAIMER_OPENSEARCH_HYBRID,
        }
    url = f"https://{endpoint}/{INDEX_NAME}/_search"

    must_filters: list[dict[str, Any]] = []
    if corpus_kind:
        must_filters.append({"term": {"corpus_kind": corpus_kind}})
    if prefecture:
        must_filters.append({"term": {"prefecture": prefecture}})
    if tier:
        must_filters.append({"term": {"tier": tier}})
    if min_amount_man_yen is not None:
        must_filters.append({"range": {"amount_max_man_yen": {"gte": float(min_amount_man_yen)}}})

    should_clauses: list[dict[str, Any]] = [
        {
            "multi_match": {
                "query": query,
                "fields": ["title^3", "body"],
                "type": "best_fields",
            }
        }
    ]
    if embedding and len(embedding) == 384:
        should_clauses.append({"knn": {"embedding": {"vector": embedding, "k": top_n}}})

    body = json.dumps(
        {
            "size": top_n,
            "_source": [
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
            "query": {
                "bool": {
                    "should": should_clauses,
                    "filter": must_filters,
                    "minimum_should_match": 1,
                }
            },
        },
        ensure_ascii=False,
    )
    status, resp = _signed_post(url=url, body=body)
    if status >= 300:
        return {
            "state": "QUERY_FAILED",
            "status": status,
            "body": resp[:500],
            "_billing_unit": 0,
            "_disclaimer": _DISCLAIMER_OPENSEARCH_HYBRID,
        }
    parsed = json.loads(resp)
    hits = parsed.get("hits", {}).get("hits", [])
    top = [
        {
            "score": h.get("_score"),
            "id": h.get("_id"),
            "corpus_kind": (h.get("_source") or {}).get("corpus_kind"),
            "doc_key": (h.get("_source") or {}).get("doc_key"),
            "title": (h.get("_source") or {}).get("title"),
            "tier": (h.get("_source") or {}).get("tier"),
            "prefecture": (h.get("_source") or {}).get("prefecture"),
            "authority": (h.get("_source") or {}).get("authority"),
            "amount_max_man_yen": (h.get("_source") or {}).get("amount_max_man_yen"),
            "source_url": (h.get("_source") or {}).get("source_url"),
        }
        for h in hits
    ]
    return {
        "state": "OK",
        "index": INDEX_NAME,
        "query": query,
        "took_ms": parsed.get("took"),
        "total": (parsed.get("hits", {}).get("total") or {}).get("value"),
        "top": top,
        "filters_applied": {
            "corpus_kind": corpus_kind,
            "prefecture": prefecture,
            "tier": tier,
            "min_amount_man_yen": min_amount_man_yen,
            "hybrid_vector": bool(embedding and len(embedding) == 384),
        },
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER_OPENSEARCH_HYBRID,
    }


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def opensearch_hybrid_search(
        query: Annotated[
            str,
            Field(
                description="JA / EN free-text query (kuromoji-analyzed against title^3 + body)."
            ),
        ],
        corpus_kind: Annotated[
            str | None,
            Field(
                description=(
                    "Restrict to one corpus: program / law / law_article / case / adoption / "
                    "court / invoice / enforcement. None = all 8."
                ),
            ),
        ] = None,
        prefecture: Annotated[
            str | None,
            Field(description="Exact prefecture match (e.g. '東京都')."),
        ] = None,
        tier: Annotated[
            str | None,
            Field(description="Exact tier match for programs (S/A/B/C)."),
        ] = None,
        min_amount_man_yen: Annotated[
            float | None,
            Field(description="Filter by minimum amount_max_man_yen (万円)."),
        ] = None,
        top_n: Annotated[
            int,
            Field(ge=1, le=50, description="Top-N hits (1..50). Default 10."),
        ] = 10,
    ) -> dict[str, Any]:
        """OpenSearch BM25 + kuromoji hybrid search over the full jpcite corpus (~600K docs, 8 corpora). Returns top-N hits ranked by relevance. NOT an 採択 forecast — 行政書士法 §1 / 税理士法 §52 / 弁護士法 §72 fence."""
        return _opensearch_hybrid_search_impl(
            query=query,
            corpus_kind=corpus_kind,
            prefecture=prefecture,
            tier=tier,
            min_amount_man_yen=min_amount_man_yen,
            top_n=top_n,
        )


__all__ = [
    "_opensearch_hybrid_search_impl",
    "_DISCLAIMER_OPENSEARCH_HYBRID",
]
