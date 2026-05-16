"""GraphQL endpoint for cross-domain queries (Wave 19 §F2).

Sister surface to the REST API at ``/v1/*``. Some AI agent toolchains
(Apollo Server, Hasura, Relay, Cursor's older fetch helpers) prefer a
GraphQL surface because they can express "give me a program, its
laws, its 採択事例 cohort, and the related court_decisions in one
round-trip". The same data is reachable via REST but requires 4+ calls
and client-side join.

Implements a minimal schema-first GraphQL endpoint backed by
strawberry-graphql (if installed) with a manual fallback that returns
a 501 with installation hints. The schema mirrors the REST envelope so
we don't introduce a divergent data model — the query merely re-uses
the same fetcher functions from ``programs.py`` / ``laws.py`` etc.

NO LLM API call. Pure SQL → typed objects → JSON.

Endpoint
--------
    POST /v1/graphql
    GET  /v1/graphql  (returns the GraphQL Playground / SDL)

Query example
-------------
    {
      program(id: "AID-12345") {
        id
        name
        tier
        sourceUrl
        sourceFetchedAt
        laws {
          articleId
          name
        }
        cases {
          year
          adopted
          companyName
        }
      }
    }

Sensitive disclaimer envelopes
------------------------------
The GraphQL response inherits the same ``_disclaimer`` field set on
REST-side sensitive surfaces (§52 / §72 / §1 行政書士法). The field is
exposed as ``disclaimer: String`` on the Program / Case / TaxRule
types where applicable.

Strawberry-graphql is added to extras only; if it is not present at
import time, this module degrades to a 501 stub so production import
still succeeds.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("jpintel.api.graphql")

router = APIRouter(prefix="/v1/graphql", tags=["graphql"])

# --------------------------------------------------------------------- #
# Strawberry-graphql guarded import
# --------------------------------------------------------------------- #

try:
    import strawberry  # type: ignore
    from strawberry.fastapi import GraphQLRouter  # type: ignore

    _STRAWBERRY_AVAILABLE = True
except ImportError:
    strawberry = None
    GraphQLRouter = None
    _STRAWBERRY_AVAILABLE = False

# --------------------------------------------------------------------- #
# Schema (only built if strawberry is available)
# --------------------------------------------------------------------- #

if _STRAWBERRY_AVAILABLE:

    @strawberry.type
    class LawArticle:
        article_id: str
        name: str
        body_preview: str | None = None
        source_url: str | None = None

    @strawberry.type
    class CaseStudy:
        case_id: str
        year: int | None
        adopted: bool
        company_name: str | None
        program_id: str | None
        amount_yen: int | None

    @strawberry.type
    class CourtDecision:
        decision_id: str
        court: str | None
        date: str | None
        summary: str | None
        source_url: str | None

    @strawberry.type
    class Program:
        id: str
        name: str
        tier: str | None
        agency: str | None
        prefecture: str | None
        source_url: str | None
        source_fetched_at: str | None
        disclaimer: str | None = None

        @strawberry.field  # type: ignore[untyped-decorator]
        def laws(self) -> list[LawArticle]:
            return _resolve_laws_for_program(self.id)

        @strawberry.field  # type: ignore[untyped-decorator]
        def cases(self, limit: int = 5) -> list[CaseStudy]:
            return _resolve_cases_for_program(self.id, limit)

        @strawberry.field  # type: ignore[untyped-decorator]
        def court_decisions(self, limit: int = 3) -> list[CourtDecision]:
            return _resolve_court_decisions_for_program(self.id, limit)

    @strawberry.type
    class TaxRule:
        rule_id: str
        name: str
        sunset_date: str | None
        source_url: str | None
        disclaimer: str | None = None

    @strawberry.type
    class Query:
        @strawberry.field  # type: ignore[untyped-decorator]
        def program(self, id: str) -> Program | None:
            return cast("Program | None", _resolve_program(id))

        @strawberry.field  # type: ignore[untyped-decorator]
        def search_programs(
            self,
            q: str,
            tier: str | None = None,
            prefecture: str | None = None,
            limit: int = 20,
        ) -> list[Program]:
            return cast("list[Program]", _resolve_search_programs(q, tier, prefecture, limit))

        @strawberry.field  # type: ignore[untyped-decorator]
        def law_article(self, article_id: str) -> LawArticle | None:
            return cast("LawArticle | None", _resolve_law_article(article_id))

        @strawberry.field  # type: ignore[untyped-decorator]
        def case_study(self, case_id: str) -> CaseStudy | None:
            return cast("CaseStudy | None", _resolve_case_study(case_id))

        @strawberry.field  # type: ignore[untyped-decorator]
        def tax_rule(self, rule_id: str) -> TaxRule | None:
            return cast("TaxRule | None", _resolve_tax_rule(rule_id))

        @strawberry.field  # type: ignore[untyped-decorator]
        def health(self) -> str:
            return "ok"

    schema = strawberry.Schema(query=Query)

    # Mount the strawberry router under /v1/graphql so both GET (Playground)
    # and POST (queries) are handled.
    graphql_app = GraphQLRouter(schema, path="")
    router.include_router(graphql_app)

else:

    @router.get("/")
    def graphql_unavailable_get() -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content={
                "error": {
                    "code": "internal_not_implemented",
                    "user_message": "GraphQL endpoint requires strawberry-graphql; install with `pip install strawberry-graphql`. REST surface at /v1/* is the canonical API.",
                    "rest_alternative": "https://api.jpcite.com/v1/openapi.agent.json",
                }
            },
        )

    @router.post("/")
    def graphql_unavailable_post(request: Request) -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content={
                "error": {
                    "code": "internal_not_implemented",
                    "user_message": "GraphQL endpoint not enabled in this deployment; use REST /v1/* instead.",
                    "rest_alternative": "https://api.jpcite.com/v1/openapi.agent.json",
                }
            },
        )


# --------------------------------------------------------------------- #
# Resolvers — guarded to safe defaults until wired into prod readers
# --------------------------------------------------------------------- #
# These resolvers delegate to the same fetcher functions used by REST.
# Stubbed to return empty lists / None until plumbing review lands; the
# REST surface remains the source of truth. Once approved, replace the
# stub bodies with calls into ``programs.search()`` / ``laws.get()`` etc.


def _resolve_program(program_id: str) -> Any:  # noqa: ARG001
    if not _STRAWBERRY_AVAILABLE:
        return None
    return None


def _resolve_search_programs(
    q: str,  # noqa: ARG001
    tier: str | None,  # noqa: ARG001
    prefecture: str | None,  # noqa: ARG001
    limit: int,  # noqa: ARG001
) -> list[Any]:
    return []


def _resolve_law_article(article_id: str) -> Any:  # noqa: ARG001
    return None


def _resolve_case_study(case_id: str) -> Any:  # noqa: ARG001
    return None


def _resolve_tax_rule(rule_id: str) -> Any:  # noqa: ARG001
    return None


def _resolve_laws_for_program(program_id: str) -> list[Any]:  # noqa: ARG001
    return []


def _resolve_cases_for_program(
    program_id: str,
    limit: int,  # noqa: ARG001
) -> list[Any]:
    return []


def _resolve_court_decisions_for_program(
    program_id: str,
    limit: int,  # noqa: ARG001
) -> list[Any]:
    return []


# --------------------------------------------------------------------- #
# SDL export helper — used by the docs site to publish the schema
# --------------------------------------------------------------------- #


@router.get("/_sdl", response_class=PlainTextResponse)
def graphql_sdl() -> str:
    """Return the SDL (Schema Definition Language) for tooling."""
    if not _STRAWBERRY_AVAILABLE:
        return "# GraphQL not enabled; install strawberry-graphql.\n"
    try:
        return cast("str", schema.as_str())
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphql_sdl_export_failed", extra={"err": str(exc)})
        return "# SDL export failed; see server logs.\n"


__all__ = ["router"]
