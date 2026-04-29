"""pytest セットアップ — env を埋めて load_settings() を通す。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MF_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("MF_CLIENT_SECRET", "test-client-secret-which-is-long-enough")
    monkeypatch.setenv("ZEIMU_KAIKEI_API_KEY", "zk_test_dummy_value_xyz")
    monkeypatch.setenv("PLUGIN_BASE_URL", "https://mf-plugin.zeimu-kaikei.ai")
    monkeypatch.setenv("SESSION_SECRET", "0" * 48)
    monkeypatch.setenv("NODE_ENV", "test")
