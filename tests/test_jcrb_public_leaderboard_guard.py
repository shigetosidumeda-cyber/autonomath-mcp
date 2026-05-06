from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "cron" / "jcrb_publish_results.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("jcrb_publish_results", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _submission(mod, *, mode: str = "with_jpcite") -> dict:
    return {
        "model": "frontier-test",
        "provider": "test",
        "mode": mode,
        "submitted_at": "2026-05-06T00:00:00Z",
        "submitter": "external verified",
        "n": 100,
        "exact_match": 0.6,
        "citation_ok": 0.9,
        "by_domain": {
            domain: {"n": 20, "exact_match": 0.6, "citation_ok": 0.9} for domain in mod.DOMAINS
        },
        "questions_sha256": mod.EXPECTED_QUESTIONS_SHA256,
    }


def test_jcrb_loader_keeps_seed_examples_out_of_verified_leaderboard(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    (tmp_path / "verified.json").write_text(
        json.dumps(_submission(mod), ensure_ascii=False),
        encoding="utf-8",
    )
    seed = _submission(mod, mode="without_jpcite")
    seed["submitter"] = "bookyou (seed estimate, not validated)"
    seed["questions_sha256"] = "seed-not-validated"
    (tmp_path / "SEED_frontier_without.json").write_text(
        json.dumps(seed, ensure_ascii=False),
        encoding="utf-8",
    )

    verified, seed_examples = mod._load_submissions(tmp_path)
    leaderboard = mod._build_leaderboard(verified)

    assert len(verified) == 1
    assert len(seed_examples) == 1
    assert all("seed estimate" not in row.get("submitter", "") for row in verified)
    assert len(leaderboard) == 1
    assert "without_exact_match" not in leaderboard[0]


def test_jcrb_loader_rejects_bad_hash_and_bad_domain_shape(tmp_path: Path) -> None:
    mod = _load_module()
    bad_hash = _submission(mod)
    bad_hash["questions_sha256"] = "bad"
    (tmp_path / "bad_hash.json").write_text(
        json.dumps(bad_hash, ensure_ascii=False),
        encoding="utf-8",
    )
    bad_domain = _submission(mod)
    bad_domain["by_domain"]["subsidy_eligibility"]["n"] = 19
    (tmp_path / "bad_domain.json").write_text(
        json.dumps(bad_domain, ensure_ascii=False),
        encoding="utf-8",
    )

    verified, seed_examples = mod._load_submissions(tmp_path)

    assert verified == []
    assert seed_examples == []


def test_jcrb_outputs_verified_and_seed_channels_separately(tmp_path: Path) -> None:
    mod = _load_module()
    verified = [_submission(mod)]
    seed = _submission(mod, mode="without_jpcite")
    seed["submitter"] = "bookyou (seed estimate, not validated)"
    leaderboard = mod._build_leaderboard(verified)
    original_out = mod.SITE_OUT_DIR
    try:
        mod.SITE_OUT_DIR = tmp_path
        mod._write_outputs(leaderboard, verified, [seed])
    finally:
        mod.SITE_OUT_DIR = original_out

    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))

    assert data["leaderboard"] == data["leaderboard_verified"]
    assert data["raw_submissions"] == verified
    assert data["seed_examples"] == [seed]
    assert "seed_examples are illustrative estimates" in data["notes"][1]
