import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

logging.basicConfig(level=logging.INFO, format="%(message)s")

QT_PLUGIN_FAMILY_EXCLUDES = (
    "iconengines",
    "printsupport",
    "tls",
)
QT_PLUGIN_DLL_EXCLUDES = (
    "PySide6/qt-plugins/imageformats/qgif.dll",
    "PySide6/qt-plugins/imageformats/qicns.dll",
    "PySide6/qt-plugins/imageformats/qjpeg.dll",
    "PySide6/qt-plugins/imageformats/qpdf.dll",
    "PySide6/qt-plugins/imageformats/qsvg.dll",
    "PySide6/qt-plugins/imageformats/qtga.dll",
    "PySide6/qt-plugins/imageformats/qtiff.dll",
    "PySide6/qt-plugins/imageformats/qwbmp.dll",
    "PySide6/qt-plugins/imageformats/qwebp.dll",
    "PySide6/qt-plugins/platforms/qdirect2d.dll",
    "PySide6/qt-plugins/platforms/qminimal.dll",
    "PySide6/qt-plugins/platforms/qoffscreen.dll",
)
QT_PLUGIN_INCLUDE_FAMILIES = "platforms,imageformats"
EXECUTABLE_NAME = "MinecraftServerManager.exe"


def print_error_and_exit(msg: str, exit_code: int = 1):
    logging.error(msg)
    sys.exit(exit_code)


def main():
    script_dir = Path(__file__).resolve().parents[0]
    project_root = script_dir.parents[0]
    os.chdir(project_root)

    logging.info("Step 0: 讀取版本資訊...")
    try:
        sys.path.insert(0, str(project_root))
        from src.utils import APP_ID, APP_NAME, APP_VERSION
    except Exception as e:
        print_error_and_exit(f"無法讀取版本資訊: {e}")

    logging.info(f"開始建置 {APP_NAME} v{APP_VERSION} (ID: {APP_ID})")

    logging.info("Step 1: 清理舊產物與鎖定進程...")
    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", EXECUTABLE_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    clean_dirs = ["build", "dist", "main.dist", "main.build"]
    for d in clean_dirs:
        target = project_root / d
        if target.exists():
            try:
                shutil.rmtree(target)
            except Exception as e:
                logging.warning(f"無法完全清除 {d}: {e}")

    logging.info("Step 2: 環境檢查與 uv 同步...")
    if shutil.which("uv") is None:
        logging.info("安裝 uv 工具...")
        subprocess.run([sys.executable, "-m", "pip", "install", "uv"], check=True)

    venv_path = project_root / ".venv"
    recreate_venv = os.environ.get("MSM_RECREATE_VENV", "").strip().lower() in {"1", "true", "yes", "y"}
    if recreate_venv and venv_path.exists():
        shutil.rmtree(venv_path, ignore_errors=True)

    if recreate_venv or not (venv_path / "pyvenv.cfg").exists():
        subprocess.run(["uv", "venv", ".venv", "--clear"], check=True)
    else:
        logging.info("重用既有 .venv；若需完全重建，請設定 MSM_RECREATE_VENV=1")
    subprocess.run(["uv", "sync", "--group", "build", "--frozen"], check=True)

    logging.info("Step 3: Nuitka 高效編譯...")
    python_exe = venv_path / "Scripts" / "python.exe"
    is_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    cpu_count = os.cpu_count() or 1
    if is_ci:
        num_jobs = cpu_count
        logging.info(f"偵測到 CI 環境，啟用全數 CPU 核心編譯 (jobs={num_jobs})")
    else:
        num_jobs = max(1, cpu_count - 1)
        logging.info(f"偵測到本地環境 (CPU 邏輯核心數: {cpu_count})，分配 jobs={num_jobs}")

    nuitka_args = [
        str(python_exe),
        "-m",
        "nuitka",
        "--quiet",
        "--onefile",
        "--enable-plugin=pyside6",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--output-dir=dist",
        f"--output-filename={EXECUTABLE_NAME}",
        "--include-package=src",
        "--include-data-dir=assets=assets",
        "--include-data-file=README.md=README.md",
        "--include-data-file=LICENSE=LICENSE",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
        "--windows-console-mode=attach",
        "--noinclude-qt-translations=1",
        "--nofollow-import-to=PySide6.QtWebEngineCore",
        "--nofollow-import-to=PySide6.QtWebEngineWidgets",
        "--nofollow-import-to=PySide6.QtMultimedia",
        "--nofollow-import-to=PySide6.QtSql",
        "--nofollow-import-to=PySide6.QtNetwork",
        "--nofollow-import-to=PySide6.QtPdf",
        f"--include-qt-plugins={QT_PLUGIN_INCLUDE_FAMILIES}",
        "--noinclude-setuptools-mode=nofollow",
        "--noinclude-pytest-mode=nofollow",
        "--noinclude-unittest-mode=nofollow",
        "--noinclude-pydoc-mode=nofollow",
        "--noinclude-IPython-mode=nofollow",
        *[f"--noinclude-qt-plugins={family}" for family in QT_PLUGIN_FAMILY_EXCLUDES],
        *[f"--noinclude-dlls={pattern}" for pattern in QT_PLUGIN_DLL_EXCLUDES],
        "--windows-icon-from-ico=assets/icon.ico",
        f"--file-version={APP_VERSION}",
        f"--product-version={APP_VERSION}",
        "--msvc=latest",
        "--lto=yes",
        f"--jobs={num_jobs}",
        "src/main.py",
    ]

    try:
        subprocess.run(nuitka_args, check=True, timeout=1800)
    except subprocess.CalledProcessError:
        print_error_and_exit("Nuitka 編譯失敗")

    logging.info("Step 4: 整理建置產出物目錄...")

    dist_dir = project_root / "dist"
    executable_path = dist_dir / EXECUTABLE_NAME

    if not executable_path.exists():
        print_error_and_exit(f"找不到已編譯的執行檔：{executable_path}")

    logging.info("========================================================")
    logging.info("              建置成功完成！")
    logging.info("========================================================")
    logging.info("")
    logging.info(f"執行檔：{executable_path.relative_to(project_root)}")
    logging.info("SHA-256 將由 GitHub Release asset 的 digest 提供")
    logging.info("========================================================")
    logging.info("")


if __name__ == "__main__":
    main()
