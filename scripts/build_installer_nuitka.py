import os
import sys
import shutil
import subprocess
import logging
from pathlib import Path

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

logging.basicConfig(level=logging.INFO, format="%(message)s")


def print_error_and_exit(msg: str, exit_code: int = 1):
    logging.error(msg)
    sys.exit(exit_code)


def main():
    script_dir = Path(__file__).resolve().parents[0]
    project_root = script_dir.parents[0]
    os.chdir(project_root)

    is_ci = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"

    logging.info("Step 0: 讀取版本資訊...")
    try:
        sys.path.insert(0, str(project_root))
        from src.version_info import APP_VERSION, APP_NAME, APP_ID
    except Exception as e:
        print_error_and_exit(f"無法讀取版本資訊: {e}")

    logging.info(f"開始建置 {APP_NAME} v{APP_VERSION} (ID: {APP_ID})")

    logging.info("Step 1: 清理舊產物與鎖定進程...")
    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", f"{APP_NAME}.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
    if not is_ci and venv_path.exists():
        shutil.rmtree(venv_path, ignore_errors=True)

    subprocess.run(["uv", "venv", ".venv", "--clear"], check=True)
    subprocess.run(["uv", "sync", "--group", "build", "--frozen"], check=True)

    logging.info("Step 3: Nuitka 高效編譯...")
    python_exe = venv_path / "Scripts" / "python.exe"
    num_jobs = max(1, int(os.cpu_count() or 1) - 1)

    nuitka_args = [
        str(python_exe),
        "-m",
        "nuitka",
        "--quiet",
        "--standalone",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--output-dir=dist",
        "--output-filename=MinecraftServerManager.exe",
        "--enable-plugin=tk-inter",
        "--include-package=src",
        "--include-data-dir=assets=assets",
        "--include-data-file=README.md=README.md",
        "--include-data-file=LICENSE=LICENSE",
        "--python-flag=no_docstrings",
        "--python-flag=no_asserts",
        "--windows-console-mode=attach",
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

    logging.info("Step 3.5: 整理建置產出物目錄...")

    dist_dir = project_root / "dist"
    dist_main_dist = dist_dir / "main.dist"
    dist_msm_dist = dist_dir / "MinecraftServerManager.dist"
    dist_target = dist_dir / "MinecraftServerManager"

    if dist_main_dist.exists():
        if dist_target.exists():
            shutil.rmtree(dist_target, ignore_errors=True)
        shutil.move(dist_main_dist, dist_target)
    elif dist_msm_dist.exists():
        if dist_target.exists():
            shutil.rmtree(dist_target, ignore_errors=True)
        shutil.move(dist_msm_dist, dist_target)

    if not dist_target.exists():
        print_error_and_exit(f"找不到 Nuitka 輸出目錄，預期 {dist_main_dist} 或 {dist_msm_dist}")

    if not (dist_target / "MinecraftServerManager.exe").exists():
        print_error_and_exit("找不到已編譯的執行檔")

    logging.info("Step 4: 封裝安裝程式 (Inno Setup)...")
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not Path(iscc).exists():
        print_error_and_exit("找不到 ISCC.exe")

    subprocess.run(
        [
            str(iscc),
            f"/DAppVersion={APP_VERSION}",
            f"/DAppName={APP_NAME}",
            f"/DAppId={APP_ID}",
            "scripts/installer.iss",
        ],
        check=True,
    )

    logging.info("Step 5: 封裝免安裝版...")
    pwsh = shutil.which("pwsh") or "powershell"
    subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/package-portable.ps1",
            "-Version",
            APP_VERSION,
        ],
        check=True,
    )

    logging.info("Step 6: 驗證建置產物...")
    dist_dir = project_root / "dist"
    setup_file = dist_dir / f"{APP_NAME}-Setup-{APP_VERSION}.exe"
    portable_file = dist_dir / f"MinecraftServerManager-v{APP_VERSION}-portable.zip"

    missing_artifacts = []
    if not setup_file.exists():
        missing_artifacts.append(f"安裝程式 ({setup_file.name})")
    if not portable_file.exists():
        missing_artifacts.append(f"免安裝版 ({portable_file.name})")

    if missing_artifacts:
        error_msg = "遺失建置產物：\n" + "\n".join([f" - {a}" for a in missing_artifacts])
        print_error_and_exit(error_msg)

    logging.info("========================================================")
    logging.info("              建置成功完成！")
    logging.info("========================================================")
    logging.info("")
    logging.info(f"安裝程式：{setup_file.relative_to(project_root)}")
    logging.info(f"免安裝版：{portable_file.relative_to(project_root)}")
    logging.info("SHA256 將由 GitHub Release asset 的 digest 提供")
    logging.info("========================================================")
    logging.info("")


if __name__ == "__main__":
    main()
