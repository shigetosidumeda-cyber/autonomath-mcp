"""pytest セットアップ — env を埋めて load_settings() を通す。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MF_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("MF_CLIENT_SECRET", "test-client-secret-which-is-long-enough")
    monkeypatch.setenv("JPCITE_API_KEY", "jpcite_test_dummy_value_xyz")
    monkeypatch.setenv("JPCITE_API_BASE", "https://api.jpcite.com")
    monkeypatch.delenv("ZEIMU_KAIKEI_API_KEY", raising=False)
    monkeypatch.delenv("ZEIMU_KAIKEI_BASE_URL", raising=False)
    monkeypatch.setenv("PLUGIN_BASE_URL", "https://mf-plugin.jpcite.com")
    monkeypatch.setenv("SESSION_SECRET", "0" * 48)
    monkeypatch.setenv("NODE_ENV", "test")
