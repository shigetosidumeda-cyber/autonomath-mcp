"""Read-only tests for the M10 OpenSearch export/check script."""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import types

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/aws_credit_ops/opensearch_m10_export_check_2026_05_17.py"


def _load_script_module(alias: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(alias, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m10_export_module() -> types.ModuleType:
    return _load_script_module("m10_opensearch_export_check_test")


def test_m10_export_script_has_no_mutating_opensearch_calls() -> None:
    source = SCRIPT_PATH.read_text()
    forbidden_tokens = [
        "create_domain",
        "update_domain_config",
        "delete_domain",
        "_bulk",
        "_delete_by_query",
        "_reindex",
        'method="PUT"',
        'method="DELETE"',
        'method="PATCH"',
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_m10_export_script_only_posts_to_search() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method_kw = next((kw for kw in node.keywords if kw.arg == "method"), None)
        if not isinstance(method_kw, ast.keyword):
            continue
        if not isinstance(method_kw.value, ast.Constant) or method_kw.value.value != "POST":
            continue
        url_kw = next((kw for kw in node.keywords if kw.arg == "url"), None)
        assert url_kw is not None
        assert ast.unparse(url_kw.value).rstrip("'\"").endswith("/_search")


def test_m10_search_body_is_bounded_and_excludes_large_fields(
    m10_export_module: types.ModuleType,
) -> None:
    body = m10_export_module._search_body(query="中小企業 補助金 東京", top_n=99)
    assert body["size"] == 25
    assert body["_source"]["excludes"] == ["body", "embedding"]
    multi_match = body["query"]["bool"]["should"][0]["multi_match"]
    assert multi_match["fields"] == ["title^3", "body"]
    assert multi_match["query"] == "中小企業 補助金 東京"


def test_m10_signed_request_blocks_mutating_methods(m10_export_module: types.ModuleType) -> None:
    with pytest.raises(ValueError):
        m10_export_module._signed_request(
            session=object(),
            method="DELETE",
            url="https://example.com/index",
            body=None,
            region="ap-northeast-1",
        )
    with pytest.raises(ValueError):
        m10_export_module._signed_request(
            session=object(),
            method="POST",
            url="https://example.com/index/_bulk",
            body="{}",
            region="ap-northeast-1",
        )


def test_m10_json_loads_preserves_non_json_error_body(
    m10_export_module: types.ModuleType,
) -> None:
    parsed = m10_export_module._json_loads("<html>bad gateway</html>")
    assert "_json_parse_error" in parsed
    assert parsed["_raw"] == "<html>bad gateway</html>"


def test_m10_export_writes_expected_artifacts(
    m10_export_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeSession:
        pass

    def fake_session(*, profile: str, region: str) -> FakeSession:
        assert profile == "bookyou-recovery"
        assert region == "ap-northeast-1"
        return FakeSession()

    def fake_describe_domain(_session: FakeSession, *, domain: str) -> dict[str, Any]:
        assert domain == "jpcite-xfact-2026-05"
        return {
            "DomainStatus": {
                "DomainName": domain,
                "Endpoint": "search.example.ap-northeast-1.es.amazonaws.com",
                "EngineVersion": "OpenSearch_2.13",
            }
        }

    def fake_signed_request(
        *,
        session: FakeSession,
        method: str,
        url: str,
        body: str | None,
        region: str,
    ) -> tuple[int, str]:
        assert isinstance(session, FakeSession)
        assert region == "ap-northeast-1"
        calls.append((method, url))
        if url.endswith("/_settings"):
            return 200, json.dumps({"jpcite-corpus-2026-05": {"settings": {"index": {}}}})
        if url.endswith("/_mapping"):
            return 200, json.dumps(
                {
                    "jpcite-corpus-2026-05": {
                        "mappings": {
                            "properties": {
                                "title": {"type": "text"},
                                "body": {"type": "text"},
                                "corpus_kind": {"type": "keyword"},
                            }
                        }
                    }
                }
            )
        if url.endswith("/_count"):
            return 200, json.dumps({"count": 595545})
        assert method == "POST"
        assert url.endswith("/_search")
        assert body is not None
        body_json = json.loads(body)
        assert body_json["_source"]["excludes"] == ["body", "embedding"]
        return 200, json.dumps(
            {
                "took": 12,
                "hits": {
                    "total": {"value": 1, "relation": "eq"},
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_score": 19.2,
                            "_source": {
                                "corpus_kind": "program",
                                "doc_key": "p1",
                                "title": "中小企業補助金",
                                "tier": "A",
                                "prefecture": "東京都",
                                "authority": "東京都",
                                "source_url": "https://example.com",
                            },
                        }
                    ],
                },
            }
        )

    monkeypatch.setattr(m10_export_module, "_session", fake_session)
    monkeypatch.setattr(m10_export_module, "_describe_domain", fake_describe_domain)
    monkeypatch.setattr(m10_export_module, "_signed_request", fake_signed_request)

    summary = m10_export_module.run_export(
        profile="bookyou-recovery",
        region="ap-northeast-1",
        domain="jpcite-xfact-2026-05",
        index="jpcite-corpus-2026-05",
        output_dir=tmp_path,
        run_id="20260517T123456Z",
        queries=["中小企業 補助金 東京", "税額控除 研究開発"],
        top_n=10,
    )

    run_dir = tmp_path / "20260517T123456Z"
    expected = {
        "domain_config.json",
        "index_settings.json",
        "index_mapping.json",
        "index_count.json",
        "query_relevance.jsonl",
        "summary.json",
    }
    assert {path.name for path in run_dir.iterdir()} == expected
    assert summary["document_count"] == 595545
    assert summary["mapping_field_count"] == 3
    assert summary["query_count"] == 2
    assert summary["mutating_operations_executed"] is False
    assert len((run_dir / "query_relevance.jsonl").read_text().splitlines()) == 2
    assert calls == [
        (
            "GET",
            "https://search.example.ap-northeast-1.es.amazonaws.com/jpcite-corpus-2026-05/_settings",
        ),
        (
            "GET",
            "https://search.example.ap-northeast-1.es.amazonaws.com/jpcite-corpus-2026-05/_mapping",
        ),
        (
            "GET",
            "https://search.example.ap-northeast-1.es.amazonaws.com/jpcite-corpus-2026-05/_count",
        ),
        (
            "POST",
            "https://search.example.ap-northeast-1.es.amazonaws.com/jpcite-corpus-2026-05/_search",
        ),
        (
            "POST",
            "https://search.example.ap-northeast-1.es.amazonaws.com/jpcite-corpus-2026-05/_search",
        ),
    ]


def test_m10_dry_run_plan_does_not_create_output_dir(
    m10_export_module: types.ModuleType,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = m10_export_module.main(
        [
            "--dry-run-plan",
            "--output-dir",
            str(tmp_path / "out"),
            "--query",
            "中小企業 補助金 東京",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mutating_operations_executed"] is False
    assert payload["operations"][-1]["path"].endswith("/_search")
    assert not (tmp_path / "out").exists()
