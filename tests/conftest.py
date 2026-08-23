"""pytest 共用設定"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

TEST_RUNTIME_ROOT = PROJECT_ROOT / ".pytest_cache" / "runtime"
os.environ.setdefault("MSM_USER_DATA_DIR", str(TEST_RUNTIME_ROOT / "data"))
os.environ.setdefault("MSM_LOG_DIR", str(TEST_RUNTIME_ROOT / "log"))
