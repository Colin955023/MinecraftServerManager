"""綜合檢查報告產生器。

功能：
1. 程式碼品質（ruff + mypy + pylint + bandit + vulture + compileall）。
2. 重複程式碼檢查（僅掃描 src 目錄）。
3. UI 硬編碼檢查（尺寸/顏色是否直接寫死，鼓勵使用 ui_utils token）。
4. 隱私與安全檢查（detect-secrets + 內建規則）。
5. 跨檔案 private callable 命名檢查（公開呼叫點不得使用前導底線）。

工具說明：
- ruff: 快速的 Python linter（PEP 8、常見錯誤）
- mypy: 靜態類型檢查
- pylint: 循環引用與程式風格檢查
- bandit: 安全性漏洞檢測
- vulture: 死代碼（未使用的代碼）檢測
- compileall: Python 語法檢查
- detect-secrets: 秘密資訊洩漏檢測

輸出：
- report/comprehensive_report.html
"""

from __future__ import annotations

import ast
import functools
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "report"
HTML_REPORT_PATH = REPORT_DIR / "comprehensive_report.html"
PYTHON_EXECUTABLE = Path(sys.executable)
SCRIPTS_DIR = PYTHON_EXECUTABLE.parent

MAX_DETAIL_ITEMS = 250
TOOL_TIMEOUT_SECONDS = 180
DETECT_SECRETS_BATCH_SIZE = 120
CLI_VERBOSE_LOGS = False

IGNORED_SCAN_DIRS = {".git", ".venv", "build", "dist", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
T = TypeVar("T")

@dataclass(slots=True)
class ToolSpec:
    name: str
    tool_name: str
    args: list[str]
    module_name: str | None = None
    use_python_executable: bool = False

@dataclass(slots=True)
class ToolResult:
    name: str
    status: str
    command: str
    return_code: int | None
    duration_seconds: float
    output: str


@dataclass(slots=True)
class Finding:
    file: str
    line: int
    category: str
    message: str
    sample: str = ""


@dataclass(slots=True)
class SectionResult:
    name: str
    findings: list[Finding]
    meta: dict[str, Any]


@dataclass(slots=True)
class FileContext:
    path: Path
    content: str
    lines: list[str]
    ast_tree: ast.AST | None
    parse_error: str | None = None

FILE_CONTEXT_CACHE: dict[Path, FileContext] = {}

def get_file_context(path: Path) -> FileContext:
    """取得檔案的快取解析內容，減少重複 I/O 與 AST 解析。"""
    if path in FILE_CONTEXT_CACHE:
        return FILE_CONTEXT_CACHE[path]
    
    parse_err = None
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        try:
            tree = ast.parse(content, filename=str(path))
        except SyntaxError as exc:
            tree = None
            parse_err = f"語法解析失敗：{exc.msg} (Line {exc.lineno})"
        ctx = FileContext(path=path, content=content, lines=lines, ast_tree=tree, parse_error=parse_err)
    except OSError as exc:
        ctx = FileContext(path=path, content="", lines=[], ast_tree=None, parse_error=f"讀取失敗：{exc}")
    FILE_CONTEXT_CACHE[path] = ctx
    return ctx


def sanitize_tool_output(text: str) -> str:
    """清理工具輸出中的安裝雜訊，保留關鍵結果。"""
    if not text:
        return text
    lines = text.splitlines()
    filtered = [line for line in lines if not line.strip().startswith("Installed ")]
    return "\n".join(filtered).strip()


@functools.lru_cache(maxsize=128)
def command_exists(cmd: str) -> bool:
    if any(separator in cmd for separator in ("/", "\\")):
        return Path(cmd).exists()
    return shutil.which(cmd) is not None


def resolve_tool_command(tool_name: str, args: list[str], module_name: str | None = None) -> list[str]:
    if module_name:
        return [str(PYTHON_EXECUTABLE), "-m", module_name, *args]

    executable_candidates = [
        SCRIPTS_DIR / tool_name,
        SCRIPTS_DIR / f"{tool_name}.exe",
        SCRIPTS_DIR / f"{tool_name}.cmd",
    ]
    for candidate in executable_candidates:
        if candidate.exists():
            return [str(candidate), *args]
    return [tool_name, *args]


def format_duration(seconds: float) -> str:
    return f"{seconds:.2f}s"


def log_verbose(message: str) -> None:
    if CLI_VERBOSE_LOGS:
        print(message)


def run_command(name: str, command: list[str]) -> ToolResult:
    command_text = " ".join(command)
    log_verbose(f"  [Tool:{name}] start | command={command_text}")
    executable_name = command[0] if command else ""
    if not executable_name or not command_exists(executable_name):
        reason = Path(executable_name).name if executable_name else "missing-command"
        log_verbose(f"  [Tool:{name}] skipped | reason={reason}-not-found | elapsed=0.00s")
        return ToolResult(
            name=name,
            status="unavailable",
            command=command_text,
            return_code=None,
            duration_seconds=0.0,
            output=f"Required tool is not available: {executable_name or '(empty command)'}.",
        )

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        ended = time.perf_counter()
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        merged = sanitize_tool_output("\n".join(part for part in [stdout, stderr] if part))
        timeout_msg = f"Command timed out after {TOOL_TIMEOUT_SECONDS}s."
        output = f"{timeout_msg}\n{merged}".strip()
        elapsed = ended - started
        log_verbose(
            f"  [Tool:{name}] done | status=failed | code=-1 | elapsed={format_duration(elapsed)} | reason=timeout"
        )
        return ToolResult(
            name=name,
            status="failed",
            command=command_text,
            return_code=-1,
            duration_seconds=elapsed,
            output=output,
        )

    ended = time.perf_counter()
    elapsed = ended - started
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    merged = sanitize_tool_output("\n".join(part for part in [stdout, stderr] if part))
    status = "passed" if completed.returncode == 0 else "failed"
    log_verbose(
        f"  [Tool:{name}] done | status={status} | code={completed.returncode} | elapsed={format_duration(elapsed)}"
    )

    return ToolResult(
        name=name,
        status=status,
        command=command_text,
        return_code=completed.returncode,
        duration_seconds=elapsed,
        output=merged,
    )


def run_timed_operation(name: str, operation: Callable[[], T]) -> tuple[T, float]:
    log_verbose(f"  [Task:{name}] start")
    started = time.perf_counter()
    result: T = operation()
    elapsed = time.perf_counter() - started
    log_verbose(f"  [Task:{name}] done | elapsed={format_duration(elapsed)}")
    return result, elapsed


def run_project_tool(name: str, tool_name: str, args: list[str], module_name: str | None = None) -> ToolResult:
    return run_command(name, resolve_tool_command(tool_name, args, module_name=module_name))


def render_category_overview() -> str:
    categories = [
        ("程式碼品質", "ruff、mypy、pylint、bandit、vulture、compileall", "靜態分析、型別、循環引用、安全、死代碼與語法檢查"),
        ("API 命名", "內建 cross-file private callable scanner", "掃描 runtime code 中跨檔案呼叫的 callable 是否誤用前導底線（排除 tests）"),
        ("重複程式碼", "內建 duplicate scanner", "掃描 src 內高相似度且連續重複的程式碼區塊"),
        ("UI 硬編碼", "內建 ui hardcode scanner", "檢查色碼、尺寸與字型大小是否直接寫死"),
        ("註解整潔", "ruff ERA、eradicate", "找出已註解掉但仍殘留在專案中的舊程式碼"),
        ("隱私資訊", "detect-secrets、內建 privacy regex", "檢查疑似密鑰、token、帳密與敏感字串"),
    ]
    items = "".join(
        (
            '<div class="category-card">'
            f'<div class="category-title">{html.escape(name)}</div>'
            f'<div class="category-tools">工具：{html.escape(tools)}</div>'
            f'<div class="category-purpose">用途：{html.escape(purpose)}</div>'
            "</div>"
        )
        for name, tools, purpose in categories
    )
    return f'<div class="category-grid">{items}</div>'


def collect_code_quality_results() -> list[ToolResult]:
    specs = [
        ToolSpec(
            name="ruff",
            tool_name="ruff",
            module_name="ruff",
            args=["check", "src", "tests", "quick_test.py"]
        ),
        ToolSpec(
            name="mypy",
            tool_name="mypy",
            module_name="mypy",
            args=["src"]
        ),
        ToolSpec(
            name="pylint",
            tool_name="pylint",
            module_name="pylint",
            args=["--disable=all", "--enable=cyclic-import", "src"]
        ),
        ToolSpec(
            name="bandit",
            tool_name="bandit",
            module_name="bandit",
            args=["-r", "src"]
        ),
        ToolSpec(
            name="vulture",
            tool_name="vulture",
            module_name="vulture",
            args=["src", "--min-confidence=80"]
        ),
        ToolSpec(
            name="compileall",
            tool_name="python",
            args=["-m", "compileall", "-q", "src"],
            use_python_executable=True
        ),
    ]

    def execute_spec(spec: ToolSpec) -> ToolResult:
        if spec.use_python_executable:
            return run_command(spec.name, [str(PYTHON_EXECUTABLE), *spec.args])
        return run_project_tool(spec.name, spec.tool_name, spec.args, module_name=spec.module_name)

    with ThreadPoolExecutor() as executor:
        return list(executor.map(execute_spec, specs))


def gather_python_files(base_dir: Path) -> list[Path]:
    return sorted(
        path for path in base_dir.rglob("*.py")
        if path.is_file() and not any(part in IGNORED_SCAN_DIRS for part in path.parts)
    )


def gather_repo_files(base_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in base_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_SCAN_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def normalize_code_line(line: str) -> str:
    no_comment = line.split("#", 1)[0]
    return " ".join(no_comment.strip().split())


def is_duplicate_noise_line(normalized: str) -> bool:
    lowered = normalized.lower()
    if lowered.startswith("import ") or lowered.startswith("from "):
        return True
    if lowered in {"try:", "except:", "except exception as e:", "else:", "finally:", "pass", "return", "return none"}:
        return True
    if len(lowered) < 12:
        return True
    return False


def collect_duplicate_code_findings(src_dir: Path) -> SectionResult:
    window_size = 8
    min_chars = 220

    block_map: dict[str, list[tuple[Path, int, str]]] = {}

    for file_path in gather_python_files(src_dir):
        raw_lines = get_file_context(file_path).lines
        normalized_lines: list[tuple[int, str, str]] = []

        for idx, raw in enumerate(raw_lines, start=1):
            normalized = normalize_code_line(raw)
            if not normalized:
                continue
            normalized_lines.append((idx, normalized, raw.strip()))

        if len(normalized_lines) < window_size:
            continue

        for pos in range(0, len(normalized_lines) - window_size + 1):
            chunk = normalized_lines[pos : pos + window_size]
            chunk_str = "\n".join(item[1] for item in chunk)
            if len(chunk_str) < min_chars:
                continue

            chunk_hash = hashlib.md5(chunk_str.encode("utf-8")).hexdigest()

            substantive_count = sum(1 for _, normalized, _ in chunk if not is_duplicate_noise_line(normalized))
            if substantive_count < 4:
                continue

            sample_line = next((raw for _, normalized, raw in chunk if not is_duplicate_noise_line(normalized)), chunk[0][2])
            block_map.setdefault(chunk_hash, []).append((file_path, chunk[0][0], sample_line))

    findings: list[Finding] = []
    groups = 0

    for _, occurrences in block_map.items():
        unique_locs = {(p, ln) for p, ln, _ in occurrences}
        if len(unique_locs) < 2:
            continue

        groups += 1
        representative = sorted(occurrences, key=lambda item: (str(item[0]), item[1]))
        first_file, first_line, sample = representative[0]
        top_locations = [
            f"{str(path.relative_to(REPO_ROOT))}:{line_no}" for path, line_no, _ in representative[:4]
        ]
        location_hint = ", ".join(top_locations)
        if len(representative) > 4:
            location_hint += f", ... (+{len(representative) - 4})"

        findings.append(
            Finding(
                file=str(first_file.relative_to(REPO_ROOT)),
                line=first_line,
                category="duplicate_code",
                message=f"Detected duplicated block group with {len(unique_locs)} occurrences. Locations: {location_hint}",
                sample=sample,
            )
        )

    return SectionResult(
        name="duplicate_code",
        findings=findings,
        meta={
            "window_size": window_size,
            "min_chars": min_chars,
            "duplicate_groups": groups,
        },
    )


def collect_ui_hardcode_findings(src_dir: Path) -> SectionResult:
    color_pattern = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    size_pattern = re.compile(r"\b(width|height|padx|pady|wraplength|corner_radius|border_width)\s*=\s*(?!0\b|1\b)\d+\b")
    font_size_pattern = re.compile(r"\bfont\s*=\s*\([^)]*,\s*\d+[^)]*\)")

    findings: list[Finding] = []
    
    ignored_files = {src_dir / "utils" / "ui_utils.py", src_dir / "utils" / "ui_tokens.py", src_dir / "ui" / "ui_config.py", src_dir / "ui" / "font_manager.py", src_dir / "ui" / "icon_utils.py"}

    for file_path in gather_python_files(src_dir):
        if file_path in ignored_files:
            continue
        if "tests" in file_path.parts:
            continue

        lines = get_file_context(file_path).lines
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # 允許透過加上 # noqa: hardcode 來明確宣告這行「只能使用硬編碼」
            if "noqa: hardcode" in stripped.lower():
                continue

            if any(token in line for token in ["Colors.", "Sizes.", "Spacing.", "FontSize."]):
                continue

            if color_pattern.search(line):
                findings.append(
                    Finding(
                        file=str(file_path.relative_to(REPO_ROOT)),
                        line=idx,
                        category="hardcoded_color",
                        message="Hardcoded color literal found. Consider using ui_utils.Colors token.",
                        sample=stripped,
                    )
                )

            if size_pattern.search(line) or font_size_pattern.search(line):
                findings.append(
                    Finding(
                        file=str(file_path.relative_to(REPO_ROOT)),
                        line=idx,
                        category="hardcoded_size",
                        message="Hardcoded size literal found. Consider using ui_utils Sizes/Spacing/FontSize token.",
                        sample=stripped,
                    )
                )

    return SectionResult(name="ui_hardcode", findings=findings, meta={"scope": "src/**/*.py (except src/utils/ui_utils.py)"})


def _collect_imported_call_aliases(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    imported_bases: set[str] = set()
    imported_symbols: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                if local_name:
                    imported_bases.add(local_name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                if not local_name:
                    continue
                imported_bases.add(local_name)
                module_name = "." * node.level + (node.module or "")
                imported_symbols[local_name] = f"{module_name}.{alias.name}".strip(".")

    return imported_bases, imported_symbols


def _get_attribute_root_name(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def collect_cross_file_private_callable_findings(repo_root: Path) -> SectionResult:
    findings: list[Finding] = []
    scanned_files = 0

    for file_path in gather_python_files(repo_root):
        if "tests" in file_path.parts:
            continue
        scanned_files += 1
        
        ctx = get_file_context(file_path)
        if ctx.parse_error:
            findings.append(
                Finding(
                    file=str(file_path.relative_to(REPO_ROOT)),
                    line=1,
                    category="cross_file_private_callable",
                    message=ctx.parse_error,
                    sample="",
                )
            )
            continue
        
        if not ctx.ast_tree:
            continue

        imported_bases, imported_symbols = _collect_imported_call_aliases(ctx.ast_tree)
        lines = ctx.lines

        for node in ast.walk(ctx.ast_tree):
            if not isinstance(node, ast.Call):
                continue

            callable_name: str | None = None
            if isinstance(node.func, ast.Name):
                if not node.func.id.startswith("_"):
                    continue
                if node.func.id not in imported_symbols:
                    continue
                callable_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                if not node.func.attr.startswith("_"):
                    continue
                root_name = _get_attribute_root_name(node.func.value)
                if not root_name or root_name not in imported_bases:
                    continue
                callable_name = f"{root_name}.{node.func.attr}"
            else:
                continue

            line_no = int(getattr(node, "lineno", 1) or 1)
            sample = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
            findings.append(
                Finding(
                    file=str(file_path.relative_to(REPO_ROOT)),
                    line=line_no,
                    category="cross_file_private_callable",
                    message=f"跨檔案呼叫的 callable `{callable_name}` 不應以底線開頭。",
                    sample=sample,
                )
            )

    return SectionResult(
        name="cross_file_private_callable",
        findings=findings,
        meta={"scope": "runtime code and entry points; tests excluded", "scanned_files": scanned_files},
    )


TRIVIAL_CALLABLE_PREFIXES = (
    "get_",
    "set_",
    "is_",
    "has_",
    "can_",
    "should_",
    "clear_",
    "select_",
    "move_",
)

COMMON_EXEMPT_CALLABLE_NAMES = {
    "clear",
    "close",
    "cancel",
    "lazy_exports",
    "get_logger",
    "get_default_headers",
    "get_hidden_windows_kwargs",
    "get_timeout_retry_policy",
    "get_json_async",
    "post_json_async",
    "download_file_async",
    "main",
    "run_async",
    "run_async_in_background",
    "run_in_background",
    "shutdown_logging",
    "show_message",
    "total_count",
}

CTYPES_CLASS_BASE_NAMES = {"ctypes.Structure", "ctypes.Union", "Structure", "Union"}


def _is_dunder_name(name: str) -> bool:
    return name.startswith("__")


def _is_public_name(name: str) -> bool:
    if _is_dunder_name(name):
        return False
    return not name.startswith("_")


def _get_dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base_name = _get_dotted_name(node.value)
        return f"{base_name}.{node.attr}" if base_name else node.attr
    return ""


def _is_property_like_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        decorator_name = ""
        if isinstance(decorator, ast.Name):
            decorator_name = decorator.id
        elif isinstance(decorator, ast.Attribute):
            decorator_name = decorator.attr
        if decorator_name in {"property", "cached_property", "setter", "deleter", "getter"}:
            return True
    return False


def _is_ctypes_structure_class(node: ast.ClassDef) -> bool:
    base_names = { _get_dotted_name(base) for base in node.bases }
    return bool(base_names.intersection(CTYPES_CLASS_BASE_NAMES))


def _strip_docstring_statement(statements: list[ast.stmt]) -> list[ast.stmt]:
    if not statements:
        return statements
    first_statement = statements[0]
    if not isinstance(first_statement, ast.Expr):
        return statements
    value = getattr(first_statement, "value", None)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return statements[1:]
    return statements


def _statement_is_simple(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Pass, ast.Return)):
        return True
    if isinstance(stmt, ast.If):
        nested_statements = _strip_docstring_statement(list(stmt.body)) + _strip_docstring_statement(list(stmt.orelse))
        return bool(nested_statements) and all(_statement_is_simple(nested) for nested in nested_statements)
    return False


def _is_trivial_callable(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    statements = _strip_docstring_statement(list(node.body))
    if not statements:
        return True
    if len(statements) > 5:
        return False
    return all(_statement_is_simple(stmt) for stmt in statements)


def _get_callable_arguments(node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_method: bool) -> list[str]:
    arguments: list[str] = []
    arguments.extend(argument.arg for argument in node.args.posonlyargs)
    arguments.extend(argument.arg for argument in node.args.args)
    if node.args.vararg is not None:
        arguments.append(node.args.vararg.arg)
    arguments.extend(argument.arg for argument in node.args.kwonlyargs)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg.arg)

    if is_method and arguments:
        decorator_names = { _get_dotted_name(decorator) for decorator in node.decorator_list }
        if "staticmethod" not in decorator_names and arguments[0] in {"self", "cls"}:
            arguments = arguments[1:]
    return arguments


def _callable_requires_args(node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_method: bool) -> bool:
    return bool(_get_callable_arguments(node, is_method=is_method))


class _ReturnVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.has_return_value = False

    def visit_FunctionDef(self, _node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, _node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, _node: ast.ClassDef) -> None:
        return

    def visit_Return(self, return_node: ast.Return) -> None:
        if return_node.value is not None:
            self.has_return_value = True


def _callable_requires_returns(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if node.returns is not None:
        try:
            normalized = re.sub(r"\s+", "", ast.unparse(node.returns))
        except Exception:
            normalized = ""
        if normalized in {"None", "NoneType", "NoReturn", "Never"} or normalized.endswith(".NoReturn"):
            return False

    visitor = _ReturnVisitor()
    for statement in _strip_docstring_statement(list(node.body)):
        visitor.visit(statement)
        if visitor.has_return_value:
            return True
    return False


def _docstring_has_section(docstring: str | None, section_names: set[str]) -> bool:
    if not docstring:
        return False
    for raw_line in docstring.splitlines():
        normalized_line = re.sub(r"\s+", " ", raw_line.strip()).lower().rstrip(":")
        if normalized_line in section_names:
            return True
    return False


def _should_exempt_callable(node: ast.FunctionDef | ast.AsyncFunctionDef, *, _is_method: bool) -> bool:
    if _is_dunder_name(node.name):
        return True
    if _is_property_like_method(node):
        return True
    if node.name in COMMON_EXEMPT_CALLABLE_NAMES:
        return True
    return bool(any(node.name.startswith(prefix) for prefix in TRIVIAL_CALLABLE_PREFIXES) and _is_trivial_callable(node))


def _collect_callable_findings(
    node: ast.FunctionDef | ast.AsyncFunctionDef, file_path: Path, qualified_name: str, *, is_method: bool, owner_lines: list[str]
) -> list[Finding]:
    if _should_exempt_callable(node, _is_method=is_method):
        return []

    docstring = ast.get_docstring(node)
    findings: list[Finding] = []
    lineno = getattr(node, "lineno", 1) or 1
    sample = owner_lines[lineno - 1].strip() if 0 < lineno <= len(owner_lines) else ""

    if not docstring:
        findings.append(
            Finding(
                file=str(file_path.relative_to(REPO_ROOT)),
                line=lineno,
                category="docstring",
                message=f"公開 callable '{qualified_name}' 缺少 docstring。",
                sample=sample,
            )
        )
        return findings

    if _callable_requires_args(node, is_method=is_method) and not _docstring_has_section(docstring, {"args", "arguments", "parameters"}):
        findings.append(
            Finding(
                file=str(file_path.relative_to(REPO_ROOT)),
                line=lineno,
                category="docstring_args",
                message=f"公開 callable '{qualified_name}' 的 docstring 缺少 Args 區段。",
                sample=sample,
            )
        )

    if _callable_requires_returns(node) and not _docstring_has_section(docstring, {"return", "returns", "yield", "yields"}):
        findings.append(
            Finding(
                file=str(file_path.relative_to(REPO_ROOT)),
                line=lineno,
                category="docstring_returns",
                message=f"公開 callable '{qualified_name}' 的 docstring 缺少 Returns 區段。",
                sample=sample,
            )
        )
    return findings


def _collect_class_findings(node: ast.ClassDef, file_path: Path, owner_names: list[str], owner_lines: list[str]) -> list[Finding]:
    if _is_ctypes_structure_class(node):
        return []

    findings: list[Finding] = []
    class_names = [*owner_names, node.name]
    qualified_name = ".".join(class_names)
    class_docstring = ast.get_docstring(node)
    lineno = getattr(node, "lineno", 1) or 1
    sample = owner_lines[lineno - 1].strip() if 0 < lineno <= len(owner_lines) else ""
    if not class_docstring and _is_public_name(node.name):
        findings.append(
            Finding(
                file=str(file_path.relative_to(REPO_ROOT)),
                line=lineno,
                category="docstring_class",
                message=f"公開 class '{qualified_name}' 缺少 docstring。",
                sample=sample,
            )
        )

    for child in node.body:
        if isinstance(child, ast.ClassDef):
            if _is_public_name(child.name):
                findings.extend(_collect_class_findings(child, file_path, class_names, owner_lines))
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public_name(getattr(child, "name", "")):
            method_name = ".".join([*class_names, child.name])
            findings.extend(_collect_callable_findings(child, file_path, method_name, is_method=True, owner_lines=owner_lines))
    return findings


def collect_docstring_section(src_dir: Path) -> SectionResult:
    findings: list[Finding] = []
    for file_path in gather_python_files(src_dir):
        if "tests" in file_path.parts:
            continue

        ctx = get_file_context(file_path)
        if ctx.parse_error:
            findings.append(
                Finding(
                    file=str(file_path.relative_to(REPO_ROOT)),
                    line=1,
                    category="docstring_syntax",
                    message=ctx.parse_error,
                    sample="",
                )
            )
            continue
        
        if not ctx.ast_tree:
            continue

        owner_lines = ctx.lines
        if not ast.get_docstring(ctx.ast_tree):
            findings.append(
                Finding(
                    file=str(file_path.relative_to(REPO_ROOT)),
                    line=1,
                    category="docstring_module",
                    message=f"公開 module '{str(file_path.relative_to(REPO_ROOT))}' 缺少 docstring。",
                    sample="",
                )
            )

        for node in ctx.ast_tree.body:
            if isinstance(node, ast.ClassDef):
                if _is_public_name(node.name):
                    findings.extend(_collect_class_findings(node, file_path, [], owner_lines))
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public_name(getattr(node, "name", "")):
                findings.extend(_collect_callable_findings(node, file_path, node.name, is_method=False, owner_lines=owner_lines))

    return SectionResult(name="docstrings", findings=findings, meta={"scope": "src/**/*.py (public API)"})

# -------------------------------------------------------------------------


def collect_comment_tool_results() -> list[ToolResult]:
    specs = [
        ToolSpec(
            name="ruff-era",
            tool_name="ruff",
            module_name="ruff",
            args=["check", "--select", "ERA", "src", "tests", "quick_test.py"]
        ),
        ToolSpec(
            name="eradicate",
            tool_name="eradicate",
            module_name="eradicate",
            args=["--recursive", "--aggressive", "src", "tests", "quick_test.py"]
        ),
    ]
    
    def execute_spec(spec: ToolSpec) -> ToolResult:
        return run_project_tool(spec.name, spec.tool_name, spec.args, module_name=spec.module_name)

    with ThreadPoolExecutor() as executor:
        return list(executor.map(execute_spec, specs))


def merge_detect_secrets_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    merged_results: dict[str, list[Any]] = {}
    plugin_names: set[str] = set()
    plugins_used: list[dict[str, Any]] = []
    filters_used: list[str] = []
    seen_filters: set[str] = set()
    version = ""

    for payload in payloads:
        if not version:
            version = str(payload.get("version", "") or "")

        for plugin in payload.get("plugins_used", []) if isinstance(payload.get("plugins_used"), list) else []:
            if not isinstance(plugin, dict):
                continue
            plugin_name = str(plugin.get("name", "") or "")
            if not plugin_name or plugin_name in plugin_names:
                continue
            plugin_names.add(plugin_name)
            plugins_used.append(plugin)

        for filter_name in payload.get("filters_used", []) if isinstance(payload.get("filters_used"), list) else []:
            normalized_filter = str(filter_name or "")
            if not normalized_filter or normalized_filter in seen_filters:
                continue
            seen_filters.add(normalized_filter)
            filters_used.append(normalized_filter)

        results = payload.get("results")
        if not isinstance(results, dict):
            continue
        for file_name, findings in results.items():
            if not isinstance(findings, list):
                continue
            merged_results.setdefault(str(file_name), []).extend(findings)

    return {
        "version": version,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "plugins_used": plugins_used,
        "filters_used": filters_used,
        "results": merged_results,
    }


def collect_privacy_tool_results() -> list[ToolResult]:
    scannable_files = gather_repo_files(REPO_ROOT)
    if not scannable_files:
        return [
            ToolResult(
                name="detect-secrets",
                status="unavailable",
                command="detect-secrets scan (no files)",
                return_code=None,
                duration_seconds=0.0,
                output="No scannable repository files found.",
            )
        ]

    payloads: list[dict[str, Any]] = []
    total_duration = 0.0
    overall_status = "passed"
    failure_code = 0
    command_summary = f"detect-secrets scan --only-verified <repo-files> (batched x{(len(scannable_files) + DETECT_SECRETS_BATCH_SIZE - 1) // DETECT_SECRETS_BATCH_SIZE})"
    failure_outputs: list[str] = []

    def execute_batch(batch_index: int) -> ToolResult:
        batch = scannable_files[batch_index : batch_index + DETECT_SECRETS_BATCH_SIZE]
        relative_batch = [str(path.relative_to(REPO_ROOT)) for path in batch]
        return run_project_tool(
            name=f"detect-secrets[{(batch_index // DETECT_SECRETS_BATCH_SIZE) + 1}]",
            tool_name="detect-secrets",
            args=["scan", "--only-verified", *relative_batch],
        )

    with ThreadPoolExecutor() as executor:
        batch_indices = range(0, len(scannable_files), DETECT_SECRETS_BATCH_SIZE)
        results = list(executor.map(execute_batch, batch_indices))

    for result in results:
        total_duration += result.duration_seconds
        if result.status != "passed":
            overall_status = "failed"
            failure_code = result.return_code or 1
            failure_outputs.append(result.output)
            continue

        parsed = parse_json_output(result.output)
        if isinstance(parsed, dict):
            payloads.append(parsed)

    merged_output = json.dumps(merge_detect_secrets_payloads(payloads), ensure_ascii=False, indent=2)
    if failure_outputs:
        merged_output = (merged_output + "\n\n" + "\n\n".join(output for output in failure_outputs if output)).strip()

    return [
        ToolResult(
            name="detect-secrets",
            status=overall_status,
            command=command_summary,
            return_code=0 if overall_status == "passed" else failure_code,
            duration_seconds=total_duration,
            output=merged_output,
        )
    ]


def is_text_like(path: Path) -> bool:
    text_exts = {
        ".py",
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".ps1",
        ".bat",
        ".sh",
        ".html",
        ".css",
        ".js",
    }
    return path.suffix.lower() in text_exts


def collect_privacy_regex_findings(repo_root: Path) -> SectionResult:
    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
        (
            "generic_secret_assignment",
            re.compile(
                r"(?i)\b(api[_-]?key|token|secret|password|passwd)\b\s*[:=]\s*[\"'][^\"']{8,}[\"']"
            ),
        ),
        (
            "private_key_block",
            re.compile(r"-----BEGIN (RSA|EC|OPENSSH|DSA)? ?PRIVATE KEY-----"),
        ),
    ]

    findings: list[Finding] = []

    for path in gather_repo_files(repo_root):
        if not is_text_like(path):
            continue

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for idx, line in enumerate(lines, start=1):
            for category, pattern in patterns:
                if not pattern.search(line):
                    continue
                findings.append(
                    Finding(
                        file=str(path.relative_to(repo_root)),
                        line=idx,
                        category=category,
                        message=f"Potential sensitive information detected by pattern: {category}",
                        sample=line.strip(),
                    )
                )

    return SectionResult(name="privacy_regex", findings=findings, meta={"pattern_count": len(patterns)})


def summarize_tool_findings(results: list[ToolResult], section_name: str) -> SectionResult:
    findings: list[Finding] = []
    for result in results:
        issue_count = count_tool_reported_issues(result)

        # detect-secrets 輸出為 JSON；若 results 有候選，應視為待處理問題。
        if result.name == "detect-secrets":
            parsed = parse_json_output(result.output)
            secret_count = count_detect_secrets_candidates(parsed)
            if secret_count > 0:
                findings.append(
                    Finding(
                        file="(tool)",
                        line=0,
                        category=section_name,
                        message=f"detect-secrets 偵測到 {secret_count} 個候選項",
                        sample=summarize_output_for_finding(result),
                    )
                )
                continue

        if issue_count > 0:
            findings.append(
                Finding(
                    file="(tool)",
                    line=0,
                    category=section_name,
                    message=f"{result.name} 偵測到 {issue_count} 個問題（終止代碼 {result.return_code}）",
                    sample=summarize_output_for_finding(result),
                )
            )
            continue

        if result.status in {"passed", "unavailable"}:
            continue

        message = (
            f"{result.name} status={result.status}"
            if result.return_code is None
            else f"{result.name} 終止代碼 {result.return_code}"
        )
        findings.append(
            Finding(
                file="(tool)",
                line=0,
                category=section_name,
                message=message,
                sample=summarize_output_for_finding(result),
            )
        )
    return SectionResult(name=section_name, findings=findings, meta={"tool_count": len(results)})


def truncate_findings(findings: list[Finding], max_items: int) -> tuple[list[Finding], int]:
    if max_items <= 0:
        return [], len(findings)
    if len(findings) <= max_items:
        return findings, 0
    return findings[:max_items], len(findings) - max_items


def summarize_output_for_finding(result: ToolResult) -> str:
    highlights = extract_tool_highlights(result)
    if highlights:
        return " | ".join(highlights)
    if result.output:
        return result.output
    
    return "(no output)"


def count_detect_secrets_candidates(parsed: Any | None) -> int:
    if not isinstance(parsed, dict):
        return 0
    results_obj = parsed.get("results")
    if not isinstance(results_obj, dict):
        return 0
    total = 0
    for value in results_obj.values():
        if isinstance(value, list):
            total += len(value)
    return total

_ISSUE_COUNTERS: dict[str, Callable[[str], int]] = {
    "ruff":      lambda o: len(re.findall(r"(?m)^.+?:\d+:\d+:\s", o)),
    "mypy":      lambda o: int(m.group(1)) if (m := re.search(r"Found\s+(\d+)\s+errors?", o)) else 0,
    "pylint":    lambda o: len(re.findall(r"(?m)^.+?:\d+:\d+:\s+[A-Z]\d{4}:", o)),
    "bandit":    lambda o: len(re.findall(r"(?m)^>>\sIssue:", o)),
    "vulture":   lambda o: len([l for l in o.splitlines() if l.strip() and "unused" in l.lower()]),
    "ruff-era":  lambda o: len(re.findall(r"(?m)^.+\.py:\d+:\d+:\s+ERA", o)),
    "eradicate": lambda o: len(re.findall(r"(?m)^.+\.py:\d+", o)),
}

def count_tool_reported_issues(result: ToolResult) -> int:
    counter = _ISSUE_COUNTERS.get(result.name)
    return counter(result.output) if counter and result.output else 0

_HIGHLIGHT_MESSAGES = {
    "pylint": "pylint 偵測問題：",
    "vulture": "未使用代碼項目：",
    "eradicate": "可疑註解數量：",
    "ruff": "ruff 偵測問題：",
    "mypy": "mypy 偵測問題：",
    "bandit": "bandit 偵測問題：",
    "ruff-era": "ruff ERA 偵測可疑註解：",
}

def extract_tool_highlights(result: ToolResult) -> list[str]:
    highlights: list[str] = []
    output = result.output.strip()
    parsed = parse_json_output(output)

    if isinstance(parsed, dict):
        if "results" in parsed and isinstance(parsed["results"], dict):
            total = sum(len(value) for value in parsed["results"].values() if isinstance(value, list))
            highlights.append(f"偵測到 secrets 候選數：{total}")
        if "version" in parsed:
            highlights.append(f"工具版本：{parsed['version']}")
        if "plugins_used" in parsed and isinstance(parsed["plugins_used"], list):
            highlights.append(f"啟用偵測器數量：{len(parsed['plugins_used'])}")

    if "All checks passed!" in output:
        highlights.append("檢查通過（All checks passed）")
    if "Success: no issues found" in output:
        highlights.append("型別檢查通過（mypy 無問題）")
    if "No issues identified." in output:
        highlights.append("未發現安全性問題")
    if "No known security vulnerabilities" in output:
        highlights.append("依賴套件安全（無已知漏洞）")
    if "found 0 potentially unused" in output.lower():
        highlights.append("未發現死代碼")

    counter = _ISSUE_COUNTERS.get(result.name)
    if counter and (count := counter(output)) > 0:
        highlights.append(f"{_HIGHLIGHT_MESSAGES.get(result.name, result.name + ' 偵測問題：')}{count}")
    elif result.name == "pylint" and "rated at" in output.lower():
        highlights.append("pylint 檢查通過（無循環引用問題）")

    if result.return_code is not None:
        highlights.append(f"exit code: {result.return_code}")

    # 去除重複並保序。
    deduped: list[str] = []
    seen: set[str] = set()
    for item in highlights:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def build_quality_action_items(
    code_quality_tools: list[ToolResult], duplicate_result: SectionResult, cross_file_callable_result: SectionResult
) -> list[str]:
    actions: list[str] = []
    
    ruff_result = next((item for item in code_quality_tools if item.name == "ruff"), None)
    if ruff_result is not None and _ISSUE_COUNTERS["ruff"](ruff_result.output) > 0:
        actions.append("優先處理 ruff 回報：涵蓋語法、可讀性與常見錯誤模式。")

    mypy_result = next((item for item in code_quality_tools if item.name == "mypy"), None)
    if mypy_result is not None and _ISSUE_COUNTERS["mypy"](mypy_result.output) > 0:
        actions.append("優先處理 mypy 型別錯誤：可有效降低執行期錯誤風險。")

    pylint_result = next((item for item in code_quality_tools if item.name == "pylint"), None)
    if pylint_result is not None and _ISSUE_COUNTERS["pylint"](pylint_result.output) > 0:
        actions.append("優先處理 pylint 循環引用警告：先降低模組耦合與匯入風險。")

    bandit_result = next((item for item in code_quality_tools if item.name == "bandit"), None)
    if bandit_result is not None and _ISSUE_COUNTERS["bandit"](bandit_result.output) > 0:
        actions.append("優先處理 bandit 安全警示：先修正高風險項目。")

    vulture_result = next((item for item in code_quality_tools if item.name == "vulture"), None)
    if vulture_result is not None and _ISSUE_COUNTERS["vulture"](vulture_result.output) > 0:
        actions.append("處理 vulture 未使用代碼：可降低維護成本與誤判噪音。")

    if duplicate_result.findings:
        actions.append(f"重複碼群組 {len(duplicate_result.findings)} 組：抽出共用 helper 函式可快速下降。")

    if cross_file_callable_result.findings:
        actions.append(
            f"跨檔 private callable {len(cross_file_callable_result.findings)} 筆：先改成公開命名，再回頭整理模組邊界。"
        )

    if not actions:
        actions.append("目前未偵測到需要優先處理的品質問題。")
    return actions


def parse_json_output(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def render_tool_output(output: str) -> str:
    parsed = parse_json_output(output)
    if parsed is None:
        content = html.escape(output) if output else "(no output)"
        return f"<details><summary>完整輸出</summary><pre>{content}</pre></details>"

    pretty = json.dumps(parsed, ensure_ascii=False, indent=2)

    if isinstance(parsed, dict):
        keys = list(parsed.keys())[:8]
        key_tags = "".join(f"<span class=\"tag\">{html.escape(str(key))}</span>" for key in keys)
        meta = f"<div class=\"json-meta\"><span>JSON object</span><span>keys: {len(parsed)}</span>{key_tags}</div>"
    elif isinstance(parsed, list):
        meta = f"<div class=\"json-meta\"><span>JSON array</span><span>items: {len(parsed)}</span></div>"
    else:
        meta = "<div class=\"json-meta\"><span>JSON scalar</span></div>"

    return (
        "<details><summary>完整 JSON 輸出（已格式化）</summary>"
        + meta
        + f"<pre class=\"json-pre\">{html.escape(pretty)}</pre>"
        + "</details>"
    )


def render_tool_detail(result: ToolResult) -> str:
    command_html = html.escape(result.command or "(unavailable)")
    output_html = render_tool_output(result.output)
    return (
        "<details><summary>命令與輸出</summary>"
        + f"<div class=\"tool-detail-meta\"><div><strong>命令</strong></div><code>{command_html}</code></div>"
        + output_html
        + "</details>"
    )


def render_tool_table(results: list[ToolResult]) -> str:
    rows: list[str] = []
    for result in results:
        highlights = extract_tool_highlights(result)
        highlight_html = ""
        if highlights:
            highlight_items = "".join(f"<li>{html.escape(item)}</li>" for item in highlights)
            highlight_html = f"<div class=\"highlight-box\"><div class=\"highlight-title\">重點摘要</div><ul>{highlight_items}</ul></div>"
        else:
            highlight_html = '<div class="tool-summary-empty">此工具本輪沒有額外摘要。</div>'
        rows.append(
            """
            <tr>
              <td>{name}</td>
              <td><span class=\"badge {status_class}\">{status}</span></td>
              <td>{duration:.2f}s</td>
              <td>{highlight}</td>
              <td>{detail}</td>
            </tr>
            """.format(
                name=html.escape(result.name),
                status_class=f"status-{result.status}",
                status=html.escape(result.status),
                duration=result.duration_seconds,
                highlight=highlight_html,
                detail=render_tool_detail(result),
            )
        )
    return "\n".join(rows)


def render_finding_detail(sample_text: str) -> str:
    """呈現 finding 的詳細內容，支援 JSON 自動轉換和多行展示"""
    if not sample_text or sample_text == "(no output)":
        return "<span style=\"color: #94a3b8;\">無詳細內容</span>"
    
    parsed = parse_json_output(sample_text)
    
    if parsed is None:
        lines = [line.strip() for line in sample_text.split("|") if line.strip()]
        if len(lines) <= 2:
            return "<span><code>" + html.escape(sample_text) + "</code></span>"
        else:
            preview = "<br/>".join(html.escape(line) for line in lines[:2])
            full = "<br/>".join(html.escape(line) for line in lines)
            return (
                f"<details style=\"cursor: pointer;\">"
                f"<summary><code>{preview}</code></summary>"
                f"<pre style=\"margin: 8px 0 0; padding: 8px; background: #f8fbff; border: 1px solid #dbeafe; border-radius: 6px; font-size: 0.85rem; max-height: 320px; overflow: auto;\">"
                f"{html.escape(full)}</pre>"
                f"</details>"
            )
    else:
        pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
        if isinstance(parsed, dict):
            keys = list(parsed.keys())[:6]
            key_tags = "".join(f"<span class=\"tag\">{html.escape(str(k))}</span>" for k in keys)
            meta = f"<div style=\"font-size: 0.8rem; color: #64748b; margin-bottom: 6px;\"><span>JSON object</span> • <span>keys: {len(parsed)}</span> {key_tags}</div>"
        elif isinstance(parsed, list):
            meta = f"<div style=\"font-size: 0.8rem; color: #64748b; margin-bottom: 6px;\"><span>JSON array</span> • <span>items: {len(parsed)}</span></div>"
        else:
            meta = "<div style=\"font-size: 0.8rem; color: #64748b; margin-bottom: 6px;\"><span>JSON scalar</span></div>"
        
        return (
            f"<details style=\"cursor: pointer;\">"
            f"<summary style=\"font-weight: 600; color: #0284c7;\">檢視 JSON 詳情</summary>"
            f"{meta}"
            f"<pre class=\"json-pre\" style=\"margin: 0; padding: 8px; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; font-size: 0.8rem; max-height: 340px; overflow: auto; white-space: pre-wrap;\">"
            f"{html.escape(pretty)}</pre>"
            f"</details>"
        )


def render_findings_table(findings: list[Finding], omitted_count: int) -> str:
    if not findings:
        return "<p class=\"empty\">沒有發現問題。</p>"

    rows: list[str] = []
    for finding in findings:
        detail_html = render_finding_detail(finding.sample)
        rows.append(
            """
            <tr>
              <td>{file}</td>
              <td>{line}</td>
              <td>{category}</td>
              <td>{message}</td>
              <td>{detail}</td>
            </tr>
            """.format(
                file=html.escape(finding.file),
                line=finding.line if finding.line > 0 else "-",
                category=html.escape(finding.category),
                message=html.escape(finding.message),
                detail=detail_html,
            )
        )

    notice = ""
    if omitted_count > 0:
        notice = f"<p class=\"omitted\">另有 {omitted_count} 筆未顯示（避免報告過長）。</p>"

    return (
        notice
        + """
        <table>
          <thead>
            <tr><th>檔案</th><th>行號</th><th>類別</th><th>訊息</th><th>詳細內容</th></tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
        """.format(rows="\n".join(rows))
    )


def overall_status_from_counts(summary_cards: list[tuple[str, int]]) -> str:
    if any(count > 0 for _, count in summary_cards):
        return "warning"
    return "passed"


def build_html_report(
    generated_at: str,
    code_quality_tools: list[ToolResult],
    code_quality_findings: SectionResult,
    cross_file_callable_result: SectionResult,
    duplicate_result: SectionResult,
    hardcode_result: SectionResult,
    comment_result: SectionResult,
    docstring_result: SectionResult,
    comment_tool_results: list[ToolResult],
    privacy_tool_results: list[ToolResult],
    privacy_regex_result: SectionResult,
    max_details: int,
    total_runtime_seconds: float,
) -> str:
    combined_code_quality_findings = code_quality_findings.findings + cross_file_callable_result.findings
    code_quality_visible, code_quality_omitted = truncate_findings(combined_code_quality_findings, max_details)
    duplicate_visible, duplicate_omitted = truncate_findings(duplicate_result.findings, max_details)
    hardcode_visible, hardcode_omitted = truncate_findings(hardcode_result.findings, max_details)
    comment_visible, comment_omitted = truncate_findings(comment_result.findings, max_details)
    docstrings_visible, docstrings_omitted = truncate_findings(docstring_result.findings, max_details)

    merged_privacy_findings = summarize_tool_findings(privacy_tool_results, "privacy_tools").findings + privacy_regex_result.findings
    privacy_visible, privacy_omitted = truncate_findings(merged_privacy_findings, max_details)

    summary_cards = [
        ("程式碼品質", len(code_quality_findings.findings)),
        ("API 命名", len(cross_file_callable_result.findings)),
        ("重複程式碼", len(duplicate_result.findings)),
        ("UI 硬編碼", len(hardcode_result.findings)),
        ("註解整潔", len(comment_result.findings)),
        ("Docstring 稽核", len(docstring_result.findings)),
        ("隱私資訊", len(merged_privacy_findings)),
    ]
    overall = overall_status_from_counts(summary_cards)

    cards_html = "\n".join(
        "<div class=\"card {}\"><h3>{}</h3><p class=\"count\">{}</p><p class=\"card-note\">{}</p></div>".format(
            "is-ok" if count == 0 else "is-warning",
            html.escape(title),
            count,
            "狀態正常" if count == 0 else "需要優先處理",
        )
        for title, count in summary_cards
    )
    action_items = build_quality_action_items(code_quality_tools, duplicate_result, cross_file_callable_result)
    action_html = "".join(f"<li>{html.escape(item)}</li>" for item in action_items)
    category_overview_html = render_category_overview()
    summary_meta_html = "".join(
        (
            '<div class="meta-card">'
            f'<div class="meta-label">{html.escape(label)}</div>'
            f'<div class="meta-value">{html.escape(value)}</div>'
            "</div>"
        )
        for label, value in [
            ("執行模式", "專案開發環境直跑（非 isolated）"),
            ("detect-secrets 範圍", "專案檔案，排除 .venv / build / dist / cache"),
            ("總耗時", format_duration(total_runtime_seconds)),
            ("明細上限", str(max_details)),
        ]
    )

    duplicate_rule = f"偵測規則：連續 {duplicate_result.meta.get('window_size', 8)} 行、正規化後最少 {duplicate_result.meta.get('min_chars', 220)} 字元。"

    return f"""<!DOCTYPE html>
<html lang=\"zh-Hant\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>綜合檢查報告</title>
    <style>
        :root {{
            --bg: #f5fbff;
            --panel: #ffffff;
            --ink: #0f172a;
            --muted: #475569;
            --line: #dbeafe;
            --accent: #0284c7;
            --ok: #16a34a;
            --warn: #d97706;
            --fail: #dc2626;
            --shadow: 0 10px 28px rgba(2, 132, 199, 0.14);
        }}

        * {{ box-sizing: border-box; }}

        body {{
            margin: 0;
            font-family: "Noto Sans TC", "Microsoft JhengHei", sans-serif;
            color: var(--ink);
            background:
                radial-gradient(circle at 15% -10%, #bae6fd 0, transparent 40%),
                radial-gradient(circle at 90% 0%, #bbf7d0 0, transparent 36%),
                var(--bg);
            min-height: 100vh;
        }}

        .wrap {{
            max-width: 1160px;
            margin: 0 auto;
            padding: 20px;
        }}

        .hero {{
            background: linear-gradient(120deg, #075985 0%, #0369a1 55%, #0f766e 100%);
            border-radius: 18px;
            color: #f0f9ff;
            padding: 22px;
            box-shadow: var(--shadow);
        }}

        .hero h1 {{ margin: 0; font-size: clamp(1.45rem, 2vw, 1.95rem); }}
        .hero p {{ margin: 6px 0 0; color: #dbeafe; }}

        .overall {{
            display: inline-block;
            margin-top: 12px;
            padding: 6px 12px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.16);
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .tabs {{ margin-top: 14px; display: flex; flex-wrap: wrap; gap: 8px; }}

        .tab-btn {{
            border: 1px solid rgba(255, 255, 255, 0.4);
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.14);
            color: #f8fafc;
            padding: 8px 13px;
            cursor: pointer;
            font-weight: 700;
        }}

        .tab-btn.active {{ background: #ffffff; color: #0c4a6e; }}

        .tab-panel {{
            display: none;
            margin-top: 14px;
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 16px;
            box-shadow: 0 6px 18px rgba(2, 132, 199, 0.08);
        }}

        .tab-panel.active {{ display: block; }}

        .summary-layout {{ display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(280px, 1fr); gap: 14px; align-items: start; }}
        .summary-sidebar {{ position: sticky; top: 14px; display: grid; gap: 12px; }}
        .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
        .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
        .category-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 14px; }}

        .card, .meta-card, .category-card {{
            border: 1px solid #bfdbfe;
            border-radius: 12px;
            padding: 12px;
            background: #ffffff;
        }}

        .card {{ background: linear-gradient(160deg, #eff6ff 0%, #ffffff 100%); }}
        .card.is-warning {{ border-color: #fdba74; background: linear-gradient(160deg, #fff7ed 0%, #ffffff 100%); }}
        .card.is-ok {{ border-color: #86efac; background: linear-gradient(160deg, #f0fdf4 0%, #ffffff 100%); }}
        .card h3 {{ margin: 0; font-size: 0.95rem; color: #1e3a8a; }}
        .count {{ margin: 8px 0 0; font-size: 1.6rem; font-weight: 800; color: var(--accent); }}
        .card-note {{ margin: 6px 0 0; font-size: 0.83rem; color: #334155; }}

        .meta-label {{ font-size: 0.8rem; color: #475569; text-transform: uppercase; letter-spacing: 0.04em; }}
        .meta-value {{ margin-top: 6px; font-size: 0.95rem; color: #0f172a; line-height: 1.45; font-weight: 700; }}
        .category-title {{ font-size: 0.92rem; font-weight: 700; color: #0f4c81; }}
        .category-tools, .category-purpose {{ margin-top: 6px; font-size: 0.84rem; color: #334155; line-height: 1.45; }}

        .hint {{ margin-top: 12px; border: 1px solid #bae6fd; background: #f0f9ff; border-radius: 10px; padding: 10px; color: var(--muted); font-size: 0.92rem; }}
        .action-box {{ border: 1px solid #fdba74; background: #fff7ed; border-radius: 10px; padding: 12px; }}
        .action-box h3 {{ margin: 0 0 6px; color: #9a3412; font-size: 0.96rem; }}
        .action-box ul {{ margin: 0; padding-left: 18px; color: #7c2d12; font-size: 0.9rem; }}
        .section-lead {{ margin: 0 0 10px; color: #475569; line-height: 1.6; }}

        .table-wrap {{ margin-top: 10px; overflow-x: auto; border: 1px solid #dbeafe; border-radius: 12px; background: #ffffff; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; table-layout: fixed; }}
        th, td {{ border: 1px solid #dbeafe; padding: 8px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }}
        thead th {{ background: #e0f2fe; color: #0f172a; font-weight: 700; position: sticky; top: 0; z-index: 1; }}
        tbody tr:nth-child(even) {{ background: #f8fbff; }}

        pre {{ white-space: pre-wrap; margin: 8px 0 0; max-height: 260px; overflow: auto; border: 1px solid #dbeafe; border-radius: 8px; padding: 8px; background: #f8fbff; }}
        .json-pre {{ max-height: 340px; background: #f0f9ff; border: 1px solid #bae6fd; }}
        .json-meta {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; color: #0f4c81; font-size: 0.82rem; align-items: center; }}
        .tag {{ border: 1px solid #93c5fd; border-radius: 999px; padding: 2px 8px; background: #eff6ff; font-size: 0.78rem; color: #1e3a8a; }}
        .highlight-box {{ border: 1px solid #bae6fd; border-radius: 8px; background: #f0f9ff; padding: 8px; margin-bottom: 8px; }}
        .highlight-title {{ font-weight: 700; color: #0f4c81; margin-bottom: 4px; }}
        .highlight-box ul {{ margin: 0; padding-left: 18px; color: #0f4c81; font-size: 0.85rem; }}
        .tool-summary-empty {{ color: #64748b; font-size: 0.84rem; }}
        .tool-detail-meta {{ margin-bottom: 8px; padding: 8px; border: 1px solid #dbeafe; border-radius: 8px; background: #f8fbff; }}
        details > summary {{ cursor: pointer; font-weight: 600; color: #0f4c81; }}

        code {{ font-family: "Cascadia Code", "Consolas", monospace; font-size: 0.84rem; white-space: pre-wrap; overflow-wrap: anywhere; }}
        .badge {{ display: inline-flex; border-radius: 999px; font-size: 0.78rem; padding: 3px 9px; font-weight: 700; border: 1px solid transparent; }}
        .status-passed {{ color: var(--ok); border-color: #bbf7d0; background: #f0fdf4; }}
        .status-failed {{ color: var(--fail); border-color: #fecaca; background: #fef2f2; }}
        .status-unavailable {{ color: var(--warn); border-color: #fed7aa; background: #fff7ed; }}
        .empty {{ margin-top: 10px; border: 1px dashed #93c5fd; border-radius: 10px; padding: 10px; background: #f8fbff; color: #1e3a8a; }}
        .omitted {{ margin: 8px 0; border: 1px solid #fdba74; border-radius: 10px; background: #fff7ed; color: #7c2d12; padding: 8px; font-size: 0.9rem; }}

        @media (max-width: 720px) {{
            .wrap {{ padding: 12px; }}
            th, td {{ font-size: 0.84rem; }}
            .summary-layout {{ grid-template-columns: 1fr; }}
            .summary-sidebar {{ position: static; }}
        }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <section class=\"hero\">
            <h1>綜合檢查報告</h1>
            <p>generated_at: {html.escape(generated_at)}</p>
            <span class=\"overall\">overall: {html.escape(overall)}</span>
            <div class=\"tabs\" id=\"tabs\">
                <button class=\"tab-btn active\" data-target=\"summary\">概要</button>
                <button class=\"tab-btn\" data-target=\"code-quality\">程式碼品質</button>
                <button class=\"tab-btn\" data-target=\"duplicate\">重複程式碼</button>
                <button class=\"tab-btn\" data-target=\"hardcode\">UI 硬編碼</button>
                <button class=\"tab-btn\" data-target=\"comment\">註解整潔</button>
                <button class=\"tab-btn\" data-target=\"docstrings\">Docstring 檢查</button>
                <button class=\"tab-btn\" data-target=\"privacy\">隱私資訊</button>
            </div>
        </section>

        <section id=\"summary\" class=\"tab-panel active\">
            <h2>概要資訊</h2>
            <div class=\"summary-layout\">
                <div>
                    <div class=\"cards\">{cards_html}</div>
                    <div class=\"hint\">快速判讀：數字越大代表該項目需要處理的內容越多。先看程式碼品質與隱私資訊，再看其餘項目。</div>
                    {category_overview_html}
                </div>
                <div class=\"summary-sidebar\">
                    <div class=\"meta-grid\">{summary_meta_html}</div>
                    <div class=\"action-box\">
                        <h3>下一步建議</h3>
                        <ul>{action_html}</ul>
                    </div>
                </div>
            </div>
        </section>

        <section id=\"code-quality\" class=\"tab-panel\">
            <h2>程式碼品質（ruff / mypy / bandit / vulture / compileall）</h2>
            <p class=\"section-lead\">先看偵測出的問題，再視需要展開個別工具的命令與完整輸出。</p>
            {render_findings_table(code_quality_visible, code_quality_omitted)}
            <h3>工具執行明細</h3>
            <div class=\"table-wrap\"><table>
                <thead><tr><th>工具</th><th>狀態</th><th>耗時</th><th>摘要</th><th>詳情</th></tr></thead>
                <tbody>{render_tool_table(code_quality_tools)}</tbody>
            </table></div>
        </section>

        <section id=\"duplicate\" class=\"tab-panel\">
            <h2>重複程式碼（src）</h2>
            <p class=\"section-lead\">只保留需要處理的重複片段，避免整頁被長片段淹沒。</p>
            <p>{html.escape(duplicate_rule)}</p>
            {render_findings_table(duplicate_visible, duplicate_omitted)}
        </section>

        <section id=\"hardcode\" class=\"tab-panel\">
            <h2>UI 硬編碼檢查</h2>
            <p class=\"section-lead\">重點是找出直接寫死的尺寸、顏色或字體設定，優先收斂到共用 token。</p>
            <p>針對色碼與尺寸常數，建議改用 <code>src/utils/ui_utils.py</code> 的 token。</p>
            {render_findings_table(hardcode_visible, hardcode_omitted)}
        </section>

        <section id=\"comment\" class=\"tab-panel\">
            <h2>無用註解檢查</h2>
            <p class=\"section-lead\">只保留值得處理的殘留註解與被註解掉的舊程式碼，細節放在展開區。</p>
            <p>採用公信力工具：ruff (ERA) + eradicate。</p>
            {render_findings_table(comment_visible, comment_omitted)}
            <h3>工具執行明細</h3>
            <div class=\"table-wrap\"><table>
                <thead><tr><th>工具</th><th>狀態</th><th>耗時</th><th>摘要</th><th>詳情</th></tr></thead>
                <tbody>{render_tool_table(comment_tool_results)}</tbody>
            </table></div>
        </section>

        <section id=\"docstrings\" class=\"tab-panel\">
            <h2>Docstring 檢查（公開 API docstrings）</h2>
            <p class=\"section-lead\">檢查公開 module / class / function 是否包含 docstring，並驗證 Args / Returns 欄位。</p>
            {render_findings_table(docstrings_visible, docstrings_omitted)}
        </section>

        <section id=\"privacy\" class=\"tab-panel\">
            <h2>隱私與安全檢查（detect-secrets）</h2>
            <p class=\"section-lead\">優先看候選 secrets 與 regex 掃描結論，只有需要追查時再展開原始輸出。</p>
            {render_findings_table(privacy_visible, privacy_omitted)}
            <h3>工具執行明細</h3>
            <div class=\"table-wrap\"><table>
                <thead><tr><th>工具</th><th>狀態</th><th>耗時</th><th>摘要</th><th>詳情</th></tr></thead>
                <tbody>{render_tool_table(privacy_tool_results)}</tbody>
            </table></div>
        </section>
    </div>

    <script>
        const buttons = Array.from(document.querySelectorAll('.tab-btn'));
        const panels = Array.from(document.querySelectorAll('.tab-panel'));

        function activate(targetId) {{
            buttons.forEach((btn) => btn.classList.toggle('active', btn.dataset.target === targetId));
            panels.forEach((panel) => panel.classList.toggle('active', panel.id === targetId));
        }}

        buttons.forEach((btn) => btn.addEventListener('click', () => activate(btn.dataset.target)));
    </script>
</body>
</html>
"""


def main() -> int:
    max_details = MAX_DETAIL_ITEMS
    generated_at = datetime.now().isoformat(timespec="seconds")
    src_dir = REPO_ROOT / "src"
    operation_timings: list[tuple[str, float]] = []
    started_at = time.perf_counter()
    step_index = 0
    total_steps = 9
    def begin_step(title: str) -> tuple[int, float]:
        nonlocal step_index
        step_index += 1
        print(f"[Step {step_index}/{total_steps}] {title}...")
        return step_index, time.perf_counter()

    def end_step(idx: int, started: float, detail: str = "") -> None:
        elapsed = time.perf_counter() - started
        suffix = f" | {detail}" if detail else ""
        print(f"[Step {idx}/{total_steps}] done in {elapsed:.2f}s{suffix}")

    def remember_timing(name: str, duration_seconds: float) -> None:
        operation_timings.append((name, duration_seconds))

    idx, started = begin_step("程式碼品質檢查 (ruff/mypy/bandit/vulture/compileall)")
    code_quality_tools = collect_code_quality_results()
    for tool_result in code_quality_tools:
        remember_timing(f"tool:{tool_result.name}", tool_result.duration_seconds)
    code_quality_findings = summarize_tool_findings(code_quality_tools, "code_quality_tools")
    end_step(idx, started, f"issues={len(code_quality_findings.findings)}")

    idx, started = begin_step("跨檔 private callable 命名檢查")
    cross_file_callable_result, cross_file_callable_elapsed = run_timed_operation(
        "cross-file-private-callable-scan", lambda: collect_cross_file_private_callable_findings(REPO_ROOT)
    )
    remember_timing("task:cross-file-private-callable-scan", cross_file_callable_elapsed)
    end_step(idx, started, f"findings={len(cross_file_callable_result.findings)}")

    idx, started = begin_step("重複程式碼檢查 (src)")
    duplicate_result, duplicate_elapsed = run_timed_operation(
        "duplicate-code-scan", lambda: collect_duplicate_code_findings(src_dir)
    )
    remember_timing("task:duplicate-code-scan", duplicate_elapsed)
    end_step(idx, started, f"findings={len(duplicate_result.findings)}")

    idx, started = begin_step("UI 硬編碼檢查")
    hardcode_result, hardcode_elapsed = run_timed_operation(
        "ui-hardcode-scan", lambda: collect_ui_hardcode_findings(src_dir)
    )
    remember_timing("task:ui-hardcode-scan", hardcode_elapsed)
    end_step(idx, started, f"findings={len(hardcode_result.findings)}")

    idx, started = begin_step("無用註解檢查 (ruff ERA + eradicate)")
    comment_tool_results = collect_comment_tool_results()
    for tool_result in comment_tool_results:
        remember_timing(f"tool:{tool_result.name}", tool_result.duration_seconds)
    comment_result = summarize_tool_findings(comment_tool_results, "comment_tools")

    end_step(idx, started, f"findings={len(comment_result.findings)}")

    idx, started = begin_step("隱私與安全工具檢查 (detect-secrets)")
    privacy_tool_results = collect_privacy_tool_results()
    for tool_result in privacy_tool_results:
        remember_timing(f"tool:{tool_result.name}", tool_result.duration_seconds)
    end_step(idx, started, f"tool_runs={len(privacy_tool_results)}")

    privacy_tool_findings = summarize_tool_findings(privacy_tool_results, "privacy_tools")

    idx, started = begin_step("隱私規則掃描")
    privacy_regex_result, privacy_regex_elapsed = run_timed_operation(
        "privacy-regex-scan", lambda: collect_privacy_regex_findings(REPO_ROOT)
    )
    remember_timing("task:privacy-regex-scan", privacy_regex_elapsed)
    end_step(idx, started, f"findings={len(privacy_regex_result.findings)}")

    idx, started = begin_step("Docstring 檢查 (公開 API docstrings)")
    docstring_result, docstring_elapsed = run_timed_operation("docstring-scan", lambda: collect_docstring_section(src_dir))
    remember_timing("task:docstring-scan", docstring_elapsed)
    end_step(idx, started, f"findings={len(docstring_result.findings)}")

    output_html_path = HTML_REPORT_PATH
    output_html_path.parent.mkdir(parents=True, exist_ok=True)

    summary = {
        "code_quality": len(code_quality_findings.findings),
        "api_naming": len(cross_file_callable_result.findings),
        "duplicate_code": len(duplicate_result.findings),
        "ui_hardcode": len(hardcode_result.findings),
        "comment_hygiene": len(comment_result.findings),
        "docstrings": len(docstring_result.findings),
        "privacy": len(privacy_tool_findings.findings) + len(privacy_regex_result.findings),
    }

    idx, started = begin_step("產生並輸出 HTML 報告")
    html_text, html_elapsed = run_timed_operation(
        "build-html-report",
        lambda: build_html_report(
            generated_at=generated_at,
            code_quality_tools=code_quality_tools,
            code_quality_findings=code_quality_findings,
            cross_file_callable_result=cross_file_callable_result,
            duplicate_result=duplicate_result,
            hardcode_result=hardcode_result,
            comment_result=comment_result,
            docstring_result=docstring_result,
            comment_tool_results=comment_tool_results,
            privacy_tool_results=privacy_tool_results,
            privacy_regex_result=privacy_regex_result,
            max_details=max_details,
            total_runtime_seconds=time.perf_counter() - started_at,
        ),
    )
    remember_timing("task:build-html-report", html_elapsed)
    output_html_path.write_text(html_text, encoding="utf-8")
    end_step(idx, started, f"path={output_html_path}")

    total_elapsed = time.perf_counter() - started_at
    print("== 綜合檢查完成 ==")
    print(f"total_duration={format_duration(total_elapsed)}")
    print(f"html={output_html_path}")

    webbrowser.open(output_html_path.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
