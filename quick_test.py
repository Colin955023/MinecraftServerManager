#!/usr/bin/env python3
"""快速 smoke 測試入口。

執行 pytest 的 smoke 測試子集（等同於在專案根目錄執行：
`pytest -m smoke -q tests/`）。只會跑標記為 `smoke` 的快速、關鍵路徑
測試，用來在本機或 CI 上做基本健康檢查。

結果解讀：
- 退出碼 0：所有 smoke 測試通過。
- 非 0：至少有一個 smoke 測試失敗，或 pytest 發生錯誤。
"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    try:
        import pytest
    except Exception:
        print("找不到 pytest，請先執行: uv sync --all-groups")
        return 1

    project_root = Path(__file__).resolve().parent
    return pytest.main(["-m", "smoke", "-q", str(project_root / "tests")])


if __name__ == "__main__":
    raise SystemExit(main())
