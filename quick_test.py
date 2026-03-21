#!/usr/bin/env python3
"""快速 smoke 測試入口。

執行 pytest 的 smoke 測試子集，固定透過 `uv run --isolated` 運行：
`uv run --isolated pytest -m smoke -q tests/`。
只會跑標記為 `smoke` 的快速、關鍵路徑測試，用來在本機或 CI 上做基本健康檢查。

結果解讀：
- 退出碼 0：所有 smoke 測試通過。
- 非 0：至少有一個 smoke 測試失敗，或 pytest 發生錯誤。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    uv_path = shutil.which("uv")
    if uv_path is None:
        sys.stderr.write("quick_test requires `uv` to be installed and available in PATH.\n")
        return 1

    project_root = Path(__file__).resolve().parent
    cmd = [
        uv_path,
        "run",
        "--isolated",
        "pytest",
        "-m",
        "smoke",
        "-q",
        str(project_root / "tests"),
    ]
    try:
        completed = subprocess.run(cmd, cwd=project_root, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"quick_test failed to run pytest via uv: {exc}\n")
        return 1
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
