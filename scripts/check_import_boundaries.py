"""
匯入與公開 facade 邊界檢查。

強制規則：
1. `src/` 內禁止繞過頂層套件 facade 的深層匯入。
2. 禁止在 `src/<頂層>/<子資料夾>/` 建立 `__init__.py`。
3. `src/{core,models,ui,utils}/__init__.py` 的 lazy export 目標必須真實存在。
4. 每個 lazy export 必須在 production、tests、scripts 或 report 中有實際 consumer，
   避免累積沒有呼叫端的公開 API。

執行：uv run scripts/check_import_boundaries.py
"""

from __future__ import annotations

import ast
import logging
import pathlib
import re
import sys
from collections import defaultdict
from collections.abc import Iterable

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TOP_LEVEL = frozenset({"core", "models", "ui", "utils"})
FACADE_MODULES = tuple(f"src.{name}" for name in sorted(TOP_LEVEL))
CONSUMER_ROOTS = tuple(REPO_ROOT / name for name in ("src", "tests", "scripts", "report"))


def _parse_source(path: pathlib.Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        source = re.sub(
            r"(?m)^(\s*)except\s+([^():\n]+(?:,\s*[^():\n]+)+):$",
            lambda match: f"{match.group(1)}except ({match.group(2)}):",
            source,
        )
        return ast.parse(source, filename=str(path))


def _python_files(roots: Iterable[pathlib.Path]) -> list[pathlib.Path]:
    return sorted(path for root in roots if root.exists() for path in root.rglob("*.py"))


def _check_import_file(path: pathlib.Path) -> list[str]:
    parts = path.relative_to(SRC_ROOT).parts
    if path.name == "__init__.py" and len(parts) > 2:
        return [f"{path.relative_to(REPO_ROOT)}：禁止在二層子資料夾建立 __init__.py"]

    tree = _parse_source(path)
    violations: list[str] = []
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
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}：深層匯入 `{module}`，"
                    f"應改為 `from src.{mod_parts[1]} import ...`"
                )
    return violations


def _load_exports(init_path: pathlib.Path) -> dict[str, tuple[str, str]]:
    tree = _parse_source(init_path)
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_EXPORTS"
            and node.value is not None
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict):
                return value
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_EXPORTS" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict):
                return value
    return {}


def _module_path(module_name: str) -> pathlib.Path:
    return REPO_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")


def _resolve_export_module(facade: str, module_name: str) -> str:
    if module_name.startswith("."):
        return facade + module_name
    return module_name


def _top_level_symbols(tree: ast.Module) -> set[str]:
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.add(node.target.id)
        elif isinstance(node, ast.Import):
            symbols.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            symbols.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
    return symbols


def _attribute_chain(node: ast.Attribute) -> tuple[str, ...] | None:
    parts: list[str] = [node.attr]
    current: ast.AST = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return tuple(parts)


def _collect_facade_consumers(files: Iterable[pathlib.Path]) -> dict[str, set[str]]:
    consumed: dict[str, set[str]] = defaultdict(set)
    for path in files:
        tree = _parse_source(path)
        aliases: dict[str, str] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in FACADE_MODULES:
                    for alias in node.names:
                        if alias.name != "*":
                            consumed[node.module].add(alias.name)
                elif node.module == "src":
                    for alias in node.names:
                        facade = f"src.{alias.name}"
                        if facade in FACADE_MODULES:
                            aliases[alias.asname or alias.name] = facade
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FACADE_MODULES:
                        aliases[alias.asname or alias.name.rsplit(".", 1)[-1]] = alias.name
                    elif alias.name == "src":
                        aliases[alias.asname or "src"] = "src"

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = _attribute_chain(node)
            if not chain:
                continue
            root = chain[0]
            mapped = aliases.get(root)
            if mapped in FACADE_MODULES and len(chain) >= 2:
                consumed[mapped].add(chain[1])
                continue
            if mapped == "src" and len(chain) >= 3:
                facade = f"src.{chain[1]}"
                if facade in FACADE_MODULES:
                    consumed[facade].add(chain[2])
    return consumed


def _check_lazy_exports(consumer_files: list[pathlib.Path]) -> list[str]:
    violations: list[str] = []
    consumers = _collect_facade_consumers(consumer_files)

    for facade in FACADE_MODULES:
        init_path = REPO_ROOT.joinpath(*facade.split("."), "__init__.py")
        exports = _load_exports(init_path)
        for export_name, target in exports.items():
            if not isinstance(target, tuple) or len(target) != 2:
                violations.append(f"{init_path.relative_to(REPO_ROOT)}：`{export_name}` lazy export 格式無效")
                continue
            module_name, attr_name = target
            resolved_module = _resolve_export_module(facade, module_name)
            target_path = _module_path(resolved_module)
            if not target_path.exists():
                violations.append(
                    f"{init_path.relative_to(REPO_ROOT)}：`{export_name}` 指向不存在模組 `{resolved_module}`"
                )
                continue
            target_symbols = _top_level_symbols(_parse_source(target_path))
            if attr_name not in target_symbols:
                violations.append(
                    f"{init_path.relative_to(REPO_ROOT)}：`{export_name}` 指向 `{resolved_module}.{attr_name}`，"
                    "但目標符號不存在"
                )
            if export_name not in consumers.get(facade, set()):
                violations.append(
                    f"{init_path.relative_to(REPO_ROOT)}：lazy export `{export_name}` 沒有 production/test/script/report consumer"
                )
    return violations


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])

    src_files = _python_files((SRC_ROOT,))
    consumer_files = _python_files(CONSUMER_ROOTS)
    violations = [violation for path in src_files for violation in _check_import_file(path)]
    violations.extend(_check_lazy_exports(consumer_files))
    if violations:
        logging.error("❌ 匯入／公開 facade 邊界檢查失敗：\n" + "\n".join(violations))
        return 1
    logging.info("✅ 匯入／公開 facade 邊界檢查通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
