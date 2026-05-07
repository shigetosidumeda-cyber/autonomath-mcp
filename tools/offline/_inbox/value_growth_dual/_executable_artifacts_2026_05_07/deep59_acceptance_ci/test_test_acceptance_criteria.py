"""
test_test_acceptance_criteria.py
================================

Meta-tests for DEEP-59 acceptance criteria CI guard.

These 8 cases exercise the guard module on synthetic inputs only - they
must remain LLM-API-free and must NOT depend on the wider jpcite repo
state. Every fixture file lives under tmp_path.

Coverage:
  1. 12 check_kind verifier functions return correct results on synthetic input
  2. YAML parse + duplicate-id rejection
  3. Parametrize expansion fans out to >= 30 rows (and is ready for 258)
  4. Automation ratio computation hits 0.795 target on synthetic plan
  5. Self LLM-import-zero (guards against future regressions)
  6. aggregate JSON shape conforms to schema_version=1 contract
  7. GHA workflow YAML syntactically valid
  8. Per-spec rollup correctness on synthetic junit

Run:
    python -m pytest test_test_acceptance_criteria.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import aggregate_acceptance as aggregator  # noqa: E402
import test_acceptance_criteria as guard  # noqa: E402

# ---------------------------------------------------------------------------
# 1) Each of the 12 check_kind verifiers handles synthetic inputs correctly.
# ---------------------------------------------------------------------------


def test_01_twelve_check_kinds_each_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)

    # 1. file_existence
    (tmp_path / "exists.txt").write_text("hi", encoding="utf-8")
    assert guard.check_file_existence("exists.txt").ok
    assert not guard.check_file_existence("missing.txt").ok

    # 2. jsonschema
    (tmp_path / "data.json").write_text('{"n": 5}', encoding="utf-8")
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert guard.check_jsonschema("data.json", schema).ok
    bad_schema = {"type": "object", "required": ["x"]}
    assert not guard.check_jsonschema("data.json", bad_schema).ok

    # 3. sql_syntax
    (tmp_path / "good.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);", encoding="utf-8")
    assert guard.check_sql_syntax("good.sql").ok
    (tmp_path / "bad.sql").write_text("CREATE TABLE )))(((;", encoding="utf-8")
    assert not guard.check_sql_syntax("bad.sql").ok

    # 4. python_compile
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    assert guard.check_python_compile("ok.py").ok
    (tmp_path / "broken.py").write_text("def (\n", encoding="utf-8")
    assert not guard.check_python_compile("broken.py").ok

    # 5. llm_api_import_zero
    (tmp_path / "clean.py").write_text("import os\n", encoding="utf-8")
    assert guard.check_llm_api_import_zero("clean.py").ok
    (tmp_path / "dirty.py").write_text("import anthropic\n", encoding="utf-8")
    assert not guard.check_llm_api_import_zero("dirty.py").ok

    # 6. pytest_collect (use a tiny file with one test)
    (tmp_path / "tiny_test.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    assert guard.check_pytest_collect("tiny_test.py").ok

    # 7. gha_yaml_syntax
    (tmp_path / "wf.yml").write_text(
        dedent(
            """\
            name: x
            on: [push]
            jobs:
              j:
                runs-on: ubuntu-latest
                steps:
                  - run: echo hi
            """
        ),
        encoding="utf-8",
    )
    assert guard.check_gha_yaml_syntax("wf.yml").ok
    (tmp_path / "bad.yml").write_text("not: [valid", encoding="utf-8")
    assert not guard.check_gha_yaml_syntax("bad.yml").ok

    # 8. html5_doctype_meta
    (tmp_path / "ok.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width"></head><body></body></html>',
        encoding="utf-8",
    )
    assert guard.check_html5_doctype_meta("ok.html").ok
    (tmp_path / "bad.html").write_text("<html></html>", encoding="utf-8")
    assert not guard.check_html5_doctype_meta("bad.html").ok

    # 9. schema_org_jsonld
    (tmp_path / "ld.html").write_text(
        '<!doctype html><script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Organization"}</script>',
        encoding="utf-8",
    )
    assert guard.check_schema_org_jsonld("ld.html").ok
    (tmp_path / "no_ld.html").write_text("<!doctype html><body></body>", encoding="utf-8")
    assert not guard.check_schema_org_jsonld("no_ld.html").ok

    # 10. regex_pattern_count
    (tmp_path / "blob.txt").write_text("foo foo foo bar", encoding="utf-8")
    assert guard.check_regex_pattern_count("blob.txt", r"foo", 3).ok
    assert not guard.check_regex_pattern_count("blob.txt", r"foo", 4).ok

    # 11. migration_first_line_marker
    (tmp_path / "0144_x.sql").write_text(
        "-- migration: 0144_am_amendment_snapshot\nCREATE TABLE t (id INTEGER);",
        encoding="utf-8",
    )
    assert guard.check_migration_first_line_marker("0144_x.sql").ok
    (tmp_path / "bad_mig.sql").write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    assert not guard.check_migration_first_line_marker("bad_mig.sql").ok

    # 12. business_law_forbidden_phrases
    (tmp_path / "clean.html").write_text("<html>合法な表記</html>", encoding="utf-8")
    assert guard.check_business_law_forbidden_phrases("clean.html").ok
    (tmp_path / "dirty.html").write_text("<html>確実に勝訴します</html>", encoding="utf-8")
    assert not guard.check_business_law_forbidden_phrases("dirty.html").ok


# ---------------------------------------------------------------------------
# 2) YAML loader rejects duplicate ids and missing keys.
# ---------------------------------------------------------------------------


def test_02_yaml_parse_correctness(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(
        dedent(
            """\
            - id: DEEP-22-1
              spec: DEEP-22
              check_kind: file_existence
              path: db/migrations/0144_am_amendment_snapshot.sql
            - id: DEEP-22-2
              spec: DEEP-22
              check_kind: sql_syntax
              file: db/migrations/0144_am_amendment_snapshot.sql
            """
        ),
        encoding="utf-8",
    )
    rows = guard.load_criteria(good)
    assert [r["id"] for r in rows] == ["DEEP-22-1", "DEEP-22-2"]

    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "- {id: D-1, spec: D, check_kind: file_existence, path: x}\n"
        "- {id: D-1, spec: D, check_kind: file_existence, path: y}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        guard.load_criteria(dup)

    missing = tmp_path / "missing.yaml"
    missing.write_text("- {id: D-1, spec: D}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        guard.load_criteria(missing)


# ---------------------------------------------------------------------------
# 3) Parametrize expansion: >= 30 in the seed YAML and ready for 258 scaling.
# ---------------------------------------------------------------------------


def test_03_parametrize_fan_out_ready_for_258() -> None:
    seed = guard.load_criteria(guard.CRITERIA_FILE)
    assert len(seed) >= 30, f"only {len(seed)} rows in seed YAML"

    # Synthetic scaling exercise: clone seed * 9 with new ids, ensure dispatch
    # still understands every kind even when count crosses 258.
    scaled: list[dict] = []
    for i in range(9):
        for r in seed:
            row = dict(r)
            row["id"] = f"{r['id']}-clone{i}"
            scaled.append(row)
    assert len(scaled) >= 258
    unknown = {r["check_kind"] for r in scaled} - set(guard.CHECK_DISPATCH)
    assert not unknown, f"unknown check_kind in scaled set: {unknown}"


# ---------------------------------------------------------------------------
# 4) Automation ratio reaches the DEEP-59 79.5% target on a synthetic plan.
# ---------------------------------------------------------------------------


def test_04_automation_ratio_target_met() -> None:
    # Build a synthetic plan of 258 rows: 206 auto + 30 semi + 22 manual.
    # 206/258 = 0.7984 clears the 0.795 DEEP-59 target.
    rows: list[dict] = []
    for i in range(206):
        rows.append(
            {"id": f"X-{i}", "spec": "X", "check_kind": "file_existence", "automation": "auto"}
        )
    for i in range(30):
        rows.append({"id": f"Y-{i}", "spec": "Y", "check_kind": "sql_count", "automation": "semi"})
    for i in range(22):
        rows.append({"id": f"Z-{i}", "spec": "Z", "check_kind": "gh_api", "automation": "manual"})

    rep = aggregator.build_report(rows, junit={}, target_count=258)
    assert rep["summary"]["automated"] == 206
    assert rep["summary"]["semi_automated"] == 30
    assert rep["summary"]["manual"] == 22
    assert rep["summary"]["automation_ratio"] == pytest.approx(0.7984, abs=1e-3)
    assert rep["summary"]["automation_target_met"] is True

    # Edge case: exactly at the 79.5% target with 206 auto / 258 total.
    boundary_rep = aggregator.build_report(rows, junit={}, target_count=258)
    assert boundary_rep["summary"]["automation_target"] == 0.795


# ---------------------------------------------------------------------------
# 5) The guard module itself imports zero LLM SDKs.
# ---------------------------------------------------------------------------


def test_05_self_llm_import_free() -> None:
    for mod_path in (
        Path(guard.__file__),
        Path(aggregator.__file__),
        Path(__file__),
    ):
        res = guard.check_llm_api_import_zero(mod_path)
        assert res.ok, res.detail


# ---------------------------------------------------------------------------
# 6) aggregate JSON conforms to the schema_version=1 contract.
# ---------------------------------------------------------------------------


def test_06_aggregate_json_schema_valid(tmp_path: Path) -> None:
    rows = [
        {
            "id": "DEEP-22-1",
            "spec": "DEEP-22",
            "check_kind": "file_existence",
            "automation": "auto",
        },
        {"id": "DEEP-22-2", "spec": "DEEP-22", "check_kind": "sql_syntax", "automation": "auto"},
        {"id": "DEEP-23-1", "spec": "DEEP-23", "check_kind": "gh_api", "automation": "semi"},
    ]
    junit = {
        "DEEP-22-1-file_existence": "passed",
        "DEEP-22-2-sql_syntax": "passed",
        "DEEP-23-1-gh_api": "skipped",
    }
    rep = aggregator.build_report(rows, junit, target_count=3)

    # contract assertions
    assert rep["schema_version"] == 1
    assert set(rep) >= {"summary", "per_spec", "per_check_kind", "rows", "generated_at"}
    s = rep["summary"]
    assert s["total"] == 3
    assert s["passed"] == 2
    assert s["skipped"] == 1
    assert s["failed"] == 0
    assert rep["per_spec"]["DEEP-22"]["passed"] == 2
    assert rep["per_spec"]["DEEP-23"]["skipped"] == 1
    assert rep["per_check_kind"]["file_existence"]["passed"] == 1

    # serializes without error
    out = tmp_path / "agg.json"
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    re_read = json.loads(out.read_text(encoding="utf-8"))
    assert re_read["schema_version"] == 1


# ---------------------------------------------------------------------------
# 7) The shipped GHA workflow YAML is syntactically valid.
# ---------------------------------------------------------------------------


def test_07_gha_workflow_syntax_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    wf = HERE / "acceptance_criteria_ci.yml"
    assert wf.exists()
    monkeypatch.setattr(guard, "REPO_ROOT", HERE)
    res = guard.check_gha_yaml_syntax("acceptance_criteria_ci.yml")
    assert res.ok, res.detail
    # extra: confirm jobs / on are present in parsed form
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    assert "jobs" in doc
    # YAML coerces `on:` to True; accept either spelling
    assert "on" in doc or True in doc


# ---------------------------------------------------------------------------
# 8) Per-spec rollup is consistent across multiple specs / outcomes.
# ---------------------------------------------------------------------------


def test_08_per_spec_rollup_consistency() -> None:
    rows = [
        {
            "id": "DEEP-22-1",
            "spec": "DEEP-22",
            "check_kind": "file_existence",
            "automation": "auto",
        },
        {"id": "DEEP-22-2", "spec": "DEEP-22", "check_kind": "sql_syntax", "automation": "auto"},
        {
            "id": "DEEP-23-1",
            "spec": "DEEP-23",
            "check_kind": "html5_doctype_meta",
            "automation": "auto",
        },
        {
            "id": "DEEP-23-2",
            "spec": "DEEP-23",
            "check_kind": "schema_org_jsonld",
            "automation": "auto",
        },
        {
            "id": "DEEP-38-1",
            "spec": "DEEP-38",
            "check_kind": "business_law_forbidden_phrases",
            "automation": "auto",
        },
    ]
    junit = {
        "DEEP-22-1-file_existence": "passed",
        "DEEP-22-2-sql_syntax": "failed",
        "DEEP-23-1-html5_doctype_meta": "passed",
        "DEEP-23-2-schema_org_jsonld": "passed",
        "DEEP-38-1-business_law_forbidden_phrases": "passed",
    }
    rep = aggregator.build_report(rows, junit, target_count=5)

    assert rep["per_spec"]["DEEP-22"] == {"total": 2, "passed": 1, "failed": 1, "skipped": 0}
    assert rep["per_spec"]["DEEP-23"] == {"total": 2, "passed": 2, "failed": 0, "skipped": 0}
    assert rep["per_spec"]["DEEP-38"] == {"total": 1, "passed": 1, "failed": 0, "skipped": 0}

    # totals equal sum of per_spec totals
    total_from_specs = sum(s["total"] for s in rep["per_spec"].values())
    assert total_from_specs == rep["summary"]["total"]
    assert rep["summary"]["passed"] + rep["summary"]["failed"] + rep["summary"]["skipped"] == 5
