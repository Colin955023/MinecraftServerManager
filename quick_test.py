"""快速測試入口。

先檢查系統是否有 `uv`。如果沒有，就先透過 `pip` 安裝，再直接用
`uv run pytest -q tests/` 執行測試，用來在本機或 CI 上做基本健康檢查。

結果解讀：
- 退出碼 0：所有測試通過。
- 非 0：至少有一個測試失敗，或 pytest 發生錯誤。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_uv_path() -> str | None:
    uv_path = shutil.which("uv")
    if uv_path is not None:
        return uv_path

    script_name = "uv.exe"
    candidate = Path(sys.executable).resolve().with_name(script_name)
    if candidate.is_file():
        return str(candidate)
    return None


def main() -> int:
    uv_path = _resolve_uv_path()
    if uv_path is None:
        try:
            pip_result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "uv"],
                cwd=Path(__file__).resolve().parent,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            sys.stderr.write(f"quick_test failed to install uv via pip: {exc}\n")
            return 1

        if pip_result.returncode != 0:
            sys.stderr.write("quick_test failed to install uv via pip.\n")
            return int(pip_result.returncode)

        uv_path = _resolve_uv_path()
        if uv_path is None:
            sys.stderr.write("quick_test could not find uv after pip installation.\n")
            return 1

    project_root = Path(__file__).resolve().parent
    cmd = [
        str(uv_path),
        "run",
        "--with",
        "pytest>=9.0.2",
        "pytest",
        "-q",
        str(project_root / "tests"),
    ]
    try:
        completed = subprocess.run(cmd, cwd=project_root, check=False, shell=False)
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"quick_test failed to run pytest via uv: {exc}\n")
        return 1
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
