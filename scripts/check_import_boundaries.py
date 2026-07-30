"""
匯入邊界檢查（強制關卡，取代人工稽核表格）。

檢查兩項規則：
1. 禁止繞過套件門面的深層匯入（例如 from src.core.mod_manager import X，
   非 core 內部程式碼應改寫為 from src.core import X）。
2. 禁止在 src/<子資料夾>/<子子資料夾>/ 建立 __init__.py。

執行：uv run scripts/check_import_boundaries.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path("src")
TOP_LEVEL = {"core", "models", "ui", "utils"}


def _check_file(path: pathlib.Path) -> list[str]:
    """回傳單一檔案的違規清單。"""
    parts = path.relative_to(ROOT).parts
    owner = parts[0]

    if path.name == "__init__.py" and len(parts) > 2:
        return [f"{path}：禁止在二層子資料夾建立 __init__.py"]

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src.")):
            continue
        mod_parts = node.module.split(".")
        if len(mod_parts) > 2 and mod_parts[1] in TOP_LEVEL and mod_parts[1] != owner:
            violations.append(
                f"{path}:{node.lineno}：深層匯入 `{node.module}`，應改為 `from src.{mod_parts[1]} import ...`"
            )
    return violations


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    violations = [v for p in ROOT.rglob("*.py") for v in _check_file(p)]
    if violations:
        print("❌ 匯入邊界檢查失敗：\n" + "\n".join(violations))  # noqa: T201
        return 1
    print("✅ 匯入邊界檢查通過")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
