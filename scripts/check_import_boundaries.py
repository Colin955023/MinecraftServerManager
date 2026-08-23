"""
匯入邊界檢查（強制關卡，取代人工稽核表格）。

檢查兩項規則：
1. 禁止繞過套件門面的深層匯入（例如 from src.core.mods.mod_manager import X，
   所有程式碼皆應改寫為 from src.core import X）。
2. 禁止在 src/<子資料夾>/<子子資料夾>/ 建立 __init__.py。

執行：uv run scripts/check_import_boundaries.py
"""

from __future__ import annotations

import ast
import logging
import pathlib
import sys

ROOT = pathlib.Path("src")
TOP_LEVEL = {"core", "models", "ui", "utils"}


def _check_file(path: pathlib.Path) -> list[str]:
    """回傳單一檔案的違規清單。"""
    parts = path.relative_to(ROOT).parts
    if path.name == "__init__.py" and len(parts) > 2:
        return [f"{path}：禁止在二層子資料夾建立 __init__.py"]

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        modules: tuple[str, ...]
        if isinstance(node, ast.ImportFrom) and node.module:
            modules = (node.module,)
        elif isinstance(node, ast.Import):
            modules = tuple(alias.name for alias in node.names)
        else:
            continue
        for module in modules:
            if not module.startswith("src."):
                continue
            mod_parts = module.split(".")
            if len(mod_parts) > 2 and mod_parts[1] in TOP_LEVEL:
                violations.append(
                    f"{path}:{node.lineno}：深層匯入 `{module}`，應改為 `from src.{mod_parts[1]} import ...`"
                )
    return violations


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])
    violations = [v for p in ROOT.rglob("*.py") for v in _check_file(p)]
    if violations:
        logging.error("❌ 匯入邊界檢查失敗：\n" + "\n".join(violations))
        return 1
    logging.info("✅ 匯入邊界檢查通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
