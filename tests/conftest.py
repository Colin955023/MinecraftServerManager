"""pytest 共用設定"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

TEST_RUNTIME_ROOT = PROJECT_ROOT / ".pytest_cache" / "runtime"
os.environ.setdefault("MSM_USER_DATA_DIR", str(TEST_RUNTIME_ROOT / "data"))
os.environ.setdefault("MSM_LOG_DIR", str(TEST_RUNTIME_ROOT / "log"))


@pytest.fixture(autouse=True)
def _suppress_server_manager_issue_markers(monkeypatch):
    from src.core.server import server_crud, server_startup

    class DummyExceptionUtils:
        @staticmethod
        def record_and_mark(*args, **kwargs):
            pass

    monkeypatch.setattr(server_crud, "ExceptionUtils", DummyExceptionUtils)
    monkeypatch.setattr(server_startup, "ExceptionUtils", DummyExceptionUtils)
    yield
    issues_root = PROJECT_ROOT / ".issues"
    if issues_root.exists():
        shutil.rmtree(issues_root, ignore_errors=True)
