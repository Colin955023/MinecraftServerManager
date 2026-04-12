"""pytest 共用設定。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)


@pytest.fixture(autouse=True)
def _suppress_server_manager_issue_markers(monkeypatch):
    import src.core.server_manager as server_manager_module

    monkeypatch.setattr(server_manager_module, "record_and_mark", lambda *_args, **_kwargs: None)
    yield
    issues_root = PROJECT_ROOT / ".issues"
    if issues_root.exists():
        shutil.rmtree(issues_root, ignore_errors=True)
